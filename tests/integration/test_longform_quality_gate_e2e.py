from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.longform_stability import (
    create_arc_plan,
    create_canon_database,
    create_longform_artifacts_for_draft,
    evaluate_longform_stability_gate,
)
from novel_forge.schemas import DraftChapter
from novel_forge.storage.local import LocalStorage


class LongformQualityGateE2ETests(unittest.TestCase):
    def test_draft_to_state_pattern_motif_and_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            create_canon_database(
                storage,
                entities=[
                    {
                        "entity_id": "azhao",
                        "entity_type": "character",
                        "canonical_name": "阿照",
                        "aliases": [],
                        "forbidden_aliases": ["沈砚", "江砚", "顾砚秋"],
                        "role": "protagonist",
                        "status": "active",
                    },
                    {
                        "entity_id": "night_archive_office",
                        "entity_type": "organization",
                        "canonical_name": "夜档司",
                        "aliases": [],
                        "forbidden_aliases": ["北档房", "夜档库"],
                        "role": "core_organization",
                        "status": "active",
                    },
                ],
                project_id="project_e2e",
            )
            create_arc_plan(
                storage,
                arc_id="arc_03",
                title="桥南隐税卷",
                chapter_range="1-10",
                arc_question="谁在复活旧城隐税机制？",
                protagonist_goal="找到隐税机制源头",
                villain_goal="逼夜档司承接旧债",
                project_id="project_e2e",
            )
            draft = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Controlled Chapter",
                    content={
                        "chapter": 1,
                        "text": (
                            "阿照在夜档司案前查到竹筹穿册。陶主簿昨夜将旧竹筹藏入铺牌，"
                            "想借旧制逼铺户承债。阿照没有新增税种，只封存竹筹并确认旧城隐税机制露出一角。"
                        ),
                        "copyright_boundary": "test fixture original draft",
                    },
                    metadata={"project_id": "project_e2e"},
                ),
            )

            artifacts = create_longform_artifacts_for_draft(storage, draft)
            gate = evaluate_longform_stability_gate(storage, draft)

            self.assertTrue(artifacts["chapter_state_path"])
            self.assertTrue(artifacts["chapter_pattern_report_path"])
            self.assertTrue(artifacts["motif_budget_report_path"])
            self.assertTrue(gate["passed"], gate["blocking_issues"])
            self.assertTrue(gate["gates"]["canon_consistency_passed"])
            self.assertTrue(gate["gates"]["chapter_state_preexisting"])
            self.assertTrue(gate["gates"]["pattern_similarity_passed"])
            self.assertTrue(gate["gates"]["motif_budget_passed"])


if __name__ == "__main__":
    unittest.main()
