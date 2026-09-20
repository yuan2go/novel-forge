from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from typing import Any, Mapping, Protocol

from novel_forge.modules.chapter_authority.contracts import (
    ChapterHandlerRequest,
    resolve_stage_context_token_budget,
)
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapter,
)
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    dispatch_external_effect,
    plan_external_effect,
    read_external_effect_intent,
)
from novel_forge.modules.command_kernel.budget_runtime import (
    BudgetReservationRequest,
    reserve_provider_budget,
    resolve_provider_token_reservation_contract,
    resolve_provider_budget_failure,
    settle_provider_budget,
)
from novel_forge.storage.authority_asset_store import (
    AuthorityAssetQuery,
    AuthorityAssetWriter,
)
from novel_forge.storage.database_runtime import get_database_runtime
from novel_forge.modules.provider_control.contracts import (
    ProviderCapabilityProfile,
)
from novel_forge.modules.production_execution.contracts import ExecutionRecoveryAction


MODEL_CAPABILITY_STAGES = frozenset(
    {
        "memo",
        "draft",
        "review",
        "revision",
        "rereview",
        "canon_extraction",
        "canon_support",
        "quality_structural",
        "quality_commercial",
        "quality_source_originality",
        "quality_longform",
        "quality_platform",
        "narrative_semantic_evaluation",
        "agent_session",
        "retrieval",
        "retrieval_query_expansion",
    }
)
LEGACY_AGENT_BOUND_MODEL_STAGES = MODEL_CAPABILITY_STAGES


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
    execution_evidence: dict[str, Any] | None = None
    usage_evidence: dict[str, Any] | None = None
    cost_evidence: dict[str, Any] | None = None
    tool_evidence: dict[str, Any] | None = None
    capability_evidence: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.output, dict) or not self.output:
            raise ValueError("model provider output must be a non-empty object")
        if not all(
            (self.provider_id, self.model_id, self.prompt_version, self.skill_version)
        ):
            raise ValueError(
                "model provider identity and semantic versions are required"
            )
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
        evidence = {
            "result": self.output,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "prompt_version": self.prompt_version,
            "skill_version": self.skill_version,
            "usage": (
                dict(self.usage_evidence)
                if self.usage_evidence
                else {
                    "input_tokens": self.input_tokens,
                    "output_tokens": self.output_tokens,
                    "total_tokens": self.total_tokens,
                }
            ),
            "cost": (
                dict(self.cost_evidence)
                if self.cost_evidence
                else {"amount": self.cost_amount, "currency": self.currency}
            ),
            "real_model_call": self.real_model_call,
        }
        if self.execution_evidence:
            evidence["production_execution"] = dict(self.execution_evidence)
        if self.tool_evidence:
            evidence["tools"] = dict(self.tool_evidence)
        if self.capability_evidence:
            evidence["capability_runtime"] = dict(self.capability_evidence)
        return evidence

    @classmethod
    def from_evidence(cls, evidence: dict[str, Any]) -> "ModelProviderResult":
        usage = evidence.get("usage") if isinstance(evidence.get("usage"), dict) else {}
        cost = evidence.get("cost") if isinstance(evidence.get("cost"), dict) else {}
        output = evidence.get("result")
        if not isinstance(output, dict):
            raise KernelError(
                "MODEL_EFFECT_EVIDENCE_INVALID",
                "model receipt has no structured result",
            )
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
                execution_evidence=(
                    dict(evidence["production_execution"])
                    if isinstance(evidence.get("production_execution"), dict)
                    else None
                ),
                usage_evidence=dict(usage) if usage else None,
                cost_evidence=dict(cost) if cost else None,
                tool_evidence=(
                    dict(evidence["tools"])
                    if isinstance(evidence.get("tools"), dict)
                    else None
                ),
                capability_evidence=(
                    dict(evidence["capability_runtime"])
                    if isinstance(evidence.get("capability_runtime"), dict)
                    else None
                ),
            )
        except (TypeError, ValueError) as exc:
            raise KernelError(
                "MODEL_EFFECT_EVIDENCE_INVALID",
                "model receipt identity, usage, or cost evidence is invalid",
            ) from exc


def _model_budget_settlement(
    result: ModelProviderResult,
    *,
    reserved_amount: str | None,
    reserved_tokens: int,
    frozen_capability_profile: Mapping[str, Any],
) -> tuple[str | None, int, dict[str, Any]]:
    """INVARIANT: Use frozen receipt capabilities or retain the reservation ceiling.

    A successful real Provider response is not evidence that its transport
    supplied billable cost.  Releasing a bounded reservation to zero when the
    frozen Adapter declared ``supports_cost_receipt=False`` makes the hard
    stop fail open.  Fixtures retain their explicit zero-cost semantics.
    """
    cost = dict(result.cost_evidence or {})
    accounting_basis = str(cost.get("accounting_basis") or "PRICED").upper()
    if accounting_basis == "ACCOUNT_ENTITLEMENT":
        return (
            None,
            result.total_tokens if result.total_tokens > 0 else reserved_tokens,
            {
                "token_settlement_basis": (
                    "PROVIDER_USAGE_RECEIPT"
                    if result.total_tokens > 0
                    else "RESERVATION_CEILING"
                ),
                "cost_settlement_basis": "ACCOUNT_ENTITLEMENT_UNKNOWN",
                "accounting_basis": accounting_basis,
                "cost_status": "UNKNOWN",
            },
        )
    if reserved_amount is None:
        raise KernelError(
            "MODEL_EFFECT_COST_ACCOUNTING_CONFLICT",
            "priced Provider result has no monetary reservation",
        )
    if not result.real_model_call:
        return (
            result.cost_amount,
            result.total_tokens,
            {
                "token_settlement_basis": "FIXTURE_RECEIPT",
                "cost_settlement_basis": "FIXTURE_RECEIPT",
            },
        )
    supports_usage = bool(frozen_capability_profile.get("supports_usage_receipt"))
    supports_cost = bool(frozen_capability_profile.get("supports_cost_receipt"))
    usage_tokens = result.total_tokens
    actual_tokens = (
        usage_tokens if supports_usage and usage_tokens > 0 else reserved_tokens
    )
    cost_available = (
        supports_cost
        and str(cost.get("availability") or "").upper() == "AVAILABLE"
        and str(cost.get("source") or "").lower() != "not_provided"
        and cost.get("measurement") != "ESTIMATED_UPPER_BOUND"
        and cost.get("source") not in {"usage_pricing", "usage_pricing_upper_bound"}
        and cost.get("provider_billed") is True
    )
    usage_pricing = (
        supports_usage and bool(frozen_capability_profile.get("supports_usage_pricing"))
        and cost.get("source") in {"usage_pricing_upper_bound", "usage_pricing"}
        and cost.get("measurement") in {"ESTIMATED_UPPER_BOUND", "PRICED_FROM_PROVIDER_USAGE"}
        and bool(cost.get("pricing_version")) and bool(cost.get("pricing_snapshot"))
    )
    legacy_pricing = bool(
        supports_cost and cost.get("measurement") == "ESTIMATED"
        and cost.get("pricing_ref") and cost.get("pricing_snapshot_hash")
        and cost.get("calculation_basis")
    )
    actual_amount = result.cost_amount if cost_available or usage_pricing or legacy_pricing else reserved_amount
    return (
        actual_amount,
        actual_tokens,
        {
            "token_settlement_basis": (
                "PROVIDER_USAGE_RECEIPT"
                if actual_tokens == usage_tokens and supports_usage
                else "RESERVATION_CEILING"
            ),
            "cost_settlement_basis": (
                "PROVIDER_COST_RECEIPT" if cost_available
                else "LEGACY_PRICING_ESTIMATE" if legacy_pricing
                else "FROZEN_USAGE_PRICING" if usage_pricing and cost.get("measurement") == "PRICED_FROM_PROVIDER_USAGE"
                else "FROZEN_USAGE_PRICING_UPPER_BOUND" if usage_pricing
                else "RESERVATION_CEILING"
            ),
        },
    )


_MODEL_PROVIDER_RESULT_RECORDED_PHASES = frozenset(
    {"PROVIDER_RESULT_RECORDED", "PROCESS_RESULT_RECORDED"}
)
_MODEL_PROVIDER_AMBIGUOUS_PHASES = frozenset(
    {
        "PROVIDER_INVOKING",
        "PROVIDER_OUTCOME_UNKNOWN",
        "PROCESS_STARTING",
        "PROCESS_OUTCOME_UNKNOWN",
    }
)


def _model_failed_provider_submission_state(
    dispatched: Mapping[str, Any],
) -> str:

    outcome = str(dispatched.get("outcome") or "unknown").strip().lower()
    if outcome in {"unknown", "ambiguous"}:
        return "AMBIGUOUS"
    provider = dispatched.get("provider_evidence")
    provider = provider if isinstance(provider, Mapping) else {}
    production = provider.get("production_execution")
    process = (
        production.get("process_evidence") if isinstance(production, Mapping) else None
    )
    process = process if isinstance(process, Mapping) else {}
    declared = [
        value
        for value in (
            dispatched.get("request_sent"),
            provider.get("request_sent"),
            process.get("request_sent"),
        )
        if isinstance(value, bool)
    ]
    if declared and any(value != declared[0] for value in declared[1:]):
        return "AMBIGUOUS"
    phase = str(process.get("submission_phase") or "").strip().upper()
    measured = _failed_provider_measurement(dispatched) is not None
    if declared:
        if declared[0]:
            return "AMBIGUOUS" if phase in _MODEL_PROVIDER_AMBIGUOUS_PHASES else "SENT"
        if measured or phase in (
            _MODEL_PROVIDER_RESULT_RECORDED_PHASES | _MODEL_PROVIDER_AMBIGUOUS_PHASES
        ):
            return "AMBIGUOUS"
        return "NOT_SENT"
    if any(
        str(value).strip().lower() in {"unknown", "not_established"}
        for value in (
            dispatched.get("request_sent"),
            provider.get("request_sent"),
            process.get("request_sent"),
        )
        if value is not None
    ):
        return "AMBIGUOUS"
    if phase in _MODEL_PROVIDER_AMBIGUOUS_PHASES:
        return "AMBIGUOUS"
    if measured or phase in _MODEL_PROVIDER_RESULT_RECORDED_PHASES:
        return "SENT"
    return "AMBIGUOUS"


def _model_failed_provider_budget_decision(
    *,
    dispatched: Mapping[str, Any],
    reserved_amount: str | None,
    reserved_tokens: int,
    frozen_capability_profile: Mapping[str, Any],
) -> dict[str, Any]:
    submission_state = _model_failed_provider_submission_state(dispatched)
    if submission_state == "NOT_SENT":
        return {"disposition": "RELEASE", "submission_state": submission_state}
    if submission_state == "AMBIGUOUS":
        return {
            "disposition": "HOLD_UNKNOWN",
            "submission_state": submission_state,
        }
    measurement = _failed_provider_measurement(dispatched)
    usage_authoritative = bool(
        measurement is not None
        and frozen_capability_profile.get("supports_usage_receipt") is True
    )
    cost_authoritative = bool(
        measurement is not None
        and reserved_amount is not None
        and frozen_capability_profile.get("supports_cost_receipt") is True
        and measurement[1].get("provider_billed") is True
        and measurement[1].get("source") not in {"usage_pricing", "usage_pricing_upper_bound"}
    )
    usage_priced = bool(
        measurement is not None
        and usage_authoritative
        and reserved_amount is not None
        and frozen_capability_profile.get("supports_usage_pricing") is True
        and measurement[1].get("source") in {"usage_pricing", "usage_pricing_upper_bound"}
        and measurement[1].get("pricing_version")
        and measurement[1].get("pricing_snapshot")
    )
    legacy_pricing = bool(
        measurement is not None
        and usage_authoritative and reserved_amount is not None
        and frozen_capability_profile.get("supports_cost_receipt") is True
        and measurement[1].get("measurement") == "ESTIMATED"
        and measurement[1].get("pricing_ref") and measurement[1].get("pricing_snapshot_hash")
        and measurement[1].get("calculation_basis")
    )
    measurement_authoritative = usage_authoritative and (
        cost_authoritative or usage_priced or legacy_pricing or reserved_amount is None
    )
    if usage_authoritative:
        assert measurement is not None
        usage, _cost = measurement
        actual_tokens = int(usage.get("total_tokens") or 0) or int(
            usage.get("input_tokens") or 0
        ) + int(usage.get("output_tokens") or 0)
    else:
        actual_tokens = reserved_tokens
    if cost_authoritative or usage_priced or legacy_pricing:
        assert measurement is not None
        _usage, cost = measurement
        actual_amount: str | None = str(cost.get("amount") or "0")
    else:
        actual_amount = reserved_amount
    decision = {
        "disposition": "SETTLE",
        "submission_state": submission_state,
        "measurement_available": measurement_authoritative,
        "actual_amount": actual_amount,
        "actual_tokens": actual_tokens,
        "token_settlement_basis": (
            "PROVIDER_USAGE_RECEIPT" if usage_authoritative else "RESERVATION_CEILING"
        ),
        "cost_settlement_basis": (
            "PROVIDER_COST_RECEIPT"
            if cost_authoritative
            else "LEGACY_PRICING_ESTIMATE" if legacy_pricing
            else "FROZEN_USAGE_PRICING" if usage_priced
            else (
                "ACCOUNT_ENTITLEMENT_UNKNOWN"
                if reserved_amount is None
                else "RESERVATION_CEILING"
            )
        ),
    }
    if reserved_amount is None:
        decision.update(
            {"accounting_basis": "ACCOUNT_ENTITLEMENT", "cost_status": "UNKNOWN"}
        )
    return decision


class ChapterModelPort(Protocol):
    def invoke(
        self,
        request: ChapterHandlerRequest,
        *,
        stage: str,
        payload: dict[str, Any],
        reservation_amount: str | None = None,
        reservation_tokens: int | None = None,
        pre_send_assertion: Callable[[], None] | None = None,
    ) -> ModelProviderResult: ...


class ChapterAgentBindingRecorder(Protocol):
    def freeze(
        self,
        request: ChapterHandlerRequest,
        *,
        stage: str,
        execution_binding: Any,
    ) -> Any: ...

    def accept_candidate(
        self,
        frozen_work_order: Any,
        *,
        result: ModelProviderResult,
        execution_binding: Any,
    ) -> None: ...

    def record_compatibility_usage(
        self, request: ChapterHandlerRequest, *, stage: str
    ) -> None: ...

    def finalize_domain_commit(
        self,
        *,
        project_id: str,
        operation_id: str,
        attempt_id: str,
        fencing_token: int,
        asset_version_id: str,
        content_hash: str,
    ) -> Any: ...

    def record_domain_rejection(
        self,
        *,
        project_id: str,
        operation_id: str,
        attempt_id: str,
        error_code: str,
    ) -> bool: ...


class ExternalEffectChapterModelPort:
    external_effect_backed = True

    def __init__(
        self,
        database_url: str,
        *,
        adapter: ExternalEffectAdapter,
        worker_id: str,
        lease_seconds: int = 60,
        max_cost_per_call: str = "0",
        budget_caps: dict[str, str] | None = None,
        agent_binding_recorder: ChapterAgentBindingRecorder | None = None,
        agent_binding_required: bool = False,
        fault_injector: Callable[[str], None] | None = None,
        capability_binder: Any | None = None,
        execution_binding_domain: str = "chapter",
    ) -> None:
        if not database_url or not worker_id or lease_seconds <= 0:
            raise ValueError("model effect database, worker, and lease are required")
        self.database_url = database_url
        self.adapter = adapter
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        try:
            if Decimal(max_cost_per_call) < 0:
                raise ValueError
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(
                "model max cost per call must be a non-negative decimal"
            ) from exc
        self.max_cost_per_call = max_cost_per_call
        self.budget_caps = dict(budget_caps or {})
        self.cost_accounting_basis = str(
            getattr(adapter, "cost_accounting_basis", "PRICED") or "PRICED"
        ).upper()
        self.account_authorization_ref = str(
            getattr(adapter, "account_authorization_ref", "") or ""
        )
        self.provider_call_caps = {
            str(key): int(value)
            for key, value in dict(
                getattr(adapter, "provider_call_caps", {}) or {}
            ).items()
        }
        self.provider_token_caps = {
            str(key): int(value)
            for key, value in dict(
                getattr(adapter, "provider_token_caps", {}) or {}
            ).items()
        }
        if self.cost_accounting_basis == "ACCOUNT_ENTITLEMENT":
            if not self.account_authorization_ref:
                raise ValueError(
                    "account-entitlement model execution requires authorization"
                )
            if self.budget_caps:
                raise ValueError(
                    "account-entitlement model execution cannot use monetary caps"
                )
        self.agent_binding_recorder = agent_binding_recorder
        self.agent_binding_required = agent_binding_required
        self.fault_injector = fault_injector or (lambda _checkpoint: None)
        self.capability_binder = capability_binder
        self.execution_binding_domain = execution_binding_domain.strip().lower()
        if not self.execution_binding_domain:
            raise ValueError("model execution binding domain is required")
        if agent_binding_required and agent_binding_recorder is None:
            raise ValueError(
                "production Chapter model execution requires Agent Binding"
            )
        self.query = AuthorityAssetQuery(database_url)
        self.writer = AuthorityAssetWriter(database_url)

    def _bounded_reservation_amount(self, requested: str | None) -> str | None:
        if self.cost_accounting_basis == "ACCOUNT_ENTITLEMENT":
            if requested is not None:
                raise KernelError(
                    "MODEL_EFFECT_RESERVATION_OVERRIDE_INVALID",
                    "account entitlement cannot declare a monetary reservation",
                )
            return None
        if requested is None:
            return self.max_cost_per_call
        try:
            amount = Decimal(requested)
            maximum = Decimal(self.max_cost_per_call)
        except (InvalidOperation, ValueError) as exc:
            raise KernelError(
                "MODEL_EFFECT_RESERVATION_OVERRIDE_INVALID",
                "model effect reservation amount must be numeric",
            ) from exc
        if amount < 0 or amount > maximum:
            raise KernelError(
                "MODEL_EFFECT_RESERVATION_OVERRIDE_INVALID",
                "model effect reservation amount must be within the Provider call cap",
            )
        return str(amount)

    @staticmethod
    def _bounded_reservation_tokens(requested: int | None, *, default: int) -> int:
        if requested is None:
            return default
        tokens = int(requested)
        if tokens <= 0 or tokens > default:
            raise KernelError(
                "MODEL_EFFECT_RESERVATION_OVERRIDE_INVALID",
                "model effect token reservation must be positive and within the frozen context cap",
            )
        return tokens

    def invoke(
        self,
        request: ChapterHandlerRequest,
        *,
        stage: str,
        payload: dict[str, Any],
        reservation_amount: str | None = None,
        reservation_tokens: int | None = None,
        pre_send_assertion: Callable[[], None] | None = None,
    ) -> ModelProviderResult:
        if stage not in MODEL_CAPABILITY_STAGES | {"reader_outcome"}:
            raise KernelError(
                "MODEL_EFFECT_STAGE_UNSUPPORTED", f"unsupported model stage: {stage}"
            )
        business_payload = (
            request.command.get("payload")
            if isinstance(request.command.get("payload"), dict)
            else request.command
        )
        default_reservation_tokens = resolve_stage_context_token_budget(
            business_payload, stage, default=0
        )
        bounded_reservation_amount = self._bounded_reservation_amount(
            reservation_amount
        )
        bounded_reservation_tokens = self._bounded_reservation_tokens(
            reservation_tokens,
            default=default_reservation_tokens,
        )
        if bounded_reservation_tokens <= 0:
            raise KernelError(
                "MODEL_EFFECT_PROVIDER_TOKEN_CEILING_REQUIRED",
                "model Provider execution requires a positive frozen token ceiling",
            )
        reservation_contract = resolve_provider_token_reservation_contract(
            self.database_url,
            operation_id=request.operation_id,
            project_id=request.project_id,
            currency=(
                "UNKNOWN"
                if self.cost_accounting_basis == "ACCOUNT_ENTITLEMENT"
                else "USD"
            ),
            frozen_request_token_ceiling=bounded_reservation_tokens,
            accounting_basis=self.cost_accounting_basis,
            cost_authorization_ref=self.account_authorization_ref,
        )
        provider_output_token_ceiling = bounded_reservation_tokens
        budget_scope_id = ""
        budget_scope_revision = None
        if reservation_contract["source"] == ("BOOK_OPENING_IMMUTABLE_PER_CALL_POLICY"):
            bounded_reservation_tokens = int(
                reservation_contract["estimated_total_tokens"]
            )
            provider_output_token_ceiling = int(
                reservation_contract["max_output_tokens"]
            )
            contract_amount = reservation_contract["estimated_cost_amount"]
            bounded_reservation_amount = (
                str(contract_amount) if contract_amount is not None else None
            )
            budget_scope_id = str(reservation_contract["budget_scope_id"])
            budget_scope_revision = int(reservation_contract["budget_scope_revision"])
        route = getattr(self.adapter, "routes", {}).get(stage)
        route_context_limit = int(getattr(route, "model_context_limit", 0) or 0)
        provider_admission_token_limit = (
            int(reservation_contract["estimated_total_tokens"])
            if reservation_contract["source"]
            == "BOOK_OPENING_IMMUTABLE_PER_CALL_POLICY"
            else route_context_limit
            or int(reservation_contract["estimated_total_tokens"])
        )
        context = EffectCommandContext(
            operation_id=request.operation_id,
            project_id=request.project_id,
            actor_id=request.worker_id or self.worker_id,
            trace_id=request.trace_id,
            correlation_id=request.correlation_id,
        )
        effect_instance = str(request.command.get("_effect_instance") or "").strip()
        if effect_instance and (len(effect_instance) > 200 or "/" in effect_instance):
            raise KernelError(
                "MODEL_EFFECT_INSTANCE_INVALID",
                "model effect instance must be a bounded stable identity",
            )
        stable_key = ":".join(
            item
            for item in (
                request.operation_id,
                request.attempt_id,
                stage,
                effect_instance,
                "attempt-v1",
            )
            if item
        )
        execution_fencing_token, execution_worker_id = self._execution_identity(
            request,
            stable_key=stable_key,
        )
        provider_request_timeout_seconds = self._request_timeout_seconds(request)
        effect_request_payload = {
            "stage": stage,
            "max_output_tokens": provider_output_token_ceiling,
            "stable_idempotency_key": stable_key,
            "input": payload,
            "trace_id": request.trace_id,
            "correlation_id": request.correlation_id,
            "workspace_id": request.workspace_id,
            "_production_execution": {
                "operation_id": request.operation_id,
                "attempt_id": request.attempt_id,
                "fencing_token": execution_fencing_token,
                "project_id": request.project_id,
                "workspace_id": request.workspace_id,
                "worker_id": execution_worker_id,
                "chapter": int(
                    business_payload.get("chapter_number")
                    or business_payload.get("chapter")
                    or 0
                ),
                "book_id": str(
                    business_payload.get("book_id") or f"book:{request.project_id}"
                ),
                "agent_session_id": str(business_payload.get("agent_session_id") or ""),
                "agent_execution_contract": dict(
                    business_payload.get("agent_execution_contract") or {}
                ),
                "agent_execution_contract_hash": str(
                    business_payload.get("agent_execution_contract_hash") or ""
                ),
                "target_asset_version_id": str(
                    business_payload.get("target_asset_version_id") or ""
                ),
                "source_asset_version_id": str(
                    business_payload.get("source_asset_version_id") or ""
                ),
                "source_content_hash": str(
                    business_payload.get("source_content_hash") or ""
                ),
                "target_content_hash": str(
                    business_payload.get("target_content_hash") or ""
                ),
                "generation_operation_id": str(
                    business_payload.get("generation_operation_id") or ""
                ),
                "generator_operation_name": str(
                    business_payload.get("generator_operation_name") or ""
                ),
                "route_provider": str(
                    getattr(
                        self.adapter,
                        "provider_id_for_stage",
                        lambda _stage: self.adapter.provider,
                    )(stage)
                ),
                "execution_binding_domain": self.execution_binding_domain,
                "provider_request_timeout_seconds": provider_request_timeout_seconds,
                "provider_token_limit": provider_admission_token_limit,
                "input_artifacts": [
                    {
                        "artifact_ref": f"asset-version:{item.asset_version_id}",
                        "asset_version_id": item.asset_version_id,
                        "artifact_type": item.asset_type,
                        "content_hash": item.content_hash,
                        "schema_version": str(
                            item.content.get("schema_version")
                            or item.content.get("contract_version")
                            or f"{item.asset_type}.v1"
                        ),
                        "source_eligibility": "PRODUCTION_ELIGIBLE",
                    }
                    for item in request.inputs
                ],
            },
        }
        binder = self.capability_binder or getattr(self.adapter, "binder", None)
        route_provider = str(
            getattr(
                self.adapter,
                "provider_id_for_stage",
                lambda _stage: self.adapter.provider,
            )(stage)
        )
        provider_admission_required = bool(
            getattr(self.adapter, "production_execution_gateway_backed", False)
            and route_provider != "scripted_provider_v2"
        )
        existing_intent = read_external_effect_intent(
            self.database_url,
            context,
            effect_type="model.invoke",
            stable_idempotency_key=stable_key,
        )
        if self.agent_binding_required and binder is None and existing_intent is None:
            raise KernelError(
                "CHAPTER_CAPABILITY_PREFLIGHT_REQUIRED",
                "controlled Chapter model node has no Capability contract binder",
            )
        if existing_intent is not None:
            frozen_payload = dict(existing_intent["request_payload"])
            expected_outer = {
                key: value
                for key, value in effect_request_payload.items()
                if key != "_production_execution"
            }
            frozen_outer = {
                key: value
                for key, value in frozen_payload.items()
                if key != "_production_execution"
            }
            frozen_metadata = frozen_payload.get("_production_execution")
            if (
                json.dumps(
                    frozen_outer,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                != json.dumps(
                    expected_outer,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                or existing_intent["provider"] != self.adapter.provider
                or existing_intent["capability"] != f"model.{stage}"
                or int(existing_intent["max_attempts"]) != 2
                or not isinstance(frozen_metadata, Mapping)
                or str(frozen_metadata.get("operation_id") or "")
                != request.operation_id
                or str(frozen_metadata.get("attempt_id") or "") != request.attempt_id
                or str(frozen_metadata.get("project_id") or "") != request.project_id
                or str(frozen_metadata.get("book_id") or "")
                != str(effect_request_payload["_production_execution"]["book_id"])
            ):
                raise KernelError(
                    "MODEL_EFFECT_INTENT_DRIFT",
                    "model retry differs from the first frozen Provider intent",
                )
            frozen_runtime = frozen_metadata.get("capability_runtime")
            if provider_admission_required and isinstance(frozen_runtime, Mapping):
                frozen_admission = frozen_runtime.get("provider_admission")
                if isinstance(frozen_admission, Mapping):
                    frozen_total = int(frozen_admission.get("total_reserved") or 0)
                    if frozen_total <= 0:
                        raise KernelError(
                            "PROVIDER_ADMISSION_INVALID",
                            "frozen Provider admission has no positive bounded usage",
                        )
                    bounded_reservation_tokens = frozen_total
            effect_request_payload = frozen_payload
        elif binder is not None:
            freeze_capability = getattr(binder, "freeze_before_external_effect", None)
            if not callable(freeze_capability):
                raise KernelError(
                    "CHAPTER_CAPABILITY_PREFLIGHT_REQUIRED",
                    "Chapter contract binder cannot freeze Capability before effect",
                )
            preflight = freeze_capability(
                capability=f"model.{stage}",
                request_payload=effect_request_payload,
                snapshot_fencing_token=request.fencing_token,
                snapshot_worker_id=request.worker_id or self.worker_id,
            )
            if provider_admission_required and (
                preflight is None or preflight.provider_admission_artifact is None
            ):
                raise KernelError(
                    "PROVIDER_ADMISSION_REQUIRED",
                    "Production Execution cannot create an ExternalEffect without "
                    "a frozen Provider admission receipt",
                )
            if preflight is not None:
                if provider_admission_required:
                    receipt = preflight.effect_binding.get("provider_admission")
                    if not isinstance(receipt, Mapping):
                        raise KernelError(
                            "PROVIDER_ADMISSION_REQUIRED",
                            "Provider admission receipt is absent from the frozen binding",
                        )
                    bounded_reservation_tokens = int(receipt.get("total_reserved") or 0)
                    if bounded_reservation_tokens <= 0:
                        raise KernelError(
                            "PROVIDER_ADMISSION_INVALID",
                            "Provider admission has no positive bounded request usage",
                        )
                metadata = dict(effect_request_payload["_production_execution"])
                frozen_artifacts = list(metadata["input_artifacts"])
                frozen_artifacts.append(preflight.materialization_artifact.to_dict())
                if preflight.provider_admission_artifact is not None:
                    frozen_artifacts.append(
                        preflight.provider_admission_artifact.to_dict()
                    )
                metadata.update(
                    {
                        "input_artifacts": frozen_artifacts,
                        "capability_runtime": dict(preflight.effect_binding),
                    }
                )
                effect_request_payload = {
                    **effect_request_payload,
                    "_production_execution": metadata,
                }
                self.fault_injector("after_capability_preflight")
        elif provider_admission_required:
            raise KernelError(
                "PROVIDER_ADMISSION_REQUIRED",
                "Production Execution has no Provider admission binder",
            )
        routing_decision = dict(effect_request_payload.get("_production_execution", {}).get("capability_runtime", {}).get("routing_decision") or {})
        cost_accounting_basis = self.cost_accounting_basis
        account_authorization_ref = self.account_authorization_ref
        if routing_decision:
            from novel_forge.modules.production_execution.routing_runtime import routed_reservation

            upper_bound = routed_reservation(routing_decision,
                input_tokens=max(0, bounded_reservation_tokens - provider_output_token_ceiling),
                output_tokens=provider_output_token_ceiling)
            selected = routing_decision["selected"]["candidate"]
            cost_accounting_basis = selected["pricing"]["accounting_basis"]
            account_authorization_ref = selected.get("authorization_ref", "")
            bounded_reservation_amount = None if cost_accounting_basis == "ACCOUNT_ENTITLEMENT" else self._bounded_reservation_amount(upper_bound)
        selected_model = (routing_decision.get("selected") or {}).get("candidate", {}).get("model")
        effect = plan_external_effect(
            self.database_url,
            context,
            effect_type="model.invoke",
            provider=self.adapter.provider,
            capability=f"model.{stage}",
            stable_idempotency_key=stable_key,
            request_payload=effect_request_payload,
            max_attempts=2,
            reversible=False,
            completion_policy="synchronous_final",
            model_id=str(selected_model or
                getattr(self.adapter, "model_id_for_stage", lambda _stage: "")(stage)
            ),
            request_timeout_seconds=provider_request_timeout_seconds,
            reconciliation_mode=str(self.adapter.reconciliation_mode),
            provider_capability_profile=(
                self.adapter.capability_profile.to_dict()
                if isinstance(
                    self.adapter.capability_profile, ProviderCapabilityProfile
                )
                else dict(self.adapter.capability_profile)
            ),
        )
        external_effect_id = str(effect["external_effect_id"])
        logical_ref = _model_log_ref(
            request.operation_id,
            request.attempt_id,
            stage,
            external_effect_id,
        )
        self.fault_injector("after_external_effect_plan")
        effect_adapter = self.adapter
        if bool(effect.get("replayed")):
            authorize = getattr(self.adapter, "for_recovery", None)
            if not callable(authorize):
                if execution_fencing_token != request.fencing_token:
                    raise KernelError(
                        "MODEL_EFFECT_RECOVERY_AUTHORIZATION_MISSING",
                        "stale execution fence requires an explicit recovery adapter",
                    )
            else:
                effect_adapter = authorize(
                    execution_id=(
                        "chapter-execution:" + str(effect["external_effect_id"])
                    ),
                    external_effect_id=str(effect["external_effect_id"]),
                    operation_id=request.operation_id,
                    attempt_id=request.attempt_id,
                    execution_fencing_token=execution_fencing_token,
                    recovery_fencing_token=request.fencing_token,
                    recovery_worker_id=request.worker_id,
                    action=ExecutionRecoveryAction.DISPATCH_PLANNED,
                    trace_id=request.trace_id,
                    correlation_id=request.correlation_id,
                )
                record_authorization = getattr(
                    effect_adapter, "record_authorization", None
                )
                if callable(record_authorization):
                    record_authorization()
        reservation = reserve_provider_budget(
            self.database_url,
            BudgetReservationRequest(
                operation_id=request.operation_id,
                external_effect_id=str(effect["external_effect_id"]),
                project_id=request.project_id,
                stable_idempotency_key=f"budget:{stable_key}",
                provider=(routing_decision.get("selected") or {}).get("candidate", {}).get("provider") or self.adapter.provider,
                model_id=str(selected_model or ""),
                work_id=str(effect_request_payload["_production_execution"]["book_id"]) if routing_decision else "",
                currency=(
                    "UNKNOWN"
                    if cost_accounting_basis == "ACCOUNT_ENTITLEMENT"
                    else "USD"
                ),
                estimated_amount=bounded_reservation_amount,
                estimated_tokens=bounded_reservation_tokens,
                chapter=int(
                    business_payload.get("chapter_number")
                    or business_payload.get("chapter")
                    or 0
                )
                or None,
                caps={} if cost_accounting_basis == "ACCOUNT_ENTITLEMENT" else self.budget_caps,
                call_caps=self.provider_call_caps,
                token_caps=self.provider_token_caps,
                budget_scope_id=budget_scope_id,
                expected_budget_scope_revision=budget_scope_revision,
                accounting_basis=cost_accounting_basis,
                cost_authorization_ref=account_authorization_ref,
            ),
        )
        execution_binding = None
        frozen_work_order = None
        if self.agent_binding_recorder is not None:
            if binder is None:
                raise KernelError(
                    "CHAPTER_AGENT_BINDING_PEP_REQUIRED",
                    "Chapter Agent Binding requires the PEP contract binder",
                )
            execution_binding = binder.bind(
                stable_idempotency_key=stable_key,
                capability=f"model.{stage}",
                request_payload={
                    **effect_request_payload,
                    "external_effect_id": str(effect["external_effect_id"]),
                    "_production_execution": {
                        **effect_request_payload["_production_execution"],
                        # WHY: ExternalEffect keeps its original execution identity.
                        # Snapshot admission instead uses the worker that holds
                        # the Attempt lease now, including after takeover.
                        "snapshot_fencing_token": request.fencing_token,
                        "snapshot_worker_id": request.worker_id or self.worker_id,
                    },
                },
                external_effect_id=str(effect["external_effect_id"]),
            )
            frozen_work_order = self.agent_binding_recorder.freeze(
                request,
                stage=stage,
                execution_binding=execution_binding,
            )
        elif self.agent_binding_required:
            raise KernelError(
                "CHAPTER_AGENT_BINDING_REQUIRED",
                "production Chapter model node has no Agent Binding recorder",
            )
        else:
            # COMPATIBILITY: the development path is explicit, never a fallback.
            recorder = self.agent_binding_recorder
            if recorder is not None:
                recorder.record_compatibility_usage(request, stage=stage)
        completed = self.completed_effect_result(external_effect_id, request.project_id)
        if completed is not None:
            if bool(effect.get("replayed")):
                authorize = getattr(self.adapter, "for_recovery", None)
                if callable(authorize):
                    authorization = authorize(
                        execution_id=(
                            "chapter-execution:" + str(effect["external_effect_id"])
                        ),
                        external_effect_id=str(effect["external_effect_id"]),
                        operation_id=request.operation_id,
                        attempt_id=request.attempt_id,
                        execution_fencing_token=execution_fencing_token,
                        recovery_fencing_token=request.fencing_token,
                        recovery_worker_id=request.worker_id,
                        action=ExecutionRecoveryAction.CONSUME_RESULT,
                        trace_id=request.trace_id,
                        correlation_id=request.correlation_id,
                    )
                    authorization.record_authorization()
            (
                completed_amount,
                completed_tokens,
                settlement_basis,
            ) = _model_budget_settlement(
                completed,
                reserved_amount=bounded_reservation_amount,
                reserved_tokens=bounded_reservation_tokens,
                frozen_capability_profile=dict(
                    effect.get("provider_capability_profile") or {}
                ),
            )
            settle_provider_budget(
                self.database_url,
                reservation_id=str(reservation["reservation_id"]),
                project_id=request.project_id,
                actual_amount=completed_amount,
                actual_tokens=completed_tokens,
                evidence={
                    "provider_id": completed.provider_id,
                    "model_id": completed.model_id,
                    "real_model_call": completed.real_model_call,
                    "fixture": not completed.real_model_call,
                    "recovered_completed_effect": True,
                    **settlement_basis,
                },
            )
            self._record_model_call(
                request,
                stage,
                completed,
                logical_ref,
                external_effect_id=external_effect_id,
            )
            self._ensure_cost_evidence(
                request,
                stage,
                completed,
                external_effect_id=external_effect_id,
            )
            self._validate_retrieval_result_contract(
                stage=stage,
                project_id=request.project_id,
                external_effect_id=external_effect_id,
                result=completed,
            )
            if frozen_work_order is not None and execution_binding is not None:
                self.agent_binding_recorder.accept_candidate(
                    frozen_work_order,
                    result=completed,
                    execution_binding=execution_binding,
                )
            return completed
        if not bool(reservation.get("execution_authorized")):
            raise KernelError(
                "BUDGET_RESERVATION_EXECUTION_NOT_AUTHORIZED",
                "reservation replay cannot authorize another Provider dispatch: "
                + str(reservation.get("replay_disposition") or "UNKNOWN"),
            )
        try:
            dispatched = dispatch_external_effect(
                self.database_url,
                context,
                effect_id=effect["external_effect_id"],
                worker_id=request.worker_id or self.worker_id,
                lease_seconds=self.lease_seconds,
                adapter=effect_adapter,
                budget_reservation_id=str(reservation["reservation_id"]),
                pre_send_assertion=pre_send_assertion,
            )
        except KernelError:
            resolve_provider_budget_failure(
                self.database_url,
                reservation_id=str(reservation["reservation_id"]),
                project_id=request.project_id,
            )
            raise
        if dispatched["outcome"] != "success":
            decision = _model_failed_provider_budget_decision(
                dispatched=dispatched,
                reserved_amount=bounded_reservation_amount,
                reserved_tokens=bounded_reservation_tokens,
                frozen_capability_profile=dict(
                    effect.get("provider_capability_profile") or {}
                ),
            )
            if decision["disposition"] == "RELEASE":
                resolve_provider_budget_failure(
                    self.database_url,
                    reservation_id=str(reservation["reservation_id"]),
                    project_id=request.project_id,
                )
            elif decision["disposition"] == "HOLD_UNKNOWN":
                resolve_provider_budget_failure(
                    self.database_url,
                    reservation_id=str(reservation["reservation_id"]),
                    project_id=request.project_id,
                    external_state_unknown=True,
                )
            else:
                settle_provider_budget(
                    self.database_url,
                    reservation_id=str(reservation["reservation_id"]),
                    project_id=request.project_id,
                    actual_amount=(
                        str(decision["actual_amount"])
                        if decision["actual_amount"] is not None
                        else None
                    ),
                    actual_tokens=int(decision["actual_tokens"]),
                    evidence={
                        "provider_id": str(
                            (dispatched.get("provider_evidence") or {}).get(
                                "provider_id"
                            )
                            or ""
                        ),
                        "real_model_call": True,
                        "execution_outcome": str(dispatched["outcome"]).upper(),
                        "accepted_candidate": False,
                        "submission_state": str(decision["submission_state"]),
                        "measurement_available": bool(
                            decision["measurement_available"]
                        ),
                        "token_settlement_basis": str(
                            decision["token_settlement_basis"]
                        ),
                        "cost_settlement_basis": str(decision["cost_settlement_basis"]),
                        **(
                            {
                                "accounting_basis": str(decision["accounting_basis"]),
                                "cost_status": str(decision["cost_status"]),
                            }
                            if "accounting_basis" in decision
                            else {}
                        ),
                    },
                )
            measurement = _failed_provider_measurement(dispatched)
            if (
                decision.get("measurement_available") is True
                and measurement is not None
            ):
                usage, cost = measurement
                self._record_failed_model_call(
                    request,
                    stage,
                    dispatched=dispatched,
                    logical_ref=logical_ref,
                    external_effect_id=external_effect_id,
                )
                self._record_failed_cost_evidence(
                    request,
                    stage,
                    dispatched=dispatched,
                    usage=usage,
                    cost=cost,
                    external_effect_id=external_effect_id,
                )
            _raise_model_effect_failure(dispatched)
        result = ModelProviderResult.from_evidence(
            dict(dispatched["provider_evidence"])
        )
        self.fault_injector("after_provider_success")
        actual_amount, actual_tokens, settlement_basis = _model_budget_settlement(
            result,
            reserved_amount=bounded_reservation_amount,
            reserved_tokens=bounded_reservation_tokens,
            frozen_capability_profile=dict(
                effect.get("provider_capability_profile") or {}
            ),
        )
        settle_provider_budget(
            self.database_url,
            reservation_id=str(reservation["reservation_id"]),
            project_id=request.project_id,
            actual_amount=actual_amount,
            actual_tokens=actual_tokens,
            evidence={
                "provider_id": result.provider_id,
                "model_id": result.model_id,
                "real_model_call": result.real_model_call,
                "fixture": not result.real_model_call,
                **settlement_basis,
            },
        )
        self._record_model_call(
            request,
            stage,
            result,
            logical_ref,
            external_effect_id=external_effect_id,
        )
        self._ensure_cost_evidence(
            request,
            stage,
            result,
            external_effect_id=str(effect["external_effect_id"]),
        )
        self._validate_retrieval_result_contract(
            stage=stage,
            project_id=request.project_id,
            external_effect_id=external_effect_id,
            result=result,
        )
        if frozen_work_order is not None and execution_binding is not None:
            self.agent_binding_recorder.accept_candidate(
                frozen_work_order,
                result=result,
                execution_binding=execution_binding,
            )
        return result

    def _validate_retrieval_result_contract(
        self,
        *,
        stage: str,
        project_id: str,
        external_effect_id: str,
        result: ModelProviderResult,
    ) -> None:
        if stage != "retrieval":
            return
        runtime = get_database_runtime(self.database_url)
        with runtime.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT request_payload->'_production_execution'
                                          ->'capability_runtime'
                                          ->'embedding_output_contract'
                    FROM authority_external_effect
                    WHERE project_id=%s AND external_effect_id=%s
                    """,
                    [project_id, external_effect_id],
                )
                row = cursor.fetchone()
        frozen = row[0] if row is not None else None
        if not isinstance(frozen, Mapping):
            if result.real_model_call:
                raise KernelError(
                    "RETRIEVAL_EMBEDDING_OUTPUT_CONTRACT_MISSING",
                    "real retrieval Provider result has no frozen output identity",
                )
            return
        expected_model = str(frozen.get("embedding_model") or "")
        expected_dimensions = int(frozen.get("embedding_dimensions") or 0)
        vectors = result.output.get("vectors")
        returned_model = str(result.output.get("embedding_model") or "")
        returned_dimensions = int(result.output.get("embedding_dimensions") or 0)
        if (
            not expected_model
            or expected_dimensions <= 0
            or result.model_id != expected_model
            or returned_model != expected_model
            or returned_dimensions != expected_dimensions
            or not isinstance(vectors, list)
            or not vectors
        ):
            raise KernelError(
                "RETRIEVAL_EMBEDDING_OUTPUT_IDENTITY_MISMATCH",
                "retrieval Provider output differs from its frozen model/dimensions",
            )
        for vector in vectors:
            if not isinstance(vector, list) or len(vector) != expected_dimensions:
                raise KernelError(
                    "RETRIEVAL_EMBEDDING_OUTPUT_IDENTITY_MISMATCH",
                    "retrieval Provider vector differs from frozen dimensions",
                )
            numeric = [float(value) for value in vector]
            norm = math.sqrt(sum(value * value for value in numeric))
            if (
                not all(math.isfinite(value) for value in numeric)
                or not 0.99 <= norm <= 1.01
            ):
                raise KernelError(
                    "RETRIEVAL_EMBEDDING_VECTOR_INVALID",
                    "retrieval Provider vector must be finite, non-placeholder, and L2-normalized",
                )

    def _request_timeout_seconds(self, request: ChapterHandlerRequest) -> int:
        """CONSTRAINT: Bind Provider time to the frozen Operation policy, not its lease."""
        runtime = get_database_runtime(self.database_url)
        with runtime.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT definition_snapshot->'timeout_policy'
                           ->>'operation_timeout_seconds'
                    FROM authority_operation
                    WHERE operation_id=%s AND project_id=%s
                    """,
                    [request.operation_id, request.project_id],
                )
                row = cursor.fetchone()
        if row is None:
            raise KernelError("OPERATION_NOT_FOUND", "operation does not exist")
        try:
            timeout_seconds = int(row[0] or 0)
        except (TypeError, ValueError) as exc:
            raise KernelError(
                "CHAPTER_PROVIDER_TIMEOUT_POLICY_INVALID",
                "frozen Chapter Operation timeout is invalid",
            ) from exc
        if timeout_seconds > 0:
            return timeout_seconds
        if self.agent_binding_required:
            raise KernelError(
                "CHAPTER_PROVIDER_TIMEOUT_POLICY_INVALID",
                "controlled Chapter execution requires a frozen Operation timeout",
            )
        # COMPATIBILITY: explicitly admitted development fixtures retain this path.
        return self.lease_seconds * 5

    def _execution_identity(
        self,
        request: ChapterHandlerRequest,
        *,
        stable_key: str,
    ) -> tuple[int, str]:

        runtime = get_database_runtime(self.database_url)
        with runtime.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT request_payload
                    FROM authority_external_effect
                    WHERE project_id=%s AND operation_id=%s
                      AND effect_type='model.invoke'
                      AND stable_idempotency_key=%s
                    """,
                    [request.project_id, request.operation_id, stable_key],
                )
                row = cursor.fetchone()
        if row is None:
            return request.fencing_token, request.worker_id or self.worker_id
        payload = row[0]
        metadata = (
            payload.get("_production_execution") if isinstance(payload, dict) else None
        )
        if not isinstance(metadata, dict):
            raise KernelError(
                "MODEL_EFFECT_EXECUTION_IDENTITY_INVALID",
                "replayed ExternalEffect has no frozen execution identity",
            )
        if str(metadata.get("attempt_id") or "") != request.attempt_id:
            raise KernelError(
                "MODEL_EFFECT_EXECUTION_IDENTITY_CONFLICT",
                "replayed ExternalEffect belongs to another Attempt",
            )
        try:
            fencing_token = int(metadata.get("fencing_token") or 0)
        except (TypeError, ValueError) as exc:
            raise KernelError(
                "MODEL_EFFECT_EXECUTION_IDENTITY_INVALID",
                "replayed ExternalEffect has an invalid execution fence",
            ) from exc
        if (
            not self.agent_binding_required
            and fencing_token == 0
            and request.fencing_token == 0
        ):
            return fencing_token, str(metadata.get("worker_id") or self.worker_id)
        if fencing_token <= 0 or fencing_token > request.fencing_token:
            raise KernelError(
                "MODEL_EFFECT_EXECUTION_IDENTITY_INVALID",
                "replayed ExternalEffect execution fence is not historical",
            )
        execution_worker_id = str(metadata.get("worker_id") or "")
        if not execution_worker_id:
            raise KernelError(
                "MODEL_EFFECT_EXECUTION_IDENTITY_INVALID",
                "replayed ExternalEffect has no original execution worker",
            )
        return fencing_token, execution_worker_id

    def record_result_evidence(
        self,
        request: ChapterHandlerRequest,
        *,
        stage: str,
        result: ModelProviderResult,
    ) -> None:

        execution = result.execution_evidence or {}
        execution_request = execution.get("execution_request")
        external_effect_id = (
            str(execution_request.get("external_effect_id") or "")
            if isinstance(execution_request, Mapping)
            else ""
        )
        self._record_model_call(
            request,
            stage,
            result,
            _model_log_ref(
                request.operation_id,
                request.attempt_id,
                stage,
                external_effect_id,
            ),
            external_effect_id=external_effect_id,
        )
        self._ensure_cost_evidence(
            request,
            stage,
            result,
            external_effect_id=external_effect_id,
        )

    def completed_effect_result(
        self, external_effect_id: str, project_id: str
    ) -> ModelProviderResult | None:

        runtime = get_database_runtime(self.database_url)
        with runtime.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT effect.status,
                           COALESCE(receipt.payload->'evidence', effect.reconciliation)
                    FROM authority_external_effect AS effect
                    LEFT JOIN LATERAL (
                        SELECT receipt.payload
                        FROM authority_external_receipt AS receipt
                        JOIN authority_external_effect_dispatch AS dispatch
                          ON dispatch.dispatch_id = receipt.dispatch_id
                        WHERE dispatch.external_effect_id = effect.external_effect_id
                        ORDER BY receipt.received_at DESC LIMIT 1
                    ) AS receipt ON TRUE
                    WHERE effect.external_effect_id = %s AND effect.project_id = %s
                    """,
                    [external_effect_id, project_id],
                )
                row = cursor.fetchone()
        if row is None or str(row[0]) != "SUCCEEDED":
            return None
        evidence = row[1]
        if not isinstance(evidence, dict) or not evidence:
            raise KernelError(
                "MODEL_EFFECT_EVIDENCE_INVALID",
                "successful model ExternalEffect has no durable result evidence",
            )
        return ModelProviderResult.from_evidence(dict(evidence))

    def _record_model_call(
        self,
        request: ChapterHandlerRequest,
        stage: str,
        result: ModelProviderResult,
        logical_ref: str,
        external_effect_id: str = "",
    ) -> None:
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
                asset_id=_model_call_asset_id(
                    request.operation_id,
                    request.attempt_id,
                    stage,
                    external_effect_id,
                ),
                asset_type="model_call_log",
                schema_version="model-call-log.v1",
                logical_ref=logical_ref,
                category="runs",
                output_key=_evidence_output_key(
                    f"model_call.{stage}", external_effect_id
                ),
                role="model_evidence",
                content={
                    "type": "model_call_log",
                    "operation_id": request.operation_id,
                    "attempt_id": request.attempt_id,
                    "project_id": request.project_id,
                    "stage": stage,
                    "trace_id": request.trace_id,
                    "external_effect_id": external_effect_id,
                    "target_lineage": self._target_lineage(request),
                    "context_bundle_asset_version_id": next(
                        (
                            item.asset_version_id
                            for item in request.inputs
                            if item.asset_type == "context_bundle"
                        ),
                        "",
                    ),
                    "provider_evidence": result.to_evidence(),
                },
                qualification_policy="model-call-evidence-v1",
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
            )
        )

    @staticmethod
    def _target_lineage(request: ChapterHandlerRequest) -> dict[str, str]:
        payload = (
            request.command.get("payload")
            if isinstance(request.command.get("payload"), dict)
            else request.command
        )
        return {
            "target_asset_version_id": str(
                payload.get("target_asset_version_id") or ""
            ),
            "target_content_hash": str(payload.get("target_content_hash") or ""),
            "generation_operation_id": str(
                payload.get("generation_operation_id") or ""
            ),
            "generator_operation_name": str(
                payload.get("generator_operation_name") or ""
            ),
        }

    def _record_failed_model_call(
        self,
        request: ChapterHandlerRequest,
        stage: str,
        *,
        dispatched: dict[str, Any],
        logical_ref: str,
        external_effect_id: str = "",
    ) -> None:
        try:
            self.query.require(project_id=request.project_id, logical_ref=logical_ref)
            return
        except KernelError as exc:
            if exc.code != "AUTHORITY_ASSET_NOT_FOUND":
                raise
        provider_evidence = dispatched.get("provider_evidence")
        evidence = (
            dict(provider_evidence) if isinstance(provider_evidence, dict) else {}
        )
        process = (
            (evidence.get("production_execution") or {}).get("process_evidence")
            if isinstance(evidence.get("production_execution"), dict)
            else {}
        )
        self.writer.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=request.operation_id,
                project_id=request.project_id,
                asset_id=_model_call_asset_id(
                    request.operation_id,
                    request.attempt_id,
                    stage,
                    external_effect_id,
                ),
                asset_type="model_call_log",
                schema_version="model-call-log.v1",
                logical_ref=logical_ref,
                category="runs",
                output_key=_evidence_output_key(
                    f"model_call.{stage}.failed.{request.attempt_id}",
                    external_effect_id,
                ),
                role="model_failure_evidence",
                content={
                    "type": "model_call_log",
                    "operation_id": request.operation_id,
                    "attempt_id": request.attempt_id,
                    "project_id": request.project_id,
                    "stage": stage,
                    "trace_id": request.trace_id,
                    "external_effect_id": external_effect_id,
                    "call_status": str(dispatched.get("outcome") or "").upper(),
                    "accepted_candidate": False,
                    "failure_code": str(
                        process.get("failure_code")
                        if isinstance(process, dict)
                        else "PROVIDER_FAILURE"
                    ),
                    "provider_evidence": evidence,
                },
                qualification_policy="model-call-failure-evidence-v1",
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
            )
        )

    def _record_failed_cost_evidence(
        self,
        request: ChapterHandlerRequest,
        stage: str,
        *,
        dispatched: dict[str, Any],
        usage: Mapping[str, Any],
        cost: Mapping[str, Any],
        external_effect_id: str = "",
    ) -> None:
        logical_ref = _cost_log_ref(
            request.operation_id,
            request.attempt_id,
            stage,
            external_effect_id,
        )
        try:
            self.query.require(project_id=request.project_id, logical_ref=logical_ref)
            return
        except KernelError as exc:
            if exc.code != "AUTHORITY_ASSET_NOT_FOUND":
                raise
        provider_evidence = dispatched.get("provider_evidence")
        provider = provider_evidence if isinstance(provider_evidence, dict) else {}
        accounting_basis = str(
            cost.get("accounting_basis") or self.cost_accounting_basis
        ).upper()
        cost_unknown = accounting_basis == "ACCOUNT_ENTITLEMENT"
        self.writer.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=request.operation_id,
                project_id=request.project_id,
                asset_id=_cost_ledger_asset_id(
                    request.operation_id,
                    request.attempt_id,
                    stage,
                    external_effect_id,
                ),
                asset_type="cost_ledger",
                schema_version="model-cost-ledger.v1",
                logical_ref=logical_ref,
                category="runs",
                output_key=_evidence_output_key(
                    f"cost_ledger.{stage}.failed.{request.attempt_id}",
                    external_effect_id,
                ),
                role="cost_failure_evidence",
                content={
                    "type": "cost_ledger",
                    "operation_id": request.operation_id,
                    "attempt_id": request.attempt_id,
                    "project_id": request.project_id,
                    "stage": stage,
                    "trace_id": request.trace_id,
                    "external_effect_id": external_effect_id,
                    "availability": "UNAVAILABLE" if cost_unknown else "AVAILABLE",
                    "measurement": "UNKNOWN" if cost_unknown else str(cost.get("measurement") or "MEASURED"),
                    "amount": None if cost_unknown else str(cost.get("amount") or "0"),
                    "currency": (
                        "UNKNOWN"
                        if cost_unknown
                        else str(cost.get("currency") or "USD")
                    ),
                    "accounting_basis": accounting_basis,
                    "cost_status": "UNKNOWN" if cost_unknown else "KNOWN",
                    "provider_id": str(provider.get("provider_id") or ""),
                    "model_id": str(provider.get("model_id") or ""),
                    "total_tokens": int(usage.get("total_tokens") or 0),
                    "usage": dict(usage),
                    "cost": dict(cost),
                    "pricing_ref": str(cost.get("pricing_ref") or ""),
                    "pricing_snapshot_hash": str(
                        cost.get("pricing_snapshot_hash") or ""
                    ),
                    "calculation_basis": dict(cost.get("calculation_basis") or {}),
                    "estimated": bool(cost.get("estimated", False)),
                    "provider_billed": (
                        "UNKNOWN"
                        if cost_unknown
                        else bool(cost.get("provider_billed", False))
                    ),
                    "execution_outcome": str(dispatched.get("outcome") or "").upper(),
                    "accepted_candidate": False,
                },
                qualification_policy="model-cost-failure-evidence-v1",
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
                reference_asset_ids=(
                    _model_call_asset_id(
                        request.operation_id,
                        request.attempt_id,
                        stage,
                        external_effect_id,
                    ),
                ),
            )
        )

    def _ensure_cost_evidence(
        self,
        request: ChapterHandlerRequest,
        stage: str,
        result: ModelProviderResult,
        external_effect_id: str = "",
    ) -> None:
        logical_ref = _cost_log_ref(
            request.operation_id,
            request.attempt_id,
            stage,
            external_effect_id,
        )
        try:
            self.query.require(project_id=request.project_id, logical_ref=logical_ref)
            return
        except KernelError as exc:
            if exc.code != "AUTHORITY_ASSET_NOT_FOUND":
                raise
        cost_evidence = dict(result.cost_evidence or {})
        accounting_basis = str(
            cost_evidence.get("accounting_basis") or self.cost_accounting_basis
        ).upper()
        cost_unknown = accounting_basis == "ACCOUNT_ENTITLEMENT"
        self.writer.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=request.operation_id,
                project_id=request.project_id,
                asset_id=_cost_ledger_asset_id(
                    request.operation_id,
                    request.attempt_id,
                    stage,
                    external_effect_id,
                ),
                asset_type="cost_ledger",
                schema_version="model-cost-ledger.v1",
                logical_ref=logical_ref,
                category="runs",
                output_key=_evidence_output_key(
                    f"cost_ledger.{stage}", external_effect_id
                ),
                role="cost_evidence",
                content={
                    "type": "cost_ledger",
                    "operation_id": request.operation_id,
                    "attempt_id": request.attempt_id,
                    "project_id": request.project_id,
                    "stage": stage,
                    "trace_id": request.trace_id,
                    "external_effect_id": external_effect_id,
                    "availability": "UNAVAILABLE" if cost_unknown else "AVAILABLE",
                    "measurement": "UNKNOWN" if cost_unknown else str(cost_evidence.get("measurement") or "MEASURED"),
                    "amount": None if cost_unknown else result.cost_amount,
                    "currency": "UNKNOWN" if cost_unknown else result.currency,
                    "accounting_basis": accounting_basis,
                    "cost_status": "UNKNOWN" if cost_unknown else "KNOWN",
                    "provider_id": result.provider_id,
                    "model_id": result.model_id,
                    "total_tokens": result.total_tokens,
                    "usage": dict(result.usage_evidence or {}),
                    "cost": cost_evidence,
                    "pricing_ref": str(
                        (result.cost_evidence or {}).get("pricing_ref") or ""
                    ),
                    "pricing_snapshot_hash": str(
                        (result.cost_evidence or {}).get("pricing_snapshot_hash") or ""
                    ),
                    "calculation_basis": dict(
                        (result.cost_evidence or {}).get("calculation_basis") or {}
                    ),
                    "estimated": bool(
                        (result.cost_evidence or {}).get("estimated", False)
                    ),
                    "provider_billed": (
                        "UNKNOWN"
                        if cost_unknown
                        else bool(cost_evidence.get("provider_billed", False))
                    ),
                },
                qualification_policy="model-cost-evidence-v1",
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
                reference_asset_ids=(
                    _model_call_asset_id(
                        request.operation_id,
                        request.attempt_id,
                        stage,
                        external_effect_id,
                    ),
                ),
            )
        )


def _evidence_instance_token(external_effect_id: str) -> str:
    return (
        hashlib.sha256(external_effect_id.encode("utf-8")).hexdigest()[:20]
        if external_effect_id
        else ""
    )


def _evidence_output_key(base: str, external_effect_id: str) -> str:
    token = _evidence_instance_token(external_effect_id)
    return f"{base}.{token}" if token else base


def _model_call_asset_id(
    operation_id: str,
    attempt_id: str,
    stage: str,
    external_effect_id: str = "",
) -> str:
    base = f"model-call:{operation_id}:{attempt_id}:{stage}"
    token = _evidence_instance_token(external_effect_id)
    return f"{base}:{token}" if token else base


def _cost_ledger_asset_id(
    operation_id: str,
    attempt_id: str,
    stage: str,
    external_effect_id: str = "",
) -> str:
    base = f"cost-ledger:{operation_id}:{attempt_id}:{stage}"
    token = _evidence_instance_token(external_effect_id)
    return f"{base}:{token}" if token else base


def _model_log_ref(
    operation_id: str,
    attempt_id: str,
    stage: str,
    external_effect_id: str = "",
) -> str:
    token = _evidence_instance_token(external_effect_id)
    suffix = f"-{token}" if token else ""
    return f"runs/model_calls/{operation_id}-{attempt_id}-{stage}{suffix}.json"


def model_call_log_ref(
    operation_id: str,
    attempt_id: str,
    stage: str,
    external_effect_id: str = "",
) -> str:

    return _model_log_ref(operation_id, attempt_id, stage, external_effect_id)


def _cost_log_ref(
    operation_id: str,
    attempt_id: str,
    stage: str,
    external_effect_id: str = "",
) -> str:
    token = _evidence_instance_token(external_effect_id)
    suffix = f"-{token}" if token else ""
    return f"runs/cost_ledgers/{operation_id}-{attempt_id}-{stage}{suffix}.json"


def _raise_model_effect_failure(dispatched: dict[str, Any]) -> None:
    outcome = str(dispatched.get("outcome") or "unknown")
    provider_evidence = dispatched.get("provider_evidence")
    evidence = provider_evidence if isinstance(provider_evidence, dict) else {}
    production_execution = evidence.get("production_execution")
    process_evidence = (
        production_execution.get("process_evidence")
        if isinstance(production_execution, dict)
        else None
    )
    failure = process_evidence if isinstance(process_evidence, dict) else evidence
    failure_code = str(failure.get("failure_code") or "PROVIDER_FAILURE").upper()
    failure_message = str(
        failure.get("failure_message")
        or failure.get("message")
        or "model effect did not complete successfully"
    )
    if outcome in {"unknown", "ambiguous"}:
        raise KernelError(
            "MODEL_EFFECT_OUTCOME_UNKNOWN",
            f"{failure_code}: {failure_message}",
        )
    if outcome in {"retryable_failure", "not_found"}:
        code = (
            "MODEL_EFFECT_TIMEOUT"
            if failure_code == "PROCESS_TIMEOUT"
            else f"MODEL_EFFECT_RETRYABLE_{failure_code}"
        )
        raise KernelError(code, failure_message)
    if outcome in {"final_failure", "failed_final", "cancelled"}:
        raise KernelError(
            f"MODEL_EFFECT_FINAL_{failure_code}",
            failure_message,
        )
    raise KernelError(
        "MODEL_EFFECT_OUTCOME_INVALID",
        f"unexpected ExternalEffect outcome {outcome}: {failure_code}",
    )


def _failed_provider_measurement(
    dispatched: Mapping[str, Any],
) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    provider = dispatched.get("provider_evidence")
    production = (
        provider.get("production_execution") if isinstance(provider, Mapping) else None
    )
    process = (
        production.get("process_evidence") if isinstance(production, Mapping) else None
    )
    usage = process.get("usage") if isinstance(process, Mapping) else None
    cost = process.get("cost") if isinstance(process, Mapping) else None
    if (
        not isinstance(usage, Mapping)
        or not isinstance(cost, Mapping)
        or str(usage.get("availability") or "").upper() != "AVAILABLE"
        or str(usage.get("measurement") or "").upper() not in {"MEASURED", "PROVIDER_REPORTED"}
        or str(cost.get("availability") or "").upper() != "AVAILABLE"
    ):
        return None
    token_values: list[int] = []
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = usage.get(key)
        if value is None or value == "":
            token_values.append(0)
            continue
        if isinstance(value, bool):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        if parsed < 0:
            return None
        token_values.append(parsed)
    measured_tokens = max(token_values[2], token_values[0] + token_values[1])
    if measured_tokens <= 0:
        return None
    try:
        measured_amount = Decimal(str(cost.get("amount") or ""))
    except (InvalidOperation, ValueError):
        return None
    if not measured_amount.is_finite() or measured_amount < 0:
        return None
    return {**dict(usage), "total_tokens": measured_tokens}, cost


def _object(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise KernelError(
            "MODEL_EFFECT_INPUT_INVALID", f"model input {key} must be an object"
        )
    return value


def _decode_agent_json_envelope(
    value: Any, *, field: str, allow_empty: bool
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise KernelError(
            "MODEL_RESPONSE_INVALID", f"Agent {field} envelope is missing"
        )
    if "payload_json" not in value:
        decoded = dict(value)
        if decoded or allow_empty:
            return decoded
        raise KernelError(
            "MODEL_RESPONSE_INVALID", f"Agent {field} must decode to an object"
        )
    payload_json = value.get("payload_json")
    if not isinstance(payload_json, str):
        raise KernelError(
            "MODEL_RESPONSE_INVALID", f"Agent {field} payload_json is missing"
        )
    try:
        decoded = json.loads(payload_json)
    except json.JSONDecodeError as exc:
        raise KernelError(
            "MODEL_RESPONSE_INVALID", f"Agent {field} payload_json is invalid"
        ) from exc
    if not isinstance(decoded, dict) or (not decoded and not allow_empty):
        raise KernelError(
            "MODEL_RESPONSE_INVALID", f"Agent {field} must decode to an object"
        )
    return decoded


def _normalize_model_output(stage: str, raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise KernelError("MODEL_RESPONSE_INVALID", "model response must be an object")
    if stage == "draft":
        text = str(raw.get("text") or "").strip()
        if not text:
            raise KernelError("MODEL_RESPONSE_INVALID", "draft response has no text")
        return {"text": text, "scene_artifacts": raw.get("scene_artifacts", [])}
    if stage == "agent_session":
        message = str(raw.get("message") or "").strip()
        action = str(raw.get("action") or "").strip().upper()
        tool_call = raw.get("tool_call")
        final_response = raw.get("final_response")
        if not message or action not in {"TOOL_CALL", "FINAL"}:
            raise KernelError(
                "MODEL_RESPONSE_INVALID",
                "Agent model turn requires a message and one explicit action",
            )
        if action == "TOOL_CALL":
            if not isinstance(tool_call, dict) or final_response is not None:
                raise KernelError(
                    "MODEL_RESPONSE_INVALID",
                    "Agent Tool action requires exactly one typed Tool call",
                )
            arguments = _decode_agent_json_envelope(
                tool_call.get("arguments"), field="Tool arguments", allow_empty=True
            )
            normalized_call = {
                "tool_name": str(tool_call.get("tool_name") or "").strip(),
                "arguments": arguments,
                "reason": str(tool_call.get("reason") or "").strip(),
            }
            if not normalized_call["tool_name"] or not normalized_call["reason"]:
                raise KernelError(
                    "MODEL_RESPONSE_INVALID", "Agent Tool call is incomplete"
                )
            return {
                "message": message,
                "action": action,
                "tool_call": normalized_call,
                "final_response": None,
            }
        if (
            tool_call is not None
            or not isinstance(final_response, dict)
            or not final_response
        ):
            raise KernelError(
                "MODEL_RESPONSE_INVALID",
                "Agent final action requires exactly one non-empty response",
            )
        return {
            "message": message,
            "action": action,
            "tool_call": None,
            "final_response": _decode_agent_json_envelope(
                final_response, field="final response", allow_empty=False
            ),
        }
    if stage == "narrative_semantic_evaluation":
        return dict(raw)
    if stage == "retrieval":
        vectors = raw.get("vectors")
        dimensions = int(raw.get("embedding_dimensions") or 0)
        if (
            not isinstance(vectors, list)
            or not vectors
            or dimensions <= 0
            or any(
                not isinstance(vector, list) or len(vector) != dimensions
                for vector in vectors
            )
        ):
            raise KernelError(
                "MODEL_RESPONSE_INVALID",
                "retrieval embedding response has invalid vector dimensions",
            )
        return {
            "vectors": [[float(value) for value in vector] for vector in vectors],
            "embedding_model": str(raw.get("embedding_model") or ""),
            "embedding_dimensions": dimensions,
        }
    if stage == "retrieval_query_expansion":
        return dict(raw)
    if stage in {"review", "rereview"}:
        score_value = raw.get("score")
        if not isinstance(score_value, (int, float)) or isinstance(score_value, bool):
            raise KernelError(
                "MODEL_RESPONSE_INVALID", "review response has no numeric score"
            )
        score = float(score_value)
        issues = raw.get("issues")
        if not isinstance(issues, list):
            raise KernelError(
                "MODEL_RESPONSE_INVALID", "review response has no issue list"
            )
        normalized: list[dict[str, str]] = []
        for item in issues:
            if not isinstance(item, dict):
                raise KernelError(
                    "MODEL_RESPONSE_INVALID", "review issue must be an object"
                )
            code = str(item.get("code") or item.get("dimension") or "").strip().upper()
            severity = _review_severity(str(item.get("severity") or ""))
            message = str(item.get("message") or "").strip()
            if not code or not message:
                raise KernelError(
                    "MODEL_RESPONSE_INVALID", "review issue identity is incomplete"
                )
            normalized.append(
                {**item, "code": code, "severity": severity, "message": message}
            )
        decision = "NEEDS_REVISION" if normalized or score < 80 else "PASSED"
        return {
            "decision": decision,
            "score": score,
            "issues": normalized,
            **(
                {
                    "diagnostic_contract_version": "actionable-diagnostics.v1",
                    "resolution_checks": raw["resolution_checks"],
                }
                if "resolution_checks" in raw
                else {}
            ),
            **({"knowledge_checks": raw["knowledge_checks"]} if "knowledge_checks" in raw else {}),
            **({"craft_checks": raw["craft_checks"]} if "craft_checks" in raw else {}),
            **({"craft_preservation_checks": raw["craft_preservation_checks"]} if "craft_preservation_checks" in raw else {}),
            **({"preservation_checks": raw["preservation_checks"]} if "preservation_checks" in raw else {}),
        }
    if stage in {"memo", "canon_support"}:
        return dict(raw)
    if stage == "canon_extraction":
        from .provider_output_contracts import (
            canon_provider_array_fields,
            validate_chapter_provider_output_semantics,
        )

        raw = validate_chapter_provider_output_semantics(stage, raw)
        fields = canon_provider_array_fields()
        normalized_extraction: dict[str, list[dict[str, Any]]] = {}
        for field in fields:
            values = raw.get(field)
            if not isinstance(values, list) or any(
                not isinstance(item, dict) for item in values
            ):
                raise KernelError(
                    "MODEL_RESPONSE_INVALID",
                    f"Canon semantic extraction field {field} must be an array of objects",
                )
            normalized_extraction[field] = [dict(item) for item in values]
        if (
            not any(normalized_extraction.values())
            and raw.get("extraction_status") != "NO_CHANGE"
        ):
            raise KernelError(
                "MODEL_RESPONSE_INVALID",
                "Canon semantic extraction cannot be empty on the Provider path",
            )
        return {
            **normalized_extraction,
            **{
                key: raw[key]
                for key in ("extraction_status", "no_change_reason")
                if key in raw
            },
        }
    if stage.startswith("quality_"):
        dimensions = raw.get("dimensions")
        if not isinstance(dimensions, list) or not dimensions:
            raise KernelError(
                "MODEL_RESPONSE_INVALID", "quality response has no dimension evidence"
            )
        normalized_dimensions: list[dict[str, Any]] = []
        for item in dimensions:
            if not isinstance(item, dict):
                raise KernelError(
                    "MODEL_RESPONSE_INVALID", "quality dimension must be an object"
                )
            dimension = str(item.get("dimension") or "").strip()
            status = str(item.get("gate_status") or "").strip().upper()
            confidence = item.get("confidence")
            locations = item.get("evidence_locations")
            score = item.get("score")
            if not dimension or status not in {
                "PASSED",
                "PASSED_WITH_WARNINGS",
                "FAILED",
                "INSUFFICIENT_EVIDENCE",
                "REQUIRES_HUMAN_REVIEW",
            }:
                raise KernelError(
                    "MODEL_RESPONSE_INVALID",
                    "quality dimension identity or status is invalid",
                )
            if (
                not isinstance(confidence, (int, float))
                or isinstance(confidence, bool)
                or not 0 <= float(confidence) <= 1
            ):
                raise KernelError(
                    "MODEL_RESPONSE_INVALID",
                    "quality confidence must be between zero and one",
                )
            if (
                not isinstance(locations, list)
                or any(
                    not isinstance(location, dict) or not location
                    for location in locations
                )
                or (status in {"PASSED", "FAILED"} and not locations)
            ):
                raise KernelError(
                    "MODEL_RESPONSE_INVALID",
                    "quality decision requires evidence locations",
                )
            if score is not None and (
                not isinstance(score, (int, float))
                or isinstance(score, bool)
                or not 0 <= float(score) <= 100
            ):
                raise KernelError(
                    "MODEL_RESPONSE_INVALID",
                    "quality score must be between zero and one hundred",
                )
            normalized_dimensions.append(
                {
                    "dimension": dimension,
                    "gate_status": status,
                    "score": score,
                    "confidence": float(confidence),
                    "evidence_locations": locations,
                    "issue_codes": list(item.get("issue_codes") or []),
                    "revision_strategies": list(item.get("revision_strategies") or []),
                }
            )
        return {"dimensions": normalized_dimensions}
    if stage == "reader_outcome":
        state = raw.get("reader_state")
        evidence = raw.get("evidence")
        required = (
            "continue_intent",
            "curiosity",
            "satisfaction",
            "confusion",
            "trust",
            "character_attachment",
            "antagonist_pressure",
            "promise_expectation",
            "payoff_satisfaction",
            "drop_risk",
            "repetition_fatigue",
        )
        if (
            not isinstance(state, dict)
            or not isinstance(evidence, list)
            or not evidence
        ):
            raise KernelError(
                "MODEL_RESPONSE_INVALID",
                "Reader Outcome response requires reader_state and evidence",
            )
        normalized_state: dict[str, float] = {}
        for dimension in required:
            value = state.get(dimension)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0 <= float(value) <= 1
            ):
                raise KernelError(
                    "MODEL_RESPONSE_INVALID",
                    f"Reader Outcome dimension {dimension} must be between zero and one",
                )
            normalized_state[dimension] = float(value)
        if any(not isinstance(item, dict) or not item for item in evidence):
            raise KernelError(
                "MODEL_RESPONSE_INVALID", "Reader Outcome evidence must contain objects"
            )
        return {
            "reader_state": normalized_state,
            "evidence": [dict(item) for item in evidence],
        }
    text = str(raw.get("text") or raw.get("revised_text") or "")
    if "edits" not in raw:
        text = text.strip()
    resolved = [
        str(item).strip()
        for item in raw.get("resolved_issue_codes", [])
        if str(item).strip()
    ]
    if not text:
        raise KernelError(
            "MODEL_RESPONSE_INVALID", "revision response has no revised text"
        )
    return {
        "text": text,
        "resolved_issue_codes": resolved,
        "scene_artifacts": raw.get("scene_artifacts", []),
        **({"edits": raw["edits"]} if "edits" in raw else {}),
    }


def normalize_model_output(stage: str, raw: dict[str, Any]) -> dict[str, Any]:

    return _normalize_model_output(stage, raw)


def _review_severity(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"critical", "blocker", "blocking", "high"}:
        return "blocking"
    if normalized in {"major", "medium"}:
        return "major"
    return "minor"


__all__ = [
    "ChapterAgentBindingRecorder",
    "ChapterModelPort",
    "ExternalEffectChapterModelPort",
    "ModelProviderResult",
    "model_call_log_ref",
    "normalize_model_output",
]
