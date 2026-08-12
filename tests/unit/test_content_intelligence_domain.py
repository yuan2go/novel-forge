from __future__ import annotations

from datetime import datetime, timezone
import unittest

from novel_forge.modules.content_intelligence import (
    aggregate_pacing_windows,
    build_hook_analysis,
    build_pacing_observation,
    build_world_consequence_candidate,
    verify_claim,
)
from novel_forge.modules.command_kernel.errors import KernelError


class ContentIntelligenceDomainTests(unittest.TestCase):
    def test_hook_analysis_preserves_horizon_promise_and_provider_evidence(
        self,
    ) -> None:
        result = build_hook_analysis(
            project_id="project-a",
            chapter=12,
            chapter_plan={
                "opening_hook": "The sealed verdict is already open.",
                "chapter_hook": "The witness names the absent heir.",
                "hook_horizon": "VOLUME",
                "reader_promise_actions": [{"promise_id": "promise-heir"}],
            },
            provider_dimensions=[
                {
                    "dimension": "chapter_hook",
                    "gate_status": "PASSED",
                    "confidence": 0.82,
                    "evidence_locations": [
                        {"start": 140, "end": 176, "claim": "ending reveal"}
                    ],
                    "issue_codes": [],
                    "revision_strategies": [],
                }
            ],
            target_asset_version_id="revision-v12",
            chapter_plan_asset_version_id="plan-v12",
            provider_evidence={
                "provider_id": "provider-a",
                "model_id": "model-a",
                "real_model_call": True,
                "trace_id": "trace-a",
            },
        )

        self.assertEqual(result["hook_horizon"], "VOLUME")
        self.assertEqual(result["promise_id"], "promise-heir")
        self.assertEqual(result["ending_hook_type"], "SEMANTIC_PROVIDER_OBSERVATION")
        self.assertEqual(result["evidence_spans"][0]["start"], 140)
        self.assertTrue(result["real_provider_observed"])
        self.assertEqual(result["qualification"], "PROVIDER_UNCALIBRATED")

    def test_pacing_observation_does_not_infer_quality_from_text(self) -> None:
        observation = build_pacing_observation(
            project_id="project-a",
            chapter=20,
            revision={"text": "fight fight fast slow dialogue!!!"},
            chapter_plan={"scene_sequence": [{"scene_id": "s1"}]},
            canon={
                "snapshot_candidates": [
                    {"state_kind": "reader_promise", "changes": [{"status": "OPEN"}]},
                    {"state_kind": "foreshadow_state", "changes": [{"status": "OPEN"}]},
                    {
                        "state_kind": "character_state",
                        "changes": [{"character_id": "c"}],
                    },
                ]
            },
            provider_dimensions=[],
            target_asset_version_id="revision-v20",
            provider_evidence={"real_model_call": False},
        )
        self.assertEqual(observation["metrics"]["open_promises"]["value"], 1)
        self.assertEqual(
            observation["metrics"]["event_density"]["status"],
            "REQUIRES_PROVIDER_JUDGE",
        )
        self.assertEqual(observation["metrics"]["dialogue_ratio"]["value"], None)
        self.assertFalse(observation["used_keyword_or_regex_heuristics"])
        self.assertEqual(observation["qualification"], "INSUFFICIENT_EVIDENCE")

    def test_multi_window_aggregation_excludes_future_observations(self) -> None:
        observations = [
            {
                "project_id": "project-a",
                "chapter": chapter,
                "metrics": {
                    "state_change_magnitude": {
                        "value": float(chapter),
                        "status": "MEASURED",
                        "measurement_type": "DETERMINISTIC",
                    }
                },
                "source_asset_version_id": f"pacing-v{chapter}",
            }
            for chapter in (10, 11, 12, 13)
        ]
        result = aggregate_pacing_windows(
            project_id="project-a",
            as_of_chapter=12,
            observations=observations,
            scopes={"ARC": (10, 15), "VOLUME": (1, 30), "BOOK": (1, 100)},
        )
        three = next(
            item for item in result["aggregates"] if item["scale"] == "3_CHAPTER_WINDOW"
        )
        self.assertEqual(three["chapters"], [10, 11, 12])
        self.assertNotIn(
            13,
            {chapter for item in result["aggregates"] for chapter in item["chapters"]},
        )
        self.assertTrue(result["future_observations_excluded"])

    def test_world_consequences_remain_candidates_and_validate_graph_scope(
        self,
    ) -> None:
        candidate = build_world_consequence_candidate(
            project_id="project-a",
            world_bible_asset_version_id="world-v1",
            world_rules=[{"rule_id": "rule-magic-tax"}],
            provider_consequences=[
                {
                    "consequence_id": "consequence-1",
                    "rule_id": "rule-magic-tax",
                    "direct_consequence": "Licensed use concentrates in cities.",
                    "systemic_consequence": "Guilds become fiscal intermediaries.",
                    "cultural_consequence": "Unlicensed magic becomes a class marker.",
                    "affected_groups": ["rural-mages", "guilds"],
                    "institutional_adaptations": ["license-courts"],
                    "contradictions": [],
                    "story_opportunities": ["smuggling dispute"],
                    "evidence": [{"rule_id": "rule-magic-tax"}],
                }
            ],
            provider_evidence={"trace_id": "trace-world", "real_model_call": True},
        )
        self.assertEqual(candidate["status"], "CANDIDATE")
        self.assertFalse(candidate["accepted_canon"])
        self.assertEqual(candidate["canon_mutation"], "FORBIDDEN")
        self.assertEqual(candidate["graph_integrity"], "PASSED")
        node_ids = {item["node_id"] for item in candidate["nodes"]}
        self.assertIn("affected_group:rural-mages", node_ids)
        self.assertIn("affected_group:guilds", node_ids)
        self.assertIn("institutional_adaptation:license-courts", node_ids)
        self.assertTrue(
            all(
                edge["source_id"] in node_ids and edge["target_id"] in node_ids
                for edge in candidate["edges"]
            )
        )
        self.assertEqual(
            candidate["affected_group_node_ids"],
            ["affected_group:guilds", "affected_group:rural-mages"],
        )

        with self.assertRaisesRegex(KernelError, "WORLD_CONSEQUENCE_RULE_UNKNOWN"):
            build_world_consequence_candidate(
                project_id="project-a",
                world_bible_asset_version_id="world-v1",
                world_rules=[{"rule_id": "rule-known"}],
                provider_consequences=[
                    {"consequence_id": "c", "rule_id": "rule-other"}
                ],
                provider_evidence={"trace_id": "trace-world"},
            )

    def test_fact_verification_is_evidence_bound_fail_closed_and_temporal(self) -> None:
        claim = {
            "claim_id": "claim-1",
            "project_id": "project-a",
            "statement": "The policy is in force.",
            "temporal_valid_to": "2026-12-31T00:00:00+00:00",
        }
        self.assertEqual(
            verify_claim(
                claim=claim,
                evidence=[],
                as_of=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )["status"],
            "INSUFFICIENT_EVIDENCE",
        )
        supporting = [
            {
                "project_id": "project-a",
                "evidence_span_id": "span-1",
                "source_document_id": "source-1",
                "stance": "SUPPORTS",
                "qualified": True,
                "source_quality": 0.9,
                "confidence": 0.8,
            }
        ]
        self.assertEqual(
            verify_claim(
                claim=claim,
                evidence=supporting,
                as_of=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )["status"],
            "VERIFIED",
        )
        disputed = [
            *supporting,
            {**supporting[0], "evidence_span_id": "span-2", "stance": "CONTRADICTS"},
        ]
        self.assertEqual(
            verify_claim(
                claim=claim,
                evidence=disputed,
                as_of=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )["status"],
            "DISPUTED",
        )
        unsupported = [
            {**supporting[0], "evidence_span_id": "span-neutral", "stance": "NEUTRAL"}
        ]
        self.assertEqual(
            verify_claim(
                claim=claim,
                evidence=unsupported,
                as_of=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )["status"],
            "UNSUPPORTED",
        )
        self.assertEqual(
            verify_claim(
                claim=claim,
                evidence=supporting,
                as_of=datetime(2027, 1, 1, tzinfo=timezone.utc),
            )["status"],
            "OUTDATED",
        )
        evidence_expired = [
            {
                **supporting[0],
                "temporal_valid_to": "2026-07-31T23:59:59+00:00",
            }
        ]
        fresh_claim = {**claim, "temporal_valid_to": "2027-12-31T00:00:00+00:00"}
        self.assertEqual(
            verify_claim(
                claim=fresh_claim,
                evidence=evidence_expired,
                as_of=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )["status"],
            "OUTDATED",
        )
        with self.assertRaisesRegex(KernelError, "CROSS_PROJECT_REFERENCE"):
            verify_claim(
                claim=claim,
                evidence=[{**supporting[0], "project_id": "project-b"}],
                as_of=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )
        with self.assertRaisesRegex(KernelError, "TIMEZONE_REQUIRED"):
            verify_claim(
                claim=claim,
                evidence=supporting,
                as_of=datetime(2026, 8, 1),
            )


if __name__ == "__main__":
    unittest.main()
