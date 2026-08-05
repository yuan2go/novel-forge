"""Application facade for PostgreSQL-only chapter commands and strong queries."""
from __future__ import annotations

from novel_forge.modules.chapter_authority.handlers import build_chapter_handler_registry
from novel_forge.modules.chapter_authority.model_effects import (
    ChapterAgentBindingRecorder,
    ExternalEffectChapterModelPort,
)
from novel_forge.modules.chapter_authority.orchestrator import (
    ChapterSagaAdmission,
    ChapterSliceResult,
    SingleChapterRequest,
    admit_single_chapter_saga,
    run_single_chapter_slice,
)
from novel_forge.modules.chapter_authority.scheduler import ChapterAuthorityScheduler
from novel_forge.modules.authority_security import Principal
from novel_forge.modules.chapter_authority.queries import ChapterAuthorityQuery
from novel_forge.modules.command_kernel.external_effect_adapters import ExternalEffectAdapter


class ChapterAuthorityApplication:
    def __init__(
        self,
        database_url: str,
        *,
        model_adapter: ExternalEffectAdapter,
        object_store_adapter: ExternalEffectAdapter,
        worker_id: str,
        allow_synchronous_fixture: bool = True,
        max_cost_per_model_call: str = "0",
        budget_caps: dict[str, str] | None = None,
        agent_binding_recorder: ChapterAgentBindingRecorder | None = None,
        agent_binding_required: bool = False,
    ) -> None:
        if not database_url or not worker_id:
            raise ValueError("PostgreSQL database and worker identity are required")
        self.database_url = database_url
        self.model_port = ExternalEffectChapterModelPort(
            database_url,
            adapter=model_adapter,
            worker_id=f"{worker_id}:model",
            max_cost_per_call=max_cost_per_model_call,
            budget_caps=budget_caps,
            agent_binding_recorder=agent_binding_recorder,
            agent_binding_required=agent_binding_required,
        )
        self.registry = build_chapter_handler_registry(self.model_port)
        self.object_store_adapter = object_store_adapter
        self.worker_id = worker_id
        self.allow_synchronous_fixture = allow_synchronous_fixture
        self.query = ChapterAuthorityQuery(database_url)

    @property
    def external_effect_adapters(self) -> dict[str, ExternalEffectAdapter]:
        return {
            self.model_port.adapter.provider: self.model_port.adapter,
            self.object_store_adapter.provider: self.object_store_adapter,
        }

    def run(self, request: SingleChapterRequest) -> ChapterSliceResult:
        if not self.allow_synchronous_fixture:
            raise RuntimeError(
                "synchronous Chapter Authority execution is disabled; use durable admission"
            )
        return run_single_chapter_slice(
            self.database_url,
            request=request,
            registry=self.registry,
            object_store_adapter=self.object_store_adapter,
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
        return admit_single_chapter_saga(
            self.database_url,
            request=request,
            registry=self.registry,
            permissions=principal.permissions,
        )

    def scheduler(self, *, principal: Principal) -> ChapterAuthorityScheduler:
        if principal.principal_type.value != "worker":
            raise PermissionError("Chapter scheduler requires a configured worker Principal")
        return ChapterAuthorityScheduler(
            self.database_url,
            registry=self.registry,
            object_store_adapter=self.object_store_adapter,
            worker_id=principal.principal_id,
            permissions=principal.permissions,
        )


__all__ = ["ChapterAuthorityApplication"]
