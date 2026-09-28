"""SECURITY: Human annotations bind native samples and authenticated authors, never model labels."""

from __future__ import annotations

from typing import Any

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.chapter_quality_authority.generator_reference import generator_reference_contract
from novel_forge.modules.chapter_quality_authority.reference_subject import require_reference_subject
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_design_authority.qualification import required_qualification_profiles
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def planning_reference_samples(database_url: str, *, project_id: str, book_id: str,
                               principal: Principal, limit: int = 100) -> dict[str, Any]:
    principal.require("content.authority.query", project_id)
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SET TRANSACTION READ ONLY")
        uow.cursor.execute(
            """SELECT version.asset_version_id,version.content_hash,
                      operation.command_payload #>> '{payload,workspace_id}',
                      effect.request_payload #>> '{_production_execution,capability_runtime,routing_decision,task,producer_contract_hash}'
               FROM authority_story_planning_generation generation
               JOIN authority_operation operation USING(operation_id)
               JOIN authority_asset_version version ON version.asset_version_id=generation.candidate_asset_version_id
               JOIN authority_external_effect effect USING(operation_id)
               WHERE generation.project_id=%s AND generation.book_id=%s
                 AND effect.status='SUCCEEDED'
                 AND effect.request_payload->>'stage'=version.content->>'generator_operation_name'
                 AND version.content->>'routing_eligibility'='BENCHMARK_ONLY'
               ORDER BY version.created_at DESC,version.asset_version_id LIMIT %s""",
            [project_id, book_id, limit],
        )
        rows = uow.cursor.fetchall()
        samples = []
        for asset_id, digest, workspace_id, producer_hash in rows:
            subject = require_reference_subject(
                uow.cursor, project_id=project_id,
                binding={"asset_version_id": asset_id, "content_hash": digest},
                allowed_types=frozenset({"planning_generation_candidate"}),
            )
            content = subject["content"]
            task = content["generator_operation_name"]
            contract = generator_reference_contract(task, producer_hash)
            dimensions = [profile.layer.value + ":" + criterion
                          for profile in required_qualification_profiles(task)
                          for criterion in profile.criteria]
            samples.append({
                "asset_version_id": asset_id, "content_hash": digest,
                "workspace_id": workspace_id, "book_id": book_id,
                "content": content["candidate_payload"],
                "reference_contract": {**contract, "dimensions": dimensions},
            })
    return {
        "samples": samples, "actor_id": principal.principal_id,
        "can_annotate": principal.principal_type is PrincipalType.LOCAL_OPERATOR
        and principal.allows("content.authority.execute", project_id)
        and principal.allows("content.operation:quality.human_evaluation.record", project_id),
        "blind_presentation": "GENERATOR_AND_OTHER_REVIEWER_IDENTITIES_NOT_INCLUDED",
        "sample_promotion_allowed": False,
    }


def reference_evaluation_request(database_url: str, *, principal: Principal,
                                 values: dict[str, Any]):
    from .application import ContentOperationRequest

    project_id = values["project_id"]
    if principal.principal_type is not PrincipalType.LOCAL_OPERATOR:
        raise PermissionError("reference judgments require an authenticated human operator")
    principal.require("content.authority.execute", project_id)
    principal.require("content.operation:quality.human_evaluation.record", project_id)
    selected = planning_reference_samples(database_url, project_id=project_id,
                                         book_id=values["book_id"], principal=principal)
    sample = next((item for item in selected["samples"]
                   if item["asset_version_id"] == values["asset_version_id"]), None)
    if not sample or sample["content_hash"] != values["content_hash"]:
        raise KernelError("QUALITY_REFERENCE_TARGET_INVALID", "selected exact sample is no longer available")
    contract = sample["reference_contract"]
    if values["dimension"] not in contract["dimensions"]:
        raise KernelError("QUALITY_REFERENCE_ANNOTATION_INVALID", "dimension differs from the frozen Producer")
    quote = values["quote"].strip()

    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)

    if not quote or not any(quote in text for text in strings(sample["content"])):
        raise KernelError("QUALITY_REFERENCE_QUOTE_MISMATCH", "evidence quote must occur in the exact sample")
    identity = "author-reference:" + values["idempotency_key"]
    binding = {key: sample[key] for key in ("asset_version_id", "content_hash")}
    return ContentOperationRequest(
        definition_name="quality.human_evaluation.record", project_id=project_id,
        workspace_id=sample["workspace_id"], actor_id=principal.principal_id,
        trace_id="trace:" + identity, correlation_id=identity, idempotency_key=identity,
        input_assets=(binding,), payload={
            "reference_sample": binding,
            "evaluation": {
                "evaluation_id": identity, "subject_asset_version_id": sample["asset_version_id"],
                "dimension": values["dimension"], "status": values["status"],
                "score": values["score"], "confidence": values["confidence"],
                "evaluator_id": principal.principal_id,
                "evaluator_group": "human-author-review:" + principal.principal_id,
                "evaluator_identity_class": values["evaluator_identity_class"],
                "protocol_version": contract["protocol_version"],
                "evaluation_version": contract["evaluation_version"],
                "scope_type": values["scope_type"], "chapter_start": values["chapter_start"],
                "chapter_end": values["chapter_end"], "blind": values["blind"],
                "evidence": [{**binding, "quote": quote, "rationale": values["rationale"].strip(),
                              "preserve_strengths": values["preserve_strengths"].strip(),
                              "contribution_source": "AUTHENTICATED_HUMAN_FORM"}],
            },
        },
    )
