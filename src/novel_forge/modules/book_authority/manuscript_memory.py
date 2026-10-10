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
