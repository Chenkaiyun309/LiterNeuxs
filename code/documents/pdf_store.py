#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


STATUS_NOT_DOWNLOADED = "not_downloaded"
STATUS_DOWNLOADED = "downloaded"
STATUS_FAILED = "failed"
PDF_SOURCE_UPLOAD = "upload"
PDF_SOURCE_LEGACY = "legacy"
PARSE_STATUS_NOT_PARSED = "not_parsed"
PARSE_STATUS_PARSED = "parsed"
PARSE_STATUS_FAILED = "failed"
PARSE_QUALITY_WARNING = "warning"
FTS_SCHEMA_VERSION = "3"


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _add_column_if_missing(conn: sqlite3.Connection, table_name: str, column_name: str, ddl: str) -> None:
    if column_name not in _table_columns(conn, table_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {ddl}")


def _json_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return "[]"


def _embedding_payload_is_valid(embedding_json: str, dimensions: int) -> bool:
    try:
        values = json.loads(embedding_json or "[]")
        return (
            isinstance(values, list)
            and int(dimensions or 0) > 0
            and len(values) == int(dimensions)
            and all(isinstance(value, (int, float)) and math.isfinite(float(value)) for value in values)
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return False


def _create_knowledge_embeddings_table(conn: sqlite3.Connection, table_name: str = "knowledge_embeddings") -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            source_id TEXT NOT NULL,
            identity_key TEXT NOT NULL,
            source_type TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            embedding_model TEXT NOT NULL,
            dimensions INTEGER NOT NULL,
            embedding_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (source_id, embedding_model),
            FOREIGN KEY (identity_key) REFERENCES papers(identity_key) ON DELETE CASCADE
        )
        """
    )


def _ensure_knowledge_embeddings_schema(conn: sqlite3.Connection) -> None:
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'knowledge_embeddings'"
    ).fetchone()
    if not table_exists:
        _create_knowledge_embeddings_table(conn)
        return

    primary_key = [
        row[1]
        for row in sorted(conn.execute("PRAGMA table_info(knowledge_embeddings)").fetchall(), key=lambda row: row[5])
        if int(row[5] or 0) > 0
    ]
    if primary_key == ["source_id", "embedding_model"]:
        return

    conn.execute("DROP TABLE IF EXISTS knowledge_embeddings_v2")
    _create_knowledge_embeddings_table(conn, "knowledge_embeddings_v2")
    conn.execute(
        """
        INSERT OR REPLACE INTO knowledge_embeddings_v2 (
            source_id, identity_key, source_type, content_hash, embedding_model,
            dimensions, embedding_json, updated_at
        )
        SELECT source_id, identity_key, source_type, content_hash, embedding_model,
               dimensions, embedding_json, updated_at
        FROM knowledge_embeddings
        """
    )
    conn.execute("DROP TABLE knowledge_embeddings")
    conn.execute("ALTER TABLE knowledge_embeddings_v2 RENAME TO knowledge_embeddings")


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_documents (
            identity_key TEXT PRIMARY KEY,
            doi TEXT,
            pdf_url TEXT,
            pdf_path TEXT,
            download_status TEXT NOT NULL DEFAULT 'not_downloaded',
            download_error TEXT,
            downloaded_at TEXT,
            pdf_source TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (identity_key) REFERENCES papers(identity_key) ON DELETE CASCADE
        )
        """
    )
    _add_column_if_missing(conn, "paper_documents", "pdf_source", "pdf_source TEXT NOT NULL DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_documents_status ON paper_documents(download_status)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_fulltext (
            identity_key TEXT PRIMARY KEY,
            full_text TEXT,
            markdown_text TEXT,
            markdown_path TEXT,
            parse_engine TEXT NOT NULL DEFAULT 'marker',
            parse_status TEXT NOT NULL DEFAULT 'not_parsed',
            parse_error TEXT,
            page_count INTEGER NOT NULL DEFAULT 0,
            parsed_at TEXT,
            parse_quality TEXT,
            page_mapping_coverage REAL NOT NULL DEFAULT 0,
            text_length INTEGER NOT NULL DEFAULT 0,
            quality_warnings_json TEXT,
            FOREIGN KEY (identity_key) REFERENCES papers(identity_key) ON DELETE CASCADE
        )
        """
    )
    _add_column_if_missing(conn, "paper_fulltext", "markdown_text", "markdown_text TEXT")
    _add_column_if_missing(conn, "paper_fulltext", "markdown_path", "markdown_path TEXT")
    _add_column_if_missing(conn, "paper_fulltext", "parse_engine", "parse_engine TEXT NOT NULL DEFAULT 'marker'")
    _add_column_if_missing(conn, "paper_fulltext", "parse_quality", f"parse_quality TEXT DEFAULT '{PARSE_QUALITY_WARNING}'")
    _add_column_if_missing(conn, "paper_fulltext", "page_mapping_coverage", "page_mapping_coverage REAL NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "paper_fulltext", "text_length", "text_length INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "paper_fulltext", "quality_warnings_json", "quality_warnings_json TEXT DEFAULT '[]'")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_chunks (
            chunk_id TEXT PRIMARY KEY,
            identity_key TEXT NOT NULL,
            section_title TEXT,
            page_start INTEGER,
            page_end INTEGER,
            chunk_text TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            token_count INTEGER NOT NULL DEFAULT 0,
            content_hash TEXT,
            chunk_type TEXT NOT NULL DEFAULT 'body',
            page_mapping_confidence REAL NOT NULL DEFAULT 0,
            FOREIGN KEY (identity_key) REFERENCES papers(identity_key) ON DELETE CASCADE
        )
        """
    )
    _add_column_if_missing(conn, "paper_chunks", "token_count", "token_count INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "paper_chunks", "content_hash", "content_hash TEXT")
    _add_column_if_missing(conn, "paper_chunks", "chunk_type", "chunk_type TEXT NOT NULL DEFAULT 'body'")
    _add_column_if_missing(conn, "paper_chunks", "page_mapping_confidence", "page_mapping_confidence REAL NOT NULL DEFAULT 0")
    _ensure_knowledge_embeddings_schema(conn)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_fulltext_status ON paper_fulltext(parse_status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_chunks_identity ON paper_chunks(identity_key, chunk_index)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_embeddings_scope ON knowledge_embeddings(identity_key, embedding_model)")


def ensure_fts_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS paper_chunks_fts USING fts5(
            chunk_id UNINDEXED,
            identity_key UNINDEXED,
            section_title,
            chunk_text,
            tokenize='unicode61'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS literature_schema_meta (
            meta_key TEXT PRIMARY KEY,
            meta_value TEXT NOT NULL
        )
        """
    )
    version_row = conn.execute(
        "SELECT meta_value FROM literature_schema_meta WHERE meta_key = 'paper_chunks_fts_version'"
    ).fetchone()
    needs_migration = version_row is None or str(version_row[0]) != FTS_SCHEMA_VERSION
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS paper_chunks_fts_after_insert
        AFTER INSERT ON paper_chunks
        WHEN TRIM(COALESCE(NEW.chunk_text, '')) != ''
        BEGIN
            INSERT INTO paper_chunks_fts (chunk_id, identity_key, section_title, chunk_text)
            VALUES (NEW.chunk_id, NEW.identity_key, COALESCE(NEW.section_title, ''), NEW.chunk_text);
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS paper_chunks_fts_after_delete
        AFTER DELETE ON paper_chunks
        BEGIN
            DELETE FROM paper_chunks_fts WHERE chunk_id = OLD.chunk_id;
        END
        """
    )
    if needs_migration:
        conn.execute("DROP TRIGGER IF EXISTS paper_chunks_fts_after_update_delete")
        conn.execute("DROP TRIGGER IF EXISTS paper_chunks_fts_after_update_insert")
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS paper_chunks_fts_after_update
        AFTER UPDATE OF chunk_id, identity_key, section_title, chunk_text ON paper_chunks
        BEGIN
            DELETE FROM paper_chunks_fts WHERE chunk_id = OLD.chunk_id;
            INSERT INTO paper_chunks_fts (chunk_id, identity_key, section_title, chunk_text)
            SELECT NEW.chunk_id, NEW.identity_key, COALESCE(NEW.section_title, ''), NEW.chunk_text
            WHERE TRIM(COALESCE(NEW.chunk_text, '')) != '';
        END
        """
    )
    if needs_migration:
        repair_chunk_fts_integrity(conn)
        conn.execute(
            """
            INSERT INTO literature_schema_meta (meta_key, meta_value)
            VALUES ('paper_chunks_fts_version', ?)
            ON CONFLICT(meta_key) DO UPDATE SET meta_value = excluded.meta_value
            """,
            (FTS_SCHEMA_VERSION,),
        )


def chunk_fts_integrity(conn: sqlite3.Connection) -> dict[str, int | bool]:
    ensure_fts_schema(conn)
    source_count = int(conn.execute(
        "SELECT COUNT(*) FROM paper_chunks WHERE TRIM(COALESCE(chunk_text, '')) != ''"
    ).fetchone()[0] or 0)
    fts_count = int(conn.execute("SELECT COUNT(*) FROM paper_chunks_fts").fetchone()[0] or 0)
    missing = int(conn.execute(
        """
        SELECT COUNT(*)
        FROM paper_chunks c
        LEFT JOIN paper_chunks_fts fts ON fts.chunk_id = c.chunk_id
        WHERE TRIM(COALESCE(c.chunk_text, '')) != '' AND fts.chunk_id IS NULL
        """
    ).fetchone()[0] or 0)
    orphaned = int(conn.execute(
        """
        SELECT COUNT(*)
        FROM paper_chunks_fts fts
        LEFT JOIN paper_chunks c ON c.chunk_id = fts.chunk_id
        WHERE c.chunk_id IS NULL
        """
    ).fetchone()[0] or 0)
    mismatched = int(conn.execute(
        """
        SELECT COUNT(*)
        FROM paper_chunks c
        JOIN paper_chunks_fts fts ON fts.chunk_id = c.chunk_id
        WHERE COALESCE(fts.identity_key, '') != c.identity_key
           OR COALESCE(fts.section_title, '') != COALESCE(c.section_title, '')
           OR COALESCE(fts.chunk_text, '') != c.chunk_text
        """
    ).fetchone()[0] or 0)
    return {
        "ok": source_count == fts_count and not missing and not orphaned and not mismatched,
        "source_count": source_count,
        "fts_count": fts_count,
        "missing": missing,
        "orphaned": orphaned,
        "mismatched": mismatched,
    }


def repair_chunk_fts_integrity(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM paper_chunks_fts")
    conn.execute(
        """
        INSERT INTO paper_chunks_fts (chunk_id, identity_key, section_title, chunk_text)
        SELECT chunk_id, identity_key, COALESCE(section_title, ''), chunk_text
        FROM paper_chunks
        WHERE TRIM(COALESCE(chunk_text, '')) != ''
        ORDER BY identity_key, chunk_index
        """
    )


def delete_chunk_fts(conn: sqlite3.Connection, identity_key: str) -> None:
    ensure_fts_schema(conn)
    conn.execute("DELETE FROM paper_chunks_fts WHERE identity_key = ?", (identity_key,))


def rebuild_chunk_fts(conn: sqlite3.Connection, identity_key: str, chunks: list[Any] | None = None) -> None:
    ensure_fts_schema(conn)
    delete_chunk_fts(conn, identity_key)
    rows = []
    if chunks is None:
        source_rows = conn.execute(
            """
            SELECT chunk_id, identity_key, section_title, chunk_text
            FROM paper_chunks
            WHERE identity_key = ?
              AND COALESCE(chunk_text, '') != ''
            ORDER BY chunk_index ASC
            """,
            (identity_key,),
        ).fetchall()
        rows = [
            (
                row["chunk_id"],
                row["identity_key"],
                row["section_title"] or "",
                row["chunk_text"] or "",
            )
            for row in source_rows
        ]
    else:
        rows = [
            (
                f"{identity_key}::chunk:{int(getattr(chunk, 'chunk_index', 0)):05d}",
                identity_key,
                getattr(chunk, "section_title", "") or "",
                getattr(chunk, "chunk_text", "") or "",
            )
            for chunk in chunks
            if str(getattr(chunk, "chunk_text", "") or "").strip()
        ]
    if rows:
        conn.executemany(
            "INSERT INTO paper_chunks_fts (chunk_id, identity_key, section_title, chunk_text) VALUES (?, ?, ?, ?)",
            rows,
        )


def pdf_cache_dir(search_results_dir: str | Path) -> Path:
    path = Path(search_results_dir) / "pdfs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def relative_to_project(path: str | Path, project_dir: str | Path) -> str:
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(Path(project_dir).resolve()))
    except ValueError:
        return str(resolved)


def resolve_pdf_path(pdf_path: str, project_dir: str | Path) -> Path:
    path = Path(pdf_path)
    if path.is_absolute():
        return path
    return Path(project_dir) / path


def get_paper(conn: sqlite3.Connection, identity_key: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT identity_key, doi, pdf_url, title
        FROM papers
        WHERE identity_key = ?
        """,
        (identity_key,),
    ).fetchone()


def get_document(conn: sqlite3.Connection, identity_key: str) -> sqlite3.Row | None:
    ensure_schema(conn)
    return conn.execute(
        """
        SELECT identity_key, doi, pdf_url, pdf_path, download_status, download_error, downloaded_at,
               COALESCE(pdf_source, '') AS pdf_source
        FROM paper_documents
        WHERE identity_key = ?
        """,
        (identity_key,),
    ).fetchone()


def get_fulltext(conn: sqlite3.Connection, identity_key: str) -> sqlite3.Row | None:
    ensure_schema(conn)
    return conn.execute(
        """
        SELECT identity_key, full_text, markdown_text, markdown_path, parse_engine,
               parse_status, parse_error, page_count, parsed_at,
               COALESCE(parse_quality, 'warning') AS parse_quality,
               COALESCE(page_mapping_coverage, 0) AS page_mapping_coverage,
               COALESCE(text_length, 0) AS text_length,
               COALESCE(quality_warnings_json, '[]') AS quality_warnings_json
        FROM paper_fulltext
        WHERE identity_key = ?
        """,
        (identity_key,),
    ).fetchone()


def mark_parse_failed(
    conn: sqlite3.Connection,
    *,
    identity_key: str,
    error: str,
    parse_engine: str = "marker",
) -> dict[str, Any]:
    ensure_schema(conn)
    message = str(error or "PDF 解析失败")[:1000]
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO paper_fulltext (
            identity_key, full_text, markdown_text, markdown_path, parse_engine,
            parse_status, parse_error, page_count, parsed_at,
            parse_quality, page_mapping_coverage, text_length, quality_warnings_json
        ) VALUES (?, '', '', '', ?, ?, ?, 0, ?, ?, 0, 0, ?)
        ON CONFLICT(identity_key) DO UPDATE SET
            parse_engine = excluded.parse_engine,
            parse_status = excluded.parse_status,
            parse_error = excluded.parse_error,
            parsed_at = excluded.parsed_at,
            parse_quality = excluded.parse_quality,
            page_mapping_coverage = excluded.page_mapping_coverage,
            text_length = excluded.text_length,
            quality_warnings_json = excluded.quality_warnings_json
        """,
        (
            identity_key,
            parse_engine or "marker",
            PARSE_STATUS_FAILED,
            message,
            now,
            "poor",
            _json_text([message]),
        ),
    )
    return {
        "identity_key": identity_key,
        "parse_status": PARSE_STATUS_FAILED,
        "parse_error": message,
        "page_count": 0,
        "parsed_at": now,
        "parse_engine": parse_engine or "marker",
        "parse_quality": "poor",
        "page_mapping_coverage": 0.0,
        "text_length": 0,
        "quality_warnings": [message],
    }


def replace_parse_result(
    conn: sqlite3.Connection,
    *,
    identity_key: str,
    full_text: str,
    page_count: int,
    chunks: list[Any],
    markdown_text: str = "",
    markdown_path: str = "",
    parse_engine: str = "marker",
    parse_quality: str = PARSE_QUALITY_WARNING,
    page_mapping_coverage: float = 0.0,
    text_length: int = 0,
    quality_warnings_json: str = "[]",
) -> dict[str, Any]:
    ensure_schema(conn)
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO paper_fulltext (
            identity_key, full_text, markdown_text, markdown_path, parse_engine,
            parse_status, parse_error, page_count, parsed_at,
            parse_quality, page_mapping_coverage, text_length, quality_warnings_json
        ) VALUES (?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?)
        ON CONFLICT(identity_key) DO UPDATE SET
            full_text = excluded.full_text,
            markdown_text = excluded.markdown_text,
            markdown_path = excluded.markdown_path,
            parse_engine = excluded.parse_engine,
            parse_status = excluded.parse_status,
            parse_error = '',
            page_count = excluded.page_count,
            parsed_at = excluded.parsed_at,
            parse_quality = excluded.parse_quality,
            page_mapping_coverage = excluded.page_mapping_coverage,
            text_length = excluded.text_length,
            quality_warnings_json = excluded.quality_warnings_json
        """,
        (
            identity_key,
            full_text,
            markdown_text or "",
            markdown_path or "",
            parse_engine or "marker",
            PARSE_STATUS_PARSED,
            int(page_count or 0),
            now,
            parse_quality or PARSE_QUALITY_WARNING,
            float(page_mapping_coverage or 0.0),
            int(text_length or 0),
            _json_text(quality_warnings_json),
        ),
    )
    conn.execute("DELETE FROM paper_chunks WHERE identity_key = ?", (identity_key,))
    for chunk in chunks:
        chunk_index = int(getattr(chunk, "chunk_index", 0))
        page_start = getattr(chunk, "page_start", None)
        page_end = getattr(chunk, "page_end", None)
        conn.execute(
            """
            INSERT INTO paper_chunks (
                chunk_id, identity_key, section_title, page_start, page_end, chunk_text, chunk_index,
                token_count, content_hash, chunk_type, page_mapping_confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{identity_key}::chunk:{chunk_index:05d}",
                identity_key,
                getattr(chunk, "section_title", "") or "",
                int(page_start) if page_start else None,
                int(page_end) if page_end else None,
                getattr(chunk, "chunk_text", "") or "",
                chunk_index,
                int(getattr(chunk, "token_count", 0) or 0),
                getattr(chunk, "content_hash", "") or "",
                getattr(chunk, "chunk_type", "body") or "body",
                float(getattr(chunk, "page_mapping_confidence", 0.0) or 0.0),
            ),
        )
    rebuild_chunk_fts(conn, identity_key)
    prune_stale_fulltext_embeddings(conn, identity_key)
    return {
        "identity_key": identity_key,
        "parse_status": PARSE_STATUS_PARSED,
        "parse_error": "",
        "page_count": int(page_count or 0),
        "parsed_at": now,
        "chunk_count": len(chunks),
        "parse_engine": parse_engine or "marker",
        "markdown_path": markdown_path or "",
        "parse_quality": parse_quality or PARSE_QUALITY_WARNING,
        "page_mapping_coverage": float(page_mapping_coverage or 0.0),
        "text_length": int(text_length or 0),
        "quality_warnings": json.loads(_json_text(quality_warnings_json) or "[]"),
    }


def update_fulltext_content(
    conn: sqlite3.Connection,
    *,
    identity_key: str,
    markdown_text: str,
    page_count: int,
    chunks: list[Any],
    markdown_path: str = "",
    parse_engine: str = "marker",
    parse_quality: str = PARSE_QUALITY_WARNING,
    page_mapping_coverage: float = 0.0,
    text_length: int = 0,
    quality_warnings_json: str = "[]",
) -> dict[str, Any]:
    return replace_parse_result(
        conn,
        identity_key=identity_key,
        full_text=markdown_text,
        markdown_text=markdown_text,
        markdown_path=markdown_path,
        parse_engine=parse_engine,
        page_count=page_count,
        chunks=chunks,
        parse_quality=parse_quality,
        page_mapping_coverage=page_mapping_coverage,
        text_length=text_length,
        quality_warnings_json=quality_warnings_json,
    )


def list_chunks(conn: sqlite3.Connection, identity_key: str, *, limit: int = 50) -> list[dict[str, Any]]:
    ensure_schema(conn)
    rows = conn.execute(
        """
        SELECT chunk_id, identity_key, section_title, page_start, page_end, chunk_text, chunk_index,
               COALESCE(token_count, 0) AS token_count,
               COALESCE(content_hash, '') AS content_hash,
               COALESCE(chunk_type, 'body') AS chunk_type,
               COALESCE(page_mapping_confidence, 0) AS page_mapping_confidence
        FROM paper_chunks
        WHERE identity_key = ?
        ORDER BY chunk_index ASC
        LIMIT ?
        """,
        (identity_key, int(limit)),
    ).fetchall()
    return [dict(row) for row in rows]


def count_chunks(conn: sqlite3.Connection, identity_key: str) -> int:
    ensure_schema(conn)
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM paper_chunks WHERE identity_key = ?",
            (identity_key,),
        ).fetchone()[0]
        or 0
    )


def mark_cached_parse_valid(conn: sqlite3.Connection, identity_key: str) -> dict[str, Any]:
    ensure_schema(conn)
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """
        UPDATE paper_fulltext
        SET parse_status = ?, parse_error = '', parsed_at = ?
        WHERE identity_key = ?
        """,
        (PARSE_STATUS_PARSED, now, identity_key),
    )
    row = get_fulltext(conn, identity_key)
    warnings = []
    if row and row["quality_warnings_json"]:
        try:
            warnings = json.loads(row["quality_warnings_json"])
        except Exception:
            warnings = []
    return {
        "identity_key": identity_key,
        "parse_status": PARSE_STATUS_PARSED,
        "parse_error": "",
        "page_count": int(row["page_count"] or 0) if row else 0,
        "parsed_at": now,
        "chunk_count": count_chunks(conn, identity_key),
        "parse_engine": (row["parse_engine"] if row else "") or "marker",
        "markdown_path": (row["markdown_path"] if row else "") or "",
        "parse_quality": (row["parse_quality"] if row else "") or PARSE_QUALITY_WARNING,
        "page_mapping_coverage": float(row["page_mapping_coverage"] or 0) if row else 0.0,
        "text_length": int(row["text_length"] or 0) if row else 0,
        "quality_warnings": warnings,
    }


def mark_not_parsed(conn: sqlite3.Connection, *, identity_key: str) -> dict[str, Any]:
    ensure_schema(conn)
    conn.execute("DELETE FROM paper_chunks WHERE identity_key = ?", (identity_key,))
    delete_chunk_fts(conn, identity_key)
    conn.execute(
        "DELETE FROM knowledge_embeddings WHERE identity_key = ? AND source_type = 'fulltext'",
        (identity_key,),
    )
    conn.execute("DELETE FROM paper_fulltext WHERE identity_key = ?", (identity_key,))
    return {
        "identity_key": identity_key,
        "parse_status": PARSE_STATUS_NOT_PARSED,
        "parse_error": "",
        "page_count": 0,
        "parsed_at": "",
        "chunk_count": 0,
        "parse_engine": "marker",
        "markdown_path": "",
        "parse_quality": "",
        "page_mapping_coverage": 0.0,
        "text_length": 0,
        "quality_warnings": [],
    }


def upsert_pending(conn: sqlite3.Connection, *, identity_key: str, doi: str = "", pdf_url: str = "") -> None:
    ensure_schema(conn)
    conn.execute(
        """
        INSERT INTO paper_documents (
            identity_key, doi, pdf_url, pdf_path, download_status, download_error, downloaded_at
        ) VALUES (?, ?, ?, '', ?, '', '')
        ON CONFLICT(identity_key) DO UPDATE SET
            doi = excluded.doi,
            pdf_url = CASE WHEN excluded.pdf_url != '' THEN excluded.pdf_url ELSE paper_documents.pdf_url END
        """,
        (identity_key, doi or "", pdf_url or "", STATUS_NOT_DOWNLOADED),
    )


def mark_downloaded(
    conn: sqlite3.Connection,
    *,
    identity_key: str,
    doi: str = "",
    pdf_url: str = "",
    pdf_path: str,
    pdf_source: str = PDF_SOURCE_LEGACY,
) -> dict[str, Any]:
    ensure_schema(conn)
    now = datetime.now().isoformat(timespec="seconds")
    normalized_source = pdf_source if pdf_source in {PDF_SOURCE_UPLOAD, PDF_SOURCE_LEGACY} else PDF_SOURCE_LEGACY
    conn.execute(
        """
        INSERT INTO paper_documents (
            identity_key, doi, pdf_url, pdf_path, download_status, download_error, downloaded_at, pdf_source
        ) VALUES (?, ?, ?, ?, ?, '', ?, ?)
        ON CONFLICT(identity_key) DO UPDATE SET
            doi = excluded.doi,
            pdf_url = excluded.pdf_url,
            pdf_path = excluded.pdf_path,
            download_status = excluded.download_status,
            download_error = '',
            downloaded_at = excluded.downloaded_at,
            pdf_source = excluded.pdf_source
        """,
        (identity_key, doi or "", pdf_url or "", pdf_path, STATUS_DOWNLOADED, now, normalized_source),
    )
    return {
        "identity_key": identity_key,
        "doi": doi or "",
        "pdf_url": pdf_url or "",
        "pdf_path": pdf_path,
        "download_status": STATUS_DOWNLOADED,
        "download_error": "",
        "downloaded_at": now,
        "pdf_source": normalized_source,
    }


def mark_failed(
    conn: sqlite3.Connection,
    *,
    identity_key: str,
    doi: str = "",
    pdf_url: str = "",
    error: str,
) -> dict[str, Any]:
    ensure_schema(conn)
    message = str(error or "PDF 下载失败")[:1000]
    conn.execute(
        """
        INSERT INTO paper_documents (
            identity_key, doi, pdf_url, pdf_path, download_status, download_error, downloaded_at, pdf_source
        ) VALUES (?, ?, ?, '', ?, ?, '', '')
        ON CONFLICT(identity_key) DO UPDATE SET
            doi = excluded.doi,
            pdf_url = excluded.pdf_url,
            download_status = excluded.download_status,
            download_error = excluded.download_error,
            pdf_source = ''
        """,
        (identity_key, doi or "", pdf_url or "", STATUS_FAILED, message),
    )
    return {
        "identity_key": identity_key,
        "doi": doi or "",
        "pdf_url": pdf_url or "",
        "pdf_path": "",
        "download_status": STATUS_FAILED,
        "download_error": message,
        "downloaded_at": "",
        "pdf_source": "",
    }


def mark_not_downloaded(
    conn: sqlite3.Connection,
    *,
    identity_key: str,
    doi: str = "",
    pdf_url: str = "",
) -> dict[str, Any]:
    ensure_schema(conn)
    conn.execute(
        """
        INSERT INTO paper_documents (
            identity_key, doi, pdf_url, pdf_path, download_status, download_error, downloaded_at
        ) VALUES (?, ?, ?, '', ?, '', '')
        ON CONFLICT(identity_key) DO UPDATE SET
            doi = CASE WHEN excluded.doi != '' THEN excluded.doi ELSE paper_documents.doi END,
            pdf_url = CASE WHEN excluded.pdf_url != '' THEN excluded.pdf_url ELSE paper_documents.pdf_url END,
            pdf_path = '',
            download_status = excluded.download_status,
            download_error = '',
            downloaded_at = '',
            pdf_source = ''
        """,
        (identity_key, doi or "", pdf_url or "", STATUS_NOT_DOWNLOADED),
    )
    return {
        "identity_key": identity_key,
        "doi": doi or "",
        "pdf_url": pdf_url or "",
        "pdf_path": "",
        "download_status": STATUS_NOT_DOWNLOADED,
        "download_error": "",
        "downloaded_at": "",
        "pdf_source": "",
    }


def create_qa_session(conn: sqlite3.Connection, *, session_id: str, title: str, scope_type: str, scope_json: str) -> dict[str, Any]:
    ensure_schema(conn)
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


def list_qa_sessions(conn: sqlite3.Connection, *, limit: int = 50, identity_key: str = "") -> list[dict[str, Any]]:
    ensure_schema(conn)
    if identity_key:
        rows = conn.execute(
            """
            SELECT session_id, title, scope_type, scope_json, created_at, updated_at
            FROM qa_sessions
            WHERE scope_type = 'current_paper'
              AND json_extract(scope_json, '$.identity_key') = ?
            ORDER BY updated_at DESC, created_at DESC
            LIMIT ?
            """,
            (identity_key, int(limit)),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT session_id, title, scope_type, scope_json, created_at, updated_at
            FROM qa_sessions
            ORDER BY updated_at DESC, created_at DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    return [dict(row) for row in rows]


def get_qa_session(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
    ensure_schema(conn)
    return conn.execute(
        "SELECT session_id, title, scope_type, scope_json, created_at, updated_at FROM qa_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()


def create_qa_message(
    conn: sqlite3.Connection,
    *,
    message_id: str,
    session_id: str,
    role: str,
    content: str,
    model: str = "",
    token_usage: dict[str, Any] | None = None,
    retrieval_mode: str = "",
) -> dict[str, Any]:
    ensure_schema(conn)
    now = datetime.now().isoformat(timespec="seconds")
    usage = token_usage or {}
    conn.execute(
        """
        INSERT INTO qa_messages (
            message_id, session_id, role, content, model,
            prompt_tokens, completion_tokens, total_tokens, retrieval_mode, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            message_id, session_id, role, content, model or None,
            usage.get("prompt_tokens"), usage.get("completion_tokens"), usage.get("total_tokens"),
            retrieval_mode or None, now,
        ),
    )
    conn.execute(
        "UPDATE qa_sessions SET updated_at = ? WHERE session_id = ?",
        (now, session_id),
    )
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
        "created_at": now,
    }


def save_qa_citations(conn: sqlite3.Connection, *, message_id: str, citations: list[dict[str, Any]]) -> None:
    ensure_schema(conn)
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


def get_qa_session_detail(conn: sqlite3.Connection, session_id: str) -> dict[str, Any] | None:
    ensure_schema(conn)
    session_row = get_qa_session(conn, session_id)
    if session_row is None:
        return None
    messages = []
    rows = conn.execute(
        """
        SELECT message_id, session_id, role, content, model,
               prompt_tokens, completion_tokens, total_tokens, retrieval_mode, created_at
        FROM qa_messages
        WHERE session_id = ?
        ORDER BY created_at ASC
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
    payload = dict(session_row)
    payload["messages"] = messages
    return payload


def delete_qa_session(conn: sqlite3.Connection, session_id: str) -> int:
    ensure_schema(conn)
    cursor = conn.execute("DELETE FROM qa_sessions WHERE session_id = ?", (session_id,))
    return int(cursor.rowcount or 0)


def upsert_knowledge_embedding(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    identity_key: str,
    source_type: str,
    content_hash: str,
    embedding_model: str,
    embedding: list[float],
) -> None:
    ensure_schema(conn)
    try:
        normalized_embedding = [float(value) for value in embedding]
    except (TypeError, ValueError) as exc:
        raise ValueError("embedding 必须是数值数组") from exc
    if not normalized_embedding or not all(math.isfinite(value) for value in normalized_embedding):
        raise ValueError("embedding 不能为空且必须只包含有限数值")
    conn.execute(
        """
        INSERT INTO knowledge_embeddings (
            source_id, identity_key, source_type, content_hash, embedding_model,
            dimensions, embedding_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id, embedding_model) DO UPDATE SET
            identity_key = excluded.identity_key,
            source_type = excluded.source_type,
            content_hash = excluded.content_hash,
            embedding_model = excluded.embedding_model,
            dimensions = excluded.dimensions,
            embedding_json = excluded.embedding_json,
            updated_at = excluded.updated_at
        """,
        (
            source_id,
            identity_key,
            source_type,
            content_hash,
            embedding_model,
            len(normalized_embedding),
            json.dumps(normalized_embedding, ensure_ascii=False, separators=(",", ":")),
            datetime.now().isoformat(timespec="seconds"),
        ),
    )


def prune_stale_fulltext_embeddings(conn: sqlite3.Connection, identity_key: str) -> int:
    ensure_schema(conn)
    rows = conn.execute(
        """
        SELECT embedding.source_id, embedding.embedding_model, embedding.content_hash,
               chunk.chunk_text
        FROM knowledge_embeddings AS embedding
        LEFT JOIN paper_chunks AS chunk
          ON chunk.chunk_id = embedding.source_id
         AND chunk.identity_key = embedding.identity_key
        WHERE embedding.identity_key = ? AND embedding.source_type = 'fulltext'
        """,
        (identity_key,),
    ).fetchall()
    stale = []
    for row in rows:
        text = row["chunk_text"]
        current_hash = ""
        if text is not None:
            current_hash = hashlib.sha256(str(text).encode("utf-8")).hexdigest()
        if current_hash != str(row["content_hash"] or ""):
            stale.append((str(row["source_id"]), str(row["embedding_model"])))
    if stale:
        conn.executemany(
            "DELETE FROM knowledge_embeddings WHERE source_id = ? AND embedding_model = ?",
            stale,
        )
    return len(stale)


def prune_embedding_index(
    conn: sqlite3.Connection,
    *,
    model: str,
    identity_keys: list[str],
    valid_hashes: dict[str, str],
) -> int:
    ensure_schema(conn)
    normalized_keys = [str(value) for value in identity_keys if str(value or "").strip()]
    stale: list[tuple[str, str]] = []
    for start in range(0, len(normalized_keys), 400):
        batch = normalized_keys[start:start + 400]
        placeholders = ",".join("?" for _ in batch)
        rows = conn.execute(
            f"""
            SELECT source_id, content_hash, dimensions, embedding_json
            FROM knowledge_embeddings
            WHERE embedding_model = ? AND identity_key IN ({placeholders})
            """,
            [model, *batch],
        ).fetchall()
        stale.extend(
            (str(row["source_id"]), model)
            for row in rows
            if (
                valid_hashes.get(str(row["source_id"])) != str(row["content_hash"] or "")
                or not _embedding_payload_is_valid(row["embedding_json"], row["dimensions"])
            )
        )
    if stale:
        conn.executemany(
            "DELETE FROM knowledge_embeddings WHERE source_id = ? AND embedding_model = ?",
            stale,
        )
    return len(stale)


def get_embedding_hashes(conn: sqlite3.Connection, *, model: str) -> dict[str, str]:
    ensure_schema(conn)
    rows = conn.execute(
        """
        SELECT source_id, content_hash, dimensions, embedding_json
        FROM knowledge_embeddings
        WHERE embedding_model = ?
        """,
        (model,),
    ).fetchall()
    return {
        str(row["source_id"]): str(row["content_hash"] or "")
        for row in rows
        if _embedding_payload_is_valid(row["embedding_json"], row["dimensions"])
    }


def get_chunk_by_id(conn: sqlite3.Connection, chunk_id: str) -> dict[str, Any] | None:
    ensure_schema(conn)
    row = conn.execute(
        """
        SELECT chunk_id, identity_key, section_title, page_start, page_end, chunk_text, chunk_index,
               COALESCE(token_count, 0) AS token_count,
               COALESCE(content_hash, '') AS content_hash,
               COALESCE(chunk_type, 'body') AS chunk_type,
               COALESCE(page_mapping_confidence, 0) AS page_mapping_confidence
        FROM paper_chunks
        WHERE chunk_id = ?
        """,
        (chunk_id,),
    ).fetchone()
    return dict(row) if row else None
