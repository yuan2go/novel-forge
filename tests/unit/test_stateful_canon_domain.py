from __future__ import annotations

import unittest

from novel_forge.modules.canon_graph.domain import (
    SNAPSHOT_ASSET_TYPES,
    STATE_ASSET_TYPES,
    build_canon_update,
    extract_canon_candidates,
)


class StatefulCanonDomainTests(unittest.TestCase):
    def extraction(self):
        return extract_canon_candidates(
            project_id="project-a",
            revision={
                "chapter": 2,
                "text": "The alliance breaks after the costly choice.",
                "canon_assertions": [
                    {"subject": "alliance", "predicate": "status", "object": "broken"}
                ],
                "timeline_events": [{"chapter": 1, "event": "late insertion"}],
                "character_state_changes": [
                    {"character_id": "hero", "canonical_name": "Different Hero"}
                ],
                "world_rule_usages": [{"exception": True, "cost": ""}],
                "power_state_changes": [{"tier_increase": True, "change_reasons": []}],
                "foreshadow_changes": [{"status": "PAID", "payoff_evidence": ""}],
                "promise_changes": [{"status": "PAID", "payoff_evidence": ""}],
            },
            revision_asset_version_id="revision-v2",
            context_bundle_version_id="context-v2",
        )

    def test_real_path_always_has_independent_digest_assertion(self) -> None:
        extraction = extract_canon_candidates(
            project_id="project-a",
            revision={"chapter": 1, "text": "A choice changes the public record."},
            revision_asset_version_id="revision-v1",
            context_bundle_version_id="context-v1",
        )
        self.assertEqual(extraction["extraction_source"], "deterministic_extractor")
        self.assertEqual(
            extraction["canon_assertion_candidates"][-1]["predicate"],
            "accepted_revision_digest",
        )

    def test_historical_state_detects_typed_cross_chapter_conflicts(self) -> None:
        state = {
            "canon_snapshot": [{"asset_version_id": "canon-v1", "subject": "alliance", "predicate": "status", "object": "active"}],
            "timeline_snapshot": [{"asset_version_id": "timeline-v1", "chapter": 2}],
            "character_state": [{"asset_version_id": "character-v1", "character_id": "hero", "canonical_name": "Hero"}],
            "world_rule": [{"asset_version_id": "world-v1"}],
            "power_state": [{"asset_version_id": "power-v1"}],
            "foreshadow_state": [{"asset_version_id": "foreshadow-v1"}],
            "reader_promise": [{"asset_version_id": "promise-v1"}],
        }
        update = build_canon_update(
            project_id="project-a",
            revision_asset_version_id="revision-v2",
            context_bundle_version_id="context-v2",
            extraction=self.extraction(),
            historical_state=state,
        )
        codes = {item["conflict_code"] for item in update["conflicts"]}
        self.assertTrue({
            "FACT_CONTRADICTION", "TEMPORAL_CONTRADICTION",
            "CHARACTER_IDENTITY_CONTRADICTION", "WORLD_RULE_CONTRADICTION",
            "POWER_PROGRESSION_CONTRADICTION", "FORESHADOW_LIFECYCLE_CONTRADICTION",
            "PROMISE_LIFECYCLE_CONTRADICTION",
        }.issubset(codes))
        self.assertEqual(update["gate"], "BLOCKED")
        self.assertEqual(
            {item["asset_type"] for item in update["snapshot_candidates"]},
            set(SNAPSHOT_ASSET_TYPES.values()),
        )
        self.assertEqual(
            {item["state_kind"] for item in update["snapshot_candidates"]},
            set(STATE_ASSET_TYPES),
        )
        self.assertTrue(all(item["append_only"] for item in update["snapshot_candidates"]))
        self.assertTrue(all(item["rollback_aware"] for item in update["snapshot_candidates"]))
        self.assertIn("canon-v1", update["historical_input_version_ids"])


if __name__ == "__main__":
    unittest.main()
