from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.core.exception_policy import require_recoverable_asset_scan_error


class ExceptionPolicyTests(unittest.TestCase):
    def test_asset_scan_policy_suppresses_only_recoverable_data_errors(self):
        require_recoverable_asset_scan_error(json.JSONDecodeError("bad json", "{}", 0), context="unit")
        require_recoverable_asset_scan_error(ValueError("asset JSON must be an object"), context="unit")

        with self.assertRaisesRegex(RuntimeError, "unexpected exception during unit"):
            require_recoverable_asset_scan_error(PermissionError("permission denied"), context="unit")

        with self.assertRaisesRegex(RuntimeError, "unexpected exception during unit"):
            require_recoverable_asset_scan_error(ValueError("limit must be greater than zero"), context="unit")


if __name__ == "__main__":
    unittest.main()
