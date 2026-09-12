from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from .domain import D0_GATE_NAMES, request_hash


SOURCE_ABSTRACTION_CAPABILITIES = frozenset({"mkaos.knowledge.extract", "mkaos.rule.extract", "mkaos.template.extract"})
_RUNTIME_FIELDS = (
    "backend_id", "backend_version", "runtime_host_id", "auth_profile_ref",
    "model_profile_id", "model_profile_version", "model_profile_hash",
    "model_provider", "model_id", "reasoning_effort", "release_sha",
    "policy_id", "policy_version", "route_policy_hash", "output_schema_ref",
)


def _blocked(reason: str) -> KernelError:
    return KernelError("SOURCE_RUNTIME_QUALIFICATION_REQUIRED", reason)


def source_runtime_identity(evidence: Mapping[str, Any]) -> dict[str, Any]:
    production = evidence.get("production_execution") or {}
    request, handle, result, route = (production.get(key) or {} for key in (
        "execution_request", "execution_handle", "execution_result", "route_snapshot"))
    execution_id = request.get("execution_id")
    if (
        evidence.get("fixture_protocol_only") is not False
        or evidence.get("real_model_call") is not True
        or request.get("capability") not in SOURCE_ABSTRACTION_CAPABILITIES
        or not execution_id or not request.get("external_effect_id")
        or handle.get("execution_id") != execution_id or result.get("execution_id") != execution_id
        or result.get("outcome") != "SUCCEEDED"
        or handle.get("transport") not in {"REMOTE_PROVIDER_API", "LOCAL_CLI_REMOTE_INFERENCE"}
        or not (handle.get("provider_request_id") or handle.get("external_request_id") or handle.get("local_execution_receipt_id"))
        or not all(result.get(key) for key in ("normalized_output_ref", "usage_receipt_ref", "cost_receipt_ref"))
        or evidence.get("provider_id") != route.get("model_provider")
        or evidence.get("model_id") != route.get("model_id")
        or handle.get("backend_id") != route.get("backend_id")
        or not all(route.get(key) for key in _RUNTIME_FIELDS)
    ):
        raise _blocked("a successful, exact, non-fixture Source execution receipt is required")
    runtime = evidence.get("capability_runtime") or {}
    materialization = {key: (runtime.get(key) or {}).get("content_hash")
                       for key in ("system_instruction", "prompt_template", "skill")}
    materialization["output_schema_hash"] = runtime.get("output_schema_hash")
    if not all(materialization.values()):
        raise _blocked("compiled Source instruction, Skill and output Schema identities are required")
    return {"capability": request["capability"], "transport": handle["transport"],
            "route": {key: route[key] for key in _RUNTIME_FIELDS}, "materialization": materialization}


def _receipt(cursor: Any, *, project_id: str, effect_id: str) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT effect.status,effect.provider,effect.model_id,effect.capability,
               effect.request_hash,effect.request_payload,effect.operation_id,
               operation.workspace_id,dispatch.status,receipt.external_receipt_id,receipt.payload
        FROM authority_external_effect effect
        JOIN authority_operation operation ON operation.operation_id=effect.operation_id
        JOIN authority_external_effect_dispatch dispatch ON dispatch.external_effect_id=effect.external_effect_id
        JOIN authority_external_receipt receipt ON receipt.dispatch_id=dispatch.dispatch_id
        WHERE effect.external_effect_id=%s AND effect.project_id=%s
        """, [effect_id, project_id],
    )
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise _blocked("Source effect needs one immutable confirmed receipt")
    status, provider, model, capability, input_hash, payload, operation, workspace, dispatch_status, receipt_id, receipt = rows[0]
    evidence = dict((receipt or {}).get("evidence") or {})
    production = evidence.get("production_execution") or {}
    request = production.get("execution_request") or {}
    metadata = (payload or {}).get("_production_execution") or {}
    frozen_materialization = metadata.get("capability_runtime") or {}
    observed_materialization = evidence.get("capability_runtime") or {}
    if (
        (payload or {}).get("stage") != "source.mkaos.extract"
        or ((payload or {}).get("_source_intelligence") or {}).get("kind") != "mkaos"
        or metadata.get("operation_id") != str(operation) or metadata.get("project_id") != project_id
        or metadata.get("workspace_id") != str(workspace)
        or not all(frozen_materialization.get(key) and frozen_materialization[key] == observed_materialization.get(key)
                   for key in ("materialization_hash", "provider_request_envelope_hash"))
        or status != "SUCCEEDED" or dispatch_status != "SUCCEEDED"
        or provider != "production_execution_gateway" or model != evidence.get("model_id")
        or capability != request.get("capability") or request.get("external_effect_id") != effect_id
        or request.get("operation_id") != str(operation) or request.get("project_id") != project_id
        or request.get("workspace_id") != str(workspace) or request_hash(payload) != input_hash
    ):
        raise _blocked("Source receipt does not match its final Authority effect and request")
    return {"evidence": evidence, "receipt_id": str(receipt_id), "request_hash": str(input_hash),
            "response_hash": request_hash(evidence), "workspace_id": str(workspace)}


def require_source_runtime_qualification(
    database_url: str, *, project_id: str, workspace_id: str,
    execution_asset_version_id: str, execution_content_hash: str,
    candidate_payload_hash: str, frozen: Mapping[str, Any] | None = None,
    approval_cursor: Any | None = None,
) -> dict[str, Any]:
    scope = AuthorityUnitOfWork(database_url) if approval_cursor is None else nullcontext(SimpleNamespace(cursor=approval_cursor))
    with scope as uow:
        cursor = uow.cursor
        cursor.execute(
            """SELECT version.content,version.content_hash,version.lifecycle,version.eligibility,version.governance
               FROM authority_asset_version version JOIN authority_asset asset USING(asset_id)
               WHERE version.asset_version_id=%s AND asset.project_id=%s AND asset.asset_type='model_call_log'""",
            [execution_asset_version_id, project_id],
        )
        row = cursor.fetchone()
        if row is None or tuple(row[2:]) != ("ACTIVE", "ELIGIBLE", "CLEAR") or row[1] != execution_content_hash or request_hash(row[0]) != row[1]:
            raise _blocked("exact active Source execution evidence is unavailable")
        execution = dict(row[0])
        if (execution.get("schema_version") != "source-model-call-log.v1"
                or execution.get("fixture_protocol_only") is not False
                or execution.get("real_provider_proven") is not True):
            raise _blocked("only real Source execution evidence can use Source runtime qualification")
        production = execution.get("production_execution") or {}
        effect_id = str((production.get("execution_request") or {}).get("external_effect_id") or "")
        actual = _receipt(cursor, project_id=project_id, effect_id=effect_id)
        evidence = actual["evidence"]
        if (actual["workspace_id"] != workspace_id or evidence.get("production_execution") != production
                or evidence.get("usage") != execution.get("usage") or evidence.get("cost") != execution.get("cost")
                or request_hash(evidence.get("result") or {}) != candidate_payload_hash):
            raise _blocked("candidate or execution log differs from the confirmed Source output")
        identity = source_runtime_identity(evidence)
        cursor.execute(
            """
            SELECT run.qualification_run_id,run.report_asset_version_id,version.content_hash,
                   version.content,operation.command_payload,scenario.external_effect_id,
                   scenario.request_hash,scenario.response_hash
            FROM authority_d0_qualification_run run
            JOIN authority_operation operation ON operation.operation_id=run.operation_id
            JOIN authority_asset_version version ON version.asset_version_id=run.report_asset_version_id
            JOIN authority_d0_scenario_evidence scenario ON scenario.qualification_run_id=run.qualification_run_id AND scenario.scenario='D0-F'
            WHERE run.project_id=%s AND run.workspace_id=%s AND run.fixture_protocol_only=FALSE
              AND run.status='COMPLETED' AND run.decision='QUALIFIED' AND operation.status='SUCCEEDED'
              AND version.lifecycle='ACTIVE' AND version.eligibility='INELIGIBLE' AND version.governance='CLEAR'
              AND (%s='' OR run.report_asset_version_id=%s)
            ORDER BY run.created_at DESC,run.qualification_run_id
            FOR SHARE OF run,version,operation
            """, [project_id, workspace_id, str((frozen or {}).get("report_asset_version_id") or ""),
                    str((frozen or {}).get("report_asset_version_id") or "")],
        )
        qualification_rows = cursor.fetchall()
        for run_id, report_id, report_hash, report, command, qualified_effect_id, qualified_request_hash, qualified_response_hash in qualification_rows:
            config = (command or {}).get("config") or (command or {}).get("input", {}).get("config") or {}
            if (request_hash(report) != report_hash or config.get("capability") != identity["capability"] or report.get("schema_version") != "d0-provider-probe-report.v3"
                    or report.get("status") != "PASSED" or report.get("fixture_protocol_only") is not False
                    or report.get("gates") != {key: True for key in D0_GATE_NAMES}
                    or report.get("route_snapshot", {}).get("release_sha") != identity["route"]["release_sha"]):
                continue
            try:
                qualified = _receipt(cursor, project_id=project_id, effect_id=str(qualified_effect_id))
                qualified_identity = source_runtime_identity(qualified["evidence"])
            except KernelError:
                continue
            if (qualified["workspace_id"] != workspace_id or qualified_identity != identity or qualified["request_hash"] != qualified_request_hash
                    or qualified["response_hash"] != qualified_response_hash):
                continue
            binding = {
                "schema_version": "source-runtime-qualification-binding.v1",
                "proof_scope": "EXACT_SOURCE_CAPABILITY_RUNTIME_AND_CONFIRMED_OUTPUT",
                "qualification_run_id": str(run_id), "report_asset_version_id": str(report_id),
                "report_content_hash": str(report_hash), "qualified_effect_id": str(qualified_effect_id),
                "qualified_receipt_id": qualified["receipt_id"], "qualified_response_hash": qualified["response_hash"],
                "source_effect_id": effect_id, "source_receipt_id": actual["receipt_id"],
                "source_request_hash": actual["request_hash"], "source_response_hash": actual["response_hash"],
                "execution_asset_version_id": execution_asset_version_id, "execution_content_hash": execution_content_hash,
                "scope": identity, "semantic_correctness_proven": False, "production_effect_proven": False,
            }
            if frozen is not None and dict(frozen) != binding:
                raise _blocked("frozen runtime qualification identity changed; automatic replacement is forbidden")
            return binding
    raise _blocked("no current exact Source capability/profile qualification exists; run the scoped D0 Source scenario and retain manual knowledge review")
