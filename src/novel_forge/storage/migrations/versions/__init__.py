from __future__ import annotations

from . import (
    v20260625_0001_initial_industrial_schema,
    v20260628_0002_query_and_release_indexes,
    v20260702_0003_mkaos_p0,
    v20260703_0004_review_issue,
    v20260712_0005_core_os_runtime,
    v20260712_0006_core_os_outbox_delivery,
    v20260712_0007_postgres_command_kernel_authority,
    v20260713_0008_authority_schema_recovery,
    v20260713_0009_attempt_lease_invariants,
)

VERSION_MODULES = [
    v20260625_0001_initial_industrial_schema,
    v20260628_0002_query_and_release_indexes,
    v20260702_0003_mkaos_p0,
    v20260703_0004_review_issue,
    v20260712_0005_core_os_runtime,
    v20260712_0006_core_os_outbox_delivery,
    v20260712_0007_postgres_command_kernel_authority,
    v20260713_0008_authority_schema_recovery,
    v20260713_0009_attempt_lease_invariants,
]

__all__ = ["VERSION_MODULES"]
