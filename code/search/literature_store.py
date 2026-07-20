#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from data_sources.common import OUTPUT_COLUMNS, PaperRecord, clean_text, normalize_doi, normalize_title_key


LIBRARY_DB_NAME = "literature_library.sqlite"


PAPER_COLUMNS = [
    "query",
    "paperId",
    "source",
    "title",
    "authors",
    "institutions",
    "abstract",
    "year",
    "venue",
    "volume",
    "issue",
    "publicationDate",
    "citationCount",
    "doi",
    "url",
    "pdf_url",
    "source_ids_json",
    "externalIds_json",
    "enrichment_sources",
]


def library_db_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / LIBRARY_DB_NAME


def connect_library(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS papers (
            identity_key TEXT PRIMARY KEY,
            normalized_title TEXT,
            query TEXT,
            paperId TEXT,
            source TEXT,
            title TEXT,
            authors TEXT,
            institutions TEXT,
            abstract TEXT,
            year TEXT,
            venue TEXT,
            volume TEXT,
            issue TEXT,
            publicationDate TEXT,
            citationCount TEXT,
            doi TEXT,
            url TEXT,
            pdf_url TEXT,
            source_ids_json TEXT,
            externalIds_json TEXT,
            enrichment_sources TEXT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            last_dataset TEXT,
            discovery_count INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS search_runs (
            run_id TEXT PRIMARY KEY,
            query TEXT,
            run_type TEXT,
            run_date TEXT,
            sources_json TEXT,
            output_csv TEXT,
            output_jsonl TEXT,
            record_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    ensure_paper_columns(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS run_papers (
            run_id TEXT NOT NULL,
            identity_key TEXT NOT NULL,
            PRIMARY KEY (run_id, identity_key),
            FOREIGN KEY (run_id) REFERENCES search_runs(run_id) ON DELETE CASCADE,
            FOREIGN KEY (identity_key) REFERENCES papers(identity_key) ON DELETE CASCADE
        )
        """
    )


def ensure_paper_columns(conn: sqlite3.Connection) -> None:
    existing_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(papers)").fetchall()
    }
    for column in PAPER_COLUMNS:
        if column not in existing_columns:
            conn.execute(f"ALTER TABLE papers ADD COLUMN {column} TEXT")
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
    document_columns = {row[1] for row in conn.execute("PRAGMA table_info(paper_documents)").fetchall()}
    if "pdf_source" not in document_columns:
        conn.execute("ALTER TABLE paper_documents ADD COLUMN pdf_source TEXT NOT NULL DEFAULT ''")
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
    fulltext_columns = {row[1] for row in conn.execute("PRAGMA table_info(paper_fulltext)").fetchall()}
    if "parse_quality" not in fulltext_columns:
        conn.execute("ALTER TABLE paper_fulltext ADD COLUMN parse_quality TEXT DEFAULT 'warning'")
    if "page_mapping_coverage" not in fulltext_columns:
        conn.execute("ALTER TABLE paper_fulltext ADD COLUMN page_mapping_coverage REAL NOT NULL DEFAULT 0")
    if "text_length" not in fulltext_columns:
        conn.execute("ALTER TABLE paper_fulltext ADD COLUMN text_length INTEGER NOT NULL DEFAULT 0")
    if "quality_warnings_json" not in fulltext_columns:
        conn.execute("ALTER TABLE paper_fulltext ADD COLUMN quality_warnings_json TEXT DEFAULT '[]'")
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
    chunk_columns = {row[1] for row in conn.execute("PRAGMA table_info(paper_chunks)").fetchall()}
    if "token_count" not in chunk_columns:
        conn.execute("ALTER TABLE paper_chunks ADD COLUMN token_count INTEGER NOT NULL DEFAULT 0")
    if "content_hash" not in chunk_columns:
        conn.execute("ALTER TABLE paper_chunks ADD COLUMN content_hash TEXT")
    if "chunk_type" not in chunk_columns:
        conn.execute("ALTER TABLE paper_chunks ADD COLUMN chunk_type TEXT NOT NULL DEFAULT 'body'")
    if "page_mapping_confidence" not in chunk_columns:
        conn.execute("ALTER TABLE paper_chunks ADD COLUMN page_mapping_confidence REAL NOT NULL DEFAULT 0")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS library_collections (
            collection_id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            collection_type TEXT NOT NULL DEFAULT 'custom',
            description TEXT,
            rules_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS collection_papers (
            collection_id TEXT NOT NULL,
            identity_key TEXT NOT NULL,
            match_source TEXT NOT NULL DEFAULT 'manual',
            match_score REAL NOT NULL DEFAULT 1.0,
            note TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (collection_id, identity_key),
            FOREIGN KEY (collection_id) REFERENCES library_collections(collection_id) ON DELETE CASCADE,
            FOREIGN KEY (identity_key) REFERENCES papers(identity_key) ON DELETE CASCADE
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_title ON papers(normalized_title)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_query_date ON search_runs(query, run_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_documents_status ON paper_documents(download_status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_fulltext_status ON paper_fulltext(parse_status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_chunks_identity ON paper_chunks(identity_key, chunk_index)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_collection_papers_identity ON collection_papers(identity_key)")
    conn.commit()


def identity_key_for_record(record: PaperRecord) -> str:
    doi = normalize_doi(record.doi)
    if doi:
        return f"doi:{doi}"
    title_key = normalize_title_key(record.title)
    if title_key:
        return f"title:{title_key}"
    source = clean_text(record.source) or "unknown"
    paper_id = clean_text(record.paperId)
    return f"source:{source}:{paper_id or id(record)}"


def parse_json_dict(value: Any) -> dict[str, Any]:
    text = clean_text(value)
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def merge_json_dicts(current: Any, candidate: Any) -> str:
    merged = parse_json_dict(current)
    merged.update({k: v for k, v in parse_json_dict(candidate).items() if v})
    return json.dumps(merged, ensure_ascii=False)


def merge_semicolon_values(current: Any, candidate: Any) -> str:
    values = []
    seen = set()
    for raw in [current, candidate]:
        for item in clean_text(raw).split(";"):
            item = item.strip()
            if item and item not in seen:
                seen.add(item)
                values.append(item)
    return ";".join(values)


def choose_value(field: str, current: Any, candidate: Any) -> str:
    current_text = clean_text(current)
    candidate_text = clean_text(candidate)
    if not candidate_text:
        return current_text
    if not current_text:
        return candidate_text
    if field == "abstract" and len(candidate_text) > len(current_text) * 1.2:
        return candidate_text
    if field == "citationCount":
        try:
            return str(max(int(float(current_text)), int(float(candidate_text))))
        except ValueError:
            return current_text
    return current_text


def normalize_row(row: dict[str, Any]) -> dict[str, str]:
    normalized = {column: clean_text(row.get(column, "")) for column in PAPER_COLUMNS}
    normalized["doi"] = normalize_doi(normalized.get("doi"))
    return normalized


def record_to_library_row(record: PaperRecord) -> dict[str, str]:
    row = record.to_row()
    normalized = normalize_row(row)
    normalized["source_ids_json"] = clean_text(row.get("source_ids_json")) or "{}"
    normalized["externalIds_json"] = clean_text(row.get("externalIds_json")) or "{}"
    return normalized


def upsert_paper(
    conn: sqlite3.Connection,
    record: PaperRecord,
    *,
    dataset_path: str = "",
    seen_at: str = "",
) -> tuple[str, bool]:
    now = seen_at or datetime.now().isoformat(timespec="seconds")
    key = identity_key_for_record(record)
    incoming = record_to_library_row(record)
    incoming["normalized_title"] = normalize_title_key(incoming.get("title"))
    existing = conn.execute("SELECT * FROM papers WHERE identity_key = ?", (key,)).fetchone()

    if existing is None:
        values = {
            "identity_key": key,
            "normalized_title": incoming["normalized_title"],
            **incoming,
            "first_seen_at": now,
            "last_seen_at": now,
            "last_dataset": dataset_path,
            "discovery_count": 1,
        }
        columns = [
            "identity_key",
            "normalized_title",
            *PAPER_COLUMNS,
            "first_seen_at",
            "last_seen_at",
            "last_dataset",
            "discovery_count",
        ]
        placeholders = ", ".join("?" for _ in columns)
        conn.execute(
            f"INSERT INTO papers ({', '.join(columns)}) VALUES ({placeholders})",
            [values.get(column, "") for column in columns],
        )
        return key, True

    merged = {}
    for column in PAPER_COLUMNS:
        if column in {"source_ids_json", "externalIds_json"}:
            merged[column] = merge_json_dicts(existing[column], incoming[column])
        elif column in {"query", "source", "enrichment_sources"}:
            merged[column] = merge_semicolon_values(existing[column], incoming[column])
        else:
            merged[column] = choose_value(column, existing[column], incoming[column])
    merged["normalized_title"] = normalize_title_key(merged.get("title"))

    assignments = ", ".join(f"{column} = ?" for column in ["normalized_title", *PAPER_COLUMNS])
    conn.execute(
        f"""
        UPDATE papers
        SET {assignments},
            last_seen_at = ?,
            last_dataset = ?,
            discovery_count = discovery_count + 1
        WHERE identity_key = ?
        """,
        [merged.get(column, "") for column in ["normalized_title", *PAPER_COLUMNS]]
        + [now, dataset_path, key],
    )
    return key, False


def record_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    query: str,
    run_type: str,
    sources: Iterable[str],
    csv_path: str = "",
    jsonl_path: str = "",
    record_count: int = 0,
    created_at: str = "",
) -> None:
    now = created_at or datetime.now().isoformat(timespec="seconds")
    run_date = now[:10]
    conn.execute(
        """
        INSERT OR REPLACE INTO search_runs (
            run_id, query, run_type, run_date, sources_json,
            output_csv, output_jsonl, record_count, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            query,
            run_type,
            run_date,
            json.dumps(list(sources), ensure_ascii=False),
            csv_path,
            jsonl_path,
            int(record_count),
            now,
        ),
    )


def upsert_records(
    records: list[PaperRecord],
    *,
    output_dir: str | Path,
    run_id: str,
    query: str,
    run_type: str,
    sources: Iterable[str],
    csv_path: str | Path = "",
    jsonl_path: str | Path = "",
) -> dict[str, Any]:
    db_path = library_db_path(output_dir)
    now = datetime.now().isoformat(timespec="seconds")
    csv_text = str(csv_path) if csv_path else ""
    jsonl_text = str(jsonl_path) if jsonl_path else ""
    inserted = 0
    updated = 0

    with connect_library(db_path) as conn:
        record_run(
            conn,
            run_id=run_id,
            query=query,
            run_type=run_type,
            sources=sources,
            csv_path=csv_text,
            jsonl_path=jsonl_text,
            record_count=len(records),
            created_at=now,
        )
        for record in records:
            key, was_inserted = upsert_paper(conn, record, dataset_path=csv_text, seen_at=now)
            if was_inserted:
                inserted += 1
            else:
                updated += 1
            conn.execute(
                "INSERT OR IGNORE INTO run_papers (run_id, identity_key) VALUES (?, ?)",
                (run_id, key),
            )
        conn.commit()

    return {
        "db_path": db_path,
        "inserted": inserted,
        "updated": updated,
        "total": len(records),
    }
