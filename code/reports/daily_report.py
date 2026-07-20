# -*- coding: utf-8 -*-
"""
daily_report.py

统一版科研日报生成脚本（单文件）：
1. 读取 CSV 文献数据
2. 清洗与去重
3. 调用 Ollama 生成结构化 JSON
4. 校验并重试
5. 程序回填 references
6. 输出 JSON 与 Markdown
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import textwrap
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

import pandas as pd
import requests



# 路径定位：兼容源码运行与 PyInstaller 打包
# - 资源(prompts)从资源目录读；用户数据写到 exe 所在目录
def _is_frozen() -> bool:
    import sys as _sys
    return getattr(_sys, "frozen", False) and hasattr(_sys, "_MEIPASS")

import sys as _sys
if _is_frozen():
    _PROJECT_DIR = Path(_sys.executable).resolve().parent   # 用户数据目录
    _BUNDLE_DIR = Path(_sys._MEIPASS)                       # 资源目录（prompts 打包到此处）
else:
    BASE_DIR = Path(__file__).resolve().parent              # code/reports
    CODE_DIR = BASE_DIR.parent                              # code
    _PROJECT_DIR = CODE_DIR.parent                          # V6 项目根
    _BUNDLE_DIR = _PROJECT_DIR                              # 源码模式下 prompts 在项目根

PROJECT_DIR = _PROJECT_DIR
PROMPTS_DIR = _BUNDLE_DIR / "prompts"
REPORT_STYLE_PROMPTS_DIR = PROMPTS_DIR / "report-styles"
LITERNEXUS_OUTPUTS_DIR = PROJECT_DIR / "LiterNexus_outputs"
LEGACY_BRAND_OUTPUTS_DIR = PROJECT_DIR / "ScholarFlow_outputs"
if LEGACY_BRAND_OUTPUTS_DIR.exists() and not LITERNEXUS_OUTPUTS_DIR.exists():
    LEGACY_BRAND_OUTPUTS_DIR.rename(LITERNEXUS_OUTPUTS_DIR)
WORKSPACE_OUTPUTS_DIR = LITERNEXUS_OUTPUTS_DIR

CONFIG = {
    # 输入 CSV（优先读取统一输出目录下的 metadata/csv 文件）
    "input_csv": str(WORKSPACE_OUTPUTS_DIR / "literature" / "metadata" / "csv" / "refractory_high_entropy_alloy_2026-03-07.csv"),

    # 输出目录
    "output_dir": str(WORKSPACE_OUTPUTS_DIR / "reports"),

    # LLM 配置
    "llm_provider": "openai_compatible",  # ollama / openai_compatible
    "ollama_base_url": "",
    "llm_base_url": "",
    "llm_api_key": "",
    "model": "",

    # 送入模型的论文数量（<=0 表示全部）
    "max_papers_for_llm": 15,

    # 若摘要为空，是否保留该文献
    "keep_empty_abstract": False,

    # 报告证据输入模式：abstract_only / fulltext_only / abstract_plus_fulltext
    "report_input_mode": "abstract_only",
    "literature_library_db": str(WORKSPACE_OUTPUTS_DIR / "literature" / "literature_library.sqlite"),
    "fulltext_chunk_limit_per_paper": 4,
    "fulltext_chunk_char_limit": 900,

    # LLM 参数
    "temperature": 0,
    "top_p": 0.9,
    "num_predict": 6000,
    "ollama_request_timeout_sec": 900,

    # JSON 校验失败重试次数
    "max_retry": 3,

    # 主题名留空则自动从 query 生成
    "topic_override": "",

    # 报告风格
    "report_style": "科研日报",

    # research_content 最低字数建议
    "min_research_content_chars": 350,

    # 是否保存调试文件
    "save_debug_files": True,
}

PROMPT_TEMPLATE_FILES = {
    "system": "system-role.md",
    "literature_review": "literature-review-report.md",
    "json_repair": "json-repair.md",
}
REPORT_STYLE_NAMES = [
    "科研日报",
    "主题综述",
    "研究进展",
    "方法对比",
    "材料体系对比",
    "综述摘要",
    "技术路线图",
    "专利机会",
    "研究建议",
]
REPORT_STYLE_ALIASES = {"专利撰写": "专利机会", "实验建议": "研究建议"}
REPORT_INPUT_MODES = {"abstract_only", "fulltext_only", "abstract_plus_fulltext"}
REPORT_DATA_SOURCES = {"csv", "collection", "library"}
HIGH_VALUE_SECTION_PATTERNS = [
    "method",
    "methods",
    "methodology",
    "experimental",
    "experiment",
    "materials and methods",
    "result",
    "results",
    "discussion",
    "conclusion",
    "conclusions",
]


def extract_prompt_block(markdown_text: str, source_path: Path) -> str:
    match = re.search(r"```(?:text)?\s*\n(.*?)\n```", markdown_text, flags=re.DOTALL)
    if not match:
        raise ValueError(f"提示词文件缺少 ```text 代码块：{source_path}")
    return match.group(1).strip()


def load_prompt_template(filename: str) -> str:
    path = PROMPTS_DIR / filename
    return extract_prompt_block(path.read_text(encoding="utf-8"), path)


def load_report_style_prompts() -> Dict[str, str]:
    prompts: Dict[str, str] = {}
    for style_name in REPORT_STYLE_NAMES:
        path = REPORT_STYLE_PROMPTS_DIR / f"{style_name}.md"
        prompts[style_name] = extract_prompt_block(path.read_text(encoding="utf-8"), path)
    return prompts


def render_prompt_template(template: str, values: Dict[str, Any]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered.strip()


SYSTEM_PROMPT = load_prompt_template(PROMPT_TEMPLATE_FILES["system"])
LITERATURE_REVIEW_PROMPT_TEMPLATE = load_prompt_template(PROMPT_TEMPLATE_FILES["literature_review"])
JSON_REPAIR_PROMPT_TEMPLATE = load_prompt_template(PROMPT_TEMPLATE_FILES["json_repair"])
REPORT_STYLE_PROMPTS = load_report_style_prompts()


def log_message(message: str, logger: Callable[[str], None] | None = None) -> None:
    print(message)
    if logger:
        logger(message)


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_str(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, float) and pd.isna(x):
        return ""
    return str(x).strip()


def normalize_whitespace(text: str) -> str:
    text = safe_str(text)
    text = text.replace("\u2009", " ").replace("\u2005", " ").replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_research_content(text: Any) -> str:
    raw = safe_str(text)
    if not raw:
        return ""
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    raw = raw.replace("\u2009", " ").replace("\u2005", " ").replace("\xa0", " ")

    section_heading_patterns = [
        r"\u80cc\u666f\u610f\u4e49",
        r"\u603b\u4f53\u8fdb\u5c55",
        r"\u6750\u6599\u4e0e\u8def\u7ebf\u6bd4\u8f83",
        r"\u65b9\u6cd5\u4f53\u7cfb",
        r"\u5173\u952e\u74f6\u9888",
        r"\u672a\u6765\u8d8b\u52bf",
        r"\u7814\u7a76\u5efa\u8bae",
        r"\u5b9e\u9a8c\u5efa\u8bae",
    ]
    heading_union = "|".join(section_heading_patterns)
    section_heading_regex = re.compile(rf"(^|\n)\s*({heading_union})\s*[\uff1a:]\s*")
    inline_section_heading_regex = re.compile(rf"(?<=[\u3002\uff01\uff1f!?\uff1b;])\s*({heading_union})\s*[\uff1a:]\s*")
    raw = inline_section_heading_regex.sub(lambda match: f"\n\n{match.group(1)}\uff1a", raw)
    raw = section_heading_regex.sub(lambda match: f"\n\n{match.group(2)}\uff1a", raw)
    raw = raw.strip()

    paragraphs: List[str] = []
    for block in re.split(r"\n\s*\n+", raw):
        lines = [normalize_whitespace(line) for line in block.splitlines()]
        paragraph = normalize_whitespace(" ".join(part for part in lines if part))
        if paragraph:
            paragraphs.append(paragraph)
    return "\n\n".join(paragraphs)


def research_content_paragraphs(text: Any) -> List[str]:
    normalized = normalize_research_content(text)
    if not normalized:
        return []
    return [paragraph for paragraph in normalized.split("\n\n") if paragraph.strip()]


def render_research_content_markdown_blocks(text: Any) -> List[str]:
    heading_patterns = [
        "背景意义",
        "总体进展",
        "材料与路线比较",
        "方法体系",
        "关键瓶颈",
        "未来趋势",
        "研究建议",
        "实验建议",
    ]
    heading_regex = re.compile(rf"^(?P<label>{'|'.join(heading_patterns)})[：:](?P<body>.*)$")

    blocks: List[str] = []
    for paragraph in research_content_paragraphs(text):
        match = heading_regex.match(paragraph)
        if match:
            label = "研究建议" if match.group("label") == "实验建议" else match.group("label")
            body = match.group("body").strip()
            blocks.append(f"### {label}")
            if body:
                blocks.append(body)
        else:
            blocks.append(paragraph)
    return blocks


def sanitize_filename(text: str) -> str:
    value = normalize_whitespace(text)
    value = re.sub(r"[^\w\-]+", "_", value, flags=re.UNICODE)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "report"


def build_unique_report_file_stem(
    group_output_dir: Path,
    topic: str,
    report_date: str,
    report_style: str,
) -> str:
    topic_part = sanitize_filename(topic)
    style_part = sanitize_filename(normalize_report_style(report_style))
    stem_prefix = f"{topic_part}_{report_date}_{style_part}"

    sequence = 1
    while True:
        candidate = f"{stem_prefix}_{sequence:02d}"
        candidate_paths = [
            group_output_dir / f"{candidate}.json",
            group_output_dir / f"{candidate}.md",
        ]
        if not any(path.exists() for path in candidate_paths):
            return candidate
        sequence += 1


def normalize_doi(value: Any) -> str:
    text = normalize_whitespace(value)
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.I)
    text = re.sub(r"^doi:\s*", "", text, flags=re.I)
    return text.strip().lower()


def normalize_title_key(value: Any) -> str:
    text = normalize_whitespace(value).lower()
    text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_date_for_sorting(x: Any) -> pd.Timestamp:
    s = safe_str(x)
    if not s:
        return pd.NaT
    try:
        return pd.to_datetime(s, errors="coerce")
    except Exception:
        return pd.NaT


def clean_paper_record(row: pd.Series) -> Dict[str, Any]:
    return {
        "identity_key": safe_str(row.get("identity_key", "")),
        "query": normalize_whitespace(row.get("query", "")),
        "paperId": safe_str(row.get("paperId", "")),
        "title": normalize_whitespace(row.get("title", "")),
        "authors": normalize_whitespace(row.get("authors", "")),
        "abstract": normalize_whitespace(row.get("abstract", "")),
        "year": safe_str(row.get("year", "")),
        "venue": normalize_whitespace(row.get("venue", "")),
        "volume": normalize_whitespace(row.get("volume", "")),
        "issue": normalize_whitespace(row.get("issue", "")),
        "publicationDate": safe_str(row.get("publicationDate", "")),
        "citationCount": safe_str(row.get("citationCount", "")),
        "doi": normalize_whitespace(row.get("doi", "")),
        "url": safe_str(row.get("url", "")),
        "pdf_url": safe_str(row.get("pdf_url", "")),
        "source": normalize_whitespace(row.get("source", "")),
    }


CSV_COLUMN_ALIASES = {
    "title": ["标题", "论文标题", "文献标题", "题名", "name"],
    "abstract": ["摘要", "内容摘要", "summary", "description"],
    "doi": ["数字对象标识符", "doi号", "doi编号"],
    "authors": ["作者", "作者列表", "author"],
    "year": ["年份", "发表年份", "出版年份"],
    "venue": ["期刊", "期刊名称", "会议", "出版物", "journal"],
    "volume": ["卷", "卷号"],
    "issue": ["期", "期号"],
    "publicationDate": ["发表日期", "出版日期", "发布日期", "date"],
    "citationCount": ["引用次数", "被引次数", "引用量", "citations"],
    "query": ["主题", "检索主题", "检索词", "关键词", "topic"],
    "source": ["来源", "数据来源", "数据库"],
    "url": ["链接", "文献链接", "网址"],
    "pdf_url": ["pdf链接", "全文链接", "下载链接"],
    "identity_key": ["文献标识", "文献编号", "唯一标识"],
}


def map_csv_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, Dict[str, str]]:
    normalized_names = {str(column).strip().lstrip("\ufeff").lower(): column for column in df.columns}
    rename_map: Dict[str, str] = {}
    detected: Dict[str, str] = {}
    canonical_names = set(CSV_COLUMN_ALIASES)
    for canonical, aliases in CSV_COLUMN_ALIASES.items():
        if canonical in df.columns:
            continue
        candidates = [canonical, *aliases]
        source_column = next(
            (normalized_names.get(str(candidate).strip().lower()) for candidate in candidates if str(candidate).strip().lower() in normalized_names),
            None,
        )
        if source_column is not None and source_column not in canonical_names:
            rename_map[source_column] = canonical
            detected[str(source_column)] = canonical
    return df.rename(columns=rename_map), detected


def normalize_papers_dataframe(df: pd.DataFrame, *, filter_for_mode: bool = True) -> pd.DataFrame:
    mapped_df, _ = map_csv_columns(df)
    required_cols = [
        "title", "abstract", "doi", "venue", "volume", "issue", "year",
        "publicationDate", "citationCount", "authors",
    ]
    for col in required_cols:
        if col not in mapped_df.columns:
            mapped_df[col] = ""

    cleaned = [clean_paper_record(row) for _, row in mapped_df.iterrows()]
    normalized = pd.DataFrame(cleaned)
    if (
        filter_for_mode
        and not CONFIG["keep_empty_abstract"]
        and normalize_report_input_mode(CONFIG.get("report_input_mode")) == "abstract_only"
    ):
        normalized = normalized[normalized["abstract"].astype(str).str.strip() != ""]

    normalized["_pub_dt"] = normalized["publicationDate"].apply(parse_date_for_sorting)
    normalized["_cite_num"] = pd.to_numeric(normalized["citationCount"], errors="coerce").fillna(0)
    normalized = normalized.sort_values(by=["_pub_dt", "_cite_num"], ascending=[False, False])
    return normalized.reset_index(drop=True)


def deduplicate_papers(papers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    results = []
    for p in papers:
        key = (safe_str(p.get("doi")).lower(), safe_str(p.get("title")).lower())
        if key in seen:
            continue
        seen.add(key)
        results.append(p)
    return results


def load_papers_from_csv(csv_path: str | Path, *, filter_for_mode: bool = True) -> pd.DataFrame:
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"找不到输入文件: {csv_path}")

    return normalize_papers_dataframe(pd.read_csv(csv_path), filter_for_mode=filter_for_mode)


def guess_data_source_from_df(df: pd.DataFrame) -> str:
    if "source" not in df.columns:
        return "Semantic Scholar"

    source_labels = {
        "semantic_scholar": "Semantic Scholar",
        "openalex": "OpenAlex",
        "crossref": "Crossref",
        "arxiv": "arXiv",
        "pubmed": "PubMed",
        "springer_nature": "Springer Nature",
    }
    sources = [
        source_labels.get(safe_str(value), safe_str(value))
        for value in df["source"].dropna().unique().tolist()
        if safe_str(value)
    ]
    if not sources:
        return "Semantic Scholar"
    return " / ".join(sources)


def resolve_input_csv(csv_path: str | Path) -> Path:
    path = Path(csv_path).expanduser()
    if not path.is_absolute():
        path = PROJECT_DIR / path
    if path.exists():
        return path

    legacy_path = PROJECT_DIR / "s2_papers.csv"
    if path in {
        WORKSPACE_OUTPUTS_DIR / "literature" / "metadata" / "csv" / "s2_papers.csv",
        PROJECT_DIR / "Literature_search_results" / "s2_papers.csv",
        PROJECT_DIR / "search_results" / "s2_papers.csv",
    } and legacy_path.exists():
        warnings.warn(
            f"默认输入文件 {path} 不存在，已回退到旧路径 {legacy_path}",
            stacklevel=2,
        )
        return legacy_path

    return path


def select_papers_for_llm(df: pd.DataFrame, max_n: int) -> List[Dict[str, Any]]:
    if len(df) == 0:
        return []
    if max_n <= 0:
        return df.to_dict(orient="records")
    return df.head(max_n).to_dict(orient="records")


def guess_topic_from_df(df: pd.DataFrame) -> str:
    if "query" in df.columns and not df["query"].dropna().empty:
        q = safe_str(df["query"].dropna().iloc[0])
        if q:
            return q
    return "科研文献综合日报"


def extract_queries_from_df(df: pd.DataFrame) -> str:
    if "query" not in df.columns:
        return ""
    values = [normalize_whitespace(x) for x in df["query"].dropna().tolist()]
    values = [x for x in values if x]
    unique_values = list(dict.fromkeys(values))
    return ", ".join(unique_values)


def split_df_by_query(df: pd.DataFrame) -> List[Tuple[str, pd.DataFrame]]:
    if "query" not in df.columns:
        deduped = deduplicate_papers(df.to_dict(orient="records"))
        return [("科研文献综合日报", pd.DataFrame(deduped))]

    ordered_queries = []
    seen = set()
    for value in df["query"].tolist():
        query = normalize_whitespace(value)
        group_name = query or "未命名主题"
        if group_name in seen:
            continue
        seen.add(group_name)
        ordered_queries.append(group_name)

    groups: List[Tuple[str, pd.DataFrame]] = []
    for group_name in ordered_queries:
        if group_name == "未命名主题":
            subset = df[df["query"].astype(str).str.strip() == ""].copy()
        else:
            subset = df[df["query"] == group_name].copy()
        deduped = deduplicate_papers(subset.to_dict(orient="records"))
        groups.append((group_name, pd.DataFrame(deduped)))
    return groups


def normalize_report_input_mode(value: Any) -> str:
    mode = safe_str(value).lower().replace("-", "_").replace("+", "_")
    mode = re.sub(r"\s+", "_", mode)
    aliases = {
        "abstract": "abstract_only",
        "metadata": "abstract_only",
        "summary": "abstract_only",
        "fulltext": "fulltext_only",
        "full_text": "fulltext_only",
        "chunks": "fulltext_only",
        "abstract_fulltext": "abstract_plus_fulltext",
        "abstract_full_text": "abstract_plus_fulltext",
        "hybrid": "abstract_plus_fulltext",
        "mixed": "abstract_plus_fulltext",
    }
    mode = aliases.get(mode, mode)
    return mode if mode in REPORT_INPUT_MODES else "abstract_only"


def report_input_mode_label(mode: str) -> str:
    return {
        "abstract_only": "摘要模式",
        "fulltext_only": "全文证据模式",
        "abstract_plus_fulltext": "摘要+全文混合模式",
    }.get(mode, "摘要模式")


def library_db_path() -> Path:
    configured = safe_str(CONFIG.get("literature_library_db"))
    return Path(configured) if configured else WORKSPACE_OUTPUTS_DIR / "literature" / "literature_library.sqlite"


LIBRARY_REPORT_COLUMNS = """
    p.identity_key, p.query, p.paperId, p.source, p.title, p.authors, p.abstract,
    p.year, p.venue, p.volume, p.issue, p.publicationDate, p.citationCount,
    p.doi, p.url, p.pdf_url
"""


def normalize_report_data_source(value: Any) -> str:
    source = safe_str(value).lower().replace("-", "_")
    aliases = {
        "dataset": "csv",
        "search": "csv",
        "search_result": "csv",
        "topic_collection": "collection",
        "library_collection": "collection",
        "all": "library",
        "all_library": "library",
    }
    source = aliases.get(source, source)
    return source if source in REPORT_DATA_SOURCES else "csv"


def load_papers_from_library(
    data_source: str,
    collection_id: str = "",
    *,
    filter_for_mode: bool = True,
) -> tuple[pd.DataFrame, str]:
    source = normalize_report_data_source(data_source)
    if source not in {"collection", "library"}:
        raise ValueError("文献库读取仅支持文献主题库或全部文献库")

    db_path = library_db_path()
    if not db_path.exists():
        raise FileNotFoundError("文献库尚未初始化")

    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5) as conn:
            if source == "collection":
                collection_id = safe_str(collection_id)
                if not collection_id:
                    raise ValueError("请选择一个文献主题库")
                collection = conn.execute(
                    "SELECT name FROM library_collections WHERE collection_id = ?",
                    (collection_id,),
                ).fetchone()
                if collection is None:
                    raise ValueError("所选文献主题库不存在")
                source_label = safe_str(collection[0]) or "文献主题库"
                query = f"""
                    SELECT {LIBRARY_REPORT_COLUMNS}
                    FROM collection_papers cp
                    JOIN papers p ON p.identity_key = cp.identity_key
                    WHERE cp.collection_id = ?
                      AND (COALESCE(p.title, '') != '' OR COALESCE(p.abstract, '') != '')
                    ORDER BY cp.created_at DESC, p.title ASC
                """
                df = pd.read_sql_query(query, conn, params=(collection_id,))
            else:
                source_label = "全部文献库"
                query = f"""
                    SELECT {LIBRARY_REPORT_COLUMNS}
                    FROM papers p
                    WHERE COALESCE(p.title, '') != '' OR COALESCE(p.abstract, '') != ''
                    ORDER BY p.last_seen_at DESC, p.title ASC
                """
                df = pd.read_sql_query(query, conn)
    except sqlite3.Error as exc:
        raise RuntimeError(f"读取文献库失败: {exc}") from exc

    if df.empty:
        raise RuntimeError(f"{source_label}中没有可用于生成报告的文献")
    df["query"] = source_label
    return normalize_papers_dataframe(df, filter_for_mode=filter_for_mode), source_label


def load_report_source(
    data_source: str,
    *,
    input_csv: str | Path | None = None,
    collection_id: str = "",
    filter_for_mode: bool = True,
) -> tuple[pd.DataFrame, str, Path | None]:
    source = normalize_report_data_source(data_source)
    if source == "csv":
        if input_csv is None or not safe_str(input_csv):
            raise ValueError("请选择一个 CSV 数据集")
        csv_path = resolve_input_csv(input_csv)
        return load_papers_from_csv(csv_path, filter_for_mode=filter_for_mode), csv_path.name, csv_path

    df, source_label = load_papers_from_library(
        source,
        collection_id=collection_id,
        filter_for_mode=filter_for_mode,
    )
    return df, source_label, None


def report_source_coverage(df: pd.DataFrame, source_label: str = "") -> Dict[str, Any]:
    papers = df.to_dict(orient="records")
    abstract_count = sum(1 for paper in papers if normalize_whitespace(paper.get("abstract", "")))
    matched_count = 0
    fulltext_count = 0
    chunk_count = 0
    seen_identity_keys: set[str] = set()
    fulltext_paper_indexes: set[int] = set()
    db_path = library_db_path()

    if db_path.exists():
        try:
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5) as conn:
                conn.row_factory = sqlite3.Row
                for paper_index, paper in enumerate(papers):
                    match = paper_match_row(conn, paper)
                    if not match:
                        continue
                    identity_key = safe_str(match["identity_key"])
                    if identity_key in seen_identity_keys:
                        continue
                    seen_identity_keys.add(identity_key)
                    matched_count += 1
                    evidence = conn.execute(
                        """
                        SELECT f.parse_status, COUNT(c.chunk_id) AS chunk_count
                        FROM paper_fulltext f
                        LEFT JOIN paper_chunks c ON c.identity_key = f.identity_key
                            AND COALESCE(c.chunk_text, '') != ''
                        WHERE f.identity_key = ?
                        GROUP BY f.identity_key, f.parse_status
                        """,
                        (identity_key,),
                    ).fetchone()
                    available_chunks = int(evidence["chunk_count"] or 0) if evidence else 0
                    if evidence and evidence["parse_status"] == "parsed" and available_chunks > 0:
                        fulltext_count += 1
                        chunk_count += available_chunks
                        fulltext_paper_indexes.add(paper_index)
        except sqlite3.Error:
            matched_count = 0
            fulltext_count = 0
            chunk_count = 0

    total = len(papers)
    mixed_usable_count = sum(
        1
        for index, paper in enumerate(papers)
        if normalize_whitespace(paper.get("abstract", "")) or index in fulltext_paper_indexes
    )
    return {
        "source_label": source_label,
        "paper_count": total,
        "abstract_count": abstract_count,
        "library_match_count": matched_count,
        "fulltext_paper_count": fulltext_count,
        "chunk_count": chunk_count,
        "missing_abstract_count": max(0, total - abstract_count),
        "missing_fulltext_count": max(0, total - fulltext_count),
        "mixed_usable_count": mixed_usable_count,
        "abstract_coverage": round((abstract_count / total * 100), 1) if total else 0.0,
        "fulltext_coverage": round((fulltext_count / total * 100), 1) if total else 0.0,
    }


def paper_match_row(conn: sqlite3.Connection, paper: Dict[str, Any]) -> sqlite3.Row | None:
    identity_key = safe_str(paper.get("identity_key"))
    if identity_key:
        row = conn.execute(
            "SELECT identity_key FROM papers WHERE identity_key = ?",
            (identity_key,),
        ).fetchone()
        if row:
            return row

    doi = normalize_doi(paper.get("doi"))
    if doi:
        row = conn.execute(
            "SELECT identity_key FROM papers WHERE lower(COALESCE(doi, '')) = ? ORDER BY last_seen_at DESC LIMIT 1",
            (doi,),
        ).fetchone()
        if row:
            return row

    title_key = normalize_title_key(paper.get("title"))
    if title_key:
        row = conn.execute(
            "SELECT identity_key FROM papers WHERE normalized_title = ? ORDER BY last_seen_at DESC LIMIT 1",
            (title_key,),
        ).fetchone()
        if row:
            return row
    return None


def section_priority(section_title: Any) -> tuple[int, int]:
    section = normalize_source_text(section_title)
    if not section:
        return (1, 0)
    for idx, pattern in enumerate(HIGH_VALUE_SECTION_PATTERNS):
        if pattern in section:
            return (0, idx)
    if "reference" in section or "acknowledg" in section:
        return (3, 0)
    return (2, 0)


def select_high_value_chunks(rows: list[sqlite3.Row], limit: int) -> list[dict[str, Any]]:
    chunks = [dict(row) for row in rows if normalize_whitespace(row["chunk_text"])]
    chunks.sort(key=lambda item: (section_priority(item.get("section_title")), int(item.get("chunk_index") or 0)))
    return chunks[: max(0, int(limit or 0))]


def load_fulltext_chunks_for_paper(conn: sqlite3.Connection, paper: Dict[str, Any]) -> list[dict[str, Any]]:
    match = paper_match_row(conn, paper)
    if not match:
        return []
    rows = conn.execute(
        """
        SELECT c.chunk_id, c.section_title, c.page_start, c.page_end, c.chunk_text, c.chunk_index
        FROM paper_chunks c
        JOIN paper_fulltext f ON f.identity_key = c.identity_key
        WHERE c.identity_key = ?
          AND f.parse_status = 'parsed'
          AND COALESCE(c.chunk_text, '') != ''
        ORDER BY c.chunk_index ASC
        """,
        (match["identity_key"],),
    ).fetchall()
    return select_high_value_chunks(rows, int(CONFIG.get("fulltext_chunk_limit_per_paper") or 4))


def enrich_papers_with_fulltext_chunks(papers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    mode = normalize_report_input_mode(CONFIG.get("report_input_mode", "abstract_only"))
    if mode == "abstract_only":
        return [dict(paper, _fulltext_chunks=[]) for paper in papers]

    db_path = library_db_path()
    if not db_path.exists():
        return [dict(paper, _fulltext_chunks=[]) for paper in papers]

    enriched: List[Dict[str, Any]] = []
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5) as conn:
            conn.row_factory = sqlite3.Row
            for paper in papers:
                item = dict(paper)
                item["_fulltext_chunks"] = load_fulltext_chunks_for_paper(conn, paper)
                enriched.append(item)
    except sqlite3.Error:
        return [dict(paper, _fulltext_chunks=[]) for paper in papers]
    return enriched


def chunk_page_label(chunk: Dict[str, Any]) -> str:
    page_start = int(chunk.get("page_start") or 0)
    page_end = int(chunk.get("page_end") or 0)
    if page_start and page_end and page_end != page_start:
        return f"p.{page_start}-{page_end}"
    if page_start:
        return f"p.{page_start}"
    return "page unknown"



def format_chunk_for_prompt(chunk: Dict[str, Any], chunk_number: int) -> str:
    section = normalize_whitespace(chunk.get("section_title", "")) or "Unknown section"
    page_label = chunk_page_label(chunk)
    text = normalize_whitespace(chunk.get("chunk_text", ""))
    char_limit = max(200, int(CONFIG.get("fulltext_chunk_char_limit") or 900))
    if len(text) > char_limit:
        text = text[:char_limit].rstrip() + "..."
    return f"- Chunk {chunk_number} ({page_label}, {section}): {text}"


def build_papers_text(papers: List[Dict[str, Any]]) -> str:
    mode = normalize_report_input_mode(CONFIG.get("report_input_mode", "abstract_only"))
    blocks = []
    for i, p in enumerate(papers, 1):
        abstract = safe_str(p.get("abstract", ""))
        chunks = p.get("_fulltext_chunks") if isinstance(p.get("_fulltext_chunks"), list) else []
        abstract_line = f"Abstract: {abstract}" if mode != "fulltext_only" else "Abstract: omitted by fulltext_only mode"
        if mode == "abstract_only":
            fulltext_text = "Full-text evidence chunks: not requested"
        elif chunks:
            chunk_lines = [format_chunk_for_prompt(chunk, idx) for idx, chunk in enumerate(chunks, 1)]
            fulltext_text = "Full-text evidence chunks:\n" + "\n".join(chunk_lines)
        else:
            fulltext_text = "Full-text evidence chunks: none available; do not infer page/section-specific evidence for this paper"
        block = f"""
[Paper {i}]
Title: {safe_str(p.get("title", ""))}
Journal: {safe_str(p.get("venue", ""))}
Publication Date: {safe_str(p.get("publicationDate", ""))}
DOI: {safe_str(p.get("doi", ""))}
Authors: {safe_str(p.get("authors", ""))}
{abstract_line}
{fulltext_text}
"""
        blocks.append(textwrap.dedent(block).strip())
    return "\n\n".join(blocks)

# 18. 本次给出的每一篇文献（1 到 {len(papers)}）都必须至少被引用一次。
def normalize_report_style(style: Any) -> str:
    value = safe_str(style) or "科研日报"
    value = REPORT_STYLE_ALIASES.get(value, value)
    return value if value in REPORT_STYLE_PROMPTS else "科研日报"


def build_prompt(papers: List[Dict[str, Any]], topic: str, report_date: str, report_style: str = "科研日报") -> str:
    papers_text = build_papers_text(papers)
    active_style = normalize_report_style(report_style)
    input_mode = normalize_report_input_mode(CONFIG.get("report_input_mode", "abstract_only"))
    style_instruction = REPORT_STYLE_PROMPTS[active_style]
    return render_prompt_template(LITERATURE_REVIEW_PROMPT_TEMPLATE, {
        "active_style": active_style,
        "style_instruction": style_instruction,
        "report_input_mode": input_mode,
        "report_input_mode_label": report_input_mode_label(input_mode),
        "min_research_content_chars": CONFIG["min_research_content_chars"],
        "reference_count": len(papers),
        "report_date": report_date,
        "topic": topic,
        "papers_text": papers_text,
    })



def sentence_candidates_from_text(text: Any, *, min_len: int = 24, max_len: int = 280, limit: int = 3) -> list[str]:
    normalized = normalize_whitespace(text)
    if not normalized:
        return []
    pieces = re.split(r"(?<=[\.!?。！？;；])\s+", normalized)
    results: list[str] = []
    seen = set()
    for piece in pieces:
        candidate = normalize_whitespace(piece)
        if len(candidate) < min_len:
            continue
        if len(candidate) > max_len:
            candidate = candidate[:max_len].rstrip(" ,;，；") + "..."
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        results.append(candidate)
        if len(results) >= limit:
            break
    return results



def build_evidence_candidate_text(papers: List[Dict[str, Any]]) -> str:
    blocks = []
    for idx, paper in enumerate(papers, 1):
        candidate_lines = []
        for snippet in sentence_candidates_from_text(paper.get("abstract", ""), limit=2):
            candidate_lines.append(f"- Abstract snippet: {snippet}")
        for chunk_idx, chunk in enumerate(paper.get("_fulltext_chunks", []) if isinstance(paper.get("_fulltext_chunks"), list) else [], 1):
            section = normalize_whitespace(chunk.get("section_title", "")) or "Unknown section"
            page_label = chunk_page_label(chunk)
            for snippet in sentence_candidates_from_text(chunk.get("chunk_text", ""), limit=2):
                candidate_lines.append(
                    f"- Full-text snippet ({page_label}, {section}, chunk {chunk_idx}): {snippet}"
                )
        if not candidate_lines:
            candidate_lines.append("- No reliable snippet candidates available; if you cite this paper, only use a verbatim snippet from the original abstract text above.")
        block = [
            f"[Paper {idx}]",
            f"Title: {safe_str(paper.get('title', ''))}",
            f"DOI: {safe_str(paper.get('doi', ''))}",
            *candidate_lines[:6],
        ]
        blocks.append("\n".join(block))
    return "\n\n".join(blocks)



def classify_validation_error(error_message: str) -> str:
    message = safe_str(error_message)
    if "research_content 过短" in message:
        return "research_content_too_short"
    if "research_content 需要按段落写作" in message:
        return "research_content_paragraphs_invalid"
    if "没有可回溯到摘要或全文片段的证据" in message or "evidence" in message:
        return "evidence_invalid"
    if "引用编号" in message:
        return "citation_invalid"
    return "generic_invalid"


def check_ollama_available(base_url: str) -> None:
    url = f"{base_url}/api/tags"
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
    except Exception as e:
        raise RuntimeError(
            "无法连接到 Ollama。请确认：\n"
            "1. 已执行 ollama serve\n"
            "2. 端口 11434 可访问\n"
            f"原始错误：{e}"
        ) from e


def call_ollama_chat(
    prompt: str,
    model: str,
    base_url: str,
    temperature: float = 0,
    top_p: float = 0.9,
    num_predict: int = 2200,
    request_timeout_sec: int = 900,
) -> Dict[str, Any]:
    url = f"{base_url}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {
            "temperature": temperature,
            "top_p": top_p,
            "num_predict": num_predict,
        },
    }

    try:
        r = requests.post(url, json=payload, timeout=(20, max(30, int(request_timeout_sec))))
    except requests.exceptions.ReadTimeout as exc:
        raise RuntimeError(
            "调用 Ollama 超时。"
            f"读取超时 {request_timeout_sec}s，model={model}，num_predict={num_predict}。"
            "可尝试：减小 num_predict、切换更小模型，或增大 ollama_request_timeout_sec。"
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise RuntimeError(
            "调用 Ollama 超时（连接或读取阶段）。"
            f"timeout={request_timeout_sec}s，model={model}。"
        ) from exc

    if not r.ok:
        detail = ""
        try:
            payload_text = r.json()
            if isinstance(payload_text, dict):
                detail = safe_str(payload_text.get("error")) or safe_str(payload_text)
            else:
                detail = safe_str(payload_text)
        except Exception:
            detail = safe_str(r.text)
        detail = detail or "未返回详细错误信息"
        raise RuntimeError(
            f"Ollama /api/chat 请求失败（HTTP {r.status_code}）。"
            f"model={model}, base_url={base_url}。"
            f"原因：{detail}"
        )
    data = r.json()

    if "message" not in data or "content" not in data["message"]:
        raise ValueError(f"Ollama 返回格式异常：{data}")

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
        "content": data["message"]["content"],
        "token_usage": token_usage,
    }


def call_openai_compatible_chat(
    prompt: str,
    model: str,
    base_url: str,
    api_key: str,
    temperature: float = 0,
    top_p: float = 0.9,
    num_predict: int = 2200,
    request_timeout_sec: int = 900,
) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": num_predict,
    }

    last_error: Exception | None = None
    for attempt in range(1, 5):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=(20, max(30, int(request_timeout_sec))))
            break
        except requests.exceptions.ReadTimeout as exc:
            last_error = exc
            if attempt == 4:
                raise RuntimeError(
                    "调用远程大模型超时。"
                    f"读取超时 {request_timeout_sec}s，model={model}，max_tokens={num_predict}。"
                ) from exc
        except requests.exceptions.Timeout as exc:
            last_error = exc
            if attempt == 4:
                raise RuntimeError(
                    "调用远程大模型超时（连接或读取阶段）。"
                    f"timeout={request_timeout_sec}s，model={model}。"
                ) from exc
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
            last_error = exc
            if attempt == 4:
                suffix_hint = "；如果服务要求 OpenAI-compatible 接口，请确认 Base URL 是否包含 /v1。"
                raise RuntimeError(
                    "远程大模型连接失败。"
                    f"model={model}, base_url={base_url}。"
                    f"原始错误：{exc}{suffix_hint}"
                ) from exc

        time.sleep(min(2 ** (attempt - 1), 8))
    else:
        raise RuntimeError("远程大模型请求失败。") from last_error

    if not r.ok:
        detail = ""
        try:
            payload_text = r.json()
            if isinstance(payload_text, dict):
                error = payload_text.get("error")
                detail = safe_str(error.get("message")) if isinstance(error, dict) else safe_str(error)
                detail = detail or safe_str(payload_text)
            else:
                detail = safe_str(payload_text)
        except Exception:
            detail = safe_str(r.text)
        detail = detail or "未返回详细错误信息"
        raise RuntimeError(
            f"远程大模型 /chat/completions 请求失败（HTTP {r.status_code}）。"
            f"model={model}, base_url={base_url}。"
            f"原因：{detail}"
        )

    data = r.json()
    try:
        usage = data.get("usage") or {}
        return {
            "content": safe_str(data["choices"][0]["message"]["content"]),
            "token_usage": {
                "prompt_tokens": usage.get("prompt_tokens") if isinstance(usage.get("prompt_tokens"), int) else None,
                "completion_tokens": usage.get("completion_tokens") if isinstance(usage.get("completion_tokens"), int) else None,
                "total_tokens": usage.get("total_tokens") if isinstance(usage.get("total_tokens"), int) else None,
            },
        }
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"远程大模型返回格式异常：{safe_str(data)}") from exc


def call_llm_chat(
    prompt: str,
    model: str,
    temperature: float = 0,
    top_p: float = 0.9,
    num_predict: int = 2200,
    request_timeout_sec: int = 900,
) -> Dict[str, Any]:
    provider = safe_str(CONFIG.get("llm_provider")) or "ollama"
    if provider == "openai_compatible":
        base_url = safe_str(CONFIG.get("llm_base_url")) or safe_str(CONFIG.get("ollama_base_url"))
        api_key = safe_str(CONFIG.get("llm_api_key"))
        if not base_url:
            raise RuntimeError("远程大模型 Base URL 为空。")
        if not api_key:
            raise RuntimeError("远程大模型访问密钥为空。")
        return call_openai_compatible_chat(
            prompt=prompt,
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=temperature,
            top_p=top_p,
            num_predict=num_predict,
            request_timeout_sec=request_timeout_sec,
        )

    base_url = safe_str(CONFIG.get("ollama_base_url")) or safe_str(CONFIG.get("llm_base_url"))
    return call_ollama_chat(
        prompt=prompt,
        model=model,
        base_url=base_url,
        temperature=temperature,
        top_p=top_p,
        num_predict=num_predict,
        request_timeout_sec=request_timeout_sec,
    )


def merge_token_usage(total: Dict[str, Any], item: Dict[str, Any] | None) -> Dict[str, Any]:
    item = item or {}
    for key in ["prompt_tokens", "completion_tokens", "total_tokens"]:
        value = item.get(key)
        if isinstance(value, int):
            total[key] = int(total.get(key) or 0) + value
    return total


def format_token_usage(token_usage: Dict[str, Any] | None) -> str:
    token_usage = token_usage or {}
    total = token_usage.get("total_tokens")
    prompt_tokens = token_usage.get("prompt_tokens")
    completion_tokens = token_usage.get("completion_tokens")
    if isinstance(total, int):
        details = []
        if isinstance(prompt_tokens, int):
            details.append(f"输入 {prompt_tokens}")
        if isinstance(completion_tokens, int):
            details.append(f"输出 {completion_tokens}")
        suffix = f"（{'，'.join(details)}）" if details else ""
        return f"{total} tokens{suffix}"
    return "模型接口未返回 token 统计"


def extract_json_text(raw_text: str) -> str:
    text = raw_text.strip()
    code_block_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.S)
    if code_block_match:
        return code_block_match.group(1).strip()

    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and last > first:
        return text[first:last + 1].strip()

    raise ValueError("未能从模型输出中提取 JSON")


def parse_json_output(raw_text: str) -> Dict[str, Any]:
    json_text = extract_json_text(raw_text)
    try:
        return json.loads(json_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 解析失败：{e}\n原始提取文本：\n{json_text}") from e


REQUIRED_KEYS = [
    "date",
    "report_style",
    "topic",
    "research_content",
    "key_findings",
    "scientific_questions",
    "methods",
    "references",
]

CITATION_RE = re.compile(r"\[(\d+)(?=[,\]])")
CHINESE_CHAR_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def has_citation(text: Any) -> bool:
    return bool(CITATION_RE.search(safe_str(text)))


def first_missing_citation_index(items: List[str]) -> int:
    for i, item in enumerate(items, 1):
        if not has_citation(item):
            return i
    return 0


def finding_conclusion(item: Any) -> str:
    if isinstance(item, dict):
        return safe_str(item.get("conclusion", ""))
    return safe_str(item)


def collect_citation_ids(text: str) -> set[int]:
    ids = set()
    for match in CITATION_RE.findall(safe_str(text)):
        try:
            ids.add(int(match))
        except ValueError:
            continue
    return ids


def normalize_source_text(text: Any) -> str:
    return re.sub(r"\s+", " ", safe_str(text)).strip().lower()


def compact_source_text(text: Any) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", normalize_source_text(text))


def significant_source_tokens(text: Any) -> list[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9\-]{3,}|[\u4e00-\u9fff]{2,}", normalize_source_text(text))
    stop_words = {
        "this", "that", "with", "from", "were", "was", "are", "and", "the", "for",
        "using", "based", "study", "results", "result", "paper", "show", "shows",
    }
    return [token for token in tokens if token not in stop_words]


def snippet_matches_source_text(snippet: Any, source_text: Any) -> bool:
    normalized_snippet = normalize_source_text(snippet)
    normalized_source = normalize_source_text(source_text)
    if len(normalized_snippet) < 12 or not normalized_source:
        return False
    if normalized_snippet in normalized_source:
        return True

    compact_snippet = compact_source_text(snippet)
    compact_source = compact_source_text(source_text)
    if len(compact_snippet) >= 12 and compact_snippet in compact_source:
        return True

    tokens = significant_source_tokens(snippet)
    if len(tokens) < 4:
        return False
    matched = sum(1 for token in tokens if token in normalized_source)
    return matched >= max(4, int(len(tokens) * 0.72))


def snippet_matches_paper(snippet: Any, paper: Dict[str, Any]) -> bool:
    if snippet_matches_source_text(snippet, paper.get("abstract", "")):
        return True
    for chunk in paper.get("_fulltext_chunks", []) if isinstance(paper.get("_fulltext_chunks"), list) else []:
        if snippet_matches_source_text(snippet, chunk.get("chunk_text", "")):
            return True
    return False


def evidence_snippet(ev: Dict[str, Any]) -> str:
    return normalize_whitespace(
        ev.get("evidence_snippet")
        or ev.get("abstract_snippet")
        or ev.get("fulltext_snippet")
        or ev.get("chunk_snippet")
        or ""
    )


def prune_unmatched_evidence(data: Dict[str, Any], papers_for_llm: List[Dict[str, Any]] | None) -> Dict[str, Any]:
    papers_by_ref = {
        idx: paper
        for idx, paper in enumerate(papers_for_llm or [], 1)
    }
    if not papers_by_ref:
        return data

    for item in data.get("key_findings", []):
        if not isinstance(item, dict):
            continue
        evidence = item.get("evidence", [])
        if not isinstance(evidence, list):
            item["evidence"] = []
            continue
        valid_evidence = []
        for ev in evidence:
            if not isinstance(ev, dict):
                continue
            ref_id = ev.get("ref_id")
            snippet = evidence_snippet(ev)
            if (
                isinstance(ref_id, int)
                and ref_id in papers_by_ref
                and snippet
                and snippet_matches_paper(snippet, papers_by_ref[ref_id])
            ):
                valid_evidence.append(ev)
        item["evidence"] = valid_evidence
    return data



def deduplicate_text_items(items: List[str]) -> List[str]:
    seen = set()
    results = []
    for item in items:
        normalized = normalize_whitespace(item)
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        results.append(normalized)
    return results



def salvage_report_json(data: Dict[str, Any], papers_for_llm: List[Dict[str, Any]] | None) -> Dict[str, Any]:
    salvaged = normalize_report_json(data)
    salvaged = prune_unmatched_evidence(salvaged, papers_for_llm)

    findings = []
    for item in salvaged.get("key_findings", []):
        if not isinstance(item, dict):
            continue
        conclusion = finding_conclusion(item)
        evidence = item.get("evidence", []) if isinstance(item.get("evidence"), list) else []
        if not conclusion or not evidence:
            continue
        findings.append({
            "conclusion": conclusion,
            "evidence": evidence[:1],
        })
    salvaged["key_findings"] = findings
    salvaged["scientific_questions"] = deduplicate_text_items(salvaged.get("scientific_questions", []))
    salvaged["methods"] = deduplicate_text_items(salvaged.get("methods", []))
    return salvaged


def count_chinese_chars(text: Any) -> int:
    return len(CHINESE_CHAR_RE.findall(safe_str(text)))


def is_mostly_chinese_text(text: Any, *, min_chars: int = 80, min_ratio: float = 0.2) -> bool:
    content = safe_str(text)
    if not content:
        return False

    chinese_count = count_chinese_chars(content)
    non_space_count = len(re.sub(r"\s+", "", content))
    if non_space_count <= 0:
        return False

    ratio = chinese_count / non_space_count
    return chinese_count >= min_chars and ratio >= min_ratio


def normalize_report_json(data: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    out["date"] = safe_str(data.get("date", ""))
    out["report_style"] = normalize_report_style(data.get("report_style", CONFIG.get("report_style", "科研日报")))
    out["topic"] = normalize_whitespace(data.get("topic", ""))
    out["research_content"] = normalize_research_content(data.get("research_content", ""))

    findings = data.get("key_findings", [])
    findings_out = []
    if isinstance(findings, list):
        for item in findings:
            if isinstance(item, dict):
                evidence_out = []
                evidence = item.get("evidence", [])
                if isinstance(evidence, list):
                    for ev in evidence:
                        if not isinstance(ev, dict):
                            continue
                        try:
                            ref_id = int(ev.get("ref_id"))
                        except (TypeError, ValueError):
                            ref_id = 0
                        evidence_out.append({
                            "ref_id": ref_id,
                            "abstract_snippet": normalize_whitespace(ev.get("abstract_snippet", "")),
                            "evidence_snippet": evidence_snippet(ev),
                            "section": normalize_whitespace(ev.get("section", "")),
                            "page": normalize_whitespace(ev.get("page", "")),
                        })
                findings_out.append({
                    "conclusion": normalize_whitespace(item.get("conclusion", "")),
                    "evidence": evidence_out,
                })
            else:
                conclusion = normalize_whitespace(item)
                if conclusion:
                    findings_out.append({"conclusion": conclusion, "evidence": []})
    out["key_findings"] = [item for item in findings_out if item.get("conclusion")]

    for key in ["scientific_questions", "methods"]:
        val = data.get(key, [])
        out[key] = [normalize_whitespace(x) for x in val if normalize_whitespace(x)] if isinstance(val, list) else []

    refs = data.get("references", [])
    refs_out = []
    if isinstance(refs, list):
        for item in refs:
            if isinstance(item, dict):
                refs_out.append({
                    "title": normalize_whitespace(item.get("title", "")),
                    "doi": normalize_whitespace(item.get("doi", "")),
                })
    out["references"] = refs_out
    return out


def validate_report_json(
    data: Dict[str, Any],
    expected_ref_count: int,
    papers_for_llm: List[Dict[str, Any]] | None = None,
) -> Tuple[bool, str]:
    for k in REQUIRED_KEYS:
        if k not in data:
            return False, f"缺少字段：{k}"

    if not isinstance(data["topic"], str):
        return False, "topic 必须是字符串"
    if data["report_style"] not in REPORT_STYLE_PROMPTS:
        return False, f"report_style 必须是以下之一：{', '.join(REPORT_STYLE_PROMPTS)}"
    if not isinstance(data["research_content"], str):
        return False, "research_content 必须是字符串"
    if not isinstance(data["key_findings"], list):
        return False, "key_findings 必须是列表"
    if not isinstance(data["scientific_questions"], list):
        return False, "scientific_questions 必须是列表"
    if not isinstance(data["methods"], list):
        return False, "methods 必须是列表"
    if not isinstance(data["references"], list):
        return False, "references 必须是列表"

    if len(data["research_content"].strip()) < CONFIG["min_research_content_chars"]:
        return False, f"research_content 过短，少于 {CONFIG['min_research_content_chars']} 字符"

    if not is_mostly_chinese_text(data["research_content"]):
        return False, "research_content 必须以中文撰写，当前中文内容不足"

    if len(research_content_paragraphs(data["research_content"])) < 3:
        return False, "research_content 需要按段落写作，至少保留 3 个自然段，且每段围绕一个小主题展开"

    if len(data["key_findings"]) < 3:
        return False, "key_findings 至少需要 3 条"
    if len(data["scientific_questions"]) < 3:
        return False, "scientific_questions 至少需要 3 条"
    if len(data["methods"]) < 3:
        return False, "methods 至少需要 3 条"

    if not has_citation(data["research_content"]):
        return False, "research_content 缺少引用编号，如 [1]"

    finding_conclusions = [finding_conclusion(item) for item in data["key_findings"]]
    missing_idx = first_missing_citation_index(finding_conclusions)
    if missing_idx:
        return False, f"key_findings 第 {missing_idx} 条 conclusion 缺少引用编号，如 [1]"

    papers_by_ref = {
        idx: paper
        for idx, paper in enumerate(papers_for_llm or [], 1)
    }
    for idx, item in enumerate(data["key_findings"], 1):
        if not isinstance(item, dict):
            return False, f"key_findings 第 {idx} 条必须是对象，包含 conclusion 和 evidence"
        evidence = item.get("evidence", [])
        if not isinstance(evidence, list) or not evidence:
            return False, f"key_findings 第 {idx} 条缺少 evidence 证据"
        matched_evidence_count = 0
        for ev_idx, ev in enumerate(evidence, 1):
            if not isinstance(ev, dict):
                return False, f"key_findings 第 {idx} 条 evidence 第 {ev_idx} 项必须是对象"
            ref_id = ev.get("ref_id")
            if not isinstance(ref_id, int) or ref_id < 1 or ref_id > expected_ref_count:
                return False, f"key_findings 第 {idx} 条 evidence 第 {ev_idx} 项 ref_id 超出范围"
            snippet = evidence_snippet(ev)
            if not snippet:
                return False, f"key_findings 第 {idx} 条 evidence 第 {ev_idx} 项缺少 evidence_snippet 或 abstract_snippet"
            if papers_by_ref:
                if snippet_matches_paper(snippet, papers_by_ref.get(ref_id, {})):
                    matched_evidence_count += 1
            else:
                matched_evidence_count += 1
        if papers_by_ref and matched_evidence_count <= 0:
            return False, f"key_findings 第 {idx} 条没有可回溯到摘要或全文片段的证据"
        conclusion_refs = collect_citation_ids(item.get("conclusion", ""))
        evidence_refs = {ev.get("ref_id") for ev in evidence if isinstance(ev, dict)}
        if conclusion_refs and not conclusion_refs.intersection(evidence_refs):
            return False, f"key_findings 第 {idx} 条 conclusion 的引用编号需要至少一个出现在 evidence.ref_id 中"

    missing_idx = first_missing_citation_index(data["scientific_questions"])
    if missing_idx:
        return False, f"scientific_questions 第 {missing_idx} 条缺少引用编号，如 [1]"

    missing_idx = first_missing_citation_index(data["methods"])
    if missing_idx:
        return False, f"methods 第 {missing_idx} 条缺少引用编号，如 [1]"

    for key in ["key_findings", "scientific_questions", "methods"]:
        for idx, item in enumerate(data[key], 1):
            text = finding_conclusion(item) if key == "key_findings" else item
            if not is_mostly_chinese_text(text, min_chars=6, min_ratio=0.15):
                return False, f"{key} 第 {idx} 条必须以中文撰写"

    cited_ids = set()
    cited_ids.update(collect_citation_ids(data["research_content"]))
    for item in data["key_findings"]:
        cited_ids.update(collect_citation_ids(finding_conclusion(item)))
    for item in data["scientific_questions"]:
        cited_ids.update(collect_citation_ids(item))
    for item in data["methods"]:
        cited_ids.update(collect_citation_ids(item))

    # if expected_ref_count > 0:
    #     required_ids = set(range(1, expected_ref_count + 1))
    #     missing_ids = sorted(required_ids - cited_ids)
    #     if missing_ids:
    #         missing_preview = ", ".join(str(x) for x in missing_ids[:10])
    #         return False, f"仍有文献未被引用：[{missing_preview}]"

    return True, "OK"


def repair_prompt(
    previous_output: str,
    error_message: str,
    original_prompt: str = "",
    papers_for_llm: List[Dict[str, Any]] | None = None,
) -> str:
    error_type = classify_validation_error(error_message)
    focus_map = {
        "research_content_too_short": "本次请优先保留已经基本可用的 topic、key_findings、scientific_questions、methods，只重点扩写 research_content，并确保长度明显高于最低阈值。",
        "research_content_paragraphs_invalid": "本次请优先保留已经基本可用的 topic、key_findings、scientific_questions、methods，只重点重写 research_content。请按多个自然段输出，并确保一个段落只围绕一个小主题展开。",
        "evidence_invalid": "本次请优先保留已经基本可用的 topic、research_content、scientific_questions、methods，只重点重写 key_findings。每条 finding 优先只保留 1 条最可靠 evidence；宁可减少 finding，也不要给无法逐字回溯的 evidence。",
        "citation_invalid": "本次请重点修复引用编号格式与字段间的一致性，尽量不要重写已经合格的内容。",
        "generic_invalid": "本次请在修复错误时尽量保留已经合格的字段，避免整份内容大幅漂移。",
    }
    evidence_candidate_text = build_evidence_candidate_text(papers_for_llm or [])
    return render_prompt_template(JSON_REPAIR_PROMPT_TEMPLATE, {
        "error_message": error_message,
        "error_type": error_type,
        "repair_focus": focus_map.get(error_type, focus_map["generic_invalid"]),
        "min_research_content_chars": CONFIG["min_research_content_chars"],
        "previous_output": previous_output,
        "original_prompt": original_prompt,
        "evidence_candidate_text": evidence_candidate_text or "(无额外证据候选)"
    })


def build_references_from_papers(papers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    seen = set()
    for p in papers:
        title = normalize_whitespace(p.get("title", ""))
        doi = normalize_whitespace(p.get("doi", ""))
        key = (title.lower(), doi.lower())
        if not title and not doi:
            continue
        if key in seen:
            continue
        seen.add(key)
        refs.append({
            "authors": normalize_whitespace(p.get("authors", "")),
            "title": title,
            "journal": normalize_whitespace(p.get("venue", "")),
            "volume": normalize_whitespace(p.get("volume", "")),
            "issue": normalize_whitespace(p.get("issue", "")),
            "year": safe_str(p.get("year", "")),
            "publicationDate": safe_str(p.get("publicationDate", "")),
            "doi": doi,
        })
    return refs


def format_journal_reference(ref: Dict[str, Any]) -> str:
    authors = normalize_whitespace(ref.get("authors", "")) or "Unknown"
    title = normalize_whitespace(ref.get("title", "")) or "Untitled"
    journal = normalize_whitespace(ref.get("journal", "")) or "Unknown Journal"
    volume = normalize_whitespace(ref.get("volume", ""))
    issue = normalize_whitespace(ref.get("issue", ""))
    year = safe_str(ref.get("year", ""))
    pub_date = safe_str(ref.get("publicationDate", ""))
    doi = normalize_whitespace(ref.get("doi", ""))

    if not year and pub_date:
        year = pub_date[:4]

    vol_issue = ""
    if volume and issue:
        vol_issue = f"{volume}({issue})"
    elif volume:
        vol_issue = volume
    elif issue:
        vol_issue = f"({issue})"

    parts = [f"{authors}. {title}[J]. {journal}"]

    if year and vol_issue:
        parts.append(f", {year}, {vol_issue}")
    elif year:
        parts.append(f", {year}")
    elif vol_issue:
        parts.append(f", {vol_issue}")

    if doi:
        parts.append(f". doi:{doi}")
    else:
        parts.append(".")

    return "".join(parts)


def cleanup_debug_files(out_dir: Path) -> int:
    removed = 0
    for file_path in out_dir.glob("debug_attempt_*.txt"):
        if file_path.is_file():
            file_path.unlink(missing_ok=True)
            removed += 1
    return removed


def cleanup_debug_files_recursive(root_dir: Path) -> int:
    if not root_dir.exists():
        return 0

    removed = 0
    for file_path in root_dir.rglob("debug_attempt_*.txt"):
        if file_path.is_file():
            file_path.unlink(missing_ok=True)
            removed += 1
    return removed


def render_markdown(
    data: Dict[str, Any],
    data_source: str,
    model_name: str,
    token_usage: Dict[str, Any] | None = None,
    title_topic: str = "",
    report_date: str = "",
) -> str:
    title_parts = [x for x in [safe_str(title_topic), safe_str(report_date)] if x]
    title = f"# {'_'.join(title_parts)}" if title_parts else "# 科研日报"
    report_style_label = safe_str(data.get('report_style', CONFIG.get('report_style', '科研日报')))
    report_style_display = "研究建议" if report_style_label == "实验建议" else report_style_label
    research_blocks = render_research_content_markdown_blocks(data.get("research_content", ""))
    lines = [
        title,
        "",
        f"日期：{safe_str(data.get('date', ''))}\n",
        f"报告风格：{report_style_display}\n",
        f"证据模式：{report_input_mode_label(safe_str(data.get('report_input_mode', CONFIG.get('report_input_mode', 'abstract_only'))))}\n",
        f"主题：{safe_str(data.get('topic', ''))}\n",
        f"文献范围：{safe_str(data.get('source_scope', ''))}\n",
        f"数据来源：{data_source}\n",
        f"生成模型：{model_name}\n",
        f"Token 消耗：{format_token_usage(token_usage)}\n",
        "",
    ]

    lines.append("")
    lines.append("## 一、研究内容")
    if research_blocks:
        lines.extend(research_blocks)
    else:
        lines.append(safe_str(data.get("research_content", "")))
    lines.append("")

    lines.append("## 二、主要发现")
    for i, item in enumerate(data.get("key_findings", []), 1):
        if isinstance(item, dict):
            lines.append(f"### {i}. {safe_str(item.get('conclusion', ''))}")
            evidence = item.get("evidence", [])
            if isinstance(evidence, list) and evidence:
                lines.append("")
                lines.append("证据片段：")
                for ev in evidence:
                    if not isinstance(ev, dict):
                        continue
                    ref_id = ev.get("ref_id", "")
                    section = normalize_whitespace(ev.get("section", ""))
                    page = normalize_whitespace(ev.get("page", ""))
                    cite_parts = [safe_str(ref_id)]
                    if page:
                        cite_parts.append(page if page.lower().startswith("p.") else f"p.{page}")
                    if section:
                        cite_parts.append(section)
                    snippet = evidence_snippet(ev)
                    lines.append(f"- [{', '.join(cite_parts)}] {snippet}")
                lines.append("")
        else:
            lines.append(f"### {i}. {item}")
    lines.append("")

    lines.append("## 三、主要科学问题")
    for i, item in enumerate(data.get("scientific_questions", []), 1):
        lines.append(f"{i}. {item}")
    lines.append("")

    lines.append("## 四、研究方法")
    for i, item in enumerate(data.get("methods", []), 1):
        lines.append(f"{i}. {item}")
    lines.append("")

    lines.append("## 五、文献出处")
    for i, ref in enumerate(data.get("references", []), 1):
        lines.append(f"[{i}] {format_journal_reference(ref)}")
        lines.append("")
    lines.append("")

    return "\n".join(lines)


def run_generation(
    papers_for_llm: List[Dict[str, Any]],
    topic: str,
    report_date: str,
    out_dir: Path,
) -> Dict[str, Any]:
    report_style = normalize_report_style(CONFIG.get("report_style", "科研日报"))
    prompt = build_prompt(papers_for_llm, topic=topic, report_date=report_date, report_style=report_style)

    raw_output = ""
    last_error = ""
    total_token_usage: Dict[str, Any] = {}

    for attempt in range(1, CONFIG["max_retry"] + 1):
        current_prompt = prompt if attempt == 1 else repair_prompt(
            raw_output,
            last_error,
            original_prompt=prompt,
            papers_for_llm=papers_for_llm,
        )

        llm_response = call_llm_chat(
            prompt=current_prompt,
            model=CONFIG["model"],
            temperature=CONFIG["temperature"],
            top_p=CONFIG["top_p"],
            num_predict=CONFIG["num_predict"],
            request_timeout_sec=CONFIG["ollama_request_timeout_sec"],
        )
        raw_output = safe_str(llm_response.get("content", ""))
        merge_token_usage(total_token_usage, llm_response.get("token_usage"))

        if CONFIG["save_debug_files"]:
            (out_dir / f"debug_attempt_{attempt}_prompt.txt").write_text(current_prompt, encoding="utf-8")
            (out_dir / f"debug_attempt_{attempt}_raw_output.txt").write_text(raw_output, encoding="utf-8")

        try:
            parsed = normalize_report_json(parse_json_output(raw_output))
            salvaged = salvage_report_json(parsed, papers_for_llm)
            ok, msg = validate_report_json(
                salvaged,
                expected_ref_count=len(papers_for_llm),
                papers_for_llm=papers_for_llm,
            )
            if ok:
                salvaged["token_usage"] = total_token_usage
                return salvaged
            last_error = msg
        except Exception as e:
            last_error = str(e)

        time.sleep(1)

    raise RuntimeError(f"模型输出多次校验失败，最后错误：{last_error}")


def generate_report_for_group(
    df: pd.DataFrame,
    topic: str,
    report_date: str,
    output_dir: Path,
    input_label: str,
    source_scope: str = "",
    logger: Callable[[str], None] | None = None,
) -> Dict[str, Any]:
    mode = normalize_report_input_mode(CONFIG.get("report_input_mode", "abstract_only"))
    max_papers = int(CONFIG["max_papers_for_llm"])
    candidate_limit = 0 if mode == "fulltext_only" else max_papers
    papers_for_llm = select_papers_for_llm(df, candidate_limit)
    if not papers_for_llm:
        raise RuntimeError(f"主题“{topic}”没有可用于生成报告的文献。")
    papers_for_llm = enrich_papers_with_fulltext_chunks(papers_for_llm)
    if mode == "fulltext_only":
        papers_for_llm = [paper for paper in papers_for_llm if paper.get("_fulltext_chunks")]
        papers_for_llm = papers_for_llm if max_papers <= 0 else papers_for_llm[:max_papers]
        if not papers_for_llm:
            raise RuntimeError("所选文献中没有已解析的全文证据，请先解析全文或切换证据范围")
    elif mode == "abstract_plus_fulltext":
        papers_for_llm = [
            paper for paper in papers_for_llm
            if normalize_whitespace(paper.get("abstract", "")) or paper.get("_fulltext_chunks")
        ]
        if not papers_for_llm:
            raise RuntimeError("所选文献中没有可用摘要或全文证据")

    group_output_dir = ensure_dir(output_dir / sanitize_filename(topic))

    report_data = run_generation(
        papers_for_llm=papers_for_llm,
        topic=topic,
        report_date=report_date,
        out_dir=group_output_dir,
    )

    report_data["references"] = build_references_from_papers(papers_for_llm)

    if not safe_str(report_data.get("topic", "")):
        report_data["topic"] = topic
    report_data["date"] = report_date
    report_data["data_source"] = guess_data_source_from_df(df)
    report_data["source_scope"] = source_scope or input_label
    report_data["model_name"] = CONFIG["model"]
    report_data["report_input_mode"] = normalize_report_input_mode(CONFIG.get("report_input_mode", "abstract_only"))
    report_data["fulltext_evidence_count"] = sum(
        len(paper.get("_fulltext_chunks", []))
        for paper in papers_for_llm
        if isinstance(paper.get("_fulltext_chunks"), list)
    )

    markdown_text = render_markdown(
        report_data,
        data_source=report_data["data_source"],
        model_name=report_data["model_name"],
        token_usage=report_data.get("token_usage"),
        title_topic=topic,
        report_date=report_data["date"],
    )

    file_stem = build_unique_report_file_stem(
        group_output_dir=group_output_dir,
        topic=topic,
        report_date=report_data["date"],
        report_style=report_data.get("report_style", CONFIG.get("report_style", "科研日报")),
    )
    json_path = group_output_dir / f"{file_stem}.json"
    md_path = group_output_dir / f"{file_stem}.md"

    json_path.write_text(json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown_text, encoding="utf-8")

    log_message("=" * 80, logger)
    log_message("科研日报生成完成", logger)
    log_message(f"文献范围: {source_scope or input_label}", logger)
    log_message(f"主题词: {topic}", logger)
    log_message(f"共读取文献数: {len(df)}", logger)
    log_message(f"送入模型文献数: {len(papers_for_llm)}", logger)
    log_message(f"报告输入模式: {report_input_mode_label(report_data['report_input_mode'])}", logger)
    log_message(f"全文证据片段数: {report_data['fulltext_evidence_count']}", logger)
    log_message(f"JSON 输出: {json_path.resolve()}", logger)
    log_message(f"Markdown 输出: {md_path.resolve()}", logger)
    log_message("=" * 80, logger)

    return {
        "topic": topic,
        "paper_count": len(df),
        "llm_count": len(papers_for_llm),
        "source_scope": source_scope or input_label,
        "json_path": json_path,
        "md_path": md_path,
    }


def generate_reports(
    input_csv: str | Path | None = None,
    output_dir: str | Path | None = None,
    config_overrides: Dict[str, Any] | None = None,
    report_date: str | None = None,
    logger: Callable[[str], None] | None = None,
    data_source: str = "csv",
    collection_id: str = "",
) -> List[Dict[str, Any]]:
    original_config = CONFIG.copy()
    overrides: Dict[str, Any] = {}
    if input_csv is not None:
        overrides["input_csv"] = str(input_csv)
    if output_dir is not None:
        overrides["output_dir"] = str(output_dir)
    if config_overrides:
        overrides.update(config_overrides)

    CONFIG.update(overrides)
    output_dir_path = ensure_dir(CONFIG["output_dir"])
    active_report_date = report_date or datetime.now().strftime("%Y-%m-%d")

    try:
        if (safe_str(CONFIG.get("llm_provider")) or "ollama") == "ollama":
            check_ollama_available(CONFIG["ollama_base_url"])

        active_source = normalize_report_data_source(data_source)
        source_input = input_csv if input_csv is not None else CONFIG.get("input_csv")
        df, source_label, input_csv_path = load_report_source(
            active_source,
            input_csv=source_input,
            collection_id=collection_id,
        )
        if len(df) == 0:
            raise RuntimeError("没有可用文献。请检查所选数据来源和证据范围。")

        groups = split_df_by_query(df)
        multiple_groups = len(groups) > 1
        topic_override = CONFIG["topic_override"].strip()

        if multiple_groups and topic_override:
            log_message("检测到多个主题词，已忽略 topic_override，改为按 query 分别生成报告。", logger)

        results = []
        for group_name, group_df in groups:
            topic = topic_override if topic_override and not multiple_groups else guess_topic_from_df(group_df)
            results.append(
                generate_report_for_group(
                    df=group_df,
                    topic=topic,
                    report_date=active_report_date,
                    output_dir=output_dir_path,
                    input_label=str(input_csv_path or source_label),
                    source_scope=source_label,
                    logger=logger,
                )
            )

        log_message(f"本次共生成 {len(results)} 份报告。", logger)
        return results
    finally:
        if not CONFIG["save_debug_files"]:
            removed = cleanup_debug_files_recursive(output_dir_path)
            if removed:
                log_message(f"已清理 debug 文件: {removed} 个", logger)
        CONFIG.clear()
        CONFIG.update(original_config)


def main() -> None:
    generate_reports()


if __name__ == "__main__":
    main()
