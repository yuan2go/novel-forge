"""Production adapters for the governed Agent Harness.

These adapters deliberately reuse AuthorityUnitOfWork and the owning Operation.
They introduce no scheduler, lease, effect, or story-truth authority.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.budget_runtime import (
    BudgetReservationRequest,
    reserve_provider_budget,
)
from novel_forge.modules.command_kernel.external_effect_adapters import ProviderResult
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    dispatch_external_effect,
    plan_external_effect,
    resolve_external_effect_receipt_budget,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .harness import (
    AgentHarnessSession,
    AgentHarnessStatus,
    AgentHarnessUsage,
    AgentModelTurn,
    AgentToolCall,
    AgentToolKind,
    AgentToolObservation,
    AgentToolSpec,
    AgentTranscriptEventType,
    UnifiedAgentHarness,
)


class PostgresAgentHarnessTranscript:
    """Short-transaction append port for session provenance."""

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("Agent Harness transcript requires PostgreSQL")
        self.database_url = database_url

    def create(self, session: AgentHarnessSession) -> AgentHarnessSession:
        with AuthorityUnitOfWork(self.database_url) as uow:
            result = uow.repositories.agent_runtime.create_harness_session(session)
            uow.commit()
            return result

    def append_event(
        self,
        *,
        session: AgentHarnessSession,
        request_id: str,
        turn_number: int,
        event_type: AgentTranscriptEventType,
        payload: Mapping[str, Any],
        trace_id: str,
        attempt_id: str = "",
        external_effect_id: str = "",
        target_status: AgentHarnessStatus | None = None,
        usage: AgentHarnessUsage | None = None,
    ) -> AgentHarnessSession:
        with AuthorityUnitOfWork(self.database_url) as uow:
            result = uow.repositories.agent_runtime.append_event(
                session=session,
                request_id=request_id,
                turn_number=turn_number,
                event_type=event_type,
                payload=payload,
                trace_id=trace_id,
                attempt_id=attempt_id,
                external_effect_id=external_effect_id,
                target_status=target_status,
                usage=usage,
            )
            uow.commit()
            return result

    def committed_request_events(
        self, *, agent_session_id: str
    ) -> tuple[Mapping[str, Any], ...]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            return uow.repositories.agent_runtime.committed_request_events(
                agent_session_id=agent_session_id
            )


class PostgresOperationCancellation:
    """Read the existing Command Kernel cancellation fact; own no state."""

    def __init__(self, database_url: str, *, project_id: str) -> None:
        self.database_url = database_url
        self.project_id = project_id

    def cancellation_requested(self, *, operation_id: str) -> bool:
        with AuthorityUnitOfWork(self.database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(
                operation_id, self.project_id
            )
        return str(state["status"]) in {"CANCELLATION_REQUESTED", "CANCELLED"}


class PostgresAgentSessionUsageMeter:
    """Aggregate existing receipt/ledger evidence over Agent causation lineage."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def measure(
        self, *, session: AgentHarnessSession, usage: AgentHarnessUsage
    ) -> AgentHarnessUsage:
        with AuthorityUnitOfWork(self.database_url) as uow:
            params = [session.operation_id, session.project_id, session.project_id]
            uow.cursor.execute(
                """
                WITH RECURSIVE descendants AS (
                  SELECT operation_id FROM authority_operation
                  WHERE operation_id=%s AND project_id=%s
                  UNION
                  SELECT child.operation_id
                  FROM authority_operation AS child
                  JOIN descendants AS parent
                    ON child.parent_operation_id=parent.operation_id
                    OR child.causation_operation_id=parent.operation_id
                  WHERE child.project_id=%s
                ), latest_receipts AS (
                  SELECT DISTINCT ON (effect.external_effect_id)
                         effect.external_effect_id, receipt.payload
                  FROM authority_external_effect AS effect
                  LEFT JOIN authority_external_effect_dispatch AS dispatch
                    ON dispatch.external_effect_id=effect.external_effect_id
                  LEFT JOIN authority_external_receipt AS receipt
                    ON receipt.dispatch_id=dispatch.dispatch_id
                   AND receipt.status='VERIFIED'
                   AND receipt.payload->>'outcome'='success'
                  WHERE effect.operation_id IN (
                    SELECT operation_id FROM descendants
                  )
                  ORDER BY effect.external_effect_id, receipt.received_at DESC
                )
                SELECT external_effect_id, payload FROM latest_receipts
                """,
                params,
            )
            receipts = uow.cursor.fetchall()
            uow.cursor.execute(
                """
                WITH RECURSIVE descendants AS (
                  SELECT operation_id FROM authority_operation
                  WHERE operation_id=%s AND project_id=%s
                  UNION
                  SELECT child.operation_id
                  FROM authority_operation AS child
                  JOIN descendants AS parent
                    ON child.parent_operation_id=parent.operation_id
                    OR child.causation_operation_id=parent.operation_id
                  WHERE child.project_id=%s
                )
                SELECT COALESCE(SUM(
                  CASE WHEN status='SETTLED' THEN settled_amount
                       ELSE reserved_amount END
                ), 0)
                FROM authority_budget_reservation
                WHERE operation_id IN (SELECT operation_id FROM descendants)
                  AND status IN ('RESERVED','HELD_UNKNOWN','SETTLED')
                """,
                params,
            )
            amount = str(uow.cursor.fetchone()[0])
        input_tokens = 0
        output_tokens = 0
        for _effect_id, raw_payload in receipts:
            payload = dict(raw_payload or {})
            evidence = payload.get("evidence")
            if not isinstance(evidence, Mapping):
                continue
            usage_evidence = evidence.get("usage")
            if not isinstance(usage_evidence, Mapping):
                production = evidence.get("production_execution")
                usage_evidence = (
                    production.get("usage") if isinstance(production, Mapping) else None
                )
            if isinstance(usage_evidence, Mapping):
                input_tokens += int(usage_evidence.get("input_tokens") or 0)
                output_tokens += int(usage_evidence.get("output_tokens") or 0)
        return AgentHarnessUsage(
            turns=usage.turns,
            tool_calls=usage.tool_calls,
            external_effects=len(receipts),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_amount=amount,
        )


AgentToolHandler = Callable[
    [AgentToolSpec, AgentToolCall, AgentHarnessSession, str, int],
    AgentToolObservation,
]


class BoundAgentToolRouter:
    """Invoke typed bindings after the Harness has applied its frozen allowlist."""

    def __init__(self, handlers: Mapping[str, AgentToolHandler]) -> None:
        if not handlers:
            raise ValueError("Agent Harness requires at least one bound Tool")
        self.handlers = dict(handlers)

    def invoke(
        self,
        *,
        spec: AgentToolSpec,
        call: AgentToolCall,
        session: AgentHarnessSession,
        request_id: str,
        turn_number: int,
    ) -> AgentToolObservation:
        handler = self.handlers.get(spec.tool_name)
        if handler is None:
            raise KernelError(
                "AGENT_HARNESS_TOOL_UNBOUND",
                f"allowlisted Tool has no production binding: {spec.tool_name}",
            )
        result = handler(spec, call, session, request_id, turn_number)
        if result.tool_name != spec.tool_name:
            raise KernelError(
                "AGENT_HARNESS_TOOL_RESULT_DRIFT", "Tool result identity changed"
            )
        if spec.kind is AgentToolKind.AUTHORITY_COMMAND:
            if not result.authority_command_id:
                raise KernelError(
                    "AGENT_HARNESS_AUTHORITY_COMMAND_NOT_SUBMITTED",
                    "Authority Command Tool returned no submitted command identity",
                )
            forbidden = {
                "canon_mutated",
                "narrative_state_mutated",
                "arc_actual_advanced",
                "obligation_resolved",
                "plan_activated",
                "chapter_accepted",
            }
            if any(bool(result.result.get(key)) for key in forbidden):
                raise KernelError(
                    "AGENT_HARNESS_AUTHORITY_BYPASS",
                    "Tool claimed a business mutation instead of command submission",
                )
        elif spec.kind is AgentToolKind.TYPED_CAPABILITY:
            if result.result.get("candidate_only") is not True:
                raise KernelError(
                    "AGENT_HARNESS_CAPABILITY_NOT_CANDIDATE",
                    "Typed Capability Tool must return an immutable Candidate",
                )
        return result


class ScriptedAgentHarnessEffectAdapter:
    """Deterministic development adapter; never qualifies as a real Provider."""

    provider = "scripted_agent_harness_fixture"
    reconciliation_mode = "query"
    production_execution_gateway_backed = True
    capability_profile = {
        "provider": provider,
        "control_level": "FIXTURE_CONTROLLED",
        "supports_request_timeout": True,
        "supports_provider_idempotency": True,
        "supports_query": True,
        "supports_cancel": True,
        "supports_callback": False,
        "supports_usage_receipt": False,
        "supports_cost_receipt": False,
        "reconciliation_mode": "query",
        "real_provider_validation_eligible": False,
        "contract_version": "provider-capability-v2",
    }

    def execute(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        if capability != "model.agent_session":
            return ProviderResult(
                "final_failure",
                f"scripted-agent:{stable_idempotency_key}",
                {"error": "unsupported_capability"},
            )
        observations = list(request_payload.get("observations") or ())
        tool_names = [str(item) for item in request_payload.get("tool_names") or ()]
        if not observations and "narrative.query_accepted" in tool_names:
            turn = {
                "message": "Inspect the frozen accepted narrative boundary.",
                "tool_call": {
                    "tool_name": "narrative.query_accepted",
                    "arguments": {"scope": "accepted_boundary"},
                    "reason": "ground the proposal in accepted facts",
                },
            }
        else:
            turn = {
                "message": "Return an authority-bounded proposal.",
                "final_response": {
                    "proposal": {
                        "candidate_only": True,
                        "instruction": str(request_payload.get("instruction") or ""),
                        "accepted_boundary": dict(
                            request_payload.get("accepted_boundary") or {}
                        ),
                    },
                    "fixture_protocol_only": True,
                },
            }
        return ProviderResult(
            "success",
            f"scripted-agent:{stable_idempotency_key}",
            {
                "model_turn": turn,
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "cost": {"amount": "0", "currency": "USD"},
                "fixture_protocol_only": True,
                "real_model_call": False,
                "production_verified": False,
            },
        )

    def query(self, **values: Any) -> ProviderResult:
        return self.execute(**values)

    def cancel(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
        provider_request_id: str,
    ) -> ProviderResult:
        del capability, request_payload
        return ProviderResult(
            "cancelled",
            provider_request_id or f"scripted-agent:{stable_idempotency_key}",
            {"cancelled": True, "fixture_protocol_only": True},
        )


class PostgresScriptedAgentModelTurnPort:
    """ExternalEffect-backed protocol fixture for the durable Harness smoke path."""

    external_effect_backed = True

    def __init__(
        self,
        database_url: str,
        *,
        project_id: str,
        attempt_id: str,
        actor_id: str,
        trace_id: str,
        worker_id: str,
        lease_seconds: int = 30,
    ) -> None:
        self.database_url = database_url
        self.project_id = project_id
        self.attempt_id = attempt_id
        self.actor_id = actor_id
        self.trace_id = trace_id
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.adapter = ScriptedAgentHarnessEffectAdapter()

    def next_turn(
        self,
        *,
        session: AgentHarnessSession,
        request_id: str,
        turn_number: int,
        instruction: str,
        committed_transcript: Any,
        observations: Any,
    ) -> AgentModelTurn:
        del committed_transcript
        context = EffectCommandContext(
            operation_id=session.operation_id,
            project_id=self.project_id,
            actor_id=self.actor_id,
            trace_id=self.trace_id,
            correlation_id=f"agent-session:{session.agent_session_id}",
            causation_id=request_id,
        )
        payload = {
            "agent_session_id": session.agent_session_id,
            "agent_role": session.role.value,
            "instruction": instruction,
            "turn_number": turn_number,
            "accepted_boundary": asdict(session.accepted_boundary),
            "tool_names": [item.tool_name for item in session.tool_policy],
            "observations": [asdict(item) for item in observations],
            "skill_bindings": [dict(item) for item in session.skill_bindings],
        }
        planned = plan_external_effect(
            self.database_url,
            context,
            effect_type="agent_model_turn",
            provider=self.adapter.provider,
            capability="model.agent_session",
            stable_idempotency_key=(
                f"agent-session:{session.agent_session_id}:request:{request_id}:"
                f"turn:{turn_number}"
            ),
            request_payload=payload,
            max_attempts=1,
            reversible=False,
            completion_policy="synchronous_final",
            model_id="scripted-agent-harness-fixture",
            request_timeout_seconds=30,
            reconciliation_mode=self.adapter.reconciliation_mode,
            provider_capability_profile=dict(self.adapter.capability_profile),
        )
        effect_id = str(planned["external_effect_id"])
        reserve_provider_budget(
            self.database_url,
            BudgetReservationRequest(
                operation_id=session.operation_id,
                external_effect_id=effect_id,
                project_id=self.project_id,
                stable_idempotency_key=(
                    f"agent-session-budget:{session.agent_session_id}:"
                    f"{request_id}:{turn_number}"
                ),
                provider=self.adapter.provider,
                currency="USD",
                estimated_amount="0",
                estimated_tokens=0,
            ),
        )
        dispatched = dispatch_external_effect(
            self.database_url,
            context,
            effect_id=effect_id,
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
            adapter=self.adapter,
        )
        if dispatched["outcome"] != "success":
            raise KernelError(
                "AGENT_HARNESS_MODEL_EFFECT_FAILED",
                "scripted Agent model ExternalEffect did not succeed",
            )
        evidence = dict(dispatched["provider_evidence"] or {})
        resolve_external_effect_receipt_budget(
            self.database_url,
            effect_id=effect_id,
            project_id=self.project_id,
            outcome="success",
            evidence={
                **evidence,
                "actual_cost": str((evidence.get("cost") or {}).get("amount") or "0"),
                "actual_tokens": int(
                    (evidence.get("usage") or {}).get("input_tokens") or 0
                )
                + int((evidence.get("usage") or {}).get("output_tokens") or 0),
                "model_id": "scripted-agent-harness-fixture",
            },
        )
        raw_turn = dict(evidence.get("model_turn") or {})
        tool_call = raw_turn.get("tool_call")
        final_response = raw_turn.get("final_response")
        return AgentModelTurn(
            message=str(raw_turn.get("message") or "Agent turn completed."),
            operation_id=session.operation_id,
            attempt_id=self.attempt_id,
            external_effect_id=effect_id,
            input_tokens=int((evidence.get("usage") or {}).get("input_tokens") or 0),
            output_tokens=int((evidence.get("usage") or {}).get("output_tokens") or 0),
            cost_amount=str((evidence.get("cost") or {}).get("amount") or "0"),
            tool_call=(
                AgentToolCall(
                    tool_name=str(tool_call["tool_name"]),
                    arguments=dict(tool_call.get("arguments") or {}),
                    reason=str(tool_call.get("reason") or "governed Tool selection"),
                )
                if isinstance(tool_call, Mapping)
                else None
            ),
            final_response=(
                dict(final_response) if isinstance(final_response, Mapping) else None
            ),
        )


def build_scripted_agent_harness_factory(
    database_url: str,
    *,
    worker_id: str,
    lease_seconds: int = 30,
) -> Callable[[str, str, str], UnifiedAgentHarness]:
    """Build the explicitly fixture-only durable Agent Harness composition."""

    def factory(project_id: str, attempt_id: str, trace_id: str) -> UnifiedAgentHarness:
        def query_accepted(
            spec: AgentToolSpec,
            call: AgentToolCall,
            session: AgentHarnessSession,
            request_id: str,
            turn_number: int,
        ) -> AgentToolObservation:
            del spec, call, request_id, turn_number
            with AuthorityUnitOfWork(database_url) as uow:
                uow.cursor.execute(
                    """
                    SELECT active_longform_projection_set_id
                    FROM authority_book_production
                    WHERE book_run_id=%s AND project_id=%s AND book_id=%s
                    """,
                    [
                        session.accepted_boundary.book_run_id,
                        session.project_id,
                        session.accepted_boundary.book_id,
                    ],
                )
                row = uow.cursor.fetchone()
            if row is None or str(row[0] or "") != str(
                session.accepted_boundary.projection_set_id
            ):
                raise KernelError(
                    "AGENT_HARNESS_ACCEPTED_BOUNDARY_STALE",
                    "read Tool observed a different accepted projection set",
                )
            return AgentToolObservation(
                tool_name="narrative.query_accepted",
                result={
                    "accepted_boundary": asdict(session.accepted_boundary),
                    "authoritative": True,
                },
                operation_id=session.operation_id,
                attempt_id=attempt_id,
            )

        return UnifiedAgentHarness(
            transcript=PostgresAgentHarnessTranscript(database_url),
            model=PostgresScriptedAgentModelTurnPort(
                database_url,
                project_id=project_id,
                attempt_id=attempt_id,
                actor_id=worker_id,
                trace_id=trace_id,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
            ),
            tools=BoundAgentToolRouter({"narrative.query_accepted": query_accepted}),
            cancellation=PostgresOperationCancellation(
                database_url, project_id=project_id
            ),
            usage_meter=PostgresAgentSessionUsageMeter(database_url),
        )

    return factory


__all__ = [
    "AgentToolHandler",
    "BoundAgentToolRouter",
    "PostgresAgentHarnessTranscript",
    "PostgresAgentSessionUsageMeter",
    "PostgresOperationCancellation",
    "PostgresScriptedAgentModelTurnPort",
    "ScriptedAgentHarnessEffectAdapter",
    "build_scripted_agent_harness_factory",
]
