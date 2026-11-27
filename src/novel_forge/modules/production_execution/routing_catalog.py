from __future__ import annotations

from datetime import datetime, timezone

from .cost_routing import ModelCandidate, PricingSnapshot


DEEPSEEK_PRICING_SOURCE = "https://api-docs.deepseek.com/quick_start/pricing/"
DEEPSEEK_MODEL_REVISIONS = {
    "deepseek-flash": "DeepSeek-V4.1-Flash",
    "deepseek-v4-pro": "DeepSeek-V4-Pro-0813",
}


def deepseek_pricing_period(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("DEEPSEEK_PRICING_TIMEZONE_REQUIRED")
    at = value.astimezone(timezone.utc)
    if at.weekday() < 5 and (1 <= at.hour < 4 or 6 <= at.hour < 10):
        return "PEAK"
    return "OFF_PEAK"


def deepseek_expected_price_multiplier(value: datetime) -> str:
    return "1" if deepseek_pricing_period(value) == "PEAK" else "0.5"


def deepseek_model_revision(model: str) -> str:
    try:
        return DEEPSEEK_MODEL_REVISIONS[model]
    except KeyError as exc:
        raise ValueError("DEEPSEEK_MODEL_REVISION_UNKNOWN") from exc


def deepseek_model_routing_available(model: str) -> bool:
    deepseek_model_revision(model)
    return True


def deepseek_candidates(
    *, available: bool, estimated_at: datetime | None = None
) -> tuple[ModelCandidate, ...]:
    estimated_price_multiplier = (
        deepseek_expected_price_multiplier(estimated_at)
        if estimated_at is not None
        else "1"
    )
    entries = (
        (
            "deepseek-flash",
            "2026-09-10T04:00:00+00:00",
            "low",
            "flash",
            ".3",
            ".006",
            "1.2",
        ),
        (
            "deepseek-v4-pro",
            "2026-08-16T16:00:00+00:00",
            "high",
            "pro-high",
            "1.32",
            ".044",
            "3.96",
        ),
        (
            "deepseek-v4-pro",
            "2026-08-16T16:00:00+00:00",
            "max",
            "pro-max",
            "1.32",
            ".044",
            "3.96",
        ),
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
            capability_version="deepseek-official-2026-09-16",
            model_revision=deepseek_model_revision(model),
            estimated_price_multiplier=estimated_price_multiplier,
            available=available and deepseek_model_routing_available(model),
            availability_reason="" if available else "CREDENTIAL_NOT_CONFIGURED",
            pricing=PricingSnapshot(
                version=f"deepseek-scheduled-peak-ceiling:{effective_from}:{model}",
                effective_from=effective_from,
                effective_until="9999-12-31T23:59:59+00:00",
                input_miss_per_million=miss,
                input_hit_per_million=hit,
                output_per_million=output,
                source=DEEPSEEK_PRICING_SOURCE,
            ),
        )
        for (
            model,
            effective_from,
            reasoning,
            tier,
            miss,
            hit,
            output,
        ) in entries
    )
