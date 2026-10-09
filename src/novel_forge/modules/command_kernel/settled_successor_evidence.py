from __future__ import annotations

from types import SimpleNamespace

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import EffectCommandContext, _read_verified_success
from novel_forge.modules.production_execution.cost_routing import snapshot_hash
from novel_forge.storage.external_effect_repositories import ExternalEffectRepository

CONTRACTS = {
    'chapter-known-receipt.v2': {'chapter.memo.generate', 'chapter.draft.generate', 'chapter.review.evaluate', 'chapter.canon.extract'},
    'chapter-canon-span-successor.v2': {'chapter.canon.extract'},
    'chapter-canon-support-contract-successor.v1': {'chapter.canon.propose_changes'},
}
PROOF_KEYS = ('contract_version', 'source_operation_id', 'source_effect_id', 'source_dispatch_id',
              'source_output_hash', 'source_request_hash', 'provider_invoked', 'strict_certification_eligible')


def _require_binding(source, current, frozen, policy, *, predecessor_id=None):
    allowed_versions = {"3.10.0"}
    if source["definition_name"] == "chapter.memo.generate" and policy.get("character_reference_contract", {}).get("contract_version") == "frozen-character-references.v1":
        allowed_versions.add("3.10.1")
        if policy.get("completion_revalidation") == "settled-memo-completion.v1":
            allowed_versions.add("3.10.2")
    if source["definition_name"] == "chapter.draft.generate" and policy.get("scene_evidence_union_revalidation") == "scene-evidence-union.v1":
        allowed_versions.add("3.10.1")
    if (source != frozen or source['status'] not in {'FAILED_FINAL', 'DEAD_LETTER'}
        or current['status'] != 'SUCCEEDED' or current['definition_version'] not in allowed_versions
        or source['definition_name'] not in CONTRACTS.get(policy.get('contract_version'), set())
        or current['causation_operation_id'] != (predecessor_id or source['operation_id'])
        or any(current.get(k) != source.get(k) for k in ('project_id', 'workspace_id', 'actor_id',
            'root_operation_id', 'saga_id', 'step_key', 'definition_name', 'command_payload', 'input_asset_snapshot'))):
        raise KernelError('SETTLED_SUCCESSOR_EVIDENCE_DRIFT', 'Require exact immutable source and completed current native successor')


def _require_rejection(effect, reservation, proof, receipt):
    result = (effect.get('last_error') or {}).get('production_execution', {}).get('execution_result', {})
    if (proof.get('request_hash') != effect['request_hash'] or proof.get('effect_status') != effect['status']
        or effect['status'] not in {'FAILED_FINAL', 'FAILED_RETRYABLE'}
        or reservation['status'] != proof.get('reservation_status') or reservation['status'] != 'SETTLED'
        or reservation['accounting_basis'] != proof.get('accounting_basis') or reservation['accounting_basis'] != 'ACCOUNT_ENTITLEMENT'
        or not reservation['evidence'].get('cost_authorization_ref')
        or receipt is None or receipt[0] != proof.get('process_receipt_hash')
        or result.get('process_receipt_ref') != 'authority-asset-version:' + str(proof.get('process_receipt_asset_version_id'))
        or proof.get('outcome') not in {'PROVIDER_SCHEMA_REJECTED', 'COMPLETED_OUTPUT_SCHEMA_FAILURE'}):
        raise KernelError('SETTLED_SUCCESSOR_REJECTION_DRIFT', 'Bind the exact terminal request, settled accounting and immutable process receipt')
    content = receipt[1]
    payload = content.get('payload') or {}
    if (content.get('kind') != 'process-receipt' or content.get('contract_version') != 'authority-execution-evidence.v1'
        or payload.get('operation_id') != effect['operation_id']
        or payload.get('execution_id') != 'chapter-execution:' + effect['external_effect_id']
        or payload.get('status') != ('FAILED' if proof['outcome'] == 'PROVIDER_SCHEMA_REJECTED' else 'SUCCEEDED')):
        raise KernelError('SETTLED_SUCCESSOR_REJECTION_DRIFT', 'Require native process outcome from the original owner')


def verified_successor_effects(cursor, operation_ids):
    cursor.execute('''SELECT to_jsonb(source),to_jsonb(current),j.source_failure_snapshot,j.policy_evidence
        FROM authority_saga_step_successor j JOIN authority_operation source ON source.operation_id=j.predecessor_operation_id
        JOIN authority_operation current ON current.operation_id=j.successor_operation_id
        JOIN authority_saga_step active ON active.operation_id=current.operation_id AND active.saga_id=j.saga_id
        WHERE source.operation_id=ANY(%s) AND j.contract_version='kernel-failed-step-successor.v2'
        AND j.project_id=source.project_id AND j.actor_id=source.actor_id AND j.saga_id=source.saga_id
        AND current.status='SUCCEEDED' AND current.definition_version IN ('3.10.0','3.10.1')
        AND j.policy_evidence->>'contract_version'=ANY(%s)''', [operation_ids, list(CONTRACTS)])
    journals = [(source, current, frozen, policy, None) for source, current, frozen, policy in cursor.fetchall()]
    cursor.execute("""SELECT to_jsonb(source),to_jsonb(current),first.source_failure_snapshot,last.policy_evidence,
        to_jsonb(predecessor),last.source_failure_snapshot
        FROM authority_saga_step_successor first
        JOIN authority_operation source ON source.operation_id=first.predecessor_operation_id
        JOIN authority_operation predecessor ON predecessor.operation_id=first.successor_operation_id
        JOIN authority_saga_step_successor last ON last.predecessor_operation_id=predecessor.operation_id
        JOIN authority_operation current ON current.operation_id=last.successor_operation_id
        JOIN authority_saga_step active ON active.operation_id=current.operation_id AND active.saga_id=last.saga_id
        WHERE source.operation_id=ANY(%s) AND source.definition_name='chapter.memo.generate'
          AND source.definition_version='3.10.0' AND predecessor.definition_version='3.10.1'
          AND current.definition_version='3.10.2' AND current.status='SUCCEEDED'
          AND first.contract_version='kernel-failed-step-successor.v2'
          AND last.contract_version='kernel-failed-step-successor.v2'""", [operation_ids])
    for source, current, frozen, policy, predecessor, last_frozen in cursor.fetchall():
        from novel_forge.modules.chapter_authority.memo_recovery import original_memo_source
        if (last_frozen["operation"] != predecessor
            or original_memo_source(cursor, predecessor, policy) != frozen["operation"]
            or policy.get("completion_revalidation") != "settled-memo-completion.v1"
            or any(predecessor[k] != current[k] for k in ("project_id", "workspace_id", "actor_id", "saga_id"))):
            raise KernelError('SETTLED_SUCCESSOR_EVIDENCE_DRIFT', 'Require both exact immutable Memo repair generations')
        journals.append((source, current, frozen, policy, predecessor["operation_id"]))
    authorized = {}
    for source, current, frozen, policy, predecessor_id in journals:
        _require_binding(source, current, frozen['operation'], policy, predecessor_id=predecessor_id)
        cursor.execute('''SELECT v.content FROM authority_operation_output_asset output
            JOIN authority_asset_version v USING(asset_version_id) JOIN authority_asset a ON a.asset_id=v.asset_id
            WHERE output.operation_id=%s AND output.role='primary' AND a.project_id=%s
            AND output.content_hash=v.content_hash AND v.lifecycle='ACTIVE' AND v.eligibility='ELIGIBLE' AND v.governance='CLEAR' ''',
            [current['operation_id'], current['project_id']])
        outputs = cursor.fetchall()
        if len(outputs) != 1:
            raise KernelError('SETTLED_SUCCESSOR_EVIDENCE_DRIFT', 'Require one governed current domain output')
        if policy['contract_version'] == 'chapter-known-receipt.v2':
            if (any(k not in policy for k in PROOF_KEYS)
                or outputs[0][0].get('known_receipt_revalidation') != {k: policy[k] for k in PROOF_KEYS}
                or policy['provider_invoked'] is not False or policy['strict_certification_eligible'] is not False):
                raise KernelError('SETTLED_SUCCESSOR_EVIDENCE_DRIFT', 'Require exact materialized known receipt proof')
        cursor.execute('''SELECT to_jsonb(e),to_jsonb(b),to_jsonb(a) FROM authority_external_effect e
            JOIN authority_budget_reservation b USING(external_effect_id)
            JOIN authority_attempt a ON a.attempt_id=e.request_payload #>> '{_production_execution,attempt_id}'
            AND a.operation_id=e.operation_id WHERE e.operation_id=%s ORDER BY e.external_effect_id''', [source['operation_id']])
        effects = cursor.fetchall()
        proofs = {p['external_effect_id']: p for p in policy.get('schema_rejection_receipts', [])}
        context = EffectCommandContext(operation_id=source['operation_id'], project_id=source['project_id'],
            actor_id=source['actor_id'], trace_id=source['trace_id'], correlation_id=source['correlation_id'])
        for effect, budget, attempt in effects:
            if budget['status'] != 'SETTLED' or budget['accounting_basis'] != 'ACCOUNT_ENTITLEMENT' or not budget['evidence'].get('cost_authorization_ref'):
                raise KernelError('SETTLED_SUCCESSOR_EVIDENCE_DRIFT', 'Original usage remains settled and authorized')
            if effect['status'] == 'SUCCEEDED':
                verified = _read_verified_success(SimpleNamespace(cursor=cursor), ExternalEffectRepository(cursor), context, effect['external_effect_id'])
                if not verified or verified['budget_reservation_status'] != 'SETTLED':
                    raise KernelError('SETTLED_SUCCESSOR_EVIDENCE_DRIFT', 'Original receipt must remain Kernel verified')
                if policy['contract_version'] == 'chapter-known-receipt.v2':
                    cursor.execute('SELECT dispatch_id FROM authority_external_effect_dispatch WHERE external_effect_id=%s AND generation=%s AND status=\'SUCCEEDED\'', [effect['external_effect_id'], verified['generation']])
                    expected = policy
                    if source['definition_name'] == 'chapter.memo.generate':
                        matches = [r for r in policy.get('settled_memo_receipts', []) if r.get('source_effect_id') == effect['external_effect_id']]
                        if len(matches) != 1:
                            raise KernelError('SETTLED_SUCCESSOR_EVIDENCE_DRIFT', 'Require an exact proof for every original Memo receipt')
                        expected = matches[0]
                    if (effect['external_effect_id'] != expected['source_effect_id'] or effect['request_hash'] != expected['source_request_hash']
                        or snapshot_hash(verified['provider_evidence'].get('result')) != expected['source_output_hash']
                        or cursor.fetchone() != (expected['source_dispatch_id'],)):
                        raise KernelError('SETTLED_SUCCESSOR_EVIDENCE_DRIFT', 'Original dispatch, output and request remain exact')
            else:
                proof = proofs.get(effect['external_effect_id']) or {}
                cursor.execute('SELECT v.content_hash,v.content FROM authority_asset_version v JOIN authority_asset a USING(asset_id) WHERE v.asset_version_id=%s AND a.project_id=%s', [proof.get('process_receipt_asset_version_id'), source['project_id']])
                _require_rejection(effect, budget, proof, cursor.fetchone())
                if proof['outcome'] == 'COMPLETED_OUTPUT_SCHEMA_FAILURE':
                    cursor.execute('SELECT v.content_hash FROM authority_asset_version v JOIN authority_asset a USING(asset_id) WHERE v.asset_version_id=%s AND a.project_id=%s', [proof.get('raw_output_asset_version_id'), source['project_id']])
                    if cursor.fetchone() != (proof.get('raw_output_hash'),):
                        raise KernelError('SETTLED_SUCCESSOR_REJECTION_DRIFT', 'Original rejected output identity remains immutable')
            authorized[effect['external_effect_id']] = {'successor_operation_id': current['operation_id'],
                'operation_id': source['operation_id'], 'attempt_id': attempt['attempt_id'], 'attempt_status': attempt['status'],
                'effect': [effect['external_effect_id'], effect['request_hash'], effect['status'], budget['status'], budget['accounting_basis'], budget['evidence']['cost_authorization_ref']]}
    return authorized


def acknowledge_successor_effects(cursor, effects, operation_ids):
    authorized = verified_successor_effects(cursor, operation_ids)
    for item in effects:
        proof = authorized.get(item['external_effect_id'])
        if (proof and item['operation_id'] == proof['operation_id'] and item['attempt_id'] == proof['attempt_id']
            and item['attempt_status'] == proof['attempt_status'] and item['status'] == proof['effect'][2]):
            item['settled_candidate_superseded' if item['status'] == 'SUCCEEDED' else 'settled_nonproducing_superseded'] = True
            item['successor_operation_id'] = proof['successor_operation_id']
