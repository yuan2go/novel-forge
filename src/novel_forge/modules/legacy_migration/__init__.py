"""Frozen Legacy snapshot import through PostgreSQL Authority."""

from .application import LegacyImportApplication, LegacyImportCommand
from .scanner import LegacySnapshotRecord, LegacySnapshotScan, scan_legacy_snapshot
from .service import LegacyMigrationService
from .codecs import DEFAULT_CODEC_REGISTRY, TypedMigrationCodecRegistry

__all__ = [
    "LegacyImportApplication",
    "LegacyImportCommand",
    "LegacyMigrationService",
    "DEFAULT_CODEC_REGISTRY",
    "TypedMigrationCodecRegistry",
    "LegacySnapshotRecord",
    "LegacySnapshotScan",
    "scan_legacy_snapshot",
]
