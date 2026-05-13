"""Tests for utils.py (→ lib/config.py after refactor).

Covers: normalize_space, parse_date, today_iso, paper_matches_topics,
        read_json / write_json roundtrip, ensure_dirs.
"""

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest


# --- Imports ---

from lib.config import (
    ensure_dirs,
    normalize_space,
    paper_matches_topics,
    parse_date,
    read_json,
    today_iso,
    write_json,
)


# --- normalize_space ---

class TestNormalizeSpace:
    def test_single_spaces_unchanged(self):
        assert normalize_space("hello world") == "hello world"

    def test_multiple_spaces_collapsed(self):
        assert normalize_space("hello   world") == "hello world"

    def test_tabs_and_newlines_collapsed(self):
        assert normalize_space("hello\t\nworld") == "hello world"

    def test_leading_trailing_stripped(self):
        assert normalize_space("  hello  ") == "hello"

    def test_none_returns_empty(self):
        assert normalize_space(None) == ""

    def test_empty_string(self):
        assert normalize_space("") == ""


# --- parse_date ---

class TestParseDate:
    def test_valid_date_roundtrip(self):
        assert parse_date("2026-05-10") == "2026-05-10"

    def test_none_returns_today(self):
        result = parse_date(None)
        assert result == date.today().isoformat()

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            parse_date("05-10-2026")

    def test_non_date_string_raises(self):
        with pytest.raises(ValueError):
            parse_date("not-a-date")


# --- today_iso ---

class TestTodayIso:
    def test_returns_iso_format(self):
        result = today_iso()
        assert result == date.today().isoformat()


# --- paper_matches_topics ---

class TestPaperMatchesTopics:
    def test_no_match(self, sample_paper, sample_topics):
        result = paper_matches_topics(sample_paper, sample_topics)
        assert "Video Generation" not in result
        assert "Vision-Language Model" in result

    def test_match_by_title(self, sample_paper, sample_topics):
        sample_paper["title"] = "Video Generation with DiT"
        result = paper_matches_topics(sample_paper, sample_topics)
        assert "Video Generation" in result

    def test_match_by_abstract(self, sample_paper, sample_topics):
        sample_paper["abstract"] = "We propose text-to-video diffusion."
        result = paper_matches_topics(sample_paper, sample_topics)
        assert "Video Generation" in result

    def test_multiple_topics(self, sample_paper, sample_topics):
        sample_paper["title"] = "Video Generation for VLM"
        result = paper_matches_topics(sample_paper, sample_topics)
        assert "Vision-Language Model" in result
        assert "Video Generation" in result

    def test_empty_paper(self, sample_topics):
        result = paper_matches_topics({}, sample_topics)
        assert result == []

    def test_empty_topics(self, sample_paper):
        result = paper_matches_topics(sample_paper, {})
        assert result == []

    def test_case_insensitive(self, sample_paper, sample_topics):
        sample_paper["title"] = "VISION LANGUAGE MODEL TEST"
        result = paper_matches_topics(sample_paper, sample_topics)
        assert "Vision-Language Model" in result


# --- read_json / write_json ---

class TestJsonRoundtrip:
    def test_write_and_read(self, tmp_path: Path):
        data = {"key": "value", "nested": {"a": 1}}
        path = tmp_path / "test.json"
        write_json(path, data)
        result = read_json(path)
        assert result == data

    def test_ensure_ascii_false(self, tmp_path: Path):
        data = {"chinese": "中文测试"}
        path = tmp_path / "test.json"
        write_json(path, data)
        raw = path.read_text(encoding="utf-8")
        assert "中文测试" in raw

    def test_indent_two_spaces(self, tmp_path: Path):
        data = {"a": 1, "b": 2}
        path = tmp_path / "test.json"
        write_json(path, data)
        raw = path.read_text(encoding="utf-8")
        assert "  " in raw

    def test_trailing_newline(self, tmp_path: Path):
        data = {"a": 1}
        path = tmp_path / "test.json"
        write_json(path, data)
        raw = path.read_text(encoding="utf-8")
        assert raw.endswith("\n")


# --- ensure_dirs ---

class TestEnsureDirs:
    @patch("lib.config.PROJECT_ROOT")
    def test_creates_all_expected_dirs(self, mock_root, tmp_path: Path):
        mock_root.__truediv__ = lambda self, other: tmp_path / other
        ensure_dirs()
        assert (tmp_path / "data" / "raw").is_dir()
        assert (tmp_path / "data" / "analyzed").is_dir()
        assert (tmp_path / "data" / "archive").is_dir()
        assert (tmp_path / "data" / "mock").is_dir()
        assert (tmp_path / "docs" / "daily").is_dir()
        assert (tmp_path / "docs" / "data").is_dir()
        assert (tmp_path / "docs" / "assets").is_dir()
