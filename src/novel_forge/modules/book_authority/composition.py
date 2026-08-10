"""Canonical Book production dependency graph shared by API and Worker."""

from __future__ import annotations

from dataclasses import dataclass

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.book_followup_authority.application import (
    BookFollowupAuthorityApplication,
)
from novel_forge.modules.book_replan import BookReplanCoordinator
from novel_forge.modules.chapter_group_authority import PostgresChapterGroupAuthority
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.plan_change_authority import PostgresPlanChangeAuthority
from novel_forge.modules.production_preparation import ProductionPreparationService
from novel_forge.modules.story_planning_runtime import (
    StoryPlanningGenerationApplication,
)

from .governed_scheduler import BookAuthorityTick
from .input_resolver import BookProductionInputResolver
from .production import PostgresBookAuthority
from .supervisor import (
    BookProductionSupervisorTick,
    PostgresBookProductionSupervisor,
)


@dataclass(frozen=True, slots=True)
class BookProductionComposition:
    """Dependency container only; all durable state remains in PostgreSQL."""

    authority: PostgresBookAuthority
    planning: StoryPlanningGenerationApplication
    chapter_groups: PostgresChapterGroupAuthority
    production_preparation: ProductionPreparationService
    followup: BookFollowupAuthorityApplication
    plan_change: PostgresPlanChangeAuthority
    input_resolver: BookProductionInputResolver
    replan: BookReplanCoordinator
    supervisor: PostgresBookProductionSupervisor
    principal: Principal

    def tick(
        self, book_run_id: str
    ) -> BookProductionSupervisorTick | BookAuthorityTick:
        book = self.authority.require(book_run_id)
        if book["input_mode"] == "RESOLVED_AUTHORITY_INPUT":
            return self.supervisor.tick(book_run_id)
        return self.supervisor.scheduler.tick(book_run_id)

    def approve_replan(
        self,
        *,
        book_run_id: str,
        replan_id: str,
        authority_type: str,
        authority_version: str,
        evidence: dict[str, object],
    ) -> dict[str, object]:
        replan = self.replan.require(replan_id)
        if str(replan["book_run_id"]) != book_run_id:
            raise KernelError(
                "BOOK_REPLAN_SCOPE_MISMATCH",
                "Replan belongs to another Book production run",
            )
        self.principal.require(
            "book.authority.approve_replan", str(replan["project_id"])
        )
        return self.replan.approve(
            replan_id,
            authority_type=authority_type,
            authority_version=authority_version,
            evidence=evidence,
        )


__all__ = ["BookProductionComposition"]
