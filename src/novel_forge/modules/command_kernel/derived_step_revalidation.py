from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.operation_graph import (
    GraphCommandContext,
    _record,
)
from novel_forge.modules.command_kernel.service import admit_command_in_uow
from novel_forge.modules.command_kernel.step_successor import require_live_chapter_frontier
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

CONTRACT = "kernel-derived-step-successor.v1"


def _settled_graph(cursor, root_id, *, verified_nonproducing_effects=()):
    cursor.execute(
        """SELECT e.external_effect_id,e.request_hash,e.status,r.status,r.accounting_basis,
        r.evidence->>'cost_authorization_ref' FROM authority_external_effect e
        JOIN authority_operation o USING(operation_id) LEFT JOIN authority_budget_reservation r USING(external_effect_id)
        WHERE o.root_operation_id=%s ORDER BY e.external_effect_id""",
        [root_id],
    )
    effects = cursor.fetchall()
    for effect in effects:
        if effect[3:5] != ("SETTLED", "ACCOUNT_ENTITLEMENT") or not effect[5]:
            raise KernelError(
                "DERIVED_STEP_UNSETTLED",
                "Reconcile all membership effects before revalidation",
            )
        if effect[2] == "SUCCEEDED":
            continue
        if list(effect) in verified_nonproducing_effects and effect[2] == "FAILED_RETRYABLE":
            continue
        if effect[2] not in {"FAILED_FINAL", "FAILED_RETRYABLE"}:
            raise KernelError(
                "DERIVED_STEP_UNSETTLED",
                "Unknown or dispatched outcomes cannot authorize revalidation",
            )
        cursor.execute(
            """SELECT EXISTS(SELECT 1 FROM authority_saga_step_successor j
            JOIN authority_external_effect e ON e.operation_id=j.predecessor_operation_id
            JOIN authority_operation predecessor ON predecessor.operation_id=j.predecessor_operation_id
            JOIN authority_operation successor ON successor.operation_id=j.successor_operation_id
            WHERE j.project_id=predecessor.project_id AND j.saga_id=predecessor.saga_id
              AND successor.project_id=predecessor.project_id AND successor.workspace_id=predecessor.workspace_id
              AND successor.root_operation_id=predecessor.root_operation_id AND successor.saga_id=j.saga_id
              AND successor.step_key=predecessor.step_key AND successor.actor_id=predecessor.actor_id
              AND successor.definition_name=predecessor.definition_name AND j.actor_id=predecessor.actor_id AND e.external_effect_id=%s AND j.contract_version='kernel-failed-step-successor.v1'
            AND j.policy_evidence->>'contract_version'='chapter-provider-schema-contract-repair.v1'
            AND EXISTS(SELECT 1 FROM jsonb_array_elements(j.policy_evidence->'known_failed_effects') b
                WHERE b->>0=e.external_effect_id AND b->>1=e.request_hash AND b->>2=e.status
                  AND b->>3='SETTLED' AND b->>4='ACCOUNT_ENTITLEMENT' AND b->>5=%s))""",
            [effect[0], effect[5]],
        )
        authorized_schema_failure = cursor.fetchone()[0]
        cursor.execute('''SELECT EXISTS(SELECT 1 FROM authority_external_effect failed
            JOIN authority_attempt a ON a.operation_id=failed.operation_id AND a.attempt_id=failed.request_payload #>> '{_production_execution,attempt_id}'
            JOIN authority_operation o ON o.operation_id=failed.operation_id
            JOIN authority_attempt later ON later.operation_id=o.operation_id AND later.attempt_number>a.attempt_number
            JOIN authority_external_effect success ON success.operation_id=later.operation_id AND success.request_payload #>> '{_production_execution,attempt_id}'=later.attempt_id
            JOIN authority_budget_reservation r ON r.external_effect_id=success.external_effect_id
            WHERE failed.external_effect_id=%s AND o.status='SUCCEEDED' AND later.status='SUCCEEDED'
              AND failed.status='FAILED_RETRYABLE' AND a.status='FAILED_RETRYABLE'
              AND success.status='SUCCEEDED' AND r.status='SETTLED'
              AND r.accounting_basis='ACCOUNT_ENTITLEMENT' AND r.evidence->>'cost_authorization_ref'=%s)''', [effect[0],effect[5]])
        recovered_in_place = cursor.fetchone()[0]
        current_successor = False
        if not authorized_schema_failure and not recovered_in_place:
            from .settled_successor_evidence import verified_successor_effects
            cursor.execute("SELECT operation_id FROM authority_external_effect WHERE external_effect_id=%s", [effect[0]])
            owner = cursor.fetchone()
            proof = verified_successor_effects(cursor, [owner[0]]) if owner and isinstance(owner[0], str) else {}
            current_successor = proof.get(effect[0], {}).get("effect") == list(effect)
        if not authorized_schema_failure and not recovered_in_place and not current_successor:
            raise KernelError(
                "DERIVED_STEP_UNRESOLVED_FAILURE",
                "Preserve unrelated failure recovery ownership",
            )
    cursor.execute(
        """SELECT EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id)
        JOIN authority_operation o USING(operation_id) WHERE o.root_operation_id=%s AND l.released_at IS NULL AND l.expires_at>NOW())""",
        [root_id],
    )
    if cursor.fetchone()[0]:
        raise KernelError(
            "DERIVED_STEP_LIVE_LEASE", "Wait for the original execution owner"
        )
    return [list(e) for e in effects]


def replace_derived_step(database_url, *, predecessor_id, context, policy_evidence):
    digest = hashlib.sha256(
        json.dumps(
            {"predecessor": predecessor_id, "policy": policy_evidence},
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    with AuthorityUnitOfWork(database_url) as uow:
        c = uow.cursor
        c.execute(
            "SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s FOR UPDATE",
            [predecessor_id],
        )
        row = c.fetchone()
        if not row:
            raise KernelError(
                "DERIVED_STEP_SOURCE_MISSING", "Retain the completed source operation"
            )
        source = row[0]
        project = source["project_id"]
        root_id = source["root_operation_id"]
        if source["actor_id"] != context.actor_id or not set(
            source["definition_snapshot"]["permissions"]
        ).issubset(context.permissions):
            raise KernelError(
                "PERMISSION_DENIED",
                "Revalidation requires the original actor and permissions",
            )
        c.execute(
            "SELECT request_digest,successor_operation_id FROM authority_saga_step_revalidation WHERE predecessor_operation_id=%s",
            [predecessor_id],
        )
        replay = c.fetchone()
        if replay:
            if replay[0] != digest:
                raise KernelError(
                    "DERIVED_STEP_IDEMPOTENCY_CONFLICT",
                    "The frozen revalidation request changed",
                )
            return {"operation_id": replay[1], "replayed": True}
        repo = uow.repositories.operation_graph
        saga = repo.saga_for_update(source["saga_id"], project)
        repo.operation(root_id, project, lock=True)
        c.execute(
            "SELECT to_jsonb(o),business_deadline_at FROM authority_operation o WHERE operation_id=%s",
            [root_id],
        )
        root, deadline = c.fetchone()
        require_live_chapter_frontier(c, root_id=root_id, project_id=project)
        c.execute(
            "SELECT to_jsonb(s) FROM authority_saga_step s WHERE saga_id=%s AND operation_id=%s FOR UPDATE",
            [saga["saga_id"], predecessor_id],
        )
        row = c.fetchone()
        from novel_forge.modules.canon_graph.validation_recovery import (
            selected_validation_policy,
            canon_revalidation_evidence,
        )

        admission = selected_validation_policy(
            c, project_id=project, root_operation_id=root_id, lock=True
        )
        if (
            not row
            or root["status"] != "WAITING_CHILDREN"
            or root["actor_id"] != context.actor_id
            or saga["status"] not in {"RUNNING", "FORWARD_RECOVERY"}
            or admission != policy_evidence.get("admission")
        ):
            raise KernelError(
                "DERIVED_STEP_FRONTIER_INVALID",
                "Only the unaccepted current frontier and exact trusted v6 policy may be revalidated",
            )
        step = row[0]
        if step["compensation_status"] != "NOT_REQUIRED" or step.get(
            "compensation_operation_id"
        ):
            raise KernelError(
                "DERIVED_STEP_COMPENSATION_PRESENT",
                "Retain compensation recovery ownership",
            )
        c.execute(
            """SELECT o.definition_name FROM authority_operation_dependency d JOIN authority_operation o USING(operation_id)
            WHERE d.depends_on_operation_id=%s""",
            [predecessor_id],
        )
        dependent_names = [r[0] for r in c.fetchall()]
        quality_correction = policy_evidence.get('quality_revalidation')
        if quality_correction:
            from novel_forge.modules.chapter_quality_authority.revalidation import quality_revalidation_evidence
            if quality_revalidation_evidence(c,source) != quality_correction:
                raise KernelError('DERIVED_STEP_QUALITY_PROOF_INVALID', 'Reproduce the exact frozen assessment correction')
        allowed_dependents = {'chapter.quality.evaluate','chapter.publishing.prepare_release','chapter.export.render'} if quality_correction else set()
        if any(
            r
            not in {
                "chapter.quality.structural.evaluate",
                "chapter.quality.commercial.evaluate",
                "chapter.quality.source_originality.evaluate",
                "chapter.quality.longform.evaluate",
                "chapter.quality.platform.evaluate",
            }
            for r in dependent_names
        ) and any(r not in allowed_dependents for r in dependent_names):
            raise KernelError(
                "DERIVED_STEP_DEPENDENT_COMMIT",
                "Committed downstream work cannot be rebound",
            )
        c.execute(
            "SELECT to_jsonb(a) FROM authority_attempt a WHERE operation_id=%s ORDER BY attempt_number",
            [predecessor_id],
        )
        attempts = [r[0] for r in c.fetchall()]
        c.execute(
            """SELECT v.asset_version_id,v.content_hash,a.asset_type,o.role FROM authority_operation_output_asset o
            JOIN authority_asset_version v USING(asset_version_id) JOIN authority_asset a ON a.asset_id=v.asset_id
            WHERE o.operation_id=%s ORDER BY v.asset_version_id,o.role""",
            [predecessor_id],
        )
        outputs = [list(r) for r in c.fetchall()]
        effects = _settled_graph(c, root_id)
        old = source["definition_snapshot"]
        inputs = source["input_asset_snapshot"]
        canonical_replacement = None
        replacements = []
        if quality_correction:
            inputs = quality_correction['input_snapshot']
            replacements = quality_correction['input_replacements']
            target_version = quality_correction['target_version']
        elif source["definition_name"] == "chapter.canon.update":
            if (
                source["status"] != "SUCCEEDED"
                or source["definition_version"] != "3.9.0"
            ):
                raise KernelError(
                    "DERIVED_STEP_CANON_SOURCE_INVALID",
                    "Only the completed legacy pure validator can be revalidated",
                )
            c.execute(
                "SELECT count(*) FROM authority_external_effect WHERE operation_id=%s",
                [predecessor_id],
            )
            if c.fetchone()[0] or canon_revalidation_evidence(
                c, source
            ) != policy_evidence.get("diagnostic"):
                raise KernelError(
                    "DERIVED_STEP_CANON_PROOF_INVALID",
                    "Reproduce the exact pure diagnostic without regenerating claims or prose",
                )
            target_version = "3.9.10"
        elif source["definition_name"] in {
            "chapter.quality.longform.evaluate",
            "chapter.quality.commercial.evaluate",
        }:
            if source["definition_version"] != "3.9.0":
                raise KernelError(
                    "DERIVED_STEP_QUALITY_SOURCE_INVALID",
                    "Only reviews against the superseded Canon may be revalidated",
                )
            c.execute(
                """SELECT j.predecessor_operation_id,j.successor_operation_id,j.policy_evidence,v.asset_version_id,v.content_hash,v.content
                FROM authority_saga_step_revalidation j JOIN authority_saga_step s ON s.operation_id=j.successor_operation_id
                JOIN authority_operation n ON n.operation_id=s.operation_id AND n.status='SUCCEEDED' AND n.definition_version='3.9.10'
                JOIN authority_operation_output_asset o ON o.operation_id=n.operation_id AND o.role='primary'
                JOIN authority_asset_version v USING(asset_version_id)
                WHERE j.saga_id=%s AND j.contract_version=%s AND j.policy_evidence #>> '{diagnostic,contract_version}'='chapter-canon-derived-revalidation.v1' """,
                [saga["saga_id"], CONTRACT],
            )
            canon = c.fetchone()
            from novel_forge.modules.production_execution.cost_routing import (
                snapshot_hash,
            )

            if (
                not canon
                or snapshot_hash(canon[5])
                != canon[2]["diagnostic"]["corrected_content_hash"]
            ):
                raise KernelError(
                    "DERIVED_STEP_CANON_NOT_COMPLETED",
                    "Run the exact new Canon validator before its affected reviews",
                )
            old_binding = canon[2]["diagnostic"]["source_output"]
            new_binding = {"asset_version_id": canon[3], "content_hash": canon[4]}

            def is_old_canon(binding):
                return (
                    binding.get("asset_version_id") == old_binding["asset_version_id"]
                    and binding.get("content_hash") == old_binding["content_hash"]
                    and binding.get("project_id") == project
                )

            if sum(is_old_canon(binding) for binding in inputs) != 1:
                raise KernelError(
                    "DERIVED_STEP_REVIEW_INPUT_DRIFT",
                    "Review must consume the exact superseded Canon output",
                )
            inputs = [{**i, **new_binding} if is_old_canon(i) else i for i in inputs]
            canonical_replacement = {
                "predecessor_operation_id": canon[0],
                "successor_operation_id": canon[1],
                "old_input": old_binding,
                "new_input": new_binding,
            }
            if canonical_replacement != policy_evidence.get(
                "canonical_input_replacement"
            ):
                raise KernelError(
                    "DERIVED_STEP_REVIEW_PROOF_INVALID",
                    "Bind the exact completed Canon successor",
                )
            if source["definition_name"] == "chapter.quality.longform.evaluate":
                if source["status"] != "SUCCEEDED" or not any(
                    r[3] == "primary" for r in outputs
                ):
                    raise KernelError(
                        "DERIVED_STEP_REVIEW_SOURCE_INVALID",
                        "Preserve the completed affected review",
                    )
            else:
                from novel_forge.modules.chapter_quality_authority.applicability_contract import (
                    quality_applicability_repair_evidence,
                )

                from novel_forge.modules.command_kernel.step_successor import (
                    has_candidate_domain_outputs,
                )

                if has_candidate_domain_outputs(c, predecessor_id):
                    raise KernelError(
                        "DERIVED_STEP_REVIEW_OUTPUT_PRESENT",
                        "Retain independently committed domain outputs",
                    )
                if (
                    source["status"] != "DEAD_LETTER"
                    or not attempts
                    or any(
                        a["status"] != "FAILED_RETRYABLE"
                        or a["result"].get("error_code")
                        != "QUALITY_APPLICABILITY_CONFLICT"
                        for a in attempts
                    )
                    or quality_applicability_repair_evidence(
                        c, predecessor_id, attempts[-1]["attempt_id"]
                    )
                    != policy_evidence.get("diagnostic")
                ):
                    raise KernelError(
                        "DERIVED_STEP_REVIEW_SOURCE_INVALID",
                        "Only the exact applicability dead letter may be reissued with the corrected Canon",
                    )
            target_version = "3.9.9"
        else:
            raise KernelError(
                "DERIVED_STEP_SOURCE_INVALID",
                "This contract cannot replace arbitrary completed work",
            )
        target = uow.repositories.definitions.get(
            source["definition_name"], target_version
        )
        immutable = (
            "handler_key",
            "permissions",
            "completion_contract",
            "command_schema",
            "result_schema",
            "external_capabilities",
            "retry_policy",
            "timeout_policy",
        )
        if not target or any(target[k] != old[k] for k in immutable):
            raise KernelError(
                "DERIVED_STEP_CONTRACT_CHANGED",
                "Retain completion, permissions, execution and retry bounds",
            )
        quality_policy = {'3.9.11':('internal_quality_disposition','creative-quality-disposition.v2'),
            '3.9.12':('quality_foundation_contract','quality-frozen-world-foundation.v1'),
            '3.9.13':('internal_quality_input_contract','creative-quality-admission.v2')}
        expected_policy = quality_policy.get(target_version) or (
            ("canon_validation_contract", "grounded-canon-validation.v2")
            if target_version == "3.9.10"
            else ("quality_applicability_contract", "quality-host-applicability.v1")
        )
        if target["policy"].get(expected_policy[0]) != expected_policy[1]:
            raise KernelError(
                "DERIVED_STEP_TARGET_INVALID",
                "Select the explicit versioned correction",
            )
        duration = int(
            root["definition_snapshot"]["timeout_policy"]["operation_timeout_seconds"]
        )
        if (
            not deadline
            or not 0 < duration <= 3600
            or any(
                k in root["command_payload"]
                for k in ("business_deadline_at", "author_deadline_at")
            )
        ):
            raise KernelError(
                "DERIVED_STEP_WINDOW_INVALID",
                "Explicit author deadlines cannot be extended",
            )
        renewed = max(
            deadline, datetime.now(timezone.utc) + timedelta(seconds=duration)
        )
        graph = GraphCommandContext(
            project,
            context.actor_id,
            source["trace_id"],
            source["correlation_id"],
            predecessor_id,
        )
        lease = repo.acquire_coordinator(
            saga, owner=context.actor_id, lease_id=str(uuid4()), lease_seconds=30
        )
        command = {
            "definition_name": source["definition_name"],
            "definition_version": target_version,
            "project_id": project,
            "workspace_id": source["workspace_id"],
            "actor_id": context.actor_id,
            "idempotency_scope": source["idempotency_scope"],
            "idempotency_key": source["idempotency_key"]
            + ":revalidation:"
            + target_version,
            "trace_id": source["trace_id"],
            "span_id": str(uuid4()),
            "correlation_id": source["correlation_id"],
            "causation_id": predecessor_id,
            "input": source["command_payload"],
            "input_assets": inputs,
            "root_operation_id": root_id,
            "parent_operation_id": source["parent_operation_id"],
            "causation_operation_id": predecessor_id,
        }
        admitted = admit_command_in_uow(uow, command, context=context)
        successor = admitted["operation_id"]
        c.execute(
            "SELECT depends_on_operation_id,dependency_condition FROM authority_operation_dependency WHERE operation_id=%s",
            [predecessor_id],
        )
        if canonical_replacement:
            replacements.append(canonical_replacement)
        for dependency, condition in c.fetchall():
            mapped_dependency = next((r['successor_operation_id'] for r in replacements if dependency == r['predecessor_operation_id']), dependency)
            repo.add_dependency(
                successor,
                mapped_dependency,
                condition,
            )
        c.execute(
            """INSERT INTO authority_saga_step_revalidation(revalidation_id,project_id,saga_id,predecessor_operation_id,
            successor_operation_id,actor_id,contract_version,request_digest,source_step_snapshot,source_execution_snapshot,policy_evidence)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            [
                str(uuid4()),
                project,
                saga["saga_id"],
                predecessor_id,
                successor,
                context.actor_id,
                CONTRACT,
                digest,
                Jsonb(step),
                Jsonb(
                    {
                        "operation": source,
                        "attempts": attempts,
                        "outputs": outputs,
                        "settled_graph_effects": effects,
                    }
                ),
                Jsonb(policy_evidence),
            ],
        )
        if target_version == '3.9.13' and source['status'] in {'ADMITTED','READY','FAILED_RETRYABLE'}:
            from novel_forge.modules.command_kernel.runtime import OperationTransitionCommand, transition_operation_in_uow
            for before,after in ((source['status'],'CANCELLATION_REQUESTED'),('CANCELLATION_REQUESTED','CANCELLED')):
                c.execute('SELECT version FROM authority_operation WHERE operation_id=%s',[predecessor_id])
                transition_operation_in_uow(uow,OperationTransitionCommand(operation_id=predecessor_id,project_id=project,
                    expected_version=c.fetchone()[0],expected_status=before,target_status=after,actor_id=context.actor_id,
                    reason='Exact unexecuted publication input successor; retain failed admission evidence',
                    trace_id=source['trace_id'],correlation_id=source['correlation_id'],causation_id=predecessor_id))
        c.execute(
            "UPDATE authority_saga_step SET operation_id=%s WHERE saga_id=%s AND operation_id=%s",
            [successor, saga["saga_id"], predecessor_id],
        )
        if c.rowcount != 1:
            raise KernelError(
                "DERIVED_STEP_FENCE_CHANGED", "Reload the current Saga reference"
            )
        c.execute(
            "UPDATE authority_operation SET saga_id=%s,step_key=%s WHERE operation_id=%s AND status='ADMITTED'",
            [saga["saga_id"], step["step_key"], successor],
        )
        c.execute(
            "UPDATE authority_operation SET business_deadline_at=%s,version=version+1,updated_at=NOW() WHERE operation_id=%s AND version=%s AND status='WAITING_CHILDREN'",
            [renewed, root_id, root["version"]],
        )
        if c.rowcount != 1:
            raise KernelError(
                "DERIVED_STEP_FENCE_CHANGED", "Reload the current Root fence"
            )
        if target_version in {"3.9.10", "3.9.11", "3.9.12"}:
            c.execute(
                "SELECT count(*) FROM authority_operation_dependency d JOIN authority_operation o ON o.operation_id=d.depends_on_operation_id WHERE d.operation_id=%s AND (d.dependency_condition<>'ON_SUCCESS' OR o.status<>'SUCCEEDED')",
                [successor],
            )
            if c.fetchone()[0]:
                raise KernelError(
                    "DERIVED_STEP_DEPENDENCY_NOT_COMPLETE",
                    "The pure validator retains all completed prerequisite outputs",
                )
            from novel_forge.modules.command_kernel.runtime import (
                OperationTransitionCommand,
                transition_operation_in_uow,
            )

            c.execute(
                "SELECT version FROM authority_operation WHERE operation_id=%s",
                [successor],
            )
            transition_operation_in_uow(
                uow,
                OperationTransitionCommand(
                    operation_id=successor,
                    project_id=project,
                    expected_version=c.fetchone()[0],
                    expected_status="ADMITTED",
                    target_status="READY",
                    actor_id=context.actor_id,
                    reason="Exact owned pure derived revalidation has completed prerequisites",
                    trace_id=source["trace_id"],
                    correlation_id=source["correlation_id"],
                    causation_id=predecessor_id,
                ),
            )
        repo.update_saga(saga["saga_id"], saga["version"], saga["status"])
        _record(
            repo,
            graph,
            predecessor_id,
            "authority.saga.derived_step_revalidated",
            {
                "contract_version": CONTRACT,
                "successor_operation_id": successor,
                "source_step": step,
                "policy_evidence": policy_evidence,
                "source_root": root,
                "original_deadline": deadline.isoformat(),
                "new_deadline": renewed.isoformat(),
                "provider_invoked": False,
                "history_rewritten": False,
            },
            aggregate_type="authority_saga",
            aggregate_id=saga["saga_id"],
        )
        repo.release_coordinator(
            saga["saga_id"], context.actor_id, lease["fencing_token"]
        )
        uow.commit()
    return {"operation_id": successor, "replayed": False}


def acknowledge_revalidated_effects(cursor, model_effects, operation_ids):
    cursor.execute(
        """SELECT j.predecessor_operation_id,j.successor_operation_id,j.source_execution_snapshot,j.policy_evidence
        FROM authority_saga_step_revalidation j JOIN authority_operation n ON n.operation_id=j.successor_operation_id
        JOIN authority_operation p ON p.operation_id=j.predecessor_operation_id
          AND p.project_id=j.project_id AND p.saga_id=j.saga_id
          AND n.project_id=p.project_id AND n.workspace_id=p.workspace_id
          AND n.root_operation_id=p.root_operation_id AND n.saga_id=p.saga_id
          AND n.step_key=p.step_key AND n.actor_id=p.actor_id AND j.actor_id=p.actor_id
          AND n.definition_name=p.definition_name
        JOIN authority_saga_step s ON s.operation_id=n.operation_id AND s.saga_id=j.saga_id
        WHERE j.predecessor_operation_id=ANY(%s) AND j.contract_version=%s
          AND n.status='SUCCEEDED' AND n.definition_version='3.9.9'
          AND n.definition_name IN ('chapter.quality.longform.evaluate','chapter.quality.commercial.evaluate')""",
        [operation_ids, CONTRACT],
    )
    for predecessor, successor, snapshot, policy in cursor.fetchall():
        source = snapshot["operation"]
        if (
            source["definition_version"] != "3.9.0"
            or source["status"] not in {"SUCCEEDED", "DEAD_LETTER"}
            or not policy.get("canonical_input_replacement")
        ):
            continue
        attempts = {a["attempt_id"]: a for a in snapshot["attempts"]}
        effects = {e[0]: e for e in snapshot["settled_graph_effects"]}
        for item in model_effects:
            attempt = attempts.get(item["attempt_id"])
            recorded = effects.get(item["external_effect_id"])
            if (
                item["operation_id"] != predecessor
                or item["status"] != "SUCCEEDED"
                or not attempt
                or attempt["status"] != "FAILED_RETRYABLE"
                or attempt["result"].get("error_code")
                != "QUALITY_APPLICABILITY_CONFLICT"
                or not recorded
            ):
                continue
            cursor.execute(
                """SELECT e.request_hash,e.status,r.status,r.accounting_basis,r.evidence->>'cost_authorization_ref'
                FROM authority_external_effect e JOIN authority_budget_reservation r USING(external_effect_id)
                WHERE e.external_effect_id=%s AND e.operation_id=%s""",
                [item["external_effect_id"], predecessor],
            )
            current = cursor.fetchone()
            if (
                current
                and list(current) == recorded[1:]
                and current[1:4] == ("SUCCEEDED", "SETTLED", "ACCOUNT_ENTITLEMENT")
                and current[4]
            ):
                item["settled_candidate_superseded"] = True
                item["successor_operation_id"] = successor
