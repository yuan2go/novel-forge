from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from novel_forge.modules.agent_runtime import execution as execution_module
from novel_forge.modules.agent_runtime.execution import (
    ChapterGatewayAgentExecutionPreparer,
)
from novel_forge.modules.chapter_authority.contracts import ChapterInputAsset
from novel_forge.modules.command_kernel.errors import KernelError


def test_agent_preparer_rejects_before_external_effect_creation(monkeypatch) -> None:
    calls: list[str] = []

    class RejectingBinder:
        def freeze_before_external_effect(self, **_kwargs):
            calls.append("admission")
            raise KernelError(
                "PROVIDER_TOKEN_ADMISSION_REJECTED", "complete request is too large"
            )

        def bind(self, **_kwargs):  # pragma: no cover - an ordering assertion
            calls.append("bind")
            raise AssertionError("bind must not run after rejected admission")

    adapter = SimpleNamespace(
        production_execution_gateway_backed=True,
        provider="openai",
        routes={"draft": SimpleNamespace(model_context_limit=8_000)},
        reconciliation_mode="exact",
        capability_profile=SimpleNamespace(to_dict=lambda: {}),
        provider_id_for_stage=lambda _stage: "openai",
        model_id_for_stage=lambda _stage: "gpt-test",
    )
    preparer = ChapterGatewayAgentExecutionPreparer.__new__(
        ChapterGatewayAgentExecutionPreparer
    )
    preparer.database_url = "postgresql://unused"
    preparer.adapter = adapter
    preparer.capability_binder = RejectingBinder()
    preparer.worker_id = "worker-a"
    preparer.lease_seconds = 60
    preparer.max_cost_per_call = "1"
    preparer.budget_caps = {}
    preparer._input_assets = lambda **_kwargs: (  # type: ignore[method-assign]
        ChapterInputAsset(
            asset_version_id="context-v1",
            asset_type="context_bundle",
            content_hash="sha256:" + "a" * 64,
            content={"context_contract_version": "authority-context-bundle-v8"},
            blobs=(),
        ),
    )
    preparer._execution_identity = lambda **_kwargs: (1, "worker-a")  # type: ignore[method-assign]
    monkeypatch.setattr(
        execution_module,
        "resolve_provider_token_reservation_contract",
        lambda *_args, **_kwargs: {
            "estimated_total_tokens": 400,
            "max_output_tokens": 200,
            "estimated_cost_amount": None,
            "budget_scope_id": "",
            "budget_scope_revision": None,
            "source": "FROZEN_REQUEST_INPUT_PLUS_OUTPUT_CEILING",
        },
    )
    monkeypatch.setattr(
        execution_module,
        "read_external_effect_intent",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        execution_module,
        "plan_external_effect",
        lambda *_args, **_kwargs: calls.append("effect"),
    )
    operation = {
        "operation_id": "operation-a",
        "project_id": "project-a",
        "workspace_id": "workspace-a",
        "trace_id": "trace-a",
        "correlation_id": "correlation-a",
        "command_payload": {
            "workflow_node_id": "draft",
            "execution_capability_id": "prose.chapter.draft",
            "input_asset_versions": ["context-v1"],
            "chapter_number": 1,
            "book_id": "book-a",
            "context_token_budget": 200,
        },
    }

    with pytest.raises(KernelError, match="complete request is too large"):
        preparer.prepare(
            operation=operation,
            attempt_id="attempt-a",
            execution_fencing_token=1,
            recovery_fencing_token=1,
            worker_id="worker-a",
        )

    assert calls == ["admission"]


def test_agent_retry_reuses_pre_upgrade_frozen_effect_without_repreflight(
    monkeypatch,
) -> None:
    calls: list[str] = []
    frozen: dict[str, object] = {}

    class LegacyCompatibleBinder:
        def freeze_before_external_effect(self, **_kwargs):
            calls.append("preflight")
            return SimpleNamespace(
                provider_admission_artifact=None,
                materialization_artifact=SimpleNamespace(
                    to_dict=lambda: {"artifact_type": "legacy-materialization"}
                ),
                effect_binding={"snapshot_id": "snapshot-v1"},
            )

        def bind(self, **_kwargs):
            calls.append("bind")
            return SimpleNamespace()

    adapter = SimpleNamespace(
        production_execution_gateway_backed=True,
        provider="scripted_provider_v2",
        routes={"draft": SimpleNamespace(model_context_limit=8_000)},
        reconciliation_mode="query",
        capability_profile=SimpleNamespace(to_dict=lambda: {}),
        provider_id_for_stage=lambda _stage: "scripted_provider_v2",
        model_id_for_stage=lambda _stage: "scripted-model",
    )
    recovery_adapter = SimpleNamespace(record_authorization=lambda: None)
    adapter.for_recovery = lambda **_kwargs: recovery_adapter
    preparer = ChapterGatewayAgentExecutionPreparer.__new__(
        ChapterGatewayAgentExecutionPreparer
    )
    preparer.database_url = "postgresql://unused"
    preparer.adapter = adapter
    preparer.capability_binder = LegacyCompatibleBinder()
    preparer.worker_id = "worker-a"
    preparer.lease_seconds = 60
    preparer.max_cost_per_call = "0"
    preparer.budget_caps = {}
    preparer.evidence_writer = None
    inputs = (
        ChapterInputAsset(
            asset_version_id="context-v1",
            asset_type="context_bundle",
            content_hash="sha256:" + "a" * 64,
            content={"context_contract_version": "authority-context-bundle-v7"},
            blobs=(),
        ),
    )
    preparer._input_assets = lambda **_kwargs: inputs  # type: ignore[method-assign]
    preparer._execution_identity = lambda **_kwargs: (1, "worker-a")  # type: ignore[method-assign]
    contract_hash = "sha256:" + "b" * 64
    preparer._contracts = lambda *_args: {  # type: ignore[method-assign]
        name: contract_hash if name.endswith("_hash") else f"ref:{name}"
        for name in (
            "route_snapshot_ref",
            "route_snapshot_hash",
            "input_manifest_ref",
            "input_manifest_hash",
            "prompt_bundle_ref",
            "prompt_bundle_hash",
            "skill_bundle_ref",
            "skill_bundle_hash",
            "tool_permission_snapshot_ref",
            "tool_permission_snapshot_hash",
            "context_policy_ref",
            "context_policy_hash",
        )
    }
    monkeypatch.setattr(
        execution_module,
        "resolve_provider_token_reservation_contract",
        lambda *_args, **_kwargs: {
            "estimated_total_tokens": 400,
            "max_output_tokens": 200,
            "estimated_cost_amount": None,
            "budget_scope_id": "",
            "budget_scope_revision": None,
            "source": "FROZEN_REQUEST_INPUT_PLUS_OUTPUT_CEILING",
        },
    )

    def read_intent(*_args, **_kwargs):
        return frozen.get("intent")

    def plan(*_args, **kwargs):
        frozen["intent"] = {
            "external_effect_id": "effect-a",
            "request_payload": deepcopy(kwargs["request_payload"]),
            "provider": kwargs["provider"],
            "capability": kwargs["capability"],
            "max_attempts": kwargs["max_attempts"],
        }
        return {
            "external_effect_id": "effect-a",
            "replayed": calls.count("bind") > 0,
        }

    monkeypatch.setattr(execution_module, "read_external_effect_intent", read_intent)
    monkeypatch.setattr(execution_module, "plan_external_effect", plan)
    monkeypatch.setattr(
        execution_module,
        "reserve_provider_budget",
        lambda *_args, **_kwargs: {"reservation_id": "reservation-a"},
    )
    operation = {
        "operation_id": "operation-a",
        "project_id": "project-a",
        "workspace_id": "workspace-a",
        "trace_id": "trace-a",
        "correlation_id": "correlation-a",
        "command_payload": {
            "workflow_node_id": "draft",
            "execution_capability_id": "prose.chapter.draft",
            "input_asset_versions": ["context-v1"],
            "chapter_number": 1,
            "book_id": "book-a",
            "context_token_budget": 200,
        },
    }

    preparer.prepare(
        operation=operation,
        attempt_id="attempt-a",
        execution_fencing_token=1,
        recovery_fencing_token=1,
        worker_id="worker-a",
    )
    preparer.prepare(
        operation=operation,
        attempt_id="attempt-a",
        execution_fencing_token=1,
        recovery_fencing_token=1,
        worker_id="worker-a",
    )

    assert calls == ["preflight", "bind", "bind"]
