from __future__ import annotations

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.step_successor_v2 import CONTRACT as STEP_CONTRACT, replace_failed_step
from novel_forge.modules.command_kernel.service import AdmissionContext
from novel_forge.modules.production_execution.execution_template import selected_book_template
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .contracts import ChapterInputAsset
from .receipt_recovery import _cancelled

CONTRACT = "frozen-publication-revalidation.v2"
LEGACY_CONTRACT = "frozen-publication-revalidation.v1"


def _source_allowed(source, current, policy, publish_gate):
    if (policy.get("contract_version") != CONTRACT or current.get("definition_version") != "3.10.0"
        or source.get("definition_name") != "chapter.export.render" or current.get("definition_name") != source.get("definition_name")
        or source.get("definition_version") != "3.9.0" or source.get("status") != "FAILED_FINAL"
        or any(current.get(key) != source.get(key) for key in ("project_id", "workspace_id", "actor_id", "root_operation_id", "command_payload", "input_asset_snapshot"))
        or policy.get("frozen_inputs") != source.get("input_asset_snapshot")
        or current.get("causation_operation_id") != source.get("operation_id")
        or not publish_gate.content.get("failed_checks")
        or set(publish_gate.content.get("failed_checks", [])) - {"latest_rereview_passed", "quality_internal_admission"}):
        raise KernelError("PUBLICATION_RECOVERY_SOURCE_INVALID", "Only the exact owned historical work-admission interface may be rebuilt")


def revalidate_frozen_publication(request, *, revision, publish_gate):
    from .domain_handlers import build_publish_gate
    from .handlers import _content_hash
    from novel_forge.modules.chapter_quality_authority.creative_validation import verify_internal_quality
    if request.definition_version != "3.10.0" or not request.database_url:
        raise KernelError("PUBLICATION_RECOVERY_SOURCE_INVALID", "Publication recovery requires the declared current native successor")
    with AuthorityUnitOfWork(request.database_url) as u:
        u.cursor.execute("""SELECT j.policy_evidence,j.source_failure_snapshot,to_jsonb(current),to_jsonb(source)
            FROM authority_saga_step_successor j JOIN authority_operation current ON current.operation_id=j.successor_operation_id
            JOIN authority_operation source ON source.operation_id=j.predecessor_operation_id
            JOIN authority_saga_step step ON step.operation_id=current.operation_id AND step.saga_id=j.saga_id
            WHERE j.successor_operation_id=%s AND j.project_id=%s AND j.contract_version=%s""",
            [request.operation_id, request.project_id, STEP_CONTRACT])
        rows = u.cursor.fetchall()
        if len(rows) != 1:
            raise KernelError("PUBLICATION_RECOVERY_SOURCE_INVALID", "One immutable native replacement is required")
        policy, frozen, current, source = rows[0]
        if source != frozen.get("operation"):
            raise KernelError("PUBLICATION_RECOVERY_SOURCE_INVALID", "The original terminal owner remains immutable")
        _source_allowed(source, current, policy, publish_gate)
        u.cursor.execute("""SELECT to_jsonb(o) FROM authority_operation o JOIN authority_operation_output_asset a USING(operation_id)
            WHERE a.asset_version_id=%s AND a.output_key='chapter.publish_gate' AND a.role='primary'
            AND o.project_id=%s AND o.status='SUCCEEDED' AND o.definition_name='chapter.publishing.prepare_release'
            AND o.definition_version='3.9.0'""", [publish_gate.asset_version_id, request.project_id])
        gates = u.cursor.fetchall()
        if (len(gates) != 1 or any(gates[0][0].get(key) != source.get(key)
            for key in ("project_id", "workspace_id", "actor_id", "root_operation_id"))):
            raise KernelError("PUBLICATION_RECOVERY_SOURCE_INVALID", "The frozen publish gate must share the original execution owner")
        from novel_forge.modules.command_kernel.step_successor import require_live_chapter_frontier
        require_live_chapter_frontier(u.cursor, root_id=source["root_operation_id"], project_id=request.project_id,
            book_run_id=policy["book_run_id"])
        gate_source = gates[0][0]
    query = AuthorityAssetQuery(request.database_url)
    inputs = {}
    for binding in gate_source["input_asset_snapshot"]:
        item = query.require(project_id=request.project_id, asset_version_id=binding["asset_version_id"])
        if (item.content_hash != binding["content_hash"] or item.asset_type in inputs
            or (item.lifecycle, item.eligibility, item.governance) != ("ACTIVE", "ELIGIBLE", "CLEAR")):
            raise KernelError("PUBLICATION_RECOVERY_SOURCE_INVALID", "Frozen evidence identity, hash and governance must remain exact")
        inputs[item.asset_type] = item
    if set(inputs) != {"best_draft_candidate", "quality_score_report", "re_review_report", "canon_patch", "context_bundle"}:
        raise KernelError("PUBLICATION_RECOVERY_SOURCE_INVALID", "The complete original publication evidence set is required")
    selected = inputs["best_draft_candidate"]
    if (selected.asset_version_id, selected.content_hash) != (revision.asset_version_id, revision.content_hash):
        raise KernelError("PUBLICATION_RECOVERY_SOURCE_INVALID", "Publication must bind the exact frozen candidate")
    quality, review, canon, context = [inputs[k] for k in ("quality_score_report", "re_review_report", "canon_patch", "context_bundle")]
    verify_internal_quality(request.database_url, quality.content["internal_admission"], project_id=request.project_id,
        book_id=policy["book_id"])
    content = build_publish_gate(project_id=request.project_id, revision=revision.content, revision_asset_version_id=revision.asset_version_id,
        quality=quality.content, quality_asset_version_id=quality.asset_version_id, review=review.content, review_asset_version_id=review.asset_version_id,
        canon=canon.content, canon_asset_version_id=canon.asset_version_id, context_bundle=context.content,
        context_bundle_version_id=context.asset_version_id, work_admission=True)
    if content.get("gate") != "INTERNAL_ADMITTED":
        raise KernelError("CHAPTER_QUALITY_GATE_BLOCKED", "Current exact evidence still blocks work admission")
    content["publication_contract_revalidation"] = {"contract_version": CONTRACT,
        "source_gate_asset_version_id": publish_gate.asset_version_id, "source_input_snapshot": gate_source["input_asset_snapshot"],
        "provider_dispatches": 0, "original_review_decision_preserved": True}
    return ChapterInputAsset(f"authority-output:{request.operation_id}:chapter.export.revalidated_publish_gate:v1",
        "publish_gate_report", _content_hash(content), content)


def recover_publication_contract(authority, *, book_run_id, principal):
    book = authority.require(book_run_id)
    principal.require("book.authority.execute", book["project_id"])
    principal.require("chapter.authority.execute", book["project_id"])
    if book["state"] != "CHAPTER_RUNNING" or not book.get("active_chapter_request_id"):
        return False
    request = authority.require_chapter_request(book["active_chapter_request_id"])
    if request["chapter_number"] != book["accepted_through_chapter"] + 1:
        return False
    with AuthorityUnitOfWork(authority.database_url) as u:
        template = selected_book_template(u.cursor, project_id=book["project_id"], book_id=book["book_id"])
        if not template or _cancelled(u.cursor, book):
            return False
        u.cursor.execute("""SELECT DISTINCT to_jsonb(o) FROM authority_operation o JOIN authority_saga_step s USING(operation_id)
            JOIN authority_attempt a USING(operation_id) WHERE o.root_operation_id=%s AND o.project_id=%s
            AND o.definition_name='chapter.export.render' AND o.definition_version='3.9.0' AND o.status='FAILED_FINAL'
            AND a.result->>'error_code'='CHAPTER_QUALITY_GATE_BLOCKED'""", [request["chapter_root_operation_id"], book["project_id"]])
        rows = u.cursor.fetchall()
        if not rows:
            return False
        if len(rows) != 1 or rows[0][0]["actor_id"] != principal.principal_id:
            raise KernelError("PUBLICATION_RECOVERY_SOURCE_INVALID", "One exact owned terminal Export is required")
        source = rows[0][0]
        query = AuthorityAssetQuery(authority.database_url)
        gates = [query.require(project_id=book["project_id"], asset_version_id=row["asset_version_id"])
            for row in source["input_asset_snapshot"]]
        gate = next((item for item in gates if item.asset_type == "publish_gate_report"), None)
        manifest = (gate.content.get("release_manifest") or {}) if gate else {}
        quality_id = manifest.get("quality_asset_version_id")
        if not quality_id:
            return False
        quality = query.require(project_id=book["project_id"], asset_version_id=quality_id)
        if (quality.content.get("internal_admission") or {}).get("version") != "creative-quality-admission.v3":
            return False
    def guard(u):
        u.cursor.execute("SELECT version,active_chapter_request_id,accepted_through_chapter FROM authority_book_production WHERE book_run_id=%s FOR UPDATE", [book_run_id])
        if (u.cursor.fetchone() != (book["version"], book["active_chapter_request_id"], book["accepted_through_chapter"])
            or _cancelled(u.cursor, book) or selected_book_template(u.cursor, project_id=book["project_id"], book_id=book["book_id"]) != template):
            raise KernelError("PUBLICATION_RECOVERY_SOURCE_INVALID", "Reload the exact Book frontier and authorization")
    replace_failed_step(authority.database_url, predecessor_id=source["operation_id"], target_version="3.10.0",
        context=AdmissionContext(principal.principal_id, principal.permissions, authority.chapter_port.application.registry.available_handler_keys,
            authority.application_build_id, authority.commit_sha), expected_failure_code="CHAPTER_QUALITY_GATE_BLOCKED",
        policy_evidence={"contract_version": CONTRACT, "book_run_id": book_run_id, "book_id": book["book_id"],
            "chapter_request_id": request["chapter_request_id"], "policy_admission": template, "frozen_inputs": source["input_asset_snapshot"]},
        transaction_guard=guard, window_successor={"contract_version": "kernel-corrected-contract-window.v1",
            "policy_key": "reviewed_work_admission", "policy_value": "reviewed-work-admission.v2"})
    return True
