"""Analyze archived arXiv papers date by date."""

from __future__ import annotations

import argparse
import logging
from datetime import datetime

from commands.analyze import DEFAULT_ANALYSIS_VERSION, analyze_date
from commands.build import build_site
from lib.archive import available_dates, load_analysis_index, paper_id, papers_for_date
from lib.config import parse_date, setup_logging

LOGGER = logging.getLogger("batch.analyze_archive")


def date_range_filter(dates: list[str], start_date: str, end_date: str) -> list[str]:
    return [date for date in dates if start_date <= date <= end_date]


def analyzed_count_for_date(source_date: str, analysis_version: str) -> tuple[int, int]:
    papers = papers_for_date(source_date)
    analysis_index = load_analysis_index()
    analyzed = sum(1 for paper in papers if (paper_id(paper), analysis_version) in analysis_index)
    return analyzed, len(papers)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze archived arXiv papers date by date.")
    parser.add_argument("--start-date", default="2026-04-01", help="Start date in YYYY-MM-DD format.")
    parser.add_argument("--end-date", default=None, help="End date in YYYY-MM-DD format. Defaults to latest archive date.")
    parser.add_argument("--concurrency", type=int, default=None)
    parser.add_argument("--analysis-version", default=DEFAULT_ANALYSIS_VERSION)
    parser.add_argument(
        "--cache-only",
        action="store_true",
        help="Only backfill existing analyzed cache; do not call DeepSeek for missing papers.",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Do not rebuild doc after each completed date.",
    )
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()

    all_dates = available_dates()
    if not all_dates:
        raise RuntimeError("No archived papers found. Run backfill_arxiv.py first.")

    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date) if args.end_date else all_dates[-1]
    dates = date_range_filter(all_dates, start_date, end_date)
    if not dates:
        raise RuntimeError(f"No archived dates found from {start_date} to {end_date}.")

    LOGGER.info(
        "Analyzing archive from %s to %s (%d date(s)), version=%s, cache_only=%s.",
        start_date,
        end_date,
        len(dates),
        args.analysis_version,
        args.cache_only,
    )

    for index, source_date in enumerate(dates, start=1):
        analyzed_before, total = analyzed_count_for_date(source_date, args.analysis_version)
        if total and analyzed_before >= total:
            LOGGER.info("[%d/%d] %s already complete (%d/%d).", index, len(dates), source_date, analyzed_before, total)
            continue

        LOGGER.info("[%d/%d] Analyzing %s (%d/%d cached).", index, len(dates), source_date, analyzed_before, total)
        analyze_date(
            source_date,
            concurrency=args.concurrency,
            analysis_version=args.analysis_version,
            cache_only=args.cache_only,
        )

        analyzed_after, total_after = analyzed_count_for_date(source_date, args.analysis_version)
        LOGGER.info("[%d/%d] Completed %s (%d/%d cached).", index, len(dates), source_date, analyzed_after, total_after)
        if not args.skip_build:
            build_site(use_mock=False)

    if not args.skip_build:
        build_site(use_mock=False)
    LOGGER.info("Archive analysis run finished at %s.", datetime.now().isoformat(timespec="seconds"))


if __name__ == "__main__":
    main()
