from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


def _load_source_governance_script():
    script_path = ROOT / "scripts" / "run_source_governance_regression.py"
    spec = importlib.util.spec_from_file_location("run_source_governance_regression", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SourceGovernanceRegressionScriptTests(unittest.TestCase):
    def test_source_governance_bundle_excludes_connector_execution_acceptance_and_provider(self):
        module = _load_source_governance_script()

        commands = module._commands()
        command_text = "\n".join(" ".join(command) for command in commands)

        self.assertIn("test_source_refresh_report_audits_existing_governance_without_connector_execution", command_text)
        self.assertIn("test_source_connector_execution_plan_is_approval_gated_and_no_network_by_default", command_text)
        self.assertIn("test_source_diff_repair_plan_creates_reviewable_impact_without_mutation", command_text)
        self.assertIn("test_source_guarded_apply_readiness_surfaces_reviewable_diff_plan", command_text)
        self.assertIn("test_source_guarded_apply_readiness_route_surfaces_reviewable_evidence", command_text)
        self.assertIn("test_source_governance_runtime_gate_fails_closed_without_required_sweep_evidence", command_text)
        self.assertIn("test_source_governance_runtime_gate_passes_with_clean_readiness_and_sweeps", command_text)
        self.assertIn("test_source_governance_runtime_gate_route_passes_with_clean_sweeps", command_text)
        self.assertIn("test_project_cockpit_snapshot_is_schema_backed", command_text)
        self.assertIn("test_project_cockpit_route_surfaces_source_guarded_apply_readiness", command_text)
        self.assertIn("src/novel_forge/modules/source_intake", command_text)
        self.assertIn("src/novel_forge/modules/novel_os_cockpit", command_text)
        self.assertIn("tests/unit/test_novel_os_cockpit.py", command_text)
        self.assertIn("tests/unit/test_source_governance_regression_script.py", command_text)
        self.assertNotIn("test_source_connector_runner_executes_approved_local_file_in_sandbox", command_text)
        self.assertNotIn("connector-run", command_text)
        self.assertNotIn("run_v1_chapter_sequence_acceptance.py", command_text)
        self.assertNotIn("provider-proof", command_text)
        self.assertNotIn("make test", command_text)

    def test_source_governance_bundle_is_documented_and_discoverable(self):
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        regression_docs = (ROOT / "docs" / "quality" / "regression-tests.md").read_text(encoding="utf-8")

        self.assertIn("make source-governance-regression - run focused source governance regression", makefile)
        self.assertIn("source-governance-regression:", makefile)
        self.assertIn("scripts/run_source_governance_regression.py", makefile)
        self.assertIn("## Source Governance Focused Regression", regression_docs)
        self.assertIn("make source-governance-regression", regression_docs)
        self.assertIn("excludes connector execution, chapter acceptance, and provider proof", regression_docs)


if __name__ == "__main__":
    unittest.main()
