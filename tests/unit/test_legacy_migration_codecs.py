from __future__ import annotations

import unittest

from novel_forge.modules.legacy_migration.codecs import (
    DEFAULT_CODEC_REGISTRY,
    MigrationCodecNotFound,
)
from novel_forge.modules.legacy_migration.scanner import LegacySnapshotRecord


class LegacyMigrationCodecTests(unittest.TestCase):
    def _record(self, source_type: str, *, approved: bool = False) -> LegacySnapshotRecord:
        return LegacySnapshotRecord(
            source_ref=f"data/assets/{source_type}.json",
            category="assets",
            source_hash="sha256:" + "a" * 64,
            size_bytes=100,
            stable_business_key=f"{source_type}-1",
            project_id="project-1",
            workspace_id="workspace-1",
            source_asset_type=source_type,
            payload={
                "id": f"{source_type}-1",
                "type": source_type,
                "status": "ACTIVE" if approved else "DRAFT",
                "content": {
                    "title": "Native migration",
                    "legacy_file_path": "/tmp/legacy.json",
                },
                "metadata": {"migration_approved": approved},
            },
            references=("ref-1",),
            decision="IMPORT",
            status="VALIDATED",
        )

    def test_registry_covers_current_backend_business_families(self) -> None:
        required = {
            "project_workspace_state",
            "book_record",
            "book_design",
            "story_design",
            "book_plan",
            "volume_plan",
            "arc_plan",
            "chapter_plan",
            "world_bible",
            "character_card",
            "context_bundle",
            "draft_chapter",
            "review_report",
            "canon_database",
            "story_state_snapshot",
            "source_document",
            "material_card",
            "knowledge_card",
            "knowledge_pack",
            "workflow_definition",
            "agent_checkpoint",
            "feedback_import_batch",
            "reader_outcome",
            "release_package",
            "publishing_log",
        }
        self.assertTrue(required <= DEFAULT_CODEC_REGISTRY.source_types)

    def test_conversion_produces_native_content_and_stable_reconciliation(self) -> None:
        codec = DEFAULT_CODEC_REGISTRY.resolve("chapter_plan_version")
        candidate = codec.convert_record(self._record("chapter_plan_version"))

        self.assertEqual(candidate.target_asset_type, "chapter_plan")
        self.assertNotIn("legacy_file_path", candidate.content)
        self.assertEqual(
            candidate.stable_business_identity,
            "project-1:chapter_plan:chapter_plan_version-1",
        )
        self.assertEqual(candidate.lifecycle, "IMPORTED")
        self.assertEqual(candidate.eligibility, "PENDING_EVALUATION")
        self.assertEqual(candidate.activation_decision, "NEEDS_REVIEW")
        self.assertEqual(candidate.reconciliation["reference_count"], 1)
        self.assertEqual(candidate.reconciliation["target_content_hash"], candidate.content_hash)

    def test_explicit_approval_can_qualify_and_activate_native_version(self) -> None:
        codec = DEFAULT_CODEC_REGISTRY.resolve("material_card")
        candidate = codec.convert_record(self._record("material_card", approved=True))

        self.assertEqual(candidate.lifecycle, "ACTIVE")
        self.assertEqual(candidate.eligibility, "ELIGIBLE")
        self.assertEqual(candidate.activation_decision, "ACTIVATE")

    def test_unknown_type_fails_closed(self) -> None:
        with self.assertRaisesRegex(MigrationCodecNotFound, "no native migration codec"):
            DEFAULT_CODEC_REGISTRY.resolve("invented_legacy_payload")

    def test_manifest_exposes_full_codec_contract(self) -> None:
        row = next(
            item
            for item in DEFAULT_CODEC_REGISTRY.to_manifest()
            if item["source_type"] == "book_design"
        )
        required = {
            "source_type",
            "target_asset_type",
            "schema_version",
            "stable_business_identity",
            "scope_resolution",
            "reference_resolution",
            "conversion",
            "validation",
            "qualification_policy",
            "activation_policy",
            "rebuildable",
            "quarantine_rules",
            "reconciliation_rules",
        }
        self.assertTrue(required <= row.keys())


if __name__ == "__main__":
    unittest.main()
