from __future__ import annotations

from dataclasses import fields
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.routing_bootstrap import (
    authorization_hash, validate_reference_evaluation_binding,
)
from novel_forge.modules.reader_calibration.domain import EvaluatorIdentityClass

from .calibration_v2 import AdjudicatedEvaluation, HumanEvaluation, _validate_adjudication_sources
from .domain import QUALITY_GROUPS


def reference_dimensions(stage: str) -> tuple[str, ...]:
    if stage in {"review", "rereview"}:
        return (stage + "_decision",)
    if stage.startswith("quality_") and stage[8:] in QUALITY_GROUPS:
        return QUALITY_GROUPS[stage[8:]]
    raise KernelError("QUALITY_REFERENCE_TASK_UNSUPPORTED", "reference evaluation requires a native reviewer task")


def _native_label(cursor: Any, *, project_id: str, asset_version_id: str, asset_type: str,
                  operation_name: str, actor_field: str) -> tuple[dict[str, Any], str, str]:
    cursor.execute("""SELECT version.content,version.content_hash,operation.actor_id,operation.operation_id
        FROM authority_asset_version version JOIN authority_asset asset USING(asset_id)
        JOIN authority_operation_output_asset output ON output.asset_version_id=version.asset_version_id
          AND output.content_hash=version.content_hash
        JOIN authority_operation operation ON operation.operation_id=output.operation_id
          AND operation.project_id=asset.project_id
        WHERE asset.project_id=%s AND version.asset_version_id=%s AND asset.asset_type=%s
          AND version.lifecycle='ACTIVE' AND version.governance='CLEAR'
          AND operation.definition_name=%s AND operation.status='SUCCEEDED'
          AND NOT EXISTS (SELECT 1 FROM authority_external_effect effect WHERE effect.operation_id=operation.operation_id)
        """, [project_id, asset_version_id, asset_type, operation_name])
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise KernelError("QUALITY_REFERENCE_PROVENANCE_INVALID", "labels require their exact native authoring Operation")
    content, digest, actor, operation = rows[0]
    if digest != authorization_hash(content) or content.get("project_id") != project_id or actor != content.get(actor_field):
        raise KernelError("QUALITY_REFERENCE_PROVENANCE_INVALID", "label author or content differs from native evidence")
    return dict(content), digest, operation


def require_chapter_reference(
    cursor: Any, *, project_id: str, stage: str, input_versions: list[dict[str, Any]],
    binding: Mapping[str, Any], evaluator_actor_id: str, chapter: int,
) -> dict[str, Any]:
    validate_reference_evaluation_binding(binding)
    if "adjudications" not in binding:
        raise KernelError("QUALITY_REFERENCE_REQUIRED", "reviewer samples require adjudicated independent labels")
    target_type = {"review": "draft_chapter", "rereview": "draft_version"}.get(stage, "best_draft_candidate")
    cursor.execute("""SELECT version.asset_version_id,version.content_hash,
        ARRAY(SELECT operation.actor_id FROM authority_operation_output_asset output
              JOIN authority_operation operation USING(operation_id)
              WHERE output.asset_version_id=version.asset_version_id AND operation.project_id=asset.project_id)
        FROM authority_asset_version version JOIN authority_asset asset USING(asset_id)
        WHERE asset.project_id=%s AND version.asset_version_id=ANY(%s) AND asset.asset_type=%s
          AND version.governance='CLEAR'""",
        [project_id, [item["asset_version_id"] for item in input_versions], target_type])
    targets = cursor.fetchall()
    if len(targets) != 1 or not targets[0][2]:
        raise KernelError("QUALITY_REFERENCE_TARGET_INVALID", "reference labels must target the exact native reviewed draft")
    target_id, target_hash, generators = targets[0]
    if not any(item["asset_version_id"] == target_id and item["content_hash"] == target_hash for item in input_versions):
        raise KernelError("QUALITY_REFERENCE_TARGET_INVALID", "reference target differs from frozen task inputs")
    return require_adjudicated_reference(
        cursor, project_id=project_id, binding=binding, target_id=target_id, target_hash=target_hash,
        generators=generators, evaluator_actor_id=evaluator_actor_id, chapter=chapter,
        expected_dimensions=reference_dimensions(stage),
        allowed_statuses={"PASSED", "NEEDS_REVISION", "BLOCKED"} if stage in {"review", "rereview"} else {
            "PASSED", "PASSED_WITH_WARNINGS", "FAILED", "INSUFFICIENT_EVIDENCE"},
    )


def require_adjudicated_reference(
    cursor: Any, *, project_id: str, binding: Mapping[str, Any], target_id: str, target_hash: str,
    generators: list[str], evaluator_actor_id: str, chapter: int, expected_dimensions: tuple[str, ...],
    allowed_statuses: set[str],
) -> dict[str, Any]:
    validate_reference_evaluation_binding(binding)
    if "adjudications" not in binding or not expected_dimensions or not generators:
        raise KernelError("QUALITY_REFERENCE_REQUIRED", "reference evaluation requires its native target and adjudicated dimensions")
    excluded = {*generators, evaluator_actor_id}
    labels = []
    all_humans: dict[str, HumanEvaluation] = {}
    adjudications = []
    for reference in binding["adjudications"]:
        content, digest, operation = _native_label(cursor, project_id=project_id,
            asset_version_id=reference["asset_version_id"], asset_type="adjudicated_evaluation",
            operation_name="quality.adjudication.record", actor_field="adjudicator_id")
        if digest != reference["content_hash"] or content.get("contract_version") != "adjudicated-evaluation-v2":
            raise KernelError("QUALITY_REFERENCE_PROVENANCE_INVALID", "adjudication version or hash differs")
        adjudication = AdjudicatedEvaluation(**{field.name: content[field.name] for field in fields(AdjudicatedEvaluation)
            if field.name != "adjudication_asset_version_id"}, adjudication_asset_version_id=reference["asset_version_id"])
        if (adjudication.subject_asset_version_id != target_id or adjudication.protocol_version != binding["protocol_version"]
            or adjudication.scope_type != "CHAPTER" or adjudication.chapter_start != chapter or adjudication.chapter_end != chapter
            or adjudication.adjudicator_id in excluded or adjudication.adjudicator_identity_class not in set(EvaluatorIdentityClass)):
            raise KernelError("QUALITY_REFERENCE_NOT_INDEPENDENT", "adjudication is outside the exact blind reference scope")
        for human_id in adjudication.source_human_evaluation_asset_version_ids:
            human_content, _, _ = _native_label(cursor, project_id=project_id, asset_version_id=human_id,
                asset_type="human_evaluation", operation_name="quality.human_evaluation.record", actor_field="evaluator_id")
            if human_content.get("contract_version") != "human-evaluation-v2":
                raise KernelError("QUALITY_REFERENCE_PROVENANCE_INVALID", "reference human evaluation contract differs")
            human = HumanEvaluation(**{field.name: human_content[field.name] for field in fields(HumanEvaluation)
                if field.name != "evaluation_asset_version_id"}, evaluation_asset_version_id=human_id)
            if (human.evaluator_id in excluded or human.evaluator_id == adjudication.adjudicator_id
                or human.evaluator_identity_class not in set(EvaluatorIdentityClass) or not human.evidence):
                raise KernelError("QUALITY_REFERENCE_NOT_INDEPENDENT", "reference labels require independent evidenced human authors")
            all_humans[human_id] = human
        adjudications.append(adjudication)
        labels.append({"dimension": adjudication.dimension, "status": adjudication.status,
            "score_range": list(adjudication.score_range), "adjudication_asset_version_id": reference["asset_version_id"],
            "adjudication_operation_id": operation, "evaluation_version": adjudication.evaluation_version})
    _validate_adjudication_sources(tuple(all_humans.values()), tuple(adjudications))
    if (len(labels) != len(expected_dimensions) or {row["dimension"] for row in labels} != set(expected_dimensions)
        or any(row["status"] not in allowed_statuses for row in labels)
        or len({row["evaluation_version"] for row in labels}) != 1):
        raise KernelError("QUALITY_REFERENCE_COVERAGE_INCOMPLETE", "reference labels must cover every native reviewer dimension")
    return {"binding": dict(binding), "target_asset_version_id": target_id, "target_content_hash": target_hash,
            "labels": labels, "reference_basis": "ADJUDICATED_SUBJECTIVE_EVIDENCE",
            "human_preference_evidence": False, "production_qualification_eligible": False}


def chapter_reference_agreement(reference: Mapping[str, Any], *, stage: str, result: Mapping[str, Any]) -> dict[str, Any]:
    if stage in {"review", "rereview"}:
        observed = {stage + "_decision": {"gate_status": result.get("decision"), "score": None}}
    else:
        entries = result.get("dimensions")
        if not isinstance(entries, list) or len(entries) != len(reference["labels"]):
            raise KernelError("QUALITY_REFERENCE_RESULT_INVALID", "reviewer result does not cover its reference dimensions")
        observed = {entry["dimension"]: entry for entry in entries}
    if set(observed) != {label["dimension"] for label in reference["labels"]}:
        raise KernelError("QUALITY_REFERENCE_RESULT_INVALID", "reviewer result dimensions differ from reference")
    comparisons = []
    for label in reference["labels"]:
        actual = observed[label["dimension"]]
        score = actual.get("score")
        comparisons.append({**label, "observed_status": actual.get("gate_status"), "observed_score": score,
            "status_agrees": actual.get("gate_status") == label["status"],
            "score_in_range": None if stage in {"review", "rereview"} else
                isinstance(score, (int, float)) and not isinstance(score, bool) and label["score_range"][0] <= score <= label["score_range"][1]})
    return {**reference, "schema_version": "chapter-reference-agreement.v1", "comparisons": comparisons,
            "status_accuracy": sum(row["status_agrees"] for row in comparisons) / len(comparisons),
            "calibration_claim_allowed": False, "reader_preference_proven": False}


def reference_provider_result(cursor: Any, *, project_id: str, operation_id: str, attempt_id: str, stage: str) -> dict[str, Any]:
    cursor.execute("""SELECT version.content,version.content_hash,version.asset_version_id FROM authority_asset_version version
        JOIN authority_asset asset USING(asset_id)
        JOIN authority_operation_output_asset output ON output.asset_version_id=version.asset_version_id
          AND output.content_hash=version.content_hash AND output.role='model_evidence'
        JOIN authority_external_effect effect ON effect.external_effect_id=COALESCE(version.content->'provider_evidence',version.content)
          #>> '{production_execution,execution_request,external_effect_id}'
          AND effect.operation_id=%s AND effect.operation_id=output.operation_id
          AND effect.project_id=asset.project_id AND effect.status='SUCCEEDED'
        WHERE asset.project_id=%s AND asset.asset_type='model_call_log'
          AND version.content->>'attempt_id'=%s AND version.content->>'stage'=%s
        ORDER BY version.created_at DESC""", [operation_id, project_id, attempt_id, stage])
    rows = cursor.fetchall()
    if len(rows) != 1 or rows[0][1] != authorization_hash(rows[0][0]):
        raise KernelError("QUALITY_REFERENCE_PROVIDER_RESULT_MISSING", "reference agreement requires the exact successful native Provider result")
    content, digest, asset_id = rows[0]
    evidence = content.get("provider_evidence", content)
    if not isinstance(evidence.get("result"), dict):
        raise KernelError("QUALITY_REFERENCE_PROVIDER_RESULT_MISSING", "native Provider result is unavailable")
    return {"result": evidence["result"], "model_call_asset_version_id": asset_id, "model_call_content_hash": digest,
            "real_model_call": evidence.get("real_model_call") is True and not evidence.get("fixture_protocol_only")}
