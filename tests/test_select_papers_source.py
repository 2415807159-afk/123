import importlib.util
import pathlib
import sys
import tempfile
import unittest


def _load_module(module_name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class SelectPapersSourceTagTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = pathlib.Path(__file__).resolve().parents[1]
        src_dir = root / "src"
        if str(src_dir) not in sys.path:
            sys.path.insert(0, str(src_dir))
        cls.mod = _load_module("select_mod", src_dir / "5.select_papers.py")

    def test_build_candidates_marks_selection_source(self):
        scored = [
            {"id": "fresh-1", "title": "Fresh", "llm_score": 8.2},
            {"id": "fresh-2", "title": "Fresh2", "llm_score": 8.1},
        ]
        carryover = [
            {"id": "carry-1", "title": "Carry", "llm_score": 9.0},
        ]
        out = self.mod.build_candidates(scored, carryover, set())
        source_map = {item.get("id"): item.get("selection_source") for item in out}
        self.assertEqual(source_map.get("fresh-1"), "fresh_fetch")
        self.assertEqual(source_map.get("fresh-2"), "fresh_fetch")
        self.assertEqual(source_map.get("carry-1"), "carryover_cache")

    def test_build_carryover_out_marks_source(self):
        out = self.mod.build_carryover_out(
            [
                {
                    "id": "p-1",
                    "llm_score": 8.5,
                    "title": "P1",
                    "selection_source": "fresh_fetch",
                },
                {
                    "id": "p-2",
                    "llm_score": 7.9,
                    "title": "P2",
                    "selection_source": "fresh_fetch",
                },
            ],
            set(),
            5,
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].get("selection_source"), "carryover_cache")
        self.assertEqual(out[0].get("paper_id"), "p-1")

    def test_sanitize_items_keeps_selection_source(self):
        with tempfile.TemporaryDirectory():
            items = [
                {
                    "id": "p-1",
                    "_source": "new",
                    "selection_source": "fresh_fetch",
                }
            ]
            out = self.mod.sanitize_items(items)
            self.assertEqual(len(out), 1)
            self.assertNotIn("_source", out[0])
            self.assertEqual(out[0].get("selection_source"), "fresh_fetch")


class SelectPapersDeepPriorityModeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = pathlib.Path(__file__).resolve().parents[1]
        src_dir = root / "src"
        if str(src_dir) not in sys.path:
            sys.path.insert(0, str(src_dir))
        cls.mod = _load_module("select_mod", src_dir / "5.select_papers.py")

    def test_process_mode_keeps_all_nine_plus_even_if_over_cap(self):
        candidates = [
            {"id": "p-1", "llm_score": 9.6},
            {"id": "p-2", "llm_score": 9.3},
            {"id": "p-3", "llm_score": 9.1},
            {"id": "p-4", "llm_score": 8.9},
            {"id": "p-5", "llm_score": 8.8},
        ]
        result = self.mod.process_mode(
            candidates=candidates,
            tag_count=1,
            mode="standard",
            cfg={"deep_base": 1, "deep_unlimited": False, "deep_strategy": "round_robin"},
            carryover_ratio=0.5,
        )
        self.assertEqual(result.get("stats", {}).get("deep_selected"), 3)
        deep_ids = [item.get("id") for item in result.get("deep_dive", [])]
        self.assertEqual(deep_ids, ["p-1", "p-2", "p-3"])

    def test_process_mode_nine_plus_full_then_fill_to_cap_with_regular(self):
        candidates = [
            {"id": "p-1", "llm_score": 9.8},
            {"id": "p-2", "llm_score": 8.9},
            {"id": "p-3", "llm_score": 8.7},
            {"id": "p-4", "llm_score": 8.6},
        ]
        result = self.mod.process_mode(
            candidates=candidates,
            tag_count=2,
            mode="standard",
            cfg={"deep_base": 1, "deep_unlimited": False, "deep_strategy": "score"},
            carryover_ratio=0.5,
        )
        self.assertEqual(result.get("stats", {}).get("deep_selected"), 3)
        deep_ids = {item.get("id") for item in result.get("deep_dive", [])}
        self.assertIn("p-1", deep_ids)
        self.assertTrue("p-2" in deep_ids or "p-3" in deep_ids)

    def test_process_mode_nine_plus_only_keeps_original_when_none(self):
        candidates = [
            {"id": "p-1", "llm_score": 8.9},
            {"id": "p-2", "llm_score": 8.6},
            {"id": "p-3", "llm_score": 8.4},
            {"id": "p-4", "llm_score": 7.9},
        ]
        result = self.mod.process_mode(
            candidates=candidates,
            tag_count=2,
            mode="standard",
            cfg={"deep_base": 3, "deep_unlimited": False, "deep_strategy": "score"},
            carryover_ratio=0.5,
        )
        self.assertEqual(result.get("stats", {}).get("deep_selected"), 3)
        deep_scores = [float(item.get("llm_score", 0)) for item in result.get("deep_dive", [])]
        self.assertEqual(deep_scores, sorted(deep_scores, reverse=True))


if __name__ == "__main__":
    unittest.main()
