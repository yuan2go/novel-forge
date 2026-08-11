from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from novel_forge.api.authority_app import create_authority_app
from novel_forge.infrastructure.settings import IndustrialSettings


class AuthorityApiSurfaceTests(unittest.TestCase):
    def test_track_b_minimal_profile_does_not_construct_provider_or_legacy_routes(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ",
            {
                "NOVEL_FORGE_APPLICATION_BUILD_ID": "track-b-minimal-unit",
                "NOVEL_FORGE_COMMIT_SHA": "e" * 40,
                "NOVEL_FORGE_ENVIRONMENT": "production",
                "NOVEL_FORGE_LOCAL_OPERATOR_PRINCIPAL_ID": "operator-unit",
            },
            clear=False,
        ):
            app = create_authority_app(
                IndustrialSettings(
                    root=Path(directory),
                    environment="production",
                    storage_authority="postgresql",
                    authority_runtime_profile="track-b-minimal",
                    database_url="postgresql://authority-test.invalid/test",
                )
            )
            paths = set(app.openapi()["paths"])

        self.assertIn("/authority/books", paths)
        self.assertIn("/authority/books/{book_id}/design-candidates", paths)
        self.assertIn("/ready", paths)
        self.assertNotIn("/authority/chapters/run", paths)
        self.assertFalse(any("provider" in path for path in paths))

    def test_track_b_minimal_profile_rejects_legacy_write_or_fallback(self) -> None:
        for field in ("legacy_write_enabled", "silent_legacy_fallback_enabled"):
            with self.subTest(field=field), self.assertRaisesRegex(
                ValueError, "forbids Legacy writes, dual write, and silent fallback"
            ):
                IndustrialSettings(
                    root=Path("."),
                    environment="production",
                    storage_authority="postgresql",
                    authority_runtime_profile="track-b-minimal",
                    **{field: True},
                )

    def test_required_product_reads_are_exposed_by_postgresql_app(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ",
            {
                "NOVEL_FORGE_APPLICATION_BUILD_ID": "authority-api-unit",
                "NOVEL_FORGE_COMMIT_SHA": "d" * 40,
                "NOVEL_FORGE_ENVIRONMENT": "test",
                "NOVEL_FORGE_MODEL_PROVIDER": "mock",
                "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": directory,
            },
            clear=False,
        ):
            app = create_authority_app(
                IndustrialSettings(
                    root=Path(directory),
                    environment="test",
                    storage_authority="postgresql",
                    database_url="postgresql://authority-test.invalid/test",
                )
            )
            paths = set(app.openapi()["paths"])
        self.assertTrue(
            {
                "/product/projects",
                "/product/projects/operating-dashboard",
                "/product/projects/{project_id}/bindings",
                "/product/projects/{project_id}/bindings/{binding_type}",
                "/product/projects/{project_id}/bindings/{binding_type}/remove",
                "/product/tasks",
                "/product/tasks/{operation_id}/recover",
                "/product/tasks/outbox/{outbox_id}/requeue",
                "/product/system/health",
                "/product/analysis/reports",
                "/product/context/assets",
                "/product/manuscript/workbench",
                "/product/review-issues",
                "/product/feedback/assets",
                "/product/publishing/assets",
                "/product/source-governance/documents",
                "/product/source-governance/documents/{source_document_id}",
                "/product/source-governance/documents/{source_document_id}/transforms",
                "/product/source-governance/transforms/{source_transform_id}/chunks",
                "/product/source-governance/invalidations",
                "/product/source-imports",
                "/product/source-imports/preview",
                "/product/source-imports/{import_job_id}",
                "/product/source-imports/{import_job_id}/preview",
                "/product/source-imports/{import_job_id}/files",
                "/product/source-imports/{import_job_id}/work",
                "/product/source-imports/{import_job_id}/downstream",
                "/product/source-imports/{import_job_id}/resume",
                "/product/source-imports/reprocessing/apply",
                "/product/source-imports/reprocessing/{plan_asset_version_id}",
                "/product/mkaos/knowledge-candidates",
                "/product/mkaos/knowledge-candidates/{candidate_asset_version_id}/approve",
                "/product/mkaos/knowledge-cards",
                "/product/mkaos/knowledge-packs",
                "/product/mkaos/knowledge-packs/{knowledge_pack_id}",
                "/product/mkaos/knowledge-packs/{knowledge_pack_id}/diff",
                "/product/temporal-query",
                "/product/content-intelligence/pacing",
                "/product/content-intelligence/hooks",
            }.issubset(paths)
        )

    def test_project_scoped_principal_cannot_query_another_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ",
            {
                "NOVEL_FORGE_APPLICATION_BUILD_ID": "authority-api-unit",
                "NOVEL_FORGE_COMMIT_SHA": "d" * 40,
                "NOVEL_FORGE_ENVIRONMENT": "test",
                "NOVEL_FORGE_MODEL_PROVIDER": "mock",
                "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": directory,
                "NOVEL_FORGE_AUTHORITY_PROJECT_SCOPE": "project-allowed",
            },
            clear=False,
        ):
            app = create_authority_app(
                IndustrialSettings(
                    root=Path(directory),
                    environment="test",
                    storage_authority="postgresql",
                    database_url="postgresql://authority-test.invalid/test",
                )
            )
            with TestClient(app) as client:
                responses = (
                    client.get("/product/tasks", params={"project_id": "project-denied"}),
                    client.get(
                        "/product/analysis/reports",
                        params={"project_id": "project-denied"},
                    ),
                    client.get("/product/projects/project-denied"),
                    client.get("/product/projects/project-denied/bindings"),
                    client.post(
                        "/product/tasks/cancel",
                        json={
                            "operation_id": "operation-denied",
                            "project_id": "project-denied",
                            "expected_version": 1,
                            "idempotency_key": "cancel-denied",
                            "reason": "test",
                            "actor_id": "attacker-supplied",
                            "trace_id": "trace-denied",
                            "correlation_id": "correlation-denied",
                        },
                    ),
                    client.post(
                        "/product/tasks/operation-denied/recover",
                        json={
                            "project_id": "project-denied",
                            "expected_version": 1,
                            "idempotency_key": "recover-denied",
                            "reason": "test",
                        },
                    ),
                    client.post(
                        "/product/tasks/outbox/outbox-denied/requeue",
                        json={
                            "project_id": "project-denied",
                            "expected_attempt_count": 3,
                            "idempotency_key": "outbox-denied",
                            "reason": "test",
                        },
                    ),
                    client.post(
                        "/product/source-governance/documents",
                        json={
                            "project_id": "project-denied",
                            "workspace_id": "workspace-denied",
                            "blob_id": "blob-denied",
                            "title": "denied",
                            "source_kind": "text",
                            "rights_authorization": "owned",
                            "idempotency_key": "source-denied",
                        },
                    ),
                    client.post(
                        "/product/source-governance/documents/source-denied/transforms",
                        json={
                            "project_id": "project-denied",
                            "workspace_id": "workspace-denied",
                            "normalization_version": "normalize:v1",
                            "chunking_version": "chunk:v1",
                            "chunking_policy_hash": "sha256:" + "a" * 64,
                            "chunks": [
                                {
                                    "chunk_index": 0,
                                    "blob_id": "blob-denied",
                                    "content_hash": "sha256:" + "b" * 64,
                                    "byte_size": 1,
                                    "character_count": 1,
                                    "token_count": 1,
                                    "source_byte_start": 0,
                                    "source_byte_end": 1,
                                }
                            ],
                            "idempotency_key": "transform-denied",
                        },
                    ),
                    client.post(
                        "/product/mkaos/knowledge-candidates",
                        json={
                            "project_id": "project-denied",
                            "workspace_id": "workspace-denied",
                            "execution_asset_version_id": "execution-denied:v1",
                            "candidate": {"concept_name": "denied"},
                            "evidence_spans": [
                                {
                                    "source_chunk_asset_version_id": "chunk-denied:v1",
                                    "chunk_byte_start": 0,
                                    "chunk_byte_end": 1,
                                    "evidence_hash": "sha256:" + "c" * 64,
                                }
                            ],
                            "abstraction_policy_version": "anti-copy:v1",
                            "idempotency_key": "mkaos-denied",
                        },
                    ),
                    client.get(
                        "/product/source-imports/import-denied",
                        params={"project_id": "project-denied"},
                    ),
                )

        self.assertEqual([response.status_code for response in responses], [403] * 11)


if __name__ == "__main__":
    unittest.main()
