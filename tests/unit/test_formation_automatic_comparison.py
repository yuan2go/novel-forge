from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from novel_forge.modules.book_design_authority.formation_domain import StoryFormationInput
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.domain import canonical_hash
from novel_forge.modules.story_planning_runtime.narrative_search import CREATIVE_INTELLIGENCE_DIMENSIONS
from novel_forge.storage.story_formation_repositories import StoryFormationRepository
from tests.unit.test_story_formation_authorization import _input


def frozen_comparison():
    original = _input()
    profiles = json.loads((Path(__file__).resolve().parents[2] / "config/execution_templates/creation_inputs.json").read_text())
    profiles["profiles"]["production_profile"]["content"]["language_contract"] = {"required_language": "zh-CN"}
    return replace(original, generation_policy={**original.generation_policy,
        "contract_version": "formation-generation.v7", "creative_selection": "AUTO_COMPARISON",
        "creation_input_policy": profiles, "strategy_directives": ["causal direction", "character direction"],
        "selection_policy": {"contract_version": "narrative-search-comparison.v2",
            "dimension_weights": {dimension: 1 for dimension in CREATIVE_INTELLIGENCE_DIMENSIONS},
            "uncertainty_margin": 0.05, "tie_break": "STABLE_ID"}})


def test_current_automatic_policy_preserves_historical_selection_and_exact_digest():
    frozen = frozen_comparison()
    assert StoryFormationInput.from_mapping(frozen.to_dict()).digest == frozen.digest
    assert _input().generation_policy["contract_version"] == "formation-generation.v2"
    changed = deepcopy(frozen.to_dict())
    changed["generation_policy"]["selection_policy"]["uncertainty_margin"] = 0.1
    assert StoryFormationInput.from_mapping(changed).digest != frozen.digest


@pytest.mark.parametrize("field,value", [
    ("creative_selection", "AUTHOR_COMPARISON"), ("approval_mode", "REVIEW_PLAN"),
    ("strategy_directives", ["same", "same"]), ("creative_candidates", 1),
    ("strategy_directives", ["only one"]),
])
def test_automatic_comparison_requires_distinct_bounded_explicit_authorization(field, value):
    frozen = frozen_comparison()
    with pytest.raises(ValueError):
        replace(frozen, generation_policy={**frozen.generation_policy, field: value})


def owned_proof():
    frozen = frozen_comparison()
    authorization = frozen.auto_authorization
    run = {**{key: authorization[key] for key in ("formation_run_id", "project_id", "workspace_id", "book_id")},
        "frozen_input": frozen.to_dict(), "frozen_input_digest": frozen.digest, "lifecycle": "PREPARING"}
    policy = frozen.generation_policy
    comparison = {"selected": "candidate", "uncertainty": "RETAINED"}
    row = ["search", run["project_id"], run["book_id"], "creative.candidates.generate",
        {"selection_policy": policy["selection_policy"], "author_brief": {
            "asset_version_id": frozen.creative_brief_asset_version_id, "content_hash": frozen.creative_brief_content_hash}},
        policy["strategy_directives"], "candidate", comparison, canonical_hash(comparison),
        run["formation_run_id"] + ":CREATIVE_FOUNDATION:comparison",
        {"level": "CREATIVE_FOUNDATION", "target_chapters": policy["target_chapters"]},
        run["workspace_id"], 0, None, None, None, "SELECTED", run["workspace_id"],
        run["project_id"], run["book_id"], "creative.candidates.generate", "sha256:" + "b" * 64]
    members = [("candidate", row[21], "causal direction", "CURRENT", "CLEAR", "STRUCTURALLY_VALID"),
        ("alternative", "sha256:" + "c" * 64, "character direction", "CURRENT", "CLEAR", "QUALIFIED")]
    cursor = Mock()
    cursor.fetchone.return_value = tuple(row)
    cursor.fetchall.return_value = members
    repository = StoryFormationRepository(cursor)
    repository.require = Mock(return_value=run)
    repository.cancellation = Mock(return_value=None)
    kwargs = {"generation_operation_id": "generation", "candidate_asset_version_id": "candidate",
        "candidate_content_hash": row[21], "candidate_asset_version_ids": ("candidate", "alternative"), "search_id": "search"}
    return repository, run, row, members, kwargs


def test_auto_selection_reads_exact_native_comparison_without_literary_qualification_claim():
    repository, run, _, _, kwargs = owned_proof()
    proof = repository.require_automatic_comparison_selection(run["formation_run_id"], **kwargs)
    assert proof["search_id"] == "search"
    assert proof["comparison"]["uncertainty"] == "RETAINED"


@pytest.mark.parametrize("index,value", [
    (1, "foreign-project"), (2, "foreign-book"), (11, "foreign-workspace"),
    (12, 1), (13, "accepted-run"), (15, "accepted-state"), (16, "STALE"),
    (18, "foreign-generation"), (21, "changed-hash"), (8, "changed-comparison-hash"),
    (6, "unselected-candidate"),
])
def test_foreign_or_accepted_or_changed_comparison_never_authorizes_selection(index, value):
    repository, run, row, _, kwargs = owned_proof()
    row[index] = value
    repository.cursor.fetchone.return_value = tuple(row)
    with pytest.raises(KernelError, match="CREATIVE_SEARCH_SELECTION_DRIFT"):
        repository.require_automatic_comparison_selection(run["formation_run_id"], **kwargs)


def test_sole_survivor_or_cancelled_or_changed_original_grant_cannot_auto_select():
    repository, run, _, members, kwargs = owned_proof()
    repository.cursor.fetchall.return_value = members[:1]
    with pytest.raises(KernelError, match="CREATIVE_SEARCH_CANDIDATE_EVIDENCE_INVALID"):
        repository.require_automatic_comparison_selection(run["formation_run_id"], **kwargs)
    repository.cancellation.return_value = {"cancellation_id": "cancel"}
    with pytest.raises(KernelError, match="CREATIVE_SEARCH_SELECTION_DRIFT"):
        repository.require_automatic_comparison_selection(run["formation_run_id"], **kwargs)
    repository.cancellation.return_value = None
    run["frozen_input_digest"] = "changed-original"
    with pytest.raises(KernelError, match="CREATIVE_SEARCH_SELECTION_DRIFT"):
        repository.require_automatic_comparison_selection(run["formation_run_id"], **kwargs)
