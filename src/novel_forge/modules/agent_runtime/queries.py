"""Strong PostgreSQL projections for Agent Definitions and Agent Runs."""

from __future__ import annotations

from datetime import datetime
from dataclasses import asdict
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .contracts import (
    AgentDomainCommitStatus,
    AgentExecutionEmbedding,
    AgentSchedulingAuthority,
    derive_agent_run_status,
)


class AgentRuntimeQuery:
    """Compose Agent Run views from the existing Authority fact owners."""

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("Agent Runtime query requires PostgreSQL")
        self.database_url = database_url

    def list_agents(
        self,
        *,
        agent_id: str = "",
        activation_status: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            return uow.repositories.agent_runtime.list_definitions(
                agent_id=agent_id,
                activation_status=activation_status,
                limit=limit,
            )

    def require_harness_session(
        self, *, project_id: str, agent_session_id: str
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            session = uow.repositories.agent_runtime.require_harness_session(
                agent_session_id
            )
            if session.project_id != project_id:
                raise KernelError(
                    "AGENT_HARNESS_SESSION_NOT_FOUND", "Agent session does not exist"
                )
            uow.cursor.execute(
                """
                SELECT sequence, request_id, turn_number, event_type, payload,
                       attempt_id, external_effect_id, trace_id, payload_hash,
                       created_at
                FROM authority_agent_transcript_event
                WHERE agent_session_id=%s
                ORDER BY sequence
                """,
                [agent_session_id],
            )
            transcript = [
                {
                    "sequence": int(row[0]),
                    "request_id": str(row[1]),
                    "turn_number": int(row[2]),
                    "event_type": str(row[3]),
                    "payload": dict(row[4] or {}),
                    "attempt_id": str(row[5] or ""),
                    "external_effect_id": str(row[6] or ""),
                    "trace_id": str(row[7]),
                    "payload_hash": str(row[8]),
                    "created_at": _timestamp(row[9]),
                }
                for row in uow.cursor.fetchall()
            ]
        payload = asdict(session)
        payload["role"] = session.role.value
        payload["status"] = session.status.value
        payload["tool_policy"] = [
            {
                **asdict(tool),
                "kind": tool.kind.value,
                "allowed_roles": [role.value for role in tool.allowed_roles],
            }
            for tool in session.tool_policy
        ]
        return {**payload, "transcript": transcript}

    def recovery_health(self, *, project_id: str = "") -> dict[str, Any]:
        """Aggregate derived recovery backlog without creating runtime state."""

        project_clause = "AND operation.project_id=%s" if project_id else ""
        parameters: list[Any] = [project_id] if project_id else []
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                f"""
                SELECT binding.binding_id, binding.attempt_id,
                       binding.fencing_token, binding.book_id,
                       binding.created_at, operation.operation_id,
                       operation.definition_name, attempt.attempt_number,
                       attempt.status, current_lease.fencing_token,
                       effects.planned, effects.waiting, effects.unknown,
                       effects.reconciliation, effects.succeeded,
                       candidate.candidate_version_id,
                       supersession.supersession_id,
                       decision.decision_id, domain_asset.asset_version_id,
                       collaboration_commit.commit_id
                FROM authority_agent_runtime_binding AS binding
                JOIN authority_operation AS operation
                  ON operation.operation_id=binding.operation_id
                JOIN authority_attempt AS attempt
                  ON attempt.attempt_id=binding.attempt_id
                LEFT JOIN LATERAL (
                    SELECT lease.fencing_token
                    FROM authority_lease_acquisition AS lease
                    WHERE lease.attempt_id=binding.attempt_id
                    ORDER BY lease.fencing_token DESC
                    LIMIT 1
                ) AS current_lease ON TRUE
                LEFT JOIN LATERAL (
                    SELECT
                        BOOL_OR(effect.status='READY') AS planned,
                        BOOL_OR(effect.status IN (
                            'DISPATCHING','DISPATCHED'
                        )) AS waiting,
                        BOOL_OR(effect.status='UNKNOWN') AS unknown,
                        BOOL_OR(effect.status='RECONCILIATION_REQUIRED')
                            AS reconciliation,
                        BOOL_OR(effect.status='SUCCEEDED') AS succeeded
                    FROM authority_external_effect AS effect
                    WHERE effect.operation_id=binding.operation_id
                      AND effect.request_payload
                          ->'_production_execution'->>'attempt_id'
                          =binding.attempt_id
                ) AS effects ON TRUE
                LEFT JOIN authority_agent_work_order AS work_order
                  ON work_order.work_order_id=binding.work_order_id
                LEFT JOIN authority_agent_candidate_version AS candidate
                  ON candidate.originating_turn_id=work_order.turn_id
                LEFT JOIN authority_agent_candidate_supersession AS supersession
                  ON supersession.superseded_candidate_version_id=
                     candidate.candidate_version_id
                LEFT JOIN authority_agent_collaboration_decision AS decision
                  ON decision.candidate_version_id=candidate.candidate_version_id
                LEFT JOIN authority_agent_collaboration_commit
                  AS collaboration_commit
                  ON collaboration_commit.candidate_version_id=
                     candidate.candidate_version_id
                LEFT JOIN LATERAL (
                    SELECT output.asset_version_id
                    FROM authority_operation_output_asset AS output
                    WHERE output.operation_id=binding.operation_id
                    ORDER BY output.created_at DESC, output.asset_version_id
                    LIMIT 1
                ) AS domain_asset ON TRUE
                WHERE TRUE {project_clause}
                ORDER BY binding.created_at, binding.binding_id
                """,
                parameters,
            )
            rows = uow.cursor.fetchall()
        metric_names = (
            "planned_effect_not_dispatched",
            "waiting_external_result",
            "unknown_external_effect",
            "reconciliation_required",
            "completed_effect_candidate_missing",
            "candidate_domain_decision_pending",
            "domain_asset_commit_missing",
            "commit_attempt_result_missing",
            "superseded_candidate",
            "standalone_candidate_ready",
        )
        metrics = {name: 0 for name in metric_names}
        scopes: list[dict[str, Any]] = []
        backlog_ages: list[int] = []
        for row in rows:
            standalone = str(row[6]) == "agent.candidate.execute"
            candidate_id = str(row[15] or "")
            superseded = bool(row[16])
            commit_id = str(row[19] or "")
            categories: list[str] = []
            if superseded:
                categories.append("superseded_candidate")
            else:
                if bool(row[10]):
                    categories.append("planned_effect_not_dispatched")
                if bool(row[11]):
                    categories.append("waiting_external_result")
                if bool(row[12]):
                    categories.append("unknown_external_effect")
                if bool(row[13]):
                    categories.append("reconciliation_required")
                if bool(row[14]) and not candidate_id:
                    categories.append("completed_effect_candidate_missing")
                if standalone and candidate_id and not commit_id:
                    categories.append("standalone_candidate_ready")
                if not standalone and candidate_id and not row[17]:
                    categories.append("candidate_domain_decision_pending")
                if not standalone and row[17] and not commit_id:
                    categories.append("domain_asset_commit_missing")
                if commit_id and str(row[8]) != "SUCCEEDED":
                    categories.append("commit_attempt_result_missing")
            if not categories:
                continue
            for category in categories:
                metrics[category] += 1
            age_seconds = max(
                0,
                int(
                    (
                        datetime.now(row[4].tzinfo)
                        - row[4]
                    ).total_seconds()
                ),
            )
            if any(
                item not in {
                    "superseded_candidate",
                    "standalone_candidate_ready",
                }
                for item in categories
            ):
                backlog_ages.append(age_seconds)
            scopes.append(
                {
                    "binding_id": str(row[0]),
                    "operation_id": str(row[5]),
                    "attempt_id": str(row[1]),
                    "attempt_number": int(row[7]),
                    "book_id": str(row[3]),
                    "execution_fencing_token": int(row[2]),
                    "recovery_fencing_token": int(row[9] or row[2]),
                    "categories": categories,
                    "age_seconds": age_seconds,
                }
            )
        return {
            **metrics,
            "recoverable_runtime_binding_count": len(
                {
                    scope["binding_id"]
                    for scope in scopes
                    if any(
                        category
                        not in {
                            "superseded_candidate",
                            "standalone_candidate_ready",
                        }
                        for category in scope["categories"]
                    )
                }
            ),
            "unknown_external_effect_count": (
                metrics["unknown_external_effect"]
                + metrics["reconciliation_required"]
            ),
            "oldest_recovery_age_seconds": max(backlog_ages, default=0),
            "candidate_without_domain_commit_count": (
                metrics["candidate_domain_decision_pending"]
                + metrics["domain_asset_commit_missing"]
            ),
            "frozen_binding_without_final_result_count": (
                metrics["completed_effect_candidate_missing"]
                + metrics["commit_attempt_result_missing"]
            ),
            "scopes": scopes,
        }

    def list_runs(
        self,
        *,
        project_id: str,
        agent_id: str = "",
        book_id: str = "",
        agent_run_id: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not project_id:
            raise ValueError("project_id is required")
        if limit <= 0 or limit > 500:
            raise ValueError("Agent run query limit must be between 1 and 500")
        clauses = ["operation.project_id=%s"]
        parameters: list[Any] = [project_id]
        if agent_id:
            clauses.append(
                "COALESCE(binding.agent_id, operation.command_payload->>'agent_id')=%s"
            )
            parameters.append(agent_id)
        if book_id:
            clauses.append(
                "COALESCE(binding.book_id, operation.command_payload->>'book_id')=%s"
            )
            parameters.append(book_id)
        if agent_run_id:
            clauses.append("operation.operation_id=%s")
            parameters.append(agent_run_id)
        where = " AND ".join(clauses)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                f"""
                SELECT operation.operation_id, operation.project_id,
                       operation.workspace_id,
                       COALESCE(binding.book_id,
                                operation.command_payload->>'book_id', ''),
                       COALESCE(binding.agent_id,
                                operation.command_payload->>'agent_id', ''),
                       COALESCE(binding.agent_definition_version,
                                NULLIF(operation.command_payload
                                    ->>'agent_definition_version', '')::int),
                       COALESCE(binding.capability_id,
                                operation.command_payload->>'capability_id', ''),
                       operation.definition_name,
                       operation.definition_version,
                       operation.status, operation.version,
                       attempt.attempt_id, attempt.attempt_number,
                       attempt.status, attempt.worker_id,
                       lease.lease_id, lease.fencing_token, lease.status,
                       effect.status,
                       binding.binding_id,
                       binding.capability_pack_ref,
                       binding.capability_pack_compilation_hash,
                       binding.context_bundle_asset_version_id,
                       binding.route_snapshot_ref,
                       binding.input_manifest_ref,
                       operation.trace_id, operation.span_id,
                       operation.correlation_id,
                       operation.created_at, operation.updated_at,
                       binding.fencing_token
                FROM authority_operation AS operation
                LEFT JOIN LATERAL (
                    SELECT current.*
                    FROM authority_agent_runtime_binding AS current
                    WHERE current.operation_id=operation.operation_id
                    ORDER BY current.created_at DESC, current.binding_id DESC
                    LIMIT 1
                ) AS binding ON TRUE
                LEFT JOIN LATERAL (
                    SELECT current.attempt_id, current.attempt_number,
                           current.status, current.worker_id
                    FROM authority_attempt AS current
                    WHERE current.operation_id=operation.operation_id
                    ORDER BY current.attempt_number DESC
                    LIMIT 1
                ) AS attempt ON TRUE
                LEFT JOIN LATERAL (
                    SELECT current.lease_id, current.fencing_token,
                           current.status
                    FROM authority_lease_acquisition AS current
                    WHERE current.attempt_id=attempt.attempt_id
                    ORDER BY current.fencing_token DESC
                    LIMIT 1
                ) AS lease ON TRUE
                LEFT JOIN LATERAL (
                    SELECT current.status
                    FROM authority_external_effect AS current
                    WHERE current.operation_id=operation.operation_id
                    ORDER BY
                        CASE WHEN current.status IN (
                            'UNKNOWN', 'RECONCILIATION_REQUIRED'
                        ) THEN 0 ELSE 1 END,
                        current.created_at DESC
                    LIMIT 1
                ) AS effect ON TRUE
                WHERE {where}
                  AND (
                    binding.operation_id IS NOT NULL
                    OR operation.definition_name='agent.candidate.execute'
                  )
                ORDER BY operation.created_at DESC, operation.operation_id
                LIMIT %s
                """,
                [*parameters, limit],
            )
            rows = uow.cursor.fetchall()
        return [self._run_summary(row) for row in rows]

    def require_run(self, *, project_id: str, agent_run_id: str) -> dict[str, Any]:
        runs = self._run_header(project_id=project_id, agent_run_id=agent_run_id)
        if runs is None:
            raise KernelError(
                "AGENT_RUN_NOT_FOUND",
                "Agent Run projection does not exist in the requested project",
            )
        operation_id = str(runs["operation_id"])
        with AuthorityUnitOfWork(self.database_url) as uow:
            cursor = uow.cursor
            cursor.execute(
                """
                SELECT attempt_id, attempt_number, max_attempts, status,
                       worker_id, queued_at, started_at, checkpointed_at,
                       result_submitted_at, finished_at, checkpoint,
                       result, error
                FROM authority_attempt
                WHERE operation_id=%s
                ORDER BY attempt_number
                """,
                [operation_id],
            )
            attempts = [
                {
                    "attempt_id": row[0],
                    "attempt_number": int(row[1]),
                    "max_attempts": int(row[2]),
                    "status": row[3],
                    "worker_id": row[4],
                    "queued_at": _timestamp(row[5]),
                    "started_at": _timestamp(row[6]),
                    "checkpointed_at": _timestamp(row[7]),
                    "result_submitted_at": _timestamp(row[8]),
                    "finished_at": _timestamp(row[9]),
                    "checkpoint": dict(row[10] or {}),
                    "result": dict(row[11] or {}),
                    "error": dict(row[12] or {}),
                }
                for row in cursor.fetchall()
            ]
            cursor.execute(
                """
                SELECT binding_id, workflow_definition_ref, workflow_node_id,
                       operation_definition_name,
                       operation_definition_version,
                       operation_definition_hash, operation_id, attempt_id,
                       fencing_token, work_order_id,
                       agent_id, agent_definition_version,
                       agent_definition_hash,
                       capability_id, capability_version, capability_hash,
                       execution_capability_id,
                       chapter_node_binding_id,
                       chapter_node_binding_version,
                       capability_pack_ref,
                       capability_pack_compilation_hash,
                       context_bundle_asset_version_id, context_bundle_hash,
                       prompt_bundle_ref, prompt_bundle_hash,
                       skill_bundle_ref, skill_bundle_hash,
                       tool_policy_ref, tool_policy_hash,
                       tool_permission_snapshot_ref,
                       tool_permission_snapshot_hash,
                       context_policy_ref, context_policy_hash,
                       route_snapshot_ref, route_snapshot_hash,
                       input_manifest_ref, input_manifest_hash,
                       budget_policy_ref, timeout_policy_ref,
                       approval_policy_ref, validation_policy_ref,
                       commit_policy_ref, commit_authority,
                       release_sha, binding_hash, created_at,
                       capability_pack_deployment_id,
                       capability_pack_activation_version,
                       capability_pack_binding_set_id,
                       capability_pack_binding_set_hash,
                       capability_pack_scope_type,
                       capability_pack_assignment_ref
                FROM authority_agent_runtime_binding
                WHERE operation_id=%s
                ORDER BY created_at, binding_id
                """,
                [operation_id],
            )
            runtime_binding_fields = (
                "binding_id",
                "workflow_definition_ref",
                "workflow_node_id",
                "operation_definition_name",
                "operation_definition_version",
                "operation_definition_hash",
                "operation_id",
                "attempt_id",
                "fencing_token",
                "work_order_id",
                "agent_id",
                "agent_definition_version",
                "agent_definition_hash",
                "capability_id",
                "capability_version",
                "capability_hash",
                "execution_capability_id",
                "chapter_node_binding_id",
                "chapter_node_binding_version",
                "capability_pack_ref",
                "capability_pack_compilation_hash",
                "context_bundle_asset_version_id",
                "context_bundle_hash",
                "prompt_bundle_ref",
                "prompt_bundle_hash",
                "skill_bundle_ref",
                "skill_bundle_hash",
                "tool_policy_ref",
                "tool_policy_hash",
                "tool_permission_snapshot_ref",
                "tool_permission_snapshot_hash",
                "context_policy_ref",
                "context_policy_hash",
                "route_snapshot_ref",
                "route_snapshot_hash",
                "input_manifest_ref",
                "input_manifest_hash",
                "budget_policy_ref",
                "timeout_policy_ref",
                "approval_policy_ref",
                "validation_policy_ref",
                "commit_policy_ref",
                "commit_authority",
                "release_sha",
                "binding_hash",
                "created_at",
                "capability_pack_deployment_id",
                "capability_pack_activation_version",
                "capability_pack_binding_set_id",
                "capability_pack_binding_set_hash",
                "capability_pack_scope_type",
                "capability_pack_assignment_ref",
            )
            runtime_bindings = []
            for row in cursor.fetchall():
                binding = dict(zip(runtime_binding_fields, row, strict=True))
                for name in (
                    "fencing_token",
                    "agent_definition_version",
                    "capability_version",
                ):
                    binding[name] = int(binding[name])
                if binding["capability_pack_deployment_id"]:
                    binding["capability_pack_activation_version"] = int(
                        binding["capability_pack_activation_version"]
                    )
                else:
                    binding["chapter_node_binding_version"] = int(
                        binding["chapter_node_binding_version"]
                    )
                binding["operation_definition_ref"] = (
                    f"{binding.pop('operation_definition_name')}@"
                    f"{binding.pop('operation_definition_version')}"
                )
                chapter_binding_id = binding.pop("chapter_node_binding_id")
                chapter_binding_version = binding.pop(
                    "chapter_node_binding_version"
                )
                binding["chapter_node_binding_ref"] = (
                    f"pack-binding-set:{binding['capability_pack_binding_set_id']}:"
                    f"{binding['workflow_node_id']}@"
                    f"{binding['capability_pack_activation_version']}"
                    if binding["capability_pack_deployment_id"]
                    else f"{chapter_binding_id}@{chapter_binding_version}"
                )
                binding["created_at"] = _timestamp(binding["created_at"])
                runtime_bindings.append(binding)
            attempt_ids = [item["attempt_id"] for item in attempts]
            cursor.execute(
                """
                SELECT lease_id, attempt_id, owner, fencing_token, status,
                       acquired_at, expires_at, heartbeat_at,
                       released_at, release_reason
                FROM authority_lease_acquisition
                WHERE attempt_id=ANY(%s)
                ORDER BY attempt_id, fencing_token
                """,
                [attempt_ids],
            )
            leases = [
                {
                    "lease_id": row[0],
                    "attempt_id": row[1],
                    "worker_id": row[2],
                    "fencing_token": int(row[3]),
                    "status": row[4],
                    "acquired_at": _timestamp(row[5]),
                    "expires_at": _timestamp(row[6]),
                    "heartbeat_at": _timestamp(row[7]),
                    "released_at": _timestamp(row[8]),
                    "release_reason": row[9],
                }
                for row in cursor.fetchall()
            ]
            cursor.execute(
                """
                SELECT external_effect_id, effect_type, capability, provider,
                       model_id, provider_request_id, status,
                       stable_idempotency_key, completion_policy,
                       request_hash, request_payload, reconciliation,
                       last_error, created_at
                FROM authority_external_effect
                WHERE operation_id=%s
                ORDER BY created_at, external_effect_id
                """,
                [operation_id],
            )
            effects = [
                {
                    "external_effect_id": row[0],
                    "effect_type": row[1],
                    "capability": row[2],
                    "provider": row[3],
                    "model_id": row[4],
                    "provider_request_id": row[5],
                    "status": row[6],
                    "stable_idempotency_key": row[7],
                    "completion_policy": row[8],
                    "request_hash": row[9],
                    "request_payload": dict(row[10] or {}),
                    "reconciliation": dict(row[11] or {}),
                    "last_error": dict(row[12] or {}),
                    "created_at": _timestamp(row[13]),
                }
                for row in cursor.fetchall()
            ]
            cursor.execute(
                """
                SELECT authorization_id, attempt_id, external_effect_id,
                       execution_id, execution_fencing_token,
                       recovery_fencing_token, recovery_worker_id,
                       action, trace_id, correlation_id, created_at
                FROM authority_execution_recovery_authorization
                WHERE operation_id=%s AND project_id=%s
                ORDER BY created_at, authorization_id
                """,
                [operation_id, project_id],
            )
            recovery_authorizations = [
                {
                    "authorization_id": row[0],
                    "attempt_id": row[1],
                    "external_effect_id": row[2],
                    "execution_id": row[3],
                    "execution_fencing_token": int(row[4]),
                    "recovery_fencing_token": int(row[5]),
                    "recovery_worker_id": row[6],
                    "action": row[7],
                    "trace_id": row[8],
                    "correlation_id": row[9],
                    "created_at": _timestamp(row[10]),
                }
                for row in cursor.fetchall()
            ]
            cursor.execute(
                """
                SELECT attempt.attempt_id, attempt.attempt_number,
                       session.session_id, session.status,
                       candidate.candidate_version_id,
                       supersession.supersession_id,
                       supersession.superseding_candidate_version_id,
                       collaboration_commit.commit_id
                FROM authority_attempt AS attempt
                LEFT JOIN authority_agent_collaboration_session AS session
                  ON session.attempt_id=attempt.attempt_id
                LEFT JOIN authority_agent_candidate_version AS candidate
                  ON candidate.session_id=session.session_id
                LEFT JOIN authority_agent_candidate_supersession AS supersession
                  ON supersession.superseded_candidate_version_id=
                     candidate.candidate_version_id
                LEFT JOIN authority_agent_collaboration_commit
                  AS collaboration_commit
                  ON collaboration_commit.candidate_version_id=
                     candidate.candidate_version_id
                WHERE attempt.operation_id=%s
                ORDER BY attempt.attempt_number,
                         candidate.created_at, candidate.candidate_version_id
                """,
                [operation_id],
            )
            candidate_attempts = [
                {
                    "attempt_id": row[0],
                    "attempt_number": int(row[1]),
                    "session_id": row[2] or "",
                    "session_status": row[3] or "",
                    "candidate_version_id": row[4] or "",
                    "supersession_id": row[5] or "",
                    "superseding_candidate_version_id": row[6] or "",
                    "commit_id": row[7] or "",
                    "is_effective_candidate": bool(row[4])
                    and not bool(row[5]),
                }
                for row in cursor.fetchall()
            ]
            cursor.execute(
                """
                SELECT output.output_key, output.role, output.asset_id,
                       output.asset_version_id, output.content_hash,
                       asset.asset_type, version.schema_version,
                       version.lifecycle, version.eligibility,
                       version.governance, version.content,
                       output.created_at
                FROM authority_operation_output_asset AS output
                JOIN authority_asset AS asset
                  ON asset.asset_id=output.asset_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=output.asset_version_id
                WHERE output.operation_id=%s
                ORDER BY output.created_at, output.output_key, output.role
                """,
                [operation_id],
            )
            outputs = [
                {
                    "output_key": row[0],
                    "role": row[1],
                    "asset_id": row[2],
                    "asset_version_id": row[3],
                    "content_hash": row[4],
                    "asset_type": row[5],
                    "schema_version": row[6],
                    "lifecycle": row[7],
                    "eligibility": row[8],
                    "governance": row[9],
                    "content": dict(row[10] or {}),
                    "created_at": _timestamp(row[11]),
                }
                for row in cursor.fetchall()
            ]
            cursor.execute(
                """
                SELECT cost_evidence_id, provider, model, amount, currency,
                       evidence, recorded_at
                FROM authority_operation_cost_evidence
                WHERE operation_id=%s
                ORDER BY recorded_at, cost_evidence_id
                """,
                [operation_id],
            )
            costs = [
                {
                    "cost_evidence_id": row[0],
                    "provider": row[1],
                    "model": row[2],
                    "amount": str(row[3]),
                    "currency": row[4],
                    "evidence": dict(row[5] or {}),
                    "recorded_at": _timestamp(row[6]),
                }
                for row in cursor.fetchall()
            ]
            cursor.execute(
                """
                SELECT cancel_command_id, actor_id, reason,
                       expected_operation_version, idempotency_key,
                       trace_id, correlation_id, created_at
                FROM authority_cancellation_command
                WHERE operation_id=%s
                ORDER BY created_at
                """,
                [operation_id],
            )
            cancellations = [
                {
                    "cancel_command_id": row[0],
                    "actor_id": row[1],
                    "reason": row[2],
                    "expected_operation_version": int(row[3]),
                    "idempotency_key": row[4],
                    "trace_id": row[5],
                    "correlation_id": row[6],
                    "created_at": _timestamp(row[7]),
                }
                for row in cursor.fetchall()
            ]
            cursor.execute(
                """
                SELECT action, payload, created_at
                FROM audit_log
                WHERE operation_id=%s AND project_id=%s
                ORDER BY created_at, audit_id
                """,
                [operation_id, project_id],
            )
            audit = [
                {
                    "action": row[0],
                    "payload": dict(row[1] or {}),
                    "created_at": _timestamp(row[2]),
                }
                for row in cursor.fetchall()
            ]
            collaboration = self._collaboration_projection(cursor, operation_id)
            domain_resolution = _domain_resolution_projection(
                collaboration,
                standalone=(
                    str(runs["operation_definition_ref"]).split("@", 1)[0]
                    == "agent.candidate.execute"
                ),
            )
        return {
            **runs,
            "attempts": attempts,
            "runtime_bindings": runtime_bindings,
            "active_runtime_binding": (
                runtime_bindings[-1] if runtime_bindings else {}
            ),
            "leases": leases,
            "external_effects": effects,
            "recovery_authorizations": recovery_authorizations,
            "candidate_attempts": candidate_attempts,
            "effective_candidate": next(
                (
                    item
                    for item in reversed(candidate_attempts)
                    if item["is_effective_candidate"]
                ),
                {},
            ),
            "provider_calls": [
                effect for effect in effects if effect["effect_type"] == "model.invoke"
            ],
            "tool_calls": [
                effect for effect in effects if effect["effect_type"] != "model.invoke"
            ],
            "outputs": outputs,
            "route_snapshots": _outputs_of_type(outputs, "route_snapshot"),
            "prompt_bundles": _outputs_of_type(outputs, "prompt_bundle"),
            "skill_bundles": _outputs_of_type(outputs, "skill_bundle"),
            "tool_permission_snapshots": _outputs_of_type(
                outputs, "tool_permission_snapshot"
            ),
            "context_bundles": _outputs_of_type(outputs, "context_bundle"),
            "execution_evidence": [
                output
                for output in outputs
                if output["asset_type"]
                in {"execution_evidence", "execution_recovery_session"}
            ],
            "final_asset_versions": [
                output
                for output in outputs
                if output["role"] in {"primary", "authority_commit"}
            ],
            "token_usage": _usage_projection(outputs),
            "cost": costs,
            "cancellation": cancellations,
            "audit": audit,
            "collaboration": collaboration,
            **domain_resolution,
            "retry_count": max(0, len(attempts) - 1),
            "recovery": {
                "checkpointed_attempts": [
                    item["attempt_id"] for item in attempts if item["checkpoint"]
                ],
                "reconciliation_required": any(
                    item["status"] in {"UNKNOWN", "RECONCILIATION_REQUIRED"}
                    for item in effects
                ),
            },
        }

    def require_collaboration(
        self, *, project_id: str, session_id: str
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            cursor = uow.cursor
            cursor.execute(
                """
                SELECT created_operation_id
                FROM authority_agent_collaboration_session
                WHERE session_id=%s AND project_id=%s
                """,
                [session_id, project_id],
            )
            row = cursor.fetchone()
            if row is None:
                raise KernelError(
                    "AGENT_COLLABORATION_NOT_FOUND",
                    "collaboration does not exist in the requested project",
                )
            return self._collaboration_projection(
                cursor, str(row[0]), session_id=session_id
            )

    def require_asset_lineage(
        self, *, project_id: str, asset_version_id: str
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT output.operation_id, operation.root_operation_id,
                       commit.commit_id, commit.candidate_version_id,
                       commit.decision_id, commit.attempt_id,
                       commit.fencing_token, commit.content_hash,
                       commit.receipt_ref
                FROM authority_operation_output_asset AS output
                JOIN authority_operation AS operation
                  ON operation.operation_id=output.operation_id
                LEFT JOIN authority_agent_collaboration_commit AS commit
                  ON commit.asset_version_id=output.asset_version_id
                WHERE output.asset_version_id=%s
                  AND operation.project_id=%s
                ORDER BY output.created_at DESC
                LIMIT 1
                """,
                [asset_version_id, project_id],
            )
            row = uow.cursor.fetchone()
            if row is not None:
                exact = bool(row[2])
                uow.cursor.execute(
                    (
                        """
                        SELECT DISTINCT binding.operation_id
                        FROM authority_agent_runtime_binding AS binding
                        WHERE binding.project_id=%s AND binding.operation_id=%s
                        ORDER BY binding.operation_id
                        """
                        if exact
                        else """
                        SELECT DISTINCT binding.operation_id
                        FROM authority_agent_runtime_binding AS binding
                        JOIN authority_operation AS operation
                          ON operation.operation_id=binding.operation_id
                        WHERE operation.project_id=%s
                          AND operation.root_operation_id=%s
                        ORDER BY binding.operation_id
                        """
                    ),
                    [project_id, str(row[0] if exact else row[1])],
                )
                agent_operation_ids = [str(item[0]) for item in uow.cursor.fetchall()]
        if row is None:
            raise KernelError(
                "AGENT_ASSET_LINEAGE_NOT_FOUND",
                "AssetVersion has no Agent Runtime operation lineage",
            )
        if not agent_operation_ids:
            raise KernelError(
                "AGENT_ASSET_LINEAGE_NOT_FOUND",
                "AssetVersion root workflow contains no Agent Runtime binding",
            )
        same_operation_binding = str(row[0]) in agent_operation_ids
        return {
            "final_asset_version_id": asset_version_id,
            "producing_operation_id": str(row[0]),
            "root_operation_id": str(row[1]),
            "lineage_strength": (
                "EXACT_COLLABORATION_COMMIT"
                if row[2]
                else (
                    "SAME_OPERATION_BINDING"
                    if same_operation_binding
                    else "SAME_ROOT_WORKFLOW_ONLY"
                )
            ),
            "exact_collaboration_commit": (
                {
                    "commit_id": str(row[2]),
                    "candidate_version_id": str(row[3]),
                    "decision_id": str(row[4]),
                    "attempt_id": str(row[5] or ""),
                    "fencing_token": int(row[6] or 0),
                    "content_hash": str(row[7] or ""),
                    "receipt_ref": str(row[8] or ""),
                }
                if row[2]
                else {}
            ),
            "agent_runs": [
                self.require_run(
                    project_id=project_id,
                    agent_run_id=operation_id,
                )
                for operation_id in agent_operation_ids
            ],
        }

    def _run_header(
        self, *, project_id: str, agent_run_id: str
    ) -> dict[str, Any] | None:
        rows = self.list_runs(project_id=project_id, agent_run_id=agent_run_id, limit=1)
        return next((row for row in rows if row["agent_run_id"] == agent_run_id), None)

    @staticmethod
    def _run_summary(row: tuple[Any, ...]) -> dict[str, Any]:
        operation_status = str(row[9])
        standalone = str(row[7]) == "agent.candidate.execute"
        attempt_status = str(row[13] or "")
        external_effect_status = str(row[18] or "")
        return {
            "agent_run_id": row[0],
            "operation_id": row[0],
            "project_id": row[1],
            "workspace_id": row[2],
            "book_id": row[3],
            "agent_id": row[4],
            "agent_definition_version": int(row[5] or 0),
            "capability_id": row[6],
            "operation_definition_ref": f"{row[7]}@{row[8]}",
            "execution_embedding": (
                AgentExecutionEmbedding.STANDALONE_CANDIDATE_OPERATION.value
                if standalone
                else AgentExecutionEmbedding.EMBEDDED_DOMAIN_ATTEMPT.value
            ),
            "scheduling_authority": (
                AgentSchedulingAuthority.AGENT_RUNTIME_AUTHORITY.value
                if standalone
                else AgentSchedulingAuthority.CHAPTER_AUTHORITY.value
            ),
            "status": derive_agent_run_status(
                operation_status=operation_status,
                attempt_status=attempt_status,
                lease_status=str(row[17] or ""),
                external_effect_status=external_effect_status,
            ).value,
            "operation_status": operation_status,
            "operation_version": int(row[10]),
            "attempt_id": row[11] or "",
            "attempt_number": int(row[12] or 0),
            "attempt_status": attempt_status,
            "worker_id": row[14] or "",
            "lease_id": row[15] or "",
            "fencing_token": int(row[16] or 0),
            "execution_fencing_token": int(row[30] or 0),
            "recovery_fencing_token": int(row[16] or 0),
            "lease_status": row[17] or "",
            "external_effect_status": row[18] or "",
            "runtime_binding_id": row[19] or "",
            "capability_pack_ref": row[20] or "",
            "capability_pack_compilation_hash": row[21] or "",
            "context_bundle_asset_version_id": row[22] or "",
            "route_snapshot_ref": row[23] or "",
            "input_manifest_ref": row[24] or "",
            "trace_id": row[25],
            "span_id": row[26],
            "correlation_id": row[27],
            "created_at": _timestamp(row[28]),
            "updated_at": _timestamp(row[29]),
        }

    @staticmethod
    def _collaboration_projection(
        cursor: Any, operation_id: str, *, session_id: str = ""
    ) -> dict[str, Any]:
        cursor.execute(
            """
            SELECT session.session_id, session.owner_authority,
                   session.business_goal, session.issue_type, session.status,
                   session.scope_snapshot_id,
                   session.participant_snapshot_id,
                   session.current_candidate_version_id,
                   session.authority_decision_id,
                   work_order.work_order_id, work_order.turn_id,
                   work_order.context_bundle_ref,
                   work_order.route_snapshot_ref,
                   work_order.input_manifest_ref,
                   output.output_id, output.structured_payload,
                   output.execution_evidence_ref,
                   candidate.candidate_version_id,
                   candidate.validation_status,
                   candidate.content_ref,
                   decision.decision_id, decision.decision_type,
                   commit.commit_id, commit.asset_version_id,
                   commit.receipt_ref, commit.attempt_id,
                   commit.fencing_token, commit.content_hash,
                   session.attempt_id, supersession.supersession_id,
                   supersession.superseding_candidate_version_id
            FROM authority_agent_work_order AS work_order
            JOIN authority_agent_collaboration_session AS session
              ON session.session_id=work_order.session_id
            LEFT JOIN authority_agent_output_envelope AS output
              ON output.turn_id=work_order.turn_id
            LEFT JOIN authority_agent_candidate_version AS candidate
              ON candidate.originating_turn_id=work_order.turn_id
            LEFT JOIN authority_agent_collaboration_decision AS decision
              ON decision.session_id=session.session_id
             AND decision.decision_id=session.authority_decision_id
            LEFT JOIN authority_agent_collaboration_commit AS commit
              ON commit.session_id=session.session_id
            LEFT JOIN authority_agent_candidate_supersession AS supersession
              ON supersession.superseded_candidate_version_id=
                 candidate.candidate_version_id
            WHERE (
                (%s <> '' AND session.session_id=%s)
                OR (%s = '' AND work_order.operation_id=%s)
            )
            ORDER BY work_order.created_at DESC, work_order.work_order_id DESC
            LIMIT 1
            """,
            [session_id, session_id, session_id, operation_id],
        )
        row = cursor.fetchone()
        if row is None:
            return {}
        return {
            "session_id": row[0],
            "owner_authority": row[1],
            "business_goal": row[2],
            "issue_type": row[3],
            "session_status": row[4],
            "attempt_id": row[28] or "",
            "scope_snapshot_ref": row[5] or "",
            "participant_snapshot_ref": row[6] or "",
            "current_candidate_version_id": row[7] or "",
            "authority_decision_id": row[8] or "",
            "work_order_id": row[9],
            "turn_id": row[10],
            "context_bundle_ref": row[11],
            "route_snapshot_ref": row[12],
            "input_manifest_ref": row[13],
            "output": {
                "output_id": row[14] or "",
                "structured_payload": dict(row[15] or {}),
                "execution_evidence_ref": row[16] or "",
            },
            "candidate": {
                "candidate_version_id": row[17] or "",
                "validation_status": row[18] or "",
                "content_ref": row[19] or "",
                "supersession_id": row[29] or "",
                "superseding_candidate_version_id": row[30] or "",
                "is_effective": bool(row[17]) and not bool(row[29]),
            },
            "decision": {
                "decision_id": row[20] or "",
                "decision_type": row[21] or "",
            },
            "commit": {
                "commit_id": row[22] or "",
                "asset_version_id": row[23] or "",
                "receipt_ref": row[24] or "",
                "attempt_id": row[25] or "",
                "fencing_token": int(row[26] or 0),
                "content_hash": row[27] or "",
            },
        }


def _outputs_of_type(
    outputs: list[dict[str, Any]], asset_type: str
) -> list[dict[str, Any]]:
    return [item for item in outputs if item["asset_type"] == asset_type]


def _domain_resolution_projection(
    collaboration: dict[str, Any], *, standalone: bool
) -> dict[str, str]:
    candidate = str(
        collaboration.get("candidate", {}).get("candidate_version_id") or ""
    )
    decision = str(collaboration.get("decision", {}).get("decision_type") or "")
    commit = str(collaboration.get("commit", {}).get("commit_id") or "")
    asset = str(collaboration.get("commit", {}).get("asset_version_id") or "")
    candidate_status = "CANDIDATE_READY" if candidate else "CANDIDATE_NOT_CREATED"
    if commit:
        domain_status = AgentDomainCommitStatus.DOMAIN_COMMITTED.value
    elif decision in {"REPAIR_REQUIRED", "REPLAN_REQUIRED"}:
        domain_status = AgentDomainCommitStatus.REPAIR_REQUIRED.value
    elif decision == "REJECTED":
        domain_status = AgentDomainCommitStatus.REJECTED.value
    elif candidate and not standalone:
        domain_status = AgentDomainCommitStatus.DOMAIN_DECISION_PENDING.value
    else:
        domain_status = AgentDomainCommitStatus.NOT_REQUESTED.value
    return {
        "candidate_status": candidate_status,
        "domain_resolution_status": domain_status,
        "authority_decision_status": decision or "NOT_REQUESTED",
        "domain_commit_status": domain_status,
        "final_asset_version_id": asset,
    }


def _usage_projection(outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    usage: list[dict[str, Any]] = []
    for output in outputs:
        content = output.get("content") or {}
        if not isinstance(content, dict):
            continue
        kind = str(content.get("kind") or "")
        payload = content.get("payload")
        if "usage" in kind and isinstance(payload, dict):
            usage.append(
                {
                    "asset_version_id": output["asset_version_id"],
                    "content_hash": output["content_hash"],
                    **dict(payload),
                }
            )
    return usage


def _timestamp(value: Any) -> str:
    return "" if value is None else str(value)


__all__ = ["AgentRuntimeQuery"]
