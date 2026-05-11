(function () {
  const state = {
    query: "",
    priority: "",
    tag: "",
    category: "",
    area: "",
    subarea: "",
  };

  const searchInput = document.getElementById("searchInput");
  const clearButton = document.getElementById("clearFilters");
  const clearButtonTop = document.getElementById("clearFiltersTop");
  const visibleCount = document.getElementById("visibleCount");
  const noResults = document.getElementById("noResults");
  const activeFilters = document.getElementById("activeFilters");
  const cards = Array.from(document.querySelectorAll(".paper-card"));
  const sections = Array.from(document.querySelectorAll("[data-section]"));
  const subSections = Array.from(document.querySelectorAll(".sub-sec"));

  function normalize(value) {
    return (value || "").toString().toLowerCase().trim();
  }

  function setActiveButtons() {
    document.querySelectorAll("[data-filter-priority]").forEach((button) => {
      button.classList.toggle("active", button.dataset.filterPriority === state.priority);
    });
    document.querySelectorAll("[data-filter-tag]").forEach((button) => {
      button.classList.toggle("active", button.dataset.filterTag === state.tag);
    });
    document.querySelectorAll("[data-filter-category]").forEach((button) => {
      button.classList.toggle("active", button.dataset.filterCategory === state.category);
    });
    document.querySelectorAll("[data-filter-area]").forEach((button) => {
      button.classList.toggle("active", button.dataset.filterArea === state.area);
    });
    document.querySelectorAll("[data-filter-subarea]").forEach((button) => {
      button.classList.toggle("active", button.dataset.filterSubarea === state.subarea);
    });
  }

  function updateFilterText() {
    const parts = [];
    if (state.query) parts.push(`search: ${state.query}`);
    if (state.priority) parts.push(`priority: ${state.priority}`);
    if (state.tag) parts.push(`tag: ${state.tag}`);
    if (state.category) parts.push(`category: ${state.category}`);
    if (state.area) parts.push(`area: ${state.area}`);
    if (state.subarea) parts.push(`subarea: ${state.subarea}`);
    activeFilters.textContent = parts.length ? `· ${parts.join(" · ")}` : "";
  }

  function updateSectionVisibility() {
    subSections.forEach((section) => {
      const visibleCards = section.querySelectorAll(".paper-card:not(.hidden)").length;
      section.classList.toggle("hidden", visibleCards === 0);
    });
    sections.forEach((section) => {
      const visibleCards = section.querySelectorAll(".paper-card:not(.hidden)").length;
      section.classList.toggle("hidden", visibleCards === 0);
    });
    document.querySelectorAll(".nav-pri").forEach((nav) => {
      const area = nav.dataset.area || "";
      const visibleCards = cards.filter((card) => {
        return !card.classList.contains("hidden") && card.dataset.area === area;
      }).length;
      const count = nav.querySelector(".nav-pri-head .count");
      if (count) count.textContent = String(visibleCards);
      nav.classList.toggle("hidden", visibleCards === 0 && (state.query || state.priority || state.tag || state.category || state.area || state.subarea));
      if (state.query || state.priority || state.tag || state.category || state.area || state.subarea) {
        nav.classList.toggle("expanded", visibleCards > 0);
      }
    });
  }

  function applyFilters() {
    let count = 0;
    const query = normalize(state.query);

    cards.forEach((card) => {
      const searchBlob = normalize(card.dataset.search);
      const tags = (card.dataset.tags || "").split("|");
      const categories = (card.dataset.categories || "").split("|");
      const matchesQuery = !query || searchBlob.includes(query);
      const matchesPriority = !state.priority || card.dataset.priority === state.priority;
      const matchesTag = !state.tag || tags.includes(state.tag);
      const matchesCategory = !state.category || categories.includes(state.category);
      const matchesArea = !state.area || card.dataset.area === state.area;
      const matchesSubarea = !state.subarea || card.dataset.subarea === state.subarea;
      const visible = matchesQuery && matchesPriority && matchesTag && matchesCategory && matchesArea && matchesSubarea;
      card.classList.toggle("hidden", !visible);
      if (visible) count += 1;
    });

    visibleCount.textContent = String(count);
    noResults.classList.toggle("hidden", count !== 0 || cards.length === 0);
    updateSectionVisibility();
    setActiveButtons();
    updateFilterText();
  }

  if (searchInput) {
    searchInput.addEventListener("input", (event) => {
      state.query = event.target.value;
      applyFilters();
    });
  }

  document.querySelectorAll("[data-filter-priority]").forEach((button) => {
    button.addEventListener("click", () => {
      state.priority = state.priority === button.dataset.filterPriority ? "" : button.dataset.filterPriority;
      applyFilters();
    });
  });

  document.querySelectorAll("[data-filter-tag]").forEach((button) => {
    button.addEventListener("click", () => {
      state.tag = state.tag === button.dataset.filterTag ? "" : button.dataset.filterTag;
      applyFilters();
    });
  });

  document.querySelectorAll("[data-filter-category]").forEach((button) => {
    button.addEventListener("click", (event) => {
      state.category = state.category === button.dataset.filterCategory ? "" : button.dataset.filterCategory;
      applyFilters();
      const targetId = button.dataset.target;
      if (targetId) {
        event.stopPropagation();
        document.getElementById(targetId)?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  });

  document.querySelectorAll("[data-filter-area]").forEach((button) => {
    button.addEventListener("click", () => {
      state.area = state.area === button.dataset.filterArea ? "" : button.dataset.filterArea;
      state.subarea = "";
      applyFilters();
    });
  });

  document.querySelectorAll("[data-filter-subarea]").forEach((button) => {
    button.addEventListener("click", (event) => {
      state.subarea = state.subarea === button.dataset.filterSubarea ? "" : button.dataset.filterSubarea;
      applyFilters();
      const targetId = button.dataset.target;
      if (targetId) {
        event.stopPropagation();
        document.getElementById(targetId)?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  });

  document.querySelectorAll(".nav-pri-head").forEach((button) => {
    button.addEventListener("click", () => {
      button.closest(".nav-pri")?.classList.toggle("expanded");
    });
  });

  function clearFilters() {
    state.query = "";
    state.priority = "";
    state.tag = "";
    state.category = "";
    state.area = "";
    state.subarea = "";
    if (searchInput) searchInput.value = "";
    applyFilters();
  }

  clearButton?.addEventListener("click", clearFilters);
  clearButtonTop?.addEventListener("click", clearFilters);

  applyFilters();
})();
