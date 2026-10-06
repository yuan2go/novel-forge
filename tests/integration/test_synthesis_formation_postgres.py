from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json

import pytest

from novel_forge.api.authority_dependencies import (
    build_book_production_composition,
    build_chapter_authority_application,
    build_production_execution_composition,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.book_design_authority.formation import (
    StartStoryFormationCommand,
)
from novel_forge.modules.book_design_authority.formation_domain import (
    StoryFormationInput,
    deterministic_story_formation_run_id,
)
from novel_forge.modules.authority_security import TrustedPrincipalResolver
from novel_forge.modules.capability_packs.longform_profiles import (
    build_story_planning_pack_profile,
)
from novel_forge.modules.content_authority.application import (
    ContentAuthorityApplication,
    ContentOperationRequest,
)
from novel_forge.modules.content_authority.codecs import CONTENT_CODECS
from novel_forge.modules.provider_control.registry import ProviderAdapterRegistry
from novel_forge.modules.story_planning_runtime import (
    story_planning_generation_definition,
)
from novel_forge.modules.story_planning_runtime.domain import canonical_hash
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.workers.book_authority import execute_story_formation_claim
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.capability_pack_postgres_support import (
    CapabilityPackPostgresHarness,
    RELEASE_SHA,
)
from tests.integration.synthesis_production_support import SynthesisTransport
from tests.integration.test_core_functional_loops_postgres import _principal


@pytest.mark.parametrize(
    "author_guided,result_repair,runtime_recovery,evaluation_recovery,manual_review,advice_only,target_chapters",
    [
        pytest.param(False, False, False, False, False, False, 3, id="current-production"),
        pytest.param(True, False, False, False, False, False, 3, id="author-guided"),
        pytest.param(False, True, False, False, False, False, 3, id="result-repair"),
        pytest.param(False, False, True, False, False, False, 3, id="legacy-runtime-recovery"),
        pytest.param(False, False, False, True, False, False, 3, id="evaluation-recovery"),
        pytest.param(False, False, False, False, True, False, 3, id="manual-second-candidate"),
        pytest.param(False, False, False, False, False, True, 3, id="advice-only-production"),
        pytest.param(False, False, False, False, False, False, 1, id="single-chapter-production"),
    ],
)
def test_native_formation_generates_foundation_from_author_brief(
    tmp_path, monkeypatch, author_guided, result_repair, runtime_recovery,
    evaluation_recovery, manual_review, advice_only, target_chapters,
    *, complete_after_result_repair=False, creative_validation=False, author_result_repair=False, valid_result_admission=False, capacity_continuation=False, semantic_repair=False, route_continuation=False, input_order_continuation=False,
):
    fixture_production_profile = {"world_production_policy": {"context_token_budget": 16000},
        "chapter_context_policy": {"version": "book-chapter-context.v1", "draft_profile": "draft-context-profile-v4", "draft_token_budget": 128000, "quality_token_budget": 128000}}
    if advice_only:
        from novel_forge.modules.review.prose_window import WINDOW_POLICY

        fixture_production_profile["cross_chapter_review_policy"] = {
            "version": WINDOW_POLICY, "source_token_budget": 8000,
        }
    harness = CapabilityPackPostgresHarness(
        "synthesis-formation-author" if author_guided else "synthesis-formation",
        production_profile=fixture_production_profile,
    )
    from copy import copy

    chapter_pack = copy(harness)
    chapter_pack.pack_id += "-chapter"
    if creative_validation:
        from tests.integration.creative_validation_production_support import prepare_native_template
        template_actor = prepare_native_template(harness, chapter_pack, bounded_repairs=semantic_repair and not route_continuation)
    else:
        approved_chapter = chapter_pack.register_compile_approve(
            "1.0.0",
            generation=1,
            approval_scope=chapter_pack.approval_scope(
                environments=("test",), runtime_profiles=("test",)
            ),
            target_runtime_profile="test",
        )
        chapter_pack.register_agents(approved_chapter.compiled)
        chapter_deployment = chapter_pack.deploy(
            approved_chapter, environment="test", runtime_profile="test"
        )
        chapter_pack.activate(chapter_deployment, environment="test")
    from tests.integration.test_postgresql_only_chapter_slice import (
        PostgreSQLOnlyChapterSliceTests,
    )

    PostgreSQLOnlyChapterSliceTests.release_evidence(harness.project_id)
    historical = pytest.MonkeyPatch() if runtime_recovery else None
    if historical:
        import novel_forge.modules.capability_packs.longform_profiles as profiles
        import novel_forge.modules.story_planning_runtime.application as planning_module
        import novel_forge.modules.book_design_authority.formation_generation as formation_generation
        original_command = formation_generation.StoryPlanningGenerationCommand
        historical.setattr(profiles, "STORY_PLANNING_OPERATION_DEFINITION_REF", "story_planning.generate@1.15.0")
        historical.setattr(planning_module, "STORY_PLANNING_GENERATION_VERSION", "1.15.0")
        historical.setattr(formation_generation, "StoryPlanningGenerationCommand", lambda **values: replace(original_command(**values), execution_contract_version="1.15.0"))
    definition = story_planning_generation_definition(
        application_build_id="synthesis-formation", commit_sha=RELEASE_SHA,
        definition_version="1.15.0" if runtime_recovery else "1.18.0",
    )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.repositories.definitions.register(definition)
        uow.cursor.execute(
            "SELECT definition_hash FROM authority_operation_definition WHERE name=%s AND definition_version=%s",
            [definition["name"], definition["definition_version"]],
        )
        digest = str(uow.cursor.fetchone()[0])
        uow.commit()
    profile = build_story_planning_pack_profile(
        Path(__file__).resolve().parents[2],
        operation_definition_hash=digest,
        pack_id=harness.pack_id,
    )
    harness._base_manifest, harness._base_catalog = (
        profile.manifest,
        profile.artifact_catalog,
    )
    approval = harness.approval_scope(
        environments=("test",), runtime_profiles=("test",)
    )
    approval["allowed_workflow_definition_refs"] = [profile.workflow_ref]
    if creative_validation:
        from tests.integration.creative_validation_production_support import install_planning
        install_planning(harness, profile, template_actor)
    else:
        approved = harness.register_compile_approve(
            "1.1.0",
            generation=1,
            approval_scope=approval,
            target_runtime_profile="test",
            proof_skill_ref=profile.agent_skill_ref,
        )
        harness.register_agents(approved.compiled)
        deployment = harness.deploy(approved, environment="test", runtime_profile="test")
        harness.activate(deployment, environment="test")
    principal = _principal(harness.project_id)
    principal = replace(
        principal,
        permissions=principal.permissions
        | {
            "content.authority.execute",
            *(f"content.operation:{name}" for name in CONTENT_CODECS),
        },
    )
    content = ContentAuthorityApplication(
        DATABASE_URL,
        application_build_id="synthesis-formation",
        commit_sha=RELEASE_SHA,
        integration_proven=CONTENT_CODECS,
        trusted_only=True,
    )
    from tests.integration.synthesis_author_input_support import author_fixture, AuthorSynthesisTransport
    author = author_fixture(harness.project_id, harness.book_ids[0]) if author_guided else None
    brief = content.execute(
        ContentOperationRequest(
            definition_name="creative.brief.create",
            project_id=harness.project_id,
            workspace_id=harness.workspace_id,
            actor_id=principal.principal_id,
            trace_id="trace:synthesis-brief",
            correlation_id=harness.project_id,
            idempotency_key=f"{harness.project_id}:synthesis:brief",
            payload={
                "brief": {
                    "creative_brief_contract_version": "creative-brief-v3" if author_guided else "creative-brief-v2",
                    **({"author_design": author} if author_guided else {}),
                    "idea": "一名制图学徒发现街区正在被公共档案抹去，她必须决定是否公开会牵连证人的不完整证据。",
                    "genre": "speculative mystery",
                    "audience": "adult mystery readers",
                    "constraints": ["知识有来源；每次公开发现都需付出代价"],
                    "source_boundaries": [
                        "Only original expression; no reference prose"
                    ],
                }
            },
        ),
        principal=principal,
    )
    env = {
        "NOVEL_FORGE_ENVIRONMENT": "test",
        "NOVEL_FORGE_TEST_ALLOW_SCRIPTED_NARRATIVE_EVALUATION_FIXTURE": "true",
        "NOVEL_FORGE_APPLICATION_BUILD_ID": "synthesis-formation",
        "NOVEL_FORGE_COMMIT_SHA": RELEASE_SHA,
        "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
        "NOVEL_FORGE_PLANNING_PROVIDER": "scripted_provider_v2",
        "NOVEL_FORGE_PLANNING_MODEL": "synthesis-scripted",
        "NOVEL_FORGE_PLANNING_REASONING_EFFORT": "high",
        "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(tmp_path),
        "NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID": harness.pack_id,
        "NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID": chapter_pack.pack_id,
        "NOVEL_FORGE_AUTHORITY_PROJECT_SCOPE": harness.project_id,
    }
    settings = IndustrialSettings(
        root=str(tmp_path),
        environment="test",
        storage_authority="postgresql",
        database_url=DATABASE_URL,
    )
    registry = ProviderAdapterRegistry()
    transport = AuthorSynthesisTransport(author, brief) if author_guided else SynthesisTransport()
    if valid_result_admission:
        from novel_forge.modules.story_planning_runtime import result_recovery
        from novel_forge.modules.command_kernel.errors import KernelError
        normal_validation = result_recovery.validate_raw_result
        old_parser_rejected = False
        def reject_valid_result_once(generator, raw, **kwargs):
            nonlocal old_parser_rejected
            if generator == "world.design.generate" and not old_parser_rejected:
                old_parser_rejected = True
                raise KernelError("FOUNDATION_APPLICABILITY_INVALID", "old parser rejected an exact optional field path")
            return normal_validation(generator, raw, **kwargs)
        monkeypatch.setattr(result_recovery, "validate_raw_result", reject_valid_result_once)
        monkeypatch.setattr(result_recovery, "MAXIMUM_RESULT_REPAIRS", 0)
    if author_result_repair:
        original_author_planning = transport.planning
        damaged_author_decision = False

        def malformed_author_once(stage, inputs):
            nonlocal damaged_author_decision
            result = original_author_planning(stage, inputs)
            if stage == "reader.promise.generate" and not damaged_author_decision:
                damaged_author_decision = True
                result["author_design_decisions"][0]["realization_excerpt"] = "不存在的作者采纳摘录"
            return result

        transport.planning = malformed_author_once
    if advice_only:
        from tests.integration.synthesis_production_support import AdviceOnlySynthesisChapterTransport

        transport.chapter = AdviceOnlySynthesisChapterTransport()
    if result_repair:
        normal_planning = transport.planning
        damaged_world = False

        def malformed_once(stage, inputs):
            nonlocal damaged_world
            result = normal_planning(stage, inputs)
            if stage == "world.design.generate" and not damaged_world:
                damaged_world = True
                world = json.loads(result["world_foundation_json"])
                world["compiled_scope"] = ["BOOK", "VOLUME", "ARC"]
                result["world_foundation_json"] = json.dumps(world)
            return result

        transport.planning = malformed_once
    if creative_validation:
        normal_planning = transport.planning
        def consistent_fixture(stage, inputs):
            result = normal_planning(stage, inputs)
            if stage == "creative.candidates.generate":
                result["serialization_potential"] = None
                for declaration in result.get("applicability", []):
                    if declaration["field_path"] == "$.serialization_potential":
                        declaration.update(status="NOT_APPLICABLE", rationale="Bounded fixture work")
            def bounded_serialization(value):
                if isinstance(value, dict):
                    for key, child in value.items():
                        if key == "serialization_function":
                            value[key] = None
                        else:
                            bounded_serialization(child)
                elif isinstance(value, list):
                    for child in value:
                        bounded_serialization(child)
            bounded_serialization(result)
            return result
        transport.planning = consistent_fixture
    if semantic_repair:
        normal_group_planning = transport.planning
        damaged_group = 0

        def invalid_cause_once(stage, inputs):
            nonlocal damaged_group
            result = normal_group_planning(stage, inputs)
            if stage == "chapter_group_plan.generate" and damaged_group < (2 if input_order_continuation else 1):
                damaged_group += 1
                result["narrative_event_chain"][0]["causes"] = ["absent-causal-event"]
            return result

        transport.planning = invalid_cause_once
    if input_order_continuation:
        from novel_forge.modules.story_planning_runtime import application as planning_module
        from novel_forge.modules.production_execution import planning_repair_routing as routing_module
        original_record = planning_module.StoryPlanningGenerationApplication._record_generation
        original_replay = planning_module._replay_generation_input_snapshot
        original_evidence = routing_module.native_planning_repair
        old_failure_injected = False

        def historical_unordered_record(app, *, operation_id, command, inputs):
            if command.repair_number == 2 and not command.runtime_continuation_id:
                with monkeypatch.context() as old:
                    old.setattr(planning_module, "_replay_generation_input_snapshot",
                        lambda *args: list(reversed(original_replay(*args))))
                    return original_record(app, operation_id=operation_id, command=command, inputs=inputs)
            return original_record(app, operation_id=operation_id, command=command, inputs=inputs)

        def historical_exact_order_guard(cursor, **kwargs):
            nonlocal old_failure_injected
            cursor.execute("SELECT repair_number,runtime_continuation_id FROM authority_story_planning_generation WHERE operation_id=%s", [kwargs["operation_id"]])
            current = cursor.fetchone()
            if current == (2, None) and not old_failure_injected:
                old_failure_injected = True
                kwargs["evidence_version"] = routing_module.LEGACY_REPAIR_VERSION
            return original_evidence(cursor, **kwargs)

        monkeypatch.setattr(planning_module.StoryPlanningGenerationApplication, "_record_generation", historical_unordered_record)
        monkeypatch.setattr(routing_module, "native_planning_repair", historical_exact_order_guard)
    registry.register(transport)
    if creative_validation:
        from tests.integration.creative_validation_production_support import controlled_member_environment
        env = controlled_member_environment(tmp_path, env, monkeypatch, transport)
        settings = replace(settings, environment="validation", root=Path(__file__).resolve().parents[2])
    execution = build_production_execution_composition(
        settings,
        env=env,
        provider_registry=registry,
        planning_fixture_factory=transport.planning,
        chapter_fixture_factory=transport.chapter,
    )
    try:
        chapter = build_chapter_authority_application(
            settings, execution=execution, env=env
        )
        composition = build_book_production_composition(
            settings,
            principal=principal,
            execution=execution,
            chapter_application=chapter,
            env=env,
        )
        formation = composition.formation
        assert formation is not None
        formation_worker = TrustedPrincipalResolver(
            environment="test",
            configured_project_scope=frozenset({harness.project_id}),
        ).resolve_book_formation_worker_principal("synthesis-worker")
        formation_key = f"{harness.project_id}:synthesis:formation"
        formation_run_id = deterministic_story_formation_run_id(
            project_id=harness.project_id,
            book_id=harness.book_ids[0],
            stable_idempotency_key=formation_key,
        )
        admitted = formation.admit(
            StartStoryFormationCommand(
                project_id=harness.project_id,
                workspace_id=harness.workspace_id,
                book_id=harness.book_ids[0],
                actor_id=principal.principal_id,
                expected_book_version=1,
                stable_idempotency_key=formation_key,
                trace_id="trace:synthesis-formation",
                correlation_id=harness.project_id,
                frozen_input=StoryFormationInput(
                    creative_brief_asset_version_id=brief.asset_version_id,
                    creative_brief_content_hash=brief.content_hash,
                    generation_policy={
                        "contract_version": "formation-generation.v2",
                        "approval_mode": "REVIEW_PLAN" if manual_review else "AUTO",
                        "creative_candidates": 2,
                        "target_chapters": target_chapters,
                        "title": "Witness Map",
                        **({} if manual_review else {"auto_authorization": {
                            "contract_version": "formation-auto-authorization.v1",
                            "policy_version": "formation-auto-policy.v1",
                            "authorization_ref": "test:synthesis-formation",
                            "authorized_by_principal_id": principal.principal_id,
                            "project_id": harness.project_id,
                            "workspace_id": harness.workspace_id,
                            "book_id": harness.book_ids[0],
                            "formation_run_id": formation_run_id,
                            "allowed_actions": [
                                "book_design.candidate.activate",
                                "book_design.candidate.decide",
                                "story_planning.candidate.activate",
                                "story_planning.candidate.approve",
                            ],
                        }}),
                    },
                ),
            ),
            principal=principal,
        )
        projection_checkpoints = []
        recovered_activation = False

        def fail_activation(checkpoint):
            if checkpoint == "after_business_projection_update":
                projection_checkpoints.append(checkpoint)
                if len(projection_checkpoints) == 3:
                    raise RuntimeError("simulated activation projection crash")

        formation.generation.book_design.fault_injector = None if manual_review else fail_activation
        evaluation_failed = False
        concurrent_recovery_heads = []
        if evaluation_recovery:
            from novel_forge.modules.story_design_authority.evaluation_runtime import NarrativeSemanticEvaluationHandler, NarrativeSemanticEvaluationApplication
            original_evaluation = NarrativeSemanticEvaluationHandler.execute
            original_admission = NarrativeSemanticEvaluationApplication._admit_candidate_once

            def fail_evaluation_preflight_once(handler, request):
                nonlocal evaluation_failed
                if request.command["payload"]["generator_operation_name"] == "book_design.propose" and not evaluation_failed:
                    from novel_forge.modules.command_kernel.errors import KernelError
                    evaluation_failed = True
                    raise KernelError("NARRATIVE_EVALUATION_PROVIDER_CONTEXT_INVALID", "retained preflight failure before any Effect")
                return original_evaluation(handler, request)

            monkeypatch.setattr(NarrativeSemanticEvaluationHandler, "execute", fail_evaluation_preflight_once)

            def admit_concurrently_once(application, command, admission_command):
                if evaluation_failed and not concurrent_recovery_heads and command.generator_operation_name == "book_design.propose":
                    from concurrent.futures import ThreadPoolExecutor
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        concurrent_recovery_heads.extend(pool.map(lambda _: original_admission(application, command, admission_command), range(2)))
                    return concurrent_recovery_heads[0]
                return original_admission(application, command, admission_command)

            monkeypatch.setattr(NarrativeSemanticEvaluationApplication, "_admit_candidate_once", admit_concurrently_once)
        runtime_recovered = False
        capacity_failed = False
        if capacity_continuation:
            resolver = formation.generation.planning.execution_binder.resolver.execution_preparer
            original_context = resolver._context_bundle
            def fail_capacity_once(**kwargs):
                nonlocal capacity_failed
                if kwargs["command"].repair_of_operation_id and not capacity_failed:
                    from novel_forge.modules.command_kernel.errors import KernelError
                    capacity_failed = True
                    raise KernelError("PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED", "retained zero-dispatch capacity failure")
                return original_context(**kwargs)
            resolver._context_bundle = fail_capacity_once
        if runtime_recovery:
            preparer = formation.generation.planning.execution_binder.resolver.execution_preparer
            def profile_collision(**_):
                from novel_forge.modules.command_kernel.errors import KernelError
                raise KernelError("EXECUTION_CONTRACT_FROZEN_CONFLICT", "retained legacy schema conflicts before dispatch")
            preparer._execution_binding = profile_collision
        selected_creative = ""
        for _ in range(24 if manual_review else 12):
            formation.schedule_candidates(
                limit=1,
                project_id=harness.project_id,
                formation_run_id=admitted.formation_run_id,
            )
            claim = formation.runtime_jobs.claim(
                runtime_group="story_formation",
                worker_id="synthesis-worker",
                lease_seconds=60,
                job_kinds=("STORY_FORMATION_ADVANCE",),
                project_id=harness.project_id,
            )
            if claim is None:
                break
            try:
                execute_story_formation_claim(
                    formation.runtime_jobs,
                    formation,
                    formation_worker,
                    claim,
                    lease_seconds=60,
                )
            except Exception as exc:
                from novel_forge.modules.command_kernel.errors import KernelError
                if capacity_continuation and isinstance(exc, KernelError) and exc.code == "PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED":
                    execution.close()
                    formation, execution, chapter, composition = _recover_capacity_formation(harness=harness,
                        chapter_pack=chapter_pack, principal=principal, pack_actor=template_actor, settings=settings, env=env, registry=registry,
                        transport=transport, admitted=admitted, monkeypatch=monkeypatch)
                    formation.generation.book_design.fault_injector = fail_activation
                    continue
                if valid_result_admission and isinstance(exc, KernelError) and exc.code == "PLANNING_RESULT_REPAIR_BOUND_EXCEEDED":
                    from concurrent.futures import ThreadPoolExecutor
                    from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
                    planning = formation.generation.planning
                    failures = AuthorityAssetQuery(DATABASE_URL).list_versions(project_id=harness.project_id, asset_type="planning_generation_result_failure")
                    assert len(failures) == 1
                    failure = failures[0]
                    source = failure.content["operation_id"]
                    before = len(transport.calls)
                    def register(actor=principal):
                        return planning.register_result_admission_recovery(source,project_id=harness.project_id,
                            source_asset_version_id=failure.asset_version_id,reason="compatible parser repair; retain original result",principal=actor)
                    with pytest.raises(PermissionError):
                        register(formation_worker)
                    from novel_forge.modules.story_planning_runtime import result_admission
                    with monkeypatch.context() as strict:
                        verified = result_admission.verify_template_provenance
                        strict.setattr(result_admission,"verify_template_provenance",lambda *args: {**verified(*args),"mode":"STRICT_PRODUCTION"})
                        with pytest.raises(KernelError,match="PLANNING_RESULT_ADMISSION_POLICY_REQUIRED"):
                            register()
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        recoveries = list(pool.map(lambda _:register(), range(2)))
                    assert len({r["asset_version_id"] for r in recoveries}) == 1
                    assert register()["replayed"] and len(transport.calls) == before
                    with AuthorityUnitOfWork(DATABASE_URL) as uow:
                        uow.cursor.execute("SELECT status FROM authority_operation WHERE operation_id=%s",[source])
                        assert uow.cursor.fetchone()[0] == "FAILED_FINAL"
                        uow.cursor.execute("SELECT count(*) FROM authority_external_effect WHERE operation_id=%s",[recoveries[0]["operation_id"]])
                        assert uow.cursor.fetchone()[0] == 0
                    failed = formation.require(admitted.formation_run_id)
                    formation.resume(admitted.formation_run_id,expected_version=failed["version"],principal=principal)
                    continue
                if evaluation_recovery and isinstance(exc, KernelError) and exc.code == "NARRATIVE_EVALUATION_PROVIDER_CONTEXT_INVALID":
                    failed = formation.require(admitted.formation_run_id)
                    assert failed["lifecycle"] == "FAILED"
                    formation.resume(admitted.formation_run_id, expected_version=failed["version"], principal=principal)
                    continue
                if isinstance(exc, KernelError) and exc.code == "EXECUTION_CONTRACT_FROZEN_CONFLICT" and runtime_recovery and not runtime_recovered:
                    historical.undo()
                    historical = None
                    execution.close()
                    formation, execution = _recover_runtime_profile_formation(
                        harness=harness, chapter_pack=chapter_pack, formation=formation,
                        principal=principal, settings=settings, env=env, registry=registry,
                        transport=transport, admitted=admitted,
                    )
                    formation.generation.book_design.fault_injector = fail_activation
                    runtime_recovered = True
                    continue
                assert (
                    str(exc) == "simulated activation projection crash"
                    and not recovered_activation
                )
                from novel_forge.modules.book_design_authority.query import (
                    BookDesignAuthorityQuery,
                )
                from novel_forge.storage.authority_asset_store import (
                    AuthorityAssetQuery,
                )

                assert not BookDesignAuthorityQuery(DATABASE_URL).require_book(
                    project_id=harness.project_id, book_id=harness.book_ids[0]
                )["active_book_design_version_id"]
                assert not AuthorityAssetQuery(DATABASE_URL).list(
                    project_id=harness.project_id, asset_type="character_arc_portfolio"
                )
                calls_before_recovery = len(transport.calls)
                execution.close()
                execution = build_production_execution_composition(
                    settings,
                    env=env,
                    provider_registry=registry,
                    planning_fixture_factory=transport.planning,
                    chapter_fixture_factory=transport.chapter,
                )
                chapter = build_chapter_authority_application(
                    settings, execution=execution, env=env
                )
                composition = build_book_production_composition(
                    settings,
                    principal=principal,
                    execution=execution,
                    chapter_application=chapter,
                    env=env,
                )
                formation = composition.formation
                failed = formation.require(admitted.formation_run_id)
                formation.resume(
                    admitted.formation_run_id,
                    expected_version=failed["version"],
                    principal=principal,
                )
                recovered_activation = True

            waiting = formation.require(admitted.formation_run_id)
            if manual_review and waiting["lifecycle"] == "WAITING_APPROVAL":
                from novel_forge.modules.command_kernel.errors import KernelError

                reviewer = replace(principal, permissions=principal.permissions | {"book.authority.query"})
                review = formation.review_candidates(admitted.formation_run_id, principal=reviewer)
                candidates = review["candidates"]
                target = candidates[1] if len(candidates) > 1 else candidates[0]
                if len(candidates) > 1:
                    with pytest.raises(KernelError, match="outside the frozen comparison"):
                        formation.author_decision(
                            admitted.formation_run_id, expected_version=review["version"],
                            candidate_asset_version_id=brief.asset_version_id,
                            candidate_content_hash=brief.content_hash, decision="SELECT",
                            reason="Invalid cross-role selection must not change the comparison",
                            idempotency_key="manual:outside-candidate-set", principal=reviewer,
                        )
                    assert formation.require(admitted.formation_run_id)["version"] == review["version"]
                    rejected = formation.author_decision(
                        admitted.formation_run_id, expected_version=review["version"],
                        candidate_asset_version_id=candidates[0]["asset_version_id"],
                        candidate_content_hash=candidates[0]["content_hash"],
                        decision="REJECT", reason="Fixture author rejects first branch; preserve alternatives",
                        idempotency_key="manual:reject-first", principal=reviewer,
                    )
                    with pytest.raises(KernelError, match="Select and approve"):
                        formation.resume(admitted.formation_run_id, expected_version=rejected["version"], principal=reviewer)
                    review = rejected
                    selected_creative = target["asset_version_id"]
                args = dict(expected_version=review["version"],
                            candidate_asset_version_id=target["asset_version_id"],
                            candidate_content_hash=target["content_hash"], decision="APPROVE",
                            reason="Fixture author preserves witness conflict and selects this exact branch",
                            idempotency_key=f"manual:approve:{waiting['current_stage']}", principal=reviewer)
                approved = formation.author_decision(admitted.formation_run_id, **args)
                repeated = formation.author_decision(admitted.formation_run_id, **args)
                assert repeated["version"] == approved["version"]
                assert repeated["recovery_instruction"]["candidate_asset_version_id"] == target["asset_version_id"]
                formation.resume(admitted.formation_run_id, expected_version=approved["version"], principal=reviewer)

            if formation.require(admitted.formation_run_id)["lifecycle"] == "READY":
                break
        result = formation.require(admitted.formation_run_id)
        assert result["lifecycle"] == "READY", result
        if manual_review:
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("SELECT asset_version_id FROM authority_book_foundation_binding WHERE formation_run_id=%s AND foundation_role='CREATIVE_FOUNDATION' AND freshness='CURRENT'", [admitted.formation_run_id])
                assert str(uow.cursor.fetchone()[0]) == selected_creative
                uow.cursor.execute("SELECT operation.input_asset_snapshot FROM authority_story_planning_generation generation JOIN authority_operation operation ON operation.operation_id=generation.operation_id WHERE generation.project_id=%s AND generation.generator_operation_name='theme.candidates.generate'", [harness.project_id])
                parents = uow.cursor.fetchall()
                assert parents and all(any(item["asset_version_id"] == selected_creative for item in row[0]) for row in parents)
                uow.cursor.execute("SELECT checkpoint->'author_decisions' FROM authority_story_formation_stage WHERE formation_run_id=%s AND stage='CREATIVE_SEARCH'", [admitted.formation_run_id])
                decisions = uow.cursor.fetchone()[0]
                assert [item["decision"] for item in decisions] == ["REJECT", "APPROVE"]
            return
        if evaluation_recovery:
            assert evaluation_failed
            assert len(concurrent_recovery_heads) == 2
            assert len({head["operation_id"] for head in concurrent_recovery_heads}) == 1
            assert {head["generation"] for head in concurrent_recovery_heads} == {2}
            with AuthorityUnitOfWork(DATABASE_URL) as recovery_uow:
                recovery_uow.cursor.execute("""
                    SELECT source.status,successor.status,source.command_payload=successor.command_payload,
                           successor.causation_operation_id=source.operation_id,recovery.candidate_asset_version_id,
                           source_execution.candidate_asset_version_id,successor_execution.candidate_asset_version_id,
                           source_execution.lifecycle,successor_execution.lifecycle,
                           (SELECT count(*) FROM authority_external_effect WHERE operation_id=source.operation_id)
                    FROM authority_narrative_formation_recovery recovery
                    JOIN authority_operation source ON source.operation_id=recovery.source_operation_id
                    JOIN authority_operation successor ON successor.operation_id=recovery.successor_operation_id
                    JOIN authority_narrative_evaluation_execution source_execution ON source_execution.operation_id=source.operation_id
                    JOIN authority_narrative_evaluation_execution successor_execution ON successor_execution.operation_id=successor.operation_id
                    WHERE recovery.project_id=%s
                """, [harness.project_id])
                continuations = recovery_uow.cursor.fetchall()
            assert len(continuations) == 1
            recovery = continuations[0]
            assert recovery[:4] == ("FAILED_FINAL", "SUCCEEDED", True, True)
            assert recovery[4] == recovery[5] == recovery[6]
            assert recovery[7:] == ("FAILED", "SUCCEEDED", 0)
            with AuthorityUnitOfWork(DATABASE_URL) as recovery_uow:
                recovery_uow.cursor.execute("SELECT authority_narrative_formation_gate_is_open(successor_operation_id,project_id,recovery_id) FROM authority_narrative_formation_recovery WHERE project_id=%s", [harness.project_id])
                assert recovery_uow.cursor.fetchone()[0] is False
        assert runtime_recovered is runtime_recovery
        if runtime_recovery:
            _assert_runtime_continuation_once(formation, harness, transport, principal)
        creative_candidates = [
            item
            for item in AuthorityAssetQuery(DATABASE_URL).list_versions(
                project_id=harness.project_id,
                asset_type="planning_generation_candidate",
            )
            if item.content.get("generator_operation_name")
            == "creative.candidates.generate"
        ]
        assert sorted(item.lifecycle for item in creative_candidates) == [
            "ACTIVE",
            "CANDIDATE",
        ]
        from novel_forge.modules.story_design_authority.evaluation_execution import (
            PostgresNarrativeEvaluationExecutionContractBinder,
        )

        asset_query = AuthorityAssetQuery(DATABASE_URL)
        book_design = next(
            item for item in asset_query.list_versions(
                project_id=harness.project_id, asset_type="book_design"
            ) if item.lifecycle == "ACTIVE"
        )
        if not creative_validation:
            binder = object.__new__(PostgresNarrativeEvaluationExecutionContractBinder)
            binder.evaluation_query = asset_query
            dependencies = binder._canonical_dependencies(
                book_design, book_id=harness.book_ids[0]
            )
            assert len(dependencies) == 6
            assert all(
                source.asset_type == "planning_generation_candidate"
                and source.content["book_id"] == harness.book_ids[0]
                and qualification.content["candidate_content_hash"] == source.content_hash
                for _, source, qualification in dependencies
            )
        assert (
            recovered_activation and len(transport.calls) == calls_before_recovery == (8 if result_repair or author_result_repair else 7)
        )
        assert {call["stage"] for call in transport.calls} == {
            "creative.candidates.generate",
            "theme.candidates.generate",
            "ending.intent.generate",
            "reader.promise.generate",
            "world.design.generate",
            "character.cast.generate",
        }
        if result_repair:
            from novel_forge.modules.story_planning_runtime.application import _command_from_payload
            from concurrent.futures import ThreadPoolExecutor

            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("SELECT op.operation_id, op.status, op.command_payload->'payload', op.causation_operation_id, g.candidate_asset_version_id FROM authority_operation op JOIN authority_story_planning_generation g USING(operation_id) WHERE op.project_id=%s AND g.generator_operation_name='world.design.generate' ORDER BY op.created_at", [harness.project_id])
                generations = uow.cursor.fetchall()
            assert len(generations) == 2
            failed, repaired = generations
            assert failed[1] == "FAILED_FINAL" and not failed[4]
            assert repaired[1] == "SUCCEEDED" and repaired[4]
            assert str(repaired[3]) == str(failed[0])
            failures = AuthorityAssetQuery(DATABASE_URL).list_versions(project_id=harness.project_id, asset_type="planning_generation_result_failure")
            assert len(failures) == 1 and failures[0].eligibility == "INELIGIBLE"
            assert failures[0].content["candidate_status"] == "NOT_MATERIALIZED"
            assert failures[0].content["diagnostic"]["error_code"] == "WORLD_FOUNDATION_SCHEMA_INVALID"
            from novel_forge.modules.command_kernel.errors import KernelError
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                frozen_failure = [{"asset_version_id": failures[0].asset_version_id, "content_hash": failures[0].content_hash}]
                with pytest.raises(KernelError, match="AUTHORITY_INPUT_NOT_ELIGIBLE"):
                    uow.repositories.chapter_authority.frozen_inputs(harness.project_id, frozen_failure)
                readable_failure = uow.repositories.chapter_authority.frozen_inputs(harness.project_id, frozen_failure, repair_result_asset_version_id=failures[0].asset_version_id)
                assert readable_failure[0]["asset_type"] == "planning_generation_result_failure"
            before = len(transport.calls)
            planning = formation.generation.planning
            original = _command_from_payload(dict(failed[2]))
            from novel_forge.modules.story_planning_runtime.result_recovery import require_result_repair_source
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("SELECT output.asset_version_id FROM authority_operation_output_asset output JOIN authority_asset asset USING(asset_id) WHERE output.operation_id=%s AND asset.asset_type='model_call_log'", [failed[0]])
                legacy_result_asset = str(uow.cursor.fetchone()[0])
            retained = require_result_repair_source(DATABASE_URL, command=original, operation_id=str(failed[0]), source_asset_version_id=legacy_result_asset)
            assert retained["diagnostic"] == failures[0].content["diagnostic"]
            assert retained["raw_result"] == failures[0].content["raw_result"]
            with pytest.raises(KernelError, match="PLANNING_RESULT_REPAIR_INPUT_DRIFT"):
                require_result_repair_source(DATABASE_URL, command=replace(original, auto_approve_low_risk=True), operation_id=str(failed[0]))
            with ThreadPoolExecutor(max_workers=2) as pool:
                replayed = list(pool.map(lambda _: planning.generate(original, principal=formation_worker), range(2)))
            assert {item.candidate_asset_version_id for item in replayed} == {str(repaired[4])}
            assert len(transport.calls) == before
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("SELECT status FROM authority_operation WHERE operation_id=%s", [failed[0]])
                assert uow.cursor.fetchone()[0] == "FAILED_FINAL"
                uow.cursor.execute("SELECT count(*) FROM authority_external_effect WHERE operation_id IN (%s,%s)", [failed[0], repaired[0]])
                assert uow.cursor.fetchone()[0] == 2
            if not complete_after_result_repair:
                return
        if author_result_repair and not capacity_continuation:
            from novel_forge.modules.story_planning_runtime.application import _command_from_payload
            from novel_forge.modules.story_planning_runtime.result_recovery import require_result_repair_source
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("SELECT op.operation_id,op.status,op.command_payload->'payload',op.causation_operation_id,g.candidate_asset_version_id FROM authority_operation op JOIN authority_story_planning_generation g USING(operation_id) WHERE op.project_id=%s AND g.generator_operation_name='reader.promise.generate' ORDER BY op.created_at", [harness.project_id])
                failed, repaired = uow.cursor.fetchall()
                uow.cursor.execute("SELECT output.asset_version_id FROM authority_operation_output_asset output JOIN authority_asset asset USING(asset_id) WHERE output.operation_id=%s AND asset.asset_type='model_call_log'", [failed[0]])
                legacy_result_asset = str(uow.cursor.fetchone()[0])
            assert failed[1] == "FAILED_FINAL" and not failed[4]
            assert repaired[1] == "SUCCEEDED" and repaired[3] == failed[0]
            failures = asset_query.list_versions(project_id=harness.project_id, asset_type="planning_generation_result_failure")
            assert len(failures) == 1 and failures[0].eligibility == "INELIGIBLE"
            assert failures[0].content["diagnostic"]["error_code"] == "AUTHOR_DESIGN_INPUT_INVALID"
            original = _command_from_payload(dict(failed[2]))
            retained = require_result_repair_source(DATABASE_URL, command=original, operation_id=str(failed[0]), source_asset_version_id=legacy_result_asset)
            assert retained["diagnostic"] == failures[0].content["diagnostic"]
            before = len(transport.calls)
            replayed = formation.generation.planning.generate(original, principal=formation_worker)
            assert replayed.candidate_asset_version_id == str(repaired[4])
            assert len(transport.calls) == before
            return
        from novel_forge.modules.book_authority.creation_inputs import (
            prepare_creation_inputs,
        )
        from novel_forge.modules.book_authority.opening import (
            OpenBookProductionRequest,
            _OPENING_INPUT_ROLES,
        )
        from novel_forge.modules.runtime_job import RuntimeJobAuthority
        from novel_forge.workers.book_authority import execute_book_opening_claim

        policy = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "config/production/short-arc-creation.json"
            ).read_text()
        )
        policy["profiles"]["production_profile"]["content"].update(fixture_production_profile)
        policy["profiles"]["production_profile"]["content"]["target_chapter_count"] = target_chapters
        if creative_validation:
            from novel_forge.modules.book_authority.creation_runtime import continue_creation
            from novel_forge.modules.authority_security import PrincipalType
            from types import SimpleNamespace
            import time

            worker = replace(principal, principal_type=PrincipalType.WORKER,
                permissions=principal.permissions - {"book.authority.approve_replan"})
            if route_continuation or input_order_continuation:
                from novel_forge.modules.command_kernel.errors import KernelError
                with pytest.raises(KernelError, match="NATIVE_PLANNING_REPAIR_SOURCE_INVALID" if input_order_continuation else "PROVIDER_ROUTING_BLOCKED"):
                    continue_creation(composition=composition, content=content, chapter=chapter,
                        formation_run_id=admitted.formation_run_id, formation_worker=formation_worker,
                        book_worker=worker, maximum_ticks=80, deadline=time.monotonic() + 240, creation_policy=policy)
                execution.close()
                formation, execution, chapter, composition = _recover_capacity_formation(harness=harness,
                    chapter_pack=chapter_pack, principal=principal, pack_actor=template_actor, settings=settings,
                    env=env, registry=registry, transport=transport, admitted=admitted, monkeypatch=monkeypatch,
                    routing=True, input_order=input_order_continuation)
            creation_result = continue_creation(composition=composition, content=content, chapter=chapter,
                formation_run_id=admitted.formation_run_id, formation_worker=formation_worker,
                book_worker=worker, maximum_ticks=80, deadline=time.monotonic() + 240, creation_policy=policy)
            assert creation_result["stop_reason"] == "COMPLETED", creation_result
            if semantic_repair:
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute("SELECT g.repair_number,o.status,g.candidate_asset_version_id FROM authority_story_planning_generation g JOIN authority_operation o USING(operation_id) WHERE o.project_id=%s AND g.generator_operation_name='chapter_group_plan.generate' ORDER BY o.created_at", [harness.project_id])
                    groups = uow.cursor.fetchall()
                    expected = [0, 1, 2, 2, 0, 0] if input_order_continuation else [0, 1, 1, 0, 0] if route_continuation else [0, 1, 0, 0]
                    assert [row[0] for row in groups] == expected
                    assert all(row[1] == "SUCCEEDED" and row[2] for row in groups if row[1] not in {"CANCELLED","FAILED_FINAL"})
                    if route_continuation:
                        assert groups[1][1:] == ("CANCELLED", None)
                    if input_order_continuation:
                        assert groups[2][1:] == ("FAILED_FINAL", None)
                    uow.cursor.execute("SELECT e.request_payload #> '{_production_execution,capability_runtime,routing_decision}' FROM authority_external_effect e JOIN authority_story_planning_generation g USING(operation_id) WHERE e.project_id=%s AND g.generator_operation_name='chapter_group_plan.generate' AND g.repair_number=%s", [harness.project_id,2 if input_order_continuation else 1])
                    decision = uow.cursor.fetchone()[0]
                    assert decision["selected"]["native_repair_admission"]["status"] == "BOUNDED_REPAIR_ADMITTED"
                    assert decision["selected"]["native_repair_admission"]["retained_failed_outcomes"][0]["failure_class"] == "SCHEMA_REJECTION"
            book_run = SimpleNamespace(book_run_id=creation_result["book_run_id"])
            calls = len(transport.calls), len(transport.chapter.calls)
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("SELECT count(*),sum(actual_tokens) FROM authority_budget_reservation WHERE project_id=%s", [harness.project_id])
                ledger = uow.cursor.fetchone()
                uow.cursor.execute("SELECT count(*) FROM authority_capability_pack_approval approval JOIN authority_operation op ON op.operation_id=approval.decided_by_operation_id WHERE op.project_id=%s", [harness.project_id])
                assert uow.cursor.fetchone()[0] == 0
            execution.close()
            if route_continuation:
                from novel_forge.modules.capability_packs.validation_deployment import register_validation_runtime_definitions, install_chapter_validation_pack
                from tests.integration.creative_validation_production_support import install_planning
                sha = "c" * 40
                hashes = register_validation_runtime_definitions(DATABASE_URL, application_build_id=harness.application_build_id, commit_sha=sha)
                harness.release_sha = sha
                harness.pack_id += ".replay"
                chapter_pack.pack_id += ".replay"
                install_chapter_validation_pack(DATABASE_URL, repository_root=Path(__file__).resolve().parents[2],
                    project_id=harness.project_id, workspace_id=harness.workspace_id, book_id=harness.book_ids[0],
                    application_build_id=harness.application_build_id, commit_sha=sha, compiler=template_actor,
                    approver=template_actor, agent_admin=template_actor, pack_id_override=chapter_pack.pack_id)
                profile = build_story_planning_pack_profile(Path(__file__).resolve().parents[2],
                    operation_definition_hash=hashes["planning"], pack_id=harness.pack_id)
                install_planning(harness, profile, template_actor)
                env.update(NOVEL_FORGE_COMMIT_SHA=sha, NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID=harness.pack_id,
                    NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID=chapter_pack.pack_id)
            execution = build_production_execution_composition(settings, env=env, provider_registry=registry,
                planning_fixture_factory=transport.planning, chapter_fixture_factory=transport.chapter)
            chapter = build_chapter_authority_application(settings, execution=execution, env=env)
            rebuilt = build_book_production_composition(settings, principal=principal, execution=execution,
                chapter_application=chapter, env=env)
            if route_continuation:
                from novel_forge.modules.story_planning_runtime.application import _command_from_payload
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute("SELECT o.command_payload->'payload' FROM authority_story_planning_generation g JOIN authority_operation o USING(operation_id) WHERE o.project_id=%s AND g.generator_operation_name='chapter_group_plan.generate' AND g.repair_number=0 ORDER BY o.created_at LIMIT 1", [harness.project_id])
                    original = _command_from_payload(uow.cursor.fetchone()[0])
                replayed = rebuilt.formation.generation.planning.generate(original, principal=principal)
                assert replayed.candidate_asset_version_id
                assert (len(transport.calls), len(transport.chapter.calls)) == calls
            resumed = continue_creation(composition=rebuilt, content=content, chapter=chapter,
                formation_run_id=admitted.formation_run_id, formation_worker=formation_worker,
                book_worker=worker, maximum_ticks=5, deadline=time.monotonic() + 30, creation_policy=policy)
            assert resumed["stop_reason"] == "COMPLETED" and resumed["book_run_id"] == book_run.book_run_id
            assert (len(transport.calls), len(transport.chapter.calls)) == calls
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("SELECT count(*),sum(actual_tokens) FROM authority_budget_reservation WHERE project_id=%s", [harness.project_id])
                assert uow.cursor.fetchone() == ledger
        else:
            prepared = prepare_creation_inputs(
                composition=composition,
                content=content,
                formation_run_id=admitted.formation_run_id,
                policy=policy,
            )
            versions = prepared["versions"]
            opening_request = OpenBookProductionRequest(
                project_id=harness.project_id,
                workspace_id=harness.workspace_id,
                book_id=harness.book_ids[0],
                actor_id=principal.principal_id,
                expected_book_version=prepared["book_version"],
                production_profile=versions["production_profile"],
                planning_input_versions={
                    role: versions[role] for role in _OPENING_INPUT_ROLES
                },
                arc_logical_keys=("arc:central", "arc:relationship"),
                idempotency_key=f"{harness.project_id}:synthesis:opening",
                trace_id="trace:synthesis:opening",
                correlation_id=harness.project_id,
                initial_story_state_version=versions["story_state"],
                initial_canon_snapshot_version=versions["canon_snapshot"],
            )
            opening = composition.open_book(opening_request)
            assert opening.opening_run_id
            claim = composition.opening.claim_next_execution(
                worker_id="synthesis-opening",
                lease_seconds=60,
                project_id=harness.project_id,
            )
            assert claim is not None
            opened = execute_book_opening_claim(
                RuntimeJobAuthority(DATABASE_URL),
                composition.opening,
                principal,
                claim,
                lease_seconds=60,
            )
            snapshot = composition.input_resolver.require(opened["input_snapshot_id"])
            if creative_validation:
                from novel_forge.modules.book_authority.creation_runtime import drive_book as drive, resolved_book_command as start_command
            else:
                from scripts.run_world_production_smoke import drive, start_command
            from novel_forge.modules.authority_security import PrincipalType
            import time

            book_run = composition.authority.start(
                start_command(
                    snapshot,
                    actor=principal.principal_id,
                    run_key=f"{harness.project_id}:synthesis:production",
                    chapters=target_chapters,
                ),
                principal=principal,
            )
            worker = replace(
                principal,
                principal_type=PrincipalType.WORKER,
                permissions=principal.permissions - {"book.authority.approve_replan"},
            )
            ticks = []
            stop = drive(
                composition=composition,
                chapter=chapter,
                book_run_id=book_run.book_run_id,
                worker=worker,
                events=ticks.append,
                maximum_ticks=80,
                deadline=time.monotonic() + 240,
            )
            assert stop == ("COMPLETED" if creative_validation else "ACCEPTED_TARGET_REACHED"), (stop, ticks[-3:])
        from tests.integration.creative_grounding_support import (
            verify_creative_workspace,
        )

        workspaces = verify_creative_workspace(
            composition=composition,
            chapter_application=chapter,
            book_run_id=book_run.book_run_id,
            transport=transport.chapter,
            minimum_chapters=min(2, target_chapters),
        )
        if advice_only:
            from novel_forge.modules.review.diagnostics import prose_repair_diagnoses

            for workspace in workspaces["workspaces"]:
                candidates = {item["asset_type"]: item for item in workspace["artifacts"]["candidates"]}
                draft = candidates["draft_chapter"]["content"]
                revision = candidates["draft_version"]["content"]
                assert revision["text"] == draft["text"]
                assert revision["scene_artifacts"] == draft["scene_artifacts"]
                assert candidates["best_draft_candidate"]["content"]["selected_source_asset_version_id"] == candidates["draft_chapter"]["asset_version_id"]
            reviews = [call for call in transport.chapter.calls if call["stage"] == "review"]
            assert len(reviews) == 3
            assert all(call["output"]["issues"][0]["judgment_kind"] == "AESTHETIC_SUGGESTION" for call in reviews)
            revisions = [call for call in transport.chapter.calls if call["stage"] == "revision"]
            assert len(revisions) == 3
            assert any(call["input"]["review"].get("cross_chapter_window") for call in revisions)
            assert all(not prose_repair_diagnoses(call["input"]["review"], work_requirements=True) for call in revisions)
            targeted = [call for call in revisions if call["input"]["review"].get("cross_chapter_window") or call["input"]["review"].get("craft_targets")]
            assert targeted
            assert all(call["output"] == {"edits": [], "resolved_issue_codes": []} for call in targeted)
            from novel_forge.modules.book_followup_authority.prose_coordinator import load_accepted_sources
            from novel_forge.modules.book_followup_authority.prose_review import freeze_manifest

            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                sources = load_accepted_sources(uow, book_run.book_run_id, harness.project_id)
            baselines = {
                workspace["acceptance"]["accepted_through_chapter"]: next(
                    item["content"]["creative_baseline"] for item in workspace["artifacts"]["candidates"]
                    if item["asset_type"] == "best_draft_candidate"
                ) for workspace in workspaces["workspaces"]
            }
            assert {source["chapter_number"]: source["creative_baseline"] for source in sources} == baselines
            manifest = freeze_manifest(
                project_id=harness.project_id, workspace_id=harness.workspace_id,
                book_run_id=book_run.book_run_id, sources=sources,
                policy={"policy_version": "work-fixture", "window_codepoints": 2048,
                        "overlap_codepoints": 64, "context_token_budget": 16000, "maximum_windows": 20},
            )
            assert all(source["work_intent_status"] == "FROZEN_CANDIDATE_BASELINE" for source in manifest["sources"])
        from novel_forge.modules.chapter_outcome.acceptance_contract import resolve_accepted_manuscript

        for workspace in workspaces["workspaces"]:
            assert workspace["accepted_manuscript"]["status"] == "EXACT_ACCEPTANCE_BOUND", workspace["accepted_manuscript"]
            accepted_text = resolve_accepted_manuscript(workspace)
            assert accepted_text["candidate"]["content"]["text"]
            assert accepted_text["outcome"]["asset_version_id"] == workspace["acceptance"]["outcome_asset_version_id"]
            assert workspace["creation_sources"]["status"] == "EXACT_FROZEN_INPUT"
            best = next(
                item["content"]
                for item in workspace["artifacts"]["candidates"]
                if item["asset_type"] == "best_draft_candidate"
            )
            assert (
                best["realization_contract"]["contract_version"]
                == "scene-realization-composition.v2"
            )
            assert best["realization_contract"]["craft_tasks"]["tasks"]
        if author_guided:
            from novel_forge.modules.chapter_outcome.acceptance_contract import resolve_accepted_manuscript
            from novel_forge.modules.story_design_authority.author_input import text_hash
            for workspace in workspaces["workspaces"]:
                manuscript = resolve_accepted_manuscript(workspace)
                candidate = manuscript["candidate"]["content"]
                guidance = candidate["author_design_guidance"]
                assert guidance["brief_asset_version_id"] == brief.asset_version_id
                assert guidance["brief_content_hash"] == brief.content_hash
                assert all(item["visibility"] == "SCENE_INTENT" for item in guidance["fragments"])
                assert "PRIVATE_AUTHOR_CAUSE_NOT_FOR_WRITER" not in json.dumps(guidance)
                assert all(text_hash(item["text"]) == item["content_hash"] for item in guidance["fragments"])
            contexts = AuthorityAssetQuery(DATABASE_URL).list_versions(project_id=harness.project_id, asset_type="context_bundle", limit=500)
            bound_contexts = [item for item in contexts if item.content.get("author_design_projection")]
            assert bound_contexts
            from novel_forge.modules.story_design_authority.author_input import compile_provider_author_projection
            for item in bound_contexts:
                manifest = item.content["context_manifest"]
                original = item.content["author_design_projection"]
                delivered = manifest["provider_context_view"]["compiled_view"]["author_design_projection"]
                assert delivered == compile_provider_author_projection(original)
                semantic_fields = {"text", "fragment_id", "content_hash", "visibility", "strength", "chapter_range"}
                assert delivered["fragments"] == [
                    {key: value for key, value in fragment.items() if key in semantic_fields}
                    for fragment in original["fragments"]
                ]
                assert delivered["source_receipt"]["json_pointer"] == "/author_design_projection"
                assert delivered["source_receipt"]["content_hash"] == canonical_hash(original)
                assert any(selected["logical_context_kind"] == "planning_author_design_projection" for selected in manifest["selected_inputs"])
        artifact = {
            "prepared": {"creation_input_policy": policy} if creative_validation else prepared,
            "opening": creation_result if creative_validation else opened,
            "ticks": {"status": "NOT_RECORDED"} if creative_validation else ticks,
            "workspaces": workspaces,
            "proof_ceiling": "SCRIPTED_PROVIDER_PRODUCTION_WIRING_ONLY",
            "formation": result,
            "provider_calls": transport.calls,
        }
        (tmp_path / "formation-production.json").write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2, default=str)
        )
        from scripts.run_world_production_smoke import export, export_artifacts

        export_artifacts(
            database_url=DATABASE_URL,
            project_id=harness.project_id,
            destination=tmp_path,
            extra_kinds=(
                "planning_generation_candidate",
                "narrative_design_evaluation",
            ),
        )
        export(
            composition=composition,
            book_run_id=book_run.book_run_id,
            destination=tmp_path,
        )
        from scripts.compare_creation_exports import chapters
        from scripts.creation_pilot import prepare_pilot_book
        assert set(chapters(tmp_path)) == set(range(1, target_chapters + 1))
        assert len(list(tmp_path.glob("accepted-chapter-*.txt"))) == target_chapters
        if creative_validation:
            from copy import deepcopy
            from novel_forge.modules.chapter_quality_authority.creative_validation import verify_internal_quality
            reports = AuthorityAssetQuery(DATABASE_URL).list_versions(project_id=harness.project_id, asset_type="quality_score_report")
            assert reports
            for report in reports:
                admission = report.content["internal_admission"]
                assert admission["status"] == "INTERNAL_ADMITTED" and admission["literary_qualification"] == "NOT_RUN"
                assert report.content["gate"] not in {"PASSED", "PASSED_WITH_WARNINGS"}
                forged = deepcopy(admission)
                forged["observations"][0]["status"] = "QUALIFIED"
                with pytest.raises(ValueError, match="VALIDATION_QUALITY_ADMISSION_TAMPERED"):
                    verify_internal_quality(DATABASE_URL, forged, project_id=harness.project_id, book_id=harness.book_ids[0])
            return
        assert formation.find_by_key(project_id=harness.project_id, book_id=harness.book_ids[0], idempotency_key=formation_key)["formation_run_id"] == admitted.formation_run_id
        assert formation.find_by_key(project_id=harness.project_id, book_id=harness.book_ids[0], idempotency_key="different-key") is None
        assert composition.opening.find_by_key(project_id=harness.project_id, book_id=harness.book_ids[0], idempotency_key=f"{harness.project_id}:synthesis:opening")["opening_run_id"] == opening.opening_run_id
        pilot_project = harness.project_id + "-pilot"
        pilot_principal = replace(principal, project_scope=frozenset({pilot_project}), permissions=principal.permissions | {"project.authority.execute"})
        frozen_pilot = {"creation_policy": policy, "implementation_identity": RELEASE_SHA}
        arguments = dict(composition=composition, principal=pilot_principal, project_id=pilot_project,
                         workspace_id=pilot_project + "-workspace", book_id=pilot_project + "-book",
                         run_key=f"{harness.project_id}:pilot-prepare", title="隔离试运行", frozen=frozen_pilot)
        first_book = prepare_pilot_book(**arguments, initialize=True)
        assert prepare_pilot_book(**arguments, initialize=True) == first_book
        assert prepare_pilot_book(**arguments, initialize=False) == first_book
        with pytest.raises(ValueError, match="differs"):
            prepare_pilot_book(**{**arguments, "frozen": {**frozen_pilot, "run_key": "changed"}}, initialize=False)
    finally:
        if historical:
            historical.undo()
        (tmp_path / "provider-transcript.json").write_text(
            json.dumps(
                {
                    "proof_ceiling": "SCRIPTED_TRANSPORT_ONLY",
                    "foundation": transport.calls,
                    "chapter": transport.chapter.calls,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        execution.close()


def _recover_runtime_profile_formation(*, harness, chapter_pack, formation, principal, settings, env, registry, transport, admitted):
    from concurrent.futures import ThreadPoolExecutor
    from novel_forge.modules.command_kernel.budget_runtime import resolve_provider_budget_failure
    from novel_forge.modules.command_kernel.cancellation import CancelCommand, request_cancellation, resolve_cancellation
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.story_planning_runtime.application import _command_from_payload
    from novel_forge.modules.story_planning_runtime.runtime_continuation import require_binding

    assert not transport.calls
    failed = formation.require(admitted.formation_run_id)
    assert failed["lifecycle"] == "FAILED"
    assert failed["current_stage"] == "CREATIVE_SEARCH"
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT op.operation_id,op.version,op.status,op.command_payload->'payload',effect.external_effect_id,reservation.reservation_id,snapshot.snapshot_payload FROM authority_operation op JOIN authority_story_planning_generation generation USING(operation_id) JOIN authority_external_effect effect USING(operation_id) JOIN authority_budget_reservation reservation USING(operation_id) JOIN authority_attempt_capability_pack_snapshot snapshot USING(operation_id) WHERE op.project_id=%s", [harness.project_id])
        source_id, source_version, source_status, source_payload, effect_id, reservation_id, source_snapshot = uow.cursor.fetchone()
        assert source_status == "FAILED_RETRYABLE"
        assert source_payload["execution_contract_version"] == "1.15.0"
        uow.cursor.execute("SELECT count(*) FROM authority_external_effect_dispatch WHERE external_effect_id=%s", [effect_id])
        assert uow.cursor.fetchone()[0] == 0
    requested = request_cancellation(DATABASE_URL, CancelCommand(operation_id=source_id,project_id=harness.project_id,actor_id=principal.principal_id,expected_version=source_version,reason="fixture verified no dispatch before runtime repair",idempotency_key=f"{source_id}:cancel",trace_id="trace:runtime-continuation",correlation_id=harness.project_id))
    del requested
    def cancel():
        return resolve_cancellation(DATABASE_URL,operation_id=source_id,project_id=harness.project_id,expected_version=source_version+1,resolution="never_dispatched_effects",actor_id=principal.principal_id,reason="all reservations released and no dispatch",trace_id="trace:runtime-continuation",correlation_id=harness.project_id)
    with pytest.raises(KernelError, match="CANCELLATION_NOT_DISPATCHED_PROOF_REQUIRED"):
        cancel()
    assert resolve_provider_budget_failure(DATABASE_URL,reservation_id=reservation_id,project_id=harness.project_id)["status"] == "RELEASED"
    cancelled = cancel()
    assert cancel()["replayed"] is True
    new_sha = "f" * 40
    definition = story_planning_generation_definition(application_build_id="synthesis-formation", commit_sha=new_sha, definition_version="1.15.0")
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        registered = uow.repositories.definitions.register(definition)
        uow.cursor.execute("SELECT definition_hash FROM authority_operation_definition WHERE name=%s AND definition_version=%s",[definition["name"],definition["definition_version"]])
        digest=uow.cursor.fetchone()[0]
        uow.commit()
    del registered
    profile = build_story_planning_pack_profile(Path(__file__).resolve().parents[2], operation_definition_hash=digest,pack_id=harness.pack_id, execution_contract_version="1.15.0")
    harness._base_manifest,harness._base_catalog=profile.manifest,profile.artifact_catalog
    scope=harness.approval_scope(environments=("test",),runtime_profiles=("test",))
    scope["allowed_workflow_definition_refs"]=[profile.workflow_ref]
    from novel_forge.modules.capability_pack_authority.application import CapabilityPackAuthorityApplication
    harness.release_sha=new_sha
    harness.application=CapabilityPackAuthorityApplication(DATABASE_URL,application_build_id=harness.application_build_id,commit_sha=new_sha)
    approved=harness.register_compile_approve("1.2.0",generation=2,approval_scope=scope,target_runtime_profile="test",proof_skill_ref=profile.agent_skill_ref,release_sha=new_sha)
    deployment=harness.deploy(approved,environment="test",runtime_profile="test")
    harness.activate(deployment,expected_activation_version=1,environment="test")
    from novel_forge.modules.chapter_authority.definitions import chapter_operation_definitions
    from novel_forge.modules.agent_runtime.definitions import agent_runtime_operation_definitions
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        for item in (*chapter_operation_definitions(application_build_id=chapter_pack.application_build_id,commit_sha=new_sha,model_effects_required=True),*agent_runtime_operation_definitions(application_build_id=chapter_pack.application_build_id,commit_sha=new_sha)):
            uow.repositories.definitions.register(item)
        uow.commit()
    chapter_pack.release_sha=new_sha
    chapter_pack.application=CapabilityPackAuthorityApplication(DATABASE_URL,application_build_id=chapter_pack.application_build_id,commit_sha=new_sha)
    approved_chapter=chapter_pack.register_compile_approve("1.1.0",generation=2,approval_scope=chapter_pack.approval_scope(environments=("test",),runtime_profiles=("test",)),target_runtime_profile="test",release_sha=new_sha)
    chapter_deployment=chapter_pack.deploy(approved_chapter,environment="test",runtime_profile="test")
    chapter_pack.activate(chapter_deployment,expected_activation_version=1,environment="test")
    env["NOVEL_FORGE_COMMIT_SHA"]=new_sha
    execution=build_production_execution_composition(settings,env=env,provider_registry=registry,planning_fixture_factory=transport.planning,chapter_fixture_factory=transport.chapter)
    chapter=build_chapter_authority_application(settings,execution=execution,env=env)
    composition=build_book_production_composition(settings,principal=principal,execution=execution,chapter_application=chapter,env=env)
    formation=composition.formation
    planning=formation.generation.planning
    def register():
        return planning.register_runtime_continuation(source_id,project_id=harness.project_id,principal=principal,expected_source_version=cancelled["version"],decision_evidence={"authorization_ref":"test:trusted-runtime-continuation", "authorized_reasoning_effort":"high", "reason":"exact immutable profile identity repair"},trace_id="trace:runtime-continuation",correlation_id=harness.project_id)
    worker = replace(principal, principal_type=__import__('novel_forge.modules.authority_security',fromlist=['PrincipalType']).PrincipalType.SERVICE)
    with pytest.raises(PermissionError):
        planning.register_runtime_continuation(source_id,project_id=harness.project_id,principal=worker,expected_source_version=cancelled["version"],decision_evidence={"authorization_ref":"test:trusted-runtime-continuation","reason":"not operator"},trace_id="trace:runtime-continuation",correlation_id=harness.project_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        registrations=list(pool.map(lambda _:register(),range(2)))
    assert {item["operation_id"] for item in registrations}.__len__()==1
    continuation_id=f"planning-runtime-continuation:{source_id}"
    binding=require_binding(DATABASE_URL,continuation_id)
    assert binding["source_command"]==source_payload
    assert binding["target_release_sha"]==new_sha
    assert binding["successor_command"]["execution_contract_version"]=="1.15.0"
    assert binding["successor_operation_id"] is None
    successor=_command_from_payload(binding["successor_command"])
    with pytest.raises(KernelError,match="PLANNING_RUNTIME_CONTINUATION_COMMAND_DRIFT"):
        planning.generate(replace(successor,book_id="different-book"),principal=replace(principal,principal_id=successor.actor_id))
    actual_sha=planning.commit_sha
    planning.commit_sha=RELEASE_SHA
    try:
        with pytest.raises(KernelError,match="PLANNING_RUNTIME_CONTINUATION_COMMAND_DRIFT"):
            planning.generate(successor,principal=replace(principal,principal_id=successor.actor_id))
    finally:
        planning.commit_sha=actual_sha
    formation.resume(admitted.formation_run_id,expected_version=failed["version"],principal=principal)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT status,command_payload->'payload' FROM authority_operation WHERE operation_id=%s",[source_id])
        assert uow.cursor.fetchone()==("CANCELLED",source_payload)
        uow.cursor.execute("SELECT snapshot_payload FROM authority_attempt_capability_pack_snapshot WHERE operation_id=%s",[source_id])
        assert uow.cursor.fetchone()[0]==source_snapshot
        uow.cursor.execute("SELECT status FROM authority_external_effect WHERE external_effect_id=%s",[effect_id])
        assert uow.cursor.fetchone()[0]=="CANCELLED"
    planning.generate(successor, principal=replace(principal, principal_id=successor.actor_id))
    definition = story_planning_generation_definition(application_build_id="synthesis-formation", commit_sha=new_sha)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.repositories.definitions.register(definition)
        uow.cursor.execute("SELECT definition_hash FROM authority_operation_definition WHERE name=%s AND definition_version=%s", [definition["name"], definition["definition_version"]])
        digest = uow.cursor.fetchone()[0]
        uow.commit()
    profile = build_story_planning_pack_profile(Path(__file__).resolve().parents[2], operation_definition_hash=digest, pack_id=harness.pack_id)
    harness._base_manifest, harness._base_catalog = profile.manifest, profile.artifact_catalog
    approved = harness.register_compile_approve("1.3.0", generation=3, approval_scope=scope, target_runtime_profile="test", proof_skill_ref=profile.agent_skill_ref, release_sha=new_sha)
    deployment = harness.deploy(approved, environment="test", runtime_profile="test")
    harness.activate(deployment, expected_activation_version=2, environment="test")
    return formation,execution


def _assert_runtime_continuation_once(formation, harness, transport, principal):
    from concurrent.futures import ThreadPoolExecutor
    from novel_forge.modules.story_planning_runtime.application import _command_from_payload
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT source_operation_id,successor_operation_id,source_command,target_release_sha,source_evidence_asset_version_id FROM authority_story_planning_runtime_continuation WHERE project_id=%s",[harness.project_id])
        rows=uow.cursor.fetchall()
        assert len(rows)==1
        source_id,successor_id,payload,target_sha,control_asset=rows[0]
        assert successor_id and source_id!=successor_id
        uow.cursor.execute("SELECT op.status,op.causation_operation_id,snapshot.release_sha,g.candidate_asset_version_id,g.input_snapshot_hash FROM authority_operation op JOIN authority_story_planning_generation g USING(operation_id) JOIN authority_attempt_capability_pack_snapshot snapshot USING(operation_id) WHERE op.operation_id=ANY(%s) ORDER BY op.status",[[source_id,successor_id]])
        source,successor=uow.cursor.fetchall()
        assert source[0]=="CANCELLED" and source[3] is None
        assert successor[0]=="SUCCEEDED" and successor[1]==source_id and successor[2]==target_sha
        assert source[2]!=target_sha and source[4]==successor[4]
        uow.cursor.execute("SELECT input_asset_snapshot FROM authority_operation WHERE operation_id=%s",[successor_id])
        assert all(item["asset_version_id"] != control_asset for item in uow.cursor.fetchone()[0])
    command=_command_from_payload(payload)
    worker=replace(principal,principal_id=command.actor_id)
    before=len(transport.calls)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes=list(pool.map(lambda version:formation.generation.planning.generate(replace(command,execution_contract_version=version),principal=worker),["1.15.0","1.17.0"]))
    assert len({item.candidate_asset_version_id for item in outcomes})==1
    assert all(item.generation_operation_id==successor_id for item in outcomes)
    assert len(transport.calls)==before


def test_creative_validation_native_controlled_process_to_internal_acceptance(tmp_path, monkeypatch):
    test_native_formation_generates_foundation_from_author_brief(
        tmp_path, monkeypatch, False, False, False, False, False, False, 1,
        creative_validation=True,
    )


def test_native_author_adoption_result_repair_and_legacy_receipt_replay(tmp_path, monkeypatch):
    test_native_formation_generates_foundation_from_author_brief(
        tmp_path, monkeypatch, True, False, False, False, False, False, 1,
        author_result_repair=True,
    )


def test_native_retained_valid_result_admission_without_another_provider_call(tmp_path, monkeypatch):
    test_native_formation_generates_foundation_from_author_brief(
        tmp_path, monkeypatch, False, False, False, False, False, False, 1,
        creative_validation=True, valid_result_admission=True,
    )


def _recover_capacity_formation(*, harness, chapter_pack, principal, pack_actor, settings, env, registry, transport, admitted, monkeypatch, routing=False, input_order=False):
    from concurrent.futures import ThreadPoolExecutor
    from novel_forge.modules.command_kernel.cancellation import CancelCommand, request_cancellation
    from novel_forge.modules.capability_packs.validation_deployment import register_validation_runtime_definitions, install_chapter_validation_pack
    from tests.integration.creative_validation_production_support import install_planning
    from novel_forge.modules.story_planning_runtime.runtime_continuation import require_binding
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT o.operation_id,o.version,o.command_payload->'payload' FROM authority_operation o JOIN authority_story_planning_generation g USING(operation_id) WHERE o.project_id=%s AND o.status=%s", [harness.project_id,"FAILED_FINAL" if input_order else "FAILED_RETRYABLE"])
        source, version, original = uow.cursor.fetchone()
        uow.cursor.execute("SELECT count(*) FROM authority_external_effect WHERE operation_id=%s", [source])
        assert uow.cursor.fetchone()[0] == 0
    before = len(transport.calls)
    if input_order:
        cancelled = {"status":"FAILED_FINAL", "version":version}
    else:
        cancelled = request_cancellation(DATABASE_URL,CancelCommand(operation_id=source,project_id=harness.project_id,
            actor_id=principal.principal_id,expected_version=version,reason="native capacity successor; zero dispatch",
            idempotency_key=source+":capacity-cancel",trace_id=harness.project_id,correlation_id=harness.project_id),settle_undispatched=True)
        assert cancelled["status"] == "CANCELLED"
    sha = "f"*40
    hashes = register_validation_runtime_definitions(DATABASE_URL,application_build_id=harness.application_build_id,commit_sha=sha)
    harness.release_sha=sha
    if routing:
        from novel_forge.modules.authority_handler_runtime.policy_commands import configure_owned_policy
        from tests.unit.test_creative_execution_template import template
        value = template(harness.book_ids[0], version="creative-execution-template.v2", repair_routing={
            "version": "native-repair-routing.v1", "max_same_route_repairs": 2})
        value["allowed_candidates"] = ["codex-cli:gpt-test:high"]
        configure_owned_policy(database_url=DATABASE_URL, owner="PROVIDER_ROUTING", project_id=harness.project_id,
            workspace_id=harness.workspace_id, principal=pack_actor, application_build_id=harness.application_build_id,
            commit_sha=sha, idempotency_key=harness.project_id+":repair-policy-v2", trace_id=harness.project_id,
            correlation_id=harness.project_id, content={"policy_version":"creative-e2e.v2", "task_overrides":[],
                "reason":"explicit successor for undispatched native repair", "execution_templates":[value]})
    harness.pack_id += ".capacity"
    chapter_pack.pack_id += ".capacity"
    install_chapter_validation_pack(DATABASE_URL,repository_root=Path(__file__).resolve().parents[2],project_id=harness.project_id,
        workspace_id=harness.workspace_id,book_id=harness.book_ids[0],application_build_id=harness.application_build_id,commit_sha=sha,
        compiler=pack_actor,approver=pack_actor,agent_admin=pack_actor,pack_id_override=chapter_pack.pack_id)
    profile=build_story_planning_pack_profile(Path(__file__).resolve().parents[2],operation_definition_hash=hashes["planning"],
        pack_id=harness.pack_id,planning_task_token_budget=None if routing else 128000)
    install_planning(harness,profile,pack_actor)
    env.update(NOVEL_FORGE_COMMIT_SHA=sha,NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID=harness.pack_id,NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID=chapter_pack.pack_id)
    execution=build_production_execution_composition(settings,env=env,provider_registry=registry,planning_fixture_factory=transport.planning,chapter_fixture_factory=transport.chapter)
    chapter=build_chapter_authority_application(settings,execution=execution,env=env)
    composition=build_book_production_composition(settings,principal=principal,execution=execution,chapter_application=chapter,env=env)
    formation=composition.formation
    planning=formation.generation.planning
    def register():
        return planning.register_runtime_continuation(source,project_id=harness.project_id,principal=principal,
            expected_source_version=cancelled["version"],decision_evidence={"authorization_ref":"member-grant",
                "authorized_reasoning_effort":"high","reason":"same task and repair count; capacity only"},trace_id=harness.project_id,correlation_id=harness.project_id)
    from novel_forge.modules.story_planning_runtime import preflight_continuation
    from novel_forge.modules.command_kernel.errors import KernelError
    with monkeypatch.context() as strict:
        verified=preflight_continuation.verify_template_provenance
        strict.setattr(preflight_continuation,"verify_template_provenance",lambda *args: {**verified(*args),"mode":"STRICT_PRODUCTION"})
        with pytest.raises(KernelError,match="PLANNING_RUNTIME_CONTINUATION_FAILURE_NOT_ALLOWED" if routing and not input_order else "PLANNING_RUNTIME_CONTINUATION_POLICY_REQUIRED"):
            register()
    with ThreadPoolExecutor(max_workers=2) as pool:
        records=list(pool.map(lambda _:register(),range(2)))
    assert len({r["operation_id"] for r in records})==1 and len(transport.calls)==before
    binding=require_binding(DATABASE_URL,records[0]["continuation_id"])
    assert binding["source_command"]==original
    assert binding["successor_command"]["repair_number"]==original["repair_number"]==(2 if input_order else 1)
    if not routing:
        failed=formation.require(admitted.formation_run_id)
        formation.resume(admitted.formation_run_id,expected_version=failed["version"],principal=principal)
    return formation,execution,chapter,composition


def test_native_undispatched_result_repair_capacity_successor_preserves_raw_task(tmp_path,monkeypatch):
    test_native_formation_generates_foundation_from_author_brief(tmp_path,monkeypatch,author_guided=True,
        result_repair=False,runtime_recovery=False,evaluation_recovery=False,manual_review=False,advice_only=False,
        target_chapters=1,creative_validation=True,author_result_repair=True,capacity_continuation=True)


def test_native_bounded_semantic_repair_reaches_review_acceptance_and_replays_without_calls(tmp_path, monkeypatch):
    test_native_formation_generates_foundation_from_author_brief(tmp_path, monkeypatch, False,
        False, False, False, False, False, 1, creative_validation=True, semantic_repair=True)


def test_native_undispatched_route_repair_successor_preserves_candidate_counter_and_acceptance(tmp_path, monkeypatch):
    test_native_formation_generates_foundation_from_author_brief(tmp_path, monkeypatch, False,
        False, False, False, False, False, 1, creative_validation=True, semantic_repair=True,
        route_continuation=True)


def test_native_failed_final_input_order_successor_preserves_terminal_history_and_counter(tmp_path, monkeypatch):
    test_native_formation_generates_foundation_from_author_brief(tmp_path, monkeypatch, False,
        False, False, False, False, False, 1, creative_validation=True, semantic_repair=True,
        input_order_continuation=True)
