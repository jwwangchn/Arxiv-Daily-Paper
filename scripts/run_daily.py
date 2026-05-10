from __future__ import annotations

import argparse
import logging

from analyze_deepseek import analyze_date
from build_site import build_site
from fetch_arxiv import fetch_papers, save_raw
from utils import ensure_dirs, load_config, parse_date, setup_logging


LOGGER = logging.getLogger("run_daily")


def parse_args() -> argparse.Namespace:
    config = load_config()
    parser = argparse.ArgumentParser(description="Run the full arXiv Daily Paper Guide pipeline.")
    parser.add_argument("--date", default=None, help="Target date in YYYY-MM-DD format.")
    parser.add_argument("--max-papers", type=int, default=config.get("arxiv", {}).get("max_papers", 30))
    parser.add_argument("--categories", nargs="+", default=config.get("arxiv", {}).get("categories", []))
    parser.add_argument("--mock", action="store_true", help="Skip arXiv and DeepSeek; build the site with mock data.")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    ensure_dirs()
    args = parse_args()

    if args.mock:
        LOGGER.info("Running in mock mode; no external APIs will be called.")
        build_site(use_mock=True)
        return

    target_date = parse_date(args.date)
    LOGGER.info("Starting daily pipeline for %s", target_date)

    papers = fetch_papers(target_date, args.categories, args.max_papers)
    save_raw(target_date, papers)

    analysis_failed = False
    try:
        analyze_date(target_date)
    except Exception:
        analysis_failed = True
        LOGGER.exception("DeepSeek analysis step failed. Site build will continue with available data.")

    build_site(use_mock=False)
    if analysis_failed:
        raise RuntimeError("Daily pipeline failed during DeepSeek analysis.")
    LOGGER.info("Pipeline completed for %s", target_date)


if __name__ == "__main__":
    main()
