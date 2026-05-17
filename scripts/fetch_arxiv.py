"""Active arXiv fetch entry point.

This wrapper keeps CI/backward-compatible script names stable while delegating
the actual fetch logic to commands.fetch. Fetch logic should live in one place.
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
from lib.config import PROJECT_ROOT, ensure_dirs, load_config, parse_date, setup_logging, write_json

try:
    from lib.archive import ARCHIVE_DIR, append_new_papers as append_new_papers_jsonl, load_paper_index as load_paper_index_jsonl
    from lib.db import DB_PATH, append_new_papers as append_new_papers_db, load_paper_index as load_paper_index_db

    _HAS_ARCHIVE = True
except ImportError:
    _HAS_ARCHIVE = False

LOGGER = logging.getLogger("fetch_arxiv")


def find_latest_date_with_papers(
    categories: list[str],
    max_papers: int,
    *,
    start_date: str | None = None,
    lookback_days: int = 14,
) -> tuple[str, list[dict[str, Any]]]:
    """Walk backward using the canonical OAI-PMH fetcher only."""
    cursor = datetime.strptime(parse_date(start_date), "%Y-%m-%d").date()
    for offset in range(lookback_days + 1):
        target_date = (cursor - timedelta(days=offset)).isoformat()
        papers = fetch_papers_for_date_oai(target_date, categories, max_papers=max_papers)
        if papers:
            LOGGER.info("Selected latest non-empty arXiv date: %s (%d papers)", target_date, len(papers))
            return target_date, papers
        LOGGER.info("No papers found for %s; checking previous day", target_date)
    raise RuntimeError(f"No arXiv papers found in the last {lookback_days + 1} days from {cursor.isoformat()}.")


def save_raw(target_date: str, papers: list[dict[str, Any]]) -> Path:
    output = PROJECT_ROOT / "data" / "raw" / f"{target_date}.json"
    write_json(output, {"date": target_date, "source": "arxiv", "papers": papers})
    LOGGER.info("Wrote %s", output)

    if _HAS_ARCHIVE and papers:
        try:
            jsonl_index = load_paper_index_jsonl() if (ARCHIVE_DIR / "papers.jsonl").exists() else None
            inserted, skipped = append_new_papers_jsonl(papers, source_date=target_date, existing_index=jsonl_index)
            if inserted:
                LOGGER.info("JSONL: appended %d paper(s) (skipped %d duplicates)", inserted, skipped)
        except Exception as exc:
            LOGGER.warning("Failed to write papers to JSONL: %s", exc)

        try:
            db_index = load_paper_index_db() if DB_PATH.exists() else None
            inserted, skipped = append_new_papers_db(papers, source_date=target_date, existing_index=db_index)
            if inserted:
                LOGGER.info("SQLite: inserted %d paper(s) (skipped %d duplicates)", inserted, skipped)
        except Exception as exc:
            LOGGER.warning("Failed to write papers to SQLite: %s", exc)

    return output


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

    save_raw(target_date, papers)


if __name__ == "__main__":
    main()
