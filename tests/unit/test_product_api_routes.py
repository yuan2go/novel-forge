from pathlib import Path
import os
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


class ProductApiRouterTests(unittest.TestCase):
    def setUp(self):
        self._previous_model_provider = os.environ.get("NOVEL_FORGE_MODEL_PROVIDER")
        os.environ["NOVEL_FORGE_MODEL_PROVIDER"] = "mock"

    def tearDown(self):
        if self._previous_model_provider is None:
            os.environ.pop("NOVEL_FORGE_MODEL_PROVIDER", None)
        else:
            os.environ["NOVEL_FORGE_MODEL_PROVIDER"] = self._previous_model_provider

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
                "/product/projects/operating-dashboard",
                "/product/tasks",
                "/product/tasks/timeline",
                "/product/workflow/node-runs",
                "/product/workflow/definitions",
                "/product/workflow/nodes",
                "/product/workflow/execute",
                "/product/workflow/resume",
                "/product/workflow/runtime-console",
                "/product/workflow/ready-queue",
                "/product/workflow/processor-contracts",
                "/product/workflow/scheduler/tick",
                "/product/agents/runs",
                "/product/agents/events",
                "/product/agents/contracts",
                "/product/agents/boundary-audit",
                "/product/agents/sla",
                "/product/agents/rollback",
                "/product/agents/executor/run-once",
                "/product/agents/scheduler/status",
                "/product/agents/scheduler/queue",
                "/product/agents/scheduler/tick",
                "/product/agents/dispatch",
                "/product/agents/recover",
                "/product/agents/operation-contracts",
                "/product/assets/detail",
                "/product/manuscript/workbench",
                "/product/libraries/creative",
                "/product/libraries/creative/{library_key}",
                "/product/creative-assets",
                "/product/analysis/reports",
                "/product/analysis/run",
                "/product/analysis/convert",
                "/product/analysis/handoff",
                "/product/context/assets",
                "/product/context/build-plan",
                "/product/context/bundle",
                "/product/context/diff",
                "/product/continuity/graph",
                "/product/continuity/graph-snapshot",
                "/product/continuity/canon-snapshot",
                "/product/continuity/chapter-report",
                "/product/continuity/canon-patch",
                "/product/continuity/canon-patch/apply",
                "/product/novel-kg/graph",
                "/product/novel-kg/snapshot",
                "/product/novel-kg/query",
                "/product/novel-kg/paths",
                "/product/novel-kg/impact",
                "/product/novel-kg/conflicts",
                "/product/novel-kg/cypher",
                "/product/novel-kg/context",
                "/product/novel-kg/gate",
                "/product/novel-kg/semantic-extraction",
                "/product/novel-kg/dirty",
                "/product/novel-kg/refresh",
                "/product/editor/artifacts",
                "/product/editor/patch",
                "/product/editor/apply",
                "/product/editor/diff-report",
                "/product/evaluation/assets",
                "/product/evaluation/model-profile",
                "/product/evaluation/benchmark-task",
                "/product/evaluation/benchmark-from-generation-run",
                "/product/evaluation/benchmark-run",
                "/product/evaluation/benchmark-batch",
                "/product/evaluation/compare",
                "/product/evaluation/routing-policy",
                "/product/evaluation/route",
                "/product/evaluation/prompt-version",
                "/product/evaluation/prompt-regression",
                "/product/feedback/assets",
                "/product/feedback/import-batch",
                "/product/feedback/sentiment-report",
                "/product/feedback/operational-snapshot",
                "/product/feedback/insight",
                "/product/feedback/apply-strategy",
                "/product/feedback/backflow-plan",
                "/product/feedback/backflow-apply",
                "/product/metrics/snapshots",
                "/product/metrics/snapshot",
                "/product/runtime/trace-timeline",
                "/product/runtime/cost-ledger",
                "/product/runtime/cost-dashboard",
                "/product/runtime/cost-snapshot",
                "/product/runtime/policy/status",
                "/product/runtime/policy/enforcement-report",
                "/product/runtime/policy/check",
                "/product/runtime/rollback/verify",
                "/product/settings/assets",
                "/product/settings/profile",
                "/product/production/versions",
                "/product/production/macro-plans",
                "/product/production/macro-plan",
                "/product/production/chapter-runs",
                "/product/production/chapter-run",
                "/product/production/chapter-run/start",
                "/product/production/chapter-run/resume",
                "/product/production/chapter-run/pause",
                "/product/production/chapter-run/cancel",
                "/product/production/chapter-run/recover",
                "/product/production/invalidate-downstream",
                "/product/production/outline-version",
                "/product/production/chapter-plan-version",
                "/product/production/draft-version",
                "/product/production/generation-run",
                "/product/impact/reports",
                "/product/impact/report",
                "/product/handoffs",
                "/product/batch/deconstruct",
                "/product/drafts",
                "/product/reviews/run",
                "/product/revisions/rework-loop",
                "/product/audits/chapter",
                "/product/audits/originality",
                "/product/publishing/gate",
                "/product/publishing/release-package",
                "/product/publishing/assets",
                "/product/publishing/plan",
                "/product/publishing/log",
                "/product/publishing/adapters",
                "/product/publishing/adapter-release",
                "/product/system/health",
                "/product/system/module-completion",
                "/product/system/module-completion/snapshot",
                "/product/system/operation-reports",
                "/product/system/failure-drill",
                "/product/system/long-chain-acceptance",
                "/product/qdrant/search",
                "/product/minio/objects",
            }
            self.assertTrue(expected.issubset(set(paths)))

            client = TestClient(app)
            self.assertEqual(client.get("/product/projects").status_code, 200)
            self.assertEqual(client.get("/product/tasks").status_code, 200)
            self.assertEqual(client.get("/product/system/health").status_code, 200)
            completion = client.get("/product/system/module-completion")
            self.assertEqual(completion.status_code, 200, completion.text)
            self.assertGreaterEqual(completion.json()["summary"]["module_count"], 8)
            self.assertEqual(client.get("/product/libraries/creative").status_code, 200)
            self.assertEqual(client.get("/product/feedback/assets").status_code, 200)
            self.assertEqual(client.get("/product/metrics/snapshots").status_code, 200)
            self.assertEqual(client.get("/product/settings/assets").status_code, 200)
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
            settings_profile = client.post("/product/settings/profile", json={"workspace_path": project.json()["path"]})
            self.assertEqual(settings_profile.status_code, 200, settings_profile.text)
            metric_snapshot = client.post(
                "/product/metrics/snapshot",
                json={"project_id": project.json()["project_id"], "workspace_path": project.json()["path"]},
            )
            self.assertEqual(metric_snapshot.status_code, 200, metric_snapshot.text)
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

            from novel_forge.schemas import ChapterPlan, DraftChapter, Outline, SourceDocument
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

            outline_path = storage.write_asset(
                "outlines",
                Outline(
                    title="API Outline",
                    content={"acts": [{"act": 1, "goal": "open mystery"}]},
                    metadata={"project_id": project.json()["project_id"], "workspace_path": project.json()["path"]},
                ),
            )
            chapter_plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(
                    title="API Chapter Plan",
                    source=storage.read_asset(outline_path).id,
                    content={
                        "chapter": 1,
                        "objective": "open clock mystery",
                        "beats": ["rain", "archive mismatch"],
                        "hook": "next bell rings",
                    },
                    metadata={"project_id": project.json()["project_id"], "workspace_path": project.json()["path"]},
                    references=[storage.read_asset(outline_path).id],
                ),
            )
            chapter_plan_ref = str(chapter_plan_path.relative_to(storage.root))
            context_plan = client.post(
                "/product/context/build-plan",
                json={"target_path": chapter_plan_ref, "query": "clock mystery", "workspace_path": project.json()["path"]},
            )
            self.assertEqual(context_plan.status_code, 200, context_plan.text)
            context_bundle = client.post("/product/context/bundle", json={"build_plan_path": context_plan.json()["path"]})
            self.assertEqual(context_bundle.status_code, 200, context_bundle.text)
            context_bundle_2 = client.post(
                "/product/context/bundle",
                json={"build_plan_path": context_plan.json()["path"], "final_confirmed": True},
            )
            self.assertEqual(context_bundle_2.status_code, 200, context_bundle_2.text)
            context_diff = client.post(
                "/product/context/diff",
                json={"left_path": context_bundle.json()["path"], "right_path": context_bundle_2.json()["path"]},
            )
            self.assertEqual(context_diff.status_code, 200, context_diff.text)
            self.assertEqual(client.get(f"/product/context/assets?project_id={project.json()['project_id']}").status_code, 200)
            outline_version = client.post("/product/production/outline-version", json={"outline_path": str(outline_path.relative_to(storage.root))})
            self.assertEqual(outline_version.status_code, 200, outline_version.text)
            chapter_plan_version = client.post("/product/production/chapter-plan-version", json={"chapter_plan_path": chapter_plan_ref})
            self.assertEqual(chapter_plan_version.status_code, 200, chapter_plan_version.text)
            chapter_run = client.post(
                "/product/production/chapter-run/start",
                json={
                    "outline_path": str(outline_path.relative_to(storage.root)),
                    "chapter_plan_path": chapter_plan_ref,
                    "workspace_path": project.json()["path"],
                    "chapter": 1,
                    "run_to": "context_bundle",
                },
            )
            self.assertEqual(chapter_run.status_code, 200, chapter_run.text)
            self.assertEqual(chapter_run.json()["status"], "succeeded")
            self.assertTrue(chapter_run.json()["outputs"]["context_bundle_path"])
            chapter_runs = client.get(f"/product/production/chapter-runs?project_id={project.json()['project_id']}")
            self.assertEqual(chapter_runs.status_code, 200, chapter_runs.text)
            self.assertGreaterEqual(len(chapter_runs.json()), 1)
            chapter_run_detail = client.get(f"/product/production/chapter-run?path={chapter_run.json()['path']}")
            self.assertEqual(chapter_run_detail.status_code, 200, chapter_run_detail.text)
            chapter_run_resume = client.post(
                "/product/production/chapter-run/resume",
                json={"run_path": chapter_run.json()["path"], "from_step": "context_bundle", "run_to": "context_bundle"},
            )
            self.assertEqual(chapter_run_resume.status_code, 200, chapter_run_resume.text)
            self.assertTrue(chapter_run_resume.json()["outputs"]["context_bundle_path"])

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
            draft_version = client.post("/product/production/draft-version", json={"draft_path": draft_ref})
            self.assertEqual(draft_version.status_code, 200, draft_version.text)
            generation_run = client.post(
                "/product/production/generation-run",
                json={"input_path": chapter_plan_ref, "context_bundle_path": context_bundle.json()["path"], "output_path": draft_ref},
            )
            self.assertEqual(generation_run.status_code, 200, generation_run.text)
            manuscript = client.get(
                f"/product/manuscript/workbench?project_id={project.json()['project_id']}&draft_path={draft_ref}"
            )
            self.assertEqual(manuscript.status_code, 200, manuscript.text)
            manuscript_json = manuscript.json()
            self.assertEqual(manuscript_json["selected_draft"]["path"], draft_ref)
            self.assertGreaterEqual(manuscript_json["trace_summary"]["generation_run_count"], 1)
            self.assertEqual(client.get(f"/product/production/versions?project_id={project.json()['project_id']}").status_code, 200)


if __name__ == "__main__":
    unittest.main()
