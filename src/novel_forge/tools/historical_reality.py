from __future__ import annotations

import argparse
from datetime import datetime, timezone
from fnmatch import fnmatch
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from novel_forge.tools.instruction_surface import check_instruction_surface
from novel_forge.tools.test_reality import check_test_reality


POLICY_PATH = Path("architecture/manifests/historical-reality-policy.yaml")
POLICY_SCHEMA = "novel-forge.historical-reality-policy.v1"
REPORT_SCHEMA = "novel-forge.historical-reality.v1"
PROOF_SCOPE_SCHEMA = "novel-forge.qualification-proof-scope.v1"
STALE_DELIVERY_REFERENCE = re.compile(
    r"(?:\bWP-[A-Z0-9_-]+\b|\bPR\s*#\d+\b|\bADR[-_ ]?\d+\b)",
    re.IGNORECASE,
)
TEXT_SUFFIXES = frozenset(
    {".json", ".js", ".md", ".mjs", ".py", ".toml", ".ts", ".tsx", ".yaml", ".yml"}
)


def load_historical_reality_policy(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    payload = json.loads((root / POLICY_PATH).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != POLICY_SCHEMA:
        raise ValueError("historical reality policy schema is invalid")
    return payload


def validate_proof_scope(
    proof_scope: object, *, policy: Mapping[str, Any]
) -> list[str]:
    errors: list[str] = []
    if not isinstance(proof_scope, Mapping):
        return ["proof_scope must be an object"]
    expected_fields = {
        "schema_version",
        "fact_type",
        "proves",
        "ceiling",
        "does_not_establish",
    }
    supplied_fields = set(proof_scope)
    if supplied_fields != expected_fields:
        errors.append("proof_scope fields differ from the typed contract")
    if proof_scope.get("schema_version") != PROOF_SCOPE_SCHEMA:
        errors.append("proof_scope schema is invalid")
    expected_fact_type = dict(policy["fact_types"])["current_qualification"]
    if proof_scope.get("fact_type") != expected_fact_type:
        errors.append("proof_scope fact_type is not current qualification evidence")
    retired = set(policy["retired_current_ontology"])
    proves = proof_scope.get("proves")
    if not isinstance(proves, list) or not proves or len(proves) != len(set(proves)):
        errors.append("proof_scope.proves must be a non-empty unique list")
    else:
        allowed = set(policy["current_capabilities"])
        for value in proves:
            if value in retired:
                errors.append(
                    f"proof_scope.proves contains a retired current ontology: {value}"
                )
            elif value not in allowed:
                errors.append(f"proof_scope.proves contains an unknown capability: {value}")
    if proof_scope.get("ceiling") not in set(policy["allowed_proof_ceilings"]):
        errors.append("proof_scope.ceiling is not allowed")
    excluded = proof_scope.get("does_not_establish")
    if (
        not isinstance(excluded, list)
        or not excluded
        or len(excluded) != len(set(excluded))
    ):
        errors.append("proof_scope.does_not_establish must be a non-empty unique list")
    else:
        allowed = set(policy["allowed_unestablished_evidence_classes"])
        for value in excluded:
            if value not in allowed:
                errors.append(
                    "proof_scope.does_not_establish contains an unknown evidence class: "
                    + str(value)
                )
    return errors


def _surface_files(root: Path, policy: Mapping[str, Any]) -> tuple[Path, ...]:
    exclusions = tuple(str(value) for value in policy["authority_surface_exclusions"])
    discovered: set[Path] = set()
    for relative in policy["authority_surface_roots"]:
        candidate = root / str(relative)
        if candidate.is_file():
            discovered.add(candidate)
        elif candidate.is_dir():
            discovered.update(item for item in candidate.rglob("*") if item.is_file())
    return tuple(
        sorted(
            item
            for item in discovered
            if (
                item.name == "Makefile"
                or item.suffix.lower() in TEXT_SUFFIXES
            )
            and not any(
                fnmatch(item.relative_to(root).as_posix(), pattern)
                for pattern in exclusions
            )
        )
    )


def _historical_authorization_evidence(
    root: Path, policy: Mapping[str, Any]
) -> tuple[set[Path], list[str]]:
    excluded: set[Path] = set()
    errors: list[str] = []
    entries = policy.get("immutable_historical_authorization_evidence", {})
    if not isinstance(entries, Mapping):
        return excluded, ["immutable historical authorization evidence must be a map"]
    for relative, identity in entries.items():
        name = str(relative)
        path = root / name
        if (
            not name.startswith("config/production/narrative-closure/authorization-")
            or path.suffix != ".json"
            or not path.resolve().is_relative_to(root)
        ):
            errors.append(f"invalid historical authorization path: {relative}")
            continue
        try:
            raw = path.read_bytes()
            payload = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            errors.append(f"historical authorization is missing or invalid: {relative}")
            continue
        if (
            not isinstance(payload, Mapping)
            or not isinstance(identity, Mapping)
            or sha256(raw).hexdigest() != identity.get("sha256")
        ):
            errors.append(f"historical authorization content changed: {relative}")
            continue
        disposition = identity.get("disposition")
        if disposition == "NON_AUTHORIZATION_REQUEST":
            valid = payload.get("status") == "NOT_AUTHORIZATION"
        elif disposition == "EXPIRED_AUTHORIZATION":
            try:
                expiry = datetime.fromisoformat(str(payload["expires_at"]).replace("Z", "+00:00"))
                valid = expiry.tzinfo is not None and expiry < datetime.now(timezone.utc)
            except (KeyError, TypeError, ValueError):
                valid = False
        else:
            valid = False
        if valid:
            excluded.add(path)
        else:
            errors.append(f"historical authorization disposition is not established: {relative}")
    return excluded, errors


def _walk_machine_fields(value: object) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key)
            yield from _walk_machine_fields(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_machine_fields(child)


def _machine_field_violations(
    root: Path, files: Iterable[Path], *, forbidden: set[str]
) -> list[str]:
    violations: list[str] = []
    for file_path in files:
        if file_path.suffix.lower() not in {".json", ".yaml", ".yml"}:
            continue
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        for field in _walk_machine_fields(payload):
            if field in forbidden:
                violations.append(
                    f"{file_path.relative_to(root).as_posix()}: forbidden field {field}"
                )
    return violations


def _validate_reality_projection(
    root: Path, policy: Mapping[str, Any]
) -> list[str]:
    errors: list[str] = []
    reality_path = root / "architecture/reality-evidence.json"
    backend_path = root / "architecture/manifests/backend-qualification-manifest.yaml"
    reality = json.loads(reality_path.read_text(encoding="utf-8"))
    backend = json.loads(backend_path.read_text(encoding="utf-8"))
    fact_types = dict(policy["fact_types"])
    if reality.get("fact_type_policy") != fact_types:
        errors.append("reality fact_type_policy differs from historical reality policy")
    capabilities = reality.get("capabilities")
    if not isinstance(capabilities, list):
        errors.append("reality capabilities must be a list")
    else:
        observed = []
        for index, capability in enumerate(capabilities):
            if not isinstance(capability, Mapping):
                errors.append(f"capabilities[{index}] must be an object")
                continue
            observed.append(str(capability.get("concept") or ""))
            if capability.get("fact_type") != fact_types["current_runtime"]:
                errors.append(f"capabilities[{index}] is not a current runtime fact")
            if capability.get("proof_ceiling") not in set(
                policy["allowed_proof_ceilings"]
            ):
                errors.append(f"capabilities[{index}] proof ceiling is not allowed")
        if observed != list(policy["current_capabilities"]):
            errors.append("reality capability concepts differ from the current allowlist")
    runs = reality.get("qualification_runs")
    if not isinstance(runs, list):
        errors.append("reality qualification_runs must be a list")
    else:
        for index, run in enumerate(runs):
            if not isinstance(run, Mapping):
                errors.append(f"qualification_runs[{index}] must be an object")
                continue
            run_fact_type = run.get("fact_type")
            if run_fact_type not in {
                fact_types["current_qualification"],
                fact_types["historical_compatibility"],
            }:
                errors.append(
                    f"qualification_runs[{index}] has an invalid fact type"
                )
            if run_fact_type == fact_types["current_qualification"]:
                errors.extend(
                    f"qualification_runs[{index}]: {message}"
                    for message in validate_proof_scope(
                        run.get("proof_scope"), policy=policy
                    )
                )
    backend_scope = backend.get("proof_scope")
    errors.extend(
        "backend qualification: " + message
        for message in validate_proof_scope(backend_scope, policy=policy)
    )
    if backend_scope != policy.get("backend_proof_scope"):
        errors.append("backend proof_scope differs from the canonical policy")
    return errors


def check_historical_reality(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    try:
        policy = load_historical_reality_policy(root)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return {
            "schema_version": REPORT_SCHEMA,
            "status": "FAIL",
            "errors": [f"cannot load historical reality policy: {exc}"],
        }
    historical_evidence, historical_errors = _historical_authorization_evidence(root, policy)
    files = tuple(path for path in _surface_files(root, policy) if path not in historical_evidence)
    retired_tokens = tuple(str(value) for value in policy["retired_current_ontology"])
    token_violations: list[str] = []
    stale_delivery: list[str] = []
    eight_references: list[str] = []
    text_by_path: dict[str, str] = {}
    for file_path in files:
        relative = file_path.relative_to(root).as_posix()
        try:
            text = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        text_by_path[relative] = text
        for token in retired_tokens:
            count = text.count(token)
            token_violations.extend(f"{relative}: retired ontology {token}" for _ in range(count))
            if token == "EIGHT_CHAPTER":
                eight_references.extend(relative for _ in range(count))
        stale_delivery.extend(
            f"{relative}: stale delivery reference {match.group(0)}"
            for match in STALE_DELIVERY_REFERENCE.finditer(text)
        )
    field_violations = _machine_field_violations(
        root,
        files,
        forbidden=set(policy["forbidden_machine_fields"]),
    )
    retired_paths = [
        str(relative)
        for relative in policy["retired_paths"]
        if (root / str(relative)).exists()
    ]
    instruction_report = check_instruction_surface(root)
    instruction_violations: list[str] = []
    for item in instruction_report.get("sources", []):
        relative = str(item.get("path") or "")
        text = text_by_path.get(relative, "")
        if any(token in text for token in retired_tokens) or STALE_DELIVERY_REFERENCE.search(text):
            instruction_violations.append(relative)
    test_report = check_test_reality(root)
    retired_test_paths = set(
        relative for relative in retired_paths if relative.startswith("tests/")
    )
    historical_tests = set(retired_test_paths)
    for item in test_report.get("files", []):
        if not isinstance(item, Mapping):
            continue
        classification = str(item.get("classification") or "")
        targets = tuple(str(value) for value in item.get("production_targets", []))
        if classification.startswith("CURRENT_") and any(
            "/runtime_proof/" in target for target in targets
        ):
            historical_tests.add(str(item.get("path") or ""))
        if classification == "HISTORICAL_REDUNDANT":
            historical_tests.add(str(item.get("path") or ""))
    projection_errors = _validate_reality_projection(root, policy)
    errors = sorted(
        set(
            token_violations
            + stale_delivery
            + field_violations
            + [f"retired path remains: {value}" for value in retired_paths]
            + [f"historical test authority remains: {value}" for value in historical_tests]
            + [f"historical instruction remains: {value}" for value in instruction_violations]
            + projection_errors
            + historical_errors
        )
    )
    return {
        "schema_version": REPORT_SCHEMA,
        "status": "PASS" if not errors else "FAIL",
        "fact_types": dict(policy["fact_types"]),
        "authority_surface_file_count": len(files),
        "historical_roadmap_authority_count": len(
            token_violations + field_violations + retired_paths
        ),
        "eight_chapter_canonical_reference_count": len(eight_references),
        "stale_wp_pr_adr_roadmap_authority_count": len(stale_delivery),
        "unmanaged_historical_instruction_count": len(set(instruction_violations)),
        "historical_test_authority_count": len(historical_tests),
        "retired_path_count": len(retired_paths),
        "forbidden_machine_field_count": len(field_violations),
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify that repository facts cannot act as a historical roadmap."
    )
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args(argv)
    report = check_historical_reality(args.repo_root)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
