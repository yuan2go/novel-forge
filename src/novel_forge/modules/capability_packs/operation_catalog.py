"""Read-only OperationDefinition resolution over the existing Authority contract."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Any, Protocol

from novel_forge.modules.chapter_authority.contracts import ChapterNode
from novel_forge.modules.chapter_authority.definitions import (
    CHAPTER_MODEL_WORKFLOW_DEFINITION_ID,
    CHAPTER_MODEL_WORKFLOW_DEFINITION_VERSION,
    chapter_operation_definitions,
)
from novel_forge.modules.chapter_authority.execution_gateway import (
    chapter_stage_capability,
)
from novel_forge.modules.chapter_authority.scheduler import _admission_dependencies
from novel_forge.modules.book_followup_authority.contracts import (
    BOOK_FOLLOWUP_DEFINITION_VERSION,
    READER_OUTCOME_DEFINITION,
)
from novel_forge.storage.authority_repositories import definition_hash


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


@dataclass(frozen=True, slots=True)
class ResolvedOperationDefinition:
    definition_name: str
    definition_version: str
    definition_hash: str
    enabled: bool
    family: str
    handler_key: str
    handler_contract_version: str
    execution_mode: str
    idempotency_scope: str
    concurrency_key_template: str
    application_build_id: str
    source_commit_sha: str
    command_schema_json: str
    result_schema_json: str
    permissions: tuple[str, ...]
    approval_policy_json: str
    retry_policy_json: str
    timeout_policy_json: str
    cancellation_policy_json: str
    compensation_policy_json: str
    irreversible_effect_policy_json: str
    external_capabilities: tuple[str, ...]
    policy_json: str
    completion_contract_json: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "ResolvedOperationDefinition":
        enabled = row["enabled"]
        if type(enabled) is not bool:
            raise TypeError("OperationDefinition enabled must be an exact boolean")
        return cls(
            definition_name=str(row["name"]),
            definition_version=str(row["definition_version"]),
            definition_hash=definition_hash(dict(row)),
            enabled=enabled,
            family=str(row["family"]),
            handler_key=str(row["handler_key"]),
            handler_contract_version=str(row["handler_contract_version"]),
            execution_mode=str(row["execution_mode"]),
            idempotency_scope=str(row["idempotency_scope"]),
            concurrency_key_template=str(row["concurrency_key_template"]),
            application_build_id=str(row["application_build_id"]),
            source_commit_sha=str(row["commit_sha"]),
            command_schema_json=_canonical(row["command_schema"]),
            result_schema_json=_canonical(row["result_schema"]),
            permissions=tuple(sorted(str(item) for item in row["permissions"])),
            approval_policy_json=_canonical(row["approval_policy"]),
            retry_policy_json=_canonical(row["retry_policy"]),
            timeout_policy_json=_canonical(row["timeout_policy"]),
            cancellation_policy_json=_canonical(row["cancellation_policy"]),
            compensation_policy_json=_canonical(row["compensation_policy"]),
            irreversible_effect_policy_json=_canonical(
                row["irreversible_effect_policy"]
            ),
            external_capabilities=tuple(
                sorted(str(item) for item in row["external_capabilities"])
            ),
            policy_json=_canonical(row["policy"]),
            completion_contract_json=_canonical(row["completion_contract"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "definition_name": self.definition_name,
            "definition_version": self.definition_version,
            "definition_hash": self.definition_hash,
            "enabled": self.enabled,
            "family": self.family,
            "handler_key": self.handler_key,
            "handler_contract_version": self.handler_contract_version,
            "execution_mode": self.execution_mode,
            "idempotency_scope": self.idempotency_scope,
            "concurrency_key_template": self.concurrency_key_template,
            "application_build_id": self.application_build_id,
            "source_commit_sha": self.source_commit_sha,
            "command_schema": json.loads(self.command_schema_json),
            "result_schema": json.loads(self.result_schema_json),
            "permissions": list(self.permissions),
            "approval_policy": json.loads(self.approval_policy_json),
            "retry_policy": json.loads(self.retry_policy_json),
            "timeout_policy": json.loads(self.timeout_policy_json),
            "cancellation_policy": json.loads(self.cancellation_policy_json),
            "compensation_policy": json.loads(self.compensation_policy_json),
            "irreversible_effect_policy": json.loads(
                self.irreversible_effect_policy_json
            ),
            "external_capabilities": list(self.external_capabilities),
            "policy": json.loads(self.policy_json),
            "completion_contract": json.loads(self.completion_contract_json),
        }


class OperationDefinitionCatalog(Protocol):
    def resolve(
        self, definition_name: str, definition_version: str
    ) -> ResolvedOperationDefinition: ...

    def snapshot_hash(self) -> str: ...


class OperationDefinitionReader(Protocol):
    """Minimal read-only shape implemented by OperationDefinitionRepository."""

    def get(
        self, definition_name: str, definition_version: str
    ) -> Mapping[str, Any] | None: ...


class InMemoryOperationDefinitionCatalog:
    def __init__(self, definitions: Iterable[Mapping[str, Any]]) -> None:
        values: dict[tuple[str, str], ResolvedOperationDefinition] = {}
        for row in definitions:
            resolved = ResolvedOperationDefinition.from_row(row)
            key = (resolved.definition_name, resolved.definition_version)
            existing = values.get(key)
            if existing is not None and existing != resolved:
                raise ValueError(
                    "operation definition name/version is bound to a different full snapshot"
                )
            values[key] = resolved
        self._values = MappingProxyType(values)

    def resolve(
        self, definition_name: str, definition_version: str
    ) -> ResolvedOperationDefinition:
        try:
            return self._values[(definition_name, definition_version)]
        except KeyError as exc:
            raise KeyError(
                f"operation definition not found: {definition_name}@{definition_version}"
            ) from exc

    def definitions(self) -> tuple[ResolvedOperationDefinition, ...]:
        return tuple(self._values[key] for key in sorted(self._values))

    def snapshot_hash(self) -> str:
        import hashlib

        payload = [item.to_dict() for item in self.definitions()]
        return (
            "sha256:"
            + hashlib.sha256(_canonical({"definitions": payload}).encode()).hexdigest()
        )


class RepositoryOperationDefinitionLoader:
    """Read-only preload adapter; the compiler receives only its memory snapshot."""

    def __init__(self, repository: OperationDefinitionReader) -> None:
        self._repository = repository

    def load(
        self, identities: Iterable[tuple[str, str]]
    ) -> InMemoryOperationDefinitionCatalog:
        rows: list[Mapping[str, Any]] = []
        for definition_name, definition_version in sorted(set(identities)):
            row = self._repository.get(definition_name, definition_version)
            if row is None:
                raise KeyError(
                    f"operation definition not found: {definition_name}@{definition_version}"
                )
            calculated = definition_hash(row)
            persisted = str(row.get("definition_hash") or "")
            if persisted and persisted != calculated:
                raise ValueError(
                    "persisted OperationDefinition hash does not match content"
                )
            rows.append(row)
        return InMemoryOperationDefinitionCatalog(rows)


@dataclass(frozen=True, slots=True)
class WorkflowBinding:
    node_id: str
    operation_name: str
    stage: str
    handler_key: str
    capability_id: str
    depends_on: tuple[str, ...]
    primary_output_asset_type: str


class WorkflowBindingCatalog:
    def __init__(
        self,
        workflow_id: str,
        workflow_version: str,
        bindings: Iterable[WorkflowBinding],
    ) -> None:
        self.workflow_id = workflow_id
        self.workflow_version = workflow_version
        source = tuple(bindings)
        values = {item.node_id: item for item in source}
        if len(values) != len(source):
            raise ValueError("workflow binding node conflict")
        self._values = MappingProxyType(values)

    def bindings(self) -> tuple[WorkflowBinding, ...]:
        return tuple(self._values[key] for key in sorted(self._values))

    def resolve(self, node_id: str) -> WorkflowBinding:
        try:
            return self._values[node_id]
        except KeyError as exc:
            raise KeyError(f"workflow binding not found: {node_id}") from exc


_NON_PROVIDER_CAPABILITIES = {
    "plan": "planning.chapter.generate",
    "context": "retrieval.index.query",
    "canon_proposal": "canon.extract",
    "canon": "canon.extract",
    "quality": "quality.aggregate",
    "publish_gate": "publishing.release.query",
    "export": "storage.object.put",
    "final_release_gate": "publishing.release.query",
}


def chapter_workflow_binding_catalog() -> WorkflowBindingCatalog:
    bindings: list[WorkflowBinding] = []
    for node in ChapterNode:
        capability = _NON_PROVIDER_CAPABILITIES.get(node.value)
        if capability is None:
            capability = chapter_stage_capability(node.value).value
        bindings.append(
            WorkflowBinding(
                node_id=node.value,
                operation_name=node.definition_name,
                stage=node.value,
                handler_key=node.handler_key,
                capability_id=capability,
                depends_on=tuple(item.value for item in _admission_dependencies(node)),
                primary_output_asset_type=node.asset_type,
            )
        )
    return WorkflowBindingCatalog(
        CHAPTER_MODEL_WORKFLOW_DEFINITION_ID,
        CHAPTER_MODEL_WORKFLOW_DEFINITION_VERSION,
        bindings,
    )


def story_planning_workflow_binding_catalog() -> WorkflowBindingCatalog:
    capabilities = (
        ("book_plan.generate", "planning.book.generate"),
        ("volume_plan.generate", "planning.volume.generate"),
        ("arc_plan.generate", "planning.arc.generate"),
        ("chapter_group_plan.generate", "planning.chapter_group.generate"),
        ("chapter_plan.generate", "planning.story_chapter.generate"),
    )
    return WorkflowBindingCatalog(
        "story_planning_generators",
        "1.1.0",
        (
            WorkflowBinding(
                node_id=node_id,
                operation_name="story_planning.generate",
                stage=node_id,
                handler_key="novel_forge.story_planning.generate",
                capability_id=capability,
                depends_on=(),
                primary_output_asset_type="planning_generation_candidate",
            )
            for node_id, capability in capabilities
        ),
    )


def reader_outcome_workflow_binding_catalog() -> WorkflowBindingCatalog:
    return WorkflowBindingCatalog(
        "book_followup_reader_outcome",
        BOOK_FOLLOWUP_DEFINITION_VERSION,
        (
            WorkflowBinding(
                node_id="reader_outcome",
                operation_name=READER_OUTCOME_DEFINITION,
                stage="reader_outcome",
                handler_key=(
                    f"novel_forge.book_followup_authority.{READER_OUTCOME_DEFINITION}"
                ),
                capability_id="quality.reader_outcome.judge",
                depends_on=(),
                primary_output_asset_type="reader_outcome_report",
            ),
        ),
    )


def governed_workflow_binding_catalog(
    workflow_id: str, workflow_version: str
) -> WorkflowBindingCatalog:
    catalogs = (
        chapter_workflow_binding_catalog(),
        story_planning_workflow_binding_catalog(),
        reader_outcome_workflow_binding_catalog(),
    )
    for catalog in catalogs:
        if (catalog.workflow_id, catalog.workflow_version) == (
            workflow_id,
            workflow_version,
        ):
            return catalog
    raise KeyError(
        f"governed workflow binding not found: {workflow_id}@{workflow_version}"
    )


def chapter_operation_definition_catalog(
    *, release_sha: str, application_build_id: str = "novel-forge-capability-compiler"
) -> InMemoryOperationDefinitionCatalog:
    return InMemoryOperationDefinitionCatalog(
        chapter_operation_definitions(
            application_build_id=application_build_id,
            commit_sha=release_sha,
            model_effects_required=True,
        )
    )


__all__ = [
    "InMemoryOperationDefinitionCatalog",
    "OperationDefinitionCatalog",
    "OperationDefinitionReader",
    "RepositoryOperationDefinitionLoader",
    "ResolvedOperationDefinition",
    "WorkflowBinding",
    "WorkflowBindingCatalog",
    "chapter_operation_definition_catalog",
    "chapter_workflow_binding_catalog",
    "governed_workflow_binding_catalog",
    "reader_outcome_workflow_binding_catalog",
    "story_planning_workflow_binding_catalog",
]
