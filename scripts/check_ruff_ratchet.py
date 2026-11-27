#!/usr/bin/env python3
"""Fail closed when repository Ruff debt grows or moves to new diagnostics."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


DEFAULT_BASELINE = Path("architecture/manifests/ruff-legacy-baseline.json")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    parser.add_argument("--ruff", default="ruff")
    return parser.parse_args()


def _read_baseline(root: Path, path: str) -> dict[str, Any]:
    baseline_path = (root / path).resolve()
    try:
        payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Ruff baseline is unreadable: {baseline_path}") from exc
    if payload.get("schema_version") != "ruff-legacy-baseline.v1":
        raise RuntimeError("Ruff baseline schema is unsupported")
    if not isinstance(payload.get("files"), list) or not payload["files"]:
        raise RuntimeError("Ruff baseline must contain explicit legacy files")
    return payload


def _ruff_findings(
    root: Path,
    *,
    ruff: str,
    scope: list[str],
) -> tuple[str, Counter[tuple[str, str]]]:
    version = subprocess.run(
        [ruff, "--version"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    completed = subprocess.run(
        [ruff, "check", *scope, "--output-format", "json"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode not in {0, 1}:
        raise RuntimeError(completed.stderr.strip() or "Ruff execution failed")
    try:
        findings = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError("Ruff returned invalid JSON") from exc
    counts: Counter[tuple[str, str]] = Counter()
    for finding in findings:
        filename = Path(str(finding["filename"])).resolve()
        try:
            relative = filename.relative_to(root).as_posix()
        except ValueError as exc:
            raise RuntimeError(
                f"Ruff returned a path outside the repository: {filename}"
            ) from exc
        counts[(relative, str(finding["code"]))] += 1
    return version, counts


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate(
    root: Path,
    baseline: dict[str, Any],
    current: Counter[tuple[str, str]],
) -> tuple[list[str], int]:
    expected: Counter[tuple[str, str]] = Counter()
    baseline_files: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    required_metadata = {
        "owner",
        "legacy_classification",
        "replacement",
        "removal_preconditions",
    }
    for entry in baseline["files"]:
        path = str(entry.get("path") or "")
        if not path or path in baseline_files:
            errors.append(f"baseline path is empty or duplicated: {path!r}")
            continue
        missing = sorted(required_metadata - set(entry))
        if missing or any(
            not str(entry.get(item) or "").strip() for item in required_metadata
        ):
            errors.append(f"baseline metadata is incomplete for {path}: {missing}")
        violations = entry.get("violations")
        if not isinstance(violations, dict) or not violations:
            errors.append(f"baseline violations are missing for {path}")
            continue
        baseline_files[path] = entry
        for rule, raw_count in violations.items():
            count = int(raw_count)
            if count <= 0:
                errors.append(f"baseline count must be positive: {path} {rule}")
            expected[(path, str(rule))] = count

    declared_total = int(baseline.get("diagnostic_count") or -1)
    expected_total = sum(expected.values())
    if declared_total != expected_total:
        errors.append(
            f"baseline diagnostic_count={declared_total} does not equal entries={expected_total}"
        )

    for key, count in sorted(current.items()):
        allowance = expected.get(key)
        if allowance is None:
            errors.append(
                f"new Ruff diagnostic is not baselined: {key[0]} {key[1]}={count}"
            )
        elif count > allowance:
            errors.append(
                f"Ruff diagnostic increased: {key[0]} {key[1]} {allowance}->{count}"
            )

    for path, entry in baseline_files.items():
        baseline_count = sum(int(value) for value in entry["violations"].values())
        current_count = sum(
            count
            for (finding_path, _rule), count in current.items()
            if finding_path == path
        )
        file_path = root / path
        current_hash = _sha256(file_path) if file_path.is_file() else "REMOVED"
        if current_hash != str(entry.get("content_sha256") or ""):
            if current_count >= baseline_count:
                errors.append(
                    f"modified baseline file did not reduce Ruff debt: "
                    f"{path} {baseline_count}->{current_count}"
                )
    return errors, expected_total


def main() -> int:
    args = _arguments()
    root = Path(args.repo_root).resolve()
    try:
        baseline = _read_baseline(root, args.baseline)
        scope = [str(item) for item in baseline.get("scope", [])]
        if not scope:
            raise RuntimeError("Ruff baseline scope is empty")
        version, current = _ruff_findings(root, ruff=args.ruff, scope=scope)
        if version != str(baseline.get("ruff_version") or ""):
            raise RuntimeError(
                f"Ruff version drift: expected {baseline.get('ruff_version')}, got {version}"
            )
        errors, baseline_total = _validate(root, baseline, current)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"ruff-ratchet: FAIL: {exc}", file=sys.stderr)
        return 1
    if errors:
        print("ruff-ratchet: FAIL", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(
        "ruff-ratchet: PASS "
        f"current={sum(current.values())} baseline={baseline_total} "
        f"legacy_files={len(baseline['files'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
