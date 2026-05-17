"""Fetch arXiv papers via OAI-PMH, arxiv.py, and browse-page fallback."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import parsedate_to_datetime
import html as html_lib
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any
import xml.etree.ElementTree as ET

import arxiv
import requests

from lib.archive import append_new_papers, load_paper_index
from lib.config import (
    ensure_dirs,
    load_config,
    normalize_space,
    parse_date,
    setup_logging,
)
from lib.progress import progress_bar

LOGGER = logging.getLogger("commands.fetch")

ARXIV_BASE_URL = "https://arxiv.org"
ARXIV_USER_AGENT = "ArxivDailyPaperGuide/0.1 (https://github.com/jwwangchn/Arxiv-Daily-Paper)"
OAI_BASE_URL = "https://oaipmh.arxiv.org/oai"
OAI_NS = {"oai": "http://www.openarchives.org/OAI/2.0/", "raw": "http://arxiv.org/OAI/arXivRaw/"}
DEFAULT_BACKFILL_WORKERS = 2


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
        headers={"User-Agent": ARXIV_USER_AGENT},
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
    return {
        "arxiv_id": arxiv_id,
        "title": oai_text_at(raw, "raw:title"),
        "authors": parse_authors(oai_text_at(raw, "raw:authors")),
        "abstract": oai_text_at(raw, "raw:abstract"),
        "categories": categories,
        "primary_category": primary_category,
        "published": published.replace("+00:00", "Z") if published else "",
        "updated": updated or (published.replace("+00:00", "Z") if published else ""),
        "entry_url": f"{ARXIV_BASE_URL}/abs/{arxiv_id}",
        "pdf_url": f"{ARXIV_BASE_URL}/pdf/{arxiv_id}",
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


def build_query(categories: list[str], target_date: str) -> str:
    start = target_date.replace("-", "")
    end_dt = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    next_day = datetime.fromtimestamp(end_dt.timestamp() + 86400, tz=timezone.utc).strftime("%Y%m%d")
    category_query = " OR ".join(f"cat:{category}" for category in categories)
    return f"({category_query}) AND submittedDate:[{start}0000 TO {next_day}0000]"


def strip_version(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", arxiv_id)


def result_datetime(value: Any) -> str:
    if not value:
        return ""
    if hasattr(value, "isoformat"):
        text = value.isoformat()
        return text.replace("+00:00", "Z")
    return str(value)


def paper_submitted_date(paper: dict[str, Any]) -> str:
    return str(paper.get("source_date") or paper.get("published") or "")[:10]


def parse_result(result: arxiv.Result) -> dict[str, Any]:
    entry_url = str(getattr(result, "entry_id", "") or "")
    raw_id = entry_url.rstrip("/").split("/")[-1] if entry_url else str(result.get_short_id())
    arxiv_id = strip_version(raw_id)

    authors = [
        normalize_space(getattr(author, "name", str(author)))
        for author in getattr(result, "authors", [])
    ]
    categories = list(getattr(result, "categories", []) or [])
    primary_category = str(
        getattr(result, "primary_category", "") or (categories[0] if categories else "")
    )
    pdf_url = str(getattr(result, "pdf_url", "") or f"{ARXIV_BASE_URL}/pdf/{arxiv_id}")

    published = result_datetime(getattr(result, "published", ""))
    return {
        "arxiv_id": arxiv_id,
        "title": normalize_space(getattr(result, "title", "")),
        "authors": authors,
        "abstract": normalize_space(getattr(result, "summary", "")),
        "categories": categories,
        "primary_category": primary_category,
        "published": published,
        "updated": result_datetime(getattr(result, "updated", "")),
        "entry_url": entry_url or f"{ARXIV_BASE_URL}/abs/{arxiv_id}",
        "pdf_url": pdf_url,
        "source_date": published[:10],
    }


def strip_html(fragment: str) -> str:
    fragment = re.sub(
        r"<span[^>]*class=[\"']descriptor[\"'][^>]*>.*?</span>",
        " ",
        fragment,
        flags=re.S,
    )
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    return normalize_space(html_lib.unescape(fragment))


def browse_header_for_date(target_date: str) -> str:
    value = datetime.strptime(target_date, "%Y-%m-%d")
    return f"{value:%a}, {value.day} {value:%b} {value.year}"


def browse_month_for_date(target_date: str) -> str:
    """arXiv listing archive URLs use YYYY-MM, e.g. 2026-05."""
    value = datetime.strptime(target_date, "%Y-%m-%d")
    return value.strftime("%Y-%m")


def parse_abs_page(arxiv_id: str, session: requests.Session) -> dict[str, Any]:
    url = f"{ARXIV_BASE_URL}/abs/{arxiv_id}"
    response = session.get(url, headers={"User-Agent": ARXIV_USER_AGENT}, timeout=30)
    response.raise_for_status()

    text = response.text

    title_match = re.search(
        r"<h1[^>]*class=[\"']title mathjax[\"'][^>]*>\s*"
        r"<span[^>]*class=[\"']descriptor[\"'][^>]*>Title:</span>\s*"
        r"(.*?)\s*</h1>",
        text,
        re.S,
    )

    authors_match = re.search(
        r"<div[^>]*class=[\"']authors[\"'][^>]*>\s*"
        r"<span[^>]*class=[\"']descriptor[\"'][^>]*>Authors:</span>\s*"
        r"(.*?)\s*</div>",
        text,
        re.S,
    )

    abstract_match = re.search(
        r"<blockquote[^>]*class=[\"']abstract mathjax[\"'][^>]*>\s*"
        r"<span[^>]*class=[\"']descriptor[\"'][^>]*>Abstract:</span>\s*"
        r"(.*?)\s*</blockquote>",
        text,
        re.S,
    )

    subjects_match = re.search(
        r"<td[^>]*class=[\"']tablecell subjects[\"'][^>]*>\s*(.*?)\s*</td>",
        text,
        re.S,
    )

    dateline_match = re.search(r"\[Submitted on ([^\]]+)\]", text)

    subjects_text = strip_html(subjects_match.group(1)) if subjects_match else ""
    categories = re.findall(r"\(([a-z.-]+\.[A-Z0-9-]+)\)", subjects_text)

    primary_match = (
        re.search(r".*?\(([a-z.-]+\.[A-Z0-9-]+)\).*?", subjects_match.group(1), re.S)
        if subjects_match
        else None
    )
    primary_category = primary_match.group(1) if primary_match else (categories[0] if categories else "")

    published = ""
    if dateline_match:
        try:
            published_date = datetime.strptime(dateline_match.group(1), "%d %b %Y").date().isoformat()
            published = f"{published_date}T00:00:00Z"
        except ValueError:
            published = ""

    return {
        "title": strip_html(title_match.group(1)) if title_match else "",
        "authors": [
            author.strip()
            for author in strip_html(authors_match.group(1)).split(",")
            if author.strip()
        ]
        if authors_match
        else [],
        "abstract": strip_html(abstract_match.group(1)) if abstract_match else "",
        "categories": categories,
        "primary_category": primary_category,
        "published": published,
        "updated": published,
    }


def extract_browse_headings(html: str) -> list[str]:
    headings = re.findall(r"<h3[^>]*>\s*(.*?)\s*</h3>", html, re.S)
    return [strip_html(heading) for heading in headings]


def find_browse_section(html: str, header: str) -> str | None:
    """Find the section under a date heading."""
    pattern = (
        rf"<h3[^>]*>\s*"
        rf"{re.escape(header)}"
        rf"(?:\s*\([^<]*entries\s*\))?"
        rf"\s*</h3>"
        rf"(.*?)(?=<h3[^>]*>|</main>|$)"
    )

    match = re.search(pattern, html, re.S)
    if match:
        return match.group(1)

    return None


def fetch_browse_html(session: requests.Session, url: str) -> str:
    response = session.get(url, headers={"User-Agent": ARXIV_USER_AGENT}, timeout=30)
    response.raise_for_status()
    return response.text


def candidate_browse_urls(category: str, target_date: str) -> list[str]:
    """Prefer monthly archive page because recent pages can be paginated."""
    month = browse_month_for_date(target_date)
    return [
        f"{ARXIV_BASE_URL}/list/{category}/{month}?show=2000",
        f"{ARXIV_BASE_URL}/list/{category}/recent?show=2000",
    ]


def extract_arxiv_ids_from_browse_section(section_html: str) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()

    entries = re.finditer(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", section_html, re.S)

    for entry in entries:
        dt_html = entry.group(1)
        id_match = re.search(r"/abs/([0-9]{4}\.[0-9]{4,5})(?:v[0-9]+)?", dt_html)
        if not id_match:
            continue

        arxiv_id = id_match.group(1)
        if arxiv_id in seen:
            continue

        seen.add(arxiv_id)
        ids.append(arxiv_id)

    return ids


def fetch_browse_fallback(target_date: str, categories: list[str], max_papers: int) -> list[dict[str, Any]]:
    LOGGER.info("Falling back to arXiv browse pages for %s", target_date)

    session = requests.Session()
    header = browse_header_for_date(target_date)

    seen: set[str] = set()
    papers: list[dict[str, Any]] = []

    for category in progress_bar(categories, desc="arXiv browse categories", unit="cat"):
        if len(papers) >= max_papers:
            break

        section_html: str | None = None
        matched_url = ""

        for url in candidate_browse_urls(category, target_date):
            try:
                html = fetch_browse_html(session, url)
            except Exception as exc:
                LOGGER.warning("Failed to fetch arXiv browse page for %s: %s (%s)", category, url, exc)
                continue

            section_html = find_browse_section(html, header)
            if section_html is not None:
                matched_url = url
                break

            headings = extract_browse_headings(html)
            LOGGER.info(
                "No browse section for %s in %s at %s. Expected heading=%r. "
                "Available headings sample=%s",
                target_date,
                category,
                url,
                header,
                headings[:30],
            )

        if section_html is None:
            LOGGER.info("No browse section for %s in %s after trying all candidate URLs", target_date, category)
            continue

        arxiv_ids = extract_arxiv_ids_from_browse_section(section_html)

        LOGGER.info(
            "Found %d paper id(s) for %s in %s via %s",
            len(arxiv_ids),
            target_date,
            category,
            matched_url,
        )

        for arxiv_id in progress_bar(
            arxiv_ids,
            total=len(arxiv_ids),
            desc=f"arXiv abs {category}",
            unit="paper",
        ):
            if len(papers) >= max_papers:
                break

            if arxiv_id in seen:
                continue

            try:
                time.sleep(1)
                metadata = parse_abs_page(arxiv_id, session)
            except Exception as exc:
                LOGGER.warning("Failed to parse arXiv abs page for %s: %s", arxiv_id, exc)
                metadata = {}

            seen.add(arxiv_id)

            published = metadata.get("published") or f"{target_date}T00:00:00Z"
            paper_categories = metadata.get("categories") or [category]
            source_date = str(metadata.get("source_date") or published)[:10]
            if source_date != target_date:
                continue

            papers.append(
                {
                    "arxiv_id": arxiv_id,
                    "title": metadata.get("title") or "",
                    "authors": metadata.get("authors") or [],
                    "abstract": metadata.get("abstract") or "",
                    "categories": paper_categories,
                    "primary_category": metadata.get("primary_category") or category,
                    "published": published,
                    "updated": metadata.get("updated") or published,
                    "entry_url": f"{ARXIV_BASE_URL}/abs/{arxiv_id}",
                    "pdf_url": f"{ARXIV_BASE_URL}/pdf/{arxiv_id}",
                    "source_date": source_date,
                }
            )

    LOGGER.info("Fetched %d papers via arXiv browse fallback", len(papers))
    return papers


def fetch_papers(
    target_date: str,
    categories: list[str],
    max_papers: int,
    retries: int = 2,
    use_fallback: bool = False,
    prefer_oai: bool = False,
) -> list[dict[str, Any]]:
    if prefer_oai:
        papers = fetch_papers_for_date_oai(target_date, categories, max_papers=max_papers)
        LOGGER.info("Fetched %d paper(s) via OAI-PMH for %s", len(papers), target_date)
        return papers

    query = build_query(categories, target_date)

    LOGGER.info("Fetching arXiv papers for %s from %s", target_date, ", ".join(categories))

    client = arxiv.Client(
        page_size=min(max_papers, 100),
        delay_seconds=3.0,
        num_retries=retries,
    )

    search = arxiv.Search(
        query=query,
        max_results=max_papers,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )

    seen: set[str] = set()
    papers: list[dict[str, Any]] = []
    last_error: Exception | None = None

    try:
        results = client.results(search)

        for result in progress_bar(
            results,
            total=max_papers,
            desc=f"arXiv {target_date}",
            unit="paper",
        ):
            paper = parse_result(result)

            if paper["arxiv_id"] in seen:
                continue
            if paper_submitted_date(paper) != target_date:
                LOGGER.debug(
                    "Skipping %s for %s because submitted date is %s.",
                    paper["arxiv_id"],
                    target_date,
                    paper_submitted_date(paper) or "unknown",
                )
                continue

            seen.add(paper["arxiv_id"])
            papers.append(paper)

            if len(papers) >= max_papers:
                break

        LOGGER.info("Fetched %d unique papers via arxiv.py", len(papers))

        if papers:
            return papers

        LOGGER.info("arxiv.py returned 0 papers for %s; trying browse fallback.", target_date)

    except Exception as exc:
        last_error = exc
        LOGGER.warning(
            "arxiv.py fetch failed after collecting %d paper(s): %s",
            len(papers),
            exc,
        )

    if not use_fallback:
        if papers:
            LOGGER.warning("Browse fallback disabled; using %d partial paper(s).", len(papers))
            return papers
        raise RuntimeError(f"arxiv.py failed and browse fallback is disabled: {last_error}")

    try:
        fallback_papers = fetch_browse_fallback(target_date, categories, max_papers)

        if fallback_papers:
            LOGGER.info("Using %d papers from arXiv browse fallback", len(fallback_papers))
            return fallback_papers

        if papers:
            LOGGER.warning(
                "Browse fallback returned 0 papers; using %d partial paper(s) collected from arxiv.py",
                len(papers),
            )
            return papers

        return fallback_papers

    except Exception as exc:
        LOGGER.warning("arXiv browse fallback failed: %s", exc)

        if papers:
            LOGGER.warning(
                "Using %d partial paper(s) collected from arxiv.py despite fallback failure",
                len(papers),
            )
            return papers

        raise RuntimeError(
            f"Failed to fetch arXiv papers after {retries} attempts: {last_error}"
        ) from exc


def find_latest_date_with_papers(
    categories: list[str],
    max_papers: int,
    start_date: str | None = None,
    lookback_days: int = 14,
) -> tuple[str, list[dict[str, Any]]]:
    """Walk backward from start_date until an arXiv issue with papers is found."""
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


def safe_worker_count(value: int) -> int:
    if value < 1:
        return 1
    if value > 4:
        LOGGER.warning("Worker count %d is high for arXiv backfills; capping at 4.", value)
        return 4
    return value


def fetch_one_date_for_backfill(
    target_date: str,
    categories: list[str],
    max_papers: int,
    use_browse_fallback: bool,
) -> tuple[str, list[dict[str, Any]], str | None]:
    try:
        if use_browse_fallback:
            papers = fetch_papers(target_date, categories, max_papers, use_fallback=True)
        else:
            papers = fetch_papers_for_date_oai(target_date, categories, max_papers=max_papers)
        return target_date, papers, None
    except Exception as exc:
        return target_date, [], str(exc)


def backfill_metadata(
    *,
    start_date: str,
    end_date: str,
    categories: list[str],
    max_papers: int,
    workers: int,
    use_browse_fallback: bool = False,
) -> dict[str, int]:
    ensure_dirs()
    dates = date_range(start_date, end_date)
    paper_index = load_paper_index()
    worker_count = safe_worker_count(workers)
    stats = {"dates": len(dates), "fetched": 0, "appended": 0, "failed_dates": 0}

    LOGGER.info(
        "Backfilling arXiv metadata from %s to %s across %d date(s), categories=%s, workers=%d.",
        start_date,
        end_date,
        len(dates),
        ", ".join(categories),
        worker_count,
    )

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(fetch_one_date_for_backfill, target_date, categories, max_papers, use_browse_fallback): target_date
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
                "Backfilled %s: fetched=%d appended=%d total_archive=%d",
                target_date,
                len(papers),
                appended,
                len(paper_index),
            )

    return stats


def merge_papers(existing: list[dict[str, Any]], new_papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge new papers into existing by arxiv_id."""
    seen_ids: set[str] = set()
    merged: list[dict[str, Any]] = []

    existing_map: dict[str, dict[str, Any]] = {}
    for paper in existing:
        pid = str(paper.get("arxiv_id") or "").strip()
        if pid:
            existing_map[pid] = paper

    for paper in new_papers:
        pid = str(paper.get("arxiv_id") or "").strip()
        if not pid:
            continue
        if pid not in existing_map:
            existing_map[pid] = paper
        else:
            cur = existing_map[pid]
            for key, value in paper.items():
                if not cur.get(key) and value:
                    cur[key] = value

    return list(existing_map.values())


def parse_args() -> argparse.Namespace:
    config = load_config()

    parser = argparse.ArgumentParser(description="Fetch daily arXiv metadata.")
    parser.add_argument("--date", default=None, help="Target date in YYYY-MM-DD format.")
    parser.add_argument("--start-date", default=None, help="Start date for --backfill or --oai-check.")
    parser.add_argument("--end-date", default=None, help="End date for --backfill or --oai-check.")
    parser.add_argument(
        "--max-papers",
        type=int,
        default=config.get("arxiv", {}).get("max_papers", 30),
    )
    parser.add_argument(
        "--categories",
        nargs="+",
        default=config.get("arxiv", {}).get("categories", []),
    )
    parser.add_argument(
        "--latest-with-papers",
        action="store_true",
        help="Walk backward and fetch the latest date with papers.",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=14,
        help="Maximum days to look back when --latest-with-papers is used.",
    )
    parser.add_argument(
        "--source",
        choices=["oai", "api"],
        default="oai",
        help="Metadata source. Defaults to OAI-PMH; api uses arxiv.py without browse fallback.",
    )
    parser.add_argument("--backfill", action="store_true", help="Backfill a date range into data/archive/papers.jsonl.")
    parser.add_argument("--workers", type=int, default=DEFAULT_BACKFILL_WORKERS, help="Concurrent workers for --backfill.")
    parser.add_argument(
        "--use-browse-fallback",
        action="store_true",
        help="Use slower arXiv browse fallback during --backfill.",
    )
    parser.add_argument(
        "--oai-check",
        action="store_true",
        help="Use OAI-PMH to append missing papers for a date range into data/archive/papers.jsonl.",
    )
    parser.add_argument("--from-datestamp", default=None, help="OAI datestamp lower bound for --oai-check.")
    parser.add_argument("--until-datestamp", default=None, help="OAI datestamp upper bound for --oai-check.")
    parser.add_argument("--oai-sleep", type=float, default=1.0, help="Seconds to sleep between OAI requests.")
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Compatibility flag for archive workflows; this command never calls DeepSeek.",
    )

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
            use_browse_fallback=args.use_browse_fallback,
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
        if args.source == "oai":
            papers = fetch_papers_for_date_oai(target_date, args.categories, max_papers=args.max_papers)
        else:
            papers = fetch_papers(
                target_date,
                args.categories,
                args.max_papers,
                prefer_oai=False,
                use_fallback=False,
            )

    if not papers:
        LOGGER.info("No papers found for %s; archive was not modified.", target_date)
        return
    appended, _ = append_new_papers(papers, source_date=target_date, existing_index=load_paper_index())
    LOGGER.info("Fetched %d paper(s) for %s, appended %d to archive.", len(papers), target_date, appended)


if __name__ == "__main__":
    main()
