#!/usr/bin/env python

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List


SCRIPT_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
TODAY_STR = str(os.getenv("DPR_RUN_DATE") or "").strip() or datetime.now(timezone.utc).strftime("%Y%m%d")
RANKED_DIR = os.path.join(ROOT_DIR, "archive", TODAY_STR, "rank")


def log(message: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {message}", flush=True)


def load_json(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"missing file: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: Dict[str, Any], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log(f"[INFO] saved: {path}")


def _norm_text(value: Any) -> str:
    return str(value or "").strip()


def _coerce_score(value: Any) -> float:
    try:
        score = float(value)
    except Exception:
        score = 0.0
    return max(0.0, min(1.0, score))


def _quick_score_to_llm(score_01: float) -> float:
    # 快速模式下复用 Step 5 的 6/7/8/9 阈值体系：
    # rerank 得分越高，映射越接近 10 分。
    return round(6.0 + score_01 * 4.0, 3)


def _collect_ranked_items(query: Dict[str, Any]) -> List[Dict[str, Any]]:
    ranked = query.get("ranked") or []
    if isinstance(ranked, list) and ranked:
        items: List[Dict[str, Any]] = []
        for item in ranked:
            if not isinstance(item, dict):
                continue
            pid = _norm_text(item.get("paper_id") or item.get("id"))
            if not pid:
                continue
            items.append({"paper_id": pid, "score": _coerce_score(item.get("score"))})
        if items:
            return items

    sim_scores = query.get("sim_scores") or {}
    if not isinstance(sim_scores, dict) or not sim_scores:
        return []

    pairs: List[tuple[str, float]] = []
    for pid, payload in sim_scores.items():
        paper_id = _norm_text(pid)
        if not paper_id or not isinstance(payload, dict):
            continue
        try:
            score = float(payload.get("score", 0.0))
        except Exception:
            score = 0.0
        pairs.append((paper_id, score))
    if not pairs:
        return []

    pairs.sort(key=lambda x: x[1], reverse=True)
    values = [score for _, score in pairs]
    min_score = min(values)
    max_score = max(values)
    denom = max_score - min_score if max_score > min_score else 1.0
    return [
        {"paper_id": pid, "score": max(0.0, min(1.0, (score - min_score) / denom))}
        for pid, score in pairs
    ]


def build_fast_llm_ranked(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for idx, query in enumerate(data.get("queries") or [], start=1):
        if not isinstance(query, dict):
            continue
        query_text = _norm_text(
            query.get("query_text") or query.get("rewrite") or query.get("query") or ""
        )
        matched_tag = _norm_text(query.get("tag") or f"query:q{idx}")
        ranked = _collect_ranked_items(query)
        for item in ranked:
            pid = _norm_text(item.get("paper_id") or item.get("id"))
            if not pid:
                continue
            score_01 = _coerce_score(item.get("score"))
            llm_score = _quick_score_to_llm(score_01)
            evidence_cn = (
                f"快速模式：该论文与检索主题“{query_text or matched_tag}”相关，"
                f"基于召回与重排结果优先保留。"
            )
            evidence_en = (
                f"Fast mode: this paper is relevant to the query "
                f"'{query_text or matched_tag}' based on retrieval and rerank signals."
            )
            payload = {
                "paper_id": pid,
                "score": llm_score,
                "evidence_en": evidence_en,
                "evidence_cn": evidence_cn,
                "canonical_evidence": evidence_cn,
                "tldr_en": evidence_en,
                "tldr_cn": evidence_cn,
                "matched_requirement_id": f"fast:{matched_tag or f'q{idx}'}",
                "matched_query_tag": matched_tag,
                "matched_query_text": query_text,
            }
            prev = merged.get(pid)
            if prev is None or llm_score > float(prev.get("score", 0.0)):
                merged[pid] = payload
    return sorted(merged.values(), key=lambda x: x.get("score", 0), reverse=True)


def process_file(input_path: str, output_path: str) -> None:
    data = load_json(input_path)
    llm_ranked = build_fast_llm_ranked(data)
    data["llm_ranked"] = llm_ranked
    data["llm_ranked_at"] = datetime.now(timezone.utc).isoformat()
    data["llm_ranked_mode"] = "fast"
    save_json(data, output_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fast refine bridge for skims mode: convert rerank output into llm_ranked JSON."
    )
    parser.add_argument(
        "--input",
        type=str,
        default=os.path.join(RANKED_DIR, f"arxiv_papers_{TODAY_STR}.json"),
        help="Step 3 rerank JSON input path.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=os.path.join(RANKED_DIR, f"arxiv_papers_{TODAY_STR}.llm.json"),
        help="LLM-compatible JSON output path.",
    )
    args = parser.parse_args()

    input_path = args.input
    output_path = args.output
    if not os.path.isabs(input_path):
        input_path = os.path.abspath(os.path.join(ROOT_DIR, input_path))
    if not os.path.isabs(output_path):
        output_path = os.path.abspath(os.path.join(ROOT_DIR, output_path))
    process_file(input_path, output_path)


if __name__ == "__main__":
    main()
