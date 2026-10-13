from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import Field

from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.book_authority.production import (
    StartBookProductionCommand,
    SubmitBookChapterCommand,
)
from novel_forge.modules.book_authority.input_resolver import (
    ResolveBookProductionInputCommand,
)
from novel_forge.modules.book_authority.opening import (
    BookOpeningBudgetReconciliationRequest as LegacyBudgetReconciliationRequest,
    OpenBookProductionRequest,
)
from novel_forge.modules.book_authority.opening_progress import (
    PostgresBookOpeningWorkflowProgressQuery,
)
from novel_forge.modules.book_design_authority import (
    FormationLayerInput,
    StartStoryFormationCommand,
    StoryFormationInput,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_preparation import PostgresProductionAssetResolver
from novel_forge.modules.chapter_group_authority.policy import (
    ChapterGroupExecutionPolicy,
)
from novel_forge.modules.book_followup_authority.reader_policy import ReaderProxyPolicy
from novel_forge.modules.book_authority.control_policy import ControlPolicy
from novel_forge.modules.plan_change_authority import PlanChangeProposalCommand
from novel_forge.modules.story_planning_runtime import StoryPlanningGenerationCommand, StoryPlanningEvaluationCommand
from novel_forge.modules.story_planning_runtime.world_sampling import WorldProviderSampleCommand


@dataclass
class AuthorSupervisionModeRequest:
    project_id: str
    mode: str
    reason: str
    expected_policy_hash: str
    idempotency_key: str


@dataclass
class AuthorSupervisionRequest:
    project_id: str
    routing_asset_version_id: str
    candidate_id: str
    expires_at: str
    maximum_tokens: Annotated[int, Field(strict=True, ge=1)]
    maximum_amount: str
    reason: str
    expected_policy_hash: str
    idempotency_key: str


@dataclass
class AuthorCreativeInputRequest:
    project_id: str
    brief_asset_version_id: str
    brief_content_hash: str
    design: dict[str, str]
    contribution: str
    idempotency_key: str


@dataclass
class AuthorModelReviewRequest:
    project_id: str
    content_hash: str
    idempotency_key: str


@dataclass
class AuthorDesignDecisionRequest:
    project_id: str
    content_hash: str
    reason: str
    idempotency_key: str
    findings: list[dict[str, Any]] = field(default_factory=list)
    decision: str = "APPROVE"


@dataclass
class PlanChangeDecisionRequest:
    project_id: str
    actor_id: str
    approved: bool
    reason: str
    craft_scope_dispositions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PlanChangeControlRequest:
    project_id: str
    actor_id: str


@dataclass
class PlanningRuntimeContinuationRequest:
    project_id: str
    expected_source_version: Annotated[int, Field(strict=True, ge=1)]
    decision_evidence: dict[str, Any]
    trace_id: str
    correlation_id: str


@dataclass
class BookOpeningCapacityContinuationRequest:
    actor_id: str
    expected_version: Annotated[int, Field(strict=True, ge=0)]
    reason: str


def _planning_scope(record: dict[str, Any], *, project_id: str, book_id: str) -> None:
    if record.get("project_id") != project_id or record.get("book_id") != book_id:
        raise KernelError("BOOK_PLANNING_SCOPE_MISMATCH", "Planning request belongs to another Book")


@dataclass
class ChapterGroupExecutionPolicyRequest:
    project_id: str
    actor_id: str
    policy: ChapterGroupExecutionPolicy
    workspace_id: str
    idempotency_key: str
    trace_id: str
    correlation_id: str


@dataclass
class CreativeExperimentBudgetRequest:
    project_id: str
    actor_id: str
    policy: dict[str, Any]
    workspace_id: str
    idempotency_key: str
    trace_id: str
    correlation_id: str


@dataclass
class ReaderProxyPolicyRequest:
    project_id: str
    actor_id: str
    policy: ReaderProxyPolicy
    workspace_id: str
    idempotency_key: str
    trace_id: str
    correlation_id: str


@dataclass
class CausalPlanningRequest:
    project_id: str
    actor_id: str
    reality_revision_id: str
    intent_version_id: str
    chapter_number: int
    candidates: list[dict[str, Any]]
    idempotency_key: str
    trace_id: str
    correlation_id: str


@dataclass
class BookControlPolicyRequest:
    project_id: str
    actor_id: str
    policy: ControlPolicy
    workspace_id: str
    idempotency_key: str
    trace_id: str
    correlation_id: str


@dataclass
class BookControlDecisionRequest:
    project_id: str
    actor_id: str
    chapter_number: int
    boundary: str
    subject_version_id: str
    decision: str
    reason: str
    idempotency_key: str
    trace_id: str
    correlation_id: str


def create_router(ctx: ProductRouterContext) -> APIRouter:
    globals().update(ctx.models)
    BookAuthorityStartRequest = ctx.models["BookAuthorityStartRequest"]
    BookProductionInputResolveRequest = ctx.models["BookProductionInputResolveRequest"]
    StoryFormationStartRequest = ctx.models["StoryFormationStartRequest"]
    StoryFormationControlRequest = ctx.models["StoryFormationControlRequest"]
    StoryFormationAuthorDecisionRequest = ctx.models["StoryFormationAuthorDecisionRequest"]
    StoryFormationBookDesignApprovalRequest = ctx.models[
        "StoryFormationBookDesignApprovalRequest"
    ]
    BookOpeningStartRequest = ctx.models["BookOpeningStartRequest"]
    BookOpeningControlRequest = ctx.models["BookOpeningControlRequest"]
    BookOpeningAssessmentRequest = ctx.models["BookOpeningAssessmentRequest"]
    BookOpeningBudgetReconciliationRequest = ctx.models[
        "BookOpeningBudgetReconciliationRequest"
    ]
    BookOpeningConvergenceRequest = ctx.models["BookOpeningConvergenceRequest"]
    BookOpeningRecoveryRequest = ctx.models["BookOpeningRecoveryRequest"]
    BookOpeningCheckpointAssessmentRequest = ctx.models[
        "BookOpeningCheckpointAssessmentRequest"
    ]
    BookAuthorityChapterRequest = ctx.models["BookAuthorityChapterRequest"]
    BookAuthorityControlRequest = ctx.models["BookAuthorityControlRequest"]
    BookReplanApprovalRequest = ctx.models["BookReplanApprovalRequest"]
    BookReplanReevaluationRequest = ctx.models["BookReplanReevaluationRequest"]
    router = APIRouter(
        prefix="/product/production/book-authority",
        tags=["product-book-authority"],
    )

    @router.get("/author-workspace")
    def author_workspace(project_id: str, book_id: str = "") -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("book.authority.query", project_id)
            from novel_forge.api.authority_dependencies import authority_release_identity
            from novel_forge.modules.command_kernel.dispatch_control import dispatch_control_status
            composition = _composition(ctx)
            control = dispatch_control_status(composition.query.database_url, project_id=project_id)
            build_id, sha = authority_release_identity()
            return {**composition.query.author_workspace(project_id=project_id, book_id=book_id),
                    "release_identity": build_id + "@" + sha, "dispatch_control": control}
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.get("/books/{book_id}/author-supervision")
    def author_supervision(book_id: str, project_id: str) -> dict[str, Any]:
        try:
            from novel_forge.modules.book_authority.author_supervision import supervision_workspace
            principal = build_trusted_principal_resolver().resolve_api_principal()
            return supervision_workspace(_composition(ctx).query.database_url, project_id=project_id, book_id=book_id, principal=principal)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/books/{book_id}/author-supervision/mode")
    def select_author_supervision_mode(book_id: str, request: AuthorSupervisionModeRequest) -> dict[str, Any]:
        try:
            from novel_forge.api.authority_dependencies import authority_release_identity
            from novel_forge.modules.book_authority.author_supervision import select_book_mode
            principal = build_trusted_principal_resolver().resolve_api_principal()
            build, sha = authority_release_identity()
            return select_book_mode(_composition(ctx).query.database_url, project_id=request.project_id, book_id=book_id,
                request=request, principal=principal, application_build_id=build, commit_sha=sha)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/books/{book_id}/author-supervision")
    def approve_author_supervision(book_id: str, request: AuthorSupervisionRequest) -> dict[str, Any]:
        try:
            from novel_forge.api.authority_dependencies import authority_release_identity
            from novel_forge.modules.book_authority.author_supervision import approve_route
            principal = build_trusted_principal_resolver().resolve_api_principal()
            build, sha = authority_release_identity()
            return approve_route(_composition(ctx).query.database_url, project_id=request.project_id, book_id=book_id,
                request=request, principal=principal, application_build_id=build, commit_sha=sha)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/books/{book_id}/author-creative-input")
    def save_author_creative_input(book_id: str, request: AuthorCreativeInputRequest) -> dict[str, Any]:
        try:
            from novel_forge.api.authority_dependencies import authority_release_identity
            from novel_forge.modules.book_authority.author_supervision import author_creative_input
            principal = build_trusted_principal_resolver().resolve_api_principal()
            build, sha = authority_release_identity()
            return author_creative_input(_composition(ctx).query.database_url, project_id=request.project_id,
                book_id=book_id, request=request, principal=principal, application_build_id=build, commit_sha=sha)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/books/{book_id}/author-creative-input/{asset_version_id}/decisions")
    def approve_author_creative_input(book_id: str, asset_version_id: str, request: AuthorDesignDecisionRequest) -> dict[str, Any]:
        try:
            from novel_forge.api.authority_dependencies import authority_release_identity
            from novel_forge.modules.book_authority.author_supervision import decide_creative_input
            if request.decision != "APPROVE":
                raise KernelError("FORMATION_AUTHOR_INPUT_REQUIRED", "Save a revised original input before approving its direction")
            principal = build_trusted_principal_resolver().resolve_api_principal()
            build, sha = authority_release_identity()
            return decide_creative_input(_composition(ctx).query.database_url, project_id=request.project_id,
                book_id=book_id, asset_version_id=asset_version_id, request=request, principal=principal,
                application_build_id=build, commit_sha=sha)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/books/{book_id}/planning-candidates/{asset_version_id}/model-reviews")
    def review_author_design(book_id: str, asset_version_id: str, request: AuthorModelReviewRequest) -> dict[str, Any]:
        try:
            resolver = build_trusted_principal_resolver()
            operator = resolver.resolve_api_principal()
            operator.require("story_planning.authority.execute", request.project_id)
            planning = _composition(ctx).planning
            candidate = planning.require_candidate(asset_version_id)
            _planning_scope(candidate, project_id=request.project_id, book_id=book_id)
            if candidate["content_hash"] != request.content_hash:
                raise KernelError("AUTHOR_SUPERVISION_EXACT_REVIEW_REQUIRED", "Review must bind the displayed candidate hash")
            from novel_forge.modules.story_design_authority.author_supervision import supervised_state
            state = planning.story_design.require(project_id=request.project_id, asset_version_id=asset_version_id)
            if not supervised_state(state):
                raise KernelError("AUTHOR_ADVISORY_TARGET_INVALID", "Use the existing strict evaluation path for strict candidates")
            from novel_forge.modules.authority_security import PrincipalType
            supervision = state["execution_evidence"]["author_supervision"]
            if (operator.principal_type is not PrincipalType.LOCAL_OPERATOR
                    or operator.principal_id != supervision.get("author_id", supervision.get("authorization", {}).get("author_id"))):
                raise PermissionError("Only the scoped author may request model advice against the authorized budget")
            evaluator = resolver.resolve_narrative_evaluator_principal()
            result = planning.evaluate_candidate(StoryPlanningEvaluationCommand(project_id=request.project_id,
                workspace_id=candidate["workspace_id"], book_id=book_id, actor_id=evaluator.principal_id,
                candidate_asset_version_id=asset_version_id, candidate_content_hash=request.content_hash,
                generation_operation_id=candidate["generation_operation_id"], generator_operation_name=candidate["generator_operation_name"],
                evaluator_execution_class="MODEL_PROVIDER", idempotency_key=request.idempotency_key,
                trace_id=request.idempotency_key, correlation_id=request.idempotency_key),
                principal=evaluator, transition_principal=operator)
            return asdict(result)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/books/{book_id}/planning-candidates/{asset_version_id}/author-decisions")
    def decide_author_design(book_id: str, asset_version_id: str, request: AuthorDesignDecisionRequest) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal()
            planning = _composition(ctx).planning
            candidate = planning.require_candidate(asset_version_id)
            _planning_scope(candidate, project_id=request.project_id, book_id=book_id)
            if candidate["content_hash"] != request.content_hash:
                raise KernelError("AUTHOR_SUPERVISION_EXACT_REVIEW_REQUIRED", "Refresh the exact candidate before approving")
            state = planning.story_design.require(project_id=request.project_id, asset_version_id=asset_version_id)
            supervision = state["execution_evidence"].get("author_supervision", {})
            from novel_forge.modules.authority_security import PrincipalType
            if (principal.principal_type is not PrincipalType.LOCAL_OPERATOR or principal.principal_id != supervision.get("author_id", supervision.get("authorization", {}).get("author_id"))):
                raise PermissionError("Only the scoped author may decide this supervised plan")
            if not request.reason.strip() or request.decision not in {"APPROVE", "REJECT", "REQUEST_CHANGES"}:
                raise KernelError("AUTHOR_SUPERVISION_EXACT_REVIEW_REQUIRED", "Record the decision and its basis")
            if request.decision != "APPROVE":
                return planning.reject_candidate(asset_version_id, principal=principal,
                    idempotency_key=request.idempotency_key, reason=request.reason, decision=request.decision)
            evidence = {"author_review": {"asset_version_id": asset_version_id, "content_hash": request.content_hash,
                "decision": "ACCEPT", "reason": request.reason, "findings": request.findings}}
            planning.approve_candidate(asset_version_id, principal=principal, idempotency_key=request.idempotency_key+":approve",
                trace_id=request.idempotency_key, correlation_id=request.idempotency_key, decision_evidence=evidence)
            return planning.activate_candidate(asset_version_id, principal=principal, idempotency_key=request.idempotency_key+":activate",
                trace_id=request.idempotency_key, correlation_id=request.idempotency_key, decision_evidence=evidence)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/books/{book_id}/planning-generations")
    def generate_plan(book_id: str, request: StoryPlanningGenerationCommand) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal(claimed_actor_id=request.actor_id)
            _planning_scope({"project_id": request.project_id, "book_id": request.book_id}, project_id=request.project_id, book_id=book_id)
            result = _composition(ctx).planning.generate(replace(request, actor_id=principal.principal_id, auto_approve_low_risk=False), principal=principal)
            return asdict(result)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.get("/books/{book_id}/planning-generations/{operation_id}")
    def planning_generation(book_id: str, operation_id: str, project_id: str) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("book.authority.query", project_id)
            result = _composition(ctx).planning.require_generation(operation_id)
            _planning_scope(result, project_id=project_id, book_id=book_id)
            return {**result, "frozen_command": _composition(ctx).planning.frozen_generation_command(operation_id)}
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/books/{book_id}/world-provider-samples")
    def sample_world(book_id: str, request: WorldProviderSampleCommand, dry_run: bool = False) -> dict[str, Any]:
        from novel_forge.modules.story_planning_runtime.world_sampling import run_world_sample, prepare_world_sample

        try:
            principal = build_trusted_principal_resolver().resolve_api_principal(claimed_actor_id=request.actor_id)
            _planning_scope({"project_id": request.project_id, "book_id": request.book_id}, project_id=request.project_id, book_id=book_id)
            action = prepare_world_sample if dry_run else run_world_sample
            return action(_composition(ctx).planning, replace(request, actor_id=principal.principal_id), principal=principal)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.get("/books/{book_id}/world-provider-samples/{operation_id}")
    def world_sample(book_id: str, operation_id: str, project_id: str) -> dict[str, Any]:
        from novel_forge.modules.story_planning_runtime.world_sampling import query_world_sample

        try:
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("book.authority.query", project_id)
            return query_world_sample(_composition(ctx).planning.database_url, project_id=project_id, book_id=book_id, operation_id=operation_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/books/{book_id}/planning-generations/{operation_id}/runtime-continuation")
    def continue_planning_runtime(book_id: str, operation_id: str, request: PlanningRuntimeContinuationRequest) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("story_planning.authority.execute", request.project_id)
            planning = _composition(ctx).planning
            _planning_scope(planning.require_generation(operation_id), project_id=request.project_id, book_id=book_id)
            return planning.register_runtime_continuation(
                operation_id, project_id=request.project_id, principal=principal,
                expected_source_version=request.expected_source_version,
                decision_evidence=request.decision_evidence,
                trace_id=request.trace_id, correlation_id=request.correlation_id,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.get("/books/{book_id}/planning-candidates/{asset_version_id}")
    def planning_candidate(book_id: str, asset_version_id: str, project_id: str) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("book.authority.query", project_id)
            planning = _composition(ctx).planning
            result = planning.require_candidate(asset_version_id)
            _planning_scope(result, project_id=project_id, book_id=book_id)
            return {**result, "frozen_command": planning.frozen_generation_command(result["generation_operation_id"])}
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/books/{book_id}/planning-evaluations")
    def evaluate_plan(book_id: str, request: StoryPlanningEvaluationCommand, dry_run: bool = False) -> dict[str, Any]:
        try:
            resolver = build_trusted_principal_resolver()
            operator = resolver.resolve_api_principal(claimed_actor_id=request.actor_id)
            operator.require("story_planning.authority.execute", request.project_id)
            _planning_scope({"project_id": request.project_id, "book_id": request.book_id}, project_id=request.project_id, book_id=book_id)
            if request.evaluator_execution_class != "MODEL_PROVIDER":
                raise KernelError("PLANNING_PROVIDER_EVALUATION_REQUIRED", "this native endpoint requires independent governed Provider evaluation")
            evaluator = resolver.resolve_narrative_evaluator_principal()
            if dry_run:
                from novel_forge.modules.story_design_authority.evaluation_runtime import NarrativeSemanticEvaluationCommand

                return _composition(ctx).planning.semantic_evaluation.prepare_reference_evaluation(
                    NarrativeSemanticEvaluationCommand(**asdict(replace(request, actor_id=evaluator.principal_id))),
                    principal=evaluator,
                )
            result = _composition(ctx).planning.evaluate_candidate(replace(request, actor_id=evaluator.principal_id), principal=evaluator, transition_principal=operator)
            return asdict(result)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/books/{book_id}/plan-changes")
    def propose_plan_change(book_id: str, request: PlanChangeProposalCommand) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal(claimed_actor_id=request.actor_id)
            _planning_scope({"project_id": request.project_id, "book_id": request.book_id}, project_id=request.project_id, book_id=book_id)
            return _composition(ctx).plan_change.propose(replace(request, actor_id=principal.principal_id), principal=principal)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.get("/books/{book_id}/plan-changes/{proposal_id}")
    def plan_change_detail(book_id: str, proposal_id: str, project_id: str) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("book.authority.query", project_id)
            result = _composition(ctx).plan_change.require(proposal_id)
            _planning_scope(result, project_id=project_id, book_id=book_id)
            return result
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/books/{book_id}/plan-changes/{proposal_id}/decisions")
    def decide_plan_change(book_id: str, proposal_id: str, request: PlanChangeDecisionRequest) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal(claimed_actor_id=request.actor_id)
            principal.require("book.authority.execute", request.project_id)
            authority = _composition(ctx).plan_change
            _planning_scope(authority.require(proposal_id), project_id=request.project_id, book_id=book_id)
            if not request.reason.strip():
                raise ValueError("PlanChange decision requires a reason")
            evidence = {"reason": request.reason, "actor_id": principal.principal_id}
            if request.craft_scope_dispositions:
                evidence["craft_scope_dispositions"] = request.craft_scope_dispositions
            return authority.decide(proposal_id, approved=request.approved, authority_type="OPERATOR", authority_version="operator-plan-change-v1", evidence=evidence, principal=principal)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/books/{book_id}/plan-changes/{proposal_id}/activate")
    def activate_plan_change(book_id: str, proposal_id: str, request: PlanChangeControlRequest) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal(claimed_actor_id=request.actor_id)
            principal.require("book.authority.execute", request.project_id)
            authority = _composition(ctx).plan_change
            _planning_scope(authority.require(proposal_id), project_id=request.project_id, book_id=book_id)
            return authority.activate(proposal_id, principal=principal)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/runs/{book_run_id}/plan-changes/{proposal_id}/resume")
    def resume_plan_change(book_run_id: str, proposal_id: str, request: PlanChangeControlRequest) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal(claimed_actor_id=request.actor_id)
            principal.require("book.authority.execute", request.project_id)
            composition = _composition(ctx)
            book = composition.authority.require(book_run_id)
            _planning_scope(book, project_id=request.project_id, book_id=book["book_id"])
            return composition.resume_after_plan_change(book_run_id=book_run_id, proposal_id=proposal_id, principal=principal)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.put("/policies/book-control")
    def configure_book_control(request: BookControlPolicyRequest) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal(claimed_actor_id=request.actor_id)
            arguments = {key: value for key, value in asdict(request).items() if key not in {"actor_id", "policy"}}
            return _composition(ctx).controls.configure(policy=request.policy, principal=principal, **arguments)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/runs/{book_run_id}/control-decisions")
    def decide_book_control(book_run_id: str, request: BookControlDecisionRequest) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal(claimed_actor_id=request.actor_id)
            arguments = {key: value for key, value in asdict(request).items() if key != "actor_id"}
            return _composition(ctx).controls.decide(book_run_id=book_run_id, principal=principal, **arguments)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.put("/policies/creative-experiment-budget")
    def configure_experiment_budget(request: CreativeExperimentBudgetRequest) -> dict[str, Any]:
        from novel_forge.api.authority_dependencies import authority_release_identity
        from novel_forge.modules.command_kernel.creative_budget_runtime import configure_creative_budget
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal(claimed_actor_id=request.actor_id)
            build_id, sha = authority_release_identity()
            arguments = {key: value for key, value in asdict(request).items() if key != "actor_id"}
            return configure_creative_budget(database_url=ctx.app_settings.database_url, principal=principal,
                application_build_id=build_id, commit_sha=sha, **arguments)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.get("/projects/{project_id}/creative-experiment-budget")
    def query_experiment_budget(project_id: str) -> dict[str, Any]:
        from novel_forge.modules.command_kernel.creative_budget_runtime import get_creative_budget
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("book.authority.query", project_id)
            return get_creative_budget(ctx.app_settings.database_url, project_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.put("/policies/chapter-group-execution")
    def configure_execution_policy(
        request: ChapterGroupExecutionPolicyRequest,
    ) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            return _composition(ctx).chapter_groups.execution_policies.configure(
                project_id=request.project_id,
                policy=request.policy,
                principal=principal,
                workspace_id=request.workspace_id,
                idempotency_key=request.idempotency_key,
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.put("/policies/reader-proxy")
    def configure_reader_policy(request: ReaderProxyPolicyRequest) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            return _composition(ctx).followup.reader_policies.configure(
                project_id=request.project_id,
                policy=request.policy,
                principal=principal,
                workspace_id=request.workspace_id,
                idempotency_key=request.idempotency_key,
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/books/{book_id}/opening-runs", status_code=202)
    def start_book_opening(
        book_id: str, request: BookOpeningStartRequest
    ) -> dict[str, Any]:
        try:
            composition = _composition(ctx)
            if composition.opening is None:
                raise KernelError(
                    "BOOK_OPENING_RUNTIME_NOT_CONFIGURED",
                    "Book opening is unavailable in this partial composition",
                )
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            admission = composition.opening.admit(
                OpenBookProductionRequest(
                    project_id=request.project_id,
                    workspace_id=request.workspace_id,
                    book_id=book_id,
                    actor_id=principal.principal_id,
                    expected_book_version=request.expected_book_version,
                    production_profile=request.production_profile,
                    planning_input_versions=dict(request.planning_input_versions),
                    arc_logical_keys=tuple(request.arc_logical_keys),
                    idempotency_key=request.idempotency_key,
                    trace_id=request.trace_id or f"trace:{uuid4()}",
                    correlation_id=request.correlation_id or f"correlation:{uuid4()}",
                    initial_story_state_version=request.initial_story_state_version,
                    initial_canon_snapshot_version=request.initial_canon_snapshot_version,
                ),
                principal=principal,
            )
            return asdict(admission)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.get("/opening-runs/{opening_run_id}")
    def book_opening_detail(opening_run_id: str) -> dict[str, Any]:
        try:
            composition = _composition(ctx)
            if composition.opening is None:
                raise KernelError(
                    "BOOK_OPENING_RUNTIME_NOT_CONFIGURED", "Book opening is unavailable"
                )
            run = composition.opening.require(opening_run_id)
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("book.authority.query", str(run["project_id"]))
            return run
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.get("/opening-runs/{opening_run_id}/progress")
    def book_opening_progress(opening_run_id: str) -> dict[str, Any]:
        try:
            composition = _composition(ctx)
            if composition.opening is None:
                raise KernelError(
                    "BOOK_OPENING_RUNTIME_NOT_CONFIGURED", "Book opening is unavailable"
                )
            progress = PostgresBookOpeningWorkflowProgressQuery(
                composition.opening.database_url
            ).progress(opening_run_id=opening_run_id)
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("book.authority.query", progress.project_id)
            return progress.to_dict()
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/opening-runs/{opening_run_id}/resume", status_code=202)
    def resume_book_opening(
        opening_run_id: str, request: BookOpeningControlRequest
    ) -> dict[str, Any]:
        try:
            composition = _composition(ctx)
            if composition.opening is None:
                raise KernelError(
                    "BOOK_OPENING_RUNTIME_NOT_CONFIGURED", "Book opening is unavailable"
                )
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            return composition.opening.resume(
                opening_run_id,
                expected_version=request.expected_version,
                principal=principal,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post(
        "/opening-runs/{opening_run_id}/reconcile-legacy-budget-scope",
        status_code=202,
    )
    def reconcile_legacy_book_opening_budget_scope(
        opening_run_id: str,
        request: BookOpeningBudgetReconciliationRequest,
    ) -> dict[str, Any]:
        try:
            composition = _composition(ctx)
            if composition.opening is None:
                raise KernelError(
                    "BOOK_OPENING_RUNTIME_NOT_CONFIGURED", "Book opening is unavailable"
                )
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            receipt = composition.opening.reconcile_legacy_budget_scope(
                opening_run_id,
                LegacyBudgetReconciliationRequest(
                    expected_opening_version=request.expected_opening_version,
                    expected_frozen_request_digest=(
                        request.expected_frozen_request_digest
                    ),
                    idempotency_key=request.idempotency_key,
                    policy_contract_version=request.policy_contract_version,
                    policy_snapshot=dict(request.policy_snapshot),
                    policy_hash=request.policy_hash,
                    currency=request.currency,
                    budget_timezone=request.budget_timezone,
                    started_at=request.started_at,
                    deadline_at=request.deadline_at,
                    reason=request.reason,
                    legacy_operation_ids=tuple(request.legacy_operation_ids),
                    legacy_reservation_ids=tuple(request.legacy_reservation_ids),
                ),
                principal=principal,
            )
            return asdict(receipt)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post(
        "/opening-runs/{opening_run_id}/reconcile-legacy-execution",
        status_code=202,
    )
    def reconcile_legacy_book_opening_execution(
        opening_run_id: str, request: BookOpeningAssessmentRequest
    ) -> dict[str, Any]:
        try:
            composition = _composition(ctx)
            if composition.opening is None:
                raise KernelError(
                    "BOOK_OPENING_RUNTIME_NOT_CONFIGURED", "Book opening is unavailable"
                )
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            return asdict(
                composition.opening.recovery.reconcile_legacy_execution(
                    opening_run_id,
                    idempotency_key=request.idempotency_key,
                    principal=principal,
                )
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post(
        "/opening-runs/{opening_run_id}/assess-execution-loss",
        status_code=202,
    )
    def assess_book_opening_execution_loss(
        opening_run_id: str, request: BookOpeningAssessmentRequest
    ) -> dict[str, Any]:
        try:
            composition = _composition(ctx)
            if composition.opening is None:
                raise KernelError(
                    "BOOK_OPENING_RUNTIME_NOT_CONFIGURED", "Book opening is unavailable"
                )
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            return asdict(
                composition.opening.recovery.assess_execution_loss(
                    opening_run_id,
                    idempotency_key=request.idempotency_key,
                    principal=principal,
                )
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post(
        "/opening-runs/{opening_run_id}/converge-execution-loss",
        status_code=202,
    )
    def converge_book_opening_execution_loss(
        opening_run_id: str, request: BookOpeningConvergenceRequest
    ) -> dict[str, Any]:
        try:
            composition = _composition(ctx)
            if composition.opening is None:
                raise KernelError(
                    "BOOK_OPENING_RUNTIME_NOT_CONFIGURED", "Book opening is unavailable"
                )
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            receipt = composition.opening.recovery.converge_execution_loss(
                request.recovery_assessment_id,
                idempotency_key=request.idempotency_key,
                principal=principal,
                expected_opening_run_id=opening_run_id,
            )
            if receipt.opening_run_id != opening_run_id:
                raise KernelError(
                    "BOOK_OPENING_RECOVERY_SCOPE_MISMATCH",
                    "loss assessment belongs to another Book Opening",
                )
            return asdict(receipt)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/opening-runs/{opening_run_id}/continue-unstarted-capacity", status_code=202)
    def continue_unstarted_book_opening(
        opening_run_id: str, request: BookOpeningCapacityContinuationRequest,
    ) -> dict[str, Any]:
        try:
            composition = _composition(ctx)
            if composition.opening is None:
                raise KernelError("BOOK_OPENING_RUNTIME_NOT_CONFIGURED", "Book opening is unavailable")
            principal = build_trusted_principal_resolver().resolve_api_principal(claimed_actor_id=request.actor_id)
            return asdict(composition.opening.continue_unstarted_with_budget(
                opening_run_id, expected_version=request.expected_version,
                reason=request.reason, principal=principal,
            ))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/opening-runs/{opening_run_id}/assess-recovery", status_code=202)
    def assess_book_opening_recovery(
        opening_run_id: str, request: BookOpeningAssessmentRequest
    ) -> dict[str, Any]:
        try:
            composition = _composition(ctx)
            if composition.opening is None:
                raise KernelError(
                    "BOOK_OPENING_RUNTIME_NOT_CONFIGURED", "Book opening is unavailable"
                )
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            return asdict(
                composition.opening.recovery.assess_recovery(
                    opening_run_id,
                    idempotency_key=request.idempotency_key,
                    principal=principal,
                )
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/opening-runs/{opening_run_id}/recover", status_code=202)
    def recover_book_opening(
        opening_run_id: str, request: BookOpeningRecoveryRequest
    ) -> dict[str, Any]:
        try:
            composition = _composition(ctx)
            if composition.opening is None:
                raise KernelError(
                    "BOOK_OPENING_RUNTIME_NOT_CONFIGURED", "Book opening is unavailable"
                )
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            receipt = composition.opening.recovery.recover(
                request.recovery_assessment_id,
                idempotency_key=request.idempotency_key,
                reason=request.reason,
                principal=principal,
                expected_opening_run_id=opening_run_id,
            )
            if receipt.opening_run_id != opening_run_id:
                raise KernelError(
                    "BOOK_OPENING_RECOVERY_SCOPE_MISMATCH",
                    "recovery assessment belongs to another Book Opening",
                )
            return asdict(receipt)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post(
        "/opening-runs/{opening_run_id}/assess-checkpoint-reconciliation",
        status_code=202,
    )
    def assess_book_opening_checkpoint_reconciliation(
        opening_run_id: str, request: BookOpeningCheckpointAssessmentRequest
    ) -> dict[str, Any]:
        try:
            composition = _composition(ctx)
            if composition.opening is None:
                raise KernelError(
                    "BOOK_OPENING_RUNTIME_NOT_CONFIGURED", "Book opening is unavailable"
                )
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            return asdict(
                composition.opening.recovery.assess_checkpoint_reconciliation(
                    opening_run_id,
                    semantic_work_key=request.semantic_work_key,
                    owning_authority=request.owning_authority,
                    evidence_type=request.evidence_type,
                    evidence_id=request.evidence_id,
                    evidence_version=request.evidence_version,
                    evidence_hash=request.evidence_hash,
                    idempotency_key=request.idempotency_key,
                    principal=principal,
                )
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post(
        "/opening-runs/{opening_run_id}/reconcile-checkpoint",
        status_code=202,
    )
    def reconcile_book_opening_checkpoint(
        opening_run_id: str, request: BookOpeningConvergenceRequest
    ) -> dict[str, Any]:
        try:
            composition = _composition(ctx)
            if composition.opening is None:
                raise KernelError(
                    "BOOK_OPENING_RUNTIME_NOT_CONFIGURED", "Book opening is unavailable"
                )
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            receipt = composition.opening.recovery.reconcile_checkpoint(
                request.recovery_assessment_id,
                idempotency_key=request.idempotency_key,
                principal=principal,
                expected_opening_run_id=opening_run_id,
            )
            return asdict(receipt)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/opening-runs/{opening_run_id}/abort")
    def abort_book_opening(
        opening_run_id: str, request: BookOpeningControlRequest
    ) -> dict[str, Any]:
        try:
            composition = _composition(ctx)
            if composition.opening is None:
                raise KernelError(
                    "BOOK_OPENING_RUNTIME_NOT_CONFIGURED", "Book opening is unavailable"
                )
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            return composition.opening.abort(
                opening_run_id,
                expected_version=request.expected_version,
                principal=principal,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/books/{book_id}/formation-runs", status_code=202)
    def start_story_formation(
        book_id: str, request: StoryFormationStartRequest
    ) -> dict[str, Any]:
        try:
            composition = _composition(ctx)
            if composition.formation is None:
                raise KernelError(
                    "STORY_FORMATION_RUNTIME_NOT_CONFIGURED",
                    "Story Formation is unavailable in this partial composition",
                )
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            if request.production_intent is not None:
                from pathlib import Path
                from types import SimpleNamespace
                from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
                from novel_forge.modules.book_authority.creation_runtime import execute_creation_command
                principal.require("book.authority.execute", request.project_id)
                if request.layers or request.book_design_asset_version_id or request.generation_policy:
                    raise ValueError("Continuous creation uses its exact saved author brief and production intent")
                brief = AuthorityAssetQuery(ctx.app_settings.database_url).require(project_id=request.project_id,
                    asset_version_id=request.creative_brief_asset_version_id)
                if brief.content_hash != request.creative_brief_content_hash:
                    raise KernelError("CREATION_BRIEF_SOURCE_DRIFT", "The saved author brief changed")
                from novel_forge.modules.book_design_authority.query import BookDesignAuthorityQuery
                current_book = BookDesignAuthorityQuery(ctx.app_settings.database_url).require_book(project_id=request.project_id, book_id=book_id)
                existing = composition.formation.find_by_key(project_id=request.project_id, book_id=book_id,
                    idempotency_key=f"creation:{request.project_id}:{book_id}:{request.idempotency_key}")
                expected = existing["expected_book_version"] if existing else current_book["version"]
                if current_book["workspace_id"] != request.workspace_id or expected != request.expected_book_version:
                    raise KernelError("CREATION_BOOK_VERSION_CONFLICT", "The selected Book or saved creation version changed")
                intent = request.production_intent.model_dump(exclude_none=True)
                creative_selection = intent.pop("creative_selection")
                arguments = SimpleNamespace(action="start", project_id=request.project_id, workspace_id=request.workspace_id,
                    book_id=book_id, input_file=None, formation_run_id="", idempotency_key=request.idempotency_key,
                    creation_policy_file=None, execution_template_file=ctx.app_settings.root / "config/execution_templates/author_first.json",
                    repository_root=Path(ctx.app_settings.root), maximum_ticks=100, work_window_seconds=300,
                    yield_after_window=False, foreground=False, creative_selection=creative_selection, candidate_number=None,
                    candidate_version="", candidate_hash="", reason="")
                return execute_creation_command(ctx.app_settings, arguments,
                    request_input={"version": "creation-request.v1" if "title" in intent else "creation-request.v2", "brief": brief.content, **intent},
                    brief_source=(brief.asset_version_id, brief.content_hash))
            frozen = StoryFormationInput(
                layers=tuple(
                    FormationLayerInput.from_mapping(layer.model_dump())
                    for layer in request.layers
                ),
                book_design_asset_version_id=request.book_design_asset_version_id,
                book_design_content_hash=request.book_design_content_hash,
                creative_brief_asset_version_id=request.creative_brief_asset_version_id,
                creative_brief_content_hash=request.creative_brief_content_hash,
                generation_policy=request.generation_policy,
            )
            admission = composition.formation.admit(
                StartStoryFormationCommand(
                    project_id=request.project_id,
                    workspace_id=request.workspace_id,
                    book_id=book_id,
                    actor_id=principal.principal_id,
                    expected_book_version=request.expected_book_version,
                    stable_idempotency_key=request.idempotency_key,
                    trace_id=request.trace_id or f"trace:{uuid4()}",
                    correlation_id=request.correlation_id or f"correlation:{uuid4()}",
                    frozen_input=frozen,
                ),
                principal=principal,
            )
            return {
                "formation_run_id": admission.formation_run_id,
                "root_operation_id": admission.root_operation_id,
                "runtime_job_id": admission.runtime_job_id,
                "lifecycle": admission.lifecycle,
                "replayed": admission.replayed,
            }
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.get("/formation-runs/{formation_run_id}")
    def story_formation_detail(formation_run_id: str) -> dict[str, Any]:
        try:
            composition = _composition(ctx)
            if composition.formation is None:
                raise KernelError(
                    "STORY_FORMATION_RUNTIME_NOT_CONFIGURED",
                    "Story Formation is unavailable",
                )
            principal = build_trusted_principal_resolver().resolve_api_principal()
            reviewed = composition.formation.review_candidates(formation_run_id, principal=principal)
            if (composition.formation.frozen_input(formation_run_id).generation_policy or {}).get("contract_version") in {"formation-generation.v5", "formation-generation.v7"}:
                from novel_forge.modules.book_authority.creation_runtime import creation_status
                reviewed["creation"] = creation_status(composition.authority.database_url, project_id=reviewed["project_id"],
                    formation_run_id=formation_run_id, principal=principal)
            return reviewed
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/formation-runs/{formation_run_id}/author-decisions")
    def story_formation_author_decision(
        formation_run_id: str, request: StoryFormationAuthorDecisionRequest
    ) -> dict[str, Any]:
        try:
            composition = _composition(ctx)
            if composition.formation is None:
                raise KernelError("STORY_FORMATION_RUNTIME_NOT_CONFIGURED", "Story Formation is unavailable")
            principal = build_trusted_principal_resolver().resolve_api_principal(claimed_actor_id=request.actor_id)
            return composition.formation.author_decision(
                formation_run_id, principal=principal,
                **request.model_dump(exclude={"actor_id"}),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/formation-runs/{formation_run_id}/resume", status_code=202)
    def resume_story_formation(
        formation_run_id: str, request: StoryFormationControlRequest
    ) -> dict[str, Any]:
        try:
            composition = _composition(ctx)
            if composition.formation is None:
                raise KernelError(
                    "STORY_FORMATION_RUNTIME_NOT_CONFIGURED",
                    "Story Formation is unavailable",
                )
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            run = composition.formation.require(formation_run_id)
            if (composition.formation.frozen_input(formation_run_id).generation_policy or {}).get("contract_version") in {"formation-generation.v5", "formation-generation.v7"}:
                from novel_forge.modules.book_authority.creation_runtime import schedule_creation_jobs, creation_status, creation_recovery_record
                principal.require("book.authority.execute", run["project_id"])
                composition.formation.require_continuation_live(formation_run_id)
                if not request.reason.strip() or not request.idempotency_key.strip():
                    raise ValueError("Continuous recovery requires a saved reason and request key")
                recovered = creation_recovery_record(composition.authority.database_url, formation_run_id, request.reason, request.idempotency_key)
                if not recovered and run["lifecycle"] in {"FAILED", "WAITING_APPROVAL"}:
                    composition.formation.resume(formation_run_id, expected_version=request.expected_version, principal=principal)
                elif request.expected_version > run["version"]:
                    raise KernelError("CREATION_BOOK_VERSION_CONFLICT", "Recovery view is ahead of the original source")
                schedule_creation_jobs(composition.authority.database_url, formation_run_id=formation_run_id,
                    recovery_reason=request.reason, recovery_key=request.idempotency_key)
                reviewed = composition.formation.review_candidates(formation_run_id, principal=principal)
                reviewed["creation"] = creation_status(composition.authority.database_url, project_id=run["project_id"], formation_run_id=formation_run_id, principal=principal)
                return reviewed
            return composition.formation.resume(
                formation_run_id,
                expected_version=request.expected_version,
                principal=principal,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post(
        "/formation-runs/{formation_run_id}/approve-book-design",
        status_code=202,
    )
    def approve_story_formation_book_design(
        formation_run_id: str,
        request: StoryFormationBookDesignApprovalRequest,
    ) -> dict[str, Any]:
        try:
            composition = _composition(ctx)
            if composition.formation is None:
                raise KernelError(
                    "STORY_FORMATION_RUNTIME_NOT_CONFIGURED",
                    "Story Formation is unavailable",
                )
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            return composition.formation.approve_book_design(
                formation_run_id,
                expected_version=request.expected_version,
                asset_version_id=request.book_design_asset_version_id,
                content_hash=request.book_design_content_hash,
                principal=principal,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/formation-runs/{formation_run_id}/abort")
    def abort_story_formation(
        formation_run_id: str, request: StoryFormationControlRequest
    ) -> dict[str, Any]:
        try:
            composition = _composition(ctx)
            if composition.formation is None:
                raise KernelError(
                    "STORY_FORMATION_RUNTIME_NOT_CONFIGURED",
                    "Story Formation is unavailable",
                )
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            if (composition.formation.frozen_input(formation_run_id).generation_policy or {}).get("contract_version") in {"formation-generation.v5", "formation-generation.v7"}:
                from novel_forge.modules.book_authority.creation_runtime import reconcile_creation_cancellation, creation_status
                run = composition.formation.require(formation_run_id)
                if request.expected_version > run["version"]:
                    raise KernelError("CREATION_BOOK_VERSION_CONFLICT", "Cancellation view changed; reload the original creation")
                composition.formation.cancel_continuation(formation_run_id, principal=principal,
                    reason=request.reason or "Author cancels continuous creation",
                    idempotency_key=request.idempotency_key or f"{formation_run_id}:cancel-continuation:{request.expected_version}")
                reconcile_creation_cancellation(composition, formation_run_id)
                reviewed = composition.formation.review_candidates(formation_run_id, principal=principal)
                reviewed["creation"] = creation_status(composition.authority.database_url, project_id=run["project_id"], formation_run_id=formation_run_id, principal=principal)
                return reviewed
            return composition.formation.abort(
                formation_run_id,
                expected_version=request.expected_version,
                principal=principal,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/books/{book_id}/production-inputs/resolve")
    def resolve_production_inputs(
        book_id: str, request: BookProductionInputResolveRequest
    ) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            snapshot = _composition(ctx).input_resolver.resolve(
                ResolveBookProductionInputCommand(
                    project_id=request.project_id,
                    workspace_id=request.workspace_id,
                    book_id=book_id,
                    production_profile=request.production_profile,
                    expected_book_version=request.expected_book_version,
                    narrative_chapter_cursor=request.narrative_chapter_cursor,
                    actor_id=principal.principal_id,
                    idempotency_key=request.idempotency_key,
                    trace_id=request.trace_id or f"trace:{uuid4()}",
                    correlation_id=request.correlation_id or f"correlation:{uuid4()}",
                ),
                principal=principal,
            )
            return snapshot.to_dict()
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/commands", status_code=202)
    def start_book(request: BookAuthorityStartRequest) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            book_design_version = request.book_design_version
            book_plan_version = request.book_plan_version
            production_profile_version = request.production_profile_version
            longform_context_versions = dict(request.longform_context_versions)
            if request.input_mode == "RESOLVED_AUTHORITY_INPUT":
                snapshot = _composition(ctx).input_resolver.require(
                    request.input_snapshot_id
                )
                if (snapshot.project_id, snapshot.workspace_id, snapshot.book_id) != (
                    request.project_id,
                    request.workspace_id,
                    request.book_id,
                ):
                    raise KernelError(
                        "BOOK_PRODUCTION_INPUT_SNAPSHOT_SCOPE_INVALID",
                        "resolved input snapshot belongs to another Book scope",
                    )
                book_design_version = snapshot.book_design_version
                book_plan_version = snapshot.book_plan_version
                production_profile_version = snapshot.production_profile_version
                longform_context_versions = {
                    "volume_plan_version": snapshot.current_volume_plan_version,
                    "arc_plan_versions": list(
                        snapshot.current_relevant_arc_plan_versions
                    ),
                    "character_state_version": snapshot.character_state_version,
                    "foreshadowing_state_version": snapshot.foreshadowing_state_version,
                    "quality_trend_version": snapshot.quality_trend_version,
                    "reward_ledger_version": snapshot.reward_ledger_version,
                    "promise_ledger_version": snapshot.promise_ledger_version,
                    "reader_segment_version": snapshot.reader_segment_version,
                    "reader_contract_version": snapshot.reader_contract_version,
                    "platform_profile_version": snapshot.platform_profile_version,
                }
            admission = _application(ctx).start(
                StartBookProductionCommand(
                    project_id=request.project_id,
                    workspace_id=request.workspace_id,
                    book_id=request.book_id,
                    actor_id=principal.principal_id,
                    trace_id=request.trace_id or f"trace:{uuid4()}",
                    correlation_id=request.correlation_id or f"correlation:{uuid4()}",
                    stable_idempotency_key=request.idempotency_key,
                    book_design_version=book_design_version,
                    book_plan_version=book_plan_version,
                    production_profile_version=production_profile_version,
                    longform_context_versions=longform_context_versions,
                    target_chapter_count=request.target_chapter_count,
                    light_recap_cadence=request.light_recap_cadence,
                    formal_recap_cadence=request.formal_recap_cadence,
                    input_snapshot_id=request.input_snapshot_id,
                    input_mode=request.input_mode,
                    revision_candidate_origin=request.revision_candidate_origin,
                ),
                principal=principal,
            )
            return {
                "book_run_id": admission.book_run_id,
                "root_operation_id": admission.root_operation_id,
                "saga_id": admission.saga_id,
                "state": "READY",
                "replayed": admission.replayed,
            }
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/runs/{book_run_id}/chapters", status_code=202)
    def submit_chapter(
        book_run_id: str, request: BookAuthorityChapterRequest
    ) -> dict[str, Any]:
        try:
            authority = _application(ctx)
            book = authority.require(book_run_id)
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            resolver = PostgresProductionAssetResolver(authority.database_url)
            resolved = [
                resolver.resolve_override(
                    project_id=book["project_id"],
                    asset_version_id=asset_version_id,
                )
                for asset_version_id in request.context_asset_version_ids
            ]
            plan = next(
                (
                    item
                    for item in resolved
                    if item.asset_version_id == request.chapter_plan_asset_version_id
                    and item.asset_type == "chapter_plan"
                ),
                None,
            )
            if plan is None:
                raise KernelError(
                    "CHAPTER_PLAN_AUTHORITY_INPUT_REQUIRED",
                    "context assets must contain the requested ChapterPlan version",
                )
            candidates = tuple(
                {
                    "asset_version_id": item.asset_version_id,
                    "asset_type": item.asset_type,
                    "project_id": item.project_id,
                    "content_hash": item.content_hash,
                    "content": item.content,
                    "safe_summary": str(item.content.get("safe_summary") or ""),
                    "structured_facts": list(
                        item.content.get("structured_facts") or []
                    ),
                    "estimated_tokens": int(item.content.get("estimated_tokens") or 1),
                    "narrative_function": str(
                        item.content.get("narrative_function") or item.asset_type
                    ),
                }
                for item in resolved
            )
            return authority.submit_chapter(
                SubmitBookChapterCommand(
                    book_run_id=book_run_id,
                    chapter_number=request.chapter_number,
                    title=request.title,
                    premise=request.premise,
                    chapter_plan_asset_version_id=plan.asset_version_id,
                    chapter_plan_content_hash=plan.content_hash,
                    context_candidates=candidates,
                    context_version_refs=dict(request.context_version_refs),
                    context_token_budget=request.context_token_budget,
                    preparation_report=dict(request.preparation_report),
                ),
                principal=principal,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/chapter-requests/{chapter_request_id}/reconcile")
    def reconcile_chapter(chapter_request_id: str) -> dict[str, Any]:
        try:
            request = _application(ctx).require_chapter_request(chapter_request_id)
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("book.authority.execute", request["project_id"])
            return _application(ctx).reconcile_chapter(chapter_request_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/chapter-requests/{chapter_request_id}/accept")
    def accept_chapter(chapter_request_id: str) -> dict[str, Any]:
        try:
            request = _application(ctx).require_chapter_request(chapter_request_id)
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("book.authority.execute", request["project_id"])
            return _application(ctx).accept_chapter(
                chapter_request_id, principal=principal
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/chapter-requests/{chapter_request_id}/recover")
    def recover_chapter(chapter_request_id: str) -> dict[str, Any]:
        try:
            request = _application(ctx).require_chapter_request(chapter_request_id)
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("book.authority.execute", request["project_id"])
            return _application(ctx).recover_chapter_submission(
                chapter_request_id, principal=principal
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/runs/{book_run_id}/tick")
    def tick_book(book_run_id: str) -> dict[str, Any]:
        try:
            authority = _application(ctx)
            book = authority.require(book_run_id)
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("book.authority.execute", book["project_id"])
            tick = _composition(ctx).tick(book_run_id)
            return {
                "book_run_id": tick.book_run_id,
                "previous_state": tick.previous_state,
                "state": tick.state,
                "action": tick.action,
                "operation_id": tick.operation_id,
            }
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.get("/runs/{book_run_id}")
    def book_detail(book_run_id: str) -> dict[str, Any]:
        try:
            result = _application(ctx).require(book_run_id)
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("book.authority.query", result["project_id"])
            return result
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/runs/{book_run_id}/causal-plans")
    def propose_causal_plan(book_run_id: str, request: CausalPlanningRequest) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal(claimed_actor_id=request.actor_id)
            return _composition(ctx).causal_planning.propose(principal=principal, book_run_id=book_run_id, **{k: v for k, v in asdict(request).items() if k != "actor_id"})
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.get("/runs/{book_run_id}/control-readiness")
    def book_control_readiness(book_run_id: str) -> dict[str, Any]:
        try:
            book = _application(ctx).require(book_run_id)
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("book.authority.query", book["project_id"])
            return _composition(ctx).controls.readiness(project_id=book["project_id"], book_run_id=book_run_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.get("/runs/{book_run_id}/reality/context")
    def reality_context(book_run_id: str, role: str, token_budget: int, character_id: str = "") -> dict[str, Any]:
        try:
            book = _application(ctx).require(book_run_id)
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("book.authority.query", book["project_id"])
            return _composition(ctx).query.reality_context(book_run_id=book_run_id, role=role, token_budget=token_budget, character_ids=(character_id,) if character_id else ())
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.get("/runs/{book_run_id}/reality/views/{view}")
    def narrative_reality_view(book_run_id: str, view: str, chapter_number: int | None = None, offset: int = 0, limit: int = 100, event_id: str = "") -> dict[str, Any]:
        try:
            book = _application(ctx).require(book_run_id)
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("book.authority.query", book["project_id"])
            return _composition(ctx).query.reality_view(book_run_id=book_run_id, view=view, chapter_number=chapter_number, offset=offset, limit=limit, event_id=event_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.get("/runs/{book_run_id}/reality")
    def narrative_reality(book_run_id: str, chapter_number: int | None = None) -> dict[str, Any]:
        try:
            book = _application(ctx).require(book_run_id)
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("book.authority.query", book["project_id"])
            return _composition(ctx).query.narrative_reality(book_run_id=book_run_id, chapter_number=chapter_number)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.get("/runs/{book_run_id}/progress")
    def book_progress(book_run_id: str) -> dict[str, Any]:
        try:
            book = _application(ctx).require(book_run_id)
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("book.authority.query", book["project_id"])
            return _composition(ctx).query.progress(book_run_id=book_run_id).to_dict()
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.get("/runs/{book_run_id}/chapter-groups")
    def chapter_group_lineage(book_run_id: str, offset: int = 0, limit: int = 100) -> dict[str, Any]:
        try:
            book = _application(ctx).require(book_run_id)
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("book.authority.query", book["project_id"])
            return _composition(ctx).query.chapter_group_execution_lineage(
                project_id=book["project_id"], book_run_id=book_run_id, offset=offset, limit=limit,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.get("/runs/{book_run_id}/corrective-actions")
    def corrective_actions(
        book_run_id: str,
        status: str = "",
        issue_type: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        try:
            book = _application(ctx).require(book_run_id)
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("book.authority.query", book["project_id"])
            return _composition(ctx).corrective_actions.list(
                project_id=str(book["project_id"]),
                status=status,
                issue_type=issue_type,
                limit=limit,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/runs/{book_run_id}/replans/{replan_id}/approve")
    def approve_replan(
        book_run_id: str,
        replan_id: str,
        request: BookReplanApprovalRequest,
    ) -> dict[str, Any]:
        try:
            book = _application(ctx).require(book_run_id)
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            principal.require("book.authority.approve_replan", book["project_id"])
            return _composition(ctx).approve_replan(
                book_run_id=book_run_id,
                replan_id=replan_id,
                authority_type=request.authority_type,
                authority_version=request.authority_version,
                evidence=dict(request.evidence),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/runs/{book_run_id}/replans/{replan_id}/reevaluate")
    def reevaluate_replan(
        book_run_id: str,
        replan_id: str,
        request: BookReplanReevaluationRequest,
    ) -> dict[str, Any]:
        try:
            book = _application(ctx).require(book_run_id)
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            principal.require("book.authority.execute", book["project_id"])
            return _composition(ctx).reevaluate_replan(
                book_run_id=book_run_id,
                replan_id=replan_id,
                source_recap_asset_version_id=(request.source_recap_asset_version_id),
                deviation_report_asset_version_id=(
                    request.deviation_report_asset_version_id
                ),
                idempotency_key=request.idempotency_key,
                trace_id=request.trace_id or f"trace:{uuid4()}",
                correlation_id=request.correlation_id or f"correlation:{uuid4()}",
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/runs/{book_run_id}/pause")
    def pause_book(
        book_run_id: str, request: BookAuthorityControlRequest
    ) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            return _application(ctx).pause(
                book_run_id, reason=request.reason, principal=principal
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/runs/{book_run_id}/resume")
    def resume_book(
        book_run_id: str, request: BookAuthorityControlRequest
    ) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            return _application(ctx).resume(
                book_run_id, reason=request.reason, principal=principal
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/runs/{book_run_id}/cancel")
    def cancel_book(
        book_run_id: str, request: BookAuthorityControlRequest
    ) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            return _application(ctx).cancel(
                book_run_id, reason=request.reason, principal=principal
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    return router


def _application(ctx: ProductRouterContext):
    return ctx.services.book_authority_application


def _composition(ctx: ProductRouterContext):
    return ctx.services.book_production


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KernelError):
        return HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message, "failure": exc.details},
        )
    return HTTPException(status_code=503, detail=str(exc))


__all__ = ["create_router"]
