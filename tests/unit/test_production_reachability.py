from __future__ import annotations

from pathlib import Path
import unittest

from novel_forge.tools.production_reachability import (
    build_production_reachability_manifest,
)


ROOT = Path(__file__).resolve().parents[2]


class ProductionReachabilityManifestTests(unittest.TestCase):
    def test_manifest_derives_book_and_chapter_reachability_from_compose(self) -> None:
        manifest = build_production_reachability_manifest(ROOT)
        by_name = {item["name"]: item for item in manifest["capabilities"]}

        for name in ("book.production.coordinate", "chapter.slice.run"):
            item = by_name[name]
            self.assertTrue(item["code_exists"])
            self.assertTrue(item["composed"])
            self.assertTrue(item["deployed"])
            self.assertTrue(item["runtime_reachable"])
            self.assertTrue(item["authority_backed"])
            self.assertTrue(item["worker_backed"])
            self.assertEqual(item["proof_level"], "ARCHITECTURE_REACHABLE")
            self.assertEqual(item["proof_sha"], manifest["proof_sha"])

    def test_manifest_does_not_upgrade_architecture_to_runtime_proof(self) -> None:
        manifest = build_production_reachability_manifest(ROOT)
        self.assertIn("not runtime", manifest["proof_boundary"])
        self.assertTrue(
            all(
                item["proof_level"]
                not in {"REAL_PROVIDER_PROVEN", "PRODUCTION_VERIFIED"}
                for item in manifest["capabilities"]
            )
        )


if __name__ == "__main__":
    unittest.main()
