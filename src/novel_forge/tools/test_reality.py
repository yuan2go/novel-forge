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
DIRECT_CLASSIFICATIONS = frozenset(
    {"CURRENT_DOMAIN_INVARIANT", "CURRENT_RUNTIME_CONTRACT"}
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


def _fixture_info(node: ast.AST) -> tuple[str, bool] | None:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    for decorator in node.decorator_list:
        function = decorator.func if isinstance(decorator, ast.Call) else decorator
        if not (
            isinstance(function, ast.Attribute)
            and function.attr == "fixture"
            or isinstance(function, ast.Name)
            and function.id == "fixture"
        ):
            continue
        options = (
            {item.arg: item.value for item in decorator.keywords}
            if isinstance(decorator, ast.Call)
            else {}
        )
        name = options.get("name")
        autouse = options.get("autouse")
        return (
            str(name.value) if isinstance(name, ast.Constant) else node.name,
            autouse is not None
            and not (isinstance(autouse, ast.Constant) and autouse.value is False),
        )
    return None


def _import_module(path: Path, root: Path, node: ast.ImportFrom) -> str:
    module = node.module or ""
    if node.level:
        parts = list(path.relative_to(root).parent.parts)
        base = parts[: len(parts) - node.level + 1]
        module = ".".join([*base, *([module] if module else [])])
    return module


def _test_module_path(root: Path, module: str) -> Path | None:
    if not module.startswith("tests."):
        return None
    path = (root / module.replace(".", "/")).with_suffix(".py")
    if not path.is_file():
        path = root / module.replace(".", "/") / "__init__.py"
    return path if path.is_file() else None


def _mock_markers(content: str) -> bool:
    return any(
        marker in content
        for marker in (
            "unittest.mock",
            "pytest.MonkeyPatch",
            "monkeypatch",
            "Scripted",
            "scripted",
            "fixture_protocol_only",
            "FakeDeterministicProvider",
            "FakeUnknownOnceProvider",
            "FIXTURE_CONTROLLED",
            "MagicMock",
            "AsyncMock",
            "SimpleNamespace",
        )
    )


def _fixture_mock_backed(root: Path, path: Path) -> bool:
    sources = [
        parent / "conftest.py"
        for parent in reversed(path.parents)
        if parent == root or root in parent.parents
    ]
    sources = [source for source in sources if source.is_file()] + [path]
    fixtures: dict[str, list[tuple[Path, ast.AST, bool]]] = {}
    modules: dict[Path, ast.Module] = {}

    def module(source: Path) -> ast.Module:
        if source not in modules:
            tree = ast.parse(source.read_text(encoding="utf-8"))
            fixture_aliases = {
                alias.asname or alias.name
                for node in tree.body
                if isinstance(node, ast.ImportFrom) and node.module == "pytest"
                for alias in node.names
                if alias.name == "fixture"
            }
            for node in ast.walk(tree):
                for decorator in getattr(node, "decorator_list", ()):
                    function = (
                        decorator.func if isinstance(decorator, ast.Call) else decorator
                    )
                    if (
                        isinstance(function, ast.Name)
                        and function.id in fixture_aliases
                    ):
                        function.id = "fixture"
            modules[source] = tree
        return modules[source]

    def exported_fixtures(
        source: Path, visited: set[Path]
    ) -> dict[str, tuple[Path, ast.AST, bool]]:
        if source in visited:
            return {}
        visited = {*visited, source}
        exported = {}
        for binding in module(source).body:
            if not isinstance(binding, ast.ImportFrom):
                continue
            imported = _test_module_path(root, _import_module(source, root, binding))
            if imported is not None:
                inherited = exported_fixtures(imported, visited)
                for alias in binding.names:
                    if alias.name in inherited:
                        exported[alias.asname or alias.name] = inherited[alias.name]
        for node in ast.walk(module(source)):
            info = _fixture_info(node)
            if info is not None:
                exported[info[0]] = (source, node, info[1])
        return exported

    for source in sources:
        for name, fixture in exported_fixtures(source, set()).items():
            fixtures.setdefault(name, []).append(fixture)

    seen: set[tuple[Path, int]] = set()

    def inspect(source: Path, node: ast.AST) -> bool:
        key = (source, getattr(node, "lineno", 0))
        if key in seen:
            return False
        seen.add(key)
        if _mock_markers(ast.unparse(node)) or any(
            isinstance(item, ast.ClassDef)
            and re.match(r"(?:Fake|Mock|Stub|Scripted)", item.name)
            for item in ast.walk(node)
        ):
            return True
        for call in ast.walk(node):
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "getfixturevalue"
            ):
                if (
                    not call.args
                    or not isinstance(call.args[0], ast.Constant)
                    or not isinstance(call.args[0].value, str)
                ):
                    return True
                if inspect_fixture(call.args[0].value):
                    return True
        names = {
            item.id
            for item in ast.walk(node)
            if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load)
        }
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for argument in (
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
            ):
                if inspect_fixture(argument.arg, requester=(source, node)):
                    return True
        for binding in module(source).body:
            if binding is node:
                continue
            if (
                isinstance(
                    binding, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                )
                and binding.name in names
            ):
                if inspect(source, binding):
                    return True
            if isinstance(binding, (ast.Assign, ast.AnnAssign)):
                targets = (
                    binding.targets
                    if isinstance(binding, ast.Assign)
                    else [binding.target]
                )
                if any(
                    isinstance(target, ast.Name) and target.id in names
                    for target in targets
                ) and inspect(source, binding):
                    return True
            if not isinstance(binding, (ast.Import, ast.ImportFrom)):
                continue
            for alias in binding.names:
                imported_name = alias.asname or (
                    alias.name.split(".")[0]
                    if isinstance(binding, ast.Import)
                    else alias.name
                )
                if imported_name not in names:
                    continue
                imported_module = (
                    alias.name
                    if isinstance(binding, ast.Import)
                    else _import_module(source, root, binding)
                )
                if _mock_markers(imported_module):
                    return True
                imported = (
                    _test_module_path(root, f"{imported_module}.{alias.name}")
                    if isinstance(binding, ast.ImportFrom)
                    else None
                ) or _test_module_path(root, imported_module)
                if imported is not None:
                    selected = [
                        item
                        for item in module(imported).body
                        if getattr(item, "name", None) == alias.name
                    ]
                    if selected:
                        if any(inspect(imported, item) for item in selected):
                            return True
                    elif _mock_backed(root, imported):
                        return True
        return False

    def inspect_fixture(
        name: str, requester: tuple[Path, ast.AST] | None = None
    ) -> bool:
        candidates = fixtures.get(name, [])
        if requester is not None:
            for index, candidate in enumerate(candidates):
                if candidate[:2] == requester:
                    candidates = candidates[:index]
                    break
        return bool(candidates) and inspect(candidates[-1][0], candidates[-1][1])

    for name, candidates in fixtures.items():
        autouse = candidates[-1][2]
        if autouse and inspect_fixture(name):
            return True
    for node in ast.walk(module(path)):
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef)
        ) and node.name.startswith("test"):
            if inspect(path, node):
                return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "getfixturevalue":
                if (
                    not node.args
                    or not isinstance(node.args[0], ast.Constant)
                    or not isinstance(node.args[0].value, str)
                ):
                    return True
                if inspect_fixture(node.args[0].value):
                    return True
            if node.func.attr == "usefixtures":
                if any(
                    not isinstance(arg, ast.Constant)
                    or not isinstance(arg.value, str)
                    or inspect_fixture(arg.value)
                    for arg in node.args
                ):
                    return True
    return False


def _mock_backed(root: Path, path: Path, seen: set[Path] | None = None) -> bool:
    visited = set() if seen is None else seen
    if path in visited:
        return False
    visited.add(path)
    content = path.read_text(encoding="utf-8")
    tree = ast.parse(content)
    if any(_fixture_info(node) is not None for node in ast.walk(tree)):
        return _fixture_mock_backed(root, path)
    if _mock_markers(content):
        return True
    for node in ast.walk(ast.parse(content)):
        if isinstance(node, ast.ClassDef) and re.match(
            r"(?:Fake|Mock|Stub|Scripted)", node.name
        ):
            return True
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = _import_module(path, root, node)
            modules = [module, *(f"{module}.{alias.name}" for alias in node.names)]
        for module in modules:
            if module.startswith("tests."):
                imported = (root / module.replace(".", "/")).with_suffix(".py")
                if not imported.is_file():
                    imported = root / module.replace(".", "/") / "__init__.py"
                if imported.is_file() and _mock_backed(root, imported, visited):
                    return True
    return False


def _test_facts(
    root: Path, path: Path
) -> tuple[int, list[str], list[str], list[str], str]:
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
    direct_targets = sorted(targets)
    for match in PATH_LITERAL.finditer(content):
        candidate = match.group(0).rstrip(".,;:')\"")
        path_candidate = root / candidate
        if "*" not in candidate and path_candidate.exists():
            targets.add(candidate)
    evidence_basis = (
        "FIXTURE_OR_MOCK_BACKED"
        if _mock_backed(root, path) or _fixture_mock_backed(root, path)
        else "DIRECT_CONTRACT"
    )
    return (
        definition_count,
        sorted(symbols),
        sorted(targets),
        direct_targets,
        evidence_basis,
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
    classification_by_path: dict[str, str] = {}
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
            definition_count, symbols, targets, direct_targets, evidence_basis = (
                _test_facts(root, path)
            )
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            _error(errors, f"cannot inspect test reality: {relative}: {exc}")
            continue
        declared_classification = classification
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
        demoted = (
            classification == "CURRENT_DOMAIN_INVARIANT"
            and evidence_basis == "FIXTURE_OR_MOCK_BACKED"
        )
        if demoted:
            classification = "FIXTURE_PROTOCOL"
        classification_by_path[relative] = classification
        records.append(
            {
                "path": relative,
                "classification": classification,
                "declared_classification": declared_classification,
                "owner": owner,
                "capability": str(rule["capability"]),
                "production_targets": targets,
                "direct_production_targets": direct_targets,
                "tested_symbols": symbols,
                "qualification_role": (
                    "FIXTURE_CONTRACT_ONLY"
                    if demoted
                    else str(rule["qualification_role"])
                ),
                "proof_ceiling": "FIXTURE_ONLY"
                if demoted
                else str(rule["proof_ceiling"]),
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
            _error(
                errors, f"semantic slice contains unclassified test evidence: {name}"
            )
        if role not in SEMANTIC_SLICE_ROLES:
            _error(errors, f"semantic slice has unsupported reality role: {name}")
        if role == "CURRENT_BUSINESS_CAPABILITY" and not (
            classes & CURRENT_CLASSIFICATIONS
        ):
            _error(
                errors,
                f"current semantic slice has no current-behavior evidence: {name}",
            )
        if role == "CURRENT_BUSINESS_CAPABILITY":
            direct = [
                record
                for record in records
                if record["path"] in paths
                and record["classification"] in DIRECT_CLASSIFICATIONS
                and record["evidence_basis"] == "DIRECT_CONTRACT"
            ]
            if not direct:
                _error(
                    errors,
                    f"current semantic slice has no direct contract/runtime evidence: {name}",
                )
            required_targets = slice_policy.get("production_targets")
            if not isinstance(required_targets, list) or not required_targets:
                _error(
                    errors,
                    f"current semantic slice requires explicit production targets: {name}",
                )
                required_targets = []
            for target in required_targets:
                if not isinstance(target, str) or not (root / target).is_file():
                    _error(
                        errors,
                        f"semantic slice production target must be a concrete file: {name}:{target}",
                    )
                elif not any(
                    target in record["direct_production_targets"] for record in direct
                ):
                    _error(
                        errors,
                        f"semantic slice target lacks direct evidence: {name}:{target}",
                    )
        if role == "MIGRATION_COMPATIBILITY" and classes != {"MIGRATION_COMPATIBILITY"}:
            _error(
                errors,
                f"migration semantic slice contains non-migration evidence: {name}",
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
        "mocked_invariant_demotions": [
            record["path"]
            for record in records
            if record["declared_classification"] == "CURRENT_DOMAIN_INVARIANT"
            and record["classification"] == "FIXTURE_PROTOCOL"
        ],
        "mock_fixture_false_qualification_count": sum(
            "no direct contract/runtime evidence" in error
            or "target lacks direct evidence" in error
            for error in errors
        ),
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
