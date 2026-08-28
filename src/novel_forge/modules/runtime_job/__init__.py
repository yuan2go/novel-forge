"""PostgreSQL Authority Runtime Job execution plane.

Runtime Jobs own execution coordination only. Business state remains in the
domain Authority, Command Kernel Operation, Outbox, or ExternalEffect tables.
"""

from .application import (
    AUTHORITY_CONVERGENCE_REQUIRED,
    SAME_JOB_TAKEOVER,
    RuntimeJobAuthority,
    RuntimeJobClaim,
    RuntimeJobSpec,
    canonical_payload_hash,
    deterministic_runtime_job_id,
    OPERATIONAL_RUNTIME_JOB_CONTRACTS,
)

__all__ = [
    "AUTHORITY_CONVERGENCE_REQUIRED",
    "SAME_JOB_TAKEOVER",
    "RuntimeJobAuthority",
    "RuntimeJobClaim",
    "RuntimeJobSpec",
    "canonical_payload_hash",
    "deterministic_runtime_job_id",
    "OPERATIONAL_RUNTIME_JOB_CONTRACTS",
]
