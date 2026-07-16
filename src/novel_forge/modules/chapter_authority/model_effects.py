"""Generic ExternalEffect-backed model boundary for chapter handlers."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from novel_forge.modules.chapter_authority.contracts import ChapterHandlerRequest
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.model_adapters.base import ModelAdapter
from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapter,
    ExternalEffectAdapterError,
    ProviderResult,
)
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


@dataclass(frozen=True, slots=True)
class ChapterModelRoute:
    adapter: ModelAdapter
    provider_id: str
    model_id: str
    prompt_version: str
    skill_version: str
    real_model_call: bool

    def __post_init__(self) -> None:
        if not all(
            (
                self.provider_id,
                self.model_id,
                self.prompt_version,
                self.skill_version,
            )
        ):
            raise ValueError("chapter model route identity is incomplete")


class ChapterModelExternalEffectAdapter:
    """Adapts explicit stage routes without consulting filesystem routing state."""

    provider = "novel_forge_model_gateway_v1"

    def __init__(self, routes: dict[str, ChapterModelRoute]) -> None:
        unsupported = set(routes) - {"draft", "review", "revision"}
        if not routes or unsupported:
            raise ValueError("chapter model routes contain unsupported stages")
        self.routes = dict(routes)

    def execute(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        stage, route, inputs = self._request(capability, request_payload)
        try:
            raw = self._call(route.adapter, stage, inputs)
        except ExternalEffectAdapterError:
            raise
        except Exception as exc:
            raise ExternalEffectAdapterError(
                f"chapter model route raised {type(exc).__name__}: {exc}",
                request_sent=True,
            ) from exc
        try:
            output = _normalize_model_output(stage, raw)
            usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
            cost = raw.get("cost") if isinstance(raw.get("cost"), dict) else {}
            result = ModelProviderResult(
                output=output,
                provider_id=route.provider_id,
                model_id=route.model_id,
                prompt_version=route.prompt_version,
                skill_version=route.skill_version,
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                cost_amount=str(cost.get("amount") or "0"),
                currency=str(cost.get("currency") or "USD"),
                real_model_call=route.real_model_call,
            )
        except (KernelError, TypeError, ValueError) as exc:
            return ProviderResult(
                "final_failure",
                f"model:{stable_idempotency_key}",
                {
                    "error_code": "MODEL_RESPONSE_INVALID",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "stage": stage,
                    "provider_id": route.provider_id,
                    "model_id": route.model_id,
                },
            )
        return ProviderResult(
            "success",
            f"model:{stable_idempotency_key}",
            result.to_evidence(),
        )

    def query(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        stage, route, _inputs = self._request(capability, request_payload)
        return ProviderResult(
            "ambiguous",
            f"model-query:{stable_idempotency_key}",
            {
                "provider_state": "query_capability_not_established",
                "stage": stage,
                "provider_id": route.provider_id,
                "model_id": route.model_id,
            },
        )

    def _request(
        self,
        capability: str,
        request_payload: dict[str, Any],
    ) -> tuple[str, ChapterModelRoute, dict[str, Any]]:
        stage = str(request_payload.get("stage") or "")
        if capability != f"model.{stage}" or stage not in self.routes:
            raise ExternalEffectAdapterError(
                "chapter model capability or route is unsupported",
                request_sent=False,
            )
        inputs = request_payload.get("input")
        if not isinstance(inputs, dict):
            raise ExternalEffectAdapterError(
                "chapter model input must be an object",
                request_sent=False,
            )
        return stage, self.routes[stage], inputs

    @staticmethod
    def _call(adapter: ModelAdapter, stage: str, inputs: dict[str, Any]) -> dict[str, Any]:
        if stage == "draft":
            plan = _object(inputs, "plan")
            context = _object(inputs, "context")
            prompt = (
                f"Write chapter {plan.get('chapter', '')}: {plan.get('title', '')}\n"
                f"Premise: {plan.get('premise', '')}\n"
                f"Objective: {plan.get('objective', '')}\n"
                f"Beats: {plan.get('beats', [])}"
            )
            return adapter.generate(prompt, context)
        if stage == "review":
            draft = _object(inputs, "draft")
            return adapter.review(
                str(draft.get("text") or ""),
                {"rubric": "chapter-authority-review-v1"},
            )
        draft = _object(inputs, "draft")
        review = _object(inputs, "review")
        return adapter.revise(
            str(draft.get("text") or ""),
            review,
            {"policy": "resolve-all-blocking-issues-v1"},
        )


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


def _object(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise KernelError("MODEL_EFFECT_INPUT_INVALID", f"model input {key} must be an object")
    return value


def _normalize_model_output(stage: str, raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise KernelError("MODEL_RESPONSE_INVALID", "model response must be an object")
    if stage == "draft":
        text = str(raw.get("text") or "").strip()
        if not text:
            raise KernelError("MODEL_RESPONSE_INVALID", "draft response has no text")
        return {"text": text}
    if stage == "review":
        score_value = raw.get("score")
        if not isinstance(score_value, (int, float)) or isinstance(score_value, bool):
            raise KernelError("MODEL_RESPONSE_INVALID", "review response has no numeric score")
        score = float(score_value)
        issues = raw.get("issues")
        if not isinstance(issues, list):
            raise KernelError("MODEL_RESPONSE_INVALID", "review response has no issue list")
        normalized: list[dict[str, str]] = []
        for item in issues:
            if not isinstance(item, dict):
                raise KernelError("MODEL_RESPONSE_INVALID", "review issue must be an object")
            code = str(item.get("code") or item.get("dimension") or "").strip().upper()
            severity = _review_severity(str(item.get("severity") or ""))
            message = str(item.get("message") or "").strip()
            if not code or not message:
                raise KernelError("MODEL_RESPONSE_INVALID", "review issue identity is incomplete")
            normalized.append({"code": code, "severity": severity, "message": message})
        decision = "NEEDS_REVISION" if normalized or score < 80 else "PASSED"
        return {"decision": decision, "score": score, "issues": normalized}
    text = str(raw.get("text") or raw.get("revised_text") or "").strip()
    resolved = [
        str(item).strip()
        for item in raw.get("resolved_issue_codes", [])
        if str(item).strip()
    ]
    if not text:
        raise KernelError("MODEL_RESPONSE_INVALID", "revision response has no revised text")
    return {"text": text, "resolved_issue_codes": resolved}


def _review_severity(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"critical", "blocker", "blocking", "high"}:
        return "blocking"
    if normalized in {"major", "medium"}:
        return "major"
    return "minor"


__all__ = [
    "ChapterModelPort",
    "ChapterModelExternalEffectAdapter",
    "ChapterModelRoute",
    "ExternalEffectChapterModelPort",
    "ModelProviderResult",
]
