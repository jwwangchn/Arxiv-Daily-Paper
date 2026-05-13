"""Tests for analyze_deepseek.py (→ commands/analyze.py + 03_analyze.py after refactor).

Covers: legacy_priority, parse_model_json, normalize_analysis,
        legacy_analysis_for_site, parse_concurrency, paper_with_analysis_record,
        archive_analysis_record.
"""

import json
from unittest.mock import patch

import pytest


# --- Imports ---

from commands.analyze import (
    ModelJsonError,
    archive_analysis_record,
    legacy_analysis_for_site,
    legacy_priority,
    normalize_analysis,
    paper_with_analysis_record,
    parse_concurrency,
    parse_model_json,
)


# --- legacy_priority ---

class TestLegacyPriority:
    def test_must_read_is_high(self):
        assert legacy_priority("must_read") == "high"

    def test_recommended_is_medium(self):
        assert legacy_priority("recommended") == "medium"

    def test_skim_is_medium(self):
        assert legacy_priority("skim") == "medium"

    def test_low_priority_is_low(self):
        assert legacy_priority("low_priority") == "low"


# --- parse_model_json ---

class TestParseModelJson:
    def test_valid_json(self):
        result = parse_model_json('{"a": 1}')
        assert result == {"a": 1}

    def test_strips_whitespace(self):
        result = parse_model_json('  {"a": 1}  ')
        assert result == {"a": 1}

    def test_strips_code_block_no_lang(self):
        result = parse_model_json('```{"a": 1}```')
        assert result == {"a": 1}

    def test_strips_code_block_with_json_tag(self):
        result = parse_model_json('```json\n{"a": 1}\n```')
        assert result == {"a": 1}

    def test_strips_code_block_with_JSON_tag_uppercase(self):
        result = parse_model_json('```JSON\n{"a": 1}\n```')
        assert result == {"a": 1}

    def test_invalid_json_raises_model_error(self):
        with pytest.raises(ModelJsonError) as exc_info:
            parse_model_json("not json")
        assert exc_info.value.raw_response == "not json"

    def test_model_error_preserves_content(self):
        with pytest.raises(ModelJsonError) as exc_info:
            parse_model_json("{broken: json}")
        assert exc_info.value.raw_response == "{broken: json}"


# --- normalize_analysis ---

class TestNormalizeAnalysis:
    def _make_minimal(self) -> dict:
        return {
            "tldr": "test",
            "reading_priority": "recommended",
            "recommended_action": "read_abstract",
            "primary_area": "其他 ML 主题",
            "category": "其他",
        }

    def test_score_fields_are_removed(self):
        analysis = {
            **self._make_minimal(),
            "novelty": 4,
            "technical_depth": 3,
            "impact": 4,
            "relevance": 5,
            "score_raw": 3.95,
            "score": 4,
            "reason": "good paper",
        }
        result = normalize_analysis(analysis)
        for key in ("novelty", "technical_depth", "impact", "relevance", "score_raw", "score", "reason"):
            assert key not in result

    def test_priority_mapping(self):
        analysis = {**self._make_minimal(), "reading_priority": "must_read"}
        result = normalize_analysis(analysis)
        assert result["reading_priority"] == "must_read"

    def test_unknown_priority_defaults_to_recommended(self):
        analysis = {**self._make_minimal(), "reading_priority": "foobar"}
        result = normalize_analysis(analysis)
        assert result["reading_priority"] == "recommended"

    def test_legacy_priority_alias(self):
        analysis = {**self._make_minimal(), "reading_priority": "high"}
        result = normalize_analysis(analysis)
        assert result["reading_priority"] == "must_read"

    def test_action_mapping_from_priority(self):
        analysis = {**self._make_minimal(), "reading_priority": "must_read", "recommended_action": ""}
        result = normalize_analysis(analysis)
        assert result["recommended_action"] == "read_deeply"

    def test_action_mapping_from_skip(self):
        analysis = {**self._make_minimal(), "reading_priority": "skip", "recommended_action": ""}
        result = normalize_analysis(analysis)
        assert result["recommended_action"] == "skip"

    def test_category_canonicalization(self):
        analysis = {**self._make_minimal(), "category": "其他"}
        result = normalize_analysis(analysis)
        assert result["category"] == "其他"
        assert result["sub_area"] == "其他"

    def test_invalid_category_falls_back(self):
        analysis = {**self._make_minimal(), "category": "nonexistent_category_xyz"}
        result = normalize_analysis(analysis)
        assert result["category"] == "其他"
        assert result["sub_area"] == "其他"

    def test_sub_area_mirrors_category(self):
        analysis = {**self._make_minimal(), "category": "其他"}
        result = normalize_analysis(analysis)
        assert result["sub_area"] == result["category"]

    def test_tldr_from_one_sentence_summary(self):
        analysis = {**self._make_minimal(), "one_sentence_summary": "fallback tldr"}
        del analysis["tldr"]
        result = normalize_analysis(analysis)
        assert result["tldr"] == "fallback tldr"
        assert result["one_sentence_summary"] == "fallback tldr"

    def test_legacy_reading_priority_field(self):
        analysis = {**self._make_minimal(), "reading_priority": "recommended"}
        result = normalize_analysis(analysis)
        assert result["legacy_reading_priority"] == "medium"


# --- legacy_analysis_for_site ---

class TestLegacyAnalysisForSite:
    def test_swaps_priority_fields(self, sample_analysis):
        result = legacy_analysis_for_site(sample_analysis)
        assert result["archive_reading_priority"] == "must_read"
        assert result["reading_priority"] == "high"


# --- parse_concurrency ---

class TestParseConcurrency:
    def test_none_returns_default(self):
        assert parse_concurrency(None) == 4

    def test_string_number(self):
        assert parse_concurrency("3") == 3

    def test_caps_at_max(self):
        assert parse_concurrency(10) == 8

    def test_minimum_1(self):
        assert parse_concurrency(0) == 1
        assert parse_concurrency(-1) == 1

    def test_invalid_string_returns_default(self):
        assert parse_concurrency("abc") == 4


# --- archive_analysis_record ---

class TestAnalysisRecord:
    def test_builds_record(self, sample_analyzed_paper):
        record = archive_analysis_record(
            sample_analyzed_paper,
            analysis_version="v1",
            model="deepseek-v4-flash",
        )
        assert record["arxiv_id"] == "2605.12345"
        assert record["analysis_version"] == "v1"
        assert record["model"] == "deepseek-v4-flash"
        assert "analyzed_at" in record
        assert record["analysis"]["tldr"] == sample_analyzed_paper["analysis"]["tldr"]


# --- paper_with_analysis_record ---

class TestPaperWithAnalysisRecord:
    def test_merges_analysis(self, sample_paper, sample_analysis):
        record = {"analysis": sample_analysis}
        result = paper_with_analysis_record(sample_paper, record)
        assert "analysis" in result

    def test_preserves_error(self, sample_paper):
        record = {"analysis_error": "timeout", "raw_response": "..."}
        result = paper_with_analysis_record(sample_paper, record)
        assert result["analysis_error"] == "timeout"
        assert result["raw_response"] == "..."

    def test_preserves_both_analysis_and_error(self, sample_paper, sample_analysis):
        record = {"analysis": sample_analysis, "analysis_error": "partial"}
        result = paper_with_analysis_record(sample_paper, record)
        assert "analysis" in result
        assert result["analysis_error"] == "partial"
