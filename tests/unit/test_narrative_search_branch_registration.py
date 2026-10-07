from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.domain import (
    GENERATOR_INPUT_ROLES,
    PlanningGenerationResult,
    PlanningGenerationStatus,
    StoryPlanningGenerationCommand,
    canonical_hash,
)
from novel_forge.modules.story_planning_runtime.narrative_search import (
    CREATIVE_INTELLIGENCE_DIMENSIONS,
    NARRATIVE_SEARCH_PROJECTION_VERSION,
    NarrativeSearchCandidate,
    NarrativeSearchProjection,
    compare_narrative_futures,
)
from novel_forge.modules.story_planning_runtime.search_application import (
    NARRATIVE_SEARCH_BRANCH_EVIDENCE_CONTRACT_VERSION,
    NARRATIVE_SEARCH_BRANCH_RECONCILIATION_CONTRACT_VERSION,
    NarrativeSearchBranchEvidence,
    NarrativeSearchBranchReconciliationEvidence,
    NarrativeSearchRequest,
    PostgresNarrativeSearchApplication,
)
from novel_forge.modules.story_design_authority.qualification import (
    required_qualification_profiles,
)
from novel_forge.modules.story_planning_runtime import search_application as search_module


def _projection(fingerprint: str, score: float) -> dict[str, object]:
    return {
        "contract_version": NARRATIVE_SEARCH_PROJECTION_VERSION,
        "strategy_fingerprint": fingerprint,
        "assumptions": ["accepted reality remains immutable"],
        "projected_consequences": ["the protagonist pays for a chosen action"],
        "narrative_opportunities": ["a relationship pressure opens a new path"],
        "narrative_risks": ["one payoff window becomes narrower"],
        "irreversible_decisions": [],
        "future_options": ["world consequence", "relationship reversal"],
        "repetition_keys": [fingerprint],
        "creative_intelligence": {
            dimension: score for dimension in CREATIVE_INTELLIGENCE_DIMENSIONS
        },
        "selection_summary": f"qualified {fingerprint}",
    }


class _Planning:
    allow_scripted_evaluation_fixture = True


class _Cursor:
    def __init__(self) -> None:
        self.membership: tuple[Any, ...] | None = None
        self._row: tuple[Any, ...] | None = None
        self._rows: list[tuple[Any, ...]] = []
        self.suppress_insert = False
        self.read_order: list[str] = []
        self.insert_parameters: list[Any] | None = None
        self.reconciliation: tuple[Any, ...] | None = None
        self.reconciliation_insert_parameters: list[Any] | None = None

    @staticmethod
    def _qualification_rows() -> list[tuple[Any, ...]]:
        return [
            (
                f"qualification:{profile.layer.value}",
                profile.layer.value,
                profile.profile_id,
                profile.profile_version,
                profile.profile_hash,
                "sha256:" + "4" * 64,
                "sha256:" + "3" * 64,
                "SCRIPTED_FIXTURE",
                f"evaluation:{profile.layer.value}",
                f"attempt:{profile.layer.value}",
                f"asset:evaluation:{profile.layer.value}",
                "sha256:" + "5" * 64,
                None,
                None,
                None,
                None,
                None,
            )
            for profile in required_qualification_profiles("book_plan.generate")
        ]

    def execute(self, statement: str, parameters: list[Any]) -> None:
        if "SELECT v.content FROM authority_asset_version" in statement:
            assert parameters == ["project:test", "candidate:future-1"]
            self._row = ({"narrative_search_projection": _projection("agency", 0.82)},)
            return
        if "SELECT v.content_hash,e.request_payload" in statement:
            self._rows = []
            self._row = None
            return
        if "FROM authority_story_narrative_search\n" in statement:
            assert "FOR UPDATE" in statement
            self.read_order.append("search")
            self._row = (
                "project:test",
                "workspace:test",
                "book:test",
                "book_plan.generate",
                "BOOK",
                "book:main",
                "GENERATING",
            )
            return
        if "FROM authority_story_planning_generation" in statement:
            assert "FOR SHARE" in statement
            self.read_order.append("generation")
            self._row = (
                "generation:future-1",
                "operation:future-1",
                "project:test",
                "workspace:test",
                "book:test",
                "book_plan.generate",
                "BOOK",
                "book:main",
                "sha256:" + "1" * 64,
                "APPROVAL_PENDING",
                "candidate:future-1",
                "search:test",
                "future-1",
            )
            return
        if "FROM authority_story_planning_candidate AS candidate" in statement:
            assert "FOR SHARE OF candidate,version,asset" in statement
            self.read_order.append("candidate")
            self._row = (
                "generation:future-1",
                "project:test",
                "book:test",
                "sha256:" + "2" * 64,
                "sha256:" + "2" * 64,
                "project:test",
                {"narrative_search_projection": _projection("agency", 0.82)},
            )
            return
        if "FROM authority_narrative_design_qualification" in statement:
            assert "FOR SHARE OF qualification" in statement
            self.read_order.append("qualification")
            self._rows = self._qualification_rows()
            self._row = None
            return
        if "INSERT INTO authority_story_narrative_search_candidate" in statement:
            self.insert_parameters = list(parameters)
            if self.suppress_insert:
                self._row = None
                return
            if self.membership is None:
                self.membership = (
                    parameters[0],
                    parameters[1],
                    parameters[2],
                    parameters[3],
                    parameters[4],
                    parameters[5].obj,
                    parameters[6],
                    parameters[7],
                    parameters[8],
                    parameters[9],
                    parameters[10],
                    parameters[11],
                )
                self._row = (parameters[0],)
            else:
                self._row = None
            return
        if (
            "INSERT INTO authority_story_narrative_branch_reconciliation_evidence"
            in statement
        ):
            self.reconciliation_insert_parameters = list(parameters)
            if self.reconciliation is None:
                self.reconciliation = tuple(
                    parameter.obj if hasattr(parameter, "obj") else parameter
                    for parameter in parameters
                )
                self._row = (parameters[0],)
            else:
                self._row = None
            return
        if (
            "FROM authority_story_narrative_branch_reconciliation_evidence"
            in statement
        ):
            assert "FOR SHARE" in statement
            self.read_order.append("reconciliation")
            self._row = self.reconciliation
            return
        if "FROM authority_story_narrative_search_candidate" in statement:
            assert "FOR UPDATE" in statement
            self.read_order.append("membership")
            self._row = self.membership
            return
        raise AssertionError(statement)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._row

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class _Uow:
    def __init__(self) -> None:
        self.cursor = _Cursor()


class _SelectionLockCursor:
    def __init__(self, *, legacy: bool = False, reconciled: bool = False) -> None:
        self._row: tuple[Any, ...] | None = None
        self._rows: list[tuple[Any, ...]] = []
        self.read_order: list[str] = []
        self.legacy = legacy
        self.reconciled = reconciled

    def execute(self, statement: str, parameters: list[Any]) -> None:
        assert parameters == ["search:test"]
        if "SELECT status" in statement:
            assert "FOR UPDATE" in statement
            self.read_order.append("search")
            self._row = ("GENERATING",)
            return
        if "SELECT membership.branch_key" in statement:
            assert "FOR UPDATE OF membership" in statement
            self.read_order.append("membership")
            self._rows = [
                (
                    "future-1",
                    "candidate:future-1",
                    "operation:future-1",
                    "legacy-unbound"
                    if self.legacy
                    else NARRATIVE_SEARCH_BRANCH_EVIDENCE_CONTRACT_VERSION,
                    ""
                    if self.legacy
                    else "sha256:" + "8" * 64,
                    "reconciliation:future-1" if self.reconciled else "",
                    NARRATIVE_SEARCH_BRANCH_RECONCILIATION_CONTRACT_VERSION
                    if self.reconciled
                    else "",
                    "sha256:" + "9" * 64 if self.reconciled else "",
                ),
                (
                    "future-2",
                    "candidate:future-2",
                    "operation:future-2",
                    NARRATIVE_SEARCH_BRANCH_EVIDENCE_CONTRACT_VERSION,
                    "sha256:" + "7" * 64,
                    "",
                    "",
                    "",
                ),
            ]
            return
        raise AssertionError(statement)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._row

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class _SelectionLockUow:
    def __init__(self, *, legacy: bool = False, reconciled: bool = False) -> None:
        self.cursor = _SelectionLockCursor(
            legacy=legacy,
            reconciled=reconciled,
        )


def _result() -> PlanningGenerationResult:
    return PlanningGenerationResult(
        generation_operation_id="operation:future-1",
        candidate_asset_version_id="candidate:future-1",
        status=PlanningGenerationStatus.APPROVAL_PENDING,
        story_design_state={"qualification": "QUALIFIED"},
        replayed=False,
    )


def test_register_qualified_branch_in_uow_returns_durable_evidence() -> None:
    application = PostgresNarrativeSearchApplication(
        "postgresql://authority.test/database",
        planning=_Planning(),  # type: ignore[arg-type]
    )
    uow = _Uow()

    evidence = application.register_qualified_branch_in_uow(
        uow,  # type: ignore[arg-type]
        search_id="search:test",
        branch_key="future-1",
        result=_result(),
    )

    assert isinstance(evidence, NarrativeSearchBranchEvidence)
    assert evidence.membership_id == (
        "narrative-search-candidate:search:test:future-1"
    )
    assert evidence.candidate_asset_version_id == "candidate:future-1"
    assert evidence.generation_operation_id == "operation:future-1"
    assert evidence.generation_input_snapshot_hash == "sha256:" + "1" * 64
    assert evidence.candidate_content_hash == "sha256:" + "2" * 64
    assert evidence.qualification_hash == "sha256:" + "3" * 64
    assert evidence.evidence_version == 1
    assert evidence.evidence_hash.startswith("sha256:")
    assert evidence.replayed is False
    assert uow.cursor.insert_parameters is not None
    assert uow.cursor.insert_parameters[-2:] == [
        NARRATIVE_SEARCH_BRANCH_EVIDENCE_CONTRACT_VERSION,
        evidence.evidence_hash,
    ]
    assert uow.cursor.read_order[:5] == [
        "search",
        "generation",
        "candidate",
        "qualification",
        "membership",
    ]


def test_branch_commit_contract_is_exported_from_story_planning_runtime() -> None:
    from novel_forge.modules.story_planning_runtime import (
        NARRATIVE_SEARCH_BRANCH_EVIDENCE_CONTRACT_VERSION as PublicContractVersion,
    )
    from novel_forge.modules.story_planning_runtime import (
        NarrativeSearchBranchEvidence as PublicEvidence,
    )
    from novel_forge.modules.story_planning_runtime import (
        NarrativeSearchQualifiedBranchCommitter as PublicCommitter,
    )

    assert PublicEvidence is NarrativeSearchBranchEvidence
    assert PublicCommitter.__name__ == "NarrativeSearchQualifiedBranchCommitter"
    assert PublicContractVersion == NARRATIVE_SEARCH_BRANCH_EVIDENCE_CONTRACT_VERSION


def test_register_qualified_branch_in_uow_replays_exact_evidence() -> None:
    application = PostgresNarrativeSearchApplication(
        "postgresql://authority.test/database",
        planning=_Planning(),  # type: ignore[arg-type]
    )
    uow = _Uow()

    first = application.register_qualified_branch_in_uow(
        uow,  # type: ignore[arg-type]
        search_id="search:test",
        branch_key="future-1",
        result=_result(),
    )
    replay = application.register_qualified_branch_in_uow(
        uow,  # type: ignore[arg-type]
        search_id="search:test",
        branch_key="future-1",
        result=_result(),
    )

    assert replay.evidence_hash == first.evidence_hash
    assert replay.membership_id == first.membership_id
    assert replay.replayed is True


def test_register_qualified_branch_in_uow_rejects_conflicting_membership() -> None:
    application = PostgresNarrativeSearchApplication(
        "postgresql://authority.test/database",
        planning=_Planning(),  # type: ignore[arg-type]
    )
    uow = _Uow()
    application.register_qualified_branch_in_uow(
        uow,  # type: ignore[arg-type]
        search_id="search:test",
        branch_key="future-1",
        result=_result(),
    )
    assert uow.cursor.membership is not None
    uow.cursor.membership = (
        *uow.cursor.membership[:3],
        "candidate:conflict",
        *uow.cursor.membership[4:],
    )

    with pytest.raises(KernelError) as conflict:
        application.register_qualified_branch_in_uow(
            uow,  # type: ignore[arg-type]
            search_id="search:test",
            branch_key="future-1",
            result=_result(),
        )

    assert conflict.value.code == "NARRATIVE_SEARCH_BRANCH_IDEMPOTENCY_CONFLICT"


@pytest.mark.parametrize(
    ("field_index", "replacement"),
    (
        (10, "narrative-search-branch-evidence.v2"),
        (11, "sha256:" + "9" * 64),
    ),
)
def test_register_qualified_branch_in_uow_rejects_stored_evidence_contract_drift(
    field_index: int,
    replacement: str,
) -> None:
    application = PostgresNarrativeSearchApplication(
        "postgresql://authority.test/database",
        planning=_Planning(),  # type: ignore[arg-type]
    )
    uow = _Uow()
    application.register_qualified_branch_in_uow(
        uow,  # type: ignore[arg-type]
        search_id="search:test",
        branch_key="future-1",
        result=_result(),
    )
    assert uow.cursor.membership is not None
    stored = list(uow.cursor.membership)
    stored[field_index] = replacement
    uow.cursor.membership = tuple(stored)

    with pytest.raises(KernelError) as conflict:
        application.register_qualified_branch_in_uow(
            uow,  # type: ignore[arg-type]
            search_id="search:test",
            branch_key="future-1",
            result=_result(),
        )

    assert conflict.value.code == "NARRATIVE_SEARCH_BRANCH_IDEMPOTENCY_CONFLICT"


def test_register_qualified_branch_in_uow_requires_reconciliation_for_legacy_row(
) -> None:
    application = PostgresNarrativeSearchApplication(
        "postgresql://authority.test/database",
        planning=_Planning(),  # type: ignore[arg-type]
    )
    uow = _Uow()
    uow.cursor.membership = (
        "narrative-search-candidate:search:test:future-1",
        "search:test",
        "future-1",
        "candidate:future-1",
        "operation:future-1",
        _projection("agency", 0.82),
        "sha256:" + "6" * 64,
        "agency",
        0.82,
        "sha256:" + "3" * 64,
        "legacy-unbound",
        "",
    )

    with pytest.raises(KernelError) as reconciliation:
        application.register_qualified_branch_in_uow(
            uow,  # type: ignore[arg-type]
            search_id="search:test",
            branch_key="future-1",
            result=_result(),
        )

    assert (
        reconciliation.value.code
        == "NARRATIVE_SEARCH_BRANCH_RECONCILIATION_REQUIRED"
    )
    assert uow.cursor.insert_parameters is None


def test_reconcile_legacy_branch_in_uow_appends_exact_sidecar_evidence() -> None:
    application = PostgresNarrativeSearchApplication(
        "postgresql://authority.test/database",
        planning=_Planning(),  # type: ignore[arg-type]
    )
    uow = _Uow()
    projection = _projection("agency", 0.82)
    uow.cursor.membership = (
        "narrative-search-candidate:search:test:future-1",
        "search:test",
        "future-1",
        "candidate:future-1",
        "operation:future-1",
        projection,
        canonical_hash(projection),
        "agency",
        NarrativeSearchProjection.from_mapping(projection).comparison_score,
        "sha256:" + "3" * 64,
        "legacy-unbound",
        "",
    )

    evidence = application.reconcile_legacy_qualified_branch_in_uow(
        uow,  # type: ignore[arg-type]
        search_id="search:test",
        branch_key="future-1",
        result=_result(),
        opening_run_id="opening:test",
        opening_execution_id="opening-execution:test:1",
        execution_generation=1,
    )

    assert isinstance(evidence, NarrativeSearchBranchReconciliationEvidence)
    assert evidence.membership_id == uow.cursor.membership[0]
    assert evidence.evidence_type == "NARRATIVE_SEARCH_BRANCH_RECONCILIATION"
    assert evidence.reconciliation_contract_version == (
        NARRATIVE_SEARCH_BRANCH_RECONCILIATION_CONTRACT_VERSION
    )
    assert evidence.qualification_receipt_set_hash.startswith("sha256:")
    assert evidence.reconciled_branch_evidence_hash.startswith("sha256:")
    assert evidence.evidence_hash.startswith("sha256:")
    assert evidence.replayed is False
    assert uow.cursor.reconciliation_insert_parameters is not None


def test_reconcile_legacy_branch_in_uow_is_exactly_idempotent() -> None:
    application = PostgresNarrativeSearchApplication(
        "postgresql://authority.test/database",
        planning=_Planning(),  # type: ignore[arg-type]
    )
    uow = _Uow()
    projection = _projection("agency", 0.82)
    uow.cursor.membership = (
        "narrative-search-candidate:search:test:future-1",
        "search:test",
        "future-1",
        "candidate:future-1",
        "operation:future-1",
        projection,
        canonical_hash(projection),
        "agency",
        NarrativeSearchProjection.from_mapping(projection).comparison_score,
        "sha256:" + "3" * 64,
        "legacy-unbound",
        "",
    )
    options = {
        "search_id": "search:test",
        "branch_key": "future-1",
        "result": _result(),
        "opening_run_id": "opening:test",
        "opening_execution_id": "opening-execution:test:1",
        "execution_generation": 1,
    }

    first = application.reconcile_legacy_qualified_branch_in_uow(
        uow, **options  # type: ignore[arg-type]
    )
    replay = application.reconcile_legacy_qualified_branch_in_uow(
        uow, **options  # type: ignore[arg-type]
    )

    assert replay.reconciliation_evidence_id == first.reconciliation_evidence_id
    assert replay.evidence_hash == first.evidence_hash
    assert replay.replayed is True


def test_reconcile_legacy_branch_rejects_outer_execution_drift() -> None:
    application = PostgresNarrativeSearchApplication(
        "postgresql://authority.test/database",
        planning=_Planning(),  # type: ignore[arg-type]
    )
    uow = _Uow()
    projection = _projection("agency", 0.82)
    uow.cursor.membership = (
        "narrative-search-candidate:search:test:future-1",
        "search:test",
        "future-1",
        "candidate:future-1",
        "operation:future-1",
        projection,
        canonical_hash(projection),
        "agency",
        NarrativeSearchProjection.from_mapping(projection).comparison_score,
        "sha256:" + "3" * 64,
        "legacy-unbound",
        "",
    )
    first = application.reconcile_legacy_qualified_branch_in_uow(
        uow,  # type: ignore[arg-type]
        search_id="search:test",
        branch_key="future-1",
        result=_result(),
        opening_run_id="opening:test",
        opening_execution_id="opening-execution:test:1",
        execution_generation=1,
    )
    assert first.replayed is False

    with pytest.raises(KernelError) as conflict:
        application.reconcile_legacy_qualified_branch_in_uow(
            uow,  # type: ignore[arg-type]
            search_id="search:test",
            branch_key="future-1",
            result=_result(),
            opening_run_id="opening:test",
            opening_execution_id="opening-execution:test:2",
            execution_generation=2,
        )

    assert conflict.value.code == "NARRATIVE_SEARCH_BRANCH_RECONCILIATION_CONFLICT"


def test_selection_uses_the_same_search_then_membership_lock_order() -> None:
    application = PostgresNarrativeSearchApplication(
        "postgresql://authority.test/database",
        planning=_Planning(),  # type: ignore[arg-type]
    )
    uow = _SelectionLockUow()
    candidates = tuple(
        NarrativeSearchCandidate(
            candidate_asset_version_id=f"candidate:future-{ordinal}",
            generation_operation_id=f"operation:future-{ordinal}",
            branch_key=f"future-{ordinal}",
            projection=NarrativeSearchProjection.from_mapping(
                _projection(f"strategy-{ordinal}", 0.7 + ordinal / 10)
            ),
            qualification_hash="sha256:" + str(ordinal) * 64,
        )
        for ordinal in (1, 2)
    )

    application._lock_candidate_set_for_selection(  # noqa: SLF001
        uow,  # type: ignore[arg-type]
        search_id="search:test",
        candidates=candidates,
    )

    assert uow.cursor.read_order == ["search", "membership"]


def test_selection_rejects_legacy_membership_without_explicit_sidecar_gate() -> None:
    application = PostgresNarrativeSearchApplication(
        "postgresql://authority.test/database",
        planning=_Planning(),  # type: ignore[arg-type]
    )
    candidates = tuple(
        NarrativeSearchCandidate(
            candidate_asset_version_id=f"candidate:future-{ordinal}",
            generation_operation_id=f"operation:future-{ordinal}",
            branch_key=f"future-{ordinal}",
            projection=NarrativeSearchProjection.from_mapping(
                _projection(f"strategy-{ordinal}", 0.7 + ordinal / 10)
            ),
            qualification_hash="sha256:" + str(ordinal) * 64,
        )
        for ordinal in (1, 2)
    )

    with pytest.raises(KernelError) as missing:
        application._lock_candidate_set_for_selection(  # noqa: SLF001
            _SelectionLockUow(legacy=True),  # type: ignore[arg-type]
            search_id="search:test",
            candidates=candidates,
        )
    assert missing.value.code == "NARRATIVE_SEARCH_BRANCH_RECONCILIATION_REQUIRED"

    application._lock_candidate_set_for_selection(  # noqa: SLF001
        _SelectionLockUow(legacy=True, reconciled=True),  # type: ignore[arg-type]
        search_id="search:test",
        candidates=candidates,
        allow_reconciled_branches=True,
    )


def test_reconciled_selection_requires_exact_outer_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Cursor:
        def __init__(self, checkpoint_id: str) -> None:
            self.checkpoint_id = checkpoint_id

        def execute(self, statement: str, parameters: list[Any]) -> None:
            assert "authority_book_opening_semantic_checkpoint" in statement
            assert parameters == ["opening:test", "search:test"]

        def fetchall(self) -> list[tuple[Any, ...]]:
            return [
                (
                    "future-1",
                    "reconciliation:future-1",
                    1,
                    "sha256:" + "9" * 64,
                    self.checkpoint_id or None,
                )
            ]

    class Uow:
        def __init__(self, checkpoint_id: str) -> None:
            self.cursor = Cursor(checkpoint_id)

        def __enter__(self):
            return self

        def __exit__(self, *_: Any) -> None:
            return None

    application = PostgresNarrativeSearchApplication(
        "postgresql://authority.test/database",
        planning=_Planning(),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        search_module,
        "AuthorityUnitOfWork",
        lambda database_url: Uow(""),
    )
    with pytest.raises(KernelError) as missing:
        application._require_reconciled_branch_outer_checkpoints(  # noqa: SLF001
            "search:test",
            opening_run_id="opening:test",
        )
    assert missing.value.code == "NARRATIVE_SEARCH_BRANCH_RECONCILIATION_REQUIRED"

    monkeypatch.setattr(
        search_module,
        "AuthorityUnitOfWork",
        lambda database_url: Uow("checkpoint:future-1"),
    )
    application._require_reconciled_branch_outer_checkpoints(  # noqa: SLF001
        "search:test",
        opening_run_id="opening:test",
    )


def test_register_qualified_branch_in_uow_rejects_other_unique_conflict() -> None:
    application = PostgresNarrativeSearchApplication(
        "postgresql://authority.test/database",
        planning=_Planning(),  # type: ignore[arg-type]
    )
    uow = _Uow()
    uow.cursor.suppress_insert = True

    with pytest.raises(KernelError) as conflict:
        application.register_qualified_branch_in_uow(
            uow,  # type: ignore[arg-type]
            search_id="search:test",
            branch_key="future-1",
            result=_result(),
        )

    assert conflict.value.code == "NARRATIVE_SEARCH_BRANCH_IDEMPOTENCY_CONFLICT"


class _ExplorePlanning:
    def __init__(self) -> None:
        self.commands: list[StoryPlanningGenerationCommand] = []
        self.frozen_commands: dict[str, StoryPlanningGenerationCommand] = {}

    def find_frozen_generation_command(
        self,
        *,
        project_id: str,
        idempotency_key: str,
    ) -> StoryPlanningGenerationCommand | None:
        command = self.frozen_commands.get(idempotency_key)
        if command is not None:
            assert command.project_id == project_id
        return command

    def generate(
        self,
        command: StoryPlanningGenerationCommand,
        **_: Any,
    ) -> PlanningGenerationResult:
        self.commands.append(command)
        branch_key = command.narrative_search_branch_key
        return PlanningGenerationResult(
            generation_operation_id=f"operation:{branch_key}",
            candidate_asset_version_id=f"candidate:{branch_key}",
            status=PlanningGenerationStatus.APPROVAL_PENDING,
            story_design_state={"qualification": "QUALIFIED"},
            replayed=False,
        )


class _SearchHarness(PostgresNarrativeSearchApplication):
    def __init__(self) -> None:
        super().__init__(
            "postgresql://authority.test/database",
            planning=_ExplorePlanning(),  # type: ignore[arg-type]
        )
        self.committed: list[str] = []

    def _open_search(self, **_: Any) -> bool:
        return False

    def _candidate_for_branch(
        self, search_id: str, branch_key: str
    ) -> dict[str, Any] | None:
        del search_id, branch_key
        return None

    def _load_candidates(
        self,
        search_id: str,
        *,
        allow_reconciled_branches: bool = False,
    ) -> tuple[NarrativeSearchCandidate, ...]:
        del search_id, allow_reconciled_branches
        return tuple(
            NarrativeSearchCandidate(
                candidate_asset_version_id=f"candidate:{branch_key}",
                generation_operation_id=f"operation:{branch_key}",
                branch_key=branch_key,
                projection=NarrativeSearchProjection.from_mapping(
                    _projection(branch_key, 0.7 + ordinal / 10)
                ),
                qualification_hash="sha256:" + str(ordinal) * 64,
            )
            for ordinal, branch_key in enumerate(self.committed, start=1)
        )

    def _select(
        self,
        search_id: str,
        candidates: Any,
        *,
        allow_reconciled_branches: bool = False,
    ) -> tuple[Any, bool]:
        del search_id, allow_reconciled_branches
        return compare_narrative_futures(candidates), False


def _search_request() -> NarrativeSearchRequest:
    return NarrativeSearchRequest(
        generation=StoryPlanningGenerationCommand(
            project_id="project:test",
            workspace_id="workspace:test",
            book_id="book:test",
            actor_id="planner:test",
            generator_operation_name="book_plan.generate",
            logical_key="book:main",
            input_versions={
                role: f"asset:{role}:v1"
                for role in GENERATOR_INPUT_ROLES["book_plan.generate"]
            },
            idempotency_key="search:test",
            trace_id="trace:test",
            correlation_id="correlation:test",
        ),
        planning_horizon={"level": "BOOK"},
        desired_transformation={"goal": "sustain the Book"},
        hard_constraints=("accepted reality is immutable",),
        accepted_through_chapter=0,
        strategy_directives=("costly agency", "consequential reversal"),
    )


def test_explore_routes_every_qualified_future_through_coordinated_committer() -> None:
    search = _SearchHarness()

    def commit_branch(
        *,
        search_id: str,
        branch_key: str,
        result: PlanningGenerationResult,
    ) -> NarrativeSearchBranchEvidence:
        assert search_id.startswith("narrative-search:")
        search.committed.append(branch_key)
        return NarrativeSearchBranchEvidence(
            membership_id=f"narrative-search-candidate:{search_id}:{branch_key}",
            search_id=search_id,
            branch_key=branch_key,
            candidate_asset_version_id=result.candidate_asset_version_id,
            generation_operation_id=result.generation_operation_id,
            generation_input_snapshot_hash="sha256:" + "1" * 64,
            candidate_content_hash="sha256:" + "2" * 64,
            projection_hash="sha256:" + "3" * 64,
            strategy_fingerprint=branch_key,
            qualification_hash="sha256:" + "4" * 64,
            evidence_version=1,
            evidence_hash="sha256:" + "5" * 64,
            replayed=False,
        )

    result = search.explore(
        _search_request(),
        principal=type(
            "Principal",
            (),
            {"require": lambda self, permission, project_id: None},
        )(),
        qualified_branch_committer=commit_branch,
    )

    assert search.committed == ["future-1", "future-2"]
    assert result.candidate_asset_version_ids == (
        "candidate:future-1",
        "candidate:future-2",
    )


def test_explore_preserves_exact_opening_fence_on_every_future_command() -> None:
    search = _SearchHarness()
    binding = {
        "opening_run_id": "opening:test",
        "opening_execution_id": "opening-execution:test",
        "opening_execution_generation": 2,
        "runtime_job_id": "runtime-job:test",
        "runtime_attempt_id": "runtime-attempt:test",
        "runtime_lease_id": "runtime-lease:test",
        "runtime_worker_id": "runtime-worker:test",
        "runtime_fencing_token": 7,
    }
    request = replace(
        _search_request(),
        generation=replace(
            _search_request().generation,
            opening_execution_binding=binding,
        ),
    )

    def commit_branch(
        *,
        search_id: str,
        branch_key: str,
        result: PlanningGenerationResult,
    ) -> NarrativeSearchBranchEvidence:
        search.committed.append(branch_key)
        return NarrativeSearchBranchEvidence(
            membership_id=f"narrative-search-candidate:{search_id}:{branch_key}",
            search_id=search_id,
            branch_key=branch_key,
            candidate_asset_version_id=result.candidate_asset_version_id,
            generation_operation_id=result.generation_operation_id,
            generation_input_snapshot_hash="sha256:" + "1" * 64,
            candidate_content_hash="sha256:" + "2" * 64,
            projection_hash="sha256:" + "3" * 64,
            strategy_fingerprint=branch_key,
            qualification_hash="sha256:" + "4" * 64,
            evidence_version=1,
            evidence_hash="sha256:" + "5" * 64,
            replayed=False,
        )

    search.explore(
        request,
        principal=type(
            "Principal",
            (),
            {"require": lambda self, permission, project_id: None},
        )(),
        qualified_branch_committer=commit_branch,
    )

    planning = search.planning
    assert isinstance(planning, _ExplorePlanning)
    assert [command.narrative_search_branch_key for command in planning.commands] == [
        "future-1",
        "future-2",
    ]
    assert all(
        dict(command.opening_execution_binding or {}) == binding
        for command in planning.commands
    )


def test_explore_resumes_admitted_branch_with_its_frozen_outer_fence() -> None:
    search = _SearchHarness()
    request = _search_request()
    current_binding = {
        "opening_run_id": "opening:test",
        "opening_execution_id": "opening-execution:test:2",
        "opening_execution_generation": 2,
        "runtime_job_id": "runtime-job:test:2",
        "runtime_attempt_id": "runtime-attempt:test:2",
        "runtime_lease_id": "runtime-lease:test:2",
        "runtime_worker_id": "runtime-worker:test:2",
        "runtime_fencing_token": 2,
    }
    predecessor_binding = {
        **current_binding,
        "opening_execution_id": "opening-execution:test:1",
        "opening_execution_generation": 1,
        "runtime_job_id": "runtime-job:test:1",
        "runtime_attempt_id": "runtime-attempt:test:1",
        "runtime_lease_id": "runtime-lease:test:1",
        "runtime_worker_id": "runtime-worker:test:1",
        "runtime_fencing_token": 1,
    }
    request = replace(
        request,
        generation=replace(
            request.generation,
            opening_execution_binding=current_binding,
        ),
    )
    search_key, search_id, _, _ = search._search_identity(request)  # noqa: SLF001
    frozen = replace(
        request.generation,
        idempotency_key=f"{search_key}:future-1",
        narrative_search_id=search_id,
        narrative_search_branch_key="future-1",
        narrative_search_parent_state_asset_version_id=(
            request.parent_state_asset_version_id
        ),
        narrative_search_accepted_through_chapter=request.accepted_through_chapter,
        narrative_search_strategy_directive=request.strategy_directives[0],
        narrative_search_planning_horizon=request.planning_horizon,
        narrative_search_desired_transformation=request.desired_transformation,
        narrative_search_hard_constraints=request.hard_constraints,
        opening_execution_binding=predecessor_binding,
        auto_approve_low_risk=False,
    )
    planning = search.planning
    assert isinstance(planning, _ExplorePlanning)
    planning.frozen_commands[frozen.idempotency_key] = frozen

    def commit_branch(
        *,
        search_id: str,
        branch_key: str,
        result: PlanningGenerationResult,
    ) -> NarrativeSearchBranchEvidence:
        search.committed.append(branch_key)
        return NarrativeSearchBranchEvidence(
            membership_id=f"narrative-search-candidate:{search_id}:{branch_key}",
            search_id=search_id,
            branch_key=branch_key,
            candidate_asset_version_id=result.candidate_asset_version_id,
            generation_operation_id=result.generation_operation_id,
            generation_input_snapshot_hash="sha256:" + "1" * 64,
            candidate_content_hash="sha256:" + "2" * 64,
            projection_hash="sha256:" + "3" * 64,
            strategy_fingerprint=branch_key,
            qualification_hash="sha256:" + "4" * 64,
            evidence_version=1,
            evidence_hash="sha256:" + "5" * 64,
            replayed=False,
        )

    search.explore(
        request,
        principal=type(
            "Principal",
            (),
            {"require": lambda self, permission, project_id: None},
        )(),
        qualified_branch_committer=commit_branch,
    )

    assert planning.commands[0] == frozen
    assert dict(planning.commands[0].opening_execution_binding or {}) == (
        predecessor_binding
    )
    assert dict(planning.commands[1].opening_execution_binding or {}) == (
        current_binding
    )


def test_explore_rejects_semantic_drift_in_an_admitted_branch_command() -> None:
    search = _SearchHarness()
    request = _search_request()
    search_key, search_id, _, _ = search._search_identity(request)  # noqa: SLF001
    frozen = replace(
        request.generation,
        idempotency_key=f"{search_key}:future-1",
        narrative_search_id=search_id,
        narrative_search_branch_key="future-1",
        narrative_search_parent_state_asset_version_id=(
            request.parent_state_asset_version_id
        ),
        narrative_search_accepted_through_chapter=request.accepted_through_chapter,
        narrative_search_strategy_directive="stale strategy",
        narrative_search_planning_horizon=request.planning_horizon,
        narrative_search_desired_transformation=request.desired_transformation,
        narrative_search_hard_constraints=request.hard_constraints,
        auto_approve_low_risk=False,
    )
    planning = search.planning
    assert isinstance(planning, _ExplorePlanning)
    planning.frozen_commands[frozen.idempotency_key] = frozen

    with pytest.raises(KernelError) as drift:
        search.explore(
            request,
            principal=type(
                "Principal",
                (),
                {"require": lambda self, permission, project_id: None},
            )(),
        )

    assert drift.value.code == "NARRATIVE_SEARCH_BRANCH_FROZEN_COMMAND_DRIFT"
    assert planning.commands == []


def test_explore_rejects_committer_evidence_for_another_branch() -> None:
    search = _SearchHarness()

    def commit_wrong_branch(
        *,
        search_id: str,
        branch_key: str,
        result: PlanningGenerationResult,
    ) -> NarrativeSearchBranchEvidence:
        search.committed.append(branch_key)
        return NarrativeSearchBranchEvidence(
            membership_id=f"narrative-search-candidate:{search_id}:future-9",
            search_id=search_id,
            branch_key="future-9",
            candidate_asset_version_id=result.candidate_asset_version_id,
            generation_operation_id=result.generation_operation_id,
            generation_input_snapshot_hash="sha256:" + "1" * 64,
            candidate_content_hash="sha256:" + "2" * 64,
            projection_hash="sha256:" + "3" * 64,
            strategy_fingerprint=branch_key,
            qualification_hash="sha256:" + "4" * 64,
            evidence_version=1,
            evidence_hash="sha256:" + "5" * 64,
            replayed=False,
        )

    with pytest.raises(KernelError) as invalid:
        search.explore(
            _search_request(),
            principal=type(
                "Principal",
                (),
                {"require": lambda self, permission, project_id: None},
            )(),
            qualified_branch_committer=commit_wrong_branch,
        )

    assert invalid.value.code == "NARRATIVE_SEARCH_BRANCH_COMMIT_INVALID"
