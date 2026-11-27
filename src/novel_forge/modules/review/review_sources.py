from __future__ import annotations

from typing import Any

from novel_forge.modules.chapter_authority.author_editor import text_hash
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_asset_store import AuthorityAssetDocumentRepository
from novel_forge.storage.book_edition_repositories import BookEditionRepository


def _invalid(message: str) -> None:
    raise KernelError("CROSS_MODEL_REVIEW_SOURCE_INVALID", message)


def _document(cursor, project_id, version_id):
    document = AuthorityAssetDocumentRepository(cursor).require(project_id=project_id, asset_version_id=version_id)
    content = document.content
    if (document.governance != "CLEAR" or document.eligibility != "ELIGIBLE"
            or content.get("routing_eligibility") == "BENCHMARK_ONLY"
            or content.get("fixture_protocol_only") or content.get("diagnostic_only")):
        _invalid("Review sources must be governed production assets; diagnostics cannot be adopted")
    return document


def _native_output(cursor, document, names):
    cursor.execute("""SELECT op.operation_id,op.actor_id,op.workspace_id,op.command_payload,
            root.command_payload FROM authority_operation_output_asset output
        JOIN authority_operation op USING(operation_id)
        JOIN authority_operation root ON root.operation_id=op.root_operation_id
        WHERE output.asset_version_id=%s AND output.content_hash=%s AND op.project_id=%s
          AND op.status='SUCCEEDED' AND op.definition_name=ANY(%s)""",
        [document.asset_version_id, document.content_hash, document.project_id, list(names)])
    rows = cursor.fetchall()
    if len(rows) != 1:
        _invalid("Source lacks one successful native adoption or author operation")
    row = rows[0]
    if any(command.get("routing_bootstrap_authorization") or command.get("chapter_sampling")
           for command in (row[3], row[4])):
        _invalid("Diagnostic operations cannot establish authored production provenance")
    return row


def _ref(document):
    return {"asset_version_id": document.asset_version_id, "content_hash": document.content_hash}


def adopted_source(cursor: Any, *, project_id: str, book_id: str,
                   asset_version_id: str, content_hash: str, content: dict[str, Any], depth: int = 0) -> dict[str, Any]:
    if depth >= 32:
        _invalid("Source lineage exceeds the review bound; reconcile the original source before review")
    document = _document(cursor, project_id, asset_version_id)
    if document.content_hash != content_hash or document.content != content or document.asset_type != "draft_chapter":
        _invalid("Adopted prose differs from the exact frozen review target")
    adoption = content["author_draft_adoption"]
    origin = _native_output(cursor, document, {"chapter.draft.generate"})
    frozen = (origin[4].get("preparation_report") or {}).get("author_draft_adoption")
    if frozen != adoption or adoption.get("project_id") != project_id or adoption.get("book_id") != book_id:
        _invalid("Adoption must match its native Chapter request and Book")
    if (adoption.get("workspace_id") != origin[2] or adoption.get("chapter") != content.get("chapter")
            or adoption.get("text_hash") != text_hash(content["text"])):
        _invalid("Adoption workspace, chapter or current text differs")
    cursor.execute("""SELECT v.content FROM authority_operation_output_asset output
        JOIN authority_asset_version v USING(asset_version_id)
        JOIN authority_asset a ON a.asset_id=v.asset_id AND a.project_id=%s
        WHERE output.operation_id=%s AND a.asset_type='author_draft_adoption_evidence'
          AND output.content_hash=v.content_hash""", [project_id, origin[0]])
    proofs = cursor.fetchall()
    if len(proofs) != 1 or any(proofs[0][0].get(key) != value for key, value in adoption.items()):
        _invalid("Adopted draft requires its separately persisted native adoption evidence")
    if adoption.get("contract_version") == "book-edition-draft-adoption.v1":
        return _edition_source(cursor, document, adoption, depth)
    if adoption.get("contract_version") != "author-draft-adoption.v1":
        _invalid("Unknown adoption contract; select a supported native author or edition input")
    candidate = _document(cursor, project_id, adoption["candidate_asset_version_id"])
    decision = _document(cursor, project_id, adoption["decision_asset_version_id"])
    saved = _native_output(cursor, candidate, {"chapter.author_edit.save"})
    accepted = _native_output(cursor, decision, {"chapter.author_edit.accept"})
    scope = {key: adoption[key] for key in ("project_id", "workspace_id", "book_id", "chapter")}
    if (candidate.asset_type != "author_edit_candidate" or decision.asset_type != "author_edit_decision"
            or candidate.content_hash != adoption["candidate_content_hash"]
            or decision.content_hash != adoption["decision_content_hash"]
            or any(item.content.get(key) != value for item in (candidate, decision) for key, value in scope.items())
            or candidate.content.get("text") != content["text"]
            or candidate.content.get("text_hash") != adoption["text_hash"]
            or candidate.content.get("author_id") != saved[1] or adoption.get("author_id") != saved[1]
            or decision.content.get("actor_id") != accepted[1] or adoption.get("decision_actor_id") != accepted[1]
            or decision.content.get("decision") != "ACCEPT"
            or decision.content.get("candidate_asset_version_id") != candidate.asset_version_id
            or decision.content.get("candidate_content_hash") != candidate.content_hash
            or decision.content.get("text_hash") != adoption["text_hash"]):
        _invalid("Author input and adoption decision must bind this exact current prose and actor")
    lineage = []
    current = candidate
    visited = set()
    while current.asset_type == "author_edit_candidate":
        if current.asset_version_id in visited or len(visited) >= 32:
            _invalid("Author lineage is cyclic or too deep; reconcile its original source")
        visited.add(current.asset_version_id)
        _native_output(cursor, current, {"chapter.author_edit.save"})
        if any(current.content.get(key) != value for key, value in scope.items()):
            _invalid("Author edit lineage crosses Book or chapter scope")
        base = _document(cursor, project_id, current.content["base_asset_version_id"])
        if (base.content_hash != current.content["base_asset_hash"]
                or text_hash(str(base.content.get("text") or "")) != current.content["base_text_hash"]):
            _invalid("Author edit baseline differs from its immutable version or text hash")
        lineage.append({**_ref(current), "base": _ref(base), "edits": current.content["edits"],
                        "author_id": current.content["author_id"]})
        current = base
    if current.asset_version_id != adoption.get("originating_draft_asset_version_id"):
        _invalid("Author lineage does not end at the frozen original source")
    source = {"kind": "AUTHOR_ORIGINAL", "adoption": dict(adoption), "candidate": _ref(candidate),
              "decision": _ref(decision), "lineage": lineage, "original_source": _ref(current)}
    if current.asset_type == "chapter_plan" and not current.content.get("text"):
        return source
    original = prose_origin(cursor, current, book_id, depth + 1)
    return {**source, "kind": "MODEL_EDITED_BY_AUTHOR" if original["model_origins"] else "AUTHOR_ORIGINAL",
            "original_provenance": original}


def prose_origin(cursor, document, book_id, depth=0):
    if depth >= 32:
        _invalid("Source lineage exceeds the review bound; reconcile its original provenance")
    if document.asset_type == "best_draft_candidate":
        from novel_forge.modules.chapter_authority.candidate_selection import retained_candidate_evidence
        selected = retained_candidate_evidence(document.asset_version_id, document.content)
        original = _document(cursor, document.project_id, selected.asset_version_id)
        if original.content.get("text") != document.content.get("text"):
            _invalid("Version reuse must preserve the selected source text exactly")
        cursor.execute("""SELECT input->>'asset_version_id',input->>'content_hash' FROM authority_operation_output_asset output
            JOIN authority_operation op USING(operation_id)
            CROSS JOIN LATERAL jsonb_array_elements(op.input_asset_snapshot) input
            WHERE output.asset_version_id=%s AND output.content_hash=%s AND op.project_id=%s
              AND op.status='SUCCEEDED'""",
            [document.asset_version_id, document.content_hash, document.project_id])
        inputs = cursor.fetchall()
        direct = (original.asset_version_id, original.content_hash) in inputs
        retained = None
        if not direct:
            for version_id, digest in inputs:
                prior = AuthorityAssetDocumentRepository(cursor).require(project_id=document.project_id, asset_version_id=version_id)
                if (prior.asset_type == "best_draft_candidate" and prior.content_hash == digest
                        and prior.content.get("selected_source_asset_version_id") == original.asset_version_id
                        and prior.content.get("text") == original.content.get("text")):
                    prior = _document(cursor, document.project_id, version_id)
                    retained = prose_origin(cursor, prior, book_id, depth + 1)
                    break
        if not direct and retained is None:
            _invalid("Reused version must be a frozen input of the native selection operation")
        provenance = retained or prose_origin(cursor, original, book_id, depth + 1)
        return {"reused_version": _ref(document), "selected_provenance": provenance,
                "model_origins": provenance["model_origins"]}
    if document.content.get("author_draft_adoption") and document.asset_type == "draft_chapter":
        source = adopted_source(cursor, project_id=document.project_id, book_id=book_id,
            asset_version_id=document.asset_version_id, content_hash=document.content_hash,
            content=document.content, depth=depth + 1)
        models = source.get("original_provenance", {}).get("model_origins", [])
        if source["kind"] == "EDITION_MIXED":
            models = [model for item in source["unit_sources"] for model in item["provenance"]["model_origins"]]
        return {"adopted_version": _ref(document), "source": source, "model_origins": models}
    if document.asset_type not in {"draft_chapter", "draft_version"}:
        _invalid("Unknown prose source; select an exact native authored or generated draft")
    from .cross_model_binding import generator_identity
    original = generator_identity(cursor, project_id=document.project_id, book_id=book_id,
        asset_version_id=document.asset_version_id, content_hash=document.content_hash)
    return {"generated_version": _ref(document), "model_origins": [original["generator"]]}


def _edition_source(cursor, document, adoption, depth):
    from novel_forge.modules.book_authority.editions import require_manifest
    repo = BookEditionRepository(cursor)
    revision = repo.revision(project_id=document.project_id, book_id=adoption["book_id"],
                             revision_id=adoption["revision_id"], for_update=False)
    manifest = revision["manifest"]
    require_manifest(manifest)
    binding = repo.run_binding(adoption["book_run_id"])
    if (not binding or binding["revision_id"] != adoption["revision_id"] or binding["role"] != "VALIDATION"
            or revision["content_hash"] != adoption["revision_content_hash"]
            or revision["manifest_digest"] != adoption["manifest_digest"]
            or manifest["workspace_id"] != adoption["workspace_id"]
            or not 1 <= adoption["chapter"] <= len(manifest["units"])):
        _invalid("Edition review requires its exact validation run, revision and manifest")
    unit = manifest["units"][adoption["chapter"] - 1]
    if (unit["unit_id"] != adoption["unit_id"] or unit["text_hash"] != adoption["text_hash"]
            or unit["text"] != document.content["text"]):
        _invalid("Edition unit does not match the current review target")
    sources = []
    for mapping in unit["source_ranges"]:
        original = _document(cursor, document.project_id, mapping["asset_version_id"])
        if (original.content_hash != mapping["asset_hash"]
                or text_hash(original.content["text"][mapping["start"]:mapping["end"]]) != mapping["text_hash"]):
            _invalid("Edition unit source mapping differs from its original prose")
        source = next((item for item in manifest["sources"] if item["asset_version_id"] == original.asset_version_id), None)
        cursor.execute("""SELECT 1 FROM authority_book_chapter_acceptance accepted
            JOIN authority_book_production book USING(book_run_id)
            JOIN authority_asset_version outcome ON outcome.asset_version_id=accepted.chapter_outcome_asset_version_id
            WHERE book.project_id=%s AND book.book_id=%s AND accepted.acceptance_id=%s
              AND accepted.status='COMMITTED' AND outcome.content->>'accepted_draft_asset_version_id'=%s""",
            [document.project_id, adoption["book_id"], (source or {}).get("acceptance_id", ""), original.asset_version_id])
        if source is None or cursor.fetchone() is None or source["asset_hash"] != original.content_hash:
            _invalid("Edition sources require same-Book committed acceptance provenance")
        sources.append({**mapping, "acceptance_id": source["acceptance_id"],
                        "provenance": prose_origin(cursor, original, adoption["book_id"], depth + 1)})
    native = _native_output(cursor, _document(cursor, document.project_id, revision["revision_id"]),
                            {"book.edition.create", "book.edition.save"})
    return {"kind": "EDITION_MIXED", "adoption": dict(adoption), "unit_sources": sources,
            "author_id": native[1], "revision_id": revision["revision_id"],
            "revision_content_hash": revision["content_hash"], "manifest_digest": revision["manifest_digest"],
            "base_revision_id": revision["base_revision_id"],
            "predecessor_revision_id": revision["predecessor_revision_id"]}
