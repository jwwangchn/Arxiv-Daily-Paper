"""Shared fixtures and path setup for all tests."""

import sys
from pathlib import Path

import pytest

# Ensure scripts/ is importable (tests run from project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """Create a temporary data directory with standard subfolders."""
    d = tmp_path / "data"
    (d / "archive").mkdir(parents=True)
    return d


@pytest.fixture
def sample_paper() -> dict:
    """A minimal paper dict for testing."""
    return {
        "arxiv_id": "2605.12345",
        "title": "Test Paper Title",
        "authors": ["Alice", "Bob"],
        "abstract": "This is a test abstract about vision-language models.",
        "categories": ["cs.CV", "cs.AI"],
        "primary_category": "cs.CV",
        "published": "2026-05-10T00:00:00Z",
        "updated": "2026-05-10T00:00:00Z",
        "entry_url": "https://arxiv.org/abs/2605.12345",
        "pdf_url": "https://arxiv.org/pdf/2605.12345",
    }


@pytest.fixture
def sample_analysis() -> dict:
    """A minimal analysis dict for testing."""
    return {
        "tldr": "Test paper proposes a new VLM method.",
        "research_motivation": "Existing VLMs lack efficiency.",
        "problem": "Slow inference for large models.",
        "phenomenon_analysis": "摘要未提供明确现象分析。",
        "method": "A new efficient fine-tuning approach.",
        "contributions": ["Method A", "Benchmark B"],
        "experiments": "Evaluated on COCO and VQA.",
        "limitations": ["Limited to English", "No ablation study"],
        "primary_area_en": "efficient methods for machine learning",
        "primary_area": "高效学习方法",
        "category": "模型压缩与加速",
        "sub_area": "模型压缩与加速",
        "tags": ["VLM", "Efficiency"],
        "recommended_action": "read_deeply",
        "reading_priority": "must_read",
    }


@pytest.fixture
def sample_analyzed_paper(sample_paper: dict, sample_analysis: dict) -> dict:
    """A paper with analysis attached."""
    paper = dict(sample_paper)
    paper["analysis"] = dict(sample_analysis)
    return paper


@pytest.fixture
def sample_taxonomy() -> dict:
    """A minimal ICLR-style taxonomy."""
    return {
        "areas": [
            {
                "primary_area_en": "efficient methods for machine learning",
                "primary_area": "高效学习方法",
                "categories": ["模型压缩与加速", "蒸馏与量化", "稀疏化与剪枝"],
            },
            {
                "primary_area_en": "other topics in machine learning (i.e., none of the above)",
                "primary_area": "其他 ML 主题",
                "categories": ["其他"],
            },
        ],
    }


@pytest.fixture
def sample_topics() -> dict:
    """Topic config from config.yaml."""
    return {
        "vlm": {
            "name": "Vision-Language Model",
            "keywords": ["vision-language", "multimodal", "VLM", "MLLM"],
        },
        "video_generation": {
            "name": "Video Generation",
            "keywords": ["video generation", "text-to-video", "DiT"],
        },
    }


@pytest.fixture
def sample_config() -> dict:
    """A minimal config dict."""
    return {
        "site": {"title": "Test arXiv Daily", "subtitle": "Test"},
        "arxiv": {
            "categories": ["cs.CV", "cs.AI"],
            "max_papers": 30,
        },
        "topics": {
            "vlm": {
                "name": "Vision-Language Model",
                "keywords": ["vision-language", "multimodal", "VLM"],
            },
        },
    }