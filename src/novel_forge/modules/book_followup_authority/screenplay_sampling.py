from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping
from types import SimpleNamespace
from uuid import uuid4

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.authority_handler_runtime import AuthorityHandlerOutput
from novel_forge.modules.authority_handler_runtime.routing_bootstrap import freeze_bootstrap_authorization
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.routing_bootstrap import authorization_hash, bootstrap_command_hash, load_bootstrap_authorization
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command_in_uow
from novel_forge.modules.command_kernel.runtime import OperationTransitionCommand, transition_operation_in_uow
from novel_forge.modules.command_kernel.operation_graph import GraphCommandContext, register_saga_step, start_saga
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .contracts import BOOK_FOLLOWUP_DEFINITION_VERSION
from .screenplay import SCREENPLAY_STAGES, SOURCE_TYPE, validate_candidate, validate_review

SCREENPLAY_SAMPLE_VERSION = "1.0.0"
SCREENPLAY_SAMPLE_SCOPE = "book:screenplay-provider-sample"
SCREENPLAY_SAMPLE_TYPE = "screenplay_provider_sample"
SCREENPLAY_SAMPLE_PROTOCOL = "screenplay-independent-quality.v1"


def sample_definition_name(stage: str) -> str:
    if stage not in SCREENPLAY_STAGES:
        raise ValueError("SCREENPLAY_SAMPLE_STAGE_INVALID")
    return "book.screenplay.sample." + stage.removeprefix("screenplay_")


def sample_workflow(stage: str) -> str:
    sample_definition_name(stage)
    return "book_followup_" + stage + "_sampling@" + SCREENPLAY_SAMPLE_VERSION


def sample_purpose(stage: str) -> str:
    return "REFERENCE_EVALUATION" if stage == "screenplay_review" else "BENCHMARK_CHALLENGER"


@dataclass(frozen=True, slots=True)
class ScreenplaySampleCommand:
    project_id: str
    actor_id: str
    source_operation_id: str
    authorization_id: str
    idempotency_key: str
    stage: str
    upstream_sample: dict[str, str] | None = None
    predecessor_operation_id: str = ""


def screenplay_sample_definition(*, application_build_id: str, commit_sha: str, stage: str) -> dict[str, Any]:
    from .definitions import book_followup_operation_definitions
    name = sample_definition_name(stage)
    definition = deepcopy(next(item for item in book_followup_operation_definitions(
        application_build_id=application_build_id, commit_sha=commit_sha) if item["name"] == stage))
    definition.update(name=name, definition_version=SCREENPLAY_SAMPLE_VERSION,
        handler_key="novel_forge.book_followup_authority." + name,
        command_schema_version=name + ".command.v1", result_schema_version=name + ".result.v1",
        permissions=["book.followup:" + name], idempotency_scope=SCREENPLAY_SAMPLE_SCOPE,
        concurrency_key_template="project:{project_id}:" + name,
        projection_consumers=["independent_screenplay_benchmark"],
        output_contract={**definition["result_schema"], "asset_type": SCREENPLAY_SAMPLE_TYPE,
            "output_key": name, "role": "primary", "auxiliary_asset_types": []},
        policy={**definition["policy"], "routing_bootstrap_sample": True, "production_eligible": False,
            "screenplay_sample_input_allowed": True},
        completion_contract={"version": "screenplay-sample.completion.v1",
            "required_asset_selectors": [{"selector": SCREENPLAY_SAMPLE_TYPE, "output_key": name,
                "role": "primary", "lifecycle": "ACTIVE", "eligibility": "INELIGIBLE", "governance": "CLEAR"}],
            "required_qualifications": [{"decision": "INELIGIBLE"}], "required_evidence": ["trace", "audit"],
            "required_outbox_events": ["book_followup." + name + ".materialized"]})
    return definition


def require_sample(cursor: Any, *, project_id: str, binding: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(binding, Mapping) or set(binding) != {"asset_version_id", "content_hash"}:
        raise KernelError("SCREENPLAY_SAMPLE_INVALID", "Freeze one exact native upstream sample")
    cursor.execute("""SELECT version.content,version.content_hash,operation.operation_id,operation.actor_id,
        operation.definition_name,operation.definition_version,operation.command_payload->'payload'
        FROM authority_asset_version version JOIN authority_asset asset USING(asset_id)
        JOIN authority_operation_output_asset output ON output.asset_version_id=version.asset_version_id
          AND output.content_hash=version.content_hash AND output.role='primary'
        JOIN authority_operation operation ON operation.operation_id=output.operation_id AND operation.project_id=asset.project_id
        WHERE asset.project_id=%s AND version.asset_version_id=%s AND asset.asset_type=%s
          AND version.lifecycle='ACTIVE' AND version.eligibility='INELIGIBLE' AND version.governance='CLEAR'
          AND operation.status='SUCCEEDED'""", [project_id, binding["asset_version_id"], SCREENPLAY_SAMPLE_TYPE])
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise KernelError("SCREENPLAY_SAMPLE_INVALID", "Only a successful immutable native sample may supply this stage")
    content, digest, operation_id, actor_id, name, version, payload = rows[0]
    stage = content.get("stage")
    if (stage not in SCREENPLAY_STAGES or digest != binding["content_hash"] or digest != authorization_hash(content)
        or name != sample_definition_name(stage) or version != SCREENPLAY_SAMPLE_VERSION
        or content.get("production_eligible") is not False or content.get("routing_eligibility") != "BENCHMARK_ONLY"
        or content.get("source_operation_id") != payload.get("logical_key")):
        raise KernelError("SCREENPLAY_SAMPLE_INVALID", "Sample origin, contract or content differs")
    grant = load_bootstrap_authorization(cursor, project_id=project_id, operation_id=operation_id, check_expiry=False)
    if (not grant or grant["authorization"]["purpose"] != sample_purpose(stage)
        or grant["authorization"]["task_type"] != stage or content.get("authorization_id") != grant["authorization"]["authorization_id"]
        or content.get("campaign") != grant["authorization"].get("campaign")):
        raise KernelError("SCREENPLAY_SAMPLE_INVALID", "Sample requires its exact immutable authorization")
    return {**dict(binding), "asset_type": SCREENPLAY_SAMPLE_TYPE, "content": content,
        "generation_operation_id": operation_id, "generation_actor_id": actor_id,
        "producer_contract_hash": grant["authorization"]["producer_contract_hash"]}


def validate_screenplay_sample_origin(cursor: Any, *, project_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    from .screenplay_handler import require_validated_source
    metadata = payload.get("screenplay_sampling") or {}
    stage = payload.get("generator_operation_name")
    sample_definition_name(stage)
    cursor.execute("SELECT definition_name,definition_version,command_payload->'payload',input_asset_snapshot FROM authority_operation WHERE project_id=%s AND operation_id=%s",
        [project_id, metadata.get("source_operation_id")])
    original = cursor.fetchone()
    keys = {"project_id", "generator_operation_name", "logical_key", "idempotency_key", "input_versions",
        "screenplay_sampling", "screenplay_predecessor_operation_id", "routing_bootstrap_authorization_id", "reference_evaluation", "book_run_id"}
    if payload.get("routing_bootstrap_authorization") is not None:
        keys.add("routing_bootstrap_authorization")
    if (not original or original[:2] != ("screenplay_generate", BOOK_FOLLOWUP_DEFINITION_VERSION)
        or len(original[3]) != 1 or metadata.get("source_operation_id") != payload.get("logical_key")
        or metadata.get("source_command_hash") != authorization_hash(original[2])
        or set(metadata) != {"source_operation_id", "source_command_hash", "upstream_sample"}
        or dict(payload) != {**original[2], **{key: payload.get(key) for key in keys}}):
        raise KernelError("SCREENPLAY_SAMPLE_ORIGIN_INVALID", "Sampling retains its frozen formal generate task and exact source")
    binding = original[3][0]
    cursor.execute("SELECT asset.asset_type,version.content,version.content_hash FROM authority_asset_version version JOIN authority_asset asset USING(asset_id) WHERE asset.project_id=%s AND version.asset_version_id=%s AND version.lifecycle='ACTIVE' AND version.eligibility='ELIGIBLE' AND version.governance='CLEAR'",
        [project_id, binding["asset_version_id"]])
    row = cursor.fetchone()
    if not row or row[0] != SOURCE_TYPE or row[2] != binding["content_hash"] or row[2] != authorization_hash(row[1]):
        raise KernelError("SCREENPLAY_SAMPLE_ORIGIN_INVALID", "Adaptation source must remain an exact eligible native contract")
    source = row[1]
    from novel_forge.storage.authority_repositories import AuthorityRepositories
    require_validated_source(SimpleNamespace(cursor=cursor, repositories=AuthorityRepositories(cursor),
        database_url=cursor.connection.info.dsn), project_id=project_id, source=source)
    upstream = metadata["upstream_sample"]
    inputs = [binding, *([upstream] if upstream else [])]
    expected_reference = {**{key: binding[key] for key in ("asset_version_id", "content_hash")}, "protocol_version": SCREENPLAY_SAMPLE_PROTOCOL} if stage == "screenplay_review" else None
    if (payload.get("input_versions") != inputs or payload.get("reference_evaluation") != expected_reference
        or payload.get("source_digest") != source["source_digest"] or payload.get("book_run_id") != source["book_run_id"] or (stage == "screenplay_generate") != (upstream is None)):
        raise KernelError("SCREENPLAY_SAMPLE_ORIGIN_INVALID", "Task, references or exact input chain differs")
    prior = require_sample(cursor, project_id=project_id, binding=upstream) if upstream else None
    candidate = review = None
    round_number = 0
    if prior:
        content = prior["content"]
        if content.get("source_operation_id") != metadata["source_operation_id"] or content.get("source_binding") != binding:
            raise KernelError("SCREENPLAY_SAMPLE_SCOPE_INVALID", "An upstream sample belongs to another frozen source")
        if stage == "screenplay_review" and content["stage"] in {"screenplay_generate", "screenplay_revision"}:
            candidate = content["sampled_output"]
            round_number = content["revision_round"]
        elif stage == "screenplay_revision" and content["stage"] == "screenplay_review" and content["sampled_output"]["verdict"] == "REVISE":
            candidate, review = content["input_candidate"], content["sampled_output"]
            round_number = content["revision_round"] + 1
        else:
            raise KernelError("SCREENPLAY_SAMPLE_STAGE_INVALID", "Review needs a candidate; revision needs an exact REVISE review sample")
        if round_number > source["policy"]["max_revision_rounds"]:
            raise KernelError("SCREENPLAY_REVISION_EXHAUSTED", "Sampling preserves the approved revision bound")
    return {"source": source, "source_binding": binding, "candidate": candidate, "review": review,
        "revision_round": round_number, "upstream": prior}


def prepare_screenplay_sample(app: Any, command: ScreenplaySampleCommand, *, principal: Principal) -> dict[str, Any]:
    principal.require("book.authority.execute", command.project_id)
    principal.require("book.followup:" + sample_definition_name(command.stage), command.project_id)
    if principal.principal_type is not PrincipalType.LOCAL_OPERATOR or principal.principal_id != command.actor_id:
        raise PermissionError("screenplay sampling requires its authenticated local operator")
    if any(not isinstance(value, str) or not value.strip() for value in (
        command.project_id, command.source_operation_id, command.authorization_id, command.idempotency_key)):
        raise ValueError("Screenplay sampling requires exact task, grant and request identities")
    if command.stage not in app.screenplay_model_ports:
        raise KernelError("SCREENPLAY_SAMPLE_PORT_REQUIRED", "Configure the exact native screenplay stage")
    with AuthorityUnitOfWork(app.database_url) as uow:
        uow.cursor.execute("SELECT command_payload->'payload',input_asset_snapshot,workspace_id FROM authority_operation WHERE project_id=%s AND operation_id=%s AND definition_name='screenplay_generate' AND definition_version=%s",
            [command.project_id, command.source_operation_id, BOOK_FOLLOWUP_DEFINITION_VERSION])
        original = uow.cursor.fetchone()
        if not original or len(original[1]) != 1:
            raise KernelError("SCREENPLAY_SAMPLE_ORIGIN_INVALID", "Prepare from an admitted native screenplay generate source")
        binding = original[1][0]
        uow.cursor.execute("SELECT content FROM authority_asset_version WHERE asset_version_id=%s AND content_hash=%s", [binding["asset_version_id"], binding["content_hash"]])
        source_content = uow.cursor.fetchone()
        if not source_content:
            raise KernelError("SCREENPLAY_SAMPLE_ORIGIN_INVALID", "Exact source is unavailable")
        payload = {**original[0], "project_id": command.project_id, "generator_operation_name": command.stage,
            "logical_key": command.source_operation_id, "idempotency_key": command.idempotency_key,
            "book_run_id": source_content[0]["book_run_id"],
            "input_versions": [binding, *([command.upstream_sample] if command.upstream_sample else [])],
            "screenplay_sampling": {"source_operation_id": command.source_operation_id,
                "source_command_hash": authorization_hash(original[0]), "upstream_sample": command.upstream_sample},
            "screenplay_predecessor_operation_id": command.predecessor_operation_id,
            "routing_bootstrap_authorization_id": command.authorization_id,
            "reference_evaluation": {**{key: binding[key] for key in ("asset_version_id", "content_hash")},
                "protocol_version": SCREENPLAY_SAMPLE_PROTOCOL} if command.stage == "screenplay_review" else None}
        frozen = validate_screenplay_sample_origin(uow.cursor, project_id=command.project_id, payload=payload)
    producer = sample_producer_identity(app, command=command, payload=payload, frozen=frozen, workspace_id=original[2])
    from .screenplay_sample_feedback import screenplay_reference_contract
    return {"status": "PREPARED_NO_PROVIDER_CALL", "provider_calls": 0, "production_eligible": False,
        "definition_name": sample_definition_name(command.stage), "definition_version": SCREENPLAY_SAMPLE_VERSION,
        "workspace_id": original[2], "command_payload": payload, "input_assets": payload["input_versions"],
        "command_hash": bootstrap_command_hash(payload), "input_versions_hash": authorization_hash(payload["input_versions"]),
        "producer_contract": producer, "producer_contract_hash": authorization_hash(producer),
        "evaluation_contract": screenplay_reference_contract(command.stage, authorization_hash(producer)),
        "required_workflow_ref": sample_workflow(command.stage)}


def sample_producer_identity(app: Any, *, command: ScreenplaySampleCommand, payload: dict[str, Any], frozen: dict[str, Any], workspace_id: str) -> dict[str, Any]:
    import json
    from novel_forge.modules.capability_pack_authority.runtime import CapabilityPackResolutionRequest, materialize_registered_pack_version
    from novel_forge.modules.chapter_authority.execution_gateway import _materialize_production_codex_prompt, chapter_producer_contract_identity, _stage_tool_permissions
    from .screenplay_sample_execution import projected_sample_context
    from novel_forge.modules.chapter_authority.execution_gateway import PostgresChapterExecutionContractBinder
    stage = command.stage
    binder = app.screenplay_model_ports[stage].capability_binder
    with AuthorityUnitOfWork(app.database_url) as uow:
        uow.cursor.execute("SELECT operation.command_payload->'payload',attempt.attempt_id FROM authority_operation operation JOIN authority_attempt attempt USING(operation_id) WHERE operation.project_id=%s AND operation.idempotency_scope=%s AND operation.idempotency_key=%s ORDER BY attempt.attempt_number DESC LIMIT 1",
            [command.project_id, SCREENPLAY_SAMPLE_SCOPE, command.idempotency_key])
        existing = uow.cursor.fetchone()
        stored = None
        if existing:
            if {key: value for key, value in existing[0].items() if key != "routing_bootstrap_authorization"} != payload:
                raise KernelError("SCREENPLAY_SAMPLE_INPUT_DRIFT", "Replay retains its exact original sample request")
            stored = uow.repositories.capability_packs.find_attempt_snapshot(existing[1])
        snapshot = stored["snapshot"] if stored else binder.pack_resolver.resolve_in_uow(uow, CapabilityPackResolutionRequest(
            project_id=command.project_id, workspace_id=workspace_id, book_id=payload["book_id"],
            workflow_definition_ref=sample_workflow(stage), workflow_node_id=stage, environment=binder.pack_environment,
            runtime_profile=binder.pack_runtime_profile, release_channel=binder.pack_release_channel,
            release_sha=binder.routes[stage].release_sha, operation_definition_ref=sample_definition_name(stage) + "@" + SCREENPLAY_SAMPLE_VERSION,
            pack_id=binder.capability_pack_id + ".samples"))
        version = uow.repositories.capability_packs.require_version(snapshot.pack_id, snapshot.pack_version)
        artifacts = materialize_registered_pack_version(snapshot, version)
        uow.cursor.execute("SELECT version.content,version.content_hash FROM authority_operation_output_asset output JOIN authority_asset_version version USING(asset_version_id) JOIN authority_asset asset ON asset.asset_id=version.asset_id WHERE output.operation_id=%s AND asset.project_id=%s AND asset.asset_type='capability_materialization_manifest' AND output.content_hash=version.content_hash",
            [command.source_operation_id, command.project_id])
        rows = uow.cursor.fetchall()
    producers = {}
    for content, digest in rows:
        materialization = deepcopy(content.get("contract") or {})
        if digest != authorization_hash(content) or materialization.get("stage") != "screenplay_generate":
            raise KernelError("SCREENPLAY_SAMPLE_PRODUCER_DRIFT", "Original source materialization differs")
        schema, schema_ref = PostgresChapterExecutionContractBinder._provider_output_contract(stage=stage, request_payload={"input": sample_provider_input(frozen)})
        materialization.update(stage=stage, output_schema={"ref": schema_ref, "content_hash": authorization_hash(schema), "content": schema})
        materialization["pack_artifacts"] = artifacts.to_dict(include_content=True)
        context = projected_sample_context(stage, frozen)
        materialization["context_selection"] = [{**materialization["context_selection"][0], "content": context, "content_hash": authorization_hash(context)}]
        tool_payload = json.loads(snapshot.tool_policy_payload_json)
        allowed, denied = _stage_tool_permissions(tool_payload, stage)
        materialization["tool_permissions"] = {"default": str(tool_payload.get("default") or ""), "allowed": list(allowed), "denied": list(denied),
            "invoked": ["model.provider.invoke"], "governing_policy_ref": snapshot.tool_policy_ref, "governing_policy_hash": snapshot.tool_policy_hash}
        _, evidence = _materialize_production_codex_prompt(target_scope={"scope_kind": "asset_version", "scope_id": frozen["source_binding"]["asset_version_id"],
            "asset_version_id": frozen["source_binding"]["asset_version_id"], "project_id": command.project_id, "book_id": payload["book_id"]},
            stage=stage, inputs=sample_provider_input(frozen), materialization=materialization)
        producer = chapter_producer_contract_identity(evidence, materialization)
        producers[authorization_hash(producer)] = producer
    if len(producers) != 1:
        raise KernelError("SCREENPLAY_SAMPLE_PRODUCER_REQUIRED", "Original formal source must materialize its exact producer before sampling")
    return next(iter(producers.values()))


def sample_provider_input(frozen: Mapping[str, Any]) -> dict[str, Any]:
    return {"book_id": frozen["source"]["book_id"], "source_digest": frozen["source"]["source_digest"],
        **({"screenplay_source_contract": "screenplay-source.v2"} if frozen["source"]["schema_version"] == "screenplay-source.v2" else {}),
        "candidate_digest": frozen["candidate"]["candidate_digest"] if frozen["candidate"] else ""}


def admit_screenplay_sample(app: Any, command: ScreenplaySampleCommand, *, principal: Principal) -> dict[str, Any]:
    prepared = prepare_screenplay_sample(app, command, principal=principal)
    binder = app.screenplay_model_ports[command.stage].capability_binder
    snapshot = freeze_bootstrap_authorization(database_url=app.database_url, command_payload=prepared["command_payload"],
        principal=principal, environment=binder.pack_environment, permission="book.authority.execute", idempotency_scope=SCREENPLAY_SAMPLE_SCOPE)
    grant = snapshot["authorization"]
    if (grant["purpose"] != sample_purpose(command.stage) or not grant.get("campaign")
        or grant.get("producer_contract_hash") != prepared["producer_contract_hash"]):
        raise KernelError("SCREENPLAY_SAMPLE_AUTHORIZATION_INVALID", "sample requires a scoped reference campaign and its unchanged formal producer")
    definition = screenplay_sample_definition(application_build_id=app.application_build_id, commit_sha=app.commit_sha, stage=command.stage)
    payload = {**prepared["command_payload"], "routing_bootstrap_authorization": snapshot}
    trace = "screenplay-sample:" + command.idempotency_key
    with AuthorityUnitOfWork(app.database_url, coordinate_nested=True) as uow:
        uow.repositories.definitions.register(definition)
        identity = authorization_hash([command.project_id, grant["campaign"]["campaign_id"], grant["campaign"]["sample_id"], grant["candidate_id"], grant["model_revision"]])
        uow.cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", [identity])
        _require_predecessor(uow.cursor, command=command, payload=payload)
        admitted = admit_command_in_uow(uow, {"definition_name": sample_definition_name(command.stage), "definition_version": SCREENPLAY_SAMPLE_VERSION,
            "project_id": command.project_id, "workspace_id": prepared["workspace_id"], "book_id": payload["book_id"],
            "logical_key": command.source_operation_id, "actor_id": principal.principal_id,
            "idempotency_scope": SCREENPLAY_SAMPLE_SCOPE, "idempotency_key": command.idempotency_key,
            "trace_id": trace, "span_id": str(uuid4()), "correlation_id": trace,
            "causation_id": command.predecessor_operation_id or command.source_operation_id,
            "causation_operation_id": command.predecessor_operation_id or command.source_operation_id,
            "input": {"project_id": command.project_id, "input_asset_version_ids": [item["asset_version_id"] for item in prepared["input_assets"]], "payload": payload},
            "input_assets": prepared["input_assets"]},
            context=AdmissionContext(actor_id=principal.principal_id, permissions=principal.permissions,
                available_handlers=app.registry.available_handler_keys, application_build_id=app.application_build_id, commit_sha=app.commit_sha))
        operation_id = str(admitted["operation_id"])
        state = uow.repositories.attempt_runtime.operation_state(operation_id, command.project_id)
        if state["status"] == "ADMITTED":
            transition_operation_in_uow(uow, OperationTransitionCommand(operation_id=operation_id, project_id=command.project_id,
                expected_version=int(state["version"]), expected_status="ADMITTED", target_status="READY", actor_id=principal.principal_id,
                reason="authorized screenplay sample inputs frozen", trace_id=trace, correlation_id=trace, causation_id=command.source_operation_id))
        context = GraphCommandContext(command.project_id, principal.principal_id, trace, trace)
        saga = start_saga(app.database_url, context, root_operation_id=operation_id)
        register_saga_step(app.database_url, context, str(saga["saga_id"]), operation_id, "screenplay_sample", 1, "")
        uow.commit()
    return {"operation_id": operation_id, "replayed": bool(admitted["replayed"]), "production_eligible": False,
        "authorization_id": command.authorization_id, "campaign_id": grant["campaign"]["campaign_id"]}


def _require_predecessor(cursor: Any, *, command: ScreenplaySampleCommand, payload: dict[str, Any]) -> None:
    grant = payload["routing_bootstrap_authorization"]["authorization"]
    cursor.execute("""SELECT operation_id,status,actor_id,idempotency_key,command_payload->'payload'
        FROM authority_operation WHERE project_id=%s AND definition_name=%s
          AND command_payload #>> '{payload,routing_bootstrap_authorization,authorization,campaign,campaign_id}'=%s
          AND command_payload #>> '{payload,routing_bootstrap_authorization,authorization,campaign,sample_id}'=%s
          AND command_payload #>> '{payload,routing_bootstrap_authorization,authorization,candidate_id}'=%s
          AND command_payload #>> '{payload,routing_bootstrap_authorization,authorization,model_revision}'=%s
        ORDER BY created_at,operation_id FOR UPDATE""",
        [command.project_id, sample_definition_name(command.stage), grant["campaign"]["campaign_id"], grant["campaign"]["sample_id"], grant["candidate_id"], grant["model_revision"]])
    rows = cursor.fetchall()
    if any(row[3] == command.idempotency_key for row in rows):
        return
    if not rows and not command.predecessor_operation_id:
        return
    if not rows or command.predecessor_operation_id != rows[-1][0]:
        raise KernelError("SCREENPLAY_SAMPLE_PREDECESSOR_REQUIRED", "sample replacement must identify its latest native operation")
    previous = rows[-1]
    if (previous[2] != command.actor_id or any(previous[4].get(key) != payload.get(key)
        for key in ("screenplay_sampling", "input_versions", "reference_evaluation", "generator_operation_name"))
        or previous[4]["routing_bootstrap_authorization"]["authorization"]["campaign"] != grant["campaign"]):
        raise KernelError("SCREENPLAY_SAMPLE_PREDECESSOR_INVALID", "replacement cannot change its frozen sample or operator")
    cursor.execute("SELECT status FROM authority_external_effect WHERE project_id=%s AND operation_id=%s FOR UPDATE", [command.project_id, previous[0]])
    effects = cursor.fetchall()
    cursor.execute("SELECT status FROM authority_budget_reservation WHERE project_id=%s AND operation_id=%s FOR UPDATE", [command.project_id, previous[0]])
    budgets = cursor.fetchall()
    if (previous[1] not in {"FAILED_FINAL", "DEAD_LETTER", "CANCELLED"}
        or any(row[0] not in {"FAILED_FINAL", "DEAD_LETTER", "CANCELLED"} for row in effects)
        or any(row[0] not in {"SETTLED", "RELEASED", "REJECTED"} for row in budgets)):
        raise KernelError("SCREENPLAY_SAMPLE_PREDECESSOR_NOT_REPLACEABLE", "recover success and reconcile unknown effects and budgets before replacement")


@dataclass(frozen=True, slots=True)
class ScreenplaySampleHandler:
    model_port: Any
    stage: str

    def __post_init__(self) -> None:
        sample_definition_name(self.stage)
        if not getattr(self.model_port, "external_effect_backed", False):
            raise ValueError("Screenplay samples require native ExternalEffect execution")

    def execute(self, request: Any) -> AuthorityHandlerOutput:
        payload = request.command["payload"]
        def assert_origin():
            with AuthorityUnitOfWork(self.model_port.database_url) as uow:
                snapshot = load_bootstrap_authorization(uow.cursor, project_id=request.project_id, operation_id=request.operation_id, check_expiry=False)
                if not snapshot or snapshot["authorization"]["task_type"] != self.stage:
                    raise KernelError("SCREENPLAY_SAMPLE_AUTHORIZATION_INVALID", "Sample requires its exact frozen task grant")
                return snapshot, validate_screenplay_sample_origin(uow.cursor, project_id=request.project_id, payload=payload)
        snapshot, frozen = assert_origin()
        result = self.model_port.invoke(request, stage=self.stage, payload=sample_provider_input(frozen),
            reservation_tokens=frozen["source"]["policy"]["context_token_budget"], pre_send_assertion=assert_origin)
        output = validate_review(result.output, frozen["source"], frozen["candidate"]) if self.stage == "screenplay_review" else validate_candidate(result.output, frozen["source"])
        grant = snapshot["authorization"]
        return AuthorityHandlerOutput(asset_type=SCREENPLAY_SAMPLE_TYPE, output_key=sample_definition_name(self.stage), role="primary",
            content={"schema_version": "screenplay-provider-sample.v1", "project_id": request.project_id,
                "stage": self.stage, "source_operation_id": payload["logical_key"], "source_binding": frozen["source_binding"],
                "source_revision_id": frozen["source"]["source_revision_id"], "source_manifest_digest": frozen["source"]["source_manifest_digest"],
                "upstream_sample": payload["screenplay_sampling"]["upstream_sample"], "revision_round": frozen["revision_round"],
                "input_candidate": frozen["candidate"], "input_review": frozen["review"], "sampled_output": output,
                "authorization_id": grant["authorization_id"], "campaign": grant["campaign"],
                "production_eligible": False, "routing_eligibility": "BENCHMARK_ONLY"},
            qualification_policy="screenplay-provider-sample.v1", eligibility="INELIGIBLE",
            reference_asset_version_ids=tuple(item["asset_version_id"] for item in payload["input_versions"]),
            evidence={"model_evidence": result.to_evidence(), "production_eligible": False,
                "novel_canon_mutation_allowed": False, "formal_candidate_created": False})
