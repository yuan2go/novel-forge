# INVARIANT: A known stopped local process leaves remote usage UNKNOWN.

from __future__ import annotations

from dataclasses import fields
from types import SimpleNamespace

from novel_forge.modules.capability_packs.schema import canonical_json
from novel_forge.modules.capability_pack_authority.runtime import (
    CapabilityPackResolutionRequest, CapabilityPackRuntimeResolver,
)
import hashlib

from novel_forge.modules.chapter_authority.orchestrator import SingleChapterRequest
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.cancellation import (
    CancelCommand,
    request_cancellation,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.step_successor import require_live_chapter_frontier
from novel_forge.modules.production_execution.execution_template import (
    selected_book_template,
    verify_template_provenance,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

CONTRACT = "book-preprose-timeout-successor.v2"
BINDING = "chapter_execution_recovery_v2"
COMMAND = "execution_replacement_chapter_command_v2"


def _cancellation_key(request_id):
    return "chapter-timeout-v2:" + hashlib.sha256(request_id.encode()).hexdigest() + ":cancel"


def _require_recovery_cancellation(cursor, *, root, request_id, actor_id):
    cursor.execute(
        """SELECT COUNT(*),COUNT(*) FILTER (WHERE idempotency_key=%s AND actor_id=%s)
        FROM authority_cancellation_command WHERE operation_id=%s""",
        [_cancellation_key(request_id), actor_id, root["operation_id"]],
    )
    if cursor.fetchone() != (1, 1):
        raise KernelError("CHAPTER_TIMEOUT_RECOVERY_CONFLICT", "Retain only the exact owned recovery cancellation")


def _timeout_effects(cursor, *, root, target_template):
    cursor.execute(
        """SELECT EXISTS(SELECT 1 FROM authority_external_effect e JOIN authority_operation o USING(operation_id)
            LEFT JOIN authority_budget_reservation r USING(external_effect_id)
            WHERE o.root_operation_id=%s AND (e.status IN ('UNKNOWN','DISPATCHING','RECONCILIATION_REQUIRED','INTENT_RECORDED')
                OR r.status IS DISTINCT FROM 'SETTLED'))
            OR EXISTS(SELECT 1 FROM authority_operation o WHERE o.root_operation_id=%s
                AND (o.status IN ('UNKNOWN','RECONCILIATION_REQUIRED','CANCELLATION_REQUESTED','RUNNING','WAITING_EXTERNAL_RESULT')
                    OR o.project_id<>%s OR o.workspace_id<>%s OR o.actor_id<>%s))
            OR EXISTS(SELECT 1 FROM authority_attempt a JOIN authority_operation o USING(operation_id)
                WHERE o.root_operation_id=%s AND a.status IN ('UNKNOWN','RUNNING','WAITING_EXTERNAL_RESULT','RECONCILIATION_REQUIRED')),
            EXISTS(SELECT 1 FROM authority_budget_reservation r JOIN authority_operation o USING(operation_id)
                WHERE o.root_operation_id=%s AND r.status IS DISTINCT FROM 'SETTLED'),
            EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id)
                JOIN authority_operation o USING(operation_id) WHERE o.root_operation_id=%s
                AND l.released_at IS NULL AND l.expires_at>NOW())""",
        [root["operation_id"],root["operation_id"],root["project_id"],root["workspace_id"],root["actor_id"],
         root["operation_id"],root["operation_id"],root["operation_id"]],
    )
    unresolved, unsettled, lease = cursor.fetchone()
    if unresolved or unsettled or lease:
        raise KernelError("CHAPTER_TIMEOUT_RECOVERY_UNRECONCILED", "Reconcile the complete source graph and release every execution lease")
    cursor.execute(
        """SELECT e.external_effect_id,e.status,e.request_hash,e.request_payload,e.last_error,r.status,
            o.definition_name,o.definition_snapshot->'timeout_policy'->>'operation_timeout_seconds',
            o.definition_snapshot->'retry_policy'->>'max_attempts',o.operation_id,a.attempt_number,
            o.project_id,o.workspace_id,o.actor_id,o.definition_version
        FROM authority_external_effect e JOIN authority_operation o USING(operation_id)
        LEFT JOIN authority_budget_reservation r USING(external_effect_id)
        LEFT JOIN authority_attempt a ON a.attempt_id=e.request_payload #>> '{_production_execution,attempt_id}'
            AND a.operation_id=o.operation_id
        WHERE o.root_operation_id=%s ORDER BY a.attempt_number,e.external_effect_id""",
        [root["operation_id"]],
    )
    effects = cursor.fetchall()
    if len(effects) < 2:
        return None
    receipts = []
    operation_ids, attempt_numbers, bounds, pack_refs = set(), [], set(), set()
    for effect, status, request_hash, payload, error, settlement, name, timeout, bound, operation_id, number, project, workspace, actor, version in effects:
        process = (error or {}).get("production_execution", {})
        result = process.get("execution_result", {})
        runtime = (payload.get("_production_execution") or {}).get("capability_runtime", {})
        decision = runtime.get("routing_decision", {})
        source_template = verify_template_provenance(cursor, decision)
        candidate = decision.get("selected", {}).get("candidate", {})
        if (not runtime.get("pack_ref") or not request_hash or status != "FAILED_RETRYABLE"
            or settlement != "SETTLED" or name != "chapter.memo.generate" or version != "3.8.0" or timeout != "60"
            or bound != "2" or len(effects) != 2 or type(number) is not int
            or (project, workspace, actor) != (root["project_id"], root["workspace_id"], root["actor_id"])
            or result.get("outcome") != "TIMED_OUT"
            or process.get("process_evidence", {}).get("failure_code") != "PROCESS_TIMEOUT"
            or not result.get("process_receipt_ref")
            or any(result.get(key) for key in ("output_manifest_ref", "normalized_output_ref", "raw_output_ref", "provider_receipt_ref", "external_receipt_ref"))
            or candidate.get("provider") != "codex-cli"
            or candidate.get("pricing", {}).get("accounting_basis") != "ACCOUNT_ENTITLEMENT"
            or not source_template or source_template["mode"] != "CREATIVE_VALIDATION"
            or source_template["book_id"] != root["command_payload"]["book_id"]
            or candidate.get("authorization_ref") != source_template["member_authorization_ref"]
            or source_template["require_literary_qualification"]
            or source_template["member_authorization_ref"] != target_template["member_authorization_ref"]
            or source_template["require_independent_review"] != target_template["require_independent_review"]):
            return None
        operation_ids.add(operation_id)
        attempt_numbers.append(number)
        bounds.add(int(bound))
        pack_refs.add(runtime["pack_ref"])
        receipts.append({"external_effect_id": effect, "request_hash": request_hash,
            "original_failure": error, "reservation_status": settlement,
            "remote_usage": "UNKNOWN", "local_outcome": "TIMED_OUT", "pack_ref": runtime["pack_ref"],
            "attempt_number": number, "operation_id": operation_id})
    if (len(operation_ids) != 1 or len(bounds) != 1 or len(pack_refs) != 1
        or attempt_numbers != list(range(1, len(effects) + 1))
        or len({r["external_effect_id"] for r in receipts}) != len(receipts)):
        return None
    return receipts


def _current_template(cursor, *, book):
    admission = selected_book_template(cursor, project_id=book["project_id"], book_id=book["book_id"])
    if not admission:
        return None, None
    target = next((t for t in admission["policy_snapshot"]["policy"]["execution_templates"]
                   if t["book_id"] == book["book_id"]), None)
    if (not target or target.get("version") != "creative-execution-template.v11"
        or target.get("mode") != "CREATIVE_VALIDATION" or target.get("require_literary_qualification")):
        return None, None
    return admission, target


def _source_proof(root, request, admission, receipts):
    return {"contract_version": CONTRACT, "predecessor_root_operation_id": root["operation_id"],
        "predecessor_request_id": request["chapter_request_id"], "effects": receipts,
        "policy_admission": admission, "target_definition_version": "3.10.0"}


def _proof_digest(proof):
    return "sha256:" + hashlib.sha256(canonical_json(proof).encode()).hexdigest()


def source_evidence(cursor, *, book, request, principal):
    principal.require("book.authority.execute", book["project_id"])
    principal.require("chapter.authority.execute", book["project_id"])
    admission, template = _current_template(cursor, book=book)
    if not template:
        return None
    cursor.execute("SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s AND project_id=%s FOR SHARE",
        [request["chapter_root_operation_id"], book["project_id"]])
    row = cursor.fetchone()
    if not row:
        return None
    root = row[0]
    if (root["definition_version"] != "3.8.0" or root["definition_name"] != "chapter.slice.run"
        or root["command_payload"].get("preparation_report", {}).get("author_draft_adoption")
        or root["actor_id"] != principal.principal_id
        or book["state"] not in {"CHAPTER_SUBMITTED", "CHAPTER_RUNNING", "CHAPTER_WAITING_RETRY", "CHAPTER_FAILED_RETRYABLE"}
        or book["active_chapter_request_id"] != request["chapter_request_id"]
        or request["chapter_number"] != book["accepted_through_chapter"] + 1
        or root["status"] not in {"WAITING_CHILDREN", "FAILED_RETRYABLE", "CANCELLED"}):
        return None
    if (root["project_id"] != book["project_id"] or root["workspace_id"] != book["workspace_id"]
        or request["project_id"] != book["project_id"] or request["book_run_id"] != book["book_run_id"]
        or root["command_payload"].get("book_id") != book["book_id"]
        or root["command_payload"].get("chapter") != request["chapter_number"]):
        raise KernelError("CHAPTER_TIMEOUT_RECOVERY_SCOPE_INVALID", "Retain the exact original Chapter and Book scope")
    require_live_chapter_frontier(cursor, root_id=root["operation_id"], project_id=book["project_id"], book_run_id=book["book_run_id"])
    if root["status"] == "CANCELLED":
        _require_recovery_cancellation(cursor, root=root, request_id=request["chapter_request_id"], actor_id=principal.principal_id)
    receipts = _timeout_effects(cursor, root=root, target_template=template)
    if not receipts:
        return None
    cursor.execute("SELECT EXISTS(SELECT 1 FROM authority_book_chapter_acceptance WHERE chapter_request_id=%s)", [request["chapter_request_id"]])
    if cursor.fetchone()[0]:
        return None
    return {**_source_proof(root, request, admission, receipts), "root": root}


def recover_timeout(authority, *, book_run_id, principal):
    book = authority.require(book_run_id)
    if not book.get("active_chapter_request_id"):
        return False
    old = authority.require_chapter_request(book["active_chapter_request_id"])
    if old["command_payload"].get(COMMAND):
        if old["chapter_root_operation_id"]:
            return False
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
    pack_ids = {receipt["pack_ref"].rpartition("@")[0] for receipt in source["effects"]}
    if len(pack_ids) != 1 or not all(pack_ids):
        raise KernelError("CHAPTER_TIMEOUT_RECOVERY_PACK_DRIFT", "Retain one source Memo Pack")
    snapshot = CapabilityPackRuntimeResolver(authority.database_url).resolve_active_deployment(
        CapabilityPackResolutionRequest(project_id=book["project_id"], workspace_id=book["workspace_id"],
            book_id=book["book_id"], workflow_definition_ref="chapter_authority_slice@3.10.0",
            workflow_node_id="memo", environment="validation", runtime_profile="validation",
            release_channel="VALIDATION", release_sha=authority.commit_sha,
            operation_definition_ref="chapter.memo.generate@3.10.0", pack_id=next(iter(pack_ids))))
    if snapshot.execution_capability_id != "planning.chapter.memo" or snapshot.pack_version != "3.0.0":
        raise KernelError("CHAPTER_TIMEOUT_RECOVERY_PACK_DRIFT", "Require the current versioned Memo Pack")
    root = source["root"]
    stable = (
        "chapter-timeout-v2:"
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
            or proof['predecessor_root_operation_id'] != root['operation_id']
            or proof['predecessor_request_id'] != old['chapter_request_id']
            or {k: v for k, v in proof.items() if k != 'root'} != {k: v for k, v in source.items() if k != 'root'}
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
            "source_digest": _proof_digest({k: v for k, v in proof.items() if k != "root"}),
            "target_definition_version": "3.10.0",
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


def _validate_binding(binding):
    required = {"contract_version", "book_run_id", "chapter_request_id", "predecessor_request_id",
        "predecessor_root_operation_id", "generation", "source_digest", "target_definition_version"}
    if (not isinstance(binding, dict) or set(binding) != required
        or binding.get("contract_version") != CONTRACT or binding.get("target_definition_version") != "3.10.0"
        or type(binding.get("generation")) is not int or binding["generation"] < 2
        or any(not isinstance(binding[k], str) or not binding[k] for k in required - {"generation"})):
        raise KernelError("CHAPTER_TIMEOUT_SUCCESSOR_UNLINKED", "Invalid native execution successor binding")


def require_dispatch(database_url, *, command_payload, root_operation_id):
    binding = (command_payload.get("preparation_report") or {}).get(BINDING)
    if binding is None:
        return
    _validate_binding(binding)
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("""SELECT to_jsonb(b),to_jsonb(r),to_jsonb(n),to_jsonb(d)
            FROM authority_book_production b JOIN authority_book_chapter_request r USING(book_run_id)
            JOIN authority_operation n ON n.operation_id=r.chapter_root_operation_id
            JOIN authority_child_delegation d USING(chapter_request_id)
            WHERE r.chapter_request_id=%s AND b.book_run_id=%s FOR UPDATE OF b,r""",
            [binding["chapter_request_id"], binding["book_run_id"]])
        row = uow.cursor.fetchone()
        if not row:
            raise KernelError("CHAPTER_TIMEOUT_SUCCESSOR_UNLINKED", "Retain the exact native Book delegation")
        book, request, root, delegation = row
        if (request["chapter_root_operation_id"] != root_operation_id
            or root["operation_id"] != root_operation_id or root["project_id"] != book["project_id"]
            or root["workspace_id"] != book["workspace_id"] or root["definition_name"] != "chapter.slice.run"
            or root["definition_version"] != binding["target_definition_version"]
            or root["command_payload"] != command_payload or delegation["superseded_at"] is not None
            or delegation["owner_id"] != book["book_run_id"] or delegation["child_root_operation_id"] != root_operation_id):
            raise KernelError("CHAPTER_TIMEOUT_SUCCESSOR_UNLINKED", "Retain the exact current Chapter and delegation identity")
        _require_successor_frontier(uow.cursor, request=request, book=book,
            principal=SimpleNamespace(principal_id=root["actor_id"]), expected_root=root_operation_id)


def _require_successor_frontier(cursor, *, request, book, principal, expected_root=None):
    frozen = request["command_payload"].get(COMMAND) or {}
    binding = (frozen.get("preparation_report") or {}).get(BINDING) or {}
    _validate_binding(binding)
    cursor.execute("""SELECT to_jsonb(b),to_jsonb(r),to_jsonb(pr),to_jsonb(p),
        EXISTS(SELECT 1 FROM authority_story_creation_cancellation c WHERE c.project_id=b.project_id
            AND b.stable_idempotency_key=c.formation_run_id || ':production'),
        EXISTS(SELECT 1 FROM authority_book_chapter_acceptance a WHERE a.chapter_request_id IN (r.chapter_request_id,pr.chapter_request_id))
        FROM authority_book_production b JOIN authority_book_chapter_request r ON r.book_run_id=b.book_run_id
        JOIN authority_book_chapter_request pr ON pr.chapter_request_id=r.predecessor_request_id
        JOIN authority_operation p ON p.operation_id=pr.chapter_root_operation_id
        LEFT JOIN authority_operation n ON n.operation_id=r.chapter_root_operation_id
        WHERE b.book_run_id=%s AND r.chapter_request_id=%s
          AND (r.chapter_root_operation_id IS NULL OR (n.project_id=b.project_id AND n.workspace_id=b.workspace_id
            AND n.actor_id=p.actor_id AND n.definition_name='chapter.slice.run' AND n.definition_version='3.10.0'
            AND n.status NOT IN ('CANCELLED','CANCELLATION_REQUESTED','UNKNOWN','RECONCILIATION_REQUIRED')
            AND n.command_payload #> '{preparation_report,chapter_execution_recovery_v2}'=r.command_payload #> '{preparation_report,chapter_execution_recovery_v2}'))
        FOR UPDATE OF b,r,pr""", [book["book_run_id"], request["chapter_request_id"]])
    row = cursor.fetchone()
    if not row:
        raise KernelError("CHAPTER_TIMEOUT_RECOVERY_CONFLICT", "Retain the native predecessor and current successor")
    current, successor, predecessor, root, cancelled, accepted = row
    exact = {"contract_version": CONTRACT, "book_run_id": current["book_run_id"],
        "chapter_request_id": successor["chapter_request_id"], "predecessor_request_id": predecessor["chapter_request_id"],
        "predecessor_root_operation_id": root["operation_id"], "generation": successor["generation"],
        "source_digest": binding["source_digest"], "target_definition_version": "3.10.0"}
    if (cancelled or accepted or current["state"] in {"ABORTED", "COMPLETED", "CANCELLED"}
        or successor["status_reference"] == "CANCELLED" or current["active_chapter_request_id"] != successor["chapter_request_id"]
        or successor["chapter_number"] != current["accepted_through_chapter"] + 1
        or successor["book_run_id"] != current["book_run_id"] or predecessor["book_run_id"] != current["book_run_id"]
        or successor["project_id"] != current["project_id"] or predecessor["project_id"] != current["project_id"]
        or root["project_id"] != current["project_id"] or root["workspace_id"] != current["workspace_id"]
        or root["actor_id"] != principal.principal_id or root["status"] != "CANCELLED"
        or root["definition_version"] != "3.8.0" or root["definition_name"] != "chapter.slice.run"
        or root["operation_id"] != predecessor["chapter_root_operation_id"]
        or successor["generation"] != predecessor["generation"] + 1 or predecessor["chapter_number"] != successor["chapter_number"]
        or current["book_run_id"] != book["book_run_id"] or current["project_id"] != book["project_id"]
        or successor["command_payload"] != request["command_payload"] or binding != exact
        or successor["command_payload"].get("preparation_report", {}).get(BINDING) != exact
        or frozen.get("project_id") != current["project_id"] or frozen.get("workspace_id") != current["workspace_id"]
        or frozen.get("book_id") != current["book_id"] or frozen.get("chapter") != successor["chapter_number"]
        or frozen.get("actor_id") != principal.principal_id or successor["chapter_root_operation_id"] not in {None, expected_root}
        or root["command_payload"].get("book_id") != current["book_id"]
        or root["command_payload"].get("chapter") != successor["chapter_number"]):
        raise KernelError("CHAPTER_TIMEOUT_RECOVERY_CONFLICT", "Successor requires the exact live unaccepted frontier without cancellation")
    _require_recovery_cancellation(cursor, root=root, request_id=predecessor["chapter_request_id"], actor_id=principal.principal_id)
    admission, template = _current_template(cursor, book=current)
    receipts = _timeout_effects(cursor, root=root, target_template=template) if template else None
    if not receipts or _proof_digest(_source_proof(root, predecessor, admission, receipts)) != binding["source_digest"]:
        raise KernelError("CHAPTER_TIMEOUT_RECOVERY_CONFLICT", "Retain the exact settled prefix and authorized policy")
    return current, successor


def resume_successor(authority, *, chapter_request_id, principal):
    request = authority.require_chapter_request(chapter_request_id)
    principal.require("book.authority.execute", request["project_id"])
    principal.require("chapter.authority.execute", request["project_id"])
    frozen = request["command_payload"][COMMAND]
    book = authority.require(request["book_run_id"])
    with AuthorityUnitOfWork(authority.database_url) as uow:
        _require_successor_frontier(uow.cursor, request=request, book=book, principal=principal,
                                   expected_root=request['chapter_root_operation_id'])
    if request["chapter_root_operation_id"]:
        return request
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
        _require_successor_frontier(uow.cursor, request=request, book=current, principal=principal,
                                   expected_root=admission.root_operation_id)
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
