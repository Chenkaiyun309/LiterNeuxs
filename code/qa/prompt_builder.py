#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
from typing import Any


def build_system_prompt() -> str:
    return (
        "你是严谨、克制、严格遵守格式的科研助手。除文献原始题名、作者、期刊、DOI 外，始终使用中文输出。\n"
        "你现在要回答单篇文献问答。\n"
        "只能依据提供的全文证据片段作答。\n"
        "如果证据不足，必须明确回答“现有全文证据不足”。\n"
        "每个关键结论必须引用一个或多个 citation 编号。\n"
        "不得虚构页码、作者结论、实验结果、统计值或未提供的 chunk_id。\n"
        "输出必须是合法 JSON，不能输出 Markdown、解释或代码块。"
    )


def build_scope_system_prompt() -> str:
    return (
        "你是严谨的科研文献问答助手。除文献原始题名、作者、期刊和 DOI 外，使用中文输出。\n"
        "只能依据本次提供的文献摘要和全文证据作答，不得使用未提供的事实补全答案。\n"
        "综合多篇文献时要区分共识、差异和证据边界；每个关键结论都必须附引用编号。\n"
        "优先提取证据中的实验条件、定量结果、公式、图注和表格信息。证据含公式时应保留 LaTeX，解释符号与物理意义；"
        "证据含图片时只能依据图注和相邻正文解释，不得声称看到了未提供的像素细节。\n"
        "回答字段允许使用 Markdown 标题、列表、粗体和 LaTeX；显示公式使用 $$...$$。\n"
        "证据不足时必须明确写出“现有文献证据不足”。\n"
        "不得虚构实验参数、页码、结论或 source_id。\n"
        "输出必须是合法 JSON，不得输出 JSON 外的 Markdown 代码块或额外说明；JSON 字符串内的 LaTeX 反斜杠必须正确转义。"
    )


def _evidence_content_types(text: str) -> list[str]:
    value = str(text or "")
    lowered = value.lower()
    content_types = []
    if "$$" in value or "\\frac" in value or "\\begin{equation" in value or "\\begin{align" in value:
        content_types.append("formula")
    if "![" in value or "fig." in lowered or "figure " in lowered:
        content_types.append("figure")
    if "table " in lowered or ("|" in value and "---" in value):
        content_types.append("table")
    return content_types


def build_scope_user_prompt(
    question: str,
    evidence: list[dict[str, Any]],
    *,
    scope_label: str,
    conversation: list[dict[str, Any]] | None = None,
    answer_depth: str = "detailed",
) -> str:
    evidence_payload = []
    for index, item in enumerate(evidence, 1):
        page_text = ""
        if item.get("page_start"):
            page_text = f"p.{item['page_start']}"
            if item.get("page_end") and item.get("page_end") != item.get("page_start"):
                page_text = f"p.{item['page_start']}-{item['page_end']}"
        text = str(item.get("chunk_text") or "")[:6000]
        evidence_payload.append({
            "evidence_order": index,
            "source_id": item.get("source_id") or item.get("chunk_id") or "",
            "source_type": item.get("source_type") or "fulltext",
            "paper_title": item.get("title") or "",
            "authors": item.get("authors") or "",
            "venue": item.get("venue") or "",
            "doi": item.get("doi") or "",
            "section_title": item.get("section_title") or "",
            "page": page_text,
            "content_types": item.get("content_types") or _evidence_content_types(text),
            "text": text,
        })

    history = []
    for item in (conversation or [])[-6:]:
        role = str(item.get("role") or "")
        content = str(item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            history.append({"role": role, "content": content[:1600]})

    schema = {
        "answer": "可含 Markdown 与 LaTeX 的中文回答正文，使用 [1] [2] 标记引用。",
        "citations": [
            {"citation_order": 1, "chunk_id": "source_id", "claim": "该证据支持的结论"}
        ],
        "insufficient_evidence": False,
    }
    depth_instructions = {
        "concise": "简洁回答核心结论；仅保留直接相关的证据和限制。",
        "standard": "按结论、关键证据和局限性组织回答；解释直接相关的公式或图表。",
        "detailed": (
            "在证据充分时给出结构化详细回答，通常包括：直接结论、作用机理或方法、定量结果与实验条件、"
            "公式及符号解释、图表证据、跨文献比较、局限性与证据边界。避免重复和无证据扩写；"
            "正文控制在约 1200-2200 个中文字符，确保 JSON 能完整闭合。"
        ),
    }
    normalized_depth = answer_depth if answer_depth in depth_instructions else "detailed"
    formula_instruction = ""
    if any(term in question.lower() for term in ("公式", "方程", "表达式", "计算式", "equation", "formula")):
        formula_instruction = (
            "用户正在追问公式：只选择与当前问题及最近对话直接相关的最多 5 组公式，"
            "逐组解释符号和适用条件，不要罗列无关文献中的全部公式，并确保每个 LaTeX 定界符和 JSON 字符串完整闭合。\n"
        )
    return (
        f"知识范围：{scope_label}\n"
        f"用户问题：{question.strip()}\n\n"
        f"最近对话：{json.dumps(history, ensure_ascii=False)}\n\n"
        "可用文献证据如下。只能引用其中的 source_id：\n"
        f"{json.dumps(evidence_payload, ensure_ascii=False, indent=2)}\n\n"
        "严格输出以下 JSON 结构：\n"
        f"{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
        f"回答详细度：{normalized_depth}。{depth_instructions[normalized_depth]}\n"
        f"{formula_instruction}"
        "若证据含公式，请在 answer 中用 $$...$$ 原样复现最相关公式，并逐一定义能由证据确认的符号；"
        "若证据含 Figure/Fig./Table，请写明编号及其图注或相邻正文支持的结论。\n"
        "要求：answer 中引用编号必须与 citations 的连续编号完全一致；"
        "citations.chunk_id 填对应 source_id；无充分证据时设置 insufficient_evidence=true，"
        "并在回答中明确写“现有文献证据不足”。JSON 内 LaTeX 的每个反斜杠必须写成双反斜杠。"
    )


def build_json_repair_prompt(raw_output: str, allowed_source_ids: list[str]) -> str:
    schema = {
        "answer": "中文回答正文，使用 [1] [2] 标记引用。",
        "citations": [
            {"citation_order": 1, "chunk_id": "source_id", "claim": "该证据支持的结论"}
        ],
        "insufficient_evidence": False,
    }
    return (
        "下面是一份格式不合法的问答 JSON。只修复 JSON 语法、连续引用编号和字段结构，"
        "不要扩写、改写事实或添加新结论。保留 Markdown、公式和 LaTeX，并正确转义公式中的反斜杠。\n"
        f"允许使用的 source_id：{json.dumps(allowed_source_ids, ensure_ascii=False)}\n"
        f"目标结构：{json.dumps(schema, ensure_ascii=False)}\n\n"
        "待修复内容：\n"
        f"{str(raw_output or '')[:12000]}\n\n"
        "仅输出修复后的合法 JSON，不要输出代码块或解释。"
    )


def build_user_prompt(question: str, paper: dict[str, Any], chunks: list[dict[str, Any]]) -> str:
    chunk_payload = []
    for index, chunk in enumerate(chunks, 1):
        page_text = ""
        if chunk.get("page_start"):
            if chunk.get("page_end") and chunk.get("page_end") != chunk.get("page_start"):
                page_text = f"p.{chunk['page_start']}-{chunk['page_end']}"
            else:
                page_text = f"p.{chunk['page_start']}"
        chunk_payload.append({
            "citation_order": index,
            "chunk_id": chunk.get("chunk_id", ""),
            "section_title": chunk.get("section_title", ""),
            "page": page_text,
            "chunk_text": chunk.get("chunk_text", ""),
        })

    schema = {
        "answer": "回答正文，使用 [1] [2] 形式标记引用。",
        "citations": [
            {
                "citation_order": 1,
                "chunk_id": "chunk-id",
                "claim": "该证据支持的结论",
            }
        ],
        "insufficient_evidence": False,
    }

    return (
        f"当前文献：{paper.get('title', '')}\n"
        f"作者：{paper.get('authors', '')}\n"
        f"期刊：{paper.get('venue', '')}\n"
        f"DOI：{paper.get('doi', '')}\n\n"
        f"用户问题：{question.strip()}\n\n"
        "以下是可用全文证据片段。只能引用这些片段：\n"
        f"{json.dumps(chunk_payload, ensure_ascii=False, indent=2)}\n\n"
        "请严格输出如下 JSON 结构：\n"
        f"{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
        "要求：\n"
        "1. answer 必须使用中文。\n"
        "2. answer 中每个关键结论都必须带 [citation_order]。\n"
        "3. citations 中的 chunk_id 只能来自上面提供的证据集合。\n"
        "4. 如果证据不足，insufficient_evidence=true，answer 中明确写“现有全文证据不足”。\n"
        "5. 不要输出 JSON 以外的任何内容。"
    )
