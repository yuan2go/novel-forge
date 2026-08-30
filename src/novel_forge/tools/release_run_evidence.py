"""INVARIANT: release proof is a CI artifact bound to the tested Git SHA, not a checked-in run narrative."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from novel_forge.tools.backend_qualification_contract import (
    REQUIRED_GATE_ORDER,
    validate_resolved_dependency_snapshot,
)


GIT_SHA = re.compile(r"[0-9a-f]{40}")
CONTENT_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
REQUIRED_ARTIFACT_FILES = {
    "reality_inventory": "documentation-reality-{sha}.json",
    "test_result": "test-result-{sha}.json",
    "migration_result": "migration-{sha}.log",
    "compose_evidence": "authority-compose-{sha}.json",
    "query_plan_evidence": "query-plan-{sha}.json",
    "worker_fleet_evidence": "worker-fleet-summary-{sha}.json",
    "docker_image_digest": "docker-image-digest-{sha}.json",
    "environment_metadata": "environment-metadata-{sha}.json",
}
P0_EVIDENCE_CEILINGS = {
    "CURRENT_UI": "DEFERRED / NOT_RUN_BY_SCOPE",
    "REAL_PROVIDER": "NOT_RUN_BY_SCOPE",
    "HISTORICAL_ORPHAN_MUTATION": "NOT_RUN_BY_SCOPE",
    "EIGHT_CHAPTER": "NOT_RUN_BY_SCOPE",
    "HUMAN_REVIEW": "NOT_RUN_BY_SCOPE",
    "LONGFORM": "NOT_PROVEN",
    "MULTIBOOK": "NOT_PROVEN",
    "PRODUCTION": "NOT_PROVEN",
}


def _validated_sha(commit_sha: str) -> str:
    value = commit_sha.strip().lower()
    if not GIT_SHA.fullmatch(value):
        raise ValueError("commit SHA must be a full lowercase Git SHA")
    return value


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _artifact_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _required_gate_evidence(
    gates: Sequence[Mapping[str, Any]], gate_id: str
) -> Mapping[str, Any]:
    matches = [gate for gate in gates if gate.get("gate_id") == gate_id]
    if len(matches) != 1 or not isinstance(matches[0].get("evidence"), Mapping):
        raise ValueError(f"P0 qualification gate evidence is missing: {gate_id}")
    return matches[0]["evidence"]


def _required_artifact_evidence(
    evidence: Mapping[str, Any], *, evidence_name: str
) -> None:
    if not str(evidence.get("artifact") or "") or not CONTENT_DIGEST.fullmatch(
        str(evidence.get("digest") or "")
    ):
        raise ValueError(f"{evidence_name} artifact identity is invalid")


def _validate_pytest_gate_evidence(
    evidence: Mapping[str, Any], *, expected_schema: str, evidence_name: str
) -> None:
    if evidence.get("schema_version") != expected_schema or evidence.get(
        "status"
    ) != "PASS":
        raise ValueError(f"{evidence_name} structured evidence is not PASS")
    junit = evidence.get("junit")
    collection = evidence.get("collection")
    accounting = evidence.get("case_accounting")
    if not all(
        isinstance(item, Mapping) for item in (junit, collection, accounting)
    ):
        raise ValueError(f"{evidence_name} machine evidence is incomplete")
    tests = junit.get("tests")
    passed = junit.get("passed")
    duration = junit.get("duration_seconds")
    if (
        not isinstance(tests, int)
        or isinstance(tests, bool)
        or tests < 1
        or passed != tests
        or junit.get("failures") != 0
        or junit.get("errors") != 0
        or junit.get("skipped") != 0
        or not isinstance(duration, (int, float))
        or isinstance(duration, bool)
        or duration < 0
    ):
        raise ValueError(f"{evidence_name} JUnit summary is not zero-skip PASS")
    _required_artifact_evidence(junit, evidence_name=f"{evidence_name} JUnit")

    collected = collection.get("collected_count")
    source_files = collection.get("source_file_count")
    if (
        collection.get("complete_collection") is not True
        or not isinstance(collected, int)
        or isinstance(collected, bool)
        or collected < 1
        or not isinstance(source_files, int)
        or isinstance(source_files, bool)
        or source_files < 1
        or collection.get("pytest_exit_status") != 0
        or not CONTENT_DIGEST.fullmatch(
            str(collection.get("report_digest") or "")
        )
    ):
        raise ValueError(f"{evidence_name} complete collection evidence is invalid")
    if (
        accounting.get("authority") != "JUNIT_XML"
        or accounting.get("junit_case_count") != tests
        or accounting.get("collected_node_count") != collected
        or accounting.get("additional_junit_case_count") != tests - collected
        or tests < collected
    ):
        raise ValueError(f"{evidence_name} JUnit/collection accounting is invalid")


def _validate_p0_gate_evidence(
    *,
    gates: Sequence[Mapping[str, Any]],
    tested_sha: str,
    source_tree: str,
    expected_migration_head: str,
) -> None:
    source = _required_gate_evidence(gates, "source-preflight")
    if (
        source.get("commit_sha") != tested_sha
        or source.get("source_tree") != source_tree
        or source.get("dirty") is not False
    ):
        raise ValueError("P0 source-preflight evidence identity differs")

    documentation = _required_gate_evidence(gates, "documentation-reality")
    documentation_counts = {
        field: documentation.get(field)
        for field in (
            "canonical_document_count",
            "capability_count",
            "source_comment_count",
            "module_docstring_count",
            "source_docstring_count",
        )
    }
    if (
        documentation.get("schema_version")
        != "novel-forge.documentation-reality-check.v1"
        or documentation.get("evidence_class") != "reality_inventory"
        or documentation.get("status") != "PASS"
        or documentation.get("tested_sha") != tested_sha
        or documentation.get("errors") != []
        or not CONTENT_DIGEST.fullmatch(
            str(documentation.get("inventory_sha256") or "")
        )
        or documentation_counts["canonical_document_count"] != 5
        or not isinstance(documentation_counts["capability_count"], int)
        or isinstance(documentation_counts["capability_count"], bool)
        or documentation_counts["capability_count"] < 1
        or any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            for field, value in documentation_counts.items()
            if field not in {"canonical_document_count", "capability_count"}
        )
    ):
        raise ValueError("Documentation Reality evidence is not exact-SHA PASS")
    _required_artifact_evidence(
        documentation,
        evidence_name="Documentation Reality",
    )

    backend = _required_gate_evidence(gates, "pytest-backend")
    _validate_pytest_gate_evidence(
        backend,
        expected_schema="novel-forge.backend-pytest-evidence.v1",
        evidence_name="backend pytest",
    )
    migration_compatibility = _required_gate_evidence(
        gates, "migration-compatibility"
    )
    _validate_pytest_gate_evidence(
        migration_compatibility,
        expected_schema="novel-forge.postgresql-pytest-evidence.v1",
        evidence_name="migration compatibility pytest",
    )
    migration_slices = migration_compatibility.get("semantic_slices")
    if (
        not isinstance(migration_slices, Mapping)
        or not isinstance(migration_slices.get("migration_matrix"), list)
        or not migration_slices["migration_matrix"]
    ):
        raise ValueError("migration compatibility matrix evidence is incomplete")
    if any(gate.get("gate_id") == "pytest-postgresql-integration" for gate in gates):
        postgresql = _required_gate_evidence(
            gates, "pytest-postgresql-integration"
        )
        _validate_pytest_gate_evidence(
            postgresql,
            expected_schema="novel-forge.postgresql-pytest-evidence.v1",
            evidence_name="PostgreSQL pytest",
        )

    migration = _required_gate_evidence(gates, "migration-head")
    if (
        not expected_migration_head
        or migration.get("expected_head") != expected_migration_head
        or migration.get("observed_head") != expected_migration_head
    ):
        raise ValueError(
            "P0 qualification migration head is not bound to the canonical manifest"
        )
    query_plan = _required_gate_evidence(gates, "query-plan-release")
    _required_artifact_evidence(query_plan, evidence_name="query-plan")

    compose = _required_gate_evidence(gates, "compose-runtime")
    _required_artifact_evidence(compose, evidence_name="Compose runtime")
    operation_ids = {
        str(compose.get(key) or "")
        for key in (
            "pre_restart_operation_id",
            "recovered_operation_id",
            "post_restart_operation_id",
        )
    }
    if "" in operation_ids or len(operation_ids) != 3:
        raise ValueError(
            "Compose runtime evidence requires three distinct operation identities"
        )
    if compose.get("authoritative_side_effect") is not True:
        raise ValueError("Compose runtime evidence lacks an authoritative side effect")

    finalization = _required_gate_evidence(gates, "evidence-finalization")
    if finalization.get("atomic_write") is not True or not str(
        finalization.get("artifact") or ""
    ):
        raise ValueError("P0 evidence finalization is not atomic")


def build_docker_image_evidence(
    *,
    commit_sha: str,
    image_ref: str,
    build_metadata: Mapping[str, Any],
    image_id: str,
) -> dict[str, Any]:
    tested_sha = _validated_sha(commit_sha)
    candidates = (
        ("oci_manifest_digest", build_metadata.get("containerimage.digest")),
        ("image_config_digest", build_metadata.get("containerimage.config.digest")),
        ("docker_image_id", image_id),
    )
    selected_kind = ""
    selected_digest = ""
    for kind, candidate in candidates:
        value = str(candidate or "").strip().lower()
        if CONTENT_DIGEST.fullmatch(value):
            selected_kind = kind
            selected_digest = value
            break
    if not selected_digest:
        raise ValueError("Docker build did not emit a content-addressed sha256 digest")
    return {
        "schema_version": "authority-docker-image-evidence.v1",
        "evidence_class": "docker_image_digest",
        "status": "PASS",
        "tested_sha": tested_sha,
        "image_ref": image_ref,
        "docker_image_digest": selected_digest,
        "digest_kind": selected_kind,
        "generated_at": _now(),
    }


def build_environment_metadata(
    *,
    commit_sha: str,
    docker_version: str = "",
    compose_version: str = "",
    postgres_image: str = "pgvector/pgvector:pg16",
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    tested_sha = _validated_sha(commit_sha)
    env = environment if environment is not None else os.environ
    return {
        "schema_version": "authority-environment-metadata.v1",
        "evidence_class": "environment_metadata",
        "status": "PASS",
        "tested_sha": tested_sha,
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "runner_os": env.get("RUNNER_OS", ""),
        "runner_arch": env.get("RUNNER_ARCH", ""),
        "github_run_id": env.get("GITHUB_RUN_ID", ""),
        "github_run_attempt": env.get("GITHUB_RUN_ATTEMPT", ""),
        "docker_version": docker_version.strip(),
        "docker_compose_version": compose_version.strip(),
        "postgres_image": postgres_image,
        "generated_at": _now(),
    }


def build_ci_test_result(
    *, commit_sha: str, needs: Mapping[str, Any]
) -> dict[str, Any]:
    tested_sha = _validated_sha(commit_sha)
    if not needs:
        raise ValueError("required CI job results are empty")
    results: dict[str, str] = {}
    for job, payload in sorted(needs.items()):
        result = str(payload.get("result") if isinstance(payload, Mapping) else "")
        results[str(job)] = result
    failures = [f"{job}={result or 'missing'}" for job, result in results.items() if result != "success"]
    if failures:
        raise ValueError("required CI jobs did not succeed: " + ", ".join(failures))
    return {
        "schema_version": "authority-ci-test-result.v1",
        "evidence_class": "test_result",
        "status": "PASS",
        "tested_sha": tested_sha,
        "all_required_jobs_passed": True,
        "required_jobs": results,
        "generated_at": _now(),
    }


def _find_unique(root: Path, filename: str, evidence_class: str) -> Path:
    matches = sorted(root.rglob(filename))
    if len(matches) != 1:
        raise ValueError(
            f"{evidence_class} requires exactly one {filename}; found {len(matches)}"
        )
    return matches[0]


def _validate_json_sha(path: Path, tested_sha: str) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON evidence: {path.name}") from exc
    bound_values = {
        str(payload.get(key) or "").lower()
        for key in ("tested_sha", "commit_sha", "tested_repository_sha")
    }
    if tested_sha not in bound_values:
        raise ValueError(f"{path.name} is not content-bound to tested SHA {tested_sha}")
    if str(payload.get("status") or payload.get("result") or "PASS").upper() != "PASS":
        raise ValueError(f"{path.name} is not PASS evidence")


def build_release_qualification(
    *, commit_sha: str, artifact_root: str | Path
) -> dict[str, Any]:
    tested_sha = _validated_sha(commit_sha)
    root = Path(artifact_root)
    artifacts: dict[str, Any] = {}
    for evidence_class, template in REQUIRED_ARTIFACT_FILES.items():
        filename = template.format(sha=tested_sha)
        path = _find_unique(root, filename, evidence_class)
        if path.suffix == ".json":
            _validate_json_sha(path, tested_sha)
        artifacts[evidence_class] = {
            "filename": filename,
            "sha256": _artifact_hash(path),
            "size": path.stat().st_size,
        }
    return {
        "schema_version": "postgresql-authority-release-qualification.v1",
        "evidence_class": "release_qualification",
        "status": "PASS",
        "tested_sha": tested_sha,
        "all_required_artifact_classes_present": True,
        "artifacts": artifacts,
        "evidence_boundaries": {
            "real_provider_proven": False,
            "longform_proven": False,
            "multi_book_proven": False,
            "production_verified": False,
            "backup_pitr_proven": False,
            "autonomous_book_loop_proven": False,
        },
        "generated_at": _now(),
    }


def build_p0_backend_qualification_report(
    *,
    tested_sha: str,
    source_tree: str,
    source_identity: Mapping[str, Any],
    manifest: Mapping[str, Any],
    dependency_snapshot: Mapping[str, Any],
    gates: Sequence[Mapping[str, Any]],
    cleanup: Mapping[str, Any],
    run_identity: Mapping[str, Any],
) -> dict[str, Any]:
    commit_sha = _validated_sha(tested_sha)
    tree_sha = _validated_sha(source_tree)
    workflow_sha = str(source_identity.get("workflow_sha") or "")
    if (
        source_identity.get("dirty") is not False
        or source_identity.get("commit_sha") != commit_sha
        or source_identity.get("source_tree") != tree_sha
        or (workflow_sha and workflow_sha != commit_sha)
    ):
        raise ValueError("P0 qualification source identity must be exact and clean")
    if (
        manifest.get("schema_version")
        != "novel-forge.backend-qualification-manifest.v1"
    ):
        raise ValueError("P0 qualification manifest schema is invalid")
    required_gates = manifest.get("required_gates")
    if not isinstance(required_gates, list) or not required_gates:
        raise ValueError("P0 qualification required gates are empty")
    if not all(isinstance(item, str) and item for item in required_gates):
        raise ValueError("P0 qualification required gate IDs are invalid")
    if len(set(required_gates)) != len(required_gates):
        raise ValueError("P0 qualification required gate IDs are duplicated")
    if tuple(required_gates) != REQUIRED_GATE_ORDER:
        raise ValueError("P0 qualification required gate order is not canonical")
    gate_ids = [str(item.get("gate_id") or "") for item in gates]
    if gate_ids != required_gates:
        raise ValueError("P0 qualification gates are missing, extra, or out of order")
    for gate in gates:
        if gate.get("status") != "PASS":
            raise ValueError(
                f"P0 qualification gate is not PASS: {gate.get('gate_id')}"
            )
        duration = gate.get("duration_seconds")
        if not isinstance(duration, (int, float)) or duration < 0:
            raise ValueError(
                f"P0 qualification gate duration is invalid: {gate.get('gate_id')}"
            )
        if not isinstance(gate.get("evidence"), Mapping):
            raise ValueError(
                f"P0 qualification gate evidence is invalid: {gate.get('gate_id')}"
            )

    validated_dependency = validate_resolved_dependency_snapshot(
        dependency_snapshot
    )

    expected_head = str(manifest.get("expected_migration_head") or "")
    _validate_p0_gate_evidence(
        gates=gates,
        tested_sha=commit_sha,
        source_tree=tree_sha,
        expected_migration_head=expected_head,
    )
    migration_gate = next(
        gate for gate in gates if gate.get("gate_id") == "migration-head"
    )
    migration_evidence = migration_gate["evidence"]
    if (
        not expected_head
        or migration_evidence.get("expected_head") != expected_head
        or migration_evidence.get("observed_head") != expected_head
    ):
        raise ValueError(
            "P0 qualification migration head is not bound to the canonical manifest"
        )
    manifest_digests = manifest.get("manifest_digests")
    if not isinstance(manifest_digests, Mapping) or not manifest_digests:
        raise ValueError("P0 qualification manifest digests are empty")
    if not all(
        isinstance(path, str)
        and path
        and CONTENT_DIGEST.fullmatch(str(digest or ""))
        for path, digest in manifest_digests.items()
    ):
        raise ValueError("P0 qualification manifest digest entry is invalid")
    if dict(manifest.get("evidence_ceilings") or {}) != P0_EVIDENCE_CEILINGS:
        raise ValueError("P0 qualification evidence ceilings differ from policy")
    if cleanup.get("status") != "PASS" or cleanup.get(
        "remaining_resource_count"
    ) != 0:
        raise ValueError("P0 qualification cleanup is incomplete")
    if not str(run_identity.get("run_id") or ""):
        raise ValueError("P0 qualification run identity is empty")

    from novel_forge.tools.backend_qualification_contract import sanitize_evidence

    report = {
        "schema_version": "novel-forge.p0-backend-qualification-report.v1",
        "evidence_class": "p0_backend_engineering_qualification",
        "status": "PASS",
        "decision": "PASS",
        "tested_sha": commit_sha,
        "source_tree": tree_sha,
        "source_identity": dict(source_identity),
        "run_identity": dict(run_identity),
        "qualification_manifest": {
            "schema_version": manifest["schema_version"],
            "manifest_digests": dict(manifest_digests),
            "required_gates": list(required_gates),
        },
        "dependency_snapshot": validated_dependency,
        "migration": {
            "expected_head": expected_head,
            "observed_head": str(migration_evidence["observed_head"]),
            "expectation_source": "architecture/manifests/migration-manifest.yaml",
        },
        "gates": [dict(item) for item in gates],
        "cleanup": dict(cleanup),
        "evidence_ceilings": dict(P0_EVIDENCE_CEILINGS),
        "generated_at": _now(),
    }
    sanitized = sanitize_evidence(report)
    if not isinstance(sanitized, dict):
        raise ValueError("P0 qualification evidence sanitizer returned invalid data")
    return sanitized


def build_p0_backend_qualification_failure_report(
    *,
    tested_sha: str,
    source_tree: str,
    source_identity: Mapping[str, Any],
    manifest: Mapping[str, Any],
    dependency_snapshot: Mapping[str, Any],
    gates: Sequence[Mapping[str, Any]],
    cleanup: Mapping[str, Any],
    run_identity: Mapping[str, Any],
    failure_reason: str,
) -> dict[str, Any]:
    commit_sha = _validated_sha(tested_sha)
    tree_sha = _validated_sha(source_tree)
    required_gates = manifest.get("required_gates")
    if not isinstance(required_gates, list) or [
        str(gate.get("gate_id") or "") for gate in gates
    ] != required_gates:
        raise ValueError("failed P0 report gates differ from the manifest")
    if tuple(required_gates) != REQUIRED_GATE_ORDER:
        raise ValueError("failed P0 report gate order is not canonical")
    allowed_statuses = {"PASS", "FAIL", "BLOCKED", "NOT_RUN"}
    if not any(gate.get("status") in {"FAIL", "BLOCKED"} for gate in gates):
        raise ValueError("failed P0 report has no failed or blocked gate")
    if any(gate.get("status") not in allowed_statuses for gate in gates):
        raise ValueError("failed P0 report contains an invalid gate status")
    if dict(manifest.get("evidence_ceilings") or {}) != P0_EVIDENCE_CEILINGS:
        raise ValueError("failed P0 report evidence ceilings differ from policy")
    validated_dependency = validate_resolved_dependency_snapshot(
        dependency_snapshot
    )
    if not failure_reason.strip():
        raise ValueError("failed P0 report requires a failure reason")

    from novel_forge.tools.backend_qualification_contract import sanitize_evidence

    report = {
        "schema_version": "novel-forge.p0-backend-qualification-report.v1",
        "evidence_class": "p0_backend_engineering_qualification",
        "status": "FAIL",
        "decision": "FAIL",
        "failure_reason": failure_reason,
        "tested_sha": commit_sha,
        "source_tree": tree_sha,
        "source_identity": dict(source_identity),
        "run_identity": dict(run_identity),
        "qualification_manifest": {
            "schema_version": manifest.get("schema_version"),
            "manifest_digests": dict(manifest.get("manifest_digests") or {}),
            "required_gates": list(required_gates),
        },
        "dependency_snapshot": validated_dependency,
        "migration": {
            "expected_head": str(manifest.get("expected_migration_head") or ""),
            "observed_head": "",
            "expectation_source": "architecture/manifests/migration-manifest.yaml",
        },
        "gates": [dict(item) for item in gates],
        "cleanup": dict(cleanup),
        "evidence_ceilings": dict(P0_EVIDENCE_CEILINGS),
        "generated_at": _now(),
    }
    sanitized = sanitize_evidence(report)
    if not isinstance(sanitized, dict):
        raise ValueError("failed P0 report sanitizer returned invalid data")
    return sanitized


def validate_p0_backend_qualification_report(
    report: Mapping[str, Any],
    *,
    expected_sha: str,
) -> dict[str, Any]:
    tested_sha = _validated_sha(expected_sha)
    if report.get("schema_version") != (
        "novel-forge.p0-backend-qualification-report.v1"
    ):
        raise ValueError("P0 backend qualification report schema is invalid")
    if report.get("status") != "PASS" or report.get("decision") != "PASS":
        raise ValueError("P0 backend qualification report is not PASS")
    if report.get("tested_sha") != tested_sha:
        raise ValueError("P0 backend qualification report targets another SHA")
    if not GIT_SHA.fullmatch(str(report.get("source_tree") or "")):
        raise ValueError("P0 backend qualification source tree is invalid")
    source_identity = report.get("source_identity")
    if (
        not isinstance(source_identity, Mapping)
        or source_identity.get("dirty") is not False
        or source_identity.get("commit_sha") != tested_sha
        or source_identity.get("source_tree") != report.get("source_tree")
        or (
            source_identity.get("workflow_sha")
            and source_identity.get("workflow_sha") != tested_sha
        )
    ):
        raise ValueError("P0 backend qualification source identity is not exact and clean")
    dependency = report.get("dependency_snapshot")
    if not isinstance(dependency, Mapping):
        raise ValueError("P0 backend qualification dependency snapshot is invalid")
    validated_dependency = validate_resolved_dependency_snapshot(dependency)
    migration = report.get("migration")
    if (
        not isinstance(migration, Mapping)
        or not migration.get("expected_head")
        or migration.get("expected_head") != migration.get("observed_head")
        or migration.get("expectation_source")
        != "architecture/manifests/migration-manifest.yaml"
    ):
        raise ValueError("P0 backend qualification migration evidence is invalid")
    manifest = report.get("qualification_manifest")
    gates = report.get("gates")
    if not isinstance(manifest, Mapping) or not isinstance(gates, list):
        raise ValueError("P0 backend qualification gates are invalid")
    required_gates = manifest.get("required_gates")
    if not isinstance(required_gates, list) or [
        item.get("gate_id") if isinstance(item, Mapping) else "" for item in gates
    ] != required_gates:
        raise ValueError("P0 backend qualification gate order differs")
    if tuple(required_gates) != REQUIRED_GATE_ORDER:
        raise ValueError("P0 backend qualification gate order is not canonical")
    if any(
        not isinstance(item, Mapping) or item.get("status") != "PASS"
        for item in gates
    ):
        raise ValueError("P0 backend qualification contains a non-PASS gate")
    _validate_p0_gate_evidence(
        gates=gates,
        tested_sha=tested_sha,
        source_tree=str(report["source_tree"]),
        expected_migration_head=str(migration["expected_head"]),
    )
    cleanup = report.get("cleanup")
    if (
        not isinstance(cleanup, Mapping)
        or cleanup.get("status") != "PASS"
        or cleanup.get("remaining_resource_count") != 0
    ):
        raise ValueError("P0 backend qualification cleanup evidence is invalid")
    if report.get("evidence_ceilings") != P0_EVIDENCE_CEILINGS:
        raise ValueError("P0 backend qualification evidence ceilings differ")
    return {
        "schema_version": "novel-forge.p0-backend-qualification-validation.v1",
        "status": "PASS",
        "tested_sha": tested_sha,
        "source_tree": report["source_tree"],
        "dependency_digest": validated_dependency["digest"],
        "migration_head": migration["observed_head"],
        "gate_count": len(gates),
        "evidence_ceilings": dict(P0_EVIDENCE_CEILINGS),
    }


def write_atomic_evidence(path: str | Path, payload: Mapping[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, output)
        directory = os.open(output.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary_name:
            try:
                Path(temporary_name).unlink()
            except FileNotFoundError:
                pass


def _write(path: str | Path, payload: Mapping[str, Any]) -> None:
    write_atomic_evidence(path, payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    image_parser = subparsers.add_parser("image")
    image_parser.add_argument("--commit-sha", required=True)
    image_parser.add_argument("--image-ref", required=True)
    image_parser.add_argument("--metadata", type=Path, required=True)
    image_parser.add_argument("--image-id-file", type=Path, required=True)
    image_parser.add_argument("--output", required=True)

    environment_parser = subparsers.add_parser("environment")
    environment_parser.add_argument("--commit-sha", required=True)
    environment_parser.add_argument("--docker-version", default="")
    environment_parser.add_argument("--compose-version", default="")
    environment_parser.add_argument("--postgres-image", default="pgvector/pgvector:pg16")
    environment_parser.add_argument("--output", required=True)

    test_parser = subparsers.add_parser("test-result")
    test_parser.add_argument("--commit-sha", required=True)
    test_parser.add_argument("--needs-json", required=True)
    test_parser.add_argument("--output", required=True)

    release_parser = subparsers.add_parser("release")
    release_parser.add_argument("--commit-sha", required=True)
    release_parser.add_argument("--artifact-root", type=Path, required=True)
    release_parser.add_argument("--output", required=True)

    p0_validate_parser = subparsers.add_parser("p0-validate")
    p0_validate_parser.add_argument("--commit-sha", required=True)
    p0_validate_parser.add_argument("--report", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "image":
        payload = build_docker_image_evidence(
            commit_sha=args.commit_sha,
            image_ref=args.image_ref,
            build_metadata=json.loads(args.metadata.read_text(encoding="utf-8")),
            image_id=args.image_id_file.read_text(encoding="utf-8").strip(),
        )
    elif args.command == "environment":
        payload = build_environment_metadata(
            commit_sha=args.commit_sha,
            docker_version=args.docker_version,
            compose_version=args.compose_version,
            postgres_image=args.postgres_image,
        )
    elif args.command == "test-result":
        payload = build_ci_test_result(
            commit_sha=args.commit_sha,
            needs=json.loads(args.needs_json),
        )
    elif args.command == "release":
        payload = build_release_qualification(
            commit_sha=args.commit_sha,
            artifact_root=args.artifact_root,
        )
    else:
        try:
            report = json.loads(args.report.read_text(encoding="utf-8"))
        except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("P0 qualification report is missing or invalid") from exc
        if not isinstance(report, dict):
            raise ValueError("P0 qualification report must be a JSON object")
        payload = validate_p0_backend_qualification_report(
            report,
            expected_sha=args.commit_sha,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    _write(args.output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "REQUIRED_ARTIFACT_FILES",
    "P0_EVIDENCE_CEILINGS",
    "build_p0_backend_qualification_report",
    "build_p0_backend_qualification_failure_report",
    "build_ci_test_result",
    "build_docker_image_evidence",
    "build_environment_metadata",
    "build_release_qualification",
    "validate_p0_backend_qualification_report",
    "write_atomic_evidence",
]
