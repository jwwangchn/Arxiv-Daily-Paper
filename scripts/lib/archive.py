"""Archive store — now backed by SQLite (lib.db) with JSONL fallback.

All public functions keep the same signatures for backward compatibility.
When the database exists and has data, SQL queries are used.
Otherwise the original JSONL path is used as a fallback.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.config import PROJECT_ROOT
from lib import db as db_layer


ARCHIVE_DIR = PROJECT_ROOT / "data" / "archive"
PAPERS_JSONL = ARCHIVE_DIR / "papers.jsonl"
ANALYSES_JSONL = ARCHIVE_DIR / "analyses.jsonl"


def _use_db() -> bool:
    return db_layer.DB_PATH.exists()


# Re-export helpers
utc_now_iso = db_layer.utc_now_iso
paper_id = db_layer.paper_id
paper_source_date = db_layer.paper_source_date
init_db = db_layer.init_db


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if _use_db():
        return db_layer.read_jsonl(path)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                records.append(json.loads(text))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL in {path} at line {line_number}: {exc}") from exc
    return records


def load_paper_index(path: Path = PAPERS_JSONL) -> dict[str, dict[str, Any]]:
    if _use_db():
        return db_layer.load_paper_index()
    return {paper_id(record): record for record in read_jsonl(path) if paper_id(record)}


def load_analysis_index(path: Path = ANALYSES_JSONL) -> dict[str, dict[str, Any]]:
    if _use_db():
        return db_layer.load_analysis_index()
    index: dict[str, dict[str, Any]] = {}
    for record in read_jsonl(path):
        arxiv_id = str(record.get("arxiv_id") or "").strip()
        if arxiv_id:
            index[arxiv_id] = record
    return index


def analysis_key(record: dict[str, Any]) -> str:
    return str(record.get("arxiv_id") or "").strip()


def normalize_archive_paper(paper: dict[str, Any], source_date: str, fetched_at: str | None = None) -> dict[str, Any]:
    archived = dict(paper)
    archived["source_date"] = source_date
    archived["fetched_at"] = fetched_at or utc_now_iso()
    return archived


def append_new_papers(
    papers: Iterable[dict[str, Any]],
    *,
    source_date: str,
    path: Path = PAPERS_JSONL,
    existing_index: dict[str, dict[str, Any]] | None = None,
) -> tuple[int, int]:
    if _use_db():
        return db_layer.append_new_papers(papers, source_date=source_date, existing_index=existing_index)

    index = existing_index if existing_index is not None else load_paper_index(path)
    fetched_at = utc_now_iso()
    new_records: list[dict[str, Any]] = []
    seen_in_batch: set[str] = set()

    for paper in papers:
        arxiv_id = paper_id(paper)
        if not arxiv_id or arxiv_id in index or arxiv_id in seen_in_batch:
            continue
        record = normalize_archive_paper(paper, source_date, fetched_at=fetched_at)
        new_records.append(record)
        seen_in_batch.add(arxiv_id)
        index[arxiv_id] = record

    appended = _append_jsonl(path, new_records)
    return appended, len(seen_in_batch)


def append_new_analyses(
    analyses: Iterable[dict[str, Any]],
    *,
    path: Path = ANALYSES_JSONL,
    existing_index: dict[str, dict[str, Any]] | None = None,
) -> tuple[int, int]:
    if _use_db():
        return db_layer.append_new_analyses(analyses, existing_index=existing_index)

    index = existing_index if existing_index is not None else load_analysis_index(path)
    new_records: list[dict[str, Any]] = []
    seen_in_batch: set[str] = set()

    for analysis in analyses:
        key = analysis_key(analysis)
        if not key or key in index or key in seen_in_batch:
            continue
        record = dict(analysis)
        if not record.get("analyzed_at"):
            record["analyzed_at"] = utc_now_iso()
        new_records.append(record)
        seen_in_batch.add(key)
        index[key] = record

    appended = _append_jsonl(path, new_records)
    return appended, len(seen_in_batch)


def _append_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> int:
    items = list(records)
    if not items:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
            f.write("\n")
    return len(items)


def papers_for_date(source_date: str, path: Path = PAPERS_JSONL) -> list[dict[str, Any]]:
    if _use_db():
        return db_layer.papers_for_date(source_date)
    return [record for record in read_jsonl(path) if paper_source_date(record) == source_date]


def available_dates(path: Path = PAPERS_JSONL) -> list[str]:
    if _use_db():
        return db_layer.available_dates()
    dates = {paper_source_date(record) for record in read_jsonl(path)}
    return sorted(date for date in dates if date)


def latest_analysis_by_arxiv_id(
    *,
    version: str | None = None,
    path: Path = ANALYSES_JSONL,
) -> dict[str, dict[str, Any]]:
    if _use_db():
        return db_layer.latest_analysis_by_arxiv_id(version=version)
    latest: dict[str, dict[str, Any]] = {}
    for record in read_jsonl(path):
        arxiv_id = analysis_key(record)
        analysis_version = str(record.get("analysis_version") or "").strip()
        if not arxiv_id:
            continue
        if version and analysis_version != version:
            continue
        latest[arxiv_id] = record
    return latest


def unanalyzed_papers_for_date(
    source_date: str,
    *,
    analysis_version: str,
    papers_path: Path = PAPERS_JSONL,
    analyses_path: Path = ANALYSES_JSONL,
) -> list[dict[str, Any]]:
    if _use_db():
        return db_layer.unanalyzed_papers_for_date(source_date, analysis_version=analysis_version)
    analyzed = load_analysis_index(analyses_path)
    return [
        paper
        for paper in papers_for_date(source_date, papers_path)
        if paper_id(paper) not in analyzed
    ]


def export_month_data(
    month: str,
    *,
    analysis_version: str | None = None,
    papers_path: Path = PAPERS_JSONL,
    analyses_path: Path = ANALYSES_JSONL,
) -> dict[str, Any]:
    if _use_db():
        return db_layer.export_month_data(month, analysis_version=analysis_version)
    if len(month) != 7:
        raise ValueError("month must use YYYY-MM format")

    analyses_by_id = latest_analysis_by_arxiv_id(version=analysis_version, path=analyses_path)
    dates: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for paper in read_jsonl(papers_path):
        source_date = paper_source_date(paper)
        if not source_date.startswith(f"{month}-"):
            continue
        item = dict(paper)
        analysis_record = analyses_by_id.get(paper_id(paper))
        if analysis_record:
            item["analysis"] = analysis_record.get("analysis", {})
            item["analysis_version"] = analysis_record.get("analysis_version")
            item["analyzed_at"] = analysis_record.get("analyzed_at")
        dates[source_date].append(item)

    return {
        "month": month,
        "dates": {date: dates[date] for date in sorted(dates, reverse=True)},
    }
