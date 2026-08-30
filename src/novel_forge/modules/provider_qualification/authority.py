"""INVARIANT: fixture recovery evidence cannot qualify a real Provider route."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import importlib.metadata
from typing import Any, Mapping, Protocol
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    WorkerResultCommand,
    acquire_attempt_lease,
    create_attempt,
    queue_attempt,
    start_attempt,
    submit_attempt_result,
)
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    accept_external_effect_receipt,
    cancel_external_effect,
    dispatch_external_effect,
    plan_external_effect,
    reconcile_external_effect,
)
from novel_forge.modules.command_kernel.runtime import OperationTransitionCommand, transition_operation
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.modules.provider_control import ScriptedProviderAdapterV2
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery, AuthorityAssetWriter
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .definitions import D0_DEFINITION_VERSION, D0_HANDLER_KEY, D0_OPERATION, d0_operation_definition
from .domain import D0_GATE_NAMES, D0ProbeConfig, request_hash
from .runner import run_fixture_protocol_probe


class D0EvidenceStore(Protocol):
    def put_json(self, *, object_key: str, payload: Mapping[str, Any]) -> str: ...


@dataclass(frozen=True, slots=True)
class D0QualificationCommand:
    project_id: str
    workspace_id: str
    actor_id: str
    idempotency_key: str
    trace_id: str
    correlation_id: str
    config: D0ProbeConfig


class D0QualificationAuthority:
    def __init__(
        self,
        database_url: str,
        *,
        evidence_store: D0EvidenceStore,
        application_build_id: str,
        commit_sha: str,
        worker_id: str = "integration-worker:d0",
    ) -> None:
        self.database_url = database_url
        self.evidence_store = evidence_store
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.worker_id = worker_id

    def admit(self, command: D0QualificationCommand) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                "SELECT 1 FROM authority_workspace WHERE project_id=%s AND workspace_id=%s",
                [command.project_id, command.workspace_id],
            )
            if uow.cursor.fetchone() is None:
                raise ValueError("D0 Project/Workspace scope does not exist")
            uow.repositories.definitions.register(
                d0_operation_definition(
                    application_build_id=self.application_build_id,
                    commit_sha=self.commit_sha,
                )
            )
            uow.commit()
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": D0_OPERATION,
                "definition_version": D0_DEFINITION_VERSION,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "actor_id": command.actor_id,
                "idempotency_scope": "project:provider-qualification",
                "idempotency_key": command.idempotency_key,
                "trace_id": command.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": command.correlation_id,
                "causation_id": "",
                "input": {
                    "project_id": command.project_id,
                    "workspace_id": command.workspace_id,
                    "config": asdict(command.config),
                },
                "input_assets": [],
            },
            context=AdmissionContext(
                actor_id=command.actor_id,
                permissions=frozenset({"provider.qualification.execute"}),
                available_handlers=frozenset({D0_HANDLER_KEY}),
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
        )
        operation_id = str(admitted["operation_id"])
        state = self._operation(operation_id, command.project_id)
        if state["status"] == "ADMITTED":
            transition_operation(
                self.database_url,
                OperationTransitionCommand(
                    operation_id=operation_id,
                    project_id=command.project_id,
                    expected_version=int(state["version"]),
                    expected_status="ADMITTED",
                    target_status="READY",
                    actor_id=command.actor_id,
                    reason="D0 qualification admitted for integration worker",
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    causation_id="",
                ),
            )
        return {"operation_id": operation_id, "replayed": bool(admitted.get("replayed"))}

    def execute_fixture(self, command: D0QualificationCommand) -> dict[str, Any]:
        admitted = self.admit(command)
        operation_id = str(admitted["operation_id"])
        existing = self._existing_result(operation_id, command.project_id)
        if existing is not None:
            return {**existing, "replayed": True}
        state = self._operation(operation_id, command.project_id)
        attempt = create_attempt(
            self.database_url,
            operation_id=operation_id,
            project_id=command.project_id,
            max_attempts=2,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        attempt_id = str(attempt["attempt_id"])
        queue_attempt(
            self.database_url,
            attempt_id=attempt_id,
            project_id=command.project_id,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        lease = acquire_attempt_lease(
            self.database_url,
            attempt_id=attempt_id,
            project_id=command.project_id,
            worker_id=self.worker_id,
            lease_seconds=60,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        worker = WorkerLeaseCommand(
            attempt_id=attempt_id,
            project_id=command.project_id,
            worker_id=self.worker_id,
            fencing_token=int(lease["fencing_token"]),
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            causation_id=operation_id,
        )
        start_attempt(self.database_url, worker)
        result = self._execute_fixture(worker, command)
        current = self._operation(operation_id, command.project_id)
        submit_attempt_result(
            self.database_url,
            WorkerResultCommand(
                **worker.__dict__,
                expected_operation_version=int(current["version"]),
                expected_operation_status=str(current["status"]),
            ),
            outcome="success",
            result=result,
        )
        return {**result, "attempt_id": attempt_id, "replayed": False}

    def _execute_fixture(
        self, worker: WorkerLeaseCommand, command: D0QualificationCommand
    ) -> dict[str, Any]:
        operation_id = worker.causation_id
        qualification_run_id = f"d0:{operation_id}"
        fixture = run_fixture_protocol_probe(command.config)
        self._ensure_run(qualification_run_id, operation_id, command, fixture)
        context = EffectCommandContext(
            operation_id=operation_id,
            project_id=command.project_id,
            actor_id=self.worker_id,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        payload = {
            "schema_version": "d0-structured-echo.v1",
            "stage": "d0_qualification",
            "model_id": "fixture-model",
            "input": {"ok": True, "probe": "d0"},
            "trace_id": command.trace_id,
            "correlation_id": command.correlation_id,
        }
        basic_adapter = ScriptedProviderAdapterV2("success")
        basic_effect = plan_external_effect(
            self.database_url,
            context,
            effect_type="provider.qualification.basic",
            provider=basic_adapter.provider,
            capability=command.config.capability,
            stable_idempotency_key=f"{qualification_run_id}:basic",
            request_payload=payload,
            max_attempts=1,
            reversible=False,
            completion_policy="synchronous_final",
            model_id="fixture-model",
            request_timeout_seconds=command.config.timeout_seconds,
            reconciliation_mode="query",
            provider_capability_profile=basic_adapter.capability_profile.to_dict(),
        )
        basic_effect_id = str(basic_effect["external_effect_id"])
        basic_dispatched = dispatch_external_effect(
            self.database_url,
            context,
            effect_id=basic_effect_id,
            worker_id=f"{self.worker_id}:basic-effect",
            lease_seconds=60,
            adapter=basic_adapter,
        )
        adapter = ScriptedProviderAdapterV2("unknown_after_send")
        effect = plan_external_effect(
            self.database_url,
            context,
            effect_type="provider.qualification.invoke",
            provider=adapter.provider,
            capability=command.config.capability,
            stable_idempotency_key=f"{qualification_run_id}:invoke",
            request_payload=payload,
            max_attempts=1,
            reversible=False,
            completion_policy="poll_reconciliation",
            model_id="fixture-model",
            request_timeout_seconds=command.config.timeout_seconds,
            reconciliation_mode="query",
            provider_capability_profile=adapter.capability_profile.to_dict(),
        )
        effect_id = str(effect["external_effect_id"])
        dispatched = dispatch_external_effect(
            self.database_url,
            context,
            effect_id=effect_id,
            worker_id=f"{self.worker_id}:effect",
            lease_seconds=60,
            adapter=adapter,
        )
        # A new adapter instance models process loss. Scripted request identity is
        # deterministic and queryable without an in-memory invocation registry.
        restarted_adapter = ScriptedProviderAdapterV2("unknown_after_send")
        reconciled = reconcile_external_effect(
            self.database_url, context, effect_id=effect_id, adapter=restarted_adapter
        )
        receipt = dict(basic_dispatched["receipt"] or {})
        cancel_adapter = ScriptedProviderAdapterV2("unknown_after_send")
        cancel_effect = plan_external_effect(
            self.database_url,
            context,
            effect_type="provider.qualification.cancel",
            provider=cancel_adapter.provider,
            capability=command.config.capability,
            stable_idempotency_key=f"{qualification_run_id}:cancel",
            request_payload={**payload, "background": True},
            max_attempts=1,
            reversible=False,
            completion_policy="poll_reconciliation",
            model_id="fixture-model",
            request_timeout_seconds=command.config.timeout_seconds,
            reconciliation_mode="query",
            provider_capability_profile=cancel_adapter.capability_profile.to_dict(),
        )
        cancel_effect_id = str(cancel_effect["external_effect_id"])
        dispatch_external_effect(
            self.database_url,
            context,
            effect_id=cancel_effect_id,
            worker_id=f"{self.worker_id}:cancel-effect",
            lease_seconds=60,
            adapter=cancel_adapter,
        )
        cancel = cancel_external_effect(
            self.database_url,
            context,
            effect_id=cancel_effect_id,
            adapter=cancel_adapter,
        )
        request_ref = self.evidence_store.put_json(
            object_key=f"d0/{qualification_run_id}/request.json", payload=payload
        )
        response_payload = {
            "provider_request_id": dispatched["provider_request_id"],
            "basic_dispatch": basic_dispatched,
            "dispatch": dispatched,
            "reconciliation": reconciled,
            "receipt": receipt,
        }
        response_ref = self.evidence_store.put_json(
            object_key=f"d0/{qualification_run_id}/response.json",
            payload=response_payload,
        )
        self._persist_scenarios(
            qualification_run_id=qualification_run_id,
            effect_id=effect_id,
            provider_request_id=str(dispatched["provider_request_id"]),
            request_ref=request_ref,
            response_ref=response_ref,
            request_payload=payload,
            response_payload=response_payload,
            fixture=fixture.to_dict(),
            cancel=cancel,
            cancel_effect_id=cancel_effect_id,
            basic_effect_id=basic_effect_id,
            basic_provider_request_id=str(basic_dispatched["provider_request_id"]),
        )
        report = self._report_from_authority(qualification_run_id)
        report_asset = self._materialize_report(operation_id, command, qualification_run_id, report)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                UPDATE authority_d0_qualification_run
                SET status='BLOCKED', decision='BLOCKED', blocker=%s,
                    report_asset_version_id=%s, updated_at=NOW()
                WHERE qualification_run_id=%s
                """,
                [report["blocker"], report_asset.asset_version_id, qualification_run_id],
            )
            uow.commit()
        return {
            "operation_id": operation_id,
            "qualification_run_id": qualification_run_id,
            "report_asset_version_id": report_asset.asset_version_id,
            "status": "BLOCKED_MISSING_CREDENTIALS",
        }

    def _ensure_run(self, run_id: str, operation_id: str, command: D0QualificationCommand, fixture: Any) -> None:
        try:
            sdk_version = importlib.metadata.version("openai")
        except importlib.metadata.PackageNotFoundError:
            sdk_version = "not-installed"
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_d0_qualification_run(
                    qualification_run_id, operation_id, project_id, workspace_id,
                    provider, backend_id, model, model_version, sdk_version,
                    api_mode, sdk_max_retries, timeout_seconds, auth_secret_ref,
                    route_snapshot, fixture_protocol_only, status, blocker
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'responses',0,%s,%s,%s,TRUE,'RUNNING',%s)
                ON CONFLICT (qualification_run_id) DO NOTHING
                """,
                [run_id, operation_id, command.project_id, command.workspace_id,
                 command.config.provider, command.config.backend_id, fixture.model,
                 fixture.model_version, sdk_version, command.config.timeout_seconds,
                 command.config.auth_secret_ref,
                 Jsonb({"route_policy_version": command.config.route_policy_version,
                        "provider": command.config.provider,
                        "backend_id": command.config.backend_id,
                        "model": fixture.model}), fixture.blocker],
            )
            uow.commit()

    def _persist_scenarios(self, **values: Any) -> None:
        run_id = values["qualification_run_id"]
        request_payload = values["request_payload"]
        response_payload = values["response_payload"]
        fixture = values["fixture"]
        common = {
            "request_object_ref": values["request_ref"],
            "response_object_ref": values["response_ref"],
            "request_hash": request_hash(request_payload),
            "response_hash": request_hash(response_payload),
        }
        scenarios = {
            "D0-A": {"status": "BLOCKED", "receipt": fixture["receipt"], "evidence": {"auth": "fixture_only"}},
            "D0-B": {"status": "PASSED", "receipt": fixture["receipt"], "evidence": {"query": "reconciled"}},
            "D0-C": {"status": "CANCELLED", "receipt": fixture["receipt"], "evidence": values["cancel"]},
            "D0-D": {"status": "UNKNOWN", "receipt": {}, "evidence": {"before_send": "retryable", "after_send": "UNKNOWN"}},
            "D0-E": {"status": "LATE_RESULT", "receipt": fixture["receipt"], "evidence": {"terminal_decision_preserved": True}, "late_result": True},
            "D0-F": {"status": "PASSED", "receipt": fixture["receipt"], "evidence": {"restart_query_without_resend": True}},
        }
        with AuthorityUnitOfWork(self.database_url) as uow:
            for scenario, item in scenarios.items():
                uow.cursor.execute(
                    """
                    INSERT INTO authority_d0_scenario_evidence(
                        qualification_run_id, scenario, external_effect_id,
                        provider_request_id, status, request_object_ref,
                        response_object_ref, request_hash, response_hash, receipt,
                        raw_usage, normalized_usage, provider_cost, calculated_cost,
                        evidence, late_result
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (qualification_run_id, scenario) DO NOTHING
                    """,
                    [run_id, scenario,
                     (values["cancel_effect_id"] if scenario == "D0-C" else
                      values["basic_effect_id"] if scenario == "D0-A" else values["effect_id"]),
                     (values["basic_provider_request_id"] if scenario == "D0-A"
                      else values["provider_request_id"]),
                     item["status"], common["request_object_ref"], common["response_object_ref"],
                     common["request_hash"], common["response_hash"], Jsonb(item["receipt"]),
                     Jsonb(fixture["raw_usage"]), Jsonb(fixture["normalized_usage"]),
                     Jsonb(fixture["provider_cost"]), Jsonb(fixture["calculated_cost"]),
                     Jsonb(item["evidence"]), bool(item.get("late_result"))],
                )
            uow.commit()

    def _report_from_authority(self, run_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT provider, backend_id, model, model_version, sdk_version,
                       api_mode, sdk_max_retries, timeout_seconds, auth_secret_ref,
                       route_snapshot, blocker
                FROM authority_d0_qualification_run WHERE qualification_run_id=%s
                """,
                [run_id],
            )
            run = uow.cursor.fetchone()
            uow.cursor.execute(
                """
                SELECT scenario, status, external_effect_id, provider_request_id,
                       request_object_ref, response_object_ref, request_hash,
                       response_hash, receipt, raw_usage, normalized_usage,
                       provider_cost, calculated_cost, evidence, late_result
                FROM authority_d0_scenario_evidence
                WHERE qualification_run_id=%s ORDER BY scenario
                """,
                [run_id],
            )
            rows = uow.cursor.fetchall()
        return {
            "schema_version": "d0-provider-probe-report.v2",
            "qualification_run_id": run_id,
            "status": "BLOCKED_MISSING_CREDENTIALS",
            "blocker": str(run[10]),
            "provider": str(run[0]), "backend_id": str(run[1]),
            "model": str(run[2]), "model_version": str(run[3]),
            "sdk_version": str(run[4]), "api_mode": str(run[5]),
            "sdk_max_retries": int(run[6]), "timeout_seconds": int(run[7]),
            "auth_secret_ref": str(run[8]), "route_snapshot": dict(run[9]),
            "fixture_protocol_only": True,
            "gates": {name: False for name in D0_GATE_NAMES},
            "scenarios": [
                {"scenario": row[0], "status": row[1], "external_effect_id": row[2],
                 "provider_request_id": row[3], "request_object_ref": row[4],
                 "response_object_ref": row[5], "request_hash": row[6],
                 "response_hash": row[7], "receipt": row[8], "raw_usage": row[9],
                 "normalized_usage": row[10], "provider_cost": row[11],
                 "calculated_cost": row[12], "evidence": row[13], "late_result": row[14]}
                for row in rows
            ],
        }

    def _materialize_report(self, operation_id: str, command: D0QualificationCommand, run_id: str, report: dict[str, Any]):
        logical_ref = f"provider_qualification/{run_id}.json"
        try:
            return AuthorityAssetQuery(self.database_url).require(
                project_id=command.project_id, logical_ref=logical_ref
            )
        except Exception:
            return AuthorityAssetWriter(self.database_url).materialize_output(
                AuthorityAssetWriteCommand(
                    operation_id=operation_id, project_id=command.project_id,
                    asset_id=f"d0-report:{run_id}", asset_type="d0_provider_qualification_report",
                    schema_version="d0-provider-probe-report.v2", logical_ref=logical_ref,
                    category="provider_qualification", output_key="provider.qualification.d0.report",
                    role="primary", content=report, expected_current_asset_version_id=None,
                    reference_asset_ids=(), qualification_policy="d0-authority-evidence.v1",
                    trace_id=command.trace_id, correlation_id=command.correlation_id,
                )
            )

    def _operation(self, operation_id: str, project_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            return uow.repositories.attempt_runtime.operation_state(operation_id, project_id)

    def _existing_result(self, operation_id: str, project_id: str) -> dict[str, Any] | None:
        state = self._operation(operation_id, project_id)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT qualification_run_id, report_asset_version_id
                FROM authority_d0_qualification_run
                WHERE operation_id=%s AND project_id=%s
                  AND status='BLOCKED' AND report_asset_version_id IS NOT NULL
                """,
                [operation_id, project_id],
            )
            blocked = uow.cursor.fetchone()
        if blocked is not None:
            return {
                "operation_id": operation_id,
                "qualification_run_id": str(blocked[0]),
                "report_asset_version_id": str(blocked[1]),
                "status": "BLOCKED_MISSING_CREDENTIALS",
            }
        if state["status"] != "SUCCEEDED":
            return None
        metadata = dict(state.get("metadata") or {})
        result = metadata.get("transaction_result")
        if isinstance(result, dict):
            return result
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                "SELECT result FROM authority_attempt WHERE operation_id=%s AND status='SUCCEEDED' ORDER BY attempt_number DESC LIMIT 1",
                [operation_id],
            )
            row = uow.cursor.fetchone()
        return dict(row[0]) if row else None


__all__ = ["D0EvidenceStore", "D0QualificationAuthority", "D0QualificationCommand"]
