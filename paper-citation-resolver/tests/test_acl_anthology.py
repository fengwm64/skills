import importlib.util
import sys
from pathlib import Path
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "resolve_citation.py"
SPEC = importlib.util.spec_from_file_location("resolve_citation", MODULE_PATH)
resolve_citation = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = resolve_citation
SPEC.loader.exec_module(resolve_citation)


class ACLAnthologyTests(unittest.TestCase):
    def test_acl_anthology_id_supports_common_venue_prefixes(self) -> None:
        cases = [
            ("10.18653/v1/2024.acl-long.299", "2024.acl-long.299"),
            ("10.18653/v1/2024.naacl-long.121", "2024.naacl-long.121"),
            ("10.18653/v1/2024.emnlp-main.876", "2024.emnlp-main.876"),
            ("10.18653/v1/2024.eacl-short.27", "2024.eacl-short.27"),
            ("10.18653/v1/2024.findings-acl.449", "2024.findings-acl.449"),
            ("10.18653/v1/2024.findings-naacl.100", "2024.findings-naacl.100"),
            ("https://aclanthology.org/N19-1272/", "N19-1272"),
        ]

        for value, expected in cases:
            with self.subTest(value=value):
                candidate = resolve_citation.Candidate(source="test", doi=value if value.startswith("10.") else "", url=value if value.startswith("https://") else "")
                self.assertEqual(resolve_citation.acl_anthology_id(candidate), expected)

    def test_maybe_attach_official_bibtex_fetches_acl_bib_for_common_venue_prefixes(self) -> None:
        cases = [
            ("10.18653/v1/2024.acl-long.299", "https://aclanthology.org/2024.acl-long.299.bib"),
            ("10.18653/v1/2024.naacl-long.121", "https://aclanthology.org/2024.naacl-long.121.bib"),
            ("10.18653/v1/2024.emnlp-main.876", "https://aclanthology.org/2024.emnlp-main.876.bib"),
            ("10.18653/v1/2024.eacl-short.27", "https://aclanthology.org/2024.eacl-short.27.bib"),
            ("10.18653/v1/2024.findings-acl.449", "https://aclanthology.org/2024.findings-acl.449.bib"),
            ("10.18653/v1/2024.findings-naacl.100", "https://aclanthology.org/2024.findings-naacl.100.bib"),
        ]
        fake_bib = "@inproceedings{example,}"

        for doi, expected_url in cases:
            with self.subTest(doi=doi):
                candidate = resolve_citation.Candidate(source="crossref", doi=doi)
                with patch.object(resolve_citation, "fetch_url_text", return_value=fake_bib) as fetch:
                    resolve_citation.maybe_attach_official_bibtex(candidate, headers={}, timeout=1.0, errors=[])

                self.assertEqual(candidate.official_bibtex, fake_bib)
                self.assertEqual(candidate.official_bibtex_source, expected_url)
                self.assertIn(f"Official BibTeX from ACL Anthology: {expected_url}", candidate.evidence)
                fetch.assert_called_once_with(expected_url, {}, 1.0)

    def test_maybe_attach_official_bibtex_keeps_existing_bibtex(self) -> None:
        candidate = resolve_citation.Candidate(
            source="crossref",
            doi="10.18653/v1/2021.naacl-main.168",
            official_bibtex="@inproceedings{existing,}",
        )

        with patch.object(resolve_citation, "fetch_url_text") as fetch:
            resolve_citation.maybe_attach_official_bibtex(candidate, headers={}, timeout=1.0, errors=[])

        self.assertEqual(candidate.official_bibtex, "@inproceedings{existing,}")
        fetch.assert_not_called()

    def test_official_acl_bibtex_is_preferred_during_ranking(self) -> None:
        official = resolve_citation.Candidate(
            source="crossref",
            title="Are NLP Models really able to Solve Simple Math Word Problems?",
            authors=["Arkil Patel"],
            year=2021,
            venue="North American Chapter of the Association for Computational Linguistics",
            work_type="proceedings-article",
            doi="10.18653/v1/2021.naacl-main.168",
            reviewed=True,
            official_bibtex="@inproceedings{patel-etal-2021-nlp,}",
            official_bibtex_source="https://aclanthology.org/2021.naacl-main.168.bib",
        )
        aggregator = resolve_citation.Candidate(
            source="openalex",
            title=official.title,
            authors=official.authors,
            year=2021,
            venue="NAACL",
            work_type="article",
            doi="10.18653/v1/2021.naacl-main.168",
            reviewed=True,
        )

        ranked = resolve_citation.score_candidates(
            [aggregator, official],
            official.title,
            "title",
            official.title,
        )
        recommended = resolve_citation.choose_recommended(ranked, "title")

        self.assertIs(recommended, official)
        self.assertGreater(official.score, aggregator.score)

    def test_acl_proceedings_doi_does_not_fall_back_to_article(self) -> None:
        candidate = resolve_citation.Candidate(
            source="openalex",
            title="Are NLP Models really able to Solve Simple Math Word Problems?",
            authors=["Arkil Patel", "Satwik Bhattamishra", "Navin Goyal"],
            year=2021,
            venue="North American Chapter of the Association for Computational Linguistics",
            work_type="article",
            doi="10.18653/v1/2021.naacl-main.168",
            reviewed=True,
        )

        bibtex = resolve_citation.bibtex_entry(candidate)

        self.assertTrue(bibtex.startswith("@inproceedings{"))
        self.assertIn("booktitle =", bibtex)
        self.assertNotIn("journal =", bibtex)


if __name__ == "__main__":
    unittest.main()
