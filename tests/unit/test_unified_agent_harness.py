from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Sequence

import pytest

from novel_forge.modules.agent_runtime.harness import (
    AcceptedBoundaryRef,
    AgentHarnessBudget,
    AgentHarnessSession,
    AgentHarnessStatus,
    AgentHarnessUsage,
    AgentModelTurn,
    AgentToolCall,
    AgentToolKind,
    AgentToolObservation,
    AgentToolSpec,
    AgentTranscriptEventType,
    AutonomousAgentRole,
    UnifiedAgentHarness,
)
from novel_forge.modules.command_kernel.errors import KernelError


class _Transcript:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def append_event(self, *, session: AgentHarnessSession, **values: Any) -> AgentHarnessSession:
        self.events.append({"request_id": values["request_id"], **values})
        return replace(
            session,
            status=values.get("target_status") or session.status,
            usage=values.get("usage") or session.usage,
            next_sequence=session.next_sequence + 1,
            version=session.version + 1,
        )

    def committed_request_events(
        self, *, agent_session_id: str
    ) -> tuple[Mapping[str, Any], ...]:
        del agent_session_id
        committed = {
            event["request_id"]
            for event in self.events
            if event["event_type"] is AgentTranscriptEventType.REQUEST_COMMITTED
        }
        failed = {
            event["request_id"]
            for event in self.events
            if event["event_type"] is AgentTranscriptEventType.REQUEST_FAILED
        }
        return tuple(
            event
            for event in self.events
            if event["request_id"] in committed and event["request_id"] not in failed
        )


class _Model:
    external_effect_backed = True

    def __init__(self, turns: Sequence[AgentModelTurn]) -> None:
        self.turns = list(turns)

    def next_turn(self, **_: Any) -> AgentModelTurn:
        return self.turns.pop(0)


class _Tools:
    def invoke(self, **values: Any) -> AgentToolObservation:
        spec = values["spec"]
        session = values["session"]
        return AgentToolObservation(
            tool_name=spec.tool_name,
            result={"facts": ["accepted-only"], "candidate_only": True},
            operation_id=session.operation_id,
            attempt_id="attempt-1",
        )


class _Cancellation:
    def cancellation_requested(self, *, operation_id: str) -> bool:
        del operation_id
        return False


def _session(*, max_turns: int = 3) -> AgentHarnessSession:
    return AgentHarnessSession(
        agent_session_id="session-1",
        project_id="project-1",
        workspace_id="workspace-1",
        operation_id="operation-1",
        role=AutonomousAgentRole.STUDIO_DIRECTOR,
        status=AgentHarnessStatus.READY,
        accepted_boundary=AcceptedBoundaryRef(
            book_id="book-1",
            book_run_id="book-run-1",
            accepted_through_chapter=4,
            acceptance_id="acceptance-4",
            projection_set_id="projection-4",
        ),
        tool_policy=(
            AgentToolSpec(
                tool_name="narrative.query_accepted",
                kind=AgentToolKind.READ_ONLY_QUERY,
                input_schema_ref="schema:query:v1",
                output_schema_ref="schema:result:v1",
                allowed_roles=(AutonomousAgentRole.STUDIO_DIRECTOR,),
            ),
        ),
        skill_bindings=(
            {
                "skill_id": "director-planning",
                "skill_version": "1.0.0",
                "skill_hash": "sha256:" + "a" * 64,
            },
        ),
        budget=AgentHarnessBudget(
            max_turns=max_turns,
            max_tool_calls=2,
            max_external_effects=3,
            max_input_tokens=100,
            max_output_tokens=100,
            max_cost_amount="1.0",
        ),
    )


def test_harness_observes_dynamic_tool_then_commits_final_response() -> None:
    transcript = _Transcript()
    model = _Model(
        (
            AgentModelTurn(
                message="I need accepted facts.",
                operation_id="operation-1",
                attempt_id="attempt-1",
                external_effect_id="effect-1",
                input_tokens=10,
                output_tokens=5,
                cost_amount="0.1",
                tool_call=AgentToolCall(
                    tool_name="narrative.query_accepted",
                    arguments={"entity_id": "character-1"},
                    reason="ground the proposal",
                ),
            ),
            AgentModelTurn(
                message="Here is the proposal.",
                operation_id="operation-1",
                attempt_id="attempt-1",
                external_effect_id="effect-2",
                input_tokens=12,
                output_tokens=8,
                cost_amount="0.1",
                final_response={"proposal": {"candidate_only": True}},
            ),
        )
    )
    result = UnifiedAgentHarness(
        transcript=transcript,
        model=model,
        tools=_Tools(),
        cancellation=_Cancellation(),
    ).execute_request(
        session=_session(),
        request_id="request-1",
        instruction="Propose the next Book direction.",
        attempt_id="attempt-1",
        trace_id="trace-1",
    )

    assert result.session.status is AgentHarnessStatus.COMPLETED
    assert result.response["proposal"]["candidate_only"] is True
    assert result.session.usage == AgentHarnessUsage(
        turns=2,
        tool_calls=1,
        external_effects=2,
        input_tokens=22,
        output_tokens=13,
        cost_amount="0.2",
    )
    assert [event["event_type"] for event in transcript.events] == [
        AgentTranscriptEventType.REQUEST_STARTED,
        AgentTranscriptEventType.MODEL_MESSAGE,
        AgentTranscriptEventType.TOOL_REQUESTED,
        AgentTranscriptEventType.TOOL_OBSERVED,
        AgentTranscriptEventType.MODEL_MESSAGE,
        AgentTranscriptEventType.REQUEST_COMMITTED,
    ]


def test_harness_turn_budget_fails_closed_without_committing_request() -> None:
    transcript = _Transcript()
    model = _Model(
        (
            AgentModelTurn(
                message="Need a query.",
                operation_id="operation-1",
                attempt_id="attempt-1",
                external_effect_id="effect-1",
                input_tokens=1,
                output_tokens=1,
                cost_amount="0",
                tool_call=AgentToolCall(
                    tool_name="narrative.query_accepted", arguments={}, reason="query"
                ),
            ),
        )
    )
    with pytest.raises(KernelError, match="hard turn limit"):
        UnifiedAgentHarness(
            transcript=transcript,
            model=model,
            tools=_Tools(),
            cancellation=_Cancellation(),
        ).execute_request(
            session=_session(max_turns=1),
            request_id="request-failed",
            instruction="Keep thinking forever.",
            attempt_id="attempt-1",
            trace_id="trace-1",
        )
    assert transcript.events[-1]["event_type"] is AgentTranscriptEventType.REQUEST_FAILED
    assert not any(
        event["event_type"] is AgentTranscriptEventType.REQUEST_COMMITTED
        for event in transcript.events
    )


def test_agent_tool_contract_rejects_direct_truth_mutation() -> None:
    with pytest.raises(ValueError, match="direct Authority mutation"):
        AgentToolSpec(
            tool_name="chapter.accept",
            kind=AgentToolKind.AUTHORITY_COMMAND,
            input_schema_ref="schema:accept:v1",
            output_schema_ref="schema:accept-result:v1",
            allowed_roles=(AutonomousAgentRole.STUDIO_DIRECTOR,),
            authority_command_type="chapter.propose_acceptance",
        )


def test_harness_rejects_model_evidence_from_another_attempt() -> None:
    model = _Model(
        (
            AgentModelTurn(
                message="wrong attempt",
                operation_id="operation-1",
                attempt_id="attempt-other",
                external_effect_id="effect-1",
                input_tokens=1,
                output_tokens=1,
                cost_amount="0",
                final_response={"proposal": {}},
            ),
        )
    )
    with pytest.raises(KernelError, match="not owned"):
        UnifiedAgentHarness(
            transcript=_Transcript(),
            model=model,
            tools=_Tools(),
            cancellation=_Cancellation(),
        ).execute_request(
            session=_session(),
            request_id="request-identity",
            instruction="Propose.",
            attempt_id="attempt-1",
            trace_id="trace-1",
        )
