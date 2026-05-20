-- Migration number: 0002 	 2026-05-20T22:05:00.000Z

CREATE TABLE IF NOT EXISTS date_index (
    date TEXT PRIMARY KEY,
    month TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    analyzed_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_date_index_month ON date_index(month);
