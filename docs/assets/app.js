(function () {
  const state = {
    query: "",
    priority: "",
    tag: "",
    category: "",
  };

  const searchInput = document.getElementById("searchInput");
  const clearButton = document.getElementById("clearFilters");
  const clearButtonTop = document.getElementById("clearFiltersTop");
  const visibleCount = document.getElementById("visibleCount");
  const noResults = document.getElementById("noResults");
  const activeFilters = document.getElementById("activeFilters");
  const cards = Array.from(document.querySelectorAll(".paper-card"));
  const sections = Array.from(document.querySelectorAll("[data-section]"));

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
  }

  function updateFilterText() {
    const parts = [];
    if (state.query) parts.push(`search: ${state.query}`);
    if (state.priority) parts.push(`priority: ${state.priority}`);
    if (state.tag) parts.push(`tag: ${state.tag}`);
    if (state.category) parts.push(`category: ${state.category}`);
    activeFilters.textContent = parts.length ? `· ${parts.join(" · ")}` : "";
  }

  function updateSectionVisibility() {
    sections.forEach((section) => {
      const visibleCards = section.querySelectorAll(".paper-card:not(.hidden)").length;
      section.classList.toggle("hidden", visibleCards === 0);
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
      const visible = matchesQuery && matchesPriority && matchesTag && matchesCategory;
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
    button.addEventListener("click", () => {
      state.category = state.category === button.dataset.filterCategory ? "" : button.dataset.filterCategory;
      applyFilters();
    });
  });

  function clearFilters() {
    state.query = "";
    state.priority = "";
    state.tag = "";
    state.category = "";
    if (searchInput) searchInput.value = "";
    applyFilters();
  }

  clearButton?.addEventListener("click", clearFilters);
  clearButtonTop?.addEventListener("click", clearFilters);

  applyFilters();
})();
