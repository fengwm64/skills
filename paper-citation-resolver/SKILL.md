---
name: paper-citation-resolver
description: Resolve academic paper citations from a verified full title, DOI, arXiv ID, arXiv URL, preprint URL, or rough paper name after first recovering the paper's complete title and identifiers with paper-search or live web search. Use when Codex needs to find the best current citation for a research paper, especially to replace an arXiv/preprint citation with the latest peer-reviewed conference or journal version when evidence supports it, and to output BibTeX plus APA, MLA, Chicago, or IEEE-style citations.
---

# Paper Citation Resolver

## Overview

Resolve paper inputs to citation metadata and citation formats, prioritizing
peer-reviewed conference or journal records over preprints when the metadata
evidence is strong.

## Workflow

1. If the user gives a rough paper name, first recover the complete title and
   identifiers with `paper-search` or `ai-search` before resolving citations.
2. Run `scripts/resolve_citation.py` with the verified title, DOI, arXiv URL,
   or arXiv ID.
3. Prefer the recommended record when it is marked as reviewed and has strong
   title similarity.
4. If API results are missing, rate-limited, contradictory, or only return
   preprint-like records, use agent research as a fallback. Search authoritative
   venues and indexes, then cite the sources used as evidence.
5. If the final recommendation is still a preprint, state that no stronger
   reviewed record was found from the checked sources.
6. Include BibTeX first unless the user requested another format.
7. Show enough evidence for the user to audit the decision: DOI, venue, source,
   title match score, and any API warnings.

When an authoritative venue provides its own BibTeX entry, prefer that official
BibTeX over generated BibTeX from general metadata APIs. General APIs are useful
for discovery, but venue BibTeX usually includes canonical citation keys, URL,
address, month, editors, and field capitalization.

## Quick Commands

Use Markdown for a human-readable report:

```bash
python3 paper-citation-resolver/scripts/resolve_citation.py "Attention Is All You Need"
```

Return only BibTeX:

```bash
python3 paper-citation-resolver/scripts/resolve_citation.py "https://arxiv.org/abs/1706.03762" --format bibtex
```

Return structured JSON for further processing:

```bash
python3 paper-citation-resolver/scripts/resolve_citation.py "10.48550/arXiv.1706.03762" --format json
```

Optional environment variables:

- `CROSSREF_MAILTO` or `OPENALEX_MAILTO`: identify the caller politely to public
  metadata APIs.
- `S2_API_KEY`: Semantic Scholar API key, if available.

## Decision Policy

Read `references/resolution-policy.md` when a result is ambiguous or when the
user asks why a preprint was or was not replaced. Read
`references/agent-fallback.md` when metadata APIs fail or conflict.

Default preference order:

1. Official venue/publisher BibTeX for the confirmed reviewed version.
2. Peer-reviewed conference or journal version with DOI and venue metadata.
3. Publisher/proceedings record with strong title match.
4. arXiv record containing a DOI or journal reference.
5. Preprint record when no reviewed version is found.

Do not silently replace a preprint with a weak candidate. If title similarity is
low, authors are inconsistent, or venue metadata is absent, report the ambiguity
and include the top candidates.

When the user has only a partial or fuzzy title, do not skip the title recovery
step. The resolver works best after the canonical title is known, and the
recorded citation should be matched against that exact title rather than the
user's first guess.

## Service Implementations

This skill currently ships a local Python script with no third-party Python
dependencies. If a reusable service is needed later, keep the same input/output
shape and add one of these companion implementations:

- `api/cloudflare-worker/` for a lightweight HTTP API on Cloudflare Workers.
- `mcp/cloudflare-worker/` for an MCP interface on Cloudflare Workers.
- `service/docker/` only when the resolver needs runtime features that Workers
  cannot support; keep it small enough for deployment on Alibaba Cloud ECS in
  Guangzhou.
