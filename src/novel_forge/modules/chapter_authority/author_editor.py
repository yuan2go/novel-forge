from __future__ import annotations

from dataclasses import asdict
from difflib import SequenceMatcher
import hashlib
from typing import Any
from uuid import uuid4

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import AdmissionContext, execute_transaction_command
from novel_forge.storage.authority_asset_store import AuthorityAssetDocument
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

EDITOR_CONTRACT = "chapter-author-edit.v1"
EDITOR_HANDLER = "novel_forge.chapter_authority.author_edit"
EDITOR_ACTIONS = ("save", "accept", "reject")


def text_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def edit_map(before: str, after: str) -> list[dict[str, Any]]:
    return [{"start": start, "end": end, "after_start": new_start, "after_end": new_end,
             "before": before[start:end], "after": after[new_start:new_end]}
            for action, start, end, new_start, new_end in SequenceMatcher(None, before, after, autojunk=False).get_opcodes()
            if action != "equal"]


def reconcile_author_scenes(source: dict[str, Any], text: str, supplied: list[dict[str, Any]] | None = None,
                            separators: list[str] | None = None) -> list[dict[str, Any]]:
    from .realization_composition import integrate_realization, realization_separators, serialize_realization
    enforce_voice = source.get("author_workflow") != {"version": "author-workflow.v1", "mode": "AUTHOR_FIRST", "deep_review": False}
    artifacts = source.get("scene_artifacts") or []
    before = str(source.get("text") or "")
    original_joins = realization_separators(artifacts, source.get("scene_separators"))
    joins = realization_separators(artifacts, separators if separators is not None else source.get("scene_separators"))
    if artifacts and serialize_realization(artifacts, original_joins) != before:
        raise KernelError("AUTHOR_SCENE_BASE_CONFLICT", "Source Scene artifacts disagree with exact source text")
    if supplied is not None:
        if not artifacts or not isinstance(supplied, list) or len(supplied) != len(artifacts):
            raise KernelError("AUTHOR_SCENE_SCOPE_CONFLICT", "Scene creation or removal requires native Plan Change")
        for original, item in zip(artifacts, supplied, strict=True):
            if (not isinstance(item, dict) or set(item) != set(original)
                or any(item[key] != value for key, value in original.items() if key not in {"text", "used_fact_ids"})):
                raise KernelError("AUTHOR_SCENE_SCOPE_CONFLICT", "Scene identities, order and structural metadata require native Plan Change")
            if not isinstance(item.get("text"), str) or not item["text"].strip():
                raise KernelError("AUTHOR_SCENE_TEXT_CONFLICT", "mapped Scene text must remain nonempty")
            if not source.get("realization_contract") and item.get("used_fact_ids") != original.get("used_fact_ids"):
                raise KernelError("AUTHOR_SCENE_SCOPE_CONFLICT", "new information use requires a frozen Scene knowledge contract")
        if serialize_realization(supplied, joins) != text:
            raise KernelError("AUTHOR_SCENE_TEXT_CONFLICT", "Scene mapping must exactly serialize the submitted text")
        if source.get("realization_contract"):
            integrate_realization(contract=source["realization_contract"], artifacts=supplied, text=text, separators=joins, enforce_voice_contract=enforce_voice)
        return supplied
    if not artifacts:
        return []
    if joins != original_joins:
        raise KernelError("AUTHOR_SCENE_MAPPING_REQUIRED", "separator changes require explicit Scene mapping")
    result = [dict(item) for item in artifacts]
    spans, offset = [], 0
    for index, item in enumerate(artifacts):
        spans.append((offset, offset + len(item["text"])))
        offset += len(item["text"]) + (len(original_joins[index]) if index < len(original_joins) else 0)
    for edit in reversed(edit_map(before, text)):
        matches = [(index, start) for index, (start, end) in enumerate(spans)
                   if start <= edit["start"] <= edit["end"] <= end]
        if len(matches) != 1:
            raise KernelError("AUTHOR_SCENE_MAPPING_REQUIRED", "Editing a Scene boundary requires explicit Scene artifacts")
        index, start = matches[0]
        old = result[index]["text"]
        result[index]["text"] = old[:edit["start"] - start] + edit["after"] + old[edit["end"] - start:]
    if serialize_realization(result, joins) != text:
        raise KernelError("AUTHOR_SCENE_TEXT_CONFLICT", "Scene edit mapping did not preserve exact text")
    if any(not item["text"].strip() for item in result):
        raise KernelError("AUTHOR_SCENE_SCOPE_CONFLICT", "Removing a Scene requires native Plan Change")
    if source.get("realization_contract"):
        integrate_realization(contract=source["realization_contract"], artifacts=result, text=text, separators=joins, enforce_voice_contract=enforce_voice)
    return result


def source_draft_content(source: AuthorityAssetDocument) -> dict[str, Any]:
    content = source.content
    if source.asset_type != "author_edit_candidate":
        return content
    draft = content.get("draft_content")
    if not isinstance(draft, dict) or any(draft.get(key) != content.get(key) for key in ("text", "scene_artifacts", "scene_separators")):
        raise KernelError("AUTHOR_BASE_CONTRACT_CONFLICT", "Candidate prose must agree with its retained draft contract")
    return draft


def _scope(payload: dict[str, Any]) -> dict[str, Any]:
    value = {key: payload[key] for key in ("project_id", "workspace_id", "book_id", "chapter")}
    if any(not isinstance(value[key], str) or not value[key].strip() for key in ("project_id", "workspace_id", "book_id")) or type(value["chapter"]) is not int or value["chapter"] < 1:
        raise ValueError("Exact project/workspace/book/chapter scope is required")
    return value


def _session_ref(scope: dict[str, Any]) -> str:
    digest = text_hash("\0".join(str(scope[key]) for key in ("workspace_id", "book_id", "chapter"))).split(":")[1]
    return f"author-editor/sessions/{digest}"


def _book_scope(uow: AuthorityUnitOfWork, scope: dict[str, Any]) -> None:
    uow.cursor.execute("SELECT 1 FROM authority_book WHERE project_id=%s AND workspace_id=%s AND book_id=%s FOR SHARE",
                       [scope["project_id"], scope["workspace_id"], scope["book_id"]])
    if uow.cursor.fetchone() is None:
        raise KernelError("AUTHOR_BOOK_SCOPE_CONFLICT", "Book does not belong to the requested project and workspace")


def require_source(uow: AuthorityUnitOfWork, scope: dict[str, Any], version_id: str) -> AuthorityAssetDocument:
    _book_scope(uow, scope)
    source = uow.repositories.asset_documents.require(project_id=scope["project_id"], asset_version_id=version_id)
    if source.asset_type not in {"draft_chapter", "draft_version", "best_draft_candidate", "chapter_plan", "author_edit_candidate"}:
        raise KernelError("AUTHOR_BASE_TYPE_INVALID", "Editor requires exact prose or a scoped Chapter Plan")
    if source.governance != "CLEAR":
        raise KernelError("AUTHOR_BASE_GOVERNANCE_BLOCKED", "Editor base is not governance clear")
    content = source.content
    if source.asset_type == "author_edit_candidate":
        if any(content.get(key) != value for key, value in scope.items()):
            raise KernelError("AUTHOR_BASE_SCOPE_CONFLICT", "Candidate belongs to another chapter scope")
        return source
    uow.cursor.execute(
        """SELECT root.workspace_id, root.command_payload, book.book_id
           FROM authority_operation_output_asset output
           JOIN authority_operation op ON op.operation_id=output.operation_id
           JOIN authority_operation root ON root.operation_id=op.root_operation_id
           LEFT JOIN authority_book_chapter_request request ON request.chapter_root_operation_id=root.operation_id
           LEFT JOIN authority_book_production book ON book.book_run_id=request.book_run_id
           WHERE output.asset_version_id=%s AND op.project_id=%s""", [version_id, scope["project_id"]])
    origins = uow.cursor.fetchall()
    valid = any(workspace == scope["workspace_id"] and int(command.get("chapter") or 0) == scope["chapter"]
                and (book or command.get("book_id") or (command.get("preparation_report") or {}).get("book_id")) == scope["book_id"]
                for workspace, command, book in origins)
    if not valid and source.asset_type == "chapter_plan":
        uow.cursor.execute(
            """SELECT 1 FROM story_plan_binding WHERE project_id=%s AND book_id=%s
               AND asset_version_id=%s AND contract_type='CHAPTER' AND freshness='CURRENT'""",
            [scope["project_id"], scope["book_id"], version_id])
        valid = uow.cursor.fetchone() is not None and int(content.get("chapter") or content.get("chapter_number") or 0) == scope["chapter"]
    if not valid:
        raise KernelError("AUTHOR_BASE_SCOPE_CONFLICT", "Base has no exact authoritative chapter and Book binding")
    return source


class ChapterAuthorEditingApplication:
    def __init__(self, database_url: str, *, application_build_id: str, commit_sha: str, fault_injector=None) -> None:
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.fault_injector = fault_injector

    def require(self, *, project_id: str, workspace_id: str, book_id: str, chapter: int,
                base_asset_version_id: str, principal: Principal) -> dict[str, Any]:
        principal.require("chapter.authority.query", project_id)
        scope = _scope(locals())
        with AuthorityUnitOfWork(self.database_url) as uow:
            source = require_source(uow, scope, base_asset_version_id)
            session = self._session(uow, scope)
            candidates = [asdict(item) for item in uow.repositories.asset_documents.list(
                project_id=project_id, asset_type="author_edit_candidate", limit=500)
                if all(item.content.get(key) == value for key, value in scope.items())]
            decisions = [asdict(item) for item in uow.repositories.asset_documents.list(
                project_id=project_id, asset_type="author_edit_decision", limit=500)
                if all(item.content.get(key) == value for key, value in scope.items())]
            uow.cursor.execute(
                """SELECT version.asset_version_id, asset.asset_type, version.content
                   FROM authority_asset_version version JOIN authority_asset asset USING(asset_id)
                   WHERE asset.project_id=%s AND asset.asset_type IN ('review_report','re_review_report')
                     AND version.content->>'target_asset_version_id'=%s
                   ORDER BY version.created_at DESC LIMIT 50""", [project_id, base_asset_version_id])
            diagnostics = [{"asset_version_id": row[0], "asset_type": row[1], "content": row[2]} for row in uow.cursor.fetchall()]
            uow.cursor.execute("SELECT book_run_id FROM authority_book_production WHERE project_id=%s AND workspace_id=%s AND book_id=%s ORDER BY created_at DESC LIMIT 100",
                               [project_id, workspace_id, book_id])
            book_runs = [row[0] for row in uow.cursor.fetchall()]
            uow.cursor.execute("""SELECT r.chapter_request_id,r.book_run_id,r.chapter_root_operation_id,b.version,
                b.active_chapter_request_id=r.chapter_request_id,b.accepted_through_chapter<r.chapter_number
                FROM authority_operation_output_asset output JOIN authority_operation op USING(operation_id)
                JOIN authority_book_chapter_request r ON r.chapter_root_operation_id=op.root_operation_id
                JOIN authority_book_production b USING(book_run_id)
                WHERE output.asset_version_id=%s AND r.project_id=%s AND b.book_id=%s LIMIT 1""",
                [base_asset_version_id, project_id, book_id])
            row = uow.cursor.fetchone()
            book_request = None if row is None else {"chapter_request_id":row[0],"book_run_id":row[1],
                "root_operation_id":row[2],"book_version":row[3],"is_current":row[4],"unaccepted":row[5]}
        return {**scope, "base_asset_version_id": source.asset_version_id, "base_asset_hash": source.content_hash,
                "base_text_hash": text_hash(str(source.content.get("text") or "")),
                "text": str(source.content.get("text") or ""), "title": source.content.get("title", ""),
                "scene_artifacts": source.content.get("scene_artifacts", []),
                "scene_separators": source.content.get("scene_separators"),
                "version": session.version_number if session else 0,
                "session": session.content if session and session.content.get("base_asset_version_id") == base_asset_version_id else None, "candidates": candidates, "decisions": decisions,
                "diagnostics": diagnostics, "book_runs": book_runs, "book_request": book_request,
                "authority": "CHAPTER_CANDIDATES_ONLY", "book_acceptance": "SEPARATE_CANON_AND_BOOK_GATES"}

    def execute(self, *, action: str, payload: dict[str, Any], idempotency_key: str,
                principal: Principal, trace_id: str = "", correlation_id: str = "") -> dict[str, Any]:
        scope = _scope(payload)
        principal.require("chapter.authority.execute", scope["project_id"])
        if action not in EDITOR_ACTIONS or not idempotency_key.strip():
            raise ValueError("Supported author action and idempotency key required")
        if type(payload.get("expected_version")) is not int or payload["expected_version"] < 0:
            raise ValueError("expected_version must be a non-negative integer")
        with AuthorityUnitOfWork(self.database_url) as uow:
            for definition in author_edit_definitions(self.application_build_id, self.commit_sha):
                uow.repositories.definitions.register(definition)
            references = [uow.repositories.asset_documents.require(project_id=scope["project_id"], asset_version_id=str(payload[key]))
                          for key in ("base_asset_version_id", "candidate_asset_version_id") if payload.get(key)]
            uow.commit()
        return execute_transaction_command(self.database_url, {
            "definition_name": f"chapter.author_edit.{action}", "definition_version": "1.0.0",
            **{key: scope[key] for key in ("project_id", "workspace_id")}, "actor_id": principal.principal_id,
            "idempotency_scope": "chapter:author-edit", "idempotency_key": idempotency_key,
            "trace_id": trace_id or f"trace:{uuid4()}", "span_id": str(uuid4()),
            "correlation_id": correlation_id or f"correlation:{uuid4()}", "causation_id": "",
            "input": {**payload, "action": action}, "input_assets": [
                {"asset_version_id": item.asset_version_id, "content_hash": item.content_hash} for item in references],
        }, context=AdmissionContext(principal.principal_id, frozenset({"chapter.authority.execute"}),
                                    frozenset({EDITOR_HANDLER}), self.application_build_id, self.commit_sha),
            handler=self._handle, fault_injector=self.fault_injector)

    @staticmethod
    def _session(uow, scope):
        try:
            return uow.repositories.asset_documents.require(project_id=scope["project_id"], logical_ref=_session_ref(scope))
        except KernelError as error:
            if error.code != "AUTHORITY_ASSET_NOT_FOUND":
                raise
            return None

    def _handle(self, uow, operation_id, checkpoint):
        uow.cursor.execute("SELECT project_id FROM authority_operation WHERE operation_id=%s", [operation_id])
        project_id = uow.cursor.fetchone()[0]
        operation = uow.repositories.chapter_authority.operation_execution(operation_id, project_id)
        payload, actor = operation["command_payload"], operation["actor_id"]
        scope, action = _scope(payload), payload["action"]
        uow.cursor.execute("SELECT book_id FROM authority_book WHERE project_id=%s AND book_id=%s FOR UPDATE", [project_id, scope["book_id"]])
        uow.cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"{project_id}:{_session_ref(scope)}"])
        _book_scope(uow, scope)
        session = self._session(uow, scope)
        version = session.version_number if session else 0
        if version != payload["expected_version"]:
            raise KernelError("AUTHOR_VERSION_CONFLICT", "A concurrent edit changed the chapter editor; preserve input and reload the current version")
        source = require_source(uow, scope, payload["base_asset_version_id"])
        from novel_forge.modules.book_authority.manuscript import require_current_editor_base
        require_current_editor_base(uow, scope, source.asset_version_id)
        draft_source = source_draft_content(source)
        before = str(draft_source.get("text") or "")
        if payload.get("base_text_hash") != text_hash(before) or payload.get("base_asset_hash") != source.content_hash:
            raise KernelError("AUTHOR_BASE_HASH_CONFLICT", "Exact base text and asset hashes are required")
        uow.cursor.execute("SELECT current_asset_version_id FROM authority_asset_locator WHERE project_id=%s AND asset_id=%s FOR SHARE",
                           [project_id, source.asset_id])
        current_versions = [row[0] for row in uow.cursor.fetchall()]
        if not current_versions:
            uow.cursor.execute("SELECT asset_version_id FROM authority_asset_version WHERE asset_id=%s ORDER BY version_number DESC LIMIT 1 FOR SHARE", [source.asset_id])
            current_versions = [row[0] for row in uow.cursor.fetchall()]
        if current_versions != [source.asset_version_id]:
            raise KernelError("AUTHOR_BASE_STALE", "The base Asset has a newer version; preserve the author input and reload")
        candidate_id = ""
        decision_id = ""
        if action == "save":
            text = payload.get("text")
            if not isinstance(text, str) or not text.strip() or len(text) > 200000 or "\0" in text:
                raise KernelError("AUTHOR_TEXT_INVALID", "Author text must be nonempty, bounded and contain no NUL")
            if payload.get("rights_basis") not in {"ORIGINAL_AUTHOR_INPUT", "AUTHORIZED_INPUT"}:
                raise KernelError("AUTHOR_RIGHTS_REQUIRED", "Author must identify original or authorized input")
            edits = edit_map(before, text)
            if not edits:
                raise KernelError("AUTHOR_NO_CHANGE", "No text changed; the original remains available")
            ranges = payload.get("allowed_ranges") or [{"start": 0, "end": len(before)}]
            if any(type(item.get(key)) is not int for item in ranges for key in ("start", "end")) or any(not 0 <= item["start"] <= item["end"] <= len(before) for item in ranges):
                raise KernelError("AUTHOR_EDIT_RANGE_INVALID", "Edit ranges use exact base Unicode code-point coordinates")
            if any(not any(item["start"] <= edit["start"] <= edit["end"] <= item["end"] for item in ranges) for edit in edits):
                raise KernelError("AUTHOR_EDIT_OUTSIDE_RANGE", "Submitted text changes outside the declared author selection")
            if payload.get("edit_intent", "PROSE_ONLY") != "PROSE_ONLY":
                raise KernelError("AUTHOR_PLAN_CHANGE_REQUIRED", "Scene mission, order, knowledge or event structure changes require native Plan Change before prose adoption")
            separators = payload.get("scene_separators", source.content.get("scene_separators"))
            if separators is None:
                separators = source.content.get("scene_separators")
            scenes = reconcile_author_scenes(draft_source, text, payload.get("scene_artifacts"), separators)
            mapping = {"scene_separators": separators} if separators is not None else {}
            if draft_source.get("realization_contract"):
                from .realization_composition import integrate_realization
                mapping.update(integrate_realization(contract=draft_source["realization_contract"], artifacts=scenes,
                    text=text, separators=separators, enforce_voice_contract=draft_source.get("author_workflow") != {"version": "author-workflow.v1", "mode": "AUTHOR_FIRST", "deep_review": False}))
            content = {**scope, "contract_version": EDITOR_CONTRACT, "base_asset_version_id": source.asset_version_id,
                       "base_asset_hash": source.content_hash, "base_text_hash": text_hash(before), "text_hash": text_hash(text),
                       "originating_draft_asset_version_id": source.content.get("originating_draft_asset_version_id", source.asset_version_id) if source.asset_type == "author_edit_candidate" else source.asset_version_id,
                       "text": text, "title": source.content.get("title", ""), "edits": edits, "allowed_ranges": ranges,
                       **mapping, "scene_artifacts": scenes, "author_id": actor, "rights_basis": payload["rights_basis"],
                       "source_provenance": {"kind": "HUMAN_AUTHOR_INPUT", "operation_id": operation_id},
                       "draft_content": {**draft_source, **mapping, "text": text, "scene_artifacts": scenes},
                       "status": "SAVED_CANDIDATE", "semantic_review": "NOT_RUN"}
            if payload.get("source_review_run_id") or payload.get("source_lineage_id"):
                from novel_forge.modules.book_followup_authority.prose_coordinator import load_review_run, review_progress
                uow.cursor.execute("SELECT book_run_id FROM authority_book_production WHERE project_id=%s AND book_id=%s",
                                   [project_id, scope["book_id"]])
                book_runs = [row[0] for row in uow.cursor.fetchall()]
                linked = None
                for book_run in book_runs:
                    try:
                        run = load_review_run(uow, run_id=str(payload.get("source_review_run_id") or ""), project_id=project_id,
                                              workspace_id=scope["workspace_id"], book_run_id=book_run)
                    except KernelError as error:
                        if error.code != "LONGFORM_PROSE_RUN_NOT_FOUND":
                            raise
                        continue
                    progress = review_progress(uow, run)
                    if progress.get("source_current") and any(item.get("lineage_id") == payload.get("source_lineage_id") for item in progress.get("findings", [])):
                        finding = next(item for item in progress["findings"] if item["lineage_id"] == payload["source_lineage_id"])
                        linked = {"source_review_run_id": payload["source_review_run_id"], "source_lineage_id": payload["source_lineage_id"],
                                  "source_finding_digest": finding["finding_digest"], "source_manifest_digest": progress["manifest_digest"],
                                  "source_review_digest": progress["review_digest"]}
                if linked is None:
                    raise KernelError("AUTHOR_REVIEW_LINEAGE_INVALID", "Review lineage is absent, stale or outside the editor Book scope")
                content.update(linked)
            checkpoint("after_domain_validation")
            candidate = self._write(uow, operation, "author_edit_candidate", f"author-editor/candidates/{operation_id}", content)
            candidate_id = candidate.asset_version_id
            state = "SAVED_CANDIDATE"
        else:
            candidate = uow.repositories.asset_documents.require(project_id=project_id, asset_version_id=payload["candidate_asset_version_id"])
            if candidate.asset_type != "author_edit_candidate" or any(candidate.content.get(key) != value for key, value in scope.items()) or candidate.content["base_asset_version_id"] != source.asset_version_id:
                raise KernelError("AUTHOR_CANDIDATE_SCOPE_CONFLICT", "Decision does not bind the exact saved candidate and base")
            if session is None or session.content.get("candidate_asset_version_id") != candidate.asset_version_id or session.content.get("status") != "SAVED_CANDIDATE":
                raise KernelError("AUTHOR_CANDIDATE_NOT_PENDING", "Only the current saved candidate can be decided")
            rationale = str(payload.get("rationale") or "").strip()
            if not rationale:
                raise KernelError("AUTHOR_RATIONALE_REQUIRED", "An author decision requires a rationale")
            candidate_id = candidate.asset_version_id
            state = "ADOPTED_PENDING_REVIEW" if action == "accept" else "REJECTED"
            decision = self._write(uow, operation, "author_edit_decision", f"author-editor/decisions/{operation_id}",
                                   {**scope, "contract_version": EDITOR_CONTRACT, "candidate_asset_version_id": candidate_id,
                                    "candidate_content_hash": candidate.content_hash, "text_hash": candidate.content["text_hash"],
                                    "base_asset_version_id": source.asset_version_id, "decision": action.upper(),
                                    "rationale": rationale, "actor_id": actor, "status": state,
                                    "authority": "AUTHOR_CANDIDATE_SELECTION", "book_acceptance": "NOT_GRANTED"})
            decision_id = decision.asset_version_id
        checkpoint("after_asset_version_insert")
        state_doc = self._write(uow, operation, "author_edit_session", _session_ref(scope),
                                {**scope, "contract_version": EDITOR_CONTRACT, "status": state,
                                 "base_asset_version_id": source.asset_version_id, "base_text_hash": text_hash(before),
                                 "candidate_asset_version_id": candidate_id, "decision_asset_version_id": decision_id,
                                 "actor_id": actor,
                                 "selected_asset_version_id": candidate_id if action == "accept" else (session.content.get("selected_asset_version_id", source.asset_version_id) if session else source.asset_version_id)}, previous=session)
        result = {**scope, "version": state_doc.version_number, "asset_version_id": state_doc.asset_version_id,
                  "candidate_asset_version_id": candidate_id, "decision_asset_version_id": decision_id, "editor_status": state}
        uow.repositories.operation_graph.record_event({
            "event_id": str(uuid4()), "audit_id": str(uuid4()), "outbox_id": str(uuid4()),
            "aggregate_type": "authority_chapter_author_edit", "aggregate_id": state_doc.asset_id,
            "operation_id": operation_id, "project_id": project_id, "event_type": "authority.chapter.author_edit.committed",
            "correlation_id": operation["correlation_id"], "causation_id": operation_id,
            "payload": {**result, "operation_id": operation_id, "action": action, "trace_id": operation["trace_id"]},
        })
        checkpoint("after_outbox_insert")
        return result

    @staticmethod
    def _write(uow, operation, kind, logical_ref, content, previous=None):
        return uow.repositories.asset_documents.materialize_output(AuthorityAssetWriteCommand(
            operation_id=operation["operation_id"], project_id=operation["project_id"],
            asset_id=previous.asset_id if previous else f"{kind}:{uuid4()}", asset_type=kind, schema_version=EDITOR_CONTRACT,
            logical_ref=logical_ref, category="author-editor", output_key=kind, role="primary" if kind == "author_edit_session" else "author_evidence",
            content=content, qualification_policy="author-input-structural-only.v1", trace_id=operation["trace_id"],
            correlation_id=operation["correlation_id"], causation_id=operation["operation_id"],
            expected_current_asset_version_id=previous.asset_version_id if previous else None))


def author_edit_definitions(build_id: str, commit_sha: str) -> tuple[dict[str, Any], ...]:
    return tuple({"name": f"chapter.author_edit.{action}", "definition_version": "1.0.0", "family": "chapter_authority",
                  "enabled": True, "command_schema": {"type": "object"}, "result_schema": {"type": "object"},
                  "handler_key": EDITOR_HANDLER, "handler_contract_version": EDITOR_CONTRACT,
                  "application_build_id": build_id, "commit_sha": commit_sha, "execution_mode": "transactional",
                  "permissions": ["chapter.authority.execute"], "approval_policy": {"required": False, "policy_key": "none"},
                  "idempotency_scope": "chapter:author-edit", "concurrency_key_template": "project:{project_id}",
                  "retry_policy": {"max_attempts": 1, "mode": "client_replay_only"},
                  "timeout_policy": {"operation_timeout_seconds": 60},
                  "cancellation_policy": {"mode": "not_applicable_atomic_transaction"},
                  "compensation_policy": {"supported": False, "reason": "append_only_author_candidates"},
                  "irreversible_effect_policy": {"allowed": False}, "external_capabilities": [],
                  "policy": {"execution_classification": "transaction_command", "filesystem_authority_forbidden": True},
                  "completion_contract": {"version": EDITOR_CONTRACT, "required_asset_selectors": [
                      {"selector": "author_edit_session", "output_key": "author_edit_session", "role": "primary",
                       "lifecycle": "ACTIVE", "eligibility": "ELIGIBLE", "governance": "CLEAR"}],
                      "required_qualifications": [{"decision": "ELIGIBLE"}], "required_evidence": ["trace", "audit"],
                      "required_outbox_events": ["authority.chapter.author_edit.committed"]}} for action in EDITOR_ACTIONS)
