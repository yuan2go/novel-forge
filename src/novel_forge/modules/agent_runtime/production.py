from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
import hashlib
import json
from typing import Any, Callable, Mapping

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.chapter_authority.contracts import (
    ChapterHandlerRequest,
    ChapterInputAsset,
)
from novel_forge.modules.chapter_authority.execution_gateway import (
    PostgresChapterExecutionContractBinder,
    ProductionExecutionGatewayExternalEffectAdapter,
)
from novel_forge.modules.chapter_authority.model_effects import (
    ExternalEffectChapterModelPort,
)
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.plan_change_authority import (
    PlanChangeProposalCommand,
    PlanChangeSource,
    PostgresPlanChangeAuthority,
)
from novel_forge.modules.story_planning_runtime import (
    StoryPlanningGenerationApplication,
    StoryPlanningGenerationCommand,
)
from novel_forge.storage.authority_asset_store import (
    AuthorityAssetQuery,
    AuthorityAssetWriter,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.database_runtime import get_database_runtime

from .harness import (
    AgentHarnessSession,
    AgentModelTurn,
    AgentToolCall,
    AgentToolObservation,
    AgentToolSpec,
    SKILL_ACTIVATION_TOOL,
    UnifiedAgentHarness,
)
from .definitions import AGENT_SESSION_WORKFLOW_DEFINITION_REF
from .harness_runtime import (
    BoundAgentToolRouter,
    PostgresAgentHarnessTranscript,
    PostgresAgentSessionUsageMeter,
    PostgresOperationCancellation,
)


AGENT_SESSION_STAGE = "agent_session"


def _agent_turn_reservation_limits(
    *, session: AgentHarnessSession, provider_call_cap: str
) -> tuple[str, int]:
    """INVARIANT: Reserve only the unspent Session budget for the next model effect.

    The authoritative aggregate gate still lives in the shared budget runtime.
    This sizing prevents each Agent turn from presenting the whole Session cap
    as a new reservation after earlier turns have already settled.
    """
    provider_maximum = Decimal(provider_call_cap)
    remaining_cost = Decimal(session.budget.max_cost_amount) - Decimal(
        session.usage.cost_amount
    )
    remaining_input_tokens = (
        session.budget.max_input_tokens - session.usage.input_tokens
    )
    if remaining_cost < 0 or remaining_input_tokens <= 0:
        raise KernelError(
            "AGENT_HARNESS_BUDGET_EXHAUSTED",
            "Agent Session has no reservable model-turn budget remaining",
        )
    if remaining_cost == 0 and provider_maximum > 0:
        raise KernelError(
            "AGENT_HARNESS_BUDGET_EXHAUSTED",
            "Agent Session has no reservable model-turn cost remaining",
        )
    return str(min(provider_maximum, remaining_cost)), remaining_input_tokens


def agent_route_execution_identity(
    route: Any, *, capability_pack_id: str
) -> dict[str, Any]:

    identity = {
        "contract_version": "agent-route-execution-identity.v1",
        "stage": AGENT_SESSION_STAGE,
        "provider": route.model_profile.model_provider,
        "model_id": route.model_profile.model_id,
        "reasoning_effort": route.model_profile.reasoning_effort,
        "model_profile_id": route.model_profile.profile_id,
        "model_profile_version": route.model_profile.profile_version,
        "model_profile_hash": route.model_profile.contract_hash,
        "route_policy_id": route.route_policy.policy_id,
        "route_policy_version": route.route_policy.policy_version,
        "route_policy_ref": (
            f"{route.route_policy.policy_id}:v{route.route_policy.policy_version}"
        ),
        "route_policy_hash": route.route_policy.contract_hash,
        "fallback_policy_id": route.fallback_policy.policy_id,
        "fallback_policy_version": route.fallback_policy.policy_version,
        "fallback_policy_hash": route.fallback_policy.contract_hash,
        "backend_id": route.model_profile.backend_id,
        "backend_version": route.backend_version,
        "runtime_class": route.model_profile.runtime_class.value,
        "runtime_host_id": route.runtime_host_id,
        "auth_profile_ref": route.auth_profile_ref,
        "prompt_version": route.prompt_version,
        "skill_version": route.skill_version,
        "system_instruction_hash": route.system_instruction_hash,
        "template_hash": route.template_hash,
        "skill_content_hash": route.skill_content_hash,
        "prompt_compiler_version": route.prompt_compiler_version,
        "output_schema_ref": route.output_schema_ref,
        "release_sha": route.release_sha,
        "capability_pack_id": capability_pack_id,
        "gateway": "PRODUCTION_EXECUTION_GATEWAY",
    }
    return {**identity, "runtime_binding_hash": canonical_policy_hash(identity)}


class PostgresAgentExecutionContractBinder(PostgresChapterExecutionContractBinder):

    def __init__(
        self, database_url: str, routes: Mapping[str, Any], **values: Any
    ) -> None:
        super().__init__(
            database_url,
            routes,
            workflow_definition_ref=AGENT_SESSION_WORKFLOW_DEFINITION_REF,
            **values,
        )

    def _target_scope(
        self,
        *,
        metadata: Mapping[str, Any],
        project_id: str,
        book_id: str,
        chapter: int,
    ) -> dict[str, Any]:
        del chapter
        session_id = str(metadata.get("agent_session_id") or "")
        if not session_id:
            raise KernelError(
                "AGENT_EXECUTION_SCOPE_MISSING",
                "Agent execution requires a frozen session identity",
            )
        return {
            "scope_kind": "agent_session",
            "scope_id": session_id,
            "project_id": project_id,
            "book_id": book_id,
        }

    def _resource_claims(
        self,
        *,
        metadata: Mapping[str, Any],
        chapter: int,
        stage: str,
    ) -> tuple[str, ...]:
        del chapter
        return (f"agent-session:{metadata['agent_session_id']}", f"stage:{stage}")

    @staticmethod
    def _origin_chain(*, graph: Mapping[str, str], stage: str) -> tuple[str, ...]:
        del stage
        return ("agent.session.execute", graph["definition_name"])

    def freeze_before_external_effect(
        self,
        *,
        capability: str,
        request_payload: Mapping[str, Any],
        snapshot_fencing_token: int,
        snapshot_worker_id: str,
    ) -> Any:
        preflight = super().freeze_before_external_effect(
            capability=capability,
            request_payload=request_payload,
            snapshot_fencing_token=snapshot_fencing_token,
            snapshot_worker_id=snapshot_worker_id,
        )
        metadata = request_payload.get("_production_execution")
        contract = (
            dict(metadata.get("agent_execution_contract") or {})
            if isinstance(metadata, Mapping)
            else {}
        )
        if not contract:
            return preflight
        expected_pack_hash = str(contract.get("capability_pack_snapshot_hash") or "")
        if expected_pack_hash and (
            preflight is None
            or preflight.attempt_snapshot.execution_snapshot.snapshot_hash
            != expected_pack_hash
        ):
            raise KernelError(
                "AGENT_EXECUTION_CAPABILITY_PACK_DRIFT",
                "Attempt Capability Pack differs from admission-frozen identity",
            )
        expected_binding = dict(contract.get("runtime_binding") or {})
        current_binding = agent_route_execution_identity(
            self.routes[AGENT_SESSION_STAGE],
            capability_pack_id=self.capability_pack_id,
        )
        if expected_binding != current_binding:
            raise KernelError(
                "AGENT_EXECUTION_RUNTIME_BINDING_DRIFT",
                "current provider route differs from admission-frozen identity",
            )
        return preflight


class PostgresProductionAgentModelTurnPort:

    external_effect_backed = True
    production_execution_gateway_backed = True

    def __init__(
        self,
        database_url: str,
        *,
        project_id: str,
        attempt_id: str,
        worker_id: str,
        trace_id: str,
        model_port: ExternalEffectChapterModelPort,
    ) -> None:
        self.database_url = database_url
        self.project_id = project_id
        self.attempt_id = attempt_id
        self.worker_id = worker_id
        self.trace_id = trace_id
        self.model_port = model_port
        self.assets = AuthorityAssetQuery(database_url)
        self.writer = AuthorityAssetWriter(database_url)

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
        self._require_frozen_execution_contract(session)
        self._require_active_boundary(session)
        reservation_amount, reservation_tokens = _agent_turn_reservation_limits(
            session=session,
            provider_call_cap=self.model_port.max_cost_per_call,
        )
        context = self._context_asset(session, instruction)
        effect_instance = f"{request_id}:turn:{turn_number}"
        request = ChapterHandlerRequest(
            operation_id=session.operation_id,
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            trace_id=self.trace_id,
            correlation_id=f"agent-session:{session.agent_session_id}",
            command={
                "book_id": session.accepted_boundary.book_id,
                "agent_session_id": session.agent_session_id,
                "agent_execution_contract": dict(session.execution_contract),
                "agent_execution_contract_hash": session.execution_contract_hash,
                "chapter_number": session.accepted_boundary.accepted_through_chapter,
                "_effect_instance": effect_instance,
                "context_token_budget": session.budget.max_input_tokens,
            },
            inputs=(
                ChapterInputAsset(
                    asset_version_id=context.asset_version_id,
                    asset_type=context.asset_type,
                    content_hash=context.content_hash,
                    content=dict(context.content),
                    blobs=(),
                ),
            ),
            attempt_id=self.attempt_id,
            fencing_token=self._current_fence(session.operation_id),
            worker_id=self.worker_id,
        )
        result = self.model_port.invoke(
            request,
            stage=AGENT_SESSION_STAGE,
            reservation_amount=reservation_amount,
            reservation_tokens=reservation_tokens,
            payload={
                "agent_session_id": session.agent_session_id,
                "operation_id": session.operation_id,
                "instruction": instruction,
                "accepted_boundary": asdict(session.accepted_boundary),
                "execution_contract_hash": session.execution_contract_hash,
                "execution_contract_summary": {
                    "contract_version": session.execution_contract.get(
                        "contract_version"
                    ),
                    "release_sha": session.execution_contract.get("release_sha"),
                    "authority_policy": session.execution_contract.get(
                        "authority_policy"
                    ),
                    "runtime_binding": dict(
                        session.execution_contract.get("runtime_binding") or {}
                    ),
                    "policy_hash": dict(
                        session.execution_contract.get("agent_policy") or {}
                    ).get("policy_hash"),
                    "budget": asdict(session.budget),
                },
                "tools": [self._tool_payload(item) for item in session.tool_policy],
                "skills": [dict(item) for item in session.skill_bindings],
                "active_skill_activations": [
                    dict(item.result)
                    for item in observations
                    if item.tool_name == SKILL_ACTIVATION_TOOL.tool_name
                ],
                "committed_transcript": [dict(item) for item in committed_transcript],
                "observations": [asdict(item) for item in observations],
                "turn_number": turn_number,
            },
        )
        effect_id = self._effect_id(session.operation_id, effect_instance)
        raw = dict(result.output)
        tool_call = raw.get("tool_call")
        final_response = raw.get("final_response")
        return AgentModelTurn(
            message=str(raw["message"]),
            operation_id=session.operation_id,
            attempt_id=self.attempt_id,
            external_effect_id=effect_id,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_amount=result.cost_amount,
            tool_call=(
                AgentToolCall(
                    tool_name=str(tool_call["tool_name"]),
                    arguments=dict(tool_call["arguments"]),
                    reason=str(tool_call["reason"]),
                )
                if isinstance(tool_call, Mapping)
                else None
            ),
            final_response=(
                dict(final_response) if isinstance(final_response, Mapping) else None
            ),
        )

    def _require_frozen_execution_contract(self, session: AgentHarnessSession) -> None:
        contract = dict(session.execution_contract)
        if not contract:
            # Historical fixture sessions are intentionally not provider proof.
            return
        if canonical_policy_hash(contract) != session.execution_contract_hash:
            raise KernelError(
                "AGENT_EXECUTION_CONTRACT_CORRUPT",
                "Agent Session execution contract hash differs from content",
            )
        binder = self.model_port.capability_binder
        pack_id = str(getattr(binder, "capability_pack_id", ""))
        route = self.model_port.adapter.routes.get(AGENT_SESSION_STAGE)
        if route is None:
            raise KernelError(
                "AGENT_EXECUTION_RUNTIME_UNBOUND",
                "Agent Session has no current production route to validate",
            )
        current = agent_route_execution_identity(route, capability_pack_id=pack_id)
        if dict(contract.get("runtime_binding") or {}) != current:
            raise KernelError(
                "AGENT_EXECUTION_RUNTIME_BINDING_DRIFT",
                "current provider/model/route differs from admission-frozen identity",
            )
        runtime = get_database_runtime(self.database_url)
        with runtime.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT command_payload->'execution_contract',
                           command_payload->>'execution_contract_hash'
                    FROM authority_operation
                    WHERE operation_id=%s AND project_id=%s
                    """,
                    [session.operation_id, session.project_id],
                )
                row = cursor.fetchone()
        if (
            row is None
            or dict(row[0] or {}) != contract
            or str(row[1] or "") != (session.execution_contract_hash)
        ):
            raise KernelError(
                "AGENT_EXECUTION_CONTRACT_DRIFT",
                "Session and Operation do not share the same frozen execution contract",
            )

    def _context_asset(self, session: AgentHarnessSession, instruction: str) -> Any:
        logical_ref = f"agent_harness/context/{session.agent_session_id}"
        try:
            return self.assets.require(
                project_id=session.project_id, logical_ref=logical_ref
            )
        except KernelError as exc:
            if exc.code != "AUTHORITY_ASSET_NOT_FOUND":
                raise
        return self.writer.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=session.operation_id,
                project_id=session.project_id,
                asset_id=f"agent-harness-context:{session.agent_session_id}",
                asset_type="context_bundle",
                schema_version="agent-harness-context.v1",
                logical_ref=logical_ref,
                category="agent_runtime",
                output_key="agent_harness.context",
                role="frozen_context",
                content={
                    "contract_version": "agent-harness-context.v1",
                    "accepted_boundary": asdict(session.accepted_boundary),
                    "instruction": instruction,
                    "tool_policy": [
                        self._tool_payload(item) for item in session.tool_policy
                    ],
                    "skill_bindings": [dict(item) for item in session.skill_bindings],
                    "protected": True,
                    "source_authority": "POSTGRESQL_ACCEPTED_BOUNDARY",
                },
                qualification_policy="agent-harness-context-v1",
                trace_id=self.trace_id,
                correlation_id=f"agent-session:{session.agent_session_id}",
                causation_id=self.attempt_id,
            )
        )

    def _current_fence(self, operation_id: str) -> int:
        runtime = get_database_runtime(self.database_url)
        with runtime.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT lease.fencing_token
                    FROM authority_attempt AS attempt
                    JOIN authority_lease_acquisition AS lease
                      ON lease.attempt_id=attempt.attempt_id
                    WHERE attempt.attempt_id=%s AND attempt.operation_id=%s
                      AND lease.owner=%s AND lease.status='HELD'
                      AND lease.expires_at > NOW()
                    ORDER BY lease.fencing_token DESC LIMIT 1
                    """,
                    [self.attempt_id, operation_id, self.worker_id],
                )
                row = cursor.fetchone()
        if row is None:
            raise KernelError(
                "AGENT_HARNESS_MODEL_FENCE_MISSING",
                "Agent model turn requires the current held Attempt lease",
            )
        return int(row[0])

    def _require_active_boundary(self, session: AgentHarnessSession) -> None:
        boundary = session.accepted_boundary
        runtime = get_database_runtime(self.database_url)
        with runtime.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT accepted_through_chapter,
                           COALESCE(active_longform_projection_set_id, '')
                    FROM authority_book_production
                    WHERE book_run_id=%s AND project_id=%s AND book_id=%s
                    """,
                    [boundary.book_run_id, session.project_id, boundary.book_id],
                )
                row = cursor.fetchone()
        if row is None or (int(row[0]), str(row[1])) != (
            boundary.accepted_through_chapter,
            boundary.projection_set_id,
        ):
            raise KernelError(
                "AGENT_HARNESS_ACCEPTED_BOUNDARY_STALE",
                "Agent turn cannot run after its accepted boundary has advanced",
            )

    def _effect_id(self, operation_id: str, effect_instance: str) -> str:
        stable_key = ":".join(
            (
                operation_id,
                self.attempt_id,
                AGENT_SESSION_STAGE,
                effect_instance,
                "attempt-v1",
            )
        )
        runtime = get_database_runtime(self.database_url)
        with runtime.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT external_effect_id FROM authority_external_effect
                    WHERE project_id=%s AND operation_id=%s
                      AND stable_idempotency_key=%s
                    """,
                    [self.project_id, operation_id, stable_key],
                )
                row = cursor.fetchone()
        if row is None:
            raise KernelError(
                "AGENT_HARNESS_MODEL_EFFECT_MISSING",
                "completed Agent turn has no durable ExternalEffect",
            )
        return str(row[0])

    @staticmethod
    def _tool_payload(spec: AgentToolSpec) -> dict[str, Any]:
        return {
            "tool_name": spec.tool_name,
            "kind": spec.kind.value,
            "input_schema_ref": spec.input_schema_ref,
            "output_schema_ref": spec.output_schema_ref,
            "authority_command_type": spec.authority_command_type,
        }


class ProductionAgentToolBindings:

    def __init__(
        self,
        database_url: str,
        *,
        planning: StoryPlanningGenerationApplication,
        plan_change: PostgresPlanChangeAuthority,
        principal: Principal,
        worker_id: str,
        trace_id: str,
        attempt_id: str,
    ) -> None:
        self.database_url = database_url
        self.planning = planning
        self.plan_change = plan_change
        self.principal = principal
        self.worker_id = worker_id
        self.trace_id = trace_id
        self.attempt_id = attempt_id

    def handlers(self) -> dict[str, Any]:
        return {
            "narrative.query_accepted": self.query_accepted,
            "story_planning.generate_candidate": self.generate_candidate,
            "plan_change.submit": self.submit_plan_change,
        }

    def query_accepted(
        self,
        spec: AgentToolSpec,
        call: AgentToolCall,
        session: AgentHarnessSession,
        request_id: str,
        turn_number: int,
    ) -> AgentToolObservation:
        del spec, call, request_id, turn_number
        boundary = session.accepted_boundary
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT production.active_longform_projection_set_id,
                       projection.projection_hash,
                       projection.chapter_outcome_asset_version_id,
                       projection.story_state_asset_version_id,
                       projection.canon_snapshot_asset_version_id,
                       COALESCE((
                         SELECT jsonb_agg(jsonb_build_object(
                           'arc_plan_version_id', progress.arc_plan_version_id,
                           'observation_status', progress.observation_status,
                           'progress_units', progress.progress_units,
                           'cumulative_progress_units',
                             progress.cumulative_progress_units
                         ) ORDER BY progress.arc_plan_version_id)
                         FROM authority_arc_progress_v2 AS progress
                         WHERE progress.projection_set_id=projection.projection_set_id
                       ), '[]'::jsonb),
                       COALESCE((
                         SELECT jsonb_agg(jsonb_build_object(
                           'obligation_id', obligation.obligation_id,
                           'status', obligation.status,
                           'urgency', obligation.state->>'urgency'
                         ) ORDER BY obligation.obligation_id)
                         FROM authority_narrative_obligation_state AS obligation
                         WHERE obligation.projection_set_id=projection.projection_set_id
                       ), '[]'::jsonb)
                FROM authority_book_production AS production
                LEFT JOIN authority_book_narrative_projection_set AS projection
                  ON projection.projection_set_id=
                     production.active_longform_projection_set_id
                WHERE production.book_run_id=%s AND production.project_id=%s
                  AND production.book_id=%s
                """,
                [boundary.book_run_id, session.project_id, boundary.book_id],
            )
            row = uow.cursor.fetchone()
        if row is None or str(row[0] or "") != boundary.projection_set_id:
            if boundary.accepted_through_chapter == 0 and row and not row[0]:
                evidence: dict[str, Any] = {
                    "accepted_boundary": asdict(boundary),
                    "projection": None,
                    "arcs": [],
                    "obligations": [],
                }
            else:
                raise KernelError(
                    "AGENT_HARNESS_ACCEPTED_BOUNDARY_STALE",
                    "read Tool observed a different accepted projection set",
                )
        else:
            evidence = {
                "accepted_boundary": asdict(boundary),
                "projection": {
                    "projection_hash": str(row[1]),
                    "chapter_outcome_version_id": str(row[2]),
                    "story_state_version_id": str(row[3]),
                    "canon_snapshot_version_id": str(row[4]),
                },
                "arcs": list(row[5] or ()),
                "obligations": list(row[6] or ()),
            }
        return AgentToolObservation(
            tool_name="narrative.query_accepted",
            result={**evidence, "authoritative": True, "accepted_only": True},
            operation_id=session.operation_id,
            attempt_id=self.attempt_id,
        )

    def generate_candidate(
        self,
        spec: AgentToolSpec,
        call: AgentToolCall,
        session: AgentHarnessSession,
        request_id: str,
        turn_number: int,
    ) -> AgentToolObservation:
        del spec, turn_number
        arguments = dict(call.arguments)
        command = StoryPlanningGenerationCommand(
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            book_id=session.accepted_boundary.book_id,
            actor_id=self.principal.principal_id,
            generator_operation_name=str(arguments["generator_operation_name"]),
            logical_key=str(arguments["logical_key"]),
            input_versions=dict(arguments["input_versions"]),
            idempotency_key=f"agent-capability:{session.agent_session_id}:{request_id}",
            trace_id=self.trace_id,
            correlation_id=f"agent-session:{session.agent_session_id}",
            parent_version_id=str(arguments.get("parent_version_id") or ""),
            arc_scope_volume_plan_version_ids=tuple(
                arguments.get("arc_scope_volume_plan_version_ids") or ()
            ),
            related_arc_plan_version_ids=tuple(
                arguments.get("related_arc_plan_version_ids") or ()
            ),
            dependent_arc_plan_version_ids=tuple(
                arguments.get("dependent_arc_plan_version_ids") or ()
            ),
            change_evidence_version_ids=tuple(
                arguments.get("change_evidence_version_ids") or ()
            ),
            governance_action_version_ids=tuple(
                arguments.get("governance_action_version_ids") or ()
            ),
            auto_approve_low_risk=False,
            parent_agent_session_operation_id=session.operation_id,
        )
        result = self.planning.generate(command, principal=self.principal)
        candidate_effect_id = self._required_candidate_effect(
            result.generation_operation_id, session.project_id
        )
        return AgentToolObservation(
            tool_name="story_planning.generate_candidate",
            result={
                "candidate_only": True,
                "candidate_asset_version_id": result.candidate_asset_version_id,
                "candidate_operation_id": result.generation_operation_id,
                "candidate_status": result.status.value,
                "candidate_external_effect_id": candidate_effect_id,
                "activated": False,
            },
            operation_id=session.operation_id,
            attempt_id=self.attempt_id,
            external_effect_id=candidate_effect_id,
        )

    def submit_plan_change(
        self,
        spec: AgentToolSpec,
        call: AgentToolCall,
        session: AgentHarnessSession,
        request_id: str,
        turn_number: int,
    ) -> AgentToolObservation:
        del spec, turn_number
        arguments = dict(call.arguments)
        proposal = self.plan_change.propose(
            PlanChangeProposalCommand(
                project_id=session.project_id,
                workspace_id=session.workspace_id,
                book_id=session.accepted_boundary.book_id,
                actor_id=self.principal.principal_id,
                trace_id=self.trace_id,
                correlation_id=f"agent-session:{session.agent_session_id}",
                stable_idempotency_key=(
                    f"agent-plan-change:{session.agent_session_id}:{request_id}"
                ),
                source_type=PlanChangeSource(str(arguments["source_type"])),
                source_evidence_version_id=str(arguments["source_evidence_version_id"]),
                target_asset_version_id=str(arguments["target_asset_version_id"]),
                proposed_asset_version_id=str(arguments["proposed_asset_version_id"]),
            ),
            principal=self.principal,
        )
        command_id = str(proposal["proposal_operation_id"])
        return AgentToolObservation(
            tool_name="plan_change.submit",
            result={
                "submitted": True,
                "proposal_id": str(proposal["proposal_id"]),
                "operation_id": command_id,
                "authority_decision_required": True,
                "plan_activated": False,
            },
            operation_id=session.operation_id,
            attempt_id=self.attempt_id,
            authority_command_id=command_id,
        )

    def _required_candidate_effect(self, operation_id: str, project_id: str) -> str:
        runtime = get_database_runtime(self.database_url)
        with runtime.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT effect.external_effect_id
                    FROM authority_external_effect AS effect
                    JOIN authority_external_effect_dispatch AS dispatch
                      ON dispatch.external_effect_id=effect.external_effect_id
                    JOIN authority_external_receipt AS receipt
                      ON receipt.dispatch_id=dispatch.dispatch_id
                    WHERE effect.operation_id=%s AND effect.project_id=%s
                      AND effect.status='SUCCEEDED'
                      AND receipt.status='VERIFIED'
                      AND receipt.payload->>'outcome'='success'
                    ORDER BY receipt.received_at DESC LIMIT 1
                    """,
                    [operation_id, project_id],
                )
                row = cursor.fetchone()
        if row is None:
            raise KernelError(
                "AGENT_TYPED_CAPABILITY_EFFECT_MISSING",
                "Typed Capability candidate has no governed ExternalEffect receipt",
            )
        return str(row[0])


def build_production_agent_harness_factory(
    database_url: str,
    *,
    adapter: ProductionExecutionGatewayExternalEffectAdapter,
    capability_binder: PostgresAgentExecutionContractBinder,
    planning: StoryPlanningGenerationApplication,
    plan_change: PostgresPlanChangeAuthority,
    principal: Principal,
    worker_id: str,
    lease_seconds: int = 30,
    max_cost_per_call: str = "0",
    budget_caps: Mapping[str, str] | None = None,
    model_fault_injector: Callable[[str], None] | None = None,
) -> Callable[[str, str, str], UnifiedAgentHarness]:

    if "agent_session" not in adapter.routes:
        raise ValueError("production Agent route is not configured")
    existing_binder = adapter.execution_binders.get("agent_harness")
    if existing_binder is None:
        adapter.register_execution_binder("agent_harness", capability_binder)
    elif existing_binder is not capability_binder:
        raise ValueError("production Agent binder is already owned by another runtime")

    def factory(project_id: str, attempt_id: str, trace_id: str) -> UnifiedAgentHarness:
        model = ExternalEffectChapterModelPort(
            database_url,
            adapter=adapter,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            max_cost_per_call=max_cost_per_call,
            budget_caps=dict(budget_caps or {}),
            capability_binder=capability_binder,
            execution_binding_domain="agent_harness",
            fault_injector=model_fault_injector,
        )
        tools = ProductionAgentToolBindings(
            database_url,
            planning=planning,
            plan_change=plan_change,
            principal=principal,
            worker_id=worker_id,
            trace_id=trace_id,
            attempt_id=attempt_id,
        )
        return UnifiedAgentHarness(
            transcript=PostgresAgentHarnessTranscript(database_url),
            model=PostgresProductionAgentModelTurnPort(
                database_url,
                project_id=project_id,
                attempt_id=attempt_id,
                worker_id=worker_id,
                trace_id=trace_id,
                model_port=model,
            ),
            tools=BoundAgentToolRouter(tools.handlers()),
            cancellation=PostgresOperationCancellation(
                database_url, project_id=project_id
            ),
            usage_meter=PostgresAgentSessionUsageMeter(database_url),
        )

    return factory


def canonical_policy_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "AGENT_SESSION_STAGE",
    "PostgresProductionAgentModelTurnPort",
    "PostgresAgentExecutionContractBinder",
    "ProductionAgentToolBindings",
    "build_production_agent_harness_factory",
    "agent_route_execution_identity",
    "canonical_policy_hash",
]
