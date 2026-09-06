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
            "structured_facts": [
                {
                    "key": "platform_rules",
                    "value": {
                        "chapter_length": {"minimum": 1500, "maximum": 3000},
                        "format": {"paragraph_max": 260},
                        "sensitive_content": ["blocked-category"],
                        "ai_content": {"disclosure": "internal-only"},
                        "opening": ["conflict in first scene"],
                        "rhythm": ["one payoff per chapter"],
                        "publish_metadata": {"title_required": True},
                    },
                }
            ],
            "source_expression_included": False,
        },
        {
            "asset_version_id": "promise-v1",
            "asset_type": "reader_promise",
            "content_digest": "sha256:promise",
            "structured_facts": [{"promise": "the cost becomes visible"}],
            "source_expression_included": False,
        },
        {
            "asset_version_id": "world-bible-v1",
            "asset_type": "world_bible",
            "content_digest": "sha256:world-bible",
            "structured_facts": [
                {
                    "rule_id": "rule:public-record",
                    "rule": "Public records require a witnessed filing.",
                }
            ],
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
        "context_manifest": {
            "selected_asset_version_ids": [
                item["asset_version_id"] for item in segments
            ]
        },
        "source_isolation_result": {"passed": True, "raw_source_ratio": 0},
        "copyright_boundary": "abstract_or_project_owned_only",
        "production_input_manifest": {
            "quality_profile_version_id": quality_id,
            "platform_profile_version_id": platform_id,
            "source_governance": {"status": "CLEAR"},
        },
    }


def _view(
    group: str,
    bundle: dict | None = None,
    *,
    token_budget: int = 6000,
    canon: dict | None = None,
    revision_text: str = "A governed revision with an explicit cost.",
) -> dict:
    return build_quality_context_view(
        group=group,
        revision={
            "chapter": 2,
            "title": "The Cost of Memory",
            "text": revision_text,
        },
        revision_asset_version_id="revision-v2",
        chapter_plan={
            "chapter": 2,
            "title": "The Cost of Memory",
            "narrative_architecture_version": "canonical-narrative-architecture-v1",
            "safe_summary": "A clerk preserves evidence at a personal cost.",
            "chapter_function": "promise payoff",
            "chapter_objective": "make the cost visible",
            "reader_promise_actions": [{"promise_id": "p1", "action": "pay"}],
            "reward_setup": [{"reward_id": "r1"}],
            "reward_payoff": [{"reward_id": "r1", "status": "PAID"}],
            "antagonist_pressure": {"target": "safe route"},
            "chapter_hook": "a new obligation",
            "next_chapter_bridge": "debt collection",
            "chapter_intent": "make the choice and its cost executable",
            "arc_schedule": [
                {
                    "arc_plan_version_id": "arc-v1",
                    "role": "PRIMARY",
                    "segment_id": "arc-segment:1",
                }
            ],
            "scene_plan": [{"scene_id": "scene:2:1", "goal": "force the choice"}],
            "reader_experience": {"target_emotion": "costly relief"},
            "required_state_transitions": [
                {"state_kind": "character_arc", "entity_key": "lin:accountability"}
            ],
        },
        chapter_plan_asset_version_id="plan-v2",
        context_bundle=bundle or _bundle(),
        context_bundle_asset_version_id="context-v2",
        canon=canon or {"conflicts": [], "snapshot_candidates": []},
        canon_asset_version_id="canon-v2",
        token_budget=token_budget,
    )


class QualityContextAuthorityTests(unittest.TestCase):
    def test_group_views_are_minimal_and_distinct(self) -> None:
        views = {
            group: _view(group)
            for group in (
                "structural",
                "commercial",
                "source_originality",
                "longform",
                "platform",
            )
        }
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
            views["longform"]["chapter_plan"]["required_state_transitions"][0][
                "state_kind"
            ],
            "character_arc",
        )
        self.assertEqual(
            views["longform"]["governed_world_rules"][0]["asset_version_id"],
            "world-bible-v1",
        )
        self.assertEqual(views["structural"]["scene_plan"][0]["scene_id"], "scene:2:1")
        self.assertEqual(views["commercial"]["arc_schedule"][0]["role"], "PRIMARY")
        self.assertEqual(
            views["platform"]["compiled_platform_policy"]["chapter_length_rules"][
                "minimum"
            ],
            1500,
        )
        self.assertEqual(
            views["platform"]["publish_metadata_candidate"],
            {
                "chapter": 2,
                "title": "The Cost of Memory",
                "summary": "A clerk preserves evidence at a personal cost.",
            },
        )

    def test_source_view_contains_identity_not_source_expression(self) -> None:
        view = _view("source_originality")
        self.assertTrue(view["source_expression_excluded"])
        self.assertNotIn("safe_summary", view["governed_segment_identities"][0])
        self.assertTrue(
            all(
                not item["source_expression_included"]
                for item in view["governed_segment_identities"]
            )
        )

    def test_stale_or_missing_profile_version_fails_closed(self) -> None:
        bundle = _bundle()
        bundle["production_input_manifest"]["platform_profile_version_id"] = "stale-v0"
        with self.assertRaisesRegex(KernelError, "frozen platform profile"):
            _view("platform", bundle)

    def test_longform_compression_preserves_snapshot_identity(self) -> None:
        bundle = _bundle()
        state = next(
            item
            for item in bundle["context_segments"]
            if item["asset_type"] == "canon_snapshot"
        )
        state["structured_facts"] = [{"index": item} for item in range(3000)]
        view = _view("longform", bundle, token_budget=6000)
        row = view["previous_state_snapshots"]["canon_snapshot"][
            "canon_snapshot:project"
        ][0]
        self.assertEqual(row["asset_version_id"], "canon_snapshot-v1")
        self.assertTrue(row["compressed"])
        self.assertGreater(row["omitted_fact_count"], 0)

    def test_longform_view_excludes_full_planning_provider_envelope(self) -> None:
        view = build_quality_context_view(
            group="longform",
            revision={"chapter": 2, "title": "Cost", "text": "A concise revision."},
            revision_asset_version_id="revision-v2",
            chapter_plan={
                "chapter": 2,
                "title": "Cost",
                "premise": "A choice becomes irreversible.",
                "chapter_objective": "make the cost visible",
                "required_arc_contributions": [{"arc": "accountability"}],
                "source_extensions": {"provider_envelope": "x" * 60_000},
            },
            chapter_plan_asset_version_id="plan-v2",
            context_bundle=_bundle(),
            context_bundle_asset_version_id="context-v2",
            canon={"conflicts": [], "snapshot_candidates": []},
            canon_asset_version_id="canon-v2",
            token_budget=6_000,
        )

        self.assertNotIn("source_extensions", view["chapter_plan"])
        self.assertEqual(view["chapter_plan"]["chapter"], 2)

    def test_longform_projects_authority_evidence_before_budgeting(self) -> None:
        extraction_candidate = {
            "disclosure_id": "disclosure:reader:fact-1",
            "fact_id": "fact-1",
            "audience": "READER",
            "disclosure_mode": "CONFIRM",
            "presentation_channel": "The contradiction is shown directly.",
            "model_id": "provider-model",
            "provider_id": "provider",
            "prompt_version": "prompt-v1",
            "source_revision_asset_version_id": "revision-v2",
            "approval_resolution": {"decision": "APPROVE"},
            "extraction_evidence": {"raw": "x" * 12_000},
        }
        conflict = {
            "severity": "blocking",
            "conflict_code": "PLANNED_DISCLOSURE_MISSING",
            "existing_version": {
                "disclosure_id": "disclosure:character:fact-1",
                "fact_id": "fact-1",
                "audience": "ALICE",
                "mode": "CONFIRM",
            },
            "candidate_version": [extraction_candidate] * 6,
            "evidence": {
                "existing": {"duplicated": "x" * 12_000},
                "candidate": [extraction_candidate] * 6,
            },
            "approval_requirement": "REQUIRED",
            "recommended_resolution": "extract the planned presentation event",
        }
        view = _view(
            "longform",
            token_budget=6_000,
            canon={
                "conflicts": [conflict] * 3,
                "state_changes": {"disclosure_event": [extraction_candidate]},
            },
        )

        serialized = str(view)
        self.assertNotIn("extraction_evidence", serialized)
        self.assertNotIn("provider-model", serialized)
        self.assertNotIn("evidence", view["canon_conflicts"][0])
        self.assertEqual(view["canon_conflicts"][0]["candidate_count"], 6)
        self.assertEqual(
            view["current_state_candidates"]["disclosure_event"]
            ["disclosure_event:project"][0]["structured_facts"][0]
            ["presentation_channel"],
            "The contradiction is shown directly.",
        )
        self.assertLessEqual(
            view["coverage_report"]["token_estimate"],
            view["coverage_report"]["token_budget"],
        )

    def test_canonical_longform_plan_does_not_repeat_legacy_aliases(self) -> None:
        view = _view("longform")

        self.assertIn("chapter_intent", view["chapter_plan"])
        self.assertIn("scene_plan", view["chapter_plan"])
        self.assertNotIn("chapter_objective", view["chapter_plan"])
        self.assertNotIn("reader_promise_actions", view["chapter_plan"])

    def test_longform_preserves_multiple_entities_and_emits_coverage(self) -> None:
        bundle = _bundle()
        story = next(
            item
            for item in bundle["context_segments"]
            if item["asset_type"] == "story_state_snapshot"
        )
        story["structured_facts"] = [
            {
                "state_kind": "character_state",
                "entity_key": "character_id=alice",
                "state": {"character_id": "alice", "goal": "protect"},
            },
            {
                "state_kind": "character_state",
                "entity_key": "character_id=bob",
                "state": {"character_id": "bob", "goal": "escape"},
            },
        ]
        view = _view("longform", bundle)
        identities = view["previous_state_snapshots"]["story_state_snapshot"]
        self.assertIn("character_id=alice", identities)
        self.assertIn("character_id=bob", identities)
        self.assertLessEqual(
            view["coverage_report"]["token_estimate"],
            view["coverage_report"]["token_budget"],
        )

    def test_longform_coverage_deduplicates_shared_snapshot_versions_within_budget(
        self,
    ) -> None:
        bundle = _bundle()
        story = next(
            item
            for item in bundle["context_segments"]
            if item["asset_type"] == "story_state_snapshot"
        )
        story["structured_facts"] = [
            {
                "state_kind": "character_state",
                "entity_key": f"character_id=character-{index:02d}",
                "state": {
                    "character_id": f"character-{index:02d}",
                    "detail": "x" * 600,
                },
            }
            for index in range(40)
        ]

        view = _view(
            "longform",
            bundle,
            token_budget=18_000,
            canon={"conflicts": [], "state_changes": {}},
            revision_text="r" * 10_000,
        )

        selected_versions = view["coverage_report"]["selected_asset_versions"]
        self.assertEqual(selected_versions, sorted(set(selected_versions)))
        self.assertEqual(
            len(view["previous_state_snapshots"]["story_state_snapshot"]),
            40,
        )
        self.assertLessEqual(
            view["coverage_report"]["token_estimate"],
            view["coverage_report"]["token_budget"],
        )

    def test_longform_reserves_the_actual_variable_coverage_report_size(self) -> None:
        bundle = _bundle()
        story = next(
            item
            for item in bundle["context_segments"]
            if item["asset_type"] == "story_state_snapshot"
        )
        story["structured_facts"] = [
            {
                "state_kind": "character_state",
                "entity_key": (
                    "character_id=character-with-a-deliberately-long-proof-identity-"
                    f"{index:03d}"
                ),
                "state": {
                    "character_id": f"character-{index:03d}",
                    "detail": "x" * 1_200,
                },
            }
            for index in range(40)
        ]

        view = _view(
            "longform",
            bundle,
            token_budget=28_000,
            canon={"conflicts": [], "state_changes": {}},
            revision_text="r" * 11_000,
        )

        self.assertEqual(
            len(view["coverage_report"]["included_entities"]),
            41,
        )
        self.assertEqual(
            view["coverage_report"]["selected_asset_versions"],
            sorted(set(view["coverage_report"]["selected_asset_versions"])),
        )
        self.assertLessEqual(
            view["coverage_report"]["token_estimate"],
            view["coverage_report"]["token_budget"],
        )

    def test_critical_identity_overflow_fails_closed(self) -> None:
        with self.assertRaisesRegex(KernelError, "CRITICAL_OVERFLOW"):
            _view("longform", token_budget=50)

    def test_longform_compacts_noncritical_candidate_rows_but_keeps_identities(
        self,
    ) -> None:
        identities = [f"character-{index}" for index in range(60)]
        canon = {
            "conflicts": [],
            "state_changes": {
                "character_state": [
                    {
                        "character_id": identity,
                        "description": "noncritical detail " * 20,
                    }
                    for identity in identities
                ]
            },
        }

        view = _view("longform", token_budget=2500, canon=canon)

        compacted = view["current_state_candidates"]["character_state"][
            "compressed:noncritical"
        ][0]
        self.assertEqual(
            compacted["included_identities"],
            [f"character_id:{identity}" for identity in identities],
        )
        self.assertEqual(compacted["identity_count"], len(identities))
        self.assertTrue(view["coverage_report"]["critical_facts_preserved"])
        self.assertLessEqual(
            view["coverage_report"]["token_estimate"],
            view["coverage_report"]["token_budget"],
        )


if __name__ == "__main__":
    unittest.main()


def test_quality_provider_view_excludes_unrevealed_background_candidates():
    import json
    plan = {'chapter': 1, 'constraint_envelope': {'world_preparation': {'action': {'contract_version': 'world-production-action.v2'}}}}
    hidden = {'world_state_id': 'council', 'private_marker': 'UNDISCLOSED_SUCCESSION_SECRET', 'fact_origin': {'kind': 'GOVERNED_BACKGROUND'}, 'world_transition': {'payload_json': 'UNDISCLOSED_SUCCESSION_SECRET'}}
    canon = {'state_changes': {'world_state': [hidden, {'world_state_id': 'market', 'status': 'OPEN'}]}}
    view = build_quality_context_view(group='longform', revision={'text': 'Only the market opens.'}, revision_asset_version_id='draft:1', chapter_plan=plan, chapter_plan_asset_version_id='plan:1', context_bundle=_bundle(), context_bundle_asset_version_id='context:1', canon=canon, canon_asset_version_id='canon:1')
    assert 'UNDISCLOSED_SUCCESSION_SECRET' not in json.dumps(view)
    assert 'market' in json.dumps(view['current_state_candidates'])
    assert canon['state_changes']['world_state'][0] == hidden


def test_quality_sees_observed_effect_without_private_validation_metadata():
    import json

    plan = {
        "chapter": 1,
        "constraint_envelope": {
            "world_preparation": {
                "action": {"contract_version": "world-production-action.v2"}
            }
        },
    }
    actual = {
        "world_state_id": "council",
        "status": "PUBLICLY_MOBILISED",
        "preparation_lineage": {"origin_action_version_id": "a"},
        "world_transition": {"payload_json": "PRIVATE_OBSERVER_RULE_ID"},
    }
    canon = {"state_changes": {"world_state": [actual]}}
    view = build_quality_context_view(
        group="longform",
        revision={"text": "The council musters in public."},
        revision_asset_version_id="draft:1",
        chapter_plan=plan,
        chapter_plan_asset_version_id="plan:1",
        context_bundle=_bundle(),
        context_bundle_asset_version_id="context:1",
        canon=canon,
        canon_asset_version_id="canon:1",
    )
    assert "PRIVATE_OBSERVER_RULE_ID" not in json.dumps(view)
    assert "PUBLICLY_MOBILISED" in json.dumps(view["current_state_candidates"])
    assert canon["state_changes"]["world_state"][0] == actual
