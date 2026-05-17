"""Build the SPA frontend for the arXiv Daily Paper guide."""

from __future__ import annotations

import argparse
import html
import logging
import re
from datetime import datetime
from typing import Any

from lib.archive import available_dates, load_analysis_index, paper_id, paper_source_date, read_jsonl
from lib.config import PROJECT_ROOT, ensure_dirs, load_config, read_json, setup_logging, write_json

LOGGER = logging.getLogger("commands.build")


def h(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def legacy_priority_for_site(analysis: dict[str, Any]) -> str:
    priority = str(analysis.get("reading_priority") or "").lower()
    aliases = {"must_read": "high", "recommended": "medium", "skim": "medium", "low_priority": "low", "skip": "low"}
    return aliases.get(priority, priority if priority in {"high", "medium", "low"} else "medium")


def remove_score_fields(analysis: dict[str, Any]) -> None:
    for key in ("novelty", "technical_depth", "impact", "relevance", "score_raw", "score", "reason"):
        analysis.pop(key, None)


def paper_for_site(paper: dict[str, Any], analysis_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    item = dict(paper)
    analysis_record = analysis_by_id.get(paper_id(item))
    if analysis_record and analysis_record.get("analysis"):
        item["analysis"] = dict(analysis_record["analysis"])
        item["analysis_version"] = analysis_record.get("analysis_version")
        item["analyzed_at"] = analysis_record.get("analyzed_at")
    if item.get("analysis"):
        item["analysis"]["reading_priority"] = legacy_priority_for_site(item["analysis"])
        remove_score_fields(item["analysis"])
    return item


def priority_rank(paper: dict[str, Any]) -> int:
    priority = str((paper.get("analysis") or {}).get("reading_priority") or "").lower()
    return {"high": 0, "medium": 1, "low": 2}.get(priority, 3)


def paper_time_rank(paper: dict[str, Any]) -> float:
    value = str(paper.get("updated") or paper.get("published") or "")
    if value:
        try:
            return -datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    arxiv_id = str(paper.get("arxiv_id") or "")
    numeric_id = re.sub(r"[^0-9.]", "", arxiv_id)
    try:
        return -float(numeric_id)
    except ValueError:
        return 0.0


def sorted_papers_for_export(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        papers,
        key=lambda paper: (priority_rank(paper), paper_time_rank(paper), str(paper.get("arxiv_id") or "")),
    )


def archive_bundles(use_mock: bool = False) -> list[dict[str, Any]]:
    if use_mock:
        mock_path = PROJECT_ROOT / "data" / "mock" / "analyzed_sample.json"
        if mock_path.exists():
            return [read_json(mock_path)]
        return []

    dates = available_dates()
    if not dates:
        return []

    analysis_by_id = load_analysis_index()
    papers_by_date: dict[str, list[dict[str, Any]]] = {date: [] for date in dates}
    for paper in read_jsonl(PROJECT_ROOT / "data" / "archive" / "papers.jsonl"):
        source_date = paper_source_date(paper)
        if source_date in papers_by_date:
            papers_by_date[source_date].append(paper_for_site(paper, analysis_by_id))

    return [
        {"date": date, "source": "archive", "papers": sorted_papers_for_export(papers)}
        for date, papers in sorted(papers_by_date.items())
    ]


def month_key(source_date: str) -> str:
    return source_date[:7]


def export_site_data(bundles: list[dict[str, Any]]) -> dict[str, Any]:
    """Write dates.json and per-month JSON files for the SPA to consume at build time."""
    docs_data = PROJECT_ROOT / "docs" / "data"
    by_month_dir = docs_data / "by-month"
    by_month_dir.mkdir(parents=True, exist_ok=True)

    expected_month_files: set[str] = set()
    months: dict[str, dict[str, list[dict[str, Any]]]] = {}
    date_entries: list[dict[str, Any]] = []

    for bundle in bundles:
        source_date = str(bundle.get("date") or "")
        if not source_date:
            continue
        papers = bundle.get("papers", [])
        month = month_key(source_date)
        months.setdefault(month, {})[source_date] = papers
        analyzed_count = sum(1 for paper in papers if paper.get("analysis"))
        date_entries.append({"date": source_date, "month": month, "count": len(papers), "analyzed_count": analyzed_count})

    date_entries = sorted(date_entries, key=lambda item: item["date"], reverse=True)
    latest = next((item["date"] for item in date_entries if item["count"] > 0), date_entries[0]["date"] if date_entries else "")

    for month, dates in sorted(months.items()):
        expected_month_files.add(f"{month}.json")
        write_json(by_month_dir / f"{month}.json", {"month": month, "dates": {date: dates[date] for date in sorted(dates, reverse=True)}})

    for stale_file in by_month_dir.glob("*.json"):
        if stale_file.name not in expected_month_files:
            stale_file.unlink()

    payload = {"latest": latest, "dates": date_entries}
    write_json(docs_data / "dates.json", payload)
    return payload


def render_spa_page(config: dict[str, Any]) -> str:
    site = config.get("site", {})
    title = site.get("title", "arXiv Daily Paper Guide")
    subtitle = site.get("subtitle", "自动生成的每日论文中文导读")
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{h(title)}</title>
  <link rel="stylesheet" href="assets/style.css">
</head>
<body>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        <h1><span class="book-mark">&#128218;</span>{h(title)}</h1>
        <p>{h(subtitle)}</p>
      </div>
      <input id="searchInput" class="search-input" type="search" placeholder="&#128269; 搜索标题 / 关键词...">
      <div class="stat-grid">
        <div class="stat-box"><b id="totalCount">0</b><span>论文总数</span></div>
        <div class="stat-box"><b id="dateCount">0</b><span>有论文日期</span></div>
      </div>
      <button id="clearFilters" class="clear-button" type="button">&#128218; 全部论文</button>

      <section class="nav-section">
        <h2>&#128197; 历史日期</h2>
        <div id="dateNav" class="date-nav"></div>
      </section>
      <section class="nav-section">
        <h2>&#128194; 按大类 -&gt; 小类浏览</h2>
        <div id="topicNav" class="nav-tree"></div>
      </section>
      <section class="nav-section">
        <h2>Priority</h2>
        <div id="priorityFilters" class="chip-list"></div>
      </section>
      <section class="nav-section">
        <h2>Tags</h2>
        <div id="tagFilters" class="chip-list"></div>
      </section>
    </aside>
    <main class="content">
      <header class="page-header">
        <div class="hero-copy">
          <h1>{h(title)} &middot; 中文导读</h1>
          <p>从 arXiv 自动抓取每日论文，基于标题与摘要生成中文导读；每篇论文给出 TL;DR、研究动机、解决问题、现象分析、主要方法、实验信息、贡献与局限。支持搜索、标签、分类和阅读优先级快速筛选。</p>
          <div class="hero-chips">
            <button class="hero-chip active" id="clearFiltersTop" type="button">&#128218; &#20840;&#37096;<span id="heroTotal">0</span>&#31687;</button>
            <button class="hero-chip hot" id="heroHigh" data-priority="high" type="button">&#128293; High<span id="heroHighCount">0</span>&#31687;</button>
            <span class="hero-chip soft" id="currentDateLabel">&#21152;&#36733;&#20013;</span>
          </div>
        </div>
      </header>
      <div class="count-line"><span id="visibleCount">0</span> / <span id="paperTotalInline">0</span> &#31687;&#35542;&#25991;&#21487;&#35265; <span id="activeFilters"></span></div>
      <div id="paperList"></div>
      <div id="noResults" class="empty-state hidden">&#27809;&#26377;&#21305;&#37197;&#24403;&#21069;&#31569;&#36873;&#26465;&#20214;&#30340;&#35542;&#25991;&#12290;</div>
      <div id="loadingState" class="empty-state">&#27491;&#22312;&#21152;&#36733;&#35542;&#25991;&#25968;&#25454;...</div>
      <button id="backToTop" class="back-to-top" type="button" aria-label="&#22238;&#21040;&#39030;&#37096;">&uarr; &#39030;&#37096;</button>
    </main>
  </div>
  <script src="assets/app.js"></script>
</body>
</html>
"""


def build_site(use_mock: bool = False) -> None:
    ensure_dirs()
    config = load_config()
    bundles = archive_bundles(use_mock)
    bundles = sorted(bundles, key=lambda item: item.get("date", ""))
    if not bundles:
        bundles = [{"date": "暂无日期", "source": "empty", "papers": []}]

    data_index = export_site_data(bundles)
    docs_dir = PROJECT_ROOT / "docs"
    (docs_dir / "index.html").write_text(render_spa_page(config), encoding="utf-8")
    LOGGER.info("Built SPA with %d date bundle(s), latest=%s", len(bundles), data_index.get("latest"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the SPA frontend.")
    parser.add_argument("--mock", action="store_true", help="Build with data/mock/analyzed_sample.json.")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    build_site(use_mock=args.mock)


if __name__ == "__main__":
    main()
