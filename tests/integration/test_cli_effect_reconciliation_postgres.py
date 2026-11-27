import pytest
from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.budget_runtime import BudgetReservationRequest, reserve_provider_budget, settle_provider_budget, unresolved_cli_outcomes, provider_project_usage
from novel_forge.modules.command_kernel.external_effect_adapters import FakeDeterministicProvider, ProviderResult
from novel_forge.modules.command_kernel.external_effect_runtime import EffectCommandContext, plan_external_effect, prepare_effect_dispatch, acquire_effect_dispatch, submit_effect_dispatch_result, reconcile_external_effect, read_succeeded_external_effect, _hash
from novel_forge.modules.command_kernel.manual_effect_resolution import ExternalEffectManualResolutionCommand, resolve_external_effect_manually
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated, identifier, insert_definition, insert_operation, transaction


def seed(production=False, held=False, stage="world.design.generate", book_id=None):
    ensure_migrated()
    project, operation, definition = (identifier(x) for x in ("project", "operation", "definition"))
    with transaction() as c, c.cursor() as q:
        insert_definition(q, definition)
        insert_operation(q, operation_id=operation, definition_name=definition, project_id=project, status="EXECUTING")
    context = EffectCommandContext(operation, project, "operator", "trace", "correlation")
    adapter = FakeDeterministicProvider("success")
    effect = plan_external_effect(DATABASE_URL, context, effect_type="model.invoke", provider=adapter.provider,
        capability="model.test", stable_idempotency_key=identifier("key"), request_payload={"stage": stage, **({"_production_execution": {"attempt_id": "original-attempt", **({"book_id":book_id} if book_id else {})}} if production else {})},
        max_attempts=2, reversible=False, provider_capability_profile=adapter.capability_profile)["external_effect_id"]
    reservation = reserve_provider_budget(DATABASE_URL, BudgetReservationRequest(operation_id=operation, project_id=project,
        external_effect_id=effect, stable_idempotency_key=identifier("budget"), provider=adapter.provider,
        currency="UNKNOWN", estimated_amount=None, estimated_tokens=1000, accounting_basis="ACCOUNT_ENTITLEMENT",
        cost_authorization_ref="synthetic-authorization"))
    dispatch = prepare_effect_dispatch(DATABASE_URL, context, effect_id=effect)
    lease = acquire_effect_dispatch(DATABASE_URL, context, dispatch_id=dispatch["dispatch_id"], worker_id="fixture", lease_seconds=30)
    process = {"execution_id": "original-execution", "operation_id": operation, "attempt_id": "original-attempt", "fencing_token": 1,
        "input_sha256": "a" * 64, "status": "FAILED", "result_integrity": "MISSING", "process_started_at": "2026-10-08T02:40:17+08:00"}
    process_ref = asset(project, process, "execution_evidence", "process-receipt.v1")
    evidence = {"production_execution": {"execution_handle": {"transport": "LOCAL_CLI_REMOTE_INFERENCE"},
        "execution_result": {"outcome": "UNKNOWN" if held else "RETRYABLE_FAILURE", "started_at": process["process_started_at"], "execution_id": "original-execution",
            "attempt_id": "original-attempt", "fencing_token": 1, "process_receipt_ref": process_ref, "usage_receipt_ref": None},
        "process_evidence": {"failure_code": "PROCESS_EXIT_FAILURE"}}}
    if production:
        schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "properties": {"objective": {"type": "string"}}, "required": ["objective"], "additionalProperties": False}
        evidence["production_execution"].update(
            execution_request={"execution_id": "original-execution", "operation_id": operation, "attempt_id": "original-attempt", "fencing_token": 1, "capability": "model.test", "validation_policy_ref": "policy:original",
                **({"stage": stage, "project_id": project, "external_effect_id": effect} if stage.startswith("context_") else {})},
            route_snapshot={"route_snapshot_id": "original-route", "route_decision_id": "original-decision", "operation_id": operation, "attempt_id": "original-attempt", "model_id": "frozen-model"},
            input_manifest={"manifest_id": "original-input", "operation_id": operation, "attempt_id": "original-attempt", "fencing_token": 1, "project_id": project, "book_id": "synthetic-book", "input_artifacts": [{"artifact_ref": "frozen-input", "sha256": "a" * 64}]})
        evidence["production_execution"]["process_evidence"].update(output_schema=schema, output_schema_version="synthetic-output.v1", stage=stage)
    submit_effect_dispatch_result(DATABASE_URL, context, dispatch_id=dispatch["dispatch_id"], worker_id="fixture",
        fencing_token=lease["fencing_token"], outcome="unknown" if held else "retryable_failure", evidence=evidence)
    if held:
        from novel_forge.modules.command_kernel.budget_runtime import resolve_provider_budget_failure
        resolve_provider_budget_failure(DATABASE_URL, reservation_id=reservation["reservation_id"],
            project_id=project, external_state_unknown=True)
    else:
        settle_provider_budget(DATABASE_URL, reservation_id=reservation["reservation_id"], project_id=project,
            actual_amount=None, actual_tokens=1000, evidence={"measurement_available": False, "usage_settlement_basis": "RESERVATION_CEILING"})
    with transaction() as c:
        request_hash = c.execute("SELECT request_hash FROM authority_external_effect WHERE external_effect_id=%s", [effect]).fetchone()[0]
        version = c.execute("SELECT version FROM authority_operation WHERE operation_id=%s", [operation]).fetchone()[0]
    return context, effect, dispatch, request_hash, process_ref, version


def asset(project, payload, kind, schema, evidence_kind="process-receipt"):
    aid, vid = identifier("asset"), identifier("version")
    content = {"contract_version": "authority-execution-evidence.v1", "kind": evidence_kind, "execution_id": "original-execution", "payload": payload, "payload_hash": _hash(payload).removeprefix("sha256:")} if kind == "execution_evidence" else payload
    with transaction() as c:
        c.execute("INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES(%s,%s,%s)", [aid, project, kind])
        c.execute("INSERT INTO authority_asset_version(asset_version_id,asset_id,version_number,lifecycle,eligibility,governance,content,content_hash,schema_version) VALUES(%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,%s)", [vid, aid, Jsonb(content), _hash(content), schema])
    return "authority-asset-version:" + vid


class QueryOnly(FakeDeterministicProvider):
    def execute(self, **_):
        raise AssertionError("no Provider dispatch is allowed")

    def query(self, **_):
        return ProviderResult("ambiguous", "", {"external_state_unknown": True})


def test_historical_generation_enters_query_without_rewriting_dispatch():
    context, effect, dispatch, _, _, _ = seed()
    with transaction() as c:
        before = c.execute("SELECT to_jsonb(d) FROM authority_external_effect_dispatch d WHERE dispatch_id=%s", [dispatch["dispatch_id"]]).fetchone()[0]
    assert reconcile_external_effect(DATABASE_URL, context, effect_id=effect, adapter=QueryOnly("success"))["outcome"] == "ambiguous"
    with transaction() as c, c.cursor() as q:
        assert c.execute("SELECT to_jsonb(d) FROM authority_external_effect_dispatch d WHERE dispatch_id=%s", [dispatch["dispatch_id"]]).fetchone()[0] == before
        assert unresolved_cli_outcomes(q, context.project_id)


def confirmation(context, effect, dispatch, frozen_hash, process_ref, version, **changes):
    receipt = {"contract_version": "cli-remote-receipt.v1", "verification_basis": "AUTHORIZED_OPERATOR_ATTESTATION",
        "verified_by": context.actor_id, "source_ref": "provider-record:synthetic-case",
        "project_id": context.project_id, "operation_id": context.operation_id, "external_effect_id": effect,
        "dispatch_id": dispatch["dispatch_id"], "generation": 1, "request_hash": frozen_hash,
        "execution_id": "original-execution", "attempt_id": "original-attempt", "fencing_token": 1,
        "input_sha256": "a" * 64, "process_receipt_ref": process_ref,
        "provider_request_id": "remote-original", "outcome": "success",
        "usage": {"measurement": "PROVIDER_REPORTED", "input_tokens": 120, "output_tokens": 30, "total_tokens": 150},
        "result": {"objective": "synthetic original result"}}
    receipt["source_ref"] = asset(context.project_id,
        {key: receipt[key] for key in ("provider_request_id", "outcome", "input_sha256", "usage", "result")},
        "cli_provider_record", "cli-provider-record.v1")
    receipt.update(changes)
    ref = asset(context.project_id, receipt, "cli_remote_receipt", "cli-remote-receipt.v1")
    return ExternalEffectManualResolutionCommand(effect, context.operation_id, context.project_id, context.actor_id,
        "MARK_SUCCEEDED", "Verified original provider record", {"original_remote_receipt_ref": ref}, identifier("resolution"),
        version, context.trace_id, context.correlation_id)


def test_original_confirmation_corrects_usage_without_changing_old_ledgers():
    seeded = seed()
    context, effect, dispatch, *_ = seeded
    with transaction() as c:
        dispatch_before = c.execute("SELECT to_jsonb(d) FROM authority_external_effect_dispatch d WHERE dispatch_id=%s", [dispatch["dispatch_id"]]).fetchone()[0]
        budget_before = c.execute("SELECT to_jsonb(b) FROM authority_budget_reservation b WHERE external_effect_id=%s", [effect]).fetchone()[0]
    command = confirmation(*seeded)
    assert resolve_external_effect_manually(DATABASE_URL, command)["decision"] == "MARK_SUCCEEDED"
    assert resolve_external_effect_manually(DATABASE_URL, command)["replayed"] is True
    with transaction() as c, c.cursor() as q:
        assert c.execute("SELECT to_jsonb(d) FROM authority_external_effect_dispatch d WHERE dispatch_id=%s", [dispatch["dispatch_id"]]).fetchone()[0] == dispatch_before
        assert c.execute("SELECT to_jsonb(b) FROM authority_budget_reservation b WHERE external_effect_id=%s", [effect]).fetchone()[0] == budget_before
        assert unresolved_cli_outcomes(q, context.project_id) == []
        usage = provider_project_usage(q, context.project_id)
        assert usage["reconciled_actual_tokens"] == 150
        assert usage["conservative_tokens"] == 1000
    recovered = read_succeeded_external_effect(DATABASE_URL, context, effect_id=effect)
    assert recovered["provider_evidence"]["usage"]["total_tokens"] == 150
    assert recovered["provider_evidence"]["result"] == {"objective": "synthetic original result"}
    assert recovered["budget_accounting_basis"] == "ACCOUNT_ENTITLEMENT"


@pytest.mark.parametrize('changes', [
    {'execution_id': 'another-execution'}, {'request_hash': 'sha256:' + 'b' * 64},
    {'attempt_id': 'another-attempt'}, {'fencing_token': 2}, {'input_sha256': 'b' * 64},
    {'generation': 2}, {'operation_id': 'another-operation'},
    {'usage': {'measurement': 'PROVIDER_REPORTED', 'input_tokens': 120, 'output_tokens': 30, 'total_tokens': 151}},
])
def test_confirmation_rejects_changed_original_identity(changes):
    from novel_forge.modules.command_kernel.errors import KernelError
    seeded = seed()
    with pytest.raises(KernelError, match='EFFECT_CLI_REMOTE_RECEIPT_INVALID'):
        resolve_external_effect_manually(DATABASE_URL, confirmation(*seeded, **changes))


@pytest.mark.parametrize("terminal", ["FAILED_FINAL", "DEAD_LETTER", "CANCELLED"])
def test_terminal_owner_is_preserved_and_requires_linked_successor(terminal):
    from novel_forge.modules.command_kernel.external_effect_runtime import read_failed_operation_success
    seeded = seed()
    context, effect, *_ = seeded
    with transaction() as c:
        c.execute("UPDATE authority_operation SET status=%s WHERE operation_id=%s", [terminal, context.operation_id])
    result = resolve_external_effect_manually(DATABASE_URL, confirmation(*seeded))
    assert result['successor_required'] is True
    with transaction() as c:
        assert c.execute('SELECT status FROM authority_operation WHERE operation_id=%s', [context.operation_id]).fetchone()[0] == terminal
    if terminal == "CANCELLED":
        from novel_forge.modules.command_kernel.errors import KernelError
        with pytest.raises(KernelError, match="EFFECT_RETAINED_RESULT_OWNER_INVALID"):
            read_failed_operation_success(DATABASE_URL, context, effect_id=effect)
    else:
        assert read_failed_operation_success(DATABASE_URL, context, effect_id=effect)['generation'] == 1


def test_reconciled_success_cannot_prepare_another_dispatch():
    from novel_forge.modules.command_kernel.errors import KernelError
    seeded = seed()
    context, effect, *_ = seeded
    resolve_external_effect_manually(DATABASE_URL, confirmation(*seeded))
    with pytest.raises(KernelError, match='EFFECT_ALREADY_RECONCILED'):
        prepare_effect_dispatch(DATABASE_URL, context, effect_id=effect)


def test_correction_is_append_only_and_conflicting_resolution_is_rejected():
    from novel_forge.modules.command_kernel.errors import KernelError
    from psycopg import Error
    seeded = seed()
    context, effect, *_ = seeded
    resolve_external_effect_manually(DATABASE_URL, confirmation(*seeded))
    with pytest.raises(KernelError, match='EFFECT_CLI_ALREADY_RECONCILED'):
        resolve_external_effect_manually(DATABASE_URL, confirmation(*seeded))
    with pytest.raises(Error, match='immutable'):
        with transaction() as c:
            c.execute("UPDATE authority_effect_reconciliation_evidence SET evidence='{}'::jsonb WHERE external_effect_id=%s AND evidence->>'contract_version'='cli-original-reconciliation.v1'", [effect])
    with pytest.raises(Error, match='immutable'):
        with transaction() as c:
            c.execute("DELETE FROM authority_effect_reconciliation_evidence WHERE external_effect_id=%s AND evidence->>'contract_version'='cli-original-reconciliation.v1'", [effect])


def test_production_result_without_original_manifests_is_not_consumable():
    from novel_forge.modules.command_kernel.errors import KernelError
    seeded = seed()
    context, effect, *_ = seeded
    with transaction() as c:
        payload = {'stage': 'world.design.generate', '_production_execution': {'frozen': True}}
        digest = _hash(payload)
        c.execute('UPDATE authority_external_effect SET request_payload=%s,request_hash=%s WHERE external_effect_id=%s', [Jsonb(payload), digest, effect])
        c.execute('UPDATE authority_external_effect_dispatch SET payload_hash=%s WHERE external_effect_id=%s', [digest, effect])
    changed = (*seeded[:3], digest, *seeded[4:])
    with pytest.raises(KernelError, match='original normalized execution manifests'):
        resolve_external_effect_manually(DATABASE_URL, confirmation(*changed))


def test_exact_corrected_usage_replay_preserves_settled_reservation():
    from novel_forge.modules.command_kernel.errors import KernelError
    seeded = seed()
    context, effect, *_ = seeded
    resolve_external_effect_manually(DATABASE_URL, confirmation(*seeded))
    with transaction() as c:
        budget = c.execute('SELECT reservation_id,to_jsonb(b) FROM authority_budget_reservation b WHERE external_effect_id=%s', [effect]).fetchone()
    replay = settle_provider_budget(DATABASE_URL, reservation_id=budget[0], project_id=context.project_id,
        actual_amount=None, actual_tokens=150, evidence={'original_usage_recovered': True})
    assert replay['replayed'] is True
    assert replay['usage_corrected'] is True
    with pytest.raises(KernelError, match='BUDGET_SETTLEMENT_CONFLICT'):
        settle_provider_budget(DATABASE_URL, reservation_id=budget[0], project_id=context.project_id,
            actual_amount=None, actual_tokens=151, evidence={'original_usage_recovered': True})
    with transaction() as c:
        assert c.execute('SELECT to_jsonb(b) FROM authority_budget_reservation b WHERE external_effect_id=%s', [effect]).fetchone()[0] == budget[1]


def test_unpersisted_remote_source_cannot_clear_unknown():
    from novel_forge.modules.command_kernel.errors import KernelError
    seeded = seed()
    with pytest.raises(KernelError, match='EFFECT_CLI_REMOTE_RECEIPT_INVALID'):
        resolve_external_effect_manually(DATABASE_URL, confirmation(*seeded, source_ref='operator-note-only'))



def production_confirmation(seeded):
    from copy import deepcopy
    context, effect, dispatch, *_ = seeded
    with transaction() as c:
        original = c.execute('SELECT evidence FROM authority_external_effect_dispatch WHERE dispatch_id=%s', [dispatch['dispatch_id']]).fetchone()[0]
    result = {'objective': 'synthetic original result'}
    usage = {'measurement': 'PROVIDER_REPORTED', 'input_tokens': 120, 'output_tokens': 30, 'total_tokens': 150}
    cost = {'availability': 'UNAVAILABLE', 'measurement': 'UNKNOWN', 'reason': 'account_entitlement', 'currency': 'UNKNOWN'}
    def manifest(kind, data):
        return asset(context.project_id, data, 'execution_evidence', kind + '.v1', kind)
    normalized_ref = manifest('normalized-output', result)
    identity = {'operation_id': context.operation_id, 'attempt_id': 'original-attempt', 'fencing_token': 1}
    output_ref = manifest('output-manifest', {**identity, 'normalized_output_ref': normalized_ref,
        'output_hash': _hash(result).removeprefix('sha256:')})
    validation_ref = manifest('validation-manifest', {**identity, 'output_manifest_ref': output_ref,
        'validation_policy_ref': 'policy:original', 'decision': 'ACCEPTED'})
    evidence = deepcopy(original)
    evidence.update(result=result, usage=usage, cost=cost, real_model_call=False, fixture_protocol_only=True,
        provider_id='synthetic', model_id='frozen-model')
    evidence['production_execution']['execution_result'].update(operation_id=context.operation_id, outcome='SUCCEEDED',
        normalized_output_ref=normalized_ref, output_manifest_ref=output_ref, validation_report_ref=validation_ref,
        usage_receipt_ref=manifest('usage-receipt', usage), cost_receipt_ref=manifest('cost-receipt', cost))
    return confirmation(*seeded, provider_evidence=evidence), evidence


def recovered_port(seeded, completion, *, stale=False, changed_input=False):
    from copy import deepcopy
    from types import SimpleNamespace
    from novel_forge.modules.command_kernel.attempt_runtime import create_attempt, queue_attempt, acquire_attempt_lease, start_attempt, WorkerLeaseCommand
    from novel_forge.modules.story_planning_runtime.execution import _PlanningPepPort
    from novel_forge.storage.authority_asset_store import AuthorityAssetWriter
    context, effect, *_ = seeded
    with transaction() as c:
        c.execute("UPDATE authority_operation SET status='READY' WHERE operation_id=%s", [context.operation_id])
    attempt = create_attempt(DATABASE_URL, operation_id=context.operation_id, project_id=context.project_id, max_attempts=2, trace_id='trace', correlation_id='correlation')['attempt_id']
    queue_attempt(DATABASE_URL, attempt_id=attempt, project_id=context.project_id, trace_id='trace', correlation_id='correlation')
    lease = acquire_attempt_lease(DATABASE_URL, attempt_id=attempt, project_id=context.project_id, worker_id='recovery-worker', lease_seconds=60, trace_id='trace', correlation_id='correlation')
    start_attempt(DATABASE_URL, WorkerLeaseCommand(attempt, context.project_id, 'recovery-worker', lease['fencing_token'], 'trace', 'correlation'))
    production = completion['provider_evidence']['production_execution']
    current_input = deepcopy(production['input_manifest'])
    current_input.update(manifest_id='current-input', attempt_id=attempt, fencing_token=lease['fencing_token'])
    if changed_input:
        current_input['input_artifacts'] = [{'artifact_ref': 'changed-input'}]
    current_route = deepcopy(production['route_snapshot'])
    current_route.update(route_snapshot_id='current-route', route_decision_id='current-decision', attempt_id=attempt)
    request = SimpleNamespace(operation_id=context.operation_id, project_id=context.project_id, attempt_id=attempt,
        fencing_token=lease['fencing_token'] + int(stale), capability='model.test', execution_id='current-consumer',
        stage=production['execution_request'].get('stage', 'world.design.generate'), trace_id='trace', correlation_id='correlation', route_snapshot_id='current-route', input_manifest_ref='current-input')
    binding = SimpleNamespace(request=request, input_manifest=SimpleNamespace(to_dict=lambda: current_input), route_snapshot=SimpleNamespace(to_dict=lambda: current_route))
    return _PlanningPepPort(database_url=DATABASE_URL, worker_id='recovery-worker', lease_seconds=60,
        context=context, effect_id=effect, stable_key='unused', reservation_id=completion['budget_reservation_id'],
        reserved_amount=None, reserved_tokens=1000, binding=binding, adapter=QueryOnly('success'),
        recovered_completion=completion, writer=AuthorityAssetWriter(DATABASE_URL), post_provider_fault_injector=lambda _: None)


def test_planning_consumes_original_result_without_dispatch_or_resettlement():
    from types import SimpleNamespace
    seeded = seed(production=True)
    context, effect, *_ = seeded
    command, evidence = production_confirmation(seeded)
    resolve_external_effect_manually(DATABASE_URL, command)
    completion = read_succeeded_external_effect(DATABASE_URL, context, effect_id=effect)
    port = recovered_port(seeded, completion)
    candidate = port.execute(SimpleNamespace(capability='model.test'))
    assert candidate.raw_output == {'objective': 'synthetic original result'}
    assert candidate.evidence.execution_id == 'original-execution'
    assert candidate.evidence.output_manifest_ref == evidence['production_execution']['execution_result']['output_manifest_ref']
    with transaction() as c:
        assert c.execute('SELECT count(*) FROM authority_external_effect_dispatch WHERE external_effect_id=%s', [effect]).fetchone()[0] == 1
        assert c.execute('SELECT actual_tokens FROM authority_budget_reservation WHERE external_effect_id=%s', [effect]).fetchone()[0] == 1000


def test_same_attempt_receipt_consumption_preserves_first_call_log_and_cost():
    from types import SimpleNamespace
    from novel_forge.modules.command_kernel.attempt_runtime import acquire_attempt_lease
    seeded = seed(production=True)
    context, effect, *_ = seeded
    command, evidence = production_confirmation(seeded)
    resolve_external_effect_manually(DATABASE_URL, command)
    completion = read_succeeded_external_effect(DATABASE_URL, context, effect_id=effect)
    port = recovered_port(seeded, completion)
    port._record_model_evidence(evidence=evidence, usage=evidence['usage'], cost=evidence['cost'],
        amount=None, total_tokens=150, accepted_candidate=False, recovered_completion=False)
    with transaction() as c:
        original = c.execute("SELECT v.asset_version_id,v.content_hash,v.content FROM authority_asset_version v JOIN authority_asset a USING(asset_id) WHERE a.project_id=%s AND a.asset_type='model_call_log'", [context.project_id]).fetchone()
        c.execute("UPDATE authority_lease_acquisition SET acquired_at=NOW()-INTERVAL '2 minutes',heartbeat_at=NOW()-INTERVAL '1 minute',expires_at=NOW()-INTERVAL '1 second' WHERE attempt_id=%s AND status='HELD'", [port.binding.request.attempt_id])
    lease = acquire_attempt_lease(DATABASE_URL, attempt_id=port.binding.request.attempt_id,
        project_id=context.project_id, worker_id=port.worker_id, lease_seconds=60,
        trace_id='trace', correlation_id='correlation')
    port.binding.request.fencing_token = lease['fencing_token']
    assert lease['fencing_token'] == 2
    candidate = port.execute(SimpleNamespace(capability='model.test'))
    assert candidate.raw_output == evidence['result']
    assert port.execute(SimpleNamespace(capability='model.test')).raw_output == evidence['result']
    with transaction() as c:
        assert c.execute('SELECT content_hash,content FROM authority_asset_version WHERE asset_version_id=%s', [original[0]]).fetchone() == original[1:]
        assert c.execute("SELECT count(*) FROM authority_asset a WHERE a.project_id=%s AND a.asset_type='cost_ledger'", [context.project_id]).fetchone()[0] == 1
        consumed = c.execute("SELECT v.content FROM authority_asset_version v JOIN authority_asset a USING(asset_id) WHERE a.project_id=%s AND a.asset_type='model_call_log' AND v.content->>'evidence_kind'='ORIGINAL_RECEIPT_CONSUMPTION'", [context.project_id]).fetchall()
        assert len(consumed) == 1
        assert consumed[0][0]['consumer_fencing_token'] == 2
        assert consumed[0][0]['provider_invoked_this_attempt'] is False
        assert consumed[0][0]['source_external_effect_id'] == effect
        assert c.execute('SELECT count(*) FROM authority_external_effect_dispatch WHERE external_effect_id=%s', [effect]).fetchone()[0] == 1
    from novel_forge.modules.command_kernel.errors import KernelError
    with pytest.raises(KernelError, match='PLANNING_RECEIPT_CONSUMPTION_CONFLICT'):
        port._record_evidence('model_call_log', {**consumed[0][0], 'candidate_accepted': True})
    with pytest.raises(KernelError, match='PLANNING_RECEIPT_CONSUMPTION_CONFLICT'):
        port._record_evidence('model_call_log', {**consumed[0][0], 'candidate_accepted': 0})


@pytest.mark.parametrize('stage', ['context_compress', 'context_fidelity'])
def test_context_receipt_restart_fills_missing_original_accounting_once(stage):
    from types import SimpleNamespace
    from novel_forge.modules.command_kernel.errors import KernelError
    seeded = seed(production=True, stage=stage)
    context, effect, *_ = seeded
    command, _ = production_confirmation(seeded)
    resolve_external_effect_manually(DATABASE_URL, command)
    completion = read_succeeded_external_effect(DATABASE_URL, context, effect_id=effect)
    port = recovered_port(seeded, completion)
    def fail_before_accounting(checkpoint):
        if checkpoint == 'after_provider_receipt_before_budget_settlement':
            raise KernelError('CONTROLLED_RECEIPT_CHECKPOINT', 'worker stopped after its durable receipt')
    port.post_provider_fault_injector = fail_before_accounting
    with pytest.raises(KernelError, match='CONTROLLED_RECEIPT_CHECKPOINT'):
        port.execute(SimpleNamespace(capability='model.test'))
    with transaction() as c:
        assert c.execute("SELECT count(*) FROM authority_asset WHERE project_id=%s AND asset_type IN ('model_call_log','cost_ledger')", [context.project_id]).fetchone()[0] == 0
    port.post_provider_fault_injector = lambda _: None
    for _ in range(2):
        assert port.execute(SimpleNamespace(capability='model.test')).raw_output == {'objective': 'synthetic original result'}
    with transaction() as c:
        rows = c.execute("SELECT a.asset_type,a.asset_id,v.content FROM authority_asset a JOIN authority_asset_version v USING(asset_id) WHERE a.project_id=%s AND a.asset_type IN ('model_call_log','cost_ledger')", [context.project_id]).fetchall()
        assert len(rows) == 3
        assert all(row[2]['source_external_effect_id'] == effect for row in rows)
        original = [row for row in rows if row[2].get('evidence_kind') != 'ORIGINAL_RECEIPT_CONSUMPTION']
        assert len(original) == 2 and all('original-attempt' in row[1] for row in original)
        assert sum(row[0] == 'cost_ledger' for row in rows) == 1
        assert c.execute('SELECT count(*) FROM authority_external_effect_dispatch WHERE external_effect_id=%s', [effect]).fetchone()[0] == 1


@pytest.mark.parametrize('stale,changed_input', [(True, False), (False, True)])
def test_planning_cannot_consume_under_stale_fence_or_changed_input(stale, changed_input):
    from types import SimpleNamespace
    from novel_forge.modules.command_kernel.errors import KernelError
    seeded = seed(production=True)
    context, effect, *_ = seeded
    command, _ = production_confirmation(seeded)
    resolve_external_effect_manually(DATABASE_URL, command)
    completion = read_succeeded_external_effect(DATABASE_URL, context, effect_id=effect)
    port = recovered_port(seeded, completion, stale=stale, changed_input=changed_input)
    with pytest.raises(KernelError, match='PLANNING_RECOVERY_(FENCE|INPUT)_DRIFT'):
        port.execute(SimpleNamespace(capability='model.test'))


def test_usage_overrun_is_recorded_but_cannot_expand_dispatch_budget():
    from novel_forge.modules.command_kernel.budget_runtime import require_known_cli_lineage
    from novel_forge.modules.command_kernel.errors import KernelError
    seeded = seed()
    context, effect, *_ = seeded
    usage = {'measurement': 'PROVIDER_REPORTED', 'input_tokens': 1400, 'output_tokens': 600, 'total_tokens': 2000}
    source_ref = asset(context.project_id, {'provider_request_id': 'remote-original', 'outcome': 'success',
        'input_sha256': 'a' * 64, 'usage': usage, 'result': {'objective': 'synthetic original result'}},
        'cli_provider_record', 'cli-provider-record.v1')
    resolve_external_effect_manually(DATABASE_URL, confirmation(*seeded, usage=usage, source_ref=source_ref))
    with transaction() as c, c.cursor() as q:
        assert provider_project_usage(q, context.project_id)['conservative_tokens'] == 2000
        with pytest.raises(KernelError, match='BUDGET_CORRECTION_BREACH'):
            require_known_cli_lineage(q, project_id=context.project_id, operation_id=context.operation_id)
        pure = identifier("new-pure-operation")
        q.execute("""INSERT INTO authority_operation(operation_id,definition_name,definition_version,project_id,status,
            root_operation_id,idempotency_scope,idempotency_key,request_digest,command_payload,definition_snapshot,
            completion_contract_snapshot,policy_snapshot)
            SELECT %s,definition_name,definition_version,project_id,'READY',%s,%s,%s,%s,'{}',
                '{"external_capabilities":["model.draft"]}'::jsonb,'{}','{}'
            FROM authority_operation WHERE operation_id=%s""", [pure,pure,pure,pure,pure,context.operation_id])
        require_known_cli_lineage(q, project_id=context.project_id, operation_id=pure)
        root = identifier("new-pure-root")
        child = identifier("new-pure-child")
        for target, target_root, capabilities in [(root, root, []), (child, root, ["model.draft"])]:
            q.execute("""INSERT INTO authority_operation(operation_id,definition_name,definition_version,project_id,status,
                root_operation_id,idempotency_scope,idempotency_key,request_digest,command_payload,definition_snapshot,
                completion_contract_snapshot,policy_snapshot)
                SELECT %s,definition_name,definition_version,project_id,'READY',%s,%s,%s,%s,'{}',%s,'{}','{}'
                FROM authority_operation WHERE operation_id=%s""", [target,target_root,target,target,target,
                    Jsonb({"external_capabilities": capabilities}),context.operation_id])
        require_known_cli_lineage(q, project_id=context.project_id, operation_id=root)
        assert provider_project_usage(q, context.project_id)['conservative_tokens'] == 2000


@pytest.mark.parametrize('baseline', ['20260625_0001_initial_industrial_schema', '20261008_0181_author_manuscript_delivery', '20261008_0183_source_observation_span_identity'])
def test_cli_journal_forward_migration_preserves_previous_head(baseline):
    import psycopg
    from novel_forge.storage.migrations import run_migrations, LATEST_MIGRATION_ID
    from tests.integration.migration_window_postgres_support import disposable_database_at_migration
    with disposable_database_at_migration(DATABASE_URL, prefix='cli_reconciliation', target_migration_id=baseline) as url:
        with psycopg.connect(url) as c:
            before = c.execute('SELECT migration_id,applied_at FROM nf_schema_migrations ORDER BY migration_id').fetchall()
        assert run_migrations(url)['ok']
        assert run_migrations(url)['ok']
        with psycopg.connect(url) as c:
            assert c.execute('SELECT migration_id,applied_at FROM nf_schema_migrations WHERE migration_id=ANY(%s) ORDER BY migration_id', [[x[0] for x in before]]).fetchall() == before
            assert c.execute("SELECT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='authority_cli_original_reconciliation_guard')").fetchone()[0]
            assert c.execute('SELECT migration_id FROM nf_schema_migrations ORDER BY migration_id DESC LIMIT 1').fetchone()[0] == LATEST_MIGRATION_ID


@pytest.mark.parametrize('change', [
    {'outcome': 'SUCCEEDED'}, {'started_at': None}, {'usage_receipt_ref': 'existing-usage'},
])
def test_historical_exception_does_not_admit_adjacent_failure_generations(change):
    from novel_forge.modules.command_kernel.errors import KernelError
    seeded = seed()
    context, effect, dispatch, *_ = seeded
    with transaction() as c:
        evidence = c.execute('SELECT evidence FROM authority_external_effect_dispatch WHERE dispatch_id=%s', [dispatch['dispatch_id']]).fetchone()[0]
        evidence['production_execution']['execution_result'].update(change)
        c.execute('UPDATE authority_external_effect_dispatch SET evidence=%s WHERE dispatch_id=%s', [Jsonb(evidence), dispatch['dispatch_id']])
    with pytest.raises(KernelError, match='EFFECT_STATUS_CONFLICT'):
        reconcile_external_effect(DATABASE_URL, context, effect_id=effect, adapter=QueryOnly('success'))


def test_reconciled_query_returns_existing_conclusion_without_provider_query():
    seeded = seed()
    context, effect, *_ = seeded
    resolve_external_effect_manually(DATABASE_URL, confirmation(*seeded))
    class NoQuery(QueryOnly):
        def query(self, **_):
            raise AssertionError('confirmed original result must not be queried again')
    result = reconcile_external_effect(DATABASE_URL, context, effect_id=effect, adapter=NoQuery('success'))
    assert result['outcome'] == 'success'
    assert result['replayed'] is True


@pytest.mark.parametrize("held", [False, True])
def test_concurrent_same_confirmation_is_one_append_and_idempotent_replays(held):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    seeded = seed(held=held)
    context, effect, *_ = seeded
    command = confirmation(*seeded)
    barrier = Barrier(6)
    def resolve():
        barrier.wait()
        return resolve_external_effect_manually(DATABASE_URL, command)
    with ThreadPoolExecutor(max_workers=6) as executor:
        outcomes = list(executor.map(lambda _: resolve(), range(6)))
    assert sum(not outcome['replayed'] for outcome in outcomes) == 1
    with transaction() as c:
        assert c.execute("SELECT count(*) FROM authority_effect_reconciliation_evidence WHERE external_effect_id=%s AND evidence->>'contract_version'='cli-original-reconciliation.v1'", [effect]).fetchone()[0] == 1


def test_query_does_not_override_confirmation_committed_while_it_reads():
    seeded = seed()
    context, effect, *_ = seeded
    command = confirmation(*seeded)
    class ConfirmsDuringQuery(QueryOnly):
        def query(self, **_):
            resolve_external_effect_manually(DATABASE_URL, command)
            return ProviderResult('ambiguous', '', {'external_state_unknown': True})
    result = reconcile_external_effect(DATABASE_URL, context, effect_id=effect, adapter=ConfirmsDuringQuery('success'))
    assert result['outcome'] == 'success'
    with transaction() as c:
        assert c.execute("SELECT count(*) FROM authority_effect_reconciliation_evidence WHERE external_effect_id=%s", [effect]).fetchone()[0] == 1


def test_receipt_intake_cannot_replace_original_provider_or_promote_qualification():
    seeded = seed(production=True)
    context, effect, *_ = seeded
    command, _ = production_confirmation(seeded)
    with transaction() as c:
        row = c.execute('SELECT content FROM authority_asset_version WHERE asset_version_id=%s', [command.evidence['original_remote_receipt_ref'].split(':', 1)[1]]).fetchone()[0]
    row['provider_evidence'].update(provider_id='other-provider', production_verified=True)
    changed_ref = asset(context.project_id, row, 'cli_remote_receipt', 'cli-remote-receipt.v1')
    from dataclasses import replace
    resolve_external_effect_manually(DATABASE_URL, replace(command, evidence={'original_remote_receipt_ref': changed_ref}))
    recovered = read_succeeded_external_effect(DATABASE_URL, context, effect_id=effect)
    assert recovered['provider_evidence'].get('provider_id') != 'other-provider'
    assert recovered['provider_evidence']['production_verified'] is False


def test_unknown_terminal_original_settles_held_usage_once_and_preserves_history():
    seeded = seed(held=True)
    context, effect, dispatch, *_ = seeded
    with transaction() as c:
        c.execute("UPDATE authority_operation SET status='FAILED_FINAL' WHERE operation_id=%s", [context.operation_id])
        before = c.execute('SELECT to_jsonb(d) FROM authority_external_effect_dispatch d WHERE dispatch_id=%s', [dispatch['dispatch_id']]).fetchone()[0]
        assert c.execute('SELECT status FROM authority_budget_reservation WHERE external_effect_id=%s', [effect]).fetchone()[0] == 'HELD_UNKNOWN'
    command = confirmation(*seeded)
    result = resolve_external_effect_manually(DATABASE_URL, command)
    assert result['successor_required'] is True
    assert resolve_external_effect_manually(DATABASE_URL, command)['replayed'] is True
    with transaction() as c, c.cursor() as q:
        assert c.execute('SELECT to_jsonb(d) FROM authority_external_effect_dispatch d WHERE dispatch_id=%s', [dispatch['dispatch_id']]).fetchone()[0] == before
        assert c.execute('SELECT status FROM authority_operation WHERE operation_id=%s', [context.operation_id]).fetchone()[0] == 'FAILED_FINAL'
        assert c.execute('SELECT status,actual_tokens,settled_amount FROM authority_budget_reservation WHERE external_effect_id=%s', [effect]).fetchone() == ('SETTLED', 150, None)
        assert not unresolved_cli_outcomes(q, context.project_id)
        usage = provider_project_usage(q, context.project_id)
        assert usage['recorded_actual_tokens'] == usage['conservative_tokens'] == 150
    from novel_forge.modules.command_kernel.external_effect_runtime import read_failed_operation_success
    assert read_failed_operation_success(DATABASE_URL, context, effect_id=effect)['provider_evidence']['result'] == {'objective': 'synthetic original result'}


def test_unknown_without_authenticated_original_record_cannot_be_manually_cleared():
    from dataclasses import replace
    from novel_forge.modules.command_kernel.errors import KernelError
    seeded = seed(held=True)
    context, effect, *_ = seeded
    command = confirmation(*seeded)
    with pytest.raises(KernelError, match='EFFECT_CLI_REMOTE_RECEIPT_INVALID'):
        resolve_external_effect_manually(DATABASE_URL, replace(command, evidence={'provider_not_executed': True}))
    with transaction() as c:
        assert c.execute('SELECT status FROM authority_external_effect WHERE external_effect_id=%s', [effect]).fetchone()[0] == 'UNKNOWN'
        assert c.execute('SELECT status FROM authority_budget_reservation WHERE external_effect_id=%s', [effect]).fetchone()[0] == 'HELD_UNKNOWN'


def test_opening_classifies_verified_original_resolution_and_retains_unknown_history():
    from novel_forge.modules.book_authority.recovery import PostgresBookOpeningRecoveryApplication
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    seeded = seed(held=True)
    context, effect, *_ = seeded
    recovery = object.__new__(PostgresBookOpeningRecoveryApplication)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        before = recovery._external_effect_evidence(uow, context.operation_id)
        assert before['classification'] == 'UNKNOWN_AMBIGUOUS'
    resolve_external_effect_manually(DATABASE_URL, confirmation(*seeded))
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        after = recovery._external_effect_evidence(uow, context.operation_id)
    assert after['classification'] == 'PROVEN_SUCCESS'
    assert after['evidence'][0]['effect_status'] == 'UNKNOWN'
    assert after['evidence'][0]['dispatch_status'] == 'UNKNOWN'
    assert after['evidence'][0]['original_cli_reconciliation']['outcome'] == 'success'
    assert after['digest'] != before['digest']


def test_database_lineage_guard_requires_verified_original_resolution():
    seeded = seed(held=True)
    context, effect, *_ = seeded
    with transaction() as c:
        assert c.execute('SELECT authority_planning_cli_lineage_reconciled(%s)', [context.operation_id]).fetchone()[0] is False
    resolve_external_effect_manually(DATABASE_URL, confirmation(*seeded))
    with transaction() as c:
        assert c.execute('SELECT authority_planning_cli_lineage_reconciled(%s)', [context.operation_id]).fetchone()[0] is True


@pytest.mark.parametrize("outcome", ["TIMED_OUT", "UNKNOWN", "ORPHANED"])
def test_legacy_retryable_cli_uncertainty_queries_original_identity(outcome):
    context, effect, dispatch, *_ = seed()
    with transaction() as connection:
        connection.execute("UPDATE authority_external_effect_dispatch SET evidence=jsonb_set(evidence,'{production_execution,execution_result,outcome}',%s) WHERE dispatch_id=%s", [Jsonb(outcome), dispatch["dispatch_id"]])
        before = connection.execute("SELECT to_jsonb(d) FROM authority_external_effect_dispatch d WHERE dispatch_id=%s", [dispatch["dispatch_id"]]).fetchone()[0]
    result = reconcile_external_effect(DATABASE_URL, context, effect_id=effect, adapter=QueryOnly("success"))
    assert result["recovery_state"] == "RECONCILIATION_REQUIRED"
    with transaction() as connection:
        assert connection.execute("SELECT to_jsonb(d) FROM authority_external_effect_dispatch d WHERE dispatch_id=%s", [dispatch["dispatch_id"]]).fetchone()[0] == before
        assert connection.execute("SELECT count(*) FROM authority_external_effect_dispatch WHERE external_effect_id=%s", [effect]).fetchone()[0] == 1


def test_saved_result_scan_uses_owned_versions_and_keeps_book_actor_operation_scope(monkeypatch):
    from types import SimpleNamespace
    from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
    from novel_forge.modules.production_execution.saved_result_recovery import recover_saved_local_results
    from novel_forge.storage.authority_asset_store import AuthorityAssetWriter
    seeded = seed(held=True)
    context, effect, *_ = seeded
    writer = AuthorityAssetWriter(DATABASE_URL)
    previous = None
    for number in range(2):
        previous = writer.materialize_output(AuthorityAssetWriteCommand(
            operation_id=context.operation_id, project_id=context.project_id,
            asset_id='session:'+effect, asset_type='execution_recovery_session',
            schema_version='authority-execution-recovery.v1', logical_ref='sessions/'+effect,
            category='production_execution_recovery', output_key='session', role='execution_recovery_projection',
            content={'execution_id':'original-session', 'record':{'request':{'external_effect_id':effect,
                'book_id':'same-book'}, 'observation':number}}, qualification_policy='fixture-only',
            trace_id='trace', correlation_id='correlation',
            expected_current_asset_version_id=previous.asset_version_id if previous else None))
    class Captured(Exception):
        pass
    seen = []
    def get_record(identity):
        seen.append(identity)
        raise Captured
    transport = SimpleNamespace(session_for_project=lambda _: SimpleNamespace(
        evidence_store=SimpleNamespace(get_record=get_record)))
    with transaction() as c:
        actor = c.execute('SELECT actor_id FROM authority_operation WHERE operation_id=%s', [context.operation_id]).fetchone()[0]
        definition = c.execute('SELECT definition_name FROM authority_operation WHERE operation_id=%s', [context.operation_id]).fetchone()[0]
        c.execute('UPDATE authority_operation SET root_operation_id=operation_id WHERE operation_id=%s', [context.operation_id])
    principal = SimpleNamespace(principal_id=actor, require=lambda *args: None)
    args = dict(database_url=DATABASE_URL, project_id=context.project_id, book_id='same-book', principal=principal)
    with pytest.raises(Captured):
        recover_saved_local_results(transport, **args)
    assert seen == ['original-session']
    from novel_forge.modules.command_kernel.generation_isolation import recover_book_generations, recover_chapter_generations
    from novel_forge.modules.chapter_authority import receipt_recovery
    from novel_forge.modules.production_execution.gateway import ExecutionBackendRegistry
    from novel_forge.modules.story_planning_runtime import gateway_result_recovery
    from novel_forge.modules.command_kernel import execution_window
    monkeypatch.setattr(gateway_result_recovery, 'recover_completed_planning_outputs', lambda *a, **kw: False)
    monkeypatch.setattr(execution_window, 'continue_saved_result_finalization', lambda *a, **kw: False)
    registry = ExecutionBackendRegistry()
    optional_record = SimpleNamespace(request=SimpleNamespace(), handle=SimpleNamespace())
    optional_transport = SimpleNamespace(session_for_project=lambda _: SimpleNamespace(
        evidence_store=SimpleNamespace(get_record=lambda _: optional_record),
        gateway=SimpleNamespace(backends=registry, admission=SimpleNamespace(
            resolve_route=lambda _: SimpleNamespace(backend_id='remote-provider-deepseek')))))
    application = SimpleNamespace(database_url=DATABASE_URL, execution_binder=SimpleNamespace(
        resolver=SimpleNamespace(execution_preparer=SimpleNamespace(execution_transport=optional_transport))))
    assert recover_book_generations(application, project_id=context.project_id, book_id='same-book', principal=principal) is False
    monkeypatch.setattr(receipt_recovery, 'recover_completed_chapter_results', lambda *a, **kw: False)
    authority = SimpleNamespace(database_url=DATABASE_URL,
        require=lambda _: {'project_id':context.project_id, 'book_id':'same-book', 'active_chapter_request_id':'active-chapter'},
        require_chapter_request=lambda _: {'chapter_root_operation_id':'other-root'},
        chapter_port=SimpleNamespace(application=SimpleNamespace(_model_port=SimpleNamespace(adapter=optional_transport))))
    assert recover_chapter_generations(authority, book_run_id='same-book-run', principal=principal) is False
    authority.require_chapter_request = lambda _: {'chapter_root_operation_id':context.operation_id}
    with pytest.raises(ValueError, match='execution backend is not registered: remote-provider-deepseek'):
        recover_chapter_generations(authority, book_run_id='same-book-run', principal=principal)
    with transaction() as c:
        assert c.execute('SELECT status FROM authority_external_effect WHERE external_effect_id=%s', [effect]).fetchone()[0] == 'UNKNOWN'
    for scope in ({'operation_definition_name':definition}, {'root_operation_id':context.operation_id}):
        with pytest.raises(Captured):
            recover_saved_local_results(transport, **args, **scope)
    assert seen == ['original-session'] * 3
    for changed in ({'book_id':'other-book'}, {'operation_ids':['unrelated-operation']},
                    {'operation_definition_name':'unrelated-definition'}, {'root_operation_id':'unrelated-root'},
                    {'principal':SimpleNamespace(principal_id='other-actor', require=lambda *args: None)}):
        assert recover_saved_local_results(transport, **{**args, **changed}) is False
    assert seen == ['original-session'] * 3


def test_planning_original_success_without_usage_correction_keeps_execution_identity():
    from types import SimpleNamespace
    from novel_forge.modules.command_kernel.external_effect_runtime import accept_external_effect_receipt
    seeded = seed(production=True, held=True)
    context, effect, dispatch, *_ = seeded
    _, evidence = production_confirmation(seeded)
    accept_external_effect_receipt(DATABASE_URL, context, dispatch_id=dispatch['dispatch_id'],
        provider=FakeDeterministicProvider('success').provider, receipt_id='original-complete',
        message_id='original-complete', payload_hash=_hash(evidence), provider_correlation_id='original',
        generation=1, outcome='success', evidence=evidence)
    with transaction() as c:
        reservation = c.execute('SELECT reservation_id FROM authority_budget_reservation WHERE external_effect_id=%s',[effect]).fetchone()[0]
    settle_provider_budget(DATABASE_URL, reservation_id=reservation, project_id=context.project_id,
        actual_amount=None, actual_tokens=1000, evidence={'usage_settlement_basis':'RESERVATION_CEILING'})
    completion = read_succeeded_external_effect(DATABASE_URL, context, effect_id=effect)
    assert not completion.get('budget_usage_correction')
    port = recovered_port(seeded, completion)
    candidate = port.execute(SimpleNamespace(capability='model.test'))
    assert candidate.raw_output == evidence['result']
    assert candidate.evidence.execution_id == 'original-execution'
    with transaction() as c:
        assert c.execute('SELECT count(*) FROM authority_external_effect_dispatch WHERE external_effect_id=%s',[effect]).fetchone()[0] == 1


@pytest.mark.parametrize('owner', ['definition', 'root'])
def test_saved_success_accounting_recovers_only_the_selected_owner(owner):
    from types import SimpleNamespace
    from novel_forge.modules.command_kernel.external_effect_runtime import accept_external_effect_receipt
    from novel_forge.modules.production_execution.saved_result_recovery import recover_saved_local_results

    seeded = seed(production=True, held=True, book_id='synthetic-book')
    context, effect, dispatch, *_ = seeded
    _, evidence = production_confirmation(seeded)
    receipt = identifier('scoped-original-complete')
    accept_external_effect_receipt(DATABASE_URL, context, dispatch_id=dispatch['dispatch_id'],
        provider=FakeDeterministicProvider('success').provider, receipt_id=receipt,
        message_id=receipt, payload_hash=_hash(evidence), provider_correlation_id='original',
        generation=1, outcome='success', evidence=evidence)
    with transaction() as c:
        c.execute('UPDATE authority_operation SET root_operation_id=operation_id WHERE operation_id=%s', [context.operation_id])
        actor, definition = c.execute('SELECT actor_id,definition_name FROM authority_operation WHERE operation_id=%s', [context.operation_id]).fetchone()
        before = c.execute('SELECT to_jsonb(b) FROM authority_budget_reservation b WHERE external_effect_id=%s', [effect]).fetchone()[0]
    principal = SimpleNamespace(principal_id=actor, require=lambda *args: None)
    args = dict(database_url=DATABASE_URL, project_id=context.project_id, book_id='synthetic-book', principal=principal)
    key, value = ('operation_definition_name',definition) if owner=='definition' else ('root_operation_id',context.operation_id)
    assert recover_saved_local_results(None, **args, **{key:'unrelated-owner'}) is False
    with transaction() as c:
        assert c.execute('SELECT to_jsonb(b) FROM authority_budget_reservation b WHERE external_effect_id=%s', [effect]).fetchone()[0] == before
    assert recover_saved_local_results(None, **args, **{key:value}) is True
    with transaction() as c:
        assert c.execute('SELECT status,actual_tokens FROM authority_budget_reservation WHERE external_effect_id=%s', [effect]).fetchone() == ('SETTLED',150)
