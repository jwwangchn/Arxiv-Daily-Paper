"""CVF Open Access fetcher — CVPR, ICCV from openaccess.thecvf.com."""
from __future__ import annotations

import logging
import re
import time
from typing import Any
from urllib.request import Request, urlopen

from fetchers.base import FetchRequest, FetchResult, make_paper_id, normalize_unified_paper
from fetchers.registry import register

LOGGER = logging.getLogger("fetchers.cvf")

BASE_URL = "https://openaccess.thecvf.com"

CONFERENCE_PATHS = {
    "cvpr": {
        "years": {2024: "CVPR2024", 2025: "CVPR2025"},
        "venue": "CVPR",
    },
    "iccv": {
        "years": {2023: "ICCV2023"},  # ICCV is odd years; 2025 not yet on CVF
        "venue": "ICCV",
    },
}


def _fetch(url: str) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
    with urlopen(req, timeout=120) as resp:
        return resp.read().decode("utf-8")


def _parse_conference_page(html: str, venue: str, year: int) -> list[dict[str, Any]]:
    """Parse CVF conference day=all page for paper entries."""
    papers: list[dict[str, Any]] = []

    # Each paper: <dt class="ptitle">...<a href="...html">Title</a></dt>
    # Followed by: author form, pdf link

    # Split by dt tags
    entries = re.split(r'<dt\s+class="ptitle">', html)

    for entry in entries[1:]:  # skip header
        # Title and HTML link
        title_match = re.search(r'<a\s+href="([^"]*\.html)"[^>]*>(.*?)</a>', entry, re.DOTALL)
        if not title_match:
            continue
        html_path = title_match.group(1)
        title = re.sub(r"<[^>]+>", "", title_match.group(2)).strip()
        title = re.sub(r"\s+", " ", title)

        # PDF link
        pdf_match = re.search(r'href="([^"]*\.pdf)"', entry)
        pdf_url = ""
        if pdf_match:
            p = pdf_match.group(1)
            pdf_url = p if p.startswith("http") else f"{BASE_URL}{p}"

        # Authors from hidden form inputs
        authors: list[str] = []
        for m in re.finditer(r'name="query_author"[^>]*value="([^"]*)"', entry):
            authors.append(m.group(1).strip())

        # Paper ID from HTML path: /content/CVPR2024/html/Author_Title_CVPR_2024_paper.html
        id_match = re.search(r'/content/\w+/html/([^/]+)\.html', html_path)
        source_id = id_match.group(1) if id_match else title.lower().replace(" ", "_")

        if title and pdf_url:
            papers.append({
                "source_id": source_id,
                "title": title,
                "authors": authors,
                "abstract": "",
                "pdf_url": pdf_url,
                "entry_url": f"{BASE_URL}{html_path}",
            })

    return papers


@register("cvf")
class CVFFetcher:
    name = "cvf"

    def fetch(self, request: FetchRequest) -> FetchResult:
        conf = (request.venue or "").strip().lower()
        if not conf or conf not in CONFERENCE_PATHS:
            return FetchResult(
                warnings=[f"CVF fetcher requires --venue (cvpr or iccv). Available: {list(CONFERENCE_PATHS.keys())}"]
            )

        years = []
        if request.year:
            years = [request.year]
        elif request.start_year and request.end_year:
            years = list(range(request.start_year, request.end_year + 1))
        else:
            years = [2024, 2025]

        config = CONFERENCE_PATHS[conf]
        result = FetchResult()
        total = 0

        for year in years:
            conf_path = config["years"].get(year)
            if not conf_path:
                result.warnings.append(f"{config['venue']} {year} not available on CVF Open Access")
                continue

            url = f"{BASE_URL}/{conf_path}?day=all"
            LOGGER.info("CVF: fetching %s from %s", conf_path, url)

            try:
                html = _fetch(url)
            except Exception as e:
                result.warnings.append(f"Failed to fetch {conf_path}: {e}")
                continue

            conf_papers = _parse_conference_page(html, config["venue"], year)
            LOGGER.info("CVF: %s -> %d papers", conf_path, len(conf_papers))

            for p in conf_papers:
                if request.max_papers and total >= request.max_papers:
                    break
                paper_id = make_paper_id("cvf", conf, year, p["source_id"])
                result.papers.append(
                    normalize_unified_paper(
                        paper_id=paper_id,
                        source="cvf",
                        venue=config["venue"].upper(),
                        year=year,
                        track="Conference",
                        status="accepted",
                        source_paper_id=p["source_id"],
                        title=p["title"],
                        authors=p.get("authors", []),
                        abstract="",
                        published=f"{year}-01-01",
                        entry_url=p.get("entry_url", ""),
                        pdf_url=p["pdf_url"],
                        source_date=f"{year}-01-01",
                    )
                )
                total += 1

            result.source_stats[f"cvf:{conf_path}"] = len(conf_papers)
            time.sleep(1)

            LOGGER.info("CVF: %s/%d -> %d papers total", config["venue"].upper(), year, total)

        LOGGER.info("CVF fetch complete: %d total", total)
        return result
