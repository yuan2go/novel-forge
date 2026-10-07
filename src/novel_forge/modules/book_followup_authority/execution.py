from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from novel_forge.modules.capability_pack_authority.runtime import (
    CapabilityPackResolutionRequest,
)
from novel_forge.modules.book_followup_authority.contracts import (
    READER_OUTCOME_DEFINITION_VERSION,
)
from novel_forge.modules.chapter_authority.execution_gateway import (
    PostgresChapterExecutionContractBinder,
)
from novel_forge.modules.chapter_authority.provider_views import (
    project_reader_outcome_context_input,
)
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution import ArtifactPointer
from novel_forge.storage.authority_asset_store import (
    AuthorityAssetQuery,
    AuthorityAssetWriter,
)


class PostgresReaderOutcomeExecutionContractBinder(
    PostgresChapterExecutionContractBinder
):

    workflow_definition_ref = (
        f"book_followup_reader_outcome@{READER_OUTCOME_DEFINITION_VERSION}"
    )
    execution_binding_domain = "reader_outcome"
    stage_name = "reader_outcome"
    context_schema = "novelos.reader_outcome_context_bundle.v2"

    def _project_context_input(self, asset_type: str, content: Mapping[str, Any]) -> dict[str, Any]:
        return project_reader_outcome_context_input(asset_type, content)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("workflow_definition_ref", self.workflow_definition_ref)
        super().__init__(*args, **kwargs)
        self.reader_query = AuthorityAssetQuery(self.database_url)
        self.reader_writer = AuthorityAssetWriter(self.database_url)

    def freeze_before_external_effect(
        self,
        *,
        capability: str,
        request_payload: Mapping[str, Any],
        snapshot_fencing_token: int,
        snapshot_worker_id: str,
    ):
        if capability != f"model.{self.stage_name}" or str(
            request_payload.get("stage") or ""
        ) != self.stage_name:
            raise KernelError(
                "READER_OUTCOME_CAPABILITY_INVALID",
                "Reader binder accepts only Reader Outcome execution",
            )
        metadata = request_payload.get("_production_execution")
        if not isinstance(metadata, dict):
            raise KernelError(
                "READER_OUTCOME_EXECUTION_METADATA_INVALID",
                "Reader Outcome execution metadata is missing",
            )
        artifacts = metadata.get("input_artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise KernelError(
                "READER_OUTCOME_INPUT_INVALID",
                "Reader Outcome requires frozen input artifacts",
            )
        if not any(
            isinstance(item, Mapping) and item.get("artifact_type") == "context_bundle"
            for item in artifacts
        ):
            context = self._reader_context_bundle(
                operation_id=str(metadata.get("operation_id") or ""),
                attempt_id=str(metadata.get("attempt_id") or ""),
                project_id=str(metadata.get("project_id") or ""),
                trace_id=str(request_payload.get("trace_id") or ""),
                correlation_id=str(request_payload.get("correlation_id") or ""),
                artifacts=artifacts,
            )
            artifacts.append(
                ArtifactPointer(
                    artifact_ref=f"asset-version:{context.asset_version_id}",
                    asset_version_id=context.asset_version_id,
                    artifact_type="context_bundle",
                    content_hash=context.content_hash,
                    schema_version=str(
                        context.content.get("schema_version")
                        or self.context_schema
                    ),
                    source_eligibility="PRODUCTION_ELIGIBLE",
                ).to_dict()
            )
        metadata["execution_binding_domain"] = self.execution_binding_domain
        return super().freeze_before_external_effect(
            capability=capability,
            request_payload=request_payload,
            snapshot_fencing_token=snapshot_fencing_token,
            snapshot_worker_id=snapshot_worker_id,
        )

    def _resolve_pack_snapshot(
        self,
        *,
        project_id: str,
        workspace_id: str,
        book_id: str,
        operation_id: str,
        attempt_id: str,
        execution_fencing_token: int,
        worker_id: str,
        snapshot_creation_fencing_token: int,
        snapshot_creation_worker_id: str,
        stage: str,
        graph: Mapping[str, str],
        route: Any,
    ):
        if stage != self.stage_name:
            raise KernelError(
                "READER_OUTCOME_STAGE_INVALID",
                "Reader Pack cannot bind another model stage",
            )
        if not self.capability_pack_id:
            return None
        try:
            return self.pack_resolver.freeze_attempt_snapshot(
                CapabilityPackResolutionRequest(
                    project_id=project_id,
                    workspace_id=workspace_id,
                    book_id=book_id,
                    workflow_definition_ref=self.workflow_definition_ref,
                    workflow_node_id=self.stage_name,
                    environment=self.pack_environment,
                    runtime_profile=self.pack_runtime_profile,
                    release_channel=self.pack_release_channel,
                    release_sha=route.release_sha,
                    operation_definition_ref=(
                        f"{graph['definition_name']}@{graph['definition_version']}"
                    ),
                    pack_id=self.capability_pack_id,
                ),
                operation_id=operation_id,
                attempt_id=attempt_id,
                execution_fencing_token=execution_fencing_token,
                worker_id=worker_id,
                snapshot_creation_fencing_token=snapshot_creation_fencing_token,
                snapshot_creation_worker_id=snapshot_creation_worker_id,
            )
        except KernelError as exc:
            if exc.code in {
                "CAPABILITY_PACK_DEPLOYMENT_NOT_RESOLVED",
                "CAPABILITY_PACK_SCOPE_NOT_FOUND",
            } and not self.pack_required:
                return None
            raise

    def _context_input_permitted(self, document: Any, *, project_id: str, operation_id: str) -> bool:
        return document.eligibility in {"ELIGIBLE", "PRODUCTION_ELIGIBLE"}

    def _reader_context_bundle(
        self,
        *,
        operation_id: str,
        attempt_id: str,
        project_id: str,
        trace_id: str,
        correlation_id: str,
        artifacts: list[Any],
    ):
        if not all((operation_id, attempt_id, project_id, trace_id, correlation_id)):
            raise KernelError(
                "READER_OUTCOME_EXECUTION_METADATA_INVALID",
                "Reader context identity is incomplete",
            )
        selected: list[dict[str, Any]] = []
        asset_ids: list[str] = []
        for raw in artifacts:
            if not isinstance(raw, Mapping):
                raise KernelError(
                    "READER_OUTCOME_INPUT_INVALID",
                    "Reader input pointer must be an object",
                )
            document = self.reader_query.require(
                project_id=project_id,
                asset_version_id=str(raw.get("asset_version_id") or ""),
            )
            if (
                document.asset_type != str(raw.get("artifact_type") or "")
                or document.content_hash != str(raw.get("content_hash") or "")
                or document.governance != "CLEAR"
                or not self._context_input_permitted(document, project_id=project_id, operation_id=operation_id)
            ):
                raise KernelError(
                    "READER_OUTCOME_INPUT_DRIFT",
                    "Reader input differs from its frozen Authority version",
                )
            selected.append(
                {
                    "asset_version_id": document.asset_version_id,
                    "asset_type": document.asset_type,
                    "content_hash": document.content_hash,
                    "projection": self._project_context_input(
                        document.asset_type, document.content
                    ),
                }
            )
            asset_ids.append(document.asset_id)
        logical_ref = f"{self.stage_name}/context_bundles/{operation_id}-{attempt_id}.json"
        content = {
            "schema_version": self.context_schema,
            "project_id": project_id,
            "operation_id": operation_id,
            "attempt_id": attempt_id,
            "source_isolation": "EXACT_ACCEPTED_SOURCE_AND_AUTHORIZED_INELIGIBLE_SAMPLE" if any(item["asset_type"] == "screenplay_provider_sample" for item in selected) else "ACCEPTED_AUTHORITY_ASSETS_ONLY",
            "selected_inputs": selected,
        }
        try:
            existing = self.reader_query.require(
                project_id=project_id, logical_ref=logical_ref
            )
            existing_inputs = existing.content.get("selected_inputs")
            existing_refs = [
                (
                    str(item.get("asset_version_id") or ""),
                    str(item.get("asset_type") or ""),
                    str(item.get("content_hash") or ""),
                )
                for item in existing_inputs or ()
                if isinstance(item, Mapping)
            ]
            new_refs = [
                (
                    str(item.get("asset_version_id") or ""),
                    str(item.get("asset_type") or ""),
                    str(item.get("content_hash") or ""),
                )
                for item in selected
            ]
            if existing_refs != new_refs:
                raise KernelError(
                    "READER_OUTCOME_CONTEXT_CONFLICT",
                    "Reader context changed inside one Attempt",
                )
            return existing
        except KernelError as exc:
            if exc.code != "AUTHORITY_ASSET_NOT_FOUND":
                raise
        return self.reader_writer.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=operation_id,
                project_id=project_id,
                asset_id=f"{self.stage_name}-context:{attempt_id}",
                asset_type="context_bundle",
                schema_version=self.context_schema,
                logical_ref=logical_ref,
                category="reader_outcome_context",
                output_key=f"{self.stage_name}.context_bundle",
                role="context_bundle",
                content=content,
                qualification_policy="reader-outcome-context-source-isolation-v1",
                trace_id=trace_id,
                correlation_id=correlation_id,
                reference_asset_ids=tuple(asset_ids),
            )
        )


__all__ = ["PostgresReaderOutcomeExecutionContractBinder"]
