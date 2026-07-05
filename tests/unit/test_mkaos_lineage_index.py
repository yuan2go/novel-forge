from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos_lineage import build_lineage_index, query_lineage_path
from novel_forge.schemas import BaseAsset
from novel_forge.storage.local import LocalStorage


class MkaosLineageIndexTests(unittest.TestCase):
    def test_lineage_index_links_source_to_draft_without_raw_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            ids = _seed_lineage_assets(storage)

            index = build_lineage_index(storage, project_id="lineage-p")

            self.assertGreaterEqual(index["node_count"], 5)
            self.assertFalse(index["source_isolation"]["raw_text_included"])
            self.assertFalse("raw source" in str(index))
            path = query_lineage_path(storage, {"project_id": "lineage-p", "source_asset_id": ids["source"], "target_asset_id": ids["draft"], "persist": False})
            self.assertGreaterEqual(path["path_count"], 1)
            self.assertIn("source", path["paths"][0]["path"][0]["asset_id"])


def _seed_lineage_assets(storage: LocalStorage) -> dict[str, str]:
    source = BaseAsset(id="source-1", type="source_document", title="Source", source="fixture", content={"title": "safe"}, metadata={"project_id": "lineage-p"})
    chunk = BaseAsset(id="chunk-1", type="source_chunk", title="Chunk", source="source-1", content={"source_document_id": "source-1", "content_hash": "h1"}, metadata={"project_id": "lineage-p"}, references=["source-1"])
    knowledge = BaseAsset(id="knowledge-1", type="knowledge_card", title="Knowledge", source="chunk-1", content={"concept_name": "机制", "source_chunk_ids": ["chunk-1"], "applicable_flows": ["prose"]}, metadata={"project_id": "lineage-p"}, references=["chunk-1"])
    pack = BaseAsset(id="pack-1", type="knowledge_pack", title="Pack", source="mkaos", content={"pack_items": [{"knowledge_id": "knowledge-1"}]}, metadata={"project_id": "lineage-p"}, references=["knowledge-1"])
    context = BaseAsset(id="context-1", type="context_bundle", title="Context", source="pack-1", content={"context_bundle_id": "context-1", "knowledge_pack_id": "pack-1", "selected_knowledge_ids": ["knowledge-1"]}, metadata={"project_id": "lineage-p"}, references=["pack-1", "knowledge-1"])
    draft = BaseAsset(id="draft-1", type="draft_chapter", title="Draft", source="context-1", content={"context_bundle_id": "context-1", "text": "safe generated text"}, metadata={"project_id": "lineage-p"}, references=["context-1"])
    for category, asset in [("raw", source), ("raw", chunk), ("knowledge", knowledge), ("contexts", pack), ("contexts", context), ("drafts", draft)]:
        storage.write_asset(category, asset)
    return {"source": source.id, "chunk": chunk.id, "knowledge": knowledge.id, "pack": pack.id, "context": context.id, "draft": draft.id}


if __name__ == "__main__":
    unittest.main()
