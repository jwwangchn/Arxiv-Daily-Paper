from __future__ import annotations

import argparse
import html as html_lib
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

import requests

from utils import ensure_dirs, load_config, normalize_space, parse_date, setup_logging, write_json, PROJECT_ROOT


LOGGER = logging.getLogger("fetch_arxiv")
ARXIV_API_URL = "https://export.arxiv.org/api/query"
ARXIV_BASE_URL = "https://arxiv.org"
ARXIV_USER_AGENT = "ArxivDailyPaperGuide/0.1 (https://github.com/jwwangchn/Arxiv-Daily-Paper)"
ATOM = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def build_query(categories: list[str], target_date: str) -> str:
    start = target_date.replace("-", "")
    end_dt = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    next_day = datetime.fromtimestamp(end_dt.timestamp() + 86400, tz=timezone.utc).strftime("%Y%m%d")
    category_query = " OR ".join(f"cat:{category}" for category in categories)
    return f"({category_query}) AND submittedDate:[{start}0000 TO {next_day}0000]"


def atom_text(entry: ET.Element, name: str) -> str:
    node = entry.find(f"atom:{name}", ATOM)
    return normalize_space(node.text if node is not None else "")


def parse_entry(entry: ET.Element) -> dict[str, Any]:
    entry_url = atom_text(entry, "id")
    arxiv_id = entry_url.rstrip("/").split("/")[-1].split("v")[0]
    authors = [normalize_space(author.findtext("atom:name", default="", namespaces=ATOM)) for author in entry.findall("atom:author", ATOM)]
    categories = [category.attrib.get("term", "") for category in entry.findall("atom:category", ATOM) if category.attrib.get("term")]
    primary = entry.find("arxiv:primary_category", ATOM)
    primary_category = primary.attrib.get("term", "") if primary is not None else (categories[0] if categories else "")
    pdf_url = ""
    for link in entry.findall("atom:link", ATOM):
        if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
            pdf_url = link.attrib.get("href", "")
            break
    if not pdf_url:
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
    return {
        "arxiv_id": arxiv_id,
        "title": atom_text(entry, "title"),
        "authors": authors,
        "abstract": atom_text(entry, "summary"),
        "categories": categories,
        "primary_category": primary_category,
        "published": atom_text(entry, "published"),
        "updated": atom_text(entry, "updated"),
        "entry_url": entry_url or f"https://arxiv.org/abs/{arxiv_id}",
        "pdf_url": pdf_url,
    }


def strip_html(fragment: str) -> str:
    fragment = re.sub(r"<span[^>]*class=[\"']descriptor[\"'][^>]*>.*?</span>", " ", fragment, flags=re.S)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    return normalize_space(html_lib.unescape(fragment))


def browse_header_for_date(target_date: str) -> str:
    value = datetime.strptime(target_date, "%Y-%m-%d")
    return f"{value:%a}, {value.day} {value:%b} {value.year}"


def parse_abs_page(arxiv_id: str, session: requests.Session) -> dict[str, Any]:
    url = f"{ARXIV_BASE_URL}/abs/{arxiv_id}"
    response = session.get(url, headers={"User-Agent": ARXIV_USER_AGENT}, timeout=30)
    response.raise_for_status()
    text = response.text

    title_match = re.search(r"<h1 class=\"title mathjax\">(.*?)</h1>", text, re.S)
    authors_match = re.search(r"<div class=\"authors\">(.*?)</div>", text, re.S)
    abstract_match = re.search(r"<blockquote class=\"abstract mathjax\">\s*(.*?)\s*</blockquote>", text, re.S)
    subjects_match = re.search(r"<td class=\"tablecell subjects\">\s*(.*?)</td>", text, re.S)
    dateline_match = re.search(r"\[Submitted on ([^\]]+)\]", text)

    subjects_text = strip_html(subjects_match.group(1)) if subjects_match else ""
    categories = re.findall(r"\(([a-z.-]+\.[A-Z0-9-]+)\)", subjects_text)
    primary_match = re.search(r"<span class=\"primary-subject\">.*?\(([a-z.-]+\.[A-Z0-9-]+)\).*?</span>", subjects_match.group(1), re.S) if subjects_match else None
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
        "authors": [author.strip() for author in strip_html(authors_match.group(1)).split(",") if author.strip()] if authors_match else [],
        "abstract": strip_html(abstract_match.group(1)) if abstract_match else "",
        "categories": categories,
        "primary_category": primary_category,
        "published": published,
        "updated": published,
    }


def fetch_browse_fallback(target_date: str, categories: list[str], max_papers: int) -> list[dict[str, Any]]:
    LOGGER.info("Falling back to arXiv browse pages for %s", target_date)
    session = requests.Session()
    header = browse_header_for_date(target_date)
    seen: set[str] = set()
    papers: list[dict[str, Any]] = []

    for category in categories:
        if len(papers) >= max_papers:
            break
        url = f"{ARXIV_BASE_URL}/list/{category}/recent?show=1000"
        response = session.get(url, headers={"User-Agent": ARXIV_USER_AGENT}, timeout=30)
        response.raise_for_status()
        section_match = re.search(rf"<h3>\s*{re.escape(header)}.*?</h3>(.*?)(?=<h3>|</main>)", response.text, re.S)
        if not section_match:
            LOGGER.info("No browse section for %s in %s", target_date, category)
            continue

        entries = re.finditer(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", section_match.group(1), re.S)
        for entry in entries:
            if len(papers) >= max_papers:
                break
            id_match = re.search(r"/abs/([0-9]{4}\.[0-9]{4,5})(?:v[0-9]+)?", entry.group(1))
            if not id_match:
                continue
            arxiv_id = id_match.group(1)
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
                    "entry_url": f"{ARXIV_BASE_URL}/abs/{arxiv_id}",
                    "pdf_url": f"{ARXIV_BASE_URL}/pdf/{arxiv_id}",
                }
            )

    LOGGER.info("Fetched %d papers via arXiv browse fallback", len(papers))
    return papers


def fetch_papers(target_date: str, categories: list[str], max_papers: int, retries: int = 2) -> list[dict[str, Any]]:
    query = build_query(categories, target_date)
    LOGGER.info("Fetching arXiv papers for %s from %s", target_date, ", ".join(categories))
    params = {
        "search_query": query,
        "start": 0,
        "max_results": max_papers,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    url = f"{ARXIV_API_URL}?{urlencode(params)}"

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            time.sleep(3)
            response = requests.get(url, headers={"User-Agent": ARXIV_USER_AGENT}, timeout=30)
            response.raise_for_status()
            root = ET.fromstring(response.text)
            seen: set[str] = set()
            papers: list[dict[str, Any]] = []
            for entry in root.findall("atom:entry", ATOM):
                paper = parse_entry(entry)
                if paper["arxiv_id"] in seen:
                    continue
                seen.add(paper["arxiv_id"])
                papers.append(paper)
                if len(papers) >= max_papers:
                    break
            LOGGER.info("Fetched %d unique papers", len(papers))
            return papers
        except Exception as exc:
            last_error = exc
            LOGGER.warning("arXiv fetch attempt %d/%d failed: %s", attempt, retries, exc)
            retry_after = None
            response = getattr(exc, "response", None)
            if response is not None:
                retry_after = response.headers.get("Retry-After")
            if retry_after and str(retry_after).isdigit():
                delay = int(retry_after)
            elif response is not None and response.status_code == 429:
                delay = 30 * attempt
            else:
                delay = 2 * attempt
            time.sleep(delay)
    try:
        return fetch_browse_fallback(target_date, categories, max_papers)
    except Exception as exc:
        LOGGER.warning("arXiv browse fallback failed: %s", exc)
    raise RuntimeError(f"Failed to fetch arXiv papers after {retries} attempts: {last_error}")


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
    raise RuntimeError(f"No arXiv papers found in the last {lookback_days + 1} days from {cursor.isoformat()}.")


def save_raw(target_date: str, papers: list[dict[str, Any]]) -> Path:
    output = PROJECT_ROOT / "data" / "raw" / f"{target_date}.json"
    write_json(output, {"date": target_date, "source": "arxiv", "papers": papers})
    LOGGER.info("Wrote %s", output)
    return output


def parse_args() -> argparse.Namespace:
    config = load_config()
    parser = argparse.ArgumentParser(description="Fetch daily arXiv metadata.")
    parser.add_argument("--date", default=None, help="Target date in YYYY-MM-DD format.")
    parser.add_argument("--max-papers", type=int, default=config.get("arxiv", {}).get("max_papers", 30))
    parser.add_argument("--categories", nargs="+", default=config.get("arxiv", {}).get("categories", []))
    parser.add_argument("--latest-with-papers", action="store_true", help="Walk backward and fetch the latest date with papers.")
    parser.add_argument("--lookback-days", type=int, default=14, help="Maximum days to look back when --latest-with-papers is used.")
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
