from __future__ import annotations

from dataclasses import fields
import hashlib

from novel_forge.modules.chapter_authority.orchestrator import SingleChapterRequest
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.cancellation import (
    CancelCommand,
    request_cancellation,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.execution_template import (
    selected_book_template,
    verify_template_provenance,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

CONTRACT = "book-preprose-timeout-successor.v1"
BINDING = "chapter_execution_recovery"
COMMAND = "execution_replacement_chapter_command"


def source_evidence(cursor, *, book, request, principal):
    principal.require("book.authority.execute", book["project_id"])
    principal.require("chapter.authority.execute", book["project_id"])
    admission = selected_book_template(
        cursor, project_id=book["project_id"], book_id=book["book_id"]
    )
    if not admission:
        return None
    cursor.execute(
        "SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s AND project_id=%s FOR SHARE",
        [request["chapter_root_operation_id"], book["project_id"]],
    )
    row = cursor.fetchone()
    if not row:
        return None
    root = row[0]
    if (
        root["definition_version"] != "3.8.0"
        or root["command_payload"]
        .get("preparation_report", {})
        .get("author_draft_adoption")
        or root["actor_id"] != principal.principal_id
        or book["state"]
        not in {
            "CHAPTER_SUBMITTED",
            "CHAPTER_RUNNING",
            "CHAPTER_WAITING_RETRY",
            "CHAPTER_FAILED_RETRYABLE",
        }
        or book["active_chapter_request_id"] != request["chapter_request_id"]
        or request["chapter_number"] != book["accepted_through_chapter"] + 1
        or root["status"] not in {"WAITING_CHILDREN", "FAILED_RETRYABLE", "CANCELLED"}
    ):
        return None
    cursor.execute(
        """SELECT e.external_effect_id,e.status,e.request_hash,e.request_payload,e.last_error,r.status,o.definition_name,
            o.definition_snapshot->'timeout_policy'->>'operation_timeout_seconds'
        FROM authority_external_effect e JOIN authority_operation o USING(operation_id)
        JOIN authority_budget_reservation r USING(external_effect_id) WHERE o.root_operation_id=%s""",
        [root["operation_id"]],
    )
    effects = cursor.fetchall()
    if len(effects) != 1:
        return None
    effect, status, request_hash, payload, error, settlement, name, timeout = effects[0]
    process = (error or {}).get("production_execution", {})
    result = process.get("execution_result", {})
    decision = (
        (payload.get("_production_execution") or {})
        .get("capability_runtime", {})
        .get("routing_decision", {})
    )
    source_template = verify_template_provenance(cursor, decision)
    current = admission["policy_snapshot"]["policy"]["execution_templates"]
    target_template = next(t for t in current if t["book_id"] == book["book_id"])
    candidate = decision.get("selected", {}).get("candidate", {})
    if (
        status != "FAILED_RETRYABLE"
        or settlement != "SETTLED"
        or name != "chapter.memo.generate"
        or timeout != "60"
        or result.get("outcome") != "TIMED_OUT"
        or process.get("process_evidence", {}).get("failure_code") != "PROCESS_TIMEOUT"
        or result.get("output_manifest_ref")
        or result.get("normalized_output_ref")
        or candidate.get("provider") != "codex-cli"
        or candidate.get("pricing", {}).get("accounting_basis") != "ACCOUNT_ENTITLEMENT"
        or not source_template
        or source_template["mode"] != "CREATIVE_VALIDATION"
        or source_template["book_id"] != book["book_id"]
        or candidate.get("authorization_ref")
        != source_template["member_authorization_ref"]
        or source_template["require_literary_qualification"]
        or source_template["member_authorization_ref"]
        != target_template["member_authorization_ref"]
        or source_template["require_independent_review"]
        != target_template["require_independent_review"]
    ):
        return None
    cursor.execute(
        """SELECT EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id)
        JOIN authority_operation o USING(operation_id) WHERE o.root_operation_id=%s AND l.released_at IS NULL AND l.expires_at>NOW())""",
        [root["operation_id"]],
    )
    if cursor.fetchone()[0]:
        raise KernelError(
            "CHAPTER_TIMEOUT_RECOVERY_LEASE_HELD",
            "Wait for the original execution lease",
        )
    cursor.execute(
        "SELECT EXISTS(SELECT 1 FROM authority_book_chapter_acceptance WHERE chapter_request_id=%s)",
        [request["chapter_request_id"]],
    )
    if cursor.fetchone()[0]:
        return None
    return {
        "contract_version": CONTRACT,
        "predecessor_root_operation_id": root["operation_id"],
        "predecessor_request_id": request["chapter_request_id"],
        "external_effect_id": effect,
        "request_hash": request_hash,
        "original_failure": error,
        "policy_admission": admission,
        "target_definition_version": "3.9.0",
        "root": root,
    }


def recover_timeout(authority, *, book_run_id, principal):
    book = authority.require(book_run_id)
    if not book.get("active_chapter_request_id"):
        return False
    old = authority.require_chapter_request(book["active_chapter_request_id"])
    if old["command_payload"].get(COMMAND):
        resume_successor(
            authority, chapter_request_id=old["chapter_request_id"], principal=principal
        )
        return True
    with AuthorityUnitOfWork(authority.database_url) as uow:
        source = source_evidence(
            uow.cursor, book=book, request=old, principal=principal
        )
    if not source:
        return False
    root = source["root"]
    stable = (
        "chapter-timeout:"
        + hashlib.sha256(old["chapter_request_id"].encode()).hexdigest()
    )
    if root["status"] != "CANCELLED":
        cancelled = request_cancellation(
            authority.database_url,
            CancelCommand(
                operation_id=root["operation_id"],
                project_id=book["project_id"],
                actor_id=principal.principal_id,
                expected_version=root["version"],
                reason="known stopped pre-prose Memo timeout; native execution contract successor",
                idempotency_key=stable + ":cancel",
                trace_id=stable,
                correlation_id=book["root_operation_id"],
            ),
            settle_undispatched=True,
        )
        if cancelled["status"] != "CANCELLED":
            raise KernelError(
                "CHAPTER_TIMEOUT_RECOVERY_CANCELLATION_PENDING",
                "Preserve predecessor until native cancellation completes",
            )
    new_id = "chapter-request:" + stable

    def reserve(uow, operation_id, checkpoint):
        uow.cursor.execute(
            "SELECT to_jsonb(b) FROM authority_book_production b WHERE book_run_id=%s FOR UPDATE",
            [book_run_id],
        )
        current = uow.cursor.fetchone()[0]
        uow.cursor.execute(
            "SELECT to_jsonb(r) FROM authority_book_chapter_request r WHERE chapter_request_id=%s FOR UPDATE",
            [old["chapter_request_id"]],
        )
        predecessor = uow.cursor.fetchone()[0]
        proof = source_evidence(
            uow.cursor, book=current, request=predecessor, principal=principal
        )
        if (
            current["version"] != book["version"]
            or not proof
            or proof["root"]["status"] != "CANCELLED"
        ):
            raise KernelError(
                "CHAPTER_TIMEOUT_RECOVERY_CONFLICT",
                "Reload exact source Book and stopped execution",
            )
        binding = {
            "contract_version": CONTRACT,
            "book_run_id": book_run_id,
            "chapter_request_id": new_id,
            "predecessor_request_id": old["chapter_request_id"],
            "predecessor_root_operation_id": root["operation_id"],
            "generation": predecessor["generation"] + 1,
        }
        frozen = {
            **root["command_payload"],
            "project_id": book["project_id"],
            "workspace_id": book["workspace_id"],
            "book_id": book["book_id"],
            "actor_id": principal.principal_id,
            "idempotency_key": stable,
            "application_build_id": authority.application_build_id,
            "commit_sha": authority.commit_sha,
            "trace_id": stable,
            "correlation_id": book["root_operation_id"],
            "preparation_report": {
                **root["command_payload"].get("preparation_report", {}),
                BINDING: binding,
            },
        }
        payload = {
            **predecessor["command_payload"],
            "preparation_report": frozen["preparation_report"],
            COMMAND: frozen,
        }
        uow.repositories.book_authority.create_chapter_request(
            {
                **predecessor,
                "chapter_request_id": new_id,
                "stable_idempotency_key": stable,
                "command_payload": payload,
            },
            generation=binding["generation"],
            predecessor_request_id=old["chapter_request_id"],
        )
        uow.cursor.execute(
            "UPDATE authority_child_delegation SET superseded_at=NOW(),version=version+1,updated_at=NOW() WHERE chapter_request_id=%s AND superseded_at IS NULL AND status<>'ACCEPTED'",
            [old["chapter_request_id"]],
        )
        uow.cursor.execute(
            "UPDATE authority_book_production SET active_chapter_request_id=%s,active_child_delegation_id=NULL,state='CHAPTER_SUBMITTED',version=version+1,updated_at=NOW() WHERE book_run_id=%s AND version=%s",
            [new_id, book_run_id, book["version"]],
        )
        if uow.cursor.rowcount != 1:
            raise KernelError(
                "CHAPTER_TIMEOUT_RECOVERY_CONFLICT", "Book checkpoint changed"
            )
        proof.pop("root")
        evidence = uow.repositories.asset_documents.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=operation_id,
                project_id=book["project_id"],
                asset_id="execution-recovery:" + operation_id,
                asset_type="chapter_execution_recovery",
                schema_version=CONTRACT,
                logical_ref="execution-recoveries/" + operation_id,
                category="execution-recovery",
                output_key="book.execution_recovery",
                role="completion_evidence",
                content={
                    **binding,
                    "source": proof,
                    "predecessor_request": predecessor,
                    "provider_invoked": False,
                    "book_acceptance": "NOT_GRANTED",
                    "author_decision": "NOT_RUN",
                },
                qualification_policy=CONTRACT,
                trace_id=stable,
                correlation_id=book["root_operation_id"],
            )
        )
        checkpoint("after_timeout_successor_reservation")
        return {
            "chapter_request_id": new_id,
            "evidence_asset_version_id": evidence.asset_version_id,
        }

    authority._execute_mutation(
        book=book,
        action="chapter_timeout_successor",
        event_type="book.chapter.execution_successor_reserved",
        idempotency_key=stable + ":reserve",
        actor_id=principal.principal_id,
        trace_id=stable,
        correlation_id=book["root_operation_id"],
        causation_id=root["operation_id"],
        payload={"predecessor_request_id": old["chapter_request_id"]},
        handler=reserve,
    )
    resume_successor(authority, chapter_request_id=new_id, principal=principal)
    return True


def require_dispatch(database_url, *, command_payload, root_operation_id):
    binding = (command_payload.get("preparation_report") or {}).get(BINDING)
    if binding is None:
        return
    required = {
        "contract_version",
        "book_run_id",
        "chapter_request_id",
        "predecessor_request_id",
        "predecessor_root_operation_id",
        "generation",
    }
    if (
        not isinstance(binding, dict)
        or set(binding) != required
        or binding.get("contract_version") != CONTRACT
        or type(binding.get("generation")) is not int
        or binding["generation"] < 2
        or any(
            not isinstance(binding[k], str) or not binding[k]
            for k in required - {"generation"}
        )
    ):
        raise KernelError(
            "CHAPTER_TIMEOUT_SUCCESSOR_UNLINKED",
            "Invalid native execution successor binding",
        )
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """SELECT r.chapter_root_operation_id,b.active_chapter_request_id,r.generation,r.predecessor_request_id,
            b.accepted_through_chapter,r.chapter_number,r.command_payload,d.superseded_at,d.delegation_id,
            p.status,EXISTS(SELECT 1 FROM authority_book_chapter_acceptance a WHERE a.chapter_request_id=r.chapter_request_id)
            FROM authority_book_chapter_request r JOIN authority_book_production b USING(book_run_id)
            JOIN authority_child_delegation d USING(chapter_request_id)
            JOIN authority_operation p ON p.operation_id=%s WHERE r.chapter_request_id=%s AND r.book_run_id=%s""",
            [
                binding["predecessor_root_operation_id"],
                binding["chapter_request_id"],
                binding["book_run_id"],
            ],
        )
        row = uow.cursor.fetchone()
    if (
        binding.get("contract_version") != CONTRACT
        or not row
        or row[0] != root_operation_id
        or row[2] != binding["generation"]
        or row[3] != binding["predecessor_request_id"]
        or row[6].get("preparation_report", {}).get(BINDING) != binding
        or row[9] != "CANCELLED"
        or row[7] is not None
        or (
            not row[10]
            and (row[1] != binding["chapter_request_id"] or row[4] >= row[5])
        )
    ):
        raise KernelError(
            "CHAPTER_TIMEOUT_SUCCESSOR_UNLINKED",
            "Execution successor must retain its exact native Book binding",
        )


def resume_successor(authority, *, chapter_request_id, principal):
    request = authority.require_chapter_request(chapter_request_id)
    principal.require("book.authority.execute", request["project_id"])
    frozen = request["command_payload"][COMMAND]
    if request["chapter_root_operation_id"]:
        return request
    book = authority.require(request["book_run_id"])
    if book["active_chapter_request_id"] != chapter_request_id:
        raise KernelError(
            "CHAPTER_TIMEOUT_RECOVERY_CONFLICT",
            "Successor is not the current Book child",
        )
    command = {
        f.name: frozen[f.name] for f in fields(SingleChapterRequest) if f.name in frozen
    }
    command["context_candidates"] = tuple(command.get("context_candidates") or ())
    admission = authority.chapter_port.submit(
        SingleChapterRequest(**command), principal=principal
    )
    current = authority.require(book["book_run_id"])
    delegation = "child-delegation:" + request["stable_idempotency_key"]

    def link(uow, operation_id, checkpoint):
        uow.repositories.book_authority.link_chapter(
            chapter_request_id=chapter_request_id,
            book_run_id=book["book_run_id"],
            project_id=book["project_id"],
            chapter_number=request["chapter_number"],
            chapter_plan_version=request["chapter_plan_version"],
            stable_idempotency_key=request["stable_idempotency_key"],
            delegation_id=delegation,
            root_operation_id=admission.root_operation_id,
            saga_id=admission.saga_id,
            expected_book_version=current["version"],
        )
        from novel_forge.modules.chapter_group_authority.author_revision import (
            replace_unaccepted_child_reference,
        )

        replace_unaccepted_child_reference(
            uow,
            request=request,
            root_operation_id=admission.root_operation_id,
            delegation_id=delegation,
            binding_key=BINDING,
        )
        checkpoint("after_timeout_successor_link")
        return {
            "chapter_request_id": chapter_request_id,
            "chapter_root_operation_id": admission.root_operation_id,
        }

    authority._execute_mutation(
        book=current,
        action="chapter_timeout_successor_link",
        event_type="book.chapter.execution_successor_linked",
        idempotency_key=request["stable_idempotency_key"] + ":link",
        actor_id=principal.principal_id,
        trace_id=request["stable_idempotency_key"],
        correlation_id=book["root_operation_id"],
        causation_id=admission.root_operation_id,
        payload={"chapter_request_id": chapter_request_id},
        handler=link,
    )
    return authority.require_chapter_request(chapter_request_id)
