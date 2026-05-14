"""Analyze arXiv papers with DeepSeek AI."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import os
from typing import Any

from openai import OpenAI

from lib.archive import (
    ANALYSES_JSONL,
    append_new_analyses,
    load_analysis_index,
    paper_id,
    papers_for_date,
    utc_now_iso,
)
from lib.config import ensure_dirs, parse_date, setup_logging
from lib.progress import progress_bar
from lib.taxonomy import (
    AREA_CATEGORIES_MAP as _AREA_CATEGORIES_MAP,
    AREA_INDEX as _AREA_INDEX,
    CATEGORY_AREA_INDEX as _CATEGORY_AREA_INDEX,
    CATEGORY_INDEX as _CATEGORY_INDEX,
    load_taxonomy_prompt,
)

LOGGER = logging.getLogger("commands.analyze")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_ANALYSIS_VERSION = "v3_noscore_2026_05"
DEFAULT_DEEPSEEK_CONCURRENCY = 4
MAX_DEEPSEEK_CONCURRENCY = 8


SYSTEM_PROMPT_TEMPLATE = """你是一个严谨的机器学习论文导读助手。请只根据论文标题和摘要生成中文导读，不要编造摘要中不存在的实验结论。如果摘要没有提到实验结果，请明确写“摘要未提供具体实验结果”。输出必须是合法 JSON。

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
  "tags": ["VLM", "Video Generation"],
  "recommended_action": "read_deeply|read_abstract|save_for_later|skip",
  "reading_priority": "must_read|recommended|skim|low_priority|skip"
}}

分类要求：
1. primary_area 和 sub_area 必须只根据标题和摘要判断。
2. primary_area_en 必须完全等于 taxonomy 中某个英文一级分类。
3. primary_area 必须完全等于该 primary_area_en 对应的中文一级分类。
4. category 必须完全等于该 primary_area 下列出的某个中文二级分类。
5. sub_area 必须完全等于 category。
6. 如果难以判断，选择 primary_area_en="other topics in machine learning (i.e., none of the above)"，primary_area="其他 ML 主题"，category="其他"。

字段区分要求：
- research_motivation 写“为什么值得研究”：背景痛点、应用价值、已有方法为什么不够。
- problem 写“具体要解决什么问题”：论文直接攻克的任务、误差来源、约束或目标。
- research_motivation 和 problem 不要原句重复；如果摘要信息不足，也要从不同角度简短表述。

阅读建议要求：
- 不要输出 novelty、technical_depth、impact、relevance、score_raw、score、reason 等评分或评分解释字段。
- recommended_action 必须只选 read_deeply、read_abstract、save_for_later、skip。
- reading_priority 用于粗粒度排序和筛选，不是评分；不确定时偏保守。

reading_priority 判定标准：
- must_read：必须满足至少一条：1) 与 VLM/MLLM、视频生成/图像生成、CT 报告生成、LLM 训练/对齐/推理/Agent 这些重点方向强相关，且摘要显示有明确方法创新、系统性实验或显著应用价值；2) 属于基础/前沿模型、生成模型、应用：CV/音频/语言等、数据集与基准，并且看起来值得优先精读；3) 摘要中出现强实证信号，如多个 benchmark、SOTA、显著效率提升、开源数据/代码或真实临床/工业场景验证。
- recommended：与重点方向中等相关，但贡献偏增量、实验信息有限或应用范围较窄；或者方法可能有价值但摘要没有给出足够实验细节。
- skim：属于相关大类，但不是当前最核心关注点，适合快速浏览。
- low_priority：与重点方向弱相关、主要是边缘应用、小规模工程改进或特定数据集技巧。
- skip：摘要信息不足且与当前关注方向距离较远。
- 如果 must_read 和 recommended 都可解释，优先选择 recommended，避免过度标 must_read。只有明显值得优先阅读的论文才标 must_read。
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


AREA_INDEX = _AREA_INDEX
CATEGORY_INDEX = _CATEGORY_INDEX
CATEGORY_AREA_INDEX = _CATEGORY_AREA_INDEX
AREA_CATEGORIES_MAP = _AREA_CATEGORIES_MAP
SYSTEM_PROMPT = SYSTEM_PROMPT_TEMPLATE.format(taxonomy=load_taxonomy_prompt())


def legacy_priority(priority: str) -> str:
    if priority == "must_read":
        return "high"
    if priority in {"recommended", "skim"}:
        return "medium"
    return "low"


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

    for key in ("novelty", "technical_depth", "impact", "relevance", "score_raw", "score", "reason"):
        analysis.pop(key, None)

    priority = str(analysis.get("reading_priority") or "").strip().lower()
    legacy_priority_aliases = {"high": "must_read", "medium": "recommended", "low": "low_priority"}
    priority = legacy_priority_aliases.get(priority, priority)
    if priority not in {"must_read", "recommended", "skim", "low_priority", "skip"}:
        priority = "recommended"
    action = str(analysis.get("recommended_action") or "").strip().lower()
    if action not in {"read_deeply", "read_abstract", "save_for_later", "skip"}:
        action = {
            "must_read": "read_deeply",
            "recommended": "read_abstract",
            "skim": "read_abstract",
            "low_priority": "save_for_later",
            "skip": "skip",
        }[priority]
    analysis["reading_priority"] = priority
    analysis["legacy_reading_priority"] = legacy_priority(priority)
    analysis["recommended_action"] = action

    category = str(analysis.get("category") or analysis.get("sub_area") or "").strip()
    category_area = CATEGORY_AREA_INDEX.get("".join(str(category or "").replace("：", ":").lower().split()))
    primary_area = str(analysis.get("primary_area") or "").strip()
    area = AREA_INDEX.get("".join(str(primary_area or "").replace("：", ":").lower().split()))
    legacy_area_aliases = {
        "".join("医学与科学AI".replace("：", ":").lower().split()): "应用: CV/音频/语言等",
        "".join("医学与科学 AI".replace("：", ":").lower().split()): "应用: CV/音频/语言等",
    }
    norm_pa = "".join(str(primary_area or "").replace("：", ":").lower().split())
    if not area and norm_pa in legacy_area_aliases:
        area = AREA_INDEX.get("".join(legacy_area_aliases[norm_pa].replace("：", ":").lower().split()))
    if category_area:
        area = AREA_INDEX.get("".join(str(category_area).replace("：", ":").lower().split()), area)
    if area:
        analysis["primary_area_en"] = area.get("primary_area_en", analysis.get("primary_area_en", ""))
        analysis["primary_area"] = area.get("primary_area", primary_area)

    norm_cat = "".join(str(category or "").replace("：", ":").lower().split())
    canonical_category = CATEGORY_INDEX.get(norm_cat)
    primary_area_value = str(analysis.get("primary_area") or "").strip()
    if not canonical_category or norm_cat not in AREA_CATEGORIES_MAP.get(primary_area_value, set()):
        canonical_category = CATEGORY_INDEX.get("".join("其他".replace("：", ":").lower().split()), "其他")
    analysis["category"] = canonical_category
    analysis["sub_area"] = canonical_category
    return analysis


def legacy_analysis_for_site(analysis: dict[str, Any]) -> dict[str, Any]:
    legacy = dict(analysis)
    legacy["archive_reading_priority"] = analysis.get("reading_priority")
    legacy["reading_priority"] = analysis.get("legacy_reading_priority") or legacy_priority(str(analysis.get("reading_priority") or ""))
    return legacy


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
    arxiv_id = paper.get("arxiv_id")
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


def archive_analysis_record(
    enriched_paper: dict[str, Any],
    *,
    analysis_version: str,
    model: str,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "arxiv_id": enriched_paper.get("arxiv_id"),
        "analysis_version": analysis_version,
        "model": model,
        "analyzed_at": utc_now_iso(),
    }
    record["analysis"] = enriched_paper["analysis"]
    return record


def paper_with_analysis_record(paper: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(paper)
    if "analysis" in record:
        enriched["analysis"] = legacy_analysis_for_site(record["analysis"])
    if "analysis_error" in record:
        enriched["analysis_error"] = record["analysis_error"]
    if "raw_response" in record:
        enriched["raw_response"] = record["raw_response"]
    return enriched


def load_raw_papers(target_date: str) -> tuple[list[dict[str, Any]], str]:
    archive_papers = papers_for_date(target_date)
    if archive_papers:
        LOGGER.info("Loaded %d paper(s) for %s from archive.", len(archive_papers), target_date)
        return archive_papers, "archive"
    raise FileNotFoundError(f"Archive papers not found for {target_date}. Run fetch/backfill first.")


def analyze_date(
    target_date: str,
    concurrency: int | str | None = None,
    analysis_version: str = DEFAULT_ANALYSIS_VERSION,
    cache_only: bool = False,
) -> Path:
    ensure_dirs()
    raw_papers, _source = load_raw_papers(target_date)
    archive_analysis_index = load_analysis_index()

    if not raw_papers:
        LOGGER.info("No papers to analyze for %s.", target_date)
        return ANALYSES_JSONL

    model = os.environ.get("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL)
    worker_count = parse_concurrency(concurrency if concurrency is not None else os.environ.get("DEEPSEEK_CONCURRENCY"))
    pending: list[tuple[int, dict[str, Any]]] = []

    for index, paper in enumerate(raw_papers):
        arxiv_id = paper_id(paper)
        archive_existing = archive_analysis_index.get(arxiv_id)
        if archive_existing:
            LOGGER.info("Skipping archive-analyzed paper %s", arxiv_id)
            continue

        pending.append((index, paper))

    if pending:
        if cache_only:
            LOGGER.info("Cache-only mode: %d paper(s) are missing analysis and will not call DeepSeek.", len(pending))
            return ANALYSES_JSONL
        client = get_client()
        LOGGER.info("Analyzing %d pending paper(s) with concurrency=%d.", len(pending), worker_count)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {}
            for index, paper in pending:
                LOGGER.info("Queueing paper %d/%d: %s", index + 1, len(raw_papers), paper.get("arxiv_id"))
                futures[executor.submit(analyze_one_paper, client, paper, model)] = index
            completed_futures = as_completed(futures)
            for completed_count, future in enumerate(
                progress_bar(completed_futures, total=len(futures), desc="DeepSeek analysis", unit="paper"),
                start=1,
            ):
                index = futures[future]
                enriched = future.result()
                if "analysis" in enriched:
                    append_new_analyses(
                        [archive_analysis_record(enriched, analysis_version=analysis_version, model=model)],
                        existing_index=archive_analysis_index,
                    )
                LOGGER.info("Completed pending analysis %d/%d.", completed_count, len(pending))

    LOGGER.info("Updated %s", ANALYSES_JSONL)
    return ANALYSES_JSONL


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze arXiv papers with DeepSeek.")
    parser.add_argument("--date", default=None, help="Target date in YYYY-MM-DD format.")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help=f"Concurrent DeepSeek requests. Defaults to {DEFAULT_DEEPSEEK_CONCURRENCY}; capped at {MAX_DEEPSEEK_CONCURRENCY}.",
    )
    parser.add_argument("--analysis-version", default=DEFAULT_ANALYSIS_VERSION)
    parser.add_argument(
        "--cache-only",
        action="store_true",
        help="Report missing archive analyses without calling DeepSeek.",
    )
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    analyze_date(
        parse_date(args.date),
        concurrency=args.concurrency,
        analysis_version=args.analysis_version,
        cache_only=args.cache_only,
    )


if __name__ == "__main__":
    main()
