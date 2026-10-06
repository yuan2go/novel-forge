from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.book_authority.editions import (
    EDITION_CONTRACT, edition_diff, edition_manifest, require_manifest, revise_manifest,
)
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import AdmissionContext, execute_transaction_command
from novel_forge.modules.review.diagnostics import prose_hash
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.book_edition_repositories import BookEditionRepository


EDITION_ACTIONS = frozenset({"create", "save", "bind-validation", "validate", "reject", "select"})


def accepted_edition_manifest(uow: AuthorityUnitOfWork, book: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.book_followup_authority.prose_coordinator import load_accepted_sources
    sources = load_accepted_sources(uow, book["book_run_id"], book["project_id"])
    for source in sources:
        uow.cursor.execute("""SELECT a.chapter_outcome_asset_version_id,a.story_state_asset_version_id,
            a.canon_snapshot_asset_version_id,a.longform_projection_set_id,
            COALESCE(NULLIF(r.command_payload->>'execution_chapter_plan_asset_version_id',''),r.chapter_plan_version)
            FROM authority_book_chapter_acceptance a JOIN authority_book_chapter_request r USING(chapter_request_id)
            WHERE a.acceptance_id=%s AND a.book_run_id=authority_book_source_run(%s,a.chapter_number)""", [source["acceptance_id"], book["book_run_id"]])
        row = uow.cursor.fetchone()
        source.update(dict(zip(("outcome_asset_version_id", "story_state_asset_version_id", "canon_snapshot_asset_version_id",
                                "projection_set_id", "chapter_plan_asset_version_id"), row)))
        draft = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=source["asset_version_id"])
        source.update({key: deepcopy(draft.content.get(key)) for key in ("title", "scene_artifacts", "scene_separators")})
        source["scene_artifacts"] = source["scene_artifacts"] or []
        source["scene_mapping"] = [{"slot_id": slot["slot_id"], "scene_id": slot["scene_id"]}
                                   for slot in (draft.content.get("realization_contract") or {}).get("slots", [])]
    return edition_manifest({key: book[key] for key in ("project_id", "workspace_id", "book_id", "book_run_id")}, sources)


class BookEditionApplication:
    def __init__(self, database_url: str, *, application_build_id: str, commit_sha: str, fault_injector=None) -> None:
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.fault_injector = fault_injector

    def start_validation(self, *, authority, project_id: str, workspace_id: str, book_run_id: str,
                         revision_id: str, principal: Principal, input_snapshot_id: str = "") -> dict[str, Any]:
        from dataclasses import fields
        from .production import StartBookProductionCommand
        principal.require("book.authority.execute", project_id)
        with AuthorityUnitOfWork(self.database_url) as uow:
            repo = BookEditionRepository(uow.cursor)
            source = repo.book(project_id=project_id, workspace_id=workspace_id, book_run_id=book_run_id, for_update=False)
            revision = repo.revision(project_id=project_id, revision_id=revision_id, book_id=source["book_id"], for_update=False)
            uow.cursor.execute("SELECT book_run_id FROM authority_book_edition_run WHERE revision_id=%s AND role='VALIDATION'", [revision_id])
            existing = uow.cursor.fetchone()
            if existing:
                return {"revision_id": revision_id, "validation_book_run_id": existing[0], "replayed": True}
            if revision["edition"]["current_revision_id"] != revision_id:
                raise KernelError("EDITION_VERSION_CONFLICT", "Validation must start from the current saved candidate")
            if any(event["event_kind"] == "REJECTED" for event in repo.events(revision_id)):
                raise KernelError("EDITION_VALIDATION_REJECTED", "A rejected candidate cannot create a validation run")
            uow.cursor.execute("SELECT command_payload FROM authority_operation WHERE operation_id=%s", [source["root_operation_id"]])
            frozen = dict(uow.cursor.fetchone()[0])
            frozen = dict(frozen.get("payload", frozen))
        command = {field.name: frozen[field.name] for field in fields(StartBookProductionCommand) if field.name in frozen}
        command.update(project_id=project_id, workspace_id=workspace_id, book_id=source["book_id"], actor_id=principal.principal_id,
                       trace_id="edition-validation:" + revision_id, correlation_id=source["root_operation_id"],
                       stable_idempotency_key="edition-validation:" + revision_id, edition_revision_id=revision_id,
                       target_chapter_count=source["target_chapter_count"])
        if input_snapshot_id:
            from .input_resolver import BookProductionInputResolver
            snapshot = BookProductionInputResolver(self.database_url, application_build_id=self.application_build_id,
                commit_sha=self.commit_sha).require(input_snapshot_id)
            if (snapshot.project_id, snapshot.workspace_id, snapshot.book_id) != (project_id, workspace_id, source["book_id"]):
                raise KernelError("EDITION_INPUT_SCOPE_INVALID", "Edition validation requires a resolved snapshot of the same Book")
            command.update(input_snapshot_id=input_snapshot_id, input_mode="RESOLVED_AUTHORITY_INPUT",
                book_design_version=snapshot.book_design_version, book_plan_version=snapshot.book_plan_version,
                production_profile_version=snapshot.production_profile_version,
                longform_context_versions={
                    "volume_plan_version": snapshot.current_volume_plan_version,
                    "arc_plan_versions": list(snapshot.current_relevant_arc_plan_versions),
                    **{key: getattr(snapshot, key) for key in ("character_state_version", "foreshadowing_state_version", "quality_trend_version",
                        "reward_ledger_version", "promise_ledger_version", "reader_segment_version", "reader_contract_version", "platform_profile_version")}})
            with AuthorityUnitOfWork(self.database_url) as uow:
                profile = uow.repositories.asset_documents.require(project_id=project_id, asset_version_id=snapshot.production_profile_version)
                command["target_chapter_count"] = int(profile.content.get("target_chapter_count") or 0)
        if command["target_chapter_count"] < len(revision["manifest"]["units"]):
            raise KernelError("EDITION_INPUT_CAPACITY_REQUIRED", "Resolve an approved production profile covering every edited unit before validation")
        admission = authority.start(StartBookProductionCommand(**command), principal=principal)
        return {"revision_id": revision_id, "validation_book_run_id": admission.book_run_id, "replayed": admission.replayed,
                "authority": "NORMAL_BOOK_PRODUCTION_GATES", "publication_authorized": False}

    def query(self, *, project_id: str, workspace_id: str, book_run_id: str,
              principal: Principal, revision_id: str = "") -> dict[str, Any]:
        principal.require("book.authority.query", project_id)
        with AuthorityUnitOfWork(self.database_url) as uow:
            repo = BookEditionRepository(uow.cursor)
            book = repo.book(project_id=project_id, workspace_id=workspace_id, book_run_id=book_run_id, for_update=False)
            head = repo.head(book["book_id"], for_update=False)
            uow.cursor.execute("SELECT to_jsonb(e) FROM authority_book_edition e WHERE project_id=%s AND book_id=%s ORDER BY created_at", [project_id, book["book_id"]])
            editions = [row[0] for row in uow.cursor.fetchall()]
            result = {"book_id": book["book_id"], "head": head, "editions": editions, "publication_authorized": False}
            if not revision_id:
                result["source_manifest"] = accepted_edition_manifest(uow, book)
                return result
            revision = repo.revision(project_id=project_id, revision_id=revision_id, book_id=book["book_id"], for_update=False)
            result.update(revision=revision, events=repo.events(revision_id))
            uow.cursor.execute("""SELECT v.asset_version_id,v.content FROM authority_asset a JOIN authority_asset_version v USING(asset_id)
                WHERE a.project_id=%s AND a.asset_type='screenplay_update_task' AND v.content->>'book_id'=%s
                AND v.content->>'replacement_revision_id'=%s ORDER BY v.created_at DESC LIMIT 100""", [project_id,book["book_id"],revision_id])
            result["adaptation_updates"] = [{"asset_version_id": row[0], **row[1]} for row in uow.cursor.fetchall()]
            uow.cursor.execute("""SELECT binding.book_run_id,binding.role,prefix.content
                FROM authority_book_edition_run binding LEFT JOIN authority_book_edition_prefix prefix USING(book_run_id)
                WHERE binding.revision_id=%s""", [revision_id])
            result["bound_runs"] = [{"book_run_id": row[0], "role": row[1], "inherited_prefix": row[2]} for row in uow.cursor.fetchall()]
            validation = next((row for row in result["bound_runs"] if row["role"] == "VALIDATION"), None)
            if validation:
                validation_book = repo.book(project_id=project_id, workspace_id=workspace_id, book_run_id=validation["book_run_id"], for_update=False)
                if validation_book["accepted_through_chapter"] == len(revision["manifest"]["units"]):
                    reviewed = self._reviewed_manifest(uow, validation_book, revision)
                    result["validation_result"] = {"book_run_id": validation_book["book_run_id"], "manifest": reviewed,
                        "diff": edition_diff(revision["manifest"], reviewed), "publication_authorized": False}
            if revision["base_revision_id"]:
                base = repo.revision(project_id=project_id, revision_id=revision["base_revision_id"], book_id=book["book_id"], for_update=False)
                result["diff"] = edition_diff(base["manifest"], revision["manifest"])
            return result

    def export_manuscript(self, *, project_id: str, workspace_id: str, book_run_id: str,
                          revision_id: str, principal: Principal, export_kind: str = "FORMAL") -> dict[str, Any]:
        if not revision_id or export_kind not in {"FORMAL", "CANDIDATE"}:
            raise ValueError("Choose an exact revision and FORMAL or CANDIDATE export")
        result = self.query(project_id=project_id, workspace_id=workspace_id, book_run_id=book_run_id,
                            revision_id=revision_id, principal=principal)
        events = {event["event_kind"] for event in result["events"]}
        if export_kind == "FORMAL" and not {"VALIDATED", "SELECTED"}.issubset(events):
            raise KernelError("EDITION_FORMAL_EXPORT_REQUIRES_SELECTION", "This exact revision has not been validated and selected; export it explicitly as a candidate or adopt it first")
        return {**result, "export": {"kind": export_kind, "revision_id": revision_id,
            "manifest_digest": result["revision"]["manifest"]["manifest_digest"],
            "currently_selected": result["head"]["selected_revision_id"] == revision_id,
            "publication_authorized": False, "literary_quality": "NOT_PROVEN"}}

    def execute(self, *, action: str, project_id: str, workspace_id: str, book_run_id: str,
                data: dict[str, Any], idempotency_key: str, principal: Principal) -> dict[str, Any]:
        principal.require("book.authority.execute", project_id)
        if action not in EDITION_ACTIONS or not idempotency_key.strip():
            raise ValueError("An edition action and stable idempotency key are required")
        definition = self._definition(action)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.definitions.register(definition)
            inputs = self._admission_inputs(uow, action=action, project_id=project_id, workspace_id=workspace_id,
                                            book_run_id=book_run_id, data=data, idempotency_key=idempotency_key)
            uow.commit()
        payload = {"project_id": project_id, "workspace_id": workspace_id, "book_run_id": book_run_id, "action": action, "data": data}
        return execute_transaction_command(self.database_url, {
            "definition_name": definition["name"], "definition_version": "1.0.0", "project_id": project_id,
            "workspace_id": workspace_id, "actor_id": principal.principal_id, "idempotency_scope": "book:edition",
            "idempotency_key": idempotency_key, "trace_id": "edition:" + str(uuid4()), "span_id": str(uuid4()),
            "correlation_id": book_run_id, "causation_id": "", "input": payload, "input_assets": inputs,
        }, context=AdmissionContext(principal.principal_id, frozenset({"book.authority.execute"}),
                                    frozenset({definition["handler_key"]}), self.application_build_id, self.commit_sha),
            handler=self._handle, fault_injector=self.fault_injector)

    def _admission_inputs(self, uow, *, action, project_id, workspace_id, book_run_id, data, idempotency_key):
        uow.cursor.execute("""SELECT input_asset_snapshot FROM authority_operation
            WHERE idempotency_scope='book:edition' AND idempotency_key=%s AND project_id=%s""", [idempotency_key, project_id])
        previous = uow.cursor.fetchone()
        if previous is not None:
            return previous[0]
        repo = BookEditionRepository(uow.cursor)
        book = repo.book(project_id=project_id, workspace_id=workspace_id, book_run_id=book_run_id, for_update=False)
        if action == "create" and data.get("source_validation_revision_id"):
            candidate = repo.revision(project_id=project_id, book_id=book["book_id"], revision_id=str(data["source_validation_revision_id"]), for_update=False)
            validation, sources = self._validation_sources(uow, repo, book, candidate, data, for_update=False)
            reviewed = self._reviewed_manifest(uow, validation, candidate)
            if reviewed["manifest_digest"] != data.get("base_manifest_digest"):
                raise KernelError("EDITION_BASE_STALE", "Capture requires the exact native reviewed manuscript")
            versions = [candidate["revision_id"], *(source[key] for source in sources for key in (
                "asset_version_id", "outcome_asset_version_id", "story_state_asset_version_id", "canon_snapshot_asset_version_id", "chapter_plan_asset_version_id"))]
            return [{"asset_version_id": version_id, "content_hash": uow.repositories.asset_documents.require(
                project_id=project_id, asset_version_id=version_id).content_hash} for version_id in dict.fromkeys(versions)]
        revision_id = data.get("base_revision_id") if action == "create" else data.get("revision_id")
        if revision_id:
            revision = repo.revision(project_id=project_id, book_id=book["book_id"], revision_id=str(revision_id), for_update=False)
            return [{"asset_version_id": revision["revision_id"], "content_hash": revision["content_hash"]}]
        if action != "create":
            raise KernelError("EDITION_REVISION_NOT_FOUND", "Edition commands require an exact revision")
        manifest = accepted_edition_manifest(uow, book)
        if manifest["manifest_digest"] != data.get("base_manifest_digest"):
            raise KernelError("EDITION_BASE_STALE", "The exact source manifest changed; retain edits and reload")
        ids = dict.fromkeys(source[key] for source in manifest["sources"] for key in (
            "asset_version_id", "outcome_asset_version_id", "story_state_asset_version_id",
            "canon_snapshot_asset_version_id", "chapter_plan_asset_version_id") if source.get(key))
        inputs = []
        for version_id in ids:
            document = uow.repositories.asset_documents.require(project_id=project_id, asset_version_id=version_id)
            inputs.append({"asset_version_id": version_id, "content_hash": document.content_hash})
        return inputs

    def _handle(self, uow, operation_id, checkpoint):
        uow.cursor.execute("SELECT command_payload,trace_id,actor_id FROM authority_operation WHERE operation_id=%s", [operation_id])
        payload, trace_id, actor_id = uow.cursor.fetchone()
        scope = {key: payload[key] for key in ("project_id", "workspace_id", "book_run_id")}
        data, action = payload["data"], payload["action"]
        repo = BookEditionRepository(uow.cursor)
        book = repo.book(**scope, for_update=False)
        uow.cursor.execute("SELECT book_id FROM authority_book WHERE book_id=%s FOR UPDATE", [book["book_id"]])
        book = repo.book(**scope)
        head = repo.head(book["book_id"])
        if action == "create":
            result = self._create(uow, repo, book, head, data, operation_id, trace_id)
        else:
            revision = repo.revision(project_id=scope["project_id"], revision_id=str(data.get("revision_id") or ""), book_id=book["book_id"])
            require_manifest(revision["manifest"])
            if action == "save":
                result = self._save(uow, repo, book, revision, data, operation_id, trace_id)
            elif action == "bind-validation":
                validation = repo.book(project_id=scope["project_id"], workspace_id=scope["workspace_id"], book_run_id=str(data.get("validation_book_run_id") or ""))
                if (validation["book_id"] != book["book_id"] or validation["accepted_through_chapter"] != 0
                    or validation["active_chapter_request_id"] or repo.run_binding(validation["book_run_id"])):
                    raise KernelError("EDITION_VALIDATION_SCOPE_INVALID", "Bind an empty, distinct native Book run before its first task")
                if validation["book_run_id"] == revision["edition"]["source_book_run_id"]:
                    raise KernelError("EDITION_VALIDATION_SCOPE_INVALID", "Historical acceptance cannot validate a changed edition")
                self._require_current_candidate(revision, data)
                uow.cursor.execute("INSERT INTO authority_book_edition_run(book_run_id,revision_id,role,created_by_operation_id) VALUES(%s,%s,'VALIDATION',%s)",
                                   [validation["book_run_id"], revision["revision_id"], operation_id])
                result = {"revision_id": revision["revision_id"], "validation_book_run_id": validation["book_run_id"], "status": "VALIDATION_PENDING"}
                repo.event(revision_id=revision["revision_id"], kind="VALIDATION_BOUND", content=result, operation_id=operation_id)
            elif action == "validate":
                self._require_current_candidate(revision, data)
                result = self._validate(uow, repo, book, revision, data, operation_id)
            elif action == "reject":
                self._require_current_candidate(revision, data)
                if head["selected_revision_id"] == revision["revision_id"]:
                    raise KernelError("EDITION_SELECTED_REVISION_IMMUTABLE", "Reject an editing candidate; replacing the selected manuscript requires a controlled selection")
                if not str(data.get("reason") or "").strip():
                    raise KernelError("EDITION_REASON_REQUIRED", "Rejection retains its explicit reason")
                result = {"revision_id": revision["revision_id"], "status": "REJECTED", "reason": data["reason"]}
                repo.event(revision_id=revision["revision_id"], kind="REJECTED", content=result, operation_id=operation_id)
            else:
                result = self._select(uow, repo, book, revision, head, data, operation_id)
        checkpoint("after_edition_mutation")
        uow.repositories.operation_graph.record_event({
            "event_id": str(uuid4()), "audit_id": str(uuid4()), "outbox_id": str(uuid4()),
            "aggregate_type": "book_edition", "aggregate_id": book["book_id"], "operation_id": operation_id,
            "project_id": book["project_id"], "event_type": "book.edition." + action,
            "correlation_id": book["book_run_id"], "causation_id": operation_id,
            "payload": {**result, "operation_id": operation_id, "actor_id": actor_id, "trace_id": trace_id, "publication_authorized": False},
        })
        checkpoint("after_outbox_insert")
        return {**result, "publication_authorized": False}

    def _write(self, uow, book, operation_id, trace_id, manifest, key):
        return uow.repositories.asset_documents.materialize_output(AuthorityAssetWriteCommand(
            operation_id=operation_id, project_id=book["project_id"], asset_id="book-edition:" + str(uuid4()),
            asset_type="book_edition_manifest", schema_version=EDITION_CONTRACT,
            logical_ref="book-editions/" + operation_id + "/" + key, category="book-edition", output_key=key,
            role="primary", content=manifest, qualification_policy=EDITION_CONTRACT,
            trace_id=trace_id, correlation_id=book["book_run_id"], causation_id=operation_id))

    def _new_edition(self, uow, repo, book, operation_id, trace_id, manifest, base_id, key):
        version = self._write(uow, book, operation_id, trace_id, manifest, key)
        edition_id = "edition:" + str(uuid4())
        repo.record_revision(revision_id=version.asset_version_id, edition_id=edition_id, revision_number=1,
                             predecessor_revision_id="", base_revision_id=base_id, digest=manifest["manifest_digest"], operation_id=operation_id)
        uow.cursor.execute("""INSERT INTO authority_book_edition(edition_id,project_id,workspace_id,book_id,source_book_run_id,
            version,current_revision_id,created_by_operation_id) VALUES(%s,%s,%s,%s,%s,1,%s,%s)""",
            [edition_id, book["project_id"], book["workspace_id"], book["book_id"], book["book_run_id"], version.asset_version_id, operation_id])
        repo.event(revision_id=version.asset_version_id, kind="CREATED", content={"base_revision_id": base_id}, operation_id=operation_id)
        return {"edition_id": edition_id, "revision_id": version.asset_version_id, "version": 1, "manifest_digest": manifest["manifest_digest"]}

    def _create(self, uow, repo, book, head, data, operation_id, trace_id):
        if data.get("source_validation_revision_id"):
            candidate = repo.revision(project_id=book["project_id"], book_id=book["book_id"], revision_id=str(data["source_validation_revision_id"]))
            self._require_current_candidate(candidate, data)
            if not str(data.get("reason") or "").strip() or any(event["event_kind"] == "REJECTED" for event in repo.events(candidate["revision_id"])):
                raise KernelError("EDITION_CAPTURE_NOT_ALLOWED", "A rejected candidate cannot be captured; explain the reviewed-version decision")
            validation, sources = self._validation_sources(uow, repo, book, candidate, data)
            manifest = self._reviewed_manifest(uow, validation, candidate)
            if manifest["manifest_digest"] != data.get("base_manifest_digest"):
                raise KernelError("EDITION_BASE_STALE", "The native reviewed manuscript differs from the inspected exact manifest")
            result = self._new_edition(uow, repo, validation, operation_id, trace_id, manifest, candidate["revision_id"], "edition.manifest")
            proof = self._validation_proof(result["revision_id"], manifest, validation["book_run_id"], sources)
            proof.update(validation_basis="CAPTURED_NATIVE_REVIEW_RESULT", source_validation_revision_id=candidate["revision_id"], reason=data["reason"])
            repo.event(revision_id=result["revision_id"], kind="VALIDATED", content=proof, operation_id=operation_id)
            return {**result, **proof, "source_validation_revision_id": candidate["revision_id"]}
        if data.get("base_revision_id"):
            base = repo.revision(project_id=book["project_id"], revision_id=data["base_revision_id"], book_id=book["book_id"])
            manifest, base_id = base["manifest"], base["revision_id"]
        else:
            manifest = accepted_edition_manifest(uow, book)
            base_id = ""
        if manifest["manifest_digest"] != data.get("base_manifest_digest"):
            raise KernelError("EDITION_BASE_STALE", "The exact source manifest changed; retain edits and reload")
        result = self._new_edition(uow, repo, book, operation_id, trace_id, manifest, base_id, "edition.manifest")
        if not base_id:
            repo.event(revision_id=result["revision_id"], kind="VALIDATED", content={"kind": "ORIGINAL_ACCEPTED_MANUSCRIPT", "source_book_run_id": book["book_run_id"],
                       "manifest_digest": manifest["manifest_digest"]}, operation_id=operation_id)
        if not head["version"] and not base_id:
            version = repo.select(book_id=book["book_id"], revision_id=result["revision_id"], expected_version=0, operation_id=operation_id)
            repo.event(revision_id=result["revision_id"], kind="SELECTED", content={"version": version, "reason": "original native accepted manuscript"}, operation_id=operation_id)
            if repo.run_binding(book["book_run_id"]) is None:
                uow.cursor.execute("INSERT INTO authority_book_edition_run(book_run_id,revision_id,role,created_by_operation_id) VALUES(%s,%s,'SOURCE',%s)",
                                   [book["book_run_id"], result["revision_id"], operation_id])
        return {**result, "status": "CREATED"}

    @staticmethod
    def _require_current_candidate(revision, data):
        if (revision["edition"]["current_revision_id"] != revision["revision_id"]
            or type(data.get("expected_version")) is not int or data["expected_version"] != revision["edition"]["version"]):
            raise KernelError("EDITION_VERSION_CONFLICT", "A concurrent save changed this edition; preserve the candidate and reload")

    def _save(self, uow, repo, book, revision, data, operation_id, trace_id):
        self._require_current_candidate(revision, data)
        if data.get("base_manifest_digest") != revision["manifest_digest"]:
            raise KernelError("EDITION_BASE_STALE", "Save must bind the exact preceding manifest")
        manifest = revise_manifest(revision["manifest"], units=data.get("units", []), reason=str(data.get("reason") or ""),
                                   change_kind=str(data.get("change_kind") or ""), removed_source_ranges=data.get("removed_source_ranges"))
        version = self._write(uow, book, operation_id, trace_id, manifest, "edition.manifest")
        number = revision["edition"]["version"] + 1
        repo.record_revision(revision_id=version.asset_version_id, edition_id=revision["edition_id"], revision_number=number,
                             predecessor_revision_id=revision["revision_id"], base_revision_id=revision["base_revision_id"] or revision["revision_id"],
                             digest=manifest["manifest_digest"], operation_id=operation_id)
        uow.cursor.execute("UPDATE authority_book_edition SET current_revision_id=%s,version=%s WHERE edition_id=%s AND version=%s",
                            [version.asset_version_id, number, revision["edition_id"], data["expected_version"]])
        repo.event(revision_id=version.asset_version_id, kind="SAVED", content={"predecessor_revision_id": revision["revision_id"], "impact": manifest["impact"]}, operation_id=operation_id)
        return {"edition_id": revision["edition_id"], "revision_id": version.asset_version_id, "version": number,
                "manifest_digest": manifest["manifest_digest"], "status": "REVALIDATION_REQUIRED", "impact": manifest["impact"]}

    def _validation_sources(self, uow, repo, book, revision, data, *, for_update=True):
        validation_id = str(data.get("validation_book_run_id") or "")
        binding = repo.run_binding(validation_id)
        if binding is None or binding["revision_id"] != revision["revision_id"] or binding["role"] != "VALIDATION":
            raise KernelError("EDITION_VALIDATION_UNBOUND", "Validation must consume the previously frozen edition revision")
        validation = repo.book(project_id=book["project_id"], workspace_id=book["workspace_id"], book_run_id=validation_id, for_update=for_update)
        sources = accepted_edition_manifest(uow, validation)["sources"]
        units = revision["manifest"]["units"]
        if len(sources) != len(units):
            raise KernelError("EDITION_VALIDATION_INCOMPLETE", "Every edited unit needs native review, Canon and Book acceptance at its mapped position")
        from .edition_planning import require_edition_execution_plan
        for chapter, (source, unit) in enumerate(zip(sources, units, strict=True), start=1):
            if source["chapter_plan_asset_version_id"] != unit["chapter_plan_asset_version_id"]:
                require_edition_execution_plan(self.database_url, project_id=book["project_id"], book_id=book["book_id"], book_run_id=validation_id,
                    execution_plan_version_id=source["chapter_plan_asset_version_id"], revision_id=revision["revision_id"], chapter=chapter,
                    source_plan_version_id=unit["chapter_plan_asset_version_id"])
        return validation, sources

    @staticmethod
    def _reviewed_manifest(uow, validation, revision):
        from .completion_domain import completion_digest
        source = accepted_edition_manifest(uow, validation)
        if len(source["sources"]) != len(revision["manifest"]["units"]):
            raise KernelError("EDITION_VALIDATION_INCOMPLETE", "Reviewed capture requires the complete exact editing boundary")
        sources = [{**item, "unit_id": unit["unit_id"]} for item, unit in zip(source["sources"], revision["manifest"]["units"], strict=True)]
        manifest = edition_manifest({key: validation[key] for key in ("project_id", "workspace_id", "book_id", "book_run_id")}, sources)
        manifest["review_result_origin"] = {"candidate_revision_id": revision["revision_id"], "candidate_manifest_digest": revision["manifest_digest"],
            "validation_book_run_id": validation["book_run_id"], "accepted_manifest_digest": source["manifest_digest"]}
        manifest["manifest_digest"] = completion_digest({key: value for key, value in manifest.items() if key != "manifest_digest"})
        return manifest

    def _validation_proof(self, revision_id, manifest, validation_id, sources):
        proofs = [{"unit_id": unit["unit_id"], "text_hash": prose_hash(source["text"]),
                   **{key: source[key] for key in ("acceptance_id", "asset_version_id", "asset_hash", "outcome_asset_version_id",
                                                   "story_state_asset_version_id", "canon_snapshot_asset_version_id", "projection_set_id")}}
                  for unit, source in zip(manifest["units"], sources, strict=True)]
        return {"revision_id": revision_id, "manifest_digest": manifest["manifest_digest"],
                  "validation_book_run_id": validation_id, "status": "VALIDATED", "accepted_units": proofs,
                  "review_qualification": "NATIVE_BUSINESS_ACCEPTANCE_ONLY", "exact_release_sha": self.commit_sha}

    def _validate(self, uow, repo, book, revision, data, operation_id):
        validation, sources = self._validation_sources(uow, repo, book, revision, data)
        if any(source["text"] != unit["text"] for source, unit in zip(sources, revision["manifest"]["units"], strict=True)):
            raise KernelError("EDITION_VALIDATION_INCOMPLETE", "Native review changed the submitted prose; inspect and capture its exact result as a new version before selection")
        result = self._validation_proof(revision["revision_id"], revision["manifest"], validation["book_run_id"], sources)
        repo.event(revision_id=revision["revision_id"], kind="VALIDATED", content=result, operation_id=operation_id)
        return result

    def _select(self, uow, repo, book, revision, head, data, operation_id):
        if type(data.get("expected_head_version")) is not int or data["expected_head_version"] != head["version"] or not str(data.get("reason") or "").strip():
            raise KernelError("EDITION_SELECTION_CONFLICT", "Selection needs the current head version and a reason")
        events = repo.events(revision["revision_id"])
        validations = [event for event in events if event["event_kind"] == "VALIDATED" and event["content"]["manifest_digest"] == revision["manifest_digest"]]
        if not validations or any(event["event_kind"] == "REJECTED" for event in events):
            raise KernelError("EDITION_NOT_ADMITTED", "An unvalidated or rejected manuscript cannot replace the selected edition")
        validation = validations[-1]["content"]
        if validation.get("exact_release_sha") not in (None, self.commit_sha):
            raise KernelError("EDITION_VALIDATION_RELEASE_STALE", "Changed implementation requires exact edition validation again")
        target_run = validation.get("validation_book_run_id", validation.get("source_book_run_id"))
        uow.cursor.execute("SELECT book_run_id FROM authority_book_production WHERE book_run_id=%s FOR UPDATE", [target_run])
        target = repo.book(project_id=book["project_id"], workspace_id=book["workspace_id"], book_run_id=target_run)
        if target["accepted_through_chapter"] != len(revision["manifest"]["units"]):
            raise KernelError("EDITION_FRONTIER_STALE", "Freeze the run's new accepted frontier before selecting it")
        if target["active_chapter_request_id"]:
            raise KernelError("EDITION_TARGET_INFLIGHT", "Settle the target edition's current task before selecting its accepted frontier")
        new_version = repo.select(book_id=book["book_id"], revision_id=revision["revision_id"], expected_version=head["version"], operation_id=operation_id)
        result = {"revision_id": revision["revision_id"], "previous_revision_id": head["selected_revision_id"], "head_version": new_version,
                  "continuation_book_run_id": target_run, "reason": data["reason"], "status": "SELECTED",
                  "old_inflight_policy": "SETTLE_ONLY_IN_ORIGINAL_BOOK_RUN"}
        repo.event(revision_id=revision["revision_id"], kind="SELECTED", content=result, operation_id=operation_id)
        from novel_forge.modules.book_followup_authority.screenplay_application import record_screenplay_source_invalidations
        record_screenplay_source_invalidations(uow, book=book, replacement_revision_id=revision["revision_id"],
                                              operation_id=operation_id, trace_id="edition:" + operation_id)
        return result

    def _definition(self, action):
        from .completion import book_completion_definitions
        definition = deepcopy(book_completion_definitions(application_build_id=self.application_build_id, commit_sha=self.commit_sha)[0])
        name = "book.edition." + action
        schema = {"type": "object", "additionalProperties": False, "required": ["project_id", "workspace_id", "book_run_id", "action", "data"],
                  "properties": {**{key: {"type": "string", "minLength": 1} for key in ("project_id", "workspace_id", "book_run_id")},
                                 "action": {"type": "string", "enum": [action]}, "data": {"type": "object"}}}
        definition.update(name=name, definition_version="1.0.0", handler_key="novel_forge.book.edition", handler_contract_version=EDITION_CONTRACT,
                          command_schema=schema, result_schema={"type": "object"}, input_contract=schema,
                          output_contract={"type": "BookEdition"}, command_schema_version=name + ".command.v1",
                          result_schema_version=name + ".result.v1", idempotency_scope="book:edition",
                          completion_contract={"version": EDITION_CONTRACT, "required_evidence": ["trace", "audit"], "required_outbox_events": [name]})
        return definition
