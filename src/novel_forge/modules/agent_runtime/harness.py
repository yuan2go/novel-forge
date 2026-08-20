"""Governed multi-turn Agent Harness over the Industrial Runtime.

The Harness owns reasoning-session provenance, never business truth.  Callers
must run it inside an already leased Authority Attempt.  Model turns and
external tools are represented by ports whose results carry the owning
ExternalEffect identity; deterministic read/query tools may omit one.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import hashlib
import json
from typing import Any, Mapping, Protocol, Sequence

from novel_forge.modules.command_kernel.errors import KernelError


class AutonomousAgentRole(StrEnum):
    STUDIO_DIRECTOR = "STUDIO_DIRECTOR"
    RESEARCH_KNOWLEDGE = "RESEARCH_KNOWLEDGE"


class AgentHarnessStatus(StrEnum):
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING_TOOL = "WAITING_TOOL"
    CHECKPOINTED = "CHECKPOINTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    ESCALATION_REQUIRED = "ESCALATION_REQUIRED"


class AgentTranscriptEventType(StrEnum):
    REQUEST_STARTED = "REQUEST_STARTED"
    MODEL_MESSAGE = "MODEL_MESSAGE"
    TOOL_REQUESTED = "TOOL_REQUESTED"
    TOOL_OBSERVED = "TOOL_OBSERVED"
    AUTHORITY_COMMAND_SUBMITTED = "AUTHORITY_COMMAND_SUBMITTED"
    REQUEST_COMMITTED = "REQUEST_COMMITTED"
    REQUEST_FAILED = "REQUEST_FAILED"
    CHECKPOINT = "CHECKPOINT"
    SESSION_STOPPED = "SESSION_STOPPED"


class AgentToolKind(StrEnum):
    READ_ONLY_QUERY = "READ_ONLY_QUERY"
    TYPED_CAPABILITY = "TYPED_CAPABILITY"
    AUTHORITY_COMMAND = "AUTHORITY_COMMAND"


_FORBIDDEN_DIRECT_MUTATIONS = frozenset(
    {
        "canon.mutate",
        "narrative_state.mutate",
        "arc_actual.advance",
        "narrative_obligation.resolve",
        "plan.activate",
        "chapter.accept",
    }
)


@dataclass(frozen=True, slots=True)
class AcceptedBoundaryRef:
    book_id: str
    book_run_id: str
    accepted_through_chapter: int
    acceptance_id: str
    projection_set_id: str

    def __post_init__(self) -> None:
        if (
            not self.book_id.strip()
            or not self.book_run_id.strip()
            or self.accepted_through_chapter < 0
        ):
            raise ValueError("accepted boundary is incomplete")
        if self.accepted_through_chapter and (
            not self.acceptance_id.strip() or not self.projection_set_id.strip()
        ):
            raise ValueError("accepted chapter requires its complete projection set")


@dataclass(frozen=True, slots=True)
class AgentHarnessBudget:
    max_turns: int
    max_tool_calls: int
    max_external_effects: int
    max_input_tokens: int
    max_output_tokens: int
    max_cost_amount: str

    def __post_init__(self) -> None:
        numeric = (
            self.max_turns,
            self.max_tool_calls,
            self.max_external_effects,
            self.max_input_tokens,
            self.max_output_tokens,
        )
        if any(value <= 0 for value in numeric):
            raise ValueError("Agent Harness budget limits must be positive")
        try:
            if float(self.max_cost_amount) < 0:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ValueError("Agent Harness cost budget is invalid") from exc


@dataclass(frozen=True, slots=True)
class AgentHarnessUsage:
    turns: int = 0
    tool_calls: int = 0
    external_effects: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_amount: str = "0"

    def add(
        self,
        *,
        turns: int = 0,
        tool_calls: int = 0,
        external_effects: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_amount: str = "0",
    ) -> "AgentHarnessUsage":
        return AgentHarnessUsage(
            turns=self.turns + turns,
            tool_calls=self.tool_calls + tool_calls,
            external_effects=self.external_effects + external_effects,
            input_tokens=self.input_tokens + input_tokens,
            output_tokens=self.output_tokens + output_tokens,
            cost_amount=str(float(self.cost_amount) + float(cost_amount)),
        )

    def require_within(self, budget: AgentHarnessBudget) -> None:
        exceeded = [
            label
            for label, used, maximum in (
                ("turns", self.turns, budget.max_turns),
                ("tool_calls", self.tool_calls, budget.max_tool_calls),
                ("external_effects", self.external_effects, budget.max_external_effects),
                ("input_tokens", self.input_tokens, budget.max_input_tokens),
                ("output_tokens", self.output_tokens, budget.max_output_tokens),
                ("cost", float(self.cost_amount), float(budget.max_cost_amount)),
            )
            if used > maximum
        ]
        if exceeded:
            raise KernelError(
                "AGENT_HARNESS_BUDGET_EXHAUSTED",
                "Agent Harness hard budget exceeded: " + ", ".join(exceeded),
            )


@dataclass(frozen=True, slots=True)
class AgentToolSpec:
    tool_name: str
    kind: AgentToolKind
    input_schema_ref: str
    output_schema_ref: str
    allowed_roles: tuple[AutonomousAgentRole, ...]
    external_effect_required: bool = False
    authority_command_type: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", AgentToolKind(self.kind))
        object.__setattr__(
            self,
            "allowed_roles",
            tuple(AutonomousAgentRole(role) for role in self.allowed_roles),
        )
        if not all(
            value.strip()
            for value in (self.tool_name, self.input_schema_ref, self.output_schema_ref)
        ) or not self.allowed_roles:
            raise ValueError("Agent Tool specification is incomplete")
        lowered = self.tool_name.strip().lower()
        if lowered in _FORBIDDEN_DIRECT_MUTATIONS:
            raise ValueError("Agent Tool cannot expose a direct Authority mutation")
        if self.kind is AgentToolKind.AUTHORITY_COMMAND:
            if not self.authority_command_type.strip():
                raise ValueError("Authority Command Tool requires a command type")
            if self.authority_command_type.strip().lower() in _FORBIDDEN_DIRECT_MUTATIONS:
                raise ValueError("Agent cannot bind a direct truth-mutation command")


@dataclass(frozen=True, slots=True)
class AgentHarnessSession:
    agent_session_id: str
    project_id: str
    workspace_id: str
    operation_id: str
    role: AutonomousAgentRole
    status: AgentHarnessStatus
    accepted_boundary: AcceptedBoundaryRef
    tool_policy: tuple[AgentToolSpec, ...]
    skill_bindings: tuple[Mapping[str, Any], ...]
    budget: AgentHarnessBudget
    usage: AgentHarnessUsage = field(default_factory=AgentHarnessUsage)
    next_sequence: int = 1
    version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", AutonomousAgentRole(self.role))
        object.__setattr__(self, "status", AgentHarnessStatus(self.status))
        if any(
            not value.strip()
            for value in (
                self.agent_session_id,
                self.project_id,
                self.workspace_id,
                self.operation_id,
            )
        ) or self.next_sequence <= 0 or self.version <= 0:
            raise ValueError("Agent Harness session is incomplete")
        names = [tool.tool_name for tool in self.tool_policy]
        if len(names) != len(set(names)):
            raise ValueError("Agent Harness Tool names must be unique")
        for binding in self.skill_bindings:
            required = ("skill_id", "skill_version", "skill_hash")
            if any(not str(binding.get(key) or "").strip() for key in required):
                raise ValueError("Agent Harness Skill binding is not frozen")


@dataclass(frozen=True, slots=True)
class AgentToolCall:
    tool_name: str
    arguments: Mapping[str, Any]
    reason: str


@dataclass(frozen=True, slots=True)
class AgentModelTurn:
    message: str
    operation_id: str
    attempt_id: str
    external_effect_id: str
    input_tokens: int
    output_tokens: int
    cost_amount: str
    tool_call: AgentToolCall | None = None
    final_response: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (self.message, self.operation_id, self.attempt_id, self.external_effect_id)
        ):
            raise ValueError("model turn requires Attempt/ExternalEffect evidence")
        if (self.tool_call is None) == (self.final_response is None):
            raise ValueError("model turn must choose one Tool or return one final response")
        if min(self.input_tokens, self.output_tokens) < 0 or float(self.cost_amount) < 0:
            raise ValueError("model turn usage is invalid")


@dataclass(frozen=True, slots=True)
class AgentToolObservation:
    tool_name: str
    result: Mapping[str, Any]
    operation_id: str
    attempt_id: str
    external_effect_id: str = ""
    authority_command_id: str = ""

    def __post_init__(self) -> None:
        if not self.tool_name.strip() or not self.result:
            raise ValueError("Tool observation is incomplete")
        if bool(self.operation_id) != bool(self.attempt_id):
            raise ValueError("Tool observation Attempt identity is incomplete")


class AgentHarnessTranscriptPort(Protocol):
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
    ) -> AgentHarnessSession: ...

    def committed_request_events(
        self, *, agent_session_id: str
    ) -> tuple[Mapping[str, Any], ...]: ...


class AgentModelTurnPort(Protocol):
    external_effect_backed: bool

    def next_turn(
        self,
        *,
        session: AgentHarnessSession,
        request_id: str,
        turn_number: int,
        instruction: str,
        committed_transcript: Sequence[Mapping[str, Any]],
        observations: Sequence[AgentToolObservation],
    ) -> AgentModelTurn: ...


class AgentToolRouter(Protocol):
    def invoke(
        self,
        *,
        spec: AgentToolSpec,
        call: AgentToolCall,
        session: AgentHarnessSession,
        request_id: str,
        turn_number: int,
    ) -> AgentToolObservation: ...


class AgentCancellationPort(Protocol):
    def cancellation_requested(self, *, operation_id: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class AgentHarnessResult:
    session: AgentHarnessSession
    request_id: str
    response: Mapping[str, Any]
    observations: tuple[AgentToolObservation, ...]


class UnifiedAgentHarness:
    """Bounded multi-turn loop with fail-closed Tool and Authority boundaries."""

    def __init__(
        self,
        *,
        transcript: AgentHarnessTranscriptPort,
        model: AgentModelTurnPort,
        tools: AgentToolRouter,
        cancellation: AgentCancellationPort,
    ) -> None:
        if not getattr(model, "external_effect_backed", False):
            raise ValueError("Agent Harness model turns must be ExternalEffect-backed")
        self.transcript = transcript
        self.model = model
        self.tools = tools
        self.cancellation = cancellation

    def execute_request(
        self,
        *,
        session: AgentHarnessSession,
        request_id: str,
        instruction: str,
        attempt_id: str,
        trace_id: str,
    ) -> AgentHarnessResult:
        if session.status not in {AgentHarnessStatus.READY, AgentHarnessStatus.CHECKPOINTED}:
            raise KernelError(
                "AGENT_HARNESS_SESSION_NOT_RUNNABLE",
                f"session cannot run from {session.status.value}",
            )
        if not all(value.strip() for value in (request_id, instruction, attempt_id, trace_id)):
            raise ValueError("Agent Harness request identity is incomplete")
        current = self.transcript.append_event(
            session=session,
            request_id=request_id,
            turn_number=0,
            event_type=AgentTranscriptEventType.REQUEST_STARTED,
            payload={"instruction": instruction, "accepted_boundary": asdict(session.accepted_boundary)},
            trace_id=trace_id,
            attempt_id=attempt_id,
            target_status=AgentHarnessStatus.RUNNING,
        )
        observations: list[AgentToolObservation] = []
        committed = self.transcript.committed_request_events(
            agent_session_id=session.agent_session_id
        )
        try:
            for turn_number in range(1, current.budget.max_turns + 1):
                if self.cancellation.cancellation_requested(operation_id=current.operation_id):
                    current = self.transcript.append_event(
                        session=current,
                        request_id=request_id,
                        turn_number=turn_number,
                        event_type=AgentTranscriptEventType.SESSION_STOPPED,
                        payload={"reason": "operation_cancellation_requested"},
                        trace_id=trace_id,
                        attempt_id=attempt_id,
                        target_status=AgentHarnessStatus.CANCELLED,
                    )
                    raise KernelError("AGENT_HARNESS_CANCELLED", "Agent request was cancelled")
                turn = self.model.next_turn(
                    session=current,
                    request_id=request_id,
                    turn_number=turn_number,
                    instruction=instruction,
                    committed_transcript=committed,
                    observations=tuple(observations),
                )
                if turn.operation_id != current.operation_id or turn.attempt_id != attempt_id:
                    raise KernelError(
                        "AGENT_HARNESS_EXECUTION_IDENTITY_DRIFT",
                        "model turn is not owned by the leased Operation/Attempt",
                    )
                usage = current.usage.add(
                    turns=1,
                    external_effects=1,
                    input_tokens=turn.input_tokens,
                    output_tokens=turn.output_tokens,
                    cost_amount=turn.cost_amount,
                )
                usage.require_within(current.budget)
                current = self.transcript.append_event(
                    session=current,
                    request_id=request_id,
                    turn_number=turn_number,
                    event_type=AgentTranscriptEventType.MODEL_MESSAGE,
                    payload={
                        "message": turn.message,
                        "tool_call": None if turn.tool_call is None else asdict(turn.tool_call),
                        "final_response": turn.final_response,
                    },
                    trace_id=trace_id,
                    attempt_id=attempt_id,
                    external_effect_id=turn.external_effect_id,
                    usage=usage,
                )
                if turn.final_response is not None:
                    current = self.transcript.append_event(
                        session=current,
                        request_id=request_id,
                        turn_number=turn_number,
                        event_type=AgentTranscriptEventType.REQUEST_COMMITTED,
                        payload={"response": dict(turn.final_response)},
                        trace_id=trace_id,
                        attempt_id=attempt_id,
                        target_status=AgentHarnessStatus.COMPLETED,
                    )
                    return AgentHarnessResult(
                        session=current,
                        request_id=request_id,
                        response=dict(turn.final_response),
                        observations=tuple(observations),
                    )
                assert turn.tool_call is not None
                spec = self._authorize_tool(current, turn.tool_call)
                tool_usage = current.usage.add(tool_calls=1)
                tool_usage.require_within(current.budget)
                current = self.transcript.append_event(
                    session=current,
                    request_id=request_id,
                    turn_number=turn_number,
                    event_type=AgentTranscriptEventType.TOOL_REQUESTED,
                    payload={"tool": turn.tool_call.tool_name, "arguments": dict(turn.tool_call.arguments), "reason": turn.tool_call.reason},
                    trace_id=trace_id,
                    attempt_id=attempt_id,
                    target_status=AgentHarnessStatus.WAITING_TOOL,
                    usage=tool_usage,
                )
                observation = self.tools.invoke(
                    spec=spec,
                    call=turn.tool_call,
                    session=current,
                    request_id=request_id,
                    turn_number=turn_number,
                )
                if observation.operation_id and (
                    observation.operation_id != current.operation_id
                    or observation.attempt_id != attempt_id
                ):
                    raise KernelError(
                        "AGENT_HARNESS_TOOL_IDENTITY_DRIFT",
                        "Tool result is not owned by the leased Operation/Attempt",
                    )
                if spec.external_effect_required and not observation.external_effect_id:
                    raise KernelError(
                        "AGENT_HARNESS_TOOL_EFFECT_REQUIRED",
                        "external Tool lacks ExternalEffect evidence",
                    )
                observed_usage = current.usage.add(
                    external_effects=1 if observation.external_effect_id else 0
                )
                observed_usage.require_within(current.budget)
                event_type = (
                    AgentTranscriptEventType.AUTHORITY_COMMAND_SUBMITTED
                    if spec.kind is AgentToolKind.AUTHORITY_COMMAND
                    else AgentTranscriptEventType.TOOL_OBSERVED
                )
                current = self.transcript.append_event(
                    session=current,
                    request_id=request_id,
                    turn_number=turn_number,
                    event_type=event_type,
                    payload={
                        "tool": observation.tool_name,
                        "result": dict(observation.result),
                        "authority_command_id": observation.authority_command_id,
                        "candidate_only": spec.kind is not AgentToolKind.READ_ONLY_QUERY,
                    },
                    trace_id=trace_id,
                    attempt_id=attempt_id,
                    external_effect_id=observation.external_effect_id,
                    target_status=AgentHarnessStatus.RUNNING,
                    usage=observed_usage,
                )
                observations.append(observation)
            raise KernelError(
                "AGENT_HARNESS_TURN_LIMIT",
                "Agent request reached the hard turn limit without a final response",
            )
        except Exception as exc:
            if current.status is not AgentHarnessStatus.CANCELLED:
                current = self.transcript.append_event(
                    session=current,
                    request_id=request_id,
                    turn_number=current.usage.turns,
                    event_type=AgentTranscriptEventType.REQUEST_FAILED,
                    payload={
                        "error_code": getattr(exc, "code", type(exc).__name__),
                        "error_message": str(exc),
                    },
                    trace_id=trace_id,
                    attempt_id=attempt_id,
                    target_status=(
                        AgentHarnessStatus.ESCALATION_REQUIRED
                        if getattr(exc, "code", "") in {
                            "AGENT_HARNESS_BUDGET_EXHAUSTED",
                            "AGENT_HARNESS_TURN_LIMIT",
                        }
                        else AgentHarnessStatus.FAILED
                    ),
                )
            raise

    @staticmethod
    def _authorize_tool(
        session: AgentHarnessSession, call: AgentToolCall
    ) -> AgentToolSpec:
        matches = [tool for tool in session.tool_policy if tool.tool_name == call.tool_name]
        if len(matches) != 1:
            raise KernelError(
                "AGENT_HARNESS_TOOL_FORBIDDEN",
                f"Tool is not in the frozen allowlist: {call.tool_name}",
            )
        spec = matches[0]
        if session.role not in spec.allowed_roles:
            raise KernelError(
                "AGENT_HARNESS_TOOL_FORBIDDEN",
                f"Agent role cannot invoke Tool: {call.tool_name}",
            )
        return spec


def transcript_payload_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = [
    "AcceptedBoundaryRef",
    "AgentCancellationPort",
    "AgentHarnessBudget",
    "AgentHarnessResult",
    "AgentHarnessSession",
    "AgentHarnessStatus",
    "AgentHarnessTranscriptPort",
    "AgentHarnessUsage",
    "AgentModelTurn",
    "AgentModelTurnPort",
    "AgentToolCall",
    "AgentToolKind",
    "AgentToolObservation",
    "AgentToolRouter",
    "AgentToolSpec",
    "AgentTranscriptEventType",
    "AutonomousAgentRole",
    "UnifiedAgentHarness",
    "transcript_payload_hash",
]
