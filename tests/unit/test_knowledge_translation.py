from copy import deepcopy

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.knowledge_translation import (
    add_translation_contract,
    validate_knowledge_translations,
)


def test_planning_profile_cannot_silently_disagree_with_book_knowledge_authority():
    from novel_forge.modules.story_planning_runtime.execution import _planning_knowledge_access
    deny = {"knowledge_access_policy": {"policy_id": "control", "policy_version": 1, "mode": "DENY_ALL", "allowed_knowledge_card_asset_version_ids": []}}
    with pytest.raises(KernelError, match="PLANNING_BOOK_KNOWLEDGE_POLICY_MISMATCH"):
        _planning_knowledge_access(production_profile={}, selected=[{"role": "production_profile", "content": deny}], project_id="p", book_id="b")
    matched = _planning_knowledge_access(production_profile=deny, selected=[{"role": "production_profile", "content": deny}], project_id="p", book_id="b")
    assert matched["mode"] == "DENY_ALL"


def _case():
    selection = {
        "policy_version": "knowledge-grounded-selection-v2",
        "selected": [
            {
                "knowledge_card_asset_version_id": "card:v3",
                "content_hash": "sha256:" + "c" * 64,
                "applicability_assessment": {"status": "CONDITIONAL"},
            }
        ],
    }
    candidate = {
        "objective": "Spend two water units to cool the engine before the escape.",
        "knowledge_translations": [
            {
                "knowledge_card_asset_version_id": "card:v3",
                "content_hash": "sha256:" + "c" * 64,
                "decision": "ADAPT",
                "usage_role": "MECHANISM",
                "rationale": "Cooling consumes the scarce reserve and changes the escape choice.",
                "prerequisite_resolution": "Establish the two-unit reserve in the opening action; verify water quality before cooling.",
                "use_sites": [
                    {
                        "target_pointer": "/objective",
                        "realization_excerpt": "Spend two water units",
                        "expected_application": "Cooling has a measurable cost.",
                        "preservation_requirements": [
                            "Do not restore spent water without a new source."
                        ],
                        "verification_checks": [
                            "Cooling follows verified reserve and quality."
                        ],
                    }
                ],
            }
        ],
    }
    return selection, candidate


def test_translation_requires_exact_selected_version_located_change_and_checks():
    selection, candidate = _case()
    assert (
        validate_knowledge_translations(candidate, selection)
        == candidate["knowledge_translations"]
    )
    for mutation, code in (
        (
            lambda item: item.update(knowledge_card_asset_version_id="card:v2"),
            "TRANSLATION_DRIFT",
        ),
        (lambda item: item.update(decision="ADOPT"), "PREREQUISITES_UNRESOLVED"),
        (
            lambda item: item["use_sites"][0].update(target_pointer="/missing"),
            "TRANSLATION_UNLOCATED",
        ),
        (
            lambda item: item["use_sites"][0].update(
                realization_excerpt="Invented result not in the candidate"
            ),
            "TRANSLATION_UNLOCATED",
        ),
        (
            lambda item: item["use_sites"][0].update(verification_checks=[]),
            "TRANSLATION_INVALID",
        ),
    ):
        changed = deepcopy(candidate)
        mutation(changed["knowledge_translations"][0])
        with pytest.raises(KernelError, match=code):
            validate_knowledge_translations(changed, selection)


def test_explicit_rejection_is_valid_and_omission_is_not():
    selection, candidate = _case()
    candidate["knowledge_translations"][0].update(decision="REJECT", use_sites=[])
    assert validate_knowledge_translations(candidate, selection)
    with pytest.raises(KernelError, match="TRANSLATION_MISSING"):
        validate_knowledge_translations(
            {"objective": candidate["objective"]}, selection
        )


def test_constraint_cannot_be_relabelled_as_inspiration_to_bypass_prerequisites():
    selection, candidate = _case()
    selection["selected"][0]["applicability_assessment"]["usage_role"] = "CONSTRAINT"
    candidate["knowledge_translations"][0].update(
        decision="ADOPT", usage_role="INSPIRATION"
    )
    with pytest.raises(KernelError, match="ROLE_DOWNGRADE"):
        validate_knowledge_translations(candidate, selection)


def test_formation_uses_same_contract_and_inherited_chapter_scope_is_local():
    from novel_forge.modules.story_planning_runtime.foundation_generation import (
        FOUNDATION_GENERATORS,
        foundation_output_schema,
    )
    from novel_forge.modules.story_planning_runtime.execution import (
        _inherited_knowledge_versions,
    )

    selection, candidate = _case()
    for generator in FOUNDATION_GENERATORS:
        assert (
            "knowledge_translations"
            in add_translation_contract(foundation_output_schema(generator), selection)[
                "required"
            ]
        )
    translation = candidate["knowledge_translations"][0]
    content = {
        "chapter_function_matrix": [
            {"chapter_number": 4, "objective": "Cooling spends the reserve."}
        ],
        "knowledge_translations": [
            {
                **translation,
                "use_sites": [
                    {
                        **translation["use_sites"][0],
                        "target_pointer": "/chapter_function_matrix/0/objective",
                    }
                ],
            }
        ],
    }
    assert _inherited_knowledge_versions([{"content": content}], chapter=4) == (
        "card:v3",
    )
    assert _inherited_knowledge_versions([{"content": content}], chapter=3) == ()


def test_foundation_qualification_accepts_structured_located_translation():
    from novel_forge.modules.story_planning_runtime.foundation_generation import (
        validate_foundation_payload,
    )

    _, payload = _case()
    payload.update(
        constraints=[],
        prohibited_outcomes=[],
        thematic_question="Does rescue justify spending the reserve?",
        opposing_answers=["Save now", "Preserve the reserve"],
        choice_tests=[
            {
                "choice": "Spend water",
                "cost": "Reserve exhausted",
                "thematic_pressure": "Duty to later travelers",
            }
        ],
    )
    payload.update(
        constraint_envelope={"foundation_parent_bindings": {}},
        foundation_parent_bindings={},
    )
    validate_foundation_payload(
        "theme.candidates.generate", {"candidate_payload": payload}
    )
    payload["knowledge_translations"][0]["decision"] = "SILENTLY_APPLIED"
    with pytest.raises(KernelError):
        validate_foundation_payload(
            "theme.candidates.generate", {"candidate_payload": payload}
        )


def test_provider_contract_requires_every_card_but_preserves_frozen_legacy_contract():
    selection, _ = _case()
    schema = {
        "type": "object",
        "properties": {"objective": {"type": "string"}},
        "required": ["objective"],
        "additionalProperties": False,
    }
    output = add_translation_contract(schema, selection)
    assert output["properties"]["knowledge_translations"]["minItems"] == 1
    assert "knowledge_translations" in output["required"]
    assert "knowledge_translations" not in schema["properties"]
    assert (
        add_translation_contract(
            schema,
            {**selection, "policy_version": "structured-narrative-intelligence-v1"},
        )
        == schema
    )


def test_changed_adoption_is_a_plan_change_and_rejection_does_not_create_repetition_debt():
    from novel_forge.modules.plan_change_authority.domain import (
        semantic_plan_diff,
        classify_plan_change_risk,
    )
    from novel_forge.modules.story_planning_runtime.execution import (
        _recent_activated_repetition_keys,
    )

    _, candidate = _case()
    changes = semantic_plan_diff({}, candidate)
    assert any(item.change_type == "KNOWLEDGE_TRANSLATION_CHANGED" for item in changes)
    assert (
        classify_plan_change_risk(changes, target_execution_scope="PLANNED").value
        == "MEDIUM"
    )
    base = {"plan_binding_id": "binding:v1", "plan_freshness": "CURRENT"}
    assert _recent_activated_repetition_keys(
        (
            {
                **base,
                "repetition_key": "rejected",
                "usage_states": {"claimed_adoption": False},
            },
            {
                **base,
                "repetition_key": "adopted",
                "usage_states": {"claimed_adoption": True},
            },
        )
    ) == ("adopted",)
