from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


class MkaosKnowledgeGraphV1Tests(MkaosP1TestCase):
    def test_graph_relation_paths_snapshot_and_no_source_leakage(self):
        seeded = self.seed_knowledge_system()
        relation = mkaos.create_knowledge_relation(
            self.storage,
            {
                "project_id": self.project_id,
                "source_knowledge_id": seeded["history"]["asset"]["id"],
                "target_knowledge_id": seeded["mystery"]["asset"]["id"],
                "relation_type": "supports",
                "explanation": "制度压力可以生成证据线索。",
            },
        )
        graph = mkaos.build_knowledge_graph(self.storage, {"project_id": self.project_id, "persist": True})
        data = graph["data"]
        self.assertTrue(data["asset_id"])
        self.assertIn(relation["asset"]["id"], str(data["edges"]))
        self.assertNotIn("raw_text", str(data["nodes"]))
        paths = mkaos.query_knowledge_graph_paths(
            self.storage,
            {"project_id": self.project_id, "source": seeded["history"]["asset"]["id"], "target": seeded["mystery"]["asset"]["id"]},
        )
        self.assertGreaterEqual(paths["data"]["path_count"], 1)

    def test_contradicts_returns_conflict_edge(self):
        seeded = self.seed_knowledge_system()
        mkaos.create_knowledge_relation(
            self.storage,
            {
                "project_id": self.project_id,
                "source_knowledge_id": seeded["history"]["asset"]["id"],
                "target_knowledge_id": seeded["mystery"]["asset"]["id"],
                "relation_type": "contradicts",
            },
        )
        graph = mkaos.build_knowledge_graph(self.storage, {"project_id": self.project_id})
        self.assertIn("contradicts", {edge["relation"] for edge in graph["data"]["edges"]})
