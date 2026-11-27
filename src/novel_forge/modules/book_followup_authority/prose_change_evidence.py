from __future__ import annotations
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from .prose_budget import frozen_prose_budget_scope
from .prose_coordinator import load_accepted_sources, load_review_sources
from .prose_review import freeze_manifest, validate_window_report, review_sources_current


def require_prose_planning_evidence(database_url, *, command, asset_version_id, commit_sha):
    failure = KernelError("PLANNING_PROSE_EVIDENCE_INVALID", "Planning requires a current exact Book report from its native successful review and compiled release")
    if command.execution_contract_version not in {"1.16.0", "1.17.0", "1.18.0", "1.19.0", "1.21.0"}:
        raise failure
    with AuthorityUnitOfWork(database_url) as uow:
        document = uow.repositories.asset_documents.require(project_id=command.project_id, asset_version_id=asset_version_id)
        uow.cursor.execute("""SELECT op.operation_id,op.definition_name,op.definition_version,op.command_payload,effect.request_payload,
            run.book_run_id,run.manifest,run.exact_release_sha
            FROM authority_operation_output_asset output JOIN authority_operation op USING(operation_id)
            JOIN authority_external_effect effect USING(operation_id)
            JOIN authority_book_prose_review_event event ON event.content->>'operation_id'=op.operation_id AND event.kind='WINDOW_ADMITTED'
            JOIN authority_book_prose_review_run run USING(run_id)
            JOIN authority_book_production book ON book.book_run_id=run.book_run_id
            WHERE output.asset_version_id=%s AND output.output_key='longform.prose_review.report'
            AND op.project_id=%s AND op.workspace_id=%s AND op.definition_name='longform.prose_review' AND op.status='SUCCEEDED'
            AND effect.status='SUCCEEDED' AND effect.effect_type='model.invoke' AND book.book_id=%s
            AND EXISTS(SELECT 1 FROM authority_external_effect_dispatch dispatch JOIN authority_external_receipt receipt USING(dispatch_id)
                WHERE dispatch.external_effect_id=effect.external_effect_id AND dispatch.status='SUCCEEDED')""",
            [asset_version_id, command.project_id, command.workspace_id, command.book_id])
        rows = uow.cursor.fetchall()
        if not rows:
            uow.cursor.execute("""SELECT to_jsonb(event),to_jsonb(run),book.book_id FROM authority_book_prose_review_event event
                JOIN authority_book_prose_review_run run USING(run_id) JOIN authority_book_production book USING(book_run_id)
                WHERE event.kind='WINDOW_REVALIDATED' AND event.content->>'report_asset_version_id'=%s
                  AND run.project_id=%s AND run.workspace_id=%s AND run.exact_release_sha=%s""",
                [asset_version_id,command.project_id,command.workspace_id,commit_sha])
            corrected = uow.cursor.fetchall()
            if len(corrected) != 1 or corrected[0][2] != command.book_id:
                raise failure
            event,run,_ = corrected[0]
            from .prose_citation_evidence import require_revalidated_report
            if require_revalidated_report(uow,run=run,event=event) != document.content:
                raise failure
            bound_run = (command.edition_execution or {}).get('book_run_id') or (command.world_preparation_request or {}).get('book_run_id')
            working = run['manifest']['schema_version'] == 'longform-prose-manifest.v3'
            if (bound_run and bound_run != run['book_run_id']) or (not bound_run and not working):
                raise failure
            current = freeze_manifest(project_id=command.project_id,workspace_id=command.workspace_id,book_run_id=run['book_run_id'],
                sources=load_review_sources(uow,run['book_run_id'],command.project_id),policy=run['manifest']['policy'],
                work_intent=run['manifest']['schema_version'] in {'longform-prose-manifest.v2','longform-prose-manifest.v3'})
            if not review_sources_current(run['manifest']['sources'],current['sources'],run['manifest']['policy']):
                raise KernelError('PLANNING_PROSE_EVIDENCE_STALE','Revalidated evidence still requires the exact current source prose')
            return
        if len(rows) != 1 or rows[0][7] != commit_sha or document.asset_type != "longform_prose_review_report":
            raise failure
        operation, definition, version, payload, request, run_id, manifest, _ = rows[0]
        bound_run = (command.edition_execution or {}).get("book_run_id") or (command.world_preparation_request or {}).get("book_run_id")
        working = manifest["schema_version"] == "longform-prose-manifest.v3"
        if (bound_run and bound_run != run_id) or (not bound_run and not working):
            raise KernelError("PLANNING_PROSE_EDITION_SCOPE_INVALID", "Review evidence must match the exact Book run frozen by this planning task")
        if uow.repositories.definitions.get_release(definition, version, commit_sha=commit_sha) is None:
            raise failure
        frozen_prose_budget_scope(uow.cursor, {"operation_id": operation, "command_payload": payload, "request_payload": request}, project_id=command.project_id)
        current = freeze_manifest(project_id=command.project_id, workspace_id=command.workspace_id, book_run_id=run_id,
            sources=load_review_sources(uow, run_id, command.project_id) if working else load_accepted_sources(uow, run_id, command.project_id), policy=manifest["policy"],
            work_intent=manifest["schema_version"] in {"longform-prose-manifest.v2", "longform-prose-manifest.v3"})
        if not review_sources_current(manifest["sources"], current["sources"], manifest["policy"]):
            raise KernelError("PLANNING_PROSE_EVIDENCE_STALE", "Re-review the exact current source manuscript before replacing plans")
        window = next((item for item in manifest["windows"] if item["window_id"] == document.content.get("window_id")), None)
        if window is None:
            raise failure
        validate_window_report(document.content, manifest=manifest, window=window)


def pending_future_plan_evidence(database_url, *, book, plan_version_id, policy, commit_sha):
    from .prose_coordinator import review_progress
    from novel_forge.modules.book_authority.completion import _rows
    from novel_forge.modules.book_authority.manuscript import author_first
    expected = {"version": "native-prose-plan-feedback.v1", "scope": "PLANNED_FUTURE_ONLY"}
    if policy is None:
        return ()
    if policy != expected:
        raise KernelError("BOOK_PROSE_PLAN_FEEDBACK_POLICY_INVALID", "Require the frozen future Planning feedback contract")
    if not author_first(book):
        return ()
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("""WITH RECURSIVE ancestors(version_id) AS (
            SELECT %s::text UNION SELECT edge.upstream_asset_version_id
            FROM authority_artifact_lineage_edge edge JOIN ancestors ON edge.downstream_asset_version_id=ancestors.version_id
            WHERE edge.project_id=%s AND edge.book_id=%s)
            SELECT version_id FROM ancestors""", [plan_version_id,book["project_id"],book["book_id"]])
        consumed = {row[0] for row in uow.cursor.fetchall()}
        uow.cursor.execute("""SELECT * FROM authority_book_prose_review_run
            WHERE book_run_id=%s AND project_id=%s AND workspace_id=%s AND exact_release_sha=%s
              AND manifest #>> '{policy,diagnosis_contract}'='prose-root-cause.v1'
            ORDER BY created_at DESC,run_id DESC LIMIT 1""",
            [book["book_run_id"],book["project_id"],book["workspace_id"],commit_sha])
        runs = _rows(uow.cursor)
        if not runs:
            return ()
        progress = review_progress(uow, runs[0])
        if not progress["review_complete"] or not progress["source_current"] or progress["paused"]:
            return ()
        windows = {member["window_id"] for finding in progress["findings"]
            if finding["status"] == "OPEN" and not finding.get("disposition")
            and finding.get("repair_route", {}).get("repair_scope") == "FUTURE_REPLAN"
            for member in finding["members"] if member["judgment"] == "ISSUE"
            and member.get("repair", {}).get("problem_owner") == "PLAN"}
        versions = tuple(sorted({item["report_asset_version_id"] for item in progress["operations"]
            if item["status"] == "SUCCEEDED" and item["window_id"] in windows
            and item["report_asset_version_id"] not in consumed}))
    return versions
