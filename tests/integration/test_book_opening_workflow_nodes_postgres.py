from __future__ import annotations

from collections import Counter
from types import TracebackType

import psycopg
import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.lease_heartbeat import LeaseHeartbeatGuard
from novel_forge.modules.book_authority.recovery import (
    BOOK_OPENING_WORKFLOW_EXECUTION_CONTRACT_VERSION,
)
from novel_forge.modules.runtime_job import (
    BOOK_OPENING_WORKFLOW_JOB_KIND,
    BOOK_OPENING_WORKFLOW_RUNTIME_GROUP,
)
from novel_forge.modules.story_planning_runtime.search_application import (
    DEFAULT_SEARCH_DIRECTIVES,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.workers import book_authority as book_authority_worker
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated
from tests.integration.book_opening_workflow_postgres_support import (
    OneShotFaultInjector,
    SimulatedWorkflowProcessLoss,
    WORKFLOW_NODE_KINDS,
    as_mapping,
    build_workflow_fixture,
    claim_node_kind,
)


@pytest.fixture(scope="module", autouse=True)
def _migrations() -> None:
    ensure_migrated()


def _assert_reviewable_checkpoint(
    progress: dict[str, object], *, node_kind: str
) -> None:
    furthest = as_mapping(progress["furthest_completed_layer"])
    assert furthest["node_kind"] == node_kind
    assert furthest["lifecycle"] == "COMPLETE"

    artifact = as_mapping(progress["reviewable_artifact"])
    assert artifact["status"] == "AVAILABLE"
    assert artifact["source_workflow_node_id"] == furthest["workflow_node_id"]
    expected_artifact_kind = {
        "BOOK_PLAN": "BOOK_PLAN",
        "VOLUME_PORTFOLIO": "VOLUME_PORTFOLIO",
        "CURRENT_VOLUME": "CURRENT_VOLUME_PLAN",
        "INITIAL_ARC_SCOPE": "INITIAL_ARC_SCOPE",
        "INPUT_SNAPSHOT": "BOOK_PRODUCTION_INPUT_SNAPSHOT",
    }[node_kind]
    assert artifact["artifact_kind"] == expected_artifact_kind
    if node_kind == "INPUT_SNAPSHOT":
        # The final layer is a dedicated InputSnapshot Authority row, not an
        # authority_asset_version. Its immutable node receipt/checkpoint is the
        # reviewable evidence and must not invent a plan asset-version identity.
        assert artifact["asset_versions"] == []
        reference = as_mapping(artifact["artifact_reference"])
        assert reference["reference_type"] == "BOOK_PRODUCTION_INPUT_SNAPSHOT"
        assert reference["snapshot_id"]
        assert str(reference["snapshot_hash"]).startswith("sha256:")
    else:
        assert artifact["asset_versions"]
        assert as_mapping(artifact["artifact_reference"])["asset_version_ids"]
    assert artifact["node_receipt_id"]

    checkpoint = as_mapping(progress["persistent_checkpoint"])
    assert checkpoint["status"] == "AVAILABLE"
    assert checkpoint["source_workflow_node_id"] == furthest["workflow_node_id"]
    assert checkpoint["checkpoint_id"]
    assert int(checkpoint["checkpoint_sequence"]) > 0
    assert str(checkpoint["checkpoint_hash"]).startswith("sha256:")
    execution_head = as_mapping(progress["current_execution_checkpoint"])
    assert execution_head["status"] == "AVAILABLE"
    assert execution_head["workflow_node_id"] == furthest["workflow_node_id"]
    assert execution_head["checkpoint_id"] == checkpoint["checkpoint_id"]
    assert execution_head["layer_completion"] is True


def test_opening_advances_five_durable_layers_before_book_run_admission() -> None:
    fixture = build_workflow_fixture(
        target_chapter_count=12,
        arc_logical_keys=("arc:central", "arc:relationship"),
    )
    admission = fixture.admit()
    opening_run_id = str(admission.opening_run_id)

    initial = fixture.progress(opening_run_id)
    assert initial["compatibility_mode"] == "NODED_WORKFLOW"
    assert as_mapping(initial["current_layer"])["node_kind"] == "BOOK_PLAN"
    assert [as_mapping(node)["lifecycle"] for node in initial["nodes"]] == [
        "QUEUED",
        "PENDING",
        "PENDING",
        "PENDING",
        "PENDING",
    ]
    assert as_mapping(initial["reviewable_artifact"])["status"] != "AVAILABLE"
    assert as_mapping(initial["persistent_checkpoint"])["status"] != "AVAILABLE"
    assert (
        fixture.opening.require(opening_run_id)["execution_contract_version"]
        == BOOK_OPENING_WORKFLOW_EXECUTION_CONTRACT_VERSION
    )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT opening.workflow_contract_version,
                   opening.execution_contract_version,
                   job.job_kind,job.runtime_group,
                   COUNT(*) FILTER (
                       WHERE opening.execution_contract_version=
                                 'book-opening-execution-v2'
                         AND job.job_kind='BOOK_OPENING_EXECUTE'
                         AND job.runtime_group='book_opening'
                   ) OVER () AS legacy_worker_visible
            FROM authority_book_opening_run AS opening
            JOIN authority_book_opening_execution AS execution
              ON execution.opening_execution_id=opening.current_execution_id
            JOIN authority_runtime_job AS job
              ON job.runtime_job_id=execution.runtime_job_id
            WHERE opening.opening_run_id=%s
            """,
            [opening_run_id],
        )
        persisted_identity = uow.cursor.fetchone()
    assert persisted_identity == (
        "book-opening-workflow-v1",
        "book-opening-execution-v3",
        BOOK_OPENING_WORKFLOW_JOB_KIND,
        BOOK_OPENING_WORKFLOW_RUNTIME_GROUP,
        0,
    )

    runtime_job_ids: list[str] = []
    checkpoint_sequences: list[int] = []
    expected_successor_job_id = str(admission.runtime_job_id)
    final_result: dict[str, object] | None = None
    for ordinal, expected_kind in enumerate(WORKFLOW_NODE_KINDS, start=1):
        claim = fixture.claim(f"book-opening-node-worker:{ordinal}")
        assert claim is not None
        assert claim.job_kind == BOOK_OPENING_WORKFLOW_JOB_KIND
        assert claim.runtime_group == BOOK_OPENING_WORKFLOW_RUNTIME_GROUP
        assert claim_node_kind(claim) == expected_kind
        assert claim.runtime_job_id == expected_successor_job_id
        assert claim.runtime_job_id not in runtime_job_ids
        runtime_job_ids.append(claim.runtime_job_id)

        result = as_mapping(fixture.execute(claim))
        assert set(result) == {
            "opening_run_id",
            "workflow_node_id",
            "node_kind",
            "node_key",
            "node_receipt_id",
            "lifecycle",
            "status",
            "replayed",
            "successor_runtime_job_id",
            "book_opening_result",
        }
        assert result["opening_run_id"] == opening_run_id
        assert result["workflow_node_id"] == claim.input_snapshot["workflow_node_id"]
        assert result["node_kind"] == expected_kind
        assert result["node_key"] == claim.input_snapshot["workflow_node_key"]
        assert result["node_receipt_id"]
        assert result["status"] == "SUCCEEDED"
        assert result["replayed"] is False
        job = fixture.runtime_jobs.get(claim.runtime_job_id)
        assert job["status"] == "SUCCEEDED"
        assert job["attempt_count"] == 1

        progress = fixture.progress(opening_run_id)
        _assert_reviewable_checkpoint(progress, node_kind=expected_kind)
        checkpoint_sequences.append(
            int(as_mapping(progress["persistent_checkpoint"])["checkpoint_sequence"])
        )
        lifecycles = [as_mapping(node)["lifecycle"] for node in progress["nodes"]]
        assert lifecycles[:ordinal] == ["COMPLETE"] * ordinal
        if ordinal < len(WORKFLOW_NODE_KINDS):
            assert result["book_opening_result"] is None
            assert result["successor_runtime_job_id"]
            assert lifecycles[ordinal] == "QUEUED"
            assert lifecycles[ordinal + 1 :] == ["PENDING"] * (
                len(WORKFLOW_NODE_KINDS) - ordinal - 1
            )
            expected_successor_job_id = str(result["successor_runtime_job_id"])
        else:
            assert result["successor_runtime_job_id"] == ""
            final_result = as_mapping(result["book_opening_result"])

    assert len(runtime_job_ids) == 5
    assert checkpoint_sequences == sorted(set(checkpoint_sequences))
    assert fixture.claim("book-opening-node-worker:after-complete") is None
    assert fixture.opening.require(opening_run_id)["lifecycle"] == "COMPLETE"
    assert final_result is not None
    assert final_result["input_snapshot_id"]
    assert len(final_result["volume_portfolio_plan_versions"]) == 4
    assert (
        final_result["current_volume_plan_version"]
        == (final_result["volume_portfolio_plan_versions"][0])
    )
    assert len(final_result["arc_portfolio_plan_versions"]) == 2

    calls_before_book_run = tuple(fixture.binder.generator_calls)
    assert Counter(calls_before_book_run) == {
        "book_plan.generate": len(DEFAULT_SEARCH_DIRECTIVES),
        "volume_plan.generate": 4 * len(DEFAULT_SEARCH_DIRECTIVES),
        "arc_plan.generate": 2 * len(DEFAULT_SEARCH_DIRECTIVES),
    }

    book_run_id = fixture.start_book_run(str(final_result["input_snapshot_id"]))
    book_run = fixture.book_authority.require(book_run_id)
    assert book_run["input_snapshot_id"] == final_result["input_snapshot_id"]
    assert book_run["target_chapter_count"] == 12
    assert book_run["accepted_through_chapter"] == 0
    assert fixture.binder.generator_calls == list(calls_before_book_run)
    with (
        psycopg.connect(DATABASE_URL) as connection,
        pytest.raises(
            psycopg.errors.CheckViolation,
            match="BOOK_OPENING_RUN_TERMINAL_IMMUTABLE",
        ),
    ):
        connection.execute(
            "DELETE FROM authority_book_opening_run WHERE opening_run_id=%s",
            [opening_run_id],
        )


def test_committed_node_response_survives_a_terminal_heartbeat_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    late_heartbeat_errors: list[str] = []

    class CompletionHeartbeatGuard(LeaseHeartbeatGuard):
        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> bool:
            if exc is None:
                try:
                    self._renew()
                except KernelError as heartbeat_error:
                    late_heartbeat_errors.append(heartbeat_error.code)
                    self._failure = heartbeat_error
            return super().__exit__(exc_type, exc, traceback)

    monkeypatch.setattr(
        book_authority_worker, "LeaseHeartbeatGuard", CompletionHeartbeatGuard
    )
    fixture = build_workflow_fixture()
    admission = fixture.admit()
    claim = fixture.claim("opening-terminal-heartbeat-worker")
    assert claim is not None
    result = as_mapping(fixture.execute(claim))
    assert late_heartbeat_errors == ["RUNTIME_JOB_FENCE_STALE"]
    assert result["status"] == "SUCCEEDED"
    assert result["replayed"] is False
    job = fixture.runtime_jobs.get(claim.runtime_job_id)
    assert job["status"] == "SUCCEEDED"
    assert job["attempt_count"] == 1
    durable = fixture.opening.require_node_execution_result(
        opening_run_id=str(admission.opening_run_id),
        workflow_node_id=str(claim.input_snapshot["workflow_node_id"]),
        opening_execution_id=str(claim.input_snapshot["opening_execution_id"]),
        execution_generation=int(claim.input_snapshot["execution_generation"]),
    )
    assert durable == {**result, "replayed": True}
    _assert_reviewable_checkpoint(
        fixture.progress(admission.opening_run_id), node_kind="BOOK_PLAN"
    )


def test_parent_gate_exposes_only_one_claimable_layer_at_a_time() -> None:
    fixture = build_workflow_fixture()
    admission = fixture.admit()

    book_plan = fixture.claim("book-opening-parent-gate:book-plan")
    assert book_plan is not None
    assert claim_node_kind(book_plan) == "BOOK_PLAN"
    assert fixture.claim("book-opening-parent-gate:blocked-child") is None

    claimed = fixture.progress(admission.opening_run_id)
    assert [as_mapping(node)["lifecycle"] for node in claimed["nodes"]] == [
        "RUNNING",
        "PENDING",
        "PENDING",
        "PENDING",
        "PENDING",
    ]
    result = as_mapping(fixture.execute(book_plan))
    volume_portfolio = fixture.claim("book-opening-parent-gate:volume-portfolio")
    assert volume_portfolio is not None
    assert claim_node_kind(volume_portfolio) == "VOLUME_PORTFOLIO"
    assert volume_portfolio.runtime_job_id == result["successor_runtime_job_id"]
    assert volume_portfolio.runtime_job_id != book_plan.runtime_job_id
    assert fixture.claim("book-opening-parent-gate:blocked-grandchild") is None


def test_database_rejects_a_cross_version_workflow_runtime_identity() -> None:
    fixture = build_workflow_fixture()
    admission = fixture.admit()
    runtime_job_id = f"runtime-job:cross-version:{admission.opening_run_id}"
    with (
        AuthorityUnitOfWork(DATABASE_URL) as uow,
        pytest.raises(
            psycopg.errors.CheckViolation,
            match="BOOK_OPENING_RUNTIME_IDENTITY_INVALID",
        ),
    ):
        uow.cursor.execute(
            """
            INSERT INTO authority_runtime_job(
                runtime_job_id,job_kind,runtime_group,subject_kind,
                subject_id,project_id,dedupe_key,input_snapshot,input_hash,
                status,priority,max_attempts,lease_loss_policy
            ) VALUES (
                %s,'BOOK_OPENING_WORKFLOW_NODE_EXECUTE','book_opening',
                'BOOK_OPENING_RUN',%s,%s,%s,'{}'::jsonb,%s,
                'READY',100,1,'AUTHORITY_CONVERGENCE_REQUIRED'
            )
            """,
            [
                runtime_job_id,
                admission.opening_run_id,
                fixture.project_id,
                f"{admission.opening_run_id}:cross-version",
                "sha256:" + "0" * 64,
            ],
        )
        uow.commit()


def test_book_run_is_rejected_until_input_snapshot_layer_is_complete() -> None:
    fixture = build_workflow_fixture(target_chapter_count=12)
    admission = fixture.admit()

    for ordinal, expected_kind in enumerate(WORKFLOW_NODE_KINDS[:-1], start=1):
        claim = fixture.claim(f"book-opening-book-run-gate:{ordinal}")
        assert claim is not None
        assert claim_node_kind(claim) == expected_kind
        completed = as_mapping(fixture.execute(claim))
        assert completed["book_opening_result"] is None

    progress = fixture.progress(admission.opening_run_id)
    assert as_mapping(progress["current_layer"])["node_kind"] == "INPUT_SNAPSHOT"
    assert fixture.opening.require(admission.opening_run_id)["lifecycle"] != (
        "COMPLETE"
    )
    input_snapshot = fixture.claim("book-opening-book-run-gate:input-snapshot")
    assert input_snapshot is not None
    fault = OneShotFaultInjector(
        "after_workflow_node_payload",
        exception_factory=lambda point: SimulatedWorkflowProcessLoss(point),
    )
    fixture.opening.fault_injector = fault
    with pytest.raises(SimulatedWorkflowProcessLoss):
        fixture.execute(input_snapshot)
    assert fault.triggered is True
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT snapshot_id
            FROM authority_book_production_input_snapshot
            WHERE project_id=%s AND workspace_id=%s AND book_id=%s
            ORDER BY created_at DESC
            """,
            [fixture.project_id, fixture.workspace_id, fixture.book_id],
        )
        snapshots = tuple(str(row[0]) for row in uow.cursor.fetchall())
    assert len(snapshots) == 1
    with pytest.raises(KernelError) as incomplete:
        fixture.start_book_run(snapshots[0])
    assert incomplete.value.code == "BOOK_OPENING_WORKFLOW_COMPLETION_REQUIRED"

    fixture.opening.fault_injector = None
    final = as_mapping(fixture.execute(input_snapshot))
    opening_result = as_mapping(final["book_opening_result"])
    book_run_id = fixture.start_book_run(str(opening_result["input_snapshot_id"]))
    assert fixture.book_authority.require(book_run_id)["accepted_through_chapter"] == 0


@pytest.mark.parametrize(
    ("target_kind", "tamper", "expected_code"),
    (
        (
            "VOLUME_PORTFOLIO",
            lambda result: result.__setitem__(
                "target_chapters", int(result["target_chapters"]) + 1
            ),
            "BOOK_OPENING_VOLUME_PORTFOLIO_INVALID",
        ),
        (
            "CURRENT_VOLUME",
            lambda result: result.__setitem__(
                "current_volume_content_hash", "sha256:" + "0" * 64
            ),
            "BOOK_OPENING_WORKFLOW_PREDECESSOR_DRIFT",
        ),
        (
            "INITIAL_ARC_SCOPE",
            lambda result: result.__setitem__(
                "volume_portfolio_plan_version_ids",
                list(reversed(result["volume_portfolio_plan_version_ids"])),
            ),
            "BOOK_OPENING_WORKFLOW_PREDECESSOR_DRIFT",
        ),
    ),
)
def test_node_completion_rejects_forged_cross_layer_evidence(
    target_kind: str,
    tamper: object,
    expected_code: str,
) -> None:
    """The Authority handler must not trust the in-process node coordinator.

    This deliberately enters the command seam below the normal worker after
    producing legitimate inner Planning artifacts.  Forging only outer result
    metadata must fail before a node receipt/checkpoint or successor is written.
    """

    fixture = build_workflow_fixture(
        target_chapter_count=12,
        arc_logical_keys=("arc:central", "arc:relationship"),
    )
    admission = fixture.admit()
    opening_run_id = str(admission.opening_run_id)

    for ordinal, kind in enumerate(WORKFLOW_NODE_KINDS, start=1):
        claim = fixture.claim(f"book-opening-forged-result:{target_kind}:{ordinal}")
        assert claim is not None
        assert claim_node_kind(claim) == kind
        if kind != target_kind:
            fixture.execute(claim)
            continue

        run = fixture.opening.require(opening_run_id)
        node = fixture.opening._require_current_workflow_node(opening_run_id)
        request = fixture.opening._frozen_request(opening_run_id)
        fixture.opening._bind_running_execution(
            opening_run_id,
            expected_version=int(claim.input_snapshot["observed_version"]),
            runtime_claim=claim,
        )
        result = fixture.opening._execute_workflow_node_payload(
            request=request,
            node=node,
            principal=fixture.principal,
            opening_run_id=opening_run_id,
            runtime_claim=claim,
            execution_probe=None,
        )
        assert callable(tamper)
        tamper(result)
        with pytest.raises(KernelError) as forged:
            fixture.opening._control(
                run=dict(run),
                principal=fixture.principal,
                definition_name="book.opening.complete_node",
                idempotency_key=(f"{opening_run_id}:forged-node-result:{target_kind}"),
                payload={
                    "expected_version": int(claim.input_snapshot["observed_version"]),
                    "workflow_node_id": node.workflow_node_id,
                    "node_result": result,
                    "runtime_claim": fixture.opening._runtime_claim_payload(claim),
                },
            )
        assert forged.value.code == expected_code

        progress = fixture.progress(opening_run_id)
        target = next(
            as_mapping(item)
            for item in progress["nodes"]
            if as_mapping(item)["node_kind"] == target_kind
        )
        assert target["node_receipt_id"] == ""
        assert target["lifecycle"] != "COMPLETE"
        assert as_mapping(progress["current_layer"])["node_kind"] == target_kind
        break
