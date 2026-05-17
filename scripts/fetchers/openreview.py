"""OpenReview fetcher — ICLR, NeurIPS, ICML, COLM."""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from fetchers.base import FetchRequest, FetchResult, make_paper_id, normalize_unified_paper
from fetchers.registry import register

LOGGER = logging.getLogger("fetchers.openreview")

VENUE_PREFIX_MAP = {
    "iclr": "ICLR.cc",
    "neurips": "NeurIPS.cc",
    "nips": "NeurIPS.cc",
    "icml": "ICML.cc",
    "colm": "COLMConf.org",
    "aaai": "AAAI.org",
}


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _content_value(content: dict, key: str) -> Any:
    raw = content.get(key)
    if isinstance(raw, dict) and "value" in raw:
        return raw.get("value")
    return raw


def _normalize_ts_ms(value: Any) -> str:
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return ""
    if ms <= 0:
        return ""
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_authors(content: dict) -> list[str]:
    authors = _content_value(content, "authors")
    if isinstance(authors, list):
        return [_norm(item) for item in authors if _norm(item)]
    text = _norm(authors)
    if not text:
        return []
    return [_norm(item) for item in re.split(r"[;,]+", text) if _norm(item)]


def _reply_invitation(reply: dict) -> str:
    invitations = reply.get("invitations") or []
    if isinstance(invitations, list) and invitations:
        return _norm(invitations[0])
    return _norm(reply.get("invitation", ""))


def _extract_replies(note: Any) -> list[dict]:
    details = getattr(note, "details", {}) or {} if not isinstance(note, dict) else (note.get("details") or {})
    replies = details.get("replies") if isinstance(details, dict) else []
    if isinstance(replies, list):
        return [r for r in replies if isinstance(r, dict)]
    return []


def _extract_decision_text(note: Any) -> str:
    for reply in _extract_replies(note):
        inv = _reply_invitation(reply).lower()
        if not inv.endswith("/-/decision"):
            continue
        content = reply.get("content") or {}
        decision = _content_value(content, "decision")
        recommendation = _content_value(content, "recommendation")
        text = _norm(decision) or _norm(recommendation)
        if text:
            return text
    return ""


def _has_public_reader(note: Any) -> bool:
    readers = getattr(note, "readers", []) or {} if not isinstance(note, dict) else (note.get("readers") or [])
    if not isinstance(readers, list):
        return False
    lowered = {str(item).strip().lower() for item in readers}
    return "everyone" in lowered or "openreview.net/everyone" in lowered


def classify_status(note: Any) -> str:
    decision = _extract_decision_text(note).lower()
    if decision:
        if "accept" in decision and "reject" not in decision:
            return "accepted"
        if "withdraw" in decision:
            return "withdrawn" if _has_public_reader(note) else "withdrawn-private"
        if "reject" in decision:
            return "rejected" if _has_public_reader(note) else "rejected-private"
    return "public" if _has_public_reader(note) else "submission"


def should_keep(status: str, public_only: bool) -> bool:
    if status == "accepted":
        return True
    # By default only keep accepted papers for conference proceedings
    return False


def build_venue_id(conference: str, year: int) -> str:
    prefix = VENUE_PREFIX_MAP.get(conference.lower(), conference)
    return f"{prefix}/{year}/Conference"


def parse_note(note: Any, conference: str, year: int) -> dict[str, Any] | None:
    note_id = _norm(getattr(note, "id", None) if not isinstance(note, dict) else note.get("id"))
    forum = _norm(getattr(note, "forum", None) if not isinstance(note, dict) else note.get("forum")) or note_id
    content = getattr(note, "content", {}) or {} if not isinstance(note, dict) else (note.get("content") or {})
    if not isinstance(content, dict):
        content = {}

    title = _norm(_content_value(content, "title"))
    abstract = _norm(_content_value(content, "abstract"))
    if not note_id or not title:
        return None

    status = classify_status(note)
    if not should_keep(status, public_only=True):
        return None

    pdf_field = _norm(_content_value(content, "pdf"))
    pdf_url = ""
    if pdf_field:
        pdf_url = pdf_field if pdf_field.startswith("http") else f"https://openreview.net{pdf_field}"
    elif _has_public_reader(note):
        pdf_url = f"https://openreview.net/pdf?id={forum}"

    if not pdf_url:
        return None

    published = (
        _normalize_ts_ms(getattr(note, "pdate", None) if not isinstance(note, dict) else note.get("pdate"))
        or _normalize_ts_ms(getattr(note, "cdate", None) if not isinstance(note, dict) else note.get("cdate"))
        or _normalize_ts_ms(getattr(note, "tcdate", None) if not isinstance(note, dict) else note.get("tcdate"))
    )
    source_date = published[:10] if published else ""

    paper_id = make_paper_id("openreview", conference, year, note_id)

    return normalize_unified_paper(
        paper_id=paper_id,
        source="openreview",
        venue=conference.upper().replace("NIPS", "NEURIPS"),
        year=year,
        track="Conference",
        status=status,
        source_paper_id=note_id,
        title=title,
        authors=_normalize_authors(content),
        abstract=abstract,
        published=published,
        entry_url=f"https://openreview.net/forum?id={forum}",
        pdf_url=pdf_url,
        source_date=source_date,
    )


@register("openreview")
class OpenReviewFetcher:
    name = "openreview"

    def fetch(self, request: FetchRequest) -> FetchResult:
        try:
            import openreview
        except ImportError as e:
            raise RuntimeError("Missing openreview-py. Run: pip install openreview-py") from e

        venue = (request.venue or "").strip()
        if not venue:
            return FetchResult(warnings=["OpenReview fetcher requires --venue (e.g. ICLR, NeurIPS, ICML)"])

        years = []
        if request.year:
            years = [request.year]
        elif request.start_year and request.end_year:
            years = list(range(request.start_year, request.end_year + 1))
        else:
            # Default: last 3 years including current
            current_year = datetime.now(timezone.utc).year
            years = list(range(current_year - 2, current_year + 1))

        username = os.environ.get("OPENREVIEW_USERNAME", "")
        password = os.environ.get("OPENREVIEW_PASSWORD", "")

        if username and password:
            client = openreview.api.OpenReviewClient(
                baseurl="https://api2.openreview.net",
                username=username,
                password=password,
            )
            LOGGER.info("OpenReview: authenticated mode")
        else:
            client = openreview.api.OpenReviewClient(baseurl="https://api2.openreview.net")
            LOGGER.info("OpenReview: anonymous/public-only mode")

        result = FetchResult()
        total = 0
        accepted = 0

        for year in years:
            venue_id = build_venue_id(venue, year)
            submission_invitation = None

            try:
                venue_group = client.get_group(venue_id)
                if getattr(venue_group, "content", None):
                    raw = venue_group.content.get("submission_id")
                    if isinstance(raw, dict):
                        submission_invitation = _norm(raw.get("value"))
            except Exception as e:
                result.warnings.append(f"Failed to get venue group {venue_id}: {e}")
                continue

            if not submission_invitation:
                submission_invitation = f"{venue_id}/-/Submission"

            LOGGER.info("OpenReview: fetching %s via %s", venue_id, submission_invitation)

            try:
                notes = client.get_all_notes(invitation=submission_invitation, details="replies")
            except Exception as e:
                result.warnings.append(f"Failed to get notes for {submission_invitation}: {e}")
                continue

            LOGGER.info("OpenReview: %s returned %d notes", venue_id, len(notes))

            for note in notes:
                if request.max_papers and total >= request.max_papers:
                    break

                paper = parse_note(note, venue, year)
                if not paper:
                    continue

                total += 1
                if paper.get("status") == "accepted":
                    accepted += 1

                result.papers.append(paper)

            result.source_stats[venue_id] = len(notes)
            LOGGER.info("OpenReview: %s -> %d papers kept (%d accepted)", venue_id, total, accepted)

        LOGGER.info("OpenReview fetch complete: %d total, %d accepted", total, accepted)
        return result
