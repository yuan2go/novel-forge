from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
import novel_forge.modules.story_design_authority.evaluation_execution as evaluation_execution
from novel_forge.modules.story_design_authority.evaluation_execution import (
    PostgresNarrativeEvaluationExecutionContractBinder,
)
from novel_forge.modules.story_design_authority.evaluation_runtime import (
    NarrativeSemanticEvaluationApplication,
    _evaluation_command_payload_matches,
)
from novel_forge.modules.story_design_authority.replacement_gate import (
    assert_narrative_replacement_execution_gate_in_uow,
)


class _Cursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows
        self.statements: list[str] = []

    def execute(self, sql: str, parameters: list[Any]) -> None:
        assert sql.count("%s") == len(parameters)
        self.statements.append(sql)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.rows.pop(0) if self.rows else None


def _lineage_row(
    generation: int,
    *,
    recovery_intent_id: str = "",
    head_current: bool = True,
    opening_binding: dict[str, Any] | None = None,
    formation_recovery_ref: str | None = None,
) -> tuple[Any, ...]:
    return (
        generation,
        recovery_intent_id or None,
        f"evaluation:generation-{generation}",
        "book:test",
        head_current,
        "operation:planning-generation",
        "project:test",
        dict(opening_binding or {}),
        "asset:candidate",
        "sha256:" + "a" * 64,
        (f"evaluation:generation-{generation - 1}" if generation > 1 else None),
        (generation - 1 if generation > 1 else None),
        (f"operation:generation-{generation - 1}" if generation > 1 else None),
        True,
        True,
        True,
        formation_recovery_ref,
    )


def _opening_binding() -> dict[str, Any]:
    return {
        "opening_run_id": "opening:test",
        "opening_execution_id": "opening-execution:1",
        "opening_execution_generation": 1,
        "runtime_job_id": "runtime-job:1",
        "runtime_attempt_id": "runtime-attempt:1",
        "runtime_lease_id": "runtime-lease:1",
        "runtime_worker_id": "opening-worker:1",
        "runtime_fencing_token": 1,
    }


def test_evaluation_payload_freezes_opening_fence_without_poisoning_legacy_unbound() -> (
    None
):
    legacy = {
        "project_id": "project:test",
        "input_asset_version_ids": ["asset:candidate"],
        "payload": {"candidate_asset_version_id": "asset:candidate"},
    }
    ordinary = {
        **legacy,
        "payload": {
            **legacy["payload"],
            "opening_execution_binding": {},
        },
    }
    opening_bound = {
        **legacy,
        "payload": {
            **legacy["payload"],
            "opening_execution_binding": _opening_binding(),
        },
    }

    assert _evaluation_command_payload_matches(legacy, ordinary)
    assert not _evaluation_command_payload_matches(legacy, opening_bound)
    assert _evaluation_command_payload_matches(opening_bound, opening_bound)


class _ReleaseCursor:
    def __init__(self, operation_status: str) -> None:
        self.operation_status = operation_status
        self.current: tuple[Any, ...] | None = None

    def execute(self, sql: str, _parameters: list[Any]) -> None:
        if "pg_advisory_xact_lock" in sql:
            self.current = None
        elif "SELECT evaluation.generation,evaluation.recovery_intent_id" in sql:
            self.current = _lineage_row(2, recovery_intent_id="recovery-intent:1")
        elif "FROM authority_book_opening_run AS opening" in sql:
            self.current = (True,)
        elif "FROM authority_narrative_evaluation_execution_head AS head" in sql:
            self.current = (
                "evaluation:generation-2",
                "project:test",
                "book:test",
                "asset:candidate",
                "sha256:" + "a" * 64,
                2,
                "evaluation:generation-1",
                1,
                "operation:generation-1",
                "recovery-intent:1",
                "operation:generation-2",
                "book:narrative-semantic-evaluation",
                "idempotency:generation-2",
                "concurrency:generation-2",
                "ADMITTED",
                {},
                0,
                1,
                {"payload": {}},
                [],
                "workspace:test",
                "evaluator:test",
                self.operation_status,
                0,
            )
        elif (
            "FROM authority_narrative_evaluation_execution AS execution" in sql
            and "execution.operation_id=%s" in sql
        ):
            self.current = (
                "evaluation:generation-2",
                "project:test",
                "book:test",
                "asset:candidate",
                "sha256:" + "a" * 64,
                2,
                "evaluation:generation-1",
                1,
                "operation:generation-1",
                "recovery-intent:1",
                "operation:generation-2",
                "book:narrative-semantic-evaluation",
                "idempotency:generation-2",
                "concurrency:generation-2",
                "ADMITTED",
                {},
                0,
                self.operation_status,
                {"payload": {}},
                [],
                "workspace:test",
                "evaluator:test",
            )
        elif "SELECT generation,recovery_intent_id" in sql:
            self.current = (2, "recovery-intent:1")
        elif "authority_narrative_replacement_gate_is_open" in sql:
            self.current = (True,)
        else:
            raise AssertionError(sql)

    def fetchone(self) -> tuple[Any, ...] | None:
        current = self.current
        self.current = None
        return current


class _ReleaseLifecycleRepository:
    def __init__(self) -> None:
        self.transition: dict[str, Any] | None = None

    def compare_and_set(self, command: dict[str, Any]) -> dict[str, Any]:
        self.transition = command
        return {
            "operation_id": command["operation_id"],
            "status": command["target_status"],
            "version": command["expected_version"] + 1,
        }


class _ReleaseEvidenceRepository:
    def record_operation_transition(self, _event: dict[str, Any]) -> None:
        return None


def test_generation_one_execution_does_not_depend_on_book_opening_gate() -> None:
    cursor = _Cursor([_lineage_row(1), (False,)])
    uow = SimpleNamespace(cursor=cursor)

    result = assert_narrative_replacement_execution_gate_in_uow(
        uow,
        operation_id="operation:generation-1",
        project_id="project:test",
    )

    assert result == {
        "operation_id": "operation:generation-1",
        "project_id": "project:test",
        "generation": 1,
        "replacement": False,
        "gate_open": True,
    }
    assert len(cursor.statements) == 2
    assert "authority_book_opening_run" not in cursor.statements[0]
    assert "design_state.source_kind='OPERATOR_AUTHORED'" in cursor.statements[0]
    assert "story_design.creative_foundation.author" in cursor.statements[0]
    assert "FROM authority_runtime_job AS job" in cursor.statements[1]
    assert "JOIN authority_book_opening" not in cursor.statements[1]


def test_missing_semantic_execution_lineage_fails_closed() -> None:
    cursor = _Cursor([])
    uow = SimpleNamespace(cursor=cursor)

    with pytest.raises(KernelError) as rejected:
        assert_narrative_replacement_execution_gate_in_uow(
            uow,
            operation_id="operation:missing",
            project_id="project:test",
        )

    assert rejected.value.code == "NARRATIVE_EVALUATION_EXECUTION_NOT_FOUND"


@pytest.mark.parametrize("live", [False, True])
def test_formation_continuation_requires_current_worker_fence(live):
    cursor = _Cursor([_lineage_row(2, formation_recovery_ref="formation-recovery:test"),
                      (live,)])
    uow = SimpleNamespace(cursor=cursor)
    if live:
        result = assert_narrative_replacement_execution_gate_in_uow(uow, operation_id="operation:generation-2", project_id="project:test")
        assert result["replacement"] and result["gate_open"]
        assert result["formation_recovery_ref"] == "formation-recovery:test"
    else:
        with pytest.raises(KernelError, match="NARRATIVE_EVALUATION_FORMATION_GATE_CLOSED"):
            assert_narrative_replacement_execution_gate_in_uow(uow, operation_id="operation:generation-2", project_id="project:test")


@pytest.mark.parametrize("error_code,effect_exists,expected_error", [
    ("PROGRAMMING_BUG", False, None),
    ("NARRATIVE_EVALUATION_INPUT_INVALID", False, None),
    ("NARRATIVE_EVALUATION_PROVIDER_CONTEXT_INVALID", True, "NARRATIVE_EVALUATION_EXTERNAL_EFFECT_RECONCILIATION_REQUIRED"),
])
def test_formation_continuation_does_not_generalize_preflight_retries(error_code, effect_exists, expected_error):
    from novel_forge.modules.story_design_authority.formation_evaluation_recovery import try_admit_formation_continuation

    cursor = _Cursor([("attempt:test", error_code, "a" * 40, "2026-09-14"), (effect_exists,)])
    command = SimpleNamespace(generator_operation_name="book_design.propose", actor_id="evaluator:test")
    current = {"operation_status": "FAILED_FINAL", "command_payload": {"payload": {}},
               "recovery_intent_id": None, "operation_actor_id": command.actor_id, "operation_id": "operation:failed"}
    if expected_error:
        with pytest.raises(KernelError, match=expected_error):
            try_admit_formation_continuation(None, SimpleNamespace(cursor=cursor), command=command, admission_command={}, current=current)
    else:
        assert try_admit_formation_continuation(None, SimpleNamespace(cursor=cursor), command=command, admission_command={}, current=current) is None


def test_non_current_semantic_execution_lineage_fails_closed() -> None:
    cursor = _Cursor([_lineage_row(1, head_current=False)])
    uow = SimpleNamespace(cursor=cursor)

    with pytest.raises(KernelError) as rejected:
        assert_narrative_replacement_execution_gate_in_uow(
            uow,
            operation_id="operation:generation-1",
            project_id="project:test",
        )

    assert rejected.value.code == (
        "NARRATIVE_EVALUATION_REPLACEMENT_GATE_IDENTITY_INVALID"
    )


@pytest.mark.parametrize("coherence_index", (13, 14, 15))
def test_operation_payload_lineage_drift_fails_closed(
    coherence_index: int,
) -> None:
    lineage = list(_lineage_row(1))
    lineage[coherence_index] = False
    cursor = _Cursor([tuple(lineage)])

    with pytest.raises(KernelError) as rejected:
        assert_narrative_replacement_execution_gate_in_uow(
            SimpleNamespace(cursor=cursor),
            operation_id="operation:generation-1",
            project_id="project:test",
        )

    assert rejected.value.code == (
        "NARRATIVE_EVALUATION_REPLACEMENT_GATE_IDENTITY_INVALID"
    )


def test_replacement_predecessor_lineage_is_required() -> None:
    lineage = list(_lineage_row(2, recovery_intent_id="recovery-intent:1"))
    lineage[10:13] = [None, None, None]
    cursor = _Cursor([tuple(lineage)])

    with pytest.raises(KernelError) as rejected:
        assert_narrative_replacement_execution_gate_in_uow(
            SimpleNamespace(cursor=cursor),
            operation_id="operation:generation-2",
            project_id="project:test",
        )

    assert rejected.value.code == (
        "NARRATIVE_EVALUATION_REPLACEMENT_GATE_IDENTITY_INVALID"
    )


def test_generation_one_cannot_carry_recovery_intent_lineage() -> None:
    cursor = _Cursor([_lineage_row(1, recovery_intent_id="recovery-intent:corrupt")])

    with pytest.raises(KernelError) as rejected:
        assert_narrative_replacement_execution_gate_in_uow(
            SimpleNamespace(cursor=cursor),
            operation_id="operation:generation-1",
            project_id="project:test",
        )

    assert rejected.value.code == (
        "NARRATIVE_EVALUATION_REPLACEMENT_GATE_IDENTITY_INVALID"
    )


def test_malformed_opening_binding_cannot_be_treated_as_non_opening() -> None:
    lineage = list(_lineage_row(1))
    lineage[7] = ["not", "an", "object"]
    cursor = _Cursor([tuple(lineage)])
    uow = SimpleNamespace(cursor=cursor)

    with pytest.raises(KernelError) as rejected:
        assert_narrative_replacement_execution_gate_in_uow(
            uow,
            operation_id="operation:generation-1",
            project_id="project:test",
        )

    assert rejected.value.code == "NARRATIVE_EVALUATION_OPENING_BINDING_INVALID"


def test_book_opening_bound_generation_one_uses_exact_live_fence() -> None:
    cursor = _Cursor([_lineage_row(1, opening_binding=_opening_binding()), (True,)])
    uow = SimpleNamespace(cursor=cursor)

    result = assert_narrative_replacement_execution_gate_in_uow(
        uow,
        operation_id="operation:generation-1",
        project_id="project:test",
    )

    assert result["gate_open"] is True
    assert len(cursor.statements) == 2
    assert "authority_book_opening_run" in cursor.statements[1]
    assert (
        "job.lease_loss_policy='AUTHORITY_CONVERGENCE_REQUIRED'"
        in (cursor.statements[1])
    )
    assert "job.max_attempts=1" in cursor.statements[1]
    assert "lease.lease_expires_at>clock_timestamp()" in cursor.statements[1]


def test_book_opening_bound_generation_one_rejects_lost_lease() -> None:
    cursor = _Cursor(
        [_lineage_row(1, opening_binding=_opening_binding()), (False,), (False,)]
    )
    uow = SimpleNamespace(cursor=cursor)

    with pytest.raises(KernelError) as rejected:
        assert_narrative_replacement_execution_gate_in_uow(
            uow,
            operation_id="operation:generation-1",
            project_id="project:test",
        )

    assert rejected.value.code == (
        "NARRATIVE_EVALUATION_BOOK_OPENING_EXECUTION_GATE_CLOSED"
    )


def test_generation_one_can_resume_only_from_exact_recovery_assessment() -> None:
    cursor = _Cursor(
        [_lineage_row(1, opening_binding=_opening_binding()), (False,), (True,)]
    )
    uow = SimpleNamespace(cursor=cursor)

    result = assert_narrative_replacement_execution_gate_in_uow(
        uow,
        operation_id="operation:generation-1",
        project_id="project:test",
    )

    assert result["gate_open"] is True
    assert len(cursor.statements) == 3
    assert "RESUME_CURRENT" in cursor.statements[2]


def test_legacy_unbound_generation_one_uses_its_durable_recovery_binding() -> None:
    cursor = _Cursor([_lineage_row(1), (True,), (True,)])
    uow = SimpleNamespace(cursor=cursor)

    result = assert_narrative_replacement_execution_gate_in_uow(
        uow,
        operation_id="operation:generation-1",
        project_id="project:test",
    )

    assert result["gate_open"] is True
    assert len(cursor.statements) == 3
    assert "FROM authority_runtime_job AS job" in cursor.statements[1]
    assert "JOIN authority_book_opening" not in cursor.statements[1]
    assert "RESUME_CURRENT" in cursor.statements[2]


def test_legacy_unbound_generation_one_rejects_stale_recovery_fence() -> None:
    cursor = _Cursor([_lineage_row(1), (True,), (False,)])

    with pytest.raises(KernelError) as rejected:
        assert_narrative_replacement_execution_gate_in_uow(
            SimpleNamespace(cursor=cursor),
            operation_id="operation:generation-1",
            project_id="project:test",
        )

    assert rejected.value.code == (
        "NARRATIVE_EVALUATION_BOOK_OPENING_EXECUTION_GATE_CLOSED"
    )


def test_replacement_execution_uses_the_database_derived_gate() -> None:
    cursor = _Cursor([_lineage_row(2, recovery_intent_id="recovery-intent:1"), (True,)])
    uow = SimpleNamespace(cursor=cursor)

    result = assert_narrative_replacement_execution_gate_in_uow(
        uow,
        operation_id="operation:generation-2",
        project_id="project:test",
    )

    assert result == {
        "operation_id": "operation:generation-2",
        "project_id": "project:test",
        "generation": 2,
        "replacement": True,
        "gate_open": True,
    }
    assert len(cursor.statements) == 2
    assert "authority_book_opening_recovery_assessment" in cursor.statements[1]
    assert "assessment.assessment_kind='RECOVERY'" in cursor.statements[1]
    assert "receipt.recovery_assessment_id" in cursor.statements[1]
    assert "assessment.disposition NOT IN" in cursor.statements[1]
    assert "assessment.opening_execution_id" in cursor.statements[1]
    assert "opening_execution.predecessor_execution_id" in cursor.statements[1]
    assert "recovery_intent.predecessor_execution_id=%s" not in cursor.statements[1]
    assert "NEW_REPLACEMENT" in cursor.statements[1]
    assert "RESUME_CURRENT" in cursor.statements[1]
    assert "replacement_evaluation_operation_id" in cursor.statements[1]
    assert "candidate_asset_version_id" in cursor.statements[1]
    assert "lease.lease_expires_at>clock_timestamp()" in cursor.statements[1]


def test_replacement_execution_fails_closed_when_owner_chain_is_not_live() -> None:
    cursor = _Cursor(
        [_lineage_row(2, recovery_intent_id="recovery-intent:1"), (False,)]
    )
    uow = SimpleNamespace(cursor=cursor)

    with pytest.raises(KernelError) as rejected:
        assert_narrative_replacement_execution_gate_in_uow(
            uow,
            operation_id="operation:generation-2",
            project_id="project:test",
        )

    assert rejected.value.code == (
        "NARRATIVE_EVALUATION_REPLACEMENT_EXECUTION_GATE_CLOSED"
    )


def test_semantic_binder_rechecks_the_gate_immediately_before_provider_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    def assert_gate(
        database_url: str,
        *,
        operation_id: str,
        project_id: str,
    ) -> dict[str, Any]:
        captured.update(
            database_url=database_url,
            operation_id=operation_id,
            project_id=project_id,
        )
        return {"gate_open": True}

    monkeypatch.setattr(
        evaluation_execution,
        "assert_narrative_replacement_execution_gate",
        assert_gate,
        raising=False,
    )
    binder = object.__new__(PostgresNarrativeEvaluationExecutionContractBinder)
    binder.database_url = "postgresql://authority"

    binder.assert_before_provider_send(
        operation_id="operation:generation-2",
        project_id="project:test",
    )

    assert captured == {
        "database_url": "postgresql://authority",
        "operation_id": "operation:generation-2",
        "project_id": "project:test",
    }


def test_story_design_release_transitions_the_current_replacement_to_ready() -> None:
    cursor = _ReleaseCursor("ADMITTED")
    lifecycle = _ReleaseLifecycleRepository()
    uow = SimpleNamespace(
        cursor=cursor,
        repositories=SimpleNamespace(
            operation_lifecycle=lifecycle,
            runtime_evidence=_ReleaseEvidenceRepository(),
        ),
    )
    application = object.__new__(NarrativeSemanticEvaluationApplication)

    released = application.release_replacement_in_uow(
        uow,
        operation_id="operation:generation-2",
        recovery_intent_id="recovery-intent:1",
        actor_id="book-opening-authority",
        trace_id="trace:test",
        correlation_id="correlation:test",
        causation_id="opening-execution:generation-2",
    )

    assert released == {
        "evaluation_execution_id": "evaluation:generation-2",
        "generation": 2,
        "operation_id": "operation:generation-2",
        "operation_status": "READY",
        "replayed": False,
    }
    assert lifecycle.transition is not None
    assert lifecycle.transition["expected_status"] == "ADMITTED"
    assert lifecycle.transition["target_status"] == "READY"


def test_story_design_release_treats_legacy_ready_replacement_as_replay() -> None:
    cursor = _ReleaseCursor("READY")
    lifecycle = _ReleaseLifecycleRepository()
    uow = SimpleNamespace(
        cursor=cursor,
        repositories=SimpleNamespace(
            operation_lifecycle=lifecycle,
            runtime_evidence=_ReleaseEvidenceRepository(),
        ),
    )
    application = object.__new__(NarrativeSemanticEvaluationApplication)

    released = application.release_replacement_in_uow(
        uow,
        operation_id="operation:generation-2",
        recovery_intent_id="recovery-intent:1",
        actor_id="book-opening-authority",
        trace_id="trace:test",
        correlation_id="correlation:test",
        causation_id="opening-execution:generation-2",
    )

    assert released["operation_status"] == "READY"
    assert released["replayed"] is True
    assert lifecycle.transition is None
