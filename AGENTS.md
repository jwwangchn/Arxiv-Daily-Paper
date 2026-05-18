# AGENTS.md

Project-level guidance for coding agents working in this repository.

## Project Overview

Daily arXiv paper guide with AI-powered Chinese summaries. Pipeline: fetch arXiv metadata via OAI-PMH → DeepSeek analysis → store in Cloudflare D1 → serve via Worker API → SPA frontend.

**Architecture principle: database-first.** All data flows through SQLite (local) / D1 (production). No JSONL or static HTML generation. The SPA reads exclusively from the Worker API.

Fetch uses **OAI-PMH only** — if OAI fails, the pipeline errors out. No arxiv.py fallback, no browse-page scraping.

Core stack:

- Python 3.11 data pipeline scripts
- Cloudflare D1 (production) + local SQLite mirror (dev)
- Cloudflare Worker (Hono/TypeScript) API layer
- Plain HTML/CSS/JS SPA (`docs/assets/app.js`, no framework)
- GitHub Actions scheduled pipeline

## Architecture

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  GitHub Actions   │────▶│  Cloudflare       │◀────│  SPA Frontend    │
│  (daily.yml)      │     │  Worker + D1      │     │  (docs/index)    │
│                   │     │                   │     │                   │
│  fetch_arxiv.py   │     │  GET /api/*       │     │  app.js          │
│  analyze_*.py     │     │  POST /api/*      │     │  Worker API only │
│  export_to_worker │     │                   │     │                   │
│  update_date_index│     │                   │     │  data/dates.json │
└──────────────────┘     └──────────────────┘     └──────────────────┘
```

**Data layers:**

| Layer | Location | Purpose |
|---|---|---|
| **Cloudflare D1** | Remote | Production data store, queried by Worker for paper details |
| **Local SQLite** | `data/archive/papers.db` | Local dev/CI mirror of D1 schema |
| **Static Index** | `docs/data/dates.json` | Committed JSON index for calendar counts (reduces D1 reads) |

## Important Paths

- `config.yaml` — categories, max papers, topic keywords
- `scripts/fetch_arxiv.py` — arXiv OAI-PMH fetcher entry point, writes to SQLite
- `scripts/analyze_deepseek.py` — thin wrapper, delegates to `commands.analyze`
- `scripts/export_to_worker.py` — syncs local SQLite to remote D1 via Worker API
- `scripts/lib/db.py` — SQLite layer mirroring D1 schema (sole data layer)
- `scripts/lib/config.py` — config loading from `config.yaml`
- `scripts/lib/progress.py` — progress bar utility
- `scripts/commands/analyze.py` — DeepSeek analysis logic, reads/writes SQLite only
- `scripts/commands/fetch.py` — OAI-PMH fetch logic (sole fetch method)
- `scripts/commands/daily.py` — full pipeline (fetch → analyze, no build step)
- `scripts/fetchers/base.py` — base fetcher class (framework for future fetchers)
- `scripts/fetchers/registry.py` — fetcher registry (framework for future fetchers)
- `worker/src/index.ts` — Cloudflare Worker (Hono API)
- `migrations/0001_create_papers_table.sql` — D1 schema definition
- `wrangler.toml` — Cloudflare deployment config with D1 binding
- `tools/dev-server.js` — local dev server (port 3000, proxies `/api/*` to Worker)
- `data/archive/papers.db` — local SQLite database (gitignored)
- `data/iclr_taxonomy.json` — ICLR 2026 classification taxonomy
- `docs/assets/app.js` — SPA frontend, all data from Worker API
- `docs/data/dates.json` — Static date index for calendar (committed to repo)
- `tests/` — unit tests (pytest)

**Removed paths — do not use:** `scripts/lib/archive.py`, `scripts/commands/build.py`, `data/raw/`, `data/analyzed/`, `data/mock/`, `data/archive/papers.jsonl`, `data/archive/analyses.jsonl`, `db/schema.sql`, `scripts/fetchers/aaai_ojs.py`, `scripts/fetchers/acl_anthology.py`, `scripts/fetchers/cvf.py`, `scripts/fetchers/openreview.py`.

## Commands

### Install

```bash
pip install -r requirements.txt
cd worker && npm install && cd ..
```

### Initialize Local Database

```bash
npx wrangler d1 execute arxiv-daily-db --local --file migrations/0001_create_papers_table.sql
```

### Local Development

```bash
# Terminal 1: local Worker (port 8787, uses local SQLite)
cd worker && npx wrangler dev

# Terminal 2: dev server (port 3000, proxies /api/* to Worker)
node tools/dev-server.js
```

### Pipeline

```bash
export DEEPSEEK_API_KEY="your_api_key_here"

python scripts/fetch_arxiv.py --date 2026-05-14 --max-papers 30
python scripts/analyze_deepseek.py --date 2026-05-14 --concurrency 2
python scripts/export_to_worker.py --url "$WORKER_URL" --token "$WORKER_TOKEN"
```

### Tests

```bash
PYTHONPATH=scripts pytest tests/ -v --cov=scripts --cov-report=term-missing
```

### D1 Management

```bash
# Query local database
npx wrangler d1 execute arxiv-daily-db --local --command "SELECT COUNT(*) FROM papers"

# Full export to remote D1
python scripts/export_to_worker.py --url "$WORKER_URL" --token "$WORKER_TOKEN" --full

# Deploy Worker
cd worker && npx wrangler deploy
```

### Trigger GitHub Action

The `daily.yml` workflow runs automatically at 04:00 Beijing time (20:00 UTC). It processes **today's date** by default.

```bash
# Trigger for today
gh workflow run daily.yml --ref main

# Trigger for a specific date
gh workflow run daily.yml --ref main -f date=2026-05-15

# Trigger with custom max papers and concurrency
gh workflow run daily.yml --ref main -f date=2026-05-15 -f max_papers=50 -f concurrency=4

# Full export all local data to D1
gh workflow run daily.yml --ref main -f full_export=true
```

Workflow inputs:
- `date` (YYYY-MM-DD) — target date (default: today)
- `max_papers` — max number of papers to fetch
- `concurrency` — DeepSeek API concurrency (max: 4)
- `full_export` — export all local SQLite records to D1 instead of just the target date

## Data Flow

### Production (GitHub Actions, daily at 04:00 Beijing time)

1. `fetch_arxiv.py` → fetches arXiv metadata via OAI-PMH, writes to SQLite
2. `analyze_deepseek.py` → calls DeepSeek API, writes analysis to SQLite
3. `export_to_worker.py` → reads local SQLite, pushes new records to D1 via Worker API

### Local Development

1. `wrangler dev` → local Worker on :8787, uses local SQLite
2. `node tools/dev-server.js` → SPA on :3000, proxies `/api/*` to Worker
3. Run fetch/analyze scripts → data written to local SQLite immediately visible in SPA

## D1 Schema

Two tables:

- **papers**: `id TEXT PRIMARY KEY` (arxiv_id), source, title, authors (JSON), abstract, categories (JSON), primary_category, published, updated, entry_url, pdf_url, source_date, venue, year, fetched_at, created_at
- **analyses**: `arxiv_id TEXT PRIMARY KEY`, analysis_version, model, analyzed_at, tldr, research_motivation, problem, phenomenon_analysis, method, contributions (JSON), experiments, limitations (JSON), primary_area_en, primary_area, category, sub_area, tags (JSON), reading_priority, recommended_action, raw_response, created_at

Indexes on `papers.source_date`, `papers.source`, `papers.year`, `analyses.reading_priority`, `analyses.primary_area`, `analyses.category`.

**Important write semantics:**
- **papers**: `INSERT ... ON CONFLICT(id) DO UPDATE SET` — upserts (updates existing)
- **analyses**: `INSERT OR IGNORE` — no overwrite of existing analyses

## D1 Free Tier Guidelines

Cloudflare D1 free tier is limited by **daily read/write rows** (not storage). Follow these rules:

1. **Incremental only** — process only recent dates, never re-write historical data.
2. **`INSERT OR IGNORE` for analyses** — never `INSERT OR REPLACE` or `DELETE + INSERT`.
3. **Upsert for papers** — `ON CONFLICT DO UPDATE` is correct for papers (allows metadata updates).
4. **Hash-based skip** — skip writes if content hasn't changed.
5. **Batch to 100** — Worker API already batches; maintain this limit.
6. **No DELETE+INSERT** — never delete a day's papers to re-insert.
7. **All queries use LIMIT** — no unbounded SELECT.
8. **Local dev uses local D1** — `wrangler dev` uses local SQLite, not remote.
9. **Idempotent runs** — same-day re-runs must not duplicate writes.

## Worker API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/api/dates` | Date index with paper counts (cached) |
| GET | `/api/papers?date=YYYY-MM-DD` | Papers for specific date (cached) |
| GET | `/api/papers?month=YYYY-MM` | Papers for a month |
| GET | `/api/papers?id=arxiv_id` | Single paper lookup |
| GET | `/api/papers?source=all` | All papers (any source) |
| GET | `/api/papers?date=...&priority=&tag=&area=&q=&limit=50&offset=0` | Filtered + paginated |
| GET | `/api/facets?date=&month=&source=` | Facet counts (priorities, tags, areas) |
| GET | `/api/search?q=query&limit=50&offset=0` | Full-text LIKE search (max 200) |
| GET | `/api/stats` | Overall statistics |
| POST | `/api/papers` | Bulk upsert papers (max 100/batch, Bearer auth) |
| POST | `/api/analyses` | Bulk upsert analyses (max 100/batch, Bearer auth, INSERT OR IGNORE) |

Worker uses Cache API with `s-maxage=900`, `max-age=300`, `stale-while-revalidate=86400`.

Priority mapping in Worker: `must_read→high`, `recommended→medium`, `skim→low`, `low_priority→low`, `skip→low`.

## SPA Frontend

- `docs/assets/app.js` — vanilla JS, no framework, no build step.
- Hardcoded `WORKER_URL = "https://arxiv-daily-api.jwwangchn.workers.dev"`.
- Dev server injects `window.API_BASE_URL=""` for same-origin API calls.
- On init: fetches `/api/dates` → calendar + date list.
- On date selection: fetches `/api/papers?date=YYYY-MM-DD`.
- Unanalyzed papers display as "未分析" category with abstract only.

## Environment Variables

| Variable | Used In | Purpose |
|---|---|---|
| `DEEPSEEK_API_KEY` | analyze.py | DeepSeek API auth (required) |
| `DEEPSEEK_MODEL` | analyze.py | Override model (default: `deepseek-v4-flash`) |
| `DEEPSEEK_CONCURRENCY` | analyze.py | Override concurrency (default: 2, max: 4) |
| `ARXIV_DAILY_WORKER_URL` | export_to_worker.py | Worker URL (default: `https://arxiv-daily-api.jwwangchn.workers.dev`) |
| `ARXIV_DAILY_WORKER_TOKEN` | export_to_worker.py | Worker API Bearer token (required) |
| `WORKER_PORT` | tools/dev-server.js | Local Worker port (default: 8787) |
| `PORT` | tools/dev-server.js | Dev server port (default: 3000) |

`.env` file is git-ignored — never commit secrets.

## Python Path Convention

Scripts add `scripts/` to `sys.path` at runtime. Imports use `from commands.*` and `from lib.*`. Tests follow the same pattern via `conftest.py`.

## DeepSeek Quirk

Uses `openai` Python package with base URL `https://api.deepseek.com`. Output is requested as `response_format: {"type": "json_object"}` with `extra_body: {"thinking": {"type": "disabled"}}`. Has `parse_model_json()` fallback that strips markdown code fences.

## Git Tags

| Tag | Description |
|---|---|
| `v1.0.0` | Old version (JSONL + static HTML, pre-migration) |
| `v2.0.0` | D1/Worker/SPA version |

## Known Limitations

1. Analyzes only title + abstract (no PDF).
2. Frontend search limited to currently loaded date's papers.
3. SPA depends on Worker API availability.
4. DeepSeek output may not be strict JSON (fallback parsing handles this).
5. OAI-PMH is the sole fetch method — no fallback if it fails.
6. No linter, formatter, or typecheck configured for this repo.