from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ProductionExecutionGatewayBoundaryTests(unittest.TestCase):
    def test_execution_plane_does_not_define_parallel_attempt_authority(self) -> None:
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                ROOT / "src/novel_forge/modules/production_execution"
            ).glob("*.py")
        ).lower()
        self.assertNotIn("create table execution_attempt", source)
        self.assertNotIn("class executionattempt", source)
        self.assertNotIn("execution_attempts", source)

    def test_scripted_backend_cannot_claim_real_provider_proof(self) -> None:
        source = (
            ROOT / "src/novel_forge/modules/production_execution/backends.py"
        ).read_text(encoding="utf-8")
        scripted = source.split("class ScriptedFixtureExecutionBackend", 1)[1].split(
            "class RemoteProviderExecutionBackend", 1
        )[0]
        self.assertIn('evidence["fixture_protocol_only"] = True', scripted)
        self.assertIn('evidence["real_model_call"] = False', scripted)
        self.assertIn('evidence["production_verified"] = False', scripted)
        self.assertIn("real_provider_validation_eligible=False", scripted)

    def test_remote_provider_backend_uses_only_provider_v2_protocol(self) -> None:
        source = (
            ROOT / "src/novel_forge/modules/production_execution/backends.py"
        ).read_text(encoding="utf-8")
        remote = source.split("class RemoteProviderExecutionBackend", 1)[1].split(
            "class CodexCliExecutionBackend", 1
        )[0]
        self.assertIn("ProviderAdapterV2", source)
        self.assertNotRegex(
            remote, r"\.(?:generate|analyze|review|revise)\s*\("
        )


if __name__ == "__main__":
    unittest.main()
