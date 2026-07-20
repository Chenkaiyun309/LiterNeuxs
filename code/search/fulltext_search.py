#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import sqlite3
from typing import Any


HIGH_VALUE_SECTIONS = (
    "abstract",
    "introduction",
    "background",
    "method",
    "methods",
    "results",
    "discussion",
    "conclusion",
    "conclusions",
)


def _normalized_query(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _scope_identity_keys(conn: sqlite3.Connection, *, scope_type: str, identity_key: str = "", identity_keys: list[str] | None = None, collection_id: str = "") -> tuple[list[str], dict[str, Any]]:
    scope = str(scope_type or "all_papers").strip() or "all_papers"
    selected_keys = [str(item).strip() for item in (identity_keys or []) if str(item).strip()]
    if scope == "current_paper":
        keys = [identity_key] if str(identity_key or "").strip() else []
        return keys, {"scope_type": scope, "requested": len(keys), "collection_id": ""}
    if scope == "selected_papers":
        return selected_keys, {"scope_type": scope, "requested": len(selected_keys), "collection_id": ""}
    if scope == "collection":
        if not collection_id:
            return [], {"scope_type": scope, "requested": 0, "collection_id": ""}
        rows = conn.execute(
            "SELECT identity_key FROM collection_papers WHERE collection_id = ? ORDER BY created_at DESC",
            (collection_id,),
        ).fetchall()
        keys = [row["identity_key"] for row in rows]
        return keys, {"scope_type": scope, "requested": len(keys), "collection_id": collection_id}
    rows = conn.execute(
        """
        SELECT identity_key
        FROM paper_fulltext
        WHERE parse_status = 'parsed'
        ORDER BY parsed_at DESC, identity_key ASC
        """
    ).fetchall()
    keys = [row["identity_key"] for row in rows]
    return keys, {"scope_type": "all_papers", "requested": len(keys), "collection_id": ""}


def _parsed_chunk_counts(conn: sqlite3.Connection, identity_keys: list[str]) -> dict[str, int]:
    if not identity_keys:
        return {}
    placeholders = ", ".join("?" for _ in identity_keys)
    rows = conn.execute(
        f"""
        SELECT c.identity_key, COUNT(*) AS chunk_count
        FROM paper_chunks c
        JOIN paper_fulltext f ON f.identity_key = c.identity_key
        WHERE c.identity_key IN ({placeholders})
          AND f.parse_status = 'parsed'
        GROUP BY c.identity_key
        """,
        identity_keys,
    ).fetchall()
    return {row["identity_key"]: int(row["chunk_count"] or 0) for row in rows}


def _section_bonus(section_title: str) -> float:
    section = str(section_title or "").strip().lower()
    if not section:
        return 0.0
    if any(name in section for name in HIGH_VALUE_SECTIONS):
        return 0.18
    if "reference" in section or "acknowledg" in section:
        return -0.25
    return 0.05


def _chunk_type_bonus(chunk_type: str) -> float:
    value = str(chunk_type or "body").strip().lower()
    if value == "body":
        return 0.14
    if value == "abstract":
        return 0.08
    if value == "references":
        return -0.25
    return 0.0


def _paper_metadata_map(conn: sqlite3.Connection, identity_keys: list[str]) -> dict[str, dict[str, Any]]:
    if not identity_keys:
        return {}
    placeholders = ", ".join("?" for _ in identity_keys)
    rows = conn.execute(
        f"""
        SELECT identity_key, title, authors, venue, year, publicationDate, doi
        FROM papers
        WHERE identity_key IN ({placeholders})
        """,
        identity_keys,
    ).fetchall()
    return {row["identity_key"]: dict(row) for row in rows}


def _extract_snippet(text: str, query: str, *, size: int = 220) -> str:
    body = " ".join(str(text or "").split())
    if not body:
        return ""
    needle = str(query or "").strip().lower()
    if not needle:
        return body[:size] + ("..." if len(body) > size else "")
    index = body.lower().find(needle)
    if index < 0:
        return body[:size] + ("..." if len(body) > size else "")
    start = max(0, index - size // 3)
    end = min(len(body), start + size)
    snippet = body[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(body):
        snippet = snippet + "..."
    return snippet


def search_fulltext(
    conn: sqlite3.Connection,
    *,
    query: str,
    scope_type: str,
    identity_key: str = "",
    identity_keys: list[str] | None = None,
    collection_id: str = "",
    limit: int = 20,
    max_per_paper: int = 4,
) -> dict[str, Any]:
    q = _normalized_query(query)
    if not q:
        return {
            "query": "",
            "scope": {"scope_type": scope_type, "requested": 0, "collection_id": collection_id},
            "results": [],
            "total": 0,
            "included_papers": 0,
            "excluded_unparsed": 0,
        }

    scope_keys, scope_meta = _scope_identity_keys(
        conn,
        scope_type=scope_type,
        identity_key=identity_key,
        identity_keys=identity_keys,
        collection_id=collection_id,
    )
    if not scope_keys:
        return {
            "query": q,
            "scope": scope_meta,
            "results": [],
            "total": 0,
            "included_papers": 0,
            "excluded_unparsed": 0,
        }

    parsed_counts = _parsed_chunk_counts(conn, scope_keys)
    searchable_keys = [key for key in scope_keys if parsed_counts.get(key, 0) > 0]
    excluded_unparsed = max(0, len(scope_keys) - len(searchable_keys))
    if not searchable_keys:
        return {
            "query": q,
            "scope": scope_meta,
            "results": [],
            "total": 0,
            "included_papers": 0,
            "excluded_unparsed": excluded_unparsed,
        }

    placeholders = ", ".join("?" for _ in searchable_keys)
    sql = f"""
        SELECT
            fts.chunk_id,
            fts.identity_key,
            fts.section_title,
            fts.chunk_text,
            bm25(paper_chunks_fts) AS bm25_score,
            c.page_start,
            c.page_end,
            COALESCE(c.chunk_index, 0) AS chunk_index,
            COALESCE(c.chunk_type, 'body') AS chunk_type,
            COALESCE(c.page_mapping_confidence, 0) AS page_mapping_confidence,
            COALESCE(c.token_count, 0) AS token_count
        FROM paper_chunks_fts fts
        JOIN paper_chunks c ON c.chunk_id = fts.chunk_id
        WHERE paper_chunks_fts MATCH ?
          AND fts.identity_key IN ({placeholders})
        ORDER BY bm25_score ASC
        LIMIT ?
    """
    raw_rows = conn.execute(sql, [q, *searchable_keys, int(max(limit * 6, 30))]).fetchall()
    metadata = _paper_metadata_map(conn, searchable_keys)

    ranked: list[dict[str, Any]] = []
    for row in raw_rows:
        item = dict(row)
        bm25_score = float(item.get("bm25_score") or 0.0)
        lexical_score = 1.0 / (1.0 + max(0.0, bm25_score))
        rerank_score = lexical_score + _section_bonus(item.get("section_title", "")) + _chunk_type_bonus(item.get("chunk_type", "body"))
        item["score"] = round(rerank_score, 6)
        item["snippet"] = _extract_snippet(item.get("chunk_text", ""), q)
        item.update(metadata.get(item["identity_key"], {}))
        ranked.append(item)

    ranked.sort(key=lambda item: (item["score"], -float(item.get("page_mapping_confidence") or 0), -int(item.get("token_count") or 0)), reverse=True)

    per_paper: dict[str, int] = {}
    results: list[dict[str, Any]] = []
    seen_chunk_ids: set[str] = set()
    for item in ranked:
        chunk_id = str(item.get("chunk_id") or "")
        paper_key = str(item.get("identity_key") or "")
        if not chunk_id or not paper_key or chunk_id in seen_chunk_ids:
            continue
        if per_paper.get(paper_key, 0) >= max(1, int(max_per_paper or 1)):
            continue
        seen_chunk_ids.add(chunk_id)
        per_paper[paper_key] = per_paper.get(paper_key, 0) + 1
        results.append({
            "chunk_id": chunk_id,
            "identity_key": paper_key,
            "title": item.get("title") or "",
            "authors": item.get("authors") or "",
            "venue": item.get("venue") or "",
            "publicationDate": item.get("publicationDate") or item.get("year") or "",
            "doi": item.get("doi") or "",
            "section_title": item.get("section_title") or "",
            "page_start": item.get("page_start"),
            "page_end": item.get("page_end"),
            "chunk_index": int(item.get("chunk_index") or 0),
            "chunk_type": item.get("chunk_type") or "body",
            "page_mapping_confidence": float(item.get("page_mapping_confidence") or 0.0),
            "token_count": int(item.get("token_count") or 0),
            "score": float(item.get("score") or 0.0),
            "snippet": item.get("snippet") or "",
            "chunk_text": item.get("chunk_text") or "",
        })
        if len(results) >= int(limit):
            break

    return {
        "query": q,
        "scope": scope_meta,
        "results": results,
        "total": len(results),
        "included_papers": len(searchable_keys),
        "excluded_unparsed": excluded_unparsed,
    }
