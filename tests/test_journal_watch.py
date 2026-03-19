import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from journal_watch import normalize_storage_id, parse_crossref_work, strip_jats  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
