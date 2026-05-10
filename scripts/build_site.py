from __future__ import annotations

import argparse
from collections import Counter
import html
import logging
import re
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


def paper_topic(paper: dict[str, Any]) -> str:
    analysis = paper.get("analysis") or {}
    tags = analysis.get("tags") or []
    if tags:
        return str(tags[0])
    return str(paper.get("primary_category") or "未分类")


def category_name(paper: dict[str, Any]) -> str:
    return str(paper.get("primary_category") or (paper.get("categories") or ["未分类"])[0] or "未分类")


def anchor(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", value.strip()).strip("-")
    return slug or "section"


def group_papers(papers: list[dict[str, Any]]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for paper in papers:
        topic = paper_topic(paper)
        category = category_name(paper)
        groups.setdefault(topic, {}).setdefault(category, []).append(paper)
    return groups


def field_row(icon: str, label: str, content: str) -> str:
    return f"""
    <div class="analysis-row">
      <div class="analysis-label"><span>{h(icon)}</span>{h(label)}</div>
      <div class="analysis-content">{content}</div>
    </div>
"""


def paper_card(paper: dict[str, Any]) -> str:
    analysis = paper.get("analysis") or {}
    tags = analysis.get("tags") or []
    priority = analysis.get("reading_priority") or "unknown"
    categories = paper.get("categories") or []
    authors = paper.get("authors") or []
    title = paper.get("title", "")
    search_blob = " ".join(
        [
            title,
            paper.get("abstract", ""),
            analysis.get("one_sentence_summary", ""),
            analysis.get("problem", ""),
            analysis.get("method", ""),
            " ".join(map(str, analysis.get("contributions") or [])),
            analysis.get("experiments", ""),
            analysis.get("relevance", ""),
            " ".join(map(str, tags)),
        ]
    ).lower()
    category_badges = "".join(
        f"<button class=\"topic-badge\" data-filter-category=\"{h(category)}\" type=\"button\">{h(category)}</button>"
        for category in categories
    )
    tag_hashes = "".join(
        f"<button class=\"hash-tag\" data-filter-tag=\"{h(tag)}\" type=\"button\">#{h(tag)}</button>"
        for tag in tags
    )
    priority_label = {"high": "High", "medium": "Medium", "low": "Low"}.get(str(priority), h(priority))
    error_html = ""
    if paper.get("analysis_error"):
        error_html = f"<div class=\"analysis-error\">分析失败：{h(paper.get('analysis_error'))}</div>"

    return f"""
<article class="paper-card" data-priority="{h(priority)}" data-tags="{h('|'.join(tags))}" data-categories="{h('|'.join(categories))}" data-search="{h(search_blob)}">
  <h3 class="paper-title"><a href="{h(paper.get('entry_url'))}" target="_blank" rel="noopener">{h(title)}</a></h3>
  <div class="paper-meta-line">
    {category_badges}
    <span class="priority-pill priority-{h(priority)}">{priority_label}</span>
    <span class="paper-id">{h(paper.get('arxiv_id'))}</span>
    {tag_hashes}
  </div>
  <div class="paper-authors" title="{h(', '.join(authors))}">{h(', '.join(authors[:8]))}{' et al.' if len(authors) > 8 else ''}</div>
  <div class="paper-links">
    <a href="{h(paper.get('entry_url'))}" target="_blank" rel="noopener">arXiv</a>
    <a href="{h(paper.get('pdf_url'))}" target="_blank" rel="noopener">PDF</a>
    <span>{h(paper.get('primary_category'))}</span>
  </div>
  <div class="paper-tldr"><b>TL;DR：</b>{h(analysis.get('one_sentence_summary', '暂无中文导读。'))}</div>
  {error_html}
  <div class="analysis-grid">
    {field_row("🎯", "研究动机", f"<p>{h(analysis.get('problem', '暂无'))}</p>")}
    {field_row("❓", "解决问题", f"<p>{h(analysis.get('problem', '暂无'))}</p>")}
    {field_row("🛠️", "主要方法", f"<p>{h(analysis.get('method', '暂无'))}</p>")}
    {field_row("📊", "数据与实验", f"<p>{h(analysis.get('experiments', '摘要未提供具体实验结果'))}</p>")}
    {field_row("⭐", "主要贡献", list_items(analysis.get('contributions') or []))}
    {field_row("⚠️", "局限性", list_items(analysis.get('limitations') or []))}
    {field_row("🔗", "相关性点评", f"<p>{h(analysis.get('relevance', '暂无'))}</p>")}
  </div>
  <details class="abstract-block">
    <summary>查看完整摘要 (Abstract)</summary>
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


def render_sections(papers: list[dict[str, Any]]) -> str:
    if not papers:
        return "<div class=\"empty-state\">暂无论文数据。可以先运行 mock 模式生成预览页面。</div>"

    sections: list[str] = []
    for topic_name, category_groups in group_papers(papers).items():
        topic_count = sum(len(items) for items in category_groups.values())
        topic_id = "topic-" + anchor(topic_name)
        sub_sections: list[str] = []
        sorted_categories = sorted(category_groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        for cat_name, cat_items in sorted_categories:
            cat_id = f"cat-{anchor(topic_name)}-{anchor(cat_name)}"
            cards = "\n".join(paper_card(paper) for paper in cat_items)
            sub_sections.append(
                f"""
        <section id="{cat_id}" class="sub-sec">
          <h3 class="sub-title">{h(cat_name)} <small>{len(cat_items)} 篇</small></h3>
          <div class="paper-list">{cards}</div>
        </section>
"""
            )
        sections.append(
            f"""
      <section id="{topic_id}" class="paper-section pri-sec" data-section>
        <h2 class="group-title">{h(topic_name)} <small>{topic_count} 篇 · {len(category_groups)} 个细分</small></h2>
        {''.join(sub_sections)}
      </section>
"""
        )
    return "\n".join(sections)


def render_topic_nav(papers: list[dict[str, Any]]) -> str:
    nav: list[str] = []
    groups = group_papers(papers)
    sorted_topics = sorted(groups.items(), key=lambda kv: (-sum(len(v) for v in kv[1].values()), kv[0]))
    for topic_name, category_groups in sorted_topics:
        topic_count = sum(len(items) for items in category_groups.values())
        topic_id = "topic-" + anchor(topic_name)
        sub_links: list[str] = []
        sorted_categories = sorted(category_groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        for cat_name, cat_items in sorted_categories:
            cat_id = f"cat-{anchor(topic_name)}-{anchor(cat_name)}"
            sub_links.append(
                f"<button class=\"nav-sub-link\" data-filter-category=\"{h(cat_name)}\" data-target=\"{cat_id}\" type=\"button\"><span class=\"name\">{h(cat_name)}</span><span class=\"count\">({len(cat_items)})</span></button>"
            )
        nav.append(
            f"""
        <div id="nav-{topic_id}" class="nav-pri" data-topic="{h(topic_name)}">
          <button class="nav-pri-head" type="button">
            <span class="nav-arrow">▶</span>
            <span class="name">{h(topic_name)}</span>
            <span class="count">{topic_count}</span>
          </button>
          <div class="nav-sub-list">{''.join(sub_links)}</div>
        </div>
"""
        )
    return "\n".join(nav)


def render_page(bundle: dict[str, Any], all_dates: list[str], latest: str, is_index: bool, config: dict[str, Any]) -> str:
    date = bundle.get("date", "暂无日期")
    papers = bundle.get("papers", [])
    site = config.get("site", {})
    asset_prefix = "assets" if is_index else "../assets"
    daily_prefix = "daily/" if is_index else ""
    facets, _categories, priorities = collect_facets(papers)
    total_papers = len(papers)
    active_dates = len(all_dates)

    date_links = "\n".join(
        f"<a class=\"date-link {'active' if item == date else ''}\" href=\"{daily_prefix + item + '.html'}\"><span>{h(item)}</span></a>"
        for item in sorted(all_dates, reverse=True)
    )
    topic_nav = render_topic_nav(papers)
    tag_buttons = "\n".join(
        f"<button class=\"filter-chip\" data-filter-tag=\"{h(item)}\" type=\"button\">#{h(item)}</button>"
        for item in facets[:28]
    )
    priority_buttons = "\n".join(
        f"<button class=\"filter-chip priority-filter\" data-filter-priority=\"{name}\" type=\"button\">{name} <b>{count}</b></button>"
        for name, count in priorities.items()
    )
    sections = render_sections(papers)
    intro = (
        "从 arXiv 自动抓取每日论文，基于标题与摘要生成中文导读；"
        "每篇论文给出研究动机、解决问题、主要方法、实验信息、贡献、局限与相关性点评。"
        "左侧可按日期、方向、分类、优先级与关键词快速筛选。"
    )

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
        <h1><span class="book-mark">📚</span>{h(site.get('title', 'arXiv Daily Paper Guide'))}</h1>
        <p>{h(site.get('subtitle', '自动生成的每日论文中文导读'))}</p>
      </div>
      <input id="searchInput" class="search-input" type="search" placeholder="🔍 搜索标题 / 关键词…">
      <div class="stat-grid">
        <div class="stat-box"><b>{total_papers}</b><span>论文总数</span></div>
        <div class="stat-box"><b>{active_dates}</b><span>历史日期</span></div>
      </div>
      <button id="clearFilters" class="clear-button" type="button">📚 全部 {total_papers} 篇</button>

      <section class="nav-section">
        <h2>📅 历史日期</h2>
        <div class="date-list">{date_links}</div>
      </section>
      <section class="nav-section">
        <h2>📁 按论文方向 → arXiv 分类浏览</h2>
        <div class="nav-tree">{topic_nav or '<span class="muted">暂无方向</span>'}</div>
      </section>
      <section class="nav-section">
        <h2>🎚 Priority</h2>
        <div class="chip-list">{priority_buttons}</div>
      </section>
      <section class="nav-section">
        <h2># Tags</h2>
        <div class="chip-list">{tag_buttons or '<span class="muted">暂无 tags</span>'}</div>
      </section>
    </aside>
    <main class="content">
      <header class="page-header">
        <div class="hero-copy">
          <h1>{h(site.get('title', 'arXiv Daily Paper Guide'))} · 中文导读</h1>
          <p>{h(intro)}</p>
          <div class="hero-chips">
            <button class="hero-chip active" id="clearFiltersTop" type="button">📚 全部 <span>{total_papers}</span> 篇</button>
            <button class="hero-chip hot" data-filter-priority="high" type="button">🔥 High <span>{priorities.get('high', 0)}</span> 篇</button>
            <span class="hero-chip soft">📅 {h(date)}</span>
          </div>
        </div>
      </header>
      <div class="count-line"><span id="visibleCount">{len(papers)}</span> / {len(papers)} 篇论文可见 <span id="activeFilters"></span></div>
      <div id="paperList">
        {sections}
      </div>
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
