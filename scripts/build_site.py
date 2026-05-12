from __future__ import annotations

import argparse
import calendar
from collections import Counter
from datetime import date as Date
from datetime import datetime
import html
import logging
import re
from typing import Any

from utils import PROJECT_ROOT, ensure_dirs, load_config, read_json, setup_logging, write_json


LOGGER = logging.getLogger("build_site")
TAXONOMY_PATH = PROJECT_ROOT / "data" / "iclr_taxonomy.json"


def h(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def cjk_spacing(value: Any) -> str:
    text = str(value or "")
    ascii_token = r"A-Za-z0-9@#&%/+=\\-"
    text = re.sub(rf"([\u4e00-\u9fff])([{ascii_token}])", r"\1 \2", text)
    text = re.sub(rf"([{ascii_token}])([\u4e00-\u9fff])", r"\1 \2", text)
    return text


def ht(value: Any) -> str:
    return h(cjk_spacing(value))


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
    return "<ul>" + "".join(f"<li>{ht(value)}</li>" for value in values) + "</ul>"


def paper_tags(paper: dict[str, Any]) -> list[str]:
    analysis = paper.get("analysis") or {}
    return [str(tag) for tag in analysis.get("tags", []) if tag]


def normalize_label(value: str) -> str:
    return re.sub(r"\s+", "", value.replace("：", ":").strip().lower())


def load_taxonomy() -> dict[str, Any]:
    if not TAXONOMY_PATH.exists():
        return {"areas": []}
    return read_json(TAXONOMY_PATH)


def taxonomy_area_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for area in load_taxonomy().get("areas", []):
        primary = str(area.get("primary_area") or "").strip()
        if primary:
            mapping[normalize_label(primary)] = primary
    return mapping


def taxonomy_category_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for area in load_taxonomy().get("areas", []):
        for category in area.get("categories", []):
            category_name = str(category).strip()
            if category_name:
                mapping[normalize_label(category_name)] = category_name
    return mapping


def taxonomy_category_area_map() -> dict[str, str]:
    candidates: dict[str, set[str]] = {}
    for area in load_taxonomy().get("areas", []):
        primary = str(area.get("primary_area") or "").strip()
        for category in area.get("categories", []):
            candidates.setdefault(normalize_label(str(category)), set()).add(primary)
    return {category: next(iter(areas)) for category, areas in candidates.items() if len(areas) == 1}


def taxonomy_area_categories_map() -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}
    for area in load_taxonomy().get("areas", []):
        primary = str(area.get("primary_area") or "").strip()
        if not primary:
            continue
        mapping[primary] = {normalize_label(str(category)) for category in area.get("categories", [])}
    return mapping


AREA_MAP = taxonomy_area_map()
CATEGORY_MAP = taxonomy_category_map()
CATEGORY_AREA_MAP = taxonomy_category_area_map()
AREA_CATEGORIES_MAP = taxonomy_area_categories_map()
DEFAULT_AREA = AREA_MAP.get(normalize_label("其他 ML 主题"), "其他 ML 主题")
DEFAULT_CATEGORY = CATEGORY_MAP.get(normalize_label("其他"), "其他")


def canonical_area(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    direct = AREA_MAP.get(normalize_label(cleaned))
    if direct:
        return direct
    legacy_aliases = {
        normalize_label("医学与科学AI"): "应用: CV/音频/语言等",
        normalize_label("医学与科学 AI"): "应用: CV/音频/语言等",
    }
    alias = legacy_aliases.get(normalize_label(cleaned))
    return AREA_MAP.get(normalize_label(alias), alias) if alias else ""


def canonical_category(value: str, area: str) -> str:
    category = CATEGORY_MAP.get(normalize_label(value))
    if category and (not area or normalize_label(category) in AREA_CATEGORIES_MAP.get(area, set())):
        return category
    return DEFAULT_CATEGORY


def primary_area(paper: dict[str, Any]) -> str:
    analysis = paper.get("analysis") or {}
    category = str(analysis.get("category") or analysis.get("sub_area") or "").strip()
    category_area = CATEGORY_AREA_MAP.get(normalize_label(category))
    if category_area:
        return category_area
    area = canonical_area(str(analysis.get("primary_area") or ""))
    if area:
        return area
    return DEFAULT_AREA


def sub_area(paper: dict[str, Any]) -> str:
    analysis = paper.get("analysis") or {}
    area = primary_area(paper)
    category = str(analysis.get("category") or analysis.get("sub_area") or "").strip()
    return canonical_category(category, area)


def anchor(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", value.strip()).strip("-")
    return slug or "section"


def group_papers(papers: list[dict[str, Any]]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for paper in papers:
        topic = primary_area(paper)
        category = sub_area(paper)
        groups.setdefault(topic, {}).setdefault(category, []).append(paper)
    return groups


def field_row(icon: str, label: str, content: str) -> str:
    return f"""
    <div class="analysis-row">
      <div class="analysis-label"><span>{h(icon)}</span>{h(label)}</div>
      <div class="analysis-content">{content}</div>
    </div>
"""


def analysis_text(analysis: dict[str, Any], *keys: str, default: str = "暂无") -> str:
    for key in keys:
        value = analysis.get(key)
        if value:
            return str(value)
    return default


def paper_card(paper: dict[str, Any]) -> str:
    analysis = paper.get("analysis") or {}
    tags = analysis.get("tags") or []
    priority = analysis.get("reading_priority") or "unknown"
    categories = paper.get("categories") or []
    area = primary_area(paper)
    sub = sub_area(paper)
    authors = paper.get("authors") or []
    title = paper.get("title", "")
    tldr = analysis_text(analysis, "tldr", "one_sentence_summary", default="暂无中文导读。")
    motivation = analysis_text(
        analysis,
        "research_motivation",
        "motivation",
        default="旧数据未提供研究动机；重新分析后会生成该字段。",
    )
    phenomenon = analysis_text(analysis, "phenomenon_analysis", "phenomena", default="摘要未提供明确现象分析。")
    search_blob = " ".join(
        [
            title,
            paper.get("abstract", ""),
            tldr,
            motivation,
            analysis.get("problem", ""),
            phenomenon,
            analysis.get("method", ""),
            " ".join(map(str, analysis.get("contributions") or [])),
            analysis.get("experiments", ""),
            area,
            sub,
            " ".join(map(str, tags)),
        ]
    ).lower()
    area_badges = (
        f"<button class=\"topic-badge\" data-filter-area=\"{h(area)}\" type=\"button\">{h(area)}</button>"
        f"<button class=\"topic-badge subarea-badge\" data-filter-subarea=\"{h(sub)}\" type=\"button\">{h(sub)}</button>"
    )
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
<article class="paper-card" data-priority="{h(priority)}" data-tags="{h('|'.join(tags))}" data-categories="{h('|'.join(categories))}" data-area="{h(area)}" data-subarea="{h(sub)}" data-search="{h(search_blob)}">
  <h3 class="paper-title"><a href="{h(paper.get('entry_url'))}" target="_blank" rel="noopener">{h(title)}</a></h3>
  <div class="paper-meta-line">
    {area_badges}
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
  <div class="paper-tldr"><b>TL;DR：</b>{ht(tldr)}</div>
  {error_html}
  <div class="analysis-grid">
    {field_row("🎯", "研究动机", f"<p>{ht(motivation)}</p>")}
    {field_row("❓", "解决问题", f"<p>{ht(analysis.get('problem', '暂无'))}</p>")}
    {field_row("🔎", "现象分析", f"<p>{ht(phenomenon)}</p>")}
    {field_row("🛠️", "主要方法", f"<p>{ht(analysis.get('method', '暂无'))}</p>")}
    {field_row("📊", "实验结果", f"<p>{ht(analysis.get('experiments', '摘要未提供具体实验结果'))}</p>")}
    {field_row("⭐", "主要贡献", list_items(analysis.get('contributions') or []))}
    {field_row("⚠️", "方法局限", list_items(analysis.get('limitations') or []))}
  </div>
  <details class="abstract-block">
    <summary>查看完整摘要 (Abstract)</summary>
    <p>{h(paper.get('abstract'))}</p>
  </details>
</article>
"""


def collect_facets(papers: list[dict[str, Any]]) -> tuple[list[tuple[str, int]], list[str], dict[str, int]]:
    tag_counts = Counter(
        str(tag)
        for paper in papers
        for tag in (paper.get("analysis") or {}).get("tags", [])
        if tag
    )
    top_tags = sorted(tag_counts.items(), key=lambda item: (-item[1], item[0]))[:20]
    categories = sorted({category for paper in papers for category in paper.get("categories", [])})
    priorities: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    for paper in papers:
        priority = (paper.get("analysis") or {}).get("reading_priority")
        if priority in priorities:
            priorities[priority] += 1
    return top_tags, categories, priorities


def parse_date_value(value: str) -> Date | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def iter_months(start: Date, end: Date) -> list[tuple[int, int]]:
    months: list[tuple[int, int]] = []
    cursor = Date(start.year, start.month, 1)
    last = Date(end.year, end.month, 1)
    while cursor <= last:
        months.append((cursor.year, cursor.month))
        if cursor.month == 12:
            cursor = Date(cursor.year + 1, 1, 1)
        else:
            cursor = Date(cursor.year, cursor.month + 1, 1)
    return months


def render_calendar(date_counts: dict[str, int], current_date: str, is_index: bool) -> str:
    parsed_dates = [item for item in (parse_date_value(value) for value in date_counts) if item]
    if not parsed_dates:
        return "<div class=\"calendar-empty\">暂无历史日期</div>"

    day_names = ["一", "二", "三", "四", "五", "六", "日"]
    calendars: list[str] = []
    for year, month in iter_months(min(parsed_dates), max(parsed_dates)):
        weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
        week_rows: list[str] = []
        for week in weeks:
            cells: list[str] = []
            for day in week:
                iso = day.isoformat()
                count = date_counts.get(iso, 0)
                classes = ["calendar-day"]
                if day.month != month:
                    classes.append("outside")
                if iso == current_date:
                    classes.append("active")
                if count > 0 and day.month == month:
                    href = f"daily/{iso}.html" if is_index else f"{iso}.html"
                    cells.append(f"<a class=\"{' '.join(classes)}\" href=\"{href}\" title=\"{h(iso)} · {count} 篇\"><span>{day.day}</span><em>{count}</em></a>")
                else:
                    classes.append("disabled")
                    cells.append(f"<span class=\"{' '.join(classes)}\" title=\"{h(iso)}\"><span>{day.day}</span></span>")
            week_rows.append(f"<div class=\"calendar-week\">{''.join(cells)}</div>")
        calendars.append(
            f"""
        <div class="calendar-month">
          <div class="calendar-title">{year}-{month:02d}</div>
          <div class="calendar-week calendar-head">{''.join(f'<b>{name}</b>' for name in day_names)}</div>
          {''.join(week_rows)}
        </div>
"""
        )
    return "\n".join(calendars)


def render_sections(papers: list[dict[str, Any]]) -> str:
    if not papers:
        return "<div class=\"empty-state\">暂无论文数据。可以先运行 mock 模式生成预览页面。</div>"

    sections: list[str] = []
    for topic_name, category_groups in group_papers(papers).items():
        topic_count = sum(len(items) for items in category_groups.values())
        topic_id = "area-" + anchor(topic_name)
        sub_sections: list[str] = []
        sorted_categories = sorted(category_groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        for cat_name, cat_items in sorted_categories:
            cat_id = f"sub-{anchor(topic_name)}-{anchor(cat_name)}"
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
        topic_id = "area-" + anchor(topic_name)
        sub_links: list[str] = []
        sorted_categories = sorted(category_groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        for cat_name, cat_items in sorted_categories:
            cat_id = f"sub-{anchor(topic_name)}-{anchor(cat_name)}"
            sub_links.append(
                f"<button class=\"nav-sub-link\" data-filter-subarea=\"{h(cat_name)}\" data-target=\"{cat_id}\" type=\"button\"><span class=\"name\">{h(cat_name)}</span><span class=\"count\">({len(cat_items)})</span></button>"
            )
        nav.append(
            f"""
        <div id="nav-{topic_id}" class="nav-pri" data-area="{h(topic_name)}">
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


def render_page(
    bundle: dict[str, Any],
    date_counts: dict[str, int],
    is_index: bool,
    config: dict[str, Any],
) -> str:
    date = bundle.get("date", "暂无日期")
    papers = bundle.get("papers", [])
    site = config.get("site", {})
    asset_prefix = "assets" if is_index else "../assets"
    top_tags, _categories, priorities = collect_facets(papers)
    total_papers = len(papers)
    active_dates = sum(1 for value in date_counts.values() if value > 0)
    calendar_html = render_calendar(date_counts, date, is_index)
    topic_nav = render_topic_nav(papers)
    tag_buttons = "\n".join(
        f"<button class=\"filter-chip\" data-filter-tag=\"{h(tag)}\" type=\"button\">#{h(tag)} <b>{count}</b></button>"
        for tag, count in top_tags
    )
    priority_buttons = "\n".join(
        f"<button class=\"filter-chip priority-filter\" data-filter-priority=\"{name}\" type=\"button\">{name} <b>{count}</b></button>"
        for name, count in priorities.items()
    )
    sections = render_sections(papers)
    intro = (
        "从 arXiv 自动抓取每日论文，基于标题与摘要生成中文导读；"
        "每篇论文给出 TL;DR、研究动机、解决问题、现象分析、主要方法、实验信息、贡献与局限。"
        "左侧可按日期、大类/小类、优先级与关键词快速筛选。"
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
        <div class="stat-box"><b>{active_dates}</b><span>有论文日期</span></div>
      </div>
      <button id="clearFilters" class="clear-button" type="button">📚 全部 {total_papers} 篇</button>

      <section class="nav-section">
        <h2>📅 历史日期</h2>
        <div class="calendar-wrap">{calendar_html}</div>
      </section>
      <section class="nav-section">
        <h2>📁 按大类 → 小类浏览</h2>
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
    date_counts = {bundle.get("date", ""): len(bundle.get("papers", [])) for bundle in bundles if bundle.get("date")}
    non_empty_bundles = [bundle for bundle in bundles if bundle.get("papers")]
    latest_bundle = non_empty_bundles[-1] if non_empty_bundles else bundles[-1]
    latest = latest_bundle.get("date", dates[-1] if dates else "")
    docs_dir = PROJECT_ROOT / "docs"
    daily_dir = docs_dir / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    expected_daily_files = {f"{date}.html" for date in dates}
    for stale_page in daily_dir.glob("*.html"):
        if stale_page.name not in expected_daily_files:
            stale_page.unlink()

    for bundle in bundles:
        date = bundle.get("date", "empty")
        html_text = render_page(bundle, date_counts, is_index=False, config=config)
        (daily_dir / f"{date}.html").write_text(html_text, encoding="utf-8")

    (docs_dir / "index.html").write_text(render_page(latest_bundle, date_counts, is_index=True, config=config), encoding="utf-8")
    write_json(docs_dir / "data" / "dates.json", {"latest": latest, "dates": dates, "counts": date_counts})
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
