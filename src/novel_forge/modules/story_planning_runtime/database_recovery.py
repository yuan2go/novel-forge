from __future__ import annotations

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
from .domain import canonical_hash

CONTRACT = "planning-unsent-context-query-recovery.v1"
MODE = "KNOWN_UNSENT_CONTEXT_QUERY_FAILURE"


def require_source(uow, *, source_operation_id, row, frozen, attempt):
    failure = dict(attempt[2] or {})
    if (row[0] != "FAILED_FINAL" or attempt[0] != "FAILED_FINAL"
            or failure.get("error_code") != "PROGRAMMING_BUG"
            or failure.get("failure_class") != "programming_bug"
            or failure.get("error_message") != "canceling statement due to statement timeout"):
        raise KernelError("PLANNING_UNSENT_DATABASE_SOURCE_INVALID", "Require the exact historical stopped statement-timeout failure")
    uow.cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s)
        OR EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=%s)
        OR EXISTS(SELECT 1 FROM authority_operation_output_asset WHERE operation_id=%s)
        OR EXISTS(SELECT 1 FROM authority_attempt WHERE operation_id=%s AND status IN ('LEASED','RUNNING','CHECKPOINTED','RESULT_SUBMITTED'))
        OR EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id) WHERE a.operation_id=%s AND l.status='HELD')
        OR EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=%s AND acknowledged_at IS NULL)
        OR EXISTS(SELECT 1 FROM authority_book_production WHERE project_id=%s AND book_id=%s AND state IN ('ABORTED','CANCELLED','COMPLETED'))""",
        [source_operation_id] * 6 + [frozen['project_id'], frozen['book_id']])
    if uow.cursor.fetchone()[0]:
        raise KernelError("PLANNING_UNSENT_DATABASE_SOURCE_UNSAFE", "Require zero outputs, budgets and Effects, stopped leases and a live Book")
    uow.cursor.execute("""SELECT s.snapshot_payload,s.snapshot_id,s.snapshot_hash,s.attempt_id,g.input_snapshot
        FROM authority_attempt_capability_pack_snapshot s JOIN authority_story_planning_generation g USING(operation_id)
        WHERE s.operation_id=%s AND s.attempt_id=(SELECT attempt_id FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number DESC LIMIT 1)""", [source_operation_id, source_operation_id])
    snapshot = uow.cursor.fetchone()
    if not snapshot or not snapshot[4]:
        raise KernelError("PLANNING_UNSENT_DATABASE_SNAPSHOT_MISSING", "Retain the last stopped Attempt Pack and complete frozen inputs")
    inputs = snapshot[4]
    query = AuthorityAssetQuery(uow.database_url)
    for item in inputs:
        document = query.require(project_id=frozen['project_id'], asset_version_id=item['asset_version_id'])
        if document.content_hash != item['content_hash'] or document.asset_type != item['asset_type']:
            raise KernelError("PLANNING_UNSENT_DATABASE_INPUT_DRIFT", item['asset_version_id'])
    evidence_id = inputs[0]['asset_version_id']
    evidence = query.require(project_id=frozen['project_id'], asset_version_id=evidence_id)
    uow.cursor.execute("SELECT chain_depth FROM authority_story_planning_runtime_continuation WHERE successor_operation_id=%s", [source_operation_id])
    prior = uow.cursor.fetchone()
    proof = dict(contract_version=CONTRACT, source_operation_id=source_operation_id,
        project_id=frozen['project_id'], book_id=frozen['book_id'], workspace_id=frozen['workspace_id'],
        source_attempt_id=snapshot[3], source_failure=failure, source_failure_hash=canonical_hash(failure),
        original_command_hash=canonical_hash(frozen), input_snapshot_hash=canonical_hash(inputs),
        pack_snapshot_id=snapshot[1], pack_snapshot_hash=snapshot[2],
        classification_basis="HISTORICAL_WORKER_STATEMENT_TIMEOUT_TEXT_NO_RECORDED_SQLSTATE",
        provider_dispatch_count=0, context_status="NOT_MATERIALIZED")
    return dict(mode=MODE, source_operation_id=source_operation_id, command=frozen, version=int(row[1]),
        evidence_asset_version_id=evidence_id, evidence_hash=evidence.content_hash,
        snapshot=snapshot[0], attempt_id=snapshot[3], inputs=inputs, depth=(int(prior[0]) if prior else 0)+1,
        database_failure=proof)


def authorization(uow, *, source, successor, principal, target):
    from .runtime_continuation import _capacity_authorization
    checked = _capacity_authorization(uow, source=source, successor=successor, principal=principal, target=target)
    uow.cursor.execute("""SELECT r.continuation_id,r.successor_operation_id,r.target_runtime
        FROM authority_story_planning_runtime_continuation r
        JOIN authority_operation reference ON reference.operation_id=r.successor_operation_id
        JOIN authority_story_planning_generation g ON g.operation_id=reference.operation_id
        JOIN authority_operation source ON source.operation_id=%s
        WHERE r.project_id=%s AND r.workspace_id=%s AND r.book_id=%s
          AND reference.status='SUCCEEDED' AND reference.actor_id=source.actor_id
          AND g.generator_operation_name=%s AND g.logical_key=%s
          AND source.command_payload #>> '{payload,opening_execution_binding,opening_run_id}' IS NOT NULL
          AND reference.command_payload #>> '{payload,opening_execution_binding,opening_run_id}'=
              source.command_payload #>> '{payload,opening_execution_binding,opening_run_id}'
          AND EXISTS(SELECT 1 FROM authority_external_effect e WHERE e.operation_id=reference.operation_id
              AND e.status='SUCCEEDED' AND e.request_payload->>'stage'=g.generator_operation_name)
        ORDER BY reference.created_at LIMIT 1""", [source['source_operation_id'], successor.project_id,
            successor.workspace_id, successor.book_id, successor.generator_operation_name, successor.logical_key])
    reference = uow.cursor.fetchone()
    book_scope = None
    if (not reference and source.get('command', {}).get('world_preparation_request')
            and not source['command'].get('opening_execution_binding')):
        from .book_database_recovery import first_chapter_reference
        reference, book_scope = first_chapter_reference(uow, source=source, command=successor,
            formation_run_id=checked['formation_run_id'])
    if not reference:
        raise KernelError('PLANNING_UNSENT_DATABASE_ROUTE_MISSING', 'Require the original same-Opening and stage runtime with a succeeded native receipt')
    prior = reference[2]
    def stable_account(runtime):
        account = dict(runtime.get('account') or {})
        account['entitlement'] = {k:v for k,v in dict(account.get('entitlement') or {}).items() if k != 'authorization_ref'}
        return account
    keys = ('model_provider','model_id','reasoning_effort','runtime_class','model_backend_id','cost_accounting_basis')
    if any(prior.get(k) != target.get(k) for k in keys) or stable_account(prior) != stable_account(target):
        raise KernelError('PLANNING_UNSENT_DATABASE_ROUTE_DRIFT', 'Retain the original same-Opening model, reasoning, backend and account')
    actual = completed_reference_route(uow, reference_operation_id=reference[1], command=successor, prior=prior,
        **({'reference_stage':'chapter_group_plan.generate'} if book_scope else {}))
    return {**checked, 'capacity_only': False, 'recovery_kind': CONTRACT,
            'database_failure': source['database_failure'],
            'original_stage_runtime': {'continuation_id':reference[0], 'operation_id':reference[1],
                'runtime_hash':canonical_hash(prior), 'identity':{k:prior[k] for k in keys},
                'account_runtime_hash':canonical_hash(stable_account(prior)),
                'completed_effect': actual,
                'authorization_reference_change':'NATIVE_BUDGET_SUCCESSOR_ALLOWED',
                'evidence_boundary':'SAME_BOOK_ACTIVE_PARENT_GROUP_REFERENCE_NOT_SOURCE_PROVIDER_INPUT' if book_scope else 'SAME_OPENING_STAGE_REFERENCE_NOT_SOURCE_PROVIDER_INPUT',
                **({'reference_kind':'BOOK_SUPERVISOR_FIRST_CHAPTER_PLAN', 'book_scope':book_scope} if book_scope else {})},
            'first_provider_context': 'MATERIALIZE_BY_NATIVE_SUCCESSOR_NOT_REPLAY_OF_PRIOR_INPUT'}


def completed_reference_route(uow, *, reference_operation_id, command, prior, reference_stage=None):
    from novel_forge.modules.command_kernel.external_effect_runtime import EffectCommandContext, read_completed_operation_success
    stage = reference_stage or command.generator_operation_name
    if reference_stage and (command.generator_operation_name != 'chapter_plan.generate' or stage != 'chapter_group_plan.generate'):
        raise KernelError('PLANNING_UNSENT_DATABASE_ROUTE_DRIFT', 'Only the exact parent Group may precede first Book Chapter planning')
    uow.cursor.execute("""SELECT external_effect_id,request_hash FROM authority_external_effect
        WHERE operation_id=%s AND project_id=%s AND status='SUCCEEDED' AND request_payload->>'stage'=%s""",
        [reference_operation_id, command.project_id, stage])
    effects = uow.cursor.fetchall()
    if len(effects) != 1:
        raise KernelError('PLANNING_UNSENT_DATABASE_ROUTE_MISSING', 'Require one exact succeeded main-stage Effect')
    effect_id, request_hash = effects[0]
    receipt = read_completed_operation_success(uow.database_url,
        EffectCommandContext(reference_operation_id, command.project_id, command.actor_id, command.trace_id, command.correlation_id), effect_id=effect_id)
    provider = receipt.get('provider_evidence') if receipt else None
    production = provider.get('production_execution', {}) if isinstance(provider, dict) else {}
    route = production.get('route_snapshot', {})
    request = production.get('execution_request', {})
    expected = dict(model_provider=prior.get('model_provider'),model_id=prior.get('model_id'),
        reasoning_effort=prior.get('reasoning_effort'),backend_id=prior.get('model_backend_id'),auth_profile_ref=prior.get('auth_profile_ref'))
    process = production.get('process_evidence', {})
    authority = process.get('model_authority', {})
    if (not provider or provider.get('fixture_protocol_only') is not False
            or process.get('transport') != 'LOCAL_CLI_REMOTE_INFERENCE' or process.get('terminal_event_observed') is not True
            or authority.get('local_user_config_ignored') is not True
            or authority.get('invocation_model') != expected['model_id']
            or authority.get('invocation_reasoning_effort') != expected['reasoning_effort']
            or provider.get('provider_id') != expected['model_provider'] or provider.get('model_id') != expected['model_id']
            or any(route.get(k) != v for k,v in expected.items())
            or route.get('operation_id') != reference_operation_id
            or request.get('operation_id') != reference_operation_id or request.get('external_effect_id') != effect_id
            or request.get('stage') != stage):
        raise KernelError('PLANNING_UNSENT_DATABASE_ROUTE_DRIFT', 'The verified actual reference receipt and selected route must match its registered runtime')
    return dict(external_effect_id=effect_id, request_hash=request_hash, provider_evidence_hash=canonical_hash(provider),
        route_snapshot_hash=canonical_hash(route), route_snapshot_id=route['route_snapshot_id'],
        process_receipt_ref=production.get('execution_result', {}).get('process_receipt_ref'),
        model_authority_hash=canonical_hash(authority),
        model_provider=expected['model_provider'],model_id=expected['model_id'],reasoning_effort=expected['reasoning_effort'],
        backend_id=expected['backend_id'],identity_basis='VERIFIED_COMPLETED_NATIVE_RECEIPT_AND_FROZEN_ROUTE',
        model_call_in_this_read=False)


def require_diagnostic(decision, source):
    proof = decision.get('unsent_context_query_diagnostic')
    if (not isinstance(proof, dict) or proof.get('contract_version') != CONTRACT
            or any(proof.get(k) != source['database_failure'].get(k) for k in (
                'source_operation_id','source_attempt_id','project_id','workspace_id','book_id',
                'original_command_hash','input_snapshot_hash','pack_snapshot_id','pack_snapshot_hash'))
            or not all(isinstance(proof.get(k), str) and proof[k] for k in (
                'source_operation_id','source_attempt_id','project_id','workspace_id','book_id',
                'original_command_hash','input_snapshot_hash','pack_snapshot_id','pack_snapshot_hash'))
            or proof.get('source_failure_hash') != source['database_failure']['source_failure_hash']
            or proof.get('query_owner') != 'mkaos_authority.list_planning_usage'
            or proof.get('exception_type') != 'psycopg.errors.QueryCanceled'
            or proof.get('sqlstate') != '57014'
            or proof.get('diagnostic_status') != 'ACTUAL_READ_ONLY_REPRODUCTION'
            or proof.get('revalidation_status') != 'PASS_NO_PROVIDER_NO_OUTPUT'
            or not all(isinstance(proof.get(k), str) and len(proof[k]) == 71
                       and proof[k].startswith('sha256:') and all(c in '0123456789abcdef' for c in proof[k][7:])
                       for k in ('query_hash','diagnostic_hash','revalidation_hash'))):
        raise KernelError('PLANNING_UNSENT_DATABASE_DIAGNOSTIC_REQUIRED', 'Bind the actual supplemental read-only diagnosis and successful host-query revalidation; do not backfill historical SQLSTATE')
    return {**proof, 'evidence_kind': 'OPERATOR_REPORTED_SUPPLEMENTAL_DIAGNOSTIC_NOT_PROVIDER_OR_HUMAN_REVIEW'}
