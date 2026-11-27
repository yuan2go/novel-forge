from types import SimpleNamespace
from unittest.mock import patch

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.worker_execution import WorkerFailureClass, WorkerFailureClassifier
from novel_forge.modules.story_planning_runtime.world_preparation import PlanningWorldPreparation
from novel_forge.modules.story_planning_runtime.world_result_recovery import WORLD_GENERATION_CONTRACT_ERRORS


def test_agency_rejection_is_terminal_contract_failure_and_repairable():
    code = 'WORLD_AGENCY_CLASSIFICATION_REJECTED'
    assert WorkerFailureClassifier.classify(KernelError(code, 'unsupported action')) == WorkerFailureClass.FINAL_FAILURE
    assert code in WORLD_GENERATION_CONTRACT_ERRORS
    assert WorkerFailureClassifier.classify(KernelError('TEMPORARY_PROVIDER_FAILURE', 'temporary')) == WorkerFailureClass.RETRYABLE


def test_world_recovery_decodes_the_frozen_agency_contract_without_changing_result():
    from copy import deepcopy
    from dataclasses import asdict
    import json
    from novel_forge.modules.story_planning_runtime.world_result_recovery import validate_world_generation_result
    from novel_forge.modules.worldbuilding.production_planning import WorldProductionPolicy
    from tests.unit.test_world_initial_agency import genesis, chain
    from tests.unit.test_world_causal_preparation import generated_paths

    raw = generated_paths()
    candidate = raw['candidates'][0]
    candidate.update(transition={'payload_json': json.dumps(chain()[0])},
        affected_entities=['resource:record'], preparation_paths=[])
    source = {'reality': genesis(), 'entity_ids': genesis()['approved_entity_ids'],
        'policy': asdict(WorldProductionPolicy())}
    command = SimpleNamespace(input_versions={}, related_arc_plan_version_ids=())
    original = deepcopy(raw)
    result = validate_world_generation_result(raw, source, command)
    assert result[0]['transition']['action_mode'] == 'ROUTINE'
    assert raw == original
    legacy = deepcopy(source)
    legacy['reality'].pop('epistemic_contract')
    with pytest.raises(KernelError, match='WORLD_PROVIDER_TRANSITION_INVALID'):
        validate_world_generation_result(raw, legacy, command)


@pytest.mark.parametrize('accounting', ['SETTLED', 'RESERVED', 'HELD_UNKNOWN'])
def test_missing_action_still_revalidates_exact_director_receipt(accounting):
    source = SimpleNamespace(asset_version_id='source', content_hash='source-hash', content={'contract': {
        'reality': {}, 'request': {'accepted_through_chapter': 0}, 'policy': {},
        'intent_version_id': 'intent', 'contract_version': 'world-preparation-source.v1'}})
    generation = SimpleNamespace(asset_version_id='generation', content_hash='generation-hash')
    raw = {'action_classifications': [{'supported': False}]}
    evaluation = SimpleNamespace(asset_version_id='evaluation', content_hash='evaluation-hash', content={'contract': {
        'source': {'asset_version_id': 'source', 'content_hash': 'source-hash'},
        'generation': {'asset_version_id': 'generation', 'content_hash': 'generation-hash'},
        'output': raw, 'evidence': {'external_receipt_ref': 'director-effect'}}})
    def require(**kwargs):
        if kwargs['logical_ref'].endswith('/action'):
            raise KernelError('AUTHORITY_ASSET_NOT_FOUND', 'no action was committed')
        return evaluation
    query = SimpleNamespace(database_url='db', require=require)
    command = SimpleNamespace(project_id='project', actor_id='actor', trace_id='trace', correlation_id='correlation')
    receipt = {'provider_evidence': {'result': raw}, 'budget_reservation_status': accounting}
    with patch.object(PlanningWorldPreparation, '_source_operation', return_value='operation'), patch(
        'novel_forge.modules.command_kernel.external_effect_runtime.read_retained_generation_stage_success', return_value=receipt
    ), patch('novel_forge.modules.story_planning_runtime.world_preparation.compile_world_plan', side_effect=KernelError(
        'WORLD_AGENCY_CLASSIFICATION_REJECTED', 'exact retained Director refusal'
    )) as compile_plan:
        with pytest.raises(KernelError) as error:
            PlanningWorldPreparation._validate_retained_plan(query, command=command, generation=generation, source=source, decoded={})
        assert error.value.code == 'WORLD_AGENCY_CLASSIFICATION_REJECTED'
        assert compile_plan.call_count == 1
        assert receipt['budget_reservation_status'] == accounting
