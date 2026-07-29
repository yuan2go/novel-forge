from __future__ import annotations

import ast
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from novel_forge.modules.longform_recap.service import run_longform_recap
from novel_forge.modules.chapter_production_bus.service import (
    run_chapter_production_sequence,
    start_chapter_production,
)
from novel_forge.modules.book_authority.application import (
    BookProductionPolicy,
    BookProductionRequest,
    admit_book_production,
)
from novel_forge.storage.local import LocalStorage


ROOT = Path(__file__).resolve().parents[2]


class UnifiedExecutionBusinessBoundaryTests(unittest.TestCase):
    def test_local_storage_is_explicitly_non_authoritative(self) -> None:
        self.assertFalse(LocalStorage.authoritative)
        self.assertFalse(LocalStorage.production_writable)
        self.assertTrue(LocalStorage.rebuildable)

    def test_local_storage_write_fails_closed_in_production_like_environments(self) -> None:
        for environment in ("production", "staging", "production_like"):
            with self.subTest(environment=environment), tempfile.TemporaryDirectory() as root:
                storage = LocalStorage(root)
                with patch.dict(
                    os.environ,
                    {
                        "NOVEL_FORGE_ENVIRONMENT": environment,
                        "NOVEL_FORGE_STORAGE_AUTHORITY": "postgresql",
                    },
                    clear=False,
                ):
                    with self.assertRaisesRegex(
                        PermissionError, "PRODUCTION_DIRECT_WRITE_FORBIDDEN"
                    ):
                        storage.write_json("data/runs/illegal.json", {"type": "run"})

    def test_legacy_recap_is_blocked_before_any_production_write(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            storage = LocalStorage(root)
            with patch.dict(
                os.environ,
                {
                    "NOVEL_FORGE_ENVIRONMENT": "production",
                    "NOVEL_FORGE_STORAGE_AUTHORITY": "postgresql",
                },
                clear=False,
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "LEGACY_LONGFORM_RECAP_PRODUCTION_DISABLED"
                ):
                    run_longform_recap(storage, {"project_id": "project:1", "force": True})

    def test_book_authority_does_not_import_or_call_legacy_bus(self) -> None:
        book_root = ROOT / "src" / "novel_forge" / "modules" / "book_authority"
        forbidden = {
            "run_chapter_production_sequence",
            "start_chapter_production",
            "ChapterProductionBus",
        }
        found: set[str] = set()
        for path in book_root.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id in forbidden:
                    found.add(node.id)
                if isinstance(node, ast.Attribute) and node.attr in forbidden:
                    found.add(node.attr)
        self.assertEqual(found, set())

    def test_fixture_book_authority_is_explicitly_blocked_in_production(self) -> None:
        application = (
            ROOT
            / "src"
            / "novel_forge"
            / "modules"
            / "book_authority"
            / "application.py"
        ).read_text(encoding="utf-8")
        scheduler = (
            ROOT
            / "src"
            / "novel_forge"
            / "modules"
            / "book_authority"
            / "scheduler.py"
        ).read_text(encoding="utf-8")
        self.assertIn("LEGACY_BOOK_AUTHORITY_PRODUCTION_DISABLED", application)
        self.assertIn("LEGACY_BOOK_AUTHORITY_PRODUCTION_DISABLED", scheduler)
        with patch.dict(
            os.environ, {"NOVEL_FORGE_ENVIRONMENT": "production"}, clear=False
        ):
            with self.assertRaisesRegex(
                RuntimeError, "LEGACY_BOOK_AUTHORITY_PRODUCTION_DISABLED"
            ):
                admit_book_production(
                    "postgresql://must-not-be-used",
                    BookProductionRequest(
                        project_id="project:1",
                        workspace_id="workspace:1",
                        actor_id="actor:1",
                        trace_id="trace:1",
                        correlation_id="correlation:1",
                        idempotency_key="fixture-book:v1",
                        application_build_id="test",
                        commit_sha="a" * 40,
                        policy=BookProductionPolicy(target_chapter_count=1),
                    ),
                )

    def test_legacy_chapter_entrypoints_fail_before_read_or_write(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            storage = LocalStorage(root)
            for entrypoint, kwargs in (
                (
                    start_chapter_production,
                    {"outline_path": "missing.json", "environment": "production"},
                ),
                (
                    run_chapter_production_sequence,
                    {"outline_path": "missing.json", "environment": "staging"},
                ),
            ):
                with self.subTest(entrypoint=entrypoint.__name__):
                    with self.assertRaisesRegex(
                        ValueError, "LEGACY_CHAPTER_BUS_PRODUCTION_DISABLED"
                    ):
                        entrypoint(storage, **kwargs)
            self.assertFalse((Path(root) / "data").exists())

    def test_api_scheduler_and_book_services_do_not_write_authority_tables(self) -> None:
        paths = (
            ROOT / "src" / "novel_forge" / "api" / "routers" / "book_authority.py",
            ROOT / "src" / "novel_forge" / "modules" / "book_authority" / "production.py",
            ROOT / "src" / "novel_forge" / "modules" / "book_authority" / "governed_scheduler.py",
            ROOT / "src" / "novel_forge" / "modules" / "book_followup_authority" / "application.py",
        )
        violations: list[tuple[str, str]] = []
        for path in paths:
            source = path.read_text(encoding="utf-8")
            normalized = " ".join(source.upper().split())
            for marker in (
                "INSERT INTO AUTHORITY_",
                "UPDATE AUTHORITY_",
                "DELETE FROM AUTHORITY_",
            ):
                if marker in normalized:
                    violations.append((path.name, marker))
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
