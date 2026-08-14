"""One independent Narrative Semantic Evaluation runtime for design candidates."""

from __future__ import annotations

from dataclasses import dataclass
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
from novel_forge.modules.command_kernel.operation_graph import (
    GraphCommandContext,
    start_saga,
)
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.modules.content_authority.scheduler import ContentAuthorityScheduler
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .qualification import (
    NarrativeEvaluationLineage,
    NarrativeQualificationProfile,
    NarrativeQualificationResult,
    required_qualification_profiles,
    validate_narrative_qualification,
)


NARRATIVE_EVALUATION_DEFINITION = "story_design.semantic_evaluate"
NARRATIVE_EVALUATION_VERSION = "1.0.0"
NARRATIVE_EVALUATION_HANDLER = "novel_forge.story_design.semantic_evaluate"
NARRATIVE_EVALUATION_APPLICATION_BUILD_ID = (
    "canonical-narrative-semantic-evaluation-runtime"
)


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


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
        provider_result: NarrativeProviderEvaluation | None = None
        evaluation = payload.get("evaluation")
        if execution_class == "MODEL_PROVIDER":
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
        elif not evidence_inputs:
            raise KernelError(
                "NARRATIVE_EVALUATION_OPERATOR_EVIDENCE_REQUIRED",
                "operator evaluation requires immutable review evidence",
            )
        qualification = validate_narrative_qualification(
            generator_operation_name=str(payload.get("generator_operation_name") or ""),
            value=evaluation,
            require_pass=False,
        )
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
                "provider_evidence_hash": (
                    provider_result.provider_evidence_hash
                    if provider_result is not None
                    else ""
                ),
            }
        )
        reference_asset_version_ids = (
            candidate.asset_version_id,
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
        # This is one shared production worker, even when Book Design and Story
        # Planning call it through different application compositions. Its
        # release identity must not depend on which caller registers first.
        self.application_build_id = NARRATIVE_EVALUATION_APPLICATION_BUILD_ID
        self.commit_sha = commit_sha
        self.worker_id = worker_id
        self.execution_port = execution_port
        self.allow_scripted_fixture = allow_scripted_fixture
        self.registry = NarrativeSemanticEvaluationRegistry(
            execution_port=execution_port,
            allow_scripted_fixture=allow_scripted_fixture,
        )

    def execute(
        self,
        command: NarrativeSemanticEvaluationCommand,
        *,
        principal: Principal,
        caller_permission: str,
    ) -> NarrativeSemanticEvaluationResult:
        del caller_permission  # evaluator identity is governed by its own permission
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
            "logical_key": command.candidate_asset_version_id,
            "actor_id": command.actor_id,
            "idempotency_scope": "book:narrative-semantic-evaluation",
            "idempotency_key": command.idempotency_key,
            "trace_id": command.trace_id,
            "span_id": str(uuid4()),
            "correlation_id": command.correlation_id,
            "causation_id": command.generation_operation_id,
            "causation_operation_id": command.generation_operation_id,
            "input": {
                "project_id": command.project_id,
                "input_asset_version_ids": [
                    item["asset_version_id"] for item in inputs
                ],
                "payload": {
                    "candidate_asset_version_id": command.candidate_asset_version_id,
                    "candidate_content_hash": command.candidate_content_hash,
                    "generation_operation_id": command.generation_operation_id,
                    "generation_actor_id": candidate["generation_actor_id"],
                    "generator_operation_name": command.generator_operation_name,
                    "book_id": command.book_id,
                    "evaluator_execution_class": command.evaluator_execution_class,
                    "evaluation": (
                        None if command.evaluation is None else dict(command.evaluation)
                    ),
                },
            },
            "input_assets": [
                {
                    "asset_version_id": item["asset_version_id"],
                    "content_hash": item["content_hash"],
                }
                for item in inputs
            ],
        }
        admitted = self._admit_candidate_once(command, admission_command)
        operation_id = str(admitted["operation_id"])
        operation_actor_id = str(admitted.get("operation_actor_id") or command.actor_id)
        with AuthorityUnitOfWork(self.database_url) as uow:
            operation = uow.repositories.attempt_runtime.operation_state(
                operation_id, command.project_id
            )
        if operation["status"] == "ADMITTED":
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
        scheduled = ContentAuthorityScheduler(
            self.database_url,
            registry=self.registry,
            worker_id=self.worker_id,
        ).run_or_recover(operation_id=operation_id, project_id=command.project_id)
        evaluation_asset = self._require_asset(
            command.project_id, scheduled.output.asset_version_id
        )
        content = dict(evaluation_asset["content"])
        qualification = validate_narrative_qualification(
            generator_operation_name=command.generator_operation_name,
            value=content.get("evaluation"),
            require_pass=False,
        )
        lineage = NarrativeEvaluationLineage(
            generation_operation_id=command.generation_operation_id,
            evaluation_operation_id=operation_id,
            evaluation_attempt_id=scheduled.attempt_id,
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
        self._record_qualifications(command, lineage, qualification)
        return NarrativeSemanticEvaluationResult(
            lineage=lineage,
            qualification=qualification,
            evaluation_content=content,
            replayed=bool(admitted["replayed"]),
        )

    def _admit_candidate_once(
        self,
        command: NarrativeSemanticEvaluationCommand,
        admission_command: dict[str, Any],
    ) -> dict[str, Any]:
        concurrency_key = (
            f"book:{command.book_id}:evaluation:"
            f"{command.candidate_asset_version_id}"
        )
        with AuthorityUnitOfWork(self.database_url) as claim_uow:
            claim_uow.cursor.execute(
                "SELECT pg_advisory_lock(hashtextextended(%s, 0))",
                [f"narrative-evaluation:{command.project_id}:{concurrency_key}"],
            )
            try:
                claim_uow.cursor.execute(
                    """
                    SELECT operation_id, command_payload, actor_id
                    FROM authority_operation
                    WHERE project_id=%s
                      AND definition_name=%s
                      AND concurrency_key=%s
                    ORDER BY created_at, operation_id
                    """,
                    [
                        command.project_id,
                        NARRATIVE_EVALUATION_DEFINITION,
                        concurrency_key,
                    ],
                )
                rows = claim_uow.cursor.fetchall()
                if len(rows) > 1:
                    raise KernelError(
                        "NARRATIVE_EVALUATION_DUPLICATE_CLAIM",
                        "candidate has more than one Evaluation Operation",
                    )
                if rows:
                    existing_payload = dict(rows[0][1])
                    if existing_payload != admission_command["input"]:
                        raise KernelError(
                            "NARRATIVE_EVALUATION_CLAIM_CONFLICT",
                            "candidate Evaluation is already claimed by different immutable inputs",
                        )
                    return {
                        "operation_id": str(rows[0][0]),
                        "operation_actor_id": str(rows[0][2]),
                        "replayed": True,
                    }
                # The stale-domain preflight is repeated while holding the
                # cross-process candidate claim lock. This closes the gap
                # between the initial read and immutable Operation admission.
                self._require_candidate(command)
                admitted = admit_command(
                    self.database_url,
                    admission_command,
                    context=AdmissionContext(
                        actor_id=command.actor_id,
                        permissions=frozenset({"narrative_design.evaluate"}),
                        available_handlers=self.registry.available_handler_keys,
                        application_build_id=self.application_build_id,
                        commit_sha=self.commit_sha,
                    ),
                )
                return {
                    **admitted,
                    "operation_actor_id": command.actor_id,
                }
            finally:
                claim_uow.cursor.execute(
                    "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
                    [f"narrative-evaluation:{command.project_id}:{concurrency_key}"],
                )

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
                       replay.operation_id
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
                LEFT JOIN authority_operation AS replay
                  ON replay.project_id=operation.project_id
                 AND replay.idempotency_scope='book:narrative-semantic-evaluation'
                 AND replay.idempotency_key=%s
                WHERE output.operation_id=%s
                  AND output.asset_version_id=%s
                  AND output.content_hash=%s
                """,
                [
                    command.project_id,
                    command.idempotency_key,
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
        replay_exists = bool(row[11])
        if command.generator_operation_name == "book_design.propose":
            pending = (
                str(row[3]) == "book_design"
                and str(row[5] or "") == "EVALUATION_PENDING"
                and str(row[6] or "") == command.generation_operation_id
            )
        else:
            pending = (
                str(row[3]) == "planning_generation_candidate"
                and str(row[7] or "") == "EVALUATION_PENDING"
                and str(row[8] or "") == command.generation_operation_id
                and str(row[9] or "") == command.generator_operation_name
                and str(row[10] or "") == command.candidate_asset_version_id
            )
        if not pending and not replay_exists:
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
    "NarrativeProviderEvaluation",
    "NarrativeSemanticEvaluationApplication",
    "NarrativeSemanticEvaluationCommand",
    "NarrativeSemanticEvaluationHandler",
    "NarrativeSemanticEvaluationExecutionPort",
    "NarrativeSemanticEvaluationRegistry",
    "NarrativeSemanticEvaluationResult",
    "narrative_semantic_evaluation_definition",
]
