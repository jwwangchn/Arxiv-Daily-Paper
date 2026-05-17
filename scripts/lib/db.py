"""SQLite database layer mirroring D1 schema for local development.

Provides the same public API as lib/archive.py but backed by SQLite.
Used locally during development; Cloudflare D1 uses the same schema.
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
SCHEMA_PATH = PROJECT_ROOT / "db" / "schema.sql"


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
            source_date,
            fetched_at,
        ))
        seen_in_batch.add(arxiv_id)
        existing_index[arxiv_id] = {**paper, "source_date": source_date, "fetched_at": fetched_at}

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


def latest_analysis_by_arxiv_id(
    *,
    version: str | None = None,
    db_path: Path = DB_PATH,
) -> dict[str, dict[str, Any]]:
    init_db(db_path)
    conn = get_connection(db_path)
    if version:
        cursor = conn.execute("SELECT * FROM analyses WHERE analysis_version = ?", (version,))
    else:
        cursor = conn.execute("SELECT * FROM analyses")
    latest = {row["arxiv_id"]: _row_to_dict(row) for row in cursor}
    conn.close()
    return latest


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


def export_month_data(
    month: str,
    *,
    analysis_version: str | None = None,
    db_path: Path = DB_PATH,
) -> dict[str, Any]:
    if len(month) != 7:
        raise ValueError("month must use YYYY-MM format")

    init_db(db_path)
    conn = get_connection(db_path)

    papers_cursor = conn.execute("SELECT * FROM papers WHERE source_date LIKE ?", (f"{month}-%",))
    papers = [_row_to_dict(row) for row in papers_cursor]

    analyses_cursor = conn.execute(
        "SELECT a.* FROM analyses a JOIN papers p ON a.arxiv_id = p.id WHERE p.source_date LIKE ?",
        (f"{month}-%",),
    )
    analyses = {row["arxiv_id"]: _row_to_dict(row) for row in analyses_cursor}
    conn.close()

    dates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for paper in papers:
        source_date = paper_source_date(paper)
        item = dict(paper)
        record = analyses.get(paper_id(paper))
        if record:
            if analysis_version and str(record.get("analysis_version", "")) != analysis_version:
                continue
            item["analysis"] = {
                "tldr": record.get("tldr", ""),
                "research_motivation": record.get("research_motivation", ""),
                "problem": record.get("problem", ""),
                "phenomenon_analysis": record.get("phenomenon_analysis", ""),
                "method": record.get("method", ""),
                "contributions": record.get("contributions", []),
                "experiments": record.get("experiments", ""),
                "limitations": record.get("limitations", []),
                "primary_area_en": record.get("primary_area_en", ""),
                "primary_area": record.get("primary_area", ""),
                "category": record.get("category", ""),
                "sub_area": record.get("sub_area", ""),
                "tags": record.get("tags", []),
                "reading_priority": record.get("reading_priority", ""),
                "recommended_action": record.get("recommended_action", ""),
            }
            item["analysis_version"] = record.get("analysis_version")
            item["analyzed_at"] = record.get("analyzed_at")
        dates[source_date].append(item)

    return {"month": month, "dates": {date: dates[date] for date in sorted(dates, reverse=True)}}


def read_jsonl(path: Path, db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """Backward-compatible: reads from DB if available, falls back to JSONL."""
    if db_path.exists():
        conn = get_connection(db_path)
        count = conn.execute("SELECT COUNT(*) as cnt FROM papers").fetchone()["cnt"]
        conn.close()
        if count > 0:
            return list(load_paper_index(db_path).values())

    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            text = line.strip()
            if text:
                records.append(json.loads(text))
    return records
