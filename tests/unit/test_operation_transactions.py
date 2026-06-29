from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.operation_transactions import apply_rollback_plan, coordinate_runtime_rollback, create_operation_transaction, preview_operation_rollback, verify_rollback_result
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

    def test_physical_restore_quarantines_created_assets_and_restores_updated_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            project_id = "rollback-physical-project"
            previous = storage.write_asset_auto(
                DraftVersion(
                    title="Draft previous",
                    content={"draft_id": "draft-physical", "version_index": 1, "chapter": 1, "text": "known good", "source_draft_id": "draft-physical", "change_summary": "base", "status": "active"},
                    metadata={"project_id": project_id},
                )
            )
            updated = storage.write_asset_auto(
                DraftVersion(
                    title="Draft updated",
                    content={"draft_id": "draft-physical", "version_index": 2, "chapter": 1, "text": "bad edit", "source_draft_id": "draft-physical", "change_summary": "bad", "status": "active"},
                    metadata={"project_id": project_id},
                )
            )
            created = storage.write_asset_auto(
                DraftVersion(
                    title="Created side output",
                    content={"draft_id": "draft-side", "version_index": 1, "chapter": 1, "text": "side effect", "source_draft_id": "draft-side", "change_summary": "side", "status": "active"},
                    metadata={"project_id": project_id},
                )
            )
            transaction = create_operation_transaction(
                storage,
                operation="multi_asset_revision",
                created_assets=[str(created.relative_to(storage.root))],
                updated_assets=[str(updated.relative_to(storage.root))],
                previous_versions=[str(previous.relative_to(storage.root))],
                indexes_touched=["novel_kg", "pgvector"],
                project_id=project_id,
                trace={"trace_id": "trace-physical-rollback"},
            )

            plan = preview_operation_rollback(storage, transaction["path"], strategy="physical_restore")
            self.assertEqual(plan["asset"]["content"]["rollback_status"], "available")
            self.assertIn("quarantine_asset_file", {item["action"] for item in plan["asset"]["content"]["actions"]})
            self.assertIn("restore_asset_file", {item["action"] for item in plan["asset"]["content"]["actions"]})
            result = apply_rollback_plan(storage, plan["path"], confirm=True, actor="unit-test")

            self.assertEqual(result["asset"]["content"]["verification"]["status"], "passed")
            self.assertFalse(created.exists())
            quarantine_actions = [item for item in result["asset"]["content"]["applied_actions"] if item["action"] == "quarantine_asset_file"]
            restore_actions = [item for item in result["asset"]["content"]["applied_actions"] if item["action"] == "restore_asset_file"]
            self.assertTrue(resolve := quarantine_actions[0]["quarantine_path"])
            self.assertTrue((storage.root / resolve).exists())
            self.assertTrue((storage.root / restore_actions[0]["backup_path"]).exists())
            restored = storage.read_json(updated)
            self.assertEqual(restored["content"]["text"], "known good")
            self.assertEqual(restored["metadata"]["rollback_status"], "physically_restored")

    def test_coordinate_runtime_rollback_previews_and_applies_multiple_transactions(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            project_id = "rollback-coordinate-project"
            created_a = storage.write_asset_auto(
                DraftVersion(
                    title="Created A",
                    content={"draft_id": "coord-a", "version_index": 1, "chapter": 1, "text": "bad a", "source_draft_id": "coord-a", "change_summary": "bad", "status": "active"},
                    metadata={"project_id": project_id},
                )
            )
            created_b = storage.write_asset_auto(
                DraftVersion(
                    title="Created B",
                    content={"draft_id": "coord-b", "version_index": 1, "chapter": 2, "text": "bad b", "source_draft_id": "coord-b", "change_summary": "bad", "status": "active"},
                    metadata={"project_id": project_id},
                )
            )
            tx_a = create_operation_transaction(
                storage,
                operation="workflow_node_draft",
                workflow_run_id="workflow-1",
                created_assets=[str(created_a.relative_to(storage.root))],
                indexes_touched=["novel_kg"],
                project_id=project_id,
            )
            tx_b = create_operation_transaction(
                storage,
                operation="agent_revision",
                agent_run_id="agent-1",
                created_assets=[str(created_b.relative_to(storage.root))],
                indexes_touched=["pgvector"],
                project_id=project_id,
            )

            preview = coordinate_runtime_rollback(
                storage,
                transaction_paths=[tx_a["path"], tx_b["path"]],
                strategy="supersede_outputs",
                confirm=False,
                project_id=project_id,
            )
            applied = coordinate_runtime_rollback(
                storage,
                transaction_paths=[tx_a["path"], tx_b["path"]],
                strategy="supersede_outputs",
                confirm=True,
                project_id=project_id,
            )

            self.assertEqual(preview["asset"]["type"], "rollback_coordination_report")
            self.assertEqual(preview["verification"]["status"], "previewed")
            self.assertEqual(applied["verification"]["status"], "applied")
            self.assertEqual(applied["verification"]["result_count"], 2)
            self.assertEqual(applied["verification"]["domains"]["workflow_transaction_count"], 1)
            self.assertEqual(applied["verification"]["domains"]["agent_transaction_count"], 1)
            self.assertEqual(storage.read_json(created_a)["metadata"]["rollback_status"], "rolled_back")
            self.assertEqual(storage.read_json(created_b)["metadata"]["rollback_status"], "rolled_back")

    def test_coordinate_runtime_rollback_does_not_partially_apply_when_any_plan_is_unsafe(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            project_id = "rollback-coordinate-unsafe"
            created = storage.write_asset_auto(
                DraftVersion(
                    title="Created survivor",
                    content={"draft_id": "coord-safe", "version_index": 1, "chapter": 1, "text": "should remain active", "source_draft_id": "coord-safe", "change_summary": "safe", "status": "active"},
                    metadata={"project_id": project_id},
                )
            )
            safe_tx = create_operation_transaction(
                storage,
                operation="workflow_node_draft",
                workflow_run_id="workflow-safe",
                created_assets=[str(created.relative_to(storage.root))],
                project_id=project_id,
            )
            unsafe_tx = create_operation_transaction(
                storage,
                operation="agent_revision",
                agent_run_id="agent-unsafe",
                created_assets=["data/drafts/missing-created-output.json"],
                project_id=project_id,
            )

            coordinated = coordinate_runtime_rollback(
                storage,
                transaction_paths=[safe_tx["path"], unsafe_tx["path"]],
                strategy="supersede_outputs",
                confirm=True,
                project_id=project_id,
            )

            self.assertEqual(coordinated["verification"]["status"], "unsafe")
            self.assertEqual(coordinated["verification"]["result_count"], 0)
            self.assertTrue(coordinated["verification"]["unsafe_reasons"])
            self.assertNotEqual(storage.read_json(created).get("metadata", {}).get("rollback_status"), "rolled_back")


if __name__ == "__main__":
    unittest.main()
