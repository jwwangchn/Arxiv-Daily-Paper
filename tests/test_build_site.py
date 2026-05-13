"""Tests for build_site.py (→ 04_build.py after refactor).

Covers: h, cjk_spacing, ht, month_key, priority_rank,
        paper_time_rank, anchor, list_items, paper_tags,
        sorted_papers, sorted_topic_groups, sorted_category_groups,
        group_papers, legacy_priority_for_site, paper_for_site,
        canonical_area, canonical_category, normalize_label.
"""

import pytest


# --- Imports ---

from commands.build import (
    anchor,
    cjk_spacing,
    group_papers,
    h,
    ht,
    legacy_priority_for_site,
    list_items,
    month_key,
    paper_for_site,
    paper_tags,
    paper_time_rank,
    priority_rank,
    sorted_category_groups,
    sorted_papers,
    sorted_topic_groups,
    canonical_area,
    canonical_category,
    normalize_label,
)


# --- h (HTML escape) ---

class TestH:
    def test_escapes_quotes(self):
        assert h('a "b"') == "a &quot;b&quot;"

    def test_escapes_ampersand(self):
        assert h("a & b") == "a &amp; b"

    def test_escapes_lt_gt(self):
        assert h("<div>") == "&lt;div&gt;"

    def test_none_to_empty(self):
        assert h(None) == ""

    def test_number_to_string(self):
        assert h(42) == "42"


# --- cjk_spacing ---

class TestCjkSpacing:
    def test_adds_space_cjk_to_ascii(self):
        result = cjk_spacing("测试ABC")
        assert "测试 ABC" == result

    def test_adds_space_ascii_to_cjk(self):
        result = cjk_spacing("ABC测试")
        assert "ABC 测试" == result

    def test_no_change_for_pure_cjk(self):
        assert cjk_spacing("中文测试") == "中文测试"

    def test_no_change_for_pure_ascii(self):
        assert cjk_spacing("hello world") == "hello world"


# --- ht (HTML escape + CJK spacing) ---

class TestHt:
    def test_both_escaping_and_spacing(self):
        result = ht('模型 "VLM"')
        assert "&quot;" in result
        assert "VLM" in result


# --- month_key ---

class TestMonthKey:
    def test_extracts_ym(self):
        assert month_key("2026-05-10") == "2026-05"

    def test_short_date(self):
        # month_key just takes first 7 chars: "2026-05"[:7] = "2026-05"
        assert month_key("2026-05") == "2026-05"


# --- priority_rank ---

class TestPriorityRank:
    def test_high_is_0(self):
        assert priority_rank({"analysis": {"reading_priority": "high"}}) == 0

    def test_medium_is_1(self):
        assert priority_rank({"analysis": {"reading_priority": "medium"}}) == 1

    def test_low_is_2(self):
        assert priority_rank({"analysis": {"reading_priority": "low"}}) == 2

    def test_unknown_is_3(self):
        assert priority_rank({"analysis": {"reading_priority": "weird"}}) == 3

    def test_no_analysis_is_3(self):
        assert priority_rank({}) == 3


# --- paper_time_rank ---

class TestPaperTimeRank:
    def test_uses_updated_field(self):
        paper = {"updated": "2026-05-10T00:00:00Z"}
        paper2 = {"updated": "2026-05-11T00:00:00Z"}
        # paper_time_rank returns -timestamp, so newer = more negative = smaller
        assert paper_time_rank(paper2) < paper_time_rank(paper)

    def test_falls_back_to_arxiv_id(self):
        paper = {"arxiv_id": "2605.12345"}
        result = paper_time_rank(paper)
        assert result < 0  # negative = higher rank for larger IDs

    def test_returns_zero_for_garbage(self):
        paper = {"arxiv_id": "not_a_real_id"}
        # All non-numeric stripped → empty → ValueError → 0.0
        # But "not_a_real_id" strips to "" since no digits
        assert paper_time_rank(paper) == 0.0


# --- anchor ---

class TestAnchor:
    def test_basic_slug(self):
        assert anchor("Vision Language Model") == "Vision-Language-Model"

    def test_strips_special_chars(self):
        assert anchor("test: paper (2026)") == "test-paper-2026"

    def test_preserves_cjk(self):
        assert anchor("高效学习") == "高效学习"

    def test_empty_returns_section(self):
        assert anchor("") == "section"

    def test_strips_leading_trailing_dashes(self):
        assert anchor("--test--") == "test"


# --- list_items ---

class TestListItems:
    def test_empty_returns_muted(self):
        result = list_items([])
        assert "muted" in result

    def test_escapes_html(self):
        result = list_items(["<script>alert(1)</script>"])
        assert "&lt;script&gt;" in result

    def test_generates_li(self):
        result = list_items(["A", "B"])
        assert "<li>A</li>" in result
        assert "<li>B</li>" in result


# --- paper_tags ---

class TestPaperTags:
    def test_extracts_tags(self):
        paper = {"analysis": {"tags": ["VLM", "DiT"]}}
        assert paper_tags(paper) == ["VLM", "DiT"]

    def test_no_analysis(self):
        assert paper_tags({}) == []

    def test_filters_empty_tags(self):
        paper = {"analysis": {"tags": ["VLM", "", None]}}
        assert paper_tags(paper) == ["VLM"]


# --- sorted_papers ---

class TestSortedPapers:
    def test_high_priority_first(self):
        papers = [
            {"arxiv_id": "2605.00001", "analysis": {"reading_priority": "low"}},
            {"arxiv_id": "2605.00002", "analysis": {"reading_priority": "high"}},
            {"arxiv_id": "2605.00003", "analysis": {"reading_priority": "medium"}},
        ]
        result = sorted_papers(papers)
        assert result[0]["arxiv_id"] == "2605.00002"

    def test_newer_first_within_same_priority(self):
        papers = [
            {"arxiv_id": "2605.00001", "analysis": {"reading_priority": "high"}, "updated": "2026-05-10T00:00:00Z"},
            {"arxiv_id": "2605.00002", "analysis": {"reading_priority": "high"}, "updated": "2026-05-11T00:00:00Z"},
        ]
        result = sorted_papers(papers)
        assert result[0]["arxiv_id"] == "2605.00002"


# --- sorted_topic_groups ---

class TestSortedTopicGroups:
    def test_largest_topic_first(self):
        groups = {
            "Small": {"cat1": [{}]},
            "Large": {"cat1": [{}, {}, {}], "cat2": [{}]},
        }
        result = sorted_topic_groups(groups)
        assert result[0][0] == "Large"

    def test_alphabetical_tiebreak(self):
        groups = {
            "Beta": {"cat1": [{}]},
            "Alpha": {"cat1": [{}]},
        }
        result = sorted_topic_groups(groups)
        assert result[0][0] == "Alpha"


# --- sorted_category_groups ---

class TestSortedCategoryGroups:
    def test_largest_category_first(self):
        groups = {
            "Small": [{}],
            "Large": [{}, {}, {}],
        }
        result = sorted_category_groups(groups)
        assert result[0][0] == "Large"


# --- group_papers ---

class TestGroupPapers:
    def test_groups_by_area_and_category(self, sample_analyzed_paper):
        # Override the sample analysis to use an area that exists in taxonomy
        sample_analyzed_paper["analysis"]["primary_area"] = "其他 ML 主题"
        sample_analyzed_paper["analysis"]["category"] = "其他"
        result = group_papers([sample_analyzed_paper])
        assert "其他 ML 主题" in result
        assert "其他" in result["其他 ML 主题"]
        assert len(result["其他 ML 主题"]["其他"]) == 1


# --- legacy_priority_for_site ---

class TestLegacyPriorityForSite:
    def test_must_read_to_high(self):
        assert legacy_priority_for_site({"reading_priority": "must_read"}) == "high"

    def test_recommended_to_medium(self):
        assert legacy_priority_for_site({"reading_priority": "recommended"}) == "medium"

    def test_skim_to_medium(self):
        assert legacy_priority_for_site({"reading_priority": "skim"}) == "medium"

    def test_low_priority_to_low(self):
        assert legacy_priority_for_site({"reading_priority": "low_priority"}) == "low"

    def test_unknown_defaults_to_medium(self):
        assert legacy_priority_for_site({"reading_priority": "bogus"}) == "medium"

    def test_passthrough_existing_legacy(self):
        assert legacy_priority_for_site({"reading_priority": "high"}) == "high"


# --- paper_for_site ---

class TestPaperForSite:
    def test_backfills_legacy_analysis(self, sample_paper):
        legacy = {sample_paper["arxiv_id"]: {"analysis": {"tldr": "legacy", "reading_priority": "recommended"}}}
        result = paper_for_site(sample_paper, legacy)
        assert result["analysis"]["tldr"] == "legacy"

    def test_does_not_overwrite_existing_analysis(self, sample_analyzed_paper):
        legacy = {sample_analyzed_paper["arxiv_id"]: {"analysis": {"tldr": "wrong"}}}
        result = paper_for_site(sample_analyzed_paper, legacy)
        assert result["analysis"]["tldr"] == sample_analyzed_paper["analysis"]["tldr"]

    def test_sets_legacy_priority(self, sample_analyzed_paper):
        result = paper_for_site(sample_analyzed_paper, {})
        assert result["analysis"]["reading_priority"] == "high"  # must_read→high

    def test_removes_score_fields(self, sample_analyzed_paper):
        result = paper_for_site(sample_analyzed_paper, {})
        for key in ("novelty", "technical_depth", "impact", "relevance", "score_raw", "score", "reason"):
            assert key not in result["analysis"]


# --- normalize_label ---

class TestNormalizeLabel:
    def test_removes_spaces(self):
        assert normalize_label("高效 学习") == "高效学习"

    def test_lowercases(self):
        assert normalize_label("ABC") == "abc"

    def test_converts_fullwidth_colon(self):
        assert normalize_label("应用：CV") == "应用:cv"


# --- canonical_area / canonical_category ---

class TestCanonicalAreaCategory:
    def test_canonical_area_direct_match(self):
        # "其他 ML 主题" exists in taxonomy
        result = canonical_area("其他 ML 主题")
        assert result == "其他 ML 主题"

    def test_canonical_area_legacy_alias(self):
        result = canonical_area("医学与科学AI")
        assert result == "应用: CV/音频/语言等"

    def test_canonical_area_empty_for_unknown(self):
        result = canonical_area("nonexistent_area_xyz")
        assert result == ""

    def test_canonical_category_direct_match(self):
        result = canonical_category("其他", "其他 ML 主题")
        assert result == "其他"

    def test_canonical_category_default_for_unknown(self):
        result = canonical_category("nonexistent_cat_xyz", "高效学习方法")
        assert result == "其他"
