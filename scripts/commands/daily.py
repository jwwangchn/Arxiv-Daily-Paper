"""Run the full arXiv Daily Paper pipeline."""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta

from commands.analyze import analyze_date
from commands.fetch import fetch_papers_for_date_oai
from lib.db import append_new_papers, load_analysis_index, load_paper_index, paper_id, papers_for_date
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
    return parser.parse_args()


def is_fully_analyzed(target_date: str, papers: list[dict]) -> bool:
    if not papers:
        return False
    analysis_index = load_analysis_index()
    return all(paper_id(paper) in analysis_index for paper in papers if paper_id(paper))


def main() -> None:
    setup_logging()
    ensure_dirs()
    args = parse_args()

    if args.date:
        target_date = parse_date(args.date)
        new_papers = fetch_papers_for_date_oai(target_date, args.categories, max_papers=args.max_papers)
        if new_papers:
            appended, _ = append_new_papers(new_papers, source_date=target_date, existing_index=load_paper_index())
            LOGGER.info("Fetched %d paper(s) for %s, appended %d to database.", len(new_papers), target_date, appended)
        papers = papers_for_date(target_date)
    else:
        cursor = datetime.strptime(parse_date(args.date), "%Y-%m-%d").date() if args.date else datetime.today().date()
        papers = []
        target_date = ""
        for offset in range(args.lookback_days + 1):
            candidate_date = (cursor - timedelta(days=offset)).isoformat()
            existing = papers_for_date(candidate_date)
            if existing:
                target_date = candidate_date
                papers = existing
                LOGGER.info("Reusing database papers for %s (%d papers).", target_date, len(papers))
                break
            fetched = fetch_papers_for_date_oai(candidate_date, args.categories, max_papers=args.max_papers)
            if fetched:
                target_date = candidate_date
                papers = fetched
                appended, _ = append_new_papers(fetched, source_date=target_date, existing_index=load_paper_index())
                LOGGER.info("Fetched %d paper(s) for %s, appended %d to database.", len(fetched), target_date, appended)
                break
            LOGGER.info("No papers found for %s; checking previous day", candidate_date)

        if not papers:
            raise RuntimeError(f"No arXiv papers found in the last {args.lookback_days + 1} days.")

    LOGGER.info("Starting daily pipeline for %s", target_date)

    if is_fully_analyzed(target_date, papers):
        LOGGER.info("%s is already fully analyzed; skipping DeepSeek calls.", target_date)
    else:
        analyze_date(target_date, concurrency=args.concurrency)

    LOGGER.info("Pipeline completed for %s", target_date)


if __name__ == "__main__":
    main()