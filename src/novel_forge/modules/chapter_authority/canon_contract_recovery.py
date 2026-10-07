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
              OR (o.definition_version='3.9.2' AND o.status IN ('DEAD_LETTER','FAILED_FINAL') AND a.result->>'error_code'='PROVIDER_ROUTING_BLOCKED')
              OR (o.definition_version='3.9.8' AND o.status IN ('DEAD_LETTER','FAILED_FINAL') AND a.result->>'error_code'='PROVIDER_ROUTING_BLOCKED')
              OR (o.definition_version IN ('3.9.3','3.9.4') AND o.status IN ('DEAD_LETTER','FAILED_FINAL') AND a.result->>'error_code' IN ('MODEL_EFFECT_RETRYABLE_PROCESS_EXIT_FAILURE','MODEL_EFFECT_FINAL_PROVIDER_SCHEMA_REJECTED')))""",
            [request["chapter_root_operation_id"], book["project_id"]])
        row = u.cursor.fetchone()
        if not row:
            return recover_support_contract(authority, book=book, request=request, template=template, principal=principal)
        source = row[0]
        if source["definition_version"] == "3.9.8":
            return _recover_source_capacity(authority, book, request, template, principal, source)
        u.cursor.execute("SELECT external_effect_id,request_hash FROM authority_external_effect WHERE operation_id=%s AND status='SUCCEEDED'", [source["operation_id"]])
        effects = u.cursor.fetchall()
        predispatch = source["definition_version"] in {"3.9.1", "3.9.2", "3.9.3", "3.9.4"}
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
    rejected_effects, rejection_proof = schema_rejection_receipts(authority.database_url, source) if source["definition_version"] in {"3.9.3", "3.9.4"} else ((), [])
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
        **({"schema_rejection_receipts": rejection_proof} if rejection_proof else {}),
        **({"capacity_rejection_decision_ids": [row["decision_id"] for row in capacity_evidence]} if capacity_evidence else {})}

    def guard(u):
        u.cursor.execute("SELECT version,active_chapter_request_id,accepted_through_chapter FROM authority_book_production WHERE book_run_id=%s FOR UPDATE", [book_run_id])
        if (u.cursor.fetchone() != (book["version"], book["active_chapter_request_id"], book["accepted_through_chapter"])
            or _cancelled(u.cursor, book)
            or selected_book_template(u.cursor, project_id=book["project_id"], book_id=book["book_id"]) != template):
            raise KernelError("CANON_CONTRACT_FRONTIER_CHANGED", "Reload the original Book frontier and authorization")

    replace_failed_step(authority.database_url, predecessor_id=source["operation_id"], target_version="3.9.5",
        context=AdmissionContext(principal.principal_id, principal.permissions,
            authority.chapter_port.application.registry.available_handler_keys, authority.application_build_id, authority.commit_sha),
        policy_evidence=evidence, expected_failure_code=(latest_failure_code(authority.database_url, source["operation_id"]) if rejection_proof else "PROVIDER_ROUTING_BLOCKED" if capacity_evidence else "CHAPTER_EXECUTION_CONTRACT_REBUILD_REQUIRED" if predispatch else "CANON_GROUNDING_INVALID"), transaction_guard=guard,
        known_receipt_effects=tuple(effects), known_rejected_effects=rejected_effects,
        window_successor=None if predispatch else {"contract_version": "kernel-corrected-contract-window.v1", "policy_key": "canon_evidence_span", "policy_value": "literal-source-spans.v1"})
    return True


def repair_diagnostics(request):
    if not request.database_url:
        return []
    with AuthorityUnitOfWork(request.database_url) as u:
        u.cursor.execute("SELECT policy_evidence FROM authority_saga_step_successor WHERE successor_operation_id=%s AND project_id=%s", [request.operation_id, request.project_id])
        row = u.cursor.fetchone()
    return row[0].get("repair_diagnostics", []) if row and row[0].get("contract_version") == CONTRACT else []


def capacity_rejection(decision, operation_id, *, schema_ref="schema:chapter-provider-output:canon_extraction:v24"):
    task = decision.get("task") or {}
    candidates = decision.get("candidates") or []
    return bool(decision.get("status") == "BLOCKED" and decision.get("selected") is None
        and task.get("operation_id") == operation_id and task.get("task_type") == "canon_extraction"
        and candidates and all(
            "CONTEXT_CAPACITY_EXCEEDED" in row.get("rejected_reasons", [])
            and set(row["rejected_reasons"]) <= {"CONTEXT_CAPACITY_EXCEEDED", "BUDGET_HARD_LIMIT"}
            and task.get("input_tokens", 0) + task.get("output_tokens", 0) > row["candidate"].get("context_limit", 0)
            and (task.get("producer_contract") or {}).get("output_schema", {}).get("ref") == schema_ref
            for row in candidates))


def _recover_source_capacity(authority, book, request, template, principal, source):
    with AuthorityUnitOfWork(authority.database_url) as u:
        u.cursor.execute("SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s) OR EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=%s)", [source["operation_id"], source["operation_id"]])
        if u.cursor.fetchone()[0]:
            return False
        u.cursor.execute("""SELECT v.content FROM authority_operation_output_asset o
            JOIN authority_asset a ON a.asset_id=o.asset_id JOIN authority_asset_version v ON v.asset_version_id=o.asset_version_id
            WHERE o.operation_id=%s AND a.asset_type='routing_decision' AND o.role='routing_evidence'""", [source["operation_id"]])
        decisions = [row[0] for row in u.cursor.fetchall()]
    if not decisions or not all(capacity_rejection(d, source["operation_id"], schema_ref="schema:chapter-provider-output:canon_extraction:v29") for d in decisions):
        return False
    def guard(u):
        u.cursor.execute("SELECT version,active_chapter_request_id,accepted_through_chapter FROM authority_book_production WHERE book_run_id=%s FOR UPDATE", [book["book_run_id"]])
        if (u.cursor.fetchone() != (book["version"], book["active_chapter_request_id"], book["accepted_through_chapter"])
            or _cancelled(u.cursor, book) or selected_book_template(u.cursor, project_id=book["project_id"], book_id=book["book_id"]) != template):
            raise KernelError("CANON_CONTRACT_FRONTIER_CHANGED", "Reload exact Book frontier and original authorization")
    replace_failed_step(authority.database_url, predecessor_id=source["operation_id"], target_version="3.9.9",
        context=AdmissionContext(principal.principal_id, principal.permissions,
            authority.chapter_port.application.registry.available_handler_keys, authority.application_build_id, authority.commit_sha),
        policy_evidence={"contract_version": "chapter-canon-source-capacity-successor.v1", "book_run_id": book["book_run_id"],
            "chapter_request_id": request["chapter_request_id"], "policy_admission": template,
            "capacity_rejection_decision_ids": [d["decision_id"] for d in decisions],
            "input_snapshot": source["input_asset_snapshot"], "external_dispatch": "NONE", "content_repairs": "UNCHANGED",
            "single_call_capacity": "UNCHANGED", "context_projection": "canon-source-context.v1"},
        expected_failure_code="PROVIDER_ROUTING_BLOCKED", transaction_guard=guard,
        window_successor={"contract_version": "kernel-corrected-contract-window.v1", "policy_key": "canon_context_projection", "policy_value": "canon-source-context.v1"})
    return True


def latest_failure_code(database_url, operation_id):
    with AuthorityUnitOfWork(database_url) as u:
        u.cursor.execute("SELECT result->>'error_code' FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number DESC LIMIT 1", [operation_id])
        return u.cursor.fetchone()[0]


def schema_rejection_receipts(database_url, source):
    from hashlib import sha256
    from pathlib import Path
    from novel_forge.modules.production_execution.backends import codex_protocol_failure
    query = AuthorityAssetQuery(database_url)
    with AuthorityUnitOfWork(database_url) as u:
        u.cursor.execute("""SELECT to_jsonb(e),b.status,b.accounting_basis FROM authority_external_effect e
            JOIN authority_budget_reservation b USING(external_effect_id) WHERE e.operation_id=%s ORDER BY e.external_effect_id""", [source["operation_id"]])
        effects = u.cursor.fetchall()
    identities, proofs = [], []
    for effect, settled, accounting in effects:
        production = (effect.get("last_error") or {}).get("production_execution") or {}
        result = production.get("execution_result") or {}
        ref = result.get("process_receipt_ref") or ""
        if (effect["status"] not in {"FAILED_RETRYABLE", "FAILED_FINAL"} or settled != "SETTLED"
            or accounting != "ACCOUNT_ENTITLEMENT"
            or (effect.get("last_error") or {}).get("provider_id") != "codex-cli"
            or not ref.startswith("authority-asset-version:")):
            raise KernelError("CANON_SCHEMA_REJECTION_UNRECONCILED", "Reconcile every exact rejection; paid unknown outcomes remain occupied")
        receipt = query.require(project_id=source["project_id"], asset_version_id=ref.removeprefix("authority-asset-version:"))
        if receipt.content.get("kind") != "process-receipt" or receipt.content.get("contract_version") != "authority-execution-evidence.v1":
            raise KernelError("CANON_SCHEMA_REJECTION_UNRECONCILED", "Native immutable process evidence is required")
        content = receipt.content["payload"]
        expected = ((effect["request_payload"].get("_production_execution") or {}).get("capability_runtime") or {}).get("provider_admission", {}).get("input_component_hashes", {}).get("fully_rendered_prompt", "")
        directory = Path(content["execution_directory"]).resolve()
        stdout = Path(content["stdout_path"]).resolve()
        if (content.get("status") != "FAILED" or content.get("operation_id") != source["operation_id"]
            or content.get("execution_id") != "chapter-execution:" + effect["external_effect_id"]
            or "sha256:" + str(content.get("input_sha256")) != expected or stdout.parent != directory):
            raise KernelError("CANON_SCHEMA_REJECTION_UNRECONCILED", "The process receipt must bind the exact failed execution and rendered input")
        raw = stdout.read_bytes()
        if len(raw) > 262144 or codex_protocol_failure(raw.decode("utf-8")) != "PROVIDER_SCHEMA_REJECTED":
            raise KernelError("CANON_SCHEMA_REJECTION_UNRECONCILED", "Only a typed service Schema rejection supports corrected-contract continuation")
        identities.append((effect["external_effect_id"], effect["request_hash"], receipt.asset_version_id, receipt.content_hash))
        proofs.append({"external_effect_id": effect["external_effect_id"], "process_receipt_asset_version_id": receipt.asset_version_id,
            "process_receipt_hash": receipt.content_hash, "stdout_hash": "sha256:" + sha256(raw).hexdigest(),
            "outcome": "PROVIDER_SCHEMA_REJECTED", "consumption": "ORIGINAL_CONSERVATIVE_MEMBERSHIP_USAGE_PRESERVED"})
    if not identities:
        raise KernelError("CANON_SCHEMA_REJECTION_UNRECONCILED", "A recorded rejection is required")
    return tuple(identities), proofs


def recover_support_contract(authority, *, book, request, template, principal):
    from novel_forge.modules.canon_graph.grounding import grounded_claims
    with AuthorityUnitOfWork(authority.database_url) as u:
        u.cursor.execute("""SELECT to_jsonb(o) FROM authority_operation o JOIN authority_saga_step s USING(operation_id)
            JOIN authority_attempt a USING(operation_id) WHERE o.root_operation_id=%s
            AND o.definition_name='chapter.canon.propose_changes' AND o.definition_version='3.9.0'
            AND o.status IN ('DEAD_LETTER','FAILED_FINAL') AND a.result->>'error_code' IN
            ('CANON_GROUNDING_REEXTRACTION_REQUIRED','CANON_SUPPORT_SCHEMA_REBUILD_REQUIRED') LIMIT 1""",
            [request["chapter_root_operation_id"]])
        row = u.cursor.fetchone()
        if not row:
            return False
        source = row[0]
        u.cursor.execute("SELECT e.external_effect_id,e.request_hash,e.status,b.status FROM authority_external_effect e JOIN authority_budget_reservation b USING(external_effect_id) WHERE e.operation_id=%s ORDER BY e.created_at", [source["operation_id"]])
        effects = u.cursor.fetchall()
        if not effects or any(row[2:] != ("SUCCEEDED", "SETTLED") for row in effects):
            raise KernelError("CANON_SUPPORT_RECONCILIATION_REQUIRED", "Reconcile every original support effect before contract correction")
        receipts = [_receipt(u.cursor, row[0], book["project_id"]) for row in effects]
    assets = [AuthorityAssetQuery(authority.database_url).require(project_id=book["project_id"], asset_version_id=a["asset_version_id"]) for a in source["input_asset_snapshot"]]
    extraction = next(a for a in assets if a.asset_type == "canon_extraction")
    claims = {row["claim"]["grounded_claim_id"]: row["claim"]["claim_kind"] for row in grounded_claims(extraction.content)}
    diagnostics = []
    taxonomy = {"OBJECTIVE_EVENT", "OBJECTIVE_STATE", "KNOWLEDGE_ACQUISITION", "BELIEF", "SUSPICION",
        "HEARSAY", "DIALOGUE_ASSERTION", "READER_DISCLOSURE", "NARRATIVE_OBSERVATION"}
    for result in receipts:
        rows = result.output.get("claims") or []
        if (result.output.get("coverage") != "COMPLETE" or len(rows) != len(claims)
            or {r.get("claim_id") for r in rows} != set(claims)
            or any(r.get("assessment") != "SUPPORTED" or not r.get("reason") for r in rows)):
            return False
        unknown = [{"claim_id": r["claim_id"], "observed_kind": r.get("observed_kind"), "expected_taxonomy": sorted(taxonomy)} for r in rows if r.get("observed_kind") not in taxonomy]
        if not unknown:
            return False
        diagnostics.extend(unknown)
    evidence = {"contract_version": "chapter-canon-support-contract-successor.v1", "book_run_id": book["book_run_id"],
        "chapter_request_id": request["chapter_request_id"], "policy_admission": template,
        "repair_diagnostics": diagnostics, "completion_checks": "UNCHANGED", "unsupported_claims_bypassed": False}
    def guard(u):
        u.cursor.execute("SELECT version,active_chapter_request_id,accepted_through_chapter FROM authority_book_production WHERE book_run_id=%s FOR UPDATE", [book["book_run_id"]])
        if (u.cursor.fetchone() != (book["version"], book["active_chapter_request_id"], book["accepted_through_chapter"])
            or _cancelled(u.cursor, book) or selected_book_template(u.cursor, project_id=book["project_id"], book_id=book["book_id"]) != template):
            raise KernelError("CANON_CONTRACT_FRONTIER_CHANGED", "Reload the original Book frontier and authorization")
    replace_failed_step(authority.database_url, predecessor_id=source["operation_id"], target_version="3.9.1",
        context=AdmissionContext(principal.principal_id, principal.permissions, authority.chapter_port.application.registry.available_handler_keys,
            authority.application_build_id, authority.commit_sha), policy_evidence=evidence,
        expected_failure_code=latest_failure_code(authority.database_url, source["operation_id"]), transaction_guard=guard,
        known_receipt_effects=tuple(row[:2] for row in effects),
        window_successor={"contract_version": "kernel-corrected-contract-window.v1", "policy_key": "canon_support_kinds", "policy_value": "canon-claim-kinds.v1"})
    return True


def recover_completed_canon_window(authority, *, book_run_id, principal):
    from .scheduler import reader_lineage_reassessment_required
    from novel_forge.modules.command_kernel.step_successor import continue_completed_contract_window
    book = authority.require(book_run_id)
    principal.require("book.authority.execute", book["project_id"])
    principal.require("chapter.authority.execute", book["project_id"])
    if book["state"] != "CHAPTER_RUNNING" or not book.get("active_chapter_request_id"):
        return False
    request = authority.require_chapter_request(book["active_chapter_request_id"])
    with AuthorityUnitOfWork(authority.database_url) as u:
        template = selected_book_template(u.cursor, project_id=book["project_id"], book_id=book["book_id"])
        if not template or _cancelled(u.cursor, book) or request["chapter_number"] != book["accepted_through_chapter"] + 1:
            return False
        u.cursor.execute("""SELECT old.operation_id,new.operation_id,old_asset.content,new_asset.content
            FROM authority_operation new JOIN authority_operation_dependency dep ON dep.operation_id=new.operation_id
            JOIN authority_operation old ON old.operation_id=dep.depends_on_operation_id
            JOIN authority_operation_output_asset old_output ON old_output.operation_id=old.operation_id AND old_output.output_key='chapter.canon'
            JOIN authority_asset_version old_asset ON old_asset.asset_version_id=old_output.asset_version_id
            JOIN authority_operation_output_asset new_output ON new_output.operation_id=new.operation_id AND new_output.output_key='chapter.canon'
            JOIN authority_asset_version new_asset ON new_asset.asset_version_id=new_output.asset_version_id
            WHERE new.root_operation_id=%s AND old.definition_name='chapter.canon.update' AND new.definition_name=old.definition_name
            AND old.definition_version='3.9.0' AND new.definition_version='3.9.1' AND old.status='SUCCEEDED' AND new.status='SUCCEEDED'
            AND dep.dependency_condition='ON_SUCCESS'""", [request["chapter_root_operation_id"]])
        row = u.cursor.fetchone()
    if not row or not reader_lineage_reassessment_required(row[2]) or row[3].get("gate") != "PASSED":
        return False
    def guard(u):
        u.cursor.execute("SELECT version,active_chapter_request_id,accepted_through_chapter FROM authority_book_production WHERE book_run_id=%s FOR UPDATE", [book_run_id])
        if (u.cursor.fetchone() != (book["version"], book["active_chapter_request_id"], book["accepted_through_chapter"])
            or _cancelled(u.cursor, book) or selected_book_template(u.cursor, project_id=book["project_id"], book_id=book["book_id"]) != template):
            raise KernelError("CANON_CONTRACT_FRONTIER_CHANGED", "Reload the original Book frontier and authorization")
    try:
        result = continue_completed_contract_window(authority.database_url, predecessor_id=row[0], successor_id=row[1],
            context=AdmissionContext(principal.principal_id, principal.permissions,
                authority.chapter_port.application.registry.available_handler_keys, authority.application_build_id, authority.commit_sha),
            policy={"contract_version": "kernel-corrected-contract-window.v1", "policy_key": "reader_observation_lineage", "policy_value": "reader-disclosure-observation.v1"},
            transaction_guard=guard)
    except KernelError as error:
        if error.code == "STEP_SUCCESSOR_WINDOW_UNSETTLED":
            return False
        raise
    return not result["replayed"]


def guard_reader_window_frontier(uow, *, root_operation_id, project_id, book_id, chapter):
    uow.cursor.execute("""SELECT to_jsonb(b),r.chapter_number FROM authority_book_production b
        JOIN authority_book_chapter_request r ON r.chapter_request_id=b.active_chapter_request_id
        WHERE r.chapter_root_operation_id=%s AND b.project_id=%s AND b.book_id=%s FOR UPDATE OF b""",
        [root_operation_id, project_id, book_id])
    row = uow.cursor.fetchone()
    if (not row or row[0]["state"] != "CHAPTER_RUNNING" or row[1] != chapter
        or row[0]["accepted_through_chapter"] + 1 != chapter or _cancelled(uow.cursor, row[0])
        or not selected_book_template(uow.cursor, project_id=project_id, book_id=book_id)):
        raise KernelError("CANON_CONTRACT_FRONTIER_CHANGED", "A live authorized original Book frontier is required")
