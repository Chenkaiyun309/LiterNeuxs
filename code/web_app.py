#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import importlib.util
import subprocess
import threading
import logging
import shutil
import json
import re
import math
import html
import webbrowser
import sqlite3
import uuid
import traceback
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from datetime import datetime, timedelta

REQUIRED_PACKAGES = {
    "flask": "flask",
    "pandas": "pandas",
    "requests": "requests",
}
missing_packages = [
    package for module_name, package in REQUIRED_PACKAGES.items()
    if importlib.util.find_spec(module_name) is None
]
if missing_packages and "--check" in sys.argv:
    print(f"检查失败，缺少依赖: {', '.join(missing_packages)}")
    print("请运行: python3 -m pip install -r requirements.txt")
    raise SystemExit(1)

from flask import Flask, render_template, request, jsonify, send_from_directory, send_file, redirect, url_for
import pandas as pd
import requests
from markupsafe import Markup
from werkzeug.utils import secure_filename

# ---------------------------------------------------------------------------
# 路径定位：兼容「源码运行」和「PyInstaller 打包后运行」两种场景
# - FROZEN_DIR：打包后 exe 所在目录（用户数据写入处）；源码运行时回退到项目根
# - BUNDLE_DIR：打包后资源解压目录 _MEIPASS（模板/静态资源）；源码运行时回退到 code/
# ---------------------------------------------------------------------------
def _is_frozen() -> bool:
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")

FROZEN_DIR = Path(sys.executable).resolve().parent if _is_frozen() else Path(__file__).resolve().parent.parent
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", "")) if _is_frozen() else Path(__file__).resolve().parent

# 添加项目目录到 Python 路径，以便从任意工作目录启动
sys.path.insert(0, str(BUNDLE_DIR))
sys.path.insert(0, str(FROZEN_DIR))

try:
    from data_sources import semantic_scholar as scholar
except ImportError as e:
    print(f"导入 Semantic Scholar 数据源失败: {e}")
    scholar = None

try:
    from reports import daily_report as report
except ImportError as e:
    print(f"导入 daily_report 失败: {e}")
    report = None

try:
    from reports import config_store as report_config_store
except ImportError as e:
    print(f"导入综述配置模块失败: {e}")
    report_config_store = None

try:
    from search import fulltext_search, multi_source_search, literature_store
except ImportError as e:
    print(f"导入 multi_source_search 失败: {e}")
    fulltext_search = None
    multi_source_search = None
    literature_store = None

try:
    from domain import materials_vocab
except ImportError as e:
    print(f"导入 materials_vocab 失败: {e}")
    materials_vocab = None

try:
    from graph import graph_builder
except ImportError as e:
    print(f"导入 graph_builder 失败: {e}")
    graph_builder = None

try:
    from graph import config_store as graph_config_store
except ImportError as e:
    print(f"导入图谱配置模块失败: {e}")
    graph_config_store = None

try:
    from documents import chunker, marker_parser, parse_quality, pdf_fetcher, pdf_store, page_extractor
except ImportError as e:
    print(f"导入 PDF 文档模块失败: {e}")
    chunker = None
    marker_parser = None
    parse_quality = None
    pdf_fetcher = None
    pdf_store = None
    page_extractor = None

try:
    from qa import config_store, history_store, local_reranker, qa_service, qa_store, retriever
except ImportError as e:
    print(f"导入 QA 模块失败: {e}")
    config_store = None
    history_store = None
    local_reranker = None
    qa_service = None
    qa_store = None
    retriever = None

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 配置路径
# - 用户数据（检索结果、报告、数据库）写到 exe 所在目录 FROZEN_DIR
# - 程序资源（模板、静态文件、logo）从资源目录读取：
#     打包后都在 _MEIPASS(BUNDLE_DIR)；源码模式下 templates/static 在 code/，logo 在项目根
PROJECT_DIR = FROZEN_DIR
LEGACY_SEARCH_RESULTS_DIR = PROJECT_DIR / "Literature_search_results"
LEGACY_OUTPUTS_DIR = PROJECT_DIR / "report_outputs"
LITERNEXUS_OUTPUTS_DIR = PROJECT_DIR / "LiterNexus_outputs"
LEGACY_BRAND_OUTPUTS_DIR = PROJECT_DIR / "ScholarFlow_outputs"
if LEGACY_BRAND_OUTPUTS_DIR.exists() and not LITERNEXUS_OUTPUTS_DIR.exists():
    shutil.move(str(LEGACY_BRAND_OUTPUTS_DIR), str(LITERNEXUS_OUTPUTS_DIR))
WORKSPACE_OUTPUTS_DIR = LITERNEXUS_OUTPUTS_DIR
SEARCH_RESULTS_DIR = WORKSPACE_OUTPUTS_DIR / "literature"
METADATA_DIR = SEARCH_RESULTS_DIR / "metadata"
METADATA_CSV_DIR = METADATA_DIR / "csv"
METADATA_JSON_DIR = METADATA_DIR / "json"
PDF_CACHE_DIR = SEARCH_RESULTS_DIR / "pdfs"
LEGACY_PDF_CACHE_DIR = LEGACY_SEARCH_RESULTS_DIR / "pdfs"
MARKER_OUTPUT_DIR = SEARCH_RESULTS_DIR / "marker"
LEGACY_MARKER_OUTPUT_DIR = LEGACY_SEARCH_RESULTS_DIR / "marker"
OUTPUTS_DIR = WORKSPACE_OUTPUTS_DIR / "reports"
LOGO_DIR = (BUNDLE_DIR / "logo") if _is_frozen() else (FROZEN_DIR / "logo")
DOCS_DIR = (BUNDLE_DIR / "docs") if _is_frozen() else (FROZEN_DIR / "docs")
TEMPLATES_DIR = BUNDLE_DIR / "templates"
STATIC_DIR = BUNDLE_DIR / "static"
LITERATURE_LIBRARY_DB = SEARCH_RESULTS_DIR / "literature_library.sqlite"
CURRENT_PARSE_ENGINE = "marker"
KNOWLEDGE_QA_CONFIG_PATH = WORKSPACE_OUTPUTS_DIR / "config" / "knowledge_qa.json"
KNOWLEDGE_GRAPH_CONFIG_PATH = WORKSPACE_OUTPUTS_DIR / "config" / "knowledge_graph.json"
REPORT_GENERATION_CONFIG_PATH = WORKSPACE_OUTPUTS_DIR / "config" / "report_generation.json"
KNOWLEDGE_QA_DIR = WORKSPACE_OUTPUTS_DIR / "knowledge_qa"
KNOWLEDGE_QA_DB = KNOWLEDGE_QA_DIR / "knowledge_qa.sqlite"
KNOWLEDGE_QA_HISTORY_DIR = KNOWLEDGE_QA_DIR / "history"
KNOWLEDGE_QA_MODELS_DIR = WORKSPACE_OUTPUTS_DIR / "models" / "reranker"


def parse_quality_payload(fulltext) -> dict:
    if not fulltext:
        return {
            "parse_quality": "",
            "page_mapping_coverage": 0.0,
            "text_length": 0,
            "quality_warnings": [],
        }
    warnings = []
    raw_warnings = fulltext["quality_warnings_json"] if "quality_warnings_json" in fulltext.keys() else "[]"
    try:
        parsed = json.loads(raw_warnings or "[]")
        if isinstance(parsed, list):
            warnings = [str(item).strip() for item in parsed if str(item).strip()]
    except Exception:
        warnings = []
    return {
        "parse_quality": (fulltext["parse_quality"] if "parse_quality" in fulltext.keys() else "") or "",
        "page_mapping_coverage": float((fulltext["page_mapping_coverage"] if "page_mapping_coverage" in fulltext.keys() else 0) or 0.0),
        "text_length": int((fulltext["text_length"] if "text_length" in fulltext.keys() else 0) or 0),
        "quality_warnings": warnings,
    }


def summarize_quality_warnings(warnings, *, limit: int = 2) -> str:
    items = [str(item).strip() for item in (warnings or []) if str(item).strip()]
    if not items:
        return ""
    visible = items[: max(1, int(limit or 1))]
    extra = len(items) - len(visible)
    text = "；".join(visible)
    if extra > 0:
        text += f" 等 {extra + len(visible)} 项"
    return text

# 确保必要的目录存在
WORKSPACE_OUTPUTS_DIR.mkdir(exist_ok=True)
SEARCH_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
METADATA_CSV_DIR.mkdir(parents=True, exist_ok=True)
METADATA_JSON_DIR.mkdir(parents=True, exist_ok=True)
PDF_CACHE_DIR.mkdir(exist_ok=True)
MARKER_OUTPUT_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)
TEMPLATES_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)

legacy_library_db = LEGACY_SEARCH_RESULTS_DIR / "literature_library.sqlite"
if not LITERATURE_LIBRARY_DB.exists() and legacy_library_db.exists():
    for suffix in ("", "-wal", "-shm"):
        legacy_part = Path(f"{legacy_library_db}{suffix}")
        target_part = Path(f"{LITERATURE_LIBRARY_DB}{suffix}")
        if legacy_part.exists() and not target_part.exists():
            shutil.copy2(legacy_part, target_part)

app = Flask(__name__, 
            template_folder=str(TEMPLATES_DIR),
            static_folder=str(STATIC_DIR))
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-local-secret")
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# 全局变量存储任务状态
tasks = {}

class TaskManager:
    def __init__(self):
        self.tasks = {}
        self.lock = threading.Lock()
    
    def add_task(self, task_id, name, target_func, *args, **kwargs):
        with self.lock:
            self.tasks[task_id] = {
                'id': task_id,
                'name': name,
                'status': 'running',
                'progress': 0,
                'logs': [],
                'result': None,
                'error': None,
                'debug': {}
            }
        
        def wrapper():
            try:
                result = target_func(*args, **kwargs)
                with self.lock:
                    self.tasks[task_id]['status'] = 'completed'
                    self.tasks[task_id]['result'] = result
            except Exception as e:
                with self.lock:
                    self.tasks[task_id]['status'] = 'failed'
                    self.tasks[task_id]['error'] = str(e)
                    self.tasks[task_id]['debug']['traceback'] = traceback.format_exc(limit=25)
                logger.error(f"Task {task_id} failed: {e}")
        
        thread = threading.Thread(target=wrapper, daemon=True)
        thread.start()
        return task_id
    
    def get_task(self, task_id):
        with self.lock:
            return self.tasks.get(task_id)
    
    def add_log(self, task_id, message):
        with self.lock:
            if task_id in self.tasks:
                self.tasks[task_id]['logs'].append({
                    'timestamp': datetime.now().isoformat(),
                    'message': message
                })

    def set_progress(self, task_id, progress):
        with self.lock:
            if task_id in self.tasks:
                self.tasks[task_id]['progress'] = max(0, min(100, int(progress)))

task_manager = TaskManager()

def log_to_task(task_id, message):
    """将日志消息发送到特定任务"""
    task_manager.add_log(task_id, message)
    logger.info(f"[Task {task_id}] {message}")


def progress_to_task(task_id, progress, message=None):
    """更新任务进度，并可选写入运行日志。"""
    task_manager.set_progress(task_id, progress)
    if message:
        log_to_task(task_id, message)


def set_task_debug(task_id, **payload):
    """Merge structured debug data into a task for UI-safe diagnostics."""
    with task_manager.lock:
        task = task_manager.tasks.get(task_id)
        if not task:
            return
        debug = task.setdefault('debug', {})
        for key, value in payload.items():
            debug[key] = value


def compact_graph_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def compact_graph_evidence(item: dict, text_limit: int = 280) -> dict:
    evidence_text = str(item.get("evidence_text") or item.get("evidence") or "").strip()
    return {
        "paper_id": str(item.get("paper_id") or "").strip(),
        "section": str(item.get("section") or "").strip(),
        "page": str(item.get("page") or "").strip(),
        "evidence_text": evidence_text[:text_limit],
        "chunk_id": str(item.get("chunk_id") or "").strip(),
        "page_mapping_confidence": round(compact_graph_float(item.get("page_mapping_confidence")), 3),
        "parse_quality": str(item.get("parse_quality") or "unknown").strip(),
        "evidence_quality": round(compact_graph_float(item.get("evidence_quality")), 3),
    }


def compact_graph_result(result: dict) -> dict:
    compact = dict(result or {})

    nodes = []
    for node in result.get("nodes", []):
        node_copy = dict(node)
        paper_details = []
        for paper in node.get("paper_details", [])[:3]:
            paper_copy = dict(paper)
            paper_copy["abstract"] = str(paper_copy.get("abstract") or "")[:500]
            paper_details.append(paper_copy)
        node_copy["paper_details"] = paper_details
        nodes.append(node_copy)
    compact["nodes"] = nodes

    edges = []
    for edge in result.get("edges", []):
        edge_copy = dict(edge)
        evidence_items = list(edge.get("evidence") or [])
        if not evidence_items and edge.get("evidence_text"):
            evidence_items = [edge]
        compact_evidence = []
        seen_evidence = set()
        for evidence in evidence_items:
            item = compact_graph_evidence(evidence)
            evidence_key = (
                item["paper_id"],
                item["section"],
                item["page"],
                re.sub(r"\s+", " ", item["evidence_text"]).casefold(),
            )
            if not item["evidence_text"] or evidence_key in seen_evidence:
                continue
            seen_evidence.add(evidence_key)
            compact_evidence.append(item)
            if len(compact_evidence) >= 2:
                break
        edge_copy["evidence"] = compact_evidence
        first = compact_evidence[0] if compact_evidence else compact_graph_evidence(edge)
        for field in ("paper_id", "section", "page", "evidence_text"):
            edge_copy[field] = first[field]
        edges.append(edge_copy)
    compact["edges"] = edges

    source_triplets = result.get("triplets", [])
    compact["triplet_count"] = len(source_triplets)
    triplets = []
    seen_triplets = set()
    for triplet in source_triplets:
        evidence = compact_graph_evidence(triplet, text_limit=180)
        triplet_key = (
            str(triplet.get("subject") or "").casefold(),
            str(triplet.get("relation") or "").casefold(),
            str(triplet.get("object") or "").casefold(),
            evidence["paper_id"],
            evidence["section"],
            evidence["page"],
            re.sub(r"\s+", " ", evidence["evidence_text"]).casefold(),
        )
        if triplet_key in seen_triplets:
            continue
        seen_triplets.add(triplet_key)
        triplets.append({
            "subject": triplet.get("subject", ""),
            "subject_type": triplet.get("subject_type", ""),
            "relation": triplet.get("relation", ""),
            "object": triplet.get("object", ""),
            "object_type": triplet.get("object_type", ""),
            "confidence": triplet.get("confidence", 0),
            **evidence,
        })
        if len(triplets) >= 40:
            break
    compact["triplets"] = triplets
    compact["response_compacted"] = True
    return compact


REPORT_FILE_SUFFIXES = {".md", ".markdown", ".json", ".txt", ".pdf"}
TEXT_REPORT_FILE_SUFFIXES = {".md", ".markdown", ".json", ".txt"}


def render_inline_markdown(text: str) -> str:
    value = html.escape(str(text or ""))
    value = re.sub(r"`([^`]+)`", r"<code>\1</code>", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", value)
    value = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", value)
    value = re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)\)",
        lambda match: (
            f'<a href="{html.escape(match.group(2), quote=True)}" '
            f'target="_blank" rel="noopener noreferrer">{match.group(1)}</a>'
        )
        if re.match(r"^(https?://|mailto:|#|/)", match.group(2))
        else html.escape(match.group(1)),
        value,
    )
    return value


def markdown_table_to_html(lines: list[str]) -> str:
    rows = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        rows.append(cells)
    if len(rows) < 2:
        return ""
    header = rows[0]
    body = rows[2:]
    thead = "".join(f"<th>{render_inline_markdown(cell)}</th>" for cell in header)
    body_rows = []
    for row in body:
        body_rows.append(
            "<tr>" + "".join(f"<td>{render_inline_markdown(cell)}</td>" for cell in row) + "</tr>"
        )
    return (
        '<div class="markdown-table-wrap"><table>'
        f"<thead><tr>{thead}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table></div>"
    )


def render_user_guide_markdown(markdown_text: str) -> str:
    lines = str(markdown_text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    list_type = ""
    code_lines: list[str] = []
    in_code = False
    i = 0

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            blocks.append(f"<p>{render_inline_markdown(' '.join(paragraph))}</p>")
            paragraph = []

    def flush_list() -> None:
        nonlocal list_items, list_type
        if list_items:
            tag = list_type or "ul"
            blocks.append(f"<{tag}>" + "".join(list_items) + f"</{tag}>")
            list_items = []
            list_type = ""

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code:
                blocks.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
                code_lines = []
                in_code = False
            else:
                flush_paragraph()
                flush_list()
                in_code = True
                code_lines = []
            i += 1
            continue

        if in_code:
            code_lines.append(line)
            i += 1
            continue

        if not stripped:
            flush_paragraph()
            flush_list()
            i += 1
            continue

        image_match = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", stripped)
        if image_match:
            flush_paragraph()
            flush_list()
            alt = html.escape(image_match.group(1), quote=True)
            src = image_match.group(2).strip()
            if src.startswith("screenshots/"):
                src = f"/user_guide/assets/{html.escape(src, quote=True)}"
            else:
                src = html.escape(src, quote=True)
            blocks.append(f'<figure><img src="{src}" alt="{alt}"><figcaption>{alt}</figcaption></figure>')
            i += 1
            continue

        if stripped.startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?[\s:\-|]+\|[\s:\-|]*$", lines[i + 1]):
            flush_paragraph()
            flush_list()
            table_lines = [stripped, lines[i + 1].strip()]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            table_html = markdown_table_to_html(table_lines)
            if table_html:
                blocks.append(table_html)
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading_match:
            flush_paragraph()
            flush_list()
            level = len(heading_match.group(1))
            blocks.append(f"<h{level}>{render_inline_markdown(heading_match.group(2))}</h{level}>")
            i += 1
            continue

        unordered_match = re.match(r"^[-*]\s+(.+)$", stripped)
        ordered_match = re.match(r"^\d+\.\s+(.+)$", stripped)
        if unordered_match or ordered_match:
            flush_paragraph()
            new_type = "ol" if ordered_match else "ul"
            if list_type and list_type != new_type:
                flush_list()
            list_type = new_type
            item_text = ordered_match.group(1) if ordered_match else unordered_match.group(1)
            list_items.append(f"<li>{render_inline_markdown(item_text)}</li>")
            i += 1
            continue

        paragraph.append(stripped)
        i += 1

    flush_paragraph()
    flush_list()
    if in_code:
        blocks.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
    return "\n".join(blocks)


def resolve_path_from_input(file_path: str) -> Path:
    raw_path = Path(file_path).expanduser()
    full_path = raw_path if raw_path.is_absolute() else PROJECT_DIR / raw_path
    return full_path.resolve()


def resolve_project_file(file_path: str) -> Path:
    resolved = resolve_path_from_input(file_path)
    project_root = PROJECT_DIR.resolve()
    if resolved != project_root and project_root not in resolved.parents:
        raise ValueError("File path is outside project directory")
    return resolved


def resolve_allowed_file(file_path: str) -> Path:
    raw_path = Path(file_path).expanduser()
    suffix = raw_path.suffix.lower()
    if suffix == ".csv":
        return resolve_project_file(file_path)
    if suffix in REPORT_FILE_SUFFIXES:
        return resolve_path_from_input(file_path)
    raise ValueError("Unsupported file type")


def resolve_default_dialog_dir(path_value: str, fallback: Path) -> Path:
    raw_value = (path_value or "").strip()
    candidate = Path(raw_value).expanduser() if raw_value else fallback
    if not candidate.is_absolute():
        candidate = PROJECT_DIR / candidate

    if candidate.is_file():
        candidate = candidate.parent
    elif candidate.suffix:
        candidate = candidate.parent

    if not candidate.exists() or not candidate.is_dir():
        candidate = fallback
    return candidate.resolve()


def iter_search_csv_files() -> list[Path]:
    """CSV metadata files, including legacy root-level search results."""
    candidates: list[Path] = []
    seen: set[Path] = set()
    for directory in (METADATA_CSV_DIR, LEGACY_SEARCH_RESULTS_DIR, SEARCH_RESULTS_DIR):
        if not directory.exists():
            continue
        for path in directory.glob("*.csv"):
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                candidates.append(path)
    return sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True)


def iter_report_files() -> list[Path]:
    """Report outputs, including the legacy report_outputs directory."""
    suffixes = {".md", ".pdf"}
    candidates: list[Path] = []
    seen: set[Path] = set()
    for directory in (OUTPUTS_DIR, LEGACY_OUTPUTS_DIR):
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path.suffix.lower() not in suffixes:
                continue
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                candidates.append(path)
    return sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True)


def iter_report_json_files() -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()
    for directory in (OUTPUTS_DIR, LEGACY_OUTPUTS_DIR):
        if not directory.exists():
            continue
        for path in directory.rglob("*.json"):
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                candidates.append(path)
    return sorted(candidates)


def path_is_under_any(path: Path, roots: list[Path]) -> bool:
    resolved_path = path.resolve()
    for root in roots:
        resolved_root = root.resolve()
        if resolved_path == resolved_root or resolved_root in resolved_path.parents:
            return True
    return False


def escape_applescript_posix_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace('"', '\\"')


def get_selected_sources(data: dict) -> list[str]:
    if multi_source_search is None:
        return []
    sources = data.get("selected_sources")
    if isinstance(sources, list):
        return [source for source in sources if source in multi_source_search.ALL_SOURCES]
    return []


def get_source_credentials(data: dict) -> dict[str, str]:
    credentials = data.get("source_credentials")
    if not isinstance(credentials, dict):
        credentials = {}
    return {
        "semantic_scholar_api_key": str(credentials.get("semantic_scholar_api_key") or data.get("api_key") or "").strip(),
        "openalex_email": str(credentials.get("openalex_email") or "").strip(),
        "crossref_email": str(credentials.get("crossref_email") or "").strip(),
        "pubmed_api_key": str(credentials.get("pubmed_api_key") or "").strip(),
        "pubmed_email": str(credentials.get("pubmed_email") or "").strip(),
        "springer_nature_api_key": str(credentials.get("springer_nature_api_key") or "").strip(),
        "springer_nature_api_type": str(credentials.get("springer_nature_api_type") or "openaccess").strip(),
    }


def log_database_credential_hints(task_id: str, selected_sources: list[str], credentials: dict[str, str]) -> None:
    if "semantic_scholar" in selected_sources and not credentials.get("semantic_scholar_api_key"):
        log_to_task(task_id, "未填写 Semantic Scholar 访问密钥，将按未认证请求抓取，可能更容易限流。")
    if "openalex" in selected_sources and not credentials.get("openalex_email"):
        log_to_task(task_id, "OpenAlex 不需要访问密钥；建议填写联系邮箱以使用更稳定的服务通道。")
    if "crossref" in selected_sources and not credentials.get("crossref_email"):
        log_to_task(task_id, "Crossref 不需要访问密钥；建议填写联系邮箱以便进入更稳定的服务通道。")
    if "pubmed" in selected_sources:
        if not credentials.get("pubmed_api_key"):
            log_to_task(task_id, "PubMed 可不填访问密钥；填写 NCBI 访问密钥后请求额度更高。")
        if not credentials.get("pubmed_email"):
            log_to_task(task_id, "建议为 PubMed 填写联系邮箱，符合 NCBI E-utilities 使用建议。")
    if "arxiv" in selected_sources:
        log_to_task(task_id, "arXiv 不需要访问密钥。")
    if "springer_nature" in selected_sources and not credentials.get("springer_nature_api_key"):
        log_to_task(task_id, "Springer Nature 开放获取接口或元数据接口需要访问密钥；未填写时将跳过 Springer Nature。")


def call_structured_llm_chat(
    *,
    prompt: str,
    model: str,
    provider: str,
    base_url: str,
    api_key: str,
    temperature: float = 0,
    top_p: float = 0.9,
    num_predict: int = 1800,
    request_timeout_sec: int = 900,
    system_prompt: str = "",
) -> dict:
    messages = []
    if system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt.strip()})
    messages.append({"role": "user", "content": prompt})

    if provider == "openai_compatible":
        if not base_url:
            raise RuntimeError("远程大模型 Base URL 为空。")
        if not api_key:
            raise RuntimeError("远程大模型访问密钥为空。")
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": num_predict,
        }
        response = requests.post(url, headers=headers, json=payload, timeout=(20, max(30, int(request_timeout_sec))))
        response.raise_for_status()
        data = response.json()
        usage = data.get("usage") or {}
        return {
            "content": str(data["choices"][0]["message"]["content"] or ""),
            "finish_reason": str(data["choices"][0].get("finish_reason") or ""),
            "token_usage": {
                "prompt_tokens": usage.get("prompt_tokens") if isinstance(usage.get("prompt_tokens"), int) else None,
                "completion_tokens": usage.get("completion_tokens") if isinstance(usage.get("completion_tokens"), int) else None,
                "total_tokens": usage.get("total_tokens") if isinstance(usage.get("total_tokens"), int) else None,
            },
        }

    url = f"{base_url.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "top_p": top_p,
            "num_predict": num_predict,
        },
    }
    response = requests.post(url, json=payload, timeout=(20, max(30, int(request_timeout_sec))))
    response.raise_for_status()
    data = response.json()
    prompt_tokens = data.get("prompt_eval_count")
    completion_tokens = data.get("eval_count")
    token_usage = {
        "prompt_tokens": prompt_tokens if isinstance(prompt_tokens, int) else None,
        "completion_tokens": completion_tokens if isinstance(completion_tokens, int) else None,
    }
    if token_usage["prompt_tokens"] is not None or token_usage["completion_tokens"] is not None:
        token_usage["total_tokens"] = (token_usage["prompt_tokens"] or 0) + (token_usage["completion_tokens"] or 0)
    else:
        token_usage["total_tokens"] = None
    return {
        "content": str((data.get("message") or {}).get("content") or ""),
        "finish_reason": str(data.get("done_reason") or ""),
        "token_usage": token_usage,
    }


def load_knowledge_qa_settings() -> dict:
    if config_store is None:
        return {}
    return config_store.load_settings(KNOWLEDGE_QA_CONFIG_PATH)


def call_openai_compatible_embeddings(texts: list[str], settings: dict) -> list[list[float]]:
    base_url = str(settings.get("embedding_base_url") or settings.get("base_url") or "").strip().rstrip("/")
    api_key = str(settings.get("embedding_api_key") or settings.get("api_key") or "").strip()
    model = str(settings.get("embedding_model") or "").strip()
    if not base_url or not api_key or not model:
        raise RuntimeError("Embedding 服务配置不完整")
    normalized_texts = []
    for text in texts:
        clean = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", str(text or ""))
        clean = re.sub(r"\s+", " ", clean).strip()
        # Embedding-3 accepts at most 3072 tokens per item. Formula-heavy Marker
        # output can use far more tokens than its character count suggests.
        normalized_texts.append(clean[:2400] or "空白文本")
    response = requests.post(
        f"{base_url}/embeddings",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        json={"model": model, "input": normalized_texts},
        timeout=(20, max(30, int(settings.get("request_timeout_sec") or 180))),
    )
    if not response.ok:
        detail = str(response.text or "").strip()[:800]
        raise RuntimeError(f"Embedding 请求失败（HTTP {response.status_code}）：{detail or '服务未返回错误详情'}")
    payload = response.json()
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) != len(normalized_texts):
        raise RuntimeError("Embedding 服务返回数量不匹配")
    rows = sorted(rows, key=lambda item: int(item.get("index", 0)))
    vectors = []
    for row in rows:
        vector = row.get("embedding") if isinstance(row, dict) else None
        if not isinstance(vector, list) or not vector:
            raise RuntimeError("Embedding 服务未返回有效向量")
        vectors.append([float(value) for value in vector])
    return vectors


def validate_llm_config_payload(data: dict) -> str:
    provider = str(data.get("llm_provider") or "ollama").strip()
    service_url = str(data.get("llm_base_url") or data.get("ollama_base_url") or "").strip()
    model_name = str(data.get("model") or "").strip()
    saved_api_key = ""
    if report_config_store is not None:
        saved_api_key = str(report_config_store.load_settings(REPORT_GENERATION_CONFIG_PATH).get("llm_api_key") or "").strip()
    if not service_url:
        return "请先填写模型服务地址。"
    if not model_name:
        return "请先填写模型名称。"
    if provider == "openai_compatible" and not str(data.get("llm_api_key") or "").strip() and not saved_api_key:
        return "请先填写大模型访问密钥，或将接口类型切换为本地 Ollama 模型。"
    return ""


def load_report_generation_settings() -> dict:
    if report_config_store is None:
        return {}
    return report_config_store.load_settings(REPORT_GENERATION_CONFIG_PATH)


DATE_STEM_RE = re.compile(r"^(?P<topic>.+)_(?P<date>\d{4}-\d{2}-\d{2})$")

METHOD_PATTERNS = [
    ("CALPHAD", r"\bCALPHAD\b"),
    ("ANN", r"\bANN\b|artificial neural network|人工神经网络"),
    ("machine learning", r"machine learning|机器学习|data[-\s]?driven|数据驱动"),
    ("SLM", r"\bSLM\b|selective laser melting|选区激光熔化"),
    ("additive manufacturing", r"additive manufacturing|增材制造|3D printing|laser powder bed fusion"),
    ("EBSD", r"\bEBSD\b|electron backscatter"),
    ("TEM", r"\bTEM\b|transmission electron microscopy|透射电镜"),
    ("SEM", r"\bSEM\b|scanning electron microscopy|扫描电镜"),
    ("XRD", r"\bXRD\b|x-ray diffraction|X射线衍射"),
    ("aging", r"\baging\b|aged\b|时效"),
    ("annealing", r"\banneal(?:ing|ed)?\b|退火"),
    ("thermomechanical processing", r"thermomechanical|热机械"),
    ("oxygen charging", r"oxygen[-\s]?charging|氧(?:含量)?梯度|充氧"),
    ("surface coating", r"coating|涂层|surface modification|表面改性"),
]

MATERIAL_PATTERNS = [
    ("Ti alloy", r"\bTi[-\s]?alloy|titanium alloy|钛合金"),
    ("Ti-6Al-4V", r"Ti[-\s]?6Al[-\s]?4V"),
    ("β-Ti", r"(?:β|beta)[-\s]?Ti|metastable\s+β|亚稳β|β钛"),
    ("α+β Ti", r"(?:α|alpha)\s*\+\s*(?:β|beta)|α\s*\+\s*β"),
    ("TA15", r"\bTA15\b"),
    ("TA31", r"\bTA31\b"),
    ("Ti-22Al-25Nb", r"Ti[-\s]?22Al[-\s]?25Nb"),
    ("Cu-Cr-Ti", r"Cu[-\s]?Cr[-\s]?Ti"),
    ("Cu-Co-Ti", r"Cu[-\s]?Co[-\s]?Ti"),
    ("high entropy alloy", r"high[-\s]?entropy alloy|高熵合金"),
    ("CFRP/Ti stack", r"CFRP\s*/\s*Ti|CFRP[-\s]?Ti"),
    ("biomedical Ti", r"biomedical|implant|osseointegration|生物医用|植入"),
]

KEYWORD_PATTERNS = [
    ("additive manufacturing", r"additive manufacturing|增材制造|3D printing|laser powder bed fusion"),
    ("fuel cell", r"fuel cells?|燃料电池"),
    ("oxygen reduction reaction", r"oxygen reduction reaction|\bORR\b|氧还原"),
    ("hydrogen evolution reaction", r"hydrogen evolution reaction|\bHER\b|析氢"),
    ("strength-ductility", r"strength[-–\s]?ductility|强度.*延展|塑性"),
    ("corrosion", r"corrosion|腐蚀|passivation|钝化"),
    ("wear resistance", r"wear resistance|耐磨"),
    ("microstructure", r"microstructure|微观结构|组织"),
    ("grain refinement", r"grain refinement|晶粒细化"),
    ("precipitation", r"precipitat|析出"),
    ("deformation mechanism", r"deformation mechanism|变形机制"),
    ("welding", r"weld|焊接"),
    ("drilling", r"drilling|钻孔"),
    ("laser processing", r"laser|激光"),
]

TOKEN_STOPWORDS = {
    "abstract", "results", "result", "study", "studied", "using", "based", "effect",
    "effects", "properties", "property", "performance", "materials", "material",
    "alloy", "alloys", "titanium", "paper", "method", "methods", "analysis",
    "different", "structure", "structures", "mechanical", "microstructure",
    "research", "current", "present", "through", "between", "during", "after",
    "before", "there", "their", "these", "those", "which", "with", "from",
    "that", "this", "were", "was", "have", "has", "been", "into", "such",
    "high", "phase", "alpha", "beta", "laser", "zhang", "wang", "chen", "liu",
    "yang", "liang", "frontiers", "materials", "science", "engineering",
    "active", "activity", "additive", "advanced", "cell", "cells", "dynamic",
    "energy", "environmental", "fuel", "graft", "manufacturing", "parameters",
    "particles", "process", "processing", "refractory", "selective", "severe",
    "solid", "strategy", "strategies", "system", "systems", "treatment", "work",
    "parameter",
    "strength", "thermal", "orientation",
    "主要", "研究", "方法", "文献", "材料", "性能", "结构", "合金", "当前", "通过",
}

TREND_TERM_ALIASES = {
    "3d printing": "additive manufacturing",
    "additive manufacture": "additive manufacturing",
    "additive manufacturing": "additive manufacturing",
    "laser powder bed fusion": "additive manufacturing",
    "lpbf": "additive manufacturing",
    "selective laser melting": "additive manufacturing",
    "slm": "additive manufacturing",
    "superconducting": "superconductor",
    "superconductor": "superconductor",
    "superconductors": "superconductor",
    "superconductivity": "superconductor",
    "microstructures": "microstructure",
    "microstructural": "microstructure",
    "parameters": "parameter",
}

TREND_EVIDENCE_VARIANTS = {
    "ann": {"ann", "artificial neural network", "artificial neural networks"},
    "ebsd": {"ebsd", "electron backscatter", "electron backscatter diffraction"},
    "laser processing": {"laser", "laser processing"},
    "grain refinement": {"grain refinement", "grain refined"},
    "oxygen reduction reaction": {"oxygen reduction reaction", "orr"},
    "hydrogen evolution reaction": {"hydrogen evolution reaction", "her"},
    "strength-ductility": {"strength ductility", "strength-ductility"},
    "sem": {"sem", "scanning electron microscopy", "scanning electron microscope"},
    "surface coating": {"coating", "surface coating", "surface modification"},
    "tem": {"tem", "transmission electron microscopy", "transmission electron microscope"},
    "thermomechanical processing": {"thermomechanical", "thermo mechanical", "thermomechanical processing"},
    "xrd": {"xrd", "x ray diffraction", "x-ray diffraction", "x ray diffractometer", "x-ray diffractometer"},
    "biomedical ti": {"biomedical", "implant", "implants", "osseointegration", "bio medical"},
}

TREND_GENERIC_TERMS = {
    "orientation",
    "parameter",
    "strength",
    "thermal",
}


ASCII_LETTER_RE = re.compile(r"[A-Za-z]")


@lru_cache(maxsize=512)
def build_keyword_matcher(keyword: str) -> re.Pattern | None:
    term = re.sub(r"\s+", " ", str(keyword or "")).strip()
    if not term:
        return None
    parts = [re.escape(part) for part in term.split(" ")]
    pattern = r"\s+".join(parts)
    if ASCII_LETTER_RE.search(term):
        pattern = rf"(?<![A-Za-z]){pattern}(?![A-Za-z])"
    return re.compile(pattern, flags=re.IGNORECASE)


def keyword_matches_text(keyword: str, text: str) -> bool:
    matcher = build_keyword_matcher(keyword)
    if matcher is None:
        return False
    return matcher.search(str(text or "")) is not None


def keyword_matches_any_text(keyword: str, *values) -> int:
    combined = "\n".join(str(value or "") for value in values)
    return 1 if keyword_matches_text(keyword, combined) else 0


def relative_project_path(path: Path | None) -> str:
    if not path:
        return ""
    try:
        return str(path.relative_to(PROJECT_DIR))
    except ValueError:
        return str(path)


def display_path(path: Path | None) -> str:
    return relative_project_path(path)


def parse_topic_date_from_path(path: Path) -> tuple[str, str] | None:
    match = DATE_STEM_RE.match(path.stem)
    if not match:
        return None
    return match.group("topic"), match.group("date")


def topic_label_from_key(topic_key: str) -> str:
    return topic_key.replace("_AND_", " AND ").replace("_OR_", " OR ").replace("_", " ")


def normalize_trend_topic_key(value: str) -> str:
    text = (value or "").strip()
    text = re.sub(r"[^\w\-]+", "_", text, flags=re.UNICODE)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "unknown"


def collect_report_text(payload: dict) -> str:
    parts = [
        payload.get("topic", ""),
        payload.get("research_content", ""),
    ]
    for key in ["key_findings", "scientific_questions", "methods"]:
        value = payload.get(key, [])
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    parts.append(item.get("conclusion", ""))
                    evidence = item.get("evidence", [])
                    if isinstance(evidence, list):
                        parts.extend(
                            ev.get("abstract_snippet", "")
                            for ev in evidence
                            if isinstance(ev, dict)
                        )
                else:
                    parts.append(str(item))
    refs = payload.get("references", [])
    if isinstance(refs, list):
        for ref in refs:
            if isinstance(ref, dict):
                parts.extend([ref.get("title", ""), ref.get("journal", "")])
    return "\n".join(str(item) for item in parts if item)


INSTITUTION_COLUMNS = [
    "institutions",
    "institution",
    "affiliations",
    "affiliation",
    "organizations",
    "organization",
]


def split_trend_entity_values(value: object) -> list[str]:
    if value is None:
        return []
    try:
        if pd.isna(value):
            return []
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text:
        return []
    raw_parts = re.split(r"\s*(?:;|；|\||\n|\r)\s*", text)
    items = []
    seen = set()
    for raw_part in raw_parts:
        item = re.sub(r"\s+", " ", raw_part).strip(" ,，")
        if not item or item.lower() in {"unknown", "none", "nan", "n/a"}:
            continue
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
    return items


def count_csv_entities(df: pd.DataFrame, columns: list[str]) -> Counter:
    counter: Counter = Counter()
    for column in columns:
        if column not in df.columns:
            continue
        for value in df[column].fillna("").tolist():
            counter.update(split_trend_entity_values(value))
    return counter


def trend_paper_identity(row: pd.Series) -> str:
    """Build a stable identity so repeated historical searches do not inflate counts."""
    for column in ("doi", "paperId", "paper_id", "id"):
        value = str(row.get(column, "") or "").strip().casefold()
        if value and value not in {"nan", "none", "n/a"}:
            return f"{column}:{value.removeprefix('https://doi.org/').removeprefix('doi:')}"
    title = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", str(row.get("title", "") or "").casefold())
    title = re.sub(r"\s+", " ", title).strip()
    return f"title:{title}" if title else ""


def unique_trend_records(records: list[dict]) -> list[dict]:
    unique = []
    seen = set()
    for record in records:
        identity = record.get("identity", "")
        fallback = f"title:{normalize_trend_text(record.get('title', ''))}"
        key = identity or fallback
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique


def count_record_entities(records: list[dict], field: str) -> Counter:
    counter: Counter = Counter()
    for record in records:
        counter.update(record.get(field, []))
    return counter


def csv_trend_evidence_records(trend_df: pd.DataFrame, csv_path: Path) -> list[dict]:
    records = []
    for _, row in trend_df.head(300).iterrows():
        title = str(row.get("title", "") or "").strip()
        abstract = str(row.get("abstract", "") or "").strip()
        if not title and not abstract:
            continue
        records.append({
            "identity": trend_paper_identity(row),
            "title": title or "未命名文献",
            "abstract": abstract,
            "source_text": " ".join(
                str(row.get(column, "") or "")
                for column in ["query", "title", "abstract", "venue", "authors", *INSTITUTION_COLUMNS]
            ),
            "source_path": relative_project_path(csv_path),
            "venue": str(row.get("venue", "") or "").strip(),
            "date": str(row.get("publicationDate", "") or row.get("year", "") or "").strip(),
            "authors_text": str(row.get("authors", "") or ""),
            "institutions_text": " ; ".join(str(row.get(column, "") or "") for column in INSTITUTION_COLUMNS),
            "authors": split_trend_entity_values(row.get("authors", "")),
            "institutions": [
                item
                for column in INSTITUTION_COLUMNS
                for item in split_trend_entity_values(row.get(column, ""))
            ],
        })
    return records


def read_csv_trend_text(csv_path: Path) -> tuple[int, str, str, Counter, Counter, list[dict], dict[str, Counter]]:
    df = pd.read_csv(csv_path)
    display_topic = ""
    if "query" in df.columns and not df["query"].dropna().empty:
        display_topic = str(df["query"].dropna().iloc[0]).strip()

    columns = [col for col in ["query", "title", "abstract", "venue", "authors", *INSTITUTION_COLUMNS] if col in df.columns]
    if columns:
        trend_df = df
        if materials_vocab is not None and {"title", "abstract"} & set(df.columns):
            text_fields = [col for col in ["title", "abstract", "venue"] if col in df.columns]
            relevance_mask = df[text_fields].fillna("").astype(str).agg(" ".join, axis=1).apply(
                is_trend_source_text_related
            )
            trend_df = df[relevance_mask]
        text = "\n".join(
            trend_df[columns].fillna("").astype(str).head(300).agg(" ".join, axis=1).tolist()
        )
    else:
        text = ""
    evidence_records = unique_trend_records(csv_trend_evidence_records(trend_df, csv_path)) if columns else []
    author_counts = count_record_entities(evidence_records, "authors")
    institution_counts = count_record_entities(evidence_records, "institutions")
    document_term_counts = extract_trend_terms_by_document([
        record.get("source_text", "") for record in evidence_records
    ])
    return (
        len(evidence_records) if columns else len(df),
        text,
        display_topic,
        author_counts,
        institution_counts,
        evidence_records,
        document_term_counts,
    )


def count_pattern_terms(text: str, patterns: list[tuple[str, str]]) -> Counter:
    counter: Counter = Counter()
    for label, pattern in patterns:
        matches = re.findall(pattern, text, flags=re.IGNORECASE)
        if matches:
            counter[normalize_trend_term(label)] += len(matches)
    return counter


def normalize_trend_text(value: str) -> str:
    text = str(value or "").replace("β", " beta ").replace("α", " alpha ")
    text = text.casefold()
    text = re.sub(r"[_/+\-–—]+", " ", text)
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def singularize_trend_token(term: str) -> str:
    if " " in term or not re.fullmatch(r"[a-z]{5,}", term):
        return term
    if term.endswith("ies") and len(term) > 5:
        return f"{term[:-3]}y"
    if term.endswith("ses") or term.endswith("xes"):
        return term[:-2]
    if term.endswith("s") and not term.endswith(("ss", "us", "ous")):
        return term[:-1]
    return term


def normalize_trend_term(term: str) -> str:
    normalized = normalize_trend_text(term)
    if not normalized:
        return ""
    normalized = TREND_TERM_ALIASES.get(normalized, normalized)
    if normalized in TREND_TERM_ALIASES:
        return TREND_TERM_ALIASES[normalized]
    singular = singularize_trend_token(normalized)
    return TREND_TERM_ALIASES.get(singular, singular)


def normalize_trend_counter(counter: Counter) -> Counter:
    normalized_counter: Counter = Counter()
    for term, count in counter.items():
        canonical = normalize_trend_term(term)
        if not canonical or canonical in TREND_GENERIC_TERMS:
            continue
        normalized_counter[canonical] += count
    return normalized_counter


def topic_filter_terms(topic_key: str, topic_label: str = "") -> set[str]:
    filters = set()
    for value in [topic_key, topic_label, topic_label_from_key(topic_key)]:
        normalized = normalize_trend_term(value)
        if normalized:
            filters.add(normalized)
        for raw_part in re.split(r"\bAND\b|\bOR\b|[+,&，、;/|]+", str(value or ""), flags=re.IGNORECASE):
            part = normalize_trend_term(raw_part)
            if part:
                filters.add(part)
    return filters


def is_topic_term(term: str, filters: set[str]) -> bool:
    canonical = normalize_trend_term(term)
    if not canonical:
        return True
    for topic_term in filters:
        if canonical == topic_term:
            return True
        if len(topic_term) >= 5 and (canonical.startswith(f"{topic_term} ") or canonical.endswith(f" {topic_term}")):
            return True
    return False


def filter_topic_counter(counter: Counter, topic_key: str, topic_label: str = "") -> Counter:
    filters = topic_filter_terms(topic_key, topic_label)
    return Counter({
        term: count
        for term, count in normalize_trend_counter(counter).items()
        if not is_topic_term(term, filters)
    })


def trend_term_variants(term: str) -> set[str]:
    canonical = normalize_trend_term(term)
    variants = {canonical, term}
    variants.update(alias for alias, target in TREND_TERM_ALIASES.items() if target == canonical)
    variants.update(TREND_EVIDENCE_VARIANTS.get(canonical, set()))
    return {variant for variant in variants if variant}


def trend_term_matches_text(term: str, text: str) -> bool:
    if not text:
        return False
    normalized_text = normalize_trend_text(text)
    for variant in trend_term_variants(term):
        if keyword_matches_text(variant, text):
            return True
        normalized_variant = normalize_trend_text(variant)
        if normalized_variant and normalized_variant in normalized_text:
            return True
        if " " not in variant and re.search(rf"(?<![A-Za-z]){re.escape(variant)}(?:s|es|ing|ed)?(?![A-Za-z])", text, re.IGNORECASE):
            return True
    return False


def trend_evidence_snippet(term: str, text: str, max_chars: int = 180) -> str:
    if not text:
        return ""
    match = None
    for variant in sorted(trend_term_variants(term), key=len, reverse=True):
        pattern = re.compile(re.escape(variant), flags=re.IGNORECASE)
        match = pattern.search(text)
        if match:
            break
    if not match and " " not in term:
        match = re.search(rf"(?<![A-Za-z]){re.escape(term)}(?:s|es|ing|ed)?(?![A-Za-z])", text, re.IGNORECASE)
    if not match:
        return text[:max_chars].strip()
    start = max(0, match.start() - max_chars // 2)
    end = min(len(text), match.end() + max_chars // 2)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{text[start:end].strip()}{suffix}"


def build_term_evidence(term: str, records: list[dict], limit: int = 5) -> list[dict]:
    evidence = []
    seen_titles = set()
    for record in records:
        title = record.get("title", "")
        abstract = record.get("abstract", "")
        searchable_text = record.get("source_text", "") or f"{title}\n{abstract}"
        if not trend_term_matches_text(term, searchable_text):
            continue
        title_key = title.casefold()
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        evidence.append({
            "title": title,
            "snippet": trend_evidence_snippet(term, abstract or title),
            "source_path": record.get("source_path", ""),
            "venue": record.get("venue", ""),
            "date": record.get("date", ""),
        })
        if len(evidence) >= limit:
            break
    return evidence


def build_entity_evidence(term: str, records: list[dict], field: str, limit: int = 5) -> list[dict]:
    evidence = []
    seen_titles = set()
    normalized_term = term.casefold().strip()
    normalized_search_term = normalize_trend_text(term)
    text_field = f"{field}_text"
    for record in records:
        values = [str(item).casefold().strip() for item in record.get(field, [])]
        normalized_values = [normalize_trend_text(item) for item in record.get(field, [])]
        normalized_raw_text = normalize_trend_text(record.get(text_field, ""))
        if (
            normalized_term not in values
            and normalized_search_term not in normalized_values
            and normalized_search_term not in normalized_raw_text
        ):
            continue
        title = record.get("title", "")
        title_key = title.casefold()
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        evidence.append({
            "title": title,
            "snippet": (record.get("abstract", "") or title)[:180].strip(),
            "source_path": record.get("source_path", ""),
            "venue": record.get("venue", ""),
            "date": record.get("date", ""),
        })
        if len(evidence) >= limit:
            break
    return evidence


def attach_term_evidence(items: list[dict], records: list[dict]) -> list[dict]:
    return [
        {
            **item,
            "evidence": build_term_evidence(item.get("term", ""), records),
        }
        for item in items
    ]


def attach_entity_evidence(items: list[dict], records: list[dict], field: str) -> list[dict]:
    return [
        {
            **item,
            "evidence": build_entity_evidence(item.get("term", ""), records, field),
        }
        for item in items
    ]


def count_auto_tokens(text: str) -> Counter:
    cleaned = text.replace("β", " beta ").replace("α", " alpha ")
    words = re.findall(r"[A-Za-z][A-Za-z0-9+\-]{3,}|[\u4e00-\u9fff]{2,6}", cleaned)
    counter: Counter = Counter()
    for raw_word in words:
        word = normalize_trend_term(raw_word.strip("-"))
        if len(word) < 4 or word in TOKEN_STOPWORDS:
            continue
        if word.isdigit():
            continue
        # 趋势对比直接展示给用户，使用比“材料相关”更严格的候选词过滤。
        if materials_vocab is not None:
            is_allowed = getattr(
                materials_vocab,
                "is_trend_comparison_term",
                materials_vocab.is_materials_science_term,
            )
            if not is_allowed(word):
                continue
        counter[word] += 1
    return normalize_trend_counter(counter)


def is_trend_source_text_related(text: str) -> bool:
    if not text or materials_vocab is None:
        return True

    explicit_counts = Counter()
    explicit_counts.update(count_pattern_terms(text, KEYWORD_PATTERNS))
    explicit_counts.update(count_pattern_terms(text, METHOD_PATTERNS))
    explicit_counts.update(count_pattern_terms(text, MATERIAL_PATTERNS))
    if sum(explicit_counts.values()) > 0:
        return True

    cleaned = text.replace("β", " beta ").replace("α", " alpha ")
    words = re.findall(r"[A-Za-z][A-Za-z0-9+\-]{3,}|[\u4e00-\u9fff]{2,6}", cleaned)
    trend_terms = {
        word
        for raw_word in words
        if (word := raw_word.lower().strip("-")) not in TOKEN_STOPWORDS
        and materials_vocab.is_trend_comparison_term(word)
    }
    return len(trend_terms) >= 2


def extract_trend_terms(text: str) -> dict[str, Counter]:
    method_counts = normalize_trend_counter(count_pattern_terms(text, METHOD_PATTERNS))
    material_counts = normalize_trend_counter(count_pattern_terms(text, MATERIAL_PATTERNS))
    keyword_counts = normalize_trend_counter(count_pattern_terms(text, KEYWORD_PATTERNS))
    keyword_counts.update({
        word: count
        for word, count in count_auto_tokens(text).most_common(16)
        if word not in method_counts and word not in material_counts
    })
    return {
        "keywords": keyword_counts,
        "methods": method_counts,
        "materials": material_counts,
    }


def empty_trend_term_counts() -> dict[str, Counter]:
    return {
        "keywords": Counter(),
        "methods": Counter(),
        "materials": Counter(),
    }


def merge_trend_term_counts(target: dict[str, Counter], source: dict[str, Counter]) -> None:
    for category in ("keywords", "methods", "materials"):
        target.setdefault(category, Counter()).update(source.get(category, Counter()))


def extract_trend_terms_by_document(texts: list[str]) -> dict[str, Counter]:
    document_counts = empty_trend_term_counts()
    for text in texts:
        term_counts = extract_trend_terms(text)
        for category in ("keywords", "methods", "materials"):
            for term, count in term_counts.get(category, Counter()).items():
                if count > 0:
                    document_counts[category][term] += 1
    return document_counts


def counter_to_items(counter: Counter, limit: int = 12) -> list[dict]:
    return [
        {"term": term, "count": int(count)}
        for term, count in counter.most_common(limit)
        if count > 0
    ]


def resolve_current_trend_csv(current_csv: str) -> Path | None:
    if not current_csv:
        return None
    try:
        path = resolve_project_file(current_csv)
    except Exception:
        return None
    return path if path.suffix.lower() == ".csv" and path.exists() else None


def parse_trend_window_days(value: object) -> int | None:
    text = str(value or "all").strip().lower()
    if text in {"", "all", "全部", "0"}:
        return None
    try:
        days = int(text)
    except ValueError:
        return None
    return days if days > 0 else None


def parse_trend_publication_years(value: object) -> int | None:
    text = str(value or "all").strip().lower()
    if text in {"", "all", "全部", "0"}:
        return None
    try:
        years = int(text)
    except ValueError:
        return None
    return years if years > 0 else None


def filter_records_by_publication_year(records: list[dict], publication_years: int | None) -> list[dict]:
    if not publication_years:
        return records
    earliest_year = datetime.now().year - publication_years + 1
    filtered = []
    for record in records:
        match = re.search(r"\b(19\d{2}|20\d{2})\b", str(record.get("date", "")))
        if match and int(match.group(1)) >= earliest_year:
            filtered.append(record)
    return filtered


def filter_entries_by_window(entries: list[dict], window_days: int | None) -> list[dict]:
    if not window_days:
        return entries
    cutoff = (datetime.now() - timedelta(days=window_days)).date()
    filtered = []
    for entry in entries:
        try:
            entry_date = datetime.strptime(str(entry.get("date", ""))[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if entry_date >= cutoff:
            filtered.append(entry)
    return filtered


def build_history_entries(
    source_mode: str = "csv_all",
    current_csv: str = "",
    window_days: int | None = None,
    publication_years: int | None = None,
) -> list[dict]:
    entries: dict[tuple[str, str], dict] = {}
    # 研究热点只来自文献 CSV。旧版参数 all/reports 统一回退为全部历史 CSV。
    source_mode = source_mode if source_mode in {"csv_all", "current_csv"} else "csv_all"
    current_csv_path = resolve_current_trend_csv(current_csv) if source_mode == "current_csv" else None

    csv_paths = iter_search_csv_files()
    if source_mode == "current_csv":
        csv_paths = [
            path for path in csv_paths
            if current_csv_path is not None and path.resolve() == current_csv_path
        ]

    for csv_path in csv_paths:
        parsed = parse_topic_date_from_path(csv_path)
        if not parsed:
            continue
        topic_key, item_date = parsed
        try:
            (
                _,
                _,
                display_topic,
                _,
                _,
                evidence_records,
                _,
            ) = read_csv_trend_text(csv_path)
        except Exception:
            continue

        key = (topic_key, item_date)
        entry = entries.setdefault(key, {
            "topic_key": topic_key,
            "topic_label": display_topic or topic_label_from_key(topic_key),
            "date": item_date,
            "csv_path": "",
            "_evidence_records": [],
        })
        if display_topic:
            entry["topic_label"] = display_topic
        entry["csv_path"] = relative_project_path(csv_path)
        entry["_evidence_records"].extend(evidence_records)

    history = []
    for entry in entries.values():
        evidence_records = filter_records_by_publication_year(
            unique_trend_records(entry.pop("_evidence_records", [])),
            publication_years,
        )
        entry["paper_count"] = len(evidence_records)
        entry["_records"] = evidence_records
        history.append(entry)

    history = filter_entries_by_window(history, window_days)
    history.sort(key=lambda item: (item["topic_key"], item["date"]))
    return history


def trend_term_counts_for_topic(record: dict, topic_key: str, topic_label: str) -> dict[str, Counter]:
    return {
        category: filter_topic_counter(counter, topic_key, topic_label)
        for category, counter in extract_trend_terms(record.get("source_text", "")).items()
    }


def direction_cluster_label(material: str, method: str, keyword: str) -> str:
    parts = []
    if material:
        parts.append(f"材料：{material}")
    if method:
        parts.append(f"工艺：{method}")
    if keyword:
        parts.append(f"问题：{keyword}")
    return " · ".join(parts)


def build_direction_cluster_evidence(cluster: dict, limit: int = 5) -> list[dict]:
    evidence = []
    for record in cluster.get("records", []):
        abstract = record.get("abstract", "")
        evidence.append({
            "title": record.get("title", "未命名文献"),
            "snippet": (abstract or record.get("title", ""))[:180].strip(),
            "source_path": record.get("source_path", ""),
            "venue": record.get("venue", ""),
            "date": record.get("date", ""),
        })
        if len(evidence) >= limit:
            break
    return evidence


def extract_direction_clusters(records: list[dict], topic_key: str, topic_label: str) -> list[dict]:
    """Group papers by co-occurring material, method and research-question facets."""
    clusters: dict[tuple[str, str, str], dict] = {}
    for record in records:
        term_counts = trend_term_counts_for_topic(record, topic_key, topic_label)
        material = term_counts["materials"].most_common(1)[0][0] if term_counts["materials"] else ""
        method = term_counts["methods"].most_common(1)[0][0] if term_counts["methods"] else ""
        # Direction labels need conservative research-question facets. Auto tokens remain
        # useful for hotspot discovery but are too noisy to name a research direction.
        explicit_keywords = filter_topic_counter(
            normalize_trend_counter(count_pattern_terms(record.get("source_text", ""), KEYWORD_PATTERNS)),
            topic_key,
            topic_label,
        )
        keyword = explicit_keywords.most_common(1)[0][0] if explicit_keywords else ""
        if keyword in {material, method}:
            keyword = ""
        if sum(bool(value) for value in (material, method, keyword)) < 2:
            continue
        key = (material, method, keyword)
        cluster = clusters.setdefault(key, {
            "term": direction_cluster_label(material, method, keyword),
            "count": 0,
            "material": material,
            "method": method,
            "keyword": keyword,
            "records": [],
        })
        cluster["count"] += 1
        cluster["records"].append(record)

    items = []
    for cluster in sorted(clusters.values(), key=lambda item: item["count"], reverse=True)[:10]:
        items.append({
            key: value for key, value in cluster.items() if key != "records"
        } | {"evidence": build_direction_cluster_evidence(cluster)})
    return items


def summarize_topic_entries(entries: list[dict]) -> dict:
    entries = sorted(entries, key=lambda item: item["date"])
    keyword_total: Counter = Counter()
    method_total: Counter = Counter()
    material_total: Counter = Counter()
    author_total: Counter = Counter()
    institution_total: Counter = Counter()
    term_presence: defaultdict[str, int] = defaultdict(int)
    unique_batches = []
    seen_papers = set()
    for entry in entries:
        new_records = []
        for record in entry.get("_records", []):
            identity = record.get("identity", "") or f"title:{normalize_trend_text(record.get('title', ''))}"
            if not identity or identity in seen_papers:
                continue
            seen_papers.add(identity)
            new_records.append(record)
        topic_key = str(entry.get("topic_key", ""))
        topic_label = str(entry.get("topic_label", ""))
        term_counts = empty_trend_term_counts()
        for record in new_records:
            merge_trend_term_counts(term_counts, trend_term_counts_for_topic(record, topic_key, topic_label))
        unique_batches.append({
            "entry": entry,
            "records": new_records,
            "term_counts": term_counts,
            "authors": count_record_entities(new_records, "authors"),
            "institutions": count_record_entities(new_records, "institutions"),
        })

    all_records = [record for batch in unique_batches for record in batch["records"]]
    for batch in unique_batches:
        term_counts = batch["term_counts"]
        keyword_total.update(term_counts["keywords"])
        method_total.update(term_counts["methods"])
        material_total.update(term_counts["materials"])
        author_total.update(batch["authors"])
        institution_total.update(batch["institutions"])
        for term in set(term_counts["keywords"]) | set(term_counts["methods"]) | set(term_counts["materials"]):
            term_presence[term] += 1

    recent_size = min(3, max(1, math.ceil(len(unique_batches) / 2))) if unique_batches else 1
    recent_entries = unique_batches[-recent_size:]
    previous_entries = unique_batches[:-recent_size]
    recent_counts: Counter = Counter()
    previous_counts: Counter = Counter()
    recent_papers = sum(len(batch["records"]) for batch in recent_entries)
    previous_papers = sum(len(batch["records"]) for batch in previous_entries)
    for batch in recent_entries:
        recent_counts.update(batch["term_counts"]["keywords"])
    for batch in previous_entries:
        previous_counts.update(batch["term_counts"]["keywords"])

    hot_scores = []
    has_growth_baseline = len(unique_batches) >= 2 and previous_papers > 0 and recent_papers > 0
    for term in set(recent_counts) | set(previous_counts):
        recent_rate = recent_counts[term] / max(1, recent_papers)
        previous_rate = previous_counts[term] / max(1, previous_papers)
        score = recent_rate - previous_rate
        if has_growth_baseline and score > 0:
            hot_scores.append((term, score, recent_counts[term], recent_rate, previous_rate))
        elif not has_growth_baseline and recent_counts[term] > 0:
            hot_scores.append((term, recent_counts[term], recent_counts[term], recent_rate, 0.0))
    hot_scores.sort(key=lambda item: (item[1], item[2]), reverse=True)

    total_papers = len(all_records)
    topic_key = entries[0]["topic_key"] if entries else ""
    topic_label = entries[0]["topic_label"] if entries else ""

    def with_term_evidence(items: list[dict]) -> list[dict]:
        return attach_term_evidence(items, all_records)

    def with_entity_evidence(items: list[dict], field: str) -> list[dict]:
        return attach_entity_evidence(items, all_records, field)

    recent_authors: Counter = Counter()
    previous_authors: Counter = Counter()
    recent_institutions: Counter = Counter()
    previous_institutions: Counter = Counter()
    for batch in recent_entries:
        recent_authors.update(batch["authors"])
        recent_institutions.update(batch["institutions"])
    for batch in previous_entries:
        previous_authors.update(batch["authors"])
        previous_institutions.update(batch["institutions"])

    def activity_items(recent_entities: Counter, previous_entities: Counter, field: str) -> list[dict]:
        if has_growth_baseline:
            candidates = [
                (term, count) for term, count in recent_entities.items()
                if count > 0 and previous_entities[term] == 0
            ]
        else:
            candidates = [(term, count) for term, count in recent_entities.items() if count > 0]
        items = [
            {
                "term": term,
                "count": int(count),
                "value_label": f"新增 {int(count)} 篇" if has_growth_baseline else f"{int(count)} 篇",
                "detail": (
                    f"近期 {int(count)}/{recent_papers} 篇 · 基准期未出现"
                    if has_growth_baseline
                    else f"当前窗口覆盖 {int(count)}/{recent_papers} 篇"
                ),
            }
            for term, count in sorted(candidates, key=lambda item: item[1], reverse=True)[:10]
        ]
        return with_entity_evidence(items, field)

    hot_keyword_items = [
        {
            "term": term,
            "score": round(float(score * 100), 1) if has_growth_baseline else int(count),
            "value_label": f"+{score * 100:.1f}pp" if has_growth_baseline else f"{int(count)} 篇",
            "detail": (
                f"近期 {int(count)}/{recent_papers} 篇 · 基准 {int(previous_counts[term])}/{previous_papers} 篇"
                if has_growth_baseline
                else f"当前窗口 {int(count)}/{recent_papers} 篇"
            ),
        }
        for term, score, count, recent_rate, previous_rate in hot_scores[:10]
    ]
    recurring_items = [
        {"term": term, "days": int(days)}
        for term, days in sorted(term_presence.items(), key=lambda item: item[1], reverse=True)[:12]
        if days >= 2
    ]

    return {
        "topic_key": topic_key,
        "topic_label": topic_label,
        "entry_count": len(unique_batches),
        "total_papers": total_papers,
        "hot_keyword_mode": "rising" if has_growth_baseline else "current",
        "hot_keyword_note": (
            f"近期 {recent_papers} 篇相对基准期 {previous_papers} 篇的覆盖率变化"
            if has_growth_baseline
            else f"仅有 {len(unique_batches)} 个检索批次，按当前窗口 {recent_papers} 篇唯一文献排序"
        ),
        "direction_clusters": extract_direction_clusters(all_records, topic_key, topic_label),
        "author_activity_mode": "emerging" if has_growth_baseline else "current",
        "institution_activity_mode": "emerging" if has_growth_baseline else "current",
        "author_activity": activity_items(recent_authors, previous_authors, "authors"),
        "institution_activity": activity_items(recent_institutions, previous_institutions, "institutions"),
        "date_range": {
            "start": entries[0]["date"] if entries else "",
            "end": entries[-1]["date"] if entries else "",
        },
        "timeline": [
            {
                "date": batch["entry"]["date"],
                "paper_count": len(batch["records"]),
                "csv_path": batch["entry"].get("csv_path", ""),
                "top_keywords": counter_to_items(batch["term_counts"]["keywords"], 5),
                "top_authors": counter_to_items(batch["authors"], 3),
                "top_institutions": counter_to_items(batch["institutions"], 3),
            }
            for batch in unique_batches
        ],
        "hot_keywords": with_term_evidence(hot_keyword_items),
        "recurring_terms": with_term_evidence(recurring_items),
        "top_keywords": with_term_evidence(counter_to_items(keyword_total, 12)),
        "top_methods": with_term_evidence(counter_to_items(method_total, 10)),
        "top_materials": with_term_evidence(counter_to_items(material_total, 10)),
        "top_authors": with_entity_evidence(counter_to_items(author_total, 12), "authors"),
        "top_institutions": with_entity_evidence(counter_to_items(institution_total, 12), "institutions"),
    }


def trend_filter_params_from_request() -> dict:
    return {
        "source_mode": request.args.get("source_mode", "csv_all").strip() or "csv_all",
        "current_csv": request.args.get("current_csv", "").strip(),
        "window_days": parse_trend_window_days(request.args.get("window_days", "all")),
        "publication_years": parse_trend_publication_years(request.args.get("publication_years", "all")),
    }


def get_topic_summary_map(
    source_mode: str = "csv_all",
    current_csv: str = "",
    window_days: int | None = None,
    publication_years: int | None = None,
) -> dict[str, dict]:
    grouped: defaultdict[str, list] = defaultdict(list)
    for entry in build_history_entries(
        source_mode=source_mode,
        current_csv=current_csv,
        window_days=window_days,
        publication_years=publication_years,
    ):
        grouped[entry["topic_key"]].append(entry)
    return {topic_key: summarize_topic_entries(items) for topic_key, items in grouped.items()}


def extract_knowledge_terms(text: str) -> list[tuple[str, str]]:
    auto_terms = [word for word, count in count_auto_tokens(text).most_common(10) if count > 0]
    if materials_vocab is not None and hasattr(materials_vocab, "extract_knowledge_graph_terms"):
        return materials_vocab.extract_knowledge_graph_terms(text, auto_terms=auto_terms)

    terms: dict[str, str] = {word: "keyword" for word in auto_terms}
    return list(terms.items())


def clean_graph_field(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def graph_paper_detail(row: pd.Series, index: int) -> dict:
    citation_value = clean_graph_field(row.get("citationCount", ""))
    try:
        citation_count: int | str = int(float(citation_value)) if citation_value else ""
    except ValueError:
        citation_count = citation_value

    return {
        "index": int(index),
        "title": clean_graph_field(row.get("title", "")),
        "authors": clean_graph_field(row.get("authors", "")),
        "abstract": clean_graph_field(row.get("abstract", "")),
        "year": clean_graph_field(row.get("year", "")),
        "venue": clean_graph_field(row.get("venue", "")),
        "publicationDate": clean_graph_field(row.get("publicationDate", "")),
        "citationCount": citation_count,
        "doi": clean_graph_field(row.get("doi", "")),
        "url": clean_graph_field(row.get("url", "")),
        "pdf_url": clean_graph_field(row.get("pdf_url", "")),
        "source": clean_graph_field(row.get("source", "")),
        "paperId": clean_graph_field(row.get("paperId", "")),
    }


def build_knowledge_graph(
    csv_path: Path,
    max_nodes: int = 36,
    max_edges: int = 80,
    mode: str = "rule",
    llm_config: dict | None = None,
    progress_callback=None,
    graph_scope: str = "topic",
    input_source: str = "abstract",
    max_chunks_per_paper: int = 20,
    graph_source: str = "csv",
    graph_source_label: str = "",
) -> dict:
    if graph_builder is not None and hasattr(graph_builder, "build_psp_knowledge_graph"):
        graph = graph_builder.build_psp_knowledge_graph(
            csv_path=csv_path,
            project_dir=PROJECT_DIR,
            max_nodes=max_nodes,
            max_edges=max_edges,
            mode=mode,
            llm_config=llm_config,
            progress_callback=progress_callback,
            input_source=input_source,
            max_chunks_per_paper=max_chunks_per_paper,
        )
        graph["scope"] = graph_scope
        graph["scope_label"] = "全库知识图谱" if graph_scope == "library" else "主题库知识图谱"
        graph["graph_source"] = graph_source
        graph["graph_source_label"] = graph_source_label or ("文献库全量" if graph_scope == "library" else "当前 CSV")
        return graph

    df = pd.read_csv(csv_path)
    if df.empty:
        return {
            "dataset": relative_project_path(csv_path),
            "paper_count": 0,
            "nodes": [],
            "edges": [],
            "top_terms": [],
            "message": "CSV 中没有可分析的文献。",
            "scope": graph_scope,
        }

    text_columns = [col for col in ["query", "title", "abstract", "venue", "authors"] if col in df.columns]
    if not text_columns:
        return {
            "dataset": relative_project_path(csv_path),
            "paper_count": int(len(df)),
            "nodes": [],
            "edges": [],
            "top_terms": [],
            "message": "CSV 缺少 query/title/abstract/venue/authors 等可分析字段。",
        }

    node_counts: Counter = Counter()
    node_categories: dict[str, str] = {}
    edge_counts: Counter = Counter()
    sample_titles: defaultdict[str, list[str]] = defaultdict(list)
    paper_details: defaultdict[str, list[dict]] = defaultdict(list)
    paper_keys: defaultdict[str, set[str]] = defaultdict(set)

    for row_index, row in df.head(500).iterrows():
        text = " ".join(str(row.get(col, "") or "") for col in text_columns)
        extracted = extract_knowledge_terms(text)
        unique_terms = []
        seen = set()
        for term, category in extracted:
            normalized = term.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            unique_terms.append((normalized, category))

        title = str(row.get("title", "") or "").strip()
        detail = graph_paper_detail(row, int(row_index))
        paper_key = detail.get("doi") or detail.get("paperId") or detail.get("title") or str(row_index)
        for term, category in unique_terms:
            node_counts[term] += 1
            node_categories.setdefault(term, category)
            if title and len(sample_titles[term]) < 3:
                sample_titles[term].append(title)
            if detail["title"] and paper_key not in paper_keys[term]:
                paper_keys[term].add(paper_key)
                paper_details[term].append(detail)

        for left_index in range(len(unique_terms)):
            for right_index in range(left_index + 1, len(unique_terms)):
                left = unique_terms[left_index][0]
                right = unique_terms[right_index][0]
                if left == right:
                    continue
                edge_key = tuple(sorted((left, right)))
                edge_counts[edge_key] += 1

    selected_terms = {
        term for term, _ in node_counts.most_common(max(4, min(max_nodes, 80)))
    }
    nodes = [
        {
            "id": term,
            "label": term,
            "category": node_categories.get(term, "keyword"),
            "count": int(count),
            "papers": sample_titles.get(term, []),
            "paper_details": paper_details.get(term, []),
        }
        for term, count in node_counts.most_common()
        if term in selected_terms
    ]
    edges = [
        {"source": left, "target": right, "weight": int(weight)}
        for (left, right), weight in edge_counts.most_common(max_edges)
        if left in selected_terms and right in selected_terms
    ]

    connected_terms = {edge["source"] for edge in edges} | {edge["target"] for edge in edges}
    if connected_terms:
        nodes = [node for node in nodes if node["id"] in connected_terms]

    category_counts = Counter(node["category"] for node in nodes)
    return {
        "dataset": relative_project_path(csv_path),
        "paper_count": int(len(df)),
        "analyzed_paper_count": int(min(len(df), 500)),
        "nodes": nodes,
        "edges": edges,
        "top_terms": [
            {"term": term, "count": int(count), "category": node_categories.get(term, "keyword")}
            for term, count in node_counts.most_common(12)
        ],
        "category_counts": dict(category_counts),
    }


@app.context_processor
def inject_static_version():
    try:
        version = int(max(
            (STATIC_DIR / "js" / "main.js").stat().st_mtime,
            (STATIC_DIR / "css" / "style.css").stat().st_mtime,
            (STATIC_DIR / "js" / "knowledge_qa.js").stat().st_mtime,
            (STATIC_DIR / "css" / "knowledge_qa.css").stat().st_mtime,
            (STATIC_DIR / "js" / "site_shell.js").stat().st_mtime,
        ))
    except OSError:
        version = int(datetime.now().timestamp())
    try:
        logo_version = int((LOGO_DIR / "logo.png").stat().st_mtime)
    except OSError:
        logo_version = version
    return {"static_version": version, "logo_version": logo_version}

@app.route('/')
def index():
    saved_report_settings = load_report_generation_settings()
    report_config = dict(report.CONFIG) if report else {}
    report_config.update({key: value for key, value in saved_report_settings.items() if key != "llm_api_key"})
    # 准备初始数据
    initial_data = {
        'queries': [''],
        'operator': '与 (AND)',
        'api_key': scholar.resolve_api_key() if scholar else '',
        'limit_per_query': str(scholar.LIMIT_PER_QUERY) if scholar else '10',
        'sleep_each_req': str(scholar.SLEEP_EACH_REQ) if scholar else '1.0',
        'start_date': '',
        'end_date': '',
        'selected_sources': [],
        'config': {
            'llm_provider': str(report_config.get("llm_provider", "ollama")),
            'output_dir': str(OUTPUTS_DIR),
            'ollama_base_url': str(report_config.get("ollama_base_url", "")),
            'llm_base_url': str(report_config.get("llm_base_url", "")),
            'llm_api_key': "",
            'report_has_api_key': bool(str(saved_report_settings.get("llm_api_key") or "").strip()),
            'model': str(report_config.get("model", "")),
            'max_papers_for_llm': str(report_config.get("max_papers_for_llm", 10)),
            'report_style': str(report_config.get("report_style", "科研日报")),
            'report_data_source': str(report_config.get("report_data_source", "csv")),
            'report_collection_id': str(report_config.get("report_collection_id", "")),
            'report_input_mode': str(report_config.get("report_input_mode", "abstract_only")),
            'temperature': str(report_config.get("temperature", 0.7)),
            'top_p': str(report_config.get("top_p", 0.9)),
            'num_predict': str(report_config.get("num_predict", 8000)),
            'max_retry': str(report_config.get("max_retry", 3)),
            'topic_override': str(report_config.get("topic_override", "")),
            'min_research_content_chars': str(report_config.get("min_research_content_chars", 500)),
            'keep_empty_abstract': bool(report_config.get("keep_empty_abstract", False)),
            'save_debug_files': bool(report_config.get("save_debug_files", False)),
        }
    }
    
    return render_template('index.html', initial_data=initial_data)


@app.route('/user_guide')
def user_guide():
    guide_path = DOCS_DIR / "USER_GUIDE.md"
    if not guide_path.exists():
        return render_template(
            "user_guide.html",
            guide_html=Markup("<p>未找到用户手册文件。</p>"),
            updated_at="",
        ), 404
    markdown_text = guide_path.read_text(encoding="utf-8", errors="replace")
    updated_at = datetime.fromtimestamp(guide_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    return render_template(
        "user_guide.html",
        guide_html=Markup(render_user_guide_markdown(markdown_text)),
        updated_at=updated_at,
    )


@app.route('/knowledge_qa')
def knowledge_qa():
    return render_template('knowledge_qa.html')


@app.route('/authors')
def authors():
    return redirect(url_for('index', authors='1'))


@app.route('/user_guide/assets/<path:filename>')
def user_guide_asset(filename):
    if ".." in Path(filename).parts:
        return jsonify({"error": "资源路径不合法"}), 400
    return send_from_directory(DOCS_DIR, filename)


@app.route('/logo/<path:filename>')
def logo_file(filename):
    return send_from_directory(LOGO_DIR, filename)

@app.route('/api/search', methods=['POST'])
def search():
    if not multi_source_search:
        return jsonify({'error': 'Multi-source search module not available'}), 500

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': '请求内容必须是 JSON 对象'}), 400
    task_id = f"search_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{uuid.uuid4().hex[:8]}"
    
    # 解析查询参数
    raw_queries = data.get('queries', [])
    if not isinstance(raw_queries, list):
        return jsonify({'error': '检索词格式无效'}), 400
    queries = [str(q).strip() for q in raw_queries if str(q).strip()]
    operator = data.get('operator', '与 (AND)')
    try:
        limit = int(data.get('limit_per_query', 10))
        sleep_each_req = float(data.get('sleep_each_req', 1.0))
    except (TypeError, ValueError):
        return jsonify({'error': '检索条数或请求间隔格式无效'}), 400
    if not 1 <= limit <= 100:
        return jsonify({'error': '每个关键词条数必须在 1 到 100 之间'}), 400
    if not 0 <= sleep_each_req <= 60:
        return jsonify({'error': '请求间隔必须在 0 到 60 秒之间'}), 400
    source_credentials = get_source_credentials(data)
    api_key = source_credentials.get("semantic_scholar_api_key", "")
    start_date = data.get('start_date', '')
    end_date = data.get('end_date', '')
    selected_sources = get_selected_sources(data)
    
    if not queries:
        return jsonify({'error': '请至少输入一个检索词'}), 400
    if not selected_sources:
        return jsonify({'error': '请至少选择一个文献数据库'}), 400
    
    # 合并查询词
    if len(queries) == 1:
        merged_query = queries[0]
    else:
        connector = " AND " if operator == "与 (AND)" else " OR "
        merged_query = connector.join([f"({item})" for item in queries])
    search_queries = [merged_query] if operator == "与 (AND)" else queries
    
    def search_task():
        log_to_task(task_id, f"开始检索: {merged_query}")
        log_to_task(task_id, f"文献数据库: {', '.join(selected_sources)}")
        log_database_credential_hints(task_id, selected_sources, source_credentials)
        
        try:
            results = multi_source_search.search_and_save_queries(
                queries=search_queries,
                limit=limit,
                sleep_each_req=sleep_each_req,
                api_key=api_key,
                output_dir=METADATA_DIR,
                selected_sources=selected_sources,
                source_credentials=source_credentials,
                logger=lambda msg: log_to_task(task_id, msg),
                start_date=start_date,
                end_date=end_date,
                enrich_missing=False,
                persist_library=False,
            )
            
            if results:
                selected_csv = display_path(Path(results[0]["csv_path"]))
                log_to_task(task_id, f"检索完成，结果保存在: {selected_csv}")
                log_to_task(task_id, "检索结果未自动写入文献数据库；请在文献预览中选择「选中入库」或「整份 CSV 入库」。")
                return {'csv_path': selected_csv}
            else:
                log_to_task(task_id, "检索未返回结果")
                return {'csv_path': None}
        except Exception as e:
            log_to_task(task_id, f"检索过程中发生错误: {str(e)}")
            raise
    
    task_manager.add_task(task_id, '文献检索', search_task)
    return jsonify({'task_id': task_id})


@app.route('/api/report/settings', methods=['GET'])
def get_report_generation_settings():
    if report_config_store is None:
        return jsonify({"error": "综述配置模块不可用"}), 500
    settings = report_config_store.load_settings(REPORT_GENERATION_CONFIG_PATH)
    return jsonify(report_config_store.public_settings(settings))


@app.route('/api/report/settings', methods=['POST'])
def save_report_generation_settings():
    if report_config_store is None:
        return jsonify({"error": "综述配置模块不可用"}), 500
    data = request.get_json(silent=True) or {}
    try:
        settings = report_config_store.save_settings(REPORT_GENERATION_CONFIG_PATH, data)
        return jsonify({
            "message": "综述参数已保存",
            "settings": report_config_store.public_settings(settings),
        })
    except (TypeError, ValueError) as exc:
        return jsonify({"error": f"配置参数无效: {exc}"}), 400
    except OSError as exc:
        return jsonify({"error": f"保存配置失败: {exc}"}), 500


@app.route('/api/report/source-summary', methods=['POST'])
def report_source_summary():
    if not report:
        return jsonify({'error': '综述模块不可用'}), 500

    data = request.get_json(silent=True) or {}
    data_source = report.normalize_report_data_source(data.get("report_data_source", "csv"))
    collection_id = str(data.get("report_collection_id") or "").strip()
    input_csv = str(data.get("input_csv") or "").strip()
    input_csv_path = None
    column_mappings = {}
    try:
        if data_source == "csv":
            if not input_csv:
                return jsonify({'error': '请选择一个 CSV 数据集'}), 400
            input_csv_path = resolve_project_file(input_csv)
            raw_preview = pd.read_csv(input_csv_path, nrows=5)
            _, column_mappings = report.map_csv_columns(raw_preview)

        papers_df, source_label, _ = report.load_report_source(
            data_source,
            input_csv=input_csv_path,
            collection_id=collection_id,
            filter_for_mode=False,
        )
        coverage = report.report_source_coverage(papers_df, source_label=source_label)
        input_mode = report.normalize_report_input_mode(data.get("report_input_mode", "abstract_only"))
        if input_mode == "fulltext_only":
            usable_count = coverage["fulltext_paper_count"]
        elif input_mode == "abstract_plus_fulltext":
            usable_count = coverage["mixed_usable_count"]
        else:
            usable_count = coverage["abstract_count"]

        warning = ""
        if usable_count == 0:
            warning = "当前证据范围下没有可用于生成报告的文献"
        elif input_mode != "abstract_only" and coverage["fulltext_paper_count"] == 0:
            warning = "当前数据没有已解析全文，建议先解析全文或改用仅摘要"
        elif input_mode != "abstract_only" and coverage["fulltext_coverage"] < 50:
            warning = "全文覆盖率低于 50%，报告中的全文证据可能不完整"

        return jsonify({
            **coverage,
            "data_source": data_source,
            "input_mode": input_mode,
            "usable_count": usable_count,
            "can_generate": usable_count > 0,
            "warning": warning,
            "column_mappings": column_mappings,
        })
    except (FileNotFoundError, RuntimeError, ValueError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        return jsonify({'error': str(exc)}), 400


@app.route('/api/generate', methods=['POST'])
def generate():
    if not report:
        return jsonify({'error': 'Report module not available'}), 500
    
    data = request.get_json(silent=True) or {}
    saved_report_settings = load_report_generation_settings()
    effective_data = {**saved_report_settings, **{key: value for key, value in data.items() if value not in (None, "")}}
    task_id = f"generate_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    # 获取报告数据来源
    report_data_source = report.normalize_report_data_source(effective_data.get("report_data_source", "csv"))
    report_collection_id = str(effective_data.get("report_collection_id") or "").strip()
    input_csv_path = None
    if report_data_source == "csv":
        input_csv = data.get('input_csv', '')
        if not input_csv:
            return jsonify({'error': '请选择一个 CSV 数据集'}), 400
        try:
            input_csv_path = resolve_project_file(input_csv)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
    elif report_data_source == "collection" and not report_collection_id:
        return jsonify({'error': '请选择一个文献主题库'}), 400
    llm_error = validate_llm_config_payload(effective_data)
    if llm_error:
        return jsonify({'error': llm_error}), 400
    
    # 构建报告配置
    report_config = {
        "llm_provider": effective_data.get("llm_provider", "ollama"),
        "output_dir": data.get("output_dir", ""),
        "ollama_base_url": effective_data.get("ollama_base_url", effective_data.get("llm_base_url", "")),
        "llm_base_url": effective_data.get("llm_base_url", effective_data.get("ollama_base_url", "")),
        "llm_api_key": effective_data.get("llm_api_key", report.CONFIG.get("llm_api_key", "")),
        "model": effective_data.get("model", report.CONFIG.get("model", "")),
        "max_papers_for_llm": int(effective_data.get("max_papers_for_llm", 10)),
        "report_style": effective_data.get("report_style", "科研日报"),
        "report_data_source": report_data_source,
        "report_collection_id": report_collection_id,
        "report_input_mode": effective_data.get("report_input_mode", "abstract_only"),
        "keep_empty_abstract": bool(effective_data.get("keep_empty_abstract", False)),
        "temperature": float(effective_data.get("temperature", 0.7)),
        "top_p": float(effective_data.get("top_p", 0.9)),
        "num_predict": int(effective_data.get("num_predict", 8000)),
        "max_retry": int(effective_data.get("max_retry", 3)),
        "topic_override": effective_data.get("topic_override", ""),
        "min_research_content_chars": int(effective_data.get("min_research_content_chars", 500)),
        "save_debug_files": bool(effective_data.get("save_debug_files", False)),
    }
    
    def generate_task():
        source_label = relative_project_path(input_csv_path) if input_csv_path else (
            "所选文献主题库" if report_data_source == "collection" else "全部文献库"
        )
        log_to_task(task_id, f"开始生成综述: {source_label}")
        
        try:
            output_dir = report_config["output_dir"] or str(OUTPUTS_DIR)
            generation_results = report.generate_reports(
                input_csv=input_csv_path,
                output_dir=output_dir,
                config_overrides=report_config,
                logger=lambda msg: log_to_task(task_id, msg),
                data_source=report_data_source,
                collection_id=report_collection_id,
            )
            log_to_task(task_id, "综述生成完成")
            report_files = [
                display_path(item.get("md_path"))
                for item in generation_results
                if item.get("md_path")
            ]
            return {'status': 'success', 'report_files': report_files}
        except Exception as e:
            log_to_task(task_id, f"生成过程中发生错误: {str(e)}")
            raise
    
    task_manager.add_task(task_id, '综述生成', generate_task)
    return jsonify({'task_id': task_id})

@app.route('/api/task/<task_id>')
def get_task_status(task_id):
    task = task_manager.get_task(task_id)
    if task:
        response_task = dict(task)
        logs = list(task.get("logs") or [])
        try:
            since = max(0, int(request.args.get("since", 0)))
        except (TypeError, ValueError):
            since = 0
        if since:
            response_task["logs"] = logs[since:]
            response_task["log_offset"] = since
        else:
            response_task["logs"] = logs[-80:]
            response_task["log_offset"] = max(0, len(logs) - len(response_task["logs"]))
        response_task["log_count"] = len(logs)
        if task_id.startswith("graph_") and isinstance(task.get("result"), dict):
            response_task["result"] = compact_graph_result(task["result"])
        return jsonify(response_task)
    else:
        return jsonify({'error': 'Task not found'}), 404

@app.route('/api/files')
def list_files():
    # 列出搜索结果CSV文件
    search_csvs = []
    if SEARCH_RESULTS_DIR.exists() or LEGACY_SEARCH_RESULTS_DIR.exists():
        search_csvs = iter_search_csv_files()[:20]  # 只返回最新的20个
    
    # 列出输出文件
    output_files = []
    if OUTPUTS_DIR.exists() or LEGACY_OUTPUTS_DIR.exists():
        output_files = iter_report_files()[:20]  # 只返回最新的20个

    output_dirs = [OUTPUTS_DIR]
    if output_files:
        output_dirs.extend(sorted({path.parent for path in output_files}, key=lambda item: str(item)))
    
    return jsonify({
        'search_csvs': [str(f.relative_to(PROJECT_DIR)) for f in search_csvs],
        'output_files': [str(f.relative_to(PROJECT_DIR)) for f in output_files],
        'output_dirs': [str(path) for path in output_dirs],
    })


def connect_literature_library() -> sqlite3.Connection:
    conn = sqlite3.connect(LITERATURE_LIBRARY_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.create_function("KEYWORD_MATCH", -1, keyword_matches_any_text)
    if literature_store is not None:
        literature_store.init_schema(conn)
    if pdf_store is not None:
        pdf_store.ensure_schema(conn)
        pdf_store.ensure_fts_schema(conn)
        obsolete_identity_keys = [
            str(row["identity_key"])
            for row in conn.execute(
                """
                SELECT identity_key
                FROM paper_fulltext
                WHERE COALESCE(parse_engine, '') != ?
                """,
                (CURRENT_PARSE_ENGINE,),
            ).fetchall()
        ]
        conn.execute(
            """
            DELETE FROM paper_chunks
            WHERE identity_key IN (
                SELECT identity_key
                FROM paper_fulltext
                WHERE COALESCE(parse_engine, '') != ?
            )
            """,
            (CURRENT_PARSE_ENGINE,),
        )
        conn.execute(
            """
            DELETE FROM paper_fulltext
            WHERE COALESCE(parse_engine, '') != ?
            """,
            (CURRENT_PARSE_ENGINE,),
        )
        for identity_key in obsolete_identity_keys:
            pdf_store.prune_stale_fulltext_embeddings(conn, identity_key)
        conn.commit()
    return conn


_qa_migration_lock = threading.Lock()
_qa_migration_complete = False


def _sqlite_table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _migrate_legacy_qa_tables(qa_conn: sqlite3.Connection) -> None:
    global _qa_migration_complete
    if _qa_migration_complete or not LITERATURE_LIBRARY_DB.exists():
        return
    with _qa_migration_lock:
        if _qa_migration_complete:
            return
        legacy = sqlite3.connect(LITERATURE_LIBRARY_DB)
        legacy.row_factory = sqlite3.Row
        legacy.execute("PRAGMA foreign_keys=ON")
        try:
            table_columns = {
                "qa_sessions": ["session_id", "title", "scope_type", "scope_json", "created_at", "updated_at"],
                "qa_messages": [
                    "message_id", "session_id", "role", "content", "model", "prompt_tokens",
                    "completion_tokens", "total_tokens", "retrieval_mode", "created_at",
                ],
                "qa_citations": [
                    "citation_id", "message_id", "chunk_id", "citation_order", "identity_key",
                    "section_title", "page_start", "page_end", "quoted_text", "source_type", "paper_title",
                ],
            }
            found = [name for name in table_columns if _sqlite_table_exists(legacy, name)]
            if not found:
                _qa_migration_complete = True
                return
            source_ids: dict[str, list[str]] = {}
            primary_keys = {"qa_sessions": "session_id", "qa_messages": "message_id", "qa_citations": "citation_id"}
            for table_name in ("qa_sessions", "qa_messages", "qa_citations"):
                if table_name not in found:
                    continue
                existing = {row[1] for row in legacy.execute(f"PRAGMA table_info({table_name})").fetchall()}
                columns = [column for column in table_columns[table_name] if column in existing]
                rows = legacy.execute(f"SELECT {', '.join(columns)} FROM {table_name}").fetchall()
                if rows:
                    placeholders = ", ".join("?" for _ in columns)
                    qa_conn.executemany(
                        f"INSERT OR IGNORE INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})",
                        [tuple(row[column] for column in columns) for row in rows],
                    )
                source_ids[table_name] = [str(row[primary_keys[table_name]]) for row in rows]
            qa_conn.commit()

            for table_name, ids in source_ids.items():
                if not ids:
                    continue
                key = primary_keys[table_name]
                placeholders = ",".join("?" for _ in ids)
                copied = qa_conn.execute(
                    f"SELECT COUNT(*) FROM {table_name} WHERE {key} IN ({placeholders})",
                    ids,
                ).fetchone()[0]
                if int(copied or 0) != len(ids):
                    raise RuntimeError(f"迁移 {table_name} 校验失败：期望 {len(ids)}，实际 {copied}")

            legacy.execute("BEGIN")
            for table_name in ("qa_citations", "qa_messages", "qa_sessions"):
                if table_name in found:
                    legacy.execute(f"DROP TABLE {table_name}")
            legacy.commit()
            _qa_migration_complete = True
        except Exception:
            legacy.rollback()
            raise
        finally:
            legacy.close()


def connect_knowledge_qa() -> sqlite3.Connection:
    if qa_store is None:
        raise RuntimeError("问答数据库模块不可用")
    conn = qa_store.connect_db(KNOWLEDGE_QA_DB)
    _migrate_legacy_qa_tables(conn)
    return conn


def _qa_detail_with_scope(detail: dict | None) -> dict | None:
    if detail is None:
        return None
    payload = dict(detail)
    try:
        scope = json.loads(payload.get("scope_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        scope = {}
    payload["scope"] = scope if isinstance(scope, dict) else {}
    return payload


def sync_qa_history_markdown(qa_conn: sqlite3.Connection, session_id: str) -> Path | None:
    if history_store is None:
        return None
    detail = _qa_detail_with_scope(qa_store.get_session_detail(qa_conn, session_id))
    if detail is None:
        return None
    try:
        return history_store.write_session(KNOWLEDGE_QA_HISTORY_DIR, detail)
    except OSError as exc:
        logger.warning("同步问答 Markdown 失败（%s）：%s", session_id, exc)
        return None


def library_exists() -> bool:
    return LITERATURE_LIBRARY_DB.exists()


@app.route('/api/library/summary')
def library_summary():
    if not library_exists():
        return jsonify({
            "exists": False,
            "db_path": str(LITERATURE_LIBRARY_DB.relative_to(PROJECT_DIR)),
            "papers": 0,
            "runs": 0,
            "links": 0,
            "with_doi": 0,
            "with_abstract": 0,
            "latest_seen_at": "",
        })

    try:
        with connect_literature_library() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS papers,
                    SUM(CASE WHEN doi != '' THEN 1 ELSE 0 END) AS with_doi,
                    SUM(CASE WHEN abstract != '' THEN 1 ELSE 0 END) AS with_abstract,
                    MAX(last_seen_at) AS latest_seen_at
                FROM papers
                """
            ).fetchone()
            runs = conn.execute("SELECT COUNT(*) FROM search_runs").fetchone()[0]
            links = conn.execute("SELECT COUNT(*) FROM run_papers").fetchone()[0]
            documents = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN download_status = 'downloaded' THEN 1 ELSE 0 END) AS downloaded,
                    SUM(CASE WHEN download_status = 'failed' THEN 1 ELSE 0 END) AS failed
                FROM paper_documents
                """
            ).fetchone()
            fulltext = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN parse_status = 'parsed' THEN 1 ELSE 0 END) AS parsed,
                    SUM(CASE WHEN parse_status = 'failed' THEN 1 ELSE 0 END) AS failed,
                    AVG(CASE WHEN parse_status = 'parsed' THEN COALESCE(page_mapping_coverage, 0) END) AS avg_page_mapping_coverage,
                    SUM(CASE WHEN parse_status = 'parsed' AND COALESCE(parse_quality, '') = 'good' THEN 1 ELSE 0 END) AS quality_good,
                    SUM(CASE WHEN parse_status = 'parsed' AND COALESCE(parse_quality, '') = 'warning' THEN 1 ELSE 0 END) AS quality_warning,
                    SUM(CASE WHEN parse_status = 'parsed' AND COALESCE(parse_quality, '') = 'poor' THEN 1 ELSE 0 END) AS quality_poor
                FROM paper_fulltext
                """
            ).fetchone()
        return jsonify({
            "exists": True,
            "db_path": str(LITERATURE_LIBRARY_DB.relative_to(PROJECT_DIR)),
            "papers": int(row["papers"] or 0),
            "runs": int(runs or 0),
            "links": int(links or 0),
            "with_doi": int(row["with_doi"] or 0),
            "with_abstract": int(row["with_abstract"] or 0),
            "pdf_total": int(documents["total"] or 0),
            "pdf_downloaded": int(documents["downloaded"] or 0),
            "pdf_failed": int(documents["failed"] or 0),
            "fulltext_total": int(fulltext["total"] or 0),
            "fulltext_parsed": int(fulltext["parsed"] or 0),
            "fulltext_failed": int(fulltext["failed"] or 0),
            "avg_page_mapping_coverage": float(fulltext["avg_page_mapping_coverage"] or 0),
            "quality_good": int(fulltext["quality_good"] or 0),
            "quality_warning": int(fulltext["quality_warning"] or 0),
            "quality_poor": int(fulltext["quality_poor"] or 0),
            "latest_seen_at": row["latest_seen_at"] or "",
        })
    except Exception as exc:
        return jsonify({"error": f"读取文献库失败: {exc}"}), 500


@app.route('/api/library/papers')
def library_papers():
    if not library_exists():
        return jsonify({"data": [], "page": 1, "per_page": 20, "total": 0, "total_pages": 1})

    page = max(1, int(request.args.get("page", 1)))
    per_page = min(50, max(1, int(request.args.get("per_page", 20))))
    keyword = request.args.get("q", "").strip()
    sort_by = request.args.get("sort_by", "last_seen_at").strip()
    sort_dir = request.args.get("sort_dir", "desc").strip().lower()
    sort_dir = "asc" if sort_dir == "asc" else "desc"
    sortable = {
        "last_seen_at": "p.last_seen_at",
        "publicationDate": "p.publicationDate",
        "citationCount": "CAST(NULLIF(p.citationCount, '') AS INTEGER)",
        "title": "p.title",
    }
    order_expr = sortable.get(sort_by, "p.last_seen_at")

    where = ""
    params: list[str | int] = []
    if keyword:
        where = """
            WHERE KEYWORD_MATCH(?, p.title, p.authors, p.abstract, p.venue, p.doi, p.query)
        """
        params.append(keyword)

    try:
        with connect_literature_library() as conn:
            stats = conn.execute(
                f"""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN doi != '' THEN 1 ELSE 0 END) AS with_doi,
                    SUM(CASE WHEN abstract != '' THEN 1 ELSE 0 END) AS with_abstract
                FROM papers
                p
                {where}
                """,
                params,
            ).fetchone()
            total = stats["total"]
            offset = (page - 1) * per_page
            rows = conn.execute(
                f"""
                SELECT
                    p.identity_key, p.doi, p.title, p.authors, p.abstract, p.year, p.venue,
                    p.publicationDate, p.citationCount, p.url, p.pdf_url, p.source,
                    p.enrichment_sources, p.first_seen_at, p.last_seen_at,
                    p.discovery_count, p.last_dataset,
                    COALESCE(d.download_status, 'not_downloaded') AS download_status,
                    COALESCE(d.download_error, '') AS download_error,
                    COALESCE(d.pdf_path, '') AS pdf_path,
                    COALESCE(d.downloaded_at, '') AS downloaded_at,
                    COALESCE(d.pdf_source, '') AS pdf_source,
                    COALESCE(f.parse_status, 'not_parsed') AS parse_status,
                    COALESCE(f.parse_error, '') AS parse_error,
                    COALESCE(f.parse_engine, '') AS parse_engine,
                    COALESCE(f.markdown_path, '') AS markdown_path,
                    COALESCE(f.page_count, 0) AS page_count,
                    COALESCE(f.parsed_at, '') AS parsed_at,
                    COALESCE(f.parse_quality, '') AS parse_quality,
                    COALESCE(f.page_mapping_coverage, 0) AS page_mapping_coverage,
                    COALESCE(f.text_length, 0) AS text_length,
                    COALESCE(f.quality_warnings_json, '[]') AS quality_warnings_json,
                    (
                        SELECT COUNT(*)
                        FROM paper_chunks c
                        WHERE c.identity_key = p.identity_key
                    ) AS chunk_count
                FROM papers p
                LEFT JOIN paper_documents d ON d.identity_key = p.identity_key
                LEFT JOIN paper_fulltext f ON f.identity_key = p.identity_key
                {where}
                ORDER BY {order_expr} {sort_dir.upper()}, p.title ASC
                LIMIT ? OFFSET ?
                """,
                [*params, per_page, offset],
            ).fetchall()
            data_rows = sync_missing_pdf_documents(conn, rows)
        return jsonify({
            "data": data_rows,
            "page": page,
            "per_page": per_page,
            "total": int(total or 0),
            "with_doi": int(stats["with_doi"] or 0),
            "with_abstract": int(stats["with_abstract"] or 0),
            "page_count": len(rows),
            "total_pages": max(1, (int(total or 0) + per_page - 1) // per_page),
            "q": keyword,
            "sort_by": sort_by,
            "sort_dir": sort_dir,
        })
    except Exception as exc:
        return jsonify({"error": f"读取文献库失败: {exc}"}), 500


def split_collection_keywords(value) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = re.split(r"[,;；，\n]+", str(value or ""))
    keywords = []
    seen = set()
    for item in raw_items:
        text = re.sub(r"\s+", " ", str(item or "")).strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            keywords.append(text)
    return keywords


def normalize_collection_rules(payload) -> dict:
    data = payload if isinstance(payload, dict) else {}
    return {
        "include_keywords": split_collection_keywords(data.get("include_keywords", "")),
        "exclude_keywords": split_collection_keywords(data.get("exclude_keywords", "")),
    }


def collection_match_text(row: sqlite3.Row) -> str:
    return "\n".join(
        str(row[key] or "")
        for key in ["title", "authors", "abstract", "venue", "doi", "query"]
        if key in row.keys()
    )


def paper_matches_collection_rules(row: sqlite3.Row, rules: dict) -> tuple[bool, float]:
    text = collection_match_text(row)
    include_keywords = [str(item).strip() for item in rules.get("include_keywords", []) if str(item).strip()]
    exclude_keywords = [str(item).strip() for item in rules.get("exclude_keywords", []) if str(item).strip()]
    if include_keywords and not any(keyword_matches_text(keyword, text) for keyword in include_keywords):
        return False, 0.0
    if exclude_keywords and any(keyword_matches_text(keyword, text) for keyword in exclude_keywords):
        return False, 0.0
    matched = sum(1 for keyword in include_keywords if keyword_matches_text(keyword, text))
    score = float(matched or (1 if not include_keywords else 0))
    return True, score


def collection_row_to_dict(row: sqlite3.Row) -> dict:
    payload = dict(row)
    try:
        payload["rules"] = json.loads(payload.pop("rules_json") or "{}")
    except Exception:
        payload["rules"] = {}
    return payload


def sync_missing_pdf_documents(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[dict]:
    payloads = []
    changed = False
    for row in rows:
        item = dict(row)
        quality = parse_quality_payload(row) if hasattr(row, 'keys') else parse_quality_payload(item)
        item.update(quality)
        item["quality_warning_summary"] = summarize_quality_warnings(item.get("quality_warnings", []))
        if (
            pdf_store is not None
            and item.get("download_status") == "downloaded"
            and item.get("pdf_path")
        ):
            pdf_path = pdf_store.resolve_pdf_path(item["pdf_path"], PROJECT_DIR)
            if not pdf_path.exists():
                pdf_store.mark_not_downloaded(
                    conn,
                    identity_key=item.get("identity_key", ""),
                    doi=item.get("doi", ""),
                    pdf_url=item.get("pdf_url", ""),
                )
                item["download_status"] = "not_downloaded"
                item["download_error"] = ""
                item["pdf_path"] = ""
                item["downloaded_at"] = ""
                changed = True
        payloads.append(item)
    if changed:
        conn.commit()
    return payloads


def normalize_identity_keys(value) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = [value]
    keys = []
    seen = set()
    for item in raw_items:
        key = str(item or "").strip()
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def delete_library_papers_by_keys(conn: sqlite3.Connection, identity_keys: list[str]) -> int:
    if not identity_keys:
        return 0
    deleted = 0
    for identity_key in identity_keys:
        cursor = conn.execute("DELETE FROM papers WHERE identity_key = ?", (identity_key,))
        deleted += cursor.rowcount
    return deleted


def upsert_manual_metadata_records(
    records,
    *,
    source_path: Path | None = None,
    source_label: str = "manual",
    run_type: str = "manual_import",
) -> dict:
    if not multi_source_search or not literature_store:
        raise RuntimeError("多源检索模块不可用")
    valid_records = [record for record in records if str(record.title or "").strip()]
    skipped = len(records) - len(valid_records)
    if not valid_records:
        raise ValueError("没有可入库的文献；每条记录至少需要题目")
    valid_records = multi_source_search.merge_records(valid_records)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_id = f"{run_type}_{timestamp}_{uuid.uuid4().hex[:6]}"
    source_text = str(source_path or "")
    sources = sorted({record.source or source_label for record in valid_records})
    result = literature_store.upsert_records(
        valid_records,
        output_dir=SEARCH_RESULTS_DIR,
        run_id=run_id,
        query=source_label,
        run_type=run_type,
        sources=sources,
        csv_path=source_text if source_path and source_path.suffix.lower() == ".csv" else "",
        jsonl_path=source_text if source_path and source_path.suffix.lower() in {".json", ".jsonl"} else "",
    )
    return {
        "imported": len(valid_records),
        "inserted": result["inserted"],
        "updated": result["updated"],
        "skipped": skipped,
        "run_id": run_id,
    }


@app.route('/api/library/import_csv', methods=['POST'])
def import_csv_to_library():
    if not multi_source_search or not literature_store:
        return jsonify({"error": "多源检索模块不可用"}), 500
    data = request.get_json(silent=True) or {}
    file_path = str(data.get("path") or "").strip()
    if not file_path:
        return jsonify({"error": "缺少 CSV 路径"}), 400
    try:
        full_path = resolve_project_file(file_path)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not full_path.exists() or full_path.suffix.lower() != ".csv":
        return jsonify({"error": "CSV 文件不存在或类型不支持"}), 404
    try:
        records = multi_source_search.records_from_csv(full_path)
        row_indices = data.get("row_indices")
        if isinstance(row_indices, list) and row_indices:
            selected = {int(item) for item in row_indices if str(item).strip().isdigit()}
            records = [record for index, record in enumerate(records) if index in selected]
        if not records:
            return jsonify({"error": "没有可入库的文献"}), 400
        run_id = f"import_{full_path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        sources = sorted({record.source or "csv" for record in records})
        result = literature_store.upsert_records(
            records,
            output_dir=SEARCH_RESULTS_DIR,
            run_id=run_id,
            query=full_path.stem,
            run_type="import",
            sources=sources,
            csv_path=full_path,
            jsonl_path="",
        )
        return jsonify({
            "imported": len(records),
            "inserted": result["inserted"],
            "updated": result["updated"],
            "run_id": run_id,
        })
    except Exception as exc:
        return jsonify({"error": f"CSV 入库失败: {exc}"}), 500


@app.route('/api/library/import_metadata_file', methods=['POST'])
def import_metadata_file_to_library():
    if not multi_source_search or not literature_store:
        return jsonify({"error": "多源检索模块不可用"}), 500
    uploaded_file = request.files.get("file")
    if not uploaded_file or not uploaded_file.filename:
        return jsonify({"error": "请选择 CSV、JSON 或 JSONL 元数据文件"}), 400

    suffix = Path(uploaded_file.filename).suffix.lower()
    if suffix not in {".csv", ".json", ".jsonl"}:
        return jsonify({"error": "仅支持 CSV、JSON 和 JSONL 文件"}), 400
    original_name = secure_filename(uploaded_file.filename) or f"metadata{suffix}"
    stem = Path(original_name).stem or "metadata"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_dir = METADATA_CSV_DIR if suffix == ".csv" else METADATA_JSON_DIR
    target_path = target_dir / f"{stem}_{timestamp}_{uuid.uuid4().hex[:6]}{suffix}"
    uploaded_file.save(target_path)

    try:
        if target_path.stat().st_size > 20 * 1024 * 1024:
            raise ValueError("元数据文件不能超过 20 MB")
        records = (
            multi_source_search.records_from_csv(target_path)
            if suffix == ".csv"
            else multi_source_search.records_from_json(target_path)
        )
        result = upsert_manual_metadata_records(
            records,
            source_path=target_path,
            source_label=target_path.stem,
            run_type="metadata_file_import",
        )
        result["stored_path"] = str(target_path.relative_to(PROJECT_DIR))
        return jsonify(result)
    except (ValueError, json.JSONDecodeError, pd.errors.ParserError, UnicodeError) as exc:
        target_path.unlink(missing_ok=True)
        return jsonify({"error": f"元数据文件读取失败: {exc}"}), 400
    except Exception as exc:
        target_path.unlink(missing_ok=True)
        return jsonify({"error": f"元数据文件入库失败: {exc}"}), 500


@app.route('/api/library/papers/manual', methods=['POST'])
def create_manual_library_paper():
    if not multi_source_search or not literature_store:
        return jsonify({"error": "多源检索模块不可用"}), 500
    data = request.get_json(silent=True) or {}
    if not str(data.get("title") or "").strip():
        return jsonify({"error": "文献题目不能为空"}), 400
    try:
        record = multi_source_search.record_from_mapping(data, default_source="manual")
        result = upsert_manual_metadata_records(
            [record],
            source_label="manual",
            run_type="manual_entry",
        )
        result["identity_key"] = literature_store.identity_key_for_record(record)
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"单篇元数据入库失败: {exc}"}), 500


@app.route('/api/library/collections')
def library_collections():
    if not library_exists():
        return jsonify({"data": []})
    try:
        with connect_literature_library() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.collection_id, c.name, c.collection_type, c.description,
                    c.rules_json, c.created_at, c.updated_at,
                    COUNT(cp.identity_key) AS paper_count
                FROM library_collections c
                LEFT JOIN collection_papers cp ON cp.collection_id = c.collection_id
                GROUP BY c.collection_id
                ORDER BY c.updated_at DESC, c.name ASC
                """
            ).fetchall()
        return jsonify({"data": [collection_row_to_dict(row) for row in rows]})
    except Exception as exc:
        return jsonify({"error": f"读取主题库失败: {exc}"}), 500


@app.route('/api/library/collections', methods=['POST'])
def create_library_collection():
    data = request.get_json(silent=True) or {}
    name = re.sub(r"\s+", " ", str(data.get("name") or "")).strip()
    if not name:
        return jsonify({"error": "主题库名称不能为空"}), 400
    collection_type = str(data.get("collection_type") or "custom").strip() or "custom"
    if collection_type not in {"material", "method", "project", "custom"}:
        collection_type = "custom"
    rules = normalize_collection_rules(data.get("rules") or {})
    now = datetime.now().isoformat(timespec="seconds")
    collection_id = f"col_{uuid.uuid4().hex[:12]}"
    try:
        with connect_literature_library() as conn:
            conn.execute(
                """
                INSERT INTO library_collections (
                    collection_id, name, collection_type, description,
                    rules_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    collection_id,
                    name,
                    collection_type,
                    str(data.get("description") or "").strip(),
                    json.dumps(rules, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            conn.commit()
        return jsonify({"collection_id": collection_id})
    except sqlite3.IntegrityError:
        return jsonify({"error": "同名主题库已存在"}), 409
    except Exception as exc:
        return jsonify({"error": f"创建主题库失败: {exc}"}), 500


@app.route('/api/library/collections/<collection_id>/papers')
def library_collection_papers(collection_id):
    if not library_exists():
        return jsonify({"data": [], "collection": None})
    try:
        with connect_literature_library() as conn:
            collection = conn.execute(
                "SELECT * FROM library_collections WHERE collection_id = ?",
                (collection_id,),
            ).fetchone()
            if collection is None:
                return jsonify({"error": "主题库不存在"}), 404
            rows = conn.execute(
                """
                SELECT
                    p.identity_key, p.doi, p.title, p.authors, p.abstract, p.year, p.venue,
                    p.publicationDate, p.citationCount, p.url, p.pdf_url,
                    COALESCE(d.download_status, 'not_downloaded') AS download_status,
                    COALESCE(d.download_error, '') AS download_error,
                    COALESCE(d.pdf_path, '') AS pdf_path,
                    COALESCE(d.downloaded_at, '') AS downloaded_at,
                    COALESCE(d.pdf_source, '') AS pdf_source,
                    COALESCE(f.parse_status, 'not_parsed') AS parse_status,
                    COALESCE(f.parse_error, '') AS parse_error,
                    COALESCE(f.parse_engine, '') AS parse_engine,
                    COALESCE(f.markdown_path, '') AS markdown_path,
                    COALESCE(f.page_count, 0) AS page_count,
                    COALESCE(f.parsed_at, '') AS parsed_at,
                    COALESCE(f.parse_quality, '') AS parse_quality,
                    COALESCE(f.page_mapping_coverage, 0) AS page_mapping_coverage,
                    COALESCE(f.text_length, 0) AS text_length,
                    COALESCE(f.quality_warnings_json, '[]') AS quality_warnings_json,
                    (
                        SELECT COUNT(*)
                        FROM paper_chunks c
                        WHERE c.identity_key = p.identity_key
                    ) AS chunk_count,
                    cp.match_source, cp.match_score, cp.note, cp.created_at AS added_at
                FROM collection_papers cp
                JOIN papers p ON p.identity_key = cp.identity_key
                LEFT JOIN paper_documents d ON d.identity_key = p.identity_key
                LEFT JOIN paper_fulltext f ON f.identity_key = p.identity_key
                WHERE cp.collection_id = ?
                ORDER BY cp.created_at DESC, p.title ASC
                LIMIT 200
                """,
                (collection_id,),
            ).fetchall()
            data_rows = sync_missing_pdf_documents(conn, rows)
        return jsonify({
            "collection": collection_row_to_dict(collection),
            "data": data_rows,
        })
    except Exception as exc:
        return jsonify({"error": f"读取主题库文献失败: {exc}"}), 500


@app.route('/api/library/search/fulltext')
def library_fulltext_search():
    if pdf_store is None or fulltext_search is None:
        return jsonify({"error": "全文检索模块不可用"}), 500
    if not library_exists():
        return jsonify({"error": "文献库尚未创建"}), 404

    query = str(request.args.get("q") or "").strip()
    scope_type = str(request.args.get("scope_type") or "all_papers").strip() or "all_papers"
    identity_key = str(request.args.get("identity_key") or "").strip()
    collection_id = str(request.args.get("collection_id") or "").strip()
    identity_keys_raw = str(request.args.get("identity_keys") or "").strip()
    identity_keys = [item.strip() for item in identity_keys_raw.split(",") if item.strip()]
    limit = min(50, max(1, int(request.args.get("limit", 12))))

    try:
        with connect_literature_library() as conn:
            result = fulltext_search.search_fulltext(
                conn,
                query=query,
                scope_type=scope_type,
                identity_key=identity_key,
                identity_keys=identity_keys,
                collection_id=collection_id,
                limit=limit,
            )
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"全文检索失败: {exc}"}), 500


@app.route('/api/library/qa/sessions', methods=['GET'])
def list_library_qa_sessions():
    return jsonify({"error": "单篇文献问答已移除，请使用知识问答页面"}), 410
    if pdf_store is None:
        return jsonify({"error": "QA 模块不可用"}), 500
    if not library_exists():
        return jsonify({"data": []})
    identity_key = str(request.args.get("identity_key") or "").strip()
    try:
        with connect_literature_library() as conn:
            sessions = pdf_store.list_qa_sessions(conn, limit=100, identity_key=identity_key)
        return jsonify({"data": sessions})
    except Exception as exc:
        return jsonify({"error": f"读取问答会话失败: {exc}"}), 500


@app.route('/api/library/qa/sessions', methods=['POST'])
def create_library_qa_session():
    return jsonify({"error": "单篇文献问答已移除，请使用知识问答页面"}), 410
    if pdf_store is None:
        return jsonify({"error": "QA 模块不可用"}), 500
    if not library_exists():
        return jsonify({"error": "文献库尚未创建"}), 404
    data = request.get_json(silent=True) or {}
    scope_type = str(data.get("scope_type") or "current_paper").strip() or "current_paper"
    identity_key = str(data.get("identity_key") or "").strip()
    title = str(data.get("title") or "").strip()
    if scope_type != "current_paper":
        return jsonify({"error": "当前版本仅支持单篇文献问答"}), 400
    if not identity_key:
        return jsonify({"error": "缺少 identity_key"}), 400
    session_id = f"qa_{uuid.uuid4().hex[:12]}"
    scope_json = json.dumps({"identity_key": identity_key}, ensure_ascii=False)
    try:
        with connect_literature_library() as conn:
            paper = pdf_store.get_paper(conn, identity_key)
            if paper is None:
                return jsonify({"error": "未找到该文献"}), 404
            fulltext = pdf_store.get_fulltext(conn, identity_key)
            if fulltext is None or fulltext["parse_status"] != "parsed":
                return jsonify({"error": "该文献尚未解析全文，请先解析 MD"}), 400
            session = pdf_store.create_qa_session(
                conn,
                session_id=session_id,
                title=title or f"问答：{(paper['title'] or identity_key)[:48]}",
                scope_type=scope_type,
                scope_json=scope_json,
            )
            conn.commit()
        return jsonify(session)
    except Exception as exc:
        return jsonify({"error": f"创建问答会话失败: {exc}"}), 500


@app.route('/api/library/qa/sessions/<session_id>')
def get_library_qa_session(session_id):
    return jsonify({"error": "单篇文献问答已移除，请使用知识问答页面"}), 410
    if pdf_store is None:
        return jsonify({"error": "QA 模块不可用"}), 500
    if not library_exists():
        return jsonify({"error": "文献库尚未创建"}), 404
    try:
        with connect_literature_library() as conn:
            detail = pdf_store.get_qa_session_detail(conn, session_id)
        if detail is None:
            return jsonify({"error": "问答会话不存在"}), 404
        return jsonify(detail)
    except Exception as exc:
        return jsonify({"error": f"读取问答会话失败: {exc}"}), 500


@app.route('/api/library/qa/sessions/<session_id>', methods=['DELETE'])
def delete_library_qa_session(session_id):
    return jsonify({"error": "单篇文献问答已移除，请使用知识问答页面"}), 410
    if pdf_store is None:
        return jsonify({"error": "QA 模块不可用"}), 500
    if not library_exists():
        return jsonify({"error": "文献库尚未创建"}), 404
    try:
        with connect_literature_library() as conn:
            deleted = pdf_store.delete_qa_session(conn, session_id)
            conn.commit()
        if deleted <= 0:
            return jsonify({"error": "问答会话不存在"}), 404
        return jsonify({"deleted": deleted})
    except Exception as exc:
        return jsonify({"error": f"删除问答会话失败: {exc}"}), 500


@app.route('/api/library/qa/sessions/<session_id>/messages', methods=['POST'])
def create_library_qa_message(session_id):
    return jsonify({"error": "单篇文献问答已移除，请使用知识问答页面"}), 410
    if pdf_store is None or qa_service is None:
        return jsonify({"error": "QA 模块不可用"}), 500
    if not library_exists():
        return jsonify({"error": "文献库尚未创建"}), 404

    data = request.get_json(silent=True) or {}
    question = str(data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "问题不能为空"}), 400
    llm_error = validate_llm_config_payload(data)
    if llm_error:
        return jsonify({"error": llm_error}), 400

    try:
        with connect_literature_library() as conn:
            session_row = pdf_store.get_qa_session(conn, session_id)
            if session_row is None:
                return jsonify({"error": "问答会话不存在"}), 404
            if str(session_row["scope_type"] or "") != "current_paper":
                return jsonify({"error": "当前版本仅支持单篇文献问答"}), 400
            try:
                scope = json.loads(session_row["scope_json"] or "{}")
            except Exception:
                scope = {}
            identity_key = str(scope.get("identity_key") or "").strip()
            if not identity_key:
                return jsonify({"error": "问答会话缺少文献标识"}), 400
            paper_row = conn.execute(
                """
                SELECT identity_key, title, authors, doi, venue, publicationDate, year
                FROM papers
                WHERE identity_key = ?
                """,
                (identity_key,),
            ).fetchone()
            if paper_row is None:
                return jsonify({"error": "文献不存在"}), 404
            fulltext = pdf_store.get_fulltext(conn, identity_key)
            if fulltext is None or fulltext["parse_status"] != "parsed":
                return jsonify({"error": "该文献尚未解析全文，请先解析 MD"}), 400
            request_timeout_sec = int(data.get("request_timeout_sec") or 900)
            model_config = {
                "llm_provider": data.get("llm_provider", "ollama"),
                "ollama_base_url": data.get("ollama_base_url", ""),
                "llm_base_url": data.get("llm_base_url", data.get("ollama_base_url", "")),
                "llm_api_key": data.get("llm_api_key", ""),
                "model": data.get("model", ""),
                "temperature": float(data.get("temperature", 0)),
                "top_p": float(data.get("top_p", 0.9)),
                "num_predict": int(data.get("num_predict", 1800)),
                "request_timeout_sec": request_timeout_sec,
            }
            result = qa_service.answer_single_paper_question(
                conn,
                paper=dict(paper_row),
                question=question,
                model_config=model_config,
                call_llm=call_structured_llm_chat,
                top_k=int(data.get("top_k", 8) or 8),
            )
            user_message_id = f"{session_id}::user::{uuid.uuid4().hex[:8]}"
            assistant_message_id = f"{session_id}::assistant::{uuid.uuid4().hex[:8]}"
            pdf_store.create_qa_message(
                conn,
                message_id=user_message_id,
                session_id=session_id,
                role="user",
                content=question,
                model="",
            )
            assistant_message = pdf_store.create_qa_message(
                conn,
                message_id=assistant_message_id,
                session_id=session_id,
                role="assistant",
                content=result["answer"],
                model=str(model_config.get("model") or ""),
            )
            pdf_store.save_qa_citations(conn, message_id=assistant_message_id, citations=result["citations"])
            conn.commit()
            detail = pdf_store.get_qa_session_detail(conn, session_id)
        return jsonify({
            "session": detail,
            "answer": assistant_message,
            "citations": result["citations"],
            "insufficient_evidence": result.get("insufficient_evidence", False),
            "token_usage": result.get("token_usage") or {},
        })
    except Exception as exc:
        return jsonify({"error": f"生成问答失败: {exc}"}), 500


@app.route('/api/knowledge-qa/settings', methods=['GET'])
def get_knowledge_qa_settings():
    if config_store is None:
        return jsonify({"error": "知识问答配置模块不可用"}), 500
    settings = load_knowledge_qa_settings()
    return jsonify(config_store.public_settings(settings))


@app.route('/api/knowledge-qa/settings', methods=['POST'])
def save_knowledge_qa_settings():
    if config_store is None:
        return jsonify({"error": "知识问答配置模块不可用"}), 500
    data = request.get_json(silent=True) or {}
    try:
        settings = config_store.save_settings(KNOWLEDGE_QA_CONFIG_PATH, data)
        return jsonify({
            "message": "模型配置已保存",
            "settings": config_store.public_settings(settings),
        })
    except (TypeError, ValueError) as exc:
        return jsonify({"error": f"配置参数无效: {exc}"}), 400
    except OSError as exc:
        return jsonify({"error": f"保存配置失败: {exc}"}), 500


@app.route('/api/knowledge-qa/settings/test', methods=['POST'])
def test_knowledge_qa_settings():
    if config_store is None:
        return jsonify({"error": "知识问答配置模块不可用"}), 500
    data = request.get_json(silent=True) or {}
    current = load_knowledge_qa_settings()
    try:
        settings = config_store.normalize_settings(data, current=current)
    except (TypeError, ValueError) as exc:
        return jsonify({"error": f"配置参数无效: {exc}"}), 400
    error = config_store.validate_generation_settings(settings)
    if error:
        return jsonify({"error": error}), 400
    try:
        result = call_structured_llm_chat(
            prompt="只回复：连接成功",
            model=settings["model"],
            provider=settings["provider"],
            base_url=settings["base_url"],
            api_key=settings["api_key"],
            temperature=0,
            num_predict=32,
            request_timeout_sec=min(60, settings["request_timeout_sec"]),
        )
        return jsonify({"message": "大模型连接成功", "response": str(result.get("content") or "")[:120]})
    except Exception as exc:
        return jsonify({"error": f"大模型连接失败: {exc}"}), 502


@app.route('/api/knowledge-qa/index/status')
def knowledge_qa_index_status():
    if retriever is None or not library_exists():
        return jsonify({"total": 0, "papers": 0, "updated_at": "", "model": ""})
    settings = load_knowledge_qa_settings()
    try:
        with connect_literature_library() as conn:
            status = retriever.embedding_index_status(conn, model=str(settings.get("embedding_model") or ""))
        return jsonify(status)
    except Exception as exc:
        return jsonify({"error": f"读取向量索引状态失败: {exc}"}), 500


@app.route('/api/knowledge-qa/index', methods=['POST'])
def build_knowledge_qa_index():
    if retriever is None or pdf_store is None or config_store is None:
        return jsonify({"error": "知识检索模块不可用"}), 500
    if not library_exists():
        return jsonify({"error": "文献库尚未创建"}), 404
    settings = load_knowledge_qa_settings()
    if not config_store.embedding_is_configured(settings):
        return jsonify({"error": "请先启用混合检索并完整配置 Embedding 服务"}), 400
    data = request.get_json(silent=True) or {}
    scope_type = str(data.get("scope_type") or "library").strip()
    collection_id = str(data.get("collection_id") or "").strip()
    model = str(settings.get("embedding_model") or "").strip()
    try:
        with connect_literature_library() as conn:
            identity_keys = retriever.scope_identity_keys(conn, scope_type, collection_id)
            sources = retriever.iter_index_sources(conn, identity_keys)
            valid_hashes = {item["source_id"]: item["content_hash"] for item in sources}
            existing = pdf_store.get_embedding_hashes(conn, model=model)
            pending = [item for item in sources if existing.get(item["source_id"]) != item["content_hash"]]
            indexed = 0
            for start in range(0, len(pending), 4):
                batch = pending[start:start + 4]
                try:
                    vectors = call_openai_compatible_embeddings([item["content"] for item in batch], settings)
                    pairs = list(zip(batch, vectors))
                except Exception:
                    pairs = []
                    for item in batch:
                        try:
                            vector = call_openai_compatible_embeddings([item["content"]], settings)[0]
                        except Exception as exc:
                            raise RuntimeError(f"证据 {item['source_id']} 无法向量化：{exc}") from exc
                        pairs.append((item, vector))
                for item, vector in pairs:
                    pdf_store.upsert_knowledge_embedding(
                        conn,
                        source_id=item["source_id"],
                        identity_key=item["identity_key"],
                        source_type=item["source_type"],
                        content_hash=item["content_hash"],
                        embedding_model=model,
                        embedding=vector,
                    )
                    indexed += 1
                conn.commit()
            pruned = pdf_store.prune_embedding_index(
                conn,
                model=model,
                identity_keys=identity_keys,
                valid_hashes=valid_hashes,
            )
            conn.commit()
            status = retriever.embedding_index_status(conn, model=model)
        return jsonify({
            "message": f"语义索引已更新：新增或刷新 {indexed} 条，清理失效 {pruned} 条",
            "indexed": indexed,
            "pruned": pruned,
            "status": status,
        })
    except Exception as exc:
        return jsonify({"error": f"建立语义索引失败: {exc}"}), 500


@app.route('/api/knowledge-qa/reranker/status')
def knowledge_qa_reranker_status():
    if local_reranker is None:
        return jsonify({"deployed": False, "loaded": False, "error": "本地 Reranker 模块不可用"}), 500
    settings = load_knowledge_qa_settings()
    try:
        payload = local_reranker.status(
            KNOWLEDGE_QA_MODELS_DIR,
            model_id=str(settings.get("reranker_model") or local_reranker.DEFAULT_MODEL_ID),
            requested_device=str(settings.get("reranker_device") or "auto"),
        )
        payload["enabled"] = bool(settings.get("reranker_enabled"))
        return jsonify(payload)
    except Exception as exc:
        return jsonify({"deployed": False, "loaded": False, "error": f"读取 Reranker 状态失败: {exc}"}), 500


@app.route('/api/knowledge-qa/reranker/deploy', methods=['POST'])
def deploy_knowledge_qa_reranker():
    if local_reranker is None or config_store is None:
        return jsonify({"error": "本地 Reranker 模块不可用"}), 500
    data = request.get_json(silent=True) or {}
    current = load_knowledge_qa_settings()
    model_id = str(data.get("model_id") or current.get("reranker_model") or local_reranker.DEFAULT_MODEL_ID).strip()
    device = str(data.get("device") or current.get("reranker_device") or "auto").strip()
    try:
        local_reranker.deploy_model(KNOWLEDGE_QA_MODELS_DIR, model_id=model_id)
        smoke_results, smoke = local_reranker.rerank(
            "哪一个片段与材料强度有关？",
            [
                {"chunk_text": "The alloy strength increased after heat treatment."},
                {"chunk_text": "The bibliography contains twenty references."},
            ],
            models_root=KNOWLEDGE_QA_MODELS_DIR,
            model_id=model_id,
            device=device,
            batch_size=2,
            max_length=256,
            top_k=1,
        )
        updated = dict(current)
        updated.update({"reranker_enabled": True, "reranker_model": model_id, "reranker_device": device})
        settings = config_store.save_settings(KNOWLEDGE_QA_CONFIG_PATH, updated)
        status_payload = local_reranker.status(
            KNOWLEDGE_QA_MODELS_DIR,
            model_id=model_id,
            requested_device=device,
        )
        status_payload.update({
            "enabled": True,
            "smoke_test": smoke,
            "top_score": smoke_results[0].get("rerank_score") if smoke_results else None,
        })
        return jsonify({
            "message": f"本地 Reranker 已部署并通过测试（{status_payload['device']}）",
            "status": status_payload,
            "settings": config_store.public_settings(settings),
        })
    except Exception as exc:
        return jsonify({"error": f"部署本地 Reranker 失败: {exc}"}), 500


@app.route('/api/knowledge-qa/sessions', methods=['GET'])
def list_knowledge_qa_sessions():
    if qa_store is None:
        return jsonify({"data": []})
    try:
        with connect_knowledge_qa() as conn:
            rows = qa_store.list_sessions(conn, limit=80)
            for row in rows:
                sync_qa_history_markdown(conn, row["session_id"])
        return jsonify({"data": rows})
    except Exception as exc:
        return jsonify({"error": f"读取问答记录失败: {exc}"}), 500


@app.route('/api/knowledge-qa/sessions', methods=['POST'])
def create_knowledge_qa_session():
    if qa_store is None or not library_exists():
        return jsonify({"error": "文献库尚未创建"}), 404
    data = request.get_json(silent=True) or {}
    scope_type = str(data.get("scope_type") or "library").strip()
    collection_id = str(data.get("collection_id") or "").strip()
    if scope_type not in {"library", "collection"}:
        return jsonify({"error": "不支持的知识范围"}), 400
    try:
        with connect_literature_library() as conn:
            scope_label = "全库文献"
            if scope_type == "collection":
                collection = conn.execute(
                    "SELECT name FROM library_collections WHERE collection_id = ?",
                    (collection_id,),
                ).fetchone()
                if collection is None:
                    return jsonify({"error": "文献主题库不存在"}), 404
                scope_label = str(collection["name"] or "文献主题库")
        session_id = f"kqa_{uuid.uuid4().hex[:12]}"
        with connect_knowledge_qa() as qa_conn:
            session = qa_store.create_session(
                qa_conn,
                session_id=session_id,
                title=str(data.get("title") or f"{scope_label}问答")[:80],
                scope_type=scope_type,
                scope_json=json.dumps({"collection_id": collection_id, "scope_label": scope_label}, ensure_ascii=False),
            )
            qa_conn.commit()
            sync_qa_history_markdown(qa_conn, session_id)
        return jsonify(session)
    except Exception as exc:
        return jsonify({"error": f"创建问答失败: {exc}"}), 500


@app.route('/api/knowledge-qa/sessions/<session_id>', methods=['GET'])
def get_knowledge_qa_session(session_id):
    if qa_store is None:
        return jsonify({"error": "问答数据库模块不可用"}), 500
    try:
        with connect_knowledge_qa() as conn:
            detail = qa_store.get_session_detail(conn, session_id)
        if detail is None or detail.get("scope_type") not in {"library", "collection"}:
            return jsonify({"error": "问答记录不存在"}), 404
        return jsonify(detail)
    except Exception as exc:
        return jsonify({"error": f"读取问答失败: {exc}"}), 500


@app.route('/api/knowledge-qa/sessions/<session_id>', methods=['PATCH'])
def rename_knowledge_qa_session(session_id):
    if qa_store is None:
        return jsonify({"error": "问答数据库模块不可用"}), 500
    data = request.get_json(silent=True) or {}
    title = re.sub(r"\s+", " ", str(data.get("title") or "")).strip()
    if not title:
        return jsonify({"error": "对话名称不能为空"}), 400
    if len(title) > 80:
        return jsonify({"error": "对话名称不能超过 80 个字符"}), 400
    try:
        with connect_knowledge_qa() as conn:
            row = qa_store.get_session(conn, session_id)
            if row is None or row["scope_type"] not in {"library", "collection"}:
                return jsonify({"error": "问答记录不存在"}), 404
            updated = qa_store.update_session_title(conn, session_id, title)
            conn.commit()
            sync_qa_history_markdown(conn, session_id)
        return jsonify(updated)
    except Exception as exc:
        return jsonify({"error": f"修改对话名称失败: {exc}"}), 500


@app.route('/api/knowledge-qa/sessions/<session_id>', methods=['DELETE'])
def delete_knowledge_qa_session(session_id):
    if qa_store is None:
        return jsonify({"error": "问答数据库模块不可用"}), 500
    try:
        with connect_knowledge_qa() as conn:
            row = qa_store.get_session(conn, session_id)
            if row is None or row["scope_type"] not in {"library", "collection"}:
                return jsonify({"error": "问答记录不存在"}), 404
            deleted = qa_store.delete_session(conn, session_id)
            conn.commit()
        try:
            markdown_deleted = history_store.delete_session(KNOWLEDGE_QA_HISTORY_DIR, session_id) if history_store else False
        except OSError as exc:
            logger.warning("删除问答 Markdown 失败（%s）：%s", session_id, exc)
            markdown_deleted = False
        return jsonify({"deleted": deleted, "markdown_deleted": markdown_deleted})
    except Exception as exc:
        return jsonify({"error": f"删除问答失败: {exc}"}), 500


@app.route('/api/knowledge-qa/sessions/<session_id>/messages', methods=['POST'])
def create_knowledge_qa_message(session_id):
    if qa_store is None or qa_service is None or config_store is None or not library_exists():
        return jsonify({"error": "知识问答模块不可用"}), 500
    data = request.get_json(silent=True) or {}
    question = re.sub(r"\s+", " ", str(data.get("question") or "")).strip()
    if not question:
        return jsonify({"error": "问题不能为空"}), 400
    if len(question) > 4000:
        return jsonify({"error": "问题过长，请控制在 4000 字以内"}), 400
    settings = load_knowledge_qa_settings()
    error = config_store.validate_generation_settings(settings)
    if error:
        return jsonify({"error": error, "code": "settings_required"}), 400
    try:
        with connect_knowledge_qa() as qa_conn:
            session_row = qa_store.get_session(qa_conn, session_id)
            session = dict(session_row) if session_row else None
            if session is None or session["scope_type"] not in {"library", "collection"}:
                return jsonify({"error": "问答记录不存在"}), 404
            try:
                scope = json.loads(session["scope_json"] or "{}")
            except json.JSONDecodeError:
                scope = {}
            collection_id = str(scope.get("collection_id") or "")
            scope_label = str(scope.get("scope_label") or ("全库文献" if session["scope_type"] == "library" else "文献主题库"))
            history_rows = qa_conn.execute(
                "SELECT role, content FROM qa_messages WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,),
            ).fetchall()
            conversation = [dict(row) for row in history_rows]
        with connect_literature_library() as conn:
            embed_query = None
            embedding_model = ""
            if config_store.embedding_is_configured(settings):
                embedding_model = str(settings.get("embedding_model") or "")
                embed_query = lambda text: call_openai_compatible_embeddings([text], settings)[0]
            rerank_callback = None
            if local_reranker is not None and settings.get("reranker_enabled"):
                def rerank_callback(question_text, candidates, final_k):
                    return local_reranker.rerank(
                        question_text,
                        candidates,
                        models_root=KNOWLEDGE_QA_MODELS_DIR,
                        model_id=str(settings.get("reranker_model") or local_reranker.DEFAULT_MODEL_ID),
                        device=str(settings.get("reranker_device") or "auto"),
                        batch_size=int(settings.get("reranker_batch_size") or 4),
                        max_length=int(settings.get("reranker_max_length") or 512),
                        top_k=final_k,
                    )
            result = qa_service.answer_scope_question(
                conn,
                question=question,
                scope_type=str(session["scope_type"]),
                collection_id=collection_id,
                scope_label=scope_label,
                model_config=settings,
                call_llm=call_structured_llm_chat,
                conversation=conversation,
                top_k=int(settings.get("top_k") or 10),
                candidate_k=(
                    int(settings.get("reranker_candidate_k") or 40)
                    if rerank_callback is not None else int(settings.get("top_k") or 10)
                ),
                embedding_model=embedding_model,
                embed_query=embed_query,
                rerank_candidates=rerank_callback,
            )
        user_message_id = f"{session_id}::user::{uuid.uuid4().hex[:8]}"
        assistant_message_id = f"{session_id}::assistant::{uuid.uuid4().hex[:8]}"
        with connect_knowledge_qa() as qa_conn:
            if qa_store.get_session(qa_conn, session_id) is None:
                return jsonify({"error": "问答记录已被删除"}), 409
            qa_store.create_message(qa_conn, message_id=user_message_id, session_id=session_id, role="user", content=question)
            assistant_message = qa_store.create_message(
                qa_conn,
                message_id=assistant_message_id,
                session_id=session_id,
                role="assistant",
                content=result["answer"],
                model=str(settings.get("model") or ""),
                token_usage=result["token_usage"],
                retrieval_mode=result["retrieval_mode"],
                rerank_metadata=result.get("rerank") or {},
            )
            qa_store.save_citations(qa_conn, message_id=assistant_message_id, citations=result["citations"])
            if not conversation:
                qa_conn.execute(
                    "UPDATE qa_sessions SET title = ? WHERE session_id = ?",
                    ((question[:34] + ("…" if len(question) > 34 else "")), session_id),
                )
            qa_conn.commit()
            detail = qa_store.get_session_detail(qa_conn, session_id)
            sync_qa_history_markdown(qa_conn, session_id)
        return jsonify({
            "session": detail,
            "answer": assistant_message,
            "citations": result["citations"],
            "insufficient_evidence": result["insufficient_evidence"],
            "retrieval_mode": result["retrieval_mode"],
            "rerank": result.get("rerank") or {},
            "scope_paper_count": result["scope_paper_count"],
            "token_usage": result["token_usage"],
        })
    except Exception as exc:
        logger.exception("知识问答生成失败")
        return jsonify({"error": f"生成问答失败: {exc}"}), 500


@app.route('/api/library/chunks/<path:chunk_id>')
def library_chunk_detail(chunk_id):
    if pdf_store is None:
        return jsonify({"error": "PDF 解析模块不可用"}), 500
    if not library_exists():
        return jsonify({"error": "文献库尚未创建"}), 404
    try:
        with connect_literature_library() as conn:
            chunk = pdf_store.get_chunk_by_id(conn, chunk_id)
            if chunk is None:
                return jsonify({"error": "片段不存在"}), 404
            paper = pdf_store.get_paper(conn, chunk["identity_key"])
        return jsonify({
            "chunk": chunk,
            "paper": dict(paper) if paper else None,
        })
    except Exception as exc:
        return jsonify({"error": f"读取片段失败: {exc}"}), 500


@app.route('/api/library/collections/<collection_id>', methods=['DELETE'])
def delete_library_collection(collection_id):
    if not library_exists():
        return jsonify({"error": "文献库尚未创建"}), 404
    try:
        with connect_literature_library() as conn:
            cursor = conn.execute(
                "DELETE FROM library_collections WHERE collection_id = ?",
                (collection_id,),
            )
            conn.commit()
        if cursor.rowcount <= 0:
            return jsonify({"error": "主题库不存在"}), 404
        return jsonify({"deleted": cursor.rowcount})
    except Exception as exc:
        return jsonify({"error": f"删除主题库失败: {exc}"}), 500


@app.route('/api/library/collections/<collection_id>/papers', methods=['POST'])
def add_paper_to_collection(collection_id):
    data = request.get_json(silent=True) or {}
    identity_key = str(data.get("identity_key") or "").strip()
    if not identity_key:
        return jsonify({"error": "缺少 identity_key"}), 400
    now = datetime.now().isoformat(timespec="seconds")
    try:
        with connect_literature_library() as conn:
            collection = conn.execute(
                "SELECT collection_id FROM library_collections WHERE collection_id = ?",
                (collection_id,),
            ).fetchone()
            if collection is None:
                return jsonify({"error": "主题库不存在"}), 404
            paper = conn.execute("SELECT identity_key FROM papers WHERE identity_key = ?", (identity_key,)).fetchone()
            if paper is None:
                return jsonify({"error": "文献不存在"}), 404
            conn.execute(
                """
                INSERT INTO collection_papers (
                    collection_id, identity_key, match_source, match_score, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(collection_id, identity_key) DO UPDATE SET
                    match_source = excluded.match_source,
                    match_score = excluded.match_score,
                    note = excluded.note
                """,
                (
                    collection_id,
                    identity_key,
                    str(data.get("match_source") or "manual").strip() or "manual",
                    float(data.get("match_score") or 1.0),
                    str(data.get("note") or "").strip(),
                    now,
                ),
            )
            conn.execute(
                "UPDATE library_collections SET updated_at = ? WHERE collection_id = ?",
                (now, collection_id),
            )
            conn.commit()
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": f"加入主题库失败: {exc}"}), 500


@app.route('/api/library/collections/<collection_id>/papers/bulk', methods=['POST'])
def add_papers_to_collection(collection_id):
    data = request.get_json(silent=True) or {}
    identity_keys = normalize_identity_keys(data.get("identity_keys"))
    if not identity_keys:
        return jsonify({"error": "缺少要加入的文献"}), 400
    now = datetime.now().isoformat(timespec="seconds")
    try:
        with connect_literature_library() as conn:
            collection = conn.execute(
                "SELECT collection_id FROM library_collections WHERE collection_id = ?",
                (collection_id,),
            ).fetchone()
            if collection is None:
                return jsonify({"error": "文献主题库不存在"}), 404
            placeholders = ", ".join("?" for _ in identity_keys)
            existing_rows = conn.execute(
                f"SELECT identity_key FROM papers WHERE identity_key IN ({placeholders})",
                identity_keys,
            ).fetchall()
            existing_keys = [row["identity_key"] for row in existing_rows]
            existing_members = {
                row["identity_key"]
                for row in conn.execute(
                    f"""
                    SELECT identity_key FROM collection_papers
                    WHERE collection_id = ? AND identity_key IN ({placeholders})
                    """,
                    [collection_id, *identity_keys],
                ).fetchall()
            }
            added = 0
            updated = 0
            for identity_key in existing_keys:
                conn.execute(
                    """
                    INSERT INTO collection_papers (
                        collection_id, identity_key, match_source, match_score, note, created_at
                    ) VALUES (?, ?, 'manual', 1.0, '', ?)
                    ON CONFLICT(collection_id, identity_key) DO UPDATE SET
                        match_source = excluded.match_source,
                        match_score = excluded.match_score
                    """,
                    (collection_id, identity_key, now),
                )
                if identity_key in existing_members:
                    updated += 1
                else:
                    added += 1
            conn.execute(
                "UPDATE library_collections SET updated_at = ? WHERE collection_id = ?",
                (now, collection_id),
            )
            conn.commit()
        return jsonify({"requested": len(identity_keys), "matched": len(existing_keys), "added": added, "updated": updated})
    except Exception as exc:
        return jsonify({"error": f"批量加入文献主题库失败: {exc}"}), 500


@app.route('/api/library/collections/<collection_id>/papers/<path:identity_key>', methods=['DELETE'])
def remove_paper_from_collection(collection_id, identity_key):
    if not library_exists():
        return jsonify({"error": "文献库尚未创建"}), 404
    try:
        with connect_literature_library() as conn:
            cursor = conn.execute(
                "DELETE FROM collection_papers WHERE collection_id = ? AND identity_key = ?",
                (collection_id, identity_key),
            )
            conn.execute(
                "UPDATE library_collections SET updated_at = ? WHERE collection_id = ?",
                (datetime.now().isoformat(timespec="seconds"), collection_id),
            )
            conn.commit()
        return jsonify({"removed": cursor.rowcount})
    except Exception as exc:
        return jsonify({"error": f"移除文献失败: {exc}"}), 500


@app.route('/api/library/collections/<collection_id>/papers/delete', methods=['POST'])
def remove_papers_from_collection(collection_id):
    data = request.get_json(silent=True) or {}
    identity_keys = normalize_identity_keys(data.get("identity_keys"))
    if not identity_keys:
        return jsonify({"error": "缺少要移除的文献"}), 400
    try:
        with connect_literature_library() as conn:
            removed = 0
            for identity_key in identity_keys:
                cursor = conn.execute(
                    "DELETE FROM collection_papers WHERE collection_id = ? AND identity_key = ?",
                    (collection_id, identity_key),
                )
                removed += cursor.rowcount
            conn.execute(
                "UPDATE library_collections SET updated_at = ? WHERE collection_id = ?",
                (datetime.now().isoformat(timespec="seconds"), collection_id),
            )
            conn.commit()
        return jsonify({"removed": removed})
    except Exception as exc:
        return jsonify({"error": f"批量移除文献失败: {exc}"}), 500


@app.route('/api/library/collections/<collection_id>/classify', methods=['POST'])
def classify_collection_papers(collection_id):
    if not library_exists():
        return jsonify({"error": "文献库尚未创建"}), 404
    now = datetime.now().isoformat(timespec="seconds")
    try:
        with connect_literature_library() as conn:
            collection = conn.execute(
                "SELECT * FROM library_collections WHERE collection_id = ?",
                (collection_id,),
            ).fetchone()
            if collection is None:
                return jsonify({"error": "主题库不存在"}), 404
            rules = collection_row_to_dict(collection).get("rules", {})
            if not rules.get("include_keywords"):
                return jsonify({"error": "请先为主题库配置包含关键词"}), 400
            rows = conn.execute(
                """
                SELECT identity_key, title, authors, abstract, venue, doi, query
                FROM papers
                """
            ).fetchall()
            added = 0
            matched = 0
            for row in rows:
                is_match, score = paper_matches_collection_rules(row, rules)
                if not is_match:
                    continue
                matched += 1
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO collection_papers (
                        collection_id, identity_key, match_source, match_score, note, created_at
                    ) VALUES (?, ?, 'rule', ?, '', ?)
                    """,
                    (collection_id, row["identity_key"], score, now),
                )
                added += cursor.rowcount
            conn.execute(
                "UPDATE library_collections SET updated_at = ? WHERE collection_id = ?",
                (now, collection_id),
            )
            conn.commit()
        return jsonify({"matched": matched, "added": added})
    except Exception as exc:
        return jsonify({"error": f"自动归类失败: {exc}"}), 500


@app.route('/api/library/papers/<path:identity_key>', methods=['DELETE'])
def delete_library_paper(identity_key):
    if not library_exists():
        return jsonify({"error": "文献库尚未创建"}), 404
    try:
        with connect_literature_library() as conn:
            deleted = delete_library_papers_by_keys(conn, [identity_key])
            conn.commit()
        if deleted <= 0:
            return jsonify({"error": "文献不存在"}), 404
        return jsonify({"deleted": deleted})
    except Exception as exc:
        return jsonify({"error": f"删除文献失败: {exc}"}), 500


@app.route('/api/library/papers/delete', methods=['POST'])
def delete_library_papers():
    if not library_exists():
        return jsonify({"error": "文献库尚未创建"}), 404
    data = request.get_json(silent=True) or {}
    identity_keys = normalize_identity_keys(data.get("identity_keys"))
    if not identity_keys:
        return jsonify({"error": "缺少要删除的文献"}), 400
    try:
        with connect_literature_library() as conn:
            deleted = delete_library_papers_by_keys(conn, identity_keys)
            conn.commit()
        return jsonify({"deleted": deleted})
    except Exception as exc:
        return jsonify({"error": f"批量删除文献失败: {exc}"}), 500


@app.route('/api/library/papers/<path:identity_key>/download_pdf', methods=['POST'])
def download_library_pdf(identity_key):
    return jsonify({"error": "PDF 自动下载已关闭，请使用上传 PDF。"}), 410


@app.route('/api/library/papers/<path:identity_key>/upload_pdf', methods=['POST'])
def upload_library_pdf(identity_key):
    if pdf_fetcher is None or pdf_store is None:
        return jsonify({"error": "PDF 文档模块不可用"}), 500
    if not library_exists():
        return jsonify({"error": "文献库尚未创建"}), 404

    uploaded_file = request.files.get("file")
    if not uploaded_file or not uploaded_file.filename:
        return jsonify({"error": "缺少 PDF 文件"}), 400
    original_name = secure_filename(uploaded_file.filename)
    if not original_name.lower().endswith(".pdf"):
        return jsonify({"error": "只支持 PDF 文件"}), 400

    with connect_literature_library() as conn:
        paper = pdf_store.get_paper(conn, identity_key)
        if paper is None:
            return jsonify({"error": "未找到该文献"}), 404
        try:
            name = pdf_fetcher.safe_filename_part(identity_key.replace(":", "_"))
            result = pdf_fetcher.save_uploaded_pdf(
                uploaded_file,
                PDF_CACHE_DIR,
                filename_prefix=name,
                original_filename=original_name,
            )
            relative_path = pdf_store.relative_to_project(result.path, PROJECT_DIR)
            state = pdf_store.mark_downloaded(
                conn,
                identity_key=identity_key,
                doi=paper["doi"] or "",
                pdf_url=paper["pdf_url"] or "",
                pdf_path=relative_path,
                pdf_source=pdf_store.PDF_SOURCE_UPLOAD,
            )
            conn.commit()
            return jsonify({"document": state, "size_bytes": result.size_bytes})
        except Exception as exc:
            state = pdf_store.mark_failed(
                conn,
                identity_key=identity_key,
                doi=paper["doi"] or "",
                pdf_url=paper["pdf_url"] or "",
                error=str(exc),
            )
            conn.commit()
            return jsonify({"error": state["download_error"], "document": state}), 400


@app.route('/api/library/papers/<path:identity_key>/pdf')
def view_library_pdf(identity_key):
    if pdf_store is None:
        return jsonify({"error": "PDF 文档模块不可用"}), 500
    if not library_exists():
        return jsonify({"error": "文献库尚未创建"}), 404

    with connect_literature_library() as conn:
        document = pdf_store.get_document(conn, identity_key)
    if not document or document["download_status"] != "downloaded" or not document["pdf_path"]:
        return jsonify({"error": "该文献还没有可查看的 PDF"}), 404

    pdf_path = pdf_store.resolve_pdf_path(document["pdf_path"], PROJECT_DIR).resolve()
    if not path_is_under_any(pdf_path, [PDF_CACHE_DIR, LEGACY_PDF_CACHE_DIR]):
        return jsonify({"error": "PDF 路径不在缓存目录内"}), 403
    if not pdf_path.exists():
        with connect_literature_library() as conn:
            paper = pdf_store.get_paper(conn, identity_key)
            pdf_store.mark_not_downloaded(
                conn,
                identity_key=identity_key,
                doi=(paper["doi"] if paper else "") or "",
                pdf_url=(paper["pdf_url"] if paper else "") or "",
            )
            conn.commit()
        return jsonify({"error": "PDF 文件不存在，请重新上传"}), 404
    return send_file(pdf_path, mimetype="application/pdf", as_attachment=False)


@app.route('/api/library/papers/<path:identity_key>/parse_pdf', methods=['POST'])
def parse_library_pdf(identity_key):
    if pdf_store is None or marker_parser is None or chunker is None:
        return jsonify({"error": "Marker 解析模块不可用"}), 500
    if not library_exists():
        return jsonify({"error": "文献库尚未创建"}), 404

    with connect_literature_library() as conn:
        paper = pdf_store.get_paper(conn, identity_key)
        if paper is None:
            return jsonify({"error": "未找到该文献"}), 404
        force = str(request.args.get("force") or "").strip().lower() in {"1", "true", "yes", "on"}
        existing_fulltext = pdf_store.get_fulltext(conn, identity_key)
        existing_chunk_count = pdf_store.count_chunks(conn, identity_key)
        if (
            not force
            and existing_fulltext
            and str(existing_fulltext["parse_engine"] or "").startswith("marker")
            and (existing_fulltext["full_text"] or "").strip()
            and existing_chunk_count > 0
        ):
            state = pdf_store.mark_cached_parse_valid(conn, identity_key)
            conn.commit()
            return jsonify({
                "fulltext": state,
                "chunks": pdf_store.list_chunks(conn, identity_key, limit=5),
                "cached": True,
            })
        document = pdf_store.get_document(conn, identity_key)
        if not document or document["download_status"] != "downloaded" or not document["pdf_path"]:
            state = pdf_store.mark_parse_failed(
                conn,
                identity_key=identity_key,
                error="请先上传 PDF",
                parse_engine="marker",
            )
            conn.commit()
            return jsonify({"error": state["parse_error"], "fulltext": state}), 400

        pdf_path = pdf_store.resolve_pdf_path(document["pdf_path"], PROJECT_DIR).resolve()
        if not path_is_under_any(pdf_path, [PDF_CACHE_DIR, LEGACY_PDF_CACHE_DIR]):
            state = pdf_store.mark_parse_failed(
                conn,
                identity_key=identity_key,
                error="PDF 路径不在缓存目录内",
                parse_engine="marker",
            )
            conn.commit()
            return jsonify({"error": state["parse_error"], "fulltext": state}), 403
        if not pdf_path.exists():
            pdf_store.mark_not_downloaded(
                conn,
                identity_key=identity_key,
                doi=paper["doi"] or "",
                pdf_url=paper["pdf_url"] or "",
            )
            state = pdf_store.mark_parse_failed(
                conn,
                identity_key=identity_key,
                error="PDF 文件不存在，请重新上传",
                parse_engine="marker",
            )
            conn.commit()
            return jsonify({"error": state["parse_error"], "fulltext": state}), 404

        try:
            output_name = pdf_fetcher.safe_filename_part(identity_key.replace(":", "_"), "paper")
            marker_output_dir = MARKER_OUTPUT_DIR / output_name
            if str(os.getenv("MARKER_SKIP_PREFLIGHT") or "").strip().lower() not in {"1", "true", "yes", "on"}:
                preflight_timeout = int(os.getenv("MARKER_PREFLIGHT_TIMEOUT_SECONDS", "180"))
                marker_parser.preflight_marker(
                    pdf_path,
                    marker_output_dir,
                    timeout_seconds=preflight_timeout,
                )
            marker_timeout = int(os.getenv("MARKER_TIMEOUT_SECONDS", "1800"))
            parsed = marker_parser.parse_pdf_to_markdown(
                pdf_path,
                marker_output_dir,
                timeout_seconds=marker_timeout,
            )
            pages = page_extractor.extract_pdf_pages(pdf_path) if page_extractor is not None else []
            chunks = chunker.chunk_markdown_with_pages(parsed.markdown_text, pages)
            quality_result = parse_quality.evaluate_parse_quality(
                markdown_text=parsed.markdown_text,
                chunks=chunks,
                pages=pages,
            ) if parse_quality is not None else None
            relative_markdown_path = pdf_store.relative_to_project(parsed.markdown_path, PROJECT_DIR)
            parsed_page_count = int(getattr(parsed, "page_count", 0) or 0)
            if not parsed_page_count and pages:
                parsed_page_count = len(pages)
            if not parsed_page_count and existing_fulltext:
                parsed_page_count = int(existing_fulltext["page_count"] or 0)
            state = pdf_store.replace_parse_result(
                conn,
                identity_key=identity_key,
                full_text=parsed.markdown_text,
                markdown_text=parsed.markdown_text,
                markdown_path=relative_markdown_path,
                parse_engine=getattr(parsed, "engine", "marker") or "marker",
                page_count=parsed_page_count,
                chunks=chunks,
                parse_quality=(quality_result.parse_quality if quality_result else "warning"),
                page_mapping_coverage=(quality_result.page_mapping_coverage if quality_result else 0.0),
                text_length=(quality_result.text_length if quality_result else len(parsed.markdown_text or "")),
                quality_warnings_json=json.dumps((quality_result.quality_warnings if quality_result else []), ensure_ascii=False),
            )
            conn.commit()
            return jsonify({"fulltext": state, "chunks": pdf_store.list_chunks(conn, identity_key, limit=5)})
        except Exception as exc:
            state = pdf_store.mark_parse_failed(
                conn,
                identity_key=identity_key,
                error=str(exc),
                parse_engine="marker",
            )
            conn.commit()
            return jsonify({"error": state["parse_error"], "fulltext": state}), 400


@app.route('/api/library/papers/<path:identity_key>/chunks')
def library_pdf_chunks(identity_key):
    if pdf_store is None:
        return jsonify({"error": "PDF 解析模块不可用"}), 500
    if not library_exists():
        return jsonify({"error": "文献库尚未创建"}), 404

    limit = min(100, max(1, int(request.args.get("limit", 20))))
    try:
        with connect_literature_library() as conn:
            paper = pdf_store.get_paper(conn, identity_key)
            if paper is None:
                return jsonify({"error": "未找到该文献"}), 404
            fulltext = pdf_store.get_fulltext(conn, identity_key)
            chunks = pdf_store.list_chunks(conn, identity_key, limit=limit)
            chunk_count = pdf_store.count_chunks(conn, identity_key)
        status = dict(fulltext) if fulltext else {
            "identity_key": identity_key,
            "full_text": "",
            "parse_engine": "",
            "markdown_path": "",
            "parse_status": "not_parsed",
            "parse_error": "",
            "page_count": 0,
            "parsed_at": "",
            "parse_quality": "",
            "page_mapping_coverage": 0,
            "text_length": 0,
            "quality_warnings_json": "[]",
        }
        quality = parse_quality_payload(status)
        status.update(quality)
        status["quality_warning_summary"] = summarize_quality_warnings(status.get("quality_warnings", []))
        status["chunk_count"] = chunk_count
        status.pop("full_text", None)
        status.pop("quality_warnings_json", None)
        return jsonify({"fulltext": status, "chunks": chunks})
    except Exception as exc:
        return jsonify({"error": f"读取全文片段失败: {exc}"}), 500


def build_library_fulltext_response(identity_key: str, paper, fulltext, chunk_count: int):
    quality = parse_quality_payload(fulltext)
    response = jsonify({
        "identity_key": identity_key,
        "title": paper["title"] or "未命名文献",
        "authors": paper["authors"] or "",
        "doi": paper["doi"] or "",
        "venue": paper["venue"] or "",
        "publicationDate": paper["publicationDate"] or paper["year"] or "",
        "parse_status": fulltext["parse_status"],
        "parse_error": fulltext["parse_error"] or "",
        "parse_engine": fulltext["parse_engine"] or CURRENT_PARSE_ENGINE,
        "markdown_path": fulltext["markdown_path"] or "",
        "page_count": int(fulltext["page_count"] or 0),
        "parsed_at": fulltext["parsed_at"] or "",
        "chunk_count": chunk_count,
        "char_count": len((fulltext["markdown_text"] or fulltext["full_text"] or "")),
        "full_text": fulltext["markdown_text"] or fulltext["full_text"] or "",
        "parse_quality": quality["parse_quality"],
        "page_mapping_coverage": quality["page_mapping_coverage"],
        "text_length": quality["text_length"],
        "quality_warnings": quality["quality_warnings"],
        "quality_warning_summary": summarize_quality_warnings(quality["quality_warnings"]),
    })
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


@app.route('/api/library/papers/<path:identity_key>/parse_quality')
def library_parse_quality(identity_key):
    if pdf_store is None:
        return jsonify({"error": "PDF 解析模块不可用"}), 500
    if not library_exists():
        return jsonify({"error": "文献库尚未创建"}), 404

    try:
        with connect_literature_library() as conn:
            paper = pdf_store.get_paper(conn, identity_key)
            if paper is None:
                return jsonify({"error": "未找到该文献"}), 404
            fulltext = pdf_store.get_fulltext(conn, identity_key)
            if fulltext is None:
                return jsonify({
                    "identity_key": identity_key,
                    "parse_status": "not_parsed",
                    "parse_quality": "",
                    "page_mapping_coverage": 0.0,
                    "text_length": 0,
                    "quality_warnings": [],
                    "quality_warning_summary": "",
                })
            payload = parse_quality_payload(fulltext)
            payload.update({
                "identity_key": identity_key,
                "parse_status": fulltext["parse_status"],
                "page_count": int(fulltext["page_count"] or 0),
                "parsed_at": fulltext["parsed_at"] or "",
                "quality_warning_summary": summarize_quality_warnings(payload.get("quality_warnings", [])),
            })
            return jsonify(payload)
    except Exception as exc:
        return jsonify({"error": f"读取解析质量失败: {exc}"}), 500


@app.route('/api/library/papers/<path:identity_key>/fulltext')
def library_pdf_fulltext(identity_key):
    if pdf_store is None:
        return jsonify({"error": "PDF 解析模块不可用"}), 500
    if not library_exists():
        return jsonify({"error": "文献库尚未创建"}), 404

    try:
        with connect_literature_library() as conn:
            paper = conn.execute(
                """
                SELECT identity_key, title, authors, doi, venue, publicationDate, year
                FROM papers
                WHERE identity_key = ?
                """,
                (identity_key,),
            ).fetchone()
            if paper is None:
                return jsonify({"error": "未找到该文献"}), 404
            fulltext = pdf_store.get_fulltext(conn, identity_key)
            if fulltext is None or not (fulltext["full_text"] or "").strip():
                return jsonify({"error": "该文献还没有解析好的全文，请先点击解析全文"}), 404
            if fulltext["parse_status"] != "parsed":
                return jsonify({"error": fulltext["parse_error"] or "全文解析未完成"}), 400
            chunk_count = pdf_store.count_chunks(conn, identity_key)
        return build_library_fulltext_response(identity_key, paper, fulltext, chunk_count)
    except Exception as exc:
        return jsonify({"error": f"读取全文失败: {exc}"}), 500


@app.route('/library/papers/<path:identity_key>/fulltext_view')
def library_pdf_fulltext_view(identity_key):
    return render_template("fulltext_view.html", identity_key=identity_key)


@app.route('/api/library/papers/<path:identity_key>/fulltext', methods=['POST'])
def update_library_pdf_fulltext(identity_key):
    if pdf_store is None or chunker is None:
        return jsonify({"error": "PDF 解析模块不可用"}), 500
    if not library_exists():
        return jsonify({"error": "文献库尚未创建"}), 404

    payload = request.get_json(silent=True) or {}
    markdown_text = payload.get("full_text", "")
    if not isinstance(markdown_text, str):
        return jsonify({"error": "Markdown 内容格式不正确"}), 400
    markdown_text = markdown_text.replace("\r\n", "\n").replace("\r", "\n")
    if not markdown_text.strip():
        return jsonify({"error": "Markdown 内容不能为空"}), 400

    try:
        with connect_literature_library() as conn:
            paper = conn.execute(
                """
                SELECT identity_key, title, authors, doi, venue, publicationDate, year
                FROM papers
                WHERE identity_key = ?
                """,
                (identity_key,),
            ).fetchone()
            if paper is None:
                return jsonify({"error": "未找到该文献"}), 404
            fulltext = pdf_store.get_fulltext(conn, identity_key)
            if fulltext is None or fulltext["parse_status"] != "parsed":
                return jsonify({"error": "该文献还没有解析好的全文，请先点击解析全文"}), 404

            markdown_text = marker_parser.normalize_marker_math(markdown_text)
            markdown_path_value = (fulltext["markdown_path"] or "").strip()
            if markdown_path_value:
                markdown_path = resolve_path_from_input(markdown_path_value).resolve()
                marker_roots = [MARKER_OUTPUT_DIR.resolve(), LEGACY_MARKER_OUTPUT_DIR.resolve()]
                if path_is_under_any(markdown_path, marker_roots):
                    markdown_path.write_text(markdown_text.strip() + "\n", encoding="utf-8")

            pages = []
            document = pdf_store.get_document(conn, identity_key)
            if page_extractor is not None and document and document["download_status"] == "downloaded" and document["pdf_path"]:
                try:
                    pdf_path = pdf_store.resolve_pdf_path(document["pdf_path"], PROJECT_DIR).resolve()
                    if path_is_under_any(pdf_path, [PDF_CACHE_DIR, LEGACY_PDF_CACHE_DIR]) and pdf_path.exists():
                        pages = page_extractor.extract_pdf_pages(pdf_path)
                except Exception:
                    pages = []
            chunks = chunker.chunk_markdown_with_pages(markdown_text, pages) if pages else chunker.chunk_markdown(markdown_text)
            quality_result = parse_quality.evaluate_parse_quality(
                markdown_text=markdown_text,
                chunks=chunks,
                pages=pages,
            ) if parse_quality is not None else None
            pdf_store.update_fulltext_content(
                conn,
                identity_key=identity_key,
                markdown_text=markdown_text.strip(),
                page_count=int(fulltext["page_count"] or len(pages) or 0),
                chunks=chunks,
                markdown_path=markdown_path_value,
                parse_engine=(fulltext["parse_engine"] or CURRENT_PARSE_ENGINE),
                parse_quality=(quality_result.parse_quality if quality_result else "warning"),
                page_mapping_coverage=(quality_result.page_mapping_coverage if quality_result else 0.0),
                text_length=(quality_result.text_length if quality_result else len(markdown_text.strip())),
                quality_warnings_json=json.dumps((quality_result.quality_warnings if quality_result else []), ensure_ascii=False),
            )
            conn.commit()
            saved_fulltext = pdf_store.get_fulltext(conn, identity_key)
            chunk_count = pdf_store.count_chunks(conn, identity_key)
        return build_library_fulltext_response(identity_key, paper, saved_fulltext, chunk_count)
    except Exception as exc:
        return jsonify({"error": f"保存全文失败: {exc}"}), 500


@app.route('/api/library/papers/<path:identity_key>/fulltext_asset')
def library_pdf_fulltext_asset(identity_key):
    if pdf_store is None:
        return jsonify({"error": "PDF 解析模块不可用"}), 500
    if not library_exists():
        return jsonify({"error": "文献库尚未创建"}), 404

    asset_value = (request.args.get("path") or "").strip()
    if not asset_value:
        return jsonify({"error": "缺少资源路径"}), 400
    raw_asset_path = Path(asset_value)
    if raw_asset_path.is_absolute():
        return jsonify({"error": "资源路径不合法"}), 400

    try:
        with connect_literature_library() as conn:
            paper = pdf_store.get_paper(conn, identity_key)
            if paper is None:
                return jsonify({"error": "未找到该文献"}), 404
            fulltext = pdf_store.get_fulltext(conn, identity_key)
            if fulltext is None or fulltext["parse_status"] != "parsed":
                return jsonify({"error": "该文献还没有解析好的 Markdown"}), 404
            markdown_path_value = (fulltext["markdown_path"] or "").strip()
            if not markdown_path_value:
                return jsonify({"error": "缺少 Markdown 文件路径"}), 404

        markdown_path = resolve_path_from_input(markdown_path_value).resolve()
        marker_roots = [MARKER_OUTPUT_DIR.resolve(), LEGACY_MARKER_OUTPUT_DIR.resolve()]
        if not path_is_under_any(markdown_path, marker_roots):
            return jsonify({"error": "Markdown 路径不在 Marker 缓存目录内"}), 403
        markdown_dir = markdown_path.parent
        asset_path = (markdown_dir / raw_asset_path).resolve()
        if not path_is_under_any(asset_path, [markdown_dir]):
            return jsonify({"error": "资源路径不合法"}), 403
        if not asset_path.is_file():
            return jsonify({"error": "资源文件不存在"}), 404
        return send_file(asset_path)
    except Exception as exc:
        return jsonify({"error": f"读取 Markdown 资源失败: {exc}"}), 500


def delete_library_md_cache(identity_key):
    if pdf_store is None:
        return {"error": "PDF 解析模块不可用"}, 500
    if not library_exists():
        return {"error": "文献库尚未创建"}, 404

    with connect_literature_library() as conn:
        paper = pdf_store.get_paper(conn, identity_key)
        if paper is None:
            return {"error": "未找到该文献"}, 404
        fulltext = pdf_store.get_fulltext(conn, identity_key)
        deleted_files = 0
        delete_error = ""
        markdown_path_value = (fulltext["markdown_path"] if fulltext else "") or ""
        if markdown_path_value:
            markdown_path = resolve_path_from_input(markdown_path_value).resolve()
            parser_roots = [
                MARKER_OUTPUT_DIR.resolve(),
                LEGACY_MARKER_OUTPUT_DIR.resolve(),
            ]
            parser_root = next(
                (root for root in parser_roots if markdown_path == root or root in markdown_path.parents),
                None,
            )
            if parser_root is not None:
                candidate_dir = markdown_path.parent
                if candidate_dir.exists() and candidate_dir != parser_root and parser_root in candidate_dir.parents:
                    try:
                        shutil.rmtree(candidate_dir)
                        deleted_files = 1
                    except Exception as exc:
                        delete_error = str(exc)
                elif markdown_path.exists():
                    try:
                        markdown_path.unlink()
                        deleted_files = 1
                    except Exception as exc:
                        delete_error = str(exc)
            else:
                delete_error = "Markdown 路径不在解析缓存目录内，已仅清理数据库缓存。"
        state = pdf_store.mark_not_parsed(conn, identity_key=identity_key)
        conn.commit()
    return {"fulltext": state, "deleted_files": deleted_files, "delete_error": delete_error}, 200


@app.route('/api/library/papers/<path:identity_key>/delete_md', methods=['POST'])
def delete_library_md_post(identity_key):
    payload, status = delete_library_md_cache(identity_key)
    return jsonify(payload), status


@app.route('/api/library/papers/<path:identity_key>/md', methods=['DELETE'])
def delete_library_md(identity_key):
    payload, status = delete_library_md_cache(identity_key)
    return jsonify(payload), status


def delete_library_pdf_file(identity_key):
    if pdf_store is None:
        return {"error": "PDF 文档模块不可用"}, 500
    if not library_exists():
        return {"error": "文献库尚未创建"}, 404

    with connect_literature_library() as conn:
        paper = pdf_store.get_paper(conn, identity_key)
        if paper is None:
            return {"error": "未找到该文献"}, 404
        document = pdf_store.get_document(conn, identity_key)
        deleted_file = False
        delete_error = ""
        if document and document["pdf_path"]:
            pdf_path = pdf_store.resolve_pdf_path(document["pdf_path"], PROJECT_DIR).resolve()
            if path_is_under_any(pdf_path, [PDF_CACHE_DIR, LEGACY_PDF_CACHE_DIR]):
                if pdf_path.exists():
                    try:
                        pdf_path.unlink()
                        deleted_file = True
                    except Exception as exc:
                        delete_error = str(exc)
            else:
                delete_error = "PDF 路径不在缓存目录内，已仅重置数据库状态。"
        state = pdf_store.mark_not_downloaded(
            conn,
            identity_key=identity_key,
            doi=paper["doi"] or "",
            pdf_url=paper["pdf_url"] or "",
        )
        conn.commit()
    return {"document": state, "deleted_file": deleted_file, "delete_error": delete_error}, 200


@app.route('/api/library/papers/<path:identity_key>/delete_pdf', methods=['POST'])
def delete_library_pdf_post(identity_key):
    payload, status = delete_library_pdf_file(identity_key)
    return jsonify(payload), status


@app.route('/api/library/papers/<path:identity_key>/pdf', methods=['DELETE'])
def delete_library_pdf(identity_key):
    payload, status = delete_library_pdf_file(identity_key)
    return jsonify(payload), status


@app.route('/api/trends/topics')
def list_trend_topics():
    summary_map = get_topic_summary_map(**trend_filter_params_from_request())
    topics = sorted(
        [
            {
                "key": topic_key,
                "label": summary.get("topic_label") or topic_label_from_key(topic_key),
                "entry_count": summary.get("entry_count", 0),
                "total_papers": summary.get("total_papers", 0),
                "date_range": summary.get("date_range", {}),
            }
            for topic_key, summary in summary_map.items()
        ],
        key=lambda item: (item["date_range"].get("end", ""), item["entry_count"]),
        reverse=True,
    )
    return jsonify({"topics": topics})


@app.route('/api/trends')
def topic_trend():
    topic_key = request.args.get("topic", "").strip()
    summary_map = get_topic_summary_map(**trend_filter_params_from_request())
    if not topic_key and summary_map:
        topic_key = sorted(
            summary_map,
            key=lambda key: (summary_map[key].get("date_range", {}).get("end", ""), summary_map[key].get("entry_count", 0)),
            reverse=True,
        )[0]
    if not topic_key or topic_key not in summary_map:
        return jsonify({"error": "Trend topic not found"}), 404
    return jsonify(summary_map[topic_key])


@app.route('/api/trends/compare')
def compare_topic_trends():
    topic_a = request.args.get("topic_a", "").strip()
    topic_b = request.args.get("topic_b", "").strip()
    summary_map = get_topic_summary_map(**trend_filter_params_from_request())
    if topic_a not in summary_map or topic_b not in summary_map:
        return jsonify({"error": "Trend topic not found"}), 404

    summary_a = summary_map[topic_a]
    summary_b = summary_map[topic_b]
    keyword_items_a = {item["term"]: item for item in summary_a.get("top_keywords", [])}
    keyword_items_b = {item["term"]: item for item in summary_b.get("top_keywords", [])}
    keywords_a = {term: item["count"] for term, item in keyword_items_a.items()}
    keywords_b = {term: item["count"] for term, item in keyword_items_b.items()}
    author_items_a = {item["term"]: item for item in summary_a.get("top_authors", [])}
    author_items_b = {item["term"]: item for item in summary_b.get("top_authors", [])}
    institution_items_a = {item["term"]: item for item in summary_a.get("top_institutions", [])}
    institution_items_b = {item["term"]: item for item in summary_b.get("top_institutions", [])}
    authors_a = {term: item["count"] for term, item in author_items_a.items()}
    authors_b = {term: item["count"] for term, item in author_items_b.items()}
    institutions_a = {term: item["count"] for term, item in institution_items_a.items()}
    institutions_b = {term: item["count"] for term, item in institution_items_b.items()}
    common_terms = sorted(
        set(keywords_a) & set(keywords_b),
        key=lambda term: keywords_a[term] + keywords_b[term],
        reverse=True,
    )[:10]
    common_authors = sorted(
        set(authors_a) & set(authors_b),
        key=lambda term: authors_a[term] + authors_b[term],
        reverse=True,
    )[:10]
    common_institutions = sorted(
        set(institutions_a) & set(institutions_b),
        key=lambda term: institutions_a[term] + institutions_b[term],
        reverse=True,
    )[:10]
    unique_a = sorted(
        set(keywords_a) - set(keywords_b),
        key=lambda term: keywords_a[term],
        reverse=True,
    )[:10]
    unique_b = sorted(
        set(keywords_b) - set(keywords_a),
        key=lambda term: keywords_b[term],
        reverse=True,
    )[:10]

    return jsonify({
        "topic_a": summary_a,
        "topic_b": summary_b,
        "common_keywords": [
            {
                "term": term,
                "count_a": int(keywords_a[term]),
                "count_b": int(keywords_b[term]),
                "evidence": (keyword_items_a[term].get("evidence", []) + keyword_items_b[term].get("evidence", []))[:5],
            }
            for term in common_terms
        ],
        "common_authors": [
            {
                "term": term,
                "count_a": int(authors_a[term]),
                "count_b": int(authors_b[term]),
                "evidence": (author_items_a[term].get("evidence", []) + author_items_b[term].get("evidence", []))[:5],
            }
            for term in common_authors
        ],
        "common_institutions": [
            {
                "term": term,
                "count_a": int(institutions_a[term]),
                "count_b": int(institutions_b[term]),
                "evidence": (institution_items_a[term].get("evidence", []) + institution_items_b[term].get("evidence", []))[:5],
            }
            for term in common_institutions
        ],
        "unique_a": [
            {**keyword_items_a[term], "count": int(keywords_a[term])}
            for term in unique_a
        ],
        "unique_b": [
            {**keyword_items_b[term], "count": int(keywords_b[term])}
            for term in unique_b
        ],
    })


@app.route('/api/knowledge_graph', methods=['GET', 'POST'])
def knowledge_graph():
    data = request.get_json(silent=True) if request.method == "POST" else None
    source = data or request.args
    try:
        (
            csv_path, max_nodes, max_edges, mode, llm_config, graph_scope,
            input_source, max_chunks_per_paper, graph_source, graph_source_label,
        ) = parse_knowledge_graph_request(source)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        logger.info(
            "开始生成知识图谱: scope=%s source=%s label=%s csv=%s input_source=%s chunks=%s mode=%s max_nodes=%s max_edges=%s provider=%s model=%s",
            graph_scope,
            graph_source,
            graph_source_label,
            csv_path,
            input_source,
            max_chunks_per_paper,
            mode,
            max_nodes,
            max_edges,
            llm_config.get("llm_provider"),
            llm_config.get("model"),
        )
        set_task_debug(
            task_id,
            phase="build_graph",
            builder={
                "csv_name": csv_path.name,
                "csv_parent": str(csv_path.parent),
                "input_source": input_source,
                "mode": mode,
                "max_nodes": max_nodes,
                "max_edges": max_edges,
                "max_chunks_per_paper": max_chunks_per_paper,
            },
        )
        graph = build_knowledge_graph(
            csv_path,
            max_nodes=max_nodes,
            max_edges=max_edges,
            mode=mode,
            llm_config=llm_config,
            graph_scope=graph_scope,
            input_source=input_source,
            max_chunks_per_paper=max_chunks_per_paper,
            graph_source=graph_source,
            graph_source_label=graph_source_label,
        )
        logger.info(
            "知识图谱生成完成: nodes=%s edges=%s triplets=%s llm_enhanced=%s",
            len(graph.get("nodes", [])),
            len(graph.get("edges", [])),
            len(graph.get("triplets", [])),
            graph.get("llm_enhanced"),
        )
        return jsonify(graph)
    except Exception as exc:
        logger.exception("Failed to build knowledge graph")
        return jsonify({"error": f"知识图谱生成失败: {exc}"}), 500


def normalize_graph_scope(value: object) -> str:
    scope = str(value or "topic").strip().lower()
    if scope in {"library", "all", "global", "full"}:
        return "library"
    return "topic"


def normalize_graph_input_source(value: object) -> str:
    source = str(value or "abstract").strip().lower().replace("-", "_").replace("+", "_")
    source = re.sub(r"\s+", "_", source)
    if source in {"chunks", "chunk", "fulltext", "full_text", "fulltext_chunks", "full_text_chunks"}:
        return "chunks"
    if source in {
        "abstract_chunks",
        "summary_chunks",
        "abstract_fulltext",
        "abstract_full_text",
        "abstract_fulltext_chunks",
        "abstract_full_text_chunks",
    }:
        return "abstract_chunks"
    return "abstract"


def normalize_graph_topic_source(value: object) -> str:
    source = str(value or "csv").strip().lower()
    if source in {"collection", "collections", "topic_collection", "library_collection"}:
        return "collection"
    return "csv"


def graph_paper_select_query(where_clause: str) -> str:
    return f"""
        SELECT
            p.identity_key, p.query, p.paperId, p.source, p.title, p.authors, p.abstract, p.year, p.venue,
            p.volume, p.issue, p.publicationDate, p.citationCount, p.doi, p.url, p.pdf_url,
            p.source_ids_json, p.externalIds_json, p.enrichment_sources,
            d.pdf_path, f.markdown_path AS markdown_path
        FROM papers p
        LEFT JOIN paper_documents d ON d.identity_key = p.identity_key
        LEFT JOIN paper_fulltext f ON f.identity_key = p.identity_key
        {where_clause}
    """


def build_library_graph_csv() -> Path:
    if not LITERATURE_LIBRARY_DB.exists():
        raise ValueError("文献库尚未初始化，无法生成全库知识图谱")

    query = graph_paper_select_query(
        """
        WHERE COALESCE(p.title, '') != '' OR COALESCE(p.abstract, '') != ''
        ORDER BY p.last_seen_at DESC
        """
    )
    try:
        with sqlite3.connect(f"file:{LITERATURE_LIBRARY_DB}?mode=ro", uri=True, timeout=2) as conn:
            df = pd.read_sql_query(query, conn)
    except Exception as exc:
        raise ValueError(f"读取文献库失败: {exc}") from exc

    if df.empty:
        raise ValueError("文献库中没有可用于构建知识图谱的文献")

    graph_cache_dir = SEARCH_RESULTS_DIR / "graph_cache"
    graph_cache_dir.mkdir(parents=True, exist_ok=True)
    csv_path = graph_cache_dir / "library_knowledge_graph_source.csv"
    df.to_csv(csv_path, index=False)
    return csv_path


def build_collection_graph_csv(collection_id: str) -> tuple[Path, str]:
    collection_id = str(collection_id or "").strip()
    if not collection_id:
        raise ValueError("请选择一个文献主题库")
    if not LITERATURE_LIBRARY_DB.exists():
        raise ValueError("文献库尚未初始化，无法生成主题库知识图谱")

    try:
        with sqlite3.connect(f"file:{LITERATURE_LIBRARY_DB}?mode=ro", uri=True, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            collection = conn.execute(
                "SELECT collection_id, name FROM library_collections WHERE collection_id = ?",
                (collection_id,),
            ).fetchone()
            if collection is None:
                raise ValueError("文献主题库不存在")
            query = graph_paper_select_query(
                """
                JOIN collection_papers cp ON cp.identity_key = p.identity_key
                WHERE cp.collection_id = ?
                  AND (COALESCE(p.title, '') != '' OR COALESCE(p.abstract, '') != '')
                ORDER BY cp.created_at DESC, p.title ASC
                """
            )
            df = pd.read_sql_query(query, conn, params=(collection_id,))
            collection_name = str(collection["name"] or collection_id)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"读取文献主题库失败: {exc}") from exc

    if df.empty:
        raise ValueError("该文献主题库中没有可用于构建知识图谱的文献")

    graph_cache_dir = SEARCH_RESULTS_DIR / "graph_cache"
    graph_cache_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", collection_name).strip("_") or collection_id
    csv_path = graph_cache_dir / f"collection_{safe_name}_{collection_id}.csv"
    df.to_csv(csv_path, index=False)
    return csv_path, collection_name


def parse_knowledge_graph_request(source) -> tuple[Path, int, int, str, dict, str, str, int, str, str]:
    saved_settings = (
        graph_config_store.load_settings(KNOWLEDGE_GRAPH_CONFIG_PATH)
        if graph_config_store is not None
        else {}
    )

    def configured_value(key, default=""):
        value = source.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            return saved_settings.get(key, default)
        return value

    graph_scope = normalize_graph_scope(source.get("graph_scope", source.get("scope", "topic")))
    graph_source = normalize_graph_topic_source(source.get("topic_source", source.get("graph_source", "csv")))
    graph_source_label = ""
    csv_value = str(source.get("csv", "")).strip()
    if graph_scope == "library":
        csv_path = build_library_graph_csv()
        graph_source = "library"
        graph_source_label = "文献库全量"
    elif graph_source == "collection":
        csv_path, graph_source_label = build_collection_graph_csv(
            str(source.get("collection_id", source.get("graph_collection_id", ""))).strip()
        )
    else:
        if not csv_value:
            raise ValueError("请先选择一个CSV数据集")

        try:
            csv_path = resolve_project_file(csv_value)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

        if not csv_path.exists() or csv_path.suffix.lower() != ".csv":
            raise ValueError("CSV file not found")
        graph_source_label = csv_path.name

    try:
        max_nodes = max(8, min(80, int(source.get("max_nodes", 36))))
        max_edges = max(10, min(200, int(source.get("max_edges", 80))))
        max_chunks_per_paper = max(1, min(20, int(configured_value("max_chunks_per_paper", 20))))
    except ValueError:
        raise ValueError("max_nodes/max_edges/max_chunks_per_paper must be integers")

    mode = str(configured_value("mode", "hybrid")).strip().lower()
    if mode not in {"rule", "hybrid", "llm"}:
        mode = "rule"
    input_source = normalize_graph_input_source(
        configured_value("input_source", source.get("graph_input_source", "abstract"))
    )
    llm_config = {
        "llm_provider": configured_value("llm_provider", "openai_compatible"),
        "llm_base_url": configured_value("llm_base_url", ""),
        "ollama_base_url": configured_value("llm_base_url", source.get("ollama_base_url", "")),
        "llm_api_key": configured_value("llm_api_key", ""),
        "model": configured_value("model", ""),
        "llm_timeout_sec": source.get("llm_timeout_sec", 45),
        "llm_connect_timeout_sec": source.get("llm_connect_timeout_sec", 10),
        "llm_max_workers": source.get("llm_max_workers", 3),
        "llm_max_papers": source.get("llm_max_papers", 30),
        "llm_max_text_units": source.get("llm_max_text_units", source.get("llm_max_papers", 30)),
        "graph_input_source": input_source,
        "max_chunks_per_paper": max_chunks_per_paper,
    }
    return csv_path, max_nodes, max_edges, mode, llm_config, graph_scope, input_source, max_chunks_per_paper, graph_source, graph_source_label


@app.route('/api/knowledge-graph/settings', methods=['GET'])
def get_knowledge_graph_settings():
    if graph_config_store is None:
        return jsonify({"error": "知识图谱配置模块不可用"}), 500
    settings = graph_config_store.load_settings(KNOWLEDGE_GRAPH_CONFIG_PATH)
    return jsonify(graph_config_store.public_settings(settings))


@app.route('/api/knowledge-graph/settings', methods=['POST'])
def save_knowledge_graph_settings():
    if graph_config_store is None:
        return jsonify({"error": "知识图谱配置模块不可用"}), 500
    data = request.get_json(silent=True) or {}
    try:
        settings = graph_config_store.save_settings(KNOWLEDGE_GRAPH_CONFIG_PATH, data)
        return jsonify({
            "message": "知识图谱配置已保存",
            "settings": graph_config_store.public_settings(settings),
        })
    except (TypeError, ValueError) as exc:
        return jsonify({"error": f"配置参数无效: {exc}"}), 400
    except OSError as exc:
        return jsonify({"error": f"保存配置失败: {exc}"}), 500


@app.route('/api/knowledge_graph_task', methods=['POST'])
def knowledge_graph_task():
    data = request.get_json(silent=True) or {}
    try:
        (
            csv_path, max_nodes, max_edges, mode, llm_config, graph_scope,
            input_source, max_chunks_per_paper, graph_source, graph_source_label,
        ) = parse_knowledge_graph_request(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    task_id = f"graph_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def graph_task():
        progress_to_task(
            task_id,
            3,
            f"开始生成{'全库' if graph_scope == 'library' else '主题库'}知识图谱: {relative_project_path(csv_path)}",
        )
        log_to_task(
            task_id,
            f"图谱范围: {graph_scope} · 来源: {graph_source_label or graph_source} · 文本来源: {input_source} · 每篇全文片段上限: {max_chunks_per_paper}",
        )
        log_to_task(
            task_id,
            f"图谱生成模式: {mode} · {llm_config.get('llm_provider')} · {llm_config.get('model') or '未指定模型'}",
        )
        logger.info(
            "开始生成知识图谱: scope=%s source=%s label=%s csv=%s input_source=%s chunks=%s mode=%s max_nodes=%s max_edges=%s provider=%s model=%s",
            graph_scope,
            graph_source,
            graph_source_label,
            csv_path,
            input_source,
            max_chunks_per_paper,
            mode,
            max_nodes,
            max_edges,
            llm_config.get("llm_provider"),
            llm_config.get("model"),
        )
        graph = build_knowledge_graph(
            csv_path,
            max_nodes=max_nodes,
            max_edges=max_edges,
            mode=mode,
            llm_config=llm_config,
            progress_callback=lambda progress, message=None: progress_to_task(task_id, progress, message),
            graph_scope=graph_scope,
            input_source=input_source,
            max_chunks_per_paper=max_chunks_per_paper,
            graph_source=graph_source,
            graph_source_label=graph_source_label,
        )
        progress_to_task(
            task_id,
            100,
            f"知识图谱生成完成: {len(graph.get('nodes', []))} 个节点 · {len(graph.get('edges', []))} 条关系 · {len(graph.get('triplets', []))} 个三元组",
        )
        logger.info(
            "知识图谱生成完成: nodes=%s edges=%s triplets=%s llm_enhanced=%s",
            len(graph.get("nodes", [])),
            len(graph.get("edges", [])),
            len(graph.get("triplets", [])),
            graph.get("llm_enhanced"),
        )
        return graph

    task_manager.add_task(task_id, '知识图谱生成', graph_task)
    return jsonify({'task_id': task_id})


@app.route('/api/upload_csv', methods=['POST'])
def upload_csv():
    uploaded_file = request.files.get("file")
    if not uploaded_file or not uploaded_file.filename:
        return jsonify({'error': 'Missing CSV file'}), 400

    original_name = secure_filename(uploaded_file.filename)
    if not original_name.lower().endswith(".csv"):
        return jsonify({'error': 'Only CSV files are supported'}), 400

    stem = Path(original_name).stem or "uploaded"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_name = f"{stem}_{timestamp}.csv"
    target_path = METADATA_CSV_DIR / target_name
    uploaded_file.save(target_path)

    try:
        pd.read_csv(target_path, nrows=1)
    except Exception as exc:
        target_path.unlink(missing_ok=True)
        return jsonify({'error': f'CSV 文件读取失败: {exc}'}), 400

    return jsonify({
        'csv_path': str(target_path.relative_to(PROJECT_DIR))
    })


@app.route('/api/enrich_csv', methods=['POST'])
def enrich_csv():
    if not multi_source_search:
        return jsonify({'error': 'Multi-source module not available'}), 500

    data = request.get_json(silent=True) or {}
    input_csv = data.get("input_csv", "")
    if not input_csv:
        return jsonify({'error': '请先选择一个CSV文件'}), 400

    try:
        source_csv = resolve_project_file(input_csv)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    if not source_csv.exists() or source_csv.suffix.lower() != ".csv":
        return jsonify({'error': 'CSV file not found'}), 404

    selected_sources = get_selected_sources(data)
    source_credentials = get_source_credentials(data)
    if not selected_sources:
        return jsonify({'error': '请至少选择一个文献数据库'}), 400
    task_id = f"enrich_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def enrich_task():
        log_to_task(task_id, f"开始多源补全: {source_csv}")
        log_to_task(task_id, f"补全文献数据库: {', '.join(selected_sources)}")
        log_database_credential_hints(task_id, selected_sources, source_credentials)
        try:
            result = multi_source_search.enrich_csv_file(
                input_csv=source_csv,
                output_dir=METADATA_DIR,
                selected_sources=selected_sources,
                source_credentials=source_credentials,
                logger=lambda msg: log_to_task(task_id, msg),
                persist_library=False,
            )
            csv_path = result.get("csv_path")
            relative_csv = str(csv_path.relative_to(PROJECT_DIR)) if csv_path else ""
            log_to_task(task_id, f"多源补全完成: {relative_csv}")
            log_to_task(task_id, "补全结果未自动写入文献数据库；请在文献预览中选择「选中入库」或「整份 CSV 入库」。")
            return {
                'status': 'success',
                'csv_path': relative_csv,
                'count': result.get("count", 0),
            }
        except Exception as exc:
            log_to_task(task_id, f"多源补全过程中发生错误: {exc}")
            raise

    task_manager.add_task(task_id, '多源补全', enrich_task)
    return jsonify({'task_id': task_id})


@app.route('/api/select_csv_file', methods=['POST'])
def select_csv_file():
    if os.name == "nt":
        data = request.get_json(silent=True) or {}
        default_dir = resolve_default_dialog_dir(data.get("current_csv", ""), METADATA_CSV_DIR)
        selected = _win_choose_file(
            default_dir,
            "请选择CSV文件",
            "CSV files (*.csv)|*.csv|All files (*.*)|*.*",
        )

        if selected is None:
            return jsonify({'error': '无法打开文件选择框'}), 500
        if selected == "":
            return jsonify({'cancelled': True})

        selected_path = Path(selected).expanduser()
        if selected_path.suffix.lower() != ".csv":
            return jsonify({'error': 'Only CSV files are supported'}), 400
        if not selected_path.exists() or not selected_path.is_file():
            return jsonify({'error': 'File not found'}), 404

        original_name = secure_filename(selected_path.name)
        stem = Path(original_name).stem or "selected"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target_path = METADATA_CSV_DIR / f"{stem}_{timestamp}.csv"
        shutil.copy2(selected_path, target_path)

        try:
            pd.read_csv(target_path, nrows=1)
        except Exception as exc:
            target_path.unlink(missing_ok=True)
            return jsonify({'error': f'CSV 文件读取失败: {exc}'}), 400

        return jsonify({
            'csv_path': str(target_path.relative_to(PROJECT_DIR))
        })

    if sys.platform != "darwin":
        return jsonify({'error': '当前只支持在 macOS 上打开文件选择框'}), 400

    data = request.get_json(silent=True) or {}
    default_dir = resolve_default_dialog_dir(data.get("current_csv", ""), METADATA_CSV_DIR)
    escaped_default_dir = escape_applescript_posix_path(default_dir)

    script = (
        'set selectedFile to choose file '
        f'with prompt "请选择CSV文件" default location POSIX file "{escaped_default_dir}"\n'
        'return POSIX path of selectedFile'
    )

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return jsonify({'error': '文件选择超时'}), 504
    except Exception as exc:
        return jsonify({'error': f'无法打开文件选择框: {exc}'}), 500

    if result.returncode != 0:
        message = (result.stderr or "").strip()
        if "User canceled" in message or result.returncode == 1:
            return jsonify({'cancelled': True})
        return jsonify({'error': message or '文件选择失败'}), 500

    selected_path = Path(result.stdout.strip()).expanduser()
    if selected_path.suffix.lower() != ".csv":
        return jsonify({'error': 'Only CSV files are supported'}), 400
    if not selected_path.exists() or not selected_path.is_file():
        return jsonify({'error': 'File not found'}), 404

    original_name = secure_filename(selected_path.name)
    stem = Path(original_name).stem or "selected"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_path = METADATA_CSV_DIR / f"{stem}_{timestamp}.csv"
    shutil.copy2(selected_path, target_path)

    try:
        pd.read_csv(target_path, nrows=1)
    except Exception as exc:
        target_path.unlink(missing_ok=True)
        return jsonify({'error': f'CSV 文件读取失败: {exc}'}), 400

    return jsonify({
        'csv_path': str(target_path.relative_to(PROJECT_DIR))
    })


def _win_dialog_foreground_script() -> str:
    return (
        "Add-Type -TypeDefinition '"
        "using System; "
        "using System.Runtime.InteropServices; "
        "public static class Win32DialogTools { "
        "public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam); "
        "[DllImport(\"user32.dll\")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam); "
        "[DllImport(\"user32.dll\")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId); "
        "[DllImport(\"user32.dll\")] public static extern bool IsWindowVisible(IntPtr hWnd); "
        "[DllImport(\"user32.dll\")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow); "
        "[DllImport(\"user32.dll\")] public static extern bool SetForegroundWindow(IntPtr hWnd); "
        "[DllImport(\"user32.dll\")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags); "
        "public static readonly IntPtr HWND_TOPMOST = new IntPtr(-1); "
        "public const uint SWP_NOMOVE = 0x0002; "
        "public const uint SWP_NOSIZE = 0x0001; "
        "public const uint SWP_SHOWWINDOW = 0x0040; "
        "public const int SW_SHOWNORMAL = 1; "
        "public static void BringProcessWindowsToFront(uint pid) { "
        "EnumWindows(delegate(IntPtr hWnd, IntPtr lParam) { "
        "uint windowPid; "
        "GetWindowThreadProcessId(hWnd, out windowPid); "
        "if (windowPid == pid && IsWindowVisible(hWnd)) { "
        "ShowWindow(hWnd, SW_SHOWNORMAL); "
        "SetWindowPos(hWnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW); "
        "SetForegroundWindow(hWnd); "
        "} "
        "return true; "
        "}, IntPtr.Zero); "
        "} "
        "}';"
        "$dialogPid = [uint32][System.Diagnostics.Process]::GetCurrentProcess().Id;"
        "$foregroundTimer = New-Object System.Windows.Forms.Timer;"
        "$foregroundTimer.Interval = 200;"
        "$foregroundTimer.Add_Tick({ [Win32DialogTools]::BringProcessWindowsToFront($dialogPid) });"
        "$foregroundTimer.Start();"
    )


def _win_choose_folder(default_path: Path, title: str) -> str | None:
    """Windows 文件夹选择框（通过 PowerShell 调用 Windows.Forms）。
    返回选中路径；取消返回空串；出错返回 None。"""
    default_str = str(default_path).replace("'", "''") if default_path else ""
    title_esc = title.replace("'", "''")
    initial = f"$dlg.SelectedPath = '{default_str}'" if default_str else ""
    foreground_ps = _win_dialog_foreground_script()
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        f"{foreground_ps}"
        "$owner = New-Object System.Windows.Forms.Form;"
        "$owner.TopMost = $true;"
        "$owner.ShowInTaskbar = $false;"
        "$owner.StartPosition = 'CenterScreen';"
        "$owner.Size = New-Object System.Drawing.Size(1,1);"
        "$owner.Opacity = 0.01;"
        "$owner.Show();"
        "[System.Windows.Forms.Application]::DoEvents();"
        "$owner.BringToFront();"
        "$owner.Activate();"
        "[Win32DialogTools]::SetForegroundWindow($owner.Handle) | Out-Null;"
        "$dlg = New-Object System.Windows.Forms.FolderBrowserDialog;"
        f"$dlg.Description = '{title_esc}';"
        "$dlg.ShowNewFolderButton = $true;"
        f"{initial};"
        "try { if ($dlg.ShowDialog($owner) -eq 'OK') { Write-Output $dlg.SelectedPath } }"
        "finally { $foregroundTimer.Dispose(); $owner.Close(); $owner.Dispose() }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-STA", "-NoProfile", "-NonInteractive", "-Command", ps],
            check=False, capture_output=True, text=True, timeout=300,
        )
    except Exception as exc:
        logger.error("Windows 文件夹选择框出错: %s", exc)
        return None
    if result.returncode != 0:
        return None
    selected = result.stdout.strip()
    return selected  # 取消时为空串


def _win_choose_file(default_path: Path, title: str, file_filter: str | None = None) -> str | None:
    """Windows 文件选择框（通过 PowerShell 调用 Windows.Forms）。
    返回选中路径；取消返回空串；出错返回 None。"""
    default_str = str(default_path) if default_path else ""
    title_esc = title.replace("'", "''")
    filter_esc = (file_filter or "Report files (*.md;*.markdown;*.json;*.txt;*.pdf)|*.md;*.markdown;*.json;*.txt;*.pdf|All files (*.*)|*.*").replace("'", "''")
    foreground_ps = _win_dialog_foreground_script()
    init_dir = ""
    init_file = ""
    if default_str:
        p = Path(default_str)
        if p.is_dir():
            init_dir = f"$dlg.InitialDirectory = '{default_str}';"
        else:
            init_dir = f"$dlg.InitialDirectory = '{p.parent}';"
            init_file = f"$dlg.FileName = '{p.name}';"
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        f"{foreground_ps}"
        "$owner = New-Object System.Windows.Forms.Form;"
        "$owner.TopMost = $true;"
        "$owner.ShowInTaskbar = $false;"
        "$owner.StartPosition = 'CenterScreen';"
        "$owner.Size = New-Object System.Drawing.Size(1,1);"
        "$owner.Opacity = 0.01;"
        "$owner.Show();"
        "[System.Windows.Forms.Application]::DoEvents();"
        "$owner.BringToFront();"
        "$owner.Activate();"
        "[Win32DialogTools]::SetForegroundWindow($owner.Handle) | Out-Null;"
        "$dlg = New-Object System.Windows.Forms.OpenFileDialog;"
        f"$dlg.Title = '{title_esc}';"
        "$dlg.Filter = '综述文件 (*.md;*.pdf;*.txt)|*.md;*.pdf;*.txt|所有文件 (*.*)|*.*';"
        f"$dlg.Filter = '{filter_esc}';"
        f"{init_dir}{init_file}"
        "try { if ($dlg.ShowDialog($owner) -eq 'OK') { Write-Output $dlg.FileName } }"
        "finally { $foregroundTimer.Dispose(); $owner.Close(); $owner.Dispose() }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-STA", "-NoProfile", "-NonInteractive", "-Command", ps],
            check=False, capture_output=True, text=True, timeout=300,
        )
    except Exception as exc:
        logger.error("Windows 文件选择框出错: %s", exc)
        return None
    if result.returncode != 0:
        return None
    selected = result.stdout.strip()
    return selected  # 取消时为空串


def _macos_choose_folder(default_path: Path, title: str) -> str | None:
    """macOS 文件夹选择框（osascript）。取消返回空串；出错返回 None。"""
    default_str = escape_applescript_posix_path(default_path) if default_path else ""
    location = f' default location POSIX file "{default_str}"' if default_str else ""
    script = f'set selectedFolder to choose folder with prompt "{title}"{location}\nreturn POSIX path of selectedFolder'
    try:
        result = subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None
    if result.returncode != 0:
        message = (result.stderr or "").strip()
        if "User canceled" in message or result.returncode == 1:
            return ""
        return None
    return result.stdout.strip().rstrip("/")


def _macos_choose_file(default_path: Path, title: str) -> str | None:
    """macOS 文件选择框（osascript）。取消返回空串；出错返回 None。"""
    default_str = escape_applescript_posix_path(default_path) if default_path else ""
    location = f' default location POSIX file "{default_str}"' if default_str else ""
    script = f'set selectedFile to choose file with prompt "{title}"{location}\nreturn POSIX path of selectedFile'
    try:
        result = subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None
    if result.returncode != 0:
        message = (result.stderr or "").strip()
        if "User canceled" in message or result.returncode == 1:
            return ""
        return None
    return result.stdout.strip()


@app.route('/api/select_output_dir', methods=['POST'])
def select_output_dir():
    current_dir = request.get_json(silent=True) or {}
    default_path = resolve_default_dialog_dir(current_dir.get("current_dir", ""), OUTPUTS_DIR)

    if sys.platform == "darwin":
        selected = _macos_choose_folder(default_path, "请选择输出目录")
    elif os.name == "nt":
        selected = _win_choose_folder(default_path, "请选择输出目录")
    else:
        return jsonify({'error': '当前系统不支持文件夹选择框'}), 400

    if selected is None:
        return jsonify({'error': '无法打开文件夹选择框'}), 500
    if selected == "":
        return jsonify({'cancelled': True})
    return jsonify({'output_dir': selected})


@app.route('/api/select_report_file', methods=['POST'])
def select_report_file():
    data = request.get_json(silent=True) or {}
    default_dir = resolve_default_dialog_dir(data.get("current_report", ""), OUTPUTS_DIR)

    if sys.platform == "darwin":
        selected = _macos_choose_file(default_dir, "请选择综述文件")
    elif os.name == "nt":
        selected = _win_choose_file(default_dir, "请选择综述文件")
    else:
        return jsonify({'error': '当前系统不支持文件选择框'}), 400

    if selected is None:
        return jsonify({'error': '无法打开文件选择框'}), 500
    if selected == "":
        return jsonify({'cancelled': True})

    selected_path = Path(selected).expanduser()
    if selected_path.suffix.lower() not in REPORT_FILE_SUFFIXES:
        return jsonify({'error': 'Only report files are supported'}), 400
    if not selected_path.exists() or not selected_path.is_file():
        return jsonify({'error': 'File not found'}), 404

    return jsonify({'report_path': display_path(selected_path)})

@app.route('/api/preview')
def preview_file():
    file_path = request.args.get('path', '')
    if not file_path:
        return jsonify({'error': 'Missing file path'}), 400

    try:
        full_path = resolve_allowed_file(file_path)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    if not full_path.exists():
        return jsonify({'error': 'File not found'}), 404

    try:
        if full_path.suffix.lower() == '.csv':
            page = max(1, int(request.args.get("page", 1)))
            per_page = min(20, max(1, int(request.args.get("per_page", 20))))
            sort_by = request.args.get("sort_by", "").strip()
            sort_dir = request.args.get("sort_dir", "desc").strip().lower()
            sort_dir = "asc" if sort_dir == "asc" else "desc"
            df_all = pd.read_csv(full_path)
            sort_column = None
            if sort_by == "citationCount" and "citationCount" in df_all.columns:
                sort_column = "_sort_citation_count"
                df_all[sort_column] = pd.to_numeric(df_all["citationCount"], errors="coerce")
            elif sort_by == "publicationDate":
                sort_column = "_sort_publication_date"
                if "publicationDate" in df_all.columns:
                    df_all[sort_column] = pd.to_datetime(df_all["publicationDate"], errors="coerce")
                else:
                    df_all[sort_column] = pd.NaT
                if "year" in df_all.columns:
                    year_dates = pd.to_datetime(
                        pd.to_numeric(df_all["year"], errors="coerce").astype("Int64").astype(str) + "-01-01",
                        errors="coerce",
                    )
                    df_all[sort_column] = df_all[sort_column].fillna(year_dates)
            if sort_column:
                df_all = df_all.sort_values(
                    by=sort_column,
                    ascending=(sort_dir == "asc"),
                    na_position="last",
                    kind="mergesort",
                ).drop(columns=[sort_column])
            total = len(df_all)
            start = (page - 1) * per_page
            end = start + per_page
            df = df_all.iloc[start:end].copy()
            df["__row_index"] = df.index
            df = df.where(pd.notna(df), "")
            return jsonify({
                'type': 'csv',
                'data': df.to_dict(orient='records'),
                'columns': df.columns.tolist(),
                'page': page,
                'per_page': per_page,
                'total': total,
                'total_pages': max(1, (total + per_page - 1) // per_page),
                'sort_by': sort_by,
                'sort_dir': sort_dir,
            })
        elif full_path.suffix.lower() in TEXT_REPORT_FILE_SUFFIXES:
            # 读取文本文件内容
            content = full_path.read_text(encoding='utf-8')
            return jsonify({
                'type': 'text',
                'content': content
            })
        elif full_path.suffix.lower() == '.pdf':
            return jsonify({'error': 'PDF preview is not supported in this web UI'}), 400
        else:
            return jsonify({'error': 'Unsupported file type'}), 400
    except Exception as e:
        return jsonify({'error': f'Failed to read file: {str(e)}'}), 500


@app.route('/api/open_file', methods=['POST'])
def open_file():
    data = request.get_json(silent=True) or {}
    file_path = data.get("path", "")
    if not file_path:
        return jsonify({'error': 'Missing file path'}), 400

    try:
        full_path = resolve_allowed_file(file_path)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    if not full_path.exists() or not full_path.is_file():
        return jsonify({'error': 'File not found'}), 404

    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(full_path)])
        elif os.name == "nt":
            os.startfile(str(full_path))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(full_path)])
    except Exception as exc:
        return jsonify({'error': f'无法打开文件: {exc}'}), 500

    return jsonify({'status': 'opened', 'path': str(full_path)})

@app.route('/api/models', methods=['GET', 'POST'])
def list_models():
    payload = request.get_json(silent=True) or {}
    source = payload if request.method == "POST" else request.args
    base_url = source.get('base_url', '').strip().rstrip("/")
    provider = source.get('provider', 'ollama').strip() or 'ollama'
    api_key = source.get('api_key', '').strip()
    if not base_url:
        return jsonify({'error': 'Missing base URL'}), 400
    
    try:
        if provider == "openai_compatible":
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            response = requests.get(f"{base_url}/models", headers=headers, timeout=8)
        else:
            response = requests.get(f"{base_url}/api/tags", timeout=8)
        response.raise_for_status()
        payload = response.json()
        if provider == "openai_compatible":
            models = [item.get("id", "").strip() for item in payload.get("data", []) if item.get("id")]
        else:
            models = [item.get("name", "").strip() for item in payload.get("models", []) if item.get("name")]
        return jsonify({'models': models})
    except Exception as e:
        return jsonify({'error': f'Failed to fetch models: {str(e)}'}), 500

def check_runtime() -> int:
    missing_modules = []
    if scholar is None:
        missing_modules.append("data_sources.semantic_scholar")
    if multi_source_search is None:
        missing_modules.append("multi_source_search")
    if report is None:
        missing_modules.append("daily_report")

    if missing_modules:
        print(f"检查失败，模块不可用: {', '.join(missing_modules)}")
        return 1

    print("检查通过：Web 应用和核心模块可导入。")
    print(f"项目目录: {PROJECT_DIR}")
    print(f"检索目录: {SEARCH_RESULTS_DIR}")
    print(f"输出目录: {OUTPUTS_DIR}")
    return 0


def should_auto_open_browser(debug: bool) -> bool:
    if os.getenv("AUTO_OPEN_BROWSER", "1").strip().lower() in {"0", "false", "no", "off"}:
        return False
    if not debug:
        return True
    return os.getenv("WERKZEUG_RUN_MAIN") == "true"


def open_browser_later(url: str) -> None:
    def open_url() -> None:
        try:
            webbrowser.open(url, new=1, autoraise=True)
        except Exception as exc:
            logger.warning("无法自动打开浏览器: %s", exc)

    threading.Timer(1.0, open_url).start()


if __name__ == '__main__':
    if "--check" in sys.argv:
        raise SystemExit(check_runtime())
    port = int(os.getenv("PORT", "5001"))
    # 默认关闭 debug：打包成 exe 后开 debug 会触发 watchdog 重载并暴露调试器，有安全风险
    debug = os.getenv("FLASK_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"}
    url = f"http://127.0.0.1:{port}"
    if should_auto_open_browser(debug):
        print(f"浏览器将自动打开: {url}")
        open_browser_later(url)
    else:
        print(f"Web UI 地址: {url}")
    app.run(debug=debug, host='127.0.0.1', port=port)
