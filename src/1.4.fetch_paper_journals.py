#!/usr/bin/env python

from __future__ import annotations

import argparse
import os

from journal_watch import run_journal_fetch


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="抓取配置中的指定期刊文章，并并入 raw 论文池。")
    parser.add_argument("--days", type=int, default=None, help="回溯抓取天数；默认读取 journal_watch.days_window。")
    parser.add_argument("--ignore-seen", action="store_true", help="忽略 archive/journal_seen.json，不跳过已见文章。")
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="可选：指定输出 raw JSON 路径；默认写入 archive/<run_token>/raw/arxiv_papers_<run_token>.json",
    )
    args = parser.parse_args()

    output_path = args.output
    if output_path and not os.path.isabs(output_path):
        output_path = os.path.abspath(output_path)

    result = run_journal_fetch(
        days=args.days,
        ignore_seen=bool(args.ignore_seen),
        output_path=output_path,
    )
    if result.get("enabled"):
        print(
            "[OK] journal fetch complete | "
            f"fetched={result.get('fetched', 0)} "
            f"added={result.get('added', 0)} "
            f"total={result.get('total', 0)} "
            f"path={result.get('output_path', '')}",
            flush=True,
        )
    else:
        print("[INFO] journal_watch 未启用，跳过期刊抓取。", flush=True)
