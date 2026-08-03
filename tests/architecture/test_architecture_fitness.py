from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from novel_forge.tools.architecture_fitness import (
    _provider_direct_violations,
    _repository_boundary_violations,
    build_report,
)


ROOT = Path(__file__).resolve().parents[2]


class ArchitectureFitnessTests(unittest.TestCase):
    def test_current_production_boundary_passes_fitness_rules(self) -> None:
        report = build_report(ROOT)
        self.assertEqual(report["status"], "PASS", report)
        self.assertGreaterEqual(report["checked_domain_packages"], 100)
        self.assertGreaterEqual(report["checked_domain_files"], 30)
        self.assertGreaterEqual(report["checked_provider_files"], 600)
        self.assertGreaterEqual(report["classified_production_entries"], 16)

    def test_provider_direct_call_scan_rejects_sdk_http_and_cli_bypasses(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "bad_provider.py"
            path.write_text(
                """
import openai
import subprocess

def call(client):
    client.responses.create(model='x')
    subprocess.run(['openai', 'responses', 'create'])
    return 'https://api.openai.com/v1/responses'
""",
                encoding="utf-8",
            )
            violations = _provider_direct_violations(root, (path,), ())
        self.assertEqual(
            {row["rule"] for row in violations},
            {
                "provider-direct-import",
                "provider-direct-call",
                "provider-cli-call",
                "provider-direct-http-endpoint",
            },
        )

    def test_cross_domain_repository_scan_rejects_concrete_repository_import(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            planning = root / "src/novel_forge/modules/hierarchical_planning"
            planning.mkdir(parents=True)
            (planning / "bad.py").write_text(
                "from novel_forge.storage.story_state_repositories import StoryStateRepository\n",
                encoding="utf-8",
            )
            violations = _repository_boundary_violations(
                root,
                {
                    "repository_boundary_rules": [
                        {
                            "owner_roots": [
                                "src/novel_forge/modules/hierarchical_planning"
                            ],
                            "forbidden_imports": [
                                "novel_forge.storage.story_state_repositories"
                            ],
                        }
                    ]
                },
            )
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["rule"], "cross-domain-repository-import")


if __name__ == "__main__":
    unittest.main()
