"""Book opening coordinator over existing design, planning, and input Authorities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.book_design_authority import (
    FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
    BookDesignPayload,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime import (
    GENERATOR_INPUT_ROLES,
    NarrativeSearchRequest,
    PostgresNarrativeSearchApplication,
    StoryPlanningGenerationCommand,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.foundation_repositories import (
    require_current_foundation_set,
)

from .input_resolver import (
    BookProductionInputResolver,
    BookProductionInputSnapshot,
    ResolveBookProductionInputCommand,
)


_RESOLVER_ROLE_BY_PLANNING_ROLE = {
    "production_profile": "production_profile_version",
    "reader_segment": "reader_segment_version",
    "reader_contract": "reader_contract_version",
    "platform_profile": "platform_profile_version",
    "character_state": "character_state_version",
    "foreshadowing_state": "foreshadowing_state_version",
    "quality_trend": "quality_trend_version",
    "reward_ledger": "reward_ledger_version",
    "promise_ledger": "promise_ledger_version",
}
_OPENING_INPUT_ROLES = frozenset(
    role
    for generator in (
        "book_plan.generate",
        "volume_plan.generate",
        "arc_plan.generate",
    )
    for role in GENERATOR_INPUT_ROLES[generator]
    if role not in {"book_plan", "volume_plan"}
)


@dataclass(frozen=True, slots=True)
class OpenBookProductionRequest:
    project_id: str
    workspace_id: str
    book_id: str
    actor_id: str
    expected_book_version: int
    production_profile: str
    planning_input_versions: Mapping[str, str]
    arc_logical_keys: tuple[str, ...]
    idempotency_key: str
    trace_id: str
    correlation_id: str
    initial_story_state_version: str = ""
    initial_canon_snapshot_version: str = ""

    def __post_init__(self) -> None:
        identities = (
            self.project_id,
            self.workspace_id,
            self.book_id,
            self.actor_id,
            self.production_profile,
            self.idempotency_key,
            self.trace_id,
            self.correlation_id,
        )
        if (
            any(not item.strip() for item in identities)
            or self.expected_book_version <= 0
        ):
            raise ValueError("Book opening request is incomplete")
        if not self.arc_logical_keys or len(set(self.arc_logical_keys)) != len(
            self.arc_logical_keys
        ):
            raise ValueError("Book opening requires a non-empty unique Arc portfolio")
        if (
            not self.initial_story_state_version
            or not self.initial_canon_snapshot_version
        ):
            raise ValueError(
                "Book opening requires the initial accepted Story State and Canon boundary"
            )


@dataclass(frozen=True, slots=True)
class BookOpeningResult:
    book_design_version: str
    book_plan_version: str
    volume_plan_version: str
    arc_plan_versions: tuple[str, ...]
    input_snapshot: BookProductionInputSnapshot
    search_ids: tuple[str, ...]


class PostgresBookOpeningApplication:
    """Coordinates existing Authorities; it owns no new truth or execution state."""

    def __init__(
        self,
        database_url: str,
        *,
        narrative_search: PostgresNarrativeSearchApplication,
        input_resolver: BookProductionInputResolver,
    ) -> None:
        if not database_url:
            raise ValueError("Book opening requires PostgreSQL")
        self.database_url = database_url
        self.narrative_search = narrative_search
        self.input_resolver = input_resolver

    def open(
        self, request: OpenBookProductionRequest, *, principal: Principal
    ) -> BookOpeningResult:
        principal.require("book.authority.execute", request.project_id)
        principal.require("story_planning.authority.execute", request.project_id)
        design_version = self._require_qualified_foundation(request)
        generic = dict(request.planning_input_versions)
        if (
            set(generic) != _OPENING_INPUT_ROLES
            or generic.get("book_design") != design_version
        ):
            raise KernelError(
                "BOOK_OPENING_INPUTS_INVALID",
                "opening inputs must exactly match the Book planning Authority roles and active Foundation",
            )
        accepted_state = request.initial_story_state_version
        search_ids: list[str] = []
        book_search = self._search(
            request=request,
            principal=principal,
            generator="book_plan.generate",
            logical_key="book:main",
            input_versions={
                role: generic[role]
                for role in GENERATOR_INPUT_ROLES["book_plan.generate"]
            },
            parent_version_id="",
            accepted_state=accepted_state,
            horizon={"level": "BOOK", "stability": "HIGH", "reach": "DISTANT"},
            transformation={
                "foundation_version": design_version,
                "goal": "establish a sustainable Book narrative architecture",
            },
        )
        search_ids.append(book_search.search_id)
        book_plan = book_search.selected_generation.candidate_asset_version_id
        volume_inputs = self._stage_inputs(
            generic, "volume_plan.generate", book_plan=book_plan
        )
        volume_search = self._search(
            request=request,
            principal=principal,
            generator="volume_plan.generate",
            logical_key="volume:1",
            input_versions=volume_inputs,
            parent_version_id=book_plan,
            accepted_state=accepted_state,
            horizon={"level": "VOLUME", "stability": "MEDIUM_HIGH", "ordinal": 1},
            transformation={
                "goal": "create the first irreversible stage transformation"
            },
        )
        search_ids.append(volume_search.search_id)
        volume_plan = volume_search.selected_generation.candidate_asset_version_id
        arc_versions: list[str] = []
        for arc_key in request.arc_logical_keys:
            arc_inputs = self._stage_inputs(
                generic,
                "arc_plan.generate",
                book_plan=book_plan,
                volume_plan=volume_plan,
            )
            arc_search = self._search(
                request=request,
                principal=principal,
                generator="arc_plan.generate",
                logical_key=arc_key,
                input_versions=arc_inputs,
                parent_version_id="",
                accepted_state=accepted_state,
                horizon={"level": "ARC", "stability": "MEDIUM", "volume": 1},
                transformation={
                    "goal": "produce a causal transformation with closure criteria",
                    "arc_key": arc_key,
                },
            )
            search_ids.append(arc_search.search_id)
            arc_versions.append(
                arc_search.selected_generation.candidate_asset_version_id
            )
        overrides = tuple(
            (
                _RESOLVER_ROLE_BY_PLANNING_ROLE[role],
                version_id,
            )
            for role, version_id in generic.items()
            if role in _RESOLVER_ROLE_BY_PLANNING_ROLE
        )
        overrides += (
            ("initial_story_state_version", request.initial_story_state_version),
            ("initial_canon_snapshot_version", request.initial_canon_snapshot_version),
        )
        snapshot = self.input_resolver.resolve(
            ResolveBookProductionInputCommand(
                project_id=request.project_id,
                workspace_id=request.workspace_id,
                book_id=request.book_id,
                production_profile=request.production_profile,
                expected_book_version=request.expected_book_version,
                actor_id=request.actor_id,
                idempotency_key=f"{request.idempotency_key}:production-input",
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
                role_asset_version_overrides=overrides,
            ),
            principal=principal,
        )
        return BookOpeningResult(
            book_design_version=design_version,
            book_plan_version=book_plan,
            volume_plan_version=volume_plan,
            arc_plan_versions=tuple(arc_versions),
            input_snapshot=snapshot,
            search_ids=tuple(search_ids),
        )

    def _search(
        self,
        *,
        request: OpenBookProductionRequest,
        principal: Principal,
        generator: str,
        logical_key: str,
        input_versions: Mapping[str, str],
        parent_version_id: str,
        accepted_state: str,
        horizon: Mapping[str, object],
        transformation: Mapping[str, object],
    ):
        generation = StoryPlanningGenerationCommand(
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            book_id=request.book_id,
            actor_id=request.actor_id,
            generator_operation_name=generator,
            logical_key=logical_key,
            input_versions=input_versions,
            parent_version_id=parent_version_id,
            idempotency_key=f"{request.idempotency_key}:{generator}:{logical_key}",
            trace_id=request.trace_id,
            correlation_id=request.correlation_id,
        )
        return self.narrative_search.explore(
            NarrativeSearchRequest(
                generation=generation,
                planning_horizon=horizon,
                desired_transformation=transformation,
                hard_constraints=(
                    "preserve the approved Creative Foundation",
                    "protect reader promise and ending direction",
                    "do not convert future intent into accepted reality",
                ),
                accepted_through_chapter=0,
                parent_state_asset_version_id=accepted_state,
            ),
            principal=principal,
            activate_selected=True,
        )

    @staticmethod
    def _stage_inputs(
        generic: Mapping[str, str],
        generator: str,
        *,
        book_plan: str,
        volume_plan: str = "",
    ) -> dict[str, str]:
        values = dict(generic)
        values["book_plan"] = book_plan
        if volume_plan:
            values["volume_plan"] = volume_plan
        return {role: values[role] for role in GENERATOR_INPUT_ROLES[generator]}

    def _require_qualified_foundation(self, request: OpenBookProductionRequest) -> str:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT book.current_book_design_asset_version_id,
                       version.schema_version, version.lifecycle,
                       version.eligibility, version.governance,
                       version.content_hash, version.content
                FROM authority_book AS book
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=book.current_book_design_asset_version_id
                WHERE book.project_id=%s AND book.workspace_id=%s AND book.book_id=%s
                  AND book.version=%s AND book.status='DESIGN_ACTIVE'
                """,
                [
                    request.project_id,
                    request.workspace_id,
                    request.book_id,
                    request.expected_book_version,
                ],
            )
            row = uow.cursor.fetchone()
            if row is None or tuple(str(item) for item in row[1:5]) != (
                FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
                "ACTIVE",
                "ELIGIBLE",
                "CLEAR",
            ):
                raise KernelError(
                    "BOOK_OPENING_FOUNDATION_REQUIRED",
                    "Book opening requires the exact active and qualified Foundation synthesis",
                )
            foundation = require_current_foundation_set(
                uow.cursor,
                project_id=request.project_id,
                book_id=request.book_id,
            )
            design = BookDesignPayload.from_mapping(dict(row[6]))
            if design.foundation_set != foundation:
                raise KernelError(
                    "BOOK_OPENING_FOUNDATION_DRIFT",
                    "BookDesign does not bind the current qualified Foundation Set",
                )
            uow.cursor.execute(
                """
                SELECT formation_run_id
                FROM authority_story_formation_run
                WHERE project_id=%s AND workspace_id=%s AND book_id=%s
                  AND lifecycle='READY' AND current_stage='COMPLETE'
                  AND foundation_set_digest=%s
                  AND book_design_asset_version_id=%s
                  AND book_design_content_hash=%s
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                [
                    request.project_id,
                    request.workspace_id,
                    request.book_id,
                    foundation.set_digest,
                    str(row[0]),
                    str(row[5]),
                ],
            )
            formation = uow.cursor.fetchone()
        if formation is None:
            raise KernelError(
                "BOOK_OPENING_FORMATION_NOT_READY",
                "Book opening requires a READY durable Story Formation bound to the active synthesis",
            )
        return str(row[0])


__all__ = [
    "BookOpeningResult",
    "OpenBookProductionRequest",
    "PostgresBookOpeningApplication",
]
