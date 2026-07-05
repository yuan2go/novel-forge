from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.schemas import BaseAsset, NodeRun, WorkflowRun
from novel_forge.storage.local import LocalStorage


class AssetScanSeamTests(unittest.TestCase):
    def test_core_asset_scan_skips_corrupt_json_but_raises_unexpected_errors(self):
        from novel_forge.core.asset_scan import iter_json_objects, read_json_for_scan

        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            good_path = storage.write_asset("runs", BaseAsset(type="gate_result", title="Good", content={"status": "passed"}))
            bad_path = storage.data_dir("runs") / "bad.json"
            bad_path.write_text("{not json", encoding="utf-8")

            rows = list(iter_json_objects(storage, "runs", context="unit scan"))

            self.assertEqual([row["id"] for _, row in rows], [storage.read_json(good_path)["id"]])
            self.assertEqual(read_json_for_scan(storage, bad_path, context="unit scan"), {})

            broken = _PermissionStorage(tmp, blocked_name=good_path.name)
            with self.assertRaisesRegex(RuntimeError, "unexpected exception during unit scan"):
                list(iter_json_objects(broken, "runs", context="unit scan"))

    def test_mkaos_asset_index_finds_and_lists_assets_with_scan_policy(self):
        from novel_forge.modules.mkaos.asset_index import find_asset, list_assets

        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            asset_path = storage.write_asset(
                "knowledge",
                BaseAsset(
                    type="knowledge_card",
                    title="Risk seam card",
                    content={"project_id": "mkaos-seam-p", "risk_level": "medium"},
                    metadata={"project_id": "mkaos-seam-p", "mkaos": True},
                ),
            )
            (storage.data_dir("knowledge") / "bad.json").write_text("{bad", encoding="utf-8")
            asset = storage.read_json(asset_path)

            found_path, found = find_asset(storage, asset["id"], asset_type="knowledge_card", categories=["knowledge"])
            rows = list_assets(storage, "knowledge", "knowledge_card", project_id="mkaos-seam-p", mkaos_only=True)

            self.assertEqual(found_path, asset_path)
            self.assertEqual(found["id"], asset["id"])
            self.assertEqual([row["id"] for row in rows], [asset["id"]])

            broken = _PermissionStorage(tmp, blocked_name=asset_path.name)
            with self.assertRaisesRegex(RuntimeError, "unexpected exception during mkaos asset scan"):
                list_assets(broken, "knowledge", "knowledge_card")

    def test_product_asset_index_supports_project_binding_and_asset_id_lookup(self):
        from novel_forge.api.services.product_asset_index import find_asset_binding, asset_path_by_id

        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            path = storage.write_asset(
                "platforms",
                BaseAsset(
                    type="platform_profile",
                    title="Platform profile",
                    content={"platform_id": "local"},
                    metadata={"project_id": "product-seam-p"},
                ),
            )
            asset = storage.read_json(path)

            by_id = find_asset_binding(storage, "platform_profile", asset["id"])
            by_path = find_asset_binding(storage, "platform_profile", str(path.relative_to(storage.root)))

            self.assertEqual(by_id, {"id": asset["id"], "path": str(path.relative_to(storage.root))})
            self.assertEqual(by_path, by_id)
            self.assertEqual(asset_path_by_id(storage, "platforms", asset["id"]), path)

            broken = _PermissionStorage(tmp, blocked_name=path.name)
            with self.assertRaisesRegex(RuntimeError, "unexpected exception during product asset binding scan"):
                find_asset_binding(broken, "platform_profile", asset["id"])

    def test_workflow_query_lists_runs_and_raises_unexpected_scan_errors(self):
        from novel_forge.modules.workflow_nodes import list_node_runs, list_workflow_runs

        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            run_path = storage.write_asset(
                "runs",
                NodeRun(
                    title="Node run",
                    content={
                        "run_id": "run-1",
                        "node_id": "node-1",
                        "node_type": "task",
                        "operation": "unit",
                        "status": "succeeded",
                        "input_assets": [],
                        "output_assets": [],
                    },
                    metadata={"project_id": "workflow-seam-p"},
                ),
            )
            storage.write_asset(
                "runs",
                WorkflowRun(
                    title="Workflow run",
                    content={"run_id": "workflow-run-1", "status": "completed", "blocked": {}, "trace": {}},
                    metadata={"project_id": "workflow-seam-p"},
                ),
            )
            (storage.data_dir("runs") / "bad.json").write_text("{bad", encoding="utf-8")

            self.assertEqual(list_node_runs(storage, project_id="workflow-seam-p")[0]["path"], str(run_path.relative_to(storage.root)))
            self.assertEqual(list_workflow_runs(storage, project_id="workflow-seam-p")[0]["run_id"], "workflow-run-1")

            broken = _PermissionStorage(tmp, blocked_name=run_path.name)
            with self.assertRaisesRegex(RuntimeError, "unexpected exception during workflow node run list"):
                list_node_runs(broken, project_id="workflow-seam-p")


class _PermissionStorage(LocalStorage):
    def __init__(self, root: str | Path, *, blocked_name: str) -> None:
        super().__init__(root)
        self.blocked_name = blocked_name

    def read_json(self, path: str | Path):
        if Path(path).name == self.blocked_name:
            raise PermissionError("permission denied")
        return super().read_json(path)


if __name__ == "__main__":
    unittest.main()
