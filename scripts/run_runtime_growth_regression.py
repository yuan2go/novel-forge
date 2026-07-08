#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

RUNTIME_GROWTH_TESTS = [
    "tests.unit.test_context_and_production_chain.ContextAndProductionChainTests.test_chapter_production_compact_task_status_mode_preserves_completed_step_evidence",
    "tests.unit.test_context_and_production_chain.ContextAndProductionChainTests.test_chapter_production_compact_mode_preserves_failure_node_run_and_trace",
    "tests.unit.test_agent_workflow_and_impact.AgentWorkflowImpactTests.test_agent_run_event_checkpoint_write_growth_is_characterized",
    "tests.unit.test_agent_workflow_and_impact.AgentWorkflowImpactTests.test_agent_run_success_summary_event_policy_compacts_success_path_events",
    "tests.unit.test_agent_workflow_and_impact.AgentWorkflowImpactTests.test_agent_run_success_summary_event_policy_preserves_failure_events",
    "tests.unit.test_workflow_executor.WorkflowExecutorTests.test_agent_event_policy_flows_from_workflow_runtime_policy_to_agent_run",
    "tests.unit.test_agent_scheduler.AgentSchedulerTests.test_agent_center_snapshot_exposes_agent_event_summary",
    "tests.unit.test_agent_scheduler.AgentSchedulerTests.test_agent_center_api_surfaces_agent_event_summary",
    "tests.unit.test_workflow_executor.WorkflowExecutorTests.test_service_processor_starts_chapter_production_with_runtime_policy",
    "tests.unit.test_workflow_executor.WorkflowExecutorTests.test_service_processor_resumes_chapter_production",
    "tests.unit.test_workflow_executor.WorkflowExecutorTests.test_service_processor_blocks_production_chapter_without_governance_evidence",
    "tests.unit.test_workflow_executor.WorkflowExecutorTests.test_v1_chapter_production_workflow_template_creates_governed_definition",
    "tests.unit.test_workflow_executor.WorkflowExecutorTests.test_v1_chapter_production_workflow_console_marks_missing_production_evidence",
    "tests.unit.test_workflow_executor.WorkflowExecutorTests.test_workflow_governance_drift_gate_passes_clean_canonical_template",
    "tests.unit.test_workflow_executor.WorkflowExecutorTests.test_workflow_governance_drift_gate_blocks_drifted_workflow_in_production",
    "tests.unit.test_workflow_executor.WorkflowExecutorTests.test_workflow_governance_drift_gate_warns_for_local_drift",
    "tests.unit.test_workflow_executor.WorkflowExecutorTests.test_execute_workflow_blocks_drifted_production_definition_before_nodes",
    "tests.unit.test_workflow_executor.WorkflowExecutorTests.test_scheduler_dead_letters_workflow_governance_preflight_failure",
    "tests.unit.test_novel_os_cockpit.NovelOsCockpitTests.test_project_cockpit_surfaces_workflow_governance_readiness",
    "tests.unit.test_product_api_routes.ProductApiRouterTests.test_project_cockpit_route_surfaces_workflow_governance_readiness",
    "tests.unit.test_runtime_growth_regression_script.RuntimeGrowthRegressionScriptTests",
]


def _commands(*, include_ui: bool) -> list[list[str]]:
    commands = [
        [sys.executable, "-m", "unittest", *RUNTIME_GROWTH_TESTS],
        [
            sys.executable,
            "-m",
            "compileall",
            "-q",
            "src/novel_forge/modules/chapter_production_bus",
            "src/novel_forge/modules/agent_runs",
            "src/novel_forge/modules/agent_scheduler",
            "src/novel_forge/modules/workflow_nodes",
            "src/novel_forge/modules/novel_os_cockpit",
            "tests/unit/test_context_and_production_chain.py",
            "tests/unit/test_agent_workflow_and_impact.py",
            "tests/unit/test_workflow_executor.py",
            "tests/unit/test_agent_scheduler.py",
            "tests/unit/test_novel_os_cockpit.py",
            "tests/unit/test_product_api_routes.py",
            "tests/unit/test_runtime_growth_regression_script.py",
        ],
    ]
    if include_ui:
        commands.extend(
            [
                ["node", "--test", "web/admin/tests/feature-architecture.test.mjs"],
                ["npm", "--prefix", "web/admin", "run", "lint"],
            ]
        )
    return commands


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the focused runtime-growth governance regression bundle. This intentionally excludes chapter acceptance and provider proof."
    )
    parser.add_argument("--list", action="store_true", help="Print commands without running them.")
    parser.add_argument("--skip-ui", action="store_true", help="Skip web/admin static UI and TypeScript checks.")
    args = parser.parse_args()

    commands = _commands(include_ui=not args.skip_ui)
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
