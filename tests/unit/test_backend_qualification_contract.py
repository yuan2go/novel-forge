from __future__ import annotations

import unittest
from pathlib import Path

from novel_forge.tools.backend_qualification_contract import (
    load_qualification_manifest,
)
from novel_forge.tools.architecture_manifest import check_tests


ROOT = Path(__file__).resolve().parents[2]


class BackendQualificationManifestTests(unittest.TestCase):
    def test_integration_collection_is_complete_and_postgresql_required(self) -> None:
        manifest = load_qualification_manifest(ROOT)

        integration = next(
            item for item in manifest.pytest_collections if item.name == "integration"
        )

        self.assertEqual(integration.paths, ("tests/integration",))
        self.assertEqual(integration.classification, "POSTGRESQL_REQUIRED")
        self.assertTrue(integration.complete_collection)
        self.assertFalse(integration.allow_skips)

    def test_repository_test_collections_have_exactly_one_qualification_class(
        self,
    ) -> None:
        result = check_tests(ROOT)

        classifications = {
            item["name"]: item["qualification_class"]
            for item in result["collections"]
        }

        self.assertEqual(
            classifications,
            {
                "acceptance": "BACKEND_NON_POSTGRESQL",
                "architecture": "BACKEND_NON_POSTGRESQL",
                "integration": "POSTGRESQL_REQUIRED",
                "unit": "BACKEND_NON_POSTGRESQL",
            },
        )
        integration = next(
            item for item in result["collections"] if item["name"] == "integration"
        )
        self.assertTrue(integration["complete_collection"])
        self.assertEqual(integration["source_file_count"], integration["collected_file_count"])


if __name__ == "__main__":
    unittest.main()
