from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def ensure_dirs() -> None:
    for path in [
        PROJECT_ROOT / "data" / "archive",
    ]:
        path.mkdir(parents=True, exist_ok=True)


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def today_iso() -> str:
    return date.today().isoformat()


def normalize_space(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_date(value: str | None) -> str:
    if value:
        datetime.strptime(value, "%Y-%m-%d")
        return value
    return today_iso()


def paper_matches_topics(paper: dict[str, Any], topics: dict[str, Any]) -> list[str]:
    haystack = f"{paper.get('title', '')} {paper.get('abstract', '')}".lower()
    matched: list[str] = []
    for topic in topics.values():
        name = topic.get("name")
        keywords = topic.get("keywords", [])
        if name and any(str(keyword).lower() in haystack for keyword in keywords):
            matched.append(str(name))
    return matched
