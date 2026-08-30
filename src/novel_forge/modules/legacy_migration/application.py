"""INVARIANT: One Legacy record import using the shared fenced Authority runtime."""
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
    legacy_native_definition,
    legacy_native_definition_name,
    legacy_native_handler_key,
    legacy_native_output_key,
)
from novel_forge.modules.legacy_migration.codecs import (
    DEFAULT_CODEC_REGISTRY,
    TypedMigrationCodec,
    TypedMigrationCodecRegistry,
)
from novel_forge.modules.legacy_migration.scanner import LegacySnapshotRecord
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
    references: tuple[dict[str, Any] | str, ...] = ()


class _LegacyImportCodec:
    def __init__(self, codec: TypedMigrationCodec) -> None:
        self.codec = codec

    def execute(self, request: AuthorityHandlerRequest) -> AuthorityHandlerOutput:
        payload = request.command
        if payload.get("project_id") != request.project_id:
            raise ValueError("legacy import project scope changed after admission")
        source_hash = str(payload.get("source_hash") or "")
        if not source_hash.startswith("sha256:"):
            raise ValueError("legacy import source hash is invalid")
        candidate = self.codec.convert_record(
            LegacySnapshotRecord(
                source_ref=str(payload["source_ref"]),
                category="authority-import",
                source_hash=source_hash,
                size_bytes=0,
                stable_business_key=str(payload["stable_business_key"]),
                project_id=request.project_id,
                workspace_id=request.workspace_id,
                source_asset_type=str(payload["source_asset_type"]),
                payload=dict(payload["payload"]),
                references=tuple(payload.get("references") or ()),
                decision="IMPORT",
                status="VALIDATED",
            )
        )
        return AuthorityHandlerOutput(
            asset_type=candidate.target_asset_type,
            output_key=legacy_native_output_key(self.codec),
            role="primary",
            content=candidate.content,
            qualification_policy=candidate.qualification_policy,
            lifecycle=candidate.lifecycle,
            eligibility=candidate.eligibility,
            governance=candidate.governance,
            evidence={
                "source_ref": str(payload["source_ref"]),
                "source_hash": source_hash,
                "codec_name": self.codec.codec_name,
                "codec_version": self.codec.codec_version,
                "target_content_hash": candidate.content_hash,
                "activation_decision": candidate.activation_decision,
                "materialization_level": candidate.materialization_level.value,
                "target_materialization_level": (
                    self.codec.materialization_level.value
                ),
                "legacy_approval_evidence": candidate.legacy_approval_evidence,
                "reconciliation": candidate.reconciliation,
            },
        )


class _LegacyImportRegistry:
    def __init__(self, codec: TypedMigrationCodec) -> None:
        self.codec = codec
        self.definition_names = frozenset({legacy_native_definition_name(codec)})
        self.available_handler_keys = frozenset({legacy_native_handler_key(codec)})

    def registration(
        self, definition_name: str, definition_version: str
    ) -> AuthorityHandlerRegistration:
        if definition_name != legacy_native_definition_name(self.codec) or definition_version != self.codec.codec_version:
            raise ValueError("unsupported Legacy import definition")
        return AuthorityHandlerRegistration(
            definition_name=definition_name,
            definition_version=definition_version,
            handler_key=legacy_native_handler_key(self.codec),
            handler_contract_version=self.codec.codec_version,
            output_asset_type=self.codec.target_asset_type,
            output_key=legacy_native_output_key(self.codec),
            role="primary",
            completion_topic="legacy_migration.asset.converted",
            handler=_LegacyImportCodec(self.codec),
        )


class LegacyImportApplication:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        codec_registry: TypedMigrationCodecRegistry = DEFAULT_CODEC_REGISTRY,
    ) -> None:
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.codec_registry = codec_registry

    def execute(self, command: LegacyImportCommand) -> dict[str, Any]:
        codec = self.codec_registry.resolve(command.source_asset_type)
        registry = _LegacyImportRegistry(codec)
        definition_name = legacy_native_definition_name(codec)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.definitions.register(
                legacy_native_definition(
                    codec,
                    application_build_id=self.application_build_id,
                    commit_sha=self.commit_sha,
                )
            )
            uow.commit()
        context = AdmissionContext(
            actor_id=command.actor_id,
            permissions=frozenset({"legacy_migration.import"}),
            available_handlers=registry.available_handler_keys,
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": definition_name,
                "definition_version": codec.codec_version,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "actor_id": command.actor_id,
                "idempotency_scope": "project:legacy-native-migration",
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
                    "references": list(command.references),
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
                    reason="Legacy native conversion ready",
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    causation_id="",
                ),
            )
        scheduled = ContentAuthorityScheduler(
            self.database_url,
            registry=registry,  # type: ignore[arg-type]
            worker_id="legacy-migration-worker",
        ).run_or_recover(operation_id=operation_id, project_id=command.project_id)
        candidate = codec.convert_record(
            LegacySnapshotRecord(
                source_ref=command.source_ref,
                category="authority-import",
                source_hash=command.source_hash,
                size_bytes=0,
                stable_business_key=command.stable_business_key,
                project_id=command.project_id,
                workspace_id=command.workspace_id,
                source_asset_type=command.source_asset_type,
                payload=command.payload,
                references=command.references,
                decision="IMPORT",
                status="VALIDATED",
            )
        )
        return {
            "operation_id": operation_id,
            "asset_id": scheduled.output.asset_id,
            "asset_version_id": scheduled.output.asset_version_id,
            "content_hash": scheduled.output.content_hash,
            "replayed": bool(admitted["replayed"] or scheduled.output.replayed),
            "source_asset_type": codec.source_type,
            "target_asset_type": codec.target_asset_type,
            "codec_name": codec.codec_name,
            "codec_version": codec.codec_version,
            "lifecycle": candidate.lifecycle,
            "eligibility": candidate.eligibility,
            "activation_decision": candidate.activation_decision,
            "materialization_level": candidate.materialization_level.value,
            "target_materialization_level": codec.materialization_level.value,
            "domain_adapter": codec.domain_adapter,
            "domain_validator": codec.domain_validator,
            "projection_strategy": codec.projection_strategy,
            "activation_strategy": codec.activation_strategy,
            "reconciliation": candidate.reconciliation,
        }


__all__ = ["LegacyImportApplication", "LegacyImportCommand"]
