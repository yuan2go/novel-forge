"""Generic ExternalEffect-backed model boundary for chapter handlers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Protocol

from novel_forge.infrastructure.environment import RuntimeEnvironment
from novel_forge.modules.chapter_authority.contracts import (
    ChapterHandlerRequest,
    resolve_stage_context_token_budget,
)
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
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
from novel_forge.modules.command_kernel.budget_runtime import (
    BudgetReservationRequest,
    reserve_provider_budget,
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
    ProviderControlLevel,
)
from novel_forge.modules.production_execution.contracts import ExecutionRecoveryAction


AGENT_MODEL_STAGES = frozenset(
    {
        "draft",
        "review",
        "revision",
        "rereview",
        "canon_extraction",
        "quality_structural",
        "quality_commercial",
        "quality_source_originality",
        "quality_longform",
        "quality_platform",
    }
)


class LegacyChapterModelAdapter(Protocol):
    name: str

    def generate(
        self, prompt: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    def analyze(
        self, text: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    def review(
        self, content: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    def revise(
        self,
        content: str,
        review: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


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


class ChapterModelPort(Protocol):
    def invoke(
        self,
        request: ChapterHandlerRequest,
        *,
        stage: str,
        payload: dict[str, Any],
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


@dataclass(frozen=True, slots=True)
class ChapterModelRoute:
    adapter: LegacyChapterModelAdapter
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
    """Test/development compatibility adapter for pre-PEP Chapter routes.

    The production composition root does not construct this adapter.  Keeping it
    available makes old fixtures replayable while the explicit environment guard
    prevents it from becoming a controlled-environment fallback.
    """

    provider = "novel_forge_model_gateway_v1"
    reconciliation_mode = "unsupported"
    legacy_compatibility_only = True
    legacy_independent_execution = True
    production_execution_gateway_backed = False
    capability_profile = ProviderCapabilityProfile(
        provider=provider,
        control_level=ProviderControlLevel.LEGACY_UNCONTROLLED,
        supports_request_timeout=False,
        supports_provider_idempotency=False,
        supports_query=False,
        supports_cancel=False,
        supports_callback=False,
        supports_usage_receipt=True,
        supports_cost_receipt=True,
        reconciliation_mode="unsupported",
        real_provider_validation_eligible=False,
    )

    def __init__(
        self,
        routes: dict[str, ChapterModelRoute],
        *,
        environment: str = "test",
    ) -> None:
        unsupported = set(routes) - {
            "draft",
            "review",
            "revision",
            "rereview",
            "canon_extraction",
            "quality_structural",
            "quality_commercial",
            "quality_source_originality",
            "quality_longform",
            "quality_platform",
            "reader_outcome",
        }
        if not routes or unsupported:
            raise ValueError("chapter model routes contain unsupported stages")
        self.routes = dict(routes)
        self.environment = environment.strip().lower() or "development"

    def execute(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        self._assert_legacy_execution_allowed()
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
            if stage.startswith("quality_"):
                requested_dimensions = inputs.get("dimensions")
                returned_dimensions = [
                    str(item.get("dimension") or "") for item in output["dimensions"]
                ]
                if (
                    not isinstance(requested_dimensions, list)
                    or len(returned_dimensions) != len(set(returned_dimensions))
                    or set(returned_dimensions)
                    != {str(item) for item in requested_dimensions}
                ):
                    raise KernelError(
                        "MODEL_RESPONSE_INVALID",
                        "quality response dimensions must exactly match the frozen contract",
                    )
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
        self._assert_legacy_execution_allowed()
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

    def cancel(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
        provider_request_id: str,
    ) -> ProviderResult:
        self._assert_legacy_execution_allowed()
        stage, route, _inputs = self._request(capability, request_payload)
        return ProviderResult(
            "ambiguous",
            provider_request_id or f"model-cancel:{stable_idempotency_key}",
            {
                "cancel_capability_not_established": True,
                "manual_resolution_required": True,
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
        route = self.routes.get(stage)
        if stage == "rereview" and route is None:
            route = self.routes.get("review")
        if capability != f"model.{stage}" or route is None:
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
        return stage, route, inputs

    def model_id_for_stage(self, stage: str) -> str:
        route = self.routes.get(stage)
        if stage == "rereview" and route is None:
            route = self.routes.get("review")
        return "" if route is None else route.model_id

    def _assert_legacy_execution_allowed(self) -> None:
        if RuntimeEnvironment.parse(self.environment).controlled:
            raise ExternalEffectAdapterError(
                "legacy Chapter model execution is blocked in controlled environments; "
                "use ProductionExecutionGatewayExternalEffectAdapter",
                request_sent=False,
            )

    @staticmethod
    def _call(
        adapter: LegacyChapterModelAdapter,
        stage: str,
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        if stage == "draft":
            plan = _object(inputs, "plan")
            context = _object(inputs, "context")
            style = _object(inputs, "style")
            prompt = (
                f"Write chapter {plan.get('chapter', '')}: {plan.get('title', '')}\n"
                f"Premise: {plan.get('premise', '')}\n"
                f"Objective: {plan.get('chapter_objective', '')}\n"
                f"Scenes: {plan.get('scene_sequence', [])}\n"
                f"Conflict: {plan.get('conflict_chain', [])}\n"
                f"Reveals: {plan.get('information_reveals', [])}\n"
                f"Promise actions: {plan.get('reader_promise_actions', [])}\n"
                f"Reward setup/payoff: {plan.get('reward_setup', [])} / {plan.get('reward_payoff', [])}\n"
                f"Hook: {plan.get('chapter_hook', '')}"
            )
            return adapter.generate(
                prompt,
                {"draft_context_view": context, "draft_style_view": style},
            )
        if stage in {"review", "rereview"}:
            draft = _object(inputs, "draft")
            return adapter.review(
                str(draft.get("text") or ""),
                {
                    "rubric": (
                        "chapter-authority-rereview-v1"
                        if stage == "rereview" or "revision" in inputs
                        else "chapter-authority-review-v1"
                    ),
                    "initial_review": inputs.get("review", {}),
                },
            )
        if stage == "canon_extraction":
            revision = _object(inputs, "revision")
            context = _object(inputs, "context")
            prompt = (
                "Extract Canon semantic changes as a JSON object matching "
                "canon-semantic-extraction-v2. Return arrays for canon_facts, "
                "character_state_changes, relationship_changes, timeline_events, "
                "foreshadow_changes, promise_changes, reward_changes, world_rule_usages, "
                "power_state_changes, narrative_pattern_fingerprints, theme_movements, "
                "and antagonist_pressure_changes. Every item must cite evidence_start, "
                "evidence_end and confidence.\nRevision:\n"
                + str(revision.get("text") or "")
            )
            return adapter.generate(
                prompt,
                {
                    "contract_version": "canon-semantic-extraction-v2",
                    "context": context,
                },
            )
        if stage.startswith("quality_"):
            revision = _object(inputs, "revision")
            quality_context = _object(inputs, "quality_context")
            group = stage.removeprefix("quality_")
            dimensions = inputs.get("dimensions")
            if not isinstance(dimensions, list) or not dimensions:
                raise ExternalEffectAdapterError(
                    "quality judge requires an explicit dimension contract",
                    request_sent=False,
                )
            prompt = (
                "Evaluate only the requested chapter quality dimensions. Return JSON "
                "{dimensions:[{dimension,gate_status,score,evidence_locations,confidence,"
                "issue_codes,revision_strategies}]}. Use PASSED only when the chapter "
                "contains direct evidence; otherwise use INSUFFICIENT_EVIDENCE or FAILED. "
                "Every dimension must include at least one concrete evidence location, "
                "including policy-compliance dimensions.\n"
                f"Group: {group}\nDimensions: {dimensions}\nGoverned context:\n"
                + str(quality_context)
            )
            return adapter.generate(
                prompt,
                {
                    "contract_version": "chapter-quality-provider-evidence-v2",
                    "group": group,
                    "dimensions": dimensions,
                    "quality_context": quality_context,
                },
            )
        if stage == "reader_outcome":
            assets = _object(inputs, "assets")
            prompt = (
                "Evaluate the frozen chapter from the reader-outcome perspective. "
                "Return JSON {reader_state:{continue_intent,curiosity,satisfaction,"
                "confusion,trust,character_attachment,antagonist_pressure,"
                "promise_expectation,payoff_satisfaction,drop_risk,"
                "repetition_fatigue},evidence:[{asset_version_id,location,claim}]}. "
                "All reader-state values must be numbers from zero to one."
            )
            return adapter.generate(
                prompt,
                {
                    "contract_version": "reader-outcome-provider-v1",
                    "chapter": inputs.get("chapter"),
                    "book_id": inputs.get("book_id"),
                    "assets": assets,
                },
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

    def invoke(
        self,
        request: ChapterHandlerRequest,
        *,
        stage: str,
        payload: dict[str, Any],
    ) -> ModelProviderResult:
        if stage not in AGENT_MODEL_STAGES | {"reader_outcome"}:
            raise KernelError(
                "MODEL_EFFECT_STAGE_UNSUPPORTED", f"unsupported model stage: {stage}"
            )
        logical_ref = _model_log_ref(request.operation_id, request.attempt_id, stage)
        business_payload = (
            request.command.get("payload")
            if isinstance(request.command.get("payload"), dict)
            else request.command
        )
        context = EffectCommandContext(
            operation_id=request.operation_id,
            project_id=request.project_id,
            actor_id=request.worker_id or self.worker_id,
            trace_id=request.trace_id,
            correlation_id=request.correlation_id,
        )
        stable_key = f"{request.operation_id}:{request.attempt_id}:{stage}:attempt-v1"
        execution_fencing_token, execution_worker_id = self._execution_identity(
            request,
            stable_key=stable_key,
        )
        effect_request_payload = {
            "stage": stage,
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
                "route_provider": str(
                    getattr(
                        self.adapter,
                        "provider_id_for_stage",
                        lambda _stage: self.adapter.provider,
                    )(stage)
                ),
                "execution_binding_domain": self.execution_binding_domain,
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
        if self.agent_binding_required and binder is None:
            raise KernelError(
                "CHAPTER_CAPABILITY_PREFLIGHT_REQUIRED",
                "controlled Chapter model node has no Capability contract binder",
            )
        if binder is not None:
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
            if preflight is not None:
                metadata = dict(effect_request_payload["_production_execution"])
                frozen_artifacts = list(metadata["input_artifacts"])
                frozen_artifacts.append(preflight.materialization_artifact.to_dict())
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
            model_id=str(
                getattr(self.adapter, "model_id_for_stage", lambda _stage: "")(stage)
            ),
            request_timeout_seconds=self.lease_seconds * 5,
            reconciliation_mode=str(self.adapter.reconciliation_mode),
            provider_capability_profile=(
                self.adapter.capability_profile.to_dict()
                if isinstance(
                    self.adapter.capability_profile, ProviderCapabilityProfile
                )
                else dict(self.adapter.capability_profile)
            ),
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
                provider=self.adapter.provider,
                currency="USD",
                estimated_amount=self.max_cost_per_call,
                estimated_tokens=resolve_stage_context_token_budget(
                    business_payload, stage, default=0
                ),
                chapter=int(
                    business_payload.get("chapter_number")
                    or business_payload.get("chapter")
                    or 0
                )
                or None,
                caps=self.budget_caps,
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
                        # ExternalEffect keeps its original execution identity.
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
            # Explicit development compatibility path; never a silent fallback.
            recorder = self.agent_binding_recorder
            if recorder is not None:
                recorder.record_compatibility_usage(request, stage=stage)
        completed = self.completed_effect_result(
            str(effect["external_effect_id"]), request.project_id
        )
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
            settle_provider_budget(
                self.database_url,
                reservation_id=str(reservation["reservation_id"]),
                project_id=request.project_id,
                actual_amount=completed.cost_amount,
                actual_tokens=completed.total_tokens,
                evidence={
                    "provider_id": completed.provider_id,
                    "model_id": completed.model_id,
                    "real_model_call": completed.real_model_call,
                    "fixture": not completed.real_model_call,
                    "recovered_completed_effect": True,
                },
            )
            self._record_model_call(request, stage, completed, logical_ref)
            self._ensure_cost_evidence(request, stage, completed)
            if frozen_work_order is not None and execution_binding is not None:
                self.agent_binding_recorder.accept_candidate(
                    frozen_work_order,
                    result=completed,
                    execution_binding=execution_binding,
                )
            return completed
        try:
            dispatched = dispatch_external_effect(
                self.database_url,
                context,
                effect_id=effect["external_effect_id"],
                worker_id=request.worker_id or self.worker_id,
                lease_seconds=self.lease_seconds,
                adapter=effect_adapter,
            )
        except KernelError:
            resolve_provider_budget_failure(
                self.database_url,
                reservation_id=str(reservation["reservation_id"]),
                project_id=request.project_id,
            )
            raise
        if dispatched["outcome"] != "success":
            measurement = _failed_provider_measurement(dispatched)
            if measurement is None:
                resolve_provider_budget_failure(
                    self.database_url,
                    reservation_id=str(reservation["reservation_id"]),
                    project_id=request.project_id,
                )
            else:
                usage, cost = measurement
                settle_provider_budget(
                    self.database_url,
                    reservation_id=str(reservation["reservation_id"]),
                    project_id=request.project_id,
                    actual_amount=str(cost.get("amount") or "0"),
                    actual_tokens=int(usage.get("total_tokens") or 0),
                    evidence={
                        "provider_id": str(
                            (dispatched.get("provider_evidence") or {}).get(
                                "provider_id"
                            )
                            or ""
                        ),
                        "model_id": str(cost.get("model") or ""),
                        "real_model_call": True,
                        "execution_outcome": str(dispatched["outcome"]).upper(),
                        "accepted_candidate": False,
                    },
                )
                self._record_failed_model_call(
                    request,
                    stage,
                    dispatched=dispatched,
                    logical_ref=logical_ref,
                )
                self._record_failed_cost_evidence(
                    request,
                    stage,
                    dispatched=dispatched,
                    usage=usage,
                    cost=cost,
                )
            _raise_model_effect_failure(dispatched)
        result = ModelProviderResult.from_evidence(
            dict(dispatched["provider_evidence"])
        )
        self.fault_injector("after_provider_success")
        settle_provider_budget(
            self.database_url,
            reservation_id=str(reservation["reservation_id"]),
            project_id=request.project_id,
            actual_amount=result.cost_amount,
            actual_tokens=result.total_tokens,
            evidence={
                "provider_id": result.provider_id,
                "model_id": result.model_id,
                "real_model_call": result.real_model_call,
                "fixture": not result.real_model_call,
            },
        )
        self._record_model_call(request, stage, result, logical_ref)
        self._ensure_cost_evidence(request, stage, result)
        if frozen_work_order is not None and execution_binding is not None:
            self.agent_binding_recorder.accept_candidate(
                frozen_work_order,
                result=result,
                execution_binding=execution_binding,
            )
        return result

    def _execution_identity(
        self,
        request: ChapterHandlerRequest,
        *,
        stable_key: str,
    ) -> tuple[int, str]:
        """Read the immutable execution fence/worker from a replayed effect."""

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
        """Persist model/cost evidence for an already-dispatched governed effect."""

        self._record_model_call(
            request,
            stage,
            result,
            _model_log_ref(request.operation_id, request.attempt_id, stage),
        )
        self._ensure_cost_evidence(request, stage, result)

    def completed_effect_result(
        self, external_effect_id: str, project_id: str
    ) -> ModelProviderResult | None:
        """Return durable provider evidence without dispatching the effect again."""

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
                asset_id=(
                    f"model-call:{request.operation_id}:{request.attempt_id}:{stage}"
                ),
                asset_type="model_call_log",
                schema_version="model-call-log.v1",
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

    def _record_failed_model_call(
        self,
        request: ChapterHandlerRequest,
        stage: str,
        *,
        dispatched: dict[str, Any],
        logical_ref: str,
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
                asset_id=(
                    f"model-call:{request.operation_id}:{request.attempt_id}:{stage}"
                ),
                asset_type="model_call_log",
                schema_version="model-call-log.v1",
                logical_ref=logical_ref,
                category="runs",
                output_key=f"model_call.{stage}.failed.{request.attempt_id}",
                role="model_failure_evidence",
                content={
                    "type": "model_call_log",
                    "operation_id": request.operation_id,
                    "project_id": request.project_id,
                    "stage": stage,
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
    ) -> None:
        logical_ref = _cost_log_ref(request.operation_id, request.attempt_id, stage)
        try:
            self.query.require(project_id=request.project_id, logical_ref=logical_ref)
            return
        except KernelError as exc:
            if exc.code != "AUTHORITY_ASSET_NOT_FOUND":
                raise
        provider_evidence = dispatched.get("provider_evidence")
        provider = provider_evidence if isinstance(provider_evidence, dict) else {}
        self.writer.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=request.operation_id,
                project_id=request.project_id,
                asset_id=(
                    f"cost-ledger:{request.operation_id}:{request.attempt_id}:{stage}"
                ),
                asset_type="cost_ledger",
                schema_version="model-cost-ledger.v1",
                logical_ref=logical_ref,
                category="runs",
                output_key=f"cost_ledger.{stage}.failed.{request.attempt_id}",
                role="cost_failure_evidence",
                content={
                    "type": "cost_ledger",
                    "operation_id": request.operation_id,
                    "project_id": request.project_id,
                    "stage": stage,
                    "availability": "AVAILABLE",
                    "amount": str(cost.get("amount") or "0"),
                    "currency": str(cost.get("currency") or "USD"),
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
                    "provider_billed": bool(cost.get("provider_billed", False)),
                    "execution_outcome": str(dispatched.get("outcome") or "").upper(),
                    "accepted_candidate": False,
                },
                qualification_policy="model-cost-failure-evidence-v1",
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
                reference_asset_ids=(
                    f"model-call:{request.operation_id}:{request.attempt_id}:{stage}",
                ),
            )
        )

    def _ensure_cost_evidence(
        self,
        request: ChapterHandlerRequest,
        stage: str,
        result: ModelProviderResult,
    ) -> None:
        logical_ref = _cost_log_ref(request.operation_id, request.attempt_id, stage)
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
                asset_id=(
                    f"cost-ledger:{request.operation_id}:{request.attempt_id}:{stage}"
                ),
                asset_type="cost_ledger",
                schema_version="model-cost-ledger.v1",
                logical_ref=logical_ref,
                category="runs",
                output_key=f"cost_ledger.{stage}",
                role="cost_evidence",
                content={
                    "type": "cost_ledger",
                    "operation_id": request.operation_id,
                    "project_id": request.project_id,
                    "stage": stage,
                    "availability": "AVAILABLE",
                    "amount": result.cost_amount,
                    "currency": result.currency,
                    "provider_id": result.provider_id,
                    "model_id": result.model_id,
                    "total_tokens": result.total_tokens,
                    "usage": dict(result.usage_evidence or {}),
                    "cost": dict(result.cost_evidence or {}),
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
                    "provider_billed": bool(
                        (result.cost_evidence or {}).get("provider_billed", False)
                    ),
                },
                qualification_policy="model-cost-evidence-v1",
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
                reference_asset_ids=(
                    f"model-call:{request.operation_id}:{request.attempt_id}:{stage}",
                ),
            )
        )


def _model_log_ref(operation_id: str, attempt_id: str, stage: str) -> str:
    return f"runs/model_calls/{operation_id}-{attempt_id}-{stage}.json"


def _cost_log_ref(operation_id: str, attempt_id: str, stage: str) -> str:
    return f"runs/cost_ledgers/{operation_id}-{attempt_id}-{stage}.json"


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
        or usage.get("availability") != "AVAILABLE"
        or usage.get("measurement") != "MEASURED"
        or cost.get("availability") != "AVAILABLE"
    ):
        return None
    return usage, cost


def _object(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise KernelError(
            "MODEL_EFFECT_INPUT_INVALID", f"model input {key} must be an object"
        )
    return value


def _normalize_model_output(stage: str, raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise KernelError("MODEL_RESPONSE_INVALID", "model response must be an object")
    if stage == "draft":
        text = str(raw.get("text") or "").strip()
        if not text:
            raise KernelError("MODEL_RESPONSE_INVALID", "draft response has no text")
        return {"text": text}
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
            normalized.append({"code": code, "severity": severity, "message": message})
        decision = "NEEDS_REVISION" if normalized or score < 80 else "PASSED"
        return {"decision": decision, "score": score, "issues": normalized}
    if stage == "canon_extraction":
        fields = (
            "canon_facts",
            "character_state_changes",
            "relationship_changes",
            "timeline_events",
            "foreshadow_changes",
            "promise_changes",
            "reward_changes",
            "world_rule_usages",
            "power_state_changes",
            "narrative_pattern_fingerprints",
            "theme_movements",
            "antagonist_pressure_changes",
        )
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
        if not any(normalized_extraction.values()):
            raise KernelError(
                "MODEL_RESPONSE_INVALID",
                "Canon semantic extraction cannot be empty on the Provider path",
            )
        return normalized_extraction
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
    text = str(raw.get("text") or raw.get("revised_text") or "").strip()
    resolved = [
        str(item).strip()
        for item in raw.get("resolved_issue_codes", [])
        if str(item).strip()
    ]
    if not text:
        raise KernelError(
            "MODEL_RESPONSE_INVALID", "revision response has no revised text"
        )
    return {"text": text, "resolved_issue_codes": resolved}


def normalize_model_output(stage: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Public typed validation seam shared by legacy and provider-v2 gateways."""

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
    "ChapterModelExternalEffectAdapter",
    "ChapterModelRoute",
    "ExternalEffectChapterModelPort",
    "ModelProviderResult",
    "normalize_model_output",
]
