from __future__ import annotations

import sys
import unittest
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    suite = unittest.TestSuite()
    for pattern in (
        "test_authority_*_postgres.py",
        "test_command_kernel_*_postgres.py",
    ):
        suite.addTests(
            unittest.defaultTestLoader.discover(
                str(root / "tests" / "integration"),
                pattern=pattern,
                top_level_dir=str(root),
            )
        )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.skipped:
        for test, reason in result.skipped:
            print(f"CORE_POSTGRES_SKIP_FORBIDDEN: {test}: {reason}", file=sys.stderr)
        return 1
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
