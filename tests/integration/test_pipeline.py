from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.workflows import pipeline


class PipelineTests(unittest.TestCase):
    def test_sample_pipeline_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_path = pipeline.run_pipeline(root, sample=True)
            self.assertTrue(run_path.exists())
            ok, errors = pipeline.validate_project(root)
            # Temp pipeline roots intentionally do not contain full docs, so asset validation is checked directly.
            asset_errors = [error for error in errors if not error.startswith("missing documentation file")]
            self.assertEqual(asset_errors, [])
            self.assertTrue((root / "examples" / "sample_outputs" / "pipeline-summary.json").exists())


if __name__ == "__main__":
    unittest.main()
