"""TEST: Native Source purpose admission precedes any model execution or Book creation."""
import json

import psycopg
import pytest

from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.test_corpus_ingestion_postgres import _manifest, _runtime

pytest_plugins = ["tests.integration.test_corpus_foundation_postgres"]


def _selection(corpus, tmp_path, monkeypatch, purpose, *, generation_granted=True):
    app, scheduler = _runtime(tmp_path, monkeypatch)
    path = tmp_path / (purpose + ".jsonl")
    path.write_text("\n".join(json.dumps({"book": "original-" + purpose, "chapter": str(n), "order": n,
                                        "text": "原创测试：一次冷却消耗一份清洁水。没有水就不能冷却。" * 15}) for n in (1, 2)))
    manifest = _manifest(path, purpose=purpose)
    if not generation_granted:
        manifest["rights"]["allowed_uses"].remove("ABSTRACT_GENERATION")
    request = corpus.client.post("/product/source-imports/corpus", json={
        "project_id": corpus.project, "workspace_id": corpus.workspace,
        "run_key": "source-" + purpose, "manifest": manifest})
    assert request.status_code == 202, request.text
    acquired = scheduler.run_or_recover(operation_id=request.json()["operation_id"], project_id=corpus.project)
    processed = scheduler.run_or_recover(operation_id=acquired["result"]["children"][0]["operation_id"], project_id=corpus.project)["result"]
    processing = processed["processing_id"]
    work = corpus.run({"action": "resolve_canonical_works", "changes": [{"work_key": purpose,
        "title": "Original purpose fixture", "language": "zh", "metadata_evidence": ["fixture:original-authorship"],
        "members": [{"processing_id": processing, "relation": "SAME_WORK", "evidence_refs": ["fixture:original-authorship"]}]}],
        "reason": "fixture native identity decision"})
    action = {"action": "revise_curated_corpus", "corpus_key": purpose, "title": purpose, "purpose": purpose,
              "filters": {"work_ids": [work["revisions"][0]["work_id"]]}, "reason": "explicit purpose fixture"}
    candidate = corpus.run(action)
    frozen = corpus.run({**action, "previous_id": candidate["revision_id"], "state": "FROZEN", "choices": [{
        "processing_id": processing, "selected": True, "reason": "original complete fixture", "evidence_refs": ["fixture:original-authorship"]}]})
    return app, scheduler, frozen


@pytest.mark.parametrize("purpose", ["RESEARCH", "PRODUCTION_REFERENCE"])
def test_native_analysis_checks_intended_book_use_before_model_or_book_creation(corpus, tmp_path, monkeypatch, purpose):
    _, _, frozen = _selection(corpus, tmp_path, monkeypatch, purpose)
    request = {"project_id": corpus.project, "revision_id": frozen["revision_id"], "run_key": "for-creative-book",
               "max_members": 1, "max_calls": 4, "max_tokens": 10000, "authorization_ref": "fixture:no-live-authorization",
               "intended_use": "ABSTRACT_GENERATION", "target_book_id": "declared-book:" + corpus.project}
    result = corpus.client.post("/product/source-imports/corpus/analyze", json=request)
    processing = frozen["availability"][0]["processing_id"]
    units = corpus.client.get(f"/product/source-imports/corpus/processing/{processing}/chapters", params={"project_id": corpus.project}).json()["units"]
    preview = corpus.client.post("/product/source-imports/corpus/reading-preview", json={
        "project_id": corpus.project, "revision_id": frozen["revision_id"],
        "intended_use": "ABSTRACT_GENERATION", "target_book_id": request["target_book_id"],
        "reading_scopes": [{"processing_id": processing, "first_unit_version_id": units[0]["source_unit_version_id"],
                            "last_unit_version_id": units[-1]["source_unit_version_id"], "max_chapters": 2}]})
    if purpose == "RESEARCH":
        assert result.status_code == 409 and "PRODUCTION_PURPOSE_NOT_GRANTED" in result.text, result.text
        assert preview.status_code == 409 and "PRODUCTION_PURPOSE_NOT_GRANTED" in preview.text, preview.text
        legacy = {key: value for key, value in request.items() if key not in {"intended_use", "target_book_id"}}
        legacy["run_key"] = "legitimate-research-analysis"
        research = corpus.client.post("/product/source-imports/corpus/analyze", json=legacy)
        assert research.status_code == 202, research.text
        assert research.json()["consumption_admission"]["book_status"] == "NOT_REQUESTED"
    else:
        assert result.status_code == 202, result.text
        assert preview.status_code == 200, preview.text
        assert preview.json()["consumption_admission"] == result.json()["consumption_admission"]
        admission = result.json()["consumption_admission"]
        assert admission["book_status"] == "PENDING_BOOK_CREATION"
        assert admission["knowledge_status"] == "PENDING_CARD_REVIEW"
        assert admission["generation_consumption_allowed"] is False
        assert admission["source_use_admitted"] is True
        assert admission["source_evidence"][0]["rights_id"]
        replay = corpus.client.post("/product/source-imports/corpus/analyze", json=request)
        assert replay.status_code == 202 and replay.json()["replayed"]
    with psycopg.connect(DATABASE_URL) as connection:
        assert connection.execute("SELECT count(*) FROM authority_external_effect WHERE project_id=%s AND capability LIKE 'mkaos.%%'", [corpus.project]).fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM authority_book WHERE project_id=%s", [corpus.project]).fetchone()[0] == 0
        sources = connection.execute("SELECT DISTINCT purpose FROM authority_corpus_source WHERE project_id=%s", [corpus.project]).fetchall()
        assert sources == [(purpose,)]


def _create_book(corpus, book_id, *, deny=False):
    from novel_forge.modules.authority_security import Principal, PrincipalType
    from novel_forge.modules.book_design_authority import BookDesignAuthorityApplication, BookDesignAuthorityCommand
    principal = Principal(principal_id="fixture-book-operator", principal_type=PrincipalType.LOCAL_OPERATOR,
                          permissions=frozenset({"book_design.authority.execute"}), project_scope=frozenset({corpus.project}),
                          authentication_source="integration-test")
    return BookDesignAuthorityApplication(DATABASE_URL, application_build_id="source-purpose-test", commit_sha="e" * 40).execute(
        BookDesignAuthorityCommand(definition_name="book.create", project_id=corpus.project, workspace_id=corpus.workspace,
            book_id=book_id, actor_id=principal.principal_id, service_identity="authority-api", idempotency_key=book_id,
            trace_id=book_id, correlation_id=book_id, payload={"schema_version": "book-authority.v1", "title": "Purpose fixture Book",
            "production_profile": {"knowledge_access_policy": {"mode": "DENY_ALL" if deny else "PROJECT_DEFAULT"}},
            "runtime_policy": {"silent_fallback": False}, "release_identity": "fixture@" + "e" * 40}), principal=principal)


@pytest.mark.parametrize("blocker", ["missing_use", "rights_changed", "book_deny_all"])
def test_native_intended_use_and_later_book_or_rights_changes_block_dispatch(corpus, tmp_path, monkeypatch, blocker):
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.source_authority.curation import require_curated_operation_current
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    from novel_forge.storage.source_authority_repositories import SourceAuthorityRepository
    _, scheduler, frozen = _selection(corpus, tmp_path, monkeypatch, "PRODUCTION_REFERENCE", generation_granted=blocker != "missing_use")
    book_id = "declared-book:" + corpus.project
    request = {"project_id": corpus.project, "revision_id": frozen["revision_id"], "run_key": "for-book",
               "max_members": 1, "max_calls": 4, "max_tokens": 10000, "authorization_ref": "fixture:no-live-authorization",
               "intended_use": "ABSTRACT_GENERATION", "target_book_id": book_id}
    result = corpus.client.post("/product/source-imports/corpus/analyze", json=request)
    if blocker == "missing_use":
        assert result.status_code == 409 and "CORPUS_USE_NOT_GRANTED" in result.text, result.text
        return
    assert result.status_code == 202, result.text
    operation = result.json()["operation_id"]
    expanded = scheduler.run_or_recover(operation_id=operation, project_id=corpus.project)
    member_operation = expanded["result"]["children"][0]["operation_id"]
    if blocker == "book_deny_all":
        assert _create_book(corpus, book_id, deny=True)["status"] == "SUCCEEDED"
        expected = "CORPUS_TARGET_BOOK_KNOWLEDGE_DENIED"
    else:
        evidence = result.json()["consumption_admission"]["source_evidence"][0]
        corpus.rights(evidence["source_id"], status="RESTRICTED", previous=evidence["rights_id"])
        expected = "CURATED_PROVIDER_INPUT_STALE"
    with pytest.raises(KernelError, match=expected), AuthorityUnitOfWork(DATABASE_URL) as uow:
        require_curated_operation_current(SourceAuthorityRepository(uow.cursor), corpus.project, member_operation)
    with pytest.raises(KernelError):
        scheduler.run_or_recover(operation_id=member_operation, project_id=corpus.project)
    with psycopg.connect(DATABASE_URL) as connection:
        assert connection.execute("SELECT count(*) FROM authority_external_effect WHERE project_id=%s AND provider='production_execution_gateway'", [corpus.project]).fetchone()[0] == 0
        payload = connection.execute("SELECT command_payload->'payload' FROM authority_operation WHERE operation_id=%s", [operation]).fetchone()[0]
        assert payload["consumption_admission"] == result.json()["consumption_admission"]


def test_existing_target_book_scope_is_checked_without_auto_approving_cards(corpus, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from novel_forge.modules.project_authority import ProjectAuthorityApplication, ProjectAuthorityCommand
    _, _, frozen = _selection(corpus, tmp_path, monkeypatch, "PRODUCTION_REFERENCE")
    book_id = "existing-book:" + corpus.project
    assert _create_book(corpus, book_id)["status"] == "SUCCEEDED"
    request = {"project_id": corpus.project, "revision_id": frozen["revision_id"], "run_key": "existing-book",
               "max_members": 1, "max_calls": 4, "max_tokens": 10000, "authorization_ref": "fixture:no-live-authorization",
               "intended_use": "ABSTRACT_GENERATION", "target_book_id": book_id}
    result = corpus.client.post("/product/source-imports/corpus/analyze", json=request)
    assert result.status_code == 202, result.text
    admission = result.json()["consumption_admission"]
    assert admission["book_status"] == "EXISTING_BOOK_SCOPE_VERIFIED"
    assert admission["book_policy_evidence"][0]["mode"] == "PROJECT_DEFAULT"
    assert admission["knowledge_status"] == "PENDING_CARD_REVIEW" and not admission["generation_consumption_allowed"]
    other = SimpleNamespace(project=corpus.project + "-other", workspace=corpus.workspace + "-other")
    ProjectAuthorityApplication(DATABASE_URL, application_build_id="scope-fixture", commit_sha="e" * 40).execute(
        ProjectAuthorityCommand(definition_name="project_lifecycle.create", project_id=other.project, workspace_id=other.workspace,
            actor_id="scope-fixture", idempotency_key=other.project, trace_id=other.project, correlation_id=other.project, payload={"title": "Other fixture"}))
    foreign_book = book_id + "-other"
    assert _create_book(other, foreign_book)["status"] == "SUCCEEDED"
    rejected = corpus.client.post("/product/source-imports/corpus/analyze", json={**request, "run_key": "foreign-book", "target_book_id": foreign_book})
    assert rejected.status_code == 409 and "CORPUS_TARGET_BOOK_SCOPE_INVALID" in rejected.text, rejected.text
