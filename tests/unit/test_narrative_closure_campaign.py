from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts.narrative_closure_campaign import (
    digest, main, plan_semantics, require_intervention, validate_campaign,
)


ROOT = Path(__file__).resolve().parents[2]


def manifest():
    source = json.loads((ROOT / "config/production/narrative-closure/samples.json").read_text())
    budget = json.loads((ROOT / "config/production/narrative-closure/budget-proposal.json").read_text())
    samples = []
    for sample in source["samples"]:
        arms = {}
        for name in ("A", "B"):
            participant = next(arm for arm in budget["arms"] if arm["sample_id"] == sample["sample_id"] and arm["arm"] == name)
            project = participant["project_id"]
            arms[name] = {"project_id": project, "book_id": participant["book_id"], "book_run_id": project + ":run",
                "author_input_asset_version_id": project + ":author", "chapter_group_run_id": project + ":group",
                "world_character_asset_version_ids": {"world": project + ":world", "characters": project + ":characters"},
                "chapter_command": {"chapter_number": 2, "title": "原创场景", "premise": sample["brief"],
                    "chapter_plan_asset_version_id": project + ":plan", "chapter_plan_content_hash": "sha256:" + "a" * 64,
                    "context_candidates": [], "preparation_report": {"author_draft_adoption": {
                        "candidate_asset_version_id": project + ":author", "decision_asset_version_id": project + ":adoption"}}}}
        samples.append({key: sample[key] for key in ("sample_id", "stage", "domain", "data_group")} | {
            "arms": arms, "source_text_hashes": [digest(sample["history"])], "original_text_hash": digest(sample["current"]),
            "plan_semantics_hash": "sha256:" + "1" * 64, "world_character_contract_hash": "sha256:" + "2" * 64})
    return {"contract_version": "narrative-closure-campaign.v1", "intervention": "WP02_COMBINED",
        "comparison_design": {"implementation_control": "SAME_FINAL_IMPLEMENTATION_NATIVE_PATHS",
            "historical_defective_implementation": "NOT_RUN", "attribution": "COMPLETE_DECLARED_INTERVENTION_ONLY"},
        "campaign_id": budget["experiment_id"], "budget": budget, "samples": samples,
        "implementation_sha": "a" * 40, "implementation_identity": "sha256:" + "a" * 64,
        "migration_head": "fixture-only-migration", "route_contract_hash": "sha256:" + "a" * 64,
        "database_name": "narrative_closure_fixture_test"}


def test_original_two_then_six_samples_and_budget_are_complete():
    value = manifest()
    assert validate_campaign(value) == value
    assert sum(sample["stage"] == "PILOT" for sample in value["samples"]) == 2
    assert value["budget"]["shared_total"] == {"calls": 928, "tokens": 29696000}


@pytest.mark.parametrize("mutate", [
    lambda value: value["samples"][0].update(sample_id="../escape"),
    lambda value: value["samples"][1].update(data_group=value["samples"][0]["data_group"]),
    lambda value: value["samples"][0]["arms"]["B"].update(book_run_id=value["samples"][0]["arms"]["A"]["book_run_id"]),
    lambda value: value["samples"][0]["arms"]["B"].update(project_id="foreign-project"),
    lambda value: value["samples"][0].update(expected_answer="fix injury"),
    lambda value: value["samples"][0]["arms"]["A"]["chapter_command"].update(preparation_report={}),
    lambda value: value["samples"][7].update(domain="ACTION"),
])
def test_manifest_rejects_scope_reuse_answer_leakage_and_missing_native_inputs(mutate):
    value = manifest()
    mutate(value)
    with pytest.raises(ValueError):
        validate_campaign(value)


def test_freeze_is_immutable_and_run_requires_explicit_exact_pin(tmp_path):
    source = tmp_path / "source.json"
    source.write_text(json.dumps(manifest()))
    target = tmp_path / "frozen.json"
    assert main(["freeze", "--manifest", str(source), "--output", str(target)]) == 0
    assert json.loads(target.read_text()) == manifest()
    with pytest.raises(FileExistsError):
        main(["freeze", "--manifest", str(source), "--output", str(target)])
    with pytest.raises(SystemExit):
        main(["resume", "--manifest", str(target), "--output", str(tmp_path / "out"), "--manifest-hash", digest(manifest())])


def test_wp02_and_craft_cannot_claim_each_others_changed_variables():
    pair = {name: {"production_profile": {"book_id": name, "target_chapter_count": 2},
                   "plan": {"craft_strategy": {"uses": ["existing"]}}} for name in ("A", "B")}
    pair["B"]["production_profile"]["cross_chapter_review_policy"] = {"enabled": True}
    require_intervention(manifest={"intervention": "WP02_COMBINED"}, pair=pair)
    pair["B"]["plan"]["craft_strategy"] = {"uses": ["different"]}
    with pytest.raises(ValueError, match="Craft strategy"):
        require_intervention(manifest={"intervention": "WP02_COMBINED"}, pair=pair)
    with pytest.raises(ValueError, match="production policy"):
        require_intervention(manifest={"intervention": "CRAFT_POLICY"}, pair=pair)
    pair["A"]["production_profile"]["cross_chapter_review_policy"] = {"enabled": True}
    require_intervention(manifest={"intervention": "CRAFT_POLICY"}, pair=pair)
    original = {"book_id": "A", "scene_plan": ["unchanged"], "craft_strategy": {"uses": ["first"]}}
    changed = deepcopy(original)
    changed["craft_strategy"] = {"uses": ["second"]}
    assert plan_semantics(original, intervention="CRAFT_POLICY") == plan_semantics(changed, intervention="CRAFT_POLICY")
    assert plan_semantics(original) != plan_semantics(changed)


def test_quality_correction_freezes_native_ranges_and_rejects_unlocated_or_whole_prose():
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.revision.domain import freeze_quality_edit_scope, quality_edit_contract
    from novel_forge.modules.review.cross_chapter import apply_targeted_edits
    revision = {'text': '🗡前文。代价缺失。后文。'}
    action = {'observation': 'causal_consistency', 'issue': {'code': 'QUALITY_CAUSAL_FAILED'}}
    evidence = {'dimension': action['observation'], 'target_asset_version_id': 'candidate', 'gate_status': 'FAILED',
                'evidence_locations': [{'start': 4, 'end': 9, 'claim': '缺失代价'}]}
    quality = {'evidence_reports': [evidence]}
    scope = freeze_quality_edit_scope(revision=revision, revision_asset_version_id='candidate', quality=quality, action=action)
    task = {**action, 'bounded_edit_scope': scope}
    contract = quality_edit_contract(revision=revision, revision_asset_version_id='candidate', revision_tasks=(task,))
    row = contract['permitted_ranges'][0]
    result = {'edits': [{**row['evidence_locator'], 'replacement': '付出代价。', 'issue_codes': [row['code']]}],
              'text': '🗡前文。付出代价。后文。'}
    assert apply_targeted_edits(draft=revision, review={'issues': contract['permitted_ranges'],
        'target_text_hash': contract['target_text_hash']}, result=result)['targeted_edits'] == result['edits']
    result['text'] = '偷改前文。付出代价。后文。'
    with pytest.raises(KernelError, match='exact diagnosed edits'):
        apply_targeted_edits(draft=revision, review={'issues': contract['permitted_ranges'],
            'target_text_hash': contract['target_text_hash']}, result=result)
    for locations in ([], [{'start': 0, 'end': len(revision['text'])}], [{'start': 0.5, 'end': 3}]):
        evidence['evidence_locations'] = locations
        task['bounded_edit_scope'] = freeze_quality_edit_scope(revision=revision, revision_asset_version_id='candidate', quality=quality, action=action)
        with pytest.raises(KernelError, match='located native evidence'):
            quality_edit_contract(revision=revision, revision_asset_version_id='candidate', revision_tasks=(task,))
    assert quality_edit_contract(revision=revision, revision_asset_version_id='candidate', revision_tasks=(action,)) is None


def test_quality_candidate_selection_requires_exact_explicit_checks_and_preserves_old_candidate():
    from dataclasses import replace
    from novel_forge.modules.chapter_authority.candidate_selection import CandidateEvidence, compare_candidates
    from novel_forge.modules.review.diagnostics import prose_hash
    from novel_forge.modules.review.prose_window import PRESERVATION_DIMENSIONS
    original = CandidateEvidence('old', {'text': '原有正文'}, 90, ('timeline_consistency',), 'review-old')
    content = {'text': '修订正文', 'source_quality_asset_version_id': 'quality-old',
               'quality_action_observations': ['timeline_consistency']}
    check = {'observation': 'timeline_consistency', 'status': 'SATISFIED', 'preservation': 'PRESERVED',
             'target_asset_version_id': 'new', 'target_text_hash': prose_hash(content['text']),
             'source_quality_asset_version_id': 'quality-old'}
    revised = CandidateEvidence('new', content, 92, (), 'review-new',
        diagnostic_contract_version='actionable-diagnostics.v1', cross_chapter_review=True,
        preservation_checks=tuple({'dimension': dimension, 'status': 'PRESERVED'} for dimension in PRESERVATION_DIMENSIONS),
        quality_resolution_checks=(check,))
    def compare(candidate):
        return compare_candidates(project_id='p', chapter_root_operation_id='root', previous=original,
            challenger=candidate, minimum_net_improvement=3)
    assert compare(revised)['selected_asset_version_id'] == 'new'
    for change in ({'status': 'UNCERTAIN'}, {'preservation': 'REGRESSED'}, {'target_text_hash': prose_hash('其他版本')}):
        assert compare(replace(revised, score=100, quality_resolution_checks=({**check, **change},)))['selected_asset_version_id'] == 'old'
    assert compare(replace(revised, score=100, quality_resolution_checks=()))['selected_asset_version_id'] == 'old'
