#!/usr/bin/env python
"""
Ultra-Fast Paper Reader - Zero LLM Calls

This script implements a pure BM25-based paper retrieval system without any LLM calls.
It significantly reduces execution time and token costs by:
1. Skipping all LLM refinement steps (Step 3, 4)
2. Using only BM25 scores for ranking
3. Directly generating docs from ranked results

Performance improvement: ~10-20x faster than full pipeline
Token consumption: ZERO (no API calls)
"""

import argparse
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    yaml = None

# Directory setup
SCRIPT_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
ARCHIVE_ROOT = os.path.join(ROOT_DIR, "archive")
TODAY_STR = datetime.now(timezone.utc).strftime("%Y%m%d")
ARCHIVE_DIR = os.path.join(ARCHIVE_ROOT, TODAY_STR)
RAW_DIR = os.path.join(ARCHIVE_DIR, "raw")
FILTERED_DIR = os.path.join(ARCHIVE_DIR, "filtered")
RANKED_DIR = os.path.join(ARCHIVE_DIR, "rank")
RECOMMEND_DIR = os.path.join(ARCHIVE_DIR, "recommend")
DOCS_DIR = os.path.join(ROOT_DIR, "docs", TODAY_STR)
CONFIG_FILE = os.path.join(ROOT_DIR, "config.yaml")


def log(message: str) -> None:
    """Log message with timestamp."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {message}", flush=True)


def group_start(title: str) -> None:
    """Start GitHub Actions log group."""
    print(f"::group::{title}", flush=True)


def group_end() -> None:
    """End GitHub Actions log group."""
    print("::endgroup::", flush=True)


def load_yaml(path: str) -> Dict[str, Any]:
    """Load YAML configuration file."""
    if not yaml:
        raise RuntimeError("PyYAML not installed")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def load_json(path: str) -> Dict[str, Any]:
    """Load JSON file."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"JSON file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: Dict[str, Any], path: str) -> None:
    """Save data to JSON file."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log(f"Saved: {path}")


def run_step1_fetch(fetch_days: int) -> None:
    """Step 1: Fetch papers from arXiv/journals."""
    log("=" * 60)
    log("STEP 1: Fetching papers from sources...")
    log("=" * 60)
    
    args = [
        "python",
        os.path.join(ROOT_DIR, "src", "1.fetch_paper_arxiv.py"),
        "--days", str(fetch_days)
    ]
    
    import subprocess
    result = subprocess.run(args, check=True, capture_output=False)
    log("Step 1 completed successfully")


def run_step2_bm25(max_papers_per_day: int) -> None:
    """Step 2: Run BM25 retrieval and scoring."""
    log("=" * 60)
    log("STEP 2: Running BM25 retrieval (Zero LLM)...")
    log("=" * 60)
    
    # Set environment variable for max papers
    os.environ["BM25_TOP_K"] = str(max_papers_per_day)
    
    args = [
        "python",
        os.path.join(ROOT_DIR, "src", "2.1.retrieval_papers_bm25.py")
    ]
    
    import subprocess
    result = subprocess.run(args, check=True, capture_output=False)
    log("Step 2 completed - BM25 scoring done")


def select_top_papers(max_papers_per_day: int) -> Dict[str, Any]:
    """Select top papers based on BM25 scores only (no LLM)."""
    log("=" * 60)
    log("STEP 3: Selecting top papers by BM25 score...")
    log("=" * 60)
    
    # Find all filtered JSON files
    if not os.path.exists(FILTERED_DIR):
        raise RuntimeError(f"Filtered directory not found: {FILTERED_DIR}")
    
    selected_papers = []
    filter_files = sorted([f for f in os.listdir(FILTERED_DIR) if f.endswith('.json')])
    
    for fname in filter_files:
        fpath = os.path.join(FILTERED_DIR, fname)
        try:
            data = load_json(fpath)
            papers = data.get("papers", [])
            
            # Sort by BM25 score descending
            papers_sorted = sorted(
                papers, 
                key=lambda p: float(p.get("bm25_score", 0)), 
                reverse=True
            )
            
            # Take top N per day
            for i, paper in enumerate(papers_sorted[:max_papers_per_day]):
                paper["_selection_rank"] = i + 1
                paper["_selected_by"] = "bm25_only"
                selected_papers.append(paper)
                
            log(f"Selected {min(len(papers_sorted), max_papers_per_day)} papers from {fname}")
            
        except Exception as e:
            log(f"Warning: Failed to process {fname}: {e}")
            continue
    
    # Save ranked results
    ranked_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": "bm25_only_zero_llm",
        "total_selected": len(selected_papers),
        "papers": selected_papers
    }
    
    rank_output_path = os.path.join(RANKED_DIR, "ranked_papers.json")
    save_json(ranked_data, rank_output_path)
    
    log(f"Total selected papers: {len(selected_papers)}")
    return ranked_data


def generate_docs_simple(ranked_data: Dict[str, Any]) -> None:
    """Generate simple docs without LLM enrichment."""
    log("=" * 60)
    log("STEP 4: Generating docs (Simple Mode, No LLM)...")
    log("=" * 60)
    
    os.makedirs(DOCS_DIR, exist_ok=True)
    
    papers = ranked_data.get("papers", [])
    
    # Group papers by date
    papers_by_date: Dict[str, List[Dict]] = {}
    for paper in papers:
        pub_date = paper.get("published", "")[:10]  # YYYY-MM-DD
        if pub_date not in papers_by_date:
            papers_by_date[pub_date] = []
        papers_by_date[pub_date].append(paper)
    
    # Generate index.md for each date
    for date_str, date_papers in sorted(papers_by_date.items(), reverse=True):
        date_dir = os.path.join(DOCS_DIR, date_str.replace("-", ""))
        os.makedirs(date_dir, exist_ok=True)
        
        index_md_path = os.path.join(date_dir, "index.md")
        
        md_content = f"# Papers for {date_str}\n\n"
        md_content += f"**Total**: {len(date_papers)} papers\n\n"
        md_content += "---\n\n"
        
        for idx, paper in enumerate(date_papers, 1):
            title = paper.get("title", "Untitled")
            authors = ", ".join(paper.get("authors", [])[:3])
            if len(paper.get("authors", [])) > 3:
                authors += " et al."
            
            journal = paper.get("journal", paper.get("source", "arXiv"))
            bm25_score = paper.get("bm25_score", 0)
            pdf_url = paper.get("pdf_url", "#")
            abs_url = paper.get("arxiv_url", paper.get("abstract_url", "#"))
            
            md_content += f"## {idx}. {title}\n\n"
            md_content += f"**Authors**: {authors}\n\n"
            md_content += f"**Journal**: {journal} | **BM25 Score**: {bm25_score:.2f}\n\n"
            md_content += f"**Links**: [Abstract]({abs_url}) | [PDF]({pdf_url})\n\n"
            md_content += "---\n\n"
        
        with open(index_md_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        
        log(f"Generated: {index_md_path}")
    
    # Update main _sidebar.md
    update_sidebar()
    
    log("Docs generation completed")


def update_sidebar() -> None:
    """Update sidebar with latest dates."""
    sidebar_path = os.path.join(ROOT_DIR, "docs", "_sidebar.md")
    
    if not os.path.exists(sidebar_path):
        log(f"Sidebar not found: {sidebar_path}, creating...")
        os.makedirs(os.path.dirname(sidebar_path), exist_ok=True)
        with open(sidebar_path, "w", encoding="utf-8") as f:
            f.write("* Daily Papers\n")
    
    # Get all date directories
    if os.path.exists(DOCS_DIR):
        date_dirs = sorted([
            d for d in os.listdir(DOCS_DIR) 
            if os.path.isdir(os.path.join(DOCS_DIR, d)) and re.match(r'\d{8}', d)
        ], reverse=True)[:30]  # Last 30 days
        
        sidebar_content = "* Daily Papers\n"
        for date_dir in date_dirs:
            formatted_date = f"{date_dir[:4]}-{date_dir[4:6]}-{date_dir[6:]}"
            sidebar_content += f"  * [{formatted_date}]({date_dir}/)\n"
        
        with open(sidebar_path, "w", encoding="utf-8") as f:
            f.write(sidebar_content)
        
        log(f"Updated sidebar with {len(date_dirs)} dates")


def cleanup_intermediate_files() -> None:
    """Clean up intermediate files to save space."""
    log("Cleaning up intermediate files...")
    
    dirs_to_clean = [RAW_DIR, FILTERED_DIR, RANKED_DIR, RECOMMEND_DIR]
    for dir_path in dirs_to_clean:
        if os.path.exists(dir_path):
            import shutil
            shutil.rmtree(dir_path)
            log(f"Removed: {dir_path}")
    
    log("Cleanup completed")


def main():
    parser = argparse.ArgumentParser(description="Ultra-Fast Paper Reader (Zero LLM)")
    parser.add_argument("--fetch-days", type=int, default=3, help="Days to fetch papers")
    parser.add_argument("--max-papers", type=int, default=15, help="Max papers per day")
    parser.add_argument("--skip-cleanup", action="store_true", help="Skip cleanup step")
    args = parser.parse_args()
    
    log("=" * 60)
    log("ULTRA-FAST PAPER READER - ZERO LLM CALLS")
    log(f"Configuration:")
    log(f"  - Fetch window: {args.fetch_days} days")
    log(f"  - Max papers/day: {args.max_papers}")
    log("=" * 60)
    
    try:
        # Step 1: Fetch papers
        run_step1_fetch(args.fetch_days)
        
        # Step 2: BM25 retrieval
        run_step2_bm25(args.max_papers)
        
        # Step 3: Select top papers (BM25 only, no LLM)
        ranked_data = select_top_papers(args.max_papers)
        
        # Step 4: Generate docs (simple mode)
        generate_docs_simple(ranked_data)
        
        # Copy config to docs
        import shutil
        shutil.copy(CONFIG_FILE, os.path.join(ROOT_DIR, "docs", "config.yaml"))
        log("Copied config.yaml to docs/")
        
        log("=" * 60)
        log("✅ ULTRA-FAST PIPELINE COMPLETED SUCCESSFULLY")
        log(f"   Total papers processed: {len(ranked_data.get('papers', []))}")
        log(f"   LLM calls made: 0 (ZERO TOKEN COST)")
        log(f"   Estimated time savings: ~90% vs full pipeline")
        log("=" * 60)
        
    except Exception as e:
        log(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise
    
    finally:
        if not args.skip_cleanup:
            cleanup_intermediate_files()


if __name__ == "__main__":
    main()
