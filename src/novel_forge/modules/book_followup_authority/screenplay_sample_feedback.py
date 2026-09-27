from __future__ import annotations

from typing import Any, Mapping, Sequence

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.routing_bootstrap import authorization_hash
from .screenplay import SCREENPLAY_STAGES, SCREENPLAY_DIMENSIONS
from .screenplay_sampling import SCREENPLAY_SAMPLE_TYPE, SCREENPLAY_SAMPLE_PROTOCOL, require_sample, validate_screenplay_sample_origin

SCREENPLAY_ANNOTATION_VERSION = "2.6.0"
REVIEWER_DIMENSIONS = ("finding_precision", "missed_relationships", "evidence_fidelity", "disposition_fit")


def screenplay_reference_contract(stage: str, producer_contract_hash: str) -> dict[str, Any]:
    if stage not in SCREENPLAY_STAGES or len(producer_contract_hash) != 71 or not producer_contract_hash.startswith("sha256:"):
        raise ValueError("SCREENPLAY_REFERENCE_CONTRACT_INVALID")
    dimensions = REVIEWER_DIMENSIONS if stage == "screenplay_review" else SCREENPLAY_DIMENSIONS
    return {"protocol_version": SCREENPLAY_SAMPLE_PROTOCOL, "task_type": stage,
        "producer_contract_hash": producer_contract_hash, "dimensions": list(dimensions),
        "independent_blind_humans_required": 2, "independent_adjudicator_required": True,
        "maximum_score_interval_width": 20, "score_basis": "MINIMUM_ADJUDICATED_LOWER_ENDPOINT",
        "sample_promotion_allowed": False}


def require_screenplay_reference_subject(cursor: Any, *, project_id: str, binding: Mapping[str, Any]) -> dict[str, Any]:
    subject = require_sample(cursor, project_id=project_id, binding=binding)
    cursor.execute("SELECT command_payload->'payload' FROM authority_operation WHERE project_id=%s AND operation_id=%s",
        [project_id, subject["generation_operation_id"]])
    payload = cursor.fetchone()[0]
    frozen = validate_screenplay_sample_origin(cursor, project_id=project_id, payload=payload)
    cursor.execute("SELECT actor_id FROM authority_operation WHERE project_id=%s AND operation_id=%s", [project_id, payload["logical_key"]])
    actors = {subject["generation_actor_id"], cursor.fetchone()[0]}
    upstream = subject["content"]["upstream_sample"]
    depth = 0
    while upstream:
        depth += 1
        if depth > 12:
            raise KernelError("SCREENPLAY_SAMPLE_LINEAGE_INVALID", "Sample lineage exceeds the approved revision scope")
        prior = require_sample(cursor, project_id=project_id, binding=upstream)
        actors.add(prior["generation_actor_id"])
        upstream = prior["content"]["upstream_sample"]
    return {**subject, "source": frozen["source"], "generation_actor_ids": sorted(actors)}


def screenplay_annotation_scope(subject: Mapping[str, Any]) -> dict[str, Any]:
    source = subject["source"]
    numbers = [unit["chapter_number"] for unit in source["accepted_source_evidence"]["units"]]
    first, last = min(numbers), max(numbers)
    stage = subject["content"]["stage"]
    return {"protocol_version": SCREENPLAY_SAMPLE_PROTOCOL,
        "evaluation_version": ":".join((SCREENPLAY_SAMPLE_PROTOCOL, stage, subject["producer_contract_hash"], source["source_digest"])),
        "scope_type": "CHAPTER" if first == last else "ARC", "chapter_start": first, "chapter_end": last}


def validate_screenplay_annotation(*, subject: Mapping[str, Any], annotation: Mapping[str, Any], human: bool) -> None:
    scope = screenplay_annotation_scope(subject)
    contract = screenplay_reference_contract(subject["content"]["stage"], subject["producer_contract_hash"])
    if annotation.get("dimension") not in contract["dimensions"] or any(annotation.get(key) != value for key, value in scope.items()):
        raise KernelError("SCREENPLAY_REFERENCE_SCOPE_INVALID", "Labels bind the exact task, producer, source edition and dimension")
    if not human:
        return
    if annotation.get("evaluator_id") in subject["generation_actor_ids"]:
        raise KernelError("SCREENPLAY_REFERENCE_NOT_INDEPENDENT", "A source operator or sample generator cannot label its own chain")
    evidence = annotation.get("evidence")
    if not isinstance(evidence, (list, tuple)) or not evidence:
        raise KernelError("SCREENPLAY_REFERENCE_EVIDENCE_REQUIRED", "Independent labels require source and scene or finding evidence")
    content, source = subject["content"], subject["source"]
    candidate = content["input_candidate"] if content["stage"] == "screenplay_review" else content["sampled_output"]
    scenes = {scene["scene_id"]: scene for scene in candidate["scenes"]}
    units = {unit["unit_id"]: unit for unit in source["source_units"]}
    for item in evidence:
        scene = scenes.get(item.get("scene_id")) if isinstance(item, Mapping) else None
        unit = units.get(item.get("unit_id")) if isinstance(item, Mapping) else None
        if (not scene or not unit or item.get("source_digest") != source["source_digest"]
            or item["unit_id"] not in scene["source_unit_ids"] or not item.get("observation")
            or type(item.get("start")) is not int or type(item.get("end")) is not int
            or not 0 <= item["start"] < item["end"] <= len(unit["text"])
            or item.get("quote") != unit["text"][item["start"]:item["end"]]
            or item.get("beat_id") and item["beat_id"] not in {beat["beat_id"] for beat in scene["beats"]}):
            raise KernelError("SCREENPLAY_REFERENCE_EVIDENCE_INVALID", "Evidence must locate the exact source passage and real scene/beat")
        if content["stage"] == "screenplay_review":
            paths = {"/findings", *("/findings/" + str(i) for i in range(len(content["sampled_output"]["findings"])))}
            if item.get("sample_path") not in paths:
                raise KernelError("SCREENPLAY_REFERENCE_EVIDENCE_INVALID", "Reviewer labels must locate the report as well as its source")


def screenplay_sample_outcomes(cursor: Any, *, project_id: str, effect_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    from novel_forge.modules.authority_handler_runtime.generator_feedback import adjudicated_generator_score
    from novel_forge.modules.chapter_quality_authority.reference_sampling import (
        _native_label, require_adjudicated_reference, reference_label_classes, reference_provider_result,
    )
    if not effect_ids:
        return {}
    cursor.execute("""SELECT effect.external_effect_id,effect.operation_id,effect.request_payload,version.asset_version_id,version.content_hash
        FROM authority_external_effect effect JOIN authority_operation operation USING(operation_id)
        JOIN authority_operation_output_asset output ON output.operation_id=effect.operation_id AND output.role='primary'
        JOIN authority_asset_version version ON version.asset_version_id=output.asset_version_id AND version.content_hash=output.content_hash
        JOIN authority_asset asset ON asset.asset_id=version.asset_id AND asset.project_id=effect.project_id
        WHERE effect.project_id=%s AND effect.external_effect_id=ANY(%s) AND effect.status='SUCCEEDED'
          AND operation.status='SUCCEEDED' AND asset.asset_type=%s""", [project_id, list(effect_ids), SCREENPLAY_SAMPLE_TYPE])
    result = {}
    for effect_id, operation_id, request, asset_id, digest in cursor.fetchall():
        decision = request.get("_production_execution", {}).get("capability_runtime", {}).get("routing_decision", {})
        task = decision.get("task", {})
        producer, stage = task.get("producer_contract_hash"), task.get("task_type")
        if not producer or producer != authorization_hash(task.get("producer_contract")) or stage not in SCREENPLAY_STAGES:
            continue
        try:
            subject = require_screenplay_reference_subject(cursor, project_id=project_id, binding={"asset_version_id": asset_id, "content_hash": digest})
            if subject["generation_operation_id"] != operation_id or subject["producer_contract_hash"] != producer or subject["content"]["stage"] != stage:
                continue
            scope = screenplay_annotation_scope(subject)
            contract = screenplay_reference_contract(stage, producer)
            cursor.execute("SELECT attempt_id FROM authority_attempt WHERE operation_id=%s AND status='SUCCEEDED' ORDER BY attempt_number DESC LIMIT 1", [operation_id])
            attempt = cursor.fetchone()
            if not attempt:
                continue
            provider = reference_provider_result(cursor, project_id=project_id, operation_id=operation_id, attempt_id=attempt[0], stage=stage)
            actual = dict(subject["content"]["sampled_output"])
            if stage != "screenplay_review":
                actual.pop("candidate_digest", None)
            if not provider["real_model_call"] or provider["result"] != actual:
                continue
            cursor.execute("SELECT version.asset_version_id,version.content_hash FROM authority_asset_version version JOIN authority_asset asset USING(asset_id) WHERE asset.project_id=%s AND asset.asset_type='adjudicated_evaluation' AND version.lifecycle='ACTIVE' AND version.governance='CLEAR' AND version.content->>'subject_asset_version_id'=%s AND version.content->>'protocol_version'=%s AND version.content->>'evaluation_version'=%s ORDER BY version.created_at,version.asset_version_id",
                [project_id, asset_id, SCREENPLAY_SAMPLE_PROTOCOL, scope["evaluation_version"]])
            labels = [{"asset_version_id": row[0], "content_hash": row[1]} for row in cursor.fetchall()]
            reference = require_adjudicated_reference(cursor, project_id=project_id,
                binding={"protocol_version": SCREENPLAY_SAMPLE_PROTOCOL, "adjudications": labels}, target_id=asset_id, target_hash=digest,
                generators=subject["generation_actor_ids"], evaluator_actor_id=subject["generation_actor_id"],
                chapter=scope["chapter_start"], chapter_end=scope["chapter_end"], scope_type=scope["scope_type"],
                expected_dimensions=contract["dimensions"], allowed_statuses={"PASSED", "PASSED_WITH_WARNINGS", "FAILED", "BLOCKED", "NEEDS_REVISION"})
            if not reference_label_classes(cursor, project_id=project_id, reference=reference, stage=stage):
                continue
            for label in labels:
                adjudication, _, _ = _native_label(cursor, project_id=project_id, asset_version_id=label["asset_version_id"], asset_type="adjudicated_evaluation", operation_name="quality.adjudication.record", actor_field="adjudicator_id")
                validate_screenplay_annotation(subject=subject, annotation=adjudication, human=False)
                for human_id in adjudication["source_human_evaluation_asset_version_ids"]:
                    human, _, _ = _native_label(cursor, project_id=project_id, asset_version_id=human_id, asset_type="human_evaluation", operation_name="quality.human_evaluation.record", actor_field="evaluator_id")
                    validate_screenplay_annotation(subject=subject, annotation=human, human=True)
            score = adjudicated_generator_score(reference["labels"])
        except (KernelError, ValueError, TypeError, KeyError):
            continue
        if score is None:
            continue
        reviewer = stage == "screenplay_review"
        prefix = "independent" if reviewer else "generator"
        result[effect_id] = {"metric": "INDEPENDENT_SCREENPLAY_ADJUDICATION.v1", "accepted": None,
            prefix + "_quality_score": score, prefix + "_protocol_hash": authorization_hash(contract),
            prefix + "_risk": decision["policy"]["risk"], prefix + "_context_tokens": task["input_tokens"],
            prefix + "_sample_identity": authorization_hash({"task_type": stage, "text": [
                " ".join(beat["text"].split()) for scene in (subject["content"]["input_candidate"] if reviewer else actual)["scenes"] for beat in scene["beats"]]}),
            "evidence_refs": ["asset-version:" + asset_id, "asset-version:" + provider["model_call_asset_version_id"],
                *("asset-version:" + row["asset_version_id"] for row in labels)],
            "assessment_basis": "INDEPENDENT_HUMAN_ADJUDICATION", "sample_promoted": False}
    return result
