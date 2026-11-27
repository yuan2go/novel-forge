
from typing import Any, Mapping


def validate_execution_window(
    value: Any, *, target_chapters: int
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"version", "stop_after_chapter"}:
        raise ValueError("CREATION_EXECUTION_WINDOW_INVALID")
    stop = value["stop_after_chapter"]
    if (
        value["version"] != "creation-execution-window.v1"
        or not isinstance(stop, int)
        or isinstance(stop, bool)
        or not 1 <= stop <= target_chapters
    ):
        raise ValueError("CREATION_EXECUTION_WINDOW_INVALID")
    return dict(value)


def execution_stop_chapter(policy: Mapping[str, Any], *, target_chapters: int) -> int:
    profile = (
        policy.get("creation_input_policy", {})
        .get("profiles", {})
        .get("production_profile", {})
        .get("content", {})
    )
    window = validate_execution_window(
        profile.get("execution_window"), target_chapters=target_chapters
    )
    return window["stop_after_chapter"] if window else target_chapters


def delivery_window_evidence(cursor: Any, book: Mapping[str, Any]) -> dict[str, Any] | None:
    from novel_forge.modules.command_kernel.errors import KernelError

    cursor.execute("""SELECT v.asset_version_id,v.content FROM authority_asset_locator l
        JOIN authority_asset_version v ON v.asset_version_id=l.current_asset_version_id
        JOIN authority_asset a ON a.asset_id=v.asset_id
        WHERE l.project_id=%s AND l.logical_ref=%s AND a.asset_type='book_delivery_window_policy'
          AND v.governance='CLEAR' AND v.eligibility='ELIGIBLE'""",
        [book["project_id"], "book-delivery-window/" + book["book_run_id"]])
    row = cursor.fetchone()
    if row is None:
        return None
    content = row[1]
    if (content.get("book_run_id") != book["book_run_id"]
            or content.get("source_profile_version") != book["production_profile_version"]
            or content.get("stop_after_chapter") != book["target_chapter_count"]):
        raise KernelError("BOOK_DELIVERY_WINDOW_DRIFT", "Delivery target must match its exact retained policy evidence")
    return {"asset_version_id": row[0], **content}


def extend_delivery_window(authority: Any, book_run_id: str, *, principal: Any,
                           expected_version: int, stop_after_chapter: int,
                           idempotency_key: str) -> dict[str, Any]:
    from novel_forge.modules.book_authority.manuscript import (
        AUTHOR_WORKFLOW, _require_workflow_checkpoint, effective_workflow,
    )
    from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
    from novel_forge.modules.command_kernel.errors import KernelError

    if (not isinstance(expected_version, int) or isinstance(expected_version, bool)
            or expected_version < 0 or not isinstance(stop_after_chapter, int)
            or isinstance(stop_after_chapter, bool) or not isinstance(idempotency_key, str)
            or not idempotency_key.strip()):
        raise ValueError("BOOK_DELIVERY_WINDOW_COMMAND_INVALID")
    book = authority.require(book_run_id)
    principal.require("book.authority.execute", book["project_id"])

    def commit(uow, operation_id, checkpoint):
        current = _require_workflow_checkpoint(uow, book, expected_version)
        if effective_workflow(uow.cursor, current) != AUTHOR_WORKFLOW:
            raise KernelError("BOOK_DELIVERY_WINDOW_AUTHOR_FIRST_REQUIRED", "Extend the delivery window of an author-first work at its original idle checkpoint")
        if current["active_child_delegation_id"]:
            raise KernelError("AUTHOR_WORKFLOW_CHECKPOINT_REQUIRED", "Settle the active child before extending delivery")
        uow.cursor.execute("""SELECT 1 FROM authority_lease_acquisition lease
            JOIN authority_attempt attempt USING(attempt_id)
            JOIN authority_operation op USING(operation_id)
            WHERE lease.status='HELD' AND op.project_id=%s
              AND (op.operation_id=%s OR op.root_operation_id=%s OR op.root_operation_id IN (
                  SELECT chapter_root_operation_id FROM authority_book_chapter_request WHERE book_run_id=%s)) LIMIT 1""",
            [book["project_id"], book["root_operation_id"], book["root_operation_id"], book_run_id])
        if uow.cursor.fetchone():
            raise KernelError("AUTHOR_WORKFLOW_CHECKPOINT_REQUIRED", "Release original execution leases before extending delivery")
        profile = uow.repositories.asset_documents.require(project_id=book["project_id"],
            asset_version_id=book["production_profile_version"])
        target = profile.content.get("target_chapter_count")
        if (profile.asset_type != "production_profile" or profile.governance != "CLEAR"
                or profile.eligibility != "ELIGIBLE" or not isinstance(target, int)
                or isinstance(target, bool) or target <= 0):
            raise KernelError("BOOK_DELIVERY_WINDOW_PROFILE_REQUIRED", "Retain a frozen full-book target before extending delivery")
        if not current["target_chapter_count"] < stop_after_chapter <= target:
            raise KernelError("BOOK_DELIVERY_WINDOW_RANGE_INVALID", "Extend beyond the current delivery target within the frozen full-book target")
        previous = delivery_window_evidence(uow.cursor, current)
        content = {"version": "book-delivery-window-extension.v1", "project_id": book["project_id"],
            "workspace_id": book["workspace_id"], "book_id": book["book_id"], "book_run_id": book_run_id,
            "source_profile_version": book["production_profile_version"], "source_book_version": expected_version,
            "previous_stop_after_chapter": current["target_chapter_count"], "stop_after_chapter": stop_after_chapter,
            "full_book_target_chapters": target,
            "previous_policy_asset_version_id": previous["asset_version_id"] if previous else None,
            "current_chapter": current["current_chapter"], "accepted_through_chapter": current["accepted_through_chapter"],
            "history_rewritten": False}
        asset = uow.repositories.asset_documents.materialize_output(AuthorityAssetWriteCommand(
            operation_id=operation_id, project_id=book["project_id"], asset_id="book-delivery-window:" + book_run_id,
            asset_type="book_delivery_window_policy", schema_version=content["version"],
            logical_ref="book-delivery-window/" + book_run_id, category="policy", output_key="book.delivery_window",
            role="primary", content=content, qualification_policy="authenticated-book-policy.v1",
            expected_current_asset_version_id=previous["asset_version_id"] if previous else None,
            trace_id=operation_id, correlation_id=book["root_operation_id"]))
        uow.cursor.execute("""UPDATE authority_book_production
            SET target_chapter_count=%s,version=version+1,updated_at=NOW() WHERE book_run_id=%s""",
            [stop_after_chapter, book_run_id])
        checkpoint("after_delivery_window_extension")
        return {"book_run_id": book_run_id, "book_version": expected_version + 1,
            "policy_asset_version_id": asset.asset_version_id, "stop_after_chapter": stop_after_chapter,
            "full_book_target_chapters": target}

    return authority._execute_mutation(book=book, action="delivery_window_extend",
        event_type="book.delivery_window.extended", idempotency_key=idempotency_key,
        actor_id=principal.principal_id, trace_id=idempotency_key,
        correlation_id=book["root_operation_id"], causation_id=book["root_operation_id"],
        payload={"expected_version": expected_version, "stop_after_chapter": stop_after_chapter}, handler=commit)
