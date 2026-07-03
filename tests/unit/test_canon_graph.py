from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.canon_graph import build_canon_graph, check_canon_graph_conflicts, persist_canon_graph_issues, query_canon_graph
from novel_forge.modules.longform_stability import create_arc_plan, create_canon_database
from novel_forge.schemas import DraftChapter, ForeshadowingGraph, WorldBible
from novel_forge.storage.local import LocalStorage


class CanonGraphTests(unittest.TestCase):
    def test_unified_graph_queries_canon_character_arc_foreshadowing_and_world_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            _seed_governance_assets(storage, project_id="canon-p")

            graph = build_canon_graph(storage, project_id="canon-p")
            query = query_canon_graph(storage, {"project_id": "canon-p", "query": "阿照"})

            self.assertTrue(graph["summary"]["coverage"]["character"])
            self.assertTrue(graph["summary"]["coverage"]["arc"])
            self.assertTrue(graph["summary"]["coverage"]["foreshadowing"])
            self.assertTrue(graph["summary"]["coverage"]["world_rule"])
            self.assertGreaterEqual(query["match_count"], 1)
            self.assertEqual(query["matches"][0]["canonical_name"], "阿照")

    def test_canon_graph_conflicts_convert_to_review_issues(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            _seed_governance_assets(storage, project_id="canon-p")
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Conflict draft",
                    content={
                        "chapter": 3,
                        "text": "沈砚带着无关宗门线回到夜档司，顺手提起竹筹，还让无代价复活成为规则。",
                        "copyright_boundary": "project-owned unit fixture",
                    },
                    metadata={"project_id": "canon-p"},
                ),
            )

            check = check_canon_graph_conflicts(storage, {"target_path": str(draft_path.relative_to(storage.root)), "project_id": "canon-p"})
            persisted = persist_canon_graph_issues(storage, {"target_path": str(draft_path.relative_to(storage.root)), "project_id": "canon-p"})

            self.assertEqual(check["status"], "blocked")
            self.assertTrue(any(item["issue_type"] == "canon_conflict" for item in check["conflicts"]))
            self.assertTrue(any("forbidden expansion" in item["message"] for item in check["conflicts"]))
            self.assertGreaterEqual(persisted["review_issue_summary"]["blocking_count"], 1)


def _seed_governance_assets(storage: LocalStorage, *, project_id: str) -> None:
    create_canon_database(
        storage,
        project_id=project_id,
        entities=[
            {
                "entity_id": "azhao",
                "entity_type": "character",
                "canonical_name": "阿照",
                "aliases": [],
                "forbidden_aliases": ["沈砚"],
                "role": "protagonist",
                "status": "active",
            }
        ],
    )
    create_arc_plan(
        storage,
        arc_id="archive-tax-arc",
        title="旧税契卷",
        chapter_range="1-10",
        arc_question="竹筹是谁留下的",
        protagonist_goal="查明旧税契",
        villain_goal="拖延归档",
        required_payoffs=["解释竹筹来源"],
        forbidden_expansion=["无关宗门线"],
        project_id=project_id,
    )
    storage.write_asset(
        "continuity",
        ForeshadowingGraph(
            title="Foreshadowing graph",
            content={
                "graph_id": "fg-unit",
                "clues": [{"clue_id": "bamboo", "name": "竹筹", "target_truth": "旧税契责任人", "status": "dropped"}],
                "edges": [],
                "created_at": "2026-07-03T00:00:00Z",
            },
            metadata={"project_id": project_id},
        ),
    )
    storage.write_asset(
        "continuity",
        WorldBible(
            title="World rules",
            content={
                "setting": "夜档司",
                "rules": [{"name": "代价规则", "forbidden_terms": ["无代价复活"], "description": "复活必须付出代价"}],
                "conflict_system": "账册和代价",
            },
            metadata={"project_id": project_id},
        ),
    )


if __name__ == "__main__":
    unittest.main()
