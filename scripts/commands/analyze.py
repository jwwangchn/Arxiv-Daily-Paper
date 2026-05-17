from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import os
from pathlib import Path
from typing import Any

from openai import OpenAI

from lib.config import PROJECT_ROOT, ensure_dirs, parse_date, read_json, setup_logging
from lib.db import DB_PATH, append_new_analyses, load_analysis_index, load_paper_index, paper_id, papers_for_date
from lib.progress import progress_bar

LOGGER = logging.getLogger("analyze_deepseek")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_DEEPSEEK_CONCURRENCY = 2
MAX_DEEPSEEK_CONCURRENCY = 4
TAXONOMY_PATH = PROJECT_ROOT / "data" / "iclr_taxonomy.json"


SYSTEM_PROMPT_TEMPLATE = """你是一个严谨的机器学习论文导读助手。请只根据论文标题和摘要生成中文导读，不要编造摘要中不存在的实验结论。如果摘要没有提到实验结果，请明确写"摘要未提供具体实验结果"。输出必须是合法 JSON。

分类体系来自 ICLR 2026 官方研究方向整理。你必须从下列 taxonomy 中选择最匹配的一级分类和二级分类，不要发明新类别：
{taxonomy}

请输出以下 JSON schema：
{{
  "tldr": "TL;DR，1 句中文极简导读",
  "research_motivation": "研究动机：为什么这个问题值得研究，背景痛点是什么",
  "problem": "论文要解决的问题",
  "phenomenon_analysis": "现象分析：摘要中观察到的现象、失败模式、瓶颈或经验规律；如果摘要未提供则说明",
  "method": "核心方法概括",
  "contributions": ["贡献1", "贡献2"],
  "experiments": "实验信息；如果摘要未提供则说明",
  "limitations": ["可能局限1", "可能局限2"],
  "primary_area_en": "taxonomy 中的英文一级分类",
  "primary_area": "taxonomy 中 primary_area_en 对应的中文一级分类",
  "category": "taxonomy 中该一级分类下的中文二级分类",
  "sub_area": "必须与 category 完全相同，用于兼容旧页面字段",
  "tags": ["VLM", "Video Generation", "LLM Reasoning"],
  "reading_priority": "high|medium|low"
}}

tags 说明：提取 3–5 个英文关键词标签，反映论文核心技术/方法/应用。使用常见英文术语（如 "VLM", "Diffusion", "Reinforcement Learning"），不要用中文。

分类要求：
1. primary_area 和 sub_area 必须只根据标题和摘要判断。
2. primary_area_en 必须完全等于 taxonomy 中某个英文一级分类。
3. primary_area 必须完全等于该 primary_area_en 对应的中文一级分类。
4. category 必须完全等于该 primary_area 下列出的某个中文二级分类。
5. sub_area 必须完全等于 category。
6. 如果难以判断，选择 primary_area_en="other topics in machine learning (i.e., none of the above)"，primary_area="其他 ML 主题"，category="其他"。

字段区分要求：
- research_motivation 写"为什么值得研究"：背景痛点、应用价值、已有方法为什么不够。
- problem 写"具体要解决什么问题"：论文直接攻克的任务、误差来源、约束或目标。
- research_motivation 和 problem 不要原句重复；如果摘要信息不足，也要从不同角度简短表述。

reading_priority 判定标准：
- high：必须满足至少一条：1) 与 VLM/MLLM、视频生成/图像生成、CT 报告生成、LLM 训练/对齐/推理/Agent 这些重点方向强相关，且摘要显示有明确方法创新、系统性实验或显著应用价值；2) 属于基础/前沿模型、生成模型、应用：CV/音频/语言等、数据集与基准，并且看起来值得优先精读；3) 摘要中出现强实证信号，如多个 benchmark、SOTA、显著效率提升、开源数据/代码或真实临床/工业场景验证。
- medium：满足至少一条：1) 与重点方向中等相关，但贡献偏增量、实验信息有限或应用范围较窄；2) 方法可能有价值但摘要没有给出足够实验细节；3) 属于相关大类，但不是当前最核心关注点。
- low：满足至少一条：1) 与重点方向弱相关或主要是边缘应用；2) 摘要信息不足，难以判断贡献；3) 主要是小规模工程改进、特定数据集技巧或与当前关注方向距离较远。
- 如果 high 和 medium 都可解释，优先选择 medium，避免过度标 high。只有明显值得优先阅读的论文才标 high。
"""

PAPER_PROMPT_TEMPLATE = """论文标题：
{title}

论文摘要：
{abstract}
"""


class ModelJsonError(ValueError):
    def __init__(self, message: str, raw_response: str) -> None:
        super().__init__(message)
        self.raw_response = raw_response


def load_taxonomy_prompt() -> str:
    taxonomy = read_json(TAXONOMY_PATH)
    lines: list[str] = []
    for area in taxonomy.get("areas", []):
        primary_area_en = area.get("primary_area_en", "")
        primary_area = area.get("primary_area", "")
        categories = "；".join(area.get("categories", []))
        lines.append(f"- {primary_area_en} | {primary_area}: {categories}")
    return "\n".join(lines)


def normalize_label(value: str) -> str:
    return "".join(str(value or "").replace("：", ":").lower().split())


def taxonomy_indexes() -> tuple[dict[str, dict[str, Any]], dict[str, str], dict[str, str], dict[str, set[str]]]:
    taxonomy = read_json(TAXONOMY_PATH)
    area_index: dict[str, dict[str, Any]] = {}
    category_index: dict[str, str] = {}
    category_candidates: dict[str, set[str]] = {}
    area_categories: dict[str, set[str]] = {}
    for area in taxonomy.get("areas", []):
        primary_area = str(area.get("primary_area") or "").strip()
        if not primary_area:
            continue
        area_index[normalize_label(primary_area)] = area
        area_categories[primary_area] = set()
        for category in area.get("categories", []):
            category_name = str(category).strip()
            category_key = normalize_label(category_name)
            category_index[category_key] = category_name
            category_candidates.setdefault(category_key, set()).add(primary_area)
            area_categories[primary_area].add(category_key)
    category_area_index = {
        category: next(iter(areas)) for category, areas in category_candidates.items() if len(areas) == 1
    }
    return area_index, category_index, category_area_index, area_categories


SYSTEM_PROMPT = SYSTEM_PROMPT_TEMPLATE.format(taxonomy=load_taxonomy_prompt())
AREA_INDEX, CATEGORY_INDEX, CATEGORY_AREA_INDEX, AREA_CATEGORIES = taxonomy_indexes()


def get_client() -> OpenAI:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set. Use --mock for a key-free preview.")
    return OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL, timeout=60.0, max_retries=2)


def parse_model_json(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ModelJsonError(f"Failed to parse model JSON: {exc}", content) from exc


def normalize_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    tldr = str(analysis.get("tldr") or analysis.get("one_sentence_summary") or "").strip()
    if tldr:
        analysis["tldr"] = tldr
        analysis["one_sentence_summary"] = tldr

    priority = str(analysis.get("reading_priority", "")).strip().lower()
    if priority not in {"high", "medium", "low"}:
        priority = "medium"
    analysis["reading_priority"] = priority

    category = str(analysis.get("category") or analysis.get("sub_area") or "").strip()
    category_area = CATEGORY_AREA_INDEX.get(normalize_label(category))
    primary_area = str(analysis.get("primary_area") or "").strip()
    area = AREA_INDEX.get(normalize_label(primary_area))
    legacy_area_aliases = {
        normalize_label("医学与科学AI"): "应用: CV/音频/语言等",
        normalize_label("医学与科学 AI"): "应用: CV/音频/语言等",
    }
    if not area and normalize_label(primary_area) in legacy_area_aliases:
        area = AREA_INDEX.get(normalize_label(legacy_area_aliases[normalize_label(primary_area)]))
    if category_area:
        area = AREA_INDEX.get(normalize_label(category_area), area)
    if area:
        analysis["primary_area_en"] = area.get("primary_area_en", analysis.get("primary_area_en", ""))
        analysis["primary_area"] = area.get("primary_area", primary_area)

    category_key = normalize_label(category)
    canonical_category = CATEGORY_INDEX.get(category_key)
    primary_area_value = str(analysis.get("primary_area") or "").strip()
    if not canonical_category or category_key not in AREA_CATEGORIES.get(primary_area_value, set()):
        canonical_category = CATEGORY_INDEX.get(normalize_label("其他"), "其他")
    analysis["category"] = canonical_category
    analysis["sub_area"] = canonical_category
    return analysis


def analyze_paper(client: OpenAI, paper: dict[str, Any], model: str) -> dict[str, Any]:
    prompt = PAPER_PROMPT_TEMPLATE.format(title=paper.get("title", ""), abstract=paper.get("abstract", ""))
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
        extra_body={"thinking": {"type": "disabled"}},
    )
    content = response.choices[0].message.content or ""
    return normalize_analysis(parse_model_json(content))


def parse_concurrency(value: int | str | None) -> int:
    if value is None or value == "":
        return DEFAULT_DEEPSEEK_CONCURRENCY
    try:
        concurrency = int(value)
    except (TypeError, ValueError):
        LOGGER.warning("Invalid concurrency %r; using %d.", value, DEFAULT_DEEPSEEK_CONCURRENCY)
        return DEFAULT_DEEPSEEK_CONCURRENCY
    if concurrency < 1:
        return 1
    if concurrency > MAX_DEEPSEEK_CONCURRENCY:
        LOGGER.warning(
            "Concurrency %d is higher than the safe cap %d; using %d.",
            concurrency,
            MAX_DEEPSEEK_CONCURRENCY,
            MAX_DEEPSEEK_CONCURRENCY,
        )
        return MAX_DEEPSEEK_CONCURRENCY
    return concurrency


def analyze_one_paper(client: OpenAI, paper: dict[str, Any], model: str) -> dict[str, Any]:
    enriched = dict(paper)
    arxiv_id = paper_id(paper)
    try:
        enriched["analysis"] = analyze_paper(client, paper, model)
    except ModelJsonError as exc:
        LOGGER.warning("Analysis JSON parse failed for %s: %s", arxiv_id, exc)
        enriched["analysis_error"] = str(exc)
        enriched["raw_response"] = exc.raw_response
    except Exception as exc:
        LOGGER.warning("Analysis failed for %s: %s", arxiv_id, exc)
        enriched["analysis_error"] = str(exc)
    return enriched


def _extract_analyses(papers: list[dict[str, Any] | None]) -> list[dict[str, Any]]:
    analyses = []
    for paper in papers:
        if paper is None:
            continue
        arxiv_id = paper_id(paper)
        if not arxiv_id:
            continue
        analyses.append({
            "arxiv_id": arxiv_id,
            "analysis_version": str(paper.get("analysis_version", "1")),
            "model": os.environ.get("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL),
            "analyzed_at": paper.get("analyzed_at", ""),
            "analysis": paper.get("analysis", {}),
            "raw_response": paper.get("raw_response", ""),
        })
    return analyses


def analyze_date(target_date: str, concurrency: int | str | None = None) -> None:
    ensure_dirs()
    papers = papers_for_date(target_date)
    if not papers:
        LOGGER.info("No papers found in database for %s.", target_date)
        return

    analysis_index = load_analysis_index()
    existing_by_id: dict[str, dict[str, Any]] = {}
    for arxiv_id, record in analysis_index.items():
        if record.get("analysis") or record.get("tldr"):
            existing_by_id[arxiv_id] = record

    client = get_client()
    model = os.environ.get("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL)
    worker_count = parse_concurrency(concurrency if concurrency is not None else os.environ.get("DEEPSEEK_CONCURRENCY"))
    analyzed_papers: list[dict[str, Any] | None] = [None] * len(papers)
    pending: list[tuple[int, dict[str, Any]]] = []

    for index, paper in enumerate(papers):
        arxiv_id = paper_id(paper)
        existing = existing_by_id.get(arxiv_id)
        if existing and (existing.get("analysis") or existing.get("tldr")):
            LOGGER.info("Skipping already analyzed paper %s", arxiv_id)
            analyzed_papers[index] = {**paper, "analysis": existing.get("analysis", existing), "analysis_version": existing.get("analysis_version", "1"), "analyzed_at": existing.get("analyzed_at", ""), "model": existing.get("model", model)}
            continue
        pending.append((index, paper))

    if pending:
        LOGGER.info("Analyzing %d pending paper(s) with concurrency=%d.", len(pending), worker_count)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {}
            for index, paper in pending:
                LOGGER.info("Queueing paper %d/%d: %s", index + 1, len(papers), paper_id(paper))
                futures[executor.submit(analyze_one_paper, client, paper, model)] = index
            for completed_count, future in enumerate(
                progress_bar(as_completed(futures), total=len(futures), desc="DeepSeek analysis", unit="paper"),
                start=1,
            ):
                index = futures[future]
                analyzed_papers[index] = future.result()
                LOGGER.info("Completed pending analysis %d/%d.", completed_count, len(pending))

    new_analyses = _extract_analyses(analyzed_papers)
    if new_analyses:
        inserted, skipped = append_new_analyses(new_analyses, existing_index=analysis_index)
        LOGGER.info("Database: inserted %d analysis record(s) (skipped %d duplicates)", inserted, skipped)

    LOGGER.info("Analysis complete for %s: %d papers total, %d analyzed", target_date, len(papers), len(pending))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze arXiv papers with DeepSeek.")
    parser.add_argument("--date", default=None, help="Target date in YYYY-MM-DD format.")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help=f"Concurrent DeepSeek requests. Defaults to {DEFAULT_DEEPSEEK_CONCURRENCY}; capped at {MAX_DEEPSEEK_CONCURRENCY}.",
    )
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    analyze_date(parse_date(args.date), concurrency=args.concurrency)


if __name__ == "__main__":
    main()