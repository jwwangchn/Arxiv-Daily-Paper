"""Independent JSONl storage for non-arXiv paper sources."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from lib.config import PROJECT_ROOT

LOGGER = logging.getLogger("lib.source_archive")

SOURCES_DIR = PROJECT_ROOT / "data" / "archive" / "sources"


def source_jsonl_path(source: str) -> Path:
    return SOURCES_DIR / f"{source}.jsonl"


def read_source(source: str) -> list[dict[str, Any]]:
    path = source_jsonl_path(source)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                LOGGER.warning("Bad JSONL in %s line %d: %s", path, i, e)
    return records


def load_source_index(source: str) -> dict[str, dict[str, Any]]:
    return {r.get("paper_id"): r for r in read_source(source) if r.get("paper_id")}


def append_source_papers(
    source: str,
    papers: list[dict[str, Any]],
    *,
    existing_index: dict[str, dict[str, Any]] | None = None,
) -> tuple[int, int]:
    """Append papers to a source JSONL file. Returns (appended, skipped)."""
    if existing_index is None:
        existing_index = load_source_index(source)

    path = source_jsonl_path(source)
    path.parent.mkdir(parents=True, exist_ok=True)

    appended = 0
    skipped = 0
    seen_in_batch: set[str] = set()

    with path.open("a", encoding="utf-8") as f:
        for paper in papers:
            pid = paper.get("paper_id")
            if not pid or pid in existing_index or pid in seen_in_batch:
                skipped += 1
                continue
            f.write(json.dumps(paper, ensure_ascii=False, separators=(",", ":")) + "\n")
            existing_index[pid] = paper
            seen_in_batch.add(pid)
            appended += 1

    LOGGER.info("Source %s: appended=%d skipped=%d total=%d", source, appended, skipped, len(existing_index))
    return appended, skipped


def source_stats() -> dict[str, dict[str, int]]:
    """Return paper counts per source."""
    stats: dict[str, dict[str, int]] = {}
    if not SOURCES_DIR.exists():
        return stats
    for path in SOURCES_DIR.glob("*.jsonl"):
        source = path.stem
        count = sum(1 for line in path.read_text().splitlines() if line.strip())
        stats[source] = {"count": count, "path": str(path)}
    return stats
