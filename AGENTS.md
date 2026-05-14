# AGENTS.md

Project-level guidance for coding agents working in this repository.

## Project Overview

This repository builds a static arXiv Daily Paper Guide. The pipeline fetches arXiv metadata, analyzes each paper with DeepSeek using only `title + abstract`, stores all data as JSON, and renders a GitHub Pages site under `docs/`.

Keep the MVP simple:

- Python 3.11.
- No database, SQL, backend service, login, or cloud server.
- No PDF download, arXiv source download, image extraction, embeddings, or vector search.
- Frontend is static HTML/CSS/JavaScript, with no React/Vue/Next/Vite build step.
- The deployed site is served from the repository's `docs/` directory.

## Important Paths

- `config.yaml`: site title, arXiv categories, max papers, topic keywords.
- `scripts/01_daily.py`: full pipeline entrypoint (alias for `scripts/commands/daily.py`).
- `scripts/02_fetch.py`: arXiv metadata fetcher (alias for `scripts/commands/fetch.py`).
- `scripts/03_analyze.py`: DeepSeek analysis and resume logic (alias for `scripts/commands/analyze.py`).
- `scripts/04_build.py`: static site renderer (alias for `scripts/commands/build.py`).
- `scripts/lib/`: shared modules — `config.py`, `archive.py`, `progress.py`, `taxonomy.py`.
- `scripts/commands/`: pipeline command modules — `daily.py`, `fetch.py`, `analyze.py`, `build.py`.
- `scripts/batch/backfill_arxiv.py`: backfills metadata into `data/archive/papers.jsonl`.
- `scripts/batch/analyze_archive.py`: analyzes archived papers date by date.
- `scripts/merge_analyzed_to_archive.py`: one-off importer for legacy analyzed JSON bundles.
- `data/archive/papers.jsonl`: canonical archive of all papers, unique by `arxiv_id`.
- `data/archive/analyses.jsonl`: canonical archive of all analyses, unique by `arxiv_id`.
- `data/raw/` and `data/analyzed/`: deprecated local caches; do not use as source data or commit new files.
- `data/mock/analyzed_sample.json`: mock analyzed data for offline preview.
- `data/iclr_taxonomy.json`: ICLR-style primary area/category taxonomy.
- `docs/`: generated GitHub Pages site.
- `.github/workflows/daily.yml`: scheduled daily run.

## Data And Generated Files

JSON files must be UTF-8 and written with `ensure_ascii=False`.

Canonical data lives in `data/archive/`:

- `data/archive/papers.jsonl`: paper metadata, unique by `arxiv_id`.
- `data/archive/analyses.jsonl`: analysis results, unique by `arxiv_id`.

The site is generated, not hand-authored:

- Edit templates and rendering logic in `scripts/commands/build.py`.
- Then run `python scripts/04_build.py`.
- Generated files in `docs/` may have large diffs after sorting/layout/rendering changes.

Do not manually patch generated HTML unless the user explicitly asks for a one-off emergency fix. Prefer changing the generator and regenerating.

## Commands

Install dependencies:

```bash
pip install -r requirements.txt
```

Mock/offline site build:

```bash
python scripts/01_daily.py --mock
python scripts/04_build.py --mock
```

Normal pipeline:

```bash
export DEEPSEEK_API_KEY="your_api_key_here"
python scripts/01_daily.py
python scripts/01_daily.py --date 2026-05-10 --max-papers 30
python scripts/01_daily.py --date 2026-05-10 --max-papers 30 --concurrency 2
```

Individual steps:

```bash
python scripts/02_fetch.py --date 2026-05-10 --max-papers 30
python scripts/02_fetch.py --latest-with-papers --max-papers 30
python scripts/03_analyze.py --date 2026-05-10 --concurrency 2
python scripts/04_build.py
```

Maintenance scripts:

```bash
python scripts/backfill_all.py                      # backfill metadata 2026-04-01 to today
python scripts/analyze_missing.py                   # analyze all papers missing DeepSeek analysis
python scripts/merge_analyzed_to_archive.py         # merge analyzed/ into archive/analyses.jsonl
```

Lightweight checks:

```bash
python -m py_compile scripts/*.py scripts/lib/*.py scripts/commands/*.py
python scripts/04_build.py
test -f docs/index.html
test -f docs/assets/style.css
test -f docs/assets/app.js
```

## External APIs And Secrets

Never request, print, commit, or write a real API key.

- DeepSeek key comes only from `DEEPSEEK_API_KEY`.
- Optional model override comes from `DEEPSEEK_MODEL`.
- Default model is `deepseek-v4-flash`.
- Do not log raw secrets or environment variables.
- Do not create or commit `.env` files.

If local network access fails, the user's environment may need a SOCKS proxy on `127.0.0.1:1082`. For local troubleshooting, prefer command-scoped proxy variables rather than committing proxy config:

```bash
ALL_PROXY=socks5://127.0.0.1:1082 HTTPS_PROXY=socks5://127.0.0.1:1082 python scripts/run_daily.py --date 2026-05-10
```

## Archive Store

Paper and analysis data are persisted in `data/archive/` as JSONL files, managed by `scripts/lib/archive.py`:

- `data/archive/papers.jsonl`: one JSON object per paper with `arxiv_id`, metadata, and `source_date`. This is the canonical paper source.
- `data/archive/analyses.jsonl`: one JSON object per analyzed paper keyed by `arxiv_id`. `analysis_version` is metadata only, not part of the uniqueness key.
- The archive store provides append-only, index-based deduplication. Functions like `append_new_papers`, `append_new_analyses`, `papers_for_date`, and `available_dates` are the public API.
- `commands/analyze.py` reads papers only from `data/archive/papers.jsonl` and writes successful analyses only to `data/archive/analyses.jsonl`.
- `data/raw/` and `data/analyzed/` are deprecated compatibility caches. Do not add new pipeline dependencies on them.
- Additional scripts: `scripts/batch/backfill_arxiv.py` (bulk metadata backfill), `scripts/batch/analyze_archive.py` (bulk analysis), `scripts/merge_analyzed_to_archive.py` (one-off import from a legacy analyzed JSON file).

## SPA Frontend Architecture

The deployed site (`docs/index.html`) is a single-page application that lazily loads data:

- `docs/data/dates.json` lists all available dates with paper counts and a `latest` date pointer.
- `docs/data/by-month/YYYY-MM.json` contains month-bundled paper data. The SPA loads month data on demand as the user scrolls or navigates.
- Month files are generated by `build_site.py` from `data/archive/papers.jsonl` plus `data/archive/analyses.jsonl`. Stale month files are deleted during rebuild.
- `docs/daily/YYYY-MM-DD.html` pages are simple HTTP redirects to `../index.html?date=YYYY-MM-DD` for backward compatibility with existing links.
- `docs/assets/app.js` handles all client-side filtering, search, lazy loading, and rendering. No framework or build step.

## ICLR Taxonomy

`data/iclr_taxonomy.json` defines the ICLR 2026 classification taxonomy used by both `analyze_deepseek.py` (in the system prompt) and `build_site.py` (for area/category canonicalization). Do not edit this file manually — it should be updated from the official ICLR 2026 taxonomy when needed.

## Pipeline Behavior

`commands/daily.py` (`scripts/01_daily.py`) should:

- Reuse existing archive JSONL records when possible.
- If no date is provided, pick the most recent date with available papers.
- Skip DeepSeek calls when all papers for the selected date are already analyzed.
- Continue site generation when individual paper analyses fail.

`commands/fetch.py` (`scripts/02_fetch.py`) should:

- Use arXiv OAI-PMH (`oaipmh.arxiv.org`) as the primary metadata source, with `arxiv.py` API and browse-page HTML as fallbacks.
- Respect categories and max paper settings from `config.yaml` unless CLI args override them.
- Apply reasonable retry/timeout/rate-limit behavior.
- Append new papers to the archive store (`data/archive/papers.jsonl`) via `append_new_papers`.
- Support `--backfill` for bulk metadata harvesting over date ranges and `--oai-check` for finding papers missed by prior fetches.

`commands/analyze.py` (`scripts/03_analyze.py`) should:

- Analyze only `title + abstract`.
- Load papers from the archive store (`data/archive/papers.jsonl`).
- Skip papers already analyzed in the archive (`data/archive/analyses.jsonl`) by `arxiv_id`.
- Record `analysis_error` per paper instead of failing the whole date when one request fails.
- Preserve raw model response only when useful for parse failure debugging, and never include secrets.
- Use ICLR-style taxonomy fields where available: `primary_area_en`, `primary_area`, and `category`.
- Append successful analyses to the archive store immediately after each paper completes.
- `--cache-only` reports missing archive analyses without calling DeepSeek.

`commands/build.py` (`scripts/04_build.py`) should:

- Read paper data from `data/archive/papers.jsonl` and merge with `data/archive/analyses.jsonl` by `arxiv_id`.
- Work with real analyzed data or mock data.
- Generate `docs/index.html` (SPA entry point), `docs/daily/YYYY-MM-DD.html` (redirect pages), `docs/data/dates.json` (date index), `docs/data/by-month/YYYY-MM.json` (month bundles), `docs/assets/style.css`, and `docs/assets/app.js`.
- Use only relative links so GitHub Pages works under `/Arxiv-Daily-Paper/`.
- Keep generated pages static and CDN-free.
- Delete stale month files and daily pages that no longer correspond to available dates.

`merge_analyzed_to_archive.py` should:

- Import explicitly provided legacy analyzed JSON bundle files.
- Normalize analysis via `commands.analyze.normalize_analysis()` and append new records via `lib.archive.append_new_analyses()`.

## Site UX Rules

The visual target is a compact academic paper guide similar in density to the referenced ICLR guide, but implemented independently.

Preserve these behaviors:

- Left navigation with search, calendar, area/category tree, priority filters, and top tags.
- Right content grouped by primary area and category.
- Default right-side ordering: primary areas by paper count descending, categories by paper count descending, papers by priority `High > Medium > Low` and then newest metadata first.
- Do not hide other primary areas merely because a subcategory filter is active; filtering should update visible cards while keeping the navigation understandable.
- Show only the highest-frequency 20 tags in the sidebar.
- Avoid horizontal overflow on desktop and mobile.
- Use system fonts and restrained academic-tool styling.

When changing UI, verify generated HTML at least by rebuilding and checking `docs/index.html` exists. For larger visual changes, inspect in a browser if available.

## GitHub Actions And Pages

The scheduled workflow runs daily at Beijing time 04:00, which is `20:00 UTC` on the previous day:

```yaml
cron: "0 20 * * *"
```

The workflow should:

- Use Python 3.11.
- Install `requirements.txt`.
- Read `DEEPSEEK_API_KEY` from GitHub Secrets.
- Run `python scripts/run_daily.py`.
- Commit and push changes under `data/` and `docs/`.
- Exit cleanly if there are no changes.

GitHub Pages should deploy from branch `main`, folder `/docs`.

## Editing And Commit Hygiene

- Keep changes scoped to the user's request.
- Do not revert user changes or generated data unless explicitly asked.
- Prefer changing source scripts over editing generated artifacts directly.
- If generated artifacts change because of a source change, include them when the user asks for a ready-to-deploy update.
- Before committing, run `git status --short` and inspect the diff enough to understand what is being committed.
- Group unrelated work into separate commits when the user asks for categorized commits.

## Known Limitations To Preserve In Docs

The MVP intentionally:

- Analyzes only title and abstract.
- Does not read PDFs.
- Does not download arXiv source.
- Does not extract figures or main images.
- Does not use a database or backend service.
- Performs search/filtering only in the current static page.
- Depends on DeepSeek JSON compliance and prompt quality.
- Relies on GitHub Actions scheduling, which is not second-level precise.
