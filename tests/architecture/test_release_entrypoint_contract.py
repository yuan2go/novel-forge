from __future__ import annotations

import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]


class ReleaseEntrypointContractTests(unittest.TestCase):
    def test_dockerfile_default_cmd_is_accepted_by_authority_parser(self) -> None:
        source = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        match = re.search(r"^CMD\s+(\[.*\])$", source, flags=re.MULTILINE)
        self.assertIsNotNone(match)
        command = json.loads(match.group(1))
        self.assertEqual(
            command[:4],
            ["python", "-m", "novel_forge.cli.authority", "serve-api"],
        )
        self.assertNotIn("--root", command)

        from novel_forge.cli.authority import _authority_parser

        parsed = _authority_parser().parse_args(command[3:])
        self.assertEqual(parsed.command, "serve-api")
        self.assertEqual(parsed.host, "0.0.0.0")
        self.assertEqual(parsed.port, 8000)

    def test_python_module_entrypoint_invokes_the_authority_cli(self) -> None:
        source = (ROOT / "src/novel_forge/cli/authority.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('if __name__ == "__main__":', source)
        self.assertIn("raise SystemExit(main())", source)

    def test_standard_make_targets_do_not_reference_removed_services_or_commands(self) -> None:
        source = (ROOT / "Makefile").read_text(encoding="utf-8")
        forbidden = (
            "docker compose up -d postgres redis qdrant minio",
            "docker compose build api worker web",
            "postgres-init --root",
            "postgres-sync --root",
            "docker compose logs -f api worker web",
        )
        for marker in forbidden:
            self.assertNotIn(marker, source)
        for target in (
            "authority-up:",
            "authority-down:",
            "authority-build:",
            "authority-smoke:",
            "authority-logs:",
            "authority-test:",
            "authority-postgres-test:",
            "authority-compose-config-check:",
        ):
            self.assertIn(target, source)

    def test_core_ci_has_no_removed_authority_cli_commands(self) -> None:
        source = (ROOT / ".github/workflows/core-os-ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("postgres-init", source)
        self.assertNotIn("postgres-sync", source)
        self.assertIn('test "$(git rev-parse HEAD)" = "${GITHUB_SHA}"', source)
        self.assertIn("make pr-governance", source)
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("novel_forge.tools.pr_governance --base-sha", makefile)
        gate = (ROOT / "src/novel_forge/tools/pr_governance.py").read_text(encoding="utf-8")
        self.assertIn('"scripts/run_p0_backend_qualification.py", "--profile"', gate)
        self.assertIn("validate_p0_backend_qualification_report", gate)
        self.assertIn("p0-backend-qualification-${{ github.sha }}", source)


if __name__ == "__main__":
    unittest.main()
