#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import re
from typing import Any


CITATION_RE = re.compile(r"\[(\d+)\]")


class CitationValidationError(ValueError):
    """Raised when QA citations fail validation."""


def normalize_answer_math(answer: str) -> str:
    text = str(answer or "")
    text = re.sub(r"\\bm\s*\{([^{}]+)\}", r"\\boldsymbol{\1}", text)
    text = re.sub(r"\\bm\s*([A-Za-z])", r"\\boldsymbol{\1}", text)
    if text.count("$$") % 2:
        text = text[:text.rfind("$$")].rstrip()
        text += "\n\n> 回答达到模型输出上限，末尾未完成的公式已省略。"
    if text.count("\\[") > text.count("\\]"):
        text = text[:text.rfind("\\[")].rstrip()
        text += "\n\n> 回答达到模型输出上限，末尾未完成的公式已省略。"
    return text.strip()


def extract_citation_orders(answer: str) -> list[int]:
    text = str(answer or "")
    text = re.sub(r"\$\$.*?\$\$|\\\[.*?\\\]|\$[^$]+\$", "", text, flags=re.DOTALL)
    orders: list[int] = []
    for match in CITATION_RE.findall(text):
        try:
            orders.append(int(match))
        except ValueError:
            continue
    return orders


def validate_qa_response(payload: dict[str, Any], allowed_chunks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise CitationValidationError("模型返回不是对象 JSON")

    answer = normalize_answer_math(payload.get("answer") or "")
    citations = payload.get("citations")
    insufficient_evidence = bool(payload.get("insufficient_evidence", False))

    if not isinstance(citations, list):
        raise CitationValidationError("citations 必须是数组")
    if not answer:
        raise CitationValidationError("answer 不能为空")

    normalized: list[dict[str, Any]] = []
    seen_chunk_ids: set[str] = set()
    for item in citations:
        if not isinstance(item, dict):
            raise CitationValidationError("citations 项必须是对象")
        try:
            citation_order = int(item.get("citation_order"))
        except Exception as exc:
            raise CitationValidationError("citation_order 必须是整数") from exc
        chunk_id = str(item.get("chunk_id") or "").strip()
        claim = str(item.get("claim") or "").strip()
        if not chunk_id:
            raise CitationValidationError("chunk_id 不能为空")
        if chunk_id not in allowed_chunks:
            raise CitationValidationError(f"模型引用了未授权的 chunk_id：{chunk_id}")
        if not str(allowed_chunks[chunk_id].get("chunk_text") or "").strip():
            raise CitationValidationError(f"引用证据正文为空：{chunk_id}")
        if not claim:
            raise CitationValidationError("citation.claim 不能为空")
        if chunk_id in seen_chunk_ids:
            raise CitationValidationError(f"同一 chunk_id 不得重复建立引用：{chunk_id}")
        seen_chunk_ids.add(chunk_id)
        normalized.append({
            "citation_order": citation_order,
            "chunk_id": chunk_id,
            "claim": claim,
        })

    normalized.sort(key=lambda item: item["citation_order"])
    expected = list(range(1, len(normalized) + 1))
    actual = [item["citation_order"] for item in normalized]
    if actual != expected:
        raise CitationValidationError("citation_order 必须从 1 开始连续编号")

    answer_orders = sorted(set(extract_citation_orders(answer)))
    if answer_orders != expected:
        raise CitationValidationError("answer 中的引用编号必须与 citations 完全一致")
    if not insufficient_evidence and not normalized:
        raise CitationValidationError("证据充分的回答至少需要一个有效引用")
    if insufficient_evidence and not any(
        phrase in answer for phrase in ("现有全文证据不足", "现有文献证据不足")
    ):
        raise CitationValidationError("证据不足时 answer 必须明确写出现有文献证据不足")

    return {
        "answer": answer,
        "citations": normalized,
        "insufficient_evidence": insufficient_evidence,
    }
