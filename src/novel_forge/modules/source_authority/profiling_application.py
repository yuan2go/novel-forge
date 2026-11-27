from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any
from uuid import uuid4

from novel_forge.modules.authority_handler_runtime.runtime import require_current_fence
from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.attempt_runtime import WorkerLeaseCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.modules.source_authority.definitions import (
    SOURCE_ANALYSIS_PLAN_DEFINITION_VERSION,
    SOURCE_ANALYSIS_PLAN_HANDLER_KEY,
    SOURCE_ANALYSIS_PLAN_OPERATION,
    SOURCE_CONTENT_PROFILE_DEFINITION_VERSION,
    SOURCE_CONTENT_PROFILE_HANDLER_KEY,
    SOURCE_CONTENT_PROFILE_OPERATION,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.mkaos_authority_repositories import MkaosAuthorityRepository
from novel_forge.storage.source_authority_repositories import SourceAuthorityRepository
from novel_forge.storage.source_profile_repositories import SourceProfileRepository


_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_CONTENT_TYPES = {
    "WEB_NOVEL",
    "PUBLISHED_FICTION",
    "CLASSIC_LITERATURE",
    "WRITING_THEORY",
    "PROFESSIONAL_KNOWLEDGE",
    "HISTORY_SOCIAL_SCIENCE",
    "BIOGRAPHY_MEMOIR",
    "PHILOSOPHY_ESSAY",
    "PLATFORM_RULES",
    "UNKNOWN",
    "MIXED",
}


def _hash(value: Any) -> str:
    data = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, slots=True)
class CommitSourceContentProfileCommand:
    project_id: str
    workspace_id: str
    logical_document_scope: dict[str, Any]
    intelligence_policy: dict[str, Any]
    classifier_contract: dict[str, Any]
    classification_evidence: dict[str, Any]
    classifier_output: dict[str, Any]
    resolution: dict[str, Any]
    execution_asset_version_id: str
    evidence_class: str
    governance_override: dict[str, Any]
    actor_id: str
    idempotency_key: str
    trace_id: str
    correlation_id: str

    def __post_init__(self) -> None:
        _require_strings(
            self.project_id,
            self.workspace_id,
            self.execution_asset_version_id,
            self.evidence_class,
            self.actor_id,
            self.idempotency_key,
            self.trace_id,
            self.correlation_id,
        )
        if self.evidence_class not in {
            "FIXTURE",
            "PROVIDER_UNCALIBRATED",
            "PROVIDER_QUALIFIED",
        }:
            raise ValueError("Source Profile evidence_class is invalid")
        if not isinstance(self.governance_override, dict):
            raise ValueError("Source Profile governance override must be an object")


@dataclass(frozen=True, slots=True)
class CommitSourceAnalysisPlanCommand:
    project_id: str
    workspace_id: str
    profile_asset_version_id: str
    strategy: dict[str, Any]
    actor_id: str
    idempotency_key: str
    trace_id: str
    correlation_id: str

    def __post_init__(self) -> None:
        _require_strings(
            self.project_id,
            self.workspace_id,
            self.profile_asset_version_id,
            self.actor_id,
            self.idempotency_key,
            self.trace_id,
            self.correlation_id,
        )


class SourceProfilingApplication:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        allow_fixture_profiles: bool = False,
    ) -> None:
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.allow_fixture_profiles = allow_fixture_profiles

    def admit_profile(
        self,
        command: CommitSourceContentProfileCommand,
        *,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        actor_id = self._actor(command.actor_id, principal, command.project_id)
        validated = self._preflight_profile(command)
        existing = validated["existing"]
        if existing is not None:
            self._require_succeeded(existing, "SOURCE_PROFILE_RECOVERY_REQUIRED")
            return {
                **existing,
                "project_id": command.project_id,
                "status": "SUCCEEDED",
                "replayed": True,
                "duplicate": True,
            }
        payload = {
            "project_id": command.project_id,
            "workspace_id": command.workspace_id,
            "payload": {
                "logical_document_scope": command.logical_document_scope,
                "logical_document_scope_hash": validated["scope_hash"],
                "intelligence_policy": command.intelligence_policy,
                "intelligence_policy_hash": validated["policy_hash"],
                "classifier_contract": command.classifier_contract,
                "classifier_contract_hash": validated["classifier_contract_hash"],
                "classification_evidence": command.classification_evidence,
                "classification_input_hash": validated["classification_input_hash"],
                "classifier_output": command.classifier_output,
                "classification_output_hash": validated["classification_output_hash"],
                "resolution": command.resolution,
                "governance_override": command.governance_override,
                "execution_asset_version_id": command.execution_asset_version_id,
                "execution_binding": validated["execution_binding"],
                "evidence_class": command.evidence_class,
                "override_contract_hash": validated["override_contract_hash"],
                "client_idempotency_key": command.idempotency_key,
                "raw_source_text_in_postgresql": False,
                "generation_context_allowed": False,
            },
        }
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": SOURCE_CONTENT_PROFILE_OPERATION,
                "definition_version": SOURCE_CONTENT_PROFILE_DEFINITION_VERSION,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "actor_id": actor_id,
                "idempotency_scope": "project:source_content_profile",
                "idempotency_key": (
                    f"source.profile:{command.project_id}:{validated['scope_hash']}:"
                    f"{validated['classifier_contract_hash']}:"
                    f"{validated['policy_hash']}:"
                    f"{validated['override_contract_hash']}:"
                    f"{validated['classification_input_hash']}:"
                    f"{validated['classification_output_hash']}"
                ),
                "trace_id": command.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": command.correlation_id,
                "causation_id": command.execution_asset_version_id,
                "input": payload,
                "input_assets": validated["input_assets"],
            },
            context=self._context(actor_id, SOURCE_CONTENT_PROFILE_HANDLER_KEY),
        )
        return self._ready(
            admitted,
            command.project_id,
            actor_id=actor_id,
            reason="governed Source content profile ready",
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            causation_id=command.execution_asset_version_id,
        )

    def admit_plan(
        self,
        command: CommitSourceAnalysisPlanCommand,
        *,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        actor_id = self._actor(command.actor_id, principal, command.project_id)
        validated = self._preflight_plan(command)
        existing = validated["existing"]
        if existing is not None:
            self._require_succeeded(existing, "SOURCE_ANALYSIS_PLAN_RECOVERY_REQUIRED")
            return {
                **existing,
                "project_id": command.project_id,
                "status": "SUCCEEDED",
                "replayed": True,
                "duplicate": True,
            }
        payload = {
            "project_id": command.project_id,
            "workspace_id": command.workspace_id,
            "payload": {
                "profile_asset_version_id": command.profile_asset_version_id,
                "strategy": command.strategy,
                "strategy_contract_hash": validated["strategy_contract_hash"],
                "methodologies": validated["methodologies"],
                "methodology_contract_hash": validated["methodology_contract_hash"],
                "client_idempotency_key": command.idempotency_key,
                "raw_source_text_in_postgresql": False,
                "generation_context_allowed": False,
            },
        }
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": SOURCE_ANALYSIS_PLAN_OPERATION,
                "definition_version": SOURCE_ANALYSIS_PLAN_DEFINITION_VERSION,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "actor_id": actor_id,
                "idempotency_scope": "project:source_analysis_plan",
                "idempotency_key": (
                    f"source.analysis.plan:{command.project_id}:"
                    f"{command.profile_asset_version_id}:"
                    f"{validated['strategy_contract_hash']}:"
                    f"{validated['methodology_contract_hash']}"
                ),
                "trace_id": command.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": command.correlation_id,
                "causation_id": command.profile_asset_version_id,
                "input": payload,
                "input_assets": [
                    {
                        "asset_version_id": command.profile_asset_version_id,
                        "role": "source_content_profile",
                        "content_hash": validated["profile"]["content_hash"],
                    }
                ],
            },
            context=self._context(actor_id, SOURCE_ANALYSIS_PLAN_HANDLER_KEY),
        )
        return self._ready(
            admitted,
            command.project_id,
            actor_id=actor_id,
            reason="Source analysis strategy plan ready",
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            causation_id=command.profile_asset_version_id,
        )

    def execute_fenced(
        self, worker: WorkerLeaseCommand, definition_name: str
    ) -> dict[str, Any]:
        if definition_name == SOURCE_CONTENT_PROFILE_OPERATION:
            return self._execute_profile_fenced(worker)
        if definition_name == SOURCE_ANALYSIS_PLAN_OPERATION:
            return self._execute_plan_fenced(worker)
        raise KernelError(
            "SOURCE_PROFILE_HANDLER_NOT_FOUND",
            f"unsupported Source Profile Operation: {definition_name}",
        )

    def result(
        self,
        operation_id: str,
        project_id: str,
        *,
        definition_name: str,
        replayed: bool,
    ) -> dict[str, Any]:
        output_key = (
            "source.content.profile"
            if definition_name == SOURCE_CONTENT_PROFILE_OPERATION
            else "source.analysis.plan"
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = SourceProfileRepository(uow.cursor)
            output = repository.operation_output(
                project_id=project_id,
                operation_id=operation_id,
                output_key=output_key,
            )
            if output is None:
                raise KernelError(
                    "SOURCE_PROFILE_RESULT_MISSING",
                    "Source Profile Authority output is missing",
                )
            state = uow.repositories.attempt_runtime.operation_state(
                operation_id, project_id
            )
            asset = repository.asset_version(
                project_id=project_id,
                asset_version_id=str(output["asset_version_id"]),
            )
            assert asset is not None
        content = dict(asset["content"])
        return {
            "operation_id": operation_id,
            "project_id": project_id,
            "asset_version_id": output["asset_version_id"],
            "content_hash": output["content_hash"],
            **(
                {
                    "source_content_profile_id": content["source_content_profile_id"],
                    "profile_status": content["resolution"]["status"],
                    "resolved_content_type": content["resolution"][
                        "resolved_content_type"
                    ],
                }
                if output_key == "source.content.profile"
                else {
                    "source_analysis_plan_id": content["source_analysis_plan_id"],
                    "strategy_contract_hash": content["strategy_contract_hash"],
                }
            ),
            "status": state["status"],
            "replayed": replayed,
            "duplicate": False,
        }

    @staticmethod
    def _validate_reading_binding(
        uow: Any, command: Any, scope: dict, chunk_ids: tuple
    ) -> None:
        from .curation import require_curated_operation_current

        reference = scope.get("reading_binding") or {}
        repository = SourceAuthorityRepository(uow.cursor)
        operation = reference.get("member_operation_id", "")
        require_curated_operation_current(repository, command.project_id, operation)
        binding = repository.catalog_execution_binding(command.project_id, operation)
        plan = (
            (binding or {})
            .get("reading_plans", {})
            .get((binding or {}).get("member_processing_id"))
        )
        if (
            not plan
            or plan["identity"] != reference.get("reading_identity")
            or plan["source_transform_id"] != scope["source_transform_id"]
        ):
            raise KernelError(
                "SOURCE_PROFILE_READING_BINDING_INVALID",
                "chapter window must match frozen curated scope",
            )
        chunks = {
            c["asset_version_id"]: c for unit in plan["units"] for c in unit["chunks"]
        }
        expected = tuple(
            c["asset_version_id"]
            for c in sorted(chunks.values(), key=lambda c: c["chunk_index"])
        )
        if expected != chunk_ids:
            raise KernelError(
                "SOURCE_PROFILE_READING_CHUNKS_INVALID",
                "scope cannot expand or truncate frozen reading chunks",
            )

    def _preflight_profile(
        self, command: CommitSourceContentProfileCommand
    ) -> dict[str, Any]:
        scope = dict(command.logical_document_scope)
        if scope.get("scope_kind") not in {"FILE_DOCUMENT", "CHAPTER_WINDOW"}:
            raise ValueError(
                "Source Profile requires an explicit document or frozen chapter window"
            )
        required_scope = {
            "source_document_id",
            "source_transform_id",
            "source_chunk_asset_version_ids",
            "boundary_policy_version",
            "label",
        }
        if not required_scope.issubset(scope):
            raise ValueError("Source Profile LogicalDocument scope is incomplete")
        chunk_ids = tuple(str(item) for item in scope["source_chunk_asset_version_ids"])
        if not chunk_ids or len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("Source Profile chunk manifest is invalid")
        scope_hash = _hash(scope)
        policy_hash = _hash(command.intelligence_policy)
        classifier_contract_hash = _hash(command.classifier_contract)
        classification_input_hash = _hash(command.classification_evidence)
        classification_output_hash = _hash(command.classifier_output)
        if (
            command.classification_evidence.get("logical_document_scope_hash")
            != scope_hash
        ):
            raise ValueError("classification Evidence belongs to another scope")
        if _contains_source_text(command.classification_evidence):
            raise ValueError("classification Evidence cannot persist Source text")
        resolution = dict(command.resolution)
        predicted = str(resolution.get("predicted_content_type") or "")
        resolved = str(resolution.get("resolved_content_type") or "")
        status = str(resolution.get("status") or "")
        manual = bool(resolution.get("manual_review_required"))
        resolution_mode = str(resolution.get("resolution_mode") or "")
        override = dict(command.governance_override)
        override_hash = _hash(override) if override else ""
        if predicted not in _CONTENT_TYPES or resolved not in _CONTENT_TYPES:
            raise ValueError("Source Profile resolution content type is invalid")
        if status not in {"ROUTABLE", "NEEDS_REVIEW", "FAILED"}:
            raise ValueError("Source Profile resolution status is invalid")
        if (status == "ROUTABLE") != (not manual):
            raise ValueError("Source Profile manual review admission is inconsistent")
        if status == "ROUTABLE" and resolved in {"UNKNOWN", "MIXED"}:
            raise ValueError("UNKNOWN/MIXED Source Profile cannot be routed")
        if str(command.classifier_output.get("content_type")) != predicted:
            raise ValueError("Source Profile prediction differs from classifier output")
        if override:
            base_override_keys = {
                "logical_document_scope_hash",
                "content_type",
                "reason",
                "decision_ref",
            }
            aggregate_override_keys = base_override_keys | {
                "boundary_resolution",
                "expected_document_count",
            }
            override_keys = set(override)
            boundary = dict(command.classifier_output.get("boundary_assessment") or {})
            aggregate_boundary_is_valid = bool(
                override_keys == aggregate_override_keys
                and override.get("boundary_resolution")
                == "CONFIRM_SOURCE_WORK_AGGREGATE"
                and isinstance(override.get("expected_document_count"), int)
                and not isinstance(override.get("expected_document_count"), bool)
                and int(override["expected_document_count"]) >= 2
            )
            override_keys_are_valid = override_keys in (
                base_override_keys,
                aggregate_override_keys,
            )
            if (
                not override_keys_are_valid
                or override.get("logical_document_scope_hash") != scope_hash
                or (status == "ROUTABLE" and override.get("content_type") != resolved)
                or len(str(override.get("reason") or "").strip()) < 20
                or not str(override.get("decision_ref") or "").strip()
                or override.get("decision_ref")
                != resolution.get("override_decision_ref")
                or resolution_mode != "GOVERNANCE_OVERRIDE"
                or (
                    override_keys == aggregate_override_keys
                    and not aggregate_boundary_is_valid
                )
                or (
                    status == "ROUTABLE"
                    and override_keys == aggregate_override_keys
                    and (
                        int(boundary.get("suspected_document_count") or 0)
                        != int(override["expected_document_count"])
                    )
                )
            ):
                raise ValueError(
                    "Source Profile governance override differs from resolution scope"
                )
        elif resolution_mode != "AUTOMATIC" or resolution.get("override_decision_ref"):
            raise ValueError("automatic Source Profile cannot claim an override")
        with AuthorityUnitOfWork(self.database_url) as uow:
            SourceAuthorityRepository(uow.cursor).require_scope(
                project_id=command.project_id, workspace_id=command.workspace_id
            )
            repository = SourceProfileRepository(uow.cursor)
            if scope["scope_kind"] == "CHAPTER_WINDOW":
                self._validate_reading_binding(uow, command, scope, chunk_ids)
            transform = repository.transform_scope(
                project_id=command.project_id,
                workspace_id=command.workspace_id,
                source_transform_id=str(scope["source_transform_id"]),
            )
            chunks = repository.chunks(
                project_id=command.project_id,
                source_transform_id=str(scope["source_transform_id"]),
                chunk_ids=chunk_ids
                if scope["scope_kind"] == "CHAPTER_WINDOW"
                else None,
            )
            execution = MkaosAuthorityRepository(uow.cursor).execution_evidence(
                project_id=command.project_id,
                asset_version_id=command.execution_asset_version_id,
            )
            existing = repository.exact_profile(
                project_id=command.project_id,
                logical_document_scope_hash=scope_hash,
                classifier_contract_hash=classifier_contract_hash,
                intelligence_policy_hash=policy_hash,
                override_contract_hash=override_hash,
                classification_input_hash=classification_input_hash,
                classification_output_hash=classification_output_hash,
            )
        if transform is None or (
            transform["source_document_id"] != scope["source_document_id"]
            or transform["status"] != "ACTIVE"
            or transform["lifecycle"] != "ACTIVE"
        ):
            raise KernelError(
                "SOURCE_PROFILE_TRANSFORM_INVALID",
                "Source Profile requires an active governed SourceTransform",
            )
        ordered_ids = tuple(str(item["asset_version_id"]) for item in chunks)
        if ordered_ids != chunk_ids or any(
            item["lifecycle"] != "ACTIVE" for item in chunks
        ):
            raise KernelError(
                "SOURCE_PROFILE_CHUNK_MANIFEST_DRIFT",
                "LogicalDocument chunks differ from the active SourceTransform",
            )
        execution_binding = _classification_execution_binding(
            execution,
            evidence_class=command.evidence_class,
            scope_hash=scope_hash,
            classifier_contract_hash=classifier_contract_hash,
            classification_input_hash=classification_input_hash,
            classification_output_hash=classification_output_hash,
            allow_fixture=self.allow_fixture_profiles,
        )
        samples = {
            str(item["source_chunk_asset_version_id"]): item
            for item in command.classification_evidence.get("samples") or []
        }
        input_assets = [
            {
                "asset_version_id": command.execution_asset_version_id,
                "role": "classifier_execution",
                "content_hash": execution["content_hash"],
            },
            *[
                {
                    "asset_version_id": item["asset_version_id"],
                    "role": "source_chunk",
                    "content_hash": item["asset_content_hash"],
                }
                for item in chunks
            ],
        ]
        return {
            "scope_hash": scope_hash,
            "policy_hash": policy_hash,
            "classifier_contract_hash": classifier_contract_hash,
            "classification_input_hash": classification_input_hash,
            "classification_output_hash": classification_output_hash,
            "override_contract_hash": override_hash,
            "transform": transform,
            "chunks": chunks,
            "samples": samples,
            "execution": execution,
            "execution_binding": execution_binding,
            "existing": existing,
            "input_assets": input_assets,
        }

    def _preflight_plan(
        self, command: CommitSourceAnalysisPlanCommand
    ) -> dict[str, Any]:
        strategy = dict(command.strategy)
        required = {
            "profile_id",
            "profile_version",
            "content_type",
            "routing_policy_version",
            "analyzers",
            "window_chunks",
            "max_analyzer_calls",
            "mkaos_capability",
            "abstraction_policy_version",
        }
        if (
            not required.issubset(strategy)
            or not isinstance(strategy.get("analyzers"), list)
            or not strategy["analyzers"]
        ):
            raise ValueError("Source analysis strategy is incomplete")
        methodology_by_key: dict[tuple[str, str, str], dict[str, str]] = {}
        for analyzer in strategy["analyzers"]:
            if not isinstance(analyzer, dict):
                raise ValueError("Source analysis analyzer contract is invalid")
            digest = str(analyzer.get("methodology_content_hash") or "")
            if not _SHA256.fullmatch(digest):
                raise ValueError("Source analysis methodology digest is required")
            key = (
                str(analyzer.get("skill_id") or ""),
                str(analyzer.get("skill_version") or ""),
                digest,
            )
            if not all(key):
                raise ValueError("Source analysis Skill binding is incomplete")
            methodology_by_key[key] = {
                "skill_id": key[0],
                "skill_version": key[1],
                "methodology_content_hash": key[2],
            }
        methodologies = [methodology_by_key[key] for key in sorted(methodology_by_key)]
        strategy_contract_hash = _hash(strategy)
        methodology_contract_hash = _hash(methodologies)
        with AuthorityUnitOfWork(self.database_url) as uow:
            SourceAuthorityRepository(uow.cursor).require_scope(
                project_id=command.project_id, workspace_id=command.workspace_id
            )
            repository = SourceProfileRepository(uow.cursor)
            profile = repository.profile(
                project_id=command.project_id,
                asset_version_id=command.profile_asset_version_id,
            )
            existing = repository.exact_plan(
                project_id=command.project_id,
                profile_asset_version_id=command.profile_asset_version_id,
                strategy_contract_hash=strategy_contract_hash,
                methodology_contract_hash=methodology_contract_hash,
            )
        if profile is None or (
            profile["status"] != "ROUTABLE"
            or profile["operation_status"] != "SUCCEEDED"
        ):
            raise KernelError(
                "SOURCE_ANALYSIS_PROFILE_NOT_ROUTABLE",
                "AnalysisPlan requires a succeeded ROUTABLE Source Profile",
            )
        if profile["resolved_content_type"] != strategy["content_type"]:
            raise KernelError(
                "SOURCE_ANALYSIS_STRATEGY_TYPE_CONFLICT",
                "Analysis strategy differs from the resolved Source type",
            )
        if profile["content"]["logical_document_scope"]["source_document_id"] == "":
            raise KernelError(
                "SOURCE_ANALYSIS_PROFILE_SCOPE_INVALID",
                "Analysis Profile scope is incomplete",
            )
        return {
            "profile": profile,
            "strategy_contract_hash": strategy_contract_hash,
            "methodologies": methodologies,
            "methodology_contract_hash": methodology_contract_hash,
            "existing": existing,
        }

    def _execute_profile_fenced(self, worker: WorkerLeaseCommand) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            require_current_fence(uow, worker)
            repository = SourceProfileRepository(uow.cursor)
            replay = repository.operation_output(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                output_key="source.content.profile",
            )
            if replay is not None:
                return replay
            operation = uow.repositories.chapter_authority.operation_execution(
                worker.causation_id, worker.project_id
            )
            command = dict(operation["command_payload"])
            payload = dict(command["payload"])
            from novel_forge.modules.source_authority.curation import (
                require_curated_evidence_current,
            )
            from novel_forge.storage.source_authority_repositories import (
                SourceAuthorityRepository,
            )

            require_curated_evidence_current(
                SourceAuthorityRepository(uow.cursor),
                worker.project_id,
                str(payload["execution_asset_version_id"]),
            )
            scope = dict(payload["logical_document_scope"])
            current = repository.current_profile(
                project_id=worker.project_id,
                logical_document_scope_hash=str(payload["logical_document_scope_hash"]),
            )
            digest = str(payload["logical_document_scope_hash"]).removeprefix("sha256:")
            profile_id = f"source-content-profile:{worker.project_id}:{digest}"
            content = {
                "schema_version": "source-content-profile.v1",
                "source_content_profile_id": profile_id,
                "project_id": worker.project_id,
                "workspace_id": str(command["workspace_id"]),
                "logical_document_scope": scope,
                "logical_document_scope_hash": payload["logical_document_scope_hash"],
                "intelligence_policy": payload["intelligence_policy"],
                "intelligence_policy_hash": payload["intelligence_policy_hash"],
                "classifier": {
                    **payload["classifier_contract"],
                    "contract_hash": payload["classifier_contract_hash"],
                },
                "classification_evidence": payload["classification_evidence"],
                "classification_input_hash": payload["classification_input_hash"],
                "classifier_output": payload["classifier_output"],
                "classification_output_hash": payload["classification_output_hash"],
                "resolution": payload["resolution"],
                "execution_evidence": {
                    "asset_version_id": payload["execution_asset_version_id"],
                    "binding": payload["execution_binding"],
                    "evidence_class": payload["evidence_class"],
                },
                "governance_override": {
                    **dict(payload["governance_override"]),
                    "contract_hash": payload["override_contract_hash"],
                },
                "source_policy": {
                    "raw_source_text_in_postgresql": False,
                    "generation_context_allowed": False,
                    "reusable_knowledge": False,
                },
                "lineage": {
                    "created_by_operation_id": worker.causation_id,
                    "source_transform_id": scope["source_transform_id"],
                    "source_chunk_asset_version_ids": scope[
                        "source_chunk_asset_version_ids"
                    ],
                    "supersedes_asset_version_id": (
                        current["asset_version_id"] if current else None
                    ),
                },
            }
            created = uow.repositories.asset_documents.materialize_output(
                AuthorityAssetWriteCommand(
                    operation_id=worker.causation_id,
                    project_id=worker.project_id,
                    asset_id=profile_id,
                    asset_type="source_content_profile",
                    schema_version="source-content-profile.v1",
                    logical_ref=f"source-intelligence/profiles/{digest}.json",
                    category="source-intelligence",
                    output_key="source.content.profile",
                    role="evidence",
                    content=content,
                    qualification_policy="source-profile-isolation-v1",
                    trace_id=worker.trace_id,
                    correlation_id=worker.correlation_id,
                    causation_id=str(payload["execution_asset_version_id"]),
                    expected_current_asset_version_id=(
                        str(current["asset_version_id"]) if current else None
                    ),
                    eligibility="INELIGIBLE",
                    governance="CLEAR",
                )
            )
            resolution = dict(payload["resolution"])
            classifier = dict(payload["classifier_contract"])
            repository.register_profile(
                {
                    "source_content_profile_id": profile_id,
                    "project_id": worker.project_id,
                    "workspace_id": str(command["workspace_id"]),
                    "asset_version_id": created.asset_version_id,
                    "source_document_id": scope["source_document_id"],
                    "source_transform_id": scope["source_transform_id"],
                    "logical_document_scope": scope,
                    "logical_document_scope_hash": payload[
                        "logical_document_scope_hash"
                    ],
                    "boundary_policy_version": scope["boundary_policy_version"],
                    "classifier_id": classifier["classifier_id"],
                    "classifier_version": classifier["classifier_version"],
                    "classifier_prompt_version": classifier["prompt_version"],
                    "classifier_schema_version": classifier["schema_version"],
                    "classifier_contract_hash": payload["classifier_contract_hash"],
                    "classification_input_hash": payload["classification_input_hash"],
                    "classification_output_hash": payload["classification_output_hash"],
                    "intelligence_policy_hash": payload["intelligence_policy_hash"],
                    "override_contract_hash": payload["override_contract_hash"],
                    "execution_asset_version_id": payload["execution_asset_version_id"],
                    "evidence": payload["classification_evidence"],
                    "predicted_content_type": resolution["predicted_content_type"],
                    "resolved_content_type": resolution["resolved_content_type"],
                    "confidence": resolution["confidence"],
                    "margin": resolution["margin"],
                    "resolution_mode": resolution["resolution_mode"],
                    "resolution_reasons": resolution["reasons"],
                    "override_decision_ref": resolution.get(
                        "override_decision_ref", ""
                    ),
                    "status": resolution["status"],
                    "manual_review_required": resolution["manual_review_required"],
                    "evidence_class": payload["evidence_class"],
                    "created_by_operation_id": worker.causation_id,
                }
            )
            samples = {
                str(item["source_chunk_asset_version_id"]): item
                for item in payload["classification_evidence"].get("samples") or []
            }
            for ordinal, chunk_id in enumerate(scope["source_chunk_asset_version_ids"]):
                repository.register_profile_input(
                    {
                        "profile_asset_version_id": created.asset_version_id,
                        "project_id": worker.project_id,
                        "input_asset_version_id": chunk_id,
                        "role": "SOURCE_CHUNK",
                        "ordinal": ordinal,
                        "sample_manifest": samples.get(chunk_id, {}),
                        "created_by_operation_id": worker.causation_id,
                    }
                )
                self._dependency(
                    repository,
                    worker,
                    upstream=chunk_id,
                    downstream=created.asset_version_id,
                    relationship="PROFILES",
                    selector_key=str(payload["classifier_contract_hash"]),
                )
            repository.register_profile_input(
                {
                    "profile_asset_version_id": created.asset_version_id,
                    "project_id": worker.project_id,
                    "input_asset_version_id": payload["execution_asset_version_id"],
                    "role": "CLASSIFIER_EXECUTION",
                    "ordinal": 0,
                    "sample_manifest": {},
                    "created_by_operation_id": worker.causation_id,
                }
            )
            self._dependency(
                repository,
                worker,
                upstream=str(payload["execution_asset_version_id"]),
                downstream=created.asset_version_id,
                relationship="EVIDENCES",
                selector_key="source-content-classification",
            )
            if current is not None:
                cause_type = _profile_change_cause(current, payload)
                descendants = repository.descendants(
                    project_id=worker.project_id,
                    upstream_asset_version_id=str(current["asset_version_id"]),
                )
                repository.record_invalidations(
                    project_id=worker.project_id,
                    target_asset_version_ids=(
                        item["asset_version_id"]
                        for item in descendants
                        if item["lifecycle"]
                        not in {"SUPERSEDED", "REJECTED", "RETIRED", "DELETED"}
                    ),
                    cause_type=cause_type,
                    cause_ref=created.asset_version_id,
                    created_by_operation_id=worker.causation_id,
                )
            self._event(
                uow,
                worker,
                aggregate_type="authority_source_content_profile",
                aggregate_id=profile_id,
                event_type="authority.source.content.profile.committed",
                causation_id=str(payload["execution_asset_version_id"]),
                payload={
                    "source_content_profile_id": profile_id,
                    "asset_version_id": created.asset_version_id,
                    "status": resolution["status"],
                    "resolved_content_type": resolution["resolved_content_type"],
                    "classifier_contract_hash": payload["classifier_contract_hash"],
                    "provider_calls_by_commit": 0,
                },
            )
            uow.commit()
        return {
            "source_content_profile_id": profile_id,
            "asset_version_id": created.asset_version_id,
            "content_hash": created.content_hash,
            "profile_status": resolution["status"],
            "resolved_content_type": resolution["resolved_content_type"],
        }

    def _execute_plan_fenced(self, worker: WorkerLeaseCommand) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            require_current_fence(uow, worker)
            repository = SourceProfileRepository(uow.cursor)
            replay = repository.operation_output(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                output_key="source.analysis.plan",
            )
            if replay is not None:
                return replay
            operation = uow.repositories.chapter_authority.operation_execution(
                worker.causation_id, worker.project_id
            )
            command = dict(operation["command_payload"])
            payload = dict(command["payload"])
            profile = repository.profile(
                project_id=worker.project_id,
                asset_version_id=str(payload["profile_asset_version_id"]),
            )
            if profile is None or profile["status"] != "ROUTABLE":
                raise KernelError(
                    "SOURCE_ANALYSIS_PROFILE_NOT_ROUTABLE",
                    "AnalysisPlan input Profile is no longer routable",
                )
            scope_hash = str(profile["content"]["logical_document_scope_hash"])
            current = repository.current_plan(
                project_id=worker.project_id,
                logical_document_scope_hash=scope_hash,
            )
            digest = scope_hash.removeprefix("sha256:")
            plan_id = f"source-analysis-plan:{worker.project_id}:{digest}"
            strategy = dict(payload["strategy"])
            content = {
                "schema_version": "source-analysis-plan.v1",
                "source_analysis_plan_id": plan_id,
                "project_id": worker.project_id,
                "workspace_id": str(command["workspace_id"]),
                "profile_asset_version_id": payload["profile_asset_version_id"],
                "logical_document_scope": profile["content"]["logical_document_scope"],
                "logical_document_scope_hash": scope_hash,
                "resolved_content_type": strategy["content_type"],
                "strategy": strategy,
                "strategy_contract_hash": payload["strategy_contract_hash"],
                "methodologies": payload["methodologies"],
                "methodology_contract_hash": payload["methodology_contract_hash"],
                "source_policy": {
                    "raw_source_text_in_postgresql": False,
                    "generation_context_allowed": False,
                    "reusable_knowledge": False,
                },
                "lineage": {
                    "created_by_operation_id": worker.causation_id,
                    "profile_asset_version_id": payload["profile_asset_version_id"],
                    "supersedes_asset_version_id": (
                        current["asset_version_id"] if current else None
                    ),
                },
            }
            created = uow.repositories.asset_documents.materialize_output(
                AuthorityAssetWriteCommand(
                    operation_id=worker.causation_id,
                    project_id=worker.project_id,
                    asset_id=plan_id,
                    asset_type="source_analysis_plan",
                    schema_version="source-analysis-plan.v1",
                    logical_ref=f"source-intelligence/plans/{digest}.json",
                    category="source-intelligence",
                    output_key="source.analysis.plan",
                    role="evidence",
                    content=content,
                    qualification_policy="source-analysis-plan-isolation-v1",
                    trace_id=worker.trace_id,
                    correlation_id=worker.correlation_id,
                    causation_id=str(payload["profile_asset_version_id"]),
                    expected_current_asset_version_id=(
                        str(current["asset_version_id"]) if current else None
                    ),
                    eligibility="INELIGIBLE",
                    governance="CLEAR",
                )
            )
            repository.register_plan(
                {
                    "source_analysis_plan_id": plan_id,
                    "project_id": worker.project_id,
                    "workspace_id": str(command["workspace_id"]),
                    "asset_version_id": created.asset_version_id,
                    "profile_asset_version_id": payload["profile_asset_version_id"],
                    "logical_document_scope_hash": scope_hash,
                    "resolved_content_type": strategy["content_type"],
                    "routing_policy_version": strategy["routing_policy_version"],
                    "profile_id": strategy["profile_id"],
                    "profile_version": strategy["profile_version"],
                    "strategy_contract_hash": payload["strategy_contract_hash"],
                    "methodology_contract_hash": payload["methodology_contract_hash"],
                    "methodologies": payload["methodologies"],
                    "mkaos_capability": strategy["mkaos_capability"],
                    "abstraction_policy_version": strategy[
                        "abstraction_policy_version"
                    ],
                    "status": "ACTIVE",
                    "created_by_operation_id": worker.causation_id,
                }
            )
            if current is not None:
                repository.supersede_plan(
                    project_id=worker.project_id,
                    asset_version_id=str(current["asset_version_id"]),
                )
            self._dependency(
                repository,
                worker,
                upstream=str(payload["profile_asset_version_id"]),
                downstream=created.asset_version_id,
                relationship="ROUTES",
                selector_key=str(payload["strategy_contract_hash"]),
            )
            if current is not None:
                cause = (
                    "METHODOLOGY_UPGRADE"
                    if current["methodology_contract_hash"]
                    != payload["methodology_contract_hash"]
                    else "ROUTING_POLICY_UPGRADE"
                    if current["strategy_contract_hash"]
                    != payload["strategy_contract_hash"]
                    else "UPSTREAM_REPLACED"
                )
                descendants = repository.descendants(
                    project_id=worker.project_id,
                    upstream_asset_version_id=str(current["asset_version_id"]),
                )
                repository.record_invalidations(
                    project_id=worker.project_id,
                    target_asset_version_ids=(
                        item["asset_version_id"]
                        for item in descendants
                        if item["lifecycle"]
                        not in {"SUPERSEDED", "REJECTED", "RETIRED", "DELETED"}
                    ),
                    cause_type=cause,
                    cause_ref=created.asset_version_id,
                    created_by_operation_id=worker.causation_id,
                )
            self._event(
                uow,
                worker,
                aggregate_type="authority_source_analysis_plan",
                aggregate_id=plan_id,
                event_type="authority.source.analysis.plan.committed",
                causation_id=str(payload["profile_asset_version_id"]),
                payload={
                    "source_analysis_plan_id": plan_id,
                    "asset_version_id": created.asset_version_id,
                    "strategy_contract_hash": payload["strategy_contract_hash"],
                    "methodology_contract_hash": payload["methodology_contract_hash"],
                    "provider_calls": 0,
                },
            )
            uow.commit()
        return {
            "source_analysis_plan_id": plan_id,
            "asset_version_id": created.asset_version_id,
            "content_hash": created.content_hash,
            "strategy_contract_hash": payload["strategy_contract_hash"],
        }

    def _ready(
        self,
        admitted: dict[str, Any],
        project_id: str,
        *,
        actor_id: str,
        reason: str,
        trace_id: str,
        correlation_id: str,
        causation_id: str,
    ) -> dict[str, Any]:
        operation_id = str(admitted["operation_id"])
        with AuthorityUnitOfWork(self.database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(
                operation_id, project_id
            )
            uow.cursor.execute(
                "SELECT definition_name FROM authority_operation WHERE operation_id=%s",
                [operation_id],
            )
            definition_name = str(uow.cursor.fetchone()[0])
        if state["status"] == "SUCCEEDED":
            return self.result(
                operation_id,
                project_id,
                definition_name=definition_name,
                replayed=True,
            )
        if state["status"] == "ADMITTED":
            transition_operation(
                self.database_url,
                OperationTransitionCommand(
                    operation_id=operation_id,
                    project_id=project_id,
                    expected_version=int(state["version"]),
                    expected_status="ADMITTED",
                    target_status="READY",
                    actor_id=actor_id,
                    reason=reason,
                    trace_id=trace_id,
                    correlation_id=correlation_id,
                    causation_id=causation_id,
                ),
            )
            with AuthorityUnitOfWork(self.database_url) as uow:
                state = uow.repositories.attempt_runtime.operation_state(
                    operation_id, project_id
                )
        return {
            "operation_id": operation_id,
            "project_id": project_id,
            "status": state["status"],
            "replayed": bool(admitted.get("replayed")),
            "duplicate": False,
        }

    def _context(self, actor_id: str, handler: str) -> AdmissionContext:
        return AdmissionContext(
            actor_id=actor_id,
            permissions=frozenset({"source.authority.execute"}),
            available_handlers=frozenset({handler}),
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )

    @staticmethod
    def _actor(actor_id: str, principal: Principal | None, project_id: str) -> str:
        if principal is None:
            return actor_id
        principal.require("source.authority.execute", project_id)
        return principal.principal_id

    @staticmethod
    def _require_succeeded(existing: dict[str, Any], code: str) -> None:
        if existing["operation_status"] != "SUCCEEDED":
            raise KernelError(
                code, "matching Source intelligence Operation requires recovery"
            )

    @staticmethod
    def _dependency(
        repository: SourceProfileRepository,
        worker: WorkerLeaseCommand,
        *,
        upstream: str,
        downstream: str,
        relationship: str,
        selector_key: str,
    ) -> None:
        repository.record_dependency(
            {
                "dependency_id": str(uuid4()),
                "project_id": worker.project_id,
                "upstream_asset_version_id": upstream,
                "downstream_asset_version_id": downstream,
                "relationship": relationship,
                "selector_key": selector_key,
                "created_by_operation_id": worker.causation_id,
            }
        )

    @staticmethod
    def _event(
        uow: AuthorityUnitOfWork,
        worker: WorkerLeaseCommand,
        *,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        causation_id: str,
        payload: dict[str, Any],
    ) -> None:
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": aggregate_type,
                "aggregate_id": aggregate_id,
                "operation_id": worker.causation_id,
                "project_id": worker.project_id,
                "event_type": event_type,
                "correlation_id": worker.correlation_id,
                "causation_id": causation_id,
                "payload": {
                    **payload,
                    "operation_id": worker.causation_id,
                    "trace_id": worker.trace_id,
                    "attempt_id": worker.attempt_id,
                    "fencing_token": worker.fencing_token,
                },
            }
        )


def _require_strings(*values: str) -> None:
    if any(not str(value).strip() for value in values):
        raise ValueError("Source Profile command strings must not be empty")


def _contains_source_text(value: Any) -> bool:
    if isinstance(value, dict):
        forbidden = {"raw_text", "source_text", "sample_text", "text", "content"}
        if forbidden.intersection(str(key).lower() for key in value):
            return True
        return any(_contains_source_text(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_source_text(item) for item in value)
    return False


def _classification_execution_binding(
    execution: dict[str, Any],
    *,
    evidence_class: str,
    scope_hash: str,
    classifier_contract_hash: str,
    classification_input_hash: str,
    classification_output_hash: str,
    allow_fixture: bool,
) -> dict[str, Any]:
    content = dict(execution["content"])
    if content.get("qualification_status") == "BENCHMARK_ONLY":
        raise KernelError("SOURCE_BENCHMARK_CANNOT_COMMIT", "calibration evidence cannot commit a Source Profile")
    binding = dict(content.get("source_classification_binding") or {})
    expected = {
        "schema_version": "source-classification-execution-binding.v1",
        "logical_document_scope_hash": scope_hash,
        "classifier_contract_hash": classifier_contract_hash,
        "classification_input_hash": classification_input_hash,
        "classification_output_hash": classification_output_hash,
    }
    if binding != expected:
        raise KernelError(
            "SOURCE_CLASSIFICATION_EXECUTION_MISMATCH",
            "classifier execution evidence differs from the committed Profile",
        )
    fixture = bool(content.get("fixture_protocol_only"))
    real = bool(content.get("real_provider_proven"))
    verified = bool(content.get("production_verified"))
    if fixture:
        if evidence_class != "FIXTURE" or not allow_fixture:
            raise KernelError(
                "SOURCE_CLASSIFICATION_FIXTURE_BLOCKED",
                "fixture classification is disabled outside explicit tests",
            )
    elif evidence_class == "FIXTURE":
        raise KernelError(
            "SOURCE_CLASSIFICATION_EVIDENCE_CONFLICT",
            "non-fixture classification cannot be labeled FIXTURE",
        )
    elif evidence_class == "PROVIDER_QUALIFIED" and not (real and verified):
        raise KernelError(
            "SOURCE_CLASSIFICATION_PROVIDER_NOT_QUALIFIED",
            "qualified classification requires verified provider evidence",
        )
    return binding


def _profile_change_cause(current: dict[str, Any], payload: dict[str, Any]) -> str:
    if current["classifier_contract_hash"] != payload["classifier_contract_hash"]:
        return "CLASSIFIER_UPGRADE"
    if current["override_contract_hash"] != payload["override_contract_hash"]:
        return "PROFILE_OVERRIDE"
    if current["intelligence_policy_hash"] != payload["intelligence_policy_hash"]:
        return "POLICY_UPGRADE"
    return "UPSTREAM_REPLACED"


__all__ = [
    "CommitSourceAnalysisPlanCommand",
    "CommitSourceContentProfileCommand",
    "SourceProfilingApplication",
]
