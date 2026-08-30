"""INVARIANT: Durable Legacy migration phase and evidence contracts.

The state machine is intentionally independent from PostgreSQL so that every
caller, including resume/recovery code, shares the same transition rules and
checkpoint identity.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping


class MigrationMaterializationLevel(StrEnum):
    ARCHIVAL_NATIVE = "ARCHIVAL_NATIVE"
    DOMAIN_NATIVE = "DOMAIN_NATIVE"


class MigrationArchivalState(StrEnum):
    DISCOVERED = "DISCOVERED"
    CLASSIFIED = "CLASSIFIED"
    ARCHIVAL_IMPORTED = "ARCHIVAL_IMPORTED"
    ARCHIVAL_VALIDATED = "ARCHIVAL_VALIDATED"
    REFERENCES_PENDING = "REFERENCES_PENDING"
    REFERENCES_RESOLVED = "REFERENCES_RESOLVED"
    ARCHIVAL_RECONCILED = "ARCHIVAL_RECONCILED"


class MigrationDomainState(StrEnum):
    DOMAIN_NOT_APPLICABLE = "DOMAIN_NOT_APPLICABLE"
    DOMAIN_VALIDATION_PENDING = "DOMAIN_VALIDATION_PENDING"
    DOMAIN_VALIDATED = "DOMAIN_VALIDATED"
    DOMAIN_VALIDATION_FAILED = "DOMAIN_VALIDATION_FAILED"
    DOMAIN_DECISION_PENDING = "DOMAIN_DECISION_PENDING"
    DOMAIN_APPROVED = "DOMAIN_APPROVED"
    DOMAIN_REJECTED = "DOMAIN_REJECTED"
    DOMAIN_ACTIVATION_PENDING = "DOMAIN_ACTIVATION_PENDING"
    DOMAIN_ACTIVATED = "DOMAIN_ACTIVATED"
    DOMAIN_RECONCILED = "DOMAIN_RECONCILED"
    DOMAIN_RECONCILIATION_FAILED = "DOMAIN_RECONCILIATION_FAILED"


class MigrationValidationScope(StrEnum):
    ARCHIVAL = "ARCHIVAL"
    DOMAIN = "DOMAIN"


class MigrationRunCompletionLevel(StrEnum):
    NONE = "NONE"
    ARCHIVAL_RECONCILED = "ARCHIVAL_RECONCILED"
    DOMAIN_RECONCILED = "DOMAIN_RECONCILED"
    RELEASE_READY = "RELEASE_READY"


class MigrationRunStatus(StrEnum):
    IMPORT_RUNNING = "IMPORT_RUNNING"
    ARCHIVAL_RECONCILED = "ARCHIVAL_RECONCILED"
    DOMAIN_REVIEW_PENDING = "DOMAIN_REVIEW_PENDING"
    DOMAIN_ACTIVATION_PARTIAL = "DOMAIN_ACTIVATION_PARTIAL"
    DOMAIN_RECONCILED = "DOMAIN_RECONCILED"
    QUARANTINED = "QUARANTINED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class MigrationVerificationLevel(StrEnum):
    ARCHIVAL_NATIVE = "ARCHIVAL_NATIVE"
    DOMAIN_NATIVE = "DOMAIN_NATIVE"
    RELEASE_READY = "RELEASE_READY"


@dataclass(frozen=True, slots=True)
class MigrationCompletionFacts:
    archival_integrity: bool
    domain_native_count: int = 0
    domain_native_activated_count: int = 0
    pending_domain_native_count: int = 0
    failed_count: int = 0
    quarantine_count: int = 0
    actual_domain_failures: int = 0
    domain_validation_failures: int = 0
    domain_reconciliation_failures: int = 0
    required_reference_failures: int = 0

    def __post_init__(self) -> None:
        for name in (
            "domain_native_count",
            "domain_native_activated_count",
            "pending_domain_native_count",
            "failed_count",
            "quarantine_count",
            "actual_domain_failures",
            "domain_validation_failures",
            "domain_reconciliation_failures",
            "required_reference_failures",
        ):
            if int(getattr(self, name)) < 0:
                raise ValueError(f"{name} cannot be negative")


@dataclass(frozen=True, slots=True)
class MigrationCompletion:
    run_status: MigrationRunStatus
    completion_level: MigrationRunCompletionLevel
    required_level: MigrationVerificationLevel
    required_level_satisfied: bool


def derive_migration_completion(
    facts: MigrationCompletionFacts,
    *,
    required_level: MigrationVerificationLevel | str,
) -> MigrationCompletion:

    level = MigrationVerificationLevel(required_level)
    domain_failure_count = (
        facts.actual_domain_failures
        + facts.domain_validation_failures
        + facts.domain_reconciliation_failures
        + facts.required_reference_failures
    )
    if facts.failed_count or domain_failure_count or not facts.archival_integrity:
        run_status = MigrationRunStatus.FAILED
    elif facts.quarantine_count:
        run_status = MigrationRunStatus.QUARANTINED
    elif facts.pending_domain_native_count:
        run_status = (
            MigrationRunStatus.DOMAIN_ACTIVATION_PARTIAL
            if facts.domain_native_activated_count
            else MigrationRunStatus.DOMAIN_REVIEW_PENDING
        )
    elif facts.domain_native_count:
        run_status = MigrationRunStatus.DOMAIN_RECONCILED
    else:
        run_status = MigrationRunStatus.ARCHIVAL_RECONCILED

    archival_satisfied = (
        facts.archival_integrity
        and facts.failed_count == 0
        and facts.quarantine_count == 0
    )
    domain_satisfied = (
        archival_satisfied
        and facts.pending_domain_native_count == 0
        and domain_failure_count == 0
    )
    release_satisfied = (
        domain_satisfied
        and facts.domain_native_count > 0
        and run_status is MigrationRunStatus.DOMAIN_RECONCILED
    )
    if release_satisfied and level is MigrationVerificationLevel.RELEASE_READY:
        completion_level = MigrationRunCompletionLevel.RELEASE_READY
    elif domain_satisfied and facts.domain_native_count > 0:
        completion_level = MigrationRunCompletionLevel.DOMAIN_RECONCILED
    elif archival_satisfied:
        completion_level = MigrationRunCompletionLevel.ARCHIVAL_RECONCILED
    else:
        completion_level = MigrationRunCompletionLevel.NONE
    satisfied = {
        MigrationVerificationLevel.ARCHIVAL_NATIVE: archival_satisfied,
        MigrationVerificationLevel.DOMAIN_NATIVE: domain_satisfied,
        MigrationVerificationLevel.RELEASE_READY: release_satisfied,
    }[level]
    return MigrationCompletion(
        run_status=run_status,
        completion_level=completion_level,
        required_level=level,
        required_level_satisfied=satisfied,
    )


class MigrationPhase(StrEnum):
    SCAN = "SCAN"
    CLASSIFY = "CLASSIFY"
    IMPORT_CANDIDATE = "IMPORT_CANDIDATE"
    SEMANTIC_CONVERT = "SEMANTIC_CONVERT"
    VALIDATE = "VALIDATE"
    QUALIFY = "QUALIFY"
    ACTIVATE = "ACTIVATE"
    QUARANTINE = "QUARANTINE"
    RECONCILE = "RECONCILE"
    COMPLETE = "COMPLETE"


class MigrationReferenceStatus(StrEnum):
    UNRESOLVED = "UNRESOLVED"
    RESOLVED = "RESOLVED"
    QUARANTINED = "QUARANTINED"
    OPTIONAL_MISSING = "OPTIONAL_MISSING"
    CONFLICT = "CONFLICT"


class MigrationDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


_ALLOWED_TRANSITIONS: dict[MigrationPhase, frozenset[MigrationPhase]] = {
    MigrationPhase.SCAN: frozenset(
        {MigrationPhase.CLASSIFY, MigrationPhase.QUARANTINE}
    ),
    MigrationPhase.CLASSIFY: frozenset(
        {MigrationPhase.IMPORT_CANDIDATE, MigrationPhase.QUARANTINE}
    ),
    MigrationPhase.IMPORT_CANDIDATE: frozenset(
        {MigrationPhase.SEMANTIC_CONVERT, MigrationPhase.QUARANTINE}
    ),
    MigrationPhase.SEMANTIC_CONVERT: frozenset(
        {MigrationPhase.VALIDATE, MigrationPhase.QUARANTINE}
    ),
    MigrationPhase.VALIDATE: frozenset(
        {MigrationPhase.QUALIFY, MigrationPhase.QUARANTINE}
    ),
    MigrationPhase.QUALIFY: frozenset(
        {
            MigrationPhase.ACTIVATE,
            MigrationPhase.QUARANTINE,
            MigrationPhase.RECONCILE,
        }
    ),
    MigrationPhase.ACTIVATE: frozenset(
        {MigrationPhase.RECONCILE, MigrationPhase.QUARANTINE}
    ),
    MigrationPhase.QUARANTINE: frozenset({MigrationPhase.RECONCILE}),
    MigrationPhase.RECONCILE: frozenset(
        {MigrationPhase.COMPLETE, MigrationPhase.QUARANTINE}
    ),
    MigrationPhase.COMPLETE: frozenset(),
}


def require_phase_transition(
    current: MigrationPhase | str, target: MigrationPhase | str
) -> None:
    source = MigrationPhase(current)
    destination = MigrationPhase(target)
    if destination not in _ALLOWED_TRANSITIONS[source]:
        raise ValueError(
            f"illegal Legacy migration phase transition: "
            f"{source.value}->{destination.value}"
        )


@dataclass(frozen=True, slots=True)
class MigrationPhaseCheckpoint:
    migration_run_id: str
    item_id: str
    phase: MigrationPhase
    source_hash: str
    target_identity: str
    reference_state: MigrationReferenceStatus
    counts: Mapping[str, int]

    def __post_init__(self) -> None:
        if not self.migration_run_id or not self.item_id:
            raise ValueError("migration checkpoint requires run and item identity")
        if not self.source_hash.startswith("sha256:"):
            raise ValueError("migration checkpoint requires a SHA-256 source hash")
        if any(int(value) < 0 for value in self.counts.values()):
            raise ValueError("migration checkpoint counts cannot be negative")

    @property
    def content(self) -> dict[str, Any]:
        return {
            "migration_run_id": self.migration_run_id,
            "item_id": self.item_id,
            "phase": self.phase.value,
            "source_hash": self.source_hash,
            "target_identity": self.target_identity,
            "reference_state": self.reference_state.value,
            "counts": {key: int(self.counts[key]) for key in sorted(self.counts)},
        }

    @property
    def checkpoint_hash(self) -> str:
        encoded = json.dumps(
            self.content,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "MigrationArchivalState",
    "MigrationCompletion",
    "MigrationCompletionFacts",
    "MigrationDecision",
    "MigrationDomainState",
    "MigrationMaterializationLevel",
    "MigrationPhase",
    "MigrationPhaseCheckpoint",
    "MigrationReferenceStatus",
    "MigrationRunCompletionLevel",
    "MigrationRunStatus",
    "MigrationValidationScope",
    "MigrationVerificationLevel",
    "derive_migration_completion",
    "require_phase_transition",
]
