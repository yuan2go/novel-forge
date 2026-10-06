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
    generation_sample: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    validate_reference_evaluation_binding(binding)
    model_reference = binding.get("basis") == "MODEL_CONSENSUS"
    if "adjudications" not in binding:
        raise KernelError("QUALITY_REFERENCE_REQUIRED", "reviewer samples require adjudicated independent labels")
    if generation_sample is not None:
        from .reference_subject import require_reference_subject

        target = {key: generation_sample.get(key) for key in ("asset_version_id", "content_hash")}
        subject = require_reference_subject(cursor, project_id=project_id, binding=target)
        if (target not in input_versions or subject["content"]["stage"] != {"review": "draft", "rereview": "revision"}.get(stage)):
            raise KernelError("QUALITY_REFERENCE_TARGET_INVALID", "reference labels require the exact compatible generator sample")
        return require_model_consensus_reference(cursor, project_id=project_id, binding=binding,
            target_id=subject["asset_version_id"], target_hash=subject["content_hash"],
            chapter=chapter, expected_dimensions=reference_dimensions(stage),
            allowed_statuses={"PASSED", "FAILED"}) if model_reference else require_adjudicated_reference(cursor, project_id=project_id, binding=binding,
            target_id=subject["asset_version_id"], target_hash=subject["content_hash"],
            generators=[subject["generation_actor_id"]], evaluator_actor_id=evaluator_actor_id, chapter=chapter,
            expected_dimensions=reference_dimensions(stage), allowed_statuses={"PASSED", "NEEDS_REVISION", "BLOCKED"})
    if stage == "canon_support":
        from .canon_support_reference import require_reference
        return require_reference(cursor, project_id=project_id, input_versions=input_versions,
            binding=binding, evaluator_actor_id=evaluator_actor_id, chapter=chapter)
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
    if model_reference:
        return require_model_consensus_reference(cursor, project_id=project_id, binding=binding,
            target_id=target_id, target_hash=target_hash, chapter=chapter,
            expected_dimensions=reference_dimensions(stage),
            allowed_statuses={"PASSED", "FAILED"})
    return require_adjudicated_reference(
        cursor, project_id=project_id, binding=binding, target_id=target_id, target_hash=target_hash,
        generators=generators, evaluator_actor_id=evaluator_actor_id, chapter=chapter,
        expected_dimensions=reference_dimensions(stage),
        allowed_statuses={"PASSED", "NEEDS_REVISION", "BLOCKED"} if stage in {"review", "rereview"} else {
            "PASSED", "PASSED_WITH_WARNINGS", "FAILED", "INSUFFICIENT_EVIDENCE"},
    )


def require_model_consensus_reference(cursor: Any, *, project_id: str, binding: Mapping[str, Any],
                                      target_id: str, target_hash: str, chapter: int,
                                      expected_dimensions: tuple[str, ...],
                                      allowed_statuses: set[str],
                                      expected_producer_contract_hash: str | None = None) -> dict[str, Any]:
    from .model_reference import MODEL_REFERENCE_PROTOCOL, require_model_panel_reference

    if (binding.get("basis") != "MODEL_CONSENSUS" or binding.get("protocol_version") != MODEL_REFERENCE_PROTOCOL
        or not isinstance(binding.get("adjudications"), list)
        or len(binding["adjudications"]) != len(expected_dimensions)):
        raise KernelError("MODEL_REFERENCE_COVERAGE_INCOMPLETE", "model panel must cover each native reviewer dimension")
    labels = []
    correlated = False
    versions = set()
    evidence_refs = []
    for item in binding["adjudications"]:
        panel = require_model_panel_reference(cursor, project_id=project_id,
            binding={"protocol_version": MODEL_REFERENCE_PROTOCOL, "adjudications": [item]})
        if (panel["target_asset_version_id"] != target_id or panel["target_content_hash"] != target_hash
            or panel["scope"] != {"scope_type": "CHAPTER", "chapter_start": chapter, "chapter_end": chapter}
            or (expected_producer_contract_hash is not None and
                panel["producer_contract_hash"] != expected_producer_contract_hash)):
            raise KernelError("MODEL_REFERENCE_TARGET_INVALID", "model panel subject differs from frozen reviewer target")
        label = panel["labels"][0]
        if (label["status"] not in allowed_statuses or not isinstance(label["score_range"], list)
            or len(label["score_range"]) != 2 or any(type(score) is not int or not 0 <= score <= 100
                for score in label["score_range"]) or label["score_range"][0] > label["score_range"][1]):
            raise KernelError("MODEL_REFERENCE_RESULT_INVALID", "model panel judgment is outside native quality schema")
        labels.append(label)
        versions.add(label["evaluation_version"])
        correlated |= panel["same_model_correlated"]
        evidence_refs.extend(panel["evidence_refs"])
    if {item["dimension"] for item in labels} != set(expected_dimensions) or len(versions) != 1:
        raise KernelError("MODEL_REFERENCE_COVERAGE_INCOMPLETE", "model panel dimensions or version differ")
    return {"binding": dict(binding), "target_asset_version_id": target_id,
        "target_content_hash": target_hash, "labels": labels, "reference_basis": "MODEL_CONSENSUS",
        "same_model_correlated": correlated, "human_verified": False,
        "human_preference_evidence": False, "production_qualification_eligible": False,
        "evidence_refs": sorted(set(evidence_refs))}


def require_adjudicated_reference(
    cursor: Any, *, project_id: str, binding: Mapping[str, Any], target_id: str, target_hash: str,
    generators: list[str], evaluator_actor_id: str, chapter: int, expected_dimensions: tuple[str, ...],
    allowed_statuses: set[str],
    scope_type: str = "CHAPTER", chapter_end: int | None = None,
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
            or adjudication.scope_type != scope_type or adjudication.chapter_start != chapter
            or adjudication.chapter_end != (chapter if chapter_end is None else chapter_end)
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
    if stage == "canon_support":
        from .canon_support_reference import observed_dimensions
        observed = observed_dimensions(reference, result)
    elif stage in {"review", "rereview"}:
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
            "score_in_range": None if stage in {"review", "rereview", "canon_support"} else
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
          AND COALESCE(version.content->>'attempt_id',COALESCE(version.content->'provider_evidence',version.content)
            #>> '{production_execution,execution_request,attempt_id}')=%s AND version.content->>'stage'=%s
        ORDER BY version.created_at DESC""", [operation_id, project_id, attempt_id, stage])
    rows = cursor.fetchall()
    if len(rows) != 1 or rows[0][1] != authorization_hash(rows[0][0]):
        raise KernelError("QUALITY_REFERENCE_PROVIDER_RESULT_MISSING", "reference agreement requires the exact successful native Provider result")
    content, digest, asset_id = rows[0]
    evidence = content.get("provider_evidence", content)
    if not isinstance(evidence.get("result"), dict):
        raise KernelError("QUALITY_REFERENCE_PROVIDER_RESULT_MISSING", "native Provider result is unavailable")
    return {"result": evidence["result"], "model_call_asset_version_id": asset_id, "model_call_content_hash": digest,
            "real_model_call": evidence.get("real_model_call") is True and not any(
                item.get(flag) is True for item in (content, evidence) for flag in ("fixture", "fixture_protocol_only"))}


def reference_label_classes(cursor: Any, *, project_id: str, reference: Mapping[str, Any], stage: str) -> tuple[str, ...]:
    classes = set()
    statuses = {"PASSED": "PASS", "PASSED_WITH_WARNINGS": "PASS", "NEEDS_REVISION": "FAIL", "FAILED": "FAIL", "BLOCKED": "FAIL"}
    for label in reference["labels"]:
        status = statuses.get(label["status"])
        if status is None or (stage not in {"review", "rereview", "canon_support"} and label["score_range"][1] - label["score_range"][0] > 20):
            return ()
        classes.add(status)
        if reference.get("reference_basis") == "MODEL_CONSENSUS":
            continue
        adjudication, _, _ = _native_label(cursor, project_id=project_id,
            asset_version_id=label["adjudication_asset_version_id"], asset_type="adjudicated_evaluation",
            operation_name="quality.adjudication.record", actor_field="adjudicator_id")
        for asset_id in adjudication["source_human_evaluation_asset_version_ids"]:
            human, _, _ = _native_label(cursor, project_id=project_id, asset_version_id=asset_id,
                asset_type="human_evaluation", operation_name="quality.human_evaluation.record", actor_field="evaluator_id")
            if ("FIXTURE" in human["evaluator_group"].upper()
                or any(item.get("fixture_protocol_only") or item.get("fixture") for item in human["evidence"])):
                return ()
    return tuple(sorted(classes))


def chapter_reference_outcomes(cursor: Any, *, project_id: str, effect_ids: list[str]) -> dict[str, dict[str, Any]]:
    from novel_forge.modules.command_kernel.routing_bootstrap import load_bootstrap_authorization, CHAPTER_REFERENCE_TASKS
    from .reference_subject import require_chapter_sample_target

    if not effect_ids:
        return {}
    cursor.execute("""SELECT effect.external_effect_id,effect.operation_id,model.content->>'attempt_id',operation.actor_id,
        operation.command_payload->'payload',version.asset_version_id,version.content_hash,version.content
        FROM authority_external_effect effect JOIN authority_operation operation USING(operation_id)
        JOIN authority_operation_output_asset output ON output.operation_id=operation.operation_id AND output.role='primary'
        JOIN authority_asset_version version ON version.asset_version_id=output.asset_version_id AND version.content_hash=output.content_hash
        JOIN authority_asset asset ON asset.asset_id=version.asset_id AND asset.project_id=operation.project_id
        JOIN authority_asset_version model ON model.asset_version_id=version.content #>> '{reference_evaluation,model_call_asset_version_id}'
          AND effect.external_effect_id=COALESCE(model.content->'provider_evidence',model.content) #>> '{production_execution,execution_request,external_effect_id}'
        JOIN authority_attempt attempt ON attempt.attempt_id=model.content->>'attempt_id'
          AND attempt.operation_id=operation.operation_id AND attempt.status='SUCCEEDED'
        WHERE effect.project_id=%s AND effect.external_effect_id=ANY(%s) AND effect.status='SUCCEEDED'
          AND operation.status='SUCCEEDED' AND asset.asset_type='chapter_provider_sample'
          AND version.lifecycle='ACTIVE' AND version.eligibility='INELIGIBLE' AND version.governance='CLEAR'
        ORDER BY version.created_at,version.asset_version_id""", [project_id, effect_ids])
    rows = cursor.fetchall()
    outcomes = {}
    for effect_id, operation_id, attempt_id, actor, payload, asset_id, digest, content in rows:
        stage = content.get("stage")
        if (stage not in CHAPTER_REFERENCE_TASKS.values() or digest != authorization_hash(content)
            or content.get("production_eligible") is not False or content.get("routing_eligibility") != "BENCHMARK_ONLY"):
            continue
        try:
            snapshot = load_bootstrap_authorization(cursor, project_id=project_id, operation_id=operation_id, check_expiry=False)
            grant = snapshot["authorization"] if snapshot else {}
            if (grant.get("purpose") != "REFERENCE_EVALUATION" or content.get("authorization_id") != grant.get("authorization_id")
                or content.get("campaign") != grant.get("campaign") or payload.get("generator_operation_name") != stage):
                continue
            provider = reference_provider_result(cursor, project_id=project_id, operation_id=operation_id, attempt_id=attempt_id, stage=stage)
            if not provider["real_model_call"]:
                continue
            subject = require_chapter_sample_target(cursor, project_id=project_id, payload=payload) if (
                payload["chapter_sampling"].get("generation_sample") is not None) else None
            reference = require_chapter_reference(cursor, project_id=project_id, stage=stage,
                input_versions=payload["input_versions"], binding=payload["reference_evaluation"], evaluator_actor_id=actor,
                chapter=payload["chapter"], generation_sample=subject)
            agreement = {**chapter_reference_agreement(reference, stage=stage, result=provider["result"]),
                **{key: value for key, value in provider.items() if key != "result"}}
            if agreement != content.get("reference_evaluation"):
                continue
            classes = reference_label_classes(cursor, project_id=project_id, reference=reference, stage=stage)
            if not classes:
                continue
            cursor.execute("SELECT content FROM authority_asset_version WHERE asset_version_id=%s AND content_hash=%s",
                [reference["target_asset_version_id"], reference["target_content_hash"]])
            target = cursor.fetchone()[0]
            prose = (target.get("sampled_output") or target).get("text")
            if stage != "canon_support" and (not isinstance(prose, str) or not prose.strip()):
                continue
        except (KernelError, ValueError, TypeError, KeyError):
            continue
        agreed = all(item["status_agrees"] and (stage in {"review", "rereview", "canon_support"} or item["score_in_range"] is True)
            for item in agreement["comparisons"])
        outcomes[effect_id] = {"accepted": None, "metric": "REFERENCE_AGREEMENT.v1", "reference_agreed": agreed,
            "reference_basis": reference["reference_basis"],
            "same_model_correlated": reference.get("same_model_correlated", False),
            "generator_assessment": {"target_asset_version_id": reference["target_asset_version_id"],
                "target_content_hash": reference["target_content_hash"], "labels": reference["labels"],
                "protocol_version": reference["binding"]["protocol_version"]},
            "reference_label_classes": classes,
            "reference_protocol_hash": authorization_hash({"protocol_version": reference["binding"]["protocol_version"],
                "evaluation_versions": sorted({item["evaluation_version"] for item in reference["labels"]}),
                "dimensions": ["canon_support_claim", "canon_no_change"] if stage == "canon_support" else sorted(item["dimension"] for item in reference["labels"]),
                **({"reference_basis": "MODEL_CONSENSUS"} if reference["reference_basis"] == "MODEL_CONSENSUS" else {}),
                "agreement_contract": "REFERENCE_AGREEMENT.v1"}),
            "reference_sample_identity": reference["canon_reference_sample_identity"] if stage == "canon_support" else authorization_hash({"task_type": stage, "text": " ".join(prose.split())}),
            "failure_class": "" if agreed else "QUALITY_FAILURE",
            "evidence_refs": ["asset-version:" + asset_id, "asset-version:" + provider["model_call_asset_version_id"],
                *("asset-version:" + item["adjudication_asset_version_id"] for item in agreement["comparisons"]),
                *reference.get("evidence_refs", [])]}
    return outcomes


def admitted_reference_calibration(
    request: Any, result: Any, *, stage: str, target_asset_version_id: str
) -> dict[str, Any] | None:
    from novel_forge.modules.chapter_authority.definitions import (
        CHAPTER_MODEL_EFFECT_DEFINITION_VERSION,
        CHAPTER_RECOVERABLE_MODEL_DEFINITION_VERSIONS,
    )
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork

    evidence = result.to_evidence()
    execution = evidence.get("production_execution") or {}
    native = execution.get("execution_request") or {}
    if (not result.real_model_call or request.command.get("chapter_sampling") or not request.database_url
        or native.get("project_id") != request.project_id or native.get("operation_id") != request.operation_id
        or native.get("attempt_id") != request.attempt_id or native.get("stage") != stage
        or not native.get("external_effect_id")):
        return None
    with AuthorityUnitOfWork(request.database_url) as uow:
        uow.cursor.execute(
            """SELECT model.asset_version_id,model.content_hash,model.content,
            decision.asset_version_id,decision.content_hash,decision.content,effect.request_payload
            FROM authority_external_effect effect JOIN authority_operation operation USING(operation_id)
            JOIN authority_operation_output_asset output ON output.operation_id=operation.operation_id AND output.role='model_evidence'
            JOIN authority_asset_version model ON model.asset_version_id=output.asset_version_id AND model.content_hash=output.content_hash
            JOIN authority_asset model_asset ON model_asset.asset_id=model.asset_id AND model_asset.project_id=effect.project_id
              AND model_asset.asset_type='model_call_log'
            JOIN authority_attempt attempt ON attempt.operation_id=effect.operation_id
              AND attempt.attempt_id=model.content->>'attempt_id' AND attempt.status IN ('RUNNING','RESULT_SUBMITTED','SUCCEEDED')
            JOIN authority_asset_version decision ON decision.asset_version_id=effect.request_payload
              #>> '{_production_execution,capability_runtime,routing_decision,asset_version_id}'
            JOIN authority_asset decision_asset ON decision_asset.asset_id=decision.asset_id AND decision_asset.project_id=effect.project_id
              AND decision_asset.asset_type='routing_decision'
            JOIN authority_operation_output_asset routing ON routing.operation_id=effect.operation_id
              AND routing.asset_version_id=decision.asset_version_id AND routing.content_hash=decision.content_hash AND routing.role='routing_evidence'
            WHERE effect.project_id=%s AND effect.operation_id=%s AND effect.external_effect_id=%s AND effect.status='SUCCEEDED'
              AND operation.definition_name=%s AND operation.definition_version=ANY(%s)
              AND effect.provider_capability_profile->>'real_provider_validation_eligible'='true'
              AND effect.model_id=model.content #>> '{provider_evidence,model_id}'
              AND effect.capability='model.' || (model.content->>'stage')
              AND model.content->>'stage'=%s AND model.content->>'attempt_id'=%s
              AND model.content #>> '{provider_evidence,production_execution,execution_request,external_effect_id}'=effect.external_effect_id
              AND effect.request_payload #>> '{input,quality_context,target_revision_asset_version_id}'=%s
              AND model.governance='CLEAR' AND decision.governance='CLEAR'""",
            [
                request.project_id,
                request.operation_id,
                native["external_effect_id"],
                "chapter.quality." + stage.removeprefix("quality_") + ".evaluate",
                [
                    CHAPTER_MODEL_EFFECT_DEFINITION_VERSION,
                    *sorted(CHAPTER_RECOVERABLE_MODEL_DEFINITION_VERSIONS),
                ],
                stage,
                request.attempt_id,
                target_asset_version_id,
            ],
        )
        rows = uow.cursor.fetchall()
        uow.cursor.execute(
            "SELECT request_payload #> '{_production_execution,capability_runtime,routing_decision}' FROM authority_external_effect WHERE project_id=%s AND external_effect_id=%s",
            [request.project_id, native["external_effect_id"]],
        )
        effect_row = uow.cursor.fetchone()
        frozen = effect_row[0] if effect_row and isinstance(effect_row[0], dict) else {}
    required = frozen.get("independent_qualification_eligible") is not False and frozen.get("status") == "SELECTED" and frozen.get("policy", {}).get("quality_metric") == "REFERENCE_AGREEMENT"
    if len(rows) != 1:
        if required:
            raise KernelError("QUALITY_REFERENCE_ADMISSION_INVALID", "qualified reviewer call lost its native receipt or target binding")
        return None
    model_id, model_hash, model, decision_id, decision_hash, decision, payload = rows[0]
    if (model_hash != authorization_hash(model) or decision_hash != authorization_hash(decision)
        or model.get("provider_evidence") != evidence
        or payload["_production_execution"]["capability_runtime"]["routing_decision"] != {**decision, "asset_version_id": decision_id}
        or not reference_decision_qualifies(decision, evidence=evidence, stage=stage)):
        if required:
            raise KernelError("QUALITY_REFERENCE_ADMISSION_INVALID", "qualified reviewer result differs from its frozen model, scope or evidence")
        return None
    benchmark = decision["selected"]["benchmark"]
    return {"schema_version": "chapter-reference-calibration.v1", "stage": stage, "operation_id": request.operation_id,
        "target_asset_version_id": target_asset_version_id, "external_effect_id": native["external_effect_id"],
        "routing_decision": {"asset_version_id": decision_id, "content_hash": decision_hash},
        "model_call": {"asset_version_id": model_id, "content_hash": model_hash},
        "benchmark_hash": authorization_hash(benchmark), "reference_protocol_hash": benchmark["reference_protocol_hashes"][0],
        "reference_outcome_refs": benchmark["outcome_refs"], "reference_lower_bound": benchmark["predicted_quality"],
        "human_verified": False, "reader_preference_proven": False, "production_verified": False}


def reference_decision_qualifies(decision: Mapping[str, Any], *, evidence: Mapping[str, Any], stage: str) -> bool:
    from dataclasses import asdict
    from novel_forge.modules.production_execution.cost_routing import POLICY_VERSION, REFERENCE_TASKS, reference_context_bucket, task_policy

    selected = decision.get("selected") or {}
    candidate = selected.get("candidate") or {}
    benchmark = selected.get("benchmark") or {}
    task = decision.get("task") or {}
    policy = decision.get("policy") or {}
    execution = evidence.get("production_execution") or {}
    native = execution.get("execution_request") or {}
    route = execution.get("route_snapshot") or {}
    process = execution.get("process_evidence") or {}
    strata = benchmark.get("reference_label_strata") or {}
    compatible_versions = {POLICY_VERSION, "quality-constrained-routing.v12"} | ({"quality-constrained-routing.v10", "quality-constrained-routing.v11"} if stage != "canon_support" else set())
    if (stage not in REFERENCE_TASKS or decision.get("schema_version") not in compatible_versions
        or decision.get("status") != "SELECTED" or decision.get("bootstrap_authorization")
        or decision.get("production_eligible") is False or decision.get("independent_qualification_eligible") is False or selected.get("rejected_reasons")
        or candidate.get("provider") not in {"deepseek", "codex-cli"}
        or evidence.get("real_model_call") is not True or evidence.get("fixture_protocol_only") or process.get("fixture_protocol_only")
        or (execution.get("execution_result") or {}).get("outcome") != "SUCCEEDED"
        or task.get("task_type") != stage or any(task.get(key) != native.get(key) for key in ("project_id", "operation_id", "attempt_id"))
        or not task.get("producer_contract_hash") or task["producer_contract_hash"] != authorization_hash(task.get("producer_contract"))
        or policy.get("quality_metric") != "REFERENCE_AGREEMENT" or benchmark.get("quality_metric") != "REFERENCE_AGREEMENT"
        or benchmark.get("uncertain") is not False or benchmark.get("reference_risk") != policy.get("risk")
        or len(benchmark.get("reference_protocol_hashes", [])) != 1 or not benchmark.get("outcome_refs")
        or benchmark.get("reference_context_buckets") != [reference_context_bucket(task.get("input_tokens", 0))]
        or (candidate.get("provider"), candidate.get("model"), candidate.get("reasoning")) !=
           (evidence.get("provider_id"), evidence.get("model_id"), route.get("reasoning_effort"))
        or set(strata) != {"PASS", "FAIL"}):
        return False
    try:
        expected_policy = asdict(task_policy(stage, policy["risk"], policy["quality_floor"]))
        expected_policy.pop("retain_failed_domain_samples")
        reference_policy = dict(policy)
        if reference_policy.pop("retain_failed_domain_samples", False) is not False or reference_policy != expected_policy:
            return False
    except (ValueError, KeyError, TypeError):
        return False
    if candidate.get("provider") == "deepseek" and (
        not process.get("served_model_identity_hash") or benchmark.get("served_model_identity_hashes") != [process["served_model_identity_hash"]]
        or process.get("model_revision") != candidate.get("model_revision")):
        return False
    if candidate.get("provider") == "codex-cli" and (
        (evidence.get("cost") or {}).get("entitlement_snapshot", {}).get("configuration_ref") != candidate.get("model_revision")):
        return False
    return (benchmark.get("predicted_quality", 0) >= policy.get("quality_floor", 1)
        and all(row.get("sample_count", 0) >= policy.get("minimum_samples", 1)
            and row.get("lower_bound", 0) >= policy.get("quality_floor", 1) for row in strata.values()))
