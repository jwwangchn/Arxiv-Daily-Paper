from __future__ import annotations

import argparse
import logging
from pathlib import Path

from analyze_deepseek import analyze_date
from build_site import build_site
from fetch_arxiv import fetch_papers, find_latest_date_with_papers, save_raw
from utils import PROJECT_ROOT, ensure_dirs, load_config, parse_date, read_json, setup_logging


LOGGER = logging.getLogger("run_daily")


def parse_args() -> argparse.Namespace:
    config = load_config()
    parser = argparse.ArgumentParser(description="Run the full arXiv Daily Paper Guide pipeline.")
    parser.add_argument("--date", default=None, help="Target date in YYYY-MM-DD format.")
    parser.add_argument("--max-papers", type=int, default=config.get("arxiv", {}).get("max_papers", 30))
    parser.add_argument("--categories", nargs="+", default=config.get("arxiv", {}).get("categories", []))
    parser.add_argument("--lookback-days", type=int, default=14, help="Days to look back when no --date is provided.")
    parser.add_argument("--concurrency", type=int, default=None, help="Concurrent DeepSeek requests; safe-capped by analyze_deepseek.py.")
    parser.add_argument("--mock", action="store_true", help="Skip arXiv and DeepSeek; build the site with mock data.")
    return parser.parse_args()


def is_fully_analyzed(target_date: str, papers: list[dict]) -> bool:
    if not papers:
        return False
    output_path: Path = PROJECT_ROOT / "data" / "analyzed" / f"{target_date}.json"
    if not output_path.exists():
        return False
    existing = read_json(output_path)
    existing_by_id = {paper.get("arxiv_id"): paper for paper in existing.get("papers", []) if paper.get("arxiv_id")}
    for paper in papers:
        existing_paper = existing_by_id.get(paper.get("arxiv_id"))
        if not existing_paper or ("analysis" not in existing_paper and "analysis_error" not in existing_paper):
            return False
    return True


def main() -> None:
    setup_logging()
    ensure_dirs()
    args = parse_args()

    if args.mock:
        LOGGER.info("Running in mock mode; no external APIs will be called.")
        build_site(use_mock=True)
        return

    if args.date:
        target_date = parse_date(args.date)
        papers = fetch_papers(target_date, args.categories, args.max_papers)
    else:
        target_date, papers = find_latest_date_with_papers(
            args.categories,
            args.max_papers,
            lookback_days=args.lookback_days,
        )

    LOGGER.info("Starting daily pipeline for %s", target_date)
    save_raw(target_date, papers)

    analysis_failed = False
    if is_fully_analyzed(target_date, papers):
        LOGGER.info("%s is already fully analyzed; skipping DeepSeek calls.", target_date)
    else:
        try:
            analyze_date(target_date, concurrency=args.concurrency)
        except Exception:
            analysis_failed = True
            LOGGER.exception("DeepSeek analysis step failed. Site build will continue with available data.")

    build_site(use_mock=False)
    if analysis_failed:
        raise RuntimeError("Daily pipeline failed during DeepSeek analysis.")
    LOGGER.info("Pipeline completed for %s", target_date)


if __name__ == "__main__":
    main()
