from copy import deepcopy

import pytest

from novel_forge.modules.chapter_authority.provider_views import (
    _project_denied_planning_selection, _projection_hash, compile_planning_provider_context,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority.domain import resolve_book_knowledge_access_policy
from tests.unit.test_foundation_hierarchy import _foundation_set


def _context():
    foundation = _foundation_set()
    literal = "The protagonist must choose between a paid voyage and surrendering control of a skill, while companions retain their own goals and ability to refuse."
    constraint = "Early victory must retain an actual reward."
    sources = [{"role": "book_design", "asset_type": "book_design", "asset_version_id": "design:v5", "content_hash": "sha256:" + "a" * 64,
                "content": {"schema_version": "book-design.v5", "foundation_set": foundation.to_dict(),
                            "narrative_dna": {"core_conflict": literal}, "book_invariants": [constraint, "Keep all travel times consistent."]}}]
    for binding in foundation.bindings:
        role = binding.role.value.lower()
        content = {"project_id": "project-1", "book_id": "book-1", "constraints": [constraint], "prohibited_outcomes": ["No mind reading."]}
        if role == "creative_foundation":
            content.update(core_conflict=literal, style_profile={"original_examples": ["Illustrative prose"], "style": "clear action"})
        elif role == "character_cast":
            content["characters"] = [{"name": "hero", "desire": "travel", "private_history": "unknown rival motive", "voice_anchors": ["illustrative dialogue"]}]
        elif role == "theme_contract":
            content["choice_tests"] = ["Illustrative local choice"]
        sources.append({"role": role, "asset_type": role, "asset_version_id": binding.asset_version_id, "content_hash": binding.content_hash, "content": content})
    return {"schema_version": "novelos.planning_context_bundle.v1", "project_id": "project-1", "book_id": "book-1", "logical_key": "book:main", "planning_scope": "BOOK", "input_versions": sources, "token_budget": 16000}


def test_qualified_projection_keeps_exact_constraints_and_uses_auditable_literal_references():
    context = _context()
    original = deepcopy(context)
    view, audit = compile_planning_provider_context("book_plan.generate", context)
    segments = {item["role"]: item["content"] for item in view["segments"]}
    assert segments["book_design"]["book_invariants"] == ["Keep all travel times consistent."]
    reference = segments["book_design"]["narrative_dna"]["core_conflict"]
    assert reference == {"literal_source_role": "creative_foundation", "json_pointer": "/core_conflict"}
    assert segments[reference["literal_source_role"]]["core_conflict"] == original["input_versions"][0]["content"]["narrative_dna"]["core_conflict"]
    for role in ("creative_foundation", "character_cast", "theme_contract"):
        assert segments[role]["constraints"] == ["Early victory must retain an actual reward."]
        assert segments[role]["prohibited_outcomes"] == ["No mind reading."]
    assert segments["character_cast"]["characters"][0]["private_history"] == "unknown rival motive"
    assert "voice_anchors" not in segments["character_cast"]["characters"][0]
    assert context == original
    assert view["selection_explanation"]["loss_receipt"]["audit_hash"] == _projection_hash(audit)


@pytest.mark.parametrize("field,value", [("asset_version_id", "foreign:v1"), ("content_hash", "sha256:" + "f" * 64), ("project_id", "foreign-project"), ("book_id", "foreign-book")])
def test_qualified_projection_rejects_source_identity_drift(field, value):
    context = _context()
    source = context["input_versions"][1]
    (source["content"] if field in {"project_id", "book_id"} else source)[field] = value
    with pytest.raises(KernelError, match="PLANNING_FOUNDATION_PROJECTION_DRIFT"):
        compile_planning_provider_context("book_plan.generate", context)


def test_volume_retains_theme_choices_while_book_defers_them():
    context = _context()
    context["planning_scope"] = "VOLUME"
    view, _ = compile_planning_provider_context("volume_plan.generate", context)
    theme = next(item["content"] for item in view["segments"] if item["role"] == "theme_contract")
    assert theme["choice_tests"] == ["Illustrative local choice"]


def _selection():
    policy = resolve_book_knowledge_access_policy(production_profile={"knowledge_access_policy": {"mode": "DENY_ALL"}}, project_id="project-1", book_id="book-1")
    need = {"query": "Duplicated search query that is not story evidence", "required_card_asset_version_ids": []}
    need["need_digest"] = _projection_hash(need)
    selection = {"project_id": "project-1", "knowledge_access_policy": policy, "need": need,
                 "selection_status": "NO_ELIGIBLE_MATCH", "selected": []}
    selection["selection_digest"] = _projection_hash(selection)
    return selection


def test_denied_empty_retrieval_preserves_policy_and_exact_need_receipt():
    source = _selection()
    original = deepcopy(source)
    result = _project_denied_planning_selection(source)
    assert "need" not in result
    assert result["need_receipt"]["need_digest"] == source["need"]["need_digest"]
    assert result["knowledge_access_policy"] == source["knowledge_access_policy"]
    assert result["selected"] == []
    assert source == original


@pytest.mark.parametrize("tamper", ["query", "selected", "status", "digest"])
def test_denied_retrieval_fails_closed_on_payload_or_lineage_drift(tamper):
    source = _selection()
    if tamper == "query":
        source["need"]["query"] = "tampered"
    elif tamper == "selected":
        source["selected"] = [{"raw_source": "must not be admitted"}]
    elif tamper == "status":
        source["selection_status"] = "SELECTED"
    else:
        source["selection_digest"] = "sha256:" + "f" * 64
    with pytest.raises(KernelError, match="PLANNING_EMPTY_SELECTION_DRIFT"):
        _project_denied_planning_selection(source)


def test_non_denied_retrieval_is_not_compacted():
    source = {"selected": [{"knowledge": "required evidence"}], "need": {"query": "keep"}}
    assert _project_denied_planning_selection(source) == source


def test_versioned_empty_project_query_retains_policy_and_source_identity():
    source = _selection()
    source['knowledge_access_policy'] = resolve_book_knowledge_access_policy(
        production_profile={}, project_id='project-1', book_id='book-1',
    )
    source['selection_digest'] = _projection_hash({k: v for k, v in source.items() if k != 'selection_digest'})
    original = deepcopy(source)
    assert _project_denied_planning_selection(source) == source
    result = _project_denied_planning_selection(source, empty_query=True)
    assert result['need_receipt']['selection_digest'] == source['selection_digest']
    assert result['need_receipt']['need_digest'] == source['need']['need_digest']
    assert result['knowledge_access_policy'] == source['knowledge_access_policy']
    assert result['need_receipt']['reason'] == 'NO_ELIGIBLE_EMPTY_RETRIEVAL_QUERY_IS_NOT_STORY_INPUT'
    assert 'need' not in result and source == original
    source['need']['query'] = 'unbound replacement'
    with pytest.raises(KernelError, match='PLANNING_EMPTY_SELECTION_DRIFT'):
        _project_denied_planning_selection(source, empty_query=True)


def test_empty_query_projection_never_omits_selected_card_inputs():
    source = _selection()
    source['selected'] = [{'knowledge': 'required creative input'}]
    source['knowledge_access_policy'] = resolve_book_knowledge_access_policy(
        production_profile={}, project_id='project-1', book_id='book-1',
    )
    assert _project_denied_planning_selection(source, empty_query=True) == source


def test_chapter_repair_schema_enforces_existing_operational_commitment_rule():
    from novel_forge.modules.hierarchical_planning import PlanContractType
    from novel_forge.modules.story_planning_runtime.execution import planning_provider_output_schema

    from tests.unit.test_story_planning_runtime import _realization_slice, _chapter_schedule_row
    arguments = {'logical_key': 'chapter:1', 'parent_version_id': 'group:v1', 'narrative_realization': _realization_slice(parent_version_id='group:v1'), 'chapter_schedule_row': _chapter_schedule_row()}
    historical = planning_provider_output_schema(PlanContractType.CHAPTER, **arguments)
    repair = planning_provider_output_schema(PlanContractType.CHAPTER, **arguments, operational_commitments=True)
    def levels(schema):
        return schema['properties']['commitment_contract']['items']['properties']['level']['enum']
    assert 'OPEN_DESIGN_SPACE' in levels(historical)
    assert levels(repair) == ['HARD_CONSTRAINT', 'SOFT_INTENT']
    with pytest.raises(KernelError, match='PLANNING_OPERATIONAL_SCOPE_INVALID'):
        planning_provider_output_schema(PlanContractType.BOOK, operational_commitments=True)
