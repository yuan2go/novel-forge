from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from novel_forge.modules.legacy_migration import scan_legacy_snapshot
from novel_forge.modules.legacy_migration.codecs import (
    DOMAIN_MIGRATION_ALIAS_GROUPS,
)


class LegacyMigrationScannerTests(unittest.TestCase):
    def test_scan_classifies_valid_corrupt_missing_cross_project_and_rights(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "data" / "materials"
            sources = root / "data" / "raw"
            runs = root / "data" / "runs"
            assets.mkdir(parents=True)
            sources.mkdir(parents=True)
            runs.mkdir(parents=True)
            self._write(
                assets / "a.json",
                {"id": "a", "type": "material_card", "project_id": "p1", "references": []},
            )
            self._write(
                assets / "cross.json",
                {"id": "cross", "type": "material_card", "project_id": "p2", "references": ["a"]},
            )
            self._write(
                assets / "missing.json",
                {"id": "missing", "type": "material_card", "project_id": "p1", "references": ["absent"]},
            )
            self._write(
                sources / "source.json",
                {"id": "source", "type": "source_document", "project_id": "p1", "rights_authorization": "unknown"},
            )
            self._write(
                runs / "run.json",
                {"id": "run", "type": "run_log", "project_id": "p1"},
            )
            (assets / "broken.json").write_text("{broken", encoding="utf-8")

            scan = scan_legacy_snapshot(root)

        by_id = {record.stable_business_key: record for record in scan.records}
        self.assertEqual(by_id["a"].status, "VALIDATED")
        self.assertEqual(by_id["cross"].error_code, "CROSS_PROJECT_REFERENCE")
        self.assertEqual(by_id["missing"].error_code, "MISSING_REFERENCE")
        self.assertEqual(by_id["source"].error_code, "SOURCE_RIGHTS_UNVERIFIED")
        self.assertEqual(by_id["run"].decision, "DISCARD_REBUILDABLE")
        broken = next(item for item in scan.records if item.source_ref.endswith("broken.json"))
        self.assertEqual(broken.error_code, "MALFORMED_JSON")
        self.assertTrue(scan.snapshot_hash.startswith("sha256:"))

    def test_alias_identity_conflicts_fail_closed_in_the_same_snapshot(self) -> None:
        for canonical, alias in DOMAIN_MIGRATION_ALIAS_GROUPS:
            with self.subTest(canonical=canonical, alias=alias):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    assets = root / "data" / "assets"
                    assets.mkdir(parents=True)
                    common = {
                        "id": "same-business-key",
                        "project_id": "project-1",
                        "content": {"objective": "canonical identity conflict"},
                    }
                    self._write(
                        assets / "01-canonical.json",
                        {**common, "type": canonical},
                    )
                    self._write(
                        assets / "02-alias.json",
                        {**common, "type": alias},
                    )

                    scan = scan_legacy_snapshot(root)

                self.assertEqual(scan.records[0].status, "VALIDATED")
                self.assertEqual(scan.records[1].status, "QUARANTINED")
                self.assertEqual(
                    scan.records[1].error_code,
                    "BUSINESS_IDENTITY_CONTENT_CONFLICT",
                )

    @staticmethod
    def _write(path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
