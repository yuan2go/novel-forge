from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "architecture/manifests/legacy-surface-manifest.yaml"
CLASSIFICATIONS = {
    "MIGRATION_ONLY",
    "READ_ONLY_ARCHIVE",
    "DEVELOPMENT_FIXTURE",
    "COMPATIBILITY_ADAPTER",
    "REPLACE_PENDING",
    "DEAD_CODE",
}


def test_legacy_surfaces_are_explicitly_classified_and_production_is_excluded() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert payload["production_policy"]["silent_fallback"] == "FORBIDDEN"
    for surface in payload["surfaces"]:
        assert surface["classification"] in CLASSIFICATIONS
        assert "production" not in surface["allowed_environments"]
        assert surface["replacement"]
        assert surface["removal_preconditions"]
        for relative in surface["paths"]:
            assert (ROOT / relative).exists(), relative


def test_authority_entrypoints_do_not_import_legacy_application_or_local_storage() -> None:
    for relative in (
        "src/novel_forge/api/authority_app.py",
        "src/novel_forge/workers/agent_authority.py",
        "src/novel_forge/workers/chapter_authority.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "novel_forge.api.legacy_app" not in source
        assert "novel_forge.storage.local" not in source
