"""Base fetcher interface and unified paper schema."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FetchRequest:
    source: str
    venue: str | None = None
    year: int | None = None
    track: str | None = None
    status: str | None = None
    start_year: int | None = None
    end_year: int | None = None
    max_papers: int | None = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchResult:
    papers: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source_stats: dict[str, int] = field(default_factory=dict)


def make_paper_id(source: str, venue: str, year: int, source_id: str) -> str:
    """Generate a stable paper_id: {source}-{venue_lower}-{year}-{source_id}."""
    return f"{source}-{venue.lower()}-{year}-{source_id}"


def normalize_unified_paper(
    *,
    paper_id: str,
    source: str,
    venue: str,
    year: int,
    title: str,
    authors: list[str],
    abstract: str,
    source_paper_id: str,
    track: str = "",
    status: str = "accepted",
    published: str = "",
    entry_url: str = "",
    pdf_url: str = "",
    source_date: str = "",
    doi: str = "",
    raw_source: dict[str, Any] | None = None,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Build a source-agnostic paper record."""
    from datetime import datetime, timezone

    if not source_date:
        source_date = published[:10] if published else (fetched_at or "")[:10]

    return {
        "paper_id": paper_id,
        "source": source,
        "venue": venue,
        "year": year,
        "track": track,
        "status": status,
        "source_paper_id": source_paper_id,
        "doi": doi,
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "published": published,
        "entry_url": entry_url,
        "pdf_url": pdf_url,
        "source_date": source_date,
        "fetched_at": fetched_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "raw_source": raw_source or {},
    }
