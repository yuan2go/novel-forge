from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.novel_kg import (
    analyze_novel_kg_conflicts,
    build_novel_kg,
    build_novel_kg_context,
    build_novel_kg_cypher,
    create_novel_kg_snapshot,
    evaluate_novel_kg_gate,
    novel_kg_dirty_status,
    query_novel_kg,
    query_novel_kg_impact,
    query_novel_kg_paths,
    refresh_novel_kg,
)
from novel_forge.schemas import (
    CharacterCard,
    ChapterPlan,
    ContinuityBible,
    DraftChapter,
    ForeshadowingThread,
    PowerScaleRule,
    ReviewRulePack,
    WorldBible,
    WritingTemplate,
    validate_common_fields,
)
from novel_forge.storage.local import LocalStorage


class NovelKGTests(unittest.TestCase):
    def test_builds_unified_novel_kg_ontology_from_story_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            project_id = "project-kg"
            workspace_path = "data/workspaces/project-kg.json"
            metadata = {"project_id": project_id, "workspace_path": workspace_path}
            world = storage.write_asset(
                "worlds",
                WorldBible(
                    title="Clock City World",
                    content={
                        "setting": "Clock City",
                        "rules": ["Every bell toll consumes stored memory"],
                        "conflict_system": "factions fight over memory tariffs",
                        "factions": [{"name": "Archive Guild", "goal": "control the bells"}],
                        "locations": [{"name": "North Tower", "risk": "collapsed clockwork"}],
                        "props": [{"name": "Memory Key", "function": "opens sealed hour rooms"}],
                    },
                    metadata=metadata,
                ),
            )
            character = storage.write_asset(
                "characters",
                CharacterCard(
                    title="Lin Qiao",
                    content={
                        "name": "林乔",
                        "aliases": ["钟城行者"],
                        "role": "protagonist",
                        "external_goal": "recover the Memory Key",
                        "internal_need": "trust allies",
                        "motivation_chain": ["loss", "choice", "cost"],
                        "faction": "Archive Guild",
                        "current_location": "North Tower",
                    },
                    metadata=metadata,
                    references=[storage.read_asset(world).id],
                ),
            )
            storage.write_asset(
                "chapters",
                ChapterPlan(
                    title="Clock chapter plan",
                    content={
                        "chapter": 1,
                        "objective": "人物：钟城行者 enters North Tower and finds 道具：Memory Key",
                        "hook": "势力：Archive Guild demands a memory tariff",
                        "beats": ["地点：North Tower rings"],
                    },
                    metadata=metadata,
                    references=[storage.read_asset(character).id],
                ),
            )
            draft = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Clock draft",
                    content={"chapter": 1, "text": "钟城行者 follows the Archive Guild into North Tower and raises the Memory Key."},
                    metadata=metadata,
                    references=[storage.read_asset(character).id],
                ),
            )
            storage.write_asset(
                "continuity",
                ContinuityBible(
                    title="Clock City Continuity",
                    content={
                        "project_id": project_id,
                        "worldview_rules": ["Memory cannot be restored without equivalent cost"],
                        "timeline": [{"chapter": 1, "event": "林乔 enters North Tower"}],
                        "entities": [{"name": "Memory Key", "type": "prop"}],
                        "open_threads": ["Who built the first bell"],
                        "constraints": ["Do not let bells restore memory for free"],
                    },
                    metadata=metadata,
                    references=[storage.read_asset(character).id],
                ),
            )
            storage.write_asset(
                "continuity",
                ForeshadowingThread(
                    title="First bell mystery",
                    content={"thread_id": "first_bell", "setup": "silent bell", "payoff_plan": "founder reveal", "status": "planned", "related_chapters": [1, 8]},
                    metadata=metadata,
                ),
            )
            storage.write_asset(
                "continuity",
                PowerScaleRule(
                    title="Bell power scale",
                    content={"scale_id": "bell_power", "levels": ["spark", "hour", "epoch"], "constraints": ["epoch toll requires sacrifice"], "violation_checks": ["free epoch toll"]},
                    metadata=metadata,
                ),
            )
            storage.write_asset(
                "quality_standards",
                ReviewRulePack(
                    title="Clock review rules",
                    content={"rule_pack_id": "review_clock", "name": "Clock review", "dimensions": {"continuity": {"threshold": 85}}, "checks": ["memory cost visible"], "severity_policy": {"blocker": "must_fix"}},
                    metadata=metadata,
                ),
            )
            storage.write_asset(
                "templates",
                WritingTemplate(
                    title="Clock hook template",
                    content={"template_id": "clock_hook", "name": "Clock hook", "template_kind": "chapter_hook", "structure": ["bell", "choice", "cost"], "usage_constraints": ["respect canon"]},
                    metadata=metadata,
                ),
            )

            kg = build_novel_kg(storage, project_id=project_id, workspace_path=workspace_path)

            self.assertEqual(kg["ontology_version"], "novel-kg-0.2.0")
            self.assertEqual(kg["ontology_schema"]["schema_version"], "2026-06-kg-typed-v1")
            self.assertGreaterEqual(kg["summary"]["counts"]["entities"], 2)
            self.assertGreaterEqual(kg["summary"]["counts"]["relations"], 1)
            self.assertIn("semantic", kg["summary"])
            self.assertGreaterEqual(kg["summary"]["semantic"]["entity_count"], 1)
            self.assertIn("Archive Guild", {row["name"] for row in kg["factions"]})
            self.assertIn("North Tower", {row["name"] for row in kg["locations"]})
            self.assertIn("Memory Key", {row["name"] for row in kg["props"]})
            character_nodes = [row for row in kg["entities"] if row["name"] == "林乔"]
            self.assertTrue(character_nodes)
            self.assertIn("钟城行者", character_nodes[0]["aliases"])
            self.assertTrue(character_nodes[0]["evidence_spans"])
            self.assertGreater(character_nodes[0]["confidence"], 0.8)
            self.assertTrue(any(row["relation_type"] == "affiliated_with" for row in kg["relations"]))
            self.assertTrue(any(row["relation_type"] == "located_at" for row in kg["relations"]))
            self.assertTrue(any(row["relation_type"] == "mentions" and row["evidence_spans"] for row in kg["relations"]))
            self.assertTrue(any(row["name"] == "first_bell" for row in kg["foreshadowing"]))
            self.assertTrue(any(row["name"] == "bell_power" for row in kg["power_scales"]))
            self.assertTrue(any(row["name"] == "review_clock" for row in kg["review_rules"]))
            self.assertTrue(any(row["name"] == "clock_hook" for row in kg["templates"]))
            self.assertTrue(any(row.get("attributes", {}).get("semantic_projection") for row in kg["entities"]))

            snapshot = create_novel_kg_snapshot(storage, project_id=project_id, workspace_path=workspace_path)
            asset = storage.read_asset(snapshot["path"])
            self.assertEqual(asset.type, "novel_kg_snapshot")
            self.assertEqual(validate_common_fields(asset.to_dict()), [])

            query = query_novel_kg(storage, snapshot_path=snapshot["path"], kind="factions", q="Archive")
            self.assertEqual(query["count"], 1)
            self.assertEqual(query["items"][0]["name"], "Archive Guild")

            path_query = query_novel_kg_paths(storage, snapshot_path=snapshot["path"], source="林乔", target="Archive Guild")
            self.assertGreaterEqual(path_query["count"], 1)
            impact = query_novel_kg_impact(storage, snapshot_path=snapshot["path"], node="林乔", max_depth=2)
            self.assertGreaterEqual(impact["count"], 1)
            conflicts = analyze_novel_kg_conflicts(storage, snapshot_path=snapshot["path"])
            self.assertIn(conflicts["recommendation"], {"pass", "review", "block"})
            cypher = build_novel_kg_cypher(q="Archive", kind="faction")
            self.assertIn("MATCH", cypher["cypher"])
            kg_context = build_novel_kg_context(storage, target_path=draft, query="Archive Guild Memory Key", project_id=project_id, workspace_path=workspace_path)
            self.assertGreaterEqual(len(kg_context["items"]), 1)
            gate = evaluate_novel_kg_gate(storage, target_path=draft, project_id=project_id, workspace_path=workspace_path)
            self.assertIn(gate["status"], {"passed", "passed_with_warnings", "blocked"})
            self.assertIn("semantic_review", gate)
            self.assertIn("chapter_pleasure_toxicity", gate["semantic_review"])
            dirty = novel_kg_dirty_status(storage, project_id=project_id, workspace_path=workspace_path)
            self.assertTrue(dirty["dirty"])
            refresh = refresh_novel_kg(storage, project_id=project_id, workspace_path=workspace_path, changed_asset_path=draft, apply_invalidation=False)
            self.assertTrue(refresh["snapshot"]["path"])
            self.assertFalse(novel_kg_dirty_status(storage, project_id=project_id, workspace_path=workspace_path)["dirty"])


if __name__ == "__main__":
    unittest.main()
