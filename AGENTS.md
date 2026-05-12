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
- `scripts/run_daily.py`: full pipeline entrypoint.
- `scripts/fetch_arxiv.py`: arXiv metadata fetcher.
- `scripts/analyze_deepseek.py`: DeepSeek analysis and resume logic.
- `scripts/build_site.py`: static site renderer.
- `scripts/utils.py`: shared filesystem/config/logging helpers.
- `data/raw/`: fetched arXiv JSON by date.
- `data/analyzed/`: analyzed JSON by date.
- `data/mock/analyzed_sample.json`: mock analyzed data for offline preview.
- `data/iclr_taxonomy.json`: ICLR-style primary area/category taxonomy.
- `docs/`: generated GitHub Pages site.
- `.github/workflows/daily.yml`: scheduled daily run.

## Data And Generated Files

JSON files must be UTF-8 and written with `ensure_ascii=False`.

The site is generated, not hand-authored:

- Edit templates and rendering logic in `scripts/build_site.py`.
- Then run `python scripts/build_site.py`.
- Generated files in `docs/` may have large diffs after sorting/layout/rendering changes.

Do not manually patch generated HTML unless the user explicitly asks for a one-off emergency fix. Prefer changing the generator and regenerating.

## Commands

Install dependencies:

```bash
pip install -r requirements.txt
```

Mock/offline site build:

```bash
python scripts/run_daily.py --mock
python scripts/build_site.py --mock
```

Normal pipeline:

```bash
export DEEPSEEK_API_KEY="your_api_key_here"
python scripts/run_daily.py
python scripts/run_daily.py --date 2026-05-10 --max-papers 30
python scripts/run_daily.py --date 2026-05-10 --max-papers 30 --concurrency 2
```

Individual steps:

```bash
python scripts/fetch_arxiv.py --date 2026-05-10 --max-papers 30
python scripts/fetch_arxiv.py --latest-with-papers --max-papers 30
python scripts/analyze_deepseek.py --date 2026-05-10 --concurrency 2
python scripts/build_site.py
```

Lightweight checks:

```bash
python -m py_compile scripts/*.py
python scripts/build_site.py
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

## Pipeline Behavior

`run_daily.py` should:

- Reuse existing raw/analyzed JSON when possible.
- If no date is provided, pick the most recent date with available papers.
- Skip DeepSeek calls when all papers for the selected date are already analyzed.
- Continue site generation when individual paper analyses fail.

`fetch_arxiv.py` should:

- Use `arxiv.py` for metadata.
- Respect categories and max paper settings from `config.yaml` unless CLI args override them.
- Apply reasonable retry/timeout/rate-limit behavior.
- Write a valid raw JSON file even when no papers are found.

`analyze_deepseek.py` should:

- Analyze only `title + abstract`.
- Resume from existing analyzed JSON and avoid duplicate API calls.
- Record `analysis_error` per paper instead of failing the whole date when one request fails.
- Preserve raw model response only when useful for parse failure debugging, and never include secrets.
- Use ICLR-style taxonomy fields where available: `primary_area_en`, `primary_area`, and `category`.

`build_site.py` should:

- Work with real analyzed data or mock data.
- Generate `docs/index.html`, `docs/daily/YYYY-MM-DD.html`, `docs/data/dates.json`, `docs/assets/style.css`, and `docs/assets/app.js`.
- Use only relative links so GitHub Pages works under `/Arxiv-Daily-Paper/`.
- Keep generated pages static and CDN-free.

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
