"""Taxonomy loading, indexing, and normalization utilities.

Shared by commands/analyze.py and commands/build.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lib.config import PROJECT_ROOT, read_json

TAXONOMY_PATH = PROJECT_ROOT / "data" / "iclr_taxonomy.json"


def normalize_label_for_taxonomy(value: str) -> str:
    """Normalize a taxonomy label for comparison (used by analysis)."""
    return "".join(str(value or "").replace("：", ":").lower().split())


def normalize_label_for_site(value: str) -> str:
    """Normalize a label for site rendering (removes all whitespace)."""
    import re
    return re.sub(r"\s+", "", value.replace("：", ":").strip().lower())


def load_taxonomy() -> dict[str, Any]:
    if not TAXONOMY_PATH.exists():
        return {"areas": []}
    return read_json(TAXONOMY_PATH)


def load_taxonomy_prompt() -> str:
    taxonomy = load_taxonomy()
    lines: list[str] = []
    for area in taxonomy.get("areas", []):
        primary_area_en = area.get("primary_area_en", "")
        primary_area = area.get("primary_area", "")
        categories = "；".join(area.get("categories", []))
        lines.append(f"- {primary_area_en} | {primary_area}: {categories}")
    return "\n".join(lines)


def taxonomy_indexes() -> tuple[dict[str, dict[str, Any]], dict[str, str], dict[str, str], dict[str, set[str]]]:
    taxonomy = load_taxonomy()
    area_index: dict[str, dict[str, Any]] = {}
    category_index: dict[str, str] = {}
    category_candidates: dict[str, set[str]] = {}
    area_categories: dict[str, set[str]] = {}
    for area in taxonomy.get("areas", []):
        primary_area = str(area.get("primary_area") or "").strip()
        if not primary_area:
            continue
        area_index[normalize_label_for_taxonomy(primary_area)] = area
        area_categories[primary_area] = set()
        for category in area.get("categories", []):
            category_name = str(category).strip()
            category_key = normalize_label_for_taxonomy(category_name)
            category_index[category_key] = category_name
            category_candidates.setdefault(category_key, set()).add(primary_area)
            area_categories[primary_area].add(category_key)
    category_area_index = {
        category: next(iter(areas)) for category, areas in category_candidates.items() if len(areas) == 1
    }
    return area_index, category_index, category_area_index, area_categories


def taxonomy_area_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for area in load_taxonomy().get("areas", []):
        primary = str(area.get("primary_area") or "").strip()
        if primary:
            mapping[normalize_label_for_site(primary)] = primary
    return mapping


def taxonomy_category_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for area in load_taxonomy().get("areas", []):
        for category in area.get("categories", []):
            category_name = str(category).strip()
            if category_name:
                mapping[normalize_label_for_site(category_name)] = category_name
    return mapping


def taxonomy_category_area_map() -> dict[str, str]:
    candidates: dict[str, set[str]] = {}
    for area in load_taxonomy().get("areas", []):
        primary = str(area.get("primary_area") or "").strip()
        for category in area.get("categories", []):
            candidates.setdefault(normalize_label_for_site(str(category)), set()).add(primary)
    return {category: next(iter(areas)) for category, areas in candidates.items() if len(areas) == 1}


def taxonomy_area_categories_map() -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}
    for area in load_taxonomy().get("areas", []):
        primary = str(area.get("primary_area") or "").strip()
        if not primary:
            continue
        mapping[primary] = {normalize_label_for_site(str(category)) for category in area.get("categories", [])}
    return mapping


# Pre-computed indexes (used by commands/analyze.py at module load time)
AREA_INDEX, CATEGORY_INDEX, CATEGORY_AREA_INDEX, AREA_CATEGORIES_MAP = taxonomy_indexes()
