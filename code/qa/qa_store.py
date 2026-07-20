#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


def connect_db(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    ensure_schema(conn)
    return conn


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _add_column_if_missing(conn: sqlite3.Connection, table_name: str, column_name: str, ddl: str) -> None:
    if column_name not in _table_columns(conn, table_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {ddl}")


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS qa_sessions (
            session_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            scope_type TEXT NOT NULL,
            scope_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS qa_messages (
            message_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            model TEXT,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            total_tokens INTEGER,
            retrieval_mode TEXT,
            reranker_model TEXT,
            rerank_device TEXT,
            rerank_duration_ms INTEGER,
            rerank_candidates INTEGER,
            rerank_error TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES qa_sessions(session_id) ON DELETE CASCADE
        )
        """
    )
    _add_column_if_missing(conn, "qa_messages", "prompt_tokens", "prompt_tokens INTEGER")
    _add_column_if_missing(conn, "qa_messages", "completion_tokens", "completion_tokens INTEGER")
    _add_column_if_missing(conn, "qa_messages", "total_tokens", "total_tokens INTEGER")
    _add_column_if_missing(conn, "qa_messages", "retrieval_mode", "retrieval_mode TEXT")
    _add_column_if_missing(conn, "qa_messages", "reranker_model", "reranker_model TEXT")
    _add_column_if_missing(conn, "qa_messages", "rerank_device", "rerank_device TEXT")
    _add_column_if_missing(conn, "qa_messages", "rerank_duration_ms", "rerank_duration_ms INTEGER")
    _add_column_if_missing(conn, "qa_messages", "rerank_candidates", "rerank_candidates INTEGER")
    _add_column_if_missing(conn, "qa_messages", "rerank_error", "rerank_error TEXT")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS qa_citations (
            citation_id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL,
            chunk_id TEXT,
            citation_order INTEGER NOT NULL,
            identity_key TEXT NOT NULL,
            section_title TEXT,
            page_start INTEGER,
            page_end INTEGER,
            quoted_text TEXT NOT NULL,
            source_type TEXT NOT NULL DEFAULT 'fulltext',
            paper_title TEXT,
            FOREIGN KEY (message_id) REFERENCES qa_messages(message_id) ON DELETE CASCADE
        )
        """
    )
    _add_column_if_missing(conn, "qa_citations", "source_type", "source_type TEXT NOT NULL DEFAULT 'fulltext'")
    _add_column_if_missing(conn, "qa_citations", "paper_title", "paper_title TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_qa_sessions_updated ON qa_sessions(updated_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_qa_messages_session ON qa_messages(session_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_qa_citations_message ON qa_citations(message_id, citation_order)")
    conn.commit()


def create_session(conn: sqlite3.Connection, *, session_id: str, title: str, scope_type: str, scope_json: str) -> dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO qa_sessions (session_id, title, scope_type, scope_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (session_id, title, scope_type, scope_json, now, now),
    )
    return {
        "session_id": session_id,
        "title": title,
        "scope_type": scope_type,
        "scope_json": scope_json,
        "created_at": now,
        "updated_at": now,
    }


def list_sessions(conn: sqlite3.Connection, *, limit: int = 80) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT s.session_id, s.title, s.scope_type, s.scope_json,
               s.created_at, s.updated_at, COUNT(m.message_id) AS message_count
        FROM qa_sessions s
        LEFT JOIN qa_messages m ON m.session_id = s.session_id
        WHERE s.scope_type IN ('library', 'collection')
        GROUP BY s.session_id
        ORDER BY s.updated_at DESC, s.created_at DESC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    return [dict(row) for row in rows]


def get_session(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT session_id, title, scope_type, scope_json, created_at, updated_at FROM qa_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()


def update_session_title(conn: sqlite3.Connection, session_id: str, title: str) -> dict[str, Any] | None:
    now = datetime.now().isoformat(timespec="seconds")
    cursor = conn.execute(
        "UPDATE qa_sessions SET title = ?, updated_at = ? WHERE session_id = ?",
        (title, now, session_id),
    )
    if not cursor.rowcount:
        return None
    row = get_session(conn, session_id)
    return dict(row) if row is not None else None


def create_message(
    conn: sqlite3.Connection,
    *,
    message_id: str,
    session_id: str,
    role: str,
    content: str,
    model: str = "",
    token_usage: dict[str, Any] | None = None,
    retrieval_mode: str = "",
    rerank_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    usage = token_usage or {}
    rerank = rerank_metadata or {}
    conn.execute(
        """
        INSERT INTO qa_messages (
            message_id, session_id, role, content, model,
            prompt_tokens, completion_tokens, total_tokens, retrieval_mode,
            reranker_model, rerank_device, rerank_duration_ms, rerank_candidates, rerank_error,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            message_id, session_id, role, content, model or None,
            usage.get("prompt_tokens"), usage.get("completion_tokens"), usage.get("total_tokens"),
            retrieval_mode or None,
            rerank.get("model") or None,
            rerank.get("device") or None,
            rerank.get("duration_ms"),
            rerank.get("candidate_count"),
            rerank.get("error") or None,
            now,
        ),
    )
    conn.execute("UPDATE qa_sessions SET updated_at = ? WHERE session_id = ?", (now, session_id))
    return {
        "message_id": message_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "model": model,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "retrieval_mode": retrieval_mode,
        "reranker_model": rerank.get("model") or "",
        "rerank_device": rerank.get("device") or "",
        "rerank_duration_ms": rerank.get("duration_ms"),
        "rerank_candidates": rerank.get("candidate_count"),
        "rerank_error": rerank.get("error") or "",
        "created_at": now,
    }


def save_citations(conn: sqlite3.Connection, *, message_id: str, citations: list[dict[str, Any]]) -> None:
    for index, item in enumerate(citations, 1):
        conn.execute(
            """
            INSERT INTO qa_citations (
                citation_id, message_id, chunk_id, citation_order, identity_key,
                section_title, page_start, page_end, quoted_text, source_type, paper_title
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{message_id}::citation:{index:03d}",
                message_id,
                item.get("chunk_id"),
                int(item.get("citation_order") or index),
                item.get("identity_key") or "",
                item.get("section_title") or "",
                item.get("page_start"),
                item.get("page_end"),
                item.get("quoted_text") or "",
                item.get("source_type") or "fulltext",
                item.get("paper_title") or item.get("title") or "",
            ),
        )


def get_session_detail(conn: sqlite3.Connection, session_id: str) -> dict[str, Any] | None:
    session = get_session(conn, session_id)
    if session is None:
        return None
    messages = []
    rows = conn.execute(
        """
        SELECT message_id, session_id, role, content, model,
               prompt_tokens, completion_tokens, total_tokens, retrieval_mode,
               reranker_model, rerank_device, rerank_duration_ms, rerank_candidates, rerank_error,
               created_at
        FROM qa_messages
        WHERE session_id = ?
        ORDER BY created_at ASC, rowid ASC
        """,
        (session_id,),
    ).fetchall()
    for row in rows:
        message = dict(row)
        citations = conn.execute(
            """
            SELECT citation_id, message_id, chunk_id, citation_order, identity_key,
                   section_title, page_start, page_end, quoted_text, source_type, paper_title
            FROM qa_citations
            WHERE message_id = ?
            ORDER BY citation_order ASC
            """,
            (row["message_id"],),
        ).fetchall()
        message["citations"] = [dict(item) for item in citations]
        messages.append(message)
    payload = dict(session)
    payload["messages"] = messages
    return payload


def delete_session(conn: sqlite3.Connection, session_id: str) -> int:
    cursor = conn.execute("DELETE FROM qa_sessions WHERE session_id = ?", (session_id,))
    return int(cursor.rowcount or 0)
