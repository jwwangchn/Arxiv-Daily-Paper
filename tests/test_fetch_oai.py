"""Tests for commands/fetch.py — OAI parsing and date helpers."""

import xml.etree.ElementTree as ET

import pytest

from commands.fetch import (
    category_to_set_spec,
    date_in_range,
    date_range,
    parse_authors,
    parse_categories,
    parse_oai_record,
    safe_worker_count,
    sorted_daily_papers,
)

OAI_NS = {"oai": "http://www.openarchives.org/OAI/2.0/", "raw": "http://arxiv.org/OAI/arXivRaw/"}


def _make_oai_record(
    arxiv_id="2512.12345",
    title="Test Paper",
    authors="Alice, Bob",
    abstract="Test abstract",
    categories="cs.CV cs.AI",
    published_date="Mon, 30 Dec 2025 12:00:00 +0000",
) -> ET.Element:
    xml = f"""<oai:record xmlns:oai="http://www.openarchives.org/OAI/2.0/" xmlns:raw="http://arxiv.org/OAI/arXivRaw/">
  <oai:metadata>
    <raw:arXivRaw>
      <raw:id>{arxiv_id}</raw:id>
      <raw:title>{title}</raw:title>
      <raw:authors>{authors}</raw:authors>
      <raw:abstract>{abstract}</raw:abstract>
      <raw:categories>{categories}</raw:categories>
      <raw:version>
        <raw:date>{published_date}</raw:date>
      </raw:version>
    </raw:arXivRaw>
  </oai:metadata>
</oai:record>"""
    return ET.fromstring(xml)


class TestParseOaiRecord:
    def test_parses_basic_fields(self):
        record = _make_oai_record()
        paper = parse_oai_record(record)
        assert paper is not None
        assert paper["arxiv_id"] == "2512.12345"
        assert paper["title"] == "Test Paper"
        assert paper["authors"] == ["Alice", "Bob"]
        assert paper["abstract"] == "Test abstract"
        assert paper["categories"] == ["cs.CV", "cs.AI"]
        assert paper["primary_category"] == "cs.CV"
        assert paper["source_date"] == "2025-12-30"

    def test_returns_none_for_missing_metadata(self):
        xml = """<oai:record xmlns:oai="http://www.openarchives.org/OAI/2.0/"><oai:metadata/></oai:record>"""
        record = ET.fromstring(xml)
        assert parse_oai_record(record) is None

    def test_returns_none_for_missing_id(self):
        xml = """<oai:record xmlns:oai="http://www.openarchives.org/OAI/2.0/">
  <oai:metadata><raw:arXivRaw xmlns:raw="http://arxiv.org/OAI/arXivRaw/"/></oai:metadata>
</oai:record>"""
        record = ET.fromstring(xml)
        assert parse_oai_record(record) is None

    def test_handles_multiple_versions(self):
        xml = """<oai:record xmlns:oai="http://www.openarchives.org/OAI/2.0/" xmlns:raw="http://arxiv.org/OAI/arXivRaw/">
  <oai:metadata>
    <raw:arXivRaw>
      <raw:id>2512.12345</raw:id>
      <raw:title>Test</raw:title>
      <raw:authors>Alice</raw:authors>
      <raw:abstract>Abstract</raw:abstract>
      <raw:categories>cs.CV</raw:categories>
      <raw:version><raw:date>Mon, 29 Dec 2025 10:00:00 +0000</raw:date></raw:version>
      <raw:version><raw:date>Tue, 30 Dec 2025 12:00:00 +0000</raw:date></raw:version>
    </raw:arXivRaw>
  </oai:metadata>
</oai:record>"""
        record = ET.fromstring(xml)
        paper = parse_oai_record(record)
        assert paper is not None
        assert paper["source_date"] == "2025-12-29"
        assert paper["updated"].startswith("2025-12-30")


class TestSortedDailyPapers:
    def test_sorts_by_published_desc(self):
        papers = [
            {"arxiv_id": "1", "published": "2025-12-29T00:00:00Z"},
            {"arxiv_id": "2", "published": "2025-12-30T00:00:00Z"},
        ]
        result = sorted_daily_papers(papers)
        assert result[0]["arxiv_id"] == "2"

    def test_tiebreak_by_arxiv_id(self):
        papers = [
            {"arxiv_id": "2512.12345", "published": "2025-12-30T00:00:00Z"},
            {"arxiv_id": "2512.99999", "published": "2025-12-30T00:00:00Z"},
        ]
        result = sorted_daily_papers(papers)
        assert result[0]["arxiv_id"] == "2512.99999"

    def test_fallback_to_updated(self):
        papers = [
            {"arxiv_id": "1", "updated": "2025-12-29T00:00:00Z"},
            {"arxiv_id": "2", "updated": "2025-12-30T00:00:00Z"},
        ]
        result = sorted_daily_papers(papers)
        assert result[0]["arxiv_id"] == "2"


class TestCategoryToSetSpec:
    def test_valid_category(self):
        assert category_to_set_spec("cs.CV") == "cs:cs:CV"

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            category_to_set_spec("invalid")


class TestDateRange:
    def test_single_day(self):
        assert date_range("2025-12-30", "2025-12-30") == ["2025-12-30"]

    def test_multi_day(self):
        assert date_range("2025-12-28", "2025-12-30") == ["2025-12-28", "2025-12-29", "2025-12-30"]

    def test_start_after_end_raises(self):
        with pytest.raises(ValueError):
            date_range("2025-12-31", "2025-12-30")


class TestDateInRange:
    def test_within(self):
        assert date_in_range("2025-12-29", "2025-12-01", "2025-12-31") is True

    def test_before(self):
        assert date_in_range("2025-11-30", "2025-12-01", "2025-12-31") is False

    def test_empty(self):
        assert date_in_range("", "2025-12-01", "2025-12-31") is False


class TestSafeWorkerCount:
    def test_normal(self):
        assert safe_worker_count(2) == 2

    def test_minimum(self):
        assert safe_worker_count(0) == 1

    def test_cap(self):
        assert safe_worker_count(10) == 4