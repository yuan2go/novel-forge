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
    CHAPTER_RECOVERABLE_MODEL_DEFINITION_VERSIONS,
    chapter_operation_definitions,
    CHAPTER_SAMPLE_WORKFLOW_ID,
    chapter_provider_sample_definitions,
)
from novel_forge.modules.chapter_authority.execution_gateway import (
    chapter_stage_capability,
)
from novel_forge.modules.chapter_authority.scheduler import _admission_dependencies
from novel_forge.modules.book_followup_authority.contracts import (
    BOOK_FOLLOWUP_DEFINITION_VERSION,
    READER_OUTCOME_DEFINITION,
)
from novel_forge.modules.story_planning_runtime.domain import (
    STORY_PLANNING_WORKFLOW_DEFINITION_REF,
)
from novel_forge.modules.story_design_authority.evaluation_runtime import (
    NARRATIVE_EVALUATION_DEFINITION,
    NARRATIVE_EVALUATION_HANDLER,
    NARRATIVE_EVALUATION_VERSION,
)
from novel_forge.modules.agent_runtime.definitions import (
    AGENT_RUNTIME_HARNESS_HANDLER_KEY,
    AGENT_SESSION_WORKFLOW_DEFINITION_ID,
    AGENT_SESSION_WORKFLOW_DEFINITION_VERSION,
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

    def get(
        self, definition_name: str, definition_version: str
    ) -> Mapping[str, Any] | None: ...

    def get_release(
        self,
        definition_name: str,
        definition_version: str,
        *,
        commit_sha: str,
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

    def __init__(self, repository: OperationDefinitionReader) -> None:
        self._repository = repository

    def load(
        self,
        identities: Iterable[tuple[str, str]],
        *,
        commit_sha: str = "",
    ) -> InMemoryOperationDefinitionCatalog:
        rows: list[Mapping[str, Any]] = []
        for definition_name, definition_version in sorted(set(identities)):
            row = (
                self._repository.get_release(
                    definition_name,
                    definition_version,
                    commit_sha=commit_sha,
                )
                if commit_sha
                else self._repository.get(definition_name, definition_version)
            )
            if row is None:
                raise KeyError(
                    f"operation definition not found: {definition_name}@{definition_version}"
                )
            calculated = definition_hash(dict(row))
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
    "execution_intent": "planning.chapter.generate",
    "memo": "planning.chapter.memo",
    "retrieval": "retrieval.embed",
    "best_candidate": "planning.chapter.generate",
    "context": "context.task.compile",
    "canon_proposal": "canon.extract",
    "canon": "canon.extract",
    "quality": "quality.aggregate",
    "publish_gate": "publishing.release.query",
    "export": "storage.object.put",
    "final_release_gate": "publishing.release.query",
}


def chapter_workflow_binding_catalog(*, coordinated_contract: bool = True) -> WorkflowBindingCatalog:
    bindings: list[WorkflowBinding] = []
    for node in ChapterNode:
        capability = _NON_PROVIDER_CAPABILITIES.get(node.value)
        if capability is None:
            capability = chapter_stage_capability(node.value).value
        bindings.append(
            WorkflowBinding(
                node_id=node.value,
                operation_name=node.definition_name,
                stage="canon_support" if node is ChapterNode.CANON_PROPOSAL else node.value,
                handler_key=node.handler_key,
                capability_id=capability,
                depends_on=tuple(item.value for item in _admission_dependencies(node)),
                primary_output_asset_type=node.asset_type,
            )
        )
    return WorkflowBindingCatalog(
        CHAPTER_MODEL_WORKFLOW_DEFINITION_ID,
        "3.10.0" if coordinated_contract else CHAPTER_MODEL_WORKFLOW_DEFINITION_VERSION,
        bindings,
    )


def chapter_sampling_workflow_binding_catalog(*, reference: bool = False, reference_samples: bool = False, coordinated_contract: bool = True) -> WorkflowBindingCatalog:
    from novel_forge.modules.command_kernel.routing_bootstrap import (
        CHAPTER_GENERATOR_TASKS, CHAPTER_REFERENCE_TASKS, CHAPTER_SAMPLE_DEFINITION_VERSION,
        CHAPTER_REFERENCE_SAMPLE_VERSION, CHAPTER_REFERENCE_SAMPLE_SOURCES,
        chapter_sample_definition_name,
    )
    from novel_forge.modules.chapter_authority.definitions import CHAPTER_REFERENCE_WORKFLOW_ID

    formal = chapter_workflow_binding_catalog(coordinated_contract=coordinated_contract)
    return WorkflowBindingCatalog(
        CHAPTER_REFERENCE_WORKFLOW_ID if reference else CHAPTER_SAMPLE_WORKFLOW_ID,
        (CHAPTER_REFERENCE_SAMPLE_VERSION if reference_samples else CHAPTER_SAMPLE_DEFINITION_VERSION) if coordinated_contract else ("2.5.0" if reference_samples else "2.4.0"),
        (WorkflowBinding(
            node_id="canon_proposal" if stage == "canon_support" else stage, operation_name=chapter_sample_definition_name(stage), stage=stage,
            handler_key="novel_forge.chapter_authority.sample." + stage,
            capability_id=formal.resolve("canon_proposal" if stage == "canon_support" else stage).capability_id, depends_on=(),
            primary_output_asset_type="chapter_provider_sample",
        ) for stage in (CHAPTER_REFERENCE_SAMPLE_SOURCES if reference_samples else (CHAPTER_REFERENCE_TASKS if reference else CHAPTER_GENERATOR_TASKS).values())),
    )


def story_planning_workflow_binding_catalog() -> WorkflowBindingCatalog:
    from novel_forge.modules.story_planning_runtime.foundation_generation import FOUNDATION_CAPABILITIES

    capabilities = (
        *FOUNDATION_CAPABILITIES,
        ("book_plan.generate", "planning.book.generate"),
        ("volume_plan.generate", "planning.volume.generate"),
        ("arc_plan.generate", "planning.arc.generate"),
        ("chapter_group_plan.generate", "planning.chapter_group.generate"),
        ("chapter_plan.generate", "planning.story_chapter.generate"),
    )
    return WorkflowBindingCatalog(
        "story_planning_generators",
        STORY_PLANNING_WORKFLOW_DEFINITION_REF.rpartition("@")[2],
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


def world_sampling_workflow_binding_catalog(*, reference_samples: bool = False) -> WorkflowBindingCatalog:
    return WorkflowBindingCatalog("world_provider_sampling", "1.1.0" if reference_samples else "1.0.0", (
        WorkflowBinding(node_id="world_candidates." + action, operation_name="world.provider.sample." + action,
            stage="world_candidates." + action, handler_key="novel_forge.world.provider.sample." + action,
            capability_id="planning.story_chapter.generate", depends_on=(), primary_output_asset_type="world_provider_sample")
        for action in (("evaluate",) if reference_samples else ("generate", "evaluate", "actor_0", "actor_1", "actor_2"))))


def reader_outcome_workflow_binding_catalog(version: str = BOOK_FOLLOWUP_DEFINITION_VERSION) -> WorkflowBindingCatalog:
    if version not in {"1.1.0", "1.2.0", "1.3.0", "1.4.0"}:
        raise ValueError("Reader workflow requires an explicit supported contract")
    return WorkflowBindingCatalog(
        "book_followup_reader_outcome",
        version,
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


def working_memory_workflow_binding_catalog() -> WorkflowBindingCatalog:
    return WorkflowBindingCatalog("book_followup_working_memory_extract", BOOK_FOLLOWUP_DEFINITION_VERSION, (
        WorkflowBinding(node_id="working_memory_extract", operation_name="working_memory_extract", stage="working_memory_extract",
            handler_key="novel_forge.book_followup_authority.working_memory_extract", capability_id="canon.extract",
            depends_on=(), primary_output_asset_type="working_memory_result"),
    ))


def longform_prose_review_workflow_binding_catalog(*, provider_sampling: bool = False) -> WorkflowBindingCatalog:
    from novel_forge.modules.book_followup_authority.prose_sampling import PROSE_SAMPLE_DEFINITION, PROSE_SAMPLE_TYPE, PROSE_SAMPLE_VERSION

    name = PROSE_SAMPLE_DEFINITION if provider_sampling else "longform.prose_review"
    return WorkflowBindingCatalog("book_followup_prose_sampling" if provider_sampling else "book_followup_longform_prose_review", PROSE_SAMPLE_VERSION if provider_sampling else BOOK_FOLLOWUP_DEFINITION_VERSION, (
        WorkflowBinding(node_id="longform_prose_review", operation_name=name, stage="longform_prose_review", handler_key="novel_forge.book_followup_authority." + name, capability_id="review.chapter.evaluate", depends_on=(), primary_output_asset_type=PROSE_SAMPLE_TYPE if provider_sampling else "longform_prose_review_report"),
    ))


def screenplay_workflow_binding_catalog(stage: str, *, provider_sampling: bool = False) -> WorkflowBindingCatalog:
    from novel_forge.modules.book_followup_authority.screenplay import SCREENPLAY_STAGES, CANDIDATE_TYPE, REVIEW_TYPE
    from novel_forge.modules.chapter_authority.execution_gateway import chapter_stage_capability
    if stage not in SCREENPLAY_STAGES:
        raise ValueError("Unknown screenplay workflow stage")
    from novel_forge.modules.book_followup_authority.screenplay_sampling import SCREENPLAY_SAMPLE_VERSION, SCREENPLAY_SAMPLE_TYPE, sample_definition_name
    name = sample_definition_name(stage) if provider_sampling else stage
    return WorkflowBindingCatalog("book_followup_" + stage + ("_sampling" if provider_sampling else ""),
        SCREENPLAY_SAMPLE_VERSION if provider_sampling else BOOK_FOLLOWUP_DEFINITION_VERSION, (
        WorkflowBinding(node_id=stage, operation_name=name, stage=stage,
            handler_key="novel_forge.book_followup_authority." + name,
            capability_id=chapter_stage_capability(stage), depends_on=(),
            primary_output_asset_type=SCREENPLAY_SAMPLE_TYPE if provider_sampling else REVIEW_TYPE if stage == "screenplay_review" else CANDIDATE_TYPE),
    ))


def narrative_evaluation_workflow_binding_catalog() -> WorkflowBindingCatalog:
    return WorkflowBindingCatalog(
        "story_design_semantic_evaluation",
        NARRATIVE_EVALUATION_VERSION,
        (
            WorkflowBinding(
                node_id="narrative_semantic_evaluation",
                operation_name=NARRATIVE_EVALUATION_DEFINITION,
                stage="narrative_semantic_evaluation",
                handler_key=NARRATIVE_EVALUATION_HANDLER,
                capability_id="quality.intrinsic.judge",
                depends_on=(),
                primary_output_asset_type="narrative_design_evaluation",
            ),
        ),
    )


def model_reference_creation_workflow_binding_catalog() -> WorkflowBindingCatalog:
    from novel_forge.modules.chapter_quality_authority.model_reference_execution import (
        MODEL_REFERENCE_STAGE, MODEL_REFERENCE_HANDLER, MODEL_REFERENCE_OUTPUT,
    )
    return WorkflowBindingCatalog("model_reference_creation", "1.0.0", (
        WorkflowBinding(node_id=stage, operation_name=name, stage=stage,
            handler_key=MODEL_REFERENCE_HANDLER, capability_id="quality.intrinsic.judge",
            depends_on=(), primary_output_asset_type=MODEL_REFERENCE_OUTPUT)
        for name, stage in MODEL_REFERENCE_STAGE.items()))


def agent_session_workflow_binding_catalog() -> WorkflowBindingCatalog:
    return WorkflowBindingCatalog(
        AGENT_SESSION_WORKFLOW_DEFINITION_ID,
        AGENT_SESSION_WORKFLOW_DEFINITION_VERSION,
        (
            WorkflowBinding(
                node_id="agent_session",
                operation_name="agent.session.execute",
                stage="agent_session",
                handler_key=AGENT_RUNTIME_HARNESS_HANDLER_KEY,
                capability_id="agent.workspace.execute",
                depends_on=(),
                primary_output_asset_type="",
            ),
        ),
    )


def governed_workflow_binding_catalog(
    workflow_id: str, workflow_version: str
) -> WorkflowBindingCatalog:
    if workflow_id == CHAPTER_MODEL_WORKFLOW_DEFINITION_ID and workflow_version in CHAPTER_RECOVERABLE_MODEL_DEFINITION_VERSIONS:
        current = chapter_workflow_binding_catalog()
        # COMPATIBILITY: Shared node routing does not replace frozen database contracts/assets.
        return WorkflowBindingCatalog(workflow_id, workflow_version, current.bindings())
    catalogs = (
        chapter_workflow_binding_catalog(coordinated_contract=False),
        chapter_workflow_binding_catalog(coordinated_contract=True),
        chapter_sampling_workflow_binding_catalog(coordinated_contract=False),
        chapter_sampling_workflow_binding_catalog(reference=True, coordinated_contract=False),
        chapter_sampling_workflow_binding_catalog(reference=True, reference_samples=True, coordinated_contract=False),
        chapter_sampling_workflow_binding_catalog(),
        chapter_sampling_workflow_binding_catalog(reference=True),
        chapter_sampling_workflow_binding_catalog(reference=True, reference_samples=True),
        story_planning_workflow_binding_catalog(),
        world_sampling_workflow_binding_catalog(),
        world_sampling_workflow_binding_catalog(reference_samples=True),
        reader_outcome_workflow_binding_catalog(),
        reader_outcome_workflow_binding_catalog("1.2.0"),
        reader_outcome_workflow_binding_catalog("1.3.0"),
        reader_outcome_workflow_binding_catalog("1.4.0"),
        working_memory_workflow_binding_catalog(),
        longform_prose_review_workflow_binding_catalog(),
        longform_prose_review_workflow_binding_catalog(provider_sampling=True),
        *(screenplay_workflow_binding_catalog(stage, provider_sampling=sample) for stage in ("screenplay_generate", "screenplay_review", "screenplay_revision") for sample in (False, True)),
        narrative_evaluation_workflow_binding_catalog(),
        model_reference_creation_workflow_binding_catalog(),
        agent_session_workflow_binding_catalog(),
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
    from novel_forge.modules.chapter_quality_authority.model_reference_execution import model_reference_creation_definitions

    return InMemoryOperationDefinitionCatalog(
        (*chapter_operation_definitions(
            application_build_id=application_build_id,
            commit_sha=release_sha,
            model_effects_required=True,
        ), *(item for item in chapter_operation_definitions(
            application_build_id=application_build_id, commit_sha=release_sha,
            model_effects_required=True, coordinated_contract=True,
        )), *chapter_provider_sample_definitions(
            application_build_id=application_build_id, commit_sha=release_sha,
        ), *chapter_provider_sample_definitions(
            application_build_id=application_build_id, commit_sha=release_sha, reference_samples=True,
        ), *chapter_provider_sample_definitions(
            application_build_id=application_build_id, commit_sha=release_sha, definition_version="2.4.0",
        ), *chapter_provider_sample_definitions(
            application_build_id=application_build_id, commit_sha=release_sha, reference_samples=True, definition_version="2.5.0",
        ), *model_reference_creation_definitions(
            application_build_id=application_build_id, commit_sha=release_sha,
        ))
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
    "agent_session_workflow_binding_catalog",
    "chapter_workflow_binding_catalog",
    "governed_workflow_binding_catalog",
    "narrative_evaluation_workflow_binding_catalog",
    "model_reference_creation_workflow_binding_catalog",
    "reader_outcome_workflow_binding_catalog",
    "story_planning_workflow_binding_catalog",
]
