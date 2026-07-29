from __future__ import annotations

import unittest
from pathlib import Path

from novel_forge.modules.chapter_production_bus.service import CHAPTER_PRODUCTION_STEPS
from novel_forge.tools.authority_parity_manifest import (
    AuthorityParityStatus,
    load_authority_parity_manifest,
    validate_authority_parity_manifest,
)


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "config" / "authority" / "authority-parity-manifest.json"


class AuthorityParityManifestTests(unittest.TestCase):
    def test_manifest_exactly_covers_real_legacy_chapter_steps(self) -> None:
        manifest = load_authority_parity_manifest(MANIFEST)

        self.assertEqual(
            {entry.legacy_step for entry in manifest.capabilities},
            set(CHAPTER_PRODUCTION_STEPS),
        )
        self.assertEqual(
            len(manifest.capabilities),
            len(CHAPTER_PRODUCTION_STEPS),
        )

    def test_manifest_definitions_handlers_outputs_and_evidence_are_valid(self) -> None:
        report = validate_authority_parity_manifest(MANIFEST, repo_root=ROOT)

        self.assertTrue(report.passed, report.to_dict())
        self.assertEqual(report.direct_write_bypasses, 0)
        self.assertEqual(report.missing_handlers, ())
        self.assertEqual(report.missing_output_contracts, ())
        self.assertTrue(
            all(
                entry.parity_status
                in {
                    AuthorityParityStatus.TESTED_WITH_FAKE,
                    AuthorityParityStatus.TESTED_WITH_REAL_PROVIDER,
                    AuthorityParityStatus.PRODUCTION_PROVEN,
                    AuthorityParityStatus.DEPRECATED,
                }
                for entry in report.manifest.capabilities
            )
        )

    def test_manifest_does_not_claim_real_provider_or_production_proof(self) -> None:
        manifest = load_authority_parity_manifest(MANIFEST)

        self.assertFalse(manifest.evidence_boundary["real_provider_proven"])
        self.assertFalse(manifest.evidence_boundary["production_verified"])
        self.assertNotIn(
            AuthorityParityStatus.PRODUCTION_PROVEN,
            {entry.parity_status for entry in manifest.capabilities},
        )


if __name__ == "__main__":
    unittest.main()
