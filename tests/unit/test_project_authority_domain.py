from __future__ import annotations

import unittest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.project_authority.definitions import (
    PROJECT_AUTHORITY_OPERATIONS,
    project_authority_definitions,
)
from novel_forge.modules.project_authority.domain import (
    build_project_snapshot,
    transition_project_snapshot,
    update_project_snapshot,
)


class ProjectAuthorityDomainTests(unittest.TestCase):
    def test_create_update_and_lifecycle_are_deterministic(self) -> None:
        created = build_project_snapshot(
            project_id="project-1",
            workspace_id="workspace-1",
            payload={"title": "Bound Project", "book_number": 1},
        )
        updated = update_project_snapshot(
            created,
            {"stage": "planning", "health": "healthy", "config": {"genre": "mystery"}},
        )
        paused = transition_project_snapshot(updated, target_status="paused")

        self.assertEqual(created["status"], "ACTIVE")
        self.assertEqual(updated["stage"], "PLANNING")
        self.assertEqual(updated["config"], {"genre": "mystery"})
        self.assertEqual(paused["status"], "PAUSED")
        self.assertEqual(created["status"], "ACTIVE")

    def test_deleted_project_is_terminal(self) -> None:
        current = build_project_snapshot(
            project_id="project-1",
            workspace_id="workspace-1",
            payload={"title": "Bound Project"},
        )
        deleted = transition_project_snapshot(current, target_status="deleted")
        with self.assertRaisesRegex(KernelError, "cannot transition"):
            transition_project_snapshot(deleted, target_status="active")
        with self.assertRaisesRegex(KernelError, "cannot be updated"):
            update_project_snapshot(deleted, {"title": "Resurrected"})

    def test_filesystem_paths_are_rejected_as_authority_identity(self) -> None:
        with self.assertRaisesRegex(KernelError, "FILESYSTEM_AUTHORITY_FORBIDDEN"):
            build_project_snapshot(
                project_id="project-1",
                workspace_id="workspace-1",
                payload={
                    "title": "Unsafe Project",
                    "platform_profile_path": "data/platforms/local.json",
                },
            )

    def test_definitions_require_asset_audit_and_outbox_evidence(self) -> None:
        definitions = project_authority_definitions(
            application_build_id="build-1", commit_sha="a" * 40
        )
        self.assertEqual(
            {item["name"] for item in definitions}, set(PROJECT_AUTHORITY_OPERATIONS)
        )
        for definition in definitions:
            with self.subTest(definition["name"]):
                self.assertTrue(definition["enabled"])
                self.assertEqual(definition["execution_mode"], "worker")
                self.assertTrue(
                    definition["completion_contract"]["required_asset_selectors"]
                )
                self.assertIn(
                    "audit", definition["completion_contract"]["required_evidence"]
                )
                self.assertTrue(
                    definition["completion_contract"]["required_outbox_events"]
                )


if __name__ == "__main__":
    unittest.main()
