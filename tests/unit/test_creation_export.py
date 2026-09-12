from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from novel_forge.modules.chapter_outcome.acceptance_contract import resolve_accepted_manuscript
from novel_forge.modules.command_kernel.errors import KernelError


def document(kind, identity, content, *, project_id="p"):
    return {"project_id": project_id, "asset_type": kind, "asset_version_id": identity,
            "content": content, "content_hash": "sha256:" + hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}


def accepted_workspace():
    text = "🚪她决定寻找密室，却还不知道入口。"
    digest = "sha256:" + hashlib.sha256(text.encode()).hexdigest()
    grounding = {"contract_version": "grounded-canon.v1", "project_id": "p",
                 "semantic_status": "SUPPORTED_CANDIDATE", "candidate_asset_version_id": "chosen",
                 "text_hash": digest, "context_asset_version_id": "context"}
    artifacts = [
        document("best_draft_candidate", "chosen", {"text": text, "selected_source_asset_version_id": "original"}),
        document("quality_score_report", "q", {"target_asset_version_id": "chosen", "canon_patch_version_id": "canon", "review_asset_version_id": "review", "context_bundle_version_id": "context"}),
        document("re_review_report", "review", {"revision_version_id": "original", "target_text_hash": digest, "diagnostic_contract_version": "actionable-diagnostics.v1", "context_bundle_version_id": "context"}),
        document("canon_patch", "canon", {"source_asset_version_id": "chosen", "grounding": grounding}),
        document("context_bundle", "context", {"chapter_execution": {"memo_asset_version_id": "memo", "source_chapter_plan_asset_version_id": "plan"}}),
        document("chapter_memo", "memo", {"chapter": 1}),
        document("final_release_gate_report", "gate", {"accepted_asset_version_ids": {"quality": "q", "canon": "canon", "rereview": "review"}}),
        document("quality_score_report", "old-quality", {"target_asset_version_id": "discarded"}),
    ]
    outcome = document("chapter_outcome", "outcome", {"project_id": "p", "book_id": "b", "chapter_number": 1,
        "chapter_plan_version_id": "plan", "accepted_draft_asset_version_id": "chosen",
        "quality_aggregate_asset_version_id": "q", "canon_patch_asset_version_id": "canon",
        "final_release_gate_asset_version_id": "gate", "grounding": grounding})
    return {"project_id": "p", "book_id": "b", "root_operation_id": "chapter-root",
            "run": {"command": {"chapter_plan_content_hash": "sha256:plan"}},
            "artifacts": {"history": artifacts, "diagnoses": [], "facts": []}, "acceptance": {"status": "COMMITTED",
            "acceptance_id": "accepted", "accepted_through_chapter": 1,
            "outcome_asset_version_id": "outcome", "outcome": outcome}}


def test_formal_acceptance_resolves_retained_original_despite_historical_quality_order():
    workspace = accepted_workspace()
    resolved = resolve_accepted_manuscript(workspace)
    workspace["artifacts"]["history"].reverse()
    assert resolve_accepted_manuscript(workspace) == resolved
    assert resolved["candidate"]["asset_version_id"] == "chosen"
    assert resolved["review"]["content"]["revision_version_id"] == "original"
    assert len(workspace["artifacts"]["history"]) == 8


def test_knowledge_trace_keeps_selection_and_actual_accepted_prose_check_separate():
    from novel_forge.modules.mkaos_authority.trace import workspace_knowledge_trace
    workspace = accepted_workspace()
    workspace["acceptance"].update(story_state_asset_version_id="state:v1", canon_snapshot_asset_version_id="canon:v1")
    items = workspace["artifacts"]["history"]
    context = next(item for item in items if item["asset_type"] == "context_bundle")
    context["content"]["context_manifest"] = {"knowledge_usage": [{"knowledge_card_asset_version_id": "card:v1", "usage_role": "REFERENCE"}]}
    context.update(document("context_bundle", "context", context["content"]))
    review = next(item for item in items if item["asset_type"] == "re_review_report")
    review["content"]["knowledge_checks"] = [{"knowledge_card_asset_version_id": "card:v1", "status": "NOT_USED", "target_text_hash": review["content"]["target_text_hash"]}]
    review.update(document("re_review_report", "review", review["content"]))
    workspace["artifacts"]["inputs"] = [context]
    workspace["artifacts"]["diagnoses"] = [review]
    trace = workspace_knowledge_trace(workspace)["cards"][0]
    assert trace["selected"][0]["context_bundle_asset_version_id"] == "context"
    assert trace["accepted"]["check"]["status"] == "NOT_USED"
    assert trace["independent_editorial"] == "NOT_PROVEN"
    review["content"]["knowledge_checks"][0]["target_text_hash"] = "wrong-prose"
    review.update(document("re_review_report", "review", review["content"]))
    with pytest.raises(KernelError, match="accepted prose"):
        workspace_knowledge_trace(workspace)


def _comparison_exports(tmp_path, *, group_ranges=((1, 3), (4, 6)), shared_arc=True, chapter_count=6):
    from novel_forge.modules.mkaos_authority.domain import resolve_book_knowledge_access_policy
    from tests.unit.test_creation_comparison import comparison_identities
    comparison = comparison_identities(tmp_path, book_names=("treatment", "control"), target_chapters=6)
    for index, (arm, mode) in enumerate((("treatment", "ALLOW_ONLY"), ("control", "DENY_ALL"))):
        identity = comparison[index]
        project_id = identity["project_id"]
        access = resolve_book_knowledge_access_policy(
            production_profile={"knowledge_access_policy": {
                "mode": mode, "allowed_knowledge_card_asset_version_ids": ["card:v1"] if mode == "ALLOW_ONLY" else [],
            }}, project_id=project_id, book_id=arm,
        )
        folder = tmp_path / arm
        folder.mkdir()
        rows = []
        for chapter in range(1, chapter_count + 1):
            original = accepted_workspace()
            identities = {item["asset_version_id"] for item in original["artifacts"]["history"]} | {"outcome", "plan", "original"}
            def rewrite(value):
                if isinstance(value, str):
                    return f"{arm}:{chapter}:{value}" if value in identities else arm if value == "b" else project_id if value == "p" else value
                if isinstance(value, list):
                    return [rewrite(item) for item in value]
                if isinstance(value, dict):
                    return {key: rewrite(item) for key, item in value.items()}
                return value
            workspace = rewrite(original)
            workspace["root_operation_id"] = f"{arm}:root:{chapter}"
            workspace["run"]["command"]["chapter_plan_asset_version_id"] = f"{arm}:imported-plan:{chapter}"
            workspace["artifacts"]["history"].append(document("chapter_plan", f"{arm}:{chapter}:plan", {
                "source_chapter_plan_asset_version_id": f"{arm}:imported-plan:{chapter}",
                "source_chapter_plan_content_hash": workspace["run"]["command"]["chapter_plan_content_hash"],
                "source_extensions": {"source_planning_candidate_asset_version_id": f"{arm}:{chapter}:planning-candidate"},
            }))
            workspace["book_run_id"] = f"{arm}:book-run"
            workspace["acceptance"]["accepted_through_chapter"] = chapter
            workspace["acceptance"]["acceptance_id"] = f"{arm}:accept:{chapter}"
            workspace["acceptance"]["outcome"]["content"]["chapter_number"] = chapter
            workspace["acceptance"]["outcome"]["content"]["parent_group_version_id"] = f"{arm}:group-plan:{next(start for start, end in group_ranges if start <= chapter <= end)}"
            workspace["run"]["command"]["context_version_refs"] = {"arc_plan_versions": [f"{arm}:arc:1"] if shared_arc else [f"{arm}:arc:1", f"{arm}:arc:2"]}
            workspace["acceptance"].update(story_state_asset_version_id=f"{arm}:state:{chapter}", canon_snapshot_asset_version_id=f"{arm}:canon:{chapter}")
            context = next(item for item in workspace["artifacts"]["history"] if item["asset_type"] == "context_bundle")
            context["content"]["knowledge_access_policy"] = access
            for item in [workspace["acceptance"]["outcome"], *workspace["artifacts"]["history"]]:
                item.update(document(item["asset_type"], item["asset_version_id"], item["content"], project_id=project_id))
            rows.append(workspace)
        (folder / "chapter-workspaces.json").write_text(json.dumps(rows))
        groups = []
        for start, end in group_ranges:
            plan = document("planning_generation_candidate", f"{arm}:group-plan:{start}", {"chapter_range": [start, end]})
            groups.append({
                "group_run_id": f"{arm}:group:{start}", "project_id": project_id, "book_id": arm,
                "book_run_id": f"{arm}:book-run", "group_plan_version_id": plan["asset_version_id"],
                "volume_plan_version_id": f"{arm}:volume", "root_operation_id": f"{arm}:group-root:{start}",
                "chapter_range": [start, end], "accepted_through_chapter": end, "state": "COMPLETED", "plan": plan,
                "chapters": [{
                    "chapter_number": n, "chapter_plan_version_id": f"{arm}:{n}:planning-candidate",
                    "chapter_request_id": f"{arm}:request:{n}", "child_root_operation_id": f"{arm}:root:{n}",
                    "status": "ACCEPTED", "acceptance_operation_id": f"{arm}:accept-op:{n}",
                    "chapter_outcome_version_id": f"{arm}:{n}:outcome", "acceptance_id": f"{arm}:accept:{n}",
                    "acceptance_status": "COMMITTED", "story_state_asset_version_id": f"{arm}:state:{n}",
                    "canon_snapshot_asset_version_id": f"{arm}:canon:{n}",
                } for n in range(start, end + 1)],
            })
        (folder / "chapter-groups.json").write_text(json.dumps({
            "contract_version": "book-chapter-group-lineage.v1", "project_id": project_id, "book_id": arm,
            "book_run_id": f"{arm}:book-run", "accepted_through_chapter": chapter_count,
            "groups": groups, "offset": 0, "limit": 500, "has_more": False,
        }))
        for name in ("asset-export-status.json", "workspace-export-status.json"):
            (folder / name).write_text(json.dumps({"status": "COMPLETE", "errors": []}))
        identity["frozen_configuration"]["creation_policy"]["profiles"]["production_profile"]["content"]["knowledge_access_policy"] = access
        identity.update(status="ACCEPTED_TARGET_REACHED", book_run_id=f"{arm}:book-run",
                        future_plan_change={"after_chapter": 3, "result": {"snapshot_id": arm + ":changed-input"}},
                        knowledge_access_policy=access)
        (folder / "creation-run.json").write_text(json.dumps(identity))


def test_six_chapter_blind_export_uses_only_acceptance_bound_text_and_leaves_forms_empty(tmp_path):
    from scripts.prepare_knowledge_closure import blind_export
    _comparison_exports(tmp_path)
    result = blind_export(tmp_path / "treatment", tmp_path / "control", tmp_path / "blind")
    assert result["human_approval"] is False
    comparison = json.loads((tmp_path / "blind/private/comparison-contract.json").read_text())
    assert comparison["status"] == "COMPARABLE_RECORDED_OPPORTUNITY"
    allocations = next(item for item in comparison["classified_differences"] if item["category"] == "PROJECT_AND_SOURCE_ALLOCATION")
    assert allocations["A"]["project_total"]["calls"] == 270
    assert allocations["B"]["project_total"]["calls"] == 210
    assert allocations["A"]["creation_allocation"] == allocations["B"]["creation_allocation"]
    assert comparison["real_provider_execution"] == "NOT_ESTABLISHED_BY_COMPARISON"
    assert comparison["creative_benefit"] == "NOT_PROVEN"
    for form in (tmp_path / "blind").glob("unassigned-reader-*/knowledge-review-form.json"):
        value = json.loads(form.read_text())
        assert value["status"] == "NOT_REVIEWED"
        assert all(score is None for response in value["responses"] for score in response["scores"].values())
    context_path = tmp_path / "control/chapter-workspaces.json"
    original_export = context_path.read_text()
    contaminated = json.loads(original_export)
    context = next(item for item in contaminated[0]["artifacts"]["history"] if item["asset_type"] == "context_bundle")
    context["content"]["context_manifest"] = {"knowledge_usage": [{"asset_type": "knowledge_card", "asset_version_id": "card:v1"}]}
    context.update(document("context_bundle", context["asset_version_id"], context["content"], project_id=context["project_id"]))
    context_path.write_text(json.dumps(contaminated))
    with pytest.raises(ValueError, match="forbidden external knowledge"):
        blind_export(tmp_path / "treatment", tmp_path / "control", tmp_path / "contaminated-blind")
    context_path.write_text(original_export)
    report_path = tmp_path / "control/creation-run.json"
    changed = json.loads(report_path.read_text())
    changed["frozen_configuration"]["runtime_settings"].update(NOVEL_FORGE_CHAPTER_PROVIDER_CAP="100")
    report_path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="budgets"):
        blind_export(tmp_path / "treatment", tmp_path / "control", tmp_path / "invalid-blind")


def test_multiple_arcs_do_not_make_one_executed_group_into_two(tmp_path):
    from scripts.prepare_knowledge_closure import blind_export
    _comparison_exports(tmp_path, group_ranges=((1, 6),), shared_arc=False)
    with pytest.raises(ValueError, match="two.*chapter groups"):
        blind_export(tmp_path / "treatment", tmp_path / "control", tmp_path / "blind")


@pytest.mark.parametrize("fault", ["wrong_book", "wrong_range", "wrong_outcome", "wrong_state", "missing_child", "duplicate_group", "partial_page"])
def test_blind_group_lineage_must_match_exact_accepted_chapters(tmp_path, fault):
    from scripts.prepare_knowledge_closure import blind_export
    _comparison_exports(tmp_path, shared_arc=False)
    path = tmp_path / "treatment/chapter-groups.json"
    value = json.loads(path.read_text())
    group = value["groups"][0]
    if fault == "wrong_book":
        group["book_id"] = "foreign-book"
    elif fault == "wrong_range":
        group["chapter_range"] = [1, 4]
    elif fault == "wrong_outcome":
        group["chapters"][0]["chapter_outcome_version_id"] = "different-outcome"
    elif fault == "wrong_state":
        group["chapters"][0]["story_state_asset_version_id"] = "different-state"
    elif fault == "missing_child":
        group["chapters"].pop()
    elif fault == "duplicate_group":
        value["groups"].append(deepcopy(group))
    else:
        value["has_more"] = True
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="ChapterGroup"):
        blind_export(tmp_path / "treatment", tmp_path / "control", tmp_path / "blind")


@pytest.mark.parametrize("fault", ["missing_quality", "wrong_hash", "wrong_book", "old_candidate", "wrong_memo", "conflicting_version"])
def test_accepted_export_rejects_incomplete_or_conflicting_evidence(fault):
    workspace = accepted_workspace()
    items = workspace["artifacts"]["history"]
    if fault == "missing_quality":
        items[:] = [item for item in items if item["asset_version_id"] != "q"]
    elif fault == "wrong_hash":
        items[0]["content"]["text"] += "改稿"
    elif fault == "wrong_book":
        workspace["book_id"] = "other-book"
    elif fault == "old_candidate":
        outcome = workspace["acceptance"]["outcome"]["content"]
        outcome["accepted_draft_asset_version_id"] = "discarded"
        workspace["acceptance"]["outcome"] = document("chapter_outcome", "outcome", outcome)
    elif fault == "wrong_memo":
        items[:] = [item for item in items if item["asset_version_id"] != "memo"]
    else:
        items.append(deepcopy(items[0]))
        items[-1]["content"]["text"] = "conflict"
    with pytest.raises(KernelError):
        resolve_accepted_manuscript(workspace)


def test_partial_export_retains_successful_prose_and_reports_conflicting_chapter(tmp_path):
    from scripts.compare_creation_exports import main
    left, right = tmp_path / "before", tmp_path / "after"
    for folder in (left, right):
        folder.mkdir()
        (folder / "chapter-workspaces.json").write_text(json.dumps([accepted_workspace()], ensure_ascii=False))
    damaged = accepted_workspace()
    damaged["acceptance"]["outcome"]["content_hash"] = "sha256:bad"
    (right / "chapter-workspaces.json").write_text(json.dumps([accepted_workspace(), damaged], ensure_ascii=False))
    output = tmp_path / "comparison"
    assert main([str(left), str(right), "--output", str(output)]) == 2
    report = json.loads((output / "comparison.json").read_text())
    assert report["status"] == "PARTIAL_EXPORT"
    assert report["errors"] and (output / "chapter-1-candidate.txt").read_text().startswith("🚪")
    assert report["candidate_cost"]["status"] == "NOT_EXPORTED"


def test_blind_groups_cannot_share_an_absorbed_parent_volume(tmp_path):
    from scripts.prepare_knowledge_closure import blind_export
    _comparison_exports(tmp_path)
    path = tmp_path / 'control/chapter-groups.json'
    value = json.loads(path.read_text())
    for group in value['groups']:
        group['volume_plan_version_id'] = 'treatment:volume'
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='share upper-level plans'):
        blind_export(tmp_path / 'treatment', tmp_path / 'control', tmp_path / 'blind')


@pytest.mark.parametrize('fault', ['run_failed', 'partial_assets', 'missing_assets', 'partial_workspace'])
def test_blind_export_requires_complete_native_evidence_export(tmp_path, fault):
    from scripts.prepare_knowledge_closure import blind_export
    _comparison_exports(tmp_path)
    folder = tmp_path / 'treatment'
    if fault == 'run_failed':
        path = folder / 'creation-run.json'
        value = json.loads(path.read_text())
        value.update(status='EVIDENCE_EXPORT_BLOCKED', artifact_export_error='missing model-call page')
        path.write_text(json.dumps(value))
    elif fault == 'missing_assets':
        (folder / 'asset-export-status.json').unlink(missing_ok=True)
    else:
        path = folder / ('asset-export-status.json' if fault == 'partial_assets' else 'workspace-export-status.json')
        path.write_text(json.dumps({'status': 'PARTIAL', 'errors': ['missing exact evidence']}))
    with pytest.raises(ValueError, match='complete native evidence'):
        blind_export(folder, tmp_path / 'control', tmp_path / 'blind')


def test_allow_only_without_actual_delivery_is_not_an_effective_treatment(tmp_path):
    from scripts.prepare_knowledge_closure import blind_export
    _comparison_exports(tmp_path)
    result = blind_export(tmp_path / 'treatment', tmp_path / 'control', tmp_path / 'blind')
    assert result['treatment_status'] == 'TREATMENT_NOT_ESTABLISHED'
    assert result['creative_benefit'] == 'CREATIVE_BENEFIT_NOT_EVALUABLE'
    assert result['treatment_delivery'] == 'NOT_EXPORTED'
    assert result['treatment_realization'] == 'NOT_VERIFIED_IN_ACCEPTED_PROSE'
    assert (tmp_path / 'blind/private/treatment-status.json').is_file()


@pytest.mark.parametrize('mode', ['claimed', 'review_only', 'verified'])
def test_treatment_requires_creative_delivery_and_exact_accepted_prose_review(tmp_path, mode):
    from scripts.prepare_knowledge_closure import blind_export
    from novel_forge.modules.review.diagnostics import prose_hash
    _comparison_exports(tmp_path)
    folder = tmp_path / 'treatment'
    path = folder / 'chapter-workspaces.json'
    workspaces = json.loads(path.read_text())
    workspace = workspaces[0]
    items = workspace['artifacts']['history']
    context = next(item for item in items if item['asset_type'] == 'context_bundle')
    review = next(item for item in items if item['asset_type'] == 're_review_report')
    text = next(item for item in items if item['asset_version_id'] == 'treatment:1:chosen')['content']['text']
    context['content']['context_manifest'] = {'knowledge_usage': [{'knowledge_card_asset_version_id': 'card:v1', 'usage_role': 'REFERENCE'}]}
    context.update(document('context_bundle', context['asset_version_id'], context['content'], project_id=context['project_id']))
    review['content']['knowledge_checks'] = [{
        'knowledge_card_asset_version_id': 'card:v1', 'status': 'NOT_OBSERVED' if mode == 'claimed' else 'VERIFIED_IN_PROSE',
        'target_text_hash': prose_hash(text), 'evidence_class': 'FIXTURE_SEMANTIC_REVIEW',
        'conditions_checked': ['fixture condition'], 'evidence': {'start': 0, 'end': 2, 'quote': text[:2]},
    }]
    review.update(document('re_review_report', review['asset_version_id'], review['content'], project_id=review['project_id']))
    path.write_text(json.dumps(workspaces))
    (folder / 'knowledge-runtime-usage.json').write_text(json.dumps({
        'contract_version': 'book-knowledge-runtime-export.v1', 'project_id': workspace['project_id'], 'book_id': 'treatment',
        'book_run_id': 'treatment:book-run', 'status': 'COMPLETE', 'bounded': False,
        'records': [{'project_id': workspace['project_id'], 'book_id': 'treatment', 'knowledge_card_asset_version_id': 'card:v1',
                     'context_bundle_asset_version_id': context['asset_version_id'], 'context_bundle_content_hash': context['content_hash'],
                     'consumer_definition_name': 'chapter.revision.review' if mode == 'review_only' else 'chapter.draft.generate',
                     'external_effect_status': 'SUCCEEDED', 'external_effect_id': 'fixture:effect',
                     'external_receipt_ids': ['fixture:receipt'], 'provider_context_view_hash': 'sha256:fixture',
                     'delivery_evidence_class': 'FIXTURE_PROTOCOL_RECEIPT'}],
    }))
    result = blind_export(folder, tmp_path / 'control', tmp_path / 'blind')
    expected = 'TREATMENT_ESTABLISHED_BY_RECORDED_EVIDENCE' if mode == 'verified' else 'TREATMENT_NOT_ESTABLISHED'
    assert result['treatment_status'] == expected
    assert result['creative_benefit'] == ('EVALUABLE_NOT_PROVEN' if mode == 'verified' else 'CREATIVE_BENEFIT_NOT_EVALUABLE')
    private = json.loads((tmp_path / 'blind/private/treatment-status.json').read_text())
    assert private['independent_editorial'] == 'NOT_PROVEN'
    if mode == 'verified':
        assert private['realized'][0]['acceptance_id'] == 'treatment:accept:1'
        assert private['evidence_classes'] == ['FIXTURE_PROTOCOL_RECEIPT', 'FIXTURE_SEMANTIC_REVIEW']
