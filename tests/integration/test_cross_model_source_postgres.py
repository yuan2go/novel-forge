"""PostgreSQL source-contract checks; transport outputs are engineering fixtures."""

from copy import deepcopy
from dataclasses import replace
import sys
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.chapter_authority.author_draft import freeze_author_adoption
from novel_forge.modules.chapter_authority.author_editor import ChapterAuthorEditingApplication, text_hash
from novel_forge.modules.chapter_authority.contracts import ChapterNode
from novel_forge.modules.chapter_authority.handlers import DeterministicFixtureChapterProvider, build_chapter_handler_registry
from novel_forge.modules.chapter_authority.orchestrator import SingleChapterRequest, run_single_chapter_slice
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.external_effect_adapters import FakeDeterministicProvider
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.author_supervision import supervised_decision, verify_frozen_supervision
from novel_forge.modules.production_execution.cost_routing import CostAwareRouter
from novel_forge.modules.production_execution.cross_model_review import freeze_review_requirement, reviewer_rejection
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.migrations import run_migrations
from tests.integration.authority_postgres_support import DATABASE_URL, identifier, insert_definition, insert_operation, seed_authority_project_book
from tests.integration import test_postgresql_only_chapter_slice as chapter_slice_support
from tests.unit.test_author_supervised_routing import prepared
from tests.unit.test_cost_aware_routing import NOW


REVIEWER = {"candidate_id": "source-reviewer", "provider": "deepseek", "model": "reviewer-model",
            "model_revision": "reviewer-revision"}


@pytest.fixture
def separate_release_database(monkeypatch):
    # Separate immutable definition registries are necessary for the fixture release variants.
    primary_url = DATABASE_URL
    parameters = conninfo_to_dict(primary_url)
    parameters["dbname"] = "postgres"
    maintenance = make_conninfo(**parameters)
    name = "nf_p0_" + uuid4().hex + "_test"
    with psycopg.connect(maintenance, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    parameters["dbname"] = name
    database_url = make_conninfo(**parameters)
    original_modules = set(sys.modules)
    try:
        assert run_migrations(database_url)["ok"]
        monkeypatch.setenv("NOVEL_FORGE_DATABASE_URL", database_url)
        for module in tuple(sys.modules.values()):
            if module and module.__name__.startswith("tests.integration") and hasattr(module, "DATABASE_URL"):
                monkeypatch.setattr(module, "DATABASE_URL", database_url)
        yield name
    finally:
        for module_name, module in tuple(sys.modules.items()):
            if (module_name not in original_modules and module_name.startswith("tests.integration")
                    and getattr(module, "DATABASE_URL", None) == database_url):
                module.DATABASE_URL = primary_url
        with psycopg.connect(maintenance, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture(scope="module")
def original_author_draft():
    scope = dict(project_id=identifier("source-project"), workspace_id=identifier("source-workspace"),
                 book_id=identifier("source-book"), chapter=1)
    seed_authority_project_book(**{key: scope[key] for key in ("project_id", "workspace_id", "book_id")})
    root = identifier("source-plan-root")
    evidence = list(chapter_slice_support.PostgreSQLOnlyChapterSliceTests.release_evidence(scope["project_id"]))
    plan_content = {**evidence[0]["content"], "text": "", "scene_artifacts": [{"slot_id": "s1:skeleton", "text": "", "used_fact_ids": []}]}
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        definition = identifier("source-plan-fixture")
        insert_definition(uow.cursor, definition)
        insert_operation(uow.cursor, operation_id=root, definition_name=definition,
                         project_id=scope["project_id"], workspace_id=scope["workspace_id"],
                         status="EXECUTING", command_payload={"chapter": 1, "book_id": scope["book_id"]})
        plan = uow.repositories.asset_documents.materialize_output(AuthorityAssetWriteCommand(
            operation_id=root, project_id=scope["project_id"], asset_id=identifier("source-plan"),
            asset_type="chapter_plan", schema_version="fixture-plan.v1", logical_ref=identifier("plans"),
            category="plans", output_key="chapter.plan", role="primary", content=plan_content,
            qualification_policy="fixture-only", trace_id=identifier("trace"), correlation_id=identifier("correlation")))
        uow.commit()
    evidence[0] = {**evidence[0], "asset_version_id": plan.asset_version_id, "content_hash": plan.content_hash, "content": plan_content}
    principal = Principal("source-author-test", PrincipalType.LOCAL_OPERATOR,
                          frozenset({"chapter.authority.execute", "chapter.authority.query"}),
                          frozenset({scope["project_id"]}), "test")
    app = ChapterAuthorEditingApplication(DATABASE_URL, application_build_id="source-test", commit_sha="e" * 40)
    payload = {**scope, "base_asset_version_id": plan.asset_version_id, "base_asset_hash": plan.content_hash,
               "base_text_hash": text_hash(""), "expected_version": 0,
               "text": "剑已出鞘，林遥却在最后一步收住锋芒。她将归山的令牌压在桥头，任追兵踏碎。",
               "rights_basis": "ORIGINAL_AUTHOR_INPUT"}
    saved = app.execute(action="save", payload=payload, idempotency_key=identifier("author-save"), principal=principal)
    accepted = app.execute(action="accept", payload={**payload, "expected_version": saved["version"],
        "candidate_asset_version_id": saved["candidate_asset_version_id"], "rationale": "采用作者原创正文"},
        idempotency_key=identifier("author-adopt"), principal=principal)
    adoption = freeze_author_adoption(DATABASE_URL, **scope,
        candidate_asset_version_id=saved["candidate_asset_version_id"],
        decision_asset_version_id=accepted["decision_asset_version_id"], principal=principal)

    class NoDraftTransport(DeterministicFixtureChapterProvider):
        def invoke(self, request, *, stage, payload, **kwargs):
            assert stage != "draft", "Author input must not acquire a synthetic generator Effect"
            return super().invoke(request, stage=stage, payload=payload, **kwargs)

    request = SingleChapterRequest(**scope, actor_id=principal.principal_id, title="关山旧约",
        premise="守住同伴的退路需要付出归山的代价。", trace_id=identifier("trace"), correlation_id=identifier("correlation"),
        application_build_id="source-test", commit_sha="e" * 40, context_candidates=tuple(evidence),
        preparation_report={"author_draft_adoption": adoption})
    result = run_single_chapter_slice(DATABASE_URL, request=request,
        registry=build_chapter_handler_registry(NoDraftTransport()), object_store_adapter=FakeDeterministicProvider("success"))
    assert result.root_status == "SUCCEEDED"
    return scope, result, adoption


def test_native_author_draft_without_generator_effect_enters_exact_review(original_author_draft):
    scope, result, adoption = original_author_draft
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        draft = uow.repositories.asset_documents.require(project_id=scope["project_id"],
            asset_version_id=result.outputs[ChapterNode.DRAFT].asset_version_id)
        uow.cursor.execute("SELECT count(*) FROM authority_external_effect WHERE operation_id=%s AND capability='model.draft'",
                           [result.operation_ids[ChapterNode.DRAFT]])
        assert uow.cursor.fetchone()[0] == 0
        contract = freeze_review_requirement(uow.cursor, project_id=scope["project_id"], book_id=scope["book_id"],
            operation_id=result.operation_ids[ChapterNode.REVIEW], task_type="review", request_input={},
            authorized_reviewer=REVIEWER)
    assert contract["schema_version"] == "cross-model-review.v2"
    assert contract["source"]["kind"] == "AUTHOR_ORIGINAL"
    assert contract["target_asset_version_id"] == draft.asset_version_id
    assert contract["target_content_hash"] == draft.content_hash
    assert adoption["candidate_asset_version_id"] != draft.asset_version_id
    assert "generator" not in contract
    assert contract["reviewer_policy"] == "EXPLICIT_AUTHORIZED_REVIEWER"
    assert reviewer_rejection(contract, REVIEWER) is None
    assert reviewer_rejection(contract, {**REVIEWER, "model": "not-authorized"})
    assert reviewer_rejection(contract, {**REVIEWER, "model_revision": "new-unapproved-revision"})


def test_author_source_still_requires_an_explicit_reviewer(original_author_draft):
    scope, result, _ = original_author_draft
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        contract = freeze_review_requirement(uow.cursor, project_id=scope["project_id"], book_id=scope["book_id"],
            operation_id=result.operation_ids[ChapterNode.REVIEW], task_type="review", request_input={})
    assert reviewer_rejection(contract, REVIEWER) == "CROSS_MODEL_REVIEW_SOURCE_POLICY_REQUIRED"
    task, model = prepared("review")
    task = replace(task, declared_requirements={"cross_model_review": contract})
    decision = supervised_decision(CostAwareRouter().explain(task, [model], {}, now=NOW), now=NOW).to_dict()
    assert decision["status"] == "BLOCKED"
    assert decision["selected"] is None


def test_native_source_contract_is_consumed_by_router_without_claiming_qualification(original_author_draft):
    scope, result, _ = original_author_draft
    task, model = prepared("review")
    reviewer = {"candidate_id": model.candidate_id, "model": model.model,
                "model_revision": model.model_revision, "provider": model.provider}
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        contract = freeze_review_requirement(uow.cursor, project_id=scope["project_id"], book_id=scope["book_id"],
            operation_id=result.operation_ids[ChapterNode.REVIEW], task_type="review", request_input={},
            authorized_reviewer=reviewer)
    task = replace(task, declared_requirements={"cross_model_review": contract})
    decision = supervised_decision(CostAwareRouter().explain(task, [model], {}, now=NOW), now=NOW).to_dict()
    assert decision["status"] == "AUTHOR_SUPERVISED_SELECTED"
    assert decision["independent_qualification_eligible"] is False
    verify_frozen_supervision(decision)
    forged = deepcopy(decision)
    forged["selected"]["candidate"]["model"] = "unapproved-reviewer"
    with pytest.raises(KernelError):
        verify_frozen_supervision(forged)


@pytest.mark.parametrize("task,node", [("rereview", ChapterNode.REREVIEW), ("canon_support", ChapterNode.CANON_PROPOSAL)])
def test_model_revision_and_canon_targets_do_not_inherit_author_source(original_author_draft, task, node):
    scope, result, _ = original_author_draft
    with AuthorityUnitOfWork(DATABASE_URL) as uow, pytest.raises(KernelError, match="SOURCE_REQUIRED"):
        freeze_review_requirement(uow.cursor, project_id=scope["project_id"], book_id=scope["book_id"],
            operation_id=result.operation_ids[node], task_type=task, request_input={}, authorized_reviewer=REVIEWER)


def test_author_source_cannot_cross_book_scope(original_author_draft):
    scope, result, _ = original_author_draft
    with AuthorityUnitOfWork(DATABASE_URL) as uow, pytest.raises(KernelError):
        freeze_review_requirement(uow.cursor, project_id=scope["project_id"], book_id="different-book",
            operation_id=result.operation_ids[ChapterNode.REVIEW], task_type="review", request_input={},
            authorized_reviewer=REVIEWER)


@pytest.mark.parametrize("diagnostic", [False, True])
def test_copying_adoption_metadata_cannot_forge_native_author_source(original_author_draft, diagnostic):
    scope, result, _ = original_author_draft
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        source = uow.repositories.asset_documents.require(project_id=scope["project_id"],
            asset_version_id=result.outputs[ChapterNode.DRAFT].asset_version_id)
        definition, operation = identifier("forged-source"), identifier("forged-source")
        insert_definition(uow.cursor, definition)
        insert_operation(uow.cursor, operation_id=operation, definition_name=definition,
            project_id=scope["project_id"], workspace_id=scope["workspace_id"], status="EXECUTING")
        copied = uow.repositories.asset_documents.materialize_output(AuthorityAssetWriteCommand(
            operation_id=operation, project_id=scope["project_id"], asset_id=identifier("copied-author-draft"),
            asset_type="draft_chapter", schema_version="chapter-authority.v1", logical_ref=identifier("copied-draft"),
            category="drafts", output_key="chapter.draft", role="primary",
            content={**source.content, **({"routing_eligibility": "BENCHMARK_ONLY"} if diagnostic else {})},
            qualification_policy="fixture-only", trace_id=identifier("trace"), correlation_id=identifier("correlation")))
        uow.cursor.execute("UPDATE authority_operation SET input_asset_snapshot=%s WHERE operation_id=%s",
            [Jsonb([{"asset_version_id": copied.asset_version_id, "content_hash": copied.content_hash}]), operation])
        with pytest.raises(KernelError, match="SOURCE_INVALID"):
            freeze_review_requirement(uow.cursor, project_id=scope["project_id"], book_id=scope["book_id"],
                operation_id=operation, task_type="review", request_input={}, authorized_reviewer=REVIEWER)


def test_wrong_frozen_hash_cannot_resolve_a_review_target(original_author_draft):
    scope, result, _ = original_author_draft
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        definition, operation = identifier("wrong-hash-review"), identifier("wrong-hash-review")
        insert_definition(uow.cursor, definition)
        insert_operation(uow.cursor, operation_id=operation, definition_name=definition,
            project_id=scope["project_id"], workspace_id=scope["workspace_id"], status="EXECUTING")
        uow.cursor.execute("UPDATE authority_operation SET input_asset_snapshot=%s WHERE operation_id=%s",
            [Jsonb([{"asset_version_id": result.outputs[ChapterNode.DRAFT].asset_version_id,
                     "content_hash": "sha256:" + "f" * 64}]), operation])
        with pytest.raises(KernelError, match="TARGET_REQUIRED"):
            freeze_review_requirement(uow.cursor, project_id=scope["project_id"], book_id=scope["book_id"],
                operation_id=operation, task_type="review", request_input={}, authorized_reviewer=REVIEWER)


def test_repeated_author_edits_retain_original_source_and_each_exact_version(original_author_draft):
    scope, initial, original_adoption = original_author_draft
    principal = Principal("source-author-test", PrincipalType.LOCAL_OPERATOR,
        frozenset({"chapter.authority.execute", "chapter.authority.query"}), frozenset({scope["project_id"]}), "test")
    app = ChapterAuthorEditingApplication(DATABASE_URL, application_build_id="source-test", commit_sha="e" * 40)
    base_id = original_adoption["candidate_asset_version_id"]
    for suffix in (" 她听见身后有人停步。", " 她仍未回头。"):
        current = app.require(**scope, base_asset_version_id=base_id, principal=principal)
        payload = {**scope, **{key: current[key] for key in ("base_asset_hash", "base_text_hash")},
            "base_asset_version_id": base_id, "expected_version": current["version"],
            "text": current["text"] + suffix, "rights_basis": "ORIGINAL_AUTHOR_INPUT"}
        saved = app.execute(action="save", payload=payload, idempotency_key=identifier("repeat-author-save"), principal=principal)
        base_id = saved["candidate_asset_version_id"]
    accepted = app.execute(action="accept", payload={**payload, "expected_version": saved["version"],
        "candidate_asset_version_id": base_id, "rationale": "保留原稿并核对两轮作者修改"},
        idempotency_key=identifier("repeat-author-accept"), principal=principal)
    adoption = freeze_author_adoption(DATABASE_URL, **scope, candidate_asset_version_id=base_id,
        decision_asset_version_id=accepted["decision_asset_version_id"], principal=principal)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT command_payload FROM authority_operation WHERE operation_id=%s", [initial.root_operation_id])
        original_command = uow.cursor.fetchone()[0]
    request = SingleChapterRequest(**scope, actor_id=principal.principal_id, title="关山旧约",
        premise="守住同伴的退路需要付出归山的代价。", trace_id=identifier("trace"), correlation_id=identifier("correlation"),
        application_build_id="source-test", commit_sha="e" * 40, idempotency_key=identifier("repeat-author-chapter"),
        context_candidates=tuple(original_command["context_candidates"]), preparation_report={"author_draft_adoption": adoption})
    from novel_forge.modules.chapter_authority.orchestrator import admit_single_chapter_saga
    from novel_forge.modules.chapter_authority.scheduler import ChapterAuthorityScheduler
    registry = build_chapter_handler_registry(DeterministicFixtureChapterProvider())
    admitted = admit_single_chapter_saga(DATABASE_URL, request=request, registry=registry, permissions=principal.permissions)
    scheduler = ChapterAuthorityScheduler(DATABASE_URL, registry=registry, object_store_adapter=FakeDeterministicProvider("success"),
        worker_id="repeat-author-worker", permissions=frozenset({"chapter.authority.execute"}))
    for node in ("plan", "execution_intent", "memo", "retrieval", "context", "draft", "review"):
        tick = scheduler.tick(project_id=scope["project_id"], root_operation_id=admitted.root_operation_id)
        assert (tick.node, tick.operation_status) == (node, "SUCCEEDED"), tick
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        contract = freeze_review_requirement(uow.cursor, project_id=scope["project_id"], book_id=scope["book_id"],
            operation_id=tick.operation_id, task_type="review", request_input={}, authorized_reviewer=REVIEWER)
    assert contract["source"]["kind"] == "AUTHOR_ORIGINAL"
    assert len(contract["source"]["lineage"]) == 3
    assert contract["source"]["original_source"]["asset_version_id"] == original_adoption["originating_draft_asset_version_id"]
    assert contract["target_asset_version_id"] != initial.outputs[ChapterNode.DRAFT].asset_version_id
    assert contract["target_content_hash"] != initial.outputs[ChapterNode.DRAFT].content_hash


def test_native_edition_cannot_launder_fixture_sources(request, monkeypatch, tmp_path, separate_release_database):
    from novel_forge.modules.book_authority.edition_application import BookEditionApplication
    from novel_forge.modules.chapter_authority.realization_composition import serialize_realization
    from tests.integration.test_book_editions_postgres import persistent_actor_book, advance_to

    captured = persistent_actor_book(request, monkeypatch, tmp_path)
    composition = captured["composition"]
    principal = replace(composition.principal, permissions=composition.principal.permissions | {"book.authority.query"})
    source_run = captured["source_book_run_id"]
    book = composition.authority.require(source_run)
    app = BookEditionApplication(DATABASE_URL, application_build_id=composition.authority.application_build_id,
                                 commit_sha=composition.authority.commit_sha)
    scope = dict(project_id=book["project_id"], workspace_id=book["workspace_id"], book_run_id=source_run, principal=principal)
    manifest = app.query(**scope)["source_manifest"]
    original = app.execute(action="create", **scope, data={"base_manifest_digest": manifest["manifest_digest"]},
                           idempotency_key=identifier("source-original-edition"))
    candidate = app.execute(action="create", **scope,
        data={"base_revision_id": original["revision_id"], "base_manifest_digest": manifest["manifest_digest"]},
        idempotency_key=identifier("source-candidate-edition"))
    units = deepcopy(manifest["units"])
    units[1]["scene_artifacts"][0]["text"] += " Wind passed under the door while the witness waited."
    units[1]["text"] = serialize_realization(units[1]["scene_artifacts"], units[1].get("scene_separators"))
    saved = app.execute(action="save", **scope,
        data={"revision_id": candidate["revision_id"], "expected_version": candidate["version"],
              "base_manifest_digest": candidate["manifest_digest"], "units": units,
              "reason": "Engineering fixture author edits the exact second unit", "change_kind": "EXPRESSION"},
        idempotency_key=identifier("source-save-edition"))
    admitted = app.start_validation(authority=composition.authority, **scope, revision_id=saved["revision_id"])
    validation_run = admitted["validation_book_run_id"]
    advance_to(captured, validation_run, 2)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("""SELECT op.operation_id FROM authority_book_chapter_request request
            JOIN authority_operation op ON op.root_operation_id=request.chapter_root_operation_id
            WHERE request.book_run_id=%s AND request.chapter_number=2
              AND op.definition_name='chapter.review.evaluate' AND op.status='SUCCEEDED'""", [validation_run])
        review_operation = uow.cursor.fetchone()[0]
        with pytest.raises(KernelError) as caught:
            freeze_review_requirement(uow.cursor, project_id=book["project_id"], book_id=book["book_id"],
                operation_id=review_operation, task_type="review", request_input={}, authorized_reviewer=REVIEWER)
        assert caught.value.code == "CROSS_MODEL_REVIEW_SOURCE_REQUIRED"
        assert "No unique real generator receipt" in str(caught.value)


def test_model_and_author_edited_sources_use_native_router_effect_and_distinct_hashes(monkeypatch, tmp_path, separate_release_database):
    from datetime import datetime, timedelta, timezone
    from novel_forge.api.authority_dependencies import build_chapter_authority_application, build_production_execution_composition
    from novel_forge.infrastructure.settings import IndustrialSettings
    from novel_forge.modules.authority_handler_runtime.policy_commands import configure_owned_policy
    from novel_forge.modules.chapter_authority.execution_gateway import ProductionExecutionGatewayExternalEffectAdapter, chapter_producer_contract_identity
    from novel_forge.modules.command_kernel.external_effect_adapters import ProviderResult
    from novel_forge.modules.production_execution.cost_routing import snapshot_hash
    from novel_forge.modules.production_execution.routing_catalog import deepseek_candidates
    from novel_forge.modules.production_execution.routing_runtime import ProductionProviderRouter
    from tests.integration.capability_pack_postgres_support import CapabilityPackPostgresHarness, ROOT

    h = CapabilityPackPostgresHarness("source-review-model")
    compiled = h.register_compile_approve("1.0.0", generation=1)
    h.activate(h.deploy(compiled))
    template = h.run_draft_attempt()
    runtime = template["effect_request_payload"]["_production_execution"]["capability_runtime"]
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        materialization = uow.repositories.asset_documents.require(project_id=h.project_id,
            asset_version_id=runtime["materialization_asset_version_id"]).content
        admission = uow.repositories.asset_documents.require(project_id=h.project_id,
            asset_version_id=runtime["provider_admission_asset_version_id"]).content
    producer = chapter_producer_contract_identity(admission.get("contract", admission)["prompt_materialization"],
                                                 materialization.get("contract", materialization))
    model = deepseek_candidates(available=True)[0]
    author = h.principal("source-model-author", "book.authority.execute", "chapter.authority.execute", "chapter.authority.query")
    grant = {"authorization_id": identifier("source-model-grant"), "book_id": h.book_ids[0], "task_type": "draft",
        "producer_contract_hash": snapshot_hash(producer), "candidate_id": model.candidate_id, "model_revision": model.model_revision,
        "author_id": author.principal_id, "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "maximum_tokens": 200000, "maximum_amount": "1", "reason": "Isolated protocol test with a simulated provider transport"}
    configure_owned_policy(database_url=DATABASE_URL, owner="PROVIDER_ROUTING", project_id=h.project_id,
        workspace_id=h.workspace_id, content={"policy_version": "source-model-v1", "reason": grant["reason"],
            "task_overrides": [], "author_supervised_books": [{"book_id": h.book_ids[0], "author_id": author.principal_id, "reason": grant["reason"]}], "author_supervised_authorizations": [grant]}, idempotency_key=identifier("source-model-policy"),
        trace_id="source-test", correlation_id="source-test", application_build_id=h.application_build_id,
        commit_sha=h.release_sha, principal=author)
    settings = IndustrialSettings(root=ROOT, environment="development", storage_authority="postgresql", database_url=DATABASE_URL)
    env = {"NOVEL_FORGE_ENVIRONMENT": "development", "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
        "NOVEL_FORGE_COMMIT_SHA": h.release_sha, "NOVEL_FORGE_APPLICATION_BUILD_ID": h.application_build_id,
        "NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID": h.pack_id, "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(tmp_path)}
    execution = build_production_execution_composition(settings, env=env)
    execution.gateway.routes = {stage: replace(route, model_context_limit=200000) for stage, route in execution.gateway.routes.items()}
    app = build_chapter_authority_application(settings, execution=execution, env=env)
    binder = app._model_port.capability_binder
    router = ProductionProviderRouter(DATABASE_URL, candidates=[model], execution_environment="development",
        task_money_limit="1", task_token_limit=200000, token_caps={"work_total": 1000000}, call_caps={"work_total": 10})
    app._model_port.max_cost_per_call = "1"
    worker = replace(author, principal_id="source-model-worker", principal_type=PrincipalType.WORKER)
    scheduler = app.scheduler(principal=worker)
    plan = h._chapter_plan_candidate(2)
    request = SingleChapterRequest(project_id=h.project_id, workspace_id=h.workspace_id, book_id=h.book_ids[0],
        actor_id=author.principal_id, chapter=2, title="Exact simulated model source", premise="Preserve the costly public choice.",
        trace_id=identifier("trace"), correlation_id=identifier("correlation"), application_build_id=h.application_build_id,
        commit_sha=h.release_sha, idempotency_key=identifier("source-model-chapter"), context_candidates=(plan,))
    root = app.admit(request, principal=author).root_operation_id
    for node in ("plan", "execution_intent", "memo", "retrieval", "context"):
        tick = scheduler.tick(project_id=h.project_id, root_operation_id=root)
        assert (tick.node, tick.operation_status) == (node, "SUCCEEDED"), tick
    calls = []

    def simulated_provider(adapter, **kwargs):
        calls.append(kwargs)
        metadata = kwargs["request_payload"]["_production_execution"]
        decision = metadata["capability_runtime"]["routing_decision"]
        assert decision["status"] == "AUTHOR_SUPERVISED_SELECTED"
        assert decision["task"]["producer_contract"] == producer
        evidence = deepcopy(template["dispatch_evidence"])
        # Simulated protocol fields exercise production validation only in this disposable database.
        evidence.update(fixture_protocol_only=False, real_model_call=True, production_verified=False,
                        provider_id=model.provider, model_id=model.model, test_transport="SIMULATED_PROVIDER_PROTOCOL")
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("SELECT external_effect_id FROM authority_external_effect WHERE operation_id=%s AND stable_idempotency_key=%s",
                [metadata["operation_id"], kwargs["stable_idempotency_key"]])
            effect_id = uow.cursor.fetchone()[0]
        evidence["production_execution"]["execution_request"].update(
            {key: metadata[key] for key in ("operation_id", "attempt_id", "project_id")}, external_effect_id=effect_id)
        return ProviderResult("success", identifier("simulated-receipt"), evidence)

    binder.provider_router = router
    with monkeypatch.context() as transport_patch:
        transport_patch.setattr(ProductionExecutionGatewayExternalEffectAdapter, "execute", simulated_provider)
        tick = scheduler.tick(project_id=h.project_id, root_operation_id=root)
    assert (tick.node, tick.operation_status) == ("draft", "SUCCEEDED"), tick
    assert len(calls) == 1
    binder.provider_router = None
    tick = scheduler.tick(project_id=h.project_id, root_operation_id=root)
    assert (tick.node, tick.operation_status) == ("review", "SUCCEEDED"), tick
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT operation_id FROM authority_operation WHERE root_operation_id=%s AND definition_name='chapter.review.evaluate'", [root])
        review_operation = uow.cursor.fetchone()[0]
        original_contract = freeze_review_requirement(uow.cursor, project_id=h.project_id, book_id=h.book_ids[0],
            operation_id=review_operation, task_type="review", request_input={})
        source = uow.repositories.asset_documents.require(project_id=h.project_id,
            asset_version_id=original_contract["target_asset_version_id"])
    assert original_contract["schema_version"] == "cross-model-review.v1"
    assert original_contract["generator"]["provider"] == model.provider
    assert original_contract["required_reviewer_provider"] == "codex-cli"
    assert reviewer_rejection(original_contract, {"provider": model.provider, "model": "different-name"})
    editor = ChapterAuthorEditingApplication(DATABASE_URL, application_build_id=h.application_build_id, commit_sha=h.release_sha)
    payload = dict(project_id=h.project_id, workspace_id=h.workspace_id, book_id=h.book_ids[0], chapter=2,
        base_asset_version_id=source.asset_version_id, base_asset_hash=source.content_hash, base_text_hash=text_hash(source.content["text"]),
        expected_version=0, text=source.content["text"] + " The witness kept the signed record.", rights_basis="ORIGINAL_AUTHOR_INPUT")
    saved = editor.execute(action="save", payload=payload, idempotency_key=identifier("model-author-save"), principal=author)
    accepted = editor.execute(action="accept", payload={**payload, "expected_version": saved["version"],
        "candidate_asset_version_id": saved["candidate_asset_version_id"], "rationale": "Fixture author clarifies custody"},
        idempotency_key=identifier("model-author-accept"), principal=author)
    adoption = freeze_author_adoption(DATABASE_URL, **{key: payload[key] for key in ("project_id", "workspace_id", "book_id", "chapter")},
        candidate_asset_version_id=saved["candidate_asset_version_id"], decision_asset_version_id=accepted["decision_asset_version_id"], principal=author)
    edited_request = replace(request, idempotency_key=identifier("model-author-adoption"), preparation_report={"author_draft_adoption": adoption},
        chapter_plan_asset_version_id=plan["asset_version_id"], chapter_plan_content_hash=plan["content_hash"])
    edited_root = app.admit(edited_request, principal=author).root_operation_id
    for node in ("plan", "execution_intent", "memo", "retrieval", "context", "draft", "review"):
        tick = scheduler.tick(project_id=h.project_id, root_operation_id=edited_root)
        assert (tick.node, tick.operation_status) == (node, "SUCCEEDED"), tick
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT operation_id FROM authority_operation WHERE root_operation_id=%s AND definition_name='chapter.review.evaluate'", [edited_root])
        edited_review = uow.cursor.fetchone()[0]
        edited_contract = freeze_review_requirement(uow.cursor, project_id=h.project_id, book_id=h.book_ids[0],
            operation_id=edited_review, task_type="review", request_input={}, authorized_reviewer=REVIEWER)
    assert edited_contract["source"]["kind"] == "MODEL_EDITED_BY_AUTHOR"
    assert edited_contract["source"]["original_provenance"]["model_origins"] == [original_contract["generator"]]
    assert edited_contract["target_asset_version_id"] != source.asset_version_id
    assert edited_contract["target_content_hash"] != source.content_hash
    assert "generator" not in edited_contract
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT request_payload FROM authority_external_effect WHERE operation_id=%s", [edited_review])
        review_request = uow.cursor.fetchone()[0]
        review_runtime = review_request["_production_execution"]["capability_runtime"]
        review_materialization = uow.repositories.asset_documents.require(project_id=h.project_id,
            asset_version_id=review_runtime["materialization_asset_version_id"]).content
        review_admission = uow.repositories.asset_documents.require(project_id=h.project_id,
            asset_version_id=review_runtime["provider_admission_asset_version_id"]).content
    review_producer = chapter_producer_contract_identity(review_admission.get("contract", review_admission)["prompt_materialization"],
        review_materialization.get("contract", review_materialization))
    review_args = dict(task_type="review", project_id=h.project_id, work_id=h.book_ids[0], operation_id=edited_review,
        attempt_id=identifier("review-preflight"), stable_key=identifier("review-preflight"), input_tokens=1000, output_tokens=1000,
        trace_id="source-test", correlation_id="source-test", dry_run=True, request_input=review_request.get("input", {}),
        producer_contract=review_producer, chapter=2)
    _, blocked = router.select(execution.gateway.routes["review"], **review_args)
    assert blocked["status"] == "BLOCKED"
    assert "CROSS_MODEL_REVIEW_SOURCE_POLICY_REQUIRED" in blocked["candidates"][0]["rejected_reasons"]
    review_grant = {**grant, "authorization_id": identifier("source-review-grant"), "task_type": "review",
                    "producer_contract_hash": snapshot_hash(review_producer)}
    configure_owned_policy(database_url=DATABASE_URL, owner="PROVIDER_ROUTING", project_id=h.project_id,
        workspace_id=h.workspace_id, content={"policy_version": "source-model-v2", "reason": grant["reason"],
            "task_overrides": [], "author_supervised_books": [{"book_id": h.book_ids[0], "author_id": author.principal_id, "reason": grant["reason"]}], "author_supervised_authorizations": [grant, review_grant]}, idempotency_key=identifier("source-review-policy"),
        trace_id="source-test", correlation_id="source-test", application_build_id=h.application_build_id,
        commit_sha=h.release_sha, principal=author)
    _, allowed = router.select(execution.gateway.routes["review"], **review_args)
    assert allowed["status"] == "AUTHOR_SUPERVISED_SELECTED"
    actual_contract = allowed["task"]["declared_requirements"]["cross_model_review"]
    assert actual_contract["source"] == edited_contract["source"]
    assert actual_contract["target_content_hash"] == edited_contract["target_content_hash"]
    assert actual_contract["authorized_reviewer"]["candidate_id"] == model.candidate_id
    verify_frozen_supervision(allowed)
