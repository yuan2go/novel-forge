from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.schemas import CharacterCard, ChapterPlan, ProjectWorkspaceState, SourceDocument, WorldBible
from novel_forge.storage.asset_manifest import rebuild_asset_manifest, manifest_counts
from novel_forge.storage.local import LocalStorage
from novel_forge.storage.retrieval_index import build_retrieval_index
from novel_forge.storage.search import search_assets
from novel_forge.storage.rag_context import build_rag_context
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

    def test_asset_overwrite_creates_backup_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            asset = SourceDocument(
                id="source_document_fixed",
                title="A",
                source="a.txt",
                content={"text": "first"},
                metadata={
                    "rights": {
                        "authorization": "test_fixture",
                        "copyright_boundary": "test fixture",
                        "allow_downstream_generation": True,
                    }
                },
            )

            storage.write_asset("raw", asset)
            asset.content = {"text": "second"}
            storage.write_asset("raw", asset)

            backups = list((storage.data_root / "backups").rglob("source_document_fixed*.json"))
            self.assertEqual(len(backups), 1)
            manifest = rebuild_asset_manifest(storage)
            self.assertTrue(manifest.exists())
            self.assertEqual(manifest_counts(storage)["raw"], 1)

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
            self.assertEqual(index_data["retrieval"]["ranker"], "hybrid-hash-vector-bm25")

            results = vector_search_assets(storage, query="hidden bell", category="raw")

            self.assertEqual(results[0]["title"], "Bell clue source")
            self.assertIn("score", results[0])
            self.assertEqual(results[0]["ranker"], "hybrid-hash-vector-bm25")
            self.assertIn("lexical_score", results[0])

    def test_vector_search_uses_cjk_tokens_and_hybrid_lexical_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            storage.write_asset(
                "raw",
                SourceDocument(
                    title="钟声线索",
                    source="a.txt",
                    tags=["source", "suspense"],
                    content={"text": "旧钟楼的钟声线索推动主角选择。"},
                ),
            )
            storage.write_asset(
                "raw",
                SourceDocument(
                    title="都市关系",
                    source="b.txt",
                    tags=["source", "romance"],
                    content={"text": "人物关系变化和约定。"},
                ),
            )

            build_vector_index(storage)
            results = vector_search_assets(storage, query="线索 钟声", category="raw")

            self.assertEqual(results[0]["title"], "钟声线索")
            self.assertGreater(results[0]["lexical_score"], 0)

    def test_rag_context_builder_filters_by_project_scope_and_asset_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = storage.write_asset(
                "workspaces",
                ProjectWorkspaceState(
                    title="Project One",
                    content={
                        "project_id": "project-one",
                        "memory": {"summary": "钟声和旧城案件"},
                        "chapter_states": [{"chapter": 1, "summary": "钟声伏笔尚未回收"}],
                        "continuity_threads": ["旧钟楼伏笔"],
                        "open_issues": [],
                    },
                ),
            )
            workspace_rel = str(workspace.relative_to(storage.root))
            storage.write_asset(
                "characters",
                CharacterCard(
                    title="林乔",
                    content={
                        "role": "protagonist",
                        "external_goal": "追查钟声线索",
                        "internal_need": "接受父亲旧案的真相",
                        "motivation_chain": ["责任", "代价", "选择"],
                    },
                    metadata={"project_id": "project-one", "workspace_path": workspace_rel},
                ),
            )
            storage.write_asset(
                "characters",
                CharacterCard(
                    title="Other Project Lead",
                    content={
                        "role": "protagonist",
                        "external_goal": "unrelated romance promise",
                        "internal_need": "trust",
                        "motivation_chain": ["promise"],
                    },
                    metadata={"project_id": "project-two", "workspace_path": "data/workspaces/other.json"},
                ),
            )
            storage.write_asset(
                "worlds",
                WorldBible(
                    title="旧城世界观",
                    content={
                        "setting": "旧钟楼城区",
                        "rules": ["钟声对应未结案件"],
                        "conflict_system": "制度压力与私人追查互相冲突",
                    },
                    metadata={"project_id": "project-one", "workspace_path": workspace_rel},
                ),
            )
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(
                    title="第一章计划",
                    content={
                        "chapter": 1,
                        "objective": "让主角发现钟声线索",
                        "beats": ["进入旧钟楼", "发现巡检号"],
                        "hook": "另一端传来第二声钟",
                    },
                    metadata={"project_id": "project-one", "workspace_path": workspace_rel},
                    references=["project-one", workspace_rel],
                ),
            )
            plan = storage.read_asset(plan_path)

            context = build_rag_context(storage, plan, input_path=plan_path, query="钟声 旧钟楼 主角", top_k=6)

            titles = {item["title"] for item in context["items"]}
            self.assertIn("林乔", titles)
            self.assertIn("旧城世界观", titles)
            self.assertNotIn("Other Project Lead", titles)
            self.assertTrue(context["buckets"]["characters"])
            self.assertTrue(context["buckets"]["worldbuilding"])
            self.assertEqual(context["project_id"], "project-one")
            self.assertEqual(context["requested_backend"], "auto")
            self.assertIn(context["retrieval_backend"], {"local", "scan"})

    def test_rag_context_builder_uses_qdrant_when_auto_backend_is_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            char_path = storage.write_asset(
                "characters",
                CharacterCard(
                    title="Qdrant lead",
                    content={
                        "role": "protagonist",
                        "external_goal": "追查向量线索",
                        "internal_need": "建立信任",
                        "motivation_chain": ["线索"],
                    },
                ),
            )
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(
                    title="向量计划",
                    content={"chapter": 1, "objective": "use qdrant", "beats": ["query"], "hook": "vector hook"},
                ),
            )
            plan = storage.read_asset(plan_path)
            qdrant_rows = [
                {
                    "path": str(char_path.relative_to(storage.root)),
                    "score": 0.91,
                    "ranker": "qdrant-vector",
                }
            ]

            with patch("novel_forge.storage.rag_context.embedding_provider_health", return_value={"ok": True}), patch(
                "novel_forge.storage.rag_context.qdrant_search_assets",
                return_value=qdrant_rows,
            ):
                context = build_rag_context(storage, plan, input_path=plan_path, query="vector", top_k=1, backend="auto")

            self.assertEqual(context["retrieval_backend"], "qdrant")
            self.assertEqual(context["items"][0]["title"], "Qdrant lead")
            self.assertEqual(context["items"][0]["ranker"], "qdrant-vector")


if __name__ == "__main__":
    unittest.main()
