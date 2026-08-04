from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from novel_forge.tools.authority_coverage_manifest import FAMILIES, build_manifest, operation_catalog, write_manifest


class AuthorityCoverageManifestTests(unittest.TestCase):
    def test_manifest_is_deterministic_for_a_fixed_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src/novel_forge/modules/example.py"
            source.parent.mkdir(parents=True)
            source.write_text("from novel_forge.storage.local import LocalStorage\ndef save():\n storage=LocalStorage('.')\n storage.write_json('x', {})\n", encoding="utf-8")
            first = build_manifest(root, generated_at="2026-07-12T00:00:00+00:00")
            second = build_manifest(root, generated_at="2026-07-12T00:00:00+00:00")
            self.assertEqual(first, second)
            self.assertEqual(first["schema_version"], "postgresql-authority-run-evidence.v1")
            self.assertEqual(first["evidence_class"], "dynamic_run_evidence")
            self.assertIn("implementation_tree_identity", first)
            self.assertEqual(first["summary"]["authority_write"], 1)
            self.assertEqual(
                first["findings"][-1]["dependency"],
                "novel_forge.storage.local.LocalStorage.write_json",
            )

    def test_writer_emits_canonical_json_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src/novel_forge").mkdir(parents=True)
            output = root / "baseline.json"
            manifest = write_manifest(root, output, generated_at="2026-07-12T00:00:00+00:00")
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["artifact_hash"], manifest["artifact_hash"])

    def test_catalog_covers_every_required_operation_family(self) -> None:
        catalog = operation_catalog()
        self.assertTrue(set(FAMILIES).issubset({item["family"] for item in catalog}))
        self.assertNotIn("review_revision_publish", {item["name"] for item in catalog})
        self.assertTrue({"review.run", "review.resolve_issue", "revision.apply", "quality.run_completion_gate", "publishing.prepare_release", "publishing.submit"}.issubset({item["name"] for item in catalog}))
