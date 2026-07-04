from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.canon_graph import (
    build_canon_graph,
    create_canon_change_approval,
    diff_canon_graph,
    locate_canon_graph_impacted_chapters,
    propagate_canon_graph_conflicts,
    resolve_canon_change_approval,
)
from novel_forge.modules.longform_stability import create_canon_database
from novel_forge.schemas import CharacterStateLedger, DraftChapter
from novel_forge.storage.local import LocalStorage


class CanonGraphV1GovernanceTests(unittest.TestCase):
    def test_diff_approval_propagation_and_impacted_chapters(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            create_canon_database(
                storage,
                project_id="canon-v1",
                entities=[{"entity_id": "azhao", "entity_type": "character", "canonical_name": "阿照", "status": "active"}],
            )
            ledger_path = storage.write_asset(
                "continuity",
                CharacterStateLedger(
                    title="Ledger",
                    content={"ledger_id": "ledger", "chapter_no": 2, "characters": [{"character_id": "azhao", "canonical_name": "阿照", "status": "dead"}]},
                    metadata={"project_id": "canon-v1"},
                ),
            )
            baseline = build_canon_graph(storage, project_id="canon-v1", persist=True)
            storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Draft",
                    content={"chapter": 3, "text": "阿照在第三章继续行动。"},
                    metadata={"project_id": "canon-v1"},
                ),
            )
            ledger = storage.read_json(ledger_path)
            ledger["content"]["characters"][0]["status"] = "alive"
            storage.write_json(ledger_path, ledger)

            diff = diff_canon_graph(storage, {"project_id": "canon-v1", "baseline_snapshot_path": baseline["path"]})
            impact = locate_canon_graph_impacted_chapters(storage, {"project_id": "canon-v1", "keywords": ["阿照"]})
            propagation = propagate_canon_graph_conflicts(storage, {"project_id": "canon-v1", "artifact_text": "阿照死亡后仍继续行动。"})
            approval = create_canon_change_approval(
                storage,
                {
                    "project_id": "canon-v1",
                    "baseline_snapshot_path": baseline["path"],
                    "proposal": {"summary": "restore 阿照 lifecycle"},
                    "proposed_patch": {"characters": [{"character_id": "azhao", "status": "alive"}]},
                    "actor": "chief-editor",
                },
            )
            resolved = resolve_canon_change_approval(storage, approval["approval"]["approval_id"], {"decision": "approved", "actor": "chief-editor"})

            self.assertEqual(diff["status"], "changed")
            self.assertGreaterEqual(diff["summary"]["changed_node_count"], 1)
            self.assertEqual(impact["summary"]["impacted_chapter_count"], 1)
            self.assertIn(propagation["status"], {"blocked", "warning"})
            self.assertEqual(approval["status"], "waiting_human")
            self.assertEqual(resolved["status"], "approved")
            self.assertEqual(resolved["canon_patch"]["asset"]["type"], "canon_patch")


if __name__ == "__main__":
    unittest.main()
