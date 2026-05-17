"""SQLite database layer mirroring D1 schema for local development.

Used locally during development; Cloudflare D1 uses the same schema in production.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.config import PROJECT_ROOT

DB_PATH = PROJECT_ROOT / "data" / "archive" / "papers.db"
SCHEMA_PATH = PROJECT_ROOT / "migrations" / "0001_create_papers_table.sql"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path: Path = DB_PATH, schema_path: Path = SCHEMA_PATH) -> None:
    if schema_path.exists():
        conn = get_connection(db_path)
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.commit()
        conn.close()


def paper_id(paper: dict[str, Any]) -> str:
    return str(paper.get("arxiv_id") or paper.get("id") or "").strip()


def paper_source_date(paper: dict[str, Any]) -> str:
    value = str(paper.get("source_date") or paper.get("published") or paper.get("updated") or "")
    return value[:10]


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for key in ("authors", "categories", "contributions", "limitations", "tags"):
        if d.get(key):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                d[key] = []
    return d


def append_new_papers(
    papers: Iterable[dict[str, Any]],
    *,
    source_date: str,
    db_path: Path = DB_PATH,
    existing_index: dict[str, dict[str, Any]] | None = None,
) -> tuple[int, int]:
    init_db(db_path)
    conn = get_connection(db_path)

    if existing_index is None:
        existing_index = load_paper_index(db_path)

    fetched_at = utc_now_iso()
    seen_in_batch: set[str] = set()
    new_records: list[tuple] = []

    for paper in papers:
        arxiv_id = paper_id(paper)
        if not arxiv_id or arxiv_id in existing_index or arxiv_id in seen_in_batch:
            continue
        record_source_date = paper_source_date(paper) or source_date

        new_records.append((
            arxiv_id, "arxiv",
            paper.get("title", ""),
            json.dumps(paper.get("authors", []), ensure_ascii=False),
            paper.get("abstract", ""),
            json.dumps(paper.get("categories", []), ensure_ascii=False),
            paper.get("primary_category", ""),
            paper.get("published", ""),
            paper.get("updated", ""),
            paper.get("entry_url", ""),
            paper.get("pdf_url", ""),
            record_source_date,
            fetched_at,
        ))
        seen_in_batch.add(arxiv_id)
        existing_index[arxiv_id] = {**paper, "source_date": record_source_date, "fetched_at": fetched_at}

    if new_records:
        conn.executemany(
            "INSERT OR IGNORE INTO papers "
            "(id, source, title, authors, abstract, categories, primary_category, "
            "published, updated, entry_url, pdf_url, source_date, fetched_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            new_records,
        )
        conn.commit()

    conn.close()
    return len(new_records), len(seen_in_batch)


def append_new_analyses(
    analyses: Iterable[dict[str, Any]],
    *,
    db_path: Path = DB_PATH,
    existing_index: dict[str, dict[str, Any]] | None = None,
) -> tuple[int, int]:
    init_db(db_path)
    conn = get_connection(db_path)

    if existing_index is None:
        existing_index = load_analysis_index(db_path)

    seen_in_batch: set[str] = set()
    new_records: list[tuple] = []

    for analysis in analyses:
        key = str(analysis.get("arxiv_id") or "").strip()
        if not key or key in existing_index or key in seen_in_batch:
            continue

        data = analysis.get("analysis", {})
        new_records.append((
            key,
            str(analysis.get("analysis_version", "")),
            str(analysis.get("model", "")),
            str(analysis.get("analyzed_at") or utc_now_iso()),
            data.get("tldr", ""),
            data.get("research_motivation", ""),
            data.get("problem", ""),
            data.get("phenomenon_analysis", ""),
            data.get("method", ""),
            json.dumps(data.get("contributions", []), ensure_ascii=False),
            data.get("experiments", ""),
            json.dumps(data.get("limitations", []), ensure_ascii=False),
            data.get("primary_area_en", ""),
            data.get("primary_area", ""),
            data.get("category", ""),
            data.get("sub_area", ""),
            json.dumps(data.get("tags", []), ensure_ascii=False),
            data.get("reading_priority", ""),
            data.get("recommended_action", ""),
            analysis.get("raw_response", ""),
        ))
        seen_in_batch.add(key)
        existing_index[key] = analysis

    if new_records:
        conn.executemany(
            "INSERT OR IGNORE INTO analyses "
            "(arxiv_id, analysis_version, model, analyzed_at, "
            "tldr, research_motivation, problem, phenomenon_analysis, method, "
            "contributions, experiments, limitations, "
            "primary_area_en, primary_area, category, sub_area, "
            "tags, reading_priority, recommended_action, raw_response) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            new_records,
        )
        conn.commit()

    conn.close()
    return len(new_records), len(seen_in_batch)


def load_paper_index(db_path: Path = DB_PATH) -> dict[str, dict[str, Any]]:
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.execute("SELECT * FROM papers")
    index = {row["id"]: _row_to_dict(row) for row in cursor}
    conn.close()
    return index


def load_analysis_index(db_path: Path = DB_PATH) -> dict[str, dict[str, Any]]:
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.execute("SELECT * FROM analyses")
    index = {row["arxiv_id"]: _row_to_dict(row) for row in cursor}
    conn.close()
    return index


def papers_for_date(source_date: str, db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.execute("SELECT * FROM papers WHERE source_date = ?", (source_date,))
    papers = [_row_to_dict(row) for row in cursor]
    conn.close()
    return papers


def available_dates(db_path: Path = DB_PATH) -> list[str]:
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.execute("SELECT DISTINCT source_date FROM papers WHERE source_date != '' ORDER BY source_date")
    dates = [row["source_date"] for row in cursor]
    conn.close()
    return dates


def unanalyzed_papers_for_date(
    source_date: str,
    *,
    analysis_version: str,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.execute(
        "SELECT p.* FROM papers p "
        "WHERE p.source_date = ? "
        "AND p.id NOT IN (SELECT arxiv_id FROM analyses WHERE analysis_version = ?)",
        (source_date, analysis_version),
    )
    papers = [_row_to_dict(row) for row in cursor]
    conn.close()
    return papers