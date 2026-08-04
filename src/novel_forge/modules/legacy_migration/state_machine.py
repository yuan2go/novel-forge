"""Durable Legacy migration phase and evidence contracts.

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
    "MigrationDecision",
    "MigrationMaterializationLevel",
    "MigrationPhase",
    "MigrationPhaseCheckpoint",
    "MigrationReferenceStatus",
    "require_phase_transition",
]
