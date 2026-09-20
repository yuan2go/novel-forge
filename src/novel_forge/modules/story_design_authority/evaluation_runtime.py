from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import hashlib
import json
from typing import Any, Protocol
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_handler_runtime import (
    AuthorityHandlerOutput,
    AuthorityHandlerRegistration,
    AuthorityHandlerRequest,
)
from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.budget_runtime import (
    resolve_provider_budget_failure_in_uow,
)
from novel_forge.modules.command_kernel.cancellation import (
    cancel_unstarted_operation_in_uow,
)
from novel_forge.modules.command_kernel.attempt_runtime import _transition_attempt
from novel_forge.modules.command_kernel.operation_graph import (
    GraphCommandContext,
    start_saga,
)
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
    transition_operation_in_uow,
)
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    admit_command_in_uow,
)
from novel_forge.modules.content_authority.scheduler import ContentAuthorityScheduler
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .domain import GENERATOR_DESIGN_SCOPE
from .qualification import (
    NarrativeEvaluationLineage,
    NarrativeQualificationProfile,
    NarrativeQualificationResult,
    required_qualification_profiles,
    validate_narrative_qualification,
)
from .evaluation_reference import (
    reference_command_fields, require_reference_review, reference_agreement,
)
from .replacement_gate import (
    assert_narrative_replacement_execution_gate,
    assert_narrative_replacement_execution_gate_in_uow,
)


NARRATIVE_EVALUATION_DEFINITION = "story_design.semantic_evaluate"
NARRATIVE_EVALUATION_VERSION = "1.0.0"
NARRATIVE_EVALUATION_HANDLER = "novel_forge.story_design.semantic_evaluate"
NARRATIVE_EVALUATION_APPLICATION_BUILD_ID = (
    "canonical-narrative-semantic-evaluation-runtime"
)
NARRATIVE_EVALUATION_DURABLE_REPLAY_VERSION = (
    "narrative-evaluation-durable-success-replay.v1"
)


class NarrativeEvaluationExternalEffectDisposition(StrEnum):
    PROVEN_NO_EFFECT = "PROVEN_NO_EFFECT"
    PROVEN_SUCCESS = "PROVEN_SUCCESS"
    PROVEN_TERMINAL_FAILURE = "PROVEN_TERMINAL_FAILURE"
    UNKNOWN_AMBIGUOUS = "UNKNOWN_AMBIGUOUS"


def classify_narrative_evaluation_external_effects(
    rows: Iterable[Mapping[str, object]],
) -> NarrativeEvaluationExternalEffectDisposition:
    """INVARIANT: Classify only durable Effect/Dispatch/Receipt evidence.

    Absence of an Effect is the sole no-effect proof. Once an Effect exists,
    missing dispatch/receipt evidence or any in-flight/unknown state is
    ambiguous and must be reconciled by the existing ExternalEffect runtime.
    """
    evidence = tuple(dict(row) for row in rows)
    if not evidence:
        return NarrativeEvaluationExternalEffectDisposition.PROVEN_NO_EFFECT
    effect_ids = {str(row.get("external_effect_id") or "") for row in evidence}
    if "" in effect_ids or len(effect_ids) != 1:
        return NarrativeEvaluationExternalEffectDisposition.UNKNOWN_AMBIGUOUS
    effect_statuses = {str(row.get("effect_status") or "") for row in evidence}
    dispatch_statuses = {
        str(row.get("dispatch_status") or "")
        for row in evidence
        if row.get("dispatch_id") is not None
    }
    dispatch_ids = [
        str(row.get("dispatch_id") or "")
        for row in evidence
        if row.get("dispatch_id") is not None
    ]
    if "" in dispatch_ids or len(dispatch_ids) != len(set(dispatch_ids)):
        # INVARIANT: one classifier row per dispatch is the cardinality contract. A
        # repeated dispatch means multiple receipts (or otherwise duplicated
        # durable evidence) and must never be collapsed into apparent success.
        return NarrativeEvaluationExternalEffectDisposition.UNKNOWN_AMBIGUOUS
    if len(effect_statuses) != 1 or "" in effect_statuses:
        return NarrativeEvaluationExternalEffectDisposition.UNKNOWN_AMBIGUOUS
    effect_status = next(iter(effect_statuses))
    ambiguous_effects = {
        "READY",
        "DISPATCHING",
        "DISPATCHED",
        "FAILED_RETRYABLE",
        "UNKNOWN",
        "RECONCILIATION_REQUIRED",
        "CANCELLATION_REQUESTED",
        "COMPENSATION_REQUIRED",
        "COMPENSATING",
    }
    ambiguous_dispatches = {
        "CREATED",
        "DISPATCHING",
        "ACKNOWLEDGED",
        "FAILED_RETRYABLE",
        "UNKNOWN",
        "CANCEL_REQUESTED",
    }
    if (
        effect_status in ambiguous_effects
        or not dispatch_statuses
        or dispatch_statuses & ambiguous_dispatches
    ):
        return NarrativeEvaluationExternalEffectDisposition.UNKNOWN_AMBIGUOUS
    if effect_status == "SUCCEEDED":
        succeeded = sum(
            1
            for row in evidence
            if row.get("dispatch_status") == "SUCCEEDED"
            and row.get("receipt_status") == "VERIFIED"
        )
        if succeeded == 1 and dispatch_statuses <= {
            "SUCCEEDED",
            "FAILED_FINAL",
            "CANCELLED",
            "SUPERSEDED",
            "DEAD_LETTER",
        }:
            return NarrativeEvaluationExternalEffectDisposition.PROVEN_SUCCESS
        return NarrativeEvaluationExternalEffectDisposition.UNKNOWN_AMBIGUOUS
    if effect_status in {
        "FAILED_FINAL",
        "CANCELLED",
        "COMPENSATED",
        "DEAD_LETTER",
    } and (
        dispatch_statuses <= {"FAILED_FINAL", "CANCELLED", "SUPERSEDED", "DEAD_LETTER"}
    ):
        return NarrativeEvaluationExternalEffectDisposition.PROVEN_TERMINAL_FAILURE
    return NarrativeEvaluationExternalEffectDisposition.UNKNOWN_AMBIGUOUS


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _stable_id(prefix: str, *parts: object) -> str:
    identity = "\x1f".join(str(item) for item in parts)
    return f"{prefix}:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _evaluation_command_payload_matches(
    stored: Mapping[str, Any], expected: Mapping[str, Any]
) -> bool:
    """COMPATIBILITY: Compare a caller command with a generation-aware frozen command.

    A successful-effect replacement carries three additional immutable evidence
    inputs and a replay bundle.  Those fields authorize projection of the old
    durable result; they do not change the original candidate evaluation
    request that callers replay after recovery.
    """

    def normalized(value: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(value)
        payload = dict(result.get("payload") or {})
        # INVARIANT: pre-fence commands represent only the unbound empty snapshot;
        # a non-empty server-derived Opening fence must still match exactly.
        payload.setdefault("opening_execution_binding", {})
        if payload.get("reference_evaluation"):
            payload.pop("routing_bootstrap_authorization", None)
        result["payload"] = payload
        return result

    normalized_stored = normalized(stored)
    normalized_expected = normalized(expected)
    if normalized_stored == normalized_expected:
        return True
    stored_payload = dict(normalized_stored.get("payload") or {})
    replay = stored_payload.pop("durable_success_replay", None)
    if not isinstance(replay, Mapping):
        return False
    expected_payload = dict(normalized_expected.get("payload") or {})
    if stored_payload != expected_payload:
        return False
    expected_inputs = list(normalized_expected.get("input_asset_version_ids") or [])
    replay_inputs = [
        str(replay.get("model_call_asset_version_id") or ""),
        str(replay.get("cost_ledger_asset_version_id") or ""),
        str(replay.get("source_evaluation_asset_version_id") or ""),
    ]
    if any(not item for item in replay_inputs):
        return False
    return str(normalized_stored.get("project_id") or "") == str(
        normalized_expected.get("project_id") or ""
    ) and list(normalized_stored.get("input_asset_version_ids") or []) == [
        *expected_inputs,
        *replay_inputs,
    ]


def _evaluation_lifecycle(operation_status: str) -> str:
    if operation_status == "SUCCEEDED":
        return "SUCCEEDED"
    if operation_status == "CANCELLED":
        return "CANCELLED"
    if operation_status == "DEAD_LETTER":
        return "DEAD_LETTER"
    if operation_status in {
        "FAILED_FINAL",
        "COMPENSATED",
        "COMPENSATION_FAILED",
    }:
        return "FAILED"
    if operation_status == "RECONCILIATION_REQUIRED":
        return "RECONCILIATION_REQUIRED"
    if operation_status in {
        "EXECUTING",
        "WAITING_CHILDREN",
        "WAITING_EXTERNAL_RESULT",
        "WAITING_GATE",
        "FAILED_RETRYABLE",
        "CANCELLATION_REQUESTED",
        "COMPENSATION_REQUIRED",
        "COMPENSATING",
    }:
        return "RUNNING"
    return "ADMITTED"


@dataclass(frozen=True, slots=True)
class NarrativeSemanticEvaluationCommand:
    project_id: str
    workspace_id: str
    book_id: str
    actor_id: str
    candidate_asset_version_id: str
    generation_operation_id: str
    generator_operation_name: str
    candidate_content_hash: str
    evaluator_execution_class: str
    idempotency_key: str
    trace_id: str
    correlation_id: str
    evaluation: dict[str, Any] | None = None
    evidence_asset_version_ids: tuple[str, ...] = ()
    routing_bootstrap_authorization_id: str = ""
    reference_evaluation: Mapping[str, Any] | None = None
    reference_predecessor_operation_id: str = ""

    def __post_init__(self) -> None:
        required = (
            self.project_id,
            self.workspace_id,
            self.book_id,
            self.actor_id,
            self.candidate_asset_version_id,
            self.generation_operation_id,
            self.generator_operation_name,
            self.idempotency_key,
            self.trace_id,
            self.correlation_id,
        )
        if any(not item.strip() for item in required):
            raise ValueError("Narrative Semantic Evaluation command is incomplete")
        reference_command_fields(self)
        digest = self.candidate_content_hash.removeprefix("sha256:")
        if (
            not self.candidate_content_hash.startswith("sha256:")
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError(
                "Narrative Semantic Evaluation requires a SHA-256 candidate"
            )
        if self.evaluator_execution_class not in {
            "MODEL_PROVIDER",
            "SCRIPTED_FIXTURE",
            "OPERATOR_REVIEW",
        }:
            raise ValueError("Narrative Semantic Evaluation class is unsupported")
        if self.evaluator_execution_class == "MODEL_PROVIDER" and (
            self.evaluation is not None or self.evidence_asset_version_ids
        ):
            raise ValueError(
                "model-provider Narrative Evaluation is produced by the governed runtime"
            )
        if self.evaluator_execution_class != "MODEL_PROVIDER" and not isinstance(
            self.evaluation, dict
        ):
            raise ValueError(
                "fixture or operator Narrative Evaluation requires an explicit result"
            )


def evaluation_command_payload(
    command: NarrativeSemanticEvaluationCommand, *, generation_actor_id: str,
    opening_execution_binding: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        **reference_command_fields(command),
        "candidate_asset_version_id": command.candidate_asset_version_id,
        "candidate_content_hash": command.candidate_content_hash,
        "generation_operation_id": command.generation_operation_id,
        "generation_actor_id": generation_actor_id,
        "generator_operation_name": command.generator_operation_name,
        "book_id": command.book_id,
        "evaluator_execution_class": command.evaluator_execution_class,
        "evaluation": None if command.evaluation is None else dict(command.evaluation),
        "opening_execution_binding": dict(opening_execution_binding),
    }


@dataclass(frozen=True, slots=True)
class NarrativeSemanticEvaluationReplacementCommand:
    predecessor_operation_id: str
    expected_head_generation: int
    expected_head_version: int
    recovery_intent_id: str
    actor_id: str
    trace_id: str
    correlation_id: str

    def __post_init__(self) -> None:
        required = (
            self.predecessor_operation_id,
            self.recovery_intent_id,
            self.actor_id,
            self.trace_id,
            self.correlation_id,
        )
        if any(not value.strip() for value in required):
            raise ValueError("Narrative Evaluation replacement identity is incomplete")
        if self.expected_head_generation <= 0 or self.expected_head_version < 0:
            raise ValueError("Narrative Evaluation replacement generation is invalid")

    @property
    def successor_generation(self) -> int:
        return self.expected_head_generation + 1


@dataclass(frozen=True, slots=True)
class NarrativeProviderEvaluation:
    evaluation: dict[str, Any]
    model_call_log_asset_version_id: str
    model_call_log_content_hash: str
    provider_evidence_hash: str
    provider_result_hash: str
    provider_id: str
    model_id: str
    route_snapshot_id: str
    prompt_version: str
    skill_version: str
    real_model_call: bool

    def __post_init__(self) -> None:
        required = (
            self.model_call_log_asset_version_id,
            self.provider_id,
            self.model_id,
            self.route_snapshot_id,
            self.prompt_version,
            self.skill_version,
        )
        if not self.evaluation or any(not value.strip() for value in required):
            raise ValueError("Narrative Provider Evaluation evidence is incomplete")
        for value in (
            self.model_call_log_content_hash,
            self.provider_evidence_hash,
            self.provider_result_hash,
        ):
            digest = value.removeprefix("sha256:")
            if (
                not value.startswith("sha256:")
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise ValueError(
                    "Narrative Provider Evaluation evidence must be SHA-256 bound"
                )
        if not self.real_model_call:
            raise ValueError(
                "production Narrative Provider Evaluation requires a real model call"
            )


class NarrativeSemanticEvaluationExecutionPort(Protocol):
    production_execution_gateway_backed: bool
    external_effect_backed: bool

    def evaluate(
        self,
        request: AuthorityHandlerRequest,
        *,
        candidate: Any,
        generator_operation_name: str,
        profiles: tuple[NarrativeQualificationProfile, ...],
    ) -> NarrativeProviderEvaluation: ...


@dataclass(frozen=True, slots=True)
class NarrativeSemanticEvaluationResult:
    lineage: NarrativeEvaluationLineage
    qualification: NarrativeQualificationResult
    evaluation_content: dict[str, Any]
    replayed: bool


class NarrativeSemanticEvaluationHandler:
    def __init__(
        self,
        *,
        execution_port: NarrativeSemanticEvaluationExecutionPort | None = None,
        allow_scripted_fixture: bool = False,
    ) -> None:
        if execution_port is not None and (
            not getattr(execution_port, "production_execution_gateway_backed", False)
            or not getattr(execution_port, "external_effect_backed", False)
        ):
            raise ValueError(
                "Narrative Evaluation must use the ExternalEffect-backed Production Execution Gateway"
            )
        self.execution_port = execution_port
        self.allow_scripted_fixture = allow_scripted_fixture

    def execute(self, request: AuthorityHandlerRequest) -> AuthorityHandlerOutput:
        payload = request.command.get("payload")
        if not isinstance(payload, dict):
            raise KernelError(
                "NARRATIVE_EVALUATION_INPUT_INVALID",
                "Narrative Evaluation payload must be an object",
            )
        candidate_id = str(payload.get("candidate_asset_version_id") or "")
        candidate = next(
            (item for item in request.inputs if item.asset_version_id == candidate_id),
            None,
        )
        candidate_hash = str(payload.get("candidate_content_hash") or "")
        generation_operation_id = str(payload.get("generation_operation_id") or "")
        generation_actor_id = str(payload.get("generation_actor_id") or "")
        execution_class = str(payload.get("evaluator_execution_class") or "")
        if (
            candidate is None
            or candidate.content_hash != candidate_hash
            or request.operation_id == generation_operation_id
            or not generation_operation_id
            or not generation_actor_id
            or (
                execution_class != "SCRIPTED_FIXTURE"
                and generation_actor_id == request.actor_id
            )
        ):
            raise KernelError(
                "NARRATIVE_EVALUATION_LINEAGE_INVALID",
                "Narrative Evaluation must bind a distinct generation Operation and exact candidate",
            )
        evidence_inputs = tuple(
            item for item in request.inputs if item is not candidate
        )
        reference = None
        if payload.get("reference_evaluation"):
            if execution_class != "MODEL_PROVIDER" or candidate.content.get("routing_eligibility") != "BENCHMARK_ONLY":
                raise KernelError("NARRATIVE_REFERENCE_TARGET_FORBIDDEN",
                                  "reference sampling requires an isolated benchmark candidate")
            reference = require_reference_review(
                getattr(self.execution_port, "database_url", ""),
                project_id=request.project_id, payload=payload, evaluator_actor_id=request.actor_id,
            )
        provider_result: NarrativeProviderEvaluation | None = None
        evaluation = payload.get("evaluation")
        if execution_class == "MODEL_PROVIDER":
            durable_replay = payload.get("durable_success_replay")
            if durable_replay is not None:
                return self._replay_durable_success(
                    request,
                    candidate=candidate,
                    evidence_inputs=evidence_inputs,
                    replay=durable_replay,
                )
            if evidence_inputs or evaluation is not None:
                raise KernelError(
                    "NARRATIVE_EVALUATION_PROVIDER_INPUT_INVALID",
                    "provider evaluation result and evidence must be produced inside the Evaluation Attempt",
                )
            if self.execution_port is None:
                raise KernelError(
                    "NARRATIVE_EVALUATION_PROVIDER_RUNTIME_REQUIRED",
                    "model-provider evaluation has no governed Production Execution port",
                )
            provider_result = self.execution_port.evaluate(
                request,
                candidate=candidate,
                generator_operation_name=str(
                    payload.get("generator_operation_name") or ""
                ),
                profiles=required_qualification_profiles(
                    str(payload.get("generator_operation_name") or "")
                ),
            )
            evaluation = provider_result.evaluation
        elif execution_class == "SCRIPTED_FIXTURE":
            if not self.allow_scripted_fixture:
                raise KernelError(
                    "NARRATIVE_EVALUATION_FIXTURE_FORBIDDEN",
                    "SCRIPTED_FIXTURE Narrative Evaluation is disabled outside an explicit test runtime",
                )
        else:
            review = evidence_inputs[0] if len(evidence_inputs) == 1 else None
            review_content = dict(review.content) if review is not None else {}
            if (
                review is None
                or review.asset_type != "narrative_design_operator_review"
                or review_content.get("contract_version")
                != "narrative-design-operator-review.v1"
                or review_content.get("candidate_asset_version_id") != candidate_id
                or review_content.get("candidate_content_hash") != candidate_hash
                or review_content.get("evaluation") != evaluation
                or review_content.get("evaluator_execution_class") != "OPERATOR_REVIEW"
                or review_content.get("human_preference_evidence") is not False
                or review_content.get("provider_evidence_claimed") is not False
            ):
                raise KernelError(
                    "NARRATIVE_EVALUATION_OPERATOR_EVIDENCE_REQUIRED",
                    "operator evaluation requires one exact immutable non-human review evidence asset",
                )
        qualification = validate_narrative_qualification(
            generator_operation_name=str(payload.get("generator_operation_name") or ""),
            value=evaluation,
            require_pass=False,
        )
        reference_result = (reference_agreement(payload=payload, reference=reference, evaluation=evaluation)
                            if reference is not None else None)
        provider_evidence = (
            [
                {
                    "asset_version_id": provider_result.model_call_log_asset_version_id,
                    "content_hash": provider_result.model_call_log_content_hash,
                }
            ]
            if provider_result is not None
            else [
                {
                    "asset_version_id": item.asset_version_id,
                    "content_hash": item.content_hash,
                }
                for item in evidence_inputs
            ]
        )
        evidence_hash = _canonical_hash(
            {
                "evaluation": evaluation,
                "candidate_asset_version_id": candidate_id,
                "candidate_content_hash": candidate_hash,
                "generation_operation_id": generation_operation_id,
                "evaluation_operation_id": request.operation_id,
                "evaluation_attempt_id": request.attempt_id,
                "provider_evidence": provider_evidence,
                **({"reference_evaluation": reference_result} if reference_result else {}),
                "provider_evidence_hash": (
                    provider_result.provider_evidence_hash
                    if provider_result is not None
                    else ""
                ),
            }
        )
        reference_asset_version_ids = (
            candidate.asset_version_id,
            *((payload["reference_evaluation"]["asset_version_id"],) if reference_result else ()),
            *(tuple(item["asset_version_id"] for item in payload["reference_evaluation"].get("adjudicated_reference", {}).get("adjudications", ()))
                if reference_result else ()),
            *(
                (provider_result.model_call_log_asset_version_id,)
                if provider_result is not None
                else tuple(item.asset_version_id for item in evidence_inputs)
            ),
        )
        return AuthorityHandlerOutput(
            asset_type="narrative_design_evaluation",
            output_key="story_design.semantic_evaluation",
            role="qualification_evidence",
            content={
                "schema_version": "narrative-design-evaluation.v1",
                **({"reference_evaluation": reference_result,
                    "routing_eligibility": "BENCHMARK_ONLY",
                    "production_qualification_eligible": False} if reference_result else {}),
                "project_id": request.project_id,
                "candidate_asset_version_id": candidate_id,
                "candidate_content_hash": candidate_hash,
                "generation_operation_id": generation_operation_id,
                "evaluation_operation_id": request.operation_id,
                "evaluation_attempt_id": request.attempt_id,
                "evaluator_execution_class": execution_class,
                "evaluation": dict(evaluation),
                "qualification": qualification.to_evidence(),
                "evaluation_evidence_hash": evidence_hash,
                "provider_evidence_asset_version_ids": [
                    item["asset_version_id"] for item in provider_evidence
                ],
                "provider_evidence": provider_evidence,
                "provider_execution": (
                    {
                        "provider_id": provider_result.provider_id,
                        "model_id": provider_result.model_id,
                        "route_snapshot_id": provider_result.route_snapshot_id,
                        "prompt_version": provider_result.prompt_version,
                        "skill_version": provider_result.skill_version,
                        "provider_evidence_hash": (
                            provider_result.provider_evidence_hash
                        ),
                        "provider_result_hash": provider_result.provider_result_hash,
                    }
                    if provider_result is not None
                    else {}
                ),
            },
            qualification_policy="independent-narrative-evaluation-v1",
            reference_asset_version_ids=reference_asset_version_ids,
            evidence={
                "independent_from_generation": True,
                "evaluation_attempt_id": request.attempt_id,
                "evaluation_evidence_hash": evidence_hash,
            },
        )

    @staticmethod
    def _replay_durable_success(
        request: AuthorityHandlerRequest,
        *,
        candidate: Any,
        evidence_inputs: tuple[Any, ...],
        replay: object,
    ) -> AuthorityHandlerOutput:

        if not isinstance(replay, Mapping):
            raise KernelError(
                "NARRATIVE_EVALUATION_DURABLE_REPLAY_INVALID",
                "durable-success replay metadata must be an object",
            )
        frozen = dict(replay)
        bundle_hash = str(frozen.pop("bundle_hash", ""))
        if (
            frozen.get("schema_version") != NARRATIVE_EVALUATION_DURABLE_REPLAY_VERSION
            or not bundle_hash
            or _canonical_hash(frozen) != bundle_hash
        ):
            raise KernelError(
                "NARRATIVE_EVALUATION_DURABLE_REPLAY_INVALID",
                "durable-success replay metadata hash is invalid",
            )
        by_id = {item.asset_version_id: item for item in evidence_inputs}
        expected_ids = {
            str(frozen.get("model_call_asset_version_id") or ""),
            str(frozen.get("cost_ledger_asset_version_id") or ""),
            str(frozen.get("source_evaluation_asset_version_id") or ""),
        }
        if "" in expected_ids or set(by_id) != expected_ids:
            raise KernelError(
                "NARRATIVE_EVALUATION_DURABLE_REPLAY_INVALID",
                "durable-success replay inputs differ from the admitted bundle",
            )
        model = by_id[str(frozen["model_call_asset_version_id"])]
        cost = by_id[str(frozen["cost_ledger_asset_version_id"])]
        source = by_id[str(frozen["source_evaluation_asset_version_id"])]
        if (
            model.asset_type != "model_call_log"
            or cost.asset_type != "cost_ledger"
            or source.asset_type != "narrative_design_evaluation"
            or model.content_hash != frozen.get("model_call_content_hash")
            or cost.content_hash != frozen.get("cost_ledger_content_hash")
            or source.content_hash != frozen.get("source_evaluation_content_hash")
        ):
            raise KernelError(
                "NARRATIVE_EVALUATION_DURABLE_REPLAY_INVALID",
                "durable-success replay assets no longer match their frozen hashes",
            )
        source_content = dict(source.content)
        model_content = dict(model.content)
        cost_content = dict(cost.content)
        source_operation_id = str(frozen.get("source_operation_id") or "")
        source_attempt_id = str(frozen.get("source_attempt_id") or "")
        external_effect_id = str(frozen.get("external_effect_id") or "")
        provider_evidence = model_content.get("provider_evidence")
        provider_execution = source_content.get("provider_execution")
        model_target = model_content.get("target_lineage")
        expected_target = {
            "target_asset_version_id": candidate.asset_version_id,
            "target_content_hash": candidate.content_hash,
            "generation_operation_id": str(
                request.command["payload"].get("generation_operation_id") or ""
            ),
            "generator_operation_name": str(
                request.command["payload"].get("generator_operation_name") or ""
            ),
        }
        valid = (
            source_operation_id
            and source_attempt_id
            and external_effect_id
            and model_content.get("operation_id") == source_operation_id
            and model_content.get("attempt_id") == source_attempt_id
            and model_content.get("external_effect_id") == external_effect_id
            and model_content.get("stage") == "narrative_semantic_evaluation"
            and model_target == expected_target
            and cost_content.get("operation_id") == source_operation_id
            and cost_content.get("attempt_id") == source_attempt_id
            and cost_content.get("external_effect_id") == external_effect_id
            and cost_content.get("stage") == "narrative_semantic_evaluation"
            and source_content.get("candidate_asset_version_id")
            == candidate.asset_version_id
            and source_content.get("candidate_content_hash") == candidate.content_hash
            and source_content.get("generation_operation_id")
            == expected_target["generation_operation_id"]
            and source_content.get("evaluation_operation_id") == source_operation_id
            and source_content.get("evaluation_attempt_id") == source_attempt_id
            and source_content.get("evaluator_execution_class") == "MODEL_PROVIDER"
            and source_content.get("provider_evidence_asset_version_ids")
            == [model.asset_version_id]
            and source_content.get("provider_evidence")
            == [
                {
                    "asset_version_id": model.asset_version_id,
                    "content_hash": model.content_hash,
                }
            ]
            and isinstance(provider_evidence, Mapping)
            and provider_evidence.get("real_model_call") is True
            and source_content.get("evaluation") == provider_evidence.get("result")
            and isinstance(provider_execution, Mapping)
            and provider_execution.get("provider_evidence_hash")
            == frozen.get("provider_evidence_hash")
            and provider_execution.get("provider_result_hash")
            == frozen.get("provider_result_hash")
            and provider_execution.get("route_snapshot_id")
            == frozen.get("provider_route_snapshot_id")
            and _canonical_hash(dict(provider_evidence))
            == frozen.get("provider_evidence_hash")
            and _canonical_hash(provider_evidence.get("result"))
            == frozen.get("provider_result_hash")
        )
        if not valid:
            raise KernelError(
                "NARRATIVE_EVALUATION_DURABLE_REPLAY_INVALID",
                "durable-success replay lineage no longer matches exact Provider evidence",
            )
        qualification = validate_narrative_qualification(
            generator_operation_name=expected_target["generator_operation_name"],
            value=source_content.get("evaluation"),
            require_pass=False,
        )
        if source_content.get("qualification") != qualification.to_evidence():
            raise KernelError(
                "NARRATIVE_EVALUATION_DURABLE_REPLAY_INVALID",
                "durable-success replay qualification evidence is inconsistent",
            )
        projected = dict(source_content)
        projected["durable_success_replay"] = {
            "schema_version": NARRATIVE_EVALUATION_DURABLE_REPLAY_VERSION,
            "bundle_hash": bundle_hash,
            "source_evaluation_asset_version_id": source.asset_version_id,
            "source_operation_id": source_operation_id,
            "source_attempt_id": source_attempt_id,
            "replacement_operation_id": request.operation_id,
            "replacement_attempt_id": request.attempt_id,
            "external_effect_id": external_effect_id,
        }
        return AuthorityHandlerOutput(
            asset_type="narrative_design_evaluation",
            output_key="story_design.semantic_evaluation",
            role="qualification_evidence",
            content=projected,
            qualification_policy="independent-narrative-evaluation-v1",
            reference_asset_version_ids=(
                candidate.asset_version_id,
                model.asset_version_id,
                cost.asset_version_id,
                source.asset_version_id,
            ),
            evidence={
                "independent_from_generation": True,
                "durable_success_replay": True,
                "source_evaluation_asset_version_id": source.asset_version_id,
                "bundle_hash": bundle_hash,
            },
        )


class NarrativeSemanticEvaluationRegistry:
    def __init__(
        self,
        *,
        execution_port: NarrativeSemanticEvaluationExecutionPort | None = None,
        allow_scripted_fixture: bool = False,
    ) -> None:
        item = AuthorityHandlerRegistration(
            definition_name=NARRATIVE_EVALUATION_DEFINITION,
            definition_version=NARRATIVE_EVALUATION_VERSION,
            handler_key=NARRATIVE_EVALUATION_HANDLER,
            handler_contract_version="narrative-evaluation-handler-v1",
            output_asset_type="narrative_design_evaluation",
            output_key="story_design.semantic_evaluation",
            role="qualification_evidence",
            completion_topic="story_design.semantic_evaluation.materialized",
            handler=NarrativeSemanticEvaluationHandler(
                execution_port=execution_port,
                allow_scripted_fixture=allow_scripted_fixture,
            ),
        )
        self.item = item

    @property
    def available_handler_keys(self) -> frozenset[str]:
        return frozenset({self.item.handler_key})

    @property
    def definition_names(self) -> frozenset[str]:
        return frozenset({self.item.definition_name})

    def registration(
        self, definition_name: str, definition_version: str
    ) -> AuthorityHandlerRegistration:
        if (
            definition_name != self.item.definition_name
            or definition_version != self.item.definition_version
        ):
            raise KeyError((definition_name, definition_version))
        return self.item


def narrative_semantic_evaluation_definition(
    *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    schema = {
        "type": "object",
        "required": ["project_id", "input_asset_version_ids", "payload"],
        "properties": {
            "project_id": {"type": "string"},
            "input_asset_version_ids": {"type": "array", "minItems": 1},
            "payload": {"type": "object"},
        },
        "additionalProperties": False,
    }
    return {
        "name": NARRATIVE_EVALUATION_DEFINITION,
        "definition_version": NARRATIVE_EVALUATION_VERSION,
        "family": "story_design_authority",
        "enabled": True,
        "definition_status": "implemented",
        "command_schema_version": "narrative-semantic-evaluation-command-v1",
        "result_schema_version": "narrative-design-evaluation.v1",
        "command_schema": schema,
        "result_schema": {"type": "object"},
        "input_contract": schema,
        "output_contract": {
            "asset_type": "narrative_design_evaluation",
            "output_key": "story_design.semantic_evaluation",
        },
        "handler_key": NARRATIVE_EVALUATION_HANDLER,
        "handler_contract_version": "narrative-evaluation-handler-v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "worker",
        "permissions": ["narrative_design.evaluate"],
        "approval_policy": {"required": False},
        "policy": {
            "candidate_generation_operation_must_differ": True,
            "non_fixture_evaluator_actor_must_differ": True,
            "candidate_content_hash_required": True,
            "candidate_evaluation_input_allowed": False,
            "evaluation_candidate_asset_input_allowed": True,
            "model_provider_evidence_produced_inside_attempt": True,
            "model_provider_evidence_exact_result_required": True,
            "qualification_authority": "story_design_authority",
        },
        "idempotency_scope": "book:narrative-semantic-evaluation",
        "concurrency_key_template": "book:{book_id}:evaluation:{logical_key}",
        "retry_policy": {"max_attempts": 3, "dead_letter_on_exhausted": True},
        "timeout_policy": {"operation_timeout_seconds": 3000},
        "cancellation_policy": {"mode": "cancel_active_attempt"},
        "compensation_policy": {
            "supported": False,
            "reason": "append-only evaluation evidence",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": ["model.narrative_semantic_evaluation"],
        "projection_consumers": ["story_design_authority"],
        "migration_owner": "story-design-authority",
        "completion_contract": {
            "version": "narrative-semantic-evaluation-completion-v1",
            "required_asset_selectors": [
                {
                    "selector": "narrative_design_evaluation",
                    "output_key": "story_design.semantic_evaluation",
                    "role": "qualification_evidence",
                    "lifecycle": "ACTIVE",
                    "eligibility": "ELIGIBLE",
                    "governance": "CLEAR",
                }
            ],
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": ["story_design.semantic_evaluation.materialized"],
        },
    }


class NarrativeSemanticEvaluationApplication:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        worker_id: str = "narrative-semantic-evaluation-worker",
        execution_port: NarrativeSemanticEvaluationExecutionPort | None = None,
        allow_scripted_fixture: bool = False,
    ) -> None:
        if not database_url or not application_build_id or len(commit_sha) != 40:
            raise ValueError(
                "Narrative Evaluation requires PostgreSQL and build identity"
            )
        self.database_url = database_url
        # INVARIANT: the shared worker release identity cannot depend on which
        # application composition registers first.
        self.application_build_id = NARRATIVE_EVALUATION_APPLICATION_BUILD_ID
        self.commit_sha = commit_sha
        self.worker_id = worker_id
        self.execution_port = execution_port
        self.allow_scripted_fixture = allow_scripted_fixture
        self.registry = NarrativeSemanticEvaluationRegistry(
            execution_port=execution_port,
            allow_scripted_fixture=allow_scripted_fixture,
        )

    def prepare_reference_evaluation(
        self, command: NarrativeSemanticEvaluationCommand, *, principal: Principal,
    ) -> dict[str, Any]:
        principal.require("narrative_design.evaluate", command.project_id)
        if principal.principal_id != command.actor_id:
            raise PermissionError("reference evaluator must be the trusted Principal")
        if not command.routing_bootstrap_authorization_id:
            raise ValueError("reference preparation requires an explicit grant identity")
        candidate = self._require_candidate(command)
        if candidate["content"].get("routing_eligibility") != "BENCHMARK_ONLY":
            raise KernelError("NARRATIVE_REFERENCE_TARGET_FORBIDDEN",
                              "reference sampling requires an isolated benchmark candidate")
        payload = evaluation_command_payload(
            command, generation_actor_id=candidate["generation_actor_id"],
            opening_execution_binding=candidate["opening_execution_binding"],
        )
        require_reference_review(self.database_url, project_id=command.project_id,
                                 payload=payload, evaluator_actor_id=command.actor_id)
        from novel_forge.modules.command_kernel.routing_bootstrap import (
            authorization_hash, bootstrap_command_hash,
        )

        return {
            "schema_version": "narrative-reference-preflight.v1",
            "provider_calls": 0, "authorized": False,
            "definition_name": NARRATIVE_EVALUATION_DEFINITION,
            "definition_version": NARRATIVE_EVALUATION_VERSION,
            "idempotency_scope": "book:narrative-semantic-evaluation",
            "payload": payload, "command_hash": bootstrap_command_hash(payload),
            "input_versions_hash": authorization_hash(payload["input_versions"]),
            "required_task_type": "narrative_semantic_evaluation",
            "required_purpose": "REFERENCE_EVALUATION", "required_environment": "validation",
            "production_qualification_eligible": False,
        }

    def execute(
        self,
        command: NarrativeSemanticEvaluationCommand,
        *,
        principal: Principal,
        caller_permission: str,
    ) -> NarrativeSemanticEvaluationResult:
        del caller_permission
        principal.require("narrative_design.evaluate", command.project_id)
        if principal.principal_id != command.actor_id:
            raise PermissionError(
                "Narrative Evaluation actor must be the trusted Principal"
            )
        candidate = self._require_candidate(command)
        evidence_assets = [
            self._require_asset(command.project_id, item)
            for item in command.evidence_asset_version_ids
        ]
        if (
            command.evaluator_execution_class != "SCRIPTED_FIXTURE"
            and candidate["generation_actor_id"] == command.actor_id
        ):
            raise KernelError(
                "NARRATIVE_EVALUATION_ACTOR_NOT_INDEPENDENT",
                "non-fixture Narrative Evaluation requires a trusted actor distinct from generation",
            )
        if (
            command.evaluator_execution_class == "MODEL_PROVIDER"
            and self.execution_port is None
        ):
            raise KernelError(
                "NARRATIVE_EVALUATION_PROVIDER_RUNTIME_REQUIRED",
                "model-provider evaluation requires the governed Production Execution runtime",
            )
        if (
            command.evaluator_execution_class == "SCRIPTED_FIXTURE"
            and not self.allow_scripted_fixture
        ):
            raise KernelError(
                "NARRATIVE_EVALUATION_FIXTURE_FORBIDDEN",
                "SCRIPTED_FIXTURE Narrative Evaluation is not enabled for this runtime",
            )
        self._register_definition()
        inputs = [candidate, *evidence_assets]
        admission_command = {
            "definition_name": NARRATIVE_EVALUATION_DEFINITION,
            "definition_version": NARRATIVE_EVALUATION_VERSION,
            "project_id": command.project_id,
            "workspace_id": command.workspace_id,
            "book_id": command.book_id,
            "logical_key": (
                _stable_id("narrative-reference", command.candidate_asset_version_id,
                           command.routing_bootstrap_authorization_id)
                if command.routing_bootstrap_authorization_id else command.candidate_asset_version_id
            ),
            "actor_id": command.actor_id,
            "idempotency_scope": "book:narrative-semantic-evaluation",
            "idempotency_key": command.idempotency_key,
            "trace_id": command.trace_id,
            "span_id": str(uuid4()),
            "correlation_id": command.correlation_id,
            "causation_id": command.reference_predecessor_operation_id or command.generation_operation_id,
            "causation_operation_id": command.reference_predecessor_operation_id or command.generation_operation_id,
            "input": {
                "project_id": command.project_id,
                "input_asset_version_ids": [
                    item["asset_version_id"] for item in inputs
                ],
                "payload": evaluation_command_payload(
                    command, generation_actor_id=candidate["generation_actor_id"],
                    opening_execution_binding=candidate["opening_execution_binding"],
                ),
            },
            "input_assets": [
                {
                    "asset_version_id": item["asset_version_id"],
                    "content_hash": item["content_hash"],
                }
                for item in inputs
            ],
        }
        if command.routing_bootstrap_authorization_id:
            if candidate["content"].get("routing_eligibility") != "BENCHMARK_ONLY":
                raise KernelError("NARRATIVE_REFERENCE_TARGET_FORBIDDEN",
                                  "reference evaluation cannot replace production qualification")
            from novel_forge.modules.authority_handler_runtime.routing_bootstrap import freeze_bootstrap_authorization

            payload = admission_command["input"]["payload"]
            model_port = getattr(self.execution_port, "model_port", None)
            binder = getattr(model_port, "capability_binder", None)
            payload["routing_bootstrap_authorization"] = freeze_bootstrap_authorization(
                database_url=self.database_url, command_payload=payload, principal=principal,
                environment=str(getattr(binder, "pack_environment", "")),
                permission="narrative_design.evaluate",
                idempotency_scope="book:narrative-semantic-evaluation",
            )
            require_reference_review(self.database_url, project_id=command.project_id,
                                     payload=payload, evaluator_actor_id=command.actor_id)
        reference_sampling = bool(command.routing_bootstrap_authorization_id)
        if reference_sampling:
            with AuthorityUnitOfWork(self.database_url) as uow:
                self._lock_candidate(uow, project_id=command.project_id,
                                     candidate_asset_version_id=command.candidate_asset_version_id)
                self._require_candidate_in_uow(uow, command)
                self._validate_reference_predecessor(uow, command, admission_command["input"]["payload"])
                admitted = admit_command_in_uow(uow, admission_command,
                                                context=self._admission_context(command.actor_id))
                uow.commit()
            admitted = {**admitted, "generation": 1}
        else:
            admitted = self._admit_candidate_once(command, admission_command)
        operation_id = str(admitted["operation_id"])
        execution_generation = int(admitted["generation"])
        operation_actor_id = str(admitted.get("operation_actor_id") or command.actor_id)
        with AuthorityUnitOfWork(self.database_url) as uow:
            operation = uow.repositories.attempt_runtime.operation_state(
                operation_id, command.project_id
            )
        operation_status = str(operation["status"])
        replacement_execution = execution_generation > 1
        if replacement_execution and operation_status == "ADMITTED":
            raise KernelError(
                "NARRATIVE_EVALUATION_REPLACEMENT_EXECUTION_GATE_CLOSED",
                "replacement semantic Evaluation was not released by its live Book Opening execution",
            )
        terminal_operation_statuses = {
            "SUCCEEDED",
            "FAILED_FINAL",
            "CANCELLED",
            "DEAD_LETTER",
            "COMPENSATED",
            "COMPENSATION_FAILED",
        }
        if (
            replacement_execution
            and operation_status not in terminal_operation_statuses
        ):
            assert_narrative_replacement_execution_gate(
                self.database_url,
                operation_id=operation_id,
                project_id=command.project_id,
            )
        operation_was_unstarted = operation_status in {"ADMITTED", "READY"}
        if not replacement_execution and operation_status == "ADMITTED":
            transition_operation(
                self.database_url,
                OperationTransitionCommand(
                    operation_id=operation_id,
                    project_id=command.project_id,
                    expected_version=int(operation["version"]),
                    expected_status="ADMITTED",
                    target_status="READY",
                    actor_id=operation_actor_id,
                    reason="independent Narrative Evaluation inputs are frozen",
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    causation_id=command.generation_operation_id,
                ),
            )
        if operation_was_unstarted:
            start_saga(
                self.database_url,
                GraphCommandContext(
                    command.project_id,
                    operation_actor_id,
                    command.trace_id,
                    command.correlation_id,
                ),
                root_operation_id=operation_id,
            )
        if not reference_sampling:
            self._mark_execution_running(
                operation_id=operation_id, project_id=command.project_id
            )
        try:
            scheduled = ContentAuthorityScheduler(
                self.database_url,
                registry=self.registry,
                worker_id=self.worker_id,
            ).run_or_recover(operation_id=operation_id, project_id=command.project_id)
        except Exception:
            if not reference_sampling:
                self._synchronize_execution_for_operation(
                    operation_id=operation_id, project_id=command.project_id
                )
            raise
        if not reference_sampling:
            self._synchronize_execution_for_operation(
                operation_id=operation_id, project_id=command.project_id
            )
        evaluation_asset = self._require_asset(
            command.project_id, scheduled.output.asset_version_id
        )
        content = dict(evaluation_asset["content"])
        qualification = validate_narrative_qualification(
            generator_operation_name=command.generator_operation_name,
            value=content.get("evaluation"),
            require_pass=False,
        )
        evaluation_operation_id = operation_id
        evaluation_attempt_id = scheduled.attempt_id
        durable_replay = content.get("durable_success_replay")
        if durable_replay is not None:
            if not isinstance(durable_replay, Mapping):
                raise KernelError(
                    "NARRATIVE_EVALUATION_DURABLE_REPLAY_INVALID",
                    "materialized durable-success projection metadata is invalid",
                )
            evaluation_operation_id = str(
                durable_replay.get("source_operation_id") or ""
            )
            evaluation_attempt_id = str(durable_replay.get("source_attempt_id") or "")
            if (
                durable_replay.get("schema_version")
                != NARRATIVE_EVALUATION_DURABLE_REPLAY_VERSION
                or durable_replay.get("replacement_operation_id") != operation_id
                or durable_replay.get("replacement_attempt_id") != scheduled.attempt_id
                or content.get("evaluation_operation_id") != evaluation_operation_id
                or content.get("evaluation_attempt_id") != evaluation_attempt_id
                or not evaluation_operation_id
                or not evaluation_attempt_id
            ):
                raise KernelError(
                    "NARRATIVE_EVALUATION_DURABLE_REPLAY_INVALID",
                    "materialized projection differs from its predecessor execution lineage",
                )
        lineage = NarrativeEvaluationLineage(
            generation_operation_id=command.generation_operation_id,
            evaluation_operation_id=evaluation_operation_id,
            evaluation_attempt_id=evaluation_attempt_id,
            evaluation_asset_version_id=scheduled.output.asset_version_id,
            candidate_asset_version_id=command.candidate_asset_version_id,
            candidate_content_hash=command.candidate_content_hash,
            evaluator_execution_class=command.evaluator_execution_class,
            evaluation_evidence_hash=str(content.get("evaluation_evidence_hash") or ""),
            provider_model_call_asset_version_id=str(
                (content.get("provider_evidence_asset_version_ids") or [""])[0]
                if command.evaluator_execution_class == "MODEL_PROVIDER"
                else ""
            ),
            provider_model_call_content_hash=str(
                ((content.get("provider_evidence") or [{}])[0]).get("content_hash")
                if command.evaluator_execution_class == "MODEL_PROVIDER"
                else ""
            ),
            provider_evidence_hash=str(
                (content.get("provider_execution") or {}).get("provider_evidence_hash")
                or ""
            ),
            provider_result_hash=str(
                (content.get("provider_execution") or {}).get("provider_result_hash")
                or ""
            ),
            provider_route_snapshot_id=str(
                (content.get("provider_execution") or {}).get("route_snapshot_id") or ""
            ),
        )
        if command.routing_bootstrap_authorization_id:
            if content.get("production_qualification_eligible") is not False or not content.get("reference_evaluation"):
                raise KernelError("NARRATIVE_REFERENCE_RESULT_INVALID",
                                  "reference evaluation must retain its non-production evidence boundary")
        else:
            self._record_qualifications(command, lineage, qualification)
        return NarrativeSemanticEvaluationResult(
            lineage=lineage,
            qualification=qualification,
            evaluation_content=content,
            replayed=bool(admitted["replayed"]),
        )

    def _validate_reference_predecessor(
        self, uow: AuthorityUnitOfWork, command: NarrativeSemanticEvaluationCommand,
        payload: Mapping[str, Any],
    ) -> None:
        grant = payload["routing_bootstrap_authorization"]["authorization"]
        uow.cursor.execute(
            """SELECT operation_id,status,actor_id,idempotency_key,command_payload->'payload'
               FROM authority_operation
               WHERE project_id=%s AND definition_name='story_design.semantic_evaluate'
                 AND command_payload #>> '{payload,candidate_asset_version_id}'=%s
                 AND command_payload #>> '{payload,routing_bootstrap_authorization,authorization,candidate_id}'=%s
                 AND command_payload #>> '{payload,routing_bootstrap_authorization,authorization,model_revision}'=%s
               ORDER BY created_at,operation_id FOR UPDATE""",
            [command.project_id, command.candidate_asset_version_id,
             grant["candidate_id"], grant["model_revision"]],
        )
        rows = uow.cursor.fetchall()
        if any(row[3] == command.idempotency_key for row in rows):
            return
        if not rows:
            if command.reference_predecessor_operation_id:
                raise KernelError("NARRATIVE_REFERENCE_PREDECESSOR_INVALID",
                                  "reference predecessor must belong to this candidate and evaluator model")
            return
        prior = rows[-1]
        if command.reference_predecessor_operation_id != prior[0]:
            raise KernelError("NARRATIVE_REFERENCE_PREDECESSOR_REQUIRED",
                              "repeating an evaluator arm requires its latest native Operation lineage")
        prior_payload = dict(prior[4])
        prior_grant = prior_payload["routing_bootstrap_authorization"]["authorization"]
        if (prior[2] != command.actor_id or prior_payload["input_versions"] != payload["input_versions"]
            or prior_payload["reference_evaluation"] != payload["reference_evaluation"]
            or prior_grant["campaign"] != grant["campaign"]):
            raise KernelError("NARRATIVE_REFERENCE_PREDECESSOR_INVALID",
                              "reference replacement must preserve evaluator, inputs, labels and campaign sample")
        external = self._external_effect_evidence_in_uow(uow, operation_id=str(prior[0]))
        if (prior[1] not in {"FAILED_FINAL", "CANCELLED", "DEAD_LETTER"}
            or external["classification"] not in {"PROVEN_NO_EFFECT", "PROVEN_TERMINAL_FAILURE"}):
            raise KernelError("NARRATIVE_REFERENCE_PREDECESSOR_NOT_REPLACEABLE",
                              "recover the existing Operation; unknown or successful external results cannot be resent")

    def _admit_candidate_once(
        self,
        command: NarrativeSemanticEvaluationCommand,
        admission_command: dict[str, Any],
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as claim_uow:
            self._lock_candidate(
                claim_uow,
                project_id=command.project_id,
                candidate_asset_version_id=command.candidate_asset_version_id,
            )
            current = self._current_execution_in_uow(
                claim_uow,
                project_id=command.project_id,
                candidate_asset_version_id=command.candidate_asset_version_id,
                lock=True,
            )
            if current is not None:
                self._synchronize_execution_in_uow(claim_uow, current)
                if not _evaluation_command_payload_matches(
                    dict(current["command_payload"]), admission_command["input"]
                ):
                    raise KernelError(
                        "NARRATIVE_EVALUATION_CLAIM_CONFLICT",
                        "candidate Evaluation head is bound to different immutable inputs",
                    )
                from .formation_evaluation_recovery import try_admit_formation_continuation

                continuation = try_admit_formation_continuation(
                    self, claim_uow, command=command,
                    admission_command=admission_command, current=current,
                )
                if continuation is not None:
                    claim_uow.commit()
                    return continuation
                claim_uow.commit()
                return {
                    "operation_id": str(current["operation_id"]),
                    "operation_actor_id": str(current["operation_actor_id"]),
                    "evaluation_execution_id": str(current["evaluation_execution_id"]),
                    "generation": int(current["generation"]),
                    "replayed": True,
                }

            # INVARIANT: candidate eligibility is re-read under the per-candidate
            # transaction lock. Operation admission and the generation-1 head
            # are one commit boundary, so no operation-only orphan is created.
            self._require_candidate_in_uow(claim_uow, command)
            admitted = admit_command_in_uow(
                claim_uow,
                admission_command,
                context=self._admission_context(command.actor_id),
            )
            operation = self._operation_for_lineage_in_uow(
                claim_uow,
                operation_id=str(admitted["operation_id"]),
                project_id=command.project_id,
                lock=True,
            )
            if dict(operation["command_payload"]) != admission_command["input"]:
                raise KernelError(
                    "NARRATIVE_EVALUATION_CLAIM_CONFLICT",
                    "generation-1 Operation has different immutable inputs",
                )
            execution_id = _stable_id(
                "narrative-evaluation-execution",
                command.project_id,
                command.candidate_asset_version_id,
                1,
            )
            lifecycle = _evaluation_lifecycle(str(operation["status"]))
            terminal = lifecycle in {
                "SUCCEEDED",
                "FAILED",
                "CANCELLED",
                "DEAD_LETTER",
            }
            claim_uow.cursor.execute(
                """
                INSERT INTO authority_narrative_evaluation_execution(
                    evaluation_execution_id,project_id,book_id,
                    candidate_asset_version_id,candidate_content_hash,generation,
                    operation_id,idempotency_scope,idempotency_key,
                    concurrency_key,lifecycle,terminal_reason,started_at,
                    terminal_at
                ) VALUES (
                    %s,%s,%s,%s,%s,1,%s,%s,%s,%s,%s,%s,
                    CASE WHEN %s IN ('RUNNING','SUCCEEDED','FAILED','CANCELLED',
                                     'DEAD_LETTER','RECONCILIATION_REQUIRED')
                         THEN transaction_timestamp() END,
                    CASE WHEN %s THEN transaction_timestamp() END
                )
                """,
                [
                    execution_id,
                    command.project_id,
                    command.book_id,
                    command.candidate_asset_version_id,
                    command.candidate_content_hash,
                    operation["operation_id"],
                    operation["idempotency_scope"],
                    operation["idempotency_key"],
                    operation["concurrency_key"],
                    lifecycle,
                    Jsonb(
                        {"operation_status": operation["status"]} if terminal else {}
                    ),
                    lifecycle,
                    terminal,
                ],
            )
            claim_uow.cursor.execute(
                """
                INSERT INTO authority_narrative_evaluation_execution_head(
                    project_id,candidate_asset_version_id,current_execution_id,
                    current_generation
                ) VALUES (%s,%s,%s,1)
                """,
                [
                    command.project_id,
                    command.candidate_asset_version_id,
                    execution_id,
                ],
            )
            claim_uow.commit()
            return {
                **admitted,
                "operation_actor_id": str(operation["operation_actor_id"]),
                "evaluation_execution_id": execution_id,
                "generation": 1,
            }

    def admit_replacement_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        *,
        predecessor_operation_id: str,
        recovery_intent_id: str,
        actor_id: str,
        trace_id: str,
        correlation_id: str,
        expected_head_generation: int,
        expected_head_version: int,
    ) -> dict[str, Any]:
        """INVARIANT: the caller owns the transaction; verify recovery evidence without starting an Attempt or Provider call."""

        replacement = NarrativeSemanticEvaluationReplacementCommand(
            predecessor_operation_id=predecessor_operation_id,
            expected_head_generation=expected_head_generation,
            expected_head_version=expected_head_version,
            recovery_intent_id=recovery_intent_id,
            actor_id=actor_id,
            trace_id=trace_id,
            correlation_id=correlation_id,
        )
        predecessor = self._execution_by_operation_in_uow(
            uow, predecessor_operation_id=predecessor_operation_id, lock=False
        )
        if predecessor is None:
            raise KernelError(
                "NARRATIVE_EVALUATION_PREDECESSOR_NOT_FOUND",
                "replacement predecessor is not a semantic Evaluation execution",
            )
        project_id = str(predecessor["project_id"])
        candidate_id = str(predecessor["candidate_asset_version_id"])
        self._lock_candidate(
            uow,
            project_id=project_id,
            candidate_asset_version_id=candidate_id,
        )
        predecessor = self._execution_by_operation_in_uow(
            uow, predecessor_operation_id=predecessor_operation_id, lock=True
        )
        assert predecessor is not None
        if actor_id != str(predecessor["operation_actor_id"]):
            raise KernelError(
                "NARRATIVE_EVALUATION_RECOVERY_EVALUATOR_DRIFT",
                "replacement must preserve the predecessor trusted evaluator identity",
            )
        current = self._current_execution_in_uow(
            uow,
            project_id=project_id,
            candidate_asset_version_id=candidate_id,
            lock=True,
        )
        if current is None:
            self._replacement_stale("semantic Evaluation generation head is missing")

        assessment = self._recovery_assessment_in_uow(
            uow, recovery_intent_id=recovery_intent_id
        )
        if assessment is None or assessment["assessment_kind"] != "RECOVERY":
            raise KernelError(
                "NARRATIVE_EVALUATION_RECOVERY_ASSESSMENT_INVALID",
                "replacement requires a RecoveryIntent bound to a RECOVERY assessment",
            )
        if (
            str(assessment["project_id"]) != project_id
            or str(assessment["book_id"]) != str(predecessor["book_id"])
            or str(assessment["workspace_id"]) != str(predecessor["workspace_id"])
        ):
            raise KernelError(
                "NARRATIVE_EVALUATION_RECOVERY_SCOPE_INVALID",
                "RecoveryIntent Opening and semantic Evaluation scopes differ",
            )
        disposition = str(assessment["disposition"])
        allowed = {
            NarrativeEvaluationExternalEffectDisposition.PROVEN_NO_EFFECT.value,
            NarrativeEvaluationExternalEffectDisposition.PROVEN_SUCCESS.value,
            NarrativeEvaluationExternalEffectDisposition.PROVEN_TERMINAL_FAILURE.value,
        }
        if disposition not in allowed:
            raise KernelError(
                "NARRATIVE_EVALUATION_EXTERNAL_EFFECT_RECONCILIATION_REQUIRED",
                "semantic Evaluation replacement is forbidden for ambiguous Provider evidence",
            )
        snapshot = dict(assessment["snapshot"])
        if _canonical_hash(snapshot) != str(assessment["snapshot_hash"]):
            raise KernelError(
                "NARRATIVE_EVALUATION_RECOVERY_ASSESSMENT_INVALID",
                "RecoveryAssessment snapshot hash is invalid",
            )
        opening_snapshot = dict(snapshot.get("opening") or {})
        if str(opening_snapshot.get("opening_run_id") or "") != str(
            assessment["opening_run_id"]
        ):
            raise KernelError(
                "NARRATIVE_EVALUATION_RECOVERY_ASSESSMENT_INVALID",
                "RecoveryAssessment Opening identity is invalid",
            )
        semantic_snapshot = dict(snapshot.get("semantic_evaluation") or {})
        expected_semantic_snapshot = {
            "evaluation_execution_id": str(predecessor["evaluation_execution_id"]),
            "generation": int(predecessor["generation"]),
            "operation_id": str(predecessor["operation_id"]),
            "lifecycle": str(predecessor["lifecycle"]),
            "execution_version": int(predecessor["execution_version"]),
            "candidate_asset_version_id": candidate_id,
            "candidate_content_hash": str(predecessor["candidate_content_hash"]),
            "operation_status": str(predecessor["operation_status"]),
            "evaluator_actor_id": str(predecessor["operation_actor_id"]),
            "head_version": replacement.expected_head_version,
        }
        if not self._semantic_snapshot_matches_execution(
            semantic_snapshot,
            expected_semantic_snapshot,
            predecessor=predecessor,
        ):
            self._replacement_stale(
                "RecoveryAssessment semantic Evaluation snapshot drifted"
            )
        if replacement.expected_head_generation != int(
            predecessor["generation"]
        ) or replacement.expected_head_generation != int(
            semantic_snapshot["generation"]
        ):
            self._replacement_stale("semantic Evaluation generation drifted")
        expected_head_digest = _canonical_hash(
            {
                "evaluation_execution_id": semantic_snapshot["evaluation_execution_id"],
                "generation": semantic_snapshot["generation"],
                "head_version": semantic_snapshot["head_version"],
            }
        )
        if expected_head_digest != str(assessment["evaluation_head_digest"]):
            self._replacement_stale("semantic Evaluation head digest drifted")

        external = self._external_effect_evidence_in_uow(
            uow, operation_id=predecessor_operation_id
        )
        snapshot_external = dict(snapshot.get("external_effect") or {})
        if (
            external != snapshot_external
            or str(external["digest"]) != str(assessment["external_effect_digest"])
            or str(external["classification"]) != disposition
        ):
            raise KernelError(
                "NARRATIVE_EVALUATION_EXTERNAL_EFFECT_RECONCILIATION_REQUIRED",
                "semantic Evaluation ExternalEffect evidence drifted or is ambiguous",
            )
        durable_success_replay: dict[str, Any] | None = None
        if (
            disposition
            == NarrativeEvaluationExternalEffectDisposition.PROVEN_SUCCESS.value
        ):
            durable_success_replay = self._durable_success_replay_bundle_in_uow(
                uow,
                predecessor=predecessor,
                external_evidence=external,
            )
            allowed_terminal_statuses = {"SUCCEEDED"}
            allowed_terminal_lifecycles = {"SUCCEEDED"}
        else:
            allowed_terminal_statuses = {
                "CANCELLED",
                "FAILED_FINAL",
                "DEAD_LETTER",
                "COMPENSATED",
                "COMPENSATION_FAILED",
            }
            allowed_terminal_lifecycles = {
                "CANCELLED",
                "FAILED",
                "DEAD_LETTER",
            }
        if str(predecessor["operation_status"]) not in allowed_terminal_statuses:
            raise KernelError(
                "NARRATIVE_EVALUATION_PREDECESSOR_NOT_TERMINAL",
                "replacement predecessor is not the immutable terminal execution required by its evidence classification",
            )
        self._synchronize_execution_in_uow(uow, predecessor)
        predecessor = self._execution_by_operation_in_uow(
            uow, predecessor_operation_id=predecessor_operation_id, lock=True
        )
        assert predecessor is not None
        if str(predecessor["lifecycle"]) not in allowed_terminal_lifecycles:
            raise KernelError(
                "NARRATIVE_EVALUATION_PREDECESSOR_NOT_TERMINAL",
                "replacement predecessor execution did not converge terminal",
            )

        uow.cursor.execute(
            """
            SELECT evaluation_execution_id,operation_id,
                   candidate_asset_version_id,generation,
                   predecessor_operation_id
            FROM authority_narrative_evaluation_execution
            WHERE recovery_intent_id=%s
            ORDER BY created_at,evaluation_execution_id
            """,
            [recovery_intent_id],
        )
        intent_bindings = [tuple(row) for row in uow.cursor.fetchall()]
        if len(intent_bindings) > 1:
            raise KernelError(
                "NARRATIVE_EVALUATION_RECOVERY_INTENT_CONFLICT",
                "RecoveryIntent is bound to multiple semantic Evaluation executions",
            )
        if intent_bindings and (
            str(intent_bindings[0][0]) != str(current["evaluation_execution_id"])
            or str(intent_bindings[0][1]) != str(current["operation_id"])
            or str(intent_bindings[0][2]) != candidate_id
            or int(intent_bindings[0][3]) != replacement.successor_generation
            or str(intent_bindings[0][4]) != predecessor_operation_id
        ):
            raise KernelError(
                "NARRATIVE_EVALUATION_RECOVERY_INTENT_CONFLICT",
                "RecoveryIntent is already bound outside the exact current generation head",
            )

        is_intent_replay = (
            int(current["generation"]) == replacement.successor_generation
            and str(current["predecessor_operation_id"] or "")
            == predecessor_operation_id
            and str(current["recovery_intent_id"] or "") == recovery_intent_id
        )
        if is_intent_replay:
            return {
                "evaluation_execution_id": str(current["evaluation_execution_id"]),
                "generation": int(current["generation"]),
                "operation_id": str(current["operation_id"]),
                "external_effect_disposition": disposition,
                "durable_result_replay": durable_success_replay is not None,
                "replayed": True,
            }
        if (
            str(current["evaluation_execution_id"])
            != str(predecessor["evaluation_execution_id"])
            or str(current["operation_id"]) != predecessor_operation_id
            or int(current["generation"]) != replacement.expected_head_generation
            or int(current["head_version"]) != replacement.expected_head_version
        ):
            self._replacement_stale("semantic Evaluation generation head changed")

        uow.repositories.definitions.register(
            narrative_semantic_evaluation_definition(
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            )
        )
        uow.cursor.execute(
            """
            SELECT idempotency_key
            FROM authority_narrative_evaluation_execution
            WHERE project_id=%s AND candidate_asset_version_id=%s
              AND generation=1
            """,
            [project_id, candidate_id],
        )
        generation_one = uow.cursor.fetchone()
        if generation_one is None:
            self._replacement_stale("generation-1 semantic Evaluation is missing")
        successor_generation = replacement.successor_generation
        generation_idempotency_key = (
            f"{generation_one[0]}:evaluation-generation:{successor_generation}"
        )
        successor_input = json.loads(json.dumps(predecessor["command_payload"]))
        successor_input_assets = [
            {
                "asset_version_id": str(item["asset_version_id"]),
                "content_hash": str(item["content_hash"]),
            }
            for item in predecessor["input_asset_snapshot"]
        ]
        if durable_success_replay is not None:
            successor_input["payload"]["durable_success_replay"] = dict(
                durable_success_replay
            )
            replay_assets = [
                {
                    "asset_version_id": str(
                        durable_success_replay["model_call_asset_version_id"]
                    ),
                    "content_hash": str(
                        durable_success_replay["model_call_content_hash"]
                    ),
                },
                {
                    "asset_version_id": str(
                        durable_success_replay["cost_ledger_asset_version_id"]
                    ),
                    "content_hash": str(
                        durable_success_replay["cost_ledger_content_hash"]
                    ),
                },
                {
                    "asset_version_id": str(
                        durable_success_replay["source_evaluation_asset_version_id"]
                    ),
                    "content_hash": str(
                        durable_success_replay["source_evaluation_content_hash"]
                    ),
                },
            ]
            successor_input["input_asset_version_ids"] = [
                *successor_input["input_asset_version_ids"],
                *(item["asset_version_id"] for item in replay_assets),
            ]
            successor_input_assets.extend(replay_assets)
        successor_command = {
            "definition_name": NARRATIVE_EVALUATION_DEFINITION,
            "definition_version": NARRATIVE_EVALUATION_VERSION,
            "project_id": project_id,
            "workspace_id": str(predecessor["workspace_id"]),
            "book_id": str(predecessor["book_id"]),
            "logical_key": (
                f"{candidate_id}:evaluation-generation:{successor_generation}"
            ),
            "actor_id": actor_id,
            "idempotency_scope": str(predecessor["idempotency_scope"]),
            "idempotency_key": generation_idempotency_key,
            "trace_id": trace_id,
            "span_id": str(uuid4()),
            "correlation_id": correlation_id,
            "causation_id": predecessor_operation_id,
            "causation_operation_id": predecessor_operation_id,
            "input": successor_input,
            "input_assets": successor_input_assets,
        }
        admitted = admit_command_in_uow(
            uow,
            successor_command,
            context=self._admission_context(actor_id),
        )
        if admitted["replayed"]:
            raise KernelError(
                "NARRATIVE_EVALUATION_REPLACEMENT_IDEMPOTENCY_CONFLICT",
                "generation-aware replacement Operation exists without its exact lineage head",
            )
        operation = self._operation_for_lineage_in_uow(
            uow,
            operation_id=str(admitted["operation_id"]),
            project_id=project_id,
            lock=True,
        )
        if str(operation["status"]) != "ADMITTED":
            self._replacement_stale(
                "replacement Operation did not remain in the unstarted ADMITTED state"
            )
        successor_execution_id = _stable_id(
            "narrative-evaluation-execution",
            project_id,
            candidate_id,
            successor_generation,
        )
        uow.cursor.execute(
            """
            INSERT INTO authority_narrative_evaluation_execution(
                evaluation_execution_id,project_id,book_id,
                candidate_asset_version_id,candidate_content_hash,generation,
                predecessor_execution_id,predecessor_generation,
                predecessor_operation_id,recovery_intent_id,operation_id,
                idempotency_scope,idempotency_key,concurrency_key,lifecycle
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'ADMITTED')
            """,
            [
                successor_execution_id,
                project_id,
                predecessor["book_id"],
                candidate_id,
                predecessor["candidate_content_hash"],
                successor_generation,
                predecessor["evaluation_execution_id"],
                predecessor["generation"],
                predecessor_operation_id,
                recovery_intent_id,
                operation["operation_id"],
                operation["idempotency_scope"],
                operation["idempotency_key"],
                operation["concurrency_key"],
            ],
        )
        uow.cursor.execute(
            """
            UPDATE authority_narrative_evaluation_execution_head
            SET current_execution_id=%s,current_generation=%s,
                version=version+1,updated_at=transaction_timestamp()
            WHERE project_id=%s AND candidate_asset_version_id=%s
              AND current_execution_id=%s AND current_generation=%s
              AND version=%s
            """,
            [
                successor_execution_id,
                successor_generation,
                project_id,
                candidate_id,
                predecessor["evaluation_execution_id"],
                replacement.expected_head_generation,
                replacement.expected_head_version,
            ],
        )
        if uow.cursor.rowcount != 1:
            self._replacement_stale("semantic Evaluation generation head CAS failed")
        return {
            "evaluation_execution_id": successor_execution_id,
            "generation": successor_generation,
            "operation_id": str(operation["operation_id"]),
            "external_effect_disposition": disposition,
            "durable_result_replay": durable_success_replay is not None,
            "replayed": False,
        }

    def release_replacement_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        *,
        operation_id: str,
        recovery_intent_id: str,
        actor_id: str,
        trace_id: str,
        correlation_id: str,
        causation_id: str,
    ) -> dict[str, Any]:

        if any(
            not value.strip()
            for value in (
                operation_id,
                recovery_intent_id,
                actor_id,
                trace_id,
                correlation_id,
                causation_id,
            )
        ):
            raise ValueError("replacement release identity is incomplete")
        execution = self._execution_by_operation_in_uow(
            uow, predecessor_operation_id=operation_id, lock=False
        )
        if execution is None:
            raise KernelError(
                "NARRATIVE_EVALUATION_REPLACEMENT_NOT_FOUND",
                "semantic Evaluation replacement does not exist",
            )
        project_id = str(execution["project_id"])
        candidate_id = str(execution["candidate_asset_version_id"])
        self._lock_candidate(
            uow,
            project_id=project_id,
            candidate_asset_version_id=candidate_id,
        )
        current = self._current_execution_in_uow(
            uow,
            project_id=project_id,
            candidate_asset_version_id=candidate_id,
            lock=True,
        )
        if (
            current is None
            or str(current["evaluation_execution_id"])
            != str(execution["evaluation_execution_id"])
            or str(current["operation_id"]) != operation_id
        ):
            self._replacement_stale(
                "only the current semantic Evaluation generation may be released"
            )
        assert current is not None
        if (
            int(current["generation"]) <= 1
            or str(current["recovery_intent_id"] or "") != recovery_intent_id
            or not str(current["predecessor_operation_id"] or "")
        ):
            raise KernelError(
                "NARRATIVE_EVALUATION_REPLACEMENT_IDENTITY_INVALID",
                "replacement release requires exact recovery lineage",
            )
        assert_narrative_replacement_execution_gate_in_uow(
            uow,
            operation_id=operation_id,
            project_id=project_id,
        )
        operation_status = str(current["operation_status"])
        if operation_status == "READY":
            return {
                "evaluation_execution_id": str(current["evaluation_execution_id"]),
                "generation": int(current["generation"]),
                "operation_id": operation_id,
                "operation_status": "READY",
                "replayed": True,
            }
        if operation_status != "ADMITTED" or str(current["lifecycle"]) != "ADMITTED":
            raise KernelError(
                "NARRATIVE_EVALUATION_REPLACEMENT_ACTIVE",
                "only an unstarted ADMITTED replacement can be released",
            )
        ready = transition_operation_in_uow(
            uow,
            OperationTransitionCommand(
                operation_id=operation_id,
                project_id=project_id,
                expected_version=int(current["operation_version"]),
                expected_status="ADMITTED",
                target_status="READY",
                actor_id=actor_id,
                reason="live Book Opening execution released semantic replacement",
                trace_id=trace_id,
                correlation_id=correlation_id,
                causation_id=causation_id,
            ),
        )
        return {
            "evaluation_execution_id": str(current["evaluation_execution_id"]),
            "generation": int(current["generation"]),
            "operation_id": operation_id,
            "operation_status": str(ready["status"]),
            "replayed": False,
        }

    def cancel_unstarted_replacement_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        *,
        operation_id: str,
        actor_id: str,
        trace_id: str,
        correlation_id: str,
        reason: str,
    ) -> dict[str, Any]:

        if any(
            not value.strip()
            for value in (operation_id, actor_id, trace_id, correlation_id, reason)
        ):
            raise ValueError("unstarted replacement cancellation is incomplete")
        execution = self._execution_by_operation_in_uow(
            uow, predecessor_operation_id=operation_id, lock=False
        )
        if execution is None:
            raise KernelError(
                "NARRATIVE_EVALUATION_REPLACEMENT_NOT_FOUND",
                "semantic Evaluation replacement does not exist",
            )
        project_id = str(execution["project_id"])
        candidate_id = str(execution["candidate_asset_version_id"])
        self._lock_candidate(
            uow,
            project_id=project_id,
            candidate_asset_version_id=candidate_id,
        )
        execution = self._execution_by_operation_in_uow(
            uow, predecessor_operation_id=operation_id, lock=True
        )
        assert execution is not None
        current = self._current_execution_in_uow(
            uow,
            project_id=project_id,
            candidate_asset_version_id=candidate_id,
            lock=True,
        )
        if (
            current is None
            or str(current["evaluation_execution_id"])
            != str(execution["evaluation_execution_id"])
            or str(current["operation_id"]) != operation_id
        ):
            raise KernelError(
                "NARRATIVE_EVALUATION_REPLACEMENT_STALE",
                "only the current semantic Evaluation generation may be cancelled",
            )
        if (
            int(execution["generation"]) <= 1
            or not str(execution["predecessor_operation_id"] or "")
            or not str(execution["recovery_intent_id"] or "")
        ):
            raise KernelError(
                "NARRATIVE_EVALUATION_REPLACEMENT_IDENTITY_INVALID",
                "unstarted cancellation requires formal replacement lineage",
            )
        terminal_lifecycles = {"SUCCEEDED", "FAILED", "CANCELLED", "DEAD_LETTER"}
        if str(execution["lifecycle"]) in terminal_lifecycles:
            expected_operation_statuses = {
                "SUCCEEDED": {"SUCCEEDED"},
                "FAILED": {
                    "FAILED_FINAL",
                    "COMPENSATED",
                    "COMPENSATION_FAILED",
                },
                "CANCELLED": {"CANCELLED"},
                "DEAD_LETTER": {"DEAD_LETTER"},
            }
            if (
                str(execution["operation_status"])
                not in expected_operation_statuses[str(execution["lifecycle"])]
            ):
                raise KernelError(
                    "NARRATIVE_EVALUATION_TERMINAL_HISTORY_CONFLICT",
                    "terminal replacement execution disagrees with its Operation",
                )
            return {
                "evaluation_execution_id": str(execution["evaluation_execution_id"]),
                "operation_id": operation_id,
                "operation_status": str(execution["operation_status"]),
                "lifecycle": str(execution["lifecycle"]),
                "replayed": True,
            }
        if str(execution["lifecycle"]) != "ADMITTED" or str(
            execution["operation_status"]
        ) not in {"ADMITTED", "READY"}:
            raise KernelError(
                "NARRATIVE_EVALUATION_REPLACEMENT_ACTIVE",
                "active or ambiguous semantic Evaluation replacement cannot use unstarted cancellation",
            )
        cancellation = cancel_unstarted_operation_in_uow(
            uow,
            operation_id=operation_id,
            project_id=project_id,
            actor_id=actor_id,
            trace_id=trace_id,
            correlation_id=correlation_id,
            reason=reason,
            causation_id=str(execution["recovery_intent_id"]),
        )
        terminal_reason = {
            "code": "NARRATIVE_EVALUATION_REPLACEMENT_CANCELLED_UNSTARTED",
            "reason": reason,
            "actor_id": actor_id,
            "recovery_intent_id": str(execution["recovery_intent_id"]),
        }
        uow.cursor.execute(
            """
            UPDATE authority_narrative_evaluation_execution
            SET lifecycle='CANCELLED',terminal_reason=%s,version=version+1,
                terminal_at=transaction_timestamp(),
                updated_at=transaction_timestamp()
            WHERE evaluation_execution_id=%s AND version=%s
              AND lifecycle='ADMITTED'
            """,
            [
                Jsonb(terminal_reason),
                execution["evaluation_execution_id"],
                execution["execution_version"],
            ],
        )
        if uow.cursor.rowcount != 1:
            raise KernelError(
                "NARRATIVE_EVALUATION_EXECUTION_STALE",
                "replacement execution changed during unstarted cancellation",
            )
        return {
            "evaluation_execution_id": str(execution["evaluation_execution_id"]),
            "operation_id": operation_id,
            "operation_status": str(cancellation["status"]),
            "lifecycle": "CANCELLED",
            "replayed": False,
        }

    def abort_opening_owned_execution_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        *,
        operation_id: str,
        evaluation_execution_id: str,
        generation: int,
        actor_id: str,
        trace_id: str,
        correlation_id: str,
        reason: str,
    ) -> dict[str, Any]:
        """INVARIANT: Converge the exact current RESUME execution when its owner aborts.

        The outer Book Opening lock is already held.  This method takes the
        semantic candidate/Operation/Attempt/Lease locks in their normal
        order, fences any old worker, and never rewrites terminal history.
        Exact planned/never-sent Effect evidence is cancelled in the same UoW;
        durable success/failure remains immutable evidence, while any unknown
        or potentially-sent request parks the semantic Operation in
        reconciliation instead of permitting replay.
        """
        if (
            any(
                not value.strip()
                for value in (
                    operation_id,
                    evaluation_execution_id,
                    actor_id,
                    trace_id,
                    correlation_id,
                    reason,
                )
            )
            or generation <= 0
        ):
            raise ValueError("Opening-owned semantic abort identity is incomplete")
        execution = self._execution_by_operation_in_uow(
            uow, predecessor_operation_id=operation_id, lock=False
        )
        if execution is None:
            raise KernelError(
                "NARRATIVE_EVALUATION_EXECUTION_NOT_FOUND",
                "Opening abort semantic execution is missing",
            )
        project_id = str(execution["project_id"])
        candidate_id = str(execution["candidate_asset_version_id"])
        # INVARIANT: semantic locks follow the held Opening -> Runtime -> Budget
        # lock prefix.
        self._lock_candidate(
            uow,
            project_id=project_id,
            candidate_asset_version_id=candidate_id,
        )
        execution = self._execution_by_operation_in_uow(
            uow, predecessor_operation_id=operation_id, lock=True
        )
        assert execution is not None
        current = self._current_execution_in_uow(
            uow,
            project_id=project_id,
            candidate_asset_version_id=candidate_id,
            lock=True,
        )
        if (
            current is None
            or str(current["evaluation_execution_id"]) != evaluation_execution_id
            or str(current["operation_id"]) != operation_id
            or int(current["generation"]) != generation
            or str(execution["evaluation_execution_id"]) != evaluation_execution_id
            or int(execution["generation"]) != generation
        ):
            raise KernelError(
                "NARRATIVE_EVALUATION_REPLACEMENT_STALE",
                "Opening abort no longer owns the current semantic execution",
            )

        external = self._external_effect_evidence_in_uow(uow, operation_id=operation_id)
        external_effect_disposition = str(external["classification"])
        external_effect_ids = {
            str(item.get("effect_id") or "")
            for item in external["evidence"]
            if str(item.get("effect_id") or "")
        }
        if (
            external_effect_disposition
            == NarrativeEvaluationExternalEffectDisposition.UNKNOWN_AMBIGUOUS.value
            and len(external_effect_ids) == 1
        ):
            effect_id = next(iter(external_effect_ids))
            effect = uow.repositories.external_effects.get_for_update(effect_id)
            if (
                str(effect["operation_id"]) != operation_id
                or str(effect["project_id"]) != project_id
            ):
                raise KernelError(
                    "NARRATIVE_EVALUATION_EXTERNAL_EFFECT_LINEAGE_INVALID",
                    "semantic ExternalEffect belongs to another execution scope",
                )
            if uow.repositories.external_effects.cancel_proven_never_sent(
                effect,
                reason=reason,
            ):
                external_effect_disposition = "PROVEN_NEVER_SENT_CANCELLED"
                uow.cursor.execute(
                    """
                    SELECT reservation_id,status
                    FROM authority_budget_reservation
                    WHERE external_effect_id=%s AND operation_id=%s
                      AND project_id=%s
                    ORDER BY created_at,reservation_id
                    """,
                    [effect_id, operation_id, project_id],
                )
                reservations = [tuple(row) for row in uow.cursor.fetchall()]
                if len(reservations) > 1:
                    raise KernelError(
                        "BOOK_OPENING_BUDGET_RESERVATION_AMBIGUOUS",
                        "never-sent semantic Effect has multiple budget generations",
                    )
                if reservations:
                    reservation_id, reservation_status = reservations[0]
                    if str(reservation_status) == "RESERVED":
                        released = resolve_provider_budget_failure_in_uow(
                            uow,
                            reservation_id=str(reservation_id),
                            project_id=project_id,
                        )
                        if str(released["status"]) != "RELEASED":
                            raise KernelError(
                                "BOOK_OPENING_BUDGET_RELEASE_CONFLICT",
                                "never-sent semantic abort did not release its budget",
                            )
                    elif str(reservation_status) not in {
                        "RELEASED",
                        "REJECTED",
                    }:
                        raise KernelError(
                            "BOOK_OPENING_BUDGET_RECONCILIATION_REQUIRED",
                            "never-sent semantic Effect has non-releasable budget evidence",
                        )
                uow.repositories.external_effects.record_event(
                    {
                        "event_id": str(uuid4()),
                        "audit_id": str(uuid4()),
                        "outbox_id": str(uuid4()),
                        "aggregate_type": "authority_external_effect",
                        "aggregate_id": effect_id,
                        "operation_id": operation_id,
                        "project_id": project_id,
                        "event_type": "external_effect.cancelled",
                        "correlation_id": correlation_id,
                        "causation_id": evaluation_execution_id,
                        "payload": {
                            "actor_id": actor_id,
                            "trace_id": trace_id,
                            "operation_id": operation_id,
                            "reason": reason,
                            "request_sent": False,
                            "classification": "planned_never_sent",
                        },
                    }
                )
        external_effect_reconciliation_required = (
            external_effect_disposition
            == NarrativeEvaluationExternalEffectDisposition.UNKNOWN_AMBIGUOUS.value
        )

        operation_status = str(execution["operation_status"])
        operation_state = uow.repositories.attempt_runtime.operation_state(
            operation_id, project_id
        )
        if str(operation_state["status"]) != operation_status:
            raise KernelError(
                "NARRATIVE_EVALUATION_EXECUTION_STALE",
                "semantic Operation changed during Opening abort",
            )
        operation_version = int(operation_state["version"])
        terminal_operation_statuses = {
            "SUCCEEDED",
            "FAILED_FINAL",
            "CANCELLED",
            "DEAD_LETTER",
            "COMPENSATED",
            "COMPENSATION_FAILED",
        }
        if operation_status in terminal_operation_statuses:
            self._synchronize_execution_in_uow(uow, execution)
            return {
                "evaluation_execution_id": evaluation_execution_id,
                "operation_id": operation_id,
                "operation_status": operation_status,
                "lifecycle": _evaluation_lifecycle(operation_status),
                "external_effect_disposition": external_effect_disposition,
                "external_effect_reconciliation_required": (
                    external_effect_reconciliation_required
                ),
                "replayed": True,
            }
        target_operation_status = (
            "RECONCILIATION_REQUIRED"
            if external_effect_reconciliation_required
            else "CANCELLED"
        )
        if operation_status == "RECONCILIATION_REQUIRED":
            if external_effect_reconciliation_required:
                self._synchronize_execution_in_uow(uow, execution)
                return {
                    "evaluation_execution_id": evaluation_execution_id,
                    "operation_id": operation_id,
                    "operation_status": operation_status,
                    "lifecycle": "RECONCILIATION_REQUIRED",
                    "external_effect_disposition": external_effect_disposition,
                    "external_effect_reconciliation_required": True,
                    "replayed": True,
                }
        cancelable_statuses = {
            "ADMITTED",
            "READY",
            "EXECUTING",
            "WAITING_CHILDREN",
            "WAITING_EXTERNAL_RESULT",
            "WAITING_GATE",
            "FAILED_RETRYABLE",
            "CANCELLATION_REQUESTED",
            "RECONCILIATION_REQUIRED",
        }
        if operation_status not in cancelable_statuses:
            raise KernelError(
                "NARRATIVE_EVALUATION_REPLACEMENT_ACTIVE",
                f"Opening abort cannot converge semantic state {operation_status}",
            )

        uow.cursor.execute(
            """
            SELECT attempt_id,status,worker_id
            FROM authority_attempt
            WHERE operation_id=%s
              AND status IN (
                  'CREATED','QUEUED','LEASED','RUNNING','CHECKPOINTED',
                  'RESULT_SUBMITTED'
              )
            ORDER BY attempt_number DESC
            FOR UPDATE
            """,
            [operation_id],
        )
        active_attempts = [tuple(row) for row in uow.cursor.fetchall()]
        if len(active_attempts) > 1:
            raise KernelError(
                "NARRATIVE_EVALUATION_ATTEMPT_HISTORY_INVALID",
                "semantic Operation has multiple active Attempts",
            )
        if active_attempts:
            attempt_id, attempt_status, attempt_worker = active_attempts[0]
            attempt = uow.repositories.attempt_runtime.get_for_update(
                str(attempt_id), project_id
            )
            uow.cursor.execute(
                """
                SELECT owner,fencing_token,status
                FROM authority_lease_acquisition
                WHERE attempt_id=%s
                ORDER BY fencing_token DESC
                LIMIT 1
                FOR UPDATE
                """,
                [attempt_id],
            )
            lease = uow.cursor.fetchone()
            worker_id = str(attempt_worker or (lease[0] if lease else ""))
            fencing_token = int(lease[1]) if lease is not None else None
            _transition_attempt(
                uow,
                attempt,
                "FAILED_FINAL"
                if str(attempt_status) == "RESULT_SUBMITTED"
                else "CANCELLED",
                worker_id=worker_id,
                fencing_token=fencing_token,
                trace_id=trace_id,
                correlation_id=correlation_id,
                result={
                    "code": "NARRATIVE_EVALUATION_OPENING_OWNER_ABORTED",
                    "reason": reason,
                },
            )
            if lease is not None and str(lease[2]) == "HELD":
                uow.repositories.attempt_runtime.release(
                    str(attempt_id),
                    str(lease[0]),
                    int(lease[1]),
                    "book_opening_authority_aborted",
                )

        if operation_status != "CANCELLATION_REQUESTED":
            requested = transition_operation_in_uow(
                uow,
                OperationTransitionCommand(
                    operation_id=operation_id,
                    project_id=project_id,
                    expected_version=operation_version,
                    expected_status=operation_status,
                    target_status="CANCELLATION_REQUESTED",
                    actor_id=actor_id,
                    reason=reason,
                    trace_id=trace_id,
                    correlation_id=correlation_id,
                    causation_id=evaluation_execution_id,
                ),
            )
            operation_version = int(requested["version"])
        transitioned = transition_operation_in_uow(
            uow,
            OperationTransitionCommand(
                operation_id=operation_id,
                project_id=project_id,
                expected_version=operation_version,
                expected_status="CANCELLATION_REQUESTED",
                target_status=target_operation_status,
                actor_id=actor_id,
                reason=(
                    "Book Opening aborted; durable ExternalEffect requires reconciliation"
                    if external_effect_reconciliation_required
                    else reason
                ),
                trace_id=trace_id,
                correlation_id=correlation_id,
                causation_id=evaluation_execution_id,
            ),
        )
        refreshed = self._execution_by_operation_in_uow(
            uow, predecessor_operation_id=operation_id, lock=True
        )
        assert refreshed is not None
        self._synchronize_execution_in_uow(uow, refreshed)
        return {
            "evaluation_execution_id": evaluation_execution_id,
            "operation_id": operation_id,
            "operation_status": str(transitioned["status"]),
            "lifecycle": _evaluation_lifecycle(str(transitioned["status"])),
            "external_effect_disposition": external_effect_disposition,
            "external_effect_reconciliation_required": (
                external_effect_reconciliation_required
            ),
            "replayed": False,
        }

    def _admission_context(self, actor_id: str) -> AdmissionContext:
        return AdmissionContext(
            actor_id=actor_id,
            permissions=frozenset({"narrative_design.evaluate"}),
            available_handlers=self.registry.available_handler_keys,
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )

    @staticmethod
    def _semantic_snapshot_matches_execution(
        snapshot: dict[str, Any],
        current: dict[str, Any],
        *,
        predecessor: dict[str, Any],
    ) -> bool:
        if snapshot == current:
            return True
        stable_fields = {
            "evaluation_execution_id",
            "generation",
            "operation_id",
            "candidate_asset_version_id",
            "candidate_content_hash",
            "operation_status",
            "evaluator_actor_id",
            "head_version",
        }
        if any(snapshot.get(key) != current.get(key) for key in stable_fields):
            return False
        return (
            str(current.get("lifecycle") or "")
            in {"CANCELLED", "FAILED", "DEAD_LETTER"}
            and str(snapshot.get("lifecycle") or "")
            in {"ADMITTED", "RUNNING", "RECONCILIATION_REQUIRED"}
            and int(current.get("execution_version") or -1)
            == int(snapshot.get("execution_version") or -1) + 1
            and dict(predecessor.get("terminal_reason") or {})
            == {"operation_status": predecessor.get("operation_status")}
        )

    @staticmethod
    def _lock_candidate(
        uow: AuthorityUnitOfWork,
        *,
        project_id: str,
        candidate_asset_version_id: str,
    ) -> None:
        uow.cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            [f"narrative-evaluation:{project_id}:{candidate_asset_version_id}"],
        )

    @staticmethod
    def _operation_for_lineage_in_uow(
        uow: AuthorityUnitOfWork,
        *,
        operation_id: str,
        project_id: str,
        lock: bool,
    ) -> dict[str, Any]:
        suffix = " FOR UPDATE" if lock else ""
        uow.cursor.execute(
            f"""
            SELECT operation_id,project_id,workspace_id,actor_id,status,version,
                   idempotency_scope,idempotency_key,concurrency_key,
                   command_payload,input_asset_snapshot
            FROM authority_operation
            WHERE operation_id=%s AND project_id=%s
              AND definition_name=%s{suffix}
            """,
            [operation_id, project_id, NARRATIVE_EVALUATION_DEFINITION],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "NARRATIVE_EVALUATION_OPERATION_NOT_FOUND",
                "semantic Evaluation Operation does not exist",
            )
        keys = (
            "operation_id",
            "project_id",
            "workspace_id",
            "operation_actor_id",
            "status",
            "version",
            "idempotency_scope",
            "idempotency_key",
            "concurrency_key",
            "command_payload",
            "input_asset_snapshot",
        )
        return dict(zip(keys, row, strict=True))

    @staticmethod
    def _current_execution_in_uow(
        uow: AuthorityUnitOfWork,
        *,
        project_id: str,
        candidate_asset_version_id: str,
        lock: bool,
    ) -> dict[str, Any] | None:
        suffix = " FOR UPDATE OF head,execution,operation" if lock else ""
        uow.cursor.execute(
            f"""
            SELECT execution.evaluation_execution_id,execution.project_id,
                   execution.book_id,execution.candidate_asset_version_id,
                   execution.candidate_content_hash,execution.generation,
                   execution.predecessor_execution_id,
                   execution.predecessor_generation,
                   execution.predecessor_operation_id,
                   execution.recovery_intent_id,execution.operation_id,
                   execution.idempotency_scope,execution.idempotency_key,
                   execution.concurrency_key,execution.lifecycle,
                   execution.terminal_reason,execution.version,head.version,
                   operation.command_payload,
                   operation.input_asset_snapshot,operation.workspace_id,
                   operation.actor_id,operation.status,operation.version
            FROM authority_narrative_evaluation_execution_head AS head
            JOIN authority_narrative_evaluation_execution AS execution
              ON execution.project_id=head.project_id
             AND execution.candidate_asset_version_id=
                 head.candidate_asset_version_id
             AND execution.evaluation_execution_id=head.current_execution_id
             AND execution.generation=head.current_generation
            JOIN authority_operation AS operation
              ON operation.operation_id=execution.operation_id
             AND operation.project_id=execution.project_id
            WHERE head.project_id=%s
              AND head.candidate_asset_version_id=%s{suffix}
            """,
            [project_id, candidate_asset_version_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            return None
        keys = (
            "evaluation_execution_id",
            "project_id",
            "book_id",
            "candidate_asset_version_id",
            "candidate_content_hash",
            "generation",
            "predecessor_execution_id",
            "predecessor_generation",
            "predecessor_operation_id",
            "recovery_intent_id",
            "operation_id",
            "idempotency_scope",
            "idempotency_key",
            "concurrency_key",
            "lifecycle",
            "terminal_reason",
            "execution_version",
            "head_version",
            "command_payload",
            "input_asset_snapshot",
            "workspace_id",
            "operation_actor_id",
            "operation_status",
            "operation_version",
        )
        return dict(zip(keys, row, strict=True))

    @staticmethod
    def _execution_by_operation_in_uow(
        uow: AuthorityUnitOfWork,
        *,
        predecessor_operation_id: str,
        lock: bool,
    ) -> dict[str, Any] | None:
        suffix = " FOR UPDATE OF execution,operation" if lock else ""
        uow.cursor.execute(
            f"""
            SELECT execution.evaluation_execution_id,execution.project_id,
                   execution.book_id,execution.candidate_asset_version_id,
                   execution.candidate_content_hash,execution.generation,
                   execution.predecessor_execution_id,
                   execution.predecessor_generation,
                   execution.predecessor_operation_id,
                   execution.recovery_intent_id,execution.operation_id,
                   execution.idempotency_scope,execution.idempotency_key,
                   execution.concurrency_key,execution.lifecycle,
                   execution.terminal_reason,execution.version,
                   operation.status,operation.command_payload,
                   operation.input_asset_snapshot,operation.workspace_id,
                   operation.actor_id
            FROM authority_narrative_evaluation_execution AS execution
            JOIN authority_operation AS operation
              ON operation.operation_id=execution.operation_id
             AND operation.project_id=execution.project_id
            WHERE execution.operation_id=%s{suffix}
            """,
            [predecessor_operation_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            return None
        keys = (
            "evaluation_execution_id",
            "project_id",
            "book_id",
            "candidate_asset_version_id",
            "candidate_content_hash",
            "generation",
            "predecessor_execution_id",
            "predecessor_generation",
            "predecessor_operation_id",
            "recovery_intent_id",
            "operation_id",
            "idempotency_scope",
            "idempotency_key",
            "concurrency_key",
            "lifecycle",
            "terminal_reason",
            "execution_version",
            "operation_status",
            "command_payload",
            "input_asset_snapshot",
            "workspace_id",
            "operation_actor_id",
        )
        return dict(zip(keys, row, strict=True))

    @staticmethod
    def _synchronize_execution_in_uow(
        uow: AuthorityUnitOfWork, execution: dict[str, Any]
    ) -> None:
        current = str(execution["lifecycle"])
        target = _evaluation_lifecycle(str(execution["operation_status"]))
        if current == target:
            return
        terminal = {"SUCCEEDED", "FAILED", "CANCELLED", "DEAD_LETTER"}
        if current in terminal:
            raise KernelError(
                "NARRATIVE_EVALUATION_TERMINAL_HISTORY_CONFLICT",
                "terminal semantic Evaluation execution disagrees with its Operation",
            )
        if current in {"RUNNING", "RECONCILIATION_REQUIRED"} and target == "ADMITTED":
            return
        uow.cursor.execute(
            """
            UPDATE authority_narrative_evaluation_execution
            SET lifecycle=%s,terminal_reason=%s,version=version+1,
                started_at=CASE
                    WHEN %s <> 'ADMITTED' THEN COALESCE(
                        started_at,transaction_timestamp()
                    ) ELSE started_at END,
                terminal_at=CASE
                    WHEN %s THEN transaction_timestamp() ELSE NULL END,
                updated_at=transaction_timestamp()
            WHERE evaluation_execution_id=%s AND version=%s
              AND lifecycle=%s
            """,
            [
                target,
                Jsonb(
                    {"operation_status": execution["operation_status"]}
                    if target in terminal
                    else {}
                ),
                target,
                target in terminal,
                execution["evaluation_execution_id"],
                execution["execution_version"],
                current,
            ],
        )
        if uow.cursor.rowcount != 1:
            raise KernelError(
                "NARRATIVE_EVALUATION_EXECUTION_STALE",
                "semantic Evaluation execution changed during projection",
            )

    def _mark_execution_running(self, *, operation_id: str, project_id: str) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            execution = self._execution_by_operation_in_uow(
                uow, predecessor_operation_id=operation_id, lock=True
            )
            if execution is None or str(execution["project_id"]) != project_id:
                raise KernelError(
                    "NARRATIVE_EVALUATION_EXECUTION_NOT_FOUND",
                    "semantic Evaluation Operation has no execution lineage",
                )
            if int(execution["generation"]) > 1:
                assert_narrative_replacement_execution_gate_in_uow(
                    uow,
                    operation_id=operation_id,
                    project_id=project_id,
                )
            if str(execution["lifecycle"]) == "ADMITTED":
                uow.cursor.execute(
                    """
                    UPDATE authority_narrative_evaluation_execution
                    SET lifecycle='RUNNING',version=version+1,
                        started_at=COALESCE(started_at,transaction_timestamp()),
                        updated_at=transaction_timestamp()
                    WHERE evaluation_execution_id=%s AND version=%s
                      AND lifecycle='ADMITTED'
                    """,
                    [
                        execution["evaluation_execution_id"],
                        execution["execution_version"],
                    ],
                )
                if uow.cursor.rowcount != 1:
                    raise KernelError(
                        "NARRATIVE_EVALUATION_EXECUTION_STALE",
                        "semantic Evaluation execution changed before scheduling",
                    )
            uow.commit()

    def _synchronize_execution_for_operation(
        self, *, operation_id: str, project_id: str
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            execution = self._execution_by_operation_in_uow(
                uow, predecessor_operation_id=operation_id, lock=True
            )
            if execution is None or str(execution["project_id"]) != project_id:
                raise KernelError(
                    "NARRATIVE_EVALUATION_EXECUTION_NOT_FOUND",
                    "semantic Evaluation Operation has no execution lineage",
                )
            self._synchronize_execution_in_uow(uow, execution)
            uow.commit()

    @staticmethod
    def _recovery_assessment_in_uow(
        uow: AuthorityUnitOfWork, *, recovery_intent_id: str
    ) -> dict[str, Any] | None:
        uow.cursor.execute(
            """
            SELECT intent.opening_run_id,opening.project_id,opening.workspace_id,
                   opening.book_id,
                   intent.recovery_assessment_id,assessment.assessment_kind,
                   assessment.disposition,assessment.snapshot,
                   assessment.snapshot_hash,assessment.evaluation_head_digest,
                   assessment.external_effect_digest
            FROM authority_book_opening_recovery_intent AS intent
            JOIN authority_book_opening_recovery_assessment AS assessment
              ON assessment.opening_run_id=intent.opening_run_id
             AND assessment.recovery_assessment_id=
                 intent.recovery_assessment_id
            JOIN authority_book_opening_run AS opening
              ON opening.opening_run_id=intent.opening_run_id
            WHERE intent.recovery_intent_id=%s
            """,
            [recovery_intent_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            return None
        keys = (
            "opening_run_id",
            "project_id",
            "workspace_id",
            "book_id",
            "recovery_assessment_id",
            "assessment_kind",
            "disposition",
            "snapshot",
            "snapshot_hash",
            "evaluation_head_digest",
            "external_effect_digest",
        )
        return dict(zip(keys, row, strict=True))

    @staticmethod
    def _durable_success_replay_bundle_in_uow(
        uow: AuthorityUnitOfWork,
        *,
        predecessor: dict[str, Any],
        external_evidence: dict[str, Any],
    ) -> dict[str, Any]:
        """INVARIANT: Freeze one complete Provider result bundle for cross-generation replay.

        A VERIFIED receipt alone is insufficient.  Admission requires the
        successful Attempt, settled budget, ModelCallLog, CostLedger, and
        semantic evaluation output to agree on the exact immutable execution.
        The surrounding Recovery UoW rolls back its Intent and every successor
        admission when any part is absent or inconsistent.
        """
        operation_id = str(predecessor["operation_id"])
        project_id = str(predecessor["project_id"])
        candidate_id = str(predecessor["candidate_asset_version_id"])
        candidate_hash = str(predecessor["candidate_content_hash"])

        def invalid(message: str) -> None:
            raise KernelError(
                "NARRATIVE_EVALUATION_DURABLE_OUTPUT_RECONCILIATION_REQUIRED",
                message,
            )

        uow.cursor.execute(
            """
            SELECT attempt_id,status
            FROM authority_attempt
            WHERE operation_id=%s
            ORDER BY attempt_number,attempt_id
            FOR UPDATE
            """,
            [operation_id],
        )
        attempts = [tuple(row) for row in uow.cursor.fetchall()]
        succeeded_attempts = [row for row in attempts if str(row[1]) == "SUCCEEDED"]
        if len(succeeded_attempts) != 1 or any(
            str(row[1]) not in {"SUCCEEDED", "FAILED", "CANCELLED", "LEASE_LOST"}
            for row in attempts
        ):
            invalid("successful semantic evaluation has no unique terminal Attempt")
        source_attempt_id = str(succeeded_attempts[0][0])

        uow.cursor.execute(
            """
            SELECT effect.external_effect_id,effect.request_hash,
                   effect.request_payload,effect.provider,effect.model_id,
                   dispatch.dispatch_id,dispatch.generation,
                   dispatch.payload_hash,dispatch.evidence,dispatch.provider,
                   dispatch.receipt_id,
                   receipt.external_receipt_id,receipt.provider,
                   receipt.receipt_id,receipt.payload_hash,receipt.payload,
                   budget.reservation_id,budget.status,budget.provider,
                   budget.settled_amount,budget.currency,budget.actual_tokens,
                   budget.evidence
            FROM authority_external_effect AS effect
            JOIN authority_external_effect_dispatch AS dispatch
              ON dispatch.external_effect_id=effect.external_effect_id
             AND dispatch.status='SUCCEEDED'
            JOIN authority_external_receipt AS receipt
              ON receipt.dispatch_id=dispatch.dispatch_id
             AND receipt.status='VERIFIED'
            JOIN authority_budget_reservation AS budget
              ON budget.external_effect_id=effect.external_effect_id
             AND budget.operation_id=effect.operation_id
            WHERE effect.operation_id=%s AND effect.project_id=%s
              AND effect.status='SUCCEEDED'
            ORDER BY dispatch.generation,dispatch.dispatch_id,
                     receipt.external_receipt_id,budget.reservation_id
            FOR UPDATE OF effect,dispatch,receipt,budget
            """,
            [operation_id, project_id],
        )
        durable_rows = [tuple(row) for row in uow.cursor.fetchall()]
        if len(durable_rows) != 1:
            invalid(
                "successful semantic evaluation has no unique Effect/Dispatch/Receipt/budget bundle"
            )
        durable = durable_rows[0]
        (
            external_effect_id,
            effect_request_hash,
            effect_request_payload,
            effect_provider,
            effect_model_id,
            dispatch_id,
            dispatch_generation,
            dispatch_payload_hash,
            dispatch_evidence,
            dispatch_provider,
            dispatch_receipt_id,
            external_receipt_id,
            receipt_provider,
            receipt_id,
            receipt_payload_hash,
            receipt_payload,
            reservation_id,
            budget_status,
            budget_provider,
            settled_amount,
            budget_currency,
            actual_tokens,
            budget_evidence,
        ) = durable
        effect_request = dict(effect_request_payload or {})
        receipt = dict(receipt_payload or {})
        provider_evidence = receipt.get("evidence")
        production = effect_request.get("_production_execution")
        if (
            str(budget_status) != "SETTLED"
            or not isinstance(provider_evidence, Mapping)
            or receipt.get("outcome") != "success"
            or not isinstance(production, Mapping)
            or production.get("operation_id") != operation_id
            or production.get("attempt_id") != source_attempt_id
            or str(effect_request_hash) != _canonical_hash(effect_request)
            or str(dispatch_payload_hash) != str(effect_request_hash)
        ):
            invalid(
                "successful Provider receipt is incomplete or execution-bound incorrectly"
            )
        provider_evidence = dict(provider_evidence)
        provider_result = provider_evidence.get("result")
        provider_usage = provider_evidence.get("usage")
        provider_cost = provider_evidence.get("cost")
        provider_execution = provider_evidence.get("production_execution")
        execution_request = (
            provider_execution.get("execution_request")
            if isinstance(provider_execution, Mapping)
            else None
        )
        route_snapshot = (
            provider_execution.get("route_snapshot")
            if isinstance(provider_execution, Mapping)
            else None
        )
        if (
            provider_evidence.get("real_model_call") is not True
            or not isinstance(provider_result, Mapping)
            or not isinstance(provider_usage, Mapping)
            or not isinstance(provider_cost, Mapping)
            or not isinstance(execution_request, Mapping)
            or execution_request.get("external_effect_id") != str(external_effect_id)
            or not isinstance(route_snapshot, Mapping)
            or not str(route_snapshot.get("route_snapshot_id") or "")
            or str(receipt_payload_hash) != _canonical_hash(provider_evidence)
            or dict(dispatch_evidence or {}) != provider_evidence
            or int(receipt.get("generation") or 0) != int(dispatch_generation)
            or str(dispatch_provider) != str(effect_provider)
            or str(receipt_provider) != str(effect_provider)
            or str(dispatch_receipt_id) != str(receipt_id)
            or str(effect_provider) != str(provider_evidence.get("provider_id") or "")
            or (
                bool(str(effect_model_id or ""))
                and str(effect_model_id) != str(provider_evidence.get("model_id") or "")
            )
            or str(budget_provider) != str(effect_provider)
            or dict(budget_evidence or {}).get("provider_id") != str(effect_provider)
            or dict(budget_evidence or {}).get("model_id")
            != str(provider_evidence.get("model_id") or "")
        ):
            invalid("Provider receipt/result identity is incomplete or inconsistent")
        uow.cursor.execute(
            """
            SELECT dispatch.dispatch_id,dispatch.status,
                   COUNT(receipt.external_receipt_id),
                   COUNT(receipt.external_receipt_id)
                     FILTER (WHERE receipt.status='VERIFIED')
            FROM authority_external_effect_dispatch AS dispatch
            LEFT JOIN authority_external_receipt AS receipt
              ON receipt.dispatch_id=dispatch.dispatch_id
            WHERE dispatch.external_effect_id=%s
            GROUP BY dispatch.dispatch_id,dispatch.status
            ORDER BY dispatch.dispatch_id
            """,
            [external_effect_id],
        )
        dispatch_receipt_cardinality = [tuple(row) for row in uow.cursor.fetchall()]
        if (
            sum(1 for row in dispatch_receipt_cardinality if row[1] == "SUCCEEDED") != 1
            or any(int(row[2]) > 1 for row in dispatch_receipt_cardinality)
            or sum(int(row[3]) for row in dispatch_receipt_cardinality) != 1
            or any(
                str(row[1])
                not in {
                    "SUCCEEDED",
                    "FAILED_FINAL",
                    "CANCELLED",
                    "SUPERSEDED",
                    "DEAD_LETTER",
                }
                for row in dispatch_receipt_cardinality
            )
        ):
            invalid("Provider dispatch/receipt history is ambiguous")
        try:
            amounts_match = Decimal(str(settled_amount)) == Decimal(
                str(provider_cost.get("amount"))
            )
        except (InvalidOperation, ValueError):
            amounts_match = False
        if (
            not amounts_match
            or str(budget_currency) != str(provider_cost.get("currency") or "")
            or int(actual_tokens) != int(provider_usage.get("total_tokens") or -1)
        ):
            invalid("settled Provider budget differs from the verified receipt")

        uow.cursor.execute(
            """
            SELECT binding.role,binding.output_key,asset.asset_type,
                   version.asset_version_id,version.content_hash,version.content,
                   version.lifecycle,version.eligibility,version.governance
            FROM authority_operation_output_asset AS binding
            JOIN authority_asset_version AS version
              ON version.asset_version_id=binding.asset_version_id
             AND version.asset_id=binding.asset_id
            JOIN authority_asset AS asset
              ON asset.asset_id=version.asset_id AND asset.project_id=%s
            WHERE binding.operation_id=%s
              AND (
                   binding.role IN ('model_evidence','cost_evidence')
                   OR (
                       binding.output_key='story_design.semantic_evaluation'
                       AND binding.role='qualification_evidence'
                   )
              )
            ORDER BY binding.role,binding.output_key,binding.asset_version_id
            FOR UPDATE OF binding,version
            """,
            [project_id, operation_id],
        )
        outputs = [tuple(row) for row in uow.cursor.fetchall()]

        def content_matches(row: tuple[Any, ...], asset_type: str) -> bool:
            return (
                str(row[2]) == asset_type
                and str(row[4]) == _canonical_hash(dict(row[5] or {}))
                and tuple(str(value) for value in row[6:9])
                == ("ACTIVE", "ELIGIBLE", "CLEAR")
            )

        models = [
            row
            for row in outputs
            if str(row[0]) == "model_evidence"
            and content_matches(row, "model_call_log")
            and dict(row[5] or {}).get("operation_id") == operation_id
            and dict(row[5] or {}).get("attempt_id") == source_attempt_id
            and dict(row[5] or {}).get("external_effect_id") == str(external_effect_id)
        ]
        costs = [
            row
            for row in outputs
            if str(row[0]) == "cost_evidence"
            and content_matches(row, "cost_ledger")
            and dict(row[5] or {}).get("operation_id") == operation_id
            and dict(row[5] or {}).get("attempt_id") == source_attempt_id
            and dict(row[5] or {}).get("external_effect_id") == str(external_effect_id)
        ]
        evaluations = [
            row
            for row in outputs
            if str(row[0]) == "qualification_evidence"
            and str(row[1]) == "story_design.semantic_evaluation"
            and content_matches(row, "narrative_design_evaluation")
        ]
        if len(models) != 1 or len(costs) != 1 or len(evaluations) != 1:
            invalid(
                "successful semantic evaluation lacks one exact model/cost/output evidence set"
            )
        model, cost, evaluation = models[0], costs[0], evaluations[0]
        model_content = dict(model[5])
        cost_content = dict(cost[5])
        evaluation_content = dict(evaluation[5])
        model_provider_evidence = model_content.get("provider_evidence")
        target_lineage = model_content.get("target_lineage")
        evaluation_provider_execution = evaluation_content.get("provider_execution")
        evaluation_provider_evidence = evaluation_content.get("provider_evidence")
        command_payload = dict(predecessor["command_payload"])
        command_business_payload = dict(command_payload.get("payload") or {})
        generator_operation_id = str(
            command_business_payload.get("generation_operation_id") or ""
        )
        generator_operation_name = str(
            command_business_payload.get("generator_operation_name") or ""
        )
        model_asset_id = str(model[3])
        model_content_hash = str(model[4])
        provider_evidence_hash = _canonical_hash(provider_evidence)
        provider_result_hash = _canonical_hash(provider_result)
        expected_provider_reference = [
            {
                "asset_version_id": model_asset_id,
                "content_hash": model_content_hash,
            }
        ]
        expected_evaluation_hash = _canonical_hash(
            {
                "evaluation": dict(provider_result),
                "candidate_asset_version_id": candidate_id,
                "candidate_content_hash": candidate_hash,
                "generation_operation_id": generator_operation_id,
                "evaluation_operation_id": operation_id,
                "evaluation_attempt_id": source_attempt_id,
                "provider_evidence": expected_provider_reference,
                "provider_evidence_hash": provider_evidence_hash,
            }
        )
        qualification = validate_narrative_qualification(
            generator_operation_name=generator_operation_name,
            value=dict(provider_result),
            require_pass=False,
        )
        if (
            model_content.get("stage") != "narrative_semantic_evaluation"
            or model_provider_evidence != provider_evidence
            or target_lineage
            != {
                "target_asset_version_id": candidate_id,
                "target_content_hash": candidate_hash,
                "generation_operation_id": generator_operation_id,
                "generator_operation_name": generator_operation_name,
            }
            or cost_content.get("stage") != "narrative_semantic_evaluation"
            or cost_content.get("provider_id") != provider_evidence.get("provider_id")
            or cost_content.get("model_id") != provider_evidence.get("model_id")
            or Decimal(str(cost_content.get("amount")))
            != Decimal(str(provider_cost.get("amount")))
            or cost_content.get("currency") != provider_cost.get("currency")
            or int(cost_content.get("total_tokens") or -1)
            != int(provider_usage.get("total_tokens") or -2)
            or evaluation_content.get("candidate_asset_version_id") != candidate_id
            or evaluation_content.get("candidate_content_hash") != candidate_hash
            or evaluation_content.get("generation_operation_id")
            != generator_operation_id
            or evaluation_content.get("evaluation_operation_id") != operation_id
            or evaluation_content.get("evaluation_attempt_id") != source_attempt_id
            or evaluation_content.get("evaluator_execution_class") != "MODEL_PROVIDER"
            or evaluation_content.get("evaluation") != provider_result
            or evaluation_content.get("qualification") != qualification.to_evidence()
            or evaluation_content.get("evaluation_evidence_hash")
            != expected_evaluation_hash
            or evaluation_content.get("provider_evidence_asset_version_ids")
            != [model_asset_id]
            or evaluation_provider_evidence != expected_provider_reference
            or not isinstance(evaluation_provider_execution, Mapping)
            or evaluation_provider_execution.get("provider_evidence_hash")
            != provider_evidence_hash
            or evaluation_provider_execution.get("provider_result_hash")
            != provider_result_hash
            or evaluation_provider_execution.get("route_snapshot_id")
            != route_snapshot.get("route_snapshot_id")
        ):
            invalid("durable semantic output differs from its exact Provider evidence")

        external_items = list(external_evidence.get("evidence") or [])
        if not any(
            item.get("effect_id") == str(external_effect_id)
            and item.get("dispatch_id") == str(dispatch_id)
            and item.get("receipt_id") == str(external_receipt_id)
            for item in external_items
            if isinstance(item, Mapping)
        ):
            invalid("durable result is outside the assessed ExternalEffect snapshot")
        bundle = {
            "schema_version": NARRATIVE_EVALUATION_DURABLE_REPLAY_VERSION,
            "source_evaluation_execution_id": str(
                predecessor["evaluation_execution_id"]
            ),
            "source_evaluation_generation": int(predecessor["generation"]),
            "source_operation_id": operation_id,
            "source_attempt_id": source_attempt_id,
            "external_effect_id": str(external_effect_id),
            "external_effect_request_hash": str(effect_request_hash),
            "external_effect_evidence_digest": str(external_evidence["digest"]),
            "dispatch_id": str(dispatch_id),
            "dispatch_generation": int(dispatch_generation),
            "dispatch_payload_hash": str(dispatch_payload_hash),
            "external_receipt_id": str(external_receipt_id),
            "receipt_payload_hash": str(receipt_payload_hash),
            "budget_reservation_id": str(reservation_id),
            "model_call_asset_version_id": model_asset_id,
            "model_call_content_hash": model_content_hash,
            "cost_ledger_asset_version_id": str(cost[3]),
            "cost_ledger_content_hash": str(cost[4]),
            "source_evaluation_asset_version_id": str(evaluation[3]),
            "source_evaluation_content_hash": str(evaluation[4]),
            "evaluation_evidence_hash": expected_evaluation_hash,
            "qualification_hash": qualification.qualification_hash,
            "provider_evidence_hash": provider_evidence_hash,
            "provider_result_hash": provider_result_hash,
            "provider_route_snapshot_id": str(route_snapshot.get("route_snapshot_id")),
        }
        return {**bundle, "bundle_hash": _canonical_hash(bundle)}

    @staticmethod
    def _external_effect_evidence_in_uow(
        uow: AuthorityUnitOfWork, *, operation_id: str
    ) -> dict[str, Any]:
        uow.cursor.execute(
            """
            SELECT external_effect_id,status,request_hash
            FROM authority_external_effect
            WHERE operation_id=%s
            ORDER BY external_effect_id
            FOR UPDATE
            """,
            [operation_id],
        )
        effects = [tuple(row) for row in uow.cursor.fetchall()]
        if not effects:
            empty_hash = _canonical_hash([])
            return {
                "classification": (
                    NarrativeEvaluationExternalEffectDisposition.PROVEN_NO_EFFECT.value
                ),
                "evidence": [],
                "digest": empty_hash,
            }
        effect_ids = [str(row[0]) for row in effects]
        uow.cursor.execute(
            """
            SELECT dispatch_id,external_effect_id,generation,status,payload_hash
            FROM authority_external_effect_dispatch
            WHERE external_effect_id=ANY(%s)
            ORDER BY external_effect_id,generation,dispatch_id
            FOR UPDATE
            """,
            [effect_ids],
        )
        dispatches = [tuple(row) for row in uow.cursor.fetchall()]
        dispatch_ids = [str(row[0]) for row in dispatches]
        receipts: list[tuple[Any, ...]] = []
        if dispatch_ids:
            uow.cursor.execute(
                """
                SELECT external_receipt_id,dispatch_id,status,payload_hash
                FROM authority_external_receipt
                WHERE dispatch_id=ANY(%s)
                ORDER BY dispatch_id,external_receipt_id
                FOR UPDATE
                """,
                [dispatch_ids],
            )
            receipts = [tuple(row) for row in uow.cursor.fetchall()]
        dispatch_by_effect: dict[str, list[tuple[Any, ...]]] = {}
        for dispatch in dispatches:
            dispatch_by_effect.setdefault(str(dispatch[1]), []).append(dispatch)
        receipts_by_dispatch: dict[str, list[tuple[Any, ...]]] = {}
        for receipt in receipts:
            receipts_by_dispatch.setdefault(str(receipt[1]), []).append(receipt)
        evidence: list[dict[str, Any]] = []
        classifier_rows: list[dict[str, object]] = []
        for effect in effects:
            items: Iterable[tuple[Any, ...] | None] = dispatch_by_effect.get(
                str(effect[0])
            ) or (None,)
            for dispatch in items:
                dispatch_receipts: Iterable[tuple[Any, ...] | None] = (
                    (None,)
                    if dispatch is None
                    else receipts_by_dispatch.get(str(dispatch[0])) or (None,)
                )
                for receipt in dispatch_receipts:
                    item = {
                        "effect_id": str(effect[0]),
                        "effect_status": str(effect[1]),
                        "request_hash": str(effect[2]),
                        "dispatch_id": str(dispatch[0]) if dispatch else "",
                        "dispatch_status": str(dispatch[3]) if dispatch else "",
                        "dispatch_payload_hash": (
                            str(dispatch[4] or "") if dispatch else ""
                        ),
                        "receipt_id": str(receipt[0]) if receipt else "",
                        "receipt_status": str(receipt[2]) if receipt else "",
                        "receipt_payload_hash": (
                            str(receipt[3] or "") if receipt else ""
                        ),
                    }
                    evidence.append(item)
                    classifier_rows.append(
                        {
                            "external_effect_id": item["effect_id"],
                            "effect_status": item["effect_status"],
                            "dispatch_id": item["dispatch_id"] or None,
                            "dispatch_status": item["dispatch_status"] or None,
                            "receipt_status": item["receipt_status"] or None,
                        }
                    )
        classification = classify_narrative_evaluation_external_effects(
            classifier_rows
        ).value
        return {
            "classification": classification,
            "evidence": evidence,
            "digest": _canonical_hash(evidence),
        }

    @staticmethod
    def _replacement_stale(message: str) -> None:
        raise KernelError("NARRATIVE_EVALUATION_REPLACEMENT_STALE", message)

    def _register_definition(self) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.definitions.register(
                narrative_semantic_evaluation_definition(
                    application_build_id=self.application_build_id,
                    commit_sha=self.commit_sha,
                )
            )
            uow.commit()

    def _require_candidate(
        self, command: NarrativeSemanticEvaluationCommand
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            return self._require_candidate_in_uow(uow, command)

    @staticmethod
    def _require_candidate_in_uow(
        uow: AuthorityUnitOfWork,
        command: NarrativeSemanticEvaluationCommand,
    ) -> dict[str, Any]:
        uow.cursor.execute(
            """
            SELECT version.asset_version_id, version.content_hash,
                   version.content, asset.asset_type, operation.actor_id,
                   book_candidate.status,
                   book_candidate.created_by_operation_id,
                   planning_generation.status,
                   planning_generation.operation_id,
                   planning_generation.generator_operation_name,
                   planning_generation.candidate_asset_version_id,
                   design_state.lifecycle,
                   design_state.qualification,
                   design_state.generator_operation_name,
                   design_state.execution_evidence->>'operation_id',
                   current_operation.command_payload,
                   current_operation.idempotency_key,
                   generation_one.idempotency_key,
                   operation.command_payload
            FROM authority_operation_output_asset AS output
            JOIN authority_operation AS operation
              ON operation.operation_id=output.operation_id
             AND operation.project_id=%s
             AND operation.status IN ('WAITING_GATE', 'SUCCEEDED')
            JOIN authority_asset_version AS version
              ON version.asset_version_id=output.asset_version_id
            JOIN authority_asset AS asset
              ON asset.asset_id=version.asset_id
             AND asset.project_id=operation.project_id
            LEFT JOIN authority_book_design_candidate AS book_candidate
              ON book_candidate.asset_version_id=version.asset_version_id
            LEFT JOIN authority_story_planning_generation AS planning_generation
              ON planning_generation.operation_id=operation.operation_id
             AND planning_generation.candidate_asset_version_id=
                 version.asset_version_id
            LEFT JOIN authority_story_design_version_state AS design_state
              ON design_state.project_id=operation.project_id
             AND design_state.asset_version_id=version.asset_version_id
            LEFT JOIN authority_narrative_evaluation_execution_head AS head
              ON head.project_id=operation.project_id
             AND head.candidate_asset_version_id=version.asset_version_id
            LEFT JOIN authority_narrative_evaluation_execution AS current_execution
              ON current_execution.project_id=head.project_id
             AND current_execution.candidate_asset_version_id=
                 head.candidate_asset_version_id
             AND current_execution.evaluation_execution_id=
                 head.current_execution_id
             AND current_execution.generation=head.current_generation
            LEFT JOIN authority_operation AS current_operation
              ON current_operation.operation_id=current_execution.operation_id
             AND current_operation.project_id=current_execution.project_id
            LEFT JOIN authority_narrative_evaluation_execution AS generation_one
              ON generation_one.project_id=operation.project_id
             AND generation_one.candidate_asset_version_id=version.asset_version_id
             AND generation_one.generation=1
            WHERE output.operation_id=%s
              AND output.asset_version_id=%s
              AND output.content_hash=%s
            """,
            [
                command.project_id,
                command.generation_operation_id,
                command.candidate_asset_version_id,
                command.candidate_content_hash,
            ],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "NARRATIVE_EVALUATION_GENERATION_LINEAGE_INVALID",
                "candidate is not an exact gated or successful output of the generation Operation",
            )
        generation_command_payload = dict(row[18] or {})
        raw_opening_binding = dict(generation_command_payload.get("payload") or {}).get(
            "opening_execution_binding"
        )
        if raw_opening_binding is None:
            opening_execution_binding: dict[str, Any] = {}
        elif isinstance(raw_opening_binding, Mapping):
            opening_execution_binding = dict(raw_opening_binding)
        else:
            raise KernelError(
                "NARRATIVE_EVALUATION_OPENING_BINDING_INVALID",
                "generation Operation carries a malformed Opening execution fence",
            )
        expected_payload = {
            "project_id": command.project_id,
            "input_asset_version_ids": [
                command.candidate_asset_version_id,
                *command.evidence_asset_version_ids,
            ],
            "payload": evaluation_command_payload(
                command, generation_actor_id=str(row[4]),
                opening_execution_binding=opening_execution_binding,
            ),
        }
        lineage_exists = (
            row[15] is not None
            and _evaluation_command_payload_matches(dict(row[15]), expected_payload)
            and command.idempotency_key in {str(row[16]), str(row[17])}
        )
        if command.generator_operation_name == "book_design.propose":
            pending = (
                str(row[3]) == "book_design"
                and str(row[5] or "") == "EVALUATION_PENDING"
                and str(row[6] or "") == command.generation_operation_id
            )
        elif str(row[3]) == "planning_generation_candidate":
            pending = (
                str(row[7] or "") == "EVALUATION_PENDING"
                and str(row[8] or "") == command.generation_operation_id
                and str(row[9] or "") == command.generator_operation_name
                and str(row[10] or "") == command.candidate_asset_version_id
            )
        else:
            expected_scope = GENERATOR_DESIGN_SCOPE.get(
                command.generator_operation_name
            )
            pending = (
                expected_scope is not None
                and str(row[3]) == expected_scope.value.lower()
                and str(row[11] or "") == "MATERIALIZED"
                and str(row[12] or "") == "STRUCTURALLY_VALID"
                and str(row[13] or "") == command.generator_operation_name
                and str(row[14] or "") == command.generation_operation_id
            )
        if not pending and not lineage_exists:
            raise KernelError(
                "NARRATIVE_EVALUATION_CANDIDATE_NOT_PENDING",
                "Narrative Evaluation requires the exact domain candidate to be EVALUATION_PENDING before Provider dispatch",
            )
        return {
            "asset_version_id": str(row[0]),
            "content_hash": str(row[1]),
            "content": dict(row[2]),
            "asset_type": str(row[3]),
            "generation_actor_id": str(row[4]),
            "opening_execution_binding": opening_execution_binding,
        }

    def _require_asset(self, project_id: str, asset_version_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT version.asset_version_id, version.content_hash,
                       version.content, asset.asset_type,
                       COALESCE(producer.operation_id, ''),
                       COALESCE(producer.status, '')
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                LEFT JOIN LATERAL (
                    SELECT operation.operation_id, operation.status
                    FROM authority_operation_output_asset AS output
                    JOIN authority_operation AS operation
                      ON operation.operation_id=output.operation_id
                     AND operation.project_id=asset.project_id
                    WHERE output.asset_version_id=version.asset_version_id
                    ORDER BY output.created_at DESC
                    LIMIT 1
                ) AS producer ON TRUE
                WHERE version.asset_version_id=%s AND asset.project_id=%s
                """,
                [asset_version_id, project_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "NARRATIVE_EVALUATION_EVIDENCE_NOT_FOUND",
                "Narrative Evaluation input is outside project scope",
            )
        return {
            "asset_version_id": str(row[0]),
            "content_hash": str(row[1]),
            "content": dict(row[2]),
            "asset_type": str(row[3]),
            "producer_operation_id": str(row[4]),
            "producer_status": str(row[5]),
        }

    def _record_qualifications(
        self,
        command: NarrativeSemanticEvaluationCommand,
        lineage: NarrativeEvaluationLineage,
        result: NarrativeQualificationResult,
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            for receipt in result.receipts:
                qualification_id = _canonical_hash(
                    {
                        "asset_version_id": lineage.candidate_asset_version_id,
                        "design_layer": receipt.layer.value,
                        "profile_hash": receipt.profile_hash,
                        "evaluation_hash": receipt.evaluation_hash,
                        "evaluation_operation_id": lineage.evaluation_operation_id,
                    }
                )
                uow.cursor.execute(
                    """
                    INSERT INTO authority_narrative_design_qualification(
                        qualification_id, project_id, book_id,
                        asset_version_id, source_operation_id,
                        candidate_content_hash, design_layer, profile_id,
                        profile_version, profile_hash, capability_id, skill_ref,
                        evaluator_execution_class, qualification_status,
                        evaluation, evaluation_hash, qualification_hash,
                        generation_operation_id, evaluation_operation_id,
                        evaluation_attempt_id, evaluation_asset_version_id,
                        evaluation_evidence_hash, trust_boundary
                        , provider_model_call_asset_version_id
                        , provider_model_call_content_hash
                        , provider_evidence_hash, provider_result_hash
                        , provider_route_snapshot_id
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, 'INDEPENDENT', %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (
                        asset_version_id, design_layer,
                        profile_version, evaluation_hash
                    ) DO NOTHING
                    """,
                    [
                        qualification_id,
                        command.project_id,
                        command.book_id,
                        lineage.candidate_asset_version_id,
                        lineage.evaluation_operation_id,
                        lineage.candidate_content_hash,
                        receipt.layer.value,
                        receipt.profile_id,
                        receipt.profile_version,
                        receipt.profile_hash,
                        receipt.capability_id,
                        receipt.skill_ref,
                        lineage.evaluator_execution_class,
                        receipt.status,
                        Jsonb(receipt.evidence),
                        receipt.evaluation_hash,
                        result.qualification_hash,
                        lineage.generation_operation_id,
                        lineage.evaluation_operation_id,
                        lineage.evaluation_attempt_id,
                        lineage.evaluation_asset_version_id,
                        lineage.evaluation_evidence_hash,
                        lineage.provider_model_call_asset_version_id or None,
                        lineage.provider_model_call_content_hash or None,
                        lineage.provider_evidence_hash or None,
                        lineage.provider_result_hash or None,
                        lineage.provider_route_snapshot_id or None,
                    ],
                )
            uow.commit()


__all__ = [
    "NARRATIVE_EVALUATION_DEFINITION",
    "NARRATIVE_EVALUATION_HANDLER",
    "NARRATIVE_EVALUATION_APPLICATION_BUILD_ID",
    "NARRATIVE_EVALUATION_VERSION",
    "NarrativeEvaluationExternalEffectDisposition",
    "NarrativeProviderEvaluation",
    "NarrativeSemanticEvaluationApplication",
    "NarrativeSemanticEvaluationCommand",
    "NarrativeSemanticEvaluationReplacementCommand",
    "NarrativeSemanticEvaluationHandler",
    "NarrativeSemanticEvaluationExecutionPort",
    "NarrativeSemanticEvaluationRegistry",
    "NarrativeSemanticEvaluationResult",
    "classify_narrative_evaluation_external_effects",
    "narrative_semantic_evaluation_definition",
]
