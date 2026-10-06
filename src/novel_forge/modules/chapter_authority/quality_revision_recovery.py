from __future__ import annotations

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.cost_routing import snapshot_hash
from novel_forge.modules.revision.domain import (
    apply_quality_revision_result,
    han_characters,
)
from .model_effects import ModelProviderResult

CONTRACT = "chapter-quality-range-revalidation.v1"
RANGE_POLICY = "NAMED_DIAGNOSIS_UNION_V1"


def retained_quality_revision(cursor, source):
    from .handlers import _provider_evidence
    from novel_forge.modules.command_kernel.step_successor import (
        has_candidate_domain_outputs,
    )

    operation = source["operation_id"]
    project = source["project_id"]
    if (
        source["definition_name"] != "chapter.revision.apply"
        or source["definition_version"] != "3.9.4"
        or source["status"] != "FAILED_FINAL"
        or has_candidate_domain_outputs(cursor, operation)
    ):
        raise KernelError(
            "QUALITY_RANGE_RECOVERY_NOT_APPLICABLE",
            "Retain the exact non-producing legacy Quality revision failure",
        )
    cursor.execute(
        "SELECT to_jsonb(a) FROM authority_attempt a WHERE operation_id=%s ORDER BY attempt_number",
        [operation],
    )
    attempts = [row[0] for row in cursor.fetchall()]
    if (
        len(attempts) != 1
        or attempts[0]["status"] != "FAILED_FINAL"
        or attempts[0]["result"].get("error_code") != "REVISION_TARGETED_EDIT_INVALID"
    ):
        raise KernelError(
            "QUALITY_RANGE_RECOVERY_DIAGNOSTIC_REQUIRED",
            "Only the reproduced terminal range interpretation error may be revalidated",
        )
    cursor.execute(
        """SELECT e.external_effect_id,e.request_hash,e.request_payload,r.evidence,d.dispatch_id,receipt.payload->'evidence'
        FROM authority_external_effect e JOIN authority_budget_reservation r USING(external_effect_id)
        JOIN authority_external_effect_dispatch d USING(external_effect_id)
        JOIN authority_external_receipt receipt USING(dispatch_id)
        WHERE e.operation_id=%s AND e.status='SUCCEEDED' AND r.status='SETTLED'
          AND r.accounting_basis='ACCOUNT_ENTITLEMENT' AND e.effect_type='model.invoke'
          AND e.request_payload #>> '{_production_execution,attempt_id}'=%s
        ORDER BY receipt.received_at DESC""",
        [operation, attempts[0]["attempt_id"]],
    )
    receipts = cursor.fetchall()
    if len(receipts) != 1 or not receipts[0][3].get("cost_authorization_ref"):
        raise KernelError(
            "QUALITY_RANGE_RECOVERY_RECEIPT_REQUIRED",
            "Retain one genuinely successful settled membership result and original authorization",
        )
    effect, request_hash, payload, budget, dispatch, receipt = receipts[0]
    from novel_forge.modules.production_execution.execution_template import (
        verify_template_provenance,
    )

    decision = (
        payload.get("_production_execution", {})
        .get("capability_runtime", {})
        .get("routing_decision", {})
    )
    template = verify_template_provenance(cursor, decision)
    if (
        not template
        or template["mode"] != "CREATIVE_VALIDATION"
        or template["require_literary_qualification"]
        or decision.get("task", {}).get("operation_id") != operation
        or decision.get("selected", {}).get("candidate", {}).get("authorization_ref")
        != budget["cost_authorization_ref"]
    ):
        raise KernelError(
            "QUALITY_RANGE_RECOVERY_AUTHORIZATION_INVALID",
            "The original result must retain its trusted creative membership provenance",
        )
    result = ModelProviderResult.from_evidence(receipt)
    assets = []
    for binding in source["input_asset_snapshot"]:
        cursor.execute(
            """SELECT a.asset_type,v.content,v.content_hash FROM authority_asset_version v
            JOIN authority_asset a USING(asset_id) WHERE v.asset_version_id=%s AND a.project_id=%s""",
            [binding["asset_version_id"], project],
        )
        row = cursor.fetchone()
        if not row or row[2] != binding["content_hash"]:
            raise KernelError(
                "QUALITY_RANGE_RECOVERY_INPUT_DRIFT",
                "Retain every frozen input identity and hash",
            )
        assets.append((row[0], binding, row[1]))

    def require(kind):
        rows = [
            (binding["asset_version_id"], doc)
            for asset_type, binding, doc in assets
            if kind == asset_type
        ]
        if len(rows) != 1:
            raise KernelError(
                "QUALITY_RANGE_RECOVERY_INPUT_REQUIRED",
                "Exactly one native target, Quality disposition and Context are required",
            )
        return rows[0]

    target, revision = require("best_draft_candidate")
    quality_id, quality = require("quality_score_report")
    context_id, context = require("context_bundle")
    tasks = [
        (binding["asset_version_id"], doc)
        for kind, binding, doc in assets
        if kind == "revision_task"
    ]
    arguments = dict(
        project_id=project,
        revision=revision,
        revision_asset_version_id=target,
        quality=quality,
        quality_asset_version_id=quality_id,
        revision_tasks=tuple(item[1] for item in tasks),
        revision_task_asset_version_ids=tuple(item[0] for item in tasks),
        context_bundle_version_id=context_id,
        result=result.output,
        provider_evidence=_provider_evidence(result),
    )
    try:
        apply_quality_revision_result(**arguments)
    except KernelError as error:
        if (
            error.code != "REVISION_TARGETED_EDIT_INVALID"
            or error.message != "repair cannot change prose outside diagnosed locations"
        ):
            raise KernelError(
                "QUALITY_RANGE_RECOVERY_NOT_APPLICABLE",
                "Unrelated malformed results retain their original recovery owner",
            ) from error
        legacy_diagnostic = {"code": error.code, "reason": error.message}
    else:
        raise KernelError(
            "QUALITY_RANGE_RECOVERY_NOT_APPLICABLE",
            "The exact legacy diagnostic must remain reproducible",
        )
    corrected = apply_quality_revision_result(**arguments, range_policy=RANGE_POLICY)
    from novel_forge.modules.revision.domain import freeze_chapter_length_scope

    if (
        freeze_chapter_length_scope(
            corrected,
            source_asset_version_id=target,
            context=context,
            context_asset_version_id=context_id,
        )
        is not None
    ):
        raise KernelError(
            "QUALITY_RANGE_RECOVERY_LENGTH_INVALID",
            "Retained edits must satisfy the same frozen chapter length contract",
        )
    admission = quality.get("internal_admission") or {}
    if template["book_id"] != admission.get("book_id"):
        raise KernelError(
            "QUALITY_RANGE_RECOVERY_BOOK_MISMATCH",
            "Do not reuse a result from another production goal",
        )
    return {
        "contract_version": CONTRACT,
        "source_operation_id": operation,
        "source_attempt": attempts[0],
        "source_effect_id": effect,
        "source_request_hash": request_hash,
        "source_dispatch_id": dispatch,
        "cost_authorization_ref": budget["cost_authorization_ref"],
        "source_output_hash": snapshot_hash(result.output),
        "source_input_snapshot": source["input_asset_snapshot"],
        "legacy_diagnostic": legacy_diagnostic,
        "range_policy": RANGE_POLICY,
        "corrected_content_hash": snapshot_hash(corrected),
        "han_characters": han_characters(corrected["text"]),
        "target_asset_version_id": target,
        "book_id": admission["book_id"],
        "provider_invoked": False,
        "strict_certification_eligible": False,
    }, corrected


def materialize_retained_revision(request):
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    from novel_forge.modules.command_kernel.retained_graph import BINDING, CONTRACT

    binding = (request.command.get("preparation_report") or {}).get(BINDING) or {}
    with AuthorityUnitOfWork(request.database_url) as uow:
        c = uow.cursor
        c.execute(
            """SELECT j.policy_evidence,j.source_snapshot,o.input_asset_snapshot,o.actor_id
            FROM authority_graph_continuation j JOIN authority_operation o ON o.root_operation_id=j.successor_root_operation_id
            WHERE o.operation_id=%s AND j.contract_version=%s""",
            [request.operation_id, CONTRACT],
        )
        row = c.fetchone()
        if (
            not row
            or row[0] != binding
            or binding.get("retained_result", {}).get("contract_version")
            != CONTRACT_REVALIDATION
        ):
            raise KernelError(
                "QUALITY_RANGE_RECOVERY_BINDING_INVALID",
                "A pure result derivation requires its native terminal graph continuation",
            )
        proof = binding["retained_result"]
        if (
            row[2] != proof["source_input_snapshot"]
            or row[3] != row[1]["root"]["actor_id"]
        ):
            raise KernelError(
                "QUALITY_RANGE_RECOVERY_INPUT_DRIFT",
                "Retain the exact original actor and frozen revision inputs",
            )
        c.execute(
            "SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s",
            [proof["source_operation_id"]],
        )
        actual, corrected = retained_quality_revision(c, c.fetchone()[0])
        if actual != proof:
            raise KernelError(
                "QUALITY_RANGE_RECOVERY_RECEIPT_DRIFT",
                "Retain the original settled Provider result",
            )
    corrected["retained_result_derivation"] = {
        "contract_version": CONTRACT_REVALIDATION,
        "source_operation_id": proof["source_operation_id"],
        "source_effect_id": proof["source_effect_id"],
        "source_dispatch_id": proof["source_dispatch_id"],
        "source_output_hash": proof["source_output_hash"],
        "source_request_hash": proof["source_request_hash"],
        "provider_invoked": False,
        "strict_certification_eligible": False,
    }
    return corrected


CONTRACT_REVALIDATION = CONTRACT
