from __future__ import annotations

from copy import deepcopy
from typing import Any

from novel_forge.modules.book_authority.editions import require_manifest
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.book_edition_repositories import BookEditionRepository


EDITION_ADOPTION = "book-edition-draft-adoption.v1"


def edition_dispatch_binding(database_url: str, *, book: dict[str, Any], chapter: int) -> dict[str, Any] | None:
    with AuthorityUnitOfWork(database_url) as uow:
        return edition_dispatch_binding_in_uow(uow, book=book, chapter=chapter)


def edition_dispatch_binding_in_uow(uow, *, book: dict[str, Any], chapter: int) -> dict[str, Any] | None:
    repo = BookEditionRepository(uow.cursor)
    head = repo.head(book["book_id"], for_update=False)
    binding = repo.run_binding(book["book_run_id"])
    if not head["version"]:
        return None
    selected = repo.revision(project_id=book["project_id"], revision_id=head["selected_revision_id"], book_id=book["book_id"], for_update=False)
    selected_proofs = [event["content"] for event in repo.events(selected["revision_id"]) if event["event_kind"] == "VALIDATED"]
    selected_run = (selected_proofs[-1].get("validation_book_run_id") or selected_proofs[-1].get("source_book_run_id")) if selected_proofs else ""
    if selected_run == book["book_run_id"]:
        return {"book_run_id": book["book_run_id"], "revision_id": selected["revision_id"], "role": "SOURCE",
                "manifest_digest": selected["manifest_digest"], "unit_count": len(selected["manifest"]["units"])}
    if binding is None:
        raise KernelError("EDITION_RUN_BINDING_REQUIRED", "Bind production to its exact manuscript edition before a new task")
    revision = repo.revision(project_id=book["project_id"], revision_id=binding["revision_id"], book_id=book["book_id"], for_update=False)
    require_manifest(revision["manifest"])
    if head["selected_revision_id"] != binding["revision_id"]:
        validation = binding["role"] == "VALIDATION" and chapter <= len(revision["manifest"]["units"])
        rejected = any(event["event_kind"] == "REJECTED" for event in repo.events(binding["revision_id"]))
        if not validation or rejected:
            raise KernelError("EDITION_RUN_NOT_SELECTED", "Old tasks can settle in their frozen edition; new production requires the selected edition")
    return {**binding, "manifest_digest": revision["manifest_digest"], "unit_count": len(revision["manifest"]["units"])}


def freeze_edition_adoption(database_url: str, *, project_id: str, workspace_id: str, book_id: str,
                            chapter: int, revision_id: str, book_run_id: str, principal, chapter_request=None) -> dict[str, Any]:
    principal.require("chapter.authority.execute", project_id)
    with AuthorityUnitOfWork(database_url) as uow:
        repo = BookEditionRepository(uow.cursor)
        book = repo.book(project_id=project_id, workspace_id=workspace_id, book_run_id=book_run_id, for_update=False)
        if book["book_id"] != book_id:
            raise KernelError("EDITION_ADOPTION_SCOPE_INVALID", "Edition and validation task must share a Book")
        binding = repo.run_binding(book_run_id)
        if binding is None or binding["revision_id"] != revision_id or binding["role"] != "VALIDATION":
            raise KernelError("EDITION_ADOPTION_UNBOUND", "The validation run must freeze this exact revision before dispatch")
        revision = repo.revision(project_id=project_id, revision_id=revision_id, book_id=book_id, for_update=False)
        if not 1 <= chapter <= len(revision["manifest"]["units"]):
            raise KernelError("EDITION_ADOPTION_POSITION_INVALID", "No edition unit maps to this production position")
        unit = revision["manifest"]["units"][chapter - 1]
        rejected = any(event["event_kind"] == "REJECTED" for event in repo.events(revision_id))
        current = revision["edition"]["current_revision_id"] == revision_id
        frozen = {"contract_version": EDITION_ADOPTION, "project_id": project_id, "workspace_id": workspace_id,
                "book_id": book_id, "book_run_id": book_run_id, "chapter": chapter,
                "revision_id": revision_id, "revision_content_hash": revision["content_hash"],
                "manifest_digest": revision["manifest_digest"], "unit_id": unit["unit_id"], "text_hash": unit["text_hash"],
                "source_chapter_plan_asset_version_id": unit["chapter_plan_asset_version_id"],
                "authority": "BOOK_EDITION_CANDIDATE", "book_acceptance": "NOT_GRANTED"}
    reserved = False
    if chapter_request is not None:
        from .chapter_dispatch import require_reserved_edition_adoption
        reserved = require_reserved_edition_adoption(database_url, request=chapter_request, adoption=frozen)
    if not current and not reserved:
        raise KernelError("EDITION_ADOPTION_STALE", "New adoption must use the current candidate revision")
    if rejected and not reserved:
        raise KernelError("EDITION_ADOPTION_REJECTED", "A rejected edition cannot start another validation task")
    return frozen


def edition_adopted_draft(request, adoption: dict[str, Any]):
    from novel_forge.modules.chapter_authority.contracts import ChapterAuxiliaryOutput, ChapterHandlerOutput, ChapterNode
    from novel_forge.modules.chapter_authority.craft_execution import require_craft_delivery
    from novel_forge.modules.chapter_authority.domain_handlers import normalize_draft_result

    with AuthorityUnitOfWork(request.database_url) as uow:
        repo = BookEditionRepository(uow.cursor)
        binding = repo.run_binding(adoption["book_run_id"])
        revision = repo.revision(project_id=request.project_id, revision_id=adoption["revision_id"], book_id=request.command["book_id"], for_update=False)
        if (binding is None or binding["revision_id"] != revision["revision_id"] or binding["role"] != "VALIDATION"
            or revision["content_hash"] != adoption["revision_content_hash"] or revision["manifest_digest"] != adoption["manifest_digest"]
            or adoption["workspace_id"] != request.workspace_id or adoption["project_id"] != request.project_id
            or adoption["book_id"] != request.command["book_id"] or adoption["chapter"] != int(request.command["chapter"])):
            raise KernelError("EDITION_ADOPTION_DRIFT", "Frozen edition adoption must retain exact scope and immutable content")
        unit = revision["manifest"]["units"][adoption["chapter"] - 1]
        if unit["unit_id"] != adoption["unit_id"] or unit["text_hash"] != adoption["text_hash"]:
            raise KernelError("EDITION_ADOPTION_DRIFT", "Stable unit identity and exact text must survive recovery")
    plan, context = request.require_input("chapter_plan"), request.require_input("context_bundle")
    intent, memo = request.require_input("chapter_execution_intent"), request.require_input("chapter_memo")
    from .edition_planning import require_edition_execution_plan
    require_edition_execution_plan(request.database_url, project_id=request.project_id, book_id=request.command["book_id"],
        book_run_id=adoption["book_run_id"], execution_plan_version_id=plan.content["source_chapter_plan_asset_version_id"],
        revision_id=adoption["revision_id"], chapter=adoption["chapter"], source_plan_version_id=adoption["source_chapter_plan_asset_version_id"])
    require_craft_delivery(plan=plan.content, intent=intent.content, memo=memo.content, context=context.content)
    draft = {"chapter": adoption["chapter"], "title": unit["title"], "text": unit["text"],
             "scene_artifacts": deepcopy(unit["scene_artifacts"])}
    if unit.get("scene_separators") is not None:
        draft["scene_separators"] = deepcopy(unit["scene_separators"])
    content = normalize_draft_result(plan=plan.content, context_asset_version_id=context.asset_version_id,
                                    context_content_hash=context.content_hash, context_content=context.content,
                                    result=draft, provider_evidence={"source": "AUTHOR_EDITION_INPUT", "model_call": "NOT_APPLICABLE"})
    if content["text"] != unit["text"]:
        raise KernelError("EDITION_TEXT_DRIFT", "Edition validation cannot silently replace submitted prose")
    content["author_draft_adoption"] = adoption
    content["creative_execution"] = {"memo_asset_version_id": memo.asset_version_id, "memo_content_hash": memo.content_hash,
                                    "memo_fingerprint": memo.content.get("memo_fingerprint"), "intent_asset_version_id": intent.asset_version_id,
                                    "guidance": dict(memo.content.get("creative_guidance") or {}),
                                    "scene_directives": list(memo.content.get("scene_directives") or []), "authority": "CREATIVE_SUGGESTION_ONLY"}
    return ChapterHandlerOutput(asset_type=ChapterNode.DRAFT.asset_type, output_key=ChapterNode.DRAFT.output_key, role="primary", content=content,
                                auxiliary_outputs=(ChapterAuxiliaryOutput(asset_type="author_draft_adoption_evidence",
                                    output_key="chapter.draft.author_adoption", role="completion_evidence",
                                    content={**adoption, "semantic_review": "REQUIRED"}, reference_asset_version_ids=(revision["revision_id"],)),))


def inherit_unchanged_prefix(uow, *, book_run_id: str, revision: dict[str, Any], operation_id: str) -> dict[str, Any] | None:
    from psycopg.types.json import Jsonb
    from novel_forge.modules.book_authority.completion_domain import completion_digest

    manifest = revision["manifest"]
    require_manifest(manifest)
    count = int(manifest.get("impact", {}).get("earliest_affected_position", 1)) - 1
    if count == 0:
        return None
    source_run = manifest["book_run_id"]
    uow.cursor.execute("""WITH RECURSIVE lineage(run_id,depth) AS (
        SELECT %s::text,0 UNION ALL
        SELECT prefix.source_book_run_id,lineage.depth+1 FROM lineage
        JOIN authority_book_edition_prefix prefix ON prefix.book_run_id=lineage.run_id
        WHERE lineage.depth<64) SELECT max(depth) FROM lineage""", [source_run])
    if int(uow.cursor.fetchone()[0]) >= 64:
        raise KernelError("EDITION_PREFIX_LINEAGE_LIMIT", "Prefix reuse must fit the effective-source resolver bound; validate a fresh prefix before another inherited edition")
    source_by_acceptance = {source["acceptance_id"]: source for source in manifest["sources"]}
    uow.cursor.execute("SELECT * FROM authority_book_acceptance_lineage(%s) WHERE chapter_number<=%s ORDER BY chapter_number", [source_run, count])
    names = [column.name for column in uow.cursor.description]
    acceptances = [dict(zip(names, row)) for row in uow.cursor.fetchall()]
    if len(acceptances) != count or [row["chapter_number"] for row in acceptances] != list(range(1, count + 1)):
        raise KernelError("EDITION_PREFIX_SOURCE_INCOMPLETE", "Every inherited position must retain its original committed acceptance")
    proofs = []
    for unit, accepted in zip(manifest["units"][:count], acceptances, strict=True):
        source = source_by_acceptance.get(accepted["acceptance_id"])
        if (source is None or unit["source_acceptance_ids"] != [accepted["acceptance_id"]]
            or unit["text"] != source["text"] or unit["chapter_plan_asset_version_id"] != source["chapter_plan_asset_version_id"]
            or unit["scene_artifacts"] != source.get("scene_artifacts") or unit.get("scene_separators") != source.get("scene_separators")):
            raise KernelError("EDITION_PREFIX_NOT_IDENTICAL", "Inherited prefix must preserve exact prose, scenes, order and approved plan")
        references = {"outcome_asset_version_id": accepted["chapter_outcome_asset_version_id"],
                      "story_state_asset_version_id": accepted["story_state_asset_version_id"],
                      "canon_snapshot_asset_version_id": accepted["canon_snapshot_asset_version_id"],
                      "projection_set_id": accepted["longform_projection_set_id"]}
        if any(source[key] != value for key, value in references.items()):
            raise KernelError("EDITION_PREFIX_FACT_DRIFT", "Inherited facts must match the source manifest's exact acceptance evidence")
        versions = {}
        for key, version_id in references.items():
            if key == "projection_set_id":
                continue
            document = uow.repositories.asset_documents.require(project_id=manifest["project_id"], asset_version_id=version_id)
            versions[key] = {"asset_version_id": version_id, "content_hash": document.content_hash}
        uow.cursor.execute("SELECT projection_hash,status FROM authority_book_narrative_projection_set WHERE projection_set_id=%s AND acceptance_id=%s", [references["projection_set_id"], accepted["acceptance_id"]])
        projection = uow.cursor.fetchone()
        if projection is None or projection[1] != "COMPLETE":
            raise KernelError("EDITION_PREFIX_PROJECTION_INCOMPLETE", "Only complete accepted projections can anchor an inherited prefix")
        proofs.append({"unit_id": unit["unit_id"], "position": accepted["chapter_number"], "acceptance_id": accepted["acceptance_id"],
                       "source_book_run_id": accepted["book_run_id"], "text_hash": unit["text_hash"],
                       "asset_version_id": source["asset_version_id"], "asset_hash": source["asset_hash"],
                       **versions, "projection_set_id": references["projection_set_id"], "projection_hash": projection[0]})
    content = {"contract_version": "book-edition-prefix-inheritance.v1", "revision_id": revision["revision_id"],
               "manifest_digest": revision["manifest_digest"], "source_book_run_id": source_run, "book_run_id": book_run_id,
               "through_chapter": count, "accepted_sources": proofs,
               "authority": "REUSE_ORIGINAL_ACCEPTANCE_NO_NEW_ACCEPTANCE", "publication_authorized": False}
    content["proof_digest"] = completion_digest(content)
    frontier = acceptances[-1]
    uow.cursor.execute("""INSERT INTO authority_book_edition_prefix(book_run_id,revision_id,source_book_run_id,through_chapter,
        source_acceptance_id,content,created_by_operation_id) VALUES(%s,%s,%s,%s,%s,%s,%s)""",
        [book_run_id, revision["revision_id"], source_run, count, frontier["acceptance_id"], Jsonb(content), operation_id])
    uow.cursor.execute("""UPDATE authority_book_production SET accepted_through_chapter=%s,current_chapter=%s,last_chapter_outcome_version_id=%s,
        active_story_state_version_id=%s,active_canon_snapshot_version_id=%s,active_longform_projection_set_id=%s,
        version=version+1 WHERE book_run_id=%s AND accepted_through_chapter=0 AND active_chapter_request_id IS NULL""",
        [count, count, frontier["chapter_outcome_asset_version_id"], frontier["story_state_asset_version_id"],
         frontier["canon_snapshot_asset_version_id"], frontier["longform_projection_set_id"], book_run_id])
    if uow.cursor.rowcount != 1:
        raise KernelError("EDITION_PREFIX_FRONTIER_CONFLICT", "Prefix inheritance must commit before the target run starts any Chapter")
    return content


def edition_start_inputs(database_url: str, *, project_id: str, book_id: str, revision_id: str) -> tuple[str, ...]:
    with AuthorityUnitOfWork(database_url) as uow:
        revision = BookEditionRepository(uow.cursor).revision(project_id=project_id, book_id=book_id, revision_id=revision_id, for_update=False)
        require_manifest(revision["manifest"])
        count = int(revision["manifest"].get("impact", {}).get("earliest_affected_position", 1)) - 1
        inherited_ids = {identity for unit in revision["manifest"]["units"][:count] for identity in unit["source_acceptance_ids"]}
        refs = [revision_id]
        for source in revision["manifest"]["sources"]:
            if source["acceptance_id"] in inherited_ids:
                refs.extend(source[key] for key in ("asset_version_id", "outcome_asset_version_id", "story_state_asset_version_id", "canon_snapshot_asset_version_id"))
        return tuple(dict.fromkeys(refs))
