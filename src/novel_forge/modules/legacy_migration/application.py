"""One Legacy record import using the shared fenced Authority runtime."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from novel_forge.modules.authority_handler_runtime import (
    AuthorityHandlerOutput,
    AuthorityHandlerRegistration,
    AuthorityHandlerRequest,
)
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.modules.content_authority.scheduler import ContentAuthorityScheduler
from novel_forge.modules.legacy_migration.definitions import (
    LEGACY_IMPORT_DEFINITION_NAME,
    LEGACY_IMPORT_DEFINITION_VERSION,
    LEGACY_IMPORT_HANDLER_KEY,
    legacy_import_definition,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


@dataclass(frozen=True, slots=True)
class LegacyImportCommand:
    project_id: str
    workspace_id: str
    actor_id: str
    trace_id: str
    correlation_id: str
    idempotency_key: str
    source_ref: str
    source_hash: str
    source_asset_type: str
    stable_business_key: str
    payload: dict[str, Any]


class _LegacyImportCodec:
    def execute(self, request: AuthorityHandlerRequest) -> AuthorityHandlerOutput:
        payload = request.command
        if payload.get("project_id") != request.project_id:
            raise ValueError("legacy import project scope changed after admission")
        source_hash = str(payload.get("source_hash") or "")
        if not source_hash.startswith("sha256:"):
            raise ValueError("legacy import source hash is invalid")
        content = {
            "schema_version": "legacy-import-candidate.v1",
            "migration_status": "NEEDS_REVIEW",
            "project_id": request.project_id,
            "workspace_id": request.workspace_id,
            "source_ref": str(payload["source_ref"]),
            "source_hash": source_hash,
            "source_asset_type": str(payload["source_asset_type"]),
            "stable_business_key": str(payload["stable_business_key"]),
            "payload": dict(payload["payload"]),
            "production_context_eligible": False,
            "active": False,
        }
        return AuthorityHandlerOutput(
            asset_type="legacy_import_candidate",
            output_key="legacy.import.candidate",
            role="primary",
            content=content,
            qualification_policy="legacy-import-needs-review-v1",
            lifecycle="IMPORTED",
            eligibility="PENDING_EVALUATION",
            governance="CLEAR",
            evidence={
                "source_ref": content["source_ref"],
                "source_hash": source_hash,
                "auto_activation_forbidden": True,
            },
        )


class _LegacyImportRegistry:
    definition_names = frozenset({LEGACY_IMPORT_DEFINITION_NAME})
    available_handler_keys = frozenset({LEGACY_IMPORT_HANDLER_KEY})

    def registration(
        self, definition_name: str, definition_version: str
    ) -> AuthorityHandlerRegistration:
        if (
            definition_name != LEGACY_IMPORT_DEFINITION_NAME
            or definition_version != LEGACY_IMPORT_DEFINITION_VERSION
        ):
            raise ValueError("unsupported Legacy import definition")
        return AuthorityHandlerRegistration(
            definition_name=definition_name,
            definition_version=definition_version,
            handler_key=LEGACY_IMPORT_HANDLER_KEY,
            handler_contract_version="legacy-import-handler-v1",
            output_asset_type="legacy_import_candidate",
            output_key="legacy.import.candidate",
            role="primary",
            completion_topic="legacy_migration.asset.imported",
            handler=_LegacyImportCodec(),
        )


class LegacyImportApplication:
    def __init__(
        self, database_url: str, *, application_build_id: str, commit_sha: str
    ) -> None:
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.registry = _LegacyImportRegistry()

    def execute(self, command: LegacyImportCommand) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.definitions.register(
                legacy_import_definition(
                    application_build_id=self.application_build_id,
                    commit_sha=self.commit_sha,
                )
            )
            uow.commit()
        context = AdmissionContext(
            actor_id=command.actor_id,
            permissions=frozenset({"legacy_migration.import"}),
            available_handlers=self.registry.available_handler_keys,
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": LEGACY_IMPORT_DEFINITION_NAME,
                "definition_version": LEGACY_IMPORT_DEFINITION_VERSION,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "actor_id": command.actor_id,
                "idempotency_scope": "project:legacy-migration",
                "idempotency_key": command.idempotency_key,
                "trace_id": command.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": command.correlation_id,
                "causation_id": "",
                "input": {
                    "project_id": command.project_id,
                    "workspace_id": command.workspace_id,
                    "source_ref": command.source_ref,
                    "source_hash": command.source_hash,
                    "source_asset_type": command.source_asset_type,
                    "stable_business_key": command.stable_business_key,
                    "payload": command.payload,
                },
                "input_assets": [],
            },
            context=context,
        )
        operation_id = str(admitted["operation_id"])
        with AuthorityUnitOfWork(self.database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(
                operation_id, command.project_id
            )
        if state["status"] == "ADMITTED":
            transition_operation(
                self.database_url,
                OperationTransitionCommand(
                    operation_id=operation_id,
                    project_id=command.project_id,
                    expected_version=int(state["version"]),
                    expected_status="ADMITTED",
                    target_status="READY",
                    actor_id=command.actor_id,
                    reason="Legacy import candidate ready",
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    causation_id="",
                ),
            )
        scheduled = ContentAuthorityScheduler(
            self.database_url,
            registry=self.registry,  # type: ignore[arg-type]
            worker_id="legacy-migration-worker",
        ).run_or_recover(operation_id=operation_id, project_id=command.project_id)
        return {
            "operation_id": operation_id,
            "asset_id": scheduled.output.asset_id,
            "asset_version_id": scheduled.output.asset_version_id,
            "content_hash": scheduled.output.content_hash,
            "replayed": bool(admitted["replayed"] or scheduled.output.replayed),
        }


__all__ = ["LegacyImportApplication", "LegacyImportCommand"]
