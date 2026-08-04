from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from novel_forge.tools.architecture_manifest import check_tests


class ArchitectureManifestTestCollectionTests(unittest.TestCase):
    def test_import_failure_is_not_counted_as_a_test_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_dir = root / "architecture" / "manifests"
            test_dir = root / "tests" / "architecture"
            manifest_dir.mkdir(parents=True)
            test_dir.mkdir(parents=True)
            (manifest_dir / "test-manifest.yaml").write_text(
                json.dumps(
                    {
                        "schema_version": "architecture-manifest.v1",
                        "collections": [
                            {
                                "name": "architecture",
                                "start_dir": "tests/architecture",
                                "pattern": "test_*.py",
                                "minimum_count": 1,
                            }
                        ],
                        "required_modules": [],
                    }
                ),
                encoding="utf-8",
            )
            (test_dir / "test_broken_import.py").write_text(
                "raise ModuleNotFoundError('deterministic missing dependency')\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "cannot be discovered"):
                check_tests(root)


if __name__ == "__main__":
    unittest.main()
