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
        self.assertEqual(verified["production_assets_activated"], 1)
        self.assertEqual(verified["needs_review_count"], 1)
        self.assertEqual(verified["target_asset_version_count"], 2)
        self.assertEqual(verified["distinct_target_asset_version_count"], 2)
        self.assertEqual(verified["target_hash_match_count"], 2)
        self.assertEqual(verified["qualification_count"], 2)
        project = ProjectAuthorityQuery(DATABASE_URL).require_project(project_id)
        self.assertEqual(project["status"], "PAUSED")
        self.assertNotIn("style_profile_path", project["content"]["config"])
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(*),
                       COUNT(*) FILTER (WHERE item.status='ACTIVATED'),
                       COUNT(*) FILTER (WHERE item.status='NEEDS_REVIEW'),
                       ARRAY_AGG(asset.asset_type ORDER BY asset.asset_type)
                FROM authority_legacy_migration_item AS item
                JOIN authority_asset_version AS version
                  ON version.asset_version_id = item.target_asset_version_id
                JOIN authority_asset AS asset ON asset.asset_id = version.asset_id
                JOIN authority_asset_qualification AS qualification
                  ON qualification.asset_version_id = version.asset_version_id
                WHERE item.migration_run_id = %s
                """,
                [first["migration_run_id"]],
            )
            count, activated, needs_review, asset_types = uow.cursor.fetchone()
            uow.cursor.execute(
                """
                SELECT COUNT(*) FROM authority_operation
                WHERE project_id=%s
                  AND definition_name='legacy_migration.material_card.convert'
                """,
                [project_id],
            )
            operation_count = int(uow.cursor.fetchone()[0])
        self.assertEqual(int(count), 2)
        self.assertEqual((int(activated), int(needs_review)), (1, 1))
        self.assertEqual(list(asset_types), ["material_card", "project_record"])
        self.assertEqual(operation_count, 1)

    def test_synthetic_snapshot_fault_resume_conflicts_and_quarantine(self) -> None:
        project_id = identifier("legacy-synthetic-project")
        other_project_id = identifier("legacy-other-project")
        service = LegacyMigrationService(
            DATABASE_URL,
            application_build_id="legacy-migration-fault-integration",
            commit_sha="c" * 40,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "data" / "assets"
            workspaces = root / "data" / "workspaces"
            sources = root / "data" / "sources"
            assets.mkdir(parents=True)
            workspaces.mkdir(parents=True)
            sources.mkdir(parents=True)
            self._write(
                workspaces / "project-1.json",
                {
                    "id": identifier("workspace-1"),
                    "type": "project_workspace_state",
                    "title": "Synthetic Project",
                    "content": {"project_id": project_id},
                    "references": [],
                },
            )
            self._write(
                workspaces / "project-2.json",
                {
                    "id": identifier("workspace-2"),
                    "type": "project_workspace_state",
                    "title": "Other Project",
                    "content": {"project_id": other_project_id},
                    "references": [],
                },
            )
            duplicate = {
                "id": "material-duplicate",
                "type": "material_card",
                "project_id": project_id,
                "content": {"mechanism": "bounded pressure"},
                "references": [],
            }
            self._write(assets / "01-material.json", duplicate)
            self._write(assets / "02-material-duplicate.json", duplicate)
            self._write(
                assets / "03-material-conflict.json",
                {**duplicate, "content": {"mechanism": "conflicting content"}},
            )
            self._write(
                assets / "04-other-project.json",
                {
                    "id": "other-asset",
                    "type": "material_card",
                    "project_id": other_project_id,
                    "content": {"mechanism": "other scope"},
                    "references": [],
                },
            )
            self._write(
                assets / "05-cross-project.json",
                {
                    "id": "cross-project-plan",
                    "type": "chapter_plan",
                    "project_id": project_id,
                    "content": {"goal": "must quarantine"},
                    "references": ["other-asset"],
                },
            )
            self._write(
                assets / "06-missing-reference.json",
                {
                    "id": "missing-reference-plan",
                    "type": "chapter_plan",
                    "project_id": project_id,
                    "content": {"goal": "must quarantine"},
                    "references": ["not-present"],
                },
            )
            self._write(
                assets / "07-approved-plan.json",
                {
                    "id": "approved-plan",
                    "type": "book_plan",
                    "status": "APPROVED",
                    "project_id": project_id,
                    "content": {"volumes": []},
                    "metadata": {"migration_approved": True},
                    "references": [],
                },
            )
            self._write(
                sources / "08-unverified-source.json",
                {
                    "id": "unverified-source",
                    "type": "source_document",
                    "project_id": project_id,
                    "content": {"rights_authorization": "unknown"},
                    "references": [],
                },
            )
            (assets / "09-large-blob.json").write_text(
                json.dumps({"type": "binary_blob", "payload": "x" * (8 * 1024 * 1024)}),
                encoding="utf-8",
            )
            for path in root.rglob("*"):
                path.chmod(0o555 if path.is_dir() else 0o444)
            root.chmod(0o555)

            with self.assertRaisesRegex(RuntimeError, "MIGRATION_FAULT_INJECTED"):
                service.import_snapshot(root, fault_after_items=2)
            resumed = service.import_snapshot(root, resume=True)
            replayed = service.import_snapshot(root, resume=True)
            verified = service.verify(resumed["migration_run_id"], snapshot_root=root)

        self.assertEqual(resumed["migration_run_id"], replayed["migration_run_id"])
        self.assertEqual(resumed["item_counts"], replayed["item_counts"])
        self.assertEqual(verified["status"], "PASS")
        self.assertTrue(verified["reconciled"])
        self.assertGreaterEqual(verified["production_assets_activated"], 3)
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT reason_code, source_payload, object_reference
                FROM authority_data_quarantine
                WHERE migration_run_id=%s
                ORDER BY reason_code
                """,
                [resumed["migration_run_id"]],
            )
            quarantine = uow.cursor.fetchall()
            uow.cursor.execute(
                """
                SELECT COUNT(*), COUNT(DISTINCT target_asset_version_id)
                FROM authority_legacy_migration_item
                WHERE migration_run_id=%s AND target_asset_version_id IS NOT NULL
                """,
                [resumed["migration_run_id"]],
            )
            target_count, distinct_target_count = uow.cursor.fetchone()
        reasons = {row[0] for row in quarantine}
        self.assertTrue(
            {
                "BUSINESS_IDENTITY_CONTENT_CONFLICT",
                "CROSS_PROJECT_REFERENCE",
                "MISSING_REFERENCE",
                "SOURCE_RIGHTS_UNVERIFIED",
                "OBJECT_STORE_REQUIRED",
            }
            <= reasons
        )
        large = next(row for row in quarantine if row[0] == "OBJECT_STORE_REQUIRED")
        self.assertEqual(large[1], {})
        self.assertEqual(large[2]["verification_status"], "REQUIRED")
        self.assertEqual(int(target_count), int(distinct_target_count))

    @staticmethod
    def _write(path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
