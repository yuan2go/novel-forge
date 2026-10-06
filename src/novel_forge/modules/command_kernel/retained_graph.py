from __future__ import annotations

import hashlib
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import admit_command_in_uow
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation_in_uow,
)
from novel_forge.modules.command_kernel.operation_graph import (
    GraphCommandContext,
    _record,
)
from novel_forge.modules.production_execution.cost_routing import snapshot_hash

CONTRACT = "kernel-retained-graph-continuation.v1"
BINDING = "retained_graph_continuation"


def source_graph(cursor, *, root_id, project_id, actor_id):
    from .derived_step_revalidation import _settled_graph
    from novel_forge.modules.chapter_authority.quality_revision_recovery import (
        retained_quality_revision,
    )

    cursor.execute(
        "SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s AND project_id=%s FOR UPDATE",
        [root_id, project_id],
    )
    row = cursor.fetchone()
    if not row:
        raise KernelError(
            "RETAINED_GRAPH_SOURCE_INVALID",
            "Source root is absent from the authorized project",
        )
    root = row[0]
    cursor.execute(
        "SELECT to_jsonb(s) FROM authority_saga s WHERE root_operation_id=%s FOR UPDATE",
        [root_id],
    )
    row = cursor.fetchone()
    if not row:
        raise KernelError(
            "RETAINED_GRAPH_SOURCE_INVALID", "Retain the original terminal Saga"
        )
    saga = row[0]
    if (
        root["definition_name"] != "chapter.slice.run"
        or saga["project_id"] != project_id
        or root["root_operation_id"] != root_id
        or root["actor_id"] != actor_id
        or root["status"] != "FAILED_FINAL"
        or root["definition_version"] != "3.9.0"
        or saga["status"] != "MANUAL_INTERVENTION"
    ):
        raise KernelError(
            "RETAINED_GRAPH_SOURCE_INVALID",
            "Retain the exact terminal root and extension history",
        )
    cursor.execute(
        "SELECT to_jsonb(o) FROM authority_operation o WHERE root_operation_id=%s AND status='FAILED_FINAL' AND definition_name='chapter.revision.apply' AND idempotency_key LIKE %s",
        [root_id, "%:quality-correction:1"],
    )
    sources = cursor.fetchall()
    if len(sources) != 1:
        raise KernelError(
            "RETAINED_GRAPH_FAILURE_AMBIGUOUS",
            "One exact reproduced Quality range failure is required",
        )
    cursor.execute(
        "SELECT operation_id FROM authority_operation WHERE root_operation_id=%s AND idempotency_key LIKE %s",
        [root_id, "%:quality-correction:%"],
    )
    if cursor.fetchall() != [(sources[0][0]["operation_id"],)]:
        raise KernelError(
            "RETAINED_GRAPH_EXTENSION_CONFLICT",
            "Other correction work retains its own recovery ownership",
        )
    if sources[0][0]["actor_id"] != actor_id:
        raise KernelError(
            "RETAINED_GRAPH_SOURCE_INVALID", "Retain the original extension actor"
        )
    proof, _ = retained_quality_revision(cursor, sources[0][0])
    effects = _settled_graph(cursor, root_id)
    cursor.execute(
        """SELECT to_jsonb(step),to_jsonb(o) FROM authority_saga_step step JOIN authority_operation o USING(operation_id)
        WHERE step.saga_id=%s ORDER BY step.ordinal FOR UPDATE OF step,o""",
        [saga["saga_id"]],
    )
    steps = []
    from novel_forge.modules.chapter_authority.contracts import ChapterNode

    definitions = {node.value: node.definition_name for node in ChapterNode}

    expected = {n.value for n in ChapterNode} - {
        ChapterNode.PUBLISH_GATE.value,
        ChapterNode.EXPORT.value,
        ChapterNode.FINAL_RELEASE_GATE.value,
    }
    for step, operation in cursor.fetchall():
        if step["step_key"] not in expected:
            if operation[
                "definition_name"
            ] != ChapterNode.PUBLISH_GATE.definition_name or operation[
                "status"
            ] not in {"ADMITTED", "READY", "FAILED_RETRYABLE"}:
                raise KernelError(
                    "RETAINED_GRAPH_DOWNSTREAM_STARTED",
                    "Preserve independently started downstream recovery ownership",
                )
            cursor.execute(
                """SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s)
                OR EXISTS(SELECT 1 FROM authority_operation_output_asset WHERE operation_id=%s)""",
                [operation["operation_id"]] * 2,
            )
            if cursor.fetchone()[0]:
                raise KernelError(
                    "RETAINED_GRAPH_DOWNSTREAM_STARTED",
                    "No previously started downstream effects may be copied",
                )
            continue
        if (
            operation["definition_name"] != definitions[step["step_key"]]
            or operation["project_id"] != project_id
            or operation["workspace_id"] != root["workspace_id"]
            or operation["actor_id"] != actor_id
            or operation["status"] != "SUCCEEDED"
            or step["compensation_status"] != "NOT_REQUIRED"
        ):
            raise KernelError(
                "RETAINED_GRAPH_STEP_INCOMPLETE",
                "Only completed uncompensated steps may be referenced",
            )
        cursor.execute(
            """SELECT to_jsonb(output),v.content_hash,v.lifecycle,v.eligibility,v.governance
            FROM authority_operation_output_asset output JOIN authority_asset_version v USING(asset_version_id)
            WHERE output.operation_id=%s ORDER BY output.output_key,output.asset_version_id""",
            [operation["operation_id"]],
        )
        outputs = cursor.fetchall()
        if not outputs or any(
            row[3:] != ("ELIGIBLE", "CLEAR")
            or row[2] not in {"ACTIVE", "SUPERSEDED"}
            or row[0]["role"] in {"primary", "required_action"}
            and row[2] != "ACTIVE"
            for row in outputs
        ):
            raise KernelError(
                "RETAINED_GRAPH_OUTPUT_INVALID",
                "Completed references require exact active governed outputs",
            )
        steps.append(
            {
                "step": step,
                "operation": operation,
                "outputs": [list(r) for r in outputs],
            }
        )
    if {item["step"]["step_key"] for item in steps} != expected:
        raise KernelError(
            "RETAINED_GRAPH_STEP_MISSING", "Retain the complete pre-publication graph"
        )
    return {
        "root": root,
        "saga": saga,
        "steps": steps,
        "effects": effects,
        "retained_result": proof,
    }


def continue_graph_in_uow(uow, *, source, request, context):
    from novel_forge.modules.chapter_authority.orchestrator import _command
    from novel_forge.modules.chapter_authority.definitions import (
        CHAPTER_SLICE_ROOT_DEFINITION_NAME,
    )

    c = uow.cursor
    original = source_graph(
        c,
        root_id=source["root"]["operation_id"],
        project_id=request.project_id,
        actor_id=context.actor_id,
    )
    if original != source or request.workspace_id != source["root"]["workspace_id"]:
        raise KernelError(
            "RETAINED_GRAPH_SOURCE_DRIFT", "Reload the frozen terminal graph"
        )
    binding = (request.preparation_report or {}).get(BINDING) or {}
    from novel_forge.modules.production_execution.execution_template import (
        selected_book_template,
        selected_template,
    )

    admission = selected_book_template(
        c, project_id=request.project_id, book_id=request.book_id
    )
    template = (
        selected_template(admission["policy_snapshot"]["policy"], request.book_id)
        if admission
        else None
    )
    c.execute(
        "SELECT active_chapter_request_id,accepted_through_chapter FROM authority_book_production WHERE book_run_id=%s AND project_id=%s FOR UPDATE",
        [binding.get("book_run_id", ""), request.project_id],
    )
    frontier = c.fetchone()
    if (
        not template
        or template.get("chapter_graph_recovery")
        != "RETAIN_SETTLED_QUALITY_RANGE_RESULT"
        or admission != binding.get("admission")
        or template["member_authorization_ref"]
        != source["retained_result"]["cost_authorization_ref"]
        or request.book_id != source["retained_result"]["book_id"]
        or binding.get("retained_result") != source["retained_result"]
        or not frontier
        or frontier != (binding.get("predecessor_request_id"), request.chapter - 1)
    ):
        raise KernelError(
            "RETAINED_GRAPH_POLICY_INVALID",
            "Only the trusted current Book frontier and original membership authorization may continue",
        )
    command = _command(
        request,
        definition_name=CHAPTER_SLICE_ROOT_DEFINITION_NAME,
        definition_version="3.9.0",
        idempotency_key=request.idempotency_key,
        input_assets=[
            {
                "asset_version_id": i["asset_version_id"],
                "content_hash": i["content_hash"],
            }
            for i in request.context_candidates
        ],
    )
    frozen = source["root"]["command_payload"]
    for key in (
        "chapter",
        "title",
        "premise",
        "book_id",
        "chapter_plan_asset_version_id",
        "chapter_plan_content_hash",
        "context_candidates",
        "context_version_refs",
        "context_token_budget",
    ):
        from json import loads, dumps

        if loads(dumps(command["input"].get(key))) != frozen.get(key):
            raise KernelError(
                "RETAINED_GRAPH_REQUEST_DRIFT",
                "Retained work requires the exact original creative request",
            )
    admitted = admit_command_in_uow(uow, command, context=context)
    root = admitted["operation_id"]
    repo = uow.repositories.operation_graph
    saga = repo.start_saga(
        str(uuid4()), root, request.project_id, request.trace_id, request.correlation_id
    )["saga_id"]
    continuation = (
        "graph-continuation:"
        + hashlib.sha256(source["root"]["operation_id"].encode()).hexdigest()
    )
    binding = request.preparation_report[BINDING]
    c.execute(
        """INSERT INTO authority_graph_continuation(continuation_id,project_id,source_root_operation_id,successor_root_operation_id,source_saga_id,successor_saga_id,actor_id,contract_version,request_digest,source_snapshot,policy_evidence)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        [
            continuation,
            request.project_id,
            source["root"]["operation_id"],
            root,
            source["saga"]["saga_id"],
            saga,
            context.actor_id,
            CONTRACT,
            snapshot_hash(command),
            Jsonb(source),
            Jsonb(binding),
        ],
    )
    for item in source["steps"]:
        step = item["step"]
        c.execute(
            """INSERT INTO authority_saga_retained_step(saga_id,operation_id,continuation_id,step_key,ordinal,source_step_snapshot,source_output_snapshot)
            VALUES(%s,%s,%s,%s,%s,%s,%s)""",
            [
                saga,
                step["operation_id"],
                continuation,
                step["step_key"],
                step["ordinal"],
                Jsonb(step),
                Jsonb(item["outputs"]),
            ],
        )
    for version, current, target in [
        (0, "ADMITTED", "READY"),
        (1, "READY", "EXECUTING"),
        (2, "EXECUTING", "WAITING_CHILDREN"),
    ]:
        transition_operation_in_uow(
            uow,
            OperationTransitionCommand(
                operation_id=root,
                project_id=request.project_id,
                expected_version=version,
                expected_status=current,
                target_status=target,
                actor_id=context.actor_id,
                reason="governed continuation references completed operations",
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
                causation_id=source["root"]["operation_id"],
            ),
        )
    _record(
        repo,
        GraphCommandContext(
            request.project_id,
            context.actor_id,
            request.trace_id,
            request.correlation_id,
        ),
        root,
        "authority.saga.retained_graph_continued",
        {
            "continuation_id": continuation,
            "source_root_operation_id": source["root"]["operation_id"],
            "retained_result": source["retained_result"],
        },
    )
    return {"root_operation_id": root, "saga_id": saga, "continuation_id": continuation}


def permits_retained_dependency(cursor, root_id, dependency_id):
    cursor.execute(
        """SELECT EXISTS(SELECT 1 FROM authority_saga_retained_step ref JOIN authority_graph_continuation j USING(continuation_id)
        JOIN authority_operation o ON o.operation_id=ref.operation_id
        WHERE j.successor_root_operation_id=%s AND ref.operation_id=%s AND o.status='SUCCEEDED'
        AND j.contract_version=%s)""",
        [root_id, dependency_id, CONTRACT],
    )
    return cursor.fetchone()[0]


def acknowledge_retained_result(cursor, effects, root_id):
    cursor.execute(
        "SELECT policy_evidence FROM authority_graph_continuation WHERE successor_root_operation_id=%s AND contract_version=%s",
        [root_id, CONTRACT],
    )
    row = cursor.fetchone()
    if not row:
        return
    proof = row[0]["retained_result"]
    cursor.execute(
        """SELECT o.operation_id,v.content FROM authority_operation o JOIN authority_operation_output_asset output USING(operation_id)
        JOIN authority_asset_version v USING(asset_version_id) WHERE o.root_operation_id=%s AND o.definition_version='3.9.17'
        AND o.status='SUCCEEDED' AND output.role='primary' AND v.lifecycle='ACTIVE' AND v.eligibility='ELIGIBLE' AND v.governance='CLEAR'""",
        [root_id],
    )
    successors = cursor.fetchall()
    if len(successors) != 1:
        return
    successor, content = successors[0]
    derived = content.get("retained_result_derivation") or {}
    if (
        any(
            derived.get(k) != proof.get(k)
            for k in (
                "contract_version",
                "source_operation_id",
                "source_effect_id",
                "source_dispatch_id",
                "source_request_hash",
                "source_output_hash",
            )
        )
        or derived.get("provider_invoked") is not False
    ):
        raise KernelError(
            "RETAINED_GRAPH_EVIDENCE_DRIFT",
            "Derived outputs must retain their exact successful original receipt",
        )
    for effect in effects:
        if (
            effect["external_effect_id"] == proof["source_effect_id"]
            and effect["operation_id"] == proof["source_operation_id"]
            and effect["status"] == "SUCCEEDED"
            and effect["attempt_id"] == proof["source_attempt"]["attempt_id"]
            and effect["attempt_status"] == "FAILED_FINAL"
        ):
            effect["settled_candidate_superseded"] = True
            effect["successor_operation_id"] = successor
            effect["retained_result_contract"] = proof["contract_version"]
