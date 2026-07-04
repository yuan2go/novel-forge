from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


class MkaosEvidenceSpanTests(MkaosP1TestCase):
    def test_span_metadata_and_pack_reference_no_raw_text(self):
        seeded = self.seed_knowledge_system()
        span = seeded["span"]["asset"]["content"]
        self.assertEqual(span["source_chunk_id"], seeded["chunk_id"])
        self.assertTrue(span["evidence_hash"])
        pack = mkaos.build_knowledge_pack(self.storage, {"project_id": self.project_id, "flow": "prose", "task_id": "span-pack"})
        self.assertFalse(pack["asset"]["content"]["source_isolation"]["prose_raw_source_text_included"])
        self.assertNotIn("历史制度会改变资源分配", str(pack["asset"]["content"]))
        spans = mkaos.list_evidence_spans(self.storage, source_chunk_id=seeded["chunk_id"])
        self.assertTrue(spans)
