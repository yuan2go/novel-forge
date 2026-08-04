from __future__ import annotations

from pathlib import Path

from novel_forge.infrastructure.settings import IndustrialSettings


def legacy_settings(root: str | Path) -> IndustrialSettings:
    """Build the explicit, non-production Legacy profile for compatibility tests."""

    return IndustrialSettings(
        root=Path(root).resolve(),
        environment="test",
        storage_authority="legacy_local",
        legacy_write_enabled=True,
        silent_legacy_fallback_enabled=False,
    )
