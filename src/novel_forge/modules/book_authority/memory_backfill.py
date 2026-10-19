from dataclasses import asdict, dataclass
from typing import Any

from novel_forge.modules.authority_handler_runtime import AuthorityHandlerOutput
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.working_memory import OBSERVATIONS_V2, normalize_observations, validate_observations, validate_promise_transitions
from novel_forge.modules.story_planning_runtime.domain import canonical_hash
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

STAGE = "working_memory_extract"
TASK_TYPE = "working_memory_task"
RESULT_TYPE = "working_memory_result"
OUTPUT_KEY = "book.working_memory.result"


def _book(uow, project_id, book_run_id, *, lock=False):
    uow.cursor.execute("SELECT book_id FROM authority_book_production WHERE project_id=%s AND book_run_id=%s", [project_id, book_run_id])
    row = uow.cursor.fetchone()
    if row is None:
        raise KernelError("BOOK_PRODUCTION_NOT_FOUND", "No Book belongs to this Project")
    if lock:
        uow.cursor.execute("SELECT book_id FROM authority_book WHERE book_id=%s FOR UPDATE", [row[0]])
    uow.cursor.execute("SELECT to_jsonb(b) FROM authority_book_production b WHERE project_id=%s AND book_run_id=%s" + (" FOR UPDATE" if lock else ""), [project_id, book_run_id])
    return uow.cursor.fetchone()[0]


def _sources(uow, book, chapter):
    from .manuscript import _optional_document, resolve_working_source, working_dependency_changes
    from .manuscript_memory import freeze_source_memory, memory_ref
    from novel_forge.modules.chapter_authority.author_editor import source_draft_content
    _, changes = working_dependency_changes(uow, book)
    rows, entries, known = [], [], set()
    for number in range(1, chapter + 1):
        source, resolution = resolve_working_source(uow, book, number)
        text = source_draft_content(source)["text"]
        memory, provenance, reference = freeze_source_memory(uow, book, source)
        head = _optional_document(uow, book["project_id"], memory_ref(book, source.asset_version_id))
        status = "MISSING"
        if memory is not None and not changes.get(number):
            try:
                validate_observations(memory, text, available_causes=known)
                status = "LOCATED_UNREVIEWED" if memory["entries"] else "LOCATED_EMPTY" if provenance.get("kind") == "NATIVE_PROVIDER_OBSERVATION" else "EMPTY"
                if number < chapter:
                    entries.extend({**entry, "source": {"chapter": number, "asset_version_id": source.asset_version_id,
                        "content_hash": source.content_hash}} for entry in memory["entries"])
                    known.update(item["observation_id"] for item in memory["entries"])
            except (KernelError, KeyError, TypeError, ValueError) as error:
                status = getattr(error, "code", "WORKING_MEMORY_INVALID")
        if changes.get(number):
            status = "WORKING_MEMORY_DEPENDENCY_CHANGED"
        rows.append({"chapter": number, "asset_version_id": source.asset_version_id,
            "content_hash": source.content_hash, "source_resolution": resolution,
            "memory_source": reference, "sidecar_head": {"asset_version_id": head.asset_version_id, "content_hash": head.content_hash} if head else None,
            "coverage": status, "provenance": provenance})
    return rows, entries, text


def require_task_current(uow, task, *, lock=False):
    book = _book(uow, task["project_id"], task["book_run_id"], lock=lock)
    rows, entries, text = _sources(uow, book, task["chapter"])
    changed = len(rows) != len(task["sources"]) or any(
        any(current[key] != frozen[key] for key in ("chapter", "asset_version_id", "content_hash", "source_resolution"))
        or current["coverage"] == "WORKING_MEMORY_DEPENDENCY_CHANGED"
        for current, frozen in zip(rows, task["sources"]))
    if (changed or rows[-1]["memory_source"] != task["sources"][-1]["memory_source"]
            or rows[-1]["sidecar_head"] != task["sources"][-1]["sidecar_head"] or text != task["text"]):
        raise KernelError("WORKING_MEMORY_SOURCE_STALE", "Selected prose, lineage or memory changed after extraction was frozen")
    return book


def memory_coverage(database_url, *, project_id, book_run_id, principal):
    principal.require("book.authority.query", project_id)
    with AuthorityUnitOfWork(database_url) as uow:
        book = _book(uow, project_id, book_run_id)
        rows = _sources(uow, book, book["current_chapter"])[0] if book["current_chapter"] else []
        uow.cursor.execute("""SELECT operation_id,status,command_payload->'payload',version
            FROM authority_operation WHERE project_id=%s AND definition_name=%s
              AND command_payload#>>'{payload,book_run_id}'=%s ORDER BY created_at""", [project_id, STAGE, book_run_id])
        operations = [dict(zip(("operation_id", "status", "payload", "version"), row, strict=True)) for row in uow.cursor.fetchall()]
        uow.cursor.execute("""SELECT operation_id,command_payload->'payload',metadata->'transaction_result'
            FROM authority_operation WHERE project_id=%s AND status='SUCCEEDED'
              AND command_payload#>>'{payload,book_run_id}'=%s
              AND command_payload#>>'{payload,action}' IN ('working_memory_batch_prepare','working_memory_batch_member','working_memory_batch_stop','working_memory_batch_complete')
            ORDER BY created_at,operation_id""", [project_id, book_run_id])
        batches = [dict(zip(("operation_id", "command", "result"), row, strict=True)) for row in uow.cursor.fetchall()]
    return {"version": "working-memory-coverage.v1", "book_run_id": book_run_id,
        "book_version": book["version"], "sources": rows, "operations": operations, "batch_evidence": batches,
        "formal_acceptance": "NOT_GRANTED", "semantic_support": "NOT_VERIFIED"}


def prepare_backfill(authority, *, book_run_id, chapter, expected_version, idempotency_key, principal, retry_operation_id="", retry_reason=""):
    from .manuscript_memory import memory_ref
    book = authority.require(book_run_id)
    principal.require("book.authority.execute", book["project_id"])

    def commit(uow, operation_id, checkpoint):
        current = _book(uow, book["project_id"], book_run_id, lock=True)
        if current["version"] != expected_version or type(chapter) is not int or not 1 <= chapter <= current["current_chapter"]:
            raise KernelError("WORKING_MEMORY_CHECKPOINT_STALE", "Reload the current Book and selected manuscript")
        rows, entries, text = _sources(uow, current, chapter)
        source = rows[-1]
        if source["coverage"] == "WORKING_MEMORY_DEPENDENCY_CHANGED":
            raise KernelError("WORKING_MEMORY_SOURCE_STALE", "Reconcile selected predecessor changes before extraction")
        from .memory_prior import select_extraction_prior
        prior, prior_selection = select_extraction_prior(entries, text)
        task = {"version": "working-memory-extraction-task.v1",
            **{key: current[key] for key in ("project_id", "workspace_id", "book_id", "book_run_id")},
            "chapter": chapter, "sources": rows, "prior_observations": prior, "prior_selection": prior_selection, "text": text,
            "observations_version": OBSERVATIONS_V2, "source_isolation": "SELECTED_OWN_WORKING_PROSE_ONLY",
            "sidecar_logical_ref": memory_ref(current, source["asset_version_id"]),
            "formal_acceptance": "NOT_GRANTED"}
        if retry_operation_id:
            uow.cursor.execute("""SELECT status,command_payload FROM authority_operation WHERE operation_id=%s AND project_id=%s
                AND definition_name=%s AND command_payload#>>'{payload,book_run_id}'=%s""", [retry_operation_id, book["project_id"], STAGE, book_run_id])
            failed = uow.cursor.fetchone()
            uow.cursor.execute("SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s AND status NOT IN ('SUCCEEDED','FAILED_FINAL','FAILED_RETRYABLE','CANCELLED'))", [retry_operation_id])
            uncertain = uow.cursor.fetchone()[0]
            uow.cursor.execute("SELECT EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt attempt USING(attempt_id) WHERE attempt.operation_id=%s AND lease.status='HELD' AND lease.expires_at>NOW())", [retry_operation_id])
            held = uow.cursor.fetchone()[0]
            if (not failed or failed[0] not in {"FAILED_FINAL", "DEAD_LETTER"} or uncertain or held
                    or failed[1]["payload"].get("chapter") != chapter or not retry_reason.strip()):
                raise KernelError("WORKING_MEMORY_RETRY_RECONCILIATION_REQUIRED", "Retry requires a diagnosed terminal failure, no uncertain Effect or active writer, and the same Book chapter")
            task["retry_source"] = {"operation_id": retry_operation_id, "task_hash": failed[1]["payload"]["task_hash"], "reason": retry_reason}
        task["task_hash"] = canonical_hash(task)
        from .manuscript import _optional_document
        logical_ref = "memory-task/" + task["task_hash"][7:]
        document = _optional_document(uow, current["project_id"], logical_ref)
        if document is not None and document.content != task:
            raise KernelError("WORKING_MEMORY_TASK_INVALID", "Content-addressed task identity conflict")
        document = document or uow.repositories.asset_documents.materialize_output(AuthorityAssetWriteCommand(
            operation_id=operation_id, project_id=current["project_id"], asset_id="memory-task:" + operation_id,
            asset_type=TASK_TYPE, schema_version=task["version"], logical_ref=logical_ref,
            category="working-manuscript", output_key="book.working_memory.task", role="completion_evidence",
            content=task, qualification_policy="source-bound-working-observation.v1", trace_id=operation_id,
            correlation_id=current["root_operation_id"]))
        checkpoint("after_memory_task_freeze")
        return {"task_asset_version_id": document.asset_version_id, "content_hash": document.content_hash,
            "task_hash": task["task_hash"], "chapter": chapter, "source_asset_version_id": source["asset_version_id"]}

    return authority._execute_mutation(book=book, action="working_memory_prepare", event_type="book.working_memory.prepared",
        idempotency_key=idempotency_key, actor_id=principal.principal_id, trace_id=idempotency_key,
        correlation_id=book["root_operation_id"], causation_id=book["root_operation_id"],
        payload={"chapter": chapter, "expected_version": expected_version, "retry_operation_id": retry_operation_id, "retry_reason": retry_reason}, handler=commit)


def admit_backfill(authority, followup, *, book_run_id, expected_version, idempotency_key, principal, chapters=None, retry_operation_id="", retry_reason=""):
    book = authority.require(book_run_id)
    principal.require("book.authority.execute", book["project_id"])
    if not idempotency_key or type(expected_version) is not int or (chapters is not None and (
            not isinstance(chapters, list) or not chapters or any(type(number) is not int for number in chapters)
            or len(chapters) != len(set(chapters)))):
        raise KernelError("WORKING_MEMORY_RANGE_INVALID", "Require a checkpoint, stable key and distinct integer chapters")

    if retry_operation_id and (not retry_reason.strip() or chapters is None or len(chapters) != 1):
        raise KernelError("WORKING_MEMORY_RETRY_RECONCILIATION_REQUIRED", "A diagnosed retry binds one explicit chapter and its original operation")

    def freeze_batch(uow, operation_id, checkpoint):
        current = _book(uow, book["project_id"], book_run_id, lock=True)
        if current["version"] != expected_version:
            raise KernelError("WORKING_MEMORY_CHECKPOINT_STALE", "Reload memory coverage before admission")
        rows = _sources(uow, current, current["current_chapter"])[0] if current["current_chapter"] else []
        requested = set(chapters) if chapters is not None else {row["chapter"] for row in rows if row["coverage"] not in {"LOCATED_UNREVIEWED", "LOCATED_EMPTY"}}
        if not requested.issubset({row["chapter"] for row in rows}):
            raise KernelError("WORKING_MEMORY_RANGE_INVALID", "Extract only existing selected chapters")
        return {"chapters": sorted(requested), "through_chapter": current["current_chapter"],
            "source_scope": [{key: source[key] for key in ("chapter", "asset_version_id", "content_hash", "source_resolution")} for source in rows]}

    with AuthorityUnitOfWork(authority.database_url, coordinate_nested=True) as transaction:
        batch = authority._execute_mutation(book=book, action="working_memory_batch_prepare",
            event_type="book.working_memory.batch_prepared", idempotency_key=idempotency_key + ":batch",
            actor_id=principal.principal_id, trace_id=idempotency_key, correlation_id=book_run_id,
            causation_id=book["root_operation_id"], payload={"chapters": chapters, "expected_version": expected_version, "retry_operation_id": retry_operation_id, "retry_reason": retry_reason}, handler=freeze_batch)
        first = advance_backfill(authority, followup, batch_operation_id=batch["operation_id"], principal=principal)
        transaction.commit()
    return {"status": "ADMITTED", "provider_calls_in_request": 0, "batch_operation_id": batch["operation_id"],
        "chapters": batch["chapters"], "operations": first,
        "resume": "Existing Book followup worker and Kernel run/reconcile/cancel operations", "formal_acceptance": "NOT_GRANTED"}


def advance_backfill(authority, followup, *, batch_operation_id, principal):
    from novel_forge.modules.book_followup_authority.application import BookFollowupCommand
    with AuthorityUnitOfWork(authority.database_url, coordinate_nested=True) as transaction:
        uow = transaction
        uow.cursor.execute("SELECT project_id,command_payload FROM authority_operation WHERE operation_id=%s AND status='SUCCEEDED'", [batch_operation_id])
        row = uow.cursor.fetchone()
        if not row or row[1].get("payload", {}).get("action") != "working_memory_batch_prepare":
            raise KernelError("WORKING_MEMORY_BATCH_INVALID", "Resume an original Book-owned extraction batch")
        project_id, payload = row[0], row[1]["payload"]
        principal.require("book.authority.execute", project_id)
        uow.cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", [batch_operation_id])
        batch = uow.repositories.operations.transaction_result(batch_operation_id, project_id)["result"]
        book = _book(uow, project_id, payload["book_run_id"], lock=True)
        rows = _sources(uow, book, batch["through_chapter"])[0] if batch["through_chapter"] else []
        def identity(source):
            return {key: source[key] for key in ("chapter", "asset_version_id", "content_hash", "source_resolution")}
        if [identity(source) for source in rows] != batch["source_scope"]:
            raise KernelError("WORKING_MEMORY_SOURCE_STALE", "The batch cannot follow changed selected manuscripts")
        uow.cursor.execute("""SELECT (member.command_payload#>>'{payload,chapter}')::int,child.operation_id,child.status
            FROM authority_operation member JOIN authority_operation child
              ON child.operation_id=member.command_payload#>>'{payload,extraction_operation_id}' AND child.project_id=member.project_id
            WHERE member.project_id=%s AND member.status='SUCCEEDED'
              AND member.command_payload#>>'{payload,action}'='working_memory_batch_member'
              AND member.command_payload#>>'{payload,batch_operation_id}'=%s""", [project_id, batch_operation_id])
        existing = {item[0]: item[1:] for item in uow.cursor.fetchall()}
        for chapter in batch["chapters"]:
            if chapter in existing:
                operation_id, status = existing[chapter]
                if status == "SUCCEEDED":
                    continue
                if status in {"FAILED_FINAL", "DEAD_LETTER", "CANCELLED"}:
                    _stop_batch(authority, book, batch_operation_id, principal, status)
                transaction.commit()
                return [{"operation_id": operation_id, "project_id": project_id, "replayed": True}]
            prepared = prepare_backfill(authority, book_run_id=book["book_run_id"], chapter=chapter,
                expected_version=book["version"], idempotency_key=batch_operation_id + ":prepare:" + str(chapter), principal=principal,
                retry_operation_id=payload.get("retry_operation_id", ""), retry_reason=payload.get("retry_reason", ""))
            command = BookFollowupCommand(definition_name=STAGE, project_id=project_id,
                workspace_id=book["workspace_id"], actor_id=principal.principal_id, trace_id=prepared["task_hash"],
                correlation_id=book["book_run_id"], idempotency_key="working-memory-extract:" + prepared["task_hash"],
                payload={"book_id": book["book_id"], "book_run_id": book["book_run_id"], "chapter": chapter,
                    "task_hash": prepared["task_hash"], "context_token_budget": 512000},
                input_assets=({"asset_version_id": prepared["task_asset_version_id"], "content_hash": prepared["content_hash"]},),
                causation_operation_id=payload.get("retry_operation_id") or None)
            uow.cursor.execute("""SELECT operation_id,command_payload->'payload',input_asset_snapshot FROM authority_operation
                WHERE project_id=%s AND idempotency_scope='project:book-followup' AND idempotency_key=%s AND definition_name=%s""",
                [project_id, command.idempotency_key, STAGE])
            retained = uow.cursor.fetchone()
            if retained:
                from novel_forge.modules.book_followup_authority.application import BookFollowupAdmission
                if retained[1] != {**command.payload, "reader_proxy_policy_snapshot": {}} or retained[2] != [{"project_id": project_id, **item} for item in command.input_assets]:
                    raise KernelError("WORKING_MEMORY_TASK_INVALID", "Existing extraction must retain identical Book, task and inputs")
                admitted = BookFollowupAdmission(retained[0], project_id, True)
            else:
                admitted = followup.admit(command, principal=principal)
            authority._execute_mutation(book=book, action="working_memory_batch_member", event_type="book.working_memory.member_admitted",
                idempotency_key=batch_operation_id + ":member:" + str(chapter), actor_id=principal.principal_id,
                trace_id=batch_operation_id, correlation_id=book["book_run_id"], causation_id=batch_operation_id,
                payload={"batch_operation_id": batch_operation_id, "chapter": chapter, "extraction_operation_id": admitted.operation_id},
                handler=lambda owner_uow, operation_id, checkpoint: {"extraction_operation_id": admitted.operation_id})
            transaction.commit()
            return [asdict(admitted)]
        authority._execute_mutation(book=book, action="working_memory_batch_complete", event_type="book.working_memory.batch_complete",
            idempotency_key=batch_operation_id + ":complete", actor_id=principal.principal_id,
            trace_id=batch_operation_id, correlation_id=book["book_run_id"], causation_id=batch_operation_id,
            payload={"batch_operation_id": batch_operation_id}, handler=lambda owner_uow, operation_id, checkpoint: {"status": "COMPLETED"})
        transaction.commit()
        return []


def _stop_batch(authority, book, batch_operation_id, principal, status):
    return authority._execute_mutation(book=book, action="working_memory_batch_stop", event_type="book.working_memory.batch_stopped",
        idempotency_key=batch_operation_id + ":stop:" + status, actor_id=principal.principal_id,
        trace_id=batch_operation_id, correlation_id=book["book_run_id"], causation_id=batch_operation_id,
        payload={"batch_operation_id": batch_operation_id, "status": status},
        handler=lambda uow, operation_id, checkpoint: {"status": status})


def advance_pending_backfills(authority, followup, *, principal, limit=50):
    with AuthorityUnitOfWork(authority.database_url) as uow:
        projects = [] if "*" in principal.project_scope else sorted(principal.project_scope)
        uow.cursor.execute("""SELECT batch.operation_id FROM authority_operation batch WHERE batch.status='SUCCEEDED'
            AND batch.command_payload#>>'{payload,action}'='working_memory_batch_prepare'
            AND (%s::text[]='{}'::text[] OR batch.project_id=ANY(%s))
            AND NOT EXISTS(SELECT 1 FROM authority_operation terminal WHERE terminal.project_id=batch.project_id
                AND terminal.command_payload#>>'{payload,batch_operation_id}'=batch.operation_id
                AND terminal.command_payload#>>'{payload,action}' IN ('working_memory_batch_complete','working_memory_batch_stop'))
            ORDER BY batch.created_at LIMIT %s""", [projects, projects, limit])
        batches = [row[0] for row in uow.cursor.fetchall()]
    result = []
    for batch in batches:
        try:
            result.extend(advance_backfill(authority, followup, batch_operation_id=batch, principal=principal))
        except KernelError as error:
            if error.code != "WORKING_MEMORY_SOURCE_STALE":
                raise
            with AuthorityUnitOfWork(authority.database_url) as uow:
                uow.cursor.execute("SELECT command_payload#>>'{payload,book_run_id}' FROM authority_operation WHERE operation_id=%s", [batch])
                run = uow.cursor.fetchone()[0]
            _stop_batch(authority, authority.require(run), batch, principal, error.code)
    return result


@dataclass(frozen=True, slots=True)
class MemoryExtractionHandler:
    model_port: Any

    def execute(self, request):
        if not self.model_port or not getattr(self.model_port, "external_effect_backed", False):
            raise KernelError("WORKING_MEMORY_PROVIDER_REQUIRED", "Configure the native memory extraction route")
        source = request.require_input(TASK_TYPE)
        task = source.content
        if (task.get("task_hash") != request.command["payload"].get("task_hash")
                or task.get("task_hash") != canonical_hash({key: value for key, value in task.items() if key != "task_hash"})):
            raise KernelError("WORKING_MEMORY_TASK_INVALID", "Extraction retains its exact frozen task")

        def current():
            with AuthorityUnitOfWork(self.model_port.database_url) as uow:
                require_task_current(uow, task)

        current()
        result = self.model_port.invoke(request, stage=STAGE, payload={"task_hash": task["task_hash"]},
            reservation_tokens=request.command["payload"]["context_token_budget"], pre_send_assertion=current)
        observations = normalize_observations(result.output["observations"], task["text"], version=OBSERVATIONS_V2,
            available_causes={row["observation_id"] for row in task["prior_observations"]})
        validate_promise_transitions(observations["entries"], task["prior_observations"])
        current()
        return AuthorityHandlerOutput(asset_type=RESULT_TYPE, output_key=OUTPUT_KEY, role="primary",
            content={"version": "working-memory-extraction-result.v1", "task_asset_version_id": source.asset_version_id,
                "task_hash": task["task_hash"], "observations": observations, "formal_acceptance": "NOT_GRANTED"},
            qualification_policy="located-unreviewed-memory.v2", reference_asset_version_ids=(source.asset_version_id,),
            evidence={"model_evidence": result.to_evidence(), "semantic_support": "NOT_VERIFIED"})


def commit_backfill_sidecar(uow, request, output):
    from .manuscript import _optional_document
    task = request.require_input(TASK_TYPE).content
    book = require_task_current(uow, task, lock=True)
    source = task["sources"][-1]
    prior = _optional_document(uow, book["project_id"], task["sidecar_logical_ref"])
    content = {"version": "manuscript-memory-sidecar.v2", "book_run_id": book["book_run_id"],
        "project_id": book["project_id"], "book_id": book["book_id"], "chapter": task["chapter"],
        "source_asset_version_id": source["asset_version_id"], "source_content_hash": source["content_hash"],
        "observations": output.content["observations"], "source_kind": "NATIVE_PROVIDER_OBSERVATION",
        "actor_id": request.actor_id, "native_operation_id": request.operation_id,
        "native_attempt_id": request.attempt_id, "task_hash": task["task_hash"],
        "formal_acceptance": "NOT_GRANTED"}
    uow.repositories.asset_documents.materialize_output(AuthorityAssetWriteCommand(
        operation_id=request.operation_id, project_id=book["project_id"], asset_id=prior.asset_id if prior else "working-memory:" + request.operation_id,
        asset_type="manuscript_memory", schema_version=content["version"], logical_ref=task["sidecar_logical_ref"],
        category="working-manuscript", output_key="book.manuscript_memory", role="derived", content=content,
        qualification_policy="located-unreviewed-memory.v2", trace_id=request.trace_id, correlation_id=request.correlation_id,
        expected_current_asset_version_id=prior.asset_version_id if prior else None))
    uow.cursor.execute("UPDATE authority_book_production SET version=version+1,updated_at=NOW() WHERE book_run_id=%s", [book["book_run_id"]])


def cancel_backfill(database_url, *, project_id, book_run_id, operation_id, expected_version, idempotency_key, reason, principal):
    from novel_forge.modules.command_kernel.cancellation import CancelCommand, request_cancellation
    principal.require("book.authority.execute", project_id)
    with AuthorityUnitOfWork(database_url) as uow:
        require_backfill_operation(uow, project_id=project_id, book_run_id=book_run_id, operation_id=operation_id)
    return request_cancellation(database_url, CancelCommand(operation_id=operation_id, project_id=project_id,
        actor_id=principal.principal_id, reason=reason, expected_version=expected_version, idempotency_key=idempotency_key,
        trace_id=idempotency_key, correlation_id=book_run_id), settle_undispatched=True)


def require_backfill_operation(uow, *, project_id, book_run_id, operation_id):
    uow.cursor.execute("""SELECT status,version FROM authority_operation WHERE operation_id=%s AND project_id=%s
        AND definition_name=%s AND command_payload#>>'{payload,book_run_id}'=%s""", [operation_id, project_id, STAGE, book_run_id])
    row = uow.cursor.fetchone()
    if not row:
        raise KernelError("WORKING_MEMORY_OPERATION_NOT_FOUND", "No extraction operation belongs to this Book")
    return {"status": row[0], "version": row[1]}
