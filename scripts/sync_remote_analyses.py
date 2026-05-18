"""Sync existing analyses from remote D1 to local SQLite.

This prevents re-analyzing papers that were already processed in previous runs
but are not yet in the local CI database. Run this BEFORE analyze_deepseek.py.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import requests

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from lib.db import init_db, get_connection

LOGGER = logging.getLogger("sync_remote_analyses")


def sync_analyses_for_date(conn: object, date: str, worker_url: str) -> int:
    url = f"{worker_url}/api/papers?date={date}"
    try:
        res = requests.get(url, timeout=60)
        res.raise_for_status()
    except Exception as exc:
        LOGGER.warning("Failed to fetch papers for %s: %s", date, exc)
        return 0

    papers = res.json()
    if not isinstance(papers, list):
        papers = papers.get("papers", [])

    synced = 0
    for p in papers:
        analysis = p.get("analysis")
        if not analysis:
            continue

        arxiv_id = p.get("arxiv_id")
        if not arxiv_id:
            continue

        conn.execute(
            """INSERT OR IGNORE INTO analyses
            (arxiv_id, analysis_version, model, analyzed_at,
             tldr, research_motivation, problem, phenomenon_analysis, method,
             contributions, experiments, limitations,
             primary_area_en, primary_area, category, sub_area,
             tags, reading_priority, recommended_action, raw_response)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                arxiv_id,
                analysis.get("analysis_version", "1"),
                analysis.get("model", ""),
                analysis.get("analyzed_at", ""),
                analysis.get("tldr", ""),
                analysis.get("research_motivation", ""),
                analysis.get("problem", ""),
                analysis.get("phenomenon_analysis", ""),
                analysis.get("method", ""),
                json.dumps(analysis.get("contributions", [])),
                analysis.get("experiments", ""),
                json.dumps(analysis.get("limitations", [])),
                analysis.get("primary_area_en", ""),
                analysis.get("primary_area", ""),
                analysis.get("category", ""),
                analysis.get("sub_area", ""),
                json.dumps(analysis.get("tags", [])),
                analysis.get("reading_priority", ""),
                analysis.get("recommended_action", ""),
                "",
            ),
        )
        synced += 1

    return synced


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync analyses from D1 to local SQLite.")
    parser.add_argument("--dates", nargs="+", required=True, help="Target dates to sync.")
    parser.add_argument("--worker-url", default=os.environ.get("ARXIV_DAILY_WORKER_URL"))
    args = parser.parse_args()

    if not args.worker_url:
        LOGGER.warning("WORKER_URL not set, skipping remote sync.")
        return

    init_db()
    conn = get_connection()
    total = 0

    for date in args.dates:
        count = sync_analyses_for_date(conn, date, args.worker_url)
        total += count
        LOGGER.info("Synced %d existing analyses for %s.", count, date)

    conn.commit()
    conn.close()
    LOGGER.info("Total synced: %d analyses.", total)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    main()
