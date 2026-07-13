from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from novel_forge.modules.command_kernel.asset_runtime import (
    AssetCommandContext,
    accept_blob_upload_receipt,
    activate_asset_version,
    apply_blob_legal_hold,
    begin_blob_upload_dispatch,
    bind_blob_to_asset_version,
    create_asset,
    create_asset_version,
    qualify_asset_version,
    reconcile_blob_upload,
    release_blob,
    release_blob_legal_hold,
    request_blob_upload,
    reserve_blob,
    verify_blob,
)
from novel_forge.modules.command_kernel.errors import KernelError
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    transaction,
)


class AssetBlobProtocolPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_verified_upload_binds_qualifies_and_activates_asset_version(self) -> None:
        context = self._context()
        asset_id = create_asset(DATABASE_URL, context, asset_type="draft_chapter")
        version_id = create_asset_version(
            DATABASE_URL,
            context,
            asset_id=asset_id,
            content={"text": "authoritative"},
            content_hash="sha256:asset-v1",
        )
        blob_id = reserve_blob(
            DATABASE_URL,
            context,
            provider="local_file_object_store",
            object_key=f"objects/{context.project_id}/chapter.json",
            expected_hash="sha256:blob-v1",
            expected_size=19,
            media_type="application/json",
        )
        effect = request_blob_upload(DATABASE_URL, context, blob_id=blob_id)
        dispatch = begin_blob_upload_dispatch(
            DATABASE_URL,
            context,
            external_effect_id=effect["external_effect_id"],
            provider="local_file_object_store",
        )
        receipt = accept_blob_upload_receipt(
            DATABASE_URL,
            context,
            dispatch_id=dispatch["dispatch_id"],
            provider="local_file_object_store",
            receipt_id=identifier("receipt"),
            object_key=f"objects/{context.project_id}/chapter.json",
            actual_hash="sha256:blob-v1",
            actual_size=19,
            payload_hash="sha256:receipt-v1",
            evidence={"provider_version": "local-file-v1"},
        )
        self.assertFalse(receipt["replayed"])
        verified = verify_blob(DATABASE_URL, context, blob_id=blob_id)
        self.assertEqual(verified["status"], "AVAILABLE")
        reference_id = bind_blob_to_asset_version(
            DATABASE_URL,
            context,
            asset_version_id=version_id,
            blob_id=blob_id,
            role="content",
            ordinal=0,
        )
        qualify_asset_version(
            DATABASE_URL,
            context,
            asset_version_id=version_id,
            decision="ELIGIBLE",
            policy_version="asset-production-v1",
            evidence={"blob_id": blob_id},
        )
        activate_asset_version(DATABASE_URL, context, asset_version_id=version_id)

        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT version.lifecycle, version.eligibility, version.governance,
                       blob.status, reference.reference_id,
                       authority_asset_version_is_production_eligible(version.asset_version_id),
                       receipt.payload->'evidence'->>'provider_version'
                FROM authority_asset_version AS version
                JOIN authority_asset_version_blob_reference AS reference
                  ON reference.asset_version_id = version.asset_version_id
                JOIN authority_blob AS blob ON blob.blob_id = reference.blob_id
                JOIN authority_external_effect AS effect
                  ON effect.external_effect_id = blob.upload_effect_id
                JOIN authority_external_effect_dispatch AS dispatch
                  ON dispatch.external_effect_id = effect.external_effect_id
                JOIN authority_external_receipt AS receipt
                  ON receipt.dispatch_id = dispatch.dispatch_id
                WHERE version.asset_version_id = %s
                """,
                [version_id],
            )
            self.assertEqual(
                cursor.fetchone(),
                (
                    "ACTIVE",
                    "ELIGIBLE",
                    "CLEAR",
                    "AVAILABLE",
                    reference_id,
                    True,
                    "local-file-v1",
                ),
            )

    def test_upload_request_is_idempotent_and_payload_drift_conflicts(self) -> None:
        context = self._context()
        blob_id = self._reserve(context)
        first = request_blob_upload(DATABASE_URL, context, blob_id=blob_id)
        second = request_blob_upload(DATABASE_URL, context, blob_id=blob_id)
        self.assertFalse(first["replayed"])
        self.assertTrue(second["replayed"])
        self.assertEqual(first["external_effect_id"], second["external_effect_id"])

        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE authority_blob SET expected_hash = 'sha256:changed' WHERE blob_id = %s",
                [blob_id],
            )
        with self.assertRaises(KernelError) as caught:
            request_blob_upload(DATABASE_URL, context, blob_id=blob_id)
        self.assertEqual(caught.exception.code, "EFFECT_DISPATCH_CONFLICT")

    def test_receipt_validation_quarantines_hash_size_and_key_mismatches(self) -> None:
        mismatches = (
            ("object_key", "objects/wrong", "BLOB_OBJECT_KEY_MISMATCH"),
            ("actual_hash", "sha256:wrong", "BLOB_HASH_MISMATCH"),
            ("actual_size", 99, "BLOB_SIZE_MISMATCH"),
        )
        for field, wrong, expected_code in mismatches:
            with self.subTest(field=field):
                context = self._context()
                blob_id = self._reserve(context)
                dispatch = self._request_and_dispatch(context, blob_id)
                payload = {
                    "dispatch_id": dispatch["dispatch_id"],
                    "provider": "fake_deterministic_provider",
                    "receipt_id": identifier("receipt"),
                    "object_key": f"objects/{context.project_id}/payload.bin",
                    "actual_hash": "sha256:expected",
                    "actual_size": 8,
                    "payload_hash": identifier("payload-hash"),
                    "evidence": {"scenario": field},
                }
                payload[field] = wrong
                accept_blob_upload_receipt(DATABASE_URL, context, **payload)
                with self.assertRaises(KernelError) as caught:
                    verify_blob(DATABASE_URL, context, blob_id=blob_id)
                self.assertEqual(caught.exception.code, expected_code)
                with transaction() as connection, connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT status FROM authority_blob WHERE blob_id = %s",
                        [blob_id],
                    )
                    self.assertEqual(cursor.fetchone()[0], "QUARANTINED")

    def test_duplicate_receipt_replays_and_conflicting_receipt_is_audited(self) -> None:
        context = self._context()
        blob_id = self._reserve(context)
        dispatch = self._request_and_dispatch(context, blob_id)
        receipt_id = identifier("receipt")
        values = {
            "dispatch_id": dispatch["dispatch_id"],
            "provider": "fake_deterministic_provider",
            "receipt_id": receipt_id,
            "object_key": f"objects/{context.project_id}/payload.bin",
            "actual_hash": "sha256:expected",
            "actual_size": 8,
            "payload_hash": "sha256:same-receipt",
            "evidence": {"provider": "fake"},
        }
        first = accept_blob_upload_receipt(DATABASE_URL, context, **values)
        replay = accept_blob_upload_receipt(DATABASE_URL, context, **values)
        self.assertFalse(first["replayed"])
        self.assertTrue(replay["replayed"])
        values["payload_hash"] = "sha256:conflicting-receipt"
        with self.assertRaises(KernelError) as caught:
            accept_blob_upload_receipt(DATABASE_URL, context, **values)
        self.assertEqual(caught.exception.code, "RECEIPT_PAYLOAD_CONFLICT")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) FROM authority_inbox_conflict
                WHERE consumer_name = 'blob.upload.receipt'
                  AND message_id = %s
                """,
                [f"fake_deterministic_provider:{receipt_id}"],
            )
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_unverified_and_cross_project_blob_binding_is_rejected(self) -> None:
        owner = self._context()
        other = self._context()
        asset_id = create_asset(DATABASE_URL, owner, asset_type="draft_chapter")
        version_id = create_asset_version(
            DATABASE_URL,
            owner,
            asset_id=asset_id,
            content={"text": "v1"},
            content_hash="sha256:v1",
        )
        blob_id = self._reserve(owner)
        for context, expected_code in (
            (owner, "BLOB_NOT_AVAILABLE"),
            (other, "CROSS_PROJECT_REFERENCE"),
        ):
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(KernelError) as caught:
                    bind_blob_to_asset_version(
                        DATABASE_URL,
                        context,
                        asset_version_id=version_id,
                        blob_id=blob_id,
                        role="content",
                        ordinal=0,
                    )
                self.assertEqual(caught.exception.code, expected_code)

    def test_legal_hold_and_reference_closure_block_release(self) -> None:
        context = self._context()
        blob_id = self._available_blob(context)
        apply_blob_legal_hold(
            DATABASE_URL,
            context,
            blob_id=blob_id,
            reason="litigation",
        )
        with self.assertRaises(KernelError) as held:
            release_blob(DATABASE_URL, context, blob_id=blob_id)
        self.assertEqual(held.exception.code, "BLOB_LEGAL_HOLD")
        release_blob_legal_hold(
            DATABASE_URL,
            context,
            blob_id=blob_id,
            reason="hold released",
        )
        asset_id = create_asset(DATABASE_URL, context, asset_type="draft_chapter")
        version_id = create_asset_version(
            DATABASE_URL,
            context,
            asset_id=asset_id,
            content={"text": "v1"},
            content_hash="sha256:v1",
        )
        bind_blob_to_asset_version(
            DATABASE_URL,
            context,
            asset_version_id=version_id,
            blob_id=blob_id,
            role="content",
            ordinal=0,
        )
        with self.assertRaises(KernelError) as referenced:
            release_blob(DATABASE_URL, context, blob_id=blob_id)
        self.assertEqual(referenced.exception.code, "BLOB_REFERENCE_EXISTS")

    def test_unknown_upload_requires_reconciliation_before_verification(self) -> None:
        context = self._context()
        blob_id = self._reserve(context)
        dispatch = self._request_and_dispatch(context, blob_id)
        reconcile_blob_upload(
            DATABASE_URL,
            context,
            dispatch_id=dispatch["dispatch_id"],
            outcome="UNKNOWN",
            evidence={"timeout_after_send": True},
        )
        with self.assertRaises(KernelError) as caught:
            verify_blob(DATABASE_URL, context, blob_id=blob_id)
        self.assertEqual(caught.exception.code, "BLOB_RECONCILIATION_REQUIRED")
        accept_blob_upload_receipt(
            DATABASE_URL,
            context,
            dispatch_id=dispatch["dispatch_id"],
            provider="fake_deterministic_provider",
            receipt_id=identifier("receipt"),
            object_key=f"objects/{context.project_id}/payload.bin",
            actual_hash="sha256:expected",
            actual_size=8,
            payload_hash=identifier("payload-hash"),
            evidence={"reconciled": True},
        )
        self.assertEqual(
            verify_blob(DATABASE_URL, context, blob_id=blob_id)["status"],
            "AVAILABLE",
        )

    def test_receipt_transaction_failure_rolls_back_receipt_and_blob_state(self) -> None:
        context = self._context()
        blob_id = self._reserve(context)
        dispatch = self._request_and_dispatch(context, blob_id)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE FUNCTION authority_test_fail_blob_receipt() RETURNS TRIGGER
                LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'forced receipt failure'; END $$
                """
            )
            cursor.execute(
                """
                CREATE TRIGGER authority_test_fail_blob_receipt_trigger
                BEFORE UPDATE OF status ON authority_blob
                FOR EACH ROW WHEN (NEW.status = 'UPLOADED')
                EXECUTE FUNCTION authority_test_fail_blob_receipt()
                """
            )
        try:
            with self.assertRaises(Exception):
                accept_blob_upload_receipt(
                    DATABASE_URL,
                    context,
                    dispatch_id=dispatch["dispatch_id"],
                    provider="fake_deterministic_provider",
                    receipt_id=identifier("receipt"),
                    object_key=f"objects/{context.project_id}/payload.bin",
                    actual_hash="sha256:expected",
                    actual_size=8,
                    payload_hash=identifier("payload-hash"),
                    evidence={},
                )
            with transaction() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT blob.status, dispatch.status,
                           (SELECT COUNT(*) FROM authority_external_receipt
                            WHERE dispatch_id = %s)
                    FROM authority_blob AS blob
                    JOIN authority_external_effect AS effect
                      ON effect.external_effect_id = blob.upload_effect_id
                    JOIN authority_external_effect_dispatch AS dispatch
                      ON dispatch.external_effect_id = effect.external_effect_id
                    WHERE blob.blob_id = %s
                    """,
                    [dispatch["dispatch_id"], blob_id],
                )
                self.assertEqual(cursor.fetchone(), ("UPLOADING", "SENT", 0))
        finally:
            with transaction() as connection, connection.cursor() as cursor:
                cursor.execute("DROP TRIGGER authority_test_fail_blob_receipt_trigger ON authority_blob")
                cursor.execute("DROP FUNCTION authority_test_fail_blob_receipt()")

    def test_concurrent_activation_accepts_only_one_version(self) -> None:
        context = self._context()
        asset_id = create_asset(DATABASE_URL, context, asset_type="draft_chapter")
        versions = [
            create_asset_version(
                DATABASE_URL,
                context,
                asset_id=asset_id,
                content={"version": number},
                content_hash=f"sha256:v{number}",
            )
            for number in (1, 2)
        ]
        barrier = Barrier(2)

        def activate(version_id: str) -> tuple[str, str]:
            barrier.wait(timeout=5)
            try:
                activate_asset_version(DATABASE_URL, context, asset_version_id=version_id)
                return version_id, "accepted"
            except KernelError as exc:
                return version_id, exc.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(activate, versions))
        self.assertEqual(
            sorted(value for _, value in outcomes),
            ["ASSET_ACTIVE_VERSION_CONFLICT", "accepted"],
        )

    def _context(self) -> AssetCommandContext:
        project_id = identifier("project")
        operation_id = identifier("operation")
        definition_name = identifier("asset-definition")
        with transaction() as connection, connection.cursor() as cursor:
            insert_definition(cursor, definition_name)
            insert_operation(
                cursor,
                operation_id=operation_id,
                definition_name=definition_name,
                project_id=project_id,
                status="EXECUTING",
            )
        return AssetCommandContext(
            operation_id=operation_id,
            project_id=project_id,
            actor_id="asset-handler",
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
            causation_id="",
        )

    def _reserve(self, context: AssetCommandContext) -> str:
        return reserve_blob(
            DATABASE_URL,
            context,
            provider="fake_deterministic_provider",
            object_key=f"objects/{context.project_id}/payload.bin",
            expected_hash="sha256:expected",
            expected_size=8,
            media_type="application/octet-stream",
        )

    def _request_and_dispatch(
        self,
        context: AssetCommandContext,
        blob_id: str,
    ) -> dict:
        effect = request_blob_upload(DATABASE_URL, context, blob_id=blob_id)
        return begin_blob_upload_dispatch(
            DATABASE_URL,
            context,
            external_effect_id=effect["external_effect_id"],
            provider="fake_deterministic_provider",
        )

    def _available_blob(self, context: AssetCommandContext) -> str:
        blob_id = self._reserve(context)
        dispatch = self._request_and_dispatch(context, blob_id)
        accept_blob_upload_receipt(
            DATABASE_URL,
            context,
            dispatch_id=dispatch["dispatch_id"],
            provider="fake_deterministic_provider",
            receipt_id=identifier("receipt"),
            object_key=f"objects/{context.project_id}/payload.bin",
            actual_hash="sha256:expected",
            actual_size=8,
            payload_hash=identifier("payload-hash"),
            evidence={},
        )
        verify_blob(DATABASE_URL, context, blob_id=blob_id)
        return blob_id


if __name__ == "__main__":
    unittest.main()
