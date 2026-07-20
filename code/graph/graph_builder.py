#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import logging
import re
import sqlite3
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .edge_weight import weighted_edges_from_triplets
from .graph_filter import prune_edges
from .graph_layout import apply_psp_layout
from .llm_triplet_extractor import extract_triplets_with_llm, llm_enabled
from .node_classifier import NODE_TYPE_COLORS, NODE_TYPE_LABELS, extract_typed_terms, normalize_term
from .quantitative_extractor import extract_quantitative_terms
from .structure_refiner import extract_specific_structures
from .triplet_extractor import extract_psp_triplets
from .visualizer import build_psp_caption, build_psp_path_details

logger = logging.getLogger(__name__)

GENERIC_STRUCTURE_TERMS = {"microstructure", "microstructure evolution", "phase", "grain"}
GENERIC_MATERIAL_TERMS = {"alloy", "material", "materials", "composite"}

GRAPH_INPUT_ABSTRACT = "abstract"
GRAPH_INPUT_CHUNKS = "chunks"
GRAPH_INPUT_ABSTRACT_CHUNKS = "abstract_chunks"
PREFERRED_CHUNK_SECTIONS = ("methods", "results", "discussion")
SKIPPED_CHUNK_SECTIONS = {
    "references",
    "reference",
    "bibliography",
    "acknowledgements",
    "acknowledgments",
    "funding",
    "supplementary",
}
MARKDOWN_PATH_COLUMNS = (
    "markdown_path",
    "md_path",
    "fulltext_markdown_path",
    "fulltext_md_path",
    "parsed_markdown_path",
    "parsed_md_path",
    "fulltext_path",
)


def graph_int_config(config: dict | None, key: str, default: int, min_value: int, max_value: int) -> int:
    try:
        value = int((config or {}).get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(min_value, min(max_value, value))


def normalize_graph_input_source(value: object) -> str:
    normalized = str(value or GRAPH_INPUT_ABSTRACT).strip().lower().replace("-", "_").replace("+", "_")
    normalized = re.sub(r"\s+", "_", normalized)
    aliases = {
        "summary": GRAPH_INPUT_ABSTRACT,
        "abstract": GRAPH_INPUT_ABSTRACT,
        "fulltext": GRAPH_INPUT_CHUNKS,
        "full_text": GRAPH_INPUT_CHUNKS,
        "chunk": GRAPH_INPUT_CHUNKS,
        "chunks": GRAPH_INPUT_CHUNKS,
        "fulltext_chunks": GRAPH_INPUT_CHUNKS,
        "full_text_chunks": GRAPH_INPUT_CHUNKS,
        "abstract_chunks": GRAPH_INPUT_ABSTRACT_CHUNKS,
        "summary_chunks": GRAPH_INPUT_ABSTRACT_CHUNKS,
        "abstract_fulltext": GRAPH_INPUT_ABSTRACT_CHUNKS,
        "abstract_full_text": GRAPH_INPUT_ABSTRACT_CHUNKS,
        "abstract_fulltext_chunks": GRAPH_INPUT_ABSTRACT_CHUNKS,
        "abstract_full_text_chunks": GRAPH_INPUT_ABSTRACT_CHUNKS,
        "summary_fulltext": GRAPH_INPUT_ABSTRACT_CHUNKS,
        "summary_full_text": GRAPH_INPUT_ABSTRACT_CHUNKS,
    }
    return aliases.get(normalized, GRAPH_INPUT_ABSTRACT)


def clean_graph_field(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def paper_identity_candidates(row: pd.Series) -> list[str]:
    candidates: list[str] = []
    identity_key = clean_graph_field(row.get("identity_key", ""))
    doi = clean_graph_field(row.get("doi", "")).lower()
    title = normalize_title_key(clean_graph_field(row.get("title", "")))
    source = clean_graph_field(row.get("source", ""))
    paper_id = clean_graph_field(row.get("paperId", ""))
    if identity_key:
        candidates.append(identity_key)
    if doi:
        candidates.append(f"doi:{doi}")
    if title:
        candidates.append(f"title:{title}")
    if source and paper_id:
        candidates.append(f"source:{source}:{paper_id}")
    return candidates


def find_library_db_path(csv_path: Path, project_dir: Path) -> Path | None:
    candidates = [
        csv_path.parent / "literature_library.sqlite",
        csv_path.parent.parent / "literature_library.sqlite",
        project_dir / "Literature_search_results" / "literature_library.sqlite",
        project_dir / "LiterNexus_outputs" / "literature" / "literature_library.sqlite",
        project_dir / "ScholarFlow_outputs" / "literature" / "literature_library.sqlite",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def normalize_title_key(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(title or "").lower())).strip()


def resolve_project_or_dataset_path(raw_path: object, project_dir: Path, dataset_dir: Path) -> Path | None:
    text = clean_graph_field(raw_path)
    if not text:
        return None
    path = Path(text).expanduser()
    candidates = [path] if path.is_absolute() else [project_dir / path, dataset_dir / path]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else None


def markdown_candidates_from_document_path(path: Path) -> list[Path]:
    return [
        path.with_suffix(".md"),
        path.with_suffix(".markdown"),
        path.parent / f"{path.name}.md",
        path.parent / f"{path.name}.markdown",
        path.parent / f"{path.stem}.md",
        path.parent / f"{path.stem}.markdown",
    ]


def find_markdown_path_for_row(row: pd.Series, csv_path: Path, project_dir: Path) -> Path | None:
    dataset_dir = csv_path.parent
    for column in MARKDOWN_PATH_COLUMNS:
        candidate = resolve_project_or_dataset_path(row.get(column, ""), project_dir, dataset_dir)
        if candidate and candidate.suffix.lower() in {".md", ".markdown"} and candidate.exists():
            return candidate

    db_path = find_library_db_path(csv_path, project_dir)
    if db_path and db_path.exists():
        identity_keys = paper_identity_candidates(row)
        try:
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1) as conn:
                for identity_key in identity_keys:
                    result = conn.execute(
                        "SELECT pdf_path FROM paper_documents WHERE identity_key = ? AND pdf_path != ''",
                        (identity_key,),
                    ).fetchone()
                    if not result:
                        continue
                    pdf_path = resolve_project_or_dataset_path(result[0], project_dir, dataset_dir)
                    if not pdf_path:
                        continue
                    for candidate in markdown_candidates_from_document_path(pdf_path):
                        if candidate.exists() and candidate.suffix.lower() in {".md", ".markdown"}:
                            return candidate
        except sqlite3.Error as exc:
            logger.debug("读取全文 markdown 路径失败: %s", exc)

    for column in ("pdf_path", "document_path"):
        pdf_path = resolve_project_or_dataset_path(row.get(column, ""), project_dir, dataset_dir)
        if not pdf_path:
            continue
        for candidate in markdown_candidates_from_document_path(pdf_path):
            if candidate.exists() and candidate.suffix.lower() in {".md", ".markdown"}:
                return candidate
    return None


def database_chunks_for_row(
    row: pd.Series,
    row_index: int,
    csv_path: Path,
    project_dir: Path,
    max_chunks_per_paper: int,
) -> list[dict[str, Any]]:
    db_path = find_library_db_path(csv_path, project_dir)
    if not db_path:
        return []
    identity_keys = paper_identity_candidates(row)
    if not identity_keys:
        return []

    placeholders = ",".join("?" for _ in identity_keys)
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT pc.identity_key, pc.chunk_id, pc.section_title, pc.page_start, pc.page_end,
                       pc.chunk_text, pc.chunk_index,
                       COALESCE(pc.chunk_type, 'body') AS chunk_type,
                       COALESCE(pc.page_mapping_confidence, 0) AS page_mapping_confidence,
                       COALESCE(pf.parse_quality, 'warning') AS parse_quality,
                       COALESCE(pf.page_mapping_coverage, 0) AS page_mapping_coverage
                FROM paper_chunks AS pc
                LEFT JOIN paper_fulltext AS pf ON pf.identity_key = pc.identity_key
                WHERE pc.identity_key IN ({placeholders})
                  AND COALESCE(pc.chunk_text, '') != ''
                ORDER BY pc.chunk_index ASC
                """,
                identity_keys,
            ).fetchall()
    except sqlite3.Error as exc:
        logger.debug("读取全文 chunks 失败: %s", exc)
        return []

    paper_id = clean_graph_field(row.get("paperId", "")) or clean_graph_field(row.get("doi", "")) or str(row_index)
    chunks: list[dict[str, Any]] = []
    for item in rows:
        section_title = clean_graph_field(item["section_title"]) or "full text"
        if should_skip_section(section_title):
            continue
        text = clean_markdown_text(item["chunk_text"])
        if len(text) < 80:
            continue
        bucket = section_bucket(section_title)
        chunks.append({
            "text": text,
            "paper_id": paper_id,
            "paper_index": int(row_index),
            "section": bucket,
            "section_title": section_title,
            "page": format_page_reference(item["page_start"], item["page_end"]),
            "source": "fulltext_chunk",
            "markdown_path": "",
            "identity_key": item["identity_key"],
            "chunk_id": item["chunk_id"],
            "chunk_type": item["chunk_type"],
            "page_mapping_confidence": float(item["page_mapping_confidence"] or 0),
            "parse_quality": clean_graph_field(item["parse_quality"]) or "warning",
            "page_mapping_coverage": float(item["page_mapping_coverage"] or 0),
            "priority": PREFERRED_CHUNK_SECTIONS.index(bucket)
            if bucket in PREFERRED_CHUNK_SECTIONS
            else len(PREFERRED_CHUNK_SECTIONS),
        })

    chunks.sort(key=lambda item: (item["priority"], page_sort_value(item.get("page")), len(item["text"])))
    return chunks[:max_chunks_per_paper]


def format_page_reference(page_start: object, page_end: object = None) -> str:
    start = clean_graph_field(page_start)
    end = clean_graph_field(page_end)
    if not start:
        return ""
    if end and end != start:
        return f"{start}-{end}"
    return start


def page_sort_value(value: object) -> int:
    match = re.search(r"\d+", clean_graph_field(value))
    return int(match.group(0)) if match else 999999


def normalize_section_title(title: str) -> str:
    title = re.sub(r"^\d+(?:\.\d+)*\s*", "", str(title or "").strip().lower())
    title = re.sub(r"[^a-z0-9\s/&-]+", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def section_bucket(title: str) -> str:
    normalized = normalize_section_title(title)
    if any(name in normalized for name in ("method", "material and method", "experimental", "experiment", "methodology")):
        return "methods"
    if any(name in normalized for name in ("result", "finding")):
        return "results"
    if "discussion" in normalized:
        return "discussion"
    if any(name in normalized for name in SKIPPED_CHUNK_SECTIONS):
        return "references"
    return normalized or "full text"


def should_skip_section(title: str) -> bool:
    bucket = section_bucket(title)
    normalized = normalize_section_title(title)
    return bucket in SKIPPED_CHUNK_SECTIONS or any(name == normalized or normalized.startswith(f"{name} ") for name in SKIPPED_CHUNK_SECTIONS)


def extract_page_marker(line: str) -> int | None:
    patterns = (
        r"<!--\s*page\s*[:= ]\s*(\d+)\s*-->",
        r"^\s*(?:page|p\.)\s+(\d+)\s*$",
        r"^\s*[-–—]?\s*(\d+)\s*[-–—]?\s*$",
    )
    for pattern in patterns:
        match = re.search(pattern, line, flags=re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
    return None


def split_markdown_sections(markdown_text: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current = {"section": "full text", "page": None, "lines": []}
    for line in str(markdown_text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        page = extract_page_marker(line)
        if page is not None:
            current["page"] = page
            continue
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
        if heading:
            if current["lines"]:
                sections.append(current)
            current = {"section": heading.group(1).strip(), "page": current.get("page"), "lines": []}
            continue
        current["lines"].append(line)
    if current["lines"]:
        sections.append(current)
    return sections


def clean_markdown_text(text: str) -> str:
    text = re.sub(r"```.*?```", " ", str(text or ""), flags=re.DOTALL)
    text = re.sub(r"!\[[^\]]*]\([^)]+\)", " ", text)
    text = re.sub(r"\[[^\]]+]\([^)]+\)", lambda match: match.group(0).split("](", 1)[0].lstrip("["), text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def chunk_section_text(text: str, max_chars: int = 2400) -> list[str]:
    paragraphs = [clean_markdown_text(part) for part in re.split(r"\n\s*\n", str(text or ""))]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) < 80:
            continue
        if current and len(current) + len(paragraph) + 2 > max_chars:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}".strip() if current else paragraph
    if current:
        chunks.append(current)
    return chunks


def markdown_chunks_for_row(
    row: pd.Series,
    row_index: int,
    csv_path: Path,
    project_dir: Path,
    max_chunks_per_paper: int,
) -> list[dict[str, Any]]:
    database_chunks = database_chunks_for_row(row, row_index, csv_path, project_dir, max_chunks_per_paper)
    if database_chunks:
        return database_chunks

    markdown_path = find_markdown_path_for_row(row, csv_path, project_dir)
    if not markdown_path:
        return []
    try:
        markdown_text = markdown_path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.debug("读取全文 markdown 失败 (%s): %s", markdown_path, exc)
        return []

    paper_id = clean_graph_field(row.get("paperId", "")) or clean_graph_field(row.get("doi", "")) or str(row_index)
    chunks: list[dict[str, Any]] = []
    for section in split_markdown_sections(markdown_text):
        section_title = clean_graph_field(section.get("section", "")) or "full text"
        if should_skip_section(section_title):
            continue
        for text in chunk_section_text("\n".join(section.get("lines", []))):
            chunks.append({
                "text": text,
                "paper_id": paper_id,
                "paper_index": int(row_index),
                "section": section_bucket(section_title),
                "section_title": section_title,
                "page": section.get("page") or "",
                "source": "fulltext_chunk",
                "markdown_path": str(markdown_path),
                "chunk_id": "",
                "chunk_type": "body",
                "page_mapping_confidence": 1.0 if section.get("page") else 0.0,
                "parse_quality": "unknown",
                "page_mapping_coverage": 0.0,
                "priority": PREFERRED_CHUNK_SECTIONS.index(section_bucket(section_title))
                if section_bucket(section_title) in PREFERRED_CHUNK_SECTIONS
                else len(PREFERRED_CHUNK_SECTIONS),
            })

    chunks.sort(key=lambda item: (item["priority"], len(item["text"])), reverse=False)
    return chunks[:max_chunks_per_paper]


def abstract_chunk_for_row(row: pd.Series, row_index: int) -> dict[str, Any]:
    paper_id = clean_graph_field(row.get("paperId", "")) or clean_graph_field(row.get("doi", "")) or str(row_index)
    text_columns = [col for col in ["query", "title", "abstract", "venue", "authors"] if col in row.index]
    return {
        "text": " ".join(str(row.get(col, "") or "") for col in text_columns),
        "paper_id": paper_id,
        "paper_index": int(row_index),
        "section": "abstract",
        "section_title": "Abstract",
        "page": "",
        "source": "abstract",
        "markdown_path": "",
        "chunk_id": "",
        "chunk_type": "abstract",
        "page_mapping_confidence": 0.0,
        "parse_quality": "metadata",
        "page_mapping_coverage": 0.0,
    }


def graph_text_units_for_row(
    row: pd.Series,
    row_index: int,
    csv_path: Path,
    project_dir: Path,
    input_source: str,
    max_chunks_per_paper: int,
    fallback_abstract_for_missing_chunks: bool = False,
) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    if input_source in {GRAPH_INPUT_ABSTRACT, GRAPH_INPUT_ABSTRACT_CHUNKS}:
        abstract_unit = abstract_chunk_for_row(row, row_index)
        if abstract_unit["text"].strip():
            units.append(abstract_unit)
    if input_source in {GRAPH_INPUT_CHUNKS, GRAPH_INPUT_ABSTRACT_CHUNKS}:
        chunk_units = markdown_chunks_for_row(row, row_index, csv_path, project_dir, max_chunks_per_paper)
        units.extend(chunk_units)
        if (
            input_source == GRAPH_INPUT_CHUNKS
            and fallback_abstract_for_missing_chunks
            and not chunk_units
        ):
            abstract_unit = abstract_chunk_for_row(row, row_index)
            if abstract_unit["text"].strip():
                abstract_unit["source"] = "abstract_fallback"
                units.append(abstract_unit)
    return units


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


def count_auto_tokens(text: str) -> Counter:
    import re

    stop_words = {
        "the", "and", "for", "with", "from", "that", "this", "were", "are", "was", "into",
        "using", "during", "after", "before", "study", "paper", "result", "results",
        "based", "effect", "effects", "properties", "behavior", "performance",
        "high", "hot", "novel", "good", "prepared", "different", "mechanical",
    }
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", str(text or "").lower())
    return Counter(token for token in tokens if token not in stop_words)


def quantitative_parent_node(term: str, category: str) -> str:
    if category != "STRUCTURE":
        return ""
    normalized = str(term or "").casefold()
    if normalized.startswith("grain size"):
        return "grain"
    if "precipitate" in normalized or "particle size" in normalized:
        return "precipitation"
    if "thickness" in normalized:
        return "interface"
    return "microstructure"


def pagerank(nodes: list[str], edges: list[dict], iterations: int = 30, damping: float = 0.85) -> dict[str, float]:
    if not nodes:
        return {}
    node_set = set(nodes)
    rank = {node: 1 / len(nodes) for node in nodes}
    outgoing: defaultdict[str, list[tuple[str, float]]] = defaultdict(list)
    for edge in edges:
        if edge["source"] in node_set and edge["target"] in node_set:
            outgoing[edge["source"]].append((edge["target"], float(edge.get("weight", 0.2))))

    for _ in range(iterations):
        next_rank = {node: (1 - damping) / len(nodes) for node in nodes}
        for source in nodes:
            total_weight = sum(weight for _, weight in outgoing.get(source, []))
            if not total_weight:
                continue
            for target, weight in outgoing[source]:
                next_rank[target] += damping * rank[source] * (weight / total_weight)
        rank = next_rank
    return rank


def relative_project_path(path: Path, project_dir: Path) -> str:
    try:
        return str(path.relative_to(project_dir))
    except ValueError:
        return str(path)


def edge_key(edge: dict) -> tuple[str, str, str]:
    return (edge["source"], edge["target"], edge.get("relation", ""))


def evidence_quality_score(unit: dict) -> float:
    parse_scores = {
        "good": 1.0,
        "warning": 0.7,
        "poor": 0.35,
        "unknown": 0.5,
        "metadata": 0.6,
    }
    parse_score = parse_scores.get(clean_graph_field(unit.get("parse_quality", "")).lower(), 0.5)
    try:
        mapping_confidence = max(0.0, min(1.0, float(unit.get("page_mapping_confidence", 0) or 0)))
    except (TypeError, ValueError):
        mapping_confidence = 0.0
    if unit.get("source") == "abstract":
        return round(parse_score, 3)
    return round((0.7 * parse_score) + (0.3 * mapping_confidence), 3)


def normalized_evidence_text(value: object) -> str:
    return re.sub(r"\s+", " ", clean_graph_field(value)).casefold()


def append_edge_evidence(edge_evidence: defaultdict[tuple[str, str], list[dict]], triplet: dict, unit: dict) -> None:
    key = (triplet["subject"], triplet["object"])
    evidence_text = clean_graph_field(triplet.get("evidence", "")) or clean_graph_field(unit.get("text", ""))
    evidence = {
        "paper_id": clean_graph_field(triplet.get("paper_id", "")) or clean_graph_field(unit.get("paper_id", "")),
        "section": clean_graph_field(triplet.get("section", "")) or clean_graph_field(unit.get("section", "")),
        "page": clean_graph_field(triplet.get("page", "")) or clean_graph_field(unit.get("page", "")),
        "evidence_text": evidence_text[:700],
        "chunk_id": clean_graph_field(unit.get("chunk_id", "")),
        "page_mapping_confidence": round(float(unit.get("page_mapping_confidence", 0) or 0), 3),
        "parse_quality": clean_graph_field(unit.get("parse_quality", "")) or "unknown",
        "evidence_quality": evidence_quality_score(unit),
    }
    if not evidence["evidence_text"]:
        return
    existing = edge_evidence[key]
    evidence_key = normalized_evidence_text(evidence["evidence_text"])
    duplicate = any(
        item.get("paper_id") == evidence["paper_id"]
        and item.get("section") == evidence["section"]
        and normalized_evidence_text(item.get("evidence_text")) == evidence_key
        for item in existing
    )
    if not duplicate:
        existing.append(evidence)
        existing.sort(
            key=lambda item: (
                float(item.get("evidence_quality", 0)),
                bool(item.get("page")),
                len(item.get("evidence_text", "")),
            ),
            reverse=True,
        )
        del existing[5:]


def attach_evidence_to_edges(edges: list[dict], edge_evidence: defaultdict[tuple[str, str], list[dict]]) -> list[dict]:
    for edge in edges:
        evidence = edge_evidence.get((edge["source"], edge["target"]), [])
        edge["evidence"] = evidence
        if evidence:
            first = evidence[0]
            edge["paper_id"] = first.get("paper_id", "")
            edge["section"] = first.get("section", "")
            edge["page"] = first.get("page", "")
            edge["evidence_text"] = first.get("evidence_text", "")
        else:
            edge.setdefault("paper_id", "")
            edge.setdefault("section", "")
            edge.setdefault("page", "")
            edge.setdefault("evidence_text", "")
    return edges


def ensure_material_anchor_edges(
    filtered_edges: list[dict],
    raw_edges: list[dict],
    node_categories: dict[str, str],
    max_edges: int,
) -> list[dict]:
    active_nodes = {edge["source"] for edge in filtered_edges} | {edge["target"] for edge in filtered_edges}
    if not active_nodes:
        return filtered_edges

    existing = {edge_key(edge) for edge in filtered_edges}
    anchored_targets = {
        edge["target"]
        for edge in filtered_edges
        if node_categories.get(edge["source"]) == "MATERIAL"
    }
    candidates = [
        edge for edge in raw_edges
        if node_categories.get(edge["source"]) == "MATERIAL"
        and node_categories.get(edge["target"]) in {"PROCESS", "STRUCTURE", "PROPERTY"}
        and edge["target"] in active_nodes
        and edge["target"] not in anchored_targets
        and edge_key(edge) not in existing
    ]
    candidates.sort(
        key=lambda edge: (
            int(edge.get("frequency", 0)),
            float(edge.get("weight", 0)),
            {"PROCESS": 2, "STRUCTURE": 1, "PROPERTY": 0}.get(node_categories.get(edge["target"]), 0),
        ),
        reverse=True,
    )

    result = list(filtered_edges)
    for edge in candidates:
        if len(result) >= max_edges:
            break
        anchor_edge = dict(edge)
        anchor_edge["anchor_edge"] = True
        anchor_edge["weight"] = max(0.22, float(anchor_edge.get("weight", 0)))
        result.append(anchor_edge)
        existing.add(edge_key(anchor_edge))
        anchored_targets.add(anchor_edge["target"])
    return result


def ensure_specific_structure_edges(
    filtered_edges: list[dict],
    raw_edges: list[dict],
    node_metadata: dict[str, dict],
    node_categories: dict[str, str],
    max_edges: int,
) -> list[dict]:
    specific_terms = {
        term for term, metadata in node_metadata.items()
        if metadata.get("specificity") == "specific"
    }
    if not specific_terms:
        return filtered_edges

    existing = {edge_key(edge) for edge in filtered_edges}
    candidates = [
        edge for edge in raw_edges
        if edge_key(edge) not in existing
        and (edge["source"] in specific_terms or edge["target"] in specific_terms)
        and (
            node_categories.get(edge["source"]) == "MATERIAL"
            or node_categories.get(edge["source"]) == "PROCESS"
            or node_categories.get(edge["target"]) == "PROPERTY"
        )
    ]
    candidates.sort(
        key=lambda edge: (
            edge["source"] in specific_terms,
            int(edge.get("frequency", 0)),
            float(edge.get("weight", 0)),
        ),
        reverse=True,
    )

    result = list(filtered_edges)
    per_structure: Counter = Counter()
    for edge in candidates:
        structure = edge["source"] if edge["source"] in specific_terms else edge["target"]
        if per_structure[structure] >= 3:
            continue
        if len(result) >= max_edges:
            break
        detail_edge = dict(edge)
        detail_edge["structure_detail_edge"] = True
        detail_edge["weight"] = max(0.24, float(detail_edge.get("weight", 0)))
        result.append(detail_edge)
        existing.add(edge_key(detail_edge))
        per_structure[structure] += 1
    return result


def has_specific_child(term: str, node_metadata: dict[str, dict], connected_terms: set[str]) -> bool:
    normalized = str(term or "").strip().lower()
    if normalized not in GENERIC_STRUCTURE_TERMS:
        return False
    return any(
        metadata.get("specificity") == "specific"
        and str(metadata.get("parent_node") or "").strip().lower() == normalized
        and child in connected_terms
        for child, metadata in node_metadata.items()
    )


def has_specific_alloy_term(terms: list[tuple[str, str]]) -> bool:
    return any(
        node_type == "MATERIAL"
        and (key := str(term or "").strip().lower()) != "alloy"
        and ("alloy" in key or key in {"niti", "ti-nb", "ti nb", "β-ti", "beta-ti"})
        for term, node_type in terms
    )


def suppress_generic_material_terms(
    terms: list[tuple[str, str]],
    specific_alloy_in_context: bool = False,
) -> list[tuple[str, str]]:
    material_terms = [term for term, node_type in terms if node_type == "MATERIAL"]
    material_keys = {term.strip().lower() for term in material_terms}
    has_specific_material = any(key not in GENERIC_MATERIAL_TERMS for key in material_keys)
    has_specific_alloy = specific_alloy_in_context or has_specific_alloy_term(terms)
    has_specific_composite = any(
        key not in {"composite", "composites"} and "composite" in key
        for key in material_keys
    )

    result: list[tuple[str, str]] = []
    for term, node_type in terms:
        key = str(term or "").strip().lower()
        if node_type == "MATERIAL" and key in {"material", "materials"} and has_specific_material:
            continue
        if node_type == "MATERIAL" and key == "alloy" and (has_specific_alloy or has_specific_material):
            continue
        if node_type == "MATERIAL" and key == "composite" and has_specific_composite:
            continue
        result.append((term, node_type))
    return result


def build_psp_knowledge_graph(
    csv_path: Path,
    project_dir: Path,
    max_nodes: int = 36,
    max_edges: int = 80,
    mode: str = "rule",
    llm_config: dict | None = None,
    progress_callback: Callable[[int, str | None], None] | None = None,
    input_source: str | None = None,
    max_chunks_per_paper: int | None = None,
) -> dict:
    def emit_progress(progress: int, message: str | None = None) -> None:
        if message:
            logger.info(message)
        if progress_callback:
            progress_callback(max(0, min(100, int(progress))), message)

    emit_progress(5, f"知识图谱读取数据集: {csv_path.name}")
    df = pd.read_csv(csv_path)
    dataset = relative_project_path(csv_path, project_dir)
    if df.empty:
        return {
            "graph_type": "PSP_DIRECTED",
            "dataset": dataset,
            "paper_count": 0,
            "nodes": [],
            "edges": [],
            "triplets": [],
            "top_terms": [],
            "message": "CSV 中没有可分析的文献。",
        }

    input_source = normalize_graph_input_source(
        input_source
        or (llm_config or {}).get("graph_input_source")
        or (llm_config or {}).get("input_source")
        or GRAPH_INPUT_ABSTRACT
    )
    max_chunks_per_paper = (
        graph_int_config(llm_config, "max_chunks_per_paper", 20, 1, 20)
        if max_chunks_per_paper is None
        else max(1, min(20, int(max_chunks_per_paper)))
    )
    fallback_abstract_for_missing_chunks = str(
        (llm_config or {}).get("fallback_abstract_for_missing_chunks", "1")
    ).strip().lower() not in {"0", "false", "no", "off"}

    text_columns = [col for col in ["query", "title", "abstract", "venue", "authors"] if col in df.columns]
    if not text_columns and input_source == GRAPH_INPUT_ABSTRACT:
        return {
            "graph_type": "PSP_DIRECTED",
            "dataset": dataset,
            "paper_count": int(len(df)),
            "nodes": [],
            "edges": [],
            "triplets": [],
            "top_terms": [],
            "message": "CSV 缺少 query/title/abstract/venue/authors 等可分析字段。",
        }

    node_counts: Counter = Counter()
    node_unit_counts: Counter = Counter()
    node_categories: dict[str, str] = {}
    node_metadata: defaultdict[str, dict] = defaultdict(dict)
    structure_refinement_counts: Counter = Counter()
    structure_refinement_papers: defaultdict[str, list[str]] = defaultdict(list)
    triplet_counts: Counter = Counter()
    relation_counts: defaultdict[tuple[str, str], Counter] = defaultdict(Counter)
    paper_details: defaultdict[str, list[dict]] = defaultdict(list)
    paper_keys: defaultdict[str, set[str]] = defaultdict(set)
    edge_evidence: defaultdict[tuple[str, str], list[dict]] = defaultdict(list)
    triplet_samples: list[dict] = []

    analyzed = df.head(500)
    use_llm = str(mode or "rule").lower() in {"llm", "hybrid"} and llm_enabled(llm_config)
    emit_progress(12, f"知识图谱开始规则抽取: {len(analyzed)} 篇文献")

    # ---- 第一阶段：逐行规则抽取（纯本地，快），同时收集需要 LLM 的任务 ----
    rule_rows: list[tuple[int, int, str, list[tuple[str, str]], dict]] = []
    fulltext_chunk_count = 0
    missing_fulltext_count = 0
    fallback_abstract_count = 0
    unit_index = 0
    for row_index, row in analyzed.iterrows():
        units = graph_text_units_for_row(
            row=row,
            row_index=int(row_index),
            csv_path=csv_path,
            project_dir=project_dir,
            input_source=input_source,
            max_chunks_per_paper=max_chunks_per_paper,
            fallback_abstract_for_missing_chunks=fallback_abstract_for_missing_chunks,
        )
        if input_source in {GRAPH_INPUT_CHUNKS, GRAPH_INPUT_ABSTRACT_CHUNKS}:
            chunk_units = [unit for unit in units if unit.get("source") == "fulltext_chunk"]
            fallback_units = [unit for unit in units if unit.get("source") == "abstract_fallback"]
            fulltext_chunk_count += len(chunk_units)
            fallback_abstract_count += len(fallback_units)
            if not chunk_units:
                missing_fulltext_count += 1
        for unit in units:
            text = clean_graph_field(unit.get("text", ""))
            if not text:
                continue
            auto_terms = [word for word, count in count_auto_tokens(text).most_common(10) if count > 0]
            unique_terms = extract_typed_terms(text, auto_terms=auto_terms)
            quantitative_terms = extract_quantitative_terms(text)
            unique_terms.extend(quantitative_terms)
            for term, category in quantitative_terms:
                node_metadata[term].update({
                    "specificity": "quantitative",
                    "parent_node": quantitative_parent_node(term, category),
                })
            for structure in extract_specific_structures(text):
                unique_terms.append((structure["term"], "STRUCTURE"))
                node_metadata[structure["term"]].update({
                    "parent_node": structure.get("parent_node", "microstructure"),
                    "specificity": structure.get("specificity", "specific"),
                })
                structure_refinement_counts[structure["term"]] += 1
                title = clean_graph_field(row.get("title", ""))
                if title and len(structure_refinement_papers[structure["term"]]) < 3:
                    structure_refinement_papers[structure["term"]].append(title)
            unique_terms = deduplicate_terms(unique_terms)
            unique_terms = suppress_generic_material_terms(unique_terms)
            if not unique_terms:
                continue
            rule_rows.append((unit_index, int(row_index), text, unique_terms, unit))
            unit_index += 1
    if input_source in {GRAPH_INPUT_CHUNKS, GRAPH_INPUT_ABSTRACT_CHUNKS}:
        emit_progress(
            20,
            f"全文 chunk 载入完成: {fulltext_chunk_count} 个 chunks，{missing_fulltext_count} 篇未找到全文 chunks/markdown，{fallback_abstract_count} 篇使用摘要兜底",
        )
    papers_with_specific_alloy = {
        row_index
        for _unit_index, row_index, _text, terms, _unit in rule_rows
        if has_specific_alloy_term(terms)
    }
    rule_rows = [
        (
            unit_idx,
            row_index,
            text,
            suppress_generic_material_terms(
                terms,
                specific_alloy_in_context=row_index in papers_with_specific_alloy,
            ),
            unit,
        )
        for unit_idx, row_index, text, terms, unit in rule_rows
    ]
    emit_progress(25, f"知识图谱规则抽取完成: {len(rule_rows)} 个文本单元进入候选集")

    # ---- 第二阶段：并发调用 LLM 抽取三元组 ----
    llm_results: dict[int, list[dict]] = {}
    if use_llm and rule_rows:
        max_workers = graph_int_config(llm_config, "llm_max_workers", 3, 1, 6)
        max_text_units = graph_int_config(
            llm_config,
            "llm_max_text_units",
            graph_int_config(llm_config, "llm_max_papers", 30, 1, 120),
            1,
            240,
        )
        llm_tasks = sorted(rule_rows, key=lambda item: len(item[3]), reverse=True)[:max_text_units]
        total = len(llm_tasks)
        emit_progress(28, f"知识图谱 LLM 抽取开始: 共 {total}/{len(rule_rows)} 个文本单元，并发={max_workers}")
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(
                    extract_triplets_with_llm,
                    text=text,
                    candidate_terms=terms,
                    config=llm_config,
                    paper_index=row_idx,
                ): unit_idx
                for unit_idx, row_idx, text, terms, _unit in llm_tasks
            }
            done = 0
            for future in as_completed(futures):
                unit_idx = futures[future]
                try:
                    llm_results[unit_idx] = future.result()
                except Exception as exc:
                    logger.warning("LLM 抽取 future 异常 (unit_index=%s): %s", unit_idx, exc)
                    llm_results[unit_idx] = []
                done += 1
                if done % 5 == 0 or done == total:
                    progress = 28 + round((done / max(1, total)) * 42)
                    emit_progress(progress, f"知识图谱 LLM 抽取进度: {done}/{total}")
    else:
        emit_progress(55, "知识图谱使用规则 PSP 构图")

    # ---- 第三阶段：汇总节点 / 三元组 / 边 ----
    emit_progress(72, "知识图谱开始计算有向边权重与降噪")
    for unit_idx, row_index, text, unique_terms, unit in rule_rows:
        row = analyzed.loc[row_index]
        llm_triplets = llm_results.get(unit_idx, [])
        if llm_triplets:
            for triplet in llm_triplets:
                triplet["paper_id"] = unit.get("paper_id", "")
                triplet["section"] = unit.get("section", "")
                triplet["page"] = unit.get("page", "")
                unique_terms.append((triplet["subject"], triplet["subject_type"]))
                unique_terms.append((triplet["object"], triplet["object_type"]))
            unique_terms = deduplicate_terms(unique_terms)
            unique_terms = suppress_generic_material_terms(unique_terms)

        detail = graph_paper_detail(row, int(row_index))
        paper_key = detail.get("doi") or detail.get("paperId") or detail.get("title") or str(row_index)
        for term, category in unique_terms:
            node_unit_counts[term] += 1
            node_categories.setdefault(term, category)
            if paper_key not in paper_keys[term]:
                paper_keys[term].add(paper_key)
                node_counts[term] += 1
                if detail["title"]:
                    paper_details[term].append(detail)

        triplets = extract_psp_triplets(unique_terms, int(row_index))
        if llm_triplets:
            triplets.extend(llm_triplets)
        for triplet in triplets:
            triplet.setdefault("paper_id", unit.get("paper_id", ""))
            triplet.setdefault("section", unit.get("section", ""))
            triplet.setdefault("page", unit.get("page", ""))
            triplet.setdefault("evidence", clean_graph_field(unit.get("text", ""))[:500])
            key = (triplet["subject"], triplet["object"])
            triplet_counts[key] += 1
            relation_counts[key][triplet["relation"]] += 1
            append_edge_evidence(edge_evidence, triplet, unit)
            if len(triplet_samples) < 80:
                triplet_samples.append(triplet)

    raw_edges = weighted_edges_from_triplets(
        triplet_counts=triplet_counts,
        node_counts=node_unit_counts,
        relation_counts=relation_counts,
        total_documents=max(1, len(rule_rows)),
    )
    attach_evidence_to_edges(raw_edges, edge_evidence)
    min_weight = 0.2
    min_frequency = 2
    top_k_neighbors = 5
    filtered_edges = prune_edges(raw_edges, min_weight=min_weight, min_frequency=min_frequency, top_k=top_k_neighbors)[:max_edges]
    if not filtered_edges and raw_edges:
        min_weight = 0.12
        min_frequency = 1
        top_k_neighbors = 7
        filtered_edges = prune_edges(raw_edges, min_weight=min_weight, min_frequency=min_frequency, top_k=top_k_neighbors)[:max_edges]
    filtered_edges = ensure_material_anchor_edges(filtered_edges, raw_edges, node_categories, max_edges)
    filtered_edges = ensure_specific_structure_edges(filtered_edges, raw_edges, node_metadata, node_categories, max_edges)
    attach_evidence_to_edges(filtered_edges, edge_evidence)
    connected_terms = {edge["source"] for edge in filtered_edges} | {edge["target"] for edge in filtered_edges}
    if not connected_terms:
        connected_terms = {term for term, _ in node_counts.most_common(max_nodes)}

    selected_terms = set()
    ranked_terms = sorted(
        node_counts.items(),
        key=lambda item: (
            item[0] in connected_terms,
            node_metadata.get(item[0], {}).get("specificity") == "specific",
            not has_specific_child(item[0], node_metadata, connected_terms),
            item[1],
        ),
        reverse=True,
    )
    for term, _ in ranked_terms:
        if term in connected_terms:
            if has_specific_child(term, node_metadata, connected_terms):
                continue
            selected_terms.add(term)
        if len(selected_terms) >= max_nodes:
            break
    filtered_edges = [edge for edge in filtered_edges if edge["source"] in selected_terms and edge["target"] in selected_terms]
    ranks = pagerank(sorted(selected_terms), filtered_edges)

    nodes = [
        {
            "id": term,
            "label": term,
            "category": node_categories.get(term, "STRUCTURE"),
            "node_type": node_categories.get(term, "STRUCTURE"),
            "count": int(node_counts[term]),
            "pagerank": round(float(ranks.get(term, 0)), 6),
            "parent_node": node_metadata.get(term, {}).get("parent_node", ""),
            "specificity": node_metadata.get(term, {}).get("specificity", "generic"),
            "papers": [paper["title"] for paper in paper_details.get(term, [])[:3]],
            "paper_details": paper_details.get(term, []),
        }
        for term in selected_terms
    ]
    nodes = apply_psp_layout(nodes, filtered_edges)
    emit_progress(94, f"知识图谱布局完成: {len(nodes)} 个节点 · {len(filtered_edges)} 条关系")

    category_counts = Counter(node["category"] for node in nodes)
    top_terms = [
        {"term": term, "count": int(count), "category": node_categories.get(term, "STRUCTURE")}
        for term, count in node_counts.most_common()
        if not has_specific_child(term, node_metadata, connected_terms)
    ][:12]
    path_details = build_psp_path_details(filtered_edges, node_types=node_categories)

    return {
        "graph_type": "PSP_DIRECTED",
        "dataset": dataset,
        "paper_count": int(len(df)),
        "analyzed_paper_count": int(min(len(df), 500)),
        "nodes": nodes,
        "edges": filtered_edges,
        "triplets": triplet_samples,
        "top_terms": top_terms,
        "category_counts": dict(category_counts),
        "node_type_labels": NODE_TYPE_LABELS,
        "node_type_colors": NODE_TYPE_COLORS,
        "psp_paths": [" → ".join(path["nodes"]) for path in path_details],
        "psp_path_details": path_details,
        "structure_refinements": [
            {
                "term": term,
                "parent_node": node_metadata.get(term, {}).get("parent_node", "microstructure"),
                "count": int(count),
                "papers": structure_refinement_papers.get(term, []),
                "in_graph": term in selected_terms,
            }
            for term, count in structure_refinement_counts.most_common(20)
        ],
        "caption": build_psp_caption(dataset, int(len(df))),
        "mode": str(mode or "rule").lower(),
        "llm_enhanced": str(mode or "rule").lower() in {"llm", "hybrid"} and llm_enabled(llm_config),
        "input_source": input_source,
        "fulltext_chunk_count": int(fulltext_chunk_count),
        "missing_fulltext_count": int(missing_fulltext_count),
        "fallback_abstract_count": int(fallback_abstract_count),
        "max_chunks_per_paper": int(max_chunks_per_paper),
        "filters": {
            "min_weight": min_weight,
            "min_frequency": min_frequency,
            "top_k_neighbors": top_k_neighbors,
            "weighting": "PMI_normalized",
            "chunk_sections": "prefer Methods/Results/Discussion; skip References",
        },
    }


def deduplicate_terms(terms: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for term, node_type in terms:
        normalized = normalize_term(term)
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        result.append((normalized, node_type))
    return result
