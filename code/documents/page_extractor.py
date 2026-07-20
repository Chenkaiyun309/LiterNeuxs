#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class PageExtractError(RuntimeError):
    """Raised when PDF page text cannot be extracted."""


@dataclass
class ExtractedPage:
    page_number: int
    text: str


def _load_fitz():
    try:
        import fitz  # type: ignore

        return fitz
    except Exception as exc:  # pragma: no cover - import failure depends on env
        raise PageExtractError("未安装 PyMuPDF（pymupdf），无法提取 PDF 页文本") from exc


def extract_pdf_pages(pdf_path: str | Path) -> list[ExtractedPage]:
    source = Path(pdf_path).expanduser().resolve()
    if not source.exists():
        raise PageExtractError("PDF 文件不存在")
    if not source.is_file():
        raise PageExtractError("PDF 路径不是文件")

    fitz = _load_fitz()
    pages: list[ExtractedPage] = []
    try:
        with fitz.open(source) as document:
            for index, page in enumerate(document, start=1):
                text = page.get_text("text", sort=True)
                pages.append(ExtractedPage(page_number=index, text=(text or "").strip()))
    except PageExtractError:
        raise
    except Exception as exc:
        raise PageExtractError(f"提取 PDF 页文本失败：{exc}") from exc
    return pages


def get_pdf_page_count(pdf_path: str | Path) -> int:
    source = Path(pdf_path).expanduser().resolve()
    if not source.exists():
        raise PageExtractError("PDF 文件不存在")
    if not source.is_file():
        raise PageExtractError("PDF 路径不是文件")

    fitz = _load_fitz()
    try:
        with fitz.open(source) as document:
            return int(document.page_count or 0)
    except Exception as exc:
        raise PageExtractError(f"读取 PDF 页数失败：{exc}") from exc
