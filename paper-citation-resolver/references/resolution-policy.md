# Citation Resolution Policy

Use this reference when deciding whether to replace a preprint citation with a
conference or journal citation.

## Preference Order

1. Official BibTeX from the authoritative venue or publisher for the confirmed
   reviewed version.
2. Peer-reviewed conference or journal version with matching title/authors.
3. Publisher or proceedings record with DOI and venue metadata, preferring
   field-specific venue pages and DBLP over broad aggregation metadata when they
   disagree.
4. arXiv record that includes a DOI or journal reference.
5. arXiv or other preprint record with no reviewed version found.

## Evidence That Supports a Reviewed Version

- DOI resolves through Crossref or OpenAlex.
- Crossref type is `journal-article` or `proceedings-article`.
- Semantic Scholar publication type includes `JournalArticle` or `Conference`.
- OpenAlex record has a DOI plus a non-repository source or venue.
- Title similarity is high and at least the first author is consistent.
- Official venue BibTeX exists for the confirmed paper.

## Evidence That Should Trigger Caution

- Candidate title similarity is below `0.78`.
- Metadata type is `posted-content`, `preprint`, `repository`, or only arXiv.
- Venue exists only as a free-text arXiv journal reference.
- Authors are missing or clearly inconsistent with the preprint.
- A result has a DOI but no recognizable venue/container.
- Public APIs are rate-limited or disagree with authoritative venue pages.
- A broad metadata API labels a proceedings paper as a generic `article`; check
  official venue BibTeX or DBLP before emitting `@article`.

## Reporting

Always show the evidence used for the recommendation. If the best result is
still a preprint, say that no stronger reviewed record was found from the
queried metadata sources.
