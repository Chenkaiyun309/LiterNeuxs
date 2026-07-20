#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ParseQualityResult:
    parse_quality: str
    page_mapping_coverage: float
    text_length: int
    quality_warnings: list[str]


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def evaluate_parse_quality(
    *,
    markdown_text: str,
    chunks: list[Any],
    pages: list[Any],
) -> ParseQualityResult:
    text = str(markdown_text or "")
    text_length = len(text.strip())
    page_count = len(pages)
    chunk_count = len(chunks)
    warnings: list[str] = []

    mapped_chunks = 0
    page_hits: set[int] = set()
    confidence_sum = 0.0
    non_empty_pages = 0
    short_pages = 0
    repeated_pages = 0
    seen_page_texts: dict[str, int] = {}

    for page in pages:
        page_text = str(getattr(page, "text", "") or "").strip()
        if page_text:
            non_empty_pages += 1
            if len(page_text) < 80:
                short_pages += 1
            page_key = " ".join(page_text.split())[:300]
            if page_key:
                seen_page_texts[page_key] = seen_page_texts.get(page_key, 0) + 1

    for count in seen_page_texts.values():
        if count > 1:
            repeated_pages += count - 1

    for chunk in chunks:
        page_start = getattr(chunk, "page_start", None)
        page_end = getattr(chunk, "page_end", None)
        confidence = _safe_float(getattr(chunk, "page_mapping_confidence", 0.0))
        if page_start and page_end:
            mapped_chunks += 1
            confidence_sum += confidence
            for page_number in range(int(page_start), int(page_end) + 1):
                page_hits.add(page_number)

    coverage = round((mapped_chunks / chunk_count), 4) if chunk_count else 0.0
    avg_confidence = (confidence_sum / mapped_chunks) if mapped_chunks else 0.0
    blank_ratio = 0.0 if page_count <= 0 else max(0.0, 1.0 - (non_empty_pages / page_count))
    short_ratio = 0.0 if page_count <= 0 else (short_pages / page_count)
    repeated_ratio = 0.0 if page_count <= 0 else (repeated_pages / page_count)

    if text_length < 2500:
        warnings.append("全文正文偏短，解析结果可能不完整")
    if chunk_count <= 2 and text_length > 0:
        warnings.append("正文片段数量偏少，请检查分块质量")
    if coverage < 0.8 and chunk_count > 0:
        warnings.append(f"页码映射覆盖率较低（{coverage * 100:.0f}%）")
    if avg_confidence < 0.55 and mapped_chunks > 0:
        warnings.append("页码映射置信度偏低，请谨慎使用页码引用")
    if blank_ratio >= 0.45 and page_count >= 4:
        warnings.append("疑似扫描版或图片型 PDF，逐页文本较少")
    if short_ratio >= 0.55 and page_count >= 4:
        warnings.append("多页文本过短，可能存在提取质量问题")
    if repeated_ratio >= 0.3 and page_count >= 4:
        warnings.append("检测到较多重复页文本，可能有页眉页脚或重复提取")
    if page_count and not page_hits:
        warnings.append("未能为正文片段建立可靠页码映射")

    if not text_length:
        parse_quality = "poor"
    elif coverage >= 0.8 and avg_confidence >= 0.6 and blank_ratio < 0.35 and text_length >= 2500:
        parse_quality = "good"
    elif coverage >= 0.45 and text_length >= 1200:
        parse_quality = "warning"
    else:
        parse_quality = "poor"

    return ParseQualityResult(
        parse_quality=parse_quality,
        page_mapping_coverage=coverage,
        text_length=text_length,
        quality_warnings=warnings,
    )
