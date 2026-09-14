from __future__ import annotations

from .cost_routing import ModelCandidate, PricingSnapshot


DEEPSEEK_PRICING_SOURCE = "https://api-docs.deepseek.com/quick_start/pricing/"


def deepseek_candidates(*, available: bool) -> tuple[ModelCandidate, ...]:
    entries = (
        ("deepseek-flash", "low", "flash", ".3", ".006", "1.2"),
        ("deepseek-v4-pro", "high", "pro-high", "1.32", ".044", "3.96"),
        ("deepseek-v4-pro", "max", "pro-max", "1.32", ".044", "3.96"),
    )
    return tuple(
        ModelCandidate(
            candidate_id=f"deepseek:{model}:{reasoning}",
            provider="deepseek",
            model=model,
            reasoning=reasoning,
            tier=tier,
            capabilities=("structured_output", "text"),
            context_limit=1_000_000,
            output_limit=384_000,
            capability_version="deepseek-official-2026-09-14",
            available=available,
            availability_reason="" if available else "CREDENTIAL_NOT_CONFIGURED",
            pricing=PricingSnapshot(
                version=f"deepseek-2026-09-14-peak-upper-bound:{model}",
                effective_from="2026-09-14T00:00:00+00:00",
                effective_until="2026-10-14T00:00:00+00:00",
                input_miss_per_million=miss,
                input_hit_per_million=hit,
                output_per_million=output,
                source=DEEPSEEK_PRICING_SOURCE,
            ),
        )
        for model, reasoning, tier, miss, hit, output in entries
    )
