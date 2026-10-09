from __future__ import annotations

from novel_forge.modules.story_design_authority.qualification import (
    qualification_profiles_for_asset,
)

from dataclasses import dataclass, field, replace
from collections.abc import Callable
from typing import Any, Mapping, Protocol, Sequence

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
    compare_narrative_futures, select_available_qualified_future,
    validate_search_selection_policy,
)


DEFAULT_SEARCH_DIRECTIVES = (
    "maximize costly character agency while preserving future options",
    "advance promises through consequence, reversal, and differentiated rhythm",
    "hybridize world pressure and relationship change without repeating recent patterns",
)

NARRATIVE_SEARCH_BRANCH_EVIDENCE_VERSION = 1
NARRATIVE_SEARCH_BRANCH_EVIDENCE_CONTRACT_VERSION = (
    "narrative-search-branch-evidence.v1"
)
NARRATIVE_SEARCH_BRANCH_RECONCILIATION_CONTRACT_VERSION = (
    "narrative-search-branch-reconciliation.v1"
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
        if "selection_policy" in self.desired_transformation:
            validate_search_selection_policy(
                self.desired_transformation["selection_policy"]
            )
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
                or start <= 0
                or end < start
                or self.planning_horizon.get("starts_at_chapter") != start
                or self.planning_horizon.get("ends_at_chapter") != end
            ):
                raise ValueError("ChapterGroup search horizon is inconsistent")
        if self.generation.generator_operation_name == "volume_plan.generate":
            chapter_range = self.planning_horizon.get("chapter_range")
            if chapter_range is not None and (
                self.planning_horizon.get("level") != "VOLUME"
                or not isinstance(chapter_range, list)
                or len(chapter_range) != 2
                or any(
                    not isinstance(item, int) or isinstance(item, bool)
                    for item in chapter_range
                )
            ):
                raise ValueError("Volume search requires an exact frozen chapter range")
            if chapter_range is not None:
                start, end = chapter_range
                if (
                    start <= 0
                    or end < start
                    or self.accepted_through_chapter != 0
                    or self.planning_horizon.get("starts_at_chapter") != start
                    or self.planning_horizon.get("ends_at_chapter") != end
                ):
                    raise ValueError("Volume search horizon is inconsistent")
        if self.generation.generator_operation_name == "book_plan.generate":
            target_chapters = self.planning_horizon.get("target_chapters")
            if target_chapters is not None and (
                self.planning_horizon.get("level") != "BOOK"
                or not isinstance(target_chapters, int)
                or isinstance(target_chapters, bool)
                or target_chapters <= 0
            ):
                raise ValueError("Book search frozen chapter target is invalid")


@dataclass(frozen=True, slots=True)
class NarrativeSearchResult:
    search_id: str
    status: NarrativeSearchStatus
    selected_generation: PlanningGenerationResult
    comparison: NarrativeSearchComparison
    candidate_asset_version_ids: tuple[str, ...]
    replayed: bool


@dataclass(frozen=True, slots=True)
class NarrativeSearchBranchEvidence:
    membership_id: str
    search_id: str
    branch_key: str
    candidate_asset_version_id: str
    generation_operation_id: str
    generation_input_snapshot_hash: str
    candidate_content_hash: str
    projection_hash: str
    strategy_fingerprint: str
    qualification_hash: str
    evidence_version: int
    evidence_hash: str
    replayed: bool

    @property
    def evidence_id(self) -> str:
        return self.membership_id

    @property
    def evidence_type(self) -> str:
        return "NARRATIVE_SEARCH_BRANCH"


@dataclass(frozen=True, slots=True)
class NarrativeSearchBranchReconciliationEvidence:
    reconciliation_evidence_id: str
    membership_id: str
    search_id: str
    branch_key: str
    candidate_asset_version_id: str
    generation_operation_id: str
    source_branch_evidence_contract_version: str
    opening_run_id: str
    opening_execution_id: str
    execution_generation: int
    generation_input_snapshot_hash: str
    candidate_content_hash: str
    projection_hash: str
    strategy_fingerprint: str
    qualification_hash: str
    qualification_receipt_set_hash: str
    reconciled_branch_evidence_hash: str
    reconciliation_contract_version: str
    evidence_version: int
    evidence_hash: str
    replayed: bool

    @property
    def evidence_id(self) -> str:
        return self.reconciliation_evidence_id

    @property
    def evidence_type(self) -> str:
        return "NARRATIVE_SEARCH_BRANCH_RECONCILIATION"


@dataclass(frozen=True, slots=True)
class NarrativeSearchQualifiedBranch:
    branch_key: str
    result: PlanningGenerationResult
    evidence_type: str
    evidence_id: str
    evidence_version: int
    evidence_hash: str


class NarrativeSearchQualifiedBranchCommitter(Protocol):
    def __call__(
        self,
        *,
        search_id: str,
        branch_key: str,
        result: PlanningGenerationResult,
    ) -> (
        NarrativeSearchBranchEvidence | NarrativeSearchBranchReconciliationEvidence
    ): ...


class PostgresNarrativeSearchApplication:
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
        execution_probe: Callable[[], object] | None = None,
        qualified_branch_committer: NarrativeSearchQualifiedBranchCommitter
        | None = None,
    ) -> NarrativeSearchResult:
        command = request.generation
        principal.require("story_planning.authority.execute", command.project_id)
        self._probe(execution_probe)
        search_key, search_id, input_hash, parent_hash = self._search_identity(request)
        replayed = self._open_search(
            search_id=search_id,
            request=request,
            input_hash=input_hash,
            parent_hash=parent_hash,
            stable_key=search_key,
        )
        selection_policy = self._available_selection_policy(command.project_id)
        generations: dict[str, PlanningGenerationResult] = {}
        reconciled_branch_seen = False
        for ordinal, directive in enumerate(request.strategy_directives, start=1):
            self._probe(execution_probe)
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
                branch_command = replace(
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
                    # INVARIANT: Keep the exact outer Authority fence explicit at the
                    # branch boundary.  ``replace`` currently preserves it,
                    # but naming it here makes every future-N command's
                    # persisted lineage independent of dataclass defaults.
                    opening_execution_binding=command.opening_execution_binding,
                    auto_approve_low_risk=False,
                )
                frozen_command = self.planning.find_frozen_generation_command(
                    project_id=command.project_id,
                    idempotency_key=branch_command.idempotency_key,
                )
                if frozen_command is not None:
                    expected_frozen_semantics = replace(
                        branch_command,
                        opening_execution_binding=(
                            frozen_command.opening_execution_binding
                        ),
                    )
                    if frozen_command != expected_frozen_semantics:
                        raise KernelError(
                            "NARRATIVE_SEARCH_BRANCH_FROZEN_COMMAND_DRIFT",
                            "persisted future branch differs from the current Search semantics",
                        )
                    branch_command = frozen_command
                result = self.planning.generate(
                    branch_command,
                    principal=principal,
                    execution_probe=execution_probe,
                )
                self._probe(execution_probe)
                if result.status is not PlanningGenerationStatus.APPROVAL_PENDING:
                    raise KernelError(
                        "NARRATIVE_SEARCH_CANDIDATE_NOT_QUALIFIED",
                        "search branch did not reach qualified approval-pending state",
                    )
            if qualified_branch_committer is None:
                branch_evidence = self._register_candidate(
                    search_id, branch_key, result
                )
            else:
                branch_evidence = qualified_branch_committer(
                    search_id=search_id,
                    branch_key=branch_key,
                    result=result,
                )
            expected_membership_id = (
                f"narrative-search-candidate:{search_id}:{branch_key}"
            )
            if (
                branch_evidence.membership_id != expected_membership_id
                or branch_evidence.search_id != search_id
                or branch_evidence.branch_key != branch_key
                or branch_evidence.candidate_asset_version_id
                != result.candidate_asset_version_id
                or branch_evidence.generation_operation_id
                != result.generation_operation_id
                or branch_evidence.evidence_version
                != NARRATIVE_SEARCH_BRANCH_EVIDENCE_VERSION
                or not branch_evidence.evidence_hash.startswith("sha256:")
            ):
                raise KernelError(
                    "NARRATIVE_SEARCH_BRANCH_COMMIT_INVALID",
                    "qualified branch committer returned evidence for another Search branch",
                )
            reconciled_branch_seen = reconciled_branch_seen or (
                branch_evidence.evidence_type
                == "NARRATIVE_SEARCH_BRANCH_RECONCILIATION"
            )
            generations[result.candidate_asset_version_id] = result
            if selection_policy:
                break
        if reconciled_branch_seen:
            opening_binding = dict(command.opening_execution_binding or {})
            opening_run_id = str(opening_binding.get("opening_run_id") or "")
            if not opening_run_id:
                raise KernelError(
                    "NARRATIVE_SEARCH_BRANCH_RECONCILIATION_REQUIRED",
                    "reconciled branches require a Book Opening checkpoint owner",
                )
            self._require_reconciled_branch_outer_checkpoints(
                search_id,
                opening_run_id=opening_run_id,
            )
        candidates = self._load_candidates(
            search_id,
            allow_reconciled_branches=reconciled_branch_seen,
        )
        if len(candidates) != len(request.strategy_directives) and not selection_policy:
            raise KernelError(
                "NARRATIVE_SEARCH_CANDIDATE_SET_INCOMPLETE",
                "not every frozen strategy produced a qualified future",
            )
        self._probe(execution_probe)
        comparison, decision_replayed = self._select(
            search_id,
            candidates,
            allow_reconciled_branches=reconciled_branch_seen,
            available_selection_evidence=({**selection_policy,"comparison_status":"INCOMPLETE",
                "author_decision":"NOT_RECORDED", "expected_branch_keys":[f"future-{index}" for index in range(1,len(request.strategy_directives)+1)]}
                if selection_policy and len(candidates) < len(request.strategy_directives) else None),
        )
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
            self._probe(execution_probe)
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

    def _available_selection_policy(self, project_id):
        from novel_forge.storage.versioned_policy_repository import policy_hash
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute("""SELECT version.content FROM authority_runtime_policy_selection selection
                JOIN authority_runtime_policy_version version USING(owner,project_id,policy_version)
                WHERE selection.owner='BOOK_CONTROL' AND selection.project_id=%s""",[project_id])
            row = uow.cursor.fetchone()
        if not row or row[0].get("planning_selection_mode") != "AVAILABLE_QUALIFIED":
            return None
        from novel_forge.modules.book_authority.control_policy import ControlPolicy
        ControlPolicy(**row[0])
        return {"control_policy_version":row[0]["policy_version"],"control_policy_hash":policy_hash(row[0])}

    def selected_branch_keys(self, search_id, *, expected_branch_keys):
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute("SELECT comparison FROM authority_story_narrative_search_decision WHERE search_id=%s",[search_id])
            row = uow.cursor.fetchone()
        if row and row[0].get("policy_version") == "available-qualified-selection.v1":
            if tuple(row[0]["selection_evidence"]["expected_branch_keys"]) != tuple(expected_branch_keys):
                raise KernelError("NARRATIVE_SEARCH_DURABLE_SELECTION_DRIFT", "Frozen strategy identity changed")
            return tuple(sorted(item["branch_key"] for item in row[0]["ranked_candidates"]))
        return tuple(expected_branch_keys)

    def require_selected(
        self,
        request: NarrativeSearchRequest,
        *,
        activate_selected: bool,
        allow_reconciled_branches: bool = False,
        opening_run_id: str = "",
    ) -> NarrativeSearchResult:

        command = request.generation
        search_key, search_id, input_hash, parent_hash = self._search_identity(request)
        self._require_current_accepted_boundary(request)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT search.status,search.input_snapshot_hash,
                       search.parent_state_content_hash,
                       search.selected_candidate_asset_version_id,
                       search.generator_operation_name,search.planning_scope,
                       search.logical_key,search.stable_idempotency_key,
                       decision.selected_candidate_asset_version_id,
                       decision.candidate_set_hash,decision.comparison,
                       decision.comparison_hash
                FROM authority_story_narrative_search AS search
                JOIN authority_story_narrative_search_decision AS decision
                  ON decision.search_id=search.search_id
                WHERE search.search_id=%s AND search.project_id=%s
                  AND search.workspace_id=%s AND search.book_id=%s
                """,
                [
                    search_id,
                    command.project_id,
                    command.workspace_id,
                    command.book_id,
                ],
            )
            row = uow.cursor.fetchone()
        expected_statuses = (
            {"ACTIVATED"} if activate_selected else {"SELECTED", "ACTIVATED"}
        )
        if (
            row is None
            or str(row[0]) not in expected_statuses
            or str(row[1]) != input_hash
            or str(row[2] or "") != parent_hash
            or str(row[3]) != str(row[8])
            or str(row[4]) != command.generator_operation_name
            or str(row[5]) != command.planning_scope.value
            or str(row[6]) != command.logical_key
            or str(row[7]) != search_key
        ):
            raise KernelError(
                "NARRATIVE_SEARCH_DURABLE_SELECTION_DRIFT",
                "durable Narrative Search does not match the exact frozen request",
            )
        if allow_reconciled_branches:
            if not opening_run_id:
                raise ValueError(
                    "reconciled selection requires its Book Opening checkpoint owner"
                )
            self._require_reconciled_branch_outer_checkpoints(
                search_id,
                opening_run_id=opening_run_id,
            )
        candidates = self._load_candidates(
            search_id,
            allow_reconciled_branches=allow_reconciled_branches,
        )
        stored_comparison = dict(row[10])
        comparison = (select_available_qualified_future(candidates, evidence=stored_comparison["selection_evidence"])
            if stored_comparison.get("policy_version") == "available-qualified-selection.v1"
            else compare_narrative_futures(candidates, selection_policy=request.desired_transformation.get("selection_policy")))
        comparison_payload = comparison.to_dict()
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
        if (
            comparison.selected_candidate_asset_version_id != str(row[3])
            or candidate_set_hash != str(row[9])
            or comparison_payload != dict(row[10])
            or canonical_hash(comparison_payload) != str(row[11])
        ):
            raise KernelError(
                "NARRATIVE_SEARCH_DURABLE_SELECTION_DRIFT",
                "Narrative Search selection evidence no longer verifies",
            )
        selected_member = next(
            (
                item
                for item in candidates
                if item.candidate_asset_version_id
                == comparison.selected_candidate_asset_version_id
            ),
            None,
        )
        if selected_member is None:
            raise KernelError(
                "NARRATIVE_SEARCH_DURABLE_SELECTION_DRIFT",
                "Narrative Search selected candidate membership is missing",
            )
        generation = self.planning.require_generation(
            selected_member.generation_operation_id
        )
        expected_generation_status = (
            "ACTIVE" if activate_selected else str(generation["status"])
        )
        if (
            str(generation["project_id"]) != command.project_id
            or str(generation["workspace_id"]) != command.workspace_id
            or str(generation["book_id"]) != command.book_id
            or str(generation["narrative_search_id"]) != search_id
            or str(generation["candidate_asset_version_id"])
            != comparison.selected_candidate_asset_version_id
            or (activate_selected and str(generation["status"]) != "ACTIVE")
        ):
            raise KernelError(
                "NARRATIVE_SEARCH_DURABLE_SELECTION_DRIFT",
                "selected Planning Generation no longer matches the search Authority",
            )
        selected = PlanningGenerationResult(
            generation_operation_id=selected_member.generation_operation_id,
            candidate_asset_version_id=comparison.selected_candidate_asset_version_id,
            status=PlanningGenerationStatus(expected_generation_status),
            story_design_state=self.planning.story_design.require(
                project_id=command.project_id,
                asset_version_id=comparison.selected_candidate_asset_version_id,
            ),
            replayed=True,
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
            replayed=True,
        )

    def _search_identity(
        self, request: NarrativeSearchRequest
    ) -> tuple[str, str, str, str]:
        command = request.generation
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
        return search_key, search_id, input_hash, parent_hash

    @staticmethod
    def _probe(execution_probe: Callable[[], object] | None) -> None:
        if execution_probe is not None:
            execution_probe()

    def _parent_state_hash(self, project_id: str, asset_version_id: str) -> str:
        if not asset_version_id:
            return ""
        asset = self.planning._require_asset(  # WHY: same Planning application boundary
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

    def require_qualified_branches(
        self,
        search_id: str,
        *,
        expected_branch_keys: Sequence[str],
        project_id: str,
    ) -> tuple[NarrativeSearchQualifiedBranch, ...]:

        expected = tuple(expected_branch_keys)
        if not expected or len(set(expected)) != len(expected):
            raise ValueError("expected Search branch keys must be non-empty and unique")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT membership.branch_key,
                       membership.candidate_asset_version_id,
                       membership.generation_operation_id,
                       generation.status,
                       membership.membership_id,
                       membership.branch_evidence_contract_version,
                       membership.branch_evidence_hash,
                       COALESCE(reconciliation.reconciliation_evidence_id,''),
                       COALESCE(reconciliation.evidence_version,0),
                       COALESCE(reconciliation.evidence_hash,'')
                FROM authority_story_narrative_search_candidate AS membership
                JOIN authority_story_planning_generation AS generation
                  ON generation.operation_id=membership.generation_operation_id
                 AND generation.narrative_search_id=membership.search_id
                 AND generation.narrative_search_branch_key=membership.branch_key
                 AND generation.candidate_asset_version_id=
                     membership.candidate_asset_version_id
                LEFT JOIN
                    authority_story_narrative_branch_reconciliation_evidence
                    AS reconciliation
                  ON reconciliation.membership_id=membership.membership_id
                WHERE membership.search_id=%s
                ORDER BY membership.branch_key
                """,
                [search_id],
            )
            rows = tuple(tuple(row) for row in uow.cursor.fetchall())
        if tuple(str(row[0]) for row in rows) != expected:
            raise KernelError(
                "NARRATIVE_SEARCH_CANDIDATE_SET_INCOMPLETE",
                "durable Search membership does not contain every frozen future",
            )
        hydrated: list[NarrativeSearchQualifiedBranch] = []
        for row in rows:
            status = PlanningGenerationStatus(str(row[3]))
            if status not in {
                PlanningGenerationStatus.APPROVAL_PENDING,
                PlanningGenerationStatus.APPROVED,
                PlanningGenerationStatus.ACTIVE,
            }:
                raise KernelError(
                    "NARRATIVE_SEARCH_CANDIDATE_NOT_QUALIFIED",
                    "durable Search branch is no longer qualified",
                )
            contract = str(row[5])
            if contract == NARRATIVE_SEARCH_BRANCH_EVIDENCE_CONTRACT_VERSION:
                evidence_type = "NARRATIVE_SEARCH_BRANCH"
                evidence_id = str(row[4])
                evidence_version = NARRATIVE_SEARCH_BRANCH_EVIDENCE_VERSION
                evidence_hash = str(row[6])
            elif contract == "legacy-unbound" and row[7]:
                evidence_type = "NARRATIVE_SEARCH_BRANCH_RECONCILIATION"
                evidence_id = str(row[7])
                evidence_version = int(row[8])
                evidence_hash = str(row[9])
            elif contract == "legacy-unbound":
                evidence_type = ""
                evidence_id = ""
                evidence_version = 0
                evidence_hash = ""
            else:
                raise KernelError(
                    "NARRATIVE_SEARCH_BRANCH_EVIDENCE_DRIFT",
                    "durable Search branch has an unknown evidence contract",
                )
            hydrated.append(
                NarrativeSearchQualifiedBranch(
                    branch_key=str(row[0]),
                    result=PlanningGenerationResult(
                        generation_operation_id=str(row[2]),
                        candidate_asset_version_id=str(row[1]),
                        status=status,
                        story_design_state=self.planning.story_design.require(
                            project_id=project_id,
                            asset_version_id=str(row[1]),
                        ),
                        replayed=True,
                    ),
                    evidence_type=evidence_type,
                    evidence_id=evidence_id,
                    evidence_version=evidence_version,
                    evidence_hash=evidence_hash,
                )
            )
        return tuple(hydrated)

    def _require_reconciled_branch_outer_checkpoints(
        self,
        search_id: str,
        *,
        opening_run_id: str,
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT membership.branch_key,
                       reconciliation.reconciliation_evidence_id,
                       reconciliation.evidence_version,
                       reconciliation.evidence_hash,
                       checkpoint.checkpoint_id
                FROM authority_story_narrative_search_candidate AS membership
                JOIN authority_story_narrative_branch_reconciliation_evidence
                     AS reconciliation
                  ON reconciliation.membership_id=membership.membership_id
                LEFT JOIN authority_book_opening_semantic_checkpoint AS checkpoint
                  ON checkpoint.opening_run_id=%s
                 AND checkpoint.semantic_work_key=
                     'narrative-search-branch:' || membership.search_id || ':' ||
                     membership.branch_key
                 AND checkpoint.owning_authority='STORY_PLANNING'
                 AND checkpoint.evidence_type=
                     'NARRATIVE_SEARCH_BRANCH_RECONCILIATION'
                 AND checkpoint.evidence_id=
                     reconciliation.reconciliation_evidence_id
                 AND checkpoint.evidence_version=reconciliation.evidence_version
                 AND checkpoint.evidence_hash=reconciliation.evidence_hash
                WHERE membership.search_id=%s
                  AND membership.branch_evidence_contract_version='legacy-unbound'
                ORDER BY membership.branch_key
                """,
                [opening_run_id, search_id],
            )
            rows = tuple(tuple(row) for row in uow.cursor.fetchall())
        if any(not row[4] for row in rows):
            raise KernelError(
                "NARRATIVE_SEARCH_BRANCH_RECONCILIATION_REQUIRED",
                "legacy Search sidecar has no exact Book Opening checkpoint",
            )

    def register_qualified_branch_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        *,
        search_id: str,
        branch_key: str,
        result: PlanningGenerationResult,
    ) -> NarrativeSearchBranchEvidence:

        search = self._lock_search_for_branch_registration(uow, search_id)
        generation_record = self._lock_generation_for_branch_registration(
            uow, result.generation_operation_id
        )
        if (
            str(generation_record["operation_id"]) != result.generation_operation_id
            or str(generation_record.get("candidate_asset_version_id") or "")
            != result.candidate_asset_version_id
            or str(generation_record.get("narrative_search_id") or "") != search_id
            or str(generation_record.get("narrative_search_branch_key") or "")
            != branch_key
            or str(generation_record["status"])
            not in {"APPROVAL_PENDING", "APPROVED", "ACTIVE"}
            or tuple(
                str(generation_record[field])
                for field in (
                    "project_id",
                    "workspace_id",
                    "book_id",
                    "generator_operation_name",
                    "planning_scope",
                    "logical_key",
                )
            )
            != tuple(
                str(search[field])
                for field in (
                    "project_id",
                    "workspace_id",
                    "book_id",
                    "generator_operation_name",
                    "planning_scope",
                    "logical_key",
                )
            )
        ):
            raise KernelError(
                "NARRATIVE_SEARCH_BRANCH_LINEAGE_INVALID",
                "qualified Search branch differs from its Planning Generation lineage",
            )
        generation = self._lock_candidate_for_branch_registration(
            uow, result.candidate_asset_version_id
        )
        if (
            str(generation["generation_id"]) != str(generation_record["generation_id"])
            or str(generation["project_id"]) != str(generation_record["project_id"])
            or str(generation["book_id"]) != str(generation_record["book_id"])
            or str(generation["asset_project_id"])
            != str(generation_record["project_id"])
            or str(generation["candidate_content_hash"])
            != str(generation["asset_content_hash"])
        ):
            raise KernelError(
                "NARRATIVE_SEARCH_BRANCH_LINEAGE_INVALID",
                "qualified Search branch differs from its Planning candidate lineage",
            )
        projection = NarrativeSearchProjection.from_mapping(
            generation["asset_content"].get("narrative_search_projection")
        )
        qualification = self._lock_qualification_for_branch_registration(
            uow,
            operation_id=result.generation_operation_id,
            candidate_asset_version_id=result.candidate_asset_version_id,
            project_id=str(generation_record["project_id"]),
            book_id=str(generation_record["book_id"]),
            generator_operation_name=str(generation_record["generator_operation_name"]),
        )
        membership_id = f"narrative-search-candidate:{search_id}:{branch_key}"
        projection_payload = projection.to_dict()
        projection_hash = canonical_hash(projection_payload)
        qualification_hash = str(qualification["narrative_qualification_hash"])
        evidence_payload = {
            "membership_id": membership_id,
            "search_id": search_id,
            "branch_key": branch_key,
            "candidate_asset_version_id": result.candidate_asset_version_id,
            "generation_operation_id": result.generation_operation_id,
            "generation_input_snapshot_hash": str(
                generation_record["input_snapshot_hash"]
            ),
            "candidate_content_hash": str(generation["candidate_content_hash"]),
            "projection_hash": projection_hash,
            "strategy_fingerprint": projection.strategy_fingerprint,
            "qualification_hash": qualification_hash,
            "evidence_version": NARRATIVE_SEARCH_BRANCH_EVIDENCE_VERSION,
        }
        evidence_hash = canonical_hash(evidence_payload)
        expected = (
            membership_id,
            search_id,
            branch_key,
            result.candidate_asset_version_id,
            result.generation_operation_id,
            projection_payload,
            projection_hash,
            projection.strategy_fingerprint,
            projection.comparison_score,
            qualification_hash,
            NARRATIVE_SEARCH_BRANCH_EVIDENCE_CONTRACT_VERSION,
            evidence_hash,
        )
        stored = self._lock_branch_membership(uow, search_id, branch_key)
        if stored is not None and str(stored[10]) == "legacy-unbound":
            raise KernelError(
                "NARRATIVE_SEARCH_BRANCH_RECONCILIATION_REQUIRED",
                "legacy Search membership has no atomic branch evidence contract",
            )
        if str(search["status"]) not in {
            "GENERATING",
            "READY_FOR_SELECTION",
            "SELECTED",
            "ACTIVATED",
        }:
            raise KernelError(
                "NARRATIVE_SEARCH_BRANCH_LINEAGE_INVALID",
                "Narrative Search is not open to qualified branch registration",
            )
        inserted = False
        if stored is None:
            if str(search["status"]) != "GENERATING":
                raise KernelError(
                    "NARRATIVE_SEARCH_BRANCH_LINEAGE_INVALID",
                    "completed Narrative Search cannot admit a missing branch",
                )
            uow.cursor.execute(
                """
                INSERT INTO authority_story_narrative_search_candidate(
                    membership_id, search_id, branch_key,
                    candidate_asset_version_id, generation_operation_id,
                    projection, projection_hash, strategy_fingerprint,
                    comparison_score, qualification_hash,
                    branch_evidence_contract_version, branch_evidence_hash,
                    status
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    'ELIGIBLE'
                )
                ON CONFLICT DO NOTHING
                RETURNING membership_id
                """,
                [
                    membership_id,
                    search_id,
                    branch_key,
                    result.candidate_asset_version_id,
                    result.generation_operation_id,
                    Jsonb(projection_payload),
                    projection_hash,
                    projection.strategy_fingerprint,
                    projection.comparison_score,
                    qualification_hash,
                    NARRATIVE_SEARCH_BRANCH_EVIDENCE_CONTRACT_VERSION,
                    evidence_hash,
                ],
            )
            inserted = uow.cursor.fetchone() is not None
            stored = self._lock_branch_membership(uow, search_id, branch_key)
        if stored is None:
            if not inserted:
                raise KernelError(
                    "NARRATIVE_SEARCH_BRANCH_IDEMPOTENCY_CONFLICT",
                    "qualified Search branch conflicts with another durable membership",
                )
            raise KernelError(
                "NARRATIVE_SEARCH_BRANCH_REGISTRATION_LOST",
                "qualified Search branch was not durably registered",
            )
        if str(stored[10]) == "legacy-unbound":
            raise KernelError(
                "NARRATIVE_SEARCH_BRANCH_RECONCILIATION_REQUIRED",
                "legacy Search membership has no atomic branch evidence contract",
            )
        normalized_stored = (
            *(str(item) for item in stored[:5]),
            dict(stored[5]),
            str(stored[6]),
            str(stored[7]),
            float(stored[8]),
            str(stored[9]),
            str(stored[10]),
            str(stored[11]),
        )
        if normalized_stored != expected:
            raise KernelError(
                "NARRATIVE_SEARCH_BRANCH_IDEMPOTENCY_CONFLICT",
                "Search branch identity is already bound to different evidence",
            )
        return NarrativeSearchBranchEvidence(
            **evidence_payload,
            evidence_hash=evidence_hash,
            replayed=not inserted,
        )

    def reconcile_legacy_qualified_branch_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        *,
        search_id: str,
        branch_key: str,
        result: PlanningGenerationResult,
        opening_run_id: str,
        opening_execution_id: str,
        execution_generation: int,
    ) -> NarrativeSearchBranchReconciliationEvidence:
        """COMPATIBILITY: Append evidence for one immutable pre-contract membership.

        This primitive deliberately requires a caller-owned transaction.  The
        Book Opening coordinator must establish and validate its live runtime
        fence before entering Planning's canonical Search -> Generation ->
        Candidate/Qualification -> Membership lock order.  No Provider call is
        made here and the historical membership is never changed.
        """
        if not opening_run_id or not opening_execution_id or execution_generation <= 0:
            raise ValueError("legacy branch reconciliation requires an execution")
        search = self._lock_search_for_branch_registration(uow, search_id)
        generation_record = self._lock_generation_for_branch_registration(
            uow, result.generation_operation_id
        )
        if (
            str(generation_record["operation_id"]) != result.generation_operation_id
            or str(generation_record.get("candidate_asset_version_id") or "")
            != result.candidate_asset_version_id
            or str(generation_record.get("narrative_search_id") or "") != search_id
            or str(generation_record.get("narrative_search_branch_key") or "")
            != branch_key
            or str(generation_record["status"])
            not in {"APPROVAL_PENDING", "APPROVED", "ACTIVE"}
            or tuple(
                str(generation_record[field])
                for field in (
                    "project_id",
                    "workspace_id",
                    "book_id",
                    "generator_operation_name",
                    "planning_scope",
                    "logical_key",
                )
            )
            != tuple(
                str(search[field])
                for field in (
                    "project_id",
                    "workspace_id",
                    "book_id",
                    "generator_operation_name",
                    "planning_scope",
                    "logical_key",
                )
            )
        ):
            raise KernelError(
                "NARRATIVE_SEARCH_BRANCH_RECONCILIATION_DRIFT",
                "legacy branch differs from its current Planning Generation lineage",
            )
        candidate = self._lock_candidate_for_branch_registration(
            uow, result.candidate_asset_version_id
        )
        if (
            str(candidate["generation_id"]) != str(generation_record["generation_id"])
            or str(candidate["project_id"]) != str(generation_record["project_id"])
            or str(candidate["book_id"]) != str(generation_record["book_id"])
            or str(candidate["asset_project_id"])
            != str(generation_record["project_id"])
            or str(candidate["candidate_content_hash"])
            != str(candidate["asset_content_hash"])
        ):
            raise KernelError(
                "NARRATIVE_SEARCH_BRANCH_RECONCILIATION_DRIFT",
                "legacy branch differs from its current Planning candidate lineage",
            )
        projection = NarrativeSearchProjection.from_mapping(
            candidate["asset_content"].get("narrative_search_projection")
        )
        qualification = self._lock_qualification_for_branch_registration(
            uow,
            operation_id=result.generation_operation_id,
            candidate_asset_version_id=result.candidate_asset_version_id,
            project_id=str(generation_record["project_id"]),
            book_id=str(generation_record["book_id"]),
            generator_operation_name=str(generation_record["generator_operation_name"]),
        )
        membership_id = f"narrative-search-candidate:{search_id}:{branch_key}"
        projection_payload = projection.to_dict()
        projection_hash = canonical_hash(projection_payload)
        qualification_hash = str(qualification["narrative_qualification_hash"])
        membership = self._lock_branch_membership(uow, search_id, branch_key)
        expected_membership = (
            membership_id,
            search_id,
            branch_key,
            result.candidate_asset_version_id,
            result.generation_operation_id,
            projection_payload,
            projection_hash,
            projection.strategy_fingerprint,
            projection.comparison_score,
            qualification_hash,
            "legacy-unbound",
            "",
        )
        normalized_membership = (
            None
            if membership is None
            else (
                *(str(item) for item in membership[:5]),
                dict(membership[5]),
                str(membership[6]),
                str(membership[7]),
                float(membership[8]),
                str(membership[9]),
                str(membership[10]),
                str(membership[11]),
            )
        )
        if normalized_membership != expected_membership:
            raise KernelError(
                "NARRATIVE_SEARCH_BRANCH_RECONCILIATION_DRIFT",
                "legacy membership differs from revalidated authoritative evidence",
            )
        branch_payload = {
            "membership_id": membership_id,
            "search_id": search_id,
            "branch_key": branch_key,
            "candidate_asset_version_id": result.candidate_asset_version_id,
            "generation_operation_id": result.generation_operation_id,
            "generation_input_snapshot_hash": str(
                generation_record["input_snapshot_hash"]
            ),
            "candidate_content_hash": str(candidate["candidate_content_hash"]),
            "projection_hash": projection_hash,
            "strategy_fingerprint": projection.strategy_fingerprint,
            "qualification_hash": qualification_hash,
            "evidence_version": NARRATIVE_SEARCH_BRANCH_EVIDENCE_VERSION,
        }
        reconciled_branch_evidence_hash = canonical_hash(branch_payload)
        qualification_receipt_set_hash = str(
            qualification["qualification_receipt_set_hash"]
        )
        qualification_receipts = list(qualification["qualification_receipts"])
        stable_payload = {
            "membership_id": membership_id,
            "source_branch_evidence_contract_version": "legacy-unbound",
            "reconciliation_contract_version": (
                NARRATIVE_SEARCH_BRANCH_RECONCILIATION_CONTRACT_VERSION
            ),
        }
        stable_key = "narrative-search-branch-reconciliation:" + canonical_hash(
            stable_payload
        ).removeprefix("sha256:")
        reconciliation_evidence_id = stable_key
        evidence_payload = {
            **branch_payload,
            "source_branch_evidence_contract_version": "legacy-unbound",
            "opening_run_id": opening_run_id,
            "opening_execution_id": opening_execution_id,
            "execution_generation": execution_generation,
            "qualification_receipt_set_hash": qualification_receipt_set_hash,
            "qualification_receipts": qualification_receipts,
            "reconciled_branch_evidence_hash": reconciled_branch_evidence_hash,
            "reconciliation_contract_version": (
                NARRATIVE_SEARCH_BRANCH_RECONCILIATION_CONTRACT_VERSION
            ),
        }
        evidence_hash = canonical_hash(evidence_payload)
        expected = (
            reconciliation_evidence_id,
            membership_id,
            search_id,
            branch_key,
            result.candidate_asset_version_id,
            result.generation_operation_id,
            "legacy-unbound",
            opening_run_id,
            opening_execution_id,
            execution_generation,
            str(generation_record["input_snapshot_hash"]),
            str(candidate["candidate_content_hash"]),
            projection_hash,
            projection.strategy_fingerprint,
            qualification_hash,
            qualification_receipt_set_hash,
            reconciled_branch_evidence_hash,
            NARRATIVE_SEARCH_BRANCH_RECONCILIATION_CONTRACT_VERSION,
            NARRATIVE_SEARCH_BRANCH_EVIDENCE_VERSION,
            evidence_payload,
            evidence_hash,
            stable_key,
        )
        uow.cursor.execute(
            """
            INSERT INTO authority_story_narrative_branch_reconciliation_evidence(
                reconciliation_evidence_id,membership_id,search_id,branch_key,
                candidate_asset_version_id,generation_operation_id,
                source_branch_evidence_contract_version,opening_run_id,
                opening_execution_id,execution_generation,
                generation_input_snapshot_hash,candidate_content_hash,
                projection_hash,strategy_fingerprint,qualification_hash,
                qualification_receipt_set_hash,reconciled_branch_evidence_hash,
                reconciliation_contract_version,evidence_version,
                evidence_payload,evidence_hash,stable_idempotency_key
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s
            ) ON CONFLICT DO NOTHING
            RETURNING reconciliation_evidence_id
            """,
            [
                *expected[:19],
                Jsonb(evidence_payload),
                *expected[20:],
            ],
        )
        inserted = uow.cursor.fetchone() is not None
        uow.cursor.execute(
            """
            SELECT reconciliation_evidence_id,membership_id,search_id,branch_key,
                   candidate_asset_version_id,generation_operation_id,
                   source_branch_evidence_contract_version,opening_run_id,
                   opening_execution_id,execution_generation,
                   generation_input_snapshot_hash,candidate_content_hash,
                   projection_hash,strategy_fingerprint,qualification_hash,
                   qualification_receipt_set_hash,reconciled_branch_evidence_hash,
                   reconciliation_contract_version,evidence_version,
                   evidence_payload,evidence_hash,stable_idempotency_key
            FROM authority_story_narrative_branch_reconciliation_evidence
            WHERE membership_id=%s
            FOR SHARE
            """,
            [membership_id],
        )
        stored = uow.cursor.fetchone()
        normalized = (
            None
            if stored is None
            else (
                *(str(item) for item in stored[:9]),
                int(stored[9]),
                *(str(item) for item in stored[10:18]),
                int(stored[18]),
                dict(stored[19]),
                str(stored[20]),
                str(stored[21]),
            )
        )
        if normalized != expected:
            raise KernelError(
                "NARRATIVE_SEARCH_BRANCH_RECONCILIATION_CONFLICT",
                "legacy membership is already bound to different reconciliation evidence",
            )
        return NarrativeSearchBranchReconciliationEvidence(
            reconciliation_evidence_id=reconciliation_evidence_id,
            membership_id=membership_id,
            search_id=search_id,
            branch_key=branch_key,
            candidate_asset_version_id=result.candidate_asset_version_id,
            generation_operation_id=result.generation_operation_id,
            source_branch_evidence_contract_version="legacy-unbound",
            opening_run_id=opening_run_id,
            opening_execution_id=opening_execution_id,
            execution_generation=execution_generation,
            generation_input_snapshot_hash=str(
                generation_record["input_snapshot_hash"]
            ),
            candidate_content_hash=str(candidate["candidate_content_hash"]),
            projection_hash=projection_hash,
            strategy_fingerprint=projection.strategy_fingerprint,
            qualification_hash=qualification_hash,
            qualification_receipt_set_hash=qualification_receipt_set_hash,
            reconciled_branch_evidence_hash=reconciled_branch_evidence_hash,
            reconciliation_contract_version=(
                NARRATIVE_SEARCH_BRANCH_RECONCILIATION_CONTRACT_VERSION
            ),
            evidence_version=NARRATIVE_SEARCH_BRANCH_EVIDENCE_VERSION,
            evidence_hash=evidence_hash,
            replayed=not inserted,
        )

    @staticmethod
    def _lock_search_for_branch_registration(
        uow: AuthorityUnitOfWork, search_id: str
    ) -> dict[str, Any]:
        uow.cursor.execute(
            """
            SELECT project_id,workspace_id,book_id,generator_operation_name,
                   planning_scope,logical_key,status
            FROM authority_story_narrative_search
            WHERE search_id=%s
            FOR UPDATE
            """,
            [search_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "NARRATIVE_SEARCH_BRANCH_LINEAGE_INVALID",
                "Narrative Search does not exist",
            )
        fields = (
            "project_id",
            "workspace_id",
            "book_id",
            "generator_operation_name",
            "planning_scope",
            "logical_key",
            "status",
        )
        return dict(zip(fields, row, strict=True))

    @staticmethod
    def _lock_generation_for_branch_registration(
        uow: AuthorityUnitOfWork, operation_id: str
    ) -> dict[str, Any]:
        uow.cursor.execute(
            """
            SELECT generation_id,operation_id,project_id,workspace_id,book_id,
                   generator_operation_name,planning_scope,logical_key,
                   input_snapshot_hash,status,candidate_asset_version_id,
                   COALESCE(narrative_search_id,''),
                   COALESCE(narrative_search_branch_key,'')
            FROM authority_story_planning_generation
            WHERE operation_id=%s
            FOR SHARE
            """,
            [operation_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "NARRATIVE_SEARCH_BRANCH_LINEAGE_INVALID",
                "Planning Generation does not exist",
            )
        fields = (
            "generation_id",
            "operation_id",
            "project_id",
            "workspace_id",
            "book_id",
            "generator_operation_name",
            "planning_scope",
            "logical_key",
            "input_snapshot_hash",
            "status",
            "candidate_asset_version_id",
            "narrative_search_id",
            "narrative_search_branch_key",
        )
        return dict(zip(fields, row, strict=True))

    @staticmethod
    def _lock_candidate_for_branch_registration(
        uow: AuthorityUnitOfWork, candidate_asset_version_id: str
    ) -> dict[str, Any]:
        uow.cursor.execute(
            """
            SELECT candidate.generation_id,candidate.project_id,candidate.book_id,
                   candidate.content_hash,version.content_hash,asset.project_id,
                   version.content
            FROM authority_story_planning_candidate AS candidate
            JOIN authority_asset_version AS version
              ON version.asset_version_id=candidate.candidate_asset_version_id
            JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
            WHERE candidate.candidate_asset_version_id=%s
            FOR SHARE OF candidate,version,asset
            """,
            [candidate_asset_version_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "NARRATIVE_SEARCH_BRANCH_LINEAGE_INVALID",
                "Planning candidate does not exist",
            )
        fields = (
            "generation_id",
            "project_id",
            "book_id",
            "candidate_content_hash",
            "asset_content_hash",
            "asset_project_id",
            "asset_content",
        )
        return dict(zip(fields, row, strict=True))

    def _lock_qualification_for_branch_registration(
        self,
        uow: AuthorityUnitOfWork,
        *,
        operation_id: str,
        candidate_asset_version_id: str,
        project_id: str,
        book_id: str,
        generator_operation_name: str,
    ) -> dict[str, Any]:
        from novel_forge.modules.story_design_authority.creative_validation import candidate_validation
        admission = candidate_validation(uow.cursor, project_id=project_id, asset_version_id=candidate_asset_version_id)
        if admission is not None:
            uow.cursor.execute("""SELECT qualification,approval,freshness FROM authority_story_design_version_state
                WHERE project_id=%s AND asset_version_id=%s FOR SHARE""", [project_id, candidate_asset_version_id])
            state = uow.cursor.fetchone()
            if (admission["book_id"] != book_id or admission["generation_operation_id"] != operation_id
                    or not state or state[0] != "STRUCTURALLY_VALID" or state[1] not in {"PENDING", "APPROVED"} or state[2] != "CURRENT"):
                raise KernelError("NARRATIVE_VALIDATION_RECEIPT_INVALID", candidate_asset_version_id)
            return {"narrative_qualification_hash": canonical_hash(admission), "qualification_receipts": [admission],
                    "qualification_receipt_set_hash": canonical_hash([admission])}
        profiles = qualification_profiles_for_asset(
            uow.cursor,
            project_id=project_id,
            asset_version_id=candidate_asset_version_id,
            generator=generator_operation_name,
        )
        expected = {profile.layer.value: profile for profile in profiles}
        uow.cursor.execute(
            """
            SELECT qualification_id,design_layer,profile_id,profile_version,
                   profile_hash,evaluation_hash,qualification_hash,
                   evaluator_execution_class,evaluation_operation_id,
                   evaluation_attempt_id,evaluation_asset_version_id,
                   evaluation_evidence_hash,
                   provider_model_call_asset_version_id,
                   provider_model_call_content_hash,provider_evidence_hash,
                   provider_result_hash,provider_route_snapshot_id
            FROM authority_narrative_design_qualification AS qualification
            WHERE project_id=%s AND book_id=%s
              AND asset_version_id=%s AND generation_operation_id=%s
              AND qualification_status='PASS'
              AND trust_boundary='INDEPENDENT'
              AND (
                    evaluator_execution_class='MODEL_PROVIDER'
                    OR (%s AND evaluator_execution_class='SCRIPTED_FIXTURE')
                  )
              AND (
                    evaluator_execution_class<>'MODEL_PROVIDER'
                    OR (
                        provider_model_call_asset_version_id IS NOT NULL
                        AND provider_model_call_content_hash IS NOT NULL
                        AND provider_evidence_hash IS NOT NULL
                        AND provider_result_hash IS NOT NULL
                        AND provider_route_snapshot_id IS NOT NULL
                    )
                  )
            ORDER BY design_layer
            FOR SHARE OF qualification
            """,
            [
                project_id,
                book_id,
                candidate_asset_version_id,
                operation_id,
                self.planning.allow_scripted_evaluation_fixture,
            ],
        )
        rows = uow.cursor.fetchall()
        by_layer = {str(row[1]): row for row in rows}
        if set(by_layer) != set(expected) or len(rows) != len(expected):
            raise KernelError(
                "NARRATIVE_QUALIFICATION_RECEIPT_INCOMPLETE",
                "Narrative Semantic Evaluation receipts are missing or ambiguous",
            )
        hashes: set[str] = set()
        for layer in sorted(expected):
            row = by_layer[layer]
            profile = expected[layer]
            if tuple(str(item) for item in row[2:5]) != (
                profile.profile_id,
                profile.profile_version,
                profile.profile_hash,
            ):
                raise KernelError(
                    "NARRATIVE_QUALIFICATION_RECEIPT_STALE",
                    "stored Narrative Qualification profile differs from current policy",
                )
            hashes.add(str(row[6]))
        if len(hashes) != 1:
            raise KernelError(
                "NARRATIVE_QUALIFICATION_RECEIPT_INCONSISTENT",
                "layer receipts do not share one qualification identity",
            )
        receipts = [
            {
                "qualification_id": str(row[0]),
                "design_layer": str(row[1]),
                "profile_id": str(row[2]),
                "profile_version": str(row[3]),
                "profile_hash": str(row[4]),
                "evaluation_hash": str(row[5]),
                "qualification_hash": str(row[6]),
                "evaluator_execution_class": str(row[7]),
                "evaluation_operation_id": str(row[8]),
                "evaluation_attempt_id": str(row[9]),
                "evaluation_asset_version_id": str(row[10]),
                "evaluation_evidence_hash": str(row[11]),
                "provider_model_call_asset_version_id": str(row[12] or ""),
                "provider_model_call_content_hash": str(row[13] or ""),
                "provider_evidence_hash": str(row[14] or ""),
                "provider_result_hash": str(row[15] or ""),
                "provider_route_snapshot_id": str(row[16] or ""),
            }
            for row in rows
        ]
        return {
            "narrative_qualification_hash": hashes.pop(),
            "qualification_receipts": receipts,
            "qualification_receipt_set_hash": canonical_hash(receipts),
        }

    @staticmethod
    def _lock_branch_membership(
        uow: AuthorityUnitOfWork, search_id: str, branch_key: str
    ) -> tuple[Any, ...] | None:
        uow.cursor.execute(
            """
            SELECT membership_id,search_id,branch_key,
                   candidate_asset_version_id,generation_operation_id,
                   projection,projection_hash,strategy_fingerprint,
                   comparison_score,qualification_hash,
                   branch_evidence_contract_version,branch_evidence_hash
            FROM authority_story_narrative_search_candidate
            WHERE search_id=%s AND branch_key=%s
            FOR UPDATE
            """,
            [search_id, branch_key],
        )
        return uow.cursor.fetchone()

    def _register_candidate(
        self, search_id: str, branch_key: str, result: PlanningGenerationResult
    ) -> NarrativeSearchBranchEvidence:
        with AuthorityUnitOfWork(self.database_url) as uow:
            evidence = self.register_qualified_branch_in_uow(
                uow,
                search_id=search_id,
                branch_key=branch_key,
                result=result,
            )
            uow.commit()
        return evidence

    def _load_candidates(
        self,
        search_id: str,
        *,
        allow_reconciled_branches: bool = False,
    ) -> tuple[NarrativeSearchCandidate, ...]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT membership.candidate_asset_version_id,
                       membership.generation_operation_id,
                       membership.branch_key,membership.projection,
                       membership.qualification_hash,
                       membership.branch_evidence_contract_version,
                       membership.branch_evidence_hash,
                       COALESCE(reconciliation.reconciliation_evidence_id,''),
                       COALESCE(reconciliation.reconciliation_contract_version,''),
                       COALESCE(reconciliation.evidence_hash,'')
                FROM authority_story_narrative_search_candidate AS membership
                LEFT JOIN
                    authority_story_narrative_branch_reconciliation_evidence
                    AS reconciliation
                  ON reconciliation.membership_id=membership.membership_id
                WHERE membership.search_id=%s ORDER BY membership.branch_key
                """,
                [search_id],
            )
            rows = uow.cursor.fetchall()
        self._require_consumable_branch_contracts(
            rows,
            allow_reconciled_branches=allow_reconciled_branches,
        )
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
        self,
        search_id: str,
        candidates: Sequence[NarrativeSearchCandidate],
        *,
        allow_reconciled_branches: bool = False,
        available_selection_evidence: Mapping[str, Any] | None = None,
    ) -> tuple[NarrativeSearchComparison, bool]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                "SELECT desired_transformation FROM authority_story_narrative_search WHERE search_id=%s",
                [search_id],
            )
            frozen = uow.cursor.fetchone()
        if not frozen:
            raise KernelError(
                "NARRATIVE_SEARCH_SELECTION_SOURCE_MISSING",
                "Selection requires the persisted work and stage goals",
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute("SELECT comparison FROM authority_story_narrative_search_decision WHERE search_id=%s",[search_id])
            previous = uow.cursor.fetchone()
        if previous and previous[0].get("policy_version") == "available-qualified-selection.v1":
            available_selection_evidence = previous[0]["selection_evidence"]
        comparison = (select_available_qualified_future(candidates, evidence=available_selection_evidence)
            if available_selection_evidence else compare_narrative_futures(candidates, selection_policy=dict(frozen[0]).get("selection_policy")))
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
            self._lock_candidate_set_for_selection(
                uow,
                search_id=search_id,
                candidates=candidates,
                allow_reconciled_branches=allow_reconciled_branches,
            )
            if available_selection_evidence:
                if not previous:
                    uow.cursor.execute("""SELECT 1 FROM authority_runtime_policy_selection selection
                        JOIN authority_runtime_policy_version version USING(owner,project_id,policy_version)
                        JOIN authority_story_narrative_search search ON search.project_id=selection.project_id
                        WHERE selection.owner='BOOK_CONTROL' AND search.search_id=%s
                          AND version.policy_version=%s AND version.content_hash=%s
                          AND version.content->>'planning_selection_mode'='AVAILABLE_QUALIFIED'
                        FOR SHARE OF selection""",[search_id,available_selection_evidence["control_policy_version"],available_selection_evidence["control_policy_hash"]])
                    if not uow.cursor.fetchone():
                        raise KernelError("NARRATIVE_SEARCH_SELECTION_POLICY_STALE", "Select through the current native ControlPolicy")
                uow.cursor.execute("""SELECT 1 FROM authority_story_planning_generation generation
                    JOIN authority_operation operation USING(operation_id)
                    WHERE generation.narrative_search_id=%s
                      AND operation.status IN ('ADMITTED','EXECUTING','WAITING_EXTERNAL_RESULT','RECONCILIATION_REQUIRED')
                      AND NOT EXISTS(SELECT 1 FROM authority_generation_isolation isolated WHERE isolated.operation_id=operation.operation_id) LIMIT 1""",[search_id])
                if uow.cursor.fetchone():
                    raise KernelError("NARRATIVE_SEARCH_ACTIVE_WRITER", "Stop or isolate the active branch before available-candidate selection")
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

    @staticmethod
    def _lock_candidate_set_for_selection(
        uow: AuthorityUnitOfWork,
        *,
        search_id: str,
        candidates: Sequence[NarrativeSearchCandidate],
        allow_reconciled_branches: bool = False,
    ) -> None:
        uow.cursor.execute(
            """
            SELECT status
            FROM authority_story_narrative_search
            WHERE search_id=%s
            FOR UPDATE
            """,
            [search_id],
        )
        search = uow.cursor.fetchone()
        if search is None or str(search[0]) not in {
            "GENERATING",
            "READY_FOR_SELECTION",
            "SELECTED",
            "ACTIVATED",
        }:
            raise KernelError(
                "NARRATIVE_SEARCH_CANDIDATE_SET_DRIFT",
                "Narrative Search is not eligible for selection",
            )
        uow.cursor.execute(
            """
            SELECT membership.branch_key,
                   membership.candidate_asset_version_id,
                   membership.generation_operation_id,
                   membership.branch_evidence_contract_version,
                   membership.branch_evidence_hash,
                   COALESCE(reconciliation.reconciliation_evidence_id,''),
                   COALESCE(reconciliation.reconciliation_contract_version,''),
                   COALESCE(reconciliation.evidence_hash,'')
            FROM authority_story_narrative_search_candidate AS membership
            LEFT JOIN authority_story_narrative_branch_reconciliation_evidence
                       AS reconciliation
              ON reconciliation.membership_id=membership.membership_id
            WHERE membership.search_id=%s
            ORDER BY membership.branch_key
            FOR UPDATE OF membership
            """,
            [search_id],
        )
        rows = tuple(tuple(row) for row in uow.cursor.fetchall())
        PostgresNarrativeSearchApplication._require_consumable_branch_contracts(
            rows,
            allow_reconciled_branches=allow_reconciled_branches,
            contract_offset=3,
        )
        stored = tuple(tuple(str(value) for value in row[:3]) for row in rows)
        expected = tuple(
            (
                candidate.branch_key,
                candidate.candidate_asset_version_id,
                candidate.generation_operation_id,
            )
            for candidate in candidates
        )
        if stored != expected:
            raise KernelError(
                "NARRATIVE_SEARCH_CANDIDATE_SET_DRIFT",
                "locked Narrative Search membership differs from comparison input",
            )

    @staticmethod
    def _require_consumable_branch_contracts(
        rows: Sequence[Sequence[Any]],
        *,
        allow_reconciled_branches: bool,
        contract_offset: int = 5,
    ) -> None:
        for row in rows:
            contract = str(row[contract_offset])
            branch_hash = str(row[contract_offset + 1])
            reconciliation_id = str(row[contract_offset + 2])
            reconciliation_contract = str(row[contract_offset + 3])
            reconciliation_hash = str(row[contract_offset + 4])
            modern = (
                contract == NARRATIVE_SEARCH_BRANCH_EVIDENCE_CONTRACT_VERSION
                and branch_hash.startswith("sha256:")
            )
            reconciled = (
                allow_reconciled_branches
                and contract == "legacy-unbound"
                and branch_hash == ""
                and bool(reconciliation_id)
                and reconciliation_contract
                == NARRATIVE_SEARCH_BRANCH_RECONCILIATION_CONTRACT_VERSION
                and reconciliation_hash.startswith("sha256:")
            )
            if modern or reconciled:
                continue
            if contract == "legacy-unbound":
                raise KernelError(
                    "NARRATIVE_SEARCH_BRANCH_RECONCILIATION_REQUIRED",
                    "legacy Search membership is not consumable without exact sidecar evidence",
                )
            raise KernelError(
                "NARRATIVE_SEARCH_BRANCH_EVIDENCE_DRIFT",
                "Narrative Search membership evidence contract is invalid",
            )


__all__ = [
    "DEFAULT_SEARCH_DIRECTIVES",
    "NARRATIVE_SEARCH_BRANCH_EVIDENCE_CONTRACT_VERSION",
    "NARRATIVE_SEARCH_BRANCH_EVIDENCE_VERSION",
    "NARRATIVE_SEARCH_BRANCH_RECONCILIATION_CONTRACT_VERSION",
    "NarrativeSearchBranchEvidence",
    "NarrativeSearchBranchReconciliationEvidence",
    "NarrativeSearchQualifiedBranch",
    "NarrativeSearchQualifiedBranchCommitter",
    "NarrativeSearchRequest",
    "NarrativeSearchResult",
    "PostgresNarrativeSearchApplication",
]
