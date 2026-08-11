from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class CoreOsCharacterizationTests(unittest.TestCase):
    def test_core_ci_is_bound_to_checkout_head_and_real_postgres_service(self):
        workflow = (ROOT / ".github/workflows/core-os-ci.yml").read_text(encoding="utf-8")
        self.assertIn("git rev-parse HEAD", workflow)
        self.assertIn("${GITHUB_SHA}", workflow)
        self.assertIn("pgvector/pgvector:pg16", workflow)
        self.assertIn("novel_forge_core_os_test", workflow)
        self.assertIn("scripts/run_authority_postgres_tests.py", workflow)

if __name__ == "__main__":
    unittest.main()
