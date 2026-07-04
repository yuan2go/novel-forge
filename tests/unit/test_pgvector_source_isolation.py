from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.long_memory import create_memory_record
from novel_forge.modules.pgvector_store import build_embedding_job, hybrid_retrieve, rebuild_dirty_index, verify_pgvector_migration
from novel_forge.schemas import SourceDocument
from novel_forge.storage.local import LocalStorage


class PgVectorSourceIsolationTests(unittest.TestCase):
    def test_high_risk_source_document_is_rejected_from_embedding_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            source_path = storage.write_asset(
                "sources",
                SourceDocument(
                    title="Raw source",
                    content={"text": "raw reference text must not enter prose retrieval"},
                    metadata={"project_id": "pgv-p", "source_risk_level": "high", "raw_text_allowed": False},
                ),
            )

            job = build_embedding_job(storage, source_paths=[str(source_path.relative_to(storage.root))], project_id="pgv-p")
            verification = verify_pgvector_migration(storage, project_id="pgv-p")

            self.assertEqual(job["asset"]["content"]["chunk_count"], 0)
            self.assertTrue(job["rejected_sources"])
            self.assertEqual(verification["source_isolation"]["status"], "passed")

    def test_pgvector_retrieval_reports_context_builder_evidence_without_raw_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            memory = create_memory_record(
                storage,
                project_id="pgv-p",
                level="L4",
                memory_type="world_rule",
                title="Blue Gate",
                summary="Blue gates open only during a lawful eclipse.",
                content={"rule": "lawful eclipse"},
            )
            build_embedding_job(storage, source_paths=[memory["path"]], project_id="pgv-p")

            report = hybrid_retrieve(storage, query="blue gate eclipse", project_id="pgv-p", persist=False)
            rebuild = rebuild_dirty_index(storage, project_id="pgv-p", persist=False)

            self.assertTrue(report["results"])
            self.assertFalse(report["source_isolation"]["raw_source_text_included"])
            self.assertTrue(report["context_builder_evidence"]["result_refs"])
            self.assertEqual(rebuild["status"], "clean")
