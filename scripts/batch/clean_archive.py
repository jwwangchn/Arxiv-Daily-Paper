"""Clean archive JSONL files so papers and analyses are unique by arxiv_id."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from commands.analyze import DEFAULT_ANALYSIS_VERSION, DEFAULT_DEEPSEEK_MODEL, normalize_analysis
from lib.archive import ANALYSES_JSONL, PAPERS_JSONL, analysis_key, paper_id, paper_source_date, read_jsonl, utc_now_iso
from lib.config import setup_logging

LOGGER = logging.getLogger("batch.clean_archive")


def sort_date(value: str) -> str:
    return value if value else "9999-99-99"


def choose_paper(existing: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    existing_date = sort_date(paper_source_date(existing))
    candidate_date = sort_date(paper_source_date(candidate))
    if candidate_date < existing_date:
        return candidate
    if candidate_date == existing_date and len(json.dumps(candidate, ensure_ascii=False)) > len(json.dumps(existing, ensure_ascii=False)):
        return candidate
    return existing


def version_rank(record: dict[str, Any], preferred_version: str) -> tuple[int, str]:
    version = str(record.get("analysis_version") or "")
    if version == preferred_version:
        return 0, str(record.get("analyzed_at") or "")
    if version:
        return 1, str(record.get("analyzed_at") or "")
    return 2, str(record.get("analyzed_at") or "")


def normalized_analysis_record(record: dict[str, Any], preferred_version: str, model: str) -> dict[str, Any] | None:
    arxiv_id = analysis_key(record)
    analysis = record.get("analysis")
    if not arxiv_id or not isinstance(analysis, dict):
        return None

    normalized = {
        "arxiv_id": arxiv_id,
        "analysis_version": str(record.get("analysis_version") or preferred_version),
        "model": str(record.get("model") or model),
        "analyzed_at": str(record.get("analyzed_at") or utc_now_iso()),
        "analysis": normalize_analysis(dict(analysis)),
    }
    return normalized


def clean_papers(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    by_id: dict[str, dict[str, Any]] = {}
    skipped = 0
    for record in records:
        arxiv_id = paper_id(record)
        if not arxiv_id:
            skipped += 1
            continue
        if arxiv_id in by_id:
            by_id[arxiv_id] = choose_paper(by_id[arxiv_id], record)
        else:
            by_id[arxiv_id] = record
    return list(by_id.values()), skipped


def clean_analyses(records: list[dict[str, Any]], preferred_version: str, model: str) -> tuple[list[dict[str, Any]], int]:
    by_id: dict[str, dict[str, Any]] = {}
    skipped = 0
    for raw_record in records:
        record = normalized_analysis_record(raw_record, preferred_version, model)
        if not record:
            skipped += 1
            continue
        arxiv_id = record["arxiv_id"]
        if arxiv_id in by_id:
            current = by_id[arxiv_id]
            if version_rank(record, preferred_version) <= version_rank(current, preferred_version):
                by_id[arxiv_id] = record
        else:
            by_id[arxiv_id] = record
    return list(by_id.values()), skipped


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            f.write("\n")
    tmp_path.replace(path)


def backup(path: Path) -> Path:
    backup_path = path.with_suffix(path.suffix + f".bak-{utc_now_iso().replace(':', '').replace('Z', '')}")
    shutil.copy2(path, backup_path)
    return backup_path


def clean_archive(preferred_version: str, model: str, dry_run: bool = False) -> None:
    papers = read_jsonl(PAPERS_JSONL)
    analyses = read_jsonl(ANALYSES_JSONL)

    clean_paper_records, skipped_papers = clean_papers(papers)
    clean_analysis_records, skipped_analyses = clean_analyses(analyses, preferred_version, model)

    paper_ids = {paper_id(record) for record in clean_paper_records}
    clean_analysis_records = [record for record in clean_analysis_records if record["arxiv_id"] in paper_ids]

    LOGGER.info(
        "papers: %d -> %d unique, skipped_missing_id=%d",
        len(papers),
        len(clean_paper_records),
        skipped_papers,
    )
    LOGGER.info(
        "analyses: %d -> %d unique, skipped_invalid=%d",
        len(analyses),
        len(clean_analysis_records),
        skipped_analyses,
    )

    if dry_run:
        LOGGER.info("Dry run only; archive files were not modified.")
        return

    paper_backup = backup(PAPERS_JSONL)
    analysis_backup = backup(ANALYSES_JSONL)
    write_jsonl(PAPERS_JSONL, clean_paper_records)
    write_jsonl(ANALYSES_JSONL, clean_analysis_records)
    LOGGER.info("Backed up papers to %s", paper_backup)
    LOGGER.info("Backed up analyses to %s", analysis_backup)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deduplicate archive JSONL files by arxiv_id.")
    parser.add_argument("--preferred-version", default=DEFAULT_ANALYSIS_VERSION)
    parser.add_argument("--model", default=DEFAULT_DEEPSEEK_MODEL)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    clean_archive(args.preferred_version, args.model, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
