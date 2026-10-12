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
    SKILL_ACTIVATION_TOOL,
    UnifiedAgentHarness,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.agent_runtime.production import (
    _agent_turn_reservation_limits,
)


class _Transcript:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def append_event(
        self, *, session: AgentHarnessSession, **values: Any
    ) -> AgentHarnessSession:
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


class _Cancelled:
    def cancellation_requested(self, *, operation_id: str) -> bool:
        assert operation_id == "operation-1"
        return True


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
            SKILL_ACTIVATION_TOOL,
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


def test_model_skill_activation_is_explicit_frozen_and_permission_neutral() -> None:
    transcript = _Transcript()
    model = _Model(
        (
            AgentModelTurn(
                message="Activate the frozen planning Skill.",
                operation_id="operation-1",
                attempt_id="attempt-1",
                external_effect_id="effect-1",
                input_tokens=2,
                output_tokens=2,
                cost_amount="0",
                tool_call=AgentToolCall(
                    tool_name="skill.activate",
                    arguments={
                        "skill_id": "director-planning",
                        "skill_version": "1.0.0",
                        "skill_hash": "sha256:" + "a" * 64,
                    },
                    reason="apply the relevant frozen planning method",
                ),
            ),
            AgentModelTurn(
                message="Candidate ready.",
                operation_id="operation-1",
                attempt_id="attempt-1",
                external_effect_id="effect-2",
                input_tokens=2,
                output_tokens=2,
                cost_amount="0",
                final_response={"candidate_only": True},
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
        request_id="request-skill",
        instruction="Explore one direction.",
        attempt_id="attempt-1",
        trace_id="trace-1",
    )

    activation = next(
        event
        for event in transcript.events
        if event["event_type"] is AgentTranscriptEventType.SKILL_ACTIVATED
    )
    assert activation["payload"]["skill_id"] == "director-planning"
    assert activation["payload"]["skill_version"] == "1.0.0"
    assert activation["payload"]["skill_hash"] == "sha256:" + "a" * 64
    assert activation["payload"]["additional_tool_permissions"] == []
    assert activation["payload"]["additional_authority_permissions"] == []
    assert result.observations[0].tool_name == "skill.activate"


def test_explicit_caller_skill_selection_is_recorded_before_model_turn() -> None:
    transcript = _Transcript()
    model = _Model(
        (
            AgentModelTurn(
                message="Candidate ready.",
                operation_id="operation-1",
                attempt_id="attempt-1",
                external_effect_id="effect-1",
                input_tokens=2,
                output_tokens=2,
                cost_amount="0",
                final_response={"candidate_only": True},
            ),
        )
    )

    UnifiedAgentHarness(
        transcript=transcript,
        model=model,
        tools=_Tools(),
        cancellation=_Cancellation(),
    ).execute_request(
        session=_session(),
        request_id="request-explicit-skill",
        instruction="Use the specified planning Skill.",
        attempt_id="attempt-1",
        trace_id="trace-1",
        requested_skill_ids=("director-planning",),
    )

    assert [event["event_type"] for event in transcript.events[:2]] == [
        AgentTranscriptEventType.REQUEST_STARTED,
        AgentTranscriptEventType.SKILL_ACTIVATED,
    ]
    assert transcript.events[1]["payload"]["requested_by"] == "USER_OR_CALLER"


def test_skill_activation_outside_frozen_catalog_fails_closed() -> None:
    model = _Model(
        (
            AgentModelTurn(
                message="Activate an unbound Skill.",
                operation_id="operation-1",
                attempt_id="attempt-1",
                external_effect_id="effect-1",
                input_tokens=1,
                output_tokens=1,
                cost_amount="0",
                tool_call=AgentToolCall(
                    tool_name="skill.activate",
                    arguments={"skill_id": "unfrozen-skill"},
                    reason="try to expand permissions",
                ),
            ),
        )
    )
    with pytest.raises(KernelError) as raised:
        UnifiedAgentHarness(
            transcript=_Transcript(),
            model=model,
            tools=_Tools(),
            cancellation=_Cancellation(),
        ).execute_request(
            session=_session(max_turns=1),
            request_id="request-unfrozen-skill",
            instruction="Do not escape governance.",
            attempt_id="attempt-1",
            trace_id="trace-1",
        )
    assert raised.value.code == "AGENT_HARNESS_SKILL_NOT_IN_FROZEN_CATALOG"


def test_agent_turn_reserves_only_remaining_aggregate_budget() -> None:
    session = replace(
        _session(),
        usage=AgentHarnessUsage(
            turns=1,
            tool_calls=1,
            external_effects=1,
            input_tokens=40,
            output_tokens=5,
            cost_amount="0.2",
        ),
    )

    amount, tokens = _agent_turn_reservation_limits(
        session=session,
        provider_call_cap="1.0",
    )

    assert amount == "0.8"
    assert tokens == 100


def test_agent_turn_history_does_not_exhaust_new_model_input_capacity() -> None:
    session = replace(_session(), usage=AgentHarnessUsage(input_tokens=1000))
    amount, tokens = _agent_turn_reservation_limits(session=session, provider_call_cap="1.0")
    assert tokens == 100
    assert amount == "1.0"


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
    assert (
        transcript.events[-1]["event_type"] is AgentTranscriptEventType.REQUEST_FAILED
    )
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


def test_harness_cancellation_stops_before_the_next_model_effect() -> None:
    transcript = _Transcript()
    model = _Model(())
    with pytest.raises(KernelError, match="cancelled") as caught:
        UnifiedAgentHarness(
            transcript=transcript,
            model=model,
            tools=_Tools(),
            cancellation=_Cancelled(),
        ).execute_request(
            session=_session(),
            request_id="request-cancelled",
            instruction="Stop safely.",
            attempt_id="attempt-1",
            trace_id="trace-1",
        )
    assert caught.value.code == "AGENT_HARNESS_CANCELLED"
    assert [event["event_type"] for event in transcript.events] == [
        AgentTranscriptEventType.REQUEST_STARTED,
        AgentTranscriptEventType.SESSION_STOPPED,
    ]


def test_native_pure_generation_session_ignores_historical_consumption_limits():
    from novel_forge.modules.agent_runtime.policy import SERVER_AGENT_TOOL_CATALOG
    session = replace(_session(max_turns=1), tool_policy=(SERVER_AGENT_TOOL_CATALOG['narrative.query_accepted'], SKILL_ACTIVATION_TOOL),
        usage=AgentHarnessUsage(turns=10, tool_calls=10, external_effects=20, input_tokens=1000, output_tokens=1000))
    model = _Model((AgentModelTurn(message='query', operation_id='operation-1', attempt_id='attempt-1', external_effect_id='effect-1',
        input_tokens=200, output_tokens=200, cost_amount='0', tool_call=AgentToolCall('narrative.query_accepted', {}, 'ground source')),
        AgentModelTurn(message='done', operation_id='operation-1', attempt_id='attempt-1', external_effect_id='effect-2',
            input_tokens=200, output_tokens=200, cost_amount='0', final_response={'candidate_only':True})))
    result = UnifiedAgentHarness(transcript=_Transcript(), model=model, tools=_Tools(), cancellation=_Cancellation()).execute_request(
        session=session, request_id='generation-request', instruction='use actual facts', attempt_id='attempt-1', trace_id='trace-1')
    assert result.session.status is AgentHarnessStatus.COMPLETED
    assert result.session.usage.turns == 12
    assert result.session.usage.input_tokens == 1400


def test_native_generation_repeated_observations_fail_without_lifetime_quota():
    from novel_forge.modules.agent_runtime.policy import SERVER_AGENT_TOOL_CATALOG
    session = replace(_session(max_turns=1), tool_policy=(SERVER_AGENT_TOOL_CATALOG['narrative.query_accepted'], SKILL_ACTIVATION_TOOL))
    turn = AgentModelTurn(message='same query', operation_id='operation-1', attempt_id='attempt-1', external_effect_id='effect-1',
        input_tokens=1, output_tokens=1, cost_amount='0', tool_call=AgentToolCall('narrative.query_accepted', {}, 'ground source'))
    transcript = _Transcript()
    with pytest.raises(KernelError, match='AGENT_HARNESS_NO_PROGRESS'):
        UnifiedAgentHarness(transcript=transcript, model=_Model((turn, turn, turn)), tools=_Tools(), cancellation=_Cancellation()).execute_request(
            session=session, request_id='same-request', instruction='use actual facts', attempt_id='attempt-1', trace_id='trace-1')
    assert transcript.events[-1]['event_type'] is AgentTranscriptEventType.REQUEST_FAILED
