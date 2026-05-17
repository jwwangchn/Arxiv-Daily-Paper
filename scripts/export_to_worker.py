"""Export local archive data to the Cloudflare Worker API."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from lib.archive import ANALYSES_JSONL, PAPERS_JSONL, paper_id, paper_source_date, read_jsonl
from lib.config import setup_logging
from lib.db import DB_PATH, get_connection, init_db

LOGGER = logging.getLogger("export_to_worker")
BATCH_SIZE = 100


def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=None,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=1, pool_maxsize=1)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _safe_json(value: str | None) -> Any:
    if not value:
        return []
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return []


def _analysis_record_from_db(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    return {
        "arxiv_id": data.get("arxiv_id", ""),
        "analysis_version": data.get("analysis_version", ""),
        "model": data.get("model", ""),
        "analyzed_at": data.get("analyzed_at", ""),
        "analysis": {
            "tldr": data.get("tldr", ""),
            "research_motivation": data.get("research_motivation", ""),
            "problem": data.get("problem", ""),
            "phenomenon_analysis": data.get("phenomenon_analysis", ""),
            "method": data.get("method", ""),
            "contributions": _safe_json(data.get("contributions")),
            "experiments": data.get("experiments", ""),
            "limitations": _safe_json(data.get("limitations")),
            "primary_area_en": data.get("primary_area_en", ""),
            "primary_area": data.get("primary_area", ""),
            "category": data.get("category", ""),
            "sub_area": data.get("sub_area", ""),
            "tags": _safe_json(data.get("tags")),
            "reading_priority": data.get("reading_priority", ""),
            "recommended_action": data.get("recommended_action", ""),
        },
        "raw_response": data.get("raw_response", ""),
    }


def _load_from_db(date: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not DB_PATH.exists():
        return [], []

    init_db()
    conn = get_connection(DB_PATH)
    try:
        if date:
            papers_cursor = conn.execute("SELECT * FROM papers WHERE source_date = ? ORDER BY id", (date,))
            analyses_cursor = conn.execute(
                "SELECT a.* FROM analyses a JOIN papers p ON a.arxiv_id = p.id "
                "WHERE p.source_date = ? ORDER BY a.arxiv_id",
                (date,),
            )
        else:
            papers_cursor = conn.execute("SELECT * FROM papers ORDER BY source_date, id")
            analyses_cursor = conn.execute("SELECT * FROM analyses ORDER BY arxiv_id")

        papers = [dict(row) for row in papers_cursor]
        for paper in papers:
            paper["arxiv_id"] = paper.pop("id", paper.get("arxiv_id", ""))
            paper["authors"] = _safe_json(paper.get("authors"))
            paper["categories"] = _safe_json(paper.get("categories"))

        analyses = [_analysis_record_from_db(row) for row in analyses_cursor]
        return papers, analyses
    finally:
        conn.close()


def _load_from_jsonl(date: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    papers = read_jsonl(PAPERS_JSONL)
    if date:
        papers = [paper for paper in papers if paper_source_date(paper) == date]
        paper_ids = {paper_id(paper) for paper in papers}
        analyses = [
            analysis
            for analysis in read_jsonl(ANALYSES_JSONL)
            if str(analysis.get("arxiv_id") or "").strip() in paper_ids
        ]
    else:
        analyses = read_jsonl(ANALYSES_JSONL)
    return papers, analyses


def load_records(source: str, date: str | None) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    if source == "db":
        papers, analyses = _load_from_db(date)
        return "db", papers, analyses
    if source == "jsonl":
        papers, analyses = _load_from_jsonl(date)
        return "jsonl", papers, analyses

    db_papers, db_analyses = _load_from_db(date)
    jsonl_papers, jsonl_analyses = _load_from_jsonl(date)

    if date:
        if db_papers:
            return "db", db_papers, db_analyses
        return "jsonl", jsonl_papers, jsonl_analyses

    if db_papers and len(db_papers) >= len(jsonl_papers):
        return "db", db_papers, db_analyses
    return "jsonl", jsonl_papers, jsonl_analyses


def export_papers(url: str, token: str, papers: list[dict[str, Any]]) -> int:
    if not papers:
        LOGGER.info("No papers to export.")
        return 0

    session = _make_session()
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    total_exported = 0

    for i in range(0, len(papers), BATCH_SIZE):
        batch = papers[i : i + BATCH_SIZE]
        by_date: dict[str, list[dict[str, Any]]] = {}
        for paper in batch:
            date = paper_source_date(paper)
            if not date:
                LOGGER.warning("Skipping paper without source_date: %s", paper_id(paper) or paper.get("id", ""))
                continue
            by_date.setdefault(date, []).append(paper)

        for source_date, date_papers in by_date.items():
            try:
                resp = session.post(
                    f"{url}/api/papers",
                    headers=headers,
                    json={"papers": date_papers, "source_date": source_date},
                    timeout=30,
                )
                if resp.ok:
                    total_exported += int(resp.json().get("inserted", 0))
                else:
                    LOGGER.warning("Failed to export papers for %s: %s", source_date, resp.text)
            except requests.exceptions.RequestException as exc:
                LOGGER.warning("Request failed for %s: %s", source_date, exc)
            time.sleep(0.5)

        LOGGER.info("Exported papers batch %d-%d/%d", i, min(i + BATCH_SIZE, len(papers)), len(papers))

    LOGGER.info("Total paper rows accepted by Worker: %d", total_exported)
    return total_exported


def export_analyses(url: str, token: str, analyses: list[dict[str, Any]]) -> int:
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
                total_exported += int(resp.json().get("inserted", 0))
            else:
                LOGGER.warning("Failed to export analyses batch %d-%d: %s", i, i + BATCH_SIZE, resp.text)
        except requests.exceptions.RequestException as exc:
            LOGGER.warning("Request failed for analyses batch %d-%d: %s", i, i + BATCH_SIZE, exc)
        time.sleep(0.5)

    LOGGER.info("Total analysis rows accepted by Worker: %d", total_exported)
    return total_exported


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export local data to Cloudflare Worker API.")
    parser.add_argument("--url", default=os.environ.get("WORKER_URL", ""), help="Worker API base URL.")
    parser.add_argument("--token", default=os.environ.get("WORKER_TOKEN", ""), help="Worker API token.")
    parser.add_argument("--date", default=None, help="Export only one source_date in YYYY-MM-DD format.")
    parser.add_argument("--full", action="store_true", help="Export all local records.")
    parser.add_argument("--source", choices=["auto", "db", "jsonl"], default="auto", help="Local export source.")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()

    if not args.url:
        raise SystemExit("WORKER_URL is required via --url or env.")
    if not args.token:
        raise SystemExit("WORKER_TOKEN is required via --token or env.")
    if bool(args.date) == bool(args.full):
        raise SystemExit("Use exactly one of --date YYYY-MM-DD or --full.")

    source_name, papers, analyses = load_records(args.source, args.date)
    LOGGER.info(
        "Export source=%s scope=%s papers=%d analyses=%d",
        source_name,
        args.date or "full",
        len(papers),
        len(analyses),
    )

    p = export_papers(args.url.rstrip("/"), args.token, papers)
    a = export_analyses(args.url.rstrip("/"), args.token, analyses)
    LOGGER.info("Export complete: papers=%d analyses=%d", p, a)


if __name__ == "__main__":
    main()
