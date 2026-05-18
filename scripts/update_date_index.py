"""Update the static date index file from local SQLite.

Generates docs/data/dates.json to reduce D1 read costs for the calendar.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import sys

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from lib.db import get_connection, init_db
from lib.config import PROJECT_ROOT

LOGGER = logging.getLogger("update_date_index")
DATES_JSON_PATH = PROJECT_ROOT / "docs" / "data" / "dates.json"


def update_date_index() -> None:
    init_db()
    conn = get_connection()
    cursor = conn.execute(
        "SELECT source_date, COUNT(*) as count FROM papers "
        "WHERE source_date != '' GROUP BY source_date ORDER BY source_date DESC"
    )
    dates = []
    for row in cursor:
        dates.append({
            "date": row["source_date"],
            "month": row["source_date"][:7],
            "count": row["count"],
            "analyzed_count": 0,  # Placeholder; can be enhanced later if needed
        })

    conn.close()

    DATES_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DATES_JSON_PATH.open("w", encoding="utf-8") as f:
        json.dump({"latest": dates[0]["date"] if dates else "", "dates": dates}, f, ensure_ascii=False, indent=2)

    LOGGER.info("Updated %s with %d dates.", DATES_JSON_PATH, len(dates))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    update_date_index()
