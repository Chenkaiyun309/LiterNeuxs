#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from typing import Any, Callable


TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+/_-]*|[\u4e00-\u9fff]{2,}")

SCIENTIFIC_INTENT_TERMS = {
    "formula": ("公式", "方程", "表达式", "推导", "等式", "equation", "formula"),
    "figure": ("图片", "图像", "图中", "图表", "显微图", "figure", "fig.", "image", "micrograph"),
    "table": ("表格", "表中", "数据表", "table"),
}

SCIENTIFIC_QUERY_ALIASES = {
    "formula": ("equation", "formula", "model"),
    "figure": ("figure", "fig", "image", "micrograph"),
    "table": ("table",),
}


class RetrievalError(RuntimeError):
    """Raised when knowledge retrieval cannot be completed."""


def scope_identity_keys(conn, scope_type: str, collection_id: str = "") -> list[str]:
    if scope_type == "collection":
        if not collection_id:
            raise RetrievalError("缺少文献主题库标识")
        rows = conn.execute(
            "SELECT identity_key FROM collection_papers WHERE collection_id = ? ORDER BY created_at DESC",
            (collection_id,),
        ).fetchall()
        return [str(row["identity_key"]) for row in rows]
    rows = conn.execute("SELECT identity_key FROM papers ORDER BY last_seen_at DESC").fetchall()
    return [str(row["identity_key"]) for row in rows]


def _tokens(text: str) -> list[str]:
    values: list[str] = []
    for raw in TOKEN_RE.findall(str(text or "")):
        token = raw.lower().strip()
        if len(token) >= 2 and token not in values:
            values.append(token)
    for intent in _scientific_intents(text):
        for alias in SCIENTIFIC_QUERY_ALIASES[intent]:
            if alias not in values:
                values.append(alias)
    return values[:24]


def _scientific_intents(text: str) -> list[str]:
    normalized = str(text or "").lower()
    return [
        intent
        for intent, terms in SCIENTIFIC_INTENT_TERMS.items()
        if any(term in normalized for term in terms)
    ]


def _content_types(text: str) -> list[str]:
    value = str(text or "")
    lowered = value.lower()
    types: list[str] = []
    if "$$" in value or re.search(r"\\(?:frac|begin\{(?:equation|align)|mathrm|mathbf|sum|int|alpha|beta|gamma)\b", value):
        types.append("formula")
    if re.search(r"!\[[^\]]*\]\([^)]+\)", value) or re.search(r"(?:^|\s)(?:fig\.|figure)\s*\d+", lowered):
        types.append("figure")
    if re.search(r"(?:^|\s)table\s*\d+", lowered) or re.search(r"^\s*\|.+\|\s*$", value, re.MULTILINE):
        types.append("table")
    return types


def fts_query(question: str) -> str:
    terms = [item.replace('"', '""') for item in _tokens(question)]
    return " OR ".join(f'"{item}"' for item in terms)


def _paper_rows(conn, identity_keys: list[str]) -> list[dict[str, Any]]:
    if not identity_keys:
        return []
    placeholders = ",".join("?" for _ in identity_keys)
    rows = conn.execute(
        f"""
        SELECT identity_key, title, authors, abstract, venue, year, publicationDate, doi, url
        FROM papers
        WHERE identity_key IN ({placeholders})
        """,
        identity_keys,
    ).fetchall()
    return [dict(row) for row in rows]


def _paper_score(paper: dict[str, Any], terms: list[str]) -> float:
    title = str(paper.get("title") or "").lower()
    abstract = str(paper.get("abstract") or "").lower()
    metadata = " ".join([
        str(paper.get("authors") or ""),
        str(paper.get("venue") or ""),
        str(paper.get("year") or ""),
    ]).lower()
    score = 0.0
    for term in terms:
        score += title.count(term) * 5.0
        score += abstract.count(term) * 1.25
        score += metadata.count(term) * 0.5
    if terms and all(term in f"{title} {abstract}" for term in terms):
        score += 4.0
    return score


def _abstract_evidence(papers: list[dict[str, Any]], terms: list[str], limit: int) -> list[dict[str, Any]]:
    ranked = sorted(
        ((paper, _paper_score(paper, terms)) for paper in papers if str(paper.get("abstract") or "").strip()),
        key=lambda item: (item[1], len(str(item[0].get("abstract") or ""))),
        reverse=True,
    )
    if terms and any(score > 0 for _, score in ranked):
        ranked = [item for item in ranked if item[1] > 0]
    output = []
    for rank, (paper, score) in enumerate(ranked[:limit], 1):
        output.append({
            "source_id": f"abstract::{paper['identity_key']}",
            "chunk_id": f"abstract::{paper['identity_key']}",
            "identity_key": paper["identity_key"],
            "source_type": "abstract",
            "section_title": "摘要",
            "page_start": None,
            "page_end": None,
            "chunk_text": str(paper.get("abstract") or "").strip(),
            "title": paper.get("title") or "",
            "authors": paper.get("authors") or "",
            "venue": paper.get("venue") or "",
            "doi": paper.get("doi") or "",
            "lexical_rank": rank,
            "lexical_score": score,
        })
    return output


def _chunk_evidence(conn, identity_keys: list[str], question: str, limit: int) -> list[dict[str, Any]]:
    query = fts_query(question)
    if not identity_keys or not query:
        return []
    placeholders = ",".join("?" for _ in identity_keys)
    sql = f"""
        SELECT fts.chunk_id, fts.identity_key, fts.section_title, fts.chunk_text,
               bm25(paper_chunks_fts) AS bm25_score,
               c.page_start, c.page_end, COALESCE(c.chunk_index, 0) AS chunk_index,
               p.title, p.authors, p.venue, p.doi
        FROM paper_chunks_fts fts
        JOIN paper_chunks c ON c.chunk_id = fts.chunk_id
        JOIN papers p ON p.identity_key = fts.identity_key
        WHERE paper_chunks_fts MATCH ?
          AND fts.identity_key IN ({placeholders})
        ORDER BY bm25_score ASC
        LIMIT ?
    """
    try:
        rows = conn.execute(sql, [query, *identity_keys, max(limit * 3, 24)]).fetchall()
    except Exception:
        rows = []
    output = []
    per_paper: dict[str, int] = defaultdict(int)
    for rank, row in enumerate(rows, 1):
        item = dict(row)
        identity_key = str(item.get("identity_key") or "")
        if per_paper[identity_key] >= 3:
            continue
        per_paper[identity_key] += 1
        item.update({
            "source_id": item["chunk_id"],
            "source_type": "fulltext",
            "lexical_rank": rank,
            "lexical_score": -float(item.get("bm25_score") or 0),
        })
        output.append(item)
        if len(output) >= limit:
            break
    return output


def _scientific_evidence(conn, identity_keys: list[str], question: str, limit: int) -> list[dict[str, Any]]:
    intents = _scientific_intents(question)
    if not identity_keys or not intents:
        return []
    conditions = []
    if "formula" in intents:
        conditions.append(r"(c.chunk_text LIKE '%$$%' OR c.chunk_text LIKE '%\frac%' OR c.chunk_text LIKE '%\begin{equation%' OR c.chunk_text LIKE '%\begin{align%')")
    if "figure" in intents:
        conditions.append("(c.chunk_text LIKE '%![%' OR lower(c.chunk_text) LIKE '%fig.%' OR lower(c.chunk_text) LIKE '%figure %')")
    if "table" in intents:
        conditions.append("(lower(c.chunk_text) LIKE '%table %' OR c.chunk_text LIKE '%|%|%')")
    placeholders = ",".join("?" for _ in identity_keys)
    rows = conn.execute(
        f"""
        SELECT c.chunk_id, c.identity_key, c.section_title, c.chunk_text,
               c.page_start, c.page_end, COALESCE(c.chunk_index, 0) AS chunk_index,
               p.title, p.authors, p.venue, p.doi
        FROM paper_chunks c
        JOIN papers p ON p.identity_key = c.identity_key
        WHERE c.identity_key IN ({placeholders})
          AND ({' OR '.join(conditions)})
        ORDER BY c.identity_key, c.chunk_index
        """,
        identity_keys,
    ).fetchall()
    ranked = []
    question_terms = _tokens(question)
    for row in rows:
        item = dict(row)
        content_types = _content_types(item.get("chunk_text") or "")
        intent_matches = len(set(content_types) & set(intents))
        text = str(item.get("chunk_text") or "").lower()
        lexical_matches = sum(1 for term in question_terms if term in text)
        item.update({
            "source_id": item["chunk_id"],
            "source_type": "fulltext",
            "content_types": content_types,
            "scientific_score": intent_matches * 10 + lexical_matches,
        })
        ranked.append(item)
    ranked.sort(key=lambda item: (item["scientific_score"], -int(item.get("chunk_index") or 0)), reverse=True)
    return [dict(item, scientific_rank=index) for index, item in enumerate(ranked[: max(limit * 2, 20)], 1)]


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def _semantic_evidence(conn, identity_keys: list[str], query_embedding: list[float], model: str, limit: int) -> list[dict[str, Any]]:
    if not identity_keys or not query_embedding:
        return []
    placeholders = ",".join("?" for _ in identity_keys)
    rows = conn.execute(
        f"""
        SELECT e.source_id, e.identity_key, e.source_type, e.content_hash,
               e.dimensions, e.embedding_json,
               p.title, p.authors, p.venue, p.doi,
               CASE WHEN e.source_type = 'abstract' THEN p.abstract ELSE c.chunk_text END AS chunk_text,
               CASE WHEN e.source_type = 'abstract' THEN '摘要' ELSE c.section_title END AS section_title,
               c.page_start, c.page_end
        FROM knowledge_embeddings e
        JOIN papers p ON p.identity_key = e.identity_key
        LEFT JOIN paper_chunks c ON c.chunk_id = e.source_id
        WHERE e.identity_key IN ({placeholders}) AND e.embedding_model = ?
        """,
        [*identity_keys, model],
    ).fetchall()
    ranked = []
    for row in rows:
        try:
            current_text = str(row["chunk_text"] or "")
            if not current_text.strip():
                continue
            current_hash = hashlib.sha256(current_text.encode("utf-8")).hexdigest()
            if current_hash != str(row["content_hash"] or ""):
                continue
            if int(row["dimensions"] or 0) != len(query_embedding):
                continue
            vector = json.loads(row["embedding_json"] or "[]")
            score = _cosine(query_embedding, [float(value) for value in vector])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        item = dict(row)
        item["chunk_id"] = item["source_id"]
        item["semantic_score"] = score
        ranked.append(item)
    ranked.sort(key=lambda item: item["semantic_score"], reverse=True)
    return [dict(item, semantic_rank=index) for index, item in enumerate(ranked[: max(limit * 2, 20)], 1)]


def _merge_evidence(
    lexical: list[dict[str, Any]],
    semantic: list[dict[str, Any]],
    specialized: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    scores: dict[str, float] = defaultdict(float)
    for rank, item in enumerate(lexical, 1):
        source_id = str(item.get("source_id") or item.get("chunk_id") or "")
        if not source_id:
            continue
        merged[source_id] = dict(item)
        scores[source_id] += 1.0 / (60 + rank)
    for rank, item in enumerate(semantic, 1):
        source_id = str(item.get("source_id") or item.get("chunk_id") or "")
        if not source_id:
            continue
        if source_id not in merged:
            merged[source_id] = dict(item)
        else:
            merged[source_id].update({key: value for key, value in item.items() if value not in (None, "")})
        scores[source_id] += 1.0 / (60 + rank)
    for rank, item in enumerate(specialized, 1):
        source_id = str(item.get("source_id") or item.get("chunk_id") or "")
        if not source_id:
            continue
        if source_id not in merged:
            merged[source_id] = dict(item)
        else:
            merged[source_id].update({key: value for key, value in item.items() if value not in (None, "")})
        scores[source_id] += 1.35 / (55 + rank)
    ranked = sorted(merged.values(), key=lambda item: scores[str(item.get("source_id") or item.get("chunk_id"))], reverse=True)
    output = []
    per_paper: dict[str, int] = defaultdict(int)
    for item in ranked:
        identity_key = str(item.get("identity_key") or "")
        if per_paper[identity_key] >= 3:
            continue
        if not str(item.get("chunk_text") or "").strip():
            continue
        per_paper[identity_key] += 1
        item["content_types"] = item.get("content_types") or _content_types(item.get("chunk_text") or "")
        item["retrieval_score"] = scores[str(item.get("source_id") or item.get("chunk_id"))]
        output.append(item)
        if len(output) >= limit:
            break
    return output


def retrieve_evidence(
    conn,
    *,
    question: str,
    scope_type: str,
    collection_id: str = "",
    top_k: int = 10,
    candidate_k: int | None = None,
    embedding_model: str = "",
    embed_query: Callable[[str], list[float]] | None = None,
) -> dict[str, Any]:
    identity_keys = scope_identity_keys(conn, scope_type, collection_id)
    if not identity_keys:
        return {"identity_keys": [], "evidence": [], "retrieval_mode": "lexical"}
    final_k = max(1, int(top_k or 10))
    recall_k = max(final_k, int(candidate_k or final_k))
    papers = _paper_rows(conn, identity_keys)
    terms = _tokens(question)
    candidate_ranked = sorted(papers, key=lambda paper: _paper_score(paper, terms), reverse=True)
    candidates = candidate_ranked[: min(120, max(20, recall_k * 3))]
    candidate_keys = [str(item["identity_key"]) for item in candidates]
    lexical = _chunk_evidence(conn, candidate_keys, question, recall_k * 2)
    lexical.extend(_abstract_evidence(candidates, terms, max(4, recall_k)))
    specialized = _scientific_evidence(conn, identity_keys, question, recall_k)
    semantic: list[dict[str, Any]] = []
    mode = "lexical"
    if embed_query is not None and embedding_model:
        try:
            query_embedding = embed_query(question)
            semantic = _semantic_evidence(conn, identity_keys, query_embedding, embedding_model, recall_k)
            if semantic:
                mode = "hybrid"
        except Exception:
            semantic = []
    return {
        "identity_keys": identity_keys,
        "evidence": _merge_evidence(lexical, semantic, specialized, recall_k),
        "retrieval_mode": mode,
    }


def iter_index_sources(conn, identity_keys: list[str]) -> list[dict[str, Any]]:
    if not identity_keys:
        return []
    placeholders = ",".join("?" for _ in identity_keys)
    rows = conn.execute(
        f"""
        SELECT 'abstract::' || identity_key AS source_id, identity_key, 'abstract' AS source_type,
               abstract AS content
        FROM papers
        WHERE identity_key IN ({placeholders}) AND COALESCE(abstract, '') != ''
        UNION ALL
        SELECT chunk_id AS source_id, identity_key, 'fulltext' AS source_type, chunk_text AS content
        FROM paper_chunks
        WHERE identity_key IN ({placeholders}) AND COALESCE(chunk_text, '') != ''
        """,
        [*identity_keys, *identity_keys],
    ).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        item["content_hash"] = hashlib.sha256(str(item["content"]).encode("utf-8")).hexdigest()
        output.append(item)
    return output


def embedding_index_status(conn, *, model: str = "") -> dict[str, Any]:
    where = "WHERE e.embedding_model = ?" if model else ""
    params = (model,) if model else ()
    rows = conn.execute(
        f"""
        SELECT e.identity_key, e.content_hash, e.dimensions, e.embedding_json, e.updated_at,
               CASE WHEN e.source_type = 'abstract' THEN p.abstract ELSE c.chunk_text END AS current_text
        FROM knowledge_embeddings e
        LEFT JOIN papers p ON p.identity_key = e.identity_key
        LEFT JOIN paper_chunks c ON c.chunk_id = e.source_id
        {where}
        """,
        params,
    ).fetchall()
    valid_rows = []
    stale = 0
    for row in rows:
        current_text = row["current_text"]
        current_hash = (
            hashlib.sha256(str(current_text).encode("utf-8")).hexdigest()
            if current_text is not None else ""
        )
        try:
            vector = json.loads(row["embedding_json"] or "[]")
            vector_valid = (
                isinstance(vector, list)
                and int(row["dimensions"] or 0) > 0
                and len(vector) == int(row["dimensions"])
                and all(isinstance(value, (int, float)) and math.isfinite(float(value)) for value in vector)
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            vector_valid = False
        if current_hash == str(row["content_hash"] or "") and vector_valid:
            valid_rows.append(row)
        else:
            stale += 1
    return {
        "total": len(valid_rows),
        "papers": len({str(row["identity_key"]) for row in valid_rows}),
        "updated_at": max((str(row["updated_at"] or "") for row in valid_rows), default=""),
        "stale": stale,
        "model": model,
    }
