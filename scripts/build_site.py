from __future__ import annotations

import argparse
import html
import json
import logging
from pathlib import Path
from typing import Any

from utils import PROJECT_ROOT, ensure_dirs, load_config, read_json, setup_logging, write_json


LOGGER = logging.getLogger("build_site")


def h(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def load_analyzed_data(use_mock: bool = False) -> list[dict[str, Any]]:
    ensure_dirs()
    files = sorted((PROJECT_ROOT / "data" / "analyzed").glob("*.json"))
    if use_mock or not files:
        mock_path = PROJECT_ROOT / "data" / "mock" / "analyzed_sample.json"
        if mock_path.exists():
            LOGGER.info("Using mock analyzed data from %s", mock_path)
            return [read_json(mock_path)]
    return [read_json(path) for path in files]


def list_items(values: list[Any]) -> str:
    if not values:
        return "<span class=\"muted\">无</span>"
    return "<ul>" + "".join(f"<li>{h(value)}</li>" for value in values) + "</ul>"


def badges(values: list[Any], class_name: str = "badge") -> str:
    return "".join(f"<button class=\"{class_name}\" data-filter-tag=\"{h(value)}\" type=\"button\">{h(value)}</button>" for value in values)


def paper_card(paper: dict[str, Any]) -> str:
    analysis = paper.get("analysis") or {}
    tags = analysis.get("tags") or []
    priority = analysis.get("reading_priority") or "unknown"
    categories = paper.get("categories") or []
    authors = paper.get("authors") or []
    search_blob = " ".join(
        [
            paper.get("title", ""),
            paper.get("abstract", ""),
            analysis.get("one_sentence_summary", ""),
            analysis.get("problem", ""),
            analysis.get("method", ""),
            " ".join(tags),
        ]
    ).lower()
    error_html = ""
    if paper.get("analysis_error"):
        error_html = f"<div class=\"analysis-error\">分析失败：{h(paper.get('analysis_error'))}</div>"

    return f"""
<article class="paper-card" data-priority="{h(priority)}" data-tags="{h('|'.join(tags))}" data-categories="{h('|'.join(categories))}" data-search="{h(search_blob)}">
  <div class="paper-topline">
    <span class="priority priority-{h(priority)}">{h(priority)}</span>
    <span class="paper-id">{h(paper.get('arxiv_id'))}</span>
  </div>
  <h2 class="paper-title">{h(paper.get('title'))}</h2>
  <div class="paper-authors" title="{h(', '.join(authors))}">{h(', '.join(authors[:8]))}{' et al.' if len(authors) > 8 else ''}</div>
  <div class="paper-links">
    <a href="{h(paper.get('entry_url'))}" target="_blank" rel="noopener">arXiv</a>
    <a href="{h(paper.get('pdf_url'))}" target="_blank" rel="noopener">PDF</a>
    <span>{h(paper.get('primary_category'))}</span>
  </div>
  <div class="badge-row">{badges(categories, "badge category-badge")} {badges(tags, "badge tag-badge")}</div>
  <div class="summary">{h(analysis.get('one_sentence_summary', '暂无中文导读。'))}</div>
  {error_html}
  <details class="analysis-block" open>
    <summary>导读详情</summary>
    <div class="field"><b>研究问题</b><p>{h(analysis.get('problem', '暂无'))}</p></div>
    <div class="field"><b>方法概括</b><p>{h(analysis.get('method', '暂无'))}</p></div>
    <div class="field"><b>贡献点</b>{list_items(analysis.get('contributions') or [])}</div>
    <div class="field"><b>实验信息</b><p>{h(analysis.get('experiments', '摘要未提供具体实验结果'))}</p></div>
    <div class="field"><b>局限性</b>{list_items(analysis.get('limitations') or [])}</div>
    <div class="field"><b>相关性点评</b><p>{h(analysis.get('relevance', '暂无'))}</p></div>
  </details>
  <details class="abstract-block">
    <summary>Abstract</summary>
    <p>{h(paper.get('abstract'))}</p>
  </details>
</article>
"""


def collect_facets(papers: list[dict[str, Any]]) -> tuple[list[str], list[str], dict[str, int]]:
    tags = sorted({tag for paper in papers for tag in (paper.get("analysis") or {}).get("tags", [])})
    categories = sorted({category for paper in papers for category in paper.get("categories", [])})
    priorities: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    for paper in papers:
        priority = (paper.get("analysis") or {}).get("reading_priority")
        if priority in priorities:
            priorities[priority] += 1
    return tags + categories, categories, priorities


def render_page(bundle: dict[str, Any], all_dates: list[str], latest: str, is_index: bool, config: dict[str, Any]) -> str:
    date = bundle.get("date", "暂无日期")
    papers = bundle.get("papers", [])
    site = config.get("site", {})
    asset_prefix = "assets" if is_index else "../assets"
    daily_prefix = "daily/" if is_index else ""
    facets, categories, priorities = collect_facets(papers)
    date_links = "\n".join(
        f"<a class=\"date-link {'active' if item == date else ''}\" href=\"{daily_prefix + item + '.html'}\">{h(item)}</a>"
        for item in sorted(all_dates, reverse=True)
    )
    tag_buttons = "\n".join(f"<button class=\"filter-chip\" data-filter-tag=\"{h(item)}\" type=\"button\">{h(item)}</button>" for item in facets)
    category_buttons = "\n".join(f"<button class=\"filter-chip\" data-filter-category=\"{h(item)}\" type=\"button\">{h(item)}</button>" for item in categories)
    priority_buttons = "\n".join(
        f"<button class=\"filter-chip priority-filter\" data-filter-priority=\"{name}\" type=\"button\">{name} <span>{count}</span></button>"
        for name, count in priorities.items()
    )
    cards = "\n".join(paper_card(paper) for paper in papers) or "<div class=\"empty-state\">暂无论文数据。可以先运行 mock 模式生成预览页面。</div>"
    stats = f"{len(papers)} papers · {len(facets)} tags/categories"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{h(site.get('title', 'arXiv Daily Paper Guide'))} · {h(date)}</title>
  <link rel="stylesheet" href="{asset_prefix}/style.css">
</head>
<body>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="eyebrow">Daily arXiv</div>
        <h1>{h(site.get('title', 'arXiv Daily Paper Guide'))}</h1>
        <p>{h(site.get('subtitle', '自动生成的每日论文中文导读'))}</p>
      </div>
      <label class="search-label" for="searchInput">搜索论文</label>
      <input id="searchInput" class="search-input" type="search" placeholder="title / abstract / tag / 中文导读">
      <button id="clearFilters" class="clear-button" type="button">Show all / Clear filters</button>

      <section class="nav-section">
        <h2>历史日期</h2>
        <div class="date-list">{date_links}</div>
      </section>
      <section class="nav-section">
        <h2>Priority</h2>
        <div class="chip-list">{priority_buttons}</div>
      </section>
      <section class="nav-section">
        <h2>论文方向分类</h2>
        <div class="chip-list">{category_buttons or '<span class="muted">暂无分类</span>'}</div>
      </section>
      <section class="nav-section">
        <h2>Tags</h2>
        <div class="chip-list">{tag_buttons or '<span class="muted">暂无 tags</span>'}</div>
      </section>
    </aside>
    <main class="content">
      <header class="page-header">
        <div>
          <div class="eyebrow">Generated guide</div>
          <h1>{h(date)} 论文导读</h1>
          <p>{h(stats)} · <span id="visibleCount">{len(papers)}</span> visible</p>
        </div>
        <a class="data-link" href="{asset_prefix.replace('assets', 'data')}/dates.json">dates.json</a>
      </header>
      <div id="activeFilters" class="active-filters"></div>
      <section id="paperList" class="paper-list">
        {cards}
      </section>
      <div id="noResults" class="empty-state hidden">没有匹配当前筛选条件的论文。</div>
    </main>
  </div>
  <script src="{asset_prefix}/app.js"></script>
</body>
</html>
"""


def build_site(use_mock: bool = False) -> None:
    ensure_dirs()
    config = load_config()
    bundles = load_analyzed_data(use_mock)
    bundles = sorted(bundles, key=lambda item: item.get("date", ""))
    if not bundles:
        bundles = [{"date": "暂无日期", "source": "empty", "papers": []}]

    dates = [bundle.get("date", "") for bundle in bundles if bundle.get("date")]
    non_empty_bundles = [bundle for bundle in bundles if bundle.get("papers")]
    latest_bundle = non_empty_bundles[-1] if non_empty_bundles else bundles[-1]
    latest = latest_bundle.get("date", dates[-1] if dates else "")
    docs_dir = PROJECT_ROOT / "docs"
    daily_dir = docs_dir / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)

    for bundle in bundles:
        date = bundle.get("date", "empty")
        html_text = render_page(bundle, dates, latest, is_index=False, config=config)
        (daily_dir / f"{date}.html").write_text(html_text, encoding="utf-8")

    (docs_dir / "index.html").write_text(render_page(latest_bundle, dates, latest, is_index=True, config=config), encoding="utf-8")
    write_json(docs_dir / "data" / "dates.json", {"latest": latest, "dates": dates})
    LOGGER.info("Built site with %d date bundle(s)", len(bundles))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the static GitHub Pages site.")
    parser.add_argument("--mock", action="store_true", help="Build with data/mock/analyzed_sample.json.")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    build_site(use_mock=args.mock)


if __name__ == "__main__":
    main()
