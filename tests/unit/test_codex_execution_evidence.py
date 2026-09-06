from __future__ import annotations

import hashlib
import inspect
import json
import sys
import tempfile
from pathlib import Path

import pytest

from novel_forge.modules.chapter_authority.execution_gateway import (
    _provider_process_timeout_seconds,
)
from novel_forge.modules.chapter_authority.model_effects import normalize_model_output
from novel_forge.modules.chapter_authority.provider_output_contracts import (
    chapter_provider_output_schema,
    validate_chapter_provider_output_schema,
)
from novel_forge.modules.production_execution import ExecutionOutcome
from novel_forge.modules.production_execution.backends import (
    CodexCliExecutionBackend,
    CodexPricingSnapshot,
    InMemoryExecutionRecordStore,
    LocalProcessExecutionPolicy,
    ResolvedExecutionPayload,
    StaticExecutionPayloadResolver,
    parse_codex_jsonl_evidence,
)
from novel_forge.modules.production_execution.gateway import (
    AdmissionController,
    StaticAttemptFenceVerifier,
    StaticExecutionContractSource,
)
from novel_forge.modules.production_execution.process_supervisor import (
    CodexProcessSupervisor,
    PersistentExecutionDirectory,
)
from tests.unit.test_production_execution_gateway import contracts
from novel_forge.modules.production_execution import ExecutionRuntimeClass


def _pricing() -> CodexPricingSnapshot:
    return CodexPricingSnapshot(
        model_id="codex-test",
        pricing_ref="pricing:codex-test:2026-08-08",
        currency="USD",
        input_per_million="10",
        cached_input_per_million="1",
        output_per_million="30",
    )


def test_codex_jsonl_produces_measured_usage_and_estimated_cost() -> None:
    evidence = parse_codex_jsonl_evidence(
        "\n".join(
            (
                json.dumps({"type": "thread.started", "thread_id": "thread-1"}),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {
                            "input_tokens": 1000,
                            "cached_input_tokens": 400,
                            "output_tokens": 500,
                            "reasoning_output_tokens": 200,
                        },
                    }
                ),
            )
        ),
        model_id="codex-test",
        pricing=_pricing(),
        allowed_tools=("model.provider.invoke",),
        denied_tools=("storage.object.put",),
    )

    assert evidence["usage"]["measurement"] == "MEASURED"
    assert evidence["usage"]["total_tokens"] == 1500
    assert evidence["cost"]["amount"] == "0.0214"
    assert evidence["cost"]["estimated"] is True
    assert evidence["cost"]["provider_billed"] is False
    assert evidence["cost"]["pricing_snapshot_hash"].startswith("sha256:")
    assert evidence["tools"] == {
        "policy": "DEFAULT_DENY",
        "allowed": ["model.provider.invoke"],
        "denied": ["storage.object.put"],
        "invoked": ["model.provider.invoke"],
        "invocations": [
            {
                "tool_ref": "model.provider.invoke",
                "event": "provider_execution",
                "call_id": "",
                "status": "completed",
            }
        ],
    }


def test_codex_jsonl_records_and_denies_observed_cli_tools() -> None:
    evidence = parse_codex_jsonl_evidence(
        "\n".join(
            (
                json.dumps(
                    {
                        "type": "item.started",
                        "item": {
                            "id": "item-1",
                            "type": "command_execution",
                            "status": "in_progress",
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {
                            "input_tokens": 1,
                            "cached_input_tokens": 0,
                            "output_tokens": 1,
                            "reasoning_output_tokens": 0,
                        },
                    }
                ),
            )
        ),
        model_id="codex-test",
        pricing=_pricing(),
        allowed_tools=("model.provider.invoke",),
    )

    assert evidence["tools"]["invoked"] == [
        "codex.command_execution",
        "model.provider.invoke",
    ]
    assert evidence["unauthorized_tools"] == ["codex.command_execution"]


def test_codex_jsonl_requires_terminal_measured_usage() -> None:
    with pytest.raises(ValueError, match="terminal measured usage"):
        parse_codex_jsonl_evidence(
            json.dumps({"type": "thread.started"}),
            model_id="codex-test",
            pricing=_pricing(),
            allowed_tools=("model.provider.invoke",),
        )


def test_codex_invocation_is_derived_from_frozen_route_not_backend_defaults() -> None:
    _capability, profile, policy, route, manifest, request = contracts(
        backend_id="codex-cli",
        runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
    )
    source = StaticExecutionContractSource(
        route_snapshots=(route,),
        model_profiles=(profile,),
        route_policies=(policy,),
        input_manifests=(manifest,),
    )
    admission = AdmissionController(
        source,
        StaticAttemptFenceVerifier({("operation:1", "attempt:1"): 7}),
    )
    assert "model_id" not in inspect.signature(CodexCliExecutionBackend).parameters
    assert (
        "reasoning_effort" not in inspect.signature(CodexCliExecutionBackend).parameters
    )

    with tempfile.TemporaryDirectory() as tmp:
        directory = PersistentExecutionDirectory(Path(tmp) / "executions")
        payload = ResolvedExecutionPayload(
            request_payload={"stage": "draft"},
            input_text="frozen prompt",
            working_directory=tmp,
            timeout_seconds=5,
            output_schema_version="schema:test:v1",
            output_schema={"type": "object"},
        )
        backend = CodexCliExecutionBackend(
            admission=admission,
            payload_resolver=StaticExecutionPayloadResolver(
                {request.execution_id: payload}
            ),
            record_store=InMemoryExecutionRecordStore(),
            supervisor=CodexProcessSupervisor(directory),
            execution_policy=LocalProcessExecutionPolicy(
                fixed_working_directory=tmp,
                allowed_command_prefixes=((sys.executable, "exec"),),
                maximum_result_bytes=1_000_000,
            ),
            codex_executable=sys.executable,
            pricing=_pricing(),
            structured_result_validator=lambda _stage, _schema, value: value,
        )
        frozen = admission.admit(request, backend.capability_profile)
        prepared = backend._prepare_payload(request, payload, frozen)
        evidence = backend._model_authority_evidence(
            frozen,
            prepared.command,
            require_codex_invocation=True,
        )

    assert prepared.command[prepared.command.index("--model") + 1] == route.model_id
    assert f"model_reasoning_effort={route.reasoning_effort}" in prepared.command
    assert "--ignore-user-config" in prepared.command
    assert evidence["policy_requested_model"] == profile.model_id
    assert evidence["frozen_route_model"] == route.model_id
    assert evidence["invocation_model"] == route.model_id
    assert evidence["provider_observed_model"] == "unavailable"
    assert evidence["policy_requested_reasoning_effort"] == profile.reasoning_effort
    assert evidence["frozen_route_reasoning_effort"] == route.reasoning_effort
    assert evidence["invocation_reasoning_effort"] == route.reasoning_effort
    assert evidence["provider_observed_reasoning_effort"] == "unavailable"
    assert evidence["model_profile_hash"] == profile.contract_hash
    assert evidence["route_policy_hash"] == policy.contract_hash
    assert evidence["local_user_config_ignored"] is True
    assert evidence["local_user_config_is_model_authority"] is False


def test_provider_process_timeout_preserves_external_effect_settlement_headroom() -> (
    None
):
    assert _provider_process_timeout_seconds(300) == 270
    assert _provider_process_timeout_seconds(30) == 27
    assert _provider_process_timeout_seconds(2) == 1
    assert _provider_process_timeout_seconds(1_800, max_attempts=3) == 570


def test_codex_backend_validates_schema_and_semantics_before_success() -> None:
    contract_set = contracts(
        backend_id="codex-cli",
        runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
    )
    _capability, profile, policy, route, manifest, request = contract_set
    source = StaticExecutionContractSource(
        route_snapshots=(route,),
        model_profiles=(profile,),
        route_policies=(policy,),
        input_manifests=(manifest,),
    )
    admission = AdmissionController(
        source,
        StaticAttemptFenceVerifier({("operation:1", "attempt:1"): 7}),
    )

    def validator(stage, schema, value):  # type: ignore[no-untyped-def]
        validate_chapter_provider_output_schema(stage, value)
        return normalize_model_output(stage, dict(value))

    with tempfile.TemporaryDirectory() as tmp:
        execution_directory = PersistentExecutionDirectory(Path(tmp) / "executions")
        result_path = execution_directory.prepare(request.execution_id).result_path(
            "result.json"
        )
        stdout_event = json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 10,
                    "cached_input_tokens": 2,
                    "output_tokens": 4,
                    "reasoning_output_tokens": 1,
                },
            }
        )
        input_text = "fully materialized prompt"
        prompt_hash = "sha256:" + hashlib.sha256(input_text.encode()).hexdigest()
        command = (
            sys.executable,
            "-c",
            (
                "import json,sys; "
                "json.dump({'text':'Validated chapter.','scene_artifacts':[]},open(sys.argv[1],'w')); "
                "print(sys.argv[2])"
            ),
            str(result_path),
            stdout_event,
        )
        store = InMemoryExecutionRecordStore()
        backend = CodexCliExecutionBackend(
            admission=admission,
            payload_resolver=StaticExecutionPayloadResolver(
                {
                    request.execution_id: ResolvedExecutionPayload(
                        request_payload={"stage": "draft"},
                        input_text=input_text,
                        working_directory=tmp,
                        timeout_seconds=5,
                        output_schema_version="schema:chapter-provider-output:draft:v2",
                        command=command,
                        output_schema=chapter_provider_output_schema("draft"),
                        capability_evidence={
                            "fully_rendered_prompt_hash": prompt_hash,
                            "materialization_hash": "sha256:" + "a" * 64,
                        },
                        allowed_tools=("model.provider.invoke",),
                    )
                }
            ),
            record_store=store,
            supervisor=CodexProcessSupervisor(execution_directory),
            execution_policy=LocalProcessExecutionPolicy(
                fixed_working_directory=tmp,
                allowed_command_prefixes=((sys.executable,),),
                maximum_result_bytes=1_000_000,
            ),
            pricing=_pricing(),
            structured_result_validator=validator,
        )

        result = backend.reconcile(backend.submit(request))

    assert result.outcome is ExecutionOutcome.SUCCEEDED
    evidence = store.get_record(request.execution_id).raw_evidence
    assert evidence["result"] == {"text": "Validated chapter.", "scene_artifacts": []}
    assert evidence["usage"]["measurement"] == "MEASURED"
    assert set(evidence["validation_checks"]) == {
        "output_schema",
        "stage_semantics",
        "capability_materialization",
        "tool_policy",
    }


def test_codex_backend_schema_failure_is_not_a_success_receipt() -> None:
    contract_set = contracts(
        backend_id="codex-cli",
        runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
    )
    _capability, profile, policy, route, manifest, request = contract_set
    source = StaticExecutionContractSource(
        route_snapshots=(route,),
        model_profiles=(profile,),
        route_policies=(policy,),
        input_manifests=(manifest,),
    )
    admission = AdmissionController(
        source,
        StaticAttemptFenceVerifier({("operation:1", "attempt:1"): 7}),
    )
    with tempfile.TemporaryDirectory() as tmp:
        directory = PersistentExecutionDirectory(Path(tmp) / "executions")
        result_path = directory.prepare(request.execution_id).result_path("result.json")
        command = (
            sys.executable,
            "-c",
            "import json,sys; json.dump({'unexpected':True},open(sys.argv[1],'w'))",
            str(result_path),
        )
        store = InMemoryExecutionRecordStore()
        backend = CodexCliExecutionBackend(
            admission=admission,
            payload_resolver=StaticExecutionPayloadResolver(
                {
                    request.execution_id: ResolvedExecutionPayload(
                        request_payload={"stage": "draft"},
                        input_text="prompt",
                        working_directory=tmp,
                        timeout_seconds=5,
                        output_schema_version="schema:chapter-provider-output:draft:v2",
                        command=command,
                        output_schema=chapter_provider_output_schema("draft"),
                    )
                }
            ),
            record_store=store,
            supervisor=CodexProcessSupervisor(directory),
            execution_policy=LocalProcessExecutionPolicy(
                fixed_working_directory=tmp,
                allowed_command_prefixes=((sys.executable,),),
                maximum_result_bytes=1_000_000,
            ),
            structured_result_validator=lambda stage, schema, value: (
                validate_chapter_provider_output_schema(stage, value)
            ),
        )

        result = backend.reconcile(backend.submit(request))

    assert result.outcome is ExecutionOutcome.RETRYABLE_FAILURE
    assert (
        store.get_record(request.execution_id).raw_evidence["failure_code"]
        == "OUTPUT_SCHEMA_FAILURE"
    )
    assert result.output_manifest_ref is None
