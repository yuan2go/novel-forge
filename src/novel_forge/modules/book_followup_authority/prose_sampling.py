from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping
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
from .prose_review import PROSE_REVIEW_DEFINITION, prose_review_invoke_payload, validate_window_report

PROSE_SAMPLE_DEFINITION = "longform.prose_review.sample"
PROSE_SAMPLE_VERSION = "1.0.0"
PROSE_SAMPLE_SCOPE = "book:prose-review-sample"
PROSE_SAMPLE_WORKFLOW = "book_followup_prose_sampling@1.0.0"
PROSE_SAMPLE_TYPE = "longform_prose_review_sample"
PROSE_SAMPLE_OUTPUT = "longform.prose_review.sample"
PROSE_REVIEWER_PROTOCOL = "prose-reviewer-independent-quality.v1"


def prose_sample_invoke_payload(content: Mapping[str, Any]) -> dict[str, Any]:
    if content["policy"].get("citation_locator_contract") == "literal-prose-citation.v1":
        return prose_review_invoke_payload(content)
    return {"manifest_digest": content["manifest_digest"], "window_id": content["window"]["window_id"]}


@dataclass(frozen=True, slots=True)
class ProseReviewSampleCommand:
    project_id: str
    actor_id: str
    source_operation_id: str
    authorization_id: str
    idempotency_key: str
    predecessor_operation_id: str = ""


def prose_sample_definition(*, application_build_id: str, commit_sha: str) -> dict[str, Any]:
    from .definitions import book_followup_operation_definitions

    definition = deepcopy(next(item for item in book_followup_operation_definitions(
        application_build_id=application_build_id, commit_sha=commit_sha) if item["name"] == PROSE_REVIEW_DEFINITION))
    definition.update(name=PROSE_SAMPLE_DEFINITION, definition_version=PROSE_SAMPLE_VERSION,
        handler_key="novel_forge.book_followup_authority." + PROSE_SAMPLE_DEFINITION,
        command_schema_version=PROSE_SAMPLE_DEFINITION + ".command.v1",
        result_schema_version=PROSE_SAMPLE_DEFINITION + ".result.v1",
        permissions=["book.followup:" + PROSE_SAMPLE_DEFINITION], idempotency_scope=PROSE_SAMPLE_SCOPE,
        concurrency_key_template="project:{project_id}:" + PROSE_SAMPLE_DEFINITION,
        projection_consumers=["independent_prose_reviewer_benchmark"],
        output_contract={**definition["result_schema"], "asset_type": PROSE_SAMPLE_TYPE,
            "output_key": PROSE_SAMPLE_OUTPUT, "role": "primary", "auxiliary_asset_types": []},
        policy={**definition["policy"], "routing_bootstrap_sample": True, "production_eligible": False},
        completion_contract={"version": "prose-review-sample.completion.v1",
            "required_asset_selectors": [{"selector": PROSE_SAMPLE_TYPE, "output_key": PROSE_SAMPLE_OUTPUT,
                "role": "primary", "lifecycle": "ACTIVE", "eligibility": "INELIGIBLE", "governance": "CLEAR"}],
            "required_qualifications": [{"decision": "INELIGIBLE"}], "required_evidence": ["trace", "audit"],
            "required_outbox_events": ["book_followup." + PROSE_SAMPLE_DEFINITION + ".materialized"]})
    return definition


def validate_prose_sample_origin(cursor: Any, *, project_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    metadata = payload.get("prose_sampling") or {}
    cursor.execute("SELECT definition_name,definition_version,command_payload->'payload',input_asset_snapshot FROM authority_operation WHERE project_id=%s AND operation_id=%s",
        [project_id, metadata.get("source_operation_id")])
    source = cursor.fetchone()
    metadata_keys = {"project_id", "generator_operation_name", "logical_key", "idempotency_key", "input_versions",
        "prose_sampling", "prose_predecessor_operation_id", "routing_bootstrap_authorization_id", "reference_evaluation"}
    if payload.get("routing_bootstrap_authorization") is not None:
        metadata_keys.add("routing_bootstrap_authorization")
    if (not source or source[:2] != (PROSE_REVIEW_DEFINITION, BOOK_FOLLOWUP_DEFINITION_VERSION)
        or metadata != {"source_operation_id": payload.get("logical_key"), "source_command_hash": authorization_hash(source[2])}
        or payload.get("generator_operation_name") != "longform_prose_review"
        or payload.get("input_versions") != source[3]
        or dict(payload) != {**source[2], **{key: payload.get(key) for key in metadata_keys}}):
        raise KernelError("PROSE_SAMPLE_ORIGIN_INVALID", "sample must retain its exact native review command and inputs")
    if len(source[3]) != 1:
        raise KernelError("PROSE_SAMPLE_ORIGIN_INVALID", "sample requires one exact accepted manuscript window")
    binding = source[3][0]
    cursor.execute("SELECT asset.asset_type,version.content,version.content_hash FROM authority_asset_version version JOIN authority_asset asset ON asset.asset_id=version.asset_id WHERE asset.project_id=%s AND version.asset_version_id=%s AND version.lifecycle='ACTIVE' AND version.eligibility='ELIGIBLE' AND version.governance='CLEAR'",
        [project_id, binding["asset_version_id"]])
    row = cursor.fetchone()
    if (not row or row[0] != "longform_prose_review_window" or row[2] != binding["content_hash"]
        or row[2] != authorization_hash(row[1]) or row[1].get("source_isolation") != "ACCEPTED_PROSE_ONLY"
        or row[1].get("manifest_digest") != payload.get("manifest_digest")
        or row[1].get("window", {}).get("window_id") != payload.get("window_id")
        or payload.get("reference_evaluation") != {**{key: binding[key] for key in ("asset_version_id", "content_hash")}, "protocol_version": PROSE_REVIEWER_PROTOCOL}):
        raise KernelError("PROSE_SAMPLE_ORIGIN_INVALID", "sample cannot replace its exact frozen window or evaluation protocol")
    cursor.execute("SELECT 1 FROM authority_book_prose_review_run run JOIN authority_book_prose_review_event event USING(run_id) WHERE run.project_id=%s AND run.book_run_id=%s AND run.manifest_digest=%s AND event.kind='WINDOW_ADMITTED' AND event.content->>'operation_id'=%s AND event.content->>'window_id'=%s",
        [project_id, payload["book_run_id"], payload["manifest_digest"], metadata["source_operation_id"], payload["window_id"]])
    if not cursor.fetchone():
        raise KernelError("PROSE_SAMPLE_ORIGIN_INVALID", "sample origin requires its durable native Book window admission")
    return dict(row[1])


def prepare_prose_sample(app: Any, command: ProseReviewSampleCommand, *, principal: Principal) -> dict[str, Any]:
    principal.require("book.authority.execute", command.project_id)
    principal.require("book.followup:" + PROSE_SAMPLE_DEFINITION, command.project_id)
    if principal.principal_type is not PrincipalType.LOCAL_OPERATOR or principal.principal_id != command.actor_id:
        raise PermissionError("prose sampling requires its authenticated local operator")
    if any(not isinstance(value, str) or not value.strip() for value in (
        command.project_id, command.source_operation_id, command.authorization_id, command.idempotency_key)):
        raise ValueError("prose sampling requires exact task, authorization and request identities")
    with AuthorityUnitOfWork(app.database_url) as uow:
        uow.cursor.execute("SELECT command_payload->'payload',input_asset_snapshot,workspace_id FROM authority_operation WHERE project_id=%s AND operation_id=%s AND definition_name=%s AND definition_version=%s",
            [command.project_id, command.source_operation_id, PROSE_REVIEW_DEFINITION, BOOK_FOLLOWUP_DEFINITION_VERSION])
        source = uow.cursor.fetchone()
        if not source or len(source[1]) != 1:
            raise KernelError("PROSE_SAMPLE_ORIGIN_INVALID", "prepare sampling from a frozen native review operation")
        payload = {**source[0], "project_id": command.project_id, "generator_operation_name": "longform_prose_review",
            "logical_key": command.source_operation_id, "idempotency_key": command.idempotency_key, "input_versions": source[1],
            "prose_sampling": {"source_operation_id": command.source_operation_id, "source_command_hash": authorization_hash(source[0])},
            "prose_predecessor_operation_id": command.predecessor_operation_id,
            "routing_bootstrap_authorization_id": command.authorization_id,
            "reference_evaluation": {**{key: source[1][0][key] for key in ("asset_version_id", "content_hash")}, "protocol_version": PROSE_REVIEWER_PROTOCOL}}
        window = validate_prose_sample_origin(uow.cursor, project_id=command.project_id, payload=payload)
        producer = _source_producer(uow.cursor, command=command, payload=payload, window=window)
    return {"status": "PREPARED_NO_PROVIDER_CALL", "provider_calls": 0, "production_eligible": False,
        "definition_name": PROSE_SAMPLE_DEFINITION, "definition_version": PROSE_SAMPLE_VERSION,
        "workspace_id": source[2], "command_payload": payload, "input_assets": source[1],
        "command_hash": bootstrap_command_hash(payload), "input_versions_hash": authorization_hash(source[1]),
        "producer_contract": producer, "producer_contract_hash": authorization_hash(producer),
        "required_workflow_ref": PROSE_SAMPLE_WORKFLOW}


def _source_producer(cursor: Any, *, command: ProseReviewSampleCommand, payload: dict[str, Any], window: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.chapter_authority.execution_gateway import _materialize_production_codex_prompt, chapter_producer_contract_identity

    cursor.execute("SELECT version.content,version.content_hash FROM authority_operation_output_asset output JOIN authority_asset_version version USING(asset_version_id) JOIN authority_asset asset ON asset.asset_id=version.asset_id WHERE output.operation_id=%s AND asset.project_id=%s AND asset.asset_type='capability_materialization_manifest' AND output.content_hash=version.content_hash",
        [command.source_operation_id, command.project_id])
    contracts = {}
    for content, digest in cursor.fetchall():
        contract = content.get("contract") or {}
        if digest != authorization_hash(content) or contract.get("stage") != "longform_prose_review":
            raise KernelError("PROSE_SAMPLE_PRODUCER_INVALID", "source materialization integrity differs")
        _, evidence = _materialize_production_codex_prompt(
            target_scope={"scope_kind": "asset_version", "scope_id": payload["input_versions"][0]["asset_version_id"],
                "project_id": command.project_id, "book_id": payload["book_id"],
                "asset_version_id": payload["input_versions"][0]["asset_version_id"]},
            stage="longform_prose_review", inputs=prose_sample_invoke_payload(window),
            materialization=contract)
        producer = chapter_producer_contract_identity(evidence, contract)
        contracts[authorization_hash(producer)] = producer
    if len(contracts) != 1:
        raise KernelError("PROSE_SAMPLE_PRODUCER_REQUIRED", "source review must first materialize one exact formal producer contract")
    return next(iter(contracts.values()))


def admit_prose_sample(app: Any, command: ProseReviewSampleCommand, *, principal: Principal) -> dict[str, Any]:
    prepared = prepare_prose_sample(app, command, principal=principal)
    binder = app.prose_model_port.capability_binder
    snapshot = freeze_bootstrap_authorization(database_url=app.database_url, command_payload=prepared["command_payload"],
        principal=principal, environment=binder.pack_environment, permission="book.authority.execute", idempotency_scope=PROSE_SAMPLE_SCOPE)
    grant = snapshot["authorization"]
    if (grant["purpose"] != "REFERENCE_EVALUATION" or not grant.get("campaign")
        or grant.get("producer_contract_hash") != prepared["producer_contract_hash"]):
        raise KernelError("PROSE_SAMPLE_AUTHORIZATION_INVALID", "sample requires a scoped reference campaign and its unchanged formal producer")
    definition = prose_sample_definition(application_build_id=app.application_build_id, commit_sha=app.commit_sha)
    payload = {**prepared["command_payload"], "routing_bootstrap_authorization": snapshot}
    trace = "prose-sample:" + command.idempotency_key
    with AuthorityUnitOfWork(app.database_url, coordinate_nested=True) as uow:
        uow.repositories.definitions.register(definition)
        identity = authorization_hash([command.project_id, grant["campaign"]["campaign_id"], grant["campaign"]["sample_id"], grant["candidate_id"], grant["model_revision"]])
        uow.cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", [identity])
        _require_predecessor(uow.cursor, command=command, payload=payload)
        admitted = admit_command_in_uow(uow, {"definition_name": PROSE_SAMPLE_DEFINITION, "definition_version": PROSE_SAMPLE_VERSION,
            "project_id": command.project_id, "workspace_id": prepared["workspace_id"], "book_id": payload["book_id"],
            "logical_key": command.source_operation_id, "actor_id": principal.principal_id,
            "idempotency_scope": PROSE_SAMPLE_SCOPE, "idempotency_key": command.idempotency_key,
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
                reason="authorized prose reviewer sample inputs frozen", trace_id=trace, correlation_id=trace, causation_id=command.source_operation_id))
        context = GraphCommandContext(command.project_id, principal.principal_id, trace, trace)
        saga = start_saga(app.database_url, context, root_operation_id=operation_id)
        register_saga_step(app.database_url, context, str(saga["saga_id"]), operation_id, "prose_reviewer_sample", 1, "")
        uow.commit()
    return {"operation_id": operation_id, "replayed": bool(admitted["replayed"]), "production_eligible": False,
        "authorization_id": command.authorization_id, "campaign_id": grant["campaign"]["campaign_id"]}


def _require_predecessor(cursor: Any, *, command: ProseReviewSampleCommand, payload: dict[str, Any]) -> None:
    grant = payload["routing_bootstrap_authorization"]["authorization"]
    cursor.execute("""SELECT operation_id,status,actor_id,idempotency_key,command_payload->'payload'
        FROM authority_operation WHERE project_id=%s AND definition_name=%s
          AND command_payload #>> '{payload,routing_bootstrap_authorization,authorization,campaign,campaign_id}'=%s
          AND command_payload #>> '{payload,routing_bootstrap_authorization,authorization,campaign,sample_id}'=%s
          AND command_payload #>> '{payload,routing_bootstrap_authorization,authorization,candidate_id}'=%s
          AND command_payload #>> '{payload,routing_bootstrap_authorization,authorization,model_revision}'=%s
        ORDER BY created_at,operation_id FOR UPDATE""",
        [command.project_id, PROSE_SAMPLE_DEFINITION, grant["campaign"]["campaign_id"], grant["campaign"]["sample_id"], grant["candidate_id"], grant["model_revision"]])
    rows = cursor.fetchall()
    if any(row[3] == command.idempotency_key for row in rows):
        return
    if not rows and not command.predecessor_operation_id:
        return
    if not rows or command.predecessor_operation_id != rows[-1][0]:
        raise KernelError("PROSE_SAMPLE_PREDECESSOR_REQUIRED", "sample replacement must identify its latest native operation")
    previous = rows[-1]
    if (previous[2] != command.actor_id or any(previous[4].get(key) != payload.get(key)
        for key in ("prose_sampling", "input_versions", "reference_evaluation"))
        or previous[4]["routing_bootstrap_authorization"]["authorization"]["campaign"] != grant["campaign"]):
        raise KernelError("PROSE_SAMPLE_PREDECESSOR_INVALID", "replacement cannot change its frozen sample or operator")
    cursor.execute("SELECT status FROM authority_external_effect WHERE project_id=%s AND operation_id=%s FOR UPDATE", [command.project_id, previous[0]])
    effects = cursor.fetchall()
    cursor.execute("SELECT status FROM authority_budget_reservation WHERE project_id=%s AND operation_id=%s FOR UPDATE", [command.project_id, previous[0]])
    budgets = cursor.fetchall()
    if (previous[1] not in {"FAILED_FINAL", "DEAD_LETTER", "CANCELLED"}
        or any(row[0] not in {"FAILED_FINAL", "DEAD_LETTER", "CANCELLED"} for row in effects)
        or any(row[0] not in {"SETTLED", "RELEASED", "REJECTED"} for row in budgets)):
        raise KernelError("PROSE_SAMPLE_PREDECESSOR_NOT_REPLACEABLE", "recover success and reconcile unknown effects and budgets before replacement")


@dataclass(frozen=True, slots=True)
class ProseReviewSampleHandler:
    model_port: Any

    def __post_init__(self) -> None:
        if not getattr(self.model_port, "external_effect_backed", False):
            raise ValueError("prose reviewer samples require native ExternalEffect execution")

    def execute(self, request: Any) -> AuthorityHandlerOutput:
        payload = request.command["payload"]
        source = request.require_input("longform_prose_review_window")

        def assert_origin() -> Mapping[str, Any]:
            with AuthorityUnitOfWork(self.model_port.database_url) as uow:
                snapshot = load_bootstrap_authorization(uow.cursor, project_id=request.project_id, operation_id=request.operation_id, check_expiry=False)
                if not snapshot:
                    raise KernelError("PROSE_SAMPLE_AUTHORIZATION_INVALID", "sample requires its immutable native authorization")
                content = validate_prose_sample_origin(uow.cursor, project_id=request.project_id, payload=payload)
                if content != source.content:
                    raise KernelError("PROSE_SAMPLE_ORIGIN_INVALID", "sample input changed after admission")
                return snapshot

        snapshot = assert_origin()
        result = self.model_port.invoke(request, stage="longform_prose_review",
            payload=prose_sample_invoke_payload(source.content),
            reservation_tokens=source.content["policy"]["context_token_budget"], pre_send_assertion=assert_origin)
        report = validate_window_report(result.output, manifest=source.content, window=source.content["window"])
        grant = snapshot["authorization"]
        return AuthorityHandlerOutput(asset_type=PROSE_SAMPLE_TYPE, output_key=PROSE_SAMPLE_OUTPUT, role="primary",
            content={"schema_version": "longform-prose-review-sample.v1", "project_id": request.project_id,
                "stage": "longform_prose_review", "source_operation_id": payload["prose_sampling"]["source_operation_id"],
                "source_window": payload["input_versions"][0], "sampled_output": report, "authorization_id": grant["authorization_id"],
                "campaign": grant["campaign"], "production_eligible": False, "routing_eligibility": "BENCHMARK_ONLY"},
            qualification_policy="longform-prose-review-sample.v1", eligibility="INELIGIBLE",
            reference_asset_version_ids=(source.asset_version_id,), evidence={"model_evidence": result.to_evidence(),
                "production_eligible": False, "formal_findings_created": False, "plan_change_allowed": False})
