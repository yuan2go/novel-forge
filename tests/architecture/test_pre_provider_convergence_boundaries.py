from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUTHORITY_ROOTS = (
    ROOT / "src/novel_forge/modules/chapter_authority",
    ROOT / "src/novel_forge/modules/content_authority",
    ROOT / "src/novel_forge/modules/production_preparation",
    ROOT / "src/novel_forge/modules/chapter_quality_authority",
    ROOT / "src/novel_forge/modules/provider_control",
)


class PreProviderConvergenceBoundaryTests(unittest.TestCase):
    def test_authority_modules_do_not_import_local_storage(self) -> None:
        violations: list[str] = []
        for root in AUTHORITY_ROOTS:
            for path in root.rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and (
                        node.module or ""
                    ).startswith("novel_forge.storage.local"):
                        violations.append(str(path.relative_to(ROOT)))
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name.startswith("novel_forge.storage.local"):
                                violations.append(str(path.relative_to(ROOT)))
        self.assertEqual(violations, [])

    def test_authority_source_cannot_hardcode_verified_fixture_maturity(self) -> None:
        violations: list[str] = []
        for root in AUTHORITY_ROOTS:
            for path in root.rglob("*.py"):
                text = path.read_text(encoding="utf-8")
                for forbidden in (
                    '"production_verified": True',
                    '"real_provider_proven": True',
                    '"longform_proven": True',
                ):
                    if forbidden in text:
                        violations.append(f"{path.relative_to(ROOT)}:{forbidden}")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
