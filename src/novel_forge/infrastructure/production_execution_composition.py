from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from novel_forge.infrastructure.environment import RuntimeEnvironment
from novel_forge.modules.chapter_authority.execution_gateway import (
    ProductionExecutionGatewayExternalEffectAdapter,
)
from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapter,
)


@dataclass(frozen=True, slots=True)
class ProductionExecutionComposition:

    gateway: ProductionExecutionGatewayExternalEffectAdapter
    object_store: ExternalEffectAdapter
    source_object_reader: Any
    runtime_environment: RuntimeEnvironment
    max_cost_per_call: str
    shared_budget_caps: Mapping[str, str]
    chapter_total_budget_cap: str = ""

    def budget_caps(self, *, include_chapter_total: bool = False) -> dict[str, str]:
        caps = dict(self.shared_budget_caps)
        if include_chapter_total and self.chapter_total_budget_cap:
            caps["chapter_total"] = self.chapter_total_budget_cap
        return caps

    @property
    def external_effect_adapters(self) -> dict[str, ExternalEffectAdapter]:
        return {
            self.gateway.provider: self.gateway,
            self.object_store.provider: self.object_store,
        }

    def close(self) -> None:
        self.gateway.close_sessions()


__all__ = ["ProductionExecutionComposition"]
