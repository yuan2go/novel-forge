import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from novel_forge.modules.chapter_authority import runtime
from novel_forge.modules.chapter_authority.contracts import ChapterHandlerRegistry, ChapterNode
from novel_forge.modules.chapter_authority.definitions import chapter_provider_sample_definitions
from novel_forge.modules.chapter_authority.execution_gateway import PostgresChapterExecutionContractBinder
from novel_forge.modules.chapter_authority.sampling import _existing_sample_definition
from novel_forge.modules.command_kernel.attempt_runtime import WorkerLeaseCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.routing_bootstrap import chapter_sample_definition_supported
from novel_forge.storage.authority_repositories import definition_hash


@pytest.mark.parametrize('name,version,kind,supported', [
    ('draft', '1.0.0', False, True), ('draft', '2.0.0', False, True),
    ('review', '1.0.0', False, True), ('review', '2.0.0', False, True),
    ('review', '1.1.0', True, True), ('review', '2.1.0', True, True),
    ('rereview', '1.1.0', True, True), ('rereview', '2.1.0', True, True),
    ('draft', '1.1.0', True, False), ('draft', '2.1.0', True, False),
    ('review', '2.0.0', True, False), ('review', '2.1.0', False, False),
    ('draft', '2.0.1', False, False), ('unpublished', '2.0.0', False, False),
])
def test_sample_contract_versions_and_target_kind_are_exact(name, version, kind, supported):
    assert chapter_sample_definition_supported('chapter.provider.sample.' + name, version, reference_samples=kind) is supported


@pytest.mark.parametrize('reference,version', [(False, '2.0.0'), (True, '2.1.0')])
def test_new_sample_definitions_have_a_distinct_version_and_explicit_source_contracts(reference, version):
    definitions = chapter_provider_sample_definitions(application_build_id='test-build', commit_sha='e' * 40, reference_samples=reference)
    assert {item['definition_version'] for item in definitions} == {version}
    assert all(item['policy']['source_definition_versions'] == ['3.4.1', '3.5.0'] for item in definitions)
    if reference:
        assert {item['name'] for item in definitions} == {'chapter.provider.sample.review', 'chapter.provider.sample.rereview'}


@pytest.mark.parametrize('version,node', [('1.0.0', ChapterNode.DRAFT), ('2.0.0', ChapterNode.DRAFT), ('1.1.0', ChapterNode.REVIEW), ('2.1.0', ChapterNode.REVIEW)])
def test_runtime_registration_keeps_the_persisted_sample_contract(monkeypatch, version, node):
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.cursor.fetchone.return_value = (version,)
    monkeypatch.setattr(runtime, 'AuthorityUnitOfWork', lambda _: uow)
    execute = MagicMock(return_value='original-output')
    monkeypatch.setattr(runtime, 'execute_authority_handler', execute)
    result = runtime.execute_chapter_handler('unused', command=WorkerLeaseCommand('attempt', 'project', 'worker', 7, 'trace', 'correlation'),
        node=node, registry=ChapterHandlerRegistry(model_effects_required=True), sampling=True)
    assert result == 'original-output'
    assert execute.call_args.kwargs['registration'].definition_version == version


@pytest.mark.parametrize('version,node', [('9.0.0', ChapterNode.DRAFT), ('2.1.0', ChapterNode.DRAFT), ('1.1.1', ChapterNode.REVIEW)])
def test_unknown_sample_cannot_recover_an_already_materialized_result(monkeypatch, version, node):
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.cursor.fetchone.return_value = (version,)
    monkeypatch.setattr(runtime, 'AuthorityUnitOfWork', lambda _: uow)
    execute = MagicMock(return_value='already-materialized-result')
    monkeypatch.setattr(runtime, 'execute_authority_handler', execute)
    with pytest.raises(KernelError, match='AUTHORITY_HANDLER_CONTRACT_STALE'):
        runtime.execute_chapter_handler('unused', command=WorkerLeaseCommand('attempt', 'project', 'worker', 7, 'trace', 'correlation'),
            node=node, registry=ChapterHandlerRegistry(model_effects_required=True), sampling=True)
    execute.assert_not_called()


@pytest.mark.parametrize('version,stage,suffix', [('1.0.0', 'draft', 'provider_sampling'), ('2.0.0', 'draft', 'provider_sampling'),
    ('1.0.0', 'review', 'reference_sampling'), ('2.0.0', 'review', 'reference_sampling'),
    ('1.1.0', 'review', 'reference_samples'), ('2.1.0', 'rereview', 'reference_samples')])
def test_frozen_sample_pack_resolution_retains_its_workflow_version(version, stage, suffix):
    binder = object.__new__(PostgresChapterExecutionContractBinder)
    binder.capability_pack_id = 'pack'
    binder.pack_environment = binder.pack_runtime_profile = 'validation'
    binder.pack_release_channel = 'VALIDATION'
    binder.pack_resolver = MagicMock()
    binder._resolve_pack_snapshot(project_id='project', workspace_id='workspace', book_id='book', operation_id='operation',
        attempt_id='attempt', execution_fencing_token=7, worker_id='worker', snapshot_creation_fencing_token=7,
        snapshot_creation_worker_id='worker', stage=stage, route=SimpleNamespace(release_sha='e' * 40),
        graph={'definition_name': 'chapter.provider.sample.' + stage, 'definition_version': version})
    request = binder.pack_resolver.freeze_attempt_snapshot.call_args.args[0]
    expected = 'chapter_provider_sampling' if stage == 'draft' else 'chapter_reference_sampling'
    assert request.workflow_definition_ref == expected + '@' + version
    assert request.operation_definition_ref == 'chapter.provider.sample.' + stage + '@' + version
    assert request.pack_id == 'pack.' + suffix


@pytest.mark.parametrize('change', [None, 'stored_hash', 'registered_hash', 'handler', 'unknown'])
def test_api_replay_reads_published_definition_without_rebuilding_it(change):
    fixture = json.loads((Path(__file__).parents[1] / 'fixtures/chapter_sampler_base_48af52.json').read_text())
    original = fixture['definitions'][0]
    assert definition_hash(original) == original['published_hash']
    definition = {**original, 'definition_hash': original['published_hash']}
    snapshot = {**definition}
    version = definition['definition_version']
    if change == 'stored_hash':
        snapshot['definition_hash'] = 'sha256:' + '0' * 64
    elif change == 'registered_hash':
        definition['definition_hash'] = 'sha256:' + '0' * 64
    elif change == 'handler':
        snapshot['handler_key'] = 'different.handler'
    elif change == 'unknown':
        version = '1.0.1'
    uow = MagicMock()
    uow.cursor.fetchone.return_value = (definition['name'], version, snapshot)
    uow.repositories.definitions.get.return_value = definition
    if change:
        with pytest.raises(KernelError, match='AUTHORITY_HANDLER_CONTRACT_STALE'):
            _existing_sample_definition(uow, project_id='project', idempotency_key='key', definition_name=definition['name'], reference_samples=False)
    else:
        assert _existing_sample_definition(uow, project_id='project', idempotency_key='key', definition_name=definition['name'], reference_samples=False) is definition
    uow.repositories.definitions.register.assert_not_called()


@pytest.mark.parametrize('reference,samples,workflow', [(False, False, 'chapter_provider_sampling@2.0.0'),
    (True, False, 'chapter_reference_sampling@2.0.0'), (True, True, 'chapter_reference_sampling@2.1.0')])
def test_new_derived_pack_has_an_immutable_exact_semver_identity(reference, samples, workflow):
    from novel_forge.modules.capability_packs.validation_deployment import chapter_provider_sampling_manifest

    source = json.loads((Path(__file__).parents[2] / 'config/capability_packs/chapter_generation_pack.json').read_text())
    frozen_source = json.loads(json.dumps(source))
    manifest = chapter_provider_sampling_manifest(source, application_build_id='test-build', commit_sha='e' * 40,
        reference=reference, reference_samples=samples)
    source_parts = source['identity']['version'].split('.')
    assert manifest['identity']['version'] == '.'.join([str(int(source_parts[0]) + 1), *source_parts[1:]])
    template = manifest['workflow_template']
    assert template['workflow_id'] + '@' + template['workflow_version'] == workflow
    assert source == frozen_source


def reference_preflight(monkeypatch, *, current_attempt, prior_snapshot, legacy_binding=True):
    from novel_forge.modules.chapter_authority import sampling, execution_gateway, review_window
    from novel_forge.modules.capability_pack_authority import runtime as pack_runtime
    from novel_forge.storage import authority_asset_store
    from novel_forge.modules.command_kernel.routing_bootstrap import authorization_hash

    historical = json.loads((Path(__file__).parents[1] / 'fixtures/chapter_sampler_base_48af52.json').read_text())
    definition = next(item for item in historical['definitions'] if item['definition_version'] == '1.1.0')
    definition = {**definition, 'definition_hash': definition['published_hash']}
    digest = authorization_hash({})
    source = SimpleNamespace(asset_version_id='source-context', content_hash=digest, content={}, asset_type='context_bundle', blobs=())
    payload = {'project_id': 'project', 'book_id': 'book', 'chapter': 1, 'generator_operation_name': 'review',
        'logical_key': 'source-operation', 'idempotency_key': 'sample-key',
        'input_versions': [{'asset_version_id': source.asset_version_id, 'content_hash': digest}],
        'chapter_sampling': {'generation_sample': {'asset_version_id': 'sample', 'content_hash': digest}}}
    base_contract = {'contract': {'stage': 'draft', 'context_selection': payload['input_versions']}}
    uow = MagicMock()
    uow.__enter__.return_value = uow
    def select(query, params):
        if 'definition_snapshot' in query:
            uow.cursor.fetchone.return_value = (definition['name'], '1.1.0', definition)
        elif 'operation.command_payload' in query and 'JOIN authority_attempt' in query and 'LEFT JOIN' not in query:
            uow.cursor.fetchone.return_value = (payload, current_attempt) if current_attempt else None
        elif 'operation.operation_id' in query:
            uow.cursor.fetchone.return_value = ('sample-operation', payload, current_attempt, '1.1.0')
    uow.cursor.execute.side_effect = select
    uow.cursor.fetchall.return_value = [(base_contract, authorization_hash(base_contract))]
    uow.repositories.definitions.get.return_value = definition
    def snapshot(version):
        return SimpleNamespace(pack_id='pack.reference_samples', pack_version='legacy-pack' if version == '1.1.0' else 'new-pack',
            workflow_definition_ref='chapter_reference_sampling@' + version, workflow_node_id='review',
            operation_definition_ref='chapter.provider.sample.review@' + version, tool_policy_payload_json='{}',
            tool_policy_ref='tools:' + version, tool_policy_hash='hash:' + version)
    original = snapshot('1.1.0')
    uow.repositories.capability_packs.find_attempt_snapshot.return_value = None
    uow.repositories.capability_packs.find_latest_operation_attempt_snapshot.return_value = {
        'operation_id': 'sample-operation', 'snapshot': original,
    } if prior_snapshot else None
    binder = SimpleNamespace(pack_resolver=MagicMock(), pack_environment='validation', pack_runtime_profile='validation',
        pack_release_channel='VALIDATION', capability_pack_id='pack', routes={'review': SimpleNamespace(release_sha='e' * 40)})
    def resolve(_uow, request):
        if request.operation_definition_ref.endswith('@1.1.0') and not legacy_binding:
            raise KernelError('CAPABILITY_PACK_ASSIGNMENT_NOT_FOUND', 'no original legacy binding')
        return snapshot(request.operation_definition_ref.rpartition('@')[2])
    binder.pack_resolver.resolve_in_uow.side_effect = resolve
    monkeypatch.setattr(sampling, 'AuthorityUnitOfWork', lambda _: uow)
    monkeypatch.setattr(authority_asset_store, 'AuthorityAssetQuery', lambda _: SimpleNamespace(require=lambda **_: source))
    monkeypatch.setattr(review_window, 'prepare_native_review', lambda *args, **kwargs: (None, source, None, None, {}))
    monkeypatch.setattr(PostgresChapterExecutionContractBinder, '_provider_output_contract', lambda **kwargs: ({}, 'output:v1'))
    monkeypatch.setattr(pack_runtime, 'materialize_registered_pack_version', lambda selected, _: SimpleNamespace(to_dict=lambda **_: {'version': selected.pack_version}))
    monkeypatch.setattr(execution_gateway, '_stage_tool_permissions', lambda *args: (('model.provider.invoke',), ()))
    monkeypatch.setattr(execution_gateway, '_materialize_production_codex_prompt', lambda **kwargs: ('prompt', kwargs['materialization']))
    monkeypatch.setattr(execution_gateway, 'chapter_producer_contract_identity', lambda evidence, _: evidence['pack_artifacts'])
    app = SimpleNamespace(database_url='unused', _model_port=SimpleNamespace(capability_binder=binder))
    return lambda: sampling.reference_sample_producer_identity(app, payload=payload, workspace_id='workspace'), binder, uow, original


@pytest.mark.parametrize('current_attempt,prior_snapshot', [(None, False), ('new-attempt', True)])
def test_legacy_reference_preflight_retains_its_definition_and_original_pack(monkeypatch, current_attempt, prior_snapshot):
    invoke, binder, uow, _ = reference_preflight(monkeypatch, current_attempt=current_attempt, prior_snapshot=prior_snapshot)
    assert invoke() == {'version': 'legacy-pack'}
    if prior_snapshot:
        binder.pack_resolver.resolve_in_uow.assert_not_called()
        uow.repositories.capability_packs.find_latest_operation_attempt_snapshot.assert_called_once_with('sample-operation', excluding_attempt_id='new-attempt')
    else:
        resolution = binder.pack_resolver.resolve_in_uow.call_args.args[1]
        assert resolution.workflow_definition_ref == 'chapter_reference_sampling@1.1.0'
        assert resolution.operation_definition_ref == 'chapter.provider.sample.review@1.1.0'


def test_legacy_reference_without_any_frozen_pack_cannot_select_a_new_contract(monkeypatch):
    invoke, binder, _, _ = reference_preflight(monkeypatch, current_attempt=None, prior_snapshot=False, legacy_binding=False)
    with pytest.raises(KernelError, match='CAPABILITY_PACK_ASSIGNMENT_NOT_FOUND'):
        invoke()
    assert binder.pack_resolver.resolve_in_uow.call_args.args[1].workflow_definition_ref == 'chapter_reference_sampling@1.1.0'


@pytest.mark.parametrize('field,value', [('operation_definition_ref', 'chapter.provider.sample.review@2.1.0'),
    ('workflow_definition_ref', 'chapter_reference_sampling@2.1.0'), ('workflow_node_id', 'rereview')])
def test_prior_reference_snapshot_cannot_change_the_frozen_contract(monkeypatch, field, value):
    invoke, binder, _, snapshot = reference_preflight(monkeypatch, current_attempt='new-attempt', prior_snapshot=True)
    setattr(snapshot, field, value)
    with pytest.raises(KernelError, match='CHAPTER_SAMPLE_PRODUCER_DRIFT'):
        invoke()
    binder.pack_resolver.resolve_in_uow.assert_not_called()
