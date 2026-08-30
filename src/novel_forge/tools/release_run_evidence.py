"""INVARIANT: release proof is a CI artifact bound to the tested Git SHA, not a checked-in run narrative."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


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


def _validated_sha(commit_sha: str) -> str:
    value = commit_sha.strip().lower()
    if not GIT_SHA.fullmatch(value):
        raise ValueError("commit SHA must be a full lowercase Git SHA")
    return value


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _artifact_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


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


def _write(path: str | Path, payload: Mapping[str, Any]) -> None:
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
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

    args = parser.parse_args()
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
    else:
        payload = build_release_qualification(
            commit_sha=args.commit_sha,
            artifact_root=args.artifact_root,
        )
    _write(args.output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "REQUIRED_ARTIFACT_FILES",
    "build_ci_test_result",
    "build_docker_image_evidence",
    "build_environment_metadata",
    "build_release_qualification",
]
