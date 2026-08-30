from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from novel_forge.tools.implementation_tree_identity import (
    build_implementation_tree_identity,
    select_implementation_paths,
)


class ImplementationTreeIdentityTests(unittest.TestCase):
    def test_identity_is_deterministic_and_only_tracks_semantic_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            semantic_files = {
                "src/novel_forge/example.py": "VALUE = 1\n",
                "tests/unit/test_example.py": "def test_example(): pass\n",
                "scripts/check_example.py": "print('checked')\n",
                "config/capability_packs/example.json": '{"enabled":true}\n',
                "skills/example/SKILL.md": "# Example runtime skill\n",
                "architecture/manifests/example.yaml": '{"schema_version":"architecture-manifest.v1"}\n',
                ".github/workflows/ci.yml": "name: CI\n",
                "compose.authority-only.yml": "services: {}\n",
                "Dockerfile": "FROM scratch\n",
                "Makefile": "check:\n\ttrue\n",
                "pyproject.toml": "[project]\nname='example'\n",
            }
            for relative, content in semantic_files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            generated = root / "tests/__pycache__/test_example.pyc"
            generated.parent.mkdir(parents=True)
            generated.write_bytes(b"generated")
            report = root / "docs/generated-current-head.json"
            report.parent.mkdir(parents=True)
            report.write_text('{"run_id":"changes-every-run"}\n', encoding="utf-8")

            selected = select_implementation_paths(root)
            self.assertEqual(
                [path.relative_to(root).as_posix() for path in selected],
                sorted(semantic_files),
            )
            first = build_implementation_tree_identity(root)
            second = build_implementation_tree_identity(root)
            self.assertEqual(first, second)

            report.write_text('{"run_id":"new-run"}\n', encoding="utf-8")
            self.assertEqual(
                build_implementation_tree_identity(root)["implementation_tree_sha"],
                first["implementation_tree_sha"],
            )
            (root / "src/novel_forge/example.py").write_text(
                "VALUE = 2\n", encoding="utf-8"
            )
            self.assertNotEqual(
                build_implementation_tree_identity(root)["implementation_tree_sha"],
                first["implementation_tree_sha"],
            )

    def test_identity_scope_is_explicit_and_self_describing(self) -> None:
        root = Path(__file__).resolve().parents[2]
        identity = build_implementation_tree_identity(root)
        self.assertEqual(identity["schema_version"], "implementation-tree-identity.v2")
        self.assertEqual(identity["algorithm"], "sha256-canonical-file-records-v1")
        self.assertTrue(identity["implementation_tree_sha"].startswith("sha256:"))
        self.assertGreater(identity["path_count"], 0)
        self.assertIn("src/**", identity["scope"]["included"])
        self.assertIn("config/**", identity["scope"]["included"])
        self.assertIn("skills/**", identity["scope"]["included"])
        self.assertIn("docs/**", identity["scope"]["excluded"])
        self.assertNotIn(
            "docs/generated-coverage-baseline.json",
            identity["paths"],
        )


if __name__ == "__main__":
    unittest.main()
