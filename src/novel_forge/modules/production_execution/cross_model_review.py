from __future__ import annotations

from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError

from .cost_routing import snapshot_hash


REVIEW_TASKS = frozenset({"narrative_semantic_evaluation", "review", "rereview", "canon_support"})
COUNTERPART = {"codex-cli": "deepseek", "deepseek": "codex-cli"}


def generator_identity(cursor: Any, *, project_id: str, book_id: str,
                       asset_version_id: str, content_hash: str) -> dict[str, Any]:
    cursor.execute(
        """SELECT e.external_effect_id,e.model_id,
                  e.request_payload #> '{_production_execution,capability_runtime,routing_decision}',
                  d.evidence
           FROM authority_operation_output_asset output
           JOIN authority_asset_version v ON v.asset_version_id=output.asset_version_id
           JOIN authority_external_effect e ON e.operation_id=output.operation_id
           JOIN authority_external_effect_dispatch d USING(external_effect_id)
           WHERE e.project_id=%s AND output.asset_version_id=%s AND v.content_hash=%s
             AND e.status='SUCCEEDED'
             AND e.request_payload #>> '{_production_execution,book_id}'=%s
             AND d.evidence->>'real_model_call'='true'""",
        [project_id, asset_version_id, content_hash, book_id],
    )
    identities = {}
    for effect_id, model_id, decision, evidence in cursor.fetchall():
        selected = (decision or {}).get("selected", {}).get("candidate", {})
        if (not selected or decision.get("bootstrap_authorization")
                or selected.get("model") != model_id or evidence.get("model_id") != model_id
                or evidence.get("provider_id") != selected.get("provider")
                or evidence.get("fixture_protocol_only")):
            raise KernelError("CROSS_MODEL_REVIEW_SOURCE_INVALID", "Generator identity must match its real native receipt")
        identities[effect_id] = {"provider": selected["provider"], "model": model_id,
            "model_revision": selected["model_revision"], "external_effect_id": effect_id,
            "routing_decision_id": decision["decision_id"], "receipt_hash": snapshot_hash(evidence)}
    if len(identities) != 1:
        raise KernelError("CROSS_MODEL_REVIEW_SOURCE_REQUIRED", "Exact target needs one successful real generator receipt")
    identity = next(iter(identities.values()))
    if identity["provider"] not in COUNTERPART:
        raise KernelError("CROSS_MODEL_REVIEW_PROVIDER_UNSUPPORTED", "Author must select an explicit reviewer policy for this provider")
    return {"schema_version": "cross-model-review.v1", "project_id": project_id, "book_id": book_id,
        "target_asset_version_id": asset_version_id, "target_content_hash": content_hash,
        "generator": identity, "required_reviewer_provider": COUNTERPART[identity["provider"]],
        "purpose": "AUTHOR_ADVISORY", "independent_literary_qualification": "NOT_PROVEN"}


def reviewer_rejection(contract: Mapping[str, Any], candidate: Mapping[str, Any]) -> str | None:
    generator = contract.get("generator", {})
    required = COUNTERPART.get(generator.get("provider"))
    if (not required or contract.get("required_reviewer_provider") != required
            or not generator.get("model_revision") or not contract.get("target_content_hash")):
        return "CROSS_MODEL_REVIEW_IDENTITY_INVALID"
    if candidate.get("provider") != required or candidate.get("model") == generator.get("model"):
        return "CROSS_MODEL_REVIEW_DIFFERENT_PROVIDER_REQUIRED"
    return None


def freeze_review_requirement(cursor: Any, *, project_id: str, book_id: str, operation_id: str,
                              task_type: str, request_input: Mapping[str, Any]) -> dict[str, Any]:
    target = (request_input.get("evaluation_target") or {}).get("candidate_asset_version_id")
    target = target or request_input.get("target_candidate_asset_version_id")
    target_types = {"review": ["draft_chapter"], "rereview": ["draft_version"],
                    "canon_support": ["canon_extraction"]}
    cursor.execute(
        """SELECT v.asset_version_id,v.content_hash,a.asset_type,v.content,op.command_payload
           FROM authority_operation op
           CROSS JOIN LATERAL jsonb_array_elements(op.input_asset_snapshot) input
           JOIN authority_asset_version v ON v.asset_version_id=input->>'asset_version_id'
             AND v.content_hash=input->>'content_hash'
           JOIN authority_asset a ON a.asset_id=v.asset_id AND a.project_id=op.project_id
           WHERE op.project_id=%s AND op.operation_id=%s""", [project_id, operation_id])
    rows = [row for row in cursor.fetchall() if row[0] == target] if target else [
        row for row in cursor.fetchall() if row[2] in target_types.get(task_type, [])]
    if len(rows) != 1:
        raise KernelError("CROSS_MODEL_REVIEW_TARGET_REQUIRED", "Review must resolve one exact frozen target")
    asset_id, digest, _, content, command = rows[0]
    if content.get("routing_eligibility") == "BENCHMARK_ONLY" or content.get("provider_generated") is False:
        raise KernelError("CROSS_MODEL_REVIEW_SOURCE_INVALID", "Diagnostic or authored input cannot claim real model generation")
    contract = generator_identity(cursor, project_id=project_id, book_id=book_id,
                                  asset_version_id=asset_id, content_hash=digest)
    if task_type == "narrative_semantic_evaluation" and command.get("payload", {}).get("evaluation_purpose") != "AUTHOR_ADVISORY":
        contract["purpose"] = "STRICT_QUALIFICATION"
    return contract
