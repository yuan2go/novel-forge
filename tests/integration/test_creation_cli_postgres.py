import json
from pathlib import Path

import pytest

from novel_forge.cli.authority import _authority_parser
from novel_forge.cli.creation import run_creation_command
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.capability_pack_postgres_support import CapabilityPackPostgresHarness
from tests.integration.creative_validation_production_support import controlled_member_environment


@pytest.mark.parametrize("full_creation,generated_title", [(False, False), (True, False), (True, True)],
    ids=["admission-boundaries", "controlled-process-main-chain", "native-generated-title"])
def test_native_start_freezes_current_work_and_reuses_original_formation(tmp_path, monkeypatch, full_creation, generated_title):
    harness = CapabilityPackPostgresHarness("creation-cli-full" if full_creation else "creation-cli-admission")
    project = harness.project_id + "-native"
    root = Path(__file__).resolve().parents[2]
    from tests.integration.synthesis_production_support import SynthesisTransport
    transport = SynthesisTransport() if full_creation else None
    if transport:
        transport.chapter.controlled_prose = (Path(__file__).resolve().parents[1] / "fixtures/creation/short-arc/controlled-prose.txt").read_text()
    if full_creation:
        from novel_forge.api import authority_dependencies
        build_book = authority_dependencies.build_book_production_composition
        checkpoints = []
        def fail_once(checkpoint):
            if checkpoint == "after_business_projection_update":
                checkpoints.append(checkpoint)
                if len(checkpoints) == 3:
                    raise RuntimeError("controlled projection interruption")
        def recovering_book(*values, **options):
            composition = build_book(*values, **options)
            composition.formation.generation.book_design.fault_injector = fail_once
            return composition
        monkeypatch.setattr(authority_dependencies, "build_book_production_composition", recovering_book)
        from novel_forge.modules.chapter_authority.model_effects import ExternalEffectChapterModelPort
        from novel_forge.modules.command_kernel.errors import KernelError
        invoke = ExternalEffectChapterModelPort.invoke
        quality_order = []
        def unavailable_once(port, request, *, stage, **options):
            if stage.startswith("quality_"):
                quality_order.append(stage)
                if quality_order == ["quality_structural"]:
                    raise KernelError("PROVIDER_ROUTING_BLOCKED", "controlled independent task temporarily unavailable")
            return invoke(port, request, stage=stage, **options)
        monkeypatch.setattr(ExternalEffectChapterModelPort, "invoke", unavailable_once)
        normal = transport.planning
        def bounded_fixture(stage, values):
            result = normal(stage, values)
            if stage == "creative.candidates.generate":
                result["serialization_potential"] = None
                for declaration in result.get("applicability", []):
                    if declaration["field_path"] in {"$.serialization_potential", "/serialization_potential"}:
                        declaration.update(status="NOT_APPLICABLE", rationale="Bounded controlled fixture")
            def visit(value):
                if isinstance(value, dict):
                    for key, child in value.items():
                        if key == "serialization_function":
                            value[key] = None
                        else:
                            visit(child)
                elif isinstance(value, list):
                    for child in value:
                        visit(child)
            visit(result)
            return result
        transport.planning = bounded_fixture
    env = controlled_member_environment(tmp_path, {
        "NOVEL_FORGE_APPLICATION_BUILD_ID": harness.application_build_id,
        "NOVEL_FORGE_COMMIT_SHA": harness.release_sha,
        "NOVEL_FORGE_MODEL_PROVIDER": "codex-cli", "NOVEL_FORGE_MODEL": "gpt-test",
        "NOVEL_FORGE_PLANNING_PROVIDER": "codex-cli", "NOVEL_FORGE_PLANNING_MODEL": "gpt-test",
        "NOVEL_FORGE_LOCAL_OPERATOR_PRINCIPAL_ID": "native-creation-operator",
        "NOVEL_FORGE_AUTHORITY_PROJECT_SCOPE": project,
    }, monkeypatch, transport)
    if full_creation:
        catalog = json.loads(env["NOVEL_FORGE_CODEX_ROUTER_MODELS"])
        for model in catalog["models"]:
            model["reasoning"] = "medium"
        env["NOVEL_FORGE_CODEX_ROUTER_MODELS"] = json.dumps(catalog)
        env["NOVEL_FORGE_CODEX_ROUTER_REASONING_EFFORT"] = "medium"
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("NOVEL_FORGE_ROUTER_PROVIDERS", "codex-cli,deepseek")
    monkeypatch.setenv("NOVEL_FORGE_DEEPSEEK_BUDGET_TEMPLATE_FILE", str(tmp_path / "missing-paid-template.json"))
    inputs = {"version": "creation-request.v1", "title": "Current author work", "target_chapters": 1 if full_creation else 17,
        "chapter_length": {"minimum": 800, "maximum": 4000},
        "language_contract": {"required_language": "zh-CN"},
        "brief": {"creative_brief_contract_version": "creative-brief-v2", "idea": "An archivist confronts contradictory accounts of a flood.",
            "genre": "social mystery", "audience": "adult readers", "constraints": ["Preserve the author's intended scope."],
            "source_boundaries": ["Original work; do not copy protected expression."]}}
    if generated_title:
        inputs["version"] = "creation-request.v2"
        inputs.pop("title")
    input_file = tmp_path / "request.json"
    input_file.write_text(json.dumps(inputs))
    book = project + "-new-book"
    parser = _authority_parser()
    args = parser.parse_args(["authority-creation", "start", "--project-id", project,
        "--workspace-id", harness.workspace_id + "-new", "--book-id", book, "--input-file", str(input_file),
        "--idempotency-key", "native-create", "--repository-root", str(root), "--maximum-ticks", "100",
        "--creative-selection", "FIRST_ADMITTED", "--foreground", "--execution-template-file", str(root / "config/execution_templates/creative_validation.json")])
    if not full_creation:
        args.yield_after_window = True
        monkeypatch.setattr("novel_forge.modules.book_authority.creation_runtime.continue_creation",
            lambda **values: {"formation_run_id": values["formation_run_id"], "stop_reason": "YIELDED_CHECKPOINT"})
    settings = IndustrialSettings(root=tmp_path, database_url=DATABASE_URL, environment="validation")
    if transport is not None:
        transport.database_url = settings.database_url
    first = run_creation_command(settings, args)
    if full_creation:
        if first["stop_reason"] != "FORMATION_FAILED":
            pytest.fail(json.dumps({"stop_reason": first.get("stop_reason"),
                "reason_code": first.get("reason_code"), "checkpoint": first.get("checkpoint")}, ensure_ascii=False))
        before_recovery = len(transport.calls)
        recovery_args = parser.parse_args(["authority-creation", "continue", "--project-id", project,
            "--formation-run-id", first["formation_run_id"], "--repository-root", str(root), "--maximum-ticks", "2"])
        first = run_creation_command(settings, recovery_args)
        assert first["stop_reason"] == "COMPLETED", first
        assert before_recovery == 7
        assert len(transport.calls) == before_recovery
        assert quality_order[0] == quality_order[-1] == "quality_structural"
        assert len(set(quality_order[1:-1])) == 4
        calls = (len(transport.calls), len(transport.chapter.calls))
    assert run_creation_command(settings, args) == first
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT frozen_stage_inputs FROM authority_story_formation_run WHERE formation_run_id=%s", [first["formation_run_id"]])
        frozen = uow.cursor.fetchone()[0]["generation_policy"]
        assert frozen["contract_version"] == "formation-generation.v4"
        assert frozen["target_chapters"] == inputs["target_chapters"]
        assert frozen["creation_input_policy"]["profiles"]["production_profile"]["content"]["language_contract"] == inputs["language_contract"]
        assert frozen["creation_input_policy"]["profiles"]["production_profile"]["content"]["chapter_length"] == inputs["chapter_length"]
        if generated_title:
            from novel_forge.modules.book_design_authority.query import BookDesignAuthorityQuery
            current_book = BookDesignAuthorityQuery(DATABASE_URL).require_book(project_id=project, book_id=book)
            assert current_book["title"] == "潮痕录"
            assert current_book["title_source_asset_version_id"] == current_book["active_book_design_version_id"]
            uow.cursor.execute("SELECT content->>'title' FROM authority_asset_version WHERE asset_version_id=%s", [current_book["book_asset_version_id"]])
            assert uow.cursor.fetchone()[0] == "Untitled — pending native Foundation"
            assert frozen["creation_input_policy"]["profiles"]["production_profile"]["content"]["title_generation_contract"] == "generated-book-title.v1"
        uow.cursor.execute("SELECT count(*) FROM authority_book WHERE project_id=%s AND book_id=%s", [project, book])
        assert uow.cursor.fetchone()[0] == 1
        uow.cursor.execute("SELECT count(*) FROM authority_capability_pack_approval approval JOIN authority_operation op ON op.operation_id=approval.decided_by_operation_id WHERE op.project_id=%s", [project])
        assert uow.cursor.fetchone()[0] == 0
        if full_creation:
            uow.cursor.execute("""SELECT consumption.chapter_plan_asset_version_id,
                outcome.content->>'chapter_plan_version_id', plan.asset_type
                FROM authority_narrative_realization_consumption consumption
                JOIN authority_asset_version outcome ON outcome.asset_version_id=consumption.chapter_outcome_asset_version_id
                JOIN authority_asset outcome_asset ON outcome_asset.asset_id=outcome.asset_id
                JOIN authority_asset_version execution_plan ON execution_plan.asset_version_id=outcome.content->>'chapter_plan_version_id'
                JOIN authority_asset plan ON plan.asset_id=execution_plan.asset_id
                WHERE outcome_asset.project_id=%s""", [project])
            accepted_plan_bindings = uow.cursor.fetchall()
            assert accepted_plan_bindings
            assert all(source != execution and kind == "chapter_plan" for source, execution, kind in accepted_plan_bindings)
            uow.cursor.execute("SELECT count(*) FROM state_event WHERE project_id=%s AND event_type='external_effect.storage_admitted'", [project])
            assert uow.cursor.fetchone()[0] > 0
            uow.cursor.execute("SELECT external_effect_id,operation_id FROM authority_external_effect WHERE project_id=%s AND effect_type='blob.upload' LIMIT 1", [project])
            effect_id, operation_id = uow.cursor.fetchone()
    if full_creation:
        from novel_forge.modules.command_kernel.external_effect_runtime import _admit_effect_adapter, _read_effect, EffectCommandContext
        from novel_forge.modules.command_kernel.external_effect_adapters import MinioObjectStoreExternalEffectAdapter, FakeDeterministicProvider
        from novel_forge.modules.command_kernel.errors import KernelError
        context = EffectCommandContext(operation_id, project, "native-creation-operator", "storage-negative", project)
        effect = _read_effect(DATABASE_URL, effect_id, project)
        effect["request_payload"] = {**effect["request_payload"], "object_key": "unauthorized-object"}
        with pytest.raises(KernelError, match="BLOB_EXECUTION_ADMISSION_CONFLICT|OPERATION_STATUS_CONFLICT"):
            _admit_effect_adapter(DATABASE_URL, context, effect=effect,
                adapter=MinioObjectStoreExternalEffectAdapter(object(), bucket="isolated-fixture"))
        with pytest.raises(RuntimeError, match="legacy execution is blocked"):
            _admit_effect_adapter(DATABASE_URL, context, effect=effect, adapter=FakeDeterministicProvider("success"))
    continuation = parser.parse_args(["authority-creation", "continue", "--project-id", project,
        "--formation-run-id", first["formation_run_id"], "--repository-root", str(root)])
    continuation.yield_after_window = not full_creation
    assert run_creation_command(settings, continuation) == first
    if full_creation:
        assert (len(transport.calls), len(transport.chapter.calls)) == calls
    else:
        from copy import deepcopy
        from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
        from novel_forge.modules.authority_handler_runtime.policy_commands import configure_owned_policy
        from novel_forge.modules.production_execution.routing_runtime import PostgresRoutingRegistry
        registry = PostgresRoutingRegistry(DATABASE_URL)
        policy = deepcopy(registry.policy(project)["policy"])
        policy.update(policy_version="explicit-literary-objective", reason="controlled explicit validation objective")
        policy["execution_templates"][0]["require_literary_qualification"] = True
        configure_owned_policy(database_url=DATABASE_URL, owner="PROVIDER_ROUTING", project_id=project,
            workspace_id=args.workspace_id, principal=build_trusted_principal_resolver().resolve_api_principal(),
            application_build_id=harness.application_build_id, commit_sha=harness.release_sha,
            idempotency_key=project + ":require-literary", trace_id=project, correlation_id=project, content=policy)
        assert run_creation_command(settings, args) == first
        assert registry.policy(project)["policy"] == policy
    with pytest.raises(ValueError, match="USE_ORIGINAL_FORMATION"):
        run_creation_command(settings, replace_args(args, idempotency_key="new-task"))
    with pytest.raises(PermissionError):
        run_creation_command(settings, replace_args(continuation, project_id="outside-authorized-project"))


def replace_args(args, **changes):
    from argparse import Namespace
    return Namespace(**{**vars(args), **changes})


@pytest.mark.parametrize(
    "mode",
    [
        "complete",
        "partial-alternative",
        "cancel",
        "no-progress",
        "ordinary-continue",
        "repair-exhausted",
        "capacity-recovery",
        "capacity-foundation",
        "capacity-foundation-new-cause",
        "pending-deployment",
        "capacity-repair",
        "capacity-retained-repair-cause",
        "world-result-repair",
        "world-primary-result-repair",
        "world-causal-result-repair",
        "world-causal-legacy-replay",
        "world-causal-dead-letter-replay",
    ],
)
def test_durable_creation_compares_nonfirst_candidate_and_worker_resumes_exact_source(
    tmp_path, monkeypatch, mode
):
    from novel_forge.modules.book_authority.creation_runtime import schedule_creation_jobs, creation_status
    from novel_forge.modules.runtime_job import RuntimeJobAuthority
    from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
    from novel_forge.workers.book_authority import execute_creation_worker_claim
    from tests.integration.synthesis_production_support import SynthesisTransport

    from novel_forge.modules.command_kernel.errors import KernelError

    harness = CapabilityPackPostgresHarness("durable-creation")
    project = harness.project_id + "-native"
    root = Path(__file__).resolve().parents[2]
    transport = SynthesisTransport()
    if mode == "pending-deployment":
        transport.interrupt_once_stage = "book_plan.generate"
    transport.chapter.controlled_prose = (Path(__file__).resolve().parents[1] / "fixtures/creation/short-arc/controlled-prose.txt").read_text()
    if mode.startswith("capacity-"):
        from novel_forge.modules.story_planning_runtime.execution import (
            PostgresPlanningExecutionPreparer,
        )
        from novel_forge.modules.command_kernel.errors import KernelError

        build_context = PostgresPlanningExecutionPreparer._context_bundle

        def capacity_failure(preparer, **values):
            command = values["command"]
            if mode == "capacity-foundation-new-cause" and command.generator_operation_name == "character.cast.generate" and command.runtime_continuation_id and not values.get("preflight_only"):
                raise KernelError("PLANNING_CONTEXT_BINDING_FAILED", "A different current successor failure requires correction")
            if (
                command.generator_operation_name == ("character.cast.generate" if mode.startswith("capacity-foundation") else "chapter_group_plan.generate")
                and not command.runtime_continuation_id
                and (mode in {"capacity-recovery", "capacity-foundation", "capacity-foundation-new-cause"} or command.repair_of_candidate_id)
            ):
                raise KernelError(
                    "PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED",
                    "Controlled native pre-send capacity failure",
                )
            return build_context(preparer, **values)

        monkeypatch.setattr(
            PostgresPlanningExecutionPreparer, "_context_bundle", capacity_failure
        )
    planning = transport.planning
    creative_calls = []
    group_calls = []
    world_calls = []
    primary_calls = []
    if mode == "capacity-retained-repair-cause":
        from novel_forge.modules.story_planning_runtime import (
            application as planning_application,
        )

        native_admit = planning_application.admit_command

        def retain_repair_cause(database_url, request, **options):
            payload = request["input"]["payload"]
            if payload.get("runtime_continuation_id") and payload.get(
                "repair_of_candidate_id"
            ):
                with AuthorityUnitOfWork(database_url) as uow:
                    uow.cursor.execute(
                        "SELECT operation_id FROM authority_story_planning_generation WHERE candidate_asset_version_id=%s",
                        [payload["repair_of_candidate_id"]],
                    )
                    request = {
                        **request,
                        "causation_operation_id": uow.cursor.fetchone()[0],
                    }
            return native_admit(database_url, request, **options)

        monkeypatch.setattr(planning_application, "admit_command", retain_repair_cause)

    historical_classifier_restored = False
    if mode in {"world-causal-legacy-replay", "world-causal-dead-letter-replay"}:
        from novel_forge.modules.story_planning_runtime.world_preparation import (
            PlanningWorldPreparation,
        )

        from novel_forge.modules.command_kernel.worker_execution import WorkerFailureClassifier, WorkerFailureClass

        native_world_prepare = PlanningWorldPreparation.prepare
        native_classifier = WorkerFailureClassifier.classify
        historical_classifier_source = "f9e1ee5e115fd47b8bb9d97a35aa2813b7e04609"
        historical_errors = set()
        historical_snapshots = []
        legacy_block = []
        historical_classifier_restored = False

        def historical_failure_class(error):
            if error in historical_errors:
                assert error.historical_classifier_source == historical_classifier_source
                return WorkerFailureClass.RETRYABLE
            return native_classifier(error)

        monkeypatch.setattr(WorkerFailureClassifier, "classify", staticmethod(historical_failure_class))

        if mode == "world-causal-dead-letter-replay":
            from novel_forge.modules.command_kernel import generation_policy
            current_generation_operation = generation_policy.pure_generation_operation

            def historical_attempt_policy(cursor, operation_id, project_id):
                if legacy_block and operation_id == legacy_block[0] and not historical_classifier_restored:
                    return False
                return current_generation_operation(cursor, operation_id, project_id)

            monkeypatch.setattr(generation_policy, "pure_generation_operation", historical_attempt_policy)

        def historical_gate_checkpoint(preparation, **values):
            try:
                return native_world_prepare(preparation, **values)
            except KernelError as error:
                if (
                    error.code == "WORLD_PREPARATION_RESULT_INVALID"
                    and (not legacy_block or (mode == "world-causal-dead-letter-replay" and values["command"].repair_number == 0))
                ):
                    assert values["command"].repair_number == 0
                    historical_error = KernelError("WORLD_PREPARATION_BLOCKED", error.message)
                    historical_error.historical_classifier_source = historical_classifier_source
                    historical_error.historical_operation_id = values["operation_id"]
                    historical_errors.add(historical_error)
                    legacy_block.append(historical_error.historical_operation_id)
                    raise historical_error from error
                raise

        monkeypatch.setattr(
            PlanningWorldPreparation, "prepare", historical_gate_checkpoint
        )

    def bounded_planning(stage, inputs):
        result = planning(stage, inputs)
        if stage == "world_candidates.generate":
            world_calls.append(inputs)
            if mode == "world-result-repair" and len(world_calls) <= 2:
                result = {
                    **result,
                    "disposition": "CANDIDATES",
                    "reason": "Controlled malformed typed transition only.",
                    "candidates": [
                        {
                            "transition": {
                                "payload_json": json.dumps({"story_time": "chapter:1"})
                            },
                            "affected_entities": [
                                inputs["world_preparation"]["approved_entity_ids"][0]
                            ],
                            "world_consequences": [
                                "Controlled proposed consequence; not accepted fact."
                            ],
                            "arc_refs": [],
                            "obligation_refs": [],
                            "risks": [],
                            "soft_assumptions": [],
                            "narrative_preferences": [],
                            "rationale": "Controlled Schema-valid but domain-invalid result.",
                            "preparation_paths": [],
                            "information_scope": {"disclosures": []},
                        }
                    ],
                }
            if (
                mode in {"world-causal-result-repair", "world-causal-legacy-replay", "world-causal-dead-letter-replay"}
                and len(world_calls) <= 2
            ):
                identity = inputs["world_preparation"]["approved_entity_ids"][0]
                proposal = {
                    "transition_id": "blocked_future",
                    "actor_id": identity,
                    "camera": "ON_CAMERA",
                    "story_time": {
                        "timeline_id": "controlled",
                        "start_ordinal": 1,
                        "end_ordinal": 1,
                        "precision": "EXACT",
                        "label": "controlled",
                    },
                    "action": "act on the approved faction pressure",
                    "action_mode": "ROUTINE",
                    "state_kind": "world_state",
                    "entity_key": identity,
                    "changes": {"status": "controlled"},
                    "requirements": [],
                    "cause_refs": ["controlled:missing-source"],
                    "epistemic_basis": [],
                }
                result = {
                    **result,
                    "disposition": "CANDIDATES",
                    "reason": "Controlled causal rejection, not a fabricated manuscript flaw.",
                    "candidates": [
                        {
                            "transition": {"payload_json": json.dumps(proposal)},
                            "affected_entities": [
                                inputs["world_preparation"]["approved_entity_ids"][0]
                            ],
                            "world_consequences": [
                                "Controlled proposed consequence; not accepted fact."
                            ],
                            "arc_refs": [],
                            "obligation_refs": [],
                            "risks": [],
                            "soft_assumptions": [],
                            "narrative_preferences": [],
                            "rationale": "Controlled unavailable causal support.",
                            "preparation_paths": [],
                            "information_scope": {"disclosures": []},
                        }
                    ],
                }
        if stage == "chapter_plan.generate":
            primary_calls.append(inputs)
            if mode == "world-primary-result-repair" and len(primary_calls) <= 2:
                result["objective"] = " "
        if stage == "chapter_group_plan.generate":
            group_calls.append(stage)
            if (
                mode in {"capacity-repair", "capacity-retained-repair-cause"}
                and len(group_calls) == 1
            ):
                result["narrative_event_chain"][0]["causes"] = [
                    "controlled-missing-predecessor"
                ]
        if stage == "creative.candidates.generate":
            creative_calls.append(stage)
            result["serialization_potential"] = None
            for declaration in result.get("applicability", []):
                if declaration["field_path"] in {"$.serialization_potential", "/serialization_potential"}:
                    declaration.update(status="NOT_APPLICABLE", rationale="Bounded controlled fixture")
        def visit(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == "serialization_function":
                        value[key] = None
                    else:
                        visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        visit(result)
        if mode == "partial-alternative" and stage == "creative.candidates.generate" and len(creative_calls) > 1:
            result["applicability"][0]["field_path"] = "serialization_potential"
        return result
    transport.planning = bounded_planning
    env = controlled_member_environment(tmp_path, {
        "NOVEL_FORGE_APPLICATION_BUILD_ID": harness.application_build_id,
        "NOVEL_FORGE_COMMIT_SHA": harness.release_sha,
        "NOVEL_FORGE_MODEL_PROVIDER": "codex-cli", "NOVEL_FORGE_MODEL": "gpt-test",
        "NOVEL_FORGE_PLANNING_PROVIDER": "codex-cli", "NOVEL_FORGE_PLANNING_MODEL": "gpt-test",
        "NOVEL_FORGE_LOCAL_OPERATOR_PRINCIPAL_ID": "durable-operator",
        "NOVEL_FORGE_AUTHORITY_PROJECT_SCOPE": project,
    }, monkeypatch, transport)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    inputs = {"version": "creation-request.v1", "title": "Durable original work", "target_chapters": 2 if mode == "complete" else 1,
        "chapter_length": {"minimum": 800, "maximum": 4000}, "language_contract": {"required_language": "zh-CN"},
        "brief": {"creative_brief_contract_version": "creative-brief-v2", "idea": "An archivist investigates conflicting flood accounts.",
            "genre": "social mystery", "audience": "adult readers", "constraints": ["Preserve cause and knowledge boundaries."],
            "source_boundaries": ["Original expression only."]}}
    input_file = tmp_path / "request.json"
    input_file.write_text(json.dumps(inputs))
    parser = _authority_parser()
    args = parser.parse_args(["authority-creation", "start", "--project-id", project,
        "--workspace-id", harness.workspace_id + "-new", "--book-id", project + "-book", "--input-file", str(input_file),
        "--idempotency-key", "durable", "--creative-selection", "AUTHOR_COMPARISON", "--repository-root", str(root),
        "--execution-template-file", str(root / "config/execution_templates/creative_validation.json")])
    if mode.startswith("world-"):
        execution_template = json.loads((root / "config/execution_templates/creative_validation.json").read_text())
        execution_template["world_future_preparation"] = "REQUIRED"
        args.execution_template_file = tmp_path / "required-world-execution-template.json"
        args.execution_template_file.write_text(json.dumps(execution_template))
    settings = IndustrialSettings(root=root, database_url=DATABASE_URL, environment="validation")
    transport.database_url = settings.database_url
    first = run_creation_command(settings, args)
    identity = first["formation_run_id"]
    assert first["stop_reason"] == "WORKER_OWNS_CONTINUATION"
    jobs = RuntimeJobAuthority(DATABASE_URL)

    def claim():
        return jobs.claim(runtime_group="book_creation", worker_id="durable-book", lease_seconds=60,
            job_kinds=("BOOK_CREATION_ADVANCE",), subject_kind="STORY_FORMATION_RUN", subject_id=identity)

    if mode == "repair-exhausted":
        def exhausted(**_values):
            from novel_forge.modules.command_kernel.errors import KernelError
            raise KernelError("PLANNING_RESULT_REPAIR_BOUND_EXCEEDED", "Exact raw proposals exhausted their frozen allowance")
        monkeypatch.setattr("novel_forge.modules.book_authority.creation_runtime.continue_creation", exhausted)
        current = claim()
        result = execute_creation_worker_claim(settings, current)
        assert result["wait_class"] == "OWNER_RECOVERY_REQUIRED"
        assert result["failure"]["code"] == "PLANNING_RESULT_REPAIR_BOUND_EXCEEDED"
        assert jobs.get(current.runtime_job_id)["status"] == "SUCCEEDED"
        assert schedule_creation_jobs(DATABASE_URL, formation_run_id=identity) == ()
        assert claim() is None
        status = creation_status(DATABASE_URL, project_id=project, formation_run_id=identity,
            principal=build_trusted_principal_resolver().resolve_api_principal())
        assert status["author_state"] == "OWNER_RECOVERY_REQUIRED"
        assert status["failure"] == result["failure"]
        assert status["recovery_instruction"] == result["recovery_instruction"]
        assert status["responsible_party"] == "RUNTIME_OWNER"
        assert len(transport.calls) == 0
        return

    if mode in {"no-progress", "ordinary-continue"}:
        monkeypatch.setattr("novel_forge.modules.book_authority.creation_runtime.continue_creation",
            lambda **values:{"formation_run_id":identity,"stop_reason":"YIELDED_CHECKPOINT"})
        for _ in range(12):
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("UPDATE authority_runtime_job SET available_at=NOW() WHERE subject_id=%s AND job_kind='BOOK_CREATION_ADVANCE' AND status IN ('READY','RETRY_WAIT')", [identity])
                uow.cursor.execute("UPDATE authority_story_formation_run SET version=version+1 WHERE formation_run_id=%s", [identity])
                uow.commit()
            current = claim()
            assert current is not None
            result = execute_creation_worker_claim(settings, current)
        assert result["wait_class"] == "TECHNICAL_WAIT"
        assert result["stop_reason"] == "YIELDED_CHECKPOINT"
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("UPDATE authority_runtime_job SET available_at=NOW() WHERE subject_id=%s AND job_kind='BOOK_CREATION_ADVANCE' AND status='READY'", [identity])
            uow.commit()
        monkeypatch.setattr("novel_forge.modules.book_authority.creation_runtime.continue_creation",
            lambda **values: {"formation_run_id": identity, "stop_reason": "GENERATION_NO_PROGRESS",
                "failure": {"code": "UNCHANGED_FAILED_RESULT", "operation_id": "retained-operation"}})
        current = claim()
        assert current is not None
        result = execute_creation_worker_claim(settings, current)
        assert result["wait_class"] == "OWNER_RECOVERY_REQUIRED"
        assert result["stop_reason"] == "GENERATION_NO_PROGRESS"
        assert schedule_creation_jobs(DATABASE_URL, formation_run_id=identity) == ()
        assert claim() is None
        assert len(transport.calls) == 0
        if mode == "ordinary-continue":
            continuation = parser.parse_args(["authority-creation", "continue", "--project-id", project,
                "--formation-run-id", identity, "--idempotency-key", "fresh-continuation", "--repository-root", str(root)])
            resumed = run_creation_command(settings, continuation)
            assert len(resumed["scheduled"]) == 1
            repeated = run_creation_command(settings, continuation)
            assert repeated["scheduled"][0]["runtime_job_id"] == resumed["scheduled"][0]["runtime_job_id"]
            assert repeated["scheduled"][0]["deduplicated"]
            restarted = claim()
            assert restarted.input_snapshot["stagnant_windows"] == 0
            assert len(transport.calls) == 0
            return
        recover = parser.parse_args(["authority-creation","recover","--project-id",project,"--formation-run-id",identity,
            "--reason","Operator resolved the isolated scheduling configuration","--idempotency-key","recovery-window","--repository-root",str(root)])
        restored = run_creation_command(settings,recover)
        assert len(restored["scheduled"]) == 1
        replay = run_creation_command(settings,recover)
        assert replay["scheduled"][0]["runtime_job_id"] == restored["scheduled"][0]["runtime_job_id"]
        assert replay["scheduled"][0]["deduplicated"]
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from types import SimpleNamespace
        from novel_forge.api import authority_dependencies as dependencies
        from novel_forge.api.models import product_model_map
        from novel_forge.api.routers.book_authority import create_router
        from novel_forge.api.routers.context import ProductRouterContext
        author = build_trusted_principal_resolver().resolve_api_principal()
        native_execution = dependencies.build_production_execution_composition(settings)
        try:
            native_chapter = dependencies.build_chapter_authority_application(settings, execution=native_execution)
            native = dependencies.build_book_production_composition(settings, principal=author,
                execution=native_execution, chapter_application=native_chapter)
            app = FastAPI()
            app.include_router(create_router(ProductRouterContext(app_settings=settings,models=product_model_map(),
                services=SimpleNamespace(book_production=native))))
            body = {"expected_version":creation_status(DATABASE_URL,project_id=project,formation_run_id=identity,principal=author)["version"],
                    "reason":recover.reason,"idempotency_key":recover.idempotency_key}
            with TestClient(app) as client:
                endpoint = f"/product/production/book-authority/formation-runs/{identity}/resume"
                for _ in range(2):
                    response = client.post(endpoint,json=body)
                    assert response.status_code == 202, response.text
                    assert response.json()["creation"]["coordination"]["runtime_job_id"] == restored["scheduled"][0]["runtime_job_id"]
                drift = client.post(endpoint,json={**body,"reason":"A different request cannot reuse this recovery key"})
                assert drift.status_code == 409, drift.text
        finally:
            native_execution.close()
        assert claim() is not None
        assert len(transport.calls) == 0
        return
    current = claim()
    result = execute_creation_worker_claim(settings, current)
    assert result["wait_class"] == "AUTHOR_DECISION"
    assert len(transport.calls) == 2
    assert schedule_creation_jobs(DATABASE_URL, formation_run_id=identity) == ()
    assert claim() is None
    author = build_trusted_principal_resolver().resolve_api_principal()
    status = creation_status(DATABASE_URL, project_id=project, formation_run_id=identity, principal=author)
    candidates = status["recovery_instruction"]["candidate_asset_version_ids"]
    assert len(candidates) == (1 if mode == "partial-alternative" else 2)
    if mode == "partial-alternative":
        assert len(status["recovery_instruction"]["generation_failures"]) == 1
    if mode == "cancel":
        cancellation = parser.parse_args(["authority-creation", "cancel", "--project-id", project,
            "--formation-run-id", identity, "--reason", "Author cancels isolated work", "--idempotency-key", "cancel-work", "--repository-root", str(root)])
        cancelled = run_creation_command(settings, cancellation)
        assert cancelled["stop_reason"] == "CANCELLED"
        assert cancelled["cancellation"]["frozen_input_digest"]
        assert schedule_creation_jobs(DATABASE_URL, formation_run_id=identity) == ()
        assert claim() is None
        assert run_creation_command(settings, args)["stop_reason"] == "CANCELLED"
        assert len(transport.calls) == 2
        return
    if mode == "complete":
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from types import SimpleNamespace
        from novel_forge.api import authority_dependencies as dependencies
        from novel_forge.api.models import product_model_map
        from novel_forge.api.routers.book_authority import create_router
        from novel_forge.api.routers.context import ProductRouterContext
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("SELECT expected_book_version,frozen_stage_inputs FROM authority_story_formation_run WHERE formation_run_id=%s", [identity])
            source_version, source = uow.cursor.fetchone()
        native_execution = dependencies.build_production_execution_composition(settings)
        try:
            native_chapter = dependencies.build_chapter_authority_application(settings, execution=native_execution)
            native = dependencies.build_book_production_composition(settings, principal=author,
                execution=native_execution, chapter_application=native_chapter)
            app = FastAPI()
            app.include_router(create_router(ProductRouterContext(app_settings=settings,models=product_model_map(),
                services=SimpleNamespace(book_production=native))))
            body = {"project_id":project,"workspace_id":args.workspace_id,"expected_book_version":source_version,
                "idempotency_key":"durable","creative_brief_asset_version_id":source["creative_brief_asset_version_id"],
                "creative_brief_content_hash":source["creative_brief_content_hash"],
                "production_intent":{key:inputs[key] for key in ("title","target_chapters","language_contract","chapter_length")}}
            with TestClient(app) as client:
                endpoint = f"/product/production/book-authority/books/{args.book_id}/formation-runs"
                stale = client.post(endpoint,json={**body,"expected_book_version":source_version+1})
                assert stale.status_code == 409, stale.text
                response = client.post(endpoint,json=body)
                assert response.status_code == 202, response.text
                assert response.json()["formation_run_id"] == identity
                malformed = client.post(endpoint,json={**body,"production_intent":{**body["production_intent"],"chapter_length":{"minimum":5,"maximum":1}}})
                assert malformed.status_code == 422
            assert len(transport.calls) == 2
        finally:
            native_execution.close()
    selected = candidates[0] if mode == "partial-alternative" else candidates[1]
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT content_hash FROM authority_asset_version WHERE asset_version_id=%s", [selected])
        chosen_hash = uow.cursor.fetchone()[0]
    chosen = parser.parse_args(["authority-creation", "choose", "--project-id", project,
        "--formation-run-id", identity, "--candidate-version", selected, "--candidate-hash", chosen_hash,
        "--reason", "Controlled author comparison chooses the second exact branch; no literary preference proof.",
        "--idempotency-key", "choose-second", "--repository-root", str(root)])
    run_creation_command(settings, chosen)
    run_creation_command(settings, chosen)
    if mode == "complete":
        from novel_forge.modules.book_authority import creation_runtime
        advance = creation_runtime.execute_creation_claim
        windows = []
        def bounded_window(*args, **options):
            if not windows:
                options["maximum_ticks"] = 2
            windows.append(True)
            return advance(*args, **options)
        monkeypatch.setattr(creation_runtime, "execute_creation_claim", bounded_window)
        handoff = RuntimeJobAuthority.complete_and_schedule_continuation
        lost = []
        def response_lost(authority, *values, **options):
            result = handoff(authority, *values, **options)
            if not lost:
                lost.append(True)
                raise OSError("controlled committed handoff response loss")
            return result
        monkeypatch.setattr(RuntimeJobAuthority, "complete_and_schedule_continuation", response_lost)

    def capture_historical_checkpoint(source_id, *, require_dead_letter=False):
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("SELECT status FROM authority_operation WHERE operation_id=%s", [source_id])
            source_status = uow.cursor.fetchone()[0]
            if require_dead_letter:
                assert source_status == "DEAD_LETTER"
            assert source_status in {"FAILED_RETRYABLE", "DEAD_LETTER"}
            uow.cursor.execute("SELECT to_jsonb(a) FROM authority_attempt a WHERE operation_id=%s ORDER BY attempt_number", [source_id])
            attempts = [row[0] for row in uow.cursor.fetchall()]
            assert attempts and all(row["status"] == "FAILED_RETRYABLE" for row in attempts)
            uow.cursor.execute("SELECT to_jsonb(e),to_jsonb(b) FROM authority_external_effect e JOIN authority_budget_reservation b USING(external_effect_id) WHERE e.operation_id=%s ORDER BY e.external_effect_id", [source_id])
            receipts = uow.cursor.fetchall()
            assert len(receipts) == 2
            assert all(effect["status"] == "SUCCEEDED" and budget["status"] == "SETTLED" for effect, budget in receipts)
            uow.cursor.execute("SELECT candidate_asset_version_id,repair_number FROM authority_story_planning_generation WHERE operation_id=%s", [source_id])
            assert uow.cursor.fetchone() == (None, 0)
            uow.cursor.execute("SELECT count(*) FROM authority_book_chapter_acceptance WHERE project_id=%s AND status='COMMITTED'", [project])
            assert uow.cursor.fetchone() == (0,)
        historical_snapshots.append({"source_operation_id": source_id, "source_status": source_status,
            "attempts": attempts, "receipts": receipts, "world_calls": len(world_calls),
            "classifier_source": historical_classifier_source})
        return source_status

    def restore_dead_letter_classifier():
        nonlocal historical_classifier_restored
        if mode != "world-causal-dead-letter-replay" or historical_classifier_restored or not legacy_block:
            return False
        source_id = legacy_block[0]
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("SELECT status FROM authority_operation WHERE operation_id=%s", [source_id])
            source_status = uow.cursor.fetchone()[0]
        if source_status != "DEAD_LETTER":
            return False
        capture_historical_checkpoint(source_id, require_dead_letter=True)
        monkeypatch.setattr(WorkerFailureClassifier, "classify", staticmethod(native_classifier))
        historical_classifier_restored = True
        assert all(WorkerFailureClassifier.classify(error) is WorkerFailureClass.FINAL_FAILURE for error in historical_errors)
        return True

    if mode == "world-causal-dead-letter-replay":
        from novel_forge.modules.story_planning_runtime.application import StoryPlanningGenerationApplication

        native_result_repair = StoryPlanningGenerationApplication._repair_unmaterialized_result

        def restore_before_result_repair(application, command, **values):
            if values["operation_id"] in legacy_block:
                assert restore_dead_letter_classifier() or historical_classifier_restored
            return native_result_repair(application, command, **values)

        monkeypatch.setattr(StoryPlanningGenerationApplication, "_repair_unmaterialized_result", restore_before_result_repair)

    def execute_window(current):
        nonlocal historical_classifier_restored
        restore_dead_letter_classifier()
        try:
            return execute_creation_worker_claim(settings, current)
        except KernelError as error:
            if mode not in {
                "world-result-repair",
                "world-causal-result-repair",
                "world-causal-legacy-replay",
                "world-causal-dead-letter-replay",
            } or error.code not in {
                "WORLD_PROVIDER_TRANSITION_INVALID",
                "WORLD_PREPARATION_RESULT_INVALID",
                "WORLD_PREPARATION_BLOCKED",
            }:
                raise
            if mode in {"world-causal-legacy-replay", "world-causal-dead-letter-replay"} and error in historical_errors:
                source_id = error.historical_operation_id
                source_status = capture_historical_checkpoint(source_id)
                if mode == "world-causal-legacy-replay" or source_status == "DEAD_LETTER":
                    monkeypatch.setattr(WorkerFailureClassifier, "classify", staticmethod(native_classifier))
                    historical_classifier_restored = True
                    assert WorkerFailureClassifier.classify(error) is WorkerFailureClass.FINAL_FAILURE
            status = jobs.get(current.runtime_job_id)["status"]
            if status == "DEAD_LETTER" and mode == "world-causal-dead-letter-replay":
                recover = parser.parse_args(["authority-creation", "recover", "--project-id", project,
                    "--formation-run-id", identity, "--reason", "Controlled owner resolved historical World retry classification; retain original inputs and receipts.",
                    "--idempotency-key", "legacy-dead-letter-window:" + current.runtime_job_id, "--repository-root", str(root)])
                run_creation_command(settings, recover)
            else:
                assert status == "RETRY_WAIT"
            return {"stop_reason": "YIELDED_CHECKPOINT", "error_code": error.code}

    result = execute_window(claim())
    if mode == "pending-deployment":
        assert result["stop_reason"] == "YIELDED_CHECKPOINT", result
        from novel_forge.api import authority_dependencies as dependencies
        from novel_forge.modules.book_authority.creation_runtime import creation_runtime_environment, creation_narrative_execution
        from novel_forge.modules.capability_packs.longform_profiles import build_story_planning_pack_profile
        from novel_forge.modules.capability_packs.validation_deployment import register_validation_runtime_definitions, install_longform_validation_pack
        from novel_forge.modules.story_planning_runtime.runtime_continuation import require_binding
        from novel_forge.modules.story_planning_runtime.runtime_deployment import register
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("SELECT continuation_id,to_jsonb(link) FROM authority_story_planning_runtime_continuation link WHERE project_id=%s AND successor_operation_id IS NULL", [project])
            pending = uow.cursor.fetchone()
            assert pending
            uow.cursor.execute("SELECT to_jsonb(op) FROM authority_operation op WHERE operation_id=%s", [pending[1]["source_operation_id"]])
            original_source=uow.cursor.fetchone()[0]
            uow.cursor.execute("SELECT frozen_stage_inputs FROM authority_story_formation_run WHERE formation_run_id=%s", [identity])
            frozen_policy=uow.cursor.fetchone()[0]["generation_policy"]
        assert original_source["status"] == "FAILED_FINAL"
        calls_before=(len(transport.calls),len(transport.chapter.calls))
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from novel_forge.modules.story_planning_runtime import application as planning_module
        from novel_forge.modules.story_planning_runtime.application import _command_from_payload
        old_values=creation_runtime_environment(project)
        old_execution=dependencies.build_production_execution_composition(settings,env=old_values)
        old_chapter=dependencies.build_chapter_authority_application(settings,execution=old_execution,env=old_values)
        old_native=dependencies.build_book_production_composition(settings,principal=author,execution=old_execution,chapter_application=old_chapter,env=old_values)
        old_binding=require_binding(DATABASE_URL,pending[0])
        old_preflight,allow_admission=Event(),Event()
        native_admit=planning_module.admit_command
        def hold_old_admission(*arguments,**options):
            if options["context"].commit_sha==old_binding["target_release_sha"]:
                old_preflight.set()
                assert allow_admission.wait(30), "controlled admission barrier was not released"
            return native_admit(*arguments,**options)
        monkeypatch.setattr(planning_module,"admit_command",hold_old_admission)
        pool=ThreadPoolExecutor(max_workers=1)
        old_attempt=pool.submit(old_native.planning.generate,_command_from_payload(old_binding["successor_command"]),principal=author)
        assert old_preflight.wait(30), "old worker did not finish frozen deployment preflight"
        target_sha="d"*40
        monkeypatch.setenv("NOVEL_FORGE_COMMIT_SHA", target_sha)
        values=creation_runtime_environment(project)
        hashes=register_validation_runtime_definitions(DATABASE_URL,application_build_id=harness.application_build_id,commit_sha=target_sha)
        path=creation_narrative_execution(frozen_policy["creation_input_policy"])
        pack=values["NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID"]
        profile=build_story_planning_pack_profile(root,operation_definition_hash=hashes["planning"],pack_id=pack,**path["planning"])
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("SELECT activation_version FROM authority_capability_pack_activation WHERE project_id=%s AND book_id=%s AND pack_id=%s", [project,project+"-book",pack])
            activation=uow.cursor.fetchone()[0]
        install_longform_validation_pack(DATABASE_URL,profile=profile,pack_version="2.14.999",agent_generation=1,
            agent_domain="story_planning",agent_scope_type="BOOK",project_id=project,workspace_id=harness.workspace_id+"-new",book_id=project+"-book",
            application_build_id=harness.application_build_id,commit_sha=target_sha,compiler=author,approver=author,agent_admin=author,
            expected_activation_version=activation,runtime_environment=settings.environment)
        from novel_forge.modules.capability_packs.longform_profiles import build_reader_outcome_pack_profile
        reader_pack=values["NOVEL_FORGE_READER_OUTCOME_CAPABILITY_PACK_ID"]
        reader_profile=build_reader_outcome_pack_profile(root,operation_definition_hash=hashes["reader_proxy_current"],pack_id=reader_pack,coordinated_contract=True)
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("SELECT activation_version FROM authority_capability_pack_activation WHERE project_id=%s AND book_id=%s AND pack_id=%s", [project,project+"-book",reader_pack])
            reader_activation=uow.cursor.fetchone()[0]
        install_longform_validation_pack(DATABASE_URL,profile=reader_profile,pack_version="1.6.999",agent_generation=1,
            agent_domain="reader_outcome",agent_scope_type="BOOK",project_id=project,workspace_id=harness.workspace_id+"-new",book_id=project+"-book",
            application_build_id=harness.application_build_id,commit_sha=target_sha,compiler=author,approver=author,agent_admin=author,
            expected_activation_version=reader_activation,runtime_environment=settings.environment)
        native_execution=dependencies.build_production_execution_composition(settings,env=values)
        try:
            native_chapter=dependencies.build_chapter_authority_application(settings,execution=native_execution,env=values)
            native=dependencies.build_book_production_composition(settings,principal=author,execution=native_execution,chapter_application=native_chapter,env=values)
            worker=build_trusted_principal_resolver(env=values).resolve_book_formation_worker_principal("not-operator")
            request=dict(project_id=project,authorization_ref=frozen_policy["auto_authorization"]["authorization_ref"],reason="Exact pending deployment after controlled release change")
            with pytest.raises(PermissionError):
                register(native.planning,pending[0],principal=worker,**request)
            with pytest.raises(KernelError,match="PLANNING_DEPLOYMENT_REVALIDATION_AUTHORIZATION_REQUIRED"):
                register(native.planning,pending[0],principal=author,**{**request,"authorization_ref":"foreign"})
            with ThreadPoolExecutor(max_workers=2) as registration_pool:
                records=list(registration_pool.map(lambda _:register(native.planning,pending[0],principal=author,**request),range(2)))
            assert len({item["operation_id"] for item in records})==1
            record=records[0]
            assert (len(transport.calls),len(transport.chapter.calls))==calls_before
            allow_admission.set()
            with pytest.raises(KernelError,match="PLANNING_RUNTIME_CONTINUATION_COMMAND_DRIFT"):
                old_attempt.result(30)
            assert register(native.planning,pending[0],principal=author,**request)["asset_version_id"]==record["asset_version_id"]
            binding=require_binding(DATABASE_URL,pending[0])
            assert binding["target_release_sha"]==target_sha
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("SELECT to_jsonb(link) FROM authority_story_planning_runtime_continuation link WHERE continuation_id=%s", [pending[0]])
                assert uow.cursor.fetchone()[0]==pending[1]
                uow.cursor.execute("SELECT to_jsonb(op) FROM authority_operation op WHERE operation_id=%s", [pending[1]["source_operation_id"]])
                assert uow.cursor.fetchone()[0]==original_source
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("SELECT count(*) FROM authority_operation WHERE project_id=%s AND command_payload#>>'{payload,runtime_continuation_id}'=%s", [project,pending[0]])
                assert uow.cursor.fetchone()[0]==0
            resume=parser.parse_args(["authority-creation","continue","--project-id",project,"--formation-run-id",identity,
                "--repository-root",str(root),"--foreground","--yield-after-window","--maximum-ticks","1","--work-window-seconds","1"])
            for _ in range(3):
                result=run_creation_command(settings,resume)
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute("""SELECT op.operation_id,op.status,g.candidate_asset_version_id FROM authority_story_planning_runtime_continuation link
                        JOIN authority_operation op ON op.operation_id=link.successor_operation_id
                        JOIN authority_story_planning_generation g ON g.operation_id=op.operation_id WHERE link.continuation_id=%s""", [pending[0]])
                    generated=uow.cursor.fetchone()
                if generated and generated[1]=="SUCCEEDED":
                    break
            assert generated and generated[1]=="SUCCEEDED" and generated[2], result
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("SELECT status,count(*) FROM authority_external_effect WHERE operation_id=%s GROUP BY status", [generated[0]])
                assert uow.cursor.fetchall()==[("SUCCEEDED",1)]
                uow.cursor.execute("SELECT to_jsonb(op) FROM authority_operation op WHERE operation_id=%s", [pending[1]["source_operation_id"]])
                assert uow.cursor.fetchone()[0]==original_source
            assert register(native.planning,pending[0],principal=author,**request)["replayed"]
        finally:
            allow_admission.set()
            pool.shutdown(wait=True)
            old_execution.close()
            native_execution.close()
        return
    if mode == "capacity-foundation-new-cause":
        assert result["stop_reason"] == "YIELDED_CHECKPOINT"
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("UPDATE authority_runtime_job SET available_at=NOW() WHERE project_id=%s AND job_kind='BOOK_CREATION_ADVANCE' AND status='READY'", [project])
            uow.commit()
        result = execute_window(claim())
        assert result["stop_reason"] == "FORMATION_OWNER_RECOVERY_REQUIRED"
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("SELECT count(*) FROM authority_story_planning_runtime_continuation WHERE project_id=%s", [project])
            assert uow.cursor.fetchone()[0] == 1
            uow.cursor.execute("""SELECT latest.result->>'error_code',
                (SELECT count(*) FROM authority_external_effect WHERE operation_id=operation.operation_id)
                FROM authority_operation operation JOIN authority_story_planning_generation generation USING(operation_id)
                JOIN LATERAL (SELECT result FROM authority_attempt WHERE operation_id=operation.operation_id
                    ORDER BY attempt_number DESC LIMIT 1) latest ON TRUE
                WHERE generation.project_id=%s AND generation.generator_operation_name='character.cast.generate'
                ORDER BY operation.created_at DESC LIMIT 1""", [project])
            assert uow.cursor.fetchone() == ("PLANNING_CONTEXT_BINDING_FAILED", 0)
        return
    if mode == "complete":
        assert result["stop_reason"] == "YIELDED_CHECKPOINT"
        assert lost
        from novel_forge.api import authority_dependencies as dependencies
        from novel_forge.workers.book_authority import execute_book_phase_with_creation_scope, execute_story_formation_claim
        legacy_execution = dependencies.build_production_execution_composition(settings)
        try:
            legacy_chapter = dependencies.build_chapter_authority_application(settings, execution=legacy_execution)
            legacy = dependencies.build_book_production_composition(
                settings,
                principal=build_trusted_principal_resolver().resolve_worker_principal(
                    "durable-phase-worker"
                ),
                execution=legacy_execution,
                chapter_application=legacy_chapter,
            )
            legacy.formation.schedule_candidates(limit=1, project_id=project, formation_run_id=identity)
            phase = jobs.claim(runtime_group="story_formation", worker_id="durable-phase", lease_seconds=60,
                job_kinds=("STORY_FORMATION_ADVANCE",), subject_kind="STORY_FORMATION_RUN", subject_id=identity)
            assert phase is not None
            worker = build_trusted_principal_resolver().resolve_book_formation_worker_principal(phase.worker_id)
            native = execute_book_phase_with_creation_scope(settings, phase, legacy,
                lambda scoped: execute_story_formation_claim(jobs, scoped.formation, worker, phase, lease_seconds=60))
            assert native["current_stage"] == "ENDING_INTENT"
        finally:
            legacy_execution.close()
    assert result["stop_reason"] in {"COMPLETED", "YIELDED_CHECKPOINT"}, result
    for _ in range(10 if mode == "world-causal-dead-letter-replay" else 6):
        if result["stop_reason"] == "COMPLETED":
            break
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("UPDATE authority_runtime_job SET available_at=NOW() WHERE project_id=%s AND job_kind IN ('BOOK_CREATION_ADVANCE','BOOK_COORDINATION_TICK') AND status IN ('READY','RETRY_WAIT')", [project])
            uow.commit()
        next_claim = claim()
        assert next_claim is not None, result
        result = execute_window(next_claim)
    assert result["stop_reason"] == "COMPLETED", result
    if mode in {
        "world-result-repair",
        "world-primary-result-repair",
        "world-causal-result-repair",
        "world-causal-legacy-replay",
        "world-causal-dead-letter-replay",
    }:
        assert len(world_calls) == (1 if mode == "world-primary-result-repair" else 3)
        assert len(primary_calls) == (3 if mode == "world-primary-result-repair" else 1)
        assert (
            len(
                {
                    json.dumps(item["world_preparation"]["source_ref"], sort_keys=True)
                    for item in world_calls
                }
            )
            == 1
        )
        if mode in {"world-result-repair", "world-causal-result-repair", "world-causal-legacy-replay", "world-causal-dead-letter-replay"}:
            assert "Controlled Schema-valid but domain-invalid result." not in json.dumps(primary_calls[0])
            assert all(
                item["world_preparation"]["result_repair"]["diagnostic"][
                    "provider_stage"
                ]
                == "world_candidates.generate"
                for item in world_calls[1:]
            )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "SELECT op.status,op.causation_operation_id,op.command_payload->'payload' FROM authority_operation op JOIN authority_story_planning_generation gen USING(operation_id) WHERE op.project_id=%s AND gen.generator_operation_name='chapter_plan.generate' ORDER BY op.created_at",
                [project],
            )
            lineage = uow.cursor.fetchall()
        assert [row[0] for row in lineage] == [
            "DEAD_LETTER" if mode == "world-causal-dead-letter-replay" else "FAILED_FINAL",
            "FAILED_FINAL",
            "SUCCEEDED",
        ]
        assert [row[2]["repair_number"] for row in lineage] == [0, 1, 2]
        assert lineage[1][1] == lineage[1][2]["repair_of_operation_id"]
        assert lineage[2][1] == lineage[2][2]["repair_of_operation_id"]
        if mode in {"world-causal-result-repair", "world-causal-legacy-replay", "world-causal-dead-letter-replay"}:
            assert all(
                row[2]["repair_result_diagnostic"]["validation_kind"]
                == "WORLD_CAUSAL_GATE"
                for row in lineage[1:]
            )
        if mode in {"world-causal-legacy-replay", "world-causal-dead-letter-replay"}:
            assert legacy_block and historical_snapshots and historical_classifier_restored
            assert all(record["classifier_source"] == historical_classifier_source for record in historical_snapshots)
            original = historical_snapshots[-1]
            assert original["source_operation_id"] == lineage[1][1]
            assert original["source_status"] == ("DEAD_LETTER" if mode == "world-causal-dead-letter-replay" else "FAILED_RETRYABLE")
            assert original["world_calls"] == 1
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                for record in historical_snapshots:
                    for attempt in record["attempts"]:
                        uow.cursor.execute("SELECT to_jsonb(a) FROM authority_attempt a WHERE attempt_id=%s", [attempt["attempt_id"]])
                        assert uow.cursor.fetchone()[0] == attempt
                    uow.cursor.execute("SELECT to_jsonb(e),to_jsonb(b) FROM authority_external_effect e JOIN authority_budget_reservation b USING(external_effect_id) WHERE e.operation_id=%s ORDER BY e.external_effect_id", [record["source_operation_id"]])
                    assert uow.cursor.fetchall() == record["receipts"]
        if mode == "world-causal-legacy-replay":
            assert legacy_block
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute(
                    "SELECT status FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number",
                    [lineage[1][1]],
                )
                assert [row[0] for row in uow.cursor.fetchall()] == ["FAILED_RETRYABLE", "FAILED_FINAL"]
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT checkpoint->'generated_layer'->>'asset_version_id' FROM authority_story_formation_stage WHERE formation_run_id=%s AND stage='CREATIVE_FOUNDATION'", [identity])
        assert uow.cursor.fetchone()[0] == selected
        uow.cursor.execute("SELECT count(*) FROM authority_book_chapter_acceptance WHERE book_run_id=%s AND status='COMMITTED'", [result["book_run_id"]])
        assert uow.cursor.fetchone()[0] == inputs["target_chapters"]
    if mode.startswith("capacity-"):
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "SELECT source_operation_id,successor_operation_id,source_command,successor_command,target_runtime FROM authority_story_planning_runtime_continuation WHERE project_id=%s",
                [project],
            )
            registrations = uow.cursor.fetchall()
            assert len(registrations) == (3 if mode == "capacity-recovery" else 1)
            for (
                source,
                successor,
                original_command,
                next_command,
                runtime,
            ) in registrations:
                assert {
                    key: value
                    for key, value in original_command.items()
                    if key not in {"runtime_continuation_id", "idempotency_key"}
                } == {
                    key: value
                    for key, value in next_command.items()
                    if key not in {"runtime_continuation_id", "idempotency_key"}
                }
                assert runtime["planning_capacity"]["allocated_task_tokens"] == 128000
                uow.cursor.execute(
                    "SELECT status,(SELECT count(*) FROM authority_external_effect WHERE operation_id=%s) FROM authority_operation WHERE operation_id=%s",
                    [source, source],
                )
                assert uow.cursor.fetchone() == ("FAILED_FINAL", 0)
                uow.cursor.execute(
                    "SELECT count(*) FROM authority_external_effect WHERE operation_id=%s AND status='SUCCEEDED'",
                    [successor],
                )
                assert uow.cursor.fetchone()[0] == 1
                if mode != "capacity-recovery":
                    uow.cursor.execute(
                        "SELECT causation_operation_id FROM authority_operation WHERE operation_id=%s",
                        [successor],
                    )
                    cause = uow.cursor.fetchone()[0]
                    if mode == "capacity-retained-repair-cause":
                        uow.cursor.execute(
                            "SELECT operation_id FROM authority_story_planning_generation WHERE candidate_asset_version_id=%s",
                            [original_command["repair_of_candidate_id"]],
                        )
                        assert cause == uow.cursor.fetchone()[0]
                    else:
                        assert cause == source
    before = len(transport.calls), len(transport.chapter.calls)
    assert schedule_creation_jobs(DATABASE_URL, formation_run_id=identity) == ()
    assert claim() is None
    run_creation_command(settings, args)
    run_creation_command(settings, chosen)
    assert (len(transport.calls), len(transport.chapter.calls)) == before
    final = creation_status(DATABASE_URL, project_id=project, formation_run_id=identity, principal=author)
    assert final["author_state"] == "INTERNAL_ACCEPTANCE_COMPLETE"
    assert final["production"]["accepted_chapters"] == inputs["target_chapters"]
    assert final["delivery"]["required_action"] == "READ_EDIT_OR_EXPORT_CURRENT_MANUSCRIPT"
    cancelled = parser.parse_args(["authority-creation", "cancel", "--project-id", project,
        "--formation-run-id", identity, "--reason", "Cannot cancel terminal production", "--idempotency-key", "late-cancel", "--repository-root", str(root)])
    from novel_forge.modules.command_kernel.errors import KernelError
    with pytest.raises(KernelError, match="CREATION_ALREADY_COMPLETED"):
        run_creation_command(settings, cancelled)
    assert creation_status(DATABASE_URL, project_id=project, formation_run_id=identity, principal=author)["cancellation"] is None
    if mode == "complete":
        from copy import deepcopy
        from time import monotonic
        from novel_forge.modules.book_authority.creation_runtime import creation_runtime_environment, drive_book
        from novel_forge.modules.book_authority.edition_application import BookEditionApplication
        from novel_forge.modules.chapter_authority.realization_composition import serialize_realization
        from novel_forge.workers.book_authority import schedule_book_coordination_jobs, execute_book_coordination_claim
        from novel_forge.workers.chapter_authority import execute_chapter_with_creation_scope
        values = creation_runtime_environment(project)
        native_execution = dependencies.build_production_execution_composition(settings, env=values)
        legacy_execution = dependencies.build_production_execution_composition(settings)
        try:
            native_chapter = dependencies.build_chapter_authority_application(settings, execution=native_execution, env=values)
            native = dependencies.build_book_production_composition(settings, principal=author,
                execution=native_execution, chapter_application=native_chapter, env=values)
            legacy_chapter = dependencies.build_chapter_authority_application(settings, execution=legacy_execution)
            legacy = dependencies.build_book_production_composition(
                settings,
                principal=build_trusted_principal_resolver().resolve_worker_principal(
                    "durable-phase-worker"
                ),
                execution=legacy_execution,
                chapter_application=legacy_chapter,
            )
            editor = BookEditionApplication(DATABASE_URL,application_build_id=native.authority.application_build_id,
                                           commit_sha=native.authority.commit_sha)
            scope = dict(project_id=project,workspace_id=args.workspace_id,book_run_id=result["book_run_id"],principal=author)
            manifest = editor.query(**scope)["source_manifest"]
            original = editor.execute(action="create",**scope,data={"base_manifest_digest":manifest["manifest_digest"]},idempotency_key="original-manuscript")
            candidate = editor.execute(action="create",**scope,data={"base_revision_id":original["revision_id"],"base_manifest_digest":manifest["manifest_digest"]},idempotency_key="author-expression")
            units = deepcopy(manifest["units"])
            units[1]["scene_artifacts"][0]["text"] += " 风停了一瞬。"
            units[1]["text"] = serialize_realization(units[1]["scene_artifacts"],units[1].get("scene_separators"))
            saved = editor.execute(action="save",**scope,data={"revision_id":candidate["revision_id"],"expected_version":candidate["version"],
                "base_manifest_digest":manifest["manifest_digest"],"units":units,"reason":"Controlled author expression edit; no literary benefit claim","change_kind":"EXPRESSION"},idempotency_key="save-author-expression")
            inspected = editor.query(**scope,revision_id=saved["revision_id"])
            assert inspected["revision"]["manifest"]["units"][0] == manifest["units"][0]
            assert len(inspected["diff"]["changes"]) == 1
            with pytest.raises(KernelError,match="EDITION_FORMAL_EXPORT_REQUIRES_SELECTION"):
                editor.export_manuscript(**scope,revision_id=saved["revision_id"])
            assert editor.export_manuscript(**scope,revision_id=saved["revision_id"],export_kind="CANDIDATE")["export"]["kind"] == "CANDIDATE"
            validation = editor.start_validation(authority=native.authority,**scope,revision_id=saved["revision_id"])
            target = validation["validation_book_run_id"]
            assert native.query.uses_creation_scope(project_id=project,subject_id=target)
            assert native.authority.require(target)["accepted_through_chapter"] == 1
            worker = build_trusted_principal_resolver().resolve_worker_principal("edition-worker")
            scheduled = schedule_book_coordination_jobs(
                legacy.query, jobs, limit=1, book_run_id=target
            )
            assert len(scheduled) == 1
            assert not schedule_book_coordination_jobs(
                legacy.query, jobs, limit=1, book_run_id=target
            )
            for _ in range(5):
                stalled = jobs.claim(
                    runtime_group="book",
                    worker_id=worker.principal_id,
                    lease_seconds=60,
                    job_kinds=("BOOK_COORDINATION_TICK",),
                    subject_kind="BOOK_RUN",
                    subject_id=target,
                )
                assert stalled is not None
                failed = jobs.fail(
                    stalled, {"code": "CONTROLLED_OWNER_CONFIGURATION_FAILURE"}
                )
            assert failed["status"] == "DEAD_LETTER"
            assert target not in {
                item.book_run_id
                for item in legacy.query.coordination_candidates(limit=50)
            }
            assert legacy.query.coordination_candidates(limit=1, book_run_id=target)
            for _ in range(20):
                schedule_book_coordination_jobs(legacy.query,jobs,limit=1,book_run_id=target)
                phase = jobs.claim(runtime_group="book",worker_id=worker.principal_id,lease_seconds=60,
                    job_kinds=("BOOK_COORDINATION_TICK",),subject_kind="BOOK_RUN",subject_id=target)
                assert phase is not None
                dispatch = execute_book_phase_with_creation_scope(settings,phase,legacy,
                    lambda scoped:execute_book_coordination_claim(jobs,scoped,phase))
                if dispatch["action"] == "DISPATCH_CHAPTER":
                    break
            assert dispatch["action"] == "DISPATCH_CHAPTER", dispatch
            active = dispatch["operation_id"]
            assert native.query.uses_creation_scope(project_id=project,subject_id=active)
            execute_chapter_with_creation_scope(settings,legacy_chapter.scheduler(principal=worker),worker,
                project_id=project,root_operation_id=active)
            stopped = drive_book(composition=native,chapter=native_chapter,book_run_id=target,worker=worker,
                maximum_ticks=50,deadline=monotonic()+180)
            assert stopped == "COMPLETED", stopped
            reviewed = editor.query(**scope,revision_id=saved["revision_id"])["validation_result"]
            if reviewed["diff"]["changes"]:
                adopted = editor.execute(action="create",**scope,data={"source_validation_revision_id":saved["revision_id"],
                    "validation_book_run_id":target,"expected_version":saved["version"],"base_manifest_digest":reviewed["manifest"]["manifest_digest"],
                    "reason":"Explicitly retain submitted candidate and capture exact native reviewed text"},idempotency_key="capture-native-review")
            else:
                adopted = editor.execute(action="validate",**scope,data={"revision_id":saved["revision_id"],"expected_version":saved["version"],
                    "validation_book_run_id":target},idempotency_key="validate-author-expression")
            editor.execute(action="select",**scope,data={"revision_id":adopted["revision_id"],"expected_head_version":1,
                "reason":"Adopt exact revalidated author version"},idempotency_key="select-author-expression")
            exported = editor.export_manuscript(**scope,revision_id=adopted["revision_id"])
            assert exported["export"]["currently_selected"]
            assert exported["revision"]["manifest"] == reviewed["manifest"]
            assert editor.query(**scope,revision_id=original["revision_id"])["revision"]["manifest"] == manifest
        finally:
            native_execution.close()
            legacy_execution.close()
