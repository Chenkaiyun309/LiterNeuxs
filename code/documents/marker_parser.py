#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from documents import page_extractor


class MarkerParseError(RuntimeError):
    """Raised when Marker is unavailable or cannot parse a document."""


@dataclass
class MarkerParseResult:
    markdown_text: str
    markdown_path: Path
    output_dir: Path
    page_count: int = 0
    engine: str = "marker"


def find_marker_cli() -> str:
    executable = shutil.which("marker_single")
    if executable:
        return executable
    raise MarkerParseError("未找到 Marker CLI。请先安装：python3 -m pip install marker-pdf")


def _select_markdown_file(output_dir: Path) -> Path:
    candidates = [
        path
        for path in output_dir.rglob("*.md")
        if path.is_file() and path.name.lower() not in {"readme.md"}
    ]
    if not candidates:
        raise MarkerParseError("Marker 未生成 Markdown 文件")
    return max(candidates, key=lambda path: (path.stat().st_size, path.stat().st_mtime))


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


_MARKDOWN_IMAGE_LINE_RE = re.compile(r"^\s*!\[[^\]]*]\(([^)]+)\)\s*$")
_FIGURE_CAPTION_RE = re.compile(r"^\s*(?:<span\b[^>]*>\s*</span>\s*)?\*\*(?:figure|fig\.|table)\b", re.I)
_MATRIX_RE = re.compile(
    r"\\begin\{(bmatrix|pmatrix|vmatrix|Vmatrix|matrix|array)\}(.*?)\\end\{\1\}",
    re.DOTALL,
)


def _next_non_empty_line(lines: list[str], index: int) -> str:
    for line in lines[index + 1 :]:
        if line.strip():
            return line.strip()
    return ""


def _marker_asset_path(markdown_path: Path, href: str) -> Path:
    clean_href = unquote(str(href or "").split("#", 1)[0].split("?", 1)[0]).strip()
    return (markdown_path.parent / clean_href).resolve()


def _image_size(path: Path) -> tuple[int, int] | None:
    try:
        from PIL import Image

        with Image.open(path) as image:
            return image.size
    except Exception:
        return None


def _is_decorative_marker_image(markdown_path: Path, href: str, next_line: str) -> bool:
    if _enabled("MARKER_KEEP_DECORATIVE_IMAGES"):
        return False
    asset_path = _marker_asset_path(markdown_path, href)
    if not asset_path.exists() or not asset_path.is_file():
        return False
    name = asset_path.name.lower()
    if "_figure_" in name or _FIGURE_CAPTION_RE.match(next_line or ""):
        return False
    size = _image_size(asset_path)
    if not size:
        return False
    width, height = size
    area = width * height
    marker_picture = re.search(r"_page_\d+_picture_\d+\.(?:jpe?g|png|webp)$", name) is not None
    if marker_picture and (height <= 220 or area <= 180_000):
        return True
    return False


def _clean_marker_markdown(markdown_text: str, markdown_path: Path) -> str:
    lines = str(markdown_text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cleaned: list[str] = []
    removed = 0
    for index, line in enumerate(lines):
        match = _MARKDOWN_IMAGE_LINE_RE.match(line)
        if match and _is_decorative_marker_image(markdown_path, match.group(1), _next_non_empty_line(lines, index)):
            removed += 1
            continue
        cleaned.append(line)
    text = _normalize_marker_headings(normalize_marker_math(_clean_marker_symbols("\n".join(cleaned)))).strip()
    if removed or text != str(markdown_text or "").strip():
        markdown_path.write_text(text + "\n", encoding="utf-8")
    return text


def _normalize_matrix_rows(match: re.Match) -> str:
    environment = match.group(1)
    body = match.group(2)
    body = re.sub(
        r"(?<!\\)\\[ \t]+(?=(?:[-+]?\d|\\Delta|\\[A-Za-z]+))",
        r"\\\\ ",
        body,
    )
    return f"\\begin{{{environment}}}{body}\\end{{{environment}}}"


def _merge_fragmented_display_math(markdown_text: str) -> str:
    lines = str(markdown_text or "").split("\n")
    output: list[str] = []
    index = 0
    while index < len(lines):
        display = re.match(r"^\s*\$\$(.+?)\$\$\s*$", lines[index])
        if not display:
            output.append(lines[index])
            index += 1
            continue
        parts = [display.group(1).strip()]
        labels: list[str] = []
        cursor = index + 1
        while cursor < len(lines):
            line = lines[cursor]
            inline_parts = re.findall(r"(?<!\$)\$([^$\n]+)\$(?!\$)", line)
            if not inline_parts:
                break
            residual = re.sub(r"(?<!\$)\$[^$\n]+\$(?!\$)", "", line)
            label = re.search(r"\(([A-Za-z]?\.?\d+(?:\.\d+)*)\)", residual)
            if label:
                labels.append(label.group(1))
                residual = residual.replace(label.group(0), "")
            if re.sub(r"[\s,;:.]+", "", residual):
                break
            parts.extend(item.strip() for item in inline_parts if item.strip())
            cursor += 1
        if cursor == index + 1:
            output.append(lines[index])
            index += 1
            continue
        body = r", \quad ".join(part.strip(" ,;.") for part in parts)
        if labels and r"\tag{" not in body:
            body += f" \\tag{{{labels[-1]}}}"
        output.append(f"$${body}$$")
        index = cursor
    return "\n".join(output)


def normalize_marker_math(markdown_text: str) -> str:
    text = str(markdown_text or "")
    text = re.sub(r"\\bm\s*\{([^{}]+)\}", r"\\boldsymbol{\1}", text)
    text = re.sub(r"\\bm\s*([A-Za-z])", r"\\boldsymbol{\1}", text)
    text = _MATRIX_RE.sub(_normalize_matrix_rows, text)
    return _merge_fragmented_display_math(text)


def _clean_marker_anchor_label(label: str) -> str:
    text = str(label or "")
    text = text.replace(r"\[", "[").replace(r"\]", "]")
    text = re.sub(r"\\(?=[\[\]().])", "", text)
    text = text.replace("\\", "")
    text = text.strip()
    if text.startswith("[") and text.endswith("]"):
        return text
    if re.fullmatch(r"\d+(?:[-–]\d+)?", text):
        return f"[{text}]"
    return text


def _clean_marker_symbols(markdown_text: str) -> str:
    text = str(markdown_text or "")
    text = re.sub(r"<span\b[^>]*\bid=[\"']page-\d+-\d+[\"'][^>]*>\s*</span>", "", text, flags=re.I)
    text = re.sub(
        r"\[\[([^\]]+?)\\?\]\]\(#page-\d+-\d+\)",
        lambda match: _clean_marker_anchor_label(f"[{match.group(1)}]"),
        text,
    )
    text = re.sub(
        r"\[((?:\\.|[^\]])+)\]\(#page-\d+-\d+\)",
        lambda match: _clean_marker_anchor_label(match.group(1)),
        text,
    )
    text = re.sub(r"\(#page-\d+-\d+\)", "", text)
    text = re.sub(r"<\s*(sup|sub)\s*>\s*(.*?)\s*<\s*/\s*\1\s*>", lambda match: f"<{match.group(1).lower()}>{match.group(2).strip()}</{match.group(1).lower()}>", text, flags=re.I | re.S)
    text = re.sub(r"([A-Za-z])\s*-\s+(\d+(?:[-–]\d+)?\b)", r"\1-\2", text)
    text = re.sub(r"\b(Ab)\s+\d+\s+(initio)\b", r"\1 \2", text, flags=re.I)
    text = re.sub(r"(?m)^(\d+)$", "", text)
    text = re.sub(r"(?m)^[ \t]*$\n?", lambda match: "\n" if "\n" in match.group(0) else "", text)
    text = text.replace("112�0", "112\u03050")
    text = re.sub(r"�E(?=[A-Za-zΑ-Ωα-ω])", "ΔE", text)
    text = re.sub(r"�(\d{3}¯)�", r"⟨\1⟩", text)
    text = re.sub(r"�(\*\*\d+\*\*¯?)\s*�", r"⟨\1⟩", text)
    text = re.sub(r"�(\d+¯?)�", r"⟨\1⟩", text)
    text = re.sub(r"/<(\d+¯?)>", r"⟨\1⟩", text)
    text = re.sub(r"<(\*{0,2}\d+\*{0,2}¯?)>", r"⟨\1⟩", text)
    text = re.sub(r"\*\*(\d+)\*\*¯", lambda match: f"**{_overbar_last_digit(match.group(1))}**", text)
    text = re.sub(r"(\d)¯", lambda match: match.group(1) + "\u0305", text)
    return text


def _strip_heading_markup(text: str) -> str:
    value = re.sub(r"\*\*([^*]+)\*\*", r"\1", str(text or ""))
    value = re.sub(r"\*([^*]+)\*", r"\1", value)
    return re.sub(r"\s+", " ", value).strip()


def _heading_level_after_title(raw_heading: str, original_level: int, has_main_heading: bool) -> int:
    plain = _strip_heading_markup(raw_heading)
    numeric = re.match(r"^(\d+(?:\.\d+)*)(?:[.)])?\s+\S+", plain)
    if numeric:
        return min(2 + numeric.group(1).count("."), 4)
    letter = re.match(r"^([A-Z])\.\s+(.+)", plain)
    if letter and not letter.group(2).isupper():
        return 3
    if re.match(r"^[IVXLCDM]+\.\s+\S+", plain, re.I):
        return 2
    if letter:
        return 3

    normalized = re.sub(r"[^a-z]+", " ", plain.lower()).strip()
    main_sections = {
        "abstract",
        "introduction",
        "background",
        "method",
        "methods",
        "methodology",
        "materials and methods",
        "results",
        "result",
        "results and discussion",
        "discussion",
        "conclusion",
        "conclusions",
        "references",
        "acknowledgement",
        "acknowledgements",
        "acknowledgment",
        "acknowledgments",
        "author contributions",
        "declarations",
        "declaration of competing interest",
        "competing interests",
        "open access",
    }
    if normalized in main_sections:
        return 2
    if original_level <= 2 and not has_main_heading:
        return 2
    return 3


def _looks_like_section_heading(raw_heading: str) -> bool:
    plain = _strip_heading_markup(raw_heading)
    if re.match(r"^\d+(?:\.\d+)*(?:[.)])?\s+\S+", plain):
        return True
    if re.match(r"^[IVXLCDM]+\.\s+\S+", plain, re.I):
        return True
    normalized = re.sub(r"[^a-z]+", " ", plain.lower()).strip()
    return normalized in {
        "abstract",
        "introduction",
        "background",
        "method",
        "methods",
        "methodology",
        "materials and methods",
        "results",
        "result",
        "results and discussion",
        "discussion",
        "conclusion",
        "conclusions",
        "references",
    }


def _normalize_marker_headings(markdown_text: str) -> str:
    lines = str(markdown_text or "").split("\n")
    normalized: list[str] = []
    seen_title = False
    has_main_heading = False
    for line in lines:
        match = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$", line)
        if not match:
            normalized.append(line)
            continue
        original_level = len(match.group(1))
        heading_text = match.group(2).strip()
        if not seen_title and not _looks_like_section_heading(heading_text):
            level = 1
            seen_title = True
        else:
            level = _heading_level_after_title(heading_text, original_level, has_main_heading)
            if level == 2:
                has_main_heading = True
            seen_title = True
        normalized.append(f"{'#' * level} {heading_text}")
    return "\n".join(normalized)


def _overbar_last_digit(value: str) -> str:
    text = str(value or "")
    if not text:
        return text
    return text[:-1] + text[-1] + "\u0305"


def _build_marker_command(
    marker: str,
    source: Path,
    target: Path,
    *,
    page_range: str = "",
    disable_images: bool = False,
) -> list[str]:
    command = [
        marker,
        str(source),
        "--output_dir",
        str(target),
        "--output_format",
        "markdown",
        "--disable_tqdm",
    ]
    if page_range:
        command.extend(["--page_range", page_range])
    if not _enabled("MARKER_ENABLE_OCR"):
        command.append("--disable_ocr")
    if not _enabled("MARKER_ENABLE_MULTIPROCESSING"):
        command.append("--disable_multiprocessing")
    if _enabled("MARKER_USE_LLM"):
        command.append("--use_llm")
    if disable_images or _enabled("MARKER_DISABLE_IMAGE_EXTRACTION"):
        command.append("--disable_image_extraction")
    return command


def _run_marker_command(command: list[str], target: Path, timeout_seconds: int, label: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=str(target),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MarkerParseError(
            f"{label}超时：{timeout_seconds} 秒。Marker 程序已安装，但模型加载/下载或 PDF 初始化未在限定时间内完成。"
            "请检查 HuggingFace 模型缓存、代理连接，或先在终端运行 marker_single 预热模型。"
        ) from exc


def preflight_marker(
    pdf_path: str | Path,
    output_dir: str | Path,
    *,
    timeout_seconds: int = 180,
) -> dict[str, object]:
    source = Path(pdf_path).expanduser().resolve()
    if not source.exists():
        raise MarkerParseError("PDF 文件不存在")
    if not source.is_file():
        raise MarkerParseError("PDF 路径不是文件")

    target = Path(output_dir).expanduser().resolve()
    preflight_dir = target / "_preflight"
    if preflight_dir.exists():
        shutil.rmtree(preflight_dir)
    preflight_dir.mkdir(parents=True, exist_ok=True)
    marker = find_marker_cli()
    command = _build_marker_command(
        marker,
        source,
        preflight_dir,
        page_range="0",
        disable_images=True,
    )
    started_at = time.monotonic()
    try:
        completed = _run_marker_command(command, preflight_dir, timeout_seconds, "Marker 预检")
        elapsed = round(time.monotonic() - started_at, 2)
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "Marker 预检失败").strip()
            raise MarkerParseError(f"Marker 预检失败：{message[-1600:]}")
        try:
            _select_markdown_file(preflight_dir)
        except MarkerParseError as exc:
            raise MarkerParseError("Marker 预检完成但没有生成 Markdown；请检查该 PDF 是否可解析。") from exc
        return {
            "marker": marker,
            "elapsed_seconds": elapsed,
            "timeout_seconds": timeout_seconds,
        }
    finally:
        shutil.rmtree(preflight_dir, ignore_errors=True)


def parse_pdf_to_markdown(
    pdf_path: str | Path,
    output_dir: str | Path,
    *,
    timeout_seconds: int = 1800,
) -> MarkerParseResult:
    source = Path(pdf_path).expanduser().resolve()
    if not source.exists():
        raise MarkerParseError("PDF 文件不存在")
    if not source.is_file():
        raise MarkerParseError("PDF 路径不是文件")

    target = Path(output_dir).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    marker = find_marker_cli()
    command = _build_marker_command(marker, source, target)

    completed = _run_marker_command(command, target, timeout_seconds, "Marker 解析")

    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "Marker 解析失败").strip()
        raise MarkerParseError(message[-1800:])

    markdown_path = _select_markdown_file(target)
    markdown_text = markdown_path.read_text(encoding="utf-8", errors="replace").strip()
    markdown_text = _clean_marker_markdown(markdown_text, markdown_path)
    if not markdown_text:
        raise MarkerParseError("Marker 生成的 Markdown 为空")
    page_count = 0
    try:
        page_count = page_extractor.get_pdf_page_count(source)
    except Exception:
        page_count = 0
    return MarkerParseResult(
        markdown_text=markdown_text,
        markdown_path=markdown_path,
        output_dir=target,
        page_count=page_count,
    )
