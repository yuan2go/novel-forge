from __future__ import annotations
from .foundation_generation import FOUNDATION_GENERATORS, require_resolved_foundation_applicability, validate_foundation_payload
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import asdict, replace
from typing import Any
from uuid import uuid4
from psycopg import sql
from psycopg.types.json import Jsonb
from novel_forge.modules.authority_handler_runtime import (
    AuthorityHandlerOutput,
    AuthorityHandlerRegistration,
    AuthorityHandlerRequest,
)
from novel_forge.modules.authority_security import (
    Principal,
    require_worker_scoped_auto_decision,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.asset_commands import (
    AuthorityAssetWriteCommand,
)
from novel_forge.modules.command_kernel.operation_graph import (
    GraphCommandContext,
    start_saga,
)
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    TransactionCheckpoint,
    admit_command,
    execute_transaction_command,
)
from novel_forge.modules.content_authority.scheduler import ContentAuthorityScheduler
from novel_forge.modules.hierarchical_planning import (
    PlanContractType,
    PlanExecutionScope,
    PostgresHierarchicalPlanningAuthority,
    validate_planning_contract,
)
from novel_forge.modules.story_design_authority import (
    GENERATOR_CATALOG,
    DesignTransition,
    PostgresStoryDesignAssetAuthority,
    StoryDesignTransitionCommand,
)
from novel_forge.modules.story_design_authority.validators import (
    validate_story_design_candidate,
)
from novel_forge.modules.story_design_authority.qualification import (
    qualification_profile_options,
    required_qualification_profiles,
    scripted_qualification,
)
from novel_forge.modules.story_design_authority.evaluation_runtime import (
    NARRATIVE_EVALUATION_DEFINITION as STORY_PLANNING_EVALUATION_DEFINITION,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.narrative_realization_repositories import (
    NarrativeRealizationRepository,
)
from .binder import PlanningExecutionBinder
from .domain import (
    CHAPTER_READER_SCHEDULE_FIELDS,
    CHAPTER_SCHEDULE_FIELDS,
    STORY_PLANNING_MAX_ATTEMPTS,
    STORY_PLANNING_OPERATION_DEFINITION_REF,
    STORY_PLANNING_OPERATION_TIMEOUT_SECONDS,
    FrozenPlanningInput,
    PlanningGenerationResult,
    PlanningGenerationStatus,
    StoryPlanningEvaluationCommand,
    StoryPlanningGenerationCommand,
    build_planning_constraint_envelope,
    canonical_book_volume_allocation,
    canonical_hash,
    require_chapter_schedule_row,
)
from novel_forge.modules.story_design_authority.evaluation_runtime import (
    NARRATIVE_EVALUATION_HANDLER as STORY_PLANNING_EVALUATION_HANDLER,
)
from novel_forge.modules.story_design_authority.evaluation_runtime import (
    NARRATIVE_EVALUATION_VERSION as STORY_PLANNING_EVALUATION_VERSION,
)
from novel_forge.modules.story_design_authority.evaluation_runtime import (
    NarrativeSemanticEvaluationApplication,
    NarrativeSemanticEvaluationCommand,
    NarrativeSemanticEvaluationExecutionPort,
    NarrativeSemanticEvaluationResult,
)

STORY_PLANNING_GENERATION_DEFINITION = "story_planning.generate"
STORY_PLANNING_GENERATION_VERSION = STORY_PLANNING_OPERATION_DEFINITION_REF.rpartition(
    "@"
)[2]
STORY_PLANNING_GENERATION_HANDLER = "novel_forge.story_planning.generate"
CHAPTER_PLAN_PROJECTION_DEFINITION = "story_planning.chapter_plan.materialize"
CHAPTER_PLAN_PROJECTION_HANDLER = "novel_forge.story_planning.chapter_plan.materialize"


class _ChapterProjectionAlreadyMaterialized(Exception):
    def __init__(self, result: dict[str, Any]) -> None:
        super().__init__("exact Chapter projection already materialized")
        self.result = result


_PLAN_INPUT_CONTRACTS = {
    "book_plan": PlanContractType.BOOK,
    "volume_plan": PlanContractType.VOLUME,
    "arc_plans": PlanContractType.ARC,
    "chapter_group_plan": PlanContractType.CHAPTER_GROUP,
}

_AUTHORITY_INPUT_ASSET_TYPES = {
    "story_state": frozenset({"story_state", "story_state_snapshot"}),
    "reader_state": frozenset({"reader_state", "reader_state_transition"}),
    "character_state": frozenset({"character_state", "character_state_snapshot"}),
    "foreshadowing_state": frozenset({"foreshadowing_state", "foreshadow_snapshot"}),
    "reward_ledger": frozenset({"reward_ledger", "reward_ledger_snapshot"}),
    "promise_ledger": frozenset({"promise_ledger", "promise_ledger_snapshot"}),
    "previous_volume_outcome": frozenset({"previous_volume_outcome", "volume_outcome"}),
    "previous_chapter_group_outcome": frozenset(
        {"previous_chapter_group_outcome", "chapter_group_outcome"}
    ),
    "previous_chapter_outcome": frozenset(
        {"previous_chapter_outcome", "chapter_outcome"}
    ),
    "ending_reachability": frozenset(
        {"ending_reachability", "ending_reachability_report"}
    ),
    "narrative_search_parent_state": frozenset(
        {"story_state", "story_state_snapshot", "narrative_state"}
    ),
}


class _PlanningGenerationHandler:
    def __init__(self, binder: PlanningExecutionBinder, database_url: str = "") -> None:
        self.binder = binder
        self.database_url = database_url

    def execute(self, request: AuthorityHandlerRequest) -> AuthorityHandlerOutput:
        from .result_recovery import (
            PlanningResultValidationError,
            persist_result_failure,
        )

        try:
            return self._execute(request)
        except PlanningResultValidationError as error:
            if self.database_url:
                persist_result_failure(self.database_url, request=request, command=_command_from_payload(dict(request.command["payload"])), error=error)
            raise

    def _execute(self, request: AuthorityHandlerRequest) -> AuthorityHandlerOutput:
        payload = request.command.get("payload")
        if not isinstance(payload, dict):
            raise KernelError(
                "PLANNING_GENERATION_INPUT_INVALID",
                "Planning Generation payload must be an object",
            )
        command = _command_from_payload(payload)
        bootstrap = payload.get("routing_bootstrap_authorization")
        if bool(command.routing_bootstrap_authorization_id) != bool(bootstrap) or (
            bootstrap
            and (
                not isinstance(bootstrap, Mapping)
                or bootstrap.get("project_id") != command.project_id
                or bootstrap.get("environment") != "validation"
                or not isinstance(bootstrap.get("authorization"), Mapping)
                or bootstrap["authorization"].get("authorization_id")
                != command.routing_bootstrap_authorization_id
            )
        ):
            raise KernelError(
                "PLANNING_BOOTSTRAP_AUTHORIZATION_MISSING",
                "bootstrap candidate requires its server-frozen authorization",
            )
        if (
            command.project_id != request.project_id
            or command.workspace_id != request.workspace_id
        ):
            raise KernelError(
                "PLANNING_GENERATION_SCOPE_MISMATCH",
                "Planning Generation command differs from admitted scope",
            )
        definition = GENERATOR_CATALOG.get(command.generator_operation_name)
        if definition is None:
            raise KernelError(
                "GENERATOR_DEFINITION_NOT_FOUND",
                "Planning GeneratorDefinition is not registered",
            )
        by_id = {item.asset_version_id: item for item in request.inputs}
        inputs: list[FrozenPlanningInput] = []
        authority_roles = _authority_role_versions(command)
        for role, asset_version_id in authority_roles.items():
            item = by_id.get(asset_version_id)
            if item is None:
                raise KernelError(
                    "PLANNING_GENERATION_FROZEN_INPUT_MISSING",
                    f"admitted input is missing Authority role {role}",
                )
            inputs.append(
                FrozenPlanningInput(
                    role=role,
                    asset_version_id=item.asset_version_id,
                    content_hash=item.content_hash,
                    asset_type=item.asset_type,
                )
            )
        for asset_version_id in command.change_evidence_version_ids:
            item = by_id.get(asset_version_id)
            if item is None:
                raise KernelError(
                    "PLANNING_GENERATION_CHANGE_EVIDENCE_MISSING",
                    "admitted Planning input is missing frozen change evidence",
                )
        candidate = self.binder.execute(
            operation_id=request.operation_id,
            attempt_id=request.attempt_id,
            fencing_token=request.fencing_token,
            worker_id=request.worker_id,
            command=command,
            inputs=tuple(inputs),
            definition=definition,
        )
        if "craft_strategy" in candidate.candidate_payload:
            raise KernelError("CRAFT_PROVIDER_STRATEGY_FORBIDDEN", "Craft strategy is derived from exact governed selection after Provider translation validation")
        evidence = candidate.evidence.to_dict()
        knowledge_policy = ""
        knowledge_refs: tuple[str, ...] = ()
        author_projection: dict[str, Any] = {}
        craft_strategy = None
        title_contract = None
        if self.database_url and candidate.evidence.context_bundle_asset_version_id:
            from novel_forge.storage.authority_asset_store import AuthorityAssetQuery

            from .knowledge_translation import validate_knowledge_translations

            context = AuthorityAssetQuery(self.database_url).require(
                project_id=command.project_id,
                asset_version_id=candidate.evidence.context_bundle_asset_version_id,
            )
            title_contract = context.content.get("generated_title_contract")
            if title_contract is not None and (
                title_contract != "generated-book-title.v1" or context.content_hash != candidate.evidence.context_bundle_hash
                or command.generator_operation_name != "creative.candidates.generate"
            ):
                raise KernelError("FOUNDATION_TITLE_CONTRACT_INVALID", "Title generation must bind its exact native Context")
            selection = context.content.get("narrative_intelligence") or {}
            if any(item.get("selected_content", {}).get("craft_mechanism") for item in selection.get("selected") or ()) and (
                context.content_hash != candidate.evidence.context_bundle_hash
                or selection.get("selection_digest") != candidate.evidence.narrative_intelligence_selection_digest
            ):
                raise KernelError("CRAFT_PLANNING_SELECTION_DRIFT", "Craft planning evidence must bind the exact persisted Context and frozen selection")
            from novel_forge.modules.story_design_authority.author_input import validate_author_decisions
            author_projection = dict(context.content.get("author_design_projection") or {})
            try:
                validate_author_decisions(candidate.candidate_payload, author_projection)
            except KernelError as error:
                from .result_recovery import PlanningResultValidationError
                raise PlanningResultValidationError(error, raw_result=candidate.raw_provider_result or candidate.candidate_payload, execution_evidence=evidence) from error
            if selection.get("policy_version") == "knowledge-grounded-selection-v2":
                try:
                    validate_knowledge_translations(candidate.candidate_payload, selection)
                    knowledge_policy = selection["policy_version"]
                    if command.generator_operation_name == "chapter_plan.generate":
                        from novel_forge.modules.mkaos_authority.craft_reselection import validate_concrete_selection
                        from novel_forge.modules.mkaos_authority.craft_selection import build_craft_strategy
                        validate_concrete_selection(candidate.candidate_payload, selection)
                        craft_strategy = build_craft_strategy(candidate.candidate_payload, selection)
                except KernelError as error:
                    if selection.get("craft_policy", {}).get("schema_version") != "narrative-craft-budget.v4":
                        raise
                    from .result_recovery import PlanningResultValidationError
                    raise PlanningResultValidationError(error, raw_result=candidate.candidate_payload, execution_evidence=evidence) from error
            knowledge_refs = tuple(
                item["knowledge_card_asset_version_id"] for item in selection.get("selected") or ()
            )
        if (
            evidence["operation_id"] != request.operation_id
            or evidence["attempt_id"] != request.attempt_id
            or int(evidence["fencing_token"]) != request.fencing_token
        ):
            raise KernelError(
                "PLANNING_EXECUTION_EVIDENCE_DRIFT",
                "PEP candidate evidence differs from the current Authority Attempt",
            )
        world_refs = ()
        envelope = build_planning_constraint_envelope(
            project_id=command.project_id,
            book_id=command.book_id,
            generation_operation_id=request.operation_id,
            generator_operation_name=command.generator_operation_name,
            frozen_inputs=tuple(inputs),
            input_contents={
                role: by_id[asset_version_id].content
                for role, asset_version_id in authority_roles.items()
            },
            candidate_payload=candidate.candidate_payload,
            arc_working_set=command.arc_working_set,
            work_requirements=command.execution_contract_version in {"1.17.0", "1.18.0", "1.19.0", "1.21.0"},
            aligned_methods=command.execution_contract_version in {"1.18.0", "1.19.0", "1.21.0"},
            rfc6901_paths=command.execution_contract_version in {"1.19.0", "1.21.0"},
        )
        if command.generator_operation_name in FOUNDATION_GENERATORS and command.narrative_search_id and command.execution_contract_version == "1.21.0":
            envelope["contract_version"] = "foundation-generation.v5"
            envelope["narrative_search"] = command.narrative_search_snapshot
        if title_contract is not None:
            envelope["generated_title_contract"] = title_contract
        if envelope.get("author_design"):
            from novel_forge.modules.story_design_authority.author_input import frozen_author_projection
            envelope["author_design_projection"] = author_projection
            frozen_author_projection({"constraint_envelope": envelope}, generator=command.generator_operation_name, logical_key=command.logical_key)
            if "envelope_digest" in envelope:
                envelope["envelope_digest"] = canonical_hash({key: value for key, value in envelope.items() if key != "envelope_digest"})
        if command.world_preparation_request:
            from novel_forge.storage.authority_asset_store import AuthorityAssetQuery

            from .world_preparation import require_world_action

            action = require_world_action(
                AuthorityAssetQuery(self.database_url),
                command=command,
                operation_id=request.operation_id,
            )
            source = AuthorityAssetQuery(self.database_url).require(
                project_id=command.project_id,
                asset_version_id=action.content["contract"]["source"][
                    "asset_version_id"
                ],
            )
            envelope["world_preparation"] = {
                "asset_version_id": action.asset_version_id,
                "content_hash": action.content_hash,
                "action": action.content["contract"],
                "frozen_source": source.content["contract"],
            }
            if (
                action.content["contract"].get("contract_version")
                == "world-production-action.v2"
            ):
                from novel_forge.modules.canon_graph.background import (
                    bind_world_execution,
                )

                envelope["world_execution"] = bind_world_execution(
                    envelope["world_preparation"],
                    candidate.candidate_payload.get("scene_plan", []),
                )
            envelope["envelope_digest"] = canonical_hash(
                {
                    key: value
                    for key, value in envelope.items()
                    if key != "envelope_digest"
                }
            )
            world_refs = (action.asset_version_id,)
        if command.edition_execution:
            from novel_forge.modules.book_authority.edition_planning import validate_edition_plan_scope
            validate_edition_plan_scope(self.database_url, project_id=command.project_id, book_id=command.book_id, scope=dict(command.edition_execution))
            target_scenes = command.edition_execution.get("target_scene_ids") or []
            if target_scenes and [scene["scene_id"] for scene in candidate.candidate_payload.get("scene_plan", [])] != list(target_scenes):
                raise KernelError("EDITION_SCENE_MAPPING_DRIFT", "Edition planning must preserve the mapped source Scene identities and order")
            target_slots = command.edition_execution.get("target_slot_ids") or []
            if target_slots:
                from novel_forge.modules.book_authority.edition_planning import require_edition_slot_mapping
                require_edition_slot_mapping(candidate.candidate_payload, list(target_slots))
            envelope["edition_execution"] = deepcopy(dict(command.edition_execution))
            envelope["envelope_digest"] = canonical_hash({key: value for key, value in envelope.items() if key != "envelope_digest"})
        content = candidate.authority_content(
            project_id=command.project_id,
            book_id=command.book_id,
            constraint_envelope=envelope,
        )
        if knowledge_policy:
            content["knowledge_translation_policy_version"] = knowledge_policy
        if craft_strategy is not None:
            content["craft_strategy"] = craft_strategy
            content["candidate_payload"]["craft_strategy"] = craft_strategy
        if bootstrap:
            content["routing_eligibility"] = "BENCHMARK_ONLY"
            content["routing_bootstrap_authorization"] = dict(bootstrap)
        return AuthorityHandlerOutput(
            # WHY: One generic worker Operation has one frozen output contract.
            # The concrete candidate kind remains frozen in the Generator
            # Definition and candidate content; it cannot change the admitted
            # OperationDefinition output selector mid-Attempt.
            asset_type="planning_generation_candidate",
            output_key="story_planning.candidate",
            role="primary",
            content=content,
            qualification_policy="story-planning-candidate-only-v1",
            reference_asset_version_ids=(
                *(item.asset_version_id for item in inputs),
                *command.change_evidence_version_ids,
                *world_refs,
                *knowledge_refs,
            ),
            evidence=evidence,
            # INVARIANT: Generation only creates an immutable candidate.  Semantic
            # Evaluation and activation own the two later transitions.
            lifecycle="CANDIDATE",
            eligibility="INELIGIBLE",
            governance="CLEAR",
        )


class StoryPlanningGenerationHandlerRegistry:
    def __init__(self, binder: PlanningExecutionBinder, database_url: str = "") -> None:
        generation = AuthorityHandlerRegistration(
            definition_name=STORY_PLANNING_GENERATION_DEFINITION,
            definition_version=STORY_PLANNING_GENERATION_VERSION,
            handler_key=STORY_PLANNING_GENERATION_HANDLER,
            handler_contract_version="story-planning-generation-handler-v1",
            output_asset_type="planning_generation_candidate",
            output_key="story_planning.candidate",
            role="primary",
            completion_topic="story_planning.candidate.materialized",
            handler=_PlanningGenerationHandler(binder, database_url),
        )
        self.items = {
            STORY_PLANNING_GENERATION_DEFINITION: generation,
        }
        from .world_sampling import WORLD_SAMPLE_STAGES, WORLD_SAMPLE_VERSION, WorldSampleHandler

        for stage in WORLD_SAMPLE_STAGES:
            name = "world.provider.sample." + stage.rsplit(".", 1)[1]
            self.items[name] = AuthorityHandlerRegistration(definition_name=name, definition_version=WORLD_SAMPLE_VERSION,
                handler_key="novel_forge." + name, handler_contract_version="world-provider-sample.v1",
                output_asset_type="world_provider_sample", output_key="world.sample.output", role="primary",
                completion_topic="world.sample.materialized", handler=WorldSampleHandler(binder, database_url))

    @property
    def available_handler_keys(self) -> frozenset[str]:
        return frozenset(item.handler_key for item in self.items.values())

    @property
    def definition_names(self) -> frozenset[str]:
        return frozenset(self.items)

    def registration(
        self, definition_name: str, definition_version: str
    ) -> AuthorityHandlerRegistration:
        item = self.items.get(definition_name)
        if item is not None and definition_name.startswith("world.provider.sample."):
            from .world_sampling import WORLD_REFERENCE_SAMPLE_VERSION

            supported = {item.definition_version}
            if definition_name == "world.provider.sample.evaluate":
                supported.add(WORLD_REFERENCE_SAMPLE_VERSION)
            if definition_version not in supported:
                raise KeyError((definition_name, definition_version))
            return replace(item, definition_version=definition_version)
        if item is None or definition_version not in {
            STORY_PLANNING_GENERATION_VERSION,
            "1.11.0",
            "1.12.0",
            "1.13.0",
            "1.14.0",
            "1.15.0",
            "1.16.0",
            "1.17.0",
            "1.18.0",
            "1.19.0",
        }:
            raise KeyError((definition_name, definition_version))
        return replace(item, definition_version=definition_version)


def _requires_formation_decision_evidence(logical_key: str) -> bool:
    return logical_key.startswith("story-formation:")


class StoryPlanningGenerationApplication:
    def __init__(
        self,
        database_url: str,
        *,
        execution_binder: PlanningExecutionBinder,
        application_build_id: str,
        commit_sha: str,
        worker_id: str = "story-planning-generation-worker",
        semantic_evaluation_execution_port: NarrativeSemanticEvaluationExecutionPort
        | None = None,
        allow_scripted_evaluation_fixture: bool = False,
        narrative_evaluator_principal: Principal | None = None,
    ) -> None:
        if not database_url or not application_build_id or len(commit_sha) != 40:
            raise ValueError(
                "Planning Generation requires PostgreSQL and build identity"
            )
        self.database_url = database_url
        self.execution_binder = execution_binder
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.worker_id = worker_id
        self.allow_scripted_evaluation_fixture = allow_scripted_evaluation_fixture
        self.narrative_evaluator_principal = narrative_evaluator_principal
        self.registry = StoryPlanningGenerationHandlerRegistry(execution_binder, database_url)
        self.semantic_evaluation = NarrativeSemanticEvaluationApplication(
            database_url,
            application_build_id=application_build_id,
            commit_sha=commit_sha,
            worker_id=f"{worker_id}:semantic-evaluation",
            execution_port=semantic_evaluation_execution_port,
            allow_scripted_fixture=allow_scripted_evaluation_fixture,
        )
        self.story_design = PostgresStoryDesignAssetAuthority(
            database_url,
            application_build_id=application_build_id,
            commit_sha=commit_sha,
            worker_id=f"{worker_id}:story-design",
        )
        self.planning = PostgresHierarchicalPlanningAuthority(
            database_url,
            application_build_id=application_build_id,
            commit_sha=commit_sha,
        )

    def register_runtime_continuation(self, source_operation_id: str, *, project_id: str, principal: Principal, expected_source_version: int, decision_evidence: Mapping[str, Any], trace_id: str, correlation_id: str) -> dict[str, Any]:
        from .runtime_continuation import register
        return register(self, source_operation_id, project_id=project_id, principal=principal, expected_source_version=expected_source_version, decision_evidence=decision_evidence, trace_id=trace_id, correlation_id=correlation_id)

    def generate(
        self,
        command: StoryPlanningGenerationCommand,
        *,
        principal: Principal,
        execution_probe: Callable[[], object] | None = None,
    ) -> PlanningGenerationResult:
        principal.require("story_planning.authority.execute", command.project_id)
        if principal.principal_id != command.actor_id:
            raise PermissionError(
                "Planning Generation actor must be the trusted Principal"
            )
        environment = (
            str(getattr(getattr(self.execution_binder, "resolver", None), "environment", ""))
            if command.routing_bootstrap_authorization_id else ""
        )
        if command.routing_bootstrap_authorization_id and environment != "validation":
            raise KernelError(
                "ROUTING_BOOTSTRAP_ENVIRONMENT_FORBIDDEN",
                "benchmark challengers require the validation runtime",
            )
        self._probe(execution_probe)
        continuation = None
        if command.runtime_continuation_id:
            from .runtime_continuation import require_successor
            continuation = require_successor(self, command, validate_runtime=False)
        replay = self._terminal_generation_replay(command, principal=principal, execution_probe=execution_probe)
        if replay is not None:
            return replay
        if continuation is not None:
            continuation = require_successor(self, command)
        definition = GENERATOR_CATALOG[command.generator_operation_name]
        self._register_definitions(command.execution_contract_version)
        frozen_inputs = self._resolve_inputs(command)
        if command.generator_operation_name == "book_plan.generate":
            with AuthorityUnitOfWork(self.database_url) as uow:
                self.planning._require_qualified_foundation_for_book_plan(
                    uow.cursor,
                    project_id=command.project_id,
                    book_id=command.book_id,
                    content={
                        "frozen_inputs": [asdict(item) for item in frozen_inputs],
                    },
                )
        frozen_change_evidence = self._resolve_change_evidence(command)
        input_assets = [
            {
                "asset_version_id": item.asset_version_id,
                "content_hash": item.content_hash,
            }
            for item in frozen_inputs
        ]
        input_assets.extend(
            {
                "asset_version_id": item.asset_version_id,
                "content_hash": item.content_hash,
            }
            for item in frozen_change_evidence
        )
        working = (command.arc_working_set or {}).get("working_manuscript")
        if working:
            from novel_forge.modules.book_authority.manuscript import verify_working_context
            with AuthorityUnitOfWork(self.database_url) as uow:
                uow.cursor.execute("SELECT to_jsonb(b) FROM authority_book_production b WHERE book_run_id=%s AND project_id=%s AND book_id=%s", [working["book_run_id"], command.project_id, command.book_id])
                owner = uow.cursor.fetchone()
                if owner is None:
                    raise KernelError("MANUSCRIPT_CONTEXT_INVALID", "Planning working sources require their exact Book owner")
                verify_working_context(uow, owner[0], working)
            input_assets.extend({"asset_version_id": source["asset_version_id"], "content_hash": source["content_hash"]} for source in working["sources"])
        if command.edition_execution:
            from novel_forge.modules.book_authority.edition_planning import require_edition_planning_request, validate_edition_plan_scope
            require_edition_planning_request(self.database_url, project_id=command.project_id, book_id=command.book_id,
                scope=dict(command.edition_execution), definition_name=STORY_PLANNING_GENERATION_DEFINITION, idempotency_key=command.idempotency_key)
            input_assets.extend(validate_edition_plan_scope(self.database_url, project_id=command.project_id,
                book_id=command.book_id, scope=dict(command.edition_execution)))
        if command.narrative_realization:
            self._require_frozen_realization_slice(command)
            proof = self._require_asset(
                project_id=command.project_id,
                asset_version_id=str(
                    command.narrative_realization["proof_asset_version_id"]
                ),
            )
            if str(proof["content_hash"]) != str(
                command.narrative_realization["proof_hash"]
            ):
                raise KernelError(
                    "NARRATIVE_REALIZATION_PROOF_STALE",
                    "ChapterPlan proof asset differs from the Frozen Realization",
                )
            input_assets.append(
                {
                    "asset_version_id": str(proof["asset_version_id"]),
                    "content_hash": str(proof["content_hash"]),
                }
            )
        if command.repair_of_operation_id:
            from .result_recovery import require_result_repair_source
            repair_source = require_result_repair_source(self.database_url, command=command, operation_id=command.repair_of_operation_id, source_asset_version_id=command.repair_result_asset_version_id)
            if repair_source["diagnostic"] != dict(command.repair_result_diagnostic or {}):
                raise KernelError("PLANNING_RESULT_REPAIR_DIAGNOSTIC_DRIFT", "the frozen result repair diagnosis changed")
            input_assets.append({"asset_version_id": repair_source["asset_version_id"], "content_hash": repair_source["content_hash"]})
        causation_operation_id = (
            (continuation["source_operation_id"] if continuation else "")
            or command.repair_of_operation_id
            or command.parent_agent_session_operation_id
            or None
        )
        if command.repair_of_candidate_id:
            from .execution import require_candidate_repair_operation

            repair_asset = self._require_asset(
                project_id=command.project_id,
                asset_version_id=command.repair_of_candidate_id,
            )
            if (
                repair_asset["content"].get("routing_eligibility") == "BENCHMARK_ONLY"
                or repair_asset["content"].get("routing_bootstrap_authorization")
            ):
                raise KernelError(
                    "PLANNING_BENCHMARK_ONLY",
                    "bootstrap candidates cannot become production repair inputs",
                )
            input_assets.append(
                {
                    "asset_version_id": repair_asset["asset_version_id"],
                    "content_hash": repair_asset["content_hash"],
                }
            )
            with AuthorityUnitOfWork(self.database_url) as uow:
                source_operation_id = require_candidate_repair_operation(
                    uow.cursor, candidate_asset_version_id=command.repair_of_candidate_id,
                    project_id=command.project_id, book_id=command.book_id,
                    generator_operation_name=command.generator_operation_name,
                    logical_key=command.logical_key,
                )
                uow.cursor.execute("SELECT definition_version FROM authority_operation WHERE operation_id=%s AND project_id=%s", [source_operation_id, command.project_id])
                source_version = uow.cursor.fetchone()
                if source_version is None or str(source_version[0]) != command.execution_contract_version:
                    raise KernelError("PLANNING_REPAIR_CONTRACT_DRIFT", "candidate repair must retain the source generation contract")
                uow.cursor.execute(
                    "SELECT causation_operation_id FROM authority_operation WHERE project_id=%s AND definition_name=%s AND idempotency_scope='book:story-planning-generation' AND idempotency_key=%s",
                    [command.project_id, STORY_PLANNING_GENERATION_DEFINITION, command.idempotency_key],
                )
                retained = uow.cursor.fetchone()
            causation_operation_id = (
                retained[0]
                if retained
                else (
                    continuation["source_operation_id"]
                    if continuation
                    else source_operation_id
                )
            )
        input_assets = self._replay_ordered_input_assets(
            command=command,
            resolved_input_assets=_canonical_admission_assets(input_assets),
        )
        payload = _command_payload(command)
        if command.routing_bootstrap_authorization_id:
            from novel_forge.modules.authority_handler_runtime.routing_bootstrap import (
                freeze_planning_bootstrap_authorization,
            )

            payload["routing_bootstrap_authorization"] = (
                freeze_planning_bootstrap_authorization(
                    database_url=self.database_url,
                    command_payload=payload,
                    principal=principal,
                    environment=environment,
                )
            )
        self._probe(execution_probe)
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": STORY_PLANNING_GENERATION_DEFINITION,
                "definition_version": command.execution_contract_version,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "book_id": command.book_id,
                "logical_key": command.logical_key,
                "actor_id": command.actor_id,
                "idempotency_scope": "book:story-planning-generation",
                "idempotency_key": command.idempotency_key,
                "trace_id": command.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": command.correlation_id,
                "causation_id": (
                    command.parent_agent_session_operation_id
                    or command.repair_of_operation_id
                    or command.repair_of_candidate_id
                ),
                "causation_operation_id": causation_operation_id,
                "input": {
                    "project_id": command.project_id,
                    "input_asset_version_ids": [
                        item["asset_version_id"] for item in input_assets
                    ],
                    "payload": payload,
                },
                "input_assets": input_assets,
            },
            context=AdmissionContext(
                actor_id=command.actor_id,
                permissions=frozenset({"story_planning.authority.execute"}),
                available_handlers=self.registry.available_handler_keys,
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
        )
        operation_id = str(admitted["operation_id"])
        self._record_generation(
            operation_id=operation_id,
            command=command,
            inputs=(*frozen_inputs, *frozen_change_evidence),
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(
                operation_id, command.project_id
            )
        if state["status"] == "ADMITTED":
            transition_operation(
                self.database_url,
                OperationTransitionCommand(
                    operation_id=operation_id,
                    project_id=command.project_id,
                    expected_version=int(state["version"]),
                    expected_status="ADMITTED",
                    target_status="READY",
                    actor_id=command.actor_id,
                    reason="Planning Generation inputs and Pack route are frozen",
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    causation_id=(
                        command.parent_agent_session_operation_id
                        or command.repair_of_candidate_id
                    ),
                ),
            )
            start_saga(
                self.database_url,
                GraphCommandContext(
                    command.project_id,
                    command.actor_id,
                    command.trace_id,
                    command.correlation_id,
                ),
                root_operation_id=operation_id,
            )
        generation = self.require_generation(operation_id)
        existing_candidate_id = str(generation.get("candidate_asset_version_id") or "")
        if existing_candidate_id:
            existing_candidate = self.require_candidate(existing_candidate_id)
            advanced = self._advance_candidate(
                operation_id=operation_id,
                candidate_asset_version_id=existing_candidate_id,
                candidate_content_hash=str(existing_candidate["content_hash"]),
                command=command,
                principal=principal,
                replayed=True,
                definition=definition,
            )
            return self._evaluate_pending_if_required(
                advanced=advanced,
                generation_command=command,
                principal=principal,
                execution_probe=execution_probe,
            )
        self._probe(execution_probe)
        if command.world_preparation_request:
            from .world_result_recovery import resume_world_result_checkpoint
            resume_world_result_checkpoint(self.database_url, command=command, operation_id=operation_id)
        try:
            scheduled = ContentAuthorityScheduler(
                self.database_url,
                registry=self.registry,
                worker_id=self.worker_id,
            ).run_or_recover(operation_id=operation_id, project_id=command.project_id)
        except KernelError as error:
            if error.code in {
                "PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED",
                "CONTENT_RECOVERY_RETRY_EXHAUSTED",
            }:
                continued = self._terminal_generation_replay(
                    command, principal=principal, execution_probe=execution_probe
                )
                if continued is not None:
                    return continued
            from .world_result_recovery import WORLD_GENERATION_CONTRACT_ERRORS
            if error.code not in {"PLANNING_GENERATION_RESULT_INVALID", "WORLD_PREPARATION_RESULT_INVALID"} and not (
                command.world_preparation_request and error.code in WORLD_GENERATION_CONTRACT_ERRORS
            ):
                raise
            return self._repair_unmaterialized_result(command, operation_id=operation_id, principal=principal, execution_probe=execution_probe)
        self._probe(execution_probe)
        candidate_id = scheduled.output.asset_version_id
        self._record_candidate(
            operation_id=operation_id,
            candidate_asset_version_id=candidate_id,
            candidate_content_hash=scheduled.output.content_hash,
            command=command,
            attempt_id=scheduled.attempt_id,
        )
        advanced = self._advance_candidate(
            operation_id=operation_id,
            candidate_asset_version_id=candidate_id,
            candidate_content_hash=scheduled.output.content_hash,
            command=command,
            principal=principal,
            replayed=bool(admitted["replayed"]),
            definition=definition,
        )
        return self._evaluate_pending_if_required(
            advanced=advanced,
            generation_command=command,
            principal=principal,
            execution_probe=execution_probe,
        )

    def evaluate_candidate(
        self,
        command: StoryPlanningEvaluationCommand,
        *,
        principal: Principal,
        transition_principal: Principal | None = None,
        execution_probe: Callable[[], object] | None = None,
    ) -> PlanningGenerationResult | NarrativeSemanticEvaluationResult:
        from novel_forge.modules.story_design_authority.author_supervision import supervised_state
        principal.require("narrative_design.evaluate", command.project_id)
        if principal.principal_id != command.actor_id:
            raise PermissionError(
                "Planning Evaluation actor must be the trusted Principal"
            )
        transition_principal = transition_principal or principal
        transition_principal.require(
            "story_planning.authority.execute", command.project_id
        )
        generation = self.require_candidate(command.candidate_asset_version_id)
        if (
            generation["project_id"] != command.project_id
            or generation["workspace_id"] != command.workspace_id
            or generation["book_id"] != command.book_id
            or generation["generation_operation_id"] != command.generation_operation_id
            or generation["generator_operation_name"]
            != command.generator_operation_name
            or generation["content_hash"] != command.candidate_content_hash
        ):
            raise KernelError(
                "NARRATIVE_EVALUATION_LINEAGE_INVALID",
                "Planning Evaluation differs from the frozen candidate lineage",
            )
        state = self.story_design.require(
            project_id=command.project_id,
            asset_version_id=command.candidate_asset_version_id,
        )
        if state["qualification"] != "STRUCTURALLY_VALID" and not supervised_state(state):
            raise KernelError(
                "NARRATIVE_EVALUATION_CANDIDATE_NOT_READY",
                "Narrative Evaluation requires a structurally valid immutable candidate",
            )
        self._probe(execution_probe)
        evaluated = self.semantic_evaluation.execute(
            NarrativeSemanticEvaluationCommand(
                project_id=command.project_id,
                workspace_id=command.workspace_id,
                book_id=command.book_id,
                actor_id=command.actor_id,
                candidate_asset_version_id=command.candidate_asset_version_id,
                generation_operation_id=command.generation_operation_id,
                generator_operation_name=command.generator_operation_name,
                candidate_content_hash=command.candidate_content_hash,
                evaluator_execution_class=command.evaluator_execution_class,
                evaluation=(
                    None if command.evaluation is None else dict(command.evaluation)
                ),
                evidence_asset_version_ids=command.evidence_asset_version_ids,
                routing_bootstrap_authorization_id=command.routing_bootstrap_authorization_id,
                reference_evaluation=command.reference_evaluation,
                reference_predecessor_operation_id=command.reference_predecessor_operation_id,
                author_supervised_review=supervised_state(state),
                idempotency_key=command.idempotency_key,
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
            ),
            principal=principal,
            caller_permission="story_planning.authority.execute",
        )
        self._probe(execution_probe)
        if command.routing_bootstrap_authorization_id or supervised_state(state):
            return evaluated
        generation_command = self._generation_command(command.generation_operation_id)
        if evaluated.qualification.status != "PASS":
            return self._repair_or_reject(
                operation_id=command.generation_operation_id,
                candidate_asset_version_id=command.candidate_asset_version_id,
                candidate_content_hash=command.candidate_content_hash,
                command=generation_command,
                principal=transition_principal,
                definition=GENERATOR_CATALOG[command.generator_operation_name],
                error=KernelError(
                    "NARRATIVE_SEMANTIC_QUALIFICATION_FAILED",
                    "independent Narrative Evaluation did not pass",
                ),
            )
        return self._advance_candidate(
            operation_id=command.generation_operation_id,
            candidate_asset_version_id=command.candidate_asset_version_id,
            candidate_content_hash=command.candidate_content_hash,
            command=generation_command,
            principal=transition_principal,
            replayed=evaluated.replayed,
            definition=GENERATOR_CATALOG[command.generator_operation_name],
        )

    def _evaluate_pending_if_required(
        self,
        *,
        advanced: PlanningGenerationResult,
        generation_command: StoryPlanningGenerationCommand,
        principal: Principal,
        execution_probe: Callable[[], object] | None = None,
    ) -> PlanningGenerationResult:
        if advanced.status is not PlanningGenerationStatus.EVALUATION_PENDING:
            return advanced
        if generation_command.routing_bootstrap_authorization_id:
            return advanced
        candidate = self._require_asset(
            project_id=generation_command.project_id,
            asset_version_id=advanced.candidate_asset_version_id,
        )
        execution = dict(candidate["content"].get("execution_evidence") or {})
        fixture = bool(execution.get("fixture_protocol_only"))
        evaluator_principal = (
            principal if fixture else self.narrative_evaluator_principal
        )
        if evaluator_principal is None:
            raise KernelError(
                "NARRATIVE_EVALUATION_PRINCIPAL_REQUIRED",
                "production Planning evaluation has no independent trusted Principal",
            )
        self._probe(execution_probe)
        return self.evaluate_candidate(
            StoryPlanningEvaluationCommand(
                project_id=generation_command.project_id,
                workspace_id=generation_command.workspace_id,
                book_id=generation_command.book_id,
                actor_id=evaluator_principal.principal_id,
                candidate_asset_version_id=advanced.candidate_asset_version_id,
                generation_operation_id=advanced.generation_operation_id,
                generator_operation_name=generation_command.generator_operation_name,
                candidate_content_hash=str(candidate["content_hash"]),
                evaluator_execution_class=(
                    "SCRIPTED_FIXTURE" if fixture else "MODEL_PROVIDER"
                ),
                evaluation=(
                    scripted_qualification(
                        generation_command.generator_operation_name,
                        **qualification_profile_options(candidate["content"]),
                    )
                    if fixture
                    else None
                ),
                idempotency_key=(
                    f"{generation_command.idempotency_key}:semantic-evaluation"
                ),
                trace_id=generation_command.trace_id,
                correlation_id=generation_command.correlation_id,
            ),
            principal=evaluator_principal,
            transition_principal=principal,
            execution_probe=execution_probe,
        )

    @staticmethod
    def _probe(execution_probe: Callable[[], object] | None) -> None:
        if execution_probe is not None:
            execution_probe()

    def reject_candidate(
        self, candidate_asset_version_id: str, *, principal: Principal,
        idempotency_key: str, reason: str, decision: str,
    ) -> dict[str, Any]:
        generation = self.require_candidate(candidate_asset_version_id)
        principal.require("story_design.authority.execute", generation["project_id"])
        state = self.story_design.require(project_id=generation["project_id"], asset_version_id=candidate_asset_version_id)
        expected_version = int(state["version"])
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute("""SELECT command_payload #>> '{payload,expected_version}'
                FROM authority_operation WHERE project_id=%s
                  AND idempotency_scope='project:story-design-transition' AND idempotency_key=%s""",
                [generation["project_id"], idempotency_key])
            original = uow.cursor.fetchone()
        if original is not None:
            expected_version = int(original[0])
        return self.story_design.transition(StoryDesignTransitionCommand(
            project_id=generation["project_id"], workspace_id=generation["workspace_id"],
            actor_id=principal.principal_id, trace_id=idempotency_key, correlation_id=idempotency_key,
            idempotency_key=idempotency_key, asset_version_id=candidate_asset_version_id,
            content_hash=generation["content_hash"], logical_key=generation["logical_key"],
            generator_operation_name=generation["generator_operation_name"], planning_scope=generation["planning_scope"],
            transition=DesignTransition.REJECT, expected_version=expected_version,
            evidence={"author_decision": decision, "reason": reason}), principal=principal)

    def approve_candidate(
        self,
        candidate_asset_version_id: str,
        *,
        principal: Principal,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
        decision_evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        generation = self.require_candidate(candidate_asset_version_id)
        principal.require("story_planning.authority.approve", generation["project_id"])
        if generation.get("routing_eligibility") == "BENCHMARK_ONLY":
            raise KernelError(
                "PLANNING_BENCHMARK_ONLY",
                "bootstrap candidates cannot be approved for production",
            )
        if _requires_formation_decision_evidence(str(generation["logical_key"])):
            require_worker_scoped_auto_decision(
                principal=principal,
                evidence=decision_evidence,
                project_id=generation["project_id"],
                workspace_id=generation["workspace_id"],
                book_id=generation["book_id"],
                action="story_planning.candidate.approve",
                candidate_asset_version_id=candidate_asset_version_id,
                candidate_content_hash=generation["content_hash"],
            )
        state = self.story_design.require(
            project_id=generation["project_id"],
            asset_version_id=candidate_asset_version_id,
        )
        from novel_forge.modules.story_design_authority.author_supervision import supervised_state
        if supervised_state(state):
            review = (decision_evidence or {}).get("author_review")
            for transition, should_apply in (
                (DesignTransition.SEMANTIC_VALIDATE, state["qualification"] == "STRUCTURALLY_VALID"),
                (DesignTransition.SUBMIT_APPROVAL, state["approval"] == "NOT_REQUESTED"),
            ):
                if should_apply:
                    state = self.story_design.transition(StoryDesignTransitionCommand(
                        project_id=generation["project_id"], workspace_id=generation["workspace_id"],
                        actor_id=principal.principal_id, trace_id=trace_id, correlation_id=correlation_id,
                        idempotency_key=idempotency_key + ":" + transition.value,
                        asset_version_id=candidate_asset_version_id, content_hash=generation["content_hash"],
                        logical_key=generation["logical_key"], generator_operation_name=generation["generator_operation_name"],
                        transition=transition, planning_scope=generation["planning_scope"], expected_version=int(state["version"]),
                        evidence={"passed": True, "author_review": review}), principal=principal)
        if state["approval"] == "APPROVED":
            if supervised_state(state):
                from novel_forge.modules.story_design_authority.author_supervision import approved_design_receipt
                with AuthorityUnitOfWork(self.database_url) as uow:
                    receipt = approved_design_receipt(uow.cursor, project_id=generation["project_id"],
                        book_id=generation["book_id"], asset_version_id=candidate_asset_version_id)
                if receipt is None or receipt["author_review"] != (decision_evidence or {}).get("author_review"):
                    raise KernelError("AUTHOR_SUPERVISION_EXACT_REVIEW_REQUIRED", "Recover the original author judgment before changing it")
            return state
        if state["approval"] != "PENDING":
            raise KernelError(
                "PLANNING_CANDIDATE_NOT_APPROVABLE",
                "Planning candidate is not waiting for approval",
            )
        approved = self.story_design.transition(
            StoryDesignTransitionCommand(
                project_id=generation["project_id"],
                workspace_id=generation["workspace_id"],
                actor_id=principal.principal_id,
                trace_id=trace_id,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                asset_version_id=candidate_asset_version_id,
                content_hash=generation["content_hash"],
                logical_key=generation["logical_key"],
                generator_operation_name=generation["generator_operation_name"],
                transition=DesignTransition.APPROVE,
                planning_scope=generation["planning_scope"],
                expected_version=int(state["version"]),
                evidence={
                    "approval_policy_key": generation["approval_policy_key"],
                    "approved_by": principal.principal_id,
                    **({"author_review": decision_evidence["author_review"]} if supervised_state(state) and decision_evidence else {}),
                    **(
                        {"formation_auto_decision": dict(decision_evidence)}
                        if decision_evidence
                        else {}
                    ),
                },
            ),
            principal=principal,
        )
        from novel_forge.modules.story_design_authority.creative_validation import validation_state
        if supervised_state(approved) or validation_state(approved):
            self._set_candidate_eligibility(project_id=generation["project_id"],
                candidate_asset_version_id=candidate_asset_version_id, eligibility="ELIGIBLE")
        self._update_generation_status(
            generation["generation_operation_id"], "APPROVED"
        )
        return approved

    def activate_candidate(
        self,
        candidate_asset_version_id: str,
        *,
        principal: Principal,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
        expected_active_asset_version_id: str = "",
        replacement_approved: bool = False,
        decision_evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        generation = self.require_candidate(candidate_asset_version_id)
        principal.require("story_planning.authority.activate", generation["project_id"])
        if generation.get("routing_eligibility") == "BENCHMARK_ONLY":
            raise KernelError(
                "PLANNING_BENCHMARK_ONLY",
                "bootstrap candidates cannot become active production plans",
            )
        if _requires_formation_decision_evidence(str(generation["logical_key"])):
            require_worker_scoped_auto_decision(
                principal=principal,
                evidence=decision_evidence,
                project_id=generation["project_id"],
                workspace_id=generation["workspace_id"],
                book_id=generation["book_id"],
                action="story_planning.candidate.activate",
                candidate_asset_version_id=candidate_asset_version_id,
                candidate_content_hash=generation["content_hash"],
            )
        generation_record = self.require_generation(
            generation["generation_operation_id"]
        )
        generation_command = self._generation_command(
            generation["generation_operation_id"]
        )
        if generation_command.generator_operation_name == "chapter_plan.generate":
            self._require_frozen_realization_slice(generation_command)
        if (
            generation_command.generator_operation_name == "book_plan.generate"
            and getattr(generation_command, "narrative_search_id", "")
        ):
            candidate_content = self._require_asset(
                project_id=generation["project_id"],
                asset_version_id=candidate_asset_version_id,
            )["content"]
            _validate_narrative_search_horizon(
                generation_command,
                dict(candidate_content),
            )
        narrative_search_id = str(generation_record.get("narrative_search_id") or "")
        if narrative_search_id:
            self._require_selected_search_candidate(
                search_id=narrative_search_id,
                candidate_asset_version_id=candidate_asset_version_id,
                generation_operation_id=generation["generation_operation_id"],
            )
        if str(generation_record["status"]) != "ACTIVE":
            self._require_generation_inputs_current(
                operation_id=generation["generation_operation_id"],
                project_id=generation["project_id"],
                book_id=generation["book_id"],
            )
        from novel_forge.modules.story_design_authority.author_supervision import supervised_state
        current = self.story_design.require(project_id=generation["project_id"], asset_version_id=candidate_asset_version_id)
        from novel_forge.modules.story_design_authority.creative_validation import validation_state
        if not supervised_state(current) and not validation_state(current):
            self._require_narrative_qualification_summary(
                operation_id=generation["generation_operation_id"], candidate_asset_version_id=candidate_asset_version_id,
                project_id=generation["project_id"], book_id=generation["book_id"],
                generator_operation_name=generation["generator_operation_name"])
        state = self.story_design.require(
            project_id=generation["project_id"],
            asset_version_id=candidate_asset_version_id,
        )
        story_design_transition_operation_id = ""
        if state["lifecycle"] == "ACTIVE":
            story_design_transition_operation_id = str(state["updated_by_operation_id"])
        else:
            if state["approval"] != "APPROVED":
                raise KernelError(
                    "PLANNING_CANDIDATE_APPROVAL_REQUIRED",
                    "Planning candidate activation requires an approval decision",
                )
            prepared = self.story_design.prepare_transition(
                StoryDesignTransitionCommand(
                    project_id=generation["project_id"],
                    workspace_id=generation["workspace_id"],
                    actor_id=principal.principal_id,
                    trace_id=trace_id,
                    correlation_id=correlation_id,
                    idempotency_key=f"{idempotency_key}:story-design",
                    asset_version_id=candidate_asset_version_id,
                    content_hash=generation["content_hash"],
                    logical_key=generation["logical_key"],
                    generator_operation_name=generation["generator_operation_name"],
                    transition=DesignTransition.ACTIVATE,
                    planning_scope=generation["planning_scope"],
                    expected_version=int(state["version"]),
                    evidence={
                        "activation_policy_key": generation["activation_policy_key"],
                        **({"author_review": decision_evidence["author_review"]} if supervised_state(state) and decision_evidence and "author_review" in decision_evidence else {}),
                        **(
                            {"formation_auto_decision": dict(decision_evidence)}
                            if decision_evidence
                            else {}
                        ),
                    },
                ),
                principal=principal,
            )
            story_design_transition_operation_id = str(prepared["operation_id"])
        if generation["generator_operation_name"] in FOUNDATION_GENERATORS:
            if state["lifecycle"] != "ACTIVE":
                state = self.story_design.transition(
                    StoryDesignTransitionCommand(
                        project_id=generation["project_id"], workspace_id=generation["workspace_id"],
                        actor_id=principal.principal_id, trace_id=trace_id, correlation_id=correlation_id,
                        idempotency_key=f"{idempotency_key}:story-design",
                        asset_version_id=candidate_asset_version_id, content_hash=generation["content_hash"],
                        logical_key=generation["logical_key"], generator_operation_name=generation["generator_operation_name"],
                        transition=DesignTransition.ACTIVATE, planning_scope=generation["planning_scope"],
                        expected_version=int(state["version"]), evidence={
                            "activation_policy_key": generation["activation_policy_key"],
                        **({"author_review": decision_evidence["author_review"]} if supervised_state(state) and decision_evidence and "author_review" in decision_evidence else {}),
                            **(
                                {"formation_auto_decision": dict(decision_evidence)}
                                if decision_evidence
                                else {}
                            ),
                        },
                    ), principal=principal,
                )
            binding = None
        else:
            binding = self.planning.bind_active_contract(
                project_id=generation["project_id"],
                workspace_id=generation["workspace_id"],
                book_id=generation["book_id"],
                actor_id=principal.principal_id,
                asset_version_id=candidate_asset_version_id,
                contract_type=PlanContractType(generation["planning_scope"].value),
                parent_version_id=generation["parent_version_id"],
                execution_scope=PlanExecutionScope.PLANNED,
                expected_active_asset_version_id=expected_active_asset_version_id,
                replacement_approved=replacement_approved,
                decision_evidence=dict(decision_evidence or {}),
                idempotency_key=f"{idempotency_key}:planning-binding",
                trace_id=trace_id,
                correlation_id=correlation_id,
                causation_operation_id=generation["generation_operation_id"],
                story_design_transition_operation_id=(story_design_transition_operation_id),
                principal=principal,
            )
        state = self.story_design.require(
            project_id=generation["project_id"],
            asset_version_id=candidate_asset_version_id,
        )
        chapter_plan_projection = None
        if generation["planning_scope"].value == PlanContractType.CHAPTER.value:
            chapter_plan_projection = self._materialize_chapter_plan_projection(
                generation=generation,
                candidate_asset_version_id=candidate_asset_version_id,
                principal=principal,
                idempotency_key=f"{idempotency_key}:chapter-plan-projection",
                trace_id=trace_id,
                correlation_id=correlation_id,
            )
        self._update_generation_status(generation["generation_operation_id"], "ACTIVE")
        if narrative_search_id:
            self._record_search_activation(
                search_id=narrative_search_id,
                candidate_asset_version_id=candidate_asset_version_id,
            )
        return {
            "story_design": state,
            "planning_binding": binding,
            "chapter_plan_projection": chapter_plan_projection,
        }

    def _require_selected_search_candidate(
        self,
        *,
        search_id: str,
        candidate_asset_version_id: str,
        generation_operation_id: str,
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT search.status, search.selected_candidate_asset_version_id,
                       member.status, decision.selected_candidate_asset_version_id,
                       member.generation_operation_id, search.book_run_id,
                       search.project_id, search.book_id,
                       search.accepted_through_chapter,
                       search.parent_state_asset_version_id,
                       production.project_id, production.book_id,
                       production.accepted_through_chapter,
                       production.active_story_state_version_id
                FROM authority_story_narrative_search AS search
                JOIN authority_story_narrative_search_candidate AS member
                  ON member.search_id=search.search_id
                 AND member.candidate_asset_version_id=%s
                JOIN authority_story_narrative_search_decision AS decision
                  ON decision.search_id=search.search_id
                LEFT JOIN authority_book_production AS production
                  ON production.book_run_id=search.book_run_id
                WHERE search.search_id=%s
                """,
                [candidate_asset_version_id, search_id],
            )
            row = uow.cursor.fetchone()
        if (
            row is None
            or str(row[0]) not in {"SELECTED", "ACTIVATED"}
            or str(row[1]) != candidate_asset_version_id
            or str(row[2]) != "SELECTED"
            or str(row[3]) != candidate_asset_version_id
            or str(row[4]) != generation_operation_id
            or (
                int(row[8]) > 0
                and (
                    not str(row[5] or "")
                    or str(row[6]) != str(row[10] or "")
                    or str(row[7]) != str(row[11] or "")
                    or int(row[8]) != int(row[12] or -1)
                    or str(row[9] or "") != str(row[13] or "")
                )
            )
        ):
            raise KernelError(
                "NARRATIVE_SEARCH_SELECTION_REQUIRED",
                "a search candidate cannot activate without its exact immutable comparison decision",
            )

    def _record_search_activation(
        self, *, search_id: str, candidate_asset_version_id: str
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                UPDATE authority_story_narrative_search
                SET status='ACTIVATED', version=version+1, updated_at=NOW()
                WHERE search_id=%s
                  AND selected_candidate_asset_version_id=%s
                  AND status='SELECTED'
                """,
                [search_id, candidate_asset_version_id],
            )
            uow.commit()

    def _require_generation_inputs_current(
        self, *, operation_id: str, project_id: str, book_id: str
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT input_snapshot
                FROM authority_story_planning_generation
                WHERE operation_id=%s AND project_id=%s AND book_id=%s
                """,
                [operation_id, project_id, book_id],
            )
            row = uow.cursor.fetchone()
            if row is None:
                raise KernelError(
                    "PLANNING_GENERATION_INPUT_SNAPSHOT_MISSING",
                    "Planning activation requires its immutable generation inputs",
                )
            for item in row[0]:
                frozen = dict(item)
                asset_version_id = str(frozen.get("asset_version_id") or "")
                uow.cursor.execute(
                    """
                    SELECT asset.asset_type, version.content_hash,
                           version.lifecycle, version.eligibility,
                           version.governance, binding.freshness,
                           active.binding_id
                    FROM authority_asset_version AS version
                    JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                    LEFT JOIN story_plan_binding AS binding
                      ON binding.project_id=asset.project_id
                     AND binding.book_id=%s
                     AND binding.asset_version_id=version.asset_version_id
                    LEFT JOIN active_story_plan_version AS active
                      ON active.binding_id=binding.binding_id
                    WHERE version.asset_version_id=%s AND asset.project_id=%s
                    """,
                    [book_id, asset_version_id, project_id],
                )
                current = uow.cursor.fetchone()
                if (
                    current is None
                    or str(current[0]) != str(frozen.get("asset_type") or "")
                    or str(current[1]) != str(frozen.get("content_hash") or "")
                    or str(current[2]) != "ACTIVE"
                    or str(current[3]) != "ELIGIBLE"
                    or str(current[4]) != "CLEAR"
                    or (
                        current[5] is not None
                        and (str(current[5]) != "CURRENT" or current[6] is None)
                    )
                ):
                    raise KernelError(
                        "PLANNING_GENERATION_INPUT_STALE",
                        "Planning candidate input identity or currentness changed before activation",
                    )

    def _require_frozen_realization_slice(
        self, command: StoryPlanningGenerationCommand
    ) -> dict[str, Any]:
        """SECURITY: Resolve Chapter elaboration identity from Planning Authority itself.

        Caller-supplied mappings are only transport.  Generation, retry, and
        activation all compare them with the current Frozen contract so a
        shaped or stale mapping cannot materialize a ChapterPlan.
        """
        supplied = dict(command.narrative_realization or {})
        if command.generator_operation_name != "chapter_plan.generate" or not supplied:
            raise KernelError(
                "NARRATIVE_REALIZATION_REQUIRED",
                "ChapterPlan generation requires a Frozen Narrative Realization slice",
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            current = NarrativeRealizationRepository(
                uow.cursor
            ).require_current_for_chapter(
                project_id=command.project_id,
                book_id=command.book_id,
                chapter_group_plan_version_id=str(
                    supplied.get("chapter_group_plan_version_id") or ""
                ),
                chapter_number=int(supplied.get("chapter_number") or 0),
                coordinated_contract=command.execution_contract_version == "1.21.0",
            )
        if current != supplied:
            raise KernelError(
                "NARRATIVE_REALIZATION_SLICE_DRIFT",
                "ChapterPlan generation input differs from the current Frozen Narrative Realization",
            )
        return current

    def _materialize_chapter_plan_projection(
        self,
        *,
        generation: dict[str, Any],
        candidate_asset_version_id: str,
        principal: Principal,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:

        candidate = self._require_asset(
            project_id=generation["project_id"], asset_version_id=candidate_asset_version_id,
        )
        from novel_forge.modules.story_design_authority.qualification import uses_work_requirements
        projection_version = "3.0.0" if candidate["content"].get("chapter_contract_schema_version") == "chapter-mission-scene.v4" else "2.0.0" if (uses_work_requirements(candidate["content"]) and candidate["content"].get("chapter_contract_schema_version") == "chapter-mission-scene.v3") else "1.0.0"
        definition = chapter_plan_projection_definition(
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha, definition_version=projection_version,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.definitions.register(definition)
            uow.commit()
        generation_command = self._generation_command(
            generation["generation_operation_id"]
        )

        def materialize(
            uow: AuthorityUnitOfWork,
            operation_id: str,
            checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            existing = self._lock_chapter_projection_source(
                uow,
                generation=generation,
                candidate_asset_version_id=candidate_asset_version_id,
                content_hash=candidate["content_hash"],
            )
            if existing is not None:
                raise _ChapterProjectionAlreadyMaterialized(existing)
            self._require_frozen_realization_slice(generation_command)
            binding = (candidate["content"].get("constraint_envelope") or {}).get(
                "world_preparation"
            )
            if binding:
                from novel_forge.storage.world_preparation_repositories import (
                    WorldPreparationRepository,
                )

                WorldPreparationRepository(uow.cursor).validate_binding(
                    project_id=generation["project_id"],
                    book_id=generation["book_id"],
                    binding=binding,
                )
                if (
                    binding["action"].get("contract_version")
                    == "world-production-action.v2"
                ):
                    from novel_forge.modules.canon_graph.background import (
                        bind_world_execution,
                    )

                    expected = bind_world_execution(
                        binding, candidate["content"].get("scene_plan", [])
                    )
                    if (
                        candidate["content"]["constraint_envelope"].get(
                            "world_execution"
                        )
                        != expected
                    ):
                        raise KernelError(
                            "WORLD_SCENE_EXECUTION_DRIFT",
                            "active Chapter plan must preserve the frozen public Scene assignments",
                        )
            checkpoint("after_domain_validation")
            content = {
                **_chapter_runtime_projection(dict(candidate["content"]), projection_version=projection_version),
                "source_planning_candidate_asset_version_id": (
                    candidate_asset_version_id
                ),
                "source_planning_generation_operation_id": generation[
                    "generation_operation_id"
                ],
                "planning_activation": "ACTIVE",
                "physical_contract_type": "chapter_plan",
            }
            document = uow.repositories.asset_documents.materialize_output(
                AuthorityAssetWriteCommand(
                    operation_id=operation_id,
                    project_id=generation["project_id"],
                    asset_id=f"chapter-plan:{candidate_asset_version_id}",
                    asset_type="chapter_plan",
                    schema_version="activated-chapter-plan.v3" if projection_version == "3.0.0" else "activated-chapter-plan.v2" if projection_version == "2.0.0" else "activated-chapter-plan.v1",
                    logical_ref=(
                        "story_planning/chapter_plans/"
                        f"{candidate_asset_version_id}.json"
                    ),
                    category="planning",
                    output_key="story_planning.chapter_plan_projection",
                    role="primary",
                    content=content,
                    qualification_policy="activated-planning-chapter-contract-v1",
                    trace_id=trace_id,
                    correlation_id=correlation_id,
                    reference_asset_ids=(str(candidate["asset_id"]),),
                )
            )
            checkpoint("after_business_projection_update")
            uow.repositories.operation_graph.record_event(
                {
                    "event_id": str(uuid4()),
                    "audit_id": str(uuid4()),
                    "outbox_id": str(uuid4()),
                    "aggregate_type": "chapter_plan",
                    "aggregate_id": document.asset_version_id,
                    "operation_id": operation_id,
                    "project_id": generation["project_id"],
                    "event_type": "story_planning.chapter_plan.materialized",
                    "correlation_id": correlation_id,
                    "causation_id": generation["generation_operation_id"],
                    "payload": {
                        "operation_id": operation_id,
                        "asset_version_id": document.asset_version_id,
                        "source_planning_candidate_asset_version_id": (
                            candidate_asset_version_id
                        ),
                    },
                }
            )
            checkpoint("after_outbox_insert")
            return {
                "asset_version_id": document.asset_version_id,
                "content_hash": document.content_hash,
                "source_planning_candidate_asset_version_id": (
                    candidate_asset_version_id
                ),
            }

        try:
            return dict(
                execute_transaction_command(
                    self.database_url,
                    {
                        "definition_name": CHAPTER_PLAN_PROJECTION_DEFINITION,
                        "definition_version": projection_version,
                        "project_id": generation["project_id"],
                        "workspace_id": generation["workspace_id"],
                        "book_id": generation["book_id"],
                        "actor_id": principal.principal_id,
                        "idempotency_scope": "book:activated-chapter-plan",
                        "idempotency_key": idempotency_key,
                        "trace_id": trace_id,
                        "span_id": str(uuid4()),
                        "correlation_id": correlation_id,
                        "causation_id": generation["generation_operation_id"],
                        "causation_operation_id": generation["generation_operation_id"],
                        "input": {
                            "project_id": generation["project_id"],
                            "candidate_asset_version_id": candidate_asset_version_id,
                        },
                        "input_assets": [
                            {
                                "asset_version_id": candidate_asset_version_id,
                                "content_hash": candidate["content_hash"],
                            }
                        ],
                    },
                    context=AdmissionContext(
                        actor_id=principal.principal_id,
                        permissions=frozenset({"story_planning.authority.activate"}),
                        available_handlers=frozenset({CHAPTER_PLAN_PROJECTION_HANDLER}),
                        application_build_id=self.application_build_id,
                        commit_sha=self.commit_sha,
                    ),
                    handler=materialize,
                )
            )
        except _ChapterProjectionAlreadyMaterialized as existing:
            return existing.result

    @staticmethod
    def _lock_chapter_projection_source(
        uow: AuthorityUnitOfWork,
        *,
        generation: dict[str, Any],
        candidate_asset_version_id: str,
        content_hash: str,
    ) -> dict[str, Any] | None:
        uow.cursor.execute(
            "SELECT book_id FROM authority_book WHERE project_id=%s AND book_id=%s FOR UPDATE",
            [generation["project_id"], generation["book_id"]],
        )
        if uow.cursor.fetchone() is None:
            raise KernelError("BOOK_NOT_FOUND", "Chapter projection requires its exact Book owner")
        uow.cursor.execute(
            """
            SELECT version.content_hash, version.lifecycle, version.eligibility,
                   version.governance, state.lifecycle,
                   EXISTS (
                       SELECT 1 FROM authority_story_design_active_version AS active
                       WHERE active.project_id=state.project_id
                         AND active.logical_key=state.logical_key
                         AND active.asset_version_id=state.asset_version_id
                   )
            FROM authority_asset_version AS version
            JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
            JOIN authority_story_design_version_state AS state
              ON state.project_id=asset.project_id
             AND state.asset_version_id=version.asset_version_id
            WHERE asset.project_id=%s AND version.asset_version_id=%s
            FOR UPDATE OF state, version
            """,
            [generation["project_id"], candidate_asset_version_id],
        )
        row = uow.cursor.fetchone()
        if row is None or tuple(row) != (content_hash, "ACTIVE", "ELIGIBLE", "CLEAR", "ACTIVE", True):
            raise KernelError(
                "PLANNING_CHAPTER_PROJECTION_ACTIVATION_REQUIRED",
                "Chapter projection requires the exact current eligible Active candidate",
            )
        uow.cursor.execute(
            """
            SELECT projection.asset_version_id, projection.content_hash,
                   projection.lifecycle, projection.eligibility, projection.governance,
                   operation.status, operation.project_id,
                   projection.content->>'source_planning_generation_operation_id',
                   operation.operation_id
            FROM authority_operation_output_asset AS output
            JOIN authority_operation AS operation ON operation.operation_id=output.operation_id
            JOIN authority_asset_version AS projection
              ON projection.asset_version_id=output.asset_version_id
            WHERE output.output_key='story_planning.chapter_plan_projection'
              AND projection.content->>'source_planning_candidate_asset_version_id'=%s
            ORDER BY projection.created_at
            FOR UPDATE OF projection
            """,
            [candidate_asset_version_id],
        )
        rows = tuple(uow.cursor.fetchall())
        if not rows:
            return None
        if len(rows) != 1 or tuple(rows[0][2:8]) != (
            "ACTIVE", "ELIGIBLE", "CLEAR", "SUCCEEDED", generation["project_id"],
            generation["generation_operation_id"],
        ):
            raise KernelError(
                "BOOK_SUPERVISOR_CHAPTER_PLAN_PROJECTION_INVALID",
                "Existing Chapter projection history cannot be replaced or reactivated",
            )
        return {
            "operation_id": str(rows[0][8]),
            "status": "SUCCEEDED",
            "asset_version_id": str(rows[0][0]),
            "content_hash": str(rows[0][1]),
            "source_planning_candidate_asset_version_id": candidate_asset_version_id,
            "replayed": True,
        }

    def materialize_activated_chapter_plan_projection(
        self,
        candidate_asset_version_id: str,
        *,
        principal: Principal,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:

        generation = self.require_candidate(candidate_asset_version_id)
        principal.require("story_planning.authority.activate", generation["project_id"])
        if generation["planning_scope"].value != PlanContractType.CHAPTER.value:
            raise KernelError(
                "PLANNING_CHAPTER_PROJECTION_SCOPE_INVALID",
                "typed ChapterPlan projection requires a Chapter candidate",
            )
        state = self.story_design.require(
            project_id=generation["project_id"],
            asset_version_id=candidate_asset_version_id,
        )
        if state["lifecycle"] != "ACTIVE":
            raise KernelError(
                "PLANNING_CHAPTER_PROJECTION_ACTIVATION_REQUIRED",
                "typed ChapterPlan projection requires an Active candidate",
            )
        self._require_frozen_realization_slice(
            self._generation_command(generation["generation_operation_id"])
        )
        projection = self._materialize_chapter_plan_projection(
            generation=generation,
            candidate_asset_version_id=candidate_asset_version_id,
            principal=principal,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            correlation_id=correlation_id,
        )
        self._update_generation_status(generation["generation_operation_id"], "ACTIVE")
        return projection

    def _terminal_generation_replay(
        self, command: StoryPlanningGenerationCommand, *, principal: Principal,
        execution_probe: Callable[[], object] | None = None,
    ) -> PlanningGenerationResult | None:
        self._probe(execution_probe)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                "SELECT op.operation_id, op.command_payload->'payload', op.status, g.status, g.candidate_asset_version_id FROM authority_operation op LEFT JOIN authority_story_planning_generation g USING(operation_id) WHERE op.project_id=%s AND op.definition_name=%s AND op.idempotency_scope='book:story-planning-generation' AND op.idempotency_key=%s",
                [
                    command.project_id,
                    STORY_PLANNING_GENERATION_DEFINITION,
                    command.idempotency_key,
                ],
            )
            row = uow.cursor.fetchone()
        if row is None:
            if command.execution_contract_version != STORY_PLANNING_GENERATION_VERSION and not (
                command.runtime_continuation_id or command.repair_of_operation_id or command.repair_of_candidate_id
            ):
                raise KernelError(
                    "PLANNING_HISTORICAL_CONTRACT_REPLAY_ONLY",
                    "historical Planning definitions may only resume their already admitted commands",
                )
            return None
        frozen_payload = dict(row[1])
        public_frozen_payload = {
            key: value for key, value in frozen_payload.items()
            if key != "routing_bootstrap_authorization"
        }
        if row[2] in {"CANCELLED","FAILED_FINAL"} and not row[4]:
            from .runtime_continuation import follow
            current_payload = _command_payload(command)
            if {key: value for key, value in public_frozen_payload.items() if key != "execution_contract_version"} == {key: value for key, value in current_payload.items() if key != "execution_contract_version"}:
                resumed = follow(self, str(row[0]), _command_from_payload(frozen_payload), principal=principal, execution_probe=execution_probe)
                if resumed is not None:
                    return resumed
        if public_frozen_payload != _command_payload(command):
            raise KernelError(
                "PLANNING_GENERATION_COMMAND_IDENTITY_DRIFT",
                "replay must use the exact immutable admitted Planning command",
            )
        if row[2] in {'FAILED_FINAL', 'DEAD_LETTER'} and not row[4] and command.world_preparation_request:
            from .world_optional import follow_optional_failure
            deferred = follow_optional_failure(self, command=command, operation_id=str(row[0]), principal=principal, execution_probe=execution_probe)
            if deferred is not None:
                return deferred
        if row[2] == "CANCELLED" and not row[4]:
            from .runtime_continuation import follow
            return follow(self, str(row[0]), command, principal=principal, execution_probe=execution_probe)
        if row[2] in {"FAILED_RETRYABLE", "FAILED_FINAL", "DEAD_LETTER"} and not row[4]:
            from .runtime_continuation import follow, register

            continued = follow(self, str(row[0]), command, principal=principal, execution_probe=execution_probe)
            if continued is not None:
                return continued
            with AuthorityUnitOfWork(self.database_url) as uow:
                uow.cursor.execute(
                    "SELECT result->>'error_code',result#>>'{failure_details,cause_code}' FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number DESC LIMIT 1",
                    [row[0]],
                )
                failure = uow.cursor.fetchone()
                uow.cursor.execute(
                    "SELECT version FROM authority_operation WHERE operation_id=%s",
                    [row[0]],
                )
                source_version = int(uow.cursor.fetchone()[0])
            if failure and (failure[1] == "PROVIDER_SCHEMA_REJECTED" or failure[0] == "PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED" or (
                    failure[0] == "PROVIDER_ROUTING_BLOCKED"
                    and command.generator_operation_name in {"arc_plan.generate", "chapter_group_plan.generate", "chapter_plan.generate"})):
                if row[2] == 'FAILED_RETRYABLE':
                    with AuthorityUnitOfWork(self.database_url) as uow:
                        uow.cursor.execute('SELECT snapshot_payload->>\'release_sha\' FROM authority_attempt_capability_pack_snapshot WHERE operation_id=%s ORDER BY created_at DESC LIMIT 1', [row[0]])
                        snapshot = uow.cursor.fetchone()
                    if not snapshot or snapshot[0] == self.commit_sha:
                        return None
                self._probe(execution_probe)
                try:
                    register(self, str(row[0]), project_id=command.project_id, principal=principal,
                        expected_source_version=source_version,
                        decision_evidence={"authorization_ref": "NATIVE_CONTINUOUS_CREATION_TEMPLATE",
                            "reason": "Equivalent transport Schema correction with trusted completed stages retained" if failure[1] == "PROVIDER_SCHEMA_REJECTED" else "Pre-send capacity correction after exact frozen failure with verified completed preparation retained"},
                        trace_id=command.trace_id, correlation_id=command.correlation_id)
                except KernelError as error:
                    if error.code != "PLANNING_RUNTIME_CONTINUATION_FAILURE_NOT_ALLOWED":
                        raise
                else:
                    return follow(self, str(row[0]), command, principal=principal, execution_probe=execution_probe)
            if row[2] in {"FAILED_FINAL", "DEAD_LETTER"}:
                from .gateway_result_recovery import recover
                revalidated = recover(self, command=command, operation_id=str(row[0]), principal=principal, execution_probe=execution_probe)
                if revalidated is not None:
                    return self.generate(command, principal=principal, execution_probe=execution_probe)
            if row[2] in {"FAILED_FINAL", "DEAD_LETTER"}:
                return self._repair_unmaterialized_result(
                    command, operation_id=str(row[0]), principal=principal, execution_probe=execution_probe
                )
        if row[4] and row[3] in {"REJECTED", "REPAIR_REQUIRED"}:
            from .stage_repairs import follow_rejected
            stage_successor = follow_rejected(self, command=command, operation_id=str(row[0]), candidate_asset_version_id=str(row[4]), principal=principal, execution_probe=execution_probe)
            if stage_successor is not None:
                return stage_successor
        if row[2] in {"FAILED_FINAL", "DEAD_LETTER"} and row[4]:
            with AuthorityUnitOfWork(self.database_url) as uow:
                uow.cursor.execute("SELECT EXISTS(SELECT 1 FROM authority_planning_result_admission r JOIN authority_operation o ON o.operation_id=r.recovery_operation_id WHERE r.source_operation_id=%s AND r.candidate_asset_version_id=%s AND o.status='SUCCEEDED')", [row[0], row[4]])
                recovered = uow.cursor.fetchone()[0]
            if recovered:
                asset = self._require_asset(project_id=command.project_id, asset_version_id=str(row[4]))
                self._probe(execution_probe)
                return self._advance_candidate(operation_id=str(row[0]), candidate_asset_version_id=str(row[4]), candidate_content_hash=asset["content_hash"], command=command, principal=principal, replayed=True, definition=GENERATOR_CATALOG[command.generator_operation_name])
        if not row[4] or (
            row[2] != "SUCCEEDED"
            and not (row[2] == "WAITING_GATE" and row[3] in {"REPAIR_REQUIRED", "REJECTED"})
        ):
            return None
        state = self.story_design.require(
            project_id=command.project_id, asset_version_id=str(row[4])
        )
        if command.generator_operation_name in FOUNDATION_GENERATORS and state["lifecycle"] == "ACTIVE":
            asset = self._require_asset(project_id=command.project_id, asset_version_id=str(row[4]))
            try:
                require_resolved_foundation_applicability(asset["content"])
            except KernelError as error:
                with AuthorityUnitOfWork(self.database_url) as uow:
                    uow.cursor.execute("SELECT EXISTS(SELECT 1 FROM authority_book_foundation_binding WHERE project_id=%s AND book_id=%s AND asset_version_id=%s)",
                                       [command.project_id, command.book_id, row[4]])
                    committed = uow.cursor.fetchone()[0]
                if committed:
                    raise
                definition = GENERATOR_CATALOG[command.generator_operation_name]
                if command.repair_number >= definition.maximum_structural_regenerations:
                    raise KernelError("PLANNING_REPAIR_BOUND_EXCEEDED", "Unresolved Foundation exhausted its frozen repair allowance") from error
                report_hash = self._record_validation(operation_id=str(row[0]), candidate_asset_version_id=str(row[4]),
                    validation_kind="STRUCTURAL", status="FAIL", report={"status": "FAIL", "validation_kind": "STRUCTURAL",
                        "error_code": error.code, "message": error.message, "candidate_asset_version_id": str(row[4])})
                repaired = replace(command, runtime_continuation_id="", repair_of_candidate_id=str(row[4]),
                    repair_of_operation_id="", repair_result_asset_version_id="", repair_result_diagnostic=None,
                    repair_reason=f"{error.code}:{report_hash}", repair_number=command.repair_number + 1,
                    idempotency_key=f"{command.idempotency_key}:repair:{command.repair_number + 1}")
                return self.generate(repaired, principal=principal, execution_probe=execution_probe)
        if command.routing_bootstrap_authorization_id and row[3] in {
            "EVALUATION_PENDING", "REPAIR_REQUIRED", "REJECTED",
        }:
            return PlanningGenerationResult(
                str(row[0]), str(row[4]), PlanningGenerationStatus(row[3]), state,
                replayed=True,
            )
        if row[3] == "REPAIR_REQUIRED":
            with AuthorityUnitOfWork(self.database_url) as uow:
                uow.cursor.execute(
                    "SELECT report, report_hash FROM authority_story_planning_validation_report WHERE candidate_asset_version_id=%s AND status='FAIL' ORDER BY created_at DESC, validation_report_id DESC LIMIT 1",
                    [row[4]],
                )
                failed = uow.cursor.fetchone()
            if failed:
                if command.execution_contract_version in {
                    "1.12.0",
                    "1.13.0",
                    "1.14.0",
                    "1.15.0",
                    "1.16.0",
                    "1.17.0",
                    "1.18.0",
                    "1.19.0",
            "1.21.0",
                }:
                    definition = GENERATOR_CATALOG[command.generator_operation_name]
                    maximum = (
                        definition.maximum_semantic_repairs
                        if failed[0]["validation_kind"] == "SEMANTIC"
                        else definition.maximum_structural_regenerations
                    )
                    if command.repair_number >= maximum:
                        raise KernelError(
                            "PLANNING_REPAIR_BOUND_EXCEEDED",
                            "a retained repair cannot expand its frozen attempt bound",
                        )
                    repaired = replace(
                        command,
                        runtime_continuation_id="",
                        repair_of_candidate_id=str(row[4]),
                        repair_of_operation_id="",
                        repair_result_asset_version_id="",
                        repair_result_diagnostic=None,
                        repair_reason=f"{failed[0]['error_code']}:{failed[1]}",
                        repair_number=command.repair_number + 1,
                        idempotency_key=f"{command.idempotency_key}:repair:{command.repair_number + 1}",
                    )
                    return self.generate(repaired, principal=principal, execution_probe=execution_probe)
                return PlanningGenerationResult(
                    str(row[0]),
                    str(row[4]),
                    PlanningGenerationStatus.REPAIR_REQUIRED,
                    state,
                    replayed=True,
                )
        if state["lifecycle"] not in {"ACTIVE", "REJECTED"}:
            if row[2] == "SUCCEEDED":
                asset = self._require_asset(project_id=command.project_id, asset_version_id=str(row[4]))
                self._probe(execution_probe)
                return self._advance_candidate(operation_id=str(row[0]), candidate_asset_version_id=str(row[4]),
                    candidate_content_hash=asset["content_hash"], command=command, principal=principal, replayed=True,
                    definition=GENERATOR_CATALOG[command.generator_operation_name])
            return None
        binding = (
            self.planning.require_binding(
                project_id=command.project_id, asset_version_id=str(row[4])
            )
            if state["lifecycle"] == "ACTIVE" and command.generator_operation_name not in FOUNDATION_GENERATORS
            else None
        )
        return PlanningGenerationResult(
            str(row[0]),
            str(row[4]),
            PlanningGenerationStatus(state["lifecycle"]),
            state,
            binding,
            True,
        )

    def _repair_unmaterialized_result(self, command: StoryPlanningGenerationCommand, *, operation_id: str, principal: Principal, execution_probe: Callable[[], object] | None = None) -> PlanningGenerationResult:
        from .result_recovery import MAXIMUM_RESULT_REPAIRS, require_result_repair_source

        if command.routing_bootstrap_authorization_id:
            raise KernelError(
                "PLANNING_BOOTSTRAP_REPAIR_REQUIRES_AUTHORIZATION",
                "invalid bootstrap output is retained; a new challenger requires explicit authorization",
            )
        maximum = min(MAXIMUM_RESULT_REPAIRS, GENERATOR_CATALOG[command.generator_operation_name].maximum_structural_regenerations)
        from .stage_repairs import repair_bound
        bound=repair_bound(self,command=command,operation_id=operation_id,maximum=maximum)
        exhausted=(bound['stage_repair_number']>=bound['maximum_repairs'] or command.repair_number>=4) if bound else command.repair_number>=maximum
        if exhausted:
            raise KernelError("PLANNING_RESULT_REPAIR_BOUND_EXCEEDED", "invalid raw results exhausted their bounded repair allowance; all results remain retained")
        source = require_result_repair_source(self.database_url, command=command, operation_id=operation_id)
        diagnostic = source["diagnostic"]
        repaired = replace(
            command,
            runtime_continuation_id="",
            repair_of_candidate_id="",
            repair_of_operation_id=operation_id,
            repair_result_asset_version_id=source["asset_version_id"],
            repair_result_diagnostic=diagnostic,
            repair_reason=f"{diagnostic['error_code']}:{canonical_hash(diagnostic)}",
            repair_number=command.repair_number + 1,
            parent_agent_session_operation_id="",
            idempotency_key=f"{command.idempotency_key}:result-repair:{command.repair_number + 1}",
        )
        return self.generate(repaired, principal=principal, execution_probe=execution_probe)

    def frozen_generation_command(self, operation_id: str) -> dict[str, Any]:
        return self._frozen_generation_payload(operation_id)

    def register_result_admission_recovery(self, source_operation_id: str, *, project_id: str,
        source_asset_version_id: str, reason: str, principal: Principal) -> dict[str, Any]:
        from .result_admission import recover
        return recover(self, source_operation_id=source_operation_id, project_id=project_id,
            source_asset_version_id=source_asset_version_id, reason=reason, principal=principal)

    def require_generation(self, operation_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT generation_id, operation_id, project_id, workspace_id,
                       book_id, generator_operation_name, planning_scope,
                       logical_key, input_snapshot, input_snapshot_hash,
                       status, candidate_asset_version_id,
                       repair_of_candidate_id, repair_number, version,
                       COALESCE(narrative_search_id, ''),
                       COALESCE(narrative_search_branch_key, ''),
                       COALESCE(to_jsonb(generation)->>'repair_of_operation_id', ''),
                       COALESCE(to_jsonb(generation)->>'repair_result_asset_version_id', '')
                FROM authority_story_planning_generation AS generation
                WHERE operation_id=%s
                """,
                [operation_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "PLANNING_GENERATION_NOT_FOUND", "Planning Generation does not exist"
            )
        fields = (
            "generation_id",
            "operation_id",
            "project_id",
            "workspace_id",
            "book_id",
            "generator_operation_name",
            "planning_scope",
            "logical_key",
            "input_snapshot",
            "input_snapshot_hash",
            "status",
            "candidate_asset_version_id",
            "repair_of_candidate_id",
            "repair_number",
            "version",
            "narrative_search_id",
            "narrative_search_branch_key",
            "repair_of_operation_id",
            "repair_result_asset_version_id",
        )
        return dict(zip(fields, row, strict=True))

    def _generation_command(self, operation_id: str) -> StoryPlanningGenerationCommand:
        return _command_from_payload(self._frozen_generation_payload(operation_id))

    def _frozen_generation_payload(self, operation_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT command_payload->'payload'
                FROM authority_operation
                WHERE operation_id=%s
                  AND definition_name=%s
                """,
                [operation_id, STORY_PLANNING_GENERATION_DEFINITION],
            )
            row = uow.cursor.fetchone()
        if row is None or not isinstance(row[0], dict):
            raise KernelError(
                "PLANNING_GENERATION_COMMAND_MISSING",
                "frozen Planning Generation command is unavailable",
            )
        return dict(row[0])

    def find_frozen_generation_command(
        self,
        *,
        project_id: str,
        idempotency_key: str,
    ) -> StoryPlanningGenerationCommand | None:
        """INVARIANT: Return the immutable command already admitted for one generation key.

        Narrative Search may lose its process after Command admission (or after
        semantic work) but before branch membership is committed.  A successor
        BookOpening execution has a different outer fence, so rebuilding the
        command from that successor would correctly conflict with the existing
        Command Kernel identity.  Resume must instead replay the exact frozen
        command and let the normal generation/evaluation authorities converge.
        """
        if not project_id or not idempotency_key:
            raise ValueError("frozen Planning Generation identity is incomplete")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT command_payload->'payload'
                FROM authority_operation
                WHERE project_id=%s
                  AND definition_name=%s
                  AND idempotency_scope='book:story-planning-generation'
                  AND idempotency_key=%s
                """,
                [
                    project_id,
                    STORY_PLANNING_GENERATION_DEFINITION,
                    idempotency_key,
                ],
            )
            row = uow.cursor.fetchone()
        if row is None:
            return None
        if not isinstance(row[0], dict):
            raise KernelError(
                "PLANNING_GENERATION_COMMAND_MISSING",
                "frozen Planning Generation command is unavailable",
            )
        command = _command_from_payload(dict(row[0]))
        if (
            command.project_id != project_id
            or command.idempotency_key != idempotency_key
        ):
            raise KernelError(
                "PLANNING_GENERATION_COMMAND_IDENTITY_DRIFT",
                "frozen Planning Generation command differs from its Authority identity",
            )
        return command

    def _replay_ordered_input_assets(
        self,
        *,
        command: StoryPlanningGenerationCommand,
        resolved_input_assets: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """COMPATIBILITY: Preserve the admitted snapshot order when replaying an Operation.

        PostgreSQL JSONB does not preserve object-key insertion order.  Rebuilding
        ``input_versions`` from the frozen payload can therefore produce the same
        semantic assets in a different list order, while the Command Kernel
        request digest intentionally covers the admitted list.  The immutable
        Operation snapshot is the replay authority: every identity/hash must
        still match, and only its original ordering is reused.
        """
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT command_payload->'payload', input_asset_snapshot
                FROM authority_operation
                WHERE project_id=%s
                  AND definition_name=%s
                  AND idempotency_scope='book:story-planning-generation'
                  AND idempotency_key=%s
                """,
                [
                    command.project_id,
                    STORY_PLANNING_GENERATION_DEFINITION,
                    command.idempotency_key,
                ],
            )
            row = uow.cursor.fetchone()
        if row is None:
            return resolved_input_assets
        if not isinstance(row[0], dict) or not isinstance(row[1], list):
            raise KernelError(
                "PLANNING_GENERATION_ADMISSION_SNAPSHOT_INVALID",
                "frozen Planning Generation admission snapshot is unavailable",
            )
        if _command_from_payload(dict(row[0])) != command:
            raise KernelError(
                "PLANNING_GENERATION_COMMAND_IDENTITY_DRIFT",
                "replay command differs from the frozen Planning Generation",
            )

        resolved_by_id = {
            str(item.get("asset_version_id") or ""): str(item.get("content_hash") or "")
            for item in resolved_input_assets
        }
        if len(resolved_by_id) != len(resolved_input_assets) or "" in resolved_by_id:
            raise KernelError(
                "PLANNING_GENERATION_ADMISSION_SNAPSHOT_INVALID",
                "resolved Planning Generation inputs are not uniquely identified",
            )
        ordered: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in row[1]:
            if not isinstance(item, dict):
                raise KernelError(
                    "PLANNING_GENERATION_ADMISSION_SNAPSHOT_INVALID",
                    "frozen Planning Generation input evidence is malformed",
                )
            asset_version_id = str(item.get("asset_version_id") or "")
            content_hash = str(item.get("content_hash") or "")
            if (
                not asset_version_id
                or asset_version_id in seen
                or resolved_by_id.get(asset_version_id) != content_hash
                or str(item.get("project_id") or command.project_id)
                != command.project_id
            ):
                raise KernelError(
                    "PLANNING_GENERATION_ADMISSION_SNAPSHOT_DRIFT",
                    "current Planning inputs differ from the frozen admission snapshot",
                )
            seen.add(asset_version_id)
            ordered.append(
                {
                    "asset_version_id": asset_version_id,
                    "content_hash": content_hash,
                }
            )
        if seen != set(resolved_by_id):
            raise KernelError(
                "PLANNING_GENERATION_ADMISSION_SNAPSHOT_DRIFT",
                "current Planning input set differs from the frozen admission snapshot",
            )
        return ordered

    def require_candidate(self, candidate_asset_version_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT generation.operation_id, generation.project_id,
                       generation.workspace_id, generation.book_id,
                       generation.generator_operation_name,
                       generation.planning_scope, generation.logical_key,
                       generation.parent_version_id,
                       design_state.generator_definition_version,
                       candidate.content_hash,
                       definition.definition->>'approval_policy_key',
                       definition.definition->>'activation_policy_key',
                       CASE WHEN candidate_version.content->>'routing_eligibility'='BENCHMARK_ONLY'
                              OR candidate_version.content ? 'routing_bootstrap_authorization'
                            THEN 'BENCHMARK_ONLY' ELSE '' END
                FROM authority_story_planning_candidate AS candidate
                JOIN authority_asset_version AS candidate_version
                  ON candidate_version.asset_version_id=candidate.candidate_asset_version_id
                JOIN authority_story_planning_generation AS generation
                  ON generation.generation_id=candidate.generation_id
                JOIN authority_story_design_version_state AS design_state
                  ON design_state.project_id=generation.project_id
                 AND design_state.asset_version_id=
                     candidate.candidate_asset_version_id
                 AND design_state.logical_key=generation.logical_key
                 AND design_state.generator_operation_name=
                     generation.generator_operation_name
                JOIN authority_story_design_generator_definition AS definition
                  ON definition.operation_name=
                     design_state.generator_operation_name
                 AND definition.definition_version=
                     design_state.generator_definition_version
                WHERE candidate.candidate_asset_version_id=%s
                """,
                [candidate_asset_version_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "PLANNING_CANDIDATE_NOT_FOUND", "Planning candidate does not exist"
            )
        fields = (
            "generation_operation_id",
            "project_id",
            "workspace_id",
            "book_id",
            "generator_operation_name",
            "planning_scope",
            "logical_key",
            "parent_version_id",
            "generator_definition_version",
            "content_hash",
            "approval_policy_key",
            "activation_policy_key",
            "routing_eligibility",
        )
        result = dict(zip(fields, row, strict=True))
        from novel_forge.modules.story_design_authority import PlanningScope

        result["planning_scope"] = PlanningScope(str(result["planning_scope"]))
        result["parent_version_id"] = str(result["parent_version_id"] or "")
        return result

    def _advance_candidate(
        self,
        *,
        operation_id: str,
        candidate_asset_version_id: str,
        candidate_content_hash: str,
        command: StoryPlanningGenerationCommand,
        principal: Principal,
        replayed: bool,
        definition: Any,
    ) -> PlanningGenerationResult:
        if command.generator_operation_name == "chapter_plan.generate":
            self._require_frozen_realization_slice(command)
        try:
            state = self.story_design.require(
                project_id=command.project_id,
                asset_version_id=candidate_asset_version_id,
            )
        except KernelError as exc:
            if exc.code != "STORY_DESIGN_CANDIDATE_NOT_FOUND":
                raise
            state = self._transition(
                command,
                principal,
                candidate_asset_version_id,
                candidate_content_hash,
                DesignTransition.ENROLL,
                expected_version=0,
                evidence=self._candidate_evidence(candidate_asset_version_id),
            )
        if state["lifecycle"] == "ACTIVE":
            try:
                binding = self.planning.require_binding(
                    project_id=command.project_id,
                    asset_version_id=candidate_asset_version_id,
                )
            except KernelError as exc:
                if (
                    exc.code != "PLANNING_BINDING_NOT_FOUND"
                    or definition.risk_class == "HIGH"
                    or not command.auto_approve_low_risk
                ):
                    raise
                recovered = self.activate_candidate(
                    candidate_asset_version_id,
                    principal=principal,
                    idempotency_key=f"{command.idempotency_key}:auto-activate",
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                )
                binding = recovered["planning_binding"]
            self._update_generation_status(operation_id, "ACTIVE")
            return PlanningGenerationResult(
                operation_id,
                candidate_asset_version_id,
                PlanningGenerationStatus.ACTIVE,
                state,
                binding,
                replayed,
            )
        if state["approval"] == "APPROVED":
            if definition.risk_class != "HIGH" and command.auto_approve_low_risk:
                activated = self.activate_candidate(
                    candidate_asset_version_id, principal=principal,
                    idempotency_key=f"{command.idempotency_key}:auto-activate",
                    trace_id=command.trace_id, correlation_id=command.correlation_id,
                )
                return PlanningGenerationResult(operation_id, candidate_asset_version_id, PlanningGenerationStatus.ACTIVE, activated["story_design"], activated["planning_binding"], replayed)
            self._update_generation_status(operation_id, "APPROVED")
            return PlanningGenerationResult(
                operation_id,
                candidate_asset_version_id,
                PlanningGenerationStatus.APPROVED,
                state,
                replayed=replayed,
            )
        if state["lifecycle"] == "REJECTED":
            self._update_generation_status(operation_id, "REJECTED")
            return PlanningGenerationResult(
                operation_id,
                candidate_asset_version_id,
                PlanningGenerationStatus.REJECTED,
                state,
                replayed=replayed,
            )
        if state["lifecycle"] == "CANDIDATE":
            state = self._transition(
                command,
                principal,
                candidate_asset_version_id,
                candidate_content_hash,
                DesignTransition.MATERIALIZE,
                expected_version=int(state["version"]),
                evidence={"generation_operation_id": operation_id},
            )
        if state["lifecycle"] == "MATERIALIZED" and state["qualification"] == "PENDING":
            content = self._require_asset(
                project_id=command.project_id,
                asset_version_id=candidate_asset_version_id,
            )["content"]
            try:
                _validate_narrative_search_horizon(command, content)
                if command.generator_operation_name == "chapter_plan.generate":
                    schedule_source = self._require_asset(
                        project_id=command.project_id,
                        asset_version_id=command.input_versions[
                            "chapter_function_matrix_row"
                        ],
                    )["content"]
                    try:
                        schedule_row = require_chapter_schedule_row(
                            schedule_source,
                            chapter_number=int(
                                (command.narrative_realization or {}).get(
                                    "chapter_number"
                                )
                                or 0
                            ),
                        )
                    except (TypeError, ValueError) as exc:
                        raise KernelError(
                            "CHAPTER_SCHEDULE_BINDING_INVALID",
                            "Frozen Scheduling input does not contain one complete Chapter row",
                        ) from exc
                    _validate_chapter_schedule_binding(content, schedule_row)
                    from novel_forge.modules.hierarchical_planning.epistemic_validation import validate_planned_character_knowledge
                    validate_planned_character_knowledge(content, self._require_asset(project_id=command.project_id, asset_version_id=command.input_versions["story_state"])["content"])
                validation = validate_story_design_candidate(
                    content=content,
                    project_id=command.project_id,
                    generator_operation_name=command.generator_operation_name,
                    planning_scope=command.planning_scope,
                    logical_key=command.logical_key,
                )
                contract = None
                if command.generator_operation_name in FOUNDATION_GENERATORS:
                    validate_foundation_payload(command.generator_operation_name, content)
                    require_resolved_foundation_applicability(content)
                else:
                    contract = validate_planning_contract(
                        project_id=command.project_id,
                        book_id=command.book_id,
                        contract_type=PlanContractType(command.planning_scope.value),
                        asset_version_id=candidate_asset_version_id,
                        parent_version_id=command.parent_version_id,
                        execution_scope=PlanExecutionScope.PLANNED,
                        content=content,
                        require_current_chapter_contract=True,
                    )
                    if command.generator_operation_name == "arc_plan.generate":
                        expected_volume_scope = (
                            command.input_versions["volume_plan"],
                            *command.arc_scope_volume_plan_version_ids,
                        )
                        declared_volume_scope = tuple(
                            str(item) for item in content.get("cross_volume_scope") or ()
                        )
                        if declared_volume_scope != expected_volume_scope:
                            raise KernelError(
                                "NARRATIVE_ARC_AUTHORITY_SCOPE_MISMATCH",
                                "Arc cross_volume_scope must exactly match frozen Active VolumePlan versions",
                            )
                    _validate_frozen_arc_references(command, content)
                    if contract.logical_key != command.logical_key:
                        raise KernelError(
                            "PLANNING_LOGICAL_KEY_MISMATCH",
                            "Planning Candidate content differs from the admitted logical key",
                        )
            except KernelError as exc:
                return self._repair_or_reject(
                    operation_id=operation_id,
                    candidate_asset_version_id=candidate_asset_version_id,
                    candidate_content_hash=candidate_content_hash,
                    command=command,
                    principal=principal,
                    definition=definition,
                    error=exc,
                )
            evidence = {
                **validation.to_evidence(),
                **({"planning_contract": {
                    "contract_type": contract.contract_type.value,
                    "logical_key": contract.logical_key,
                    "parent_version_id": contract.parent_version_id,
                    "execution_scope": contract.execution_scope.value,
                }} if contract is not None else {"foundation_contract": content["constraint_envelope"]}),
            }
            self._record_validation(
                operation_id=operation_id,
                candidate_asset_version_id=candidate_asset_version_id,
                validation_kind="COMBINED",
                status="PASS",
                report=evidence,
            )
            state = self._transition(
                command,
                principal,
                candidate_asset_version_id,
                candidate_content_hash,
                DesignTransition.STRUCTURAL_VALIDATE,
                expected_version=int(state["version"]),
                evidence={"passed": True, "validation_report": evidence},
            )
        from novel_forge.modules.story_design_authority.creative_validation import validation_state
        if validation_state(state):
            if state["approval"] == "NOT_REQUESTED":
                state = self._transition(command, principal, candidate_asset_version_id, candidate_content_hash,
                    DesignTransition.SUBMIT_APPROVAL, expected_version=int(state["version"]), evidence={})
            self._update_generation_status(operation_id, "APPROVAL_PENDING")
            if definition.risk_class != "HIGH" and command.auto_approve_low_risk:
                state = self.approve_candidate(
                    candidate_asset_version_id, principal=principal,
                    idempotency_key=f"{command.idempotency_key}:auto-approve",
                    trace_id=command.trace_id, correlation_id=command.correlation_id,
                )
                activated = self.activate_candidate(
                    candidate_asset_version_id, principal=principal,
                    idempotency_key=f"{command.idempotency_key}:auto-activate",
                    trace_id=command.trace_id, correlation_id=command.correlation_id,
                )
                return PlanningGenerationResult(operation_id, candidate_asset_version_id,
                    PlanningGenerationStatus.ACTIVE, state, activated["planning_binding"], replayed)
            return PlanningGenerationResult(operation_id, candidate_asset_version_id,
                PlanningGenerationStatus.APPROVAL_PENDING, state, replayed=replayed)
        from novel_forge.modules.story_design_authority.author_supervision import supervised_state
        if supervised_state(state):
            self._update_generation_status(operation_id, "APPROVAL_PENDING")
            return PlanningGenerationResult(operation_id, candidate_asset_version_id,
                PlanningGenerationStatus.APPROVAL_PENDING, state, replayed=replayed)
        if state["qualification"] == "STRUCTURALLY_VALID":
            if command.routing_bootstrap_authorization_id:
                self._update_generation_status(operation_id, "EVALUATION_PENDING")
                return PlanningGenerationResult(
                    operation_id, candidate_asset_version_id,
                    PlanningGenerationStatus.EVALUATION_PENDING, state,
                    replayed=replayed,
                )
            try:
                qualification = self._require_narrative_qualification_summary(
                    operation_id=operation_id,
                    candidate_asset_version_id=candidate_asset_version_id,
                    project_id=command.project_id,
                    book_id=command.book_id,
                    generator_operation_name=command.generator_operation_name,
                )
            except KernelError as exc:
                if exc.code != "NARRATIVE_QUALIFICATION_RECEIPT_INCOMPLETE":
                    raise
                self._update_generation_status(operation_id, "EVALUATION_PENDING")
                return PlanningGenerationResult(
                    operation_id,
                    candidate_asset_version_id,
                    PlanningGenerationStatus.EVALUATION_PENDING,
                    state,
                    replayed=replayed,
                )
            state = self._transition(
                command,
                principal,
                candidate_asset_version_id,
                candidate_content_hash,
                DesignTransition.SEMANTIC_VALIDATE,
                expected_version=int(state["version"]),
                evidence={"passed": True, **qualification},
            )
        if state["qualification"] == "SEMANTICALLY_VALID":
            qualification = self._require_narrative_qualification_summary(
                operation_id=operation_id,
                candidate_asset_version_id=candidate_asset_version_id,
                project_id=command.project_id,
                book_id=command.book_id,
                generator_operation_name=command.generator_operation_name,
            )
            state = self._transition(
                command,
                principal,
                candidate_asset_version_id,
                candidate_content_hash,
                DesignTransition.QUALIFY,
                expected_version=int(state["version"]),
                evidence={"passed": True, **qualification},
            )
        if state["qualification"] == "QUALIFIED":
            self._set_candidate_eligibility(
                project_id=command.project_id,
                candidate_asset_version_id=candidate_asset_version_id,
                eligibility="ELIGIBLE",
            )
        if (
            state["qualification"] == "QUALIFIED"
            and state["approval"] == "NOT_REQUESTED"
        ):
            state = self._transition(
                command,
                principal,
                candidate_asset_version_id,
                candidate_content_hash,
                DesignTransition.SUBMIT_APPROVAL,
                expected_version=int(state["version"]),
                evidence={"approval_policy_key": definition.approval_policy_key},
            )
        self._update_generation_status(operation_id, "APPROVAL_PENDING")
        if definition.risk_class != "HIGH" and command.auto_approve_low_risk:
            state = self.approve_candidate(
                candidate_asset_version_id,
                principal=principal,
                idempotency_key=f"{command.idempotency_key}:auto-approve",
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
            )
            activated = self.activate_candidate(
                candidate_asset_version_id,
                principal=principal,
                idempotency_key=f"{command.idempotency_key}:auto-activate",
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
            )
            return PlanningGenerationResult(
                operation_id,
                candidate_asset_version_id,
                PlanningGenerationStatus.ACTIVE,
                state,
                activated["planning_binding"],
                replayed,
            )
        return PlanningGenerationResult(
            operation_id,
            candidate_asset_version_id,
            PlanningGenerationStatus.APPROVAL_PENDING,
            state,
            replayed=replayed,
        )

    def _repair_or_reject(
        self,
        *,
        operation_id: str,
        candidate_asset_version_id: str,
        candidate_content_hash: str,
        command: StoryPlanningGenerationCommand,
        principal: Principal,
        definition: Any,
        error: KernelError,
    ) -> PlanningGenerationResult:
        semantic = error.code in {
            "STORY_DESIGN_SEMANTIC_INVALID",
            "NARRATIVE_SEMANTIC_EVALUATION_REQUIRED",
            "NARRATIVE_SEMANTIC_EVALUATION_INVALID",
            "NARRATIVE_SEMANTIC_PROFILE_DRIFT",
            "NARRATIVE_SEMANTIC_QUALIFICATION_FAILED",
        }
        validation_kind = "SEMANTIC" if semantic else "STRUCTURAL"
        maximum = definition.maximum_semantic_repairs if semantic else definition.maximum_structural_regenerations
        from .stage_repairs import repair_bound
        bound = repair_bound(self, command=command, operation_id=operation_id, maximum=maximum)
        report = {
            "status": "FAIL",
            "validation_kind": validation_kind,
            "error_code": error.code,
            "message": error.message,
            "candidate_asset_version_id": candidate_asset_version_id,
        }
        if bound is not None:
            report["stage_repair_bound"] = bound
        if error.code.startswith(("SCENE_", "BEAT_", "REALIZATION_")):
            report["directed_rejection"] = {
                "contract_version": "planning-directed-rejection.v1",
                "source_boundary": "SCENE_REALIZATION_CONTRACT",
                "target_generator": command.generator_operation_name,
                "target_candidate_version_id": candidate_asset_version_id,
                "frozen_input_versions": {
                    item["role"]: item["asset_version_id"]
                    for item in self.require_generation(operation_id)["input_snapshot"]
                },
                "repair_number": command.repair_number,
                "maximum_repairs": definition.maximum_structural_regenerations,
                "restart_scope": "REJECTED_CANDIDATE_AND_DEPENDENT_UNEXECUTED_NODES",
                "accepted_history_mutation_allowed": False,
            }
        report_hash = self._record_validation(
            operation_id=operation_id,
            candidate_asset_version_id=candidate_asset_version_id,
            validation_kind=validation_kind,
            status="FAIL",
            report=report,
        )
        state = self.story_design.require(
            project_id=command.project_id,
            asset_version_id=candidate_asset_version_id,
        )
        if semantic:
            state = self._transition(
                command,
                principal,
                candidate_asset_version_id,
                candidate_content_hash,
                DesignTransition.STRUCTURAL_VALIDATE,
                expected_version=int(state["version"]),
                evidence={"passed": True, "validation_report_hash": report_hash},
            )
            transition = DesignTransition.SEMANTIC_VALIDATE
            maximum = definition.maximum_semantic_repairs
        else:
            transition = DesignTransition.STRUCTURAL_VALIDATE
            maximum = definition.maximum_structural_regenerations
        state = self._transition(
            command,
            principal,
            candidate_asset_version_id,
            candidate_content_hash,
            transition,
            expected_version=int(state["version"]),
            evidence={"passed": False, "validation_report_hash": report_hash},
        )
        exhausted=(bound['stage_repair_number']>=bound['maximum_repairs'] or command.repair_number>=4) if bound else command.repair_number>=maximum
        if exhausted:
            self._update_generation_status(operation_id, "REJECTED")
            return PlanningGenerationResult(
                operation_id,
                candidate_asset_version_id,
                PlanningGenerationStatus.REJECTED,
                state,
            )
        self._update_generation_status(operation_id, "REPAIR_REQUIRED")
        if command.routing_bootstrap_authorization_id:
            return PlanningGenerationResult(
                operation_id, candidate_asset_version_id,
                PlanningGenerationStatus.REPAIR_REQUIRED, state,
            )
        repaired = replace(
            command,
            runtime_continuation_id="",
            repair_of_candidate_id=candidate_asset_version_id,
            repair_of_operation_id="",
            repair_result_asset_version_id="",
            repair_result_diagnostic=None,
            repair_reason=f"{error.code}:{report_hash}",
            repair_number=command.repair_number + 1,
            idempotency_key=f"{command.idempotency_key}:repair:{command.repair_number + 1}",
        )
        return self.generate(repaired, principal=principal)

    def _transition(
        self,
        command: StoryPlanningGenerationCommand,
        principal: Principal,
        candidate_asset_version_id: str,
        content_hash: str,
        transition: DesignTransition,
        *,
        expected_version: int,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        return self.story_design.transition(
            StoryDesignTransitionCommand(
                project_id=command.project_id,
                workspace_id=command.workspace_id,
                actor_id=command.actor_id,
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
                idempotency_key=(
                    f"{command.idempotency_key}:story-design:{transition.value}:"
                    f"{candidate_asset_version_id}:v{expected_version}"
                ),
                asset_version_id=candidate_asset_version_id,
                content_hash=content_hash,
                logical_key=command.logical_key,
                generator_operation_name=command.generator_operation_name,
                transition=transition,
                planning_scope=command.planning_scope,
                expected_version=expected_version,
                evidence=evidence,
            ),
            principal=principal,
        )

    def _candidate_evidence(self, candidate_asset_version_id: str) -> dict[str, Any]:
        content = self._require_asset_by_id(candidate_asset_version_id)["content"]
        evidence = dict(content.get("execution_evidence") or {})
        if not evidence:
            raise KernelError(
                "PLANNING_CANDIDATE_EXECUTION_EVIDENCE_MISSING",
                "materialized Planning Candidate lacks PEP evidence",
            )
        return evidence

    def _resolve_inputs(
        self, command: StoryPlanningGenerationCommand
    ) -> tuple[FrozenPlanningInput, ...]:
        authority_roles = _authority_role_versions(command)
        plan_input_ids = [
            asset_version_id
            for role, asset_version_id in authority_roles.items()
            if role in _PLAN_INPUT_CONTRACTS
            or role.startswith("arc_scope_volume:")
            or role.startswith("related_arc:")
            or role.startswith("dependent_arc:")
            or role == "chapter_function_matrix_row"
        ]
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT project_id, workspace_id
                FROM authority_book
                WHERE book_id=%s
                """,
                [command.book_id],
            )
            book = uow.cursor.fetchone()
            if book != (command.project_id, command.workspace_id):
                raise KernelError(
                    "PLANNING_GENERATION_BOOK_SCOPE_INVALID",
                    "Planning Generation Book belongs to another Project or Workspace",
                )
            uow.cursor.execute(
                """
                SELECT version.asset_version_id, asset.asset_type,
                       version.content_hash, version.content,
                       NOT EXISTS (
                           SELECT 1
                           FROM authority_asset_supersession AS supersession
                           WHERE supersession.previous_asset_version_id=
                                 version.asset_version_id
                       ) AS is_current_version
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE asset.project_id=%s
                  AND version.asset_version_id=ANY(%s)
                  AND version.lifecycle='ACTIVE'
                  AND version.eligibility='ELIGIBLE'
                  AND version.governance='CLEAR'
                """,
                [command.project_id, list(authority_roles.values())],
            )
            rows = uow.cursor.fetchall()
            uow.cursor.execute(
                """
                SELECT binding.asset_version_id, binding.contract_type,
                       binding.parent_version_id
                FROM story_plan_binding AS binding
                JOIN active_story_plan_version AS active
                  ON active.project_id=binding.project_id
                 AND active.book_id=binding.book_id
                 AND active.binding_id=binding.binding_id
                 AND active.asset_version_id=binding.asset_version_id
                WHERE binding.project_id=%s AND binding.book_id=%s
                  AND binding.asset_version_id=ANY(%s::text[])
                  AND binding.freshness='CURRENT'
                """,
                [command.project_id, command.book_id, plan_input_ids],
            )
            plan_rows = uow.cursor.fetchall()
        by_id = {
            str(row[0]): {
                "asset_type": str(row[1]),
                "content_hash": str(row[2]),
                "content": dict(row[3]),
                "is_current_version": bool(row[4]),
            }
            for row in rows
        }
        if any(
            item["content"].get("routing_eligibility") == "BENCHMARK_ONLY"
            or item["content"].get("routing_bootstrap_authorization")
            for item in by_id.values()
        ):
            raise KernelError(
                "PLANNING_BENCHMARK_ONLY",
                "bootstrap candidates cannot become active production inputs",
            )
        plan_by_id = {
            str(row[0]): {
                "contract_type": PlanContractType(str(row[1])),
                "parent_version_id": str(row[2] or ""),
            }
            for row in plan_rows
        }
        missing = sorted(set(authority_roles.values()) - set(by_id))
        if missing:
            raise KernelError(
                "PLANNING_GENERATION_INPUT_AUTHORITY_INVALID",
                "Planning inputs are missing, ineligible, or outside Project scope: "
                + ", ".join(missing),
            )
        result: list[FrozenPlanningInput] = []
        for role, asset_version_id in authority_roles.items():
            item = by_id[asset_version_id]
            if role == "creative_brief":
                from novel_forge.modules.creative.input_selection import require_selected_brief
                with AuthorityUnitOfWork(self.database_url) as input_uow:
                    input_uow.cursor.execute("""SELECT 1 FROM authority_story_formation_run
                        WHERE project_id=%s AND workspace_id=%s AND book_id=%s
                        AND frozen_stage_inputs->>'creative_brief_asset_version_id'=%s
                        AND frozen_stage_inputs->>'creative_brief_content_hash'=%s""",
                        [command.project_id, command.workspace_id, command.book_id, asset_version_id, item["content_hash"]])
                    legacy_frozen = input_uow.cursor.fetchone() is not None
                    require_selected_brief(input_uow.cursor, asset_version_id=asset_version_id,
                        content_hash=item["content_hash"], project_id=command.project_id,
                        workspace_id=command.workspace_id, book_id=command.book_id, allow_legacy_frozen=legacy_frozen)
            expected_contract = (
                PlanContractType.VOLUME
                if role.startswith("arc_scope_volume:")
                else PlanContractType.ARC
                if role.startswith(("related_arc:", "dependent_arc:"))
                else _PLAN_INPUT_CONTRACTS.get(role)
            )
            if expected_contract is not None:
                plan = plan_by_id.get(asset_version_id)
                if plan is None or plan["contract_type"] is not expected_contract:
                    raise KernelError(
                        "PLANNING_GENERATION_INPUT_ROLE_INVALID",
                        f"Authority input {role} is not the current Active "
                        f"{expected_contract.value} Plan for this Book",
                    )
            elif role == "chapter_function_matrix_row" and (
                item["asset_type"] not in {role, "chapter_function_matrix"}
                and (
                    asset_version_id not in plan_by_id
                    or plan_by_id[asset_version_id]["contract_type"]
                    is not PlanContractType.CHAPTER_GROUP
                    or not isinstance(
                        item["content"].get("chapter_function_matrix"), list
                    )
                )
            ):
                raise KernelError(
                    "PLANNING_GENERATION_INPUT_ROLE_INVALID",
                    "chapter_function_matrix_row must be a typed Authority asset "
                    "or the current Active ChapterGroupPlan containing the matrix",
                )
            elif role.startswith("narrative_governance_action:"):
                if (
                    item["asset_type"]
                    not in {"governance_decision", "narrative_governance_action"}
                    or not item["is_current_version"]
                ):
                    raise KernelError(
                        "PLANNING_GENERATION_GOVERNANCE_ACTION_INVALID",
                        "Narrative governance action must be current typed Authority evidence",
                    )
            elif role != "chapter_function_matrix_row":
                allowed_asset_types = _AUTHORITY_INPUT_ASSET_TYPES.get(
                    role, frozenset({role})
                )
                foundation_role = next((value for value in FOUNDATION_GENERATORS.values() if value.value.lower() == role), None)
                generated_foundation = item["asset_type"] == "planning_generation_candidate" and foundation_role is not None
                if generated_foundation:
                    generator = str(item["content"].get("generator_operation_name") or "")
                    if FOUNDATION_GENERATORS.get(generator) is not foundation_role or item["content"].get("planning_scope") != "NOT_APPLICABLE":
                        raise KernelError("FOUNDATION_INPUT_OWNER_INVALID", "Generated Foundation role differs from its semantic owner")
                    state = self.story_design.require(project_id=command.project_id, asset_version_id=asset_version_id)
                    from novel_forge.modules.story_design_authority.author_supervision import supervised_state
                    from novel_forge.modules.story_design_authority.creative_validation import validation_state
                    admitted = state["qualification"] == "QUALIFIED" or supervised_state(state) or validation_state(state)
                    if not admitted or (state["lifecycle"], state["approval"], state["freshness"]) != ("ACTIVE", "APPROVED", "CURRENT"):
                        raise KernelError("FOUNDATION_INPUT_NOT_ACTIVE", "Generated Foundation must be independently qualified and activated")
                if item["asset_type"] not in allowed_asset_types and not generated_foundation:
                    raise KernelError(
                        "PLANNING_GENERATION_INPUT_ROLE_INVALID",
                        f"Authority input {role} has asset type {item['asset_type']}",
                    )
            declared_book = str(item["content"].get("book_id") or "")
            if declared_book and declared_book != command.book_id:
                raise KernelError(
                    "PLANNING_GENERATION_INPUT_BOOK_INVALID",
                    f"Authority input {role} belongs to another Book",
                )
            result.append(
                FrozenPlanningInput(
                    role=role,
                    asset_version_id=asset_version_id,
                    content_hash=item["content_hash"],
                    asset_type=item["asset_type"],
                )
            )
        expected_parent_role = {
            "volume_plan.generate": "book_plan",
            "chapter_group_plan.generate": "volume_plan",
            "chapter_plan.generate": "chapter_group_plan",
        }.get(command.generator_operation_name)
        if expected_parent_role is None:
            if command.parent_version_id:
                raise KernelError(
                    "PLANNING_GENERATION_PARENT_INVALID",
                    f"{command.planning_scope.value} generation cannot declare a "
                    "containment parent Plan",
                )
        elif command.parent_version_id != command.input_versions[expected_parent_role]:
            raise KernelError(
                "PLANNING_GENERATION_PARENT_INVALID",
                f"{command.planning_scope.value} parent must equal the frozen "
                f"{expected_parent_role} Authority version",
            )
        plan_relationships = (
            ("volume_plan", "book_plan"),
            ("chapter_group_plan", "volume_plan"),
        )
        for child_role, parent_role in plan_relationships:
            child_id = command.input_versions.get(child_role)
            parent_id = command.input_versions.get(parent_role)
            if not child_id or not parent_id:
                continue
            if plan_by_id[child_id]["parent_version_id"] != parent_id:
                raise KernelError(
                    "PLANNING_GENERATION_INPUT_HIERARCHY_INVALID",
                    f"Authority input {child_role} is not a child of the frozen "
                    f"{parent_role} version",
                )
        governed_by_id = {
            item.asset_version_id: item
            for item in result
            if item.role.startswith("narrative_governance_action:")
        }
        for item in by_id.values():
            content = item["content"]
            envelope = content.get("constraint_envelope")
            policy = (
                envelope.get("narrative_load_policy")
                if isinstance(envelope, dict)
                else content.get("narrative_load_policy")
            )
            if not isinstance(policy, dict):
                continue
            for override in policy.get("governed_overrides") or ():
                if not isinstance(override, dict):
                    continue
                action_id = str(
                    override.get("governance_action_asset_version_id") or ""
                )
                action_hash = str(override.get("governance_action_content_hash") or "")
                frozen = governed_by_id.get(action_id)
                if frozen is None or frozen.content_hash != action_hash:
                    raise KernelError(
                        "PLANNING_GENERATION_GOVERNANCE_ACTION_UNBOUND",
                        "Narrative Load override is not bound to exact governance Authority evidence",
                    )
        return tuple(result)

    def _resolve_change_evidence(
        self, command: StoryPlanningGenerationCommand
    ) -> tuple[FrozenPlanningInput, ...]:
        if not command.change_evidence_version_ids:
            return ()
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT version.asset_version_id, asset.asset_type,
                       version.content_hash, version.content
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE asset.project_id=%s
                  AND version.asset_version_id=ANY(%s)
                  AND version.lifecycle='ACTIVE'
                  AND version.eligibility='ELIGIBLE'
                  AND version.governance='CLEAR'
                """,
                [command.project_id, list(command.change_evidence_version_ids)],
            )
            rows = uow.cursor.fetchall()
        by_id = {str(row[0]): row for row in rows}
        if set(by_id) != set(command.change_evidence_version_ids):
            raise KernelError(
                "PLANNING_GENERATION_CHANGE_EVIDENCE_INVALID",
                "Planning change evidence is missing or outside Authority scope",
            )
        result: list[FrozenPlanningInput] = []
        for ordinal, asset_version_id in enumerate(
            command.change_evidence_version_ids, start=1
        ):
            row = by_id[asset_version_id]
            asset_type = str(row[1])
            content = dict(row[3])
            if asset_type == "longform_prose_review_report":
                from novel_forge.modules.book_followup_authority.prose_change_evidence import require_prose_planning_evidence
                require_prose_planning_evidence(self.database_url, command=command, asset_version_id=asset_version_id, commit_sha=self.commit_sha)
            elif asset_type == "arc_revision_candidate" and command.execution_contract_version == "1.21.0":
                from .recap_sources import require_arc_recap_change_evidence
                require_arc_recap_change_evidence(self.database_url, command, asset_version_id, content)
            elif asset_type not in {"longform_recap", "replan_request"}:
                raise KernelError(
                    "PLANNING_GENERATION_CHANGE_EVIDENCE_TYPE_INVALID",
                    "Planning change evidence requires a governed Recap, ReplanRequest or current native prose review",
                )
            declared_book = str(content.get("book_id") or "")
            if declared_book and declared_book != command.book_id:
                raise KernelError(
                    "PLANNING_GENERATION_CHANGE_EVIDENCE_BOOK_INVALID",
                    "Planning change evidence belongs to another Book",
                )
            result.append(
                FrozenPlanningInput(
                    role=f"change_evidence:{ordinal}",
                    asset_version_id=asset_version_id,
                    content_hash=str(row[2]),
                    asset_type=asset_type,
                )
            )
        return tuple(result)

    def _record_generation(
        self,
        *,
        operation_id: str,
        command: StoryPlanningGenerationCommand,
        inputs: tuple[FrozenPlanningInput, ...],
    ) -> None:
        snapshot = [asdict(item) for item in inputs]
        repair_fields = (
            ("repair_of_operation_id", "repair_result_asset_version_id")
            if command.repair_of_operation_id else ()
        )
        if command.runtime_continuation_id:
            repair_fields += ("runtime_continuation_id",)
        source_operation_id = command.repair_of_operation_id
        if command.runtime_continuation_id:
            from .runtime_continuation import require_binding
            source_operation_id = require_binding(self.database_url, command.runtime_continuation_id)["source_operation_id"]
        elif command.repair_of_candidate_id:
            from .execution import require_candidate_repair_operation
            with AuthorityUnitOfWork(self.database_url) as uow:
                source_operation_id = require_candidate_repair_operation(uow.cursor,
                    candidate_asset_version_id=command.repair_of_candidate_id, project_id=command.project_id,
                    book_id=command.book_id, generator_operation_name=command.generator_operation_name,
                    logical_key=command.logical_key)
        with AuthorityUnitOfWork(self.database_url) as uow:
            if source_operation_id:
                uow.cursor.execute(
                    """
                    SELECT input_snapshot, input_snapshot_hash
                    FROM authority_story_planning_generation
                    WHERE operation_id=%s AND project_id=%s AND workspace_id=%s
                      AND book_id=%s AND generator_operation_name=%s AND logical_key=%s
                    """,
                    [source_operation_id, command.project_id,
                     command.workspace_id, command.book_id,
                     command.generator_operation_name, command.logical_key],
                )
                source = uow.cursor.fetchone()
                if source is None:
                    raise KernelError(
                        "PLANNING_RESULT_REPAIR_SOURCE_INVALID",
                        "result repair requires its exact frozen Planning Generation",
                    )
                snapshot = _replay_generation_input_snapshot(snapshot, source[0], source[1])
            snapshot_hash = canonical_hash(snapshot)
            if command.runtime_continuation_id:
                from .runtime_continuation import attach_successor
                attach_successor(uow, command, operation_id)
            uow.cursor.execute(
                sql.SQL("""
                INSERT INTO authority_story_planning_generation(
                    generation_id, operation_id, project_id, workspace_id,
                    book_id, generator_operation_name, planning_scope,
                    logical_key, parent_version_id, input_snapshot,
                    input_snapshot_hash, status, repair_of_candidate_id,
                    repair_reason, repair_number, narrative_search_id,
                    narrative_search_branch_key{repair_columns}
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, NULLIF(%s, ''),
                    %s, %s, 'ADMITTED', NULLIF(%s, ''), NULLIF(%s, ''), %s,
                    NULLIF(%s, ''), NULLIF(%s, ''){repair_values}
                )
                ON CONFLICT (operation_id) DO NOTHING
                """).format(
                    repair_columns=sql.SQL("").join(
                        sql.SQL(", {} ").format(sql.Identifier(field))
                        for field in repair_fields
                    ),
                    repair_values=sql.SQL(", NULLIF(%s, '')" * len(repair_fields)),
                ),
                [
                    f"planning-generation:{operation_id}",
                    operation_id,
                    command.project_id,
                    command.workspace_id,
                    command.book_id,
                    command.generator_operation_name,
                    command.planning_scope.value,
                    command.logical_key,
                    command.parent_version_id,
                    Jsonb(snapshot),
                    snapshot_hash,
                    command.repair_of_candidate_id,
                    command.repair_reason,
                    command.repair_number,
                    command.narrative_search_id,
                    command.narrative_search_branch_key,
                ] + [getattr(command, field) for field in repair_fields],
            )
            uow.commit()

    def _record_candidate(
        self,
        *,
        operation_id: str,
        candidate_asset_version_id: str,
        candidate_content_hash: str,
        command: StoryPlanningGenerationCommand,
        attempt_id: str,
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_story_planning_candidate(
                    candidate_id, generation_id, project_id, book_id,
                    candidate_asset_version_id, content_hash,
                    attempt_id, repair_of_candidate_id
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, NULLIF(%s, '')
                ) ON CONFLICT (generation_id) DO NOTHING
                """,
                [
                    f"planning-candidate:{candidate_asset_version_id}",
                    f"planning-generation:{operation_id}",
                    command.project_id,
                    command.book_id,
                    candidate_asset_version_id,
                    candidate_content_hash,
                    attempt_id,
                    command.repair_of_candidate_id,
                ],
            )
            uow.cursor.execute(
                """
                UPDATE authority_story_planning_generation
                SET candidate_asset_version_id=%s,
                    status='CANDIDATE_MATERIALIZED', version=version+1,
                    updated_at=NOW()
                WHERE operation_id=%s
                  AND (candidate_asset_version_id IS NULL
                       OR candidate_asset_version_id=%s)
                """,
                [candidate_asset_version_id, operation_id, candidate_asset_version_id],
            )
            uow.commit()

    def _record_validation(
        self,
        *,
        operation_id: str,
        candidate_asset_version_id: str,
        validation_kind: str,
        status: str,
        report: dict[str, Any],
    ) -> str:
        report_hash = canonical_hash(report)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_story_planning_validation_report(
                    validation_report_id, project_id,
                    candidate_asset_version_id, generation_operation_id,
                    validation_kind, status, report, report_hash
                )
                SELECT %s, generation.project_id, %s, %s, %s, %s, %s, %s
                FROM authority_story_planning_generation AS generation
                WHERE generation.operation_id=%s
                ON CONFLICT (candidate_asset_version_id, validation_kind, report_hash)
                DO NOTHING
                """,
                [
                    report_hash,
                    candidate_asset_version_id,
                    operation_id,
                    validation_kind,
                    status,
                    Jsonb(report),
                    report_hash,
                    operation_id,
                ],
            )
            uow.commit()
        return report_hash

    def _require_narrative_qualification_summary(
        self,
        *,
        operation_id: str,
        candidate_asset_version_id: str,
        project_id: str,
        book_id: str,
        generator_operation_name: str,
    ) -> dict[str, Any]:
        from novel_forge.modules.story_design_authority.qualification import (
            qualification_profile_options,
        )

        candidate = self._require_asset(
            project_id=project_id, asset_version_id=candidate_asset_version_id
        )
        profiles = required_qualification_profiles(
            generator_operation_name,
            **qualification_profile_options(candidate["content"]),
        )
        expected = {profile.layer.value: profile for profile in profiles}
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT design_layer, profile_id, profile_version, profile_hash,
                       evaluation_hash, qualification_hash,
                       evaluator_execution_class, evaluation_operation_id,
                       evaluation_attempt_id, evaluation_asset_version_id,
                       evaluation_evidence_hash
                FROM authority_narrative_design_qualification
                WHERE project_id=%s AND book_id=%s
                  AND asset_version_id=%s AND generation_operation_id=%s
                  AND qualification_status='PASS'
                  AND trust_boundary='INDEPENDENT'
                  AND (
                        evaluator_execution_class='MODEL_PROVIDER'
                        OR (%s AND evaluator_execution_class='SCRIPTED_FIXTURE')
                      )
                  AND (
                        evaluator_execution_class<>'MODEL_PROVIDER'
                        OR (
                            provider_model_call_asset_version_id IS NOT NULL
                            AND provider_model_call_content_hash IS NOT NULL
                            AND provider_evidence_hash IS NOT NULL
                            AND provider_result_hash IS NOT NULL
                            AND provider_route_snapshot_id IS NOT NULL
                        )
                      )
                ORDER BY design_layer
                """,
                [
                    project_id,
                    book_id,
                    candidate_asset_version_id,
                    operation_id,
                    self.allow_scripted_evaluation_fixture,
                ],
            )
            rows = uow.cursor.fetchall()
        by_layer = {str(row[0]): row for row in rows}
        if set(by_layer) != set(expected) or len(rows) != len(expected):
            raise KernelError(
                "NARRATIVE_QUALIFICATION_RECEIPT_INCOMPLETE",
                "Narrative Semantic Evaluation receipts are missing or ambiguous",
            )
        hashes: set[str] = set()
        receipts: list[dict[str, Any]] = []
        for layer in sorted(expected):
            row = by_layer[layer]
            profile = expected[layer]
            if tuple(str(item) for item in row[1:4]) != (
                profile.profile_id,
                profile.profile_version,
                profile.profile_hash,
            ):
                raise KernelError(
                    "NARRATIVE_QUALIFICATION_RECEIPT_STALE",
                    "stored Narrative Qualification profile differs from current policy",
                )
            hashes.add(str(row[5]))
            receipts.append(
                {
                    "design_layer": layer,
                    "profile_hash": str(row[3]),
                    "evaluation_hash": str(row[4]),
                    "evaluator_execution_class": str(row[6]),
                    "evaluation_operation_id": str(row[7]),
                    "evaluation_attempt_id": str(row[8]),
                    "evaluation_asset_version_id": str(row[9]),
                    "evaluation_evidence_hash": str(row[10]),
                }
            )
        if len(hashes) != 1:
            raise KernelError(
                "NARRATIVE_QUALIFICATION_RECEIPT_INCONSISTENT",
                "layer receipts do not share one qualification identity",
            )
        return {
            "narrative_qualification_hash": hashes.pop(),
            "narrative_qualification_receipts": receipts,
        }

    def _update_generation_status(self, operation_id: str, status: str) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                UPDATE authority_story_planning_generation
                SET status=%s, version=version+1, updated_at=NOW()
                WHERE operation_id=%s AND status<>%s
                """,
                [status, operation_id, status],
            )
            uow.commit()

    def _set_candidate_eligibility(
        self,
        *,
        project_id: str,
        candidate_asset_version_id: str,
        eligibility: str,
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            from novel_forge.modules.story_design_authority.creative_validation import candidate_validation
            validation = candidate_validation(uow.cursor, project_id=project_id, asset_version_id=candidate_asset_version_id)
            if validation is not None:
                uow.cursor.execute("SELECT qualification,execution_evidence FROM authority_story_design_version_state WHERE project_id=%s AND asset_version_id=%s FOR UPDATE", [project_id, candidate_asset_version_id])
                state = uow.cursor.fetchone()
                if not state or state[0] != "STRUCTURALLY_VALID" or state[1].get("creative_validation") != validation:
                    raise KernelError("PLANNING_VALIDATION_ELIGIBILITY_INVALID", candidate_asset_version_id)
            uow.cursor.execute(
                """
                UPDATE authority_asset_version AS version
                SET eligibility=%s
                FROM authority_asset AS asset
                WHERE version.asset_version_id=%s
                  AND version.asset_id=asset.asset_id
                  AND asset.project_id=%s
                  AND version.lifecycle='CANDIDATE'
                  AND version.eligibility IN ('INELIGIBLE', %s)
                """,
                [
                    eligibility,
                    candidate_asset_version_id,
                    project_id,
                    eligibility,
                ],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "PLANNING_CANDIDATE_ELIGIBILITY_CONFLICT",
                    "Planning candidate eligibility changed outside qualification",
                )
            if validation is not None:
                identity = canonical_hash({"asset_version_id": candidate_asset_version_id, "validation": validation, "decision": eligibility})
                uow.cursor.execute("INSERT INTO authority_asset_qualification(qualification_id,asset_version_id,policy_version,decision,evidence) VALUES (%s,%s,'creative-validation-eligibility.v1',%s,%s) ON CONFLICT (qualification_id) DO NOTHING", [identity, candidate_asset_version_id, eligibility, Jsonb(validation)])
                uow.commit()
                return
            uow.cursor.execute(
                """
                SELECT evaluation_operation_id, qualification_hash
                FROM authority_narrative_design_qualification
                WHERE project_id=%s AND asset_version_id=%s
                  AND qualification_status='PASS'
                  AND trust_boundary='INDEPENDENT'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                [project_id, candidate_asset_version_id],
            )
            receipt = uow.cursor.fetchone()
            if receipt is None:
                raise KernelError(
                    "PLANNING_CANDIDATE_QUALIFICATION_MISSING",
                    "Planning eligibility requires independent Narrative Qualification",
                )
            qualification_id = canonical_hash(
                {
                    "asset_version_id": candidate_asset_version_id,
                    "evaluation_operation_id": str(receipt[0]),
                    "decision": eligibility,
                }
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_qualification(
                    qualification_id, asset_version_id,
                    policy_version, decision, evidence
                ) VALUES (
                    %s, %s, 'independent-narrative-evaluation-v1', %s, %s
                )
                ON CONFLICT (qualification_id) DO NOTHING
                """,
                [
                    qualification_id,
                    candidate_asset_version_id,
                    eligibility,
                    Jsonb(
                        {
                            "schema_version": "planning-semantic-evaluation.v1",
                            "evaluation_operation_id": str(receipt[0]),
                            "qualification_hash": str(receipt[1]),
                            "trust_boundary": "INDEPENDENT",
                        }
                    ),
                ],
            )
            uow.commit()

    def _require_asset(
        self, *, project_id: str, asset_version_id: str
    ) -> dict[str, Any]:
        result = self._require_asset_by_id(asset_version_id)
        if result["project_id"] != project_id:
            raise KernelError(
                "PLANNING_ASSET_SCOPE_INVALID",
                "Planning asset belongs to another Project",
            )
        return result

    def _require_asset_by_id(self, asset_version_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT version.asset_version_id, version.asset_id, asset.project_id,
                       asset.asset_type, version.content_hash, version.content
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE version.asset_version_id=%s
                """,
                [asset_version_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "PLANNING_ASSET_NOT_FOUND", "Planning asset does not exist"
            )
        return dict(
            zip(
                (
                    "asset_version_id",
                    "asset_id",
                    "project_id",
                    "asset_type",
                    "content_hash",
                    "content",
                ),
                row,
                strict=True,
            )
        )

    def _register_definitions(self, definition_version: str) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.definitions.register(
                story_planning_generation_definition(
                    application_build_id=self.application_build_id,
                    commit_sha=self.commit_sha,
                    definition_version=definition_version,
                )
            )
            for definition in GENERATOR_CATALOG.values():
                uow.repositories.story_design.register_generator(asdict(definition))
            uow.commit()


def chapter_plan_projection_definition(
    *, application_build_id: str, commit_sha: str, definition_version: str = "2.0.0"
) -> dict[str, Any]:
    command = {
        "type": "object",
        "required": ["project_id", "candidate_asset_version_id"],
        "properties": {
            "project_id": {"type": "string", "minLength": 1},
            "candidate_asset_version_id": {"type": "string", "minLength": 1},
        },
        "additionalProperties": False,
    }
    result = {
        "type": "object",
        "required": [
            "asset_version_id",
            "content_hash",
            "source_planning_candidate_asset_version_id",
        ],
        "properties": {
            "asset_version_id": {"type": "string", "minLength": 1},
            "content_hash": {"type": "string", "minLength": 1},
            "source_planning_candidate_asset_version_id": {
                "type": "string",
                "minLength": 1,
            },
        },
        "additionalProperties": False,
    }
    return {
        "name": CHAPTER_PLAN_PROJECTION_DEFINITION,
        "definition_version": definition_version,
        "family": "story_planning",
        "command_schema_version": "story-planning-chapter-plan-projection.command.v1",
        "result_schema_version": "story-planning-chapter-plan-projection.result.v1",
        "enabled": True,
        "command_schema": command,
        "result_schema": result,
        "input_contract": command,
        "output_contract": {
            **result,
            "asset_type": "chapter_plan",
            "output_key": "story_planning.chapter_plan_projection",
            "role": "primary",
        },
        "handler_key": CHAPTER_PLAN_PROJECTION_HANDLER,
        "handler_contract_version": "story-planning-chapter-plan-projection-v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "transactional",
        "permissions": ["story_planning.authority.activate"],
        "approval_policy": {"required": False},
        "policy": {
            "execution_classification": "transaction_command",
            "candidate_activation_required": True,
            "lineage_required": True,
        },
        "idempotency_scope": "book:activated-chapter-plan",
        "concurrency_key_template": "book:{book_id}:chapter-plan-projection",
        "retry_policy": {"max_attempts": 1},
        "timeout_policy": {"operation_timeout_seconds": 30},
        "cancellation_policy": {"mode": "not_applicable_atomic"},
        "compensation_policy": {
            "supported": False,
            "reason": "append-only typed planning projection",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "projection_consumers": ["chapter_authority"],
        "migration_owner": "story-planning-runtime",
        "completion_contract": {
            "version": "story-planning-chapter-plan-projection-completion-v1",
            "required_asset_selectors": [
                {
                    "selector": "chapter_plan",
                    "output_key": "story_planning.chapter_plan_projection",
                    "role": "primary",
                    "lifecycle": "ACTIVE",
                    "eligibility": "ELIGIBLE",
                    "governance": "CLEAR",
                }
            ],
            "required_qualifications": [{"decision": "ELIGIBLE"}],
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": ["story_planning.chapter_plan.materialized"],
        },
    }


def _chapter_runtime_projection(candidate: dict[str, Any], *, projection_version: str = "2.0.0") -> dict[str, Any]:
    from novel_forge.modules.hierarchical_planning.chapter_contracts import (
        require_chapter_contracts,
    )

    require_chapter_contracts(candidate)
    if (projection_version == "3.0.0") != (candidate.get("chapter_contract_schema_version") == "chapter-mission-scene.v4"):
        raise KernelError("CHAPTER_PROJECTION_CONTRACT_MISMATCH", "Current method projection requires its exact Mission contract")

    from novel_forge.modules.story_design_authority.qualification import uses_work_requirements
    if (projection_version in {"2.0.0", "3.0.0"} and uses_work_requirements(candidate)
            and candidate.get("chapter_contract_schema_version") == ("chapter-mission-scene.v4" if projection_version == "3.0.0" else "chapter-mission-scene.v3")):
        return {
            **candidate,
            "chapter": int(candidate.get("chapter_number") or candidate.get("chapter") or 0),
            "title": str(candidate.get("title") or ""),
            "premise": str(candidate.get("premise") or candidate.get("objective") or ""),
            "runtime_projection_version": projection_version,
            "chapter_function": candidate["primary_function"],
            "chapter_objective": str(candidate.get("objective") or ""),
            "scene_sequence": list(candidate.get("scene_plan") or ()),
            "chapter_hook": candidate.get("ending_hook"),
            "next_chapter_bridge": candidate.get("next_chapter_bridge"),
            "reward_setup": list(candidate.get("reward_setup") or ()),
            "reward_payoff": list(candidate.get("reward_payoff") or ()),
            "reader_promise_actions": list(candidate.get("required_payoffs") or ())
                or ([candidate["promise_action"]] if candidate.get("promise_action") is not None else []),
            "emotional_curve": list(candidate.get("emotional_curve") or ()),
            "suspense_curve": list(candidate.get("suspense_curve") or ()),
            "protagonist_charm_mechanism": candidate.get("protagonist_charm_mechanism"),
            "antagonist_pressure": candidate.get("antagonist_pressure"),
            "conflict_chain": list(candidate.get("conflict_chain") or ()),
            "conflict_escalation": list(candidate.get("conflict_escalation") or ()),
            "information_reveals": list(candidate.get("information_reveals") or ()),
        }

    primary = str(candidate.get("primary_function") or "progression")
    objective = str(candidate.get("objective") or candidate.get("premise") or "")
    hook = str(candidate.get("ending_hook") or "the choice creates a new obligation")
    required_events = list(candidate.get("required_events") or ())
    required_payoffs = list(candidate.get("required_payoffs") or ())
    hard_constraints = list(candidate.get("hard_constraints") or ())
    return {
        **candidate,
        "chapter": int(
            candidate.get("chapter_number") or candidate.get("chapter") or 0
        ),
        "title": str(
            candidate.get("title")
            or (f"Chapter {int(candidate.get('chapter_number') or 0)}: {primary}")
        ),
        "premise": str(candidate.get("premise") or objective),
        "chapter_function": primary,
        "chapter_objective": objective,
        "scene_sequence": list(candidate.get("scene_plan") or required_events),
        "chapter_hook": hook,
        "conflict_chain": hard_constraints
        or ["the objective meets escalating resistance"],
        "emotional_curve": ["pressure", "choice", "consequence"],
        "suspense_curve": ["question", "complication", "earned hook"],
        "reader_promise_actions": required_payoffs
        or [str(candidate.get("promise_action") or "advance the central promise")],
        "protagonist_charm_mechanism": (
            "the protagonist accepts a visible cost to preserve agency"
        ),
        "information_reveals": required_events
        or ["the choice exposes a consequence hidden at entry"],
        "antagonist_pressure": "resistance intensifies before the chapter turn",
        "next_chapter_bridge": hook,
        "reward_setup": required_payoffs or ["the promised consequence is prepared"],
        "reward_payoff": required_payoffs or ["the chapter pays a local consequence"],
        "conflict_escalation": ["resistance", "choice", "irreversible cost"],
        "chapter_intent": candidate.get("chapter_intent"),
        "arc_schedule": list(candidate.get("arc_schedule") or ()),
        "setups": list(candidate.get("setups") or ()),
        "payoffs": list(candidate.get("payoffs") or ()),
        "character_participation": list(candidate.get("character_participation") or ()),
        "knowledge_boundaries": list(candidate.get("knowledge_boundaries") or ()),
        "disclosures": list(candidate.get("disclosures") or ()),
        "required_state_transitions": list(
            candidate.get("required_state_transitions") or ()
        ),
        "reader_experience": dict(candidate.get("reader_experience") or {}),
        "scene_plan": list(candidate.get("scene_plan") or ()),
        "expected_exit_state": dict(candidate.get("expected_exit_state") or {}),
        "narrative_segment_ref": dict(candidate.get("narrative_segment_ref") or {}),
        "narrative_architecture_version": str(
            candidate.get("narrative_architecture_version") or ""
        ),
    }


def story_planning_generation_definition(
    *,
    application_build_id: str,
    commit_sha: str,
    definition_version: str = STORY_PLANNING_GENERATION_VERSION,
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
        "name": STORY_PLANNING_GENERATION_DEFINITION,
        "definition_version": definition_version,
        "family": "story_planning_runtime",
        "enabled": True,
        "definition_status": "implemented_validation_pending",
        "command_schema_version": "story-planning-generation-command-v1",
        "result_schema_version": "story-planning-generation-result-v1",
        "command_schema": schema,
        "result_schema": {"type": "object"},
        "input_contract": schema,
        "output_contract": {
            "asset_type": "planning_generation_candidate",
            "output_key": "story_planning.candidate",
        },
        "handler_key": STORY_PLANNING_GENERATION_HANDLER,
        "handler_contract_version": "story-planning-generation-handler-v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "worker",
        "permissions": ["story_planning.authority.execute"],
        "approval_policy": {"required": False},
        "policy": {
            "candidate_only": True,
            **({"realization_source_selectors": "planning-host-source-selectors.v2", "typed_arc_context_projection": "typed-arc-context-projection.v2", "foundation_direction_search": "foundation-generation.v5"} if definition_version == "1.21.0" else {}),
            "story_design_activation_separate": True,
            "semantic_evaluation_operation_separate": True,
            "repair_candidate_asset_input_allowed": True,
            **(
                {"repair_result_evidence_input_allowed": True}
                if definition_version in {"1.15.0", "1.16.0", "1.17.0", "1.18.0", "1.19.0", "1.21.0"}
                else {}
            ),
            "capability_pack_attempt_snapshot_required": True,
            "typed_capability_binding_required": True,
            "agent_runtime_binding_required": False,
            "production_execution_gateway_required": True,
            "high_risk_auto_approval": False,
        },
        "idempotency_scope": "book:story-planning-generation",
        "concurrency_key_template": "book:{book_id}:planning:{logical_key}",
        "retry_policy": {
            "max_attempts": STORY_PLANNING_MAX_ATTEMPTS,
            "dead_letter_on_exhausted": True,
        },
        "timeout_policy": {
            "operation_timeout_seconds": STORY_PLANNING_OPERATION_TIMEOUT_SECONDS
        },
        "cancellation_policy": {"mode": "cancel_active_attempt"},
        "compensation_policy": {
            "supported": False,
            "reason": "append-only candidates and validation evidence",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": ["model.planning"],
        "projection_consumers": [
            "story_design_authority",
            "hierarchical_planning_authority",
        ],
        "migration_owner": "story-planning-runtime",
        "completion_contract": {
            "version": "story-planning-generation-completion-v1",
            "required_asset_selectors": [
                {
                    "selector": "planning_generation_candidate",
                    "output_key": "story_planning.candidate",
                    "role": "primary",
                    "lifecycle": "CANDIDATE",
                    "eligibility": "INELIGIBLE",
                    "governance": "CLEAR",
                }
            ],
            "required_evidence": ["trace", "audit", "cost_when_provider_used"],
            "required_outbox_events": ["story_planning.candidate.materialized"],
        },
    }


def _command_payload(command: StoryPlanningGenerationCommand) -> dict[str, Any]:
    return {
        **({"execution_contract_version": command.execution_contract_version} if command.execution_contract_version != "1.11.0" else {}),
        "project_id": command.project_id,
        "workspace_id": command.workspace_id,
        "book_id": command.book_id,
        "actor_id": command.actor_id,
        "generator_operation_name": command.generator_operation_name,
        "logical_key": command.logical_key,
        "input_versions": dict(command.input_versions),
        "idempotency_key": command.idempotency_key,
        "trace_id": command.trace_id,
        "correlation_id": command.correlation_id,
        "parent_version_id": command.parent_version_id,
        "arc_scope_volume_plan_version_ids": list(
            command.arc_scope_volume_plan_version_ids
        ),
        "related_arc_plan_version_ids": list(command.related_arc_plan_version_ids),
        "dependent_arc_plan_version_ids": list(command.dependent_arc_plan_version_ids),
        "change_evidence_version_ids": list(command.change_evidence_version_ids),
        "governance_action_version_ids": list(command.governance_action_version_ids),
        "repair_of_candidate_id": command.repair_of_candidate_id,
        **({"runtime_continuation_id": command.runtime_continuation_id} if command.runtime_continuation_id else {}),
        **({"repair_of_operation_id": command.repair_of_operation_id, "repair_result_asset_version_id": command.repair_result_asset_version_id, "repair_result_diagnostic": dict(command.repair_result_diagnostic or {})} if command.repair_of_operation_id else {}),
        "repair_reason": command.repair_reason,
        "repair_number": command.repair_number,
        "auto_approve_low_risk": command.auto_approve_low_risk,
        **({"routing_bootstrap_authorization_id": command.routing_bootstrap_authorization_id} if command.routing_bootstrap_authorization_id else {}),
        "parent_agent_session_operation_id": (
            command.parent_agent_session_operation_id
        ),
        "arc_working_set": dict(command.arc_working_set or {}),
        "narrative_search_id": command.narrative_search_id,
        "narrative_search_branch_key": command.narrative_search_branch_key,
        "narrative_search_parent_state_asset_version_id": (
            command.narrative_search_parent_state_asset_version_id
        ),
        "narrative_search_accepted_through_chapter": (
            command.narrative_search_accepted_through_chapter
        ),
        "narrative_search_strategy_directive": (
            command.narrative_search_strategy_directive
        ),
        "narrative_search_planning_horizon": dict(
            command.narrative_search_planning_horizon or {}
        ),
        "narrative_search_desired_transformation": dict(
            command.narrative_search_desired_transformation or {}
        ),
        "narrative_search_hard_constraints": list(
            command.narrative_search_hard_constraints
        ),
        "narrative_realization": dict(command.narrative_realization or {}),
        "opening_execution_binding": dict(command.opening_execution_binding or {}),
        **({"world_preparation_request": dict(command.world_preparation_request)} if command.world_preparation_request else {}),
        **({"edition_execution": dict(command.edition_execution)} if command.edition_execution else {}),
    }


def _command_from_payload(payload: dict[str, Any]) -> StoryPlanningGenerationCommand:
    return StoryPlanningGenerationCommand(
        execution_contract_version=str(payload.get("execution_contract_version") or "1.11.0"),
        world_preparation_request=dict(payload.get("world_preparation_request") or {}) or None,
        edition_execution=dict(payload.get("edition_execution") or {}) or None,
        project_id=str(payload.get("project_id") or ""),
        workspace_id=str(payload.get("workspace_id") or ""),
        book_id=str(payload.get("book_id") or ""),
        actor_id=str(payload.get("actor_id") or ""),
        generator_operation_name=str(payload.get("generator_operation_name") or ""),
        logical_key=str(payload.get("logical_key") or ""),
        input_versions=dict(payload.get("input_versions") or {}),
        idempotency_key=str(payload.get("idempotency_key") or ""),
        trace_id=str(payload.get("trace_id") or ""),
        correlation_id=str(payload.get("correlation_id") or ""),
        parent_version_id=str(payload.get("parent_version_id") or ""),
        arc_scope_volume_plan_version_ids=tuple(
            str(item) for item in payload.get("arc_scope_volume_plan_version_ids") or ()
        ),
        related_arc_plan_version_ids=tuple(
            str(item) for item in payload.get("related_arc_plan_version_ids") or ()
        ),
        dependent_arc_plan_version_ids=tuple(
            str(item) for item in payload.get("dependent_arc_plan_version_ids") or ()
        ),
        change_evidence_version_ids=tuple(
            str(item) for item in payload.get("change_evidence_version_ids") or ()
        ),
        governance_action_version_ids=tuple(
            str(item) for item in payload.get("governance_action_version_ids") or ()
        ),
        repair_of_candidate_id=str(payload.get("repair_of_candidate_id") or ""),
        runtime_continuation_id=str(payload.get("runtime_continuation_id") or ""),
        repair_of_operation_id=str(payload.get("repair_of_operation_id") or ""),
        repair_result_asset_version_id=str(payload.get("repair_result_asset_version_id") or ""),
        repair_result_diagnostic=dict(payload.get("repair_result_diagnostic") or {}) or None,
        repair_reason=str(payload.get("repair_reason") or ""),
        repair_number=int(payload.get("repair_number") or 0),
        auto_approve_low_risk=bool(payload.get("auto_approve_low_risk", False)),
        routing_bootstrap_authorization_id=str(payload.get("routing_bootstrap_authorization_id") or ""),
        parent_agent_session_operation_id=str(
            payload.get("parent_agent_session_operation_id") or ""
        ),
        arc_working_set=dict(payload.get("arc_working_set") or {}) or None,
        narrative_search_id=str(payload.get("narrative_search_id") or ""),
        narrative_search_branch_key=str(
            payload.get("narrative_search_branch_key") or ""
        ),
        narrative_search_parent_state_asset_version_id=str(
            payload.get("narrative_search_parent_state_asset_version_id") or ""
        ),
        narrative_search_accepted_through_chapter=int(
            payload.get("narrative_search_accepted_through_chapter") or 0
        ),
        narrative_search_strategy_directive=str(
            payload.get("narrative_search_strategy_directive") or ""
        ),
        narrative_search_planning_horizon=(
            dict(payload.get("narrative_search_planning_horizon") or {}) or None
        ),
        narrative_search_desired_transformation=(
            dict(payload.get("narrative_search_desired_transformation") or {}) or None
        ),
        narrative_search_hard_constraints=tuple(
            str(item) for item in payload.get("narrative_search_hard_constraints") or ()
        ),
        narrative_realization=(
            dict(payload.get("narrative_realization") or {}) or None
        ),
        opening_execution_binding=(
            dict(payload.get("opening_execution_binding") or {}) or None
        ),
    )


def _replay_generation_input_snapshot(
    resolved: list[dict[str, str]], frozen: Any, frozen_hash: str,
) -> list[dict[str, str]]:
    fields = {"role", "asset_version_id", "asset_type", "content_hash"}
    if not isinstance(frozen, list) or canonical_hash(frozen) != frozen_hash:
        raise KernelError(
            "PLANNING_GENERATION_INPUT_SNAPSHOT_INVALID",
            "frozen Planning Generation input snapshot is invalid",
        )
    indexes = []
    for items in (resolved, frozen):
        by_role = {}
        for item in items:
            if (
                not isinstance(item, dict) or set(item) != fields
                or any(not isinstance(value, str) or not value for value in item.values())
                or item["role"] in by_role
            ):
                raise KernelError(
                    "PLANNING_GENERATION_INPUT_SNAPSHOT_INVALID",
                    "Planning Generation inputs require unique, complete role evidence",
                )
            by_role[item["role"]] = item
        indexes.append(by_role)
    if indexes[0] != indexes[1]:
        raise KernelError(
            "PLANNING_GENERATION_INPUT_SNAPSHOT_DRIFT",
            "result repair inputs differ from its frozen parent Planning Generation",
        )
    return [dict(item) for item in frozen]


def _authority_role_versions(
    command: StoryPlanningGenerationCommand,
) -> dict[str, str]:
    roles = {
        **dict(command.input_versions),
        **{
            f"arc_scope_volume:{index}": asset_version_id
            for index, asset_version_id in enumerate(
                command.arc_scope_volume_plan_version_ids, start=1
            )
        },
        **{
            f"related_arc:{index}": asset_version_id
            for index, asset_version_id in enumerate(
                command.related_arc_plan_version_ids, start=1
            )
        },
        **{
            f"dependent_arc:{index}": asset_version_id
            for index, asset_version_id in enumerate(
                command.dependent_arc_plan_version_ids, start=1
            )
        },
        **{
            f"narrative_governance_action:{index}": asset_version_id
            for index, asset_version_id in enumerate(
                command.governance_action_version_ids, start=1
            )
        },
    }
    parent_state = command.narrative_search_parent_state_asset_version_id
    if parent_state and parent_state not in roles.values():
        roles["narrative_search_parent_state"] = parent_state
    return roles


def _validate_narrative_search_horizon(
    command: StoryPlanningGenerationCommand, content: dict[str, Any]
) -> None:
    if (
        command.generator_operation_name == "book_plan.generate"
        and command.narrative_search_id
    ):
        target = int(
            dict(command.narrative_search_planning_horizon or {}).get("target_chapters")
            or 0
        )
        if target <= 0:
            return
        if (
            int((content.get("length_strategy") or {}).get("target_chapters") or 0)
            != target
        ):
            raise KernelError(
                "NARRATIVE_SEARCH_BOOK_TARGET_MISMATCH",
                "Book candidate must exactly match the frozen Production Profile chapter target",
            )
        try:
            skeleton, _ = canonical_book_volume_allocation(content)
        except ValueError as exc:
            raise KernelError(
                "NARRATIVE_SEARCH_BOOK_PORTFOLIO_MISMATCH",
                "Book candidate Volume skeleton cannot form the frozen chapter portfolio",
            ) from exc
        raw_topology = dict(command.narrative_search_planning_horizon or {}).get(
            "opening_topology_budget"
        )
        if raw_topology is not None and not isinstance(raw_topology, Mapping):
            raise KernelError(
                "NARRATIVE_SEARCH_BOOK_TOPOLOGY_DRIFT",
                "Book candidate topology budget must be an immutable object",
            )
        topology = dict(raw_topology or {})
        if topology:
            from novel_forge.modules.book_authority.opening_workflow import BookOpeningTopologyBudget
            try:
                BookOpeningTopologyBudget.from_mapping(topology).require_volume_count(len(skeleton))
            except (TypeError, ValueError) as exc:
                raise KernelError("NARRATIVE_SEARCH_BOOK_TOPOLOGY_DRIFT", "Book candidate differs from frozen Opening workload") from exc
        return
    chapter_range = command.narrative_search_chapter_range
    if chapter_range is None:
        return
    start, end = chapter_range
    if command.generator_operation_name == "volume_plan.generate":
        if content.get("chapter_range") != [start, end]:
            raise KernelError(
                "NARRATIVE_SEARCH_VOLUME_RANGE_MISMATCH",
                "Volume candidate must exactly match its frozen Book portfolio range",
            )
        return
    expected = list(range(start, end + 1))
    candidate_range = content.get("chapter_range")
    matrix = content.get("chapter_function_matrix")
    events = content.get("narrative_event_chain")
    matrix_chapters = (
        [item.get("chapter_number") for item in matrix if isinstance(item, dict)]
        if isinstance(matrix, list)
        else []
    )
    event_chapters = (
        [item.get("chapter_number") for item in events if isinstance(item, dict)]
        if isinstance(events, list)
        else []
    )
    if (
        candidate_range != [start, end]
        or matrix_chapters != expected
        or any(
            not isinstance(item, int) or isinstance(item, bool)
            for item in event_chapters
        )
        or set(event_chapters) != set(expected)
    ):
        raise KernelError(
            "NARRATIVE_SEARCH_CHAPTER_GROUP_RANGE_MISMATCH",
            "ChapterGroup candidate, function matrix, and event chain must exactly cover the frozen Search window",
        )


def _validate_chapter_schedule_binding(
    content: dict[str, Any], schedule_row: dict[str, Any]
) -> None:
    if any(
        canonical_hash(schedule_row.get(field)) != canonical_hash(content.get(field))
        for field in CHAPTER_SCHEDULE_FIELDS
    ):
        raise KernelError(
            "CHAPTER_SCHEDULE_BINDING_DRIFT",
            "ChapterPlan scheduling fields must exactly match the frozen ChapterGroup row",
        )
    scheduled_reader = schedule_row.get("reader_experience")
    chapter_reader = content.get("reader_experience")
    if not isinstance(scheduled_reader, dict) or not isinstance(chapter_reader, dict):
        raise KernelError(
            "CHAPTER_SCHEDULE_BINDING_DRIFT",
            "ChapterPlan and Scheduling require typed Reader Experience targets",
        )
    if any(
        canonical_hash(scheduled_reader.get(field))
        != canonical_hash(chapter_reader.get(field))
        for field in CHAPTER_READER_SCHEDULE_FIELDS
    ):
        raise KernelError(
            "CHAPTER_SCHEDULE_BINDING_DRIFT",
            "ChapterPlan Reader Experience must preserve its frozen scheduled targets",
        )


def _validate_frozen_arc_references(
    command: StoryPlanningGenerationCommand, content: dict[str, Any]
) -> None:
    if command.generator_operation_name == "arc_plan.generate":
        frozen = {
            command.logical_key,
            *command.related_arc_plan_version_ids,
            *command.dependent_arc_plan_version_ids,
        }
        for relation in content.get("arc_relations") or ():
            if not isinstance(relation, dict):
                continue
            source = str(relation.get("source_arc_ref") or "")
            target = str(relation.get("target_arc_ref") or "")
            if (
                source not in frozen
                or target not in frozen
                or command.logical_key not in {source, target}
            ):
                raise KernelError(
                    "PLANNING_ARC_RELATION_SCOPE_INVALID",
                    "Arc Graph relations must connect the candidate Arc to its frozen Arc portfolio",
                )
        return
    if command.generator_operation_name not in {
        "chapter_group_plan.generate",
        "chapter_plan.generate",
    }:
        return
    frozen = {
        str(command.input_versions["arc_plans"]),
        *command.related_arc_plan_version_ids,
    }
    if command.arc_working_set:
        selected = {
            str(item.get("arc_plan_version_id") or "")
            for item in command.arc_working_set.get("selected_contributions") or ()
            if isinstance(item, dict)
        }
        if selected != frozen:
            raise KernelError(
                "PLANNING_ARC_WORKING_SET_DRIFT",
                "Planning output Arc portfolio differs from the frozen Working Set",
            )
    references: list[str] = []
    if command.generator_operation_name == "chapter_group_plan.generate":
        chapter_range = content.get("chapter_range")
        accepted_through = command.narrative_search_accepted_through_chapter
        if accepted_through > 0 and (
            not isinstance(chapter_range, list)
            or len(chapter_range) != 2
            or int(chapter_range[0]) <= accepted_through
        ):
            raise KernelError(
                "NARRATIVE_SEARCH_HISTORY_REWRITE_FORBIDDEN",
                "future ChapterGroup replacement must begin after the accepted boundary",
            )
        portfolio = [
            *(str(item) for item in content.get("primary_arc_ids") or ()),
            *(str(item) for item in content.get("secondary_arc_ids") or ()),
        ]
        if len(portfolio) != len(set(portfolio)) or set(portfolio) != frozen:
            raise KernelError(
                "PLANNING_ARC_PORTFOLIO_MISMATCH",
                "Narrative Scheduling must classify every frozen Working Set Arc exactly once",
            )
        references.extend(
            str(item) for item in content.get("required_arc_contributions") or ()
        )
        references.extend(
            str(item.get("arc_plan_version_id") or "")
            for item in content.get("arc_checkpoint_expectations") or ()
            if isinstance(item, dict)
        )
        for row in content.get("chapter_function_matrix") or ():
            if not isinstance(row, dict):
                continue
            references.extend(
                str(item.get("arc_plan_version_id") or "")
                for item in row.get("arc_cadence") or ()
                if isinstance(item, dict)
            )
            references.extend(
                str(item.get("arc_plan_version_id") or item.get("arc_id") or "")
                for item in row.get("required_arc_contributions") or ()
                if isinstance(item, dict)
            )
        event_arc_ids = {
            str(arc_id)
            for event in content.get("narrative_event_chain") or ()
            if isinstance(event, dict)
            for arc_id in event.get("arc_contributions") or ()
            if str(arc_id)
        }
        required_event_arcs = {
            str(arc) for arc in content.get("required_arc_contributions") or ()
        } | {
            str(item.get("arc_plan_version_id") or "")
            for row in content.get("chapter_function_matrix") or ()
            for item in row.get("arc_cadence") or ()
            if item.get("action") != "HOLD"
        }
        invalid_scope = (not required_event_arcs <= event_arc_ids <= frozen) if command.execution_contract_version == "1.21.0" else event_arc_ids != frozen
        if invalid_scope:
            raise KernelError(
                "NARRATIVE_REALIZATION_ARC_SCOPE_INVALID",
                "causal realization events must cover only and all frozen Working Set Arcs",
            )
    else:
        if dict(content.get("narrative_realization_slice") or {}) != dict(
            command.narrative_realization or {}
        ):
            raise KernelError(
                "CHAPTER_NARRATIVE_REALIZATION_DRIFT",
                "ChapterPlan changed the exact Frozen Narrative Realization slice",
            )
        schedule_arcs = {
            str(item.get("arc_plan_version_id") or "")
            for item in content.get("arc_schedule") or ()
            if isinstance(item, dict)
        }
        contribution_arcs = {
            str(item.get("arc_plan_version_id") or item.get("arc_id") or "")
            for item in content.get("required_arc_contributions") or ()
            if isinstance(item, dict)
        }
        scene_arcs = {
            str(item)
            for scene in content.get("scene_plan") or ()
            if isinstance(scene, dict)
            for item in scene.get("arc_progress") or ()
            if str(item)
        }
        if command.arc_working_set and (
            schedule_arcs != frozen
            or contribution_arcs != frozen
            or scene_arcs != frozen
        ):
            raise KernelError(
                "PLANNING_ARC_COMPOSITION_INCOMPLETE",
                "Chapter composition must cover every frozen Working Set Arc in schedule, contributions, and Scenes",
            )
        if command.arc_working_set:
            expected_roles = {
                str(item.get("arc_plan_version_id") or ""): str(item.get("role") or "")
                for item in command.arc_working_set.get("selected_contributions") or ()
                if isinstance(item, dict)
            }
            actual_roles = {
                str(item.get("arc_plan_version_id") or ""): str(item.get("role") or "")
                for item in content.get("arc_schedule") or ()
                if isinstance(item, dict)
            }
            if actual_roles != expected_roles:
                raise KernelError(
                    "PLANNING_ARC_CONTRIBUTION_ROLE_DRIFT",
                    "Chapter Arc roles must match the governed Working Set",
                )
        references.extend(
            str(item.get("arc_plan_version_id") or "")
            for item in content.get("arc_schedule") or ()
            if isinstance(item, dict)
        )
        references.extend(
            str(item.get("arc_plan_version_id") or item.get("arc_id") or "")
            for item in content.get("required_arc_contributions") or ()
            if isinstance(item, dict)
        )
        for scene in content.get("scene_plan") or ():
            if isinstance(scene, dict):
                references.extend(str(item) for item in scene.get("arc_progress") or ())
    if not references or any(not item or item not in frozen for item in references):
        raise KernelError(
            "PLANNING_ARC_REFERENCE_INVALID",
            "Scheduling or Chapter design references an Arc outside its frozen portfolio",
        )


__all__ = [
    "CHAPTER_PLAN_PROJECTION_DEFINITION",
    "STORY_PLANNING_EVALUATION_DEFINITION",
    "STORY_PLANNING_EVALUATION_HANDLER",
    "STORY_PLANNING_EVALUATION_VERSION",
    "STORY_PLANNING_GENERATION_DEFINITION",
    "STORY_PLANNING_GENERATION_HANDLER",
    "STORY_PLANNING_GENERATION_VERSION",
    "StoryPlanningGenerationApplication",
    "StoryPlanningGenerationHandlerRegistry",
    "chapter_plan_projection_definition",
    "story_planning_generation_definition",
]


def _canonical_admission_assets(assets: list[dict[str, str]]) -> list[dict[str, str]]:
    by_id: dict[str, dict[str, str]] = {}
    for asset in assets:
        identity = asset.get("asset_version_id")
        if not identity or not asset.get("content_hash") or (identity in by_id and by_id[identity] != asset):
            raise KernelError("PLANNING_GENERATION_ADMISSION_SNAPSHOT_INVALID", "Planning roles sharing an AssetVersion must agree on its exact content identity")
        by_id.setdefault(identity, dict(asset))
    return list(by_id.values())
