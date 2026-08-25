"""Canonical Book production dependency graph shared by API and Worker."""

from __future__ import annotations

from dataclasses import dataclass

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.book_followup_authority.application import (
    BookFollowupAuthorityApplication,
)
from novel_forge.modules.book_design_authority import StoryFormationApplication
from novel_forge.modules.book_replan import (
    BookReplanCoordinator,
    ReevaluateBookReplanCommand,
)
from novel_forge.modules.chapter_group_authority import PostgresChapterGroupAuthority
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.corrective_action import CorrectiveActionQuery
from novel_forge.modules.plan_change_authority import PostgresPlanChangeAuthority
from novel_forge.modules.production_preparation import ProductionPreparationService
from novel_forge.modules.story_planning_runtime import (
    StoryPlanningGenerationApplication,
)

from .input_resolver import BookProductionInputResolver
from .opening import (
    BookOpeningResult,
    OpenBookProductionRequest,
    PostgresBookOpeningApplication,
)
from .projection_repair import PostgresBookProjectionRepairAuthority
from .production import PostgresBookAuthority
from .queries import PostgresBookProductionQuery
from .supervisor import (
    BookProductionSupervisorTick,
    PostgresBookProductionSupervisor,
)


@dataclass(frozen=True, slots=True)
class BookProductionComposition:
    """Dependency container only; all durable state remains in PostgreSQL."""

    authority: PostgresBookAuthority
    query: PostgresBookProductionQuery
    planning: StoryPlanningGenerationApplication
    chapter_groups: PostgresChapterGroupAuthority
    production_preparation: ProductionPreparationService
    followup: BookFollowupAuthorityApplication
    plan_change: PostgresPlanChangeAuthority
    input_resolver: BookProductionInputResolver
    replan: BookReplanCoordinator
    corrective_actions: CorrectiveActionQuery
    supervisor: PostgresBookProductionSupervisor
    principal: Principal
    projection_repair: PostgresBookProjectionRepairAuthority
    opening: PostgresBookOpeningApplication | None = None
    formation: StoryFormationApplication | None = None

    def tick(self, book_run_id: str) -> BookProductionSupervisorTick:
        return self.supervisor.tick(book_run_id)

    def open_book(self, request: OpenBookProductionRequest) -> BookOpeningResult:
        if self.opening is None:
            raise KernelError(
                "BOOK_OPENING_RUNTIME_NOT_CONFIGURED",
                "Book opening is unavailable in this explicitly partial composition",
            )
        return self.opening.open(request, principal=self.principal)

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

    def reevaluate_replan(
        self,
        *,
        book_run_id: str,
        replan_id: str,
        source_recap_asset_version_id: str,
        deviation_report_asset_version_id: str,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
    ) -> dict[str, object]:
        replan = self.replan.require(replan_id)
        if str(replan["book_run_id"]) != book_run_id:
            raise KernelError(
                "BOOK_REPLAN_SCOPE_MISMATCH",
                "Replan belongs to another Book production run",
            )
        book = self.authority.require(book_run_id)
        return self.replan.reevaluate(
            ReevaluateBookReplanCommand(
                project_id=str(replan["project_id"]),
                workspace_id=str(book["workspace_id"]),
                replan_id=replan_id,
                source_recap_asset_version_id=source_recap_asset_version_id,
                deviation_report_asset_version_id=deviation_report_asset_version_id,
                idempotency_key=idempotency_key,
                trace_id=trace_id,
                correlation_id=correlation_id,
            )
        )


__all__ = ["BookProductionComposition"]
