from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "run_real_provider_qualification",
    SCRIPTS / "run_real_provider_qualification.py",
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("real Provider qualification runner could not be loaded")
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class RealProviderQualificationRunnerTests(unittest.TestCase):
    def test_runtime_environment_freezes_controlled_composition_routes(self) -> None:
        with TemporaryDirectory() as directory:
            env = RUNNER._runtime_environment(
                commit_sha="a" * 40,
                codex_executable="/tmp/codex",
                runtime_root=Path(directory),
                model="gpt-test",
                reasoning_effort="high",
            )

        self.assertEqual(env["NOVEL_FORGE_EMBEDDING_PROVIDER"], "codex-cli")
        self.assertEqual(env["NOVEL_FORGE_EMBEDDING_MODEL"], "gpt-test")
        self.assertEqual(
            env["NOVEL_FORGE_NARRATIVE_EVALUATOR_PROVIDER"], "codex-cli"
        )
        self.assertEqual(env["NOVEL_FORGE_NARRATIVE_EVALUATOR_MODEL"], "gpt-test")
        self.assertEqual(
            env["NOVEL_FORGE_NARRATIVE_SEMANTIC_EVALUATION_REASONING_EFFORT"],
            "high",
        )


if __name__ == "__main__":
    unittest.main()
