from __future__ import annotations

import unittest

from novel_forge.modules.command_kernel.asset_commands import (
    AuthorityAssetWriteCommand,
    normalize_logical_ref,
)


class AuthorityAssetLocatorTests(unittest.TestCase):
    def test_normalize_logical_ref_uses_project_relative_posix_identity(self) -> None:
        self.assertEqual(
            normalize_logical_ref("chapter_plans\\chapter-1.json"),
            "chapter_plans/chapter-1.json",
        )

        for invalid in ("", "/data/chapter.json", "../chapter.json", "data/../chapter.json"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                normalize_logical_ref(invalid)

    def test_write_command_requires_operation_scoped_versioned_identity(self) -> None:
        command = AuthorityAssetWriteCommand(
            operation_id="operation-1",
            project_id="project-1",
            asset_id="asset-1",
            asset_type="chapter_plan",
            logical_ref="chapter_plans/chapter-1.json",
            category="chapter_plans",
            output_key="chapter.plan",
            role="primary",
            content={"id": "asset-1", "type": "chapter_plan"},
            expected_current_asset_version_id=None,
            reference_asset_ids=(),
            qualification_policy="chapter-plan-v1",
            trace_id="trace-1",
            correlation_id="correlation-1",
            causation_id="causation-1",
        )

        self.assertEqual(command.logical_ref, "chapter_plans/chapter-1.json")
        self.assertEqual(command.reference_asset_ids, ())

        with self.assertRaises(ValueError):
            AuthorityAssetWriteCommand(
                operation_id="",
                project_id="project-1",
                asset_id="asset-1",
                asset_type="chapter_plan",
                logical_ref="chapter_plans/chapter-1.json",
                category="chapter_plans",
                output_key="chapter.plan",
                role="primary",
                content={},
                qualification_policy="chapter-plan-v1",
                trace_id="trace-1",
                correlation_id="correlation-1",
            )


if __name__ == "__main__":
    unittest.main()
