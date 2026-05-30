#!/usr/bin/env python3
"""Resolve paper inputs to the best available citation metadata.

The resolver accepts a title, DOI, DOI URL, arXiv URL, or arXiv identifier. It
queries public metadata APIs and prefers a peer-reviewed conference or journal
record over a preprint when the title evidence is strong enough.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any


CROSSREF_API = "https://api.crossref.org/v1/works"
OPENALEX_API = "https://api.openalex.org/works"
S2_API = "https://api.semanticscholar.org/graph/v1"
ARXIV_API = "https://export.arxiv.org/api/query"
DBLP_API = "https://dblp.org/search/publ/api"
ACL_ANTHOLOGY_URL = "https://aclanthology.org"

DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
ARXIV_RE = re.compile(
    r"(?:arxiv:|arxiv\.org/(?:abs|pdf)/)?"
    r"(?P<id>(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?)",
    re.IGNORECASE,
)
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"


REVIEWED_CROSSREF_TYPES = {
    "journal-article",
    "proceedings-article",
    "book-chapter",
    "book",
    "monograph",
}
PREPRINT_CROSSREF_TYPES = {"posted-content", "dissertation", "report"}
REVIEWED_S2_TYPES = {"JournalArticle", "Conference", "Review", "Book", "BookChapter"}
PREPRINT_S2_TYPES = {"Preprint"}
PUBLISHERISH_PREPRINT_HINTS = {"posted-content", "preprint", "repository", "report", "dissertation"}


@dataclass
class Candidate:
    source: str
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    published_date: str = ""
    venue: str = ""
    publisher: str = ""
    work_type: str = ""
    doi: str = ""
    arxiv_id: str = ""
    url: str = ""
    pages: str = ""
    volume: str = ""
    issue: str = ""
    container_title: str = ""
    reviewed: bool = False
    preprint: bool = False
    raw_id: str = ""
    evidence: list[str] = field(default_factory=list)
    official_bibtex: str = ""
    official_bibtex_source: str = ""
    score: float = 0.0
    similarity: float = 0.0

    def citation_venue(self) -> str:
        return self.venue or self.container_title

    def stable_url(self) -> str:
        if self.doi:
            return "https://doi.org/" + self.doi
        if self.url:
            return self.url
        if self.arxiv_id:
            return "https://arxiv.org/abs/" + strip_arxiv_version(self.arxiv_id)
        return ""


def strip_arxiv_version(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", arxiv_id or "", flags=re.IGNORECASE)


def clean_doi(doi: str) -> str:
    doi = doi.strip()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    doi = doi.rstrip(").,;")
    return doi.lower()


def find_doi(value: str) -> str:
    match = DOI_RE.search(value or "")
    return clean_doi(match.group(0)) if match else ""


def is_arxiv_doi(doi: str) -> bool:
    return doi.lower().startswith("10.48550/arxiv.")


def arxiv_id_from_text(value: str) -> str:
    value = value or ""
    abs_match = re.search(r"abs/(\d{4}\.\d{4,5}(?:v\d+)?)", value, re.IGNORECASE)
    if abs_match:
        return abs_match.group(1)
    doi = find_doi(value)
    if is_arxiv_doi(doi):
        return doi.split("arxiv.", 1)[-1]
    match = ARXIV_RE.search(value)
    return match.group("id") if match else ""


def detect_input(value: str) -> dict[str, str]:
    value = value.strip()
    doi_match = DOI_RE.search(value)
    if doi_match:
        return {"kind": "doi", "value": clean_doi(doi_match.group(0)), "raw": value}

    arxiv_match = ARXIV_RE.search(value)
    if arxiv_match and ("arxiv" in value.lower() or re.fullmatch(ARXIV_RE, value)):
        return {"kind": "arxiv", "value": arxiv_match.group("id"), "raw": value}

    return {"kind": "title", "value": normalize_space(value), "raw": value}


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_title(value: str) -> str:
    value = value.lower()
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return normalize_space(value)


def title_similarity(a: str, b: str) -> float:
    left = normalize_title(a)
    right = normalize_title(b)
    if not left or not right:
        return 0.0
    seq = SequenceMatcher(None, left, right).ratio()
    left_tokens = left.split()
    right_tokens = right.split()
    token_seq = SequenceMatcher(None, " ".join(sorted(left_tokens)), " ".join(sorted(right_tokens))).ratio()
    left_set = set(left_tokens)
    right_set = set(right_tokens)
    jaccard = len(left_set & right_set) / max(len(left_set | right_set), 1)
    return max(seq, token_seq, jaccard)


def family_name(name: str) -> str:
    name = normalize_space(name)
    if not name:
        return ""
    if "," in name:
        family = name.split(",", 1)[0]
    else:
        family = name.split()[-1]
    return normalize_title(family)


def author_overlap_score(candidate_authors: list[str], anchor_authors: list[str]) -> float:
    candidate_names = {family_name(author) for author in candidate_authors if family_name(author)}
    anchor_names = {family_name(author) for author in anchor_authors if family_name(author)}
    if not candidate_names or not anchor_names:
        return 0.0
    return len(candidate_names & anchor_names) / max(min(len(candidate_names), len(anchor_names)), 1)


def http_json(url: str, params: dict[str, Any] | None, headers: dict[str, str], timeout: float) -> Any:
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def http_text(url: str, params: dict[str, Any] | None, headers: dict[str, str], timeout: float) -> str:
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8")


def fetch_url_text(url: str, headers: dict[str, str], timeout: float) -> str:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8")


def safe_call(errors: list[str], label: str, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except urllib.error.HTTPError as exc:
        errors.append(f"{label}: HTTP {exc.code}")
    except urllib.error.URLError as exc:
        errors.append(f"{label}: {exc.reason}")
    except TimeoutError:
        errors.append(f"{label}: timeout")
    except Exception as exc:  # noqa: BLE001 - CLI should keep partial results.
        errors.append(f"{label}: {exc}")
    return None


def first_text(value: Any) -> str:
    if isinstance(value, list) and value:
        return normalize_space(str(value[0]))
    if value is None:
        return ""
    return normalize_space(str(value))


def parse_crossref_date(item: dict[str, Any]) -> tuple[int | None, str]:
    for key in ("published-print", "published-online", "published", "issued", "created"):
        parts = item.get(key, {}).get("date-parts")
        if parts and parts[0]:
            nums = [int(x) for x in parts[0] if isinstance(x, int)]
            if nums:
                year = nums[0]
                date = "-".join(f"{x:02d}" if idx else str(x) for idx, x in enumerate(nums[:3]))
                return year, date
    return None, ""


def crossref_author_name(author: dict[str, Any]) -> str:
    family = normalize_space(author.get("family", ""))
    given = normalize_space(author.get("given", ""))
    if family and given:
        return f"{given} {family}"
    return family or given or normalize_space(author.get("name", ""))


def crossref_to_candidate(item: dict[str, Any]) -> Candidate:
    year, published_date = parse_crossref_date(item)
    work_type = normalize_space(item.get("type", ""))
    container = first_text(item.get("container-title"))
    event = item.get("event") or {}
    event_name = normalize_space(event.get("name", ""))
    venue = event_name or container or first_text(item.get("short-container-title"))
    doi = clean_doi(item.get("DOI", "")) if item.get("DOI") else ""
    reviewed = work_type in REVIEWED_CROSSREF_TYPES
    preprint = work_type in PREPRINT_CROSSREF_TYPES or work_type == "posted-content"
    authors = [crossref_author_name(author) for author in item.get("author", [])]
    authors = [author for author in authors if author]
    candidate = Candidate(
        source="crossref",
        title=first_text(item.get("title")),
        authors=authors,
        year=year,
        published_date=published_date,
        venue=venue,
        publisher=normalize_space(item.get("publisher", "")),
        work_type=work_type,
        doi=doi,
        url=normalize_space(item.get("URL", "")),
        pages=normalize_space(item.get("page", "")),
        volume=normalize_space(item.get("volume", "")),
        issue=normalize_space(item.get("issue", "")),
        container_title=container,
        reviewed=reviewed,
        preprint=preprint,
        raw_id=doi,
    )
    if reviewed:
        candidate.evidence.append(f"Crossref type is {work_type}")
    if preprint:
        candidate.evidence.append(f"Crossref type is {work_type}, treated as preprint-like")
    if doi:
        candidate.evidence.append("DOI present")
    if venue:
        candidate.evidence.append(f"Venue/container present: {venue}")
    return candidate


def query_crossref_by_doi(doi: str, headers: dict[str, str], timeout: float, errors: list[str]) -> list[Candidate]:
    data = safe_call(errors, "Crossref DOI lookup", http_json, f"{CROSSREF_API}/{urllib.parse.quote(doi)}", None, headers, timeout)
    if not data:
        return []
    item = data.get("message", {})
    return [crossref_to_candidate(item)] if item else []


def query_crossref_by_title(title: str, headers: dict[str, str], timeout: float, errors: list[str], rows: int) -> list[Candidate]:
    params = {
        "query.title": title,
        "rows": rows,
        "sort": "score",
        "order": "desc",
    }
    data = safe_call(errors, "Crossref title search", http_json, CROSSREF_API, params, headers, timeout)
    if not data:
        return []
    return [crossref_to_candidate(item) for item in data.get("message", {}).get("items", [])]


def openalex_to_candidate(item: dict[str, Any]) -> Candidate:
    primary = item.get("primary_location") or {}
    source = primary.get("source") or {}
    biblio = item.get("biblio") or {}
    ids = item.get("ids") or {}
    doi = clean_doi(item.get("doi", "") or ids.get("doi", "")) if (item.get("doi") or ids.get("doi")) else ""
    venue = normalize_space(source.get("display_name", ""))
    work_type = normalize_space(item.get("type_crossref") or item.get("type") or "")
    year = item.get("publication_year")
    try:
        year = int(year) if year else None
    except (TypeError, ValueError):
        year = None
    authors = []
    for authorship in item.get("authorships", [])[:20]:
        author = authorship.get("author") or {}
        name = normalize_space(author.get("display_name", ""))
        if name:
            authors.append(name)
    reviewed = bool(doi and venue and work_type not in PREPRINT_CROSSREF_TYPES)
    if work_type in REVIEWED_CROSSREF_TYPES or work_type in {"article", "book-chapter", "book"}:
        reviewed = True
    preprint = work_type in PREPRINT_CROSSREF_TYPES or "preprint" in work_type.lower()
    candidate = Candidate(
        source="openalex",
        title=normalize_space(item.get("display_name", "")),
        authors=authors,
        year=year,
        published_date=normalize_space(item.get("publication_date", "")),
        venue=venue,
        publisher=normalize_space(source.get("host_organization_name", "")),
        work_type=work_type,
        doi=doi,
        url=normalize_space(primary.get("landing_page_url") or ids.get("openalex", "")),
        pages=normalize_space(biblio.get("first_page", "")),
        volume=normalize_space(biblio.get("volume", "")),
        issue=normalize_space(biblio.get("issue", "")),
        container_title=venue,
        reviewed=reviewed,
        preprint=preprint,
        raw_id=normalize_space(item.get("id", "")),
    )
    if reviewed:
        candidate.evidence.append(f"OpenAlex type/source suggests citable venue: {work_type or venue}")
    if preprint:
        candidate.evidence.append(f"OpenAlex type is {work_type}, treated as preprint-like")
    if doi:
        candidate.evidence.append("DOI present")
    if venue:
        candidate.evidence.append(f"Venue/source present: {venue}")
    return candidate


def query_openalex_by_doi(doi: str, headers: dict[str, str], timeout: float, errors: list[str]) -> list[Candidate]:
    data = safe_call(errors, "OpenAlex DOI lookup", http_json, f"{OPENALEX_API}/doi:{urllib.parse.quote(doi)}", None, headers, timeout)
    if not data:
        return []
    return [openalex_to_candidate(data)]


def query_openalex_by_title(title: str, headers: dict[str, str], timeout: float, errors: list[str], rows: int) -> list[Candidate]:
    params = {"search": title, "per-page": rows}
    data = safe_call(errors, "OpenAlex title search", http_json, OPENALEX_API, params, headers, timeout)
    if not data:
        return []
    return [openalex_to_candidate(item) for item in data.get("results", [])]


def s2_to_candidate(item: dict[str, Any]) -> Candidate:
    external = item.get("externalIds") or {}
    publication_types = item.get("publicationTypes") or []
    venue_info = item.get("publicationVenue") or {}
    journal = item.get("journal") or {}
    doi = clean_doi(external.get("DOI", "")) if external.get("DOI") else ""
    arxiv_id = normalize_space(external.get("ArXiv", ""))
    venue = normalize_space(venue_info.get("name", "") or journal.get("name", "") or item.get("venue", ""))
    work_type = ", ".join(publication_types)
    year = item.get("year")
    try:
        year = int(year) if year else None
    except (TypeError, ValueError):
        year = None
    authors = [normalize_space(author.get("name", "")) for author in item.get("authors", [])]
    authors = [author for author in authors if author]
    reviewed = bool(set(publication_types) & REVIEWED_S2_TYPES)
    preprint = bool(set(publication_types) & PREPRINT_S2_TYPES)
    if not reviewed and doi and venue and not preprint:
        reviewed = True
    candidate = Candidate(
        source="semantic-scholar",
        title=normalize_space(item.get("title", "")),
        authors=authors,
        year=year,
        published_date=normalize_space(item.get("publicationDate", "")),
        venue=venue,
        work_type=work_type,
        doi=doi,
        arxiv_id=arxiv_id,
        url=normalize_space(item.get("url", "")),
        volume=normalize_space(journal.get("volume", "")),
        pages=normalize_space(journal.get("pages", "")),
        container_title=venue,
        reviewed=reviewed,
        preprint=preprint,
        raw_id=normalize_space(item.get("paperId", "")),
    )
    if reviewed:
        candidate.evidence.append(f"Semantic Scholar publication type: {work_type or 'venue-backed record'}")
    if preprint:
        candidate.evidence.append("Semantic Scholar marks record as preprint")
    if doi:
        candidate.evidence.append("DOI present")
    if arxiv_id:
        candidate.evidence.append(f"arXiv ID present: {arxiv_id}")
    if venue:
        candidate.evidence.append(f"Venue present: {venue}")
    return candidate


def acl_anthology_id(candidate: Candidate) -> str:
    haystack = " ".join([candidate.doi, candidate.url, candidate.raw_id])
    doi_match = re.search(r"10\.18653/v1/([A-Za-z]\d{2}-\d{4})", haystack, re.IGNORECASE)
    if doi_match:
        return doi_match.group(1).upper()
    url_match = re.search(r"aclanthology\.org/([A-Za-z]\d{2}-\d{4})/?", haystack, re.IGNORECASE)
    if url_match:
        return url_match.group(1).upper()
    return ""


def maybe_attach_official_bibtex(candidate: Candidate, headers: dict[str, str], timeout: float, errors: list[str]) -> None:
    if candidate.official_bibtex:
        return
    acl_id = acl_anthology_id(candidate)
    if not acl_id:
        return
    url = f"{ACL_ANTHOLOGY_URL}/{acl_id}.bib"
    text = safe_call(errors, "ACL Anthology BibTeX lookup", fetch_url_text, url, headers, timeout)
    if not text:
        return
    text = text.strip()
    if text.startswith("@"):
        candidate.official_bibtex = text
        candidate.official_bibtex_source = url
        evidence = f"Official BibTeX from ACL Anthology: {url}"
        if evidence not in candidate.evidence:
            candidate.evidence.append(evidence)


def listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def dblp_authors(info: dict[str, Any]) -> list[str]:
    authors = info.get("authors") or {}
    result = []
    for author in listify(authors.get("author")):
        if isinstance(author, dict):
            name = html.unescape(normalize_space(author.get("text", "")))
        else:
            name = html.unescape(normalize_space(str(author)))
        if name:
            result.append(re.sub(r"\s+\d{4}$", "", name))
    return result


def dblp_to_candidate(hit: dict[str, Any]) -> Candidate:
    info = hit.get("info") or {}
    title = html.unescape(normalize_space(info.get("title", ""))).rstrip(".")
    work_type = html.unescape(normalize_space(info.get("type", "")))
    ee = normalize_space(info.get("ee", ""))
    doi = clean_doi(info.get("doi", "")) if info.get("doi") else find_doi(ee)
    venue = html.unescape(normalize_space(info.get("venue", "")))
    year = info.get("year")
    try:
        year = int(year) if year else None
    except (TypeError, ValueError):
        year = None
    lower_type = work_type.lower()
    reviewed = "conference" in lower_type or "journal" in lower_type or bool(doi and venue and venue != "CoRR")
    preprint = venue == "CoRR" or "informal" in lower_type
    arxiv_id = arxiv_id_from_text(normalize_space(info.get("volume", ""))) or arxiv_id_from_text(ee)
    candidate = Candidate(
        source="dblp",
        title=title,
        authors=dblp_authors(info),
        year=year,
        venue=venue,
        work_type=work_type,
        doi=doi,
        arxiv_id=arxiv_id,
        url=ee or normalize_space(info.get("url", "")),
        pages=normalize_space(info.get("pages", "")),
        volume=normalize_space(info.get("volume", "")),
        reviewed=reviewed and not preprint,
        preprint=preprint,
        raw_id=normalize_space(info.get("key", "")),
    )
    if candidate.reviewed:
        candidate.evidence.append(f"DBLP type/venue suggests reviewed publication: {work_type}, {venue}")
    if candidate.preprint:
        candidate.evidence.append(f"DBLP venue/type is preprint-like: {venue or work_type}")
    if doi:
        candidate.evidence.append("DOI present")
    if venue:
        candidate.evidence.append(f"Venue present: {venue}")
    return candidate


def query_dblp_by_title(title: str, headers: dict[str, str], timeout: float, errors: list[str], rows: int) -> list[Candidate]:
    params = {"q": title, "format": "json", "h": max(rows, 10)}
    data = safe_call(errors, "DBLP title search", http_json, DBLP_API, params, headers, timeout)
    if not data:
        return []
    hits = data.get("result", {}).get("hits", {}).get("hit")
    return [dblp_to_candidate(hit) for hit in listify(hits) if isinstance(hit, dict)]


def s2_fields() -> str:
    return ",".join(
        [
            "paperId",
            "title",
            "authors",
            "year",
            "venue",
            "publicationVenue",
            "publicationTypes",
            "publicationDate",
            "externalIds",
            "url",
            "journal",
        ]
    )


def query_s2_by_id(kind: str, value: str, headers: dict[str, str], timeout: float, errors: list[str]) -> list[Candidate]:
    if kind == "doi":
        paper_id = "DOI:" + value
    elif kind == "arxiv":
        paper_id = "ARXIV:" + strip_arxiv_version(value)
    else:
        return []
    url = f"{S2_API}/paper/{urllib.parse.quote(paper_id, safe=':')}"
    data = safe_call(errors, "Semantic Scholar ID lookup", http_json, url, {"fields": s2_fields()}, headers, timeout)
    if not data:
        return []
    return [s2_to_candidate(data)]


def query_s2_by_title(title: str, headers: dict[str, str], timeout: float, errors: list[str], rows: int) -> list[Candidate]:
    params = {"query": title, "limit": rows, "fields": s2_fields()}
    data = safe_call(errors, "Semantic Scholar title search", http_json, f"{S2_API}/paper/search", params, headers, timeout)
    if not data:
        return []
    return [s2_to_candidate(item) for item in data.get("data", [])]


def parse_arxiv_feed(xml_text: str) -> list[Candidate]:
    root = ET.fromstring(xml_text)
    candidates = []
    for entry in root.findall(f"{ATOM}entry"):
        raw_id = entry.findtext(f"{ATOM}id", default="")
        arxiv_id = raw_id.rstrip("/").split("/")[-1]
        title = normalize_space(entry.findtext(f"{ATOM}title", default=""))
        authors = []
        for author in entry.findall(f"{ATOM}author"):
            name = normalize_space(author.findtext(f"{ATOM}name", default=""))
            if name:
                authors.append(name)
        published = normalize_space(entry.findtext(f"{ATOM}published", default=""))
        year = None
        if published[:4].isdigit():
            year = int(published[:4])
        doi = normalize_space(entry.findtext(f"{ARXIV_NS}doi", default=""))
        journal_ref = normalize_space(entry.findtext(f"{ARXIV_NS}journal_ref", default=""))
        primary_category = entry.find(f"{ARXIV_NS}primary_category")
        primary_class = ""
        if primary_category is not None:
            primary_class = primary_category.attrib.get("term", "")
        candidate = Candidate(
            source="arxiv",
            title=title,
            authors=authors,
            year=year,
            published_date=published[:10],
            venue=journal_ref,
            work_type="preprint",
            doi=clean_doi(doi) if doi else "",
            arxiv_id=arxiv_id,
            url=raw_id,
            reviewed=bool(journal_ref and doi),
            preprint=True,
            raw_id=arxiv_id,
        )
        candidate.evidence.append(f"arXiv record {arxiv_id}")
        if doi:
            candidate.evidence.append("arXiv metadata includes DOI")
        if journal_ref:
            candidate.evidence.append(f"arXiv journal reference: {journal_ref}")
        if primary_class:
            candidate.evidence.append(f"arXiv primary class: {primary_class}")
        candidates.append(candidate)
    return candidates


def query_arxiv_by_id(arxiv_id: str, headers: dict[str, str], timeout: float, errors: list[str]) -> list[Candidate]:
    params = {"id_list": arxiv_id, "max_results": 1}
    text = safe_call(errors, "arXiv ID lookup", http_text, ARXIV_API, params, headers, timeout)
    if not text:
        return []
    return parse_arxiv_feed(text)


def query_arxiv_by_title(title: str, headers: dict[str, str], timeout: float, errors: list[str], rows: int) -> list[Candidate]:
    escaped_title = title.replace('"', "")
    params = {
        "search_query": f'ti:"{escaped_title}"',
        "start": 0,
        "max_results": rows,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    text = safe_call(errors, "arXiv title search", http_text, ARXIV_API, params, headers, timeout)
    if not text:
        return []
    return parse_arxiv_feed(text)


def dedupe_candidates(candidates: list[Candidate]) -> list[Candidate]:
    merged: dict[str, Candidate] = {}
    for candidate in candidates:
        key = ""
        if candidate.doi and not is_arxiv_doi(candidate.doi):
            key = "doi:" + candidate.doi
        elif candidate.arxiv_id:
            key = "arxiv:" + strip_arxiv_version(candidate.arxiv_id).lower()
        elif candidate.doi:
            key = "doi:" + candidate.doi
        elif candidate.title:
            venue_key = normalize_title(candidate.citation_venue())
            key = "title:" + normalize_title(candidate.title) + "|venue:" + venue_key
        else:
            key = f"{candidate.source}:{candidate.raw_id}"

        existing = merged.get(key)
        if not existing:
            merged[key] = candidate
            continue

        existing.source = existing.source + "+" + candidate.source
        existing.authors = existing.authors or candidate.authors
        existing.year = existing.year or candidate.year
        existing.published_date = existing.published_date or candidate.published_date
        existing.venue = existing.venue or candidate.venue
        existing.publisher = existing.publisher or candidate.publisher
        existing.work_type = existing.work_type or candidate.work_type
        if existing.work_type == "preprint" and candidate.work_type and not candidate.preprint:
            existing.work_type = candidate.work_type
        existing.doi = existing.doi or candidate.doi
        existing.arxiv_id = existing.arxiv_id or candidate.arxiv_id
        existing.url = existing.url or candidate.url
        existing.pages = existing.pages or candidate.pages
        existing.volume = existing.volume or candidate.volume
        existing.issue = existing.issue or candidate.issue
        existing.container_title = existing.container_title or candidate.container_title
        existing.reviewed = existing.reviewed or candidate.reviewed
        existing.preprint = existing.preprint and candidate.preprint
        existing.evidence = sorted(set(existing.evidence + candidate.evidence))
        existing.official_bibtex = existing.official_bibtex or candidate.official_bibtex
        existing.official_bibtex_source = existing.official_bibtex_source or candidate.official_bibtex_source
    return list(merged.values())


def has_peer_review_evidence(candidate: Candidate) -> bool:
    work_type = (candidate.work_type or "").lower()
    venue = (candidate.citation_venue() or "").lower()
    if candidate.preprint or any(hint in work_type for hint in PUBLISHERISH_PREPRINT_HINTS):
        return False
    if "arxiv" in venue or "repository" in venue:
        return False
    if candidate.reviewed and not candidate.preprint:
        return True
    if "conference" in work_type or "journal" in work_type:
        return True
    if candidate.work_type in REVIEWED_CROSSREF_TYPES:
        return True
    if candidate.source.startswith("dblp") and candidate.reviewed:
        return True
    if candidate.doi and candidate.citation_venue() and work_type not in PUBLISHERISH_PREPRINT_HINTS:
        return True
    return False


def is_same_arxiv(candidate: Candidate, arxiv_id: str) -> bool:
    return strip_arxiv_version(candidate.arxiv_id).lower() == strip_arxiv_version(arxiv_id).lower()


def score_candidates(
    candidates: list[Candidate],
    query_title: str,
    input_kind: str,
    input_value: str,
    anchor_authors: list[str] | None = None,
) -> list[Candidate]:
    anchor_authors = anchor_authors or []
    for candidate in candidates:
        if input_kind == "doi" and candidate.doi == input_value:
            similarity = 1.0
        elif input_kind == "arxiv" and strip_arxiv_version(candidate.arxiv_id).lower() == strip_arxiv_version(input_value).lower():
            similarity = 1.0
        else:
            similarity = title_similarity(query_title, candidate.title)

        score = similarity * 100.0
        strong_title = similarity >= 0.78
        if candidate.reviewed and strong_title:
            score += 28.0
        if candidate.doi:
            score += 12.0
        if candidate.citation_venue():
            score += 8.0
        if candidate.preprint and not candidate.reviewed:
            score -= 18.0
        if candidate.source.startswith("crossref") and candidate.reviewed and strong_title:
            score += 8.0
        if candidate.source.startswith("openalex") and candidate.reviewed and strong_title:
            score += 4.0
        if candidate.source.startswith("dblp") and candidate.reviewed and strong_title:
            score += 10.0
        if not strong_title and candidate.reviewed:
            score -= 20.0
        if input_kind == "arxiv" and is_same_arxiv(candidate, input_value):
            score += 14.0
        if input_kind == "arxiv" and candidate.preprint and not has_peer_review_evidence(candidate):
            score += 10.0
        if anchor_authors:
            overlap = author_overlap_score(candidate.authors, anchor_authors)
            if overlap:
                score += 22.0 * overlap
                candidate.evidence.append(f"Author overlap with preprint anchor: {overlap:.2f}")
            elif similarity >= 0.95 and candidate.authors:
                score -= 55.0
                candidate.evidence.append("Exact or near-exact title but no author overlap with preprint anchor")
        if candidate.year:
            score += min(max(candidate.year - 1990, 0), 40) / 20.0
        candidate.similarity = round(similarity, 4)
        candidate.score = round(score, 4)
    return sorted(candidates, key=lambda item: item.score, reverse=True)


def choose_recommended(candidates: list[Candidate], input_kind: str, anchor_authors: list[str] | None = None) -> Candidate | None:
    if not candidates:
        return None
    if input_kind == "doi":
        return candidates[0]
    anchor_authors = anchor_authors or []
    reviewed = [
        item
        for item in candidates
        if has_peer_review_evidence(item)
        and item.similarity >= 0.78
        and (not anchor_authors or not item.authors or author_overlap_score(item.authors, anchor_authors) > 0)
    ]
    if reviewed:
        return reviewed[0]
    anchored_arxiv = [
        item
        for item in candidates
        if item.source.startswith("arxiv")
        and item.similarity >= 0.95
        and (not anchor_authors or author_overlap_score(item.authors, anchor_authors) > 0)
    ]
    if anchored_arxiv:
        return anchored_arxiv[0]
    strong = [item for item in candidates if item.similarity >= 0.82]
    if strong:
        return strong[0]
    return candidates[0]


def build_headers(args: argparse.Namespace) -> dict[str, str]:
    headers = {"User-Agent": args.user_agent}
    if args.s2_api_key or os.getenv("S2_API_KEY"):
        headers["x-api-key"] = args.s2_api_key or os.getenv("S2_API_KEY", "")
    return headers


def build_crossref_headers(args: argparse.Namespace) -> dict[str, str]:
    agent = args.user_agent
    mailto = args.mailto or os.getenv("CROSSREF_MAILTO") or os.getenv("OPENALEX_MAILTO")
    if mailto:
        agent = f"{agent} (mailto:{mailto})"
    return {"User-Agent": agent}


def anchor_query(title: str, authors: list[str], limit: int = 4) -> str:
    names = [family_name(author) for author in authors if family_name(author)]
    names = [name for name in names if name]
    return normalize_space(title + " " + " ".join(names[:limit]))


def resolve(query: str, args: argparse.Namespace) -> dict[str, Any]:
    detected = detect_input(query)
    errors: list[str] = []
    candidates: list[Candidate] = []
    headers = build_headers(args)
    crossref_headers = build_crossref_headers(args)

    mailto = args.mailto or os.getenv("OPENALEX_MAILTO") or os.getenv("CROSSREF_MAILTO")
    openalex_headers = {"User-Agent": crossref_headers["User-Agent"]}

    query_title = detected["value"]
    seed_arxiv: Candidate | None = None
    anchor_authors: list[str] = []

    if detected["kind"] == "doi":
        doi = detected["value"]
        candidates.extend(query_crossref_by_doi(doi, crossref_headers, args.timeout, errors))
        candidates.extend(query_openalex_by_doi(doi, openalex_headers, args.timeout, errors))
        candidates.extend(query_s2_by_id("doi", doi, headers, args.timeout, errors))
        query_title = next((item.title for item in candidates if item.title), doi)

    elif detected["kind"] == "arxiv":
        arxiv_id = detected["value"]
        arxiv_candidates = query_arxiv_by_id(arxiv_id, headers, args.timeout, errors)
        candidates.extend(arxiv_candidates)
        if arxiv_candidates:
            seed_arxiv = arxiv_candidates[0]
            query_title = seed_arxiv.title or arxiv_id
            anchor_authors = seed_arxiv.authors
            if seed_arxiv.doi:
                candidates.extend(query_crossref_by_doi(seed_arxiv.doi, crossref_headers, args.timeout, errors))
                candidates.extend(query_openalex_by_doi(seed_arxiv.doi, openalex_headers, args.timeout, errors))
        candidates.extend(query_s2_by_id("arxiv", arxiv_id, headers, args.timeout, errors))
        if query_title and query_title != arxiv_id:
            candidates.extend(query_crossref_by_title(query_title, crossref_headers, args.timeout, errors, args.max_results))
            candidates.extend(query_openalex_by_title(query_title, openalex_headers, args.timeout, errors, args.max_results))
            candidates.extend(query_dblp_by_title(query_title, headers, args.timeout, errors, args.max_results))
            if anchor_authors:
                candidates.extend(query_dblp_by_title(anchor_query(query_title, anchor_authors), headers, args.timeout, errors, args.max_results))
            candidates.extend(query_s2_by_title(query_title, headers, args.timeout, errors, args.max_results))

    else:
        title = detected["value"]
        candidates.extend(query_crossref_by_title(title, crossref_headers, args.timeout, errors, args.max_results))
        candidates.extend(query_openalex_by_title(title, openalex_headers, args.timeout, errors, args.max_results))
        candidates.extend(query_dblp_by_title(title, headers, args.timeout, errors, args.max_results))
        candidates.extend(query_s2_by_title(title, headers, args.timeout, errors, args.max_results))
        arxiv_candidates = query_arxiv_by_title(title, headers, args.timeout, errors, min(args.max_results, 3))
        candidates.extend(arxiv_candidates)
        exact_arxiv = next((item for item in arxiv_candidates if title_similarity(title, item.title) >= 0.95), None)
        if exact_arxiv:
            seed_arxiv = exact_arxiv
            anchor_authors = exact_arxiv.authors
            candidates.extend(query_dblp_by_title(anchor_query(title, anchor_authors), headers, args.timeout, errors, args.max_results))
            candidates.extend(query_s2_by_id("arxiv", exact_arxiv.arxiv_id, headers, args.timeout, errors))

    candidates = dedupe_candidates(candidates)
    candidates = score_candidates(candidates, query_title, detected["kind"], detected["value"], anchor_authors)
    recommended = choose_recommended(candidates, detected["kind"], anchor_authors)

    if seed_arxiv and recommended and recommended.arxiv_id == "":
        recommended.arxiv_id = seed_arxiv.arxiv_id
    if recommended:
        maybe_attach_official_bibtex(recommended, headers, args.timeout, errors)

    result = {
        "input": detected,
        "query_title": query_title,
        "recommended": candidate_to_dict(recommended) if recommended else None,
        "citations": build_citations(recommended) if recommended else {},
        "candidates": [candidate_to_dict(item) for item in candidates],
        "errors": errors,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    return result


def candidate_to_dict(candidate: Candidate | None) -> dict[str, Any] | None:
    if candidate is None:
        return None
    return {
        "source": candidate.source,
        "title": candidate.title,
        "authors": candidate.authors,
        "year": candidate.year,
        "published_date": candidate.published_date,
        "venue": candidate.venue,
        "publisher": candidate.publisher,
        "type": candidate.work_type,
        "doi": candidate.doi,
        "arxiv_id": candidate.arxiv_id,
        "url": candidate.stable_url(),
        "pages": candidate.pages,
        "volume": candidate.volume,
        "issue": candidate.issue,
        "reviewed": candidate.reviewed,
        "preprint": candidate.preprint,
        "score": candidate.score,
        "title_similarity": candidate.similarity,
        "evidence": candidate.evidence,
        "official_bibtex_source": candidate.official_bibtex_source,
    }


def bibtex_escape(value: str) -> str:
    replacements = {
        "\\": r"\\",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
    }
    return "".join(replacements.get(char, char) for char in value)


def latex_braced(value: str) -> str:
    return "{" + bibtex_escape(value).replace("{", "").replace("}", "") + "}"


def author_last_name(name: str) -> str:
    pieces = name.replace(",", " ").split()
    return re.sub(r"[^A-Za-z0-9]+", "", pieces[-1]) if pieces else "paper"


def citation_key(candidate: Candidate) -> str:
    author = author_last_name(candidate.authors[0]) if candidate.authors else "paper"
    year = str(candidate.year or "nd")
    title_word = "paper"
    for word in normalize_title(candidate.title).split():
        if len(word) > 3:
            title_word = word
            break
    return f"{author}{year}{title_word}".lower()


def bibtex_entry(candidate: Candidate) -> str:
    work_type = (candidate.work_type or "").lower()
    venue = candidate.citation_venue()
    if candidate.work_type in {"proceedings-article"} or "conference" in work_type or "proceedings" in work_type:
        entry_type = "inproceedings"
    elif candidate.work_type in {"journal-article", "article"} or "journal" in work_type:
        entry_type = "article"
    elif candidate.preprint:
        entry_type = "misc"
    elif venue:
        entry_type = "inproceedings" if "conference" in venue.lower() else "article"
    else:
        entry_type = "misc"

    fields: list[tuple[str, str]] = []
    if candidate.title:
        fields.append(("title", latex_braced(candidate.title)))
    if candidate.authors:
        fields.append(("author", " and ".join(bibtex_escape(author) for author in candidate.authors)))
    if candidate.year:
        fields.append(("year", str(candidate.year)))

    if venue:
        if entry_type == "inproceedings":
            fields.append(("booktitle", latex_braced(venue)))
        elif entry_type == "article":
            fields.append(("journal", latex_braced(venue)))
        else:
            fields.append(("howpublished", latex_braced(venue)))

    if candidate.volume:
        fields.append(("volume", candidate.volume))
    if candidate.issue:
        fields.append(("number", candidate.issue))
    if candidate.pages:
        fields.append(("pages", candidate.pages.replace("-", "--")))
    if candidate.publisher:
        fields.append(("publisher", latex_braced(candidate.publisher)))
    if candidate.doi:
        fields.append(("doi", candidate.doi))
    if candidate.arxiv_id and candidate.preprint and not candidate.doi:
        fields.extend(
            [
                ("eprint", strip_arxiv_version(candidate.arxiv_id)),
                ("archivePrefix", "arXiv"),
            ]
        )
    url = candidate.stable_url()
    if url and not candidate.doi:
        fields.append(("url", url))

    lines = [f"@{entry_type}{{{citation_key(candidate)},"]
    for index, (key, value) in enumerate(fields):
        comma = "," if index < len(fields) - 1 else ""
        lines.append(f"  {key} = {{{value}}}{comma}")
    lines.append("}")
    return "\n".join(lines)


def initials(name: str) -> str:
    name = normalize_space(name)
    if not name:
        return ""
    if "," in name:
        family, given = [part.strip() for part in name.split(",", 1)]
    else:
        parts = name.split()
        family = parts[-1]
        given = " ".join(parts[:-1])
    given_initials = " ".join(f"{part[0]}." for part in given.split() if part)
    return f"{family}, {given_initials}".strip()


def format_authors_apa(authors: list[str]) -> str:
    if not authors:
        return ""
    formatted = [initials(author) for author in authors[:20]]
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return f"{formatted[0]} & {formatted[1]}"
    return ", ".join(formatted[:-1]) + f", & {formatted[-1]}"


def format_authors_plain(authors: list[str]) -> str:
    if not authors:
        return ""
    if len(authors) == 1:
        return authors[0]
    if len(authors) == 2:
        return f"{authors[0]} and {authors[1]}"
    return ", ".join(authors[:-1]) + f", and {authors[-1]}"


def build_citations(candidate: Candidate | None) -> dict[str, str]:
    if candidate is None:
        return {}
    year = str(candidate.year or "n.d.")
    title = candidate.title.rstrip(".")
    venue = candidate.citation_venue().rstrip(".")
    url = candidate.stable_url()
    author_apa = format_authors_apa(candidate.authors)
    author_plain = format_authors_plain(candidate.authors)
    first_author = candidate.authors[0] if candidate.authors else "Unknown"

    apa_parts = []
    if author_apa:
        apa_parts.append(f"{author_apa} ({year}).")
    else:
        apa_parts.append(f"({year}).")
    apa_parts.append(f"{title}.")
    if venue:
        apa_parts.append(f"{venue}.")
    if url:
        apa_parts.append(url)

    mla = ""
    if author_plain:
        mla = f'{author_plain}. "{title}."'
    else:
        mla = f'"{title}."'
    if venue:
        mla += f" {venue},"
    mla += f" {year}."
    if url:
        mla += f" {url}."

    chicago = ""
    if author_plain:
        chicago = f'{author_plain}. "{title}."'
    else:
        chicago = f'"{title}."'
    if venue:
        chicago += f" {venue}"
    chicago += f" ({year})."
    if url:
        chicago += f" {url}."

    ieee = f'{format_authors_plain(candidate.authors[:6]) or first_author}, "{title},"'
    if venue:
        ieee += f" in {venue},"
    ieee += f" {year}."
    if url:
        ieee += f" doi/url: {url}."

    return {
        "bibtex": candidate.official_bibtex or bibtex_entry(candidate),
        "apa": " ".join(apa_parts),
        "mla": normalize_space(mla),
        "chicago": normalize_space(chicago),
        "ieee": normalize_space(ieee),
    }


def markdown_report(result: dict[str, Any]) -> str:
    recommended = result["recommended"]
    if not recommended:
        errors = "\n".join(f"- {error}" for error in result["errors"]) or "- No candidates returned"
        return f"# Citation Resolution\n\nNo citation candidate found.\n\n## Errors\n\n{errors}\n"

    citations = result["citations"]
    status = "peer-reviewed venue preferred" if recommended["reviewed"] and not recommended["preprint"] else "preprint or unverified venue"
    lines = [
        "# Citation Resolution",
        "",
        f"Input: `{result['input']['raw']}`",
        f"Decision: **{status}**",
        f"Title match: `{recommended['title_similarity']}`",
        f"Score: `{recommended['score']}`",
        "",
        "## Recommended Record",
        "",
        f"- Title: {recommended['title']}",
        f"- Authors: {', '.join(recommended['authors']) if recommended['authors'] else 'Unknown'}",
        f"- Year: {recommended['year'] or 'Unknown'}",
        f"- Venue: {recommended['venue'] or 'Unknown'}",
        f"- DOI: {recommended['doi'] or 'None'}",
        f"- arXiv: {recommended['arxiv_id'] or 'None'}",
        f"- URL: {recommended['url'] or 'None'}",
        f"- Source: {recommended['source']}",
        "",
        "## BibTeX",
        "",
        "```bibtex",
        citations["bibtex"],
        "```",
        "",
        "## Other Formats",
        "",
        f"- APA: {citations['apa']}",
        f"- MLA: {citations['mla']}",
        f"- Chicago: {citations['chicago']}",
        f"- IEEE: {citations['ieee']}",
        "",
        "## Evidence",
        "",
    ]
    lines.extend(f"- {item}" for item in recommended["evidence"])
    lines.extend(["", "## Top Candidates", ""])
    for candidate in result["candidates"][:5]:
        lines.append(
            "- "
            + f"{candidate['score']}: {candidate['title']} "
            + f"({candidate['year'] or 'n.d.'}, {candidate['venue'] or candidate['source']}, "
            + f"reviewed={candidate['reviewed']}, preprint={candidate['preprint']})"
        )
    if result["errors"]:
        lines.extend(["", "## API Warnings", ""])
        lines.extend(f"- {error}" for error in result["errors"])
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resolve a paper title, DOI, arXiv URL, or arXiv ID to citation formats.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Examples:
              resolve_citation.py "Attention Is All You Need"
              resolve_citation.py https://arxiv.org/abs/1706.03762 --format bibtex
              resolve_citation.py 10.1145/nnnnnnn.nnnnnnn --format json
            """
        ),
    )
    parser.add_argument("query", help="Paper title, DOI, DOI URL, arXiv URL, or arXiv ID.")
    parser.add_argument("--format", choices=["markdown", "json", "bibtex"], default="markdown")
    parser.add_argument("--max-results", type=int, default=5, help="Candidates to request per search API.")
    parser.add_argument("--timeout", type=float, default=15.0, help="HTTP timeout in seconds.")
    parser.add_argument("--mailto", help="Email for polite Crossref/OpenAlex API identification.")
    parser.add_argument("--s2-api-key", help="Semantic Scholar API key. Defaults to S2_API_KEY.")
    parser.add_argument(
        "--user-agent",
        default="paper-citation-resolver/0.1 (+https://github.com/local/research-skills)",
        help="HTTP User-Agent sent to metadata APIs.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    result = resolve(args.query, args)
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.format == "bibtex":
        bibtex = result.get("citations", {}).get("bibtex")
        if not bibtex:
            print("No BibTeX candidate found.", file=sys.stderr)
            return 2
        print(bibtex)
    else:
        print(markdown_report(result))
    return 0 if result.get("recommended") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
