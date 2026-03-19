import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from journal_watch import (  # noqa: E402
    get_active_journal_entries,
    normalize_storage_id,
    paper_matches_active_scope,
    parse_crossref_work,
    strip_jats,
)


class JournalWatchTest(unittest.TestCase):
    def test_strip_jats_removes_markup(self):
        self.assertEqual(strip_jats("<jats:p>Hello <b>World</b></jats:p>"), "Hello World")

    def test_normalize_storage_id_handles_doi(self):
        self.assertEqual(normalize_storage_id("10.1016/j.actamat.2026.01.001"), "10.1016-j.actamat.2026.01.001")

    def test_parse_crossref_work_extracts_journal_fields(self):
        item = {
            "DOI": "10.1016/j.actamat.2026.01.001",
            "title": ["A titanium alloy paper"],
            "abstract": "<jats:p>Short abstract.</jats:p>",
            "author": [{"given": "Ada", "family": "Lovelace"}],
            "container-title": ["Acta Materialia"],
            "publisher": "Elsevier BV",
            "subject": ["Metals and Alloys"],
            "type": "journal-article",
            "published-online": {"date-parts": [[2026, 3, 10]]},
            "URL": "https://doi.org/10.1016/j.actamat.2026.01.001",
            "link": [
                {
                    "URL": "https://example.com/paper.pdf",
                    "content-type": "application/pdf",
                }
            ],
        }

        paper = parse_crossref_work(item, "Acta Materialia", [])
        self.assertIsNotNone(paper)
        assert paper is not None
        self.assertEqual(paper["source"], "journal-crossref")
        self.assertEqual(paper["journal"], "Acta Materialia")
        self.assertEqual(paper["doi"], "10.1016/j.actamat.2026.01.001")
        self.assertEqual(paper["pdf_url"], "https://example.com/paper.pdf")
        self.assertEqual(paper["published"], "2026-03-10")

    def test_active_scope_filters_journals_by_tier(self):
        cfg = {
            "journal_watch": {
                "active_scope": "core_plus",
                "scopes": [
                    {"key": "core", "tiers": ["core"]},
                    {"key": "core_plus", "tiers": ["core", "secondary"]},
                    {"key": "all", "tiers": ["core", "secondary", "spotlight"]},
                ],
                "journals": [
                    {"title": "Acta Materialia", "tier": "core"},
                    {"title": "Advanced Materials", "tier": "secondary"},
                    {"title": "Nature", "tier": "spotlight"},
                ],
            }
        }
        titles = [item["title"] for item in get_active_journal_entries(cfg)]
        self.assertEqual(titles, ["Acta Materialia", "Advanced Materials"])

    def test_paper_matches_active_scope_rejects_out_of_scope_journal(self):
        cfg = {
            "journal_watch": {
                "active_scope": "core",
                "scopes": [
                    {"key": "core", "tiers": ["core"]},
                    {"key": "all", "tiers": ["core", "secondary", "spotlight"]},
                ],
                "journals": [
                    {"title": "Acta Materialia", "tier": "core"},
                    {"title": "Nature", "tier": "spotlight"},
                ],
            }
        }
        self.assertFalse(
            paper_matches_active_scope(
                {
                    "source": "journal-crossref",
                    "journal": "Nature",
                },
                cfg,
            )
        )
        self.assertTrue(
            paper_matches_active_scope(
                {
                    "source": "journal-crossref",
                    "journal": "Acta Materialia",
                },
                cfg,
            )
        )


if __name__ == "__main__":
    unittest.main()
