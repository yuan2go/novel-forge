from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_design_authority.qualification import (
    required_qualification_profiles,
    validate_narrative_qualification,
)

from novel_forge.modules.production_execution.cost_routing import snapshot_hash


def normalized_evidence(content: Mapping[str, Any]) -> Mapping[str, Any]:
    evidence = content.get("provider_evidence", content)
    return evidence if isinstance(evidence, Mapping) else {}


def _real_evidence(content: Mapping[str, Any]) -> Mapping[str, Any] | None:
    evidence = normalized_evidence(content)
    if not (
        evidence.get("real_model_call") is True
        or evidence.get("real_provider_proven") is True
    ) or any(
        item.get(flag) is True
        for item in (content, evidence)
        for flag in ("fixture", "fixture_protocol_only")
    ):
        return None
    return evidence


def planning_gate_outcomes(
    cursor: Any, *, project_id: str, effect_ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    if not effect_ids:
        return {}
    cursor.execute(
        """SELECT effect.external_effect_id,to_jsonb(q),candidate.content_hash,
                  COALESCE(generation.generator_operation_name,state.generator_operation_name),model.content_hash,model.content,
                  evaluated.content,evaluator.external_effect_id
           FROM authority_narrative_design_qualification q
           JOIN authority_asset_version candidate ON candidate.asset_version_id=q.asset_version_id
             AND candidate.content_hash=q.candidate_content_hash
           JOIN authority_asset candidate_asset ON candidate_asset.asset_id=candidate.asset_id
             AND candidate_asset.project_id=q.project_id
           JOIN authority_external_effect effect
             ON effect.external_effect_id=candidate.content #>> '{execution_evidence,external_receipt_ref}'
             AND effect.project_id=q.project_id AND effect.operation_id=q.generation_operation_id
           LEFT JOIN authority_story_planning_generation generation
             ON generation.operation_id=effect.operation_id AND generation.project_id=q.project_id
             AND generation.candidate_asset_version_id=q.asset_version_id
           LEFT JOIN authority_story_design_version_state state
             ON state.asset_version_id=q.asset_version_id AND state.project_id=q.project_id
             AND state.execution_evidence->>'operation_id'=effect.operation_id
           JOIN authority_asset_version model ON model.asset_version_id=q.provider_model_call_asset_version_id
           JOIN authority_asset model_asset ON model_asset.asset_id=model.asset_id
             AND model_asset.project_id=q.project_id AND model_asset.asset_type='model_call_log'
           JOIN authority_operation evaluation ON evaluation.operation_id=q.evaluation_operation_id
             AND evaluation.project_id=q.project_id AND evaluation.status='SUCCEEDED'
           JOIN authority_attempt attempt ON attempt.attempt_id=q.evaluation_attempt_id
             AND attempt.operation_id=evaluation.operation_id AND attempt.status='SUCCEEDED'
           JOIN authority_asset_version evaluated ON evaluated.asset_version_id=q.evaluation_asset_version_id
             AND evaluated.governance='CLEAR'
           JOIN authority_asset evaluated_asset ON evaluated_asset.asset_id=evaluated.asset_id
             AND evaluated_asset.project_id=q.project_id AND evaluated_asset.asset_type='narrative_design_evaluation'
           JOIN authority_external_effect evaluator
             ON evaluator.external_effect_id=COALESCE(model.content->'provider_evidence',model.content)
                 #>> '{production_execution,execution_request,external_effect_id}'
             AND evaluator.project_id=q.project_id AND evaluator.operation_id=evaluation.operation_id
             AND evaluator.status='SUCCEEDED'
           WHERE q.project_id=%s AND q.trust_boundary='INDEPENDENT'
             AND q.evaluator_execution_class='MODEL_PROVIDER'
             AND q.generation_operation_id<>q.evaluation_operation_id
             AND effect.external_effect_id=ANY(%s) AND effect.status='SUCCEEDED'
             AND (generation.operation_id IS NOT NULL OR state.asset_version_id IS NOT NULL)
           ORDER BY q.created_at,q.qualification_id""",
        [project_id, list(effect_ids)],
    )
    groups: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for row in cursor.fetchall():
        (
            effect_id,
            qualification,
            candidate_hash,
            generator,
            model_hash,
            log,
            evaluated,
            evaluator_id,
        ) = row
        evidence = _real_evidence(log)
        if evidence is None:
            continue
        production = evidence.get("production_execution") or {}
        request = production.get("execution_request") or {}
        target = {
            "target_asset_version_id": qualification["asset_version_id"],
            "target_content_hash": candidate_hash,
            "generation_operation_id": qualification["generation_operation_id"],
            "generator_operation_name": generator,
        }
        if (
            qualification["provider_model_call_content_hash"] != model_hash
            or model_hash != snapshot_hash(log)
            or qualification["provider_evidence_hash"] != snapshot_hash(evidence)
            or qualification["provider_result_hash"]
            != snapshot_hash(evidence.get("result"))
            or qualification["provider_route_snapshot_id"]
            != (production.get("route_snapshot") or {}).get("route_snapshot_id")
            or log.get("operation_id") != qualification["evaluation_operation_id"]
            or log.get("attempt_id") != qualification["evaluation_attempt_id"]
            or log.get("target_lineage") != target
            or request.get("operation_id") != qualification["evaluation_operation_id"]
            or request.get("attempt_id") != qualification["evaluation_attempt_id"]
            or request.get("project_id") != project_id
            or request.get("external_effect_id") != evaluator_id
            or evaluated.get("candidate_asset_version_id")
            != qualification["asset_version_id"]
            or evaluated.get("candidate_content_hash") != candidate_hash
            or evaluated.get("generation_operation_id")
            != qualification["generation_operation_id"]
            or evaluated.get("evaluation_operation_id")
            != qualification["evaluation_operation_id"]
            or evaluated.get("evaluation_attempt_id")
            != qualification["evaluation_attempt_id"]
            or evaluated.get("evaluator_execution_class") != "MODEL_PROVIDER"
            or evaluated.get("evaluation_evidence_hash")
            != qualification["evaluation_evidence_hash"]
            or evaluated.get("evaluation") != evidence.get("result")
            or qualification["provider_model_call_asset_version_id"]
            not in evaluated.get("provider_evidence_asset_version_ids", ())
        ):
            continue
        try:
            verified = validate_narrative_qualification(
                generator_operation_name=generator,
                value=evidence.get("result"),
                require_pass=False,
            )
        except (KernelError, TypeError, ValueError):
            continue
        matching = [
            receipt
            for receipt in verified.receipts
            if receipt.layer.value == qualification["design_layer"]
        ]
        if (
            len(matching) != 1
            or matching[0].status != qualification["qualification_status"]
        ):
            continue
        groups[(effect_id, qualification["evaluation_operation_id"])].append(row)
    result = {}
    for (effect_id, evaluation_id), rows in groups.items():
        if effect_id in result:
            continue
        profiles = required_qualification_profiles(rows[0][3])
        expected = {(p.layer.value, p.profile_id, p.profile_hash) for p in profiles}
        actual = {
            (r[1]["design_layer"], r[1]["profile_id"], r[1]["profile_hash"])
            for r in rows
        }
        if not expected or actual != expected or len(rows) != len(expected):
            continue
        statuses = {r[1]["qualification_status"] for r in rows}
        accepted = (
            False if "FAIL" in statuses else True if statuses == {"PASS"} else None
        )
        qualification_status = (
            "FAIL"
            if "FAIL" in statuses
            else "PASS"
            if statuses == {"PASS"}
            else "INSUFFICIENT"
            if "INSUFFICIENT" in statuses
            else ""
        )
        if accepted is not None or qualification_status == "INSUFFICIENT":
            result[effect_id] = {
                "accepted": accepted,
                "metric": "DOMAIN_GATE_ACCEPTANCE.v1",
                "qualification_status": qualification_status,
                "evidence_refs": [
                    "narrative-qualification:" + r[1]["qualification_id"] for r in rows
                ],
                "evaluation_operation_id": evaluation_id,
            }
    return result


def planning_validation_failures(
    cursor: Any, *, project_id: str, effect_ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    if not effect_ids:
        return {}
    cursor.execute(
        """SELECT effect.external_effect_id,validation.validation_report_id,
                  validation.generation_operation_id,validation.validation_kind,
                  validation.report,validation.report_hash,
                  candidate.asset_version_id,candidate.content_hash,candidate.content,
                  model.asset_version_id,model.content_hash,model.content
           FROM authority_story_planning_validation_report validation
           JOIN authority_asset_version candidate
             ON candidate.asset_version_id=validation.candidate_asset_version_id
           JOIN authority_asset candidate_asset ON candidate_asset.asset_id=candidate.asset_id
             AND candidate_asset.project_id=validation.project_id
             AND candidate_asset.asset_type='planning_generation_candidate'
           JOIN authority_story_planning_generation generation
             ON generation.operation_id=validation.generation_operation_id
             AND generation.project_id=validation.project_id
             AND generation.candidate_asset_version_id=candidate.asset_version_id
           JOIN authority_story_planning_candidate generated
             ON generated.generation_id=generation.generation_id
             AND generated.project_id=validation.project_id
             AND generated.candidate_asset_version_id=candidate.asset_version_id
             AND generated.content_hash=candidate.content_hash
           JOIN authority_external_effect effect
             ON effect.external_effect_id=candidate.content #>> '{execution_evidence,external_receipt_ref}'
             AND effect.project_id=validation.project_id
             AND effect.operation_id=validation.generation_operation_id
             AND effect.status='SUCCEEDED'
           JOIN authority_asset model_asset ON model_asset.project_id=validation.project_id
             AND model_asset.asset_type='model_call_log'
           JOIN authority_asset_version model ON model.asset_id=model_asset.asset_id
             AND COALESCE(model.content->'provider_evidence',model.content)
                 #>> '{production_execution,execution_request,external_effect_id}'=effect.external_effect_id
           WHERE validation.project_id=%s AND effect.external_effect_id=ANY(%s)
             AND validation.status='FAIL'
             AND validation.validation_kind IN ('STRUCTURAL','SEMANTIC')
           ORDER BY validation.created_at,validation.validation_report_id,
                    model.created_at DESC,model.asset_version_id""",
        [project_id, list(effect_ids)],
    )
    result: dict[str, dict[str, Any]] = {}
    for (
        effect_id,
        validation_id,
        generation_operation_id,
        validation_kind,
        report,
        report_hash,
        candidate_id,
        candidate_hash,
        candidate,
        model_id,
        model_hash,
        model,
    ) in cursor.fetchall():
        if effect_id in result:
            continue
        execution = candidate.get("execution_evidence") or {}
        evidence = _real_evidence(model)
        request = (
            (evidence or {})
            .get("production_execution", {})
            .get("execution_request", {})
        )
        if (
            evidence is None
            or model_hash != snapshot_hash(model)
            or candidate_hash != snapshot_hash(candidate)
            or report_hash != snapshot_hash(report)
            or validation_id != report_hash
            or report.get("status") != "FAIL"
            or report.get("validation_kind") != validation_kind
            or report.get("candidate_asset_version_id") != candidate_id
            or execution.get("operation_id") != generation_operation_id
            or execution.get("external_receipt_ref") != effect_id
            or execution.get("real_provider_proven") is not True
            or execution.get("fixture_protocol_only") is True
            or request.get("project_id") != project_id
            or request.get("operation_id") != generation_operation_id
            or request.get("external_effect_id") != effect_id
        ):
            continue
        result[effect_id] = {
            "accepted": False,
            "failure_class": "SCHEMA_REJECTION"
            if validation_kind == "STRUCTURAL"
            else "QUALITY_FAILURE",
            "metric": "DOMAIN_GATE_ACCEPTANCE.v1",
            "validation_kind": validation_kind,
            "error_code": str(report.get("error_code") or ""),
            "evidence_refs": [
                "planning-validation:" + report_hash,
                "asset-version:" + candidate_id,
                "asset-version:" + model_id,
            ],
        }
    return result


def source_gate_outcomes(
    cursor: Any, *, project_id: str, effect_ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    if not effect_ids:
        return {}
    cursor.execute(
        """SELECT generator.external_effect_id,target.asset_version_id,target.content_hash,target.content,
                  reviewer.external_effect_id,reviewer.operation_id,reviewer.request_payload,
                  review.asset_version_id,review.content_hash,review.content,work.work_id,work.result
           FROM authority_external_effect reviewer
           JOIN authority_operation operation ON operation.operation_id=reviewer.operation_id
             AND operation.project_id=reviewer.project_id AND operation.status='SUCCEEDED'
           JOIN authority_source_import_work work ON work.operation_id=reviewer.operation_id
             AND work.project_id=reviewer.project_id AND work.status='SUCCEEDED'
           JOIN authority_asset_version target ON target.asset_version_id=reviewer.request_payload
             #>> '{input,review_target,execution_asset_version_id}'
           JOIN authority_asset target_asset ON target_asset.asset_id=target.asset_id
             AND target_asset.project_id=reviewer.project_id AND target_asset.asset_type='model_call_log'
           JOIN authority_external_effect generator ON generator.external_effect_id=
             COALESCE(target.content->'provider_evidence',target.content) #>> '{production_execution,execution_request,external_effect_id}'
             AND generator.project_id=reviewer.project_id AND generator.operation_id<>reviewer.operation_id
             AND generator.status='SUCCEEDED'
             AND COALESCE(target.content->'provider_evidence',target.content)
                 #>> '{production_execution,execution_request,operation_id}'=generator.operation_id
             AND COALESCE(target.content->'provider_evidence',target.content)
                 #>> '{production_execution,execution_request,project_id}'=generator.project_id
           JOIN authority_asset review_asset ON review_asset.project_id=reviewer.project_id
             AND review_asset.asset_type='model_call_log'
           JOIN authority_asset_version review ON review.asset_id=review_asset.asset_id
             AND COALESCE(review.content->'provider_evidence',review.content)
                 #>> '{production_execution,execution_request,external_effect_id}'=reviewer.external_effect_id
           WHERE reviewer.project_id=%s AND reviewer.status='SUCCEEDED'
             AND generator.external_effect_id=ANY(%s)
           ORDER BY review.created_at,review.asset_version_id""",
        [project_id, list(effect_ids)],
    )
    result = {}
    for (
        effect_id,
        target_id,
        target_hash,
        target,
        review_id,
        operation_id,
        payload,
        log_id,
        log_hash,
        log,
        work_id,
        work,
    ) in cursor.fetchall():
        if effect_id in result or _real_evidence(target) is None:
            continue
        evidence = _real_evidence(log)
        binding = log.get("narrative_review_binding") or {}
        review = binding.get("review") or {}
        frozen_target = (payload.get("input") or {}).get("review_target")
        request = (
            (evidence or {})
            .get("production_execution", {})
            .get("execution_request", {})
        )
        if (
            evidence is None
            or target_hash != snapshot_hash(target)
            or log_hash != snapshot_hash(log)
            or binding.get("target_hash") != snapshot_hash(frozen_target)
            or request.get("operation_id") != operation_id
            or request.get("project_id") != project_id
            or request.get("external_effect_id") != review_id
            or work.get("phase") != "REVIEW"
            or work.get("output_validation") != "PASSED"
            or work.get("review") != review
            or work.get("semantic_review_status") != review.get("decision")
        ):
            continue
        decision = review.get("decision")
        issues = work.get("issues")
        if not isinstance(issues, list):
            continue
        accepted = (
            True
            if decision == "ACCEPT_IN_SCOPE"
            and not any(item.get("severity") == "BLOCKING" for item in issues)
            else False
            if decision == "REVISE"
            else None
        )
        if accepted is not None:
            result[effect_id] = {
                "accepted": accepted,
                "metric": "DOMAIN_GATE_ACCEPTANCE.v1",
                "evidence_refs": [
                    "asset-version:" + target_id,
                    "asset-version:" + log_id,
                    "source-import-work:" + work_id,
                ],
                "evaluation_operation_id": operation_id,
            }
    return result


def domain_gate_outcomes(
    cursor: Any, *, project_id: str, effect_ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    from novel_forge.modules.chapter_quality_authority.reference_sampling import chapter_reference_outcomes
    from novel_forge.modules.story_planning_runtime.world_sampling import world_reference_outcomes
    from novel_forge.modules.story_design_authority.evaluation_reference import narrative_reference_outcomes

    planning = planning_gate_outcomes(
        cursor, project_id=project_id, effect_ids=effect_ids
    )
    failures = planning_validation_failures(
        cursor, project_id=project_id, effect_ids=effect_ids
    )
    for effect_id, failure in failures.items():
        qualification = planning.get(effect_id, {})
        evidence_refs = list(
            dict.fromkeys(
                [
                    *qualification.get("evidence_refs", ()),
                    *failure.get("evidence_refs", ()),
                ]
            )
        )
        if (
            failure["validation_kind"] == "SEMANTIC"
            and qualification.get("qualification_status") == "INSUFFICIENT"
        ):
            failure = {
                **failure,
                "accepted": None,
                "failure_class": "AMBIGUOUS_JUDGE",
            }
        planning[effect_id] = {
            **qualification,
            **failure,
            "evidence_refs": evidence_refs,
        }
    return {
        **planning,
        **source_gate_outcomes(cursor, project_id=project_id, effect_ids=effect_ids),
        **chapter_reference_outcomes(cursor, project_id=project_id, effect_ids=list(effect_ids)),
        **world_reference_outcomes(cursor, project_id=project_id, effect_ids=list(effect_ids)),
        **narrative_reference_outcomes(cursor, project_id=project_id, effect_ids=list(effect_ids)),
    }
