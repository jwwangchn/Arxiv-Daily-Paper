"""Analyze all missing papers across all archive dates."""
import sys
import time
from pathlib import Path

scripts_dir = Path(__file__).parent
sys.path.insert(0, str(scripts_dir))

from lib.archive import available_dates
from lib.config import setup_logging
from commands.analyze import analyze_date

def main():
    setup_logging()
    dates = available_dates()
    print(f"Found {len(dates)} dates in archive")

    start = time.time()
    for i, date in enumerate(dates, 1):
        elapsed = time.time() - start
        print(f"\n--- [{i}/{len(dates)}] {date} (elapsed: {elapsed:.0f}s) ---")
        analyze_date(date, concurrency=8)

    total = time.time() - start
    print(f"\nDone! Total time: {total:.0f}s ({total/60:.1f}min)")

if __name__ == "__main__":
    main()
