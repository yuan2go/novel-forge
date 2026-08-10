"""Planning-domain binding to the existing Production Execution Plane."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from typing import Any, Callable

from novel_forge.modules.capability_pack_authority import (
    CapabilityPackAttemptSnapshot,
)
from novel_forge.modules.capability_pack_authority.runtime import (
    CapabilityPackRuntimeResolver,
)
from novel_forge.modules.command_kernel.asset_commands import (
    AuthorityAssetWriteCommand,
)
from novel_forge.modules.command_kernel.budget_runtime import (
    BudgetReservationRequest,
    reserve_provider_budget,
    resolve_provider_budget_failure,
    settle_provider_budget,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapterError,
    ProviderResult,
)
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    dispatch_external_effect,
    plan_external_effect,
)
from novel_forge.modules.hierarchical_planning.domain import (
    TYPE_FIELDS,
    PlanContractType,
)
from novel_forge.modules.production_execution import (
    ArtifactPointer,
    ExecutionOutcome,
    ExecutionRequest,
    ExecutionRuntimeClass,
    FallbackPolicy,
    InputManifest,
    ModelProfile,
    RoutePolicy,
    RouteSnapshot,
    TargetScope,
    default_capability_registry,
)
from novel_forge.modules.production_execution.domain_execution import (
    CandidateKind,
    DomainExecutionCandidate,
    DomainExecutionCommand,
    DomainExecutionEvidence,
)
from novel_forge.modules.provider_control.contracts import (
    ProviderCapabilityProfile,
)
from novel_forge.modules.story_design_authority import GeneratorDefinition
from novel_forge.storage.authority_asset_store import (
    AuthorityAssetDocument,
    AuthorityAssetQuery,
    AuthorityAssetWriter,
)
from novel_forge.storage.database_runtime import get_database_runtime

from .binder import PreparedPlanningExecution
from .domain import (
    FrozenPlanningInput,
    StoryPlanningGenerationCommand,
    canonical_hash,
)


_PLANNING_STAGES = frozenset(
    {
        "book_plan.generate",
        "volume_plan.generate",
        "arc_plan.generate",
        "chapter_group_plan.generate",
        "chapter_plan.generate",
    }
)


@dataclass(frozen=True, slots=True)
class PlanningExecutionRoute:
    """Authority-selected Planning route carried into each frozen attempt."""

    model_profile: ModelProfile
    route_policy: RoutePolicy
    fallback_policy: FallbackPolicy
    backend_version: str
    runtime_host_id: str
    auth_profile_ref: str
    release_sha: str

    def __post_init__(self) -> None:
        if (
            self.model_profile.profile_id
            not in self.route_policy.allowed_model_profile_ids
        ):
            raise ValueError("Planning RoutePolicy does not allow its ModelProfile")
        if (
            self.route_policy.fallback_policy_ref != self.fallback_policy.policy_id
            or self.route_policy.fallback_policy_version
            != self.fallback_policy.policy_version
            or self.route_policy.fallback_policy != self.fallback_policy.mode.value
        ):
            raise ValueError("Planning RoutePolicy does not bind its FallbackPolicy")
        if not all(
            (
                self.backend_version,
                self.runtime_host_id,
                self.auth_profile_ref,
            )
        ):
            raise ValueError("Planning execution route is incomplete")
        if len(self.release_sha) != 40:
            raise ValueError("Planning execution route requires a full release SHA")


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def _chapter_function_row(chapter: int, function: str, hook: str) -> dict[str, Any]:
    return {
        "chapter_number": chapter,
        "primary_function": function,
        "secondary_functions": ["character pressure"],
        "required_state_delta": {"commitment": 1},
        "required_arc_contributions": [
            {"arc_plan_version_id": "arc:primary", "kind": "advance"}
        ],
        "promise_action": "advance",
        "foreshadow_action": "plant",
        "reward_action": "partial payoff",
        "ending_hook": hook,
        "prohibited_outcomes": ["silent reset"],
    }


def _logical_chapter_number(logical_key: str) -> int:
    parts = logical_key.split(":")
    if len(parts) >= 2 and parts[0] == "chapter":
        try:
            chapter = int(parts[1])
        except ValueError:
            chapter = 0
        if chapter > 0:
            return chapter
    return 1


def planning_fixture_response(stage: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Explicit deterministic response for SCRIPTED_FIXTURE routes only."""

    if stage not in _PLANNING_STAGES:
        raise ValueError(f"unsupported Planning fixture stage: {stage}")
    command = inputs.get("planning_command")
    if not isinstance(command, Mapping):
        raise ValueError("Planning fixture requires its frozen command")
    logical_key = str(command.get("logical_key") or "")
    chapter_number = _logical_chapter_number(logical_key)
    parent_version_id = str(command.get("parent_version_id") or "")
    input_versions = command.get("input_versions")
    versions = dict(input_versions) if isinstance(input_versions, Mapping) else {}
    contract_type = {
        "book_plan.generate": PlanContractType.BOOK,
        "volume_plan.generate": PlanContractType.VOLUME,
        "arc_plan.generate": PlanContractType.ARC,
        "chapter_group_plan.generate": PlanContractType.CHAPTER_GROUP,
        "chapter_plan.generate": PlanContractType.CHAPTER,
    }[stage]
    payload: dict[str, Any] = {
        "contract_id": f"contract:{logical_key}",
        "logical_key": logical_key,
        "objective": f"Governed objective for {logical_key}",
        "entry_state_ref": "story-state:entry",
        "exit_state_spec": {"progress": "advanced"},
        "hard_constraints": [],
        "soft_constraints": [],
        "required_events": [],
        "forbidden_events": [],
        "required_payoffs": [],
        "forbidden_payoffs": [],
        "character_deltas": [],
        "world_deltas": [],
        "relationship_deltas": [],
        "arc_contributions": [],
        "canon_dependencies": [],
        "quality_targets": {"minimum": 80},
        "budget_policy_ref": "planning-budget:v1",
        "context_profile_ref": "planning-context:v1",
    }
    if command.get("change_evidence_version_ids"):
        payload["objective"] = (
            f"{payload['objective']} adjusted by governed change evidence"
        )
    by_type: dict[PlanContractType, dict[str, Any]] = {
        PlanContractType.BOOK: {
            "reader_promise": "Escalation with earned payoff",
            "central_conflict_engine": "Goal versus irreversible cost",
            "protagonist_transformation": "Avoidance to accountable choice",
            "antagonist_escalation": ["pressure", "constraint", "collision"],
            "world_evolution": ["scarcity", "revelation"],
            "relationship_evolution": ["distrust", "alliance"],
            "theme_evolution": ["freedom", "responsibility"],
            "ending_contract": {"outcome": "costly agency"},
            "volume_skeleton": [{"volume": 1, "function": "commitment"}],
            "major_turns": ["irreversible choice"],
            "climax_distribution": [1],
            "long_promise_payoff": ["central promise settled"],
            "length_strategy": {"target_chapters": 3},
            "risk_register": [],
        },
        PlanContractType.VOLUME: {
            "volume_function": "force commitment",
            "stage_conflict": "safety versus truth",
            "stage_antagonist": "institutional resistance",
            "irreversible_change": "public commitment",
            "midpoint": "false victory",
            "climax": "costly revelation",
            "settlement": "new obligation",
            "next_volume_bridge": "wider threat",
            "chapter_range": [1, 3],
        },
        PlanContractType.ARC: {
            "arc_type": "character-conflict",
            "resistance": "denial",
            "escalation": "public consequences",
            "turn": "truth exposed",
            "choice": "accept responsibility",
            "cost": "loss of safety",
            "result": "earned agency",
            "consequence": "new opposition",
            "dependencies": [],
            "closure_conditions": ["choice demonstrated"],
            "cross_volume_scope": [parent_version_id],
        },
        PlanContractType.CHAPTER_GROUP: {
            "local_objective": "Turn private doubt into public commitment",
            "trigger": "evidence arrives",
            "resistance_escalation": ["denial", "countermove"],
            "turn": "ally defects",
            "local_climax": "public choice",
            "information_release": ["hidden cost"],
            "emotion_curve": ["doubt", "pressure", "resolve"],
            "antagonist_actions": ["isolate", "expose"],
            "chapter_function_matrix": [
                _chapter_function_row(1, "setup", "door closes"),
                _chapter_function_row(2, "reversal", "ally defects"),
                _chapter_function_row(3, "payoff", "cost arrives"),
            ],
            "chapter_range": [1, 3],
            "cost_range": ["social", "material"],
            "primary_arc_ids": ["arc:primary"],
            "secondary_arc_ids": [],
            "required_arc_contributions": ["arc:primary"],
            "arc_checkpoint_expectations": [
                {
                    "arc_plan_version_id": str(versions.get("arc_plans") or ""),
                    "expectation": "choice advances",
                }
            ],
        },
        PlanContractType.CHAPTER: {
            **_chapter_function_row(chapter_number, "setup", "door closes"),
            "actual_arc_contributions": [],
            "title": f"Chapter {chapter_number}: The Door Closes",
            "premise": (
                f"Chapter {chapter_number} forces the protagonist into a witnessed choice."
            ),
        },
    }
    payload.update(by_type[contract_type])
    if contract_type is PlanContractType.CHAPTER:
        for contribution in payload["required_arc_contributions"]:
            contribution["arc_plan_version_id"] = str(versions.get("arc_plans") or "")
    if parent_version_id:
        payload["parent_version_id"] = parent_version_id
    return payload


def _strict_object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def planning_provider_output_schema(
    contract_type: PlanContractType,
    *,
    logical_key: str = "",
    parent_version_id: str = "",
    arc_plan_version_id: str = "",
    dependency_version_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    """OpenAI-strict provider schema; Planning validation stays authoritative."""

    string = {"type": "string", "minLength": 1}
    string_array = {"type": "array", "items": {"type": "string"}}
    delta = _strict_object({"subject": string, "change": string})
    object_array = {"type": "array", "items": delta}
    dependency_items = (
        {"type": "string", "enum": list(dependency_version_ids)}
        if dependency_version_ids
        else string
    )
    canon_dependencies: dict[str, Any] = {
        "type": "array",
        "items": dependency_items,
    }
    if not dependency_version_ids:
        canon_dependencies["maxItems"] = 0
    properties: dict[str, Any] = {
        "contract_id": string,
        "logical_key": (
            {"type": "string", "const": logical_key} if logical_key else string
        ),
        "objective": string,
        "entry_state_ref": string,
        "exit_state_spec": _strict_object({"summary": string}),
        "hard_constraints": string_array,
        "soft_constraints": string_array,
        "required_events": string_array,
        "forbidden_events": string_array,
        "required_payoffs": string_array,
        "forbidden_payoffs": string_array,
        "character_deltas": object_array,
        "world_deltas": object_array,
        "relationship_deltas": object_array,
        "arc_contributions": object_array,
        "canon_dependencies": canon_dependencies,
        "quality_targets": _strict_object(
            {"minimum": {"type": "integer", "minimum": 0, "maximum": 100}}
        ),
        "budget_policy_ref": string,
        "context_profile_ref": string,
    }
    strings = {
        "reader_promise",
        "central_conflict_engine",
        "protagonist_transformation",
        "volume_function",
        "stage_conflict",
        "stage_antagonist",
        "irreversible_change",
        "midpoint",
        "climax",
        "settlement",
        "next_volume_bridge",
        "arc_type",
        "resistance",
        "escalation",
        "turn",
        "choice",
        "cost",
        "result",
        "consequence",
        "local_objective",
        "trigger",
        "local_climax",
        "primary_function",
        "promise_action",
        "foreshadow_action",
        "reward_action",
        "ending_hook",
        "title",
        "premise",
    }
    arrays = {
        "antagonist_escalation",
        "world_evolution",
        "relationship_evolution",
        "theme_evolution",
        "major_turns",
        "long_promise_payoff",
        "risk_register",
        "dependencies",
        "closure_conditions",
        "cross_volume_scope",
        "resistance_escalation",
        "information_release",
        "emotion_curve",
        "antagonist_actions",
        "cost_range",
        "secondary_functions",
        "prohibited_outcomes",
        "primary_arc_ids",
        "secondary_arc_ids",
    }
    integer_arrays = {"climax_distribution", "chapter_range"}
    for field in TYPE_FIELDS[contract_type]:
        if field in strings:
            properties[field] = string
        elif field in arrays:
            if field == "cross_volume_scope" and parent_version_id:
                properties[field] = {
                    "type": "array",
                    "items": {"type": "string", "const": parent_version_id},
                }
            else:
                properties[field] = string_array
        elif field == "ending_contract":
            properties[field] = _strict_object({"outcome": string})
        elif field == "length_strategy":
            properties[field] = _strict_object(
                {"target_chapters": {"type": "integer", "minimum": 1}}
            )
        elif field == "required_state_delta":
            properties[field] = _strict_object({"summary": string})
        elif field == "volume_skeleton":
            properties[field] = {
                "type": "array",
                "items": _strict_object(
                    {
                        "volume": {"type": "integer", "minimum": 1},
                        "function": string,
                    }
                ),
            }
        elif field == "required_arc_contributions":
            arc_ref = (
                {"type": "string", "const": arc_plan_version_id}
                if arc_plan_version_id
                else string
            )
            properties[field] = {
                "type": "array",
                "minItems": 1,
                "items": _strict_object(
                    {"arc_plan_version_id": arc_ref, "contribution": string}
                ),
            }
            if arc_plan_version_id:
                properties[field]["maxItems"] = 1
        elif field in integer_arrays:
            properties[field] = {
                "type": "array",
                "items": {"type": "integer"},
            }
            if field == "chapter_range":
                properties[field].update({"minItems": 2, "maxItems": 2})
        elif field == "chapter_number":
            properties[field] = {"type": "integer", "minimum": 1}
        elif field == "chapter_function_matrix":
            properties[field] = {
                "type": "array",
                "minItems": 3,
                "maxItems": 8,
                "items": _strict_object(
                    {
                        "chapter_number": {"type": "integer", "minimum": 1},
                        "primary_function": string,
                        "secondary_functions": string_array,
                        "required_state_delta": _strict_object({"summary": string}),
                        "required_arc_contributions": {
                            "type": "array",
                            "minItems": 1,
                            "items": _strict_object(
                                {
                                    "arc_plan_version_id": string,
                                    "contribution": string,
                                }
                            ),
                        },
                        "promise_action": string,
                        "foreshadow_action": string,
                        "reward_action": string,
                        "ending_hook": string,
                        "prohibited_outcomes": string_array,
                    }
                ),
            }
        else:
            raise ValueError(f"Planning Provider schema missing field: {field}")
    if contract_type is not PlanContractType.BOOK:
        properties["parent_version_id"] = (
            {"type": "string", "const": parent_version_id}
            if parent_version_id
            else string
        )
    if contract_type is PlanContractType.CHAPTER:
        properties["title"] = {
            "type": "string",
            "minLength": 1,
            "maxLength": 120,
            "description": (
                "Concise reader-facing chapter title; never a planning instruction."
            ),
        }
        properties["premise"] = {
            "type": "string",
            "minLength": 1,
            "maxLength": 320,
            "description": (
                "Concise reader-facing chapter synopsis; never a planning, review, "
                "or Authority instruction."
            ),
        }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


@dataclass(frozen=True, slots=True)
class _PlanningExecutionBinding:
    request: ExecutionRequest
    route_snapshot: RouteSnapshot
    input_manifest: InputManifest


class _PlanningGatewayEffectAdapter:
    """Pure execution bridge for one already-frozen Planning request."""

    production_execution_gateway_backed = True

    def __init__(
        self,
        *,
        transport: Any,
        session: Any,
        binding: _PlanningExecutionBinding,
    ) -> None:
        self.transport = transport
        self.session = session
        self.binding = binding
        self.provider = str(transport.provider)
        self.reconciliation_mode = str(transport.reconciliation_mode)
        self.capability_profile: ProviderCapabilityProfile = (
            transport.capability_profile
        )

    def execute(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        request = self.binding.request
        if (
            stable_idempotency_key != request.stable_idempotency_key
            or capability != request.capability
            or str(request_payload.get("external_effect_id") or "")
            != request.external_effect_id
        ):
            raise ExternalEffectAdapterError(
                "Planning execution differs from its frozen request",
                request_sent=False,
            )
        request_sent = False
        try:
            handle = self.session.gateway.submit(request)
            request_sent = True
            result = self.session.gateway.reconcile(handle)
        except Exception as exc:
            raise ExternalEffectAdapterError(
                f"Planning gateway execution failed: {type(exc).__name__}: {exc}",
                request_sent=request_sent,
            ) from exc
        record = self.session.evidence_store.get_record(request.execution_id)
        evidence: dict[str, Any] = {
            "provider_id": self.binding.route_snapshot.model_provider,
            "model_id": self.binding.route_snapshot.model_id,
            "prompt_version": self.binding.input_manifest.prompt_bundle_version,
            "skill_version": self.binding.input_manifest.skill_bundle_version,
            "real_model_call": handle.transport
            in {
                ExecutionRuntimeClass.REMOTE_PROVIDER_API,
                ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
            },
            "fixture_protocol_only": (
                handle.transport is ExecutionRuntimeClass.SCRIPTED_FIXTURE
            ),
            "production_verified": False,
            "production_execution": {
                "execution_request": request.to_dict(),
                "execution_handle": handle.to_dict(),
                "execution_result": result.to_dict(),
                "route_snapshot": self.binding.route_snapshot.to_dict(),
                "input_manifest": self.binding.input_manifest.to_dict(),
                "process_evidence": dict(record.raw_evidence),
            },
        }
        capability_evidence = record.raw_evidence.get("capability_evidence")
        if isinstance(capability_evidence, Mapping):
            evidence["capability_runtime"] = dict(capability_evidence)
        if result.normalized_output_ref:
            evidence["result"] = self.session.evidence_store.read_evidence(
                str(result.normalized_output_ref)
            )
        if result.usage_receipt_ref:
            evidence["usage"] = self.session.evidence_store.read_evidence(
                str(result.usage_receipt_ref)
            )
        if result.cost_receipt_ref:
            evidence["cost"] = self.session.evidence_store.read_evidence(
                str(result.cost_receipt_ref)
            )
        outcome = {
            ExecutionOutcome.SUCCEEDED: "success",
            ExecutionOutcome.RETRYABLE_FAILURE: "retryable_failure",
            ExecutionOutcome.TIMED_OUT: "retryable_failure",
            ExecutionOutcome.CORRUPT_RESULT: "retryable_failure",
            ExecutionOutcome.FINAL_FAILURE: "final_failure",
            ExecutionOutcome.CANCELLED: "cancelled",
        }.get(result.outcome, "unknown")
        return ProviderResult(
            outcome,
            handle.backend_execution_id,
            evidence,
            handle.provider_request_id or "",
        )

    def query(self, **kwargs: Any) -> ProviderResult:
        return self.execute(**kwargs)

    def cancel(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
        provider_request_id: str,
    ) -> ProviderResult:
        request = self.binding.request
        handle = self.session.gateway.submit(request)
        cancellation = self.session.gateway.cancel(handle, "Planning cancellation")
        return ProviderResult(
            "cancelled",
            handle.backend_execution_id,
            {"production_execution_cancellation": cancellation.to_dict()},
            provider_request_id,
        )


@dataclass(slots=True)
class _PlanningPepPort:
    database_url: str
    worker_id: str
    lease_seconds: int
    context: EffectCommandContext
    effect_id: str
    stable_key: str
    reservation_id: str
    binding: _PlanningExecutionBinding
    adapter: _PlanningGatewayEffectAdapter
    writer: AuthorityAssetWriter
    post_provider_fault_injector: Callable[[str], None]

    external_effect_backed = True
    production_execution_gateway_backed = True

    def execute(self, command: DomainExecutionCommand) -> DomainExecutionCandidate:
        if command.capability != self.binding.request.capability:
            raise KernelError(
                "PLANNING_PEP_CAPABILITY_DRIFT",
                "Planning command differs from the frozen execution capability",
            )
        dispatched = dispatch_external_effect(
            self.database_url,
            self.context,
            effect_id=self.effect_id,
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
            adapter=self.adapter,
        )
        if dispatched["outcome"] != "success":
            resolve_provider_budget_failure(
                self.database_url,
                reservation_id=self.reservation_id,
                project_id=self.context.project_id,
            )
            outcome = str(dispatched.get("outcome") or "unknown")
            code = (
                "MODEL_EFFECT_RETRYABLE_PLANNING"
                if outcome in {"retryable_failure", "not_found"}
                else "MODEL_EFFECT_FINAL_PLANNING"
            )
            raise KernelError(code, f"Planning provider outcome was {outcome}")
        evidence = dispatched.get("provider_evidence")
        if not isinstance(evidence, Mapping):
            raise KernelError(
                "PLANNING_MODEL_EVIDENCE_INVALID",
                "Planning provider returned no evidence",
            )
        raw = evidence.get("result")
        usage = evidence.get("usage")
        cost = evidence.get("cost")
        production = evidence.get("production_execution")
        if not all(
            (
                isinstance(raw, Mapping),
                isinstance(usage, Mapping),
                isinstance(cost, Mapping),
                isinstance(production, Mapping),
            )
        ):
            raise KernelError(
                "PLANNING_MODEL_EVIDENCE_INVALID",
                "Planning provider evidence lacks result, usage, cost, or receipt",
            )
        amount = str(cost.get("amount") or "0")
        total_tokens = int(usage.get("total_tokens") or 0)
        settle_provider_budget(
            self.database_url,
            reservation_id=self.reservation_id,
            project_id=self.context.project_id,
            actual_amount=amount,
            actual_tokens=total_tokens,
            evidence={
                "provider_id": str(evidence.get("provider_id") or ""),
                "model_id": str(evidence.get("model_id") or ""),
                "real_model_call": bool(evidence.get("real_model_call")),
                "fixture": bool(evidence.get("fixture_protocol_only")),
            },
        )
        try:
            self.post_provider_fault_injector(
                "after_measured_usage_before_candidate_acceptance"
            )
        except KernelError as exc:
            self._record_model_evidence(
                evidence=evidence,
                usage=usage,
                cost=cost,
                amount=amount,
                total_tokens=total_tokens,
                accepted_candidate=False,
                failure={"code": exc.code, "message": str(exc)},
            )
            raise
        self._record_model_evidence(
            evidence=evidence,
            usage=usage,
            cost=cost,
            amount=amount,
            total_tokens=total_tokens,
            accepted_candidate=True,
        )
        execution_result = production.get("execution_result")
        if not isinstance(execution_result, Mapping):
            raise KernelError(
                "PLANNING_PEP_EVIDENCE_INCOMPLETE",
                "Planning PEP result lacks an execution result",
            )
        required = {
            "output": execution_result.get("output_manifest_ref"),
            "validation": execution_result.get("validation_report_ref"),
            "usage": execution_result.get("usage_receipt_ref"),
            "cost": execution_result.get("cost_receipt_ref"),
        }
        if any(not value for value in required.values()):
            raise KernelError(
                "PLANNING_PEP_EVIDENCE_INCOMPLETE",
                "Planning PEP result lacks required manifests",
            )
        request = self.binding.request
        handle = production.get("execution_handle")
        backend_id = (
            str(handle.get("backend_id") or "") if isinstance(handle, Mapping) else ""
        )
        return DomainExecutionCandidate(
            candidate_kind=CandidateKind.GENERATION,
            raw_output=dict(raw),
            evidence=DomainExecutionEvidence(
                execution_id=request.execution_id,
                operation_id=request.operation_id,
                attempt_id=request.attempt_id,
                fencing_token=request.fencing_token,
                capability=request.capability,
                backend_id=backend_id,
                route_snapshot_id=request.route_snapshot_id,
                input_manifest_ref=request.input_manifest_ref,
                output_manifest_ref=str(required["output"]),
                validation_manifest_ref=str(required["validation"]),
                usage_receipt_ref=str(required["usage"]),
                cost_receipt_ref=str(required["cost"]),
                fixture_protocol_only=bool(evidence.get("fixture_protocol_only")),
                real_model_call=bool(evidence.get("real_model_call")),
                production_verified=False,
                provider_id=str(evidence.get("provider_id") or ""),
                model_id=str(evidence.get("model_id") or ""),
                external_receipt_ref=self.effect_id,
            ),
        )

    def _record_model_evidence(
        self,
        *,
        evidence: Mapping[str, Any],
        usage: Mapping[str, Any],
        cost: Mapping[str, Any],
        amount: str,
        total_tokens: int,
        accepted_candidate: bool,
        failure: Mapping[str, Any] | None = None,
    ) -> None:
        self._record_evidence(
            "model_call_log",
            {
                **dict(evidence),
                "candidate_accepted": accepted_candidate,
                "post_provider_failure": dict(failure or {}),
            },
        )
        self._record_evidence(
            "cost_ledger",
            {
                "availability": "AVAILABLE",
                "amount": amount,
                "currency": str(cost.get("currency") or "USD"),
                "total_tokens": total_tokens,
                "usage": dict(usage),
                "cost": dict(cost),
                "candidate_accepted": accepted_candidate,
                "post_provider_failure": dict(failure or {}),
            },
        )

    def _record_evidence(self, asset_type: str, content: dict[str, Any]) -> None:
        request = self.binding.request
        logical_ref = (
            f"runs/{asset_type}s/{request.operation_id}-{request.attempt_id}-"
            f"{request.stage}.json"
        )
        self.writer.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=request.operation_id,
                project_id=request.project_id,
                asset_id=f"{asset_type}:{request.operation_id}:{request.attempt_id}",
                asset_type=asset_type,
                schema_version=f"{asset_type}.v1",
                logical_ref=logical_ref,
                category="runs",
                output_key=f"{asset_type}.{request.stage}",
                role="model_evidence"
                if asset_type == "model_call_log"
                else "cost_evidence",
                content={
                    "type": asset_type,
                    "operation_id": request.operation_id,
                    "project_id": request.project_id,
                    "stage": request.stage,
                    **content,
                },
                qualification_policy=f"{asset_type}-evidence-v1",
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
            )
        )


class PostgresPlanningExecutionPreparer:
    """Freeze Planning-domain PEP contracts on the current Authority Attempt."""

    production_execution_gateway_backed = True

    def __init__(
        self,
        database_url: str,
        *,
        execution_transport: Any,
        planning_route: PlanningExecutionRoute,
        worker_id: str,
        max_cost_per_call: str = "0",
        budget_caps: Mapping[str, str] | None = None,
        lease_seconds: int = 60,
        post_provider_fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        if not database_url or not worker_id or lease_seconds <= 0:
            raise ValueError(
                "Planning execution requires PostgreSQL and worker identity"
            )
        if not getattr(
            execution_transport, "production_execution_gateway_backed", False
        ):
            raise ValueError("Planning execution requires the Production Gateway")
        self.database_url = database_url
        self.execution_transport = execution_transport
        self.planning_route = planning_route
        self.worker_id = worker_id
        self.max_cost_per_call = max_cost_per_call
        self.budget_caps = dict(budget_caps or {})
        self.lease_seconds = lease_seconds
        self.post_provider_fault_injector = post_provider_fault_injector or (
            lambda _checkpoint: None
        )
        self.query = AuthorityAssetQuery(database_url)
        self.writer = AuthorityAssetWriter(database_url)
        self.pack_runtime = CapabilityPackRuntimeResolver(database_url)

    def prepare(
        self,
        *,
        operation_id: str,
        attempt_id: str,
        fencing_token: int,
        worker_id: str,
        command: StoryPlanningGenerationCommand,
        inputs: tuple[FrozenPlanningInput, ...],
        definition: GeneratorDefinition,
        attempt_snapshot: CapabilityPackAttemptSnapshot,
    ) -> PreparedPlanningExecution:
        if worker_id != self.worker_id:
            raise KernelError(
                "PLANNING_WORKER_IDENTITY_DRIFT",
                "Planning preparer belongs to another worker",
            )
        if command.generator_operation_name not in _PLANNING_STAGES:
            raise KernelError(
                "PLANNING_STAGE_UNSUPPORTED", "Planning stage is not governed"
            )
        capability = default_capability_registry().resolve(definition.capability)
        frozen = attempt_snapshot.execution_snapshot
        if frozen.execution_capability_id != capability.capability_id.value:
            raise KernelError(
                "PLANNING_CAPABILITY_PACK_NODE_INVALID",
                "Planning Pack capability differs from the Generator",
            )
        context_document, input_documents = self._context_bundle(
            operation_id=operation_id,
            attempt_id=attempt_id,
            command=command,
            inputs=inputs,
        )
        pack_materialization = self.pack_runtime.materialize_attempt_artifacts(
            attempt_snapshot
        )
        tools = json.loads(frozen.tool_policy_payload_json)
        allowed_tools = self._allowed_tools(tools, command.generator_operation_name)
        if allowed_tools != ("model.provider.invoke",):
            raise KernelError(
                "PLANNING_CAPABILITY_TOOL_UNAUTHORIZED",
                "Planning Codex execution permits only model.provider.invoke",
            )
        output_schema = planning_provider_output_schema(
            PlanContractType(command.planning_scope.value),
            logical_key=command.logical_key,
            parent_version_id=command.parent_version_id,
            arc_plan_version_id=str(command.input_versions.get("arc_plans") or ""),
            dependency_version_ids=tuple(command.input_versions.values()),
        )
        output_schema_ref = (
            "schema:planning-provider-output:"
            + command.planning_scope.value.lower()
            + (
                ":v3"
                if command.planning_scope.value == PlanContractType.CHAPTER.value
                else ":v1"
            )
        )
        materialization = {
            "schema_version": "novelos.planning_capability_materialization.v1",
            "stage": command.generator_operation_name,
            "capability_requirement": definition.capability,
            "attempt_snapshot": {
                "snapshot_id": attempt_snapshot.snapshot_id,
                "snapshot_hash": attempt_snapshot.snapshot_hash,
                "operation_id": operation_id,
                "attempt_id": attempt_id,
                "execution_fencing_token": fencing_token,
            },
            "pack_identity": {
                "pack_id": frozen.pack_id,
                "pack_version": frozen.pack_version,
                "manifest_hash": frozen.manifest_hash,
                "compilation_hash": frozen.compilation_hash,
                "catalog_snapshot_hash": frozen.catalog_snapshot_hash,
                "binding_set_id": frozen.binding_set_id,
                "binding_set_hash": frozen.binding_set_hash,
            },
            "pack_artifacts": pack_materialization.to_dict(include_content=True),
            "pack_artifact_materialization_hash": (
                pack_materialization.materialization_hash
            ),
            "context_selection": [
                {
                    "artifact_ref": f"asset-version:{context_document.asset_version_id}",
                    "asset_version_id": context_document.asset_version_id,
                    "artifact_type": "context_bundle",
                    "content_hash": context_document.content_hash,
                    "schema_version": "novelos.planning_context_bundle.v1",
                    "source_eligibility": "PRODUCTION_ELIGIBLE",
                    "content": context_document.content,
                }
            ],
            "knowledge_selection": [
                item.to_dict(include_content=True)
                for item in pack_materialization.required_knowledge
            ],
            "tool_permissions": {
                "default": str(tools.get("default") or ""),
                "allowed": list(allowed_tools),
                "denied": [],
                "invoked": ["model.provider.invoke"],
                "governing_policy_ref": frozen.tool_policy_ref,
                "governing_policy_hash": frozen.tool_policy_hash,
            },
            "output_schema": {
                "ref": output_schema_ref,
                "content_hash": canonical_hash(output_schema),
                "content": output_schema,
            },
        }
        materialization["materialization_hash"] = canonical_hash(materialization)
        materialization_ref = (
            "production_execution/capability_materializations/"
            + _token(f"{command.project_id}:{operation_id}:{attempt_id}:planning")
        )
        materialization_document = self._ensure_contract(
            operation_id=operation_id,
            project_id=command.project_id,
            logical_ref=materialization_ref,
            asset_type="capability_materialization_manifest",
            contract=materialization,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        effect_context = EffectCommandContext(
            operation_id=operation_id,
            project_id=command.project_id,
            actor_id=worker_id,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        stable_key = (
            f"{operation_id}:{attempt_id}:{definition.capability}:planning-pep-v1"
        )
        planning_route = self.planning_route
        request_payload = {
            "stage": command.generator_operation_name,
            "input": {
                "planning_command": {
                    "logical_key": command.logical_key,
                    "planning_scope": command.planning_scope.value,
                    "parent_version_id": command.parent_version_id,
                    "input_versions": dict(command.input_versions),
                    "change_evidence_version_ids": list(
                        command.change_evidence_version_ids
                    ),
                    "repair_number": command.repair_number,
                    "repair_reason": command.repair_reason,
                },
                "frozen_inputs": [
                    {
                        "role": item.role,
                        "asset_version_id": item.asset_version_id,
                        "content_hash": item.content_hash,
                        "asset_type": item.asset_type,
                    }
                    for item in inputs
                ],
            },
            "trace_id": command.trace_id,
            "correlation_id": command.correlation_id,
            "_production_execution": {
                "operation_id": operation_id,
                "attempt_id": attempt_id,
                "fencing_token": fencing_token,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "book_id": command.book_id,
                "worker_id": worker_id,
                "capability_runtime": {
                    "snapshot_id": attempt_snapshot.snapshot_id,
                    "snapshot_hash": attempt_snapshot.snapshot_hash,
                    "materialization_asset_version_id": (
                        materialization_document.asset_version_id
                    ),
                    "materialization_content_hash": (
                        materialization_document.content_hash
                    ),
                    "materialization_hash": materialization["materialization_hash"],
                },
            },
        }
        effect = plan_external_effect(
            self.database_url,
            effect_context,
            effect_type="model.invoke",
            provider=self.execution_transport.provider,
            capability=definition.capability,
            stable_idempotency_key=stable_key,
            request_payload=request_payload,
            max_attempts=1,
            reversible=False,
            completion_policy="synchronous_final",
            model_id=planning_route.model_profile.model_id,
            request_timeout_seconds=self.lease_seconds * 5,
            reconciliation_mode=self.execution_transport.reconciliation_mode,
            provider_capability_profile=(
                self.execution_transport.capability_profile.to_dict()
            ),
        )
        effect_id = str(effect["external_effect_id"])
        reservation = reserve_provider_budget(
            self.database_url,
            BudgetReservationRequest(
                operation_id=operation_id,
                external_effect_id=effect_id,
                project_id=command.project_id,
                stable_idempotency_key=f"budget:{stable_key}",
                provider=self.execution_transport.provider,
                currency="USD",
                estimated_amount=self.max_cost_per_call,
                estimated_tokens=0,
                caps=self.budget_caps,
            ),
        )
        request_payload["external_effect_id"] = effect_id
        binding, contract_documents = self._execution_binding(
            operation_id=operation_id,
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            command=command,
            definition=definition,
            capability=capability,
            planning_route=planning_route,
            context_document=context_document,
            input_documents=input_documents,
            effect_id=effect_id,
            stable_key=stable_key,
            reservation_id=str(reservation["reservation_id"]),
            output_schema_ref=output_schema_ref,
            frozen=frozen,
        )
        session = self.execution_transport.session_for_project(command.project_id)
        adapter = _PlanningGatewayEffectAdapter(
            transport=self.execution_transport,
            session=session,
            binding=binding,
        )
        return PreparedPlanningExecution(
            execution_port=_PlanningPepPort(
                database_url=self.database_url,
                worker_id=worker_id,
                lease_seconds=self.lease_seconds,
                context=effect_context,
                effect_id=effect_id,
                stable_key=stable_key,
                reservation_id=str(reservation["reservation_id"]),
                binding=binding,
                adapter=adapter,
                writer=self.writer,
                post_provider_fault_injector=self.post_provider_fault_injector,
            ),
            context_bundle_asset_version_id=context_document.asset_version_id,
            context_bundle_hash=context_document.content_hash,
            route_snapshot_ref=binding.route_snapshot.route_snapshot_id,
            route_snapshot_hash=contract_documents["route"].content_hash,
            input_manifest_ref=binding.input_manifest.manifest_id,
            input_manifest_hash=contract_documents["input"].content_hash,
            prompt_bundle_ref=frozen.prompt_bundle_ref,
            prompt_bundle_hash=frozen.prompt_bundle_hash,
            skill_bundle_ref=frozen.skill_bundle_ref,
            skill_bundle_hash=frozen.skill_bundle_hash,
            tool_permission_snapshot_ref=frozen.tool_policy_ref,
            tool_permission_snapshot_hash=frozen.tool_policy_hash,
            context_policy_ref=frozen.context_policy_ref,
            context_policy_hash=frozen.context_policy_hash,
            validation_policy_ref=frozen.evaluation_policy_ref,
            commit_policy_ref=capability.commit_policy_ref,
            timeout_policy_ref=capability.timeout_policy_ref,
        )

    def _execution_binding(
        self,
        *,
        operation_id: str,
        attempt_id: str,
        fencing_token: int,
        command: StoryPlanningGenerationCommand,
        definition: GeneratorDefinition,
        capability: Any,
        planning_route: PlanningExecutionRoute,
        context_document: AuthorityAssetDocument,
        input_documents: tuple[AuthorityAssetDocument, ...],
        effect_id: str,
        stable_key: str,
        reservation_id: str,
        output_schema_ref: str,
        frozen: Any,
    ) -> tuple[_PlanningExecutionBinding, dict[str, AuthorityAssetDocument]]:
        graph = self._operation_graph(operation_id, command.project_id)
        suffix = command.planning_scope.value.lower()
        profile_id = f"planning.{suffix}.default"
        profile = ModelProfile(
            profile_id=profile_id,
            profile_version=1,
            backend_id=planning_route.model_profile.backend_id,
            runtime_class=planning_route.model_profile.runtime_class,
            model_provider=planning_route.model_profile.model_provider,
            model_id=planning_route.model_profile.model_id,
            reasoning_effort=planning_route.model_profile.reasoning_effort,
            timeout_policy_ref=capability.timeout_policy_ref,
            workspace_policy_ref="workspace:story-planning:v1",
            output_policy_ref=output_schema_ref,
            fallback_policy="FAIL_CLOSED",
            status=planning_route.model_profile.status,
            capability_probe_ref=planning_route.model_profile.capability_probe_ref,
        )
        policy = RoutePolicy(
            policy_id=f"planning.{suffix}.route",
            policy_version=1,
            default_model_profile_id=profile_id,
            allowed_model_profile_ids=(profile_id,),
            rule_set_ref=f"route-rules:planning:{suffix}:v1",
            fallback_policy="FAIL_CLOSED",
            fallback_policy_ref=f"planning.{suffix}.fail-closed",
            fallback_policy_version=1,
            reasoning_downgrade_policy="PROHIBITED",
            status="ACTIVE",
        )
        fallback = FallbackPolicy.fail_closed(
            policy.fallback_policy_ref, policy.fallback_policy_version
        )
        target = TargetScope(
            scope_kind=command.planning_scope.value.lower(),
            scope_id=command.logical_key,
            project_id=command.project_id,
            book_id=command.book_id,
        )
        context_ref = f"asset-version:{context_document.asset_version_id}"
        route_ref = "production_execution/routes/" + _token(
            f"{command.project_id}:{operation_id}:{attempt_id}:planning"
        )
        input_ref = "production_execution/inputs/" + _token(
            f"{command.project_id}:{operation_id}:{attempt_id}:planning"
        )
        pointers = (
            ArtifactPointer(
                artifact_ref=context_ref,
                asset_version_id=context_document.asset_version_id,
                artifact_type="context_bundle",
                content_hash=context_document.content_hash,
                schema_version="novelos.planning_context_bundle.v1",
                source_eligibility="PRODUCTION_ELIGIBLE",
            ),
            *tuple(
                ArtifactPointer(
                    artifact_ref=f"asset-version:{document.asset_version_id}",
                    asset_version_id=document.asset_version_id,
                    artifact_type=document.asset_type,
                    content_hash=document.content_hash,
                    schema_version=f"{document.asset_type}.v1",
                    source_eligibility="PRODUCTION_ELIGIBLE",
                )
                for document in input_documents
            ),
        )
        manifest = InputManifest(
            manifest_id=input_ref,
            operation_id=operation_id,
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            project_id=command.project_id,
            book_id=command.book_id,
            target_scope=target,
            context_bundle_ref=context_ref,
            prompt_bundle_ref=frozen.prompt_bundle_ref,
            skill_bundle_ref=frozen.skill_bundle_ref,
            context_bundle_version=context_document.asset_version_id,
            prompt_bundle_version=frozen.prompt_bundle_ref,
            skill_bundle_version=frozen.skill_bundle_ref,
            canon_snapshot_version=str(
                command.input_versions.get("canon_snapshot") or "none"
            ),
            story_state_version=str(
                command.input_versions.get("story_state") or "none"
            ),
            planning_version=command.parent_version_id or command.logical_key,
            quality_profile_version=str(
                command.input_versions.get("quality_trend") or "none"
            ),
            source_policy_ref=capability.source_policy_ref,
            source_eligibility="PRODUCTION_ELIGIBLE",
            canon_version_refs=tuple(
                f"asset-version:{document.asset_version_id}"
                for document in input_documents
                if "canon" in document.asset_type
            ),
            arc_version_refs=tuple(
                f"asset-version:{document.asset_version_id}"
                for document in input_documents
                if "arc" in document.asset_type
            ),
            input_artifacts=pointers,
            read_set=tuple(item.artifact_ref for item in pointers),
        )
        route = RouteSnapshot(
            route_snapshot_id=route_ref,
            route_decision_id=f"route-decision:{_token(route_ref)}",
            operation_id=operation_id,
            attempt_id=attempt_id,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            backend_id=profile.backend_id,
            backend_version=planning_route.backend_version,
            runtime_host_id=planning_route.runtime_host_id,
            auth_profile_ref=planning_route.auth_profile_ref,
            model_profile_id=profile.profile_id,
            model_profile_version=profile.profile_version,
            model_profile_hash=profile.contract_hash,
            route_policy_hash=policy.contract_hash,
            model_provider=profile.model_provider,
            model_id=profile.model_id,
            requested_reasoning_effort=profile.reasoning_effort,
            reasoning_effort=profile.reasoning_effort,
            prompt_bundle_ref=frozen.prompt_bundle_ref,
            skill_bundle_ref=frozen.skill_bundle_ref,
            context_bundle_ref=context_ref,
            output_schema_ref=output_schema_ref,
            release_sha=planning_route.release_sha,
            fallback_policy_ref=fallback.policy_id,
            fallback_policy_version=fallback.policy_version,
        )
        profile_doc = self._ensure_contract(
            operation_id=operation_id,
            project_id=command.project_id,
            logical_ref=f"production_execution/model_profiles/{profile_id}/v1",
            asset_type="model_profile",
            contract=profile.to_dict(),
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        del profile_doc
        self._ensure_contract(
            operation_id=operation_id,
            project_id=command.project_id,
            logical_ref=f"production_execution/route_policies/{policy.policy_id}/v1",
            asset_type="route_policy",
            contract=policy.to_dict(),
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        self._ensure_contract(
            operation_id=operation_id,
            project_id=command.project_id,
            logical_ref=(
                f"production_execution/fallback_policies/{fallback.policy_id}/v1"
            ),
            asset_type="fallback_policy",
            contract=fallback.to_dict(),
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        input_doc = self._ensure_contract(
            operation_id=operation_id,
            project_id=command.project_id,
            logical_ref=input_ref,
            asset_type="input_manifest",
            contract=manifest.to_dict(),
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        route_doc = self._ensure_contract(
            operation_id=operation_id,
            project_id=command.project_id,
            logical_ref=route_ref,
            asset_type="route_snapshot",
            contract={
                **route.to_dict(),
                "capability_pack_attempt_snapshot_id": frozen.snapshot_id
                if hasattr(frozen, "snapshot_id")
                else "",
            },
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        request = ExecutionRequest(
            execution_id=f"planning-execution:{effect_id}",
            operation_id=operation_id,
            root_operation_id=graph["root_operation_id"],
            saga_id=graph["saga_id"],
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            project_id=command.project_id,
            workspace_id=command.workspace_id,
            book_id=command.book_id,
            target_scope=target,
            domain=capability.domain.value,
            task_kind=graph["definition_name"],
            stage=command.generator_operation_name,
            capability=definition.capability,
            importance_class="HIGH",
            risk_class=capability.risk_class.value,
            route_snapshot_id=route_ref,
            workspace_snapshot_ref=command.workspace_id,
            input_manifest_ref=input_ref,
            resource_claims=(
                f"book:{command.book_id}",
                f"planning:{command.logical_key}",
            ),
            timeout_policy_ref=capability.timeout_policy_ref,
            budget_policy_ref=capability.budget_policy_ref,
            permission_policy_ref=capability.permission_policy_ref,
            validation_policy_ref=capability.validation_policy_ref,
            commit_policy_ref=capability.commit_policy_ref,
            stable_idempotency_key=stable_key,
            origin_chain=("story_planning.generate", command.generator_operation_name),
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            external_effect_id=effect_id,
            budget_reservation_id=reservation_id,
        )
        return _PlanningExecutionBinding(request, route, manifest), {
            "input": input_doc,
            "route": route_doc,
        }

    def _context_bundle(
        self,
        *,
        operation_id: str,
        attempt_id: str,
        command: StoryPlanningGenerationCommand,
        inputs: tuple[FrozenPlanningInput, ...],
    ) -> tuple[AuthorityAssetDocument, tuple[AuthorityAssetDocument, ...]]:
        documents: list[AuthorityAssetDocument] = []
        selected: list[dict[str, Any]] = []
        for item in inputs:
            document = self.query.require(
                project_id=command.project_id,
                asset_version_id=item.asset_version_id,
            )
            if (
                document.asset_type != item.asset_type
                or document.content_hash != item.content_hash
                or document.governance != "CLEAR"
                or document.eligibility not in {"ELIGIBLE", "PRODUCTION_ELIGIBLE"}
            ):
                raise KernelError(
                    "PLANNING_CONTEXT_INPUT_DRIFT",
                    "Planning input differs from its frozen Authority version",
                )
            documents.append(document)
            selected.append(
                {
                    "role": item.role,
                    "asset_version_id": document.asset_version_id,
                    "asset_type": document.asset_type,
                    "content_hash": document.content_hash,
                    "content": document.content,
                }
            )
        for ordinal, asset_version_id in enumerate(
            command.change_evidence_version_ids, start=1
        ):
            document = self.query.require(
                project_id=command.project_id,
                asset_version_id=asset_version_id,
            )
            if (
                document.asset_type not in {"longform_recap", "replan_request"}
                or document.governance != "CLEAR"
                or document.eligibility
                not in {"ELIGIBLE", "PRODUCTION_ELIGIBLE"}
            ):
                raise KernelError(
                    "PLANNING_CONTEXT_CHANGE_EVIDENCE_INVALID",
                    "Planning change evidence drifted after admission",
                )
            documents.append(document)
            selected.append(
                {
                    "role": f"change_evidence:{ordinal}",
                    "asset_version_id": document.asset_version_id,
                    "asset_type": document.asset_type,
                    "content_hash": document.content_hash,
                    "content": document.content,
                }
            )
        content = {
            "schema_version": "novelos.planning_context_bundle.v1",
            "project_id": command.project_id,
            "workspace_id": command.workspace_id,
            "book_id": command.book_id,
            "planning_scope": command.planning_scope.value,
            "logical_key": command.logical_key,
            "input_versions": selected,
            "token_budget": 16000,
            "source_isolation": "ABSTRACT_ASSETS_ONLY",
            "trace_id": command.trace_id,
        }
        logical_ref = f"planning/context_bundles/{operation_id}-{attempt_id}.json"
        try:
            context = self.query.require(
                project_id=command.project_id, logical_ref=logical_ref
            )
            if context.content != content:
                raise KernelError(
                    "PLANNING_CONTEXT_BUNDLE_CONFLICT",
                    "Planning Attempt context changed after freeze",
                )
        except KernelError as exc:
            if exc.code != "AUTHORITY_ASSET_NOT_FOUND":
                raise
            context = self.writer.materialize_output(
                AuthorityAssetWriteCommand(
                    operation_id=operation_id,
                    project_id=command.project_id,
                    asset_id=f"planning-context:{attempt_id}",
                    asset_type="context_bundle",
                    schema_version="novelos.planning_context_bundle.v1",
                    logical_ref=logical_ref,
                    category="planning_context",
                    output_key="planning.context_bundle",
                    role="context_bundle",
                    content=content,
                    qualification_policy="planning-context-source-isolation-v1",
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    reference_asset_ids=tuple(
                        document.asset_id for document in documents
                    ),
                )
            )
        return context, tuple(documents)

    @staticmethod
    def _allowed_tools(policy: Mapping[str, Any], stage: str) -> tuple[str, ...]:
        if str(policy.get("default") or "").upper() != "DENY":
            raise KernelError(
                "PLANNING_CAPABILITY_TOOL_POLICY_INVALID",
                "Planning Tool policy must default deny",
            )
        allowed = {
            str(item.get("tool_ref") or "")
            for item in policy.get("tools") or ()
            if isinstance(item, Mapping)
            and str(item.get("permission") or "").upper() == "EXECUTE"
            and stage in {str(value) for value in item.get("allowed_operations") or ()}
        }
        return tuple(sorted(item for item in allowed if item))

    def _operation_graph(self, operation_id: str, project_id: str) -> dict[str, str]:
        runtime = get_database_runtime(self.database_url)
        with runtime.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT operation.definition_name, operation.root_operation_id,
                           saga.saga_id
                    FROM authority_operation AS operation
                    JOIN authority_saga AS saga
                      ON saga.root_operation_id=operation.root_operation_id
                     AND saga.project_id=operation.project_id
                    WHERE operation.operation_id=%s AND operation.project_id=%s
                    """,
                    [operation_id, project_id],
                )
                row = cursor.fetchone()
        if row is None:
            raise KernelError(
                "PLANNING_OPERATION_GRAPH_MISSING",
                "Planning execution has no admitted Saga",
            )
        return {
            "definition_name": str(row[0]),
            "root_operation_id": str(row[1]),
            "saga_id": str(row[2]),
        }

    def _ensure_contract(
        self,
        *,
        operation_id: str,
        project_id: str,
        logical_ref: str,
        asset_type: str,
        contract: dict[str, Any],
        trace_id: str,
        correlation_id: str,
    ) -> AuthorityAssetDocument:
        try:
            existing = self.query.require(
                project_id=project_id, logical_ref=logical_ref
            )
        except KernelError as exc:
            if exc.code != "AUTHORITY_ASSET_NOT_FOUND":
                raise
            existing = None
        if existing is not None:
            if (
                existing.asset_type != asset_type
                or existing.content.get("contract", existing.content) != contract
            ):
                raise KernelError(
                    "EXECUTION_CONTRACT_FROZEN_CONFLICT",
                    "Planning execution contract changed inside one identity",
                )
            return existing
        token = _token(f"{project_id}:{logical_ref}")
        return self.writer.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=operation_id,
                project_id=project_id,
                asset_id=f"production-execution-contract:{token}",
                asset_type=asset_type,
                schema_version="production-execution-contract.v1",
                logical_ref=logical_ref,
                category="production_execution_contracts",
                output_key=f"production_execution.contract.{asset_type}.{token}",
                role="execution_contract",
                content={"contract": contract},
                qualification_policy="production-execution-contract-v1",
                trace_id=trace_id,
                correlation_id=correlation_id,
            )
        )


__all__ = [
    "PostgresPlanningExecutionPreparer",
    "planning_fixture_response",
    "planning_provider_output_schema",
]
