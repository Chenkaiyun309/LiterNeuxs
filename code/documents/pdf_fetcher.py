#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import requests


DEFAULT_TIMEOUT = (15, 90)
DEFAULT_MAX_BYTES = 80 * 1024 * 1024
DEFAULT_MIN_BYTES = 1024


class PdfFetchError(RuntimeError):
    """Raised when a PDF cannot be downloaded or validated."""


@dataclass
class PdfFetchResult:
    path: Path
    size_bytes: int
    content_type: str


def safe_filename_part(value: str, fallback: str = "paper") -> str:
    text = re.sub(r"[^\w.\-]+", "_", str(value or "").strip(), flags=re.UNICODE)
    text = re.sub(r"_+", "_", text).strip("._")
    return text[:120] or fallback


def unique_pdf_path(directory: Path, base_name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stem = safe_filename_part(base_name)
    candidate = directory / f"{stem}.pdf"
    index = 2
    while candidate.exists():
        candidate = directory / f"{stem}_{index}.pdf"
        index += 1
    return candidate


def _looks_like_pdf(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(5) == b"%PDF-"


def _validate_content_type(content_type: str, sniffed_pdf: bool) -> None:
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    accepted = {
        "application/pdf",
        "application/x-pdf",
        "application/octet-stream",
        "binary/octet-stream",
    }
    if normalized in accepted and sniffed_pdf:
        return
    if not normalized and sniffed_pdf:
        return
    raise PdfFetchError(f"响应不是有效 PDF，Content-Type={content_type or '空'}")


def _response_filename(url: str, content_disposition: str) -> str:
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', content_disposition or "", re.I)
    if match:
        return safe_filename_part(match.group(1))
    name = Path(urlparse(url).path).name
    if name.lower().endswith(".pdf"):
        return safe_filename_part(Path(name).stem)
    return ""


def download_pdf(
    pdf_url: str,
    target_dir: str | Path,
    *,
    filename_prefix: str,
    retries: int = 2,
    timeout: tuple[int, int] = DEFAULT_TIMEOUT,
    min_bytes: int = DEFAULT_MIN_BYTES,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> PdfFetchResult:
    url = str(pdf_url or "").strip()
    if not url:
        raise PdfFetchError("缺少 PDF URL")
    if not re.match(r"^https?://", url, flags=re.I):
        raise PdfFetchError("PDF URL 必须以 http:// 或 https:// 开头")

    target_directory = Path(target_dir)
    last_error: Exception | None = None
    headers = {"User-Agent": "LiterNexus/3.2 PDF Fetcher"}

    for attempt in range(retries + 1):
        temp_path: Path | None = None
        try:
            with requests.get(url, stream=True, timeout=timeout, headers=headers, allow_redirects=True) as response:
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "")
                remote_name = _response_filename(url, response.headers.get("Content-Disposition", ""))
                base_name = filename_prefix
                if remote_name and remote_name.lower() not in base_name.lower():
                    base_name = f"{filename_prefix}_{remote_name}"
                final_path = unique_pdf_path(target_directory, base_name)
                temp_path = final_path.with_suffix(".part")

                size = 0
                with temp_path.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 128):
                        if not chunk:
                            continue
                        size += len(chunk)
                        if size > max_bytes:
                            raise PdfFetchError(f"PDF 文件超过大小限制：{max_bytes // (1024 * 1024)} MB")
                        handle.write(chunk)

                if size < min_bytes:
                    raise PdfFetchError(f"PDF 文件过小：{size} bytes")
                _validate_content_type(content_type, _looks_like_pdf(temp_path))
                temp_path.replace(final_path)
                return PdfFetchResult(path=final_path, size_bytes=size, content_type=content_type)
        except Exception as exc:
            last_error = exc
            if temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)
            if attempt < retries:
                time.sleep(0.8 * (attempt + 1))

    raise PdfFetchError(str(last_error or "PDF 下载失败"))


def save_uploaded_pdf(
    file_storage,
    target_dir: str | Path,
    *,
    filename_prefix: str,
    original_filename: str = "",
    min_bytes: int = DEFAULT_MIN_BYTES,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> PdfFetchResult:
    suffix_name = safe_filename_part(Path(original_filename or "uploaded").stem, "uploaded")
    final_path = unique_pdf_path(Path(target_dir), f"{filename_prefix}_{suffix_name}")
    temp_path = final_path.with_suffix(".part")
    file_storage.save(temp_path)
    size = temp_path.stat().st_size
    try:
        if size < min_bytes:
            raise PdfFetchError(f"PDF 文件过小：{size} bytes")
        if size > max_bytes:
            raise PdfFetchError(f"PDF 文件超过大小限制：{max_bytes // (1024 * 1024)} MB")
        if not _looks_like_pdf(temp_path):
            raise PdfFetchError("上传文件不是有效 PDF")
        temp_path.replace(final_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return PdfFetchResult(path=final_path, size_bytes=size, content_type="application/pdf")
