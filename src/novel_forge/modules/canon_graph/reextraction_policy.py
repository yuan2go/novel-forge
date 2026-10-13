from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal

from novel_forge.modules.command_kernel.errors import KernelError


@dataclass(frozen=True, slots=True)
class CanonReextractionPolicy:
    policy_version: str = "canon-reextraction-policy-v2"
    maximum_generations: int | None = None
    maximum_total_cost: Decimal | None = None
    generation_timeout_seconds: int | None = None
    same_digest_limit: int = 2
    no_progress_limit: int = 2
    operator_escalation_after: int = 2

    def validate(self) -> None:
        if (
            self.policy_version not in {"canon-reextraction-policy-v1", "canon-reextraction-policy-v2"}
            or self.maximum_generations is not None and self.maximum_generations < 2
            or self.maximum_total_cost is not None and self.maximum_total_cost < 0
            or self.generation_timeout_seconds is not None and self.generation_timeout_seconds <= 0
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
        return {**asdict(self), "maximum_total_cost": str(self.maximum_total_cost) if self.maximum_total_cost is not None else None}

    def require_generation(self, generation: int) -> None:
        self.validate()
        if type(generation) is not int or generation < 2:
            raise KernelError(
                "CANON_REEXTRACTION_GENERATION_INVALID",
                "Canon re-extraction requires an append-only generation identity",
            )


__all__ = ["CanonReextractionPolicy"]
