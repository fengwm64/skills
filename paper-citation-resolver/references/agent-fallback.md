# Agent Fallback Workflow

Use this when public metadata APIs fail, rate-limit, return conflicting records,
or produce only preprint-like candidates.

## Search Targets

Prefer authoritative or field-specific sources before broad web search:

- Conference proceedings pages: NeurIPS, ICML/PMLR, ICLR/OpenReview, ACL
  Anthology, CVF, AAAI, IJCAI, ACM Digital Library, IEEE Xplore.
- Scholarly indexes: DBLP, Crossref, OpenAlex, Semantic Scholar.
- arXiv abstract page for title, authors, version history, DOI, and journal
  reference fields.
- Publisher pages only when the venue page is absent or incomplete.

## Agent Procedure

1. Extract title, authors, arXiv ID, DOI, and year from the input or script
   output.
2. Search with title plus the first three to five author surnames.
3. Search the likely venue indexes if the field is obvious, for example
   `site:proceedings.neurips.cc "TITLE"` or `site:proceedings.mlr.press
   "TITLE"`.
4. Confirm that title and authors match. Do not rely on title alone for generic
   titles.
5. Prefer the proceedings or publisher metadata over a preprint, but keep the
   arXiv ID in notes when it helps disambiguate.
6. Use official BibTeX from the venue when available. For ACL Anthology, fetch
   `https://aclanthology.org/<paper-id>.bib`; for PMLR, NeurIPS, OpenReview,
   ACM, IEEE, and CVF, prefer their exported BibTeX over generated entries.
7. Generate BibTeX from confirmed metadata only when no official BibTeX exists.
   If a DOI is absent, use the venue URL.
8. Report the checked sources and the reason for the choice.

## Failure Mode

If no reviewed record is found after checking likely authoritative sources,
return the best preprint citation and explicitly say which sources were checked.
