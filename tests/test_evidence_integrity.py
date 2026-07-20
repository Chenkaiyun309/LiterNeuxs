#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import sqlite3
import sys
import unittest
from pathlib import Path


CODE_DIR = Path(__file__).resolve().parents[1] / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from documents import chunker, pdf_store  # noqa: E402
from documents.page_extractor import ExtractedPage  # noqa: E402
from qa import citation_validator, retriever  # noqa: E402


def memory_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("CREATE TABLE papers (identity_key TEXT PRIMARY KEY, abstract TEXT DEFAULT '')")
    return conn


class PageMappingTests(unittest.TestCase):
    def test_disconnected_page_matches_are_not_merged_into_one_span(self) -> None:
        pages = [
            ExtractedPage(1, "alpha catalyst improves tensile strength under cyclic loading"),
            ExtractedPage(2, "unrelated experimental apparatus and calibration details"),
            ExtractedPage(3, "alpha catalyst improves tensile strength under cyclic loading"),
        ]

        start, end, confidence = chunker._page_span_for_text(
            "alpha catalyst improves tensile strength under cyclic loading",
            pages,
        )

        self.assertEqual(start, end)
        self.assertEqual(start, 1)
        self.assertGreater(confidence, 0.2)

    def test_page_floor_prevents_backward_mapping(self) -> None:
        pages = [
            ExtractedPage(1, "phase transformation increases hardness after annealing"),
            ExtractedPage(2, "microstructure observations begin on this page"),
            ExtractedPage(3, "phase transformation increases hardness after annealing and cooling"),
        ]

        start, _, _ = chunker._page_span_for_text(
            "phase transformation increases hardness after annealing",
            pages,
            min_page_number=2,
        )

        self.assertEqual(start, 3)


class FtsIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = memory_connection()
        self.conn.execute("INSERT INTO papers (identity_key) VALUES ('paper:1')")
        pdf_store.ensure_schema(self.conn)
        pdf_store.ensure_fts_schema(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_chunk_mutations_keep_fts_in_sync(self) -> None:
        self.conn.execute(
            """
            INSERT INTO paper_chunks (
                chunk_id, identity_key, section_title, chunk_text, chunk_index, content_hash
            ) VALUES ('chunk:1', 'paper:1', 'Results', 'alpha strength result', 0, 'hash-a')
            """
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM paper_chunks_fts WHERE paper_chunks_fts MATCH 'alpha'").fetchone()[0],
            1,
        )

        self.conn.execute("UPDATE paper_chunks SET chunk_text = 'beta fatigue result' WHERE chunk_id = 'chunk:1'")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM paper_chunks_fts WHERE paper_chunks_fts MATCH 'alpha'").fetchone()[0],
            0,
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM paper_chunks_fts WHERE paper_chunks_fts MATCH 'beta'").fetchone()[0],
            1,
        )

        self.conn.execute("DELETE FROM papers WHERE identity_key = 'paper:1'")
        self.assertTrue(pdf_store.chunk_fts_integrity(self.conn)["ok"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM paper_chunks_fts").fetchone()[0], 0)

    def test_integrity_check_and_repair_remove_orphans(self) -> None:
        self.conn.execute(
            "INSERT INTO paper_chunks_fts (chunk_id, identity_key, section_title, chunk_text) VALUES (?, ?, ?, ?)",
            ("orphan", "missing", "", "orphan text"),
        )
        self.assertFalse(pdf_store.chunk_fts_integrity(self.conn)["ok"])

        pdf_store.repair_chunk_fts_integrity(self.conn)

        self.assertTrue(pdf_store.chunk_fts_integrity(self.conn)["ok"])


class EmbeddingLifecycleTests(unittest.TestCase):
    def test_old_schema_migrates_and_models_coexist(self) -> None:
        conn = memory_connection()
        conn.execute("INSERT INTO papers (identity_key) VALUES ('paper:1')")
        conn.execute(
            """
            CREATE TABLE knowledge_embeddings (
                source_id TEXT PRIMARY KEY,
                identity_key TEXT NOT NULL,
                source_type TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                embedding_model TEXT NOT NULL,
                dimensions INTEGER NOT NULL,
                embedding_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO knowledge_embeddings VALUES ('chunk:1', 'paper:1', 'fulltext', 'h1', 'model-a', 2, '[1,0]', 'now')"
        )

        pdf_store.ensure_schema(conn)
        pdf_store.upsert_knowledge_embedding(
            conn,
            source_id="chunk:1",
            identity_key="paper:1",
            source_type="fulltext",
            content_hash="h1",
            embedding_model="model-b",
            embedding=[0.0, 1.0],
        )

        models = {
            row[0]
            for row in conn.execute(
                "SELECT embedding_model FROM knowledge_embeddings WHERE source_id = 'chunk:1'"
            ).fetchall()
        }
        self.assertEqual(models, {"model-a", "model-b"})
        conn.close()

    def test_changed_chunk_prunes_vectors_for_all_models(self) -> None:
        conn = memory_connection()
        conn.execute("INSERT INTO papers (identity_key) VALUES ('paper:1')")
        pdf_store.ensure_schema(conn)
        old_text = "original evidence"
        old_hash = hashlib.sha256(old_text.encode("utf-8")).hexdigest()
        conn.execute(
            """
            INSERT INTO paper_chunks (
                chunk_id, identity_key, section_title, chunk_text, chunk_index, content_hash
            ) VALUES ('chunk:1', 'paper:1', 'Results', ?, 0, ?)
            """,
            (old_text, old_hash),
        )
        for model in ("model-a", "model-b"):
            pdf_store.upsert_knowledge_embedding(
                conn,
                source_id="chunk:1",
                identity_key="paper:1",
                source_type="fulltext",
                content_hash=old_hash,
                embedding_model=model,
                embedding=[1.0, 0.0],
            )
        conn.execute(
            "UPDATE paper_chunks SET chunk_text = 'changed evidence', content_hash = 'changed' WHERE chunk_id = 'chunk:1'"
        )

        status = retriever.embedding_index_status(conn, model="model-a")
        self.assertEqual(status["total"], 0)
        self.assertEqual(status["stale"], 1)

        removed = pdf_store.prune_stale_fulltext_embeddings(conn, "paper:1")

        self.assertEqual(removed, 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM knowledge_embeddings").fetchone()[0], 0)
        conn.close()

    def test_corrupt_vector_is_not_treated_as_current(self) -> None:
        conn = memory_connection()
        conn.execute("INSERT INTO papers (identity_key) VALUES ('paper:1')")
        pdf_store.ensure_schema(conn)
        content_hash = hashlib.sha256(b"evidence").hexdigest()
        pdf_store.upsert_knowledge_embedding(
            conn,
            source_id="abstract::paper:1",
            identity_key="paper:1",
            source_type="abstract",
            content_hash=content_hash,
            embedding_model="model-a",
            embedding=[1.0, 0.0],
        )
        conn.execute(
            "UPDATE knowledge_embeddings SET embedding_json = '[1]' WHERE source_id = 'abstract::paper:1'"
        )

        self.assertEqual(pdf_store.get_embedding_hashes(conn, model="model-a"), {})
        removed = pdf_store.prune_embedding_index(
            conn,
            model="model-a",
            identity_keys=["paper:1"],
            valid_hashes={"abstract::paper:1": content_hash},
        )
        self.assertEqual(removed, 1)
        conn.close()


class CitationValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.allowed = {"chunk:1": {"chunk_text": "Measured strength increased by 20 percent."}}

    def test_sufficient_answer_requires_citation(self) -> None:
        with self.assertRaises(citation_validator.CitationValidationError):
            citation_validator.validate_qa_response(
                {"answer": "强度提高了。", "citations": [], "insufficient_evidence": False},
                self.allowed,
            )

    def test_answer_markers_must_match_citation_array(self) -> None:
        with self.assertRaises(citation_validator.CitationValidationError):
            citation_validator.validate_qa_response(
                {"answer": "强度提高了 [1]。", "citations": [], "insufficient_evidence": True},
                self.allowed,
            )

    def test_valid_citation_passes(self) -> None:
        result = citation_validator.validate_qa_response(
            {
                "answer": "实验测得强度提高了 20% [1]。",
                "citations": [
                    {"citation_order": 1, "chunk_id": "chunk:1", "claim": "强度提高了 20%"}
                ],
                "insufficient_evidence": False,
            },
            self.allowed,
        )
        self.assertEqual(result["citations"][0]["chunk_id"], "chunk:1")

    def test_citation_claim_cannot_be_empty(self) -> None:
        with self.assertRaises(citation_validator.CitationValidationError):
            citation_validator.validate_qa_response(
                {
                    "answer": "实验测得强度提高了 [1]。",
                    "citations": [{"citation_order": 1, "chunk_id": "chunk:1", "claim": ""}],
                    "insufficient_evidence": False,
                },
                self.allowed,
            )


if __name__ == "__main__":
    unittest.main()
