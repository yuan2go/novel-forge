"""INVARIANT: the Source D0 scenario runs one existing Kernel-owned extraction stage."""
from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import time
from typing import Any

from novel_forge.api.authority_dependencies import build_production_execution_composition, build_source_import_application
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_adapters import ExternalEffectAdapterError
from novel_forge.modules.provider_qualification import D0LiveQualificationEvidence, D0ProbeConfig, D0QualificationAuthority, D0QualificationCommand
from novel_forge.modules.provider_qualification.domain import request_hash
from novel_forge.modules.provider_qualification.source_binding import SOURCE_ABSTRACTION_CAPABILITIES, source_runtime_identity
from novel_forge.modules.source_import.definitions import SOURCE_IMPORT_MKAOS_OPERATION
from novel_forge.modules.source_import.scheduler import SourceImportScheduler
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.object_store import MinioObjectStore


class SourceResponseLoss:
    def __init__(self, delegate: Any, *, enabled: bool):
        self.delegate, self.enabled, self.triggered = delegate, enabled, False

    def __getattr__(self, key: str) -> Any:
        return getattr(self.delegate, key)

    def source_result_checkpoint(self, result: Any) -> None:
        if self.enabled and not self.triggered and result.outcome == "success":
            self.triggered = True
            raise ExternalEffectAdapterError(
                "Source qualification lost the response after durable Provider completion",
                request_sent=True, failure_kind="response_loss",
            )


def inspect_source_operation(database_url: str, *, project_id: str, operation_id: str, capability: str) -> dict[str, Any]:
    if capability not in SOURCE_ABSTRACTION_CAPABILITIES:
        raise ValueError("Source qualification supports only registered MKAOS extraction capabilities")
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """SELECT operation.workspace_id,operation.status,operation.command_payload,
                      work.import_job_id,job.status,COUNT(effect.external_effect_id)
               FROM authority_operation operation
               JOIN authority_source_import_work work ON work.operation_id=operation.operation_id AND work.project_id=operation.project_id
               JOIN authority_source_import_job job ON job.import_job_id=work.import_job_id AND job.project_id=work.project_id
               LEFT JOIN authority_external_effect effect ON effect.operation_id=operation.operation_id
               WHERE operation.operation_id=%s AND operation.project_id=%s AND operation.definition_name=%s
               GROUP BY operation.workspace_id,operation.status,operation.command_payload,work.import_job_id,job.status""",
            [operation_id, project_id, SOURCE_IMPORT_MKAOS_OPERATION],
        )
        row = uow.cursor.fetchone()
    if row is None or (row[2].get("payload") or {}).get("capability") != capability:
        raise ValueError("exact native Source extraction Operation and capability are required")
    if row[1] not in {"READY", "WAITING_EXTERNAL_RESULT", "RECONCILIATION_REQUIRED", "SUCCEEDED"}:
        raise ValueError("Source stage must be READY, waiting for reconciliation, or already succeeded")
    if row[4] == "PAUSED":
        raise ValueError("resume the frozen Corpus job before qualifying its existing extraction stage")
    if row[5] > 1 or (row[1] == "READY" and row[5]):
        raise ValueError("existing Source effects require recovery, never a new qualification dispatch")
    return {"project_id": project_id, "workspace_id": str(row[0]), "operation_id": operation_id,
            "status": str(row[1]), "capability": capability, "import_job_id": str(row[3]),
            "inject_response_loss": row[1] == "READY" and row[5] == 0}


def qualification_release(identity: dict[str, Any], *, scope: dict[str, Any], root: Path,
                          commit_sha: str, implementation_identity: str) -> tuple[str, str]:
    observed = str(identity["route"]["release_sha"])
    if observed == commit_sha:
        return commit_sha, implementation_identity
    if scope["status"] != "SUCCEEDED":
        raise ValueError("only a settled original Source receipt may qualify a prior release")
    from novel_forge.tools.implementation_tree_identity import build_git_implementation_tree_identity
    return observed, build_git_implementation_tree_identity(root, observed)["implementation_tree_sha"]


def run_source_qualification(args: Any, *, root: Path, commit_sha: str, implementation_identity: str) -> dict[str, Any]:
    from scripts import run_real_provider_qualification as base

    scope = inspect_source_operation(args.database_url, project_id=args.source_project_id,
                                     operation_id=args.source_operation_id, capability=args.source_capability)
    if not args.execute:
        basis = str(os.environ.get("NOVEL_FORGE_CODEX_ACCOUNTING_MODE") or "PRICED").strip().upper()
        supported = basis in {"PRICED", "ACCOUNT_ENTITLEMENT"}
        return {"result": "NOT_RUN", "status": "READY_FOR_AUTHORIZATION" if supported else "BLOCKED_UNSUPPORTED_QUALIFICATION_MODE", "scope": scope,
                "blockers": [] if supported else ["D0_ACCOUNTING_MODE_UNSUPPORTED"],
                "provider_request_sent": False, "proof_scope": "EXACT_SOURCE_CAPABILITY_RUNTIME_ONLY",
                "required_route_contract": {"accounting_basis": basis, "capability": args.source_capability,
                                            "account_entitlement_supported": True,
                                            "monetary_cost": "UNKNOWN" if basis == "ACCOUNT_ENTITLEMENT" else "PRICING_SNAPSHOT_REQUIRED",
                                            "finite_project_call_and_token_limits_required": basis == "ACCOUNT_ENTITLEMENT"},
                "authorization_fields": ["exact Provider/model/profile and account/runtime identity",
                                         "Source extraction qualification purpose", "shared total call/token/cost and repair allowance"],
                "qualification_execution": "NOT_RUN", "human_knowledge_approval": "NOT_RUN"}
    if not base._outside_repository(Path(args.runtime_root).expanduser().resolve()):
        raise ValueError("Source runtime state must stay outside the repository")
    env = dict(os.environ)
    if env.get("NOVEL_FORGE_COMMIT_SHA") != commit_sha:
        raise ValueError("Source runtime must use the exact current authorized release SHA")
    execution_root = Path(str(env.get("NOVEL_FORGE_CODEX_EXECUTION_ROOT") or "")).expanduser().resolve()
    if execution_root != Path(args.runtime_root).expanduser().resolve() / "codex-executions":
        raise ValueError("--runtime-root must contain the existing configured Source codex-executions directory")
    settings = replace(IndustrialSettings.from_env(root=root), database_url=args.database_url,
                       minio_endpoint=args.minio_endpoint, minio_access_key=args.minio_access_key,
                       minio_secret_key=args.minio_secret_key, minio_secure=args.minio_secure)
    worker_id = f"source-qualification:{args.source_operation_id}"
    env["NOVEL_FORGE_SOURCE_IMPORT_WORKER_ID"] = worker_id
    execution = build_production_execution_composition(settings, env=env)
    if execution.cost_accounting_basis not in {"PRICED", "ACCOUNT_ENTITLEMENT"}:
        execution.close()
        raise ValueError("D0 qualification accounting mode is unsupported")
    route = execution.gateway.routes["quality_source_originality"]
    if (route.model_profile.model_provider, route.model_profile.model_id, route.model_profile.reasoning_effort) != (
        args.provider, args.model, args.reasoning_effort
    ):
        execution.close()
        raise ValueError("qualification options differ from the existing Source Provider/model/reasoning route")
    fault = SourceResponseLoss(execution.gateway, enabled=scope["inject_response_loss"])
    wrapped = replace(execution, gateway=fault)
    application = build_source_import_application(settings, execution=wrapped, env=env)
    scheduler = SourceImportScheduler(application, worker_id=worker_id, lease_seconds=5)
    try:
        try:
            completed = scheduler.run_or_recover(operation_id=args.source_operation_id, project_id=args.source_project_id)
        except KernelError as exc:
            if exc.code != "EFFECT_EXTERNAL_STATE_UNKNOWN":
                raise
            completed = None
        execution.close()
        recovered_execution = build_production_execution_composition(settings, env=env)
        recovered = SourceImportScheduler(build_source_import_application(settings, execution=recovered_execution, env=env),
                                          worker_id=worker_id, lease_seconds=5)
        try:
            deadline = time.monotonic() + 30
            while completed is None:
                try:
                    completed = recovered.run_or_recover(operation_id=args.source_operation_id, project_id=args.source_project_id)
                except KernelError as exc:
                    if exc.code != "SOURCE_RECOVERY_LEASE_ACTIVE" or time.monotonic() >= deadline:
                        raise
                    time.sleep(1)
            replay = recovered.run_or_recover(operation_id=args.source_operation_id, project_id=args.source_project_id)
        finally:
            recovered_execution.close()
    finally:
        execution.close()
    if not replay.get("replayed"):
        raise RuntimeError("Source qualification must converge through native stage replay")
    effect, provider, dispatches, receipts, reconciliations, _reconciliation = base._effect_evidence(
        args.database_url, operation_id=args.source_operation_id, capability=args.source_capability)
    if (dispatches, receipts, reconciliations) != (1, 1, 1):
        raise RuntimeError("Source D0 needs one dispatch, receipt and successful ambiguity reconciliation; existing normal successes cannot be relabeled or resent")
    identity = source_runtime_identity(provider)
    qualified_sha, qualified_implementation = qualification_release(identity, scope=scope, root=root,
        commit_sha=commit_sha, implementation_identity=implementation_identity)
    if (identity["route"]["model_provider"], identity["route"]["model_id"], identity["route"]["reasoning_effort"]) != (args.provider, args.model, args.reasoning_effort):
        raise ValueError("qualification options differ from the original Source receipt")
    production = provider["production_execution"]
    request, handle, result, route_snapshot = (production[key] for key in (
        "execution_request", "execution_handle", "execution_result", "route_snapshot"))
    if request["project_id"] != args.source_project_id or request["workspace_id"] != scope["workspace_id"]:
        raise ValueError("Source receipt belongs to another scope")
    runtime = provider["capability_runtime"]
    with AuthorityUnitOfWork(args.database_url) as uow:
        uow.cursor.execute("SELECT request_timeout_seconds FROM authority_external_effect WHERE external_effect_id=%s", [effect["external_effect_id"]])
        timeout = int(uow.cursor.fetchone()[0])
    config = D0ProbeConfig.from_mapping({
        "schema_version": "d0-provider-probe-config.v1", "provider": provider["provider_id"],
        "backend_id": handle["backend_id"], "model_env": "NOVEL_FORGE_QUALITY_MODEL",
        "model_version_env": "NOVEL_FORGE_D0_MODEL_VERSION", "route_policy_version": f"{route_snapshot['policy_id']}@{route_snapshot['policy_version']}",
        "timeout_seconds": timeout, "auth_secret_ref": "env://NOVEL_FORGE_PROVIDER_AUTH_PROFILE", "capability": args.source_capability,
        "prompt_version": provider["prompt_version"], "prompt_hash": runtime["prompt_template"]["content_hash"],
        "instruction_version": runtime["system_instruction"]["version"], "instruction_hash": runtime["system_instruction"]["content_hash"],
        "skill_version": provider["skill_version"], "skill_hash": runtime["skill"]["content_hash"],
        **({"accounting_scope": identity["accounting_scope"]} if identity.get("accounting_scope") else {}),
    })
    command = D0QualificationCommand(
        project_id=args.source_project_id, workspace_id=scope["workspace_id"], actor_id=worker_id,
        idempotency_key=f"source-d0:{effect['external_effect_id']}", trace_id=f"trace:source-d0:{effect['external_effect_id']}",
        correlation_id=args.source_operation_id, config=config, resolved_model=provider["model_id"],
        resolved_model_version=env.get("NOVEL_FORGE_D0_MODEL_VERSION") or "provider-not-reported",
        resolved_auth_profile_ref=route_snapshot["auth_profile_ref"], implementation_identity=qualified_implementation,
    )
    store = MinioObjectStore(settings)
    request_ref = store.put_json(object_key=f"d0/source/{effect['external_effect_id']}/request.json", payload=effect)
    response_ref = store.put_json(object_key=f"d0/source/{effect['external_effect_id']}/response.json", payload={"provider_evidence": provider})
    evidence = D0LiveQualificationEvidence.from_mapping({
        "schema_version": "d0-live-qualification-evidence.v1", "release_sha": qualified_sha,
        "implementation_identity": qualified_implementation, "source_operation_id": args.source_operation_id,
        "external_effect_id": effect["external_effect_id"], "request_object_ref": request_ref, "response_object_ref": response_ref,
        "auth_profile_ref": route_snapshot["auth_profile_ref"], "provider": provider["provider_id"], "backend_id": handle["backend_id"],
        "model": provider["model_id"], "model_version": command.resolved_model_version,
        "route_snapshot_id": route_snapshot["route_snapshot_id"], "route_snapshot_hash": request_hash(route_snapshot),
        "prompt_version": config.prompt_version, "prompt_hash": config.prompt_hash, "instruction_version": config.instruction_version,
        "instruction_hash": config.instruction_hash, "skill_version": config.skill_version, "skill_hash": config.skill_hash,
        "request_hash": effect["request_hash"], "response_hash": request_hash(provider), "provider_execution_id": request["execution_id"],
        "provider_request_identity": handle.get("provider_request_id") or handle.get("external_request_id") or handle.get("local_execution_receipt_id"),
        "usage": provider["usage"], "cost": provider["cost"], "latency": {"duration_ms": base._duration_ms(result)},
        "controlled_failure": {"checkpoint": "after_provider_response_before_effect_receipt", "failure_kind": "response_loss", "request_sent": True},
        "recovery": {"external_state_was_ambiguous": True, "recovered_without_resend": True, "replayed": True},
        "fixture_protocol_only": False, "real_model_call": True,
    })
    qualification = D0QualificationAuthority(args.database_url, evidence_store=store, application_build_id=f"source-runtime-qualification:{commit_sha}",
        commit_sha=qualified_sha, implementation_identity=qualified_implementation,
        validation_release_sha=commit_sha).execute_live(command, evidence)
    return {"schema_version": "source-runtime-qualification-run.v1", "result": "PASS", "scope": scope,
            "proof_scope": "EXACT_SOURCE_CAPABILITY_RUNTIME_ONLY", "source_execution_scope": identity,
            "validation_release_sha": commit_sha, "qualified_release_sha": qualified_sha,
            "qualification": qualification, "source_stage": completed,
            "source_replayed": replay.get("replayed"), "provider_execution_count": 1,
            "production_verified": False, "human_knowledge_approval": "NOT_RUN", "narrative_correctness": "NOT_PROVEN"}
