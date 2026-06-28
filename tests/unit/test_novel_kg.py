from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.novel_kg import build_novel_kg, create_novel_kg_snapshot, query_novel_kg
from novel_forge.schemas import (
    CharacterCard,
    ContinuityBible,
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

            self.assertEqual(kg["ontology_version"], "novel-kg-0.1.0")
            self.assertGreaterEqual(kg["summary"]["counts"]["entities"], 2)
            self.assertGreaterEqual(kg["summary"]["counts"]["relations"], 1)
            self.assertEqual({row["name"] for row in kg["factions"]}, {"Archive Guild"})
            self.assertEqual({row["name"] for row in kg["locations"]}, {"North Tower"})
            self.assertEqual({row["name"] for row in kg["props"]}, {"Memory Key"})
            self.assertTrue(any(row["relation_type"] == "affiliated_with" for row in kg["relations"]))
            self.assertTrue(any(row["relation_type"] == "located_at" for row in kg["relations"]))
            self.assertTrue(any(row["name"] == "first_bell" for row in kg["foreshadowing"]))
            self.assertTrue(any(row["name"] == "bell_power" for row in kg["power_scales"]))
            self.assertTrue(any(row["name"] == "review_clock" for row in kg["review_rules"]))
            self.assertTrue(any(row["name"] == "clock_hook" for row in kg["templates"]))

            snapshot = create_novel_kg_snapshot(storage, project_id=project_id, workspace_path=workspace_path)
            asset = storage.read_asset(snapshot["path"])
            self.assertEqual(asset.type, "novel_kg_snapshot")
            self.assertEqual(validate_common_fields(asset.to_dict()), [])

            query = query_novel_kg(storage, snapshot_path=snapshot["path"], kind="factions", q="Archive")
            self.assertEqual(query["count"], 1)
            self.assertEqual(query["items"][0]["name"], "Archive Guild")


if __name__ == "__main__":
    unittest.main()
