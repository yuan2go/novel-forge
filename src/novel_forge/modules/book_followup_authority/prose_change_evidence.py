from __future__ import annotations
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from .prose_budget import frozen_prose_budget_scope
from .prose_coordinator import load_accepted_sources
from .prose_review import freeze_manifest, validate_window_report


def require_prose_planning_evidence(database_url, *, command, asset_version_id, commit_sha):
    failure = KernelError("PLANNING_PROSE_EVIDENCE_INVALID", "Planning requires a current exact Book report from its native successful review and compiled release")
    if command.execution_contract_version != "1.16.0":
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
        if len(rows) != 1 or rows[0][7] != commit_sha or document.asset_type != "longform_prose_review_report":
            raise failure
        operation, definition, version, payload, request, run_id, manifest, _ = rows[0]
        bound_run = (command.edition_execution or {}).get("book_run_id") or (command.world_preparation_request or {}).get("book_run_id")
        if bound_run != run_id:
            raise KernelError("PLANNING_PROSE_EDITION_SCOPE_INVALID", "Review evidence must match the exact Book run frozen by this planning task")
        if uow.repositories.definitions.get_release(definition, version, commit_sha=commit_sha) is None:
            raise failure
        frozen_prose_budget_scope(uow.cursor, {"operation_id": operation, "command_payload": payload, "request_payload": request}, project_id=command.project_id)
        current = freeze_manifest(project_id=command.project_id, workspace_id=command.workspace_id, book_run_id=run_id,
            sources=load_accepted_sources(uow, run_id, command.project_id), policy=manifest["policy"],
            work_intent=manifest["schema_version"] == "longform-prose-manifest.v2")
        if current["sources"] != manifest["sources"]:
            raise KernelError("PLANNING_PROSE_EVIDENCE_STALE", "Re-review the current accepted manuscript before replacing future plans")
        window = next((item for item in manifest["windows"] if item["window_id"] == document.content.get("window_id")), None)
        if window is None:
            raise failure
        validate_window_report(document.content, manifest=manifest, window=window)
