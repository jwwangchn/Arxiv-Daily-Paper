"""Merge legacy analyzed JSON bundles into the archive JSONL store."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from commands.analyze import DEFAULT_ANALYSIS_VERSION, normalize_analysis
from lib.archive import append_new_analyses, append_new_papers, load_analysis_index, load_paper_index, paper_id, utc_now_iso
from lib.config import read_json, setup_logging

LOGGER = logging.getLogger("scripts.merge_analyzed")


def paper_without_analysis(paper: dict[str, Any]) -> dict[str, Any]:
    item = dict(paper)
    item.pop("analysis", None)
    item.pop("analysis_error", None)
    item.pop("raw_response", None)
    item.pop("analysis_version", None)
    item.pop("analyzed_at", None)
    return item


def merge_bundle(path: Path, *, analysis_version: str, model: str) -> tuple[int, int]:
    bundle = read_json(path)
    source_date = str(bundle.get("date") or path.stem)
    papers = [paper for paper in bundle.get("papers", []) if paper_id(paper)]

    paper_index = load_paper_index()
    analysis_index = load_analysis_index()

    paper_records = [paper_without_analysis(paper) for paper in papers]
    appended_papers, _ = append_new_papers(paper_records, source_date=source_date, existing_index=paper_index)

    analysis_records = []
    for paper in papers:
        arxiv_id = paper_id(paper)
        analysis = paper.get("analysis")
        if not arxiv_id or not isinstance(analysis, dict):
            continue
        if arxiv_id in analysis_index:
            continue
        analysis_records.append(
            {
                "arxiv_id": arxiv_id,
                "analysis_version": analysis_version,
                "model": model,
                "analyzed_at": str(paper.get("analyzed_at") or utc_now_iso()),
                "analysis": normalize_analysis(dict(analysis)),
            }
        )

    appended_analyses, _ = append_new_analyses(analysis_records, existing_index=analysis_index)
    LOGGER.info(
        "Merged %s: papers=%d appended_papers=%d analyses=%d appended_analyses=%d",
        path,
        len(papers),
        appended_papers,
        len(analysis_records),
        appended_analyses,
    )
    return appended_papers, appended_analyses


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge analyzed JSON bundle(s) into archive JSONL files.")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--analysis-version", default=DEFAULT_ANALYSIS_VERSION)
    parser.add_argument("--model", default=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"))
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    total_papers = 0
    total_analyses = 0
    for path in args.paths:
        appended_papers, appended_analyses = merge_bundle(
            path,
            analysis_version=args.analysis_version,
            model=args.model,
        )
        total_papers += appended_papers
        total_analyses += appended_analyses
    LOGGER.info("Merge complete: appended_papers=%d appended_analyses=%d", total_papers, total_analyses)


if __name__ == "__main__":
    main()
