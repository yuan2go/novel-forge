from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.book_authority.editions import derived_invalidations
from novel_forge.modules.book_authority.edition_application import BookEditionApplication
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import AdmissionContext, execute_transaction_command
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.book_edition_repositories import BookEditionRepository

from .application import BookFollowupAdmission, BookFollowupCommand
from .screenplay import SOURCE_TYPE, CANDIDATE_TYPE, REVIEW_TYPE, ACCEPTED_TYPE, SCREENPLAY_STAGES, source_contract, screenplay_text, validate_review
from .screenplay_handler import require_validated_source


class ScreenplayApplication:
    def __init__(self, database_url: str, *, application_build_id: str, commit_sha: str, followup=None):
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.followup = followup

    def source_knowledge(self, *, project_id: str, workspace_id: str, book_run_id: str, revision_id: str,
                         selected_unit_ids: list[str], principal: Principal) -> dict[str, Any]:
        principal.require("book.authority.query", project_id)
        from .screenplay_sources import accepted_source_evidence
        with AuthorityUnitOfWork(self.database_url) as uow:
            repo = BookEditionRepository(uow.cursor)
            book = repo.book(project_id=project_id, workspace_id=workspace_id, book_run_id=book_run_id, for_update=False)
            revision = repo.revision(project_id=project_id, book_id=book["book_id"], revision_id=revision_id, for_update=False)
            available = {unit["unit_id"] for unit in revision["manifest"]["units"]}
            if (not selected_unit_ids or len(selected_unit_ids) > 100 or len(set(selected_unit_ids)) != len(selected_unit_ids)
                or set(selected_unit_ids) - available):
                raise KernelError("SCREENPLAY_SOURCE_INVALID", "Inspect an explicit bounded range of stable edition units")
            source = {"book_id": book["book_id"], "source_revision_id": revision_id,
                "source_manifest_digest": revision["manifest_digest"], "selected_unit_ids": selected_unit_ids,
                "scene_plan": [], "policy": {"knowledge_contract": {"character_known_fact_ids": {}, "reader_allowed_fact_ids": []}}}
            evidence = accepted_source_evidence(uow, project_id=project_id, source=source, for_update=False)
            from novel_forge.modules.mkaos_authority.domain import NarrativeIntelligenceNeed, resolve_book_knowledge_access_policy
            from novel_forge.modules.mkaos_authority.query import MkaosAuthorityQuery
            profile = uow.repositories.asset_documents.require(project_id=project_id, asset_version_id=book["production_profile_version"])
            access = resolve_book_knowledge_access_policy(production_profile=profile.content, project_id=project_id, book_id=book["book_id"])
            recommended = MkaosAuthorityQuery(self.database_url).resolve_narrative_intelligence(project_id=project_id, book_id=book["book_id"],
                knowledge_access_policy=access, need=NarrativeIntelligenceNeed(scope="SCENE", target_stage="screenplay_generate",
                    craft_context={"scene_goal": ["可表演动作、空间位置、对白潜台词与承诺因果"], "chapter_number": max(item["chapter_number"] for item in evidence["units"])}))
            return {"source_revision_id": revision_id, "source_manifest_digest": revision["manifest_digest"],
                "read_only": True, "adaptation_authorized": False, "recommended_craft_selection": recommended, **evidence}

    def command(self, *, action: str, project_id: str, workspace_id: str, book_run_id: str,
                data: dict[str, Any], idempotency_key: str, principal: Principal) -> dict[str, Any]:
        principal.require("book.authority.execute", project_id)
        if action not in {"prepare", "accept", "update"} or not idempotency_key.strip():
            raise ValueError("A valid screenplay command and stable idempotency key are required")
        definition = deepcopy(BookEditionApplication(self.database_url, application_build_id=self.application_build_id,
                                                     commit_sha=self.commit_sha)._definition(action))
        name = "book.screenplay." + action
        definition.update(name=name, handler_key="novel_forge.book.screenplay", handler_contract_version="screenplay-authority.v1",
            command_schema_version=name + ".command.v1", result_schema_version=name + ".result.v1",
            idempotency_scope="book:screenplay", output_contract={"type": "ScreenplayEvidence"},
            completion_contract={"version": "screenplay-authority.v1", "required_evidence": ["trace", "audit"], "required_outbox_events": [name]})
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.definitions.register(definition)
            inputs = self._admission_inputs(uow, action=action, project_id=project_id, workspace_id=workspace_id,
                book_run_id=book_run_id, data=data, idempotency_key=idempotency_key)
            uow.commit()
        payload = {"project_id": project_id, "workspace_id": workspace_id, "book_run_id": book_run_id, "action": action, "data": data}
        return execute_transaction_command(self.database_url, {
            "definition_name": name, "definition_version": "1.0.0", "project_id": project_id, "workspace_id": workspace_id,
            "actor_id": principal.principal_id, "idempotency_scope": "book:screenplay", "idempotency_key": idempotency_key,
            "trace_id": "screenplay:" + str(uuid4()), "span_id": str(uuid4()), "correlation_id": book_run_id,
            "causation_id": "", "input": payload, "input_assets": inputs},
            context=AdmissionContext(principal.principal_id, frozenset({"book.authority.execute"}),
                frozenset({definition["handler_key"]}), self.application_build_id, self.commit_sha), handler=self._handle)

    def _admission_inputs(self, uow, *, action, project_id, workspace_id, book_run_id, data, idempotency_key):
        uow.cursor.execute("""SELECT input_asset_snapshot FROM authority_operation
            WHERE idempotency_scope='book:screenplay' AND idempotency_key=%s AND project_id=%s""", [idempotency_key, project_id])
        previous = uow.cursor.fetchone()
        if previous is not None:
            return previous[0]
        repo = BookEditionRepository(uow.cursor)
        book = repo.book(project_id=project_id, workspace_id=workspace_id, book_run_id=book_run_id, for_update=False)
        inputs = []
        revision_id = data.get("source_revision_id") if action == "prepare" else data.get("replacement_revision_id") if action == "update" else None
        if revision_id:
            revision = repo.revision(project_id=project_id, book_id=book["book_id"], revision_id=str(revision_id), for_update=False)
            inputs.append({"asset_version_id": revision["revision_id"], "content_hash": revision["content_hash"]})
        fields = {"prepare": (("predecessor_source_id", SOURCE_TYPE), ("update_task_asset_version_id", "screenplay_update_task")),
            "accept": (("source_asset_version_id", SOURCE_TYPE), ("candidate_asset_version_id", CANDIDATE_TYPE), ("review_asset_version_id", REVIEW_TYPE)),
            "update": (("source_asset_version_id", SOURCE_TYPE),)}[action]
        for field, asset_type in fields:
            if not data.get(field) and action == "prepare":
                continue
            document = self._asset(uow, book, str(data.get(field) or ""), asset_type)
            inputs.append({"asset_version_id": document.asset_version_id, "content_hash": document.content_hash})
        return inputs

    def _handle(self, uow, operation_id, checkpoint):
        uow.cursor.execute("SELECT command_payload,trace_id FROM authority_operation WHERE operation_id=%s", [operation_id])
        payload, trace_id = uow.cursor.fetchone()
        data = payload["data"]
        repo = BookEditionRepository(uow.cursor)
        scope = {key: payload[key] for key in ("project_id", "workspace_id", "book_run_id")}
        book = repo.book(**scope, for_update=False)
        uow.cursor.execute("SELECT book_id FROM authority_book WHERE book_id=%s FOR UPDATE", [book["book_id"]])
        book = repo.book(**scope)
        if payload["action"] == "prepare":
            revision = repo.revision(project_id=book["project_id"], book_id=book["book_id"], revision_id=data["source_revision_id"])
            source = source_contract(revision_id=revision["revision_id"], manifest=revision["manifest"],
                selected_unit_ids=data.get("selected_unit_ids", []), scene_plan=data.get("scene_plan", []), policy=data.get("policy", {}),
                predecessor_source_id=str(data.get("predecessor_source_id") or ""),
                update_task_asset_version_id=str(data.get("update_task_asset_version_id") or ""))
            from .screenplay_sources import freeze_accepted_source
            source = freeze_accepted_source(uow, project_id=book["project_id"], source=source)
            require_validated_source(uow, project_id=book["project_id"], source=source)
            if source["workspace_id"] != book["workspace_id"]:
                raise KernelError("SCREENPLAY_WORKSPACE_CONFLICT", "The adaptation must retain the source workspace")
            if source["predecessor_source_id"]:
                previous = self._asset(uow, book, source["predecessor_source_id"], SOURCE_TYPE)
                task = self._asset(uow, book, source["update_task_asset_version_id"], "screenplay_update_task")
                if (task.content.get("source_asset_version_id") != previous.asset_version_id
                    or task.content.get("replacement_revision_id") != source["source_revision_id"]
                    or task.content.get("state") != "UPDATE_REQUIRED"):
                    raise KernelError("SCREENPLAY_UPDATE_TASK_INVALID", "A replacement must consume its exact native source invalidation task")
                if previous.content["source_revision_id"] == source["source_revision_id"]:
                    raise KernelError("SCREENPLAY_UPDATE_SOURCE_UNCHANGED", "A source update must name a new exact edition revision")
            document = self._write(uow, book, operation_id, trace_id, SOURCE_TYPE, source)
            result = {"source_asset_version_id": document.asset_version_id, "source_digest": source["source_digest"], "status": "PREPARED"}
        elif payload["action"] == "accept":
            source = self._asset(uow, book, data["source_asset_version_id"], SOURCE_TYPE)
            candidate = self._asset(uow, book, data["candidate_asset_version_id"], CANDIDATE_TYPE)
            review = self._asset(uow, book, data["review_asset_version_id"], REVIEW_TYPE)
            require_validated_source(uow, project_id=book["project_id"], source=source.content)
            if (candidate.content["source_asset_version_id"] != source.asset_version_id
                or review.content.get("candidate_asset_version_id") != candidate.asset_version_id
                or review.content.get("source_asset_version_id") != source.asset_version_id):
                raise KernelError("SCREENPLAY_ACCEPTANCE_SCOPE_INVALID", "Acceptance requires the exact candidate, source and native review")
            schema_fields = {key: review.content[key] for key in ("schema_version", "source_digest", "candidate_digest", "verdict", "reviewed_dimensions", "findings", "rationale")}
            if source.content["schema_version"] == "screenplay-source.v2":
                schema_fields["craft_checks"] = review.content["craft_checks"]
            validate_review(schema_fields, source.content, candidate.content)
            if review.content["verdict"] != "APPROVE":
                raise KernelError("SCREENPLAY_REVIEW_NOT_APPROVED", "A rejected, uncertain or unresolved screenplay remains a retained candidate")
            for item in (candidate, review):
                uow.cursor.execute("""SELECT o.status FROM authority_operation_output_asset a JOIN authority_operation o USING(operation_id)
                    WHERE a.asset_version_id=%s AND a.role='primary'""", [item.asset_version_id])
                if uow.cursor.fetchone() != ("SUCCEEDED",):
                    raise KernelError("SCREENPLAY_NATIVE_RESULT_REQUIRED", "Acceptance requires completed native generation and review operations")
            content = {"schema_version": "accepted-screenplay.v1", "book_id": book["book_id"],
                "source_asset_version_id": source.asset_version_id, "source_revision_id": source.content["source_revision_id"],
                "source_manifest_digest": source.content["source_manifest_digest"], "selected_unit_ids": source.content["selected_unit_ids"],
                "candidate_asset_version_id": candidate.asset_version_id, "candidate_digest": candidate.content["candidate_digest"],
                "review_asset_version_id": review.asset_version_id, "screenplay": candidate.content,
                "predecessor_source_id": source.content.get("predecessor_source_id", ""),
                "update_task_asset_version_id": source.content.get("update_task_asset_version_id", ""),
                "publication_authorized": False, "novel_canon_mutation_allowed": False,
                "craft_observations": review.content.get("craft_checks", []), "craft_observation_owner": "SCREENPLAY_VERSION_ONLY"}
            document = self._write(uow, book, operation_id, trace_id, ACCEPTED_TYPE, content)
            result = {"accepted_asset_version_id": document.asset_version_id, "status": "ACCEPTED", "publication_authorized": False}
        else:
            source = self._asset(uow, book, data["source_asset_version_id"], SOURCE_TYPE)
            old = repo.revision(project_id=book["project_id"], book_id=book["book_id"], revision_id=source.content["source_revision_id"])
            replacement = repo.revision(project_id=book["project_id"], book_id=book["book_id"], revision_id=data["replacement_revision_id"])
            changes = derived_invalidations(old["manifest"], replacement["manifest"], source.content["selected_unit_ids"])
            content = {"schema_version": "screenplay-source-update.v1", "book_id": book["book_id"],
                "source_asset_version_id": source.asset_version_id, "source_revision_id": old["revision_id"],
                "replacement_revision_id": replacement["revision_id"], "affected_units": changes,
                "state": "UPDATE_REQUIRED" if changes else "SOURCE_RANGE_UNCHANGED", "automatic_source_replacement": False}
            document = self._write(uow, book, operation_id, trace_id, "screenplay_update_task", content)
            result = {"update_task_asset_version_id": document.asset_version_id, **content}
        checkpoint("after_screenplay_evidence")
        uow.repositories.operation_graph.record_event({"event_id": str(uuid4()), "audit_id": str(uuid4()), "outbox_id": str(uuid4()),
            "aggregate_type": "book_screenplay", "aggregate_id": book["book_id"], "operation_id": operation_id,
            "project_id": book["project_id"], "event_type": "book.screenplay." + payload["action"],
            "correlation_id": book["book_run_id"], "causation_id": operation_id, "payload": {**result, "operation_id": operation_id}})
        return result

    @staticmethod
    def _write(uow, book, operation_id, trace_id, asset_type, content):
        return uow.repositories.asset_documents.materialize_output(AuthorityAssetWriteCommand(
            operation_id=operation_id, project_id=book["project_id"], asset_id="screenplay:" + str(uuid4()),
            asset_type=asset_type, schema_version=content["schema_version"], logical_ref="screenplay/" + operation_id,
            category="screenplay", output_key="screenplay.evidence", role="primary", content=content,
            qualification_policy="screenplay-authority.v1", trace_id=trace_id, correlation_id=book["book_run_id"], causation_id=operation_id))

    @staticmethod
    def _asset(uow, book, version, asset_type):
        document = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=version)
        if document.asset_type != asset_type or document.content.get("book_id") != book["book_id"]:
            raise KernelError("SCREENPLAY_ASSET_SCOPE_INVALID", "The exact typed same-Book asset is required")
        return document

    def admit(self, *, stage: str, project_id: str, workspace_id: str, source_asset_version_id: str,
              principal: Principal, idempotency_key: str, candidate_asset_version_id: str = "",
              review_asset_version_id: str = "") -> dict[str, Any]:
        principal.require("book.authority.execute", project_id)
        if stage not in SCREENPLAY_STAGES or self.followup is None:
            raise ValueError("A configured native screenplay stage is required")
        with AuthorityUnitOfWork(self.database_url) as uow:
            source = uow.repositories.asset_documents.require(project_id=project_id, asset_version_id=source_asset_version_id)
            if source.asset_type != SOURCE_TYPE or source.content["workspace_id"] != workspace_id:
                raise KernelError("SCREENPLAY_SOURCE_INVALID", "An exact same-workspace adaptation contract is required")
            require_validated_source(uow, project_id=project_id, source=source.content)
            inputs = [source]
            for version, kind in ((candidate_asset_version_id, CANDIDATE_TYPE), (review_asset_version_id, REVIEW_TYPE)):
                if version:
                    inputs.append(self._asset(uow, {"project_id": project_id, "book_id": source.content["book_id"]}, version, kind))
        expected = {SOURCE_TYPE} | ({CANDIDATE_TYPE} if stage != "screenplay_generate" else set()) | ({REVIEW_TYPE} if stage == "screenplay_revision" else set())
        if {item.asset_type for item in inputs} != expected:
            raise KernelError("SCREENPLAY_INPUT_REQUIRED", "The native stage requires its exact source, candidate and review inputs")
        result = self.followup.admit(BookFollowupCommand(stage, project_id, workspace_id, principal.principal_id,
            "screenplay:" + str(uuid4()), source.content["book_id"], idempotency_key,
            {"book_id": source.content["book_id"], "source_digest": source.content["source_digest"],
             "context_token_budget": source.content["policy"]["context_token_budget"]},
            tuple({"asset_version_id": item.asset_version_id, "content_hash": item.content_hash} for item in inputs)), principal=principal)
        return {"operation_id": result.operation_id, "project_id": project_id, "replayed": result.replayed}

    def run(self, *, project_id: str, operation_id: str, principal: Principal) -> dict[str, Any]:
        principal.require("book.authority.execute", project_id)
        if self.followup is None:
            raise ValueError("Native screenplay execution is not configured")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute("SELECT definition_name FROM authority_operation WHERE project_id=%s AND operation_id=%s", [project_id, operation_id])
            row = uow.cursor.fetchone()
            if row is None or row[0] not in SCREENPLAY_STAGES:
                raise KernelError("SCREENPLAY_OPERATION_SCOPE_INVALID", "Resume the original screenplay operation")
        self.followup.run_or_recover(BookFollowupAdmission(operation_id, project_id, True))
        return self.query(project_id=project_id, operation_id=operation_id, principal=principal)

    def query(self, *, project_id: str, principal: Principal, operation_id: str = "", asset_version_id: str = "") -> dict[str, Any]:
        principal.require("book.authority.query", project_id)
        with AuthorityUnitOfWork(self.database_url) as uow:
            if operation_id:
                uow.cursor.execute("SELECT status,definition_name FROM authority_operation WHERE project_id=%s AND operation_id=%s", [project_id, operation_id])
                row = uow.cursor.fetchone()
                if row is None or row[1] not in SCREENPLAY_STAGES:
                    raise KernelError("SCREENPLAY_OPERATION_SCOPE_INVALID", "Query requires the exact screenplay operation")
                uow.cursor.execute("SELECT asset_version_id FROM authority_operation_output_asset WHERE operation_id=%s AND role='primary'", [operation_id])
                outputs = [item[0] for item in uow.cursor.fetchall()]
                return {"operation_id": operation_id, "status": row[0], "outputs": outputs}
            document = uow.repositories.asset_documents.require(project_id=project_id, asset_version_id=asset_version_id)
            if document.asset_type not in {SOURCE_TYPE, CANDIDATE_TYPE, REVIEW_TYPE, ACCEPTED_TYPE, "screenplay_update_task"}:
                raise KernelError("SCREENPLAY_ASSET_SCOPE_INVALID", "Query requires a screenplay asset")
            result = {"asset_version_id": document.asset_version_id, "asset_type": document.asset_type, "content_hash": document.content_hash, "content": document.content}
            if document.asset_type in {CANDIDATE_TYPE, ACCEPTED_TYPE}:
                result["text"] = screenplay_text(document.content.get("screenplay", document.content))
            source_id = document.asset_version_id if document.asset_type == SOURCE_TYPE else document.content.get("source_asset_version_id")
            if source_id:
                uow.cursor.execute("""SELECT v.asset_version_id,v.content FROM authority_asset a JOIN authority_asset_version v USING(asset_id)
                    JOIN authority_book_edition_head h ON h.book_id=v.content->>'book_id'
                    WHERE a.project_id=%s AND a.asset_type='screenplay_update_task'
                    AND v.content->>'source_asset_version_id'=%s AND v.content->>'replacement_revision_id'=h.selected_revision_id""",
                    [project_id, source_id])
                result["source_update_tasks"] = [{"asset_version_id": row[0], **row[1]} for row in uow.cursor.fetchall()]
                result["source_update_state"] = "UPDATE_REQUIRED" if any(item["state"] == "UPDATE_REQUIRED" for item in result["source_update_tasks"]) else "SOURCE_RANGE_UNCHANGED"
            return result


def record_screenplay_source_invalidations(uow, *, book: dict[str, Any], replacement_revision_id: str,
                                          operation_id: str, trace_id: str) -> list[dict[str, Any]]:
    repo = BookEditionRepository(uow.cursor)
    replacement = repo.revision(project_id=book["project_id"], book_id=book["book_id"], revision_id=replacement_revision_id)
    uow.cursor.execute("""SELECT v.asset_version_id,v.content FROM authority_asset a JOIN authority_asset_version v USING(asset_id)
        WHERE a.project_id=%s AND a.asset_type=%s AND v.content->>'book_id'=%s
        AND v.content->>'source_revision_id'<>%s ORDER BY v.asset_version_id""",
        [book["project_id"], SOURCE_TYPE, book["book_id"], replacement_revision_id])
    sources = uow.cursor.fetchall()
    tasks = []
    for source_id, source in sources:
        original = repo.revision(project_id=book["project_id"], book_id=book["book_id"], revision_id=source["source_revision_id"])
        changes = derived_invalidations(original["manifest"], replacement["manifest"], source["selected_unit_ids"])
        if not changes:
            continue
        content = {"schema_version": "screenplay-source-update.v1", "book_id": book["book_id"],
            "source_asset_version_id": source_id, "source_revision_id": source["source_revision_id"],
            "replacement_revision_id": replacement_revision_id, "affected_units": changes,
            "state": "UPDATE_REQUIRED", "automatic_source_replacement": False}
        document = uow.repositories.asset_documents.materialize_output(AuthorityAssetWriteCommand(
            operation_id=operation_id, project_id=book["project_id"], asset_id="screenplay-update:" + str(uuid4()),
            asset_type="screenplay_update_task", schema_version="screenplay-source-update.v1",
            logical_ref="screenplay/updates/" + operation_id + "/" + source_id, category="screenplay",
            output_key="screenplay.update." + source_id, role="auxiliary", content=content,
            qualification_policy="screenplay-authority.v1", trace_id=trace_id, correlation_id=book["book_run_id"], causation_id=operation_id))
        tasks.append({"update_task_asset_version_id": document.asset_version_id, **content})
    return tasks
