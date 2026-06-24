from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.storage.local import LocalStorage
from novel_forge.workflows import pipeline
from novel_forge.workflows.status import execute_task


class TaskStatusTests(unittest.TestCase):
    def test_execute_task_records_failed_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = pipeline.ensure_project(root)

            def fail():
                raise RuntimeError("planned failure")

            with self.assertRaises(RuntimeError):
                execute_task(storage, "run-test", "failing-step", ["input.json"], fail)

            assets = [storage.read_asset(path) for path in storage.list_json("runs")]
            failed = [asset for asset in assets if asset.type == "task_status" and asset.content["status"] == "failed"]
            self.assertEqual(len(failed), 1)
            self.assertEqual(failed[0].content["step"], "failing-step")
            self.assertIn("RuntimeError: planned failure", failed[0].content["error_message"])
            ok, errors = pipeline.validate_project(root)
            asset_errors = [
                error
                for error in errors
                if not error.startswith("missing documentation file") and not error.startswith("missing skills directory")
            ]
            self.assertTrue(ok or not asset_errors)
            self.assertEqual(asset_errors, [])

    def test_pipeline_failure_records_failed_workflow_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_clean = pipeline.clean

            def fail_clean(*_args, **_kwargs):
                raise RuntimeError("clean failed")

            try:
                pipeline.clean = fail_clean
                with self.assertRaises(RuntimeError):
                    pipeline.run_pipeline(root, sample=True)
            finally:
                pipeline.clean = original_clean

            storage = LocalStorage(root)
            assets = [storage.read_asset(path) for path in storage.list_json("runs")]
            failed_runs = [asset for asset in assets if asset.type == "workflow_run" and asset.content["status"] == "failed"]
            failed_tasks = [asset for asset in assets if asset.type == "task_status" and asset.content["status"] == "failed"]
            self.assertEqual(len(failed_runs), 1)
            self.assertEqual(failed_tasks[-1].content["step"], "clean")
            self.assertGreaterEqual(len(failed_runs[0].content["run_log"]), 4)
            self.assertIn("Recover by inspecting step 'clean'", failed_runs[0].content["recovery_instruction"])
            self.assertIn("RuntimeError: clean failed", failed_runs[0].content["error_message"])
            recovery_path = root / failed_runs[0].content["recovery_path"]
            self.assertTrue(recovery_path.exists())
            self.assertIn("clean", recovery_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
