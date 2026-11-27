from copy import deepcopy
from types import SimpleNamespace

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.execution import bind_provider_realization_selectors
from novel_forge.modules.story_planning_runtime.foundation_generation import foundation_output_schema, foundation_output_schema_ref
from novel_forge.modules.story_planning_runtime.narrative_search import CREATIVE_INTELLIGENCE_DIMENSIONS, compare_narrative_futures, validate_search_selection_policy
from novel_forge.modules.story_planning_runtime.runtime_continuation import require_source, _require_rejected_reference_owner
from tests.unit.test_narrative_search import _candidate


def catalog():
    return {"references_by_domain": {"WORLD_STATE": [{"asset_version_id": "world-state:v1", "project_id": "project", "book_id": "book", "domain_type": "WORLD_STATE", "content_hash": "sha256:" + "a" * 64, "frozen_by_operation_id": "native-owner"}]}}


def test_host_binds_exact_frozen_selector_without_changing_provider_receipt():
    raw = {"world_realization": [{"state_ref": {"asset_version_id": "world-state:v1"}, "invariant_refs": [], "structure_refs": []}]}
    frozen = deepcopy(raw)
    sources = catalog()
    result = bind_provider_realization_selectors(raw, sources)
    assert raw == frozen
    assert result["world_realization"][0]["state_ref"] == sources["references_by_domain"]["WORLD_STATE"][0]
    result["world_realization"][0]["state_ref"]["frozen_by_operation_id"] = "spoof"
    assert sources["references_by_domain"]["WORLD_STATE"][0]["frozen_by_operation_id"] == "native-owner"


@pytest.mark.parametrize("selector", [{"asset_version_id": "foreign"}, {"asset_version_id": "world-state:v1", "content_hash": "spoof"}, "world-state:v1"])
def test_provider_cannot_supply_foreign_selector_or_host_provenance(selector):
    with pytest.raises(KernelError, match="PLANNING_REALIZATION_SELECTOR_INVALID"):
        bind_provider_realization_selectors({"world_realization": [{"state_ref": selector, "invariant_refs": [], "structure_refs": []}]}, catalog())


def test_foundation_search_uses_forward_schema_and_old_schema_body_is_unchanged():
    baseline = foundation_output_schema("creative.candidates.generate", work_requirements=True, rfc6901_paths=True)
    current = foundation_output_schema("creative.candidates.generate", work_requirements=True, rfc6901_paths=True, narrative_search=True)
    assert "narrative_search_projection" not in baseline["properties"]
    assert "narrative_search_projection" in current["required"]
    assert current["properties"]["applicability"] == baseline["properties"]["applicability"]
    assert foundation_output_schema_ref("creative.candidates.generate", execution_contract_version="1.19.0").endswith(":v4")
    assert foundation_output_schema_ref("creative.candidates.generate", execution_contract_version="1.21.0", narrative_search=True).endswith(":v5")
    with pytest.raises(ValueError):
        foundation_output_schema_ref("creative.candidates.generate", execution_contract_version="1.19.0", narrative_search=True)
    with pytest.raises(ValueError):
        foundation_output_schema("theme.candidates.generate", narrative_search=True)


def policy():
    return {"contract_version": "narrative-search-comparison.v2", "dimension_weights": {dimension: 1 for dimension in CREATIVE_INTELLIGENCE_DIMENSIONS}, "uncertainty_margin": 0.2, "tie_break": "STABLE_ID"}


def test_uncertain_comparison_tie_retains_model_evidence_ceiling():
    candidates = (_candidate("b", "agency", 0.8), _candidate("a", "consequence", 0.75))
    comparison = compare_narrative_futures(candidates, selection_policy=policy())
    assert comparison.selected_candidate_asset_version_id == "a"
    assert comparison.selection_evidence["literary_superiority"] == "NOT_PROVEN"
    assert compare_narrative_futures(tuple(reversed(candidates)), selection_policy=policy()) == comparison


@pytest.mark.parametrize("change", [{"uncertainty_margin": float("nan")}, {"dimension_weights": {}}, {"tie_break": "MODEL_PREFERENCE"}])
def test_comparison_rejects_unfrozen_or_nonfinite_policy(change):
    with pytest.raises(KernelError, match="NARRATIVE_SEARCH_SELECTION_POLICY_INVALID"):
        validate_search_selection_policy({**policy(), **change})


class Cursor:
    def __init__(self, responses):
        self.responses = iter(responses)

    def execute(self, *_):
        self.row = next(self.responses)

    def fetchone(self):
        return self.row


def test_succeeded_candidate_cannot_shortcut_original_workspace_scope():
    frozen = {"project_id": "project", "workspace_id": "foreign", "book_id": "book", "execution_contract_version": "1.19.0"}
    with pytest.raises(KernelError, match="PLANNING_RUNTIME_CONTINUATION_SCOPE_INVALID"):
        require_source(SimpleNamespace(cursor=Cursor([("SUCCEEDED", 1, "workspace", frozen, "book", "candidate")])), source_operation_id="source", project_id="project")


@pytest.mark.parametrize("fields", [("REJECTED", "FAILED", "REJECTED", "CURRENT", "source"), ("ACTIVE", "QUALIFIED", "APPROVED", "CURRENT", "source"), ("REJECTED", "FAILED", "PENDING", "STALE", "source"), ("REJECTED", "FAILED", "PENDING", "CURRENT", "foreign")])
def test_host_recovery_preserves_author_rejection_current_owner_and_freshness(fields):
    owner = (*fields, "sha256:" + "a" * 64, "FAIL", {"error_code": "WORLD_REALIZATION_REFERENCE_INVALID"}, "sha256:" + "b" * 64)
    with pytest.raises(KernelError, match="PLANNING_REFERENCE_CONTRACT_SOURCE_INVALID"):
        _require_rejected_reference_owner(SimpleNamespace(cursor=Cursor([owner])), source_operation_id="source", row=("SUCCEEDED", 1, "workspace", {}, "book", "candidate"), frozen={"project_id": "project"})


def test_current_binder_keeps_provider_json_and_binds_candidate_only():
    from dataclasses import replace
    from novel_forge.modules.story_design_authority import GENERATOR_CATALOG
    from novel_forge.modules.story_planning_runtime.binder import CapabilityPackBackedPlanningExecutionBinder
    from tests.unit.test_story_planning_runtime import _ExecutionPort, _Resolver, _command, _inputs

    provider = {"objective": "Advance the governed plan", "world_realization": [{"state_ref": {"asset_version_id": "world-state:v1"}, "invariant_refs": [], "structure_refs": []}]}

    class Port(_ExecutionPort):
        realization_selector_catalog = catalog()

        def execute(self, command):
            return replace(super().execute(command), raw_output=provider)

    class Resolver(_Resolver):
        def resolve(self, **kwargs):
            return replace(super().resolve(**kwargs), execution_port=Port())

    command = replace(_command("book_plan.generate"), execution_contract_version="1.21.0")
    result = CapabilityPackBackedPlanningExecutionBinder(Resolver()).execute(
        operation_id="operation-1", attempt_id="attempt-1", fencing_token=7, worker_id="planning-worker",
        command=command, inputs=_inputs(command), definition=GENERATOR_CATALOG[command.generator_operation_name],
    )
    assert result.raw_provider_result == provider
    assert result.candidate_payload["world_realization"][0]["state_ref"]["content_hash"] == "sha256:" + "a" * 64
    assert provider["world_realization"][0]["state_ref"] == {"asset_version_id": "world-state:v1"}


def test_invalid_selector_retains_original_json_in_failure_evidence():
    from dataclasses import replace
    from novel_forge.modules.story_design_authority import GENERATOR_CATALOG
    from novel_forge.modules.story_planning_runtime.binder import CapabilityPackBackedPlanningExecutionBinder
    from novel_forge.modules.story_planning_runtime.result_recovery import PlanningResultValidationError
    from tests.unit.test_story_planning_runtime import _ExecutionPort, _Resolver, _command, _inputs

    provider = {"objective": "Advance the governed plan", "world_realization": [{"state_ref": {"asset_version_id": "foreign"}, "invariant_refs": [], "structure_refs": []}]}

    class Port(_ExecutionPort):
        realization_selector_catalog = catalog()

        def execute(self, command):
            return replace(super().execute(command), raw_output=provider)

    class Resolver(_Resolver):
        def resolve(self, **kwargs):
            return replace(super().resolve(**kwargs), execution_port=Port())

    command = replace(_command("book_plan.generate"), execution_contract_version="1.21.0")
    with pytest.raises(PlanningResultValidationError) as failed:
        CapabilityPackBackedPlanningExecutionBinder(Resolver()).execute(
            operation_id="operation-1", attempt_id="attempt-1", fencing_token=7, worker_id="planning-worker",
            command=command, inputs=_inputs(command), definition=GENERATOR_CATALOG[command.generator_operation_name],
        )
    assert failed.value.raw_result == provider
    assert failed.value.diagnostic["error_code"] == "PLANNING_REALIZATION_SELECTOR_INVALID"
    assert failed.value.execution_evidence["external_receipt_ref"] == "external-effect-receipt-1"


def test_rendered_foundation_task_declares_current_search_identity_only():
    from novel_forge.modules.story_planning_runtime.foundation_generation import foundation_task
    historical = foundation_task("creative.candidates.generate", work_requirements=True, aligned_methods=True, rfc6901_paths=True)
    current = foundation_task("creative.candidates.generate", work_requirements=True, aligned_methods=True, rfc6901_paths=True, narrative_search=True)
    assert historical["contract_version"] == "foundation-generation.v4"
    assert "narrative_search_contract" not in historical
    assert current["contract_version"] == "foundation-generation.v5"
    assert "not literary qualification" in current["narrative_search_contract"]


def test_current_arc_scope_allows_unscheduled_frozen_arc_without_changing_old_gate():
    from dataclasses import replace
    from novel_forge.modules.story_planning_runtime.application import _validate_frozen_arc_references
    from tests.unit.test_story_planning_runtime import _command

    command = replace(_command("chapter_group_plan.generate"), execution_contract_version="1.21.0", related_arc_plan_version_ids=("held-arc",))
    primary = command.input_versions["arc_plans"]
    content = {
        "primary_arc_ids": [primary], "secondary_arc_ids": ["held-arc"],
        "required_arc_contributions": [primary],
        "arc_checkpoint_expectations": [],
        "chapter_function_matrix": [{"arc_cadence": [{"arc_plan_version_id": primary, "action": "ADVANCE"}, {"arc_plan_version_id": "held-arc", "action": "HOLD"}], "required_arc_contributions": []}],
        "narrative_event_chain": [{"arc_contributions": [primary]}],
    }
    _validate_frozen_arc_references(command, content)
    with pytest.raises(KernelError, match="NARRATIVE_REALIZATION_ARC_SCOPE_INVALID"):
        _validate_frozen_arc_references(replace(command, execution_contract_version="1.19.0"), content)
    for arcs in ([], [primary, "foreign"]):
        invalid = {**content, "narrative_event_chain": [{"arc_contributions": arcs}]}
        with pytest.raises(KernelError, match="NARRATIVE_REALIZATION_ARC_SCOPE_INVALID"):
            _validate_frozen_arc_references(command, invalid)
    with pytest.raises(KernelError, match="PLANNING_ARC_PORTFOLIO_MISMATCH"):
        _validate_frozen_arc_references(command, {**content, "secondary_arc_ids": []})


@pytest.mark.parametrize("version", ["1.1.0", "1.2.0"])
def test_arc_recap_change_evidence_reads_exact_supported_native_owner(monkeypatch, version):
    from novel_forge.modules.story_planning_runtime import recap_sources
    from novel_forge.modules.book_followup_authority import accepted_realization

    observation = {"chapter_request_id": "request", "acceptance_id": "accepted", "contract_version": "accepted-realization-deviations.v2"}
    report = {"book_id": "book", "chapter_range": [1, 3], "contract_version": "longform-recap-v2" if version == "1.2.0" else "longform-recap-v1", "observation_snapshot": {"accepted_realization_deviations": observation} if version == "1.2.0" else {}}
    cursor = Cursor([(report, version, "original-author")])
    uow = SimpleNamespace(cursor=cursor)
    from contextlib import nullcontext
    monkeypatch.setattr(recap_sources, "AuthorityUnitOfWork", lambda url: nullcontext(uow))
    calls = []
    def read(cursor, **kwargs):
        calls.append(kwargs)
        return observation
    monkeypatch.setattr(accepted_realization, "read_accepted_realization_deviations", read)
    command = SimpleNamespace(project_id="project", workspace_id="workspace", book_id="book", change_evidence_version_ids=("report",))
    proposal = {"type": "ArcRevisionCandidate", "contract_version": "arc-revision-candidate-v1", "candidate_only": True, "plan_mutation_allowed": False, "affected_scope": "ARC", "impact_scope": {"future_only": True}, "future_from_chapter": 4}
    recap_sources.require_arc_recap_change_evidence("unused", command, "request-proposal", proposal)
    assert len(calls) == (1 if version == "1.2.0" else 0)
    if calls:
        assert calls[0] == {"project_id": "project", "workspace_id": "workspace", "book_id": "book", "chapter_request_id": "request", "actor_id": "original-author"}


def test_current_arc_recap_rejects_changed_accepted_observation(monkeypatch):
    from contextlib import nullcontext
    from novel_forge.modules.story_planning_runtime import recap_sources
    from novel_forge.modules.book_followup_authority import accepted_realization
    observation = {"chapter_request_id": "request", "acceptance_id": "accepted"}
    report = {"book_id": "book", "chapter_range": [1, 3], "contract_version": "longform-recap-v2", "observation_snapshot": {"accepted_realization_deviations": observation}}
    monkeypatch.setattr(recap_sources, "AuthorityUnitOfWork", lambda url: nullcontext(SimpleNamespace(cursor=Cursor([(report, "1.2.0", "author")]))))
    monkeypatch.setattr(accepted_realization, "read_accepted_realization_deviations", lambda *args, **kwargs: {**observation, "acceptance_id": "other"})
    command = SimpleNamespace(project_id="project", workspace_id="workspace", book_id="book", change_evidence_version_ids=("report",))
    with pytest.raises(KernelError, match="immutable accepted owner evidence"):
        recap_sources.require_arc_recap_change_evidence("unused", command, "proposal", {})


@pytest.mark.parametrize("search", [False, True])
def test_current_foundation_task_view_preserves_exact_rendered_contract(search):
    from novel_forge.modules.chapter_authority.provider_views import build_provider_task_view
    from novel_forge.modules.story_planning_runtime.foundation_generation import FOUNDATION_INPUT_ROLES, foundation_task
    stage = "creative.candidates.generate"
    inputs = {"planning_command": {"planning_scope": "NOT_APPLICABLE", "creative_requirements_contract": "work-requirements.v2", "execution_contract_version": "1.21.0", "narrative_search_id": "search" if search else ""},
        "frozen_inputs": [{"role": role} for role in FOUNDATION_INPUT_ROLES[stage]],
        "foundation_task": foundation_task(stage, work_requirements=True, aligned_methods=True, rfc6901_paths=True, narrative_search=search)}
    projected = build_provider_task_view(stage, inputs)
    assert projected["foundation_task"]["contract_version"] == ("foundation-generation.v5" if search else "foundation-generation.v4")
    assert projected["planning_command"]["execution_contract_version"] == "1.21.0"
    inputs["foundation_task"] = foundation_task(stage, work_requirements=True, aligned_methods=True, rfc6901_paths=False)
    with pytest.raises(KernelError, match="FOUNDATION_PROVIDER_TASK_INVALID"):
        build_provider_task_view(stage, inputs)
