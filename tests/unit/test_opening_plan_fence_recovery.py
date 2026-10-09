from unittest.mock import Mock

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage import book_opening_plan_fence as fence


@pytest.mark.parametrize("live, checkpointed, allowed", [
    (None, True, False),
    (("opening", "new", 2, "job", "attempt", "lease", "worker", 3, "", "NONE"), False, False),
    (("opening", "new", 2, "job", "attempt", "lease", "worker", 3, "", "NONE"), True, True),
])
def test_retained_selected_branch_still_requires_current_live_fence(monkeypatch, live, checkpointed, allowed):
    cursor = Mock()
    cursor.fetchone.side_effect = [
        ("book",),
        ({"opening_run_id": "opening", "opening_execution_id": "old", "opening_execution_generation": 1}, None, None, None, False),
        live,
    ]
    cursor.fetchall.return_value = [("opening",)]
    proof = Mock(return_value=checkpointed)
    monkeypatch.setattr(fence, "_checkpoint_generation_authorized", proof)
    kwargs = dict(project_id="project", book_id="book", generation_operation_id="generation", candidate_asset_version_id="candidate")
    if allowed:
        fence.lock_and_assert_book_opening_plan_mutation(cursor, **kwargs)
    else:
        with pytest.raises(KernelError, match="BOOK_OPENING_PLAN_MUTATION_NOT_AUTHORIZED"):
            fence.lock_and_assert_book_opening_plan_mutation(cursor, **kwargs)
    if live is None:
        proof.assert_not_called()
    else:
        assert proof.call_args.kwargs["current_binding"]["runtime_fencing_token"] == 3
        assert proof.call_args.kwargs["candidate_asset_version_id"] == "candidate"
