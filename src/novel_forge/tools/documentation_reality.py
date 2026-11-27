"""INVARIANT: repository reality claims must resolve to executable evidence."""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tokenize
from typing import Any, Iterable, Mapping

from novel_forge.tools.backend_qualification_contract import (
    P0_PROOF_SCOPE,
    REQUIRED_GATE_ORDER,
)
from novel_forge.tools.implementation_tree_identity import (
    build_git_implementation_tree_identity,
    build_implementation_tree_identity,
)

SCHEMA_VERSION = "novel-forge.reality-evidence.v4"
REPORT_SCHEMA_VERSION = "novel-forge.documentation-reality-check.v1"
PROJECTION_KIND = "CURRENT_CODE_REALITY_PROJECTION"
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
COMMENT_PREFIXES = (
    "WHY:",
    "INVARIANT:",
    "CONSTRAINT:",
    "WORKAROUND:",
    "SECURITY:",
    "COMPATIBILITY:",
)
COMMENT_RATCHET = "GIT_MERGE_BASE_NONINCREASING"
COMMENT_POLICY_SCOPE = "ALL_NON_MIGRATION_PRODUCTION_COMMENTS"
TOOLING_COMMENT = re.compile(
    r"^(?:#!|#\s*(?:type:\s*ignore|noqa\b|pragma:\s*no cover|nosec\b|"
    r"fmt:|ruff:|pyright:|mypy:|coding[:=]))",
    re.IGNORECASE,
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
WEB_TOOLING_COMMENT = re.compile(r"^\s*(?:/\*\*\s*@type|///\s*<reference)")
FULL_SHA = re.compile(r"[0-9a-f]{40}")
CONTENT_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
MIGRATION_ID_IN_PROSE = re.compile(r"\b20[0-9]{6}_[0-9]{4}_[a-z0-9_]+\b")
P0_EVIDENCE_CLASS = "p0_backend_engineering_qualification"
P0_COLLECTIONS = (
    "BACKEND_NON_POSTGRESQL",
    "MIGRATION_COMPATIBILITY",
    "POSTGRESQL_REQUIRED",
)
FACT_TYPE_POLICY = {
    "current_runtime": "CURRENT_RUNTIME_FACT",
    "current_qualification": "CURRENT_QUALIFICATION_EVIDENCE",
    "historical_compatibility": "HISTORICAL_COMPATIBILITY_FACT",
    "product_narrative_roadmap": "NOT_REPOSITORY_AUTHORITY",
}
CAPABILITY_REFERENCE_FIELDS = (
    "production_entries",
    "application",
    "domain_symbols",
    "commands_operations",
    "mutation_boundary",
    "persistence",
    "tests",
)
EXTERNAL_EFFECT_MODES = frozenset({"NONE", "INDIRECT", "DIRECT"})
SEMANTIC_CONSTRAINT_CLASSES = frozenset(
    {
        "CURRENT_PROVEN_INVARIANT",
        "CURRENT_RUNTIME_FACT",
        "CONFIGURABLE_POLICY",
        "HISTORICAL_COMPATIBILITY",
        "UNRESOLVED_DESIGN_CONSTRAINT",
    }
)
SYSTEM_ROLES = frozenset(
    {
        "AUTHORITY",
        "PROJECTION",
        "COORDINATOR",
        "REPOSITORY",
        "EVIDENCE",
        "CANDIDATE",
        "ACCEPTED_FACT",
    }
)
NARRATIVE_NATURES = frozenset(
    {
        "CONTAINER",
        "TRAJECTORY",
        "PLAN",
        "PROPOSAL",
        "CANDIDATE",
        "ACCEPTED_ACTUAL",
        "PROJECTION",
        "EVIDENCE",
        "EXECUTION_CONTRACT",
    }
)
NARRATIVE_RELATION_TYPES = frozenset(
    {
        "STRUCTURAL_CONTAINMENT",
        "CAUSAL_DEPENDENCY",
        "TEMPORAL_TRAJECTORY",
        "PLANNING_DEPENDENCY",
        "EXECUTION_DEPENDENCY",
        "ACCEPTED_FACT_PROJECTION",
    }
)
NARRATIVE_DISPOSITIONS = frozenset(
    {"KEEP", "MERGE", "SPLIT", "RENAME", "DEMOTE", "RETIRE", "ADD"}
)
RUNTIME_CHAIN_ROLES = frozenset(
    {
        "REQUIRED",
        "OPTIONAL_INPUT",
        "CONDITIONAL",
        "ASYNCHRONOUS_FOLLOWUP",
        "FUTURE_ONLY_CHANGE",
    }
)
BOUNDARY_CLASSES = frozenset(
    {
        "MISSING_CAPABILITY",
        "FIXTURE_ONLY_SEAM",
        "PARALLEL_TRUTH_RISK",
        "MISSING_AUTHORITY_TRANSITION",
        "UNSUPPORTED_CAPABILITY_CLAIM",
        "PROOF_BOUNDARY",
    }
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


def _validate_text_list(
    payload: Mapping[str, Any],
    field: str,
    errors: list[str],
    *,
    context: str,
    required: bool,
    allowed: frozenset[str] | None = None,
) -> list[str]:
    value = payload.get(field)
    if not isinstance(value, list):
        _error(errors, f"{context}.{field} must be a list")
        return []
    normalized = [str(item).strip() for item in value]
    if required and not normalized:
        _error(errors, f"{context}.{field} must not be empty")
    if any(not item for item in normalized):
        _error(errors, f"{context}.{field} contains an empty value")
    if len(set(normalized)) != len(normalized):
        _error(errors, f"{context}.{field} contains duplicates")
    if allowed is not None:
        for item in normalized:
            if item not in allowed:
                _error(errors, f"{context}.{field} contains an unknown value: {item}")
    return normalized


def _validate_projection_identity(
    inventory: Mapping[str, Any], current_tree_sha: str, errors: list[str]
) -> None:
    if inventory.get("projection_kind") != PROJECTION_KIND:
        _error(errors, f"reality inventory projection_kind must be {PROJECTION_KIND}")
    projection_source = inventory.get("projection_source")
    if not isinstance(projection_source, Mapping):
        _error(errors, "reality inventory projection_source must be an object")
        return
    if projection_source.get("authority") != "EXECUTABLE_CODE":
        _error(errors, "projection_source.authority must be EXECUTABLE_CODE")
    if projection_source.get("identity_scope") != "IMPLEMENTATION_TREE_IDENTITY_V3":
        _error(
            errors,
            "projection_source.identity_scope must be IMPLEMENTATION_TREE_IDENTITY_V3",
        )
    if projection_source.get("implementation_tree_sha") != current_tree_sha:
        _error(errors, "current-system projection is stale for the implementation tree")


def _validate_role_definitions(inventory: Mapping[str, Any], errors: list[str]) -> None:
    definitions = inventory.get("role_definitions")
    if not isinstance(definitions, Mapping):
        _error(errors, "reality inventory role_definitions must be an object")
        return
    if set(definitions) != SYSTEM_ROLES:
        _error(errors, "reality inventory role_definitions are not canonical")
    for role, definition in definitions.items():
        if not str(definition or "").strip():
            _error(errors, f"role_definitions.{role} is empty")


def _validate_semantic_constraints(
    root: Path, inventory: Mapping[str, Any], errors: list[str]
) -> None:
    constraints = inventory.get("semantic_constraints")
    if not isinstance(constraints, list) or not constraints:
        _error(
            errors, "reality inventory semantic_constraints must be a non-empty list"
        )
        return
    seen: set[str] = set()
    for index, constraint in enumerate(constraints):
        context = f"semantic_constraints[{index}]"
        if not isinstance(constraint, Mapping):
            _error(errors, f"{context} must be an object")
            continue
        constraint_id = str(constraint.get("id") or "").strip()
        if not CONCEPT_NAME.fullmatch(constraint_id):
            _error(errors, f"{context}.id must be lowercase kebab-case")
        elif constraint_id in seen:
            _error(errors, f"duplicate semantic constraint id: {constraint_id}")
        seen.add(constraint_id)
        classification = str(constraint.get("classification") or "")
        if classification not in SEMANTIC_CONSTRAINT_CLASSES:
            _error(errors, f"{context}.classification is not recognized")
        if not str(constraint.get("statement") or "").strip():
            _error(errors, f"{context}.statement is missing")
        design_review_required = constraint.get("design_review_required")
        if type(design_review_required) is not bool:
            _error(errors, f"{context}.design_review_required must be boolean")
        elif design_review_required != (
            classification == "UNRESOLVED_DESIGN_CONSTRAINT"
        ):
            _error(
                errors, f"{context}.design_review_required contradicts classification"
            )
        _validate_reference_list(
            root, constraint, "evidence", errors, context=context, required=True
        )


def _validate_authority_model(
    root: Path, inventory: Mapping[str, Any], errors: list[str]
) -> None:
    model = inventory.get("authority_model")
    if not isinstance(model, list) or not model:
        _error(errors, "reality inventory authority_model must be a non-empty list")
        return
    seen: set[str] = set()
    for index, item in enumerate(model):
        context = f"authority_model[{index}]"
        if not isinstance(item, Mapping):
            _error(errors, f"{context} must be an object")
            continue
        identity = str(item.get("id") or "").strip()
        if not CONCEPT_NAME.fullmatch(identity):
            _error(errors, f"{context}.id must be lowercase kebab-case")
        elif identity in seen:
            _error(errors, f"duplicate authority model id: {identity}")
        seen.add(identity)
        if item.get("role") not in SYSTEM_ROLES:
            _error(errors, f"{context}.role is not recognized")
        _validate_text_list(item, "owns", errors, context=context, required=True)
        _validate_text_list(
            item, "does_not_own", errors, context=context, required=True
        )
        if not str(item.get("mutation_rule") or "").strip():
            _error(errors, f"{context}.mutation_rule is missing")
        _validate_reference_list(
            root, item, "evidence", errors, context=context, required=True
        )


def _validate_narrative_model(
    root: Path, inventory: Mapping[str, Any], errors: list[str]
) -> None:
    model = inventory.get("narrative_model")
    if not isinstance(model, list) or not model:
        _error(errors, "reality inventory narrative_model must be a non-empty list")
        return
    by_id: dict[str, Mapping[str, Any]] = {}
    for index, item in enumerate(model):
        context = f"narrative_model[{index}]"
        if not isinstance(item, Mapping):
            _error(errors, f"{context} must be an object")
            continue
        identity = str(item.get("id") or "").strip()
        if not CONCEPT_NAME.fullmatch(identity):
            _error(errors, f"{context}.id must be lowercase kebab-case")
        elif identity in by_id:
            _error(errors, f"duplicate narrative object id: {identity}")
        else:
            by_id[identity] = item
        if item.get("nature") not in NARRATIVE_NATURES:
            _error(errors, f"{context}.nature is not recognized")
        if item.get("disposition") not in NARRATIVE_DISPOSITIONS:
            _error(errors, f"{context}.disposition is not recognized")
        if not str(item.get("owner") or "").strip():
            _error(errors, f"{context}.owner is missing")
        if not str(item.get("lifecycle_rule") or "").strip():
            _error(errors, f"{context}.lifecycle_rule is missing")
        _validate_reference_list(
            root, item, "evidence", errors, context=context, required=True
        )
    for index, item in enumerate(model):
        if not isinstance(item, Mapping):
            continue
        context = f"narrative_model[{index}]"
        relationships = item.get("relationships")
        if not isinstance(relationships, list):
            _error(errors, f"{context}.relationships must be a list")
            continue
        for relation_index, relation in enumerate(relationships):
            relation_context = f"{context}.relationships[{relation_index}]"
            if not isinstance(relation, Mapping):
                _error(errors, f"{relation_context} must be an object")
                continue
            if relation.get("type") not in NARRATIVE_RELATION_TYPES:
                _error(errors, f"{relation_context}.type is not recognized")
            target = str(relation.get("target") or "")
            if target not in by_id:
                _error(errors, f"{relation_context}.target is unknown: {target}")


def _validate_runtime_chain(
    root: Path, inventory: Mapping[str, Any], errors: list[str]
) -> None:
    chain = inventory.get("runtime_chain")
    if not isinstance(chain, list) or not chain:
        _error(errors, "reality inventory runtime_chain must be a non-empty list")
        return
    by_id: dict[str, Mapping[str, Any]] = {}
    orders: set[int] = set()
    for index, step in enumerate(chain):
        context = f"runtime_chain[{index}]"
        if not isinstance(step, Mapping):
            _error(errors, f"{context} must be an object")
            continue
        identity = str(step.get("id") or "").strip()
        if not CONCEPT_NAME.fullmatch(identity):
            _error(errors, f"{context}.id must be lowercase kebab-case")
        elif identity in by_id:
            _error(errors, f"duplicate runtime chain id: {identity}")
        else:
            by_id[identity] = step
        order = step.get("order")
        if type(order) is not int or order < 1:
            _error(errors, f"{context}.order must be a positive integer")
        elif order in orders:
            _error(errors, f"duplicate runtime chain order: {order}")
        else:
            orders.add(order)
        if step.get("path_role") not in RUNTIME_CHAIN_ROLES:
            _error(errors, f"{context}.path_role is not recognized")
        if not str(step.get("owner") or "").strip():
            _error(errors, f"{context}.owner is missing")
        _validate_reference_list(
            root, step, "evidence", errors, context=context, required=True
        )
    for index, step in enumerate(chain):
        if not isinstance(step, Mapping):
            continue
        context = f"runtime_chain[{index}]"
        for target in _validate_text_list(
            step, "downstream", errors, context=context, required=False
        ):
            if target not in by_id:
                _error(
                    errors, f"{context}.downstream references unknown step: {target}"
                )


def _git_tree_for_ancestor_commit(
    root: Path,
    commit_sha: str,
    errors: list[str],
    *,
    context: str,
) -> str:
    if not FULL_SHA.fullmatch(commit_sha):
        return ""
    try:
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit_sha, "HEAD"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        tree = subprocess.run(
            ["git", "rev-parse", "--verify", f"{commit_sha}^{{tree}}"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _error(errors, f"{context}.observed_at_sha cannot be verified by Git: {exc}")
        return ""
    resolved_tree = tree.stdout.strip().lower()
    if (
        ancestor.returncode != 0
        or tree.returncode != 0
        or not FULL_SHA.fullmatch(resolved_tree)
    ):
        _error(
            errors,
            f"{context}.observed_at_sha is not an ancestor Git commit",
        )
        return ""
    return resolved_tree


def _p0_report_projection(report: Mapping[str, Any]) -> dict[str, Any]:
    gates = report.get("gates")
    if not isinstance(gates, list):
        raise ValueError("P0 report gates are not a list")
    by_id = {
        str(gate.get("gate_id") or ""): gate
        for gate in gates
        if isinstance(gate, Mapping)
    }

    def collection(
        gate_id: str,
        classification: str,
        *,
        repeated: bool = False,
    ) -> dict[str, Any]:
        gate = by_id.get(gate_id)
        evidence = gate.get("evidence") if isinstance(gate, Mapping) else None
        if not isinstance(evidence, Mapping):
            raise ValueError(f"P0 report gate evidence is missing: {gate_id}")
        collected = evidence.get("collection")
        junit = evidence.get("junit")
        if not isinstance(collected, Mapping) or not isinstance(junit, Mapping):
            raise ValueError(f"P0 report collection evidence is missing: {gate_id}")
        projection = {
            "classification": classification,
            "collected_nodes": collected.get("collected_count"),
            "junit_cases": junit.get("tests"),
            "passed": junit.get("passed"),
            "skipped": junit.get("skipped"),
            "complete": collected.get("complete_collection"),
        }
        if repeated:
            projection["repeated_in_postgresql_collection"] = True
        return projection

    collections = [
        collection("pytest-backend", "BACKEND_NON_POSTGRESQL"),
        collection(
            "migration-compatibility",
            "MIGRATION_COMPATIBILITY",
            repeated=True,
        ),
        collection("pytest-postgresql-integration", "POSTGRESQL_REQUIRED"),
    ]
    migration_fresh = by_id.get("migration-fresh")
    migration_evidence = (
        migration_fresh.get("evidence")
        if isinstance(migration_fresh, Mapping)
        else None
    )
    migration = report.get("migration")
    cleanup = report.get("cleanup")
    if not isinstance(migration_evidence, Mapping) or not isinstance(
        migration, Mapping
    ):
        raise ValueError("P0 report migration evidence is missing")
    if not isinstance(cleanup, Mapping) or not isinstance(cleanup.get("phases"), list):
        raise ValueError("P0 report cleanup evidence is missing")
    phases = [dict(phase) for phase in cleanup["phases"]]
    owned_resource_count = sum(
        int(phase.get("resource_count") or 0)
        for phase in phases
        if type(phase.get("resource_count")) is int
    )
    unique_collections = (collections[0], collections[2])
    return {
        "source_tree": report.get("source_tree"),
        "implementation_tree_sha": report.get("implementation_tree_sha"),
        "dependency_snapshot_digest": (report.get("dependency_snapshot") or {}).get(
            "digest"
        ),
        "collected": sum(int(item["junit_cases"]) for item in unique_collections),
        "passed": sum(int(item["passed"]) for item in unique_collections),
        "failed": 0,
        "collections": collections,
        "gates": [
            {"id": gate.get("gate_id"), "status": gate.get("status")}
            for gate in gates
            if isinstance(gate, Mapping)
        ],
        "migration": {
            "applied_count": migration_evidence.get("applied_count"),
            "expected_head": migration.get("expected_head"),
            "observed_head": migration.get("observed_head"),
        },
        "cleanup": {
            "status": cleanup.get("status"),
            "owned_resource_count": owned_resource_count,
            "remaining_resource_count": cleanup.get("remaining_resource_count"),
            "phases": phases,
        },
        "proof_scope": report.get("proof_scope"),
    }


def _validate_p0_run_projection(
    root: Path,
    run: Mapping[str, Any],
    errors: list[str],
    *,
    context: str,
    migration_head: str,
) -> bool:
    initial_error_count = len(errors)
    observed_at_sha = str(run.get("observed_at_sha") or "")
    for field in ("dependency_snapshot_digest",):
        if not CONTENT_DIGEST.fullmatch(str(run.get(field) or "")):
            _error(errors, f"{context}.{field} must be a SHA-256 digest")

    artifact = run.get("qualification_report")
    qualification_run_id = ""
    retained_report: Mapping[str, Any] | None = None
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
        if artifact.get("retention") != "REPOSITORY_CURRENT_QUALIFICATION_ARTIFACT":
            _error(
                errors,
                f"{context}.qualification_report.retention is not explicit",
            )
        expected_path = f"architecture/evidence/{expected_report}"
        repository_path = str(artifact.get("repository_path") or "")
        if repository_path != expected_path:
            _error(
                errors,
                f"{context}.qualification_report.repository_path is not canonical",
            )
        report_path = _inside_root(root, repository_path, errors)
        if report_path is None or not report_path.is_file():
            _error(errors, f"{context}.qualification_report artifact is missing")
        else:
            try:
                report_bytes = report_path.read_bytes()
                parsed_report = json.loads(report_bytes.decode("utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                _error(
                    errors,
                    f"{context}.qualification_report artifact is invalid: {exc}",
                )
            else:
                observed_digest = "sha256:" + hashlib.sha256(report_bytes).hexdigest()
                if artifact.get("sha256") != observed_digest:
                    _error(
                        errors,
                        f"{context}.qualification_report artifact digest differs",
                    )
                if not isinstance(parsed_report, Mapping):
                    _error(
                        errors,
                        f"{context}.qualification_report artifact must be an object",
                    )
                else:
                    try:
                        from novel_forge.tools.release_run_evidence import (
                            validate_p0_backend_qualification_report,
                        )

                        validate_p0_backend_qualification_report(
                            parsed_report,
                            expected_sha=observed_at_sha,
                        )
                    except ValueError as exc:
                        _error(
                            errors,
                            f"{context}.qualification_report artifact fails validation: {exc}",
                        )
                    else:
                        retained_report = parsed_report
                        report_identity = parsed_report.get("run_identity")
                        if not isinstance(report_identity, Mapping) or (
                            report_identity.get("run_id") != qualification_run_id
                            or report_identity.get("artifact_root")
                            != artifact.get("artifact_root")
                        ):
                            _error(
                                errors,
                                f"{context}.qualification_report run identity differs",
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
            _error(
                errors, f"{context}.collections differ from the canonical P0 classes"
            )
        migration_collection = collections_by_class.get("MIGRATION_COMPATIBILITY")
        if (
            migration_collection is not None
            and migration_collection.get("repeated_in_postgresql_collection")
            is not True
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
            if (
                run.get("collected") != unique_total
                or run.get("passed") != unique_total
            ):
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
        valid_phases = isinstance(phases, list) and len(phases) == len(expected_phases)
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
    if run.get("proof_scope") != P0_PROOF_SCOPE:
        _error(errors, f"{context}.proof_scope differs from P0 policy")
    if retained_report is not None:
        try:
            report_projection = _p0_report_projection(retained_report)
        except (TypeError, ValueError) as exc:
            _error(errors, f"{context}.qualification_report cannot be projected: {exc}")
        else:
            for field, expected in report_projection.items():
                if run.get(field) != expected:
                    _error(
                        errors,
                        f"{context}.{field} differs from the retained qualification report",
                    )
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
    if inventory.get("fact_type_policy") != FACT_TYPE_POLICY:
        _error(errors, "reality inventory fact_type_policy is not canonical")

    migration_head = str(inventory.get("migration_head") or "").strip()
    if not migration_head:
        _error(errors, "reality inventory migration_head is missing")

    current_tree_sha = str(
        build_implementation_tree_identity(root).get("implementation_tree_sha") or ""
    )
    _validate_projection_identity(inventory, current_tree_sha, errors)
    _validate_role_definitions(inventory, errors)
    _validate_semantic_constraints(root, inventory, errors)
    _validate_authority_model(root, inventory, errors)
    _validate_narrative_model(root, inventory, errors)
    _validate_runtime_chain(root, inventory, errors)
    qualification_runs = inventory.get("qualification_runs")
    runs_by_id: dict[str, Mapping[str, Any]] = {}
    run_results: dict[str, tuple[int, int, int]] = {}
    run_evidence: dict[str, set[tuple[str, str, str]]] = {}
    run_classes: dict[str, str] = {}
    run_is_current: dict[str, bool] = {}
    runs_with_invalid_results: set[str] = set()
    historical_implementation_identities: dict[str, str] = {}
    if not isinstance(qualification_runs, list):
        _error(errors, "reality inventory qualification_runs must be a list")
    else:
        for index, run in enumerate(qualification_runs):
            context = f"qualification_runs[{index}]"
            if not isinstance(run, Mapping):
                _error(errors, f"{context} must be an object")
                continue
            run_error_count = len(errors)
            fact_type = str(run.get("fact_type") or "")
            if fact_type not in {
                FACT_TYPE_POLICY["current_qualification"],
                FACT_TYPE_POLICY["historical_compatibility"],
            }:
                _error(errors, f"{context}.fact_type is invalid")
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
            source_tree = str(run.get("source_tree") or "").strip()
            if not FULL_SHA.fullmatch(source_tree):
                _error(errors, f"{context}.source_tree must be a full Git tree SHA")
            resolved_tree = _git_tree_for_ancestor_commit(
                root,
                observed_at_sha,
                errors,
                context=context,
            )
            if resolved_tree and source_tree != resolved_tree:
                _error(
                    errors,
                    f"{context}.source_tree differs from the observed Git commit",
                )
            observed_implementation_tree_sha = ""
            if resolved_tree:
                try:
                    if observed_at_sha not in historical_implementation_identities:
                        historical_implementation_identities[observed_at_sha] = str(
                            build_git_implementation_tree_identity(
                                root, observed_at_sha
                            ).get("implementation_tree_sha")
                            or ""
                        )
                    observed_implementation_tree_sha = (
                        historical_implementation_identities[observed_at_sha]
                    )
                except (OSError, subprocess.SubprocessError, ValueError) as exc:
                    _error(
                        errors,
                        f"{context} cannot reconstruct the observed implementation tree: {exc}",
                    )
            counts = [run.get(field) for field in ("collected", "passed", "failed")]
            valid_counts = not any(
                type(value) is not int or value < 0 for value in counts
            )
            counts_match = valid_counts and counts[1] + counts[2] == counts[0]
            if not valid_counts:
                _error(errors, f"{context} result counts must be non-negative integers")
                runs_with_invalid_results.add(run_id)
            elif not counts_match:
                _error(errors, f"{context} passed plus failed must equal collected")
                runs_with_invalid_results.add(run_id)
            if counts_match and counts[2] == 0:
                implementation_tree_sha = str(
                    run.get("implementation_tree_sha") or ""
                ).strip()
                if not re.fullmatch(r"sha256:[0-9a-f]{64}", implementation_tree_sha):
                    _error(
                        errors,
                        f"{context}.implementation_tree_sha must be a SHA-256 digest",
                    )
                else:
                    run_is_current[run_id] = implementation_tree_sha == current_tree_sha
                if (
                    run_is_current.get(run_id, False)
                    and observed_implementation_tree_sha
                    and implementation_tree_sha != observed_implementation_tree_sha
                ):
                    _error(
                        errors,
                        f"{context} does not match the observed Git implementation tree",
                    )
                evidence = _validate_reference_list(
                    root,
                    run,
                    "qualification_evidence",
                    errors,
                    context=context,
                    required=True,
                )
                if (
                    evidence_class == P0_EVIDENCE_CLASS
                    and fact_type == FACT_TYPE_POLICY["current_qualification"]
                ):
                    _validate_p0_run_projection(
                        root,
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
                and evidence_class
                in {
                    P0_EVIDENCE_CLASS,
                    "focused_qualification_contracts",
                }
            ):
                run_results[run_id] = (counts[0], counts[1], counts[2])

    retained_artifacts = {
        str(report.get("repository_path") or "")
        for run in runs_by_id.values()
        if run_classes.get(str(run.get("id") or "")) == P0_EVIDENCE_CLASS
        and isinstance((report := run.get("qualification_report")), Mapping)
    }
    retained_root = root / "architecture/evidence"
    if retained_root.is_dir():
        for path in sorted(item for item in retained_root.rglob("*") if item.is_file()):
            relative = _relative(root, path)
            if relative not in retained_artifacts:
                _error(
                    errors, f"unreferenced retained qualification artifact: {relative}"
                )

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
        if capability.get("fact_type") != FACT_TYPE_POLICY["current_runtime"]:
            _error(errors, f"{context}.fact_type is not a current runtime fact")
        status = str(capability.get("qualification_state") or "").strip()
        if status not in STATUS_VOCABULARY:
            _error(
                errors,
                f"{context}.qualification_state is not recognized: {status}",
            )
        if not str(capability.get("proof_ceiling") or "").strip():
            _error(errors, f"{context}.proof_ceiling is missing")

        for field in CAPABILITY_REFERENCE_FIELDS:
            _validate_reference_list(
                root,
                capability,
                field,
                errors,
                context=context,
                required=(
                    field != "production_entries" or status in STATUS_VOCABULARY[1:]
                ),
            )
        state_ownership = capability.get("state_ownership")
        if not isinstance(state_ownership, Mapping):
            _error(errors, f"{context}.state_ownership must be an object")
        else:
            _validate_text_list(
                state_ownership,
                "owned_state",
                errors,
                context=f"{context}.state_ownership",
                required=True,
            )
            if not str(state_ownership.get("write_rule") or "").strip():
                _error(errors, f"{context}.state_ownership.write_rule is missing")
            _validate_reference_list(
                root,
                state_ownership,
                "evidence",
                errors,
                context=f"{context}.state_ownership",
                required=True,
            )
        external_effects = capability.get("external_effects")
        if not isinstance(external_effects, Mapping):
            _error(errors, f"{context}.external_effects must be an object")
        else:
            effect_mode = str(external_effects.get("mode") or "")
            if effect_mode not in EXTERNAL_EFFECT_MODES:
                _error(errors, f"{context}.external_effects.mode is not recognized")
            if not str(external_effects.get("rule") or "").strip():
                _error(errors, f"{context}.external_effects.rule is missing")
            _validate_reference_list(
                root,
                external_effects,
                "evidence",
                errors,
                context=f"{context}.external_effects",
                required=effect_mode != "NONE",
            )
        cited_migrations.update(
            _validate_migrations(root, capability, errors, context=context)
        )
        qualification = capability.get("tests")
        if not isinstance(qualification, list):
            qualification = []
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
                    if str(run_id) in runs_with_invalid_results:
                        _error(
                            errors,
                            f"{context} references a run with invalid results: {run_id}",
                        )
                    elif not run_is_current.get(str(run_id), False):
                        _error(
                            errors,
                            f"{context} references a run that does not qualify the current implementation tree",
                        )
                    else:
                        _error(
                            errors,
                            f"{context} references a run with invalid results: {run_id}",
                        )
                    continue
                if not run_is_current.get(str(run_id), False):
                    _error(
                        errors,
                        f"{context} references a run that does not qualify the current implementation tree",
                    )
                    continue
                proof_scope = run.get("proof_scope")
                proven_capabilities = (
                    proof_scope.get("proves")
                    if isinstance(proof_scope, Mapping)
                    else None
                )
                if not isinstance(proven_capabilities, list) or concept not in {
                    str(value) for value in proven_capabilities
                }:
                    _error(
                        errors,
                        f"{context} is outside the referenced run proof scope: {run_id}",
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

    for index, capability in enumerate(capabilities):
        if not isinstance(capability, Mapping):
            continue
        context = f"capabilities[{index}]"
        for field in ("upstream_dependencies", "downstream_consumers"):
            dependencies = _validate_text_list(
                capability, field, errors, context=context, required=False
            )
            for dependency in dependencies:
                if dependency not in concepts:
                    _error(
                        errors,
                        f"{context}.{field} references unknown capability: {dependency}",
                    )
                if dependency == capability.get("concept"):
                    _error(errors, f"{context}.{field} cannot reference itself")

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
            if boundary.get("classification") not in BOUNDARY_CLASSES:
                _error(errors, f"{context}.classification is not recognized")
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
    for relative in CANONICAL_DOCUMENTS:
        path = root / relative
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if MIGRATION_ID_IN_PROSE.search(content):
            _error(
                errors,
                f"canonical document duplicates a migration identity: {relative}",
            )


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
        accepted_comment_lines: set[int] = set()
        comments_by_line = {
            token.start[0]: token for token in tokens if token.type == tokenize.COMMENT
        }
        source_lines = path.read_text(encoding="utf-8").splitlines()
        immutable_migration = relative.startswith(
            "src/novel_forge/storage/migrations/versions/"
        )
        for token in tokens:
            if token.type != tokenize.COMMENT:
                continue
            comment_count += 1
            if HISTORICAL_OR_SPECULATIVE.search(token.string):
                _error(
                    errors,
                    f"historical or speculative comment: {relative}:{token.start[0]}",
                )
            if immutable_migration:
                continue
            line = source_lines[token.start[0] - 1]
            full_line = not line[: token.start[1]].strip()
            previous = comments_by_line.get(token.start[0] - 1)
            continuation = (
                full_line
                and previous is not None
                and previous.start[1] == token.start[1]
                and previous.start[0] in accepted_comment_lines
            )
            if _comment_is_policy_labeled(token.string) or continuation:
                accepted_comment_lines.add(token.start[0])
            else:
                _error(
                    errors,
                    f"production comment lacks policy label: {relative}:{token.start[0]}",
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


def _validate_script_comments(root: Path, errors: list[str]) -> int:
    scripts_root = root / "scripts"
    if not scripts_root.is_dir():
        return 0
    comment_count = 0
    for path in sorted(scripts_root.rglob("*.py")):
        relative = _relative(root, path)
        try:
            with path.open("rb") as handle:
                tokens = list(tokenize.tokenize(handle.readline))
            source_lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError, SyntaxError, tokenize.TokenError) as exc:
            _error(errors, f"cannot tokenize {relative}: {exc}")
            continue
        comments_by_line = {
            token.start[0]: token for token in tokens if token.type == tokenize.COMMENT
        }
        accepted_comment_lines: set[int] = set()
        for token in comments_by_line.values():
            comment_count += 1
            if HISTORICAL_OR_SPECULATIVE.search(token.string):
                _error(
                    errors,
                    f"historical or speculative comment: {relative}:{token.start[0]}",
                )
            line = source_lines[token.start[0] - 1]
            previous = comments_by_line.get(token.start[0] - 1)
            continuation = (
                not line[: token.start[1]].strip()
                and previous is not None
                and previous.start[1] == token.start[1]
                and previous.start[0] in accepted_comment_lines
            )
            if _comment_is_policy_labeled(token.string) or continuation:
                accepted_comment_lines.add(token.start[0])
            else:
                _error(
                    errors,
                    f"production comment lacks policy label: {relative}:{token.start[0]}",
                )
    return comment_count


def _validate_web_comments(root: Path, errors: list[str]) -> int:
    web_root = root / "web"
    if not web_root.is_dir():
        return 0
    comment_count = 0
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
            accepted_comment_lines: set[int] = set()
            generated_next_types = relative == "web/admin/next-env.d.ts"
            for line_number, line in enumerate(lines, start=1):
                match = WEB_COMMENT.match(line)
                if match:
                    comment_count += 1
                    if HISTORICAL_OR_SPECULATIVE.search(match.group(1)):
                        _error(
                            errors,
                            f"historical or speculative comment: {relative}:{line_number}",
                        )
                    continuation = line_number - 1 in accepted_comment_lines
                    if (
                        generated_next_types
                        or WEB_TOOLING_COMMENT.match(line)
                        or _comment_is_policy_labeled(line)
                        or continuation
                    ):
                        accepted_comment_lines.add(line_number)
                    else:
                        _error(
                            errors,
                            f"production comment lacks policy label: {relative}:{line_number}",
                        )
    return comment_count


def _archive_comment_counts(root: Path, commit_sha: str) -> tuple[int, int, int, int]:
    archived = subprocess.run(
        ["git", "archive", "--format=tar", commit_sha],
        cwd=root,
        check=False,
        capture_output=True,
        timeout=30,
    )
    if archived.returncode:
        raise ValueError("cannot read comment ratchet base tree")
    python_comments = 0
    script_comments = 0
    docstrings = 0
    web_comments = 0
    with tarfile.open(fileobj=io.BytesIO(archived.stdout), mode="r:") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            content = extracted.read()
            if member.name.startswith("src/") and member.name.endswith(".py"):
                try:
                    tokens = tokenize.tokenize(io.BytesIO(content).readline)
                    python_comments += sum(
                        token.type == tokenize.COMMENT for token in tokens
                    )
                    tree = ast.parse(content.decode("utf-8"), filename=member.name)
                except (SyntaxError, UnicodeDecodeError, tokenize.TokenError) as exc:
                    raise ValueError(
                        f"cannot inspect comment ratchet base: {member.name}: {exc}"
                    ) from exc
                docstrings += sum(1 for _node, _name, _text in _docstring_nodes(tree))
            elif member.name.startswith("scripts/") and member.name.endswith(".py"):
                try:
                    tokens = tokenize.tokenize(io.BytesIO(content).readline)
                    script_comments += sum(
                        token.type == tokenize.COMMENT for token in tokens
                    )
                except (SyntaxError, tokenize.TokenError) as exc:
                    raise ValueError(
                        f"cannot inspect comment ratchet base: {member.name}: {exc}"
                    ) from exc
            elif member.name.startswith("web/") and member.name.endswith(
                (".js", ".mjs", ".ts", ".tsx")
            ):
                if any(
                    part in {"node_modules", ".next"}
                    for part in Path(member.name).parts
                ):
                    continue
                try:
                    lines = content.decode("utf-8").splitlines()
                except UnicodeDecodeError as exc:
                    raise ValueError(
                        f"cannot inspect comment ratchet base: {member.name}: {exc}"
                    ) from exc
                web_comments += sum(
                    WEB_COMMENT.match(line) is not None for line in lines
                )
    return python_comments, script_comments, docstrings, web_comments


def _comment_ratchet_base(root: Path, errors: list[str]) -> str:
    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if remote.returncode:
        return ""
    requested = os.environ.get("NOVEL_FORGE_REALITY_BASE_REF", "").strip()
    refs = tuple(dict.fromkeys(filter(None, (requested, "origin/main", "main"))))
    for ref in refs:
        result = subprocess.run(
            ["git", "merge-base", "HEAD", ref],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        candidate = result.stdout.strip().lower()
        if result.returncode == 0 and FULL_SHA.fullmatch(candidate):
            return candidate
    _error(errors, "comment ratchet base is unavailable for repository with origin")
    return ""


def _added_lines(root: Path, base_sha: str, errors: list[str]) -> dict[str, set[int]]:
    diff = subprocess.run(
        ["git", "diff", "--unified=0", "--no-ext-diff", base_sha, "--", "src", "web"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if diff.returncode:
        _error(errors, "cannot derive added comment lines from comment ratchet base")
        return {}
    current_path = ""
    current_line = 0
    added: dict[str, set[int]] = {}
    hunk = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
    for line in diff.stdout.splitlines():
        if line.startswith("+++ b/"):
            current_path = line.removeprefix("+++ b/")
            continue
        match = hunk.match(line)
        if match:
            current_line = int(match.group(1))
            continue
        if not current_path or not current_line:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            added.setdefault(current_path, set()).add(current_line)
            current_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            continue
        elif not line.startswith("\\"):
            current_line += 1
    return added


def _comment_is_policy_labeled(comment: str) -> bool:
    stripped = comment.strip()
    if TOOLING_COMMENT.match(stripped):
        return True
    text = stripped
    for marker in ("#", "//", "/*", "*", "<!--"):
        if text.startswith(marker):
            text = text[len(marker) :].lstrip()
            break
    return text.startswith(COMMENT_PREFIXES)


def _validate_added_comment_policy(
    root: Path,
    added: Mapping[str, set[int]],
    errors: list[str],
) -> None:
    for relative, line_numbers in sorted(added.items()):
        path = root / relative
        if not path.is_file():
            continue
        if path.suffix == ".py":
            try:
                with path.open("rb") as handle:
                    all_comments = [
                        token
                        for token in tokenize.tokenize(handle.readline)
                        if token.type == tokenize.COMMENT
                    ]
            except (OSError, SyntaxError, tokenize.TokenError) as exc:
                _error(errors, f"cannot inspect added comments: {relative}: {exc}")
                continue
            by_line = {token.start[0]: token for token in all_comments}
            accepted: set[int] = set()
            source_lines = path.read_text(encoding="utf-8").splitlines()
            for token in all_comments:
                if token.start[0] not in line_numbers:
                    continue
                line = source_lines[token.start[0] - 1]
                full_line = not line[: token.start[1]].strip()
                continuation = (
                    full_line
                    and token.start[0] - 1 in by_line
                    and (
                        token.start[0] - 1 in accepted
                        or _comment_is_policy_labeled(
                            by_line[token.start[0] - 1].string
                        )
                    )
                )
                if _comment_is_policy_labeled(token.string) or continuation:
                    accepted.add(token.start[0])
                else:
                    _error(
                        errors,
                        f"new comment lacks policy label: {relative}:{token.start[0]}",
                    )
        elif path.suffix in {".js", ".mjs", ".ts", ".tsx"}:
            lines = path.read_text(encoding="utf-8").splitlines()
            accepted: set[int] = set()
            for line_number in sorted(line_numbers):
                if line_number > len(lines):
                    continue
                match = WEB_COMMENT.match(lines[line_number - 1])
                continuation = line_number - 1 in accepted or (
                    line_number > 1
                    and WEB_COMMENT.match(lines[line_number - 2]) is not None
                    and _comment_is_policy_labeled(lines[line_number - 2])
                )
                if match and (
                    _comment_is_policy_labeled(lines[line_number - 1]) or continuation
                ):
                    accepted.add(line_number)
                elif match:
                    _error(
                        errors,
                        f"new comment lacks policy label: {relative}:{line_number}",
                    )


def _validate_comment_ratchet(
    root: Path,
    *,
    python_comments: int,
    script_comments: int,
    docstrings: int,
    web_comments: int,
    errors: list[str],
) -> dict[str, Any]:
    initial_error_count = len(errors)
    base_sha = _comment_ratchet_base(root, errors)
    if not base_sha:
        return {"status": "NOT_APPLICABLE_NO_ORIGIN", "base_sha": ""}
    try:
        base_python, base_scripts, base_docstrings, base_web = _archive_comment_counts(
            root, base_sha
        )
    except ValueError as exc:
        _error(errors, str(exc))
        return {"status": "FAIL", "base_sha": base_sha}
    for name, current, baseline in (
        ("source comments", python_comments, base_python),
        ("script comments", script_comments, base_scripts),
        ("source docstrings", docstrings, base_docstrings),
        ("web comments", web_comments, base_web),
    ):
        if current > baseline:
            _error(errors, f"comment ratchet increased {name}: {current} > {baseline}")
    _validate_added_comment_policy(root, _added_lines(root, base_sha, errors), errors)
    return {
        "status": "PASS" if len(errors) == initial_error_count else "FAIL",
        "base_sha": base_sha,
        "base_source_comment_count": base_python,
        "base_script_comment_count": base_scripts,
        "base_source_docstring_count": base_docstrings,
        "base_web_comment_count": base_web,
    }


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
    script_comment_count = _validate_script_comments(repository, errors)
    web_comment_count = _validate_web_comments(repository, errors)
    comment_policy = (
        inventory.get("comment_policy") if isinstance(inventory, Mapping) else None
    )
    if not isinstance(comment_policy, Mapping):
        _error(errors, "reality inventory comment_policy must be an object")
    else:
        if comment_policy.get("ratchet") != COMMENT_RATCHET:
            _error(errors, "comment_policy.ratchet is not canonical")
        if comment_policy.get("scope") != COMMENT_POLICY_SCOPE:
            _error(errors, "comment_policy.scope is not canonical")
        if comment_policy.get("new_comment_prefixes") != list(COMMENT_PREFIXES):
            _error(errors, "comment_policy.new_comment_prefixes is not canonical")
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

    ratchet = _validate_comment_ratchet(
        repository,
        python_comments=comment_count,
        script_comments=script_comment_count,
        docstrings=docstring_count,
        web_comments=web_comment_count,
        errors=errors,
    )

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
        "script_comment_count": script_comment_count,
        "web_comment_count": web_comment_count,
        "module_docstring_count": len(module_docstrings),
        "source_docstring_count": docstring_count,
        "comment_ratchet": ratchet,
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
