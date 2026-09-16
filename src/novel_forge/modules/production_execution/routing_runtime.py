from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from typing import Any, Callable, Mapping, Sequence

from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_asset_store import (
    AuthorityAssetQuery,
    AuthorityAssetWriter,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.versioned_policy_repository import policy_hash

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
    def __init__(
        self,
        database_url: str,
        *,
        outcome_projection: Callable[..., dict[str, dict[str, Any]]] | None = None,
    ) -> None:
        self.database_url = database_url
        self.outcome_projection = outcome_projection
        self.query = AuthorityAssetQuery(database_url)
        self.writer = AuthorityAssetWriter(database_url)

    def policy(self, project_id: str) -> dict[str, Any]:
        from .routing_policy import OWNER, validate_routing_policy

        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """SELECT v.content,v.content_hash,v.actor_id,s.selected_by_operation_id
                   FROM authority_runtime_policy_selection s
                   JOIN authority_runtime_policy_version v USING(owner,project_id,policy_version)
                   WHERE s.owner=%s AND s.project_id=%s""",
                [OWNER, project_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            return {}
        content, digest, actor, operation = row
        if policy_hash(content) != digest:
            raise KernelError(
                "RUNTIME_POLICY_HASH_MISMATCH", "routing policy integrity failed"
            )
        validate_routing_policy(content)
        return {
            "policy": content,
            "policy_hash": digest,
            "actor_id": actor,
            "operation_id": operation,
        }

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
                            ELSE NULL END,
                          effect.request_payload #> '{_production_execution,capability_runtime,routing_decision}',
                          quality.asset_version_id
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
                       SELECT v.content,v.asset_version_id FROM authority_asset_version v
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
            gate_outcomes = (
                self.outcome_projection(
                    uow.cursor,
                    project_id=project_id,
                    effect_ids=[
                        str(
                            (
                                row[2]
                                .get("provider_evidence", row[2])
                                .get("production_execution")
                                or {}
                            )
                            .get("execution_request", {})
                            .get("external_effect_id")
                            or ""
                        )
                        for row in rows
                    ],
                )
                if self.outcome_projection is not None
                and (
                    task_type.endswith(".generate")
                    or task_type == "source.deconstruction.observe"
                )
                else {}
            )
        observations = []
        seen_effects = set()
        latest_served_identity = ""
        for (
            reference,
            occurred_at,
            content,
            quality,
            accepted,
            retried,
            decision,
            quality_ref,
        ) in rows:
            evidence = content.get("provider_evidence", content)
            if evidence.get("fixture_protocol_only") or content.get(
                "fixture_protocol_only"
            ):
                continue
            observed_revision = (
                ((decision or {}).get("selected") or {})
                .get("candidate", {})
                .get("model_revision")
            )
            if (
                candidate.model_revision
                and candidate.model_revision != observed_revision
            ):
                continue
            usage = evidence.get("usage") or {}
            execution = evidence.get("production_execution") or {}
            result = execution.get("execution_result") or {}
            process = execution.get("process_evidence") or {}
            served_identity = str(
                process.get("served_model_identity_hash")
                or evidence.get("served_model_identity_hash")
                or ""
            )
            if candidate.provider == "deepseek":
                if not served_identity:
                    continue
                if not latest_served_identity:
                    latest_served_identity = served_identity
                if served_identity != latest_served_identity:
                    continue
            effect_id = (execution.get("execution_request") or {}).get(
                "external_effect_id"
            )
            if not effect_id or effect_id in seen_effects:
                continue
            seen_effects.add(effect_id)
            gate = gate_outcomes.get(effect_id, {})
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
            ) in {"FINAL_FAILURE", "RETRYABLE_FAILURE"}
            cost = evidence.get("cost") or {}
            observations.append(
                BenchmarkObservation(
                    evidence_ref="asset-version:" + reference,
                    occurred_at=occurred_at.isoformat(),
                    quality_score=score,
                    judge_score=score,
                    accepted=True
                    if accepted
                    else False
                    if rejected
                    else gate.get("accepted"),
                    schema_success=result.get("outcome") == "SUCCEEDED",
                    canon_conflict=True
                    if failure == "CANON_CONFLICT"
                    else canon_conflict,
                    retried=retried,
                    repaired=True if task_type == "revision" else None,
                    escalated=candidate.escalation_only,
                    latency_seconds=float(process["latency_seconds"])
                    if process.get("latency_seconds") is not None
                    else None,
                    input_tokens=int(usage.get("input_tokens") or 0),
                    output_tokens=int(usage.get("output_tokens") or 0),
                    cache_hit_tokens=int(usage.get("prompt_cache_hit_tokens") or 0),
                    actual_cost=cost.get("amount")
                    if cost.get("provider_billed") is True
                    else None,
                    domain_gate_accepted=gate.get("accepted"),
                    outcome_refs=tuple(gate.get("evidence_refs", ()))
                    + (("asset-version:" + quality_ref,) if quality_ref else ()),
                    cache_prefix_hash=(decision or {})
                    .get("task", {})
                    .get("cache_prefix_hash", ""),
                    priced_cost=cost.get("amount")
                    if cost.get("source")
                    in {"usage_pricing", "usage_pricing_upper_bound"}
                    else None,
                    served_model_identity_hash=served_identity,
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
                          dispatch.evidence,
                          quality.content
                   FROM authority_external_effect effect
                   LEFT JOIN LATERAL (
                       SELECT evidence,created_at FROM authority_external_effect_dispatch
                       WHERE external_effect_id=effect.external_effect_id
                       ORDER BY generation DESC LIMIT 1
                   ) dispatch ON true
                   LEFT JOIN LATERAL (
                     SELECT q.content FROM authority_asset_version generated
                     JOIN authority_asset_version q ON q.content->>'target_asset_version_id'=generated.asset_version_id
                     JOIN authority_asset qa ON qa.asset_id=q.asset_id AND qa.project_id=effect.project_id
                       AND qa.asset_type='quality_score_report'
                     WHERE generated.content #>> '{provider_evidence,production_execution,execution_request,external_effect_id}'=effect.external_effect_id
                       AND q.governance='CLEAR' ORDER BY q.created_at LIMIT 1
                   ) quality ON true
                   WHERE effect.project_id=%s AND effect.operation_id=%s
                     AND effect.request_payload->>'stage'=%s
                     AND effect.request_payload #>> '{_production_execution,capability_runtime,routing_decision,task,chain_id}'=%s
                   ORDER BY effect.created_at LIMIT 10""",
                [project_id, operation_id, task_type, chain_id],
            )
            rows = uow.cursor.fetchall()
        history = []
        for effect_id, status, updated_at, decision, evidence, quality in rows:
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
            if not failure and (quality or {}).get("gate") == "FAILED":
                failure = (
                    "CANON_CONFLICT"
                    if any(
                        item.get("dimension") == "canon_consistency"
                        and item.get("gate_status") == "FAILED"
                        for item in quality.get("dimensions", ())
                    )
                    else "QUALITY_FAILURE"
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
        outcome_projection: Callable[..., dict[str, dict[str, Any]]] | None = None,
    ) -> None:
        self.registry = PostgresRoutingRegistry(
            database_url, outcome_projection=outcome_projection
        )
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
        input_hash: str = "",
        request_input: Mapping[str, Any] | None = None,
        chapter: int = 0,
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
                        "input_hash": input_hash,
                        "request_hash": snapshot_hash(request_input)
                        if request_input is not None
                        else "",
                        "declared_requirements": {
                            "risk": risk,
                            "quality_floor": quality_floor,
                            "chapter": chapter,
                        },
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
                "task_money_limit": self.task_money_limit,
                "task_token_limit": self.task_token_limit,
                "money_used_or_reserved": str(money_used),
                "tokens_used_or_reserved": int(tokens_used),
                "admission_recheck_required": True,
                "candidates": budgets,
            },
        )
        now = datetime.now(timezone.utc)
        from .routing_catalog import deepseek_pricing_period

        candidates = tuple(
            replace(
                candidate,
                estimated_price_multiplier="0.5"
                if deepseek_pricing_period(now) == "OFF_PEAK"
                else "1",
            )
            if candidate.provider == "deepseek"
            else candidate
            for candidate in self.candidates
        )
        observations = {
            candidate.candidate_id: self.registry.observations(
                project_id=project_id, task_type=task_type, candidate=candidate
            )
            for candidate in candidates
        }
        from .routing_policy import task_requirements

        policy_snapshot = self.registry.policy(project_id)
        requirements = (
            task_requirements(
                policy_snapshot["policy"],
                work_id=work_id,
                task_type=task_type,
                chapter=chapter,
            )
            if policy_snapshot
            else {}
        )
        if requirements:
            ranks = {"": -1, "LOW": 0, "MEDIUM": 1, "HIGH": 2}
            requirements["risk"] = max(
                (risk, requirements.get("risk", "")), key=ranks.__getitem__
            )
            requirements["quality_floor"] = max(
                quality_floor, requirements.get("quality_floor", 0)
            )
        task = replace(
            task,
            input_hash=input_hash,
            request_hash=snapshot_hash(request_input)
            if request_input is not None
            else "",
            stable_key=stable_key,
            declared_requirements={
                "risk": risk,
                "quality_floor": quality_floor,
                "chapter": chapter,
            },
            policy_snapshot=policy_snapshot,
            **requirements,
        )
        decision = CostAwareRouter().explain(task, candidates, observations, now=now)
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
                if candidate.escalation_only:
                    uow.cursor.execute(
                        f"""SELECT count(*) FROM authority_budget_reservation
                            WHERE provider=%s AND evidence->>'cost_authorization_ref'=%s
                              AND {provider_usage_accounted_sql()}""",
                        [candidate.provider, candidate.authorization_ref],
                    )
                    result["remaining_calls"] = max(
                        0, candidate.quota_remaining - int(uow.cursor.fetchone()[0])
                    )
                for kind, caps in (
                    ("money", self.money_caps),
                    ("tokens", self.token_caps),
                    ("calls", self.call_caps),
                ):
                    for scope, cap in caps.items():
                        if scope == "chapter_total":
                            continue
                        where, parameters = _usage_cap_dimension(request, scope)
                        if kind == "money" and scope.startswith("global_"):
                            where += " AND currency=%s"
                            parameters = [*parameters, candidate.pricing.currency]
                        aggregate = {
                            "money": "COALESCE(sum(CASE WHEN status='SETTLED' THEN settled_amount ELSE reserved_amount END),0)",
                            "tokens": "COALESCE(sum(CASE WHEN status='SETTLED' THEN actual_tokens ELSE greatest(actual_tokens,estimated_tokens) END),0)",
                            "calls": "count(*)",
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
        fixture = candidate["provider"] == "scripted_provider_v2"
        if (
            fixture
            and base.model_profile.runtime_class
            is not ExecutionRuntimeClass.SCRIPTED_FIXTURE
        ):
            raise KernelError(
                "ROUTING_FIXTURE_BOUNDARY_VIOLATION", candidate["candidate_id"]
            )
        suffix = snapshot_hash(candidate).split(":")[-1][:20]
        profile = replace(
            base.model_profile,
            profile_id=base.model_profile.profile_id + "." + suffix,
            backend_id=base.model_profile.backend_id
            if fixture
            else "codex-cli"
            if candidate["provider"] == "codex-cli"
            else "remote-provider-" + candidate["provider"],
            model_provider=candidate["provider"],
            model_id=candidate["model"],
            reasoning_effort=candidate["reasoning"],
            runtime_class=ExecutionRuntimeClass.SCRIPTED_FIXTURE
            if fixture
            else ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE
            if candidate["provider"] == "codex-cli"
            else ExecutionRuntimeClass.REMOTE_PROVIDER_API,
            capability_probe_ref=base.model_profile.capability_probe_ref
            if fixture
            else "capability-probe:codex-cli:real-runtime-v1"
            if candidate["provider"] == "codex-cli"
            else "capability-probe:"
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
                else "CODEX_CLI_APPLICATION_UTF8_BYTES_UPPER_BOUND_V1"
                if candidate["provider"] == "codex-cli"
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
            version_id = str(frozen.get("asset_version_id") or "")
            document = self.registry.query.require(
                project_id=str(metadata["project_id"]), asset_version_id=version_id
            )
            content = {
                key: value for key, value in frozen.items() if key != "asset_version_id"
            }
            expected_id = "routing-decision:" + snapshot_hash(
                {key: value for key, value in content.items() if key != "decision_id"}
            ).removeprefix("sha256:")
            if (
                document.asset_type != "routing_decision"
                or document.content != content
                or content.get("decision_id") != expected_id
            ):
                raise KernelError("ROUTING_DECISION_INTEGRITY_FAILURE", version_id)
            task = content["task"]
            if (
                any(
                    task.get(key) != str(metadata.get(key) or "")
                    for key in ("project_id", "operation_id", "attempt_id")
                )
                or task.get("work_id") != metadata.get("book_id")
                or task.get("task_type") != payload.get("stage")
                or task.get("request_hash") != snapshot_hash(payload.get("input"))
            ):
                raise KernelError("ROUTING_DECISION_SCOPE_MISMATCH", version_id)
            admission = self.registry.query.require(
                project_id=task["project_id"],
                asset_version_id=str(
                    metadata["capability_runtime"].get(
                        "provider_admission_asset_version_id"
                    )
                    or ""
                ),
            )
            identity = admission.content.get("contract", admission.content).get(
                "provider_request_identity", {}
            )
            selected = content["selected"]["candidate"]
            from .provider_admission import provider_request_protocol

            try:
                admitted_pricing = json.loads(
                    identity.get("pricing_policy_json") or "null"
                )
            except (TypeError, ValueError) as exc:
                raise KernelError(
                    "ROUTING_ADMISSION_IDENTITY_MISMATCH", version_id
                ) from exc
            if (
                admission.asset_type != "provider_request_admission_manifest"
                or admission.content_hash
                != metadata["capability_runtime"].get("provider_admission_content_hash")
                or identity.get("input_text_hash") != task.get("input_hash")
                or identity.get("stable_idempotency_key") != task.get("stable_key")
                or identity.get("max_output_tokens") != task.get("output_tokens")
                or identity.get("provider") != selected["provider"]
                or identity.get("model") != selected["model"]
                or identity.get("protocol")
                != provider_request_protocol(selected["provider"])
                or str(identity.get("reasoning_effort") or "")
                != (selected["reasoning"] if selected["provider"] == "deepseek" else "")
                or admitted_pricing != selected["pricing"]
            ):
                raise KernelError("ROUTING_ADMISSION_IDENTITY_MISMATCH", version_id)
            return self._selected_route(base, frozen), dict(frozen)
        raise KernelError("ROUTING_FROZEN_DECISION_REQUIRED", str(payload.get("stage")))


def routed_reservation(
    decision: Mapping[str, Any], *, input_tokens: int, output_tokens: int
) -> str | None:
    from .cost_routing import PricingSnapshot

    price = PricingSnapshot(**decision["selected"]["candidate"]["pricing"])
    if price.accounting_basis == "ACCOUNT_ENTITLEMENT":
        return None
    return str(price.amount(input_tokens, output_tokens))
