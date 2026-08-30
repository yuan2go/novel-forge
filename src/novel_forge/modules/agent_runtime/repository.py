from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from typing import Any, Mapping
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError

from .contracts import (
    AgentCapabilityExecutionMapping,
    AgentDefinitionActivation,
    AgentDefinitionActivationStatus,
    AgentDefinitionRuntimeContract,
    AgentRuntimeBinding,
    ChapterNodeExecutionBinding,
)
from .harness import (
    AcceptedBoundaryRef,
    AgentHarnessBudget,
    AgentHarnessSession,
    AgentHarnessStatus,
    AgentHarnessUsage,
    AgentToolSpec,
    AgentTranscriptEventType,
    AutonomousAgentRole,
    transcript_payload_hash,
)


class PostgresAgentRuntimeRepository:

    production_authority = True

    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def create_harness_session(
        self, session: AgentHarnessSession
    ) -> AgentHarnessSession:

        self.cursor.execute(
            """
            SELECT operation.project_id, operation.workspace_id, operation.status,
                   COALESCE(book_run.book_run_id, ''),
                   COALESCE(book_run.active_longform_projection_set_id, '')
            FROM authority_operation AS operation
            LEFT JOIN authority_book_production AS book_run
              ON book_run.book_run_id=%s AND book_run.book_id=%s
             AND book_run.project_id=operation.project_id
            WHERE operation.operation_id=%s
              AND operation.project_id=%s AND operation.workspace_id=%s
            FOR UPDATE OF operation
            """,
            [
                session.accepted_boundary.book_run_id,
                session.accepted_boundary.book_id,
                session.operation_id,
                session.project_id,
                session.workspace_id,
            ],
        )
        owner = self.cursor.fetchone()
        if (
            owner is None
            or not str(owner[3] or "")
            or str(owner[2])
            not in {
                "ADMITTED",
                "READY",
                "EXECUTING",
                "WAITING_EXTERNAL_RESULT",
            }
        ):
            raise KernelError(
                "AGENT_HARNESS_OPERATION_INVALID",
                "Agent session requires an active scoped Authority Operation",
            )
        active_projection = str(owner[4] or "")
        if (
            session.accepted_boundary.accepted_through_chapter > 0
            and active_projection != session.accepted_boundary.projection_set_id
        ):
            raise KernelError(
                "AGENT_HARNESS_ACCEPTED_BOUNDARY_STALE",
                "Agent session is not frozen at the Book's active complete projection set",
            )
        self.cursor.execute(
            """
            INSERT INTO authority_agent_harness_session(
                agent_session_id, project_id, workspace_id, operation_id,
                agent_role, status, accepted_boundary, tool_policy,
                skill_bindings, budget, execution_contract,
                execution_contract_hash, usage, next_sequence, version
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(agent_session_id) DO NOTHING
            """,
            [
                session.agent_session_id,
                session.project_id,
                session.workspace_id,
                session.operation_id,
                session.role.value,
                session.status.value,
                Jsonb(asdict(session.accepted_boundary)),
                Jsonb([_tool_payload(tool) for tool in session.tool_policy]),
                Jsonb([dict(item) for item in session.skill_bindings]),
                Jsonb(asdict(session.budget)),
                Jsonb(dict(session.execution_contract)),
                session.execution_contract_hash,
                Jsonb(asdict(session.usage)),
                session.next_sequence,
                session.version,
            ],
        )
        stored = self.require_harness_session(session.agent_session_id, lock=True)
        if stored != session:
            raise KernelError(
                "AGENT_HARNESS_SESSION_CONFLICT",
                "Agent session identity already has different frozen content",
            )
        return stored

    def require_harness_session(
        self, agent_session_id: str, *, lock: bool = False
    ) -> AgentHarnessSession:
        suffix = " FOR UPDATE" if lock else ""
        self.cursor.execute(
            """
            SELECT agent_session_id, project_id, workspace_id, operation_id,
                   agent_role, status, accepted_boundary, tool_policy,
                   skill_bindings, budget, execution_contract,
                   execution_contract_hash, usage, next_sequence, version
            FROM authority_agent_harness_session
            WHERE agent_session_id=%s
            """
            + suffix,
            [agent_session_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "AGENT_HARNESS_SESSION_NOT_FOUND", "Agent session does not exist"
            )
        boundary = dict(row[6] or {})
        budget = dict(row[9] or {})
        usage = dict(row[12] or {})
        return AgentHarnessSession(
            agent_session_id=str(row[0]),
            project_id=str(row[1]),
            workspace_id=str(row[2]),
            operation_id=str(row[3]),
            role=AutonomousAgentRole(str(row[4])),
            status=AgentHarnessStatus(str(row[5])),
            accepted_boundary=AcceptedBoundaryRef(**boundary),
            tool_policy=tuple(_tool_from_payload(dict(item)) for item in row[7] or ()),
            skill_bindings=tuple(dict(item) for item in row[8] or ()),
            budget=AgentHarnessBudget(**budget),
            execution_contract=dict(row[10] or {}),
            execution_contract_hash=str(row[11] or ""),
            usage=AgentHarnessUsage(**usage),
            next_sequence=int(row[13]),
            version=int(row[14]),
        )

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

        event_type = AgentTranscriptEventType(event_type)
        if not request_id.strip() or turn_number < 0 or not trace_id.strip():
            raise ValueError("Agent transcript event identity is incomplete")
        current = self.require_harness_session(session.agent_session_id, lock=True)
        if (
            current.version != session.version
            or current.next_sequence != session.next_sequence
        ):
            raise KernelError(
                "AGENT_HARNESS_SESSION_CAS_CONFLICT",
                "Agent session transcript advanced concurrently",
            )
        if current.operation_id != session.operation_id:
            raise KernelError(
                "AGENT_HARNESS_OPERATION_DRIFT", "Agent session Operation changed"
            )
        if attempt_id:
            self.cursor.execute(
                """
                SELECT 1 FROM authority_attempt
                WHERE attempt_id=%s AND operation_id=%s
                """,
                [attempt_id, current.operation_id],
            )
            if self.cursor.fetchone() is None:
                raise KernelError(
                    "AGENT_HARNESS_ATTEMPT_DRIFT",
                    "transcript Attempt is not owned by the session Operation",
                )
        if external_effect_id:
            self.cursor.execute(
                """
                WITH RECURSIVE descendants AS (
                  SELECT operation_id
                  FROM authority_operation
                  WHERE operation_id=%s AND project_id=%s
                  UNION
                  SELECT child.operation_id
                  FROM authority_operation AS child
                  JOIN descendants AS parent
                    ON child.parent_operation_id=parent.operation_id
                    OR child.causation_operation_id=parent.operation_id
                  WHERE child.project_id=%s
                )
                SELECT 1 FROM authority_external_effect
                WHERE external_effect_id=%s
                  AND operation_id IN (SELECT operation_id FROM descendants)
                """,
                [
                    current.operation_id,
                    current.project_id,
                    current.project_id,
                    external_effect_id,
                ],
            )
            if self.cursor.fetchone() is None:
                raise KernelError(
                    "AGENT_HARNESS_EXTERNAL_EFFECT_DRIFT",
                    "transcript ExternalEffect is not owned by the session Operation",
                )
        normalized = dict(payload)
        event_id = str(uuid4())
        self.cursor.execute(
            """
            INSERT INTO authority_agent_transcript_event(
                transcript_event_id, agent_session_id, sequence, request_id,
                turn_number, event_type, operation_id, attempt_id,
                external_effect_id, payload, payload_hash, trace_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                event_id,
                current.agent_session_id,
                current.next_sequence,
                request_id,
                turn_number,
                event_type.value,
                current.operation_id,
                attempt_id or None,
                external_effect_id or None,
                Jsonb(normalized),
                transcript_payload_hash(normalized),
                trace_id,
            ],
        )
        next_status = AgentHarnessStatus(target_status or current.status)
        next_usage = usage or current.usage
        self.cursor.execute(
            """
            UPDATE authority_agent_harness_session
            SET status=%s, usage=%s, next_sequence=next_sequence + 1,
                version=version + 1, updated_at=NOW()
            WHERE agent_session_id=%s AND version=%s AND next_sequence=%s
            """,
            [
                next_status.value,
                Jsonb(asdict(next_usage)),
                current.agent_session_id,
                current.version,
                current.next_sequence,
            ],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "AGENT_HARNESS_SESSION_CAS_CONFLICT",
                "Agent session transcript advanced concurrently",
            )
        return self.require_harness_session(current.agent_session_id)

    def committed_request_events(
        self, *, agent_session_id: str
    ) -> tuple[Mapping[str, Any], ...]:

        self.cursor.execute(
            """
            SELECT sequence, request_id, turn_number, event_type, payload,
                   operation_id, attempt_id, external_effect_id, trace_id,
                   payload_hash
            FROM authority_agent_transcript_event
            WHERE agent_session_id=%s
            ORDER BY sequence
            """,
            [agent_session_id],
        )
        rows = self.cursor.fetchall()
        committed = {
            str(row[1])
            for row in rows
            if str(row[3]) == AgentTranscriptEventType.REQUEST_COMMITTED.value
        }
        failed = {
            str(row[1])
            for row in rows
            if str(row[3]) == AgentTranscriptEventType.REQUEST_FAILED.value
        }
        return tuple(
            {
                "sequence": int(row[0]),
                "request_id": str(row[1]),
                "turn_number": int(row[2]),
                "event_type": str(row[3]),
                "payload": dict(row[4] or {}),
                "operation_id": str(row[5]),
                "attempt_id": str(row[6] or ""),
                "external_effect_id": str(row[7] or ""),
                "trace_id": str(row[8]),
                "payload_hash": str(row[9]),
            }
            for row in rows
            if str(row[1]) in committed and str(row[1]) not in failed
        )

    def register_capability_execution_mapping(
        self, mapping: AgentCapabilityExecutionMapping
    ) -> AgentCapabilityExecutionMapping:
        self.cursor.execute(
            """
            INSERT INTO authority_agent_capability_execution_mapping (
                capability_id, capability_version,
                execution_capability_id, execution_capability_hash,
                mapping_hash, created_by_operation_id
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (capability_id, capability_version) DO NOTHING
            """,
            [
                mapping.capability_id,
                mapping.capability_version,
                mapping.execution_capability_id,
                mapping.execution_capability_hash,
                mapping.mapping_hash,
                mapping.created_by_operation_id,
            ],
        )
        self.cursor.execute(
            """
            SELECT execution_capability_id, execution_capability_hash
            FROM authority_agent_capability_execution_mapping
            WHERE capability_id=%s AND capability_version=%s
            """,
            [mapping.capability_id, mapping.capability_version],
        )
        row = self.cursor.fetchone()
        if row is None or (str(row[0]), str(row[1])) != (
            mapping.execution_capability_id,
            mapping.execution_capability_hash,
        ):
            raise KernelError(
                "AGENT_CAPABILITY_MAPPING_CONFLICT",
                "Capability version already maps to different PEP content",
            )
        return mapping

    def register_definition_runtime_contract(
        self, contract: AgentDefinitionRuntimeContract
    ) -> AgentDefinitionRuntimeContract:
        self.cursor.execute(
            """
            INSERT INTO authority_agent_definition_runtime_contract (
                agent_id, definition_version, capability_pack_ref,
                prompt_bundle_ref, prompt_bundle_hash,
                skill_bundle_ref, skill_bundle_hash,
                tool_policy_ref, tool_policy_hash,
                context_policy_ref, context_policy_hash,
                runtime_contract_hash, definition_source,
                created_by_operation_id
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (agent_id, definition_version) DO NOTHING
            """,
            [
                contract.agent_id,
                contract.definition_version,
                contract.capability_pack_ref,
                contract.prompt_bundle_ref,
                contract.prompt_bundle_hash,
                contract.skill_bundle_ref,
                contract.skill_bundle_hash,
                contract.tool_policy_ref,
                contract.tool_policy_hash,
                contract.context_policy_ref,
                contract.context_policy_hash,
                contract.runtime_contract_hash,
                contract.definition_source,
                contract.created_by_operation_id,
            ],
        )
        self.cursor.execute(
            """
            SELECT runtime_contract_hash
            FROM authority_agent_definition_runtime_contract
            WHERE agent_id=%s AND definition_version=%s
            """,
            [contract.agent_id, contract.definition_version],
        )
        row = self.cursor.fetchone()
        if row is None or str(row[0]) != contract.runtime_contract_hash:
            raise KernelError(
                "AGENT_DEFINITION_RUNTIME_CONTRACT_CONFLICT",
                "Agent Definition version already has different runtime content",
            )
        return contract

    def activate_definition(
        self,
        *,
        agent_id: str,
        definition_version: int,
        status: AgentDefinitionActivationStatus,
        expected_activation_version: int,
        reason: str,
        activated_by: str,
        activated_by_operation_id: str,
    ) -> AgentDefinitionActivation:
        status = AgentDefinitionActivationStatus(status)
        if status is AgentDefinitionActivationStatus.ACTIVE:
            self.cursor.execute(
                """
                SELECT status
                FROM authority_agent_definition
                WHERE agent_id=%s AND definition_version=%s
                """,
                [agent_id, definition_version],
            )
            definition = self.cursor.fetchone()
            if definition is None or str(definition[0]) != "ACTIVE":
                raise KernelError(
                    "AGENT_DEFINITION_NOT_PRODUCTION_ACTIVE",
                    "only an ACTIVE immutable Agent Definition may be activated",
                )
        if expected_activation_version < 0:
            raise KernelError(
                "AGENT_DEFINITION_ACTIVATION_VERSION_INVALID",
                "expected activation version cannot be negative",
            )
        if expected_activation_version == 0:
            self.cursor.execute(
                """
                INSERT INTO authority_agent_definition_activation (
                    agent_id, definition_version, activation_status,
                    activation_version, reason, activated_by,
                    activated_by_operation_id
                ) VALUES (%s, %s, %s, 1, %s, %s, %s)
                ON CONFLICT (agent_id) DO NOTHING
                """,
                [
                    agent_id,
                    definition_version,
                    status.value,
                    reason,
                    activated_by,
                    activated_by_operation_id,
                ],
            )
        else:
            self.cursor.execute(
                """
                UPDATE authority_agent_definition_activation
                SET definition_version=%s, activation_status=%s,
                    activation_version=activation_version + 1,
                    reason=%s, activated_by=%s,
                    activated_by_operation_id=%s,
                    updated_at=NOW()
                WHERE agent_id=%s AND activation_version=%s
                  AND activation_status <> 'RETIRED'
                """,
                [
                    definition_version,
                    status.value,
                    reason,
                    activated_by,
                    activated_by_operation_id,
                    agent_id,
                    expected_activation_version,
                ],
            )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "AGENT_DEFINITION_ACTIVATION_CONFLICT",
                "Agent Definition activation changed concurrently or is retired",
            )
        return self.get_definition_activation(agent_id)

    def get_definition_activation(self, agent_id: str) -> AgentDefinitionActivation:
        self.cursor.execute(
            """
            SELECT agent_id, definition_version, activation_status,
                   activation_version, reason, activated_by,
                   activated_by_operation_id
            FROM authority_agent_definition_activation
            WHERE agent_id=%s
            """,
            [agent_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "AGENT_DEFINITION_NOT_ACTIVATED",
                f"Agent Definition has no production activation: {agent_id}",
            )
        return AgentDefinitionActivation(*row)

    def resolve_active_definition(self, agent_id: str) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT definition.agent_id, definition.definition_version,
                   definition.agent_type, definition.domain, definition.role,
                   definition.input_contract_ref,
                   definition.output_contract_ref,
                   definition.authority_scope_ref,
                   definition.default_scope_policy_ref,
                   definition.allowed_tools,
                   definition.allowed_context_types,
                   definition.execution_policy_ref,
                   definition.approval_policy_ref,
                   definition.quality_policy_ref,
                   definition.definition_hash,
                   contract.capability_pack_ref,
                   contract.prompt_bundle_ref, contract.prompt_bundle_hash,
                   contract.skill_bundle_ref, contract.skill_bundle_hash,
                   contract.tool_policy_ref, contract.tool_policy_hash,
                   contract.context_policy_ref, contract.context_policy_hash,
                   contract.runtime_contract_hash,
                   contract.definition_source,
                   activation.activation_status,
                   activation.activation_version
            FROM authority_agent_definition_activation AS activation
            JOIN authority_agent_definition AS definition
              ON definition.agent_id=activation.agent_id
             AND definition.definition_version=activation.definition_version
            JOIN authority_agent_definition_runtime_contract AS contract
              ON contract.agent_id=definition.agent_id
             AND contract.definition_version=definition.definition_version
            WHERE activation.agent_id=%s
            """,
            [agent_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "AGENT_DEFINITION_NOT_ACTIVATED",
                f"Agent Definition has no production activation: {agent_id}",
            )
        fields = (
            "agent_id",
            "definition_version",
            "agent_type",
            "domain",
            "role",
            "input_contract_ref",
            "output_contract_ref",
            "authority_scope_ref",
            "default_scope_policy_ref",
            "allowed_tools",
            "allowed_context_types",
            "execution_policy_ref",
            "approval_policy_ref",
            "quality_policy_ref",
            "definition_hash",
            "capability_pack_ref",
            "prompt_bundle_ref",
            "prompt_bundle_hash",
            "skill_bundle_ref",
            "skill_bundle_hash",
            "tool_policy_ref",
            "tool_policy_hash",
            "context_policy_ref",
            "context_policy_hash",
            "runtime_contract_hash",
            "definition_source",
            "activation_status",
            "activation_version",
        )
        result = dict(zip(fields, row, strict=True))
        if result["activation_status"] != AgentDefinitionActivationStatus.ACTIVE:
            raise KernelError(
                "AGENT_DEFINITION_DISABLED",
                f"Agent Definition is not active: {agent_id}",
            )
        result["capabilities"] = self._definition_capabilities(
            agent_id, int(result["definition_version"])
        )
        return result

    def lock_active_definition(self, agent_id: str) -> dict[str, Any]:

        self.cursor.execute(
            """
            SELECT agent_id FROM authority_agent_definition_activation
            WHERE agent_id=%s FOR SHARE
            """,
            [agent_id],
        )
        if self.cursor.fetchone() is None:
            raise KernelError(
                "AGENT_DEFINITION_NOT_ACTIVATED",
                f"Agent Definition has no production activation: {agent_id}",
            )
        return self.resolve_active_definition(agent_id)

    def lock_definition_version(
        self, agent_id: str, definition_version: int
    ) -> dict[str, Any]:

        self.cursor.execute(
            """
            SELECT definition.agent_id, definition.definition_version,
                   definition.agent_type, definition.domain, definition.role,
                   definition.input_contract_ref,
                   definition.output_contract_ref,
                   definition.authority_scope_ref,
                   definition.default_scope_policy_ref,
                   definition.allowed_tools,
                   definition.allowed_context_types,
                   definition.execution_policy_ref,
                   definition.approval_policy_ref,
                   definition.quality_policy_ref,
                   definition.definition_hash,
                   contract.capability_pack_ref,
                   contract.prompt_bundle_ref, contract.prompt_bundle_hash,
                   contract.skill_bundle_ref, contract.skill_bundle_hash,
                   contract.tool_policy_ref, contract.tool_policy_hash,
                   contract.context_policy_ref, contract.context_policy_hash,
                   contract.runtime_contract_hash,
                   contract.definition_source,
                   definition.status
            FROM authority_agent_definition AS definition
            JOIN authority_agent_definition_runtime_contract AS contract
              ON contract.agent_id=definition.agent_id
             AND contract.definition_version=definition.definition_version
            WHERE definition.agent_id=%s
              AND definition.definition_version=%s
            FOR SHARE OF definition, contract
            """,
            [agent_id, definition_version],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "AGENT_DEFINITION_NOT_FOUND",
                f"exact Agent Definition does not exist: {agent_id}@{definition_version}",
            )
        fields = (
            "agent_id",
            "definition_version",
            "agent_type",
            "domain",
            "role",
            "input_contract_ref",
            "output_contract_ref",
            "authority_scope_ref",
            "default_scope_policy_ref",
            "allowed_tools",
            "allowed_context_types",
            "execution_policy_ref",
            "approval_policy_ref",
            "quality_policy_ref",
            "definition_hash",
            "capability_pack_ref",
            "prompt_bundle_ref",
            "prompt_bundle_hash",
            "skill_bundle_ref",
            "skill_bundle_hash",
            "tool_policy_ref",
            "tool_policy_hash",
            "context_policy_ref",
            "context_policy_hash",
            "runtime_contract_hash",
            "definition_source",
            "definition_status",
        )
        result = dict(zip(fields, row, strict=True))
        if result["definition_status"] != "ACTIVE":
            raise KernelError(
                "AGENT_DEFINITION_DISABLED",
                f"exact Agent Definition is not deployable: {agent_id}@{definition_version}",
            )
        result["capabilities"] = self._definition_capabilities(
            agent_id, definition_version
        )
        return result

    def list_definitions(
        self,
        *,
        agent_id: str = "",
        activation_status: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if limit <= 0 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        clauses: list[str] = []
        parameters: list[Any] = []
        if agent_id:
            clauses.append("definition.agent_id=%s")
            parameters.append(agent_id)
        if activation_status:
            clauses.append("activation.activation_status=%s")
            parameters.append(activation_status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        self.cursor.execute(
            f"""
            SELECT definition.agent_id, definition.definition_version,
                   definition.agent_type, definition.domain, definition.role,
                   definition.status, definition.definition_hash,
                   definition.input_contract_ref,
                   definition.output_contract_ref,
                   definition.authority_scope_ref,
                   definition.default_scope_policy_ref,
                   definition.allowed_tools,
                   definition.allowed_context_types,
                   definition.execution_policy_ref,
                   definition.approval_policy_ref,
                   definition.quality_policy_ref,
                   contract.runtime_contract_hash,
                   contract.capability_pack_ref,
                   contract.prompt_bundle_ref, contract.prompt_bundle_hash,
                   contract.skill_bundle_ref, contract.skill_bundle_hash,
                   contract.tool_policy_ref, contract.tool_policy_hash,
                   contract.context_policy_ref, contract.context_policy_hash,
                   contract.definition_source,
                   COALESCE(activation.activation_status, 'UNACTIVATED'),
                   COALESCE(activation.activation_version, 0),
                   definition.created_at
            FROM authority_agent_definition AS definition
            LEFT JOIN authority_agent_definition_runtime_contract AS contract
              ON contract.agent_id=definition.agent_id
             AND contract.definition_version=definition.definition_version
            LEFT JOIN authority_agent_definition_activation AS activation
              ON activation.agent_id=definition.agent_id
             AND activation.definition_version=definition.definition_version
            {where}
            ORDER BY definition.agent_id, definition.definition_version DESC
            LIMIT %s
            """,
            [*parameters, limit],
        )
        fields = (
            "agent_id",
            "definition_version",
            "agent_type",
            "domain",
            "role",
            "definition_status",
            "definition_hash",
            "input_contract_ref",
            "output_contract_ref",
            "authority_scope_ref",
            "default_scope_policy_ref",
            "allowed_tools",
            "allowed_context_types",
            "execution_policy_ref",
            "approval_policy_ref",
            "quality_policy_ref",
            "runtime_contract_hash",
            "capability_pack_ref",
            "prompt_bundle_ref",
            "prompt_bundle_hash",
            "skill_bundle_ref",
            "skill_bundle_hash",
            "tool_policy_ref",
            "tool_policy_hash",
            "context_policy_ref",
            "context_policy_hash",
            "definition_source",
            "activation_status",
            "activation_version",
            "created_at",
        )
        results = [
            dict(zip(fields, row, strict=True)) for row in self.cursor.fetchall()
        ]
        capability_sets = self._capabilities_for_definitions(
            tuple(
                (str(result["agent_id"]), int(result["definition_version"]))
                for result in results
            )
        )
        for result in results:
            result["capabilities"] = capability_sets.get(
                (str(result["agent_id"]), int(result["definition_version"])), []
            )
        return results

    def register_chapter_node_binding(
        self, binding: ChapterNodeExecutionBinding
    ) -> ChapterNodeExecutionBinding:
        operation_name, operation_version = _version_ref(
            binding.operation_definition_ref
        )
        agent_id, agent_version = _integer_version_ref(binding.agent_definition_ref)
        capability_id, capability_version = _integer_version_ref(binding.capability_ref)
        definition = self.cursor.execute(
            """
            SELECT definition_hash FROM authority_operation_definition
            WHERE name=%s AND definition_version=%s AND enabled=TRUE
            """,
            [operation_name, operation_version],
        ).fetchone()
        if (
            definition is None
            or str(definition[0]) != binding.operation_definition_hash
        ):
            raise KernelError(
                "CHAPTER_AGENT_OPERATION_DEFINITION_DRIFT",
                "Chapter binding differs from the enabled OperationDefinition",
            )
        self.cursor.execute(
            """
            INSERT INTO authority_chapter_node_agent_binding (
                binding_id, binding_version,
                workflow_definition_ref, workflow_node_id,
                operation_definition_name, operation_definition_version,
                operation_definition_hash,
                agent_id, agent_definition_version, agent_definition_hash,
                capability_id, capability_version, capability_hash,
                execution_capability_id, capability_pack_ref,
                capability_pack_compilation_hash,
                input_contract_ref, output_contract_ref,
                domain_acceptance_policy_ref, commit_authority,
                binding_status, release_sha, binding_hash,
                created_by_operation_id
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (binding_id, binding_version) DO NOTHING
            """,
            [
                binding.binding_id,
                binding.binding_version,
                binding.workflow_definition_ref,
                binding.workflow_node_id,
                operation_name,
                operation_version,
                binding.operation_definition_hash,
                agent_id,
                agent_version,
                binding.agent_definition_hash,
                capability_id,
                capability_version,
                binding.capability_hash,
                binding.execution_capability_id,
                binding.capability_pack_ref,
                binding.capability_pack_compilation_hash,
                binding.input_contract_ref,
                binding.output_contract_ref,
                binding.domain_acceptance_policy_ref,
                binding.commit_authority,
                binding.status,
                binding.release_sha,
                binding.binding_hash,
                binding.created_by_operation_id,
            ],
        )
        self.cursor.execute(
            """
            SELECT binding_hash
            FROM authority_chapter_node_agent_binding
            WHERE binding_id=%s AND binding_version=%s
            """,
            [binding.binding_id, binding.binding_version],
        )
        row = self.cursor.fetchone()
        if row is None or str(row[0]) != binding.binding_hash:
            raise KernelError(
                "CHAPTER_AGENT_BINDING_CONFLICT",
                "Chapter node binding version has different content",
            )
        return binding

    def activate_chapter_node_binding(
        self,
        *,
        workflow_definition_ref: str,
        workflow_node_id: str,
        binding_id: str,
        binding_version: int,
        status: AgentDefinitionActivationStatus,
        expected_activation_version: int,
        reason: str,
        activated_by: str,
        activated_by_operation_id: str,
    ) -> dict[str, Any]:
        status = AgentDefinitionActivationStatus(status)
        if status is AgentDefinitionActivationStatus.ACTIVE:
            self.cursor.execute(
                """
                SELECT binding_status, agent_id, agent_definition_version
                FROM authority_chapter_node_agent_binding
                WHERE binding_id=%s AND binding_version=%s
                  AND workflow_definition_ref=%s AND workflow_node_id=%s
                """,
                [
                    binding_id,
                    binding_version,
                    workflow_definition_ref,
                    workflow_node_id,
                ],
            )
            binding = self.cursor.fetchone()
            if binding is None or str(binding[0]) != "ACTIVE":
                raise KernelError(
                    "CHAPTER_AGENT_BINDING_NOT_PRODUCTION_ACTIVE",
                    "only an ACTIVE immutable Chapter Agent Binding may be activated",
                )
            definition = self.resolve_active_definition(str(binding[1]))
            if int(definition["definition_version"]) != int(binding[2]):
                raise KernelError(
                    "CHAPTER_AGENT_BINDING_DEFINITION_NOT_ACTIVE",
                    "Chapter Agent Binding must reference the active Agent Definition version",
                )
        parameters = [
            workflow_definition_ref,
            workflow_node_id,
            binding_id,
            binding_version,
            status.value,
            reason,
            activated_by,
            activated_by_operation_id,
        ]
        if expected_activation_version == 0:
            self.cursor.execute(
                """
                INSERT INTO authority_chapter_node_agent_binding_activation (
                    workflow_definition_ref, workflow_node_id,
                    binding_id, binding_version, activation_status,
                    activation_version, reason, activated_by,
                    activated_by_operation_id
                ) VALUES (%s, %s, %s, %s, %s, 1, %s, %s, %s)
                ON CONFLICT (workflow_definition_ref, workflow_node_id)
                DO NOTHING
                """,
                parameters,
            )
        elif expected_activation_version > 0:
            self.cursor.execute(
                """
                UPDATE authority_chapter_node_agent_binding_activation
                SET binding_id=%s, binding_version=%s, activation_status=%s,
                    activation_version=activation_version + 1,
                    reason=%s, activated_by=%s,
                    activated_by_operation_id=%s, updated_at=NOW()
                WHERE workflow_definition_ref=%s AND workflow_node_id=%s
                  AND activation_version=%s
                  AND activation_status <> 'RETIRED'
                """,
                [
                    binding_id,
                    binding_version,
                    status.value,
                    reason,
                    activated_by,
                    activated_by_operation_id,
                    workflow_definition_ref,
                    workflow_node_id,
                    expected_activation_version,
                ],
            )
        else:
            raise KernelError(
                "CHAPTER_AGENT_BINDING_ACTIVATION_VERSION_INVALID",
                "expected activation version cannot be negative",
            )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "CHAPTER_AGENT_BINDING_ACTIVATION_CONFLICT",
                "Chapter Agent Binding changed concurrently or is retired",
            )
        return self.resolve_active_chapter_node_binding(
            workflow_definition_ref=workflow_definition_ref,
            workflow_node_id=workflow_node_id,
            allow_disabled=True,
        )

    def resolve_active_chapter_node_binding(
        self,
        *,
        workflow_definition_ref: str,
        workflow_node_id: str,
        allow_disabled: bool = False,
    ) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT binding.binding_id, binding.binding_version,
                   binding.workflow_definition_ref, binding.workflow_node_id,
                   binding.operation_definition_name,
                   binding.operation_definition_version,
                   binding.operation_definition_hash,
                   binding.agent_id, binding.agent_definition_version,
                   binding.agent_definition_hash,
                   binding.capability_id, binding.capability_version,
                   binding.capability_hash,
                   binding.execution_capability_id,
                   binding.capability_pack_ref,
                   binding.capability_pack_compilation_hash,
                   binding.input_contract_ref, binding.output_contract_ref,
                   binding.domain_acceptance_policy_ref,
                   binding.commit_authority, binding.binding_status,
                   binding.release_sha, binding.binding_hash,
                   activation.activation_status,
                   activation.activation_version
            FROM authority_chapter_node_agent_binding_activation AS activation
            JOIN authority_chapter_node_agent_binding AS binding
              ON binding.binding_id=activation.binding_id
             AND binding.binding_version=activation.binding_version
            WHERE activation.workflow_definition_ref=%s
              AND activation.workflow_node_id=%s
            """,
            [workflow_definition_ref, workflow_node_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "CHAPTER_AGENT_BINDING_NOT_FOUND",
                f"No active Agent Binding for node {workflow_node_id}",
            )
        fields = (
            "binding_id",
            "binding_version",
            "workflow_definition_ref",
            "workflow_node_id",
            "operation_definition_name",
            "operation_definition_version",
            "operation_definition_hash",
            "agent_id",
            "agent_definition_version",
            "agent_definition_hash",
            "capability_id",
            "capability_version",
            "capability_hash",
            "execution_capability_id",
            "capability_pack_ref",
            "capability_pack_compilation_hash",
            "input_contract_ref",
            "output_contract_ref",
            "domain_acceptance_policy_ref",
            "commit_authority",
            "binding_status",
            "release_sha",
            "binding_hash",
            "activation_status",
            "activation_version",
        )
        result = dict(zip(fields, row, strict=True))
        if not allow_disabled and result["activation_status"] != "ACTIVE":
            raise KernelError(
                "CHAPTER_AGENT_BINDING_DISABLED",
                f"Agent Binding is not active for node {workflow_node_id}",
            )
        if not allow_disabled:
            definition = self.resolve_active_definition(str(result["agent_id"]))
            if int(definition["definition_version"]) != int(
                result["agent_definition_version"]
            ):
                raise KernelError(
                    "CHAPTER_AGENT_DEFINITION_VERSION_NOT_ACTIVE",
                    "Chapter binding references a non-active Agent Definition version",
                )
        return result

    def save_runtime_binding(self, binding: AgentRuntimeBinding) -> AgentRuntimeBinding:
        operation_name, operation_version = _version_ref(
            binding.operation_definition_ref
        )
        if binding.capability_pack_deployment_id:
            chapter_binding_id = None
            chapter_binding_version = None
            self._validate_pack_runtime_binding(binding)
        else:
            chapter_binding_id, chapter_binding_version = _integer_version_ref(
                binding.chapter_node_binding_ref
            )
            active = self.resolve_active_chapter_node_binding(
                workflow_definition_ref=binding.workflow_definition_ref,
                workflow_node_id=binding.workflow_node_id,
            )
            expected = {
                "binding_id": chapter_binding_id,
                "binding_version": chapter_binding_version,
                "agent_id": binding.agent_id,
                "agent_definition_version": binding.agent_definition_version,
                "agent_definition_hash": binding.agent_definition_hash,
                "capability_id": binding.capability_id,
                "capability_version": binding.capability_version,
                "capability_hash": binding.capability_hash,
                "execution_capability_id": binding.execution_capability_id,
                "capability_pack_ref": binding.capability_pack_ref,
                "capability_pack_compilation_hash": (
                    binding.capability_pack_compilation_hash
                ),
                "commit_authority": binding.commit_authority,
                "release_sha": binding.release_sha,
            }
            drift = [
                key for key, value in expected.items() if str(active[key]) != str(value)
            ]
            if drift:
                raise KernelError(
                    "AGENT_RUNTIME_BINDING_DRIFT",
                    "Runtime binding differs from active legacy Chapter binding: "
                    + ", ".join(drift),
                )
        self.cursor.execute(
            """
            SELECT definition_hash
            FROM authority_operation_definition
            WHERE name=%s AND definition_version=%s
            """,
            [operation_name, operation_version],
        )
        operation_definition = self.cursor.fetchone()
        if (
            operation_definition is None
            or str(operation_definition[0]) != binding.operation_definition_hash
        ):
            raise KernelError(
                "AGENT_RUNTIME_OPERATION_DEFINITION_DRIFT",
                "Runtime binding differs from the Authority OperationDefinition",
            )
        payload = asdict(binding)
        self.cursor.execute(
            """
            INSERT INTO authority_agent_runtime_binding (
                binding_id, project_id, workspace_id, book_id,
                workflow_definition_ref, workflow_node_id,
                operation_definition_name, operation_definition_version,
                operation_definition_hash, operation_id, attempt_id,
                fencing_token, work_order_id,
                agent_id, agent_definition_version, agent_definition_hash,
                capability_id, capability_version, capability_hash,
                execution_capability_id,
                chapter_node_binding_id, chapter_node_binding_version,
                capability_pack_ref, capability_pack_compilation_hash,
                context_bundle_asset_version_id, context_bundle_hash,
                prompt_bundle_ref, prompt_bundle_hash,
                skill_bundle_ref, skill_bundle_hash,
                tool_policy_ref, tool_policy_hash,
                tool_permission_snapshot_ref, tool_permission_snapshot_hash,
                context_policy_ref, context_policy_hash,
                route_snapshot_ref, route_snapshot_hash,
                input_manifest_ref, input_manifest_hash,
                budget_policy_ref, timeout_policy_ref, approval_policy_ref,
                validation_policy_ref, commit_policy_ref, commit_authority,
                release_sha, binding_hash,
                capability_pack_deployment_id,
                capability_pack_activation_version,
                capability_pack_binding_set_id,
                capability_pack_binding_set_hash,
                capability_pack_scope_type,
                capability_pack_assignment_ref,
                capability_pack_attempt_snapshot_id,
                capability_pack_attempt_snapshot_hash
            ) VALUES (
                %(binding_id)s, %(project_id)s, %(workspace_id)s, %(book_id)s,
                %(workflow_definition_ref)s, %(workflow_node_id)s,
                %(operation_definition_name)s, %(operation_definition_version)s,
                %(operation_definition_hash)s, %(operation_id)s, %(attempt_id)s,
                %(fencing_token)s, %(work_order_id)s,
                %(agent_id)s, %(agent_definition_version)s,
                %(agent_definition_hash)s,
                %(capability_id)s, %(capability_version)s, %(capability_hash)s,
                %(execution_capability_id)s,
                %(chapter_node_binding_id)s, %(chapter_node_binding_version)s,
                %(capability_pack_ref)s,
                %(capability_pack_compilation_hash)s,
                %(context_bundle_asset_version_id)s, %(context_bundle_hash)s,
                %(prompt_bundle_ref)s, %(prompt_bundle_hash)s,
                %(skill_bundle_ref)s, %(skill_bundle_hash)s,
                %(tool_policy_ref)s, %(tool_policy_hash)s,
                %(tool_permission_snapshot_ref)s,
                %(tool_permission_snapshot_hash)s,
                %(context_policy_ref)s, %(context_policy_hash)s,
                %(route_snapshot_ref)s, %(route_snapshot_hash)s,
                %(input_manifest_ref)s, %(input_manifest_hash)s,
                %(budget_policy_ref)s, %(timeout_policy_ref)s,
                %(approval_policy_ref)s, %(validation_policy_ref)s,
                %(commit_policy_ref)s, %(commit_authority)s,
                %(release_sha)s, %(binding_hash)s,
                %(capability_pack_deployment_id)s,
                %(capability_pack_activation_version)s,
                %(capability_pack_binding_set_id)s,
                %(capability_pack_binding_set_hash)s,
                %(capability_pack_scope_type)s,
                %(capability_pack_assignment_ref)s,
                %(capability_pack_attempt_snapshot_id)s,
                %(capability_pack_attempt_snapshot_hash)s
            )
            ON CONFLICT (binding_id) DO NOTHING
            """,
            {
                **payload,
                "book_id": binding.book_id or None,
                "operation_definition_name": operation_name,
                "operation_definition_version": operation_version,
                "chapter_node_binding_id": chapter_binding_id,
                "chapter_node_binding_version": chapter_binding_version,
                "binding_hash": binding.binding_hash,
                "capability_pack_deployment_id": (
                    binding.capability_pack_deployment_id or None
                ),
                "capability_pack_activation_version": (
                    binding.capability_pack_activation_version or None
                ),
                "capability_pack_binding_set_id": (
                    binding.capability_pack_binding_set_id or None
                ),
                "capability_pack_binding_set_hash": (
                    binding.capability_pack_binding_set_hash or None
                ),
                "capability_pack_scope_type": (
                    binding.capability_pack_scope_type or None
                ),
                "capability_pack_assignment_ref": (
                    binding.capability_pack_assignment_ref or None
                ),
                "capability_pack_attempt_snapshot_id": (
                    binding.capability_pack_attempt_snapshot_id or None
                ),
                "capability_pack_attempt_snapshot_hash": (
                    binding.capability_pack_attempt_snapshot_hash or None
                ),
            },
        )
        self.cursor.execute(
            """
            SELECT binding_hash
            FROM authority_agent_runtime_binding
            WHERE binding_id=%s
            """,
            [binding.binding_id],
        )
        row = self.cursor.fetchone()
        if row is None or str(row[0]) != binding.binding_hash:
            raise KernelError(
                "AGENT_RUNTIME_BINDING_CONFLICT",
                "Agent Runtime binding id already has different content",
            )
        return binding

    def _validate_pack_runtime_binding(self, binding: AgentRuntimeBinding) -> None:
        self.cursor.execute(
            """
            SELECT deployment.pack_id, deployment.pack_version,
                   deployment.target_scope_type,
                   COALESCE(deployment.project_id, ''),
                   COALESCE(deployment.workspace_id, ''),
                   COALESCE(deployment.book_id, ''),
                   deployment.workflow_definition_ref,
                   compilation.compilation_hash, compilation.release_sha,
                   binding_set.binding_set_id, binding_set.binding_set_hash,
                   binding_set.node_bindings
            FROM authority_capability_pack_deployment AS deployment
            JOIN authority_capability_pack_compilation AS compilation
              ON compilation.compilation_id=deployment.compilation_id
            JOIN authority_capability_pack_binding_set AS binding_set
              ON binding_set.binding_set_id=deployment.binding_set_id
            WHERE deployment.deployment_id=%s
            """,
            [binding.capability_pack_deployment_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "CAPABILITY_PACK_DEPLOYMENT_NOT_FOUND",
                "runtime binding references an unknown Pack Deployment",
            )
        nodes = [
            dict(item)
            for item in row[11]
            if str(item.get("workflow_node_id")) == binding.workflow_node_id
        ]
        if len(nodes) != 1:
            raise KernelError(
                "CAPABILITY_PACK_WORKFLOW_NODE_AMBIGUOUS",
                "runtime binding requires exactly one Pack Workflow Node",
            )
        node = nodes[0]
        expected_ref = (
            f"pack-binding-set:{row[9]}:{binding.workflow_node_id}@"
            f"{binding.capability_pack_activation_version}"
        )
        deployment_expected = {
            "capability_pack_ref": f"{row[0]}@{row[1]}",
            "capability_pack_scope_type": row[2],
            "workflow_definition_ref": row[6],
            "capability_pack_compilation_hash": row[7],
            "release_sha": row[8],
            "capability_pack_binding_set_id": row[9],
            "capability_pack_binding_set_hash": row[10],
            "chapter_node_binding_ref": expected_ref,
        }
        node_expected = {
            "operation_definition_ref": node["operation_definition_ref"],
            "operation_definition_hash": node["operation_definition_hash"],
            "agent_definition_hash": node["agent_definition_hash"],
            "capability_hash": node["capability_hash"],
            "execution_capability_id": node["execution_capability_id"],
            "commit_authority": node["commit_authority"],
        }
        drift = [
            key
            for key, expected in {**deployment_expected, **node_expected}.items()
            if str(getattr(binding, key)) != str(expected)
        ]
        agent_id, _, agent_version = str(node["agent_definition_ref"]).rpartition("@")
        capability_id, _, capability_version = str(node["capability_ref"]).rpartition(
            "@"
        )
        if (binding.agent_id, binding.agent_definition_version) != (
            agent_id,
            int(agent_version),
        ):
            drift.append("agent_definition_ref")
        if (binding.capability_id, binding.capability_version) != (
            capability_id,
            int(capability_version),
        ):
            drift.append("capability_ref")
        scope_identities = {
            "SYSTEM": ("", "", ""),
            "PROJECT": (binding.project_id, "", ""),
            "WORKSPACE": (binding.project_id, binding.workspace_id, ""),
            "BOOK": (binding.project_id, binding.workspace_id, binding.book_id),
        }
        if (str(row[3]), str(row[4]), str(row[5])) != scope_identities.get(
            str(row[2]), (None, None, None)
        ):
            drift.append("scope_identity")
        if drift:
            raise KernelError(
                "CAPABILITY_PACK_RUNTIME_BINDING_DRIFT",
                "runtime binding differs from immutable Pack facts: "
                + ", ".join(sorted(set(drift))),
            )

    def _definition_capabilities(
        self, agent_id: str, definition_version: int
    ) -> list[dict[str, Any]]:
        return self._capabilities_for_definitions(
            ((agent_id, definition_version),)
        ).get((agent_id, definition_version), [])

    def _capabilities_for_definitions(
        self, identities: tuple[tuple[str, int], ...]
    ) -> dict[tuple[str, int], list[dict[str, Any]]]:
        if not identities:
            return {}
        placeholders = ", ".join("(%s, %s)" for _ in identities)
        self.cursor.execute(
            f"""
            SELECT link.agent_id, link.definition_version,
                   capability.capability_id,
                   capability.capability_version,
                   capability.domain,
                   capability.input_schema_ref,
                   capability.output_schema_ref,
                   capability.risk_class,
                   capability.qualification_status,
                   capability.capability_hash,
                   mapping.execution_capability_id,
                   mapping.execution_capability_hash,
                   mapping.mapping_hash
            FROM authority_agent_definition_capability AS link
            JOIN authority_agent_capability AS capability
              ON capability.capability_id=link.capability_id
             AND capability.capability_version=link.capability_version
            JOIN authority_agent_capability_execution_mapping AS mapping
              ON mapping.capability_id=capability.capability_id
             AND mapping.capability_version=capability.capability_version
            WHERE (link.agent_id, link.definition_version) IN ({placeholders})
            ORDER BY link.agent_id, link.definition_version,
                     capability.capability_id, capability.capability_version
            """,
            [value for identity in identities for value in identity],
        )
        fields = (
            "agent_id",
            "definition_version",
            "capability_id",
            "capability_version",
            "domain",
            "input_schema_ref",
            "output_schema_ref",
            "risk_class",
            "qualification_status",
            "capability_hash",
            "execution_capability_id",
            "execution_capability_hash",
            "mapping_hash",
        )
        grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
        for row in self.cursor.fetchall():
            payload = dict(zip(fields, row, strict=True))
            identity = (
                str(payload.pop("agent_id")),
                int(payload.pop("definition_version")),
            )
            grouped.setdefault(identity, []).append(payload)
        return grouped


def _tool_payload(tool: AgentToolSpec) -> dict[str, Any]:
    return {
        "tool_name": tool.tool_name,
        "kind": tool.kind.value,
        "input_schema_ref": tool.input_schema_ref,
        "output_schema_ref": tool.output_schema_ref,
        "allowed_roles": [role.value for role in tool.allowed_roles],
        "external_effect_required": tool.external_effect_required,
        "authority_command_type": tool.authority_command_type,
    }


def _tool_from_payload(payload: Mapping[str, Any]) -> AgentToolSpec:
    return AgentToolSpec(
        tool_name=str(payload["tool_name"]),
        kind=str(payload["kind"]),
        input_schema_ref=str(payload["input_schema_ref"]),
        output_schema_ref=str(payload["output_schema_ref"]),
        allowed_roles=tuple(str(item) for item in payload["allowed_roles"]),
        external_effect_required=bool(payload.get("external_effect_required", False)),
        authority_command_type=str(payload.get("authority_command_type") or ""),
    )


def _version_ref(value: str) -> tuple[str, str]:
    identity, separator, version = str(value).rpartition("@")
    if not separator or not identity or not version:
        raise ValueError(f"version ref must be exact: {value}")
    return identity, version


def _hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _integer_version_ref(value: str) -> tuple[str, int]:
    identity, version = _version_ref(value)
    try:
        parsed = int(version)
    except ValueError as exc:
        raise ValueError(f"version ref must use an integer version: {value}") from exc
    if parsed <= 0:
        raise ValueError(f"version ref must be positive: {value}")
    return identity, parsed


__all__ = ["PostgresAgentRuntimeRepository"]
