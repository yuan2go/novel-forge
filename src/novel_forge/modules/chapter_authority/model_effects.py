"""Generic ExternalEffect-backed model boundary for chapter handlers."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from novel_forge.modules.chapter_authority.contracts import ChapterHandlerRequest
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_adapters import ExternalEffectAdapter
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    dispatch_external_effect,
    plan_external_effect,
)
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery, AuthorityAssetWriter


@dataclass(frozen=True, slots=True)
class ModelProviderResult:
    output: dict[str, Any]
    provider_id: str
    model_id: str
    prompt_version: str
    skill_version: str
    input_tokens: int
    output_tokens: int
    cost_amount: str
    currency: str
    real_model_call: bool

    def __post_init__(self) -> None:
        if not isinstance(self.output, dict) or not self.output:
            raise ValueError("model provider output must be a non-empty object")
        if not all((self.provider_id, self.model_id, self.prompt_version, self.skill_version)):
            raise ValueError("model provider identity and semantic versions are required")
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError("model token usage cannot be negative")
        try:
            amount = Decimal(self.cost_amount)
        except InvalidOperation as exc:
            raise ValueError("model cost amount must be decimal") from exc
        if amount < 0 or not self.currency:
            raise ValueError("model cost evidence is invalid")

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_evidence(self) -> dict[str, Any]:
        return {
            "result": self.output,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "prompt_version": self.prompt_version,
            "skill_version": self.skill_version,
            "usage": {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.total_tokens,
            },
            "cost": {"amount": self.cost_amount, "currency": self.currency},
            "real_model_call": self.real_model_call,
        }

    @classmethod
    def from_evidence(cls, evidence: dict[str, Any]) -> "ModelProviderResult":
        usage = evidence.get("usage") if isinstance(evidence.get("usage"), dict) else {}
        cost = evidence.get("cost") if isinstance(evidence.get("cost"), dict) else {}
        output = evidence.get("result")
        if not isinstance(output, dict):
            raise KernelError("MODEL_EFFECT_EVIDENCE_INVALID", "model receipt has no structured result")
        try:
            return cls(
                output=output,
                provider_id=str(evidence.get("provider_id") or ""),
                model_id=str(evidence.get("model_id") or ""),
                prompt_version=str(evidence.get("prompt_version") or ""),
                skill_version=str(evidence.get("skill_version") or ""),
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                cost_amount=str(cost.get("amount") or "0"),
                currency=str(cost.get("currency") or ""),
                real_model_call=bool(evidence.get("real_model_call")),
            )
        except (TypeError, ValueError) as exc:
            raise KernelError(
                "MODEL_EFFECT_EVIDENCE_INVALID",
                "model receipt identity, usage, or cost evidence is invalid",
            ) from exc


class ChapterModelPort(Protocol):
    def invoke(
        self,
        request: ChapterHandlerRequest,
        *,
        stage: str,
        payload: dict[str, Any],
    ) -> ModelProviderResult: ...


class ExternalEffectChapterModelPort:
    external_effect_backed = True

    def __init__(
        self,
        database_url: str,
        *,
        adapter: ExternalEffectAdapter,
        worker_id: str,
        lease_seconds: int = 60,
    ) -> None:
        if not database_url or not worker_id or lease_seconds <= 0:
            raise ValueError("model effect database, worker, and lease are required")
        self.database_url = database_url
        self.adapter = adapter
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.query = AuthorityAssetQuery(database_url)
        self.writer = AuthorityAssetWriter(database_url)

    def invoke(
        self,
        request: ChapterHandlerRequest,
        *,
        stage: str,
        payload: dict[str, Any],
    ) -> ModelProviderResult:
        if stage not in {"draft", "review", "revision"}:
            raise KernelError("MODEL_EFFECT_STAGE_UNSUPPORTED", f"unsupported model stage: {stage}")
        logical_ref = _model_log_ref(request.operation_id, stage)
        existing = self._existing_result(request.project_id, logical_ref)
        if existing is not None:
            self._ensure_cost_evidence(request, stage, existing)
            return existing

        context = EffectCommandContext(
            operation_id=request.operation_id,
            project_id=request.project_id,
            actor_id=self.worker_id,
            trace_id=request.trace_id,
            correlation_id=request.correlation_id,
        )
        effect = plan_external_effect(
            self.database_url,
            context,
            effect_type="model.invoke",
            provider=self.adapter.provider,
            capability=f"model.{stage}",
            stable_idempotency_key=f"{request.operation_id}:{stage}:v1",
            request_payload={
                "stage": stage,
                "input": payload,
                "trace_id": request.trace_id,
                "workspace_id": request.workspace_id,
            },
            max_attempts=2,
            reversible=False,
            completion_policy="synchronous_final",
        )
        dispatched = dispatch_external_effect(
            self.database_url,
            context,
            effect_id=effect["external_effect_id"],
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
            adapter=self.adapter,
        )
        if dispatched["outcome"] != "success":
            raise KernelError("MODEL_EFFECT_NOT_FINAL", "model effect did not complete successfully")
        result = ModelProviderResult.from_evidence(dict(dispatched["provider_evidence"]))
        self._record_model_call(request, stage, result, logical_ref)
        self._ensure_cost_evidence(request, stage, result)
        return result

    def _existing_result(self, project_id: str, logical_ref: str) -> ModelProviderResult | None:
        try:
            document = self.query.require(project_id=project_id, logical_ref=logical_ref)
        except KernelError as exc:
            if exc.code == "AUTHORITY_ASSET_NOT_FOUND":
                return None
            raise
        evidence = document.content.get("provider_evidence")
        if not isinstance(evidence, dict):
            raise KernelError(
                "MODEL_EFFECT_EVIDENCE_INVALID",
                "stored model call has no provider evidence",
            )
        return ModelProviderResult.from_evidence(dict(evidence))

    def _record_model_call(
        self,
        request: ChapterHandlerRequest,
        stage: str,
        result: ModelProviderResult,
        logical_ref: str,
    ) -> None:
        self.writer.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=request.operation_id,
                project_id=request.project_id,
                asset_id=f"model-call:{request.operation_id}:{stage}",
                asset_type="model_call_log",
                logical_ref=logical_ref,
                category="runs",
                output_key=f"model_call.{stage}",
                role="model_evidence",
                content={
                    "type": "model_call_log",
                    "operation_id": request.operation_id,
                    "project_id": request.project_id,
                    "stage": stage,
                    "provider_evidence": result.to_evidence(),
                },
                qualification_policy="model-call-evidence-v1",
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
            )
        )

    def _ensure_cost_evidence(
        self,
        request: ChapterHandlerRequest,
        stage: str,
        result: ModelProviderResult,
    ) -> None:
        if Decimal(result.cost_amount) <= 0:
            return
        logical_ref = _cost_log_ref(request.operation_id, stage)
        try:
            self.query.require(project_id=request.project_id, logical_ref=logical_ref)
            return
        except KernelError as exc:
            if exc.code != "AUTHORITY_ASSET_NOT_FOUND":
                raise
        self.writer.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=request.operation_id,
                project_id=request.project_id,
                asset_id=f"cost-ledger:{request.operation_id}:{stage}",
                asset_type="cost_ledger",
                logical_ref=logical_ref,
                category="runs",
                output_key=f"cost_ledger.{stage}",
                role="cost_evidence",
                content={
                    "type": "cost_ledger",
                    "operation_id": request.operation_id,
                    "project_id": request.project_id,
                    "stage": stage,
                    "amount": result.cost_amount,
                    "currency": result.currency,
                    "provider_id": result.provider_id,
                    "model_id": result.model_id,
                    "total_tokens": result.total_tokens,
                },
                qualification_policy="model-cost-evidence-v1",
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
                reference_asset_ids=(f"model-call:{request.operation_id}:{stage}",),
            )
        )


def _model_log_ref(operation_id: str, stage: str) -> str:
    return f"runs/model_calls/{operation_id}-{stage}.json"


def _cost_log_ref(operation_id: str, stage: str) -> str:
    return f"runs/cost_ledgers/{operation_id}-{stage}.json"


__all__ = [
    "ChapterModelPort",
    "ExternalEffectChapterModelPort",
    "ModelProviderResult",
]
