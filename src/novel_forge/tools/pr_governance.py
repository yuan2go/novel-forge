from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable, Sequence

from novel_forge.tools.implementation_tree_identity import (
    build_git_implementation_tree_identity,
    build_implementation_tree_identity,
)
from novel_forge.tools.release_run_evidence import (
    validate_p0_backend_qualification_report,
    write_atomic_evidence,
)


SCHEMA_VERSION = "novel-forge.pr-governance.v1"


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise ValueError("cannot resolve PR source: " + " ".join(args))
    return result.stdout.strip()


def plan_pr_governance(repo_root: str | Path, *, base_sha: str) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    if not re.fullmatch(r"[0-9a-f]{40}", base_sha):
        raise ValueError("PR base requires an exact Git SHA")
    head = _git(root, "rev-parse", "HEAD")
    if _git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("PR governance requires a clean worktree")
    workflow_sha = os.environ.get("GITHUB_SHA")
    if workflow_sha and workflow_sha != head:
        raise ValueError("PR source differs from GITHUB_SHA")
    _git(root, "merge-base", "--is-ancestor", base_sha, head)
    base = build_git_implementation_tree_identity(root, base_sha)
    current = build_implementation_tree_identity(root)
    committed = build_git_implementation_tree_identity(root, head)
    if current != committed:
        raise ValueError("PR implementation contains untracked or ignored source")
    base_records = {record["path"]: record for record in base["records"]}
    head_records = {record["path"]: record for record in current["records"]}
    changed = sorted(
        path
        for path in base_records.keys() | head_records.keys()
        if base_records.get(path) != head_records.get(path)
    )
    provider_evidence = []
    for path in sorted((root / "architecture/live-evidence").glob("*.json")):
        evidence = json.loads(path.read_text(encoding="utf-8"))
        if evidence.get("evidence_class") != "real_provider_runtime_qualification":
            continue
        matches = (
            evidence.get("implementation_tree_sha")
            == current["implementation_tree_sha"]
        )
        provider_evidence.append(
            {
                "path": path.relative_to(root).as_posix(),
                "identity_status": "MATCHES_CURRENT_IMPLEMENTATION"
                if matches
                else "STALE",
                "qualification_authority": "GOVERNED_PROVIDER_QUALIFICATION",
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "NOT_RUN",
        "base_sha": base_sha,
        "head_sha": head,
        "base_implementation_tree_sha": base["implementation_tree_sha"],
        "implementation_tree_sha": current["implementation_tree_sha"],
        "implementation_changed": bool(changed),
        "changed_implementation_paths": changed,
        "qualification": "REQUIRED_EXACT_SHA_P0" if changed else "NOT_REQUIRED",
        "qualification_reason": "IMPLEMENTATION_CHANGED"
        if changed
        else "SAME_IMPLEMENTATION",
        "focused_test_paths": [
            path
            for path in changed
            if path.startswith("tests/")
            and Path(path).name.startswith("test_")
            and Path(path).suffix == ".py"
            and (root / path).is_file()
        ],
        "provider_evidence": provider_evidence,
        "provider_qualification": "NOT_ASSESSED_BY_PR_GATE",
        "checks": [],
    }


def validate_current_p0(report: dict[str, Any], *, plan: dict[str, Any]) -> None:
    validate_p0_backend_qualification_report(report, expected_sha=plan["head_sha"])
    if (
        report.get("schema_version") != "novel-forge.p0-backend-qualification-report.v2"
        or report.get("status") != "PASS"
        or report.get("decision") != "PASS"
        or report.get("tested_sha") != plan["head_sha"]
        or report.get("implementation_tree_sha") != plan["implementation_tree_sha"]
    ):
        raise ValueError(
            "canonical P0 report does not qualify this exact PR implementation"
        )


def run_pr_governance(
    repo_root: str | Path,
    *,
    base_sha: str,
    output: str | Path,
    profile: str = "local",
    command_runner: Callable[[Sequence[str]], int] | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    output = Path(output).resolve()
    if output.is_relative_to(root):
        raise ValueError("PR evidence output must be outside the source checkout")
    report: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "status": "FAIL"}

    def run(command: Sequence[str]) -> int:
        if command_runner is not None:
            return command_runner(command)
        return subprocess.run(command, cwd=root, check=False).returncode

    try:
        report = plan_pr_governance(root, base_sha=base_sha)
        code = run(("make", "pr-governance-checks"))
        report["checks"].append({"gate": "repository-governance", "exit_code": code})
        if code:
            raise ValueError("repository governance failed; qualification cannot PASS")
        if report["implementation_changed"]:
            focused = [
                path
                for path in report["focused_test_paths"]
                if not path.startswith("tests/integration/")
            ]
            if not focused:
                raise ValueError(
                    "FOCUSED_TEST_EVIDENCE_REQUIRED: implementation PR must supply focused non-PostgreSQL tests before complete P0"
                )
            code = run((sys.executable, "-m", "pytest", *focused))
            report["checks"].append({"gate": "focused-tests", "exit_code": code})
            if code:
                raise ValueError("focused tests failed; qualification cannot PASS")
            code = run(
                (
                    "make",
                    "p0-backend-qualification",
                    f"P0_PROFILE={profile}",
                    "P0_EVIDENCE_DIR=" + str(output.parent),
                )
            )
            report["checks"].append(
                {"gate": "canonical-exact-sha-p0", "exit_code": code}
            )
            if code:
                raise ValueError("canonical exact-SHA P0 failed")
            p0_path = (
                output.parent / f"p0-backend-qualification-{report['head_sha']}.json"
            )
            p0_bytes = p0_path.read_bytes()
            validate_current_p0(json.loads(p0_bytes), plan=report)
            report["p0_evidence"] = {
                "path": str(p0_path),
                "sha256": "sha256:" + hashlib.sha256(p0_bytes).hexdigest(),
            }
            report["qualification"] = "PASS_EXACT_SHA_P0"
        after = plan_pr_governance(root, base_sha=base_sha)
        if (after["head_sha"], after["implementation_tree_sha"]) != (
            report["head_sha"],
            report["implementation_tree_sha"],
        ):
            raise ValueError("PR implementation changed while governance was running")
        report["status"] = "PASS"
    except (OSError, ValueError, KeyError, TypeError) as exc:
        report["status"] = "FAIL"
        report["error"] = str(exc)
    write_atomic_evidence(output, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=("local", "ci"), default="local")
    args = parser.parse_args(argv)
    report = run_pr_governance(
        args.repo_root,
        base_sha=args.base_sha,
        output=args.output,
        profile=args.profile,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return int(report["status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
