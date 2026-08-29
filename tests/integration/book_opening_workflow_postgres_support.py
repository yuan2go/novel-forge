from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, is_dataclass, replace
from typing import Any, cast

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.book_authority import (
    BookProductionInputResolver,
    OpenBookProductionRequest,
    PostgresBookAuthority,
    PostgresBookOpeningApplication,
    StartBookProductionCommand,
)
from novel_forge.modules.book_followup_authority.application import (
    BookFollowupAuthorityApplication,
)
from novel_forge.modules.runtime_job import RuntimeJobAuthority, RuntimeJobClaim
from novel_forge.modules.story_planning_runtime import (
    GENERATOR_INPUT_ROLES,
    PostgresNarrativeSearchApplication,
    StoryPlanningGenerationApplication,
    canonical_hash,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.workers import book_authority as book_authority_worker
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    identifier,
)
from tests.integration.capability_pack_postgres_support import (
    CapabilityPackPostgresHarness,
)
from tests.integration.test_core_functional_loops_postgres import (
    RELEASE_SHA,
    _ExternalEffectPepFixturePlanningBinder,
    _activate_planning_pack,
    _principal,
    _seed_inputs,
)


WORKFLOW_NODE_KINDS = (
    "BOOK_PLAN",
    "VOLUME_PORTFOLIO",
    "CURRENT_VOLUME",
    "INITIAL_ARC_SCOPE",
    "INPUT_SNAPSHOT",
)


class SimulatedWorkflowProcessLoss(BaseException):
    """Cross a process boundary without entering Exception recovery handlers."""


class InjectedWorkflowTransactionFailure(RuntimeError):
    """Abort one workflow transaction at a named, deterministic failpoint."""


class OneShotFaultInjector:
    def __init__(
        self,
        expected: str,
        *,
        exception_factory: Callable[[str], BaseException],
    ) -> None:
        self.expected = expected
        self.exception_factory = exception_factory
        self.triggered = False

    def __call__(self, actual: str) -> None:
        if actual == self.expected and not self.triggered:
            self.triggered = True
            raise self.exception_factory(actual)


class CountingPlanningBinder(_ExternalEffectPepFixturePlanningBinder):
    """Deterministic Provider boundary that records semantic generation sends."""

    def __init__(self, *, target_chapter_count: int) -> None:
        super().__init__(target_chapter_count=target_chapter_count)
        self.generator_calls: list[str] = []

    def execute(self, **kwargs: Any):  # type: ignore[no-untyped-def]
        command = kwargs["command"]
        self.generator_calls.append(str(command.generator_operation_name))
        candidate = super().execute(**kwargs)
        if command.generator_operation_name == "book_plan.generate":
            payload = dict(candidate.candidate_payload)
            volume_count = (self.target_chapter_count + 2) // 3
            payload["volume_skeleton"] = [
                {"volume": ordinal, "function": "commitment"}
                for ordinal in range(1, volume_count + 1)
            ]
            payload["length_strategy"] = {"target_chapters": self.target_chapter_count}
            return replace(candidate, candidate_payload=payload)
        if command.generator_operation_name != "volume_plan.generate":
            return candidate
        ordinal = int(str(command.logical_key).removeprefix("volume:"))
        payload = dict(candidate.candidate_payload)
        payload["chapter_range"] = [
            (ordinal - 1) * 3 + 1,
            min(ordinal * 3, self.target_chapter_count),
        ]
        return replace(candidate, candidate_payload=payload)


class _UnusedChapterAuthorityPort:
    """The Opening workflow must not dispatch Chapter work before BookRun."""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(
            f"Book Opening unexpectedly used Chapter Authority port {name!r}"
        )


@dataclass(slots=True)
class BookOpeningWorkflowPostgresFixture:
    project_id: str
    workspace_id: str
    book_id: str
    principal: Principal
    opening: PostgresBookOpeningApplication
    book_authority: PostgresBookAuthority
    runtime_jobs: RuntimeJobAuthority
    request: OpenBookProductionRequest
    binder: CountingPlanningBinder
    target_chapter_count: int

    def admit(self) -> Any:
        return self.opening.admit(self.request, principal=self.principal)

    def claim(self, worker_id: str) -> RuntimeJobClaim | None:
        claim = getattr(self.opening, "claim_next_node_execution")
        return cast(
            RuntimeJobClaim | None,
            claim(worker_id=worker_id, lease_seconds=30, project_id=self.project_id),
        )

    def execute(self, claim: RuntimeJobClaim) -> Any:
        execute = getattr(book_authority_worker, "execute_book_opening_node_claim")
        return execute(
            self.runtime_jobs,
            self.opening,
            self.principal,
            claim,
            lease_seconds=30,
        )

    def progress(self, opening_run_id: str) -> dict[str, Any]:
        query = getattr(self.opening, "require_progress")
        return as_mapping(query(opening_run_id))

    def start_book_run(self, input_snapshot_id: str) -> str:
        snapshot = self.opening.input_resolver.require(input_snapshot_id)
        admitted = self.book_authority.start(
            StartBookProductionCommand(
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                book_id=self.book_id,
                actor_id=self.principal.principal_id,
                trace_id=f"trace:{self.project_id}:book-run",
                correlation_id=f"correlation:{self.project_id}:book-run",
                stable_idempotency_key=f"{self.project_id}:book-run",
                book_design_version=snapshot.book_design_version,
                book_plan_version=snapshot.book_plan_version,
                production_profile_version=snapshot.production_profile_version,
                longform_context_versions={
                    "volume_plan_version": snapshot.current_volume_plan_version,
                    "arc_plan_versions": list(
                        snapshot.current_relevant_arc_plan_versions
                    ),
                    "character_state_version": snapshot.character_state_version,
                    "foreshadowing_state_version": (
                        snapshot.foreshadowing_state_version
                    ),
                    "quality_trend_version": snapshot.quality_trend_version,
                    "reward_ledger_version": snapshot.reward_ledger_version,
                    "promise_ledger_version": snapshot.promise_ledger_version,
                    "reader_segment_version": snapshot.reader_segment_version,
                    "reader_contract_version": snapshot.reader_contract_version,
                    "platform_profile_version": snapshot.platform_profile_version,
                },
                target_chapter_count=self.target_chapter_count,
                input_mode="RESOLVED_AUTHORITY_INPUT",
                input_snapshot_id=snapshot.snapshot_id,
                light_recap_cadence=5,
                formal_recap_cadence=10,
            ),
            principal=self.principal,
        )
        return admitted.book_run_id


def as_mapping(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if is_dataclass(value) and not isinstance(value, type):
        return cast(dict[str, Any], asdict(value))
    raise AssertionError(f"expected mapping-compatible workflow result, got {value!r}")


def claim_node_kind(claim: RuntimeJobClaim) -> str:
    value = claim.input_snapshot.get("workflow_node_kind")
    if not isinstance(value, str) or not value:
        raise AssertionError("Opening node RuntimeJob must freeze workflow_node_kind")
    return value


def build_workflow_fixture(
    *,
    target_chapter_count: int = 12,
    arc_logical_keys: tuple[str, ...] = ("arc:central",),
    fault_injector: Callable[[str], None] | None = None,
) -> BookOpeningWorkflowPostgresFixture:
    harness = CapabilityPackPostgresHarness(
        f"book-opening-workflow-{identifier('pack')}"
    )
    _activate_planning_pack(harness)
    project_id = harness.project_id
    workspace_id = harness.workspace_id
    book_id = harness.book_ids[0]
    principal = _principal(project_id)
    evaluator = Principal(
        principal_id=f"book-opening-workflow-evaluator:{project_id}",
        principal_type=PrincipalType.LOCAL_OPERATOR,
        permissions=frozenset({"narrative_design.evaluate"}),
        project_scope=frozenset({project_id}),
        authentication_source="book-opening-workflow-postgres",
    )
    inputs = _seed_inputs(
        project_id,
        book_id,
        target_chapter_count=target_chapter_count,
    )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        for asset_type in ("reader_segment_profile", "reader_contract"):
            asset_id = f"fixture:{project_id}:opening:{asset_type}"
            version_id = f"{asset_id}:v1"
            content = {"book_id": book_id, "role": asset_type}
            uow.cursor.execute(
                "INSERT INTO authority_asset(asset_id,project_id,asset_type) "
                "VALUES (%s,%s,%s)",
                [asset_id, project_id, asset_type],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id,asset_id,version_number,lifecycle,
                    eligibility,governance,content,content_hash,schema_version
                ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,%s)
                """,
                [
                    version_id,
                    asset_id,
                    Jsonb(content),
                    canonical_hash(content),
                    f"{asset_type}.v1",
                ],
            )
        uow.commit()

    binder = CountingPlanningBinder(target_chapter_count=target_chapter_count)
    planning = StoryPlanningGenerationApplication(
        DATABASE_URL,
        execution_binder=binder,
        application_build_id="book-opening-workflow-postgres",
        commit_sha=RELEASE_SHA,
        allow_scripted_evaluation_fixture=True,
        narrative_evaluator_principal=evaluator,
    )
    narrative_search = PostgresNarrativeSearchApplication(
        DATABASE_URL,
        planning=planning,
    )
    input_resolver = BookProductionInputResolver(
        DATABASE_URL,
        application_build_id="book-opening-workflow-postgres",
        commit_sha=RELEASE_SHA,
        allow_scripted_qualification_fixture=True,
    )
    opening = PostgresBookOpeningApplication(
        DATABASE_URL,
        narrative_search=narrative_search,
        input_resolver=input_resolver,
        application_build_id="book-opening-workflow-postgres",
        commit_sha=RELEASE_SHA,
        fault_injector=fault_injector,
    )
    followup = BookFollowupAuthorityApplication(
        DATABASE_URL,
        application_build_id="book-opening-workflow-postgres",
        commit_sha=RELEASE_SHA,
        worker_id="book-opening-workflow-followup-worker",
    )
    book_authority = PostgresBookAuthority(
        DATABASE_URL,
        chapter_port=cast(Any, _UnusedChapterAuthorityPort()),
        followup_application=followup,
        application_build_id="book-opening-workflow-postgres",
        commit_sha=RELEASE_SHA,
    )
    opening_roles = {
        role
        for generator in (
            "book_plan.generate",
            "volume_plan.generate",
            "arc_plan.generate",
        )
        for role in GENERATOR_INPUT_ROLES[generator]
        if role not in {"book_plan", "volume_plan"}
    }
    request = OpenBookProductionRequest(
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        actor_id=principal.principal_id,
        expected_book_version=int(inputs["book_version"]),
        production_profile=inputs["production_profile"],
        planning_input_versions={
            role: (
                inputs["initial_story_state"]
                if role == "story_state"
                else inputs["initial_canon_snapshot"]
                if role == "canon_snapshot"
                else inputs[role]
            )
            for role in opening_roles
        },
        arc_logical_keys=arc_logical_keys,
        idempotency_key=f"{project_id}:open-book-workflow",
        trace_id=f"trace:{project_id}:open-book-workflow",
        correlation_id=f"correlation:{project_id}:open-book-workflow",
        initial_story_state_version=inputs["initial_story_state"],
        initial_canon_snapshot_version=inputs["initial_canon_snapshot"],
    )
    return BookOpeningWorkflowPostgresFixture(
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        principal=principal,
        opening=opening,
        book_authority=book_authority,
        runtime_jobs=RuntimeJobAuthority(DATABASE_URL),
        request=request,
        binder=binder,
        target_chapter_count=target_chapter_count,
    )


__all__ = [
    "BookOpeningWorkflowPostgresFixture",
    "InjectedWorkflowTransactionFailure",
    "OneShotFaultInjector",
    "SimulatedWorkflowProcessLoss",
    "WORKFLOW_NODE_KINDS",
    "as_mapping",
    "build_workflow_fixture",
    "claim_node_kind",
]
