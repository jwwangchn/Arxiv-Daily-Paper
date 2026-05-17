"""Tests for commands/fetch.py (OAI-PMH fetch logic)."""

import pytest

from commands.fetch import (
    category_to_set_spec,
    date_in_range,
    date_range,
    parse_authors,
    parse_categories,
    safe_worker_count,
    sorted_daily_papers,
)


class TestDateRange:
    def test_single_day(self):
        assert date_range("2026-05-10", "2026-05-10") == ["2026-05-10"]

    def test_multi_day(self):
        result = date_range("2026-05-10", "2026-05-12")
        assert result == ["2026-05-10", "2026-05-11", "2026-05-12"]

    def test_start_after_end_raises(self):
        with pytest.raises(ValueError):
            date_range("2026-05-12", "2026-05-10")


class TestCategoryToSetSpec:
    def test_valid_category(self):
        assert category_to_set_spec("cs.CV") == "cs:cs:CV"

    def test_ai_category(self):
        assert category_to_set_spec("cs.AI") == "cs:cs:AI"

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            category_to_set_spec("invalid")


class TestParseAuthors:
    def test_comma_separated(self):
        result = parse_authors("Alice, Bob, Charlie")
        assert result == ["Alice", "Bob", "Charlie"]

    def test_trims_whitespace(self):
        result = parse_authors("  Alice  ,  Bob  ")
        assert result == ["Alice", "Bob"]

    def test_skips_empty(self):
        result = parse_authors("Alice, , Bob")
        assert result == ["Alice", "Bob"]

    def test_single_author(self):
        assert parse_authors("Alice") == ["Alice"]


class TestParseCategories:
    def test_space_separated(self):
        assert parse_categories("cs.CV cs.AI cs.LG") == ["cs.CV", "cs.AI", "cs.LG"]

    def test_single(self):
        assert parse_categories("cs.CV") == ["cs.CV"]

    def test_trims_whitespace(self):
        assert parse_categories(" cs.CV  cs.AI ") == ["cs.CV", "cs.AI"]


class TestDateInRange:
    def test_within_range(self):
        assert date_in_range("2026-05-10", "2026-05-01", "2026-05-31") is True

    def test_at_start(self):
        assert date_in_range("2026-05-01", "2026-05-01", "2026-05-31") is True

    def test_at_end(self):
        assert date_in_range("2026-05-31", "2026-05-01", "2026-05-31") is True

    def test_before_range(self):
        assert date_in_range("2026-04-30", "2026-05-01", "2026-05-31") is False

    def test_after_range(self):
        assert date_in_range("2026-06-01", "2026-05-01", "2026-05-31") is False

    def test_empty_value(self):
        assert date_in_range("", "2026-05-01", "2026-05-31") is False


class TestSortedDailyPapers:
    def test_sorts_by_published_desc(self):
        papers = [
            {"arxiv_id": "1", "published": "2026-05-10T00:00:00Z"},
            {"arxiv_id": "2", "published": "2026-05-11T00:00:00Z"},
        ]
        result = sorted_daily_papers(papers)
        assert result[0]["arxiv_id"] == "2"

    def test_tiebreak_by_arxiv_id(self):
        papers = [
            {"arxiv_id": "2605.12345", "published": "2026-05-10T00:00:00Z"},
            {"arxiv_id": "2605.99999", "published": "2026-05-10T00:00:00Z"},
        ]
        result = sorted_daily_papers(papers)
        assert result[0]["arxiv_id"] == "2605.99999"


class TestSafeWorkerCount:
    def test_normal_value(self):
        assert safe_worker_count(2) == 2

    def test_minimum_1(self):
        assert safe_worker_count(0) == 1
        assert safe_worker_count(-1) == 1

    def test_caps_at_4(self):
        assert safe_worker_count(8) == 4