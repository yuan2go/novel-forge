from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_AUTHORITY_FILES = (
    ROOT / "src/novel_forge/api/app.py",
    ROOT / "src/novel_forge/api/authority_app.py",
    ROOT / "src/novel_forge/api/routers/authority_projects.py",
    ROOT / "src/novel_forge/api/routers/authority_tasks.py",
    ROOT / "src/novel_forge/api/routers/authority_assets.py",
    ROOT / "src/novel_forge/api/routers/source_authority.py",
    ROOT / "src/novel_forge/api/routers/mkaos_authority.py",
    ROOT / "src/novel_forge/workers/source_authority.py",
    ROOT / "src/novel_forge/workers/mkaos_authority.py",
    *sorted((ROOT / "src/novel_forge/modules/project_authority").glob("*.py")),
    *sorted((ROOT / "src/novel_forge/modules/task_authority").glob("*.py")),
    *sorted((ROOT / "src/novel_forge/modules/source_authority").glob("*.py")),
    *sorted((ROOT / "src/novel_forge/modules/mkaos_authority").glob("*.py")),
)

FORBIDDEN = (
    "LocalStorage(",
    "storage.write_asset",
    "storage.write_json",
    "storage.read_asset",
    "storage.list_json",
    "legacy_tasks",
    "novel_forge.storage.local",
    "novel_forge.api.product",
    "novel_forge.api.legacy_app import",
    "Path.read_text",
    "Path.write_text",
)

# The selector may import the development-only app after its explicit
# production fail-closed branch.  It is not reachable in production and is
# removed when the development UI migration reaches zero Legacy dependencies.
ALLOWLIST = {
    (
        "src/novel_forge/api/app.py",
        "novel_forge.api.legacy_app import",
    ): {
        "reason": "development-only compatibility entrypoint behind production fail-closed guard",
        "delete_when": "WP-12 development product routers are fully Authority-backed",
    },
}


class PostgreSqlAuthorityProductionBoundaryTests(unittest.TestCase):
    def test_authority_entrypoints_have_no_filesystem_or_legacy_task_authority(self) -> None:
        findings: list[str] = []
        for path in PRODUCTION_AUTHORITY_FILES:
            source = path.read_text(encoding="utf-8")
            for marker in FORBIDDEN:
                relative = str(path.relative_to(ROOT))
                if marker in source and (relative, marker) not in ALLOWLIST:
                    findings.append(f"{relative}: {marker}")
        self.assertEqual(findings, [])

    def test_production_selector_is_fail_closed(self) -> None:
        source = (ROOT / "src/novel_forge/api/app.py").read_text(encoding="utf-8")
        self.assertIn('resolved.environment == "production"', source)
        self.assertIn("production API requires NOVEL_FORGE_STORAGE_AUTHORITY=postgresql", source)
        self.assertIn("create_authority_app(resolved)", source)

    def test_task_center_has_no_legacy_retry_api(self) -> None:
        source = (
            ROOT / "web/admin/app/features/tasks/api.ts"
        ).read_text(encoding="utf-8")
        self.assertNotIn('"/product/tasks/retry"', source)
        self.assertNotIn('"/product/tasks/dead-letters/retry"', source)
        self.assertIn("/product/tasks/${encodeURIComponent(operationId)}/recover", source)
        self.assertIn(
            "/product/tasks/outbox/${encodeURIComponent(row.task_id)}/requeue",
            source,
        )

    def test_mkaos_source_ui_uses_verified_blob_authority(self) -> None:
        source = (
            ROOT / "web/admin/app/features/mkaos/api.ts"
        ).read_text(encoding="utf-8")
        self.assertNotIn('postJson("/product/mkaos/sources"', source)
        self.assertIn('postJson("/product/source-governance/documents"', source)
        self.assertIn('fetchJson<MkaosRow[]>("/product/mkaos/assets?limit=500")', source)

    def test_source_api_admits_and_worker_recovers_from_postgresql(self) -> None:
        router = (
            ROOT / "src/novel_forge/api/routers/source_authority.py"
        ).read_text(encoding="utf-8")
        worker = (
            ROOT / "src/novel_forge/workers/source_authority.py"
        ).read_text(encoding="utf-8")
        scheduler = (
            ROOT / "src/novel_forge/modules/source_authority/scheduler.py"
        ).read_text(encoding="utf-8")

        self.assertIn("return application.admit(", router)
        self.assertNotIn("return application.execute(", router)
        self.assertIn("SourceAuthorityScheduler", worker)
        self.assertIn("authority_operation AS operation", scheduler)
        self.assertIn("authority_lease_acquisition AS lease", scheduler)

    def test_mkaos_api_separates_admission_worker_and_governance_decision(self) -> None:
        router = (
            ROOT / "src/novel_forge/api/routers/mkaos_authority.py"
        ).read_text(encoding="utf-8")
        worker = (
            ROOT / "src/novel_forge/workers/mkaos_authority.py"
        ).read_text(encoding="utf-8")
        application = (
            ROOT / "src/novel_forge/modules/mkaos_authority/application.py"
        ).read_text(encoding="utf-8")

        self.assertIn("application.admit_candidate", router)
        self.assertIn("application.admit_approval", router)
        self.assertNotIn("application.execute_candidate", router)
        self.assertIn("MkaosAuthorityScheduler", worker)
        self.assertIn('asset_type="knowledge_card_candidate"', application)
        self.assertIn('asset_type="knowledge_governance_decision"', application)
        self.assertIn('asset_type="knowledge_card"', application)


if __name__ == "__main__":
    unittest.main()
