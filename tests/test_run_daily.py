"""Tests for commands.daily.py."""

from unittest.mock import patch

import pytest


class TestIsFullyAnalyzed:
    def test_all_analyzed(self):
        papers = [{"arxiv_id": "2605.00001"}, {"arxiv_id": "2605.00002"}]
        with patch(
            "commands.daily.load_analysis_index",
            return_value={"2605.00001": {}, "2605.00002": {}},
        ):
            from commands.daily import is_fully_analyzed

            assert is_fully_analyzed("2026-05-10", papers) is True

    def test_missing_analysis(self):
        papers = [{"arxiv_id": "2605.00001"}, {"arxiv_id": "2605.00002"}]
        with patch("commands.daily.load_analysis_index", return_value={"2605.00001": {}}):
            from commands.daily import is_fully_analyzed

            assert is_fully_analyzed("2026-05-10", papers) is False

    def test_empty_papers(self):
        with patch("commands.daily.load_analysis_index", return_value={}):
            from commands.daily import is_fully_analyzed

            assert is_fully_analyzed("2026-05-10", []) is False


class TestLoadExistingPapers:
    def test_finds_archive_papers(self):
        with patch("commands.daily.papers_for_date", return_value=[{"arxiv_id": "2605.00001"}]):
            from commands.daily import load_existing_papers

            papers, source = load_existing_papers("2026-05-10")

        assert papers == [{"arxiv_id": "2605.00001"}]
        assert source == "archive"

    def test_returns_empty_when_not_found(self):
        with patch("commands.daily.papers_for_date", return_value=[]):
            from commands.daily import load_existing_papers

            papers, source = load_existing_papers("2026-05-10")

        assert papers == []
        assert source == ""


class TestFindLatestExistingOrFetch:
    def test_finds_existing_archive_papers(self):
        with patch("commands.daily.papers_for_date", return_value=[{"arxiv_id": "2605.00001"}]), patch(
            "commands.daily.fetch_papers"
        ) as mock_fetch:
            from commands.daily import find_latest_existing_or_fetch

            date, papers, source = find_latest_existing_or_fetch(
                ["cs.CV"], 30, lookback_days=14, start_date="2026-05-10"
            )

        assert date == "2026-05-10"
        assert len(papers) == 1
        assert source == "archive"
        mock_fetch.assert_not_called()

    def test_falls_back_to_fetch_and_appends_archive(self):
        fetched = [{"arxiv_id": "2605.00001"}]
        with patch("commands.daily.papers_for_date", return_value=[]), patch(
            "commands.daily.fetch_papers", return_value=fetched
        ) as mock_fetch, patch("commands.daily.append_new_papers") as mock_append, patch(
            "commands.daily.load_paper_index", return_value={}
        ):
            from commands.daily import find_latest_existing_or_fetch

            date, papers, source = find_latest_existing_or_fetch(
                ["cs.CV"], 30, lookback_days=14, start_date="2026-05-10"
            )

        assert date == "2026-05-10"
        assert papers == fetched
        assert source == "fetched"
        mock_fetch.assert_called_once()
        mock_append.assert_called_once()

    def test_walks_backwards(self):
        def existing(date: str):
            return [{"arxiv_id": "2605.00008"}] if date == "2026-05-08" else []

        with patch("commands.daily.papers_for_date", side_effect=existing), patch(
            "commands.daily.fetch_papers", return_value=[]
        ):
            from commands.daily import find_latest_existing_or_fetch

            date, papers, source = find_latest_existing_or_fetch(
                ["cs.CV"], 30, lookback_days=14, start_date="2026-05-12"
            )

        assert date == "2026-05-08"
        assert papers == [{"arxiv_id": "2605.00008"}]
        assert source == "archive"

    def test_raises_when_nothing_found(self):
        with patch("commands.daily.papers_for_date", return_value=[]), patch(
            "commands.daily.fetch_papers", return_value=[]
        ):
            from commands.daily import find_latest_existing_or_fetch

            with pytest.raises(RuntimeError, match="No arXiv papers"):
                find_latest_existing_or_fetch(["cs.CV"], 30, lookback_days=2, start_date="2026-05-10")
