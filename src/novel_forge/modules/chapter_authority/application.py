"""Application facade for PostgreSQL-only chapter commands and strong queries."""
from __future__ import annotations

from novel_forge.modules.chapter_authority.handlers import build_chapter_handler_registry
from novel_forge.modules.chapter_authority.model_effects import ExternalEffectChapterModelPort
from novel_forge.modules.chapter_authority.orchestrator import (
    ChapterSliceResult,
    SingleChapterRequest,
    run_single_chapter_slice,
)
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
    ) -> None:
        if not database_url or not worker_id:
            raise ValueError("PostgreSQL database and worker identity are required")
        self.database_url = database_url
        self.model_port = ExternalEffectChapterModelPort(
            database_url,
            adapter=model_adapter,
            worker_id=f"{worker_id}:model",
        )
        self.registry = build_chapter_handler_registry(self.model_port)
        self.object_store_adapter = object_store_adapter
        self.query = ChapterAuthorityQuery(database_url)

    def run(self, request: SingleChapterRequest) -> ChapterSliceResult:
        return run_single_chapter_slice(
            self.database_url,
            request=request,
            registry=self.registry,
            object_store_adapter=self.object_store_adapter,
        )


__all__ = ["ChapterAuthorityApplication"]
