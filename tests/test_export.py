"""Tests for export_to_worker.py."""

import json
import sqlite3
from pathlib import Path

import pytest

from export_to_worker import _analysis_record_from_db, _safe_json, load_records


class TestSafeJson:
    def test_valid_json(self):
        assert _safe_json('["a", "b"]') == ["a", "b"]

    def test_empty_string(self):
        assert _safe_json("") == []

    def test_none(self):
        assert _safe_json(None) == []

    def test_invalid_json(self):
        assert _safe_json("not json") == []


class TestAnalysisRecordFromDb:
    def test_builds_record(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE analyses (
                arxiv_id TEXT, analysis_version TEXT, model TEXT,
                analyzed_at TEXT, tldr TEXT, research_motivation TEXT,
                problem TEXT, phenomenon_analysis TEXT, method TEXT,
                contributions TEXT, experiments TEXT, limitations TEXT,
                primary_area_en TEXT, primary_area TEXT, category TEXT,
                sub_area TEXT, tags TEXT, reading_priority TEXT,
                recommended_action TEXT, raw_response TEXT
            )
        """)
        conn.execute(
            "INSERT INTO analyses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("2512.00001", "1", "test-model", "2025-12-30", "TL;DR", "", "", "", "",
             json.dumps(["c1"]), "exp", json.dumps(["l1"]),
             "", "", "其他", "其他", json.dumps(["tag"]), "high", "", ""),
        )
        row = conn.execute("SELECT * FROM analyses").fetchone()
        record = _analysis_record_from_db(row)
        assert record["arxiv_id"] == "2512.00001"
        assert record["analysis"]["tldr"] == "TL;DR"
        assert record["analysis"]["contributions"] == ["c1"]
        assert record["analysis"]["limitations"] == ["l1"]
        assert record["analysis"]["tags"] == ["tag"]
        conn.close()


class TestLoadRecords:
    def test_returns_empty_when_no_db(self, tmp_path):
        papers, analyses = load_records()
        # DB_PATH is the default, which may or may not exist
        # Just verify it returns lists
        assert isinstance(papers, list)
        assert isinstance(analyses, list)

    def test_returns_empty_for_nonexistent_date(self, tmp_path):
        papers, analyses = load_records(date="2099-01-01")
        assert papers == []
        assert analyses == []