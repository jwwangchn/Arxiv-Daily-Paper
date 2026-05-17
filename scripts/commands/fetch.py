"""Fetch arXiv papers via OAI-PMH only."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import parsedate_to_datetime
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any
import xml.etree.ElementTree as ET

import requests

from lib.config import ensure_dirs, load_config, normalize_space, parse_date, setup_logging
from lib.db import append_new_papers, load_paper_index
from lib.progress import progress_bar

LOGGER = logging.getLogger("commands.fetch")

OAI_BASE_URL = "https://oaipmh.arxiv.org/oai"
OAI_NS = {"oai": "http://www.openarchives.org/OAI/2.0/", "raw": "http://arxiv.org/OAI/arXivRaw/"}
DEFAULT_BACKFILL_WORKERS = 2


def category_to_set_spec(category: str) -> str:
    parts = category.split(".", maxsplit=1)
    if len(parts) != 2:
        raise ValueError(f"Unsupported arXiv category: {category}")
    group, archive_category = parts
    return f"{group}:{group}:{archive_category}"


def request_oai(session: requests.Session, params: dict[str, str]) -> ET.Element:
    response = session.get(
        OAI_BASE_URL,
        params=params,
        headers={"User-Agent": "ArxivDailyPaperGuide/0.1"},
        timeout=60,
    )
    response.raise_for_status()
    root = ET.fromstring(response.text)
    error = root.find("oai:error", OAI_NS)
    if error is not None:
        code = error.attrib.get("code", "unknown")
        message = normalize_space(error.text or "")
        if code == "noRecordsMatch":
            return root
        raise RuntimeError(f"OAI-PMH error {code}: {message}")
    return root


def oai_text_at(element: ET.Element, path: str) -> str:
    found = element.find(path, OAI_NS)
    return normalize_space(found.text if found is not None else "")


def first_version_date(raw: ET.Element) -> tuple[str, str]:
    versions = raw.findall("raw:version", OAI_NS)
    if not versions:
        return "", ""
    date_text = oai_text_at(versions[0], "raw:date")
    if not date_text:
        return "", ""
    parsed = parsedate_to_datetime(date_text)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.date().isoformat(), parsed.isoformat()


def parse_authors(value: str) -> list[str]:
    return [normalize_space(author) for author in value.split(",") if normalize_space(author)]


def parse_categories(value: str) -> list[str]:
    return [part.strip() for part in value.split() if part.strip()]


def parse_oai_record(record: ET.Element) -> dict[str, Any] | None:
    raw = record.find("oai:metadata/raw:arXivRaw", OAI_NS)
    if raw is None:
        return None

    arxiv_id = oai_text_at(raw, "raw:id")
    if not arxiv_id:
        return None

    source_date, published = first_version_date(raw)
    updated = ""
    versions = raw.findall("raw:version", OAI_NS)
    if versions:
        last_date_text = oai_text_at(versions[-1], "raw:date")
        if last_date_text:
            try:
                updated_dt = parsedate_to_datetime(last_date_text)
                updated = updated_dt.isoformat().replace("+00:00", "Z")
            except (TypeError, ValueError):
                updated = published

    categories = parse_categories(oai_text_at(raw, "raw:categories"))
    primary_category = categories[0] if categories else ""
    base_url = "https://arxiv.org"
    return {
        "arxiv_id": arxiv_id,
        "title": oai_text_at(raw, "raw:title"),
        "authors": parse_authors(oai_text_at(raw, "raw:authors")),
        "abstract": oai_text_at(raw, "raw:abstract"),
        "categories": categories,
        "primary_category": primary_category,
        "published": published.replace("+00:00", "Z") if published else "",
        "updated": updated or (published.replace("+00:00", "Z") if published else ""),
        "entry_url": f"{base_url}/abs/{arxiv_id}",
        "pdf_url": f"{base_url}/pdf/{arxiv_id}",
        "source_date": source_date,
    }


def date_in_range(value: str, start_date: str, end_date: str) -> bool:
    return bool(value) and start_date <= value <= end_date


def sorted_daily_papers(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        papers,
        key=lambda paper: (
            str(paper.get("published") or paper.get("updated") or ""),
            str(paper.get("arxiv_id") or ""),
        ),
        reverse=True,
    )


def fetch_papers_for_date_oai(
    target_date: str,
    categories: list[str],
    *,
    max_papers: int,
    datestamp_lookahead_days: int = 3,
    sleep_seconds: float = 0.5,
) -> list[dict[str, Any]]:
    session = requests.Session()
    seen: set[str] = set()
    papers: list[dict[str, Any]] = []
    target_day = datetime.strptime(target_date, "%Y-%m-%d").date()
    today = datetime.today().date()
    until_datestamp = min(target_day + timedelta(days=datestamp_lookahead_days), today).isoformat()

    for category in categories:
        params = {
            "verb": "ListRecords",
            "metadataPrefix": "arXivRaw",
            "set": category_to_set_spec(category),
            "from": target_date,
            "until": until_datestamp,
        }

        while True:
            root = request_oai(session, params)
            records = root.findall(".//oai:record", OAI_NS)
            for record in records:
                paper = parse_oai_record(record)
                if not paper:
                    continue
                arxiv_id = str(paper.get("arxiv_id") or "")
                if arxiv_id in seen or str(paper.get("source_date") or "") != target_date:
                    continue
                seen.add(arxiv_id)
                papers.append(paper)
                if len(papers) >= max_papers:
                    return sorted_daily_papers(papers)

            token = oai_text_at(root, ".//oai:resumptionToken")
            if not token:
                break
            params = {"verb": "ListRecords", "resumptionToken": token}
            time.sleep(sleep_seconds)

    return sorted_daily_papers(papers)


def harvest_oai_set(
    *,
    session: requests.Session,
    set_spec: str,
    start_date: str,
    end_date: str,
    from_datestamp: str,
    until_datestamp: str,
    sleep_seconds: float,
    paper_index: dict[str, dict[str, Any]],
) -> dict[str, int]:
    params = {
        "verb": "ListRecords",
        "metadataPrefix": "arXivRaw",
        "set": set_spec,
        "from": from_datestamp,
        "until": until_datestamp,
    }
    stats = {"seen": 0, "in_range": 0, "appended": 0, "pages": 0}

    while True:
        root = request_oai(session, params)
        stats["pages"] += 1
        for record in root.findall(".//oai:record", OAI_NS):
            stats["seen"] += 1
            paper = parse_oai_record(record)
            if not paper:
                continue
            source_date = str(paper.get("source_date") or "")
            if not date_in_range(source_date, start_date, end_date):
                continue
            stats["in_range"] += 1
            appended, _ = append_new_papers([paper], source_date=source_date, existing_index=paper_index)
            stats["appended"] += appended

        token = oai_text_at(root, ".//oai:resumptionToken")
        LOGGER.info(
            "OAI %s page=%d seen=%d in_range=%d appended=%d token=%s",
            set_spec,
            stats["pages"],
            stats["seen"],
            stats["in_range"],
            stats["appended"],
            "yes" if token else "no",
        )
        if not token:
            break
        params = {"verb": "ListRecords", "resumptionToken": token}
        time.sleep(sleep_seconds)

    return stats


def harvest_oai_missing(
    *,
    start_date: str,
    end_date: str,
    categories: list[str],
    from_datestamp: str,
    until_datestamp: str,
    sleep_seconds: float,
) -> dict[str, int]:
    ensure_dirs()
    session = requests.Session()
    paper_index = load_paper_index()
    total = {"seen": 0, "in_range": 0, "appended": 0, "pages": 0}

    for category in progress_bar(categories, total=len(categories), desc="OAI sets", unit="set"):
        stats = harvest_oai_set(
            session=session,
            set_spec=category_to_set_spec(category),
            start_date=start_date,
            end_date=end_date,
            from_datestamp=from_datestamp,
            until_datestamp=until_datestamp,
            sleep_seconds=sleep_seconds,
            paper_index=paper_index,
        )
        for key in total:
            total[key] += stats[key]

    return total


def date_range(start_date: str, end_date: str) -> list[str]:
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    if start > end:
        raise ValueError("--start-date must be earlier than or equal to --end-date")
    dates: list[str] = []
    cursor = start
    while cursor <= end:
        dates.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return dates


def fetch_one_date_for_backfill(
    target_date: str,
    categories: list[str],
    max_papers: int,
) -> tuple[str, list[dict[str, Any]], str | None]:
    try:
        papers = fetch_papers_for_date_oai(target_date, categories, max_papers=max_papers)
        return target_date, papers, None
    except Exception as exc:
        return target_date, [], str(exc)


def safe_worker_count(value: int) -> int:
    if value < 1:
        return 1
    if value > 4:
        LOGGER.warning("Worker count %d is high for arXiv backfills; capping at 4.", value)
        return 4
    return value


def backfill_metadata(
    *,
    start_date: str,
    end_date: str,
    categories: list[str],
    max_papers: int,
    workers: int,
) -> dict[str, int]:
    ensure_dirs()
    dates = date_range(start_date, end_date)
    paper_index = load_paper_index()
    worker_count = safe_worker_count(workers)
    stats = {"dates": len(dates), "fetched": 0, "appended": 0, "failed_dates": 0}

    LOGGER.info(
        "Backfilling arXiv metadata from %s to %s across %d date(s), categories=%s, workers=%d.",
        start_date, end_date, len(dates), ", ".join(categories), worker_count,
    )

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(fetch_one_date_for_backfill, target_date, categories, max_papers): target_date
            for target_date in dates
        }

        for future in progress_bar(as_completed(futures), total=len(futures), desc="Backfill arXiv", unit="day"):
            target_date, papers, error = future.result()
            if error:
                stats["failed_dates"] += 1
                LOGGER.warning("Backfill failed for %s: %s", target_date, error)
                continue

            appended, _ = append_new_papers(papers, source_date=target_date, existing_index=paper_index)
            stats["fetched"] += len(papers)
            stats["appended"] += appended
            LOGGER.info(
                "Backfilled %s: fetched=%d appended=%d total=%d",
                target_date, len(papers), appended, len(paper_index),
            )

    return stats


def find_latest_date_with_papers(
    categories: list[str],
    max_papers: int,
    start_date: str | None = None,
    lookback_days: int = 14,
) -> tuple[str, list[dict[str, Any]]]:
    cursor = datetime.strptime(parse_date(start_date), "%Y-%m-%d").date()

    for offset in range(lookback_days + 1):
        target_date = (cursor - timedelta(days=offset)).isoformat()
        papers = fetch_papers_for_date_oai(target_date, categories, max_papers=max_papers)

        if papers:
            LOGGER.info("Selected latest non-empty arXiv date: %s (%d papers)", target_date, len(papers))
            return target_date, papers

        LOGGER.info("No papers found for %s; checking previous day", target_date)

    raise RuntimeError(
        f"No arXiv papers found in the last {lookback_days + 1} days from {cursor.isoformat()}."
    )


def parse_args() -> argparse.Namespace:
    config = load_config()

    parser = argparse.ArgumentParser(description="Fetch arXiv metadata via OAI-PMH.")
    parser.add_argument("--date", default=None, help="Target date in YYYY-MM-DD format.")
    parser.add_argument("--start-date", default=None, help="Start date for --backfill or --oai-check.")
    parser.add_argument("--end-date", default=None, help="End date for --backfill or --oai-check.")
    parser.add_argument("--max-papers", type=int, default=config.get("arxiv", {}).get("max_papers", 30))
    parser.add_argument("--categories", nargs="+", default=config.get("arxiv", {}).get("categories", []))
    parser.add_argument("--latest-with-papers", action="store_true", help="Walk backward to the latest date with papers.")
    parser.add_argument("--lookback-days", type=int, default=14, help="Maximum days to look back.")
    parser.add_argument("--backfill", action="store_true", help="Backfill a date range into the database.")
    parser.add_argument("--workers", type=int, default=DEFAULT_BACKFILL_WORKERS, help="Concurrent workers for --backfill.")
    parser.add_argument(
        "--oai-check",
        action="store_true",
        help="Use OAI-PMH to append missing papers for a date range into the database.",
    )
    parser.add_argument("--from-datestamp", default=None, help="OAI datestamp lower bound for --oai-check.")
    parser.add_argument("--until-datestamp", default=None, help="OAI datestamp upper bound for --oai-check.")
    parser.add_argument("--oai-sleep", type=float, default=1.0, help="Seconds to sleep between OAI requests.")

    return parser.parse_args()


def main() -> None:
    setup_logging()
    ensure_dirs()

    args = parse_args()

    if args.backfill:
        if not args.start_date:
            raise ValueError("--backfill requires --start-date")
        start_date = parse_date(args.start_date)
        end_date = parse_date(args.end_date) if args.end_date else datetime.today().date().isoformat()
        stats = backfill_metadata(
            start_date=start_date,
            end_date=end_date,
            categories=args.categories,
            max_papers=args.max_papers,
            workers=args.workers,
        )
        LOGGER.info("Backfill completed: %s", stats)
        return

    if args.oai_check:
        if not args.start_date:
            raise ValueError("--oai-check requires --start-date")
        start_date = parse_date(args.start_date)
        end_date = parse_date(args.end_date) if args.end_date else datetime.today().date().isoformat()
        from_datestamp = parse_date(args.from_datestamp) if args.from_datestamp else start_date
        until_datestamp = parse_date(args.until_datestamp) if args.until_datestamp else end_date
        stats = harvest_oai_missing(
            start_date=start_date,
            end_date=end_date,
            categories=args.categories,
            from_datestamp=from_datestamp,
            until_datestamp=until_datestamp,
            sleep_seconds=args.oai_sleep,
        )
        LOGGER.info("OAI check completed: %s", stats)
        return

    if args.latest_with_papers:
        target_date, papers = find_latest_date_with_papers(
            args.categories,
            args.max_papers,
            start_date=args.date,
            lookback_days=args.lookback_days,
        )
    else:
        target_date = parse_date(args.date)
        papers = fetch_papers_for_date_oai(target_date, args.categories, max_papers=args.max_papers)

    if not papers:
        LOGGER.info("No papers found for %s.", target_date)
        return
    appended, _ = append_new_papers(papers, source_date=target_date, existing_index=load_paper_index())
    LOGGER.info("Fetched %d paper(s) for %s, appended %d to database.", len(papers), target_date, appended)


if __name__ == "__main__":
    main()