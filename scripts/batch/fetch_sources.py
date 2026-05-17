"""Batch fetch conference papers from configured sources."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

scripts_dir = Path(__file__).parent.parent
sys.path.insert(0, str(scripts_dir))
os.chdir(scripts_dir.parent)

from fetchers import FetchRequest, fetch_source, available_sources
from lib.source_archive import append_source_papers, source_stats
from lib.config import setup_logging

LOGGER = logging.getLogger("batch.fetch_sources")

DEFAULT_SOURCES = {
    "openreview": [
        {"venue": "ICLR", "years": [2024, 2025, 2026]},
        {"venue": "NeurIPS", "years": [2024, 2025]},
        {"venue": "ICML", "years": [2024, 2025]},
    ],
    "acl_anthology": [
        {"venue": "acl", "years": [2024, 2025]},
        {"venue": "emnlp", "years": [2024, 2025]},
    ],
    "aaai_ojs": [
        {"venue": "aaai", "years": [2026]},
    ],
}


def fetch_one(source: str, venue: str, year: int) -> tuple[int, int]:
    """Fetch one venue/year. Returns (appended, skipped)."""
    request = FetchRequest(source=source, venue=venue, year=year)
    result = fetch_source(request)

    if not result.papers:
        LOGGER.info("%s/%s/%d: no papers fetched", source, venue, year)
        if result.warnings:
            for w in result.warnings:
                LOGGER.warning("  %s", w)
        return 0, 0

    appended, skipped = append_source_papers(source, result.papers)
    LOGGER.info("%s/%s/%d: fetched=%d appended=%d skipped=%d",
                source, venue, year, len(result.papers), appended, skipped)
    return appended, skipped


def main() -> None:
    setup_logging()

    parser = argparse.ArgumentParser(description="Batch fetch conference papers.")
    parser.add_argument("--source", default=None, help="Source to fetch (default: all configured)")
    parser.add_argument("--venue", default=None, help="Venue name (e.g. ICLR)")
    parser.add_argument("--year", type=int, default=None, help="Year to fetch")
    parser.add_argument("--list-sources", action="store_true", help="List available sources")
    parser.add_argument("--list-stats", action="store_true", help="Show current source stats")
    args = parser.parse_args()

    if args.list_sources:
        print("Available sources:", available_sources())
        return

    if args.list_stats:
        stats = source_stats()
        if not stats:
            print("No source data yet.")
        else:
            for source, info in sorted(stats.items()):
                print(f"  {source}: {info['count']} papers ({info['path']})")
        return

    if args.source and args.venue and args.year:
        fetch_one(args.source, args.venue, args.year)
        return

    # Batch mode: fetch all configured sources
    sources_to_fetch = DEFAULT_SOURCES
    if args.source:
        if args.source not in DEFAULT_SOURCES:
            LOGGER.error("Source %s not in default config. Available: %s", args.source, list(DEFAULT_SOURCES.keys()))
            return
        sources_to_fetch = {args.source: DEFAULT_SOURCES[args.source]}

    total_appended = 0
    total_skipped = 0

    for source, venues in sources_to_fetch.items():
        for vcfg in venues:
            venue = vcfg["venue"]
            for year in vcfg.get("years", []):
                if args.venue and venue.lower() != args.venue.lower():
                    continue
                if args.year and year != args.year:
                    continue
                a, s = fetch_one(source, venue, year)
                total_appended += a
                total_skipped += s

    LOGGER.info("Batch fetch complete: appended=%d skipped=%d", total_appended, total_skipped)

    # Show final stats
    stats = source_stats()
    for source, info in sorted(stats.items()):
        LOGGER.info("  %s: %d papers total", source, info["count"])


if __name__ == "__main__":
    main()
