from __future__ import annotations

import pytest

from novel_forge.modules.chapter_authority.current_semantic_recovery import (
    CONTRACT,
    require_unused_extraction_attempt,
)
from novel_forge.modules.command_kernel.errors import KernelError


def test_semantic_repair_consumes_the_original_unused_attempt_without_resetting_history():
    require_unused_extraction_attempt(
        extraction={}, maximum=2, attempts=[(1, "SUCCEEDED")]
    )
    for extraction, attempts in [
        ({}, [(1, "FAILED_RETRYABLE"), (2, "SUCCEEDED")]),
        ({}, [(1, "UNKNOWN")]),
        (
            {"retained_result_repair": {"contract_version": CONTRACT}},
            [(1, "SUCCEEDED")],
        ),
    ]:
        with pytest.raises(
            KernelError, match="CURRENT_SEMANTIC_REPAIR_CONTROL_EXHAUSTED"
        ):
            require_unused_extraction_attempt(
                extraction=extraction, maximum=2, attempts=attempts
            )
    with pytest.raises(KernelError, match="CURRENT_SEMANTIC_REPAIR_CONTROL_INVALID"):
        require_unused_extraction_attempt(
            extraction={}, maximum=1, attempts=[(1, "SUCCEEDED")]
        )
