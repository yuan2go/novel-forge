from copy import deepcopy
from types import SimpleNamespace

import pytest

from novel_forge.modules.chapter_authority.working_revision import (
    CONTRACT, NODES, ROOT_VERSION, require_working_revision_frontier, working_revision_definition,
)
from novel_forge.modules.command_kernel.errors import KernelError


def test_selected_revision_role_keeps_physical_type_for_gateway_materialization():
    from novel_forge.modules.chapter_authority.contracts import ChapterHandlerRequest, ChapterInputAsset
    source_hash = 'sha256:' + 'a' * 64
    source = ChapterInputAsset('selected:v2', 'draft_version', source_hash, {'text': '选定修订稿'}, input_role='draft_chapter')
    revision = ChapterInputAsset('new:v3', 'draft_version', 'new-hash', {'text': '新候选'})
    request = ChapterHandlerRequest(operation_id='review', project_id='project', workspace_id='workspace',
        trace_id='trace', correlation_id='correlation', command={}, inputs=(source, revision))
    assert request.require_input('draft_chapter') is source
    assert request.require_input('draft_version') is revision
    assert request.require_input('draft_chapter').asset_type == 'draft_version'
    assert request.require_input('draft_chapter').content_hash == source_hash
    from novel_forge.modules.chapter_authority.execution_gateway import PostgresChapterExecutionContractBinder
    from novel_forge.modules.production_execution import ArtifactPointer
    binder = object.__new__(PostgresChapterExecutionContractBinder)
    document = SimpleNamespace(asset_type='draft_version', content_hash=source_hash,
        content=source.content, lifecycle='ACTIVE', eligibility='ELIGIBLE', governance='CLEAR')
    binder.query = SimpleNamespace(require=lambda **kwargs: document)
    pointer = ArtifactPointer(artifact_ref='asset-version:selected:v2', asset_version_id=source.asset_version_id,
        artifact_type=source.asset_type, content_hash=source.content_hash, schema_version='draft_version.v1',
        source_eligibility='PRODUCTION_ELIGIBLE')
    actual = binder._materialize_selected_inputs(project_id='project', artifacts=(pointer,))
    assert actual[0]['artifact_type'] == 'draft_version' and actual[0]['content'] == source.content
    from dataclasses import replace
    with pytest.raises(KernelError, match='CHAPTER_CAPABILITY_CONTEXT_INVALID'):
        binder._materialize_selected_inputs(project_id='project', artifacts=(replace(pointer, artifact_type='draft_chapter'),))


def test_selected_best_role_rereview_and_selection_use_this_round_review(monkeypatch):
    from novel_forge.modules.chapter_authority.contracts import ChapterHandlerRequest, ChapterInputAsset, ChapterNode
    from novel_forge.modules.chapter_authority.handlers import build_chapter_handler_registry
    from novel_forge.modules.chapter_authority.model_effects import ModelProviderResult
    from novel_forge.modules.chapter_authority import review_window
    from novel_forge.modules.review.domain import evaluate_review_result
    source = ChapterInputAsset('selected:best', 'best_draft_candidate', 'hash',
        {'chapter': 1, 'text': '她留下照看伤者。', 'selected_review': {'score': 99, 'target_asset_version_id': 'old:prose'}}, input_role='draft_chapter')
    review = evaluate_review_result(project_id='p', target_asset_version_id=source.asset_version_id,
        context_bundle_version_id='ctx', chapter=1, result={'diagnostic_contract_version': 'actionable-diagnostics.v1',
            'decision': 'PASSED', 'score': 60, 'issues': []}, provider_evidence={}, prose_text=source.content['text'])
    revised = ChapterInputAsset('new:revision', 'draft_version', 'hash', {'chapter': 1, 'text': '她留下照看伤者，先将药放到床边。'})
    inputs = (source, revised, ChapterInputAsset('review:fresh', 'review_report', 'hash', review),
        ChapterInputAsset('ctx', 'context_bundle', 'hash', {}))
    monkeypatch.setattr(review_window, 'prepare_review_window', lambda *args: None)
    class Provider:
        def invoke(self, request, *, stage, payload):
            assert payload['original_draft_asset_version_id'] == 'selected:best'
            assert payload['review'] == review
            return ModelProviderResult({'diagnostic_contract_version': 'actionable-diagnostics.v1',
                'decision': 'PASSED', 'score': 70, 'issues': [], 'resolution_checks': [], 'knowledge_checks': []},
                'fixture', 'fixture', 'fixture', 'fixture', 0, 0, '0', 'USD', False)
    registry = build_chapter_handler_registry(Provider())
    request = ChapterHandlerRequest('rereview', 'p', 'w', 'trace', 'root', {}, inputs)
    rereview = registry.require(ChapterNode.REREVIEW).execute(request)
    assert rereview.content['initial_review_version_id'] == 'review:fresh'
    selected = registry.require(ChapterNode.BEST_CANDIDATE).execute(
        ChapterHandlerRequest('best', 'p', 'w', 'trace', 'root', {},
            (*inputs, ChapterInputAsset('rereview:fresh', 're_review_report', 'hash', rereview.content))))
    assert selected.content['candidate_comparison']['previous']['asset_version_id'] == 'selected:best'
    assert selected.content['candidate_comparison']['previous']['review_asset_version_id'] == 'review:fresh'
    assert selected.content['candidate_comparison']['previous']['score'] == 60


def frontier(monkeypatch, *, cancelled=False, state="READY", workspace="workspace", selected="draft"):
    from novel_forge.modules.book_authority import manuscript
    book = {"book_run_id": "run", "project_id": "project", "workspace_id": workspace,
        "book_id": "book", "state": state, "current_chapter": 1, "accepted_through_chapter": 0}
    source = SimpleNamespace(asset_version_id=selected, content_hash="sha256:" + "a" * 64)
    monkeypatch.setattr(manuscript, "effective_workflow", lambda *args: manuscript.AUTHOR_WORKFLOW)
    monkeypatch.setattr(manuscript, "selected_source", lambda *args: source)
    inputs = {key: {"asset_version_id": key, "content_hash": source.content_hash} for key in ("draft", "context", "plan")}
    binding = {"contract_version": CONTRACT, "book_run_id": "run", "source_asset_version_id": "draft",
        "source_content_hash": source.content_hash, "source_inputs": inputs, "previous_sources": []}
    root = {"definition_name": "chapter.slice.run", "definition_version": ROOT_VERSION,
        "definition_snapshot": {"policy": {"working_revision_contract": CONTRACT}},
        "project_id": "project", "workspace_id": "workspace",
        "command_payload": {"chapter": 1, "book_id": "book", "preparation_report": {"working_revision": binding}},
        "input_asset_snapshot": list(inputs.values())}
    class Cursor:
        def execute(self, sql, params):
            assert params == ["run", "project"]
        def fetchone(self):
            return book, cancelled
    return SimpleNamespace(cursor=Cursor()), root, source


def test_revision_requires_current_same_book_source_without_granting_acceptance(monkeypatch):
    uow, root, source = frontier(monkeypatch)
    book, actual = require_working_revision_frontier(uow, root=root)
    assert actual is source and book["accepted_through_chapter"] == 0
    original = deepcopy(root)
    require_working_revision_frontier(uow, root=root)
    assert root == original


def test_completed_revision_cannot_activate_after_earlier_selection_changes(monkeypatch):
    from novel_forge.modules.book_authority import manuscript
    uow, root, source = frontier(monkeypatch)
    root["status"] = "SUCCEEDED"
    root["command_payload"]["preparation_report"]["working_revision"]["previous_sources"] = [
        {"chapter": 1, "asset_version_id": "previous-old", "content_hash": source.content_hash}]
    root["command_payload"]["chapter"] = 2
    book = uow.cursor.fetchone()[0]
    book["current_chapter"] = 2
    monkeypatch.setattr(manuscript, "selected_source", lambda uow, book, chapter:
        source if chapter == 2 else SimpleNamespace(asset_version_id="previous-new", content_hash=source.content_hash))
    with pytest.raises(KernelError, match="earlier prose changed"):
        require_working_revision_frontier(uow, root=root)


@pytest.mark.parametrize("kind,severity,status,blocked", [
    ("SEMANTIC_CONTRADICTION", "major", "OPEN", True),
    ("SEMANTIC_CONFLICT", "major", "OPEN", True),
    ("SEMANTIC_CONTRADICTION", "major", "RESOLVED", False),
    ("LIKELY_CONTINUITY_PROBLEM", "major", "OPEN", False),
    ("AESTHETIC_SUGGESTION", "major", "OPEN", False),
])
def test_only_unresolved_explicit_major_contradiction_blocks_propagation(kind, severity, status, blocked):
    from novel_forge.modules.book_authority.manuscript import require_prose_propagation
    from novel_forge.modules.review.diagnostics import prose_hash
    review = {"target_asset_version_id": "draft", "target_text_hash": prose_hash("真实正文"),
        "issues": [{"code": "problem", "judgment_kind": kind, "severity": severity, "status": status}]}
    class Cursor:
        def execute(self, sql, params):
            assert params == ["project", "draft"]
        def fetchall(self):
            return [("review", review)]
    source = SimpleNamespace(asset_version_id="draft", asset_type="draft_chapter", content={"text": "真实正文"})
    if blocked:
        with pytest.raises(KernelError, match="Retain this complete candidate"):
            require_prose_propagation(SimpleNamespace(cursor=Cursor()), {"project_id": "project"}, source)
    else:
        require_prose_propagation(SimpleNamespace(cursor=Cursor()), {"project_id": "project"}, source)
    assert source.content == {"text": "真实正文"}


@pytest.mark.parametrize("resolved", [False, True])
def test_later_review_omission_cannot_remove_an_earlier_major_contradiction(resolved):
    from novel_forge.modules.book_authority.manuscript import require_prose_propagation
    from novel_forge.modules.review.diagnostics import prose_hash
    base = {"target_asset_version_id": "draft", "target_text_hash": prose_hash("正文"), "issues": []}
    initial = {**base, "issues": [{"code": "major", "judgment_kind": "SEMANTIC_CONTRADICTION", "severity": "major"}]}
    later = {**base, "report_type": "ReReviewReport", "prior_review_evidence": {"asset_version_id": "initial"},
        "issue_lineage": [{"code": "major", "to_status": "RESOLVED", "verified_by_rereview": True}] if resolved else [],
        "resolution_checks": [{"code": "major", "status": "SATISFIED", "preservation": "PRESERVED"}] if resolved else []}
    class Cursor:
        def execute(self, *args):
            pass
        def fetchall(self):
            return [("initial", initial), ("later", later)]
    source = SimpleNamespace(asset_version_id="draft", asset_type="draft_chapter", content={"text": "正文"})
    if resolved:
        require_prose_propagation(SimpleNamespace(cursor=Cursor()), {"project_id": "project"}, source)
    else:
        with pytest.raises(KernelError, match="Retain this complete candidate"):
            require_prose_propagation(SimpleNamespace(cursor=Cursor()), {"project_id": "project"}, source)


def test_frozen_later_context_rechecks_new_major_finding_before_execution(monkeypatch):
    from novel_forge.modules.book_authority import manuscript
    book = {"project_id": "project", "book_id": "book", "book_run_id": "run"}
    source = SimpleNamespace(content_hash="hash", content={"text": "原稿"}, asset_type="draft_chapter")
    plain = {"version": "working-manuscript-context.v1", **book,
        "sources": [{"asset_version_id": "source", "content_hash": "hash", "text_hash": manuscript.text_hash("原稿")}]}
    snapshot = {**plain, "snapshot_hash": manuscript.canonical_hash(plain)}
    monkeypatch.setattr(manuscript, "freeze_working_context", lambda *args, **kwargs: snapshot)
    def major(*args):
        raise KernelError("MANUSCRIPT_MAJOR_CONTRADICTION_UNRESOLVED", "new concrete Review finding")
    monkeypatch.setattr(manuscript, "require_prose_propagation", major)
    uow = SimpleNamespace(repositories=SimpleNamespace(asset_documents=SimpleNamespace(require=lambda **kwargs: source)))
    manuscript.verify_working_context(uow, book, snapshot, require_current=False)
    snapshot["target_chapter"] = 2
    snapshot["snapshot_hash"] = manuscript.canonical_hash({key: value for key, value in snapshot.items() if key != "snapshot_hash"})
    with pytest.raises(KernelError, match="new concrete Review finding"):
        manuscript.verify_working_context(uow, book, snapshot)


def test_review_keeps_author_requirements_and_character_state_without_duplicate_generation_directives():
    from novel_forge.modules.chapter_authority.provider_views import build_provider_context_view
    context = {"context_segments": [{"asset_type": kind, "asset_version_id": kind, "safe_summary": text, "structured_facts": []}
        for kind, text in [("chapter_memo", "重复建议"), ("chapter_execution_intent", "重复指令"),
            ("chapter_plan", "作者明确要求"), ("character_cast", "人物已知处境")]]}
    task = {"creative_baseline": {"author_requirement": "必须保留"},
        "cross_chapter_window": {"source_isolation": "SELECTED_PROSE_NO_CANON_AUTHORITY"}}
    actual = build_provider_context_view("review", context, task)
    assert [row["safe_summary"] for row in actual["segments"]] == ["作者明确要求", "人物已知处境"]
    assert task["creative_baseline"]["author_requirement"] == "必须保留"


def test_whole_chapter_revision_prompt_has_one_body_and_keeps_selected_predecessor():
    from novel_forge.modules.chapter_authority.execution_gateway import _materialize_production_codex_prompt
    from tests.unit.test_capability_pack_artifact_materialization import _prompt_materialization
    materialization = _prompt_materialization({"context_segments": []})
    materialization["output_schema"]["ref"] = "schema:chapter-provider-output:revision:v7"
    source = {"chapter": 3, "title": "第三章", "text": "唯一完整原稿正文。",
        "realization_contract": {"contract_version": "scene-realization-composition.v3"},
        "scene_artifacts": [{"text": "唯一完整原稿正文。"}], "composition_digest": "source-composition"}
    window = {"source_window_hash": "source-window", "source_isolation": "SELECTED_PROSE_NO_CANON_AUTHORITY",
        "preservation_requirements": {}, "sources": [{"text": "前章选定稿的真实约定。"}]}
    prompt, _ = _materialize_production_codex_prompt(stage="revision", inputs={"draft": source,
        "review": {"issues": [], "cross_chapter_window": window}}, materialization=materialization,
        target_scope={"scope_kind": "chapter", "scope_id": "chapter-3", "chapter_number": 3})
    assert prompt.count("唯一完整原稿正文。") == 1
    assert prompt.count("前章选定稿的真实约定。") == 1
    assert "WHOLE_CHAPTER_TEXT_WITH_FROZEN_CORE_REQUIREMENTS" in prompt
    assert "Return ordered non-overlapping edits" not in prompt


@pytest.mark.parametrize("owned", [True, False])
def test_retained_working_revision_body_is_readable_without_new_call_qualification(monkeypatch, owned):
    from novel_forge.modules.book_authority import manuscript
    payload = {"operation_id": "revision", "project_id": "project", "book_id": "book", "text": "完整候选",
        "raw_text": "完整原始结果", "completeness": "COMPLETE", "structural_status": "INVALID_AUXILIARY",
        "review_status": "NOT_REVIEWED", "selection_status": "NOT_SELECTED", "acceptance_status": "NOT_ACCEPTED",
        "accounting_status": "UNKNOWN"}
    source = SimpleNamespace(asset_type="execution_evidence", asset_version_id="raw", content_hash="hash",
        content={"kind": "prose-candidate", "payload": payload, "payload_hash": manuscript.canonical_hash(payload).split(":", 1)[1]})
    class Uow:
        def __init__(self, *args):
            self.cursor = self
            self.rows = iter([None, ("book", "workspace", 3) if owned else None])
            self.repositories = SimpleNamespace(asset_documents=SimpleNamespace(require=lambda **kwargs: source))
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def execute(self, sql, params):
            assert "authority_operation_output_asset" in sql and "runtime" not in sql.lower()
        def fetchone(self):
            return next(self.rows)
    monkeypatch.setattr(manuscript, "AuthorityUnitOfWork", Uow)
    principal = SimpleNamespace(require=lambda permission, project: None)
    if owned:
        actual = manuscript.require_retained_model_candidate("test", project_id="project", book_run_id="run",
            asset_version_id="raw", principal=principal)
        assert actual["text"] == "完整候选" and actual["accounting_status"] == "UNKNOWN"
        assert actual["structural_status"] == "INVALID_AUXILIARY" and actual["publication"] == "NOT_AUTHORIZED"
    else:
        with pytest.raises(KernelError, match="another source or Book"):
            manuscript.require_retained_model_candidate("test", project_id="project", book_run_id="run",
                asset_version_id="raw", principal=principal)


def test_unsupported_regex_wire_projection_keeps_full_host_validation():
    from novel_forge.modules.chapter_authority.provider_output_contracts import _validate
    from novel_forge.modules.production_execution.codex_configuration import codex_output_schema
    canonical = {"type": "object", "properties": {"category": {"type": "string", "pattern": "^(?!(?:CAUSAL_CARRYOVER)$).+"},
        "reference": {"type": "string", "pattern": "^[a-z]+$"}}, "required": ["category", "reference"], "additionalProperties": False}
    before = deepcopy(canonical)
    wire = codex_output_schema(canonical)
    assert "pattern" not in wire["properties"]["category"]
    assert wire["properties"]["reference"]["pattern"] == "^[a-z]+$"
    invalid = {"category": "CAUSAL_CARRYOVER", "reference": "source"}
    _validate(wire, invalid, path="wire")
    with pytest.raises(ValueError, match="permitted pattern"):
        _validate(canonical, invalid, path="canonical")
    assert canonical == before


@pytest.mark.parametrize("fault", [None, "unchanged-wire", "different-input", "external-write", "missing-receipt"])
def test_schema_transport_recovery_requires_changed_wire_and_same_pure_task(fault):
    from novel_forge.modules.chapter_authority.context_transport_recovery import require_changed_schema_transport
    from novel_forge.modules.production_execution.codex_configuration import CODEX_SCHEMA_PROJECTION_VERSION
    source = {"operation_id": "source", "project_id": "project", "workspace_id": "workspace",
        "definition_version": "3.10.0", "command_payload": {"book_id": "book"},
        "input_asset_snapshot": [{"asset_version_id": "draft", "content_hash": "hash"}],
        "definition_snapshot": {"external_capabilities": ["model.review"]}}
    policy = {"contract_version": "chapter-provider-schema-transport.v1", "transport_projection": "codex-supported-patterns.v1",
        "release_sha": "release", "source_schema_projection": "codex-structured-schema.v6",
        "target_schema_projection": CODEX_SCHEMA_PROJECTION_VERSION, "input_snapshot": deepcopy(source["input_asset_snapshot"]),
        "domain_schema": "UNCHANGED", "target_deployment_id": "deployment", "schema_rejection_receipts": [{"receipt": "immutable"}]}
    if fault == "unchanged-wire":
        policy["source_schema_projection"] = CODEX_SCHEMA_PROJECTION_VERSION
    elif fault == "different-input":
        policy["input_snapshot"] = []
    elif fault == "external-write":
        source["definition_snapshot"]["external_capabilities"].append("external.publish")
    elif fault == "missing-receipt":
        policy["schema_rejection_receipts"] = []
    class Cursor:
        def execute(self, *args):
            pass
        def fetchall(self):
            return [("codex-structured-schema.v6",)]
        def fetchone(self):
            return ("deployment",)
    if fault:
        with pytest.raises(KernelError, match="actual changed transport"):
            require_changed_schema_transport(Cursor(), source, policy, "3.10.0", execution_sha="release")
    else:
        assert require_changed_schema_transport(Cursor(), source, policy, "3.10.0", execution_sha="release")


@pytest.mark.parametrize("change", [{"cancelled": True}, {"state": "PAUSED"}, {"state": "ABORTED"},
    {"workspace": "foreign"}, {"selected": "newer-draft"}])
def test_revision_does_not_cross_cancellation_scope_or_newer_selection(monkeypatch, change):
    uow, root, _ = frontier(monkeypatch, **change)
    with pytest.raises(KernelError):
        require_working_revision_frontier(uow, root=root)


def test_working_revision_is_existing_review_revision_selection_without_foundation_or_canon():
    definition = working_revision_definition(application_build_id="test", commit_sha="a" * 40)
    assert definition["policy"]["expected_saga_steps"] == 4
    assert [row["definition_name"] for row in definition["completion_contract"]["required_child_operations"]] == [node.definition_name for node in NODES]
    schema = definition["command_schema"]["properties"]["preparation_report"]["properties"]["working_revision"]
    assert schema["properties"]["formal_acceptance"] == {"const": "NOT_GRANTED"}


def test_working_review_window_keeps_actual_unaccepted_cursor_and_exact_text_support():
    from tests.unit.test_cross_chapter_prose_review import source_snapshot, SOURCE, TARGET
    from novel_forge.modules.review.prose_window import WORKING_WINDOW_POLICY, WORKING_WINDOW_CONTRACT, digest, freeze_review_window, validate_support
    value = source_snapshot()
    value.update(contract_version="selected-working-prose-snapshot.v1", accepted_through_chapter=0,
        working_through_chapter=1, source_isolation="SELECTED_PROSE_NO_CANON_AUTHORITY")
    value["window_policy"]["version"] = WORKING_WINDOW_POLICY
    source = value["sources"][0]
    source.pop("acceptance_operation_id")
    source.pop("acceptance_status")
    source["source_status"] = "SELECTED_WORKING_PROSE"
    value["snapshot_hash"] = digest({key: content for key, content in value.items() if key != "snapshot_hash"})
    window = freeze_review_window(value, candidate_id="current", text=TARGET,
        context_token_budget=16000, protected_context={})
    assert window["contract_version"] == WORKING_WINDOW_CONTRACT
    assert window["accepted_through_chapter"] == 0 and window["working_through_chapter"] == 1
    support = {"asset_version_id": source["asset_version_id"], "text_hash": source["text_hash"],
        "chapter_number": 1, "relation_to_issue": "Previous injury and spent resource constrain the current action",
        "start": 0, "end": len(SOURCE), "quote": SOURCE}
    assert validate_support([support], window)[0]["quote"] == SOURCE
    with pytest.raises(KernelError):
        validate_support([{**support, "quote": "forged earlier prose"}], window)
