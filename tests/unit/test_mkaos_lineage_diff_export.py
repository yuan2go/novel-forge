from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos_lineage import build_lineage_index, diff_lineage_indexes, export_lineage_graph, query_lineage_path
from novel_forge.schemas import BaseAsset
from novel_forge.storage.local import LocalStorage


class MkaosLineageDiffExportTests(unittest.TestCase):
    def test_lineage_diff_export_and_semantic_path_ranking_are_source_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            ids = _seed_assets(storage)
            left = build_lineage_index(storage, project_id="lineage-diff-p", persist=False)
            storage.write_asset(
                "reviews",
                BaseAsset(
                    id="issue-1",
                    type="review_issue",
                    title="Issue",
                    source="draft-1",
                    content={"target_asset_id": "draft-1", "related_knowledge_ids": ["knowledge-1"], "issue_type": "source_leakage", "severity": "high"},
                    metadata={"project_id": "lineage-diff-p", "risk_level": "high"},
                    references=["draft-1", "knowledge-1"],
                ),
            )
            right = build_lineage_index(storage, project_id="lineage-diff-p", persist=True)

            diff = diff_lineage_indexes(storage, {"project_id": "lineage-diff-p", "left_index": left, "right_index": right, "persist": True})
            export = export_lineage_graph(storage, {"project_id": "lineage-diff-p", "rebuild": True, "persist": True})
            path = query_lineage_path(storage, {"project_id": "lineage-diff-p", "source_asset_id": ids["source"], "target_asset_id": "issue-1", "persist": False})

            self.assertTrue(any(node["asset_id"] == "issue-1" for node in diff["added_nodes"]))
            self.assertIn("clusters", export)
            self.assertTrue(export["semantic_ranking"]["top_edges"])
            self.assertIn("visualization", export)
            self.assertFalse("raw source" in str(export).lower())
            self.assertGreater(path["paths"][0]["semantic_score"], 0)
            self.assertFalse(path["paths"][0]["source_isolation"]["raw_text_included"])


def _seed_assets(storage: LocalStorage) -> dict[str, str]:
    source = BaseAsset(id="source-1", type="source_document", title="Source", source="fixture", content={"title": "safe"}, metadata={"project_id": "lineage-diff-p"})
    chunk = BaseAsset(id="chunk-1", type="source_chunk", title="Chunk", source="source-1", content={"source_document_id": "source-1", "content_hash": "h1"}, metadata={"project_id": "lineage-diff-p"}, references=["source-1"])
    knowledge = BaseAsset(id="knowledge-1", type="knowledge_card", title="Knowledge", source="chunk-1", content={"concept_name": "机制", "source_chunk_ids": ["chunk-1"], "applicable_flows": ["prose"]}, metadata={"project_id": "lineage-diff-p"}, references=["chunk-1"])
    pack = BaseAsset(id="pack-1", type="knowledge_pack", title="Pack", source="mkaos", content={"pack_items": [{"knowledge_id": "knowledge-1"}]}, metadata={"project_id": "lineage-diff-p"}, references=["knowledge-1"])
    context = BaseAsset(id="context-1", type="context_bundle", title="Context", source="pack-1", content={"context_bundle_id": "context-1", "knowledge_pack_id": "pack-1", "selected_knowledge_ids": ["knowledge-1"]}, metadata={"project_id": "lineage-diff-p"}, references=["pack-1", "knowledge-1"])
    draft = BaseAsset(id="draft-1", type="draft_chapter", title="Draft", source="context-1", content={"context_bundle_id": "context-1", "text": "safe generated text"}, metadata={"project_id": "lineage-diff-p"}, references=["context-1"])
    for category, asset in [("raw", source), ("raw", chunk), ("knowledge", knowledge), ("contexts", pack), ("contexts", context), ("drafts", draft)]:
        storage.write_asset(category, asset)
    return {"source": source.id, "knowledge": knowledge.id, "draft": draft.id}


if __name__ == "__main__":
    unittest.main()
