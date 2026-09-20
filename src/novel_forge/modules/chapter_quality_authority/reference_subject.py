from __future__ import annotations

from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.routing_bootstrap import (
    CHAPTER_GENERATOR_TASKS, authorization_hash, load_bootstrap_authorization,
)


REFERENCE_ANNOTATION_DEFINITIONS = {
    "quality.human_evaluation.record": "evaluation",
    "quality.adjudication.record": "adjudication",
}
REFERENCE_ANNOTATION_VERSION = "2.2.0"


def require_reference_subject(
    cursor: Any, *, project_id: str, binding: Mapping[str, Any],
) -> dict[str, Any]:
    if (not isinstance(binding, Mapping) or set(binding) != {"asset_version_id", "content_hash"}
        or any(not isinstance(value, str) or not value for value in binding.values())):
        raise KernelError("QUALITY_REFERENCE_TARGET_INVALID", "reference annotation requires one exact sample version")
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
    if (kind != "chapter_provider_sample" or content.get("stage") not in CHAPTER_GENERATOR_TASKS.values()
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


def require_reference_annotation(
    cursor: Any, *, project_id: str, definition_name: str, payload: Mapping[str, Any], actor_id: str,
) -> str:
    key = REFERENCE_ANNOTATION_DEFINITIONS.get(definition_name)
    annotation = payload.get(key) if key else None
    if not isinstance(annotation, Mapping):
        raise KernelError("QUALITY_REFERENCE_ANNOTATION_INVALID", "only native reference human evaluation and adjudication may read a sample")
    binding = payload.get("reference_sample")
    subject = require_reference_subject(cursor, project_id=project_id, binding=binding)
    author_field = "evaluator_id" if key == "evaluation" else "adjudicator_id"
    if annotation.get("subject_asset_version_id") != subject["asset_version_id"] or annotation.get(author_field) != actor_id:
        raise KernelError("QUALITY_REFERENCE_ANNOTATION_INVALID", "reference annotation must retain the exact target and authenticated author")
    return subject["asset_version_id"]
