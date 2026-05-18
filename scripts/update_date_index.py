"""Update the static date index file.

Reads from local SQLite and merges with existing docs/data/dates.json.
If the index is missing or empty, it seeds it from the Worker API.
This ensures the calendar always shows full history without querying D1 on every page load.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import requests

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from lib.db import get_connection, init_db
from lib.config import PROJECT_ROOT

LOGGER = logging.getLogger("update_date_index")
DATES_JSON_PATH = PROJECT_ROOT / "docs" / "data" / "dates.json"


def fetch_remote_dates(worker_url: str) -> list[dict]:
    """Fetch full date index from Worker API."""
    try:
        url = f"{worker_url}/api/dates"
        res = requests.get(url, timeout=60)
        res.raise_for_status()
        data = res.json()
        return data.get("dates", [])
    except Exception as exc:
        LOGGER.warning("Failed to fetch remote dates: %s", exc)
        return []


def update_date_index(worker_url: str | None = None) -> None:
    init_db()
    conn = get_connection()
    cursor = conn.execute(
        "SELECT source_date, COUNT(*) as count FROM papers "
        "WHERE source_date != '' GROUP BY source_date"
    )
    local_updates = {row["source_date"]: row["count"] for row in cursor}
    conn.close()

    # Load existing index
    existing_data: dict[str, dict] = {}
    if DATES_JSON_PATH.exists():
        try:
            with DATES_JSON_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
                for d in data.get("dates", []):
                    existing_data[d["date"]] = d
        except Exception:
            pass

    # Seed from Worker API if empty and URL is provided
    if not existing_data and worker_url:
        LOGGER.info("Index is empty; seeding from Worker API...")
        remote_dates = fetch_remote_dates(worker_url)
        for d in remote_dates:
            existing_data[d["date"]] = d

    # Merge local updates
    for date, count in local_updates.items():
        if date in existing_data:
            existing_data[date]["count"] = count
        else:
            existing_data[date] = {
                "date": date,
                "month": date[:7],
                "count": count,
                "analyzed_count": 0,
            }

    if not existing_data:
        LOGGER.info("No dates to write.")
        return

    # Sort and write
    dates = sorted(existing_data.values(), key=lambda x: x["date"], reverse=True)
    DATES_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DATES_JSON_PATH.open("w", encoding="utf-8") as f:
        json.dump({"latest": dates[0]["date"], "dates": dates}, f, ensure_ascii=False, indent=2)

    LOGGER.info("Updated %s with %d dates.", DATES_JSON_PATH, len(dates))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    worker_url = os.environ.get("ARXIV_DAILY_WORKER_URL")
    update_date_index(worker_url)


if __name__ == "__main__":
    main()
