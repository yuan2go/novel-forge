from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from json import dumps
from typing import Any, Mapping

from novel_forge.modules.chapter_authority.author_editor import _session_ref, source_draft_content, text_hash
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.domain import canonical_hash
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

AUTHOR_WORKFLOW = {"version": "author-workflow.v1", "mode": "AUTHOR_FIRST", "deep_review": False}
AUTHOR_ROOT_VERSION = "3.10.0-author-first.v1"


def author_first(book: dict[str, Any]) -> bool:
    return book.get("author_workflow") == AUTHOR_WORKFLOW


def writing_frontier(book: dict[str, Any]) -> int:
    return int(book["current_chapter"] if author_first(book) else book["accepted_through_chapter"])


def effective_workflow(cursor: Any, book: dict[str, Any]) -> dict[str, Any] | None:
    cursor.execute("""SELECT v.content FROM authority_asset_locator l
        JOIN authority_asset_version v ON v.asset_version_id=l.current_asset_version_id
        JOIN authority_asset a ON a.asset_id=v.asset_id
        WHERE l.project_id=%s AND l.logical_ref=%s AND a.asset_type='book_author_workflow_policy'
          AND v.governance='CLEAR' AND v.eligibility='ELIGIBLE'""", [book["project_id"], "book-author-workflow/" + book["book_run_id"]])
    row = cursor.fetchone()
    if row:
        if row[0].get("book_run_id") != book["book_run_id"] or row[0].get("source_profile_version") != book["production_profile_version"]:
            raise KernelError("AUTHOR_WORKFLOW_POLICY_DRIFT", "Workflow adoption must retain the exact frozen Book profile")
        return row[0]["author_workflow"]
    cursor.execute("SELECT content->'author_workflow' FROM authority_asset_version WHERE asset_version_id=%s", [book["production_profile_version"]])
    profile = cursor.fetchone()
    return profile[0] if profile else None


def blocking_working_cli_outcomes(cursor: Any, *, project_id: str, book_id: str,
                                 outcomes: list[dict[str, Any]], operation_id: str = "",
                                 book_run_id: str = "") -> list[dict[str, Any]]:
    if not outcomes or not all(item.get("operation_id") for item in outcomes) or not (operation_id or book_run_id):
        return outcomes
    cursor.execute("""SELECT to_jsonb(b) FROM authority_book_production b
        WHERE b.project_id=%s AND b.book_id=%s AND (%s='' OR b.book_run_id=%s)
          AND (%s='' OR EXISTS(SELECT 1 FROM authority_operation work
            JOIN authority_book_chapter_request request ON request.chapter_root_operation_id=
              COALESCE(NULLIF(work.root_operation_id,''),work.operation_id)
            JOIN authority_operation root ON root.operation_id=request.chapter_root_operation_id
            WHERE work.project_id=b.project_id AND work.workspace_id=b.workspace_id AND work.operation_id=%s
              AND request.book_run_id=b.book_run_id AND root.definition_version=%s)
            OR EXISTS(SELECT 1 FROM authority_story_planning_generation generation
              WHERE generation.project_id=b.project_id AND generation.workspace_id=b.workspace_id
                AND generation.book_id=b.book_id AND generation.operation_id=%s))
        ORDER BY b.created_at DESC,b.book_run_id LIMIT 1""",
        [project_id, book_id, book_run_id, book_run_id, operation_id, operation_id, AUTHOR_ROOT_VERSION, operation_id])
    row = cursor.fetchone()
    if not row and operation_id:
        cursor.execute("""SELECT to_jsonb(b),max((source->>'chapter_number')::integer)
            FROM authority_operation review
            JOIN authority_book_prose_review_event event ON authority_generation_current_operation(event.content->>'operation_id')=review.operation_id
              AND event.kind='WINDOW_ADMITTED'
            JOIN authority_book_prose_review_run run ON run.run_id=event.run_id
            JOIN authority_book_production b ON b.book_run_id=run.book_run_id
            CROSS JOIN LATERAL jsonb_array_elements(run.manifest->'sources') source
            WHERE review.project_id=%s AND review.operation_id=%s AND review.definition_name='longform.prose_review'
              AND review.definition_snapshot#>>'{policy,body_mutation_allowed}'='false'
              AND review.definition_snapshot#>>'{policy,plan_mutation_allowed}'='false'
              AND review.definition_snapshot#>>'{irreversible_effect_policy,allowed}'='false'
              AND NOT EXISTS(SELECT 1 FROM authority_external_effect risk
                WHERE risk.operation_id=review.operation_id AND risk.effect_type<>'model.invoke')
              AND run.project_id=review.project_id AND run.workspace_id=review.workspace_id
              AND b.project_id=run.project_id AND b.workspace_id=run.workspace_id AND b.book_id=%s
              AND run.manifest->>'source_isolation'='AUTHOR_SELECTED_UNREVIEWED_PROSE'
            GROUP BY b.book_run_id""", [project_id, operation_id, book_id])
        review = cursor.fetchone()
        if not review or effective_workflow(cursor, review[0]) != AUTHOR_WORKFLOW:
            return outcomes
        cursor.execute("""SELECT work.operation_id FROM authority_operation work
            JOIN authority_book_chapter_request request ON request.chapter_root_operation_id=
              COALESCE(NULLIF(work.root_operation_id,''),work.operation_id)
            JOIN authority_operation root ON root.operation_id=request.chapter_root_operation_id
            JOIN authority_book_production b ON b.book_run_id=request.book_run_id
            WHERE work.project_id=%s AND b.project_id=work.project_id AND b.workspace_id=work.workspace_id
              AND b.book_id=%s AND root.definition_version=%s AND request.chapter_number>%s
              AND work.operation_id=ANY(%s) AND work.operation_id<>%s""",
            [project_id, book_id, AUTHOR_ROOT_VERSION, review[1], [item["operation_id"] for item in outcomes], operation_id])
        independent = {item[0] for item in cursor.fetchall()}
        return [item for item in outcomes if item["operation_id"] not in independent]
    if not row or not isinstance(row[0], dict) or effective_workflow(cursor, row[0]) != AUTHOR_WORKFLOW:
        return outcomes
    cursor.execute("""SELECT DISTINCT review.operation_id FROM authority_operation review
        JOIN authority_book_prose_review_event event ON authority_generation_current_operation(event.content->>'operation_id')=review.operation_id
          AND event.kind='WINDOW_ADMITTED'
        JOIN authority_book_prose_review_run run ON run.run_id=event.run_id
        JOIN authority_book_production b ON b.book_run_id=run.book_run_id
        WHERE review.project_id=%s AND review.definition_name='longform.prose_review'
          AND review.definition_snapshot#>>'{policy,body_mutation_allowed}'='false'
              AND review.definition_snapshot#>>'{policy,plan_mutation_allowed}'='false'
              AND review.definition_snapshot#>>'{irreversible_effect_policy,allowed}'='false'
              AND NOT EXISTS(SELECT 1 FROM authority_external_effect risk
                WHERE risk.operation_id=review.operation_id AND risk.effect_type<>'model.invoke')
              AND run.project_id=review.project_id AND run.workspace_id=review.workspace_id
          AND b.project_id=run.project_id AND b.workspace_id=run.workspace_id AND b.book_id=%s
          AND run.manifest->>'source_isolation'='AUTHOR_SELECTED_UNREVIEWED_PROSE'
          AND review.operation_id=ANY(%s) AND review.operation_id<>%s""",
        [project_id, book_id, [item["operation_id"] for item in outcomes], operation_id])
    optional = {item[0] for item in cursor.fetchall()}
    return [item for item in outcomes if item["operation_id"] not in optional]


def _require_workflow_checkpoint(uow: Any, book: dict[str, Any], expected_version: int, *, working_selection: bool = False) -> dict[str, Any]:
    uow.cursor.execute("SELECT book_id FROM authority_book WHERE book_id=%s FOR UPDATE", [book["book_id"]])
    uow.cursor.execute("SELECT to_jsonb(b) FROM authority_book_production b WHERE book_run_id=%s FOR UPDATE", [book["book_run_id"]])
    current = uow.cursor.fetchone()[0]
    if current["version"] != expected_version or current["active_chapter_request_id"] or current["state"] not in {"READY", "PAUSED"}:
        raise KernelError("AUTHOR_WORKFLOW_CHECKPOINT_REQUIRED", "Switch only at a settled idle Book checkpoint; active work retains its frozen policy and original effects")
    uow.cursor.execute("""SELECT e.external_effect_id,op.operation_id FROM authority_external_effect e JOIN authority_operation op USING(operation_id)
        WHERE op.project_id=%s AND (e.request_payload #>> '{_production_execution,book_id}'=%s
            OR op.root_operation_id=%s OR op.root_operation_id IN (
                SELECT chapter_root_operation_id FROM authority_book_chapter_request WHERE book_run_id=%s))
          AND NOT authority_generation_isolated(e.external_effect_id)
          AND e.status IN ('READY','DISPATCHING','DISPATCHED','UNKNOWN','FAILED_RETRYABLE','RECONCILIATION_REQUIRED','CANCELLATION_REQUESTED')""",
        [book["project_id"], book["book_id"], book["root_operation_id"], book["book_run_id"]])
    blockers = [dict(external_effect_id=row[0],operation_id=row[1]) for row in uow.cursor.fetchall()]
    if working_selection:
        from novel_forge.modules.story_planning_runtime.preparation_recovery import retired_pre_submit_main
        from novel_forge.modules.story_planning_runtime.fresh_preparation_custody import retired_paused_intent
        blockers = [item for item in blockers if not retired_pre_submit_main(uow,
            project_id=book['project_id'],book_id=book['book_id'],effect_id=item['external_effect_id'])
            and not retired_paused_intent(uow, project_id=book['project_id'],book_id=book['book_id'],
                book_run_id=book['book_run_id'],effect_id=item['external_effect_id'])]
        blockers = blocking_working_cli_outcomes(uow.cursor, project_id=book['project_id'],book_id=book['book_id'],
            book_run_id=book['book_run_id'],outcomes=blockers)
    if blockers:
        raise KernelError("AUTHOR_WORKFLOW_RECONCILIATION_REQUIRED", "Reconcile original unsettled effects before switching generation policy; existing manuscripts remain readable")
    from novel_forge.modules.production_execution.execution_template import BOOK_USAGE_SQL
    uow.cursor.execute("SELECT COALESCE(r.operation_id,e.operation_id) FROM authority_budget_reservation r LEFT JOIN authority_external_effect e USING(external_effect_id) WHERE r.project_id=%s AND r.status='HELD_UNKNOWN' AND NOT authority_generation_isolated(e.external_effect_id) AND " + BOOK_USAGE_SQL,
        [book["project_id"], book["book_id"], book["book_id"], book["book_id"]])
    budgets = [dict(operation_id=row[0]) for row in uow.cursor.fetchall()]
    if working_selection:
        budgets = blocking_working_cli_outcomes(uow.cursor, project_id=book['project_id'],book_id=book['book_id'],
            book_run_id=book['book_run_id'],outcomes=budgets)
    if budgets:
        raise KernelError("AUTHOR_WORKFLOW_RECONCILIATION_REQUIRED", "Original unknown consumption remains reserved; reconcile its receipt before adopting a successor generation policy")
    return current


def adopt_author_workflow(authority: Any, book_run_id: str, *, principal: Any,
                           expected_version: int | None, idempotency_key: str, settings: Any = None) -> dict[str, Any]:
    from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
    from novel_forge.modules.production_execution.execution_template import selected_book_template, selected_template
    book = authority.require(book_run_id)
    principal.require("book.authority.execute", book["project_id"])
    with AuthorityUnitOfWork(authority.database_url) as uow:
        uow.cursor.execute("""SELECT operation_id,command_payload,actor_id FROM authority_operation
            WHERE project_id=%s AND idempotency_scope='book:authority-mutation' AND idempotency_key=%s""", [book["project_id"], idempotency_key])
        previous = uow.cursor.fetchone()
        if previous:
            payload = previous[1].get("payload", {})
            if (previous[2] != principal.principal_id or payload.get("action") != "author_workflow_adopt"
                    or payload.get("book_run_id") != book_run_id
                    or expected_version is not None and payload.get("expected_version") != expected_version):
                raise KernelError("AUTHOR_WORKFLOW_IDEMPOTENCY_CONFLICT", "An adoption key retains its original exact work, principal and checkpoint")
            replay = uow.repositories.operations.transaction_result(previous[0], book["project_id"])
            if replay["status"] != "SUCCEEDED":
                raise KernelError("AUTHOR_WORKFLOW_RECONCILIATION_REQUIRED", "Reconcile the original adoption transaction before continuing")
            return {"operation_id": previous[0], "status": "SUCCEEDED", **replay["result"], "replayed": True}
    expected_version = book["version"] if expected_version is None else expected_version
    if settings is not None:
        with AuthorityUnitOfWork(authority.database_url) as uow:
            _require_workflow_checkpoint(uow, book, expected_version)
            admission = selected_book_template(uow.cursor, project_id=book["project_id"], book_id=book["book_id"], allow_literary_required=True)
            template = selected_template(admission["policy_snapshot"]["policy"], book["book_id"]) if admission else None
        if not template or template.get("author_workflow") != AUTHOR_WORKFLOW:
            from novel_forge.runtime_resources import runtime_resource
            from types import SimpleNamespace
            from novel_forge.modules.authority_handler_runtime.policy_commands import configure_execution_template
            configure_execution_template(settings, SimpleNamespace(project_id=book["project_id"], workspace_id=book["workspace_id"],
                book_id=book["book_id"], policy_version=idempotency_key + ":routing", idempotency_key=idempotency_key + ":routing",
                template_file=runtime_resource("config/execution_templates/author_first.json"),
                inherited_template=template))
    def commit(uow, operation_id, checkpoint):
        current = _require_workflow_checkpoint(uow, book, expected_version)
        admission = selected_book_template(uow.cursor, project_id=book["project_id"], book_id=book["book_id"])
        template = selected_template(admission["policy_snapshot"]["policy"], book["book_id"]) if admission else None
        if not template or template.get("author_workflow") != AUTHOR_WORKFLOW:
            raise KernelError("AUTHOR_WORKFLOW_TEMPLATE_REQUIRED", "Select the native authorized author-first template for this Book before adoption")
        content = {"version": "book-author-workflow-adoption.v1", "project_id": book["project_id"],
            "workspace_id": book["workspace_id"], "book_id": book["book_id"], "book_run_id": book_run_id,
            "source_profile_version": book["production_profile_version"], "source_book_version": expected_version,
            "author_workflow": dict(AUTHOR_WORKFLOW), "execution_template": admission,
            "history_rewritten": False, "accepted_through_chapter": current["accepted_through_chapter"]}
        asset = uow.repositories.asset_documents.materialize_output(AuthorityAssetWriteCommand(
            operation_id=operation_id, project_id=book["project_id"], asset_id="book-author-workflow:" + book_run_id,
            asset_type="book_author_workflow_policy", schema_version=content["version"], logical_ref="book-author-workflow/" + book_run_id,
            category="policy", output_key="book.author_workflow", role="primary", content=content,
            qualification_policy="authenticated-book-policy.v1", trace_id=operation_id, correlation_id=book["root_operation_id"]))
        uow.cursor.execute("UPDATE authority_book_production SET version=version+1,updated_at=NOW() WHERE book_run_id=%s", [book_run_id])
        checkpoint("after_author_workflow_adoption")
        return {"book_run_id": book_run_id, "policy_asset_version_id": asset.asset_version_id, "author_workflow": AUTHOR_WORKFLOW}
    return authority._execute_mutation(book=book, action="author_workflow_adopt", event_type="book.author_workflow.adopted",
        idempotency_key=idempotency_key, actor_id=principal.principal_id, trace_id=idempotency_key,
        correlation_id=book["root_operation_id"], causation_id=book["root_operation_id"],
        payload={"expected_version": expected_version}, handler=commit)


def validate_complete_prose(content: dict[str, Any]) -> None:
    text = content.get("text")
    if (not isinstance(text, str) or not text.strip() or "\0" in text
            or "\ufffd" in text or len(text) > 200000):
        raise KernelError("MANUSCRIPT_BODY_INVALID", "Only a complete, bounded, intact body is deliverable")
    if content.get("truncated") or content.get("finish_reason") in {"length", "max_tokens", "cancelled"}:
        raise KernelError("MANUSCRIPT_BODY_INCOMPLETE", "Truncated or cancelled output cannot be a complete manuscript")


def edit_selection_matches_source(candidate: Any, source: Any) -> bool:
    return candidate.asset_version_id == source.asset_version_id or (
        candidate.asset_type == "author_edit_candidate" and source.asset_version_id in {
            candidate.content.get("originating_draft_asset_version_id"), candidate.content.get("base_asset_version_id")})


def _working_selection_ref(book, chapter):
    return f"book-working-manuscript/{book['book_run_id']}/{chapter}"


def _optional_document(uow, project_id, logical_ref):
    try:
        return uow.repositories.asset_documents.require(project_id=project_id, logical_ref=logical_ref)
    except KernelError as error:
        if error.code != "AUTHORITY_ASSET_NOT_FOUND":
            raise
        return None


def select_working_candidate(authority, book_run_id, *, chapter, candidate_asset_version_id,
                             expected_version, idempotency_key, reason, principal,
                             length_revalidation_root_operation_id=""):
    from novel_forge.modules.chapter_authority.author_editor import require_source
    from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
    book = authority.require(book_run_id)
    principal.require("book.authority.execute", book["project_id"])
    principal.require("chapter.authority.execute", book["project_id"])
    if not reason.strip() or type(chapter) is not int or chapter < 1:
        raise KernelError("MANUSCRIPT_WORK_SELECTION_INVALID", "Require an exact chapter and work revision reason")
    def commit(uow, operation_id, checkpoint):
        current = _require_workflow_checkpoint(uow, book, expected_version, working_selection=True)
        if effective_workflow(uow.cursor, current) != AUTHOR_WORKFLOW or chapter <= current["accepted_through_chapter"] or chapter > current["current_chapter"]:
            raise KernelError("MANUSCRIPT_WORK_SELECTION_INVALID", "Work selection requires a delivered unaccepted chapter in this author-first run")
        source = selected_source(uow, current, chapter)
        scope = {key: current[key] for key in ("project_id", "workspace_id", "book_id")}
        scope["chapter"] = chapter
        candidate = require_source(uow, scope, candidate_asset_version_id)
        result_revalidation = None
        if candidate.asset_type == "author_edit_candidate":
            if length_revalidation_root_operation_id:
                raise KernelError("MANUSCRIPT_LENGTH_REVALIDATION_INVALID", "Completed result reuse requires a native length revision")
            if candidate.content.get("base_asset_version_id") != source.asset_version_id or candidate.content.get("base_asset_hash") != source.content_hash:
                raise KernelError("MANUSCRIPT_WORK_SELECTION_STALE", "Working candidate must revise this exact current source")
            if candidate.content.get("source_provenance", {}).get("kind") != "ASSISTANT_REVISION_PROPOSAL":
                raise KernelError("MANUSCRIPT_WORK_SELECTION_INVALID", "Human author input uses its separate author choice")
        else:
            from novel_forge.modules.chapter_authority.working_revision import ROOT_VERSIONS, REGENERATION_ROOT, CONTRACT, require_working_revision_frontier
            uow.cursor.execute("""SELECT to_jsonb(root) FROM authority_operation_output_asset output
                JOIN authority_operation child USING(operation_id)
                JOIN authority_operation root ON root.operation_id=child.root_operation_id
                WHERE output.asset_version_id=%s AND output.role='primary' AND child.status='SUCCEEDED'
                  AND child.project_id=%s AND child.definition_name IN ('chapter.revision.apply','chapter.candidate.select_best','chapter.draft.generate')""",
                [candidate.asset_version_id, current["project_id"]])
            origins = uow.cursor.fetchall()
            origin = origins[0][0] if len(origins) == 1 else {}
            binding = (origin.get("command_payload", {}).get("preparation_report") or {}).get("working_revision") or {}
            if (candidate.asset_type not in {"draft_version", "best_draft_candidate"}
                    and not (candidate.asset_type == "draft_chapter" and origin.get("definition_version") == REGENERATION_ROOT)
                    or origin.get("definition_version") not in ROOT_VERSIONS
                    or origin.get("status") in {"CANCELLED", "CANCELLATION_REQUESTED"}
                    or binding.get("contract_version") != CONTRACT or binding.get("book_run_id") != book_run_id
                    or binding.get("source_asset_version_id") != source.asset_version_id
                    or binding.get("source_content_hash") != source.content_hash):
                raise KernelError("MANUSCRIPT_WORK_SELECTION_STALE", "Native working revision must bind this exact current source")
            require_working_revision_frontier(uow, root=origin, book_run_id=book_run_id)
            if length_revalidation_root_operation_id:
                from novel_forge.modules.chapter_authority.working_revision import revalidate_completed_length_candidate
                if (candidate.asset_type != "draft_version" or not candidate.content.get("chapter_length_repair_scope")
                        or origin["operation_id"] != length_revalidation_root_operation_id):
                    raise KernelError("MANUSCRIPT_LENGTH_REVALIDATION_INVALID", "Reuse must bind this exact native length revision")
                result_revalidation = revalidate_completed_length_candidate(uow, root_operation_id=origin["operation_id"],
                    book_run_id=book_run_id, principal=principal)
                if not result_revalidation or result_revalidation["candidate_asset_version_id"] != candidate.asset_version_id:
                    raise KernelError("MANUSCRIPT_LENGTH_REVALIDATION_REJECTED", "Saved length correction requires supported comparison and preservation")
        validate_complete_prose(source_draft_content(candidate))
        require_prose_propagation(uow, current, candidate)
        session = _optional_document(uow, current["project_id"], _session_ref(scope))
        if session and session.content.get("status") == "ADOPTED_PENDING_REVIEW" and session.content.get("selected_asset_version_id") == source.asset_version_id:
            raise KernelError("MANUSCRIPT_AUTHOR_SELECTION_PRESENT", "An author-selected version requires an explicit author decision before replacement")
        previous = _optional_document(uow, current["project_id"], _working_selection_ref(current, chapter))
        native_origin = previous.content["native_source_asset_version_id"] if previous and previous.content.get("selected_asset_version_id") == source.asset_version_id else source.asset_version_id
        content = {**scope, "version": "book-working-manuscript-selection.v1", "book_run_id": book_run_id,
            "native_source_asset_version_id": native_origin, "source_asset_version_id": source.asset_version_id,
            "source_content_hash": source.content_hash, "selected_asset_version_id": candidate.asset_version_id,
            "selected_content_hash": candidate.content_hash, "actor_id": principal.principal_id, "reason": reason,
            "authority": "AUTHORIZED_WORK_VERSION_USAGE", "author_selection": "NOT_GRANTED", "formal_acceptance": "NOT_GRANTED"}
        if result_revalidation:
            content["result_revalidation"] = result_revalidation
        selection = uow.repositories.asset_documents.materialize_output(AuthorityAssetWriteCommand(
            operation_id=operation_id, project_id=current["project_id"], asset_id=previous.asset_id if previous else "book-work-selection:" + operation_id,
            asset_type="book_working_manuscript_selection", schema_version=content["version"], logical_ref=_working_selection_ref(current, chapter),
            category="working-manuscript", output_key="book.working_manuscript.selection", role="primary", content=content,
            qualification_policy="authenticated-work-version-only.v1", trace_id=operation_id, correlation_id=book["root_operation_id"],
            expected_current_asset_version_id=previous.asset_version_id if previous else None))
        uow.cursor.execute("UPDATE authority_book_production SET version=version+1,updated_at=NOW() WHERE book_run_id=%s", [book_run_id])
        checkpoint("after_working_manuscript_selection")
        return {"book_run_id": book_run_id, "chapter": chapter, "selection_asset_version_id": selection.asset_version_id,
            "source_asset_version_id": candidate.asset_version_id, "author_selection": "NOT_GRANTED", "formal_acceptance": "NOT_GRANTED"}
    payload = {"chapter": chapter, "candidate_asset_version_id": candidate_asset_version_id,
        "expected_version": expected_version, "reason": reason}
    if length_revalidation_root_operation_id:
        payload["length_revalidation_root_operation_id"] = length_revalidation_root_operation_id
    return authority._execute_mutation(book=book, action="working_manuscript_select", event_type="book.working_manuscript.selected",
        idempotency_key=idempotency_key, actor_id=principal.principal_id, trace_id=idempotency_key, correlation_id=book["root_operation_id"],
        causation_id=book["root_operation_id"], payload=payload, handler=commit,
        input_assets=authority.resolve_asset_refs(project_id=book["project_id"], asset_version_ids=(candidate_asset_version_id,)))


def selected_source(uow: Any, book: dict[str, Any], chapter: int) -> Any:
    return resolve_working_source(uow, book, chapter, prefer_accepted=False)[0]


def resolve_working_source(uow: Any, book: dict[str, Any], chapter: int, *, prefer_accepted: bool = True) -> tuple[Any, dict[str, Any]]:
    def accepted_source():
        uow.cursor.execute("""SELECT outcome.content->>'accepted_draft_asset_version_id'
            FROM authority_book_acceptance_lineage(%s) acceptance
            JOIN authority_asset_version outcome ON outcome.asset_version_id=acceptance.chapter_outcome_asset_version_id
            WHERE acceptance.chapter_number=%s AND acceptance.status='COMMITTED'""", [book["book_run_id"], chapter])
        return uow.cursor.fetchone()
    row = accepted_source() if prefer_accepted else None
    basis = "ACCEPTED_OUTCOME"
    if row is None:
        basis = "NATIVE_DELIVERY"
        uow.cursor.execute("""SELECT source_asset_version_id FROM authority_book_manuscript_delivery
            WHERE book_run_id=%s AND chapter_number=%s""", [book["book_run_id"], chapter])
        row = uow.cursor.fetchone()
    if row is None:
        basis = "RETAINED_WORKING_CONTINUATION"
        uow.cursor.execute("SELECT working_asset_version_id FROM authority_book_retained_working_continuation WHERE book_run_id=%s AND chapter_number=%s", [book["book_run_id"], chapter])
        row = uow.cursor.fetchone()
    if row is None and not prefer_accepted:
        basis = "ACCEPTED_OUTCOME"
        row = accepted_source()
    if row is None:
        basis = "NATIVE_DRAFT_OUTPUT"
        uow.cursor.execute("""SELECT output.asset_version_id FROM authority_book_chapter_request request
            JOIN authority_operation op ON op.root_operation_id=request.chapter_root_operation_id
            JOIN authority_operation_output_asset output USING(operation_id)
            WHERE request.book_run_id=%s AND request.chapter_number=%s
              AND op.definition_name='chapter.draft.generate' AND op.status='SUCCEEDED'
              AND output.output_key='chapter.draft' AND output.role='primary'
            ORDER BY request.generation DESC, output.asset_version_id ASC LIMIT 1""", [book["book_run_id"], chapter])
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("MANUSCRIPT_CHAPTER_MISSING", "No complete native manuscript exists at this chapter")
    source = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=row[0])
    resolution = {"native_basis": basis,
        "native_source": {"asset_version_id": source.asset_version_id, "content_hash": source.content_hash}, "overrides": []}
    accepted = prefer_accepted and basis == "ACCEPTED_OUTCOME"
    working = None if accepted else _optional_document(uow, book["project_id"], _working_selection_ref(book, chapter))
    if working and working.content.get("native_source_asset_version_id") == source.asset_version_id:
        selected = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=working.content["selected_asset_version_id"])
        if (working.content.get("book_run_id") != book["book_run_id"] or selected.content_hash != working.content.get("selected_content_hash")):
            raise KernelError("MANUSCRIPT_WORK_SELECTION_INVALID", "Working selection must retain exact run and source hash")
        source = selected
        resolution["overrides"].append({"asset_version_id": working.asset_version_id, "content_hash": working.content_hash})
    scope = {key: book[key] for key in ("project_id", "workspace_id", "book_id")}
    scope["chapter"] = chapter
    try:
        session = None if accepted else uow.repositories.asset_documents.require(project_id=book["project_id"], logical_ref=_session_ref(scope))
    except KernelError as error:
        if error.code != "AUTHORITY_ASSET_NOT_FOUND":
            raise
        session = None
    if session and session.content.get("selected_asset_version_id"):
        selected = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=session.content["selected_asset_version_id"])
        if edit_selection_matches_source(selected, source):
            source = selected
            resolution["overrides"].append({"asset_version_id": session.asset_version_id, "content_hash": session.content_hash})
    if source.governance != "CLEAR" or source.eligibility != "ELIGIBLE":
        raise KernelError("MANUSCRIPT_SOURCE_BLOCKED", "Selected manuscript is not governed for use")
    validate_complete_prose(source_draft_content(source))
    resolution["effective_source"] = {"asset_version_id": source.asset_version_id, "content_hash": source.content_hash}
    return source, resolution



def _working_dependency_binding(book, selection, source, root):
    from novel_forge.modules.chapter_authority.working_revision import CONTRACT, ROOT_VERSIONS
    binding = (root.get("command_payload", {}).get("preparation_report") or {}).get("working_revision") or {}
    chapter = source_draft_content(source)["chapter"]
    refs = {row["asset_version_id"]: row["content_hash"] for row in root.get("input_asset_snapshot", [])}
    inputs = binding.get("source_inputs") or {}
    previous = binding.get("previous_sources", [])
    if (root.get("definition_name") != "chapter.slice.run" or root.get("definition_version") not in ROOT_VERSIONS
            or root.get("definition_snapshot", {}).get("policy", {}).get("working_revision_contract") != CONTRACT
            or root.get("status") in {"CANCELLED", "CANCELLATION_REQUESTED"}
            or any(root.get(key) != book[key] for key in ("project_id", "workspace_id"))
            or root.get("command_payload", {}).get("book_id") != book["book_id"]
            or root.get("command_payload", {}).get("chapter") != chapter
            or binding.get("contract_version") != CONTRACT or binding.get("book_run_id") != book["book_run_id"]
            or selection.get("selected_asset_version_id") != source.asset_version_id
            or selection.get("selected_content_hash") != source.content_hash or selection.get("chapter") != chapter
            or any(selection.get(key) != book[key] for key in ("project_id", "workspace_id", "book_id", "book_run_id"))
            or binding.get("source_asset_version_id") != selection.get("source_asset_version_id")
            or binding.get("source_content_hash") != selection.get("source_content_hash")
            or set(inputs) != {"draft", "context", "plan"}
            or inputs["draft"] != {"asset_version_id": binding.get("source_asset_version_id"), "content_hash": binding.get("source_content_hash")}
            or any(refs.get(row.get("asset_version_id")) != row.get("content_hash") for row in inputs.values())
            or [row.get("chapter") for row in previous] != list(range(1, chapter))
            or any(refs.get(row.get("asset_version_id")) != row.get("content_hash") for row in previous)):
        raise KernelError("MANUSCRIPT_WORK_DEPENDENCY_INVALID", "Selected revision dependencies require exact native source, Book and frozen inputs")
    return {"sources": previous}


def _selected_working_dependencies(uow, book, source):
    from novel_forge.modules.chapter_authority.author_editor import require_source
    seen, editors, bases = set(), {}, {}
    while source.asset_type == "author_edit_candidate":
        if source.asset_version_id in seen:
            raise KernelError("MANUSCRIPT_REVISION_LINEAGE_INVALID", "Editor dependency lineage contains a cycle")
        seen.add(source.asset_version_id)
        if not source.content.get("base_asset_version_id"):
            return None
        scope = {key: book[key] for key in ("project_id", "workspace_id", "book_id")}
        scope["chapter"] = source_draft_content(source)["chapter"]
        parent = require_source(uow, scope, source.content["base_asset_version_id"])
        if source.content.get("base_asset_hash") != parent.content_hash:
            raise KernelError("MANUSCRIPT_WORK_DEPENDENCY_INVALID", "Editor dependencies require the exact base hash")
        editors[source.asset_version_id], bases[source.asset_version_id] = source, parent
        source = parent
    chapter = source_draft_content(source)["chapter"]
    selection = _optional_document(uow, book["project_id"], _working_selection_ref(book, chapter))
    if not selection:
        return None
    selection_content = selection.content
    if selection_content.get("selected_asset_version_id") != source.asset_version_id:
        selected_id = selection.content.get("selected_asset_version_id")
        if selected_id not in editors:
            return None
        editor, base = editors[selected_id], bases[selected_id]
        if (selection.content.get("selected_content_hash") != editor.content_hash
                or selection.content.get("source_asset_version_id") != base.asset_version_id
                or selection.content.get("source_content_hash") != base.content_hash
                or selection.content.get("chapter") != chapter
                or any(selection.content.get(key) != book[key] for key in ("project_id", "workspace_id", "book_id", "book_run_id"))):
            raise KernelError("MANUSCRIPT_WORK_DEPENDENCY_INVALID", "Editor working selection must retain its exact source")
        uow.cursor.execute("""SELECT content FROM authority_asset_version WHERE asset_id=%s
            AND content->>'selected_asset_version_id'=%s ORDER BY created_at DESC LIMIT 2""",
            [selection.asset_id, source.asset_version_id])
        versions = uow.cursor.fetchall()
        if len(versions) != 1:
            return None
        selection_content = versions[0][0]
    uow.cursor.execute("""SELECT to_jsonb(root), child.definition_name FROM authority_operation_output_asset output
        JOIN authority_operation child USING(operation_id)
        JOIN authority_operation root ON root.operation_id=child.root_operation_id
        WHERE output.asset_version_id=%s AND output.role='primary' AND child.status='SUCCEEDED'
          AND child.project_id=%s AND child.definition_name IN ('chapter.revision.apply','chapter.candidate.select_best','chapter.draft.generate')""",
        [source.asset_version_id, book["project_id"]])
    origins = uow.cursor.fetchall()
    if len(origins) != 1:
        raise KernelError("MANUSCRIPT_WORK_DEPENDENCY_INVALID", "Selected work requires one native revision origin")
    root, stage = origins[0]
    if root.get("status") in {"CANCELLED", "CANCELLATION_REQUESTED"}:
        return None
    dependencies = _working_dependency_binding(book, selection_content, source, root)
    if stage == "chapter.candidate.select_best":
        content = source_draft_content(source)
        chosen = content.get("selected_source_asset_version_id")
        review_id = (content.get("selected_review") or {}).get("selection_review_source_asset_version_id")
        uow.cursor.execute("""SELECT child.definition_name FROM authority_operation_output_asset output
            JOIN authority_operation child USING(operation_id)
            WHERE output.asset_version_id=%s AND output.role='primary' AND child.status='SUCCEEDED'
              AND child.root_operation_id=%s AND child.project_id=%s""",
            [chosen, root["operation_id"], book["project_id"]])
        revised = uow.cursor.fetchall()
        if revised != [("chapter.revision.apply",)]:
            binding = root["command_payload"]["preparation_report"]["working_revision"]
            if chosen != binding["source_asset_version_id"]:
                return None
            uow.cursor.execute("""SELECT v.content FROM authority_operation_output_asset output
                JOIN authority_operation child USING(operation_id) JOIN authority_asset_version v USING(asset_version_id)
                WHERE output.asset_version_id=%s AND output.role='primary' AND child.status='SUCCEEDED'
                  AND child.root_operation_id=%s AND child.project_id=%s AND child.definition_name='chapter.review.evaluate'""",
                [review_id, root["operation_id"], book["project_id"]])
            rows = uow.cursor.fetchall()
            from novel_forge.modules.review.diagnostics import prose_hash
            if (len(rows) != 1 or rows[0][0].get("target_asset_version_id") != chosen
                    or rows[0][0].get("target_text_hash") != prose_hash(content["text"])):
                return None
    return dependencies


def working_dependency_changes(uow: Any, book: dict[str, Any]) -> tuple[list[Any], dict[int, list[dict[str, Any]]]]:
    from .working_prose import LONGFORM_POLICY_VERSIONS, working_source_rows
    uow.cursor.execute("""SELECT DISTINCT ON (r.chapter_number) r.chapter_number, output.asset_version_id,
            COALESCE(d.context_snapshot,r.command_payload #> '{preparation_report,working_manuscript}','{\"sources\":[]}'::jsonb)
            FROM authority_book_chapter_request r
            JOIN authority_operation op ON op.root_operation_id=r.chapter_root_operation_id
            JOIN authority_operation_output_asset output USING(operation_id)
            LEFT JOIN authority_book_manuscript_delivery d USING(chapter_request_id)
            WHERE r.book_run_id=%s AND op.definition_name='chapter.draft.generate' AND op.status='SUCCEEDED'
              AND output.output_key='chapter.draft' AND output.role='primary'
            ORDER BY r.chapter_number,r.generation DESC""", [book["book_run_id"]])
    deliveries = uow.cursor.fetchall()
    uow.cursor.execute("SELECT chapter_number,working_asset_version_id,context_snapshot FROM authority_book_retained_working_continuation WHERE book_run_id=%s ORDER BY chapter_number", [book["book_run_id"]])
    retained = uow.cursor.fetchall()
    if {row[0] for row in deliveries}.intersection(row[0] for row in retained):
        raise KernelError("MANUSCRIPT_CONTINUATION_COLLISION", "A retained original cannot replace a separately delivered native Draft")
    deliveries = sorted([*deliveries, *retained], key=lambda row: row[0])
    sources = {number: selected_source(uow, book, number) for number, _, _ in deliveries}
    selected = {number: source.asset_version_id for number, source in sources.items()}
    changes = {}
    resolutions = {}
    for number, _, dependencies in deliveries:
        dependencies = _selected_working_dependencies(uow, book, sources[number]) or dependencies
        affected = {}
        for row in working_source_rows({"sources": [], **dependencies}):
            predecessor = row["chapter"]
            current_id = selected.get(predecessor)
            lineage_changed = False
            if (dependencies.get("projection_policy") or {}).get("version") in LONGFORM_POLICY_VERSIONS:
                if predecessor not in resolutions:
                    resolutions[predecessor] = resolve_working_source(uow, book, predecessor)
                current, resolution = resolutions[predecessor]
                current_id = current.asset_version_id
                lineage_changed = current_id == row["asset_version_id"] and (
                    current.content_hash != row["content_hash"] or resolution != row["source_resolution"])
            if current_id != row["asset_version_id"] or lineage_changed:
                affected[predecessor] = {"chapter": predecessor, "source_asset_version_id": row["asset_version_id"],
                    "current_asset_version_id": current_id,
                    **({"source_resolution_changed": True} if lineage_changed else {})}
            for inherited in changes.get(predecessor, []):
                affected.setdefault(inherited["chapter"], {**inherited, "via_chapter": predecessor})
        changes[number] = list(affected.values())
    return [(number, dependencies) for number, _, dependencies in deliveries], changes


def _working_task_cast_ref(uow, book):
    uow.cursor.execute("""SELECT foundation_set FROM authority_book_production_input_snapshot
        WHERE snapshot_id=%s AND project_id=%s AND workspace_id=%s AND book_id=%s""",
        [book["input_snapshot_id"], book["project_id"], book["workspace_id"], book["book_id"]])
    row = uow.cursor.fetchone()
    bindings = [binding for binding in (row[0].get("bindings", []) if row else [])
        if isinstance(binding, Mapping) and binding.get("role") == "CHARACTER_CAST"]
    if len(bindings) != 1:
        raise KernelError("WORKING_TASK_CAST_INVALID", "Task character names require this Book's exact frozen Cast binding")
    return {key: bindings[0][key] for key in ("asset_version_id", "content_hash")}


def _working_task_sources(uow, book, pointers, *, require_current=True):
    sources = []
    for pointer in pointers:
        if not isinstance(pointer, Mapping) or any(not isinstance(pointer.get(key), str) or not pointer[key]
                for key in ("asset_version_id", "content_hash")):
            raise KernelError("WORKING_TASK_SOURCE_INVALID", "Working task requires exact plan version pointers")
        source = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=pointer["asset_version_id"])
        cast = source.asset_type == "character_cast" or source.content.get("generator_operation_name") == "character.cast.generate"
        if (source.content_hash != pointer["content_hash"] or require_current and (
                (source.eligibility, source.governance) != ("ELIGIBLE", "CLEAR") or not cast and source.lifecycle != "ACTIVE")):
            raise KernelError("WORKING_TASK_SOURCE_CHANGED", "Working task plan differs from its frozen eligible version")
        uow.cursor.execute("""SELECT EXISTS(SELECT 1 FROM story_plan_binding binding
            WHERE binding.project_id=%s AND binding.book_id=%s AND binding.asset_version_id=%s
              AND (NOT %s OR binding.freshness='CURRENT' AND EXISTS(
                SELECT 1 FROM active_story_plan_version active WHERE active.binding_id=binding.binding_id)))
            OR EXISTS(SELECT 1 FROM authority_asset_version projection
                JOIN authority_asset asset USING(asset_id)
                JOIN story_plan_binding binding ON binding.asset_version_id=projection.content->>'source_planning_candidate_asset_version_id'
                  AND binding.project_id=asset.project_id
                JOIN authority_operation_output_asset output ON output.asset_version_id=projection.asset_version_id
                  AND output.output_key='story_planning.chapter_plan_projection'
                JOIN authority_operation operation USING(operation_id)
                WHERE asset.project_id=%s AND binding.book_id=%s AND projection.asset_version_id=%s
                  AND asset.asset_type='chapter_plan' AND operation.status='SUCCEEDED'
                  AND (NOT %s OR binding.freshness='CURRENT' AND EXISTS(
                    SELECT 1 FROM active_story_plan_version active WHERE active.binding_id=binding.binding_id)))
            OR EXISTS(SELECT 1 FROM authority_book_production_input_snapshot snapshot,
                jsonb_array_elements(snapshot.foundation_set->'bindings') binding
                WHERE snapshot.snapshot_id=%s AND snapshot.project_id=%s AND snapshot.workspace_id=%s AND snapshot.book_id=%s
                  AND binding->>'role'='CHARACTER_CAST' AND binding->>'asset_version_id'=%s AND binding->>'content_hash'=%s)""",
            [book["project_id"], book["book_id"], source.asset_version_id, require_current,
             book["project_id"], book["book_id"], source.asset_version_id, require_current,
             book["input_snapshot_id"], book["project_id"], book["workspace_id"], book["book_id"], source.asset_version_id, source.content_hash])
        if uow.cursor.fetchone() != (True,):
            raise KernelError("WORKING_TASK_SOURCE_SCOPE_INVALID", "Working task sources must belong to this Book's governed plans")
        sources.append({"asset_version_id": source.asset_version_id, "content_hash": source.content_hash,
            "asset_type": source.asset_type, "content": source.content})
    return sources


def freeze_working_context(uow: Any, book: dict[str, Any], chapter: int, *,
                           projection_policy: Any = "FROM_PROFILE", scheduling_policy: Any = None,
                           task_source_refs: list[dict[str, str]] | None = None,
                           task_stage: str = "CHAPTER") -> dict[str, Any]:
    from .working_prose import CONTEXT_VERSION, LEGACY_GUIDANCE, LONGFORM_POLICY_VERSIONS, MEMORY_POLICY_VERSIONS, PROGRESSION_POLICY_VERSION, RESOLVED_POLICY_VERSIONS, RETRIEVAL_POLICY_VERSIONS, TASK_POLICY_VERSIONS, WORKING_SCHEDULE_POLICY, freeze_source_history, project_working_sources, working_instruction, working_prose_policy

    schedule_policy = scheduling_policy
    if projection_policy == "FROM_PROFILE":
        profile_id = book.get("production_profile_version")
        profile = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=profile_id) if profile_id else None
        projection_policy = working_prose_policy(profile.content) if profile else None
        from .working_policy import selected_working_policy
        projection_policy = selected_working_policy(uow, book, projection_policy, target_chapter=chapter)
        schedule_policy = profile.content.get("working_schedule_policy") if profile else None
    projection_policy = working_prose_policy({"working_prose_policy": projection_policy})
    if schedule_policy is not None and (schedule_policy != WORKING_SCHEDULE_POLICY or not projection_policy
            or projection_policy["version"] not in MEMORY_POLICY_VERSIONS):
        raise KernelError("WORKING_SCHEDULE_POLICY_INVALID", "Working scheduling requires the exact versioned source projection policy")
    task = None
    if projection_policy and projection_policy["version"] in TASK_POLICY_VERSIONS:
        from .working_task import build_working_task
        if not task_source_refs:
            raise KernelError("WORKING_TASK_REQUIRED", "Task projection requires the exact current planning input")
        pointers = list(task_source_refs)
        pointers.append(_working_task_cast_ref(uow, book))
        task = build_working_task(sources=_working_task_sources(uow, book, pointers), book=book,
            chapter=chapter, stage=task_stage, extra_queries=projection_policy["queries"])
    _, changes = working_dependency_changes(uow, book)
    rows = []
    frozen_memory_sources = {} if task is not None else None
    memory_enabled = bool(projection_policy and projection_policy["version"] in MEMORY_POLICY_VERSIONS)
    history = projection_policy["history_chapters"] if projection_policy else 4
    if projection_policy and projection_policy["version"] == PROGRESSION_POLICY_VERSION and chapter - 1 > history:
        raise KernelError("WORKING_PROSE_HISTORY_INCOMPLETE", "Progression requires every predecessor source within its declared history allocation")
    longform = bool(projection_policy and projection_policy["version"] in LONGFORM_POLICY_VERSIONS)
    resolved = []
    for number in range(1 if longform else max(1, chapter - history), chapter):
        resolution = None
        if projection_policy and projection_policy["version"] in RESOLVED_POLICY_VERSIONS:
            source, resolution = resolve_working_source(uow, book, number)
        else:
            source = selected_source(uow, book, number)
        resolved.append((number, source, resolution))
    require_prose_propagation_batch(uow, book, [source for _, source, _ in resolved])
    for number, source, resolution in resolved:
        text = source_draft_content(source)["text"]
        rows.append({"chapter": number, "asset_version_id": source.asset_version_id,
            "content_hash": source.content_hash, "text_hash": text_hash(text),
            **({"text": text} if projection_policy else {"excerpt": text[-2400:] if number == chapter - 1 else text[-600:]}),
            "status": "UNREVIEWED_WORKING_PROSE", "character_knowledge": "NOT_VERIFIED"})
        if resolution is not None:
            rows[-1]["source_resolution"] = resolution
        if memory_enabled:
            if task is not None:
                from .manuscript_memory import freeze_source_memory
                memory, provenance, reference = freeze_source_memory(uow, book, source)
                frozen_memory_sources[source.asset_version_id] = reference
            else:
                from .manuscript_memory import source_memory
                memory, provenance = source_memory(uow, book, source)
            rows[-1].update(observations=memory, memory_provenance=provenance)
        if changes.get(number):
            rows[-1]["dependency_changes"] = changes[number]
    memory_packet, selection = None, None
    if task is not None:
        from .working_selection import select_working_context, selected_memory_ranges
        selection = select_working_context(rows, target_chapter=chapter, policy=projection_policy, task=task)
    if memory_enabled:
        from novel_forge.modules.narrative_state.working_memory import compile_working_memory, bind_packet_coverage
        retrieval = projection_policy["version"] in RETRIEVAL_POLICY_VERSIONS
        memory_packet = compile_working_memory(rows, queries=projection_policy["queries"],
                                               max_characters=None if retrieval else projection_policy["max_characters"] // 3 if projection_policy["max_characters"] is not None else max(1, sum(len(row["text"]) for row in rows)),
                                               dependency_closed=projection_policy["version"] in {"working-prose-projection.v7", *RETRIEVAL_POLICY_VERSIONS},
                                               recent_complete_from=chapter - projection_policy["recent_complete_chapters"] if retrieval else None,
                                               **({"task": task, "selected_ranges": selected_memory_ranges(selection),
                                                   "frozen_sources": frozen_memory_sources,
                                                   "lifecycle": projection_policy["version"] == "working-prose-projection.v10"} if task is not None else {}))
    source_history = None
    if projection_policy:
        if task is not None:
            selection = select_working_context(rows, target_chapter=chapter, policy=projection_policy, task=task, memory=memory_packet)
            from .working_prose import _project_ranges
            rows = _project_ranges(rows, {(row["chapter"], row["start"], row["end"]) for row in selection["passages"]},
                passage_characters=projection_policy["passage_characters"])
        else:
            rows = project_working_sources(rows, target_chapter=chapter, policy=projection_policy, memory=memory_packet)
        if longform:
            source_history = freeze_source_history(rows, book=book, target_chapter=chapter)
    if memory_packet is not None:
        memory_packet = bind_packet_coverage(memory_packet, rows)
    if longform:
        rows = [row for row in rows if row["passages"]]
    result = {"version": CONTEXT_VERSION if projection_policy else "working-manuscript-context.v1", "book_run_id": book["book_run_id"],
        "project_id": book["project_id"], "book_id": book["book_id"], "target_chapter": chapter,
        "accepted_through_chapter": int(book["accepted_through_chapter"]), "sources": rows,
        "authority": "AUTHOR_WORKING_PROSE_ONLY", "structured_facts": [],
        **({"projection_policy": projection_policy} if projection_policy else {}),
        **({"scheduling_policy": dict(schedule_policy)} if schedule_policy else {}),
        **({"working_memory": memory_packet} if memory_packet is not None else {}),
        **({"source_history": source_history} if source_history is not None else {}),
        **({"retrieval_task": task, "context_selection": selection} if task is not None else {}),
        "instruction": working_instruction(projection_policy) if projection_policy else LEGACY_GUIDANCE["instruction"]}
    snapshot = {**result, "snapshot_hash": canonical_hash(result)}
    if task is not None:
        from .working_prose import validate_working_projection
        validate_working_projection(snapshot, project_id=book["project_id"], book_id=book["book_id"], target_chapter=chapter)
    return snapshot


def _prose_source_lineage(uow, book, source):
    from novel_forge.modules.chapter_authority.author_editor import require_source
    lineage, seen = [], set()
    while source is not None:
        if source.asset_version_id in seen:
            raise KernelError("MANUSCRIPT_REVISION_LINEAGE_INVALID", "Prose source lineage contains a cycle")
        seen.add(source.asset_version_id)
        lineage.append(source)
        content = source_draft_content(source)
        parent_id = (source.content.get("base_asset_version_id") if source.asset_type == "author_edit_candidate"
                     else content.get("source_draft_version_id"))
        if not parent_id:
            break
        scope = {key: book[key] for key in ("project_id", "workspace_id", "book_id")}
        scope["chapter"] = content["chapter"]
        parent = require_source(uow, scope, parent_id)
        if source.asset_type == "author_edit_candidate" and source.content.get("base_asset_hash") != parent.content_hash:
            raise KernelError("MANUSCRIPT_REVISION_LINEAGE_INVALID", "Editor source hash differs from its exact base")
        source = parent
    return reversed(lineage)


def _verified_prose_resolutions(review, text):
    from novel_forge.modules.review.diagnostics import open_diagnoses, validate_location
    if any(item.get("status") != "PRESERVED" for item in review.get("preservation_checks", [])):
        return set()
    remaining = set(review.get("remaining_issue_codes", [])) | {
        item["code"] for item in open_diagnoses(review) if item.get("status", "OPEN") == "OPEN"}
    checks = set()
    for check in review.get("resolution_checks", []):
        if (check.get("status") != "SATISFIED" or check.get("preservation") != "PRESERVED"
                or check.get("code") in remaining or check.get("code") not in review.get("resolved_issue_codes", [])):
            continue
        try:
            validate_location(check.get("evidence") or {}, text)
        except KernelError:
            continue
        checks.add(check["code"])
    return {item["code"] for item in review.get("issue_lineage", [])
        if item.get("verified_by_rereview") is True and item.get("to_status") == "RESOLVED"
        and item.get("code") in checks}


def _prose_diagnosis_identity(review, code, version, text):
    from novel_forge.modules.review.diagnostics import open_diagnoses, validate_location
    issue = next((item for item in open_diagnoses(review) if item["code"] == code), None)
    if not issue or any(not issue.get(key) for key in ("category", "judgment_kind", "violated_constraint", "revision_goal")) or not issue.get("acceptance_criteria"):
        return None
    try:
        location = validate_location(issue.get("evidence_locator") or {}, text)
    except KernelError:
        return None
    return canonical_hash({"source_version": version, "code": code,
        **{key: issue[key] for key in ("category", "judgment_kind", "violated_constraint", "revision_goal", "acceptance_criteria")},
        "preserve": issue.get("preserve"), "repair": issue.get("repair"),
        "support": {key: issue.get(key) for key in ("supporting_evidence", "candidate_supporting_evidence",
            "paired_evidence", "related_fact_ids", "related_character_ids", "related_obligation_ids")},
        "evidence": {key: location[key] for key in ("start", "end", "quote", "excerpt_digest", "offset_unit")}})


def _require_scope_proposal_review(uow, book, source):
    from novel_forge.modules.review.diagnostics import prose_hash, scope_proposal_preserved
    content = source_draft_content(source)
    proposal = content.get("prose_scope_proposal")
    if not proposal or source.asset_type not in {"draft_version", "best_draft_candidate"}:
        return
    if (proposal.get("contract_version") != "working-prose-scope-proposal.v1"
            or proposal.get("target_text_hash") != prose_hash(content["text"]) or not proposal.get("issue_codes")
            or not proposal.get("changed_target_ranges")
            or any(type(span.get("start")) is not int or type(span.get("end")) is not int
                or not 0 <= span["start"] <= span["end"] <= len(content["text"])
                for span in proposal.get("changed_target_ranges") or [])):
        raise KernelError("MANUSCRIPT_SCOPE_PROPOSAL_INVALID", "Scope proposal must bind the exact complete prose")
    aliases = [source.asset_version_id, content.get("selected_source_asset_version_id") or source.asset_version_id]
    uow.cursor.execute("""SELECT v.content FROM authority_operation_output_asset produced
        JOIN authority_operation producer ON producer.operation_id=produced.operation_id
        JOIN authority_operation reviewer ON reviewer.root_operation_id=producer.root_operation_id
        JOIN authority_operation_output_asset reviewed ON reviewed.operation_id=reviewer.operation_id
        JOIN authority_asset_version v ON v.asset_version_id=reviewed.asset_version_id
        WHERE produced.asset_version_id=%s AND produced.role='primary'
          AND producer.project_id=%s AND producer.workspace_id=%s
          AND reviewer.project_id=producer.project_id AND reviewer.workspace_id=producer.workspace_id
          AND reviewer.definition_name='chapter.revision.review' AND reviewer.status='SUCCEEDED'
          AND reviewed.output_key='chapter.rereview' AND reviewed.role='primary'
          AND v.content->>'revision_version_id'=ANY(%s)""",
        [source.asset_version_id, book["project_id"], book["workspace_id"], aliases])
    for (review,) in uow.cursor.fetchall():
        if scope_proposal_preserved(proposal, content["text"], target_text_hash=review.get("target_text_hash"),
                report_type=review.get("report_type"), resolution_checks=review.get("resolution_checks") or [],
                preservation_checks=review.get("preservation_checks") or []):
            return
    raise KernelError("MANUSCRIPT_SCOPE_PROPOSAL_PENDING_REVIEW",
        "Keep the complete expanded-scope candidate readable; exact-source preservation is required before downstream use")


def _prose_reviews(uow, book, source_ids):
    predicate = "=ANY(%s)" if isinstance(source_ids, list) else "=%s"
    uow.cursor.execute(f"""SELECT v.asset_version_id,v.content FROM authority_operation_output_asset output
        JOIN authority_operation operation USING(operation_id)
        JOIN authority_asset_version v USING(asset_version_id)
        JOIN authority_asset asset ON asset.asset_id=v.asset_id
        WHERE operation.project_id=%s AND operation.status='SUCCEEDED'
          AND asset.asset_type IN ('review_report','re_review_report')
          AND COALESCE(v.content->>'revision_version_id',v.content->>'target_asset_version_id'){predicate}
        ORDER BY operation.created_at""", [book["project_id"], source_ids])
    return uow.cursor.fetchall()


def require_prose_propagation_batch(uow, book, sources):
    if not sources:
        return
    lineages = {source.asset_version_id: tuple(_prose_source_lineage(uow, book, source)) for source in sources}
    aliases = list(dict.fromkeys(identity for lineage in lineages.values() for version in lineage
        for identity in (version.asset_version_id, source_draft_content(version).get("selected_source_asset_version_id") or version.asset_version_id)))
    reviews = {identity: [] for identity in aliases}
    for identity, content in _prose_reviews(uow, book, aliases):
        reviews[content.get("revision_version_id") or content.get("target_asset_version_id")].append((identity, content))
    for source in sources:
        require_prose_propagation(uow, book, source, lineage=lineages[source.asset_version_id], review_index=reviews)


def require_prose_propagation(uow: Any, book: dict[str, Any], source: Any, *, lineage=None, review_index=None) -> None:
    from novel_forge.modules.review.diagnostics import major_contradiction_codes, prose_hash
    _require_scope_proposal_review(uow, book, source)
    pending, seen_reviews = {}, {}
    for version in lineage if lineage is not None else _prose_source_lineage(uow, book, source):
        content = source_draft_content(version)
        aliases = list(dict.fromkeys([version.asset_version_id, content.get("selected_source_asset_version_id") or version.asset_version_id]))
        reviews = {}
        for source_id in aliases:
            reviews.update(_prose_reviews(uow, book, source_id) if review_index is None else review_index[source_id])
        embedded = content.get("selected_review")
        if isinstance(embedded, dict):
            reviews[embedded.get("selection_review_source_asset_version_id")] = embedded
        for review_id, review in reviews.items():
            target_id = review.get("revision_version_id") or review.get("target_asset_version_id")
            if target_id not in aliases or review.get("target_text_hash") != prose_hash(content["text"]):
                continue
            codes = major_contradiction_codes(review, text=content["text"], source_id=target_id)
            identities = {code: _prose_diagnosis_identity(review, code, version.asset_version_id, content["text"]) for code in codes}
            if review.get("report_type") == "ReReviewReport":
                prior_id = review.get("initial_review_version_id") or (review.get("prior_review_evidence") or {}).get("asset_version_id")
                for code in _verified_prose_resolutions(review, content["text"]):
                    pending.pop((prior_id, code), None)
                    identity = seen_reviews.get(prior_id, {}).get(code)
                    # WHY: Independently repeated diagnoses can close together only with identical source, repair goal, criteria and supporting evidence.
                    if identity is not None:
                        pending = {key: value for key, value in pending.items() if value["identity"] != identity}
            for code in codes:
                if review.get("report_type") == "ReReviewReport":
                    # WHY: Carrying an open issue advances its review lineage without leaving an ancestral duplicate ban.
                    pending.pop((prior_id, code), None)
                pending[(review_id, code)] = {"code": code, "identity": identities[code]}
            seen_reviews[review_id] = identities
    problems = sorted({value["code"] for value in pending.values()})
    if problems:
        raise KernelError("MANUSCRIPT_MAJOR_CONTRADICTION_UNRESOLVED",
            "Retain this complete candidate for targeted revision; it cannot become affected later prose's automatic source",
            details={"source_asset_version_id": source.asset_version_id, "diagnosis_codes": problems})


def verify_working_context(uow: Any, book: dict[str, Any], snapshot: dict[str, Any], *, require_current: bool = True) -> None:
    from .working_prose import CONTEXT_VERSION, MEMORY_POLICY_VERSIONS, RESOLVED_POLICY_VERSIONS, TASK_POLICY_VERSIONS, validate_working_projection, working_source_rows
    enhanced = snapshot.get("projection_policy") is not None
    if enhanced:
        validate_working_projection(snapshot, project_id=book["project_id"], book_id=book["book_id"])
    plain = {key: value for key, value in snapshot.items() if key != "snapshot_hash"}
    if (snapshot.get("version") not in {"working-manuscript-context.v1", CONTEXT_VERSION}
            or snapshot.get("snapshot_hash") != canonical_hash(plain)
            or any(snapshot.get(key) != book[key] for key in ("project_id", "book_id", "book_run_id"))):
        raise KernelError("MANUSCRIPT_CONTEXT_INVALID", "Working context must bind its exact Book and immutable sources")
    task = snapshot.get("retrieval_task") if (snapshot.get("projection_policy") or {}).get("version") in TASK_POLICY_VERSIONS else None
    if task is not None:
        from .working_task import validate_working_task
        validate_working_task(task, book=book, chapter=snapshot["target_chapter"], stage=task["stage"],
            sources=_working_task_sources(uow, book, task["sources"], require_current=require_current),
            extra_queries=snapshot["projection_policy"]["queries"])
    history_sources = working_source_rows(snapshot)
    if require_current:
        def current_source(number):
            if enhanced and snapshot["projection_policy"]["version"] in RESOLVED_POLICY_VERSIONS:
                return resolve_working_source(uow, book, number)[0]
            return selected_source(uow, book, number)
        if enhanced and snapshot["projection_policy"]["version"] in MEMORY_POLICY_VERSIONS:
            _, changes = working_dependency_changes(uow, book)
            current = snapshot["accepted_through_chapter"] == int(book["accepted_through_chapter"]) and all(current_source(row["chapter"]).asset_version_id == row["asset_version_id"]
                          and changes.get(row["chapter"], []) == row.get("dependency_changes", []) for row in history_sources)
        else:
            current = snapshot == freeze_working_context(uow, book, snapshot["target_chapter"],
                projection_policy=snapshot.get("projection_policy") if enhanced else None,
                scheduling_policy=snapshot.get("scheduling_policy"))
        if not current:
            raise KernelError("MANUSCRIPT_DEPENDENCY_CHANGED", "A selected predecessor changed; retain the result and rebind only affected continuation")
    projected_sources = {row["chapter"]: row for row in snapshot["sources"]} if enhanced else {}
    source_documents = {item["asset_version_id"]: uow.repositories.asset_documents.require(
        project_id=book["project_id"], asset_version_id=item["asset_version_id"]) for item in history_sources}
    if require_current:
        require_prose_propagation_batch(uow, book, list(source_documents.values()))
    for item in history_sources:
        if require_current and enhanced and snapshot["projection_policy"]["version"] in RESOLVED_POLICY_VERSIONS:
            _, resolution = resolve_working_source(uow, book, item["chapter"])
            if resolution != item["source_resolution"]:
                raise KernelError("MANUSCRIPT_DEPENDENCY_CHANGED", "Effective source selection lineage changed after freeze")
        source = source_documents[item["asset_version_id"]]
        if source.content_hash != item["content_hash"] or text_hash(source_draft_content(source)["text"]) != item["text_hash"]:
            raise KernelError("MANUSCRIPT_SOURCE_HASH_INVALID", "Working manuscript source failed its exact version binding")
        if snapshot.get("working_memory") and task is None:
            for entry in snapshot["working_memory"]["entries"]:
                if entry["source"]["asset_version_id"] != source.asset_version_id:
                    continue
                provenance = entry["provenance"]
                if provenance.get("kind") == "WRITER_SELF_OBSERVATION":
                    memory = source_draft_content(source).get("working_memory", {}).get("observations")
                else:
                    annotation = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=provenance.get("asset_version_id"))
                    if (annotation.asset_type != "manuscript_memory" or annotation.content_hash != provenance.get("content_hash")
                            or annotation.content.get("source_asset_version_id") != source.asset_version_id
                            or annotation.content.get("source_content_hash") != source.content_hash
                            or annotation.content.get("book_run_id") != book["book_run_id"]):
                        raise KernelError("WORKING_MEMORY_SOURCE_INVALID", "Frozen observation provenance differs from its exact Book source")
                    memory = annotation.content["observations"]
                expected = {k: v for k, v in entry.items() if k not in {"source", "provenance", "state_role"}}
                if not memory or expected not in memory["entries"]:
                    raise KernelError("WORKING_MEMORY_SOURCE_INVALID", "Frozen observations do not belong to the located source")
        if enhanced and (len(source_draft_content(source)["text"]) != item["source_characters"]
                or any(source_draft_content(source)["text"][p["start"]:p["end"]] != p["text"] for p in projected_sources.get(item["chapter"], {}).get("passages", []))):
            raise KernelError("MANUSCRIPT_SOURCE_HASH_INVALID", "Working passage does not match its exact source range")
    if task is not None:
        from .manuscript_memory import replay_source_memory
        from .working_selection import select_working_context, selected_memory_ranges
        from .working_prose import _project_ranges
        from novel_forge.modules.narrative_state.working_memory import bind_packet_coverage, compile_working_memory
        raw_sources = [{**row, "text": source_draft_content(source_documents[row["asset_version_id"]])["text"],
            "status": "UNREVIEWED_WORKING_PROSE", "character_knowledge": "NOT_VERIFIED"} for row in history_sources]
        coverage = snapshot["working_memory"]["source_coverage"]
        if (len(coverage) != len(raw_sources) or any(not isinstance(row, dict)
                or set(row) != {"chapter", "asset_version_id", "status", "memory_source"}
                or row["chapter"] != source["chapter"] or row["asset_version_id"] != source["asset_version_id"]
                for row, source in zip(coverage, raw_sources))):
            raise KernelError("WORKING_MEMORY_SOURCE_INVALID", "Task replay requires every frozen observation source, including omissions")
        frozen_memory_sources = {}
        for row, source in zip(coverage, raw_sources, strict=True):
            memory, provenance = replay_source_memory(uow, book, source_documents[source["asset_version_id"]], row["memory_source"])
            source.update(observations=memory, memory_provenance=provenance)
            frozen_memory_sources[source["asset_version_id"]] = row["memory_source"]
        initial = select_working_context(raw_sources, target_chapter=snapshot["target_chapter"],
            policy=snapshot["projection_policy"], task=task)
        memory = compile_working_memory(raw_sources, queries=snapshot["projection_policy"]["queries"],
            max_characters=None, dependency_closed=True,
            recent_complete_from=snapshot["target_chapter"] - snapshot["projection_policy"]["recent_complete_chapters"],
            task=task, selected_ranges=selected_memory_ranges(initial), frozen_sources=frozen_memory_sources,
            lifecycle=snapshot["projection_policy"]["version"] == "working-prose-projection.v10")
        expected = select_working_context(raw_sources, target_chapter=snapshot["target_chapter"],
            policy=snapshot["projection_policy"], task=task, memory=memory)
        ranges = {(row["chapter"], row["start"], row["end"]) for row in expected["passages"]}
        projected = _project_ranges(raw_sources, ranges, passage_characters=snapshot["projection_policy"]["passage_characters"])
        if bind_packet_coverage(memory, projected) != snapshot["working_memory"]:
            raise KernelError("WORKING_MEMORY_SELECTION_CHANGED", "Working memory must replay every seed and causal source from its frozen observations")
        if expected != snapshot["context_selection"] or [row for row in projected if row["passages"]] != snapshot["sources"]:
            raise KernelError("WORKING_SELECTION_CHANGED", "Working context must replay the exact frozen task selection")


def _current_planning_correction(uow, *, book, operation, request, refs, target):
    evidence = request.get("change_evidence_version_ids") or []
    if (operation["definition_name"] != "story_planning.generate"
            or target != writing_frontier(book) or target <= book.get("accepted_through_chapter", target)
            or book.get("state") not in {"READY", "PAUSED"} or book.get("active_chapter_request_id")
            or not operation.get("actor_id") or request.get("actor_id") != operation["actor_id"]
            or not evidence or any(version not in refs for version in evidence)
            or request.get("generator_operation_name") not in {"chapter_group_plan.generate", "chapter_plan.generate"}):
        return False
    uow.cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_asset_version v
        JOIN authority_asset a USING(asset_id)
        JOIN authority_operation_output_asset output USING(asset_version_id)
        JOIN authority_operation author ON author.operation_id=output.operation_id
        JOIN story_plan_binding binding ON binding.project_id=a.project_id AND binding.book_id=%s
          AND binding.asset_version_id=v.content->>'target_plan_version_id'
        LEFT JOIN active_story_plan_version active ON active.binding_id=binding.binding_id
        JOIN authority_asset_version plan_version ON plan_version.asset_version_id=binding.asset_version_id
        WHERE v.asset_version_id=ANY(%s) AND a.project_id=%s AND author.workspace_id=%s
          AND a.asset_type='replan_request' AND v.lifecycle='ACTIVE' AND v.eligibility='ELIGIBLE' AND v.governance='CLEAR'
          AND author.definition_name='planning.change_request.author' AND author.status='SUCCEEDED'
          AND author.actor_id=%s AND output.role='primary'
          AND v.content->>'contract_version'='operator-planning-change-request.v1'
          AND v.content->>'authority_boundary'='FUTURE_PLAN_PROPOSAL_ONLY'
          AND v.content->>'book_id'=%s AND v.content->>'accepted_through_chapter'=%s
          AND v.content->>'affected_scope'=binding.contract_type
          AND ((binding.freshness='CURRENT' AND active.binding_id IS NOT NULL) OR (binding.freshness='IMPACTED' AND EXISTS(
            SELECT 1 FROM authority_plan_change_proposal correction
            JOIN active_story_plan_version parent ON parent.project_id=correction.project_id
              AND parent.book_id=correction.book_id AND parent.asset_version_id=correction.proposed_asset_version_id
            JOIN authority_operation activation ON activation.operation_id=correction.activation_operation_id
            WHERE correction.proposal_id=v.content->>'upstream_plan_change_proposal_id'
              AND correction.project_id=a.project_id AND correction.book_id=binding.book_id
              AND correction.status='ACTIVE' AND correction.target_contract_type='CHAPTER_GROUP'
              AND authority_working_group_prefix_preserved(correction.project_id,correction.book_id,
                correction.proposed_asset_version_id,binding.parent_version_id,activation.actor_id,activation.workspace_id,%s)
              AND activation.status='SUCCEEDED' AND activation.actor_id=author.actor_id
              AND EXISTS(SELECT 1 FROM authority_book_manuscript_delivery delivered
                JOIN authority_book_chapter_request original USING(chapter_request_id)
                WHERE delivered.book_run_id=%s AND delivered.chapter_number=%s
                  AND original.chapter_plan_version=binding.asset_version_id
                  AND original.parent_group_version_id=binding.parent_version_id)
              AND NOT EXISTS(SELECT 1 FROM active_story_plan_version competing
                WHERE competing.project_id=binding.project_id AND competing.book_id=binding.book_id
                  AND competing.logical_key=binding.logical_key))))
          AND binding.logical_key=%s
          AND binding.execution_scope IN ('PLANNED','FROZEN')
          AND ((binding.contract_type='CHAPTER_GROUP' AND %s='chapter_group_plan.generate'
              AND %s BETWEEN (plan_version.content->'chapter_range'->>0)::integer AND (plan_version.content->'chapter_range'->>1)::integer)
            OR (binding.contract_type='CHAPTER' AND %s='chapter_plan.generate'
              AND (plan_version.content->>'chapter_number')::integer=%s))
          AND v.content_hash=%s::jsonb->>v.asset_version_id
          AND NOT EXISTS(SELECT 1 FROM authority_story_creation_cancellation cancellation
            WHERE cancellation.project_id=%s AND %s=cancellation.formation_run_id || ':production'))""",
        [book["book_id"], evidence, book["project_id"], book["workspace_id"], operation["actor_id"],
         book["book_id"], str(book["accepted_through_chapter"]), target, book["book_run_id"], target, request.get("logical_key"), request["generator_operation_name"], target,
         request["generator_operation_name"], target, dumps(refs), book["project_id"], book["stable_idempotency_key"]])
    return uow.cursor.fetchone() == (True,)


def _current_regeneration_history(uow, *, book, operation, request, target):
    from novel_forge.modules.chapter_authority.working_regeneration import ROOT_VERSION
    from novel_forge.modules.chapter_authority.working_revision import require_working_revision_frontier
    if target != writing_frontier(book):
        return False
    uow.cursor.execute("""SELECT to_jsonb(root) FROM authority_operation child
        JOIN authority_operation root ON root.operation_id=child.root_operation_id
        WHERE child.operation_id=%s AND child.project_id=%s AND child.workspace_id=%s
          AND root.project_id=child.project_id AND root.workspace_id=child.workspace_id
          AND root.actor_id=child.actor_id""", [operation['operation_id'], operation['project_id'], operation['workspace_id']])
    row = uow.cursor.fetchone()
    root = row[0] if row else {}
    if (root.get("definition_version") != ROOT_VERSION or root.get("actor_id") != operation.get("actor_id")
            or root.get("command_payload", {}).get("preparation_report") != request.get("preparation_report")):
        return False
    require_working_revision_frontier(uow, root=root, book_run_id=book["book_run_id"])
    return True


def historical_working_inputs(uow: Any, operation: dict[str, Any]) -> tuple[str, frozenset[str]]:
    name = operation["definition_name"]
    payload = operation["command_payload"]
    if name == "story_planning.generate":
        request = payload.get("payload") or {}
        working = (request.get("arc_working_set") or {}).get("working_manuscript")
    elif name in {"chapter.execution_intent.prepare", "chapter.memo.generate", "chapter.context.retrieve", "chapter.context.build", "chapter.draft.generate"}:
        request = payload
        working = (request.get("preparation_report") or {}).get("working_manuscript")
    else:
        return "", frozenset()
    if not working:
        return "", frozenset()
    refs = {item["asset_version_id"]: item["content_hash"] for item in operation["input_asset_snapshot"]}
    direct_sources = [item for item in working["sources"] if item["asset_version_id"] in refs]
    if not direct_sources:
        return "", frozenset()
    uow.cursor.execute("""SELECT to_jsonb(b) FROM authority_book_production b
        WHERE b.book_run_id=%s AND b.project_id=%s AND b.workspace_id=%s AND b.book_id=%s""",
        [working["book_run_id"], operation["project_id"], operation["workspace_id"], request.get("book_id")])
    row = uow.cursor.fetchone()
    if not row or effective_workflow(uow.cursor, row[0]) != AUTHOR_WORKFLOW:
        raise KernelError("MANUSCRIPT_CONTEXT_INVALID", "Historical working inputs require the exact author-first Book")
    book = {**row[0], "author_workflow": AUTHOR_WORKFLOW}
    target = working["target_chapter"]
    regeneration = _current_regeneration_history(uow, book=book, operation=operation, request=request, target=target) if name.startswith("chapter.") else False
    if (type(target) is not int or target != writing_frontier(book) + 1
            and not _current_planning_correction(uow, book=book, operation=operation, request=request, refs=refs, target=target)
            and not regeneration
            or any(not isinstance(source.get("chapter"), int) or not 0 < source["chapter"] < target for source in working["sources"])):
        raise KernelError("MANUSCRIPT_CONTEXT_INVALID", "Only the selected preceding writing history can be read")
    if name.startswith("chapter.") and not regeneration:
        uow.cursor.execute("""SELECT r.command_payload->'preparation_report'->'working_manuscript'
            FROM authority_book_chapter_request r JOIN authority_operation o
              ON o.root_operation_id=r.chapter_root_operation_id
            WHERE o.operation_id=%s AND r.book_run_id=%s AND r.chapter_number=%s""",
            [operation["operation_id"], book["book_run_id"], target])
        reserved = uow.cursor.fetchone()
        if not reserved or reserved[0] != working:
            raise KernelError("AUTHOR_WORKFLOW_NOT_OWNED", "Historical sources require their exact Book reservation")
    verify_working_context(uow, book, working)
    if any(refs[item["asset_version_id"]] != item["content_hash"] for item in direct_sources):
        raise KernelError("MANUSCRIPT_INPUT_SNAPSHOT_MISSING", "Historical sources require exact frozen input hashes")
    return book["book_id"], frozenset(item["asset_version_id"] for item in direct_sources)


def require_historical_input_scope_repair(cursor: Any, source: dict[str, Any], policy: dict[str, Any], target_version: str) -> bool:
    if policy.get("contract_version") != "chapter-historical-input-scope-repair.v1":
        return False
    if policy.get('input_scope_projection') == 'current-working-root-owner.v1':
        _require_current_regeneration_scope_repair(cursor, source, policy, target_version)
        return True
    working = (source["command_payload"].get("preparation_report") or {}).get("working_manuscript")
    refs = {item["asset_version_id"] for item in source["input_asset_snapshot"]}
    if (source["definition_name"] != "chapter.memo.generate" or source["definition_version"] != "3.10.0"
            or target_version != "3.10.0" or not working
            or any(item["asset_version_id"] in refs for item in working["sources"])
            or policy.get("input_snapshot") != source["input_asset_snapshot"]):
        raise KernelError("HISTORICAL_INPUT_SCOPE_REPAIR_INVALID", "Only the exact indirect Memo input shape can continue")
    cursor.execute("""SELECT result->>'error_code',result->>'error_message' FROM authority_attempt
        WHERE operation_id=%s ORDER BY attempt_number""", [source["operation_id"]])
    if cursor.fetchall() != [("MANUSCRIPT_INPUT_SNAPSHOT_MISSING", "MANUSCRIPT_INPUT_SNAPSHOT_MISSING: Historical sources require exact frozen input hashes")]:
        raise KernelError("HISTORICAL_INPUT_SCOPE_REPAIR_INVALID", "Retain the exact preflight interpreter failure")
    cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s),
        EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=%s),
        EXISTS(SELECT 1 FROM authority_operation_output_asset WHERE operation_id=%s),
        EXISTS(SELECT 1 FROM authority_saga_step_successor WHERE successor_operation_id=%s)""", [source["operation_id"]] * 4)
    if any(cursor.fetchone()):
        raise KernelError("HISTORICAL_INPUT_SCOPE_REPAIR_INVALID", "Preserve dispatched, produced and previously repaired work")
    cursor.execute("""SELECT d.deployment_id FROM authority_capability_pack_activation a
        JOIN authority_capability_pack_deployment d ON d.deployment_id=a.active_deployment_id
        JOIN authority_capability_pack_compilation c USING(compilation_id)
        WHERE a.project_id=%s AND a.workspace_id=%s AND a.book_id=%s
          AND a.workflow_definition_ref='chapter_authority_slice@3.10.0'
          AND d.deployment_id=%s AND d.deployment_status='ACTIVE' AND c.release_sha=%s""",
        [source["project_id"], source["workspace_id"], source["command_payload"]["book_id"],
         policy.get("target_deployment_id"), policy.get("release_sha")])
    if cursor.fetchone() != (policy.get("target_deployment_id"),):
        raise KernelError("HISTORICAL_INPUT_SCOPE_REPAIR_INVALID", "Require the exact same-Book deployed correction")
    return True


def deliver_manuscript(authority: Any, request_id: str, *, principal: Any) -> dict[str, Any]:
    request = authority.require_chapter_request(request_id)
    book = authority.require(request["book_run_id"])
    principal.require("book.authority.execute", book["project_id"])
    if not author_first(book):
        raise KernelError("MANUSCRIPT_WORKFLOW_REQUIRED", "Delivery requires a frozen author-first production profile")

    def commit(uow, operation_id, checkpoint):
        uow.cursor.execute("SELECT book_id FROM authority_book WHERE book_id=%s FOR UPDATE", [book["book_id"]])
        uow.cursor.execute("SELECT current_chapter,active_chapter_request_id,state FROM authority_book_production WHERE book_run_id=%s FOR UPDATE", [book["book_run_id"]])
        current, active, state = uow.cursor.fetchone()
        if active != request_id or current != request["chapter_number"] - 1 or state in {"PAUSED", "ABORTED", "COMPLETED"}:
            raise KernelError("MANUSCRIPT_DELIVERY_CONFLICT", "Delivery cannot overwrite a changed Book cursor or pause")
        uow.cursor.execute("""SELECT output.asset_version_id,root.definition_version,op.status
            FROM authority_operation_output_asset output JOIN authority_operation op USING(operation_id)
            JOIN authority_operation root ON root.operation_id=op.root_operation_id
            WHERE root.operation_id=%s AND op.definition_name='chapter.draft.generate'
              AND output.output_key='chapter.draft' AND output.role='primary'""", [request["chapter_root_operation_id"]])
        rows = uow.cursor.fetchall()
        if len(rows) != 1 or rows[0][1:] != (AUTHOR_ROOT_VERSION, "SUCCEEDED"):
            raise KernelError("MANUSCRIPT_GENERATION_NOT_COMPLETE", "Delivery requires the successful native draft operation")
        source = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=rows[0][0])
        validate_complete_prose(source.content)
        snapshot = request["command_payload"]["preparation_report"]["working_manuscript"]
        verify_working_context(uow, book, snapshot)
        from psycopg.types.json import Jsonb
        uow.cursor.execute("""INSERT INTO authority_book_manuscript_delivery
            (book_run_id,chapter_request_id,chapter_number,source_asset_version_id,source_content_hash,context_snapshot,created_by_operation_id)
            VALUES(%s,%s,%s,%s,%s,%s,%s)""",
            [book["book_run_id"], request_id, request["chapter_number"], source.asset_version_id, source.content_hash, Jsonb(snapshot), operation_id])
        uow.cursor.execute("""UPDATE authority_child_delegation SET status='SUCCEEDED',delivered_by_operation_id=%s,
            version=version+1,updated_at=NOW() WHERE chapter_request_id=%s AND delivered_by_operation_id IS NULL""", [operation_id, request_id])
        uow.cursor.execute("UPDATE authority_book_chapter_request SET status_reference='SUCCEEDED',updated_at=NOW() WHERE chapter_request_id=%s", [request_id])
        uow.cursor.execute("""UPDATE authority_book_production SET current_chapter=%s,state='READY',
            active_chapter_request_id=NULL,active_child_delegation_id=NULL,active_chapter_number=NULL,active_plan_version_id=NULL,
            version=version+1,updated_at=NOW() WHERE book_run_id=%s""", [request["chapter_number"], book["book_run_id"]])
        checkpoint("after_manuscript_delivery")
        return {"book_run_id": book["book_run_id"], "chapter": request["chapter_number"],
            "source_asset_version_id": source.asset_version_id, "source_content_hash": source.content_hash,
            "manuscript_status": "SAVED", "review_status": "NOT_RUN", "quality_status": "NOT_VERIFIED",
            "requirements_status": "NOT_EVALUATED", "acceptance": "NOT_GRANTED"}

    return authority._execute_mutation(book=book, action="manuscript_deliver", event_type="book.manuscript.delivered",
        idempotency_key=request["stable_idempotency_key"] + ":manuscript-delivery", actor_id=principal.principal_id,
        trace_id=book["root_operation_id"] + ":manuscript", correlation_id=book["root_operation_id"],
        causation_id=request["chapter_root_operation_id"], payload={"chapter_request_id": request_id}, handler=commit)



def _review_status(uow: Any, book: dict[str, Any], source: Any) -> dict[str, Any]:
    selected_review = source_draft_content(source).get("selected_review")
    if isinstance(selected_review, dict) and selected_review.get("selection_review_source_asset_version_id"):
        from novel_forge.modules.review.diagnostics import open_diagnoses
        return {"review_status": "COMPLETED", "review_asset_version_id": selected_review["selection_review_source_asset_version_id"],
            "unresolved_issue_codes": [item["code"] for item in open_diagnoses(selected_review) if item.get("status", "OPEN") == "OPEN"]}
    from psycopg.types.json import Jsonb
    uow.cursor.execute("""SELECT to_jsonb(run) FROM authority_book_prose_review_run run
        WHERE run.project_id=%s AND run.book_run_id=%s AND run.manifest->'sources' @> %s
        ORDER BY run.created_at DESC LIMIT 1""", [book["project_id"], book["book_run_id"], Jsonb([{"asset_version_id": source.asset_version_id}])])
    row = uow.cursor.fetchone()
    if row is None:
        return {"review_status": "NOT_RUN"}
    from novel_forge.modules.book_followup_authority.prose_coordinator import review_progress
    progress = review_progress(uow, row[0])
    status = "COMPLETED" if progress["review_complete"] else "PAUSED" if progress["paused"] else "FAILED" if any(item["status"] in {"FAILED_FINAL", "CANCELLED", "FAILED_RETRYABLE"} for item in progress["operations"]) else "IN_PROGRESS" if progress["operations"] else "REQUESTED"
    return {"review_status": status if progress["source_current"] else "STALE", "review_run_id": row[0]["run_id"]}


def current_manuscript(database_url: str, *, book: dict[str, Any], principal: Any,
                       version_ids: list[str] | None = None, chapters: list[int] | None = None) -> dict[str, Any]:
    principal.require("book.authority.query", book["project_id"])
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT book_id FROM authority_book WHERE book_id=%s FOR SHARE", [book["book_id"]])
        uow.cursor.execute("SELECT to_jsonb(b) FROM authority_book_production b WHERE book_run_id=%s", [book["book_run_id"]])
        book = uow.cursor.fetchone()[0]
        uow.cursor.execute("SELECT content FROM authority_asset_version WHERE asset_version_id=%s", [book["production_profile_version"]])
        requirements = uow.cursor.fetchone()[0]
        from .creation_window import delivery_window_evidence
        window = delivery_window_evidence(uow.cursor, book)
        deliveries, changes = working_dependency_changes(uow, book)
        available = [number for number, _ in deliveries]
        if chapters is not None and (not chapters or chapters != sorted(set(chapters)) or any(number not in available for number in chapters)):
            raise KernelError("MANUSCRIPT_RANGE_INVALID", "Choose an ordered, available chapter range")
        units, review_sources = [], []
        for number, dependencies in deliveries:
            if chapters is not None and number not in chapters:
                continue
            source, resolution = resolve_working_source(uow, book, number)
            content = source_draft_content(source)
            from novel_forge.modules.revision.domain import han_characters
            actual_length = han_characters(content["text"])
            length = requirements.get("chapter_length")
            length_status = "NOT_EVALUATED" if not length else "PARTIALLY_CHECKED" if length["minimum"] <= actual_length <= length["maximum"] else "LENGTH_TARGET_UNMET"
            impacted = changes[number]
            author_selection = "GENERATED_CURRENT"
            if source.asset_type == "author_edit_candidate":
                uow.cursor.execute("SELECT EXISTS(SELECT 1 FROM authority_asset_version v JOIN authority_asset a USING(asset_id) WHERE a.project_id=%s AND a.asset_type='author_edit_decision' AND v.content->>'candidate_asset_version_id'=%s AND v.content->>'decision'='ACCEPT')", [book["project_id"], source.asset_version_id])
                author_selection = "ADOPTED" if uow.cursor.fetchone()[0] else "WORKING_SELECTED"
            selection = _optional_document(uow, book["project_id"], _working_selection_ref(book, number))
            working_selection = {"status": "NOT_SELECTED"}
            if selection and any(row["asset_version_id"] == selection.asset_version_id for row in resolution["overrides"]):
                working_selection = {"status": "SELECTED", "asset_version_id": selection.asset_version_id,
                    "content_hash": selection.content_hash,
                    **{key: selection.content[key] for key in ("selected_asset_version_id", "selected_content_hash", "authority", "author_selection", "formal_acceptance")}}
                if author_selection == "GENERATED_CURRENT":
                    author_selection = "NOT_GRANTED"
            units.append({"chapter": number, "asset_version_id": source.asset_version_id,
                "content_hash": source.content_hash, "text_hash": text_hash(content["text"]),
                "title": content.get("title", ""), "text": content["text"],
                "manuscript_status": "SAVED", "quality_status": "NOT_VERIFIED", "working_selection": working_selection,
                "requirements_status": length_status, "voice_observations": content.get("voice_evidence", []), "length": {"unit": "HAN_CHARACTERS_V1", "actual": actual_length, "target": length}, "dependency_changes": impacted,
                "author_selection": author_selection})
            review_sources.append(source)
            if source.asset_type == "retained_working_prose":
                units[-1].update(manuscript_status="RETAINED_WORKING_ONLY", author_selection="NOT_AUTHOR_ACCEPTED",
                    origin_execution=content["retained_working_provenance"])
        if version_ids is not None and version_ids != [item["asset_version_id"] for item in units]:
            raise KernelError("MANUSCRIPT_EXPORT_VERSION_CONFLICT", "Export must match the exact selected version list; reload after a concurrent author change")
    for unit, source in zip(units, review_sources):
        try:
            with AuthorityUnitOfWork(database_url) as review_uow:
                unit.update(_review_status(review_uow, book, source))
        except Exception as error:
            unit.update(review_status="UNAVAILABLE", review_error_code=getattr(error, "code", None) or getattr(error, "sqlstate", None) or type(error).__name__)
    manifest = {"version": "current-manuscript-export.v1", "book_run_id": book["book_run_id"],
        "project_id": book["project_id"], "workspace_id": book["workspace_id"], "book_id": book["book_id"], "accepted_through_chapter": book["accepted_through_chapter"],
        "units": units, "kind": "CURRENT_AUTHOR_MANUSCRIPT", "publication": "NOT_AUTHORIZED",
        "writing_state": book["state"], "book_version": book["version"], "target_chapters": book["target_chapter_count"],
        "delivery_window_policy": window}
    manifest["manifest_digest"] = canonical_hash(manifest)
    manifest["text"] = "\n\n".join(f"第{item['chapter']}章 {item['title']}\n\n{item['text']}" for item in units)
    manifest["text_digest"] = "sha256:" + sha256(manifest["text"].encode()).hexdigest()
    return deepcopy(manifest)


def require_manuscript(database_url: str, *, project_id: str, book_run_id: str, principal: Any,
                       version_ids: list[str] | None = None, chapters: list[int] | None = None) -> dict[str, Any]:
    principal.require("book.authority.query", project_id)
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT to_jsonb(b) FROM authority_book_production b WHERE book_run_id=%s AND project_id=%s", [book_run_id, project_id])
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("MANUSCRIPT_BOOK_NOT_FOUND", "The work is outside the exact Project scope")
        book = row[0]
    return current_manuscript(database_url, book=book, principal=principal, version_ids=version_ids, chapters=chapters)


def authorize_working_request(database_url: str, request: Any) -> None:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("""SELECT to_jsonb(b),v.content,r.command_payload
            FROM authority_book_chapter_request r JOIN authority_book_production b USING(book_run_id)
            JOIN authority_asset_version v ON v.asset_version_id=b.production_profile_version
            WHERE r.project_id=%s AND r.stable_idempotency_key=%s AND b.book_id=%s AND b.workspace_id=%s""",
            [request.project_id, request.idempotency_key, request.book_id, request.workspace_id])
        row = uow.cursor.fetchone()
        if not row or effective_workflow(uow.cursor, row[0]) != AUTHOR_WORKFLOW:
            raise KernelError("AUTHOR_WORKFLOW_NOT_OWNED", "Author-first execution requires the exact native Book reservation")
        book = {**row[0], "author_workflow": AUTHOR_WORKFLOW}
        working = (request.preparation_report or {}).get("working_manuscript")
        if row[2].get("preparation_report", {}).get("working_manuscript") != working:
            raise KernelError("AUTHOR_WORKFLOW_NOT_OWNED", "Working sources differ from the Book-owned frozen request")
        verify_working_context(uow, book, working)


def verify_working_handler(request: Any, snapshot: dict[str, Any]) -> None:
    with AuthorityUnitOfWork(request.database_url) as uow:
        uow.cursor.execute("SELECT to_jsonb(b) FROM authority_book_production b WHERE book_run_id=%s AND project_id=%s AND book_id=%s",
            [snapshot["book_run_id"], request.project_id, snapshot["book_id"]])
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("MANUSCRIPT_CONTEXT_INVALID", "Working sources belong to another Book")
        verify_working_context(uow, row[0], snapshot)
        refs = {item.asset_version_id: item.content_hash for item in request.inputs}
        if any(refs.get(item["asset_version_id"]) != item["content_hash"] for item in snapshot["sources"]):
            raise KernelError("MANUSCRIPT_INPUT_SNAPSHOT_MISSING", "Every working source must enter the native input snapshot")


def require_current_editor_base(uow: Any, scope: dict[str, Any], version_id: str) -> None:
    uow.cursor.execute("""SELECT to_jsonb(b) FROM authority_book_production b
        JOIN authority_book_manuscript_delivery d USING(book_run_id)
        WHERE b.project_id=%s AND b.workspace_id=%s AND b.book_id=%s AND d.chapter_number=%s
        ORDER BY d.created_at DESC LIMIT 1""", [scope["project_id"], scope["workspace_id"], scope["book_id"], scope["chapter"]])
    row = uow.cursor.fetchone()
    if row and selected_source(uow, row[0], scope["chapter"]).asset_version_id != version_id:
        raise KernelError("AUTHOR_BASE_STALE", "The current author manuscript changed; keep unsaved input and rebase on its exact selected version")


def require_retained_model_candidate(database_url, *, project_id, book_run_id, asset_version_id, principal):
    principal.require("book.authority.query", project_id)
    with AuthorityUnitOfWork(database_url) as uow:
        source = uow.repositories.asset_documents.require(project_id=project_id, asset_version_id=asset_version_id)
        payload = source.content.get("payload") or {}
        typed = source.asset_type in {"draft_chapter", "draft_version", "best_draft_candidate"}
        definition, output_key = {"draft_chapter": ("chapter.draft.generate", "chapter.draft"),
            "draft_version": ("chapter.revision.apply", "chapter.revision"),
            "best_draft_candidate": ("chapter.candidate.select_best", "chapter.best_candidate")}.get(source.asset_type, (None, None))
        uow.cursor.execute("""SELECT book.book_id,book.workspace_id,request.chapter_number
            FROM authority_book_production book JOIN authority_book_chapter_request request USING(book_run_id)
            JOIN authority_operation op ON op.root_operation_id=request.chapter_root_operation_id
            JOIN authority_operation_output_asset output USING(operation_id)
            WHERE book.book_run_id=%s AND book.project_id=%s AND op.project_id=book.project_id
              AND op.workspace_id=book.workspace_id AND output.asset_version_id=%s
              AND (%s IS TRUE OR op.operation_id=%s)
              AND (%s IS FALSE OR (op.status='SUCCEEDED' AND output.role='primary'
                AND op.definition_name=%s AND output.output_key=%s))""",
            [book_run_id, project_id, asset_version_id, typed, payload.get("operation_id"), typed, definition, output_key])
        row = uow.cursor.fetchone()
        if row is None:
            from novel_forge.modules.chapter_authority.working_revision import ROOT_VERSIONS, CONTRACT
            uow.cursor.execute("""SELECT book.book_id,book.workspace_id,(root.command_payload->>'chapter')::integer
                FROM authority_book_production book
                JOIN authority_operation root ON root.command_payload#>>'{preparation_report,working_revision,book_run_id}'=book.book_run_id
                JOIN authority_operation op ON op.root_operation_id=root.operation_id
                JOIN authority_operation_output_asset output ON output.operation_id=op.operation_id
                WHERE book.book_run_id=%s AND book.project_id=%s AND root.project_id=book.project_id
                  AND root.workspace_id=book.workspace_id AND root.command_payload->>'book_id'=book.book_id
                  AND root.definition_name='chapter.slice.run' AND root.definition_version=ANY(%s)
                  AND root.command_payload#>>'{preparation_report,working_revision,contract_version}'=%s
                  AND op.project_id=book.project_id AND op.workspace_id=book.workspace_id
                  AND output.asset_version_id=%s AND (%s IS TRUE OR op.operation_id=%s)
                  AND (%s IS FALSE OR (op.status='SUCCEEDED' AND output.role='primary'
                    AND op.definition_name=%s AND output.output_key=%s))""",
                [book_run_id, project_id, list(ROOT_VERSIONS), CONTRACT, asset_version_id,
                 typed, payload.get("operation_id"), typed, definition, output_key])
            row = uow.cursor.fetchone()
        if typed:
            if (row is None or source.content.get("chapter") != row[2]
                    or any(field in source.content and source.content[field] != expected
                        for field, expected in (("project_id", project_id), ("workspace_id", row[1]), ("book_id", row[0])))):
                raise KernelError("MANUSCRIPT_CANDIDATE_SCOPE_INVALID", "Retained output belongs to another source or Book")
            if canonical_hash(source.content) != source.content_hash:
                raise KernelError("MANUSCRIPT_CANDIDATE_HASH_INVALID", "Retained typed source bytes changed")
            validate_complete_prose(source.content)
            return {"version": "retained-manuscript-candidate.v1", "kind": "RETAINED_TYPED_CANDIDATE",
                "project_id": project_id, "book_id": row[0], "workspace_id": row[1], "book_run_id": book_run_id,
                "chapter": row[2], "asset_version_id": source.asset_version_id, "content_hash": source.content_hash,
                "text": source.content["text"], "raw_text": None, "completeness": "COMPLETE",
                "structural_status": "VALIDATED_DOMAIN_RESULT", "review_status": "NOT_PROJECTED",
                "repair_scope_status": (source.content.get("prose_scope_proposal") or {}).get("qualification_status", "NOT_PROJECTED"),
                "selection_status": "NOT_PROJECTED", "acceptance_status": "NOT_PROJECTED",
                "accounting_status": "NOT_PROJECTED", "publication": "NOT_AUTHORIZED"}
        if (row is None or source.asset_type != "execution_evidence"
                or source.content.get("kind") not in {"model-result", "prose-candidate"}
                or payload.get("project_id") != project_id or payload.get("book_id") != row[0]):
            raise KernelError("MANUSCRIPT_CANDIDATE_SCOPE_INVALID", "Retained output belongs to another source or Book")
        if canonical_hash(payload).split(":", 1)[1] != source.content.get("payload_hash"):
            raise KernelError("MANUSCRIPT_CANDIDATE_HASH_INVALID", "Retained source bytes changed")
        uow.cursor.execute("SELECT status FROM authority_operation WHERE operation_id=%s", [payload["operation_id"]])
        source_operation_status = uow.cursor.fetchone()[0]
        effect = None
        if payload.get("external_effect_id"):
            uow.cursor.execute("SELECT status FROM authority_external_effect WHERE external_effect_id=%s AND operation_id=%s", [payload["external_effect_id"], payload["operation_id"]])
            effect = uow.cursor.fetchone()
        uow.cursor.execute("SELECT result->>'error_code' FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number", [payload["operation_id"]])
        failures = uow.cursor.fetchall()
        return {"version": "retained-manuscript-candidate.v1", "kind": "RETAINED_MODEL_CANDIDATE",
            "project_id": project_id, "book_id": row[0], "workspace_id": row[1], "book_run_id": book_run_id,
            "chapter": row[2], "asset_version_id": source.asset_version_id, "content_hash": source.content_hash,
            "text": payload.get("text"), "raw_text": payload["raw_text"],
            **{key: payload[key] for key in ("completeness", "structural_status", "review_status",
                "selection_status", "acceptance_status", "accounting_status")},
            "source_operation_id": payload["operation_id"], "source_operation_status": source_operation_status,
            "source_external_effect_id": payload.get("external_effect_id", ""), "source_effect_status": effect[0] if effect else "UNKNOWN",
            "source_failure_codes": [item[0] for item in failures if item[0]],
            "publication": "NOT_AUTHORIZED"}


def _require_current_regeneration_scope_repair(cursor, source, policy, target_version):
    from types import SimpleNamespace
    from novel_forge.storage.authority_repositories import AuthorityRepositories

    if (source['definition_name'] != 'chapter.execution_intent.prepare' or source['definition_version'] != '3.10.0'
            or target_version != '3.10.0' or source['status'] != 'FAILED_FINAL'
            or not policy.get('release_sha') or policy['release_sha'] == source['definition_snapshot'].get('commit_sha')
            or policy.get('input_snapshot') != source['input_asset_snapshot']):
        raise KernelError('HISTORICAL_INPUT_SCOPE_REPAIR_INVALID', 'Retain the exact unsent current working Intent failure')
    cursor.execute('SELECT status,result FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number', [source['operation_id']])
    attempts = cursor.fetchall()
    if (len(attempts) != 1 or attempts[0][0] != 'FAILED_FINAL'
            or attempts[0][1].get('error_code') != 'MANUSCRIPT_CONTEXT_INVALID'
            or attempts[0][1].get('error_message') != 'MANUSCRIPT_CONTEXT_INVALID: Only the selected preceding writing history can be read'):
        raise KernelError('HISTORICAL_INPUT_SCOPE_REPAIR_INVALID', 'Retain the one original owner-projection failure')
    cursor.execute('''SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s),
        EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=%s),
        EXISTS(SELECT 1 FROM authority_operation_output_asset WHERE operation_id=%s),
        EXISTS(SELECT 1 FROM authority_attempt_capability_pack_snapshot WHERE operation_id=%s),
        EXISTS(SELECT 1 FROM authority_saga_step_successor WHERE successor_operation_id=%s),
        EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt attempt USING(attempt_id)
          WHERE attempt.operation_id=%s AND lease.status='HELD')''', [source['operation_id']] * 6)
    if any(cursor.fetchone()):
        raise KernelError('HISTORICAL_INPUT_SCOPE_REPAIR_INVALID', 'Preserve prepared, dispatched, leased or previously succeeded work')
    uow = SimpleNamespace(cursor=cursor, repositories=AuthorityRepositories(cursor))
    book_id, history = historical_working_inputs(uow, source)
    if book_id != source['command_payload']['book_id'] or not history:
        raise KernelError('HISTORICAL_INPUT_SCOPE_REPAIR_INVALID', 'The repaired native owner and all original historical source hashes must pass')
    cursor.execute('''SELECT d.deployment_id FROM authority_capability_pack_activation activation
        JOIN authority_capability_pack_deployment d ON d.deployment_id=activation.active_deployment_id
        JOIN authority_capability_pack_compilation compilation USING(compilation_id)
        WHERE activation.project_id=%s AND activation.workspace_id=%s AND activation.book_id=%s
          AND activation.workflow_definition_ref='chapter_authority_slice@3.10.0'
          AND d.deployment_id=%s AND d.deployment_status='ACTIVE' AND compilation.release_sha=%s''',
        [source['project_id'], source['workspace_id'], book_id, policy.get('target_deployment_id'), policy['release_sha']])
    if cursor.fetchone() != (policy.get('target_deployment_id'),):
        raise KernelError('HISTORICAL_INPUT_SCOPE_REPAIR_INVALID', 'Require the exact current deployed owner projection correction')
