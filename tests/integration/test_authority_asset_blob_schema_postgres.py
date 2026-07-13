from __future__ import annotations

import unittest

import psycopg

from tests.integration.authority_postgres_support import (
    ensure_migrated,
    identifier,
    transaction,
)


def insert_asset(cursor: psycopg.Cursor, *, asset_id: str, project_id: str) -> None:
    cursor.execute(
        """
        INSERT INTO authority_asset (asset_id, project_id, asset_type)
        VALUES (%s, %s, 'draft_chapter')
        """,
        [asset_id, project_id],
    )


def insert_asset_version(
    cursor: psycopg.Cursor,
    *,
    asset_version_id: str,
    asset_id: str,
    version_number: int = 1,
    lifecycle: str = "DRAFT",
    eligibility: str = "PENDING_EVALUATION",
    governance: str = "CLEAR",
) -> None:
    cursor.execute(
        """
        INSERT INTO authority_asset_version (
            asset_version_id,
            asset_id,
            version_number,
            lifecycle,
            eligibility,
            governance,
            content,
            content_hash
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
        """,
        [
            asset_version_id,
            asset_id,
            version_number,
            lifecycle,
            eligibility,
            governance,
            '{"text":"versioned"}',
            f"hash:{asset_version_id}",
        ],
    )


def insert_blob(
    cursor: psycopg.Cursor,
    *,
    blob_id: str,
    project_id: str,
    status: str = "AVAILABLE",
    legal_hold: bool = False,
) -> None:
    cursor.execute(
        """
        INSERT INTO authority_blob (
            blob_id,
            project_id,
            object_key,
            expected_hash,
            expected_size,
            actual_hash,
            actual_size,
            status,
            legal_hold
        )
        VALUES (%s, %s, %s, %s, 10, %s, 10, %s, %s)
        """,
        [blob_id, project_id, f"objects/{blob_id}", f"hash:{blob_id}", f"hash:{blob_id}", status, legal_hold],
    )


def insert_blob_reference(
    cursor: psycopg.Cursor,
    *,
    reference_id: str,
    asset_version_id: str,
    blob_id: str,
) -> None:
    cursor.execute(
        """
        INSERT INTO authority_asset_version_blob_reference (
            reference_id,
            asset_version_id,
            blob_id,
            role,
            ordinal,
            media_type,
            content_hash
        )
        SELECT %s, %s, blob_id, 'content', 0, 'application/json', actual_hash
        FROM authority_blob
        WHERE blob_id = %s
        """,
        [reference_id, asset_version_id, blob_id],
    )


class AuthorityAssetBlobSchemaPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_asset_version_state_dimensions_reject_unknown_values(self) -> None:
        dimensions = {
            "lifecycle": "UNKNOWN_LIFECYCLE",
            "eligibility": "UNKNOWN_ELIGIBILITY",
            "governance": "UNKNOWN_GOVERNANCE",
        }
        for field, invalid_value in dimensions.items():
            with self.subTest(field=field):
                project = identifier("project")
                asset = identifier("asset")
                values = {field: invalid_value}
                with self.assertRaises(psycopg.errors.CheckViolation):
                    with transaction() as connection, connection.cursor() as cursor:
                        insert_asset(cursor, asset_id=asset, project_id=project)
                        insert_asset_version(
                            cursor,
                            asset_version_id=identifier("version"),
                            asset_id=asset,
                            **values,
                        )

    def test_blob_status_rejects_unknown_value(self) -> None:
        with self.assertRaises(psycopg.errors.CheckViolation):
            with transaction() as connection, connection.cursor() as cursor:
                insert_blob(
                    cursor,
                    blob_id=identifier("blob"),
                    project_id=identifier("project"),
                    status="UNKNOWN_BLOB_STATE",
                )

    def test_asset_has_at_most_one_active_version(self) -> None:
        project = identifier("project")
        asset = identifier("asset")
        with self.assertRaises(psycopg.errors.UniqueViolation):
            with transaction() as connection, connection.cursor() as cursor:
                insert_asset(cursor, asset_id=asset, project_id=project)
                insert_asset_version(
                    cursor,
                    asset_version_id=identifier("version-1"),
                    asset_id=asset,
                    lifecycle="ACTIVE",
                )
                insert_asset_version(
                    cursor,
                    asset_version_id=identifier("version-2"),
                    asset_id=asset,
                    version_number=2,
                    lifecycle="ACTIVE",
                )

    def test_active_asset_version_content_cannot_be_modified_in_place(self) -> None:
        project = identifier("project")
        asset = identifier("asset")
        version = identifier("version")
        with transaction() as connection, connection.cursor() as cursor:
            insert_asset(cursor, asset_id=asset, project_id=project)
            insert_asset_version(
                cursor,
                asset_version_id=version,
                asset_id=asset,
                lifecycle="ACTIVE",
            )
        with self.assertRaises(psycopg.errors.CheckViolation):
            with transaction() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE authority_asset_version
                    SET content = '{"text":"mutated"}'::jsonb,
                        content_hash = 'hash:mutated'
                    WHERE asset_version_id = %s
                    """,
                    [version],
                )

    def test_blob_reference_cannot_be_updated_or_deleted(self) -> None:
        project = identifier("project")
        asset = identifier("asset")
        version = identifier("version")
        blob = identifier("blob")
        reference = identifier("reference")
        with transaction() as connection, connection.cursor() as cursor:
            insert_asset(cursor, asset_id=asset, project_id=project)
            insert_asset_version(cursor, asset_version_id=version, asset_id=asset)
            insert_blob(cursor, blob_id=blob, project_id=project)
            insert_blob_reference(
                cursor,
                reference_id=reference,
                asset_version_id=version,
                blob_id=blob,
            )
        for statement in (
            "UPDATE authority_asset_version_blob_reference SET role = 'other' WHERE reference_id = %s",
            "DELETE FROM authority_asset_version_blob_reference WHERE reference_id = %s",
        ):
            with self.subTest(statement=statement):
                with self.assertRaises(psycopg.errors.CheckViolation):
                    with transaction() as connection, connection.cursor() as cursor:
                        cursor.execute(statement, [reference])

    def test_unavailable_or_cross_project_blob_reference_is_rejected(self) -> None:
        for cross_project, blob_status in ((False, "UPLOADED"), (True, "AVAILABLE")):
            with self.subTest(cross_project=cross_project, blob_status=blob_status):
                project = identifier("project")
                asset = identifier("asset")
                version = identifier("version")
                blob = identifier("blob")
                with self.assertRaises(psycopg.errors.CheckViolation):
                    with transaction() as connection, connection.cursor() as cursor:
                        insert_asset(cursor, asset_id=asset, project_id=project)
                        insert_asset_version(cursor, asset_version_id=version, asset_id=asset)
                        insert_blob(
                            cursor,
                            blob_id=blob,
                            project_id=identifier("other-project") if cross_project else project,
                            status=blob_status,
                        )
                        insert_blob_reference(
                            cursor,
                            reference_id=identifier("reference"),
                            asset_version_id=version,
                            blob_id=blob,
                        )

    def test_asset_cannot_activate_after_referenced_blob_becomes_unavailable(self) -> None:
        project = identifier("project")
        asset = identifier("asset")
        version = identifier("version")
        blob = identifier("blob")
        with transaction() as connection, connection.cursor() as cursor:
            insert_asset(cursor, asset_id=asset, project_id=project)
            insert_asset_version(cursor, asset_version_id=version, asset_id=asset)
            insert_blob(cursor, blob_id=blob, project_id=project)
            insert_blob_reference(
                cursor,
                reference_id=identifier("reference"),
                asset_version_id=version,
                blob_id=blob,
            )
            cursor.execute(
                "UPDATE authority_blob SET status = 'CORRUPT' WHERE blob_id = %s",
                [blob],
            )
        with self.assertRaises(psycopg.errors.CheckViolation):
            with transaction() as connection, connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE authority_asset_version SET lifecycle = 'ACTIVE' WHERE asset_version_id = %s",
                    [version],
                )

    def test_referenced_or_legal_hold_blob_cannot_enter_deletion(self) -> None:
        for has_reference, legal_hold in ((True, False), (False, True)):
            with self.subTest(has_reference=has_reference, legal_hold=legal_hold):
                project = identifier("project")
                blob = identifier("blob")
                with transaction() as connection, connection.cursor() as cursor:
                    insert_blob(
                        cursor,
                        blob_id=blob,
                        project_id=project,
                        legal_hold=legal_hold,
                    )
                    if has_reference:
                        asset = identifier("asset")
                        version = identifier("version")
                        insert_asset(cursor, asset_id=asset, project_id=project)
                        insert_asset_version(cursor, asset_version_id=version, asset_id=asset)
                        insert_blob_reference(
                            cursor,
                            reference_id=identifier("reference"),
                            asset_version_id=version,
                            blob_id=blob,
                        )
                with self.assertRaises(psycopg.errors.CheckViolation):
                    with transaction() as connection, connection.cursor() as cursor:
                        cursor.execute(
                            "UPDATE authority_blob SET status = 'DELETE_PENDING' WHERE blob_id = %s",
                            [blob],
                        )

    def test_production_eligibility_requires_all_three_dimensions_and_available_blobs(self) -> None:
        project = identifier("project")
        asset = identifier("asset")
        version = identifier("version")
        blob = identifier("blob")
        with transaction() as connection, connection.cursor() as cursor:
            insert_asset(cursor, asset_id=asset, project_id=project)
            insert_asset_version(
                cursor,
                asset_version_id=version,
                asset_id=asset,
                lifecycle="ACTIVE",
                eligibility="ELIGIBLE",
                governance="CLEAR",
            )
            insert_blob(cursor, blob_id=blob, project_id=project)
            insert_blob_reference(
                cursor,
                reference_id=identifier("reference"),
                asset_version_id=version,
                blob_id=blob,
            )
            cursor.execute(
                "SELECT authority_asset_version_is_production_eligible(%s)",
                [version],
            )
            self.assertTrue(cursor.fetchone()[0])
            cursor.execute(
                "UPDATE authority_asset_version SET governance = 'QUARANTINED' WHERE asset_version_id = %s",
                [version],
            )
            cursor.execute(
                "SELECT authority_asset_version_is_production_eligible(%s)",
                [version],
            )
            self.assertFalse(cursor.fetchone()[0])


if __name__ == "__main__":
    unittest.main()
