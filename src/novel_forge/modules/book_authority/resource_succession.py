from __future__ import annotations

from typing import Any, Mapping
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import AdmissionContext, execute_transaction_command
from novel_forge.modules.production_execution.execution_template import selected_book_template, verify_book_template
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


NAME = "book.opening.adopt_resource_policy"
VERSION = "book-opening-resource-successor.v1"


def adopt_resource_policy(application: Any, *, opening_run_id: str, principal: Any,
                          expected_version: int, idempotency_key: str) -> dict[str, Any]:
    from .opening import _opening_definition
    from novel_forge.modules.command_kernel.budget_runtime import canonical_budget_policy

    run = application.require(opening_run_id)
    project = run["project_id"]
    principal.require("book.authority.execute", project)
    policy = canonical_budget_policy(application.provider_budget_policy)
    if policy["policy_snapshot"].get("resource_control_version") != "billing-channel-resources.v1":
        raise KernelError("RESOURCE_SUCCESSOR_POLICY_REQUIRED", opening_run_id)
    definition = _opening_definition(NAME, application_build_id=application.application_build_id, commit_sha=application.commit_sha)
    schema = {"type": "object", "additionalProperties": False,
        "required": ["project_id", "book_id", "opening_run_id", "expected_version", "resource_policy"],
        "properties": {"project_id": {"type": "string"}, "book_id": {"type": "string"},
            "opening_run_id": {"type": "string"}, "expected_version": {"type": "integer", "minimum": 0},
            "resource_policy": {"type": "object"}}}
    definition.update(command_schema=schema, input_contract=schema,
        command_schema_version=VERSION, result_schema_version=VERSION)
    with AuthorityUnitOfWork(application.database_url) as uow:
        uow.repositories.definitions.register(definition)
        uow.commit()

    def handler(uow, operation_id, checkpoint):
        application.recovery._lock_opening(uow, opening_run_id)
        uow.cursor.execute("SELECT source_policy_hash,resource_policy,execution_template,operation_id FROM authority_book_opening_resource_successor WHERE opening_run_id=%s", [opening_run_id])
        prior = uow.cursor.fetchone()
        if prior:
            if prior[1] != policy:
                raise KernelError("RESOURCE_SUCCESSOR_CONFLICT", opening_run_id)
            return {"version": VERSION, "opening_run_id": opening_run_id, "source_policy_hash": prior[0],
                "resource_policy": prior[1], "execution_template": prior[2], "successor_operation_id": prior[3]}
        uow.cursor.execute("""SELECT version,lifecycle,budget_scope_id,frozen_request->>'actor_id'
            FROM authority_book_opening_run WHERE opening_run_id=%s AND project_id=%s FOR UPDATE""", [opening_run_id, project])
        current = uow.cursor.fetchone()
        if (not current or current[0] != expected_version or current[1] in {"COMPLETE", "ABORTED"}
                or not current[2] or current[3] != principal.principal_id):
            raise KernelError("RESOURCE_SUCCESSOR_PRECONDITION_INVALID", opening_run_id)
        uow.cursor.execute("""WITH RECURSIVE owned(operation_id) AS (
            SELECT operation_id FROM authority_operation WHERE project_id=%s AND (operation_id=%s
                OR COALESCE(command_payload #>> '{payload,opening_execution_binding,opening_run_id}',
                            command_payload #>> '{opening_execution_binding,opening_run_id}')=%s)
            UNION SELECT child.operation_id FROM authority_operation child JOIN owned parent ON child.causation_operation_id=parent.operation_id
            WHERE child.project_id=%s)
            SELECT EXISTS(SELECT 1 FROM authority_budget_reservation WHERE budget_scope_id=%s AND status IN ('RESERVED','HELD_UNKNOWN') AND NOT authority_generation_isolated(external_effect_id))
            OR EXISTS(SELECT 1 FROM authority_external_effect effect WHERE effect.operation_id IN (SELECT operation_id FROM owned)
                AND NOT authority_generation_isolated(effect.external_effect_id) AND effect.status IN ('READY','DISPATCHING','DISPATCHED','UNKNOWN','FAILED_RETRYABLE','RECONCILIATION_REQUIRED','CANCELLATION_REQUESTED'))
            OR EXISTS(SELECT 1 FROM authority_runtime_job job JOIN authority_runtime_job_lease lease USING(runtime_job_id)
                WHERE job.subject_kind='BOOK_OPENING_RUN' AND job.subject_id=%s AND lease.status='HELD' AND lease.lease_expires_at>clock_timestamp())""",
            [project, run["root_operation_id"], opening_run_id, project, current[2], opening_run_id])
        if uow.cursor.fetchone()[0]:
            raise KernelError("RESOURCE_SUCCESSOR_RECONCILIATION_REQUIRED", opening_run_id)
        admission = selected_book_template(uow.cursor, project_id=project, book_id=run["book_id"])
        if admission is None:
            raise KernelError("EXECUTION_TEMPLATE_PROVENANCE_INVALID", run["book_id"])
        from novel_forge.modules.production_execution.execution_template import decision_template
        template = decision_template({"task": {"work_id": run["book_id"], "policy_snapshot": admission["policy_snapshot"]}})
        if template["member_authorization_ref"] != policy["policy_snapshot"]["authorization_ref"]:
            raise KernelError("MEMBERSHIP_BILLING_IDENTITY_MISMATCH", run["book_id"])
        uow.cursor.execute("SELECT policy_hash,policy_snapshot FROM authority_provider_budget_scope WHERE budget_scope_id=%s FOR SHARE", [current[2]])
        source_hash, source_policy = uow.cursor.fetchone()
        if source_policy.get("resource_control_version") == "billing-channel-resources.v1":
            raise KernelError("RESOURCE_SUCCESSOR_NOT_REQUIRED", opening_run_id)
        result = {"version": VERSION, "opening_run_id": opening_run_id, "source_policy_hash": source_hash,
            "resource_policy": policy, "execution_template": admission, "successor_operation_id": operation_id}
        uow.cursor.execute("""INSERT INTO authority_book_opening_resource_successor
            (opening_run_id,project_id,book_id,budget_scope_id,source_policy_hash,resource_policy,execution_template,operation_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""", [opening_run_id, project, run["book_id"], current[2], source_hash,
                Jsonb(policy), Jsonb(admission), operation_id])
        checkpoint("after_resource_successor_insert")
        uow.repositories.operation_graph.record_event({"event_id": str(uuid4()), "audit_id": str(uuid4()), "outbox_id": str(uuid4()),
            "aggregate_type": "book_opening_run", "aggregate_id": opening_run_id, "operation_id": operation_id,
            "project_id": project, "event_type": "book.opening.transitioned", "correlation_id": opening_run_id,
            "causation_id": operation_id, "payload": {"operation_id": operation_id, **result}})
        return result

    return execute_transaction_command(application.database_url,
        {"definition_name": NAME, "definition_version": definition["definition_version"], "project_id": project,
            "workspace_id": run["workspace_id"], "book_id": run["book_id"], "actor_id": principal.principal_id, "idempotency_scope": "book:opening",
            "idempotency_key": idempotency_key, "trace_id": "trace:" + idempotency_key, "span_id": str(uuid4()),
            "correlation_id": opening_run_id, "causation_id": run["root_operation_id"], "input_assets": [],
            "input": {"project_id": project, "book_id": run["book_id"], "opening_run_id": opening_run_id,
                "expected_version": expected_version, "resource_policy": policy}},
        context=AdmissionContext(actor_id=principal.principal_id, permissions=principal.permissions,
            available_handlers=frozenset({definition["handler_key"]}), application_build_id=application.application_build_id,
            commit_sha=application.commit_sha), handler=handler)


def prospective_scope(uow: Any, scope: Mapping[str, Any], *, operation_id: str = "") -> dict[str, Any]:
    if scope["policy_snapshot"].get("resource_control_version") == "billing-channel-resources.v1":
        return dict(scope)
    uow.cursor.execute("""SELECT successor.resource_policy,successor.execution_template,successor.source_policy_hash,successor.operation_id
        FROM authority_book_opening_resource_successor successor JOIN authority_operation adopted ON adopted.operation_id=successor.operation_id
        WHERE successor.budget_scope_id=%s AND successor.project_id=%s AND adopted.status='SUCCEEDED'
          AND (%s='' OR EXISTS(SELECT 1 FROM authority_operation work WHERE work.operation_id=%s AND work.project_id=successor.project_id
            AND work.created_at>adopted.created_at))""", [scope["budget_scope_id"], scope["project_id"], operation_id, operation_id])
    row = uow.cursor.fetchone()
    if not row:
        return dict(scope)
    verify_book_template(uow.cursor, row[1])
    from novel_forge.modules.command_kernel.budget_runtime import canonical_budget_policy
    if row[2] != scope["policy_hash"] or canonical_budget_policy(row[0]["policy_snapshot"]) != row[0]:
        raise KernelError("RESOURCE_SUCCESSOR_PROVENANCE_INVALID", scope["owner_id"])
    return {**dict(scope), **row[0], "currency": "UNKNOWN", "policy_contract_version": VERSION,
        "resource_successor": {"operation_id": row[3], "source_policy_hash": row[2],
            "source_policy_snapshot": scope["policy_snapshot"], "execution_template": row[1]}}


def prospective_topology(uow: Any, *, opening_run_id: str, original: Any) -> Any:
    from novel_forge.modules.command_kernel.budget_runtime import lock_budget_scope_in_uow
    from .opening_workflow import assess_book_opening_topology_budget
    uow.cursor.execute("SELECT budget_scope_id,project_id FROM authority_book_opening_run WHERE opening_run_id=%s", [opening_run_id])
    identity = uow.cursor.fetchone()
    scope = lock_budget_scope_in_uow(uow, budget_scope_id=identity[0], project_id=identity[1])
    selected = prospective_scope(uow, scope)
    if not selected.get("resource_successor"):
        return original
    return assess_book_opening_topology_budget(policy_contract_version=selected["policy_contract_version"],
        policy_hash=selected["policy_hash"], policy=selected["policy_snapshot"], arc_count=original.arc_count)
