import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.stage_repairs import stage_ordinal
from novel_forge.modules.story_planning_runtime.world_result_recovery import (
    WORLD_GENERATION_CONTRACT_ERRORS,
)


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, _query, args):
        assert args == [["root", "world1", "world2", "deferred", "main1", "resumed"]]

    def fetchall(self):
        return self.rows


def rows():
    world = {
        "generator_operation_name": "chapter_plan.generate",
        "repair_result_diagnostic": {
            "error_code": sorted(WORLD_GENERATION_CONTRACT_ERRORS)[0]
        },
    }
    main = {"generator_operation_name": "chapter_plan.generate"}
    return [(*row, 0) for row in [
        ("root", 0, main, "w0", "SUCCEEDED", "SETTLED", "world_candidates.generate"),
        ("world1", 1, world, "w1", "SUCCEEDED", "SETTLED", "world_candidates.generate"),
        ("world2", 2, world, "w2", "SUCCEEDED", "SETTLED", "world_candidates.generate"),
        (
            "deferred",
            2,
            world,
            "m0",
            "FAILED_FINAL",
            "SETTLED",
            "chapter_plan.generate",
        ),
        ("main1", 3, main, "m1", "SUCCEEDED", "SETTLED", "chapter_plan.generate"),
        ("resumed", 3, main, "m1r", "SUCCEEDED", "SETTLED", "chapter_plan.generate"),
    ]]


def test_stage_ordinal_retains_world_spend_and_monotonic_counter_without_spending_main_repairs():
    data = rows()
    lineage = [r[0] for r in data]
    assert (
        stage_ordinal(Cursor(data), lineage=lineage, stage="chapter_plan.generate") == 1
    )
    assert (
        stage_ordinal(Cursor(data), lineage=lineage, stage="world_candidates.generate")
        == 2
    )


@pytest.mark.parametrize(
    "status,budget", [("UNKNOWN", "HELD_UNKNOWN"), ("SUCCEEDED", "RESERVED")]
)
def test_unsettled_or_unknown_lineage_never_enters_stage_repair(status, budget):
    data = rows()
    data[3] = (*data[3][:4], status, budget, data[3][6], 0)
    with pytest.raises(
        KernelError, match="PLANNING_STAGE_REPAIR_RECONCILIATION_REQUIRED"
    ):
        stage_ordinal(
            Cursor(data), lineage=[r[0] for r in data], stage="chapter_plan.generate"
        )


def test_legacy_stage_evidence_remains_readable_without_parallel_route_permission():
    from tests.unit.test_native_planning_repair_routing import repair_snapshot, decide
    from novel_forge.modules.story_planning_runtime.planning_repair_routing import STAGE_REPAIR_VERSION

    snapshot = repair_snapshot()
    template = snapshot["task"]["policy_snapshot"]["policy"]["execution_templates"][0]
    template.update(version="creative-execution-template.v4", world_future_preparation="DISABLED")
    template["repair_routing"]["version"] = "native-repair-routing.v2"
    evidence = snapshot["task"]["declared_requirements"]["native_planning_repair"]
    evidence.update(version=STAGE_REPAIR_VERSION, repair_number=3, stage_repair_number=1, repair_stage=snapshot["task"]["task_type"])
    assert decide(snapshot)["status"] == "BLOCKED"


def test_cancelled_zero_dispatch_runtime_predecessor_does_not_spend_stage_allowance():
    data = rows()
    data[2] = (*data[2][:4], "CANCELLED", "RELEASED", data[2][6], 0)
    assert stage_ordinal(Cursor(data), lineage=[r[0] for r in data], stage="world_candidates.generate") == 1
    data[2] = (*data[2][:7], 1)
    with pytest.raises(KernelError, match="RECONCILIATION_REQUIRED"):
        stage_ordinal(Cursor(data), lineage=[r[0] for r in data], stage="world_candidates.generate")


@pytest.mark.parametrize("decision_count", [0, 2])
def test_stage_route_requires_exact_prior_dispatch_without_inventing_first_stage_repair(monkeypatch, decision_count):
    from types import SimpleNamespace
    from novel_forge.modules.story_planning_runtime import stage_repairs

    template = {"version": "creative-execution-template.v6", "mode": "CREATIVE_VALIDATION", "require_literary_qualification": False, "repair_routing": {"version": "native-repair-routing.v2"}}
    monkeypatch.setattr(stage_repairs, "selected_book_template", lambda *args, **kwargs: {"policy_snapshot": {}})
    monkeypatch.setattr(stage_repairs, "decision_template", lambda *args: template)
    monkeypatch.setattr(stage_repairs, "stage_ordinal", lambda *args, **kwargs: pytest.fail("No unique prior stage dispatch may spend stage allowance"))
    monkeypatch.setattr(stage_repairs, "verify_template_provenance", lambda *args: pytest.fail("No unique prior dispatch may confer repair permission"))

    class RouteCursor:
        def execute(self, _query, args):
            assert args == ["source", "world_candidates.evaluate"]

        def fetchall(self):
            return [({},)] * decision_count

    command = SimpleNamespace(project_id="project", book_id="book", repair_of_operation_id="source", repair_of_candidate_id="")
    kwargs = dict(command=command, lineage=("source", "successor"), stage="world_candidates.evaluate", maximum=2)
    if decision_count:
        with pytest.raises(KernelError, match="PLANNING_STAGE_REPAIR_SOURCE_AMBIGUOUS"):
            stage_repairs.routing_repair_bound(RouteCursor(), **kwargs)
    else:
        assert stage_repairs.routing_repair_bound(RouteCursor(), **kwargs) is None


def test_stage_route_counts_only_an_exact_prior_same_stage_dispatch(monkeypatch):
    from types import SimpleNamespace
    from novel_forge.modules.story_planning_runtime import stage_repairs

    template = {"version": "creative-execution-template.v6", "mode": "CREATIVE_VALIDATION", "require_literary_qualification": False,
        "member_authorization_ref": "member:one", "require_independent_review": True, "repair_routing": {"version": "native-repair-routing.v2", "max_same_route_repairs": 2}}
    admission = {"policy_snapshot": {}}
    monkeypatch.setattr(stage_repairs, "selected_book_template", lambda *args, **kwargs: admission)
    monkeypatch.setattr(stage_repairs, "decision_template", lambda *args: template)
    monkeypatch.setattr(stage_repairs, "verify_template_provenance", lambda *args: template)

    def ordinal(cursor, *, lineage, stage):
        assert lineage == ("source",) and stage == "world_candidates.evaluate"
        return 1

    monkeypatch.setattr(stage_repairs, "stage_ordinal", ordinal)

    class RouteCursor:
        def execute(self, _query, args):
            assert args == ["source", "world_candidates.evaluate"]

        def fetchall(self):
            return [({},)]

    command = SimpleNamespace(project_id="project", book_id="book", repair_of_operation_id="source", repair_of_candidate_id="")
    assert stage_repairs.routing_repair_bound(RouteCursor(), command=command, lineage=("source", "successor"), stage="world_candidates.evaluate", maximum=3) == {
        "stage_repair_number": 2, "maximum_repairs": 2, "policy_admission": admission}


@pytest.mark.parametrize("version", range(4, 13))
def test_frozen_stage_template_dispatches_same_preflight_protocol(monkeypatch, version):
    from types import SimpleNamespace
    from novel_forge.modules.story_planning_runtime import preflight_continuation, planning_repair_routing
    from novel_forge.modules.production_execution import execution_template

    import json
    from pathlib import Path
    frozen = json.loads((Path(__file__).resolve().parents[2] / "config/execution_templates/author_first.json").read_text())
    frozen.update(book_id="book", member_authorization_ref="member", allowed_candidates=["member"])
    frozen["version"] = f"creative-execution-template.v{version}"
    for key, first in (("author_workflow", 12), ("quality_corrections", 10),
                       ("canon_evidence_localization", 9), ("chapter_graph_recovery", 7),
                       ("canon_validation_contract", 6), ("chapter_contract_recovery", 5)):
        if version < first:
            frozen.pop(key, None)
    if version < 9 and version >= 7:
        frozen["chapter_graph_recovery"] = "RETAIN_SETTLED_QUALITY_RANGE_RESULT"
    execution_template.validate_templates({"execution_templates": [frozen]})
    admission = {"policy_snapshot": {"policy": {"execution_templates": [frozen]}}}
    monkeypatch.setattr(execution_template, "selected_book_template", lambda *a, **k: admission)
    monkeypatch.setattr(planning_repair_routing, "native_planning_repair", lambda *a, **k: k["evidence_version"])
    command = SimpleNamespace(project_id="project", book_id=frozen["book_id"], generator_operation_name="chapter_plan.generate")
    assert preflight_continuation._native_preflight_evidence(SimpleNamespace(cursor=None),
        command=command, source_operation_id="repair", lineage=("source", "repair")) == planning_repair_routing.STAGE_REPAIR_VERSION
