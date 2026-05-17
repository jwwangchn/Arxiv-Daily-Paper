"""Tests for commands.daily.py."""

from unittest.mock import patch

import pytest

from commands.daily import is_fully_analyzed


class TestIsFullyAnalyzed:
    def test_all_analyzed(self):
        papers = [{"arxiv_id": "2605.00001"}, {"arxiv_id": "2605.00002"}]
        with patch(
            "commands.daily.load_analysis_index",
            return_value={"2605.00001": {}, "2605.00002": {}},
        ):
            assert is_fully_analyzed("2026-05-10", papers) is True

    def test_missing_analysis(self):
        papers = [{"arxiv_id": "2605.00001"}, {"arxiv_id": "2605.00002"}]
        with patch("commands.daily.load_analysis_index", return_value={"2605.00001": {}}):
            assert is_fully_analyzed("2026-05-10", papers) is False

    def test_empty_papers(self):
        with patch("commands.daily.load_analysis_index", return_value={}):
            assert is_fully_analyzed("2026-05-10", []) is False