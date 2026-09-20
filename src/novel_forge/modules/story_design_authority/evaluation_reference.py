from __future__ import annotations

from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.routing_bootstrap import (
    authorization_hash, validate_reference_evaluation_binding,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .qualification import validate_narrative_qualification


def reference_command_fields(command: Any) -> dict[str, Any]:
    if not command.routing_bootstrap_authorization_id:
        if command.reference_evaluation is not None:
            raise ValueError("reference evaluation requires its explicit authorization")
        return {}
    if command.evaluator_execution_class != "MODEL_PROVIDER":
        raise ValueError("reference sampling requires the governed Provider evaluator")
    validate_reference_evaluation_binding(command.reference_evaluation)
    reference = dict(command.reference_evaluation)
    return {
        "project_id": command.project_id,
        "logical_key": command.candidate_asset_version_id,
        "idempotency_key": command.idempotency_key,
        "input_versions": {
            "candidate": command.candidate_asset_version_id,
            "candidate_content_hash": command.candidate_content_hash,
            "reference": reference["asset_version_id"],
            "reference_content_hash": reference["content_hash"],
        },
        "routing_bootstrap_authorization_id": command.routing_bootstrap_authorization_id,
        "reference_evaluation": reference,
    }


def require_reference_review(
    database_url: str, *, project_id: str, payload: Mapping[str, Any],
    evaluator_actor_id: str,
) -> Mapping[str, Any]:
    reference = payload["reference_evaluation"]
    validate_reference_evaluation_binding(reference)
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """SELECT version.content,version.content_hash,operation.actor_id,
                      operation.operation_id
               FROM authority_asset_version version
               JOIN authority_asset asset USING(asset_id)
               JOIN authority_operation_output_asset output
                 ON output.asset_version_id=version.asset_version_id
                 AND output.content_hash=version.content_hash
               JOIN authority_operation operation ON operation.operation_id=output.operation_id
                 AND operation.project_id=asset.project_id
               WHERE asset.project_id=%s AND version.asset_version_id=%s
                 AND asset.asset_type='narrative_design_operator_review'
                 AND version.governance='CLEAR' AND version.lifecycle='ACTIVE'
                 AND operation.definition_name='story_design.review.author'
                 AND operation.status='SUCCEEDED'
                 AND NOT EXISTS (SELECT 1 FROM authority_external_effect effect
                     WHERE effect.operation_id=operation.operation_id)
               ORDER BY output.created_at""",
            [project_id, reference["asset_version_id"]],
        )
        rows = uow.cursor.fetchall()
    if len(rows) != 1:
        raise KernelError("NARRATIVE_REFERENCE_PROVENANCE_INVALID",
                          "reference labels require one successful native operator-review author Operation")
    content, digest, author, operation_id = rows[0]
    if (
        digest != reference["content_hash"] or digest != authorization_hash(content)
        or author in {evaluator_actor_id, payload["generation_actor_id"]}
        or operation_id == payload["generation_operation_id"]
        or content.get("contract_version") != "narrative-design-operator-review.v1"
        or content.get("project_id") != project_id
        or content.get("candidate_asset_version_id") != payload["candidate_asset_version_id"]
        or content.get("candidate_content_hash") != payload["candidate_content_hash"]
        or content.get("evaluator_execution_class") != "OPERATOR_REVIEW"
        or any(content.get(key) is not False for key in (
            "provider_evidence_claimed", "human_preference_evidence", "ground_truth_claimed",
        ))
    ):
        raise KernelError("NARRATIVE_REFERENCE_NOT_INDEPENDENT",
                          "reference identity, independent author or non-human evidence boundary differs")
    validate_narrative_qualification(
        generator_operation_name=payload["generator_operation_name"],
        value=content.get("evaluation"), require_pass=False,
    )
    return {"content": content, "author_actor_id": author, "operation_id": operation_id}


def reference_agreement(
    *, payload: Mapping[str, Any], reference: Mapping[str, Any],
    evaluation: Mapping[str, Any],
) -> dict[str, Any]:
    def verdicts(value: Mapping[str, Any]) -> dict[tuple[str, str], str]:
        validate_narrative_qualification(
            generator_operation_name=payload["generator_operation_name"],
            value=value, require_pass=False,
        )
        return {(layer["layer"], criterion["criterion"]): criterion["verdict"]
                for layer in value["evaluations"] for criterion in layer["criteria"]}

    expected = verdicts(reference["content"]["evaluation"])
    observed = verdicts(evaluation)
    comparisons = [
        {"layer": layer, "criterion": criterion, "expected": expected[(layer, criterion)],
         "observed": observed[(layer, criterion)],
         "agrees": expected[(layer, criterion)] == observed[(layer, criterion)]}
        for layer, criterion in sorted(expected)
    ]
    return {
        "schema_version": "narrative-reference-agreement.v1",
        "reference": dict(payload["reference_evaluation"]),
        "reference_operation_id": reference["operation_id"],
        "reference_author_actor_id": reference["author_actor_id"],
        "generator_operation_name": payload["generator_operation_name"],
        "criterion_agreement": comparisons,
        "agreement_rate": sum(item["agrees"] for item in comparisons) / len(comparisons),
        "reference_basis": "INDEPENDENT_OPERATOR_PROXY_LABELS",
        "ground_truth_claimed": False,
        "human_preference_evidence": False,
        "production_qualification_eligible": False,
    }
