from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.model_adapters.mock import MockModelAdapter
from novel_forge.modules.characters import service as characters
from novel_forge.modules.topics import service as topics
from novel_forge.modules.worldbuilding import service as worlds
from novel_forge.schemas import MaterialCard
from novel_forge.storage.local import LocalStorage


class ProjectDrivenCreativeServicesTests(unittest.TestCase):
    def test_distinct_material_goals_produce_distinct_topic_world_and_character_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            first = _chain(storage, "魔法债务", "法术借贷会吞噬施法者寿命", "fantasy-project")
            second = _chain(storage, "深海救援", "氧气配额迫使救援队选择幸存者", "ocean-project")

            self.assertNotEqual(first["topic"].content["logline"], second["topic"].content["logline"])
            self.assertNotEqual(first["world"].content["setting"], second["world"].content["setting"])
            self.assertNotEqual(first["character"].content["external_goal"], second["character"].content["external_goal"])
            self.assertNotIn("Echo Clock", first["world"].title)
            self.assertNotIn("Lin Qiao", first["character"].title)
            self.assertEqual(first["character"].metadata["project_id"], "fantasy-project")
            self.assertEqual(second["character"].metadata["project_id"], "ocean-project")


def _chain(storage: LocalStorage, title: str, mechanism: str, project_id: str) -> dict:
    material_path = storage.write_asset(
        "materials",
        MaterialCard(title=title, tags=["original"], content={"usable_patterns": [mechanism]}, metadata={"project_id": project_id}),
    )
    topic_path = topics.develop_topic(storage, str(material_path), model=MockModelAdapter())
    world_path = worlds.generate_world(storage, str(topic_path))
    character_path = characters.generate_characters(storage, str(world_path))
    return {"topic": storage.read_asset(topic_path), "world": storage.read_asset(world_path), "character": storage.read_asset(character_path)}


if __name__ == "__main__":
    unittest.main()
