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
                        "schema_version": "novel-forge.test-reality-manifest.v1",
                        "collections": ["tests/architecture"],
                        "classification_rules": [
                            {
                                "id": "fixture",
                                "patterns": ["tests/architecture/test_*.py"],
                                "classification": "QUALIFICATION_INFRASTRUCTURE",
                                "owner": "repository-qualification",
                                "capability": "collection",
                                "production_target": "src/novel_forge/tools/backend_qualification.py",
                                "qualification_role": "QUALIFICATION_MECHANICS_ONLY",
                                "proof_ceiling": "INFRASTRUCTURE_ONLY",
                            }
                        ],
                        "semantic_slice_policy": {},
                    }
                ),
                encoding="utf-8",
            )
            (manifest_dir / "backend-qualification-manifest.yaml").write_text(
                json.dumps(
                    {
                        "schema_version": "novel-forge.backend-qualification-manifest.v1",
                        "pytest_collections": [
                            {
                                "name": "architecture",
                                "paths": ["tests/architecture"],
                                "classification": "BACKEND_NON_POSTGRESQL",
                                "complete_collection": True,
                            }
                        ],
                        "semantic_slices": {},
                    }
                ),
                encoding="utf-8",
            )
            target = root / "src/novel_forge/tools/backend_qualification.py"
            target.parent.mkdir(parents=True)
            target.write_text("pass\n", encoding="utf-8")
            (test_dir / "test_broken_import.py").write_text(
                "raise ModuleNotFoundError('deterministic missing dependency')\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "cannot be discovered"):
                check_tests(root)


if __name__ == "__main__":
    unittest.main()
