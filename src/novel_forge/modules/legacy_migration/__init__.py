"""Frozen Legacy snapshot import through PostgreSQL Authority."""

from .application import LegacyImportApplication, LegacyImportCommand
from .approval import (
    LegacyMigrationApprovalApplication,
    LegacyMigrationDecisionCommand,
)
from .scanner import LegacySnapshotRecord, LegacySnapshotScan, scan_legacy_snapshot
from .service import LegacyMigrationService
from .codecs import DEFAULT_CODEC_REGISTRY, TypedMigrationCodecRegistry
from .state_machine import (
    MigrationDecision,
    MigrationMaterializationLevel,
    MigrationPhase,
    MigrationPhaseCheckpoint,
    MigrationReferenceStatus,
)

__all__ = [
    "LegacyImportApplication",
    "LegacyImportCommand",
    "LegacyMigrationApprovalApplication",
    "LegacyMigrationDecisionCommand",
    "LegacyMigrationService",
    "DEFAULT_CODEC_REGISTRY",
    "TypedMigrationCodecRegistry",
    "MigrationDecision",
    "MigrationMaterializationLevel",
    "MigrationPhase",
    "MigrationPhaseCheckpoint",
    "MigrationReferenceStatus",
    "LegacySnapshotRecord",
    "LegacySnapshotScan",
    "scan_legacy_snapshot",
]
