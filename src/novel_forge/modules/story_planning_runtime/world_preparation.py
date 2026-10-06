from dataclasses import asdict, dataclass
import json
from typing import Any, Callable, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.context_builder.reality_projection import ROLE_STATE_KINDS, project_role_context
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
    world_transition_schema,
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

    @property
    def output_schema_ref(self) -> str:
        version = {"world-actor-task.v2": "v2", "world-actor-task.v3": "v3"}.get(self.task.get("contract_version"), "v1")
        suffix = ":actor-isolation-v1" if self.task.get("actor_proposals") else ""
        return f"schema:{self.name}:{version}{suffix}"

    def __post_init__(self) -> None:
        from novel_forge.modules.worldbuilding.actor_isolation import ACTOR_STAGES
        if self.name not in {"world_candidates.generate", "world_candidates.evaluate", *ACTOR_STAGES}:
            raise KernelError(
                "WORLD_PROVIDER_STAGE_INVALID",
                "only the bounded world preparation stages are admitted",
            )
        from novel_forge.modules.chapter_authority.provider_views import (
            build_provider_task_view,
        )

        projected = build_provider_task_view(
            self.name, {"world_preparation": self.task}
        )
        from novel_forge.modules.chapter_quality_authority.context_views import ConservativeTokenEstimator
        serialized = json.dumps(
            projected, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        estimated_tokens = (
            ConservativeTokenEstimator().estimate(serialized)
            if self.task["policy"].get("version") in {"world-production-policy.v2", "world-production-policy.v3", "world-production-policy.v4"}
            else (len(serialized) + 3) // 4
        )
        if estimated_tokens > self.task["policy"]["context_token_budget"]:
            raise KernelError(
                "WORLD_PROVIDER_CONTEXT_BUDGET_EXCEEDED",
                f"{self.name} requires {estimated_tokens} estimated tokens but its frozen Context budget is {self.task['policy']['context_token_budget']}; resume with an explicitly approved smaller scope or new bounded policy",
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
    try:
        return query.require(
            project_id=command.project_id,
            logical_ref=f"world_preparation/{operation_id}/action",
        )
    except KernelError as error:
        if (
            error.code != "AUTHORITY_ASSET_NOT_FOUND"
            or not command.repair_of_operation_id
        ):
            raise
        return PlanningWorldPreparation.retained_action(query, command)


class PlanningWorldPreparation:
    def __init__(self, preparer: Any) -> None:
        self.preparer = preparer

    def prepare(
        self,
        *,
        operation_id: str,
        command: Any,
        execute_stage: Callable[[PlanningProviderStage], Any],
        knowledge_selection: Mapping[str, Any] | None = None,
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
        repair_source = None
        source_prefix = prefix
        if command.repair_of_operation_id:
            from .result_recovery import require_result_repair_source

            repair_source = require_result_repair_source(
                self.preparer.database_url,
                command=command,
                operation_id=command.repair_of_operation_id,
                source_asset_version_id=command.repair_result_asset_version_id,
            )
            if (
                repair_source["diagnostic"].get("provider_stage")
                != "world_candidates.generate"
            ):
                return self.retained_action(self.preparer.query, command)
            retained = self.preparer.query.require(
                project_id=command.project_id,
                asset_version_id=repair_source["asset_version_id"],
            ).content["contract"]
            source_ref = retained["source"]
            source_document = self.preparer.query.require(
                project_id=command.project_id,
                asset_version_id=source_ref["asset_version_id"],
            )
            if source_document.content_hash != source_ref["content_hash"]:
                raise KernelError(
                    "WORLD_REPAIR_SOURCE_DRIFT",
                    "World result repair must retain its exact source hash",
                )
            source_prefix = f"world_preparation/{self._source_operation(self.preparer.database_url, command.project_id, source_document.asset_version_id)}"
        else:
            source_document = self._read(command.project_id, f"{prefix}/source")
        if source_document is None:
            with AuthorityUnitOfWork(self.preparer.database_url) as uow:
                source = WorldPreparationRepository(uow.cursor).require_source(
                    project_id=command.project_id,
                    book_id=command.book_id,
                    request=command.world_preparation_request,
                    contract_version="world-preparation-source.v1"
                    if command.execution_contract_version == "1.12.0"
                    else "world-preparation-source.v2",
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
        actor_proposals = []
        actor_refs = []
        if source.get("actor_experiment") is not None:
            from novel_forge.modules.worldbuilding.actor_isolation import (
                ACTOR_STAGES, actor_task, actor_output_schema, actor_output_payload, validate_actor_output, validate_actor_policy,
            )
            actor_policy = validate_actor_policy(source["actor_experiment"], character_ids=source["reality"]["approved_character_ids"], policy=policy)
            tasks = [actor_task(source, source_ref, actor_id) for actor_id in actor_policy["actor_ids"]]
            for index, task in enumerate(tasks):
                logical_ref = f"{source_prefix}/actor/{index}"
                document = self._read(command.project_id, logical_ref)
                if document is None:
                    generated = execute_stage(PlanningProviderStage(ACTOR_STAGES[index], task, actor_output_schema(task)))
                    output = validate_actor_output(generated.raw_output, task)
                    document = self._store(command, operation_id, logical_ref, "world_actor_proposal", {
                        "source": source_ref, "output": output, "evidence": asdict(generated.evidence),
                        "authority": "ACTION_PROPOSAL_ONLY", "fact_mutation_allowed": False,
                    })
                stored = document.content["contract"]
                raw = actor_output_payload(stored["output"], task)
                if stored["source"] != source_ref or validate_actor_output(raw, task) != stored["output"]:
                    raise KernelError("WORLD_ACTOR_PROPOSAL_DRIFT", "retry must retain the exact actor private projection and proposal")
                actor_proposals.append(stored["output"])
                actor_refs.append({"asset_version_id": document.asset_version_id, "content_hash": document.content_hash})
        from novel_forge.modules.worldbuilding.continuation import (
            decide_preparation,
            apply_preparation_decisions,
        )

        decisions = [
            decide_preparation(
                reality=source["reality"],
                origin=item["origin"],
                accepted_steps=item["accepted_steps"],
                chapter_number=int(source["request"]["accepted_through_chapter"]) + 1,
                intent_version_id=source["intent_version_id"],
            )
            for item in source.get("preparation_sources", [])
        ]
        generation_document = self._read(command.project_id, f"{prefix}/generation")
        knowledge_selection = dict(knowledge_selection or {})
        from .knowledge_translation import validate_knowledge_translations

        if generation_document is None:
            stage = self.generation_stage(
                source, source_ref, knowledge_selection, actor_proposals=actor_proposals
            )
            if repair_source:
                retained = self.preparer.query.require(
                    project_id=command.project_id,
                    asset_version_id=repair_source["asset_version_id"],
                ).content["contract"]
                if retained.get(
                    "knowledge_selection_digest", ""
                ) != knowledge_selection.get("selection_digest", ""):
                    raise KernelError(
                        "WORLD_REPAIR_KNOWLEDGE_DRIFT",
                        "World repair must retain its frozen knowledge selection",
                    )
                stage = PlanningProviderStage(
                    stage.name,
                    {
                        **stage.task,
                        "result_repair": {
                            "source_result": {
                                "asset_version_id": repair_source["asset_version_id"],
                                "content_hash": repair_source["content_hash"],
                                "raw_result": repair_source["raw_result"],
                            },
                            "diagnostic": repair_source["diagnostic"],
                            "instruction": "Repair only this rejected World proposal using the exact source, typed transition contract and approved identities. It is not accepted fact. Preserve correct intentions; do not invent prerequisites or enlarge scope.",
                        },
                    },
                    stage.output_schema,
                )
            generated = execute_stage(
                stage
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
                    "knowledge_selection_digest": knowledge_selection.get("selection_digest", ""),
                },
            )
        generation = generation_document.content["contract"]
        if generation["source"] != source_ref:
            raise KernelError(
                "WORLD_PREPARATION_RECEIPT_DRIFT",
                "generation belongs to another frozen source",
            )
        if (
            knowledge_selection.get("policy_version")
            == "knowledge-grounded-selection-v2"
        ):
            validate_knowledge_translations(generation["output"], knowledge_selection)
        if actor_proposals:
            from novel_forge.modules.worldbuilding.actor_isolation import require_actor_judgments
            require_actor_judgments(generation["output"], actor_proposals)
        decoded = decode_world_generation({
            key: value for key, value in generation["output"].items()
            if key not in {"knowledge_translations", "actor_adjudications"}
        })
        candidates = validate_generated_candidates(decoded, policy)
        self._validate_references(source, candidates, command)
        evaluation_document = self._read(command.project_id, f"{prefix}/evaluation")
        generation_ref = {
            "asset_version_id": generation_document.asset_version_id,
            "content_hash": generation_document.content_hash,
        }
        if evaluation_document is None:
            evaluated = execute_stage(
                self.evaluation_stage(source, source_ref, generation, generation_ref, knowledge_selection, actor_proposals=actor_proposals)
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
        if source["contract_version"] == "world-preparation-source.v2":
            plan = apply_preparation_decisions(fresh_plan=plan, decisions=decisions)
        action = {
            "contract_version": "world-production-action.v1"
            if source["contract_version"] == "world-preparation-source.v1"
            else "world-production-action.v2",
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
            **({"actor_experiment": source["actor_experiment"], "actor_proposals": actor_refs,
                "actor_intervention": "ISOLATED_ACTORS_AND_WORLD_JUDGE", "creative_benefit_proven": False} if actor_proposals else {}),
        }
        if source.get("actor_experiment", {}).get("execution_contract_version") == "world-scene-execution.v2":
            from novel_forge.modules.worldbuilding.actor_execution import compile_current_actor_steps

            action["execution_contract_version"] = "world-scene-execution.v2"
            action["current_actor_steps"] = compile_current_actor_steps(action, actor_proposals, actor_refs)
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

    @classmethod
    def generation_stage(cls, source, source_ref, knowledge_selection, *, actor_proposals=None):
        from .knowledge_translation import add_translation_contract

        if source.get("actor_experiment") is not None and not actor_proposals:
            raise KernelError("WORLD_ACTOR_PROPOSAL_REQUIRED", "Actor intervention requires its frozen independent proposals; unified sampling cannot substitute for them")
        task = {**cls._task(source, source_ref, "WORLD_REASONER"), "narrative_intelligence": knowledge_selection}
        schema = add_translation_contract(world_generation_schema(
            WorldProductionPolicy(**source["policy"]),
            audience_scoped=source["contract_version"] == "world-preparation-source.v2",
        ), knowledge_selection)
        if actor_proposals:
            from novel_forge.modules.worldbuilding.actor_isolation import actor_judge_schema
            schema = actor_judge_schema(schema, actor_proposals)
            task["actor_proposals"] = actor_proposals
            task["actor_judgment_contract"] = "Adjudicate every exact proposal hash. Accept or reject each action and determine conflicts and consequences. Preserve actor_id and intended action verbatim in an executable transition. Do not replace intentions to satisfy the outline. No preparation branches, new actors or missing adjudications. Director may select or reorder feasible proposals but cannot change them."
            if source.get("provider_projection_version") in {"world-role-delivery.v2", "world-role-delivery.v3"}:
                task["actor_judgment_contract"] += " For every CONTINUE commitment disposition, retain source_event_id in transition cause_refs and obligation_id in candidate obligation_refs. DEFER preserves the accepted commitment; it cannot cancel or fulfill it."
            if source.get("actor_experiment", {}).get("version") == "world-actor-experiment.v2":
                task["actor_judgment_contract"] += " Future intent steps are private proposals, not facts or executable prerequisites. Judge only the selected current action and do not mark intention steps complete. A deferred or abandoned intent with no selected_step_id must be REJECTED and cannot produce a transition."
        return PlanningProviderStage(
            "world_candidates.generate",
            task,
            schema,
        )

    @classmethod
    def evaluation_stage(cls, source, source_ref, generation, generation_ref, knowledge_selection, *, actor_proposals=None):
        if generation["source"] != source_ref:
            raise KernelError("WORLD_PREPARATION_RECEIPT_DRIFT", "evaluation must retain the generation's frozen World source")
        if source.get("actor_experiment") is not None and not actor_proposals:
            raise KernelError("WORLD_ACTOR_PROPOSAL_REQUIRED", "Director requires the frozen actor proposals and their world adjudications")
        if actor_proposals:
            from novel_forge.modules.worldbuilding.actor_isolation import require_actor_judgments
            require_actor_judgments(generation["output"], actor_proposals)
        decoded = decode_world_generation({key: value for key, value in generation["output"].items() if key not in {"knowledge_translations", "actor_adjudications"}})
        return PlanningProviderStage(
            "world_candidates.evaluate",
            {**cls._task(source, source_ref, "DIRECTOR"), "generated_portfolio": decoded,
             "generation_ref": generation_ref, "narrative_intelligence": knowledge_selection,
             "knowledge_translations": generation["output"].get("knowledge_translations", []),
             **({"actor_proposals": actor_proposals, "actor_adjudications": generation["output"]["actor_adjudications"]} if actor_proposals else {})},
            world_evaluation_schema(decoded),
        )

    @staticmethod
    def _task(
        source: Mapping[str, Any], source_ref: Mapping[str, str], role: str
    ) -> dict[str, Any]:
        from novel_forge.modules.context_builder.task_context import world_task_scope

        projection = project_role_context(
            reality=source["reality"],
            role=role,
            token_budget=source["policy"]["context_token_budget"],
            task=world_task_scope(chapter=int(source["reality"]["chapter_number"]) + 1, intent=source["intent"], planning_window=source["planning_window"], world_foundation=source["world_foundation"]) if source.get("provider_projection_version") == "world-role-delivery.v3" else None,
            required_event_ids=tuple(sorted({entry["source_event_id"] for kind, entries in source["reality"]["current_state"].items() if kind in ROLE_STATE_KINDS.get(role, ()) for entry in entries})) if source.get("provider_projection_version") == "world-role-delivery.v2" else (),
        )
        return {
            "contract_version": "world-provider-task.v2" if source.get("provider_projection_version") in {"world-role-delivery.v2", "world-role-delivery.v3"} else "world-provider-task.v1",
            "role": role,
            "source_ref": dict(source_ref),
            "baseline_id": source["reality"]["revision_id"],
            "baseline_kind": source["reality"]["baseline_kind"],
            "accepted_through_chapter": source["reality"]["chapter_number"],
            "context_projection": projection,
            "projection_identity": projection["context_digest"],
            **(
                {
                    "accepted_history": [
                        {
                            "event_id": event["event_id"],
                            "state_kind": event["state_kind"],
                            "entity_key": event["identity"]["entity_key"],
                            "accepted_chapter": event["coordinate"]["source_chapter"],
                            "story_time": event.get("story_time"),
                            "fields": {
                                key: value
                                for key, value in event["mutation"]["payload"].items()
                                if isinstance(value, (str, int, float, bool))
                                and key
                                not in {
                                    "coverage",
                                    "approval_requirement",
                                    "entity_id",
                                    "confidence",
                                    "visibility",
                                }
                            },
                        }
                        for event in source["reality"].get("events", [])
                        if (source.get("provider_projection_version") != "world-role-delivery.v3" or event["event_id"] in {row["source_event_id"] for row in projection["selection"]})
                        and event.get("mutation", {})
                        .get("payload", {})
                        .get("world_transition")
                    ]
                }
                if source["contract_version"] == "world-preparation-source.v2"
                else {}
            ),
            "intent": source["intent"],
            "world_foundation": source["world_foundation"],
            "character_definitions": source["character_definitions"],
            "planning_window": source["planning_window"],
            "policy": source["policy"],
            "world_clock": source["reality"].get("world_clock", {}),
            "approved_entity_ids": source["entity_ids"],
            "foundation_cause_refs": source["reality"]["foundation_cause_refs"],
            **(
                {"disclosure_contract": "world-information-scope.v2"}
                if source["contract_version"] == "world-preparation-source.v2"
                else {}
            ),
            "transition_contract": {
                "fields": list(WorldTransition.__dataclass_fields__),
                "schema": world_transition_schema(),
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
    def _source_operation(database_url: str, project_id: str, asset_version_id: str) -> str:
        with AuthorityUnitOfWork(database_url) as uow:
            uow.cursor.execute(
                "SELECT output.operation_id FROM authority_operation_output_asset output JOIN authority_operation op USING(operation_id) WHERE output.asset_version_id=%s AND op.project_id=%s",
                [asset_version_id, project_id],
            )
            rows = uow.cursor.fetchall()
        if len(rows) != 1:
            raise KernelError(
                "WORLD_REPAIR_SOURCE_AMBIGUOUS",
                "World source must retain one exact native owner",
            )
        return str(rows[0][0])

    @staticmethod
    def validate_retained_generation(
        database_url: str, *, command: Any, generation: Any
    ) -> None:
        from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
        from .knowledge_translation import validate_knowledge_translations

        query = AuthorityAssetQuery(database_url)
        retained = generation.content["contract"]
        source_document = query.require(
            project_id=command.project_id,
            asset_version_id=retained["source"]["asset_version_id"],
        )
        source = source_document.content["contract"]
        if source_document.content_hash != retained["source"]["content_hash"] or source[
            "request"
        ] != dict(command.world_preparation_request or {}):
            raise KernelError(
                "WORLD_REPAIR_SOURCE_DRIFT",
                "retained World result must bind its exact frozen Book frontier",
            )
        with AuthorityUnitOfWork(database_url) as uow:
            WorldPreparationRepository(uow.cursor).assert_source_current(
                project_id=command.project_id, book_id=command.book_id, frozen=source
            )
        source_operation = PlanningWorldPreparation._source_operation(
            database_url, command.project_id, source_document.asset_version_id
        )
        context = query.require(
            project_id=command.project_id,
            logical_ref=f"planning/context_bundles/{source_operation}.json",
        )
        selection = context.content.get("narrative_intelligence") or {}
        if retained.get("knowledge_selection_digest", "") != selection.get(
            "selection_digest", ""
        ):
            raise KernelError(
                "WORLD_REPAIR_KNOWLEDGE_DRIFT",
                "retained World result differs from its exact frozen knowledge selection",
            )
        if selection.get("policy_version") == "knowledge-grounded-selection-v2":
            validate_knowledge_translations(retained["output"], selection)
        if source.get("actor_experiment"):
            from novel_forge.modules.worldbuilding.actor_isolation import (
                require_actor_judgments,
                validate_actor_policy,
            )

            actor_policy = validate_actor_policy(
                source["actor_experiment"],
                character_ids=source["reality"]["approved_character_ids"],
                policy=WorldProductionPolicy(**source["policy"]),
            )
            proposals = [
                query.require(
                    project_id=command.project_id,
                    logical_ref=f"world_preparation/{source_operation}/actor/{index}",
                ).content["contract"]["output"]
                for index in range(len(actor_policy["actor_ids"]))
            ]
            require_actor_judgments(retained["output"], proposals)
        decoded = decode_world_generation(
            {
                key: value
                for key, value in retained["output"].items()
                if key not in {"knowledge_translations", "actor_adjudications"}
            }
        )
        candidates = validate_generated_candidates(
            decoded, WorldProductionPolicy(**source["policy"])
        )
        PlanningWorldPreparation._validate_references(source, candidates, command)

    @staticmethod
    def retained_action(query: Any, command: Any) -> Any:
        source_id = command.repair_of_operation_id
        seen = set()
        while source_id and source_id not in seen and len(seen) < 3:
            seen.add(source_id)
            try:
                action = query.require(
                    project_id=command.project_id,
                    logical_ref=f"world_preparation/{source_id}/action",
                )
            except KernelError as error:
                if error.code != "AUTHORITY_ASSET_NOT_FOUND":
                    raise
                action = None
            if action:
                source_ref = action.content["contract"]["source"]
                source = query.require(
                    project_id=command.project_id,
                    asset_version_id=source_ref["asset_version_id"],
                )
                if source.content_hash != source_ref["content_hash"] or source.content[
                    "contract"
                ]["request"] != dict(command.world_preparation_request):
                    raise KernelError(
                        "WORLD_REPAIR_SOURCE_DRIFT",
                        "Planning result repair must retain its original selected World action",
                    )
                with AuthorityUnitOfWork(query.database_url) as uow:
                    WorldPreparationRepository(uow.cursor).assert_source_current(
                        project_id=command.project_id,
                        book_id=command.book_id,
                        frozen=source.content["contract"],
                    )
                return action
            with AuthorityUnitOfWork(query.database_url) as uow:
                uow.cursor.execute(
                    "SELECT command_payload->'payload'->>'repair_of_operation_id' FROM authority_operation WHERE operation_id=%s AND project_id=%s AND command_payload->'payload'->>'book_id'=%s AND status='FAILED_FINAL'",
                    [source_id, command.project_id, command.book_id],
                )
                row = uow.cursor.fetchone()
            source_id = str(row[0] or "") if row else ""
        raise KernelError(
            "WORLD_REPAIR_SOURCE_MISSING",
            "Planning result repair requires its retained selected World action; no World request was repeated",
        )

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
