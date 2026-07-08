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
        self.assertIn("test_agent_center_api_surfaces_agent_event_summary", command_text)
        self.assertIn("web/admin/tests/feature-architecture.test.mjs", command_text)
        self.assertIn("web/admin run lint", command_text)
        self.assertNotIn("run_v1_chapter_sequence_acceptance.py", command_text)
        self.assertNotIn("v1-slow-acceptance", command_text)
        self.assertNotIn("make test", command_text)
        self.assertNotIn("provider-proof", command_text)

    def test_runtime_growth_bundle_is_documented_and_discoverable(self):
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        regression_docs = (ROOT / "docs" / "quality" / "regression-tests.md").read_text(encoding="utf-8")

        self.assertIn("make runtime-growth-regression - run focused runtime write-growth regression", makefile)
        self.assertIn("runtime-growth-regression:", makefile)
        self.assertIn("scripts/run_runtime_growth_regression.py", makefile)
        self.assertIn("## Runtime Growth Focused Regression", regression_docs)
        self.assertIn("make runtime-growth-regression", regression_docs)
        self.assertIn("excludes chapter sequence acceptance and provider proof", regression_docs)


if __name__ == "__main__":
    unittest.main()
