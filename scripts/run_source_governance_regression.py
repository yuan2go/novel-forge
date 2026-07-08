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
    "tests.unit.test_source_intake.SourceIntakeTests.test_source_governance_runtime_gate_fails_closed_without_required_sweep_evidence",
    "tests.unit.test_source_intake.SourceIntakeTests.test_source_governance_runtime_gate_passes_with_clean_readiness_and_sweeps",
    "tests.unit.test_source_intake.SourceIntakeTests.test_source_governance_runtime_gate_warns_locally_and_fails_in_production_for_stale_assets",
    "tests.unit.test_source_intake.SourceIntakeTests.test_source_governance_runtime_gate_blocks_unguarded_source_derived_assets",
    "tests.unit.test_product_api_routes.ProductApiRouterTests.test_source_guarded_apply_readiness_route_surfaces_reviewable_evidence",
    "tests.unit.test_product_api_routes.ProductApiRouterTests.test_source_governance_runtime_gate_route_passes_with_clean_sweeps",
    "tests.unit.test_novel_os_cockpit.NovelOsCockpitTests.test_project_cockpit_snapshot_is_schema_backed",
    "tests.unit.test_product_api_routes.ProductApiRouterTests.test_project_cockpit_route_surfaces_source_guarded_apply_readiness",
    "tests.unit.test_publishing_center.PublishingCenterTests.test_publishing_calendar_rules_logs_and_version_registry",
    "tests.unit.test_publishing_center.PublishingCenterTests.test_release_gate_evidence_requires_source_governance_gate_in_production",
    "tests.unit.test_context_builder_stage_profiles.ContextBuilderStageProfileTests.test_flow_context_bundle_records_source_governance_runtime_gate",
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
            "src/novel_forge/modules/novel_os_cockpit",
            "src/novel_forge/modules/publishing",
            "src/novel_forge/modules/context_builder",
            "src/novel_forge/api/routers/handoffs.py",
            "src/novel_forge/api/services/product.py",
            "tests/unit/test_source_intake.py",
            "tests/unit/test_novel_os_cockpit.py",
            "tests/unit/test_product_api_routes.py",
            "tests/unit/test_publishing_center.py",
            "tests/unit/test_context_builder_stage_profiles.py",
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
