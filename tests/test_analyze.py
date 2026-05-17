"""Tests for commands/analyze.py.

Covers: parse_model_json, normalize_analysis, parse_concurrency.
"""

import json

import pytest

from commands.analyze import (
    ModelJsonError,
    normalize_analysis,
    parse_concurrency,
    parse_model_json,
    CATEGORY_INDEX,
    AREA_INDEX,
)


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


class TestNormalizeAnalysis:
    def _make_minimal(self) -> dict:
        return {
            "tldr": "test",
            "reading_priority": "recommended",
            "recommended_action": "read_abstract",
            "primary_area": "其他 ML 主题",
            "category": "其他",
        }

    def test_priority_mapping(self):
        analysis = {**self._make_minimal(), "reading_priority": "high"}
        result = normalize_analysis(analysis)
        assert result["reading_priority"] == "high"

    def test_unknown_priority_defaults_to_medium(self):
        analysis = {**self._make_minimal(), "reading_priority": "foobar"}
        result = normalize_analysis(analysis)
        assert result["reading_priority"] == "medium"

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


class TestParseConcurrency:
    def test_none_returns_default(self):
        assert parse_concurrency(None) == 2

    def test_string_number(self):
        assert parse_concurrency("3") == 3

    def test_caps_at_max(self):
        assert parse_concurrency(10) == 4

    def test_minimum_1(self):
        assert parse_concurrency(0) == 1
        assert parse_concurrency(-1) == 1

    def test_invalid_string_returns_default(self):
        assert parse_concurrency("abc") == 2