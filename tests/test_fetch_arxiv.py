"""Tests for fetch_arxiv.py (→ 02_fetch.py after refactor).

Covers: date_range, category_to_set_spec, parse_authors, parse_categories,
        date_in_range, sorted_daily_papers, strip_version, strip_html,
        extract_browse_headings, candidate_browse_urls, safe_worker_count.
"""

import pytest


# --- Imports ---

from commands.fetch import (
    candidate_browse_urls,
    category_to_set_spec,
    date_in_range,
    date_range,
    extract_browse_headings,
    parse_authors,
    parse_categories,
    sorted_daily_papers,
    strip_html,
    strip_version,
    safe_worker_count,
)


# --- date_range ---

class TestDateRange:
    def test_single_day(self):
        assert date_range("2026-05-10", "2026-05-10") == ["2026-05-10"]

    def test_multi_day(self):
        result = date_range("2026-05-10", "2026-05-12")
        assert result == ["2026-05-10", "2026-05-11", "2026-05-12"]

    def test_start_after_end_raises(self):
        with pytest.raises(ValueError):
            date_range("2026-05-12", "2026-05-10")


# --- category_to_set_spec ---

class TestCategoryToSetSpec:
    def test_valid_category(self):
        assert category_to_set_spec("cs.CV") == "cs:cs:CV"

    def test_ai_category(self):
        assert category_to_set_spec("cs.AI") == "cs:cs:AI"

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            category_to_set_spec("invalid")


# --- parse_authors ---

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


# --- parse_categories ---

class TestParseCategories:
    def test_space_separated(self):
        assert parse_categories("cs.CV cs.AI cs.LG") == ["cs.CV", "cs.AI", "cs.LG"]

    def test_single(self):
        assert parse_categories("cs.CV") == ["cs.CV"]

    def test_trims_whitespace(self):
        assert parse_categories(" cs.CV  cs.AI ") == ["cs.CV", "cs.AI"]


# --- date_in_range ---

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


# --- sorted_daily_papers ---

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


# --- strip_version ---

class TestStripVersion:
    def test_removes_version(self):
        assert strip_version("2605.12345v1") == "2605.12345"

    def test_removes_higher_version(self):
        assert strip_version("2605.12345v12") == "2605.12345"

    def test_no_version_unchanged(self):
        assert strip_version("2605.12345") == "2605.12345"


# --- strip_html ---

class TestStripHtml:
    def test_removes_tags(self):
        result = strip_html("<p>hello <b>world</b></p>")
        assert "hello" in result
        assert "world" in result
        assert "<p>" not in result

    def test_removes_descriptor_spans(self):
        html = '<span class="descriptor">Title:</span> My Paper'
        result = strip_html(html)
        assert "Title:" not in result
        assert "My Paper" in result

    def test_unescapes_html_entities(self):
        result = strip_html("a &amp; b")
        assert result == "a & b"

    def test_collapses_whitespace(self):
        result = strip_html("hello\n\n\nworld")
        assert result == "hello world"


# --- extract_browse_headings ---

class TestExtractBrowseHeadings:
    def test_extracts_h3(self):
        html = "<h3>Thu, 7 May 2026 (showing 116 of 116 entries )</h3>"
        result = extract_browse_headings(html)
        assert "Thu, 7 May 2026" in result[0]
        assert "116 of 116" in result[0]

    def test_multiple_headings(self):
        html = "<h3>Wed, 6 May 2026</h3><h3>Thu, 7 May 2026</h3>"
        result = extract_browse_headings(html)
        assert len(result) == 2


# --- candidate_browse_urls ---

class TestCandidateBrowseUrls:
    def test_monthly_first(self):
        urls = candidate_browse_urls("cs.CV", "2026-05-10")
        assert "list/cs.CV/2026-05" in urls[0]
        assert "?show=all" in urls[0]

    def test_recent_fallback(self):
        urls = candidate_browse_urls("cs.CV", "2026-05-10")
        assert "list/cs.CV/recent" in urls[1]
        assert "show=2000" in urls[1]


# --- safe_worker_count ---

class TestSafeWorkerCount:
    def test_normal_value(self):
        assert safe_worker_count(2) == 2

    def test_minimum_1(self):
        assert safe_worker_count(0) == 1
        assert safe_worker_count(-1) == 1

    def test_caps_at_4(self):
        assert safe_worker_count(8) == 4


# --- merge_papers ---

from commands.fetch import merge_papers


class TestMergePapers:
    def test_new_papers_only(self):
        new = [{"arxiv_id": "2605.00001", "title": "A"}]
        result = merge_papers([], new)
        assert len(result) == 1
        assert result[0]["arxiv_id"] == "2605.00001"

    def test_existing_papers_only(self):
        existing = [{"arxiv_id": "2605.00001", "title": "A"}]
        result = merge_papers(existing, [])
        assert len(result) == 1

    def test_preserves_existing_fields(self):
        existing = [{"arxiv_id": "2605.00001", "title": "Old Title", "abstract": "Old abstract"}]
        new = [{"arxiv_id": "2605.00001", "title": "New Title"}]
        result = merge_papers(existing, new)
        assert result[0]["title"] == "Old Title"

    def test_fills_missing_fields(self):
        existing = [{"arxiv_id": "2605.00001", "title": "Title", "abstract": ""}]
        new = [{"arxiv_id": "2605.00001", "abstract": "New abstract"}]
        result = merge_papers(existing, new)
        assert result[0]["abstract"] == "New abstract"

    def test_adds_new_ids(self):
        existing = [{"arxiv_id": "2605.00001", "title": "A"}]
        new = [{"arxiv_id": "2605.00002", "title": "B"}]
        result = merge_papers(existing, new)
        ids = {p["arxiv_id"] for p in result}
        assert ids == {"2605.00001", "2605.00002"}

    def test_no_duplicates(self):
        existing = [{"arxiv_id": "2605.00001", "title": "A"}]
        new = [
            {"arxiv_id": "2605.00001", "title": "New A"},
            {"arxiv_id": "2605.00002", "title": "B"},
        ]
        result = merge_papers(existing, new)
        ids = [p["arxiv_id"] for p in result]
        assert len(ids) == len(set(ids))
