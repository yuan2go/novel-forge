from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]


class CoreOsCharacterizationTests(unittest.TestCase):
    def test_core_ci_is_bound_to_checkout_head_and_ci_profile(self):
        workflow = (ROOT / ".github/workflows/core-os-ci.yml").read_text(encoding="utf-8")
        self.assertIn("git rev-parse HEAD", workflow)
        self.assertIn("${GITHUB_SHA}", workflow)
        self.assertIn("P0_PROFILE: ci", workflow)
        self.assertIn("P0_EVIDENCE_DIR: /tmp/novel-forge-p0", workflow)

    def test_authoritative_backend_job_uses_only_the_common_backend_entry(self):
        workflow_path = ROOT / ".github/workflows/core-os-ci.yml"
        workflow_source = workflow_path.read_text(encoding="utf-8")
        workflow = yaml.safe_load(workflow_source)
        backend = workflow["jobs"]["backend-qualification"]
        commands = "\n".join(
            str(step.get("run") or "") for step in backend["steps"]
        )

        self.assertEqual(backend["name"], "P0 Backend Qualification")
        self.assertNotIn("needs", backend)
        self.assertIn('python -m pip install -e ".[test,industrial]"', commands)
        self.assertIn("make pr-governance", commands)
        self.assertNotIn("npm", commands)
        self.assertNotIn("authority-parity-check", workflow_source)
        self.assertNotIn("web", workflow["jobs"])

        uploads = [
            step
            for step in backend["steps"]
            if step.get("uses") == "actions/upload-artifact@v4"
        ]
        self.assertEqual(len(uploads), 1)
        self.assertEqual(uploads[0].get("if"), "always()")
        self.assertIn("/tmp/novel-forge-p0", uploads[0]["with"]["path"])

if __name__ == "__main__":
    unittest.main()
