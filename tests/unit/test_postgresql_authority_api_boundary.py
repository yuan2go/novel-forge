from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest.mock import patch

from novel_forge.api.app import create_app
from novel_forge.infrastructure.settings import IndustrialSettings


class PostgreSQLAuthorityApiBoundaryTests(unittest.TestCase):
    def test_production_defaults_to_postgresql_authority(self) -> None:
        settings = IndustrialSettings.from_env(
            env={
                "NOVEL_FORGE_ROOT": ".",
                "NOVEL_FORGE_ENVIRONMENT": "production",
                "NOVEL_FORGE_DATABASE_URL": "postgresql://authority",
            }
        )
        self.assertEqual(settings.environment, "production")
        self.assertEqual(settings.storage_authority, "postgresql")

    def test_production_cannot_select_legacy_authority(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be postgresql"):
            IndustrialSettings(
                root=Path("."),
                environment="production",
                storage_authority="legacy_local",
            )

    def test_postgresql_selector_never_constructs_legacy_app(self) -> None:
        settings = IndustrialSettings(
            root=Path("."),
            environment="production",
            storage_authority="postgresql",
            database_url="postgresql://authority",
        )
        sentinel = object()
        with (
            patch(
                "novel_forge.api.authority_app.create_authority_app",
                return_value=sentinel,
            ) as authority,
            patch(
                "novel_forge.api.legacy_app.create_app",
                side_effect=AssertionError("legacy app must not be constructed"),
            ) as legacy,
        ):
            self.assertIs(create_app(settings), sentinel)
        authority.assert_called_once_with(settings)
        legacy.assert_not_called()

    def test_authority_runtime_surface_has_no_localstorage_dependency(self) -> None:
        root = Path(__file__).resolve().parents[2] / "src" / "novel_forge"
        paths = [
            root / "api" / "app.py",
            root / "api" / "authority_app.py",
            root / "api" / "authority_dependencies.py",
            root / "api" / "routers" / "chapter_authority.py",
            root / "api" / "routers" / "content_authority.py",
        ]
        forbidden = {
            "novel_forge.storage.local",
            "novel_forge.api.services.postgres_fallback_policy",
        }
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imports = {
                node.module
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module
            }
            self.assertFalse(
                imports & forbidden,
                f"{path.relative_to(root)} imports a forbidden production dependency",
            )

    def test_command_admission_routes_are_explicitly_asynchronous(self) -> None:
        root = Path(__file__).resolve().parents[2] / "src" / "novel_forge" / "api" / "routers"
        for filename in ("chapter_authority.py", "content_authority.py"):
            tree = ast.parse((root / filename).read_text(encoding="utf-8"))
            commands = [
                decorator
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                for decorator in node.decorator_list
                if isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "post"
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
                and decorator.args[0].value == "/commands"
            ]
            self.assertEqual(len(commands), 1, filename)
            status = next(
                keyword.value.value
                for keyword in commands[0].keywords
                if keyword.arg == "status_code" and isinstance(keyword.value, ast.Constant)
            )
            self.assertEqual(status, 202, filename)


if __name__ == "__main__":
    unittest.main()
