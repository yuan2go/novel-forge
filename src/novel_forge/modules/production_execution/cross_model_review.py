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
                  d.evidence,r.payload_hash,r.payload,r.status
           FROM authority_operation_output_asset output
           JOIN authority_asset_version v ON v.asset_version_id=output.asset_version_id
           JOIN authority_asset a ON a.asset_id=v.asset_id
           JOIN authority_operation op ON op.operation_id=output.operation_id
           JOIN authority_external_effect e ON e.operation_id=output.operation_id
           JOIN LATERAL (
             SELECT dispatch_id,evidence FROM authority_external_effect_dispatch
             WHERE external_effect_id=e.external_effect_id AND status='SUCCEEDED'
             ORDER BY generation DESC LIMIT 1
           ) d ON true
           LEFT JOIN authority_external_receipt r ON r.dispatch_id=d.dispatch_id
           WHERE e.project_id=%s AND output.asset_version_id=%s AND v.content_hash=%s
             AND e.status='SUCCEEDED'
             AND op.status='SUCCEEDED' AND op.project_id=e.project_id AND a.project_id=e.project_id
             AND output.content_hash=v.content_hash
             AND e.request_payload #>> '{_production_execution,book_id}'=%s
             AND d.evidence->>'real_model_call'='true'""",
        [project_id, asset_version_id, content_hash, book_id],
    )
    identities = {}
    for effect_id, model_id, decision, evidence, receipt_hash, receipt, receipt_status in cursor.fetchall():
        if (effect_id in identities or receipt_status != "VERIFIED"
                or not isinstance(receipt, dict) or not isinstance(evidence, dict)
                or not evidence or receipt.get("evidence") != evidence
                or snapshot_hash(evidence) != receipt_hash):
            raise KernelError("CROSS_MODEL_REVIEW_SOURCE_INVALID", "Generator requires one intact verified success receipt")
        if not isinstance(decision, dict) or not isinstance(evidence, dict):
            raise KernelError("CROSS_MODEL_REVIEW_SOURCE_INVALID", "Generator receipt and routing identity must be native objects")
        selected = (decision.get("selected") or {}).get("candidate", {})
        if (not isinstance(selected, dict) or not all(selected.get(key) for key in ("provider", "model", "model_revision"))
                or not decision.get("decision_id") or decision.get("bootstrap_authorization")
                or selected.get("model") != model_id or evidence.get("model_id") != model_id
                or evidence.get("provider_id") != selected.get("provider")
                or evidence.get("fixture_protocol_only")):
            raise KernelError("CROSS_MODEL_REVIEW_SOURCE_INVALID", "Generator identity must match its real native receipt")
        identities[effect_id] = {"provider": selected["provider"], "model": model_id,
            "model_revision": selected["model_revision"], "external_effect_id": effect_id,
            "routing_decision_id": decision["decision_id"], "receipt_hash": snapshot_hash(evidence)}
    if len(identities) != 1:
        raise KernelError("CROSS_MODEL_REVIEW_SOURCE_REQUIRED",
            "No unique real generator receipt for this exact target; use native author adoption or edition lineage for edited prose, and reconcile ambiguous Effects")
    identity = next(iter(identities.values()))
    if identity["provider"] not in COUNTERPART:
        raise KernelError("CROSS_MODEL_REVIEW_PROVIDER_UNSUPPORTED", "Author must select an explicit reviewer policy for this provider")
    return {"schema_version": "cross-model-review.v1", "project_id": project_id, "book_id": book_id,
        "target_asset_version_id": asset_version_id, "target_content_hash": content_hash,
        "generator": identity, "required_reviewer_provider": COUNTERPART[identity["provider"]],
        "purpose": "AUTHOR_ADVISORY", "independent_literary_qualification": "NOT_PROVEN"}


def reviewer_rejection(contract: Mapping[str, Any], candidate: Mapping[str, Any]) -> str | None:
    if contract.get("schema_version") not in {None, "cross-model-review.v1", "cross-model-review.v2"}:
        return "CROSS_MODEL_REVIEW_IDENTITY_INVALID"
    if contract.get("schema_version") == "cross-model-review.v2":
        source = contract.get("source", {})
        reviewer = contract.get("authorized_reviewer", {})
        if (contract.get("reviewer_policy") != "EXPLICIT_AUTHORIZED_REVIEWER"
                or source.get("kind") not in {"AUTHOR_ORIGINAL", "MODEL_EDITED_BY_AUTHOR", "EDITION_MIXED"}
                or not contract.get("target_asset_version_id") or not contract.get("target_content_hash")
                or contract.get("source_hash") != snapshot_hash(source)):
            return "CROSS_MODEL_REVIEW_IDENTITY_INVALID"
        if (reviewer.get("provider") not in COUNTERPART
                or not all(reviewer.get(key) for key in ("candidate_id", "model", "model_revision"))):
            return "CROSS_MODEL_REVIEW_SOURCE_POLICY_REQUIRED"
        if any(candidate.get(key) != reviewer[key] for key in ("candidate_id", "provider", "model", "model_revision")):
            return "CROSS_MODEL_REVIEW_AUTHORIZED_REVIEWER_REQUIRED"
        return None
    generator = contract.get("generator", {})
    required = COUNTERPART.get(generator.get("provider"))
    if (not required or contract.get("required_reviewer_provider") != required
            or not generator.get("model_revision") or not contract.get("target_content_hash")):
        return "CROSS_MODEL_REVIEW_IDENTITY_INVALID"
    if candidate.get("provider") != required or candidate.get("model") == generator.get("model"):
        return "CROSS_MODEL_REVIEW_DIFFERENT_PROVIDER_REQUIRED"
    return None


def freeze_review_requirement(cursor: Any, *, project_id: str, book_id: str, operation_id: str,
                              task_type: str, request_input: Mapping[str, Any],
                              authorized_reviewer: Mapping[str, Any] | None = None) -> dict[str, Any]:
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
    asset_id, digest, asset_type, content, command = rows[0]
    if task_type in target_types and asset_type not in target_types[task_type]:
        raise KernelError("CROSS_MODEL_REVIEW_TARGET_REQUIRED", "Review task must retain its own target type")
    if content.get("routing_eligibility") == "BENCHMARK_ONLY":
        raise KernelError("CROSS_MODEL_REVIEW_SOURCE_INVALID", "Diagnostic sources cannot enter production review")
    if task_type == "review" and content.get("author_draft_adoption"):
        from .review_sources import adopted_source
        source = adopted_source(cursor, project_id=project_id, book_id=book_id,
            asset_version_id=asset_id, content_hash=digest, content=content)
        reviewer = dict(authorized_reviewer or {})
        contract = {"schema_version": "cross-model-review.v2", "project_id": project_id, "book_id": book_id,
            "target_asset_version_id": asset_id, "target_content_hash": digest,
            "source": source, "source_hash": snapshot_hash(source),
            "reviewer_policy": "EXPLICIT_AUTHORIZED_REVIEWER", "authorized_reviewer": reviewer,
            "purpose": "AUTHOR_ADVISORY", "independent_literary_qualification": "NOT_PROVEN"}
        return contract
    if content.get("provider_generated") is False:
        raise KernelError("CROSS_MODEL_REVIEW_SOURCE_INVALID", "Diagnostic or authored input cannot claim real model generation")
    contract = generator_identity(cursor, project_id=project_id, book_id=book_id,
                                  asset_version_id=asset_id, content_hash=digest)
    if task_type == "canon_support":
        from novel_forge.modules.chapter_quality_authority.canon_support_reference import source_contract
        cursor.execute("SELECT input_asset_snapshot FROM authority_operation WHERE project_id=%s AND operation_id=%s",
                       [project_id, operation_id])
        support = source_contract(cursor, project_id=project_id, input_versions=cursor.fetchone()[0])
        contract["support_source"] = {key: support[key] for key in (
            "target_asset_version_id", "target_content_hash", "source_asset_version_id", "source_content_hash")}
    if task_type == "narrative_semantic_evaluation" and command.get("payload", {}).get("evaluation_purpose") != "AUTHOR_ADVISORY":
        contract["purpose"] = "STRICT_QUALIFICATION"
    return contract
