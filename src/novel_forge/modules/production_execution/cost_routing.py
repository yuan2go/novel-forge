from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
from statistics import mean, pstdev
from typing import Any, Mapping, Sequence


def snapshot_hash(value: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                value,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()
    )


@dataclass(frozen=True)
class TaskPolicy:
    risk: str
    quality_floor: float
    minimum_samples: int
    confidence_penalty: float
    max_attempts: int = 4
    max_escalations: int = 1
    quality_metric: str = "CALIBRATED_SCORE"

    def __post_init__(self) -> None:
        if self.risk not in {"LOW", "MEDIUM", "HIGH"}:
            raise ValueError("ROUTING_RISK_INVALID")
        if not 0 < self.quality_floor <= 1 or not 0 <= self.confidence_penalty <= 1:
            raise ValueError("ROUTING_QUALITY_POLICY_INVALID")
        if min(self.minimum_samples, self.max_escalations) < 0 or self.max_attempts < 1:
            raise ValueError("ROUTING_CHAIN_POLICY_INVALID")
        if self.quality_metric not in {"CALIBRATED_SCORE", "DOMAIN_GATE_ACCEPTANCE"}:
            raise ValueError("ROUTING_QUALITY_METRIC_INVALID")


QUALITY_POLICIES = {
    "LOW": TaskPolicy("LOW", 0.60, 3, 0.10),
    "MEDIUM": TaskPolicy("MEDIUM", 0.75, 8, 0.15),
    "HIGH": TaskPolicy("HIGH", 0.85, 20, 0.20),
}
TASK_TAXONOMY = {
    **dict.fromkeys(
        (
            "classification",
            "metadata",
            "tagging",
            "retrieval_query",
            "summary",
            "fact_candidate",
            "source.content.classify",
            "retrieval_query_expansion",
        ),
        "LOW",
    ),
    **dict.fromkeys(
        (
            "deconstruction",
            "knowledge_extraction",
            "character_analysis",
            "relationship_analysis",
            "world_candidates.generate",
            "world_candidates.evaluate",
            "chapter_plan.generate",
            "chapter_group_plan.generate",
            "memo",
            "canon_extraction",
            "review",
            "revision",
            "rereview",
            "draft",
            "source.deconstruction.observe",
            "source.mkaos.extract",
            "agent_session",
            "quality_structural",
            "quality_commercial",
            "quality_source_originality",
            "quality_platform",
            "reader_outcome",
        ),
        "MEDIUM",
    ),
    **dict.fromkeys(
        (
            "book_plan.generate",
            "volume_plan.generate",
            "arc_plan.generate",
            "core_world_rules",
            "core_character_arc",
            "critical_chapter",
            "climax",
            "major_reversal",
            "cross_volume_repair",
            "quality_longform",
            "narrative_semantic_evaluation",
            "canon_support",
            "canon_high_impact_conflict",
            "creative_foundation.generate",
            "theme.generate",
            "ending.generate",
            "reader_promise.generate",
            "world.generate",
            "character.generate",
        ),
        "HIGH",
    ),
    **dict.fromkeys(
        (
            "creative.candidates.generate",
            "theme.candidates.generate",
            "ending.intent.generate",
            "reader.promise.generate",
            "world.design.generate",
            "character.cast.generate",
        ),
        "HIGH",
    ),
}
POLICY_VERSION = "quality-constrained-routing.v3"


def task_policy(task_type: str, risk: str = "", quality_floor: float = 0) -> TaskPolicy:
    if task_type not in TASK_TAXONOMY:
        raise ValueError("ROUTING_TASK_POLICY_REQUIRED:" + task_type)
    default = TASK_TAXONOMY[task_type]
    ranks = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    selected = risk or default
    if selected not in ranks or ranks[selected] < ranks[default]:
        raise ValueError("ROUTING_RISK_DOWNGRADE_FORBIDDEN")
    policy = QUALITY_POLICIES[selected]
    return TaskPolicy(
        selected,
        max(policy.quality_floor, quality_floor),
        policy.minimum_samples,
        policy.confidence_penalty,
        policy.max_attempts,
        policy.max_escalations,
        "DOMAIN_GATE_ACCEPTANCE"
        if task_type.endswith(".generate")
        or task_type == "source.deconstruction.observe"
        else "CALIBRATED_SCORE",
    )


@dataclass(frozen=True)
class PricingSnapshot:
    version: str
    effective_from: str
    effective_until: str
    input_miss_per_million: str
    input_hit_per_million: str
    output_per_million: str
    currency: str = "USD"
    source: str = ""
    accounting_basis: str = "PRICED"

    def __post_init__(self) -> None:
        if (
            not self.version
            or not self.source
            or self.accounting_basis not in {"PRICED", "ACCOUNT_ENTITLEMENT"}
        ):
            raise ValueError("ROUTING_PRICING_IDENTITY_REQUIRED")
        for value in (
            self.input_miss_per_million,
            self.input_hit_per_million,
            self.output_per_million,
        ):
            amount = Decimal(value)
            if not amount.is_finite() or amount < 0:
                raise ValueError("ROUTING_PRICE_INVALID")
        if Decimal(self.input_hit_per_million) > Decimal(self.input_miss_per_million):
            raise ValueError("ROUTING_CACHE_PRICE_INVALID")
        for value in (self.effective_from, self.effective_until):
            if datetime.fromisoformat(value).tzinfo is None:
                raise ValueError("ROUTING_PRICE_TIMEZONE_REQUIRED")
        if self.effective_until <= self.effective_from:
            raise ValueError("ROUTING_PRICE_WINDOW_INVALID")

    def amount(
        self, input_tokens: int, output_tokens: int, cache_tokens: float = 0
    ) -> Decimal:
        if (
            min(input_tokens, output_tokens, cache_tokens) < 0
            or cache_tokens > input_tokens
        ):
            raise ValueError("ROUTING_COST_USAGE_INVALID")
        return (
            (Decimal(input_tokens) - Decimal(str(cache_tokens)))
            * Decimal(self.input_miss_per_million)
            + Decimal(str(cache_tokens)) * Decimal(self.input_hit_per_million)
            + Decimal(output_tokens) * Decimal(self.output_per_million)
        ) / Decimal(1_000_000)


@dataclass(frozen=True)
class ModelCandidate:
    candidate_id: str
    provider: str
    model: str
    reasoning: str
    tier: str
    capabilities: tuple[str, ...]
    context_limit: int
    output_limit: int
    pricing: PricingSnapshot
    capability_version: str
    available: bool = True
    availability_reason: str = ""
    escalation_only: bool = False
    quota_remaining: int = 0
    authorization_ref: str = ""
    model_revision: str = ""
    estimated_price_multiplier: str = "1"

    def __post_init__(self) -> None:
        if not all(
            (
                self.candidate_id,
                self.provider,
                self.model,
                self.reasoning,
                self.tier,
                self.capability_version,
            )
        ):
            raise ValueError("ROUTING_CAPABILITY_IDENTITY_REQUIRED")
        if min(self.context_limit, self.output_limit) <= 0:
            raise ValueError("ROUTING_CAPACITY_INVALID")
        multiplier = Decimal(self.estimated_price_multiplier)
        if not multiplier.is_finite() or not 0 < multiplier <= 1:
            raise ValueError("ROUTING_PRICE_MULTIPLIER_INVALID")


@dataclass(frozen=True)
class BenchmarkObservation:
    evidence_ref: str
    occurred_at: str
    quality_score: float | None
    accepted: bool | None
    schema_success: bool
    canon_conflict: bool | None
    retried: bool | None
    repaired: bool | None
    escalated: bool | None
    latency_seconds: float | None
    input_tokens: int
    output_tokens: int
    cache_hit_tokens: int
    actual_cost: str | None
    judge_score: float | None = None
    evidence_kind: str = "REAL_PROVIDER"
    domain_gate_accepted: bool | None = None
    outcome_refs: tuple[str, ...] = ()
    cache_prefix_hash: str = ""
    priced_cost: str | None = None
    served_model_identity_hash: str = ""
    evidence_class: str = "PRODUCTION_OUTCOME"
    production_eligible: bool = True
    sample_identity: str = ""
    experiment_partition: str = ""

    def __post_init__(self) -> None:
        for value in (self.quality_score, self.judge_score):
            if value is not None and (not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError("BENCHMARK_SCORE_INVALID")
        if (
            not self.evidence_ref
            or datetime.fromisoformat(self.occurred_at).tzinfo is None
        ):
            raise ValueError("BENCHMARK_EVIDENCE_IDENTITY_REQUIRED")
        if self.evidence_class not in {
            "PRODUCTION_OUTCOME",
            "BENCHMARK_CHALLENGER",
            "UNCLASSIFIED_REAL_PROVIDER",
        }:
            raise ValueError("BENCHMARK_EVIDENCE_CLASS_INVALID")
        if self.production_eligible != (
            self.evidence_class == "PRODUCTION_OUTCOME"
        ):
            raise ValueError("BENCHMARK_PRODUCTION_ELIGIBILITY_INVALID")
        if self.experiment_partition not in {"", "DEVELOPMENT", "CALIBRATION", "HOLDOUT"}:
            raise ValueError("BENCHMARK_PARTITION_INVALID")
        if self.experiment_partition and not self.sample_identity:
            raise ValueError("BENCHMARK_SAMPLE_IDENTITY_REQUIRED")
        if (
            min(
                self.input_tokens,
                self.output_tokens,
                self.cache_hit_tokens,
                self.latency_seconds or 0,
            )
            < 0
            or self.cache_hit_tokens > self.input_tokens
        ):
            raise ValueError("BENCHMARK_USAGE_INVALID")


def benchmark_snapshot(
    observations: Sequence[BenchmarkObservation],
    *,
    now: datetime,
    policy: TaskPolicy,
    window_days: int = 30,
    maximum_samples: int = 200,
) -> dict[str, Any]:
    unique = {
        row.evidence_ref: row
        for row in observations
        if row.evidence_kind == "REAL_PROVIDER"
        and 0
        <= (now - datetime.fromisoformat(row.occurred_at)).total_seconds()
        <= window_days * 86400
    }
    excluded_partition_count = sum(
        row.experiment_partition in {"DEVELOPMENT", "HOLDOUT"} for row in unique.values()
    )
    rows = sorted(
        (row for row in unique.values()
         if row.experiment_partition not in {"DEVELOPMENT", "HOLDOUT"}),
        key=lambda row: (row.occurred_at, row.evidence_ref),
    )[
        -maximum_samples:
    ]
    independent: dict[str, BenchmarkObservation] = {}
    for row in rows:
        independent.setdefault(row.sample_identity or row.evidence_ref, row)
    samples = list(independent.values())
    scores = [row.quality_score for row in samples if row.quality_score is not None]
    domain_outcomes = [
        row.domain_gate_accepted for row in samples if row.domain_gate_accepted is not None
    ]
    n = (
        len(domain_outcomes)
        if policy.quality_metric == "DOMAIN_GATE_ACCEPTANCE"
        else len(scores)
    )
    uncertainty = n < policy.minimum_samples
    average = mean(scores) if scores else 0.0
    penalty = policy.confidence_penalty * min(
        1, math.sqrt(policy.minimum_samples / max(1, n))
    )
    quality = max(
        0.0,
        average - penalty - (pstdev(scores) / math.sqrt(len(scores)) if scores else 0),
    )
    if policy.quality_metric == "DOMAIN_GATE_ACCEPTANCE":
        probability = mean(domain_outcomes) if domain_outcomes else 0.0
        z = 1.645
        quality = (
            max(
                0.0,
                (
                    probability
                    + z * z / (2 * n)
                    - z
                    * math.sqrt(
                        probability * (1 - probability) / n + z * z / (4 * n * n)
                    )
                )
                / (1 + z * z / n)
                - policy.confidence_penalty / math.sqrt(n),
            )
            if n
            else 0.0
        )
    decisions = [row for row in rows if row.accepted is not None]
    production_rows = [row for row in rows if row.production_eligible]
    production_decisions = [
        row for row in production_rows if row.accepted is not None
    ]
    benchmark_rows = [
        row for row in rows if row.evidence_class == "BENCHMARK_CHALLENGER"
    ]
    benchmark_decisions = [
        row for row in benchmark_rows if row.accepted is not None
    ]
    schema_yield = mean([int(row.schema_success) for row in rows]) if rows else 0.0
    qualification_acceptance = (
        mean([int(bool(row.accepted)) for row in decisions]) if decisions else None
    )
    production_acceptance = (
        mean([int(bool(row.accepted)) for row in production_decisions])
        if production_decisions
        else None
    )
    scoring_acceptance = (
        production_acceptance
        if production_acceptance is not None
        else qualification_acceptance
    )
    conditional_quality = quality
    quality = min(
        quality,
        schema_yield,
        scoring_acceptance if scoring_acceptance is not None else 1.0,
    )
    latencies = sorted(
        row.latency_seconds for row in rows if row.latency_seconds is not None
    )
    result: dict[str, Any] = {
        "sample_count": len(rows),
        "independent_sample_count": len(samples),
        "repeated_sample_attempt_count": len(rows) - len(samples),
        "excluded_experiment_partition_count": excluded_partition_count,
        "evidence_class_counts": {
            evidence_class: sum(
                row.evidence_class == evidence_class for row in rows
            )
            for evidence_class in (
                "PRODUCTION_OUTCOME",
                "BENCHMARK_CHALLENGER",
                "UNCLASSIFIED_REAL_PROVIDER",
            )
        },
        "production_eligible_sample_count": len(production_rows),
        "benchmark_challenger_sample_count": len(benchmark_rows),
        "served_model_identity_hashes": sorted(
            {
                row.served_model_identity_hash
                for row in rows
                if row.served_model_identity_hash
            }
        ),
        "quality_sample_count": len(scores),
        "quality_metric": policy.quality_metric,
        "metric_sample_count": n,
        "domain_gate_sample_count": len(domain_outcomes),
        "uncertain": uncertainty,
        "predicted_quality": quality,
        "conditional_content_quality": conditional_quality,
        "quality_constraint_basis": "CONTENT_AND_OBSERVED_DELIVERY_YIELD",
        "quality_mean": average,
        "quality_distribution": sorted(scores),
        "outcome_refs": sorted({ref for row in rows for ref in row.outcome_refs}),
        "confidence_penalty": penalty,
        "judge_score": mean(
            [row.judge_score for row in rows if row.judge_score is not None]
        )
        if any(row.judge_score is not None for row in rows)
        else None,
        "qualification_acceptance_rate": qualification_acceptance,
        "acceptance_rate": production_acceptance,
        "acceptance_sample_count": len(production_decisions),
        "production_acceptance_rate": production_acceptance,
        "production_acceptance_sample_count": len(production_decisions),
        "benchmark_acceptance_rate": mean(
            [int(bool(row.accepted)) for row in benchmark_decisions]
        )
        if benchmark_decisions
        else None,
        "benchmark_acceptance_sample_count": len(benchmark_decisions),
        "schema_success": schema_yield,
        **{
            name: mean(values) if values else None
            for name, values in {
                "canon_conflict_rate": [
                    int(row.canon_conflict)
                    for row in rows
                    if row.canon_conflict is not None
                ],
                "retry_rate": [
                    int(row.retried) for row in rows if row.retried is not None
                ],
                "repair_rate": [
                    int(row.repaired) for row in rows if row.repaired is not None
                ],
                "escalation_rate": [
                    int(row.escalated) for row in rows if row.escalated is not None
                ],
            }.items()
        },
        "latency_sample_count": len(latencies),
        "latency_seconds": latencies[int((len(latencies) - 1) * 0.95)]
        if latencies
        else None,
        "input_tokens": sum(row.input_tokens for row in rows),
        "output_tokens": sum(row.output_tokens for row in rows),
        "mean_output_tokens": mean([row.output_tokens for row in rows])
        if rows
        else None,
        "cache_hit_ratio": sum(row.cache_hit_tokens for row in rows)
        / max(1, sum(row.input_tokens for row in rows)),
        "mean_cache_hit_tokens": mean([row.cache_hit_tokens for row in rows])
        if rows
        else 0,
        "actual_cost": str(
            sum(
                (
                    Decimal(row.actual_cost)
                    for row in rows
                    if row.actual_cost is not None
                ),
                Decimal(0),
            )
        ),
        "cost_unknown_samples": sum(row.actual_cost is None for row in rows),
        "priced_usage_cost": str(
            sum(
                (
                    Decimal(row.priced_cost)
                    for row in rows
                    if row.priced_cost is not None
                ),
                Decimal(0),
            )
        ),
        "evidence_refs": [row.evidence_ref for row in rows],
        "window_days": window_days,
        "maximum_samples": maximum_samples,
        "as_of": now.isoformat(),
    }
    result["version"] = snapshot_hash(result)
    return result


@dataclass(frozen=True)
class RoutingTask:
    task_type: str
    project_id: str
    work_id: str
    operation_id: str
    attempt_id: str
    input_tokens: int
    output_tokens: int
    remaining_tokens: int
    remaining_money: str
    required_capabilities: tuple[str, ...] = ("structured_output",)
    risk: str = ""
    quality_floor: float = 0
    latency_sla_seconds: float = 0
    latency_cost_per_second: str = "0"
    reusable_prefix_tokens: int = 0
    cache_eligible: bool = False
    soft_money_limit: str | None = None
    history: tuple[Mapping[str, Any], ...] = ()
    escalation_reason: str = ""
    budget_snapshot: Mapping[str, Any] = field(default_factory=dict)
    cache_prefix_hash: str = ""
    chain_id: str = ""
    input_hash: str = ""
    request_hash: str = ""
    stable_key: str = ""
    declared_requirements: Mapping[str, Any] = field(default_factory=dict)
    policy_snapshot: Mapping[str, Any] = field(default_factory=dict)
    lineage_operation_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all(
            (
                self.task_type,
                self.project_id,
                self.work_id,
                self.operation_id,
                self.attempt_id,
            )
        ):
            raise ValueError("ROUTING_TASK_IDENTITY_REQUIRED")
        if (
            min(
                self.input_tokens,
                self.output_tokens,
                self.remaining_tokens,
                self.reusable_prefix_tokens,
            )
            < 0
            or self.reusable_prefix_tokens > self.input_tokens
        ):
            raise ValueError("ROUTING_TASK_SIZE_INVALID")
        if self.lineage_operation_ids and (
            self.lineage_operation_ids[-1] != self.operation_id
            or len(set(self.lineage_operation_ids)) != len(self.lineage_operation_ids)
            or any(not item for item in self.lineage_operation_ids)
        ):
            raise ValueError("ROUTING_TASK_LINEAGE_INVALID")
        for value in (
            self.remaining_money,
            self.latency_cost_per_second,
            self.soft_money_limit,
        ):
            if value is not None and (
                not Decimal(value).is_finite() or Decimal(value) < 0
            ):
                raise ValueError("ROUTING_BUDGET_INVALID")


@dataclass(frozen=True)
class RoutingDecision:
    snapshot_json: str

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.snapshot_json)

    @property
    def decision_id(self) -> str:
        return self.to_dict()["decision_id"]


class CostAwareRouter:
    def explain(
        self,
        task: RoutingTask,
        candidates: Sequence[ModelCandidate],
        observations: Mapping[str, Sequence[BenchmarkObservation]],
        *,
        now: datetime | None = None,
    ) -> RoutingDecision:
        now = now or datetime.now(timezone.utc)
        policy = task_policy(task.task_type, task.risk, task.quality_floor)
        if len({item.candidate_id for item in candidates}) != len(candidates):
            raise ValueError("ROUTING_DUPLICATE_CANDIDATE")
        failures = [str(item.get("failure_class") or "") for item in task.history]
        semantic_failures = sum(
            item
            in {
                "QUALITY_FAILURE",
                "CANON_CONFLICT",
                "SCHEMA_REJECTION",
                "MALFORMED_STRUCTURED_OUTPUT",
                "AMBIGUOUS_JUDGE",
            }
            for item in failures
        )
        escalations = sum(bool(item.get("escalation")) for item in task.history)
        rows: list[dict[str, Any]] = []
        for candidate in candidates:
            evidence = benchmark_snapshot(
                observations.get(candidate.candidate_id, ()), now=now, policy=policy
            )
            reasons: list[str] = []
            if len(task.history) >= policy.max_attempts:
                reasons.append("CHAIN_ATTEMPTS_EXHAUSTED")
            if any(
                item in {"UNKNOWN_EXTERNAL_OUTCOME", "POLICY_REJECTION"}
                for item in failures
            ):
                reasons.append("RECONCILIATION_OR_POLICY_RESOLUTION_REQUIRED")
            if not candidate.available:
                reasons.append("PROVIDER_UNAVAILABLE:" + candidate.availability_reason)
            if not set(task.required_capabilities).issubset(candidate.capabilities):
                reasons.append("CAPABILITY_UNSUPPORTED")
            if (
                task.input_tokens + task.output_tokens > candidate.context_limit
                or task.output_tokens > candidate.output_limit
            ):
                reasons.append("CONTEXT_CAPACITY_EXCEEDED")
            if evidence["predicted_quality"] < policy.quality_floor:
                reasons.append("QUALITY_FLOOR_NOT_MET")
            if evidence["uncertain"]:
                reasons.append("BENCHMARK_INSUFFICIENT")
            if (
                not datetime.fromisoformat(candidate.pricing.effective_from)
                <= now
                < datetime.fromisoformat(candidate.pricing.effective_until)
            ):
                reasons.append("PRICING_NOT_EFFECTIVE")
            if candidate.escalation_only:
                if not (
                    semantic_failures >= 2
                    or (policy.risk == "HIGH" and task.escalation_reason)
                ):
                    reasons.append("ESCALATION_THRESHOLD_NOT_MET")
                if candidate.quota_remaining <= 0 or not candidate.authorization_ref:
                    reasons.append("ESCALATION_CAPACITY_OR_AUTHORIZATION_MISSING")
                if escalations >= policy.max_escalations:
                    reasons.append("ESCALATION_LIMIT_REACHED")
            elif escalations or semantic_failures >= 2:
                reasons.append("SEMANTIC_ARBITRATION_REQUIRED")
            previous = [
                item
                for item in task.history
                if item.get("candidate_id") == candidate.candidate_id
            ]
            if any(
                item.get("failure_class")
                in {
                    "QUALITY_FAILURE",
                    "CANON_CONFLICT",
                    "CONTEXT_OVERFLOW",
                    "OUTPUT_CAPACITY_EXCEEDED",
                    "SCHEMA_REJECTION",
                    "MALFORMED_STRUCTURED_OUTPUT",
                    "AMBIGUOUS_JUDGE",
                    "PROVIDER_UNAVAILABLE",
                }
                for item in previous
            ):
                reasons.append("FAILED_ROUTE_EXCLUDED")
            if len(previous) >= 2:
                reasons.append("ROUTE_RETRY_LIMIT_REACHED")
            if any(
                item.get("status") in {"READY", "DISPATCHING", "DISPATCHED"}
                for item in task.history
            ):
                reasons.append("CHAIN_EXECUTION_IN_FLIGHT")
            if any(
                item.get("retry_after_until")
                and datetime.fromisoformat(str(item["retry_after_until"])) > now
                for item in previous
            ):
                reasons.append("RETRY_AFTER_ACTIVE")
            cache_rows = [
                row
                for row in observations.get(candidate.candidate_id, ())
                if not task.cache_prefix_hash
                or row.cache_prefix_hash == task.cache_prefix_hash
            ]
            cache_evidence = benchmark_snapshot(cache_rows, now=now, policy=policy)
            cache_tokens = (
                min(
                    task.reusable_prefix_tokens,
                    task.input_tokens,
                    cache_evidence["mean_cache_hit_tokens"],
                )
                if task.cache_eligible
                else 0
            )
            price = candidate.pricing
            expected_output = (
                min(task.output_tokens, math.ceil(evidence["mean_output_tokens"]))
                if evidence["mean_output_tokens"] is not None
                else task.output_tokens
            )
            estimated = price.amount(
                task.input_tokens, expected_output, cache_tokens
            ) * Decimal(candidate.estimated_price_multiplier)
            worst_case = price.amount(task.input_tokens, task.output_tokens)
            candidate_budget = task.budget_snapshot.get("candidates", {}).get(
                candidate.candidate_id, {}
            )
            remaining_tokens = min(
                task.remaining_tokens,
                int(candidate_budget.get("remaining_tokens", task.remaining_tokens)),
            )
            remaining_money = min(
                Decimal(task.remaining_money),
                Decimal(
                    str(candidate_budget.get("remaining_money", task.remaining_money))
                ),
            )
            if (
                candidate_budget.get("remaining_calls") == 0
                or task.input_tokens + task.output_tokens > remaining_tokens
                or (price.accounting_basis == "PRICED" and worst_case > remaining_money)
            ):
                reasons.append("BUDGET_HARD_LIMIT")
            latency = evidence["latency_seconds"]
            if task.latency_sla_seconds and (
                latency is None
                or evidence["latency_sample_count"] < policy.minimum_samples
                or latency > task.latency_sla_seconds
            ):
                reasons.append("LATENCY_SLA_UNPROVEN")
            acceptance = evidence["qualification_acceptance_rate"]
            failure_load = (1 - evidence["schema_success"]) + sum(
                evidence[key] if evidence[key] is not None else 0.5
                for key in (
                    "retry_rate",
                    "repair_rate",
                    "escalation_rate",
                    "canon_conflict_rate",
                )
            )
            effective = (
                estimated
                * Decimal(str(1 + min(policy.max_attempts - 1, failure_load)))
                / Decimal(str(max(0.01, acceptance or 0.01)))
            )
            effective += Decimal(str(latency or 0)) * Decimal(
                task.latency_cost_per_second
            )
            soft_pressure = task.soft_money_limit is not None and worst_case > Decimal(
                task.soft_money_limit
            )
            if soft_pressure:
                effective += worst_case - Decimal(task.soft_money_limit)
            rows.append(
                {
                    "candidate": asdict(candidate),
                    "benchmark": evidence,
                    "rejected_reasons": reasons,
                    "expected_quality": evidence["predicted_quality"],
                    "estimated_monetary_cost": str(estimated)
                    if price.accounting_basis == "PRICED"
                    else None,
                    "reservation_upper_bound": str(worst_case)
                    if price.accounting_basis == "PRICED"
                    else None,
                    "estimated_total_tokens": task.input_tokens + task.output_tokens,
                    "expected_effective_cost": str(effective)
                    if price.accounting_basis == "PRICED"
                    else None,
                    "cache_tokens_estimate": cache_tokens,
                    "cache_evidence_refs": cache_evidence["evidence_refs"],
                    "soft_limit_pressure": soft_pressure,
                }
            )
        eligible = [row for row in rows if not row["rejected_reasons"]]
        selected = (
            min(
                eligible,
                key=lambda row: (
                    row["expected_effective_cost"] is None,
                    Decimal(row["expected_effective_cost"] or "0"),
                    row["candidate"]["candidate_id"],
                ),
            )
            if eligible
            else None
        )
        snapshot: dict[str, Any] = {
            "schema_version": POLICY_VERSION,
            "policy_version": POLICY_VERSION,
            "policy": asdict(policy),
            "task": asdict(task),
            "created_at": now.isoformat(),
            "status": "SELECTED" if selected else "BLOCKED",
            "selected": selected,
            "candidates": rows,
            "escalation_policy": {
                "max_attempts": policy.max_attempts,
                "max_escalations": policy.max_escalations,
                "semantic_failure_threshold": 2,
                "unavailable_action": "BLOCK",
                "reason": task.escalation_reason,
                "history": list(task.history),
            },
        }
        snapshot["decision_id"] = "routing-decision:" + snapshot_hash(
            snapshot
        ).removeprefix("sha256:")
        return RoutingDecision(
            json.dumps(snapshot, sort_keys=True, ensure_ascii=False, allow_nan=False)
        )
