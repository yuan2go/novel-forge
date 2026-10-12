from __future__ import annotations

from dataclasses import replace
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .contracts import ChapterNode

ROOT_VERSION = "3.10.0-working-revision.v1"
CONTRACT = "chapter-working-revision.v1"
NODES = (ChapterNode.REVIEW, ChapterNode.REVISION, ChapterNode.REREVIEW, ChapterNode.BEST_CANDIDATE)


def working_review_window(request, draft, context, prior=None):
    from novel_forge.modules.chapter_authority.author_editor import source_draft_content
    from novel_forge.modules.review.prose_window import WORKING_WINDOW_POLICY, digest, freeze_review_window, validate_window
    from .contracts import resolve_stage_context_token_budget
    from .provider_views import build_provider_context_view
    binding = request.command["preparation_report"]["working_revision"]
    with AuthorityUnitOfWork(request.database_url) as uow:
        uow.cursor.execute("SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s", [request.command["chapter_root_operation_id"]])
        root = uow.cursor.fetchone()[0]
        book, _ = require_working_revision_frontier(uow, root=root)
        if prior and prior.get("cross_chapter_window"):
            window = prior["cross_chapter_window"]
            validate_window(window)
            return window
        scope = {key: book[key] for key in ("project_id", "workspace_id", "book_id", "book_run_id")}
        sources = []
        for row in binding["previous_sources"]:
            document = uow.repositories.asset_documents.require(project_id=request.project_id, asset_version_id=row["asset_version_id"])
            if document.content_hash != row["content_hash"]:
                raise KernelError("MANUSCRIPT_REVISION_SOURCE_STALE", "Earlier source content must match its frozen version")
            text = source_draft_content(document)["text"]
            from novel_forge.modules.review.diagnostics import prose_hash
            sources.append({**scope, "chapter_number": row["chapter"], "asset_version_id": document.asset_version_id,
                "content_hash": document.content_hash, "text_hash": prose_hash(text), "text": text,
                "source_status": "SELECTED_WORKING_PROSE"})
    budget = resolve_stage_context_token_budget(request.command, "review")
    snapshot = {**scope, "contract_version": "selected-working-prose-snapshot.v1",
        "target_chapter_number": request.command["chapter"], "working_through_chapter": request.command["chapter"] - 1,
        "accepted_through_chapter": binding["accepted_through_chapter"], "sources": sources,
        "source_isolation": "SELECTED_PROSE_NO_CANON_AUTHORITY",
        "window_policy": {"version": WORKING_WINDOW_POLICY,
            "maximum_previous_chapters": max(1, request.command["chapter"] - 1), "source_token_budget": budget}}
    snapshot["snapshot_hash"] = digest(snapshot)
    return freeze_review_window(snapshot, candidate_id=draft.asset_version_id, text=draft.content["text"],
        context_token_budget=budget, protected_context={"current_context_asset_version_id": context.asset_version_id,
            "current_context_content_hash": context.content_hash, "authority": "FROZEN_REQUIREMENTS_AND_SELECTED_PROSE"},
        required_context=build_provider_context_view("review", context.content,
            {"creative_baseline": draft.content.get("creative_baseline"), "cross_chapter_window": {"source_isolation": "SELECTED_PROSE_NO_CANON_AUTHORITY"}},
            writer_projection_version="accepted-writer-history.v2"))


def working_revision_definition(*, application_build_id: str, commit_sha: str) -> dict[str, Any]:
    from .definitions import chapter_root_operation_definition
    definition = chapter_root_operation_definition(application_build_id=application_build_id,
        commit_sha=commit_sha, model_effects_required=True, coordinated_contract=True)
    definition["definition_version"] = ROOT_VERSION
    from copy import deepcopy
    text = {"type": "string", "minLength": 1}
    hash_value = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
    def obj(fields):
        return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}
    pointer = obj({"asset_version_id": text, "content_hash": hash_value})
    binding_schema = obj({"contract_version": {"const": CONTRACT}, "book_run_id": text,
        "source_asset_version_id": text, "source_content_hash": hash_value,
        "expected_book_version": {"type": "integer", "minimum": 0}, "reason": text,
        "author_choice": {"const": "NOT_GRANTED"}, "formal_acceptance": {"const": "NOT_GRANTED"},
        "source_inputs": obj({key: deepcopy(pointer) for key in ("draft", "context", "plan")}),
        "previous_sources": {"type": "array", "uniqueItems": True,
            "items": obj({"chapter": {"type": "integer", "minimum": 1}, **pointer["properties"]})},
        "accepted_through_chapter": {"type": "integer", "minimum": 0}})
    for key in ("command_schema", "input_contract"):
        definition[key] = deepcopy(definition[key])
        definition[key]["properties"]["preparation_report"] = {"type": "object",
            "properties": {"working_revision": deepcopy(binding_schema)}, "required": ["working_revision"]}
    definition["policy"].update(expected_saga_steps=len(NODES), working_revision_contract=CONTRACT)
    definition["completion_contract"]["required_child_operations"] = [
        {"definition_name": node.definition_name, "allowed_states": ["SUCCEEDED"]} for node in NODES]
    return definition


def working_revision_status(database_url, *, project_id, book_run_id, root_operation_id, principal):
    principal.require("chapter.authority.query", project_id)
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s AND project_id=%s", [root_operation_id, project_id])
        row = uow.cursor.fetchone()
        root = row[0] if row else {}
        binding = (root.get("command_payload", {}).get("preparation_report") or {}).get("working_revision") or {}
        if root.get("definition_version") != ROOT_VERSION or binding.get("book_run_id") != book_run_id:
            raise KernelError("MANUSCRIPT_REVISION_SCOPE_INVALID", "Revision status requires this exact Book request")
        uow.cursor.execute("""SELECT child.operation_id,child.definition_name,child.status,
            output.asset_version_id,output.output_key FROM authority_operation child
            LEFT JOIN authority_operation_output_asset output ON output.operation_id=child.operation_id AND output.role='primary'
            WHERE child.root_operation_id=%s AND child.operation_id<>%s ORDER BY child.created_at""", [root_operation_id, root_operation_id])
        stages = [dict(zip(("operation_id", "definition_name", "status", "asset_version_id", "output_key"), row)) for row in uow.cursor.fetchall()]
        return {"contract_version": CONTRACT, "root_operation_id": root_operation_id, "book_run_id": book_run_id,
            "chapter": root["command_payload"]["chapter"], "status": root["status"], "stages": stages,
            "source_asset_version_id": binding["source_asset_version_id"],
            "author_selection": "NOT_GRANTED", "formal_acceptance": "NOT_GRANTED"}


def require_working_revision_frontier(uow, *, root: dict[str, Any], book_run_id: str | None = None):
    from novel_forge.modules.book_authority.manuscript import AUTHOR_WORKFLOW, effective_workflow, selected_source
    binding = (root.get("command_payload", {}).get("preparation_report") or {}).get("working_revision")
    if (root.get("definition_name") != "chapter.slice.run" or root.get("definition_version") != ROOT_VERSION
            or root.get("definition_snapshot", {}).get("policy", {}).get("working_revision_contract") != CONTRACT
            or not isinstance(binding, dict) or binding.get("contract_version") != CONTRACT
            or book_run_id is not None and binding.get("book_run_id") != book_run_id):
        raise KernelError("MANUSCRIPT_REVISION_SCOPE_INVALID", "Require the exact native working-revision contract")
    uow.cursor.execute("""SELECT to_jsonb(b), EXISTS(SELECT 1 FROM authority_story_creation_cancellation c
        WHERE c.project_id=b.project_id AND b.stable_idempotency_key=c.formation_run_id || ':production')
        FROM authority_book_production b WHERE b.book_run_id=%s AND b.project_id=%s FOR UPDATE""",
        [binding.get("book_run_id"), root["project_id"]])
    row = uow.cursor.fetchone()
    book = row[0] if row else None
    chapter = root["command_payload"].get("chapter")
    if (not book or row[1] or book["workspace_id"] != root["workspace_id"]
            or book["book_id"] != root["command_payload"].get("book_id")
            or effective_workflow(uow.cursor, book) != AUTHOR_WORKFLOW
            or book["state"] in {"PAUSED", "CANCELLED", "ABORTED"}
            or type(chapter) is not int or not book["accepted_through_chapter"] < chapter <= book["current_chapter"]):
        raise KernelError("MANUSCRIPT_REVISION_FRONTIER_STALE", "Revision requires this live unaccepted working chapter without cancellation")
    source = selected_source(uow, book, chapter)
    if (source.asset_version_id != binding.get("source_asset_version_id")
            or source.content_hash != binding.get("source_content_hash")):
        raise KernelError("MANUSCRIPT_REVISION_SOURCE_STALE", "The selected source changed; preserve this revision as an older candidate")
    for previous in binding.get("previous_sources", []):
        selected = selected_source(uow, book, previous["chapter"])
        if selected.asset_version_id != previous["asset_version_id"] or selected.content_hash != previous["content_hash"]:
            raise KernelError("MANUSCRIPT_REVISION_SOURCE_STALE", "The selected earlier prose changed; retain the frozen result without propagating it")
    refs = {item["asset_version_id"]: item["content_hash"] for item in root.get("input_asset_snapshot", [])}
    inputs = binding.get("source_inputs") or {}
    if (set(inputs) != {"draft", "context", "plan"}
            or inputs["draft"] != {"asset_version_id": source.asset_version_id, "content_hash": source.content_hash}
            or any(refs.get(pointer.get("asset_version_id")) != pointer.get("content_hash") for pointer in inputs.values())):
        raise KernelError("MANUSCRIPT_REVISION_SCOPE_INVALID", "Revision must retain its exact frozen source inputs")
    if any(refs.get(row["asset_version_id"]) != row["content_hash"] for row in binding.get("previous_sources", [])):
        raise KernelError("MANUSCRIPT_REVISION_SCOPE_INVALID", "Earlier prose must retain its exact Root input binding")
    return book, source


def admit_working_revision(app, *, authority, book_run_id: str, chapter: int,
                          expected_version: int, idempotency_key: str, reason: str, principal):
    from novel_forge.modules.book_authority.manuscript import AUTHOR_WORKFLOW, effective_workflow, selected_source
    from novel_forge.modules.chapter_authority.orchestrator import (
        ChapterSagaAdmission, _command, _transition_root_to_executing,
    )
    from novel_forge.modules.command_kernel.operation_graph import GraphCommandContext, start_saga
    from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
    from .definitions import CHAPTER_SLICE_ROOT_HANDLER_KEY, chapter_operation_definitions
    from .scheduler import ChapterAuthorityScheduler
    scheduler = ChapterAuthorityScheduler(app.database_url, registry=app.registry,
        object_store_adapter=app._object_store_adapter, worker_id=app.worker_id,
        permissions=principal.permissions, model_effect_adapter=app._model_port.adapter)
    book = authority.require(book_run_id)
    principal.require("chapter.authority.execute", book["project_id"])
    principal.require("book.authority.execute", book["project_id"])
    if not idempotency_key.strip() or not reason.strip() or type(chapter) is not int or chapter < 1:
        raise ValueError("Revision requires an exact chapter, request identity and revision purpose")
    root_key = "working-revision:" + idempotency_key
    existing_root = None
    with AuthorityUnitOfWork(app.database_url) as uow:
        uow.cursor.execute("""SELECT to_jsonb(o) FROM authority_operation o WHERE project_id=%s
            AND idempotency_scope='project:chapter-slice' AND idempotency_key=%s""", [book["project_id"], root_key])
        existing = uow.cursor.fetchone()
        if existing:
            root = existing[0]
            existing_root = root
            binding = (root["command_payload"].get("preparation_report") or {}).get("working_revision") or {}
            if (root["definition_version"] != ROOT_VERSION or root["actor_id"] != principal.principal_id
                    or binding.get("book_run_id") != book_run_id or binding.get("expected_book_version") != expected_version
                    or root["command_payload"].get("chapter") != chapter or binding.get("reason") != reason):
                raise KernelError("MANUSCRIPT_REVISION_REQUEST_DRIFT", "Replay the original working-revision identity and purpose")
            request = scheduler._request_from_root(root)
            if root["status"] in {"SUCCEEDED", "CANCELLED", "FAILED_FINAL", "DEAD_LETTER"}:
                uow.cursor.execute("SELECT saga_id FROM authority_saga WHERE root_operation_id=%s", [root["operation_id"]])
                saga = uow.cursor.fetchone()
                return ChapterSagaAdmission(root["operation_id"], str(saga[0]) if saga else "", "", root["status"], True)
        else:
            uow.cursor.execute("SELECT to_jsonb(b) FROM authority_book_production b WHERE book_run_id=%s FOR UPDATE", [book_run_id])
            book = uow.cursor.fetchone()[0]
            if (book["version"] != expected_version or effective_workflow(uow.cursor, book) != AUTHOR_WORKFLOW
                    or book["state"] != "READY" or book.get("active_chapter_request_id")
                    or not book["accepted_through_chapter"] < chapter <= book["current_chapter"]):
                raise KernelError("MANUSCRIPT_REVISION_CHECKPOINT_REQUIRED", "Revision admission requires the exact delivered idle work checkpoint")
            source = selected_source(uow, book, chapter)
            native_source_id = (source.content.get("originating_draft_asset_version_id")
                if source.asset_type == "author_edit_candidate" else source.asset_version_id)
            uow.cursor.execute("""SELECT to_jsonb(root) FROM authority_operation_output_asset output
                JOIN authority_operation child USING(operation_id)
                JOIN authority_operation root ON root.operation_id=child.root_operation_id
                WHERE output.asset_version_id=%s AND child.project_id=%s AND output.role='primary'""",
                [native_source_id, book["project_id"]])
            rows = uow.cursor.fetchall()
            if len(rows) != 1:
                raise KernelError("MANUSCRIPT_REVISION_NATIVE_SOURCE_REQUIRED", "Require one native current manuscript source")
            original_root = rows[0][0]
            original = scheduler._request_from_root(original_root)
            inherited = (original.preparation_report or {}).get("working_revision")
            if inherited:
                context_pointer = inherited["source_inputs"]["context"]
            else:
                uow.cursor.execute("""SELECT v.asset_version_id,v.content_hash FROM authority_operation child
                    JOIN authority_operation_output_asset output USING(operation_id)
                    JOIN authority_asset_version v USING(asset_version_id)
                    WHERE child.root_operation_id=%s AND child.project_id=%s
                    AND output.output_key='chapter.context' AND output.role='primary' AND child.status='SUCCEEDED'""",
                    [original_root["operation_id"], book["project_id"]])
                context_rows = uow.cursor.fetchall()
                if len(context_rows) != 1:
                    raise KernelError("MANUSCRIPT_REVISION_CONTEXT_REQUIRED", "Require the original governed Context rather than a reconstructed summary")
                context_pointer = dict(zip(("asset_version_id", "content_hash"), context_rows[0]))
            binding = {"contract_version": CONTRACT, "book_run_id": book_run_id,
                "source_asset_version_id": source.asset_version_id, "source_content_hash": source.content_hash,
                "expected_book_version": expected_version, "reason": reason,
                "author_choice": "NOT_GRANTED", "formal_acceptance": "NOT_GRANTED",
                "source_inputs": {"draft": {"asset_version_id": source.asset_version_id, "content_hash": source.content_hash},
                    "context": context_pointer, "plan": {"asset_version_id": original.chapter_plan_asset_version_id,
                        "content_hash": original.chapter_plan_content_hash}}}
            binding["previous_sources"] = []
            for number in range(1, chapter):
                previous = selected_source(uow, book, number)
                binding["previous_sources"].append({"chapter": number, "asset_version_id": previous.asset_version_id,
                    "content_hash": previous.content_hash})
            binding["accepted_through_chapter"] = book["accepted_through_chapter"]
            preparation = {**dict(original.preparation_report or {}), "working_revision": binding}
            for field in ("author_draft_adoption", "author_book_replacement"):
                preparation.pop(field, None)
            request = replace(original, actor_id=principal.principal_id, idempotency_key=root_key,
                application_build_id=app.application_build_id, commit_sha=app.commit_sha,
                preparation_report=preparation, trace_id=root_key, correlation_id=book["root_operation_id"])
        uow.repositories.definitions.register(working_revision_definition(
            application_build_id=app.application_build_id, commit_sha=app.commit_sha))
        for definition in chapter_operation_definitions(application_build_id=app.application_build_id,
                commit_sha=app.commit_sha, model_effects_required=True, coordinated_contract=True):
            uow.repositories.definitions.register(definition)
        uow.commit()
    admission = AdmissionContext(actor_id=principal.principal_id, permissions=principal.permissions,
        available_handlers=app.registry.available_handler_keys | frozenset({CHAPTER_SLICE_ROOT_HANDLER_KEY}),
        application_build_id=app.application_build_id, commit_sha=app.commit_sha)
    frozen = (request.preparation_report or {})["working_revision"]
    root = {**existing_root, "replayed": True} if existing_root is not None else admit_command(app.database_url, _command(request, definition_name="chapter.slice.run",
        definition_version=ROOT_VERSION, idempotency_key=root_key, input_assets=[*frozen["source_inputs"].values(),
            *({"asset_version_id": row["asset_version_id"], "content_hash": row["content_hash"]} for row in frozen["previous_sources"])]), context=admission)
    root_id = str(root["operation_id"])
    with AuthorityUnitOfWork(app.database_url) as uow:
        uow.cursor.execute("SELECT status FROM authority_operation WHERE operation_id=%s", [root_id])
        state = uow.cursor.fetchone()[0]
    if state == "ADMITTED":
        _transition_root_to_executing(app.database_url, request, root_id)
    graph = GraphCommandContext(request.project_id, principal.principal_id, request.trace_id, request.correlation_id)
    saga = str(start_saga(app.database_url, graph, root_operation_id=root_id)["saga_id"])
    actual_root, _, children = scheduler._graph_state(request.project_id, root_id)
    with AuthorityUnitOfWork(app.database_url) as uow:
        require_working_revision_frontier(uow, root=actual_root)
    first = children.get(ChapterNode.REVIEW)
    if first is None:
        first = scheduler._admit_node(request=request, root=actual_root, saga_id=saga,
            children=children, node=ChapterNode.REVIEW, dependency_operation_ids=[], timeline_ordinal=1)
    return ChapterSagaAdmission(root_id, saga, str(first["operation_id"]), "ACCEPTED", bool(root["replayed"]))
