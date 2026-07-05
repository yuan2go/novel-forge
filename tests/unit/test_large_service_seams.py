from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.api.services import product as product_service
from novel_forge.api.services.postgres_fallback_policy import handle_postgres_asset_read_fallback, postgres_asset_read_fallback_policy
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.mkaos.risk_policy import normalize_risk_level, risk_reasons, severity_penalty
from novel_forge.modules.workflow_nodes.publishing_ops import run_publish_gate_report_operation
from novel_forge.schemas import DraftChapter, ProjectWorkspaceState
from novel_forge.storage.local import LocalStorage


class LargeServiceSeamTests(unittest.TestCase):
    def test_postgres_asset_read_fallback_policy_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            loose = IndustrialSettings(root=Path(tmp), database_url="postgresql://unit", postgres_write_strict=False)
            strict = IndustrialSettings(root=Path(tmp), database_url="postgresql://unit", postgres_write_strict=True)
            local = IndustrialSettings(root=Path(tmp), database_url="", postgres_write_strict=False)

            self.assertEqual(postgres_asset_read_fallback_policy(local)["mode"], "local_only")
            loose_policy = postgres_asset_read_fallback_policy(loose, RuntimeError("down"))
            self.assertTrue(loose_policy["allow_local_fallback"])
            self.assertTrue(loose_policy["audit_required"])
            self.assertFalse(loose_policy["silent_fallback_allowed"])
            self.assertEqual(loose_policy["rollback_plan"]["rollback_action"], "restore_postgres_asset_index")
            strict_policy = postgres_asset_read_fallback_policy(strict, RuntimeError("down"))
            self.assertFalse(strict_policy["allow_local_fallback"])
            self.assertEqual(strict_policy["http_status"], 503)
            self.assertTrue(strict_policy["audit_required"])

    def test_postgres_asset_read_fallback_persists_decision_when_audited(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            settings = IndustrialSettings(root=Path(tmp), database_url="postgresql://unit", postgres_write_strict=False)

            policy = handle_postgres_asset_read_fallback(
                storage,
                settings,
                RuntimeError("index down"),
                operation="indexed_list_projects",
            )
            decision = storage.read_json(storage.root / policy["fallback_decision_path"])

            self.assertTrue(policy["allow_local_fallback"])
            self.assertEqual(decision["type"], "fallback_decision")
            self.assertEqual(decision["content"]["fallback_type"], "postgres_asset_read")
            self.assertFalse(decision["content"]["silent_fallback_allowed"])
            self.assertEqual(decision["content"]["rollback_plan"]["rollback_action"], "restore_postgres_asset_index")

    def test_indexed_project_read_records_fallback_decision_on_postgres_failure(self):
        class FailingPostgresStore:
            def list_projects(self, include_deleted: bool = False):
                raise RuntimeError("postgres unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            settings = IndustrialSettings(root=Path(tmp), database_url="postgresql://unit", postgres_write_strict=False)
            storage.write_asset(
                "workspaces",
                ProjectWorkspaceState(
                    title="Fallback indexed project",
                    content={
                        "project_id": "fallback-index-project",
                        "project_config": {"status": "active"},
                        "memory": {},
                        "chapter_states": [],
                        "continuity_threads": {},
                        "open_issues": [],
                    },
                ),
            )

            with patch.object(product_service, "_postgres_store", return_value=FailingPostgresStore()):
                rows = product_service.indexed_list_projects(settings, storage)

            self.assertEqual(rows[0]["index_source"], "json")
            decisions = [
                storage.read_json(path)
                for path in storage.list_json("runs")
                if storage.read_json(path).get("type") == "fallback_decision"
            ]
            self.assertTrue(decisions)
            self.assertEqual(decisions[-1]["content"]["mode"], "postgres_read_fail_open")
            self.assertFalse(decisions[-1]["content"]["silent_fallback_allowed"])

    def test_mkaos_risk_policy_matches_existing_characterization(self):
        row = {
            "id": "knowledge-risk",
            "content": {"status": "needs_review", "risk_level": "high"},
            "metadata": {"asset_status": "active"},
        }

        self.assertEqual(normalize_risk_level(" HIGH "), "high")
        self.assertEqual(normalize_risk_level("unknown"), "low")
        self.assertEqual(severity_penalty("critical"), 45)
        self.assertEqual(severity_penalty("unexpected"), 5)
        self.assertEqual(risk_reasons(row, {"knowledge-risk"}), ["needs_review", "high_risk", "review_hit"])

    def test_workflow_publishing_seam_creates_publish_gate_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace_path = storage.write_asset(
                "workspaces",
                ProjectWorkspaceState(
                    title="Workflow publishing seam",
                    content={
                        "project_id": "workflow-publish-seam-p",
                        "memory": {},
                        "chapter_states": [],
                        "continuity_threads": {},
                        "open_issues": [],
                        "project_config": {"target_platform": "local_serial"},
                    },
                ),
            )
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Chapter 1",
                    content={"chapter": 1, "text": "原创章节文本，包含目标、冲突、反转和发布钩子。"},
                    metadata={"project_id": "workflow-publish-seam-p", "workspace_path": str(workspace_path.relative_to(storage.root))},
                    references=[str(workspace_path.relative_to(storage.root))],
                ),
            )

            gate_path = run_publish_gate_report_operation(
                storage,
                draft_path,
                workspace_path=str(workspace_path.relative_to(storage.root)),
                human_override=True,
            )

            self.assertEqual(storage.read_asset(gate_path).type, "publish_gate_report")


if __name__ == "__main__":
    unittest.main()
