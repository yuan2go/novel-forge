from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.publishing import (
    create_publish_gate_report,
    create_publishing_log,
    create_publishing_plan,
    create_release_package,
    list_publishing_assets,
    prepare_platform_release,
    publishing_adapter_status,
)
from novel_forge.modules.publishing.release_gate import release_package_gate_evidence
from novel_forge.schemas import DraftChapter, ProjectWorkspaceState
from novel_forge.storage.local import LocalStorage


class PublishingCenterTests(unittest.TestCase):
    def test_publishing_calendar_rules_logs_and_version_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace_path = storage.write_asset(
                "workspaces",
                ProjectWorkspaceState(
                    title="Publishing Project",
                    content={
                        "project_id": "project_publish",
                        "memory": {},
                        "chapter_states": [],
                        "continuity_threads": {},
                        "open_issues": [],
                        "project_config": {"target_platform": "local_serial", "publish_min_hook_score": 0.75},
                    },
                ),
            )
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Chapter 1",
                    content={
                        "chapter": 1,
                        "text": (
                            "雨夜里，林澈在封存的卷宗里发现一枚带血的登记铜牌，这条线索指向三年前被掩盖的真相。"
                            "官署黑手逼近，威胁要扣押他的师父；林澈却选择拒绝退让，决定当众查明旧案。"
                            "他赌上自己的官职和名声，把铜牌塞到证人手中，逼对方承认账册被调包。"
                            "然而反转忽然出现，证人交出的不是账册，而是反派提前准备的空匣。"
                            "林澈承责保住证人，证明旧案仍有活口，也让新的疑点和下一章钩子同时浮出水面。"
                        ),
                        "chapter_plan_blueprint": {
                            "pleasure_beats": ["发现一枚带血的登记铜牌", "选择拒绝退让", "反转忽然出现"],
                            "payoff_target": {"local_payoff": "证明旧案仍有活口", "withheld_question": "账册去了哪里"},
                            "conflict_beats": [{"choice": "选择拒绝退让", "cost": "赌上自己的官职和名声", "reversal": "反转忽然出现"}],
                        },
                    },
                    metadata={"project_id": "project_publish", "workspace_path": str(workspace_path.relative_to(storage.root))},
                    references=[str(workspace_path.relative_to(storage.root))],
                ),
            )

            gate_path = create_publish_gate_report(
                storage,
                draft_path,
                workspace_path=str(workspace_path.relative_to(storage.root)),
                human_override=True,
            )
            gate_asset = storage.read_asset(gate_path)
            self.assertEqual(gate_asset.type, "publish_gate_report")
            self.assertIn("source_governance_gate", gate_asset.content)
            self.assertEqual(gate_asset.content["source_governance_gate"]["status"], "warning")

            package_path = create_release_package(
                storage,
                draft_path,
                workspace_path=str(workspace_path.relative_to(storage.root)),
                publish_gate_path=gate_path,
                channel="local_serial",
                human_override=True,
            )
            package = storage.read_asset(package_path)
            self.assertEqual(package.type, "release_package")
            self.assertTrue(package.content["release_version"])
            self.assertEqual(package.content["platform_rules"]["target_platform"], "local_serial")
            self.assertTrue(package.content["metadata_optimization"]["title_candidates"])
            self.assertIn("cover_asset", package.content)
            self.assertIn("source_governance_gate", package.content)

            plan = create_publishing_plan(
                storage,
                release_package_paths=[str(package_path.relative_to(storage.root))],
                project_id="project_publish",
                workspace_path=str(workspace_path.relative_to(storage.root)),
                channel="local_serial",
                cadence="daily",
                start_date="2026-07-01",
            )
            self.assertEqual(storage.read_asset(plan["path"]).content["calendar"][0]["scheduled_at"], "2026-07-01")
            self.assertTrue(storage.read_asset(plan["path"]).content["platform_rules"]["require_publish_gate_ready"])

            log = create_publishing_log(
                storage,
                str(package_path.relative_to(storage.root)),
                publishing_plan_path=plan["path"],
                channel="local_serial",
                external_url="https://local.example/chapter-1",
            )
            self.assertTrue(storage.read_asset(log["path"]).content["rollback_plan"]["available"])
            self.assertIn("platform_feedback", storage.read_asset(log["path"]).content)

            rows = list_publishing_assets(storage, project_id="project_publish")
            by_type = {row["type"]: row for row in rows}
            self.assertEqual(by_type["release_package"]["release_version"], package.content["release_version"])
            self.assertTrue(by_type["release_package"]["metadata_optimization"])
            self.assertEqual(by_type["publishing_plan"]["next_scheduled_at"], "2026-07-01")
            self.assertTrue(by_type["publishing_log"]["rollback_available"])

            adapters = {row["key"]: row for row in publishing_adapter_status()}
            self.assertIn("manual_web", adapters)
            self.assertFalse(adapters["manual_web"]["can_execute"])
            adapter_result = prepare_platform_release(
                storage,
                str(package_path.relative_to(storage.root)),
                publishing_plan_path=plan["path"],
                adapter_key="manual_web",
                dry_run=True,
            )
            self.assertEqual(adapter_result["adapter"], "manual_web")
            adapter_log = storage.read_asset(adapter_result["path"])
            self.assertEqual(adapter_log.content["adapter_result"]["status"], "manual_required")
            self.assertTrue(adapter_log.content["approval_request"]["required"])
            self.assertEqual(adapter_log.content["approval_request"]["scope"], "publish")
            self.assertTrue(adapter_log.content["approval_request"]["path"])
            self.assertTrue(adapter_log.content["adapter_payload"]["manual_checklist"])

    def test_release_gate_evidence_requires_source_governance_gate_in_production(self):
        gate = {
            "id": "publish-gate-source-fixture",
            "content": {
                "decision": "ready",
                "production_governance": {"status": "passed", "path": "data/runs/production-governance.json"},
                "evaluation_gate": {"status": "passed", "path": "data/runs/eval.json"},
                "provider_runtime_gate": {"status": "passed", "blocking": False},
                "platform_strategy_gate": {"status": "passed", "platform_strategy_pack_path": "data/assets/platform.json"},
                "context_governance_gate": {"status": "passed", "gate_result_path": "data/runs/context-gate.json"},
                "release_quality": {
                    "asset_integrity": {"status": "passed", "path": "data/runs/release-asset-integrity.json", "blocking": False},
                    "content_quality": {"status": "passed", "path": "data/runs/release-content-quality.json", "blocking": False},
                },
            },
        }

        blocked = release_package_gate_evidence(gate, production=True)
        gate["content"]["source_governance_gate"] = {"status": "passed", "gate_result_path": "data/runs/source-gate.json"}
        passed = release_package_gate_evidence(gate, production=True)

        self.assertTrue(blocked["blocking"])
        self.assertIn("source_governance_gate", {issue["dimension"] for issue in blocked["blocking_issues"]})
        self.assertFalse(passed["blocking"])


if __name__ == "__main__":
    unittest.main()
