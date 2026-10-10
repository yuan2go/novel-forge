import json
import hashlib
from pathlib import Path

import pytest

from novel_forge.cli.authority import _authority_parser
from novel_forge.cli.creation import run_creation_command
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.book_authority.manuscript import current_manuscript
from novel_forge.modules.chapter_authority.author_editor import ChapterAuthorEditingApplication
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.capability_pack_postgres_support import CapabilityPackPostgresHarness
from tests.integration.creative_validation_production_support import controlled_member_environment
from tests.integration.synthesis_production_support import SynthesisTransport


def prepare_context_model_stages(transport, monkeypatch):
    from novel_forge.modules.chapter_authority import handlers
    from novel_forge.modules.chapter_authority.execution_gateway import default_chapter_fixture_response
    chapter_transport = transport.chapter
    class ContextFixtureTransport:
        def __setattr__(self, name, value):
            setattr(chapter_transport, name, value)
        def __getattr__(self, name):
            return getattr(chapter_transport, name)
        def __call__(self, stage, inputs):
            if stage in {"context_compress", "context_fidelity"}:
                return default_chapter_fixture_response(stage, inputs)
            return chapter_transport(stage, inputs)
    transport.chapter = ContextFixtureTransport()
    build_context = handlers.build_context_bundle
    def prepare_two_model_stages(**kwargs):
        if kwargs["plan"]["chapter"] == 1:
            memo = kwargs["chapter_memo"]
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                source = uow.repositories.asset_documents.require(project_id=kwargs["project_id"],
                    asset_version_id=kwargs["plan_asset_version_id"])
            task = {"contract_version": "task-context-compression.v1", "policy_version": "task-scoped-context.v1",
                "accepted_boundary": memo["accepted_boundary"], "memo_fingerprint": memo["memo_fingerprint"],
                "task": {"stage": "draft", "chapter": 1, "goal": kwargs["plan"]["chapter_objective"]},
                "target_tokens": 1024, "required_unit_ids": ["controlled-plan-goal"],
                "units": [{"unit_id": "controlled-plan-goal", "text": kwargs["plan"]["chapter_objective"], "required": True}],
                "source_binding": {"asset_version_id": source.asset_version_id, "content_hash": source.content_hash}}
            selected = kwargs["context_model_call"]("context_compress", task)
            kwargs["context_model_call"]("context_fidelity", {**task, "selected_unit_ids": selected["selected_unit_ids"]})
        return build_context(**kwargs)
    monkeypatch.setattr(handlers, "build_context_bundle", prepare_two_model_stages)


@pytest.mark.parametrize("completed_sibling,recoverable_result,enhanced_working", [(False, False, False), (True, False, False), (False, True, False), (False, False, True), (False, False, "memory")], ids=["single-interruption", "completed-sibling-interruption", "saved-complete-result", "enhanced-working-interruption", "working-memory-interruption"])
def test_native_author_first_cross_chapter_edit_and_export(tmp_path, monkeypatch, completed_sibling, recoverable_result, enhanced_working):
    harness = CapabilityPackPostgresHarness("author-first")
    project = harness.project_id + "-native"
    root = Path(__file__).resolve().parents[2]
    transport = SynthesisTransport()
    if enhanced_working == "memory":
        parent_transport = transport.chapter
        class MemoryTransport:
            def __getattr__(self, name):
                return getattr(parent_transport, name)
            def __setattr__(self, name, value):
                setattr(parent_transport, name, value)
            def __call__(self, stage, inputs):
                output = parent_transport(stage, inputs)
                if stage == "draft":
                    number = inputs["plan"]["chapter"]
                    quote = output["scene_artifacts"][0]["text"][:200]
                    output["working_memory_json"] = (json.dumps([{"kind": "EVENT", "subject": "archivist",
                        "state_key": "controlled-opening", "claim": "The selected opening is available for later source lookup.",
                        "perspective": "OBSERVED", "knowledge_owner": "", "quote": quote, "causes": []}])
                        if number == 1 else {"invalid": "optional metadata"} if number == 2 else "[]")
                return output
        transport.chapter = MemoryTransport()
    env = controlled_member_environment(tmp_path, {
        "NOVEL_FORGE_APPLICATION_BUILD_ID": harness.application_build_id,
        "NOVEL_FORGE_COMMIT_SHA": harness.release_sha,
        "NOVEL_FORGE_MODEL_PROVIDER": "codex-cli", "NOVEL_FORGE_MODEL": "gpt-test",
        "NOVEL_FORGE_PLANNING_PROVIDER": "codex-cli", "NOVEL_FORGE_PLANNING_MODEL": "gpt-test",
        "NOVEL_FORGE_STORAGE_AUTHORITY": "postgresql", "NOVEL_FORGE_DATABASE_URL": DATABASE_URL,
        "NOVEL_FORGE_OPERATOR_PRINCIPAL_ID": "native-creation-operator",
    }, monkeypatch, transport)
    env["NOVEL_FORGE_ENVIRONMENT"] = "production"
    executable = Path(env["NOVEL_FORGE_CODEX_EXECUTABLE"])
    executable.write_text(executable.read_text().replace(
        ' target.write_bytes(',
        ''' if target.with_name("interrupt-stream").exists():
  print(json.dumps({"type":"thread.started","thread_id":"controlled-interrupted-generation"}))
  print(json.dumps({"type":"turn.failed","error":{"message":"stream disconnected before completion"}}))
  sys.exit(1)
 target.write_bytes('''))
    env["NOVEL_FORGE_CODEX_EXECUTABLE_SHA256"] = "sha256:" + hashlib.sha256(executable.read_bytes()).hexdigest()
    from novel_forge.modules.chapter_authority.execution_gateway import PostgresProductionExecutionPayloadResolver
    from novel_forge.modules.production_execution.process_supervisor import PersistentExecutionDirectory
    resolve = PostgresProductionExecutionPayloadResolver.resolve
    stream_failures = []
    compression_calls = []
    def interrupt_first_memo(resolver, request, admission):
        payload = resolve(resolver, request, admission)
        if request.stage in {"context_compress", "context_fidelity"}:
            compression_calls.append((request.operation_id, request.stage))
        failure_stage = "context_fidelity" if completed_sibling else "memo"
        if not recoverable_result and request.stage == failure_stage and not stream_failures:
            layout = PersistentExecutionDirectory(env["NOVEL_FORGE_CODEX_EXECUTION_ROOT"]).prepare(request.execution_id)
            layout.result_path("interrupt-stream").write_text("controlled fault")
            stream_failures.append(request.operation_id)
        return payload
    monkeypatch.setattr(PostgresProductionExecutionPayloadResolver, "resolve", interrupt_first_memo)
    if completed_sibling:
        prepare_context_model_stages(transport, monkeypatch)
    if recoverable_result:
        from dataclasses import replace
        from novel_forge.modules.chapter_authority.execution_gateway import ProductionExecutionGatewayExternalEffectAdapter
        execute = ProductionExecutionGatewayExternalEffectAdapter.execute
        def lose_completed_response(adapter, **options):
            result = execute(adapter, **options)
            payload = options["request_payload"]
            if payload.get("stage") == "memo" and not stream_failures:
                assert result.outcome == "success"
                stream_failures.append(payload["operation_id"])
                return replace(result, outcome="unknown")
            return result
        monkeypatch.setattr(ProductionExecutionGatewayExternalEffectAdapter, "execute", lose_completed_response)
    if not completed_sibling and not recoverable_result:
        from novel_forge.modules.command_kernel import generation_isolation, step_successor_v2
        from concurrent.futures import ThreadPoolExecutor
        native_recovery = generation_isolation.recover_chapter_generations
        admission_checked = []
        def verify_atomic_recovery(authority, **options):
            if admission_checked:
                return native_recovery(authority, **options)
            book = authority.require(options["book_run_id"])
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("""SELECT to_jsonb(o) FROM authority_operation o
                    JOIN authority_external_effect e USING(operation_id)
                    WHERE o.project_id=%s AND o.definition_name='chapter.memo.generate' AND e.status='UNKNOWN'""", [book["project_id"]])
                original = uow.cursor.fetchone()
            if original is None:
                return native_recovery(authority, **options)
            def interrupt_admission(*args, **kwargs):
                raise RuntimeError("controlled successor admission interruption")
            with monkeypatch.context() as fault:
                fault.setattr(step_successor_v2, "replace_failed_step", interrupt_admission)
                with pytest.raises(RuntimeError, match="controlled successor admission interruption"):
                    native_recovery(authority, **options)
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s", [original[0]["operation_id"]])
                assert uow.cursor.fetchone() == original
                uow.cursor.execute("SELECT count(*) FROM authority_generation_isolation WHERE operation_id=%s", [original[0]["operation_id"]])
                assert uow.cursor.fetchone() == (0,)
                uow.cursor.execute("SELECT count(*) FROM authority_saga_step_successor WHERE predecessor_operation_id=%s", [original[0]["operation_id"]])
                assert uow.cursor.fetchone() == (0,)
            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(lambda _: native_recovery(authority, **options), range(2)))
            assert sum(outcomes) == 1
            admission_checked.append(True)
            return True
        monkeypatch.setattr(generation_isolation, "recover_chapter_generations", verify_atomic_recovery)
    env["NOVEL_FORGE_LOCAL_OPERATOR_PRINCIPAL_ID"] = "native-creation-operator"
    env["NOVEL_FORGE_NARRATIVE_EVALUATOR_PRINCIPAL_ID"] = "native-planning-evaluator"
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("NOVEL_FORGE_DEEPSEEK_BUDGET_TEMPLATE_FILE", str(tmp_path / "not-authorized.json"))
    transport.database_url = DATABASE_URL
    inputs = {"version": "creation-request.v1", "title": f"Author work {harness.project_id} sibling={completed_sibling} recoverable={recoverable_result} enhanced={enhanced_working}", "target_chapters": 8,
        "execution_window": {"version": "creation-execution-window.v1", "stop_after_chapter": 6},
        "chapter_length": {"minimum": 800, "maximum": 4000}, "language_contract": {"required_language": "zh-CN"},
        "brief": {"creative_brief_contract_version": "creative-brief-v2", "idea": "An archivist investigates a flood.",
            "genre": "social mystery", "audience": "adult readers", "constraints": ["Six chapters across a ChapterGroup boundary"],
            "source_boundaries": ["Original work"]}}
    source = tmp_path / "request.json"
    source.write_text(json.dumps(inputs))
    parser = _authority_parser()
    args = parser.parse_args(["authority-creation", "start", "--input-file", str(source),
        "--repository-root", str(root), "--maximum-ticks", "100",
        "--foreground"])
    if enhanced_working:
        creation_policy = json.loads((root / "config/execution_templates/creation_inputs.json").read_text())
        creation_policy["profiles"]["production_profile"]["content"]["working_prose_policy"] = {
            "version": "working-prose-projection.v3" if enhanced_working == "memory" else "working-prose-projection.v2", "history_chapters": 8,
            "recent_complete_chapters": 2, "max_characters": 32000,
            "queries": ["flood"], "guidance_mode": "COMBINED"}
        args.creation_policy_file = tmp_path / "working-creation-policy.json"
        args.creation_policy_file.write_text(json.dumps(creation_policy))
    settings = IndustrialSettings(root=tmp_path, database_url=DATABASE_URL, environment="production")
    from novel_forge.api import authority_dependencies
    build_book = authority_dependencies.build_book_production_composition
    interruptions = []
    def fail_delivery_once(checkpoint):
        if checkpoint == "after_manuscript_delivery" and not interruptions:
            interruptions.append(checkpoint)
            raise RuntimeError("controlled interruption after saved prose")
    def with_interrupt(*values, **options):
        composition = build_book(*values, **options)
        composition.authority.failure_injector = fail_delivery_once
        return composition
    monkeypatch.setattr(authority_dependencies, "build_book_production_composition", with_interrupt)
    with pytest.raises(RuntimeError, match="controlled interruption"):
        started = run_creation_command(settings, args)
        raise AssertionError({key: started.get(key) for key in ("stop_reason", "reason_code", "reason")})
    if not completed_sibling and not recoverable_result:
        assert admission_checked == [True]
    from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
    principal = build_trusted_principal_resolver().resolve_api_principal()
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT to_jsonb(b) FROM authority_book_production b WHERE project_id=(SELECT project_id FROM authority_operation WHERE operation_id=%s)", [stream_failures[0]])
        stopped = uow.cursor.fetchone()[0]
        project = stopped["project_id"]
        args.project_id, args.workspace_id, args.book_id = project, stopped["workspace_id"], stopped["book_id"]
        uow.cursor.execute("SELECT formation_run_id FROM authority_story_formation_run WHERE project_id=%s", [project])
        formation = uow.cursor.fetchone()[0]
    retained = current_manuscript(DATABASE_URL, book=stopped, principal=principal)
    assert len(stream_failures) == 1
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("""SELECT original.status,effect.status,budget.status,child.status,
            isolation.proof#>>'{observed_failure,error_code}' FROM authority_generation_isolation isolation
            JOIN authority_operation original ON original.operation_id=isolation.operation_id
            JOIN authority_external_effect effect USING(external_effect_id)
            JOIN authority_budget_reservation budget USING(external_effect_id)
            JOIN authority_saga_step_successor successor ON successor.predecessor_operation_id=original.operation_id
            JOIN authority_operation child ON child.operation_id=successor.successor_operation_id
            WHERE original.operation_id=%s""", [stream_failures[0]])
        if recoverable_result:
            assert uow.cursor.fetchone() is None
            uow.cursor.execute("SELECT status FROM authority_operation WHERE operation_id=%s", [stream_failures[0]])
            assert uow.cursor.fetchone() == ("SUCCEEDED",)
            uow.cursor.execute("SELECT count(*) FROM authority_external_effect_dispatch WHERE external_effect_id IN (SELECT external_effect_id FROM authority_external_effect WHERE operation_id=%s)", [stream_failures[0]])
            assert uow.cursor.fetchone() == (1,)
            uow.cursor.execute("SELECT count(*) FROM authority_saga_step_successor WHERE predecessor_operation_id=%s", [stream_failures[0]])
            assert uow.cursor.fetchone() == (0,)
        else:
            assert uow.cursor.fetchone() == ("FAILED_FINAL", "UNKNOWN", "HELD_UNKNOWN", "SUCCEEDED", "PROVIDER_STREAM_INTERRUPTED")
    if completed_sibling:
        assert [stage for operation, stage in compression_calls] == ["context_compress", "context_fidelity", "context_fidelity"]
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("SELECT status,count(*) FROM authority_external_effect WHERE operation_id=%s GROUP BY status", [stream_failures[0]])
            assert dict(uow.cursor.fetchall()) == {"SUCCEEDED": 1, "UNKNOWN": 1}
            uow.cursor.execute("""SELECT effect.request_payload->>'stage',effect.status FROM authority_external_effect effect
                JOIN authority_saga_step_successor journal ON journal.successor_operation_id=effect.operation_id
                WHERE journal.predecessor_operation_id=%s""", [stream_failures[0]])
            assert uow.cursor.fetchall() == [("context_fidelity", "SUCCEEDED")]
            uow.cursor.execute("SELECT count(*) FROM authority_saga_step_successor WHERE predecessor_operation_id=%s", [stream_failures[0]])
            assert uow.cursor.fetchone()[0] == 1
    assert len(retained["units"]) == 1
    assert stopped["current_chapter"] == 0
    import time
    time.sleep(31)
    args.action, args.formation_run_id = "continue", formation
    result = run_creation_command(settings, args)
    assert result["stop_reason"] == "MANUSCRIPT_READY", result
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT to_jsonb(b) FROM authority_book_production b WHERE book_run_id=%s", [result["book_run_id"]])
        book = uow.cursor.fetchone()[0]
        assert book["current_chapter"] == 6
        assert book["target_chapter_count"] == 6
        uow.cursor.execute("SELECT content FROM authority_asset_version WHERE asset_version_id=%s", [book["book_design_version"]])
        assert uow.cursor.fetchone()[0]["target_chapters"] == 8
        assert "execution_window" not in json.dumps(transport.calls, ensure_ascii=False)
        assert book["accepted_through_chapter"] == 0
        uow.cursor.execute("SELECT definition_name,count(*) FROM authority_operation WHERE project_id=%s GROUP BY definition_name", [project])
        counts = dict(uow.cursor.fetchall())
        assert counts["chapter.draft.generate"] == 6
        assert not any(count for name, count in counts.items() if name.startswith(("chapter.review.", "chapter.quality.", "chapter.canon.", "chapter.revision.")))
    from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
    principal = build_trusted_principal_resolver().resolve_api_principal()
    from novel_forge.modules.book_authority.queries import PostgresBookProductionQuery
    assert not PostgresBookProductionQuery(DATABASE_URL).coordination_candidates(limit=10, book_run_id=book["book_run_id"])
    manifest = current_manuscript(DATABASE_URL, book=book, principal=principal)
    assert len(manifest["units"]) == 6
    assert all(unit["quality_status"] == "NOT_VERIFIED" for unit in manifest["units"])
    prefix_versions = [unit["asset_version_id"] for unit in manifest["units"]]
    from fastapi.testclient import TestClient
    from novel_forge.api.authority_app import create_authority_app
    client = TestClient(create_authority_app(settings))
    extension = {"project_id": project, "book_run_id": book["book_run_id"],
        "expected_version": book["version"], "stop_after_chapter": 8, "idempotency_key": f"{project}:extend-native-to-eight"}
    outside = client.post("/product/editor/manuscripts/extend-delivery-window", json={**extension, "project_id": "another-project"})
    assert outside.status_code == 403
    extended = client.post("/product/editor/manuscripts/extend-delivery-window", json=extension)
    assert extended.status_code == 200, extended.json()
    assert client.post("/product/editor/manuscripts/extend-delivery-window", json=extension).json()["replayed"]
    continued = run_creation_command(settings, args)
    assert continued["stop_reason"] == "MANUSCRIPT_READY", continued
    from novel_forge.modules.book_authority.production import PostgresBookAuthority
    book = PostgresBookAuthority(DATABASE_URL, chapter_port=None, followup_application=None,
        application_build_id=harness.application_build_id, commit_sha=harness.release_sha).require(book["book_run_id"])
    manifest = current_manuscript(DATABASE_URL, book=book, principal=principal)
    assert len(manifest["units"]) == 8 and book["current_chapter"] == 8 and book["accepted_through_chapter"] == 0
    assert [unit["asset_version_id"] for unit in manifest["units"][:6]] == prefix_versions
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT context_snapshot FROM authority_book_manuscript_delivery WHERE book_run_id=%s AND chapter_number=7", [book["book_run_id"]])
        frozen_working = uow.cursor.fetchone()[0]
        sources = frozen_working["sources"]
        if enhanced_working:
            assert frozen_working["projection_policy"]["version"] == ("working-prose-projection.v3" if enhanced_working == "memory" else "working-prose-projection.v2")
            assert len(sources) == 6 and sources[-1]["omitted_ranges"] == []
            uow.cursor.execute("""SELECT content FROM authority_asset_version v JOIN authority_asset a USING(asset_id)
                WHERE a.project_id=%s AND a.asset_type='chapter_execution_intent'
                AND (content->>'chapter')::integer=7 ORDER BY v.created_at DESC LIMIT 1""", [project])
            frozen_intent = uow.cursor.fetchone()[0]
            assert frozen_intent["working_manuscript"] == frozen_working
            assert frozen_intent["accepted_boundary"]["accepted_through_chapter"] == 0
            assert frozen_intent["working_manuscript"]["structured_facts"] == []
            if enhanced_working == "memory":
                assert frozen_working["working_memory"]["entries"][0]["source"]["chapter"] == 1
                assert next(row for row in frozen_working["working_memory"]["source_coverage"] if row["chapter"] == 2)["status"] == "UNAVAILABLE"
                second = uow.repositories.asset_documents.require(project_id=project, asset_version_id=prefix_versions[1])
                assert second.content["working_memory"]["prose_preserved"]
        assert any(source["chapter"] == 6 and source["asset_version_id"] == prefix_versions[5] for source in sources)
    from novel_forge.modules.book_followup_authority.application import BookFollowupAuthorityApplication
    from novel_forge.modules.book_followup_authority.prose_coordinator import BookProseReviewCoordinator
    from novel_forge.modules.command_kernel.errors import KernelError
    class UnavailableReview:
        external_effect_backed = True
        database_url = DATABASE_URL
        def invoke(self, *args, **kwargs):
            raise KernelError("CONTROLLED_OPTIONAL_SERVICE_UNAVAILABLE", "Isolated optional service outage; no Provider dispatch")
    followup = BookFollowupAuthorityApplication(DATABASE_URL, application_build_id=harness.application_build_id, commit_sha=harness.release_sha, prose_model_port=UnavailableReview())
    coordinator = BookProseReviewCoordinator(followup)
    review_scope = dict(project_id=project, workspace_id=book["workspace_id"], book_run_id=book["book_run_id"], principal=principal)
    review = coordinator.start(**review_scope, policy={"policy_version": "author-prose-review.v1", "window_codepoints": 4000,
        "overlap_codepoints": 200, "context_token_budget": 16000, "maximum_windows": 8},
        idempotency_key=f"{project}:optional-review", trace_id="trace-optional", correlation_id="correlation-optional")
    report = coordinator.report(**review_scope, run_id=review["run_id"])
    assert report["source_current"] is True
    assert report["review_complete"] is False
    if enhanced_working == "memory":
        from novel_forge.modules.book_followup_authority.prose_review import PROSE_DIMENSIONS
        from novel_forge.modules.chapter_authority.model_effects import ModelProviderResult
        class RootCauseReview(UnavailableReview):
            def invoke(self, request, *, stage, payload, **options):
                window = request.require_input("longform_prose_review_window").content
                assert payload["prose_diagnosis_contract"] == "prose-root-cause.v1"
                span = window["window"]["spans"][0]
                return ModelProviderResult(output={"schema_version": "longform-prose-review.v2",
                    "manifest_digest": window["manifest_digest"], "window_id": window["window"]["window_id"],
                    "reviewed_dimensions": list(PROSE_DIMENSIONS), "findings": [{
                        "lineage_id": "controlled-future-plot:" + window["window"]["window_id"], "dimension": "motivation_cost", "judgment": "ISSUE",
                        "severity": "MAJOR", "confidence": 0.8, "claim": "Controlled future-plot diagnosis.",
                        "rationale": "Test source binding and native repair routing only.",
                        "evidence": [{"asset_version_id": span["asset_version_id"], "text_hash": span["text_hash"],
                            "start": span["start"], "end": span["start"]+2, "quote": span["text"][:2]}],
                        "repair": {"root_cause": "UPPER_PLOT", "problem_owner": "PLAN", "repair_scope": "FUTURE_REPLAN",
                            "revision_goal": "Review future plot intent.", "preserve": ["Selected manuscripts."],
                            "resolution_criteria": ["Bind an exact future plan candidate."]}}]},
                    provider_id="fixture", model_id="fixture", prompt_version="fixture.v1", skill_version="fixture.v1",
                    input_tokens=1, output_tokens=1, cost_amount="0", currency="USD", real_model_call=False)
        diagnostic = BookProseReviewCoordinator(BookFollowupAuthorityApplication(DATABASE_URL,
            application_build_id=harness.application_build_id, commit_sha=harness.release_sha, prose_model_port=RootCauseReview()))
        diagnosed = diagnostic.start(**review_scope, policy={"policy_version": "author-root-cause.v1", "window_codepoints": 4000,
            "overlap_codepoints": 200, "context_token_budget": 16000, "maximum_windows": 8,
            "diagnosis_contract": "prose-root-cause.v1"}, idempotency_key=f"{project}:root-cause", trace_id="trace-root", correlation_id="correlation-root")
        diagnosed = diagnostic.report(**review_scope, run_id=diagnosed["run_id"])
        for turn in range(10):
            if diagnosed["review_complete"]:
                break
            diagnosed = diagnostic.advance(**review_scope, run_id=diagnosed["run_id"], expected_version=diagnosed["expected_version"],
                idempotency_key=f"{project}:root-cause:{turn}", trace_id="trace-root", correlation_id="correlation-root")
        assert diagnosed["review_complete"] and diagnosed["independent_human_review"] == "NOT_RUN"
        assert diagnosed["findings"][0]["repair_route"]["consumer"] == "NATIVE_PLAN_CHANGE_OR_BOOK_REPLAN"
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT manifest FROM authority_book_prose_review_run WHERE run_id=%s", [review["run_id"]])
        frozen_review = uow.cursor.fetchone()[0]
        assert frozen_review["source_isolation"] == "AUTHOR_SELECTED_UNREVIEWED_PROSE"
        assert all(source["acceptance_id"] == "" for source in frozen_review["sources"])
    with pytest.raises(KernelError, match="CONTROLLED_OPTIONAL_SERVICE_UNAVAILABLE"):
        coordinator.advance(**review_scope, run_id=review["run_id"], expected_version=report["expected_version"],
            idempotency_key=f"{project}:optional-outage", trace_id="trace-outage", correlation_id="correlation-outage")
    from novel_forge.modules.book_authority.manuscript import blocking_working_cli_outcomes
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT content->>'operation_id' FROM authority_book_prose_review_event WHERE run_id=%s AND kind='WINDOW_ADMITTED'", [review["run_id"]])
        review_operation = uow.cursor.fetchone()[0]
        simulated_unknown = [{"operation_id": review_operation, "usage": "UNKNOWN"}]
        assert not blocking_working_cli_outcomes(uow.cursor, project_id=project, book_id=book["book_id"],
            book_run_id=book["book_run_id"], outcomes=simulated_unknown)
        uow.cursor.execute("SELECT operation_id FROM authority_operation WHERE project_id=%s AND definition_name='chapter.draft.generate' ORDER BY created_at DESC LIMIT 1", [project])
        draft_operation = uow.cursor.fetchone()[0]
        assert not blocking_working_cli_outcomes(uow.cursor, project_id=project, book_id=book["book_id"],
            operation_id=draft_operation, outcomes=simulated_unknown)
        assert blocking_working_cli_outcomes(uow.cursor, project_id=project, book_id=book["book_id"],
            operation_id=review_operation, outcomes=simulated_unknown) == simulated_unknown
        required_unknown = [{"operation_id": draft_operation, "usage": "UNKNOWN"}]
        assert blocking_working_cli_outcomes(uow.cursor, project_id=project, book_id=book["book_id"],
            book_run_id=book["book_run_id"], outcomes=required_unknown) == required_unknown
    usable = current_manuscript(DATABASE_URL, book=book, principal=principal)
    assert len(usable["units"]) == 8
    assert usable["units"][0]["review_status"] == ("COMPLETED" if enhanced_working == "memory" else "FAILED")
    assert usable["units"][0]["asset_version_id"] == manifest["units"][0]["asset_version_id"]
    unit = manifest["units"][0]
    if enhanced_working == "memory":
        from novel_forge.modules.book_authority.manuscript_memory import save_manuscript_memory
        from novel_forge.modules.book_authority.production import PostgresBookAuthority
        from novel_forge.modules.book_authority.manuscript import freeze_working_context, verify_working_context
        authority = PostgresBookAuthority(DATABASE_URL, chapter_port=None, followup_application=None,
            application_build_id=harness.application_build_id, commit_sha=harness.release_sha)
        current = authority.require(book["book_run_id"])
        memory_args = dict(chapter=1, source_asset_version_id=unit["asset_version_id"], expected_version=current["version"],
            observations=[{"kind": "EVENT", "subject": "scene", "state_key": "opening", "claim": "The opening event occurred in the selected working version.",
                "perspective": "OBSERVED", "knowledge_owner": "", "quote": unit["text"], "causes": []}],
            idempotency_key=project+":working-memory", source_kind="ASSISTANT_ANALYSIS", principal=principal)
        receipt = save_manuscript_memory(authority, book["book_run_id"], **memory_args)
        assert receipt["formal_acceptance"] == "NOT_GRANTED"
        assert save_manuscript_memory(authority, book["book_run_id"], **memory_args)["replayed"]
        memory_response = client.get("/product/editor/manuscripts/memory", params={"project_id": project, "book_run_id": book["book_run_id"], "max_characters": 32000})
        assert memory_response.status_code == 200, memory_response.json()
        assert memory_response.json()["working_memory"]["candidate_count"] == 1
        with pytest.raises(KernelError, match="checkpoint"):
            save_manuscript_memory(authority, book["book_run_id"], **{**memory_args, "idempotency_key": project+":stale-memory"})
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            current = authority.require(book["book_run_id"])
            verify_working_context(uow, current, frozen_working, require_current=False)
        book = current
    editor = ChapterAuthorEditingApplication(DATABASE_URL, application_build_id=harness.application_build_id, commit_sha=harness.release_sha)
    scope = {key: book[key] for key in ("project_id", "workspace_id", "book_id")}
    scope.update(chapter=1, base_asset_version_id=unit["asset_version_id"])
    opened = editor.require(**scope, principal=principal)
    before = unit["text"]
    payload = {**scope, "base_text_hash": unit["text_hash"], "base_asset_hash": unit["content_hash"], "expected_version": opened["version"],
        "text": before + " 作者增补。", "rights_basis": "ORIGINAL_AUTHOR_INPUT", "allowed_ranges": [{"start": len(before), "end": len(before)}]}
    from novel_forge.cli.manuscript import run_manuscript_command
    text_file = tmp_path / "author-wording.txt"
    text_file.write_text(payload["text"], encoding="utf-8")
    edit_args = parser.parse_args(["authority-manuscript", "edit", "--book-run-id", book["book_run_id"], "--chapter", "1", "--text-file", str(text_file)])
    saved = run_manuscript_command(settings, edit_args)
    assert saved["candidate_asset_version_id"]
    replay = run_manuscript_command(settings, edit_args)
    assert replay["replayed"] and replay["operation_id"] == saved["operation_id"]
    edit_args.action, edit_args.candidate_version = "adopt", saved["candidate_asset_version_id"]
    accepted = run_manuscript_command(settings, edit_args)
    replay = run_manuscript_command(settings, edit_args)
    assert replay["replayed"] and replay["operation_id"] == accepted["operation_id"]
    assert accepted["decision_asset_version_id"]
    updated = current_manuscript(DATABASE_URL, book=book, principal=principal)
    assert updated["units"][0]["text"].endswith(" 作者增补。")
    if enhanced_working == "memory":
        memory_response = client.get("/product/editor/manuscripts/memory", params={"project_id": project, "book_run_id": book["book_run_id"], "max_characters": 32000})
        assert memory_response.status_code == 200
        assert memory_response.json()["working_memory"]["candidate_count"] == 0
        with pytest.raises(KernelError, match="unselected"):
            save_manuscript_memory(authority, book["book_run_id"], **{**memory_args,
                "expected_version": authority.require(book["book_run_id"])["version"], "idempotency_key": project+":old-source-memory"})

    assert updated["units"][1]["asset_version_id"] == manifest["units"][1]["asset_version_id"]
    assert updated["units"][1]["dependency_changes"]
    assert any(change["chapter"] == 1 and (enhanced_working or "via_chapter" in change)
        for change in updated["units"][5]["dependency_changes"])
    from novel_forge.modules.command_kernel.errors import KernelError
    with pytest.raises(KernelError, match="Export must match"):
        current_manuscript(DATABASE_URL, book=book, principal=principal, version_ids=[u["asset_version_id"] for u in manifest["units"]])
    exact = current_manuscript(DATABASE_URL, book=book, principal=principal, version_ids=[u["asset_version_id"] for u in updated["units"]])
    assert exact["text_digest"] == updated["text_digest"]

    stale_review = coordinator.report(**review_scope, run_id=review["run_id"])
    assert stale_review["source_current"] is False
    from fastapi.testclient import TestClient
    from novel_forge.api.authority_app import create_authority_app
    monkeypatch.setenv("NOVEL_FORGE_CODEX_EXECUTABLE", str(tmp_path / "provider-unavailable"))
    monkeypatch.delenv("NOVEL_FORGE_SOURCE_IMPORT_GIT_CACHE_ROOT", raising=False)
    app = create_authority_app(settings)
    client = TestClient(app)
    query = {"project_id": project, "book_run_id": book["book_run_id"]}
    assert client.get("/product/editor/manuscripts", params=query).status_code == 200
    assert client.post("/product/editor/manuscripts/export", json={**query, "version_ids": [unit["asset_version_id"] for unit in manifest["units"]]}).status_code == 409
    exported = client.post("/product/editor/manuscripts/export", json={**query, "chapters": [2], "version_ids": [updated["units"][1]["asset_version_id"]]})
    assert exported.status_code == 200
    assert [unit["chapter"] for unit in exported.json()["units"]] == [2]
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT count(*) FROM authority_operation WHERE project_id=%s AND definition_name='chapter.draft.generate'", [project])
        assert uow.cursor.fetchone()[0] == 8
    if not completed_sibling and not recoverable_result:
        from tests.integration.migration_window_postgres_support import restored_generation_backup
        with restored_generation_backup(DATABASE_URL, backup_root=tmp_path / "chapter-joint-backup",
                execution_root=Path(env["NOVEL_FORGE_CODEX_EXECUTION_ROOT"])) as restored_url:
            assert current_manuscript(restored_url, book=book, principal=principal) == current_manuscript(DATABASE_URL, book=book, principal=principal)
            from novel_forge.storage.migrations import get_migration_status
            assert get_migration_status(restored_url)["ok"]


def test_legacy_workflow_adoption_keeps_frozen_profile_and_replays_checkpoint():
    from dataclasses import replace
    from tests.integration.test_book_to_chapter_authority_vertical_postgres import BookToChapterAuthorityVerticalPostgresTests
    from novel_forge.modules.authority_handler_runtime.policy_commands import configure_owned_policy
    from novel_forge.modules.book_authority.manuscript import adopt_author_workflow, AUTHOR_WORKFLOW
    from novel_forge.modules.command_kernel.errors import KernelError
    case = BookToChapterAuthorityVerticalPostgresTests()
    try:
        fixture = case._new_book_fixture(target_chapter_count=2)
        authority, principal = fixture['authority'], fixture['principal']
        principal = replace(principal, permissions=principal.permissions | {'book.authority.query'})
        book = authority.require(fixture['book'].book_run_id)
        value = json.loads((Path(__file__).resolve().parents[2] / 'config/execution_templates/author_first.json').read_text())
        value.update(book_id=book['book_id'], member_authorization_ref='controlled-member-grant', allowed_candidates=['codex-cli:gpt-test:high'])
        configure_owned_policy(database_url=DATABASE_URL, owner='PROVIDER_ROUTING', project_id=book['project_id'], workspace_id=book['workspace_id'],
            principal=principal, application_build_id=authority.application_build_id, commit_sha=authority.commit_sha,
            idempotency_key='adoption-routing', trace_id='adoption-routing', correlation_id=book['book_id'],
            content={'policy_version':'author-adoption-test.v1','task_overrides':[], 'reason':'controlled historical checkpoint', 'execution_templates':[value]})
        adopted = adopt_author_workflow(authority, book['book_run_id'], principal=principal,
            expected_version=book['version'], idempotency_key='adopt-current')
        current = authority.require(book['book_run_id'])
        assert current['author_workflow'] == AUTHOR_WORKFLOW
        assert current['production_profile_version'] == book['production_profile_version']
        assert current['accepted_through_chapter'] == book['accepted_through_chapter']
        replay = adopt_author_workflow(authority, book['book_run_id'], principal=principal,
            expected_version=book['version'], idempotency_key='adopt-current')
        assert replay['replayed'] and replay['operation_id'] == adopted['operation_id']
        with pytest.raises(KernelError, match='AUTHOR_WORKFLOW_CHECKPOINT_REQUIRED'):
            adopt_author_workflow(authority, book['book_run_id'], principal=principal,
                expected_version=book['version'], idempotency_key='stale-new-key')
    finally:
        case.doCleanups()


@pytest.mark.parametrize("failure_stage", ["memo", "context_compress", "context_fidelity"])
def test_native_generation_fault_allowance_survives_successors_and_stops_dispatch(tmp_path, monkeypatch, failure_stage):
    harness = CapabilityPackPostgresHarness('bounded-generation-faults')
    root = Path(__file__).resolve().parents[2]
    transport = SynthesisTransport()
    env = controlled_member_environment(tmp_path, {
        'NOVEL_FORGE_APPLICATION_BUILD_ID': harness.application_build_id,
        'NOVEL_FORGE_COMMIT_SHA': harness.release_sha,
        'NOVEL_FORGE_MODEL_PROVIDER': 'codex-cli', 'NOVEL_FORGE_MODEL': 'gpt-test',
        'NOVEL_FORGE_PLANNING_PROVIDER': 'codex-cli', 'NOVEL_FORGE_PLANNING_MODEL': 'gpt-test',
        'NOVEL_FORGE_STORAGE_AUTHORITY': 'postgresql', 'NOVEL_FORGE_DATABASE_URL': DATABASE_URL,
        'NOVEL_FORGE_OPERATOR_PRINCIPAL_ID': 'bounded-fault-operator',
    }, monkeypatch, transport)
    env['NOVEL_FORGE_ENVIRONMENT'] = 'production'
    executable = Path(env['NOVEL_FORGE_CODEX_EXECUTABLE'])
    executable.write_text(executable.read_text().replace(' target.write_bytes(', ''' if target.with_name("interrupt-stream").exists():
  print(json.dumps({"type":"thread.started","thread_id":"controlled-bounded-generation"}))
  print(json.dumps({"type":"turn.failed","error":{"message":"stream disconnected before completion"}}))
  sys.exit(1)
 target.write_bytes('''))
    env['NOVEL_FORGE_CODEX_EXECUTABLE_SHA256'] = 'sha256:' + hashlib.sha256(executable.read_bytes()).hexdigest()
    env['NOVEL_FORGE_LOCAL_OPERATOR_PRINCIPAL_ID'] = 'bounded-fault-operator'
    env['NOVEL_FORGE_NARRATIVE_EVALUATOR_PRINCIPAL_ID'] = 'bounded-planning-evaluator'
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    monkeypatch.setenv('NOVEL_FORGE_DEEPSEEK_BUDGET_TEMPLATE_FILE', str(tmp_path / 'not-authorized.json'))
    transport.database_url = DATABASE_URL
    from novel_forge.modules.chapter_authority.execution_gateway import PostgresProductionExecutionPayloadResolver
    from novel_forge.modules.production_execution.process_supervisor import PersistentExecutionDirectory
    resolve = PostgresProductionExecutionPayloadResolver.resolve
    executions = set()
    def interrupt_every_memo(resolver, request, admission):
        payload = resolve(resolver, request, admission)
        if request.stage == failure_stage:
            layout = PersistentExecutionDirectory(env['NOVEL_FORGE_CODEX_EXECUTION_ROOT']).prepare(request.execution_id)
            layout.result_path('interrupt-stream').write_text('controlled persistent stream failure')
            executions.add(request.execution_id)
        return payload
    monkeypatch.setattr(PostgresProductionExecutionPayloadResolver, 'resolve', interrupt_every_memo)
    if failure_stage.startswith('context_'):
        prepare_context_model_stages(transport, monkeypatch)
    source = tmp_path / 'request.json'
    source.write_text(json.dumps({'version':'creation-request.v1','title':f'Bounded generation {failure_stage}','target_chapters':1,
        'language_contract':{'required_language':'zh-CN'},'chapter_length':{'minimum':800,'maximum':4000},
        'brief':{'creative_brief_contract_version':'creative-brief-v2','idea':'An archivist investigates a flood.',
            'genre':'social mystery','audience':'adult readers','constraints':['Original single chapter'],
            'source_boundaries':['Original work']}}))
    args = _authority_parser().parse_args(['authority-creation','start','--input-file',str(source),
        '--repository-root',str(root),'--maximum-ticks','100','--work-window-seconds','180','--foreground','--yield-after-window'])
    settings = IndustrialSettings(root=tmp_path, database_url=DATABASE_URL, environment='production')
    result = run_creation_command(settings, args)
    assert result['stop_reason'] == 'GENERATION_RECOVERY_EXHAUSTED', result
    assert result['checkpoint']['state'] == 'PAUSED'
    assert result['checkpoint']['paused_reason'] == 'GENERATION_RECOVERY_EXHAUSTED'
    from novel_forge.modules.command_kernel.generation_isolation import generation_retry_usage, require_generation_retry_budget, book_recovery_projection
    from novel_forge.modules.command_kernel.errors import KernelError
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT effect.operation_id FROM authority_external_effect effect JOIN authority_operation operation USING(operation_id) WHERE effect.project_id=%s AND effect.effect_type='model.invoke' AND operation.definition_name=%s AND effect.request_payload->>'stage'=%s ORDER BY effect.created_at", [result['project_id'], 'chapter.context.build' if failure_stage.startswith('context_') else 'chapter.memo.generate', failure_stage])
        operations = [row[0] for row in uow.cursor.fetchall()]
        assert len(operations) == len(executions) == 2
        usage = generation_retry_usage(uow.cursor, operation_id=operations[-1])
        assert usage['failure_attempts'] == usage['maximum_failure_attempts'] == 2
        with pytest.raises(KernelError, match='GENERATION_RECOVERY_EXHAUSTED'):
            require_generation_retry_budget(uow.cursor, operation_id=operations[-1])
        projections = book_recovery_projection(uow.cursor, project_id=result['project_id'], book_id=result['book_id'])
        assert any(row['successor_failure'] and row['successor_failure'].get('error_code') for row in projections)
    restarted = args
    restarted.action = 'continue'
    restarted.project_id, restarted.workspace_id, restarted.book_id = result['project_id'], result['checkpoint']['workspace_id'], result['book_id']
    restarted.formation_run_id = result['formation_run_id']
    repeated = run_creation_command(settings, restarted)
    assert repeated['stop_reason'] == 'GENERATION_RECOVERY_EXHAUSTED', repeated
    assert len(executions) == 2
