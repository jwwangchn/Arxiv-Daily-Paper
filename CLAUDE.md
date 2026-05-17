# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

See [AGENTS.md](AGENTS.md) for pipeline behavior details, archive store conventions, site UX rules, and editing hygiene. This file focuses on architecture and D1-specific guidance.

## Architecture Overview

The project has a dual-write architecture: data flows through both JSONL files and a D1 database.

```
┌─────────────────────────────────────────────────────────┐
│  GitHub Actions (daily.yml)                              │
│    1. scripts/fetch_arxiv.py       → JSONL + SQLite     │
│    2. scripts/analyze_deepseek.py  → JSONL + SQLite     │
│    3. scripts/export_to_worker.py  → Worker API (D1)   │
│    4. git commit data/ + push                             │
└─────────────────────────────────────────────────────────┘
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
   data/archive/    local SQLite    Cloudflare D1
   *.jsonl          (dev only)      (production)
        │               │               │
        └───────────────┴───────────────┘
                        │
                        ▼
        ┌───────────────────────────────┐
        │  SPA Frontend (docs/index.html)│
        │  → Worker API for all data    │
        │  → /api/dates + /api/papers    │
        └───────────────────────────────┘
```

**Three data layers** (all kept in sync):

| Layer | Location | Role |
|---|---|---|
| **JSONL archive** | `data/archive/papers.jsonl`, `analyses.jsonl` | Canonical source, git-tracked |
| **Local SQLite** | `data/archive/papers.db` | Local dev mirror of D1 schema |
| **Cloudflare D1** | `ac0b5b96-b8c4-4e51-9e92-f8a935875b40` | Production data store for Worker API |

## Key Commands

### Pipeline (GitHub Actions / CI)

```bash
# Full daily pipeline (what the workflow runs):
python scripts/fetch_arxiv.py --date 2026-05-14
python scripts/analyze_deepseek.py --date 2026-05-14 --concurrency 2
python scripts/export_to_worker.py --url "$WORKER_URL" --token "$WORKER_TOKEN"
```

### Local Development

```bash
# Install Python deps
pip install -r requirements.txt

# Install Worker deps
cd worker && npm install && cd ..

# Run local Worker on port 8787
cd worker && npx wrangler dev

# Dev server (SPA on 3000, proxies /api to Worker on 8787)
node dev-server.js

# D1 local simulation
npx wrangler d1 execute arxiv-daily-db --local --file migrations/0001_create_papers_table.sql
```

### Worker Deployment

```bash
cd worker
npx wrangler deploy
```

## Important Paths

| Path | Purpose |
|---|---|
| `scripts/fetch_arxiv.py` | arXiv metadata fetcher, dual-writes to JSONL + SQLite |
| `scripts/analyze_deepseek.py` | DeepSeek analysis (calls DeepSeek API) |
| `scripts/export_to_worker.py` | Exports new JSONL data to Worker API |
| `scripts/lib/db.py` | SQLite layer (local dev mirror of D1 schema) |
| `scripts/lib/archive.py` | JSONL archive layer (canonical source) |
| `worker/src/index.ts` | Hono API server (Cloudflare Worker) |
| `worker/package.json` | Worker dependencies (hono, wrangler) |
| `migrations/0001_create_papers_table.sql` | D1 schema definition |
| `wrangler.toml` | Cloudflare Worker config |
| `docs/assets/app.js` | SPA frontend, all data from Worker API |
| `dev-server.js` | Local dev server (SPA + Worker proxy) |

## Worker API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/api/dates` | Date index with paper counts |
| GET | `/api/papers?date=YYYY-MM-DD` | Papers for specific date |
| GET | `/api/papers?id=arxiv_id` | Single paper lookup |
| GET | `/api/papers?source=all` | All papers (any source) |
| GET | `/api/stats` | Overall statistics |
| GET | `/api/search?q=query` | Full-text search (paginated) |
| POST | `/api/papers` | Bulk upsert papers (requires Bearer token) |
| POST | `/api/analyses` | Bulk upsert analyses (requires Bearer token) |

## GitHub Secrets

| Secret | Value |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek API key |
| `ARXIV_DAILY_WORKER_URL` | `https://arxiv-daily-api.jwwangchn.workers.dev` |
| `ARXIV_DAILY_WORKER_TOKEN` | Worker API Bearer token |

## D1 Free Tier Optimization Guidelines

Cloudflare D1 free tier is limited by **daily read/write rows**, not storage. Current database: 108 MB, ~57K rows. These guidelines prevent quota exhaustion:

### Core Principles

1. **Incremental writes only** — process only recent dates, never re-write historical data.
2. **Use `arxiv_id` as the sole unique key** — `INSERT OR IGNORE`, never `INSERT OR REPLACE`.
3. **Hash-based change detection** — skip updates if content hasn't changed (generate hash of metadata/analysis before writing).
4. **Batch writes** — Worker API already batches to 100 rows per request; maintain this limit.
5. **Single UPDATE per record** — avoid split updates like `UPDATE title` then `UPDATE abstract`.
6. **Minimal indexing** — current indexes (`source_date`, `source`, `year`, `reading_priority`, `primary_area`, `category`) are sufficient. Don't add more without justification.
7. **Long text in D1 is OK for now** — full abstract and analysis are stored in D1. If quota becomes critical, move large fields to R2/static JSON and store paths in D1.
8. **All queries must use LIMIT** — no unbounded `SELECT *`. API endpoints already enforce this.
9. **Local dev uses local D1** — `wrangler dev` uses local SQLite simulation, not remote.
10. **Idempotent CI runs** — same-day re-runs should not duplicate writes. Use `--force` flag to override.
11. **No DELETE+INSERT pattern** — never delete a day's papers to re-insert. Use INSERT OR IGNORE for new, conditional UPDATE for changes.

### Current Status

- Schema uses `INSERT OR IGNORE` for both papers and analyses tables
- Primary keys: `papers.id` (arxiv_id) and `analyses.arxiv_id`
- No DELETE patterns in sync pipeline
- SPA fetches single-date data from API (not month-level bulk)

## Git Tags

| Tag | Commit | Description |
|---|---|---|
| `v1.0.0` | `b9a98bb` | Old version (JSONL + static HTML, pre-migration) |
| `v2.0.0` | `a54acec` | New version (D1/Worker/SPA) |

## Known Issues

- `scripts/analyze_deepseek.py` is referenced in the workflow but does not exist. The actual analysis script is `scripts/commands/analyze.py`. The workflow will fail on the analysis step.
