from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from novel_forge.modules.production_execution.cost_routing import (
    CostAwareRouter,
    RoutingTask,
    benchmark_snapshot,
    task_policy,
)
from novel_forge.modules.production_execution.routing_catalog import deepseek_candidates
from novel_forge.modules.production_execution.routing_runtime import (
    PostgresRoutingRegistry,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def add_provider_routing_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "authority-provider-routing",
        help="explain or replay Provider selection without inference",
    )
    parser.add_argument("action", choices=("explain", "replay", "metrics"))
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--decision-id", default="")
    parser.add_argument("--task-context-file", default="")


def run_provider_routing_command(settings: Any, args: Any) -> dict[str, Any]:
    from novel_forge.api.authority_dependencies import build_trusted_principal_resolver

    principal = build_trusted_principal_resolver().resolve_api_principal()
    principal.require("content.authority.query", args.project_id)
    registry = PostgresRoutingRegistry(settings.database_url)
    if args.action == "replay":
        document = registry.query.require(
            project_id=args.project_id, asset_id=args.decision_id
        )
        if document.asset_type != "routing_decision":
            raise ValueError("ROUTING_DECISION_REQUIRED")
        return {
            "decision": document.content,
            "asset_version_id": document.asset_version_id,
            "content_hash": document.content_hash,
            "mode": "IMMUTABLE_REPLAY",
        }
    if args.action == "explain":
        task = RoutingTask(**json.loads(Path(args.task_context_file).read_text()))
        if task.project_id != args.project_id:
            raise ValueError("ROUTING_PROJECT_SCOPE_MISMATCH")
        candidates = deepseek_candidates(
            available=bool(os.environ.get("DEEPSEEK_API_KEY"))
        )
        task = replace(
            task,
            history=registry.history(
                project_id=args.project_id,
                operation_id=task.operation_id,
                task_type=task.task_type,
                chain_id=task.chain_id,
            ),
        )
        observations = {
            candidate.candidate_id: registry.observations(
                project_id=args.project_id,
                task_type=task.task_type,
                candidate=candidate,
            )
            for candidate in candidates
        }
        return {
            "mode": "DRY_RUN",
            "budget_evidence": "CALLER_TASK_SNAPSHOT_RECHECKED_AT_ADMISSION",
            "decision": CostAwareRouter()
            .explain(task, candidates, observations)
            .to_dict(),
        }
    with AuthorityUnitOfWork(settings.database_url) as uow:
        uow.cursor.execute(
            """SELECT v.content->'task'->>'task_type',v.content->>'status',
                      v.content #>> '{selected,candidate,provider}',
                      v.content #>> '{selected,candidate,model}', count(*)
               FROM authority_asset a JOIN authority_asset_version v USING(asset_id)
               WHERE a.project_id=%s AND a.asset_type='routing_decision'
               GROUP BY 1,2,3,4 ORDER BY 1,2,3,4""",
            [args.project_id],
        )
        distribution = [
            dict(
                zip(
                    ("task_type", "status", "provider", "model", "count"),
                    row,
                    strict=True,
                )
            )
            for row in uow.cursor.fetchall()
        ]
        uow.cursor.execute(
            """SELECT b.provider,e.model_id,e.request_payload->>'stage',
                      count(*),sum(b.estimated_tokens),sum(b.actual_tokens),
                      sum(b.estimated_amount),sum(b.settled_amount),
                      count(*) FILTER (WHERE b.status='HELD_UNKNOWN')
               FROM authority_budget_reservation b JOIN authority_external_effect e USING(external_effect_id)
               WHERE b.project_id=%s GROUP BY 1,2,3 ORDER BY 1,2,3""",
            [args.project_id],
        )
        costs = [
            dict(
                zip(
                    (
                        "provider",
                        "model",
                        "task_type",
                        "calls",
                        "estimated_tokens",
                        "actual_tokens",
                        "reserved_money",
                        "settled_money",
                        "held_unknown",
                    ),
                    row,
                    strict=True,
                )
            )
            for row in uow.cursor.fetchall()
        ]
    benchmarks = []
    for task_type in sorted({row["task_type"] for row in distribution}):
        for candidate in deepseek_candidates(available=False):
            observations = registry.observations(
                project_id=args.project_id, task_type=task_type, candidate=candidate
            )
            benchmarks.append(
                {
                    "task_type": task_type,
                    "candidate_id": candidate.candidate_id,
                    **benchmark_snapshot(
                        observations,
                        now=datetime.now(timezone.utc),
                        policy=task_policy(task_type),
                    ),
                }
            )
    return {
        "source": "POSTGRESQL_AUTHORITY_PROJECTION",
        "project_id": args.project_id,
        "routing_distribution": distribution,
        "costs": costs,
        "benchmarks": benchmarks,
        "monetary_measurement": "SETTLED_LEDGER_AMOUNTS_MAY_BE_UPPER_BOUNDS; ACTUAL_COST_REQUIRES_BILLED_EVIDENCE",
    }
