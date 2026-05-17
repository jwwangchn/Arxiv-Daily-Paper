# AGENTS.md

Project-level guidance for coding agents working in this repository.

## Project Overview

This repository builds a daily arXiv paper guide with AI-powered Chinese summaries. The pipeline fetches arXiv metadata, analyzes each paper with DeepSeek (title + abstract only), stores data in a **Cloudflare D1 database** (production) with local SQLite mirror (development), and serves a SPA frontend via GitHub Pages that reads from a Cloudflare Worker API.

**Architecture principle: database-first.** All data flows through D1/SQLite. JSONL files in `data/archive/` are kept for git tracking and backup but are not the primary data source for the running system.

Core stack:

- Python 3.11 for data pipeline scripts.
- Cloudflare D1 (serverless SQLite) for production data storage.
- SQLite (`data/archive/papers.db`) for local development, mirroring the D1 schema.
- Cloudflare Worker (Hono/TypeScript) as the API layer between frontend and D1.
- GitHub Pages serves the SPA frontend (`docs/`).
- No React/Vue/Next.js — plain HTML/CSS/JavaScript.

## Architecture

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  GitHub Actions   │────▶│  Cloudflare       │◀────│  SPA Frontend    │
│  (daily.yml)      │     │  Worker + D1      │     │  (docs/index)    │
│                   │     │                   │     │                   │
│  fetch_arxiv.py   │     │  GET /api/dates   │     │  app.js          │
│  analyze_*.py     │     │  GET /api/papers  │     │  All data via    │
│  export_to_worker │     │  POST /api/*      │     │  Worker API      │
└──────────────────┘     └──────────────────┘     └──────────────────┘
```

**Three data layers (kept in sync):**

| Layer | Location | Purpose |
|---|---|---|
| **Cloudflare D1** | Remote (`ac0b5b96-...`) | Production data store, queried by Worker API |
| **Local SQLite** | `data/archive/papers.db` | Local dev mirror of D1 schema |
| **JSONL archive** | `data/archive/*.jsonl` | Git-tracked backup, used for seeding and version control |

## Important Paths

- `config.yaml`: site title, arXiv categories (cs.CV/cs.AI/cs.CL/cs.LG), max papers, topic keywords.
- `scripts/fetch_arxiv.py`: arXiv metadata fetcher — writes to local SQLite + JSONL backup.
- `scripts/analyze_deepseek.py`: DeepSeek analysis entry point — delegates to `commands.analyze`.
- `scripts/export_to_worker.py`: syncs new local data to remote D1 via Worker API (with retry logic).
- `scripts/lib/db.py`: SQLite layer — mirrors D1 schema for local development.
- `scripts/lib/archive.py`: JSONL archive layer — append-only backup, not primary source.
- `scripts/lib/config.py`: config loading from `config.yaml`.
- `scripts/fetchers/`: multi-source fetch plugins (AAAI, ACL, CVF, OpenReview) — extensible base class.
- `scripts/commands/analyze.py`: DeepSeek analysis logic (called by analyze_deepseek.py).
- `scripts/commands/build.py`: SPA build — reads JSONL, writes `docs/index.html` + `docs/data/`.
- `scripts/commands/fetch.py`: legacy fetch commands.
- `scripts/commands/daily.py`: legacy full pipeline (calls fetch → analyze → build).
- `worker/src/index.ts`: Cloudflare Worker (Hono API) — the only API the frontend calls.
- `migrations/0001_create_papers_table.sql`: D1 schema definition (papers + analyses tables).
- `wrangler.toml`: Cloudflare deployment config with D1 binding.
- `dev-server.js`: local dev server — serves `docs/` and proxies `/api/*` to local Worker.
- `data/archive/papers.jsonl` + `analyses.jsonl`: JSONL backup, git-tracked.
- `data/archive/papers.db`: local SQLite database.
- `data/raw/` and `data/analyzed/`: deprecated, do not use.
- `docs/assets/app.js`: SPA frontend — all data loaded from Worker API.
- `.github/workflows/daily.yml`: scheduled daily pipeline.

## Data Flow

### Production (GitHub Actions)

1. `fetch_arxiv.py` → fetches arXiv metadata, writes to local SQLite + JSONL backup
2. `analyze_deepseek.py` → calls DeepSeek API, writes analysis to local SQLite + JSONL backup
3. `export_to_worker.py` → reads local SQLite, pushes new records to remote D1 via Worker API
4. Git commits JSONL changes for backup/versioning

### Local Development

1. `wrangler dev` (in `worker/`) → starts local Worker on port 8787, uses local SQLite
2. `node dev-server.js` → SPA on port 3000, proxies `/api/*` to local Worker
3. Run fetch/analyze scripts directly → data written to local SQLite immediately visible in SPA

## Commands

### Install

```bash
pip install -r requirements.txt
cd worker && npm install && cd ..
```

### Local Development

```bash
# Terminal 1: local Worker (port 8787, uses local SQLite)
cd worker && npx wrangler dev

# Terminal 2: dev server (port 3000, proxies to Worker)
node dev-server.js
```

### Pipeline

```bash
export DEEPSEEK_API_KEY="your_api_key_here"

# Fetch papers for a date
python scripts/fetch_arxiv.py --date 2026-05-14 --max-papers 30

# Analyze with DeepSeek
python scripts/analyze_deepseek.py --date 2026-05-14 --concurrency 2

# Sync to remote D1
python scripts/export_to_worker.py --url "$WORKER_URL" --token "$WORKER_TOKEN"
```

### D1 Management

```bash
# Apply migration to local SQLite
npx wrangler d1 execute arxiv-daily-db --local --file migrations/0001_create_papers_table.sql

# One-time seed from JSONL backup to Worker/D1
python scripts/export_to_worker.py --url "$WORKER_URL" --token "$WORKER_TOKEN" --full --source jsonl

# Query local database
npx wrangler d1 execute arxiv-daily-db --local --command "SELECT COUNT(*) FROM papers"

# Deploy Worker to Cloudflare
cd worker && npx wrangler deploy
```

## D1 Schema

Two tables with `INSERT OR IGNORE` for deduplication:

- **papers**: `id TEXT PRIMARY KEY` (arxiv_id), source, title, authors (JSON), abstract, categories (JSON), primary_category, published, updated, entry_url, pdf_url, source_date, venue, year, fetched_at, created_at
- **analyses**: `arxiv_id TEXT PRIMARY KEY`, analysis_version, model, analyzed_at, tldr, research_motivation, problem, phenomenon_analysis, method, contributions (JSON), experiments, limitations (JSON), primary_area_en, primary_area, category, sub_area, tags (JSON), reading_priority, recommended_action, raw_response, created_at

Indexes on `papers.source_date`, `papers.source`, `papers.year`, `analyses.reading_priority`, `analyses.primary_area`, `analyses.category`.

## D1 Free Tier Guidelines

Cloudflare D1 free tier is limited by **daily read/write rows** (not storage). Follow these rules:

1. **Incremental only** — process only recent dates, never re-write historical data.
2. **`INSERT OR IGNORE`** — never `INSERT OR REPLACE` or `DELETE + INSERT`.
3. **Hash-based skip** — skip writes if content hasn't changed.
4. **Batch to 100** — Worker API already batches; maintain this limit.
5. **Single UPDATE per record** — avoid split updates.
6. **Minimal indexing** — current indexes are sufficient, don't add more.
7. **All queries use LIMIT** — no unbounded SELECT.
8. **Local dev uses local D1** — `wrangler dev` uses local SQLite, not remote.
9. **Idempotent runs** — same-day re-runs must not duplicate writes.
10. **Use `--force` to override** — default behavior skips existing records.

## Worker API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/api/dates` | Date index with paper counts |
| GET | `/api/papers?date=YYYY-MM-DD` | Papers for specific date |
| GET | `/api/papers?id=arxiv_id` | Single paper lookup |
| GET | `/api/search?q=query` | Full-text search (paginated, max 200) |
| GET | `/api/stats` | Overall statistics |
| POST | `/api/papers` | Bulk upsert papers (Bearer token required) |
| POST | `/api/analyses` | Bulk upsert analyses (Bearer token required) |

## SPA Frontend

The deployed site (`docs/index.html`) is a single-page application:

- All data loaded from Worker API (`docs/assets/app.js`).
- On init: fetches `/api/dates` for calendar and date list.
- On date selection: fetches `/api/papers?date=YYYY-MM-DD`.
- Unanalyzed papers (no analysis record) display as "未分析" category with abstract only.
- No static JSON dependency for data — `docs/data/` files are backward-compatible only.
- No framework or build step.

## Site UX Rules

- Left sidebar: search, calendar, area/category tree, priority filters, top tags.
- Right content: grouped by primary area → category, papers sorted by priority then recency.
- Unanalyzed papers show simplified card (title, authors, links, abstract) — no analysis grid.
- Show max 20 tags in sidebar.
- No horizontal overflow on desktop or mobile.
- System fonts, restrained academic-tool styling.

## GitHub Actions

Daily at Beijing time 04:00 (`cron: "0 20 * * *"`):

1. Fetch arXiv → local SQLite + JSONL backup
2. DeepSeek analyze → local SQLite + JSONL backup
3. Export new data to Worker API → remote D1
4. Commit and push `data/` (JSONL backup)

Secrets: `DEEPSEEK_API_KEY`, `ARXIV_DAILY_WORKER_URL`, `ARXIV_DAILY_WORKER_TOKEN`.

## External APIs And Secrets

- DeepSeek key from `DEEPSEEK_API_KEY` env var or `.env` file (never committed).
- Default model: `deepseek-v4-flash`.
- Worker API token from `ARXIV_DAILY_WORKER_TOKEN`.
- Never log raw secrets or environment variables.
- `.env` is git-ignored — do not commit.

## Known Limitations

1. Analyzes only title + abstract (no PDF).
2. Does not download arXiv source or extract images.
3. Frontend search limited to currently loaded date's papers.
4. SPA depends on Worker API availability.
5. GitHub Actions scheduling is not second-level precise.
6. DeepSeek output may not be strict JSON (handled with fallback parsing).
