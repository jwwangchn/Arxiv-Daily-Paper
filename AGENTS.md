# AGENTS.md

Project-level guidance for coding agents working in this repository.

## Project Overview

Daily arXiv paper guide with AI-powered Chinese summaries. Pipeline: fetch arXiv metadata → DeepSeek analysis → store in Cloudflare D1 → serve via Worker API → SPA frontend on GitHub Pages.

**Architecture principle: database-first.** All data flows through D1/SQLite. JSONL files in `data/archive/` are git-tracked backup and seed data, not the primary runtime data source.

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
└──────────────────┘     └──────────────────┘     └──────────────────┘
```

**Three data layers (kept in sync):**

| Layer | Location | Purpose |
|---|---|---|
| **Cloudflare D1** | Remote (`ac0b5b96-...`) | Production data store, queried by Worker |
| **Local SQLite** | `data/archive/papers.db` | Local dev mirror of D1 schema |
| **JSONL archive** | `data/archive/*.jsonl` | Git-tracked backup, used for seeding |

## Important Paths

- `config.yaml` — categories, max papers, topic keywords
- `scripts/fetch_arxiv.py` — arXiv metadata fetcher, dual-writes SQLite + JSONL
- `scripts/analyze_deepseek.py` — thin wrapper, delegates to `commands.analyze`
- `scripts/export_to_worker.py` — syncs local data to remote D1 via Worker API
- `scripts/lib/db.py` — SQLite layer mirroring D1 schema
- `scripts/lib/archive.py` — JSONL archive layer (append-only)
- `scripts/lib/config.py` — config loading from `config.yaml`
- `scripts/commands/analyze.py` — DeepSeek analysis logic
- `scripts/commands/build.py` — SPA build (reads JSONL → writes `docs/`)
- `scripts/fetchers/` — multi-source fetch plugins (AAAI, ACL, CVF, OpenReview)
- `worker/src/index.ts` — Cloudflare Worker (Hono API, ~500 lines)
- `migrations/0001_create_papers_table.sql` — D1 schema definition
- `wrangler.toml` — Cloudflare deployment config with D1 binding
- `dev-server.js` — local dev server (port 3000, proxies `/api/*` to Worker)
- `data/archive/papers.db` — local SQLite database (gitignored)
- `docs/assets/app.js` — SPA frontend, all data from Worker API

**Deprecated paths — do not use:** `data/raw/`, `data/analyzed/`, `scripts/commands/daily.py`, `scripts/commands/fetch.py`.

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

# Terminal 2: dev server (port 3000, proxies /api/* to Worker)
node dev-server.js
```

### Pipeline

```bash
export DEEPSEEK_API_KEY="your_api_key_here"

python scripts/fetch_arxiv.py --date 2026-05-14 --max-papers 30
python scripts/analyze_deepseek.py --date 2026-05-14 --concurrency 2
python scripts/export_to_worker.py --url "$WORKER_URL" --token "$WORKER_TOKEN"
```

### D1 Management

```bash
# Apply migration to local SQLite
npx wrangler d1 execute arxiv-daily-db --local --file migrations/0001_create_papers_table.sql

# Query local database
npx wrangler d1 execute arxiv-daily-db --local --command "SELECT COUNT(*) FROM papers"

# Seed from JSONL backup
python scripts/export_to_worker.py --url "$WORKER_URL" --token "$WORKER_TOKEN" --full --source jsonl

# Deploy Worker
cd worker && npx wrangler deploy
```

## Data Flow

### Production (GitHub Actions, daily at 04:00 Beijing time)

1. `fetch_arxiv.py` → fetches arXiv metadata, writes SQLite + JSONL
2. `analyze_deepseek.py` → calls DeepSeek API, writes SQLite + JSONL
3. `export_to_worker.py` → reads local SQLite, pushes new records to D1 via Worker API
4. Git commits JSONL changes for backup

### Local Development

1. `wrangler dev` → local Worker on :8787, uses local SQLite
2. `node dev-server.js` → SPA on :3000, proxies `/api/*` to Worker
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
10. **Use `--force` to override** — default behavior skips existing records.

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
- `docs/data/` files are backward-compat only, not primary data source.

## Environment Variables

| Variable | Used In | Purpose |
|---|---|---|
| `DEEPSEEK_API_KEY` | analyze.py | DeepSeek API auth (required) |
| `DEEPSEEK_MODEL` | analyze.py | Override model (default: `deepseek-v4-flash`) |
| `DEEPSEEK_CONCURRENCY` | analyze.py | Override concurrency (default: 2, max: 4) |
| `ARXIV_DAILY_WORKER_URL` | export_to_worker.py | Worker URL (default: `https://arxiv-daily-api.jwwangchn.workers.dev`) |
| `ARXIV_DAILY_WORKER_TOKEN` | export_to_worker.py | Worker API Bearer token (required) |
| `WORKER_PORT` | dev-server.js | Local Worker port (default: 8787) |
| `PORT` | dev-server.js | Dev server port (default: 3000) |

`.env` file is git-ignored — never commit secrets.

## Python Path Convention

Scripts add `scripts/` to `sys.path` at runtime. Imports use `from commands.*` and `from lib.*`. Tests follow the same pattern via `conftest.py`.

## DeepSeek Quirk

Uses `openai` Python package with base URL `https://api.deepseek.com`. Output is requested as `response_format: {"type": "json_object"}` with `extra_body: {"thinking": {"type": "disabled"}}`. Has `parse_model_json()` fallback that strips markdown code fences.

## Git Tags

| Tag | Description |
|---|---|
| `v1.0.0` | Old version (JSONL + static HTML, pre-migration) |
| `v2.0.0` | Current version (D1/Worker/SPA) |

## Known Limitations

1. Analyzes only title + abstract (no PDF).
2. Frontend search limited to currently loaded date's papers.
3. SPA depends on Worker API availability.
4. DeepSeek output may not be strict JSON (fallback parsing handles this).
5. No linter, formatter, or typecheck configured for this repo.