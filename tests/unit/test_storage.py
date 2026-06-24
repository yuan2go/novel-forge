from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.schemas import SourceDocument
from novel_forge.storage.local import LocalStorage
from novel_forge.storage.retrieval_index import build_retrieval_index
from novel_forge.storage.search import search_assets
from novel_forge.storage.vector_index import build_vector_index, vector_search_assets


class StorageTests(unittest.TestCase):
    def test_write_and_read_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            path = storage.write_asset("raw", SourceDocument(title="A", source="a.txt", content={"text": "x"}))
            loaded = storage.read_asset(path)
            self.assertEqual(loaded.type, "source_document")
            self.assertEqual(storage.counts()["raw"], 1)

    def test_search_assets_filters_by_type_tag_keyword_and_category(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            storage.write_asset(
                "raw",
                SourceDocument(
                    title="Suspense source",
                    source="a.txt",
                    tags=["source", "suspense"],
                    content={"text": "hidden clue"},
                ),
            )
            storage.write_asset(
                "raw",
                SourceDocument(
                    title="Romance source",
                    source="b.txt",
                    tags=["source", "romance"],
                    content={"text": "relationship"},
                ),
            )

            results = search_assets(
                storage,
                category="raw",
                asset_type="source_document",
                tags=["suspense"],
                keyword="hidden",
            )

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["title"], "Suspense source")
            self.assertEqual(results[0]["category"], "raw")

    def test_retrieval_index_builds_and_auto_refreshes_for_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            storage.write_asset(
                "raw",
                SourceDocument(
                    title="Indexed suspense source",
                    source="a.txt",
                    tags=["source", "suspense"],
                    content={"text": "hidden bell clue"},
                ),
            )

            index_path = build_retrieval_index(storage)
            self.assertTrue(index_path.exists())
            index_data = storage.read_json(index_path)
            self.assertEqual(index_data["asset_count"], 1)

            indexed_results = search_assets(storage, category="raw", tags=["suspense"], keyword="bell")
            self.assertEqual(len(indexed_results), 1)
            self.assertEqual(indexed_results[0]["title"], "Indexed suspense source")

            storage.write_asset(
                "raw",
                SourceDocument(
                    title="Fresh indexed source",
                    source="b.txt",
                    tags=["source", "feedback"],
                    content={"text": "fresh reader signal"},
                ),
            )
            refreshed_results = search_assets(storage, category="raw", tags=["feedback"], keyword="fresh")
            refreshed_index = storage.read_json(index_path)

            self.assertEqual(len(refreshed_results), 1)
            self.assertEqual(refreshed_results[0]["title"], "Fresh indexed source")
            self.assertEqual(refreshed_index["asset_count"], 2)

    def test_relevance_rank_boosts_title_and_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            storage.write_asset(
                "raw",
                SourceDocument(
                    title="Generic source",
                    source="a.txt",
                    tags=["source"],
                    content={"text": "hook hook hook"},
                ),
            )
            storage.write_asset(
                "raw",
                SourceDocument(
                    title="Hook craft note",
                    source="b.txt",
                    tags=["source", "hook"],
                    content={"text": "single mention"},
                ),
            )

            results = search_assets(storage, category="raw", keyword="hook", rank="relevance")

            self.assertEqual(results[0]["title"], "Hook craft note")
            self.assertIn("score", results[0])
            self.assertEqual(results[0]["ranker"], "field-weighted-token")

    def test_vector_index_builds_and_ranks_by_hash_embedding_similarity(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            storage.write_asset(
                "raw",
                SourceDocument(
                    title="Bell clue source",
                    source="a.txt",
                    tags=["source", "suspense"],
                    content={"text": "hidden bell clue"},
                ),
            )
            storage.write_asset(
                "raw",
                SourceDocument(
                    title="Romance source",
                    source="b.txt",
                    tags=["source", "romance"],
                    content={"text": "relationship promise"},
                ),
            )

            index_path = build_vector_index(storage)
            self.assertTrue(index_path.exists())
            index_data = storage.read_json(index_path)
            self.assertEqual(index_data["asset_count"], 2)
            self.assertEqual(index_data["metadata"]["kind"], "local_vector_index")

            results = vector_search_assets(storage, query="hidden bell", category="raw")

            self.assertEqual(results[0]["title"], "Bell clue source")
            self.assertIn("score", results[0])
            self.assertEqual(results[0]["ranker"], "hash-vector")


if __name__ == "__main__":
    unittest.main()
