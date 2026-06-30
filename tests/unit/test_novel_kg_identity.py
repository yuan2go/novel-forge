from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.novel_kg import adjudicate_kg_identity_candidate, build_identity_merge_queue, create_kg_identity_resolution, normalize_identity_name
from novel_forge.schemas import NovelKGSnapshot, validate_common_fields
from novel_forge.storage.local import LocalStorage


class NovelKGIdentityTests(unittest.TestCase):
    def test_builds_identity_merge_queue_with_evidence_spans(self):
        graph = _identity_graph()

        queue = build_identity_merge_queue(graph)

        self.assertEqual(queue["summary"]["candidate_count"], 1)
        candidate = queue["candidates"][0]
        self.assertEqual(candidate["kind"], "entity")
        self.assertIn(candidate["normalized_alias"], {"钟城行者", "林乔"})
        self.assertIn("node-a", candidate["node_ids"])
        self.assertIn("node-b", candidate["node_ids"])
        self.assertTrue(candidate["evidence_spans"])
        self.assertTrue(candidate["requires_human_gate"])
        self.assertEqual(normalize_identity_name("《钟 城 行 者》"), "钟城行者")

    def test_persists_identity_resolution_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            snapshot = storage.write_asset_auto(
                NovelKGSnapshot(
                    title="KG snapshot",
                    content={**_identity_graph(), "kg_id": "kg-1", "ontology_version": "novel-kg-0.2.0", "summary": {}, "built_at": "2026-06-29T00:00:00Z"},
                    metadata={"project_id": "kg-project"},
                )
            )

            result = create_kg_identity_resolution(storage, snapshot_path=str(snapshot.relative_to(storage.root)))

            self.assertEqual(result["asset"]["type"], "kg_identity_resolution")
            self.assertEqual(validate_common_fields(result["asset"]), [])
            self.assertEqual(result["asset"]["content"]["summary"]["candidate_count"], 1)
            self.assertEqual(result["asset"]["content"]["status"], "needs_review")

    def test_adjudicates_and_applies_identity_merge_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            snapshot = storage.write_asset_auto(
                NovelKGSnapshot(
                    title="KG snapshot",
                    content={**_identity_graph(), "kg_id": "kg-1", "ontology_version": "novel-kg-0.2.0", "summary": {}, "built_at": "2026-06-29T00:00:00Z"},
                    metadata={"project_id": "kg-project"},
                )
            )
            resolution = create_kg_identity_resolution(storage, snapshot_path=str(snapshot.relative_to(storage.root)))
            candidate_id = resolution["asset"]["content"]["candidates"][0]["candidate_id"]

            result = adjudicate_kg_identity_candidate(
                storage,
                resolution_path_or_id=resolution["path"],
                candidate_id=candidate_id,
                decision="approve",
                actor="unit-test",
                note="same protagonist alias",
                apply_merge=True,
            )

            content = result["asset"]["content"]
            self.assertEqual(content["status"], "ready")
            self.assertEqual(content["summary"]["approved_count"], 1)
            self.assertEqual(content["summary"]["applied_merge_count"], 1)
            self.assertFalse(content["merge_queue"])
            overlay = content["identity_overlay"]
            self.assertEqual(overlay["node_to_canonical_identity"]["node-a"], content["candidates"][0]["canonical_identity_id"])
            self.assertEqual(content["adjudications"][0]["actor"], "unit-test")


def _identity_graph() -> dict:
    return {
        "project_id": "kg-project",
        "entities": [
            {
                "id": "node-a",
                "kind": "entity",
                "canonical_id": "canonical-a",
                "name": "林乔",
                "aliases": ["钟城行者"],
                "confidence": 0.91,
                "source_path": "data/characters/a.json",
                "evidence_spans": [
                    {
                        "source_path": "data/characters/a.json",
                        "field_path": "content.name",
                        "start": 0,
                        "end": 2,
                        "snippet": "林乔",
                        "extractor": "structured_asset",
                    }
                ],
            },
            {
                "id": "node-b",
                "kind": "entity",
                "canonical_id": "canonical-b",
                "name": "钟城行者",
                "aliases": ["林乔"],
                "confidence": 0.83,
                "source_path": "data/drafts/ch1.json",
                "evidence_spans": [
                    {
                        "source_path": "data/drafts/ch1.json",
                        "field_path": "content.text",
                        "start": 5,
                        "end": 9,
                        "snippet": "钟城行者",
                        "extractor": "known_alias_mention",
                    }
                ],
            },
        ],
        "factions": [],
        "locations": [],
        "props": [],
        "rules": [],
        "power_scales": [],
        "foreshadowing": [],
        "review_rules": [],
        "templates": [],
    }


if __name__ == "__main__":
    unittest.main()
