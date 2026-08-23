from __future__ import annotations

import unittest
from decimal import Decimal

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority.application import (
    _candidate_execution_binding,
    _hash,
)
from novel_forge.modules.mkaos_authority.domain import (
    KnowledgeEvidenceSpan,
    KnowledgePackSelection,
    NarrativeIntelligenceNeed,
    select_narrative_intelligence,
    validate_evidence_spans,
    validate_knowledge_candidate,
    validate_pack_selections,
)


class MkaosAuthorityDomainTests(unittest.TestCase):
    def test_non_fixture_candidate_execution_must_bind_output_and_inputs(self) -> None:
        span = KnowledgeEvidenceSpan("chunk:v1", 0, 20, "sha256:" + "a" * 64)
        arguments = {
            "fixture_protocol_only": False,
            "candidate_payload_hash": "sha256:" + "b" * 64,
            "abstraction_policy_version": "anti-copy:v1",
            "evidence_spans": (span,),
            "observation_asset_version_ids": ("observation:v1",),
        }
        with self.assertRaisesRegex(KernelError, "MKAOS_EXECUTION_OUTPUT_UNBOUND"):
            _candidate_execution_binding({}, **arguments)

        binding = {
            "schema_version": "mkaos-candidate-execution-binding.v1",
            "candidate_payload_hash": arguments["candidate_payload_hash"],
            "abstraction_policy_version": arguments["abstraction_policy_version"],
            "evidence_manifest_hash": _hash(
                {
                    "evidence_spans": [
                        {
                            "source_chunk_asset_version_id": "chunk:v1",
                            "chunk_byte_start": 0,
                            "chunk_byte_end": 20,
                            "evidence_hash": "sha256:" + "a" * 64,
                        }
                    ]
                }
            ),
            "observation_asset_version_ids": ["observation:v1"],
        }
        verified = _candidate_execution_binding(
            {"mkaos_candidate_binding": binding}, **arguments
        )
        self.assertEqual(verified["validation_status"], "VERIFIED")

    def test_candidate_requires_abstract_fields_and_blocks_source_expression(
        self,
    ) -> None:
        valid = {
            "concept_name": "Escalating obligation",
            "discipline": "organizational behavior",
            "abstract_principle": "A favor becomes costly when repayment criteria move.",
            "constraints": ["Every escalation must expose a changed obligation."],
            "conflict_generators": ["The beneficiary disputes what repayment means."],
            "review_checks": ["Check that no source-specific proper noun remains."],
            "copyright_boundaries": ["Mechanism only; no protected expression."],
        }
        self.assertEqual(validate_knowledge_candidate(valid), valid)

        with self.assertRaises(KernelError) as caught:
            validate_knowledge_candidate(
                {**valid, "raw_text": "forbidden source prose"}
            )
        self.assertEqual(caught.exception.code, "MKAOS_SOURCE_LEAKAGE_BLOCKED")

    def test_structured_narrative_intelligence_selects_possibilities_not_plots(
        self,
    ) -> None:
        abstract = {
            "concept_name": "Progress with incompatible benefits",
            "discipline": "narrative_design",
            "abstract_principle": "Progress exposes a choice and a visible cost.",
            "constraints": ["The cost must alter later choices."],
            "conflict_generators": ["Two benefits cannot both be retained."],
            "review_checks": ["Verify a causal state change."],
            "copyright_boundaries": ["Do not reuse source events or expression."],
            "knowledge_kind": "NARRATIVE_INTELLIGENCE",
            "semantic_family": "CONFLICT_ESCALATION_REVERSAL_PAYOFF",
            "mechanism": "Couple progress to an incompatible-benefit choice.",
            "applicability": ["A chapter needs progress and consequence."],
            "failure_conditions": ["The event does not alter future options."],
            "selection_tags": {
                "genre": [],
                "conflict": ["cost of progress"],
                "reader_effect": ["tension"],
                "theme": ["choice"],
            },
            "repetition_key": "progress-choice-cost",
            "originality_boundary": {
                "source_specific_sequence_reusable": False,
                "named_entity_substitution_allowed": False,
                "expression_reuse_allowed": False,
            },
        }
        self.assertEqual(validate_knowledge_candidate(abstract), abstract)
        need = NarrativeIntelligenceNeed(
            scope="chapter",
            target_stage="chapter_plan.generate",
            conflict_tags=("cost of progress",),
            reader_effect_tags=("tension",),
            semantic_families=("CONFLICT_ESCALATION_REVERSAL_PAYOFF",),
        )
        result = select_narrative_intelligence(
            need,
            (
                {
                    "knowledge_card_id": "card:1",
                    "asset_version_id": "card:1:v1",
                    "content_hash": "sha256:" + "a" * 64,
                    "candidate_asset_version_id": "candidate:1:v1",
                    "governance_decision_asset_version_id": "decision:1:v1",
                    "content": {"abstract_content": abstract, "lineage": {}},
                },
            ),
        )
        self.assertEqual(result["selection_status"], "SELECTED")
        self.assertEqual(
            result["selected"][0]["selected_content"]["mechanism"],
            abstract["mechanism"],
        )
        self.assertEqual(
            result["authority_boundary"]["semantic_role"], "POSSIBILITY_ONLY"
        )
        self.assertFalse(result["authority_boundary"]["may_mutate_story_authority"])

    def test_narrative_intelligence_blocks_ready_plot_and_recent_repetition(
        self,
    ) -> None:
        legacy = {
            "concept_name": "Cost before gain",
            "discipline": "narrative_design",
            "abstract_principle": "Visible cost makes later gain credible.",
            "constraints": ["Cost changes options."],
            "conflict_generators": ["Delay the gain."],
            "review_checks": ["Check consequence."],
            "copyright_boundaries": ["Mechanism only."],
        }
        with self.assertRaises(KernelError) as caught:
            validate_knowledge_candidate(
                {**legacy, "ready_made_plot": "Rename the source protagonist."}
            )
        self.assertEqual(caught.exception.code, "MKAOS_SOURCE_LEAKAGE_BLOCKED")

        result = select_narrative_intelligence(
            NarrativeIntelligenceNeed(
                scope="SCENE",
                target_stage="chapter_plan.generate",
                recently_used_repetition_keys=("cost-before-gain",),
            ),
            (
                {
                    "knowledge_card_id": "card:legacy",
                    "asset_version_id": "card:legacy:v1",
                    "content_hash": "sha256:" + "b" * 64,
                    "content": {"abstract_content": legacy, "lineage": {}},
                },
            ),
        )
        self.assertEqual(result["selection_status"], "NO_ELIGIBLE_MATCH")
        self.assertEqual(result["rejected"][0]["reason"], "RECENT_REPETITION_RISK")

    def test_evidence_is_deterministic_unique_and_in_bounds(self) -> None:
        first = KnowledgeEvidenceSpan("chunk:v1", 0, 20, "sha256:" + "a" * 64)
        second = KnowledgeEvidenceSpan("chunk:v1", 30, 50, "sha256:" + "b" * 64)
        self.assertEqual(
            validate_evidence_spans(
                (second, first), source_chunk_sizes={"chunk:v1": 50}
            ),
            (first, second),
        )
        with self.assertRaises(KernelError) as caught:
            validate_evidence_spans(
                (KnowledgeEvidenceSpan("chunk:v1", 0, 51, "sha256:" + "c" * 64),),
                source_chunk_sizes={"chunk:v1": 50},
            )
        self.assertEqual(caught.exception.code, "MKAOS_EVIDENCE_OUT_OF_BOUNDS")

    def test_pack_selection_freezes_roles_weights_and_rejects_duplicates(self) -> None:
        selection = KnowledgePackSelection("card:v1", "constraint", Decimal("1.5"))
        self.assertEqual(selection.usage_role, "CONSTRAINT")
        with self.assertRaises(KernelError) as caught:
            validate_pack_selections((selection, selection))
        self.assertEqual(caught.exception.code, "MKAOS_PACK_SELECTION_DUPLICATE")


if __name__ == "__main__":
    unittest.main()
