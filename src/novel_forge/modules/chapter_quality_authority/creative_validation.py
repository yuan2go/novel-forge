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


def assess_internal_quality(*, groups: list[Mapping[str, Any]], target: str, disposition_version: int = 1) -> dict[str, Any] | None:
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
            if disposition_version == 2 and (row.get("fixture") or row.get("calibration_status") == "FIXTURE_UNCALIBRATED"):
                valid = False
            if not valid:
                blocked.append(dimension)
            observations.append({"dimension": dimension, "status": "OBSERVED" if valid else "BLOCKED",
                "semantic_verdict": verdict, "threshold_evaluation": measured,
                "literary_qualification": "NOT_RUN"})
    return {"version": f"creative-quality-admission.v{disposition_version}", "mode": MODE, "target_asset_version_id": target,
            "book_id": receipts[0]["book_id"], "status": "INTERNAL_ADMITTED" if not blocked else "BLOCKED",
            "blocked_dimensions": blocked, "observations": observations, "receipts": receipts,
            "literary_qualification": "NOT_RUN", "strict_certification_eligible": False}


def verify_internal_quality(database_url: str, admission: Mapping[str, Any], *, project_id: str, book_id: str | None = None) -> None:
    if (admission.get("version") not in {"creative-quality-admission.v1", "creative-quality-admission.v2", "creative-quality-admission.v3"} or admission.get("mode") != MODE
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
        expected = assess_internal_quality(groups=groups, target=admission["target_asset_version_id"], disposition_version=2 if admission["version"].endswith("v2") else 1)
        if admission["version"] == "creative-quality-admission.v3":
            constraints = receipt_work_constraints(database_url, project_id=project_id,
                receipts=admission["receipts"], target=admission["target_asset_version_id"])
            expected = assess_coordinated_internal_quality(groups=groups,
                target=admission["target_asset_version_id"], work_constraints=constraints)
        if expected != dict(admission):
            raise KernelError("VALIDATION_QUALITY_ADMISSION_TAMPERED", admission["target_asset_version_id"])


def internal_required_actions(*, admission, evidence_reports, target):
    actions = []
    for report in evidence_reports:
        dimension = report['dimension']
        if dimension not in admission['blocked_dimensions']:
            continue
        located_failure = (report.get('semantic_verdict') == 'FAILED'
            and report.get('provider_verified') is True and not report.get('fixture')
            and report.get('target_asset_version_id') == target
            and any(location.get('quote') for location in report.get('evidence_locations', [])))
        action = 'LOCAL_REPAIR' if located_failure else 'EVIDENCE_REASSESSMENT'
        actions.append({'observation': dimension, 'evidence_asset_version_ids': [],
            'issue': {'code': f'QUALITY_{dimension.upper()}_FAILED', 'severity': 'BLOCKING', 'status': 'OPEN'},
            'required_action': action, 'permitted_change_scope': 'CHAPTER' if located_failure else 'EVIDENCE_ONLY',
            'required_authority': 'CHAPTER_AUTHORITY' if located_failure else 'QUALITY_AUTHORITY',
            'preserved_invariants': ['accepted_canon', 'executed_chapter_history', 'active_parent_plan_identity'],
            'reevaluation_gate': report.get('gate_type', ''), 'disposition_contract': 'creative-quality-disposition.v2',
            'strict_certification_eligible': False})
    return actions


def receipt_work_constraints(database_url, *, project_id, receipts, target):
    from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
    receipt = next(row for row in receipts if row["stage"] == "quality_platform")
    with AuthorityUnitOfWork(database_url) as u:
        if quality_receipt(u.cursor, project_id=project_id, effect_id=receipt["external_effect_id"], target=target) != receipt:
            raise KernelError("VALIDATION_QUALITY_SCOPE_MISMATCH", target)
        u.cursor.execute("SELECT request_payload->'input'->'quality_context'->'compiled_platform_policy' FROM authority_external_effect WHERE external_effect_id=%s", [receipt["external_effect_id"]])
        policy = u.cursor.fetchone()[0] or {}
    rules = policy.get("chapter_length_rules") or {}
    if not rules or rules.get("status") == "INSUFFICIENT_EVIDENCE":
        return ()
    minimum, maximum = rules.get("minimum"), rules.get("maximum")
    if type(minimum) is not int or type(maximum) is not int or not 0 < minimum <= maximum:
        raise KernelError("CHAPTER_LENGTH_POLICY_INVALID", "Frozen bounds must be positive ordered integers")
    unit = rules.get("unit", "UNICODE_CODE_POINTS_V1")
    if unit not in {"UNICODE_CODE_POINTS_V1", "HAN_CHARACTERS_V1"}:
        raise KernelError("CHAPTER_LENGTH_UNIT_INVALID", unit)
    text = AuthorityAssetQuery(database_url).require(project_id=project_id, asset_version_id=target).content["text"]
    observed = measure_length(text, unit)
    return ({"dimension": "chapter_length", "status": "PASSED" if minimum <= observed <= maximum else "FAILED",
        "source_policy": policy["source_asset_version_id"], "policy_digest": policy["policy_digest"],
        "target_asset_version_id": target, "unit": unit, "minimum": minimum, "maximum": maximum, "observed": observed,
        "compatibility": "EXPLICIT_UNIT" if "unit" in rules else "LEGACY_CHARACTER_BOUNDS_UNICODE"},)


def apply_work_constraint_actions(content, *, admission, revision, target, canon):
    from novel_forge.modules.review.diagnostics import prose_hash
    content["required_actions"] = [action for action in content["required_actions"]
        if action["observation"] in admission["blocked_dimensions"] and action["observation"] != "chapter_length"]
    conflicts = canon.get("conflicts") or []
    interface_codes = {"NARRATIVE_TRANSITION_PRECONDITION_FAILED", "NARRATIVE_TRANSITION_BASELINE_MISSING", "PLANNED_STATE_TRANSITION_MISMATCH"}
    if conflicts and all(row.get("conflict_code") in interface_codes for row in conflicts):
        for action in content["required_actions"]:
            if action["observation"] == "canon_consistency":
                action.update(required_action="EVIDENCE_REASSESSMENT", required_authority="CANON_GRAPH_AUTHORITY",
                    permitted_change_scope="EVIDENCE_ONLY", repair_diagnostics=[{"code": row["conflict_code"], "message": row.get("evidence", {}).get("message", ""), "recommended_resolution": row.get("recommended_resolution", "")} for row in conflicts],
                    reassessment_reason="Typed extraction preconditions must reconcile accepted history and the active plan; no prose location establishes these interface conflicts.")
    for constraint in admission.get("work_constraints", ()):
        if constraint["status"] != "FAILED":
            continue
        text = revision["text"]
        scenes = [item["text"] for item in revision.get("scene_artifacts", ()) if item.get("text") and item["text"] in text]
        if not scenes:
            raise KernelError("QUALITY_REVISION_LOCATION_REQUIRED", "A length repair requires a preserved Scene boundary")
        scene = max(scenes, key=len)
        start = text.index(scene)
        report = {"dimension": constraint["dimension"], "target_asset_version_id": target,
            "gate_status": "FAILED", "calibration_status": "DETERMINISTIC", "measurement": constraint,
            "evidence_locations": [{"start": start, "end": start + len(scene), "quote": scene}],
            "source": constraint["source_policy"]}
        content["evidence_reports"] = [row for row in content["evidence_reports"] if row["dimension"] != constraint["dimension"]] + [report]
        content["required_actions"].append({"observation": constraint["dimension"], "required_action": "LOCAL_REPAIR",
            "required_authority": "CHAPTER_AUTHORITY", "permitted_change_scope": "CHAPTER",
            "reevaluation_gate": "platform_quality_gate", "preserved_invariants": ["accepted_canon", "executed_chapter_history", "active_parent_plan_identity"],
            "issue": {"code": "QUALITY_CHAPTER_LENGTH_FAILED", "status": "OPEN", "severity": "BLOCKING"},
            "evidence_asset_version_ids": [constraint["source_policy"]], "work_constraint": constraint,
            "repair_goal": "Meet the frozen author length range through a developed action or dialogue within the located Scene; preserve all outside text, facts, voices and causality. Avoid padding and explanatory summaries.",
            "source_text_hash": prose_hash(text)})
    content["decision_chain"] = {**content["decision_chain"], "required_actions": content["required_actions"],
        "mode": MODE, "literary_qualification": "NOT_RUN"}
    return content


def measure_length(text, unit):
    import unicodedata
    if unit == "UNICODE_CODE_POINTS_V1":
        return len(text)
    if unit == "HAN_CHARACTERS_V1":
        return sum(unicodedata.name(char, "").startswith(("CJK UNIFIED IDEOGRAPH-", "CJK COMPATIBILITY IDEOGRAPH-")) for char in text)
    raise KernelError("CHAPTER_LENGTH_UNIT_INVALID", unit)


def candidate_work_constraint_checks(*, revision, target, quality, checks):
    from copy import deepcopy
    rows = deepcopy(checks)
    for constraint in quality.get("internal_admission", {}).get("work_constraints", ()):
        if constraint["dimension"] not in revision.get("quality_action_observations", ()):
            continue
        if constraint["target_asset_version_id"] != revision.get("source_revision_asset_version_id"):
            raise KernelError("QUALITY_REVISION_LINEAGE_CONFLICT", "Objective constraint must bind the frozen revision source")
        if constraint["dimension"] != "chapter_length":
            continue
        observed = measure_length(revision["text"], constraint["unit"])
        passing = constraint["minimum"] <= observed <= constraint["maximum"]
        for check in rows:
            if check["observation"] == constraint["dimension"]:
                if check["target_asset_version_id"] != target:
                    raise KernelError("QUALITY_REREVIEW_CHECKS_INVALID", "Measurement requires the reviewed exact candidate")
                check.update(model_status=check["status"], status="SATISFIED" if passing else "UNRESOLVED",
                    evidence_class="OBJECTIVE_WORK_CONSTRAINT_WITH_MODEL_PRESERVATION",
                    objective_verification={**constraint, "target_asset_version_id": target, "observed": observed,
                        "status": "PASSED" if passing else "FAILED"})
    return rows


def assess_coordinated_internal_quality(*, groups, target, work_constraints):
    admission = assess_internal_quality(groups=groups, target=target, disposition_version=2)
    if admission is None:
        return None
    constraints = tuple(work_constraints)
    if len({item["dimension"] for item in constraints}) != len(constraints):
        raise KernelError("VALIDATION_QUALITY_COVERAGE_REQUIRED", target)
    for constraint in constraints:
        if constraint["dimension"] != "chapter_length" or constraint["target_asset_version_id"] != target:
            raise KernelError("VALIDATION_QUALITY_SCOPE_MISMATCH", target)
        if constraint["status"] not in {"PASSED", "FAILED"}:
            raise KernelError("VALIDATION_QUALITY_SCOPE_MISMATCH", target)
        dimension = constraint["dimension"]
        admission["blocked_dimensions"] = [item for item in admission["blocked_dimensions"] if item != dimension]
        if constraint["status"] == "FAILED":
            admission["blocked_dimensions"].append(dimension)
        admission["observations"] = [item for item in admission["observations"] if item["dimension"] != dimension]
        admission["observations"].append({"dimension": dimension, "status": "OBSERVED" if constraint["status"] == "PASSED" else "BLOCKED", "work_constraint": constraint})
    admission.update(version="creative-quality-admission.v3", work_constraints=list(constraints),
        status="BLOCKED" if admission["blocked_dimensions"] else "INTERNAL_ADMITTED")
    return admission
