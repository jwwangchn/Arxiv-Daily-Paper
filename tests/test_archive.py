"""Tests for archive_store.py (→ lib/archive.py after refactor).

Covers: paper_id, paper_source_date, utc_now_iso, read_jsonl, append_jsonl,
        normalize_archive_paper, append_new_papers, append_new_analyses,
        analysis_key, papers_for_date, available_dates,
        latest_analysis_by_arxiv_id, unanalyzed_papers_for_date,
        export_month_data.
"""

import json
from pathlib import Path

import pytest


# --- Imports ---

from lib.archive import (
    ANALYSES_JSONL,
    PAPERS_JSONL,
    analysis_key,
    append_jsonl,
    append_new_analyses,
    append_new_papers,
    available_dates,
    export_month_data,
    latest_analysis_by_arxiv_id,
    load_analysis_index,
    load_paper_index,
    normalize_archive_paper,
    paper_id,
    paper_source_date,
    papers_for_date,
    read_jsonl,
    unanalyzed_papers_for_date,
    utc_now_iso,
)

from tests.conftest import write_jsonl


# --- paper_id ---

class TestPaperId:
    def test_normal(self):
        assert paper_id({"arxiv_id": "2605.12345"}) == "2605.12345"

    def test_missing_key(self):
        assert paper_id({}) == ""

    def test_none_value(self):
        assert paper_id({"arxiv_id": None}) == ""

    def test_strips_whitespace(self):
        assert paper_id({"arxiv_id": "  2605.12345  "}) == "2605.12345"


# --- paper_source_date ---

class TestPaperSourceDate:
    def test_uses_source_date(self):
        assert paper_source_date({"source_date": "2026-05-10T12:00:00Z"}) == "2026-05-10"

    def test_falls_back_to_published(self):
        assert paper_source_date({"published": "2026-05-10T00:00:00Z"}) == "2026-05-10"

    def test_falls_back_to_updated(self):
        assert paper_source_date({"updated": "2026-05-10T12:30:00Z"}) == "2026-05-10"

    def test_empty(self):
        assert paper_source_date({}) == ""

    def test_prefix_10_chars(self):
        assert paper_source_date({"source_date": "2026-05-10"}) == "2026-05-10"


# --- utc_now_iso ---

class TestUtcNowIso:
    def test_ends_with_z(self):
        result = utc_now_iso()
        assert result.endswith("Z")

    def test_valid_iso_format(self):
        from datetime import datetime
        # Should be parseable
        result = utc_now_iso().replace("Z", "+00:00")
        datetime.fromisoformat(result)  # no exception


# --- read_jsonl / append_jsonl ---

class TestReadAppendJsonl:
    def test_read_empty_file(self, tmp_path: Path):
        p = tmp_path / "empty.jsonl"
        p.touch()
        assert read_jsonl(p) == []

    def test_read_nonexistent_file(self, tmp_path: Path):
        assert read_jsonl(tmp_path / "nope.jsonl") == []

    def test_read_valid_records(self, tmp_path: Path):
        p = tmp_path / "data.jsonl"
        write_jsonl(p, [{"a": 1}, {"b": 2}])
        result = read_jsonl(p)
        assert len(result) == 2
        assert result[0]["a"] == 1

    def test_read_skips_blank_lines(self, tmp_path: Path):
        p = tmp_path / "data.jsonl"
        p.write_text('{"a": 1}\n\n{"b": 2}\n', encoding="utf-8")
        result = read_jsonl(p)
        assert len(result) == 2

    def test_read_invalid_json_raises(self, tmp_path: Path):
        p = tmp_path / "data.jsonl"
        p.write_text('{bad json}\n', encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid JSONL"):
            read_jsonl(p)

    def test_append_empty_list(self, tmp_path: Path):
        p = tmp_path / "data.jsonl"
        assert append_jsonl(p, []) == 0
        assert not p.exists()  # nothing written

    def test_append_records(self, tmp_path: Path):
        p = tmp_path / "data.jsonl"
        count = append_jsonl(p, [{"x": 1}, {"x": 2}])
        assert count == 2
        records = read_jsonl(p)
        assert len(records) == 2

    def test_append_compact_separators(self, tmp_path: Path):
        p = tmp_path / "data.jsonl"
        append_jsonl(p, [{"a": 1}])
        raw = p.read_text(encoding="utf-8").strip()
        assert ": " not in raw  # compact: no space after colon


# --- normalize_archive_paper ---

class TestNormalizeArchivePaper:
    def test_sets_source_date(self, sample_paper):
        result = normalize_archive_paper(sample_paper, "2026-05-10")
        assert result["source_date"] == "2026-05-10"

    def test_sets_fetched_at(self, sample_paper):
        result = normalize_archive_paper(sample_paper, "2026-05-10")
        assert "fetched_at" in result

    def test_custom_fetched_at(self, sample_paper):
        result = normalize_archive_paper(sample_paper, "2026-05-10", fetched_at="custom")
        assert result["fetched_at"] == "custom"

    def test_does_not_mutate_original(self, sample_paper):
        original = dict(sample_paper)
        normalize_archive_paper(sample_paper, "2026-05-10")
        assert sample_paper == original


# --- append_new_papers ---

class TestAppendNewPapers:
    def test_appends_new_papers(self, tmp_path: Path, sample_paper):
        p = tmp_path / "papers.jsonl"
        appended, seen = append_new_papers([sample_paper], source_date="2026-05-10", path=p)
        assert appended == 1
        assert seen == 1

    def test_deduplicates_by_arxiv_id(self, tmp_path: Path, sample_paper):
        p = tmp_path / "papers.jsonl"
        append_new_papers([sample_paper], source_date="2026-05-10", path=p)
        appended, seen = append_new_papers([sample_paper], source_date="2026-05-10", path=p)
        assert appended == 0  # already exists

    def test_skips_empty_arxiv_id(self, tmp_path: Path):
        p = tmp_path / "papers.jsonl"
        appended, _ = append_new_papers([{"arxiv_id": ""}], source_date="2026-05-10", path=p)
        assert appended == 0

    def test_batch_dedup(self, tmp_path: Path, sample_paper):
        p = tmp_path / "papers.jsonl"
        appended, seen = append_new_papers(
            [sample_paper, sample_paper], source_date="2026-05-10", path=p
        )
        assert appended == 1
        assert seen == 1

    def test_uses_existing_index(self, tmp_path: Path, sample_paper):
        p = tmp_path / "papers.jsonl"
        index = {sample_paper["arxiv_id"]: sample_paper}
        appended, _ = append_new_papers(
            [sample_paper], source_date="2026-05-10", path=p, existing_index=index
        )
        assert appended == 0
        assert not p.exists()  # nothing to append


# --- append_new_analyses ---

class TestAppendNewAnalyses:
    def test_appends_new_analysis(self, tmp_path: Path):
        p = tmp_path / "analyses.jsonl"
        record = {"arxiv_id": "2605.12345", "analysis_version": "v1", "analysis": {"tldr": "test"}}
        appended, seen = append_new_analyses([record], path=p)
        assert appended == 1
        assert seen == 1

    def test_deduplicates_by_key(self, tmp_path: Path):
        p = tmp_path / "analyses.jsonl"
        record = {"arxiv_id": "2605.12345", "analysis_version": "v1", "analysis": {}}
        append_new_analyses([record], path=p)
        appended, _ = append_new_analyses([record], path=p)
        assert appended == 0

    def test_skips_missing_arxiv_id(self, tmp_path: Path):
        p = tmp_path / "analyses.jsonl"
        appended, _ = append_new_analyses(
            [{"arxiv_id": "", "analysis_version": "v1"}], path=p
        )
        assert appended == 0

    def test_sets_analyzed_at(self, tmp_path: Path):
        p = tmp_path / "analyses.jsonl"
        record = {"arxiv_id": "2605.12345", "analysis_version": "v1"}
        append_new_analyses([record], path=p)
        records = read_jsonl(p)
        assert "analyzed_at" in records[0]


# --- analysis_key ---

class TestAnalysisKey:
    def test_extracts_tuple(self):
        record = {"arxiv_id": "2605.12345", "analysis_version": "v2"}
        assert analysis_key(record) == ("2605.12345", "v2")


# --- papers_for_date ---

class TestPapersForDate:
    def test_returns_matching_papers(self, tmp_path: Path, sample_paper):
        p = tmp_path / "papers.jsonl"
        paper1 = dict(sample_paper, source_date="2026-05-10", fetched_at="now")
        paper2 = dict(sample_paper, arxiv_id="2605.99999", source_date="2026-05-11", fetched_at="now")
        write_jsonl(p, [paper1, paper2])
        result = papers_for_date("2026-05-10", p)
        assert len(result) == 1
        assert result[0]["arxiv_id"] == "2605.12345"

    def test_returns_empty_for_no_match(self, tmp_path: Path):
        p = tmp_path / "papers.jsonl"
        p.touch()
        assert papers_for_date("2026-05-10", p) == []


# --- available_dates ---

class TestAvailableDates:
    def test_returns_sorted_unique_dates(self, tmp_path: Path, sample_paper):
        p = tmp_path / "papers.jsonl"
        write_jsonl(p, [
            dict(sample_paper, source_date="2026-05-12", fetched_at="now"),
            dict(sample_paper, arxiv_id="2605.99999", source_date="2026-05-10", fetched_at="now"),
            dict(sample_paper, arxiv_id="2605.88888", source_date="2026-05-12", fetched_at="now"),
        ])
        result = available_dates(p)
        assert result == ["2026-05-10", "2026-05-12"]


# --- latest_analysis_by_arxiv_id ---

class TestLatestAnalysisByArxivId:
    def test_returns_latest_per_arxiv_id(self, tmp_path: Path):
        p = tmp_path / "analyses.jsonl"
        write_jsonl(p, [
            {"arxiv_id": "2605.12345", "analysis_version": "v1", "analysis": {"score": 3}},
            {"arxiv_id": "2605.12345", "analysis_version": "v2", "analysis": {"score": 4}},
        ])
        result = latest_analysis_by_arxiv_id(path=p)
        assert result["2605.12345"]["analysis"]["score"] == 4

    def test_filters_by_version(self, tmp_path: Path):
        p = tmp_path / "analyses.jsonl"
        write_jsonl(p, [
            {"arxiv_id": "2605.12345", "analysis_version": "v1", "analysis": {}},
            {"arxiv_id": "2605.12345", "analysis_version": "v2", "analysis": {}},
        ])
        result = latest_analysis_by_arxiv_id(version="v1", path=p)
        assert "2605.12345" in result
        assert result["2605.12345"]["analysis_version"] == "v1"


# --- unanalyzed_papers_for_date ---

class TestUnanalyzedPapersForDate:
    def test_returns_unanalyzed(self, tmp_path: Path, sample_paper):
        papers_path = tmp_path / "papers.jsonl"
        analyses_path = tmp_path / "analyses.jsonl"
        paper1 = dict(sample_paper, source_date="2026-05-10", fetched_at="now")
        paper2 = dict(sample_paper, arxiv_id="2605.99999", source_date="2026-05-10", fetched_at="now")
        write_jsonl(papers_path, [paper1, paper2])
        write_jsonl(analyses_path, [
            {"arxiv_id": "2605.12345", "analysis_version": "v1"},
        ])
        result = unanalyzed_papers_for_date(
            "2026-05-10", analysis_version="v1",
            papers_path=papers_path, analyses_path=analyses_path,
        )
        assert len(result) == 1
        assert result[0]["arxiv_id"] == "2605.99999"

    def test_returns_empty_when_all_analyzed(self, tmp_path: Path, sample_paper):
        papers_path = tmp_path / "papers.jsonl"
        analyses_path = tmp_path / "analyses.jsonl"
        paper = dict(sample_paper, source_date="2026-05-10", fetched_at="now")
        write_jsonl(papers_path, [paper])
        write_jsonl(analyses_path, [
            {"arxiv_id": "2605.12345", "analysis_version": "v1"},
        ])
        result = unanalyzed_papers_for_date(
            "2026-05-10", analysis_version="v1",
            papers_path=papers_path, analyses_path=analyses_path,
        )
        assert result == []


# --- export_month_data ---

class TestExportMonthData:
    def test_exports_month(self, tmp_path: Path, sample_paper):
        papers_path = tmp_path / "papers.jsonl"
        analyses_path = tmp_path / "analyses.jsonl"
        write_jsonl(papers_path, [
            dict(sample_paper, source_date="2026-05-10", fetched_at="now"),
        ])
        write_jsonl(analyses_path, [
            {"arxiv_id": "2605.12345", "analysis_version": "v1", "analysis": {"tldr": "test"}},
        ])
        result = export_month_data(
            "2026-05", analysis_version="v1",
            papers_path=papers_path, analyses_path=analyses_path,
        )
        assert result["month"] == "2026-05"
        assert "2026-05-10" in result["dates"]
        assert result["dates"]["2026-05-10"][0]["analysis"]["tldr"] == "test"

    def test_invalid_month_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="YYYY-MM"):
            export_month_data("2026", papers_path=tmp_path / "x.jsonl")

    def test_dates_sorted_descending(self, tmp_path: Path, sample_paper):
        papers_path = tmp_path / "papers.jsonl"
        write_jsonl(papers_path, [
            dict(sample_paper, source_date="2026-05-10", fetched_at="now"),
            dict(sample_paper, arxiv_id="2605.99999", source_date="2026-05-12", fetched_at="now"),
        ])
        result = export_month_data("2026-05", papers_path=papers_path)
        dates = list(result["dates"].keys())
        assert dates == ["2026-05-12", "2026-05-10"]


# --- load_paper_index / load_analysis_index (file-based) ---

class TestLoadIndexes:
    def test_load_paper_index(self, tmp_path: Path, sample_paper):
        p = tmp_path / "papers.jsonl"
        write_jsonl(p, [dict(sample_paper, source_date="2026-05-10", fetched_at="now")])
        index = load_paper_index(p)
        assert "2605.12345" in index

    def test_load_analysis_index(self, tmp_path: Path):
        p = tmp_path / "analyses.jsonl"
        write_jsonl(p, [
            {"arxiv_id": "2605.12345", "analysis_version": "v1"},
        ])
        index = load_analysis_index(p)
        assert ("2605.12345", "v1") in index
