"""Validation for the stable PostgreSQL Authority architecture contract."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from novel_forge.tools.architecture_manifest import check_tests
from novel_forge.tools.authority_reachability import (
    build_authority_import_graph,
    production_paths,
)


CONTRACT_PATH = Path("architecture/manifests/postgresql-authority-contract.json")
SCHEMA_VERSION = "postgresql-authority-architecture-contract.v1"


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON contract: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"contract must be an object: {path}")
    return value


def load_contract(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    contract = _json_object(root / CONTRACT_PATH)
    if contract.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported PostgreSQL Authority architecture contract schema")
    if not str(contract.get("contract_id") or "").strip():
        raise ValueError("architecture contract id is required")
    return contract


def _manifest(root: Path, name: str) -> dict[str, Any]:
    path = root / "architecture/manifests" / name
    payload = _json_object(path)
    if payload.get("schema_version") != "architecture-manifest.v1":
        raise ValueError(f"unsupported subordinate manifest schema: {name}")
    return payload


def _missing(required: list[str], actual: set[str]) -> list[str]:
    return sorted(set(required) - actual)


def validate_contract(
    contract: dict[str, Any],
    coverage_manifest: dict[str, Any],
    repo_root: str | Path,
) -> dict[str, Any]:
    """Validate stable requirements against the current implementation and scan."""
    root = Path(repo_root).resolve()
    errors: list[str] = []
    if contract.get("schema_version") != SCHEMA_VERSION:
        errors.append("unsupported contract schema")

    requirements = contract.get("requirements")
    thresholds = contract.get("thresholds")
    if not isinstance(requirements, dict) or not isinstance(thresholds, dict):
        return {"status": "FAIL", "errors": ["contract requirements and thresholds are required"]}

    try:
        module_manifest = _manifest(root, "module-manifest.yaml")
        worker_manifest = _manifest(root, "worker-manifest.yaml")
        migration_manifest = _manifest(root, "migration-manifest.yaml")
        test_manifest = _manifest(root, "test-manifest.yaml")
        fitness_policy = _manifest(root, "fitness-policy.yaml")
    except ValueError as exc:
        return {"status": "FAIL", "errors": [str(exc)]}

    module_names = {str(item.get("name") or "") for item in module_manifest.get("modules", [])}
    worker_names = {str(item.get("name") or "") for item in worker_manifest.get("workers", [])}
    migration_ids = {str(item) for item in migration_manifest.get("migration_ids", [])}
    test_modules = {str(item) for item in test_manifest.get("required_modules", [])}

    for label, required, actual in (
        ("module", requirements.get("required_modules", []), module_names),
        ("worker", requirements.get("required_workers", []), worker_names),
        ("migration", requirements.get("required_migrations", []), migration_ids),
        ("test module", requirements.get("required_test_modules", []), test_modules),
    ):
        missing = _missing([str(value) for value in required], actual)
        if missing:
            errors.append(f"missing required {label}s: {', '.join(missing)}")

    from novel_forge.tools.authority_coverage_manifest import operation_catalog

    definitions = {
        str(item.get("name") or "")
        for item in operation_catalog(coverage_manifest.get("findings", []))
    }
    missing_operations = _missing(
        [str(value) for value in requirements.get("required_operation_definitions", [])],
        definitions,
    )
    if missing_operations:
        errors.append(f"missing required operation definitions: {', '.join(missing_operations)}")

    forbidden_dependencies = requirements.get("forbidden_dependencies", {})
    actual_domain_forbidden = {
        str(value) for value in fitness_policy.get("forbidden_domain_imports", [])
    }
    actual_production_forbidden = {
        str(value) for value in fitness_policy.get("forbidden_production_imports", [])
    }
    missing_domain_forbidden = _missing(
        [str(value) for value in forbidden_dependencies.get("domain", [])],
        actual_domain_forbidden,
    )
    missing_production_forbidden = _missing(
        [str(value) for value in forbidden_dependencies.get("production", [])],
        actual_production_forbidden,
    )
    if missing_domain_forbidden:
        errors.append(
            "fitness policy no longer forbids domain dependencies: "
            + ", ".join(missing_domain_forbidden)
        )
    if missing_production_forbidden:
        errors.append(
            "fitness policy no longer forbids production dependencies: "
            + ", ".join(missing_production_forbidden)
        )

    summary = coverage_manifest.get("summary", {})
    for metric, maximum in thresholds.get("coverage_summary_max", {}).items():
        actual = int(summary.get(metric, 0))
        if actual > int(maximum):
            errors.append(f"coverage metric {metric} is {actual}; maximum is {maximum}")
    side_effect_count = sum(
        1 for item in coverage_manifest.get("findings", []) if item.get("side_effect")
    )
    mapped_count = int(summary.get("mapped_side_effects", 0))
    mapped_ratio = 1.0 if side_effect_count == 0 else mapped_count / side_effect_count
    minimum_ratio = float(thresholds.get("minimum_mapped_side_effect_ratio", 1.0))
    if mapped_ratio < minimum_ratio:
        errors.append(
            f"mapped side-effect ratio is {mapped_ratio:.6f}; minimum is {minimum_ratio:.6f}"
        )
    false_positive_rate = float(
        coverage_manifest.get("quality_metrics", {}).get("false_positive_sample_rate", 1.0)
    )
    maximum_false_positive_rate = float(
        thresholds.get("maximum_false_positive_sample_rate", 0.05)
    )
    if false_positive_rate > maximum_false_positive_rate:
        errors.append(
            "false-positive sample rate is "
            f"{false_positive_rate:.6f}; maximum is {maximum_false_positive_rate:.6f}"
        )

    graph = build_authority_import_graph(root)
    reachable_forbidden = {
        path: production_paths(graph.paths_by_file.get(path, ()))
        for path in requirements.get("forbidden_production_reachable_paths", [])
        if production_paths(graph.paths_by_file.get(path, ()))
    }
    if reachable_forbidden:
        errors.append(
            "forbidden legacy production reachability: "
            + ", ".join(sorted(reachable_forbidden))
        )
    maximum_reachable = int(
        thresholds.get("maximum_forbidden_production_reachable_paths", 0)
    )
    if len(reachable_forbidden) > maximum_reachable:
        errors.append(
            "forbidden production reachability count is "
            f"{len(reachable_forbidden)}; maximum is {maximum_reachable}"
        )

    for rule in requirements.get("required_schema_and_index_rules", []):
        path = root / str(rule.get("path") or "")
        token = str(rule.get("token") or "")
        if not path.is_file():
            errors.append(f"required schema/index rule path is missing: {path.relative_to(root)}")
        elif token and token not in path.read_text(encoding="utf-8"):
            errors.append(
                f"required schema/index rule token {token!r} is missing from {path.relative_to(root)}"
            )

    test_report = check_tests(root)
    observed_test_counts = {
        str(item["name"]): int(item["count"])
        for item in test_report.get("collections", [])
    }
    for collection, minimum in thresholds.get("minimum_test_counts", {}).items():
        actual = observed_test_counts.get(str(collection), 0)
        if actual < int(minimum):
            errors.append(
                f"test collection {collection} has {actual}; minimum is {minimum}"
            )

    for label, actual, threshold_key in (
        ("module", len(module_names), "minimum_module_count"),
        ("worker", len(worker_names), "minimum_worker_count"),
        ("migration", len(migration_ids), "minimum_migration_count"),
    ):
        minimum = int(thresholds.get(threshold_key, 0))
        if actual < minimum:
            errors.append(f"{label} count is {actual}; minimum is {minimum}")

    identity = coverage_manifest.get("implementation_tree_identity", {})
    if coverage_manifest.get("schema_version") != "postgresql-authority-run-evidence.v1":
        errors.append("run evidence schema is missing or invalid")
    if not isinstance(coverage_manifest.get("findings"), list):
        errors.append("run evidence findings must be a list")
    if not isinstance(summary, dict):
        errors.append("run evidence summary must be an object")
    if identity.get("schema_version") != "implementation-tree-identity.v1":
        errors.append("implementation tree identity is missing or invalid")
    if coverage_manifest.get("architecture_contract_id") != contract.get("contract_id"):
        errors.append("run evidence references a different architecture contract")

    return {
        "schema_version": "postgresql-authority-contract-validation.v1",
        "contract_id": contract.get("contract_id"),
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "observed": {
            "module_count": len(module_names),
            "worker_count": len(worker_names),
            "migration_count": len(migration_ids),
            "operation_definition_count": len(definitions),
            "mapped_side_effect_ratio": mapped_ratio,
            "false_positive_sample_rate": false_positive_rate,
            "test_counts": observed_test_counts,
            "implementation_tree_sha": identity.get("implementation_tree_sha", ""),
        },
    }


__all__ = [
    "CONTRACT_PATH",
    "SCHEMA_VERSION",
    "load_contract",
    "validate_contract",
]
