from __future__ import annotations

from uuid import uuid4
from time import sleep

from psycopg.types.json import Jsonb

from .errors import KernelError


CONTRACT = "pure-generation-isolation.v1"


def isolation(cursor, effect_id: str):
    cursor.execute(
        "SELECT proof FROM authority_generation_isolation WHERE external_effect_id=%s",
        [effect_id],
    )
    row = cursor.fetchone()
    return row[0] if row else None


def require_not_isolated(cursor, operation_id: str):
    cursor.execute(
        "SELECT external_effect_id FROM authority_generation_isolation WHERE operation_id=%s",
        [operation_id],
    )
    if cursor.fetchone():
        raise KernelError(
            "GENERATION_ATTEMPT_ISOLATED",
            "Old generation has permanently lost business commit and activation rights; follow its registered native continuation",
        )


def recover_book_generations(application, *, project_id, book_id, principal):
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    from .manual_effect_resolution import (
        ExternalEffectManualResolutionCommand,
        resolve_external_effect_manually,
    )
    from .budget_runtime import unresolved_cli_outcomes

    from novel_forge.modules.production_execution.saved_result_recovery import recover_saved_local_results

    recover_saved_local_results(application.execution_binder.resolver.execution_preparer.execution_transport,
        database_url=application.database_url, project_id=project_id, book_id=book_id, principal=principal)
    from .execution_window import continue_saved_result_finalization
    continue_saved_result_finalization(application.database_url, project_id=project_id,
        book_id=book_id, principal=principal)
    principal.require("external_effect.resolve", project_id)
    with AuthorityUnitOfWork(application.database_url) as uow:
        rows = unresolved_cli_outcomes(uow.cursor, project_id, book_id=book_id)
        uow.cursor.execute(
            """SELECT to_jsonb(e),to_jsonb(o) FROM authority_generation_isolation i
            JOIN authority_external_effect e USING(external_effect_id) JOIN authority_operation o ON o.operation_id=i.operation_id
            WHERE i.project_id=%s AND i.book_id=%s AND o.definition_name='story_planning.generate' AND NOT EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation r
            WHERE r.source_operation_id=i.operation_id)""",
            [project_id, book_id],
        )
        pending = uow.cursor.fetchall()
    for item in rows:
        with AuthorityUnitOfWork(application.database_url) as uow:
            effect = uow.repositories.external_effects.get_for_update(
                item["external_effect_id"]
            )
            uow.cursor.execute(
                "SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s",
                [effect["operation_id"]],
            )
            operation = uow.cursor.fetchone()[0]
        if operation["definition_name"] != "story_planning.generate":
            continue
        authorization = (
            effect["request_payload"]
            .get("_production_execution", {})
            .get("capability_runtime", {})
            .get("routing_decision", {})
            .get("selected", {})
            .get("candidate", {})
            .get("authorization_ref")
        )
        if not authorization:
            raise KernelError(
                "GENERATION_ISOLATION_AUTHORIZATION_REQUIRED",
                "The original authorized Provider identity is required",
            )
        resolve_external_effect_manually(
            application.database_url,
            ExternalEffectManualResolutionCommand(
                effect["external_effect_id"],
                operation["operation_id"],
                project_id,
                principal.principal_id,
                "ISOLATE_PURE_GENERATION",
                "Original stopped pure generation has no recoverable result; preserve remote facts and continue the same task",
                {"authorization_ref": authorization},
                "generation-isolation:" + effect["external_effect_id"],
                operation["version"],
                operation["trace_id"],
                operation["correlation_id"],
            ),
        )
        with AuthorityUnitOfWork(application.database_url) as uow:
            uow.cursor.execute(
                "SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s",
                [operation["operation_id"]],
            )
            operation = uow.cursor.fetchone()[0]
        pending.append((effect, operation))
    if pending:
        sleep(30)
    for effect, operation in pending:
        with AuthorityUnitOfWork(application.database_url) as uow:
            proof = isolation(uow.cursor, effect["external_effect_id"])
        application.register_runtime_continuation(
            operation["operation_id"],
            project_id=project_id,
            principal=principal,
            expected_source_version=operation["version"],
            decision_evidence={
                "authorization_ref": proof["authorization_ref"],
                "reason": proof["reason"],
            },
            trace_id=operation["trace_id"],
            correlation_id=operation["correlation_id"],
        )
    return bool(pending)


def append_isolation(uow, effect, command):
    cursor = uow.cursor
    prior = isolation(cursor, effect["external_effect_id"])
    if prior:
        return prior
    cursor.execute(
        "SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s FOR UPDATE",
        [effect["operation_id"]],
    )
    operation = cursor.fetchone()[0]
    chapter_generation = operation["definition_name"] in {
        "chapter.memo.generate",
        "chapter.draft.generate",
        "chapter.review.evaluate",
        "chapter.revision.apply",
        "chapter.canon.extract",
    }
    if (
        operation["status"]
        not in {
            "FAILED_FINAL",
            "DEAD_LETTER",
            "WAITING_EXTERNAL_RESULT",
            "RECONCILIATION_REQUIRED",
        }
        or operation["actor_id"] != command.actor_id
        or not (
            operation["definition_name"] == "story_planning.generate"
            or chapter_generation
        )
        or effect["effect_type"] != "model.invoke"
        or effect["status"] not in {"UNKNOWN", "RECONCILIATION_REQUIRED"}
    ):
        raise KernelError(
            "GENERATION_ISOLATION_SCOPE_UNSAFE",
            "Only an owned stopped native model generation can be isolated",
        )
    cursor.execute(
        """SELECT 1 WHERE EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id)
          WHERE a.operation_id=%s AND l.status='HELD') OR EXISTS(SELECT 1 FROM authority_effect_dispatch_lease l
          JOIN authority_external_effect_dispatch d USING(dispatch_id) WHERE d.external_effect_id=%s AND l.status='HELD')""",
        [effect["operation_id"], effect["external_effect_id"]],
    )
    if cursor.fetchone():
        raise KernelError(
            "GENERATION_ISOLATION_WRITER_ACTIVE",
            "Release or expire the original writer lease before isolation",
        )
    cursor.execute(
        "SELECT 1 FROM authority_operation_output_asset WHERE operation_id=%s AND role='primary'",
        [effect["operation_id"]],
    )
    if cursor.fetchone():
        raise KernelError(
            "GENERATION_ISOLATION_RESULT_RECOVERABLE",
            "Read and reuse the original primary output",
        )
    if chapter_generation:
        from .step_successor import require_live_chapter_frontier
        from .step_successor_v2 import has_domain_outputs

        require_live_chapter_frontier(
            cursor,
            root_id=operation["root_operation_id"],
            project_id=command.project_id,
        )
        if has_domain_outputs(cursor, operation["operation_id"]):
            raise KernelError(
                "GENERATION_ISOLATION_RESULT_RECOVERABLE",
                "Reuse the immutable domain output",
            )
        cursor.execute(
            """SELECT book.book_id,book.workspace_id FROM authority_book_chapter_request request
            JOIN authority_book_production book USING(book_run_id)
            JOIN authority_saga_step step ON step.operation_id=%s AND step.saga_id=%s
            JOIN authority_operation root ON root.operation_id=request.chapter_root_operation_id
            WHERE request.chapter_root_operation_id=%s AND book.project_id=%s
            AND root.definition_name='chapter.slice.run' AND root.actor_id=%s
            AND root.status='WAITING_CHILDREN'""",
            [
                operation["operation_id"],
                operation["saga_id"],
                operation["root_operation_id"],
                command.project_id,
                command.actor_id,
            ],
        )
    else:
        cursor.execute(
            "SELECT book_id, workspace_id FROM authority_story_planning_generation WHERE operation_id=%s",
            [operation["operation_id"]],
        )
    generation = cursor.fetchone()
    frozen = (
        operation["command_payload"]
        if chapter_generation
        else operation["command_payload"].get("payload", {})
    )
    runtime = effect["request_payload"].get("_production_execution") or {}
    if (
        not generation
        or (generation[0], generation[1])
        != (runtime.get("book_id"), operation["workspace_id"])
        or (
            not chapter_generation
            and (
                frozen.get("project_id"),
                frozen.get("workspace_id"),
                frozen.get("book_id"),
            )
            != (command.project_id, operation["workspace_id"], generation[0])
        )
        or (chapter_generation and frozen.get("book_id") != generation[0])
    ):
        raise KernelError(
            "GENERATION_ISOLATION_SCOPE_UNSAFE",
            "Original native generation and frozen request must bind the same Book and workspace",
        )
    capability = runtime.get("capability_runtime") or {}
    materialization_id = capability.get("materialization_asset_version_id")
    materialization = uow.repositories.asset_documents.require(
        project_id=command.project_id, asset_version_id=materialization_id
    )
    tools = materialization.content.get("contract", {}).get("tool_permissions") or {}
    if (
        materialization.content_hash != capability.get("materialization_content_hash")
        or tools.get("default") != "DENY"
        or set(tools.get("allowed") or []) != {"model.provider.invoke"}
    ):
        raise KernelError(
            "GENERATION_ISOLATION_TOOL_BOUNDARY_UNSAFE",
            "Frozen input must disable every external write Tool",
        )
    cursor.execute(
        "SELECT to_jsonb(d) FROM authority_external_effect_dispatch d WHERE external_effect_id=%s ORDER BY generation FOR UPDATE",
        [effect["external_effect_id"]],
    )
    dispatches = [r[0] for r in cursor.fetchall()]
    if not dispatches or any(
        d["payload_hash"] != effect["request_hash"] for d in dispatches
    ):
        raise KernelError(
            "GENERATION_ISOLATION_IDENTITY_CONFLICT",
            "Every original dispatch must bind the frozen request",
        )
    cursor.execute(
        "SELECT snapshot_payload FROM authority_attempt_capability_pack_snapshot WHERE operation_id=%s ORDER BY created_at DESC LIMIT 1",
        [effect["operation_id"]],
    )
    pack = cursor.fetchone()
    if not pack:
        raise KernelError(
            "GENERATION_ISOLATION_CONTRACT_MISSING",
            "Retain the original execution Pack",
        )
    last = dispatches[-1]
    execution = last["evidence"].get("production_execution") or {}
    result = execution.get("execution_result") or {}
    ref = result.get("process_receipt_ref")
    if not ref or not ref.startswith("authority-asset-version:"):
        raise KernelError(
            "GENERATION_ISOLATION_RECEIPT_MISSING",
            "The original local process receipt is required",
        )
    receipt = uow.repositories.asset_documents.require(
        project_id=command.project_id, asset_version_id=ref.split(":", 1)[1]
    )
    process = receipt.content.get("payload", receipt.content)
    if (
        process.get("operation_id") != effect["operation_id"]
        or process.get("status") not in {"FAILED", "TIMED_OUT", "ORPHANED", "CANCELLED"}
        or process.get("result_integrity") == "VALID"
    ):
        raise KernelError(
            "GENERATION_ISOLATION_RESULT_RECOVERABLE",
            "Require stopped original execution without a complete local result",
        )
    from pathlib import Path
    import json

    result_path = process.get("result_path")
    if result_path and Path(result_path).is_file() and Path(result_path).stat().st_size:
        raise KernelError(
            "GENERATION_ISOLATION_RESULT_RECOVERABLE",
            "Reconcile the local result before isolating generation",
        )
    stdout_path = process.get("stdout_path")
    if not stdout_path or not Path(stdout_path).is_file():
        raise KernelError(
            "GENERATION_ISOLATION_EXECUTION_EVIDENCE_MISSING",
            "Original CLI event stream must remain readable",
        )
    for line in Path(stdout_path).read_text().splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if (
            isinstance(event, dict)
            and isinstance(event.get("item"), dict)
            and event["item"].get("type")
            in {"command_execution", "mcp_tool_call", "file_change", "web_search"}
        ):
            raise KernelError(
                "GENERATION_ISOLATION_TOOL_BOUNDARY_UNSAFE",
                "Observed Tool work requires its owning external-effect reconciliation",
            )
    from novel_forge.modules.production_execution.provider_protocol_failure import (
        observed_provider_failure,
    )
    from types import SimpleNamespace

    observed = observed_provider_failure(
        Path(stdout_path).read_text(),
        status=process["status"],
        request=SimpleNamespace(
            **{**process, "project_id": command.project_id, "book_id": generation[0]}
        ),
    )
    proof = {
        "observed_failure": observed,
        "contract_version": CONTRACT,
        "external_effect_id": effect["external_effect_id"],
        "operation_id": effect["operation_id"],
        "project_id": command.project_id,
        "workspace_id": operation["workspace_id"],
        "book_id": runtime.get("book_id"),
        "request_hash": effect["request_hash"],
        "dispatch_ids": [d["dispatch_id"] for d in dispatches],
        "process_receipt_ref": ref,
        "materialization_asset_version_id": materialization_id,
        "materialization_hash": materialization.content_hash,
        "pack_snapshot": pack[0],
        "local_execution": {
            k: process.get(k)
            for k in (
                "execution_id",
                "attempt_id",
                "fencing_token",
                "input_sha256",
                "command_sha256",
            )
        },
        "remote_outcome": "UNKNOWN",
        "usage": "UNKNOWN",
        "original_history": "PRESERVED",
        "business_commit_right": "REVOKED",
        "activation_right": "REVOKED",
        "continuation_id": (
            "chapter-generation-successor:"
            if chapter_generation
            else "planning-runtime-continuation:"
        )
        + effect["operation_id"],
        "recovery_state": "ISOLATED_AWAITING_NATIVE_SUCCESSOR",
        "reason": command.reason,
        "authorization_ref": command.evidence.get("authorization_ref"),
        "actor_id": command.actor_id,
    }
    if not proof["authorization_ref"] or not proof["book_id"]:
        raise KernelError(
            "GENERATION_ISOLATION_AUTHORIZATION_REQUIRED",
            "Bind actual generation recovery authorization and original Book",
        )
    proof["evidence_asset_version_id"] = receipt.asset_version_id
    if operation["status"] not in {"FAILED_FINAL", "DEAD_LETTER"}:
        from .attempt_runtime import _cas_operation, _transition_attempt

        attempt = uow.repositories.attempt_runtime.get_for_update(
            process["attempt_id"], command.project_id
        )
        if (
            attempt["operation_id"] != operation["operation_id"]
            or attempt["status"] != "CHECKPOINTED"
        ):
            raise KernelError(
                "GENERATION_ISOLATION_WRITER_ACTIVE",
                "Only a released stopped reconciliation checkpoint may be retired",
            )
        _transition_attempt(
            uow,
            attempt,
            "CANCELLED",
            worker_id=command.actor_id,
            fencing_token=None,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            result={
                "error_code": "GENERATION_ATTEMPT_ISOLATED",
                "failure": observed,
                "local_execution_disposition": "RETIRED",
                "remote_cancellation": "NOT_ESTABLISHED",
            },
        )
        _cas_operation(
            uow,
            operation_id=operation["operation_id"],
            project_id=command.project_id,
            expected_status=operation["status"],
            expected_version=operation["version"],
            target_status="FAILED_FINAL",
            actor_id=command.actor_id,
            reason="Isolate stopped pure generation; remote outcome and usage remain UNKNOWN",
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            causation_id=effect["external_effect_id"],
        )
    cursor.execute(
        """INSERT INTO authority_generation_isolation(isolation_id,external_effect_id,operation_id,
        project_id,workspace_id,book_id,request_hash,materialization_asset_version_id,proof)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        [
            str(uuid4()),
            effect["external_effect_id"],
            operation["operation_id"],
            command.project_id,
            operation["workspace_id"],
            proof["book_id"],
            effect["request_hash"],
            materialization_id,
            Jsonb(proof),
        ],
    )
    return proof


def recover_chapter_generations(authority, *, book_run_id, principal):
    from .manual_effect_resolution import (
        ExternalEffectManualResolutionCommand,
        resolve_external_effect_manually,
    )
    from .service import AdmissionContext
    from .step_successor_v2 import replace_failed_step
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork

    book = authority.require(book_run_id)
    if not book.get("active_chapter_request_id"):
        return False
    for permission in (
        "external_effect.resolve",
        "book.authority.execute",
        "chapter.authority.execute",
    ):
        principal.require(permission, book["project_id"])
    request = authority.require_chapter_request(book["active_chapter_request_id"])
    root_id = request["chapter_root_operation_id"]
    with AuthorityUnitOfWork(authority.database_url) as uow:
        uow.cursor.execute(
            """SELECT to_jsonb(o) FROM authority_operation o
            JOIN authority_saga_step step USING(operation_id) WHERE o.root_operation_id=%s
            AND o.status IN ('WAITING_EXTERNAL_RESULT','RECONCILIATION_REQUIRED','FAILED_FINAL','DEAD_LETTER')
            AND EXISTS(SELECT 1 FROM authority_external_effect effect WHERE effect.operation_id=o.operation_id
              AND effect.effect_type='model.invoke' AND effect.status IN ('UNKNOWN','RECONCILIATION_REQUIRED'))
            ORDER BY o.created_at""",
            [root_id],
        )
        sources = [row[0] for row in uow.cursor.fetchall()]
    changed = False
    for source in sources:
        with AuthorityUnitOfWork(authority.database_url) as uow:
            uow.cursor.execute(
                "SELECT to_jsonb(e) FROM authority_external_effect e WHERE operation_id=%s ORDER BY external_effect_id",
                [source["operation_id"]],
            )
            effects = [row[0] for row in uow.cursor.fetchall()]
        if len(effects) != 1:
            raise KernelError(
                "GENERATION_ISOLATION_MIXED_EFFECTS_RECONCILIATION_REQUIRED",
                "A multi-effect node requires original per-effect result recovery before native succession",
            )
        for effect in effects:
            with AuthorityUnitOfWork(authority.database_url) as uow:
                retained = isolation(uow.cursor, effect["external_effect_id"])
            if retained:
                continue
            authorization = (
                effect["request_payload"]
                .get("_production_execution", {})
                .get("capability_runtime", {})
                .get("routing_decision", {})
                .get("selected", {})
                .get("candidate", {})
                .get("authorization_ref")
            )
            resolve_external_effect_manually(
                authority.database_url,
                ExternalEffectManualResolutionCommand(
                    effect["external_effect_id"],
                    source["operation_id"],
                    book["project_id"],
                    principal.principal_id,
                    "ISOLATE_PURE_GENERATION",
                    "Retire stopped pure generation and retain original unknown remote outcome and usage",
                    {"authorization_ref": authorization},
                    "generation-isolation:" + effect["external_effect_id"],
                    source["version"],
                    source["trace_id"],
                    source["correlation_id"],
                ),
            )
        with AuthorityUnitOfWork(authority.database_url) as uow:
            proofs = [
                isolation(uow.cursor, effect["external_effect_id"])
                for effect in effects
            ]
            uow.cursor.execute(
                """WITH RECURSIVE ancestors AS (
                SELECT %s::text operation_id UNION ALL
                SELECT journal.predecessor_operation_id FROM authority_saga_step_successor journal
                  JOIN ancestors ON journal.successor_operation_id=ancestors.operation_id)
                SELECT count(*) FROM authority_saga_step_successor journal JOIN ancestors
                  ON ancestors.operation_id=journal.successor_operation_id
                WHERE journal.policy_evidence->>'contract_version'='chapter-pure-generation-successor.v1'""",
                [source["operation_id"]],
            )
            recovery_count = int(uow.cursor.fetchone()[0])
            uow.cursor.execute(
                "SELECT result->>'error_code' FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number DESC LIMIT 1",
                [source["operation_id"]],
            )
            failure_code = uow.cursor.fetchone()[0]
        if recovery_count >= 2:
            raise KernelError(
                "GENERATION_RECOVERY_EXHAUSTED",
                "Two safe native successors exhausted this Chapter node; saved manuscript remains readable; inspect failed routes or configure an authorized backup",
                details={
                    "original_failures": proofs,
                    "recovery_attempts": recovery_count,
                    "scope": "CURRENT_CHAPTER_NODE",
                    "recovery_action": "REPAIR_ROUTE_THEN_NATIVE_SUCCESSOR",
                },
            )
        successor = replace_failed_step(
            authority.database_url,
            predecessor_id=source["operation_id"],
            target_version=source["definition_version"],
            context=AdmissionContext(
                principal.principal_id,
                principal.permissions,
                authority.chapter_port.application.registry.available_handler_keys,
                authority.application_build_id,
                authority.commit_sha,
            ),
            policy_evidence={
                "contract_version": "chapter-pure-generation-successor.v1",
                "generation_isolations": proofs,
                "book_run_id": book_run_id,
                "chapter_request_id": request["chapter_request_id"],
                "recovery_attempt_number": recovery_count + 1,
                "remote_outcome": "UNKNOWN",
                "usage": "UNKNOWN",
                "completion_checks": "UNCHANGED",
            },
            expected_failure_code=failure_code,
            known_isolated_effects=tuple(
                (effect["external_effect_id"], effect["request_hash"])
                for effect in effects
            ),
        )
        if not successor["replayed"]:
            sleep(30)
        changed = True
    return changed
