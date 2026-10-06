from __future__ import annotations

import json
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.execution_template import MODE, verify_template_provenance
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .domain import QUALITY_GROUPS


def quality_receipt(cursor: Any, *, project_id: str, effect_id: str, target: str) -> dict[str, Any] | None:
    cursor.execute("""SELECT request_payload,operation_id FROM authority_external_effect
        WHERE project_id=%s AND external_effect_id=%s AND status='SUCCEEDED' AND effect_type='model.invoke'""", [project_id, effect_id])
    row = cursor.fetchone()
    if not row:
        raise KernelError("VALIDATION_QUALITY_EFFECT_REQUIRED", effect_id)
    payload, operation = row
    decision = payload.get("_production_execution", {}).get("capability_runtime", {}).get("routing_decision", {})
    template = verify_template_provenance(cursor, decision)
    if not template or template["mode"] != MODE or template["require_literary_qualification"]:
        return None
    stage = payload.get("stage", "")
    if (stage.removeprefix("quality_") not in QUALITY_GROUPS or decision.get("status") != "SELECTED"
            or decision["task"]["operation_id"] != operation
            or payload.get("input", {}).get("quality_context", {}).get("target_revision_asset_version_id") != target):
        raise KernelError("VALIDATION_QUALITY_SCOPE_MISMATCH", effect_id)
    return {"version": "creative-quality-receipt.v1", "mode": MODE, "project_id": project_id,
            "book_id": template["book_id"], "target_asset_version_id": target,
            "stage": stage, "operation_id": operation, "external_effect_id": effect_id,
            "policy_snapshot": decision["task"]["policy_snapshot"], "literary_qualification": "NOT_RUN"}


def model_quality_receipt(request: Any, result: Any, *, target: str) -> dict[str, Any] | None:
    native = result.to_evidence().get("production_execution", {}).get("execution_request", {})
    if not request.database_url or not native.get("external_effect_id"):
        return None
    if native.get("operation_id") != request.operation_id:
        raise KernelError("VALIDATION_QUALITY_SCOPE_MISMATCH", request.operation_id)
    with AuthorityUnitOfWork(request.database_url) as uow:
        return quality_receipt(uow.cursor, project_id=request.project_id,
            effect_id=native["external_effect_id"], target=target)


def assess_internal_quality(*, groups: list[Mapping[str, Any]], target: str) -> dict[str, Any] | None:
    receipts = [group.get("validation_receipt") for group in groups]
    if not any(receipts):
        return None
    if (not all(receipts) or len(groups) != len(QUALITY_GROUPS) or {group["group"] for group in groups} != set(QUALITY_GROUPS)
            or len({receipt["book_id"] for receipt in receipts}) != 1
            or any(receipt["target_asset_version_id"] != target for receipt in receipts)):
        raise KernelError("VALIDATION_QUALITY_COVERAGE_REQUIRED", target)
    blocked = []
    observations = []
    for group in groups:
        by_dimension = {row["dimension"]: row for row in group["dimensions"]}
        if set(by_dimension) != set(QUALITY_GROUPS[group["group"]]):
            raise KernelError("VALIDATION_QUALITY_COVERAGE_REQUIRED", group["group"])
        for dimension, row in by_dimension.items():
            verdict = row.get("semantic_verdict", row["gate_status"])
            if row.get("gate_status") == "NOT_APPLICABLE" and row.get("calibration_status") == "WORK_APPLICABILITY":
                observations.append({"dimension": dimension, "status": "NOT_APPLICABLE"})
                continue
            if dimension.endswith("_evidence") and row.get("calibration_status") == "PROVIDER_UNCALIBRATED":
                observations.append({"dimension": dimension, "status": "NOT_RUN", "reason": "literary calibration excluded by template"})
                continue
            located = bool(row.get("evidence_locations"))
            passing = verdict in {"PASSED", "PASSED_WITH_WARNINGS", "PASSED_WITH_UNCALIBRATED"}
            threshold = row.get("threshold")
            measured = row.get("threshold_evaluation")
            floor = threshold is None or measured == "PASSED" or row.get("calibration_status") == "DETERMINISTIC" and passing
            valid = passing and located and floor and (row.get("provider_verified") is True or row.get("calibration_status") == "DETERMINISTIC")
            if not valid:
                blocked.append(dimension)
            observations.append({"dimension": dimension, "status": "OBSERVED" if valid else "BLOCKED",
                "semantic_verdict": verdict, "threshold_evaluation": measured,
                "literary_qualification": "NOT_RUN"})
    return {"version": "creative-quality-admission.v1", "mode": MODE, "target_asset_version_id": target,
            "book_id": receipts[0]["book_id"], "status": "INTERNAL_ADMITTED" if not blocked else "BLOCKED",
            "blocked_dimensions": blocked, "observations": observations, "receipts": receipts,
            "literary_qualification": "NOT_RUN", "strict_certification_eligible": False}


def verify_internal_quality(database_url: str, admission: Mapping[str, Any], *, project_id: str, book_id: str | None = None) -> None:
    if (admission.get("version") != "creative-quality-admission.v1" or admission.get("mode") != MODE
            or admission.get("status") != "INTERNAL_ADMITTED" or not admission.get("receipts")
            or admission.get("blocked_dimensions") or admission.get("strict_certification_eligible") is not False
            or book_id is not None and admission.get("book_id") != book_id):
        raise KernelError("VALIDATION_QUALITY_ADMISSION_REQUIRED", str(admission.get("target_asset_version_id")))
    with AuthorityUnitOfWork(database_url) as uow:
        groups = []
        for receipt in admission["receipts"]:
            actual = quality_receipt(uow.cursor, project_id=project_id, effect_id=receipt["external_effect_id"], target=admission["target_asset_version_id"])
            if actual != receipt:
                raise KernelError("VALIDATION_QUALITY_PROVENANCE_INVALID", receipt["external_effect_id"])
            uow.cursor.execute("""SELECT v.content FROM authority_asset_version v
                JOIN authority_asset a USING(asset_id)
                WHERE a.project_id=%s AND a.asset_type='chapter_quality_group_report'
                  AND v.content->'validation_receipt'=%s::jsonb""", [project_id, json.dumps(receipt)])
            rows = uow.cursor.fetchall()
            if len(rows) != 1:
                raise KernelError("VALIDATION_QUALITY_GROUP_REQUIRED", receipt["external_effect_id"])
            groups.append(rows[0][0])
        expected = assess_internal_quality(groups=groups, target=admission["target_asset_version_id"])
        if expected != dict(admission):
            raise KernelError("VALIDATION_QUALITY_ADMISSION_TAMPERED", admission["target_asset_version_id"])
