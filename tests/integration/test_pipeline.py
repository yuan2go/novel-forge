from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.workflows import pipeline
from novel_forge.storage.local import LocalStorage


class PipelineTests(unittest.TestCase):
    def test_sample_pipeline_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_path = pipeline.run_pipeline(root, sample=True)
            self.assertTrue(run_path.exists())
            ok, errors = pipeline.validate_project(root)
            # Temp pipeline roots intentionally do not contain full docs, so asset validation is checked directly.
            asset_errors = [
                error
                for error in errors
                if not error.startswith("missing documentation file") and not error.startswith("missing skills directory")
            ]
            self.assertEqual(asset_errors, [])
            self.assertTrue((root / "examples" / "sample_outputs" / "pipeline-summary.json").exists())
            storage = LocalStorage(root)
            run_assets = [storage.read_asset(path) for path in storage.list_json("runs")]
            task_statuses = [asset for asset in run_assets if asset.type == "task_status"]
            workflow_runs = [asset for asset in run_assets if asset.type == "workflow_run"]
            self.assertEqual(workflow_runs[-1].content["status"], "completed")
            self.assertGreaterEqual(len(workflow_runs[-1].content["run_log"]), 54)
            self.assertEqual(workflow_runs[-1].content["recovery_instruction"], "")
            self.assertGreaterEqual(len(task_statuses), 54)
            self.assertIn("pending", {asset.content["status"] for asset in task_statuses})
            self.assertIn("running", {asset.content["status"] for asset in task_statuses})
            self.assertIn("completed", {asset.content["status"] for asset in task_statuses})
            workspace_assets = [storage.read_asset(path) for path in storage.list_json("workspaces")]
            self.assertEqual(len(workspace_assets), 1)
            self.assertEqual(workspace_assets[0].metadata["status"], "updated")
            self.assertEqual(workspace_assets[0].metadata["chapter_count"], 1)

            counts_after_first_run = storage.counts()
            first_summary = storage.read_json("examples/sample_outputs/pipeline-summary.json")
            self.assertTrue((root / first_summary["copied_final_output"]).exists())
            second_run_path = pipeline.run_pipeline(root, sample=True)
            self.assertTrue(second_run_path.exists())
            self.assertEqual(storage.counts(), counts_after_first_run)
            second_summary = storage.read_json("examples/sample_outputs/pipeline-summary.json")
            self.assertGreater(len(second_summary["cleaned_previous_sample_paths"]), 0)


if __name__ == "__main__":
    unittest.main()
