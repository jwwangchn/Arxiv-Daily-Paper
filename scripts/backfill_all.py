"""Batch re-fetch and backfill papers for all dates from start to end."""

import json
import logging
import sys
import os
from datetime import date, timedelta
from pathlib import Path

# Ensure scripts/ is on path
scripts_dir = Path(__file__).parent
sys.path.insert(0, str(scripts_dir))

os.chdir(scripts_dir.parent)  # Change to project root

from lib.config import PROJECT_ROOT, ensure_dirs, setup_logging
from commands.fetch import fetch_papers, merge_papers
from commands.analyze import analyze_date
from commands.build import build_site

LOGGER = logging.getLogger("scripts.backfill")

CATEGORIES = ["cs.CV", "cs.AI", "cs.CL", "cs.LG"]
MAX_PAPERS = 2000
START_DATE = "2026-04-01"


def _date_path(folder: str, target_date: str) -> Path:
    month = target_date[:7]
    monthly = PROJECT_ROOT / "data" / folder / month / f"{target_date}.json"
    legacy = PROJECT_ROOT / "data" / folder / f"{target_date}.json"
    if monthly.exists():
        return monthly
    return legacy


def load_raw_papers(target_date: str) -> list[dict]:
    path = _date_path("raw", target_date)
    if path.exists():
        data = json.loads(path.read_text())
        return data.get("papers", [])
    return []


def load_archive_papers(target_date: str) -> list[dict]:
    """Load papers from archive JSONL for a specific date."""
    papers = []
    for line in open(PROJECT_ROOT / "data" / "archive" / "papers.jsonl"):
        p = json.loads(line)
        if p.get("source_date") == target_date:
            papers.append(p)
    return papers


def is_fully_analyzed(target_date: str, papers: list[dict]) -> bool:
    if not papers:
        return False
    output_path = _date_path("analyzed", target_date)
    if not output_path.exists():
        return False
    existing = json.loads(output_path.read_text())
    existing_by_id = {p.get("arxiv_id"): p for p in existing.get("papers", []) if p.get("arxiv_id")}
    for paper in papers:
        existing_paper = existing_by_id.get(paper.get("arxiv_id"))
        if not existing_paper or ("analysis" not in existing_paper and "analysis_error" not in existing_paper):
            return False
    return True


def main() -> None:
    setup_logging()
    ensure_dirs()

    start = date.fromisoformat(START_DATE)
    today = date.today()
    cur = start
    dates = []
    while cur <= today:
        dates.append(cur.isoformat())
        cur += timedelta(days=1)

    LOGGER.info("Backfilling %d dates from %s to %s", len(dates), start.isoformat(), today.isoformat())

    for idx, target_date in enumerate(dates):
        LOGGER.info("--- [%d/%d] %s ---", idx + 1, len(dates), target_date)

        # Load existing papers from raw files
        existing_papers = load_raw_papers(target_date)

        try:
            new_fetched = fetch_papers(target_date, categories=CATEGORIES, max_papers=MAX_PAPERS)
        except Exception:
            LOGGER.exception("Fetch failed for %s", target_date)
            new_fetched = []

        if not new_fetched:
            LOGGER.info("No papers fetched for %s, skipping", target_date)
            continue

        LOGGER.info("Fetched %d papers", len(new_fetched))

        # Merge with existing
        if existing_papers:
            before = len(existing_papers)
            merged = merge_papers(existing_papers, new_fetched)
            after = len(merged)
            if after > before:
                LOGGER.info("Merged %d -> %d papers (%d new)", before, after, after - before)
                # Save merged raw
                _save_raw(target_date, merged)
            else:
                LOGGER.info("No new papers added (%d existing)", before)
                merged = existing_papers
        else:
            merged = new_fetched
            LOGGER.info("Saved %d new papers", len(merged))
            _save_raw(target_date, merged)

        # Analyze if needed
        if not is_fully_analyzed(target_date, merged):
            try:
                analyze_date(target_date)
                LOGGER.info("Analysis completed for %s", target_date)
            except Exception:
                LOGGER.exception("Analysis failed for %s", target_date)
        else:
            LOGGER.info("Already fully analyzed for %s", target_date)

    LOGGER.info("All dates fetched and analyzed, building site...")
    build_site(use_mock=False)
    LOGGER.info("Done!")


def _save_raw(target_date: str, papers: list[dict]) -> None:
    month = target_date[:7]
    output = PROJECT_ROOT / "data" / "raw" / month / f"{target_date}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump({"date": target_date, "source": "arxiv", "papers": papers}, f, ensure_ascii=False, indent=2)
    LOGGER.info("Wrote %s (%d papers)", output, len(papers))


if __name__ == "__main__":
    main()
