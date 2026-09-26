from __future__ import annotations

from collections import defaultdict
import re
from typing import Any, Mapping, Sequence

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.chapter_quality_authority.generator_reference import (
    DIRECT_GENERATOR_DIMENSIONS, generator_reference_contract,
)
from novel_forge.modules.production_execution.cost_routing import snapshot_hash


def independent_model_identities(generator: Mapping[str, Any], evaluator: Mapping[str, Any],
    generation_evidence: Mapping[str, Any], evaluation_evidence: Mapping[str, Any]) -> bool:
    from novel_forge.modules.production_execution.routing_catalog import deepseek_model_revision

    identities = []
    for candidate, evidence in ((generator, generation_evidence), (evaluator, evaluation_evidence)):
        model, revision = candidate.get("model"), candidate.get("model_revision")
        if (not model or not revision or evidence.get("real_model_call") is not True
            or evidence.get("fixture_protocol_only") or evidence.get("model_id") != model
            or evidence.get("provider_id") != candidate.get("provider")):
            return False
        if candidate.get("provider") == "deepseek":
            try:
                if revision != deepseek_model_revision(model):
                    return False
            except ValueError:
                return False
        elif candidate.get("provider") != "codex-cli" or not re.fullmatch(r"gpt-\d+(?:\.\d+)?(?:-[a-z0-9]+)*", model) or any(
            part in {"latest", "default", "auto"} for part in model.split("-")):
            return False
        process = evidence.get("production_execution", {}).get("process_evidence", {})
        identities.append((model.casefold(), revision.casefold(), process.get("served_model_identity_hash") or evidence.get("served_model_identity_hash")))
    return all(left != right for left, right in zip(identities[0][:2], identities[1][:2], strict=True)) and not (
        identities[0][2] and identities[0][2] == identities[1][2])


def adjudicated_generator_score(labels: Sequence[Mapping[str, Any]]) -> float | None:
    if not labels or len({row["dimension"] for row in labels}) != len(labels):
        return None
    values = []
    for row in labels:
        interval = row.get("score_range")
        if (not isinstance(interval, (list, tuple)) or len(interval) != 2
            or any(type(value) not in {int, float} for value in interval)
            or not 0 <= interval[0] <= interval[1] <= 100 or interval[1] - interval[0] > 20):
            return None
        if row["status"] not in {"PASS", "PASSED", "FAIL", "FAILED", "REVISION_REQUIRED", "REVISE", "ACCEPT", "PASSED_WITH_WARNINGS", "NEEDS_REVISION", "BLOCKED"}:
            return None
        values.append(0.0 if row["status"] in {"FAIL", "FAILED", "REVISION_REQUIRED", "REVISE", "NEEDS_REVISION", "BLOCKED"} else interval[0] / 100)
    return min(values)


def generator_sample_outcomes(cursor: Any, *, project_id: str, effect_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    from novel_forge.modules.chapter_quality_authority.reference_sampling import chapter_reference_outcomes
    from novel_forge.modules.chapter_quality_authority.reference_subject import require_reference_subject, require_planning_reference_subject
    from novel_forge.modules.story_planning_runtime.world_sampling import world_reference_outcomes
    from novel_forge.modules.story_design_authority.evaluation_reference import narrative_reference_outcomes

    if not effect_ids:
        return {}
    cursor.execute(
        """SELECT generator.external_effect_id, generator.operation_id, generator.request_payload,
                  target.asset_version_id,target.content_hash,asset.asset_type,
                  evaluator.external_effect_id,evaluator.request_payload
           FROM authority_external_effect generator
           JOIN authority_operation_output_asset output ON output.operation_id=generator.operation_id AND output.role='primary'
           JOIN authority_asset_version target ON target.asset_version_id=output.asset_version_id AND target.content_hash=output.content_hash
           JOIN authority_asset asset ON asset.asset_id=target.asset_id AND asset.project_id=generator.project_id
             AND asset.asset_type IN ('chapter_provider_sample','world_provider_sample','planning_generation_candidate')
           JOIN authority_operation review ON review.project_id=generator.project_id AND review.status='SUCCEEDED'
             AND target.asset_version_id=COALESCE(
                 review.command_payload #>> '{payload,chapter_sampling,generation_sample,asset_version_id}',
                 review.command_payload #>> '{payload,world_sampling,generation_sample,asset_version_id}',
                 review.command_payload #>> '{payload,candidate_asset_version_id}')
           JOIN authority_external_effect evaluator ON evaluator.operation_id=review.operation_id
             AND evaluator.project_id=generator.project_id AND evaluator.status='SUCCEEDED'
           WHERE generator.project_id=%s AND generator.external_effect_id=ANY(%s) AND generator.status='SUCCEEDED'
             AND target.eligibility='INELIGIBLE'
           ORDER BY evaluator.created_at,evaluator.external_effect_id""",
        [project_id, list(effect_ids)],
    )
    rows = cursor.fetchall()
    cursor.execute("""SELECT external_effect_id,evidence FROM authority_external_effect_dispatch
        WHERE external_effect_id=ANY(%s) AND status='SUCCEEDED' ORDER BY generation DESC""",
        [list({identity for row in rows for identity in (row[0], row[6])})])
    provider_evidence = {}
    for identity, evidence in cursor.fetchall():
        provider_evidence.setdefault(identity, evidence)
    ids = list({row[6] for row in rows})
    evaluations = {
        **chapter_reference_outcomes(cursor, project_id=project_id, effect_ids=ids),
        **world_reference_outcomes(cursor, project_id=project_id, effect_ids=ids),
        **narrative_reference_outcomes(cursor, project_id=project_id, effect_ids=ids),
    }
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for effect_id, operation_id, request, target_id, digest, kind, evaluator_id, evaluator_request in rows:
        assessment = evaluations.get(evaluator_id, {}).get("generator_assessment")
        if not assessment or (assessment["target_asset_version_id"], assessment["target_content_hash"]) != (target_id, digest):
            continue
        decision = request.get("_production_execution", {}).get("capability_runtime", {}).get("routing_decision", {})
        evaluator = evaluator_request.get("_production_execution", {}).get("capability_runtime", {}).get("routing_decision", {})
        evaluator_contract = evaluator.get("task", {}).get("producer_contract_hash")
        if not evaluator_contract or evaluator_contract != snapshot_hash(evaluator.get("task", {}).get("producer_contract")):
            continue
        candidate = decision.get("selected", {}).get("candidate", {})
        judge = evaluator.get("selected", {}).get("candidate", {})
        if not independent_model_identities(candidate, judge, provider_evidence.get(effect_id, {}), provider_evidence.get(evaluator_id, {})):
            continue
        binding = {"asset_version_id": target_id, "content_hash": digest}
        try:
            subject = (require_planning_reference_subject(cursor, project_id=project_id, binding=binding)
                if kind == "planning_generation_candidate" else require_reference_subject(cursor, project_id=project_id,
                    binding=binding, allowed_types=frozenset({kind})))
        except (KernelError, ValueError, TypeError, KeyError):
            continue
        if subject["generation_operation_id"] != operation_id:
            continue
        task = decision.get("task") or {}
        if not task.get("producer_contract_hash") or task["producer_contract_hash"] != snapshot_hash(task.get("producer_contract")):
            continue
        contract = generator_reference_contract(task["task_type"], task["producer_contract_hash"])
        if (assessment.get("protocol_version") != contract["protocol_version"] or any(
            label["evaluation_version"] != contract["evaluation_version"] for label in assessment["labels"]
        )):
            continue
        score = adjudicated_generator_score(assessment["labels"])
        if score is None:
            continue
        content = subject["content"]
        output = content.get("sampled_output", content.get("candidate_payload"))
        if output is None:
            continue
        if isinstance(output, dict) and isinstance(output.get("text"), str):
            output = {"text": " ".join(output["text"].split())}
        grouped[effect_id].append({
            "generator_quality_score": score,
            "generator_protocol_hash": snapshot_hash({
                "version": "native-generator-adjudication.v1", "task_type": task["task_type"],
                "reference_protocol_hash": evaluations[evaluator_id]["reference_protocol_hash"],
                "evaluator_producer_contract_hash": evaluator.get("task", {}).get("producer_contract_hash"),
                "score_basis": "MINIMUM_ADJUDICATED_LOWER_ENDPOINT",
            }),
            "generator_risk": decision["policy"]["risk"], "generator_context_tokens": task["input_tokens"],
            "generator_sample_identity": snapshot_hash({"task_type": task["task_type"], "output": output}),
            "evidence_refs": ["asset-version:" + target_id, *evaluations[evaluator_id]["evidence_refs"]],
        })
    result = direct_generator_outcomes(cursor, project_id=project_id, effect_ids=effect_ids)
    for identity, observations in grouped.items():
        if len({row["generator_protocol_hash"] for row in observations}) != 1:
            continue
        result[identity] = {**min(observations, key=lambda row: row["generator_quality_score"]),
            "metric": "INDEPENDENT_GENERATOR_ADJUDICATION.v1", "accepted": None,
            "evidence_refs": sorted({ref for row in observations for ref in row["evidence_refs"]}),
            "assessment_basis": "INDEPENDENT_HUMAN_ADJUDICATION", "sample_promoted": False}
    return result



def direct_generator_outcomes(cursor: Any, *, project_id: str, effect_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    from novel_forge.modules.chapter_quality_authority.reference_sampling import require_adjudicated_reference, reference_label_classes, reference_provider_result
    from novel_forge.modules.chapter_quality_authority.reference_subject import require_reference_subject

    cursor.execute(
        """SELECT effect.external_effect_id,effect.operation_id,effect.request_payload,
                  version.asset_version_id,version.content_hash
           FROM authority_external_effect effect
           JOIN authority_operation_output_asset output ON output.operation_id=effect.operation_id AND output.role='primary'
           JOIN authority_asset_version version ON version.asset_version_id=output.asset_version_id AND version.content_hash=output.content_hash
           JOIN authority_asset asset ON asset.asset_id=version.asset_id AND asset.project_id=effect.project_id
           WHERE effect.project_id=%s AND effect.external_effect_id=ANY(%s) AND effect.status='SUCCEEDED'
             AND asset.asset_type='chapter_provider_sample' AND version.content->>'stage'=ANY(%s)""",
        [project_id, list(effect_ids), list(DIRECT_GENERATOR_DIMENSIONS)],
    )
    result = {}
    for effect_id, operation_id, request, target_id, digest in cursor.fetchall():
        decision = request.get("_production_execution", {}).get("capability_runtime", {}).get("routing_decision", {})
        task = decision.get("task", {})
        producer = task.get("producer_contract_hash")
        if not producer or producer != snapshot_hash(task.get("producer_contract")):
            continue
        try:
            subject = require_reference_subject(cursor, project_id=project_id,
                binding={"asset_version_id": target_id, "content_hash": digest})
            stage = subject["content"]["stage"]
            if subject["generation_operation_id"] != operation_id or task.get("task_type") != stage:
                continue
            contract = generator_reference_contract(stage, producer)
            cursor.execute(
                """SELECT version.asset_version_id,version.content_hash FROM authority_asset_version version
                   JOIN authority_asset asset USING(asset_id)
                   WHERE asset.project_id=%s AND asset.asset_type='adjudicated_evaluation'
                     AND version.lifecycle='ACTIVE' AND version.governance='CLEAR'
                     AND version.content->>'subject_asset_version_id'=%s
                     AND version.content->>'protocol_version'=%s AND version.content->>'evaluation_version'=%s
                   ORDER BY version.created_at,version.asset_version_id""",
                [project_id, target_id, contract["protocol_version"], contract["evaluation_version"]],
            )
            labels = [{"asset_version_id": row[0], "content_hash": row[1]} for row in cursor.fetchall()]
            reference = require_adjudicated_reference(cursor, project_id=project_id,
                binding={"protocol_version": contract["protocol_version"], "adjudications": labels},
                target_id=target_id, target_hash=digest, generators=[subject["generation_actor_id"]],
                evaluator_actor_id=subject["generation_actor_id"], chapter=subject["content"]["sampled_output"]["chapter"],
                expected_dimensions=DIRECT_GENERATOR_DIMENSIONS[stage],
                allowed_statuses={"PASSED", "PASSED_WITH_WARNINGS", "FAILED", "BLOCKED", "NEEDS_REVISION"})
            if not reference_label_classes(cursor, project_id=project_id, reference=reference, stage=stage):
                continue
            provider = reference_provider_result(cursor, project_id=project_id, operation_id=operation_id,
                attempt_id=request["_production_execution"]["attempt_id"], stage=stage)
            if not provider["real_model_call"]:
                continue
            score = adjudicated_generator_score(reference["labels"])
        except (KernelError, ValueError, TypeError, KeyError):
            continue
        if score is None:
            continue
        result[effect_id] = {
            "metric": "INDEPENDENT_GENERATOR_ADJUDICATION.v1", "accepted": None,
            "generator_quality_score": score, "generator_protocol_hash": snapshot_hash(contract),
            "generator_risk": decision["policy"]["risk"], "generator_context_tokens": task["input_tokens"],
            "generator_sample_identity": snapshot_hash({"task_type": stage, "output": provider["result"]}),
            "evidence_refs": ["asset-version:" + target_id, *("asset-version:" + row["asset_version_id"] for row in labels)],
            "assessment_basis": "INDEPENDENT_HUMAN_ADJUDICATION", "sample_promoted": False,
        }
    return result
