from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

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
                "/product/workflow/templates/v1-chapter-production",
                "/product/workflow/nodes",
                "/product/workflow/execute",
                "/product/workflow/resume",
                "/product/workflow/runtime-console",
                "/product/workflow/governance-drift",
                "/product/workflow/governance-drift-gate",
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
                "/product/agents/center",
                "/product/agent-registry/entries",
                "/product/agent-registry/sync-runtime-profiles",
                "/product/agent-registry/entry",
                "/product/agent-registry/entry/{agent_id}",
                "/product/agent-registry/version",
                "/product/agent-registry/lifecycle",
                "/product/agent-registry/capability",
                "/product/agent-registry/evaluation-binding",
                "/product/agent-registry/snapshot",
                "/product/agent-registry/resolve",
                "/product/agent-registry/coverage",
                "/product/editor-chief/snapshot",
                "/product/canon-graph/query",
                "/product/canon-graph/snapshot",
                "/product/canon-graph/reason",
                "/product/canon-graph/paths",
                "/product/canon-graph/check",
                "/product/canon-graph/plugin",
                "/product/canon-graph/issues",
                "/product/genre/catalog",
                "/product/genre/strategy-pack",
                "/product/genre/risk-gate",
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
                "/product/context/governance-runtime-coverage",
                "/product/context/governance-runtime-gate",
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
                "/product/novel-kg/identity-resolution",
                "/product/novel-kg/identity-resolution/adjudicate",
                "/product/novel-kg/dirty",
                "/product/novel-kg/refresh",
                "/product/longform-stability/dashboard",
                "/product/longform-stability/extract",
                "/product/longform-stability/acceptance",
                "/product/longform-stability/control-asset",
                "/product/longform-stability/calibrate",
                "/product/longform-stability/reader-promise-ledger",
                "/product/long-chain-proof/run",
                "/product/provider-proof/v7",
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
                "/product/evaluation/suites",
                "/product/evaluation/suite",
                "/product/evaluation/case",
                "/product/evaluation/human-annotation",
                "/product/evaluation/golden-set",
                "/product/evaluation/provider-calibration",
                "/product/evaluation/run-suite",
                "/product/evaluation/evaluate-asset",
                "/product/evaluation/evaluate-agent-run",
                "/product/evaluation/evaluate-workflow-run",
                "/product/evaluation/evaluate-context",
                "/product/evaluation/evaluate-longform",
                "/product/evaluation/evaluate-platform-fit",
                "/product/evaluation/evaluation-gate",
                "/product/evaluation/regression-report",
                "/product/evaluation/dashboard",
                "/product/quality/rubric-pack",
                "/product/quality/suite",
                "/product/quality/gate",
                "/product/quality/chapter-economy",
                "/product/quality/character-pressure",
                "/product/quality/mobile-reading",
                "/product/quality/provider-judge",
                "/product/style/health",
                "/product/style/sample",
                "/product/style/fingerprint",
                "/product/style/profile",
                "/product/style/drift-gate",
                "/product/feedback/assets",
                "/product/feedback/import-batch",
                "/product/feedback/sentiment-report",
                "/product/feedback/operational-snapshot",
                "/product/feedback/insight",
                "/product/feedback/apply-strategy",
                "/product/feedback/backflow-plan",
                "/product/feedback/backflow-apply",
                "/product/feedback/reader-simulation",
                "/product/feedback/real-backflow",
                "/product/metrics/snapshots",
                "/product/metrics/snapshot",
                "/product/runtime/trace-timeline",
                "/product/runtime/cost-ledger",
                "/product/runtime/cost-dashboard",
                "/product/runtime/cost-snapshot",
                "/product/runtime/policy/status",
                "/product/runtime/policy/enforcement-report",
                "/product/runtime/policy/legacy-entrypoint-audit",
                "/product/runtime/policy/surface-coverage",
                "/product/runtime/provider-hard-stop-evidence",
                "/product/runtime/policy/check",
                "/product/runtime/rollback/verify",
                "/product/runtime/rollback/coordinate",
                "/product/platform-strategy/assets",
                "/product/platform-strategy/defaults",
                "/product/platform-strategy/pack",
                "/product/platform-strategy/opening-gate",
                "/product/platform-strategy/chapter-gate",
                "/product/platform-strategy/retention-risk",
                "/product/platform-strategy/publish-adapter",
                "/product/platform-strategy/feedback-backflow",
                "/product/publishing-adapters/upload-package",
                "/product/publishing-adapters/receipt",
                "/product/publishing-adapters/receipt/parse",
                "/product/publishing-adapters/platform-gate",
                "/product/publishing-adapters/publish",
                "/product/feedback-adapters/metrics",
                "/product/feedback-adapters/comments/cluster",
                "/product/feedback-adapters/mutation-proposal",
                "/product/feedback-adapters/mutation-proposal/resolve",
                "/product/feedback-adapters/mutation-proposal/apply",
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
                "/product/provider-fallback/preview",
                "/product/provider-fallback/approve",
                "/product/provider-fallback/resolve",
                "/product/permission-center/snapshot",
                "/product/permission-center/approval-requests",
                "/product/permission-center/approval-request-caller-readiness",
                "/product/permission-center/approval-requests/expire",
                "/product/permission-center/approval-requests/{request_id}/resolve",
                "/product/impact/reports",
                "/product/impact/report",
                "/product/handoffs",
                "/product/batch/deconstruct",
                "/product/sources/policies",
                "/product/sources/github",
                "/product/sources/connectors",
                "/product/sources/policy",
                "/product/sources/license-check",
                "/product/sources/risk-report",
                "/product/sources/snapshot",
                "/product/sources/sync-job",
                "/product/sources/refresh-report",
                "/product/sources/connector-execution-plan",
                "/product/sources/connector-adapter-lifecycle",
                "/product/sources/connector-run",
                "/product/sources/diff-repair-plan",
                "/product/sources/diff-repair-apply",
                "/product/sources/diff-repair-rollback",
                "/product/sources/governance-apply",
                "/product/sources/governance-rollback",
                "/product/sources/stale-sweep",
                "/product/sources/retention-sweep",
                "/product/sources/guarded-apply-readiness",
                "/product/sources/context-eligibility",
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
                "/product/system/production-governance-drift",
                "/product/system/production-governance-drift-gate",
                "/product/system/operation-reports",
                "/product/system/failure-drill",
                "/product/system/long-chain-acceptance",
                "/product/qdrant/search",
                "/product/portfolio/project",
                "/product/portfolio/scores",
                "/product/portfolio/allocation-plan",
                "/product/portfolio/cross-book-similarity",
                "/product/portfolio/scheduler-plan",
                "/product/portfolio/lifecycle-gate",
                "/product/os/cockpit/project",
                "/product/os/cockpit/multi-book",
                "/product/os/cockpit/multi-book/schedule",
                "/product/os/retrieval/pgvector-capabilities",
                "/product/os/retrieval/pgvector-operations-plan",
                "/product/os/retrieval/pgvector-migrate",
                "/product/os/retrieval/pgvector-verify",
                "/product/os/retrieval/rebuild-dirty-index",
                "/product/os/retrieval/pgvector-qdrant-comparison",
                "/product/audit-log/events",
                "/product/audit-log/record",
                "/product/audit-log/trail",
                "/product/audit-log/trail-report",
                "/product/audit-log/export-package",
                "/product/analytics/capabilities",
                "/product/analytics/schema-plan",
                "/product/analytics/migrate",
                "/product/analytics/sync",
                "/product/analytics/quality-trends",
                "/product/analytics/agent-metrics",
                "/product/analytics/evaluation-metrics",
                "/product/analytics/cost-metrics",
                "/product/analytics/feedback-metrics",
                "/product/analytics/dashboard-snapshot",
                "/product/mkaos/model-extraction/jobs",
                "/product/mkaos/model-extraction/jobs/{job_id}",
                "/product/mkaos/model-extraction/jobs/{job_id}/run",
                "/product/mkaos/model-extraction/jobs/{job_id}/cancel",
                "/product/mkaos/model-extraction/candidates/{candidate_id}/approve",
                "/product/mkaos/model-extraction/candidates/{candidate_id}/reject",
                "/product/mkaos/model-extraction/review-queue",
                "/product/mkaos/model-extraction/benchmark/run",
                "/product/mkaos/model-extraction/regression/run",
                "/product/mkaos/model-extraction/prompts",
                "/product/mkaos/lifecycle/plan",
                "/product/mkaos/lifecycle/apply",
                "/product/mkaos/lifecycle/rollback",
                "/product/mkaos/selector-governance/refresh",
                "/product/mkaos/selector-governance/diff",
                "/product/mkaos/selector-governance/binding-proposal",
                "/product/mkaos/selector-governance/binding-apply",
                "/product/mkaos/selector-governance/binding-rollback",
                "/product/mkaos/production-gate/run",
                "/product/mkaos/production-gate/reports",
                "/product/mkaos/production-gate/latest",
                "/product/mkaos/production-gate/policy",
                "/product/mkaos/production-gate/coverage",
                "/product/mkaos/lineage/build-index",
                "/product/mkaos/lineage/index",
                "/product/mkaos/lineage/query-path",
                "/product/mkaos/lineage/diff",
                "/product/mkaos/lineage/export",
                "/product/mkaos/lineage/asset-impact",
                "/product/mkaos/lineage/issue-attribution",
                "/product/mkaos/lineage/feedback-attribution",
                "/product/mkaos/lineage/gate-attribution",
                "/product/mkaos/lineage/feedback-to-knowledge",
                "/product/mkaos/lineage/weight-governance",
                "/product/mkaos/lineage/reports",
                "/product/minio/objects",
            }
            self.assertTrue(expected.issubset(set(paths)))

            client = TestClient(app)
            self.assertEqual(client.get("/product/projects").status_code, 200)
            self.assertEqual(client.get("/product/tasks").status_code, 200)
            self.assertEqual(client.get("/product/system/health").status_code, 200)
            self.assertEqual(client.get("/product/system/production-governance-drift?persist=false").status_code, 200)
            self.assertEqual(client.post("/product/system/production-governance-drift-gate", json={"persist_report": False}).status_code, 200)
            self.assertEqual(client.get("/product/agents/center").status_code, 200)
            self.assertEqual(client.get("/product/editor-chief/snapshot").status_code, 200)
            self.assertEqual(client.get("/product/runtime/policy/surface-coverage").status_code, 200)
            self.assertEqual(client.get("/product/runtime/provider-hard-stop-evidence").status_code, 200)
            self.assertEqual(client.get("/product/permission-center/snapshot").status_code, 200)
            source_policy = client.post("/product/sources/policy", json={"source_ref": "route-owned-source", "risk_tier": "R1"})
            self.assertEqual(source_policy.status_code, 200, source_policy.text)
            self.assertEqual(source_policy.json()["asset"]["type"], "source_policy")
            source_risk = client.post("/product/sources/risk-report", json={"source_ref": "route-owned-source", "source_policy_path": source_policy.json()["path"]})
            self.assertEqual(source_risk.status_code, 200, source_risk.text)
            source_eligibility = client.post("/product/sources/context-eligibility", json={"source_ref": "route-owned-source", "risk_tier": "R1"})
            self.assertEqual(source_eligibility.status_code, 200, source_eligibility.text)
            self.assertTrue(source_eligibility.json()["generation_context_allowed"])
            source_refresh = client.post("/product/sources/refresh-report", json={"source_ref": "route-owned-source"})
            self.assertEqual(source_refresh.status_code, 200, source_refresh.text)
            self.assertEqual(source_refresh.json()["asset"]["type"], "source_refresh_report")
            self.assertFalse(source_refresh.json()["asset"]["content"]["connector_execution_allowed"])
            connector_plan = client.post("/product/sources/connector-execution-plan", json={"source_ref": "route-owned-source", "connector_id": "manual_metadata_connector"})
            self.assertEqual(connector_plan.status_code, 200, connector_plan.text)
            self.assertEqual(connector_plan.json()["sync_job"]["asset"]["type"], "source_sync_job")
            self.assertFalse(connector_plan.json()["execution_receipt"]["execution_performed"])
            connector_run = client.post("/product/sources/connector-run", json={"sync_job_path": connector_plan.json()["sync_job"]["path"]})
            self.assertEqual(connector_run.status_code, 200, connector_run.text)
            self.assertEqual(connector_run.json()["status"], "approval_required")
            old_snapshot = client.post(
                "/product/sources/snapshot",
                json={
                    "source_ref": "route-owned-source",
                    "content_hash": "old-route-hash",
                    "source_policy_path": source_policy.json()["path"],
                    "risk_report_path": source_risk.json()["path"],
                    "project_id": "route-source-project",
                },
            )
            self.assertEqual(old_snapshot.status_code, 200, old_snapshot.text)
            new_snapshot = client.post(
                "/product/sources/snapshot",
                json={
                    "source_ref": "route-owned-source",
                    "content_hash": "new-route-hash",
                    "source_policy_path": source_policy.json()["path"],
                    "risk_report_path": source_risk.json()["path"],
                    "project_id": "route-source-project",
                },
            )
            self.assertEqual(new_snapshot.status_code, 200, new_snapshot.text)
            diff_plan = client.post(
                "/product/sources/diff-repair-plan",
                json={
                    "source_ref": "route-owned-source",
                    "old_snapshot_path": old_snapshot.json()["path"],
                    "new_snapshot_path": new_snapshot.json()["path"],
                    "project_id": "route-source-project",
                },
            )
            self.assertEqual(diff_plan.status_code, 200, diff_plan.text)
            self.assertEqual(diff_plan.json()["asset"]["type"], "change_impact_report")
            self.assertFalse(diff_plan.json()["mutation_applied"])
            diff_apply = client.post("/product/sources/diff-repair-apply", json={"repair_plan_path": diff_plan.json()["path"], "project_id": "route-source-project"})
            self.assertEqual(diff_apply.status_code, 200, diff_apply.text)
            self.assertEqual(diff_apply.json()["status"], "approval_required")
            self.assertFalse(diff_apply.json()["mutation_applied"])
            self.assertEqual(client.get("/product/longform-stability/dashboard").status_code, 200)
            self.assertEqual(client.get("/product/platform-strategy/assets").status_code, 200)
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
            control_asset = client.post(
                "/product/longform-stability/control-asset",
                json={
                    "asset_type": "canon_database",
                    "project_id": project.json()["project_id"],
                    "workspace_path": project.json()["path"],
                    "content": {"entities": [{"entity_id": "azhao", "entity_type": "character", "canonical_name": "阿照"}]},
                },
            )
            self.assertEqual(control_asset.status_code, 200, control_asset.text)
            settings_profile = client.post("/product/settings/profile", json={"workspace_path": project.json()["path"]})
            self.assertEqual(settings_profile.status_code, 200, settings_profile.text)
            metric_snapshot = client.post(
                "/product/metrics/snapshot",
                json={"project_id": project.json()["project_id"], "workspace_path": project.json()["path"]},
            )
            self.assertEqual(metric_snapshot.status_code, 200, metric_snapshot.text)
            approval_request = client.post(
                "/product/permission-center/approval-requests",
                json={
                    "project_id": project.json()["project_id"],
                    "scope": "publish",
                    "action": "submit_release_package",
                    "environment": "local",
                    "risk_level": "high",
                    "blocking": True,
                    "target_type": "release_package",
                    "target_id": "release-route-fixture",
                },
            )
            self.assertEqual(approval_request.status_code, 200, approval_request.text)
            request_id = approval_request.json()["asset"]["content"]["request_id"]
            resolved_request = client.post(
                f"/product/permission-center/approval-requests/{request_id}/resolve",
                json={"decision": "approved", "actor": "route-test", "reason": "route fixture"},
            )
            self.assertEqual(resolved_request.status_code, 200, resolved_request.text)
            self.assertEqual(client.get("/product/permission-center/approval-requests", params={"project_id": project.json()["project_id"]}).status_code, 200)
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
            context_governance_coverage = client.get(f"/product/context/governance-runtime-coverage?project_id={project.json()['project_id']}&persist=false")
            self.assertEqual(context_governance_coverage.status_code, 200, context_governance_coverage.text)
            self.assertEqual(context_governance_coverage.json()["snapshot_kind"], "context_governance_runtime_coverage")
            context_governance_gate = client.post(
                "/product/context/governance-runtime-gate",
                json={"project_id": project.json()["project_id"], "environment": "local", "persist_report": False},
            )
            self.assertEqual(context_governance_gate.status_code, 200, context_governance_gate.text)
            self.assertIn(context_governance_gate.json()["status"], {"passed", "warning"})
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
                    "environment": "operating_system",
                    "os_envelope": {"environment": "operating_system", "operation": "chapter-production-api-fixture", "trace_id": "trace-api-fixture"},
                    "source_policy": {"raw_source_text_allowed": False, "generation_rag_allowed": False},
                    "require_external_provider_proof": True,
                },
            )
            self.assertEqual(chapter_run.status_code, 200, chapter_run.text)
            self.assertEqual(chapter_run.json()["status"], "succeeded")
            self.assertTrue(chapter_run.json()["outputs"]["context_bundle_path"])
            quality_policy = chapter_run.json()["asset"]["content"]["quality_loop_policy"]
            self.assertEqual(quality_policy["environment"], "operating_system")
            self.assertEqual(quality_policy["os_envelope"]["trace_id"], "trace-api-fixture")
            self.assertFalse(quality_policy["source_policy"]["raw_source_text_allowed"])
            self.assertTrue(quality_policy["require_external_provider_proof"])
            with patch("novel_forge.api.routers.production_chain._enqueue_chapter_production_task") as enqueue:
                enqueue.return_value = type("Task", (), {"id": "celery-policy-fixture"})()
                async_chapter_run = client.post(
                    "/product/production/chapter-run/start",
                    json={
                        "outline_path": str(outline_path.relative_to(storage.root)),
                        "workspace_path": project.json()["path"],
                        "chapter": 2,
                        "run_to": "outline_checkpoint",
                        "async_task": True,
                        "environment": "operating_system",
                        "os_envelope": {"environment": "operating_system", "operation": "chapter-production-api-async-fixture", "trace_id": "trace-api-async-fixture"},
                        "source_policy": {"raw_source_text_allowed": False, "generation_rag_allowed": False},
                        "require_external_provider_proof": True,
                    },
                )
            self.assertEqual(async_chapter_run.status_code, 200, async_chapter_run.text)
            self.assertEqual(async_chapter_run.json()["mode"], "async")
            async_quality_policy = async_chapter_run.json()["asset"]["content"]["quality_loop_policy"]
            self.assertEqual(async_quality_policy["environment"], "operating_system")
            self.assertEqual(async_quality_policy["os_envelope"]["trace_id"], "trace-api-async-fixture")
            self.assertFalse(async_quality_policy["source_policy"]["raw_source_text_allowed"])
            self.assertTrue(async_quality_policy["require_external_provider_proof"])
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
            calibration = client.post(
                "/product/longform-stability/calibrate",
                json={
                    "draft_path": draft_ref,
                    "workspace_path": project.json()["path"],
                    "expected": {"characters": ["阿照"], "organizations": [], "locations": [], "clues": [], "motifs": []},
                    "use_model": False,
                    "persist": True,
                },
            )
            self.assertEqual(calibration.status_code, 200, calibration.text)
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

    def test_v1_chapter_production_workflow_template_route_creates_definition_only(self):
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:
            self.skipTest("FastAPI test client is not installed")

        from novel_forge.api.app import create_app
        from novel_forge.infrastructure.settings import IndustrialSettings

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(IndustrialSettings(root=Path(tmp).resolve()))
            client = TestClient(app)

            response = client.post(
                "/product/workflow/templates/v1-chapter-production",
                json={
                    "name": "API Template Fixture",
                    "chapter": 2,
                    "run_to": "outline_checkpoint",
                    "environment": "local",
                    "workspace_path": str(Path(tmp).resolve()),
                    "source_policy": {"workflow_policy_marker": "api-template"},
                    "provider_runtime_guard": {"status": "passed", "provider": "fixture"},
                },
            )

            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(body["asset"]["type"], "workflow_definition")
            self.assertEqual(body["asset"]["content"]["template_contract"]["contract"], "v1-chapter-production-workflow-template-v1")
            self.assertFalse(body["asset"]["content"]["template_contract"]["chapter_acceptance_executed"])
            node = body["asset"]["content"]["nodes"][0]
            self.assertEqual(node["processor"]["operation"], "start-chapter-production")
            self.assertEqual(node["processor"]["chapter"], 2)
            self.assertEqual(node["processor"]["source_policy"]["workflow_policy_marker"], "api-template")
            self.assertEqual(node["quality_gate"]["contract"], "canonical_chapter_production_bus")
            self.assertNotIn("workflow_run", body["asset"]["content"])

            console = client.get("/product/workflow/runtime-console", params={"workflow_path_or_id": body["path"]})
            self.assertEqual(console.status_code, 200, console.text)
            self.assertEqual(console.json()["workflow_template_contract"]["contract"], "v1-chapter-production-workflow-template-v1")
            self.assertFalse(console.json()["workflow_template_contract"]["chapter_acceptance_executed"])
            gate = client.post(
                "/product/workflow/governance-drift-gate",
                json={"workflow_path_or_id": body["path"], "environment": "local", "persist_report": True},
            )
            self.assertEqual(gate.status_code, 200, gate.text)
            self.assertIn(gate.json()["status"], {"passed", "warning"})
            self.assertEqual(gate.json()["gate_result"]["asset"]["type"], "gate_result")

    def test_project_cockpit_route_surfaces_workflow_governance_readiness(self):
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:
            self.skipTest("FastAPI test client is not installed")

        from novel_forge.api.app import create_app
        from novel_forge.infrastructure.settings import IndustrialSettings
        from novel_forge.schemas import BaseAsset
        from novel_forge.storage.local import LocalStorage

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            app = create_app(IndustrialSettings(root=root))
            client = TestClient(app)
            storage = LocalStorage(root)
            storage.ensure_layout()
            preflight = {
                "status": "failed",
                "gate_status": "failed",
                "blocking": True,
                "message": "workflow governance drift has 1 blocking row(s)",
                "environment": "production",
                "mode": "strict",
                "gate_result_path": "data/runs/route-workflow-governance-gate.json",
                "drift_report_path": "data/runs/route-workflow-governance-report.json",
                "summary": {"drift_count": 1, "blocking_drift_count": 1},
            }
            storage.write_asset_auto(
                BaseAsset(
                    id="route-workflow-governance-gate",
                    type="gate_result",
                    title="Route workflow governance drift gate",
                    content={
                        "gate_id": "route-workflow-governance-gate",
                        "gate_kind": "workflow_governance_drift",
                        "status": "failed",
                        "target_paths": ["data/runs/route-workflow-definition.json"],
                        "blocking": True,
                        "message": preflight["message"],
                        "result": {"summary": preflight["summary"], "report_path": preflight["drift_report_path"]},
                        "created_at": "2026-07-08T00:00:00Z",
                    },
                    metadata={"project_id": "route-book"},
                )
            )
            storage.write_asset_auto(
                BaseAsset(
                    id="route-workflow-run-governance-failed",
                    type="workflow_run",
                    title="Route workflow governance failed run",
                    content={
                        "run_id": "route-workflow-run-governance-failed",
                        "workflow_id": "route-workflow-definition",
                        "workflow_definition_path": "data/runs/route-workflow-definition.json",
                        "status": "failed",
                        "outputs": [],
                        "node_runs": [],
                        "agent_runs": [],
                        "run_log": [],
                        "blocked": {"node_id": "chapter-production-start", "status": "failed", "gate_kind": "workflow_governance_drift"},
                        "error_message": preflight["message"],
                        "recovery_instruction": "repair workflow governance evidence before resume",
                        "lineage": {"workflow_governance_preflight": preflight},
                    },
                    metadata={"project_id": "route-book"},
                )
            )
            storage.write_asset_auto(
                BaseAsset(
                    id="route-ready-node-workflow-governance-dead-letter",
                    type="ready_node_queue",
                    title="Route dead-lettered workflow governance node",
                    content={
                        "queue_id": "route-ready-node-workflow-governance-dead-letter",
                        "workflow_run_id": "route-workflow-run-governance-failed",
                        "workflow_run_path": "data/runs/route-workflow-run-governance-failed.json",
                        "node_id": "chapter-production-start",
                        "status": "dead_letter",
                        "last_error": preflight["message"],
                        "dead_letter_evidence": {
                            "workflow_governance_preflight": preflight,
                            "resume_workflow_run_path": "data/runs/route-workflow-run-governance-resume.json",
                        },
                    },
                    metadata={"project_id": "route-book"},
                )
            )

            response = client.get("/product/os/cockpit/project", params={"project_id": "route-book"})

            self.assertEqual(response.status_code, 200, response.text)
            content = response.json()["asset"]["content"]
            workflow_governance = content["runtime_governance"]["workflow_governance"]
            self.assertEqual(workflow_governance["status"], "blocked")
            self.assertEqual(workflow_governance["failed_preflight_count"], 1)
            self.assertEqual(workflow_governance["dead_letter_count"], 1)
            self.assertIn(preflight["drift_report_path"], workflow_governance["evidence_paths"])
            self.assertEqual(content["quality"]["workflow_governance_status"], "blocked")
            self.assertEqual(content["cockpit"]["workflow_governance"]["status"], "blocked")
            self.assertEqual(content["production_control_console"]["gate_status_board"]["workflow_governance"], "blocked")

    def test_permission_center_route_surfaces_approval_request_caller_readiness(self):
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:
            self.skipTest("FastAPI test client is not installed")

        from novel_forge.api.app import create_app
        from novel_forge.infrastructure.settings import IndustrialSettings

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(IndustrialSettings(root=Path(tmp).resolve()))
            client = TestClient(app)
            fixtures = [
                ("source", "allow_generation_context", "source_policy"),
                ("context", "override_context_bundle", "context_bundle"),
                ("publish", "submit_release_package", "release_package"),
                ("feedback", "apply_feedback_mutation", "feedback_plan_mutation_proposal"),
                ("story_mutation", "apply_outline_patch", "outline"),
            ]
            for scope, action, target_type in fixtures:
                response = client.post(
                    "/product/permission-center/approval-requests",
                    json={
                        "project_id": "route-approval-readiness",
                        "scope": scope,
                        "action": action,
                        "environment": "local",
                        "risk_level": "high",
                        "blocking": True,
                        "target_type": target_type,
                        "target_id": f"{scope}-fixture",
                    },
                )
                self.assertEqual(response.status_code, 200, response.text)

            response = client.get(
                "/product/permission-center/approval-request-caller-readiness",
                params={"project_id": "route-approval-readiness"},
            )

            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()
            content = payload["asset"]["content"]
            self.assertEqual(payload["asset"]["type"], "project_metric_snapshot")
            self.assertEqual(payload["asset"]["metadata"]["snapshot_kind"], "approval_request_caller_readiness")
            self.assertEqual(content["status"], "review_required")
            self.assertTrue(content["non_mutating"])
            self.assertEqual(content["summary"]["covered_dimension_count"], 5)
            self.assertEqual(content["summary"]["missing_dimension_count"], 0)
            self.assertEqual(content["summary"]["pending_blocking_count"], 5)
            self.assertEqual(len(content["evidence_paths"]), 5)

    def test_source_guarded_apply_readiness_route_surfaces_reviewable_evidence(self):
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:
            self.skipTest("FastAPI test client is not installed")

        from novel_forge.api.app import create_app
        from novel_forge.infrastructure.settings import IndustrialSettings
        from novel_forge.modules.source_intake import create_source_policy, create_source_risk_report, create_source_snapshot, plan_source_diff_repair
        from novel_forge.schemas import KnowledgeCard
        from novel_forge.storage.local import LocalStorage

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            app = create_app(IndustrialSettings(root=root))
            client = TestClient(app)
            storage = LocalStorage(root)
            policy = create_source_policy(storage, {"source_ref": "local-corpus", "risk_tier": "R1", "project_id": "route-source-readiness"})
            risk = create_source_risk_report(storage, {"source_ref": "local-corpus", "source_policy_path": policy["path"], "project_id": "route-source-readiness"})
            old_snapshot = create_source_snapshot(
                storage,
                {
                    "source_ref": "local-corpus",
                    "source_type": "local_manifest",
                    "content_hash": "old-hash",
                    "source_path": "sources/local-corpus/manifest.json",
                    "source_policy_path": policy["path"],
                    "risk_report_path": risk["path"],
                    "project_id": "route-source-readiness",
                },
            )
            new_snapshot = create_source_snapshot(
                storage,
                {
                    "source_ref": "local-corpus",
                    "source_type": "local_manifest",
                    "content_hash": "new-hash",
                    "source_path": "sources/local-corpus/manifest.json",
                    "source_policy_path": policy["path"],
                    "risk_report_path": risk["path"],
                    "project_id": "route-source-readiness",
                },
            )
            storage.write_asset_auto(
                KnowledgeCard(
                    title="Source-derived abstraction",
                    source="local-corpus",
                    tags=["mkaos", "source-derived"],
                    content={"principles": ["Abstract source mechanism."], "principle": "Abstract source mechanism.", "source_snapshot_ref": old_snapshot["asset"]["id"]},
                    metadata={
                        "project_id": "route-source-readiness",
                        "asset_status": "active",
                        "use_in_generation_rag": True,
                        "copyright_boundary": "abstract structure only; no raw source expression",
                    },
                    references=[old_snapshot["path"], old_snapshot["asset"]["id"]],
                )
            )
            plan_source_diff_repair(storage, {"old_snapshot_path": old_snapshot["path"], "new_snapshot_path": new_snapshot["path"], "project_id": "route-source-readiness"})

            response = client.get("/product/sources/guarded-apply-readiness", params={"project_id": "route-source-readiness"})

            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()
            content = payload["asset"]["content"]
            self.assertEqual(payload["asset"]["type"], "project_metric_snapshot")
            self.assertEqual(payload["asset"]["metadata"]["snapshot_kind"], "source_guarded_apply_readiness")
            self.assertEqual(content["status"], "review_required")
            self.assertEqual(content["summary"]["repair_plan_count"], 1)
            self.assertEqual(content["summary"]["pending_review_plan_count"], 1)
            self.assertGreaterEqual(content["summary"]["review_task_count"], 1)
            self.assertFalse(content["quality"]["connector_execution_performed"])
            self.assertFalse(content["quality"]["dispatch_applied"])

    def test_project_cockpit_route_surfaces_clean_workflow_governance_readiness(self):
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:
            self.skipTest("FastAPI test client is not installed")

        from novel_forge.api.app import create_app
        from novel_forge.infrastructure.settings import IndustrialSettings
        from novel_forge.schemas import BaseAsset
        from novel_forge.storage.local import LocalStorage

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            app = create_app(IndustrialSettings(root=root))
            client = TestClient(app)
            storage = LocalStorage(root)
            storage.ensure_layout()
            preflight = {
                "status": "passed",
                "gate_status": "passed",
                "blocking": False,
                "message": "workflow governance drift gate passed",
                "environment": "production",
                "mode": "strict",
                "gate_result_path": "data/runs/route-workflow-governance-clean-gate.json",
                "drift_report_path": "data/runs/route-workflow-governance-clean-report.json",
                "summary": {"drift_count": 0, "blocking_drift_count": 0},
            }
            storage.write_asset_auto(
                BaseAsset(
                    id="route-workflow-governance-clean-gate",
                    type="gate_result",
                    title="Route clean workflow governance drift gate",
                    content={
                        "gate_id": "route-workflow-governance-clean-gate",
                        "gate_kind": "workflow_governance_drift",
                        "status": "passed",
                        "target_paths": ["data/runs/route-workflow-definition-clean.json"],
                        "blocking": False,
                        "message": preflight["message"],
                        "result": {"summary": preflight["summary"], "report_path": preflight["drift_report_path"]},
                        "created_at": "2026-07-08T00:00:00Z",
                    },
                    metadata={"project_id": "route-book-clean"},
                )
            )
            storage.write_asset_auto(
                BaseAsset(
                    id="route-workflow-run-governance-clean",
                    type="workflow_run",
                    title="Route workflow governance clean run",
                    content={
                        "run_id": "route-workflow-run-governance-clean",
                        "workflow_id": "route-workflow-definition-clean",
                        "workflow_definition_path": "data/runs/route-workflow-definition-clean.json",
                        "status": "completed",
                        "outputs": ["data/runs/route-chapter-production-clean.json"],
                        "node_runs": [],
                        "agent_runs": [],
                        "run_log": [],
                        "blocked": {},
                        "error_message": "",
                        "recovery_instruction": "",
                        "lineage": {"workflow_governance_preflight": preflight},
                    },
                    metadata={"project_id": "route-book-clean"},
                )
            )

            response = client.get("/product/os/cockpit/project", params={"project_id": "route-book-clean"})

            self.assertEqual(response.status_code, 200, response.text)
            content = response.json()["asset"]["content"]
            workflow_governance = content["runtime_governance"]["workflow_governance"]
            self.assertEqual(workflow_governance["status"], "passed")
            self.assertEqual(workflow_governance["gate_status"], "passed")
            self.assertEqual(workflow_governance["failed_preflight_count"], 0)
            self.assertEqual(workflow_governance["dead_letter_count"], 0)
            self.assertIn(preflight["drift_report_path"], workflow_governance["evidence_paths"])
            self.assertEqual(content["quality"]["workflow_governance_status"], "passed")
            self.assertEqual(content["cockpit"]["workflow_governance"]["status"], "passed")
            self.assertEqual(content["production_control_console"]["gate_status_board"]["workflow_governance"], "passed")

    def test_project_cockpit_route_surfaces_approval_request_caller_readiness(self):
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:
            self.skipTest("FastAPI test client is not installed")

        from novel_forge.api.app import create_app
        from novel_forge.infrastructure.settings import IndustrialSettings
        from novel_forge.modules.permission_center import build_approval_request_caller_readiness_report, create_approval_request
        from novel_forge.storage.local import LocalStorage

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            app = create_app(IndustrialSettings(root=root))
            client = TestClient(app)
            storage = LocalStorage(root)
            storage.ensure_layout()
            for scope, action, target_type in [
                ("source", "allow_generation_context", "source_policy"),
                ("context", "override_context_bundle", "context_bundle"),
                ("publish", "submit_release_package", "release_package"),
                ("feedback", "apply_feedback_mutation", "feedback_plan_mutation_proposal"),
                ("story_mutation", "apply_outline_patch", "outline"),
            ]:
                create_approval_request(
                    storage,
                    {
                        "project_id": "route-book-approval-readiness",
                        "scope": scope,
                        "action": action,
                        "environment": "local",
                        "risk_level": "high",
                        "blocking": True,
                        "target_type": target_type,
                        "target_id": f"{scope}-fixture",
                    },
                )
            build_approval_request_caller_readiness_report(storage, project_id="route-book-approval-readiness")

            response = client.get("/product/os/cockpit/project", params={"project_id": "route-book-approval-readiness"})

            self.assertEqual(response.status_code, 200, response.text)
            content = response.json()["asset"]["content"]
            readiness = content["runtime_governance"]["approval_request_caller_readiness"]
            self.assertEqual(readiness["status"], "review_required")
            self.assertEqual(readiness["summary"]["covered_dimension_count"], 5)
            self.assertEqual(readiness["summary"]["missing_dimension_count"], 0)
            self.assertEqual(readiness["summary"]["pending_blocking_count"], 5)
            self.assertTrue(readiness["path"])
            self.assertEqual(content["quality"]["approval_request_caller_readiness_status"], "review_required")
            self.assertEqual(content["quality"]["approval_request_missing_caller_count"], 0)
            self.assertEqual(content["cockpit"]["approval_request_caller_readiness"]["status"], "review_required")
            self.assertEqual(content["production_control_console"]["gate_status_board"]["approval_request_callers"], "review_required")

    def test_project_cockpit_route_surfaces_source_guarded_apply_readiness(self):
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:
            self.skipTest("FastAPI test client is not installed")

        from novel_forge.api.app import create_app
        from novel_forge.infrastructure.settings import IndustrialSettings
        from novel_forge.schemas import ProjectMetricSnapshot
        from novel_forge.storage.local import LocalStorage

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            app = create_app(IndustrialSettings(root=root))
            client = TestClient(app)
            storage = LocalStorage(root)
            storage.write_asset_auto(
                ProjectMetricSnapshot(
                    title="Route source guarded apply readiness",
                    content={
                        "snapshot_kind": "source_guarded_apply_readiness",
                        "contract": "source-guarded-apply-readiness-v1",
                        "status": "review_required",
                        "project_id": "route-book-source-readiness",
                        "snapshot_at": "2026-07-08T00:00:00Z",
                        "throughput": {"repair_plan_count": 1, "approval_request_count": 1, "stale_asset_count": 1, "agent_task_count": 1},
                        "quality": {"readiness_status": "review_required", "stale_pending_regeneration_count": 1, "dispatch_applied": False},
                        "task_health": {"dispatch_ready_task_count": 1, "operator_action": "dispatch approved regeneration"},
                        "agent_health": {"planned_agent_operations": ["plan-source-derived-regeneration"]},
                        "storage_health": {"evidence_path_count": 2},
                        "recommendations": ["dispatch approved regeneration"],
                        "summary": {
                            "repair_plan_count": 1,
                            "pending_review_plan_count": 0,
                            "applied_plan_count": 1,
                            "approval_request_count": 1,
                            "pending_approval_count": 0,
                            "blocking_approval_count": 0,
                            "stale_pending_regeneration_count": 1,
                            "review_task_count": 0,
                            "dispatch_ready_task_count": 1,
                            "rollback_plan_count": 1,
                            "rollback_result_count": 0,
                        },
                        "repair_plans": [{"path": "data/runs/source-repair.json", "asset_status": "applied"}],
                        "stale_assets": [{"path": "data/knowledge/stale-card.json", "asset_status": "stale"}],
                        "agent_tasks": [{"path": "data/runs/source-task.json", "status": "approved_pending_dispatch"}],
                        "evidence_paths": ["data/runs/source-repair.json", "data/knowledge/stale-card.json"],
                        "operator_action": "dispatch approved regeneration",
                    },
                    metadata={"project_id": "route-book-source-readiness", "snapshot_kind": "source_guarded_apply_readiness"},
                )
            )

            response = client.get("/product/os/cockpit/project", params={"project_id": "route-book-source-readiness"})

            self.assertEqual(response.status_code, 200, response.text)
            content = response.json()["asset"]["content"]
            readiness = content["runtime_governance"]["source_guarded_apply_readiness"]
            self.assertEqual(readiness["status"], "review_required")
            self.assertEqual(readiness["summary"]["stale_pending_regeneration_count"], 1)
            self.assertEqual(readiness["summary"]["dispatch_ready_task_count"], 1)
            self.assertTrue(readiness["path"])
            self.assertEqual(content["quality"]["source_guarded_apply_status"], "review_required")
            self.assertEqual(content["production_control_console"]["gate_status_board"]["source_guarded_apply"], "review_required")
            self.assertEqual(content["cockpit"]["source_guarded_apply_readiness"]["status"], "review_required")

    def test_project_cockpit_route_keeps_missing_workflow_governance_unready(self):
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:
            self.skipTest("FastAPI test client is not installed")

        from novel_forge.api.app import create_app
        from novel_forge.infrastructure.settings import IndustrialSettings

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            app = create_app(IndustrialSettings(root=root))
            client = TestClient(app)

            response = client.get("/product/os/cockpit/project", params={"project_id": "route-book-missing"})

            self.assertEqual(response.status_code, 200, response.text)
            content = response.json()["asset"]["content"]
            workflow_governance = content["runtime_governance"]["workflow_governance"]
            self.assertEqual(workflow_governance["status"], "missing")
            self.assertEqual(workflow_governance["gate_status"], "missing")
            self.assertEqual(workflow_governance["preflight_count"], 0)
            self.assertEqual(workflow_governance["failed_preflight_count"], 0)
            self.assertEqual(workflow_governance["dead_letter_count"], 0)
            self.assertEqual(workflow_governance["evidence_paths"], [])
            self.assertEqual(content["quality"]["workflow_governance_status"], "missing")
            self.assertEqual(content["cockpit"]["workflow_governance"]["status"], "missing")
            self.assertEqual(content["production_control_console"]["gate_status_board"]["workflow_governance"], "missing")


if __name__ == "__main__":
    unittest.main()
