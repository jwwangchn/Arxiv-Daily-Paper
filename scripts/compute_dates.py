"""Compute target dates for daily pipeline.

Returns a JSON array of YYYY-MM-DD dates for the past N weekdays
(excluding Saturday and Sunday). Individual paper/analysis skipping
is handled by the Python scripts themselves.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def weekday_dates(backfill_days: int) -> list[str]:
    """Return dates for the past N weekdays, excluding Saturday (5) and Sunday (6)."""
    today = datetime.today().date()
    dates: list[str] = []
    offset = 1
    while len(dates) < backfill_days:
        candidate = today - timedelta(days=offset)
        if candidate.weekday() < 5:  # Mon=0 .. Fri=4
            dates.append(candidate.isoformat())
        offset += 1
    return dates


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute target dates for daily pipeline.")
    parser.add_argument("--backfill-days", type=int, default=3, help="Number of past weekdays to consider.")
    args = parser.parse_args()

    dates = weekday_dates(args.backfill_days)
    print(json.dumps(dates))


if __name__ == "__main__":
    main()
