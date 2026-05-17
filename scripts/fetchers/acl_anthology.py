"""ACL Anthology fetcher — ACL, EMNLP."""
from __future__ import annotations

import logging
import re
import time
from typing import Any
from urllib.request import Request, urlopen

from fetchers.base import FetchRequest, FetchResult, make_paper_id, normalize_unified_paper
from fetchers.registry import register

LOGGER = logging.getLogger("fetchers.acl_anthology")

BASE_URL = "https://aclanthology.org"

VOLUME_MAP = {
    "acl": {
        "volumes": ["{year}.acl-long", "{year}.acl-short"],
        "venue": "ACL",
    },
    "emnlp": {
        "volumes": ["{year}.emnlp-main"],
        "venue": "EMNLP",
    },
}


def _fetch_page(url: str) -> str:
    req = Request(url, headers={"User-Agent": "ArxivDailyPaper/1.0 (+https://github.com)"})
    with urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8")


def _parse_volume_page_robust(html: str) -> list[dict[str, str]]:
    """Robust parser for ACL Anthology volume pages.

    Entry structure (hrefs are often unquoted):
      <div class="d-sm-flex align-items-stretch mb-3">
        <div class="d-block me-2 list-button-row">
          <a href=https://aclanthology.org/2024.acl-long.1.pdf>pdf</a>
        </div>
        <span class=d-block>
          <strong><a href=/2024.acl-long.1/>Title</a></strong><br>
          <a href=/people/...>Author</a> | ...
        </span>
      </div>
      <div class="card ..." id="abstract-2024--acl-long--N">
        <div class="card-body p-3 small">Abstract text</div>
      </div>
    """
    papers: list[dict[str, str]] = []

    # Split by entry divs. Use non-greedy match to stop at the closing </div></div>
    entry_pattern = re.compile(
        r'<div\s+class="d-sm-flex\s+align-items-stretch\s+mb-3">\s*'
        r'<div\s+class="d-block\s+me-2\s+list-button-row">(.*?)'
        r'</div>\s*</div>',
        re.DOTALL,
    )

    # Extract abstracts: id=abstract-YYYY--venue--track--N> (unquoted)
    abstract_pattern = re.compile(
        r'id=abstract-([\w-]+)><div\s+class="card-body\s+p-3\s+small">(.*?)</div>',
        re.DOTALL,
    )
    abstracts: dict[str, str] = {}
    for m in abstract_pattern.finditer(html):
        raw_id = m.group(1)
        text = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        text = re.sub(r"\s+", " ", text)
        if text:
            # Convert "2024--acl-long--1" -> "2024.acl-long.1"
            parts = raw_id.split("--")
            if len(parts) == 3:
                key = f"{parts[0]}.{parts[1]}.{parts[2]}"
            else:
                key = raw_id
            abstracts[key] = text

    # Regex for paper IDs and titles
    pdf_href_re = re.compile(r'href=["\']?(https?://[\w./-]+\.pdf|/[\w./-]+\.pdf)["\']?')
    title_re = re.compile(
        r'<strong>\s*<a[^>]*href=["\']?/(\d{4}\.[\w.\-]+)/?["\']?[^>]*>(.*?)</a>',
        re.DOTALL,
    )
    author_re = re.compile(r'<a[^>]*href=["\']?/people/[^"\'>]+["\']?[^>]*>([^<]+)</a>')

    for entry in entry_pattern.finditer(html):
        block = entry.group(1)

        # PDF link
        pdf_match = pdf_href_re.search(block)
        if not pdf_match:
            continue
        pdf_raw = pdf_match.group(1)
        pdf_url = pdf_raw if pdf_raw.startswith("http") else f"{BASE_URL}{pdf_raw}"

        # Paper ID and title
        title_match = title_re.search(block)
        if not title_match:
            continue
        paper_id_str = title_match.group(1)
        title = re.sub(r"<[^>]+>", "", title_match.group(2)).strip()
        title = re.sub(r"\s+", " ", title)

        # Skip volume-level entries (e.g., "Proceedings of...") which end with .0
        if paper_id_str.endswith(".0"):
            continue

        # Authors
        authors = [a.strip() for a in author_re.findall(block) if a.strip()]

        # Abstract (abstract_pattern already stores keys in paper_id format)
        abstract = abstracts.get(paper_id_str, "")

        papers.append({
            "source_id": paper_id_str,
            "title": title,
            "authors": authors,
            "abstract": abstract,
            "pdf_url": pdf_url,
        })

    return papers


def fetch_volume(volume_id: str, venue: str, year: int) -> list[dict[str, Any]]:
    """Fetch all papers from a single ACL Anthology volume."""
    url = f"{BASE_URL}/volumes/{volume_id}/"
    LOGGER.info("ACL Anthology: fetching %s from %s", volume_id, url)

    try:
        html = _fetch_page(url)
    except Exception as e:
        LOGGER.warning("ACL Anthology: failed to fetch %s: %s", volume_id, e)
        return []

    papers = _parse_volume_page_robust(html)
    LOGGER.info("ACL Anthology: %s -> %d papers", volume_id, len(papers))

    results = []
    for p in papers:
        paper_id = make_paper_id("acl_anthology", venue.lower(), year, p["source_id"])
        results.append(
            normalize_unified_paper(
                paper_id=paper_id,
                source="acl_anthology",
                venue=venue.upper(),
                year=year,
                track=volume_id.split(".")[1] if "." in volume_id else "main",
                status="accepted",
                source_paper_id=p["source_id"],
                title=p["title"],
                authors=p.get("authors", []),
                abstract=p.get("abstract", ""),
                published=f"{year}-01-01",
                entry_url=f"{BASE_URL}/{p['source_id']}/",
                pdf_url=p["pdf_url"],
                source_date=f"{year}-01-01",
            )
        )

    return results


@register("acl_anthology")
class ACLAnthologyFetcher:
    name = "acl_anthology"

    def fetch(self, request: FetchRequest) -> FetchResult:
        venue = (request.venue or "").strip().lower()
        if not venue or venue not in VOLUME_MAP:
            return FetchResult(
                warnings=[f"ACL Anthology fetcher requires --venue (acl or emnlp). Available: {list(VOLUME_MAP.keys())}"]
            )

        years = []
        if request.year:
            years = [request.year]
        elif request.start_year and request.end_year:
            years = list(range(request.start_year, request.end_year + 1))
        else:
            current_year = 2026
            years = list(range(current_year - 2, current_year + 1))

        config = VOLUME_MAP[venue]
        result = FetchResult()
        total = 0

        for year in years:
            for vol_template in config["volumes"]:
                volume_id = vol_template.format(year=year)
                vol_papers = fetch_volume(volume_id, config["venue"], year)
                for paper in vol_papers:
                    if request.max_papers and total >= request.max_papers:
                        break
                    result.papers.append(paper)
                    total += 1

                result.source_stats[f"acl:{volume_id}"] = len(vol_papers)
                time.sleep(1)  # be polite

            LOGGER.info(
                "ACL Anthology: %s/%d -> %d papers total",
                config["venue"].upper(), year, total,
            )

        LOGGER.info("ACL Anthology fetch complete: %d total", total)
        return result
