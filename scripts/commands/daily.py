"""Run the full arXiv Daily Paper pipeline."""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path

from commands.analyze import analyze_date
from commands.build import build_site
from commands.fetch import fetch_papers, merge_papers, save_raw
from lib.config import PROJECT_ROOT, ensure_dirs, load_config, parse_date, read_json, setup_logging

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


def _date_path(folder: str, target_date: str) -> Path:
    month = target_date[:7]
    monthly = PROJECT_ROOT / "data" / folder / month / f"{target_date}.json"
    legacy = PROJECT_ROOT / "data" / folder / f"{target_date}.json"
    if monthly.exists():
        return monthly
    return legacy


def is_fully_analyzed(target_date: str, papers: list[dict]) -> bool:
    if not papers:
        return False
    output_path = _date_path("analyzed", target_date)
    if not output_path.exists():
        return False
    existing = read_json(output_path)
    existing_by_id = {paper.get("arxiv_id"): paper for paper in existing.get("papers", []) if paper.get("arxiv_id")}
    for paper in papers:
        existing_paper = existing_by_id.get(paper.get("arxiv_id"))
        if not existing_paper or ("analysis" not in existing_paper and "analysis_error" not in existing_paper):
            return False
    return True


def load_existing_papers(target_date: str) -> tuple[list[dict], str]:
    for folder in ["raw", "analyzed"]:
        path = _date_path(folder, target_date)
        if not path.exists():
            continue
        bundle = read_json(path)
        papers = bundle.get("papers", [])
        if papers:
            LOGGER.info("Reusing existing %s data for %s (%d papers).", folder, target_date, len(papers))
            return papers, folder
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

        papers = fetch_papers(target_date, categories, max_papers)
        if papers:
            LOGGER.info("Selected latest non-empty arXiv date: %s (%d papers)", target_date, len(papers))
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
        papers, source = load_existing_papers(target_date)
        new_papers = fetch_papers(target_date, args.categories, args.max_papers)
        if new_papers:
            if papers and source:
                papers = merge_papers(papers, new_papers)
                LOGGER.info("Merged %d new paper(s) into existing %d for %s.", len(new_papers), len(papers), target_date)
                source = "raw"
            else:
                papers = new_papers
                source = "fetched"
    else:
        target_date, papers, source = find_latest_existing_or_fetch(
            args.categories,
            args.max_papers,
            lookback_days=args.lookback_days,
        )

    LOGGER.info("Starting daily pipeline for %s", target_date)
    if source in {"fetched", "raw"}:
        save_raw(target_date, papers)
    else:
        LOGGER.info("Using existing analyzed data for %s; raw save is not needed.", target_date)

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
