from dataclasses import replace
import json
from pathlib import Path

import pytest

from novel_forge.modules.book_authority.creation_runtime import creation_wait_class, creation_runtime_environment
from novel_forge.modules.book_design_authority.formation_domain import StoryFormationInput
from novel_forge.modules.runtime_job import RuntimeJobSpec
from tests.unit.test_story_formation_authorization import _input


@pytest.mark.parametrize("reason,expected", [
    ("WAITING_OPENING_DEPENDENCY", "TECHNICAL_WAIT"),
    ("WAITING_APPROVAL", "AUTHOR_DECISION"),
    ("FORMATION_RECONCILIATION_OR_LEASE_REQUIRED", "RECONCILIATION_REQUIRED"),
    ("COMPLETED", "COMPLETED"), ("ABORTED", "CANCELLED"),
    ("SCHEMA_VALIDATION_FAILED", "OWNER_RECOVERY_REQUIRED"),
])
def test_creation_distinguishes_waits_without_a_new_business_state(reason, expected):
    assert creation_wait_class(reason) == expected


def test_formation_v5_freezes_author_comparison_and_creation_profiles():
    original = _input()
    policy = {**original.generation_policy, "contract_version": "formation-generation.v5",
        "creative_selection": "AUTHOR_COMPARISON", "creation_input_policy": json.loads(
            (Path(__file__).resolve().parents[2] / "config/execution_templates/creation_inputs.json").read_text())}
    policy["creation_input_policy"]["profiles"]["production_profile"]["content"]["language_contract"] = {"required_language": "zh-CN"}
    frozen = replace(original, generation_policy=policy)
    assert StoryFormationInput.from_mapping(frozen.to_dict()).digest == frozen.digest
    for changed in ["FIRST_ADMITTED", "BEST"]:
        with pytest.raises(ValueError, match="comparison"):
            replace(frozen, generation_policy={**policy, "creative_selection": changed})
    assert original.generation_policy["contract_version"] == "formation-generation.v2"


def test_creation_job_is_an_operational_envelope_with_stable_takeover_identity():
    spec = RuntimeJobSpec(job_kind="BOOK_CREATION_ADVANCE", runtime_group="book_creation",
        subject_kind="STORY_FORMATION_RUN", subject_id="frozen-formation", project_id="project",
        dedupe_key="frozen-formation:creation:0", input_snapshot={"frozen_input_digest": "source"})
    assert replace(spec).runtime_job_id == spec.runtime_job_id
    assert spec.lease_loss_policy == "SAME_JOB_TAKEOVER"
    with pytest.raises(ValueError, match="operational contract"):
        replace(spec, subject_kind="CHAPTER_ATTEMPT")


def test_worker_and_cli_resolve_the_same_project_pack_without_cross_project_resume():
    assert creation_runtime_environment("p", {}) == creation_runtime_environment("p", {})
    assert creation_runtime_environment("p", {}) != creation_runtime_environment("other", {})
    explicit = {"NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID": "explicit"}
    assert creation_runtime_environment("p", explicit)["NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID"] == "explicit"


def test_unknown_capacity_is_an_operator_configuration_wait_not_an_unknown_effect():
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.command_kernel.worker_execution import WorkerFailureClassifier, WorkerFailureClass
    assert WorkerFailureClassifier.classify(KernelError("TASK_CONTEXT_MODEL_OUTPUT_CAPACITY_UNKNOWN", "missing model capacity")) is WorkerFailureClass.MANUAL_INTERVENTION
    assert WorkerFailureClassifier.classify(KernelError("EFFECT_OUTCOME_UNKNOWN", "lost receipt")) is WorkerFailureClass.UNKNOWN_EXTERNAL_STATE


@pytest.mark.parametrize("code", ["PLANNING_RESULT_REPAIR_BOUND_EXCEEDED", "PLANNING_REPAIR_BOUND_EXCEEDED"])
def test_exhausted_content_repairs_require_a_new_decision_not_a_technical_retry(code):
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.command_kernel.worker_execution import WorkerFailureClassifier, WorkerFailureClass
    assert creation_wait_class(code) == "OWNER_RECOVERY_REQUIRED"
    assert WorkerFailureClassifier.classify(KernelError(code, "retained invalid proposal")) is WorkerFailureClass.MANUAL_INTERVENTION


def test_author_fixed_direction_reuses_one_exact_approved_input_with_continuous_profiles():
    original = _input()
    policy = {**original.generation_policy, "contract_version": "formation-generation.v5",
        "creative_selection": "AUTHOR_DIRECTION", "creative_candidates": 1,
        "author_creative_foundation": {"asset_version_id":"author-direction", "content_hash":"sha256:" + "a"*64},
        "creation_input_policy": json.loads((Path(__file__).resolve().parents[2] / "config/execution_templates/creation_inputs.json").read_text())}
    policy["creation_input_policy"]["profiles"]["production_profile"]["content"]["language_contract"] = {"required_language":"zh-CN"}
    frozen = replace(original,generation_policy=policy)
    assert StoryFormationInput.from_mapping(frozen.to_dict()).digest == frozen.digest
    with pytest.raises(ValueError):
        replace(frozen,generation_policy={**policy,"creative_candidates":2})
    with pytest.raises(ValueError):
        replace(frozen,generation_policy={**policy,"creative_selection":"AUTHOR_COMPARISON"})


def test_formation_recovery_blocks_legacy_cli_unknown_before_policy_or_retry_mutation(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from unittest.mock import Mock
    from novel_forge.modules.book_authority import creation_runtime
    from novel_forge.modules.command_kernel import budget_runtime
    from novel_forge.modules.production_execution import execution_template

    cursor = Mock()
    monkeypatch.setattr(creation_runtime, "AuthorityUnitOfWork", lambda _: nullcontext(SimpleNamespace(cursor=cursor)))
    unknown = Mock(return_value=[{"effect_status": "FAILED_RETRYABLE", "usage": "UNKNOWN"}])
    monkeypatch.setattr(budget_runtime, "unresolved_cli_outcomes", unknown)
    selected = Mock()
    monkeypatch.setattr(execution_template, "selected_book_template", selected)
    run = {"formation_run_id": "formation", "project_id": "project", "book_id": "book",
        "recovery_instruction": {"action": "RESUME_WITH_SAME_FROZEN_INPUTS"},
        "failure": {"code": "MODEL_EFFECT_RETRYABLE_PLANNING"}}
    policy = {"approval_mode": "AUTO", "auto_authorization": {
        "formation_run_id": "formation", "project_id": "project", "book_id": "book",
        "authorized_by_principal_id": "operator"}}
    composition = SimpleNamespace(authority=SimpleNamespace(database_url="unused"),
        principal=SimpleNamespace(principal_id="operator"))
    assert creation_runtime._formation_resume_blocker(composition, run, policy) == "FORMATION_RECONCILIATION_OR_LEASE_REQUIRED"
    unknown.assert_called_once_with(cursor, "project", book_id="book")
    selected.assert_not_called()
    cursor.execute.assert_not_called()
