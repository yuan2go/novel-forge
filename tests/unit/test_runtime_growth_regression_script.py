from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


def _load_runtime_growth_script():
    script_path = ROOT / "scripts" / "run_runtime_growth_regression.py"
    spec = importlib.util.spec_from_file_location("run_runtime_growth_regression", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RuntimeGrowthRegressionScriptTests(unittest.TestCase):
    def test_runtime_growth_bundle_excludes_acceptance_provider_and_make_test(self):
        module = _load_runtime_growth_script()

        commands = module._commands(include_ui=True)
        command_text = "\n".join(" ".join(command) for command in commands)

        self.assertIn("test_chapter_production_compact_task_status_mode_preserves_completed_step_evidence", command_text)
        self.assertIn("tests.unit.test_chapter_runtime_growth.ChapterRuntimeGrowthTests", command_text)
        self.assertIn("test_agent_center_api_surfaces_agent_event_summary", command_text)
        self.assertIn("test_v1_chapter_production_workflow_template_creates_governed_definition", command_text)
        self.assertIn("test_workflow_governance_drift_gate_blocks_drifted_workflow_in_production", command_text)
        self.assertIn("test_execute_workflow_blocks_drifted_production_definition_before_nodes", command_text)
        self.assertIn("test_scheduler_dead_letters_workflow_governance_preflight_failure", command_text)
        self.assertIn("test_project_cockpit_snapshot_is_schema_backed", command_text)
        self.assertIn("test_project_cockpit_surfaces_workflow_governance_readiness", command_text)
        self.assertIn("test_project_cockpit_surfaces_clean_workflow_governance_readiness", command_text)
        self.assertIn("test_project_cockpit_route_surfaces_workflow_governance_readiness", command_text)
        self.assertIn("test_project_cockpit_route_surfaces_clean_workflow_governance_readiness", command_text)
        self.assertIn("test_project_cockpit_route_keeps_missing_workflow_governance_unready", command_text)
        self.assertIn("test_project_cockpit_route_surfaces_approval_request_caller_readiness", command_text)
        self.assertIn("test_chapter_runtime_growth_profile_route_builds_profile_and_cockpit_surfaces_it", command_text)
        self.assertIn("test_approval_request_caller_readiness_reports_missing_dimensions_without_mutation", command_text)
        self.assertIn("test_approval_request_caller_readiness_passes_when_required_callers_are_covered", command_text)
        self.assertIn("test_approval_request_caller_readiness_flags_pending_blocking_review", command_text)
        self.assertIn("test_permission_center_route_surfaces_approval_request_caller_readiness", command_text)
        self.assertIn("src/novel_forge/modules/chapter_runtime_growth", command_text)
        self.assertIn("src/novel_forge/modules/novel_os_cockpit", command_text)
        self.assertIn("src/novel_forge/modules/permission_center", command_text)
        self.assertIn("src/novel_forge/api/routers/os_capabilities.py", command_text)
        self.assertIn("tests/unit/test_chapter_runtime_growth.py", command_text)
        self.assertIn("tests/unit/test_permission_center.py", command_text)
        self.assertIn("tests/unit/test_product_api_routes.py", command_text)
        self.assertIn("web/admin/tests/feature-architecture.test.mjs", command_text)
        self.assertIn("web/admin run lint", command_text)
        self.assertNotIn("run_v1_chapter_sequence_acceptance.py", command_text)
        self.assertNotIn("v1-slow-acceptance", command_text)
        self.assertNotIn("make test", command_text)
        self.assertNotIn("provider-proof", command_text)

    def test_runtime_growth_bundle_is_documented_and_discoverable(self):
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        regression_docs = (ROOT / "docs" / "quality" / "regression-tests.md").read_text(encoding="utf-8")
        agent_registry_docs = (ROOT / "docs" / "architecture" / "agent-registry.md").read_text(encoding="utf-8")

        self.assertIn("make runtime-growth-regression - run focused runtime write-growth regression", makefile)
        self.assertIn("runtime-growth-regression:", makefile)
        self.assertIn("scripts/run_runtime_growth_regression.py", makefile)
        self.assertIn("## Runtime Growth Focused Regression", regression_docs)
        self.assertIn("make runtime-growth-regression", regression_docs)
        self.assertIn("excludes chapter sequence acceptance and provider proof", regression_docs)
        self.assertIn("## AgentRun Event Policy", agent_registry_docs)
        self.assertIn("agent_event_policy", agent_registry_docs)
        self.assertIn("success_summary", agent_registry_docs)
        self.assertIn("不能压缩的证据", agent_registry_docs)


if __name__ == "__main__":
    unittest.main()
