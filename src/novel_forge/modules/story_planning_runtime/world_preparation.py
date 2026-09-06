from dataclasses import asdict, dataclass
import json
from typing import Any, Callable, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.context_builder.reality_projection import project_role_context
from novel_forge.modules.narrative_state.contracts import NarrativeStateKind
from novel_forge.modules.worldbuilding.dynamics import (
    RequirementOperator,
    WorldTransition,
)
from novel_forge.modules.worldbuilding.production_planning import (
    WorldProductionPolicy,
    compile_world_plan,
    validate_generated_candidates,
)
from novel_forge.modules.worldbuilding.production_schema import (
    decode_world_generation,
    world_evaluation_schema,
    world_generation_schema,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.world_preparation_repositories import (
    WorldPreparationRepository,
)


@dataclass(frozen=True, slots=True)
class PlanningProviderStage:
    name: str
    task: Mapping[str, Any]
    output_schema: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.name not in {"world_candidates.generate", "world_candidates.evaluate"}:
            raise KernelError(
                "WORLD_PROVIDER_STAGE_INVALID",
                "only the two bounded world preparation stages are admitted",
            )
        from novel_forge.modules.chapter_authority.provider_views import (
            build_provider_task_view,
        )

        projected = build_provider_task_view(
            self.name, {"world_preparation": self.task}
        )
        estimated_tokens = (
            len(
                json.dumps(
                    projected, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
            )
            + 3
        ) // 4
        if estimated_tokens > self.task["policy"]["context_token_budget"]:
            raise KernelError(
                "WORLD_PROVIDER_CONTEXT_BUDGET_EXCEEDED",
                "complete world role input exceeds the frozen Context budget; compile a smaller scope",
            )
        object.__setattr__(self, "task", projected["world_preparation"])


def require_world_action(query: Any, *, command: Any, operation_id: str) -> Any:
    if command.repair_of_candidate_id:
        parent = query.require(
            project_id=command.project_id,
            asset_version_id=command.repair_of_candidate_id,
        )
        binding = (parent.content.get("constraint_envelope") or {}).get(
            "world_preparation"
        )
        if not binding:
            raise KernelError(
                "WORLD_REPAIR_SOURCE_MISSING",
                "directed repair must retain the original world action",
            )
        action = query.require(
            project_id=command.project_id, asset_version_id=binding["asset_version_id"]
        )
        if action.content_hash != binding["content_hash"]:
            raise KernelError(
                "WORLD_REPAIR_SOURCE_DRIFT",
                "directed repair cannot replace the selected world batch",
            )
        return action
    return query.require(
        project_id=command.project_id,
        logical_ref=f"world_preparation/{operation_id}/action",
    )


class PlanningWorldPreparation:
    def __init__(self, preparer: Any) -> None:
        self.preparer = preparer

    def prepare(
        self,
        *,
        operation_id: str,
        command: Any,
        execute_stage: Callable[[PlanningProviderStage], Any],
    ) -> Any:
        if command.repair_of_candidate_id:
            action = require_world_action(
                self.preparer.query, command=command, operation_id=operation_id
            )
            source = self.preparer.query.require(
                project_id=command.project_id,
                asset_version_id=action.content["contract"]["source"][
                    "asset_version_id"
                ],
            )
            with AuthorityUnitOfWork(self.preparer.database_url) as uow:
                WorldPreparationRepository(uow.cursor).assert_source_current(
                    project_id=command.project_id,
                    book_id=command.book_id,
                    frozen=source.content["contract"],
                )
            return action
        from novel_forge.storage.book_control_repositories import BookControlRepository

        with AuthorityUnitOfWork(self.preparer.database_url) as uow:
            BookControlRepository(uow.cursor).freeze(
                project_id=command.project_id,
                book_run_id=command.world_preparation_request["book_run_id"],
                chapter_number=int(
                    command.world_preparation_request["accepted_through_chapter"]
                )
                + 1,
                actor_id=command.actor_id,
            )
            uow.commit()
        prefix = f"world_preparation/{operation_id}"
        source_document = self._read(command.project_id, f"{prefix}/source")
        if source_document is None:
            with AuthorityUnitOfWork(self.preparer.database_url) as uow:
                source = WorldPreparationRepository(uow.cursor).require_source(
                    project_id=command.project_id,
                    book_id=command.book_id,
                    request=command.world_preparation_request,
                )
            source_document = self._store(
                command,
                operation_id,
                f"{prefix}/source",
                "world_preparation_source",
                source,
            )
        source = source_document.content["contract"]
        with AuthorityUnitOfWork(self.preparer.database_url) as uow:
            WorldPreparationRepository(uow.cursor).assert_source_current(
                project_id=command.project_id, book_id=command.book_id, frozen=source
            )
        if source["request"] != dict(command.world_preparation_request):
            raise KernelError(
                "WORLD_PREPARATION_REQUEST_DRIFT",
                "retry must preserve the frozen Book frontier",
            )
        source_ref = {
            "asset_version_id": source_document.asset_version_id,
            "content_hash": source_document.content_hash,
        }
        policy = WorldProductionPolicy(**source["policy"])
        generation_document = self._read(command.project_id, f"{prefix}/generation")
        if generation_document is None:
            task = self._task(source, source_ref, "WORLD_REASONER")
            generated = execute_stage(
                PlanningProviderStage(
                    "world_candidates.generate", task, world_generation_schema(policy)
                )
            )
            generation_document = self._store(
                command,
                operation_id,
                f"{prefix}/generation",
                "world_preparation_generation",
                {
                    "source": source_ref,
                    "output": dict(generated.raw_output),
                    "evidence": asdict(generated.evidence),
                },
            )
        generation = generation_document.content["contract"]
        if generation["source"] != source_ref:
            raise KernelError(
                "WORLD_PREPARATION_RECEIPT_DRIFT",
                "generation belongs to another frozen source",
            )
        decoded = decode_world_generation(generation["output"])
        candidates = validate_generated_candidates(decoded, policy)
        self._validate_references(source, candidates, command)
        evaluation_document = self._read(command.project_id, f"{prefix}/evaluation")
        generation_ref = {
            "asset_version_id": generation_document.asset_version_id,
            "content_hash": generation_document.content_hash,
        }
        if evaluation_document is None:
            task = {
                **self._task(source, source_ref, "DIRECTOR"),
                "generated_portfolio": decoded,
                "generation_ref": generation_ref,
            }
            evaluated = execute_stage(
                PlanningProviderStage(
                    "world_candidates.evaluate", task, world_evaluation_schema(decoded)
                )
            )
            evaluation_document = self._store(
                command,
                operation_id,
                f"{prefix}/evaluation",
                "world_preparation_evaluation",
                {
                    "source": source_ref,
                    "generation": generation_ref,
                    "output": dict(evaluated.raw_output),
                    "evidence": asdict(evaluated.evidence),
                },
            )
        evaluation = evaluation_document.content["contract"]
        if (
            evaluation["source"] != source_ref
            or evaluation["generation"] != generation_ref
        ):
            raise KernelError(
                "WORLD_PREPARATION_RECEIPT_DRIFT",
                "Director evaluation must bind the exact generated portfolio",
            )
        plan = compile_world_plan(
            reality=source["reality"],
            generated=decoded,
            evaluation=evaluation["output"],
            policy=policy,
            chapter_number=int(source["request"]["accepted_through_chapter"]) + 1,
            intent_version_id=source["intent_version_id"],
        )
        with AuthorityUnitOfWork(self.preparer.database_url) as uow:
            WorldPreparationRepository(uow.cursor).assert_source_current(
                project_id=command.project_id, book_id=command.book_id, frozen=source
            )
        action = {
            "contract_version": "world-production-action.v1",
            "authority": "PLANNING_PROPOSAL",
            "project_id": command.project_id,
            "book_id": command.book_id,
            "book_run_id": source["request"]["book_run_id"],
            "actor_id": command.actor_id,
            "source": source_ref,
            "generation": generation_ref,
            "evaluation": {
                "asset_version_id": evaluation_document.asset_version_id,
                "content_hash": evaluation_document.content_hash,
            },
            "world_plan": plan,
            "preserve_accepted_history": True,
            "fact_mutation_allowed": False,
        }
        action_document = self._store(
            command,
            operation_id,
            f"{prefix}/action",
            "narrative_governance_action",
            action,
        )
        if plan["disposition"] == "BLOCKED":
            raise KernelError(
                "WORLD_PREPARATION_BLOCKED",
                f"No legal world path; inspect {action_document.asset_version_id}",
            )
        return action_document

    @staticmethod
    def _task(
        source: Mapping[str, Any], source_ref: Mapping[str, str], role: str
    ) -> dict[str, Any]:
        projection = project_role_context(
            reality=source["reality"],
            role=role,
            token_budget=source["policy"]["context_token_budget"],
        )
        return {
            "contract_version": "world-provider-task.v1",
            "role": role,
            "source_ref": dict(source_ref),
            "baseline_id": source["reality"]["revision_id"],
            "baseline_kind": source["reality"]["baseline_kind"],
            "accepted_through_chapter": source["reality"]["chapter_number"],
            "context_projection": projection,
            "projection_identity": projection["context_digest"],
            "intent": source["intent"],
            "world_foundation": source["world_foundation"],
            "character_definitions": source["character_definitions"],
            "planning_window": source["planning_window"],
            "policy": source["policy"],
            "world_clock": source["reality"].get("world_clock", {}),
            "approved_entity_ids": source["entity_ids"],
            "foundation_cause_refs": source["reality"]["foundation_cause_refs"],
            "transition_contract": {
                "fields": list(WorldTransition.__dataclass_fields__),
                "state_kinds": [kind.value for kind in NarrativeStateKind],
                "requirement_operators": [
                    operator.value for operator in RequirementOperator
                ],
                "camera": ["ON_CAMERA", "OFF_CAMERA", "UNDERCURRENT"],
                "explanation_status": "UNVERIFIED_CAUSAL_HYPOTHESIS",
                "required_conditions": "All compiled hard predicates and actor epistemic bases remain mandatory regardless of score.",
            },
            "fact_mutation_allowed": False,
        }

    @staticmethod
    def _validate_references(
        source: Mapping[str, Any], candidates: list[Mapping[str, Any]], command: Any
    ) -> None:
        state = source["reality"]["current_state"]
        actors = set(source["entity_ids"]) | {
            entry["state"]["character_id"]
            for entry in state.get("character_state", [])
            if entry["state"].get("character_id")
        }
        arcs = {
            command.input_versions.get("arc_plans"),
            *command.related_arc_plan_version_ids,
        }
        obligations = {
            entry["state"].get("obligation_id")
            for entry in state.get("narrative_obligation", [])
        }
        for candidate in candidates:
            transitions = [
                candidate["transition"],
                *(
                    step["transition"]
                    for path in candidate["preparation_paths"]
                    for step in path["steps"]
                ),
            ]
            if any(
                transition["actor_id"] not in actors for transition in transitions
            ) or not set(candidate["affected_entities"]).issubset(actors):
                raise KernelError(
                    "WORLD_GENERATION_IDENTITY_UNKNOWN",
                    "generated actors and affected entities must resolve to approved Foundation or accepted Reality",
                )
            if not set(candidate["arc_refs"]).issubset(arcs) or not set(
                candidate["obligation_refs"]
            ).issubset(obligations):
                raise KernelError(
                    "WORLD_GENERATION_PLAN_REFERENCE_UNKNOWN",
                    "world generation cannot invent Arc or obligation authority references",
                )

    def _read(self, project_id: str, logical_ref: str) -> Any:
        try:
            return self.preparer.query.require(
                project_id=project_id, logical_ref=logical_ref
            )
        except KernelError as exc:
            if exc.code != "AUTHORITY_ASSET_NOT_FOUND":
                raise
            return None

    def _store(
        self,
        command: Any,
        operation_id: str,
        logical_ref: str,
        asset_type: str,
        contract: dict[str, Any],
    ) -> Any:
        return self.preparer._ensure_contract(
            operation_id=operation_id,
            project_id=command.project_id,
            logical_ref=logical_ref,
            asset_type=asset_type,
            contract=contract,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
