from __future__ import annotations

from copy import deepcopy

import pytest

from novel_forge.modules.chapter_authority.execution_gateway import (
    _required_language_from_context,
    _stage_semantic_contract,
    default_chapter_fixture_response,
)
from novel_forge.modules.chapter_authority.provider_output_contracts import (
    chapter_provider_output_schema,
    chapter_provider_output_schema_ref,
    validate_chapter_provider_output_against_schema,
    validate_chapter_provider_output_semantics,
    validate_chapter_provider_output_schema,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.chapter_authority.model_effects import normalize_model_output


CANON_FIELDS = (
    "world_state_changes",
    "faction_state_changes",
    "location_state_changes",
    "consequence_changes",
    "conflict_state_changes",

    "canon_facts",
    "character_state_changes",
    "relationship_changes",
    "timeline_events",
    "foreshadow_changes",
    "promise_changes",
    "obligation_changes",
    "reward_changes",
    "world_rule_usages",
    "power_state_changes",
    "plot_thread_changes",
    "resource_state_changes",
    "narrative_pattern_fingerprints",
    "theme_movements",
    "antagonist_pressure_changes",
    "character_knowledge_changes",
    "character_belief_changes",
    "character_arc_changes",
    "arc_state_changes",
    "disclosure_events",
    "arc_evidence",
    "realization_evidence",
)


def test_agent_turn_contract_requires_exactly_one_action() -> None:
    schema = chapter_provider_output_schema("agent_session")
    assert schema["properties"]["action"]["enum"] == ["TOOL_CALL", "FINAL"]
    tool = validate_chapter_provider_output_schema(
        "agent_session",
        {
            "message": "Inspect accepted state.",
            "action": "TOOL_CALL",
            "tool_call": {
                "tool_name": "narrative.query_accepted",
                "arguments": {"payload_json": "{}"},
                "reason": "ground in accepted facts",
            },
            "final_response": None,
        },
    )
    normalized = normalize_model_output("agent_session", tool)
    assert normalized["tool_call"]["tool_name"] == "narrative.query_accepted"
    assert normalized["tool_call"]["arguments"] == {}
    assert normalize_model_output("agent_session", normalized) == normalized
    final = validate_chapter_provider_output_schema(
        "agent_session",
        {
            "message": "Report the bounded result.",
            "action": "FINAL",
            "tool_call": None,
            "final_response": {"payload_json": '{"accepted_only":true}'},
        },
    )
    normalized_final = normalize_model_output("agent_session", final)
    assert normalized_final["final_response"] == {"accepted_only": True}
    assert normalize_model_output("agent_session", normalized_final) == normalized_final
    with pytest.raises(KernelError, match="exactly one"):
        normalize_model_output(
            "agent_session",
            {
                **tool,
                "final_response": {"candidate_only": True},
            },
        )


def test_revision_prompt_requires_issue_resolution_and_language_continuity() -> None:
    contract = _stage_semantic_contract("revision")

    assert "Resolve every supplied review issue" in contract
    assert "Preserve the reader-facing language" in contract
    assert "resolved_issue_codes" in contract
    assert "smallest bounded edit" in contract
    assert "preserve all unrelated scenes" in contract
    assert "Never replace the full chapter with a summary or excerpt" in contract


def test_narrative_evaluation_contract_consumes_exact_foundation_closure() -> None:
    contract = _stage_semantic_contract("narrative_semantic_evaluation")

    assert "EXACT_CANDIDATE_AND_CANONICAL_DEPENDENCIES" in contract
    assert "sole candidate under evaluation" in contract
    assert "exact qualified dependency's semantic_payload" in contract
    assert "Do not consume prior qualification verdicts" in contract
    assert "demand downstream plans" in contract


def test_book_plan_prompt_closes_realization_and_obligation_invariants() -> None:
    contract = _stage_semantic_contract("book_plan.generate")

    assert "ANCHOR < DEFINED < DETAILED < ACTIVE" in contract
    assert "every CURRENT entity's realization_level" in contract
    assert "obligation_id must copy one exact identity" in contract
    assert "setup_chapter <= payoff_not_before <= payoff_due_by" in contract


def test_retrieval_prompt_freezes_model_dimensions_and_rejects_placeholders() -> None:
    contract = _stage_semantic_contract(
        "retrieval",
        embedding_output_contract={
            "embedding_model": "gpt-semantic-test",
            "embedding_dimensions": 8,
            "vector_normalization": "L2_UNIT",
            "placeholder_vectors_allowed": False,
        },
    )

    assert '"gpt-semantic-test"' in contract
    assert "exactly 8 finite numeric entries" in contract
    assert "L2 norm" in contract
    assert "provider-unavailable" in contract


def test_retrieval_query_expansion_is_a_strict_proposal_only_contract() -> None:
    value = validate_chapter_provider_output_schema(
        "retrieval_query_expansion",
        {
            "contract_version": "retrieval-expansion-plan-v1",
            "queries": [
                {
                    "query_id": "query:oath",
                    "text": "bridge oath witness",
                    "reason": "missing causal antecedent",
                    "targets": ["fact:fact:oath-origin"],
                    "selectors": {"character_ids": ["character:mei"]},
                    "temporal_range": {"from_chapter": 1, "to_chapter": 100},
                }
            ],
        },
    )
    assert normalize_model_output("retrieval_query_expansion", value) == value
    contract = _stage_semantic_contract("retrieval_query_expansion")
    assert "proposal" in contract
    assert "never" in contract.lower()
    assert "SQL" in contract

    invalid = deepcopy(value)
    invalid["queries"][0]["selectors"] = {
        "asset_version_ids": ["asset-version:arbitrary"]
    }
    with pytest.raises(KernelError, match="is not allowed"):
        validate_chapter_provider_output_schema("retrieval_query_expansion", invalid)


def test_scripted_expansion_exercises_only_the_typed_missing_evidence_contract() -> (
    None
):
    output = default_chapter_fixture_response(
        "retrieval_query_expansion",
        {
            "accepted_boundary": {"accepted_through_chapter": 40},
            "coverage": {
                "sufficient": False,
                "missing": {"fact_ids": ["fact:oath-origin"]},
            },
            "coverage_contract": {"selectors": {"entity_ids": ["entity:bridge"]}},
        },
    )

    assert (
        validate_chapter_provider_output_schema("retrieval_query_expansion", output)
        == output
    )
    assert output["queries"][0]["targets"] == ["fact:fact:oath-origin"]
    assert output["queries"][0]["selectors"] == {"entity_ids": ["entity:bridge"]}


def test_zh_cn_language_contract_overrides_legacy_revision_language() -> None:
    contract = _stage_semantic_contract("revision", required_language="zh-CN")

    assert "zh-CN" in contract
    assert "Simplified Chinese" in contract
    assert "even when the input draft uses another language" in contract


def test_language_contract_is_discovered_in_governed_context_only() -> None:
    assert (
        _required_language_from_context(
            {
                "context_segments": [
                    {
                        "structured_facts": [
                            {
                                "key": "language_contract",
                                "value": {
                                    "required_language": "zh-CN",
                                    "reader_facing_prose": "REQUIRED",
                                },
                            }
                        ]
                    }
                ]
            }
        )
        == "zh-CN"
    )
    assert _required_language_from_context({"language": "English"}) is None


def test_rereview_prompt_reports_only_acceptance_blocking_defects() -> None:
    contract = _stage_semantic_contract("rereview")

    assert "acceptance-blocking" in contract
    assert "minor polish" in contract
    assert "issues=[]" in contract


def test_arc_planning_prompt_requires_exact_authority_scope_references() -> None:
    contract = _stage_semantic_contract("arc_plan.generate")

    assert "immutable Authority reference" in contract
    assert "cross_volume_scope to exactly the ordered VolumePlan Authority" in contract
    assert "planning_command.input_versions.volume_plan" in contract
    assert "arc_scope_volume_plan_version_ids" in contract
    assert "Never use a logical label such as volume:1" in contract
    assert "Thread -> Arc -> Arc Segment" in contract


def test_chapter_group_prompt_requires_exact_search_horizon_and_disclosures() -> None:
    contract = _stage_semantic_contract("chapter_group_plan.generate")

    assert "narrative_search_planning_horizon.chapter_range" in contract
    assert "one ordered chapter_function_matrix row for every Chapter" in contract
    assert "narrative_event_chain cover every Chapter" in contract
    assert "knowledge_boundary.reader_may_learn" in contract
    assert "must not occur in forbidden_disclosures" in contract


def test_chapter_planning_prompt_requires_executable_narrative_plan() -> None:
    contract = _stage_semantic_contract("chapter_plan.generate")

    assert "executable Chapter plan" in contract
    assert "Primary/Secondary/Touch/Hold" in contract
    assert "knowledge boundaries" in contract
    assert "scene or scene-group execution units" in contract
    assert "expected exit state" in contract
    assert "Do not put Reader Knowledge or Disclosure" in contract
    assert "mixed audience" in contract
    assert "HINT -> HINTED" in contract
    assert "WITHHOLD does not advance" in contract
    assert "Use resource_state only for a quantifiable balance" in contract


def test_quality_prompt_and_schema_version_require_dimension_evidence() -> None:
    contract = _stage_semantic_contract("quality_platform")

    assert "Every returned dimension" in contract
    assert "at least one concrete evidence location" in contract
    assert (
        chapter_provider_output_schema_ref("quality_platform")
        == "schema:chapter-provider-output:quality_platform:v2"
    )
    assert (
        chapter_provider_output_schema_ref("draft")
        == "schema:chapter-provider-output:draft:v2"
    )
    assert (
        chapter_provider_output_schema_ref("canon_extraction")
        == "schema:chapter-provider-output:canon_extraction:v16"
    )


def test_longform_quality_prompt_distinguishes_proven_noop_from_missing_state() -> None:
    contract = _stage_semantic_contract("quality_longform")

    assert "no state-changing use or claim" in contract
    assert "current state candidates contain no transition" in contract
    assert "PASSED with concrete no-op evidence" in contract
    assert "claims a state or transition" in contract
    assert "INSUFFICIENT_EVIDENCE" in contract
    assert "canon_conflicts as the authoritative deterministic" in contract
    assert "governed_world_rules" in contract


def test_platform_quality_prompt_scopes_internal_assisted_content_policy() -> None:
    contract = _stage_semantic_contract("quality_platform")

    assert "compiled_platform_policy" in contract
    assert "release_scope" in contract
    assert "internal Provider validation" in contract
    assert "Do not duplicate source-lineage" in contract
    assert "external publication is not a defect" in contract


def test_canon_prompt_explains_unique_semantic_slot_encoding() -> None:
    contract = _stage_semantic_contract("canon_extraction")

    assert "(subject, predicate, impact_type)" in contract
    assert "at most once" in contract
    assert "authorizes_testimony" in contract
    assert "authorizes_public_identification" in contract
    assert "Actual accepted prose" in contract
    assert "chars:<start>-<end>:<summary>" in contract
    assert "Planning context alone never proves observation" in contract
    schema = chapter_provider_output_schema("canon_extraction")
    resolution = schema["properties"]["arc_evidence"]["items"]["properties"][
        "resolution_evidence"
    ]
    assert "accepted_revision character-span" in resolution["description"]
    assert "copy disclosure_id" in contract
    assert "do not expand the audience" in contract


def test_canon_prompt_binds_transition_preconditions_to_accepted_state() -> None:
    contract = _stage_semantic_contract("canon_extraction")

    assert "accepted Story State" in contract
    assert "first occurrence" in contract
    assert "leave from_status, from_state, from_stance, and from_tier null" in contract


def test_canon_prompt_binds_fact_supersession_to_accepted_canon_event() -> None:
    contract = _stage_semantic_contract("canon_extraction")

    assert "accepted Canon facts" in contract
    assert "source_event_id" in contract
    assert "supersedes_event_id" in contract
    assert "omit the redundant fact" in contract
    assert "Never paraphrase an unchanged accepted fact" in contract


def test_canon_prompt_requires_character_knowledge_precondition_closure() -> None:
    contract = _stage_semantic_contract("canon_extraction")

    assert "requires_fact_ids" in contract
    assert "atomic character_knowledge_changes item with fact_id" in contract
    assert "never bundle multiple newly learned facts" in contract
    assert "character-specific epistemic preconditions" in contract
    assert (
        "world-rule availability is not automatically character knowledge"
        in contract.lower()
    )
    assert "never add unsupported knowledge merely to satisfy validation" in contract
    assert "Story Truth, Character Knowledge, Character Belief" in contract
    assert "a belief may be false" in contract
    assert "use only stance with BELIEVES, DOUBTS" in contract
    assert "from_stance only for an exact accepted baseline" in contract
    assert "source_id and target_id" in contract
    assert "entity_id cannot replace an endpoint" in contract
    assert "generic entity_id never substitutes" in contract
    assert "rule_id" in contract
    assert "including character-facing events" in contract
    assert "reader-facing Disclosure alone" in contract
    assert "deterministically projected into Reader Knowledge" in contract


def test_canon_prompt_separates_numeric_resource_balance_from_object_status() -> None:
    contract = _stage_semantic_contract("canon_extraction")

    assert "resource_state_changes only for quantifiable resource balances" in contract
    assert "initial resource baseline must set balance_after" in contract
    assert "balance_before, delta, and balance_after" in contract
    assert "custody, location, protection, ownership" in contract
    assert "leave resource_state_changes empty" in contract


def test_canon_semantics_normalizes_initial_resource_balance() -> None:
    value = _valid("canon_extraction")
    value["resource_state_changes"] = [
        {
            "summary": "The protagonist starts with three credits.",
            "effective_from_chapter": 1,
            "supersedes_event_id": None,
            "event_id": None,
            "reward_id": None,
            "fingerprint_id": None,
            "antagonist_id": None,
            "character_id": None,
            "source_id": None,
            "target_id": None,
            "thread_id": None,
            "promise_id": None,
            "rule_id": None,
            "entity_id": "protagonist",
            "resource_id": "credits",
            "status": None,
            "from_status": None,
            "stance": None,
            "from_stance": None,
            "from_state": None,
            "from_stage": None,
            "life_status": None,
            "action_state": None,
            "canonical_name": None,
            "transition_kind": None,
            "state": None,
            "stage": None,
            "tier": None,
            "from_tier": None,
            "balance_before": None,
            "delta": None,
            "balance_after": 3,
            "exception": None,
            "resurrection_authorized": None,
            "allow_negative_balance": None,
            "payoff_evidence": None,
            "cost": None,
            "requires_fact_ids": None,
            "acquired_fact_ids": None,
            "change_reasons": None,
            "fact_id": None,
            "proposition_id": None,
            "disclosure_id": None,
            "arc_id": None,
            "audience": None,
            "disclosure_mode": None,
            "presentation_channel": None,
            "belief_confidence": None,
            "evidence_quote": "The observed claim.",
            "claim_kind": "OBJECTIVE_EVENT",
            "evidence_start": 0,
            "evidence_end": 12,
            "confidence": 0.9,
            "impact_type": "resource_baseline",
        }
    ]

    structural = validate_chapter_provider_output_schema("canon_extraction", value)
    normalized = validate_chapter_provider_output_semantics(
        "canon_extraction", structural
    )

    assert normalized["resource_state_changes"][0]["balance"] == 3


def test_canon_accepts_typed_unified_obligation_payoff_evidence() -> None:
    value = _valid("canon_extraction")
    value["obligation_changes"] = [
        {
            "obligation_id": "promise:late",
            "obligation_type": "PROMISE",
            "causal_requirement": None,
            "causal_plan_asset_version_id": None,
            "from_status": "OPEN",
            "status": "FULFILLED",
            "priority": "HIGH",
            "target_window": {
                "status": "SCHEDULED",
                "from_chapter": 1,
                "to_chapter": 2,
            },
            "payoff_evidence": {
                "asset_version_id": "draft:v2",
                "event_id": "payoff:event:2",
            },
            "linked_arc_ids": ["arc:v1"],
            "summary": "The accepted choice visibly fulfills the promise.",
            "evidence_quote": "The observed claim.",
            "claim_kind": "OBJECTIVE_EVENT",
            "evidence_start": 0,
            "evidence_end": 24,
            "confidence": 0.96,
            "impact_type": "narrative_obligation_payoff",
        }
    ]

    structural = validate_chapter_provider_output_schema("canon_extraction", value)
    normalized = validate_chapter_provider_output_semantics(
        "canon_extraction", structural
    )

    assert normalized["obligation_changes"][0]["status"] == "FULFILLED"

    value["obligation_changes"][0]["payoff_evidence"] = None
    structural = validate_chapter_provider_output_schema("canon_extraction", value)
    with pytest.raises(KernelError, match="typed payoff evidence"):
        validate_chapter_provider_output_semantics("canon_extraction", structural)


def test_canon_semantics_atomizes_legacy_character_knowledge_bundle() -> None:
    value = _valid("canon_extraction")
    change_schema = chapter_provider_output_schema("canon_extraction")["properties"][
        "character_knowledge_changes"
    ]["items"]
    bundled = {
        key: (
            "The witness learns both ledger facts."
            if key == "summary"
            else "character:lin"
            if key == "character_id"
            else ["fact:ledger-owner", "fact:ledger-date", "fact:ledger-owner"]
            if key == "acquired_fact_ids"
            else "CHARACTER_KNOWLEDGE_ACQUIRED"
            if key == "impact_type"
            else "KNOWN"
            if key == "status"
            else "The observed claim."
            if key == "evidence_quote"
            else "OBJECTIVE_EVENT"
            if key == "claim_kind"
            else 0
            if key == "evidence_start"
            else 42
            if key == "evidence_end"
            else 0.95
            if key == "confidence"
            else None
        )
        for key in change_schema["properties"]
    }
    value["character_knowledge_changes"] = [bundled]

    structural = validate_chapter_provider_output_schema("canon_extraction", value)
    normalized = validate_chapter_provider_output_semantics(
        "canon_extraction", structural
    )

    assert [
        (item["character_id"], item["fact_id"])
        for item in normalized["character_knowledge_changes"]
    ] == [
        ("character:lin", "fact:ledger-owner"),
        ("character:lin", "fact:ledger-date"),
    ]
    assert all(
        "acquired_fact_ids" not in item
        for item in normalized["character_knowledge_changes"]
    )
    assert all(
        item["status"] == "KNOWN" and "state" not in item
        for item in normalized["character_knowledge_changes"]
    )


def test_canon_schema_rejects_character_knowledge_state_alias() -> None:
    value = _valid("canon_extraction")
    change_schema = chapter_provider_output_schema("canon_extraction")["properties"][
        "character_knowledge_changes"
    ]["items"]
    change = {
        key: (
            "The witness learns the ledger fact."
            if key == "summary"
            else "character:lin"
            if key == "character_id"
            else "fact:ledger-owner"
            if key == "fact_id"
            else "KNOWN"
            if key == "state"
            else None
        )
        for key in change_schema["properties"]
    }
    value["character_knowledge_changes"] = [change]

    with pytest.raises(KernelError) as error:
        validate_chapter_provider_output_schema("canon_extraction", value)

    assert error.value.code == "CHAPTER_PROVIDER_OUTPUT_SCHEMA_INVALID"


def test_canon_schema_requires_typed_character_belief_stance() -> None:
    value = _valid("canon_extraction")
    change_schema = chapter_provider_output_schema("canon_extraction")["properties"][
        "character_belief_changes"
    ]["items"]
    change = {
        key: (
            "The witness is no longer certain silence is safe."
            if key == "summary"
            else "character:lin"
            if key == "character_id"
            else "proposition:silence-is-safe"
            if key == "proposition_id"
            else "UNCERTAIN"
            if key == "stance"
            else 0.68
            if key == "belief_confidence"
            else "The observed claim."
            if key == "evidence_quote"
            else "OBJECTIVE_EVENT"
            if key == "claim_kind"
            else 0
            if key == "evidence_start"
            else 42
            if key == "evidence_end"
            else 0.95
            if key == "confidence"
            else "CHARACTER_BELIEF_CHANGED"
            if key == "impact_type"
            else None
        )
        for key in change_schema["properties"]
    }
    value["character_belief_changes"] = [change]

    structural = validate_chapter_provider_output_schema("canon_extraction", value)
    normalized = validate_chapter_provider_output_semantics(
        "canon_extraction", structural
    )

    assert normalized["character_belief_changes"][0]["stance"] == "UNCERTAIN"
    assert normalized["character_belief_changes"][0]["belief_confidence"] == 0.68
    assert "state" not in normalized["character_belief_changes"][0]
    assert "status" not in normalized["character_belief_changes"][0]


def test_canon_schema_rejects_character_belief_status_alias() -> None:
    value = _valid("canon_extraction")
    change_schema = chapter_provider_output_schema("canon_extraction")["properties"][
        "character_belief_changes"
    ]["items"]
    change = {
        key: (
            "The witness is uncertain."
            if key == "summary"
            else "character:lin"
            if key == "character_id"
            else "proposition:silence-is-safe"
            if key == "proposition_id"
            else "UNCERTAIN"
            if key == "status"
            else 0.68
            if key == "belief_confidence"
            else "The observed claim."
            if key == "evidence_quote"
            else "OBJECTIVE_EVENT"
            if key == "claim_kind"
            else 0
            if key == "evidence_start"
            else 42
            if key == "evidence_end"
            else 0.95
            if key == "confidence"
            else "CHARACTER_BELIEF_CHANGED"
            if key == "impact_type"
            else None
        )
        for key in change_schema["properties"]
    }
    value["character_belief_changes"] = [change]

    with pytest.raises(KernelError) as error:
        validate_chapter_provider_output_schema("canon_extraction", value)

    assert error.value.code == "CHAPTER_PROVIDER_OUTPUT_SCHEMA_INVALID"


def test_canon_schema_requires_typed_relationship_endpoints() -> None:
    value = _valid("canon_extraction")
    change_schema = chapter_provider_output_schema("canon_extraction")["properties"][
        "relationship_changes"
    ]["items"]
    assert change_schema["properties"]["source_id"] == {
        "type": "string",
        "minLength": 1,
    }
    assert change_schema["properties"]["target_id"] == {
        "type": "string",
        "minLength": 1,
    }
    change = {
        key: (
            "Lin and Mei enter a wary alliance."
            if key == "summary"
            else "lin-qiao:mei-an"
            if key == "entity_id"
            else "lin-qiao"
            if key == "character_id"
            else "mei-an"
            if key == "target_id"
            else "The observed claim."
            if key == "evidence_quote"
            else "OBJECTIVE_EVENT"
            if key == "claim_kind"
            else 0
            if key == "evidence_start"
            else 42
            if key == "evidence_end"
            else 0.95
            if key == "confidence"
            else "RELATIONSHIP_STATE_CHANGE"
            if key == "impact_type"
            else None
        )
        for key in change_schema["properties"]
    }
    value["relationship_changes"] = [change]

    with pytest.raises(KernelError) as error:
        validate_chapter_provider_output_schema("canon_extraction", value)

    assert error.value.code == "CHAPTER_PROVIDER_OUTPUT_SCHEMA_INVALID"
    assert "character_id" in str(error.value)

    change["character_id"] = None
    change["source_id"] = "lin-qiao"
    structural = validate_chapter_provider_output_schema("canon_extraction", value)
    normalized = validate_chapter_provider_output_semantics(
        "canon_extraction", structural
    )
    relationship = normalized["relationship_changes"][0]
    assert relationship["source_id"] == "lin-qiao"
    assert relationship["target_id"] == "mei-an"
    assert "character_id" not in relationship


@pytest.mark.parametrize(
    ("field", "identity_fields"),
    (
        ("character_state_changes", ("character_id",)),
        ("relationship_changes", ("source_id", "target_id")),
        ("timeline_events", ("event_id",)),
        ("foreshadow_changes", ("thread_id",)),
        ("promise_changes", ("promise_id",)),
        ("reward_changes", ("reward_id",)),
        ("world_rule_usages", ("rule_id",)),
        ("power_state_changes", ("character_id",)),
        ("plot_thread_changes", ("thread_id",)),
        ("resource_state_changes", ("entity_id", "resource_id")),
        ("narrative_pattern_fingerprints", ("fingerprint_id",)),
        ("theme_movements", ("entity_id",)),
        ("antagonist_pressure_changes", ("antagonist_id",)),
        ("character_arc_changes", ("character_id", "arc_id")),
        ("arc_state_changes", ("arc_id",)),
    ),
)
def test_canon_schema_requires_each_domain_identity(
    field: str,
    identity_fields: tuple[str, ...],
) -> None:
    properties = chapter_provider_output_schema("canon_extraction")["properties"][
        field
    ]["items"]["properties"]

    assert set(identity_fields) <= set(properties)
    for identity_field in identity_fields:
        assert properties[identity_field] == {"type": "string", "minLength": 1}


def test_canon_schema_exposes_epistemic_and_presentation_changes() -> None:
    schema = chapter_provider_output_schema("canon_extraction")

    assert "reader_knowledge_changes" not in schema["properties"]
    assert "disclosure_events" in schema["properties"]
    change = schema["properties"]["disclosure_events"]["items"]["properties"]
    assert {"fact_id", "disclosure_id", "audience", "disclosure_mode"}.issubset(change)
    assert change["disclosure_mode"]["enum"] == [
        "HINT",
        "PARTIAL",
        "MISDIRECT",
        "CONFIRM",
        "WITHHOLD",
    ]


def test_canon_semantics_rejects_generic_entity_as_world_rule_identity() -> None:
    value = _valid("canon_extraction")
    value["world_rule_usages"] = [
        {
            "summary": "A rule is exercised against the archive.",
            "entity_id": "archive:ledger",
            "state": "EXERCISED",
            "evidence_quote": "The observed claim.",
            "claim_kind": "OBJECTIVE_EVENT",
            "evidence_start": 0,
            "evidence_end": 12,
            "confidence": 0.9,
            "impact_type": "WORLD_RULE_USE",
        }
    ]

    with pytest.raises(KernelError) as raised:
        validate_chapter_provider_output_semantics("canon_extraction", value)

    assert raised.value.code == "CHAPTER_PROVIDER_OUTPUT_SEMANTIC_INVALID"
    assert "world_rule_usages" in str(raised.value)


def _valid(stage: str) -> dict[str, object]:
    if stage == "draft":
        return {"text": "The choice closes the only safe road home.", "scene_artifacts": []}
    if stage in {"review", "rereview"}:
        return default_chapter_fixture_response(stage, {"draft": {"text": "The choice closes the safe road home."}, "revision": {"text": "The choice closes the safe road home."}})
    if stage == "memo":
        return default_chapter_fixture_response(stage, {"execution_intent": {"scene_plans": [], "chapter_mission": {}, "chapter_objective": "A costly choice"}})
    if stage == "canon_support":
        return {"coverage": "COMPLETE", "no_change_supported": True, "claims": []}
    if stage == "revision":
        return {
            "text": "She burns the map while the witnesses watch.",
            "scene_artifacts": [],
            "resolved_issue_codes": ["COST_NOT_CONCRETE"],
        }
    if stage == "canon_extraction":
        return {"extraction_status": "EXTRACTED", "no_change_reason": "", **{
            field: (
                [
                    {
                        "subject": "protagonist",
                        "predicate": "made_choice",
                        "object": "exposed_record",
                        "effective_from_chapter": 1,
                        "supersedes_event_id": None,
                        "evidence_quote": "The observed claim.",
            "claim_kind": "OBJECTIVE_EVENT",
            "evidence_start": 0,
                        "evidence_end": 24,
                        "confidence": 0.91,
                        "impact_type": "chapter_event",
                    }
                ]
                if field == "canon_facts"
                else []
            )
            for field in CANON_FIELDS
        }}
    if stage.startswith("quality_"):
        return {
            "dimensions": [
                {
                    "dimension": "causal_clarity",
                    "gate_status": "PASSED",
                    "score": 91,
                    "confidence": 0.91,
                    "evidence_locations": [
                        {"start": 0, "end": 24, "claim": "visible choice"}
                    ],
                    "issue_codes": [],
                    "revision_strategies": [],
                }
            ]
        }
    if stage == "reader_outcome":
        return {
            "reader_state": {
                "continue_intent": 0.9,
                "curiosity": 0.8,
                "satisfaction": 0.8,
                "confusion": 0.1,
                "trust": 0.8,
                "character_attachment": 0.8,
                "antagonist_pressure": 0.7,
                "promise_expectation": 0.8,
                "payoff_satisfaction": 0.8,
                "drop_risk": 0.1,
                "repetition_fatigue": 0.1,
            },
            "evidence": [
                {
                    "asset_version_id": "draft:v2",
                    "location": "chapter",
                    "claim": "closing hook sustains curiosity",
                }
            ],
        }
    raise AssertionError(stage)


@pytest.mark.parametrize(
    "stage",
    (
        "draft",
        "review",
        "revision",
        "rereview",
        "canon_extraction",
        "quality_structural",
        "quality_commercial",
        "quality_source_originality",
        "quality_longform",
        "quality_platform",
        "reader_outcome",
    ),
)
def test_every_model_stage_has_a_strict_schema_and_accepts_its_contract(
    stage: str,
) -> None:
    schema = chapter_provider_output_schema(stage)

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert validate_chapter_provider_output_schema(stage, _valid(stage)) == _valid(
        stage
    )


def test_every_model_stage_schema_is_codex_strict_json_schema_compatible() -> None:
    """Codex strict output schemas must require every declared object property."""

    def assert_strict_object_contract(value: object, *, path: str) -> None:
        if isinstance(value, list):
            for index, item in enumerate(value):
                assert_strict_object_contract(item, path=f"{path}[{index}]")
            return
        if not isinstance(value, dict):
            return
        if value.get("type") == "object":
            properties = value.get("properties")
            assert isinstance(properties, dict), path
            assert set(value.get("required") or ()) == set(properties), path
            assert value.get("additionalProperties") is False, path
        for key, item in value.items():
            assert_strict_object_contract(item, path=f"{path}.{key}")

    for stage in (
        "draft",
        "review",
        "revision",
        "rereview",
        "canon_extraction",
        "quality_structural",
        "quality_commercial",
        "quality_source_originality",
        "quality_longform",
        "quality_platform",
        "reader_outcome",
    ):
        assert_strict_object_contract(
            chapter_provider_output_schema(stage),
            path=f"$.{stage}",
        )


def test_schema_validation_rejects_missing_required_field_before_semantics() -> None:
    with pytest.raises(KernelError) as raised:
        validate_chapter_provider_output_schema("review", {"score": 72})

    assert raised.value.code == "CHAPTER_PROVIDER_OUTPUT_SCHEMA_INVALID"
    assert "issues" in str(raised.value)


def test_schema_validation_rejects_additional_properties() -> None:
    value = _valid("draft")
    value["untrusted"] = True

    with pytest.raises(KernelError) as raised:
        validate_chapter_provider_output_schema("draft", value)

    assert raised.value.code == "CHAPTER_PROVIDER_OUTPUT_SCHEMA_INVALID"
    assert "untrusted" in str(raised.value)


def test_schema_validation_does_not_treat_boolean_as_number() -> None:
    value = deepcopy(_valid("quality_structural"))
    value["dimensions"][0]["confidence"] = True  # type: ignore[index]

    with pytest.raises(KernelError) as raised:
        validate_chapter_provider_output_schema("quality_structural", value)

    assert raised.value.code == "CHAPTER_PROVIDER_OUTPUT_SCHEMA_INVALID"
    assert "confidence" in str(raised.value)


def test_schema_validation_supports_nullable_boolean_canon_fields() -> None:
    value = deepcopy(_valid("canon_extraction"))
    change_schema = chapter_provider_output_schema("canon_extraction")["properties"][
        "character_state_changes"
    ]["items"]
    value["character_state_changes"] = [
        {
            key: (
                "The observed claim."
                if key == "evidence_quote"
                else "OBJECTIVE_EVENT"
                if key == "claim_kind"
                else False
                if key == "resurrection_authorized"
                else None
                if "null" in schema.get("type", [])
                else "character remains alive"
                if key == "summary"
                else "character:lin"
                if key == "character_id"
                else "CHARACTER_STATE_CONFIRMED"
                if key == "impact_type"
                else 0
                if key == "evidence_start"
                else 1
                if key == "evidence_end"
                else 0.9
            )
            for key, schema in change_schema["properties"].items()
        }
    ]

    assert validate_chapter_provider_output_schema("canon_extraction", value) == value
    normalized = validate_chapter_provider_output_semantics("canon_extraction", value)
    assert normalized["character_state_changes"][0]["resurrection_authorized"] is False


def test_quality_schema_requires_evidence_for_every_dimension() -> None:
    schema = chapter_provider_output_schema("quality_platform")
    locations = schema["properties"]["dimensions"]["items"]["properties"][
        "evidence_locations"
    ]
    assert locations["minItems"] == 1
    value = deepcopy(_valid("quality_platform"))
    value["dimensions"][0]["evidence_locations"] = []  # type: ignore[index]

    with pytest.raises(KernelError) as raised:
        validate_chapter_provider_output_schema("quality_platform", value)

    assert raised.value.code == "CHAPTER_PROVIDER_OUTPUT_SCHEMA_INVALID"
    assert "at least 1 items" in str(raised.value)


def test_shared_schema_validation_supports_integer_const_and_max_items() -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "chapter": {"type": "integer", "minimum": 1, "maximum": 3},
            "scope": {"type": "string", "const": "chapter:3"},
            "beats": {
                "type": "array",
                "minItems": 1,
                "maxItems": 2,
                "items": {"type": "string"},
            },
        },
        "required": ["chapter", "scope", "beats"],
        "additionalProperties": False,
    }

    assert (
        validate_chapter_provider_output_against_schema(
            "planning-proof",
            schema,
            {"chapter": 3, "scope": "chapter:3", "beats": ["choice"]},
        )["chapter"]
        == 3
    )
    with pytest.raises(KernelError, match="frozen constant"):
        validate_chapter_provider_output_against_schema(
            "planning-proof",
            schema,
            {"chapter": 3, "scope": "chapter:2", "beats": ["choice"]},
        )


@pytest.mark.parametrize(
    "text",
    (
        '{"stage":"revision","revision_markdown":"reader-facing prose"}',
        "修订后的正文。\n\n## 自检\n所有问题均已处理。",
        "修订后的正文。\n\n## 修订证据引用\n- ISSUE-1",
    ),
)
def test_revision_semantics_rejects_operator_metadata_inside_reader_prose(
    text: str,
) -> None:
    value = {"text": text, "resolved_issue_codes": ["ISSUE-1"]}

    with pytest.raises(KernelError) as raised:
        validate_chapter_provider_output_semantics("revision", value)

    assert raised.value.code == "CHAPTER_PROVIDER_OUTPUT_SEMANTIC_INVALID"


def test_revision_semantics_accepts_clean_reader_facing_prose() -> None:
    value = {
        "text": "她烧掉地图，火光照亮每一名见证人的脸。",
        "resolved_issue_codes": ["COST_NOT_CONCRETE"],
    }

    assert validate_chapter_provider_output_semantics("revision", value) == value


def test_canon_semantics_rejects_contradictory_subject_predicate_slot() -> None:
    value = _valid("canon_extraction")
    value["canon_facts"].append(
        {
            **value["canon_facts"][0],
            "object": "concealed_record",
        }
    )

    with pytest.raises(KernelError) as raised:
        validate_chapter_provider_output_semantics("canon_extraction", value)

    assert raised.value.code == "CHAPTER_PROVIDER_OUTPUT_SEMANTIC_INVALID"


def test_canon_semantics_accepts_exact_duplicate_for_authority_deduplication() -> None:
    value = _valid("canon_extraction")
    value["canon_facts"].append(dict(value["canon_facts"][0]))

    normalized = validate_chapter_provider_output_semantics("canon_extraction", value)

    assert "supersedes_event_id" not in normalized["canon_facts"][0]


def test_canon_semantics_allows_distinct_disclosures_from_one_prose_span() -> None:
    value = _valid("canon_extraction")
    shared = {
        "summary": "The record is shown.",
        "effective_from_chapter": 1,
        "supersedes_event_id": None,
        "fact_id": "fact:record",
        "disclosure_mode": "CONFIRM",
        "evidence_start": 10,
        "evidence_end": 40,
        "confidence": 1.0,
        "impact_type": "DISCLOSURE",
    }
    value["disclosure_events"] = [
        {
            **shared,
            "disclosure_id": "disclosure:record:reader",
            "audience": "READER",
        },
        {
            **shared,
            "disclosure_id": "disclosure:record:alice",
            "audience": "alice",
        },
    ]

    normalized = validate_chapter_provider_output_semantics("canon_extraction", value)

    assert len(normalized["disclosure_events"]) == 2


def test_canon_semantics_rejects_conflicting_disclosure_identity() -> None:
    value = _valid("canon_extraction")
    shared = {
        "summary": "The record is shown.",
        "effective_from_chapter": 1,
        "supersedes_event_id": None,
        "fact_id": "fact:record",
        "disclosure_id": "disclosure:record:reader",
        "audience": "READER",
        "evidence_start": 10,
        "evidence_end": 40,
        "confidence": 1.0,
        "impact_type": "DISCLOSURE",
    }
    value["disclosure_events"] = [
        {**shared, "disclosure_mode": "HINT"},
        {**shared, "disclosure_mode": "CONFIRM"},
    ]

    with pytest.raises(KernelError) as raised:
        validate_chapter_provider_output_semantics("canon_extraction", value)

    assert raised.value.code == "CHAPTER_PROVIDER_OUTPUT_SEMANTIC_INVALID"


def test_revision_schema_tells_provider_text_is_reader_facing_prose_only() -> None:
    text_schema = chapter_provider_output_schema("revision")["properties"]["text"]

    assert "reader-facing" in text_schema["description"]
    assert "metadata" in text_schema["description"]


def test_unsupported_stage_fails_closed() -> None:
    with pytest.raises(KernelError) as raised:
        chapter_provider_output_schema("unknown")

    assert raised.value.code == "CHAPTER_PROVIDER_OUTPUT_SCHEMA_UNSUPPORTED"


def test_provider_schema_has_no_open_object_escape_hatch() -> None:
    def assert_closed(schema: object) -> None:
        if isinstance(schema, dict):
            if schema.get("type") == "object":
                assert schema.get("additionalProperties") is False
                assert set(schema.get("required") or ()).issubset(
                    (schema.get("properties") or {}).keys()
                )
            for child in schema.values():
                assert_closed(child)
        elif isinstance(schema, list):
            for child in schema:
                assert_closed(child)

    for stage in ("canon_extraction", "quality_structural", "reader_outcome"):
        assert_closed(chapter_provider_output_schema(stage))
