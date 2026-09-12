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
    CodexAccountEntitlementSnapshot,
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


def _entitlement() -> CodexAccountEntitlementSnapshot:
    return CodexAccountEntitlementSnapshot(
        authorization_ref="task-authorization:classical-corpus-20260908",
        account_identity_ref="chatgpt-login:local-account",
        cli_version="codex-cli 0.153.4",
        executable_sha256="sha256:" + "c" * 64,
        configuration_ref="codex-config:ignored-user-config:ephemeral",
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


def test_codex_jsonl_account_entitlement_keeps_measured_usage_and_unknown_cost() -> (
    None
):
    evidence = parse_codex_jsonl_evidence(
        json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 21,
                    "cached_input_tokens": 5,
                    "output_tokens": 8,
                    "reasoning_output_tokens": 3,
                },
            }
        ),
        model_id="codex-test",
        account_entitlement=_entitlement(),
        allowed_tools=("model.provider.invoke",),
    )

    assert evidence["usage"]["measurement"] == "MEASURED"
    assert evidence["usage"]["total_tokens"] == 29
    assert evidence["cost"] == {
        "availability": "UNAVAILABLE",
        "measurement": "UNKNOWN",
        "model": "codex-test",
        "currency": "UNKNOWN",
        "accounting_basis": "ACCOUNT_ENTITLEMENT",
        "reason": "monetary_cost_not_observable",
        "authorization_ref": "task-authorization:classical-corpus-20260908",
        "entitlement_snapshot_hash": _entitlement().snapshot_hash,
        "entitlement_snapshot": _entitlement().to_dict(),
        "provider_billed": "UNKNOWN",
    }


def test_real_codex_backend_accepts_one_account_entitlement_without_pricing() -> None:
    _capability, profile, policy, route, manifest, request = contracts(
        backend_id="codex-cli",
        runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
    )
    admission = AdmissionController(
        StaticExecutionContractSource(
            route_snapshots=(route,),
            model_profiles=(profile,),
            route_policies=(policy,),
            input_manifests=(manifest,),
        ),
        StaticAttemptFenceVerifier({("operation:1", "attempt:1"): 7}),
    )
    with tempfile.TemporaryDirectory() as tmp:
        backend = CodexCliExecutionBackend(
            admission=admission,
            payload_resolver=StaticExecutionPayloadResolver({}),
            record_store=InMemoryExecutionRecordStore(),
            supervisor=CodexProcessSupervisor(
                PersistentExecutionDirectory(Path(tmp) / "executions")
            ),
            execution_policy=LocalProcessExecutionPolicy(
                fixed_working_directory=tmp,
                allowed_command_prefixes=((sys.executable, "exec"),),
                maximum_result_bytes=1_000_000,
            ),
            codex_executable=sys.executable,
            codex_home=tmp,
            account_entitlement=_entitlement(),
            structured_result_validator=lambda _stage, _schema, value: value,
        )

    assert backend.capability_profile.supports_usage_receipt is True
    assert backend.capability_profile.supports_cost_receipt is True


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
    from novel_forge.modules.chapter_authority.provider_output_contracts import validate_chapter_provider_output_against_schema
    from novel_forge.modules.command_kernel.errors import KernelError

    canonical_schema = {"type": "object", "properties": {
        "caused_by": {"type": "array", "items": {"type": "string"}, "uniqueItems": True}
    }}
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
            output_schema=canonical_schema,
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
            codex_home=tmp,
            pricing=_pricing(),
            structured_result_validator=lambda _stage, _schema, value: value,
        )
        frozen = admission.admit(request, backend.capability_profile)
        prepared = backend._prepare_payload(request, payload, frozen)
        projected = json.loads(Path(prepared.command[prepared.command.index("--output-schema") + 1]).read_text())
        assert "uniqueItems" not in projected["properties"]["caused_by"]
        assert canonical_schema["properties"]["caused_by"]["uniqueItems"] is True
        with pytest.raises(KernelError, match="SCHEMA_INVALID"):
            validate_chapter_provider_output_against_schema("draft", canonical_schema, {"caused_by": ["a", "a"]})
        evidence = backend._model_authority_evidence(
            frozen,
            prepared.command,
            require_codex_invocation=True,
        )

    assert prepared.command[prepared.command.index("--model") + 1] == route.model_id
    assert f"model_reasoning_effort={route.reasoning_effort}" in prepared.command
    assert "--ignore-user-config" in prepared.command
    assert prepared.environment_overrides["CODEX_HOME"] == str(Path(tmp).resolve())
    from novel_forge.modules.production_execution.codex_configuration import (
        CODEX_INPUT_ONLY_OVERRIDES,
    )

    assert set(CODEX_INPUT_ONLY_OVERRIDES) <= set(prepared.command)
    assert 'web_search="disabled"' in prepared.command
    assert "features.view_image=false" in prepared.command
    assert "features.shell_tool=false" in prepared.command
    assert "features.skip_host_skill_discovery=true" in prepared.command
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


@pytest.mark.parametrize("accounting_basis", ["PRICED", "ACCOUNT_ENTITLEMENT"])
def test_codex_backend_validates_schema_and_semantics_before_success(
    accounting_basis: str,
) -> None:
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
            pricing=_pricing() if accounting_basis == "PRICED" else None,
            account_entitlement=(
                _entitlement() if accounting_basis == "ACCOUNT_ENTITLEMENT" else None
            ),
            structured_result_validator=validator,
        )

        result = backend.reconcile(backend.submit(request))

    assert result.outcome is ExecutionOutcome.SUCCEEDED
    evidence = store.get_record(request.execution_id).raw_evidence
    assert evidence["result"] == {"text": "Validated chapter.", "scene_artifacts": []}
    assert evidence["usage"]["measurement"] == "MEASURED"
    if accounting_basis == "ACCOUNT_ENTITLEMENT":
        assert evidence["cost"]["availability"] == "UNAVAILABLE"
        assert evidence["cost"]["currency"] == "UNKNOWN"
        assert "amount" not in evidence["cost"]
    else:
        assert evidence["cost"]["availability"] == "AVAILABLE"
    assert set(evidence["validation_checks"]) == {
        "output_schema",
        "stage_semantics",
        "capability_materialization",
        "tool_policy",
    }


@pytest.mark.parametrize(
    "bad_output,expected_failure",
    [
        ('{"unexpected":true}', "OUTPUT_SCHEMA_FAILURE"),
        ("not valid JSON", "INVALID_JSON"),
    ],
)
def test_codex_backend_schema_failure_is_not_a_success_receipt(
    bad_output, expected_failure
) -> None:
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
            "import sys; open(sys.argv[1],'w').write(sys.argv[2]); print(sys.argv[3])",
            str(result_path),
            bad_output,
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 10,
                        "cached_input_tokens": 0,
                        "output_tokens": 4,
                    },
                }
            ),
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
                        allowed_tools=("model.provider.invoke",),
                        output_schema=chapter_provider_output_schema("draft"),
                        capability_evidence={
                            "fully_rendered_prompt_hash": "sha256:"
                            + hashlib.sha256(b"prompt").hexdigest(),
                            "materialization_hash": "sha256:" + "a" * 64,
                        },
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
            account_entitlement=_entitlement(),
            structured_result_validator=lambda stage, schema, value: (
                validate_chapter_provider_output_schema(stage, value)
            ),
        )

        result = backend.reconcile(backend.submit(request))

    assert result.outcome is ExecutionOutcome.RETRYABLE_FAILURE, store.get_record(
        request.execution_id
    ).raw_evidence.get("failure_code")
    assert (
        store.get_record(request.execution_id).raw_evidence["failure_code"]
        == expected_failure
    )
    assert result.usage_receipt_ref
    assert store.read_evidence(result.usage_receipt_ref)["total_tokens"] == 14
    assert result.output_manifest_ref is None
    assert result.raw_output_ref is not None
    diagnostic = store.read_evidence(result.raw_output_ref)
    assert diagnostic["result_sha256"].startswith("sha256:")
    assert diagnostic["input_sha256"]
    assert "unexpected" not in json.dumps(diagnostic)
    from types import SimpleNamespace
    from novel_forge.modules.source_import.execution import (
        _source_gateway_provider_result,
    )

    external = _source_gateway_provider_result(
        binding=SimpleNamespace(
            request=request, route_snapshot=route, input_manifest=manifest
        ),
        session=SimpleNamespace(evidence_store=store),
        handle=store.get_record(request.execution_id).handle,
        result=result,
    )
    assert external.outcome == "success"
    assert (
        external.evidence["output_validation_error"]
        == "SOURCE_OUTPUT_" + expected_failure
    )
    assert external.evidence["usage"]["total_tokens"] == 14
    assert external.evidence["result"] == {
        "_rejected_provider_output": result.raw_output_ref
    }


def test_local_codex_preflight_rejects_path_fallback_and_missing_account(
    tmp_path, monkeypatch
):
    from novel_forge.modules.production_execution.codex_configuration import (
        inspect_local_codex,
    )

    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    report = inspect_local_codex({"NOVEL_FORGE_CODEX_EXECUTABLE": "codex"})
    assert report["blockers"] == [
        "CODEX_LOCAL_PROCESS_UNAVAILABLE",
        "CODEX_HOME_NOT_EXPLICIT",
        "CODEX_EXECUTION_ROOT_NOT_ABSOLUTE",
    ]
    assert report["model_calls"] == 0
    assert report["credentials_inspected"] is False
    assert report["fallback"] == "FORBIDDEN"


def test_local_codex_preflight_observes_process_and_reports_drift_without_authorizing(
    tmp_path,
):
    from novel_forge.modules.production_execution.codex_configuration import (
        inspect_local_codex,
    )

    values = {
        "NOVEL_FORGE_CODEX_EXECUTABLE": sys.executable,
        "NOVEL_FORGE_CODEX_WORKSPACE": str(tmp_path),
        "NOVEL_FORGE_CODEX_HOME": str(tmp_path),
        "NOVEL_FORGE_CODEX_EXECUTION_ROOT": str(tmp_path / "executions"),
        "NOVEL_FORGE_CODEX_CLI_VERSION": "different-version",
        "NOVEL_FORGE_CODEX_EXECUTABLE_SHA256": "sha256:" + "0" * 64,
        "NOVEL_FORGE_CODEX_ACCOUNT_AUTHORIZATION_REF": "declared-not-verified",
    }
    report = inspect_local_codex(values)
    assert report["blockers"] == [
        "CODEX_CLI_VERSION_DRIFT",
        "CODEX_EXECUTABLE_SHA256_DRIFT",
    ]
    assert report["identity"]["codex_home"] == str(tmp_path.resolve())
    assert report["authorization"] == "REQUIRES_EXTERNAL_USER_GRANT_VERIFICATION"
    assert report["remote_availability"] == "NOT_TESTED"
    assert "NOVEL_FORGE_QUALITY_MODEL" in report["missing_configuration"]
    assert report["model_calls"] == 0


def test_codex_protocol_schema_rejection_is_distinct_from_transient_failure():
    from novel_forge.modules.production_execution.backends import codex_protocol_failure

    rejected = {"type": "error", "message": json.dumps({"status": 400,
        "error": {"code": "invalid_json_schema", "message": "uniqueItems is not permitted"}})}
    assert codex_protocol_failure(json.dumps(rejected)) == "PROVIDER_SCHEMA_REJECTED"
    for value in ("[]", "not json", json.dumps({"type": "error", "message": "timeout"}),
        json.dumps({"type": "error", "message": json.dumps({"status": 429, "error": {"code": "rate_limit"}})})):
        assert codex_protocol_failure(value) is None
