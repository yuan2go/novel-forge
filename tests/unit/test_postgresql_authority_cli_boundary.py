from __future__ import annotations

import ast
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from novel_forge.cli import _authority_main, main
from novel_forge.infrastructure.settings import IndustrialSettings


class _Query:
    def list_runs(self, *, project_id: str, limit: int) -> list[dict]:
        return [{"project_id": project_id, "limit": limit}]


class PostgreSQLAuthorityCliBoundaryTests(unittest.TestCase):
    def test_legacy_cli_is_only_reached_by_explicit_legacy_command(self) -> None:
        with (
            patch(
                "novel_forge.infrastructure.settings.IndustrialSettings.from_env",
                return_value=IndustrialSettings(
                    root=Path("."),
                    environment="development",
                    storage_authority="postgresql",
                ),
            ),
            patch("novel_forge.cli.legacy.main", return_value=17) as legacy,
        ):
            self.assertEqual(main(["legacy", "projects"]), 17)
        legacy.assert_called_once_with(["projects"])

    def test_production_rejects_explicit_legacy_command(self) -> None:
        with patch(
            "novel_forge.infrastructure.settings.IndustrialSettings.from_env",
            return_value=IndustrialSettings(
                root=Path("."),
                environment="production",
                storage_authority="postgresql",
            ),
        ):
            self.assertEqual(main(["legacy", "projects"]), 1)

    def test_authority_query_command_uses_postgresql_query_port(self) -> None:
        settings = IndustrialSettings(
            root=Path("."),
            storage_authority="postgresql",
            database_url="postgresql://authority",
        )
        output = io.StringIO()
        with (
            patch(
                "novel_forge.api.authority_dependencies.build_chapter_authority_query",
                return_value=_Query(),
            ),
            redirect_stdout(output),
        ):
            status = _authority_main(
                ["authority-chapter-runs", "--project-id", "project-1", "--limit", "9"],
                settings,
            )
        self.assertEqual(status, 0)
        self.assertIn('"project_id": "project-1"', output.getvalue())
        self.assertIn('"limit": 9', output.getvalue())

    def test_authority_cli_surface_has_no_localstorage_import(self) -> None:
        path = Path(__file__).resolve().parents[2] / "src" / "novel_forge" / "cli" / "__init__.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        self.assertNotIn("novel_forge.storage.local", imports)
        self.assertNotIn("novel_forge.workflows", imports)


if __name__ == "__main__":
    unittest.main()
