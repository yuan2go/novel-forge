from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.operation_transactions import apply_rollback_plan, create_operation_transaction, preview_operation_rollback, verify_rollback_result
from novel_forge.modules.runtime_ledger import record_cost_ledger
from novel_forge.schemas import DraftVersion, validate_common_fields
from novel_forge.storage.local import LocalStorage


class OperationTransactionTests(unittest.TestCase):
    def test_rollback_plan_marks_outputs_and_compensates_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            project_id = "rollback-project"
            previous = storage.write_asset_auto(
                DraftVersion(
                    title="Draft v1",
                    content={
                        "draft_id": "draft-1",
                        "version_index": 1,
                        "chapter": 1,
                        "text": "previous version",
                        "source_draft_id": "draft-1",
                        "change_summary": "base",
                        "status": "active",
                    },
                    metadata={"project_id": project_id},
                )
            )
            created = storage.write_asset_auto(
                DraftVersion(
                    title="Draft v2",
                    content={
                        "draft_id": "draft-1",
                        "version_index": 2,
                        "chapter": 1,
                        "text": "unsafe new version",
                        "source_draft_id": "draft-1",
                        "change_summary": "failed edit",
                        "status": "active",
                    },
                    metadata={"project_id": project_id},
                )
            )
            ledger = record_cost_ledger(
                storage,
                scope=project_id,
                amount=1.25,
                source_type="model_call_log",
                source_id="model-call-1",
                project_id=project_id,
            )

            transaction = create_operation_transaction(
                storage,
                operation="editor_patch",
                created_assets=[str(created.relative_to(storage.root))],
                previous_versions=[str(previous.relative_to(storage.root))],
                ledger_paths=[ledger["path"]],
                indexes_touched=["novel_kg"],
                project_id=project_id,
                trace={"trace_id": "trace-rollback"},
            )
            plan = preview_operation_rollback(storage, transaction["path"], strategy="supersede_outputs")
            result = apply_rollback_plan(storage, plan["path"], confirm=True)

            self.assertEqual(validate_common_fields(transaction["asset"]), [])
            self.assertEqual(validate_common_fields(plan["asset"]), [])
            self.assertEqual(validate_common_fields(result["asset"]), [])
            self.assertEqual(result["asset"]["type"], "rollback_result")
            self.assertEqual(result["asset"]["content"]["status"], "applied")
            self.assertEqual(result["asset"]["content"]["verification"]["status"], "passed")

            created_after = storage.read_json(created)
            previous_after = storage.read_json(previous)
            self.assertEqual(created_after["metadata"]["asset_status"], "superseded")
            self.assertEqual(created_after["metadata"]["rollback_status"], "rolled_back")
            self.assertEqual(previous_after["metadata"]["asset_status"], "active_restore_candidate")

            compensation_ledgers = []
            for path in storage.list_json("runs"):
                data = storage.read_json(path)
                if data.get("type") == "cost_ledger" and data.get("content", {}).get("source_type") == "rollback_compensation":
                    compensation_ledgers.append(data)
            self.assertEqual(len(compensation_ledgers), 1)
            self.assertEqual(compensation_ledgers[0]["content"]["metadata"]["adjustment_amount"], -1.25)

            verification = verify_rollback_result(storage, result["path"])
            self.assertEqual(verification["verification"]["status"], "passed")
            self.assertGreaterEqual(verification["verification"]["check_count"], 3)

    def test_restore_previous_versions_marks_prior_version_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            project_id = "rollback-restore-project"
            previous = storage.write_asset_auto(
                DraftVersion(
                    title="Draft v1",
                    content={"draft_id": "draft-1", "version_index": 1, "chapter": 1, "text": "previous", "source_draft_id": "draft-1", "change_summary": "base", "status": "superseded"},
                    metadata={"project_id": project_id},
                )
            )
            created = storage.write_asset_auto(
                DraftVersion(
                    title="Draft v2",
                    content={"draft_id": "draft-1", "version_index": 2, "chapter": 1, "text": "bad", "source_draft_id": "draft-1", "change_summary": "bad", "status": "active"},
                    metadata={"project_id": project_id},
                )
            )
            transaction = create_operation_transaction(
                storage,
                operation="editor_patch",
                created_assets=[str(created.relative_to(storage.root))],
                previous_versions=[str(previous.relative_to(storage.root))],
                project_id=project_id,
            )

            plan = preview_operation_rollback(storage, transaction["path"], strategy="restore_previous_versions")
            result = apply_rollback_plan(storage, plan["path"], confirm=True)

            self.assertEqual(result["asset"]["content"]["verification"]["status"], "passed")
            previous_after = storage.read_json(previous)
            created_after = storage.read_json(created)
            self.assertEqual(previous_after["metadata"]["asset_status"], "active")
            self.assertEqual(previous_after["content"]["status"], "active")
            self.assertEqual(created_after["metadata"]["asset_status"], "superseded")


if __name__ == "__main__":
    unittest.main()
