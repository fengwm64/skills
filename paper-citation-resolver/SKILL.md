---
name: paper-citation-resolver
description: Resolve academic paper citations from a title, DOI, arXiv ID, arXiv URL, preprint URL, or rough paper name. Use when Codex needs to find the best current citation for a research paper, especially to replace an arXiv/preprint citation with the latest peer-reviewed conference or journal version when evidence supports it, and to output BibTeX plus APA, MLA, Chicago, or IEEE-style citations.
---

# Paper Citation Resolver

## Overview

Resolve paper inputs to citation metadata and citation formats, prioritizing
peer-reviewed conference or journal records over preprints when the metadata
evidence is strong.

## Workflow

1. Run `scripts/resolve_citation.py` with the user's title, DOI, arXiv URL, or
   arXiv ID.
2. Prefer the recommended record when it is marked as reviewed and has strong
   title similarity.
3. If API results are missing, rate-limited, contradictory, or only return
   preprint-like records, use agent research as a fallback. Search authoritative
   venues and indexes, then cite the sources used as evidence.
4. If the final recommendation is still a preprint, state that no stronger
   reviewed record was found from the checked sources.
5. Include BibTeX first unless the user requested another format.
6. Show enough evidence for the user to audit the decision: DOI, venue, source,
   title match score, and any API warnings.

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

1. Peer-reviewed conference or journal version with DOI and venue metadata.
2. Publisher/proceedings record with strong title match.
3. arXiv record containing a DOI or journal reference.
4. Preprint record when no reviewed version is found.

Do not silently replace a preprint with a weak candidate. If title similarity is
low, authors are inconsistent, or venue metadata is absent, report the ambiguity
and include the top candidates.

## Service Implementations

This skill currently ships a local Python script with no third-party Python
dependencies. If a reusable service is needed later, keep the same input/output
shape and add one of these companion implementations:

- `api/cloudflare-worker/` for a lightweight HTTP API on Cloudflare Workers.
- `mcp/cloudflare-worker/` for an MCP interface on Cloudflare Workers.
- `service/docker/` only when the resolver needs runtime features that Workers
  cannot support; keep it small enough for deployment on Alibaba Cloud ECS in
  Guangzhou.
