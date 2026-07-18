from __future__ import annotations

import unittest

from novel_forge.modules.chapter_quality_authority.context_views import (
    STATE_ASSET_TYPES,
    build_quality_context_view,
)
from novel_forge.modules.command_kernel.errors import KernelError


def _bundle() -> dict:
    quality_id = "quality-profile-v1"
    platform_id = "platform-profile-v1"
    segments = [
        {
            "asset_version_id": quality_id,
            "asset_type": "quality_rubric",
            "content_digest": "sha256:quality",
            "structured_facts": [{"key": "thresholds", "value": {"readability": 78}}],
            "source_expression_included": False,
        },
        {
            "asset_version_id": platform_id,
            "asset_type": "platform_profile",
            "content_digest": "sha256:platform",
            "structured_facts": [{"key": "platform_rules", "value": {
                "chapter_length": {"minimum": 1500, "maximum": 3000},
                "format": {"paragraph_max": 260},
                "sensitive_content": ["blocked-category"],
                "ai_content": {"disclosure": "internal-only"},
                "opening": ["conflict in first scene"],
                "rhythm": ["one payoff per chapter"],
                "publish_metadata": {"title_required": True},
            }}],
            "source_expression_included": False,
        },
        {
            "asset_version_id": "promise-v1",
            "asset_type": "reader_promise",
            "content_digest": "sha256:promise",
            "structured_facts": [{"promise": "the cost becomes visible"}],
            "source_expression_included": False,
        },
    ]
    segments.extend(
        {
            "asset_version_id": f"{kind}-v1",
            "asset_type": kind,
            "content_digest": f"sha256:{kind}",
            "structured_facts": [{"state_kind": kind, "value": "stable"}],
            "source_expression_included": False,
        }
        for kind in STATE_ASSET_TYPES
    )
    return {
        "project_id": "project-1",
        "context_segments": segments,
        "context_manifest": {"selected_asset_version_ids": [item["asset_version_id"] for item in segments]},
        "source_isolation_result": {"passed": True, "raw_source_ratio": 0},
        "copyright_boundary": "abstract_or_project_owned_only",
        "production_input_manifest": {
            "quality_profile_version_id": quality_id,
            "platform_profile_version_id": platform_id,
            "source_governance": {"status": "CLEAR"},
        },
    }


def _view(group: str, bundle: dict | None = None, *, token_budget: int = 6000) -> dict:
    return build_quality_context_view(
        group=group,
        revision={"chapter": 2, "text": "A governed revision with an explicit cost."},
        revision_asset_version_id="revision-v2",
        chapter_plan={
            "chapter": 2,
            "chapter_function": "promise payoff",
            "chapter_objective": "make the cost visible",
            "reader_promise_actions": [{"promise_id": "p1", "action": "pay"}],
            "reward_setup": [{"reward_id": "r1"}],
            "reward_payoff": [{"reward_id": "r1", "status": "PAID"}],
            "antagonist_pressure": {"target": "safe route"},
            "chapter_hook": "a new obligation",
            "next_chapter_bridge": "debt collection",
        },
        chapter_plan_asset_version_id="plan-v2",
        context_bundle=bundle or _bundle(),
        context_bundle_asset_version_id="context-v2",
        canon={"conflicts": [], "snapshot_candidates": []},
        canon_asset_version_id="canon-v2",
        token_budget=token_budget,
    )


class QualityContextAuthorityTests(unittest.TestCase):
    def test_group_views_are_minimal_and_distinct(self) -> None:
        views = {group: _view(group) for group in (
            "structural", "commercial", "source_originality", "longform", "platform"
        )}
        self.assertEqual(views["structural"]["type"], "StructuralQualityContextView")
        self.assertIn("reader_promise_actions", views["commercial"])
        self.assertIn("reward_payoff", views["commercial"])
        self.assertNotIn("source_governance", views["commercial"])
        self.assertIn("source_governance", views["source_originality"])
        self.assertNotIn("previous_state_snapshots", views["source_originality"])
        self.assertEqual(
            set(views["longform"]["previous_state_snapshots"]), set(STATE_ASSET_TYPES)
        )
        self.assertEqual(
            views["platform"]["compiled_platform_policy"]["chapter_length_rules"]["minimum"],
            1500,
        )

    def test_source_view_contains_identity_not_source_expression(self) -> None:
        view = _view("source_originality")
        self.assertTrue(view["source_expression_excluded"])
        self.assertNotIn("safe_summary", view["governed_segment_identities"][0])
        self.assertTrue(all(not item["source_expression_included"] for item in view["governed_segment_identities"]))

    def test_stale_or_missing_profile_version_fails_closed(self) -> None:
        bundle = _bundle()
        bundle["production_input_manifest"]["platform_profile_version_id"] = "stale-v0"
        with self.assertRaisesRegex(KernelError, "frozen platform profile"):
            _view("platform", bundle)

    def test_longform_compression_preserves_snapshot_identity(self) -> None:
        bundle = _bundle()
        state = next(item for item in bundle["context_segments"] if item["asset_type"] == "canon_snapshot")
        state["structured_facts"] = [{"index": item} for item in range(1000)]
        view = _view("longform", bundle, token_budget=6000)
        row = view["previous_state_snapshots"]["canon_snapshot"]["canon_snapshot:project"][0]
        self.assertEqual(row["asset_version_id"], "canon_snapshot-v1")
        self.assertTrue(row["compressed"])
        self.assertGreater(row["omitted_fact_count"], 0)

    def test_longform_preserves_multiple_entities_and_emits_coverage(self) -> None:
        bundle = _bundle()
        bundle["context_segments"].extend(
            [
                {
                    "asset_version_id": "character-alice-v1",
                    "asset_type": "character_state_snapshot",
                    "entity_id": "alice",
                    "chapter": 1,
                    "content_digest": "sha256:alice",
                    "qualification": "ELIGIBLE",
                    "structured_facts": [{"entity_id": "alice", "goal": "protect"}],
                },
                {
                    "asset_version_id": "character-bob-v1",
                    "asset_type": "character_state_snapshot",
                    "entity_id": "bob",
                    "chapter": 1,
                    "content_digest": "sha256:bob",
                    "qualification": "ELIGIBLE",
                    "structured_facts": [{"entity_id": "bob", "goal": "escape"}],
                },
            ]
        )
        view = _view("longform", bundle)
        identities = view["previous_state_snapshots"]["character_state_snapshot"]
        self.assertIn("entity_id:alice", identities)
        self.assertIn("entity_id:bob", identities)
        self.assertLessEqual(
            view["coverage_report"]["token_estimate"],
            view["coverage_report"]["token_budget"],
        )

    def test_critical_identity_overflow_fails_closed(self) -> None:
        with self.assertRaisesRegex(KernelError, "CRITICAL_OVERFLOW"):
            _view("longform", token_budget=50)


if __name__ == "__main__":
    unittest.main()
