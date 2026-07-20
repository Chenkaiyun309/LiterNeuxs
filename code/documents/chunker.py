#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Protocol


MAX_CHARS = 2800
MIN_CHARS = 450


SECTION_PATTERNS = [
    re.compile(r"^\s*(abstract|introduction|background|methods?|materials and methods|results?|discussion|conclusions?|references)\s*$", re.I),
    re.compile(r"^\s*\d+(?:\.\d+)*\s+[A-Z][^\n]{2,100}$"),
]


class PageLike(Protocol):
    page_number: int
    text: str


@dataclass
class TextChunk:
    section_title: str
    page_start: int | None
    page_end: int | None
    chunk_text: str
    chunk_index: int
    token_count: int = 0
    content_hash: str = ""
    chunk_type: str = "body"
    page_mapping_confidence: float = 0.0


@dataclass
class MarkdownBlock:
    section_title: str
    block_text: str
    block_index: int


def _clean_paragraph(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", str(text or ""))
    text = re.sub(r"\n+", " ", text)
    return text.strip()


def _detect_section(line: str) -> str:
    candidate = re.sub(r"\s+", " ", str(line or "")).strip()
    if len(candidate) > 120:
        return ""
    for pattern in SECTION_PATTERNS:
        if pattern.match(candidate):
            return candidate
    return ""


def _normalize_text_for_match(text: str) -> str:
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"```.*?```", " ", value, flags=re.S)
    value = re.sub(r"`[^`]*`", " ", value)
    value = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", value)
    value = re.sub(r"\[[^\]]*\]\([^)]+\)", " ", value)
    value = re.sub(r"[#>*_~\-]+", " ", value)
    value = re.sub(r"[^\w一-鿿]+", " ", value, flags=re.UNICODE)
    value = value.lower()
    return re.sub(r"\s+", " ", value).strip()


def _match_tokens(normalized_text: str) -> list[str]:
    tokens: list[str] = []
    for raw in str(normalized_text or "").split():
        if re.search(r"[一-鿿]", raw):
            chinese = "".join(re.findall(r"[一-鿿]", raw))
            if len(chinese) >= 3:
                tokens.extend(chinese[index:index + 3] for index in range(len(chinese) - 2))
            elif chinese:
                tokens.append(chinese)
        else:
            token = raw.strip()
            if len(token) >= 2:
                tokens.append(token)
    return tokens


def _estimate_token_count(text: str) -> int:
    normalized = _normalize_text_for_match(text)
    if not normalized:
        return 0
    tokens = normalized.split()
    return max(1, len(tokens))


def _chunk_hash(text: str) -> str:
    return hashlib.sha256(str(text or "").strip().encode("utf-8")).hexdigest()


def _looks_like_reference_text(text: str, section_title: str = "") -> bool:
    combined = f"{section_title}\n{text}".lower()
    if "references" in combined or "bibliography" in combined:
        return True
    doi_like = len(re.findall(r"10\.\d{4,9}/", combined))
    bracket_refs = len(re.findall(r"\[[0-9]{1,3}\]", combined))
    year_refs = len(re.findall(r"\((?:19|20)\d{2}\)", combined))
    return doi_like >= 2 or bracket_refs >= 4 or year_refs >= 4


def _guess_chunk_type(text: str, section_title: str = "") -> str:
    if _looks_like_reference_text(text, section_title):
        return "references"
    combined = f"{section_title}\n{text}".lower()
    if "abstract" in combined[:120]:
        return "abstract"
    return "body"


def _similarity_score(block_text: str, page_text: str) -> float:
    block_norm = _normalize_text_for_match(block_text)
    page_norm = _normalize_text_for_match(page_text)
    if not block_norm or not page_norm:
        return 0.0

    block_tokens = _match_tokens(block_norm)
    page_token_set = set(_match_tokens(page_norm))
    if not block_tokens or not page_token_set:
        return 0.0

    unique_block_tokens = []
    seen = set()
    for token in block_tokens:
        if token not in seen:
            seen.add(token)
            unique_block_tokens.append(token)

    hit_count = sum(1 for token in unique_block_tokens if token in page_token_set)
    coverage = hit_count / max(1, len(unique_block_tokens))

    prefix_hits = 0
    for token in unique_block_tokens[:12]:
        if token in page_token_set:
            prefix_hits += 1
    prefix_score = prefix_hits / max(1, min(12, len(unique_block_tokens)))

    sequence_bonus = 0.0
    if len(block_norm) >= 24:
        snippet = block_norm[: min(96, len(block_norm))]
        if snippet and snippet in page_norm:
            sequence_bonus = 0.18
    return round(min(1.0, 0.72 * coverage + 0.10 * prefix_score + sequence_bonus), 4)


def _page_span_for_text(
    text: str,
    pages: list[PageLike],
    *,
    min_page_number: int | None = None,
) -> tuple[int | None, int | None, float]:
    if not pages:
        return None, None, 0.0
    normalized = _normalize_text_for_match(text)
    if not normalized or len(normalized) < 24:
        return None, None, 0.0

    eligible_pages = [
        page
        for page in pages
        if min_page_number is None or int(page.page_number) >= min_page_number
    ]
    if not eligible_pages:
        return None, None, 0.0

    scored_pages: list[tuple[float, int]] = []
    for page in eligible_pages:
        score = _similarity_score(normalized, page.text)
        if score > 0:
            scored_pages.append((score, int(page.page_number)))
    if not scored_pages:
        return None, None, 0.0

    best_score, best_page = max(scored_pages, key=lambda item: (item[0], -item[1]))
    if best_score < 0.22:
        return None, None, round(best_score, 4)

    threshold = max(0.18, best_score * 0.62)
    score_by_page = {page_number: score for score, page_number in scored_pages}
    page_lengths = sorted(
        len(_normalize_text_for_match(page.text))
        for page in eligible_pages
        if _normalize_text_for_match(page.text)
    )
    median_page_length = page_lengths[len(page_lengths) // 2] if page_lengths else len(normalized)
    expected_span = max(1, min(4, math.ceil(len(normalized) / max(1, median_page_length)) + 1))

    matched_pages = {best_page}
    while len(matched_pages) < expected_span:
        left = min(matched_pages) - 1
        right = max(matched_pages) + 1
        candidates = [
            (score_by_page.get(page_number, 0.0), page_number)
            for page_number in (left, right)
            if score_by_page.get(page_number, 0.0) >= threshold
        ]
        if not candidates:
            break
        _, selected_page = max(candidates, key=lambda item: item[0])
        matched_pages.add(selected_page)
    return min(matched_pages), max(matched_pages), round(best_score, 4)


def chunk_pages(pages: list[PageLike], *, max_chars: int = MAX_CHARS, min_chars: int = MIN_CHARS) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    current_section = ""
    buffer: list[str] = []
    page_start = 0
    page_end = 0

    def flush() -> None:
        nonlocal buffer, page_start, page_end
        text = "\n\n".join(part for part in buffer if part).strip()
        if not text:
            buffer = []
            return
        chunks.append(
            TextChunk(
                section_title=current_section,
                page_start=page_start or None,
                page_end=page_end or None,
                chunk_text=text,
                chunk_index=len(chunks),
                token_count=_estimate_token_count(text),
                content_hash=_chunk_hash(text),
                chunk_type=_guess_chunk_type(text, current_section),
                page_mapping_confidence=1.0 if page_start and page_end else 0.0,
            )
        )
        buffer = []
        page_start = 0
        page_end = 0

    for page in pages:
        raw_text = page.text or ""
        for line in raw_text.splitlines():
            section = _detect_section(line)
            if section:
                if buffer:
                    flush()
                current_section = section
                continue

        paragraphs = [_clean_paragraph(part) for part in re.split(r"\n\s*\n+", raw_text)]
        for paragraph in [part for part in paragraphs if part]:
            if not buffer:
                page_start = page.page_number
            projected = sum(len(part) for part in buffer) + len(paragraph) + 2 * len(buffer)
            if buffer and projected > max_chars and projected >= min_chars:
                flush()
                page_start = page.page_number
            buffer.append(paragraph)
            page_end = page.page_number

    flush()
    return chunks


def markdown_blocks(markdown_text: str) -> list[MarkdownBlock]:
    blocks: list[MarkdownBlock] = []
    current_section = ""
    raw_blocks = [part.strip() for part in re.split(r"\n\s*\n+", str(markdown_text or "")) if part.strip()]
    for block in raw_blocks:
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", block)
        if heading:
            current_section = heading.group(1).strip()
        blocks.append(MarkdownBlock(section_title=current_section, block_text=block, block_index=len(blocks)))
    return blocks


def chunk_markdown(markdown_text: str, *, max_chars: int = MAX_CHARS, min_chars: int = MIN_CHARS) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    current_section = ""
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        text = "\n\n".join(part for part in buffer if part).strip()
        if not text:
            buffer = []
            return
        chunks.append(
            TextChunk(
                section_title=current_section,
                page_start=None,
                page_end=None,
                chunk_text=text,
                chunk_index=len(chunks),
                token_count=_estimate_token_count(text),
                content_hash=_chunk_hash(text),
                chunk_type=_guess_chunk_type(text, current_section),
                page_mapping_confidence=0.0,
            )
        )
        buffer = []

    blocks = [part.strip() for part in re.split(r"\n\s*\n+", str(markdown_text or "")) if part.strip()]
    for block in blocks:
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", block)
        if heading:
            if buffer:
                flush()
            current_section = heading.group(1).strip()
            buffer.append(block)
            continue

        projected = sum(len(part) for part in buffer) + len(block) + 2 * len(buffer)
        if buffer and projected > max_chars and projected >= min_chars:
            flush()
        buffer.append(block)

    flush()
    return chunks


def chunk_markdown_with_pages(
    markdown_text: str,
    pages: list[PageLike],
    *,
    max_chars: int = MAX_CHARS,
    min_chars: int = MIN_CHARS,
) -> list[TextChunk]:
    chunks = chunk_markdown(markdown_text, max_chars=max_chars, min_chars=min_chars)
    if not pages:
        return chunks

    previous_page_start: int | None = None
    for chunk in chunks:
        page_start, page_end, confidence = _page_span_for_text(
            chunk.chunk_text,
            pages,
            min_page_number=previous_page_start,
        )
        chunk.page_start = page_start
        chunk.page_end = page_end
        chunk.page_mapping_confidence = confidence
        if page_start is not None:
            previous_page_start = page_start
    return chunks


def summarize_page_mapping(chunks: list[TextChunk]) -> dict[str, float | int]:
    total = len(chunks)
    mapped = 0
    confidence_sum = 0.0
    for chunk in chunks:
        if chunk.page_start and chunk.page_end:
            mapped += 1
            confidence_sum += float(chunk.page_mapping_confidence or 0.0)
    return {
        "total_chunks": total,
        "mapped_chunks": mapped,
        "coverage": round(mapped / total, 4) if total else 0.0,
        "average_confidence": round(confidence_sum / mapped, 4) if mapped else 0.0,
    }
