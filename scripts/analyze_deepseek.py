from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from openai import OpenAI

from utils import PROJECT_ROOT, ensure_dirs, parse_date, read_json, setup_logging, write_json


LOGGER = logging.getLogger("analyze_deepseek")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
TAXONOMY_PATH = PROJECT_ROOT / "data" / "iclr_taxonomy.json"


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
  "reading_priority": "high|medium|low"
}}

分类要求：
1. primary_area 和 sub_area 必须只根据标题和摘要判断。
2. primary_area_en 必须完全等于 taxonomy 中某个英文一级分类。
3. primary_area 必须完全等于该 primary_area_en 对应的中文一级分类。
4. category 必须完全等于该 primary_area 下列出的某个中文二级分类。
5. sub_area 必须完全等于 category。
6. 如果难以判断，选择 primary_area_en="other topics in machine learning (i.e., none of the above)"，primary_area="其他 ML 主题"，category="其他"。

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


SYSTEM_PROMPT = SYSTEM_PROMPT_TEMPLATE.format(taxonomy=load_taxonomy_prompt())


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
    if category:
        analysis["category"] = category
        analysis["sub_area"] = category
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
    )
    content = response.choices[0].message.content or ""
    return normalize_analysis(parse_model_json(content))


def load_existing(output_path: Path) -> dict[str, dict[str, Any]]:
    if not output_path.exists():
        return {}
    existing = read_json(output_path)
    return {paper.get("arxiv_id"): paper for paper in existing.get("papers", []) if paper.get("arxiv_id")}


def analyze_date(target_date: str) -> Path:
    ensure_dirs()
    raw_path = PROJECT_ROOT / "data" / "raw" / f"{target_date}.json"
    if not raw_path.exists():
        raise FileNotFoundError(f"Raw data not found: {raw_path}")

    raw = read_json(raw_path)
    output_path = PROJECT_ROOT / "data" / "analyzed" / f"{target_date}.json"
    existing_by_id = load_existing(output_path)

    if not raw.get("papers", []):
        write_json(output_path, {"date": target_date, "source": raw.get("source", "arxiv"), "papers": []})
        LOGGER.info("No papers to analyze for %s; wrote empty analyzed JSON.", target_date)
        return output_path

    client = get_client()
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

    analyzed_papers: list[dict[str, Any]] = []
    for index, paper in enumerate(raw.get("papers", []), start=1):
        arxiv_id = paper.get("arxiv_id")
        existing = existing_by_id.get(arxiv_id)
        if existing and ("analysis" in existing or "analysis_error" in existing):
            LOGGER.info("Skipping already analyzed paper %s", arxiv_id)
            analyzed_papers.append(existing)
            continue

        LOGGER.info("Analyzing paper %d/%d: %s", index, len(raw.get("papers", [])), arxiv_id)
        enriched = dict(paper)
        try:
            enriched["analysis"] = analyze_paper(client, paper, model)
        except ModelJsonError as exc:
            LOGGER.warning("Analysis JSON parse failed for %s: %s", arxiv_id, exc)
            enriched["analysis_error"] = str(exc)
            enriched["raw_response"] = exc.raw_response
        except Exception as exc:
            LOGGER.warning("Analysis failed for %s: %s", arxiv_id, exc)
            enriched["analysis_error"] = str(exc)
        analyzed_papers.append(enriched)
        write_json(output_path, {"date": target_date, "source": raw.get("source", "arxiv"), "papers": analyzed_papers})
        time.sleep(0.5)

    write_json(output_path, {"date": target_date, "source": raw.get("source", "arxiv"), "papers": analyzed_papers})
    LOGGER.info("Wrote %s", output_path)
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze arXiv papers with DeepSeek.")
    parser.add_argument("--date", default=None, help="Target date in YYYY-MM-DD format.")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    analyze_date(parse_date(args.date))


if __name__ == "__main__":
    main()
