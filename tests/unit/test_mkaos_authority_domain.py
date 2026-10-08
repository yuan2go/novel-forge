from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import patch

from novel_forge.modules.command_kernel.errors import KernelError


from novel_forge.modules.mkaos_authority.application import (
    ExperimentalKnowledgeApprovalPolicy,
    MkaosAuthorityApplication,
    _candidate_execution_binding,
    _hash,
)
from novel_forge.modules.mkaos_authority.domain import (
    KnowledgeEvidenceSpan,
    KnowledgePackSelection,
    NarrativeIntelligenceNeed,
    resolve_book_knowledge_access_policy,
    select_narrative_intelligence,
    validate_book_knowledge_access_policy,
    validate_evidence_spans,
    validate_knowledge_candidate,
    validate_pack_selections,
)
from novel_forge.modules.mkaos_authority.query import MkaosAuthorityQuery


def _planning_card(index: int) -> dict[str, object]:
    return {
        "knowledge_card_id": f"card:{index}",
        "asset_version_id": f"card:{index}:v1",
        "content_hash": "sha256:" + f"{index + 1:064x}",
        "candidate_asset_version_id": f"candidate:{index}:v1",
        "governance_decision_asset_version_id": f"decision:{index}:v1",
        "card_status": "ACTIVE",
        "lifecycle": "ACTIVE",
        "eligibility": "PRODUCTION_ELIGIBLE",
        "governance": "CLEAR",
        "operation_status": "SUCCEEDED",
        "content": {
            "abstract_content": {
                "concept_name": f"Bounded mechanism {index}",
                "discipline": "narrative_design",
                "abstract_principle": "A choice changes later options.",
                "constraints": ["The consequence must remain visible."],
                "conflict_generators": ["Two benefits cannot both be retained."],
                "review_checks": ["Verify the later state change."],
                "copyright_boundaries": ["Mechanism only."],
                "knowledge_kind": "NARRATIVE_INTELLIGENCE",
                "semantic_family": "NARRATIVE_MECHANISM",
                "mechanism": "Bind a choice to a later constraint.",
                "applicability": ["A plan needs a causal choice."],
                "failure_conditions": ["No later option changes."],
                "selection_tags": {
                    "genre": [],
                    "conflict": [],
                    "reader_effect": [],
                    "theme": [],
                },
                "repetition_key": f"bounded-mechanism-{index}",
                "originality_boundary": {
                    "source_specific_sequence_reusable": False,
                    "named_entity_substitution_allowed": False,
                    "expression_reuse_allowed": False,
                },
            },
            "lineage": {},
            "source_policy": {
                "knowledge_card_context_eligible": True,
                "raw_source_expression_included": False,
                "source_chunks_direct_context_eligible": False,
                "fixture_protocol_only": False,
            },
        },
    }


class MkaosAuthorityDomainTests(unittest.TestCase):
    def test_typed_applicability_checks_preserve_evidence_and_uncertainty(self) -> None:
        card = _planning_card(0)
        abstract = card["content"]["abstract_content"]
        abstract.pop("applicability")
        abstract.pop("failure_conditions")
        contract = {
            "schema_version": "knowledge-applicability.v1",
            "usage_role": "MECHANISM",
            "prerequisites": [{"condition_id": "water", "path": "/story_state/resources/water", "operator": "GTE", "value": 2}],
            "exceptions": [{"condition_id": "contaminated", "path": "/story_state/contaminated", "operator": "EQ", "value": True}],
            "hard_conflicts": [{"condition_id": "prohibition", "path": "/hard_constraints", "operator": "CONTAINS", "value": "No chemical extraction"}],
        }
        abstract["applicability_contract"] = contract

        def select(state, hard=()):
            return select_narrative_intelligence(NarrativeIntelligenceNeed(
                scope="SCENE", target_stage="chapter_plan.generate", hard_constraints=hard,
                condition_sources={"story_state": {"asset_version_id": "state:v7", "content_hash": "sha256:" + "d" * 64, "content": state}},
            ), (card,))

        applicable = select({"resources": {"water": 3}, "contaminated": False})["selected"][0]["applicability_assessment"]
        self.assertEqual(applicable["status"], "APPLICABLE")
        self.assertEqual(applicable["checks"][0]["source_asset_version_id"], "state:v7")
        conditional = select({"resources": {"water": 1}, "contaminated": False})["selected"][0]["applicability_assessment"]
        self.assertEqual(conditional["status"], "CONDITIONAL")
        self.assertEqual(conditional["unmet_prerequisites"][0]["actual_value"], 1)
        missing = select({})["selected"][0]["applicability_assessment"]
        self.assertEqual(missing["checks"][0]["result"], "UNKNOWN")
        exception = select({"resources": {"water": 3}, "contaminated": True})
        self.assertEqual(exception["selected"], [])
        self.assertEqual(exception["rejected"][0]["applicability_assessment"]["status"], "REJECTED")
        conflict = select({"resources": {"water": 3}, "contaminated": False}, ("No chemical extraction",))
        self.assertEqual(conflict["selected"], [])
        self.assertEqual(conflict["rejected"][0]["applicability_assessment"]["rejection_reasons"], ["HARD_CONFLICTS:prohibition"])

    def test_free_text_applicability_is_unknown_not_formal_proof(self) -> None:
        card = _planning_card(1)
        result = select_narrative_intelligence(NarrativeIntelligenceNeed(scope="SCENE", target_stage="chapter_plan.generate"), (card,))
        assessment = result["selected"][0]["applicability_assessment"]
        self.assertEqual(assessment["status"], "UNKNOWN")
        self.assertEqual(assessment["usage_role"], "INSPIRATION")
        self.assertTrue(all(item["method"] == "SEMANTIC_UNVERIFIED" for item in assessment["checks"]))

    def test_required_parent_mechanism_survives_repetition_but_not_missing_version(self) -> None:
        card = _planning_card(0)
        need = NarrativeIntelligenceNeed(
            scope="SCENE", target_stage="chapter_plan.generate",
            recently_used_repetition_keys=("bounded-mechanism-0",),
            required_card_asset_version_ids=("card:0:v1",),
        )
        selected = select_narrative_intelligence(need, (card,))["selected"]
        self.assertEqual(selected[0]["knowledge_card_asset_version_id"], "card:0:v1")
        with self.assertRaisesRegex(KernelError, "REQUIRED_KNOWLEDGE_UNAVAILABLE"):
            select_narrative_intelligence(need, ())

    def test_typed_predicates_reject_nonfinite_numbers_and_invalid_pointer_escape(self) -> None:
        from novel_forge.modules.mkaos_authority.applicability import validate_applicability_contract

        for value, path in ((float("nan"), "/state/water"), (float("inf"), "/state/water"), (1, "/state/bad~2key")):
            with self.subTest(value=value, path=path), self.assertRaisesRegex(KernelError, "MKAOS_APPLICABILITY_INVALID"):
                validate_applicability_contract({
                    "schema_version": "knowledge-applicability.v1", "usage_role": "MECHANISM",
                    "prerequisites": [{"condition_id": "water", "path": path, "operator": "GTE", "value": value}],
                    "exceptions": [], "hard_conflicts": [],
                })

    def test_prose_assessment_never_launders_hidden_state_values_or_verdicts(self) -> None:
        from novel_forge.modules.mkaos_authority.applicability import prose_applicability_view

        view = prose_applicability_view({
            "status": "APPLICABLE", "checks": [{"condition_id": "hidden-cognition", "path": "/story_state/character_knowledge/0/status", "method": "DETERMINISTIC_TYPED_PREDICATE", "group": "prerequisites", "result": "TRUE", "actual_value": "hidden truth", "source_asset_version_id": "state:v2"}],
            "unmet_prerequisites": [], "exceptions": [],
        })
        self.assertNotIn("hidden truth", str(view))
        self.assertEqual(view["status"], "UNKNOWN")
        self.assertEqual(view["checks"][0]["result"], "UNKNOWN")
        self.assertEqual(view["checks"][0]["source_asset_version_id"], "state:v2")

    def test_required_constraints_and_source_identity_are_lossless(self) -> None:
        from novel_forge.modules.story_planning_runtime.execution import _required_selection_terms

        constraints = [f"constraint-{index}" for index in range(40)] + ["不得" * 700]
        extracted = _required_selection_terms([{"hard_constraints": constraints}], {"hard_constraints"})
        need = NarrativeIntelligenceNeed(scope="STORY", target_stage="book_plan.generate", hard_constraints=extracted, condition_sources={"story_state": {"asset_version_id": "state:v1", "content_hash": "hash", "content": {"private": "not duplicated"}}})
        self.assertEqual(set(need.hard_constraints), set(constraints))
        self.assertNotIn("private", str(need.to_dict()))
        self.assertEqual(need.to_dict()["condition_sources"]["story_state"]["asset_version_id"], "state:v1")

    def test_experimental_approval_requires_exact_real_provider_scope(self) -> None:
        project_id = "project:experimental"
        workspace_id = "workspace:experimental"
        reviewer_id = "operator:experimental-policy"
        policy_version = "experimental-policy.v1"
        candidate = {
            "project_id": project_id,
            "workspace_id": workspace_id,
            "status": "NEEDS_REVIEW",
            "lifecycle": "CANDIDATE",
            "eligibility": "PENDING_EVALUATION",
            "governance": "CLEAR",
            "content": {
                "execution_evidence": {
                    "proof": {
                        "fixture_protocol_only": False,
                        "real_provider_proven": True,
                        "production_verified": False,
                    }
                }
            },
        }
        application = MkaosAuthorityApplication(
            "postgresql://not-used",
            application_build_id="test",
            commit_sha="f" * 40,
            experimental_approval_policy=ExperimentalKnowledgeApprovalPolicy(
                project_id=project_id,
                workspace_id=workspace_id,
                policy_version=policy_version,
                reviewer_id=reviewer_id,
            ),
        )

        contract = application._require_approvable(
            candidate,
            project_id=project_id,
            workspace_id=workspace_id,
            policy_version=policy_version,
            reviewer_id=reviewer_id,
            approval_class="EXPERIMENTAL_VALIDATION",
        )

        self.assertEqual(
            contract["review_class"], "EXPERIMENTAL_POLICY_APPROVAL_NOT_HUMAN"
        )
        self.assertFalse(contract["production_context_eligible"])
        self.assertTrue(contract["experimental_context_eligible"])
        with self.assertRaisesRegex(
            KernelError, "MKAOS_EXPERIMENTAL_APPROVAL_SCOPE_INVALID"
        ):
            application._require_approvable(
                candidate,
                project_id=project_id,
                workspace_id=workspace_id,
                policy_version=policy_version,
                reviewer_id="operator:other",
                approval_class="EXPERIMENTAL_VALIDATION",
            )

    def test_book_knowledge_access_policy_distinguishes_empty_deny_from_default(
        self,
    ) -> None:
        denied = resolve_book_knowledge_access_policy(
            production_profile={
                "knowledge_access_policy": {
                    "policy_id": "comparison-a",
                    "policy_version": 1,
                    "mode": "DENY_ALL",
                    "allowed_knowledge_card_asset_version_ids": [],
                }
            },
            project_id="project:comparison",
            book_id="book:a",
        )
        default = resolve_book_knowledge_access_policy(
            production_profile={},
            project_id="project:comparison",
            book_id="book:legacy",
        )

        self.assertEqual(denied["mode"], "DENY_ALL")
        self.assertTrue(denied["configured_explicitly"])
        self.assertEqual(default["mode"], "PROJECT_DEFAULT")
        self.assertFalse(default["configured_explicitly"])
        self.assertNotEqual(denied["policy_hash"], default["policy_hash"])
        self.assertEqual(
            validate_book_knowledge_access_policy(
                denied,
                project_id="project:comparison",
                book_id="book:a",
            ),
            denied,
        )

    def test_narrative_selection_does_not_truncate_project_pool_at_500(self) -> None:
        cards = [_planning_card(index) for index in range(501)]
        query = MkaosAuthorityQuery("postgresql://not-used")
        need = NarrativeIntelligenceNeed(
            scope="STORY",
            target_stage="book_plan.generate",
        )
        with patch.object(query, "_planning_cards", return_value=cards) as load:
            selection = query.resolve_narrative_intelligence(
                project_id="project:large-pool",
                need=need,
                limit=6,
            )

        load.assert_called_once_with(
            project_id="project:large-pool",
            allowed_asset_version_ids=None,
        )
        self.assertEqual(selection["examined_card_count"], 501)
        self.assertEqual(selection["eligible_card_count"], 501)
        self.assertFalse(selection["pool_truncated"])
        self.assertEqual(
            selection["pool_query_mode"], "ALL_PROJECT_ELIGIBLE_NO_TRUNCATION"
        )

    def test_experimental_card_requires_exact_experimental_allowlist(self) -> None:
        project_id = "project:experimental"
        book_id = "book:experimental"
        policy_version = "experimental-policy.v1"
        card = _planning_card(0)
        card["project_id"] = project_id
        card["workspace_id"] = "workspace:experimental"
        content = dict(card["content"])
        source_policy = dict(content["source_policy"])
        source_policy.update(
            {
                "approval_class": "EXPERIMENTAL_VALIDATION",
                "review_class": "EXPERIMENTAL_POLICY_APPROVAL_NOT_HUMAN",
                "production_context_eligible": False,
                "experimental_context_eligible": True,
                "approval_policy_version": policy_version,
                "activation_scope": {
                    "kind": "ISOLATED_PROJECT_AND_WORKSPACE",
                    "project_id": project_id,
                    "workspace_id": "workspace:experimental",
                },
            }
        )
        content["source_policy"] = source_policy
        card["content"] = content
        query = MkaosAuthorityQuery("postgresql://not-used")
        access = resolve_book_knowledge_access_policy(
            production_profile={
                "knowledge_access_policy": {
                    "policy_id": "experimental-comparison",
                    "policy_version": 1,
                    "mode": "ALLOW_ONLY",
                    "allowed_knowledge_card_asset_version_ids": ["card:0:v1"],
                    "usage_scope": "EXPERIMENTAL_VALIDATION",
                    "experimental_policy_version": policy_version,
                }
            },
            project_id=project_id,
            book_id=book_id,
        )
        with patch.object(query, "_planning_cards", return_value=[card]):
            experimental = query.resolve_narrative_intelligence(
                project_id=project_id,
                book_id=book_id,
                need=NarrativeIntelligenceNeed(
                    scope="STORY", target_stage="book_plan.generate"
                ),
                knowledge_access_policy=access,
            )
            production = query.resolve_narrative_intelligence(
                project_id=project_id,
                need=NarrativeIntelligenceNeed(
                    scope="STORY", target_stage="book_plan.generate"
                ),
            )

        self.assertEqual(experimental["eligible_card_count"], 1)
        self.assertEqual(experimental["pool_query_mode"], "EXACT_ALLOWLIST")
        self.assertEqual(production["eligible_card_count"], 0)

    def test_explicit_deny_all_never_queries_or_falls_back_to_project_cards(
        self,
    ) -> None:
        query = MkaosAuthorityQuery("postgresql://not-used")
        policy = resolve_book_knowledge_access_policy(
            production_profile={
                "knowledge_access_policy": {
                    "mode": "DENY_ALL",
                    "allowed_knowledge_card_asset_version_ids": [],
                }
            },
            project_id="project:comparison",
            book_id="book:a",
        )
        with patch.object(query, "_planning_cards") as load:
            selection = query.resolve_narrative_intelligence(
                project_id="project:comparison",
                book_id="book:a",
                need=NarrativeIntelligenceNeed(
                    scope="STORY", target_stage="book_plan.generate"
                ),
                knowledge_access_policy=policy,
            )

        load.assert_not_called()
        self.assertEqual(selection["selection_status"], "NO_ELIGIBLE_MATCH")
        self.assertEqual(selection["selected"], [])
        self.assertEqual(selection["pool_query_mode"], "DENY_ALL_NO_QUERY")

    def test_exact_allowlist_fails_closed_when_one_card_is_ineligible(self) -> None:
        query = MkaosAuthorityQuery("postgresql://not-used")
        policy = resolve_book_knowledge_access_policy(
            production_profile={
                "knowledge_access_policy": {
                    "mode": "ALLOW_ONLY",
                    "allowed_knowledge_card_asset_version_ids": [
                        "card:0:v1",
                        "card:500:v1",
                    ],
                }
            },
            project_id="project:comparison",
            book_id="book:b",
        )
        with (
            patch.object(query, "_planning_cards", return_value=[_planning_card(0)]),
            self.assertRaisesRegex(
                KernelError, "PLANNING_KNOWLEDGE_ALLOWLIST_INELIGIBLE"
            ),
        ):
            query.resolve_narrative_intelligence(
                project_id="project:comparison",
                book_id="book:b",
                need=NarrativeIntelligenceNeed(
                    scope="STORY", target_stage="book_plan.generate"
                ),
                knowledge_access_policy=policy,
            )

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


def test_narrative_method_activation_rejects_operational_strings_in_semantic_fields():
    from novel_forge.modules.mkaos_authority.domain import assert_narrative_method_activation_safe
    valid = {"knowledge_kind": "NARRATIVE_INTELLIGENCE", "constraints": ["能力进步须由下一次行动显示；不强制牺牲。"],
             "lineage": {"project_id": "research-project"}, "source_finding_codes": ["F_ACTION"]}
    assert_narrative_method_activation_safe(valid)
    for field in ("mechanism", "constraints", "review_checks"):
        with unittest.TestCase().assertRaisesRegex(KernelError, "OPERATIONAL_LEAK"):
            assert_narrative_method_activation_safe({**valid, field: ["project_id=research; observation_hash=sha256:fixture"]})
