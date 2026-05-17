"""Active arXiv fetch entry point.

Delegates to commands.fetch for actual fetch logic. Writes to SQLite only.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from commands.fetch import fetch_papers_for_date_oai
from lib.config import ensure_dirs, load_config, parse_date, setup_logging
from lib.db import append_new_papers, load_paper_index

LOGGER = logging.getLogger("fetch_arxiv")


def find_latest_date_with_papers(
    categories: list[str],
    max_papers: int,
    *,
    start_date: str | None = None,
    lookback_days: int = 14,
) -> tuple[str, list[dict[str, Any]]]:
    cursor = datetime.strptime(parse_date(start_date), "%Y-%m-%d").date()
    for offset in range(lookback_days + 1):
        target_date = (cursor - timedelta(days=offset)).isoformat()
        papers = fetch_papers_for_date_oai(target_date, categories, max_papers=max_papers)
        if papers:
            LOGGER.info("Selected latest non-empty arXiv date: %s (%d papers)", target_date, len(papers))
            return target_date, papers
        LOGGER.info("No papers found for %s; checking previous day", target_date)
    raise RuntimeError(f"No arXiv papers found in the last {lookback_days + 1} days from {cursor.isoformat()}.")


def parse_args() -> argparse.Namespace:
    config = load_config()
    parser = argparse.ArgumentParser(description="Fetch daily arXiv metadata via OAI-PMH.")
    parser.add_argument("--date", default=None, help="Target date in YYYY-MM-DD format.")
    parser.add_argument("--max-papers", type=int, default=config.get("arxiv", {}).get("max_papers", 30))
    parser.add_argument("--categories", nargs="+", default=config.get("arxiv", {}).get("categories", []))
    parser.add_argument("--latest-with-papers", action="store_true", help="Walk backward to the latest date with papers.")
    parser.add_argument("--lookback-days", type=int, default=14)
    return parser.parse_args()


def main() -> None:
    setup_logging()
    ensure_dirs()
    args = parse_args()

    if args.latest_with_papers:
        target_date, papers = find_latest_date_with_papers(
            args.categories,
            args.max_papers,
            start_date=args.date,
            lookback_days=args.lookback_days,
        )
    else:
        target_date = parse_date(args.date)
        papers = fetch_papers_for_date_oai(target_date, args.categories, max_papers=args.max_papers)
        LOGGER.info("Fetched %d paper(s) via OAI-PMH for %s", len(papers), target_date)

    if not papers:
        LOGGER.info("No papers found for %s.", target_date)
        return

    appended, _ = append_new_papers(papers, source_date=target_date, existing_index=load_paper_index())
    LOGGER.info("Appended %d new paper(s) to database for %s.", appended, target_date)


if __name__ == "__main__":
    main()