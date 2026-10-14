from copy import deepcopy
from typing import Any

from novel_forge.modules.chapter_authority.author_editor import source_draft_content
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.working_memory import normalize_observations, validate_observations


def memory_ref(book: dict[str, Any], version_id: str) -> str:
    from novel_forge.modules.story_planning_runtime.domain import canonical_hash
    return "book-working-memory/" + book["book_run_id"] + "/" + canonical_hash(version_id)[7:]


def source_memory(uow, book, source):
    from .manuscript import _optional_document
    sidecar = _optional_document(uow, book["project_id"], memory_ref(book, source.asset_version_id))
    if sidecar:
        if any(sidecar.content.get(k) != value for k, value in {
                "book_run_id": book["book_run_id"], "source_asset_version_id": source.asset_version_id,
                "source_content_hash": source.content_hash}.items()):
            return None, {"status": "SOURCE_BINDING_INVALID"}
        return sidecar.content.get("observations"), {"kind": sidecar.content.get("source_kind"),
            "asset_version_id": sidecar.asset_version_id, "content_hash": sidecar.content_hash}
    draft = source_draft_content(source)
    value = draft.get("working_memory", {})
    if not isinstance(value, dict):
        return None, {"status": "OBSERVATION_FORMAT_INVALID"}
    return value.get("observations"), {"kind": "WRITER_SELF_OBSERVATION",
        "asset_version_id": source.asset_version_id, "status": value.get("status", "MISSING")}


def selected_working_craft_history(database_url: str, *, snapshot, mkaos, policy) -> list[dict[str, Any]]:
    from novel_forge.modules.mkaos_authority.craft_usage import WORKING_CRAFT_POLICY
    if policy == WORKING_CRAFT_POLICY:
        return _selected_working_craft_v2(database_url, snapshot=snapshot, mkaos=mkaos)
    from .manuscript import AUTHOR_WORKFLOW, effective_workflow, verify_working_context
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    expected = {"version": "working-craft-delivery.v1", "use": "SOFT_SELECTION_CAUTION"}
    if policy != expected:
        raise KernelError("WORKING_CRAFT_HISTORY_POLICY_INVALID", "Working Craft delivery is a scoped selection caution")
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT to_jsonb(b) FROM authority_book_production b WHERE book_run_id=%s AND project_id=%s AND book_id=%s",
            [snapshot["book_run_id"],snapshot["project_id"],snapshot["book_id"]])
        row = uow.cursor.fetchone()
        if not row or effective_workflow(uow.cursor, row[0]) != AUTHOR_WORKFLOW:
            raise KernelError("WORKING_CRAFT_HISTORY_SCOPE_INVALID", "Require the owning author-first Book")
        verify_working_context(uow, row[0], snapshot)
    all_selected = {source["asset_version_id"]:source for source in snapshot["sources"]}
    selected = {identity:source for identity,source in all_selected.items() if not source.get("dependency_changes")}
    rows = mkaos.list_runtime_usage(project_id=snapshot["project_id"],book_id=snapshot["book_id"],limit=500)
    history = {}
    for row in rows:
        source = selected.get(row.get("result_asset_version_id"))
        if source is None:
            continue
        for use in row.get("craft_usage", []):
            if use.get("chapter") != source["chapter"] or not use.get("external_receipt_ids"):
                continue
            key = (source["chapter"],use["use_id"])
            history[key] = {**use, "usage_basis": "SELECTED_WORKING_DELIVERY", "effect_status": "NOT_ASSESSED",
                "selected_source_asset_version_id": source["asset_version_id"], "selected_source_content_hash": source["content_hash"],
                "target_text_hash": source["text_hash"], "working_snapshot_hash": snapshot["snapshot_hash"],
                "evidence_ceiling": "DELIVERED_PLANNED_ALLOCATION_NOT_REALIZED_EFFECT"}
    covered = {value["selected_source_asset_version_id"] for value in history.values()}
    missing = [{"usage_basis": "WORKING_CRAFT_COVERAGE", "status": "UNKNOWN",
        "chapter": source["chapter"], "selected_source_asset_version_id": source["asset_version_id"],
        "selected_source_content_hash": source["content_hash"], "working_snapshot_hash": snapshot["snapshot_hash"],
        "reason": "DEPENDENCY_CHANGED" if source.get("dependency_changes") else "NO_MATCHED_DELIVERY_CRAFT_RECEIPT"}
        for identity,source in all_selected.items() if identity not in covered]
    return [history[key] for key in sorted(history)] + missing


def _working_review_observations(uow, *, snapshot, source, draft, deliveries):
    from novel_forge.modules.review.craft import craft_review_targets, validate_craft_checks
    from novel_forge.modules.story_planning_runtime.domain import canonical_hash
    uow.cursor.execute(
        """SELECT DISTINCT version.asset_version_id, version.created_at
           FROM authority_asset_version version JOIN authority_asset asset USING(asset_id)
           JOIN authority_operation_output_asset output USING(asset_version_id)
           JOIN authority_operation op USING(operation_id)
           JOIN authority_book_chapter_request request ON request.chapter_root_operation_id=op.root_operation_id
           WHERE asset.project_id=%s AND request.project_id=%s AND request.book_run_id=%s
             AND request.chapter_number=%s AND asset.asset_type IN ('review_report','re_review_report')
             AND (version.content->>'target_asset_version_id'=%s OR version.content->>'revision_version_id'=%s)
           ORDER BY version.created_at DESC, version.asset_version_id DESC LIMIT 50""",
        [snapshot["project_id"], snapshot["project_id"], snapshot["book_run_id"], source["chapter"],
         source["asset_version_id"], source["asset_version_id"]])
    identities = [row[0] for row in uow.cursor.fetchall()]
    if not identities:
        return []
    try:
        targets = craft_review_targets(draft)
    except (KernelError, KeyError, TypeError, ValueError):
        return []
    if not targets:
        return []
    by_use = {row["use_id"]: row for row in deliveries}
    for identity in identities[:1]:
        document = uow.repositories.asset_documents.require(project_id=snapshot["project_id"], asset_version_id=identity)
        review = document.content
        if (document.content_hash != canonical_hash(review) or review.get("target_text_hash") != source["text_hash"]
            or review.get("project_id") != snapshot["project_id"] or review.get("chapter") != source["chapter"]
            or review.get("report_type") not in {"ReviewReport", "ReReviewReport"}):
            continue
        try:
            checks = validate_craft_checks(checks=review.get("craft_checks"), targets=targets, issues=review.get("issues", []),
                text=draft["text"], target_asset_version_id=source["asset_version_id"],
                real_model_call=review.get("provider_evidence", {}).get("real_model_call") is True)
        except (KernelError, KeyError, TypeError, ValueError):
            continue
        observations = []
        for raw, check in zip(review["craft_checks"], checks, strict=True):
            delivery = by_use.get(check["use_id"])
            if (not delivery or raw.get("target_asset_version_id") != source["asset_version_id"]
                or raw.get("target_text_hash") != source["text_hash"]
                or any(raw.get(key) != delivery.get(key) for key in ("knowledge_card_asset_version_id", "content_hash", "mechanism_id", "mechanism_version"))):
                continue
            observations.append({**delivery, "usage_basis": "SELECTED_WORKING_PROSE_REVIEW",
                "effect_status": check["effect_status"], "evidence": check["evidence"], "side_effects": check["side_effects"],
                **({"phase_transition": check["phase_transition"]} if "phase_transition" in check else {}),
                "review_asset_version_id": document.asset_version_id, "review_content_hash": document.content_hash,
                "review_provider_evidence": deepcopy(review.get("provider_evidence", {})),
                "evidence_class": check["evidence_class"], "reader_effect_proven": False,
                "evidence_ceiling": "SELECTED_WORKING_REVIEW_NOT_FORMAL_ACCEPTANCE_OR_READER_EFFECT"})
        if observations:
            return observations
    return []


def _selected_working_craft_v2(database_url: str, *, snapshot, mkaos):
    from .manuscript import AUTHOR_WORKFLOW, effective_workflow, verify_working_context
    from .working_prose import working_source_rows
    from novel_forge.modules.mkaos_authority.craft_usage import WORKING_CRAFT_POLICY
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    all_selected = {source["asset_version_id"]: source for source in working_source_rows(snapshot)}
    history, missing = [], []
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT to_jsonb(b) FROM authority_book_production b WHERE book_run_id=%s AND project_id=%s AND book_id=%s",
            [snapshot["book_run_id"], snapshot["project_id"], snapshot["book_id"]])
        row = uow.cursor.fetchone()
        if not row or effective_workflow(uow.cursor, row[0]) != AUTHOR_WORKFLOW:
            raise KernelError("WORKING_CRAFT_HISTORY_SCOPE_INVALID", "Require the owning author-first Book")
        verify_working_context(uow, row[0], snapshot)
        for source in all_selected.values():
            deliveries = {}
            if not source.get("dependency_changes"):
                rows = mkaos.list_runtime_usage(project_id=snapshot["project_id"], book_id=snapshot["book_id"],
                    result_asset_version_id=source["asset_version_id"], limit=500)
                for usage_row in rows:
                    if usage_row.get("result_asset_version_id") != source["asset_version_id"]:
                        continue
                    for use in usage_row.get("craft_usage", []):
                        if use.get("chapter") != source["chapter"] or not use.get("external_receipt_ids"):
                            continue
                        deliveries[use["use_id"]] = {**use, "usage_basis": "SELECTED_WORKING_DELIVERY", "effect_status": "NOT_ASSESSED",
                            "book_run_id": snapshot["book_run_id"], "selected_source_asset_version_id": source["asset_version_id"],
                            "selected_source_content_hash": source["content_hash"], "target_text_hash": source["text_hash"],
                            "working_snapshot_hash": snapshot["snapshot_hash"], "working_craft_policy": dict(WORKING_CRAFT_POLICY),
                            "formal_acceptance": "NOT_GRANTED", "evidence_ceiling": "DELIVERED_PLANNED_ALLOCATION_NOT_REALIZED_EFFECT"}
            if deliveries:
                history.extend(deliveries.values())
                document = uow.repositories.asset_documents.require(project_id=snapshot["project_id"], asset_version_id=source["asset_version_id"])
                history.extend(_working_review_observations(uow, snapshot=snapshot, source=source,
                    draft=source_draft_content(document), deliveries=list(deliveries.values())))
            else:
                missing.append({"usage_basis": "WORKING_CRAFT_COVERAGE", "status": "UNKNOWN", "chapter": source["chapter"],
                    "selected_source_asset_version_id": source["asset_version_id"], "selected_source_content_hash": source["content_hash"],
                    "working_snapshot_hash": snapshot["snapshot_hash"],
                    "reason": "DEPENDENCY_CHANGED" if source.get("dependency_changes") else "NO_MATCHED_DELIVERY_CRAFT_RECEIPT"})
        verify_working_context(uow, row[0], snapshot)
    return sorted(history, key=lambda item: (item["chapter"], item["use_id"], item["usage_basis"])) + missing


def save_manuscript_memory(authority, book_run_id: str, *, chapter: int, source_asset_version_id: str,
                           expected_version: int, observations: list[dict[str, Any]], idempotency_key: str,
                           source_kind: str, principal) -> dict[str, Any]:
    from .manuscript import selected_source, working_dependency_changes
    book = authority.require(book_run_id)
    principal.require("book.authority.execute", book["project_id"])
    if source_kind not in {"AUTHOR_ANNOTATION", "ASSISTANT_ANALYSIS"}:
        raise KernelError("WORKING_MEMORY_PROVENANCE_INVALID", "Model observations require their native Draft receipt")
    refs = authority.resolve_asset_refs(project_id=book["project_id"], asset_version_ids=(source_asset_version_id,))

    def commit(uow, operation_id, checkpoint):
        uow.cursor.execute("SELECT book_id FROM authority_book WHERE book_id=%s FOR UPDATE", [book["book_id"]])
        uow.cursor.execute("SELECT to_jsonb(b) FROM authority_book_production b WHERE book_run_id=%s FOR UPDATE", [book_run_id])
        current = uow.cursor.fetchone()[0]
        if current["version"] != expected_version or type(chapter) is not int or not 1 <= chapter <= current["current_chapter"]:
            raise KernelError("WORKING_MEMORY_CHECKPOINT_STALE", "Reload the exact selected manuscript and Book checkpoint")
        source = selected_source(uow, current, chapter)
        if source.asset_version_id != source_asset_version_id:
            raise KernelError("WORKING_MEMORY_SOURCE_STALE", "Cannot annotate an unselected or superseded manuscript")
        text = source_draft_content(source)["text"]
        _, changes = working_dependency_changes(uow, current)
        known = set()
        for number in range(1, chapter):
            predecessor = selected_source(uow, current, number)
            memory, _ = source_memory(uow, current, predecessor)
            if memory is not None and not changes.get(number):
                try:
                    validate_observations(memory, source_draft_content(predecessor)["text"], available_causes=known)
                    known.update(row["observation_id"] for row in memory["entries"])
                except (KernelError, TypeError, ValueError, KeyError):
                    continue
        normalized = normalize_observations(observations, text, available_causes=known)
        prior = None
        from .manuscript import _optional_document
        prior = _optional_document(uow, current["project_id"], memory_ref(current, source_asset_version_id))
        content = {"version": "manuscript-memory-sidecar.v1", "book_run_id": book_run_id,
            "project_id": current["project_id"], "book_id": current["book_id"], "chapter": chapter,
            "source_asset_version_id": source_asset_version_id, "source_content_hash": source.content_hash,
            "observations": normalized, "source_kind": source_kind, "actor_id": principal.principal_id,
            "formal_acceptance": "NOT_GRANTED"}
        document = uow.repositories.asset_documents.materialize_output(AuthorityAssetWriteCommand(
            operation_id=operation_id, project_id=current["project_id"], asset_id=prior.asset_id if prior else "working-memory:" + operation_id,
            asset_type="manuscript_memory", schema_version=content["version"], logical_ref=memory_ref(current, source_asset_version_id),
            category="working-manuscript", output_key="book.manuscript_memory", role="completion_evidence", content=content,
            qualification_policy="unreviewed-working-observation.v1", trace_id=operation_id, correlation_id=current["root_operation_id"],
            expected_current_asset_version_id=prior.asset_version_id if prior else None))
        uow.cursor.execute("UPDATE authority_book_production SET version=version+1,updated_at=NOW() WHERE book_run_id=%s", [book_run_id])
        checkpoint("after_manuscript_memory")
        return {"memory_asset_version_id": document.asset_version_id, "source_asset_version_id": source_asset_version_id,
                "observation_count": len(normalized["entries"]), "formal_acceptance": "NOT_GRANTED"}

    return authority._execute_mutation(book=book, action="manuscript_memory_save", event_type="book.manuscript_memory.saved",
        idempotency_key=idempotency_key, actor_id=principal.principal_id, trace_id=idempotency_key,
        correlation_id=book["root_operation_id"], causation_id=book["root_operation_id"],
        payload={"chapter": chapter, "source_asset_version_id": source_asset_version_id, "expected_version": expected_version,
                 "observations": observations, "source_kind": source_kind}, handler=commit, input_assets=refs)
