from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.routing_bootstrap import (
    validate_bootstrap_authorization,
    validate_bootstrap_producer,
)

from .cost_routing import RoutingDecision, snapshot_hash


def benchmark_decision(
    decision: RoutingDecision, authorization: Mapping[str, Any], *, environment: str
) -> RoutingDecision:
    if environment != "validation":
        raise KernelError(
            "ROUTING_BOOTSTRAP_ENVIRONMENT_FORBIDDEN",
            "benchmark challengers require the validation runtime",
        )
    grant = authorization["authorization"]
    validate_bootstrap_authorization(grant)
    snapshot = decision.to_dict()
    validate_bootstrap_producer(grant, snapshot["task"])
    if (
        snapshot["task"]["project_id"] != authorization["project_id"]
        or snapshot["task"]["work_id"] != grant["book_id"]
        or snapshot["task"]["task_type"] != grant["task_type"]
    ):
        raise KernelError(
            "ROUTING_BOOTSTRAP_SCOPE_MISMATCH",
            "benchmark route differs from the authorized task",
        )
    selected = None
    for row in snapshot["candidates"]:
        row["production_rejected_reasons"] = list(row["rejected_reasons"])
        candidate = row["candidate"]
        if (
            candidate["candidate_id"] != grant["candidate_id"]
            or candidate["model_revision"] != grant["model_revision"]
        ):
            row["rejected_reasons"].append("BENCHMARK_AUTHORIZED_TARGET_MISMATCH")
            continue
        if (
            candidate["provider"] != "deepseek"
            or candidate["pricing"]["accounting_basis"] != "PRICED"
        ):
            row["rejected_reasons"].append("BENCHMARK_PRICED_PROVIDER_REQUIRED")
        row["rejected_reasons"] = [
            reason
            for reason in row["rejected_reasons"]
            if reason not in {"QUALITY_FLOOR_NOT_MET", "BENCHMARK_INSUFFICIENT"}
        ]
        if row["estimated_total_tokens"] > grant["maximum_tokens"] or Decimal(
            row["reservation_upper_bound"] or "0"
        ) > Decimal(grant["maximum_amount"]):
            row["rejected_reasons"].append("BENCHMARK_AUTHORIZATION_BUDGET_EXCEEDED")
        if not row["rejected_reasons"]:
            selected = row
    snapshot.update(
        status="BENCHMARK_SELECTED" if selected else "BLOCKED",
        selected=selected,
        mode="BENCHMARK_CHALLENGER",
        production_eligible=False,
        bootstrap_authorization=dict(authorization),
    )
    snapshot.pop("decision_id", None)
    snapshot["decision_id"] = "routing-decision:" + snapshot_hash(snapshot)[7:]
    return RoutingDecision(
        json.dumps(snapshot, sort_keys=True, ensure_ascii=False, allow_nan=False)
    )
