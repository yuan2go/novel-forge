from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from novel_forge.modules.chapter_authority.author_editor import text_hash
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.domain import canonical_hash
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

CONTRACT = "retained-working-continuation.v1"
FAILURE = "MODEL_EFFECT_FINAL_UNAUTHORIZED_TOOL_INVOCATION"


def require_empty_discovery_trace(stdout: str) -> dict:
    from novel_forge.modules.production_execution.codex_configuration import strict_codex_json_loads

    events = [strict_codex_json_loads(line) for line in stdout.splitlines() if line.strip()]
    started, completed = {}, {}
    expected = {"list_mcp_resources": {"resources": []}, "list_mcp_resource_templates": {"resourceTemplates": []}}
    for event in events:
        if event.get("type") in {"thread.started", "turn.started", "turn.completed"}:
            continue
        item = event.get("item") or {}
        if event.get("type") not in {"item.started", "item.completed"}:
            raise KernelError("RETAINED_WORKING_TOOL_TRACE_UNSAFE", "Unknown or failed trace events remain ineligible")
        if item.get("type") in {"agent_message", "reasoning", "error"}:
            continue
        target = started if event.get("type") == "item.started" else completed if event.get("type") == "item.completed" else None
        if (target is None or item.get("type") != "mcp_tool_call" or item.get("server") != "codex"
                or item.get("tool") not in expected or item.get("arguments") not in ({}, None)
                or not item.get("id") or item["id"] in target
                or target is completed and item["id"] not in started):
            raise KernelError("RETAINED_WORKING_TOOL_TRACE_UNSAFE", "Only complete empty metadata discovery may support unaccepted working use")
        target[item["id"]] = item
    if (len(started) != 2 or set(started) != set(completed)
            or {item["tool"] for item in completed.values()} != set(expected)
            or sum(event.get("type") == "turn.completed" for event in events) != 1):
        raise KernelError("RETAINED_WORKING_TOOL_TRACE_UNSAFE", "Require the complete original discovery and terminal trace")
    for identity, item in completed.items():
        result = item.get("result") or {}
        content = result.get("content")
        if (item.get("status") != "completed" or item.get("error") is not None
                or started[identity]["tool"] != item["tool"]
                or not isinstance(content, list) or len(content) != 1
                or set(result) - {"content", "structured_content", "isError"}
                or set(content[0]) != {"type", "text"} or content[0].get("type") != "text"
                or strict_codex_json_loads(content[0].get("text", "null")) != expected[item["tool"]]
                or result.get("structured_content") is not None or result.get("isError", False)):
            raise KernelError("RETAINED_WORKING_TOOL_TRACE_UNSAFE", "A resource, error, incomplete call or other Tool remains ineligible")
    return {"contract_version": "empty-metadata-discovery-evidence.v1", "stdout_sha256": "sha256:" + sha256(stdout.encode()).hexdigest(),
            "calls": [{"call_id": key, "server": value["server"], "tool": value["tool"],
                       "result": expected[value["tool"]]} for key, value in sorted(completed.items())],
            "external_resource_count": 0, "permission_gate": "VIOLATED_UNCHANGED"}



def _require_governed(document, expected_hash=None):
    if (document.content_hash != canonical_hash(document.content)
            or expected_hash is not None and document.content_hash != expected_hash
            or document.lifecycle not in {"ACTIVE", "SUPERSEDED"}
            or document.governance != "CLEAR" or document.eligibility != "ELIGIBLE"):
        raise KernelError("RETAINED_WORKING_INPUT_CHANGED", "Require intact currently governed original inputs")


def require_original_contract(recovery, *, payload, effect, dispatch, admission):
    from novel_forge.modules.production_execution.contracts import ExecutionRequest

    record = recovery.get("record") or {}
    original = ExecutionRequest.from_dict(record.get("request") or {})
    frozen = record.get("frozen_output_contract") or {}
    evidence = dispatch.get("evidence") or {}
    execution = evidence.get("production_execution") or {}
    capability = evidence.get("capability_runtime") or {}
    process = record.get("process_receipt") or {}
    process_evidence = execution.get("process_evidence") or {}
    schema_hash = canonical_hash(frozen.get("output_schema"))
    if (recovery.get("contract_version") != "authority-execution-recovery.v1"
            or recovery.get("execution_id") != original.execution_id
            or recovery.get("request_contract_hash") != original.contract_hash
            or payload.get("request_contract_hash") != original.contract_hash
            or recovery.get("record_state_hash") != canonical_hash(record)[7:]
            or original.external_effect_id != effect["external_effect_id"]
            or original.operation_id != effect["operation_id"]
            or original.stable_idempotency_key != effect["stable_idempotency_key"]
            or original.project_id != payload["project_id"] or original.book_id != payload["book_id"]
            or any(original.to_dict().get(key) != payload.get(key) for key in ("attempt_id", "fencing_token", "operation_id"))
            or dispatch.get("status") != "FAILED_FINAL" or effect.get("last_error") != evidence
            or canonical_hash(effect["request_payload"]) != effect["request_hash"]
            or dispatch.get("payload_hash") != effect["request_hash"]
            or any(execution.get(key) != record.get(field) for key, field in (
                ("execution_request", "request"), ("execution_handle", "handle"), ("execution_result", "result")))
            or frozen.get("execution_request_hash") != original.contract_hash
            or frozen.get("contract_hash") != canonical_hash({k:v for k,v in frozen.items() if k != "contract_hash"})
            or frozen.get("output_schema_version") != capability.get("output_schema_ref")
            or schema_hash != capability.get("output_schema_hash")
            or schema_hash != process_evidence.get("provider_schema_contract", {}).get("canonical_hash")
            or capability.get("provider_admission_asset_version_id") != admission.asset_version_id
            or capability.get("fully_rendered_prompt_hash") != "sha256:" + process.get("input_sha256", "")
            or any(process.get(key) != getattr(original, key) or record.get("result", {}).get(key) != getattr(original, key)
                   or record.get("handle", {}).get(key) != getattr(original, key)
                   for key in ("execution_id", "operation_id", "attempt_id", "fencing_token"))):
        raise KernelError("RETAINED_WORKING_EXECUTION_INVALID", "Bind the intact original frozen contract to its durable failed dispatch")
    from novel_forge.modules.command_kernel.generation_isolation import require_stopped_reconciled_cli_process
    require_stopped_reconciled_cli_process(process)
    return {"dispatch_id": dispatch["dispatch_id"], "dispatch_evidence_hash": canonical_hash(evidence),
            "effect_request_hash": effect["request_hash"], "request_contract_hash": original.contract_hash,
            "record_state_hash": recovery["record_state_hash"], "frozen_output_contract_hash": frozen["contract_hash"],
            "output_schema_hash": schema_hash}

def _source(uow, *, book, candidate_id):
    source = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=candidate_id)
    _require_governed(source)
    payload = source.content.get("payload") or {}
    if (source.asset_type != "execution_evidence" or source.content.get("kind") != "prose-candidate"
            or payload.get("contract_version") != "retained-model-result.v1"
            or payload.get("project_id") != book["project_id"] or payload.get("book_id") != book["book_id"]
            or payload.get("stage") != "draft" or payload.get("completeness") != "COMPLETE_SOURCE_PROSE"
            or payload.get("selection_status") != "NOT_SELECTED" or payload.get("acceptance_status") != "NOT_ACCEPTED"
            or canonical_hash(payload)[7:] != source.content.get("payload_hash")
            or text_hash(payload.get("text", "")) != payload.get("text_sha256")
            or text_hash(payload.get("raw_text", "")) != payload.get("raw_sha256")):
        raise KernelError("RETAINED_WORKING_SOURCE_INVALID", "Require the exact intact original unselected Writer return")
    return source, payload


def _guard(uow, *, book, payload):
    q = uow.cursor
    q.execute("SELECT f.formation_run_id FROM authority_story_formation_run f WHERE %s=f.formation_run_id || ':production' FOR SHARE", [book["stable_idempotency_key"]])
    from novel_forge.modules.command_kernel.step_successor import require_live_chapter_frontier
    q.execute("SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s FOR SHARE", [payload["operation_id"]])
    row = q.fetchone()
    op = row[0] if row else {}
    q.execute("SELECT to_jsonb(r) FROM authority_book_chapter_request r WHERE chapter_request_id=%s", [book["active_chapter_request_id"]])
    row = q.fetchone()
    request = row[0] if row else {}
    q.execute("SELECT definition_version,status FROM authority_operation WHERE operation_id=%s FOR UPDATE", [op.get("root_operation_id")])
    root = q.fetchone()
    require_live_chapter_frontier(q, root_id=op.get("root_operation_id"), project_id=book["project_id"], book_run_id=book["book_run_id"])
    q.execute("SELECT attempt_id,status,result->>'error_code' FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number", [op.get("operation_id")])
    attempts = q.fetchall()
    q.execute("SELECT e.external_effect_id,e.status,b.status,e.request_payload FROM authority_external_effect e JOIN authority_budget_reservation b USING(external_effect_id) WHERE e.operation_id=%s", [op.get("operation_id")])
    effects = q.fetchall()
    if (op.get("definition_name") != "chapter.draft.generate" or op.get("definition_version") != "3.10.0"
            or op.get("status") != "FAILED_FINAL" or op.get("project_id") != book["project_id"]
            or op.get("workspace_id") != book["workspace_id"] or op.get("command_payload", {}).get("book_id") != book["book_id"]
            or request.get("chapter_root_operation_id") != op.get("root_operation_id")
            or request.get("chapter_number") != book["current_chapter"] + 1
            or root != ("3.10.0-author-first.v1", "WAITING_CHILDREN")
            or attempts != [(payload["attempt_id"], "FAILED_FINAL", FAILURE)]
            or len(effects) != 1 or effects[0][:3] != (payload["external_effect_id"], "FAILED_FINAL", "SETTLED")):
        raise KernelError("RETAINED_WORKING_SOURCE_INVALID", "Require one stopped, settled original permission failure at the exact working frontier")
    q.execute("SELECT EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt a USING(attempt_id) JOIN authority_operation o USING(operation_id) WHERE o.root_operation_id=%s AND lease.status='HELD'), EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=ANY(%s) AND acknowledged_at IS NULL), EXISTS(SELECT 1 FROM authority_external_effect e JOIN authority_operation o USING(operation_id) WHERE o.root_operation_id=%s AND e.status IN ('DISPATCHING','DISPATCHED','UNKNOWN','RECONCILIATION_REQUIRED')), EXISTS(SELECT 1 FROM authority_operation o JOIN authority_external_effect e USING(operation_id) WHERE o.root_operation_id=%s AND o.definition_name='chapter.draft.generate' AND o.operation_id<>%s)", [op["root_operation_id"], [op["root_operation_id"], op["operation_id"], book["root_operation_id"]], op["root_operation_id"], op["root_operation_id"], op["operation_id"]])
    if any(q.fetchone()):
        raise KernelError("RETAINED_WORKING_FRONTIER_BUSY", "Reconcile leases, cancellation, external uncertainty and alternate Writer returns first")
    q.execute("SELECT content FROM authority_asset_version WHERE asset_version_id=%s", [book["production_profile_version"]])
    profile = q.fetchone()[0]
    if (profile.get("knowledge_access_policy", {}).get("usage_scope") != "EXPERIMENTAL_VALIDATION"):
        raise KernelError("RETAINED_WORKING_EXPERIMENT_REQUIRED", "This explicit working-use contract is limited to experimental Books")
    return op, request, effects[0][3]


def prepare_retained_working(database_url, *, book, candidate_id):
    from novel_forge.modules.chapter_authority.domain_handlers import normalize_draft_result
    from novel_forge.modules.production_execution.codex_configuration import strict_codex_json_loads
    from novel_forge.modules.chapter_authority.realization_composition import serialize_realization
    from novel_forge.modules.chapter_authority.provider_output_contracts import validate_chapter_provider_output_against_schema, validate_chapter_provider_output_semantics
    from novel_forge.modules.chapter_authority.model_effects import normalize_model_output

    with AuthorityUnitOfWork(database_url) as uow:
        source, payload = _source(uow, book=book, candidate_id=candidate_id)
        op, request, effect_request = _guard(uow, book=book, payload=payload)
        if source.asset_version_id not in {row[0] for row in uow.cursor.execute("SELECT asset_version_id FROM authority_operation_output_asset WHERE operation_id=%s", [op["operation_id"]]).fetchall()}:
            raise KernelError("RETAINED_WORKING_SOURCE_INVALID", "The candidate must belong to its original Writer")
        uow.cursor.execute("SELECT v.asset_version_id,v.content_hash,v.content FROM authority_operation_output_asset output JOIN authority_asset a ON a.asset_id=output.asset_id JOIN authority_asset_version v USING(asset_version_id) WHERE output.operation_id=%s AND a.asset_type='execution_recovery_session' ORDER BY v.created_at DESC,v.asset_version_id DESC LIMIT 1", [op["operation_id"]])
        recovery_id, recovery_hash, recovery = uow.cursor.fetchone()
        _require_governed(uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=recovery_id), recovery_hash)
        record = recovery["record"]
        uow.cursor.execute("SELECT to_jsonb(e) FROM authority_external_effect e WHERE external_effect_id=%s", [payload["external_effect_id"]])
        effect = uow.cursor.fetchone()[0]
        uow.cursor.execute("SELECT to_jsonb(d) FROM authority_external_effect_dispatch d WHERE external_effect_id=%s ORDER BY generation", [payload["external_effect_id"]])
        dispatches = uow.cursor.fetchall()
        if len(dispatches) != 1:
            raise KernelError("RETAINED_WORKING_EXECUTION_INVALID", "Require exactly one original failed dispatch")
        dispatch = dispatches[0][0]
        documents = [uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=ref["asset_version_id"])
                     for ref in op["input_asset_snapshot"]]
        for doc, ref in zip(documents, op["input_asset_snapshot"], strict=True):
            _require_governed(doc, ref["content_hash"])
        admission_ref = effect_request["_production_execution"]["capability_runtime"]
        admission = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=admission_ref["provider_admission_asset_version_id"])
        material = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=admission_ref["materialization_asset_version_id"])
        _require_governed(material, admission_ref["materialization_content_hash"])
        _require_governed(admission, admission_ref["provider_admission_content_hash"])
        identity_proof = require_original_contract(recovery, payload=payload, effect=effect, dispatch=dispatch, admission=admission)
        selected = material.content["contract"]["context_selection"]
        plans = [doc for doc in documents if doc.asset_type == "chapter_plan"]
        contexts = [doc for doc in documents if len(selected) == 1 and doc.asset_version_id == selected[0]["asset_version_id"]]
        if len(plans) != 1 or len(contexts) != 1 or contexts[0].content_hash != selected[0]["content_hash"]:
            raise KernelError("RETAINED_WORKING_INPUT_CHANGED", "Require the actual original plan and Provider-selected Context")
    process = payload["source"]["process_receipt"]
    prompt_hash = admission.content["contract"]["prompt_materialization"]["provider_view"]["component_hashes"]["fully_rendered_prompt"]
    if (process.get("status") != "SUCCEEDED" or process.get("result_integrity") != "VALID" or process.get("returncode") != 0
            or process != record.get("process_receipt") or record.get("result", {}).get("outcome") != "FINAL_FAILURE"
            or record.get("raw_evidence", {}).get("failure_code") != "UNAUTHORIZED_TOOL_INVOCATION"
            or "sha256:" + process["input_sha256"] != prompt_hash
            or admission.content_hash != admission_ref["provider_admission_content_hash"]
            or any(record["request"].get(key) != payload.get(key) or process.get(key) != payload.get(key)
                   for key in ("operation_id", "attempt_id", "fencing_token", "external_effect_id") if key != "external_effect_id")
            or record["request"].get("external_effect_id") != payload["external_effect_id"]):
        raise KernelError("RETAINED_WORKING_EXECUTION_INVALID", "Require the original frozen request, final process and rejected permission evidence")
    directory = Path(process["execution_directory"]).resolve(strict=True)
    for key, name in (("stdout_path", "stdout.log"), ("result_path", "last-message.json"), ("receipt_path", "process-receipt.json")):
        if Path(process[key]).resolve(strict=True) != directory / name:
            raise KernelError("RETAINED_WORKING_EXECUTION_INVALID", "Require the original process directory")
    receipt = strict_codex_json_loads((directory / "process-receipt.json").read_text())
    metadata = strict_codex_json_loads((directory / "execution-metadata.json").read_text())
    if receipt != process or any(metadata.get(k) != process.get(k) for k in ("execution_id", "request_digest")):
        raise KernelError("RETAINED_WORKING_EXECUTION_INVALID", "Require the exact original process receipt and directory identity")
    stdout = Path(process["stdout_path"]).read_text(encoding="utf-8")
    trace = require_empty_discovery_trace(stdout)
    stream = record["raw_evidence"].get("stream_diagnostics") or {}
    if stream.get("stdout_sha256", "").removeprefix("sha256:") != trace["stdout_sha256"][7:]:
        raise KernelError("RETAINED_WORKING_TRACE_CHANGED", "Complete Tool trace must match the persisted native stream hash")
    raw = payload["raw_text"]
    if Path(process["result_path"]).read_text(encoding="utf-8") != raw:
        raise KernelError("RETAINED_WORKING_RESULT_CHANGED", "The retained source must equal the original process output")
    parsed = strict_codex_json_loads(raw)
    from novel_forge.modules.production_execution.codex_configuration import decode_codex_output
    frozen = record["frozen_output_contract"]
    parsed, _ = decode_codex_output(parsed, schema_ref=frozen.get("output_schema_version", ""))
    validated = validate_chapter_provider_output_against_schema("draft", frozen["output_schema"], parsed)
    validated = validate_chapter_provider_output_semantics("draft", validated, output_schema_ref=frozen.get("output_schema_version", ""))
    validated = normalize_model_output("draft", validated, output_schema_ref=frozen.get("output_schema_version", ""))
    plan, context = plans[0], contexts[0]
    normalized = normalize_draft_result(plan=plan.content, context_asset_version_id=context.asset_version_id,
        context_content_hash=context.content_hash, context_content=context.content, result=validated,
        provider_evidence={"kind": "RETAINED_PERMISSION_FAILED_SOURCE", "source_operation_id": op["operation_id"],
                           "source_effect_id": payload["external_effect_id"], "permission_gate": "FAILED_FINAL"},
        work_requirements=True, core_policy="continuous-scene.v1", information_policy="actor-source-scope.v1",
        realization_contract=effect_request["input"]["realization_contract"], enforce_voice_contract=False)
    if normalized["text"] != payload["text"] or serialize_realization(parsed["scene_artifacts"], parsed.get("scene_separators")) != payload["text"]:
        raise KernelError("RETAINED_WORKING_TEXT_CHANGED", "Working use cannot rewrite, replace or reselect the first return")
    proof = {"contract_version": CONTRACT, "source_candidate_asset_version_id": source.asset_version_id,
        "source_candidate_content_hash": source.content_hash, "source_operation_id": op["operation_id"],
        "source_attempt_id": payload["attempt_id"], "source_external_effect_id": payload["external_effect_id"],
        "source_permission_gate": "FAILED_FINAL", "source_failure_code": FAILURE, "budget_status": "SETTLED",
        "recovery_asset_version_id": recovery_id, "recovery_content_hash": recovery_hash, "discovery_trace": trace,
        "actual_input_sha256": process["input_sha256"], "raw_sha256": payload["raw_sha256"], "text_sha256": payload["text_sha256"],
        "execution_identity": identity_proof,
        "provider_calls": 0, "author_acceptance": "NOT_GRANTED", "formal_acceptance": "NOT_GRANTED", "qualification": "WORKING_USE_ONLY"}
    return {"normalized": normalized, "proof": proof, "request": request,
            "input_refs": [{"asset_version_id": source.asset_version_id, "content_hash": source.content_hash},
                           {"asset_version_id": recovery_id, "content_hash": recovery_hash},
                           {"asset_version_id": material.asset_version_id, "content_hash": material.content_hash},
                           {"asset_version_id": admission.asset_version_id, "content_hash": admission.content_hash}, *op["input_asset_snapshot"]]}


def continue_retained_working(authority, book_run_id, *, candidate_id, expected_version, idempotency_key, reason, principal):
    from .manuscript import AUTHOR_WORKFLOW, effective_workflow, verify_working_context, validate_complete_prose
    from psycopg.types.json import Jsonb

    book = authority.require(book_run_id)
    principal.require("book.authority.execute", book["project_id"])
    principal.require("chapter.authority.execute", book["project_id"])
    if not reason.strip() or not idempotency_key.strip() or type(expected_version) is not int:
        raise KernelError("RETAINED_WORKING_COMMAND_INVALID", "Require an explicit reason, stable key and exact Book checkpoint")
    command = {"candidate_id": candidate_id, "expected_version": expected_version, "idempotency_key": idempotency_key, "reason": reason}
    with AuthorityUnitOfWork(authority.database_url) as uow:
        row = uow.cursor.execute("SELECT c.chapter_number,c.working_asset_version_id,c.working_content_hash,c.proof,o.actor_id,o.status FROM authority_book_retained_working_continuation c JOIN authority_operation o ON o.operation_id=c.created_by_operation_id WHERE c.book_run_id=%s AND c.source_candidate_asset_version_id=%s", [book_run_id, candidate_id]).fetchone()
    if row:
        if row[3].get("command") != command or row[4:] != (principal.principal_id, "SUCCEEDED"):
            raise KernelError("RETAINED_WORKING_IDEMPOTENCY_CONFLICT", "The saved working-use decision has a different command or owner")
        return {"book_run_id": book_run_id, "chapter": row[0], "source_asset_version_id": row[1], "source_content_hash": row[2],
                "source_candidate_asset_version_id": candidate_id, "source_permission_gate": "FAILED_FINAL",
                "manuscript_status": "RETAINED_WORKING_ONLY", "acceptance": "NOT_GRANTED", "provider_calls": 0, "replayed": True}
    prepared = prepare_retained_working(authority.database_url, book=book, candidate_id=candidate_id)
    proof = {**prepared["proof"], "command": command}
    def commit(uow, operation_id, checkpoint):
        uow.cursor.execute("SELECT book_id FROM authority_book WHERE book_id=%s FOR UPDATE", [book["book_id"]])
        uow.cursor.execute("SELECT to_jsonb(b) FROM authority_book_production b WHERE book_run_id=%s FOR UPDATE", [book_run_id])
        current = uow.cursor.fetchone()[0]
        if (current["version"] != expected_version or current["state"] not in {"CHAPTER_RUNNING", "CHAPTER_SUBMITTED", "CHAPTER_WAITING_RETRY"}
                or effective_workflow(uow.cursor, current) != AUTHOR_WORKFLOW
                or current["active_chapter_request_id"] != prepared["request"]["chapter_request_id"]):
            raise KernelError("RETAINED_WORKING_CHECKPOINT_CHANGED", "Reload the original active working frontier")
        uow.cursor.execute("SELECT asset_version_id FROM authority_asset_version WHERE asset_version_id=ANY(%s) ORDER BY asset_version_id FOR SHARE", [sorted({ref["asset_version_id"] for ref in prepared["input_refs"]})])
        source, payload = _source(uow, book=current, candidate_id=candidate_id)
        op, request, _ = _guard(uow, book=current, payload=payload)
        if op["actor_id"] != principal.principal_id or source.content_hash != proof["source_candidate_content_hash"]:
            raise KernelError("RETAINED_WORKING_SOURCE_INVALID", "The authenticated original owner and exact source must remain unchanged")
        for ref in prepared["input_refs"]:
            _require_governed(uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=ref["asset_version_id"]), ref["content_hash"])
        uow.cursor.execute("SELECT to_jsonb(d) FROM authority_external_effect_dispatch d WHERE dispatch_id=%s FOR SHARE", [proof["execution_identity"]["dispatch_id"]])
        dispatch = uow.cursor.fetchone()[0]
        if dispatch["status"] != "FAILED_FINAL" or canonical_hash(dispatch["evidence"]) != proof["execution_identity"]["dispatch_evidence_hash"]:
            raise KernelError("RETAINED_WORKING_EXECUTION_INVALID", "The exact failed dispatch must remain unchanged")
        context = request["command_payload"]["preparation_report"]["working_manuscript"]
        verify_working_context(uow, current, context)
        content = {**prepared["normalized"], "type": "RetainedWorkingProse", "project_id": book["project_id"], "book_id": book["book_id"],
                   "contract_version": CONTRACT, "retained_working_provenance": proof,
                   "author_workflow": AUTHOR_WORKFLOW, "strict_certification_eligible": False}
        validate_complete_prose(content)
        asset = uow.repositories.asset_documents.materialize_output(AuthorityAssetWriteCommand(
            operation_id=operation_id, project_id=book["project_id"], asset_id="retained-working:" + operation_id,
            asset_type="retained_working_prose", schema_version=CONTRACT, logical_ref="book-retained-working/" + book_run_id + "/" + str(request["chapter_number"]),
            category="working-manuscript", output_key="book.retained_working_prose", role="primary", content=content,
            qualification_policy="unaccepted-retained-working-source.v1", trace_id=operation_id, correlation_id=book["root_operation_id"]))
        uow.cursor.execute("INSERT INTO authority_book_retained_working_continuation(book_run_id,chapter_request_id,chapter_number,source_candidate_asset_version_id,source_candidate_content_hash,working_asset_version_id,working_content_hash,context_snapshot,proof,created_by_operation_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", [book_run_id, request["chapter_request_id"], request["chapter_number"], source.asset_version_id, source.content_hash, asset.asset_version_id, asset.content_hash, Jsonb(context), Jsonb(proof), operation_id])
        uow.cursor.execute("UPDATE authority_child_delegation SET superseded_at=NOW(),version=version+1,updated_at=NOW() WHERE delegation_id=%s AND superseded_at IS NULL", [current["active_child_delegation_id"]])
        if uow.cursor.rowcount != 1:
            raise KernelError("RETAINED_WORKING_CHECKPOINT_CHANGED", "The original child reference changed concurrently")
        uow.cursor.execute("UPDATE authority_book_production SET current_chapter=%s,state='READY',active_chapter_request_id=NULL,active_child_delegation_id=NULL,active_chapter_number=NULL,active_plan_version_id=NULL,version=version+1,updated_at=NOW() WHERE book_run_id=%s", [request["chapter_number"], book_run_id])
        checkpoint("after_retained_working_continuation")
        return {"book_run_id": book_run_id, "chapter": request["chapter_number"], "source_asset_version_id": asset.asset_version_id,
                "source_content_hash": asset.content_hash, "source_candidate_asset_version_id": candidate_id,
                "source_permission_gate": "FAILED_FINAL", "manuscript_status": "RETAINED_WORKING_ONLY", "acceptance": "NOT_GRANTED", "provider_calls": 0}
    return authority._execute_mutation(book=book, action="retained_working_continue", event_type="book.retained_working.continued",
        idempotency_key=idempotency_key, actor_id=principal.principal_id, trace_id=idempotency_key, correlation_id=book["root_operation_id"],
        causation_id=proof["source_operation_id"], payload={"candidate_id": candidate_id, "expected_version": expected_version, "reason": reason, "contract_version": CONTRACT},
        handler=commit, input_assets=tuple(prepared["input_refs"]))
