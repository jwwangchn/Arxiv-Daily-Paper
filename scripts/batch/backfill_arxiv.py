"""Backfill arXiv metadata into data/archive/papers.jsonl."""

from __future__ import annotations

import argparse
import logging
from datetime import datetime

from commands.fetch import DEFAULT_BACKFILL_WORKERS, backfill_metadata
from lib.config import load_config, parse_date, setup_logging

LOGGER = logging.getLogger("batch.backfill_arxiv")


def parse_args() -> argparse.Namespace:
    config = load_config()
    arxiv_config = config.get("arxiv", {})

    parser = argparse.ArgumentParser(description="Backfill arXiv metadata into data/archive/papers.jsonl.")
    parser.add_argument("--start-date", required=True, help="Start date in YYYY-MM-DD format.")
    parser.add_argument("--end-date", default=None, help="End date in YYYY-MM-DD format. Defaults to today.")
    parser.add_argument("--categories", nargs="+", default=arxiv_config.get("categories", []))
    parser.add_argument("--max-papers", type=int, default=arxiv_config.get("max_papers", 30))
    parser.add_argument("--workers", type=int, default=DEFAULT_BACKFILL_WORKERS)
    parser.add_argument(
        "--use-browse-fallback",
        action="store_true",
        help="Use the slower arXiv browse-page fallback if arxiv.py and OAI-PMH fail.",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Compatibility flag; backfill_arxiv.py only fetches metadata and never calls DeepSeek.",
    )
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date) if args.end_date else datetime.today().date().isoformat()

    if not args.metadata_only:
        LOGGER.info("No analysis mode exists here; running metadata-only backfill.")

    stats = backfill_metadata(
        start_date=start_date,
        end_date=end_date,
        categories=args.categories,
        max_papers=args.max_papers,
        workers=args.workers,
        use_browse_fallback=args.use_browse_fallback,
    )
    LOGGER.info("Backfill completed: %s", stats)


if __name__ == "__main__":
    main()
