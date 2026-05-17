-- Migration number: 0001 	 2026-05-16T16:03:28.900Z

CREATE TABLE IF NOT EXISTS papers (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'arxiv',
    title TEXT NOT NULL,
    authors TEXT,
    abstract TEXT,
    categories TEXT,
    primary_category TEXT,
    published TEXT,
    updated TEXT,
    entry_url TEXT,
    pdf_url TEXT,
    source_date TEXT NOT NULL,
    venue TEXT,
    year INTEGER,
    fetched_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS analyses (
    arxiv_id TEXT PRIMARY KEY,
    analysis_version TEXT NOT NULL,
    model TEXT,
    analyzed_at TEXT,
    tldr TEXT,
    research_motivation TEXT,
    problem TEXT,
    phenomenon_analysis TEXT,
    method TEXT,
    contributions TEXT,
    experiments TEXT,
    limitations TEXT,
    primary_area_en TEXT,
    primary_area TEXT,
    category TEXT,
    sub_area TEXT,
    tags TEXT,
    reading_priority TEXT,
    recommended_action TEXT,
    raw_response TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_papers_source_date ON papers(source_date);
CREATE INDEX IF NOT EXISTS idx_papers_source ON papers(source);
CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(year);
CREATE INDEX IF NOT EXISTS idx_analyses_priority ON analyses(reading_priority);
CREATE INDEX IF NOT EXISTS idx_analyses_area ON analyses(primary_area);
CREATE INDEX IF NOT EXISTS idx_analyses_category ON analyses(category);
