from dataclasses import replace
from copy import deepcopy
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
    ("FORMATION_CURRENT_FAILURE_REQUIRES_CORRECTION", "OWNER_RECOVERY_REQUIRED"),
    ("GENERATION_NO_PROGRESS", "OWNER_RECOVERY_REQUIRED"),
])
def test_creation_distinguishes_waits_without_a_new_business_state(reason, expected):
    assert creation_wait_class(reason) == expected


def test_recovery_versions_and_isolation_counts_are_not_material_progress():
    from copy import deepcopy
    from novel_forge.modules.book_authority.creation_runtime import creation_material_progress
    original = ["FOUNDATION", "RUNNING", 1, 4, 2, ["CHAPTER_SUBMITTED", 0, 3],
        {"cancel_requested": False, "generation_recovery": [1, 1], "opening": ["RUNNING", 1], "chapter": ["EXECUTING", 1]}]
    recovered = deepcopy(original)
    recovered[2] = 100
    recovered[5][2] = 100
    recovered[6].update(generation_recovery=[100, 100], opening=["RUNNING", 100], chapter=["EXECUTING", 100])
    assert creation_material_progress(original) == creation_material_progress(recovered)
    assert original[2] == 1
    for index in (0, 1, 3, 4):
        changed = deepcopy(recovered)
        changed[index] = "NEXT" if index < 2 else changed[index] + 1
        assert creation_material_progress(original) != creation_material_progress(changed)
    recovered[5][1] = 1
    assert creation_material_progress(original) != creation_material_progress(recovered)


@pytest.mark.parametrize("reason", ["YIELDED_CHECKPOINT", "WAITING_LEASE_OR_DEPENDENCY",
    "WAITING_OPENING_DEPENDENCY", "WAITING_CHAPTER_DEPENDENCY", "FORMATION_RECONCILIATION_OR_LEASE_REQUIRED"])
def test_healthy_or_unknown_wait_does_not_become_a_no_progress_failure(monkeypatch, reason):
    from types import SimpleNamespace
    from novel_forge.modules.book_authority import creation_runtime
    progress = ["FOUNDATION", "RUNNING", 1, 0, 0, [], {}]
    claim = SimpleNamespace(job_kind="BOOK_CREATION_ADVANCE", runtime_group="book_creation",
        runtime_job_id="creation-job",
        subject_kind="STORY_FORMATION_RUN", subject_id="formation", project_id="project", attempt_id="attempt",
        input_snapshot={"frozen_input_digest": "digest", "operator_id": "operator", "sequence": 50,
            "stagnant_windows": 50, "progress": progress})
    run = {"project_id": "project", "frozen_input_digest": "digest"}
    composition = SimpleNamespace(formation=SimpleNamespace(require=lambda _: run),
        principal=SimpleNamespace(principal_id="operator", require=lambda *_: None))
    jobs = SimpleNamespace(database_url="unused", start=lambda _: None, heartbeat=lambda *_, **__: None,
        assert_live=lambda _: None, complete=lambda *_: None,
        complete_and_schedule_continuation=lambda *_: {"scheduled": True})
    monkeypatch.setattr(creation_runtime, "creation_progress", lambda *_, **__: progress)
    monkeypatch.setattr(creation_runtime, "continue_creation", lambda **_: {"stop_reason": reason})
    result = creation_runtime.execute_creation_claim(jobs, claim, composition=composition,
        content=None, chapter=None, formation_worker=None, book_worker=None)
    assert result["stop_reason"] == reason
    assert result["wait_class"] == creation_runtime.creation_wait_class(reason)
    assert result["scheduled"] is True


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


def test_native_creation_freezes_current_method_bindings_and_keeps_legacy_replay():
    from novel_forge.modules.book_authority.creation_runtime import creation_narrative_execution
    from novel_forge.modules.book_authority.working_prose import working_instruction, working_prose_policy
    from novel_forge.modules.capability_packs.longform_profiles import build_story_planning_pack_profile
    root = Path(__file__).resolve().parents[2]
    policy = json.loads((root / "config/execution_templates/creation_inputs.json").read_text())
    path = creation_narrative_execution(policy)
    planning = build_story_planning_pack_profile(root, operation_definition_hash="sha256:" + "a" * 64,
        **path["planning"])
    skill = next(item for item in planning.manifest["skill_binding"]["skills"] if item["skill_ref"] == "long-outline")
    assert skill["version"] == "long-outline-v5"
    assert planning.manifest["identity"]["version"] == "2.17.0"
    assert path["chapter"] == {"pack_version_override": "3.1.0", "prose_skill_version": "prose-generation-v5",
        "prompt_template_version": "v15"}
    assert creation_narrative_execution({"narrative_execution_contract": "native-narrative-execution.v1"})["chapter"]["pack_version_override"] == "3.0.3"
    assert creation_narrative_execution({"narrative_execution_contract": "native-narrative-execution.v2"})["chapter"]["pack_version_override"] == "3.0.4"
    profile = policy["profiles"]["production_profile"]["content"]
    current = working_prose_policy(profile)
    assert current["version"] == "working-prose-projection.v6"
    assert current["max_characters"] is None
    assert planning.manifest["context_sources"]["policy_id"] == "context-policy:chapter-generation-pack:v3"
    assert "No fixed number of turns" in working_instruction(current)
    assert profile["craft_budget_policy"]["schema_version"] == "narrative-craft-budget.v5"
    assert profile["working_craft_history_policy"] == {"version": "working-craft-delivery.v2", "use": "SELECTED_CONTINUATION_WITH_LOCATED_TRANSITIONS"}
    historical = deepcopy(policy)
    historical["narrative_execution_contract"] = "native-narrative-execution.v2"
    historical_profile = historical["profiles"]["production_profile"]["content"]
    historical_profile["working_prose_policy"]["version"] = "working-prose-projection.v4"
    historical_profile["working_prose_policy"]["max_characters"] = 24_000
    historical_profile["craft_budget_policy"] = {"schema_version": "narrative-craft-budget.v4"}
    historical_profile["working_craft_history_policy"] = {"version": "working-craft-delivery.v1", "use": "SOFT_SELECTION_CAUTION"}
    historical_profile["language_contract"] = {"required_language": "zh-CN"}
    legacy = working_prose_policy(historical_profile)
    assert legacy["version"] == "working-prose-projection.v4"
    assert "Use three connected" in working_instruction(legacy)
    frozen = replace(_input(), generation_policy={**_input().generation_policy, "contract_version": "formation-generation.v4",
        "creation_input_policy": historical})
    replayed = StoryFormationInput.from_mapping(frozen.to_dict())
    assert replayed.digest == frozen.digest
    assert replayed.generation_policy["creation_input_policy"] == historical
    assert creation_narrative_execution({"contract_version": "creation-input-policy.v1"}) == {"chapter": {}, "planning": {}}
    with pytest.raises(Exception, match="Unknown frozen narrative execution contract"):
        creation_narrative_execution({"narrative_execution_contract": "unknown"})


def test_generated_title_request_is_explicit_and_preserves_author_title():
    from novel_forge.modules.book_authority.creation_runtime import creation_title
    assert creation_title({"version": "creation-request.v2"}) == ("Untitled — pending native Foundation", True)
    assert creation_title({"version": "creation-request.v1", "title": "作者选名"}) == ("作者选名", False)
    with pytest.raises(ValueError, match="author title"):
        creation_title({"version": "creation-request.v1"})
    with pytest.raises(ValueError, match="author title"):
        creation_title({"version": "creation-request.v2", "title": ""})


@pytest.mark.parametrize("version,chapter_version", [("v1", "3.0.3"), ("v2", "3.0.4"), ("v3", "3.1.0")])
def test_creation_installer_uses_actual_versioned_capacity_contract(monkeypatch, version, chapter_version):
    import hashlib
    from novel_forge.modules.capability_packs import validation_deployment as installer
    from novel_forge.modules.capability_packs.longform_profiles import build_story_planning_pack_profile
    from novel_forge.modules.book_authority.creation_runtime import creation_narrative_execution

    root = Path(__file__).resolve().parents[2]
    frozen = json.loads((root / "tests/fixtures/creation_capacity_legacy_contract_hashes.json").read_text())["contracts"]
    def digest(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    monkeypatch.setattr(installer, "_install_validation_manifest", lambda *args, **kwargs: kwargs)
    bindings = creation_narrative_execution({"narrative_execution_contract": "native-narrative-execution." + version})
    installed = installer.install_chapter_validation_pack("not-connected", repository_root=root,
        project_id="p", workspace_id="w", book_id="b", application_build_id="fixture", commit_sha="a" * 40,
        compiler=None, approver=None, agent_admin=None, pack_id_override="legacy-probe", **bindings["chapter"])
    manifest, catalog = installed["manifest"], installed["artifact_catalog"]
    assert manifest["identity"]["version"] == chapter_version
    context_version = "v3" if version == "v3" else "v2"
    assert manifest["context_sources"]["policy_id"] == "context-policy:chapter-generation-pack:" + context_version
    assert (manifest["context_sources"].get("capacity_policy") == "complete-request-capacity.v1") == (version == "v3")
    planning = build_story_planning_pack_profile(root, operation_definition_hash="sha256:" + "a" * 64, **bindings["planning"])
    if version != "v3":
        assert {"manifest": digest(manifest), "catalog": digest(catalog)} == frozen[chapter_version]
        assert {"manifest": digest(planning.manifest), "catalog": digest(planning.artifact_catalog)} == frozen["planning_2.15"]
    else:
        assert planning.manifest["identity"]["version"] == "2.17.0"


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


@pytest.mark.parametrize("failure", ["MODEL_EFFECT_RETRYABLE_PLANNING", "MODEL_EFFECT_FINAL_PLANNING"])
def test_authorized_formation_continue_is_not_denied_by_historical_failures(monkeypatch, failure):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from novel_forge.modules.book_authority import creation_runtime
    from novel_forge.modules.command_kernel import budget_runtime
    from novel_forge.modules.production_execution import execution_template
    class Cursor:
        def execute(self, query, *_): self.query = query
        def fetchone(self): return (100,) if "count(DISTINCT" in self.query else (False,)
    cursor = Cursor()
    monkeypatch.setattr(creation_runtime, "AuthorityUnitOfWork", lambda _: nullcontext(SimpleNamespace(cursor=cursor)))
    monkeypatch.setattr(budget_runtime, "unresolved_cli_outcomes", lambda *_, **__: [])
    monkeypatch.setattr(execution_template, "selected_book_template", lambda *_, **__: {"book_id": "book"})
    run = {"formation_run_id": "formation", "project_id": "project", "book_id": "book", "current_stage": "CREATIVE_FOUNDATION",
        "recovery_instruction": {"action": "RESUME_WITH_SAME_FROZEN_INPUTS"}, "failure": {"code": failure}}
    policy = {"approval_mode": "AUTO", "auto_authorization": {
        "formation_run_id": "formation", "project_id": "project", "book_id": "book", "authorized_by_principal_id": "operator"}}
    composition = SimpleNamespace(authority=SimpleNamespace(database_url="unused"), principal=SimpleNamespace(principal_id="operator"))
    assert creation_runtime._formation_resume_blocker(composition, run, policy) == ""
