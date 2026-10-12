from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from typing import Any

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


def _require_workflow_checkpoint(uow: Any, book: dict[str, Any], expected_version: int) -> dict[str, Any]:
    uow.cursor.execute("SELECT book_id FROM authority_book WHERE book_id=%s FOR UPDATE", [book["book_id"]])
    uow.cursor.execute("SELECT to_jsonb(b) FROM authority_book_production b WHERE book_run_id=%s FOR UPDATE", [book["book_run_id"]])
    current = uow.cursor.fetchone()[0]
    if current["version"] != expected_version or current["active_chapter_request_id"] or current["state"] not in {"READY", "PAUSED"}:
        raise KernelError("AUTHOR_WORKFLOW_CHECKPOINT_REQUIRED", "Switch only at a settled idle Book checkpoint; active work retains its frozen policy and original effects")
    uow.cursor.execute("""SELECT 1 FROM authority_external_effect e JOIN authority_operation op USING(operation_id)
        WHERE op.project_id=%s AND (e.request_payload #>> '{_production_execution,book_id}'=%s
            OR op.root_operation_id=%s OR op.root_operation_id IN (
                SELECT chapter_root_operation_id FROM authority_book_chapter_request WHERE book_run_id=%s))
          AND NOT authority_generation_isolated(e.external_effect_id)
          AND e.status IN ('READY','DISPATCHING','DISPATCHED','UNKNOWN','FAILED_RETRYABLE','RECONCILIATION_REQUIRED','CANCELLATION_REQUESTED') LIMIT 1""",
        [book["project_id"], book["book_id"], book["root_operation_id"], book["book_run_id"]])
    if uow.cursor.fetchone():
        raise KernelError("AUTHOR_WORKFLOW_RECONCILIATION_REQUIRED", "Reconcile original unsettled effects before switching generation policy; existing manuscripts remain readable")
    from novel_forge.modules.production_execution.execution_template import BOOK_USAGE_SQL
    uow.cursor.execute("SELECT 1 FROM authority_budget_reservation r LEFT JOIN authority_external_effect e USING(external_effect_id) WHERE r.project_id=%s AND r.status='HELD_UNKNOWN' AND NOT authority_generation_isolated(e.external_effect_id) AND " + BOOK_USAGE_SQL + " LIMIT 1",
        [book["project_id"], book["book_id"], book["book_id"], book["book_id"]])
    if uow.cursor.fetchone():
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
            from pathlib import Path
            from types import SimpleNamespace
            from novel_forge.modules.authority_handler_runtime.policy_commands import configure_execution_template
            configure_execution_template(settings, SimpleNamespace(project_id=book["project_id"], workspace_id=book["workspace_id"],
                book_id=book["book_id"], policy_version=idempotency_key + ":routing", idempotency_key=idempotency_key + ":routing",
                template_file=Path(__file__).resolve().parents[4] / "config/execution_templates/author_first.json",
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
                             expected_version, idempotency_key, reason, principal):
    from novel_forge.modules.chapter_authority.author_editor import require_source
    from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
    book = authority.require(book_run_id)
    principal.require("book.authority.execute", book["project_id"])
    principal.require("chapter.authority.execute", book["project_id"])
    if not reason.strip() or type(chapter) is not int or chapter < 1:
        raise KernelError("MANUSCRIPT_WORK_SELECTION_INVALID", "Require an exact chapter and work revision reason")
    def commit(uow, operation_id, checkpoint):
        current = _require_workflow_checkpoint(uow, book, expected_version)
        if effective_workflow(uow.cursor, current) != AUTHOR_WORKFLOW or chapter <= current["accepted_through_chapter"] or chapter > current["current_chapter"]:
            raise KernelError("MANUSCRIPT_WORK_SELECTION_INVALID", "Work selection requires a delivered unaccepted chapter in this author-first run")
        source = selected_source(uow, current, chapter)
        scope = {key: current[key] for key in ("project_id", "workspace_id", "book_id")}
        scope["chapter"] = chapter
        candidate = require_source(uow, scope, candidate_asset_version_id)
        if candidate.asset_type == "author_edit_candidate":
            if candidate.content.get("base_asset_version_id") != source.asset_version_id or candidate.content.get("base_asset_hash") != source.content_hash:
                raise KernelError("MANUSCRIPT_WORK_SELECTION_STALE", "Working candidate must revise this exact current source")
            if candidate.content.get("source_provenance", {}).get("kind") != "ASSISTANT_REVISION_PROPOSAL":
                raise KernelError("MANUSCRIPT_WORK_SELECTION_INVALID", "Human author input uses its separate author choice")
        else:
            from novel_forge.modules.chapter_authority.working_revision import ROOT_VERSION, CONTRACT, require_working_revision_frontier
            uow.cursor.execute("""SELECT to_jsonb(root) FROM authority_operation_output_asset output
                JOIN authority_operation child USING(operation_id)
                JOIN authority_operation root ON root.operation_id=child.root_operation_id
                WHERE output.asset_version_id=%s AND output.role='primary' AND child.status='SUCCEEDED'
                  AND child.project_id=%s AND child.definition_name IN ('chapter.revision.apply','chapter.candidate.select_best')""",
                [candidate.asset_version_id, current["project_id"]])
            origins = uow.cursor.fetchall()
            origin = origins[0][0] if len(origins) == 1 else {}
            binding = (origin.get("command_payload", {}).get("preparation_report") or {}).get("working_revision") or {}
            if (candidate.asset_type not in {"draft_version", "best_draft_candidate"}
                    or origin.get("definition_version") != ROOT_VERSION
                    or origin.get("status") in {"CANCELLED", "CANCELLATION_REQUESTED"}
                    or binding.get("contract_version") != CONTRACT or binding.get("book_run_id") != book_run_id
                    or binding.get("source_asset_version_id") != source.asset_version_id
                    or binding.get("source_content_hash") != source.content_hash):
                raise KernelError("MANUSCRIPT_WORK_SELECTION_STALE", "Native working revision must bind this exact current source")
            require_working_revision_frontier(uow, root=origin, book_run_id=book_run_id)
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
    return authority._execute_mutation(book=book, action="working_manuscript_select", event_type="book.working_manuscript.selected",
        idempotency_key=idempotency_key, actor_id=principal.principal_id, trace_id=idempotency_key, correlation_id=book["root_operation_id"],
        causation_id=book["root_operation_id"], payload={"chapter": chapter, "candidate_asset_version_id": candidate_asset_version_id,
            "expected_version": expected_version, "reason": reason}, handler=commit,
        input_assets=authority.resolve_asset_refs(project_id=book["project_id"], asset_version_ids=(candidate_asset_version_id,)))


def selected_source(uow: Any, book: dict[str, Any], chapter: int) -> Any:
    uow.cursor.execute("""SELECT source_asset_version_id FROM authority_book_manuscript_delivery
        WHERE book_run_id=%s AND chapter_number=%s""", [book["book_run_id"], chapter])
    row = uow.cursor.fetchone()
    if row is None:
        uow.cursor.execute("""SELECT outcome.content->>'accepted_draft_asset_version_id'
            FROM authority_book_acceptance_lineage(%s) acceptance
            JOIN authority_asset_version outcome ON outcome.asset_version_id=acceptance.chapter_outcome_asset_version_id
            WHERE acceptance.chapter_number=%s AND acceptance.status='COMMITTED'""", [book["book_run_id"], chapter])
        row = uow.cursor.fetchone()
    if row is None:
        uow.cursor.execute("""SELECT output.asset_version_id FROM authority_book_chapter_request request
            JOIN authority_operation op ON op.root_operation_id=request.chapter_root_operation_id
            JOIN authority_operation_output_asset output USING(operation_id)
            WHERE request.book_run_id=%s AND request.chapter_number=%s
              AND op.definition_name='chapter.draft.generate' AND op.status='SUCCEEDED'
              AND output.output_key='chapter.draft' AND output.role='primary'
            ORDER BY request.generation DESC LIMIT 1""", [book["book_run_id"], chapter])
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("MANUSCRIPT_CHAPTER_MISSING", "No complete native manuscript exists at this chapter")
    source = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=row[0])
    working = _optional_document(uow, book["project_id"], _working_selection_ref(book, chapter))
    if working and working.content.get("native_source_asset_version_id") == source.asset_version_id:
        selected = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=working.content["selected_asset_version_id"])
        if (working.content.get("book_run_id") != book["book_run_id"] or selected.content_hash != working.content.get("selected_content_hash")):
            raise KernelError("MANUSCRIPT_WORK_SELECTION_INVALID", "Working selection must retain exact run and source hash")
        source = selected
    scope = {key: book[key] for key in ("project_id", "workspace_id", "book_id")}
    scope["chapter"] = chapter
    try:
        session = uow.repositories.asset_documents.require(project_id=book["project_id"], logical_ref=_session_ref(scope))
    except KernelError as error:
        if error.code != "AUTHORITY_ASSET_NOT_FOUND":
            raise
        session = None
    if session and session.content.get("selected_asset_version_id"):
        selected = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=session.content["selected_asset_version_id"])
        if edit_selection_matches_source(selected, source):
            source = selected
    if source.governance != "CLEAR" or source.eligibility != "ELIGIBLE":
        raise KernelError("MANUSCRIPT_SOURCE_BLOCKED", "Selected manuscript is not governed for use")
    validate_complete_prose(source_draft_content(source))
    return source


def working_dependency_changes(uow: Any, book: dict[str, Any]) -> tuple[list[Any], dict[int, list[dict[str, Any]]]]:
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
    selected = {number: selected_source(uow, book, number).asset_version_id for number, _, _ in deliveries}
    changes = {}
    for number, _, dependencies in deliveries:
        affected = {}
        for row in dependencies.get("sources", []):
            predecessor = row["chapter"]
            if selected.get(predecessor) != row["asset_version_id"]:
                affected[predecessor] = {"chapter": predecessor, "source_asset_version_id": row["asset_version_id"],
                    "current_asset_version_id": selected.get(predecessor)}
            for inherited in changes.get(predecessor, []):
                affected.setdefault(inherited["chapter"], {**inherited, "via_chapter": predecessor})
        changes[number] = list(affected.values())
    return [(number, dependencies) for number, _, dependencies in deliveries], changes


def freeze_working_context(uow: Any, book: dict[str, Any], chapter: int, *,
                           projection_policy: Any = "FROM_PROFILE") -> dict[str, Any]:
    from .working_prose import CONTEXT_VERSION, LEGACY_GUIDANCE, project_working_sources, working_instruction, working_prose_policy

    if projection_policy == "FROM_PROFILE":
        profile_id = book.get("production_profile_version")
        profile = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=profile_id) if profile_id else None
        projection_policy = working_prose_policy(profile.content) if profile else None
    projection_policy = working_prose_policy({"working_prose_policy": projection_policy})
    _, changes = working_dependency_changes(uow, book)
    rows = []
    memory_enabled = bool(projection_policy and projection_policy["version"] == "working-prose-projection.v3")
    history = projection_policy["history_chapters"] if projection_policy else 4
    for number in range(max(1, chapter - history), chapter):
        source = selected_source(uow, book, number)
        require_prose_propagation(uow, book, source)
        text = source_draft_content(source)["text"]
        rows.append({"chapter": number, "asset_version_id": source.asset_version_id,
            "content_hash": source.content_hash, "text_hash": text_hash(text),
            **({"text": text} if projection_policy else {"excerpt": text[-2400:] if number == chapter - 1 else text[-600:]}),
            "status": "UNREVIEWED_WORKING_PROSE", "character_knowledge": "NOT_VERIFIED"})
        if memory_enabled:
            from .manuscript_memory import source_memory
            memory, provenance = source_memory(uow, book, source)
            rows[-1].update(observations=memory, memory_provenance=provenance)
        if changes.get(number):
            rows[-1]["dependency_changes"] = changes[number]
    memory_packet = None
    if memory_enabled:
        from novel_forge.modules.narrative_state.working_memory import compile_working_memory, bind_packet_coverage
        memory_packet = compile_working_memory(rows, queries=projection_policy["queries"],
                                               max_characters=projection_policy["max_characters"] // 3)
    if projection_policy:
        rows = project_working_sources(rows, target_chapter=chapter, policy=projection_policy, memory=memory_packet)
    if memory_packet is not None:
        memory_packet = bind_packet_coverage(memory_packet, rows)
    result = {"version": CONTEXT_VERSION if projection_policy else "working-manuscript-context.v1", "book_run_id": book["book_run_id"],
        "project_id": book["project_id"], "book_id": book["book_id"], "target_chapter": chapter,
        "accepted_through_chapter": int(book["accepted_through_chapter"]), "sources": rows,
        "authority": "AUTHOR_WORKING_PROSE_ONLY", "structured_facts": [],
        **({"projection_policy": projection_policy} if projection_policy else {}),
        **({"working_memory": memory_packet} if memory_packet is not None else {}),
        "instruction": working_instruction(projection_policy) if projection_policy else LEGACY_GUIDANCE["instruction"]}
    return {**result, "snapshot_hash": canonical_hash(result)}


def require_prose_propagation(uow: Any, book: dict[str, Any], source: Any) -> None:
    from novel_forge.modules.review.diagnostics import major_contradiction_codes
    content = source_draft_content(source)
    source_id = content.get("selected_source_asset_version_id") or source.asset_version_id
    embedded = content.get("selected_review")
    reviews = [(embedded.get("selection_review_source_asset_version_id"), embedded)] if isinstance(embedded, dict) else []
    uow.cursor.execute("""SELECT v.asset_version_id,v.content FROM authority_operation_output_asset output
        JOIN authority_operation operation USING(operation_id)
        JOIN authority_asset_version v USING(asset_version_id)
        JOIN authority_asset asset ON asset.asset_id=v.asset_id
        WHERE operation.project_id=%s AND operation.status='SUCCEEDED'
          AND asset.asset_type IN ('review_report','re_review_report')
          AND COALESCE(v.content->>'revision_version_id',v.content->>'target_asset_version_id')=%s
        ORDER BY operation.created_at""", [book["project_id"], source_id])
    reviews.extend(uow.cursor.fetchall())
    pending = {}
    from novel_forge.modules.review.diagnostics import prose_hash
    for review_id, review in reviews:
        if (review.get("revision_version_id") or review.get("target_asset_version_id")) != source_id or review.get("target_text_hash") != prose_hash(content["text"]):
            continue
        if review.get("report_type") == "ReReviewReport":
            prior_id = (review.get("prior_review_evidence") or {}).get("asset_version_id")
            verified = {check["code"] for check in review.get("resolution_checks", [])
                if check.get("status") == "SATISFIED" and check.get("preservation") == "PRESERVED"}
            for disposition in review.get("issue_lineage", []):
                if (disposition.get("verified_by_rereview") is True and disposition.get("to_status") == "RESOLVED"
                        and disposition.get("code") in verified):
                    pending.pop((prior_id, disposition["code"]), None)
        for code in major_contradiction_codes(review, text=content["text"], source_id=source_id):
            pending[(review_id, code)] = code
    problems = sorted(set(pending.values()))
    if problems:
        raise KernelError("MANUSCRIPT_MAJOR_CONTRADICTION_UNRESOLVED",
            "Retain this complete candidate for targeted revision; it cannot become affected later prose's automatic source",
            details={"source_asset_version_id": source.asset_version_id, "diagnosis_codes": problems})


def verify_working_context(uow: Any, book: dict[str, Any], snapshot: dict[str, Any], *, require_current: bool = True) -> None:
    from .working_prose import CONTEXT_VERSION, validate_working_projection
    enhanced = snapshot.get("projection_policy") is not None
    if enhanced:
        validate_working_projection(snapshot, project_id=book["project_id"], book_id=book["book_id"])
    plain = {key: value for key, value in snapshot.items() if key != "snapshot_hash"}
    if (snapshot.get("version") not in {"working-manuscript-context.v1", CONTEXT_VERSION}
            or snapshot.get("snapshot_hash") != canonical_hash(plain)
            or any(snapshot.get(key) != book[key] for key in ("project_id", "book_id", "book_run_id"))):
        raise KernelError("MANUSCRIPT_CONTEXT_INVALID", "Working context must bind its exact Book and immutable sources")
    if require_current:
        if enhanced and snapshot["projection_policy"]["version"] == "working-prose-projection.v3":
            _, changes = working_dependency_changes(uow, book)
            current = snapshot["accepted_through_chapter"] == int(book["accepted_through_chapter"]) and all(selected_source(uow, book, row["chapter"]).asset_version_id == row["asset_version_id"]
                          and changes.get(row["chapter"], []) == row.get("dependency_changes", []) for row in snapshot["sources"])
        else:
            current = snapshot == freeze_working_context(uow, book, snapshot["target_chapter"],
                projection_policy=snapshot.get("projection_policy") if enhanced else None)
        if not current:
            raise KernelError("MANUSCRIPT_DEPENDENCY_CHANGED", "A selected predecessor changed; retain the result and rebind only affected continuation")
    for item in snapshot["sources"]:
        source = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=item["asset_version_id"])
        if require_current:
            require_prose_propagation(uow, book, source)
        if source.content_hash != item["content_hash"] or text_hash(source_draft_content(source)["text"]) != item["text_hash"]:
            raise KernelError("MANUSCRIPT_SOURCE_HASH_INVALID", "Working manuscript source failed its exact version binding")
        if snapshot.get("working_memory"):
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
                or any(source_draft_content(source)["text"][p["start"]:p["end"]] != p["text"] for p in item["passages"])):
            raise KernelError("MANUSCRIPT_SOURCE_HASH_INVALID", "Working passage does not match its exact source range")


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
    if (not isinstance(target, int) or target != writing_frontier(book) + 1
            or any(not isinstance(source.get("chapter"), int) or not 0 < source["chapter"] < target for source in working["sources"])):
        raise KernelError("MANUSCRIPT_CONTEXT_INVALID", "Only the selected preceding writing history can be read")
    if name.startswith("chapter."):
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
        units = []
        for number, dependencies in deliveries:
            if chapters is not None and number not in chapters:
                continue
            source = selected_source(uow, book, number)
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
            units.append({"chapter": number, "asset_version_id": source.asset_version_id,
                "content_hash": source.content_hash, "text_hash": text_hash(content["text"]),
                "title": content.get("title", ""), "text": content["text"],
                "manuscript_status": "SAVED", **_review_status(uow, book, source), "quality_status": "NOT_VERIFIED",
                "requirements_status": length_status, "voice_observations": content.get("voice_evidence", []), "length": {"unit": "HAN_CHARACTERS_V1", "actual": actual_length, "target": length}, "dependency_changes": impacted,
                "author_selection": author_selection})
        if version_ids is not None and version_ids != [item["asset_version_id"] for item in units]:
            raise KernelError("MANUSCRIPT_EXPORT_VERSION_CONFLICT", "Export must match the exact selected version list; reload after a concurrent author change")
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
        uow.cursor.execute("""SELECT book.book_id,book.workspace_id,request.chapter_number
            FROM authority_book_production book JOIN authority_book_chapter_request request USING(book_run_id)
            JOIN authority_operation op ON op.root_operation_id=request.chapter_root_operation_id
            JOIN authority_operation_output_asset output USING(operation_id)
            WHERE book.book_run_id=%s AND book.project_id=%s AND op.project_id=book.project_id
              AND op.workspace_id=book.workspace_id AND output.asset_version_id=%s
              AND op.operation_id=%s""", [book_run_id, project_id, asset_version_id, payload.get("operation_id")])
        row = uow.cursor.fetchone()
        if row is None:
            from novel_forge.modules.chapter_authority.working_revision import ROOT_VERSION, CONTRACT
            uow.cursor.execute("""SELECT book.book_id,book.workspace_id,(root.command_payload->>'chapter')::integer
                FROM authority_book_production book
                JOIN authority_operation root ON root.command_payload#>>'{preparation_report,working_revision,book_run_id}'=book.book_run_id
                JOIN authority_operation op ON op.root_operation_id=root.operation_id
                JOIN authority_operation_output_asset output ON output.operation_id=op.operation_id
                WHERE book.book_run_id=%s AND book.project_id=%s AND root.project_id=book.project_id
                  AND root.workspace_id=book.workspace_id AND root.command_payload->>'book_id'=book.book_id
                  AND root.definition_name='chapter.slice.run' AND root.definition_version=%s
                  AND root.command_payload#>>'{preparation_report,working_revision,contract_version}'=%s
                  AND op.project_id=book.project_id AND op.workspace_id=book.workspace_id
                  AND output.asset_version_id=%s AND op.operation_id=%s""",
                [book_run_id, project_id, ROOT_VERSION, CONTRACT, asset_version_id, payload.get("operation_id")])
            row = uow.cursor.fetchone()
        if (row is None or source.asset_type != "execution_evidence"
                or source.content.get("kind") not in {"model-result", "prose-candidate"}
                or payload.get("project_id") != project_id or payload.get("book_id") != row[0]):
            raise KernelError("MANUSCRIPT_CANDIDATE_SCOPE_INVALID", "Retained output belongs to another source or Book")
        if canonical_hash(payload).split(":", 1)[1] != source.content.get("payload_hash"):
            raise KernelError("MANUSCRIPT_CANDIDATE_HASH_INVALID", "Retained source bytes changed")
        return {"version": "retained-manuscript-candidate.v1", "kind": "RETAINED_MODEL_CANDIDATE",
            "project_id": project_id, "book_id": row[0], "workspace_id": row[1], "book_run_id": book_run_id,
            "chapter": row[2], "asset_version_id": source.asset_version_id, "content_hash": source.content_hash,
            "text": payload.get("text"), "raw_text": payload["raw_text"],
            **{key: payload[key] for key in ("completeness", "structural_status", "review_status",
                "selection_status", "acceptance_status", "accounting_status")},
            "publication": "NOT_AUTHORIZED"}
