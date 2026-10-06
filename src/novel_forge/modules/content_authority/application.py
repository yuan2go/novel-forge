from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Collection
from uuid import uuid4

from novel_forge.modules.authority_handler_runtime import AuthorityExecutionResult
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.command_kernel.runtime import OperationTransitionCommand, transition_operation
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.modules.content_authority.definitions import (
    content_operation_definitions,
)
from novel_forge.modules.content_authority.registry import ContentHandlerRegistry
from novel_forge.modules.content_authority.scheduler import ContentAuthorityScheduler
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


@dataclass(frozen=True, slots=True)
class ContentOperationRequest:
    definition_name: str
    project_id: str
    workspace_id: str
    actor_id: str
    trace_id: str
    correlation_id: str
    idempotency_key: str
    payload: dict[str, Any]
    input_assets: tuple[dict[str, str], ...] = ()
    approval: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ContentOperationAdmission:
    operation_id: str
    project_id: str
    replayed: bool


class ContentAuthorityApplication:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        integration_proven: Collection[str],
        registry: ContentHandlerRegistry | None = None,
        trusted_only: bool = False,
    ) -> None:
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.integration_proven = frozenset(integration_proven)
        self.registry = registry or ContentHandlerRegistry()
        self.trusted_only = trusted_only

    def execute(
        self,
        request: ContentOperationRequest,
        *,
        principal: Principal | None = None,
    ) -> AuthorityExecutionResult:
        admission = self.admit(request, principal=principal)
        return ContentAuthorityScheduler(
            self.database_url,
            registry=self.registry,
        ).run_or_recover(
            operation_id=admission.operation_id,
            project_id=admission.project_id,
        ).output

    def admit(
        self,
        request: ContentOperationRequest,
        *,
        principal: Principal | None = None,
    ) -> ContentOperationAdmission:
        from novel_forge.modules.chapter_quality_authority.model_reference import (
            MODEL_REFERENCE_ADJUDICATION, MODEL_REFERENCE_EVALUATION, require_model_reference_annotation,
        )

        model_reference_annotation = request.definition_name in {MODEL_REFERENCE_EVALUATION, MODEL_REFERENCE_ADJUDICATION}
        if model_reference_annotation:
            if principal is None:
                raise PermissionError("model reference record requires an authenticated principal")
            principal.require("content.authority.execute", request.project_id)
            principal.require("content.operation:" + request.definition_name, request.project_id)
            with AuthorityUnitOfWork(self.database_url) as uow:
                require_model_reference_annotation(uow.cursor, project_id=request.project_id,
                    definition_name=request.definition_name, payload=request.payload,
                    actor_id=principal.principal_id, input_assets=list(request.input_assets))
        reference_annotation = "reference_sample" in request.payload
        if reference_annotation and (principal is None or principal.principal_type is not PrincipalType.LOCAL_OPERATOR):
            raise PermissionError("sample annotations require an authenticated local operator")
        world_reference_annotation = False
        planning_reference_annotation = False
        prose_reference_annotation = False
        screenplay_reference_annotation = False
        if reference_annotation:
            from novel_forge.modules.chapter_quality_authority.reference_subject import require_reference_subject
            principal.require("content.authority.execute", request.project_id)
            principal.require("content.operation:" + request.definition_name, request.project_id)
            with AuthorityUnitOfWork(self.database_url) as uow:
                subject = require_reference_subject(uow.cursor, project_id=request.project_id, binding=request.payload["reference_sample"],
                    allowed_types=frozenset({"chapter_provider_sample", "world_provider_sample", "planning_generation_candidate", "longform_prose_review_sample", "screenplay_provider_sample"}))
            world_reference_annotation = subject["asset_type"] == "world_provider_sample"
            planning_reference_annotation = subject["asset_type"] == "planning_generation_candidate"
            prose_reference_annotation = subject["asset_type"] == "longform_prose_review_sample"
            screenplay_reference_annotation = subject["asset_type"] == "screenplay_provider_sample"
        definitions = content_operation_definitions(
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
            integration_proven=self.integration_proven,
            reference_annotations=reference_annotation,
            world_reference_annotations=world_reference_annotation,
            planning_reference_annotations=planning_reference_annotation,
            prose_reference_annotations=prose_reference_annotation,
            screenplay_reference_annotations=screenplay_reference_annotation,
            model_reference_annotations=model_reference_annotation,
        )
        definition = next((item for item in definitions if item["name"] == request.definition_name), None)
        if definition is None:
            raise ValueError("Unknown Content operation")
        if self.trusted_only and principal is None:
            raise PermissionError("trusted Principal is required for Content admission")
        actor_id = request.actor_id
        definition_permission = f"content.operation:{request.definition_name}"
        permissions = frozenset({definition_permission})
        if principal is not None:
            principal.require("content.authority.execute", request.project_id)
            principal.require(definition_permission, request.project_id)
            actor_id = principal.principal_id
        with AuthorityUnitOfWork(self.database_url) as uow:
            # WHY: unrelated task-contract drift must not block this admission.
            uow.repositories.definitions.register(definition)
            uow.commit()
        definition_version = definition["definition_version"]
        if reference_annotation:
            from novel_forge.modules.book_followup_authority.prose_sample_feedback import PROSE_ANNOTATION_VERSION
            from novel_forge.modules.book_followup_authority.screenplay_sample_feedback import SCREENPLAY_ANNOTATION_VERSION
            from novel_forge.modules.chapter_quality_authority.reference_subject import (
                REFERENCE_ANNOTATION_VERSION, WORLD_REFERENCE_ANNOTATION_VERSION, PLANNING_REFERENCE_ANNOTATION_VERSION, require_reference_annotation,
            )
            with AuthorityUnitOfWork(self.database_url) as uow:
                subject_id = require_reference_annotation(uow.cursor, project_id=request.project_id,
                    definition_name=request.definition_name, payload=request.payload, actor_id=actor_id,
                    allowed_types=frozenset({"screenplay_provider_sample"} if screenplay_reference_annotation else {"longform_prose_review_sample"} if prose_reference_annotation else {"planning_generation_candidate"} if planning_reference_annotation else
                        {"world_provider_sample"} if world_reference_annotation else {"chapter_provider_sample"}))
            if not any(item["asset_version_id"] == subject_id and item["content_hash"] == request.payload["reference_sample"]["content_hash"]
                       for item in request.input_assets):
                raise ValueError("reference annotation must freeze its exact sample input")
            definition_version = SCREENPLAY_ANNOTATION_VERSION if screenplay_reference_annotation else PROSE_ANNOTATION_VERSION if prose_reference_annotation else PLANNING_REFERENCE_ANNOTATION_VERSION if planning_reference_annotation else (
                WORLD_REFERENCE_ANNOTATION_VERSION if world_reference_annotation else REFERENCE_ANNOTATION_VERSION)
        admission = AdmissionContext(
            actor_id=actor_id,
            permissions=permissions,
            available_handlers=self.registry.available_handler_keys,
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": request.definition_name,
                "definition_version": definition_version,
                "project_id": request.project_id,
                "workspace_id": request.workspace_id,
                "actor_id": actor_id,
                "idempotency_scope": "project:content-domain",
                "idempotency_key": request.idempotency_key,
                "trace_id": request.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": request.correlation_id,
                "causation_id": "",
                "input": {
                    "project_id": request.project_id,
                    "input_asset_version_ids": [
                        item["asset_version_id"] for item in request.input_assets
                    ],
                    "payload": request.payload,
                },
                "input_assets": list(request.input_assets),
                "approval": request.approval,
            },
            context=admission,
        )
        operation_id = str(admitted["operation_id"])
        with AuthorityUnitOfWork(self.database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(
                operation_id, request.project_id
            )
        if state["status"] == "ADMITTED":
            transition_operation(
                self.database_url,
                OperationTransitionCommand(
                    operation_id=operation_id,
                    project_id=request.project_id,
                    expected_version=state["version"],
                    expected_status="ADMITTED",
                    target_status="READY",
                    actor_id=actor_id,
                    reason="content operation ready",
                    trace_id=request.trace_id,
                    correlation_id=request.correlation_id,
                    causation_id="",
                ),
            )
        return ContentOperationAdmission(
            operation_id=operation_id,
            project_id=request.project_id,
            replayed=bool(admitted["replayed"]),
        )


__all__ = [
    "ContentAuthorityApplication",
    "ContentOperationAdmission",
    "ContentOperationRequest",
]
