from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping, Sequence

from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_asset_store import (
    AuthorityAssetQuery,
    AuthorityAssetWriter,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .cost_routing import (
    BenchmarkObservation,
    CostAwareRouter,
    ModelCandidate,
    RoutingDecision,
    RoutingTask,
    snapshot_hash,
)
from .contracts import ExecutionRuntimeClass


class PostgresRoutingRegistry:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.query = AuthorityAssetQuery(database_url)
        self.writer = AuthorityAssetWriter(database_url)

    def observations(
        self, *, project_id: str, task_type: str, candidate: ModelCandidate
    ) -> list[BenchmarkObservation]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """SELECT version.asset_version_id, version.created_at, version.content,
                          quality.content,
                          EXISTS(SELECT 1 FROM authority_book_chapter_acceptance acceptance
                            JOIN authority_asset_version outcome ON outcome.asset_version_id=acceptance.chapter_outcome_asset_version_id
                            WHERE acceptance.project_id=asset.project_id AND acceptance.status='COMMITTED'
                              AND outcome.content->>'accepted_draft_asset_version_id'=generated.asset_version_id),
                          CASE WHEN effect.request_payload #>> '{_production_execution,capability_runtime,routing_decision,task,chain_id}' IS NOT NULL
                            THEN EXISTS(SELECT 1 FROM authority_external_effect previous
                              WHERE previous.project_id=effect.project_id AND previous.operation_id=effect.operation_id
                                AND previous.created_at<effect.created_at
                                AND previous.request_payload #>> '{_production_execution,capability_runtime,routing_decision,task,chain_id}'
                                  = effect.request_payload #>> '{_production_execution,capability_runtime,routing_decision,task,chain_id}')
                            ELSE NULL END
                   FROM authority_asset_version version
                   JOIN authority_asset asset ON asset.asset_id=version.asset_id
                   CROSS JOIN LATERAL (SELECT COALESCE(version.content->'provider_evidence',version.content) AS evidence) model
                   LEFT JOIN authority_external_effect effect ON effect.external_effect_id=model.evidence #>> '{production_execution,execution_request,external_effect_id}'
                     AND effect.project_id=asset.project_id
                   LEFT JOIN LATERAL (
                       SELECT v.asset_version_id,v.content,v.eligibility
                       FROM authority_asset_version v
                       JOIN authority_asset a ON a.asset_id=v.asset_id
                       WHERE a.project_id=asset.project_id
                         AND a.asset_type IN ('draft_version','best_draft_candidate')
                         AND v.content #>> '{provider_evidence,production_execution,execution_request,external_effect_id}'
                             = model.evidence #>> '{production_execution,execution_request,external_effect_id}'
                       ORDER BY v.created_at DESC LIMIT 1
                   ) generated ON true
                   LEFT JOIN LATERAL (
                       SELECT v.content FROM authority_asset_version v
                       JOIN authority_asset a ON a.asset_id=v.asset_id
                       WHERE a.project_id=asset.project_id AND a.asset_type='quality_score_report'
                         AND v.content->>'target_asset_version_id'=generated.asset_version_id
                         AND v.governance='CLEAR'
                       ORDER BY v.created_at DESC LIMIT 1
                   ) quality ON true
                   WHERE asset.project_id=%s AND asset.asset_type='model_call_log'
                     AND COALESCE(version.content->>'stage',model.evidence #>> '{production_execution,execution_request,stage}')=%s
                     AND model.evidence->>'provider_id'=%s
                     AND model.evidence->>'model_id'=%s
                     AND model.evidence #>> '{production_execution,route_snapshot,reasoning_effort}'=%s
                     AND COALESCE(model.evidence->>'real_model_call',model.evidence->>'real_provider_proven')='true'
                     AND version.created_at >= NOW() - INTERVAL '30 days'
                   ORDER BY version.created_at DESC LIMIT 200""",
                [
                    project_id,
                    task_type,
                    candidate.provider,
                    candidate.model,
                    candidate.reasoning,
                ],
            )
            rows = uow.cursor.fetchall()
        observations = []
        seen_effects = set()
        for reference, occurred_at, content, quality, accepted, retried in rows:
            evidence = content.get("provider_evidence", content)
            usage = evidence.get("usage") or {}
            execution = evidence.get("production_execution") or {}
            result = execution.get("execution_result") or {}
            process = execution.get("process_evidence") or {}
            effect_id = (execution.get("execution_request") or {}).get(
                "external_effect_id"
            )
            if not effect_id or effect_id in seen_effects:
                continue
            seen_effects.add(effect_id)
            calibrated = (
                bool(quality)
                and not quality.get("fixture")
                and not quality.get("uncalibrated_dimensions")
                and bool(
                    quality.get("provider_verified") or quality.get("human_verified")
                )
            )
            score = (quality or {}).get("aggregate_score") if calibrated else None
            score = float(score) / 100 if isinstance(score, (int, float)) else None
            canon_dimensions = [
                item
                for item in (quality or {}).get("dimensions", ())
                if item.get("dimension") == "canon_consistency"
            ]
            canon_conflict = (
                any(item.get("gate_status") == "FAILED" for item in canon_dimensions)
                if canon_dimensions
                else None
            )
            failure = process.get("failure_class")
            rejected = (quality or {}).get("gate") == "FAILED" or result.get(
                "outcome"
            ) in {"FAILED_FINAL", "FAILED_RETRYABLE"}
            cost = evidence.get("cost") or {}
            observations.append(
                BenchmarkObservation(
                    evidence_ref="asset-version:" + reference,
                    occurred_at=occurred_at.isoformat(),
                    quality_score=score,
                    judge_score=score,
                    accepted=True if accepted else False if rejected else None,
                    schema_success=result.get("outcome") == "SUCCEEDED",
                    canon_conflict=True
                    if failure == "CANON_CONFLICT"
                    else canon_conflict,
                    retried=retried,
                    repaired=True if task_type == "revision" else None,
                    escalated=candidate.escalation_only,
                    latency_seconds=float(process.get("latency_seconds") or 0),
                    input_tokens=int(usage.get("input_tokens") or 0),
                    output_tokens=int(usage.get("output_tokens") or 0),
                    cache_hit_tokens=int(usage.get("prompt_cache_hit_tokens") or 0),
                    actual_cost=cost.get("amount")
                    if cost.get("provider_billed") is True
                    else None,
                )
            )
        return observations

    def history(
        self, *, project_id: str, operation_id: str, task_type: str, chain_id: str = ""
    ) -> tuple[dict[str, Any], ...]:
        if not chain_id:
            return ()
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """SELECT effect.external_effect_id, effect.status, dispatch.created_at,
                          effect.request_payload #> '{_production_execution,capability_runtime,routing_decision}',
                          dispatch.evidence
                   FROM authority_external_effect effect
                   LEFT JOIN LATERAL (
                       SELECT evidence,created_at FROM authority_external_effect_dispatch
                       WHERE external_effect_id=effect.external_effect_id
                       ORDER BY generation DESC LIMIT 1
                   ) dispatch ON true
                   WHERE effect.project_id=%s AND effect.operation_id=%s
                     AND effect.request_payload->>'stage'=%s
                     AND effect.request_payload #>> '{_production_execution,capability_runtime,routing_decision,task,chain_id}'=%s
                   ORDER BY effect.created_at LIMIT 10""",
                [project_id, operation_id, task_type, chain_id],
            )
            rows = uow.cursor.fetchall()
        history = []
        for effect_id, status, updated_at, decision, evidence in rows:
            if not decision:
                continue
            selected = (decision.get("selected") or {}).get("candidate") or {}
            process = (
                (evidence or {})
                .get("production_execution", {})
                .get("process_evidence", {})
            )
            failure = (
                "UNKNOWN_EXTERNAL_OUTCOME"
                if status
                in {
                    "UNKNOWN",
                    "UNKNOWN_AMBIGUOUS",
                    "SENT_UNKNOWN",
                    "RECONCILIATION_REQUIRED",
                }
                else process.get("failure_class", "")
            )
            history.append(
                {
                    "external_effect_id": effect_id,
                    "candidate_id": selected.get("candidate_id"),
                    "failure_class": failure,
                    "status": status,
                    "escalation": selected.get("escalation_only", False),
                }
            )
            delay = process.get("retry_after_seconds")
            if (
                updated_at is not None
                and isinstance(delay, (int, float))
                and delay >= 0
            ):
                history[-1]["retry_after_until"] = (
                    updated_at + timedelta(seconds=delay)
                ).isoformat()
        return tuple(history)

    def save(
        self,
        decision: RoutingDecision,
        *,
        logical_ref: str,
        trace_id: str,
        correlation_id: str,
    ) -> Mapping[str, Any]:
        value = decision.to_dict()
        task = value["task"]
        document = self.writer.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=task["operation_id"],
                project_id=task["project_id"],
                asset_id=value["decision_id"],
                asset_type="routing_decision",
                schema_version=value["schema_version"],
                logical_ref=logical_ref,
                category="production_execution",
                output_key="routing." + value["decision_id"].split(":")[-1],
                role="routing_evidence",
                content=value,
                qualification_policy="routing-decision-evidence.v1",
                trace_id=trace_id,
                correlation_id=correlation_id,
            )
        )
        return {**value, "asset_version_id": document.asset_version_id}


class ProductionProviderRouter:
    def __init__(
        self,
        database_url: str,
        *,
        candidates: Sequence[ModelCandidate],
        task_money_limit: str,
        task_token_limit: int,
        soft_money_limit: str | None = None,
        money_caps: Mapping[str, str] | None = None,
        token_caps: Mapping[str, int] | None = None,
        call_caps: Mapping[str, int] | None = None,
    ) -> None:
        self.registry = PostgresRoutingRegistry(database_url)
        self.candidates = tuple(candidates)
        self.task_money_limit = task_money_limit
        self.task_token_limit = task_token_limit
        self.soft_money_limit = soft_money_limit
        self.money_caps = dict(money_caps or {})
        self.token_caps = dict(token_caps or {})
        self.call_caps = dict(call_caps or {})
        if self.task_token_limit <= 0 or Decimal(task_money_limit) <= 0:
            raise ValueError("ROUTING_POSITIVE_TASK_BUDGET_REQUIRED")

    def select(
        self,
        base_route: Any,
        *,
        task_type: str,
        project_id: str,
        work_id: str,
        operation_id: str,
        attempt_id: str,
        stable_key: str,
        input_tokens: int,
        output_tokens: int,
        trace_id: str,
        correlation_id: str,
        risk: str = "",
        quality_floor: float = 0,
        dry_run: bool = False,
        cache_prefix: bytes = b"",
    ) -> tuple[Any, dict[str, Any]]:
        logical_ref = (
            "production_execution/routing/"
            + snapshot_hash(
                {
                    "project": project_id,
                    "operation": operation_id,
                    "attempt": attempt_id,
                    "task_type": task_type,
                    "stable_key": stable_key,
                }
            ).split(":")[-1]
        )
        if not dry_run:
            try:
                existing = self.registry.query.require(
                    project_id=project_id, logical_ref=logical_ref
                )
                snapshot = {
                    **existing.content,
                    "asset_version_id": existing.asset_version_id,
                }
                original = snapshot["task"]
                if any(
                    original.get(key) != value
                    for key, value in {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "work_id": work_id,
                        "risk": risk,
                        "quality_floor": quality_floor,
                        "cache_prefix_hash": snapshot_hash(cache_prefix.hex())
                        if cache_prefix
                        else "",
                    }.items()
                ):
                    raise KernelError("ROUTING_REQUEST_DRIFT", logical_ref)
                return self._selected_route(base_route, snapshot), snapshot
            except KernelError as exc:
                if exc.code != "AUTHORITY_ASSET_NOT_FOUND":
                    raise
        chain_id = snapshot_hash(
            stable_key.replace(f"{operation_id}:{attempt_id}:", f"{operation_id}:", 1)
        )
        history = self.registry.history(
            project_id=project_id,
            operation_id=operation_id,
            task_type=task_type,
            chain_id=chain_id,
        )
        with AuthorityUnitOfWork(self.registry.database_url) as uow:
            uow.cursor.execute(
                """SELECT COALESCE(sum(CASE WHEN status='SETTLED' THEN settled_amount ELSE reserved_amount END),0),
                          COALESCE(sum(CASE WHEN status='SETTLED' THEN actual_tokens ELSE estimated_tokens END),0)
                   FROM authority_budget_reservation WHERE project_id=%s AND operation_id=%s
                     AND status IN ('RESERVED','HELD_UNKNOWN','SETTLED')
                     AND external_effect_id IN (SELECT external_effect_id FROM authority_external_effect
                       WHERE project_id=%s AND operation_id=%s AND request_payload #>> '{_production_execution,capability_runtime,routing_decision,task,chain_id}'=%s)
                   """,
                [project_id, operation_id, project_id, operation_id, chain_id],
            )
            money_used, tokens_used = uow.cursor.fetchone()
        remaining_money = max(Decimal(0), Decimal(self.task_money_limit) - money_used)
        remaining_tokens = max(0, self.task_token_limit - int(tokens_used))
        budgets = self._candidate_budgets(
            project_id=project_id,
            work_id=work_id,
            operation_id=operation_id,
            stable_key=stable_key,
        )
        task = RoutingTask(
            task_type,
            project_id,
            work_id,
            operation_id,
            attempt_id,
            input_tokens,
            output_tokens,
            remaining_tokens,
            str(remaining_money),
            risk=risk,
            quality_floor=quality_floor,
            history=history,
            chain_id=chain_id,
            soft_money_limit=self.soft_money_limit,
            cache_eligible=bool(cache_prefix),
            reusable_prefix_tokens=min(input_tokens, len(cache_prefix) // 4),
            cache_prefix_hash=snapshot_hash(cache_prefix.hex()) if cache_prefix else "",
            budget_snapshot={
                "scope": "execution_chain",
                "money_used_or_reserved": str(money_used),
                "tokens_used_or_reserved": int(tokens_used),
                "admission_recheck_required": True,
                "candidates": budgets,
            },
        )
        observations = {
            candidate.candidate_id: self.registry.observations(
                project_id=project_id, task_type=task_type, candidate=candidate
            )
            for candidate in self.candidates
        }
        decision = CostAwareRouter().explain(
            task, self.candidates, observations, now=datetime.now(timezone.utc)
        )
        snapshot = (
            decision.to_dict()
            if dry_run
            else dict(
                self.registry.save(
                    decision,
                    logical_ref=logical_ref,
                    trace_id=trace_id,
                    correlation_id=correlation_id,
                )
            )
        )
        if dry_run and snapshot["status"] != "SELECTED":
            return base_route, snapshot
        return self._selected_route(base_route, snapshot), snapshot

    def _candidate_budgets(
        self, *, project_id: str, work_id: str, operation_id: str, stable_key: str
    ) -> dict[str, Any]:
        from novel_forge.modules.command_kernel.budget_runtime import (
            BudgetReservationRequest,
            _usage_cap_dimension,
            provider_usage_accounted_sql,
        )

        budgets = {}
        with AuthorityUnitOfWork(self.registry.database_url) as uow:
            for candidate in self.candidates:
                request = BudgetReservationRequest(
                    operation_id,
                    "",
                    project_id,
                    stable_key,
                    candidate.provider,
                    candidate.pricing.currency,
                    "0",
                    0,
                    model_id=candidate.model,
                    work_id=work_id,
                )
                result: dict[str, Any] = {
                    "remaining_money": self.task_money_limit,
                    "remaining_tokens": self.task_token_limit,
                    "remaining_calls": None,
                    "scopes": {},
                }
                for kind, caps in (
                    ("money", self.money_caps),
                    ("tokens", self.token_caps),
                    ("calls", self.call_caps),
                ):
                    for scope, cap in caps.items():
                        if scope == "chapter_total":
                            continue
                        where, parameters = _usage_cap_dimension(request, scope)
                        aggregate = {
                            "money": "COALESCE(sum(CASE WHEN status='SETTLED' THEN settled_amount ELSE reserved_amount END),0)",
                            "tokens": "COALESCE(sum(CASE WHEN status='SETTLED' THEN actual_tokens ELSE greatest(actual_tokens,estimated_tokens) END),0)",
                            "calls": "count(DISTINCT external_effect_id)",
                        }[kind]
                        uow.cursor.execute(
                            f"SELECT {aggregate} FROM authority_budget_reservation WHERE {where} AND {provider_usage_accounted_sql()}",
                            parameters,
                        )
                        used = uow.cursor.fetchone()[0]
                        remaining = max(
                            Decimal(0), Decimal(str(cap)) - Decimal(str(used))
                        )
                        key = "remaining_" + kind
                        prior = result[key]
                        result[key] = (
                            str(min(Decimal(str(prior)), remaining))
                            if kind == "money"
                            else int(
                                remaining
                                if prior is None
                                else min(int(prior), remaining)
                            )
                        )
                        result["scopes"][kind + ":" + scope] = {
                            "cap": str(cap),
                            "used_or_reserved": str(used),
                            "remaining": str(remaining),
                        }
                budgets[candidate.candidate_id] = result
        return budgets

    @staticmethod
    def _selected_route(base: Any, snapshot: Mapping[str, Any]) -> Any:
        if snapshot.get("status") != "SELECTED":
            raise KernelError(
                "PROVIDER_ROUTING_BLOCKED", str(snapshot.get("decision_id"))
            )
        candidate = snapshot["selected"]["candidate"]
        suffix = snapshot_hash(candidate).split(":")[-1][:20]
        profile = replace(
            base.model_profile,
            profile_id=base.model_profile.profile_id + "." + suffix,
            backend_id="codex-cli"
            if candidate["provider"] == "codex-cli"
            else "remote-provider-" + candidate["provider"],
            model_provider=candidate["provider"],
            model_id=candidate["model"],
            reasoning_effort=candidate["reasoning"],
            runtime_class=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE
            if candidate["provider"] == "codex-cli"
            else ExecutionRuntimeClass.REMOTE_PROVIDER_API,
            capability_probe_ref="capability-probe:"
            + candidate["provider"]
            + ":provider-capability-v2",
        )
        policy = replace(
            base.route_policy,
            policy_id=base.route_policy.policy_id + "." + suffix,
            default_model_profile_id=profile.profile_id,
            allowed_model_profile_ids=(profile.profile_id,),
        )
        changes = dict(model_profile=profile, route_policy=policy)
        if hasattr(base, "model_context_limit"):
            changes.update(
                model_context_limit=candidate["context_limit"],
                token_accounting_method="DEEPSEEK_UTF8_BYTES_UPPER_BOUND_V1"
                if candidate["provider"] == "deepseek"
                else base.token_accounting_method,
                token_accounting_evidence_ref=candidate["capability_version"],
            )
        return replace(base, **changes)

    def select_for_payload(
        self, base: Any, payload: Mapping[str, Any]
    ) -> tuple[Any, dict[str, Any]]:
        metadata = payload["_production_execution"]
        frozen = (metadata.get("capability_runtime") or {}).get("routing_decision")
        if frozen:
            return self._selected_route(base, frozen), dict(frozen)
        raise KernelError("ROUTING_FROZEN_DECISION_REQUIRED", str(payload.get("stage")))


def routed_reservation(
    decision: Mapping[str, Any], *, input_tokens: int, output_tokens: int
) -> str:
    from .cost_routing import PricingSnapshot

    price = PricingSnapshot(**decision["selected"]["candidate"]["pricing"])
    return str(price.amount(input_tokens, output_tokens))
