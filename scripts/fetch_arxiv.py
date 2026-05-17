from __future__ import annotations

import argparse
import html as html_lib
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import arxiv
import requests

from lib.config import (
    PROJECT_ROOT,
    ensure_dirs,
    load_config,
    normalize_space,
    parse_date,
    setup_logging,
    write_json,
)
from lib.progress import progress_bar

try:
    from lib.archive import (
        ARCHIVE_DIR,
        append_new_papers as append_new_papers_jsonl,
        load_paper_index as load_paper_index_jsonl,
    )
    from lib.db import (
        DB_PATH,
        append_new_papers as append_new_papers_db,
        load_paper_index as load_paper_index_db,
    )
    _HAS_ARCHIVE = True
except ImportError:
    _HAS_ARCHIVE = False

LOGGER = logging.getLogger("fetch_arxiv")

ARXIV_BASE_URL = "https://arxiv.org"
ARXIV_USER_AGENT = "ArxivDailyPaperGuide/0.1 (https://github.com/jwwangchn/Arxiv-Daily-Paper)"


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

    return {
        "arxiv_id": arxiv_id,
        "title": normalize_space(getattr(result, "title", "")),
        "authors": authors,
        "abstract": normalize_space(getattr(result, "summary", "")),
        "categories": categories,
        "primary_category": primary_category,
        "published": result_datetime(getattr(result, "published", "")),
        "updated": result_datetime(getattr(result, "updated", "")),
        "entry_url": entry_url or f"{ARXIV_BASE_URL}/abs/{arxiv_id}",
        "pdf_url": pdf_url,
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
    """
    Find the section under a date heading.

    arXiv headings may look like:
      <h3>Thu, 7 May 2026 (showing 116 of 116 entries )</h3>

    So do not require an exact heading match.
    """
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
    """
    Prefer monthly archive page because recent pages can be paginated and may not
    contain the target date for high-volume categories such as cs.AI.
    """
    month = browse_month_for_date(target_date)
    return [
        f"{ARXIV_BASE_URL}/list/{category}/{month}?show=all",
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
                    "source_date": target_date,
                    "entry_url": f"{ARXIV_BASE_URL}/abs/{arxiv_id}",
                    "pdf_url": f"{ARXIV_BASE_URL}/pdf/{arxiv_id}",
                }
            )

    LOGGER.info("Fetched %d papers via arXiv browse fallback", len(papers))
    return papers


def fetch_papers(
    target_date: str,
    categories: list[str],
    max_papers: int,
    retries: int = 2,
) -> list[dict[str, Any]]:
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
            paper["source_date"] = target_date

            if paper["arxiv_id"] in seen:
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
        papers = fetch_papers(target_date, categories, max_papers)

        if papers:
            LOGGER.info("Selected latest non-empty arXiv date: %s (%d papers)", target_date, len(papers))
            return target_date, papers

        LOGGER.info("No papers found for %s; checking previous day", target_date)

    raise RuntimeError(
        f"No arXiv papers found in the last {lookback_days + 1} days from {cursor.isoformat()}."
    )


def save_raw(target_date: str, papers: list[dict[str, Any]]) -> Path:
    output = PROJECT_ROOT / "data" / "raw" / f"{target_date}.json"
    write_json(output, {"date": target_date, "source": "arxiv", "papers": papers})
    LOGGER.info("Wrote %s", output)

    # Dual-write: JSONL (backup) + SQLite (local dev)
    if _HAS_ARCHIVE and papers:
        try:
            jsonl_index = load_paper_index_jsonl() if (ARCHIVE_DIR / "papers.jsonl").exists() else None
            inserted, skipped = append_new_papers_jsonl(papers, source_date=target_date, existing_index=jsonl_index)
            if inserted:
                LOGGER.info("JSONL: appended %d paper(s) (skipped %d duplicates)", inserted, skipped)
        except Exception as exc:
            LOGGER.warning("Failed to write papers to JSONL: %s", exc)

        try:
            db_index = load_paper_index_db() if DB_PATH.exists() else None
            inserted, skipped = append_new_papers_db(papers, source_date=target_date, existing_index=db_index)
            if inserted:
                LOGGER.info("SQLite: inserted %d paper(s) (skipped %d duplicates)", inserted, skipped)
        except Exception as exc:
            LOGGER.warning("Failed to write papers to SQLite: %s", exc)

    return output


def parse_args() -> argparse.Namespace:
    config = load_config()

    parser = argparse.ArgumentParser(description="Fetch daily arXiv metadata.")
    parser.add_argument("--date", default=None, help="Target date in YYYY-MM-DD format.")
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

    return parser.parse_args()


def main() -> None:
    setup_logging()
    ensure_dirs()

    args = parse_args()

    if args.latest_with_papers:
        target_date, papers = find_latest_date_with_papers(
            args.categories,
            args.max_papers,
            start_date=args.date,
            lookback_days=args.lookback_days,
        )
    else:
        target_date = parse_date(args.date)
        papers = fetch_papers(target_date, args.categories, args.max_papers)

    save_raw(target_date, papers)


if __name__ == "__main__":
    main()
