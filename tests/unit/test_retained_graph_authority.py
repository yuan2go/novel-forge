from __future__ import annotations

from unittest.mock import Mock
import pytest

from novel_forge.api import authority_dependencies  # noqa: F401
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.retained_graph import source_graph


@pytest.mark.parametrize(
    "actor,status,version,saga",
    [
        ("another-actor", "FAILED_FINAL", "3.9.0", "MANUAL_INTERVENTION"),
        ("original", "SUCCEEDED", "3.9.0", "MANUAL_INTERVENTION"),
        ("original", "CANCELLED", "3.9.0", "MANUAL_INTERVENTION"),
        ("original", "FAILED_FINAL", "3.8.0", "MANUAL_INTERVENTION"),
        ("original", "FAILED_FINAL", "3.9.0", "SUCCEEDED"),
    ],
)
def test_terminal_graph_recovery_cannot_reopen_or_borrow_other_authorities(
    actor, status, version, saga
):
    cursor = Mock()
    cursor.fetchone.side_effect = [
        (
            {
                "definition_name": "chapter.slice.run",
                "root_operation_id": "source",
                "actor_id": actor,
                "status": status,
                "definition_version": version,
            },
        ),
        ({"status": saga, "project_id": "project"},),
    ]
    with pytest.raises(KernelError, match="RETAINED_GRAPH_SOURCE_INVALID"):
        source_graph(
            cursor, root_id="source", project_id="project", actor_id="original"
        )
    assert not cursor.fetchall.called


def test_missing_project_root_fails_before_reading_foreign_execution_evidence():
    cursor = Mock()
    cursor.fetchone.return_value = None
    with pytest.raises(KernelError, match="RETAINED_GRAPH_SOURCE_INVALID"):
        source_graph(
            cursor, root_id="foreign", project_id="project", actor_id="original"
        )
    assert cursor.execute.call_count == 1


def test_retained_correction_references_cannot_replace_missing_initial_completion_steps():
    from novel_forge.modules.command_kernel.operation_graph import initial_graph_complete

    base = [{"step_key": str(i), "status": "SUCCEEDED"} for i in range(19)]
    corrections = [
        {
            "step_key": "correction:" + str(i),
            "status": "SUCCEEDED",
            "initial_completion_member": False,
        }
        for i in range(3)
    ]
    assert not initial_graph_complete(base + corrections, 22)
    assert not initial_graph_complete(base + base[:3] + corrections, 22)
    complete = base + [{"step_key": str(i), "status": "SUCCEEDED"} for i in range(19, 22)]
    assert initial_graph_complete(complete + corrections, 22)
    corrections[0]["status"] = "UNKNOWN"
    assert not initial_graph_complete(complete + corrections, 22)
