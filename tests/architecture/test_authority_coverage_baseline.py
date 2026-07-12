from __future__ import annotations

import json
import unittest
from pathlib import Path

from novel_forge.tools.authority_coverage_manifest import build_manifest


class AuthorityCoverageBaselineTests(unittest.TestCase):
    def test_checked_in_baseline_matches_current_head_scan(self) -> None:
        root = Path(__file__).resolve().parents[2]
        baseline = json.loads((root / "docs/reports/postgresql-authority-coverage-baseline.json").read_text(encoding="utf-8"))
        current = build_manifest(root, generated_at=baseline["generated_at"])
        self.assertEqual(current["git_sha"], baseline["git_sha"])
        self.assertEqual(current["artifact_hash"], baseline["artifact_hash"])
