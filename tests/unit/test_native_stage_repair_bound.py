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
    return [
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
    ]


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
    data[3] = (*data[3][:4], status, budget, data[3][6])
    with pytest.raises(
        KernelError, match="PLANNING_STAGE_REPAIR_RECONCILIATION_REQUIRED"
    ):
        stage_ordinal(
            Cursor(data), lineage=[r[0] for r in data], stage="chapter_plan.generate"
        )


def test_stage_policy_admits_monotonic_third_repair_as_first_chapter_repair_only():
    from tests.unit.test_native_planning_repair_routing import repair_snapshot, decide
    from novel_forge.modules.production_execution.planning_repair_routing import (
        STAGE_REPAIR_VERSION,
    )
    from copy import deepcopy

    snapshot = repair_snapshot()
    template = snapshot["task"]["policy_snapshot"]["policy"]["execution_templates"][0]
    template.update(
        version="creative-execution-template.v4", world_future_preparation="DISABLED"
    )
    template["repair_routing"]["version"] = "native-repair-routing.v2"
    evidence = snapshot["task"]["declared_requirements"]["native_planning_repair"]
    evidence.update(
        version=STAGE_REPAIR_VERSION,
        repair_number=3,
        stage_repair_number=1,
        repair_stage=snapshot["task"]["task_type"],
    )
    assert decide(snapshot)["status"] == "SELECTED"
    for change in (
        "exhausted",
        "wrong-stage",
        "legacy-evidence",
        "independent",
        "unknown",
    ):
        invalid = deepcopy(snapshot)
        proof = invalid["task"]["declared_requirements"]["native_planning_repair"]
        if change == "exhausted":
            proof["stage_repair_number"] = 3
        elif change == "wrong-stage":
            proof["repair_stage"] = "world_candidates.generate"
        elif change == "legacy-evidence":
            proof["version"] = "native-planning-repair-evidence.v2"
        elif change == "independent":
            invalid["candidates"][0]["rejected_reasons"].append(
                "CROSS_MODEL_REVIEW_DIFFERENT_PROVIDER_REQUIRED"
            )
        else:
            invalid["task"]["history"][0]["failure_class"] = "UNKNOWN_EXTERNAL_OUTCOME"
        assert decide(invalid)["status"] == "BLOCKED", change
