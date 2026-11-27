from __future__ import annotations

from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.routing_bootstrap import (
    CHAPTER_GENERATOR_TASKS, PLANNING_BOOTSTRAP_SOURCE_VERSIONS, authorization_hash, load_bootstrap_authorization,
)


REFERENCE_ANNOTATION_DEFINITIONS = {
    "quality.human_evaluation.record": "evaluation",
    "quality.adjudication.record": "adjudication",
}
REFERENCE_ANNOTATION_VERSION = "2.2.0"
WORLD_REFERENCE_ANNOTATION_VERSION = "2.3.0"
PLANNING_REFERENCE_ANNOTATION_VERSION = "2.4.0"


def require_reference_subject(
    cursor: Any, *, project_id: str, binding: Mapping[str, Any],
    allowed_types: frozenset[str] = frozenset({"chapter_provider_sample"}),
) -> dict[str, Any]:
    if (not isinstance(binding, Mapping) or set(binding) != {"asset_version_id", "content_hash"}
        or any(not isinstance(value, str) or not value for value in binding.values())):
        raise KernelError("QUALITY_REFERENCE_TARGET_INVALID", "reference annotation requires one exact sample version")
    if {"planning_generation_candidate", "longform_prose_review_sample", "screenplay_provider_sample"}.intersection(allowed_types):
        cursor.execute("SELECT asset_type FROM authority_asset JOIN authority_asset_version USING(asset_id) WHERE project_id=%s AND asset_version_id=%s",
            [project_id, binding["asset_version_id"]])
        kind = cursor.fetchone()
        if kind and kind[0] == "planning_generation_candidate" and kind[0] in allowed_types:
            return require_planning_reference_subject(cursor, project_id=project_id, binding=binding)
        if kind and kind[0] == "screenplay_provider_sample" and kind[0] in allowed_types:
            from novel_forge.modules.book_followup_authority.screenplay_sample_feedback import require_screenplay_reference_subject
            return require_screenplay_reference_subject(cursor, project_id=project_id, binding=binding)
        if kind and kind[0] == "longform_prose_review_sample" and kind[0] in allowed_types:
            from novel_forge.modules.book_followup_authority.prose_sample_feedback import require_prose_reference_subject

            return require_prose_reference_subject(cursor, project_id=project_id, binding=binding)
    cursor.execute("""SELECT asset.asset_type,version.content,version.content_hash,operation.operation_id,operation.actor_id
        FROM authority_asset_version version JOIN authority_asset asset USING(asset_id)
        JOIN authority_operation_output_asset output ON output.asset_version_id=version.asset_version_id
          AND output.content_hash=version.content_hash AND output.role='primary'
        JOIN authority_operation operation ON operation.operation_id=output.operation_id
          AND operation.project_id=asset.project_id AND operation.status='SUCCEEDED'
        WHERE asset.project_id=%s AND version.asset_version_id=%s AND version.lifecycle='ACTIVE'
          AND version.eligibility='INELIGIBLE' AND version.governance='CLEAR'""",
        [project_id, binding["asset_version_id"]])
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise KernelError("QUALITY_REFERENCE_TARGET_INVALID", "reference subject must be a completed native sample")
    kind, content, digest, operation_id, actor_id = rows[0]
    stages = {"chapter_provider_sample": set(CHAPTER_GENERATOR_TASKS.values()),
              "world_provider_sample": {"world_candidates.generate", *("world_candidates.actor_" + str(index) for index in range(3))}}
    if (kind not in allowed_types or content.get("stage") not in stages.get(kind, set())
        or digest != binding["content_hash"] or digest != authorization_hash(content)
        or content.get("routing_eligibility") != "BENCHMARK_ONLY" or content.get("production_eligible") is not False):
        raise KernelError("QUALITY_REFERENCE_TARGET_INVALID", "annotation cannot reinterpret an arbitrary ineligible asset")
    snapshot = load_bootstrap_authorization(cursor, project_id=project_id, operation_id=operation_id, check_expiry=False)
    grant = snapshot["authorization"] if snapshot else {}
    if (grant.get("purpose") != "BENCHMARK_CHALLENGER" or content.get("authorization_id") != grant.get("authorization_id")
        or content.get("campaign") != grant.get("campaign") or content["stage"] != grant.get("task_type")):
        raise KernelError("QUALITY_REFERENCE_TARGET_INVALID", "sample annotation requires its immutable generation authorization")
    return {**dict(binding), "asset_type": kind, "content": content,
            "generation_operation_id": operation_id, "generation_actor_id": actor_id}


def require_planning_reference_subject(cursor: Any, *, project_id: str, binding: Mapping[str, Any]) -> dict[str, Any]:
    cursor.execute("""SELECT version.content,version.content_hash,operation.operation_id,operation.actor_id
        FROM authority_asset_version version JOIN authority_asset asset USING(asset_id)
        JOIN authority_operation_output_asset output ON output.asset_version_id=version.asset_version_id
          AND output.content_hash=version.content_hash AND output.role='primary'
        JOIN authority_operation operation ON operation.operation_id=output.operation_id AND operation.project_id=asset.project_id
        JOIN authority_story_planning_generation generation ON generation.operation_id=operation.operation_id
          AND generation.project_id=asset.project_id AND generation.candidate_asset_version_id=version.asset_version_id
        WHERE asset.project_id=%s AND version.asset_version_id=%s AND asset.asset_type='planning_generation_candidate'
          AND version.lifecycle='CANDIDATE' AND version.eligibility='INELIGIBLE' AND version.governance='CLEAR'
          AND operation.definition_name='story_planning.generate' AND operation.definition_version=ANY(%s)
          AND operation.status IN ('WAITING_GATE','SUCCEEDED')""", [project_id, binding["asset_version_id"], sorted(PLANNING_BOOTSTRAP_SOURCE_VERSIONS)])
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise KernelError("QUALITY_REFERENCE_TARGET_INVALID", "Planning annotation requires its native frozen benchmark candidate")
    content, digest, operation_id, actor_id = rows[0]
    snapshot = load_bootstrap_authorization(cursor, project_id=project_id, operation_id=operation_id, check_expiry=False)
    grant = snapshot["authorization"] if snapshot else {}
    if (digest != binding["content_hash"] or digest != authorization_hash(content)
        or content.get("routing_eligibility") != "BENCHMARK_ONLY" or content.get("project_id") != project_id
        or grant.get("purpose") != "BENCHMARK_CHALLENGER" or not grant.get("campaign")
        or content.get("routing_bootstrap_authorization") != snapshot
        or content.get("generator_operation_name") != grant.get("task_type")):
        raise KernelError("QUALITY_REFERENCE_TARGET_INVALID", "Planning annotation must retain the exact generation grant, task and content")
    return {**dict(binding), "asset_type": "planning_generation_candidate", "content": content,
            "generation_operation_id": operation_id, "generation_actor_id": actor_id}


def require_reference_annotation(
    cursor: Any, *, project_id: str, definition_name: str, payload: Mapping[str, Any], actor_id: str,
    allowed_types: frozenset[str] = frozenset({"chapter_provider_sample"}),
) -> str:
    key = REFERENCE_ANNOTATION_DEFINITIONS.get(definition_name)
    annotation = payload.get(key) if key else None
    if not isinstance(annotation, Mapping):
        raise KernelError("QUALITY_REFERENCE_ANNOTATION_INVALID", "only native reference human evaluation and adjudication may read a sample")
    binding = payload.get("reference_sample")
    subject = require_reference_subject(cursor, project_id=project_id, binding=binding, allowed_types=allowed_types)
    author_field = "evaluator_id" if key == "evaluation" else "adjudicator_id"
    if annotation.get("subject_asset_version_id") != subject["asset_version_id"] or annotation.get(author_field) != actor_id:
        raise KernelError("QUALITY_REFERENCE_ANNOTATION_INVALID", "reference annotation must retain the exact target and authenticated author")
    if subject["asset_type"] == "screenplay_provider_sample":
        from novel_forge.modules.book_followup_authority.screenplay_sample_feedback import validate_screenplay_annotation
        validate_screenplay_annotation(subject=subject, annotation=annotation, human=key == "evaluation")
    if subject["asset_type"] == "longform_prose_review_sample":
        from novel_forge.modules.book_followup_authority.prose_sample_feedback import validate_prose_annotation

        validate_prose_annotation(subject=subject, annotation=annotation, human=key == "evaluation")
    return subject["asset_version_id"]


def require_chapter_sample_target(cursor: Any, *, project_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    expected = {"review": ("draft", "draft_chapter"), "rereview": ("revision", "draft_version")}
    stage = payload.get("generator_operation_name")
    metadata = payload.get("chapter_sampling") or {}
    if stage not in expected:
        raise KernelError("QUALITY_REFERENCE_TARGET_INVALID", "reference task has no compatible native generator sample")
    subject = require_reference_subject(cursor, project_id=project_id, binding=metadata.get("generation_sample"))
    content = subject["content"]
    if (content.get("source_operation_id") != metadata.get("source_operation_id")
        or (content.get("stage"), content.get("sampled_asset_type")) != expected[stage]
        or metadata["generation_sample"] not in payload.get("input_versions", [])):
        raise KernelError("QUALITY_REFERENCE_TARGET_INVALID", "reference sample must retain its generator task and typed target")
    return subject
