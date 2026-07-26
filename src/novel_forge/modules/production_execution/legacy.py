"""Fail-closed legacy ModelAdapter facade over ProductionExecutionGateway.

The mapper never invents an Attempt or translates raw chat memory into production
inputs.  Callers must supply an already-frozen ExecutionRequest and a digest that
binds the legacy call arguments to the governed input materialization.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .contracts import ExecutionOutcome, ExecutionRequest
from .evidence import ExecutionRecordStore
from .gateway import ProductionExecutionGateway
from .security import assert_legacy_execution_allowed


class LegacyRequestMapper:
    SUPPORTED_OPERATIONS = frozenset({"generate", "analyze", "review", "revise"})

    @staticmethod
    def input_digest(
        operation: str,
        payload: str,
        *,
        review: Mapping[str, Any] | None = None,
    ) -> str:
        encoded = json.dumps(
            {
                "operation": operation,
                "payload": payload,
                "review": dict(review or {}),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    def map(
        self,
        operation: str,
        payload: str,
        context: Mapping[str, Any] | None,
        *,
        review: Mapping[str, Any] | None = None,
    ) -> ExecutionRequest:
        if operation not in self.SUPPORTED_OPERATIONS:
            raise ValueError(f"unsupported legacy model operation: {operation}")
        values = dict(context or {})
        request_payload = values.get("execution_request")
        request = (
            request_payload
            if isinstance(request_payload, ExecutionRequest)
            else ExecutionRequest.from_dict(request_payload)
            if isinstance(request_payload, Mapping)
            else None
        )
        if request is None:
            raise ValueError(
                "legacy production call requires a frozen attempt-bound ExecutionRequest"
            )
        if request.stage != operation:
            raise ValueError("legacy operation differs from frozen ExecutionRequest stage")
        expected = str(values.get("legacy_input_digest") or "")
        actual = self.input_digest(operation, payload, review=review)
        if expected != actual:
            raise ValueError("legacy call payload differs from frozen input digest")
        return request


class LegacyResultMapper:
    def __init__(self, records: ExecutionRecordStore) -> None:
        self.records = records

    def map(self, result) -> dict[str, Any]:
        if result.outcome is not ExecutionOutcome.SUCCEEDED:
            raise RuntimeError(
                f"production execution did not succeed: {result.outcome.value}"
            )
        if not result.normalized_output_ref:
            raise ValueError("successful execution has no normalized output evidence")
        output = self.records.read_evidence(result.normalized_output_ref)
        output["production_execution"] = {
            "execution_id": result.execution_id,
            "operation_id": result.operation_id,
            "attempt_id": result.attempt_id,
            "fencing_token": result.fencing_token,
            "output_manifest_ref": result.output_manifest_ref,
            "validation_report_ref": result.validation_report_ref,
            "provider_receipt_ref": result.provider_receipt_ref,
            "process_receipt_ref": result.process_receipt_ref,
        }
        return output


class LegacyGatewayModelAdapter:
    """ModelAdapter-compatible facade with no provider execution implementation."""

    production_execution_gateway_backed = True

    def __init__(
        self,
        *,
        name: str,
        gateway: ProductionExecutionGateway,
        result_mapper: LegacyResultMapper,
        request_mapper: LegacyRequestMapper | None = None,
    ) -> None:
        if not name:
            raise ValueError("legacy gateway adapter requires a stable name")
        self.name = name
        self.gateway = gateway
        self.request_mapper = request_mapper or LegacyRequestMapper()
        self.result_mapper = result_mapper

    def generate(
        self, prompt: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return self._execute("generate", prompt, context)

    def analyze(
        self, text: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return self._execute("analyze", text, context)

    def review(
        self, content: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return self._execute("review", content, context)

    def revise(
        self,
        content: str,
        review: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._execute("revise", content, context, review=review)

    def batch(
        self, prompts: list[str], context: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        raise ValueError(
            "legacy batch cannot share one Authority Attempt; submit bounded requests"
        )

    def health_check(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "implemented": "production_execution_gateway",
            "configured": True,
            "ok": True,
            "independent_execution": False,
        }

    def execute_operation(
        self,
        operation: str,
        payload: str,
        context: dict[str, Any] | None = None,
        *,
        review: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._execute(operation, payload, context, review=review)

    def _execute(
        self,
        operation: str,
        payload: str,
        context: dict[str, Any] | None,
        *,
        review: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        request = self.request_mapper.map(
            operation, payload, context, review=review
        )
        handle = self.gateway.submit(request)
        return self.result_mapper.map(self.gateway.reconcile(handle))


def execute_legacy_model_operation(
    adapter: Any,
    operation: str,
    payload: Any,
    context: dict[str, Any],
) -> dict[str, Any]:
    """One quarantined compatibility seam used by the legacy Model Router.

    Production/validation environments accept only the gateway-backed facade.
    Direct adapters remain available solely for pre-migration development paths
    and cannot be mistaken for production execution evidence.
    """

    assert_legacy_execution_allowed(
        component="legacy direct model adapters",
        gateway_backed=bool(
            getattr(adapter, "production_execution_gateway_backed", False)
        ),
        environment=str(
            context.get("environment")
            or context.get("runtime_environment")
            or ""
        ),
    )
    review = context.get("review") if isinstance(context.get("review"), Mapping) else {}
    execute = getattr(adapter, "execute_operation", None)
    if callable(execute):
        return execute(
            operation,
            str(payload),
            context,
            review=review if operation == "revise" else None,
        )
    if operation == "generate":
        return adapter.generate(str(payload), context)
    if operation == "analyze":
        return adapter.analyze(str(payload), context)
    if operation in {"review", "handoff_review"}:
        return adapter.review(str(payload), context)
    if operation == "revise":
        return adapter.revise(str(payload), dict(review), context)
    raise ValueError(f"unsupported routed model operation: {operation}")


def create_legacy_development_model_adapter(
    *,
    provider: str,
    model_name: str = "",
    environment: str = "",
) -> Any:
    """Construct a compatibility adapter only outside controlled environments."""

    assert_legacy_execution_allowed(
        component=f"{provider or 'model'} adapter factory",
        gateway_backed=False,
        environment=environment,
    )
    from novel_forge.model_adapters import ModelAdapterConfig, PROVIDER_ADAPTERS

    normalized_provider = provider.strip().lower()
    adapter_cls = PROVIDER_ADAPTERS.get(normalized_provider)
    if adapter_cls is None:
        raise ValueError(f"unsupported provider adapter: {normalized_provider}")
    if not model_name:
        return adapter_cls()
    base = adapter_cls.config
    return adapter_cls(
        ModelAdapterConfig(
            provider=base.provider,
            role=base.role,
            default_model=model_name,
            required_env_vars=list(base.required_env_vars),
            external_api=base.external_api,
        )
    )


__all__ = [
    "LegacyGatewayModelAdapter",
    "LegacyRequestMapper",
    "LegacyResultMapper",
    "create_legacy_development_model_adapter",
    "execute_legacy_model_operation",
]
