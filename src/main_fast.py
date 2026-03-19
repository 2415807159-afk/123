#!/usr/bin/env python

import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

from journal_watch import journal_watch_enabled


SRC_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(SRC_DIR, ".."))
CONFIG_FILE = os.path.join(ROOT_DIR, "config.yaml")
LONG_RANGE_DAYS_THRESHOLD = 10
MAIN_DEFAULT_DAYS = 9


def run_step(label: str, args: list[str]) -> None:
    print(f"[INFO] {label}: {' '.join(args)}", flush=True)
    subprocess.run(args, check=True)


def _load_full_config() -> dict:
    if yaml is None or not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def load_arxiv_paper_setting() -> dict:
    data = _load_full_config()
    setting = data.get("arxiv_paper_setting") or {}
    return setting if isinstance(setting, dict) else {}


def build_sidebar_date_label(days: int) -> str:
    safe_days = max(int(days), 1)
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=safe_days - 1)
    return f"{start_date:%Y-%m-%d} ~ {end_date:%Y-%m-%d}"


def build_run_date_token(days: int) -> str:
    safe_days = max(int(days), 1)
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=safe_days - 1)
    return f"{start_date:%Y%m%d}-{end_date:%Y%m%d}"


def resolve_run_date_token(fetch_days: int | None) -> str:
    if fetch_days is not None:
        if fetch_days >= LONG_RANGE_DAYS_THRESHOLD:
            return build_run_date_token(fetch_days)
        return datetime.now(timezone.utc).strftime("%Y%m%d")

    setting = load_arxiv_paper_setting()
    try:
        days_window = int(setting.get("days_window") or MAIN_DEFAULT_DAYS)
    except Exception:
        days_window = MAIN_DEFAULT_DAYS
    if days_window >= LONG_RANGE_DAYS_THRESHOLD:
        return build_run_date_token(days_window)
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def resolve_sidebar_date_label(fetch_days: int | None) -> str | None:
    if fetch_days is not None:
        if fetch_days >= LONG_RANGE_DAYS_THRESHOLD:
            return build_sidebar_date_label(fetch_days)
        return None

    setting = load_arxiv_paper_setting()
    try:
        days_window = int(setting.get("days_window") or MAIN_DEFAULT_DAYS)
    except Exception:
        days_window = MAIN_DEFAULT_DAYS
    if days_window >= LONG_RANGE_DAYS_THRESHOLD:
        return build_sidebar_date_label(days_window)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fast monitoring pipeline: fetch -> BM25 -> fast refine -> select skims -> generate docs."
    )
    parser.add_argument(
        "--fetch-days",
        type=int,
        default=7,
        help="Days to fetch. Default: 7.",
    )
    parser.add_argument(
        "--fetch-ignore-seen",
        action="store_true",
        help="Ignore seen-state during fetch.",
    )
    args = parser.parse_args()

    python = sys.executable
    run_date_token = resolve_run_date_token(args.fetch_days)
    os.environ["DPR_RUN_DATE"] = run_date_token
    sidebar_date_label = resolve_sidebar_date_label(args.fetch_days)
    print(f"[INFO] DPR_RUN_DATE={run_date_token}", flush=True)
    print(f"[INFO] fast_mode=skims fetch_days={args.fetch_days}", flush=True)

    archive_dir = os.path.join(ROOT_DIR, "archive", run_date_token)
    bm25_path = os.path.join(
        archive_dir,
        "filtered",
        f"arxiv_papers_{run_date_token}.bm25.json",
    )
    llm_path = os.path.join(archive_dir, "rank", f"arxiv_papers_{run_date_token}.llm.json")

    run_step(
        "Step 1 - fetch arxiv",
        [
            python,
            os.path.join(SRC_DIR, "1.fetch_paper_arxiv.py"),
            "--days",
            str(args.fetch_days),
            *(["--ignore-seen"] if args.fetch_ignore_seen else []),
        ],
    )
    if journal_watch_enabled():
        run_step(
            "Step 1.4 - fetch journals",
            [
                python,
                os.path.join(SRC_DIR, "1.4.fetch_paper_journals.py"),
                "--days",
                str(args.fetch_days),
                *(["--ignore-seen"] if args.fetch_ignore_seen else []),
            ],
        )

    run_step(
        "Step 2.1 - BM25",
        [python, os.path.join(SRC_DIR, "2.1.retrieval_papers_bm25.py")],
    )
    run_step(
        "Step 3.5 - Fast refine from BM25",
        [
            python,
            os.path.join(SRC_DIR, "3.5.fast_refine.py"),
            "--input",
            bm25_path,
            "--output",
            llm_path,
        ],
    )
    run_step(
        "Step 5 - Select skims",
        [
            python,
            os.path.join(SRC_DIR, "5.select_papers.py"),
            "--input",
            llm_path,
            "--modes",
            "skims",
        ],
    )
    run_step(
        "Step 6 - Generate Docs skims",
        [
            python,
            os.path.join(SRC_DIR, "6.generate_docs.py"),
            "--mode",
            "skims",
            *(["--sidebar-date-label", sidebar_date_label] if sidebar_date_label else []),
        ],
    )


if __name__ == "__main__":
    main()
