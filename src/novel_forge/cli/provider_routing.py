from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
from uuid import uuid4
from pathlib import Path
from typing import Any

from novel_forge.modules.production_execution.cost_routing import (
    RoutingTask,
    ModelCandidate,
    PricingSnapshot,
    benchmark_snapshot,
    task_policy,
)
from novel_forge.modules.production_execution.routing_catalog import deepseek_candidates
from novel_forge.modules.production_execution.routing_runtime import (
    PostgresRoutingRegistry,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def _priced_observation_metrics(observations: list[Any]) -> dict[str, Any]:
    buckets = {
        "production": [row for row in observations if row.production_eligible],
        "benchmark_challenger": [
            row
            for row in observations
            if row.evidence_class == "BENCHMARK_CHALLENGER"
        ],
        "reference_evaluation": [row for row in observations if row.evidence_class == "REFERENCE_EVALUATION"],
        "unclassified": [
            row
            for row in observations
            if not row.production_eligible
            and row.evidence_class not in {"BENCHMARK_CHALLENGER", "REFERENCE_EVALUATION"}
        ],
    }
    result: dict[str, Any] = {}
    for name, rows in buckets.items():
        priced = [row for row in rows if row.priced_cost is not None]
        cost = sum((Decimal(row.priced_cost) for row in priced), Decimal(0))
        accepted = sum(row.accepted is True for row in rows)
        complete = len(priced) == len(rows)
        calibrated = [row.quality_score for row in rows if row.quality_score is not None]
        quality_per_cost = (
            sum((Decimal(str(score)) for score in calibrated), Decimal(0)) / cost
            if rows and complete and len(calibrated) == len(rows) and cost > 0
            else None
        )
        result.update(
            {
                f"{name}_sample_count": len(rows),
                f"{name}_accepted_output_count": accepted,
                f"{name}_priced_usage_cost": str(cost),
                f"{name}_cost_unknown_samples": len(rows) - len(priced),
                f"{name}_priced_cost_per_accepted_output": (
                    str(cost / accepted) if accepted and complete else None
                ),
                f"{name}_calibrated_quality_per_priced_dollar": (
                    str(quality_per_cost) if quality_per_cost is not None else None
                ),
                f"{name}_quality_per_cost_metric": (
                    "CALIBRATED_SCORE"
                    if quality_per_cost is not None
                    else None
                ),
            }
        )
    result["priced_cost_per_accepted_output"] = result[
        "production_priced_cost_per_accepted_output"
    ]
    result["quality_per_priced_dollar"] = result[
        "production_calibrated_quality_per_priced_dollar"
    ]
    return result


def add_provider_routing_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "authority-provider-routing",
        help="explain or replay Provider selection without inference",
    )
    parser.add_argument("action", choices=("explain", "replay", "metrics", "configure", "campaign"))
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--decision-id", default="")
    parser.add_argument("--task-context-file", default="")
    parser.add_argument("--policy-file", type=Path)
    parser.add_argument("--workspace-id", default="")
    parser.add_argument("--idempotency-key", default="")
    parser.add_argument("--campaign-id", default="")


def run_provider_routing_command(settings: Any, args: Any) -> dict[str, Any]:
    from novel_forge.api.authority_dependencies import build_trusted_principal_resolver

    principal = build_trusted_principal_resolver().resolve_api_principal()
    if args.action == "configure":
        from novel_forge.api.authority_dependencies import authority_release_identity
        from novel_forge.modules.authority_handler_runtime.policy_commands import (
            configure_owned_policy,
        )
        from novel_forge.modules.production_execution.routing_policy import OWNER

        if not all((args.policy_file, args.workspace_id, args.idempotency_key)):
            raise ValueError(
                "routing configure requires policy, workspace and idempotency key"
            )
        build_id, sha = authority_release_identity()
        return configure_owned_policy(
            database_url=settings.database_url,
            owner=OWNER,
            content=json.loads(args.policy_file.read_text()),
            project_id=args.project_id,
            workspace_id=args.workspace_id,
            idempotency_key=args.idempotency_key,
            trace_id=f"trace:{uuid4()}",
            correlation_id=f"correlation:{uuid4()}",
            application_build_id=build_id,
            commit_sha=sha,
            principal=principal,
        )
    principal.require("content.authority.query", args.project_id)
    from novel_forge.modules.authority_handler_runtime.routing_feedback import (
        domain_gate_outcomes,
    )

    registry = PostgresRoutingRegistry(
        settings.database_url, outcome_projection=domain_gate_outcomes
    )
    if args.action == "campaign":
        if not args.campaign_id:
            raise ValueError("routing campaign requires campaign-id")
        return registry.campaign(project_id=args.project_id, campaign_id=args.campaign_id)
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
        from novel_forge.api.authority_dependencies import (
            build_production_execution_composition,
        )

        payload = json.loads(Path(args.task_context_file).read_text())
        request_input = payload.pop("request_input", None)
        cache_prefix = str(payload.pop("cache_prefix", "")).encode()
        task = RoutingTask(**payload)
        if task.project_id != args.project_id or not task.stable_key:
            raise ValueError("ROUTING_PROJECT_SCOPE_AND_STABLE_KEY_REQUIRED")
        execution = build_production_execution_composition(settings)
        router = execution.gateway.provider_router
        if router is None:
            raise ValueError("CANONICAL_PROVIDER_ROUTER_REQUIRED")
        base = (
            execution.gateway.routes.get(task.task_type)
            or execution.gateway.routes["draft"]
        )
        _, decision = router.select(
            base,
            task_type=task.task_type,
            project_id=task.project_id,
            work_id=task.work_id,
            operation_id=task.operation_id,
            attempt_id=task.attempt_id,
            stable_key=task.stable_key,
            input_tokens=task.input_tokens,
            output_tokens=task.output_tokens,
            trace_id="routing-dry-run",
            correlation_id="routing-dry-run",
            risk=task.risk,
            quality_floor=task.quality_floor,
            chapter=int(task.declared_requirements.get("chapter") or 0),
            input_hash=task.input_hash,
            request_input=request_input,
            producer_contract=task.producer_contract,
            cache_prefix=cache_prefix,
            lineage_operation_ids=task.lineage_operation_ids,
            dry_run=True,
        )
        return {
            "mode": "DRY_RUN",
            "budget_evidence": "CURRENT_LEDGER_RECHECKED_AT_ADMISSION",
            "decision": decision,
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
                      b.evidence->>'work_id',b.currency,b.evidence->>'accounting_basis',
                      CASE WHEN e.request_payload #> '{_production_execution,capability_runtime,routing_decision}' IS NULL
                           THEN 'LEGACY_UNKNOWN' ELSE 'FROZEN_ROUTING_DECISION' END,
                      count(*),sum(b.estimated_tokens),sum(b.actual_tokens),
                      sum(b.estimated_amount),sum(b.settled_amount),
                      count(*) FILTER (WHERE b.status='HELD_UNKNOWN')
               FROM authority_budget_reservation b JOIN authority_external_effect e USING(external_effect_id)
               WHERE b.project_id=%s GROUP BY 1,2,3,4,5,6,7 ORDER BY 1,2,3,4,5,6,7""",
            [args.project_id],
        )
        costs = [
            dict(
                zip(
                    (
                        "provider",
                        "model",
                        "task_type",
                        "work_id",
                        "currency",
                        "accounting_basis",
                        "routing_evidence",
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
        uow.cursor.execute(
            """SELECT DISTINCT v.content #> '{selected,candidate}'
               FROM authority_asset a JOIN authority_asset_version v USING(asset_id)
               WHERE a.project_id=%s AND a.asset_type='routing_decision'
                 AND v.content->>'status' IN ('SELECTED','BENCHMARK_SELECTED')""",
            [args.project_id],
        )
        candidate_snapshots = [row[0] for row in uow.cursor.fetchall()]
    candidates = {
        item.candidate_id + item.model_revision: item
        for item in deepseek_candidates(available=False)
    }
    for value in candidate_snapshots:
        candidate = ModelCandidate(
            **{**value, "pricing": PricingSnapshot(**value["pricing"])}
        )
        candidates[candidate.candidate_id + candidate.model_revision] = candidate
    benchmarks = []
    for task_type in sorted({row["task_type"] for row in distribution}):
        for candidate in candidates.values():
            observations = registry.observations(
                project_id=args.project_id, task_type=task_type, candidate=candidate
            )
            for contract_hash in sorted({row.producer_contract_hash for row in observations}) or [""]:
                cohort = [row for row in observations if row.producer_contract_hash == contract_hash]
                snapshot = benchmark_snapshot(
                    cohort, now=datetime.now(timezone.utc), policy=task_policy(task_type),
                )
                benchmarks.append({
                    "task_type": task_type, "candidate_id": candidate.candidate_id,
                    "model_revision": candidate.model_revision,
                    "producer_contract_hash": contract_hash,
                    "scope": "PRODUCER_CONTRACT_COHORT" if contract_hash else "LEGACY_PRODUCER_SCOPE_UNKNOWN",
                    "production_qualification": "REQUIRES_CURRENT_CONTRACT_AND_QUALITY_GATE",
                    **snapshot, **_priced_observation_metrics(cohort),
                })
    return {
        "source": "POSTGRESQL_AUTHORITY_PROJECTION",
        "project_id": args.project_id,
        "routing_distribution": distribution,
        "costs": costs,
        "benchmarks": benchmarks,
        "monetary_measurement": "SETTLED_LEDGER_AMOUNTS_MAY_BE_UPPER_BOUNDS; ACTUAL_COST_REQUIRES_BILLED_EVIDENCE",
    }
