"""Fail-closed contracts for P0 backend engineering qualification."""
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
QUALIFICATION_SCHEMA_VERSION = "novel-forge.backend-qualification-manifest.v1"
COLLECTION_CLASSIFICATIONS = frozenset(
    {"BACKEND_NON_POSTGRESQL", "POSTGRESQL_REQUIRED"}
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
    """Raised when qualification inputs cannot support a trustworthy result."""


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
    evidence_ceilings: Mapping[str, str]


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise QualificationContractError(f"qualification manifest is missing: {path}") from exc
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
        raise QualificationContractError(f"qualification manifest field is empty: {field}")
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
    """Load and validate the repository's canonical backend qualification policy."""
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
        name = _required_text(item.get("name"), field=f"pytest_collections[{index}].name")
        if name in names:
            raise QualificationContractError(f"duplicate pytest collection name: {name}")
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
        if not isinstance(complete_collection, bool) or not isinstance(allow_skips, bool):
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

    raw_slices = payload.get("semantic_slices")
    if not isinstance(raw_slices, dict) or not raw_slices:
        raise QualificationContractError("semantic_slices must be a non-empty object")
    semantic_slices: dict[str, tuple[str, ...]] = {}
    for name, values in raw_slices.items():
        if not isinstance(values, list) or not values:
            raise QualificationContractError(f"semantic slice {name} has no test modules")
        paths = tuple(
            _relative_path(value, field=f"semantic_slices.{name}") for value in values
        )
        missing = [path for path in paths if not (root / path).is_file()]
        if missing:
            raise QualificationContractError(
                f"semantic slice {name} references missing tests: {', '.join(missing)}"
            )
        semantic_slices[str(name)] = paths

    raw_ceilings = payload.get("evidence_ceilings")
    if not isinstance(raw_ceilings, dict) or not raw_ceilings:
        raise QualificationContractError("evidence_ceilings must be a non-empty object")
    evidence_ceilings = {
        _required_text(key, field="evidence_ceilings key"): _required_text(
            value, field=f"evidence_ceilings.{key}"
        )
        for key, value in raw_ceilings.items()
    }
    return QualificationManifest(
        schema_version=schema_version,
        migration_manifest=migration_manifest,
        pytest_collections=tuple(collections),
        required_gates=required_gates,
        semantic_slices=MappingProxyType(semantic_slices),
        evidence_ceilings=MappingProxyType(evidence_ceilings),
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
    """Read pytest results from JUnit XML without consulting terminal output."""
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
        _junit_integer(source.get("errors", "0"), field="errors")
        for source in sources
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
    """Return the manifest-owned head after cross-checking the runtime registry."""
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
    """Resolve the target interpreter's installed package identity without pip."""
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
            raise QualificationContractError("dependency package entry is not an object")
        name = DEPENDENCY_NAME_SEPARATOR.sub(
            "-", _required_text(item.get("name"), field="dependency name").lower()
        )
        version = _required_text(item.get("version"), field=f"dependency {name} version")
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
    return {
        "schema_version": "novel-forge.resolved-dependency-snapshot.v1",
        **identity,
        "package_count": len(packages),
        "digest": digest,
        "reproducibility_class": (
            "CONSTRAINTS_BOUND_RESOLVED_SNAPSHOT"
            if provenance
            else "RESOLVED_SNAPSHOT"
        ),
        "git_sha_alone_reproducible": False,
    }


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
    """Return a JSON-safe copy with credentials and connection URLs removed."""
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
    """Verify that pytest collected every test source in a declared root."""
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
    expected_files = {
        path.relative_to(root).as_posix()
        for relative in contract.paths
        for path in (root / relative).rglob("test_*.py")
        if path.is_file()
    }
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


__all__ = [
    "COLLECTION_CLASSIFICATIONS",
    "MIGRATION_MANIFEST",
    "QUALIFICATION_MANIFEST",
    "QUALIFICATION_SCHEMA_VERSION",
    "PytestCollectionContract",
    "QualificationContractError",
    "QualificationManifest",
    "expected_migration_head",
    "load_qualification_manifest",
    "parse_junit_xml",
    "resolved_dependency_snapshot",
    "sanitize_evidence",
    "validate_collection_report",
]
