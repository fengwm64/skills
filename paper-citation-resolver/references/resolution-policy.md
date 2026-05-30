# Citation Resolution Policy

Use this reference when deciding whether to replace a preprint citation with a
conference or journal citation.

## Preference Order

1. Peer-reviewed conference or journal version with matching title/authors.
2. Official BibTeX from the venue or publisher for that reviewed version.
3. Publisher or proceedings record with DOI and venue metadata.
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

## Reporting

Always show the evidence used for the recommendation. If the best result is
still a preprint, say that no stronger reviewed record was found from the
queried metadata sources.
