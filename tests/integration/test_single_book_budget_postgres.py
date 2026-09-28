from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from decimal import Decimal

import pytest

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.chapter_authority.definitions import chapter_operation_definitions
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.attempt_runtime import WorkerLeaseCommand, acquire_attempt_lease, create_attempt, queue_attempt, start_attempt
from novel_forge.modules.command_kernel.budget_runtime import reserve_provider_budget, resolve_provider_budget_failure, settle_provider_budget
from novel_forge.modules.command_kernel.creative_budget_contract import V1_POLICY_SCHEMA, V2_POLICY_SCHEMA
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_adapters import FakeDeterministicProvider
from novel_forge.modules.command_kernel.external_effect_runtime import EffectCommandContext, dispatch_external_effect, plan_external_effect
from novel_forge.modules.command_kernel.runtime import OperationTransitionCommand, transition_operation
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.modules.source_import.definitions import source_import_definitions
from novel_forge.modules.story_design_authority.evaluation_runtime import narrative_semantic_evaluation_definition
from novel_forge.modules.story_planning_runtime.application import story_planning_generation_definition
from novel_forge.storage.authority_asset_store import AuthorityAssetWriter
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated, identifier, seed_authority_project_book, transaction
from tests.integration.test_creative_experiment_budget_postgres import BUILD_ID, COMMIT_SHA, BudgetFixture
from tests.unit.test_single_book_budget_contract import chapter_identity, planning_identity, single_book_policy


class SingleBookBudget(BudgetFixture):
    def __init__(self, *, chapter=12):
        project = identifier("single-book-budget")
        self.projects = {"A": project}
        self.books = {"A": "book:" + project}
        self.workspaces = {"A": "workspace:" + project}
        self.principal = Principal(principal_id="single-book-budget-fixture", principal_type=PrincipalType.LOCAL_OPERATOR,
                                   permissions=frozenset({"book.authority.execute"}), project_scope=frozenset({project}),
                                   authentication_source="integration-test-fixture")
        seed_authority_project_book(project_id=project, book_id=self.books["A"])
        policy = single_book_policy(chapter=chapter)
        arm = policy["comparison_budget"]["arms"][0]
        arm.update(project_id=project, book_id=self.books["A"])
        policy["comparison_budget"]["experiment_id"] = identifier("single-lifetime-experiment")
        policy["authorization"].update(project_id=project, book_id=self.books["A"])
        self.plan = policy["comparison_budget"]
        self.policies = {"A": policy}
        definitions = (*source_import_definitions(application_build_id=BUILD_ID, commit_sha=COMMIT_SHA),
                       *chapter_operation_definitions(application_build_id=BUILD_ID, commit_sha=COMMIT_SHA, model_effects_required=True),
                       story_planning_generation_definition(application_build_id=BUILD_ID, commit_sha=COMMIT_SHA),
                       narrative_semantic_evaluation_definition(application_build_id=BUILD_ID, commit_sha=COMMIT_SHA))
        self.definitions = {d["name"]: d for d in definitions}
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            for definition in definitions:
                uow.repositories.definitions.register(definition)
            uow.commit()

    def native_effect(self, identity, *, scenario="success"):
        definition = self.definitions[identity["operation_name"]]
        project = self.projects["A"]
        business = deepcopy(identity["command_payload"].get("payload", identity["command_payload"]))
        business["book_id"] = self.books["A"]
        if identity["operation_name"].startswith("chapter."):
            business["chapter"] = business.pop("chapter_number")
            business.update(chapter_plan_asset_version_id="fixture-plan-not-executed", chapter_plan_content_hash="fixture-not-production-proof")
        payload = ({"project_id": project, "input_asset_version_ids": ["fixture-scope-only"], "payload": business}
                   if identity["operation_name"] in {"story_planning.generate", "story_design.semantic_evaluate"} else business)
        result = admit_command(DATABASE_URL, {
            "definition_name": definition["name"], "definition_version": definition["definition_version"],
            "project_id": project, "workspace_id": self.workspaces["A"], "book_id": self.books["A"], "logical_key": identifier("fixture-scope"), "actor_id": self.principal.principal_id,
            "idempotency_scope": definition["idempotency_scope"], "idempotency_key": identifier("run"),
            "trace_id": identifier("trace"), "span_id": identifier("span"), "correlation_id": identifier("correlation"),
            "causation_id": "", "input": payload, "input_assets": [],
        }, context=AdmissionContext(actor_id=self.principal.principal_id, permissions=frozenset(definition["permissions"]),
                                    available_handlers=frozenset({definition["handler_key"]}), application_build_id=BUILD_ID, commit_sha=COMMIT_SHA))
        context = EffectCommandContext(operation_id=result["operation_id"], project_id=project, actor_id=self.principal.principal_id,
                                       trace_id=identifier("trace"), correlation_id=identifier("correlation"))
        transition_operation(DATABASE_URL, OperationTransitionCommand(
            operation_id=context.operation_id, project_id=project, expected_version=0, expected_status="ADMITTED", target_status="READY",
            actor_id=context.actor_id, reason="synthetic budget scope fixture", trace_id=context.trace_id, correlation_id=context.correlation_id, causation_id=context.operation_id))
        attempt = create_attempt(DATABASE_URL, operation_id=context.operation_id, project_id=project, max_attempts=2,
                                 trace_id=context.trace_id, correlation_id=context.correlation_id)
        queue_attempt(DATABASE_URL, attempt_id=attempt["attempt_id"], project_id=project, trace_id=context.trace_id, correlation_id=context.correlation_id)
        lease = acquire_attempt_lease(DATABASE_URL, attempt_id=attempt["attempt_id"], project_id=project, worker_id="creative-budget-fixture",
                                      lease_seconds=120, trace_id=context.trace_id, correlation_id=context.correlation_id)
        start_attempt(DATABASE_URL, WorkerLeaseCommand(attempt_id=attempt["attempt_id"], project_id=project, worker_id="creative-budget-fixture",
                                                       fencing_token=lease["fencing_token"], trace_id=context.trace_id, correlation_id=context.correlation_id))
        request = deepcopy(identity["request_payload"])
        request.update(fixture=True, scenario=scenario)
        request.setdefault("_production_execution", {}).update(attempt_id=attempt["attempt_id"], book_id=self.books["A"])
        effect = plan_external_effect(DATABASE_URL, context, effect_type="model.invoke", provider="fake_deterministic_provider",
                                      capability=identity["capability"], stable_idempotency_key=identifier("effect"), request_payload=request,
                                      max_attempts=2, reversible=False, completion_policy="synchronous_final", model_id="fixture-model",
                                      request_timeout_seconds=30, reconciliation_mode="query")
        return context, str(effect["external_effect_id"])

    def proof(self, reservation):
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT evidence->'creative_experiment' FROM authority_budget_reservation WHERE reservation_id=%s", [reservation["reservation_id"]])
            return cursor.fetchone()[0]

    def evaluation(self, generation):
        identity = planning_identity(chapter=generation)
        origin = self.native_effect(identity)
        output = AuthorityAssetWriter(DATABASE_URL).materialize_output(AuthorityAssetWriteCommand(
            operation_id=origin[0].operation_id, project_id=self.projects["A"], asset_id=identifier("fixture-candidate"),
            asset_type="planning_generation_candidate", schema_version="budget-scope-fixture.v1", logical_ref=identifier("candidate"),
            category="budget-fixtures", output_key="story_planning.candidate", role="primary", content={"fixture": True},
            qualification_policy="budget-fixture-only", trace_id=origin[0].trace_id, correlation_id=origin[0].correlation_id))
        target = {"generator_operation_name": identity["command_payload"]["payload"]["generator_operation_name"],
                  "generation_operation_id": origin[0].operation_id, "candidate_asset_version_id": output.asset_version_id,
                  "candidate_content_hash": output.content_hash}
        return {"operation_name": "story_design.semantic_evaluate", "capability": "model.narrative_semantic_evaluation",
                "command_payload": {"payload": target}, "request_payload": {
                    "stage": "narrative_semantic_evaluation", "input": {"evaluation_target": target},
                    "_production_execution": {"chapter": 0, "generator_operation_name": target["generator_operation_name"],
                        "generation_operation_id": origin[0].operation_id, "target_asset_version_id": output.asset_version_id,
                        "target_content_hash": output.content_hash}}}


@pytest.fixture
def single():
    ensure_migrated()
    return SingleBookBudget()


def test_native_single_book_scope_blocks_every_creative_path_before_reservation(single):
    policy = deepcopy(single.policies["A"])
    policy["authorization"]["business_scope"]["max_chapter_number"] = 0
    single.configure(policy)
    single.reserve("CREATION", 100, effect=single.native_effect(planning_identity()))
    single.reserve("REPAIR", 100, effect=single.native_effect(planning_identity(repair=1)))
    denied = [chapter_identity(1, stage=stage) for stage in ("draft", "review", "revision", "rereview")]
    denied += [planning_identity(chapter=1, stage=stage) for stage in ("chapter_plan.generate", "world_candidates.generate", "world_candidates.evaluate")]
    for identity in denied:
        effect = single.native_effect(identity)
        with pytest.raises(KernelError, match="CREATIVE_BUDGET_BUSINESS_SCOPE_DENIED"):
            single.reserve("CREATION", 1, effect=effect)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM authority_budget_reservation WHERE external_effect_id=%s", [effect[1]])
            assert cursor.fetchone()[0] == 0
            cursor.execute("SELECT COUNT(*) FROM authority_external_effect_dispatch WHERE external_effect_id=%s", [effect[1]])
            assert cursor.fetchone()[0] == 0
    assert single.usage()["phases"]["DESIGN"]["calls_used_or_reserved"] == 1
    assert single.usage()["phases"]["REPAIR"]["calls_used_or_reserved"] == 1


def test_native_single_book_cumulative_scope_upgrade_keeps_old_effect_and_chapter_origins(single):
    policy = deepcopy(single.policies["A"])
    policy["authorization"]["business_scope"]["max_chapter_number"] = 1
    single.configure(policy)
    effect = single.native_effect(chapter_identity(1))
    request, old = single.reserve("CREATION", 100, effect=effect)
    old_proof = single.proof(old)
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_BUSINESS_SCOPE_DENIED"):
        single.reserve("CREATION", 1, effect=single.native_effect(chapter_identity(2)))
    for boundary in (6, 12):
        policy = deepcopy(policy)
        policy["policy_version"] = "fixture-grant-chapter-" + str(boundary)
        policy["authorization"]["authorization_ref"] = "fixture-only:" + str(boundary)
        policy["authorization"]["business_scope"]["max_chapter_number"] = boundary
        single.configure(policy)
        _, current = single.reserve("CREATION", 100, effect=single.native_effect(chapter_identity(boundary)))
        proof = single.proof(current)
        assert proof["business_scope"]["chapter_number"] == boundary
        assert proof["phase"] == ("CREATION_EARLY" if boundary == 6 else "CREATION_LATE")
        if boundary == 6:
            with pytest.raises(KernelError, match="CREATIVE_BUDGET_BUSINESS_SCOPE_DENIED"):
                single.reserve("REPAIR", 1, effect=single.native_effect(chapter_identity(7, stage="revision")))
    dispatch_external_effect(DATABASE_URL, effect[0], effect_id=effect[1], worker_id="creative-budget-fixture", lease_seconds=30, adapter=FakeDeterministicProvider("success"))
    settle_provider_budget(DATABASE_URL, reservation_id=old["reservation_id"], project_id=request.project_id,
                           actual_amount=None, actual_tokens=80, evidence={"fixture": True, "real_model_call": False})
    assert single.proof(old) == old_proof
    assert single.usage()["project_total"]["conservative_tokens"] == 280
    assert single.usage()["project_total"]["calls_used_or_reserved"] == 3


@pytest.mark.parametrize("scenario", ["timeout_after", "retryable_failure"])
def test_native_single_book_unknown_replay_and_known_retry_preserve_phase_origin(single, scenario):
    single.configure()
    effect = single.native_effect(chapter_identity(7), scenario=scenario)
    request, first = single.reserve("CREATION", 100, effect=effect)
    dispatch_external_effect(DATABASE_URL, effect[0], effect_id=effect[1], worker_id="creative-budget-fixture", lease_seconds=30, adapter=FakeDeterministicProvider(scenario))
    if scenario == "timeout_after":
        assert resolve_provider_budget_failure(DATABASE_URL, reservation_id=first["reservation_id"], project_id=request.project_id)["status"] == "HELD_UNKNOWN"
        with pytest.raises(KernelError, match="BUDGET_IDEMPOTENCY_CONFLICT"):
            reserve_provider_budget(DATABASE_URL, replace(request, stable_idempotency_key=identifier("new-run-key")))
        replay = reserve_provider_budget(DATABASE_URL, request)
        assert replay["reservation_id"] == first["reservation_id"] and replay["execution_authorized"] is False
        assert single.usage()["project_total"]["calls_used_or_reserved"] == 1
    else:
        settle_provider_budget(DATABASE_URL, reservation_id=first["reservation_id"], project_id=request.project_id,
                               actual_amount=None, actual_tokens=80, evidence={"fixture": True, "real_model_call": False})
        second = reserve_provider_budget(DATABASE_URL, replace(request, stable_idempotency_key=identifier("known-retry")))
        proof = single.proof(second)
        assert proof["phase"] == "REPAIR" and proof["business_scope"]["origin_phase"] == "CREATION_LATE"
        assert proof["business_scope"]["chapter_number"] == 7 and proof["business_scope"]["dispatch_generation"] == 2
        assert single.usage()["phases"]["CREATION_LATE"]["conservative_tokens"] == 80
        assert single.usage()["phases"]["REPAIR"]["conservative_tokens"] == 100


def test_native_single_book_cannot_reset_an_existing_registered_ab_contract():
    ensure_migrated()
    existing = BudgetFixture()
    existing.configure()
    policy = single_book_policy()
    policy["comparison_budget"]["arms"][0].update(project_id=existing.projects["A"], book_id=existing.books["A"])
    policy["authorization"].update(project_id=existing.projects["A"], book_id=existing.books["A"])
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_PLAN_IMMUTABLE"):
        existing.configure(policy)
    assert existing.usage()["project_total"]["calls_used_or_reserved"] == 0


def test_native_policy_schema_upgrade_preserves_existing_11_definition(single):
    from novel_forge.modules.authority_handler_runtime.policy_commands import owned_policy_definition
    old = owned_policy_definition(owner="CREATIVE_EXPERIMENT_BUDGET", content={}, application_build_id=BUILD_ID, commit_sha=COMMIT_SHA)
    old.update(definition_version="1.1.0", command_schema_version="creative.experiment_budget.configure.command.v1", result_schema_version="creative.experiment_budget.configure.result.v1")
    for key in ("command_schema", "result_schema", "input_contract"):
        old[key]["properties"]["policy"] = V1_POLICY_SCHEMA
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.repositories.definitions.register(old)
        uow.commit()
    single.configure()
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT definition_version,command_schema->'properties'->'policy' FROM authority_operation_definition WHERE name='creative.experiment_budget.configure' AND definition_version IN ('1.1.0','1.2.0') ORDER BY definition_version")
        rows = dict(cursor.fetchall())
        assert rows["1.1.0"] == V1_POLICY_SCHEMA
        assert rows["1.2.0"] == V2_POLICY_SCHEMA
        cursor.execute("SELECT definition_version FROM authority_operation WHERE project_id=%s AND definition_name='creative.experiment_budget.configure'", [single.projects["A"]])
        assert cursor.fetchone()[0] == "1.2.0"


def test_native_semantic_scope_uses_exact_generation_output_and_original_chapter(single):
    from novel_forge.modules.command_kernel.creative_budget_runtime import _business_scope
    from novel_forge.modules.command_kernel.creative_budget_scope import require_business_scope
    policy = deepcopy(single.policies["A"])
    policy["authorization"]["business_scope"]["max_chapter_number"] = 0
    for chapter in (None, 1, 7):
        identity = single.evaluation(chapter)
        identity["attempt_no"] = 1
        identity["command_payload"]["payload"]["book_id"] = single.books["A"]
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            scope = _business_scope(uow.cursor, identity, project_id=single.projects["A"])
        if chapter is None:
            require_business_scope(policy, scope)
            assert scope["phase"] == "DESIGN"
        else:
            assert scope["chapter_number"] == chapter
            with pytest.raises(KernelError, match="CREATIVE_BUDGET_BUSINESS_SCOPE_DENIED"):
                require_business_scope(policy, scope)
        identity["request_payload"]["_production_execution"]["target_content_hash"] = "sha256:" + "0" * 64
        with AuthorityUnitOfWork(DATABASE_URL) as uow, pytest.raises(KernelError, match="CREATIVE_BUDGET_BUSINESS_SCOPE_UNKNOWN"):
            _business_scope(uow.cursor, identity, project_id=single.projects["A"])


def provider_campaign_fixture():
    from tests.unit.test_creative_budget_contract import provider_campaign_policy

    ensure_migrated()
    fixture = SingleBookBudget()
    policy = provider_campaign_policy()
    policy["comparison_budget"]["experiment_id"] = identifier("provider-campaign")
    policy["comparison_budget"]["arms"][0].update(project_id=fixture.projects["A"], book_id=fixture.books["A"])
    policy["authorization"].update(project_id=fixture.projects["A"], book_id=fixture.books["A"])
    fixture.plan = policy["comparison_budget"]
    fixture.configure(policy)
    return fixture


def campaign_reservation(fixture, effect, *, entitlement=False, amount="0.6", tokens=200, authorization="fixture-codex-entitlement"):
    from novel_forge.modules.command_kernel.budget_runtime import BudgetReservationRequest

    context, effect_id = effect
    return BudgetReservationRequest(context.operation_id, effect_id, fixture.projects["A"], "reservation:" + effect_id,
        "codex-cli" if entitlement else "deepseek", "UNKNOWN" if entitlement else "USD",
        None if entitlement else amount, tokens, accounting_basis="ACCOUNT_ENTITLEMENT" if entitlement else "PRICED",
        cost_authorization_ref=authorization if entitlement else "")


def test_mixed_campaign_counts_production_and_subscription_without_reset_or_free_usd():
    from novel_forge.modules.command_kernel.creative_budget_runtime import get_creative_budget
    from novel_forge.modules.command_kernel.budget_runtime import assert_provider_execution_authorized

    fixture = provider_campaign_fixture()
    effects = [fixture.native_effect(chapter_identity(chapter, stage=stage)) for chapter, stage in ((1, "draft"), (1, "review"))]
    for entitlement, effect in zip((False, True), effects, strict=True):
        request = campaign_reservation(fixture, effect, entitlement=entitlement)
        reserved = reserve_provider_budget(DATABASE_URL, request)
        assert_provider_execution_authorized(DATABASE_URL, operation_id=effect[0].operation_id,
            external_effect_id=effect[1], project_id=fixture.projects["A"], budget_reservation_id=reserved["reservation_id"])
        dispatch_external_effect(DATABASE_URL, effect[0], effect_id=effect[1], worker_id="fixture-budget",
            lease_seconds=60, adapter=FakeDeterministicProvider("success"), budget_reservation_id=reserved["reservation_id"])
        settled = settle_provider_budget(DATABASE_URL, reservation_id=reserved["reservation_id"],
            project_id=fixture.projects["A"], actual_amount=None if entitlement else "0.4", actual_tokens=100,
            evidence={"fixture": True, "accounting_basis": request.accounting_basis, "cost_status": "UNKNOWN" if entitlement else "KNOWN"})
        assert settled["status"] == "SETTLED"
        assert reserve_provider_budget(DATABASE_URL, request)["replayed"]
    usage = get_creative_budget(DATABASE_URL, fixture.projects["A"])["budget_usage"]
    assert usage["project_total"]["calls_used_or_reserved"] == 2
    assert Decimal(usage["phases"]["PRODUCTION"]["priced_usd"]) == Decimal("0.4")
    assert usage["project_total"]["unpriced_calls"] == 1
    assert usage["entitlement_usd"] is None
    assert usage["entitlements"][0]["calls"] == 1
    changed = deepcopy(fixture.policies["A"])
    changed["policy_version"] = "new-run-key-same-campaign"
    changed["authorization"]["authorization_ref"] += ":new-run"
    fixture.configure(changed)
    for identity, entitlement, auth in ((chapter_identity(2), False, ""),
                                        (chapter_identity(1, stage="revision"), True, "fixture-codex-entitlement"),
                                        (chapter_identity(1, stage="rereview"), True, "another-account")):
        effect = fixture.native_effect(identity)
        with pytest.raises(KernelError, match="CREATIVE_BUDGET_EXHAUSTED"):
            reserve_provider_budget(DATABASE_URL, campaign_reservation(fixture, effect, entitlement=entitlement, authorization=auth))
    redefined = deepcopy(changed)
    redefined["policy_version"] = "reset-campaign"
    redefined["comparison_budget"]["experiment_id"] += ":renamed"
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_PLAN_IMMUTABLE"):
        fixture.configure(redefined)


def test_mixed_campaign_serializes_price_reservations_and_rechecks_expiry_before_send():
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timezone
    from novel_forge.modules.command_kernel.creative_budget_runtime import get_creative_budget
    from novel_forge.modules.command_kernel.budget_runtime import assert_provider_execution_authorized
    from unittest.mock import patch

    fixture = provider_campaign_fixture()
    effects = [fixture.native_effect(planning_identity()) for _ in range(2)]

    def reserve(effect):
        try:
            return reserve_provider_budget(DATABASE_URL, campaign_reservation(fixture, effect))
        except KernelError as exc:
            return {"status": exc.code}

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(reserve, effects))
    assert sorted(row["status"] for row in outcomes) == ["CREATIVE_BUDGET_USD_EXHAUSTED", "RESERVED"]
    index = next(i for i, row in enumerate(outcomes) if row["status"] == "RESERVED")
    effect, reservation = effects[index], outcomes[index]

    class ExpiredClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2100, 1, 1, tzinfo=timezone.utc)

    with patch("novel_forge.modules.command_kernel.creative_budget_runtime.datetime", ExpiredClock):
        with pytest.raises(KernelError, match="CREATIVE_BUDGET_AUTHORIZATION_EXPIRED"):
            assert_provider_execution_authorized(DATABASE_URL, operation_id=effect[0].operation_id,
                external_effect_id=effect[1], project_id=fixture.projects["A"], budget_reservation_id=reservation["reservation_id"])
    resolve_provider_budget_failure(DATABASE_URL, reservation_id=reservation["reservation_id"],
        project_id=fixture.projects["A"], external_state_unknown=True)
    with pytest.raises(KernelError, match="BUDGET_IDEMPOTENCY_CONFLICT"):
        reserve_provider_budget(DATABASE_URL, replace(campaign_reservation(fixture, effect), stable_idempotency_key="renamed-repair"))
    usage = get_creative_budget(DATABASE_URL, fixture.projects["A"])["budget_usage"]
    assert usage["phases"]["DESIGN"]["calls_used_or_reserved"] == 1
    assert usage["phases"]["DESIGN"]["conservative_tokens"] == 200
    assert Decimal(usage["phases"]["DESIGN"]["priced_usd"]) == Decimal("0.6")


@pytest.mark.parametrize("actual_amount,expected_status", [("0.4", "SETTLED"), ("1.1", "HELD_UNKNOWN")])
def test_mixed_campaign_reconciles_expired_calls_and_retains_monetary_breach(actual_amount, expected_status):
    from datetime import datetime, timezone
    from unittest.mock import patch
    from novel_forge.modules.command_kernel.creative_budget_runtime import get_creative_budget

    fixture = provider_campaign_fixture()
    effect = fixture.native_effect(planning_identity())
    reservation = reserve_provider_budget(DATABASE_URL, campaign_reservation(fixture, effect))
    dispatch_external_effect(DATABASE_URL, effect[0], effect_id=effect[1], worker_id="fixture-budget",
        lease_seconds=60, adapter=FakeDeterministicProvider("success"), budget_reservation_id=reservation["reservation_id"])

    class ExpiredClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2100, 1, 1, tzinfo=timezone.utc)

    with patch("novel_forge.modules.command_kernel.creative_budget_runtime.datetime", ExpiredClock):
        arguments = dict(reservation_id=reservation["reservation_id"], project_id=fixture.projects["A"],
            actual_amount=actual_amount, actual_tokens=100, evidence={"fixture": True, "real_model_call": False})
        if expected_status == "HELD_UNKNOWN":
            with pytest.raises(KernelError, match="BUDGET_ACTUAL_EXCEEDS_RESERVATION"):
                settle_provider_budget(DATABASE_URL, **arguments)
        else:
            assert settle_provider_budget(DATABASE_URL, **arguments)["status"] == expected_status
    usage = get_creative_budget(DATABASE_URL, fixture.projects["A"])["budget_usage"]
    assert Decimal(usage["phases"]["DESIGN"]["priced_usd"]) == Decimal(actual_amount)
    assert usage["phases"]["DESIGN"]["calls_used_or_reserved"] == 1
    if expected_status == "HELD_UNKNOWN":
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT evidence FROM authority_budget_reservation WHERE reservation_id=%s", [reservation["reservation_id"]])
            evidence = cursor.fetchone()[0]
        assert evidence["campaign_budget_error_code"] == "CREATIVE_BUDGET_USD_EXHAUSTED"
        assert evidence["token_cap_error_code"] == ""
        assert evidence["manual_resolution_required"] is True
        assert usage["phases"]["DESIGN"]["conservative_tokens"] == 200
        with pytest.raises(KernelError, match="CREATIVE_BUDGET_USD_EXHAUSTED"):
            reserve_provider_budget(DATABASE_URL, campaign_reservation(fixture, fixture.native_effect(planning_identity()), amount="0.01"))


def test_campaign_money_amendment_preserves_usage_frozen_settlement_and_unknown():
    from novel_forge.modules.command_kernel.creative_budget_runtime import get_creative_budget, provider_campaign_contract_lineage
    from tests.unit.test_creative_budget_contract import campaign_monetary_amendment

    fixture = provider_campaign_fixture()
    project = fixture.projects["A"]
    prior = deepcopy(fixture.policies["A"])
    effects = [fixture.native_effect(chapter_identity(1, stage=stage)) for stage in ("draft", "review")]
    requests = [campaign_reservation(fixture, effect, entitlement=index == 1) for index, effect in enumerate(effects)]
    reservations = [reserve_provider_budget(DATABASE_URL, request) for request in requests]
    resolve_provider_budget_failure(DATABASE_URL, project_id=project,
        reservation_id=reservations[1]["reservation_id"], external_state_unknown=True)
    before = get_creative_budget(DATABASE_URL, project)["budget_usage"]
    amended = campaign_monetary_amendment(prior)
    fixture.configure(amended)
    after = get_creative_budget(DATABASE_URL, project)["budget_usage"]
    assert after["project_total"] == before["project_total"]
    assert after["reservation_ids"] == before["reservation_ids"]
    settled = settle_provider_budget(DATABASE_URL, reservation_id=reservations[0]["reservation_id"],
        project_id=project, actual_amount="0.4", actual_tokens=100, evidence={"fixture": True})
    assert settled["status"] == "SETTLED"
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        lineage = provider_campaign_contract_lineage(uow.cursor, project)
        assert {row["maximum_amount"] for row in lineage} == {"8", "9"}
        uow.cursor.execute("SELECT status FROM authority_budget_reservation WHERE reservation_id=%s", [reservations[1]["reservation_id"]])
        assert uow.cursor.fetchone()[0] == "HELD_UNKNOWN"
    third = fixture.native_effect(chapter_identity(2))
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_EXHAUSTED"):
        reserve_provider_budget(DATABASE_URL, campaign_reservation(fixture, third))
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_PLAN_IMMUTABLE"):
        fixture.configure({**prior, "policy_version": "rollback-without-authority"})


@pytest.mark.parametrize("mutation", ["missing_authorization", "stale_predecessor", "permission_expansion"])
def test_campaign_money_amendment_requires_new_authorization_and_current_predecessor(mutation):
    from tests.unit.test_creative_budget_contract import campaign_monetary_amendment

    fixture = provider_campaign_fixture()
    prior = deepcopy(fixture.policies["A"])
    amended = campaign_monetary_amendment(prior)
    if mutation == "missing_authorization":
        amended["authorization"]["authorization_ref"] = prior["authorization"]["authorization_ref"]
    elif mutation == "stale_predecessor":
        amended["comparison_budget"]["previous_policy"]["policy_hash"] = "a" * 64
    else:
        amended["authorization"]["business_scope"]["max_chapter_number"] = 11
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_(AUTHORIZATION_MISMATCH|PREDECESSOR_MISMATCH|AMENDMENT_SCOPE_MISMATCH)"):
        fixture.configure(amended)


def test_router_accepts_only_native_monetary_amendment_and_retains_original_grant():
    from novel_forge.modules.authority_handler_runtime.policy_commands import configure_owned_policy
    from tests.unit.test_creative_budget_contract import campaign_monetary_amendment
    from tests.unit.test_routing_bootstrap import campaign_grant

    fixture = provider_campaign_fixture()
    project = fixture.projects["A"]
    previous = deepcopy(fixture.policies["A"])
    plan = previous["comparison_budget"]
    original = campaign_grant()
    original["book_id"] = fixture.books["A"]
    original["campaign"].update(campaign_id=plan["experiment_id"], manifest_hash=plan["manifest_hash"],
        maximum_calls=plan["shared_total"]["calls"], maximum_tokens=plan["shared_total"]["tokens"],
        maximum_amount=plan["shared_total"]["priced_usd"], expires_at=plan["expires_at"])

    def configure_route(grant, version):
        return configure_owned_policy(database_url=DATABASE_URL, owner="PROVIDER_ROUTING", project_id=project,
            workspace_id=fixture.workspaces["A"], principal=fixture.principal, application_build_id=BUILD_ID, commit_sha=COMMIT_SHA,
            idempotency_key=identifier("routing-amendment"), trace_id=identifier("trace"), correlation_id=project,
            content={"policy_version": version, "reason": "isolated explicit monetary amendment test",
                     "task_overrides": [], "bootstrap_authorizations": [grant]})

    configure_route(original, "route-before-money")
    changed = deepcopy(original)
    changed["authorization_id"] += ":new-paid-grant"
    changed["campaign"]["maximum_amount"] = "9"
    with pytest.raises(KernelError, match="ROUTING_CAMPAIGN_REDEFINED"):
        configure_route(changed, "route-unapproved-money")
    fixture.configure(campaign_monetary_amendment(previous))
    configure_route(changed, "route-after-money")
    from novel_forge.modules.production_execution.routing_runtime import PostgresRoutingRegistry
    projection = PostgresRoutingRegistry(DATABASE_URL).campaign(project_id=project, campaign_id=plan["experiment_id"])
    assert projection["campaign"]["maximum_amount"] == "9"
    assert projection["grants"] == [original, changed]
    assert projection["usage"]["calls_used_or_reserved"] == 0
    with pytest.raises(KernelError, match="ROUTING_BOOTSTRAP_AUTHORIZATION_REDEFINED"):
        configure_route({**changed, "authorization_id": original["authorization_id"]}, "route-forged-old-grant")
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT content->'bootstrap_authorizations' FROM authority_runtime_policy_version WHERE owner='PROVIDER_ROUTING' AND project_id=%s AND policy_version='route-before-money'", [project])
        assert cursor.fetchone()[0] == [original]
