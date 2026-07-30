from __future__ import annotations

import unittest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.plan_change_authority.domain import (
    PlanChangeRisk,
    classify_plan_change_risk,
    require_approvable_scope,
    semantic_plan_diff,
)


class PlanChangeAuthorityDomainTests(unittest.TestCase):
    def test_semantic_diff_detects_field_changes(self) -> None:
        changes = semantic_plan_diff(
            {
                "objective": "reach the city",
                "ending_contract": "choose duty",
                "required_events": ["cross the gate"],
            },
            {
                "objective": "save the city",
                "ending_contract": "choose agency",
                "required_events": ["open the gate"],
            },
        )
        self.assertEqual(
            {change.change_type for change in changes},
            {
                "OBJECTIVE_CHANGED",
                "ENDING_CONTRACT_CHANGED",
                "REQUIRED_EVENT_CHANGED",
            },
        )
        self.assertEqual(
            classify_plan_change_risk(
                changes, target_execution_scope="PLANNED"
            ),
            PlanChangeRisk.HIGH,
        )

    def test_executed_plan_is_retcon_only(self) -> None:
        with self.assertRaisesRegex(
            KernelError, "EXECUTED_PLAN_RETCON_ONLY"
        ):
            require_approvable_scope("EXECUTED")


if __name__ == "__main__":
    unittest.main()
