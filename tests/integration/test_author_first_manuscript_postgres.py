import json
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


def test_native_author_first_cross_chapter_edit_and_export(tmp_path, monkeypatch):
    harness = CapabilityPackPostgresHarness("author-first")
    project = harness.project_id + "-native"
    root = Path(__file__).resolve().parents[2]
    transport = SynthesisTransport()
    env = controlled_member_environment(tmp_path, {
        "NOVEL_FORGE_APPLICATION_BUILD_ID": harness.application_build_id,
        "NOVEL_FORGE_COMMIT_SHA": harness.release_sha,
        "NOVEL_FORGE_MODEL_PROVIDER": "codex-cli", "NOVEL_FORGE_MODEL": "gpt-test",
        "NOVEL_FORGE_PLANNING_PROVIDER": "codex-cli", "NOVEL_FORGE_PLANNING_MODEL": "gpt-test",
        "NOVEL_FORGE_STORAGE_AUTHORITY": "postgresql", "NOVEL_FORGE_DATABASE_URL": DATABASE_URL,
        "NOVEL_FORGE_OPERATOR_PRINCIPAL_ID": "native-creation-operator",
    }, monkeypatch, transport)
    env["NOVEL_FORGE_ENVIRONMENT"] = "production"
    env["NOVEL_FORGE_LOCAL_OPERATOR_PRINCIPAL_ID"] = "native-creation-operator"
    env["NOVEL_FORGE_NARRATIVE_EVALUATOR_PRINCIPAL_ID"] = "native-planning-evaluator"
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("NOVEL_FORGE_DEEPSEEK_BUDGET_TEMPLATE_FILE", str(tmp_path / "not-authorized.json"))
    transport.database_url = DATABASE_URL
    inputs = {"version": "creation-request.v1", "title": "Author work", "target_chapters": 8,
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
    from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
    principal = build_trusted_principal_resolver().resolve_api_principal()
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT to_jsonb(b) FROM authority_book_production b")
        stopped = uow.cursor.fetchone()[0]
        project = stopped["project_id"]
        args.project_id, args.workspace_id, args.book_id = project, stopped["workspace_id"], stopped["book_id"]
        uow.cursor.execute("SELECT formation_run_id FROM authority_story_formation_run WHERE project_id=%s", [project])
        formation = uow.cursor.fetchone()[0]
    retained = current_manuscript(DATABASE_URL, book=stopped, principal=principal)
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
        idempotency_key="optional-review", trace_id="trace-optional", correlation_id="correlation-optional")
    report = coordinator.report(**review_scope, run_id=review["run_id"])
    assert report["source_current"] is True
    assert report["review_complete"] is False
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT manifest FROM authority_book_prose_review_run WHERE run_id=%s", [review["run_id"]])
        frozen_review = uow.cursor.fetchone()[0]
        assert frozen_review["source_isolation"] == "AUTHOR_SELECTED_UNREVIEWED_PROSE"
        assert all(source["acceptance_id"] == "" for source in frozen_review["sources"])
    with pytest.raises(KernelError, match="CONTROLLED_OPTIONAL_SERVICE_UNAVAILABLE"):
        coordinator.advance(**review_scope, run_id=review["run_id"], expected_version=report["expected_version"],
            idempotency_key="optional-outage", trace_id="trace-outage", correlation_id="correlation-outage")
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
    assert len(usable["units"]) == 6
    assert usable["units"][0]["review_status"] == "FAILED"
    assert usable["units"][0]["asset_version_id"] == manifest["units"][0]["asset_version_id"]
    unit = manifest["units"][0]
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
    assert updated["units"][1]["asset_version_id"] == manifest["units"][1]["asset_version_id"]
    assert updated["units"][1]["dependency_changes"]
    assert any(change["chapter"] == 1 and "via_chapter" in change for change in updated["units"][5]["dependency_changes"])
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
        assert uow.cursor.fetchone()[0] == 6


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
