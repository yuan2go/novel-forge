from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


class ProductApiRouterTests(unittest.TestCase):
    def test_product_routers_register_paths_and_openapi(self):
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:
            self.skipTest("FastAPI test client is not installed")

        from novel_forge.api.app import create_app
        from novel_forge.infrastructure.settings import IndustrialSettings

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(IndustrialSettings(root=Path(tmp).resolve()))
            paths = app.openapi().get("paths", {})

            expected = {
                "/product/projects",
                "/product/tasks",
                "/product/tasks/timeline",
                "/product/assets/detail",
                "/product/libraries/creative",
                "/product/libraries/creative/{library_key}",
                "/product/creative-assets",
                "/product/analysis/reports",
                "/product/analysis/run",
                "/product/analysis/convert",
                "/product/analysis/handoff",
                "/product/handoffs",
                "/product/batch/deconstruct",
                "/product/drafts",
                "/product/reviews/run",
                "/product/audits/chapter",
                "/product/audits/originality",
                "/product/publishing/gate",
                "/product/publishing/release-package",
                "/product/system/health",
                "/product/qdrant/search",
                "/product/minio/objects",
            }
            self.assertTrue(expected.issubset(set(paths)))

            client = TestClient(app)
            self.assertEqual(client.get("/product/projects").status_code, 200)
            self.assertEqual(client.get("/product/tasks").status_code, 200)
            self.assertEqual(client.get("/product/system/health").status_code, 200)
            self.assertEqual(client.get("/product/libraries/creative").status_code, 200)
            schema = client.get("/product/libraries/creative/schema")
            self.assertEqual(schema.status_code, 200, schema.text)
            self.assertIn("asset_collection", schema.json()["asset_types"])

            created = client.post(
                "/product/creative-assets",
                json={"asset_type": "platform_profile", "title": "Local Platform", "scope": "global"},
            )
            self.assertEqual(created.status_code, 200, created.text)
            rows = client.get("/product/libraries/creative/topic_library").json()
            self.assertEqual(rows[0]["type"], "platform_profile")

            project = client.post("/product/projects", json={"title": "Bound Project"})
            self.assertEqual(project.status_code, 200, project.text)
            config = project.json()["project_config"]
            for key in [
                "platform_profile_path",
                "genre_market_profile_path",
                "quality_standard_profile_path",
                "style_profile_path",
                "continuity_bible_path",
            ]:
                self.assertTrue(config[key], key)
            self.assertEqual(client.post("/product/styles/decompose", json={"source_path": config["style_profile_path"]}).status_code, 200)
            self.assertEqual(client.get("/product/styles/trend").status_code, 200)

            from novel_forge.schemas import DraftChapter, SourceDocument
            from novel_forge.storage.local import LocalStorage

            storage = LocalStorage(tmp)
            source_path = storage.write_asset(
                "raw",
                SourceDocument(
                    title="Analysis Fixture Source",
                    source="fixture.txt",
                    content={"text": "第一章 秘密出现，主角选择承担代价。第二章 危机升级，新的钩子打开。"},
                    metadata={
                        "project_id": project.json()["project_id"],
                        "workspace_path": project.json()["path"],
                        "rights": {
                            "authorization": "test_fixture",
                            "copyright_boundary": "API route test fixture",
                            "allow_downstream_generation": True,
                        },
                    },
                ),
            )
            source_ref = str(source_path.relative_to(storage.root))
            analysis = client.post(
                "/product/analysis/run",
                json={"source_path": source_ref, "analysis_type": "web_fiction_business", "workspace_path": project.json()["path"]},
            )
            self.assertEqual(analysis.status_code, 200, analysis.text)
            conversion = client.post(
                "/product/analysis/convert",
                json={"report_path": analysis.json()["path"], "targets": ["writing_template"], "workspace_path": project.json()["path"]},
            )
            self.assertEqual(conversion.status_code, 200, conversion.text)
            analysis_handoff = client.post(
                "/product/analysis/handoff",
                json={"input_path": source_ref, "analysis_type": "published_fiction", "workspace_path": project.json()["path"]},
            )
            self.assertEqual(analysis_handoff.status_code, 200, analysis_handoff.text)

            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Publish Gate Draft",
                    source="fixture",
                    tags=["draft"],
                    content={
                        "chapter": 1,
                        "text": "雨夜里，林乔选择公开线索，代价是钟楼第二次响起。",
                        "copyright_boundary": "test fixture original draft",
                    },
                    metadata={"project_id": project.json()["project_id"], "workspace_path": project.json()["path"]},
                ),
            )
            draft_ref = str(draft_path.relative_to(storage.root))
            originality = client.post("/product/audits/originality", json={"draft_path": draft_ref, "workspace_path": project.json()["path"]})
            self.assertEqual(originality.status_code, 200, originality.text)
            audit = client.post("/product/audits/chapter", json={"draft_path": draft_ref, "workspace_path": project.json()["path"]})
            self.assertEqual(audit.status_code, 200, audit.text)
            gate = client.post("/product/publishing/gate", json={"draft_path": draft_ref, "workspace_path": project.json()["path"]})
            self.assertEqual(gate.status_code, 200, gate.text)
            package = client.post("/product/publishing/release-package", json={"draft_path": draft_ref, "workspace_path": project.json()["path"]})
            self.assertEqual(package.status_code, 200, package.text)


if __name__ == "__main__":
    unittest.main()
