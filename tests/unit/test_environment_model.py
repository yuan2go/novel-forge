from __future__ import annotations

import unittest
from pathlib import Path

from novel_forge.infrastructure.environment import (
    RuntimeControlLevel,
    RuntimeEnvironment,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.production_execution.security import execution_environment


class RuntimeEnvironmentTests(unittest.TestCase):
    def test_environment_has_one_typed_control_level_model(self) -> None:
        self.assertEqual(
            RuntimeEnvironment.VALIDATION.control_level,
            RuntimeControlLevel.CONTROLLED,
        )
        self.assertTrue(RuntimeEnvironment.PRODUCTION.controlled)
        self.assertTrue(RuntimeEnvironment.TEST.fixture_allowed)
        self.assertTrue(RuntimeEnvironment.DEVELOPMENT.fixture_allowed)

    def test_removed_provider_validation_environment_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "development, test, validation"):
            IndustrialSettings(root=Path("."), environment="provider-validation")

    def test_legacy_envelope_aliases_normalize_only_at_execution_boundary(self) -> None:
        self.assertIs(
            execution_environment("local"), RuntimeEnvironment.DEVELOPMENT
        )
        self.assertIs(
            execution_environment("operating_system"),
            RuntimeEnvironment.PRODUCTION,
        )
        with self.assertRaisesRegex(ValueError, "provider-validation"):
            execution_environment("provider-validation")

    def test_controlled_environments_require_postgresql_and_forbid_fixtures(self) -> None:
        for environment in ("validation", "production"):
            with self.subTest(environment=environment):
                with self.assertRaisesRegex(ValueError, "must be postgresql"):
                    IndustrialSettings(
                        root=Path("."),
                        environment=environment,
                        storage_authority="legacy_local",
                    )
                with self.assertRaisesRegex(ValueError, "forbids fixture MKAOS"):
                    IndustrialSettings(
                        root=Path("."),
                        environment=environment,
                        mkaos_fixture_activation_enabled=True,
                    )


if __name__ == "__main__":
    unittest.main()
