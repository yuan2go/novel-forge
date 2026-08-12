from __future__ import annotations

import json
from pathlib import Path

from novel_forge.tools.architecture_fitness import _imports
from novel_forge.tools.authority_reachability import (
    build_authority_import_graph,
    production_paths,
)


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "architecture/manifests/migration-surface-manifest.yaml"


def _manifest() -> dict[str, object]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_migration_surface_manifest_is_explicit_and_bounded() -> None:
    payload = _manifest()
    assert payload["schema_version"] == "novel-forge.migration-surface.v1"
    assert payload["classification"] == "MIGRATION_ONLY"
    assert payload["runtime_registration"] == "FORBIDDEN"
    assert payload["production_import"] == "FORBIDDEN"
    for relative in payload["retained_paths"]:
        assert (ROOT / relative).exists(), relative


def test_retired_interactive_legacy_runtime_is_absent() -> None:
    payload = _manifest()
    for relative in payload["retired_paths"]:
        assert not (ROOT / relative).exists(), relative


def test_production_authority_has_zero_migration_surface_reachability() -> None:
    graph = build_authority_import_graph(ROOT)
    reached = {
        relative: production_paths(paths)
        for relative, paths in graph.paths_by_file.items()
        if relative.startswith("src/novel_forge/modules/legacy_migration/")
        and production_paths(paths)
    }
    assert reached == {}


def test_migration_surface_does_not_import_runtime_entry_or_execution_planes() -> None:
    forbidden = (
        "novel_forge.api",
        "novel_forge.workers",
        "novel_forge.modules.production_execution",
    )
    violations: dict[str, tuple[str, ...]] = {}
    for path in sorted(
        (ROOT / "src/novel_forge/modules/legacy_migration").rglob("*.py")
    ):
        imports = tuple(
            module
            for module in _imports(path)
            if any(module == root or module.startswith(root + ".") for root in forbidden)
        )
        if imports:
            violations[str(path.relative_to(ROOT))] = imports
    assert violations == {}
