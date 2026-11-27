from __future__ import annotations

from unittest.mock import Mock

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.lease_heartbeat import LeaseHeartbeatGuard
from novel_forge.modules.source_import.definitions import (
    SOURCE_IMPORT_DECONSTRUCTION_OPERATION,
    SOURCE_IMPORT_OPERATION_TIMEOUT_SECONDS,
    SOURCE_IMPORT_PROFILING_OPERATION,
    SOURCE_IMPORT_PROFILING_QUEUE_TIMEOUT_SECONDS,
    source_import_definitions,
)


def test_expired_operation_is_probed_before_handler_can_start() -> None:
    renew = Mock()
    probe = Mock(
        side_effect=KernelError(
            "OPERATION_BUSINESS_TIMEOUT",
            "frozen operation business deadline has expired",
        )
    )
    guard = LeaseHeartbeatGuard(
        renew,
        lease_seconds=60,
        label="expired-before-handler",
        probe=probe,
    )

    with pytest.raises(KernelError, match="OPERATION_BUSINESS_TIMEOUT"):
        guard.__enter__()

    probe.assert_called_once_with()
    renew.assert_not_called()


def test_source_profile_deadline_includes_bounded_batch_queue() -> None:
    definitions = {
        item["name"]: item
        for item in source_import_definitions(
            application_build_id="test",
            commit_sha="f" * 40,
        )
    }

    assert definitions[SOURCE_IMPORT_PROFILING_OPERATION]["timeout_policy"] == {
        "operation_timeout_seconds": SOURCE_IMPORT_PROFILING_QUEUE_TIMEOUT_SECONDS
    }
    assert definitions[SOURCE_IMPORT_DECONSTRUCTION_OPERATION]["timeout_policy"] == {
        "operation_timeout_seconds": SOURCE_IMPORT_OPERATION_TIMEOUT_SECONDS
    }
