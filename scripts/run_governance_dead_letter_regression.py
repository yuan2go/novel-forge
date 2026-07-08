#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

AGENT_SCHEDULER_TESTS = [
    "tests.unit.test_agent_scheduler.AgentSchedulerTests.test_scheduler_tick_dead_letters_release_when_governance_drift_blocks",
    "tests.unit.test_agent_scheduler.AgentSchedulerTests.test_scheduler_tick_dead_letters_publish_gate_when_governance_drift_blocks",
    "tests.unit.test_agent_scheduler.AgentSchedulerTests.test_agent_center_surfaces_governance_dead_letter_evidence",
    "tests.unit.test_agent_scheduler.AgentSchedulerTests.test_governance_dead_letter_repair_requires_review_evidence",
    "tests.unit.test_agent_scheduler.AgentSchedulerTests.test_governance_dead_letter_repair_accepts_explicit_review_evidence",
    "tests.unit.test_agent_scheduler.AgentSchedulerTests.test_direct_recover_rejects_governance_dead_letter",
    "tests.unit.test_agent_scheduler.AgentSchedulerTests.test_agent_dead_letter_repair_api_requires_governance_review_evidence",
    "tests.unit.test_agent_scheduler.AgentSchedulerTests.test_agent_dead_letter_repair_api_accepts_governance_review_evidence",
    "tests.unit.test_agent_scheduler.AgentSchedulerTests.test_agent_center_api_surfaces_governance_dead_letter_evidence",
    "tests.unit.test_agent_scheduler.AgentSchedulerTests.test_agent_center_api_surfaces_governance_repair_audit_evidence",
    "tests.unit.test_agent_scheduler.AgentSchedulerTests.test_agent_center_evidence_drawer_includes_dead_letter_repair_assets",
    "tests.unit.test_agent_scheduler.AgentSchedulerTests.test_agent_center_readiness_warns_on_historical_governance_repair_missing_review",
    "tests.unit.test_agent_scheduler.AgentSchedulerTests.test_agent_center_api_surfaces_governance_repair_readiness_warning",
]


def _commands(*, include_ui: bool) -> list[list[str]]:
    commands = [
        [sys.executable, "-m", "unittest", *AGENT_SCHEDULER_TESTS],
        [
            sys.executable,
            "-m",
            "compileall",
            "-q",
            "src/novel_forge/modules/agent_scheduler",
            "tests/unit/test_agent_scheduler.py",
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
        description="Run the focused governance dead-letter regression bundle. This intentionally excludes chapter acceptance and provider proof."
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
