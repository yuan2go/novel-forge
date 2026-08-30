"""Fail-closed contracts for P0 backend engineering qualification."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


QUALIFICATION_MANIFEST = Path(
    "architecture/manifests/backend-qualification-manifest.yaml"
)
QUALIFICATION_SCHEMA_VERSION = "novel-forge.backend-qualification-manifest.v1"
COLLECTION_CLASSIFICATIONS = frozenset(
    {"BACKEND_NON_POSTGRESQL", "POSTGRESQL_REQUIRED"}
)


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


__all__ = [
    "COLLECTION_CLASSIFICATIONS",
    "QUALIFICATION_MANIFEST",
    "QUALIFICATION_SCHEMA_VERSION",
    "PytestCollectionContract",
    "QualificationContractError",
    "QualificationManifest",
    "load_qualification_manifest",
]
