from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.domain import canonical_hash
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def request_memory(database_url, *, project_id, book_run_id, chapter_request_id, principal):
    principal.require("book.authority.query", project_id)
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("""SELECT to_jsonb(request),root.command_payload,root.input_asset_snapshot
            FROM authority_book_chapter_request request
            JOIN authority_operation root ON root.operation_id=request.chapter_root_operation_id
            WHERE request.project_id=%s AND request.book_run_id=%s AND request.chapter_request_id=%s""",
            [project_id, book_run_id, chapter_request_id])
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("BOOK_CHAPTER_REQUEST_NOT_FOUND", "No request belongs to this Book and Project")
        request, command, inputs = row
        snapshot = (command.get("preparation_report") or {}).get("working_manuscript")
        if snapshot is not None and snapshot.get("snapshot_hash") != canonical_hash(
                {key: value for key, value in snapshot.items() if key != "snapshot_hash"}):
            raise KernelError("MANUSCRIPT_CONTEXT_INVALID", "Stored request snapshot failed its digest")
        uow.cursor.execute("""SELECT effect.external_effect_id,effect.operation_id,effect.status,
                effect.request_payload,COALESCE((SELECT jsonb_agg(to_jsonb(receipt) ORDER BY receipt.receipt_id)
                FROM authority_external_receipt receipt JOIN authority_external_effect_dispatch dispatch USING(dispatch_id)
                WHERE dispatch.external_effect_id=effect.external_effect_id),'[]'::jsonb)
            FROM authority_external_effect effect JOIN authority_operation op USING(operation_id)
            WHERE effect.project_id=%s AND op.root_operation_id=%s
              AND effect.request_payload->>'stage'='draft'
            ORDER BY effect.created_at,effect.external_effect_id""",
            [project_id, request["chapter_root_operation_id"]])
        effects = [dict(zip(("external_effect_id", "operation_id", "status", "request", "receipts"), item, strict=True))
            for item in uow.cursor.fetchall()]
        uow.cursor.execute("""SELECT asset.asset_type,version.asset_version_id,version.content_hash,version.content
            FROM authority_operation_output_asset output JOIN authority_operation op USING(operation_id)
            JOIN authority_asset_version version USING(asset_version_id)
            JOIN authority_asset asset ON asset.asset_id=version.asset_id
            WHERE op.project_id=%s AND op.root_operation_id=%s
              AND asset.asset_type IN ('context_bundle','chapter_execution_intent','capability_materialization_manifest')
            ORDER BY version.created_at,version.asset_version_id""", [project_id, request["chapter_root_operation_id"]])
        artifacts = []
        for kind, identity, digest, content in uow.cursor.fetchall():
            if canonical_hash(content) != digest:
                raise KernelError("MANUSCRIPT_CONTEXT_INVALID", "Stored request artifact failed its digest")
            artifacts.append(dict(asset_type=kind, asset_version_id=identity, content_hash=digest, content=content))
    return {"version": "working-memory-request-readback.v1", "read_kind": "FROZEN_CHAPTER_REQUEST",
        "project_id": project_id, "book_run_id": book_run_id, "chapter_request": request,
        "working_manuscript": snapshot, "input_assets": inputs, "writer_effects": effects,
        "request_artifacts": artifacts, "dispatch_observed": bool(effects),
        "attribution_boundary": "INTENT_AND_RECEIPT_STATUS_RETAINED_NOT_PROOF_OF_MODEL_COMPREHENSION"}
