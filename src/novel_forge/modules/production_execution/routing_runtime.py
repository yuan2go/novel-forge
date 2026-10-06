from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import math
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
    TASK_TAXONOMY,
    snapshot_hash,
)
from .contracts import ExecutionRuntimeClass


def _routing_operation_lineage(
    operation_id: str, lineage_operation_ids: Sequence[str]
) -> tuple[str, ...]:
    lineage = tuple(str(item) for item in lineage_operation_ids) or (operation_id,)
    if (
        lineage[-1] != operation_id
        or len(set(lineage)) != len(lineage)
        or any(not item for item in lineage)
    ):
        raise KernelError(
            "ROUTING_OPERATION_LINEAGE_INVALID",
            "routing operation lineage must be unique and end at the current Operation",
        )
    return lineage


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
                """SELECT v.content,v.content_hash,v.actor_id,s.selected_by_operation_id,v.created_by_operation_id
                   FROM authority_runtime_policy_selection s
                   JOIN authority_runtime_policy_version v USING(owner,project_id,policy_version)
                   WHERE s.owner=%s AND s.project_id=%s""",
                [OWNER, project_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            return {}
        content, digest, actor, selection_operation, created_operation = row
        operation = created_operation if content.get("execution_templates") else selection_operation
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
        self, *, project_id: str, task_type: str, candidate: ModelCandidate,
        producer_contract_hash: str | None = None, work_id: str = "",
        policy_snapshot: Mapping[str, Any] | None = None,
    ) -> list[BenchmarkObservation]:
        from .routing_sources import matching_bindings, validate_binding

        snapshot = self.policy(project_id) if policy_snapshot is None else policy_snapshot
        bindings = matching_bindings(snapshot.get("policy", {}), project_id=project_id,
            work_id=work_id, task_type=task_type, candidate=candidate, producer_contract_hash=producer_contract_hash)
        observations = self._local_observations(project_id=project_id, task_type=task_type,
            candidate=candidate, producer_contract_hash=producer_contract_hash)
        sources: dict[str, set[str]] = {}
        for binding in bindings:
            with AuthorityUnitOfWork(self.database_url) as uow:
                validate_binding(uow.cursor, binding, now=datetime.now(timezone.utc))
            row = binding["export"]
            sources.setdefault(row["source_project_id"], set()).update(item["asset_version_id"] for item in row["observations"])
        for source_project, refs in sources.items():
            observations.extend(self._local_observations(project_id=source_project,
                task_type=task_type, candidate=candidate, producer_contract_hash=producer_contract_hash,
                observation_refs=tuple(sorted(refs))))
        observations = list({item.evidence_ref: item for item in observations}.values())
        if candidate.provider == "deepseek" and observations:
            latest = max(observations, key=lambda item: datetime.fromisoformat(item.occurred_at))
            observations = [item for item in observations if item.served_model_identity_hash == latest.served_model_identity_hash]
        return observations

    def _local_observations(
        self, *, project_id: str, task_type: str, candidate: ModelCandidate,
        producer_contract_hash: str | None = None, observation_refs: tuple[str, ...] | None = None,
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
                              WHERE previous.project_id=effect.project_id
                                AND COALESCE(effect.request_payload #> '{_production_execution,capability_runtime,routing_decision,task,lineage_operation_ids}',jsonb_build_array(effect.operation_id)) ? previous.operation_id
                                AND previous.created_at<effect.created_at
                                AND previous.request_payload #>> '{_production_execution,capability_runtime,routing_decision,task,chain_id}'
                                  = effect.request_payload #>> '{_production_execution,capability_runtime,routing_decision,task,chain_id}')
                            ELSE NULL END,
                          effect.request_payload #> '{_production_execution,capability_runtime,routing_decision}',
                          quality.asset_version_id,
                          EXISTS(SELECT 1 FROM authority_external_effect_dispatch failed
                            JOIN authority_external_effect_dispatch repeated
                              ON repeated.external_effect_id=failed.external_effect_id
                                AND repeated.generation>failed.generation
                            WHERE failed.external_effect_id=effect.external_effect_id
                              AND failed.status IN ('FAILED_RETRYABLE','FAILED_FINAL','DEAD_LETTER')
                              AND COALESCE(failed.evidence->>'real_model_call',failed.evidence->>'real_provider_proven')='true'
                              AND COALESCE(repeated.evidence->>'real_model_call',repeated.evidence->>'real_provider_proven')='true'
                              AND COALESCE(failed.evidence->>'fixture_protocol_only','false')<>'true'
                              AND COALESCE(repeated.evidence->>'fixture_protocol_only','false')<>'true'),
                          EXISTS(SELECT 1 FROM authority_external_effect previous
                            JOIN authority_external_effect_dispatch dispatch USING(external_effect_id)
                            CROSS JOIN LATERAL (SELECT previous.request_payload
                              #> '{_production_execution,capability_runtime,routing_decision}' AS route) prior
                            WHERE previous.project_id=effect.project_id
                              AND (previous.created_at,previous.external_effect_id)<(effect.created_at,effect.external_effect_id)
                              AND (dispatch.created_at >= NOW() - INTERVAL '30 days'
                                OR prior.route #>> '{bootstrap_authorization,authorization,campaign,partition}' IN ('DEVELOPMENT','HOLDOUT'))
                              AND previous.request_payload->>'stage'=effect.request_payload->>'stage'
                              AND current_route.route->>'status'='BENCHMARK_SELECTED'
                              AND current_route.route->>'mode'='BENCHMARK_CHALLENGER'
                              AND current_route.route->>'production_eligible'='false'
                              AND prior.route->>'status'='BENCHMARK_SELECTED'
                              AND prior.route->>'mode'='BENCHMARK_CHALLENGER'
                              AND prior.route->>'production_eligible'='false'
                              AND prior.route #>> '{bootstrap_authorization,authorization,purpose}'
                                =current_route.route #>> '{bootstrap_authorization,authorization,purpose}'
                              AND prior.route #>> '{bootstrap_authorization,authorization,purpose}'
                                IN ('BENCHMARK_CHALLENGER','REFERENCE_EVALUATION')
                              AND NULLIF(current_route.route #>> '{task,input_hash}','') IS NOT NULL
                              AND NULLIF(current_route.route #>> '{task,producer_contract_hash}','') IS NOT NULL
                              AND prior.route #>> '{task,input_hash}'=current_route.route #>> '{task,input_hash}'
                              AND prior.route #>> '{task,producer_contract_hash}'=current_route.route #>> '{task,producer_contract_hash}'
                              AND COALESCE(prior.route #>> '{selected,candidate,model_revision}','')
                                =COALESCE(current_route.route #>> '{selected,candidate,model_revision}','')
                              AND COALESCE(dispatch.evidence->>'real_model_call',dispatch.evidence->>'real_provider_proven')='true'
                              AND COALESCE(dispatch.evidence->>'fixture_protocol_only','false')<>'true'
                              AND dispatch.evidence->>'provider_id'=model.evidence->>'provider_id'
                              AND dispatch.evidence->>'model_id'=model.evidence->>'model_id'
                              AND dispatch.evidence #>> '{production_execution,route_snapshot,reasoning_effort}'
                                =model.evidence #>> '{production_execution,route_snapshot,reasoning_effort}'
                              AND (COALESCE(dispatch.evidence #>> '{production_execution,process_evidence,served_model_identity_hash}',
                                    dispatch.evidence->>'served_model_identity_hash','')=''
                                OR COALESCE(dispatch.evidence #>> '{production_execution,process_evidence,served_model_identity_hash}',
                                    dispatch.evidence->>'served_model_identity_hash')
                                  =COALESCE(model.evidence #>> '{production_execution,process_evidence,served_model_identity_hash}',
                                    model.evidence->>'served_model_identity_hash')))
                   FROM authority_asset_version version
                   JOIN authority_asset asset ON asset.asset_id=version.asset_id
                   CROSS JOIN LATERAL (SELECT COALESCE(version.content->'provider_evidence',version.content) AS evidence) model
                   LEFT JOIN authority_external_effect effect ON effect.external_effect_id=model.evidence #>> '{production_execution,execution_request,external_effect_id}'
                     AND effect.project_id=asset.project_id
                   LEFT JOIN LATERAL (SELECT effect.request_payload
                     #> '{_production_execution,capability_runtime,routing_decision}' AS route) current_route ON true
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
                     AND (%s::text[] IS NULL OR version.asset_version_id=ANY(%s::text[]))
                     AND effect.external_effect_id IS NOT NULL
                     AND COALESCE(version.content->>'stage',model.evidence #>> '{production_execution,execution_request,stage}')=%s
                     AND model.evidence->>'provider_id'=%s
                     AND model.evidence->>'model_id'=%s
                     AND model.evidence #>> '{production_execution,route_snapshot,reasoning_effort}'=%s
                     AND COALESCE(model.evidence->>'real_model_call',model.evidence->>'real_provider_proven')='true'
                     AND (%s::text IS NULL OR (%s::text<>'' AND effect.request_payload
                       #>> '{_production_execution,capability_runtime,routing_decision,task,producer_contract_hash}'=%s))
                     AND version.created_at >= NOW() - INTERVAL '30 days'
                   ORDER BY version.created_at DESC LIMIT 200""",
                [
                    project_id,
                    list(observation_refs) if observation_refs is not None else None,
                    list(observation_refs) if observation_refs is not None else None,
                    task_type,
                    candidate.provider,
                    candidate.model,
                    candidate.reasoning,
                    producer_contract_hash, producer_contract_hash, producer_contract_hash,
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
                and rows
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
            same_effect_provider_retry,
            repeated_experiment_input,
        ) in rows:
            if ((decision or {}).get("bootstrap_authorization", {}).get("authorization", {})
                .get("purpose") == "MODEL_REFERENCE_CREATION"):
                continue
            evidence = content.get("provider_evidence", content)
            if evidence.get("fixture_protocol_only") or content.get(
                "fixture_protocol_only"
            ):
                continue
            observed_revision = (
                ((decision or {}).get("selected") or {})
                .get("candidate", {})
                .get("model_revision")
            ) or (evidence.get("production_execution") or {}).get(
                "process_evidence", {}
            ).get("model_revision")
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
            if (
                (decision or {}).get("status") == "BENCHMARK_SELECTED"
                and (decision or {}).get("mode") == "BENCHMARK_CHALLENGER"
                and (decision or {}).get("production_eligible") is False
            ):
                evidence_class = ("REFERENCE_EVALUATION" if (decision or {}).get("bootstrap_authorization", {}).get("authorization", {}).get("purpose") == "REFERENCE_EVALUATION" else "BENCHMARK_CHALLENGER")
                production_eligible = False
            elif (
                (decision or {}).get("status") == "SELECTED"
                and not (decision or {}).get("bootstrap_authorization")
                and (decision or {}).get("production_eligible") is not False
                and (decision or {}).get("independent_qualification_eligible") is not False
            ):
                evidence_class = "PRODUCTION_OUTCOME"
                production_eligible = True
            else:
                evidence_class = "UNCLASSIFIED_REAL_PROVIDER"
                production_eligible = False
            campaign = (
                (decision or {}).get("bootstrap_authorization", {})
                .get("authorization", {}).get("campaign") or {}
            )
            sample_identity = (
                snapshot_hash({key: campaign[key] for key in (
                    "campaign_id", "manifest_hash", "group_id",
                )}) if campaign else str((decision or {}).get("task", {}).get("input_hash") or "")
            )
            if gate.get("reference_sample_identity"):
                sample_identity = gate["reference_sample_identity"]
            if gate.get("generator_sample_identity"):
                sample_identity = gate["generator_sample_identity"]
            if gate.get("independent_sample_identity"):
                sample_identity = gate["independent_sample_identity"]
            observations.append(
                BenchmarkObservation(
                    evidence_ref="asset-version:" + reference,
                    occurred_at=occurred_at.isoformat(),
                    quality_score=score if sample_identity else None,
                    judge_score=score,
                    accepted=True
                    if accepted
                    else False
                    if rejected
                    else gate.get("accepted"),
                    schema_success=result.get("outcome") == "SUCCEEDED" and not same_effect_provider_retry,
                    canon_conflict=True
                    if failure == "CANON_CONFLICT"
                    else canon_conflict,
                    retried=True if same_effect_provider_retry or repeated_experiment_input else retried,
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
                    domain_gate_accepted=gate.get("accepted") if sample_identity else None,
                    independent_quality_score=gate.get("independent_quality_score") if campaign.get("partition") == "CALIBRATION" else None,
                    independent_protocol_hash=gate.get("independent_protocol_hash", ""),
                    independent_risk=gate.get("independent_risk", (decision or {}).get("policy", {}).get("risk", "")),
                    independent_context_tokens=gate.get("independent_context_tokens", (decision or {}).get("task", {}).get("input_tokens")),
                    generator_quality_score=gate.get("generator_quality_score") if campaign.get("partition") == "CALIBRATION" else None,
                    generator_protocol_hash=gate.get("generator_protocol_hash", ""),
                    generator_risk=gate.get("generator_risk", (decision or {}).get("policy", {}).get("risk", "")),
                    generator_context_tokens=gate.get("generator_context_tokens", (decision or {}).get("task", {}).get("input_tokens")),
                    reference_agreed=gate.get("reference_agreed") if sample_identity else None,
                    reference_label_classes=tuple(gate.get("reference_label_classes", ())) if sample_identity else (),
                    reference_protocol_hash=gate.get("reference_protocol_hash", ""),
                    reference_context_tokens=(decision or {}).get("task", {}).get("input_tokens") if evidence_class == "REFERENCE_EVALUATION" else None,
                    reference_risk=(decision or {}).get("policy", {}).get("risk", "") if evidence_class == "REFERENCE_EVALUATION" else "",
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
                    evidence_class=evidence_class,
                    production_eligible=production_eligible,
                    sample_identity=sample_identity,
                    independence_group=snapshot_hash({"task_type": task_type, "input_hash": decision["task"]["input_hash"]})
                    if (decision or {}).get("task", {}).get("input_hash") else "",
                    experiment_partition=campaign.get("partition", ""),
                    producer_contract_hash=str((decision or {}).get("task", {}).get("producer_contract_hash") or ""),
                )
            )
        return observations

    def campaign(self, *, project_id: str, campaign_id: str) -> dict[str, Any]:
        from novel_forge.modules.command_kernel.budget_runtime import provider_usage_accounted_sql
        from novel_forge.modules.command_kernel.routing_bootstrap import (
            campaign_contract, validate_bootstrap_history,
        )
        from novel_forge.modules.command_kernel.creative_budget_runtime import provider_campaign_contract_lineage

        with AuthorityUnitOfWork(self.database_url) as uow:
            authorized_contracts = provider_campaign_contract_lineage(uow.cursor, project_id)
            uow.cursor.execute(
                "SELECT content,content_hash FROM authority_runtime_policy_version WHERE owner='PROVIDER_ROUTING' AND project_id=%s ORDER BY created_at,policy_version",
                [project_id],
            )
            grants = {}
            for content, digest in uow.cursor.fetchall():
                if policy_hash(content) != digest:
                    raise KernelError("RUNTIME_POLICY_HASH_MISMATCH", "policy integrity failed")
                current = content.get("bootstrap_authorizations", [])
                validate_bootstrap_history(current, list(grants.values()),
                                           authorized_campaign_contracts=authorized_contracts)
                grants.update({grant["authorization_id"]: grant for grant in current})
            matched = [grant for grant in grants.values()
                       if (grant.get("campaign") or {}).get("campaign_id") == campaign_id]
            if not matched:
                raise KernelError("ROUTING_CAMPAIGN_NOT_FOUND", "no governed campaign exists in this project")
            uow.cursor.execute(
                f"""SELECT b.reservation_id,e.operation_id,e.external_effect_id,e.status,
                          b.status,b.accounted,b.currency,b.evidence->>'accounting_basis',
                          b.estimated_tokens,b.actual_tokens,b.reserved_amount,b.settled_amount,
                          e.request_payload #>> '{{_production_execution,capability_runtime,routing_decision,bootstrap_authorization,authorization,authorization_id}}',
                          e.request_payload #> '{{_production_execution,capability_runtime,routing_decision,bootstrap_authorization,authorization,campaign}}',
                          b.provider,b.evidence->>'cost_authorization_ref',b.evidence
                   FROM (SELECT *,{provider_usage_accounted_sql()} AS accounted
                         FROM authority_budget_reservation) b
                   JOIN authority_external_effect e USING(external_effect_id)
                   WHERE b.project_id=%s AND e.request_payload #>> '{{_production_execution,capability_runtime,routing_decision,bootstrap_authorization,authorization,campaign,campaign_id}}'=%s
                   ORDER BY b.created_at,b.reservation_id""",
                [project_id, campaign_id],
            )
            columns = ("reservation_id", "operation_id", "external_effect_id", "effect_status",
                       "reservation_status", "usage_accounted", "currency", "accounting_basis",
                       "estimated_tokens", "actual_tokens", "reserved_amount", "settled_amount",
                       "authorization_id", "campaign", "provider", "cost_authorization_ref", "budget_evidence")
            reservations = [dict(zip(columns, row, strict=True)) for row in uow.cursor.fetchall()]
            uow.cursor.execute(
                """SELECT operation.operation_id,operation.status,operation.definition_name,
                          operation.command_payload #>> '{payload,routing_bootstrap_authorization,authorization,authorization_id}',
                          operation.command_payload #>> '{payload,routing_bootstrap_authorization,authorization,task_type}',
                          operation.command_payload #>> '{payload,routing_bootstrap_authorization,authorization,purpose}',
                          operation.command_payload #> '{payload,routing_bootstrap_authorization,authorization,campaign}',
                          operation.causation_operation_id,
                          COALESCE(outputs.assets,'[]'::jsonb)
                   FROM authority_operation operation
                   LEFT JOIN LATERAL (
                       SELECT jsonb_agg(jsonb_build_object(
                           'asset_version_id',output.asset_version_id,'content_hash',output.content_hash,
                           'output_key',output.output_key,'role',output.role,
                           'reference_agreement',version.content->'reference_evaluation')
                           ORDER BY output.created_at,output.asset_version_id) assets
                       FROM authority_operation_output_asset output
                       JOIN authority_asset_version version USING(asset_version_id)
                       WHERE output.operation_id=operation.operation_id
                   ) outputs ON TRUE
                   WHERE operation.project_id=%s AND operation.command_payload
                     #>> '{payload,routing_bootstrap_authorization,authorization,campaign,campaign_id}'=%s
                   ORDER BY operation.created_at,operation.operation_id""",
                [project_id, campaign_id],
            )
            operation_columns = ("operation_id", "status", "definition_name", "authorization_id",
                                 "task_type", "purpose", "campaign_sample", "causation_operation_id", "outputs")
            operations = [dict(zip(operation_columns, row, strict=True)) for row in uow.cursor.fetchall()]
        used = [row for row in reservations if row["usage_accounted"]]
        pending = [row for row in reservations if row["reservation_status"] in {"RESERVED", "HELD_UNKNOWN"}
                   or row["effect_status"] in {"UNKNOWN", "SENT_UNKNOWN", "UNKNOWN_AMBIGUOUS", "RECONCILIATION_REQUIRED"}]
        entitlement_usage: dict[tuple[str, str], dict[str, Any]] = {}
        priced_usd = Decimal(0)
        tokens = 0
        for row in used:
            actual = max(int(row["actual_tokens"] or 0), int(row["budget_evidence"].get("actual_tokens") or 0))
            counted = actual if row["reservation_status"] == "SETTLED" else max(actual, int(row["estimated_tokens"] or 0))
            tokens += counted
            if row["accounting_basis"] == "ACCOUNT_ENTITLEMENT":
                key = (row["provider"], row["cost_authorization_ref"])
                lane = entitlement_usage.setdefault(key, {"provider": key[0], "authorization_ref": key[1],
                    "calls_used_or_reserved": 0, "conservative_tokens": 0, "usd": None})
                lane["calls_used_or_reserved"] += 1
                lane["conservative_tokens"] += counted
            else:
                recorded = Decimal(str(row["budget_evidence"].get("actual_amount") or "0"))
                priced_usd += max(recorded, Decimal(row["settled_amount"] or 0) if row["reservation_status"] == "SETTLED"
                                  else Decimal(row["reserved_amount"] or 0))
        return {
            "source": "POSTGRESQL_AUTHORITY_PROJECTION", "project_id": project_id,
            "scope": "BOOTSTRAP_SAMPLING_ONLY", "campaign": campaign_contract(matched[-1]["campaign"]),
            "grants": matched, "reservations": reservations, "operations": operations,
            "usage": {"calls_used_or_reserved": len(used),
                      "conservative_tokens": tokens,
                      "settled_or_reserved_usd": None if entitlement_usage else str(priced_usd),
                      "priced_settled_or_reserved_usd": str(priced_usd),
                      "entitlements": list(entitlement_usage.values()),
                      "unpriced_calls": sum(lane["calls_used_or_reserved"] for lane in entitlement_usage.values()),
                      "total_monetary_cost_status": "UNKNOWN" if entitlement_usage else "PRICED_ESTIMATE"},
            "unresolved_effect_ids": sorted({row["external_effect_id"] for row in pending}),
            "state": "RECONCILIATION_REQUIRED" if pending else "ACCOUNTED",
            "invoice_status": "NOT_VERIFIED", "production_qualification": "NOT_PROVEN",
        }

    def available_candidates(
        self, *, project_id: str, candidates: Sequence[ModelCandidate], now: datetime
    ) -> tuple[ModelCandidate, ...]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """SELECT COALESCE(
                            effect.request_payload #>> '{_production_execution,capability_runtime,routing_decision,selected,candidate,provider}',
                            dispatch.evidence->>'provider_id'),effect.model_id,COALESCE(dispatch.finished_at,dispatch.updated_at,dispatch.created_at),
                          dispatch.evidence #> '{production_execution,process_evidence}',
                          effect.external_effect_id
                   FROM authority_external_effect effect
                   JOIN authority_external_effect_dispatch dispatch USING(external_effect_id)
                   WHERE effect.project_id=%s AND effect.model_id=ANY(%s)
                     AND dispatch.evidence #>> '{production_execution,process_evidence,failure_class}'
                         IN ('RATE_LIMIT','PROVIDER_UNAVAILABLE','AUTHENTICATION_FAILED','PROVIDER_BUDGET_EXHAUSTED')
                     AND EXTRACT(EPOCH FROM (%s - COALESCE(dispatch.finished_at,dispatch.updated_at,dispatch.created_at)))
                         < CASE WHEN jsonb_typeof(dispatch.evidence #> '{production_execution,process_evidence,retry_after_seconds}')='number'
                           THEN (dispatch.evidence #>> '{production_execution,process_evidence,retry_after_seconds}')::numeric
                           ELSE 300 END
                   ORDER BY dispatch.created_at DESC""",
                [project_id, [candidate.model for candidate in candidates], now],
            )
            failures = uow.cursor.fetchall()
        result = []
        for candidate in candidates:
            for provider, model, occurred_at, evidence, effect_id in failures:
                if provider != candidate.provider or model != candidate.model:
                    continue
                failure = evidence["failure_class"]
                delay = evidence.get("retry_after_seconds")
                if (
                    not isinstance(delay, (int, float))
                    or not math.isfinite(delay)
                    or delay < 0
                ):
                    delay = (
                        300
                        if failure
                        in {"AUTHENTICATION_FAILED", "PROVIDER_BUDGET_EXHAUSTED"}
                        else 30
                    )
                try:
                    until = occurred_at + timedelta(seconds=delay)
                except OverflowError:
                    until = datetime.max.replace(tzinfo=occurred_at.tzinfo)
                if until > now:
                    candidate = replace(
                        candidate,
                        available=False,
                        availability_reason=f"{failure}:{effect_id}:until:{until.isoformat()}",
                    )
                    break
            result.append(candidate)
        return tuple(result)

    def history(
        self,
        *,
        project_id: str,
        task_type: str,
        chain_id: str = "",
        operation_id: str = "",
        operation_ids: Sequence[str] = (),
    ) -> tuple[dict[str, Any], ...]:
        if not chain_id:
            return ()
        lineage = tuple(operation_ids) or ((operation_id,) if operation_id else ())
        if not lineage or len(set(lineage)) != len(lineage):
            raise KernelError(
                "ROUTING_OPERATION_LINEAGE_INVALID",
                "routing history requires a unique Operation lineage",
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """SELECT effect.external_effect_id, effect.status, dispatch.created_at,
                          effect.request_payload #> '{_production_execution,capability_runtime,routing_decision}',
                          dispatch.evidence,
                          quality.content
                   FROM authority_external_effect effect
                   LEFT JOIN LATERAL (
                       SELECT evidence,COALESCE(finished_at,updated_at,created_at) AS created_at FROM authority_external_effect_dispatch
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
                   WHERE effect.project_id=%s AND effect.operation_id=ANY(%s::text[])
                     AND effect.request_payload->>'stage'=%s
                     AND effect.request_payload #>> '{_production_execution,capability_runtime,routing_decision,task,chain_id}'=%s
                   ORDER BY effect.created_at LIMIT 10""",
                [project_id, list(lineage), task_type, chain_id],
            )
            rows = uow.cursor.fetchall()
            gate_outcomes = (
                self.outcome_projection(
                    uow.cursor,
                    project_id=project_id,
                    effect_ids=[str(row[0]) for row in rows],
                )
                if self.outcome_projection is not None and rows
                else {}
            )
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
            gate = gate_outcomes.get(str(effect_id), {})
            if not failure and (
                gate.get("accepted") is False or gate.get("failure_class")
            ):
                failure = (
                    gate.get("failure_class")
                    if gate.get("failure_class")
                    in {
                        "QUALITY_FAILURE",
                        "CANON_CONFLICT",
                        "SCHEMA_REJECTION",
                        "AMBIGUOUS_JUDGE",
                    }
                    else "QUALITY_FAILURE"
                )
            history.append(
                {
                    "external_effect_id": effect_id,
                    "candidate_id": selected.get("candidate_id"),
                    "failure_class": failure,
                    "status": status,
                    "escalation": selected.get("escalation_only", False),
                    "outcome_refs": gate.get("evidence_refs", []),
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
        execution_environment: str = "production",
        provider_auth_profiles: Mapping[str, str] | None = None,
        review_requirement_resolver: Callable[..., dict[str, Any]] | None = None,
        provider_task_scope: Mapping[str, Sequence[str]] | None = None,
        membership_identity: Mapping[str, str] | None = None,
        provider_billing_accounts: Mapping[str, str] | None = None,
        provider_billing_identities: Mapping[str, Mapping[str, str]] | None = None,
        disabled_provider_reasons: Mapping[str, str] | None = None,
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
        self.execution_environment = execution_environment
        self.provider_auth_profiles = dict(provider_auth_profiles or {})
        self.membership_identity = dict(membership_identity or {})
        self.provider_billing_accounts = dict(provider_billing_accounts or {})
        self.provider_billing_identities = {key: dict(value) for key, value in (provider_billing_identities or {}).items()}
        self.disabled_provider_reasons = dict(disabled_provider_reasons or {})
        self.review_requirement_resolver = review_requirement_resolver
        self.provider_task_scope = None
        if provider_task_scope is not None:
            if (not isinstance(provider_task_scope, dict)
                or set(provider_task_scope) != {candidate.provider for candidate in self.candidates}
                or any(not isinstance(tasks, list) or any(not isinstance(task, str) or task not in TASK_TAXONOMY for task in tasks)
                       for tasks in provider_task_scope.values())):
                raise ValueError("ROUTING_PROVIDER_TASK_SCOPE_INVALID")
            self.provider_task_scope = {provider: sorted(set(tasks)) for provider, tasks in sorted(provider_task_scope.items())}
        money_limit = Decimal(task_money_limit)
        if self.task_token_limit <= 0 or not money_limit.is_finite() or money_limit < 0:
            raise ValueError("ROUTING_NONNEGATIVE_MONEY_AND_POSITIVE_TOKEN_BUDGET_REQUIRED")

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
        lineage_operation_ids: Sequence[str] = (),
        producer_contract: Mapping[str, Any] | None = None,
    ) -> tuple[Any, dict[str, Any]]:
        lineage = _routing_operation_lineage(operation_id, lineage_operation_ids)
        contract = dict(producer_contract or {})
        contract_hash = snapshot_hash(contract) if contract else ""
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
                if tuple(
                    original.get("lineage_operation_ids") or (operation_id,)
                ) != lineage or any(
                    original.get(key) != value
                    for key, value in {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "work_id": work_id,
                        "producer_contract": contract,
                        "producer_contract_hash": contract_hash,
                        "input_hash": input_hash,
                        "request_hash": snapshot_hash(request_input)
                        if request_input is not None
                        else "",
                        "declared_requirements": {
                            "risk": risk,
                            "quality_floor": quality_floor,
                            "chapter": chapter,
                            **({"provider_task_scope": self.provider_task_scope} if self.provider_task_scope is not None else {}),
                            **({"native_planning_repair": original["declared_requirements"]["native_planning_repair"]}
                               if original.get("declared_requirements", {}).get("native_planning_repair") else {}),
                            **({"cross_model_review": original["declared_requirements"]["cross_model_review"]}
                               if original.get("declared_requirements", {}).get("cross_model_review") else {}),
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
        normalized_stable_key = stable_key.replace(
            f"{operation_id}:{attempt_id}:", f"{operation_id}:", 1
        )
        if len(lineage) > 1:
            if not normalized_stable_key.startswith(operation_id + ":"):
                raise KernelError(
                    "ROUTING_OPERATION_LINEAGE_INVALID",
                    "repair successor stable key is outside its Operation lineage",
                )
            normalized_stable_key = (
                lineage[0] + normalized_stable_key[len(operation_id) :]
            )
        chain_id = snapshot_hash(normalized_stable_key)
        history = self.registry.history(
            project_id=project_id,
            operation_ids=lineage,
            task_type=task_type,
            chain_id=chain_id,
        )
        with AuthorityUnitOfWork(self.registry.database_url) as uow:
            uow.cursor.execute(
                """SELECT COALESCE(sum(CASE WHEN status='SETTLED' THEN settled_amount ELSE reserved_amount END),0),
                          COALESCE(sum(CASE WHEN status='SETTLED' THEN actual_tokens ELSE estimated_tokens END),0)
                   FROM authority_budget_reservation WHERE project_id=%s AND operation_id=ANY(%s::text[])
                     AND status IN ('RESERVED','HELD_UNKNOWN','SETTLED')
                     AND external_effect_id IN (SELECT external_effect_id FROM authority_external_effect
                       WHERE project_id=%s AND operation_id=ANY(%s::text[]) AND request_payload #>> '{_production_execution,capability_runtime,routing_decision,task,chain_id}'=%s)
                   """,
                [project_id, list(lineage), project_id, list(lineage), chain_id],
            )
            money_used, tokens_used = uow.cursor.fetchone()
        remaining_money = max(Decimal(0), Decimal(self.task_money_limit) - money_used)
        remaining_tokens = max(0, self.task_token_limit - int(tokens_used))
        policy_snapshot = self.registry.policy(project_id)
        from .execution_template import selected_template
        template = selected_template(policy_snapshot.get("policy", {}), work_id)
        budgets = self._candidate_budgets(
            project_id=project_id,
            work_id=work_id,
            operation_id=operation_id,
            stable_key=stable_key,
            template=template,
        )
        resource_estimate = None
        if template is not None:
            from .resource_planning import rolling_work_estimate
            with AuthorityUnitOfWork(self.registry.database_url) as uow:
                resource_estimate = rolling_work_estimate(uow.cursor, project_id=project_id, book_id=work_id,
                    input_tokens=input_tokens, output_tokens=output_tokens, template=template)
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
                "unavailable_channels": {provider: {"status": "NOT_RUN", "reason": reason}
                    for provider, reason in self.disabled_provider_reasons.items()},
                **({"work_resource_plan": resource_estimate} if resource_estimate is not None else {}),
                "candidates": budgets,
            },
            lineage_operation_ids=lineage,
            producer_contract=contract, producer_contract_hash=contract_hash,
        )
        now = datetime.now(timezone.utc)
        from .routing_catalog import deepseek_pricing_period

        candidates = self.registry.available_candidates(
            project_id=project_id,
            now=now,
            candidates=tuple(
                replace(
                    candidate,
                    estimated_price_multiplier="0.5"
                    if deepseek_pricing_period(now) == "OFF_PEAK"
                    else "1",
                )
                if candidate.provider == "deepseek"
                else candidate
                for candidate in self.candidates
            ),
        )
        observations = {
            candidate.candidate_id: self.registry.observations(
                project_id=project_id, task_type=task_type, candidate=candidate,
                producer_contract_hash=contract_hash, work_id=work_id,
                policy_snapshot=policy_snapshot,
            )
            for candidate in candidates
        }
        from .routing_policy import task_requirements

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
                **({"provider_task_scope": self.provider_task_scope} if self.provider_task_scope is not None else {}),
            },
            policy_snapshot=policy_snapshot,
            **requirements,
        )
        if template and template["version"] in {"creative-execution-template.v2", "creative-execution-template.v3", "creative-execution-template.v4", "creative-execution-template.v5","creative-execution-template.v6","creative-execution-template.v7", "creative-execution-template.v8", "creative-execution-template.v9"} and template["mode"] == "CREATIVE_VALIDATION":
            from .planning_repair_routing import native_planning_repair
            with AuthorityUnitOfWork(self.registry.database_url) as uow:
                repair_evidence = native_planning_repair(uow.cursor,project_id=project_id,book_id=work_id,
                    operation_id=operation_id,task_type=task_type,lineage=lineage,
                    evidence_version='native-planning-repair-evidence.v3' if template['version'] in {'creative-execution-template.v4','creative-execution-template.v5','creative-execution-template.v6','creative-execution-template.v7','creative-execution-template.v8','creative-execution-template.v9'} else 'native-planning-repair-evidence.v2')
            if repair_evidence:
                task = replace(task,declared_requirements={**task.declared_requirements,
                    "native_planning_repair":repair_evidence})
        from novel_forge.modules.command_kernel.routing_bootstrap import (
            load_bootstrap_authorization,
        )
        from .routing_bootstrap import benchmark_decision, bind_diagnostic_escalation_reason

        with AuthorityUnitOfWork(self.registry.database_url) as uow:
            bootstrap = load_bootstrap_authorization(
                uow.cursor, project_id=project_id, operation_id=operation_id
            )
        if bootstrap:
            task = bind_diagnostic_escalation_reason(
                task, candidates, bootstrap, environment=self.execution_environment
            )
        else:
            from .author_supervision import matching_grant
            from .cross_model_review import REVIEW_TASKS
            supervised_book = any(book["book_id"] == work_id for book in policy_snapshot.get("policy", {}).get("author_supervised_books", []))
            if task_type in REVIEW_TASKS and ((not template and (supervised_book or matching_grant(asdict(task), now=now))) or (template and (template["require_independent_review"] or template["mode"] == "STRICT_PRODUCTION" and (supervised_book or matching_grant(asdict(task), now=now))))):
                grant = matching_grant(asdict(task), now=now)
                reviewers = [asdict(candidate) for candidate in candidates if grant
                    and candidate.candidate_id == grant["candidate_id"] and candidate.model_revision == grant["model_revision"]]
                authorized_reviewer = ({key: reviewers[0][key] for key in ("candidate_id", "provider", "model", "model_revision")}
                    if len(reviewers) == 1 else None)
                if self.review_requirement_resolver is None:
                    raise KernelError("CROSS_MODEL_REVIEW_BINDER_REQUIRED", "Production review requires its domain-owned source binder")
                with AuthorityUnitOfWork(self.registry.database_url) as uow:
                    cross_review = self.review_requirement_resolver(uow.cursor, project_id=project_id,
                        book_id=work_id, operation_id=operation_id, task_type=task_type,
                        request_input=request_input or {}, authorized_reviewer=authorized_reviewer)
                task = replace(task, declared_requirements={**task.declared_requirements, "cross_model_review": cross_review})
        decision = CostAwareRouter().explain(task, candidates, observations, now=now)
        if template and not bootstrap:
            from .execution_template import template_decision
            decision = template_decision(decision)
        if bootstrap:
            decision = benchmark_decision(
                decision, bootstrap, environment=self.execution_environment
            )
        elif not template and (policy_snapshot.get("policy", {}).get("author_supervised_authorizations")
                or policy_snapshot.get("policy", {}).get("author_supervised_books")):
            from .author_supervision import supervised_decision
            decision = supervised_decision(decision, now=now)
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
        self, *, project_id: str, work_id: str, operation_id: str, stable_key: str,
        template: Mapping[str, Any] | None = None,
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
                if template is not None:
                    result.update(resource_control_version="billing-channel-resources.v1", remaining_tokens=candidate.context_limit, remaining_calls=None)
                    if candidate.provider == "codex-cli":
                        result.update(remaining_money=None, membership=True, membership_identity=self.membership_identity)
                    elif candidate.provider == "deepseek":
                        from .execution_template import paid_usage
                        paid = template["deepseek"]
                        account = self.provider_billing_accounts.get("deepseek", "")
                        identity = self.provider_billing_identities.get("deepseek", {})
                        authorized = paid is not None and bool(identity) and paid["account_ref"] == account
                        used = paid_usage(uow.cursor, project_id=project_id, book_id=work_id)
                        result.update(remaining_money=str(max(Decimal(0), Decimal(paid["maximum_amount"]) - used)) if authorized else "0",
                                      paid_authorized=authorized, account_ref=account, billing_identity=identity, used_or_reserved=str(used))
                    budgets[candidate.candidate_id] = result
                    continue
                if candidate.pricing.accounting_basis == "ACCOUNT_ENTITLEMENT":
                    uow.cursor.execute(
                        f"""SELECT count(*) FROM authority_budget_reservation
                            WHERE provider=%s AND evidence->>'cost_authorization_ref'=%s
                              AND {provider_usage_accounted_sql()}""",
                        [candidate.provider, candidate.authorization_ref],
                    )
                    result["remaining_calls"] = max(
                        0, (candidate.quota_remaining or 0) - int(uow.cursor.fetchone()[0])
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

    def _selected_route(self, base: Any, snapshot: Mapping[str, Any]) -> Any:
        template = None
        frozen_scope = snapshot["task"].get("declared_requirements", {}).get("provider_task_scope")
        if frozen_scope != self.provider_task_scope:
            raise KernelError("ROUTING_REQUEST_DRIFT", "Provider task authorization differs from the frozen request")
        if snapshot.get("status") == "BENCHMARK_SELECTED":
            from novel_forge.modules.command_kernel.routing_bootstrap import (
                load_bootstrap_authorization,
            )

            task = snapshot["task"]
            with AuthorityUnitOfWork(self.registry.database_url) as uow:
                bootstrap = load_bootstrap_authorization(
                    uow.cursor,
                    project_id=task["project_id"],
                    operation_id=task["operation_id"],
                    check_expiry=False,
                )
            if (
                self.execution_environment != "validation"
                or not bootstrap
                or snapshot.get("bootstrap_authorization") != bootstrap
                or snapshot.get("production_eligible") is not False
            ):
                raise KernelError(
                    "ROUTING_BOOTSTRAP_SCOPE_MISMATCH",
                    "benchmark route lacks its admitted validation grant",
                )
        elif snapshot.get("status") == "AUTHOR_SUPERVISED_SELECTED":
            from .author_supervision import verify_frozen_supervision, verify_policy_provenance
            verify_frozen_supervision(snapshot)
            with AuthorityUnitOfWork(self.registry.database_url) as uow:
                verify_policy_provenance(uow.cursor, snapshot)
        elif snapshot.get("status") != "SELECTED" or snapshot.get(
            "bootstrap_authorization"
        ):
            raise KernelError(
                "PROVIDER_ROUTING_BLOCKED", str(snapshot.get("decision_id"))
            )
        if snapshot.get("resource_control_version"):
            if snapshot.get("mode") == "CREATIVE_VALIDATION" and self.execution_environment != "validation":
                raise KernelError("CREATIVE_ROUTING_ENVIRONMENT_INVALID", "Creative validation requires the validation runtime profile")
            from .execution_template import verify_template_provenance
            with AuthorityUnitOfWork(self.registry.database_url) as uow:
                template = verify_template_provenance(uow.cursor, snapshot)
                from .planning_repair_routing import verify_native_repair
                verify_native_repair(uow.cursor,snapshot)
            selected_candidate = snapshot["selected"]["candidate"]
            if selected_candidate["provider"] == "codex-cli" and (self.membership_identity.get("billing_channel") != "ACCOUNT_ENTITLEMENT"
                    or snapshot["task"]["budget_snapshot"]["candidates"][selected_candidate["candidate_id"]].get("membership_identity") != self.membership_identity):
                raise KernelError("MEMBERSHIP_BILLING_IDENTITY_MISMATCH", "Frozen route requires observed ChatGPT membership")
        candidate = snapshot["selected"]["candidate"]
        if snapshot.get("resource_control_version") and candidate["provider"] == "deepseek":
            budget = snapshot["task"]["budget_snapshot"]["candidates"][candidate["candidate_id"]]
            if not self.provider_billing_accounts.get("deepseek") or budget.get("account_ref") != self.provider_billing_accounts["deepseek"]:
                raise KernelError("PAID_BILLING_ACCOUNT_DRIFT", "DeepSeek dispatch must retain its configured billing account")
            if not self.provider_billing_identities.get("deepseek") or budget.get("billing_identity") != self.provider_billing_identities["deepseek"]:
                raise KernelError("PAID_BILLING_CREDENTIAL_DRIFT", "DeepSeek credential differs from its frozen billing-account binding")
        if frozen_scope is not None and snapshot["task"]["task_type"] not in frozen_scope.get(candidate["provider"], ()):
            raise KernelError("PROVIDER_TASK_NOT_AUTHORIZED", "Selected Provider is outside its frozen task scope")
        if candidate.get("authorized_tasks") is not None and snapshot["task"]["task_type"] not in candidate["authorized_tasks"]:
            raise KernelError("MODEL_TASK_NOT_AUTHORIZED", "Selected model is outside its frozen task scope")
        cross_review = snapshot["task"].get("declared_requirements", {}).get("cross_model_review")
        if cross_review:
            from .cross_model_review import reviewer_rejection
            rejection = reviewer_rejection(cross_review, candidate)
            if rejection:
                raise KernelError(rejection, "Reviewer selection differs from the frozen source receipt")
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
        if template is not None:
            identity = f"{candidate['provider']}:{candidate['model']}:{candidate['reasoning']}"
            if identity != candidate["candidate_id"] or identity not in template["allowed_candidates"]:
                raise KernelError("TEMPLATE_MODEL_UNAUTHORIZED", identity)
        if hasattr(base, "task_reasoning_authorization"):
            changes["task_reasoning_authorization"] = (
                (candidate["reasoning"], "sha256:" + snapshot["task"]["policy_snapshot"]["policy_hash"].removeprefix("sha256:"))
                if template is not None and template["mode"] == "CREATIVE_VALIDATION" else None
            )
        if self.provider_auth_profiles:
            auth_profile = self.provider_auth_profiles.get(candidate["provider"])
            if not auth_profile:
                raise KernelError("PROVIDER_AUTH_PROFILE_REQUIRED", candidate["provider"])
            changes["auth_profile_ref"] = auth_profile
        if hasattr(base, "model_context_limit"):
            changes.update(
                model_context_limit=candidate["context_limit"],
                **({"model_output_limit": candidate["output_limit"]} if hasattr(base, "model_output_limit") else {}),
                token_accounting_method="DEEPSEEK_UTF8_BYTES_UPPER_BOUND_V1"
                if candidate["provider"] == "deepseek"
                else "CODEX_CLI_APPLICATION_UTF8_BYTES_UPPER_BOUND_V1"
                if candidate["provider"] == "codex-cli"
                else base.token_accounting_method,
                token_accounting_evidence_ref=candidate["capability_version"],
            )
        return replace(base, **changes)

    def _frozen_output_protocol(
        self, identity: Mapping[str, Any], admission: Any,
        metadata: Mapping[str, Any], task: Mapping[str, Any], provider: str,
    ) -> str:
        from .provider_admission import (
            DEEPSEEK_STRICT_PROTOCOL,
            provider_request_protocol,
        )

        expected = provider_request_protocol(provider)
        if identity.get("protocol") != DEEPSEEK_STRICT_PROTOCOL:
            return expected
        capability = metadata["capability_runtime"]
        binding = admission.content.get("contract", admission.content)
        version = str(capability.get("materialization_asset_version_id") or "")
        content_hash = capability.get("materialization_content_hash")
        if (
            not version
            or not content_hash
            or binding.get("capability_materialization_asset_version_id") != version
            or binding.get("capability_materialization_content_hash") != content_hash
        ):
            raise KernelError(
                "ROUTING_ADMISSION_IDENTITY_MISMATCH",
                "strict output materialization binding",
            )
        document = self.registry.query.require(
            project_id=task["project_id"], asset_version_id=version
        )
        if (
            document.asset_type != "capability_materialization_manifest"
            or document.content_hash != content_hash
        ):
            raise KernelError(
                "ROUTING_ADMISSION_IDENTITY_MISMATCH",
                "strict output materialization identity",
            )
        materialization = document.content.get("contract", document.content)
        artifacts = materialization.get("pack_artifacts") or {}
        policy = (artifacts.get("context_policy") or {}).get("content") or {}
        modes = (policy.get("provider_output_modes") or {}).get(task["task_type"]) or {}
        try:
            expected = provider_request_protocol(
                provider, output_mode=str(modes.get(provider) or "")
            )
            schema = json.loads(identity.get("output_schema_json") or "null")
        except (ValueError, TypeError) as exc:
            raise KernelError(
                "ROUTING_ADMISSION_IDENTITY_MISMATCH", "strict output policy"
            ) from exc
        if (
            expected != DEEPSEEK_STRICT_PROTOCOL
            or schema is None
            or schema != (materialization.get("output_schema") or {}).get("content")
        ):
            raise KernelError(
                "ROUTING_ADMISSION_IDENTITY_MISMATCH", "strict output schema or policy"
            )
        return expected

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
            frozen_lineage = task.get("lineage_operation_ids") or ()
            if frozen_lineage and not isinstance(frozen_lineage, (list, tuple)):
                raise KernelError("ROUTING_DECISION_SCOPE_MISMATCH", version_id)
            try:
                _routing_operation_lineage(
                    str(task.get("operation_id") or ""), frozen_lineage
                )
            except KernelError as exc:
                raise KernelError(
                    "ROUTING_DECISION_SCOPE_MISMATCH", version_id
                ) from exc
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
            frozen_scope = task.get("declared_requirements", {}).get("provider_task_scope")
            if frozen_scope != self.provider_task_scope:
                raise KernelError("ROUTING_REQUEST_DRIFT", "Provider task authorization differs from the frozen Effect")
            if frozen_scope is not None and task["task_type"] not in frozen_scope.get(content["selected"]["candidate"]["provider"], ()):
                raise KernelError("PROVIDER_TASK_NOT_AUTHORIZED", "Effect Provider is outside its frozen task scope")
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
            source_observation = (
                task["task_type"] == "source.deconstruction.observe"
                and (payload.get("input") or {}).get("observation_boundary", {}).get("boundary_type") == "SOURCE_OBSERVATION"
            )
            expected_protocol = self._frozen_output_protocol(
                identity, admission, metadata, task, selected["provider"]
            )

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
                != expected_protocol
                or str(identity.get("reasoning_effort") or "")
                != (selected["reasoning"] if selected["provider"] == "deepseek" or source_observation else "")
                or admitted_pricing != selected["pricing"]
            ):
                raise KernelError("ROUTING_ADMISSION_IDENTITY_MISMATCH", version_id)
            return self._selected_route(base, frozen), dict(frozen)
        raise KernelError("ROUTING_FROZEN_DECISION_REQUIRED", str(payload.get("stage")))


def validate_routed_reservation(
    decision: Mapping[str, Any], *, reserved_tokens: int, reserved_amount: str | None,
) -> None:
    selected = decision.get("selected")
    if decision.get("status") not in {"SELECTED", "BENCHMARK_SELECTED", "AUTHOR_SUPERVISED_SELECTED"} or not selected:
        raise KernelError("ROUTING_RESERVATION_DECISION_INVALID", "reservation requires a selected route")
    task, candidate = decision["task"], selected["candidate"]
    provider_scope = task.get("declared_requirements", {}).get("provider_task_scope")
    if provider_scope is not None and task["task_type"] not in provider_scope.get(candidate["provider"], ()):
        raise KernelError("PROVIDER_TASK_NOT_AUTHORIZED", "Reservation Provider is outside its frozen task scope")
    if candidate.get("authorized_tasks") is not None and task["task_type"] not in candidate["authorized_tasks"]:
        raise KernelError("MODEL_TASK_NOT_AUTHORIZED", "Reservation model is outside its frozen task scope")
    budget = task.get("budget_snapshot", {}).get("candidates", {}).get(candidate["candidate_id"], {})
    from .execution_template import decision_template
    template = decision_template(decision)
    token_limits = [int(candidate["context_limit"])] if template else [int(task["remaining_tokens"])]
    if "remaining_tokens" in budget:
        token_limits.append(int(budget["remaining_tokens"]))
    grant = (decision.get("bootstrap_authorization") or decision.get("author_supervision") or {}).get("authorization", {})
    if decision.get("status") == "AUTHOR_SUPERVISED_SELECTED":
        from .author_supervision import verify_frozen_supervision
        verify_frozen_supervision(decision)
    if grant:
        token_limits.append(int(grant["maximum_tokens"]))
    limit = min(token_limits)
    if reserved_tokens <= 0 or reserved_tokens > limit or budget.get("remaining_calls") == 0:
        raise KernelError("ROUTING_RESERVATION_BUDGET_EXCEEDED",
                          f"complete Provider reservation tokens={reserved_tokens} exceeds available limit={limit}")
    if candidate["pricing"]["accounting_basis"] == "PRICED":
        amount = Decimal(reserved_amount) if reserved_amount is not None else Decimal("NaN")
        money_limits = [] if template else [Decimal(task["remaining_money"])]
        if "remaining_money" in budget:
            money_limits.append(Decimal(str(budget["remaining_money"])))
        if grant.get("maximum_amount") is not None:
            money_limits.append(Decimal(grant["maximum_amount"]))
        if not amount.is_finite() or amount < 0 or amount > min(money_limits):
            raise KernelError("ROUTING_RESERVATION_BUDGET_EXCEEDED",
                              "complete Provider reservation exceeds the frozen monetary limit")


def routed_reservation(
    decision: Mapping[str, Any], *, input_tokens: int, output_tokens: int
) -> str | None:
    from .cost_routing import PricingSnapshot

    price = PricingSnapshot(**decision["selected"]["candidate"]["pricing"])
    if price.accounting_basis == "ACCOUNT_ENTITLEMENT":
        return None
    return str(price.amount(input_tokens, output_tokens))
