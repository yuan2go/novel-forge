from __future__ import annotations

import unittest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.plan_change_authority.domain import (
    PlanChangeRisk,
    classify_plan_change_risk,
    require_approvable_scope,
    semantic_plan_diff,
)
from novel_forge.modules.plan_change_authority.semantic_impact import (
    DISCOVERY_POLICY,
    discover_semantic_impacts,
    resolve_semantic_dispositions,
)


class PlanChangeAuthorityDomainTests(unittest.TestCase):
    def _discovery(self, *, execution_scope="PLANNED", count=1):
        return discover_semantic_impacts(
            target_asset_version_id="arc:river:v1",
            proposed_asset_version_id="arc:river:v2",
            changes=[
                {
                    "field": "required_events",
                    "before": ["promise:river-rescue"],
                    "after": ["promise:river-crossing"],
                }
            ],
            plans=[
                {
                    "asset_version_id": f"plan:volume-2:{index}",
                    "content_hash": f"hash:{index}",
                    "execution_scope": execution_scope,
                    "binding_version": 2,
                    "freshness": "CURRENT",
                    "contract_type": "CHAPTER",
                    "logical_key": f"chapter:{index}",
                    "content": {
                        "required_payoffs": ["promise:river-rescue"],
                        "volume": 2,
                    },
                }
                for index in range(count)
            ],
            accepted_prose=[
                {
                    "acceptance_id": "accept:1",
                    "asset_version_id": "draft:1:v2",
                    "chapter_number": 1,
                    "content_hash": "draft-hash",
                    "text": "江边刻着promise:river-rescue。",
                }
            ],
            coverage={"plan_scan_truncated": False},
        )

    def test_implicit_retrieval_is_versioned_and_not_causal_proof(self):
        discovery = self._discovery()
        hypothesis = discovery["hypotheses"][0]
        self.assertEqual(hypothesis["relation_status"], "UNVERIFIED")
        self.assertFalse(discovery["hard_dependency_created"])
        self.assertEqual(
            hypothesis["plan_evidence"][0]["json_pointer"], "/required_payoffs/0"
        )
        prose = hypothesis["accepted_prose_evidence"][0]
        self.assertEqual(prose["asset_version_id"], "draft:1:v2")
        self.assertEqual(
            "江边刻着promise:river-rescue。"[prose["start"] : prose["end"]],
            prose["quote"],
        )
        self.assertEqual(
            resolve_semantic_dispositions(discovery, [])[0]["disposition"], "DEFER"
        )

    def test_reviewed_false_positive_and_confirmed_relation_bind_frozen_evidence(self):
        discovery = self._discovery()
        hypothesis = discovery["hypotheses"][0]
        for outcome in ("CONFIRMED", "FALSE_POSITIVE"):
            result = resolve_semantic_dispositions(
                discovery,
                [
                    {
                        "hypothesis_id": hypothesis["hypothesis_id"],
                        "disposition": outcome,
                        "rationale": "same term checked against the exact future commitment",
                        "evidence": hypothesis["plan_evidence"],
                    }
                ],
            )
            self.assertEqual(result[0]["disposition"], outcome)
        with self.assertRaisesRegex(KernelError, "PLAN_IMPACT_EVIDENCE_INVALID"):
            resolve_semantic_dispositions(
                discovery,
                [
                    {
                        "hypothesis_id": hypothesis["hypothesis_id"],
                        "disposition": "CONFIRMED",
                        "rationale": "unbound assertion",
                        "evidence": [{"quote": "invented"}],
                    }
                ],
            )

    def test_history_breadth_and_unknown_hypotheses_cannot_be_invalidated(self):
        discovery = self._discovery(execution_scope="EXECUTED")
        hypothesis = discovery["hypotheses"][0]
        self.assertEqual(
            resolve_semantic_dispositions(discovery, [])[0]["disposition"],
            "PRESERVE_HISTORY",
        )
        with self.assertRaisesRegex(KernelError, "PLAN_IMPACT_FUTURE_ONLY"):
            resolve_semantic_dispositions(
                discovery,
                [
                    {
                        "hypothesis_id": hypothesis["hypothesis_id"],
                        "disposition": "CONFIRMED",
                        "rationale": "retcon request",
                        "evidence": hypothesis["plan_evidence"],
                    }
                ],
            )
        wide = self._discovery(count=DISCOVERY_POLICY["hypothesis_limit"] + 1)
        self.assertEqual(wide["coverage"]["hypotheses_omitted"], 1)
        self.assertEqual(len(wide["hypotheses"]), DISCOVERY_POLICY["hypothesis_limit"])
        hypothesis = wide["hypotheses"][0]
        hypothesis["dependency_scope_truncated"] = True
        with self.assertRaisesRegex(KernelError, "PLAN_IMPACT_SCOPE_TOO_BROAD"):
            resolve_semantic_dispositions(
                wide,
                [
                    {
                        "hypothesis_id": hypothesis["hypothesis_id"],
                        "disposition": "CONFIRMED",
                        "rationale": "too many dependents",
                        "evidence": hypothesis["plan_evidence"],
                    }
                ],
            )

    def test_semantic_diff_detects_field_changes(self) -> None:
        changes = semantic_plan_diff(
            {
                "objective": "reach the city",
                "ending_contract": "choose duty",
                "required_events": ["cross the gate"],
            },
            {
                "objective": "save the city",
                "ending_contract": "choose agency",
                "required_events": ["open the gate"],
            },
        )
        self.assertEqual(
            {change.change_type for change in changes},
            {
                "OBJECTIVE_CHANGED",
                "ENDING_CONTRACT_CHANGED",
                "REQUIRED_EVENT_CHANGED",
            },
        )
        self.assertEqual(
            classify_plan_change_risk(changes, target_execution_scope="PLANNED"),
            PlanChangeRisk.HIGH,
        )

    def test_executed_plan_is_retcon_only(self) -> None:
        with self.assertRaisesRegex(KernelError, "EXECUTED_PLAN_RETCON_ONLY"):
            require_approvable_scope("EXECUTED")

    def test_new_high_risk_commitment_cannot_hide_as_an_unchanged_plan(self) -> None:
        changes = semantic_plan_diff(
            {"objective": "cross the river"},
            {"objective": "cross the river", "reader_promise": "justice has a cost"},
        )
        self.assertEqual([item.field for item in changes], ["reader_promise"])
        self.assertIsNone(changes[0].before)
        self.assertEqual(
            classify_plan_change_risk(changes, target_execution_scope="PLANNED"),
            PlanChangeRisk.HIGH,
        )

    def test_semantic_diff_covers_progressive_design_scopes(self) -> None:
        changes = semantic_plan_diff(
            {
                "narrative_segments": [{"segment_id": "segment:1"}],
                "arc_segments": [{"segment_id": "arc-segment:1"}],
                "scene_plan": [{"scene_id": "scene:1"}],
                "realization_level": "DEFINED",
            },
            {
                "narrative_segments": [{"segment_id": "segment:2"}],
                "arc_segments": [{"segment_id": "arc-segment:2"}],
                "scene_plan": [{"scene_id": "scene:2"}],
                "realization_level": "DETAILED",
            },
        )

        self.assertEqual(
            {change.change_type for change in changes},
            {
                "NARRATIVE_SEGMENT_CHANGED",
                "ARC_SEGMENT_CHANGED",
                "SCENE_ARCHITECTURE_CHANGED",
                "REALIZATION_LEVEL_CHANGED",
            },
        )


if __name__ == "__main__":
    unittest.main()
