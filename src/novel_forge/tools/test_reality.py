from __future__ import annotations

import argparse
import ast
from collections import Counter
import fnmatch
import json
from pathlib import Path
import re
from typing import Any, Mapping


MANIFEST_PATH = Path("architecture/manifests/test-manifest.yaml")
QUALIFICATION_MANIFEST_PATH = Path(
    "architecture/manifests/backend-qualification-manifest.yaml"
)
SCHEMA_VERSION = "novel-forge.test-reality-manifest.v1"
REPORT_SCHEMA_VERSION = "novel-forge.test-reality.v1"
CLASSIFICATIONS = (
    "CURRENT_DOMAIN_INVARIANT",
    "CURRENT_RUNTIME_CONTRACT",
    "CURRENT_AUTHORITY_BOUNDARY",
    "MIGRATION_COMPATIBILITY",
    "RETIREMENT_GUARD",
    "FIXTURE_PROTOCOL",
    "QUALIFICATION_INFRASTRUCTURE",
    "HISTORICAL_REDUNDANT",
)
CURRENT_CLASSIFICATIONS = frozenset(
    {
        "CURRENT_DOMAIN_INVARIANT",
        "CURRENT_RUNTIME_CONTRACT",
        "CURRENT_AUTHORITY_BOUNDARY",
    }
)
DIRECT_CURRENT_CLASSIFICATIONS = frozenset(
    {"CURRENT_DOMAIN_INVARIANT", "CURRENT_RUNTIME_CONTRACT"}
)
SEMANTIC_SLICE_ROLES = frozenset(
    {"CURRENT_BUSINESS_CAPABILITY", "MIGRATION_COMPATIBILITY", "SUPPORTING_CONTRACT"}
)
SEMANTIC_PROOF_CEILINGS = frozenset(
    {
        "CURRENT_CONTRACT_NO_REAL_PROVIDER",
        "FIXTURE_CONTROL_ONLY",
        "MIGRATION_COMPATIBILITY_ONLY",
        "POSTGRESQL_CURRENT_CONTRACT",
    }
)
CLASSIFICATION_PROOF_CEILINGS = {
    "CURRENT_DOMAIN_INVARIANT": frozenset({"IN_PROCESS_CONTRACT_ONLY"}),
    "CURRENT_RUNTIME_CONTRACT": frozenset(
        {"POSTGRESQL_INTEGRATION_ONLY", "IN_PROCESS_ACCEPTANCE_ONLY"}
    ),
    "CURRENT_AUTHORITY_BOUNDARY": frozenset({"STATIC_AUTHORITY_BOUNDARY"}),
    "MIGRATION_COMPATIBILITY": frozenset({"MIGRATION_COMPATIBILITY_ONLY"}),
    "RETIREMENT_GUARD": frozenset({"RETIREMENT_ONLY"}),
    "FIXTURE_PROTOCOL": frozenset({"FIXTURE_ONLY"}),
    "QUALIFICATION_INFRASTRUCTURE": frozenset({"INFRASTRUCTURE_ONLY"}),
    "HISTORICAL_REDUNDANT": frozenset({"NONE"}),
}
REQUIRED_RULE_FIELDS = (
    "id",
    "patterns",
    "classification",
    "owner",
    "capability",
    "production_target",
    "qualification_role",
    "proof_ceiling",
)
PATH_LITERAL = re.compile(
    r"(?:src/novel_forge|scripts|architecture/manifests)/[A-Za-z0-9_./*-]+"
)


def _error(errors: list[str], message: str) -> None:
    if message not in errors:
        errors.append(message)


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"manifest must be an object: {path}")
    return payload


def _relative(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    path = Path(text)
    if not text or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field} must be repository-relative")
    return path.as_posix()


def _matches(relative: str, rule: Mapping[str, Any]) -> bool:
    patterns = rule.get("patterns")
    if not isinstance(patterns, list):
        return False
    if not any(fnmatch.fnmatchcase(relative, str(pattern)) for pattern in patterns):
        return False
    excludes = rule.get("exclude_patterns", [])
    return not isinstance(excludes, list) or not any(
        fnmatch.fnmatchcase(relative, str(pattern)) for pattern in excludes
    )


def _module_target(root: Path, module: str) -> str:
    parts = module.split(".")
    while parts:
        candidate = root / "src" / Path(*parts)
        module_file = candidate.with_suffix(".py")
        package_file = candidate / "__init__.py"
        if module_file.is_file():
            return module_file.relative_to(root).as_posix()
        if package_file.is_file():
            return package_file.relative_to(root).as_posix()
        parts.pop()
    return ""


def _local_test_dependencies(root: Path, path: Path, tree: ast.AST) -> set[Path]:
    dependencies: set[Path] = set()
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = str(node.module or "")
            if node.level:
                package = list(path.relative_to(root).parent.parts)
                package = package[: len(package) - node.level + 1]
                module = ".".join([*package, *module.split(".")]).rstrip(".")
            modules = [module, *(f"{module}.{alias.name}" for alias in node.names)]
        for module in modules:
            if module != "tests" and not module.startswith("tests."):
                continue
            candidate = root / Path(*module.split("."))
            for dependency in (candidate.with_suffix(".py"), candidate / "__init__.py"):
                if dependency.is_file():
                    dependencies.add(dependency)
    for parent in path.parents:
        if parent == root:
            break
        conftest = parent / "conftest.py"
        if conftest.is_file() and conftest != path:
            dependencies.add(conftest)
    return dependencies


def _fixture_or_mock_sources(
    root: Path, path: Path, cache: dict[Path, tuple[bool, set[Path]]]
) -> list[str]:
    pending = [path]
    visited: set[Path] = set()
    sources: set[str] = set()
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        if current not in cache:
            content = current.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=str(current))
            backed = any(
                marker in content
                for marker in (
                    "unittest.mock",
                    "pytest.MonkeyPatch",
                    "monkeypatch",
                    "Scripted",
                    "scripted",
                    "fixture_protocol_only",
                    "SimpleNamespace",
                    "fake_deterministic_provider",
                )
            ) or any(
                (
                    isinstance(node, (ast.Name, ast.alias))
                    and re.match(
                        r"(?:Fake|Mock|MagicMock|AsyncMock|Stub)(?:[A-Z_]|$)",
                        node.id if isinstance(node, ast.Name) else node.name,
                    )
                )
                or (isinstance(node, ast.Attribute) and node.attr == "__new__")
                or (
                    isinstance(node, ast.ClassDef)
                    and not node.bases
                    and not node.name.startswith("Test")
                    and not node.name.endswith("Tests")
                    and any(isinstance(item, ast.FunctionDef) for item in node.body)
                )
                for node in ast.walk(tree)
            )
            cache[current] = (backed, _local_test_dependencies(root, current, tree))
        backed, dependencies = cache[current]
        if backed:
            sources.add(current.relative_to(root).as_posix())
        pending.extend(dependencies - visited)
    return sorted(sources)


def _test_facts(
    root: Path, path: Path, evidence_cache: dict[Path, tuple[bool, set[Path]]]
) -> tuple[int, list[str], list[str], list[str]]:
    content = path.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(path))
    definition_count = sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test")
    )
    symbols: set[str] = set()
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "novel_forge" or alias.name.startswith("novel_forge."):
                    symbols.add(alias.name)
                    target = _module_target(root, alias.name)
                    if target:
                        targets.add(target)
        elif isinstance(node, ast.ImportFrom):
            module = str(node.module or "")
            if module == "novel_forge" or module.startswith("novel_forge."):
                for alias in node.names:
                    symbols.add(f"{module}.{alias.name}")
                target = _module_target(root, module)
                if target:
                    targets.add(target)
    for match in PATH_LITERAL.finditer(content):
        candidate = match.group(0).rstrip(".,;:')\"")
        path_candidate = root / candidate
        if "*" not in candidate and path_candidate.exists():
            targets.add(candidate)
    return (
        definition_count,
        sorted(symbols),
        sorted(targets),
        _fixture_or_mock_sources(root, path, evidence_cache),
    )


def _owner_for_target(target: str) -> str:
    marker = "src/novel_forge/modules/"
    if target.startswith(marker):
        module = target.removeprefix(marker).split("/", 1)[0]
        return module.replace("_", "-") + "-authority"
    if target.startswith("src/novel_forge/storage/migrations/"):
        return "migration-authority"
    if target.startswith("src/novel_forge/storage/"):
        return "storage-authority"
    if target.startswith("src/novel_forge/api/"):
        return "api-composition"
    if target.startswith("src/novel_forge/workers/"):
        return "worker-composition"
    if target.startswith(("src/novel_forge/tools/", "scripts/")):
        return "repository-qualification"
    if target.startswith("architecture/manifests/"):
        return "repository-architecture"
    return "platform"


def check_test_reality(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    errors: list[str] = []
    try:
        manifest = _load_object(root / MANIFEST_PATH)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "status": "FAIL",
            "test_file_count": 0,
            "test_definition_count": 0,
            "classification_file_counts": {name: 0 for name in CLASSIFICATIONS},
            "classification_test_counts": {name: 0 for name in CLASSIFICATIONS},
            "unclassified_files": [],
            "files": [],
            "errors": [f"cannot load test reality manifest: {exc}"],
        }
    if manifest.get("schema_version") != SCHEMA_VERSION:
        _error(errors, f"test reality manifest schema must be {SCHEMA_VERSION}")
    raw_collections = manifest.get("collections")
    if not isinstance(raw_collections, list) or not raw_collections:
        _error(errors, "test reality collections must be a non-empty list")
        raw_collections = []
    for index, value in enumerate(raw_collections):
        try:
            relative = _relative(value, field=f"collections[{index}]")
        except ValueError as exc:
            _error(errors, str(exc))
            continue
        if not (root / relative).is_dir():
            _error(errors, f"test collection does not exist: {relative}")
    rules = manifest.get("classification_rules")
    if not isinstance(rules, list) or not rules:
        _error(errors, "classification_rules must be a non-empty list")
        rules = []
    validated_rules: list[Mapping[str, Any]] = []
    rule_ids: set[str] = set()
    for index, rule in enumerate(rules):
        if not isinstance(rule, Mapping):
            _error(errors, f"classification_rules[{index}] must be an object")
            continue
        missing = [field for field in REQUIRED_RULE_FIELDS if not rule.get(field)]
        if missing:
            _error(
                errors,
                f"classification_rules[{index}] is missing fields: {', '.join(missing)}",
            )
            continue
        rule_id = str(rule["id"])
        if rule_id in rule_ids:
            _error(errors, f"duplicate test reality rule id: {rule_id}")
        rule_ids.add(rule_id)
        classification = str(rule["classification"])
        if classification not in CLASSIFICATIONS:
            _error(errors, f"unsupported test reality classification: {classification}")
            continue
        if rule["proof_ceiling"] not in CLASSIFICATION_PROOF_CEILINGS[classification]:
            _error(
                errors, f"test classification has unsupported proof ceiling: {rule_id}"
            )
        validated_rules.append(rule)

    discovered = (
        sorted(path for path in (root / "tests").rglob("test_*.py") if path.is_file())
        if (root / "tests").is_dir()
        else []
    )
    discovered_relatives = {path.relative_to(root).as_posix() for path in discovered}
    for rule in validated_rules:
        for pattern in rule["patterns"]:
            if not any(
                fnmatch.fnmatchcase(relative, str(pattern))
                for relative in discovered_relatives
            ):
                _error(
                    errors,
                    f"test reality pattern matches no test files: {rule['id']}:{pattern}",
                )
    records: list[dict[str, Any]] = []
    unclassified: list[str] = []
    evidence_cache: dict[Path, tuple[bool, set[Path]]] = {}
    for path in discovered:
        relative = path.relative_to(root).as_posix()
        rule = next(
            (item for item in validated_rules if _matches(relative, item)), None
        )
        if rule is None:
            unclassified.append(relative)
            continue
        classification = str(rule["classification"])
        try:
            definition_count, symbols, targets, mock_sources = _test_facts(
                root, path, evidence_cache
            )
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            _error(errors, f"cannot inspect test reality: {relative}: {exc}")
            continue
        observed_targets = list(targets)
        configured_target = str(rule["production_target"])
        if configured_target != "AUTO_FROM_TEST_IMPORTS":
            try:
                target = _relative(
                    configured_target, field=f"{rule['id']}.production_target"
                )
            except ValueError as exc:
                _error(errors, str(exc))
            else:
                if not (root / target).exists():
                    _error(
                        errors, f"test reality production target is missing: {target}"
                    )
                targets.append(target)
                targets = sorted(set(targets))
        if classification in CURRENT_CLASSIFICATIONS and not targets:
            _error(errors, f"current test has no production target: {relative}")
        owner = str(rule["owner"])
        if owner == "AUTO_FROM_PRODUCTION_TARGET":
            owner = _owner_for_target(targets[0]) if targets else ""
        if not owner:
            _error(errors, f"test reality owner cannot be derived: {relative}")
        if classification == "HISTORICAL_REDUNDANT":
            _error(errors, f"historical redundant tests must be deleted: {relative}")
        records.append(
            {
                "path": relative,
                "classification": classification,
                "owner": owner,
                "capability": str(rule["capability"]),
                "production_targets": targets,
                "observed_production_targets": observed_targets,
                "tested_symbols": symbols,
                "qualification_role": str(rule["qualification_role"]),
                "proof_ceiling": str(rule["proof_ceiling"]),
                "evidence_basis": (
                    "FIXTURE_OR_MOCK_BACKED" if mock_sources else "DIRECT_CONTRACT"
                ),
                "fixture_or_mock_sources": mock_sources,
                "test_definition_count": definition_count,
                "rule_id": str(rule["id"]),
            }
        )
    for relative in unclassified:
        _error(errors, f"unclassified test file: {relative}")

    direct_records = [
        record
        for record in records
        if record["classification"] in DIRECT_CURRENT_CLASSIFICATIONS
        and record["evidence_basis"] == "DIRECT_CONTRACT"
        and record["test_definition_count"] > 0
        and any(
            target.startswith("src/novel_forge/")
            for target in record["observed_production_targets"]
        )
    ]
    downgraded: list[str] = []
    for record in records:
        record["current_semantic_evidence"] = record in direct_records
        record["direct_contract_witnesses"] = []
        if (
            record["classification"] != "CURRENT_DOMAIN_INVARIANT"
            or record["evidence_basis"] != "FIXTURE_OR_MOCK_BACKED"
        ):
            continue
        required = set(record["production_targets"])
        witnesses = [
            witness
            for witness in direct_records
            if witness["capability"] == record["capability"]
            and required.intersection(witness["observed_production_targets"])
        ]
        covered = {
            target
            for witness in witnesses
            for target in witness["observed_production_targets"]
        }
        if required and required <= covered:
            record["direct_contract_witnesses"] = sorted(
                witness["path"] for witness in witnesses
            )
        else:
            for field in ("classification", "qualification_role", "proof_ceiling"):
                record[f"declared_{field}"] = record[field]
            record["classification"] = "FIXTURE_PROTOCOL"
            record["qualification_role"] = "FIXTURE_CONTRACT_ONLY"
            record["proof_ceiling"] = "FIXTURE_ONLY"
            downgraded.append(record["path"])
    records_by_path = {record["path"]: record for record in records}
    slice_evidence: dict[str, dict[str, Any]] = {}
    policy = manifest.get("semantic_slice_policy")
    if not isinstance(policy, Mapping):
        _error(errors, "semantic_slice_policy must be an object")
        policy = {}
    try:
        qualification = _load_object(root / QUALIFICATION_MANIFEST_PATH)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        _error(errors, f"cannot load qualification semantic slices: {exc}")
        qualification = {}
    slices = qualification.get("semantic_slices")
    if not isinstance(slices, Mapping):
        _error(errors, "qualification semantic_slices must be an object")
        slices = {}
    for name, paths in slices.items():
        slice_policy = policy.get(name)
        if not isinstance(slice_policy, Mapping):
            _error(errors, f"semantic slice lacks test reality policy: {name}")
            continue
        if not isinstance(paths, list) or not paths:
            _error(errors, f"qualification semantic slice is empty: {name}")
            continue
        classes = {
            records_by_path.get(str(relative), {}).get("classification", "UNCLASSIFIED")
            for relative in paths
        }
        role = str(slice_policy.get("role") or "")
        proof_ceiling = str(slice_policy.get("proof_ceiling") or "")
        if "UNCLASSIFIED" in classes:
            _error(
                errors, f"semantic slice contains unclassified test evidence: {name}"
            )
        if role not in SEMANTIC_SLICE_ROLES:
            _error(errors, f"semantic slice has unsupported reality role: {name}")
        witnesses = [
            records_by_path[str(relative)]
            for relative in paths
            if records_by_path.get(str(relative), {}).get("current_semantic_evidence")
        ]
        required_targets = slice_policy.get("direct_contract_targets", [])
        valid_targets: set[str] = set()
        if role == "CURRENT_BUSINESS_CAPABILITY":
            if not witnesses:
                _error(
                    errors,
                    f"current semantic slice has no direct current-contract evidence: {name}",
                )
            if not isinstance(required_targets, list) or not required_targets:
                _error(
                    errors,
                    f"current semantic slice has no direct production targets: {name}",
                )
            else:
                for value in required_targets:
                    try:
                        target = _relative(
                            value, field=f"{name}.direct_contract_targets"
                        )
                    except ValueError as exc:
                        _error(errors, str(exc))
                        continue
                    if (
                        not target.startswith("src/novel_forge/")
                        or not (root / target).is_file()
                    ):
                        _error(
                            errors,
                            f"current semantic slice target is not production code: {name}:{target}",
                        )
                        continue
                    valid_targets.add(target)
                covered = {
                    target
                    for witness in witnesses
                    for target in witness["observed_production_targets"]
                }
                for target in sorted(valid_targets - covered):
                    _error(
                        errors,
                        f"current semantic slice lacks direct target evidence: {name}:{target}",
                    )
            if proof_ceiling in {
                "FIXTURE_CONTROL_ONLY",
                "MIGRATION_COMPATIBILITY_ONLY",
            }:
                _error(
                    errors,
                    f"supporting proof cannot qualify a current semantic slice: {name}",
                )
        if role == "SUPPORTING_CONTRACT" and proof_ceiling != "FIXTURE_CONTROL_ONLY":
            _error(
                errors,
                f"supporting semantic slice must retain fixture proof ceiling: {name}",
            )
        slice_evidence[str(name)] = {
            "role": role,
            "proof_ceiling": proof_ceiling,
            "direct_contract_targets": sorted(valid_targets),
            "direct_current_witnesses": sorted(record["path"] for record in witnesses),
            "supporting_evidence": sorted(
                str(relative)
                for relative in paths
                if not records_by_path.get(str(relative), {}).get(
                    "current_semantic_evidence"
                )
            ),
        }
        if role == "MIGRATION_COMPATIBILITY" and classes != {"MIGRATION_COMPATIBILITY"}:
            _error(
                errors,
                f"migration semantic slice contains non-migration evidence: {name}",
            )
        if (
            role == "MIGRATION_COMPATIBILITY"
            and proof_ceiling != "MIGRATION_COMPATIBILITY_ONLY"
        ):
            _error(
                errors,
                f"migration semantic slice must retain compatibility proof ceiling: {name}",
            )
        if proof_ceiling not in SEMANTIC_PROOF_CEILINGS:
            _error(errors, f"semantic slice has unsupported proof ceiling: {name}")

    file_counts = Counter(record["classification"] for record in records)
    test_counts = Counter()
    for record in records:
        test_counts[record["classification"]] += int(record["test_definition_count"])
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "FAIL" if errors else "PASS",
        "test_file_count": len(discovered),
        "test_definition_count": sum(test_counts.values()),
        "classification_file_counts": {
            name: file_counts.get(name, 0) for name in CLASSIFICATIONS
        },
        "classification_test_counts": {
            name: test_counts.get(name, 0) for name in CLASSIFICATIONS
        },
        "unclassified_files": unclassified,
        "files": records,
        "downgraded_fixture_files": downgraded,
        "semantic_slice_evidence": slice_evidence,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Classify retained tests by current reality role and proof ceiling."
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = check_test_reality(args.repo_root)
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
