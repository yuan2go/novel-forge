from __future__ import annotations

from typing import Any, Sequence

from novel_forge.modules.production_execution.cost_routing import snapshot_hash


def _effect_id(evidence: dict[str, Any]) -> str:
    return str(
        (evidence.get("execution_request") or {}).get("external_effect_id") or ""
    )


def assess_extract(
    assessment: dict[str, Any], *, compressor: dict[str, Any], fidelity: dict[str, Any]
) -> bool | None:
    task = assessment.get("task") or {}
    selected = assessment.get("selected_unit_ids")
    verdict = assessment.get("fidelity") or {}
    if (
        not isinstance(selected, list)
        or any(not isinstance(item, str) for item in selected)
        or len(set(selected)) != len(selected)
    ):
        return None
    allowed = {unit["unit_id"] for unit in task.get("units", [])}
    required = set(task.get("required_unit_ids", []))
    chosen = sorted(set(selected) | required)
    if set(selected) - allowed:
        return False
    if (
        compressor.get("stage") != "context_compress"
        or fidelity.get("stage") != "context_fidelity"
    ):
        return None
    if (compressor.get("input") or {}).get("context_compression_task") != task:
        return None
    checked = assessment.get("fidelity_selected_unit_ids", chosen)
    if (
        not isinstance(checked, list)
        or any(not isinstance(item, str) for item in checked)
        or set(checked) - allowed
        or not required.issubset(checked)
    ):
        return None
    if (fidelity.get("input") or {}).get("context_compression_task") != {
        **task,
        "selected_unit_ids": checked,
    }:
        return None
    return (
        verdict.get("supported") is True
        and verdict.get("coverage_complete") is True
        and not verdict.get("missing_unit_ids")
        and not verdict.get("distorted_unit_ids")
    )


def context_gate_outcomes(
    cursor: Any, *, project_id: str, effect_ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    if not effect_ids:
        return {}
    cursor.execute(
        """SELECT v.asset_version_id,v.content,o.operation_id
        FROM authority_asset_version v JOIN authority_asset a USING(asset_id)
        JOIN authority_operation_output_asset output ON output.asset_version_id=v.asset_version_id
        JOIN authority_operation o ON o.operation_id=output.operation_id AND o.project_id=a.project_id
        WHERE a.project_id=%s AND a.asset_type='context_bundle'
          AND o.status='SUCCEEDED' AND v.governance='CLEAR'
          AND v.content #> '{task_context_receipt,compression_trace}' IS NOT NULL""",
        [project_id],
    )
    bundles = cursor.fetchall()
    assessments = [
        (identity, content, operation, trace, row)
        for identity, content, operation in bundles
        for trace in (content.get("task_context_receipt") or {}).get(
            "compression_trace", []
        )
        for row in trace.get("routing_assessments", [])
    ]
    cursor.execute(
        """SELECT e.external_effect_id,e.operation_id,e.request_payload,
        o.status,d.generation,d.status,d.evidence,r.payload_hash,r.payload,r.external_receipt_id,
        v.asset_version_id,v.content,d.payload_hash,e.status,
        (SELECT max(latest.generation) FROM authority_external_effect_dispatch latest
          WHERE latest.external_effect_id=e.external_effect_id)
        FROM authority_external_effect e JOIN authority_operation o USING(operation_id)
        JOIN authority_external_effect_dispatch d USING(external_effect_id)
        JOIN authority_external_receipt r USING(dispatch_id)
        JOIN authority_asset_version v
          ON (COALESCE(v.content->'provider_evidence',v.content)
              #>> '{production_execution,execution_request,external_effect_id}')=e.external_effect_id
        JOIN authority_asset a USING(asset_id)
        WHERE e.project_id=%s AND a.project_id=e.project_id AND a.asset_type='model_call_log'
          AND r.status='VERIFIED' AND d.status IN ('SUCCEEDED','FAILED_FINAL','FAILED_RETRYABLE')
          AND e.request_payload->>'stage' IN ('context_compress','context_fidelity')
          AND e.operation_id IN (SELECT operation_id FROM authority_external_effect
              WHERE project_id=%s AND external_effect_id=ANY(%s))
        ORDER BY e.created_at,e.external_effect_id,d.generation,v.asset_version_id""",
        [project_id, project_id, list(effect_ids)],
    )
    native = {}
    history = {}
    current_success = set()
    for (
        identity,
        operation,
        payload,
        status,
        generation,
        dispatch_status,
        dispatch_evidence,
        receipt_hash,
        receipt,
        receipt_id,
        log_id,
        content,
        dispatch_hash,
        effect_status,
        latest_generation,
    ) in cursor.fetchall():
        from .routing_feedback import _real_evidence
        from novel_forge.modules.command_kernel.external_effect_runtime import _hash

        evidence = _real_evidence(content)
        if (
            evidence is None
            or receipt.get("evidence") != dispatch_evidence
            or _hash(dispatch_evidence) != receipt_hash
            or dispatch_hash != receipt_hash
            or evidence != dispatch_evidence
        ):
            continue
        execution = (evidence.get("production_execution") or {}).get(
            "execution_request"
        ) or {}
        if (
            content.get("operation_id"),
            execution.get("operation_id"),
            execution.get("project_id"),
            execution.get("external_effect_id"),
        ) != (operation, operation, project_id, identity):
            continue
        history.setdefault(identity, {})[generation] = {
            "status": dispatch_status,
            "evidence_refs": [
                f"external-receipt:{receipt_id}",
                "asset-version:" + log_id,
            ],
        }
        native[identity] = (operation, payload, evidence, status)
        if (
            effect_status == "SUCCEEDED"
            and dispatch_status == "SUCCEEDED"
            and generation == latest_generation
        ):
            current_success.add(identity)
    result = {}
    for bundle_id, bundle, operation, trace, assessment in assessments:
        comp = _effect_id(assessment.get("compressor_evidence", {}))
        fid = _effect_id(assessment.get("fidelity_evidence", {}))
        if not comp or comp == fid or comp not in native or fid not in native:
            continue
        c_op, c_input, c_evidence, _ = native[comp]
        f_op, f_input, f_evidence, _ = native[fid]
        if c_op != operation or f_op != operation:
            continue
        task = assessment.get("task") or {}
        source = task.get("source_binding") or {}
        if (trace.get("source_asset_version_id"), trace.get("source_content_hash")) != (
            source.get("asset_version_id"),
            source.get("content_hash"),
        ):
            continue
        if c_evidence.get("result") != {
            "selected_unit_ids": assessment.get("selected_unit_ids")
        } or f_evidence.get("result") != assessment.get("fidelity"):
            continue
        passed = assess_extract(assessment, compressor=c_input, fidelity=f_input)
        if passed is None:
            continue
        if passed and not {comp, fid}.issubset(current_success):
            continue
        refs = [
            "asset-version:" + bundle_id,
            "external-effect:" + comp,
            "external-effect:" + fid,
        ]
        for identity in (comp, fid):
            if identity in effect_ids:
                result[identity] = {
                    "accepted": passed,
                    "metric": "CONTEXT_EXTRACT_GATE.v1",
                    "evidence_refs": refs,
                    "context_source_hash": snapshot_hash(source),
                    "literary_quality_proven": False,
                    "fidelity_calibrated": False,
                }
    for comp, (operation, c_input, c_evidence, status) in native.items():
        if c_input.get("stage") != "context_compress":
            continue
        task = (c_input.get("input") or {}).get("context_compression_task") or {}
        selected = (c_evidence.get("result") or {}).get("selected_unit_ids")
        pairs = [
            (fid, f_input, f_evidence)
            for fid, (f_op, f_input, f_evidence, _) in native.items()
            if f_op == operation
            and f_input.get("stage") == "context_fidelity"
            and {
                key: value
                for key, value in (
                    (f_input.get("input") or {}).get("context_compression_task") or {}
                ).items()
                if key != "selected_unit_ids"
            }
            == task
        ]
        if (
            not pairs
            and status in {"FAILED_FINAL", "CANCELLED", "DEAD_LETTER"}
            and comp in effect_ids
        ):
            result[comp] = {
                "accepted": False,
                "metric": "CONTEXT_EXTRACT_GATE.v1",
                "evidence_refs": ["external-effect:" + comp, "operation:" + operation],
                "context_source_hash": snapshot_hash(task.get("source_binding") or {}),
                "literary_quality_proven": False,
                "fidelity_calibrated": False,
                "context_operation_status": status,
            }
        for index, (fid, f_input, f_evidence) in enumerate(pairs):
            checked = f_input["input"]["context_compression_task"]["selected_unit_ids"]
            assessment = {
                "task": task,
                "selected_unit_ids": selected,
                "fidelity_selected_unit_ids": checked,
                "fidelity": f_evidence.get("result") or {},
            }
            verdict = assess_extract(assessment, compressor=c_input, fidelity=f_input)
            if verdict is None or (
                verdict and status not in {"FAILED_FINAL", "CANCELLED", "DEAD_LETTER"}
            ):
                continue
            source = task.get("source_binding") or {}
            failure = {
                "accepted": False,
                "metric": "CONTEXT_EXTRACT_GATE.v1",
                "evidence_refs": ["external-effect:" + comp, "external-effect:" + fid],
                "context_source_hash": snapshot_hash(source),
                "literary_quality_proven": False,
                "fidelity_calibrated": False,
                "context_operation_status": status,
            }
            if fid in effect_ids:
                result[fid] = failure
            if index == 0 and comp in effect_ids:
                result[comp] = failure
    for identity, outcome in result.items():
        attempts = history[identity]
        outcome["native_dispatch_history"] = [
            dict(generation=generation, **attempts[generation])
            for generation in sorted(attempts)
        ]
        outcome["evidence_refs"] += [
            ref for attempt in attempts.values() for ref in attempt["evidence_refs"]
        ]
        if any(attempt["status"] != "SUCCEEDED" for attempt in attempts.values()):
            outcome["accepted"] = False
    return result
