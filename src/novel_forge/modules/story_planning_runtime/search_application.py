"""Durable divergent search over the existing Story Planning runtime."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.authority_security import Principal
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .application import StoryPlanningGenerationApplication
from .domain import (
    PlanningGenerationResult,
    PlanningGenerationStatus,
    StoryPlanningGenerationCommand,
    canonical_hash,
)
from .narrative_search import (
    NarrativeSearchCandidate,
    NarrativeSearchComparison,
    NarrativeSearchProjection,
    NarrativeSearchStatus,
    compare_narrative_futures,
)


DEFAULT_SEARCH_DIRECTIVES = (
    "maximize costly character agency while preserving future options",
    "advance promises through consequence, reversal, and differentiated rhythm",
    "hybridize world pressure and relationship change without repeating recent patterns",
)


@dataclass(frozen=True, slots=True)
class NarrativeSearchRequest:
    generation: StoryPlanningGenerationCommand
    planning_horizon: Mapping[str, Any]
    desired_transformation: Mapping[str, Any]
    hard_constraints: tuple[str, ...]
    accepted_through_chapter: int
    book_run_id: str = ""
    parent_state_asset_version_id: str = ""
    strategy_directives: tuple[str, ...] = DEFAULT_SEARCH_DIRECTIVES
    expected_active_asset_version_id: str = ""
    replacement_approved: bool = False
    replacement_decision_evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.generation.generator_operation_name == "chapter_plan.generate":
            raise ValueError(
                "Chapter planning is operational, not a divergent search level"
            )
        if not 2 <= len(self.strategy_directives) <= 5:
            raise ValueError(
                "Narrative search requires two to five strategy directives"
            )
        if len(set(self.strategy_directives)) != len(self.strategy_directives):
            raise ValueError("Narrative search strategy directives must be distinct")
        if self.accepted_through_chapter < 0:
            raise ValueError("accepted boundary cannot be negative")
        if self.accepted_through_chapter and not (
            self.book_run_id and self.parent_state_asset_version_id
        ):
            raise ValueError(
                "continuing search requires its Book Run and accepted Story State"
            )
        if self.generation.auto_approve_low_risk:
            raise ValueError("search candidates cannot auto-activate before comparison")
        if self.replacement_approved and not self.replacement_decision_evidence:
            raise ValueError("approved search replacement requires decision evidence")
        if not self.planning_horizon or not self.desired_transformation:
            raise ValueError("search horizon and desired transformation are required")
        if (
            not self.hard_constraints
            or any(not str(item).strip() for item in self.hard_constraints)
            or len(set(self.hard_constraints)) != len(self.hard_constraints)
        ):
            raise ValueError("search hard constraints must be non-empty and distinct")
        if self.generation.generator_operation_name == "chapter_group_plan.generate":
            chapter_range = self.planning_horizon.get("chapter_range")
            if (
                self.planning_horizon.get("level") != "CHAPTER_GROUP"
                or not isinstance(chapter_range, list)
                or len(chapter_range) != 2
                or any(
                    not isinstance(item, int) or isinstance(item, bool)
                    for item in chapter_range
                )
            ):
                raise ValueError(
                    "ChapterGroup search requires an exact frozen chapter range"
                )
            start, end = chapter_range
            if (
                start <= self.accepted_through_chapter
                or not 3 <= end - start + 1 <= 8
                or self.planning_horizon.get("starts_at_chapter") != start
                or self.planning_horizon.get("ends_at_chapter") != end
            ):
                raise ValueError("ChapterGroup search horizon is inconsistent")


@dataclass(frozen=True, slots=True)
class NarrativeSearchResult:
    search_id: str
    status: NarrativeSearchStatus
    selected_generation: PlanningGenerationResult
    comparison: NarrativeSearchComparison
    candidate_asset_version_ids: tuple[str, ...]
    replayed: bool


class PostgresNarrativeSearchApplication:
    """Planning-owned portfolio lifecycle; it does not activate Story truth."""

    def __init__(
        self,
        database_url: str,
        *,
        planning: StoryPlanningGenerationApplication,
    ) -> None:
        self.database_url = database_url
        self.planning = planning

    def explore(
        self,
        request: NarrativeSearchRequest,
        *,
        principal: Principal,
        activate_selected: bool = False,
    ) -> NarrativeSearchResult:
        command = request.generation
        principal.require("story_planning.authority.execute", command.project_id)
        search_key = f"{command.idempotency_key}:narrative-search"
        search_id = "narrative-search:" + canonical_hash(
            {
                "project_id": command.project_id,
                "book_id": command.book_id,
                "stable_idempotency_key": search_key,
            }
        ).removeprefix("sha256:")
        parent_hash = self._parent_state_hash(
            command.project_id, request.parent_state_asset_version_id
        )
        input_hash = canonical_hash(
            {
                "generator_operation_name": command.generator_operation_name,
                "planning_scope": command.planning_scope.value,
                "logical_key": command.logical_key,
                "parent_version_id": command.parent_version_id,
                "input_versions": dict(command.input_versions),
                "arc_scope": list(command.arc_scope_volume_plan_version_ids),
                "related_arcs": list(command.related_arc_plan_version_ids),
                "dependent_arcs": list(command.dependent_arc_plan_version_ids),
                "change_evidence": list(command.change_evidence_version_ids),
                "governance_actions": list(command.governance_action_version_ids),
                "accepted_through_chapter": request.accepted_through_chapter,
                "book_run_id": request.book_run_id,
                "parent_state_asset_version_id": request.parent_state_asset_version_id,
                "parent_state_content_hash": parent_hash,
                "planning_horizon": dict(request.planning_horizon),
                "desired_transformation": dict(request.desired_transformation),
                "hard_constraints": list(request.hard_constraints),
                "strategy_directives": list(request.strategy_directives),
                "expected_active_asset_version_id": (
                    request.expected_active_asset_version_id
                ),
                "replacement_approved": request.replacement_approved,
                "replacement_decision_evidence": dict(
                    request.replacement_decision_evidence
                ),
            }
        )
        replayed = self._open_search(
            search_id=search_id,
            request=request,
            input_hash=input_hash,
            parent_hash=parent_hash,
            stable_key=search_key,
        )
        generations: dict[str, PlanningGenerationResult] = {}
        for ordinal, directive in enumerate(request.strategy_directives, start=1):
            branch_key = f"future-{ordinal}"
            existing = self._candidate_for_branch(search_id, branch_key)
            if existing:
                generation = self.planning.require_generation(
                    str(existing["generation_operation_id"])
                )
                result = PlanningGenerationResult(
                    generation_operation_id=str(generation["operation_id"]),
                    candidate_asset_version_id=str(
                        generation["candidate_asset_version_id"]
                    ),
                    status=PlanningGenerationStatus(str(generation["status"])),
                    story_design_state=self.planning.story_design.require(
                        project_id=command.project_id,
                        asset_version_id=str(generation["candidate_asset_version_id"]),
                    ),
                    replayed=True,
                )
            else:
                result = self.planning.generate(
                    replace(
                        command,
                        idempotency_key=f"{search_key}:{branch_key}",
                        narrative_search_id=search_id,
                        narrative_search_branch_key=branch_key,
                        narrative_search_parent_state_asset_version_id=(
                            request.parent_state_asset_version_id
                        ),
                        narrative_search_accepted_through_chapter=(
                            request.accepted_through_chapter
                        ),
                        narrative_search_strategy_directive=directive,
                        narrative_search_planning_horizon=(request.planning_horizon),
                        narrative_search_desired_transformation=(
                            request.desired_transformation
                        ),
                        narrative_search_hard_constraints=(request.hard_constraints),
                        auto_approve_low_risk=False,
                    ),
                    principal=principal,
                )
                if result.status is not PlanningGenerationStatus.APPROVAL_PENDING:
                    raise KernelError(
                        "NARRATIVE_SEARCH_CANDIDATE_NOT_QUALIFIED",
                        "search branch did not reach qualified approval-pending state",
                    )
                self._register_candidate(search_id, branch_key, result)
            generations[result.candidate_asset_version_id] = result
        candidates = self._load_candidates(search_id)
        if len(candidates) != len(request.strategy_directives):
            raise KernelError(
                "NARRATIVE_SEARCH_CANDIDATE_SET_INCOMPLETE",
                "not every frozen strategy produced a qualified future",
            )
        comparison, decision_replayed = self._select(search_id, candidates)
        selected = generations.get(comparison.selected_candidate_asset_version_id)
        if selected is None:
            generation_id = next(
                item.generation_operation_id
                for item in candidates
                if item.candidate_asset_version_id
                == comparison.selected_candidate_asset_version_id
            )
            generation = self.planning.require_generation(generation_id)
            selected = PlanningGenerationResult(
                generation_operation_id=generation_id,
                candidate_asset_version_id=comparison.selected_candidate_asset_version_id,
                status=PlanningGenerationStatus(str(generation["status"])),
                story_design_state=self.planning.story_design.require(
                    project_id=command.project_id,
                    asset_version_id=comparison.selected_candidate_asset_version_id,
                ),
                replayed=True,
            )
        if activate_selected:
            state = selected.story_design_state
            if state["approval"] != "APPROVED" and state["lifecycle"] != "ACTIVE":
                self.planning.approve_candidate(
                    selected.candidate_asset_version_id,
                    principal=principal,
                    idempotency_key=f"{search_key}:approve-selected",
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                )
            activation = self.planning.activate_candidate(
                selected.candidate_asset_version_id,
                principal=principal,
                idempotency_key=f"{search_key}:activate-selected",
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
                expected_active_asset_version_id=(
                    request.expected_active_asset_version_id
                ),
                replacement_approved=request.replacement_approved,
                decision_evidence=dict(request.replacement_decision_evidence),
            )
            selected = replace(
                selected,
                status=PlanningGenerationStatus.ACTIVE,
                story_design_state=dict(activation["story_design"]),
                planning_binding=dict(activation["planning_binding"]),
            )
        return NarrativeSearchResult(
            search_id=search_id,
            status=(
                NarrativeSearchStatus.ACTIVATED
                if activate_selected
                else NarrativeSearchStatus.SELECTED
            ),
            selected_generation=selected,
            comparison=comparison,
            candidate_asset_version_ids=tuple(
                item.candidate_asset_version_id for item in candidates
            ),
            replayed=replayed or decision_replayed,
        )

    def _parent_state_hash(self, project_id: str, asset_version_id: str) -> str:
        if not asset_version_id:
            return ""
        asset = self.planning._require_asset(  # same Planning application boundary
            project_id=project_id, asset_version_id=asset_version_id
        )
        return str(asset["content_hash"])

    def _open_search(
        self,
        *,
        search_id: str,
        request: NarrativeSearchRequest,
        input_hash: str,
        parent_hash: str,
        stable_key: str,
    ) -> bool:
        command = request.generation
        self._require_current_accepted_boundary(request)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_story_narrative_search(
                    search_id, project_id, workspace_id, book_id, book_run_id,
                    generator_operation_name, planning_scope, logical_key,
                    parent_version_id, parent_state_asset_version_id,
                    parent_state_content_hash, accepted_through_chapter,
                    planning_horizon, desired_transformation, hard_constraints,
                    input_snapshot_hash, strategy_directives, candidate_target,
                    status, stable_idempotency_key
                ) VALUES (
                    %s, %s, %s, %s, NULLIF(%s, ''), %s, %s, %s,
                    NULLIF(%s, ''), NULLIF(%s, ''), NULLIF(%s, ''),
                    %s, %s, %s, %s, %s, %s, %s, 'GENERATING', %s
                ) ON CONFLICT (project_id, book_id, stable_idempotency_key) DO NOTHING
                RETURNING search_id
                """,
                [
                    search_id,
                    command.project_id,
                    command.workspace_id,
                    command.book_id,
                    request.book_run_id,
                    command.generator_operation_name,
                    command.planning_scope.value,
                    command.logical_key,
                    command.parent_version_id,
                    request.parent_state_asset_version_id,
                    parent_hash,
                    request.accepted_through_chapter,
                    Jsonb(dict(request.planning_horizon)),
                    Jsonb(dict(request.desired_transformation)),
                    Jsonb(list(request.hard_constraints)),
                    input_hash,
                    Jsonb(list(request.strategy_directives)),
                    len(request.strategy_directives),
                    stable_key,
                ],
            )
            inserted = uow.cursor.fetchone() is not None
            uow.cursor.execute(
                """
                SELECT search_id, input_snapshot_hash
                FROM authority_story_narrative_search
                WHERE project_id=%s AND book_id=%s AND stable_idempotency_key=%s
                """,
                [command.project_id, command.book_id, stable_key],
            )
            row = uow.cursor.fetchone()
            if row is None or str(row[0]) != search_id or str(row[1]) != input_hash:
                raise KernelError(
                    "NARRATIVE_SEARCH_IDEMPOTENCY_CONFLICT",
                    "search key was reused with a different frozen future boundary",
                )
            uow.commit()
        return not inserted

    def _require_current_accepted_boundary(
        self, request: NarrativeSearchRequest
    ) -> None:
        if request.accepted_through_chapter == 0:
            return
        command = request.generation
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT accepted_through_chapter, active_story_state_version_id
                FROM authority_book_production
                WHERE book_run_id=%s AND project_id=%s AND book_id=%s
                """,
                [request.book_run_id, command.project_id, command.book_id],
            )
            row = uow.cursor.fetchone()
        if (
            row is None
            or int(row[0]) != request.accepted_through_chapter
            or str(row[1] or "") != request.parent_state_asset_version_id
        ):
            raise KernelError(
                "NARRATIVE_SEARCH_ACCEPTED_BOUNDARY_STALE",
                "Narrative Search must freeze the current Book Run accepted boundary",
            )

    def _candidate_for_branch(
        self, search_id: str, branch_key: str
    ) -> dict[str, Any] | None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT candidate_asset_version_id, generation_operation_id
                FROM authority_story_narrative_search_candidate
                WHERE search_id=%s AND branch_key=%s
                """,
                [search_id, branch_key],
            )
            row = uow.cursor.fetchone()
        return (
            None
            if row is None
            else {
                "candidate_asset_version_id": str(row[0]),
                "generation_operation_id": str(row[1]),
            }
        )

    def _register_candidate(
        self, search_id: str, branch_key: str, result: PlanningGenerationResult
    ) -> None:
        generation = self.planning.require_candidate(result.candidate_asset_version_id)
        asset = self.planning._require_asset(
            project_id=str(generation["project_id"]),
            asset_version_id=result.candidate_asset_version_id,
        )
        projection = NarrativeSearchProjection.from_mapping(
            asset["content"].get("narrative_search_projection")
        )
        qualification = self.planning._require_narrative_qualification_summary(
            operation_id=result.generation_operation_id,
            candidate_asset_version_id=result.candidate_asset_version_id,
            project_id=str(generation["project_id"]),
            book_id=str(generation["book_id"]),
            generator_operation_name=str(generation["generator_operation_name"]),
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_story_narrative_search_candidate(
                    membership_id, search_id, branch_key,
                    candidate_asset_version_id, generation_operation_id,
                    projection, projection_hash, strategy_fingerprint,
                    comparison_score, qualification_hash, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'ELIGIBLE')
                ON CONFLICT (search_id, branch_key) DO NOTHING
                """,
                [
                    f"narrative-search-candidate:{search_id}:{branch_key}",
                    search_id,
                    branch_key,
                    result.candidate_asset_version_id,
                    result.generation_operation_id,
                    Jsonb(projection.to_dict()),
                    canonical_hash(projection.to_dict()),
                    projection.strategy_fingerprint,
                    projection.comparison_score,
                    qualification["narrative_qualification_hash"],
                ],
            )
            uow.commit()

    def _load_candidates(self, search_id: str) -> tuple[NarrativeSearchCandidate, ...]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT candidate_asset_version_id, generation_operation_id,
                       branch_key, projection, qualification_hash
                FROM authority_story_narrative_search_candidate
                WHERE search_id=%s ORDER BY branch_key
                """,
                [search_id],
            )
            rows = uow.cursor.fetchall()
        return tuple(
            NarrativeSearchCandidate(
                candidate_asset_version_id=str(row[0]),
                generation_operation_id=str(row[1]),
                branch_key=str(row[2]),
                projection=NarrativeSearchProjection.from_mapping(row[3]),
                qualification_hash=str(row[4]),
            )
            for row in rows
        )

    def _select(
        self, search_id: str, candidates: Sequence[NarrativeSearchCandidate]
    ) -> tuple[NarrativeSearchComparison, bool]:
        comparison = compare_narrative_futures(candidates)
        evidence = comparison.to_dict()
        candidate_set_hash = canonical_hash(
            [
                {
                    "candidate_asset_version_id": item.candidate_asset_version_id,
                    "projection": item.projection.to_dict(),
                    "qualification_hash": item.qualification_hash,
                }
                for item in candidates
            ]
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_story_narrative_search_decision(
                    decision_id, search_id, selected_candidate_asset_version_id,
                    candidate_set_hash, comparison, comparison_hash, selection_reason
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (search_id) DO NOTHING RETURNING decision_id
                """,
                [
                    f"narrative-search-decision:{search_id}",
                    search_id,
                    comparison.selected_candidate_asset_version_id,
                    candidate_set_hash,
                    Jsonb(evidence),
                    canonical_hash(evidence),
                    Jsonb(list(comparison.selection_reasons)),
                ],
            )
            inserted = uow.cursor.fetchone() is not None
            uow.cursor.execute(
                """
                SELECT selected_candidate_asset_version_id, candidate_set_hash, comparison
                FROM authority_story_narrative_search_decision WHERE search_id=%s
                """,
                [search_id],
            )
            stored = uow.cursor.fetchone()
            if (
                stored is None
                or str(stored[0]) != comparison.selected_candidate_asset_version_id
                or str(stored[1]) != candidate_set_hash
                or dict(stored[2]) != evidence
            ):
                raise KernelError(
                    "NARRATIVE_SEARCH_DECISION_DRIFT",
                    "replayed search differs from its immutable selection decision",
                )
            uow.cursor.execute(
                """
                UPDATE authority_story_narrative_search_candidate
                SET status=CASE WHEN candidate_asset_version_id=%s
                                THEN 'SELECTED' ELSE 'REJECTED' END
                WHERE search_id=%s
                """,
                [comparison.selected_candidate_asset_version_id, search_id],
            )
            uow.cursor.execute(
                """
                UPDATE authority_story_narrative_search
                SET status='SELECTED', selected_candidate_asset_version_id=%s,
                    version=version+1, updated_at=NOW()
                WHERE search_id=%s AND status NOT IN ('SELECTED', 'ACTIVATED')
                """,
                [comparison.selected_candidate_asset_version_id, search_id],
            )
            uow.commit()
        return comparison, not inserted


__all__ = [
    "DEFAULT_SEARCH_DIRECTIVES",
    "NarrativeSearchRequest",
    "NarrativeSearchResult",
    "PostgresNarrativeSearchApplication",
]
