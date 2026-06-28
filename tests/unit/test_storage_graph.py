from __future__ import annotations

import unittest

from novel_forge.storage.graph import Neo4jGraphStore


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def run(self, query: str, **params):
        self.calls.append((query, params))


class _FakeDriver:
    def __init__(self) -> None:
        self.session_obj = _FakeSession()

    def session(self):
        return self.session_obj


class Neo4jGraphStoreTests(unittest.TestCase):
    def test_sync_novel_kg_projects_nodes_and_relations(self):
        driver = _FakeDriver()
        store = Neo4jGraphStore.__new__(Neo4jGraphStore)
        store.driver = driver
        graph = {
            "kg_id": "kg_1",
            "ontology_version": "novel-kg-0.1.0",
            "project_id": "project_1",
            "entities": [{"id": "e_1", "kind": "entity", "entity_type": "character", "name": "Lin", "attributes": {"role": "lead"}}],
            "relations": [{"id": "r_1", "relation_type": "mentions", "source": "e_1", "target": "event_1", "attributes": {"weight": 1}}],
            "events": [{"id": "event_1", "kind": "event", "entity_type": "chapter", "name": "arrival"}],
            "rules": [],
            "timelines": [],
            "foreshadowing": [],
            "factions": [],
            "locations": [],
            "props": [],
            "power_scales": [],
            "review_rules": [],
            "templates": [],
        }

        result = store.sync_novel_kg(graph)

        self.assertEqual(result, {"nodes": 2, "relations": 1})
        queries = [query for query, _params in driver.session_obj.calls]
        self.assertTrue(any("NFNovelKGNode" in query for query in queries))
        self.assertTrue(any("NF_KG_RELATION" in query for query in queries))
        relation_params = driver.session_obj.calls[-1][1]
        self.assertEqual(relation_params["source"], "e_1")
        self.assertEqual(relation_params["target"], "event_1")


if __name__ == "__main__":
    unittest.main()
