from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


class MkaosGraphExplorerTests(MkaosP1TestCase):
    def test_graph_explorer_returns_clusters_layout_and_path_frames_without_source_text(self):
        seeded = self.seed_knowledge_system()
        mkaos.create_knowledge_relation(
            self.storage,
            {
                "project_id": self.project_id,
                "source_knowledge_id": seeded["history"]["asset"]["id"],
                "target_knowledge_id": seeded["mystery"]["asset"]["id"],
                "relation_type": "supports",
                "confidence": 0.8,
            },
        )

        report = mkaos.build_knowledge_graph_explorer(
            self.storage,
            {"project_id": self.project_id, "persist": True, "max_nodes": 40, "max_frames": 12},
        )["data"]

        self.assertEqual(report["version"], "mkaos-graph-explorer-v2")
        self.assertTrue(report["clusters"])
        self.assertTrue(report["layout"]["positions"])
        self.assertTrue(report["path_animation_frames"])
        self.assertFalse(report["source_isolation"]["raw_text_included"])
        serialized = str(report)
        self.assertNotIn("历史制度会改变资源分配", serialized)
        self.assertLessEqual(report["large_graph_policy"]["sampled_nodes"], 40)
