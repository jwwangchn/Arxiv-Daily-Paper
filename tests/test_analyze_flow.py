"""Tests for commands/analyze.py — additional coverage for _extract_analyses and analyze_date flow."""

import os
from unittest.mock import patch, MagicMock

import pytest

from commands.analyze import (
    _extract_analyses,
    analyze_one_paper,
    ModelJsonError,
)


class TestExtractAnalyses:
    def test_extracts_valid_analyses(self):
        papers = [
            {
                "arxiv_id": "2512.00001",
                "analysis_version": "1",
                "analyzed_at": "2025-12-30T00:00:00Z",
                "analysis": {"tldr": "Test"},
                "raw_response": "",
            },
            None,
            {
                "arxiv_id": "2512.00002",
                "analysis_version": "2",
                "analyzed_at": "",
                "analysis": {"tldr": "Test 2"},
                "raw_response": "raw",
            },
        ]
        with patch.dict(os.environ, {"DEEPSEEK_MODEL": "test-model"}, clear=False):
            result = _extract_analyses(papers)
        assert len(result) == 2
        assert result[0]["arxiv_id"] == "2512.00001"
        assert result[0]["model"] == "test-model"
        assert result[1]["arxiv_id"] == "2512.00002"
        assert result[1]["raw_response"] == "raw"

    def test_skips_none_entries(self):
        papers = [None, None]
        result = _extract_analyses(papers)
        assert result == []

    def test_skips_missing_arxiv_id(self):
        papers = [{"arxiv_id": "", "analysis": {}}]
        result = _extract_analyses(papers)
        assert result == []


class TestAnalyzeOnePaper:
    def test_successful_analysis(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices[0].message.content = '{"tldr": "test", "reading_priority": "high", "research_motivation": "", "problem": "", "phenomenon_analysis": "", "method": "", "contributions": [], "experiments": "", "limitations": [], "primary_area_en": "other topics in machine learning (i.e., none of the above)", "primary_area": "其他 ML 主题", "category": "其他", "sub_area": "其他", "tags": [], "recommended_action": ""}'
        mock_client.chat.completions.create.return_value = mock_response

        paper = {"arxiv_id": "2512.00001", "title": "Test", "abstract": "Abstract"}
        result = analyze_one_paper(mock_client, paper, "test-model")
        assert "analysis" in result
        assert result["analysis"]["tldr"] == "test"

    def test_json_parse_error(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = ModelJsonError("bad json", "not json")

        paper = {"arxiv_id": "2512.00001", "title": "Test", "abstract": "Abstract"}
        result = analyze_one_paper(mock_client, paper, "test-model")
        assert "analysis_error" in result
        assert "raw_response" in result

    def test_general_exception(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("API down")

        paper = {"arxiv_id": "2512.00001", "title": "Test", "abstract": "Abstract"}
        result = analyze_one_paper(mock_client, paper, "test-model")
        assert "analysis_error" in result