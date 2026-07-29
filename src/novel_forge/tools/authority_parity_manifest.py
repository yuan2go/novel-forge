"""Typed loader and CI validator for business Authority parity."""
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Any

from novel_forge.modules.book_followup_authority.definitions import (
    book_followup_operation_definitions,
)
from novel_forge.modules.book_followup_authority.registry import (
    BookFollowupHandlerRegistry,
)
from novel_forge.modules.chapter_authority.contracts import ChapterNode
from novel_forge.modules.chapter_authority.definitions import (
    CHAPTER_SLICE_ROOT_DEFINITION_NAME,
    CHAPTER_SLICE_ROOT_HANDLER_KEY,
    chapter_operation_definitions,
    chapter_root_operation_definition,
)
from novel_forge.modules.chapter_production_bus.service import (
    CHAPTER_PRODUCTION_STEPS,
)


class AuthorityParityStatus(str, Enum):
    NOT_MAPPED = "NOT_MAPPED"
    PARTIALLY_MAPPED = "PARTIALLY_MAPPED"
    MAPPED_NOT_TESTED = "MAPPED_NOT_TESTED"
    TESTED_WITH_FAKE = "TESTED_WITH_FAKE"
    TESTED_WITH_REAL_PROVIDER = "TESTED_WITH_REAL_PROVIDER"
    PRODUCTION_PROVEN = "PRODUCTION_PROVEN"
    DEPRECATED = "DEPRECATED"


@dataclass(frozen=True, slots=True)
class AuthorityParityCapability:
    legacy_step: str
    business_capability: str
    authority_command: str
    operation_type: str
    operation_definition: tuple[str, ...]
    handler: tuple[str, ...]
    input_contract: str
    input_asset_versions: tuple[str, ...]
    output_contract: str
    output_asset_versions: tuple[str, ...]
    external_effects: tuple[str, ...]
    idempotency_scope: str
    retry_policy: str
    cancel_policy: str
    timeout_policy: str
    lease_policy: str
    fencing_policy: str
    failure_classification: str
    compensation_or_recovery: str
    projection: tuple[str, ...]
    evidence: tuple[str, ...]
    production_status: str
    parity_status: AuthorityParityStatus
    known_gap: str


@dataclass(frozen=True, slots=True)
class AuthorityParityManifest:
    schema_version: str
    authority: str
    evidence_boundary: dict[str, bool]
    capabilities: tuple[AuthorityParityCapability, ...]


@dataclass(frozen=True, slots=True)
class AuthorityParityReport:
    manifest: AuthorityParityManifest
    legacy_capabilities: int
    fully_mapped: int
    production_enabled: int
    direct_write_bypasses: int
    duplicate_steps: tuple[str, ...]
    missing_steps: tuple[str, ...]
    unexpected_steps: tuple[str, ...]
    missing_definitions: tuple[str, ...]
    missing_handlers: tuple[str, ...]
    missing_output_contracts: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "PASS" if self.passed else "FAIL",
            "legacy_capabilities": self.legacy_capabilities,
            "fully_mapped": self.fully_mapped,
            "production_enabled": self.production_enabled,
            "direct_write_bypasses": self.direct_write_bypasses,
            "duplicate_steps": list(self.duplicate_steps),
            "missing_steps": list(self.missing_steps),
            "unexpected_steps": list(self.unexpected_steps),
            "missing_definitions": list(self.missing_definitions),
            "missing_handlers": list(self.missing_handlers),
            "missing_output_contracts": list(self.missing_output_contracts),
            "errors": list(self.errors),
            "evidence_boundary": dict(self.manifest.evidence_boundary),
        }


def load_authority_parity_manifest(path: str | Path) -> AuthorityParityManifest:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    capabilities = []
    for item in payload.get("capabilities") or ():
        capabilities.append(
            AuthorityParityCapability(
                legacy_step=str(item["legacy_step"]),
                business_capability=str(item["business_capability"]),
                authority_command=str(item["authority_command"]),
                operation_type=str(item["operation_type"]),
                operation_definition=tuple(item["operation_definition"]),
                handler=tuple(item["handler"]),
                input_contract=str(item["input_contract"]),
                input_asset_versions=tuple(item["input_asset_versions"]),
                output_contract=str(item["output_contract"]),
                output_asset_versions=tuple(item["output_asset_versions"]),
                external_effects=tuple(item["external_effects"]),
                idempotency_scope=str(item["idempotency_scope"]),
                retry_policy=str(item["retry_policy"]),
                cancel_policy=str(item["cancel_policy"]),
                timeout_policy=str(item["timeout_policy"]),
                lease_policy=str(item["lease_policy"]),
                fencing_policy=str(item["fencing_policy"]),
                failure_classification=str(item["failure_classification"]),
                compensation_or_recovery=str(item["compensation_or_recovery"]),
                projection=tuple(item["projection"]),
                evidence=tuple(item["evidence"]),
                production_status=str(item["production_status"]),
                parity_status=AuthorityParityStatus(str(item["parity_status"])),
                known_gap=str(item.get("known_gap") or ""),
            )
        )
    boundary = payload.get("evidence_boundary")
    if not isinstance(boundary, dict) or any(
        not isinstance(value, bool) for value in boundary.values()
    ):
        raise ValueError("authority parity evidence boundary must contain booleans")
    return AuthorityParityManifest(
        schema_version=str(payload["schema_version"]),
        authority=str(payload["authority"]),
        evidence_boundary=dict(boundary),
        capabilities=tuple(capabilities),
    )


def validate_authority_parity_manifest(
    path: str | Path, *, repo_root: str | Path
) -> AuthorityParityReport:
    manifest = load_authority_parity_manifest(path)
    expected = set(CHAPTER_PRODUCTION_STEPS)
    steps = [item.legacy_step for item in manifest.capabilities]
    duplicate_steps = tuple(sorted({step for step in steps if steps.count(step) > 1}))
    missing_steps = tuple(sorted(expected - set(steps)))
    unexpected_steps = tuple(sorted(set(steps) - expected))

    definitions = _operation_definitions()
    registered_handlers = _registered_handlers()
    referenced_definitions = {
        definition
        for entry in manifest.capabilities
        for definition in entry.operation_definition
    }
    referenced_handlers = {
        handler for entry in manifest.capabilities for handler in entry.handler
    }
    missing_definitions = tuple(sorted(referenced_definitions - definitions.keys()))
    missing_handlers = tuple(sorted(referenced_handlers - registered_handlers))
    missing_output_contracts = tuple(
        sorted(
            name
            for name in referenced_definitions & definitions.keys()
            if not definitions[name].get("output_contract")
        )
    )
    direct_write_bypasses = _production_direct_write_bypasses(Path(repo_root))
    fully_mapped = sum(
        bool(entry.operation_definition and entry.handler and entry.output_asset_versions)
        and entry.parity_status
        not in {
            AuthorityParityStatus.NOT_MAPPED,
            AuthorityParityStatus.PARTIALLY_MAPPED,
        }
        for entry in manifest.capabilities
    )
    production_enabled = sum(
        entry.production_status == "ENABLED_POSTGRESQL"
        for entry in manifest.capabilities
    )
    errors: list[str] = []
    for label, values in (
        ("duplicate legacy steps", duplicate_steps),
        ("missing legacy steps", missing_steps),
        ("unexpected legacy steps", unexpected_steps),
        ("missing operation definitions", missing_definitions),
        ("missing handlers", missing_handlers),
        ("missing output contracts", missing_output_contracts),
    ):
        if values:
            errors.append(f"{label}: {', '.join(values)}")
    if direct_write_bypasses:
        errors.append(f"production direct-write bypasses: {direct_write_bypasses}")
    if fully_mapped != len(CHAPTER_PRODUCTION_STEPS):
        errors.append(
            f"fully mapped {fully_mapped}/{len(CHAPTER_PRODUCTION_STEPS)}"
        )
    if production_enabled != len(CHAPTER_PRODUCTION_STEPS):
        errors.append(
            f"production enabled {production_enabled}/{len(CHAPTER_PRODUCTION_STEPS)}"
        )
    if manifest.evidence_boundary.get("real_provider_proven") is not False:
        errors.append("real provider evidence boundary must remain false")
    if manifest.evidence_boundary.get("production_verified") is not False:
        errors.append("production verification evidence boundary must remain false")
    return AuthorityParityReport(
        manifest=manifest,
        legacy_capabilities=len(CHAPTER_PRODUCTION_STEPS),
        fully_mapped=fully_mapped,
        production_enabled=production_enabled,
        direct_write_bypasses=direct_write_bypasses,
        duplicate_steps=duplicate_steps,
        missing_steps=missing_steps,
        unexpected_steps=unexpected_steps,
        missing_definitions=missing_definitions,
        missing_handlers=missing_handlers,
        missing_output_contracts=missing_output_contracts,
        errors=tuple(errors),
    )


def _operation_definitions() -> dict[str, dict[str, Any]]:
    build = "authority-parity-validator"
    commit = "0" * 40
    definitions = (
        chapter_root_operation_definition(
            application_build_id=build,
            commit_sha=commit,
            model_effects_required=True,
        ),
        *chapter_operation_definitions(
            application_build_id=build,
            commit_sha=commit,
            model_effects_required=True,
        ),
        *book_followup_operation_definitions(
            application_build_id=build,
            commit_sha=commit,
        ),
    )
    return {str(item["name"]): item for item in definitions}


def _registered_handlers() -> set[str]:
    return {
        CHAPTER_SLICE_ROOT_HANDLER_KEY,
        *(node.handler_key for node in ChapterNode),
        *BookFollowupHandlerRegistry().available_handler_keys,
    }


def _production_direct_write_bypasses(repo_root: Path) -> int:
    roots = (
        repo_root / "src" / "novel_forge" / "modules" / "chapter_authority",
        repo_root / "src" / "novel_forge" / "modules" / "book_authority",
        repo_root / "src" / "novel_forge" / "modules" / "book_followup_authority",
    )
    count = 0
    for root in roots:
        for path in root.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = (
                        [alias.name for alias in node.names]
                        if isinstance(node, ast.Import)
                        else [str(node.module or "")]
                    )
                    if any(name.endswith("storage.local") for name in names):
                        count += 1
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"write_asset", "write_asset_auto", "write_json"}
                ):
                    count += 1
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        default="config/authority/authority-parity-manifest.json",
    )
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args(argv)
    report = validate_authority_parity_manifest(
        args.manifest, repo_root=args.repo_root
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AuthorityParityCapability",
    "AuthorityParityManifest",
    "AuthorityParityReport",
    "AuthorityParityStatus",
    "load_authority_parity_manifest",
    "main",
    "validate_authority_parity_manifest",
]
