from copy import deepcopy

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.domain import canonical_hash
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

CONTRACT = "chapter-complete-request-preparation-reuse.v1"


def retained_preparation(database_url, request, *, stage, payload):
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("""SELECT journal.policy_evidence,journal.source_failure_snapshot,
                current.command_payload,current.input_asset_snapshot,current.actor_id,current.definition_version
            FROM authority_saga_step_successor journal JOIN authority_operation current
              ON current.operation_id=journal.successor_operation_id
            WHERE journal.successor_operation_id=%s AND journal.project_id=%s
              AND journal.contract_version='kernel-failed-step-successor.v2'
              AND journal.policy_evidence->>'contract_version'='chapter-pure-generation-successor.v1'""",
            [request.operation_id, request.project_id])
        row = uow.cursor.fetchone()
        if not row:
            return None
        policy, failure, command, inputs, actor, version = row
        source = failure['operation']
        if (command != source['command_payload'] or inputs != source['input_asset_snapshot']
                or actor != source['actor_id'] or version != source['definition_version']
                or version != request.effective_definition_version):
            raise KernelError('CONTEXT_PREPARATION_REUSE_DRIFT', 'Prepared Context requires the exact native successor actor, command, inputs and contract')
        uow.cursor.execute("""SELECT external_effect_id,request_hash,request_payload FROM authority_external_effect
            WHERE project_id=%s AND operation_id=%s AND effect_type='model.invoke'
              AND request_payload->>'stage'=%s ORDER BY created_at,external_effect_id""",
            [request.project_id, source['operation_id'], stage])
        candidates = uow.cursor.fetchall()
        for effect_id, request_hash, frozen in candidates:
            source_input = dict(frozen.get('input') or {})
            projection = source_input.pop('_context_capacity_projection', None)
            if not projection or source_input != payload:
                continue
            proofs = policy.get('generation_isolations') or []
            if not any(proof.get('external_effect_id') == effect_id for proof in proofs):
                continue
            from novel_forge.modules.command_kernel.external_effect_runtime import _hash
            if _hash(frozen) != request_hash:
                raise KernelError('CONTEXT_PREPARATION_REUSE_DRIFT', 'Original prepared request failed its frozen digest')
            capability = (frozen.get('_production_execution') or {}).get('capability_runtime') or {}
            document = uow.repositories.asset_documents.require(project_id=request.project_id,
                asset_version_id=capability['provider_admission_asset_version_id'])
            if (document.content_hash != capability.get('provider_admission_content_hash')
                    or canonical_hash(document.content) != document.content_hash):
                raise KernelError('CONTEXT_PREPARATION_REUSE_DRIFT', 'Original preparation admission failed its frozen digest')
            admission = document.content['contract']
            snapshot = admission.get('provider_request_snapshot')
            if snapshot is None:
                continue
            from .request_snapshot import validate_provider_request_snapshot
            validate_provider_request_snapshot(snapshot, identity=admission['provider_request_identity'],
                envelope_hash=capability['provider_request_envelope_hash'])
            routes = {}
            for trace in [*projection.get('compression_receipt', {}).get('compression_trace', []),
                          *projection.get('retained_fidelity_traces', [])]:
                for assessment in trace.get('routing_assessments', []):
                    binding = assessment.get('task', {}).get('task', {}).get('capacity_bindings', {}).get(stage)
                    if binding:
                        routes[canonical_hash(binding['route'])] = binding['route']
            if len(routes) != 1:
                continue
            proof = {'contract_version': CONTRACT, 'source_operation_id': source['operation_id'],
                'source_external_effect_id': effect_id, 'source_request_hash': request_hash,
                'source_admission_asset_version_id': document.asset_version_id,
                'source_admission_content_hash': document.content_hash,
                'pack_snapshot_hash': capability['snapshot_hash'], 'projection_hash': canonical_hash(projection),
                'prepared_route': next(iter(routes.values())), 'provider_invoked_for_preparation_reuse': False,
                'remote_main_outcome': 'UNCHANGED_NOT_RECONCILED', 'status': 'CANDIDATE_REQUIRES_CURRENT_ADMISSION'}
            return deepcopy(projection), proof
    return None


def reusable_preparation(projection, proof, *, source_boundary, original, route_contract, measure):
    if (proof.get('contract_version') != CONTRACT or canonical_hash(projection) != proof.get('projection_hash')
            or projection.get('source_boundary') != source_boundary
            or proof.get('pack_snapshot_hash') != source_boundary.get('pack_snapshot_hash')
            or projection.get('original_hash') != canonical_hash(original)
            or proof.get('prepared_route') != route_contract):
        return False
    amount, limit = measure(projection)
    return amount <= limit
