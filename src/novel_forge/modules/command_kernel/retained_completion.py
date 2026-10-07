# INVARIANT: completion references verified original effects without copying their lifecycle.

from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import EffectCommandContext, _read_verified_success
from novel_forge.modules.command_kernel.step_successor import require_live_chapter_frontier
from novel_forge.modules.production_execution.cost_routing import snapshot_hash
from novel_forge.storage.external_effect_repositories import ExternalEffectRepository

PROOF_KEYS = (
    "contract_version", "source_operation_id", "source_effect_id", "source_dispatch_id",
    "source_output_hash", "source_request_hash", "provider_invoked", "strict_certification_eligible",
)
KNOWN_RECEIPT = "chapter-known-receipt.v2"
GRAPH = "kernel-retained-graph-continuation.v2"
REFERENCE = "chapter-canon-reference-resolution-revalidation.v1"
NODES = {
    "chapter.draft.generate": "model.draft",
    "chapter.review.evaluate": "model.review",
    "chapter.canon.extract": "model.canon_extraction",
}


def _invalid():
    return KernelError("RETAINED_COMPLETION_EVIDENCE_INVALID", "Require exact native lineage, governed output and settled original receipt")


def _validate_proof(proof, output_proof, source, current):
    if (not isinstance(proof, dict) or not isinstance(output_proof, dict)
        or any(key not in proof for key in PROOF_KEYS)
        or output_proof != {key: proof[key] for key in PROOF_KEYS}
        or proof["provider_invoked"] is not False
        or proof["strict_certification_eligible"] is not False
        or source.get("operation_id") != proof["source_operation_id"]
        or source.get("definition_name") != current.get("definition_name")
        or source.get("definition_name") == "chapter.draft.generate" and source.get("definition_version") != "3.10.0"
        or any(source.get(key) != current.get(key) for key in ("project_id", "workspace_id", "actor_id"))
        or not source.get("actor_id")
        or source.get("status") not in {"FAILED_FINAL", "FAILED_RETRYABLE", "DEAD_LETTER"}):
        raise _invalid()


def retained_completion_evidence(uow: Any, operation: dict[str, Any], own_effects):
    definition = operation.get("definition_snapshot") or {}
    policy = definition.get("policy") or {}
    if (definition.get("definition_version") != "3.10.0"
        or operation.get("definition_name") not in NODES or own_effects
        or (policy.get("known_receipt_recovery") != KNOWN_RECEIPT
            and policy.get("retained_result_derivation") != GRAPH)):
        return []
    cursor = uow.cursor
    cursor.execute("SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s AND project_id=%s",
        [operation["operation_id"], operation["project_id"]])
    row = cursor.fetchone()
    if not row:
        raise _invalid()
    current = row[0]
    if current["definition_snapshot"] != definition or current["definition_version"] != "3.10.0":
        raise _invalid()
    cursor.execute("""SELECT j.policy_evidence,j.source_failure_snapshot,j.predecessor_operation_id,
        j.actor_id,j.saga_id FROM authority_saga_step_successor j
        WHERE j.successor_operation_id=%s AND j.project_id=%s AND j.contract_version='kernel-failed-step-successor.v2'""",
        [current["operation_id"], current["project_id"]])
    journal = cursor.fetchone()
    frozen_source = None
    if journal:
        proof, failure, predecessor, actor, saga_id = journal
        if proof.get("contract_version") != KNOWN_RECEIPT:
            return []
        frozen_source = failure["operation"]
        source_id = predecessor
        if (policy.get("known_receipt_recovery") != KNOWN_RECEIPT
            or source_id != proof.get("source_operation_id") or actor != current["actor_id"]
            or saga_id != current["saga_id"] or current["causation_operation_id"] != source_id
            or current["root_operation_id"] != frozen_source["root_operation_id"]
            or current["command_payload"] != frozen_source["command_payload"]
            or current["input_asset_snapshot"] != frozen_source["input_asset_snapshot"]
            or proof.get("completion_checks") != "UNCHANGED"
            or current["completion_contract_snapshot"] != frozen_source["completion_contract_snapshot"]):
            raise _invalid()
        output_key = "known_receipt_revalidation"
    else:
        if (operation["definition_name"] != "chapter.canon.extract"
            or policy.get("retained_result_derivation") != GRAPH):
            return []
        cursor.execute("""SELECT j.policy_evidence,j.source_snapshot,j.actor_id,j.successor_saga_id
            FROM authority_graph_continuation j WHERE j.successor_root_operation_id=%s
            AND j.project_id=%s AND j.contract_version=%s""",
            [current["root_operation_id"], current["project_id"], GRAPH])
        journal = cursor.fetchone()
        if not journal:
            return []
        binding, frozen, actor, saga_id = journal
        proof = binding.get("retained_result") or {}
        if proof.get("contract_version") != REFERENCE:
            return []
        if (proof != frozen.get("retained_result") or actor != current["actor_id"]
            or saga_id != current["saga_id"]
            or ((current.get("command_payload") or {}).get("preparation_report") or {}).get("retained_graph_continuation") != binding
            or current["input_asset_snapshot"] != proof.get("source_input_snapshot")):
            raise _invalid()
        source_id = proof.get("source_operation_id")
        output_key = "retained_result_derivation"
    cursor.execute("SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s AND project_id=%s",
        [source_id, current["project_id"]])
    row = cursor.fetchone()
    if not row or (frozen_source is not None and row[0] != frozen_source):
        raise _invalid()
    source = row[0]
    cursor.execute("""SELECT v.content FROM authority_operation_output_asset output
        JOIN authority_asset_version v USING(asset_version_id)
        JOIN authority_asset a ON a.asset_id=v.asset_id AND a.asset_id=output.asset_id
        WHERE output.operation_id=%s AND a.project_id=%s AND output.role='primary'
        AND output.content_hash=v.content_hash AND v.lifecycle='ACTIVE'
        AND v.eligibility='ELIGIBLE' AND v.governance='CLEAR'""",
        [current["operation_id"], current["project_id"]])
    proofs = [row[0].get(output_key) for row in cursor.fetchall() if row[0].get(output_key) is not None]
    if len(proofs) != 1:
        raise _invalid()
    _validate_proof(proof, proofs[0], source, current)
    require_live_chapter_frontier(cursor, root_id=current["root_operation_id"], project_id=current["project_id"])
    _require_settled_lineage(cursor, current, source)
    context = EffectCommandContext(operation_id=source_id, project_id=source["project_id"],
        actor_id=source["actor_id"], trace_id=source["trace_id"], correlation_id=source["correlation_id"])
    verified = _read_verified_success(uow, ExternalEffectRepository(cursor), context, proof["source_effect_id"])
    if (not verified or verified["budget_reservation_status"] != "SETTLED"
        or snapshot_hash(verified["provider_evidence"].get("result")) != proof["source_output_hash"]):
        raise _invalid()
    cursor.execute("""SELECT e.operation_id,e.request_hash,e.effect_type,d.dispatch_id,
        b.evidence->>'cost_authorization_ref',e.capability FROM authority_external_effect e
        JOIN authority_external_effect_dispatch d USING(external_effect_id)
        JOIN authority_budget_reservation b USING(external_effect_id)
        WHERE e.external_effect_id=%s AND e.project_id=%s AND d.generation=%s
        AND d.status='SUCCEEDED' AND b.reservation_id=%s AND b.status='SETTLED'""",
        [proof["source_effect_id"], current["project_id"], verified["generation"], verified["budget_reservation_id"]])
    row = cursor.fetchone()
    if (not row or row[:4] != (source_id, proof["source_request_hash"], "model.invoke", proof["source_dispatch_id"])
        or not row[4] or row[4] != proof.get("cost_authorization_ref")
        or row[5] != NODES[current["definition_name"]]
        or not uow.repositories.completion_contracts.has_cost(source_id)):
        raise _invalid()
    return [{"capability": row[5], "status": "SUCCEEDED", "source_operation_id": source_id}]


def _require_settled_lineage(cursor, current, source):
    from .budget_runtime import require_known_cli_lineage

    require_known_cli_lineage(cursor, project_id=current["project_id"], operation_id=current["operation_id"])
    roots = sorted({current["root_operation_id"], source["root_operation_id"]})
    cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_external_effect e
        JOIN authority_operation o USING(operation_id)
        LEFT JOIN authority_budget_reservation b USING(external_effect_id)
        WHERE o.root_operation_id=ANY(%s) AND (e.status IN
        ('PENDING','DISPATCHING','UNKNOWN','RECONCILIATION_REQUIRED') OR b.status IS DISTINCT FROM 'SETTLED')),
        EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id)
        JOIN authority_operation o USING(operation_id) WHERE o.root_operation_id=ANY(%s)
        AND o.operation_id<>%s AND l.released_at IS NULL AND l.expires_at>NOW()),
        EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=ANY(%s))""",
        [roots, roots, current["operation_id"], [*roots, source["operation_id"], current["operation_id"]]])
    if any(cursor.fetchone()):
        raise _invalid()
