from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from novel_forge.modules.operation_checkpoint import operation_checkpoint_schema
from novel_forge.storage.local import LocalStorage

OperationRunner = Callable[[LocalStorage, dict[str, Any], dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class AgentOperationSpec:
    operation: str
    aliases: tuple[str, ...]
    runner: OperationRunner
    agent_key: str
    input_types: tuple[str, ...]
    output_types: tuple[str, ...]
    required_tool: str
    checkpoint_strategy: str = "service_result"
    rollback_strategy: str = "mark_outputs_rolled_back"
    sla_seconds: int = 1800

    def checkpoint_schema(self) -> dict[str, Any]:
        schema = operation_checkpoint_schema(self.operation, checkpoint_strategy=self.checkpoint_strategy)
        return {
            **schema,
            "version": "1.0",
            "strategy": self.checkpoint_strategy,
            "required": ["status", "operation", "idempotency_key", "input_assets", "output_assets"],
            "states": ["operation_started", "agent_scheduler_service_completed", "agent_scheduler_service_failed", "agent_scheduler_rollback_applied"],
            "resume_from_checkpoint": {
                "output_committed": "reuse completed output_assets when assets still exist and are not rolled back or quarantined",
                "provider_completed": "resume output validation from durable raw provider output",
                "prompt_built": "restart provider call without rebuilding context when input fingerprints still match",
            },
            "idempotency_key": "agent_dispatch_queue.content.idempotency_key",
            "rollback_strategy": self.rollback_strategy,
        }


@dataclass(frozen=True)
class AgentOperationContract:
    operation: str
    agent_key: str = ""
    runner_kind: str = "output_reuse"
    input_types: list[str] = field(default_factory=list)
    output_types: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    checkpoint_schema: dict[str, Any] = field(default_factory=dict)
    resume_supported: bool = True
    rollback_strategy: str = "agent_rollback_report"
    gates: list[str] = field(default_factory=lambda: ["permission", "schema", "budget", "sla"])
    sla_seconds: int = 1800

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "agent_key": self.agent_key,
            "runner_kind": self.runner_kind,
            "input_types": self.input_types,
            "output_types": self.output_types,
            "required_tools": self.required_tools,
            "checkpoint_schema": self.checkpoint_schema,
            "resume_supported": self.resume_supported,
            "rollback_strategy": self.rollback_strategy,
            "gates": self.gates,
            "sla_seconds": self.sla_seconds,
        }


class OperationRegistryCatalog:
    def __init__(
        self,
        *,
        operation_runners: Callable[[], dict[str, OperationRunner]],
        operation_specs_by_alias: Callable[[], dict[str, AgentOperationSpec]],
        canonical_operation: Callable[[str], str],
        mkaos_operation_contract_fields: Callable[[str], dict[str, Any]],
        tool_name_for_output: Callable[[list[str]], str],
    ) -> None:
        self._operation_runners = operation_runners
        self._operation_specs_by_alias = operation_specs_by_alias
        self._canonical_operation = canonical_operation
        self._mkaos_operation_contract_fields = mkaos_operation_contract_fields
        self._tool_name_for_output = tool_name_for_output
        self._runner_map: dict[str, OperationRunner] | None = None
        self._spec_map: dict[str, AgentOperationSpec] | None = None

    @property
    def runners(self) -> dict[str, OperationRunner]:
        if self._runner_map is None:
            self._runner_map = self._operation_runners()
        return self._runner_map

    @property
    def specs(self) -> dict[str, AgentOperationSpec]:
        if self._spec_map is None:
            self._spec_map = self._operation_specs_by_alias()
        return self._spec_map

    def list_contracts(self) -> list[dict[str, Any]]:
        contracts = []
        for spec in sorted({item.operation: item for item in self.specs.values()}.values(), key=lambda item: item.operation):
            contract = AgentOperationContract(
                operation=spec.operation,
                agent_key=spec.agent_key,
                runner_kind="local_service",
                input_types=list(spec.input_types),
                output_types=list(spec.output_types),
                required_tools=[spec.required_tool],
                checkpoint_schema=spec.checkpoint_schema(),
                resume_supported=True,
                rollback_strategy=spec.rollback_strategy,
                sla_seconds=spec.sla_seconds,
            ).to_dict()
            contract.update(self._mkaos_operation_contract_fields(spec.operation))
            contracts.append(contract)
        contracts.append(
            AgentOperationContract(
                operation="*",
                runner_kind="output_reuse",
                required_tools=["read_asset", "run_validation"],
                checkpoint_schema={"version": "0.1.0", "strategy": "output_reuse"},
                resume_supported=True,
            ).to_dict()
        )
        return contracts

    def contract_for_run(self, agent_run: dict[str, Any], contract_asset: dict[str, Any] | None = None) -> AgentOperationContract:
        content = agent_run.get("content", {}) if isinstance(agent_run.get("content", {}), dict) else {}
        metadata = agent_run.get("metadata", {}) if isinstance(agent_run.get("metadata", {}), dict) else {}
        contract_content = contract_asset.get("content", {}) if isinstance(contract_asset, dict) and isinstance(contract_asset.get("content", {}), dict) else {}
        output_types = [str(item) for item in contract_content.get("output_types", []) if str(item).strip()] if isinstance(contract_content.get("output_types", []), list) else []
        permissions = content.get("permissions", {}) if isinstance(content.get("permissions", {}), dict) else {}
        canonical = self._canonical_operation(str(content.get("operation", "")))
        spec = self.specs.get(canonical)
        runner_kind = "local_service" if canonical in self.runners else "output_reuse"
        resolved_output_types = output_types or (list(spec.output_types) if spec else [])
        required_tools = [spec.required_tool] if spec else ([self._tool_name_for_output(resolved_output_types)] if resolved_output_types else [str((permissions.get("tool_allowlist") or ["run_validation"])[0])])
        return AgentOperationContract(
            operation=str(content.get("operation", "")),
            agent_key=str(metadata.get("agent_key", "") or (spec.agent_key if spec else "")),
            runner_kind=runner_kind,
            input_types=[str(item) for item in contract_content.get("input_types", []) if str(item).strip()] if isinstance(contract_content.get("input_types", []), list) else [],
            output_types=resolved_output_types,
            required_tools=required_tools,
            checkpoint_schema=spec.checkpoint_schema() if spec else {"version": "0.1.0", "strategy": runner_kind},
            rollback_strategy=spec.rollback_strategy if spec else "agent_rollback_report",
            sla_seconds=spec.sla_seconds if spec else 1800,
        )
