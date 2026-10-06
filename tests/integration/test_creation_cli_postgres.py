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


@pytest.mark.parametrize("full_creation", [False, True], ids=["admission-boundaries", "controlled-process-main-chain"])
def test_native_start_freezes_current_work_and_reuses_original_formation(tmp_path, monkeypatch, full_creation):
    harness = CapabilityPackPostgresHarness("creation-cli-full" if full_creation else "creation-cli-admission")
    project = harness.project_id + "-native"
    root = Path(__file__).resolve().parents[2]
    from tests.integration.synthesis_production_support import SynthesisTransport
    transport = SynthesisTransport() if full_creation else None
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
                    if declaration["field_path"] == "$.serialization_potential":
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
    input_file = tmp_path / "request.json"
    input_file.write_text(json.dumps(inputs))
    book = project + "-new-book"
    parser = _authority_parser()
    args = parser.parse_args(["authority-creation", "start", "--project-id", project,
        "--workspace-id", harness.workspace_id + "-new", "--book-id", book, "--input-file", str(input_file),
        "--idempotency-key", "native-create", "--repository-root", str(root), "--maximum-ticks", "100"])
    if not full_creation:
        args.yield_after_window = True
        monkeypatch.setattr("novel_forge.modules.book_authority.creation_runtime.continue_creation",
            lambda **values: {"formation_run_id": values["formation_run_id"], "stop_reason": "YIELDED_CHECKPOINT"})
    settings = IndustrialSettings(root=tmp_path, database_url=DATABASE_URL, environment="validation")
    first = run_creation_command(settings, args)
    if full_creation:
        assert first["stop_reason"] == "FORMATION_FAILED", first
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
        uow.cursor.execute("SELECT count(*) FROM authority_book WHERE project_id=%s AND book_id=%s", [project, book])
        assert uow.cursor.fetchone()[0] == 1
        uow.cursor.execute("SELECT count(*) FROM authority_capability_pack_approval approval JOIN authority_operation op ON op.operation_id=approval.decided_by_operation_id WHERE op.project_id=%s", [project])
        assert uow.cursor.fetchone()[0] == 0
        if full_creation:
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
