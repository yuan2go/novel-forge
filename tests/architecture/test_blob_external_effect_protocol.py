from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class BlobExternalEffectProtocolArchitectureTests(unittest.TestCase):
    def test_blob_runtime_routes_dispatch_and_receipts_through_generic_protocol(self) -> None:
        source = (
            ROOT / "src/novel_forge/modules/command_kernel/asset_runtime.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("repository.plan_effect(", source)
        self.assertNotIn("repository.begin_dispatch(", source)
        self.assertNotIn("repository.accept_upload_receipt(", source)
        self.assertIn("prepare_effect_dispatch(", source)
        self.assertIn("accept_external_effect_receipt(", source)
        self.assertIn("mark_external_effect_unknown(", source)

    def test_legacy_blob_repository_dispatch_methods_are_removed(self) -> None:
        source = (
            ROOT / "src/novel_forge/storage/asset_blob_repositories.py"
        ).read_text(encoding="utf-8")
        for method in (
            "plan_effect",
            "begin_dispatch",
            "dispatch_for_update",
            "record_inbox",
            "insert_receipt",
            "accept_upload_receipt",
        ):
            self.assertNotIn(f"def {method}(", source)


if __name__ == "__main__":
    unittest.main()
