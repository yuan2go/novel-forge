#!/usr/bin/env python3
"""Run the complete PostgreSQL integration collection with structured evidence."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from novel_forge.tools.backend_qualification_contract import (
    QualificationContractError,
    build_postgres_pytest_command,
    load_qualification_manifest,
    sanitize_evidence,
    validate_postgres_test_evidence,
)
from novel_forge.tools.backend_qualification_resources import (
    validate_disposable_database_url,
)


ROOT = Path(__file__).resolve().parents[1]
PASS = 0
TEST_OR_CONTRACT_FAIL = 1
PREFLIGHT_FAIL = 2


def _error(message: object) -> None:
    print(str(sanitize_evidence(message)), file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--junit-xml", type=Path, required=True)
    parser.add_argument("--collection-report", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=7_200)
    args = parser.parse_args(argv)

    database_url = os.environ.get("NOVEL_FORGE_DATABASE_URL", "").strip()
    database_name = os.environ.get(
        "NOVEL_FORGE_QUALIFICATION_DATABASE_NAME", ""
    ).strip()
    if not database_url or not database_name:
        _error(
            "NOVEL_FORGE_DATABASE_URL and "
            "NOVEL_FORGE_QUALIFICATION_DATABASE_NAME are required"
        )
        return PREFLIGHT_FAIL
    if args.timeout_seconds <= 0:
        _error("--timeout-seconds must be positive")
        return PREFLIGHT_FAIL

    root = args.repo_root.resolve()
    junit_xml = args.junit_xml.resolve()
    collection_report = args.collection_report.resolve()
    if junit_xml == collection_report:
        _error("JUnit XML and collection report paths must differ")
        return PREFLIGHT_FAIL
    try:
        safe_database_identity = validate_disposable_database_url(
            database_url,
            expected_database=database_name,
        )
        manifest = load_qualification_manifest(root)
        contract = next(
            item
            for item in manifest.pytest_collections
            if item.name == "integration"
        )
        command = build_postgres_pytest_command(
            contract=contract,
            python=args.python,
            junit_xml=junit_xml,
            collection_report=collection_report,
        )
    except (QualificationContractError, StopIteration, ValueError) as exc:
        _error(exc)
        return PREFLIGHT_FAIL

    junit_xml.parent.mkdir(parents=True, exist_ok=True)
    collection_report.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    source_path = str(root / "src")
    existing_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = (
        source_path
        if not existing_pythonpath
        else source_path + os.pathsep + existing_pythonpath
    )
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            env=environment,
            check=False,
            timeout=args.timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        _error("complete PostgreSQL pytest collection exceeded its timeout")
        return TEST_OR_CONTRACT_FAIL

    try:
        evidence = validate_postgres_test_evidence(
            contract=contract,
            junit_xml=junit_xml,
            collection_report=collection_report,
            repo_root=root,
            semantic_slices=manifest.semantic_slices,
        )
    except QualificationContractError as exc:
        _error(exc)
        return TEST_OR_CONTRACT_FAIL
    if completed.returncode != 0:
        _error("PostgreSQL pytest process failed despite readable evidence")
        return TEST_OR_CONTRACT_FAIL
    print(
        json.dumps(
            {
                **evidence,
                "database_identity": safe_database_identity,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return PASS


if __name__ == "__main__":
    raise SystemExit(main())
