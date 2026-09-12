from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from time import monotonic, sleep
from typing import Any

import psycopg
import pytest

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.chapter_authority.definitions import chapter_operation_definitions
from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    acquire_attempt_lease,
    create_attempt,
    queue_attempt,
    start_attempt,
)
from novel_forge.modules.command_kernel.budget_runtime import (
    BudgetReservationRequest,
    reserve_provider_budget,
    reserve_provider_budget_in_uow,
    resolve_provider_budget_failure,
    settle_provider_budget,
)
from novel_forge.modules.command_kernel.creative_budget_runtime import (
    OWNER,
    configure_creative_budget,
    get_creative_budget,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_adapters import FakeDeterministicProvider
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    dispatch_external_effect,
    plan_external_effect,
)
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.modules.command_kernel.runtime import OperationTransitionCommand, transition_operation
from novel_forge.modules.source_import.definitions import source_import_definitions
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    seed_authority_project_book,
    transaction,
)


BUILD_ID = "creative-budget-pg-fixture"
COMMIT_SHA = "6b837069ab74996d434e8870edad8d6f30d1ce25"
PHASE_FIELDS = {
    "SOURCE": "source_allocation",
    "CREATION": "creation_allocation",
    "REPAIR": "repair_allocation",
}


class BudgetFixture:
    """Native policy/Effect transactions with explicitly synthetic Provider observations."""

    def __init__(self, *, native_project_only: bool = False) -> None:
        self.projects = {arm: identifier("creative-budget-" + arm) for arm in ("A", "B")}
        self.books = {arm: "book:" + project for arm, project in self.projects.items()}
        self.workspaces = {arm: "workspace:" + project for arm, project in self.projects.items()}
        self.principal = Principal(
            principal_id="creative-budget-fixture-operator",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset({"book.authority.execute", "project.authority.execute", "book_design.authority.execute"}),
            project_scope=frozenset(self.projects.values()),
            authentication_source="integration-test-fixture",
        )
        for arm, project in self.projects.items():
            if native_project_only:
                from novel_forge.modules.project_authority import ProjectAuthorityApplication, ProjectAuthorityCommand
                ProjectAuthorityApplication(DATABASE_URL, application_build_id=BUILD_ID, commit_sha=COMMIT_SHA).execute(
                    ProjectAuthorityCommand(
                        definition_name="project_lifecycle.create", project_id=project,
                        workspace_id=self.workspaces[arm], actor_id=self.principal.principal_id,
                        idempotency_key=f"{project}:create", trace_id=f"trace:{project}",
                        correlation_id=project, payload={"title": "Native budget resume fixture " + arm},
                    ), principal=self.principal,
                )
            else:
                seed_authority_project_book(project_id=project, book_id=self.books[arm])
        arms = []
        for arm in ("A", "B"):
            source = 3 if arm == "A" else 0
            arms.append({
                "arm": arm, "project_id": self.projects[arm], "book_id": self.books[arm],
                "source_allocation": {"calls": source, "tokens": source * 1000},
                "creation_allocation": {"calls": 2, "tokens": 2000},
                "repair_allocation": {"calls": 1, "tokens": 1000},
                "project_total": {"calls": source + 3, "tokens": (source + 3) * 1000},
            })
        self.plan = {
            "contract_version": "creative-experiment-budget.v1",
            "experiment_id": identifier("creative-budget-experiment"),
            "accounting_basis": "ACCOUNT_ENTITLEMENT",
            "shared_total": {"calls": 9, "tokens": 9000},
            "arms": arms,
        }
        self.policies = {arm: self.policy(arm) for arm in ("A", "B")}
        definitions = (
            *source_import_definitions(application_build_id=BUILD_ID, commit_sha=COMMIT_SHA),
            *chapter_operation_definitions(
                application_build_id=BUILD_ID, commit_sha=COMMIT_SHA, model_effects_required=True,
            ),
        )
        self.definitions = {definition["name"]: definition for definition in definitions}
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            for definition in definitions:
                uow.repositories.definitions.register(definition)
            uow.commit()

    def policy(self, arm: str = "A", *, version: str = "fixture-grant-v1") -> dict[str, Any]:
        allocation = next(item for item in self.plan["arms"] if item["arm"] == arm)
        return {
            "policy_version": version,
            "comparison_budget": deepcopy(self.plan),
            "authorization": {
                "authorization_ref": f"fixture-only:{self.projects[arm]}:{version}",
                "evidence_hash": "sha256:" + "f" * 64,
                "project_id": self.projects[arm], "book_id": self.books[arm],
                "authorized_cumulative_caps": {
                    phase: deepcopy(allocation[field]) for phase, field in PHASE_FIELDS.items()
                },
            },
        }

    def configure(self, policy: dict[str, Any] | None = None, *, arm: str = "A", **overrides: Any) -> dict[str, Any]:
        selected = policy or self.policies[arm]
        result = configure_creative_budget(**{
            "database_url": DATABASE_URL, "policy": selected,
            "project_id": self.projects[arm], "workspace_id": self.workspaces[arm],
            "principal": self.principal, "application_build_id": BUILD_ID,
            "commit_sha": COMMIT_SHA, "idempotency_key": identifier("grant"),
            "trace_id": identifier("trace"), "correlation_id": identifier("correlation"),
            **overrides,
        })
        self.policies[arm] = deepcopy(selected)
        return result

    def effect(self, phase: str, *, arm: str = "A", book_id: str | None = None, scenario: str = "success", intended_use: str = "ABSTRACT_GENERATION") -> tuple[EffectCommandContext, str]:
        operation_name, capability, stage = {
            "SOURCE": ("source.import.mkaos.extract", "mkaos.knowledge.extract", "source.mkaos.extract"),
            "CREATION": ("chapter.draft.generate", "model.draft", "draft"),
            "REPAIR": ("chapter.revision.apply", "model.revision", "revision"),
        }[phase]
        definition = self.definitions[operation_name]
        project, workspace = self.projects[arm], self.workspaces[arm]
        if phase == "SOURCE":
            payload = {"project_id": project, "workspace_id": workspace, "payload": {
                "member_processing_id": identifier("fixture-processing"),
                "requested_manifest": {"intended_use": intended_use, "target_book_id": book_id or self.books[arm]},
            }}
        else:
            payload = {
                "chapter": 1, "book_id": book_id or self.books[arm],
                "chapter_plan_asset_version_id": "fixture-semantic-plan-not-executed",
                "chapter_plan_content_hash": "fixture-not-production-proof",
            }
        result = admit_command(DATABASE_URL, {
            "definition_name": operation_name, "definition_version": definition["definition_version"],
            "project_id": project, "workspace_id": workspace, "actor_id": self.principal.principal_id,
            "idempotency_scope": definition["idempotency_scope"], "idempotency_key": identifier("run-key"),
            "trace_id": identifier("trace"), "span_id": identifier("span"),
            "correlation_id": identifier("correlation"), "causation_id": "",
            "input": payload, "input_assets": [],
        }, context=AdmissionContext(
            actor_id=self.principal.principal_id,
            permissions=frozenset(definition["permissions"]),
            available_handlers=frozenset({definition["handler_key"]}),
            application_build_id=BUILD_ID, commit_sha=COMMIT_SHA,
        ))
        context = EffectCommandContext(
            operation_id=result["operation_id"], project_id=project,
            actor_id=self.principal.principal_id, trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        transition_operation(DATABASE_URL, OperationTransitionCommand(
            operation_id=context.operation_id, project_id=project, expected_version=0,
            expected_status="ADMITTED", target_status="READY", actor_id=context.actor_id,
            reason="bounded budget integration fixture", trace_id=context.trace_id,
            correlation_id=context.correlation_id, causation_id=context.operation_id,
        ))
        attempt = create_attempt(
            DATABASE_URL, operation_id=context.operation_id, project_id=project,
            max_attempts=2, trace_id=context.trace_id, correlation_id=context.correlation_id,
        )
        queue_attempt(DATABASE_URL, attempt_id=attempt["attempt_id"], project_id=project,
                      trace_id=context.trace_id, correlation_id=context.correlation_id)
        lease = acquire_attempt_lease(
            DATABASE_URL, attempt_id=attempt["attempt_id"], project_id=project,
            worker_id="creative-budget-fixture", lease_seconds=120,
            trace_id=context.trace_id, correlation_id=context.correlation_id,
        )
        start_attempt(DATABASE_URL, WorkerLeaseCommand(
            attempt_id=attempt["attempt_id"], project_id=project, worker_id="creative-budget-fixture",
            fencing_token=lease["fencing_token"], trace_id=context.trace_id,
            correlation_id=context.correlation_id,
        ))
        effect = plan_external_effect(
            DATABASE_URL, context, effect_type="model.invoke", provider="fake_deterministic_provider",
            capability=capability, stable_idempotency_key=identifier("effect"),
            request_payload={"stage": stage, "input": {}, "scenario": scenario, "fixture": True,
                             "_production_execution": {"attempt_id": attempt["attempt_id"]}},
            max_attempts=2, reversible=False, completion_policy="synchronous_final",
            model_id="fixture-model", request_timeout_seconds=30, reconciliation_mode="query",
        )
        return context, str(effect["external_effect_id"])

    def reserve(self, phase: str, tokens: int, *, arm: str = "A", effect: tuple[EffectCommandContext, str] | None = None, policy: dict[str, Any] | None = None) -> tuple[BudgetReservationRequest, dict[str, Any]]:
        context, effect_id = effect or self.effect(phase, arm=arm)
        request = BudgetReservationRequest(
            operation_id=context.operation_id, external_effect_id=effect_id,
            project_id=context.project_id, stable_idempotency_key="budget:" + effect_id,
            provider="fake_deterministic_provider", currency="UNKNOWN", estimated_amount=None,
            estimated_tokens=tokens, accounting_basis="ACCOUNT_ENTITLEMENT",
            cost_authorization_ref=(policy or self.policies[arm])["authorization"]["authorization_ref"],
            call_caps={"project_total": 100}, token_caps={"project_total": 100_000},
        )
        return request, reserve_provider_budget(DATABASE_URL, request)

    def usage(self, arm: str = "A") -> dict[str, Any]:
        return get_creative_budget(DATABASE_URL, self.projects[arm])["budget_usage"]


@pytest.fixture
def budget() -> BudgetFixture:
    ensure_migrated()
    return BudgetFixture()


def test_source_only_grant_and_unused_source_cannot_fund_creation_or_repair(budget: BudgetFixture) -> None:
    policy = budget.policy()
    caps = policy["authorization"]["authorized_cumulative_caps"]
    caps["CREATION"] = {"calls": 0, "tokens": 0}
    caps["REPAIR"] = {"calls": 0, "tokens": 0}
    budget.configure(policy)
    budget.reserve("SOURCE", 100)
    for phase in ("CREATION", "REPAIR"):
        with pytest.raises(KernelError, match="CREATIVE_BUDGET_EXHAUSTED"):
            budget.reserve(phase, 1)
    assert budget.usage()["creation_opportunity"] is None

    policy["policy_version"] = "fixture-grant-v2"
    caps["CREATION"] = {"calls": 1, "tokens": 500}
    caps["REPAIR"] = {"calls": 1, "tokens": 200}
    budget.configure(policy)
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_EXHAUSTED"):
        budget.reserve("CREATION", 501)
    budget.reserve("CREATION", 500)
    budget.reserve("REPAIR", 200)
    for phase in ("CREATION", "REPAIR"):
        with pytest.raises(KernelError, match="CREATIVE_BUDGET_EXHAUSTED"):
            budget.reserve(phase, 1)
    usage = budget.usage()
    assert {phase: value["conservative_tokens"] for phase, value in usage["phases"].items()} == {
        "SOURCE": 100, "CREATION": 500, "REPAIR": 200,
    }
    assert usage["project_total"]["calls_used_or_reserved"] == 3


def test_shared_usage_new_grants_and_run_keys_retain_exact_frozen_effect_scope(budget: BudgetFixture) -> None:
    budget.configure()
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_AUTHORIZATION_REQUIRED"):
        budget.reserve("CREATION", 100, arm="B")
    budget.configure(arm="B")
    old_policy = deepcopy(budget.policies["A"])
    old_request, first = budget.reserve("CREATION", 100)
    budget.reserve("CREATION", 100, arm="B")
    for arm in ("A", "B"):
        usage = budget.usage(arm)
        assert usage["project_total"]["conservative_tokens"] == 100
        assert usage["shared_total"]["conservative_tokens"] == 200
        assert usage["shared_total"]["calls_used_or_reserved"] == 2
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_EXHAUSTED"):
        budget.reserve("SOURCE", 1, arm="B")
    wrong_book = budget.effect("CREATION", book_id=budget.books["B"])
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_SCOPE_MISMATCH"):
        budget.reserve("CREATION", 1, effect=wrong_book)

    budget.configure(budget.policy(version="fixture-grant-v2"))
    assert reserve_provider_budget(DATABASE_URL, old_request)["replayed"] is True
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT evidence->'creative_experiment' FROM authority_budget_reservation WHERE reservation_id=%s", [first["reservation_id"]])
        proof = cursor.fetchone()[0]
        assert proof["policy_version"] == old_policy["policy_version"]
        assert proof["authorization"] == old_policy["authorization"]
        cursor.execute("SELECT policy_version FROM authority_runtime_policy_binding WHERE owner=%s AND project_id=%s AND subject_id=%s", [OWNER, old_request.project_id, "effect:" + old_request.external_effect_id])
        assert cursor.fetchone()[0] == old_policy["policy_version"]
    with pytest.raises(psycopg.errors.RaiseException, match="binding is immutable"):
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE authority_budget_reservation SET evidence=evidence - 'creative_experiment' WHERE reservation_id=%s", [first["reservation_id"]])
    budget.reserve("CREATION", 1900)
    budget.configure(budget.policy(version="fixture-grant-v3"))
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_EXHAUSTED"):
        budget.reserve("CREATION", 1)
    assert budget.usage()["phases"]["CREATION"]["conservative_tokens"] == 2000
    changed = budget.policy(version="fixture-reallocate")
    changed["comparison_budget"]["experiment_id"] = identifier("reset-experiment")
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_PLAN_IMMUTABLE"):
        budget.configure(changed)
    assert budget.usage()["shared_total"]["conservative_tokens"] == 2100


def test_unknown_usage_holds_estimate_and_measured_overrun_cannot_escape_phase(budget: BudgetFixture) -> None:
    policy = budget.policy()
    policy["authorization"]["authorized_cumulative_caps"]["CREATION"]["tokens"] = 1000
    budget.configure(policy)
    effect = budget.effect("CREATION", scenario="timeout_after")
    request, reservation = budget.reserve("CREATION", 600, effect=effect)
    context, effect_id = effect
    dispatch_external_effect(DATABASE_URL, context, effect_id=effect_id, worker_id="creative-budget-fixture", lease_seconds=30, adapter=FakeDeterministicProvider("timeout_after"))
    held = resolve_provider_budget_failure(DATABASE_URL, reservation_id=reservation["reservation_id"], project_id=context.project_id)
    assert held["status"] == "HELD_UNKNOWN"
    replay = reserve_provider_budget(DATABASE_URL, request)
    assert replay["replayed"] is True
    assert replay["execution_authorized"] is False
    usage = budget.usage()["phases"]["CREATION"]
    assert usage["conservative_tokens"] == usage["unmeasured_reserved_tokens"] == 600
    assert usage["recorded_actual_tokens"] == 0
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_EXHAUSTED"):
        budget.reserve("CREATION", 401)
    with pytest.raises(KernelError, match="BUDGET_ACTUAL_EXCEEDS_RESERVATION"):
        settle_provider_budget(
            DATABASE_URL, reservation_id=reservation["reservation_id"], project_id=context.project_id,
            actual_amount=None, actual_tokens=1100, evidence={
                "fixture": True, "real_model_call": False, "model_id": "fixture-model",
                "evidence_class": "SCRIPTED_PROVIDER_USAGE_FIXTURE",
                "token_accounting_precision": "APPLICATION_VISIBLE_UPPER_BOUND",
                "actual_token_source": "PROVIDER_USAGE_RECEIPT",
            },
        )
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT status,actual_tokens,budget_breach,evidence->>'token_cap_error_code' FROM authority_budget_reservation WHERE reservation_id=%s", [reservation["reservation_id"]])
        assert cursor.fetchone() == ("HELD_UNKNOWN", 1100, True, "CREATIVE_BUDGET_EXHAUSTED")
    usage = budget.usage()["phases"]["CREATION"]
    assert usage["conservative_tokens"] == usage["recorded_actual_tokens"] == 1100
    assert usage["unmeasured_reserved_tokens"] == 0
    assert usage["calls_used_or_reserved"] == 1
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_EXHAUSTED"):
        budget.reserve("CREATION", 1)


def test_configure_transaction_rollback_lost_response_and_operator_scope(budget: BudgetFixture) -> None:
    def crash(name: str) -> None:
        if name == "after_policy_selection":
            raise RuntimeError("fixture crash after policy selection")

    key = identifier("recoverable-grant")
    with pytest.raises(RuntimeError, match="fixture crash"):
        budget.configure(idempotency_key=key, fault_injector=crash)
    with transaction() as connection, connection.cursor() as cursor:
        for table in ("authority_runtime_policy_version", "authority_runtime_policy_selection"):
            cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE owner=%s AND project_id=%s", [OWNER, budget.projects["A"]])
            assert cursor.fetchone()[0] == 0
    def lose_response(name: str) -> None:
        if name == "after_operation_completion_before_response":
            raise RuntimeError("fixture lost committed response")

    with pytest.raises(RuntimeError, match="lost committed response"):
        budget.configure(idempotency_key=key, fault_injector=lose_response)
    result = budget.configure(idempotency_key=key)
    assert result["status"] == "SUCCEEDED"
    assert result["replayed"] is True
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT selected_by_operation_id FROM authority_runtime_policy_selection WHERE owner=%s AND project_id=%s", [OWNER, budget.projects["A"]])
        assert cursor.fetchone()[0] == result["operation_id"]
        cursor.execute("SELECT COUNT(*) FROM authority_runtime_policy_version WHERE owner=%s AND project_id=%s", [OWNER, budget.projects["A"]])
        assert cursor.fetchone()[0] == 1
    for principal in (
        replace(budget.principal, principal_type=PrincipalType.SERVICE),
        replace(budget.principal, project_scope=frozenset({"foreign-project"})),
        replace(budget.principal, permissions=frozenset()),
    ):
        with pytest.raises(PermissionError):
            budget.configure(budget.policy(version="denied-grant"), principal=principal)
    assert get_creative_budget(DATABASE_URL, budget.projects["A"])["budget_binding"]["policy_version"] == "fixture-grant-v1"


def test_reservation_replay_cannot_replace_frozen_authorization(budget: BudgetFixture) -> None:
    budget.configure()
    request, reservation = budget.reserve("CREATION", 100)
    with pytest.raises(KernelError, match="BUDGET_IDEMPOTENCY_CONFLICT"):
        reserve_provider_budget(DATABASE_URL, replace(
            request, cost_authorization_ref="fixture-unrelated-ungranted-authorization",
        ))
    replay = reserve_provider_budget(DATABASE_URL, request)
    assert replay["reservation_id"] == reservation["reservation_id"]
    assert replay["replayed"] is True
    assert budget.usage()["project_total"]["calls_used_or_reserved"] == 1


def test_source_phase_requires_frozen_creative_purpose_and_exact_target_book(budget: BudgetFixture) -> None:
    budget.configure()
    for arguments in (
        {"book_id": budget.books["B"]},
        {"intended_use": "RESEARCH"},
    ):
        effect = budget.effect("SOURCE", **arguments)
        with pytest.raises(KernelError, match="CREATIVE_BUDGET_SCOPE_MISMATCH"):
            budget.reserve("SOURCE", 100, effect=effect)
    assert budget.usage()["project_total"]["calls_used_or_reserved"] == 0
    assert budget.usage()["reservation_ids"] == []
    budget.reserve("SOURCE", 100)
    assert budget.usage()["phases"]["SOURCE"]["calls_used_or_reserved"] == 1


def test_old_effect_settles_after_new_grant_without_rewriting_frozen_proof(budget: BudgetFixture) -> None:
    old_policy = budget.policy()
    old_policy["authorization"]["authorized_cumulative_caps"]["CREATION"] = {"calls": 1, "tokens": 100}
    budget.configure(old_policy)
    effect = budget.effect("CREATION")
    request, reservation = budget.reserve("CREATION", 100, effect=effect)
    dispatch_external_effect(
        DATABASE_URL, effect[0], effect_id=effect[1], worker_id="creative-budget-fixture",
        lease_seconds=30, adapter=FakeDeterministicProvider("success"),
    )
    budget.configure(budget.policy(version="fixture-expanded-grant"))
    budget.reserve("CREATION", 100)
    settled = settle_provider_budget(
        DATABASE_URL, reservation_id=reservation["reservation_id"], project_id=request.project_id,
        actual_amount=None, actual_tokens=80,
        evidence={"fixture": True, "real_model_call": False, "model_id": "fixture-model"},
    )
    assert settled["status"] == "SETTLED"
    assert budget.usage()["phases"]["CREATION"]["conservative_tokens"] == 180
    assert budget.usage()["phases"]["CREATION"]["recorded_actual_tokens"] == 80
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT evidence->'creative_experiment',evidence->>'cost_authorization_ref' FROM authority_budget_reservation WHERE reservation_id=%s", [reservation["reservation_id"]])
        proof, reference = cursor.fetchone()
        assert proof["authorization"] == old_policy["authorization"]
        assert reference == request.cost_authorization_ref
        assert proof["policy_version"] == old_policy["policy_version"]


@pytest.mark.parametrize("unknown", [False, True])
def test_same_effect_cannot_receive_another_reservation_key(budget: BudgetFixture, unknown: bool) -> None:
    budget.configure()
    effect = budget.effect("CREATION", scenario="timeout_after" if unknown else "success")
    request, reservation = budget.reserve("CREATION", 100, effect=effect)
    if unknown:
        dispatch_external_effect(
            DATABASE_URL, effect[0], effect_id=effect[1], worker_id="creative-budget-fixture",
            lease_seconds=30, adapter=FakeDeterministicProvider("timeout_after"),
        )
        result = resolve_provider_budget_failure(
            DATABASE_URL, reservation_id=reservation["reservation_id"], project_id=request.project_id,
        )
        assert result["status"] == "HELD_UNKNOWN"
    with pytest.raises(KernelError, match="BUDGET_IDEMPOTENCY_CONFLICT"):
        reserve_provider_budget(DATABASE_URL, replace(request, stable_idempotency_key=identifier("second-budget-key")))
    replay = reserve_provider_budget(DATABASE_URL, request)
    assert replay["reservation_id"] == reservation["reservation_id"]
    assert replay["execution_authorized"] is not unknown
    assert budget.usage()["project_total"]["calls_used_or_reserved"] == 1
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM authority_budget_reservation WHERE external_effect_id=%s", [request.external_effect_id])
        assert cursor.fetchone()[0] == 1


def test_known_retry_with_measured_usage_reserves_next_dispatch_as_repair(budget: BudgetFixture) -> None:
    budget.configure()
    effect = budget.effect("CREATION", scenario="retryable_failure")
    request, first = budget.reserve("CREATION", 100, effect=effect)
    dispatch_external_effect(
        DATABASE_URL, effect[0], effect_id=effect[1], worker_id="creative-budget-fixture",
        lease_seconds=30, adapter=FakeDeterministicProvider("retryable_failure"),
    )
    settled = settle_provider_budget(
        DATABASE_URL, reservation_id=first["reservation_id"], project_id=request.project_id,
        actual_amount=None, actual_tokens=80,
        evidence={"fixture": True, "real_model_call": False, "model_id": "fixture-model"},
    )
    assert settled["status"] == "SETTLED"
    second = reserve_provider_budget(DATABASE_URL, replace(request, stable_idempotency_key=identifier("retry-budget-key")))
    assert second["execution_authorized"] is True
    assert second["reservation_id"] != first["reservation_id"]
    usage = budget.usage()
    assert usage["project_total"]["calls_used_or_reserved"] == 2
    assert usage["project_total"]["conservative_tokens"] == 180
    assert usage["phases"]["CREATION"]["conservative_tokens"] == 80
    assert usage["phases"]["REPAIR"]["conservative_tokens"] == 100
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT evidence->'creative_experiment' FROM authority_budget_reservation WHERE reservation_id=%s", [second["reservation_id"]])
        proof = cursor.fetchone()[0]
        assert proof["phase"] == "REPAIR"
        assert proof["subject_id"] == f"effect:{effect[1]}:dispatch:2"


def test_first_policy_cannot_race_uncommitted_unconfigured_reservation(budget: BudgetFixture) -> None:
    effect = budget.effect("CREATION")
    request = BudgetReservationRequest(
        operation_id=effect[0].operation_id, external_effect_id=effect[1],
        project_id=effect[0].project_id, stable_idempotency_key=identifier("pre-policy-budget"),
        provider="fake_deterministic_provider", currency="UNKNOWN", estimated_amount=None,
        estimated_tokens=100, accounting_basis="ACCOUNT_ENTITLEMENT",
        cost_authorization_ref=budget.policies["A"]["authorization"]["authorization_ref"],
        call_caps={"project_total": 100}, token_caps={"project_total": 100_000},
    )
    policy = budget.policy()
    policy["authorization"]["authorized_cumulative_caps"]["CREATION"] = {"calls": 0, "tokens": 0}
    policy["authorization"]["authorized_cumulative_caps"]["REPAIR"] = {"calls": 0, "tokens": 0}
    with ThreadPoolExecutor(max_workers=1) as executor:
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            reservation = reserve_provider_budget_in_uow(uow, request)
            uow.cursor.execute("SELECT pg_backend_pid()")
            reserving_backend = uow.cursor.fetchone()[0]
            configuring = executor.submit(budget.configure, policy)
            blocked = False
            deadline = monotonic() + 5
            try:
                while monotonic() < deadline and not configuring.done():
                    uow.cursor.execute(
                        "SELECT EXISTS(SELECT 1 FROM pg_locks l WHERE l.locktype='advisory' AND NOT l.granted AND %s=ANY(pg_blocking_pids(l.pid)))",
                        [reserving_backend],
                    )
                    if uow.cursor.fetchone()[0]:
                        blocked = True
                        break
                    sleep(0.01)
            finally:
                uow.commit()
        assert blocked, "first configuration must wait for the unconfigured reservation transaction"
        with pytest.raises(KernelError, match="CREATIVE_BUDGET_EXHAUSTED"):
            configuring.result(timeout=5)
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM authority_runtime_policy_selection WHERE owner=%s AND project_id=%s", [OWNER, request.project_id])
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT status,estimated_tokens FROM authority_budget_reservation WHERE reservation_id=%s", [reservation["reservation_id"]])
        assert cursor.fetchone() == ("RESERVED", 100)
