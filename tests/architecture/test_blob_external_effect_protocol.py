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

    def test_legacy_blob_repository_dispatch_methods_fail_closed(self) -> None:
        source = (
            ROOT / "src/novel_forge/storage/asset_blob_repositories.py"
        ).read_text(encoding="utf-8")
        self.assertGreaterEqual(
            source.count("BLOB_EXTERNAL_EFFECT_PROTOCOL_DEPRECATED"),
            7,
        )


if __name__ == "__main__":
    unittest.main()
