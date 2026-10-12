from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .sampling import ChapterProviderSampleCommand

from novel_forge.modules.chapter_authority.handlers import (
    build_chapter_handler_registry,
)
from novel_forge.modules.chapter_authority.model_effects import (
    ChapterAgentBindingRecorder,
    ExternalEffectChapterModelPort,
)
from novel_forge.modules.chapter_authority.execution_gateway import (
    PostgresChapterExecutionContractBinder,
)
from novel_forge.modules.chapter_authority.orchestrator import (
    ChapterSagaAdmission,
    ChapterSliceResult,
    SingleChapterRequest,
    admit_single_chapter_saga,
    recover_single_chapter_admission,
    run_single_chapter_slice,
)
from novel_forge.modules.chapter_authority.scheduler import ChapterAuthorityScheduler
from novel_forge.modules.authority_security import Principal
from novel_forge.modules.chapter_authority.queries import ChapterAuthorityQuery
from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapter,
)
from novel_forge.modules.context_builder.embedding_projection import (
    RetrievalEmbeddingProjectionRuntime,
)


class ChapterAuthorityApplication:
    def __init__(
        self,
        database_url: str,
        *,
        model_adapter: ExternalEffectAdapter,
        object_store_adapter: ExternalEffectAdapter,
        worker_id: str,
        capability_binder: PostgresChapterExecutionContractBinder | None = None,
        embedding_capability_binder: PostgresChapterExecutionContractBinder
        | None = None,
        allow_synchronous_fixture: bool = True,
        max_cost_per_model_call: str = "0",
        budget_caps: dict[str, str] | None = None,
        embedding_budget_caps: dict[str, str] | None = None,
        agent_binding_recorder: ChapterAgentBindingRecorder | None = None,
        agent_binding_required: bool = False,
        runtime_fault_injector: Callable[[str], None] | None = None,
        application_build_id: str = "chapter-authority-runtime",
        commit_sha: str = "0" * 40,
    ) -> None:
        if not database_url or not worker_id:
            raise ValueError("PostgreSQL database and worker identity are required")
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.agent_binding_recorder = agent_binding_recorder
        self._model_port = ExternalEffectChapterModelPort(
            database_url,
            adapter=model_adapter,
            worker_id=f"{worker_id}:model",
            max_cost_per_call=max_cost_per_model_call,
            budget_caps=budget_caps,
            agent_binding_recorder=agent_binding_recorder,
            agent_binding_required=agent_binding_required,
            fault_injector=runtime_fault_injector,
            capability_binder=capability_binder,
        )
        self.registry = build_chapter_handler_registry(self._model_port)
        self._embedding_model_port = (
            ExternalEffectChapterModelPort(
                database_url,
                adapter=model_adapter,
                worker_id=f"{worker_id}:retrieval-embedding:model",
                max_cost_per_call=max_cost_per_model_call,
                budget_caps=(
                    embedding_budget_caps
                    if embedding_budget_caps is not None
                    else budget_caps
                ),
                fault_injector=runtime_fault_injector,
                capability_binder=embedding_capability_binder,
                execution_binding_domain="retrieval_projection",
            )
            if self.registry.semantic_retrieval_available
            else None
        )
        self.embedding_projection_runtime = (
            RetrievalEmbeddingProjectionRuntime(
                database_url,
                provider=self._embedding_model_port,
                worker_id=f"{worker_id}:retrieval-embedding",
                application_build_id=application_build_id,
                commit_sha=commit_sha,
            )
            if self._embedding_model_port is not None
            else None
        )
        self._object_store_adapter = object_store_adapter
        self.worker_id = worker_id
        self.allow_synchronous_fixture = allow_synchronous_fixture
        self.runtime_fault_injector = runtime_fault_injector
        self.query = ChapterAuthorityQuery(database_url)

    def prepare_provider_sample(self, command: ChapterProviderSampleCommand, *, principal: Principal) -> dict[str, Any]:
        from .sampling import prepare_provider_sample

        return prepare_provider_sample(self, command, principal=principal)

    def admit_provider_sample(self, command: ChapterProviderSampleCommand, *, principal: Principal) -> dict[str, Any]:
        from .sampling import admit_provider_sample

        return admit_provider_sample(self, command, principal=principal)

    def run(self, request: SingleChapterRequest) -> ChapterSliceResult:
        if not self.allow_synchronous_fixture:
            raise RuntimeError(
                "synchronous Chapter Authority execution is disabled; use durable admission"
            )
        return run_single_chapter_slice(
            self.database_url,
            request=request,
            registry=self.registry,
            object_store_adapter=self._object_store_adapter,
        )

    def admit(
        self,
        request: SingleChapterRequest,
        *,
        principal: Principal,
    ) -> ChapterSagaAdmission:
        principal.require("chapter.authority.execute", request.project_id)
        if request.actor_id != principal.principal_id:
            raise PermissionError("Chapter command actor must be the trusted Principal")
        adoption = (request.preparation_report or {}).get("author_draft_adoption")
        if adoption:
            if adoption.get("contract_version") == "book-edition-draft-adoption.v1":
                from novel_forge.modules.book_authority.edition_runtime import freeze_edition_adoption
                frozen = freeze_edition_adoption(
                    self.database_url, project_id=request.project_id, workspace_id=request.workspace_id,
                    book_id=request.book_id, chapter=request.chapter, revision_id=adoption["revision_id"],
                    book_run_id=adoption["book_run_id"], principal=principal, chapter_request=request,
                )
            else:
                from .author_draft import freeze_author_adoption
                frozen = freeze_author_adoption(
                    self.database_url, project_id=request.project_id, workspace_id=request.workspace_id,
                    book_id=request.book_id, chapter=request.chapter,
                    candidate_asset_version_id=str(adoption.get("candidate_asset_version_id") or ""),
                    decision_asset_version_id=str(adoption.get("decision_asset_version_id") or ""), principal=principal,
                )
            if dict(adoption) != frozen:
                raise ValueError("Author adoption must match its exact immutable candidate and author decision")
            if frozen.get("contract_version") == "book-edition-draft-adoption.v1":
                from novel_forge.modules.book_authority.edition_planning import require_edition_execution_plan
                require_edition_execution_plan(self.database_url, project_id=request.project_id, book_id=request.book_id,
                    book_run_id=frozen["book_run_id"], execution_plan_version_id=request.chapter_plan_asset_version_id,
                    revision_id=frozen["revision_id"], chapter=request.chapter, source_plan_version_id=frozen["source_chapter_plan_asset_version_id"])
            elif frozen["source_chapter_plan_asset_version_id"] and frozen["source_chapter_plan_asset_version_id"] != request.chapter_plan_asset_version_id:
                from novel_forge.modules.command_kernel.errors import KernelError
                raise KernelError("AUTHOR_PLAN_DRIFT", "Reprepare from the author's exact source Chapter Plan before dispatch")
            request = replace(request, preparation_report={**dict(request.preparation_report or {}), "author_draft_adoption": frozen})
        return admit_single_chapter_saga(
            self.database_url,
            request=request,
            registry=self.registry,
            permissions=principal.permissions,
        )

    def recover_admission(
        self, request: SingleChapterRequest, *, principal: Principal,
    ) -> ChapterSagaAdmission | None:
        principal.require("chapter.authority.execute", request.project_id)
        if request.actor_id != principal.principal_id:
            raise PermissionError("Chapter recovery actor must be the trusted Principal")
        return recover_single_chapter_admission(self.database_url, request=request)

    def scheduler(self, *, principal: Principal) -> ChapterAuthorityScheduler:
        if principal.principal_type.value != "worker":
            raise PermissionError(
                "Chapter scheduler requires a configured worker Principal"
            )
        return ChapterAuthorityScheduler(
            self.database_url,
            registry=self.registry,
            object_store_adapter=self._object_store_adapter,
            worker_id=principal.principal_id,
            permissions=principal.permissions,
            agent_binding_recorder=self.agent_binding_recorder,
            fault_injector=self.runtime_fault_injector,
            model_effect_adapter=self._model_port.adapter,
        )

    def admit_manuscript_revision(self, *, authority, book_run_id, chapter, expected_version,
                                 idempotency_key, reason, principal):
        from .working_revision import admit_working_revision
        return admit_working_revision(self, authority=authority, book_run_id=book_run_id,
            chapter=chapter, expected_version=expected_version, idempotency_key=idempotency_key,
            reason=reason, principal=principal)


__all__ = ["ChapterAuthorityApplication"]
