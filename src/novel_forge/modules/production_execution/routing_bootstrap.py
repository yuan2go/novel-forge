from __future__ import annotations

import json
from dataclasses import asdict, replace
from decimal import Decimal
from typing import Any, Mapping, Sequence

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.routing_bootstrap import (
    authorization_hash,
    bootstrap_candidate_accounting_matches,
    validate_bootstrap_authorization,
    validate_bootstrap_producer,
)

from .cost_routing import ModelCandidate, RoutingDecision, RoutingTask, snapshot_hash, task_policy


def bind_diagnostic_escalation_reason(
    task: RoutingTask, candidates: Sequence[ModelCandidate],
    authorization: Mapping[str, Any], *, environment: str,
) -> RoutingTask:
    """CONSTRAINT: Only a frozen exact HIGH-risk diagnostic grant supplies escalation intent."""
    if environment != "validation":
        raise KernelError("ROUTING_BOOTSTRAP_ENVIRONMENT_FORBIDDEN",
                          "benchmark challengers require the validation runtime")
    grant = authorization["authorization"]
    validate_bootstrap_authorization(grant)
    if authorization.get("authorization_hash") != authorization_hash(grant):
        raise KernelError("ROUTING_BOOTSTRAP_SCOPE_MISMATCH", "diagnostic authorization hash differs")
    validate_bootstrap_producer(grant, asdict(task))
    if (task.project_id != authorization["project_id"] or task.work_id != grant["book_id"]
        or task.task_type != grant["task_type"]):
        raise KernelError("ROUTING_BOOTSTRAP_SCOPE_MISMATCH",
                          "diagnostic escalation differs from the authorized task")
    if task.escalation_reason or task_policy(task.task_type, task.risk, task.quality_floor).risk != "HIGH":
        return task
    matching = [candidate for candidate in candidates
        if candidate.candidate_id == grant["candidate_id"]
        and candidate.model_revision == grant["model_revision"]
        and candidate.provider == "codex-cli" and candidate.escalation_only
        and bootstrap_candidate_accounting_matches(grant, asdict(candidate))]
    if len(matching) != 1:
        return task
    # WHY: The admitted grant explicitly selected this diagnostic model; preserve its
    # reason in the Task rather than inventing failure history or dropping a gate.
    return replace(task, escalation_reason=grant["reason"])


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
        if not bootstrap_candidate_accounting_matches(grant, candidate):
            row["rejected_reasons"].append("BENCHMARK_ACCOUNTING_AUTHORIZATION_MISMATCH")
        row["rejected_reasons"] = [
            reason
            for reason in row["rejected_reasons"]
            if reason not in {"QUALITY_FLOOR_NOT_MET", "BENCHMARK_INSUFFICIENT"}
        ]
        if (row["estimated_total_tokens"] > grant["maximum_tokens"]
            or grant["maximum_amount"] is not None and Decimal(
                row["reservation_upper_bound"] or "0"
            ) > Decimal(grant["maximum_amount"])):
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
