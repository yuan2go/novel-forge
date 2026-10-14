from copy import deepcopy
import json
from pathlib import Path

import pytest

from novel_forge.cli.authority import _authority_parser
from novel_forge.cli.creation import run_creation_command
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.book_authority.manuscript import freeze_working_context
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.world_preparation import PlanningWorldPreparation
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.book_control_repositories import BookControlRepository
from novel_forge.storage.world_preparation_repositories import WorldPreparationRepository
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.capability_pack_postgres_support import CapabilityPackPostgresHarness
from tests.integration.creative_validation_production_support import controlled_member_environment
from tests.integration.synthesis_production_support import SynthesisTransport
from tests.unit.test_working_prose_projection import rehash


def test_native_creation_world_binds_selected_delivery_and_rejects_changed_experience(tmp_path, monkeypatch):
    harness = CapabilityPackPostgresHarness("world-working")
    root = Path(__file__).resolve().parents[2]
    transport = SynthesisTransport()
    transport.database_url = DATABASE_URL
    env = controlled_member_environment(tmp_path, {
        "NOVEL_FORGE_APPLICATION_BUILD_ID": harness.application_build_id,
        "NOVEL_FORGE_COMMIT_SHA": harness.release_sha,
        "NOVEL_FORGE_MODEL_PROVIDER": "codex-cli", "NOVEL_FORGE_MODEL": "gpt-test",
        "NOVEL_FORGE_PLANNING_PROVIDER": "codex-cli", "NOVEL_FORGE_PLANNING_MODEL": "gpt-test",
        "NOVEL_FORGE_STORAGE_AUTHORITY": "postgresql", "NOVEL_FORGE_DATABASE_URL": DATABASE_URL,
        "NOVEL_FORGE_LOCAL_OPERATOR_PRINCIPAL_ID": "native-creation-operator",
        "NOVEL_FORGE_OPERATOR_PRINCIPAL_ID": "native-creation-operator",
        "NOVEL_FORGE_NARRATIVE_EVALUATOR_PRINCIPAL_ID": "native-planning-evaluator",
        "NOVEL_FORGE_ENVIRONMENT": "production",
    }, monkeypatch, transport)
    env["NOVEL_FORGE_ENVIRONMENT"] = "production"
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    from novel_forge.modules.chapter_authority.execution_gateway import PostgresProductionExecutionPayloadResolver
    resolve = PostgresProductionExecutionPayloadResolver.resolve
    writer_prompts = []
    chapter_planning_prompts = []
    world_prompts = []

    def capture_writer_prompt(resolver, request, admission):
        payload = resolve(resolver, request, admission)
        if request.stage in {"draft", "chapter_plan.generate", "world_candidates.generate", "world_candidates.evaluate"}:
            start = payload.input_text.find('{"context_bundle":')
            assert start >= 0
            from novel_forge.modules.chapter_authority.provider_views import expand_exact_context_references
            envelope = expand_exact_context_references(json.JSONDecoder().raw_decode(payload.input_text[start:])[0])
            target = writer_prompts if request.stage == "draft" else world_prompts if request.stage.startswith("world_candidates.") else chapter_planning_prompts
            target.append(envelope)
        return payload

    monkeypatch.setattr(PostgresProductionExecutionPayloadResolver, "resolve", capture_writer_prompt)
    input_file = tmp_path / "request.json"
    input_file.write_text(json.dumps({"version": "creation-request.v1", "title": harness.project_id,
        "target_chapters": 2, "execution_window": {"version": "creation-execution-window.v1", "stop_after_chapter": 1},
        "chapter_length": {"minimum": 800, "maximum": 4000}, "language_contract": {"required_language": "zh-CN"},
        "brief": {"creative_brief_contract_version": "creative-brief-v2", "idea": "An archivist investigates a flood.",
            "genre": "social mystery", "audience": "adult readers", "constraints": ["Keep the witness's limited viewpoint"], "source_boundaries": ["Original work"]}}))
    args = _authority_parser().parse_args(["authority-creation", "start", "--input-file", str(input_file),
        "--repository-root", str(root), "--maximum-ticks", "100", "--foreground"])
    template = json.loads((root / args.execution_template_file).read_text())
    template["optional_enhancements"] = sorted(set(template["optional_enhancements"]) | {"memo"})
    args.execution_template_file = tmp_path / "execution-template.json"
    args.execution_template_file.write_text(json.dumps(template))
    result = run_creation_command(IndustrialSettings(root=tmp_path, database_url=DATABASE_URL, environment="production"), args)
    if result["stop_reason"] != "MANUSCRIPT_READY":
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("""SELECT operation.definition_name,operation.status,attempt.result->>'error_code',attempt.result->>'error_message'
                FROM authority_operation operation LEFT JOIN LATERAL (SELECT result FROM authority_attempt
                    WHERE operation_id=operation.operation_id ORDER BY attempt_number DESC LIMIT 1) attempt ON TRUE
                WHERE operation.project_id=%s ORDER BY operation.created_at DESC LIMIT 8""", [result["project_id"]])
            failures = uow.cursor.fetchall()
        pytest.fail(f"Native Creation stopped at {result['stop_reason']}: {failures!r}")
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT to_jsonb(b) FROM authority_book_production b WHERE book_run_id=%s", [result["book_run_id"]])
        book = uow.cursor.fetchone()[0]
        assert book["current_chapter"] == 1 and book["accepted_through_chapter"] == 0
        uow.cursor.execute("""SELECT v.content FROM authority_asset_version v JOIN authority_asset a USING(asset_id)
            WHERE a.project_id=%s AND a.asset_type='context_bundle' AND v.content->>'stage'='draft'""", [book["project_id"]])
        draft_contexts = [row[0] for row in uow.cursor.fetchall() if row[0].get("chapter_generation_length")]
        assert len(draft_contexts) == 1
        assert draft_contexts[0]["chapter_generation_length"]["minimum"] == 800
        assert draft_contexts[0]["chapter_generation_length"]["maximum"] == 4000
        from novel_forge.modules.chapter_authority.quality_length_requirement import require_generation_binding
        require_generation_binding(draft_contexts[0])
        assert len(writer_prompts) == 1
        assert writer_prompts[0]["context_bundle"]["chapter_generation_length"] == draft_contexts[0]["chapter_generation_length"]
        assert len(chapter_planning_prompts) == 1
        scale = chapter_planning_prompts[0]["context_bundle"]["chapter_planning_length"]
        assert scale["minimum"] == 800 and scale["maximum"] == 4000 and scale["unit"] == "HAN_CHARACTERS_V1"
        uow.cursor.execute("SELECT current_book_asset_version_id FROM authority_book WHERE project_id=%s AND book_id=%s", [book["project_id"], book["book_id"]])
        assert scale["source_book_asset_version_id"] == uow.cursor.fetchone()[0]
        uow.cursor.execute("""SELECT v.content->'creative_baseline' FROM authority_asset_version v
            JOIN authority_asset a USING(asset_id) WHERE a.project_id=%s AND a.asset_type='draft_chapter'""", [book["project_id"]])
        baselines = [row[0] for row in uow.cursor.fetchall()]
        assert len(baselines) == 1
        assert baselines[0]["chapter_generation_length"] == draft_contexts[0]["chapter_generation_length"]
        uow.cursor.execute("""SELECT v.content->'contract' FROM authority_asset_version v JOIN authority_asset a USING(asset_id)
            WHERE a.project_id=%s AND a.asset_type='world_preparation_source' ORDER BY v.created_at LIMIT 1""", [book["project_id"]])
        first_source = uow.cursor.fetchone()[0]
        assert first_source["contract_version"] == "world-preparation-source.v5"
        assert first_source["provider_projection_version"] == "world-role-delivery.v4"
        assert len(world_prompts) == 2
        for envelope in world_prompts:
            delivered = envelope["input_manifest"]["narrative_inputs"]["world_preparation"]
            assert delivered["contract_version"] == "world-provider-task.v5"
            assert delivered["working_delivery_receipt"]["source_snapshot_hash"] == first_source["working_manuscript"]["snapshot_hash"]
            assert "schema" not in delivered["transition_contract"]
            assert delivered["transition_contract"]["payload_schema"]
        working = freeze_working_context(uow, book, 2)
        BookControlRepository(uow.cursor).freeze(project_id=book["project_id"], book_run_id=book["book_run_id"],
            chapter_number=2, actor_id="native-creation-operator")
        repository = WorldPreparationRepository(uow.cursor)
        source = repository.require_source(project_id=book["project_id"], book_id=book["book_id"],
            request=first_source["request"], contract_version="world-preparation-source.v5", epistemic_contract="world-agency.v2",
            working_manuscript=working)
        assert source["target_chapter"] == 2 and source["reality"]["chapter_number"] == 0
        assert source["working_manuscript"]["sources"][0]["passages"] == working["sources"][0]["passages"]
        repository.assert_source_current(project_id=book["project_id"], book_id=book["book_id"], frozen=source)
        task = PlanningWorldPreparation._task(source, {"asset_version_id": "controlled-source", "content_hash": "digest"}, "DIRECTOR")
        assert task["target_chapter"] == 2 and task["accepted_through_chapter"] == 0
        changed = deepcopy(source)
        changed["working_manuscript"]["sources"][0]["content_hash"] = "sha256:" + "0" * 64
        rehash(changed["working_manuscript"])
        with pytest.raises(KernelError, match="MANUSCRIPT_SOURCE_HASH_INVALID|WORKING_PROSE_SOURCE_RESOLUTION_INVALID"):
            repository.assert_source_current(project_id=book["project_id"], book_id=book["book_id"], frozen=changed)
        assert uow.cursor.execute("SELECT accepted_through_chapter FROM authority_book_production WHERE book_run_id=%s", [book["book_run_id"]]).fetchone() == (0,)
    from novel_forge.cli.manuscript import run_manuscript_command
    from novel_forge.modules.book_authority.queries import PostgresBookProductionQuery
    revision = _authority_parser().parse_args(["authority-manuscript", "revise", "--project-id", book["project_id"],
        "--book-run-id", book["book_run_id"], "--chapter", "1", "--expected-version", str(book["version"]),
        "--idempotency-key", harness.project_id + ":working-revision", "--reason", "Native selected working review"])
    admitted = run_manuscript_command(IndustrialSettings(root=root, database_url=DATABASE_URL, environment="production"), revision)
    assert PostgresBookProductionQuery(DATABASE_URL).uses_creation_scope(project_id=book["project_id"], subject_id=admitted["root_operation_id"])
    assert not PostgresBookProductionQuery(DATABASE_URL).uses_creation_scope(project_id="other-project", subject_id=admitted["root_operation_id"])
