from __future__ import annotations

import unittest

from novel_forge.modules.chapter_authority.chapter_plan_views import (
    build_draft_plan_view,
    normalize_authoritative_chapter_plan,
)
from novel_forge.modules.command_kernel.errors import KernelError


class ChapterPlanFidelityTests(unittest.TestCase):
    def test_rich_plan_survives_normalization_and_draft_view(self) -> None:
        source = {
            "project_id": "project-1", "chapter": 7, "title": "The Debt",
            "premise": "A promise comes due.", "chapter_function": "payoff",
            "chapter_objective": "Force the protagonist to choose a public loss.",
            "cast": ["protagonist", "rival"],
            "relationship_pairs": [["protagonist", "rival"]],
            "scene_sequence": [{"scene_id": "s1", "goal": "collect the debt"}],
            "reader_promise_actions": [{"promise_id": "p1", "action": "pay"}],
            "reward_payoff": [{"reward_id": "r1"}],
            "canon_expected_changes": [{"state_kind": "relationship"}],
            "chapter_hook": "The creditor names the next price.",
            "next_chapter_bridge": "The rival follows.",
        }
        normalized, report = normalize_authoritative_chapter_plan(
            project_id="project-1", expected_chapter=7, content=source,
            asset_version_id="plan-v7", content_hash="sha256:plan7",
        )
        view = build_draft_plan_view(normalized)

        self.assertNotEqual(report.decision, "BLOCKED")
        self.assertEqual(view["scene_sequence"], source["scene_sequence"])
        self.assertEqual(view["reader_promise_actions"], source["reader_promise_actions"])
        self.assertEqual(view["source_chapter_plan_asset_version_id"], "plan-v7")

    def test_legacy_fields_are_mapped_with_compatibility_evidence(self) -> None:
        normalized, report = normalize_authoritative_chapter_plan(
            project_id="project-1", expected_chapter=1,
            content={
                "chapter": 1, "title": "Legacy", "premise": "A debt.",
                "objective": "Make a choice.", "beats": ["choice", "cost"],
                "closing_hook": "A second debt appears.",
            },
            asset_version_id="legacy-v1", content_hash="sha256:legacy",
        )

        self.assertEqual(normalized["chapter_objective"], "Make a choice.")
        self.assertEqual(report.compatibility_mappings["beats"], "scene_sequence")
        self.assertEqual(report.decision, "ELIGIBLE_WITH_WARNINGS")

    def test_title_and_premise_only_are_not_a_complete_plan(self) -> None:
        with self.assertRaisesRegex(KernelError, "CHAPTER_PLAN_SEMANTIC_FIELDS_MISSING"):
            normalize_authoritative_chapter_plan(
                project_id="project-1", expected_chapter=1,
                content={"chapter": 1, "title": "Thin", "premise": "Not enough."},
                asset_version_id="thin-v1", content_hash="sha256:thin",
            )

    def test_cross_project_plan_is_rejected(self) -> None:
        with self.assertRaisesRegex(KernelError, "CHAPTER_PLAN_CROSS_PROJECT"):
            normalize_authoritative_chapter_plan(
                project_id="project-1", expected_chapter=1,
                content={
                    "project_id": "project-2", "chapter": 1, "title": "Wrong",
                    "premise": "Wrong.", "chapter_objective": "Wrong.",
                    "scene_sequence": ["wrong"], "chapter_hook": "Wrong.",
                },
                asset_version_id="wrong-v1", content_hash="sha256:wrong",
            )

    def test_different_plan_versions_produce_different_normalized_digests(self) -> None:
        base = {
            "chapter": 1, "title": "Versioned", "premise": "A choice.",
            "chapter_objective": "Choose.", "scene_sequence": ["scene-a"],
            "chapter_hook": "A hook.",
        }
        first, _ = normalize_authoritative_chapter_plan(
            project_id="project-1", expected_chapter=1, content=base,
            asset_version_id="plan-v1", content_hash="sha256:v1",
        )
        second, _ = normalize_authoritative_chapter_plan(
            project_id="project-1", expected_chapter=1,
            content={**base, "scene_sequence": ["scene-b"]},
            asset_version_id="plan-v2", content_hash="sha256:v2",
        )

        self.assertNotEqual(first["normalized_digest"], second["normalized_digest"])


if __name__ == "__main__":
    unittest.main()
