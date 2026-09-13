from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

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
