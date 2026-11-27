from __future__ import annotations

from typing import Any, Mapping, Sequence

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.routing_bootstrap import authorization_hash, load_bootstrap_authorization

from .prose_sampling import PROSE_REVIEWER_PROTOCOL, PROSE_SAMPLE_DEFINITION, PROSE_SAMPLE_TYPE, validate_prose_sample_origin
from .prose_review import validate_window_report

PROSE_ANNOTATION_VERSION = "2.5.0"
PROSE_REVIEWER_DIMENSIONS = ("finding_precision", "missed_relationships", "evidence_fidelity", "disposition_fit")


def prose_reviewer_contract(producer_contract_hash: str) -> dict[str, Any]:
    if len(producer_contract_hash) != 71 or not producer_contract_hash.startswith("sha256:"):
        raise ValueError("PROSE_REVIEWER_PRODUCER_REQUIRED")
    return {"protocol_version": PROSE_REVIEWER_PROTOCOL, "task_type": "longform_prose_review",
        "producer_contract_hash": producer_contract_hash, "dimensions": list(PROSE_REVIEWER_DIMENSIONS),
        "dimension_criteria": {
            "finding_precision": "Higher scores mean fewer false or overstated findings.",
            "missed_relationships": "Higher scores mean fewer missed relationships within the frozen evidence scope.",
            "evidence_fidelity": "Higher scores mean exact citations and conclusions supported by those passages.",
            "disposition_fit": "Higher scores mean appropriate revision, future-only change, historical review or uncertainty disposition."},
        "scope_contract": "EXACT_FROZEN_PROSE_WINDOW.v1", "independent_blind_humans_required": 2,
        "independent_adjudicator_required": True, "maximum_score_interval_width": 20,
        "score_basis": "MINIMUM_ADJUDICATED_LOWER_ENDPOINT", "sample_promotion_allowed": False}


def prose_annotation_scope(*, producer_contract_hash: str, window: Mapping[str, Any]) -> dict[str, Any]:
    spans = window["window"]["spans"]
    first, last = min(span["chapter_number"] for span in spans), max(span["chapter_number"] for span in spans)
    exact = {"manifest_digest": window["manifest_digest"], "window_id": window["window"]["window_id"],
        "spans": [{key: span[key] for key in ("asset_version_id", "text_hash", "start", "end")} for span in spans]}
    return {"protocol_version": PROSE_REVIEWER_PROTOCOL,
        "evaluation_version": PROSE_REVIEWER_PROTOCOL + ":" + producer_contract_hash + ":" + authorization_hash(exact),
        "scope_type": "CHAPTER" if first == last else "ARC", "chapter_start": first, "chapter_end": last}


def require_prose_reference_subject(cursor: Any, *, project_id: str, binding: Mapping[str, Any]) -> dict[str, Any]:
    cursor.execute("""SELECT version.content,version.content_hash,operation.operation_id,operation.actor_id,
        operation.command_payload->'payload' FROM authority_asset_version version JOIN authority_asset asset USING(asset_id)
        JOIN authority_operation_output_asset output ON output.asset_version_id=version.asset_version_id AND output.content_hash=version.content_hash AND output.role='primary'
        JOIN authority_operation operation ON operation.operation_id=output.operation_id AND operation.project_id=asset.project_id
        WHERE asset.project_id=%s AND version.asset_version_id=%s AND asset.asset_type=%s
          AND version.lifecycle='ACTIVE' AND version.eligibility='INELIGIBLE' AND version.governance='CLEAR'
          AND operation.definition_name=%s AND operation.status='SUCCEEDED'""",
        [project_id, binding["asset_version_id"], PROSE_SAMPLE_TYPE, PROSE_SAMPLE_DEFINITION])
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise KernelError("QUALITY_REFERENCE_TARGET_INVALID", "prose annotations require a completed native ineligible sample")
    content, digest, operation_id, actor, payload = rows[0]
    snapshot = load_bootstrap_authorization(cursor, project_id=project_id, operation_id=operation_id, check_expiry=False)
    grant = snapshot["authorization"] if snapshot else {}
    if (digest != binding["content_hash"] or digest != authorization_hash(content)
        or content.get("schema_version") != "longform-prose-review-sample.v1" or content.get("stage") != "longform_prose_review"
        or content.get("production_eligible") is not False or content.get("routing_eligibility") != "BENCHMARK_ONLY"
        or grant.get("purpose") != "REFERENCE_EVALUATION" or grant.get("task_type") != "longform_prose_review"
        or content.get("authorization_id") != grant.get("authorization_id") or content.get("campaign") != grant.get("campaign")
        or content.get("source_window") != payload["input_versions"][0]
        or content.get("source_operation_id") != payload["prose_sampling"]["source_operation_id"]):
        raise KernelError("QUALITY_REFERENCE_TARGET_INVALID", "prose subject differs from its immutable native sample grant")
    window = validate_prose_sample_origin(cursor, project_id=project_id, payload=payload)
    validate_window_report(content["sampled_output"], manifest=window, window=window["window"])
    cursor.execute("SELECT actor_id FROM authority_operation WHERE operation_id=%s AND project_id=%s", [content["source_operation_id"], project_id])
    source_actor = cursor.fetchone()[0]
    return {**dict(binding), "asset_type": PROSE_SAMPLE_TYPE, "content": content,
        "generation_operation_id": operation_id, "generation_actor_id": actor, "source_actor_id": source_actor,
        "window": window, "producer_contract_hash": grant["producer_contract_hash"]}


def validate_prose_annotation(*, subject: Mapping[str, Any], annotation: Mapping[str, Any], human: bool) -> None:
    scope = prose_annotation_scope(producer_contract_hash=subject["producer_contract_hash"], window=subject["window"])
    if (annotation.get("dimension") not in PROSE_REVIEWER_DIMENSIONS
        or any(annotation.get(key) != value for key, value in scope.items())):
        raise KernelError("PROSE_REVIEWER_LABEL_SCOPE_INVALID", "reviewer labels must bind the declared task, producer and exact frozen window scope")
    if not human:
        return
    evidence = annotation.get("evidence")
    if not isinstance(evidence, (list, tuple)) or not evidence:
        raise KernelError("PROSE_REVIEWER_LABEL_EVIDENCE_INVALID", "reviewer quality requires located observations, not review success or coverage")
    report = subject["content"]["sampled_output"]
    source = subject["window"]
    paths = {"/findings", *("/findings/" + str(index) for index in range(len(report["findings"])))}
    for item in evidence:
        if (not isinstance(item, Mapping) or item.get("manifest_digest") != source["manifest_digest"]
            or item.get("window_id") != source["window"]["window_id"] or item.get("sample_path") not in paths
            or not isinstance(item.get("observation"), str) or not item["observation"].strip()):
            raise KernelError("PROSE_REVIEWER_LABEL_EVIDENCE_INVALID", "observations must locate both the sampled review and its exact manuscript window")
        matches = [span for span in source["window"]["spans"] if
            item.get("asset_version_id") == span["asset_version_id"] and item.get("text_hash") == span["text_hash"]
            and type(item.get("start")) is int and type(item.get("end")) is int
            and span["start"] <= item["start"] < item["end"] <= span["end"]
            and item.get("quote") == span["text"][item["start"] - span["start"]:item["end"] - span["start"]]]
        if not matches:
            raise KernelError("PROSE_REVIEWER_LABEL_EVIDENCE_INVALID", "reviewer observations require exact Unicode source citations")


def prose_sample_outcomes(cursor: Any, *, project_id: str, effect_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    from novel_forge.modules.authority_handler_runtime.generator_feedback import adjudicated_generator_score
    from novel_forge.modules.chapter_quality_authority.reference_sampling import (
        _native_label, require_adjudicated_reference, reference_label_classes, reference_provider_result,
    )

    if not effect_ids:
        return {}
    cursor.execute("""SELECT effect.external_effect_id,effect.operation_id,effect.request_payload,version.asset_version_id,
        version.content_hash FROM authority_external_effect effect
        JOIN authority_operation operation USING(operation_id)
        JOIN authority_operation_output_asset output ON output.operation_id=effect.operation_id AND output.role='primary'
        JOIN authority_asset_version version ON version.asset_version_id=output.asset_version_id AND version.content_hash=output.content_hash
        JOIN authority_asset asset ON asset.asset_id=version.asset_id AND asset.project_id=effect.project_id
        WHERE effect.project_id=%s AND effect.external_effect_id=ANY(%s) AND effect.status='SUCCEEDED'
          AND operation.status='SUCCEEDED' AND asset.asset_type=%s""", [project_id, list(effect_ids), PROSE_SAMPLE_TYPE])
    result = {}
    for effect_id, operation_id, request, asset_id, digest in cursor.fetchall():
        decision = request.get("_production_execution", {}).get("capability_runtime", {}).get("routing_decision", {})
        task = decision.get("task", {})
        producer = task.get("producer_contract_hash")
        if (not producer or producer != authorization_hash(task.get("producer_contract"))
            or task.get("task_type") != "longform_prose_review"):
            continue
        try:
            subject = require_prose_reference_subject(cursor, project_id=project_id, binding={"asset_version_id": asset_id, "content_hash": digest})
            if subject["generation_operation_id"] != operation_id or subject["producer_contract_hash"] != producer:
                continue
            scope = prose_annotation_scope(producer_contract_hash=producer, window=subject["window"])
            cursor.execute("SELECT attempt_id FROM authority_attempt WHERE operation_id=%s AND status='SUCCEEDED' ORDER BY attempt_number DESC LIMIT 1", [operation_id])
            attempt = cursor.fetchone()
            if not attempt:
                continue
            provider = reference_provider_result(cursor, project_id=project_id, operation_id=operation_id,
                attempt_id=attempt[0], stage="longform_prose_review")
            if not provider["real_model_call"] or provider["result"] != subject["content"]["sampled_output"]:
                continue
            cursor.execute("""SELECT version.asset_version_id,version.content_hash FROM authority_asset_version version
                JOIN authority_asset asset USING(asset_id) WHERE asset.project_id=%s AND asset.asset_type='adjudicated_evaluation'
                AND version.lifecycle='ACTIVE' AND version.governance='CLEAR' AND version.content->>'subject_asset_version_id'=%s
                AND version.content->>'protocol_version'=%s AND version.content->>'evaluation_version'=%s
                ORDER BY version.created_at,version.asset_version_id""", [project_id, asset_id, scope["protocol_version"], scope["evaluation_version"]])
            labels = [{"asset_version_id": row[0], "content_hash": row[1]} for row in cursor.fetchall()]
            reference = require_adjudicated_reference(cursor, project_id=project_id,
                binding={"protocol_version": PROSE_REVIEWER_PROTOCOL, "adjudications": labels}, target_id=asset_id, target_hash=digest,
                generators=[subject["generation_actor_id"], subject["source_actor_id"]], evaluator_actor_id=subject["generation_actor_id"],
                chapter=scope["chapter_start"], chapter_end=scope["chapter_end"], scope_type=scope["scope_type"],
                expected_dimensions=PROSE_REVIEWER_DIMENSIONS, allowed_statuses={"PASSED", "PASSED_WITH_WARNINGS", "FAILED", "BLOCKED", "NEEDS_REVISION"})
            if not reference_label_classes(cursor, project_id=project_id, reference=reference, stage="longform_prose_review"):
                continue
            for label in labels:
                adjudication, _, _ = _native_label(cursor, project_id=project_id, asset_version_id=label["asset_version_id"],
                    asset_type="adjudicated_evaluation", operation_name="quality.adjudication.record", actor_field="adjudicator_id")
                validate_prose_annotation(subject=subject, annotation=adjudication, human=False)
                for human_id in adjudication["source_human_evaluation_asset_version_ids"]:
                    human, _, _ = _native_label(cursor, project_id=project_id, asset_version_id=human_id,
                        asset_type="human_evaluation", operation_name="quality.human_evaluation.record", actor_field="evaluator_id")
                    validate_prose_annotation(subject=subject, annotation=human, human=True)
            score = adjudicated_generator_score(reference["labels"])
        except (KernelError, ValueError, TypeError, KeyError):
            continue
        if score is None:
            continue
        result[effect_id] = {"metric": "INDEPENDENT_REVIEWER_ADJUDICATION.v1", "accepted": None,
            "independent_quality_score": score, "independent_protocol_hash": authorization_hash(prose_reviewer_contract(producer)),
            "independent_risk": decision["policy"]["risk"], "independent_context_tokens": task["input_tokens"],
            "independent_sample_identity": authorization_hash({"task_type": "longform_prose_review",
                "accepted_text_hashes": sorted({span["text_hash"] for span in subject["window"]["window"]["spans"]})}),
            "evidence_refs": ["asset-version:" + asset_id, "asset-version:" + provider["model_call_asset_version_id"],
                *("asset-version:" + row["asset_version_id"] for row in labels)],
            "assessment_basis": "INDEPENDENT_HUMAN_ADJUDICATION", "sample_promoted": False}
    return result
