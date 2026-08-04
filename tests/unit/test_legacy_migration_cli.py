from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from novel_forge.cli import _authority_parser, main


class LegacyMigrationCliTests(unittest.TestCase):
    def test_verify_requires_an_explicit_bounded_level_vocabulary(self) -> None:
        parser = _authority_parser()
        parsed = parser.parse_args(
            [
                "authority-verify-migration",
                "--migration-run-id",
                "run-1",
                "--required-level",
                "DOMAIN_NATIVE",
            ]
        )

        self.assertEqual(parsed.required_level, "DOMAIN_NATIVE")

    def test_dry_run_does_not_require_database_or_mutate_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data" / "materials").mkdir(parents=True)
            source = root / "data" / "materials" / "one.json"
            source.write_text(
                json.dumps(
                    {"id": "one", "type": "material_card", "project_id": "p1"}
                ),
                encoding="utf-8",
            )
            before = source.read_bytes()
            output = StringIO()
            previous = os.environ.pop("NOVEL_FORGE_DATABASE_URL", None)
            try:
                with redirect_stdout(output):
                    code = main(["authority-import-legacy", "--root", str(root), "--dry-run"])
            finally:
                if previous is not None:
                    os.environ["NOVEL_FORGE_DATABASE_URL"] = previous
            after = source.read_bytes()

        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["mode"], "DRY_RUN")
        self.assertFalse(payload["production_mutation_performed"])
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
