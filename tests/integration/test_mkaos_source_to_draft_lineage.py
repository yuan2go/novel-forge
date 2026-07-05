from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos_lineage import build_lineage_index, query_lineage_path
from novel_forge.schemas import BaseAsset
from novel_forge.storage.local import LocalStorage


class MkaosSourceToDraftLineageTests(unittest.TestCase):
    def test_source_to_draft_path_is_queryable(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            for category, asset in _assets():
                storage.write_asset(category, asset)

            build_lineage_index(storage, project_id="source-draft")
            path = query_lineage_path(storage, {"project_id": "source-draft", "source_asset_id": "source-1", "target_asset_id": "draft-1", "persist": False})

            self.assertGreater(path["path_count"], 0)
            self.assertIn("selected_by_pack", str(path["paths"]))
            self.assertFalse(path["source_isolation"]["raw_text_included"])


def _assets():
    metadata = {"project_id": "source-draft"}
    return [
        ("raw", BaseAsset(id="source-1", type="source_document", title="Source", source="fixture", content={"source_kind": "professional_book"}, metadata=metadata)),
        ("raw", BaseAsset(id="chunk-1", type="source_chunk", title="Chunk", source="source-1", content={"source_document_id": "source-1", "content_hash": "h"}, metadata=metadata, references=["source-1"])),
        ("knowledge", BaseAsset(id="knowledge-1", type="knowledge_card", title="Knowledge", source="chunk-1", content={"source_chunk_ids": ["chunk-1"], "creative_principle": "abstract"}, metadata=metadata, references=["chunk-1"])),
        ("contexts", BaseAsset(id="pack-1", type="knowledge_pack", title="Pack", source="mkaos", content={"pack_items": [{"knowledge_id": "knowledge-1"}]}, metadata=metadata, references=["knowledge-1"])),
        ("contexts", BaseAsset(id="context-1", type="context_bundle", title="Context", source="pack-1", content={"knowledge_pack_id": "pack-1"}, metadata=metadata, references=["pack-1"])),
        ("drafts", BaseAsset(id="draft-1", type="draft_chapter", title="Draft", source="context-1", content={"context_bundle_id": "context-1", "text": "safe"}, metadata=metadata, references=["context-1"])),
    ]


if __name__ == "__main__":
    unittest.main()
