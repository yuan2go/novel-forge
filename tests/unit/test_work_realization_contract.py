from copy import deepcopy

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.hierarchical_planning.domain import (
    validate_chapter_function_matrix,
)
from novel_forge.modules.hierarchical_planning.realization_domain import (
    NarrativeRealizationContract,
)
from novel_forge.modules.story_planning_runtime.execution import (
    _frozen_provider_value_schema,
)
from novel_forge.storage.narrative_realization_repositories import (
    _realization_event_deviations,
)
from tests.unit.test_narrative_realization import _contract


def observation_contract():
    values = _contract().to_dict()
    values["schema_version"] = "narrative-realization-contract.v2"
    proof = values["proof"]
    proof["schema_version"] = "narrative-realization-proof.v2"
    proof["causal_alignment_proven"] = proof.pop("causal_escalation_proven")
    proof["design_admission"] = {
        "mode": "AUTHOR_SUPERVISED_DESIGN",
        "literary_qualification": "NOT_PROVEN",
        "decision_asset_version_id": "author-decision:v1",
        "decision_content_hash": proof["semantic_evaluation_hash"],
    }
    for event in values["events"]:
        event.update(
            decision=None,
            resistance=None,
            irreversible_change=None,
            state_deltas=[],
            disclosures=[],
            obligation_actions=[],
            arc_contributions=[],
            preconditions=[],
            causes=[],
            next_event_ids=[],
        )
        event["knowledge_boundary"] = {
            "actor_knows": [],
            "reader_may_learn": [],
            "forbidden_disclosures": [],
        }
        event["feature_status"] = {
            name: {
                "status": "NOT_APPLICABLE",
                "rationale": "Approved observational scope",
            }
            for name in ("decision", "resistance", "irreversible_change")
        }
    return values


def observed_event(event):
    return {
        "planned_event_id": event["event_id"],
        "observation_status": "OBSERVED",
        "observed_event_id": "observed:" + event["event_id"],
        "accepted_prose_evidence": {"quote": "雪落在街道上。"},
        "observed_action": event["action"],
        "observed_decision": None,
        "observed_consequence": event["consequence"],
        "observed_cause_event_ids": [],
        "observed_state_deltas": [],
        "observed_state_event_ids": [],
        "observed_disclosures": [],
    }


def test_observation_still_requires_every_chapter_and_exact_execution():
    values = observation_contract()
    contract = NarrativeRealizationContract.from_mapping(values)
    assert (
        contract.to_dict()["proof"]["design_admission"]["mode"]
        == "AUTHOR_SUPERVISED_DESIGN"
    )
    assert all(not event.state_deltas for event in contract.events)
    for event in contract.to_dict()["events"]:
        observed = observed_event(event)
        assert _realization_event_deviations(event, observed) == ()
        del observed["observed_state_deltas"]
        assert "MISSING_REQUIRED_EVENT" in _realization_event_deviations(
            event, observed
        )
    values["events"].pop()
    with pytest.raises(KernelError):
        NarrativeRealizationContract.from_mapping(values)


def test_selected_change_and_old_contract_remain_strict():
    values = observation_contract()
    event = values["events"][0]
    event["decision"] = "公开决定"
    with pytest.raises(KernelError, match="REALIZATION_FEATURE_STATUS_INVALID"):
        NarrativeRealizationContract.from_mapping(values)
    event["feature_status"]["decision"]["status"] = "APPLICABLE"
    NarrativeRealizationContract.from_mapping(values)
    observed = observed_event(event)
    assert "CAUSALITY_DRIFT" in _realization_event_deviations(event, observed)
    legacy = observation_contract()
    legacy["schema_version"] = "narrative-realization-contract.v1"
    with pytest.raises(KernelError):
        NarrativeRealizationContract.from_mapping(legacy)


def test_confirmed_zero_is_distinct_from_unknown_or_missing_scheduling():
    rows = [
        dict(
            chapter_number=i,
            primary_function="observation",
            secondary_functions=[],
            required_state_delta={"status": "NO_INCREMENT", "summary": None},
            required_arc_contributions=[],
            promise_action=None,
            foreshadow_action=None,
            reward_action=None,
            ending_hook=None,
            prohibited_outcomes=[],
        )
        for i in (1, 2, 3)
    ]
    assert (
        validate_chapter_function_matrix(
            rows, group_objective="观察城市", work_requirements=True
        )["status"]
        == "PASSED"
    )
    with pytest.raises(KernelError, match="CHAPTER_FUNCTION_MATRIX_BLOCKED"):
        validate_chapter_function_matrix(rows, group_objective="观察城市")
    for status in ("UNDETERMINED", None):
        broken = deepcopy(rows)
        broken[0]["required_state_delta"] = {"status": status, "summary": None}
        with pytest.raises(KernelError, match="CHAPTER_FUNCTION_MATRIX_BLOCKED"):
            validate_chapter_function_matrix(
                broken, group_objective="观察城市", work_requirements=True
            )


def test_nullable_projection_is_versioned_and_preserves_frozen_vocabulary():
    with pytest.raises(ValueError):
        _frozen_provider_value_schema([None, "selected decision"])
    schema = _frozen_provider_value_schema(
        [None, "selected decision"], work_requirements=True
    )
    assert schema == {"type": ["string", "null"], "enum": [None, "selected decision"]}


def test_zero_increment_outcome_replays_without_fabricated_canon_and_keeps_scope():
    from novel_forge.modules.chapter_outcome.domain import build_chapter_outcome, reduce_story_state
    from novel_forge.modules.narrative_state.reducers import rebuild_story_state
    from novel_forge.modules.canon_graph.domain import extract_canon_candidates
    from novel_forge.modules.chapter_authority.domain_handlers import build_canon_patch
    extraction = extract_canon_candidates(project_id="project", revision={"chapter": 1, "text": "雪落在街道上。"},
        revision_asset_version_id="draft:1", context_bundle_version_id="context:1", work_requirements=True)
    assert extraction["canon_assertion_candidates"] == []
    assert extraction["revision_text_hash"].startswith("sha256:")
    legacy = extract_canon_candidates(project_id="project", revision={"chapter": 1, "text": "雪落在街道上。"},
        revision_asset_version_id="draft:1", context_bundle_version_id="context:1")
    assert legacy["canon_assertion_candidates"][0]["predicate"] == "accepted_revision_digest"
    outcomes = []
    state = None
    for number in (1, 2):
        outcome = build_chapter_outcome(project_id="project", book_id="book", chapter_number=number,
            chapter_plan_version_id=f"plan:{number}", parent_group_version_id="group:1", accepted_draft_version_id=f"draft:{number}",
            final_release_gate_version_id=f"release:{number}", quality_aggregate_version_id=f"quality:{number}",
            canon_patch_asset_version_id=f"canon:{number}", canon_patch={"gate": "PASSED", "conflicts": [], "state_changes": {}},
            cost_receipt_refs=(), created_by_operation_id=f"operation:{number}", trace_id="trace", work_requirements=True)
        assert outcome["state_events"] == []
        outcomes.append((f"outcome:{number}", outcome))
        state = reduce_story_state(previous=state, chapter_outcome=outcome, chapter_outcome_asset_version_id=f"outcome:{number}")
        assert state["accepted_through_chapter"] == number
        assert state["reducer_applications"] == []
        assert reduce_story_state(previous=state, chapter_outcome=outcome, chapter_outcome_asset_version_id=f"outcome:{number}") == state
    rebuilt = rebuild_story_state(outcomes)
    assert rebuilt["current_state"] == state["current_state"]
    assert rebuilt["accepted_through_chapter"] == 2
    altered = deepcopy(outcomes[-1][1])
    altered["book_id"] = "other-book"
    with pytest.raises(KernelError):
        reduce_story_state(previous=state, chapter_outcome=altered, chapter_outcome_asset_version_id="outcome:3")
    altered = deepcopy(outcomes[-1][1])
    altered["contract_version"] = "chapter-outcome-v3"
    with pytest.raises(KernelError, match="NARRATIVE_EVENT_SET_REQUIRED"):
        reduce_story_state(previous=state, chapter_outcome=altered, chapter_outcome_asset_version_id="outcome:3")
    # INVARIANT: Empty history is legal only with the exact accepted state/Canon frontier.
    extraction["chapter"] = 2
    with pytest.raises(KernelError, match="CANON_HISTORY_BASELINE_REQUIRED"):
        build_canon_patch(project_id="project", revision={"chapter": 2, "text": "雪落在街道上。"},
            revision_asset_version_id="draft:2", context_bundle_version_id="context:2", extraction=extraction, context_bundle={})


def test_native_realization_compiler_preserves_author_supervision_without_strict_requalification(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from novel_forge.modules.hierarchical_planning import realization_application as application
    from novel_forge.modules.story_design_authority import author_supervision
    values = observation_contract()
    group = {"chapter_range": values["chapter_range"], "narrative_event_chain": values["events"],
             "constraint_envelope": {"creative_requirements_contract": "work-requirements.v1"}}
    cursor = MagicMock()
    boundary = values["accepted_boundary"]
    cursor.fetchone.return_value = (values["project_id"], values["book_id"], 0,
        boundary["story_state_version_id"], boundary["canon_version_id"], boundary["story_state_content_hash"],
        boundary["canon_content_hash"], group, values["chapter_group_content_hash"], "FROZEN", "CURRENT", values["foundation_set_digest"])
    cursor.fetchall.return_value = []
    monkeypatch.setattr(application, "require_current_foundation_set", lambda *args, **kwargs: SimpleNamespace(set_digest=values["foundation_set_digest"]))
    receipt = {"mode": "AUTHOR_SUPERVISED_DESIGN", "literary_qualification": "NOT_PROVEN",
               "content_hash": values["chapter_group_content_hash"], "lifecycle": "ACTIVE",
               "decision_asset_version_id": "approved:1", "decision_content_hash": values["proof"]["semantic_evaluation_hash"]}
    monkeypatch.setattr(author_supervision, "approved_design_receipt", lambda *args, **kwargs: dict(receipt))
    def compile_contract():
        return application.PostgresNarrativeRealizationApplication._contract_for_group(cursor, book_run_id="book-run",
            chapter_group_plan_version_id=values["chapter_group_plan_version_id"],
            arc_working_set={"working_set_digest": values["arc_working_set_digest"], "selected_contributions": []})
    contract = compile_contract().to_dict()
    assert contract["proof"]["design_admission"]["mode"] == "AUTHOR_SUPERVISED_DESIGN"
    assert contract["proof"]["design_admission"]["literary_qualification"] == "NOT_PROVEN"
    assert contract["proof_asset_version_id"] == "approved:1"
    assert not any("authority_current_narrative_design_qualification" in call.args[0] for call in cursor.execute.call_args_list)
    receipt["content_hash"] = "sha256:" + "0" * 64
    with pytest.raises(KernelError, match="REALIZATION_AUTHOR_APPROVAL_STALE"):
        compile_contract()
    monkeypatch.setattr(author_supervision, "approved_design_receipt", lambda *args, **kwargs: None)
    with pytest.raises(KernelError, match="REALIZATION_PROOF_INCOMPLETE"):
        compile_contract()


def test_intrinsic_scene_core_is_versioned_without_mutating_selected_specialisms():
    from copy import deepcopy
    from novel_forge.modules.chapter_authority.realization_composition import compile_realization_contract
    from novel_forge.modules.command_kernel.errors import KernelError
    import pytest
    plan = {"scene_plan": [{"scene_id": "scene", "beats": [{"beat_id": "beat"}],
                           "realization_capabilities": ["ACTION"]}]}
    before = deepcopy(plan)
    with pytest.raises(KernelError, match="narrative skeleton"):
        compile_realization_contract(plan, {})
    result = compile_realization_contract(plan, {}, core_policy="scene-core-slots.v1")
    assert [s["capability"] for s in result["slots"]] == ["SKELETON", "ACTION"]
    assert result["core_projection"]["source_capabilities"] == {"scene": ["ACTION"]}
    assert plan == before
    plan["scene_plan"][0]["realization_capabilities"] = ["ACTION", "ACTION"]
    with pytest.raises(KernelError):
        compile_realization_contract(plan, {}, core_policy="scene-core-slots.v1")


def test_scene_information_flow_keeps_future_actor_and_withheld_scopes():
    from novel_forge.modules.chapter_authority.realization_composition import compile_realization_contract
    plan = {'chapter':1,'scene_plan':[
        {'scene_id':'first','beats':[{'beat_id':'first:beat'}],'realization_capabilities':['SKELETON','INTERIOR'],
         'pov_character_id':'actor','participants':['actor'],'accessible_knowledge':[],'information_gain':['observed','withheld']},
        {'scene_id':'later','beats':[{'beat_id':'later:beat'}],'realization_capabilities':['SKELETON'],
         'pov_character_id':'actor','participants':['actor'],'accessible_knowledge':['observed'],'information_gain':['future']}],
        'character_participation':[{'character_id':'actor','known_fact_ids':[]}],
        'knowledge_boundaries':[{'layer':'CHARACTER_KNOWLEDGE','subject_id':'actor','fact_id':'observed','status':'KNOWN','available_from_chapter':1}],
        'disclosures':[{'audience':'ALL','mode':'WITHHOLD','fact_id':'withheld','earliest_chapter':1}]}
    old = compile_realization_contract(plan,{})
    assert all(not s['accessible_knowledge'] for s in old['slots'][:2])
    current = compile_realization_contract(plan,{},information_policy='scene-information-flow.v1')
    assert current['slots'][0]['accessible_knowledge'] == ['observed']
    assert current['slots'][1]['accessible_knowledge'] == ['observed']
    assert 'future' not in current['slots'][0]['accessible_knowledge']
    assert current['information_flow']['authority'] == 'EXECUTION_PROJECTION_ONLY'
    plan['knowledge_boundaries'][0]['available_from_chapter'] = 2
    current = compile_realization_contract(plan,{},information_policy='scene-information-flow.v1')
    assert current['slots'][1]['accessible_knowledge'] == []


@pytest.mark.parametrize('declared_unit', [{}, {'unit': 'HAN_CHARACTERS_V1'}])
def test_measured_frozen_length_scope_does_not_promote_local_advice(declared_unit):
    import pytest
    from novel_forge.modules.revision.domain import freeze_chapter_length_scope, validate_chapter_length_scope
    from novel_forge.modules.review.diagnostics import validate_prose_repair_scope
    from novel_forge.modules.command_kernel.errors import KernelError
    artifacts = [{'text':'First choice 甲.'}, {'text':'Second choice preserved.'}]
    source = {'text':'\n\n'.join(a['text'] for a in artifacts), 'scene_artifacts':artifacts}
    profile = {'asset_type':'platform_profile','asset_version_id':'platform:v1','content_digest':'sha256:'+'a'*64,
        'structured_facts':[{'key':'platform_rules','value':{'chapter_length':{**declared_unit,'minimum':3,'maximum':4}}}]}
    context = {'context_segments':[profile]}
    scope = freeze_chapter_length_scope(source,source_asset_version_id='draft:v1',context=context,context_asset_version_id='context:v1')
    assert scope['source_han_characters'] == 1 and scope['platform_profile_asset_version_id'] == 'platform:v1'
    revised = source['text'].replace('甲','甲乙丙丁')
    diagnoses = [{'evidence_locator':{'quote':'Second choice preserved.'}}]
    with pytest.raises(KernelError,match='REVISION_OUTSIDE_DIAGNOSIS_SCOPE'):
        validate_prose_repair_scope(source,diagnoses,revised)
    validate_prose_repair_scope(source,diagnoses,revised,length_scope=scope)
    with pytest.raises(KernelError,match='CHAPTER_LENGTH_REPAIR_INCOMPLETE'):
        validate_prose_repair_scope(source,diagnoses,source['text'],length_scope=scope)
    with pytest.raises(KernelError,match='CHAPTER_LENGTH_SCOPE_INVALID'):
        validate_chapter_length_scope(scope,source,revised,source_asset_version_id='different:draft',context_asset_version_id='context:v1')
    already_in_bounds = {**source,'text':revised}
    assert freeze_chapter_length_scope(already_in_bounds,source_asset_version_id='draft:v2',context=context,context_asset_version_id='context:v1') is None
    with pytest.raises(KernelError,match='CHAPTER_LENGTH_SCOPE_INVALID'):
        validate_prose_repair_scope(already_in_bounds,diagnoses,revised+'戊',length_scope=scope)
    with pytest.raises(KernelError,match='CHAPTER_LENGTH_SCOPE_PROFILE_CONFLICT'):
        freeze_chapter_length_scope(source,source_asset_version_id='draft:v1',context={'context_segments':[profile,profile]},context_asset_version_id='context:v1')


def test_original_frozen_bounds_without_unit_require_han_length_repair():
    from novel_forge.modules.revision.domain import freeze_chapter_length_scope, validate_chapter_length_scope
    from novel_forge.modules.chapter_authority.quality_length_requirement import freeze_requirement, require_length
    from novel_forge.modules.chapter_quality_authority.context_views import chapter_length_unit
    from novel_forge.modules.chapter_quality_authority.creative_validation import measure_length
    source = {'text': '甲' * 3520 + '，abc。'}
    profile = {'asset_type': 'platform_profile', 'asset_version_id': 'platform:original:v1',
        'content_digest': 'sha256:' + 'b' * 64, 'structured_facts': [{'key': 'platform_rules',
        'value': {'format': {'paragraph_max': 500}, 'chapter_length': {'maximum': 5000, 'minimum': 4000}}}]}
    original = deepcopy(profile)
    scope = freeze_chapter_length_scope(source, source_asset_version_id='draft:original:v1',
        context={'context_segments': [profile]}, context_asset_version_id='context:original:v1')
    assert profile == original
    assert scope['unit'] == 'HAN_CHARACTERS_V1'
    assert (scope['minimum'], scope['maximum'], scope['source_han_characters']) == (4000, 5000, 3520)
    assert scope['platform_profile_asset_version_id'] == profile['asset_version_id']
    assert scope['platform_profile_content_hash'] == profile['content_digest']
    requirement = freeze_requirement({'context_segments': [profile]}, context_id='context:original:v1')
    assert (requirement['minimum'], requirement['maximum'], requirement['unit']) == (4000, 5000, scope['unit'])
    assert requirement['platform_profile_content_hash'] == profile['content_digest']
    with pytest.raises(KernelError, match='CHAPTER_LENGTH_REPAIR_INCOMPLETE'):
        require_length(requirement, source['text'])
    qualified = '甲' * 4000 + '，' * 1001
    require_length(requirement, qualified)
    assert measure_length(qualified, chapter_length_unit(profile['structured_facts'][0]['value']['chapter_length'])) == 4000
    with pytest.raises(KernelError, match='CHAPTER_LENGTH_REPAIR_INCOMPLETE'):
        validate_chapter_length_scope(scope, source, source['text'],
            source_asset_version_id='draft:original:v1', context_asset_version_id='context:original:v1')
    for conflicting_unit in ('CODEPOINTS', 'WHITESPACE_WORDS', None):
        profile['structured_facts'][0]['value']['chapter_length']['unit'] = conflicting_unit
        with pytest.raises(KernelError, match='CHAPTER_LENGTH_UNIT_UNSUPPORTED'):
            freeze_chapter_length_scope(source, source_asset_version_id='draft:original:v1',
                context={'context_segments': [profile]}, context_asset_version_id='context:original:v1')
        with pytest.raises(KernelError, match='CHAPTER_LENGTH_UNIT_UNSUPPORTED'):
            freeze_requirement({'context_segments': [profile]}, context_id='context:original:v1')


@pytest.mark.parametrize('version,target,valid', [('v3', 1, True), ('v3', 2, False), ('v4', 1, False), ('v4', 2, True), ('v4', 3, True), ('v4', 4, False)])
def test_group_correction_versions_preserve_the_historical_start_boundary(version, target, valid):
    from novel_forge.modules.hierarchical_planning.realization_domain import realization_hash

    value = observation_contract()
    value['schema_version'] = 'narrative-realization-contract.' + version
    working = {'version': 'working-manuscript-context.v1', 'project_id': value['project_id'],
        'book_id': value['book_id'], 'book_run_id': 'original-run', 'target_chapter': target,
        'accepted_through_chapter': 0, 'sources': []}
    working['snapshot_hash'] = realization_hash(working)
    value['working_manuscript'] = working
    if valid:
        contract = NarrativeRealizationContract.from_mapping(value)
        assert contract.to_dict() == value
        changed = deepcopy(value)
        changed['working_manuscript']['target_chapter'] = 3 if target == 2 else 2
        with pytest.raises(KernelError, match='REALIZATION_WORKING_BOUNDARY_INVALID'):
            NarrativeRealizationContract.from_mapping(changed)
    else:
        with pytest.raises(KernelError, match='REALIZATION_WORKING_BOUNDARY_INVALID'):
            NarrativeRealizationContract.from_mapping(value)
