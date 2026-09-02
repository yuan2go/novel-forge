from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from types import MappingProxyType
from typing import Any, Mapping
import xml.etree.ElementTree as ElementTree


QUALIFICATION_MANIFEST = Path(
    "architecture/manifests/backend-qualification-manifest.yaml"
)
MIGRATION_MANIFEST = Path("architecture/manifests/migration-manifest.yaml")
QUALIFICATION_SCHEMA_VERSION = "novel-forge.backend-qualification-manifest.v2"
COLLECTION_CLASSIFICATIONS = frozenset(
    {"BACKEND_NON_POSTGRESQL", "POSTGRESQL_REQUIRED"}
)
REQUIRED_GATE_ORDER = (
    "source-preflight",
    "documentation-reality",
    "static-and-manifests",
    "pytest-backend",
    "postgresql-start",
    "migration-fresh",
    "migration-compatibility",
    "pytest-postgresql-integration",
    "migration-head",
    "query-plan-release",
    "compose-runtime",
    "resource-cleanup",
    "evidence-finalization",
)
P0_PROOF_SCOPE = {
    "schema_version": "novel-forge.qualification-proof-scope.v1",
    "fact_type": "CURRENT_QUALIFICATION_EVIDENCE",
    "proves": [
        "runtime-composition",
        "project-workspace-authority",
        "command-attempt-lease-fence",
        "capability-pack-instruction-runtime",
        "external-effect-provider-control",
        "source-import-and-knowledge",
        "book-design-and-story-formation",
        "story-design-authority",
        "hierarchical-planning",
        "narrative-realization",
        "plan-change-authority",
        "book-opening-workflow",
        "book-production-coordination",
        "chapter-group-coordination",
        "context-and-retrieval",
        "chapter-production-saga",
        "review-revision-quality",
        "book-chapter-acceptance",
        "canon-and-narrative-state",
        "reader-and-followup-evidence",
        "agent-runtime",
        "postgresql-persistence-and-migrations",
        "retry-recovery-and-replay",
    ],
    "ceiling": "LOCAL_BACKEND_ENGINEERING",
    "does_not_establish": [
        "ADMIN_UI_EXECUTION",
        "CREDENTIALED_PROVIDER_EXECUTION",
        "HUMAN_EDITORIAL_EVIDENCE",
        "LONGITUDINAL_NARRATIVE_STABILITY",
        "PRODUCTION_OPERATION",
    ],
}
REQUIRED_SEMANTIC_SLICES = frozenset(
    {
        "migration_matrix",
        "provider_hard_stop_and_callback",
        "provider_effect_fixture_control",
        "backend_vertical_slice",
        "book_opening_recovery",
        "story_design_plan_change_activation",
    }
)
DEPENDENCY_NAME_SEPARATOR = re.compile(r"[-_.]+")
DATABASE_URL_PATTERN = re.compile(
    r"(?i)\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis)://[^\s\"'<>]+"
)
CREDENTIAL_URL_PATTERN = re.compile(
    r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@[^\s\"'<>]+"
)
ENV_SECRET_PATTERN = re.compile(
    r"(?i)\b[A-Z0-9_]*(?:PASSWORD|SECRET|API_KEY|ACCESS_KEY|PRIVATE_KEY|AUTH_TOKEN)=[^\s]+"
)
SENSITIVE_EVIDENCE_KEYS = frozenset(
    {
        "access_key",
        "access_token",
        "api_key",
        "auth_token",
        "bearer_token",
        "credential",
        "credentials",
        "database_url",
        "dsn",
        "password",
        "private_key",
        "provider_api_key",
        "refresh_token",
        "secret",
        "secret_key",
        "token",
    }
)
DEPENDENCY_PROBE = """
import importlib.metadata
import json
import platform

packages = [
    {"name": distribution.metadata.get("Name", ""), "version": distribution.version}
    for distribution in importlib.metadata.distributions()
]
print(json.dumps({
    "python_implementation": platform.python_implementation(),
    "python_version": platform.python_version(),
    "packages": packages,
}, sort_keys=True))
""".strip()


class QualificationContractError(ValueError):
    pass


@dataclass(frozen=True)
class PytestCollectionContract:
    name: str
    paths: tuple[str, ...]
    classification: str
    complete_collection: bool
    allow_skips: bool


@dataclass(frozen=True)
class QualificationManifest:
    schema_version: str
    migration_manifest: Path
    pytest_collections: tuple[PytestCollectionContract, ...]
    required_gates: tuple[str, ...]
    semantic_slices: Mapping[str, tuple[str, ...]]
    proof_scope: Mapping[str, object]


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise QualificationContractError(
            f"qualification manifest is missing: {path}"
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationContractError(
            f"qualification manifest is not JSON-compatible YAML: {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise QualificationContractError("qualification manifest must be an object")
    return payload


def _required_text(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise QualificationContractError(
            f"qualification manifest field is empty: {field}"
        )
    return text


def _relative_path(value: object, *, field: str) -> str:
    text = _required_text(value, field=field)
    path = Path(text)
    if path.is_absolute() or ".." in path.parts:
        raise QualificationContractError(
            f"qualification manifest path must be repository-relative: {field}"
        )
    return path.as_posix()


def load_qualification_manifest(repo_root: Path) -> QualificationManifest:
    root = repo_root.resolve()
    payload = _load_json_object(root / QUALIFICATION_MANIFEST)
    schema_version = _required_text(
        payload.get("schema_version"), field="schema_version"
    )
    if schema_version != QUALIFICATION_SCHEMA_VERSION:
        raise QualificationContractError(
            f"unsupported backend qualification manifest schema: {schema_version}"
        )

    migration_manifest = Path(
        _relative_path(payload.get("migration_manifest"), field="migration_manifest")
    )
    if not (root / migration_manifest).is_file():
        raise QualificationContractError(
            f"canonical migration manifest is missing: {migration_manifest}"
        )

    raw_collections = payload.get("pytest_collections")
    if not isinstance(raw_collections, list) or not raw_collections:
        raise QualificationContractError("pytest_collections must be a non-empty array")
    collections: list[PytestCollectionContract] = []
    names: set[str] = set()
    roots: set[str] = set()
    for index, item in enumerate(raw_collections):
        if not isinstance(item, dict):
            raise QualificationContractError(
                f"pytest_collections[{index}] must be an object"
            )
        name = _required_text(
            item.get("name"), field=f"pytest_collections[{index}].name"
        )
        if name in names:
            raise QualificationContractError(
                f"duplicate pytest collection name: {name}"
            )
        names.add(name)
        raw_paths = item.get("paths")
        if not isinstance(raw_paths, list) or not raw_paths:
            raise QualificationContractError(f"pytest collection {name} has no paths")
        paths = tuple(
            _relative_path(value, field=f"pytest_collections[{index}].paths")
            for value in raw_paths
        )
        for path in paths:
            if path in roots:
                raise QualificationContractError(
                    f"pytest collection root is classified more than once: {path}"
                )
            if not (root / path).is_dir():
                raise QualificationContractError(
                    f"pytest collection root does not exist: {path}"
                )
            roots.add(path)
        classification = _required_text(
            item.get("classification"),
            field=f"pytest_collections[{index}].classification",
        )
        if classification not in COLLECTION_CLASSIFICATIONS:
            raise QualificationContractError(
                f"unsupported pytest qualification class: {classification}"
            )
        complete_collection = item.get("complete_collection")
        allow_skips = item.get("allow_skips")
        if not isinstance(complete_collection, bool) or not isinstance(
            allow_skips, bool
        ):
            raise QualificationContractError(
                f"pytest collection {name} requires boolean collection and skip policy"
            )
        if classification == "POSTGRESQL_REQUIRED" and allow_skips:
            raise QualificationContractError(
                f"PostgreSQL collection {name} cannot permit skips"
            )
        collections.append(
            PytestCollectionContract(
                name=name,
                paths=paths,
                classification=classification,
                complete_collection=complete_collection,
                allow_skips=allow_skips,
            )
        )

    required_gates = tuple(
        _required_text(value, field="required_gates")
        for value in payload.get("required_gates", [])
    )
    if not required_gates or len(set(required_gates)) != len(required_gates):
        raise QualificationContractError("required_gates must be non-empty and unique")
    if required_gates != REQUIRED_GATE_ORDER:
        raise QualificationContractError(
            "required_gates differ from the canonical fail-fast order"
        )

    raw_slices = payload.get("semantic_slices")
    if not isinstance(raw_slices, dict) or not raw_slices:
        raise QualificationContractError("semantic_slices must be a non-empty object")
    semantic_slices: dict[str, tuple[str, ...]] = {}
    for name, values in raw_slices.items():
        if not isinstance(values, list) or not values:
            raise QualificationContractError(
                f"semantic slice {name} has no test modules"
            )
        paths = tuple(
            _relative_path(value, field=f"semantic_slices.{name}") for value in values
        )
        missing = [path for path in paths if not (root / path).is_file()]
        if missing:
            raise QualificationContractError(
                f"semantic slice {name} references missing tests: {', '.join(missing)}"
            )
        semantic_slices[str(name)] = paths
    missing_slices = sorted(REQUIRED_SEMANTIC_SLICES - semantic_slices.keys())
    if missing_slices:
        raise QualificationContractError(
            "required semantic slices are missing: " + ", ".join(missing_slices)
        )
    discovered_migration_compatibility = {
        path.relative_to(root).as_posix()
        for pattern in ("test_*migration*.py", "test_*upgrade*.py")
        for path in (root / "tests" / "integration").glob(pattern)
        if path.is_file()
    }
    undeclared_migration_compatibility = sorted(
        discovered_migration_compatibility - set(semantic_slices["migration_matrix"])
    )
    if undeclared_migration_compatibility:
        raise QualificationContractError(
            "migration_matrix omits PostgreSQL migration/upgrade tests: "
            + ", ".join(undeclared_migration_compatibility)
        )

    proof_scope = payload.get("proof_scope")
    if not isinstance(proof_scope, dict) or not proof_scope:
        raise QualificationContractError("proof_scope must be a non-empty object")
    if proof_scope != P0_PROOF_SCOPE:
        raise QualificationContractError(
            "proof_scope differs from the canonical P0 proof contract"
        )
    return QualificationManifest(
        schema_version=schema_version,
        migration_manifest=migration_manifest,
        pytest_collections=tuple(collections),
        required_gates=required_gates,
        semantic_slices=MappingProxyType(semantic_slices),
        proof_scope=MappingProxyType(proof_scope),
    )


def _junit_integer(value: object, *, field: str) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise QualificationContractError(
            f"JUnit field {field} is not an integer"
        ) from exc
    if parsed < 0:
        raise QualificationContractError(f"JUnit field {field} cannot be negative")
    return parsed


def _junit_duration(value: object) -> float:
    try:
        parsed = float(str(value))
    except (TypeError, ValueError) as exc:
        raise QualificationContractError("JUnit time is not numeric") from exc
    if parsed < 0 or not math.isfinite(parsed):
        raise QualificationContractError("JUnit time must be finite and non-negative")
    return parsed


def parse_junit_xml(path: Path) -> dict[str, object]:
    """INVARIANT: JUnit XML, not terminal prose, owns executed test counts."""
    try:
        root = ElementTree.parse(path).getroot()
    except FileNotFoundError as exc:
        raise QualificationContractError(f"JUnit XML is missing: {path}") from exc
    except ElementTree.ParseError as exc:
        raise QualificationContractError(f"JUnit XML is malformed: {path}") from exc
    if root.tag not in {"testsuite", "testsuites"}:
        raise QualificationContractError(f"unsupported JUnit root element: {root.tag}")

    if root.get("tests") is not None:
        sources = (root,)
    elif root.tag == "testsuites":
        sources = tuple(child for child in root if child.tag == "testsuite")
        if not sources:
            raise QualificationContractError("JUnit XML contains no test suites")
    else:
        sources = (root,)

    tests = sum(
        _junit_integer(source.get("tests"), field="tests") for source in sources
    )
    failures = sum(
        _junit_integer(source.get("failures", "0"), field="failures")
        for source in sources
    )
    errors = sum(
        _junit_integer(source.get("errors", "0"), field="errors") for source in sources
    )
    skipped = sum(
        _junit_integer(source.get("skipped", "0"), field="skipped")
        for source in sources
    )
    duration = sum(_junit_duration(source.get("time", "0")) for source in sources)
    passed = tests - failures - errors - skipped
    if tests < 1:
        raise QualificationContractError("JUnit XML reports zero tests")
    if passed < 0:
        raise QualificationContractError(
            "JUnit outcomes exceed the reported test count"
        )
    return {
        "tests": tests,
        "passed": passed,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "duration_seconds": round(duration, 6),
    }


def expected_migration_head(repo_root: Path) -> str:
    payload = _load_json_object(repo_root.resolve() / MIGRATION_MANIFEST)
    if payload.get("schema_version") != "architecture-manifest.v1":
        raise QualificationContractError("unsupported migration manifest schema")
    manifest_head = _required_text(payload.get("head"), field="migration head")

    from novel_forge.storage.migrations.runner import (
        LATEST_MIGRATION_ID,
        validate_migration_chain,
    )

    validate_migration_chain()
    if manifest_head != LATEST_MIGRATION_ID:
        raise QualificationContractError(
            "canonical migration manifest head and runtime registry differ: "
            f"manifest={manifest_head!r}, registry={LATEST_MIGRATION_ID!r}"
        )
    return manifest_head


def _content_digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def resolved_dependency_snapshot(
    python: str, *, repo_root: Path | None = None
) -> dict[str, object]:
    """INVARIANT: bind proof to resolved packages because Git may leave ranges unlocked."""
    completed = subprocess.run(
        [python, "-I", "-c", DEPENDENCY_PROBE],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode:
        raise QualificationContractError(
            "dependency probe failed for the qualification interpreter"
        )
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise QualificationContractError(
            "dependency probe did not emit one JSON object"
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("packages"), list):
        raise QualificationContractError("dependency probe payload is incomplete")

    versions: dict[str, str] = {}
    for item in payload["packages"]:
        if not isinstance(item, dict):
            raise QualificationContractError(
                "dependency package entry is not an object"
            )
        name = DEPENDENCY_NAME_SEPARATOR.sub(
            "-", _required_text(item.get("name"), field="dependency name").lower()
        )
        version = _required_text(
            item.get("version"), field=f"dependency {name} version"
        )
        existing = versions.get(name)
        if existing is not None and existing != version:
            raise QualificationContractError(
                f"dependency snapshot contains conflicting versions for {name}"
            )
        versions[name] = version
    packages = [f"{name}=={versions[name]}" for name in sorted(versions)]
    if not packages:
        raise QualificationContractError("dependency snapshot contains no packages")

    root = (repo_root or Path.cwd()).resolve()
    provenance_paths = {
        path
        for pattern in ("uv.lock", "poetry.lock", "Pipfile.lock", "constraints*.txt")
        for path in root.glob(pattern)
        if path.is_file()
    }
    provenance = [
        {
            "path": path.relative_to(root).as_posix(),
            "digest": _content_digest(path.read_bytes()),
        }
        for path in sorted(provenance_paths)
    ]
    python_implementation = _required_text(
        payload.get("python_implementation"), field="python implementation"
    )
    python_version = _required_text(
        payload.get("python_version"), field="python version"
    )
    identity = {
        "python_implementation": python_implementation,
        "python_version": python_version,
        "packages": packages,
        "provenance_files": provenance,
    }
    digest = _content_digest(
        json.dumps(identity, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    snapshot = {
        "schema_version": "novel-forge.resolved-dependency-snapshot.v1",
        **identity,
        "package_count": len(packages),
        "digest": digest,
        "reproducibility_class": (
            "CONSTRAINTS_BOUND_RESOLVED_SNAPSHOT" if provenance else "RESOLVED_SNAPSHOT"
        ),
        "git_sha_alone_reproducible": False,
    }
    return validate_resolved_dependency_snapshot(snapshot)


def validate_resolved_dependency_snapshot(
    snapshot: Mapping[str, object],
) -> dict[str, object]:
    if snapshot.get("schema_version") != "novel-forge.resolved-dependency-snapshot.v1":
        raise QualificationContractError(
            "resolved dependency snapshot schema is invalid"
        )
    python_implementation = _required_text(
        snapshot.get("python_implementation"), field="python implementation"
    )
    python_version = _required_text(
        snapshot.get("python_version"), field="python version"
    )
    packages = snapshot.get("packages")
    if (
        not isinstance(packages, list)
        or not packages
        or not all(
            isinstance(item, str)
            and item.count("==") == 1
            and not any(character.isspace() for character in item)
            for item in packages
        )
    ):
        raise QualificationContractError(
            "resolved dependency package identities are invalid"
        )
    package_names = [item.partition("==")[0] for item in packages]
    if package_names != sorted(set(package_names)):
        raise QualificationContractError(
            "resolved dependency package identities must be sorted and unique"
        )
    package_count = snapshot.get("package_count")
    if (
        not isinstance(package_count, int)
        or isinstance(package_count, bool)
        or package_count != len(packages)
    ):
        raise QualificationContractError(
            "resolved dependency package count differs from package identities"
        )

    provenance_files = snapshot.get("provenance_files")
    if not isinstance(provenance_files, list):
        raise QualificationContractError(
            "resolved dependency provenance files are invalid"
        )
    normalized_provenance: list[dict[str, str]] = []
    for item in provenance_files:
        if not isinstance(item, Mapping):
            raise QualificationContractError(
                "resolved dependency provenance entry is invalid"
            )
        relative = _relative_path(item.get("path"), field="dependency provenance path")
        digest = _required_text(
            item.get("digest"), field="dependency provenance digest"
        )
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise QualificationContractError(
                "resolved dependency provenance digest is invalid"
            )
        normalized_provenance.append({"path": relative, "digest": digest})
    if normalized_provenance != sorted(
        normalized_provenance, key=lambda item: item["path"]
    ) or len({item["path"] for item in normalized_provenance}) != len(
        normalized_provenance
    ):
        raise QualificationContractError(
            "resolved dependency provenance files must be sorted and unique"
        )

    identity = {
        "python_implementation": python_implementation,
        "python_version": python_version,
        "packages": packages,
        "provenance_files": normalized_provenance,
    }
    observed_digest = _required_text(
        snapshot.get("digest"), field="dependency snapshot digest"
    )
    calculated_digest = _content_digest(
        json.dumps(identity, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    if observed_digest != calculated_digest:
        raise QualificationContractError(
            "resolved dependency snapshot digest differs from its identity"
        )
    expected_classification = (
        "CONSTRAINTS_BOUND_RESOLVED_SNAPSHOT"
        if normalized_provenance
        else "RESOLVED_SNAPSHOT"
    )
    if snapshot.get("reproducibility_class") != expected_classification:
        raise QualificationContractError(
            "resolved dependency reproducibility class differs from provenance"
        )
    if snapshot.get("git_sha_alone_reproducible") is not False:
        raise QualificationContractError(
            "resolved dependency snapshot cannot claim Git SHA alone is reproducible"
        )
    return dict(snapshot)


def _sensitive_evidence_key(key: str) -> bool:
    normalized = key.strip().lower()
    if normalized in SENSITIVE_EVIDENCE_KEYS:
        return True
    return any(
        normalized.endswith(suffix)
        for suffix in (
            "_password",
            "_secret",
            "_secret_key",
            "_api_key",
            "_access_key",
            "_private_key",
            "_database_url",
            "_dsn",
        )
    )


def _sanitize_evidence_text(value: str) -> str:
    sanitized = DATABASE_URL_PATTERN.sub("[REDACTED_DATABASE_URL]", value)
    sanitized = CREDENTIAL_URL_PATTERN.sub("[REDACTED_CREDENTIAL_URL]", sanitized)
    return ENV_SECRET_PATTERN.sub("[REDACTED_SECRET_ASSIGNMENT]", sanitized)


def sanitize_evidence(value: object) -> object:
    """SECURITY: qualification evidence must not retain credentials or connection URLs."""
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, nested in value.items():
            text_key = str(key)
            result[text_key] = (
                "[REDACTED]"
                if _sensitive_evidence_key(text_key)
                else sanitize_evidence(nested)
            )
        return result
    if isinstance(value, (list, tuple)):
        return [sanitize_evidence(item) for item in value]
    if isinstance(value, str):
        return _sanitize_evidence_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Path):
        return _sanitize_evidence_text(value.as_posix())
    return _sanitize_evidence_text(str(value))


def validate_collection_report(
    *,
    contract: PytestCollectionContract,
    report_path: Path,
    repo_root: Path,
) -> dict[str, object]:
    """INVARIANT: complete evidence includes every declared test source exactly once."""
    payload = _load_json_object(report_path)
    if payload.get("schema_version") != "novel-forge.pytest-collection.v1":
        raise QualificationContractError("unsupported pytest collection report schema")
    node_ids = payload.get("node_ids")
    source_files = payload.get("source_files")
    collection_errors = payload.get("collection_errors")
    if not isinstance(node_ids, list) or not all(
        isinstance(value, str) and value for value in node_ids
    ):
        raise QualificationContractError("pytest collection node_ids are invalid")
    if not isinstance(source_files, list) or not all(
        isinstance(value, str) and value for value in source_files
    ):
        raise QualificationContractError("pytest collection source_files are invalid")
    if not isinstance(collection_errors, list):
        raise QualificationContractError("pytest collection errors are invalid")
    if collection_errors:
        raise QualificationContractError(
            f"pytest collection contains errors: {collection_errors}"
        )
    collected_count = payload.get("collected_count")
    if not isinstance(collected_count, int) or collected_count < 1:
        raise QualificationContractError("pytest collection reports zero tests")
    if collected_count != len(node_ids) or len(set(node_ids)) != len(node_ids):
        raise QualificationContractError(
            "pytest collection count and unique node IDs differ"
        )
    if source_files != sorted(set(source_files)):
        raise QualificationContractError(
            "pytest collection source files must be sorted and unique"
        )
    node_source_files = {node_id.partition("::")[0] for node_id in node_ids}
    if node_source_files != set(source_files):
        raise QualificationContractError(
            "pytest node IDs and collected source files differ"
        )

    root = repo_root.resolve()
    expected_files: set[str] = set()
    for relative in contract.paths:
        declared = (root / relative).resolve()
        try:
            declared_relative = declared.relative_to(root).as_posix()
        except ValueError as exc:
            raise QualificationContractError(
                f"pytest collection path escapes repository: {relative}"
            ) from exc
        if declared.is_file():
            if not declared.name.startswith("test_") or declared.suffix != ".py":
                raise QualificationContractError(
                    f"pytest collection file is not a test module: {relative}"
                )
            expected_files.add(declared_relative)
            continue
        if not declared.is_dir():
            raise QualificationContractError(
                f"pytest collection path does not exist: {relative}"
            )
        for path in declared.rglob("test_*.py"):
            if not path.is_file():
                continue
            try:
                expected_files.add(path.resolve().relative_to(root).as_posix())
            except ValueError as exc:
                raise QualificationContractError(
                    f"pytest test source escapes repository: {path}"
                ) from exc
    observed_files = set(source_files)
    if contract.complete_collection and expected_files != observed_files:
        missing = sorted(expected_files - observed_files)
        unexpected = sorted(observed_files - expected_files)
        raise QualificationContractError(
            f"complete pytest collection {contract.name} differs: "
            f"missing={missing}, unexpected={unexpected}"
        )
    exit_status = payload.get("pytest_exit_status")
    if not isinstance(exit_status, int) or exit_status < 0:
        raise QualificationContractError("pytest exit status is invalid")
    return {
        "schema_version": "novel-forge.validated-pytest-collection.v1",
        "name": contract.name,
        "classification": contract.classification,
        "complete_collection": contract.complete_collection,
        "collected_count": collected_count,
        "source_file_count": len(source_files),
        "source_files": source_files,
        "pytest_exit_status": exit_status,
        "report_digest": _content_digest(report_path.read_bytes()),
    }


def _build_pytest_command(
    *,
    contracts: tuple[PytestCollectionContract, ...],
    python: str,
    junit_xml: Path,
    collection_report: Path,
) -> list[str]:
    if not contracts:
        raise QualificationContractError("qualification pytest contracts are empty")
    if any(not contract.complete_collection for contract in contracts):
        raise QualificationContractError(
            "qualification pytest collections must be complete"
        )
    if not python.strip():
        raise QualificationContractError("qualification Python executable is empty")
    if not junit_xml.is_absolute() or not collection_report.is_absolute():
        raise QualificationContractError(
            "qualification pytest evidence paths must be absolute"
        )
    paths = tuple(path for contract in contracts for path in contract.paths)
    if len(set(paths)) != len(paths):
        raise QualificationContractError("qualification pytest roots are duplicated")
    if any("*" in path or "?" in path or "[" in path for path in paths):
        raise QualificationContractError(
            "qualification pytest collection paths cannot contain selection globs"
        )
    return [
        python,
        "-m",
        "pytest",
        *paths,
        "-q",
        f"--junitxml={junit_xml}",
        "-p",
        "novel_forge.tools.pytest_collection_evidence",
        f"--novel-forge-collection-report={collection_report}",
    ]


def build_backend_pytest_command(
    *,
    contracts: tuple[PytestCollectionContract, ...],
    python: str,
    junit_xml: Path,
    collection_report: Path,
) -> list[str]:
    if any(
        contract.classification != "BACKEND_NON_POSTGRESQL" for contract in contracts
    ):
        raise QualificationContractError(
            "backend pytest command received a PostgreSQL collection"
        )
    return _build_pytest_command(
        contracts=contracts,
        python=python,
        junit_xml=junit_xml,
        collection_report=collection_report,
    )


def build_postgres_pytest_command(
    *,
    contract: PytestCollectionContract,
    python: str,
    junit_xml: Path,
    collection_report: Path,
) -> list[str]:
    if contract.classification != "POSTGRESQL_REQUIRED":
        raise QualificationContractError(
            "PostgreSQL pytest command requires a PostgreSQL collection contract"
        )
    if contract.allow_skips:
        raise QualificationContractError(
            "PostgreSQL pytest collection must forbid skips"
        )
    return _build_pytest_command(
        contracts=(contract,),
        python=python,
        junit_xml=junit_xml,
        collection_report=collection_report,
    )


def _junit_collection_case_accounting(
    *, junit: Mapping[str, object], collection: Mapping[str, object]
) -> dict[str, object]:
    """COMPATIBILITY: unittest subtests add JUnit cases without adding pytest nodes."""
    junit_case_count = int(junit["tests"])
    collected_node_count = int(collection["collected_count"])
    if junit_case_count < collected_node_count:
        raise QualificationContractError(
            "JUnit reports fewer cases than pytest collected nodes"
        )
    return {
        "authority": "JUNIT_XML",
        "junit_case_count": junit_case_count,
        "collected_node_count": collected_node_count,
        "additional_junit_case_count": junit_case_count - collected_node_count,
    }


def validate_postgres_test_evidence(
    *,
    contract: PytestCollectionContract,
    junit_xml: Path,
    collection_report: Path,
    repo_root: Path,
    semantic_slices: Mapping[str, tuple[str, ...]],
) -> dict[str, object]:
    if contract.classification != "POSTGRESQL_REQUIRED":
        raise QualificationContractError(
            "PostgreSQL evidence requires a PostgreSQL collection contract"
        )
    junit = parse_junit_xml(junit_xml)
    collection = validate_collection_report(
        contract=contract,
        report_path=collection_report,
        repo_root=repo_root,
    )
    case_accounting = _junit_collection_case_accounting(
        junit=junit, collection=collection
    )
    if int(junit["skipped"]):
        raise QualificationContractError(
            "complete PostgreSQL qualification forbids test skips"
        )
    if int(junit["failures"]) or int(junit["errors"]):
        raise QualificationContractError(
            "PostgreSQL JUnit evidence contains failures or errors"
        )
    if int(collection["pytest_exit_status"]) != 0:
        raise QualificationContractError(
            "PostgreSQL pytest process did not report a successful exit"
        )

    source_files = set(collection["source_files"])
    declared_paths = tuple(path.rstrip("/") for path in contract.paths)
    slice_evidence: dict[str, list[str]] = {}
    for name, paths in semantic_slices.items():
        relevant = sorted(
            path
            for path in paths
            if any(
                path == declared or path.startswith(declared + "/")
                for declared in declared_paths
            )
        )
        if not relevant:
            continue
        missing = sorted(set(relevant) - source_files)
        if missing:
            raise QualificationContractError(
                f"PostgreSQL semantic slice {name} is missing tests: {missing}"
            )
        slice_evidence[str(name)] = relevant
    return {
        "schema_version": "novel-forge.postgresql-pytest-evidence.v1",
        "status": "PASS",
        "classification": contract.classification,
        "complete_collection": True,
        "junit": {
            **junit,
            "artifact": junit_xml.name,
            "digest": _content_digest(junit_xml.read_bytes()),
        },
        "collection": collection,
        "case_accounting": case_accounting,
        "semantic_slices": slice_evidence,
    }


def validate_backend_test_evidence(
    *,
    contracts: tuple[PytestCollectionContract, ...],
    junit_xml: Path,
    collection_report: Path,
    repo_root: Path,
) -> dict[str, object]:
    if not contracts or any(
        item.classification != "BACKEND_NON_POSTGRESQL" for item in contracts
    ):
        raise QualificationContractError(
            "backend evidence requires non-PostgreSQL collection contracts"
        )
    combined = PytestCollectionContract(
        name="backend",
        paths=tuple(path for item in contracts for path in item.paths),
        classification="BACKEND_NON_POSTGRESQL",
        complete_collection=True,
        allow_skips=any(item.allow_skips for item in contracts),
    )
    junit = parse_junit_xml(junit_xml)
    collection = validate_collection_report(
        contract=combined,
        report_path=collection_report,
        repo_root=repo_root,
    )
    case_accounting = _junit_collection_case_accounting(
        junit=junit, collection=collection
    )
    if int(junit["failures"]) or int(junit["errors"]):
        raise QualificationContractError(
            "backend JUnit evidence contains failures or errors"
        )
    if not combined.allow_skips and int(junit["skipped"]):
        raise QualificationContractError("backend qualification forbids test skips")
    if int(collection["pytest_exit_status"]) != 0:
        raise QualificationContractError(
            "backend pytest process did not report a successful exit"
        )
    return {
        "schema_version": "novel-forge.backend-pytest-evidence.v1",
        "status": "PASS",
        "junit": {
            **junit,
            "artifact": junit_xml.name,
            "digest": _content_digest(junit_xml.read_bytes()),
        },
        "collection": collection,
        "case_accounting": case_accounting,
        "collections": [
            {
                "name": item.name,
                "classification": item.classification,
                "paths": list(item.paths),
            }
            for item in contracts
        ],
    }


def _positive_compose_counter(value: object, *, field: str, minimum: int = 1) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise QualificationContractError(
            f"Compose runtime evidence field {field} must be at least {minimum}"
        )
    return value


def _validate_compose_operation(
    value: object, *, label: str, minimum_fencing_token: int
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise QualificationContractError(
            f"Compose runtime {label} operation evidence is missing"
        )
    operation_id = _required_text(
        value.get("operation_id"), field=f"Compose {label} operation_id"
    )
    if value.get("status") != "PASS" or value.get("operation_status") != "SUCCEEDED":
        raise QualificationContractError(
            f"Compose runtime {label} operation did not succeed"
        )
    _positive_compose_counter(
        value.get("attempt_count"), field=f"{label}.attempt_count"
    )
    _positive_compose_counter(value.get("lease_count"), field=f"{label}.lease_count")
    _positive_compose_counter(
        value.get("max_fencing_token"),
        field=f"{label}.max_fencing_token",
        minimum=minimum_fencing_token,
    )
    side_effect_fields = (
        "output_asset_count",
        "audit_count",
        "published_outbox_count",
    )
    try:
        for field in side_effect_fields:
            _positive_compose_counter(value.get(field), field=f"{label}.{field}")
    except QualificationContractError as exc:
        if label == "post-restart":
            raise QualificationContractError(
                "Compose post-restart authoritative side effect is incomplete"
            ) from exc
        raise
    if (
        value.get("fixture") is not True
        or value.get("real_provider_proven") is not False
    ):
        raise QualificationContractError(
            f"Compose runtime {label} operation evidence overclaims provider scope"
        )
    return {**dict(value), "operation_id": operation_id}


def _validate_worker_projection_snapshot(
    value: object, *, label: str, stopped: bool = False
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise QualificationContractError(
            f"Compose worker projection snapshot is missing: {label}"
        )
    status = _required_text(value.get("status"), field=f"worker restart {label}.status")
    drain_status = _required_text(
        value.get("drain_status"), field=f"worker restart {label}.drain_status"
    )
    if stopped:
        if status != "STOPPED" or drain_status != "DRAINED":
            raise QualificationContractError(
                "Compose worker projection did not observe a drained stop"
            )
    elif status not in {"READY", "BUSY"} or drain_status != "ACCEPTING":
        raise QualificationContractError(
            f"Compose worker projection is not ready after {label}"
        )
    _required_text(value.get("updated_at"), field=f"worker restart {label}.updated_at")
    _required_text(
        value.get("last_heartbeat_at"),
        field=f"worker restart {label}.last_heartbeat_at",
    )
    return dict(value)


def validate_compose_runtime_evidence(
    evidence: Mapping[str, object],
    *,
    expected_sha: str,
    expected_run_id: str,
    expected_project: str,
) -> dict[str, object]:
    if evidence.get("schema_version") != "novel-forge.compose-runtime-evidence.v1":
        raise QualificationContractError("unsupported Compose runtime evidence schema")
    if evidence.get("status") != "PASS":
        raise QualificationContractError("Compose runtime evidence is not PASS")
    if (
        evidence.get("commit_sha") != expected_sha
        or evidence.get("run_id") != expected_run_id
        or evidence.get("project_name") != expected_project
    ):
        raise QualificationContractError("Compose runtime evidence identity differs")
    required_steps = {
        "clean_compose_ready",
        "required_worker_fleet_ready",
        "synthetic_operation_completed",
        "pending_operation_recovered_after_worker_restart",
        "post_restart_operation_completed",
        "graceful_drain_released_connections",
    }
    steps = evidence.get("steps")
    if not isinstance(steps, list) or not required_steps.issubset(
        {str(item) for item in steps}
    ):
        raise QualificationContractError("Compose runtime proof steps are incomplete")

    normal = _validate_compose_operation(
        evidence.get("normal_operation"),
        label="pre-restart",
        minimum_fencing_token=1,
    )
    recovered = _validate_compose_operation(
        evidence.get("recovered_operation"),
        label="recovered",
        minimum_fencing_token=2,
    )
    post_restart = _validate_compose_operation(
        evidence.get("post_restart_operation"),
        label="post-restart",
        minimum_fencing_token=1,
    )
    operation_ids = {
        normal["operation_id"],
        recovered["operation_id"],
        post_restart["operation_id"],
    }
    if len(operation_ids) != 3:
        raise QualificationContractError(
            "Compose runtime proof requires three distinct operation identities"
        )

    expired = evidence.get("expired_lease")
    stale = evidence.get("stale_fence")
    if (
        not isinstance(expired, Mapping)
        or not str(expired.get("attempt_id") or "")
        or not isinstance(stale, Mapping)
        or stale.get("status") != "PASS"
        or not str(stale.get("rejected_error_code") or "")
    ):
        raise QualificationContractError(
            "Compose runtime recovery lacks expired-lease or stale-fence evidence"
        )

    restart = evidence.get("worker_restart")
    if not isinstance(restart, Mapping):
        raise QualificationContractError("Compose worker restart evidence is missing")
    _required_text(restart.get("worker_id"), field="worker restart worker_id")
    _required_text(restart.get("worker_kind"), field="worker restart worker_kind")
    snapshots = {
        "before_stop": _validate_worker_projection_snapshot(
            restart.get("before_stop"), label="before_stop"
        ),
        "stopped": _validate_worker_projection_snapshot(
            restart.get("stopped"), label="stopped", stopped=True
        ),
        "after_recovery_start": _validate_worker_projection_snapshot(
            restart.get("after_recovery_start"), label="after_recovery_start"
        ),
        "before_forced_restart": _validate_worker_projection_snapshot(
            restart.get("before_forced_restart"), label="before_forced_restart"
        ),
        "after_forced_restart": _validate_worker_projection_snapshot(
            restart.get("after_forced_restart"), label="after_forced_restart"
        ),
    }
    if (
        restart.get("projection_changed") is not True
        or snapshots["before_stop"]["updated_at"] == snapshots["stopped"]["updated_at"]
        or snapshots["stopped"]["updated_at"]
        == snapshots["after_recovery_start"]["updated_at"]
        or snapshots["before_forced_restart"]["updated_at"]
        == snapshots["after_forced_restart"]["updated_at"]
    ):
        raise QualificationContractError(
            "Compose worker restart is not bound to changed health projection evidence"
        )
    container_before = restart.get("container_before_forced_restart")
    container_after = restart.get("container_after_forced_restart")
    if (
        not isinstance(container_before, Mapping)
        or not isinstance(container_after, Mapping)
        or not str(container_before.get("container_id") or "")
        or not str(container_after.get("container_id") or "")
        or not str(container_before.get("started_at") or "")
        or not str(container_after.get("started_at") or "")
        or container_before.get("started_at") == container_after.get("started_at")
    ):
        raise QualificationContractError(
            "Compose worker restart lacks changed container lifecycle evidence"
        )

    governance = evidence.get("shutdown_database_governance")
    if not isinstance(governance, Mapping) or any(
        governance.get(field) != 0
        for field in (
            "idle_in_transaction",
            "active_transactions",
            "worker_connections",
        )
    ):
        raise QualificationContractError(
            "Compose graceful drain left database activity"
        )
    _positive_compose_counter(
        evidence.get("drained_worker_count"), field="drained_worker_count"
    )
    cleanup = evidence.get("cleanup")
    if (
        not isinstance(cleanup, Mapping)
        or cleanup.get("status") != "PASS"
        or type(cleanup.get("remaining_resource_count")) is not int
        or cleanup.get("remaining_resource_count") != 0
        or cleanup.get("run_id") != expected_run_id
        or cleanup.get("compose_project") != expected_project
        or cleanup.get("receipt")
        != f"compose-resource-ownership-{expected_project}.json"
    ):
        raise QualificationContractError(
            "Compose runtime ownership-checked cleanup is incomplete"
        )
    _positive_compose_counter(
        cleanup.get("resource_count"), field="cleanup.resource_count"
    )
    if (
        evidence.get("fixture") is not True
        or evidence.get("real_provider_proven") is not False
        or evidence.get("longform_proven") is not False
        or evidence.get("production_verified") is not False
    ):
        raise QualificationContractError("Compose runtime evidence exceeds its ceiling")
    return dict(evidence)


__all__ = [
    "COLLECTION_CLASSIFICATIONS",
    "MIGRATION_MANIFEST",
    "QUALIFICATION_MANIFEST",
    "QUALIFICATION_SCHEMA_VERSION",
    "PytestCollectionContract",
    "P0_PROOF_SCOPE",
    "QualificationContractError",
    "QualificationManifest",
    "REQUIRED_GATE_ORDER",
    "REQUIRED_SEMANTIC_SLICES",
    "expected_migration_head",
    "load_qualification_manifest",
    "parse_junit_xml",
    "resolved_dependency_snapshot",
    "sanitize_evidence",
    "validate_resolved_dependency_snapshot",
    "validate_collection_report",
    "build_postgres_pytest_command",
    "build_backend_pytest_command",
    "validate_postgres_test_evidence",
    "validate_backend_test_evidence",
    "validate_compose_runtime_evidence",
]
