"""Tests for commands.daily.py (→ 01_daily.py after refactor).

Covers: is_fully_analyzed, load_existing_papers, find_latest_existing_or_fetch.
These are orchestrator functions that require mocking external calls.
"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# --- is_fully_analyzed ---

class TestIsFullyAnalyzed:
    def test_all_analyzed(self, tmp_path):
        # Mock PROJECT_ROOT to tmp_path
        papers = [
            {"arxiv_id": "2605.00001", "analysis": {"tldr": "test"}},
            {"arxiv_id": "2605.00002", "analysis": {"tldr": "test"}},
        ]
        analyzed_path = tmp_path / "data" / "analyzed" / "2026-05-10.json"
        analyzed_path.parent.mkdir(parents=True)
        with analyzed_path.open("w") as f:
            json.dump({"date": "2026-05-10", "papers": papers}, f)

        with patch("commands.daily.PROJECT_ROOT", tmp_path):
            from commands.daily import is_fully_analyzed
            result = is_fully_analyzed("2026-05-10", papers)
        assert result is True

    def test_missing_analysis(self, tmp_path):
        papers = [
            {"arxiv_id": "2605.00001", "analysis": {"tldr": "test"}},
            {"arxiv_id": "2605.00002"},  # no analysis
        ]
        analyzed_path = tmp_path / "data" / "analyzed" / "2026-05-10.json"
        analyzed_path.parent.mkdir(parents=True)
        with analyzed_path.open("w") as f:
            json.dump({"date": "2026-05-10", "papers": papers}, f)

        with patch("commands.daily.PROJECT_ROOT", tmp_path):
            from commands.daily import is_fully_analyzed
            result = is_fully_analyzed("2026-05-10", papers)
        assert result is False

    def test_no_analyzed_file(self, tmp_path):
        with patch("commands.daily.PROJECT_ROOT", tmp_path):
            from commands.daily import is_fully_analyzed
            result = is_fully_analyzed("2026-05-10", [{"arxiv_id": "2605.00001"}])
        assert result is False

    def test_empty_papers(self, tmp_path):
        with patch("commands.daily.PROJECT_ROOT", tmp_path):
            from commands.daily import is_fully_analyzed
            result = is_fully_analyzed("2026-05-10", [])
        assert result is False

    def test_error_counts_as_analyzed(self, tmp_path):
        papers = [
            {"arxiv_id": "2605.00001", "analysis_error": "timeout"},
        ]
        analyzed_path = tmp_path / "data" / "analyzed" / "2026-05-10.json"
        analyzed_path.parent.mkdir(parents=True)
        with analyzed_path.open("w") as f:
            json.dump({"date": "2026-05-10", "papers": papers}, f)

        with patch("commands.daily.PROJECT_ROOT", tmp_path):
            from commands.daily import is_fully_analyzed
            result = is_fully_analyzed("2026-05-10", papers)
        assert result is True


# --- load_existing_papers ---

class TestLoadExistingPapers:
    def test_finds_raw_data(self, tmp_path):
        raw_path = tmp_path / "data" / "raw" / "2026-05-10.json"
        raw_path.parent.mkdir(parents=True)
        with raw_path.open("w") as f:
            json.dump({"date": "2026-05-10", "papers": [{"arxiv_id": "2605.00001"}]}, f)

        with patch("commands.daily.PROJECT_ROOT", tmp_path):
            from commands.daily import load_existing_papers
            papers, source = load_existing_papers("2026-05-10")

        assert len(papers) == 1
        assert source == "raw"

    def test_finds_analyzed_data(self, tmp_path):
        analyzed_path = tmp_path / "data" / "analyzed" / "2026-05-10.json"
        analyzed_path.parent.mkdir(parents=True)
        with analyzed_path.open("w") as f:
            json.dump({"date": "2026-05-10", "papers": [{"arxiv_id": "2605.00001", "analysis": {}}]}, f)

        with patch("commands.daily.PROJECT_ROOT", tmp_path):
            from commands.daily import load_existing_papers
            papers, source = load_existing_papers("2026-05-10")

        assert len(papers) == 1
        assert source == "analyzed"

    def test_returns_empty_when_not_found(self, tmp_path):
        with patch("commands.daily.PROJECT_ROOT", tmp_path):
            from commands.daily import load_existing_papers
            papers, source = load_existing_papers("2026-05-10")

        assert papers == []
        assert source == ""

    def test_prefers_raw_over_analyzed(self, tmp_path):
        # Both exist; raw should be checked first
        raw_path = tmp_path / "data" / "raw" / "2026-05-10.json"
        raw_path.parent.mkdir(parents=True)
        with raw_path.open("w") as f:
            json.dump({"date": "2026-05-10", "papers": [{"arxiv_id": "2605.00001"}]}, f)

        analyzed_path = tmp_path / "data" / "analyzed" / "2026-05-10.json"
        analyzed_path.parent.mkdir(parents=True)
        with analyzed_path.open("w") as f:
            json.dump({"date": "2026-05-10", "papers": [{"arxiv_id": "2605.00002", "analysis": {}}]}, f)

        with patch("commands.daily.PROJECT_ROOT", tmp_path):
            from commands.daily import load_existing_papers
            papers, source = load_existing_papers("2026-05-10")

        assert papers[0]["arxiv_id"] == "2605.00001"
        assert source == "raw"


# --- find_latest_existing_or_fetch ---

class TestFindLatestExistingOrFetch:
    def test_finds_existing_raw(self, tmp_path):
        raw_path = tmp_path / "data" / "raw" / "2026-05-10.json"
        raw_path.parent.mkdir(parents=True)
        with raw_path.open("w") as f:
            json.dump({"date": "2026-05-10", "papers": [{"arxiv_id": "2605.00001"}]}, f)

        with patch("commands.daily.PROJECT_ROOT", tmp_path), \
             patch("commands.daily.fetch_papers") as mock_fetch:
            from commands.daily import find_latest_existing_or_fetch
            date, papers, source = find_latest_existing_or_fetch(
                ["cs.CV"], 30, lookback_days=14, start_date="2026-05-10"
            )

        assert date == "2026-05-10"
        assert len(papers) == 1
        mock_fetch.assert_not_called()

    def test_falls_back_to_fetch(self, tmp_path):
        with patch("commands.daily.PROJECT_ROOT", tmp_path), \
             patch("commands.daily.fetch_papers") as mock_fetch:
            mock_fetch.return_value = [{"arxiv_id": "2605.00001"}]
            from commands.daily import find_latest_existing_or_fetch
            date, papers, source = find_latest_existing_or_fetch(
                ["cs.CV"], 30, lookback_days=14, start_date="2026-05-10"
            )

        assert date == "2026-05-10"
        assert source == "fetched"
        mock_fetch.assert_called_once()

    def test_walks_backwards(self, tmp_path):
        # Only 2026-05-08 has data
        raw_path = tmp_path / "data" / "raw" / "2026-05-08.json"
        raw_path.parent.mkdir(parents=True)
        with raw_path.open("w") as f:
            json.dump({"date": "2026-05-08", "papers": [{"arxiv_id": "2605.00008"}]}, f)

        with patch("commands.daily.PROJECT_ROOT", tmp_path), \
             patch("commands.daily.fetch_papers") as mock_fetch:
            mock_fetch.return_value = []  # no new data
            from commands.daily import find_latest_existing_or_fetch
            date, papers, source = find_latest_existing_or_fetch(
                ["cs.CV"], 30, lookback_days=14, start_date="2026-05-12"
            )

        assert date == "2026-05-08"
        assert source == "raw"

    def test_raises_when_nothing_found(self, tmp_path):
        with patch("commands.daily.PROJECT_ROOT", tmp_path), \
             patch("commands.daily.fetch_papers") as mock_fetch:
            mock_fetch.return_value = []
            from commands.daily import find_latest_existing_or_fetch
            with pytest.raises(RuntimeError, match="No arXiv papers"):
                find_latest_existing_or_fetch(
                    ["cs.CV"], 30, lookback_days=2, start_date="2026-05-10"
                )


# --- _date_path ---

class TestDatePath:
    def test_prefers_monthly_over_legacy(self, tmp_path):
        monthly = tmp_path / "data" / "analyzed" / "2026-05" / "2026-05-10.json"
        monthly.parent.mkdir(parents=True)
        monthly.write_text("{}")

        legacy = tmp_path / "data" / "analyzed" / "2026-05-10.json"
        legacy.write_text("{}")

        with patch("commands.daily.PROJECT_ROOT", tmp_path):
            from commands.daily import _date_path
            result = _date_path("analyzed", "2026-05-10")
        assert "2026-05" in str(result)

    def test_falls_back_to_legacy(self, tmp_path):
        legacy = tmp_path / "data" / "analyzed" / "2026-05-10.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("{}")

        with patch("commands.daily.PROJECT_ROOT", tmp_path):
            from commands.daily import _date_path
            result = _date_path("analyzed", "2026-05-10")
        assert result == legacy

    def test_returns_monthly_when_neither_exists(self, tmp_path):
        with patch("commands.daily.PROJECT_ROOT", tmp_path):
            from commands.daily import _date_path
            result = _date_path("analyzed", "2026-05-10")
        # Should return monthly path since it's checked first
        assert "2026-05" in str(result)
