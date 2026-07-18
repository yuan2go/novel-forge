from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal

from novel_forge.modules.command_kernel.errors import KernelError


@dataclass(frozen=True, slots=True)
class CanonReextractionPolicy:
    policy_version: str = "canon-reextraction-policy-v1"
    maximum_generations: int = 3
    maximum_total_cost: Decimal = Decimal("5.00")
    generation_timeout_seconds: int = 900
    same_digest_limit: int = 2
    no_progress_limit: int = 2
    operator_escalation_after: int = 2

    def validate(self) -> None:
        if (
            self.maximum_generations < 2
            or self.maximum_total_cost < 0
            or self.generation_timeout_seconds <= 0
            or self.same_digest_limit <= 0
            or self.no_progress_limit <= 0
            or self.operator_escalation_after <= 0
        ):
            raise KernelError(
                "CANON_REEXTRACTION_POLICY_INVALID",
                "Canon re-extraction policy contains an invalid bound",
            )

    def snapshot(self) -> dict[str, object]:
        self.validate()
        return {**asdict(self), "maximum_total_cost": str(self.maximum_total_cost)}

    def require_generation(self, generation: int) -> None:
        self.validate()
        if generation > self.maximum_generations:
            raise KernelError(
                "CANON_REEXTRACTION_GENERATION_CAP",
                "Canon re-extraction exceeded the frozen generation policy",
            )


__all__ = ["CanonReextractionPolicy"]
