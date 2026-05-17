"""Run the full arXiv Daily Paper pipeline."""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta

from commands.analyze import analyze_date
from commands.build import build_site
from commands.fetch import fetch_papers_for_date_oai
from lib.archive import append_new_papers, load_analysis_index, load_paper_index, paper_id, papers_for_date
from lib.config import ensure_dirs, load_config, parse_date, setup_logging

LOGGER = logging.getLogger("commands.daily")


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
    analysis_index = load_analysis_index()
    return all(paper_id(paper) in analysis_index for paper in papers if paper_id(paper))


def load_existing_papers(target_date: str) -> tuple[list[dict], str]:
    papers = papers_for_date(target_date)
    if papers:
        LOGGER.info("Reusing archive papers for %s (%d papers).", target_date, len(papers))
        return papers, "archive"
    return [], ""


def find_latest_existing_or_fetch(
    categories: list[str],
    max_papers: int,
    lookback_days: int,
    start_date: str | None = None,
) -> tuple[str, list[dict], str]:
    cursor = datetime.strptime(parse_date(start_date), "%Y-%m-%d").date()
    for offset in range(lookback_days + 1):
        target_date = (cursor - timedelta(days=offset)).isoformat()
        existing, source = load_existing_papers(target_date)
        if existing:
            return target_date, existing, source

        papers = fetch_papers_for_date_oai(target_date, categories, max_papers=max_papers)
        if papers:
            LOGGER.info("Selected latest non-empty arXiv date: %s (%d papers)", target_date, len(papers))
            append_new_papers(papers, source_date=target_date, existing_index=load_paper_index())
            return target_date, papers, "fetched"
        LOGGER.info("No papers found for %s; checking previous day", target_date)
    raise RuntimeError(f"No arXiv papers found in the last {lookback_days + 1} days from {cursor.isoformat()}.")


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
        new_papers = fetch_papers_for_date_oai(target_date, args.categories, max_papers=args.max_papers)
        if new_papers:
            appended, _ = append_new_papers(new_papers, source_date=target_date, existing_index=load_paper_index())
            LOGGER.info("Fetched %d paper(s) for %s, appended %d to archive.", len(new_papers), target_date, appended)
        papers, source = load_existing_papers(target_date)
    else:
        target_date, papers, source = find_latest_existing_or_fetch(
            args.categories,
            args.max_papers,
            lookback_days=args.lookback_days,
        )

    LOGGER.info("Starting daily pipeline for %s", target_date)
    LOGGER.info("Using %s paper data for %s.", source or "empty archive", target_date)

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
