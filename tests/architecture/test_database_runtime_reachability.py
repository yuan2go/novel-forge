from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
ALLOWED_DIRECT_CONNECTS = {
    Path("src/novel_forge/storage/migrations/runner.py"),
    Path("src/novel_forge/storage/postgres.py"),
}


class DatabaseRuntimeReachabilityTests(unittest.TestCase):
    def test_authority_business_code_does_not_open_direct_psycopg_connections(self) -> None:
        violations: list[str] = []
        for path in sorted((ROOT / "src/novel_forge").rglob("*.py")):
            relative = path.relative_to(ROOT)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                function = node.func
                if (
                    isinstance(function, ast.Attribute)
                    and isinstance(function.value, ast.Name)
                    and function.value.id == "psycopg"
                    and function.attr == "connect"
                    and relative not in ALLOWED_DIRECT_CONNECTS
                ):
                    violations.append(f"{relative}:{node.lineno}")
        self.assertEqual(violations, [])

    def test_direct_connection_allowlist_is_exact_and_present(self) -> None:
        self.assertEqual(
            ALLOWED_DIRECT_CONNECTS,
            {
                Path("src/novel_forge/storage/migrations/runner.py"),
                Path("src/novel_forge/storage/postgres.py"),
            },
        )
        for relative in ALLOWED_DIRECT_CONNECTS:
            self.assertTrue((ROOT / relative).is_file())


if __name__ == "__main__":
    unittest.main()
