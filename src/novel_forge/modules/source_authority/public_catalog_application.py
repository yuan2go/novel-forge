
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from novel_forge.modules.authority_handler_runtime.runtime import require_current_fence
from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.attempt_runtime import WorkerLeaseCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    plan_external_effect,
    dispatch_external_effect,
    reconcile_external_effect,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.source_authority_repositories import SourceAuthorityRepository
from .public_catalog import (
    CATALOG_OPERATION,
    CATALOG_VERSION,
    CATALOG_HANDLER,
    CatalogCapture,
    digest,
    rank_changes,
)
from .public_catalog_adapter import PublicCatalogAdapter


def catalog_definition(*, application_build_id: str, commit_sha: str) -> dict[str, Any]:
    return {
        "name": CATALOG_OPERATION,
        "definition_version": CATALOG_VERSION,
        "family": "source_governance",
        "enabled": True,
        "command_schema": {
            "type": "object",
            "required": ["project_id", "workspace_id", "payload"],
            "properties": {
                "project_id": {"type": "string"},
                "workspace_id": {"type": "string"},
                "payload": {"type": "object"},
            },
            "additionalProperties": False,
        },
        "result_schema": {
            "type": "object",
            "required": ["asset_version_id"],
            "properties": {"asset_version_id": {"type": "string"}},
            "additionalProperties": True,
        },
        "handler_key": CATALOG_HANDLER,
        "handler_contract_version": "public-catalog-handler.v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "worker",
        "permissions": ["source.authority.execute"],
        "approval_policy": {"required": False, "policy_key": "public-metadata-only.v1"},
        "idempotency_scope": "project:public-catalog",
        "concurrency_key_template": "project:{project_id}:public-catalog",
        "retry_policy": {"max_attempts": 2},
        "timeout_policy": {"operation_timeout_seconds": 300},
        "cancellation_policy": {"mode": "cancel_active_attempt"},
        "compensation_policy": {
            "supported": False,
            "reason": "immutable metadata observations",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": ["source.remote.fetch"],
        "policy": {
            "execution_classification": "durable_job",
            "project_scope_required": True,
            "generation_context_forbidden": True,
            "prose_rights_not_inferred": True,
        },
        "completion_contract": {
            "version": "public-catalog-completion.v1",
            "required_asset_selectors": [
                {
                    "selector": "public_catalog_snapshot",
                    "output_key": "source.public_catalog.snapshot",
                    "role": "evidence",
                    "lifecycle": "ACTIVE",
                    "eligibility": "INELIGIBLE",
                    "governance": "CLEAR",
                }
            ],
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": ["authority.source.public_catalog.captured"],
        },
    }


@dataclass(frozen=True)
class CatalogCommand:
    project_id: str
    workspace_id: str
    idempotency_key: str
    actor_id: str
    capture: CatalogCapture
    trace_id: str
    correlation_id: str


class PublicCatalogApplication:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        worker_id: str = "source-authority-worker",
        adapter: PublicCatalogAdapter | None = None,
    ) -> None:
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.worker_id = worker_id
        self._adapter = adapter

    def adapter(self) -> PublicCatalogAdapter:
        if self._adapter is None:
            root = os.environ.get("NOVEL_FORGE_SOURCE_IMPORT_GIT_CACHE_ROOT", "")
            if not root or not Path(root).is_absolute():
                raise ValueError(
                    "public catalog requires NOVEL_FORGE_SOURCE_IMPORT_GIT_CACHE_ROOT"
                )
            offline = os.environ.get("NOVEL_FORGE_PUBLIC_CATALOG_OFFLINE_ROOT", "")
            self._adapter = PublicCatalogAdapter(
                Path(root) / "public-catalog",
                offline_root=Path(offline) if offline else None,
            )
        return self._adapter

    def admit(self, command: CatalogCommand, *, principal: Principal) -> dict[str, Any]:
        principal.require("source.authority.execute", command.project_id)
        if not all(
            (
                command.project_id,
                command.workspace_id,
                command.idempotency_key,
                command.trace_id,
                command.correlation_id,
            )
        ):
            raise ValueError("catalog command scope and identity are required")
        self.adapter()
        with AuthorityUnitOfWork(self.database_url) as uow:
            SourceAuthorityRepository(uow.cursor).require_scope(
                project_id=command.project_id, workspace_id=command.workspace_id
            )
            uow.repositories.definitions.register(
                catalog_definition(
                    application_build_id=self.application_build_id,
                    commit_sha=self.commit_sha,
                )
            )
            uow.commit()
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": CATALOG_OPERATION,
                "definition_version": CATALOG_VERSION,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "actor_id": principal.principal_id,
                "idempotency_scope": "project:public-catalog",
                "idempotency_key": command.idempotency_key,
                "trace_id": command.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": command.correlation_id,
                "causation_id": command.idempotency_key,
                "input_assets": [],
                "input": {
                    "project_id": command.project_id,
                    "workspace_id": command.workspace_id,
                    "payload": command.capture.model_dump(mode="json"),
                },
            },
            context=AdmissionContext(
                actor_id=principal.principal_id,
                permissions=frozenset({"source.authority.execute"}),
                available_handlers=frozenset({CATALOG_HANDLER}),
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(
                admitted["operation_id"], command.project_id
            )
        if state["status"] == "ADMITTED":
            transition_operation(
                self.database_url,
                OperationTransitionCommand(
                    operation_id=admitted["operation_id"],
                    project_id=command.project_id,
                    expected_version=state["version"],
                    expected_status="ADMITTED",
                    target_status="READY",
                    actor_id=principal.principal_id,
                    reason="public metadata capture admitted",
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    causation_id=command.idempotency_key,
                ),
            )
            state["status"] = "READY"
        return {**admitted, "status": state["status"]}

    @staticmethod
    def context(worker: WorkerLeaseCommand) -> EffectCommandContext:
        return EffectCommandContext(
            operation_id=worker.causation_id,
            project_id=worker.project_id,
            actor_id=worker.worker_id,
            trace_id=worker.trace_id,
            correlation_id=worker.correlation_id,
            causation_id=worker.causation_id,
        )

    def execute_fenced(self, worker: WorkerLeaseCommand) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            require_current_fence(uow, worker)
            operation = uow.repositories.chapter_authority.operation_execution(
                worker.causation_id, worker.project_id
            )
            uow.cursor.execute(
                "SELECT asset_version_id FROM authority_operation_output_asset WHERE operation_id=%s AND output_key='source.public_catalog.snapshot'",
                [worker.causation_id],
            )
            existing = uow.cursor.fetchone()
            if existing:
                return {"asset_version_id": existing[0], "replayed": True}
            command = operation["command_payload"]
            SourceAuthorityRepository(uow.cursor).require_scope(
                project_id=worker.project_id, workspace_id=command["workspace_id"]
            )
        capture = CatalogCapture.model_validate(command["payload"])
        adapter = self.adapter()
        effect = plan_external_effect(
            self.database_url,
            self.context(worker),
            effect_type="source.public_catalog.fetch",
            provider=adapter.provider,
            capability="source.remote.fetch",
            stable_idempotency_key="public-catalog:" + worker.causation_id,
            request_payload=capture.model_dump(mode="json"),
            max_attempts=2,
            reversible=False,
            completion_policy="synchronous_final",
            request_timeout_seconds=capture.max_pages
            * (capture.page_timeout_seconds + int(capture.minimum_interval_seconds))
            + 5,
            reconciliation_mode=adapter.reconciliation_mode,
            provider_capability_profile=adapter.capability_profile,
        )
        effect_id = effect["external_effect_id"]
        with AuthorityUnitOfWork(self.database_url) as uow:
            current = uow.repositories.external_effects.get_for_update(effect_id)
        if current["status"] in {
            "UNKNOWN",
            "RECONCILIATION_REQUIRED",
            "DISPATCHING",
            "DISPATCHED",
        }:
            result = reconcile_external_effect(
                self.database_url,
                self.context(worker),
                effect_id=effect_id,
                adapter=adapter,
                attempt_command=worker,
            )
            self._require_effect(result)
        elif current["status"] != "SUCCEEDED":
            if current["status"] in {"FAILED_FINAL", "CANCELLED", "DEAD_LETTER"}:
                raise KernelError(
                    "PUBLIC_CATALOG_CAPTURE_FAILED_FINAL",
                    str(current.get("last_error", "")),
                )
            result = dispatch_external_effect(
                self.database_url,
                self.context(worker),
                effect_id=effect_id,
                worker_id=worker.worker_id,
                lease_seconds=30,
                adapter=adapter,
            )
            self._require_effect(result)
        evidence = self._effect_evidence(effect_id, worker.project_id)
        identity = "public-catalog:" + worker.causation_id
        version = identity + ":v1"
        with AuthorityUnitOfWork(self.database_url) as uow:
            require_current_fence(uow, worker)
            uow.cursor.execute(
                "SELECT v.asset_version_id,v.content FROM authority_asset_version v JOIN authority_asset a USING(asset_id) WHERE a.project_id=%s AND a.asset_type='public_catalog_snapshot' AND v.content->>'url'=%s ORDER BY v.created_at DESC LIMIT 1",
                [worker.project_id, capture.url],
            )
            prior = uow.cursor.fetchone()
            content = {
                **evidence,
                "project_id": worker.project_id,
                "workspace_id": command["workspace_id"],
                "external_effect_id": effect_id,
                "trace_id": worker.trace_id,
                "rank_changes": rank_changes(evidence, prior[1] if prior else None),
                "previous_snapshot_asset_version_id": prior[0] if prior else None,
            }
            uow.repositories.chapter_authority.materialize_output(
                operation_id=worker.causation_id,
                project_id=worker.project_id,
                asset_id=identity,
                asset_version_id=version,
                qualification_id=version + ":contract",
                asset_type="public_catalog_snapshot",
                output_key="source.public_catalog.snapshot",
                role="evidence",
                content=content,
                content_hash=digest(
                    json.dumps(
                        content,
                        sort_keys=True,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode()
                ),
                qualification_policy="public-metadata-only.v1",
                qualification_evidence={
                    "attempt_id": worker.attempt_id,
                    "fencing_token": worker.fencing_token,
                    "generation_context_allowed": False,
                },
                lifecycle="ACTIVE",
                eligibility="INELIGIBLE",
                governance="CLEAR",
            )
            uow.repositories.operation_graph.record_event(
                {
                    "event_id": str(uuid4()),
                    "audit_id": str(uuid4()),
                    "outbox_id": str(uuid4()),
                    "aggregate_type": "authority_source_public_catalog",
                    "aggregate_id": identity,
                    "operation_id": worker.causation_id,
                    "project_id": worker.project_id,
                    "event_type": "authority.source.public_catalog.captured",
                    "correlation_id": worker.correlation_id,
                    "causation_id": worker.causation_id,
                    "payload": {
                        "operation_id": worker.causation_id,
                        "asset_version_id": version,
                        "external_effect_id": effect_id,
                        "trace_id": worker.trace_id,
                        "mode": capture.mode,
                    },
                }
            )
            uow.commit()
        return {
            "asset_version_id": version,
            "record_count": len(content["records"]),
            "mode": capture.mode,
        }

    def reconcile(self, worker: WorkerLeaseCommand) -> str:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                "SELECT external_effect_id FROM authority_external_effect WHERE operation_id=%s AND project_id=%s AND status IN ('UNKNOWN','RECONCILIATION_REQUIRED','DISPATCHING','DISPATCHED')",
                [worker.causation_id, worker.project_id],
            )
            effects = uow.cursor.fetchall()
        if not effects:
            raise KernelError(
                "PUBLIC_CATALOG_RECONCILIATION_REQUIRED",
                "no unresolved original Effect found",
            )
        for (effect_id,) in effects:
            self._require_effect(
                reconcile_external_effect(
                    self.database_url,
                    self.context(worker),
                    effect_id=effect_id,
                    adapter=self.adapter(),
                    attempt_command=worker,
                )
            )
        return "public_catalog_receipt_reconciliation"

    def _effect_evidence(self, effect_id: str, project_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                "SELECT CASE WHEN e.reconciliation<>'{}'::jsonb THEN e.reconciliation ELSE d.evidence END FROM authority_external_effect e LEFT JOIN LATERAL (SELECT evidence FROM authority_external_effect_dispatch WHERE external_effect_id=e.external_effect_id ORDER BY generation DESC LIMIT 1) d ON TRUE WHERE e.external_effect_id=%s AND e.project_id=%s AND e.status='SUCCEEDED'",
                [effect_id, project_id],
            )
            row = uow.cursor.fetchone()
        if not row or not isinstance(row[0], dict):
            raise KernelError(
                "PUBLIC_CATALOG_RECEIPT_MISSING",
                "capture lacks durable success evidence",
            )
        return row[0]

    @staticmethod
    def _require_effect(result: dict[str, Any]) -> None:
        if result["outcome"] == "success":
            return
        code = (
            "PUBLIC_CATALOG_RECONCILIATION_REQUIRED"
            if result["outcome"] in {"unknown", "not_found"}
            else "PUBLIC_CATALOG_CAPTURE_FAILED_FINAL"
        )
        raise KernelError(
            code, json.dumps(result.get("provider_evidence", {}), ensure_ascii=False)
        )

    def result(
        self, operation_id: str, project_id: str, *, replayed: bool
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                "SELECT o.status,v.asset_version_id,v.content FROM authority_operation o LEFT JOIN authority_operation_output_asset x ON x.operation_id=o.operation_id AND x.output_key='source.public_catalog.snapshot' LEFT JOIN authority_asset_version v USING(asset_version_id) WHERE o.operation_id=%s AND o.project_id=%s AND o.definition_name=%s",
                [operation_id, project_id, CATALOG_OPERATION],
            )
            row = uow.cursor.fetchone()
        if not row:
            raise KernelError(
                "PUBLIC_CATALOG_OPERATION_NOT_FOUND", "capture is outside scope"
            )
        return {
            "operation_id": operation_id,
            "project_id": project_id,
            "status": row[0],
            "asset_version_id": row[1],
            "snapshot": row[2],
            "replayed": replayed,
        }

    def snapshots(
        self, *, project_id: str, after: str = "", limit: int = 20
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise ValueError("catalog snapshot limit must be 1..100")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                "SELECT v.asset_version_id,v.content,v.content_hash FROM authority_asset_version v JOIN authority_asset a USING(asset_id) WHERE a.project_id=%s AND a.asset_type='public_catalog_snapshot' AND v.asset_version_id>%s ORDER BY v.asset_version_id LIMIT %s",
                [project_id, after, limit],
            )
            return [
                {"asset_version_id": row[0], "snapshot": row[1], "content_hash": row[2]}
                for row in uow.cursor.fetchall()
            ]

    def works(
        self,
        *,
        project_id: str,
        snapshot_id: str,
        category: str = "",
        serial_status: str = "",
        keyword: str = "",
        after: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 100 or len(keyword) > 200:
            raise ValueError("catalog query bounds are invalid")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                "SELECT v.content,v.content_hash FROM authority_asset_version v JOIN authority_asset a USING(asset_id) WHERE a.project_id=%s AND a.asset_type='public_catalog_snapshot' AND v.asset_version_id=%s",
                [project_id, snapshot_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "PUBLIC_CATALOG_SNAPSHOT_NOT_FOUND", "snapshot is outside project"
            )
        snapshot, content_hash = row
        records = [
            record
            for record in snapshot["records"]
            if (not category or record["category"] == category)
            and (not serial_status or record["serial_status"] == serial_status)
            and (
                not keyword
                or keyword.casefold()
                in (
                    record["title"]
                    + " "
                    + (record["author"] or "")
                    + " "
                    + (record["synopsis"] or "")
                ).casefold()
            )
        ]
        records.sort(key=lambda record: record["work_id"])
        remaining = [record for record in records if record["work_id"] > after]
        items = remaining[:limit]
        return {
            "snapshot_id": snapshot_id,
            "content_hash": content_hash,
            "mode": snapshot["mode"],
            "acquired_at": snapshot["acquired_at"],
            "data_time": snapshot["data_time"],
            "ranking_period": snapshot["ranking_period"],
            "items": items,
            "next_after": items[-1]["work_id"] if len(remaining) > limit else "",
            "matching_count": len(records),
        }
