from __future__ import annotations

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.cost_routing import snapshot_hash
from novel_forge.modules.review.quality_namespace import separate_quality_checks
from .model_effects import ModelProviderResult

CONTRACT = 'chapter-quality-review-revalidation.v1'


def retained_quality_review(cursor, source):
    from .handlers import _provider_evidence, normalize_rereview_result
    from novel_forge.modules.production_execution.execution_template import verify_template_provenance
    from novel_forge.modules.command_kernel.step_successor import has_candidate_domain_outputs
    op = source['operation_id']
    if (source['definition_name'] != 'chapter.revision.review' or source['definition_version'] != '3.9.3'
            or source['status'] != 'FAILED_FINAL' or has_candidate_domain_outputs(cursor, op)):
        raise KernelError('QUALITY_REVIEW_RECOVERY_NOT_APPLICABLE', 'Retain the exact non-producing settled legacy rereview')
    cursor.execute('SELECT to_jsonb(a) FROM authority_attempt a WHERE operation_id=%s ORDER BY attempt_number', [op])
    attempts = [r[0] for r in cursor.fetchall()]
    if (len(attempts) != 1 or attempts[0]['status'] != 'FAILED_FINAL'
            or attempts[0]['result'].get('error_code') != 'REVIEW_RESOLUTION_INVALID'):
        raise KernelError('QUALITY_REVIEW_RECOVERY_DIAGNOSTIC_REQUIRED', 'Only the exact legacy namespace failure may be derived')
    cursor.execute("""SELECT e.external_effect_id,e.request_hash,e.request_payload,r.evidence,d.dispatch_id,receipt.payload->'evidence'
        FROM authority_external_effect e JOIN authority_budget_reservation r USING(external_effect_id)
        JOIN authority_external_effect_dispatch d USING(external_effect_id)
        JOIN authority_external_receipt receipt USING(dispatch_id)
        WHERE e.operation_id=%s AND e.status='SUCCEEDED' AND r.status='SETTLED'
        AND r.accounting_basis='ACCOUNT_ENTITLEMENT' AND e.effect_type='model.invoke'
        AND e.request_payload #>> '{_production_execution,attempt_id}'=%s ORDER BY receipt.received_at DESC""", [op, attempts[0]['attempt_id']])
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise KernelError('QUALITY_REVIEW_RECOVERY_RECEIPT_REQUIRED', 'Retain one original settled independent member receipt')
    effect, request_hash, payload, budget, dispatch, receipt = rows[0]
    decision = payload.get('_production_execution', {}).get('capability_runtime', {}).get('routing_decision', {})
    template = verify_template_provenance(cursor, decision)
    if (not template or template['mode'] != 'CREATIVE_VALIDATION' or template['require_literary_qualification']
            or decision.get('task', {}).get('operation_id') != op
            or decision.get('selected', {}).get('candidate', {}).get('authorization_ref') != budget.get('cost_authorization_ref')):
        raise KernelError('QUALITY_REVIEW_RECOVERY_AUTHORIZATION_INVALID', 'Retain the original creative membership authorization')
    assets = {}
    for binding in source['input_asset_snapshot']:
        cursor.execute('SELECT a.asset_type,v.content,v.content_hash FROM authority_asset_version v JOIN authority_asset a USING(asset_id) WHERE v.asset_version_id=%s AND a.project_id=%s', [binding['asset_version_id'], source['project_id']])
        row = cursor.fetchone()
        if not row or row[2] != binding['content_hash'] or row[0] in assets:
            raise KernelError('QUALITY_REVIEW_RECOVERY_INPUT_DRIFT', 'Retain every exact uniquely typed frozen input')
        assets[row[0]] = (binding['asset_version_id'], row[1])
    incumbent_id, incumbent = assets['best_draft_candidate']
    from .candidate_selection import retained_candidate_evidence
    prior = retained_candidate_evidence(incumbent_id, incumbent)
    revision_id, revision = assets['draft_version']
    context_id, context = assets['context_bundle']
    result = ModelProviderResult.from_evidence(receipt)
    from novel_forge.modules.review.knowledge import knowledge_review_targets
    arguments = dict(draft_asset_version_id=prior.asset_version_id, review=incumbent['selected_review'],
        review_asset_version_id=prior.review_asset_version_id, revision=revision, revision_asset_version_id=revision_id,
        context_bundle_version_id=context_id, provider_evidence=_provider_evidence(result),
        project_id=source['project_id'], knowledge_targets=knowledge_review_targets(context))
    try:
        normalize_rereview_result(**arguments, result=result.output)
    except KernelError as error:
        if error.code != 'REVIEW_RESOLUTION_INVALID' or error.message != 'resolution checks must identify unique original diagnoses':
            raise KernelError('QUALITY_REVIEW_RECOVERY_NOT_APPLICABLE', 'Unrelated malformed output retains its recovery owner') from error
        diagnostic = {'code': error.code, 'reason': error.message}
    else:
        raise KernelError('QUALITY_REVIEW_RECOVERY_NOT_APPLICABLE', 'Reproduce the exact frozen legacy rejection')
    separated = separate_quality_checks(result.output, incumbent['selected_review'], revision)
    corrected = normalize_rereview_result(**arguments, result=separated)
    if not separated.get('quality_range_reassessment'):
        raise KernelError('QUALITY_REVIEW_RECOVERY_NOT_APPLICABLE', 'Require exact independently assessed Quality range evidence')
    corrected['quality_range_reassessment'] = separated['quality_range_reassessment']
    return {'contract_version': CONTRACT, 'source_operation_id': op, 'source_attempt': attempts[0],
        'source_effect_id': effect, 'source_request_hash': request_hash, 'source_dispatch_id': dispatch,
        'cost_authorization_ref': budget['cost_authorization_ref'], 'source_output_hash': snapshot_hash(result.output),
        'source_input_snapshot': source['input_asset_snapshot'], 'legacy_diagnostic': diagnostic,
        'corrected_content_hash': snapshot_hash(corrected), 'target_asset_version_id': revision_id,
        'book_id': template['book_id'], 'provider_invoked': False, 'strict_certification_eligible': False}, corrected


def materialize_retained_rereview(request):
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    from novel_forge.modules.command_kernel.retained_graph import BINDING, CONTRACT as GRAPH
    from .review_window import require_review_frontier
    binding = (request.command.get('preparation_report') or {}).get(BINDING) or {}
    proof = binding.get('retained_result') or {}
    with AuthorityUnitOfWork(request.database_url) as uow:
        c = uow.cursor
        c.execute('SELECT j.policy_evidence,j.source_snapshot,o.input_asset_snapshot,o.actor_id FROM authority_graph_continuation j JOIN authority_operation o ON o.root_operation_id=j.successor_root_operation_id WHERE o.operation_id=%s AND j.contract_version=%s', [request.operation_id, GRAPH])
        row = c.fetchone()
        if (not row or row[0] != binding or proof.get('contract_version') != CONTRACT
                or row[2] != proof.get('source_input_snapshot') or row[3] != row[1]['root']['actor_id']):
            raise KernelError('QUALITY_REVIEW_RECOVERY_BINDING_INVALID', 'Require exact native continuation, actor and frozen inputs')
        c.execute('SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s', [proof['source_operation_id']])
        actual, corrected = retained_quality_review(c, c.fetchone()[0])
        if actual != proof:
            raise KernelError('QUALITY_REVIEW_RECOVERY_RECEIPT_DRIFT', 'Retain the original independent Provider result')
    require_review_frontier(request)
    corrected['retained_result_derivation'] = {k: proof[k] for k in ('contract_version', 'source_operation_id', 'source_effect_id', 'source_dispatch_id', 'source_output_hash', 'source_request_hash', 'provider_invoked', 'strict_certification_eligible')}
    return corrected
