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
SEMANTIC_SLICE_ROLES = frozenset(
    {"CURRENT_BUSINESS_CAPABILITY", "MIGRATION_COMPATIBILITY"}
)
SEMANTIC_PROOF_CEILINGS = frozenset(
    {
        "CURRENT_CONTRACT_NO_REAL_PROVIDER",
        "FIXTURE_CONTROL_ONLY",
        "MIGRATION_COMPATIBILITY_ONLY",
        "POSTGRESQL_CURRENT_CONTRACT",
    }
)
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


def _test_facts(root: Path, path: Path) -> tuple[int, list[str], list[str], str]:
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
    evidence_basis = (
        "FIXTURE_OR_MOCK_BACKED"
        if any(
            marker in content
            for marker in (
                "unittest.mock",
                "pytest.MonkeyPatch",
                "monkeypatch",
                "Scripted",
                "scripted",
                "fixture_protocol_only",
            )
        )
        else "DIRECT_CONTRACT"
    )
    return definition_count, sorted(symbols), sorted(targets), evidence_basis


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
        validated_rules.append(rule)

    discovered = (
        sorted(
            path
            for path in (root / "tests").rglob("test_*.py")
            if path.is_file()
        )
        if (root / "tests").is_dir()
        else []
    )
    discovered_relatives = {
        path.relative_to(root).as_posix() for path in discovered
    }
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
    classification_by_path: dict[str, str] = {}
    for path in discovered:
        relative = path.relative_to(root).as_posix()
        rule = next((item for item in validated_rules if _matches(relative, item)), None)
        if rule is None:
            unclassified.append(relative)
            continue
        classification = str(rule["classification"])
        try:
            definition_count, symbols, targets, evidence_basis = _test_facts(root, path)
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            _error(errors, f"cannot inspect test reality: {relative}: {exc}")
            continue
        configured_target = str(rule["production_target"])
        if configured_target != "AUTO_FROM_TEST_IMPORTS":
            try:
                target = _relative(configured_target, field=f"{rule['id']}.production_target")
            except ValueError as exc:
                _error(errors, str(exc))
            else:
                if not (root / target).exists():
                    _error(errors, f"test reality production target is missing: {target}")
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
        classification_by_path[relative] = classification
        records.append(
            {
                "path": relative,
                "classification": classification,
                "owner": owner,
                "capability": str(rule["capability"]),
                "production_targets": targets,
                "tested_symbols": symbols,
                "qualification_role": str(rule["qualification_role"]),
                "proof_ceiling": str(rule["proof_ceiling"]),
                "evidence_basis": evidence_basis,
                "test_definition_count": definition_count,
                "rule_id": str(rule["id"]),
            }
        )
    for relative in unclassified:
        _error(errors, f"unclassified test file: {relative}")

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
            classification_by_path.get(str(relative), "UNCLASSIFIED")
            for relative in paths
        }
        role = str(slice_policy.get("role") or "")
        proof_ceiling = str(slice_policy.get("proof_ceiling") or "")
        if "UNCLASSIFIED" in classes:
            _error(errors, f"semantic slice contains unclassified test evidence: {name}")
        if role not in SEMANTIC_SLICE_ROLES:
            _error(errors, f"semantic slice has unsupported reality role: {name}")
        if role == "CURRENT_BUSINESS_CAPABILITY" and not (
            classes & CURRENT_CLASSIFICATIONS
        ):
            _error(errors, f"current semantic slice has no current-behavior evidence: {name}")
        if role == "MIGRATION_COMPATIBILITY" and classes != {
            "MIGRATION_COMPATIBILITY"
        }:
            _error(errors, f"migration semantic slice contains non-migration evidence: {name}")
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
