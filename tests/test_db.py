"""Tests for lib/db.py (SQLite data layer)."""

import json
import sqlite3
from pathlib import Path

import pytest

from lib.db import (
    append_new_analyses,
    append_new_papers,
    available_dates,
    get_connection,
    init_db,
    load_analysis_index,
    load_paper_index,
    paper_id,
    paper_source_date,
    papers_for_date,
    unanalyzed_papers_for_date,
)


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    db = tmp_path / "test.db"
    schema = tmp_path / "schema.sql"
    schema.write_text("""
CREATE TABLE IF NOT EXISTS papers (
    id TEXT PRIMARY KEY, source TEXT NOT NULL DEFAULT 'arxiv',
    title TEXT, authors TEXT, abstract TEXT, categories TEXT,
    primary_category TEXT, published TEXT, updated TEXT,
    entry_url TEXT, pdf_url TEXT, source_date TEXT NOT NULL,
    venue TEXT, year TEXT, fetched_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS analyses (
    arxiv_id TEXT PRIMARY KEY, analysis_version TEXT, model TEXT,
    analyzed_at TEXT, tldr TEXT, research_motivation TEXT,
    problem TEXT, phenomenon_analysis TEXT, method TEXT,
    contributions TEXT, experiments TEXT, limitations TEXT,
    primary_area_en TEXT, primary_area TEXT, category TEXT,
    sub_area TEXT, tags TEXT, reading_priority TEXT,
    recommended_action TEXT, raw_response TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
""")
    init_db(db, schema)
    return db


class TestPaperId:
    def test_from_arxiv_id(self):
        assert paper_id({"arxiv_id": "2512.12345"}) == "2512.12345"

    def test_from_id_field(self):
        assert paper_id({"id": "2512.12345"}) == "2512.12345"

    def test_empty(self):
        assert paper_id({}) == ""


class TestPaperSourceDate:
    def test_from_source_date(self):
        assert paper_source_date({"source_date": "2025-12-30"}) == "2025-12-30"

    def test_from_published(self):
        assert paper_source_date({"published": "2025-12-30T00:00:00Z"}) == "2025-12-30"

    def test_empty(self):
        assert paper_source_date({}) == ""


class TestAppendNewPapers:
    def test_insert_new_papers(self, tmp_db):
        papers = [
            {
                "arxiv_id": "2512.00001",
                "title": "Paper A",
                "authors": ["Alice"],
                "abstract": "Abstract A",
                "categories": ["cs.CV"],
                "primary_category": "cs.CV",
                "published": "2025-12-30T00:00:00Z",
                "updated": "2025-12-30T00:00:00Z",
                "entry_url": "https://arxiv.org/abs/2512.00001",
                "pdf_url": "https://arxiv.org/pdf/2512.00001",
            }
        ]
        inserted, seen = append_new_papers(papers, source_date="2025-12-30", db_path=tmp_db)
        assert inserted == 1
        assert seen == 1

    def test_skip_duplicates(self, tmp_db):
        papers = [
            {
                "arxiv_id": "2512.00001",
                "title": "Paper A",
                "authors": [],
                "abstract": "Abstract A",
                "categories": [],
                "primary_category": "",
                "published": "",
                "updated": "",
                "entry_url": "",
                "pdf_url": "",
            }
        ]
        append_new_papers(papers, source_date="2025-12-30", db_path=tmp_db)
        inserted, _ = append_new_papers(papers, source_date="2025-12-30", db_path=tmp_db)
        assert inserted == 0

    def test_insert_multiple(self, tmp_db):
        papers = [
            {
                "arxiv_id": f"2512.0000{i}",
                "title": f"Paper {i}",
                "authors": [],
                "abstract": f"Abstract {i}",
                "categories": [],
                "primary_category": "",
                "published": "",
                "updated": "",
                "entry_url": "",
                "pdf_url": "",
            }
            for i in range(1, 4)
        ]
        inserted, _ = append_new_papers(papers, source_date="2025-12-30", db_path=tmp_db)
        assert inserted == 3


class TestAppendNewAnalyses:
    def _sample_paper(self, tmp_db):
        papers = [
            {
                "arxiv_id": "2512.00001",
                "title": "Paper A",
                "authors": [],
                "abstract": "Abstract A",
                "categories": [],
                "primary_category": "",
                "published": "",
                "updated": "",
                "entry_url": "",
                "pdf_url": "",
            }
        ]
        append_new_papers(papers, source_date="2025-12-30", db_path=tmp_db)

    def test_insert_new_analysis(self, tmp_db):
        self._sample_paper(tmp_db)
        analyses = [
            {
                "arxiv_id": "2512.00001",
                "analysis_version": "1",
                "model": "deepseek-v4-flash",
                "analyzed_at": "2025-12-30T00:00:00Z",
                "analysis": {
                    "tldr": "Test TL;DR",
                    "research_motivation": "Motivation",
                    "problem": "Problem",
                    "phenomenon_analysis": "N/A",
                    "method": "Method",
                    "contributions": ["Contrib 1"],
                    "experiments": "Exp info",
                    "limitations": ["Limit 1"],
                    "primary_area_en": "other topics in machine learning (i.e., none of the above)",
                    "primary_area": "其他 ML 主题",
                    "category": "其他",
                    "sub_area": "其他",
                    "tags": ["Test"],
                    "reading_priority": "high",
                    "recommended_action": "read_deeply",
                },
                "raw_response": "",
            }
        ]
        inserted, _ = append_new_analyses(analyses, db_path=tmp_db)
        assert inserted == 1

    def test_skip_duplicate_analysis(self, tmp_db):
        self._sample_paper(tmp_db)
        analyses = [
            {
                "arxiv_id": "2512.00001",
                "analysis_version": "1",
                "model": "deepseek-v4-flash",
                "analyzed_at": "2025-12-30T00:00:00Z",
                "analysis": {
                    "tldr": "Test",
                    "research_motivation": "",
                    "problem": "",
                    "phenomenon_analysis": "",
                    "method": "",
                    "contributions": [],
                    "experiments": "",
                    "limitations": [],
                    "primary_area_en": "",
                    "primary_area": "",
                    "category": "其他",
                    "sub_area": "其他",
                    "tags": [],
                    "reading_priority": "medium",
                    "recommended_action": "",
                },
                "raw_response": "",
            }
        ]
        append_new_analyses(analyses, db_path=tmp_db)
        inserted, _ = append_new_analyses(analyses, db_path=tmp_db)
        assert inserted == 0


class TestLoadPaperIndex:
    def test_returns_empty_when_no_papers(self, tmp_db):
        index = load_paper_index(tmp_db)
        assert index == {}

    def test_returns_all_papers(self, tmp_db):
        papers = [
            {
                "arxiv_id": "2512.00001",
                "title": "Paper A",
                "authors": ["Alice"],
                "abstract": "Abstract A",
                "categories": ["cs.CV"],
                "primary_category": "cs.CV",
                "published": "",
                "updated": "",
                "entry_url": "",
                "pdf_url": "",
            }
        ]
        append_new_papers(papers, source_date="2025-12-30", db_path=tmp_db)
        index = load_paper_index(tmp_db)
        assert "2512.00001" in index
        assert index["2512.00001"]["title"] == "Paper A"


class TestPapersForDate:
    def test_returns_papers_for_date(self, tmp_db):
        papers = [
            {
                "arxiv_id": "2512.00001",
                "title": "Paper A",
                "authors": [],
                "abstract": "",
                "categories": [],
                "primary_category": "",
                "published": "",
                "updated": "",
                "entry_url": "",
                "pdf_url": "",
            },
            {
                "arxiv_id": "2512.00002",
                "title": "Paper B",
                "authors": [],
                "abstract": "",
                "categories": [],
                "primary_category": "",
                "published": "",
                "updated": "",
                "entry_url": "",
                "pdf_url": "",
            },
        ]
        append_new_papers(papers, source_date="2025-12-30", db_path=tmp_db)
        result = papers_for_date("2025-12-30", tmp_db)
        assert len(result) == 2

    def test_returns_empty_for_other_date(self, tmp_db):
        result = papers_for_date("2025-12-31", tmp_db)
        assert result == []


class TestAvailableDates:
    def test_returns_sorted_dates(self, tmp_db):
        for i, date in enumerate(["2025-12-29", "2025-12-30", "2025-12-28"], start=1):
            append_new_papers(
                [{"arxiv_id": f"2512.0000{i}", "title": "P", "authors": [], "abstract": "", "categories": [], "primary_category": "", "published": "", "updated": "", "entry_url": "", "pdf_url": ""}],
                source_date=date,
                db_path=tmp_db,
            )
        dates = available_dates(tmp_db)
        assert dates == ["2025-12-28", "2025-12-29", "2025-12-30"]


class TestUnanalyzedPapersForDate:
    def test_returns_unanalyzed(self, tmp_db):
        papers = [
            {"arxiv_id": "2512.00001", "title": "A", "authors": [], "abstract": "", "categories": [], "primary_category": "", "published": "", "updated": "", "entry_url": "", "pdf_url": ""},
            {"arxiv_id": "2512.00002", "title": "B", "authors": [], "abstract": "", "categories": [], "primary_category": "", "published": "", "updated": "", "entry_url": "", "pdf_url": ""},
        ]
        append_new_papers(papers, source_date="2025-12-30", db_path=tmp_db)
        analyses = [
            {
                "arxiv_id": "2512.00001",
                "analysis_version": "1",
                "model": "test",
                "analyzed_at": "",
                "analysis": {"tldr": "T", "research_motivation": "", "problem": "", "phenomenon_analysis": "", "method": "", "contributions": [], "experiments": "", "limitations": [], "primary_area_en": "", "primary_area": "", "category": "其他", "sub_area": "其他", "tags": [], "reading_priority": "medium", "recommended_action": ""},
                "raw_response": "",
            }
        ]
        append_new_analyses(analyses, db_path=tmp_db)
        result = unanalyzed_papers_for_date("2025-12-30", analysis_version="1", db_path=tmp_db)
        assert len(result) == 1
        assert result[0]["id"] == "2512.00002"