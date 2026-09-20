from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.routing_bootstrap import authorization_hash, bootstrap_command_hash
from novel_forge.storage.authority_asset_store import AuthorityAssetDocument, AuthorityAssetQuery
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .domain import FrozenPlanningInput
from .world_preparation import PlanningProviderStage, PlanningWorldPreparation


WORLD_SAMPLE_VERSION = "1.0.0"
WORLD_SAMPLE_WORKFLOW = "world_provider_sampling@1.0.0"
WORLD_SAMPLE_SCOPE = "book:world-provider-sample"
WORLD_SAMPLE_STAGES = {"world_candidates.generate", "world_candidates.evaluate"}


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


@dataclass(frozen=True, slots=True)
class FrozenWorldSample:
    command_payload: dict[str, Any]
    inputs: tuple[FrozenPlanningInput, ...]
    input_documents: tuple[AuthorityAssetDocument, ...]
    context: AuthorityAssetDocument
    source: AuthorityAssetDocument
    stage: PlanningProviderStage


def require_world_sample_source(database_url: str, *, project_id: str, book_id: str,
                                source_operation_id: str, stage: str) -> FrozenWorldSample:
    if stage not in WORLD_SAMPLE_STAGES:
        raise KernelError("WORLD_SAMPLE_TASK_UNSUPPORTED", "World sampling requires one native World Provider stage")
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("""SELECT operation.definition_name,operation.definition_version,
            operation.command_payload->'payload',generation.input_snapshot,generation.input_snapshot_hash,
            operation.input_asset_snapshot
            FROM authority_operation operation JOIN authority_story_planning_generation generation USING(operation_id)
            WHERE operation.project_id=%s AND operation.operation_id=%s AND generation.project_id=operation.project_id
              AND generation.book_id=%s""", [project_id, source_operation_id, book_id])
        row = uow.cursor.fetchone()
        if (not row or row[:2] != ("story_planning.generate", "1.16.0")
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
    query = AuthorityAssetQuery(database_url)
    context = query.require(project_id=project_id, logical_ref=f"world_preparation/context/{source_operation_id}/{stage}")
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
    if stage == "world_candidates.generate":
        provider_stage = PlanningWorldPreparation.generation_stage(source_contract, source_ref, selection)
    else:
        generation = query.require(project_id=project_id, logical_ref=f"world_preparation/{source_operation_id}/generation")
        native_documents.append(generation)
        provider_stage = PlanningWorldPreparation.evaluation_stage(source_contract, source_ref,
            generation.content["contract"], _binding(generation), selection)
    if context.content.get("world_preparation") != provider_stage.task:
        raise KernelError("WORLD_SAMPLE_CONTEXT_DRIFT", "World task differs from the frozen production role Context")
    with AuthorityUnitOfWork(database_url) as uow:
        for document in native_documents:
            if (document.lifecycle != "ACTIVE" or document.eligibility != "ELIGIBLE" or document.governance != "CLEAR"
                or document.content_hash != authorization_hash(document.content)):
                raise KernelError("WORLD_SAMPLE_CONTEXT_DRIFT", "World sampling requires unchanged governed native evidence")
            uow.cursor.execute("""SELECT 1 FROM authority_operation_output_asset
                WHERE operation_id=%s AND asset_version_id=%s AND content_hash=%s""",
                [source_operation_id, document.asset_version_id, document.content_hash])
            if uow.cursor.fetchone() is None:
                raise KernelError("WORLD_SAMPLE_PROVENANCE_INVALID", "World source and Context must belong to the original native Operation")
    return FrozenWorldSample(source_payload, tuple(FrozenPlanningInput(**item) for item in typed_inputs),
                             documents, context, source, provider_stage)


def prepare_world_sample(app: Any, command: WorldProviderSampleCommand, *, principal: Principal) -> dict[str, Any]:
    principal.require("story_planning.authority.execute", command.project_id)
    if principal.principal_type is not PrincipalType.LOCAL_OPERATOR or principal.principal_id != command.actor_id:
        raise PermissionError("World sampling requires its authenticated local operator")
    if any(not isinstance(value, str) or not value.strip() for value in (
        command.project_id, command.book_id, command.source_operation_id, command.authorization_id, command.idempotency_key,
    )) or not isinstance(command.predecessor_operation_id, str):
        raise ValueError("World sampling requires exact task, grant and request identities")
    frozen = require_world_sample_source(app.database_url, project_id=command.project_id, book_id=command.book_id,
                                        source_operation_id=command.source_operation_id, stage=command.stage)
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
    if command.stage == "world_candidates.evaluate":
        reference = require_world_reference(app.database_url, frozen=frozen, binding=command.reference_evaluation, evaluator_actor_id=command.actor_id)
        payload["reference_evaluation"] = reference["binding"]
    elif command.reference_evaluation is not None:
        raise KernelError("QUALITY_REFERENCE_TASK_UNSUPPORTED", "World generator samples cannot consume reviewer labels")
    producer = world_sample_producer_identity(app.database_url, frozen=frozen, source_operation_id=command.source_operation_id)
    return {"status": "PREPARED_NO_PROVIDER_CALL", "provider_calls": 0,
        "definition_name": "world.provider.sample." + command.stage.rsplit(".", 1)[1],
        "definition_version": WORLD_SAMPLE_VERSION, "workspace_id": frozen.command_payload["workspace_id"],
        "book_id": command.book_id, "command_payload": payload, "input_assets": inputs,
        "command_hash": bootstrap_command_hash(payload), "input_versions_hash": authorization_hash(inputs),
        "producer_contract": producer, "producer_contract_hash": authorization_hash(producer),
        "required_workflow_ref": WORLD_SAMPLE_WORKFLOW, "production_eligible": False}


def world_sample_producer_identity(database_url: str, *, frozen: FrozenWorldSample, source_operation_id: str) -> dict[str, Any]:
    from novel_forge.modules.chapter_authority.execution_gateway import _materialize_production_codex_prompt
    from novel_forge.modules.production_execution import TargetScope
    from novel_forge.modules.production_execution.cost_routing import producer_contract_identity
    from .application import _command_from_payload

    command = frozen.command_payload
    scope_kind = _command_from_payload(command).planning_scope.value.lower()
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("""SELECT version.content,version.content_hash FROM authority_operation_output_asset output
            JOIN authority_asset_version version USING(asset_version_id) JOIN authority_asset asset ON asset.asset_id=version.asset_id
            WHERE output.operation_id=%s AND asset.project_id=%s AND asset.asset_type='capability_materialization_manifest'
              AND output.content_hash=version.content_hash AND version.content#>>'{contract,stage}'=%s""",
            [source_operation_id, command["project_id"], frozen.stage.name])
        rows = uow.cursor.fetchall()
    producers = {}
    for content, digest in rows:
        materialization = content.get("contract") or {}
        selected = materialization.get("context_selection") or []
        if (digest != authorization_hash(content) or len(selected) != 1
            or selected[0].get("asset_version_id") != frozen.context.asset_version_id
            or selected[0].get("content_hash") != frozen.context.content_hash
            or materialization.get("output_schema", {}).get("content_hash") != authorization_hash(dict(frozen.stage.output_schema))):
            raise KernelError("WORLD_SAMPLE_PRODUCER_DRIFT", "World sample must retain the exact native Prompt, Context and Schema")
        _, prompt_evidence = _materialize_production_codex_prompt(target_scope=TargetScope(
            scope_kind=scope_kind, scope_id=command["logical_key"], project_id=command["project_id"], book_id=command["book_id"]).to_dict(),
            stage=frozen.stage.name, inputs={"world_preparation": dict(frozen.stage.task)}, materialization=materialization)
        producer = producer_contract_identity(prompt_evidence, materialization)
        producers[authorization_hash(producer)] = producer
    if len(producers) != 1:
        raise KernelError("WORLD_SAMPLE_PRODUCER_REQUIRED", "World sampling requires one compatible native producer materialization")
    return next(iter(producers.values()))


def _binding(document: AuthorityAssetDocument) -> dict[str, str]:
    return {"asset_version_id": document.asset_version_id, "content_hash": document.content_hash}


def require_world_reference(database_url: str, *, frozen: FrozenWorldSample, binding: Any,
                            evaluator_actor_id: str) -> dict[str, Any]:
    from novel_forge.modules.chapter_quality_authority.reference_sampling import require_adjudicated_reference
    from novel_forge.modules.hierarchical_planning.causal_domain import DIRECTOR_DIMENSIONS

    generation = frozen.stage.task["generation_ref"]
    with AuthorityUnitOfWork(database_url) as uow:
        return require_adjudicated_reference(uow.cursor, project_id=frozen.command_payload["project_id"], binding=binding,
            target_id=generation["asset_version_id"], target_hash=generation["content_hash"],
            generators=[frozen.command_payload["actor_id"]], evaluator_actor_id=evaluator_actor_id,
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
        if frozen.stage.name == "world_candidates.generate":
            decoded = decode_world_generation({key: value for key, value in result.items() if key != "knowledge_translations"})
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
        or snapshot["authorization"]["task_type"] != frozen.stage.name):
        raise KernelError("WORLD_SAMPLE_EXECUTION_SCOPE_INVALID", "frozen World execution requires its exact native sample grant and origin")


def world_sample_definitions(*, application_build_id: str, commit_sha: str) -> tuple[dict[str, Any], ...]:
    from .application import story_planning_generation_definition

    result = []
    for stage in sorted(WORLD_SAMPLE_STAGES):
        definition = story_planning_generation_definition(application_build_id=application_build_id, commit_sha=commit_sha)
        name = "world.provider.sample." + stage.rsplit(".", 1)[1]
        definition.update({"name": name, "definition_version": WORLD_SAMPLE_VERSION,
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
    definition = next(item for item in world_sample_definitions(application_build_id=app.application_build_id, commit_sha=app.commit_sha)
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
            "definition_name": definition["name"], "definition_version": WORLD_SAMPLE_VERSION,
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
            WHERE project_id=%s AND operation_id=%s AND definition_version=%s
              AND definition_name=ANY(%s) AND command_payload#>>'{payload,book_id}'=%s""",
            [project_id, operation_id, WORLD_SAMPLE_VERSION, ["world.provider.sample.generate", "world.provider.sample.evaluate"], book_id])
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
            source_operation_id=metadata["source_operation_id"], stage=payload["generator_operation_name"])
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
                "authorization_id": grant["authorization_id"], "campaign": grant["campaign"],
                "sampled_output": dict(executed.raw_output), "execution_evidence": asdict(executed.evidence), **reviewed},
            qualification_policy="world-provider-sample.v1", eligibility="INELIGIBLE",
            reference_asset_version_ids=tuple(item.asset_version_id for item in request.inputs) + (
                tuple(item["asset_version_id"] for item in reference["binding"]["adjudications"]) if reference is not None else ()),
            evidence={"authority_family": "story_planning", "production_eligible": False})
