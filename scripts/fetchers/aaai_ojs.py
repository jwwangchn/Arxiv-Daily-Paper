"""AAAI OJS fetcher — proceedings from ojs.aaai.org."""
from __future__ import annotations

import logging
import re
import time
from typing import Any
from urllib.request import Request, urlopen

from fetchers.base import FetchRequest, FetchResult, make_paper_id, normalize_unified_paper
from fetchers.registry import register

LOGGER = logging.getLogger("fetchers.aaai_ojs")

BASE_URL = "https://ojs.aaai.org/index.php/AAAI"

# Issue IDs per year/volume. These are the technical track issues.
ISSUE_MAP = {
    2026: list(range(683, 692)) + [733],  # Vol 40: issues 683-690 (tracks 1-8), 691, 692, 733
    2025: [],  # Not yet available on OJS
    2024: [],  # Not yet available on OJS
}


def _fetch(url: str) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
    with urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8")


def _parse_issue_page(html: str, year: int) -> list[dict[str, str]]:
    """Parse AAAI OJS issue TOC page for paper entries."""
    papers: list[dict[str, str]] = []

    # Find all article links: <a id="article-NNNNN" href="...">
    article_ids = re.findall(r'id="article-(\d+)"', html)

    # Note: Abstracts are on individual article pages, not the TOC. Skipping.

    for article_id in article_ids:
        # Title: find the <a id="article-ID" href="...">Title</a>
        title_pattern = re.compile(
            rf'id="article-{article_id}"[^>]*href="([^"]*)"[^>]*>\s*(.*?)\s*</a>',
            re.DOTALL,
        )
        title_match = title_pattern.search(html)
        if not title_match:
            continue
        article_url = title_match.group(1)
        title = re.sub(r"<[^>]+>", "", title_match.group(2)).strip()
        title = re.sub(r"\s+", " ", title)

        # Authors: <div class="authors">...</div> near this article
        authors: list[str] = []
        author_search = html[html.find(f'article-{article_id}'):]
        author_match = re.search(r'<div class="authors">\s*(.*?)\s*</div>', author_search, re.DOTALL)
        if author_match:
            authors = [a.strip() for a in re.split(r',', author_match.group(1)) if a.strip()]

        # PDF: <a class="obj_galley_link pdf" href="...">
        pdf_match = re.search(
            rf'article-{article_id}.*?class="obj_galley_link pdf"[^>]*href="([^"]*)"',
            author_search[:5000],
            re.DOTALL,
        )
        if not pdf_match:
            pdf_match = re.search(
                r'class="obj_galley_link pdf"[^>]*href="([^"]*\.pdf[^"]*)"',
                author_search[:3000],
                re.DOTALL,
            )
        pdf_url = ""
        if pdf_match:
            pdf_url = pdf_match.group(1)
            if pdf_url.startswith("//"):
                pdf_url = "https:" + pdf_url

        # Abstracts are on individual article pages, not the TOC. Skipping for speed.
        abstract = ""

        if title:
            papers.append({
                "source_id": article_id,
                "title": title,
                "authors": authors,
                "abstract": abstract,
                "pdf_url": pdf_url,
                "entry_url": article_url,
            })

    return papers


def fetch_issue(issue_id: int, year: int) -> list[dict[str, Any]]:
    """Fetch all papers from a single AAAI OJS issue."""
    url = f"{BASE_URL}/issue/view/{issue_id}"
    LOGGER.info("AAAI OJS: fetching issue %d from %s", issue_id, url)

    try:
        html = _fetch(url)
    except Exception as e:
        LOGGER.warning("AAAI OJS: failed to fetch issue %d: %s", issue_id, e)
        return []

    papers = _parse_issue_page(html, year)
    LOGGER.info("AAAI OJS: issue %d -> %d papers", issue_id, len(papers))
    return papers


@register("aaai_ojs")
class AAAIOJSFetcher:
    name = "aaai_ojs"

    def fetch(self, request: FetchRequest) -> FetchResult:
        years = []
        if request.year:
            years = [request.year]
        elif request.start_year and request.end_year:
            years = list(range(request.start_year, request.end_year + 1))
        else:
            years = [2026]

        result = FetchResult()
        total = 0

        for year in years:
            issue_ids = ISSUE_MAP.get(year, [])
            if not issue_ids:
                result.warnings.append(f"AAAI {year} not yet available on OJS")
                continue

            for issue_id in issue_ids:
                issue_papers = fetch_issue(issue_id, year)
                for p in issue_papers:
                    if request.max_papers and total >= request.max_papers:
                        break
                    paper_id = make_paper_id("aaai_ojs", "aaai", year, p["source_id"])
                    result.papers.append(
                        normalize_unified_paper(
                            paper_id=paper_id,
                            source="aaai_ojs",
                            venue="AAAI",
                            year=year,
                            track="Conference",
                            status="accepted",
                            source_paper_id=p["source_id"],
                            title=p["title"],
                            authors=p.get("authors", []),
                            abstract=p.get("abstract", ""),
                            published=f"{year}-01-01",
                            entry_url=p.get("entry_url", f"{BASE_URL}/article/view/{p['source_id']}"),
                            pdf_url=p.get("pdf_url", ""),
                            source_date=f"{year}-01-01",
                        )
                    )
                    total += 1

                result.source_stats[f"aaai:issue-{issue_id}"] = len(issue_papers)
                time.sleep(1)

            LOGGER.info("AAAI OJS: %d -> %d papers total", year, total)

        LOGGER.info("AAAI OJS fetch complete: %d total", total)
        return result
