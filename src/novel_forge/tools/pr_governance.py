from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from novel_forge.tools.implementation_tree_identity import (
    build_git_implementation_tree_identity,
    build_implementation_tree_identity,
)
from novel_forge.tools.release_run_evidence import (
    validate_p0_backend_qualification_report,
    write_atomic_evidence,
)


FULL_SHA = re.compile(r"[0-9a-f]{40}")


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=False, timeout=30
    )
    if result.returncode:
        raise ValueError("PR source preflight failed: git " + " ".join(args))
    return result.stdout.strip()


def build_pr_plan(repo_root: str | Path, base_sha: str) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    if not FULL_SHA.fullmatch(base_sha):
        raise ValueError("PR base must be an exact Git SHA")
    head = _git(root, "rev-parse", "HEAD")
    if _git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("PR governance requires a clean worktree")
    _git(root, "merge-base", "--is-ancestor", base_sha, head)
    workflow_sha = os.environ.get("GITHUB_SHA")
    if workflow_sha and workflow_sha != head:
        raise ValueError("PR checkout differs from workflow SHA")
    current = build_implementation_tree_identity(root)
    committed = build_git_implementation_tree_identity(root, head)
    if current["implementation_tree_sha"] != committed["implementation_tree_sha"]:
        raise ValueError("uncommitted or ignored implementation content differs from HEAD")
    baseline = build_git_implementation_tree_identity(root, base_sha)
    before = {item["path"]: item for item in baseline["records"]}
    after = {item["path"]: item for item in current["records"]}
    changed = sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))
    focused = [
        path for path in changed
        if path.startswith(("tests/unit/", "tests/architecture/", "tests/acceptance/"))
        and path.endswith(".py") and (root / path).is_file()
    ]
    return {
        "schema_version": "novel-forge.pr-governance.v1",
        "status": "PLANNED",
        "base_sha": base_sha,
        "head_sha": head,
        "base_implementation_identity": baseline["implementation_tree_sha"],
        "implementation_identity": current["implementation_tree_sha"],
        "implementation_changed": bool(changed),
        "changed_implementation_paths": changed,
        "focused_test_paths": focused,
        "qualification": "EXACT_SHA_P0_REQUIRED" if changed else "NOT_REQUIRED",
        "qualification_reason": "IMPLEMENTATION_CHANGED" if changed else "SAME_IMPLEMENTATION",
        "provider_evidence_policy": "EXACT_IMPLEMENTATION_IDENTITY_REQUIRED",
        "remote_enforcement": "NOT_OBSERVED_BY_LOCAL_GATE",
    }


def assess_provider_evidence(
    report: dict[str, Any], *, implementation_identity: str
) -> dict[str, str]:
    if report.get("implementation_identity") != implementation_identity:
        return {"status": "STALE", "reason": "IMPLEMENTATION_IDENTITY_CHANGED"}
    effect = report.get("external_effect") or {}
    qualification = report.get("qualification") or {}
    usage = report.get("usage") or {}
    latency = report.get("latency") or {}
    proof_scope = report.get("proof_scope") or {}
    route = (report.get("provider"), report.get("backend_id"))
    real_route = all(isinstance(value, str) for value in route) and route in {
        ("openai", "remote-provider-openai"), ("codex-cli", "codex-cli")
    }
    valid = (
        report.get("schema_version") == "novel-forge.real-provider-qualification.v1"
        and report.get("result") == "PASS"
        and isinstance(qualification, dict) and qualification.get("status") == "PASSED"
        and report.get("fixture_protocol_only", False) is False
        and qualification.get("fixture_protocol_only", False) is False
        and real_route
        and isinstance(effect, dict)
        and all(effect.get(key) for key in (
            "external_effect_id", "request_hash", "response_hash", "provider_request_identity"
        ))
        and all(type(effect.get(key)) is int and effect[key] == 1 for key in (
            "dispatch_count", "receipt_count", "reconciliation_count", "provider_execution_count"
        ))
        and type(effect.get("duplicate_external_effect_count")) is int
        and effect["duplicate_external_effect_count"] == 0
        and effect.get("initial_outcome") == "EFFECT_EXTERNAL_STATE_UNKNOWN"
        and all(effect.get(key) is True for key in (
            "ambiguous_response_injected", "recovery_runtime_restarted", "recovered_without_resend", "replayed"
        ))
        and isinstance(usage, dict) and usage.get("measurement") == "MEASURED"
        and all(type(usage.get(key)) is int and usage[key] > 0 for key in ("input_tokens", "output_tokens"))
        and isinstance(latency, dict) and isinstance(latency.get("duration_ms"), (int, float))
        and not isinstance(latency.get("duration_ms"), bool) and latency["duration_ms"] > 0
        and all(report.get(key) for key in (
            "request_object_ref", "response_object_ref", "provider", "model", "route_snapshot_id",
            "prompt_hash", "instruction_hash", "skill_hash",
        ))
        and isinstance(proof_scope, dict) and proof_scope.get("ceiling") == "REAL_PROVIDER_RUNTIME"
    )
    return {"status": "QUALIFIED" if valid else "NOT_PROVEN", "reason": "CURRENT_DURABLE_PROVIDER_EVIDENCE" if valid else "INCOMPLETE_OR_FIXTURE_EVIDENCE"}


def _provider_state(root: Path, identity: str, extra_path: Path | None) -> dict[str, Any]:
    paths = set((root / "architecture/live-evidence").glob("real-provider-qualification-*.json"))
    if extra_path:
        paths.add(extra_path.resolve())
    records = []
    for path in sorted(paths):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Provider evidence must be a JSON object")
        result = assess_provider_evidence(payload, implementation_identity=identity)
        if result["status"] == "QUALIFIED":
            sha = payload.get("release_sha")
            if not isinstance(sha, str) or not FULL_SHA.fullmatch(sha):
                raise ValueError("current Provider evidence requires exact observed SHA")
            _git(root, "merge-base", "--is-ancestor", sha, "HEAD")
            observed = build_git_implementation_tree_identity(root, sha)
            if observed["implementation_tree_sha"] != identity:
                raise ValueError("Provider observed revision differs from its identity")
        records.append({"path": str(path.relative_to(root)) if path.is_relative_to(root) else path.name, **result})
    return {"status": "QUALIFIED" if any(item["status"] == "QUALIFIED" for item in records) else "NOT_PROVEN", "evidence": records}


def _current_provider_claim(root: Path) -> bool:
    path = root / "architecture/reality-evidence.json"
    if not path.is_file():
        return False
    reality = json.loads(path.read_text(encoding="utf-8"))
    return any(
        item.get("value") is True
        and item.get("claim") == "credentialed real Provider execution qualifies the current implementation tree"
        for item in reality.get("negative_boundaries", []) if isinstance(item, dict)
    )


def run_pr_governance(
    repo_root: str | Path, *, base_sha: str, output: Path, profile: str,
    provider_evidence: Path | None = None, claim_provider_qualified: bool = False,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    output = output.resolve()
    if output.is_relative_to(root):
        raise ValueError("PR evidence must be outside the checkout to preserve exact source identity")
    report = build_pr_plan(root, base_sha)
    output.parent.mkdir(parents=True, exist_ok=True)
    environment = {**os.environ, "PYTHONPATH": str(root / "src")}
    checks = []
    report["checks"] = checks
    try:
        def execute(name: str, argv: list[str]) -> None:
            log = output.parent / ("pr-" + name + ".log")
            with log.open("w", encoding="utf-8") as stream:
                result = subprocess.run(argv, cwd=root, env=environment, stdout=stream, stderr=subprocess.STDOUT, check=False)
            checks.append({"name": name, "status": "PASS" if result.returncode == 0 else "FAIL", "log": log.name})
            if result.returncode:
                raise ValueError(name + " failed; see " + str(log))

        execute("governance", ["make", "sync-skills", "validate", "head-integrity-check", "check-skills", "PYTHON=" + sys.executable])
        if report["focused_test_paths"]:
            execute("focused-tests", [sys.executable, "-m", "pytest", *report["focused_test_paths"]])
        if report["implementation_changed"]:
            p0 = output.parent / ("p0-backend-qualification-" + report["head_sha"] + ".json")
            execute("exact-sha-p0", [
                sys.executable, "scripts/run_p0_backend_qualification.py", "--profile", profile, "--output", str(p0)
            ])
            payload = json.loads(p0.read_text(encoding="utf-8"))
            validated = validate_p0_backend_qualification_report(payload, expected_sha=report["head_sha"])
            if validated["implementation_tree_sha"] != report["implementation_identity"]:
                raise ValueError("P0 implementation identity differs from PR implementation")
            report["qualification"] = "PASS"
            report["p0_evidence"] = {"path": p0.name, **validated}
        provider = _provider_state(root, report["implementation_identity"], provider_evidence)
        report["current_real_provider"] = provider
        if (claim_provider_qualified or _current_provider_claim(root)) and provider["status"] != "QUALIFIED":
            raise ValueError("current Provider QUALIFIED claim requires requalification on this implementation")
        final = build_pr_plan(root, base_sha)
        if final["head_sha"] != report["head_sha"] or final["implementation_identity"] != report["implementation_identity"]:
            raise ValueError("PR source identity changed during governance")
        report["status"] = "PASS"
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        report["status"] = "FAIL"
        report["error"] = str(exc)
    write_atomic_evidence(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--profile", choices=("local", "ci"), default="local")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--provider-evidence", type=Path)
    parser.add_argument("--claim-current-provider-qualified", action="store_true")
    args = parser.parse_args()
    try:
        if args.plan:
            report = build_pr_plan(args.repo_root, args.base_sha)
        elif args.output:
            report = run_pr_governance(
                args.repo_root, base_sha=args.base_sha, output=args.output, profile=args.profile,
                provider_evidence=args.provider_evidence,
                claim_provider_qualified=args.claim_current_provider_qualified,
            )
        else:
            raise ValueError("--output is required when executing the PR gate")
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        report = {"schema_version": "novel-forge.pr-governance.v1", "status": "FAIL", "error": str(exc)}
        if args.output and not args.output.resolve().is_relative_to(args.repo_root.resolve()):
            write_atomic_evidence(args.output, report)
    print(json.dumps(report, indent=2))
    return 0 if report["status"] in {"PASS", "PLANNED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
