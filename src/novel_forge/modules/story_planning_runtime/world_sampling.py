from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.routing_bootstrap import PLANNING_BOOTSTRAP_SOURCE_VERSIONS, WORLD_SAMPLE_TASKS, authorization_hash, bootstrap_command_hash
from novel_forge.storage.authority_asset_store import AuthorityAssetDocument, AuthorityAssetDocumentRepository
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .domain import FrozenPlanningInput
from .world_preparation import PlanningProviderStage, PlanningWorldPreparation


WORLD_SAMPLE_VERSION = "1.0.0"
WORLD_REFERENCE_SAMPLE_VERSION = "1.1.0"
WORLD_SAMPLE_WORKFLOW = "world_provider_sampling@1.0.0"
WORLD_SAMPLE_SCOPE = "book:world-provider-sample"
WORLD_ACTOR_SAMPLE_STAGES = frozenset(stage for stage in WORLD_SAMPLE_TASKS if stage.startswith("world_candidates.actor_"))
WORLD_SAMPLE_STAGES = frozenset(WORLD_SAMPLE_TASKS)


@dataclass(frozen=True, slots=True)
class WorldProviderSampleCommand:
    project_id: str
    book_id: str
    actor_id: str
    source_operation_id: str
    stage: str
    authorization_id: str
    idempotency_key: str
    predecessor_operation_id: str = ""
    reference_evaluation: dict[str, Any] | None = None
    generation_sample: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class FrozenWorldSample:
    command_payload: dict[str, Any]
    inputs: tuple[FrozenPlanningInput, ...]
    input_documents: tuple[AuthorityAssetDocument, ...]
    context: AuthorityAssetDocument
    source: AuthorityAssetDocument
    stage: PlanningProviderStage
    generation_sample: dict[str, Any] | None = None
    derived_context: dict[str, Any] | None = None

    @property
    def definition_version(self) -> str:
        return WORLD_REFERENCE_SAMPLE_VERSION if self.generation_sample else WORLD_SAMPLE_VERSION

    @property
    def workflow_ref(self) -> str:
        return "world_provider_sampling@" + self.definition_version

    @property
    def pack_suffix(self) -> str:
        return ".world_reference_sampling" if self.generation_sample else ".world_sampling"


def require_world_sample_source(database_url: str, *, project_id: str, book_id: str,
                                source_operation_id: str, stage: str,
                                generation_sample: dict[str, str] | None = None) -> FrozenWorldSample:
    with AuthorityUnitOfWork(database_url) as uow:
        return _require_world_sample_source(uow.cursor, project_id=project_id, book_id=book_id,
            source_operation_id=source_operation_id, stage=stage, generation_sample=generation_sample)


def _require_world_sample_source(cursor: Any, *, project_id: str, book_id: str,
                                source_operation_id: str, stage: str,
                                generation_sample: dict[str, str] | None = None) -> FrozenWorldSample:
    if stage not in WORLD_SAMPLE_STAGES:
        raise KernelError("WORLD_SAMPLE_TASK_UNSUPPORTED", "World sampling requires one native World Provider stage")
    if generation_sample is not None and stage != "world_candidates.evaluate":
        raise KernelError("WORLD_SAMPLE_TASK_UNSUPPORTED", "only reference evaluation may consume a generator sample")
    cursor.execute("""SELECT operation.definition_name,operation.definition_version,
        operation.command_payload->'payload',generation.input_snapshot,generation.input_snapshot_hash,
        operation.input_asset_snapshot
        FROM authority_operation operation JOIN authority_story_planning_generation generation USING(operation_id)
        WHERE operation.project_id=%s AND operation.operation_id=%s AND generation.project_id=operation.project_id
          AND generation.book_id=%s""", [project_id, source_operation_id, book_id])
    row = cursor.fetchone()
    if (not row or row[0] != "story_planning.generate" or row[1] not in PLANNING_BOOTSTRAP_SOURCE_VERSIONS
        or row[2].get("generator_operation_name") != "chapter_plan.generate"
        or not row[2].get("world_preparation_request") or row[2].get("routing_bootstrap_authorization_id")
        or row[2].get("repair_of_candidate_id") or row[2].get("repair_of_operation_id")
        or row[2].get("project_id") != project_id or row[2].get("book_id") != book_id
        or authorization_hash(row[3]) != row[4]):
        raise KernelError("WORLD_SAMPLE_SOURCE_INVALID", "World sample requires the original frozen native ChapterPlan task")
    source_payload, typed_inputs, admitted = row[2], row[3], row[5]
    admitted_versions = {(item["asset_version_id"], item["content_hash"]) for item in admitted}
    if any((item["asset_version_id"], item["content_hash"]) not in admitted_versions for item in typed_inputs):
        raise KernelError("WORLD_SAMPLE_INPUT_DRIFT", "Planning typed inputs differ from the admitted native snapshot")
    query = AuthorityAssetDocumentRepository(cursor)
    context_stage = "world_candidates.generate" if generation_sample is not None else stage
    context = query.require(project_id=project_id, logical_ref=f"world_preparation/context/{source_operation_id}/{context_stage}")
    source = query.require(project_id=project_id, logical_ref=f"world_preparation/{source_operation_id}/source")
    documents = tuple(query.require(project_id=project_id, asset_version_id=item["asset_version_id"]) for item in typed_inputs)
    for binding, document in zip(typed_inputs, documents, strict=True):
        if (document.content_hash != binding["content_hash"] or document.asset_type != binding["asset_type"]
            or authorization_hash(document.content) != document.content_hash):
            raise KernelError("WORLD_SAMPLE_INPUT_DRIFT", "World sampling cannot replace frozen Planning dependencies")
    source_ref = _binding(source)
    selection = dict(context.content.get("narrative_intelligence") or {})
    source_contract = source.content.get("contract") or {}
    if source_contract.get("request") != source_payload["world_preparation_request"]:
        raise KernelError("WORLD_SAMPLE_SOURCE_DRIFT", "World Context must retain its original Book frontier")
    native_documents = [context, source]
    actor_proposals = None
    if source_contract.get("actor_experiment") and stage not in WORLD_ACTOR_SAMPLE_STAGES:
        from novel_forge.modules.worldbuilding.actor_isolation import actor_task, actor_output_payload, validate_actor_output

        actor_proposals = []
        for index, actor_id in enumerate(source_contract["actor_experiment"]["actor_ids"]):
            document = query.require(project_id=project_id, logical_ref=f"world_preparation/{source_operation_id}/actor/{index}")
            stored = document.content["contract"]
            task = actor_task(source_contract, source_ref, actor_id)
            if stored.get("source") != source_ref or validate_actor_output(actor_output_payload(stored["output"], task), task) != stored["output"]:
                raise KernelError("WORLD_SAMPLE_SOURCE_DRIFT", "World judge sample requires original native actor proposals, never experimental actor samples")
            native_documents.append(document)
            actor_proposals.append(stored["output"])
    subject = None
    derived_context = None
    if stage in WORLD_ACTOR_SAMPLE_STAGES:
        from novel_forge.modules.worldbuilding.actor_isolation import actor_task, actor_output_schema, validate_actor_policy
        from novel_forge.modules.worldbuilding.production_planning import WorldProductionPolicy

        actor_policy = validate_actor_policy(source_contract.get("actor_experiment") or {},
            character_ids=source_contract["reality"]["approved_character_ids"], policy=WorldProductionPolicy(**source_contract["policy"]))
        index = int(stage.rsplit("_", 1)[1])
        if index >= len(actor_policy["actor_ids"]):
            raise KernelError("WORLD_SAMPLE_TASK_UNSUPPORTED", "Actor sample stage must exist in the original frozen actor policy")
        task = actor_task(source_contract, source_ref, actor_policy["actor_ids"][index])
        provider_stage = PlanningProviderStage(stage, task, actor_output_schema(task))
    elif stage == "world_candidates.generate":
        provider_stage = PlanningWorldPreparation.generation_stage(source_contract, source_ref, selection, actor_proposals=actor_proposals)
    elif generation_sample is not None:
        from novel_forge.modules.chapter_quality_authority.reference_subject import require_reference_subject
        from .application import _command_from_payload
        from .execution import PostgresPlanningExecutionPreparer

        subject = require_reference_subject(cursor, project_id=project_id, binding=generation_sample,
            allowed_types=frozenset({"world_provider_sample"}))
        if (subject["content"].get("source_operation_id") != source_operation_id
            or subject["content"].get("context") != _binding(context)
            or subject["content"].get("source") != source_ref):
            raise KernelError("WORLD_SAMPLE_SOURCE_DRIFT", "reference sample must retain the original generator Context and source")
        provider_stage = PlanningWorldPreparation.evaluation_stage(source_contract, source_ref,
            {"source": source_ref, "output": subject["content"]["sampled_output"]}, generation_sample, selection, actor_proposals=actor_proposals)
        derived_context = PostgresPlanningExecutionPreparer._world_context_content(
            command=_command_from_payload(source_payload), base=context, stage=provider_stage, source=source)
    else:
        generation = query.require(project_id=project_id, logical_ref=f"world_preparation/{source_operation_id}/generation")
        native_documents.append(generation)
        provider_stage = PlanningWorldPreparation.evaluation_stage(source_contract, source_ref,
            generation.content["contract"], _binding(generation), selection, actor_proposals=actor_proposals)
    context_task = PlanningWorldPreparation.generation_stage(source_contract, source_ref, selection, actor_proposals=actor_proposals).task if subject else provider_stage.task
    if context.content.get("world_preparation") != context_task:
        raise KernelError("WORLD_SAMPLE_CONTEXT_DRIFT", "World task differs from the frozen production role Context")
    for document in native_documents:
        if (document.lifecycle != "ACTIVE" or document.eligibility != "ELIGIBLE" or document.governance != "CLEAR"
            or document.content_hash != authorization_hash(document.content)):
            raise KernelError("WORLD_SAMPLE_CONTEXT_DRIFT", "World sampling requires unchanged governed native evidence")
        cursor.execute("""SELECT 1 FROM authority_operation_output_asset
            WHERE operation_id=%s AND asset_version_id=%s AND content_hash=%s""",
            [source_operation_id, document.asset_version_id, document.content_hash])
        if cursor.fetchone() is None:
            raise KernelError("WORLD_SAMPLE_PROVENANCE_INVALID", "World source and Context must belong to the original native Operation")
    return FrozenWorldSample(source_payload, tuple(FrozenPlanningInput(**item) for item in typed_inputs),
                             documents, context, source, provider_stage, subject, derived_context)


def prepare_world_sample(app: Any, command: WorldProviderSampleCommand, *, principal: Principal) -> dict[str, Any]:
    principal.require("story_planning.authority.execute", command.project_id)
    if principal.principal_type is not PrincipalType.LOCAL_OPERATOR or principal.principal_id != command.actor_id:
        raise PermissionError("World sampling requires its authenticated local operator")
    if any(not isinstance(value, str) or not value.strip() for value in (
        command.project_id, command.book_id, command.source_operation_id, command.authorization_id, command.idempotency_key,
    )) or not isinstance(command.predecessor_operation_id, str):
        raise ValueError("World sampling requires exact task, grant and request identities")
    frozen = require_world_sample_source(app.database_url, project_id=command.project_id, book_id=command.book_id,
                                        source_operation_id=command.source_operation_id, stage=command.stage,
                                        generation_sample=command.generation_sample)
    inputs = [dict(asset_version_id=item.asset_version_id, content_hash=item.content_hash) for item in frozen.inputs]
    for document in (frozen.context, frozen.source):
        if _binding(document) not in inputs:
            inputs.append(_binding(document))
    if command.stage == "world_candidates.evaluate":
        inputs.append(dict(frozen.stage.task["generation_ref"]))
    payload = {
        "project_id": command.project_id, "book_id": command.book_id, "actor_id": command.actor_id,
        "generator_operation_name": command.stage, "logical_key": command.source_operation_id,
        "idempotency_key": command.idempotency_key, "input_versions": inputs,
        "world_sampling": {"source_operation_id": command.source_operation_id,
            "source_command_hash": authorization_hash(frozen.command_payload), "context": _binding(frozen.context),
            "source": _binding(frozen.source), "stage_hash": authorization_hash(dict(frozen.stage.task)),
            "schema_hash": authorization_hash(dict(frozen.stage.output_schema))},
        "world_predecessor_operation_id": command.predecessor_operation_id,
        "routing_bootstrap_authorization_id": command.authorization_id,
    }
    if frozen.generation_sample:
        payload["world_sampling"].update(generation_sample=dict(command.generation_sample),
            base_stage_hash=authorization_hash(frozen.context.content["world_preparation"]),
            derived_context_hash=authorization_hash(frozen.derived_context))
    if command.stage == "world_candidates.evaluate":
        reference = require_world_reference(app.database_url, frozen=frozen, binding=command.reference_evaluation, evaluator_actor_id=command.actor_id)
        payload["reference_evaluation"] = reference["binding"]
    elif command.reference_evaluation is not None:
        raise KernelError("QUALITY_REFERENCE_TASK_UNSUPPORTED", "World generator samples cannot consume reviewer labels")
    producer = world_sample_producer_identity(app.database_url, frozen=frozen, source_operation_id=command.source_operation_id)
    from novel_forge.modules.chapter_quality_authority.generator_reference import generator_reference_contract

    return {"status": "PREPARED_NO_PROVIDER_CALL", "provider_calls": 0,
        "definition_name": "world.provider.sample." + command.stage.rsplit(".", 1)[1],
        "definition_version": frozen.definition_version, "workspace_id": frozen.command_payload["workspace_id"],
        "book_id": command.book_id, "command_payload": payload, "input_assets": inputs,
        "command_hash": bootstrap_command_hash(payload), "input_versions_hash": authorization_hash(inputs),
        "producer_contract": producer, "producer_contract_hash": authorization_hash(producer),
        **({"generator_evaluation_contract": generator_reference_contract(command.stage, authorization_hash(producer))}
           if command.stage in WORLD_ACTOR_SAMPLE_STAGES else {}),
        "required_workflow_ref": frozen.workflow_ref, "production_eligible": False}


def world_sample_producer_identity(database_url: str, *, frozen: FrozenWorldSample, source_operation_id: str) -> dict[str, Any]:
    from novel_forge.modules.chapter_authority.execution_gateway import _materialize_production_codex_prompt
    from novel_forge.modules.production_execution import TargetScope
    from novel_forge.modules.production_execution.cost_routing import producer_contract_identity
    from .application import _command_from_payload
    from .execution import world_schema_evidence_identity

    command = frozen.command_payload
    scope_kind = _command_from_payload(command).planning_scope.value.lower()
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("""SELECT version.content,version.content_hash FROM authority_operation_output_asset output
            JOIN authority_asset_version version USING(asset_version_id) JOIN authority_asset asset ON asset.asset_id=version.asset_id
            WHERE output.operation_id=%s AND asset.project_id=%s AND asset.asset_type='capability_materialization_manifest'
              AND output.content_hash=version.content_hash AND version.content#>>'{contract,stage}'=%s""",
            [source_operation_id, command["project_id"], "world_candidates.generate" if frozen.generation_sample else frozen.stage.name])
        rows = uow.cursor.fetchall()
    producers = {}
    source_schema = PlanningWorldPreparation.generation_stage(frozen.source.content["contract"], _binding(frozen.source),
        frozen.context.content.get("narrative_intelligence") or {}, actor_proposals=frozen.context.content["world_preparation"].get("actor_proposals")).output_schema if frozen.generation_sample else frozen.stage.output_schema
    for content, digest in rows:
        materialization = content.get("contract") or {}
        selected = materialization.get("context_selection") or []
        if (digest != authorization_hash(content) or len(selected) != 1
            or selected[0].get("asset_version_id") != frozen.context.asset_version_id
            or selected[0].get("content_hash") != frozen.context.content_hash
            or materialization.get("output_schema", {}).get("content_hash") != authorization_hash(dict(source_schema))):
            raise KernelError("WORLD_SAMPLE_PRODUCER_DRIFT", "World sample must retain the exact native Prompt, Context and Schema")
        if frozen.generation_sample:
            from copy import deepcopy

            materialization = deepcopy(materialization)
            materialization["stage"] = frozen.stage.name
            materialization["context_selection"][0].update(content=frozen.derived_context,
                content_hash=authorization_hash(frozen.derived_context))
            materialization["output_schema"] = {"ref": frozen.stage.output_schema_ref,
                "content_hash": authorization_hash(dict(frozen.stage.output_schema)), "content": dict(frozen.stage.output_schema)}
        _, prompt_evidence = _materialize_production_codex_prompt(target_scope=TargetScope(
            scope_kind=scope_kind, scope_id=command["logical_key"], project_id=command["project_id"], book_id=command["book_id"]).to_dict(),
            stage=frozen.stage.name, inputs={"world_preparation": dict(frozen.stage.task)}, materialization=materialization)
        producer = producer_contract_identity(prompt_evidence, materialization,
            schema_identity=world_schema_evidence_identity(frozen.stage.output_schema, frozen.stage.output_schema_ref))
        producers[authorization_hash(producer)] = producer
    if len(producers) != 1:
        raise KernelError("WORLD_SAMPLE_PRODUCER_REQUIRED", "World sampling requires one compatible native producer materialization")
    return next(iter(producers.values()))


def _binding(document: AuthorityAssetDocument) -> dict[str, str]:
    return {"asset_version_id": document.asset_version_id, "content_hash": document.content_hash}


def require_world_reference(database_url: str, *, frozen: FrozenWorldSample, binding: Any,
                            evaluator_actor_id: str) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        return _require_world_reference(uow.cursor, frozen=frozen, binding=binding,
            evaluator_actor_id=evaluator_actor_id)


def _require_world_reference(cursor: Any, *, frozen: FrozenWorldSample, binding: Any,
                            evaluator_actor_id: str) -> dict[str, Any]:
    from novel_forge.modules.chapter_quality_authority.reference_sampling import require_adjudicated_reference
    from novel_forge.modules.hierarchical_planning.causal_domain import DIRECTOR_DIMENSIONS

    generation = frozen.stage.task["generation_ref"]
    return require_adjudicated_reference(cursor, project_id=frozen.command_payload["project_id"], binding=binding,
        target_id=generation["asset_version_id"], target_hash=generation["content_hash"],
        generators=[frozen.generation_sample["generation_actor_id"] if frozen.generation_sample else frozen.command_payload["actor_id"]],
        evaluator_actor_id=evaluator_actor_id,
        chapter=int(frozen.command_payload["world_preparation_request"]["accepted_through_chapter"]) + 1,
        expected_dimensions=tuple(f"{item['transition']['transition_id']}:{dimension}"
            for item in frozen.stage.task["generated_portfolio"]["candidates"] for dimension in DIRECTOR_DIMENSIONS),
        allowed_statuses={"PASSED", "FAILED"})


def world_sample_result_review(frozen: FrozenWorldSample, result: dict[str, Any], reference: dict[str, Any] | None) -> dict[str, Any]:
    from novel_forge.modules.worldbuilding.production_planning import WorldProductionPolicy, compile_world_plan, validate_generated_candidates
    from novel_forge.modules.worldbuilding.production_schema import decode_world_generation

    source = frozen.source.content["contract"]
    try:
        policy = WorldProductionPolicy(**source["policy"])
        if frozen.stage.name in WORLD_ACTOR_SAMPLE_STAGES:
            from novel_forge.modules.worldbuilding.actor_isolation import validate_actor_output

            validate_actor_output(result, frozen.stage.task)
        elif frozen.stage.name == "world_candidates.generate":
            if frozen.stage.task.get("actor_proposals"):
                from novel_forge.modules.worldbuilding.actor_isolation import require_actor_judgments

                require_actor_judgments(result, frozen.stage.task["actor_proposals"])
            decoded = decode_world_generation({key: value for key, value in result.items() if key not in {"knowledge_translations", "actor_adjudications"}})
            validate_generated_candidates(decoded, policy)
            from .knowledge_translation import validate_knowledge_translations
            selection = frozen.context.content.get("narrative_intelligence") or {}
            if selection.get("policy_version") == "knowledge-grounded-selection-v2":
                validate_knowledge_translations(result, selection)
        else:
            compile_world_plan(reality=source["reality"], generated=frozen.stage.task["generated_portfolio"], evaluation=result,
                policy=policy, chapter_number=int(source["request"]["accepted_through_chapter"]) + 1, intent_version_id=source["intent_version_id"])
    except (KernelError, TypeError, ValueError, KeyError) as error:
        return {"rule_validation": {"status": "FAILED", "code": getattr(error, "code", type(error).__name__),
                                    "message": str(error)}, "reference_evaluation": None}
    agreement = None
    if reference is not None:
        observed = {f"{entry['transition_id']}:{key}": value * 100
                    for entry in result["evaluations"] for key, value in entry["dimensions"].items()}
        comparisons = [{**label, "observed_score": observed[label["dimension"]],
            "score_in_range": label["score_range"][0] <= observed[label["dimension"]] <= label["score_range"][1]}
            for label in reference["labels"]]
        agreement = {**reference, "schema_version": "world-reference-agreement.v1", "score_scale": "native_0_to_1_times_100",
            "comparisons": comparisons, "score_range_agreement": sum(row["score_in_range"] for row in comparisons) / len(comparisons),
            "calibration_claim_allowed": False, "reader_preference_proven": False}
    return {"rule_validation": {"status": "PASSED"}, "reference_evaluation": agreement}


def require_frozen_world_execution(database_url: str, *, operation_id: str, command: Any,
                                   inputs: tuple[FrozenPlanningInput, ...], provider_stage: Any,
                                   frozen: FrozenWorldSample) -> None:
    from novel_forge.modules.command_kernel.routing_bootstrap import load_bootstrap_authorization
    from .application import _command_payload

    with AuthorityUnitOfWork(database_url) as uow:
        snapshot = load_bootstrap_authorization(uow.cursor, project_id=command.project_id,
                                               operation_id=operation_id, check_expiry=False)
        uow.cursor.execute("SELECT command_payload->'payload' FROM authority_operation WHERE project_id=%s AND operation_id=%s",
                           [command.project_id, operation_id])
        row = uow.cursor.fetchone()
    metadata = (row[0].get("world_sampling") or {}) if row else {}
    if (snapshot is None or not metadata or provider_stage != frozen.stage or inputs != frozen.inputs
        or _command_payload(command) != frozen.command_payload
        or metadata.get("source_command_hash") != authorization_hash(frozen.command_payload)
        or metadata.get("context") != _binding(frozen.context) or metadata.get("source") != _binding(frozen.source)
        or metadata.get("stage_hash") != authorization_hash(dict(frozen.stage.task))
        or metadata.get("schema_hash") != authorization_hash(dict(frozen.stage.output_schema))
        or (frozen.generation_sample is not None and (
            metadata.get("generation_sample") != {key: frozen.generation_sample[key] for key in ("asset_version_id", "content_hash")}
            or metadata.get("derived_context_hash") != authorization_hash(frozen.derived_context)))
        or snapshot["authorization"]["task_type"] != frozen.stage.name):
        raise KernelError("WORLD_SAMPLE_EXECUTION_SCOPE_INVALID", "frozen World execution requires its exact native sample grant and origin")


def world_reference_outcomes(cursor: Any, *, project_id: str, effect_ids: list[str]) -> dict[str, dict[str, Any]]:
    from novel_forge.modules.command_kernel.routing_bootstrap import load_bootstrap_authorization
    from novel_forge.modules.chapter_quality_authority.reference_sampling import reference_label_classes, reference_provider_result
    from novel_forge.modules.hierarchical_planning.causal_domain import DIRECTOR_DIMENSIONS

    if not effect_ids:
        return {}
    cursor.execute("""SELECT effect.external_effect_id,effect.operation_id,attempt.attempt_id,operation.actor_id,
        operation.command_payload->'payload',version.asset_version_id,version.content_hash,version.content
        FROM authority_external_effect effect JOIN authority_operation operation USING(operation_id)
        JOIN authority_operation_output_asset output ON output.operation_id=operation.operation_id AND output.role='primary'
        JOIN authority_asset_version version ON version.asset_version_id=output.asset_version_id AND version.content_hash=output.content_hash
        JOIN authority_asset asset ON asset.asset_id=version.asset_id AND asset.project_id=operation.project_id
        JOIN authority_attempt attempt ON attempt.operation_id=operation.operation_id AND attempt.status='SUCCEEDED'
        WHERE effect.project_id=%s AND effect.external_effect_id=ANY(%s) AND effect.status='SUCCEEDED'
          AND operation.status='SUCCEEDED' AND operation.definition_name='world.provider.sample.evaluate'
          AND asset.asset_type='world_provider_sample' AND version.lifecycle='ACTIVE'
          AND version.eligibility='INELIGIBLE' AND version.governance='CLEAR'
          AND version.content #>> '{execution_evidence,external_receipt_ref}'=effect.external_effect_id
        ORDER BY version.created_at,version.asset_version_id""", [project_id, effect_ids])
    outcomes = {}
    for effect_id, operation_id, attempt_id, actor, payload, asset_id, digest, content in cursor.fetchall():
        stage = "world_candidates.evaluate"
        if (content.get("stage") != stage or digest != authorization_hash(content)
            or content.get("production_eligible") is not False or content.get("routing_eligibility") != "BENCHMARK_ONLY"):
            continue
        try:
            snapshot = load_bootstrap_authorization(cursor, project_id=project_id, operation_id=operation_id, check_expiry=False)
            grant = snapshot["authorization"] if snapshot else {}
            if (grant.get("purpose") != "REFERENCE_EVALUATION" or grant.get("task_type") != stage
                or content.get("authorization_id") != grant.get("authorization_id") or content.get("campaign") != grant.get("campaign")
                or payload.get("generator_operation_name") != stage):
                continue
            provider = reference_provider_result(cursor, project_id=project_id, operation_id=operation_id, attempt_id=attempt_id, stage=stage)
            if not provider["real_model_call"] or provider["result"] != content.get("sampled_output"):
                continue
            metadata = payload["world_sampling"]
            frozen = _require_world_sample_source(cursor, project_id=project_id, book_id=payload["book_id"],
                source_operation_id=metadata["source_operation_id"], stage=stage, generation_sample=metadata.get("generation_sample"))
            if (content.get("source_operation_id") != metadata["source_operation_id"]
                or content.get("source") != _binding(frozen.source) or content.get("context") != _binding(frozen.context)
                or metadata.get("stage_hash") != authorization_hash(dict(frozen.stage.task))
                or content.get("generation_sample") != metadata.get("generation_sample")):
                continue
            reference = _require_world_reference(cursor, frozen=frozen, binding=payload["reference_evaluation"], evaluator_actor_id=actor)
            reviewed = world_sample_result_review(frozen, provider["result"], reference)
            if (reviewed["rule_validation"] != content.get("rule_validation")
                or reviewed["reference_evaluation"] != content.get("reference_evaluation")):
                continue
            classes = reference_label_classes(cursor, project_id=project_id, reference=reference, stage=stage)
            if not classes:
                continue
        except (KernelError, ValueError, TypeError, KeyError):
            continue
        agreed = reviewed["rule_validation"]["status"] == "PASSED" and reviewed["reference_evaluation"] is not None and all(
            item["score_in_range"] for item in reviewed["reference_evaluation"]["comparisons"])
        outcomes[effect_id] = {"accepted": None, "metric": "REFERENCE_AGREEMENT.v1", "reference_agreed": agreed,
            "generator_assessment": {"target_asset_version_id": reference["target_asset_version_id"],
                "target_content_hash": reference["target_content_hash"], "labels": reference["labels"],
                "protocol_version": reference["binding"]["protocol_version"]},
            "reference_label_classes": classes,
            "reference_protocol_hash": authorization_hash({"protocol_version": reference["binding"]["protocol_version"],
                "evaluation_versions": sorted({item["evaluation_version"] for item in reference["labels"]}),
                "dimensions": sorted(DIRECTOR_DIMENSIONS), "agreement_contract": "world-reference-agreement.v1",
                "world_policy": frozen.source.content["contract"]["policy"]}),
            "reference_sample_identity": authorization_hash({"task_type": stage, "generated_portfolio": frozen.stage.task["generated_portfolio"]}),
            "failure_class": "" if agreed else "QUALITY_FAILURE",
            "evidence_refs": ["asset-version:" + asset_id, "asset-version:" + provider["model_call_asset_version_id"],
                *("asset-version:" + item["adjudication_asset_version_id"] for item in reference["labels"])]}
    return outcomes


def actor_sample_outcomes(cursor: Any, *, project_id: str, effect_ids: list[str]) -> dict[str, dict[str, Any]]:
    from novel_forge.modules.authority_handler_runtime.generator_feedback import adjudicated_generator_score
    from novel_forge.modules.chapter_quality_authority.generator_reference import DIRECT_GENERATOR_DIMENSIONS, generator_reference_contract
    from novel_forge.modules.chapter_quality_authority.reference_sampling import (
        reference_label_classes, reference_provider_result, require_adjudicated_reference,
    )
    from novel_forge.modules.chapter_quality_authority.reference_subject import require_reference_subject

    if not effect_ids:
        return {}
    cursor.execute("""SELECT effect.external_effect_id,effect.operation_id,effect.request_payload,
        attempt.attempt_id,version.asset_version_id,version.content_hash,operation.command_payload->'payload'
        FROM authority_external_effect effect JOIN authority_operation operation USING(operation_id)
        JOIN authority_attempt attempt ON attempt.operation_id=operation.operation_id AND attempt.status='SUCCEEDED'
        JOIN authority_operation_output_asset output ON output.operation_id=operation.operation_id AND output.role='primary'
        JOIN authority_asset_version version ON version.asset_version_id=output.asset_version_id AND version.content_hash=output.content_hash
        JOIN authority_asset asset ON asset.asset_id=version.asset_id AND asset.project_id=effect.project_id
        WHERE effect.project_id=%s AND effect.external_effect_id=ANY(%s) AND effect.status='SUCCEEDED'
          AND operation.status='SUCCEEDED' AND asset.asset_type='world_provider_sample'
          AND version.content->>'stage'=ANY(%s)
          AND version.content #>> '{execution_evidence,external_receipt_ref}'=effect.external_effect_id
        ORDER BY version.created_at,version.asset_version_id""", [project_id, effect_ids, sorted(WORLD_ACTOR_SAMPLE_STAGES)])
    outcomes = {}
    for effect_id, operation_id, request, attempt_id, target_id, digest, payload in cursor.fetchall():
        decision = request.get("_production_execution", {}).get("capability_runtime", {}).get("routing_decision", {})
        routed = decision.get("task") or {}
        producer = routed.get("producer_contract_hash")
        if not producer or producer != authorization_hash(routed.get("producer_contract")):
            continue
        try:
            subject = require_reference_subject(cursor, project_id=project_id,
                binding={"asset_version_id": target_id, "content_hash": digest}, allowed_types=frozenset({"world_provider_sample"}))
            content = subject["content"]
            stage = content["stage"]
            if (subject["generation_operation_id"] != operation_id or routed.get("task_type") != stage
                or stage not in WORLD_ACTOR_SAMPLE_STAGES or payload.get("generator_operation_name") != stage):
                continue
            provider = reference_provider_result(cursor, project_id=project_id,
                operation_id=operation_id, attempt_id=attempt_id, stage=stage)
            if not provider["real_model_call"] or provider["result"] != content.get("sampled_output"):
                continue
            metadata = payload["world_sampling"]
            frozen = _require_world_sample_source(cursor, project_id=project_id, book_id=payload["book_id"],
                source_operation_id=metadata["source_operation_id"], stage=stage)
            if (content.get("source_operation_id") != metadata["source_operation_id"]
                or content.get("source") != _binding(frozen.source) or content.get("context") != _binding(frozen.context)
                or metadata.get("stage_hash") != authorization_hash(dict(frozen.stage.task))
                or metadata.get("schema_hash") != authorization_hash(dict(frozen.stage.output_schema))
                or world_sample_result_review(frozen, provider["result"], None)["rule_validation"] != content.get("rule_validation")):
                continue
            contract = generator_reference_contract(stage, producer)
            cursor.execute("""SELECT version.asset_version_id,version.content_hash
                FROM authority_asset_version version JOIN authority_asset asset USING(asset_id)
                WHERE asset.project_id=%s AND asset.asset_type='adjudicated_evaluation'
                  AND version.lifecycle='ACTIVE' AND version.governance='CLEAR'
                  AND version.content->>'subject_asset_version_id'=%s
                  AND version.content->>'protocol_version'=%s AND version.content->>'evaluation_version'=%s
                ORDER BY version.created_at,version.asset_version_id""",
                [project_id, target_id, contract["protocol_version"], contract["evaluation_version"]])
            labels = [{"asset_version_id": row[0], "content_hash": row[1]} for row in cursor.fetchall()]
            reference = require_adjudicated_reference(cursor, project_id=project_id,
                binding={"protocol_version": contract["protocol_version"], "adjudications": labels},
                target_id=target_id, target_hash=digest, generators=[subject["generation_actor_id"]],
                evaluator_actor_id=subject["generation_actor_id"], chapter=int(frozen.stage.task["accepted_through_chapter"]) + 1,
                expected_dimensions=DIRECT_GENERATOR_DIMENSIONS[stage],
                allowed_statuses={"PASSED", "PASSED_WITH_WARNINGS", "FAILED", "BLOCKED", "NEEDS_REVISION"})
            if not reference_label_classes(cursor, project_id=project_id, reference=reference, stage=stage):
                continue
            score = adjudicated_generator_score(reference["labels"])
        except (KernelError, ValueError, TypeError, KeyError):
            continue
        if score is None:
            continue
        if content["rule_validation"]["status"] != "PASSED":
            score = 0.0
        normalized_output = {key: " ".join(value.split()) if isinstance(value, str) else value
            for key, value in provider["result"].items()}
        outcomes[effect_id] = {
            "metric": "INDEPENDENT_GENERATOR_ADJUDICATION.v1", "accepted": None,
            "generator_quality_score": score, "generator_protocol_hash": authorization_hash(contract),
            "generator_risk": decision["policy"]["risk"], "generator_context_tokens": routed["input_tokens"],
            "generator_sample_identity": authorization_hash({"task_type": stage, "output": normalized_output}),
            "generator_assessment": {"target_asset_version_id": target_id, "target_content_hash": digest,
                "labels": reference["labels"], "protocol_version": contract["protocol_version"]},
            "evidence_refs": ["asset-version:" + target_id, "asset-version:" + provider["model_call_asset_version_id"],
                *("asset-version:" + item["asset_version_id"] for item in labels)],
            "assessment_basis": "INDEPENDENT_HUMAN_ADJUDICATION", "sample_promoted": False,
        }
    return outcomes


def world_sample_definitions(*, application_build_id: str, commit_sha: str,
                             reference_samples: bool = False) -> tuple[dict[str, Any], ...]:
    from .application import story_planning_generation_definition

    result = []
    for stage in (["world_candidates.evaluate"] if reference_samples else sorted(WORLD_SAMPLE_STAGES)):
        definition = story_planning_generation_definition(application_build_id=application_build_id, commit_sha=commit_sha)
        name = "world.provider.sample." + stage.rsplit(".", 1)[1]
        definition.update({"name": name, "definition_version": WORLD_REFERENCE_SAMPLE_VERSION if reference_samples else WORLD_SAMPLE_VERSION,
            "handler_key": "novel_forge." + name, "handler_contract_version": "world-provider-sample.v1",
            "idempotency_scope": WORLD_SAMPLE_SCOPE, "concurrency_key_template": "book:{book_id}:world-sample:{logical_key}",
            "retry_policy": {"max_attempts": 1, "dead_letter_on_exhausted": True},
            "output_contract": {"asset_type": "world_provider_sample", "output_key": "world.sample.output"},
            "policy": {"routing_bootstrap_sample": True, "production_eligible": False,
                       "capability_pack_attempt_snapshot_required": True, "production_execution_gateway_required": True},
            "completion_contract": {"version": "world-provider-sample-completion.v1",
                "required_asset_selectors": [{"selector": "world_provider_sample", "output_key": "world.sample.output",
                    "role": "primary", "lifecycle": "ACTIVE", "eligibility": "INELIGIBLE", "governance": "CLEAR"}],
                "required_external_effects": [{"capability": "planning.story_chapter.generate", "allowed_states": ["SUCCEEDED"]}],
                "required_evidence": ["trace", "audit", "cost_when_provider_used"],
                "required_outbox_events": ["world.sample.materialized"]}})
        result.append(definition)
        if reference_samples:
            definition["policy"]["world_reference_sample_input_allowed"] = True
    return tuple(result)


def admit_world_sample(app: Any, command: WorldProviderSampleCommand, *, principal: Principal) -> dict[str, Any]:
    from uuid import uuid4
    from novel_forge.modules.authority_handler_runtime.routing_bootstrap import freeze_bootstrap_authorization
    from novel_forge.modules.command_kernel.operation_graph import GraphCommandContext, register_saga_step, start_saga
    from novel_forge.modules.command_kernel.runtime import OperationTransitionCommand, transition_operation_in_uow
    from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command_in_uow

    prepared = prepare_world_sample(app, command, principal=principal)
    snapshot = freeze_bootstrap_authorization(database_url=app.database_url, command_payload=prepared["command_payload"],
        principal=principal, environment=app.execution_binder.resolver.environment,
        permission="story_planning.authority.execute", idempotency_scope=WORLD_SAMPLE_SCOPE)
    grant = snapshot["authorization"]
    expected_purpose = "REFERENCE_EVALUATION" if command.stage == "world_candidates.evaluate" else "BENCHMARK_CHALLENGER"
    if grant["purpose"] != expected_purpose or not grant.get("campaign"):
        raise KernelError("WORLD_SAMPLE_CAMPAIGN_REQUIRED", "World sampling requires its separate generator or reference campaign grant")
    definition = next(item for item in world_sample_definitions(application_build_id=app.application_build_id, commit_sha=app.commit_sha,
                      reference_samples=command.generation_sample is not None)
                      if item["name"] == prepared["definition_name"])
    payload = {**prepared["command_payload"], "routing_bootstrap_authorization": snapshot}
    trace = "world-sample:" + command.idempotency_key
    with AuthorityUnitOfWork(app.database_url, coordinate_nested=True) as uow:
        uow.repositories.definitions.register(definition)
        identity = authorization_hash([command.project_id, grant["campaign"]["campaign_id"], grant["campaign"]["sample_id"],
                                       grant["candidate_id"], grant["model_revision"]])
        uow.cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", [identity])
        require_world_sample_predecessor(uow.cursor, command=command, payload=payload)
        admitted = admit_command_in_uow(uow, {
            "definition_name": definition["name"], "definition_version": prepared["definition_version"],
            "project_id": command.project_id, "workspace_id": prepared["workspace_id"], "book_id": command.book_id,
            "logical_key": command.source_operation_id, "actor_id": principal.principal_id,
            "idempotency_scope": WORLD_SAMPLE_SCOPE, "idempotency_key": command.idempotency_key,
            "trace_id": trace, "span_id": str(uuid4()), "correlation_id": trace,
            "causation_id": command.predecessor_operation_id or command.source_operation_id,
            "causation_operation_id": command.predecessor_operation_id or command.source_operation_id,
            "input": {"project_id": command.project_id, "input_asset_version_ids": [item["asset_version_id"] for item in prepared["input_assets"]],
                      "payload": payload}, "input_assets": prepared["input_assets"],
        }, context=AdmissionContext(actor_id=principal.principal_id, permissions=principal.permissions,
            available_handlers=app.registry.available_handler_keys, application_build_id=app.application_build_id, commit_sha=app.commit_sha))
        operation_id = str(admitted["operation_id"])
        operation = uow.repositories.attempt_runtime.operation_state(operation_id, command.project_id)
        if operation["status"] == "ADMITTED":
            transition_operation_in_uow(uow, OperationTransitionCommand(operation_id=operation_id, project_id=command.project_id,
                expected_version=operation["version"], expected_status="ADMITTED", target_status="READY", actor_id=principal.principal_id,
                reason="authorized World stage and Context frozen", trace_id=trace, correlation_id=trace, causation_id=command.source_operation_id))
        graph = GraphCommandContext(command.project_id, principal.principal_id, trace, trace)
        saga = start_saga(app.database_url, graph, root_operation_id=operation_id)
        register_saga_step(app.database_url, graph, str(saga["saga_id"]), operation_id, "world_sample", 1, "")
        uow.commit()
    return {"operation_id": operation_id, "replayed": bool(admitted["replayed"]), "production_eligible": False,
            "campaign_id": grant["campaign"]["campaign_id"], "authorization_id": command.authorization_id}


def require_world_sample_predecessor(cursor: Any, *, command: WorldProviderSampleCommand, payload: dict[str, Any]) -> None:
    grant = payload["routing_bootstrap_authorization"]["authorization"]
    cursor.execute("""SELECT operation_id,status,actor_id,idempotency_key,command_payload->'payload'
        FROM authority_operation WHERE project_id=%s
          AND command_payload#>>'{payload,routing_bootstrap_authorization,authorization,campaign,campaign_id}'=%s
          AND command_payload#>>'{payload,routing_bootstrap_authorization,authorization,campaign,sample_id}'=%s
          AND command_payload#>>'{payload,routing_bootstrap_authorization,authorization,candidate_id}'=%s
          AND command_payload#>>'{payload,routing_bootstrap_authorization,authorization,model_revision}'=%s
        ORDER BY created_at,operation_id FOR UPDATE""", [command.project_id, grant["campaign"]["campaign_id"],
            grant["campaign"]["sample_id"], grant["candidate_id"], grant["model_revision"]])
    rows = cursor.fetchall()
    if any(row[3] == command.idempotency_key for row in rows):
        return
    if not rows:
        if command.predecessor_operation_id:
            raise KernelError("WORLD_SAMPLE_PREDECESSOR_INVALID", "predecessor must belong to this native sample arm")
        return
    prior = rows[-1]
    if (prior[0] != command.predecessor_operation_id or prior[2] != command.actor_id
        or any(prior[4].get(key) != payload.get(key) for key in ("world_sampling", "input_versions", "reference_evaluation"))
        or prior[4]["routing_bootstrap_authorization"]["authorization"]["campaign"] != grant["campaign"]):
        raise KernelError("WORLD_SAMPLE_PREDECESSOR_INVALID", "replacement must preserve the latest arm, inputs, labels and actor")
    cursor.execute("SELECT external_effect_id,status FROM authority_external_effect WHERE project_id=%s AND operation_id=%s FOR UPDATE",
                   [command.project_id, prior[0]])
    effects = cursor.fetchall()
    replaceable = not effects
    if len(effects) == 1 and effects[0][1] in {"FAILED_FINAL", "DEAD_LETTER"}:
        cursor.execute("SELECT status FROM authority_external_effect_dispatch WHERE external_effect_id=%s ORDER BY generation FOR UPDATE", [effects[0][0]])
        dispatches = cursor.fetchall()
        replaceable = bool(dispatches) and all(row[0] in {"FAILED_FINAL", "DEAD_LETTER"} for row in dispatches)
    if prior[1] not in {"FAILED_FINAL", "DEAD_LETTER", "CANCELLED"} or not replaceable:
        raise KernelError("WORLD_SAMPLE_PREDECESSOR_NOT_REPLACEABLE", "recover existing success and reconcile unknown outcomes before replacement")


def query_world_sample(database_url: str, *, project_id: str, book_id: str, operation_id: str) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("""SELECT status,command_payload->'payload',causation_operation_id,trace_id FROM authority_operation
            WHERE project_id=%s AND operation_id=%s AND definition_version=ANY(%s)
              AND definition_name=ANY(%s) AND command_payload#>>'{payload,book_id}'=%s""",
            [project_id, operation_id, [WORLD_SAMPLE_VERSION, WORLD_REFERENCE_SAMPLE_VERSION], ["world.provider.sample." + stage.rsplit(".", 1)[1] for stage in sorted(WORLD_SAMPLE_STAGES)], book_id])
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("WORLD_SAMPLE_NOT_FOUND", "World sample is absent from the authorized Project and Book")
        result = dict(zip(("status", "input_snapshot", "causation_operation_id", "trace_id"), row, strict=True))
        uow.cursor.execute("""SELECT output.asset_version_id,output.content_hash,output.output_key,output.role,asset.asset_type,
            version.eligibility,CASE WHEN asset.asset_type='world_provider_sample' THEN version.content ELSE NULL END
            FROM authority_operation_output_asset output JOIN authority_asset_version version USING(asset_version_id)
            JOIN authority_asset asset ON asset.asset_id=version.asset_id WHERE output.operation_id=%s ORDER BY output.created_at,output.output_key""", [operation_id])
        result["outputs"] = [dict(zip(("asset_version_id", "content_hash", "output_key", "role", "asset_type", "eligibility", "sample"), row, strict=True)) for row in uow.cursor.fetchall()]
        uow.cursor.execute("SELECT attempt_id,attempt_number,status,result FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number", [operation_id])
        result["attempts"] = [dict(zip(("attempt_id", "attempt_number", "status", "result"), row, strict=True)) for row in uow.cursor.fetchall()]
        uow.cursor.execute("SELECT external_effect_id,status,capability FROM authority_external_effect WHERE operation_id=%s ORDER BY created_at", [operation_id])
        result["effects"] = [dict(zip(("external_effect_id", "status", "capability"), row, strict=True)) for row in uow.cursor.fetchall()]
    return {**result, "operation_id": operation_id, "production_eligible": False}


def run_world_sample(app: Any, command: WorldProviderSampleCommand, *, principal: Principal) -> dict[str, Any]:
    from novel_forge.modules.content_authority.scheduler import ContentAuthorityScheduler

    admitted = admit_world_sample(app, command, principal=principal)
    error = None
    try:
        ContentAuthorityScheduler(app.database_url, registry=app.registry, worker_id=app.worker_id).run_or_recover(
            operation_id=admitted["operation_id"], project_id=command.project_id)
    except KernelError as failure:
        error = {"code": failure.code, "message": failure.message}
    result = query_world_sample(app.database_url, project_id=command.project_id, book_id=command.book_id,
                               operation_id=admitted["operation_id"])
    return {**result, "replayed": admitted["replayed"], **({"execution_error": error} if error else {})}


def world_sample_routing_lineage(database_url: str, *, project_id: str, operation_id: str) -> tuple[str, ...]:
    from novel_forge.modules.command_kernel.routing_bootstrap import load_bootstrap_authorization

    current = operation_id
    lineage = []
    expected = None
    with AuthorityUnitOfWork(database_url) as uow:
        while current:
            if current in lineage:
                raise KernelError("WORLD_SAMPLE_LINEAGE_INVALID", "World sample recovery lineage cannot cycle")
            grant = load_bootstrap_authorization(uow.cursor, project_id=project_id, operation_id=current, check_expiry=False)
            uow.cursor.execute("SELECT actor_id,command_payload->'payload',causation_operation_id FROM authority_operation WHERE project_id=%s AND operation_id=%s",
                               [project_id, current])
            row = uow.cursor.fetchone()
            if grant is None or row is None or not row[1].get("world_sampling"):
                raise KernelError("WORLD_SAMPLE_LINEAGE_INVALID", "World sample recovery requires its original native campaign arm")
            grant = grant["authorization"]
            identity = {"actor_id": row[0], "world_sampling": row[1]["world_sampling"], "input_versions": row[1]["input_versions"],
                "reference_evaluation": row[1].get("reference_evaluation"), "campaign": grant["campaign"],
                "candidate_id": grant["candidate_id"], "model_revision": grant["model_revision"]}
            if expected is not None and identity != expected:
                raise KernelError("WORLD_SAMPLE_LINEAGE_INVALID", "World sample recovery cannot cross task, labels or model arm")
            expected = identity
            lineage.append(current)
            current = row[1].get("world_predecessor_operation_id") or ""
            if current and row[2] != current:
                raise KernelError("WORLD_SAMPLE_LINEAGE_INVALID", "World sample recovery must retain Kernel causation")
    return tuple(reversed(lineage))


class WorldSampleHandler:
    def __init__(self, binder: Any, database_url: str) -> None:
        self.binder = binder
        self.database_url = database_url

    def execute(self, request: Any) -> Any:
        from dataclasses import asdict
        from novel_forge.modules.authority_handler_runtime import AuthorityHandlerOutput
        from novel_forge.modules.command_kernel.routing_bootstrap import load_bootstrap_authorization
        from novel_forge.modules.production_execution.domain_execution import CandidateKind, DomainExecutionCommand, DomainModelOperation
        from novel_forge.modules.story_design_authority import GENERATOR_CATALOG
        from .application import _command_from_payload

        payload = request.command["payload"]
        metadata = payload["world_sampling"]
        with AuthorityUnitOfWork(self.database_url) as uow:
            snapshot = load_bootstrap_authorization(uow.cursor, project_id=request.project_id,
                operation_id=request.operation_id, check_expiry=False)
        if snapshot is None:
            raise KernelError("WORLD_SAMPLE_AUTHORIZATION_REQUIRED", "World sample requires its frozen grant")
        frozen = require_world_sample_source(self.database_url, project_id=request.project_id, book_id=payload["book_id"],
            source_operation_id=metadata["source_operation_id"], stage=payload["generator_operation_name"],
            generation_sample=metadata.get("generation_sample"))
        reference = require_world_reference(self.database_url, frozen=frozen, binding=payload.get("reference_evaluation"),
            evaluator_actor_id=request.actor_id) if frozen.stage.name == "world_candidates.evaluate" else None
        command = _command_from_payload(frozen.command_payload)
        definition = GENERATOR_CATALOG["chapter_plan.generate"]
        bundle = self.binder.resolver.resolve(operation_id=request.operation_id, attempt_id=request.attempt_id,
            fencing_token=request.fencing_token, worker_id=request.worker_id, command=command,
            inputs=frozen.inputs, definition=definition, world_sample=frozen)
        self.binder._validate_bundle(bundle, operation_id=request.operation_id, attempt_id=request.attempt_id,
            fencing_token=request.fencing_token, command=command, definition=definition)
        executed = bundle.execution_port.execute(DomainExecutionCommand(capability=definition.capability,
            operation=DomainModelOperation.GENERATE, candidate_kind=CandidateKind.GENERATION,
            prompt=frozen.stage.name, context=frozen.stage.task))
        grant = snapshot["authorization"]
        reviewed = world_sample_result_review(frozen, dict(executed.raw_output), reference)
        return AuthorityHandlerOutput(asset_type="world_provider_sample", output_key="world.sample.output", role="primary",
            content={"schema_version": "world-provider-sample.v1", "routing_eligibility": "BENCHMARK_ONLY",
                "production_eligible": False, "stage": frozen.stage.name, "source_operation_id": metadata["source_operation_id"],
                "context": _binding(frozen.context), "source": _binding(frozen.source),
                **({"generation_sample": metadata["generation_sample"],
                    "derived_context_hash": metadata["derived_context_hash"]} if frozen.generation_sample else {}),
                "authorization_id": grant["authorization_id"], "campaign": grant["campaign"],
                "sampled_output": dict(executed.raw_output), "execution_evidence": asdict(executed.evidence), **reviewed},
            qualification_policy="world-provider-sample.v1", eligibility="INELIGIBLE",
            reference_asset_version_ids=tuple(item.asset_version_id for item in request.inputs) + (
                tuple(item["asset_version_id"] for item in reference["binding"]["adjudications"]) if reference is not None else ()),
            evidence={"authority_family": "story_planning", "production_eligible": False})
