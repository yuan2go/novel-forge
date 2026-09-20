from __future__ import annotations

from typing import Any
from uuid import uuid4

from novel_forge.modules.authority_handler_runtime.routing_bootstrap import freeze_bootstrap_authorization
from novel_forge.modules.authority_handler_runtime.runtime import require_current_fence
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.routing_bootstrap import (
    SOURCE_BOOTSTRAP_TASKS, authorization_hash, bootstrap_command_hash,
    load_bootstrap_authorization,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.source_import_repositories import SourceImportRepository


def prepare_sample(app, *, project_id: str, source_operation_id: str,
                   authorization_id: str, idempotency_key: str, principal: Principal,
                   predecessor_operation_id: str = "") -> dict[str, Any]:
    principal.require("source.authority.execute", project_id)
    if principal.principal_type is not PrincipalType.LOCAL_OPERATOR:
        raise PermissionError("Source sampling requires an authenticated local operator")
    if not all(isinstance(value, str) and value.strip() for value in (
        source_operation_id, authorization_id, idempotency_key,
    )):
        raise ValueError("Source sampling requires exact operation, authorization and request identities")
    if not isinstance(predecessor_operation_id, str):
        raise ValueError("Source sampling predecessor must be an operation identity")
    with AuthorityUnitOfWork(app.database_url) as uow:
        uow.cursor.execute(
            "SELECT definition_name,definition_version,workspace_id,command_payload->'payload',input_asset_snapshot FROM authority_operation WHERE project_id=%s AND operation_id=%s",
            [project_id, source_operation_id],
        )
        row = uow.cursor.fetchone()
        if not row or row[0] not in SOURCE_BOOTSTRAP_TASKS or row[1] != "1.4.0":
            raise KernelError("SOURCE_SAMPLE_TASK_UNSUPPORTED", "sampling requires a frozen native Source Provider task")
        source_payload = row[3]
        if source_payload.get("routing_bootstrap_authorization_id") or source_payload.get("reprocessing_plan_asset_version_id"):
            raise KernelError("SOURCE_SAMPLE_INPUT_SCOPE_INVALID", "sample from the original Source stage, not another sample or a reprocessing command")
        work = SourceImportRepository(uow.cursor).work_by_operation(
            project_id=project_id, operation_id=source_operation_id,
        )
        inputs = [{"asset_version_id": value["asset_version_id"], "content_hash": value["content_hash"],
                   "role": "source_sampling_input"} for value in row[4]]
    payload = {
        **source_payload, "project_id": project_id,
        "book_id": f"source-corpus:{project_id}",
        "generator_operation_name": SOURCE_BOOTSTRAP_TASKS[row[0]],
        "logical_key": source_operation_id, "idempotency_key": idempotency_key,
        "input_versions": row[4],
        "source_predecessor_operation_id": predecessor_operation_id,
        "source_sampling": {"source_operation_id": source_operation_id,
                            "source_command_hash": authorization_hash(source_payload)},
        "routing_bootstrap_authorization_id": authorization_id,
    }
    return {
        "status": "PREPARED_NO_PROVIDER_CALL", "definition_name": row[0],
        "workspace_id": row[2], "command_payload": payload, "input_assets": inputs,
        "command_hash": bootstrap_command_hash(payload),
        "input_versions_hash": authorization_hash(row[4]),
        "work": {key: work[key] for key in ("import_job_id", "work_kind", "source_path", "target_asset_version_id")},
        "production_eligible": False,
    }


def admit_sample(app, *, project_id: str, source_operation_id: str,
                 authorization_id: str, idempotency_key: str, principal: Principal,
                 predecessor_operation_id: str = "") -> dict[str, Any]:
    prepared = prepare_sample(app, project_id=project_id, source_operation_id=source_operation_id,
                              authorization_id=authorization_id, idempotency_key=idempotency_key, principal=principal,
                              predecessor_operation_id=predecessor_operation_id)
    port = app._require_execution_port()
    router = getattr(getattr(port, "transport", None), "provider_router", None)
    snapshot = freeze_bootstrap_authorization(
        database_url=app.database_url, command_payload=prepared["command_payload"],
        principal=principal, environment=getattr(router, "execution_environment", ""),
        permission="source.authority.execute", idempotency_scope="project:source-import",
    )
    grant = snapshot["authorization"]
    if not grant.get("campaign") or grant["purpose"] != "BENCHMARK_CHALLENGER":
        raise KernelError("SOURCE_SAMPLE_CAMPAIGN_REQUIRED", "Source sampling requires an immutable campaign grant")
    trace = "source-sample:" + idempotency_key
    with AuthorityUnitOfWork(app.database_url, coordinate_nested=True) as uow:
        identity = authorization_hash([project_id, grant["campaign"]["campaign_id"],
                                       grant["campaign"]["sample_id"], grant["candidate_id"], grant["model_revision"]])
        uow.cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", [identity])
        uow.cursor.execute(
            """SELECT operation_id,status,actor_id,idempotency_key,command_payload->'payload' FROM authority_operation WHERE project_id=%s
               AND command_payload #>> '{payload,routing_bootstrap_authorization,authorization,campaign,campaign_id}'=%s
               AND command_payload #>> '{payload,routing_bootstrap_authorization,authorization,campaign,sample_id}'=%s
               AND command_payload #>> '{payload,routing_bootstrap_authorization,authorization,candidate_id}'=%s
               AND command_payload #>> '{payload,routing_bootstrap_authorization,authorization,model_revision}'=%s
               ORDER BY created_at,operation_id FOR UPDATE""",
            [project_id, grant["campaign"]["campaign_id"], grant["campaign"]["sample_id"], grant["candidate_id"], grant["model_revision"]],
        )
        rows = uow.cursor.fetchall()
        replay = any(row[3] == idempotency_key for row in rows)
        if not replay and rows:
            prior = rows[-1]
            if predecessor_operation_id != prior[0]:
                raise KernelError("SOURCE_SAMPLE_RECOVERY_REQUIRED", "repeating a model arm requires its latest native Operation")
            prior_payload = prior[4]
            if (prior[2] != principal.principal_id
                or prior_payload["input_versions"] != prepared["command_payload"]["input_versions"]
                or prior_payload["source_sampling"] != prepared["command_payload"]["source_sampling"]
                or prior_payload["routing_bootstrap_authorization"]["authorization"]["campaign"] != grant["campaign"]):
                raise KernelError("SOURCE_SAMPLE_PREDECESSOR_INVALID", "replacement must preserve operator, source task, inputs and campaign sample")
            uow.cursor.execute("SELECT external_effect_id FROM authority_external_effect WHERE project_id=%s AND operation_id=%s FOR UPDATE", [project_id, prior[0]])
            if prior[1] not in {"FAILED_FINAL", "DEAD_LETTER", "CANCELLED"} or uow.cursor.fetchall():
                raise KernelError("SOURCE_SAMPLE_PREDECESSOR_NOT_REPLACEABLE", "only a terminal arm without external effects can be replaced; reconcile other outcomes")
        elif not replay and predecessor_operation_id:
            raise KernelError("SOURCE_SAMPLE_PREDECESSOR_INVALID", "predecessor must belong to this model arm")
        operation_id = app._admit_child(
            definition_name=prepared["definition_name"], project_id=project_id,
            workspace_id=prepared["workspace_id"], actor_id=principal.principal_id,
            idempotency_key=idempotency_key, trace_id=trace, correlation_id=trace,
            causation_id=source_operation_id, parent_operation_id=source_operation_id,
            causation_operation_id=predecessor_operation_id or source_operation_id,
            payload={**prepared["command_payload"], "routing_bootstrap_authorization": snapshot},
            input_assets=tuple(prepared["input_assets"]), ready=False,
        )
        SourceImportRepository(uow.cursor).register_work({
            **prepared["work"], "work_id": str(uuid4()), "project_id": project_id,
            "stable_key": "benchmark:" + authorization_hash([authorization_id, idempotency_key]),
            "operation_id": operation_id, "status": "PLANNED", "result": {}, "failure": {},
        })
        app._ready_child(operation_id=operation_id, project_id=project_id,
                         actor_id=principal.principal_id, trace_id=trace, correlation_id=trace,
                         causation_id=source_operation_id, reason="Authorized Source benchmark sample ready")
        uow.commit()
    return {"operation_id": operation_id, "production_eligible": False,
            "campaign_id": grant["campaign"]["campaign_id"], "authorization_id": authorization_id}


def sampling_authorization(app, worker):
    with AuthorityUnitOfWork(app.database_url) as uow:
        return load_bootstrap_authorization(uow.cursor, project_id=worker.project_id,
                                             operation_id=worker.causation_id, check_expiry=False)


def finish_sample(app, worker, executed: dict[str, Any]) -> dict[str, Any]:
    snapshot = sampling_authorization(app, worker)
    if snapshot is None:
        raise KernelError("SOURCE_SAMPLE_AUTHORIZATION_REQUIRED", "sample output requires its frozen authorization")
    result = {**executed, "qualification_status": "BENCHMARK_ONLY", "production_eligible": False,
              "authorization_id": snapshot["authorization"]["authorization_id"],
              "campaign": snapshot["authorization"]["campaign"]}
    with AuthorityUnitOfWork(app.database_url, coordinate_nested=True) as uow:
        require_current_fence(uow, worker)
        document = app._require_execution_port().writer.materialize_output(AuthorityAssetWriteCommand(
            operation_id=worker.causation_id, project_id=worker.project_id,
            asset_id="source-sample:" + worker.causation_id,
            asset_type="source_execution_context_manifest", schema_version="source-provider-sample.v1",
            logical_ref="source-intelligence/samples/" + worker.causation_id,
            category="production_execution_contracts", output_key="source.sample.output",
            role="benchmark_evidence", content=result, qualification_policy="source-benchmark-only.v1",
            trace_id=worker.trace_id, correlation_id=worker.correlation_id, eligibility="INELIGIBLE",
        ))
        result["sample_asset_version_id"] = document.asset_version_id
        SourceImportRepository(uow.cursor).update_work(
            project_id=worker.project_id, operation_id=worker.causation_id,
            expected=("PLANNED", "RUNNING", "FAILED_RETRYABLE"), status="SUCCEEDED", result=result,
        )
        uow.commit()
    return result
