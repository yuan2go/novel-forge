#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SOURCE_GOVERNANCE_TESTS = [
    "tests.unit.test_source_intake.SourceIntakeTests.test_source_refresh_report_audits_existing_governance_without_connector_execution",
    "tests.unit.test_source_intake.SourceIntakeTests.test_source_refresh_report_flags_license_gap_and_hash_drift",
    "tests.unit.test_source_intake.SourceIntakeTests.test_source_connector_execution_plan_is_approval_gated_and_no_network_by_default",
    "tests.unit.test_source_intake.SourceIntakeTests.test_source_diff_repair_plan_creates_reviewable_impact_without_mutation",
    "tests.unit.test_source_intake.SourceIntakeTests.test_source_diff_repair_apply_requires_approval_and_writes_rollback_plan",
    "tests.unit.test_source_intake.SourceIntakeTests.test_source_guarded_apply_readiness_reports_missing_without_mutation",
    "tests.unit.test_source_intake.SourceIntakeTests.test_source_guarded_apply_readiness_surfaces_reviewable_diff_plan",
    "tests.unit.test_source_intake.SourceIntakeTests.test_source_guarded_apply_readiness_surfaces_applied_stale_and_dispatch_ready_evidence",
    "tests.unit.test_product_api_routes.ProductApiRouterTests.test_source_guarded_apply_readiness_route_surfaces_reviewable_evidence",
    "tests.unit.test_source_governance_regression_script.SourceGovernanceRegressionScriptTests",
]


def _commands() -> list[list[str]]:
    return [
        [sys.executable, "-m", "unittest", *SOURCE_GOVERNANCE_TESTS],
        [
            sys.executable,
            "-m",
            "compileall",
            "-q",
            "src/novel_forge/modules/source_intake",
            "src/novel_forge/api/routers/handoffs.py",
            "src/novel_forge/api/services/product.py",
            "tests/unit/test_source_intake.py",
            "tests/unit/test_product_api_routes.py",
            "tests/unit/test_source_governance_regression_script.py",
        ],
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the focused source-governance regression bundle. This intentionally excludes connector execution, chapter acceptance, and provider proof."
    )
    parser.add_argument("--list", action="store_true", help="Print commands without running them.")
    args = parser.parse_args()

    commands = _commands()
    if args.list:
        for command in commands:
            print(shlex.join(command))
        return 0

    for command in commands:
        print(f"$ {shlex.join(command)}", flush=True)
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode != 0:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
