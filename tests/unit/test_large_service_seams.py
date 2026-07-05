from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.api.services.postgres_fallback_policy import postgres_asset_read_fallback_policy
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
            self.assertTrue(postgres_asset_read_fallback_policy(loose, RuntimeError("down"))["allow_local_fallback"])
            strict_policy = postgres_asset_read_fallback_policy(strict, RuntimeError("down"))
            self.assertFalse(strict_policy["allow_local_fallback"])
            self.assertEqual(strict_policy["http_status"], 503)

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
