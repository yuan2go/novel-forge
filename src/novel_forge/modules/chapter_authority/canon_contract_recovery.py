from __future__ import annotations

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import AdmissionContext
from novel_forge.modules.command_kernel.step_successor import replace_failed_step
from novel_forge.modules.production_execution.execution_template import selected_book_template
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .contract_recovery import _cancelled
from .receipt_recovery import _receipt

CONTRACT = "chapter-canon-span-successor.v1"


def recover_canon_contract(authority, *, book_run_id, principal):
    book = authority.require(book_run_id)
    principal.require("book.authority.execute", book["project_id"])
    principal.require("chapter.authority.execute", book["project_id"])
    if book["state"] not in {"CHAPTER_RUNNING", "CHAPTER_SUBMITTED", "CHAPTER_WAITING_RETRY"} or not book.get("active_chapter_request_id"):
        return False
    request = authority.require_chapter_request(book["active_chapter_request_id"])
    if request["chapter_number"] != book["accepted_through_chapter"] + 1:
        return False
    with AuthorityUnitOfWork(authority.database_url) as u:
        template = selected_book_template(u.cursor, project_id=book["project_id"], book_id=book["book_id"])
        if not template or _cancelled(u.cursor, book):
            return False
        u.cursor.execute("""SELECT to_jsonb(o) FROM authority_operation o JOIN authority_saga_step s USING(operation_id)
            JOIN authority_attempt a USING(operation_id) WHERE o.root_operation_id=%s AND o.project_id=%s
            AND o.definition_name='chapter.canon.extract'
            AND ((o.definition_version='3.9.0' AND o.status='FAILED_FINAL' AND a.result->>'error_code'='CANON_GROUNDING_INVALID')
              OR (o.definition_version='3.9.1' AND o.status IN ('DEAD_LETTER','FAILED_FINAL') AND a.result->>'error_code'='CHAPTER_EXECUTION_CONTRACT_REBUILD_REQUIRED')
              OR (o.definition_version='3.9.2' AND o.status IN ('DEAD_LETTER','FAILED_FINAL') AND a.result->>'error_code'='PROVIDER_ROUTING_BLOCKED'))""",
            [request["chapter_root_operation_id"], book["project_id"]])
        row = u.cursor.fetchone()
        if not row:
            return False
        source = row[0]
        u.cursor.execute("SELECT external_effect_id,request_hash FROM authority_external_effect WHERE operation_id=%s AND status='SUCCEEDED'", [source["operation_id"]])
        effects = u.cursor.fetchall()
        predispatch = source["definition_version"] in {"3.9.1", "3.9.2"}
        capacity_evidence = []
        if source["definition_version"] == "3.9.2":
            u.cursor.execute("""SELECT v.content FROM authority_operation_output_asset o
                JOIN authority_asset a USING(asset_id) JOIN authority_asset_version v ON v.asset_version_id=o.asset_version_id
                WHERE o.operation_id=%s AND a.asset_type='routing_decision' AND o.role='routing_evidence'""", [source["operation_id"]])
            capacity_evidence = [row[0] for row in u.cursor.fetchall()]
            if not capacity_evidence or not all(capacity_rejection(row, source["operation_id"]) for row in capacity_evidence):
                return False
        previous_evidence = None
        if predispatch:
            u.cursor.execute("SELECT policy_evidence,source_failure_snapshot FROM authority_saga_step_successor WHERE successor_operation_id=%s", [source["operation_id"]])
            prior = u.cursor.fetchone()
            if (not prior or prior[0].get("contract_version") != CONTRACT or effects
                or prior[1]["operation"]["input_asset_snapshot"] != source["input_asset_snapshot"]):
                raise KernelError("CANON_CONTRACT_SOURCE_INVALID", "Only the recorded undispatched interface successor may continue")
            previous_evidence = prior[0]
        elif len(effects) != 1:
            raise KernelError("CANON_CONTRACT_RECONCILIATION_REQUIRED", "One exact succeeded source receipt is required")
        result = _receipt(u.cursor, (previous_evidence["source_effect_id"] if predispatch else effects[0][0]), book["project_id"])
    inputs = [AuthorityAssetQuery(authority.database_url).require(project_id=book["project_id"], asset_version_id=a["asset_version_id"]) for a in source["input_asset_snapshot"]]
    revision = next(a for a in inputs if a.asset_type == "best_draft_candidate")
    context = next(a for a in inputs if a.asset_type == "context_bundle")
    from novel_forge.modules.canon_graph.source_spans import extraction_diagnostics
    from novel_forge.modules.canon_graph.background import scheduled_world_events
    binding = (context.content.get("chapter_execution_expectations") or {}).get("world_preparation") or {}
    agency = bool(binding and any(event.get("action_mode") for event in scheduled_world_events(binding)))
    diagnostics = extraction_diagnostics(result.output, revision.content["text"], agency=agency)
    if not diagnostics:
        raise KernelError("CANON_CONTRACT_DEFECT_UNPROVEN", "The source receipt must expose the corrected interface defect")
    evidence = {"contract_version": CONTRACT, "book_run_id": book_run_id,
        "chapter_request_id": request["chapter_request_id"], "policy_admission": template,
        "source_effect_id": previous_evidence["source_effect_id"] if predispatch else effects[0][0],
        "source_request_hash": previous_evidence["source_request_hash"] if predispatch else effects[0][1],
        "repair_diagnostics": diagnostics, "completion_checks": "UNCHANGED",
        "source_candidate_asset_version_id": revision.asset_version_id,
        "source_candidate_content_hash": revision.content_hash,
        **({"capacity_rejection_decision_ids": [row["decision_id"] for row in capacity_evidence]} if capacity_evidence else {})}

    def guard(u):
        u.cursor.execute("SELECT version,active_chapter_request_id,accepted_through_chapter FROM authority_book_production WHERE book_run_id=%s FOR UPDATE", [book_run_id])
        if (u.cursor.fetchone() != (book["version"], book["active_chapter_request_id"], book["accepted_through_chapter"])
            or _cancelled(u.cursor, book)
            or selected_book_template(u.cursor, project_id=book["project_id"], book_id=book["book_id"]) != template):
            raise KernelError("CANON_CONTRACT_FRONTIER_CHANGED", "Reload the original Book frontier and authorization")

    replace_failed_step(authority.database_url, predecessor_id=source["operation_id"], target_version="3.9.3",
        context=AdmissionContext(principal.principal_id, principal.permissions,
            authority.chapter_port.application.registry.available_handler_keys, authority.application_build_id, authority.commit_sha),
        policy_evidence=evidence, expected_failure_code=("PROVIDER_ROUTING_BLOCKED" if capacity_evidence else "CHAPTER_EXECUTION_CONTRACT_REBUILD_REQUIRED" if predispatch else "CANON_GROUNDING_INVALID"), transaction_guard=guard,
        known_receipt_effects=tuple(effects),
        window_successor=None if predispatch else {"contract_version": "kernel-corrected-contract-window.v1", "policy_key": "canon_evidence_span", "policy_value": "literal-source-spans.v1"})
    return True


def repair_diagnostics(request):
    if not request.database_url:
        return []
    with AuthorityUnitOfWork(request.database_url) as u:
        u.cursor.execute("SELECT policy_evidence FROM authority_saga_step_successor WHERE successor_operation_id=%s AND project_id=%s", [request.operation_id, request.project_id])
        row = u.cursor.fetchone()
    return row[0].get("repair_diagnostics", []) if row and row[0].get("contract_version") == CONTRACT else []


def capacity_rejection(decision, operation_id):
    task = decision.get("task") or {}
    candidates = decision.get("candidates") or []
    return bool(decision.get("status") == "BLOCKED" and decision.get("selected") is None
        and task.get("operation_id") == operation_id and task.get("task_type") == "canon_extraction"
        and candidates and all(
            "CONTEXT_CAPACITY_EXCEEDED" in row.get("rejected_reasons", [])
            and set(row["rejected_reasons"]) <= {"CONTEXT_CAPACITY_EXCEEDED", "BUDGET_HARD_LIMIT"}
            and task.get("input_tokens", 0) + task.get("output_tokens", 0) > row["candidate"].get("context_limit", 0)
            and (task.get("producer_contract") or {}).get("output_schema", {}).get("ref") == "schema:chapter-provider-output:canon_extraction:v24"
            for row in candidates))
