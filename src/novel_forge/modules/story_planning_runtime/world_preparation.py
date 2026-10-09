from dataclasses import asdict, dataclass
import json
from typing import Any, Callable, Mapping
from psycopg.types.json import Jsonb

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
    world_transition_payload_schema,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.world_preparation_repositories import (
    WorldPreparationRepository,
)


def require_world_host_revalidation(
    database_url: str, *, command: Any, operation_id: str
) -> dict[str, Any]:
    from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
    from novel_forge.modules.command_kernel.external_effect_runtime import (
        EffectCommandContext,
        read_failed_operation_success,
    )

    query = AuthorityAssetQuery(database_url)
    documents = {
        key: query.require(
            project_id=command.project_id,
            logical_ref=f"world_preparation/{operation_id}/{key}",
        )
        for key in ("source", "generation", "evaluation", "action")
    }
    refs = {
        key: {
            "asset_version_id": doc.asset_version_id,
            "content_hash": doc.content_hash,
        }
        for key, doc in documents.items()
    }
    source, generation, evaluation, action = (
        documents[key].content["contract"]
        for key in ("source", "generation", "evaluation", "action")
    )
    rejected = {
        row.get("rejection", {}).get("code")
        for row in action["world_plan"]["rejected_paths"]
    }
    if (
        command.execution_contract_version != "1.21.0"
        or source["reality"].get("epistemic_contract") != "world-agency.v2"
        or source.get("actor_experiment")
        or source["request"] != dict(command.world_preparation_request)
        or action["world_plan"]["disposition"] != "BLOCKED"
        or "WORLD_PERCEPTION_ACTOR_INVALID" not in rejected
        or any(
            action[key] != refs[key] for key in ("source", "generation", "evaluation")
        )
        or generation["source"] != refs["source"]
        or evaluation["source"] != refs["source"]
        or evaluation["generation"] != refs["generation"]
    ):
        raise KernelError(
            "WORLD_HOST_REVALIDATION_SOURCE_INVALID",
            "host revalidation requires the exact retained first-perception identity failure and frozen World receipts",
        )
    with AuthorityUnitOfWork(database_url) as uow:
        WorldPreparationRepository(uow.cursor).assert_source_current(
            project_id=command.project_id, book_id=command.book_id, frozen=source
        )
    for output in (generation, evaluation):
        receipt = read_failed_operation_success(
            database_url,
            EffectCommandContext(
                operation_id=operation_id,
                project_id=command.project_id,
                actor_id=command.actor_id,
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
            ),
            effect_id=output["evidence"]["external_receipt_ref"],
        )
        if (
            receipt is None
            or receipt["budget_reservation_status"] != "SETTLED"
            or receipt["provider_evidence"].get("result") != output["output"]
        ):
            raise KernelError(
                "WORLD_HOST_REVALIDATION_RECEIPT_UNSETTLED",
                "reuse requires exact succeeded Provider output and settled original usage",
            )
    decoded = decode_world_generation(
        {
            key: value
            for key, value in generation["output"].items()
            if key != "knowledge_translations"
        }, agency=True
    )
    policy = WorldProductionPolicy(**source["policy"])
    PlanningWorldPreparation._validate_references(
        source, validate_generated_candidates(decoded, policy), command
    )
    plan = compile_world_plan(
        reality=source["reality"],
        generated=decoded,
        evaluation=evaluation["output"],
        policy=policy,
        chapter_number=int(source["request"]["accepted_through_chapter"]) + 1,
        intent_version_id=source["intent_version_id"],
    )
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
    plan = apply_preparation_decisions(fresh_plan=plan, decisions=decisions)
    if plan["disposition"] not in {"ELIGIBLE", "PREPARATION_REQUIRED"}:
        raise KernelError(
            "WORLD_HOST_REVALIDATION_UNRESOLVED",
            "host revalidation cannot replace a rejected candidate with NO_OP or DEFER",
        )
    return {
        "contract_version": "world-host-revalidation.v1",
        "source_operation_id": operation_id,
        **refs,
        "plan_digest": plan["plan_digest"],
        "knowledge_selection_digest": generation.get("knowledge_selection_digest", ""),
    }



@dataclass(frozen=True, slots=True)
class PlanningProviderStage:
    name: str
    task: Mapping[str, Any]
    output_schema: Mapping[str, Any]

    @property
    def output_schema_ref(self) -> str:
        version = {"world-actor-task.v2": "v2", "world-actor-task.v3": "v3"}.get(self.task.get("contract_version"), "v1")
        if self.task.get("epistemic_contract") == "world-agency.v2":
            version = "v2"
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
    from .world_optional import continuation_action
    action = continuation_action(query.database_url, command)
    if action is not None:
        return action
    from .schema_recovery import continuation_action as schema_continuation_action
    action = schema_continuation_action(query.database_url, command)
    if action is not None:
        return action
    from types import SimpleNamespace
    preparation = PlanningWorldPreparation(SimpleNamespace(database_url=query.database_url, query=query))
    for prefix in preparation._isolated_world_prefixes(command):
        if preparation._read(command.project_id, f"{prefix}/action") is not None:
            from .schema_recovery import retained_world_action
            action, _ = retained_world_action(query.database_url, command=command,
                source_operation_id=prefix.removeprefix("world_preparation/"))
            return action
    try:
        return query.require(project_id=command.project_id, logical_ref=f"world_preparation/{operation_id}/optional_action")
    except KernelError as error:
        if error.code != "AUTHORITY_ASSET_NOT_FOUND":
            raise
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
        from .schema_recovery import continuation_action as schema_continuation_action
        schema_action = schema_continuation_action(self.preparer.database_url, command)
        if schema_action is not None:
            return schema_action
        from .world_optional import continuation_action, optional_policy, deferred_action
        retained_action = continuation_action(self.preparer.database_url, command)
        if retained_action is not None:
            return retained_action
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
        reuse_prefixes = self._isolated_world_prefixes(command)
        if reuse_prefixes:
            from .schema_recovery import retained_world_action
            for retained_prefix in reuse_prefixes:
                if self._read(command.project_id, f"{retained_prefix}/action") is not None:
                    action, _ = retained_world_action(self.preparer.database_url, command=command,
                        source_operation_id=retained_prefix.removeprefix("world_preparation/"))
                    return action
        prefix = f"world_preparation/{operation_id}"
        repair_source = None
        source_prefix = prefix
        revalidation = None
        if command.runtime_continuation_id:
            from .runtime_continuation import require_binding
            revalidation = require_binding(self.preparer.database_url, command.runtime_continuation_id)["target_runtime"].get("world_host_revalidation")
            if revalidation:
                current = require_world_host_revalidation(self.preparer.database_url, command=command, operation_id=revalidation["source_operation_id"])
                if current != revalidation:
                    raise KernelError("WORLD_HOST_REVALIDATION_DRIFT", "Known-result continuation must retain exact source, receipts and derived plan")
                source_prefix = f"world_preparation/{revalidation['source_operation_id']}"
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
            source_document = self._read(command.project_id, f"{source_prefix}/source")
            if source_document is None:
                for retained_prefix in reuse_prefixes:
                    source_document = self._read(command.project_id, f"{retained_prefix}/source")
                    if source_document is not None:
                        break
        if source_document is None:
            with AuthorityUnitOfWork(self.preparer.database_url) as uow:
                source = WorldPreparationRepository(uow.cursor).require_source(
                    project_id=command.project_id,
                    book_id=command.book_id,
                    request=command.world_preparation_request,
                    contract_version="world-preparation-source.v1"
                    if command.execution_contract_version == "1.12.0"
                    else "world-preparation-source.v2",
                    epistemic_contract="world-agency.v2" if command.execution_contract_version == "1.21.0" else "world-agency.v1",
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
        with AuthorityUnitOfWork(self.preparer.database_url) as uow:
            admission = optional_policy(uow.cursor, project_id=command.project_id, book_id=command.book_id, operation_id=operation_id)
        if admission:
            from novel_forge.modules.production_execution.execution_template import decision_template
            template = decision_template({'task': {'work_id': command.book_id, 'policy_snapshot': admission['policy_snapshot']}})
            if template['world_future_preparation'] == 'DISABLED':
                return self._store(command, operation_id, f'{prefix}/optional_action', 'narrative_governance_action',
                    deferred_action(source=source, source_ref=source_ref, command=command, admission=admission))
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
                    document = self._read_known_isolated_stage(command, reuse_prefixes, f"actor/{index}", source_ref,
                        normalize_output=lambda value: validate_actor_output(value, task))
                if document is None:
                    generated = execute_stage(PlanningProviderStage(ACTOR_STAGES[index], task, actor_output_schema(task)))
                    output = validate_actor_output(generated.raw_output, task)
                    document = self._store(command, operation_id, f"{prefix}/actor/{index}", "world_actor_proposal", {
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
        generation_document = self._read(command.project_id, f"{source_prefix if revalidation else prefix}/generation")
        if generation_document is None:
            generation_document = self._read_known_isolated_stage(command, reuse_prefixes, "generation", source_ref)
        knowledge_selection = dict(knowledge_selection or {})
        from .knowledge_translation import validate_knowledge_translations

        if generation_document is None:
            stage = self.generation_stage(
                source, source_ref, knowledge_selection, actor_proposals=actor_proposals,
                allowed_references=world_plan_references(source, command)
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
        if (revalidation or reuse_prefixes) and generation.get("knowledge_selection_digest", "") != knowledge_selection.get("selection_digest", ""):
            raise KernelError("WORLD_REPAIR_KNOWLEDGE_DRIFT", "Known-result revalidation must retain frozen knowledge selection")
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
            require_actor_judgments(generation["output"], actor_proposals, agency=source["reality"].get("epistemic_contract") == "world-agency.v2")
        decoded = decode_world_generation({
            key: value for key, value in generation["output"].items()
            if key not in {"knowledge_translations", "actor_adjudications"}
        }, agency=source["reality"].get("epistemic_contract") == "world-agency.v2")
        candidates = validate_generated_candidates(decoded, policy)
        self._validate_references(source, candidates, command)
        evaluation_document = self._read(command.project_id, f"{source_prefix if revalidation else prefix}/evaluation")
        if evaluation_document is None:
            evaluation_document = self._read_known_isolated_stage(command, reuse_prefixes, "evaluation", source_ref)
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
        if revalidation and plan["plan_digest"] != revalidation["plan_digest"]:
            raise KernelError("WORLD_HOST_REVALIDATION_DRIFT", "Derived action differs from registered known-result proof")
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
            if admission:
                action = deferred_action(source=source, source_ref=source_ref, command=command, admission=admission,
                    rejected=action_document.content['contract'])
                action['optional_preparation']['retained_rejected_action'] = {
                    'asset_version_id':action_document.asset_version_id, 'content_hash':action_document.content_hash}
                return self._store(command, operation_id, f'{prefix}/optional_action', 'narrative_governance_action', action)
            raise KernelError(
                "WORLD_PREPARATION_RESULT_INVALID",
                f"No legal world path; inspect {action_document.asset_version_id}",
            )
        return action_document

    @classmethod
    def generation_stage(cls, source, source_ref, knowledge_selection, *, actor_proposals=None, allowed_references=None):
        from .knowledge_translation import add_translation_contract

        if source.get("actor_experiment") is not None and not actor_proposals:
            raise KernelError("WORLD_ACTOR_PROPOSAL_REQUIRED", "Actor intervention requires its frozen independent proposals; unified sampling cannot substitute for them")
        task = {**cls._task(source, source_ref, "WORLD_REASONER"), "narrative_intelligence": knowledge_selection}
        if allowed_references is not None:
            task["plan_reference_contract"] = {"version": "world-plan-references.v1", **allowed_references,
                "instruction": "References must belong to these exact selected Arc and accepted obligation lists. Other visible arcs are background, not authority for this task."}
        schema = add_translation_contract(world_generation_schema(
            WorldProductionPolicy(**source["policy"]),
            audience_scoped=source["contract_version"] == "world-preparation-source.v2",
            agency=source["reality"].get("epistemic_contract") == "world-agency.v2",
            **({key: tuple(value) for key, value in allowed_references.items()} if allowed_references is not None else {}),
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
            require_actor_judgments(generation["output"], actor_proposals, agency=source["reality"].get("epistemic_contract") == "world-agency.v2")
        decoded = decode_world_generation({key: value for key, value in generation["output"].items() if key not in {"knowledge_translations", "actor_adjudications"}}, agency=source["reality"].get("epistemic_contract") == "world-agency.v2")
        return PlanningProviderStage(
            "world_candidates.evaluate",
            {**cls._task(source, source_ref, "DIRECTOR"), "generated_portfolio": decoded,
             "generation_ref": generation_ref, "narrative_intelligence": knowledge_selection,
             "knowledge_translations": generation["output"].get("knowledge_translations", []),
             **({"actor_proposals": actor_proposals, "actor_adjudications": generation["output"]["actor_adjudications"]} if actor_proposals else {})},
            world_evaluation_schema(decoded, agency=source["reality"].get("epistemic_contract") == "world-agency.v2"),
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
            **({"epistemic_contract": "world-agency.v2"} if source["reality"].get("epistemic_contract") == "world-agency.v2" else {}),
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
                "version": "world-transition-payload.v1",
                "payload_schema": world_transition_payload_schema(),
                "fields": list(WorldTransition.__dataclass_fields__),
                "schema": world_transition_schema(),
                "state_kinds": [kind.value for kind in NarrativeStateKind],
                "requirement_operators": [
                    operator.value for operator in RequirementOperator
                ],
                "camera": ["ON_CAMERA", "OFF_CAMERA", "UNDERCURRENT"],
                "explanation_status": "UNVERIFIED_CAUSAL_HYPOTHESIS",
                "required_conditions": "All compiled hard predicates and actor epistemic bases remain mandatory regardless of score.",
                "known_character_basis": "Every approved character action needs a nonempty predicate referencing that character's own accepted knowledge or belief. Missing support requires NO_OP/DEFER; Foundation descriptions are not invented knowledge facts.",
                "batch_local_names": "For preparation paths, transition_id is a bare name matching [A-Za-z][A-Za-z0-9_-]{0,63}; only dependency references use local:<name>.",
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
            require_actor_judgments(retained["output"], proposals, agency=source["reality"].get("epistemic_contract") == "world-agency.v2")
        decoded = decode_world_generation(
            {
                key: value
                for key, value in retained["output"].items()
                if key not in {"knowledge_translations", "actor_adjudications"}
            }
        , agency=source["reality"].get("epistemic_contract") == "world-agency.v2")
        candidates = validate_generated_candidates(
            decoded, WorldProductionPolicy(**source["policy"])
        )
        PlanningWorldPreparation._validate_references(source, candidates, command)
        PlanningWorldPreparation._validate_retained_plan(
            query,
            command=command,
            generation=generation,
            source=source_document,
            decoded=decoded,
        )

    @staticmethod
    def _validate_retained_plan(
        query: Any,
        *,
        command: Any,
        generation: Any,
        source: Any,
        decoded: Mapping[str, Any],
    ) -> None:
        from novel_forge.modules.command_kernel.external_effect_runtime import (
            EffectCommandContext,
            read_failed_operation_success,
        )
        from novel_forge.modules.worldbuilding.continuation import (
            decide_preparation,
            apply_preparation_decisions,
        )

        owner = PlanningWorldPreparation._source_operation(
            query.database_url, command.project_id, generation.asset_version_id
        )
        try:
            action = query.require(
                project_id=command.project_id,
                logical_ref=f"world_preparation/{owner}/action",
            )
        except KernelError as error:
            if error.code != "AUTHORITY_ASSET_NOT_FOUND":
                raise
            action = None
        binding = action.content["contract"] if action else None
        if binding and binding["world_plan"]["disposition"] != "BLOCKED":
            return
        try:
            evaluation = query.require(
                project_id=command.project_id,
                logical_ref=f"world_preparation/{owner}/evaluation",
            )
        except KernelError as error:
            if error.code != "AUTHORITY_ASSET_NOT_FOUND":
                raise
            return
        expected_source = {
            "asset_version_id": source.asset_version_id,
            "content_hash": source.content_hash,
        }
        expected_generation = {
            "asset_version_id": generation.asset_version_id,
            "content_hash": generation.content_hash,
        }
        expected_evaluation = {
            "asset_version_id": evaluation.asset_version_id,
            "content_hash": evaluation.content_hash,
        }
        retained = evaluation.content["contract"]
        if (
            (binding is not None and (
                binding["source"] != expected_source
                or binding["generation"] != expected_generation
                or binding["evaluation"] != expected_evaluation
            ))
            or retained["source"] != expected_source
            or retained["generation"] != expected_generation
        ):
            raise KernelError(
                "WORLD_REPAIR_EVALUATION_DRIFT",
                "World causal repair must bind its exact frozen proposal and Director receipt",
            )
        receipt = read_failed_operation_success(
            query.database_url,
            EffectCommandContext(
                operation_id=owner,
                project_id=command.project_id,
                actor_id=command.actor_id,
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
            ),
            effect_id=str(retained["evidence"].get("external_receipt_ref") or ""),
        )
        if (
            receipt is None
            or receipt["provider_evidence"].get("result") != retained["output"]
            or receipt["budget_reservation_status"] != "SETTLED"
        ):
            raise KernelError(
                "WORLD_REPAIR_EVALUATION_UNSETTLED",
                "World causal repair requires verified known Director outcome and settled usage",
            )
        frozen = source.content["contract"]
        chapter = int(frozen["request"]["accepted_through_chapter"]) + 1
        plan = compile_world_plan(
            reality=frozen["reality"],
            generated=decoded,
            evaluation=retained["output"],
            policy=WorldProductionPolicy(**frozen["policy"]),
            chapter_number=chapter,
            intent_version_id=frozen["intent_version_id"],
        )
        if frozen["contract_version"] == "world-preparation-source.v2":
            decisions = [
                decide_preparation(
                    reality=frozen["reality"],
                    origin=item["origin"],
                    accepted_steps=item["accepted_steps"],
                    chapter_number=chapter,
                    intent_version_id=frozen["intent_version_id"],
                )
                for item in frozen.get("preparation_sources", [])
            ]
            plan = apply_preparation_decisions(fresh_plan=plan, decisions=decisions)
        if binding is None:
            return
        require_exact_blocked_plan(plan, binding["world_plan"])
        diagnostic = {
            "action": {
                "asset_version_id": action.asset_version_id,
                "content_hash": action.content_hash,
            },
            "plan_digest": plan["plan_digest"],
            "reason": plan["reason"],
            "candidate_rejections": [
                blocked_candidate_diagnostic(item)
                for item in plan["candidate_futures"]
                if not item["eligible"]
            ],
            "path_rejections": [
                {"path_id": item["path_id"], "rejection": item["rejection"]}
                for item in plan["rejected_paths"]
            ],
        }
        raise KernelError(
            "WORLD_GENERATION_CAUSAL_REJECTED",
            json.dumps(diagnostic, ensure_ascii=False, sort_keys=True),
        )

    def _isolated_world_prefixes(self, command: Any) -> list[str]:
        if not command.runtime_continuation_id:
            return []
        from .runtime_continuation import require_binding
        binding = require_binding(self.preparer.database_url, command.runtime_continuation_id)
        proof = binding["target_runtime"].get("generation_isolation")
        if not proof:
            return []
        with AuthorityUnitOfWork(self.preparer.database_url) as uow:
            uow.cursor.execute("""WITH RECURSIVE ancestors(operation_id) AS (
                SELECT %s::text UNION SELECT link.source_operation_id
                FROM authority_story_planning_runtime_continuation link JOIN ancestors
                  ON link.successor_operation_id=ancestors.operation_id)
                SELECT operation.operation_id FROM ancestors
                JOIN authority_operation operation USING(operation_id)
                JOIN authority_story_planning_generation generation USING(operation_id)
                JOIN authority_story_planning_generation source ON source.operation_id=%s
                WHERE generation.project_id=%s AND generation.workspace_id=%s AND generation.book_id=%s
                  AND generation.input_snapshot_hash=source.input_snapshot_hash
                  AND generation.logical_key=source.logical_key AND generation.generator_operation_name=source.generator_operation_name
                  AND operation.actor_id=%s AND operation.status IN ('FAILED_FINAL','DEAD_LETTER')
                  AND operation.command_payload #> '{payload,world_preparation_request}'=%s
                  AND authority_generation_isolated(%s)
                ORDER BY operation.created_at DESC""", [proof["operation_id"], proof["operation_id"],
                    command.project_id, command.workspace_id, command.book_id, command.actor_id,
                    Jsonb(dict(command.world_preparation_request)), proof["external_effect_id"]])
            rows = uow.cursor.fetchall()
        if not rows or rows[0][0] != proof["operation_id"]:
            raise KernelError("WORLD_ISOLATED_SOURCE_DRIFT", "Reuse requires the exact revoked native task, Book, input versions and World frontier")
        return [f"world_preparation/{row[0]}" for row in rows]

    def _read_known_isolated_stage(self, command: Any, prefixes: list[str], stage: str, source_ref: dict, *, normalize_output=None):
        from novel_forge.modules.command_kernel.external_effect_runtime import EffectCommandContext, read_retained_generation_stage_success
        for prefix in prefixes:
            document = self._read(command.project_id, f"{prefix}/{stage}")
            if document is None:
                continue
            stored = document.content["contract"]
            owner = self._source_operation(self.preparer.database_url, command.project_id, document.asset_version_id)
            receipt = read_retained_generation_stage_success(self.preparer.database_url, EffectCommandContext(
                operation_id=owner, project_id=command.project_id, actor_id=command.actor_id,
                trace_id=command.trace_id, correlation_id=command.correlation_id),
                effect_id=stored["evidence"]["external_receipt_ref"])
            raw = receipt["provider_evidence"].get("result") if receipt else None
            output = normalize_output(raw) if raw is not None and normalize_output else raw
            if (stored["source"] != source_ref or receipt is None or output != stored["output"]):
                raise KernelError("WORLD_ISOLATED_RECEIPT_INVALID", "Retain a completed sibling only with its exact trusted Provider result and source")
            return document
        return None

    @staticmethod
    def retained_action(query: Any, command: Any, *, source_operation_id: str = "") -> Any:
        source_id = source_operation_id or command.repair_of_operation_id
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
                    "SELECT command_payload->'payload'->>'repair_of_operation_id' FROM authority_operation WHERE operation_id=%s AND project_id=%s AND command_payload->'payload'->>'book_id'=%s AND status IN ('FAILED_FINAL','DEAD_LETTER')",
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
        refs = world_plan_references(source, command)
        arcs, obligations = set(refs["arc_refs"]), set(refs["obligation_refs"])
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


def world_plan_references(source, command):
    return {
        'arc_refs': sorted({value for value in (command.input_versions.get('arc_plans'),
            *command.related_arc_plan_version_ids) if value}),
        'obligation_refs': sorted({entry['state']['obligation_id']
            for entry in source['reality']['current_state'].get('narrative_obligation', [])
            if entry['state'].get('obligation_id')}),
    }


def require_exact_blocked_plan(plan: Mapping[str, Any], retained: Mapping[str, Any]) -> None:
    from .domain import canonical_hash

    if canonical_hash(plan) != canonical_hash(retained) or plan.get("disposition") != "BLOCKED":
        raise KernelError("WORLD_REPAIR_CAUSAL_DIAGNOSTIC_DRIFT", "World causal repair must reproduce its immutable JSON hard gate failure")


def blocked_candidate_diagnostic(candidate: Mapping[str, Any]) -> dict[str, Any]:
    transition = candidate.get("transition") or {}
    identifier = candidate.get("transition_id") or transition.get("transition_id")
    if not identifier or (candidate.get("transition_id") and transition.get("transition_id") and candidate["transition_id"] != transition["transition_id"]):
        raise KernelError("WORLD_REPAIR_CAUSAL_DIAGNOSTIC_DRIFT", "Blocked candidate requires one exact native transition identity")
    return {
        "transition_id": identifier,
        "rejection": candidate.get("rejection"),
        **({"unmet_requirements": [dict(item) for item in candidate["requirements"] if not item["satisfied"]]}
           if "requirements" in candidate else {}),
    }
