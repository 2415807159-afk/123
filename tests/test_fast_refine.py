import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "3.5.fast_refine.py"
SPEC = importlib.util.spec_from_file_location("fast_refine", MODULE_PATH)
fast_refine = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(fast_refine)


class FastRefineTest(unittest.TestCase):
    def test_build_fast_llm_ranked_returns_step5_compatible_shape(self):
        data = {
            "queries": [
                {
                    "tag": "query:timd",
                    "query_text": "titanium alloys molecular dynamics",
                    "ranked": [
                        {"paper_id": "p1", "score": 0.95},
                        {"paper_id": "p2", "score": 0.50},
                    ],
                }
            ]
        }
        ranked = fast_refine.build_fast_llm_ranked(data)
        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0]["paper_id"], "p1")
        self.assertGreaterEqual(ranked[0]["score"], 9.0)
        self.assertEqual(ranked[0]["matched_query_tag"], "query:timd")
        self.assertIn("快速模式", ranked[0]["evidence_cn"])

    def test_build_fast_llm_ranked_supports_bm25_sim_scores(self):
        data = {
            "queries": [
                {
                    "tag": "query:core",
                    "query_text": "acta materialia titanium alloys",
                    "sim_scores": {
                        "p1": {"score": 12.0, "rank": 1},
                        "p2": {"score": 4.0, "rank": 2},
                    },
                }
            ]
        }
        ranked = fast_refine.build_fast_llm_ranked(data)
        self.assertEqual([item["paper_id"] for item in ranked], ["p1", "p2"])
        self.assertGreater(ranked[0]["score"], ranked[1]["score"])


if __name__ == "__main__":
    unittest.main()
