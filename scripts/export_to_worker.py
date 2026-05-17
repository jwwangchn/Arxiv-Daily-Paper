"""Export new papers and analyses from local archive to the Cloudflare Worker API."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from lib.config import setup_logging
from lib.archive import PAPERS_JSONL, ANALYSES_JSONL, read_jsonl

LOGGER = logging.getLogger("export_to_worker")
BATCH_SIZE = 100


def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry, pool_connections=1, pool_maxsize=1)
    session.mount("https://", adapter)
    return session


def export_papers(url: str, token: str) -> int:
    """Export papers.jsonl to Worker API."""
    papers = read_jsonl(PAPERS_JSONL)
    if not papers:
        LOGGER.info("No papers to export.")
        return 0

    session = _make_session()
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    total_exported = 0

    for i in range(0, len(papers), BATCH_SIZE):
        batch = papers[i : i + BATCH_SIZE]
        # Group by source_date for the API
        by_date: dict[str, list] = {}
        for paper in batch:
            date = paper.get("source_date", "")
            by_date.setdefault(date, []).append(paper)

        for date, date_papers in by_date.items():
            try:
                resp = session.post(
                    f"{url}/api/papers",
                    headers=headers,
                    json={"papers": date_papers, "source_date": date},
                    timeout=30,
                )
                if resp.ok:
                    result = resp.json()
                    total_exported += result.get("inserted", 0)
                else:
                    LOGGER.warning("Failed to export papers for %s: %s", date, resp.text)
            except requests.exceptions.RequestException as exc:
                LOGGER.warning("Request failed for %s: %s", date, exc)
            time.sleep(0.5)

        LOGGER.info("Exported batch %d-%d/%d", i, min(i + BATCH_SIZE, len(papers)), len(papers))

    LOGGER.info("Total papers exported: %d", total_exported)
    return total_exported


def export_analyses(url: str, token: str) -> int:
    """Export analyses.jsonl to Worker API."""
    analyses = read_jsonl(ANALYSES_JSONL)
    if not analyses:
        LOGGER.info("No analyses to export.")
        return 0

    session = _make_session()
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    total_exported = 0

    for i in range(0, len(analyses), BATCH_SIZE):
        batch = analyses[i : i + BATCH_SIZE]
        try:
            resp = session.post(
                f"{url}/api/analyses",
                headers=headers,
                json={"analyses": batch},
                timeout=30,
            )
            if resp.ok:
                result = resp.json()
                total_exported += result.get("inserted", 0)
            else:
                LOGGER.warning("Failed to export analyses batch %d-%d: %s", i, i + BATCH_SIZE, resp.text)
        except requests.exceptions.RequestException as exc:
            LOGGER.warning("Request failed for analyses batch %d-%d: %s", i, i + BATCH_SIZE, exc)
        time.sleep(0.5)

    LOGGER.info("Total analyses exported: %d", total_exported)
    return total_exported


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Export local data to Cloudflare Worker API.")
    parser.add_argument("--url", required=True, help="Worker API base URL.")
    parser.add_argument("--token", required=True, help="Worker API token.")
    args = parser.parse_args()

    p = export_papers(args.url, args.token)
    a = export_analyses(args.url, args.token)
    LOGGER.info("Export complete: papers=%d analyses=%d", p, a)


if __name__ == "__main__":
    main()
