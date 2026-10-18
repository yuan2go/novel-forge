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


@pytest.mark.parametrize('stage', ['review', 'revision', 'rereview'])
def test_revision_purpose_reaches_rendered_model_task(monkeypatch, stage):
    from novel_forge.modules.chapter_authority.contracts import ChapterHandlerRequest, ChapterInputAsset
    from novel_forge.modules.chapter_authority import review_window
    from novel_forge.modules.chapter_authority.provider_views import build_provider_task_view
    purpose = {'contract_version': CONTRACT, 'source_asset_version_id': 'selected:v2', 'reason': '合并重复课堂观察，保留学习边界。'}
    request = ChapterHandlerRequest('review', 'p', 'w', 'trace', 'root',
        {'preparation_report': {'working_revision': purpose}},
        (ChapterInputAsset('selected:v2', 'draft_version', 'hash', {'chapter': 3, 'text': '原生正文'}, input_role='draft_chapter'),
         ChapterInputAsset('ctx', 'context_bundle', 'hash', {}),
         ChapterInputAsset('revised', 'draft_version', 'hash', {'chapter': 3, 'text': '修订正文'}),
         ChapterInputAsset('report', 'review_report', 'hash', {'issues': [], 'working_revision_request': purpose})))
    monkeypatch.setattr(review_window, 'prepare_review_window', lambda *args: None)
    *_, payload = review_window.prepare_native_review(request, stage='rereview' if stage == 'rereview' else 'review')
    assert payload['working_revision_request']['reason'] == purpose['reason']
    if stage == 'revision':
        payload['review'] = {'issues': [], 'working_revision_request': payload['working_revision_request']}
    task = build_provider_task_view(stage, payload)
    assert task['working_revision_request']['reason'] == purpose['reason']
    assert task['working_revision_request']['core_story_change_authorized'] is False


@pytest.mark.parametrize('purpose', ['absent', 'stale', 'current'])
def test_requested_structural_aesthetic_repair_uses_matching_scope_and_body_contract(purpose):
    from novel_forge.modules.review.diagnostics import structural_repair_scope, validate_prose_repair_scope
    from novel_forge.modules.chapter_authority.execution_gateway import PostgresChapterExecutionContractBinder
    source = {'chapter': 1, 'title': '门前', 'text': '他绕了两次院子。\n\n他又绕了一次院子。\n\n守门人拦住了他。'}
    issue = {'code': 'repeat', 'status': 'OPEN', 'severity': 'minor', 'judgment_kind': 'AESTHETIC_SUGGESTION',
        'evidence_locator': {'start': 0, 'end': 8, 'quote': source['text'][:8]},
        'repair': {'root_cause': 'CHAPTER_STRUCTURE', 'problem_owner': 'PROSE', 'repair_scope': 'CHAPTER_REVISION',
            'revision_goal': '合并重复观察并改善过渡', 'preserve': ['守门人阻拦'], 'resolution_criteria': ['动作不再重复']}}
    review = {'issues': [issue], 'target_asset_version_id': 'draft', 'cross_chapter_window': {'source_window_hash': 'window'}}
    if purpose != 'absent':
        review['working_revision_request'] = {'contract_version': CONTRACT, 'aesthetic_revision_requested': True,
            'source_asset_version_id': 'draft' if purpose == 'current' else 'older-draft'}
    assert structural_repair_scope([issue], review=review) == ('CHAPTER_REVISION' if purpose == 'current' else 'LOCAL_PROSE')
    schema, ref = PostgresChapterExecutionContractBinder._provider_output_contract(stage='revision',
        request_payload={'input': {'draft': source, 'review': review}}, prompt_contract_version='v15')
    assert (ref == 'schema:chapter-provider-output:revision:v7') is (purpose == 'current')
    revised = '他绕过院墙，脚步刚停，守门人便横臂拦住了他。'
    if purpose == 'current':
        assert set(schema['properties']) == {'text', 'resolved_issue_codes'}
        validate_prose_repair_scope(source, [issue], revised, review=review)
    else:
        with pytest.raises(KernelError, match='REVISION_OUTSIDE_DIAGNOSIS_SCOPE'):
            validate_prose_repair_scope(source, [issue], revised, review=review)
    review['unresolved_issues'] = [issue]
    review['issues'] = [{**issue, 'repair': {**issue['repair'], 'repair_scope': 'LOCAL_PROSE'}}]
    _, updated_ref = PostgresChapterExecutionContractBinder._provider_output_contract(stage='revision',
        request_payload={'input': {'draft': source, 'review': review}}, prompt_contract_version='v15')
    assert updated_ref != 'schema:chapter-provider-output:revision:v7'


@pytest.mark.parametrize('edited', [False, True])
@pytest.mark.parametrize('mapping', ['missing', 'crossed-slot'])
def test_unmapped_prose_local_edits_retain_complete_body_without_inventing_slots(edited, mapping):
    from novel_forge.modules.revision.domain import apply_revision_result
    from novel_forge.modules.review.diagnostics import prose_hash
    source = {'chapter': 1, 'title': '合成测试', 'text': '她握住药碗。窗外灯火还亮着。', 'realization_mapping_status': 'NOT_MAPPED', 'scene_artifacts': []}
    if mapping == 'crossed-slot':
        source.update(realization_contract={'contract_version': 'scene-realization-composition.v3'},
            scene_artifacts=[{'text': source['text'][:4]}, {'text': source['text'][4:]}], scene_separators=[''])
    review = {'diagnostic_contract_version': 'actionable-diagnostics.v1', 'target_asset_version_id': 'draft',
        'context_bundle_version_id': 'ctx', 'target_text_hash': prose_hash(source['text']),
        'cross_chapter_window': {'source_window_hash': 'window', 'preservation_requirements': []},
        'issues': [{'code': 'WORD', 'status': 'OPEN', 'severity': 'minor', 'evidence_locator': {'start': 3, 'end': 5, 'quote': '药碗'}}] if edited else []}
    result = {'edits': [{'start': 3, 'end': 5, 'quote': '药碗', 'replacement': '瓷碗', 'issue_codes': ['WORD']}] if edited else [],
        'resolved_issue_codes': ['WORD'] if edited else []}
    value = apply_revision_result(project_id='p', draft=source, review=review, draft_asset_version_id='draft',
        review_asset_version_id='review', context_bundle_version_id='ctx', result=result, provider_evidence={})
    assert value['text'] == (source['text'].replace('药碗', '瓷碗') if edited else source['text'])
    assert value['realization_mapping_status'] == 'NOT_MAPPED'
    assert value['scene_artifacts'] == []
    assert value['text'].endswith('窗外灯火还亮着。')
    if edited:
        result['edits'][0]['quote'] = '假造引用'
        with pytest.raises(KernelError, match='REVIEW_EVIDENCE_INVALID'):
            apply_revision_result(project_id='p', draft=source, review=review, draft_asset_version_id='draft',
                review_asset_version_id='review', context_bundle_version_id='ctx', result=result, provider_evidence={})


def _working_scope_proposal_case():
    from novel_forge.modules.review.diagnostics import prose_hash
    from tests.unit.test_work_intent_consistency import work_input
    _, _, source = work_input("保留人物声音")
    source.update(text="老师让他放松肩膀。\n\n他又问了一遍如何练习。\n\n母亲忙着收好摊子的账。",
        realization_mapping_status="NOT_MAPPED", scene_artifacts=[])
    quote = "老师让他放松肩膀。"
    review = {"issues": [{"code": "repeat", "severity": "minor", "judgment_kind": "AESTHETIC_SUGGESTION",
        "evidence_locator": {"start": 0, "end": len(quote), "quote": quote}}],
        "creative_baseline_digest": source["creative_baseline"]["baseline_digest"],
        "diagnostic_contract_version": "actionable-diagnostics.v1", "target_asset_version_id": "draft",
        "target_text_hash": prose_hash(source["text"]), "context_bundle_version_id": "ctx",
        "cross_chapter_window": {"source_window_hash": "window", "preservation_requirements": {}},
        "working_revision_request": {"contract_version": CONTRACT, "source_asset_version_id": "draft",
            "aesthetic_revision_requested": True, "reason": "合并重复教学，保护家庭段。"}}
    result = {"edits": [{"quote": source["text"].split("\n\n母亲")[0], "replacement": "他放松肩膀，向老师问清下一回的练习。",
        "issue_codes": ["repeat"]}], "resolved_issue_codes": ["repeat"]}
    return source, review, result


def test_scope_proposal_keeps_unrepairable_open_ledger_out_of_the_temporary_edit_view():
    from novel_forge.modules.revision.domain import apply_revision_result
    source, review, result = _working_scope_proposal_case()
    review["unresolved_issues"] = [{"code": "timeline", "severity": "minor", "judgment_kind": "UNCERTAIN"}]
    review["remaining_issue_codes"] = ["timeline"]
    value = apply_revision_result(project_id="p", draft=source, review=review, draft_asset_version_id="draft",
        review_asset_version_id="review", context_bundle_version_id="ctx", result=result, provider_evidence={})
    assert next(item for item in value["issue_resolutions"] if item["code"] == "timeline")["to_status"] == "OPEN"
    assert review["remaining_issue_codes"] == ["timeline"]


def test_working_scope_expansion_materializes_complete_proposal_and_preserves_other_paragraphs():
    from novel_forge.modules.revision.domain import apply_revision_result
    from novel_forge.modules.chapter_authority.provider_views import build_provider_task_view
    source, review, result = _working_scope_proposal_case()
    value = apply_revision_result(project_id="p", draft=source, review=review, draft_asset_version_id="draft",
        review_asset_version_id="review", context_bundle_version_id="ctx", result=result, provider_evidence={})
    assert value["text"] == result["edits"][0]["replacement"] + "\n\n母亲忙着收好摊子的账。"
    assert value["repair_scope"] == "PROPOSED_EXPANSION"
    assert value["prose_scope_proposal"]["qualification_status"] == "PROPOSAL_ONLY"
    assert value["prose_scope_proposal"]["issue_codes"] == ["repeat"]
    assert value["prose_scope_proposal"]["source_asset_version_id"] == "draft"
    task = build_provider_task_view("revision", {"draft": source, "review": review}, work_requirements=True)
    assert task["targeted_repair"]["scope_policy"] == "ANCHORED_SCOPE_PROPOSAL_V1"


@pytest.mark.parametrize("invalid", ["stale-request", "no-request", "wrong-anchor", "plan-investigation"])
def test_scope_proposal_never_grants_unrelated_or_plan_owned_edit_permission(invalid):
    from novel_forge.modules.revision.domain import apply_revision_result
    source, review, result = _working_scope_proposal_case()
    if invalid == "stale-request":
        review["working_revision_request"]["source_asset_version_id"] = "old"
    elif invalid == "no-request":
        review.pop("working_revision_request")
    elif invalid == "wrong-anchor":
        result["edits"][0]["quote"] = "母亲忙着收好摊子的账。"
    else:
        review["issues"][0]["repair"] = {"root_cause": "UNCERTAIN", "problem_owner": "PLAN", "repair_scope": "INVESTIGATE"}
    with pytest.raises(KernelError):
        apply_revision_result(project_id="p", draft=source, review=review, draft_asset_version_id="draft",
            review_asset_version_id="review", context_bundle_version_id="ctx", result=result, provider_evidence={})


@pytest.mark.parametrize("evidence", ["missing", "wrong-text", "uncertain", "regression", "partial-preserved"])
def test_scope_proposal_stays_readable_but_needs_exact_rereview_before_downstream_use(evidence):
    from novel_forge.modules.book_authority.manuscript import _require_scope_proposal_review
    from novel_forge.modules.review.diagnostics import prose_hash
    from novel_forge.modules.review.prose_window import PRESERVATION_DIMENSIONS
    text = "他问清了下一次怎么练。"
    source = SimpleNamespace(asset_type="draft_version", asset_version_id="revision", content={"text": text,
        "prose_scope_proposal": {"contract_version": "working-prose-scope-proposal.v1", "target_text_hash": prose_hash(text),
            "issue_codes": ["repeat"], "changed_target_ranges": [{"start": 0, "end": len(text)}]}})
    review = {"report_type": "ReReviewReport", "revision_version_id": "revision", "target_text_hash": prose_hash(text),
        "preservation_checks": [{"dimension": dimension, "status": "PRESERVED", "evidence": {"quote": text},
            "reason": "比对前后正文。"} for dimension in PRESERVATION_DIMENSIONS],
        "decision": "NEEDS_REVISION", "resolution_checks": [{"code": "repeat", "status": "PARTIALLY_RESOLVED",
            "preservation": "PRESERVED", "reason": "局部进展有效，其他问题仍保留。", "evidence": {"quote": text}}]}
    if evidence == "wrong-text":
        review["target_text_hash"] = "old"
    elif evidence == "uncertain":
        review["resolution_checks"][0]["preservation"] = "UNCERTAIN"
    elif evidence == "regression":
        review["preservation_checks"][0]["status"] = "REGRESSED"
    class Cursor:
        def execute(self, sql, params):
            assert "reviewer.root_operation_id=producer.root_operation_id" in sql
            assert "reviewed.output_key='chapter.rereview'" in sql and params[0] == "revision"
        def fetchall(self):
            return [] if evidence == "missing" else [(review,)]
    if evidence == "partial-preserved":
        _require_scope_proposal_review(SimpleNamespace(cursor=Cursor()), {"project_id": "p", "workspace_id": "w"}, source)
    else:
        with pytest.raises(KernelError, match="MANUSCRIPT_SCOPE_PROPOSAL_PENDING_REVIEW"):
            _require_scope_proposal_review(SimpleNamespace(cursor=Cursor()), {"project_id": "p", "workspace_id": "w"}, source)
    assert source.content["text"] == text


def test_quality_edit_crossing_slot_retains_body_and_previous_mapping_only():
    from novel_forge.modules.revision.domain import apply_quality_revision_result
    from novel_forge.modules.review.diagnostics import prose_hash
    text = '她握住药碗。窗外灯火还亮着。'
    source = {'chapter': 1, 'title': '药碗', 'text': text, 'composition_digest': 'old-mapping',
        'realization_contract': {'contract_version': 'scene-realization-composition.v3'},
        'scene_artifacts': [{'text': text[:4]}, {'text': text[4:]}], 'scene_separators': ['']}
    task = {'project_id': 'p', 'observation': 'voice', 'issue': {'code': 'WORD'}, 'status': 'OPEN',
        'target_revision_asset_version_id': 'draft', 'bounded_edit_scope': {
            'contract_version': 'quality-located-edit-scope.v1', 'status': 'LOCATED', 'target_asset_version_id': 'draft',
            'text_hash': prose_hash(text), 'permitted_ranges': [{'start': 3, 'end': 5, 'quote': '药碗'}]}}
    revised = apply_quality_revision_result(project_id='p', revision=source, revision_asset_version_id='draft',
        quality={'project_id': 'p', 'required_actions': [task]}, quality_asset_version_id='quality', revision_tasks=(task,),
        revision_task_asset_version_ids=('task',), context_bundle_version_id='ctx', provider_evidence={},
        result={'edits': [{'start': 3, 'end': 5, 'quote': '药碗', 'replacement': '瓷碗', 'issue_codes': ['WORD:task:1:range:1']}]})
    assert revised['text'] == text.replace('药碗', '瓷碗')
    assert revised['realization_mapping_status'] == 'NOT_MAPPED' and revised['scene_artifacts'] == []
    assert revised['previous_composition_digest'] == 'old-mapping'
    assert not any(key in revised for key in ('realization_contract', 'composition_digest', 'scene_separators'))
    assert source['composition_digest'] == 'old-mapping'


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
        "resolved_issue_codes": ["major"] if resolved else [],
        "resolution_checks": [{"code": "major", "status": "SATISFIED", "preservation": "PRESERVED",
            "evidence": {"quote": "正文"}}] if resolved else []}
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
            self.rows = iter([None, ("book", "workspace", 3) if owned else None, ("FAILED_FINAL",)])
            self.repositories = SimpleNamespace(asset_documents=SimpleNamespace(require=lambda **kwargs: source))
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def execute(self, sql, params):
            assert any(table in sql for table in ("authority_operation_output_asset", "authority_operation", "authority_attempt")) and "runtime" not in sql.lower()
        def fetchone(self):
            return next(self.rows)
        def fetchall(self):
            return [("MODEL_EFFECT_FINAL_UNAUTHORIZED_TOOL_INVOCATION",)]
    monkeypatch.setattr(manuscript, "AuthorityUnitOfWork", Uow)
    principal = SimpleNamespace(require=lambda permission, project: None)
    if owned:
        actual = manuscript.require_retained_model_candidate("test", project_id="project", book_run_id="run",
            asset_version_id="raw", principal=principal)
        assert actual["source_operation_status"] == "FAILED_FINAL" and actual["source_effect_status"] == "UNKNOWN"
        assert actual["text"] == "完整候选" and actual["accounting_status"] == "UNKNOWN"
        assert actual["structural_status"] == "INVALID_AUXILIARY" and actual["publication"] == "NOT_AUTHORIZED"
    else:
        with pytest.raises(KernelError, match="another source or Book"):
            manuscript.require_retained_model_candidate("test", project_id="project", book_run_id="run",
                asset_version_id="raw", principal=principal)


@pytest.mark.parametrize("owned", [True, False])
@pytest.mark.parametrize("kind,identity,integrity", [
    ("draft_version", {"project_id": "project"}, True),
    ("draft_chapter", {}, True),
    ("best_draft_candidate", {}, True),
    ("draft_chapter", {"project_id": "other"}, True),
    ("draft_chapter", {"project_id": "project", "book_id": "other"}, True),
    ("draft_chapter", {"project_id": "project", "workspace_id": "other"}, True),
    ("draft_chapter", {"chapter": 4}, True),
    ("draft_chapter", {"project_id": "project"}, False),
])
def test_unselected_materialized_revision_is_readable_without_projecting_review_or_selection(monkeypatch, owned, kind, identity, integrity):
    from novel_forge.modules.book_authority import manuscript

    content = {"chapter": 3, "text": "完整物化修订正文。", **identity}
    source = SimpleNamespace(asset_type=kind, asset_version_id="typed", content_hash=manuscript.canonical_hash(content) if integrity else "sha256:" + "0" * 64,
        content=content)
    definition = {"draft_version": "chapter.revision.apply", "draft_chapter": "chapter.draft.generate",
        "best_draft_candidate": "chapter.candidate.select_best"}[kind]
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
            assert "authority_operation_output_asset" in sql and "output.role='primary'" in sql
            assert "op.definition_name=%s" in sql and definition in params
            assert "UPDATE" not in sql and "INSERT" not in sql
        def fetchone(self):
            return next(self.rows)
    monkeypatch.setattr(manuscript, "AuthorityUnitOfWork", Uow)
    principal = SimpleNamespace(require=lambda permission, project: None)
    conflicting = any(key in identity and identity[key] != expected for key, expected in
        (("project_id", "project"), ("book_id", "book"), ("workspace_id", "workspace"), ("chapter", 3)))
    if owned and not conflicting and integrity:
        actual = manuscript.require_retained_model_candidate("test", project_id="project", book_run_id="run",
            asset_version_id="typed", principal=principal)
        assert actual["text"] == source.content["text"] and actual["raw_text"] is None
        assert actual["completeness"] == "COMPLETE"
        assert {actual[key] for key in ("review_status", "selection_status", "acceptance_status")} == {"NOT_PROJECTED"}
        assert actual["publication"] == "NOT_AUTHORIZED"
    elif owned and not conflicting and not integrity:
        with pytest.raises(KernelError, match="MANUSCRIPT_CANDIDATE_HASH_INVALID"):
            manuscript.require_retained_model_candidate("test", project_id="project", book_run_id="run",
                asset_version_id="typed", principal=principal)
    else:
        with pytest.raises(KernelError, match="another source or Book"):
            manuscript.require_retained_model_candidate("test", project_id="project", book_run_id="run",
                asset_version_id="typed", principal=principal)


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


@pytest.mark.parametrize("fault", [None, "absent-review", "wrong-prior", "wrong-target", "partial", "unlocated", "regression", "still-open"])
@pytest.mark.parametrize("best", [False, True])
def test_partial_revision_inherits_major_problem_until_exact_rereview(monkeypatch, fault, best):
    from novel_forge.modules.book_authority.manuscript import require_prose_propagation
    from novel_forge.modules.chapter_authority import author_editor
    from novel_forge.modules.review.diagnostics import prose_hash
    old = SimpleNamespace(asset_type="draft_chapter", asset_version_id="old", content={"chapter": 1, "text": "旧矛盾"})
    revised = SimpleNamespace(asset_type="best_draft_candidate" if best else "draft_version",
        asset_version_id="best" if best else "new", content={"chapter": 1, "text": "已修订正文", "source_draft_version_id": "old",
        "review_version_id": "initial", "issue_resolutions": [{"code": "major", "to_status": "RESOLUTION_CLAIMED"}],
        **({"selected_source_asset_version_id": "new"} if best else {})})
    initial = {"target_asset_version_id": "old", "target_text_hash": prose_hash("旧矛盾"), "issues": [
        {"code": "major", "severity": "major", "judgment_kind": "SEMANTIC_CONTRADICTION"}]}
    review = {"report_type": "ReReviewReport", "revision_version_id": "other" if fault == "wrong-target" else "new",
        "target_text_hash": prose_hash("已修订正文"), "initial_review_version_id": "other" if fault == "wrong-prior" else "initial",
        "issues": [{"code": "major", "severity": "major"}] if fault == "still-open" else [],
        "remaining_issue_codes": [], "resolved_issue_codes": ["major"],
        "preservation_checks": [{"status": "REGRESSED" if fault == "regression" else "PRESERVED"}],
        "issue_lineage": [{"code": "major", "to_status": "PARTIALLY_RESOLVED" if fault == "partial" else "RESOLVED", "verified_by_rereview": True}],
        "resolution_checks": [{"code": "major", "status": "SATISFIED", "preservation": "PRESERVED",
            "evidence": {"quote": "无此句" if fault == "unlocated" else "已修订正文"}}]}
    class Cursor:
        def execute(self, sql, params):
            self.source = params[1]
        def fetchall(self):
            return [("initial", initial)] if self.source == "old" else [] if fault == "absent-review" else [("rereview", review)]
    def exact_source(uow, scope, version_id):
        assert scope == {"project_id": "project", "workspace_id": "workspace", "book_id": "book", "chapter": 1} and version_id == "old"
        return old
    monkeypatch.setattr(author_editor, "require_source", exact_source)
    uow = SimpleNamespace(cursor=Cursor())
    book = {"project_id": "project", "workspace_id": "workspace", "book_id": "book"}
    if fault is None:
        require_prose_propagation(uow, book, revised)
    else:
        with pytest.raises(KernelError, match="MANUSCRIPT_MAJOR_CONTRADICTION_UNRESOLVED"):
            require_prose_propagation(uow, book, revised)
    assert revised.content["issue_resolutions"][0]["to_status"] == "RESOLUTION_CLAIMED"


def test_verified_later_repair_clears_carried_major_without_erasing_history(monkeypatch):
    from novel_forge.modules.book_authority.manuscript import require_prose_propagation
    from novel_forge.modules.chapter_authority import author_editor
    from novel_forge.modules.review.diagnostics import prose_hash
    issue = {"code": "major", "severity": "major", "judgment_kind": "SEMANTIC_CONTRADICTION"}
    old = SimpleNamespace(asset_type="draft_chapter", asset_version_id="old", content={"chapter": 1, "text": "矛盾"})
    partial = SimpleNamespace(asset_type="draft_version", asset_version_id="partial",
        content={"chapter": 1, "text": "部分修订", "source_draft_version_id": "old"})
    fixed = SimpleNamespace(asset_type="draft_version", asset_version_id="fixed",
        content={"chapter": 1, "text": "最终修复", "source_draft_version_id": "partial"})
    reports = {"old": [("initial", {"target_asset_version_id": "old", "target_text_hash": prose_hash("矛盾"), "issues": [issue]})],
        "partial": [("carried", {"report_type": "ReReviewReport", "initial_review_version_id": "initial",
            "revision_version_id": "partial", "target_text_hash": prose_hash("部分修订"), "issues": [issue]})],
        "fixed": [("closed", {"report_type": "ReReviewReport", "initial_review_version_id": "carried",
            "revision_version_id": "fixed", "target_text_hash": prose_hash("最终修复"), "issues": [],
            "resolved_issue_codes": ["major"], "remaining_issue_codes": [],
            "issue_lineage": [{"code": "major", "to_status": "RESOLVED", "verified_by_rereview": True}],
            "resolution_checks": [{"code": "major", "status": "SATISFIED", "preservation": "PRESERVED", "evidence": {"quote": "最终修复"}}]})]}
    class Cursor:
        def execute(self, sql, params):
            self.source = params[1]
        def fetchall(self):
            return reports[self.source]
    monkeypatch.setattr(author_editor, "require_source", lambda uow, scope, version: {"old": old, "partial": partial}[version])
    book = {"project_id": "project", "workspace_id": "workspace", "book_id": "book"}
    with pytest.raises(KernelError, match="MANUSCRIPT_MAJOR_CONTRADICTION_UNRESOLVED"):
        require_prose_propagation(SimpleNamespace(cursor=Cursor()), book, partial)
    require_prose_propagation(SimpleNamespace(cursor=Cursor()), book, fixed)
    assert reports["old"][0][1]["issues"][0] == issue


@pytest.mark.parametrize("different_problem", [False, "quote", "goal", "support"])
def test_independent_reviews_close_only_the_same_located_source_problem(monkeypatch, different_problem):
    from novel_forge.modules.book_authority.manuscript import require_prose_propagation
    from novel_forge.modules.chapter_authority import author_editor
    from novel_forge.modules.review.diagnostics import prose_hash
    old = SimpleNamespace(asset_type="draft_chapter", asset_version_id="old", content={"chapter": 1, "text": "原矛盾。另一矛盾。"})
    new = SimpleNamespace(asset_type="draft_version", asset_version_id="new",
        content={"chapter": 1, "text": "修复后正文", "source_draft_version_id": "old"})
    issue = {"code": "D", "severity": "major", "category": "CHARACTER_KNOWLEDGE", "judgment_kind": "SEMANTIC_CONTRADICTION",
        "violated_constraint": "knowledge_before_action", "revision_goal": "解释原知识来源",
        "acceptance_criteria": ["亲历先于对应知识"], "evidence_locator": {"quote": "原矛盾"}}
    first = {"target_asset_version_id": "old", "target_text_hash": prose_hash(old.content["text"]),
        "issues": [{**issue, "evidence_locator": {"quote": "另一矛盾"}} if different_problem == "quote" else
            {**issue, "revision_goal": "解释另一种知识来源"} if different_problem == "goal" else
            {**issue, "supporting_evidence": [{"asset_version_id": "different-prior-source", "quote": "另一种知识"}]} if different_problem == "support" else issue]}
    second = {**first, "issues": [issue]}
    closed = {"report_type": "ReReviewReport", "revision_version_id": "new", "target_text_hash": prose_hash(new.content["text"]),
        "initial_review_version_id": "R2", "issues": [], "remaining_issue_codes": [], "resolved_issue_codes": ["D"],
        "issue_lineage": [{"code": "D", "to_status": "RESOLVED", "verified_by_rereview": True}],
        "resolution_checks": [{"code": "D", "status": "SATISFIED", "preservation": "PRESERVED", "evidence": {"quote": "修复后正文"}}]}
    class Cursor:
        def execute(self, sql, params):
            self.source = params[1]
        def fetchall(self):
            return [("R1", first), ("R2", second)] if self.source == "old" else [("R3", closed)]
    monkeypatch.setattr(author_editor, "require_source", lambda *args: old)
    book = {"project_id": "project", "workspace_id": "workspace", "book_id": "book"}
    if different_problem:
        with pytest.raises(KernelError, match="MANUSCRIPT_MAJOR_CONTRADICTION_UNRESOLVED"):
            require_prose_propagation(SimpleNamespace(cursor=Cursor()), book, new)
    else:
        require_prose_propagation(SimpleNamespace(cursor=Cursor()), book, new)


def test_physical_working_candidate_review_is_not_hidden_by_prose_alias(monkeypatch):
    from novel_forge.modules.book_authority.manuscript import require_prose_propagation
    from novel_forge.modules.chapter_authority import author_editor
    from novel_forge.modules.review.diagnostics import prose_hash
    work = SimpleNamespace(asset_type="best_draft_candidate", asset_version_id="workspace",
        content={"chapter": 1, "text": "工作稿矛盾", "selected_source_asset_version_id": "underlying"})
    partial = SimpleNamespace(asset_type="draft_version", asset_version_id="partial",
        content={"chapter": 1, "text": "只修次要问题", "source_draft_version_id": "workspace"})
    report = {"target_asset_version_id": "workspace", "target_text_hash": prose_hash(work.content["text"]),
        "issues": [{"code": "major", "severity": "major", "judgment_kind": "SEMANTIC_CONTRADICTION"}]}
    class Cursor:
        def execute(self, sql, params):
            self.source = params[1]
        def fetchall(self):
            return [("new-working-review", report)] if self.source == "workspace" else []
    monkeypatch.setattr(author_editor, "require_source", lambda *args: work)
    with pytest.raises(KernelError, match="MANUSCRIPT_MAJOR_CONTRADICTION_UNRESOLVED"):
        require_prose_propagation(SimpleNamespace(cursor=Cursor()),
            {"project_id": "project", "workspace_id": "workspace", "book_id": "book"}, partial)


def _working_dependency_case():
    book = {"project_id": "project", "workspace_id": "workspace", "book_id": "book", "book_run_id": "run"}
    source = SimpleNamespace(asset_version_id="best:2", content_hash="best-hash", asset_type="best_draft_candidate",
        content={"chapter": 2, "text": "正文", "selected_source_asset_version_id": "revision:2"})
    selection = {**book, "chapter": 2, "selected_asset_version_id": source.asset_version_id,
        "selected_content_hash": source.content_hash, "source_asset_version_id": "old:2", "source_content_hash": "old-hash"}
    inputs = {key: {"asset_version_id": value, "content_hash": value + "-hash"}
        for key, value in (("draft", "old:2"), ("context", "context"), ("plan", "plan"))}
    inputs["draft"]["content_hash"] = "old-hash"
    previous = [{"chapter": 1, "asset_version_id": "new:1", "content_hash": "new:1-hash"}]
    root = {"operation_id": "root", "definition_name": "chapter.slice.run", "definition_version": ROOT_VERSION,
        "project_id": "project", "workspace_id": "workspace", "status": "SUCCEEDED",
        "definition_snapshot": {"policy": {"working_revision_contract": CONTRACT}},
        "command_payload": {"book_id": "book", "chapter": 2, "preparation_report": {"working_revision": {
            "contract_version": CONTRACT, "book_run_id": "run", "source_asset_version_id": "old:2",
            "source_content_hash": "old-hash", "source_inputs": inputs, "previous_sources": previous}}},
        "input_asset_snapshot": [*inputs.values(), {key: previous[0][key] for key in ("asset_version_id", "content_hash")}]}
    return book, source, selection, root


def test_selected_revision_dependency_binding_uses_its_frozen_source_after_selection():
    from novel_forge.modules.book_authority.manuscript import _working_dependency_binding
    book, source, selection, root = _working_dependency_case()
    assert _working_dependency_binding(book, selection, source, root) == {"sources": [
        {"chapter": 1, "asset_version_id": "new:1", "content_hash": "new:1-hash"}]}
    assert selection["source_asset_version_id"] != source.asset_version_id


@pytest.mark.parametrize("drift", ["book", "workspace", "chapter", "cancelled", "source_hash", "selection_hash", "missing_input", "missing_predecessor"])
def test_selected_revision_dependency_binding_rejects_scope_and_frozen_drift(drift):
    from novel_forge.modules.book_authority.manuscript import _working_dependency_binding
    book, source, selection, root = _working_dependency_case()
    binding = root["command_payload"]["preparation_report"]["working_revision"]
    if drift == "book":
        binding["book_run_id"] = "another"
    elif drift == "workspace":
        root["workspace_id"] = "another"
    elif drift == "chapter":
        root["command_payload"]["chapter"] = 3
    elif drift == "cancelled":
        root["status"] = "CANCELLED"
    elif drift == "source_hash":
        binding["source_content_hash"] = "another"
    elif drift == "selection_hash":
        selection["selected_content_hash"] = "another"
    elif drift == "missing_input":
        root["input_asset_snapshot"].pop()
    elif drift == "missing_predecessor":
        binding["previous_sources"] = []
    with pytest.raises(KernelError, match="MANUSCRIPT_WORK_DEPENDENCY_INVALID"):
        _working_dependency_binding(book, selection, source, root)


@pytest.mark.parametrize("first", ["new:1", "newer:1"])
def test_rebound_selected_dependencies_clear_only_the_repaired_chapter(monkeypatch, first):
    from novel_forge.modules.book_authority import manuscript
    original = [(1, "old:1", {"sources": []}),
        (2, "old:2", {"sources": [{"chapter": 1, "asset_version_id": "old:1"}]}),
        (3, "old:3", {"sources": [{"chapter": 2, "asset_version_id": "old:2"}]})]
    class Cursor:
        def execute(self, sql, *_):
            self.rows = [] if "authority_book_retained_working_continuation" in sql else original
        def fetchall(self):
            return self.rows
    sources = {number: SimpleNamespace(asset_version_id=version) for number, version in ((1, first), (2, "new:2"), (3, "old:3"))}
    monkeypatch.setattr(manuscript, "selected_source", lambda uow, book, number: sources[number])
    monkeypatch.setattr(manuscript, "_selected_working_dependencies", lambda uow, book, source:
        {"sources": [{"chapter": 1, "asset_version_id": "new:1"}]} if source.asset_version_id == "new:2" else None)
    deliveries, changes = manuscript.working_dependency_changes(SimpleNamespace(cursor=Cursor()), {"book_run_id": "run"})
    assert deliveries == [(number, dependencies) for number, _, dependencies in original]
    assert (changes[2] == []) is (first == "new:1")
    assert changes[3][0]["chapter"] == 2
    if first == "newer:1":
        assert changes[3][1]["chapter"] == 1


@pytest.mark.parametrize("revised,fresh", [(True, False), (False, True), (False, False)])
def test_best_dependency_rebinding_requires_this_root_revision_or_fresh_incumbent_review(monkeypatch, revised, fresh):
    from novel_forge.modules.book_authority import manuscript
    from novel_forge.modules.review.diagnostics import prose_hash
    book, source, selection, root = _working_dependency_case()
    source.content["selected_review"] = {"selection_review_source_asset_version_id": "review"}
    if not revised:
        source.content["selected_source_asset_version_id"] = "old:2"
    class Cursor:
        def __init__(self):
            self.query = 0
        def execute(self, *_):
            self.query += 1
        def fetchall(self):
            if self.query == 1:
                return [(root, "chapter.candidate.select_best")]
            if self.query == 2:
                return [("chapter.revision.apply",)] if revised else []
            return [({"target_asset_version_id": "old:2", "target_text_hash": prose_hash("正文")},)] if fresh else []
    monkeypatch.setattr(manuscript, "_optional_document", lambda *_: SimpleNamespace(content=selection))
    result = manuscript._selected_working_dependencies(SimpleNamespace(cursor=Cursor()), book, source)
    assert (result is not None) is (revised or fresh)


@pytest.mark.parametrize("drift", [None, "base_hash", "workspace", "selection_hash", "ambiguous_history"])
def test_working_editor_selection_inherits_rebound_native_base(monkeypatch, drift):
    from novel_forge.modules.book_authority import manuscript
    from novel_forge.modules.chapter_authority import author_editor
    book, source, original_selection, root = _working_dependency_case()
    editor = SimpleNamespace(asset_version_id="editor:2", content_hash="editor-hash", asset_type="author_edit_candidate",
        content={"base_asset_version_id": source.asset_version_id, "base_asset_hash": source.content_hash,
            "text": "润色正文", "draft_content": {"chapter": 2, "text": "润色正文"}})
    selected = {**book, "chapter": 2, "selected_asset_version_id": editor.asset_version_id,
        "selected_content_hash": editor.content_hash, "source_asset_version_id": source.asset_version_id,
        "source_content_hash": source.content_hash}
    if drift == "base_hash":
        editor.content["base_asset_hash"] = "wrong"
    elif drift == "workspace":
        selected["workspace_id"] = "another"
    elif drift == "selection_hash":
        selected["selected_content_hash"] = "wrong"
    class Cursor:
        def __init__(self):
            self.query = 0
        def execute(self, *_):
            self.query += 1
        def fetchall(self):
            if self.query == 1:
                return [(original_selection,)] * (2 if drift == "ambiguous_history" else 1)
            if self.query == 2:
                return [(root, "chapter.candidate.select_best")]
            return [("chapter.revision.apply",)]
    monkeypatch.setattr(author_editor, "require_source", lambda *_: source)
    monkeypatch.setattr(manuscript, "_optional_document", lambda *_: SimpleNamespace(asset_id="work-selection", content=selected))
    if drift in {"base_hash", "workspace", "selection_hash"}:
        with pytest.raises(KernelError, match="MANUSCRIPT_WORK_DEPENDENCY_INVALID"):
            manuscript._selected_working_dependencies(SimpleNamespace(cursor=Cursor()), book, editor)
    else:
        result = manuscript._selected_working_dependencies(SimpleNamespace(cursor=Cursor()), book, editor)
        assert (result is None) is (drift == "ambiguous_history")
        if result:
            assert result["sources"][0]["asset_version_id"] == "new:1"



def test_cancelled_revision_does_not_rebind_or_withhold_already_selected_prose(monkeypatch):
    from novel_forge.modules.book_authority import manuscript
    book, source, selection, root = _working_dependency_case()
    root["status"] = "CANCELLED"
    class Cursor:
        def execute(self, *_): pass
        def fetchall(self): return [(root, "chapter.candidate.select_best")]
    monkeypatch.setattr(manuscript, "_optional_document", lambda *_: SimpleNamespace(content=selection))
    assert manuscript._selected_working_dependencies(SimpleNamespace(cursor=Cursor()), book, source) is None
    assert source.content["text"] == "正文"


@pytest.mark.parametrize('prior,status,size,expected', [
    (None, 'EXECUTING', 10, 'LENGTH_REVISION_PENDING'),
    (('original-root', 'operator'), 'EXECUTING', 10, 'LENGTH_REVISION_PENDING'),
    (('original-root', 'operator'), 'SUCCEEDED', 10, 'LENGTH_REVISION_APPLIED'),
    (('original-root', 'operator'), 'SUCCEEDED', 4, 'REVISED_LENGTH_TARGET_UNMET'),
    (('original-root', 'operator'), 'CANCELLED', 10, 'LENGTH_REVISION_BLOCKED'),
])
def test_explicit_length_delivery_reuses_native_revision_and_selects_only_compliant_candidate(monkeypatch, prior, status, size, expected):
    from novel_forge.cli import manuscript as cli
    from novel_forge.modules.book_authority import manuscript
    from novel_forge.storage import authority_uow
    from unittest.mock import Mock

    book = {'book_run_id': 'run', 'project_id': 'p', 'current_chapter': 1, 'version': 7, 'state': 'READY'}
    unit = {'chapter': 1, 'asset_version_id': 'draft:1', 'content_hash': 'sha256:' + 'a' * 64,
        'length': {'actual': 1, 'target': {'minimum': 8, 'maximum': 12}}}
    monkeypatch.setattr(manuscript, 'require_manuscript', lambda *a, **k: {'units': [unit]})
    class Cursor:
        def execute(self, sql, params):
            self.sql = sql
        def fetchone(self):
            return (8,) if self.sql.startswith('SELECT version') else None if self.sql.startswith('SELECT attempt.result') else prior
    class Uow:
        cursor = Cursor()
        repositories = SimpleNamespace(asset_documents=SimpleNamespace(require=lambda **k:
            SimpleNamespace(asset_type='best_draft_candidate', content={'text': '字' * size})))
        def __init__(self, *_): pass
        def __enter__(self): return self
        def __exit__(self, *_): pass
    monkeypatch.setattr(authority_uow, 'AuthorityUnitOfWork', Uow)
    revised = Mock(return_value={'root_operation_id': 'original-root', 'status': status,
        'stages': [{'asset_version_id': 'native-best', 'output_key': 'chapter.best_candidate', 'status': 'SUCCEEDED'}]})
    selected = Mock()
    monkeypatch.setattr(cli, '_run_working_revision_command', revised)
    monkeypatch.setattr(cli, 'run_manuscript_command', selected)
    from novel_forge.modules.chapter_authority import working_revision
    monkeypatch.setattr(working_revision, 'revalidate_completed_length_candidate', lambda *a, **k: None)
    result = cli._ensure_native_work_length(SimpleNamespace(database_url='unused'),
        SimpleNamespace(work_window_seconds=300, book_run_id='run'), book=book, principal=SimpleNamespace(principal_id='operator'))
    assert result['status'] == expected
    command = revised.call_args.args[1]
    assert command.action == ('continue-revision' if prior else 'revise')
    assert command.revision_root == ('original-root' if prior else '')
    assert command.expected_version == 7 and '8—12' in command.reason
    assert selected.call_count == (1 if expected == 'LENGTH_REVISION_APPLIED' else 0)
    if selected.called:
        selection = selected.call_args.args[1]
        assert selection.action == 'use-working-candidate' and selection.candidate_version == 'native-best'
        assert selection.expected_version == 7


@pytest.mark.parametrize('target,chapter', [(None, 1), ({'minimum': 8, 'maximum': 12}, 1)])
def test_length_delivery_refuses_unbound_or_earlier_underlength_without_revision(monkeypatch, target, chapter):
    from novel_forge.cli import manuscript as cli
    from novel_forge.modules.book_authority import manuscript
    from unittest.mock import Mock
    monkeypatch.setattr(manuscript, 'require_manuscript', lambda *a, **k: {'units': [
        {'chapter': chapter, 'length': {'actual': 1, 'target': target}}]})
    revision = Mock(side_effect=AssertionError('No replacement may be admitted'))
    monkeypatch.setattr(cli, '_run_working_revision_command', revision)
    book = {'book_run_id': 'run', 'project_id': 'p', 'current_chapter': 2, 'state': 'READY'}
    if target is None:
        with pytest.raises(KernelError, match='MANUSCRIPT_LENGTH_TARGET_REQUIRED'):
            cli._ensure_native_work_length(SimpleNamespace(database_url='unused'), SimpleNamespace(), book=book, principal=None)
    else:
        result = cli._ensure_native_work_length(SimpleNamespace(database_url='unused'), SimpleNamespace(), book=book, principal=None)
        assert result['status'] == 'EARLIER_OR_ACTIVE_CHAPTER_REQUIRES_NATIVE_REVISION'
    revision.assert_not_called()


@pytest.mark.parametrize('state,active,chapter,settles', [
    ('CHAPTER_RUNNING', 'original-request', 6, True),
    ('CHAPTER_SUBMITTED', 'original-request', 6, True),
    ('CHAPTER_COMPLETED', 'original-request', 6, True),
    ('CHAPTER_WAITING_RETRY', 'original-request', 6, True),
    ('CHAPTER_FAILED_RETRYABLE', 'original-request', 6, True),
    ('CHAPTER_ACCEPTANCE_PENDING', 'original-request', 6, True),
    ('CANON_PENDING', 'original-request', 6, True),
    ('CHAPTER_FAILED_TERMINAL', 'original-request', 6, False),
    ('CHAPTER_RUNNING', '', 6, False),
    ('CHAPTER_RUNNING', 'original-request', 4, False),
    ('CHAPTER_RUNNING', 'original-request', 7, False),
    ('PAUSED', 'original-request', 6, False),
    ('ABORTED', 'original-request', 6, False),
    ('COMPLETED', 'original-request', 6, False),
    ('READY', 'original-request', 6, False),
])
def test_length_delivery_settles_only_the_saved_active_frontier_before_revision(monkeypatch, state, active, chapter, settles):
    from novel_forge.cli import manuscript as cli
    from novel_forge.modules.book_authority import manuscript
    from unittest.mock import Mock
    monkeypatch.setattr(manuscript, 'require_manuscript', lambda *a, **k: {'units': [
        {'chapter': chapter, 'length': {'actual': 3961, 'target': {'minimum': 4000, 'maximum': 5000}}}]})
    revision = Mock(side_effect=AssertionError('Active or unrelated Chapter cannot be revised'))
    monkeypatch.setattr(cli, '_run_working_revision_command', revision)
    book = {'book_run_id': 'run', 'project_id': 'p', 'current_chapter': 5,
        'state': state, 'active_chapter_request_id': active}
    result = cli._ensure_native_work_length(SimpleNamespace(database_url='unused'), SimpleNamespace(), book=book, principal=None)
    if settles:
        assert result is None
    else:
        assert result['status'] == 'EARLIER_OR_ACTIVE_CHAPTER_REQUIRES_NATIVE_REVISION'
    revision.assert_not_called()
