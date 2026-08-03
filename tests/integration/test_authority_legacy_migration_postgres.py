from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from novel_forge.modules.legacy_migration import LegacyMigrationService
from novel_forge.modules.project_authority import ProjectAuthorityQuery
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated, identifier


class LegacyMigrationAuthorityPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_import_is_resumable_ineligible_and_reconciled(self) -> None:
        project_id = identifier("legacy-project")
        workspace_id = identifier("legacy-workspace")
        service = LegacyMigrationService(
            DATABASE_URL,
            application_build_id="legacy-migration-integration",
            commit_sha="b" * 40,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspaces = root / "data" / "workspaces"
            materials = root / "data" / "materials"
            workspaces.mkdir(parents=True)
            materials.mkdir(parents=True)
            self._write(
                workspaces / "workspace.json",
                {
                    "id": workspace_id,
                    "type": "project_workspace_state",
                    "title": "Imported Project",
                    "content": {
                        "project_id": project_id,
                        "memory": {"project_title": "Imported Project"},
                        "project_config": {
                            "genre": "mystery",
                            "style_profile_path": "data/styles/legacy.json",
                        },
                    },
                    "references": [],
                },
            )
            self._write(
                materials / "material.json",
                {
                    "id": "material-1",
                    "type": "material_card",
                    "project_id": project_id,
                    "content": {"mechanism": "pressure escalates through visible cost"},
                    "references": [],
                },
            )
            for path in root.rglob("*"):
                path.chmod(0o555 if path.is_dir() else 0o444)
            root.chmod(0o555)
            first = service.import_snapshot(root)
            second = service.import_snapshot(root, resume=True)
            verified = service.verify(first["migration_run_id"], snapshot_root=root)

        self.assertIn(first["status"], {"SUCCEEDED", "QUARANTINED"})
        self.assertEqual(second["migration_run_id"], first["migration_run_id"])
        self.assertEqual(second["counts"], first["counts"])
        self.assertEqual(verified["status"], "PASS")
        self.assertEqual(verified["production_assets_activated"], 0)
        self.assertEqual(verified["needs_review_count"], 2)
        project = ProjectAuthorityQuery(DATABASE_URL).require_project(project_id)
        self.assertEqual(project["status"], "PAUSED")
        self.assertNotIn("style_profile_path", project["content"]["config"])
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(*), MIN(version.lifecycle), MIN(version.eligibility),
                       MIN(qualification.decision)
                FROM authority_asset AS asset
                JOIN authority_asset_version AS version ON version.asset_id = asset.asset_id
                JOIN authority_asset_qualification AS qualification
                  ON qualification.asset_version_id = version.asset_version_id
                WHERE asset.project_id = %s AND asset.asset_type = 'legacy_import_candidate'
                """,
                [project_id],
            )
            count, lifecycle, eligibility, decision = uow.cursor.fetchone()
            uow.cursor.execute(
                """
                SELECT COUNT(*) FROM authority_operation
                WHERE project_id=%s AND definition_name='legacy_migration.asset.import'
                """,
                [project_id],
            )
            operation_count = int(uow.cursor.fetchone()[0])
        self.assertEqual(int(count), 2)
        self.assertEqual((lifecycle, eligibility, decision), ("IMPORTED", "PENDING_EVALUATION", "PENDING_EVALUATION"))
        self.assertEqual(operation_count, 2)

    @staticmethod
    def _write(path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
