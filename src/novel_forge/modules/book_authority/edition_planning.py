from __future__ import annotations

from copy import deepcopy
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.book_edition_repositories import BookEditionRepository


EDITION_PLANNING = "book-edition-planning.v1"


def require_edition_slot_mapping(plan: dict[str, Any], target_slots: list[str]) -> None:
    from novel_forge.modules.chapter_authority.realization_composition import compile_realization_contract

    for policy in ("continuous-scene.v1", "scene-core-slots.v1", "EXPLICIT_SKELETON_V1"):
        slots = compile_realization_contract(plan, {}, core_policy=policy)["slots"]
        if [slot["slot_id"] for slot in slots] == target_slots:
            return
    raise KernelError("EDITION_SLOT_MAPPING_DRIFT", "The new plan must realize every submitted Scene slot in frozen order")


def edition_plan_scope(database_url: str, *, book: dict[str, Any], chapter: int, generator: str, frozen_revision_id: str = "") -> dict[str, Any] | None:
    with AuthorityUnitOfWork(database_url) as uow:
        repo = BookEditionRepository(uow.cursor)
        binding = repo.run_binding(book["book_run_id"])
        if binding is None or binding["role"] != "VALIDATION":
            return None
        revision_id = binding["revision_id"]
        if frozen_revision_id:
            if frozen_revision_id != revision_id and not _accepted_revision_for_run(repo, frozen_revision_id, book["book_run_id"]):
                raise KernelError("EDITION_PLANNING_SCOPE_INVALID", "A frozen planning revision must bind this run or its exact accepted manuscript")
            revision_id = frozen_revision_id
        else:
            uow.cursor.execute("SELECT selected_revision_id FROM authority_book_edition_head WHERE book_id=%s", [book["book_id"]])
            selected = uow.cursor.fetchone()
            if selected and _accepted_revision_for_run(repo, str(selected[0]), book["book_run_id"]):
                revision_id = str(selected[0])
        uow.cursor.execute("""SELECT r.revision_id,r.manifest_digest,v.content_hash,v.content FROM authority_book_edition_revision r
            JOIN authority_book_edition e USING(edition_id) JOIN authority_asset_version v ON v.asset_version_id=r.revision_id
            WHERE r.revision_id=%s AND e.project_id=%s AND e.book_id=%s""", [revision_id,book["project_id"],book["book_id"]])
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("EDITION_PLANNING_SOURCE_MISSING", "The run's exact source revision must exist")
        revision = dict(zip(("revision_id", "manifest_digest", "content_hash", "manifest"), row))
        if not frozen_revision_id and any(event["event_kind"] == "REJECTED" for event in repo.events(revision["revision_id"])):
            raise KernelError("EDITION_REJECTED", "A rejected edition cannot produce new execution plans")
        scope = {"contract_version": EDITION_PLANNING, "book_run_id": book["book_run_id"], "revision_id": revision["revision_id"],
                 "revision_content_hash": revision["content_hash"], "manifest_digest": revision["manifest_digest"],
                 "chapter": chapter, "generator": generator}
        if generator == "chapter_plan.generate" and chapter <= len(revision["manifest"]["units"]):
            unit = revision["manifest"]["units"][chapter - 1]
            plan = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=unit["chapter_plan_asset_version_id"])
            if plan.asset_type != "chapter_plan":
                raise KernelError("EDITION_PLAN_SOURCE_INVALID", "Edition units require an exact Chapter execution plan")
            sources = {source["asset_version_id"]: source for source in revision["manifest"]["sources"]}
            source_plans = {}
            for source_range in unit["source_ranges"]:
                source_id = sources[source_range["asset_version_id"]]["chapter_plan_asset_version_id"]
                original_plan = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=source_id)
                source_plans[source_id] = {"asset_version_id": source_id, "content_hash": original_plan.content_hash,
                    "scene_plan": deepcopy(original_plan.content.get("scene_plan") or [])}
            mapping = unit.get("scene_mapping") or []
            if not mapping and unit.get("scene_artifacts"):
                from novel_forge.modules.chapter_authority.realization_composition import compile_realization_contract
                frozen_slots = {slot["slot_id"]: slot for slot in compile_realization_contract(plan.content, {})["slots"]}
                if any(scene["slot_id"] not in frozen_slots for scene in unit["scene_artifacts"]):
                    raise KernelError("EDITION_SCENE_MAPPING_REQUIRED", "New Scene slots require an explicit structural mapping before planning")
                mapping = [{"slot_id": scene["slot_id"], "scene_id": frozen_slots[scene["slot_id"]]["scene_id"]} for scene in unit["scene_artifacts"]]
            scope.update(unit_id=unit["unit_id"], unit_text_hash=unit["text_hash"],
                         source_chapter_plan_asset_version_id=plan.asset_version_id, source_plan_content_hash=plan.content_hash,
                         source_scene_plan=deepcopy(plan.content.get("scene_plan") or plan.content.get("scene_sequence") or []),
                         target_scene_ids=list(dict.fromkeys(scene["scene_id"] for scene in mapping)),
                         target_slot_ids=[scene["slot_id"] for scene in unit.get("scene_artifacts", [])],
                         source_plans=list(source_plans.values()),
                         source_ranges=deepcopy(unit["source_ranges"]))
        return scope


def _accepted_revision_for_run(repo, revision_id: str, book_run_id: str) -> bool:
    return any(event["event_kind"] == "VALIDATED" and
        (event["content"].get("validation_book_run_id") or event["content"].get("source_book_run_id")) == book_run_id
        for event in repo.events(revision_id))


def require_edition_planning_request(database_url: str, *, project_id: str, book_id: str,
                                     scope: dict[str, Any], definition_name: str, idempotency_key: str) -> None:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("""SELECT command_payload->'payload'->'edition_execution' FROM authority_operation
            WHERE project_id=%s AND definition_name=%s AND idempotency_scope='book:story-planning-generation' AND idempotency_key=%s""",
            [project_id, definition_name, idempotency_key])
        frozen = uow.cursor.fetchone()
        if frozen is not None:
            if frozen[0] != scope:
                raise KernelError("EDITION_PLANNING_SOURCE_DRIFT", "Recovery must retain the admitted edition scope")
            return
        uow.cursor.execute("SELECT to_jsonb(book) FROM authority_book_production book WHERE book_run_id=%s AND project_id=%s AND book_id=%s",
            [scope.get("book_run_id"), project_id, book_id])
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("EDITION_PLANNING_SCOPE_INVALID", "Planning must use a run of this exact Book")
        book = row[0]
    expected = edition_plan_scope(database_url, book=book, chapter=int(scope.get("chapter") or 0), generator=str(scope.get("generator") or ""))
    if scope != expected:
        raise KernelError("EDITION_PLANNING_CURRENT_REVISION_REQUIRED", "A new task must freeze the selected manuscript or its pending validation candidate")


def validate_edition_plan_scope(database_url: str, *, project_id: str, book_id: str, scope: dict[str, Any]) -> list[dict[str, str]]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT to_jsonb(book) FROM authority_book_production book WHERE book_run_id=%s AND project_id=%s AND book_id=%s",
                           [scope.get("book_run_id"), project_id, book_id])
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("EDITION_PLANNING_SCOPE_INVALID", "Edition planning must reference its exact native Book run")
        book = row[0]
    expected = edition_plan_scope(database_url, book=book, chapter=int(scope.get("chapter") or 0), generator=str(scope.get("generator") or ""), frozen_revision_id=str(scope.get("revision_id") or ""))
    if expected != scope or scope["contract_version"] != EDITION_PLANNING:
        raise KernelError("EDITION_PLANNING_SOURCE_DRIFT", "Edition execution planning must retain its exact source manifest and plan")
    refs = [{"asset_version_id": scope["revision_id"], "content_hash": scope["revision_content_hash"]}]
    if scope.get("source_chapter_plan_asset_version_id"):
        refs.append({"asset_version_id": scope["source_chapter_plan_asset_version_id"], "content_hash": scope["source_plan_content_hash"]})
    for plan in scope.get("source_plans", []):
        reference = {key: plan[key] for key in ("asset_version_id", "content_hash")}
        if reference not in refs:
            refs.append(reference)
    return refs


def require_edition_execution_plan(database_url: str, *, project_id: str, book_id: str, book_run_id: str,
                                   execution_plan_version_id: str, revision_id: str, chapter: int, source_plan_version_id: str) -> None:
    with AuthorityUnitOfWork(database_url) as uow:
        plan = uow.repositories.asset_documents.require(project_id=project_id, asset_version_id=execution_plan_version_id)
        scope = (plan.content.get("constraint_envelope") or {}).get("edition_execution")
        if (not isinstance(scope, dict) or scope.get("book_run_id") != book_run_id or scope.get("revision_id") != revision_id
            or scope.get("chapter") != chapter or scope.get("source_chapter_plan_asset_version_id") != source_plan_version_id):
            raise KernelError("EDITION_PLAN_DRIFT", "The new execution plan must explicitly bind this exact edited unit and original plan")
    validate_edition_plan_scope(database_url, project_id=project_id, book_id=book_id, scope=scope)
