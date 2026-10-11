from dataclasses import replace

import pytest

from novel_forge.modules.book_authority.opening import (
    OpenBookProductionRequest,
    PostgresBookOpeningApplication,
)
from novel_forge.modules.command_kernel.errors import KernelError


def request():
    return OpenBookProductionRequest(
        project_id="project:one",
        workspace_id="workspace:one",
        book_id="book:one",
        actor_id="operator:one",
        expected_book_version=2,
        production_profile="profile:v1",
        planning_input_versions={"book_design": "design:v1"},
        arc_logical_keys=("arc:one",),
        idempotency_key="opening:one",
        trace_id="trace:one",
        correlation_id="correlation:one",
        initial_story_state_version="state:v1",
        initial_canon_snapshot_version="canon:v1",
    )


def test_historical_frozen_opening_serialization_retains_exact_fields():
    original = request()
    serialized = original.to_dict()
    assert "planning_replacement" not in serialized
    assert len(serialized) == 13
    assert OpenBookProductionRequest.from_mapping(serialized).to_dict() == serialized


def test_planning_replacement_roundtrip_freezes_exact_predecessor_versions():
    replacement = {
        "contract_version": "unwritten-book-planning-replacement.v1",
        "source_opening_run_id": "opening:old",
        "source_version": 4,
        "reason": "typed volume allocation was lost",
        "expected_active_plan_versions": {
            "book:main": "plan:old",
            "volume:1": "volume:old",
        },
    }
    repaired = replace(request(), planning_replacement=replacement)
    assert OpenBookProductionRequest.from_mapping(repaired.to_dict()) == repaired
    with pytest.raises(ValueError, match="planning replacement"):
        replace(
            request(),
            planning_replacement={**replacement, "expected_active_plan_versions": {}},
        )


@pytest.mark.parametrize("blocked_query", [2, 3])
def test_replacement_denies_live_generation_or_unisolated_effect(blocked_query):
    original = request()
    source = (
        original.project_id,
        original.workspace_id,
        original.book_id,
        "ABORTED",
        4,
        original.to_dict(),
    )

    class Cursor:
        index = -1

        def execute(self, *_args):
            self.index += 1

        def fetchone(self):
            return (
                source
                if self.index == 0
                else ("unsettled",)
                if self.index == blocked_query
                else None
            )

        def fetchall(self):
            pytest.fail(
                "Unsettled model work must reject before any replacement lookup"
            )

    with pytest.raises(KernelError, match="REPLACEMENT_EXECUTION_UNSETTLED"):
        PostgresBookOpeningApplication._unwritten_replacement_versions_in_uow(
            Cursor(),
            request=original,
            source_opening_run_id="opening:old",
            source_version=4,
        )
