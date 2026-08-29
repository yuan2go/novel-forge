from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from novel_forge.modules.book_authority import opening as opening_module
from novel_forge.modules.book_authority import recovery as recovery_module
from novel_forge.modules.book_authority.opening import (
    OpenBookProductionRequest,
    PostgresBookOpeningApplication,
)
from novel_forge.modules.book_authority.recovery import (
    BOOK_OPENING_EXECUTION_CONTRACT_VERSION,
    PostgresBookOpeningRecoveryApplication,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime import GENERATOR_INPUT_ROLES


class _ReconciliationCursor:
    def __init__(self, *, fail_execution_insert: bool = False) -> None:
        self.fail_execution_insert = fail_execution_insert
        self.statements: list[str] = []
        self.parameters: list[list[Any]] = []
        self.rowcount = 0

    def execute(self, statement: str, parameters: list[Any]) -> None:
        normalized = " ".join(statement.split())
        self.statements.append(normalized)
        self.parameters.append(parameters)
        self.rowcount = 1
        if (
            self.fail_execution_insert
            and "INSERT INTO authority_book_opening_execution" in normalized
        ):
            raise RuntimeError("injected execution insert failure")


class _ReconciliationUow:
    instances: list["_ReconciliationUow"] = []
    fail_execution_insert = False

    def __init__(self, _database_url: str) -> None:
        self.cursor = _ReconciliationCursor(
            fail_execution_insert=self.fail_execution_insert
        )
        self.committed = False
        self.rolled_back = False
        self.instances.append(self)

    def __enter__(self) -> "_ReconciliationUow":
        return self

    def __exit__(self, exc_type: object, *_args: object) -> None:
        self.rolled_back = exc_type is not None and not self.committed

    def commit(self) -> None:
        self.committed = True


def _legacy_reconciliation_application(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[PostgresBookOpeningRecoveryApplication, dict[str, Any]]:
    run = {
        "opening_run_id": "opening:legacy",
        "project_id": "project:legacy",
        "workspace_id": "workspace:legacy",
        "book_id": "book:legacy",
        "root_operation_id": "operation:legacy",
        "lifecycle": "ADMITTED",
        "frozen_request": {},
        "frozen_request_digest": "sha256:" + "a" * 64,
        "version": 7,
        "execution_contract_version": "legacy-unbound",
        "current_execution_id": None,
        "current_execution_generation": None,
        "current_checkpoint_id": None,
        "current_checkpoint_sequence": 0,
        "current_checkpoint_hash": "",
        "recovery_state": "LEGACY_RECONCILIATION_REQUIRED",
        "budget_scope_id": "",
        "budget_scope_revision": 0,
        "budget_contract_state": "LEGACY_UNBOUND",
        "workflow_contract_version": "legacy-monolithic-v2",
        "current_workflow_node_id": None,
        "workflow_graph_revision": 0,
        "workflow_graph_hash": "",
    }
    receipt = {
        "recovery_receipt_id": "receipt:legacy",
        "receipt_kind": "LEGACY_EXECUTION_RECONCILIATION",
        "opening_run_id": "opening:legacy",
        "recovery_assessment_id": "assessment:legacy",
        "recovery_intent_id": "",
        "result": {"provider_invoked": False},
        "result_hash": "sha256:" + "b" * 64,
    }
    application = object.__new__(PostgresBookOpeningRecoveryApplication)
    application.database_url = "postgresql://unused"
    application.application_build_id = "book-opening-unit"
    application.commit_sha = "c" * 40
    application.runtime_jobs = SimpleNamespace()
    application.semantic_replacement = None
    application.fault_injector = None
    monkeypatch.setattr(recovery_module, "AuthorityUnitOfWork", _ReconciliationUow)
    monkeypatch.setattr(application, "_lock_opening", lambda *_args: None)
    monkeypatch.setattr(application, "_opening", lambda *_args, **_kwargs: run)
    monkeypatch.setattr(application, "_receipt_by_key", lambda *_args: None)
    monkeypatch.setattr(
        application,
        "_legacy_runtime_binding",
        lambda *_args, **_kwargs: {
            "runtime_job_id": "runtime-job:legacy",
            "input_hash": "sha256:" + "d" * 64,
            "attempt_id": "",
            "lease_id": "",
            "worker_id": "",
            "fencing_token": 0,
            "execution_lifecycle": "BOUND",
            "terminal_reason": {},
            "runtime_history_digest": "sha256:" + "e" * 64,
        },
    )
    monkeypatch.setattr(
        application,
        "_insert_assessment",
        lambda _uow, *, run, **_kwargs: (
            "assessment:legacy"
            if run["execution_contract_version"]
            == BOOK_OPENING_EXECUTION_CONTRACT_VERSION
            else pytest.fail("assessment observed the unadvanced execution contract")
        ),
    )
    monkeypatch.setattr(
        application,
        "_insert_receipt",
        lambda *_args, **_kwargs: receipt,
    )
    monkeypatch.setattr(application, "_record_event", lambda *_args: None)
    return application, run


def test_legacy_reconciliation_advances_run_contract_before_execution_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ReconciliationUow.instances.clear()
    _ReconciliationUow.fail_execution_insert = False
    application, _run = _legacy_reconciliation_application(monkeypatch)

    result = application.reconcile_legacy_execution(
        "opening:legacy",
        idempotency_key="reconcile:legacy",
        principal=SimpleNamespace(require=lambda *_args: None),  # type: ignore[arg-type]
    )

    uow = _ReconciliationUow.instances[-1]
    contract_advance = next(
        index
        for index, statement in enumerate(uow.cursor.statements)
        if "UPDATE authority_book_opening_run" in statement
        and "SET execution_contract_version=%s" in statement
    )
    execution_insert = next(
        index
        for index, statement in enumerate(uow.cursor.statements)
        if "INSERT INTO authority_book_opening_execution" in statement
    )
    current_pointer = next(
        index
        for index, statement in enumerate(uow.cursor.statements)
        if "UPDATE authority_book_opening_run" in statement
        and "SET current_execution_id=%s" in statement
    )

    assert contract_advance < execution_insert < current_pointer
    assert uow.cursor.parameters[contract_advance][0] == (
        BOOK_OPENING_EXECUTION_CONTRACT_VERSION
    )
    assert uow.committed is True
    assert uow.rolled_back is False
    assert result.replayed is False


def test_legacy_reconciliation_rolls_back_contract_advance_when_insert_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ReconciliationUow.instances.clear()
    _ReconciliationUow.fail_execution_insert = True
    application, _run = _legacy_reconciliation_application(monkeypatch)

    with pytest.raises(RuntimeError, match="injected execution insert failure"):
        application.reconcile_legacy_execution(
            "opening:legacy",
            idempotency_key="reconcile:legacy",
            principal=SimpleNamespace(require=lambda *_args: None),  # type: ignore[arg-type]
        )

    uow = _ReconciliationUow.instances[-1]
    assert any(
        "SET execution_contract_version=%s" in statement
        for statement in uow.cursor.statements
    )
    assert not any(
        "SET current_execution_id=%s" in statement
        for statement in uow.cursor.statements
    )
    assert uow.committed is False
    assert uow.rolled_back is True


def _control_test_application(monkeypatch: pytest.MonkeyPatch):
    application = object.__new__(PostgresBookOpeningApplication)
    application.database_url = "postgresql://unused"
    application.application_build_id = "book-opening-unit"
    application.commit_sha = "f" * 40
    application.fault_injector = None
    monkeypatch.setattr(application, "_register_definitions", lambda: None)
    return application


def _control_test_run() -> dict[str, Any]:
    return {
        "opening_run_id": "opening:legacy-control",
        "project_id": "project:legacy-control",
        "workspace_id": "workspace:legacy-control",
        "book_id": "book:legacy-control",
        "root_operation_id": "operation:legacy-control",
        "workflow_contract_version": "legacy-monolithic-v2",
        "execution_contract_version": BOOK_OPENING_EXECUTION_CONTRACT_VERSION,
        "current_execution_id": "book-opening-execution:legacy-control",
        "current_execution_generation": 1,
    }


def test_abort_control_uses_current_authority_lineage_without_planning_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _control_test_application(monkeypatch)
    monkeypatch.setattr(
        application,
        "_frozen_request",
        lambda *_args: pytest.fail("abort must not rebuild frozen Planning inputs"),
    )
    monkeypatch.setattr(
        application,
        "_opening_input_assets",
        lambda *_args: pytest.fail("abort must not resolve Planning assets"),
    )
    captured: dict[str, Any] = {}

    def execute(_database_url: str, command: dict[str, Any], **_kwargs: object):
        captured.update(command)
        return {"opening_run_id": command["input"]["opening_run_id"]}

    monkeypatch.setattr(opening_module, "execute_transaction_command", execute)

    application._control(  # noqa: SLF001
        run=_control_test_run(),
        principal=SimpleNamespace(principal_id="operator:legacy"),  # type: ignore[arg-type]
        definition_name="book.opening.abort",
        idempotency_key="opening:legacy-control:abort:7",
        payload={"expected_version": 7},
    )

    assert captured["input_assets"] == []
    assert captured["input"] == {
        "project_id": "project:legacy-control",
        "book_id": "book:legacy-control",
        "opening_run_id": "opening:legacy-control",
        "expected_version": 7,
    }
    assert captured["causation_operation_id"] == "operation:legacy-control"


@pytest.mark.parametrize(
    "definition_name",
    ["book.opening.complete", "book.opening.complete_node"],
)
def test_input_consuming_control_commands_still_require_frozen_planning_assets(
    monkeypatch: pytest.MonkeyPatch,
    definition_name: str,
) -> None:
    application = _control_test_application(monkeypatch)
    frozen_request = object()
    planning_assets = [
        {
            "asset_version_id": "asset-version:planning-input",
            "content_hash": "sha256:" + "1" * 64,
        }
    ]
    calls: list[str] = []
    monkeypatch.setattr(
        application,
        "_frozen_request",
        lambda opening_run_id: (
            calls.append(f"frozen:{opening_run_id}") or frozen_request
        ),
    )
    monkeypatch.setattr(
        application,
        "_opening_input_assets",
        lambda request: calls.append("assets") or planning_assets,
    )
    captured: dict[str, Any] = {}

    def execute(_database_url: str, command: dict[str, Any], **_kwargs: object):
        captured.update(command)
        return {"opening_run_id": command["input"]["opening_run_id"]}

    monkeypatch.setattr(opening_module, "execute_transaction_command", execute)

    application._control(  # noqa: SLF001
        run=_control_test_run(),
        principal=SimpleNamespace(principal_id="worker:opening"),  # type: ignore[arg-type]
        definition_name=definition_name,
        idempotency_key=f"opening:legacy-control:{definition_name}",
        payload={"expected_version": 7},
    )

    assert calls == ["frozen:opening:legacy-control", "assets"]
    assert captured["input_assets"] == planning_assets


def test_book_opening_rejects_underfunded_topology_before_any_provider_call() -> None:
    provider_calls: list[object] = []
    opening = PostgresBookOpeningApplication(
        "postgresql://unused",
        narrative_search=SimpleNamespace(
            explore=lambda request, **_kwargs: provider_calls.append(request)
        ),
        input_resolver=SimpleNamespace(),
        application_build_id="book-opening-unit",
        commit_sha="a" * 40,
        provider_budget_policy={
            "execution_mode": "PROVIDER_ALLOWED",
            "provider_call_limit": 17,
            "token_limit": 4_800_000,
            "cost_limit_usd": "96",
            "per_call_token_limit": 100_000,
            "per_call_cost_limit_usd": "2",
        },
    )

    with pytest.raises(KernelError, match="BOOK_OPENING_TOPOLOGY_BUDGET_INSUFFICIENT"):
        opening._topology_budget_for_request(  # type: ignore[arg-type]
            SimpleNamespace(arc_logical_keys=("arc:main",))
        )

    assert provider_calls == []


def test_book_opening_drives_foundation_through_searched_plan_baseline() -> None:
    search_requests: list[object] = []

    def explore(  # type: ignore[no-untyped-def]
        request, *, principal, activate_selected, execution_probe=None
    ):
        if execution_probe is not None:
            execution_probe()
        search_requests.append(request)
        generation = request.generation
        return SimpleNamespace(
            search_id=f"search:{generation.generator_operation_name}:{generation.logical_key}",
            selected_generation=SimpleNamespace(
                candidate_asset_version_id=(
                    f"active:{generation.generator_operation_name}:{generation.logical_key}"
                )
            ),
        )

    resolved: list[object] = []
    opening = PostgresBookOpeningApplication(
        "postgresql://unused",
        narrative_search=SimpleNamespace(explore=explore),
        input_resolver=SimpleNamespace(
            resolve=lambda command, *, principal: (
                resolved.append(command)
                or SimpleNamespace(snapshot_id="snapshot:ready")
            )
        ),
        application_build_id="book-opening-unit",
        commit_sha="a" * 40,
    )
    opening._require_qualified_foundation = (  # type: ignore[method-assign]
        lambda _request: "foundation:v5"
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
    generic = {
        role: (
            "foundation:v5"
            if role == "book_design"
            else "opening-profile"
            if role == "production_profile"
            else "story-state:initial"
            if role == "story_state"
            else "canon:initial"
            if role == "canon_snapshot"
            else f"asset:{role}"
        )
        for role in opening_roles
    }
    request = OpenBookProductionRequest(
        project_id="project:1",
        workspace_id="workspace:1",
        book_id="book:1",
        actor_id="operator:1",
        expected_book_version=2,
        production_profile="opening-profile",
        planning_input_versions=generic,
        arc_logical_keys=("arc:plot", "arc:relationship", "arc:mystery"),
        idempotency_key="book:1:opening",
        trace_id="trace:opening",
        correlation_id="correlation:opening",
        initial_story_state_version="story-state:initial",
        initial_canon_snapshot_version="canon:initial",
    )
    principal = SimpleNamespace(require=lambda _permission, _project_id: None)

    result = opening._open_frozen(request, principal=principal)

    assert [item.generation.generator_operation_name for item in search_requests] == [
        "book_plan.generate",
        "volume_plan.generate",
        "arc_plan.generate",
        "arc_plan.generate",
        "arc_plan.generate",
    ]
    assert all(
        item.generation.auto_approve_low_risk is False for item in search_requests
    )
    assert search_requests[1].generation.parent_version_id == result.book_plan_version
    assert all(item.generation.parent_version_id == "" for item in search_requests[2:])
    assert len(result.arc_plan_versions) == 3
    assert result.input_snapshot.snapshot_id == "snapshot:ready"
    assert (
        dict(resolved[0].role_asset_version_overrides)["initial_story_state_version"]
        == "story-state:initial"
    )


def test_book_opening_rejects_missing_initial_accepted_boundary() -> None:
    with pytest.raises(ValueError, match="initial accepted Story State"):
        OpenBookProductionRequest(
            project_id="project:1",
            workspace_id="workspace:1",
            book_id="book:1",
            actor_id="operator:1",
            expected_book_version=1,
            production_profile="opening-profile",
            planning_input_versions={
                "book_design": "foundation:v5",
                "production_profile": "opening-profile",
                "story_state": "",
                "canon_snapshot": "",
            },
            arc_logical_keys=("arc:plot",),
            idempotency_key="book:1:opening",
            trace_id="trace:opening",
            correlation_id="correlation:opening",
        )
