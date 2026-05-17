(function () {
  // API base — change to your Worker URL in production if not same-origin
  const API_BASE = typeof window.API_BASE_URL !== "undefined" ? window.API_BASE_URL : "";

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
    expandedAreas: new Set(),
    calendarMonth: "",
    renderJob: 0,
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
    content: document.querySelector(".content"),
  };

  function escapeHtml(value) {
    return String(value || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function normalize(value) { return String(value || "").toLowerCase().trim(); }
  function normalizeDateEntry(item) {
    return { ...item, month: item.month || String(item.date || "").slice(0, 7) };
  }
  function dateEntries() { return ((state.dateIndex && state.dateIndex.dates) || []).map(normalizeDateEntry); }
  function entryForDate(date) { return dateEntries().find((item) => item.date === date); }
  function priorityRank(priority) { return { high: 0, medium: 1, low: 2 }[priority] ?? 3; }
  function paperTime(paper) { return Date.parse(paper.updated || paper.published || "") || 0; }
  function paperPriority(paper) { return normalize((paper.analysis || {}).reading_priority) || "unknown"; }
  function hasAnalysis(paper) { return paper.has_analysis !== false && !!paper.analysis; }
  function paperArea(paper) { return hasAnalysis(paper) ? ((paper.analysis || {}).primary_area || "其他 ML 主题") : "未分析"; }
  function paperSubarea(paper) { const a = paper.analysis || {}; return a.category || a.sub_area || "其他"; }

  function parseList(value) {
    if (Array.isArray(value)) return value;
    if (!value) return [];
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [String(value)];
    }
  }

  function normalizePaper(paper) {
    if (paper.has_analysis === false || paper.analysis === null) {
      return {
        ...paper,
        authors: parseList(paper.authors),
        categories: parseList(paper.categories),
        analysis: null,
        has_analysis: false,
      };
    }
    const analysis = paper.analysis || paper;
    return {
      ...paper,
      authors: parseList(paper.authors),
      categories: parseList(paper.categories),
      analysis: {
        tldr: analysis.tldr || "",
        research_motivation: analysis.research_motivation || "",
        problem: analysis.problem || "",
        phenomenon_analysis: analysis.phenomenon_analysis || "",
        method: analysis.method || "",
        contributions: parseList(analysis.contributions),
        experiments: analysis.experiments || "",
        limitations: parseList(analysis.limitations),
        primary_area_en: analysis.primary_area_en || "",
        primary_area: analysis.primary_area || "",
        category: analysis.category || "",
        sub_area: analysis.sub_area || "",
        tags: parseList(analysis.tags),
        reading_priority: analysis.reading_priority || "unknown",
      },
      has_analysis: true,
    };
  }

  function sortPapers(papers) {
    return [...papers].sort((a, b) =>
      paperArea(a).localeCompare(paperArea(b), "zh-Hans-CN") ||
      paperSubarea(a).localeCompare(paperSubarea(b), "zh-Hans-CN") ||
      priorityRank(paperPriority(a)) - priorityRank(paperPriority(b)) ||
      paperTime(b) - paperTime(a) ||
      String(a.arxiv_id || "").localeCompare(String(b.arxiv_id || ""))
    );
  }

  async function apiFetch(path) {
    const url = API_BASE ? `${API_BASE}${path}` : path;
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error(`API error ${response.status} for ${path}`);
    return response.json();
  }

  async function loadDateIndex() { return apiFetch("/api/dates"); }
  async function loadMonthPapers(month) { return apiFetch(`/api/papers?month=${month}`); }
  async function loadDatePapers(date) { return apiFetch(`/api/papers?date=${date}`); }

  function updateUrl(date) {
    const url = new URL(window.location.href);
    url.searchParams.set("date", date);
    window.history.replaceState({}, "", url);
  }

  function clearFilters() {
    state.query = ""; state.priority = ""; state.tag = ""; state.area = "";
    state.subarea = ""; state.subareaParent = ""; state.expandedAreas.clear();
    if (els.search) els.search.value = "";
    renderPapers();
  }

  function facetCounts(papers) {
    const priorities = { high: 0, medium: 0, low: 0 };
    const tags = new Map(); const areas = new Map();
    for (const paper of papers) {
      const priority = paperPriority(paper);
      if (priority in priorities) priorities[priority] += 1;
      for (const tag of (paper.analysis || {}).tags || []) tags.set(tag, (tags.get(tag) || 0) + 1);
      const area = paperArea(paper); const sub = paperSubarea(paper);
      if (!areas.has(area)) areas.set(area, new Map());
      areas.get(area).set(sub, (areas.get(area).get(sub) || 0) + 1);
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
    for (let i = startDow - 1; i > 0; i--) cells.push({ day: prevLastDay.getDate() - i + 1, outside: true });
    for (let d = 1; d <= lastDay.getDate(); d++) {
      const dt = `${year}-${String(month).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      cells.push({ day: d, date: dt, count: dateCounts[dt] || 0 });
    }
    while (cells.length % 7 !== 0) cells.push({ day: cells.length % 7 === 0 ? 1 : cells[cells.length - 7].day + 1, outside: true });

    const headRow = `<div class="calendar-week calendar-head">${dayNames.map(n => `<b>${n}</b>`).join("")}</div>`;
    const weekRows = [];
    for (let i = 0; i < cells.length; i += 7) {
      const week = cells.slice(i, i + 7);
      const dayCells = week.map((item) => {
        if (item.outside) return `<span class="calendar-day outside disabled"><span>${item.day}</span></span>`;
        const classes = ["calendar-day"];
        if (item.date === activeDate) classes.push("active");
        if (item.count > 0) return `<a class="${classes.join(" ")}" href="?date=${escapeHtml(item.date)}" data-date="${escapeHtml(item.date)}" title="${escapeHtml(item.date)} · ${item.count} 篇"><span>${item.day}</span><em>${item.count}</em></a>`;
        classes.push("disabled");
        return `<span class="${classes.join(" ")}" title="${escapeHtml(item.date)}"><span>${item.day}</span></span>`;
      }).join("");
      weekRows.push(`<div class="calendar-week">${dayCells}</div>`);
    }
    return `<div class="calendar-month">${headRow}${weekRows.join("")}</div>`;
  }

  function renderDates() {
    const entries = dateEntries();
    els.dateCount.textContent = String(entries.filter(e => e.count > 0).length);
    const dateCounts = {};
    for (const item of entries) dateCounts[item.date] = item.count;
    const months = [...new Set(entries.filter(e => e.count > 0 && e.month).map(e => e.month))].sort();
    if (!months.length) { els.dateNav.innerHTML = '<span class="muted">暂无数据</span>'; return; }
    if (!state.calendarMonth || !months.includes(state.calendarMonth)) state.calendarMonth = state.date ? state.date.slice(0, 7) : months[months.length - 1];
    const monthIndex = months.indexOf(state.calendarMonth);
    const [year, monthNumber] = state.calendarMonth.split("-").map(Number);
    els.dateNav.innerHTML = `<div class="calendar-wrap"><div class="calendar-switcher"><button class="calendar-nav-btn" data-calendar-prev type="button"${monthIndex <= 0 ? " disabled" : ""}>‹</button><span>${state.calendarMonth}</span><button class="calendar-nav-btn" data-calendar-next type="button"${monthIndex >= months.length - 1 ? " disabled" : ""}>›</button></div>${buildCalendarMonth(year, monthNumber, dateCounts, state.date)}</div>`;
  }

  function shiftCalendarMonth(direction) {
    const months = [...new Set(dateEntries().filter(i => i.count > 0).map(i => i.month))].sort();
    const current = state.calendarMonth || (state.date ? state.date.slice(0, 7) : months[months.length - 1]);
    const next = months[months.indexOf(current) + direction];
    if (next) { state.calendarMonth = next; renderDates(); }
  }

  function renderFacets(papers) {
    const { priorities, tags, areas } = facetCounts(papers);
    els.priorityFilters.innerHTML = Object.entries(priorities).map(([name, count]) => `<button class="filter-chip${state.priority === name ? " active" : ""}" data-priority="${name}" type="button">${name} <b>${count}</b></button>`).join("");
    els.tagFilters.innerHTML = [...tags.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 20).map(([tag, count]) => `<button class="filter-chip${state.tag === tag ? " active" : ""}" data-tag="${escapeHtml(tag)}" type="button">#${escapeHtml(tag)} <b>${count}</b></button>`).join("") || '<span class="muted">暂无 tags</span>';
    els.topicNav.innerHTML = [...areas.entries()].sort((a, b) => {
      const ac = [...a[1].values()].reduce((s, v) => s + v, 0);
      const bc = [...b[1].values()].reduce((s, v) => s + v, 0);
      return bc - ac || a[0].localeCompare(b[0]);
    }).map(([area, subMap]) => {
      const count = [...subMap.values()].reduce((s, v) => s + v, 0);
      const expanded = state.expandedAreas.has(area) || state.area === area || state.subareaParent === area;
      const subs = [...subMap.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([sub, sc]) => {
        const activeSub = state.subareaParent === area && state.subarea === sub ? " active" : "";
        return `<button class="nav-sub-link${activeSub}" data-subarea="${escapeHtml(sub)}" data-parent-area="${escapeHtml(area)}" type="button"><span class="name">${escapeHtml(sub)}</span><span class="count">(${sc})</span></button>`;
      }).join("");
      return `<div class="nav-pri${state.area === area ? " active" : ""}${expanded ? " expanded" : ""}"><button class="nav-pri-head" data-nav-area="${escapeHtml(area)}" type="button"><span class="nav-arrow">▶</span><span class="name">${escapeHtml(area)}</span><span class="count">${count}</span></button><div class="nav-sub-list">${subs}</div></div>`;
    }).join("") || '<span class="muted">暂无方向</span>';
  }

  function searchBlob(paper) {
    const a = paper.analysis || {};
    return normalize([paper.title, paper.abstract, (paper.authors || []).join(" "), a.tldr, a.problem, a.method, paperArea(paper), paperSubarea(paper), ((a.tags || []).join(" "))].join(" "));
  }

  function filteredPapers() {
    const query = normalize(state.query);
    return state.papers.filter((paper) => {
      const tags = (paper.analysis || {}).tags || [];
      return (!query || searchBlob(paper).includes(query)) &&
        (!state.priority || paperPriority(paper) === state.priority) &&
        (!state.tag || tags.includes(state.tag)) &&
        (!state.area || paperArea(paper) === state.area) &&
        (!state.subarea || (paperArea(paper) === state.subareaParent && paperSubarea(paper) === state.subarea));
    });
  }

  function list(values) {
    if (!values || !values.length) return '<span class="muted">暂无</span>';
    return `<ul>${values.map(v => `<li>${escapeHtml(v)}</li>`).join("")}</ul>`;
  }

  function paperCard(paper) {
    const analysis = paper.analysis || {};
    const priority = paperPriority(paper);
    const analyzed = hasAnalysis(paper);
    const tags = analyzed ? (analysis.tags || []).map(t => `<button class="hash-tag" data-tag="${escapeHtml(t)}" type="button">#${escapeHtml(t)}</button>`).join("") : "";
    const authors = (paper.authors || []).slice(0, 8).join(", ");
    const more = (paper.authors || []).length > 8 ? " et al." : "";
    const metaHtml = analyzed
      ? `<button class="topic-badge" data-area="${escapeHtml(paperArea(paper))}" type="button">${escapeHtml(paperArea(paper))}</button><button class="topic-badge subarea-badge" data-subarea="${escapeHtml(paperSubarea(paper))}" data-parent-area="${escapeHtml(paperArea(paper))}" type="button">${escapeHtml(paperSubarea(paper))}</button><span class="priority-pill priority-${escapeHtml(priority)}">${escapeHtml(priority)}</span><span class="paper-id">${escapeHtml(paper.arxiv_id)}</span>${tags}`
      : `<span class="paper-id">${escapeHtml(paper.arxiv_id)}</span>`;
    const analysisHtml = analyzed
      ? `<div class="paper-tldr"><b>TL;DR:</b> ${escapeHtml(analysis.tldr || "暂无中文导读。")}</div><div class="analysis-grid"><div class="analysis-row"><div class="analysis-label"><span>🎯</span>研究动机</div><div class="analysis-content"><p>${escapeHtml(analysis.research_motivation || "暂无")}</p></div></div><div class="analysis-row"><div class="analysis-label"><span>❓</span>解决问题</div><div class="analysis-content"><p>${escapeHtml(analysis.problem || "暂无")}</p></div></div><div class="analysis-row"><div class="analysis-label"><span>🔎</span>现象分析</div><div class="analysis-content"><p>${escapeHtml(analysis.phenomenon_analysis || "摘要未提供明确现象分析。")}</p></div></div><div class="analysis-row"><div class="analysis-label"><span>🛠️</span>主要方法</div><div class="analysis-content"><p>${escapeHtml(analysis.method || "暂无")}</p></div></div><div class="analysis-row"><div class="analysis-label"><span>📊</span>实验结果</div><div class="analysis-content"><p>${escapeHtml(analysis.experiments || "摘要未提供具体实验结果")}</p></div></div><div class="analysis-row"><div class="analysis-label"><span>⭐</span>主要贡献</div><div class="analysis-content">${list(analysis.contributions)}</div></div><div class="analysis-row"><div class="analysis-label"><span>⚠️</span>方法局限</div><div class="analysis-content">${list(analysis.limitations)}</div></div></div><details class="abstract-block"><summary>查看完整摘要 (Abstract)</summary><p>${escapeHtml(paper.abstract)}</p></details>`
      : `<details class="abstract-block" open><summary>Abstract</summary><p>${escapeHtml(paper.abstract)}</p></details>`;
    return `<article class="paper-card"><h3 class="paper-title"><a href="${escapeHtml(paper.entry_url)}" target="_blank" rel="noopener">${escapeHtml(paper.title)}</a></h3><div class="paper-meta-line">${metaHtml}</div><div class="paper-authors">${escapeHtml(authors)}${more}</div><div class="paper-links"><a href="${escapeHtml(paper.entry_url)}" target="_blank" rel="noopener">arXiv</a><a href="${escapeHtml(paper.pdf_url)}" target="_blank" rel="noopener">PDF</a><span>${escapeHtml(paper.primary_category)}</span></div>${analysisHtml}</article>`;
  }

  function groupedPapers(papers) {
    const areaMap = new Map();
    for (const paper of papers) {
      const area = paperArea(paper); const sub = paperSubarea(paper);
      if (!areaMap.has(area)) areaMap.set(area, new Map());
      if (!areaMap.get(area).has(sub)) areaMap.get(area).set(sub, []);
      areaMap.get(area).get(sub).push(paper);
    }
    return [...areaMap.entries()].sort((a, b) => {
      const ac = [...a[1].values()].reduce((s, items) => s + items.length, 0);
      const bc = [...b[1].values()].reduce((s, items) => s + items.length, 0);
      return bc - ac || a[0].localeCompare(b[0], "zh-Hans-CN");
    }).map(([area, subMap]) => {
      const areaCount = [...subMap.values()].reduce((s, items) => s + items.length, 0);
      const subs = [...subMap.entries()]
        .sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0], "zh-Hans-CN"))
        .map(([sub, items]) => ({ sub, items: sortPapers(items) }));
      return { area, areaCount, subs };
    });
  }

  function renderPapers() {
    const papers = sortPapers(filteredPapers());
    const job = ++state.renderJob;
    const groups = groupedPapers(papers);
    els.paperList.innerHTML = "";
    els.visibleCount.textContent = String(papers.length);
    els.paperTotalInline.textContent = String(state.papers.length);
    els.totalCount.textContent = String(state.papers.length);
    els.heroTotal.textContent = String(state.papers.length);
    if (els.clear) els.clear.innerHTML = `📚 全部 ${state.papers.length} 篇`;
    if (els.clearTop) els.clearTop.classList.toggle("active", !state.priority && !state.tag && !state.area && !state.subarea && !state.query);
    if (els.heroHighCount) els.heroHighCount.textContent = String(state.papers.filter(p => paperPriority(p) === "high").length);
    if (els.heroHigh) els.heroHigh.classList.toggle("active", state.priority === "high");
    els.noResults.classList.toggle("hidden", papers.length !== 0 || state.papers.length === 0);
    updateFilterText();
    renderFacets(state.papers);
    if (papers.length === 0) {
      els.loading.classList.add("hidden");
      return;
    }

    let groupIndex = 0;
    let subIndex = 0;
    let itemIndex = 0;
    let currentSection = null;
    let currentList = null;
    const batchSize = 24;

    function renderBatch() {
      if (job !== state.renderJob) return;
      let rendered = 0;
      while (rendered < batchSize && groupIndex < groups.length) {
        const group = groups[groupIndex];
        if (!currentSection) {
          els.paperList.insertAdjacentHTML("beforeend", `<section class="paper-section pri-sec" data-section><h2 class="group-title">${escapeHtml(group.area)} <small>${group.areaCount} 篇 · ${group.subs.length} 个细分</small></h2></section>`);
          currentSection = els.paperList.lastElementChild;
        }

        const sub = group.subs[subIndex];
        if (!currentList) {
          currentSection.insertAdjacentHTML("beforeend", `<section class="sub-sec"><h3 class="sub-title">${escapeHtml(sub.sub)} <small>${sub.items.length} 篇</small></h3><div class="paper-list"></div></section>`);
          currentList = currentSection.lastElementChild.querySelector(".paper-list");
        }

        const slice = sub.items.slice(itemIndex, itemIndex + batchSize - rendered);
        currentList.insertAdjacentHTML("beforeend", slice.map(paperCard).join(""));
        rendered += slice.length;
        itemIndex += slice.length;

        if (itemIndex >= sub.items.length) {
          subIndex += 1;
          itemIndex = 0;
          currentList = null;
        }
        if (subIndex >= group.subs.length) {
          groupIndex += 1;
          subIndex = 0;
          currentSection = null;
        }
      }
      els.loading.classList.add("hidden");
      if (groupIndex < groups.length) {
        window.setTimeout(renderBatch, 0);
      }
    }

    renderBatch();
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
    const scrolled = Math.max(els.content?.scrollTop || 0, window.scrollY || document.documentElement.scrollTop || 0);
    if (els.backToTop) els.backToTop.classList.toggle("visible", scrolled > 400);
  }

  function scrollBackToTop() { els.content?.scrollTo({ top: 0, behavior: "smooth" }); window.scrollTo({ top: 0, behavior: "smooth" }); }

  async function selectDate(date) {
    const entry = entryForDate(date);
    if (!entry) return;
    state.date = date;
    state.calendarMonth = date.slice(0, 7);
    els.loading.classList.remove("hidden");
    els.currentDateLabel.textContent = `📅 ${date}`;
    try {
      state.papers = (await loadDatePapers(date)).map(normalizePaper);
    } catch {
      const monthData = await loadMonthPapers(entry.month || date.slice(0, 7));
      state.papers = monthData.filter(p => p.source_date === date).map(normalizePaper);
    }
    clearFilters();
    renderDates();
    updateUrl(date);
  }

  function bindEvents() {
    els.search?.addEventListener("input", (event) => { state.query = event.target.value; renderPapers(); });
    els.clear?.addEventListener("click", clearFilters);
    els.clearTop?.addEventListener("click", clearFilters);
    els.dateNav?.addEventListener("click", (event) => {
      const prev = event.target.closest("[data-calendar-prev]");
      const next = event.target.closest("[data-calendar-next]");
      if (prev && !prev.disabled) { shiftCalendarMonth(-1); return; }
      if (next && !next.disabled) { shiftCalendarMonth(1); return; }
      const button = event.target.closest("[data-date]");
      if (button) { event.preventDefault(); selectDate(button.dataset.date); }
    });
    els.backToTop?.addEventListener("click", scrollBackToTop);
    document.addEventListener("click", (event) => {
      const priority = event.target.closest("[data-priority]");
      const tag = event.target.closest("[data-tag]");
      const navArea = event.target.closest("[data-nav-area]");
      const area = event.target.closest("[data-area]");
      const subarea = event.target.closest("[data-subarea]");
      if (navArea) {
        const name = navArea.dataset.navArea || "";
        if (state.expandedAreas.has(name)) state.expandedAreas.delete(name); else if (name) state.expandedAreas.add(name);
        renderFacets(state.papers); return;
      }
      if (priority) state.priority = state.priority === priority.dataset.priority ? "" : priority.dataset.priority;
      if (tag) state.tag = state.tag === tag.dataset.tag ? "" : tag.dataset.tag;
      if (area) { state.area = state.area === area.dataset.area ? "" : area.dataset.area; if (state.area) state.expandedAreas.add(state.area); state.subarea = ""; state.subareaParent = ""; }
      if (subarea) {
        const parent = subarea.dataset.parentArea || "";
        if (state.subarea === subarea.dataset.subarea && state.subareaParent === parent) { state.subarea = ""; state.subareaParent = ""; }
        else { state.subarea = subarea.dataset.subarea; state.subareaParent = parent; if (parent) state.expandedAreas.add(parent); }
      }
      if (priority || tag || area || subarea) renderPapers();
    });
  }

  async function init() {
    bindEvents();
    state.dateIndex = await loadDateIndex();
    renderDates();
    els.content?.addEventListener("scroll", updateBackToTop);
    window.addEventListener("scroll", updateBackToTop);
    updateBackToTop();
    const requestedDate = new URLSearchParams(window.location.search).get("date");
    const initialDate = entryForDate(requestedDate) ? requestedDate : state.dateIndex.latest;
    await selectDate(initialDate);
  }

  init().catch((error) => {
    els.loading.textContent = error.message || "数据加载失败。";
    els.loading.classList.remove("hidden");
  });
})();
