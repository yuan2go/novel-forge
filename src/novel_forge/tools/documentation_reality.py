"""INVARIANT: repository reality claims must resolve to executable evidence."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tokenize
from typing import Any, Iterable, Mapping

from novel_forge.tools.backend_qualification_contract import (
    P0_EVIDENCE_CEILINGS,
    REQUIRED_GATE_ORDER,
)
from novel_forge.tools.implementation_tree_identity import (
    build_implementation_tree_identity,
)

SCHEMA_VERSION = "novel-forge.reality-evidence.v2"
REPORT_SCHEMA_VERSION = "novel-forge.documentation-reality-check.v1"
AUTHORITY_ORDER = [
    "executable_code",
    "schema_and_migrations",
    "runtime_wiring",
    "tests",
]
STATUS_VOCABULARY = [
    "CODE_EXISTS",
    "WIRED",
    "EXECUTABLE",
    "QUALIFIED",
    "PRODUCTION_PROVEN",
]
CANONICAL_DOCUMENTS = [
    "README.md",
    "docs/README.md",
    "docs/current-system.md",
    "docs/runtime-operations.md",
    "docs/development.md",
]
DOCSTRING_PREFIXES = (
    "INVARIANT:",
    "CONSTRAINT:",
    "SECURITY:",
    "COMPATIBILITY:",
)
HISTORICAL_OR_SPECULATIVE = re.compile(
    r"(?:\b(?:TODO|FIXME|HACK|XXX)\b|\bWP-[A-Z0-9_-]+\b|"
    r"\bwork[ -]package\b|\bpull request\b|\bPR\s*#\d+\b|"
    r"\bADR(?:s)?\b|\bblueprint\b|\broadmap\b|\beventually\b|"
    r"\bfuture architecture\b|\btemporary architecture\b|docs/new/)",
    re.IGNORECASE,
)
CONCEPT_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
INLINE_CODE = re.compile(r"`([^`\n]+)`")
WEB_COMMENT = re.compile(r"^\s*(?://|/\*|\*|<!--)\s?(.*)$")
FULL_SHA = re.compile(r"[0-9a-f]{40}")
CONTENT_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
P0_EVIDENCE_CLASS = "p0_backend_engineering_qualification"
P0_COLLECTIONS = (
    "BACKEND_NON_POSTGRESQL",
    "MIGRATION_COMPATIBILITY",
    "POSTGRESQL_REQUIRED",
)


def _error(errors: list[str], message: str) -> None:
    if message not in errors:
        errors.append(message)


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _inside_root(root: Path, relative: str, errors: list[str]) -> Path | None:
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        _error(errors, f"evidence path escapes repository: {relative}")
        return None
    return path


def _load_python(path: Path, errors: list[str], root: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        _error(errors, f"cannot parse Python evidence {_relative(root, path)}: {exc}")
        return None


def _symbol_exists(tree: ast.Module, qualified_name: str) -> bool:
    parts = qualified_name.split(".")
    if not parts or any(not part for part in parts):
        return False
    current: Iterable[ast.stmt] = tree.body
    for index, part in enumerate(parts):
        match = next(
            (
                node
                for node in current
                if isinstance(
                    node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                )
                and node.name == part
            ),
            None,
        )
        if match is None:
            return False
        if index < len(parts) - 1:
            if not isinstance(match, ast.ClassDef):
                return False
            current = match.body
    return True


def _validate_reference(
    root: Path,
    reference: object,
    errors: list[str],
    *,
    context: str,
) -> None:
    if not isinstance(reference, Mapping):
        _error(errors, f"{context} evidence reference must be an object")
        return
    relative = str(reference.get("path") or "").strip()
    if not relative:
        _error(errors, f"{context} evidence reference is missing path")
        return
    path = _inside_root(root, relative, errors)
    if path is None:
        return
    if not path.is_file():
        _error(errors, f"{context} evidence path does not exist: {relative}")
        return
    symbol = str(reference.get("symbol") or "").strip()
    locator = str(reference.get("locator") or "")
    if symbol:
        if path.suffix != ".py":
            _error(
                errors, f"{context} symbol reference is not Python: {relative}:{symbol}"
            )
            return
        tree = _load_python(path, errors, root)
        if tree is not None and not _symbol_exists(tree, symbol):
            _error(errors, f"{context} symbol does not exist: {relative}:{symbol}")
    elif locator:
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            _error(errors, f"cannot read {context} evidence {relative}: {exc}")
            return
        if locator not in content:
            _error(errors, f"{context} locator does not exist: {relative}:{locator}")
    else:
        _error(errors, f"{context} evidence requires symbol or locator: {relative}")


def _reference_key(reference: object) -> tuple[str, str, str] | None:
    if not isinstance(reference, Mapping):
        return None
    return (
        str(reference.get("path") or "").strip(),
        str(reference.get("symbol") or "").strip(),
        str(reference.get("locator") or ""),
    )


def _validate_reference_list(
    root: Path,
    payload: Mapping[str, Any],
    field: str,
    errors: list[str],
    *,
    context: str,
    required: bool,
) -> list[object]:
    value = payload.get(field)
    if not isinstance(value, list):
        _error(errors, f"{context}.{field} must be a list")
        return []
    if required and not value:
        _error(errors, f"{context}.{field} must not be empty")
    for reference in value:
        _validate_reference(root, reference, errors, context=f"{context}.{field}")
    return value


def _validate_migrations(
    root: Path,
    capability: Mapping[str, Any],
    errors: list[str],
    *,
    context: str,
) -> list[str]:
    value = capability.get("migrations")
    if not isinstance(value, list):
        _error(errors, f"{context}.migrations must be a list")
        return []
    migration_ids: list[str] = []
    for index, migration in enumerate(value):
        migration_context = f"{context}.migrations[{index}]"
        if not isinstance(migration, Mapping):
            _error(errors, f"{migration_context} must be an object")
            continue
        migration_id = str(migration.get("id") or "").strip()
        if not migration_id:
            _error(errors, f"{migration_context} is missing id")
        else:
            migration_ids.append(migration_id)
        _validate_reference(root, migration, errors, context=migration_context)
    return migration_ids


def _is_nonnegative_integer(value: object) -> bool:
    return type(value) is int and value >= 0


def _validate_p0_run_projection(
    run: Mapping[str, Any],
    errors: list[str],
    *,
    context: str,
    migration_head: str,
) -> bool:
    initial_error_count = len(errors)
    observed_at_sha = str(run.get("observed_at_sha") or "")
    if not FULL_SHA.fullmatch(str(run.get("source_tree") or "")):
        _error(errors, f"{context}.source_tree must be a full Git tree SHA")
    for field in ("dependency_snapshot_digest",):
        if not CONTENT_DIGEST.fullmatch(str(run.get(field) or "")):
            _error(errors, f"{context}.{field} must be a SHA-256 digest")

    artifact = run.get("qualification_report")
    qualification_run_id = ""
    if not isinstance(artifact, Mapping):
        _error(errors, f"{context}.qualification_report must be an object")
    else:
        qualification_run_id = str(artifact.get("run_id") or "")
        token = qualification_run_id.removeprefix("p0-")
        if not re.fullmatch(r"p0-[0-9a-f]{32}", qualification_run_id):
            _error(errors, f"{context}.qualification_report.run_id is invalid")
        expected_root = f"novel-forge-p0-{observed_at_sha[:12]}-{token}"
        if artifact.get("artifact_root") != expected_root:
            _error(
                errors,
                f"{context}.qualification_report.artifact_root differs from the run identity",
            )
        expected_report = f"p0-backend-qualification-{observed_at_sha}.json"
        if artifact.get("artifact") != expected_report:
            _error(
                errors,
                f"{context}.qualification_report.artifact differs from the observed SHA",
            )
        if not CONTENT_DIGEST.fullmatch(str(artifact.get("sha256") or "")):
            _error(
                errors,
                f"{context}.qualification_report.sha256 must be a SHA-256 digest",
            )
        if artifact.get("retention") != "EXTERNAL_QUALIFICATION_ARTIFACT":
            _error(
                errors,
                f"{context}.qualification_report.retention is not explicit",
            )

    collections = run.get("collections")
    collections_by_class: dict[str, Mapping[str, Any]] = {}
    if not isinstance(collections, list):
        _error(errors, f"{context}.collections must be a list")
    else:
        for index, collection in enumerate(collections):
            collection_context = f"{context}.collections[{index}]"
            if not isinstance(collection, Mapping):
                _error(errors, f"{collection_context} must be an object")
                continue
            classification = str(collection.get("classification") or "")
            if classification in collections_by_class:
                _error(errors, f"{context} duplicates collection {classification}")
            collections_by_class[classification] = collection
            for field in ("collected_nodes", "junit_cases", "passed", "skipped"):
                if not _is_nonnegative_integer(collection.get(field)):
                    _error(
                        errors,
                        f"{collection_context}.{field} must be a non-negative integer",
                    )
            if collection.get("complete") is not True:
                _error(errors, f"{collection_context} is not a complete collection")
            if collection.get("skipped") != 0:
                _error(errors, f"{collection_context} contains skipped cases")
            if collection.get("passed") != collection.get("junit_cases"):
                _error(errors, f"{collection_context} is not an all-passing collection")
            if (
                _is_nonnegative_integer(collection.get("junit_cases"))
                and _is_nonnegative_integer(collection.get("collected_nodes"))
                and collection["junit_cases"] < collection["collected_nodes"]
            ):
                _error(errors, f"{collection_context} has fewer JUnit cases than nodes")
        if tuple(collections_by_class) != P0_COLLECTIONS:
            _error(errors, f"{context}.collections differ from the canonical P0 classes")
        migration_collection = collections_by_class.get("MIGRATION_COMPATIBILITY")
        if (
            migration_collection is not None
            and migration_collection.get("repeated_in_postgresql_collection") is not True
        ):
            _error(errors, f"{context} does not mark the repeated migration matrix")
        unique_classes = ("BACKEND_NON_POSTGRESQL", "POSTGRESQL_REQUIRED")
        if all(
            classification in collections_by_class
            and _is_nonnegative_integer(
                collections_by_class[classification].get("junit_cases")
            )
            for classification in unique_classes
        ):
            unique_total = sum(
                int(collections_by_class[classification]["junit_cases"])
                for classification in unique_classes
            )
            if run.get("collected") != unique_total or run.get("passed") != unique_total:
                _error(errors, f"{context} aggregate counts duplicate or omit cases")
    if run.get("result_count_scope") != "UNIQUE_COMPLETE_COLLECTION_JUNIT_CASES":
        _error(errors, f"{context}.result_count_scope is not canonical")

    gates = run.get("gates")
    if not isinstance(gates, list):
        _error(errors, f"{context}.gates must be a list")
    else:
        gate_ids = [
            str(gate.get("id") or "") if isinstance(gate, Mapping) else ""
            for gate in gates
        ]
        if tuple(gate_ids) != REQUIRED_GATE_ORDER:
            _error(errors, f"{context}.gates differ from the canonical P0 order")
        if any(
            not isinstance(gate, Mapping) or gate.get("status") != "PASS"
            for gate in gates
        ):
            _error(errors, f"{context}.gates contain a non-passing result")

    migration = run.get("migration")
    if not isinstance(migration, Mapping):
        _error(errors, f"{context}.migration must be an object")
    elif (
        migration.get("expected_head") != migration_head
        or migration.get("observed_head") != migration_head
        or not _is_nonnegative_integer(migration.get("applied_count"))
        or migration.get("applied_count") < 1
    ):
        _error(errors, f"{context}.migration does not prove the inventory head")

    cleanup = run.get("cleanup")
    if not isinstance(cleanup, Mapping):
        _error(errors, f"{context}.cleanup must be an object")
    else:
        token = qualification_run_id.removeprefix("p0-")
        expected_phases = (
            ("postgresql", f"nf-p0-{token}"),
            ("compose-runtime", f"nf-p0-{token}-runtime"),
        )
        phases = cleanup.get("phases")
        phase_resource_count = 0
        valid_phases = isinstance(phases, list) and len(phases) == len(
            expected_phases
        )
        if valid_phases:
            for phase, (expected_phase, expected_project) in zip(
                phases, expected_phases, strict=True
            ):
                if (
                    not isinstance(phase, Mapping)
                    or phase.get("phase") != expected_phase
                    or phase.get("status") != "PASS"
                    or not _is_nonnegative_integer(phase.get("resource_count"))
                    or phase.get("resource_count") < 1
                    or not _is_nonnegative_integer(
                        phase.get("remaining_resource_count")
                    )
                    or phase.get("remaining_resource_count") != 0
                    or phase.get("run_id") != qualification_run_id
                    or phase.get("compose_project") != expected_project
                    or phase.get("receipt")
                    != f"compose-resource-ownership-{expected_project}.json"
                ):
                    valid_phases = False
                    break
                phase_resource_count += int(phase["resource_count"])
        if (
            cleanup.get("status") != "PASS"
            or not _is_nonnegative_integer(cleanup.get("remaining_resource_count"))
            or cleanup.get("remaining_resource_count") != 0
            or not _is_nonnegative_integer(cleanup.get("owned_resource_count"))
            or cleanup.get("owned_resource_count") != phase_resource_count
            or not valid_phases
        ):
            _error(errors, f"{context}.cleanup is not zero-residue receipt-bound PASS")
    if run.get("evidence_ceilings") != P0_EVIDENCE_CEILINGS:
        _error(errors, f"{context}.evidence_ceilings differ from P0 policy")
    return len(errors) == initial_error_count


def _validate_inventory(root: Path, inventory: object, errors: list[str]) -> int:
    if not isinstance(inventory, Mapping):
        _error(errors, "reality inventory must be a JSON object")
        return 0
    if inventory.get("schema_version") != SCHEMA_VERSION:
        _error(errors, f"reality inventory schema_version must be {SCHEMA_VERSION}")
    if inventory.get("authority_order") != AUTHORITY_ORDER:
        _error(errors, "reality inventory authority_order is not canonical")
    if inventory.get("status_vocabulary") != STATUS_VOCABULARY:
        _error(errors, "reality inventory status_vocabulary is not canonical")
    if inventory.get("canonical_documents") != CANONICAL_DOCUMENTS:
        _error(errors, "reality inventory canonical_documents is not canonical")

    migration_head = str(inventory.get("migration_head") or "").strip()
    if not migration_head:
        _error(errors, "reality inventory migration_head is missing")

    current_tree_sha = str(
        build_implementation_tree_identity(root).get("implementation_tree_sha") or ""
    )
    qualification_runs = inventory.get("qualification_runs")
    runs_by_id: dict[str, Mapping[str, Any]] = {}
    run_results: dict[str, tuple[int, int, int]] = {}
    run_evidence: dict[str, set[tuple[str, str, str]]] = {}
    run_classes: dict[str, str] = {}
    if not isinstance(qualification_runs, list) or not qualification_runs:
        _error(errors, "reality inventory qualification_runs must be a non-empty list")
    else:
        for index, run in enumerate(qualification_runs):
            context = f"qualification_runs[{index}]"
            if not isinstance(run, Mapping):
                _error(errors, f"{context} must be an object")
                continue
            run_error_count = len(errors)
            run_id = str(run.get("id") or "").strip()
            if not CONCEPT_NAME.fullmatch(run_id):
                _error(errors, f"{context}.id must be lowercase kebab-case")
            elif run_id in runs_by_id:
                _error(errors, f"duplicate qualification run id: {run_id}")
            else:
                runs_by_id[run_id] = run
            evidence_class = str(run.get("evidence_class") or "").strip()
            if evidence_class not in {
                P0_EVIDENCE_CLASS,
                "focused_qualification_contracts",
            }:
                _error(errors, f"{context}.evidence_class is not recognized")
            elif run_id in runs_by_id and runs_by_id[run_id] is run:
                run_classes[run_id] = evidence_class
            if not str(run.get("gate") or "").strip():
                _error(errors, f"{context}.gate is missing")
            observed_at_sha = str(run.get("observed_at_sha") or "").strip()
            if not re.fullmatch(r"[0-9a-f]{40}", observed_at_sha):
                _error(errors, f"{context}.observed_at_sha must be a full Git SHA")
            counts = [run.get(field) for field in ("collected", "passed", "failed")]
            valid_counts = not any(
                type(value) is not int or value < 0 for value in counts
            )
            counts_match = valid_counts and counts[1] + counts[2] == counts[0]
            if not valid_counts:
                _error(errors, f"{context} result counts must be non-negative integers")
            elif not counts_match:
                _error(errors, f"{context} passed plus failed must equal collected")
            if counts_match and counts[2] == 0:
                implementation_tree_sha = str(
                    run.get("implementation_tree_sha") or ""
                ).strip()
                if not re.fullmatch(r"sha256:[0-9a-f]{64}", implementation_tree_sha):
                    _error(
                        errors,
                        f"{context}.implementation_tree_sha must be a SHA-256 digest",
                    )
                elif implementation_tree_sha != current_tree_sha:
                    _error(
                        errors,
                        f"{context} does not qualify the current implementation tree",
                    )
                evidence = _validate_reference_list(
                    root,
                    run,
                    "qualification_evidence",
                    errors,
                    context=context,
                    required=True,
                )
                if evidence_class == P0_EVIDENCE_CLASS:
                    _validate_p0_run_projection(
                        run,
                        errors,
                        context=context,
                        migration_head=migration_head,
                    )
                if (
                    len(errors) == run_error_count
                    and run_id in runs_by_id
                    and runs_by_id[run_id] is run
                ):
                    run_results[run_id] = (counts[0], counts[1], counts[2])
                    run_evidence[run_id] = {
                        key
                        for item in evidence
                        if (key := _reference_key(item)) is not None
                    }
            elif (
                counts_match
                and run_id in runs_by_id
                and runs_by_id[run_id] is run
                and evidence_class in {
                    P0_EVIDENCE_CLASS,
                    "focused_qualification_contracts",
                }
            ):
                run_results[run_id] = (counts[0], counts[1], counts[2])

    capabilities = inventory.get("capabilities")
    if not isinstance(capabilities, list):
        _error(errors, "reality inventory capabilities must be a list")
        return 0
    if not capabilities:
        _error(errors, "reality inventory capabilities must not be empty")

    concepts: set[str] = set()
    cited_migrations: set[str] = set()
    for index, capability in enumerate(capabilities):
        context = f"capabilities[{index}]"
        if not isinstance(capability, Mapping):
            _error(errors, f"{context} must be an object")
            continue
        concept = str(capability.get("concept") or "").strip()
        if not CONCEPT_NAME.fullmatch(concept):
            _error(errors, f"{context}.concept must be lowercase kebab-case")
        elif concept in concepts:
            _error(errors, f"duplicate capability concept: {concept}")
        concepts.add(concept)
        if not str(capability.get("owner") or "").strip():
            _error(errors, f"{context}.owner is missing")
        status = str(capability.get("status") or "").strip()
        if status not in STATUS_VOCABULARY:
            _error(errors, f"{context}.status is not recognized: {status}")
        if not str(capability.get("proof_ceiling") or "").strip():
            _error(errors, f"{context}.proof_ceiling is missing")

        _validate_reference_list(
            root, capability, "implementation", errors, context=context, required=True
        )
        _validate_reference_list(
            root,
            capability,
            "runtime_entries",
            errors,
            context=context,
            required=status in STATUS_VOCABULARY[1:],
        )
        _validate_reference_list(
            root, capability, "persistence", errors, context=context, required=True
        )
        cited_migrations.update(
            _validate_migrations(root, capability, errors, context=context)
        )
        qualification = _validate_reference_list(
            root,
            capability,
            "qualification",
            errors,
            context=context,
            required=status in ("QUALIFIED", "PRODUCTION_PROVEN"),
        )
        if status in ("QUALIFIED", "PRODUCTION_PROVEN") and not qualification:
            _error(
                errors, f"{context} cannot be {status} without qualification evidence"
            )
        qualification_run_ids = capability.get("qualification_run_ids", [])
        if not isinstance(qualification_run_ids, list):
            _error(errors, f"{context}.qualification_run_ids must be a list")
            qualification_run_ids = []
        if status in ("QUALIFIED", "PRODUCTION_PROVEN"):
            if not qualification_run_ids:
                _error(
                    errors,
                    f"{context} cannot be {status} without a passing qualification run",
                )
            qualification_keys = {
                key
                for item in qualification
                if (key := _reference_key(item)) is not None
            }
            for run_id in qualification_run_ids:
                run = runs_by_id.get(str(run_id))
                if run is None:
                    _error(errors, f"{context} references unknown run: {run_id}")
                    continue
                if run_classes.get(str(run_id)) != P0_EVIDENCE_CLASS:
                    _error(
                        errors,
                        f"{context} references a run below the P0 qualification class: {run_id}",
                    )
                    continue
                result_counts = run_results.get(str(run_id))
                if result_counts is None:
                    _error(
                        errors,
                        f"{context} references a run with invalid results: {run_id}",
                    )
                    continue
                _, passed, failed = result_counts
                if failed != 0 or passed < 1:
                    _error(errors, f"{context} references a non-passing run: {run_id}")
                    continue
                missing_qualification = qualification_keys - run_evidence.get(
                    str(run_id), set()
                )
                if missing_qualification:
                    _error(
                        errors,
                        f"{context} qualification evidence is not covered by run: {run_id}",
                    )
        if status == "PRODUCTION_PROVEN":
            production_evidence = _validate_reference_list(
                root,
                capability,
                "production_evidence",
                errors,
                context=context,
                required=True,
            )
            if not production_evidence:
                _error(
                    errors,
                    f"{context} cannot be PRODUCTION_PROVEN without live evidence",
                )

    qualification_failures = inventory.get("qualification_failures")
    if not isinstance(qualification_failures, list):
        _error(errors, "reality inventory qualification_failures must be a list")
    else:
        failure_ids: set[str] = set()
        for index, failure in enumerate(qualification_failures):
            context = f"qualification_failures[{index}]"
            if not isinstance(failure, Mapping):
                _error(errors, f"{context} must be an object")
                continue
            failure_id = str(failure.get("id") or "").strip()
            if not CONCEPT_NAME.fullmatch(failure_id):
                _error(errors, f"{context}.id must be lowercase kebab-case")
            elif failure_id in failure_ids:
                _error(errors, f"duplicate qualification failure id: {failure_id}")
            failure_ids.add(failure_id)
            if not str(failure.get("scope") or "").strip():
                _error(errors, f"{context}.scope is missing")
            if not str(failure.get("gate") or "").strip():
                _error(errors, f"{context}.gate is missing")
            observed_at_sha = str(failure.get("observed_at_sha") or "").strip()
            if not re.fullmatch(r"[0-9a-f]{40}", observed_at_sha):
                _error(errors, f"{context}.observed_at_sha must be a full Git SHA")
            failed_test_count = failure.get("failed_test_count")
            if not isinstance(failed_test_count, int) or failed_test_count < 1:
                _error(errors, f"{context}.failed_test_count must be positive")
            affected = failure.get("affected_capabilities")
            if not isinstance(affected, list):
                _error(errors, f"{context}.affected_capabilities must be a list")
            else:
                for concept in affected:
                    if concept not in concepts:
                        _error(
                            errors,
                            f"{context} references unknown capability: {concept}",
                        )
            _validate_reference_list(
                root, failure, "evidence", errors, context=context, required=True
            )

    if migration_head not in cited_migrations:
        _error(errors, "reality inventory migration_head has no migration evidence")

    manifest_path = root / "architecture/manifests/migration-manifest.yaml"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            _error(errors, f"cannot parse migration manifest: {exc}")
        else:
            if manifest.get("head") != migration_head:
                _error(
                    errors,
                    "reality inventory migration_head differs from migration manifest",
                )
            if migration_head not in manifest.get("migration_ids", []):
                _error(
                    errors,
                    "reality inventory migration_head is absent from migration registry",
                )

    boundaries = inventory.get("negative_boundaries")
    if not isinstance(boundaries, list):
        _error(errors, "reality inventory negative_boundaries must be a list")
    else:
        for index, boundary in enumerate(boundaries):
            context = f"negative_boundaries[{index}]"
            if not isinstance(boundary, Mapping):
                _error(errors, f"{context} must be an object")
                continue
            if not str(boundary.get("claim") or "").strip():
                _error(errors, f"{context}.claim is missing")
            if "value" not in boundary:
                _error(errors, f"{context}.value is missing")
            _validate_reference_list(
                root, boundary, "evidence", errors, context=context, required=True
            )
    return len(capabilities)


def _validate_canonical_documents(root: Path, errors: list[str]) -> None:
    for relative in CANONICAL_DOCUMENTS:
        if not (root / relative).is_file():
            _error(errors, f"canonical documentation file is missing: {relative}")
    docs_root = root / "docs"
    if docs_root.is_dir():
        allowed = set(CANONICAL_DOCUMENTS)
        for path in sorted(item for item in docs_root.rglob("*") if item.is_file()):
            relative = _relative(root, path)
            if relative not in allowed:
                _error(errors, f"non-canonical documentation file: {relative}")
    readme = root / "README.md"
    if readme.is_file():
        try:
            line_count = len(readme.read_text(encoding="utf-8").splitlines())
        except (OSError, UnicodeDecodeError) as exc:
            _error(errors, f"cannot read README.md: {exc}")
        else:
            if line_count > 80:
                _error(errors, f"README.md must remain thin; found {line_count} lines")


def _path_from_inline_code(value: str) -> str | None:
    token = value.strip().rstrip(".,;:")
    if not token or "\n" in token or " " in token:
        return None
    if token.startswith(("http://", "https://", "/")):
        return None
    if ".py:" in token:
        token = token.split(":", 1)[0]
    if "/" not in token and token not in {
        "README.md",
        "AGENTS.md",
        "CLAUDE.md",
        "Makefile",
        "pyproject.toml",
        "compose.yml",
        ".env.example",
    }:
        return None
    return token


def _validate_document_paths(root: Path, errors: list[str]) -> None:
    for relative in CANONICAL_DOCUMENTS:
        path = root / relative
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in INLINE_CODE.finditer(content):
            candidate = _path_from_inline_code(match.group(1))
            if candidate is None:
                continue
            target = _inside_root(root, candidate, errors)
            if target is not None and not target.exists():
                _error(
                    errors,
                    f"canonical document references missing path: {relative}:{candidate}",
                )


def _docstring_nodes(
    tree: ast.Module,
) -> Iterable[tuple[ast.AST, str, str]]:
    module_docstring = ast.get_docstring(tree, clean=False)
    if module_docstring is not None:
        yield tree, "<module>", module_docstring

    def walk(node: ast.AST, prefix: str = "") -> Iterable[tuple[ast.AST, str, str]]:
        for child in getattr(node, "body", []):
            if not isinstance(
                child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue
            qualified_name = f"{prefix}.{child.name}" if prefix else child.name
            docstring = ast.get_docstring(child, clean=False)
            if docstring is not None:
                yield child, qualified_name, docstring
            yield from walk(child, qualified_name)

    yield from walk(tree)


def _validate_python_comments(
    root: Path, errors: list[str]
) -> tuple[int, set[str], int]:
    source_root = root / "src"
    comment_count = 0
    module_docstrings: set[str] = set()
    docstring_count = 0
    if not source_root.is_dir():
        return comment_count, module_docstrings, docstring_count
    for path in sorted(source_root.rglob("*.py")):
        relative = _relative(root, path)
        try:
            with path.open("rb") as handle:
                tokens = list(tokenize.tokenize(handle.readline))
        except (OSError, SyntaxError, tokenize.TokenError) as exc:
            _error(errors, f"cannot tokenize {relative}: {exc}")
            continue
        for token in tokens:
            if token.type != tokenize.COMMENT:
                continue
            comment_count += 1
            if HISTORICAL_OR_SPECULATIVE.search(token.string):
                _error(
                    errors,
                    f"historical or speculative comment: {relative}:{token.start[0]}",
                )
        tree = _load_python(path, errors, root)
        if tree is None:
            continue
        for node, _, docstring in _docstring_nodes(tree):
            docstring_count += 1
            if HISTORICAL_OR_SPECULATIVE.search(docstring):
                line = getattr(node, "lineno", 1)
                _error(
                    errors,
                    f"historical or speculative comment: {relative}:{line}",
                )
            if isinstance(node, ast.Module):
                module_docstrings.add(relative)
            if not docstring.lstrip().startswith(DOCSTRING_PREFIXES):
                line = getattr(node, "lineno", 1)
                _error(
                    errors,
                    f"docstring must explain an invariant: {relative}:{line}",
                )
    return comment_count, module_docstrings, docstring_count


def _validate_web_comments(root: Path, errors: list[str]) -> None:
    web_root = root / "web"
    if not web_root.is_dir():
        return
    for suffix in ("*.js", "*.mjs", "*.ts", "*.tsx"):
        for path in sorted(web_root.rglob(suffix)):
            if any(part in {"node_modules", ".next"} for part in path.parts):
                continue
            relative = _relative(root, path)
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError) as exc:
                _error(errors, f"cannot read web source {relative}: {exc}")
                continue
            for line_number, line in enumerate(lines, start=1):
                match = WEB_COMMENT.match(line)
                if match and HISTORICAL_OR_SPECULATIVE.search(match.group(1)):
                    _error(
                        errors,
                        f"historical or speculative comment: {relative}:{line_number}",
                    )


def _git_head(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip().lower()


def check_repository(root: str | Path, *, expected_sha: str = "") -> dict[str, Any]:
    repository = Path(root).resolve()
    errors: list[str] = []
    _validate_canonical_documents(repository, errors)
    _validate_document_paths(repository, errors)

    inventory_path = repository / "architecture/reality-evidence.json"
    inventory_bytes = b""
    inventory: object = {}
    if not inventory_path.is_file():
        _error(
            errors, "reality inventory is missing: architecture/reality-evidence.json"
        )
    else:
        try:
            inventory_bytes = inventory_path.read_bytes()
            inventory = json.loads(inventory_bytes.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            _error(errors, f"cannot parse reality inventory: {exc}")
    capability_count = _validate_inventory(repository, inventory, errors)
    comment_count, module_docstrings, docstring_count = _validate_python_comments(
        repository, errors
    )
    _validate_web_comments(repository, errors)
    comment_policy = (
        inventory.get("comment_policy") if isinstance(inventory, Mapping) else None
    )
    if not isinstance(comment_policy, Mapping):
        _error(errors, "reality inventory comment_policy must be an object")
    else:
        for field, actual in (
            ("max_source_comments", comment_count),
            ("max_source_docstrings", docstring_count),
        ):
            limit = comment_policy.get(field)
            if not isinstance(limit, int) or limit < 0:
                _error(errors, f"comment_policy.{field} must be a non-negative integer")
            elif actual > limit:
                _error(errors, f"comment_policy.{field} exceeded: {actual} > {limit}")
        allowed_module_docstrings = comment_policy.get("allowed_module_docstrings")
        if not isinstance(allowed_module_docstrings, list) or any(
            not isinstance(path, str) or not path.strip()
            for path in allowed_module_docstrings or []
        ):
            _error(
                errors,
                "comment_policy.allowed_module_docstrings must be a list of paths",
            )
        else:
            allowed = set(allowed_module_docstrings)
            if len(allowed) != len(allowed_module_docstrings):
                _error(
                    errors, "comment_policy.allowed_module_docstrings has duplicates"
                )
            for relative in sorted(module_docstrings - allowed):
                _error(errors, f"module docstring is not allowlisted: {relative}")
            for relative in sorted(allowed - module_docstrings):
                _error(errors, f"allowlisted module docstring is missing: {relative}")

    tested_sha = _git_head(repository)
    normalized_expected_sha = expected_sha.strip().lower()
    if normalized_expected_sha and tested_sha != normalized_expected_sha:
        _error(
            errors,
            f"tested SHA mismatch: expected {normalized_expected_sha}, found {tested_sha or 'none'}",
        )
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "evidence_class": "reality_inventory",
        "status": "FAIL" if errors else "PASS",
        "tested_sha": tested_sha or normalized_expected_sha,
        "inventory_sha256": "sha256:" + hashlib.sha256(inventory_bytes).hexdigest(),
        "canonical_document_count": len(CANONICAL_DOCUMENTS),
        "capability_count": capability_count,
        "source_comment_count": comment_count,
        "module_docstring_count": len(module_docstrings),
        "source_docstring_count": docstring_count,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify canonical documentation against repository reality."
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--expected-sha", default="")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = check_repository(args.repo_root, expected_sha=args.expected_sha)
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
