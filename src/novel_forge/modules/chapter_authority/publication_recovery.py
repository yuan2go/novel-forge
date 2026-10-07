from __future__ import annotations

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from .contracts import ChapterInputAsset


def revalidate_frozen_publication(request, *, revision, publish_gate):
    from .domain_handlers import build_publish_gate
    from novel_forge.modules.chapter_quality_authority.creative_validation import verify_internal_quality
    with AuthorityUnitOfWork(request.database_url) as u:
        u.cursor.execute("""SELECT o.input_asset_snapshot,o.root_operation_id,o.actor_id FROM authority_operation o
            JOIN authority_operation_output_asset a USING(operation_id) WHERE a.asset_version_id=%s
            AND a.output_key='chapter.publish_gate' AND o.project_id=%s AND o.status='SUCCEEDED'
            AND o.definition_name='chapter.publishing.prepare_release' AND o.definition_version='3.9.0'""",
            [publish_gate.asset_version_id, request.project_id])
        row = u.cursor.fetchone()
        u.cursor.execute("SELECT root_operation_id,actor_id FROM authority_operation WHERE operation_id=%s AND project_id=%s",
            [request.operation_id, request.project_id])
        owner = u.cursor.fetchone()
    if not row or row[1:] != owner or set(publish_gate.content.get("failed_checks", [])) - {"latest_rereview_passed", "quality_internal_admission"}:
        raise KernelError("PUBLICATION_RECOVERY_SOURCE_INVALID", "Only an owned historical work-admission interface may be rebuilt")
    query = AuthorityAssetQuery(request.database_url)
    inputs = {item.asset_type: item for item in (query.require(project_id=request.project_id, asset_version_id=a["asset_version_id"]) for a in row[0])}
    selected = inputs["best_draft_candidate"]
    if selected.asset_version_id != revision.asset_version_id or selected.content_hash != revision.content_hash:
        raise KernelError("PUBLICATION_RECOVERY_SOURCE_INVALID", "Publication must bind the exact frozen candidate")
    quality, review, canon, context = [inputs[k] for k in ("quality_score_report", "re_review_report", "canon_patch", "context_bundle")]
    verify_internal_quality(request.database_url, quality.content["internal_admission"], project_id=request.project_id)
    content = build_publish_gate(project_id=request.project_id, revision=revision.content, revision_asset_version_id=revision.asset_version_id,
        quality=quality.content, quality_asset_version_id=quality.asset_version_id, review=review.content, review_asset_version_id=review.asset_version_id,
        canon=canon.content, canon_asset_version_id=canon.asset_version_id, context_bundle=context.content,
        context_bundle_version_id=context.asset_version_id, work_admission=True)
    if content.get("gate") != "INTERNAL_ADMITTED":
        raise KernelError("CHAPTER_QUALITY_GATE_BLOCKED", "Current evidence still blocks work admission")
    content["publication_contract_revalidation"] = {"contract_version": "frozen-publication-revalidation.v1",
        "source_gate_asset_version_id": publish_gate.asset_version_id, "source_input_snapshot": row[0],
        "provider_dispatches": 0, "original_review_decision_preserved": True}
    from .handlers import _content_hash
    return ChapterInputAsset(f"authority-output:{request.operation_id}:chapter.export.revalidated_publish_gate:v1",
        "publish_gate_report", _content_hash(content), content)


def recover_publication_contract(authority, *, book_run_id, principal):
    from .contract_recovery import _cancelled
    from novel_forge.modules.production_execution.execution_template import selected_book_template
    from novel_forge.modules.command_kernel.service import AdmissionContext
    from novel_forge.modules.command_kernel.step_successor import replace_failed_step
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
        u.cursor.execute("""SELECT o.operation_id,o.input_asset_snapshot FROM authority_operation o
            JOIN authority_saga_step s USING(operation_id) JOIN authority_attempt a USING(operation_id)
            WHERE o.root_operation_id=%s AND o.project_id=%s AND o.definition_name='chapter.export.render'
            AND o.definition_version='3.9.0' AND o.status='FAILED_FINAL' AND a.result->>'error_code'='CHAPTER_QUALITY_GATE_BLOCKED'""",
            [request["chapter_root_operation_id"], book["project_id"]])
        row = u.cursor.fetchone()
    if not row:
        return False
    def guard(u):
        u.cursor.execute("SELECT version,active_chapter_request_id,accepted_through_chapter FROM authority_book_production WHERE book_run_id=%s FOR UPDATE", [book_run_id])
        if (u.cursor.fetchone() != (book["version"], book["active_chapter_request_id"], book["accepted_through_chapter"])
            or _cancelled(u.cursor, book) or selected_book_template(u.cursor, project_id=book["project_id"], book_id=book["book_id"]) != template):
            raise KernelError("PUBLICATION_RECOVERY_SOURCE_INVALID", "Reload the exact Book frontier and authorization")
    replace_failed_step(authority.database_url, predecessor_id=row[0], target_version="3.9.1",
        context=AdmissionContext(principal.principal_id, principal.permissions, authority.chapter_port.application.registry.available_handler_keys,
            authority.application_build_id, authority.commit_sha), expected_failure_code="CHAPTER_QUALITY_GATE_BLOCKED",
        policy_evidence={"contract_version": "frozen-publication-revalidation.v1", "book_run_id": book_run_id,
            "chapter_request_id": request["chapter_request_id"], "policy_admission": template, "frozen_inputs": row[1]},
        transaction_guard=guard)
    return True
