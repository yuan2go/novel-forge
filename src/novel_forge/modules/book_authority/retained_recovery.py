from __future__ import annotations

import hashlib
from dataclasses import fields

from novel_forge.modules.chapter_authority.orchestrator import SingleChapterRequest
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.step_successor import require_live_chapter_frontier
from novel_forge.modules.command_kernel.retained_graph import (
    BINDING,
    CONTRACT,
    source_graph,
    continue_graph_in_uow,
)
from novel_forge.modules.command_kernel.service import AdmissionContext
from novel_forge.modules.production_execution.execution_template import (
    selected_book_template,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def _require_frontier(cursor, *, book, request, root, principal):
    if (book["state"] in {"ABORTED", "COMPLETED", "CANCELLED"}
        or book["active_chapter_request_id"] != request["chapter_request_id"]
        or request["book_run_id"] != book["book_run_id"] or request["project_id"] != book["project_id"]
        or request["chapter_number"] != book["accepted_through_chapter"] + 1
        or request["status_reference"] == "CANCELLED"
        or root["operation_id"] != request["chapter_root_operation_id"]
        or root["project_id"] != book["project_id"] or root["workspace_id"] != book["workspace_id"]
        or root["actor_id"] != principal.principal_id
        or root["definition_name"] != "chapter.slice.run" or root["definition_version"] not in {"3.9.0", "3.10.0"}
        or root["status"] not in {"FAILED_FINAL", "SUCCEEDED"}
        or root["command_payload"].get("book_id") != book["book_id"]
        or root["command_payload"].get("chapter") != request["chapter_number"]):
        raise KernelError("RETAINED_GRAPH_BOOK_CONFLICT", "Retain the exact original actor and live unaccepted Book frontier")
    require_live_chapter_frontier(cursor, root_id=root["operation_id"], project_id=book["project_id"], book_run_id=book["book_run_id"])


def recover_retained_quality(authority, *, book_run_id, principal):
    book = authority.require(book_run_id)
    if not book.get("active_chapter_request_id"):
        return False
    old = authority.require_chapter_request(book["active_chapter_request_id"])
    principal.require("book.authority.execute", book["project_id"])
    principal.require("chapter.authority.execute", book["project_id"])
    with AuthorityUnitOfWork(authority.database_url) as uow:
        c = uow.cursor
        c.execute(
            "SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s",
            [old["chapter_root_operation_id"]],
        )
        row = c.fetchone()
        if not row or row[0]["status"] not in {"FAILED_FINAL", "SUCCEEDED"}:
            return False
        root = row[0]
        _require_frontier(c, book=book, request=old, root=root, principal=principal)
        if root["status"] == 'SUCCEEDED':
            c.execute("""SELECT EXISTS(SELECT 1 FROM authority_operation o JOIN authority_attempt a USING(operation_id)
                WHERE o.root_operation_id=%s AND o.definition_name='chapter.canon.extract' AND o.definition_version IN ('3.9.21','3.10.0')
                AND o.status='FAILED_RETRYABLE' AND a.result->>'error_code'='PROVIDER_ROUTING_BLOCKED'
                AND NOT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=o.operation_id))""",[old['chapter_root_operation_id']])
            if not c.fetchone()[0]:
                return False
        c.execute(
            "SELECT to_jsonb(r) FROM authority_book_chapter_request r WHERE chapter_request_id=%s",
            [old["chapter_request_id"]],
        )
        old = c.fetchone()[0]
        admission = selected_book_template(
            c, project_id=book["project_id"], book_id=book["book_id"]
        )
        if not admission:
            return False
        template = next(
            t
            for t in admission["policy_snapshot"]["policy"]["execution_templates"]
            if t["book_id"] == book["book_id"]
        )
        if (
            template.get("chapter_graph_recovery")
            not in {"RETAIN_SETTLED_QUALITY_RANGE_RESULT", "RETAIN_SETTLED_QUALITY_RESULT", "RETAIN_SETTLED_CREATIVE_RESULT"}
            or template["mode"] != "CREATIVE_VALIDATION"
        ):
            return False
        if template.get("chapter_graph_recovery") == "RETAIN_SETTLED_QUALITY_RANGE_RESULT" and (old["command_payload"].get("preparation_report") or {}).get(BINDING):
            return False
        source = source_graph(
            c,
            root_id=old["chapter_root_operation_id"],
            project_id=book["project_id"],
            actor_id=principal.principal_id,
        )
    stable = (
        "retained-graph:"
        + hashlib.sha256(old["chapter_request_id"].encode()).hexdigest()
    )
    new_id = "chapter-request:" + stable

    def reserve(uow, operation_id, checkpoint):
        c = uow.cursor
        c.execute(
            "SELECT to_jsonb(b) FROM authority_book_production b WHERE book_run_id=%s FOR UPDATE",
            [book_run_id],
        )
        current = c.fetchone()[0]
        c.execute("SELECT to_jsonb(r) FROM authority_book_chapter_request r WHERE chapter_request_id=%s FOR UPDATE", [old["chapter_request_id"]])
        current_request = c.fetchone()[0]
        if (
            current["version"] != book["version"]
            or current["active_chapter_request_id"] != old["chapter_request_id"]
            or current["accepted_through_chapter"] + 1 != old["chapter_number"]
        ):
            raise KernelError(
                "RETAINED_GRAPH_BOOK_CONFLICT",
                "Resume only the current unaccepted Book frontier",
            )
        if current_request != old:
            raise KernelError("RETAINED_GRAPH_BOOK_CONFLICT", "Retain the exact predecessor request snapshot")
        _require_frontier(c, book=current, request=current_request, root=source["root"], principal=principal)
        c.execute(
            "SELECT EXISTS(SELECT 1 FROM authority_book_chapter_acceptance WHERE chapter_request_id=%s)",
            [old["chapter_request_id"]],
        )
        if c.fetchone()[0]:
            raise KernelError(
                "RETAINED_GRAPH_BOOK_ALREADY_ACCEPTED",
                "Accepted chapters cannot be regenerated",
            )
        binding = {
            "contract_version": CONTRACT,
            "book_run_id": book_run_id,
            "chapter_request_id": new_id,
            "predecessor_request_id": old["chapter_request_id"],
            "predecessor_root_operation_id": source["root"]["operation_id"],
            "generation": old["generation"] + 1,
            "admission": admission,
            "retained_result": source["retained_result"],
        }
        prep = {**source["root"]["command_payload"].get("preparation_report", {})}
        prep.pop("chapter_execution_recovery", None)
        prep.pop("chapter_execution_recovery_v2", None)
        prep[BINDING] = binding
        frozen = {
            **source["root"]["command_payload"],
            "project_id": book["project_id"],
            "workspace_id": book["workspace_id"],
            "book_id": book["book_id"],
            "actor_id": principal.principal_id,
            "idempotency_key": stable,
            "trace_id": stable,
            "correlation_id": book["root_operation_id"],
            "application_build_id": authority.application_build_id,
            "commit_sha": authority.commit_sha,
            "preparation_report": prep,
        }
        command = {
            f.name: frozen[f.name]
            for f in fields(SingleChapterRequest)
            if f.name in frozen
        }
        command["context_candidates"] = tuple(command.get("context_candidates") or ())
        request = SingleChapterRequest(**command)
        context = AdmissionContext(
            principal.principal_id,
            principal.permissions,
            frozenset({source["root"]["definition_snapshot"]["handler_key"]}),
            authority.application_build_id,
            authority.commit_sha,
        )
        result = continue_graph_in_uow(
            uow, source=source, request=request, context=context
        )
        payload = {**old["command_payload"], "preparation_report": prep}
        for key in (
            "execution_replacement_chapter_command",
            "execution_replacement_chapter_command_v2",
            "author_replacement_chapter_command",
        ):
            payload.pop(key, None)
        uow.repositories.book_authority.create_chapter_request(
            {
                **old,
                "chapter_request_id": new_id,
                "stable_idempotency_key": stable,
                "command_payload": payload,
            },
            generation=binding["generation"],
            predecessor_request_id=old["chapter_request_id"],
        )
        c.execute(
            "UPDATE authority_child_delegation SET superseded_at=NOW(),version=version+1,updated_at=NOW() WHERE chapter_request_id=%s AND superseded_at IS NULL AND status<>'ACCEPTED'",
            [old["chapter_request_id"]],
        )
        c.execute(
            "UPDATE authority_book_production SET active_chapter_request_id=%s,active_child_delegation_id=NULL,state='CHAPTER_SUBMITTED',version=version+1,updated_at=NOW() WHERE book_run_id=%s AND version=%s",
            [new_id, book_run_id, book["version"]],
        )
        if c.rowcount != 1:
            raise KernelError("RETAINED_GRAPH_BOOK_CONFLICT", "Book checkpoint changed before native child linking")
        delegation = "child-delegation:" + stable
        uow.repositories.book_authority.link_chapter(
            chapter_request_id=new_id,
            book_run_id=book_run_id,
            project_id=book["project_id"],
            chapter_number=old["chapter_number"],
            chapter_plan_version=old["chapter_plan_version"],
            stable_idempotency_key=stable,
            delegation_id=delegation,
            root_operation_id=result["root_operation_id"],
            saga_id=result["saga_id"],
            expected_book_version=book["version"] + 1,
        )
        from novel_forge.modules.chapter_group_authority.author_revision import (
            replace_unaccepted_child_reference,
        )

        replace_unaccepted_child_reference(
            uow,
            request={**old, "chapter_request_id": new_id, "command_payload": payload},
            root_operation_id=result["root_operation_id"],
            delegation_id=delegation,
            binding_key=BINDING,
        )
        checkpoint("after_retained_graph_link")
        return {"chapter_request_id": new_id, **result}

    authority._execute_mutation(
        book=book,
        action="retained_graph_continuation",
        event_type="book.chapter.retained_graph_continued",
        idempotency_key=stable,
        actor_id=principal.principal_id,
        trace_id=stable,
        correlation_id=book["root_operation_id"],
        causation_id=source["root"]["operation_id"],
        payload={"predecessor_request_id": old["chapter_request_id"]},
        handler=reserve,
    )
    return True
