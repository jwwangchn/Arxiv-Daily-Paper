(function () {
  const WORKER_URL = window.API_BASE_URL ?? "https://arxiv-daily-api.jwwangchn.workers.dev";
  const PAGE_SIZE = 50;

  const state = {
    date: "",
    query: "",
    priority: "",
    tag: "",
    area: "",
    subarea: "",
    subareaParent: "",
    dateIndex: null,
    papers: [],
    total: 0,
    page: 0,
    facetData: null,
    paperCache: new Map(),
    facetCache: new Map(),
    paperRequests: new Map(),
    activeFetch: null,
    searchTimer: null,
    expandedAreas: new Set(),
    calendarMonth: "",
  };

  const els = {
    search: document.getElementById("searchInput"),
    clear: document.getElementById("clearFilters"),
    clearTop: document.getElementById("clearFiltersTop"),
    dateNav: document.getElementById("dateNav"),
    topicNav: document.getElementById("topicNav"),
    priorityFilters: document.getElementById("priorityFilters"),
    tagFilters: document.getElementById("tagFilters"),
    paperList: document.getElementById("paperList"),
    visibleCount: document.getElementById("visibleCount"),
    paperTotalInline: document.getElementById("paperTotalInline"),
    totalCount: document.getElementById("totalCount"),
    dateCount: document.getElementById("dateCount"),
    heroTotal: document.getElementById("heroTotal"),
    heroHigh: document.getElementById("heroHigh"),
    heroHighCount: document.getElementById("heroHighCount"),
    currentDateLabel: document.getElementById("currentDateLabel"),
    activeFilters: document.getElementById("activeFilters"),
    noResults: document.getElementById("noResults"),
    loading: document.getElementById("loadingState"),
    backToTop: document.getElementById("backToTop"),
    todayButton: document.getElementById("todayButton"),
    content: document.querySelector(".content"),
  };

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function normalize(value) {
    return String(value || "").toLowerCase().trim();
  }

  function dateEntries() {
    return (state.dateIndex && state.dateIndex.dates) || [];
  }

  function entryForDate(date) {
    return dateEntries().find((item) => item.date === date);
  }

  function priorityRank(priority) {
    return { high: 0, medium: 1, low: 2 }[priority] ?? 4;
  }

  function paperTime(paper) {
    return Date.parse(paper.updated || paper.published || "") || 0;
  }

  function paperPriority(paper) {
    return normalize((paper.analysis || {}).reading_priority) || "unknown";
  }

  function paperArea(paper) {
    const area = (paper.analysis || {}).primary_area;
    return area || (paper.has_analysis ? "其他 ML 主题" : "未分析");
  }

  function paperSubarea(paper) {
    if (paperArea(paper) === "未分析") return "未分析";
    const analysis = paper.analysis || {};
    return analysis.category || analysis.sub_area || "其他";
  }

  function sortPapers(papers) {
    return [...papers].sort((a, b) => {
      return (
        paperArea(a).localeCompare(paperArea(b), "zh-Hans-CN") ||
        paperSubarea(a).localeCompare(paperSubarea(b), "zh-Hans-CN") ||
        priorityRank(paperPriority(a)) - priorityRank(paperPriority(b)) ||
        paperTime(b) - paperTime(a) ||
        String(a.arxiv_id || "").localeCompare(String(b.arxiv_id || ""))
      );
    });
  }

  function updateUrl(date) {
    const url = new URL(window.location.href);
    url.searchParams.set("date", date);
    window.history.replaceState({}, "", url);
  }

  function clearFilters() {
    state.query = "";
    state.priority = "";
    state.tag = "";
    state.area = "";
    state.subarea = "";
    state.subareaParent = "";
    state.page = 0;
    state.expandedAreas.clear();
    if (els.search) els.search.value = "";
    renderPapers();
  }

  function facetCounts(papers) {
    const priorities = { high: 0, medium: 0, low: 0 };
    const tags = new Map();
    const areas = new Map();
    for (const paper of papers) {
      const priority = paperPriority(paper);
      if (priority in priorities) priorities[priority] += 1;
      // Unanalyzed papers: no tags, no subareas
      const area = paperArea(paper);
      if (area === "未分析") {
        if (!areas.has(area)) areas.set(area, new Map());
        areas.get(area).set("未分析", (areas.get(area).get("未分析") || 0) + 1);
        continue;
      }
      for (const tag of (paper.analysis || {}).tags || []) {
        tags.set(tag, (tags.get(tag) || 0) + 1);
      }
      const sub = paperSubarea(paper);
      if (!areas.has(area)) areas.set(area, new Map());
      const subMap = areas.get(area);
      subMap.set(sub, (subMap.get(sub) || 0) + 1);
    }
    return { priorities, tags, areas };
  }

  function buildCalendarMonth(year, month, dateCounts, activeDate) {
    const dayNames = ["一", "二", "三", "四", "五", "六", "日"];
    const firstDay = new Date(year, month - 1, 1);
    const lastDay = new Date(year, month, 0);
    const prevLastDay = new Date(year, month - 1, 0);
    let startDow = firstDay.getDay() || 7;
    const cells = [];
    for (let i = startDow - 1; i > 0; i--) {
      cells.push({ day: prevLastDay.getDate() - i + 1, outside: true });
    }
    for (let d = 1; d <= lastDay.getDate(); d++) {
      const dt = `${year}-${String(month).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      cells.push({ day: d, date: dt, count: dateCounts[dt] || 0 });
    }
    let nextDay = 1;
    while (cells.length % 7 !== 0) {
      cells.push({ day: nextDay, outside: true });
      nextDay += 1;
    }

    const headRow = `<div class="calendar-week calendar-head">${dayNames.map((name) => `<b>${name}</b>`).join("")}</div>`;
    const weekRows = [];
    for (let i = 0; i < cells.length; i += 7) {
      const week = cells.slice(i, i + 7);
      const dayCells = week
        .map((item) => {
          if (item.outside) {
            return `<span class="calendar-day outside disabled" aria-hidden="true"><span>${item.day}</span></span>`;
          }
          const classes = ["calendar-day"];
          if (item.date === activeDate) classes.push("active");
          if (item.count > 0) {
            return `<a class="${classes.join(" ")}" href="?date=${escapeHtml(item.date)}" data-date="${escapeHtml(item.date)}" title="${escapeHtml(item.date)} · ${item.count} 篇"><span>${item.day}</span><em>${item.count}</em></a>`;
          }
          classes.push("disabled");
          return `<span class="${classes.join(" ")}" title="${escapeHtml(item.date)}"><span>${item.day}</span></span>`;
        })
        .join("");
      weekRows.push(`<div class="calendar-week">${dayCells}</div>`);
    }

    return `
      <div class="calendar-month">
        ${headRow}
        ${weekRows.join("")}
      </div>`;
  }

  function renderDates() {
    const entries = dateEntries();
    const activeCount = entries.filter((item) => item.count > 0).length;
    els.dateCount.textContent = String(activeCount);

    const dateCounts = {};
    for (const item of entries) {
      dateCounts[item.date] = item.count;
    }

    const months = [...new Set(entries.filter(e => e.count > 0).map(e => e.month))].sort();
    if (months.length === 0) {
      els.dateNav.innerHTML = '<span class="muted">暂无数据</span>';
      return;
    }

    if (!state.calendarMonth || !months.includes(state.calendarMonth)) {
      state.calendarMonth = state.date ? state.date.slice(0, 7) : months[months.length - 1];
    }

    const monthIndex = months.indexOf(state.calendarMonth);
    const [year, monthNumber] = state.calendarMonth.split("-").map(Number);
    els.dateNav.innerHTML = `
      <div class="calendar-wrap">
        <div class="calendar-switcher">
          <button class="calendar-nav-btn" data-calendar-prev type="button"${monthIndex <= 0 ? " disabled" : ""}>‹</button>
          <span>${state.calendarMonth}</span>
          <button class="calendar-nav-btn" data-calendar-next type="button"${monthIndex >= months.length - 1 ? " disabled" : ""}>›</button>
        </div>
        ${buildCalendarMonth(year, monthNumber, dateCounts, state.date)}
      </div>`;
  }

  function shiftCalendarMonth(direction) {
    const months = [...new Set(dateEntries().filter((item) => item.count > 0).map((item) => item.month))].sort();
    const current = state.calendarMonth || (state.date ? state.date.slice(0, 7) : months[months.length - 1]);
    const next = months[months.indexOf(current) + direction];
    if (next) {
      state.calendarMonth = next;
      renderDates();
    }
  }

  function renderFacets(papers) {
    const facetData = Array.isArray(papers) ? facetCounts(papers) : papers;
    const priorities = facetData.priorities || { high: 0, medium: 0, low: 0 };
    const tags = facetData.tags instanceof Map ? facetData.tags : new Map(facetData.tags || []);
    const areas = facetData.areas instanceof Map
      ? facetData.areas
      : new Map((facetData.areas || []).map(([area, subs]) => [area, new Map(subs)]));
    els.priorityFilters.innerHTML = Object.entries(priorities)
      .map(([name, count]) => `<button class="filter-chip${state.priority === name ? " active" : ""}" data-priority="${name}" type="button">${name} <b>${count}</b></button>`)
      .join("");
    els.tagFilters.innerHTML = [...tags.entries()]
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .slice(0, 20)
      .map(([tag, count]) => `<button class="filter-chip${state.tag === tag ? " active" : ""}" data-tag="${escapeHtml(tag)}" type="button">#${escapeHtml(tag)} <b>${count}</b></button>`)
      .join("") || '<span class="muted">暂无 tags</span>';
    els.topicNav.innerHTML = [...areas.entries()]
      .sort((a, b) => {
        const aIsUn = a[0] === "未分析";
        const bIsUn = b[0] === "未分析";
        if (aIsUn !== bIsUn) return aIsUn ? 1 : -1;
        const ac = [...a[1].values()].reduce((sum, value) => sum + value, 0);
        const bc = [...b[1].values()].reduce((sum, value) => sum + value, 0);
        return bc - ac || a[0].localeCompare(b[0]);
      })
      .map(([area, subMap]) => {
        const count = [...subMap.values()].reduce((sum, value) => sum + value, 0);
        const expanded = state.expandedAreas.has(area) || state.area === area || state.subareaParent === area;
        const activeArea = state.area === area ? " active" : "";
        const expandedClass = expanded ? " expanded" : "";
        const subs = [...subMap.entries()]
          .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
          .map(([sub, subCount]) => {
            const activeSub = state.subareaParent === area && state.subarea === sub ? " active" : "";
            return `<button class="nav-sub-link${activeSub}" data-subarea="${escapeHtml(sub)}" data-parent-area="${escapeHtml(area)}" type="button"><span class="name">${escapeHtml(sub)}</span><span class="count">(${subCount})</span></button>`;
          })
          .join("");
        return `<div class="nav-pri${activeArea}${expandedClass}"><button class="nav-pri-head" data-nav-area="${escapeHtml(area)}" type="button"><span class="nav-arrow">▶</span><span class="name">${escapeHtml(area)}</span><span class="count">${count}</span></button><div class="nav-sub-list">${subs}</div></div>`;
      })
      .join("") || '<span class="muted">暂无方向</span>';
  }

  function searchBlob(paper) {
    const analysis = paper.analysis || {};
    return normalize([
      paper.title,
      paper.abstract,
      (paper.authors || []).join(" "),
      analysis.tldr,
      analysis.problem,
      analysis.method,
      paperArea(paper),
      paperSubarea(paper),
      ((analysis.tags || []).join(" ")),
    ].join(" "));
  }

  function filteredPapers() {
    let papers = state.papers;

    if (state.area) {
      papers = papers.filter((p) => paperArea(p) === state.area);
    }
    if (state.subarea) {
      papers = papers.filter((p) => paperSubarea(p) === state.subarea);
    }
    if (state.priority) {
      papers = papers.filter((p) => paperPriority(p) === state.priority);
    }
    if (state.tag) {
      papers = papers.filter((p) => ((p.analysis || {}).tags || []).includes(state.tag));
    }
    if (state.query) {
      const q = normalize(state.query);
      papers = papers.filter((p) => searchBlob(p).includes(q));
    }

    return papers;
  }

  function list(values) {
    if (values == null) return '<span class="muted">暂无</span>';
    if (!Array.isArray(values)) {
      // Handle string or other types defensively
      const text = String(values).trim();
      return text ? `<ul><li>${escapeHtml(text)}</li></ul>` : '<span class="muted">暂无</span>';
    }
    if (!values.length) return '<span class="muted">暂无</span>';
    return `<ul>${values.map((value) => `<li>${escapeHtml(value)}</li>`).join("")}</ul>`;
  }

  function paperUrl(paper, type) {
    const arxivId = String(paper.arxiv_id || paper.id || "").trim();
    if (type === "pdf") return paper.pdf_url || (arxivId ? `https://arxiv.org/pdf/${arxivId}` : "");
    if (type === "source") return arxivId ? `https://arxiv.org/e-print/${arxivId}` : "";
    return paper.entry_url || (arxivId ? `https://arxiv.org/abs/${arxivId}` : "");
  }

  function analysisText(analysis) {
    const parts = [
      ["TL;DR", analysis.tldr || analysis.one_sentence_summary],
      ["研究动机", analysis.research_motivation],
      ["解决问题", analysis.problem],
      ["主要方法", analysis.method],
      ["实验结果", analysis.experiments],
    ].filter(([, value]) => value);
    if (Array.isArray(analysis.contributions) && analysis.contributions.length) {
      parts.push(["主要贡献", analysis.contributions.join("; ")]);
    }
    if (Array.isArray(analysis.limitations) && analysis.limitations.length) {
      parts.push(["方法局限", analysis.limitations.join("; ")]);
    }
    return parts.map(([label, value]) => `- ${label}: ${value}`).join("\n");
  }

  function paperContext(paper) {
    const analysis = paper.analysis || {};
    const authors = (paper.authors || []).join(", ") || "Unknown";
    return [
      `Title: ${paper.title || ""}`,
      `Authors: ${authors}`,
      `arXiv ID: ${paper.arxiv_id || ""}`,
      `Primary category: ${paper.display_category || paper.primary_category || ""}`,
      `arXiv page: ${paperUrl(paper, "abs")}`,
      `PDF: ${paperUrl(paper, "pdf")}`,
      `Source: ${paperUrl(paper, "source")}`,
      "",
      "Abstract:",
      paper.abstract || "",
      "",
      "Existing Chinese digest from the site:",
      analysisText(analysis) || "暂无站内分析。",
    ].join("\n");
  }

  function buildChatPrompt(paper) {
    return [
      "请作为一名严谨的 AI/ML 论文阅读助手，帮我详细分析下面这篇 arXiv 论文。",
      "",
      "目标：不要只复述摘要。请尽可能阅读论文正文、方法、实验、图表和附录，然后用中文给出深入解读。",
      "",
      "请输出：",
      "1. 论文要解决的核心问题，以及这个问题为什么重要。",
      "2. 方法的主要思想、关键模块、训练/推理流程和必要公式解释。",
      "3. 与已有工作的差异，尤其是本文真正的新意在哪里。",
      "4. 实验设置、数据集、baseline、指标和主要结果。",
      "5. 重要图表逐个解释：图/表说明了什么，支撑了哪个结论。",
      "6. 方法的局限、潜在风险和可能失败场景。",
      "7. 如果我要复现或继续做这个方向，应该优先看哪些细节。",
      "",
      "如果你无法直接访问链接，请先说明限制，然后基于下面的标题、摘要和已有导读分析；如果可以访问 PDF，请以 PDF 正文为准。",
      "",
      "论文信息：",
      paperContext(paper),
    ].join("\n");
  }

  function buildAgentPrompt(paper) {
    return [
      "你是一个本地 AI research/coding agent。请基于下面这篇 arXiv 论文生成一份详细中文报告，并同时产出 Markdown 和 HTML 两种格式。",
      "",
      "任务要求：",
      "1. 从 arXiv 下载 LaTeX 源码：使用 Source 链接，或访问 https://arxiv.org/e-print/{arxiv_id}。",
      "2. 解压源码后，识别主要正文 .tex 文件、章节文件、参考文献文件和图像资源。优先阅读正文相关 .tex，必要时结合 figure/table caption 和图片文件。",
      "3. 下载论文 PDF，并将 PDF 页面转换为 PNG 图像，建议保存到 assets/pdf-pages/，文件名按页码排序，例如 page-001.png。",
      "4. 从源码和 PDF 中抽取并理解论文正文、方法、实验、消融、图表和局限，而不是只依赖摘要。",
      "5. 生成一份详细中文 Markdown 报告，建议文件名为 report.md。报告中需要插入关键 PNG 页面截图和源码中的重要图像，使用相对路径引用。",
      "6. 生成同内容的 HTML 报告，建议文件名为 report.html。HTML 应该可直接打开阅读，结构清晰，包含标题、目录、分节、表格，并内嵌/引用同一批 PNG 图像。",
      "",
      "报告至少包含：",
      "- 论文基本信息：标题、作者、arXiv ID、链接、分类。",
      "- 一句话结论和适合谁读。",
      "- 研究背景与问题定义。",
      "- 方法详解：核心假设、模型/算法结构、训练目标、推理流程、关键公式。",
      "- 图表解读：重要 figure/table 的作用、含义和对应结论；每个关键图表附近都应插入对应 PNG 图像。",
      "- PDF 页面证据：对方法、实验、结论等关键页面插入 PDF 转换得到的 PNG 截图，并解释这些页面支撑了哪些判断。",
      "- 实验设置：数据集、baseline、指标、实现细节。",
      "- 主要结果与消融结论。",
      "- 创新点、局限性、可复现风险和后续研究建议。",
      "- 附录：你实际读取到的关键源码文件列表、源码图像文件列表、PDF 转 PNG 文件列表。",
      "",
      "执行时请创建一个干净的工作目录，保留下载的源码、PDF、转换后的 PNG 图像和生成的两个报告。遇到源码缺失、PDF 转换失败、编译不完整或图像格式特殊时，请在报告中说明。",
      "",
      "论文信息：",
      paperContext(paper),
    ].join("\n").replaceAll("{arxiv_id}", paper.arxiv_id || "");
  }

  function paperActions(paper) {
    return `
      <button class="copy-prompt-btn" data-copy-prompt="chat" data-arxiv-id="${escapeHtml(paper.arxiv_id)}" type="button" title="复制适合 ChatGPT 深度分析论文的 Prompt">Chat</button>
      <button class="copy-prompt-btn" data-copy-prompt="agent" data-arxiv-id="${escapeHtml(paper.arxiv_id)}" type="button" title="复制适合 Claude Code 下载源码并生成报告的任务">Agent</button>`;
  }

  function sourceBadge(paper) {
    return `<span class="source-badge">${escapeHtml(paper.display_category || paper.primary_category)}</span>`;
  }

  function tagRow(tags) {
    return tags ? `<div class="paper-tag-line">${tags}</div>` : "";
  }

  async function writeClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
      try {
        await navigator.clipboard.writeText(text);
        return;
      } catch (error) {
        // Fall back for browsers that expose Clipboard API but deny the write.
      }
    }
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.select();
    const copied = document.execCommand("copy");
    textarea.remove();
    if (!copied) throw new Error("Copy command failed");
  }

  async function copyPaperPrompt(button) {
    const paper = state.papers.find((item) => String(item.arxiv_id || "") === String(button.dataset.arxivId || ""));
    if (!paper) return;
    const originalText = button.textContent;
    const prompt = button.dataset.copyPrompt === "agent" ? buildAgentPrompt(paper) : buildChatPrompt(paper);
    try {
      await writeClipboard(prompt);
      button.textContent = "已复制";
      button.classList.add("copied");
    } catch (error) {
      button.textContent = "复制失败";
      button.classList.add("copy-error");
    }
    window.setTimeout(() => {
      button.textContent = originalText;
      button.classList.remove("copied", "copy-error");
    }, 1500);
  }

  function paperCard(paper) {
    const analysis = paper.analysis || {};
    const priority = paperPriority(paper);
    const title = escapeHtml(paper.title || "");
    const authors = (paper.authors || []).slice(0, 8).join(", ");
    const moreAuthors = (paper.authors || []).length > 8 ? " et al." : "";
    const tags = (analysis.tags || []).map((tag) => `<button class="hash-tag" data-tag="${escapeHtml(tag)}" type="button">#${escapeHtml(tag)}</button>`).join("");

    // Unanalyzed papers: show abstract only, no analysis grid
    if (paperArea(paper) === "未分析") {
      return `<article class="paper-card">
        <h3 class="paper-title"><a href="${escapeHtml(paper.entry_url)}" target="_blank" rel="noopener">${title}</a></h3>
        <div class="paper-meta-line">
          <span class="priority-pill priority-unknown">未分析</span>
          ${sourceBadge(paper)}
          <a class="paper-id" href="${escapeHtml(paper.entry_url)}" target="_blank" rel="noopener">${escapeHtml(paper.arxiv_id)}</a>
          ${paperActions(paper)}
        </div>
        ${tagRow(tags)}
        <div class="paper-authors">${escapeHtml(authors)}${moreAuthors}</div>
        <div class="paper-abstract">${escapeHtml(paper.abstract)}</div>
      </article>`;
    }

    // Analyzed papers: show full analysis grid
    return `<article class="paper-card">
      <h3 class="paper-title"><a href="${escapeHtml(paper.entry_url)}" target="_blank" rel="noopener">${title}</a></h3>
      <div class="paper-meta-line">
        <button class="topic-badge" data-area="${escapeHtml(paperArea(paper))}" type="button">${escapeHtml(paperArea(paper))}</button>
        <button class="topic-badge subarea-badge" data-subarea="${escapeHtml(paperSubarea(paper))}" data-parent-area="${escapeHtml(paperArea(paper))}" type="button">${escapeHtml(paperSubarea(paper))}</button>
        <span class="priority-pill priority-${escapeHtml(priority)}">${escapeHtml(priority)}</span>
        ${sourceBadge(paper)}
        <a class="paper-id" href="${escapeHtml(paper.entry_url)}" target="_blank" rel="noopener">${escapeHtml(paper.arxiv_id)}</a>
        ${paperActions(paper)}
      </div>
      ${tagRow(tags)}
      <div class="paper-authors">${escapeHtml(authors)}${moreAuthors}</div>
      <div class="paper-tldr"><b>TL;DR:</b> ${escapeHtml(analysis.tldr || analysis.one_sentence_summary || "暂无中文导读。")}</div>
      <div class="analysis-grid">
        <div class="analysis-row"><div class="analysis-label"><span>🎯</span>研究动机</div><div class="analysis-content"><p>${escapeHtml(analysis.research_motivation || "暂无")}</p></div></div>
        <div class="analysis-row"><div class="analysis-label"><span>❓</span>解决问题</div><div class="analysis-content"><p>${escapeHtml(analysis.problem || "暂无")}</p></div></div>
        <div class="analysis-row"><div class="analysis-label"><span></span>现象分析</div><div class="analysis-content"><p>${escapeHtml(analysis.phenomenon_analysis || analysis.phenomena || "摘要未提供明确现象分析。")}</p></div></div>
        <div class="analysis-row"><div class="analysis-label"><span>🛠️</span>主要方法</div><div class="analysis-content"><p>${escapeHtml(analysis.method || "暂无")}</p></div></div>
        <div class="analysis-row"><div class="analysis-label"><span></span>实验结果</div><div class="analysis-content"><p>${escapeHtml(analysis.experiments || "摘要未提供具体实验结果")}</p></div></div>
        <div class="analysis-row"><div class="analysis-label"><span>⭐</span>主要贡献</div><div class="analysis-content">${list(analysis.contributions)}</div></div>
        <div class="analysis-row"><div class="analysis-label"><span>⚠️</span>方法局限</div><div class="analysis-content">${list(analysis.limitations)}</div></div>
      </div>
      <details class="abstract-block"><summary>查看完整摘要 (Abstract)</summary><p>${escapeHtml(paper.abstract)}</p></details>
    </article>`;
  }

  function groupedPapersHtml(papers, startOffset, endOffset) {
    const areaMap = new Map();
    for (const paper of papers) {
      const area = paperArea(paper);
      const sub = paperSubarea(paper);
      if (!areaMap.has(area)) areaMap.set(area, new Map());
      const subMap = areaMap.get(area);
      if (!subMap.has(sub)) subMap.set(sub, []);
      subMap.get(sub).push(paper);
    }

    // Sort areas: "未分析" always last, others by count descending
    const sortedAreas = [...areaMap.entries()].sort((a, b) => {
      const aIsUn = a[0] === "未分析";
      const bIsUn = b[0] === "未分析";
      if (aIsUn !== bIsUn) return aIsUn ? 1 : -1;
      const ac = [...a[1].values()].reduce((sum, items) => sum + items.length, 0);
      const bc = [...b[1].values()].reduce((sum, items) => sum + items.length, 0);
      return bc - ac || a[0].localeCompare(b[0], "zh-Hans-CN");
    });

    // Flatten into a single ordered list for pagination
    const flatOrdered = [];
    for (const [, subMap] of sortedAreas) {
      for (const [, items] of [...subMap.entries()].sort(
        (a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0], "zh-Hans-CN")
      )) {
        flatOrdered.push(...sortPapers(items));
      }
    }

    // Apply pagination slice
    const page = flatOrdered.slice(startOffset, endOffset);

    // Re-group the paginated slice for display
    const pageAreaMap = new Map();
    for (const paper of page) {
      const area = paperArea(paper);
      const sub = paperSubarea(paper);
      if (!pageAreaMap.has(area)) pageAreaMap.set(area, new Map());
      const subMap = pageAreaMap.get(area);
      if (!subMap.has(sub)) subMap.set(sub, []);
      subMap.get(sub).push(paper);
    }

    // Build HTML using the original sorted area order, but only for areas present in page
    return sortedAreas
      .filter(([area]) => pageAreaMap.has(area))
      .map(([area]) => {
        const subMap = pageAreaMap.get(area);
        const areaCount = subMap.size; // number of subareas on this page
        const pageSubEntries = [...subMap.entries()].sort(
          (a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0], "zh-Hans-CN")
        );
        const subSections = pageSubEntries
          .map(([sub, items]) => `
            <section class="sub-sec">
              <h3 class="sub-title">${escapeHtml(sub)} <small>${items.length} 篇</small></h3>
              <div class="paper-list">${items.map(paperCard).join("")}</div>
            </section>
          `)
          .join("");
        return `
          <section class="paper-section pri-sec" data-section>
            <h2 class="group-title">${escapeHtml(area)} <small>${areaCount} 个细分</small></h2>
            ${subSections}
          </section>
        `;
      })
      .join("");
  }

  function renderPapers() {
    const papers = filteredPapers();
    const total = papers.length;
    const startOffset = state.page * PAGE_SIZE;
    const endOffset = Math.min(startOffset + PAGE_SIZE, total);
    const start = total > 0 ? startOffset + 1 : 0;
    const end = Math.min((state.page + 1) * PAGE_SIZE, total);
    const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    const pagination = total > PAGE_SIZE
      ? `<div class="pagination-wrap">
          <button class="filter-chip" data-page-prev type="button"${state.page <= 0 ? " disabled" : ""}>上一页</button>
          <span class="page-indicator">${state.page + 1} / ${totalPages}</span>
          <button class="filter-chip" data-page-next type="button"${state.page >= totalPages - 1 ? " disabled" : ""}>下一页</button>
        </div>`
      : "";
    els.paperList.innerHTML = groupedPapersHtml(papers, startOffset, endOffset) + pagination;
    els.visibleCount.textContent = `${start}-${end}`;
    els.paperTotalInline.textContent = String(state.total);
    els.totalCount.textContent = String(state.total);
    els.heroTotal.textContent = String(state.total);
    if (els.clear) els.clear.innerHTML = `📚 全部 ${state.total} 篇`;
    if (els.clearTop) els.clearTop.classList.toggle("active", !state.priority && !state.tag && !state.area && !state.subarea && !state.query);
    if (els.heroHighCount) els.heroHighCount.textContent = String((state.facetData?.priorities || {}).high || 0);
    if (els.heroHigh) els.heroHigh.classList.toggle("active", state.priority === "high");
    els.noResults.classList.toggle("hidden", papers.length !== 0 || state.total === 0);
    els.loading.classList.add("hidden");
    updateFilterText();
    renderFacets(state.facetData || state.papers);
  }

  function updateFilterText() {
    const parts = [];
    if (state.query) parts.push(`search: ${state.query}`);
    if (state.priority) parts.push(`priority: ${state.priority}`);
    if (state.tag) parts.push(`tag: ${state.tag}`);
    if (state.area) parts.push(`area: ${state.area}`);
    if (state.subarea) parts.push(`subarea: ${state.subareaParent ? state.subareaParent + " · " : ""}${state.subarea}`);
    els.activeFilters.textContent = parts.length ? `· ${parts.join(" · ")}` : "";
  }

  function updateBackToTop() {
    const contentScrolled = els.content?.scrollTop || 0;
    const pageScrolled = window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0;
    const scrolled = Math.max(contentScrolled, pageScrolled);
    if (els.backToTop) els.backToTop.classList.toggle("visible", scrolled > 200);
  }

  function scrollBackToTop() {
    els.content?.scrollTo({ top: 0, behavior: "smooth" });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  // All data from Worker API
  function pageCacheKey(date) {
    const params = new URLSearchParams({ date });
    return params.toString();
  }

  async function fetchFromWorker(date, signal) {
    const url = `${WORKER_URL}/api/papers?date=${date}`;
    if (state.paperCache.has(url)) return state.paperCache.get(url);
    if (state.paperRequests.has(url)) return state.paperRequests.get(url);
    const request = fetch(url, { signal })
      .then(async (res) => {
        if (!res.ok) return { papers: [], total: 0 };
        const data = await res.json();
        const papers = Array.isArray(data) ? data : data.papers || [];
        state.paperCache.set(url, papers);
        return papers;
      })
      .finally(() => {
        state.paperRequests.delete(url);
      });
    state.paperRequests.set(url, request);
    return request;
  }

  function prefetchDate(date) {
    if (!date || state.date === date) return;
    fetchFromWorker(date).catch(() => {});
  }

  async function fetchFacets(date) {
    if (state.facetCache.has(date)) return state.facetCache.get(date);
    const res = await fetch(`${WORKER_URL}/api/facets?date=${date}`);
    if (!res.ok) return null;
    const data = await res.json();
    state.facetCache.set(date, data);
    return data;
  }

  function resetFilters() {
    state.query = "";
    state.priority = "";
    state.tag = "";
    state.area = "";
    state.subarea = "";
    state.subareaParent = "";
    state.expandedAreas.clear();
    if (els.search) els.search.value = "";
  }

  async function loadCurrentPage() {
    if (state.activeFetch) state.activeFetch.abort();
    const controller = new AbortController();
    state.activeFetch = controller;
    state.papers = [];
    els.paperList.innerHTML = "";
    els.loading.classList.remove("hidden");
    try {
      const papers = await fetchFromWorker(state.date, controller.signal);
      state.papers = papers;
      state.total = papers.length;
    } catch (error) {
      if (error.name === "AbortError") return;
      throw error;
    }
    if (state.activeFetch !== controller) return;
    state.activeFetch = null;
    // Sync date index count with actual paper count (fixes stale /api/dates cache)
    const entry = entryForDate(state.date);
    if (entry && entry.count !== state.total) {
      entry.count = state.total;
    }
    renderDates();
    updateUrl(state.date);
    renderPapers();
  }

  async function selectDate(date) {
    const entry = entryForDate(date);
    if (!entry) return;
    state.date = date;
    state.calendarMonth = date.slice(0, 7);
    state.page = 0;
    state.total = 0;
    resetFilters();
    els.currentDateLabel.textContent = `📅 ${date}`;
    state.facetData = await fetchFacets(date);
    await loadCurrentPage();
  }

  function bindEvents() {
    els.search?.addEventListener("input", (event) => {
      state.query = event.target.value;
      state.page = 0;
      clearTimeout(state.searchTimer);
      state.searchTimer = setTimeout(() => renderPapers(), 250);
    });
    els.clear?.addEventListener("click", clearFilters);
    els.clearTop?.addEventListener("click", clearFilters);
    els.dateNav?.addEventListener("click", (event) => {
      const prev = event.target.closest("[data-calendar-prev]");
      const next = event.target.closest("[data-calendar-next]");
      if (prev && !prev.disabled) {
        shiftCalendarMonth(-1);
        return;
      }
      if (next && !next.disabled) {
        shiftCalendarMonth(1);
        return;
      }
      const button = event.target.closest("[data-date]");
      if (button) {
        event.preventDefault();
        selectDate(button.dataset.date);
      }
    });
    els.dateNav?.addEventListener("pointerover", (event) => {
      const button = event.target.closest("[data-date]");
      if (button) prefetchDate(button.dataset.date);
    });
    els.backToTop?.addEventListener("click", scrollBackToTop);
    document.addEventListener("click", (event) => {
      const copyButton = event.target.closest("[data-copy-prompt]");
      if (copyButton) {
        copyPaperPrompt(copyButton);
        return;
      }
      const priority = event.target.closest("[data-priority]");
      const tag = event.target.closest("[data-tag]");
      const navArea = event.target.closest("[data-nav-area]");
      const area = event.target.closest("[data-area]");
      const subarea = event.target.closest("[data-subarea]");
      if (navArea) {
        const areaName = navArea.dataset.navArea || "";
        if (state.expandedAreas.has(areaName)) {
          state.expandedAreas.delete(areaName);
        } else if (areaName) {
          state.expandedAreas.add(areaName);
        }
        renderFacets(state.facetData || state.papers);
        return;
      }
      if (priority) state.priority = state.priority === priority.dataset.priority ? "" : priority.dataset.priority;
      if (tag) state.tag = state.tag === tag.dataset.tag ? "" : tag.dataset.tag;
      if (area) {
        state.area = state.area === area.dataset.area ? "" : area.dataset.area;
        if (state.area) state.expandedAreas.add(state.area);
        state.subarea = "";
        state.subareaParent = "";
      }
      if (subarea) {
        const parent = subarea.dataset.parentArea || "";
        if (state.subarea === subarea.dataset.subarea && state.subareaParent === parent) {
          state.subarea = "";
          state.subareaParent = "";
        } else {
          state.subarea = subarea.dataset.subarea;
          state.subareaParent = parent;
          if (parent) state.expandedAreas.add(parent);
        }
      }
      const prevPage = event.target.closest("[data-page-prev]");
      const nextPage = event.target.closest("[data-page-next]");
      if (prevPage && state.page > 0) {
        state.page -= 1;
        renderPapers();
        scrollBackToTop();
        return;
      }
      if (nextPage && (state.page + 1) * PAGE_SIZE < filteredPapers().length) {
        state.page += 1;
        renderPapers();
        scrollBackToTop();
        return;
      }
      if (priority || tag || area || subarea) {
        state.page = 0;
        renderPapers();
        scrollBackToTop();
      }
      if (nextPage && (state.page + 1) * PAGE_SIZE < filteredPapers().length) {
        state.page += 1;
        renderPapers();
        scrollBackToTop();
        return;
      }
      if (priority || tag || area || subarea) {
        state.page = 0;
        renderPapers();
        scrollBackToTop();
      }
      if (nextPage && (state.page + 1) * PAGE_SIZE < filteredPapers().length) {
        state.page += 1;
        renderPapers();
        scrollBackToTop();
        return;
      }
      if (priority || tag || area || subarea) {
        state.page = 0;
        renderPapers();
        scrollBackToTop();
      }
      if (nextPage && (state.page + 1) * PAGE_SIZE < filteredPapers().length) {
        state.page += 1;
        renderPapers();
        scrollBackToTop();
        return;
      }
      if (priority || tag || area || subarea) {
        state.page = 0;
        renderPapers();
        scrollBackToTop();
      }
      if (nextPage && (state.page + 1) * PAGE_SIZE < filteredPapers().length) {
        state.page += 1;
        renderPapers();
        scrollBackToTop();
        return;
      }
      if (priority || tag || area || subarea) {
        state.page = 0;
        renderPapers();
        scrollBackToTop();
      }
      if (nextPage && (state.page + 1) * PAGE_SIZE < filteredPapers().length) {
        state.page += 1;
        renderPapers();
        scrollBackToTop();
        return;
      }
      if (priority || tag || area || subarea) {
        state.page = 0;
        renderPapers();
        scrollBackToTop();
      }
    });
  }

  async function init() {
    bindEvents();
    // Date index comes from Worker/D1 so GitHub Actions never need to commit generated JSON.
    const apiDates = await fetch(`${WORKER_URL}/api/dates`);
    if (!apiDates.ok) {
      els.loading.textContent = "无法连接数据源，请检查网络。";
      return;
    }
    state.dateIndex = await apiDates.json();
    renderDates();
    els.content?.addEventListener("scroll", updateBackToTop);
    window.addEventListener("scroll", updateBackToTop);
    updateBackToTop();
    const requestedDate = new URLSearchParams(window.location.search).get("date");
    const initialDate = entryForDate(requestedDate) ? requestedDate : state.dateIndex.latest;
    await selectDate(initialDate);
  }

  init().catch((error) => {
    if (error.name === "AbortError") return;
    els.loading.textContent = error.message || "数据加载失败。";
  });
})();
