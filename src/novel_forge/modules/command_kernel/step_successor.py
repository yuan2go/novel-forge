from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.operation_graph import (
    GraphCommandContext,
    _record,
)
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    admit_command_in_uow,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

CONTRACT = "kernel-failed-step-successor.v1"


def has_candidate_domain_outputs(cursor, operation_id):
    cursor.execute("""SELECT a.asset_type,o.role FROM authority_operation_output_asset o
        JOIN authority_asset a USING(asset_id) WHERE o.operation_id=%s""", [operation_id])
    contract_types = {'capability_materialization_manifest','execution_commit_policy','execution_context_policy',
        'execution_source_policy','execution_validation_policy','fallback_policy','input_manifest','model_profile',
        'prompt_bundle','provider_request_admission_manifest','route_policy','route_snapshot','skill_bundle','tool_permission_snapshot'}
    allowed = {(t,'execution_contract') for t in contract_types}
    allowed |= {('execution_evidence',r) for r in ('cost-receipt','normalized-output','output-manifest','process-receipt',
        'raw-output','usage-receipt','validation-manifest')}
    allowed |= {('cost_ledger','cost_evidence'),('execution_recovery_session','execution_recovery_projection'),
        ('model_call_log','model_evidence'),('model_call_log','model_failure_evidence'),('routing_decision','routing_evidence')}
    return any(tuple(row) not in allowed for row in cursor.fetchall())



def require_live_chapter_frontier(cursor, *, root_id, project_id, book_run_id=None):
    cursor.execute(
        """SELECT b.book_run_id,b.state,r.status_reference,
        EXISTS(SELECT 1 FROM authority_story_creation_cancellation c
            WHERE c.project_id=b.project_id AND b.stable_idempotency_key=c.formation_run_id || ':production')
        FROM authority_book_production b JOIN authority_book_chapter_request r
          ON r.chapter_request_id=b.active_chapter_request_id
        WHERE b.project_id=%s AND r.chapter_root_operation_id=%s
          AND r.chapter_number=b.accepted_through_chapter+1 FOR UPDATE OF b,r""",
        [project_id, root_id],
    )
    frontier = cursor.fetchone()
    if (not frontier or (book_run_id is not None and frontier[0] != book_run_id)
        or frontier[1] in {'ABORTED', 'COMPLETED', 'CANCELLED'}
        or frontier[2] == 'CANCELLED' or frontier[3]):
        raise KernelError('CHAPTER_RECOVERY_FRONTIER_CANCELLED',
                          'Recovery requires the exact live unaccepted Book frontier without cancellation')


def replace_failed_step(
    database_url,
    *,
    predecessor_id,
    target_version,
    context: AdmissionContext,
    policy_evidence,
    expected_failure_code,
    settled_candidate_effects=(),
    transaction_guard=None,
):
    digest = hashlib.sha256(
        json.dumps(
            {
                "predecessor": predecessor_id,
                "target": target_version,
                "policy": policy_evidence,
                "failure_code": expected_failure_code,
                **({"settled_candidate_effects": settled_candidate_effects} if settled_candidate_effects else {}),
            },
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    with AuthorityUnitOfWork(database_url) as uow:
        cursor = uow.cursor
        cursor.execute(
            "SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s FOR UPDATE",
            [predecessor_id],
        )
        row = cursor.fetchone()
        if not row:
            raise KernelError(
                "STEP_SUCCESSOR_SOURCE_MISSING", "Missing native predecessor"
            )
        source = row[0]
        project = source["project_id"]
        if source["actor_id"] != context.actor_id:
            raise KernelError("STEP_SUCCESSOR_SOURCE_INVALID", "Recovery requires the original actor")
        if not set(source["definition_snapshot"]["permissions"]).issubset(context.permissions):
            raise KernelError("PERMISSION_DENIED", "Recovery requires the original command permissions")
        cursor.execute(
            "SELECT request_digest,successor_operation_id FROM authority_saga_step_successor WHERE predecessor_operation_id=%s",
            [predecessor_id],
        )
        existing = cursor.fetchone()
        if existing:
            if existing[0] != digest:
                raise KernelError(
                    "STEP_SUCCESSOR_IDEMPOTENCY_CONFLICT", "Recovery command changed"
                )
            return {"operation_id": existing[1], "replayed": True}
        if transaction_guard is not None:
            transaction_guard(uow)
        repo = uow.repositories.operation_graph
        saga = repo.saga_for_update(source["saga_id"], project)
        repo.operation(source["root_operation_id"], project, lock=True)
        cursor.execute(
            "SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s",
            [source["root_operation_id"]],
        )
        root = cursor.fetchone()[0]
        require_live_chapter_frontier(cursor, root_id=source['root_operation_id'],
                                     project_id=project, book_run_id=policy_evidence.get('book_run_id'))
        cursor.execute(
            "SELECT to_jsonb(s) FROM authority_saga_step s WHERE operation_id=%s AND saga_id=%s FOR UPDATE",
            [predecessor_id, saga["saga_id"]],
        )
        row = cursor.fetchone()
        final_review_repair = bool(settled_candidate_effects and policy_evidence.get("contract_version") == "chapter-review-output-repair.v1"
            and source["definition_name"] == "chapter.review.evaluate" and source["definition_version"] == "3.9.0"
            and expected_failure_code in {"REVIEW_KNOWLEDGE_CHECK_INVALID", "REVIEW_KNOWLEDGE_CHECK_REQUIRED"})
        canon_protocol_repair = policy_evidence.get("contract_version") == "chapter-provider-schema-contract-repair.v1"
        quality_contract_repair = policy_evidence.get("contract_version")=="chapter-quality-contract-repair.v1"
        canon_support_repair = policy_evidence.get("contract_version") == "chapter-support-contract-repair.v1"
        canon_capacity_repair = policy_evidence.get("contract_version") == "chapter-canon-capacity-repair.v1"
        if (
            not row
            or source["status"] != ("CANCELLATION_REQUESTED" if canon_capacity_repair or settled_candidate_effects and not final_review_repair and not quality_contract_repair else "DEAD_LETTER" if quality_contract_repair else "FAILED_FINAL")
            or root["status"] != "WAITING_CHILDREN"
            or saga["status"] not in ({"RUNNING", "FORWARD_RECOVERY"} if canon_capacity_repair or canon_protocol_repair or canon_support_repair or quality_contract_repair else {"RUNNING"})
            or source["actor_id"] != context.actor_id
            or root["actor_id"] != context.actor_id
            or source["definition_version"] == target_version
        ):
            raise KernelError(
                "STEP_SUCCESSOR_SOURCE_INVALID",
                f"Only an owned failed child of a live graph can be replaced (step={bool(row)}, source={source['status']}, root={root['status']}, saga={saga['status']}, source_version={source['definition_version']}, target={target_version})",
            )
        step = row[0]
        if step["compensation_status"] != "NOT_REQUIRED" or step.get(
            "compensation_operation_id"
        ):
            raise KernelError(
                "STEP_SUCCESSOR_COMPENSATION_PRESENT",
                "Compensation retains its original recovery owner",
            )
        cursor.execute(
            "SELECT business_deadline_at FROM authority_operation WHERE operation_id=%s",
            [root["operation_id"]],
        )
        deadline = cursor.fetchone()[0]
        if deadline and deadline <= datetime.now(timezone.utc):
            raise KernelError(
                "OPERATION_BUSINESS_TIMEOUT",
                "The frozen Root deadline remains authoritative",
            )
        cursor.execute(
            """SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s),
            EXISTS(SELECT 1 FROM authority_operation_output_asset WHERE operation_id=%s),
            EXISTS(SELECT 1 FROM authority_operation_dependency WHERE depends_on_operation_id=%s),
            EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id)
                WHERE a.operation_id=%s AND l.released_at IS NULL AND l.expires_at>NOW())""",
            [predecessor_id] * 4,
        )
        external, output, dependent, live_lease = cursor.fetchone()
        if settled_candidate_effects or canon_capacity_repair or canon_protocol_repair:
            output = has_candidate_domain_outputs(cursor, predecessor_id)
        if external and canon_protocol_repair:
            cursor.execute("""SELECT e.external_effect_id,e.request_hash,e.status,r.status,r.accounting_basis,r.evidence->>'cost_authorization_ref'
                FROM authority_external_effect e LEFT JOIN authority_budget_reservation r USING(external_effect_id)
                WHERE e.operation_id=%s ORDER BY e.external_effect_id""",[predecessor_id])
            effects=cursor.fetchall()
            if not effects or effects != [tuple(r) for r in policy_evidence.get('known_failed_effects',[])]:
                raise KernelError('STEP_SUCCESSOR_PROTOCOL_EVIDENCE_MISMATCH','Bind the exact recorded failed membership effects')
            if any(r[2] not in {'FAILED_FINAL','FAILED_RETRYABLE'} or r[3:5]!=('SETTLED','ACCOUNT_ENTITLEMENT') or not r[5] for r in effects):
                raise KernelError('STEP_SUCCESSOR_PROTOCOL_UNSETTLED','Unknown outcomes or priced accounts cannot use membership Schema succession')
            external=False
        if external and settled_candidate_effects:
            cursor.execute("SELECT e.external_effect_id,e.request_hash,e.status,r.status,e.effect_type FROM authority_external_effect e LEFT JOIN authority_budget_reservation r USING(external_effect_id) WHERE e.operation_id=%s ORDER BY e.external_effect_id", [predecessor_id])
            effects = cursor.fetchall()
            if effects != [(effect, digest, "SUCCEEDED", "SETTLED", "model.invoke") for effect, digest in sorted(settled_candidate_effects)]:
                raise KernelError("STEP_SUCCESSOR_CANDIDATE_UNSETTLED", "Only exact known succeeded settled candidates may be superseded")
            external = False
        if external or output or dependent or live_lease:
            raise KernelError(
                "STEP_SUCCESSOR_EXTERNAL_OR_DEPENDENT_WORK",
                "Effects, outputs, dependents or leases prevent step succession",
            )
        cursor.execute(
            "SELECT to_jsonb(a) FROM authority_attempt a WHERE operation_id=%s ORDER BY attempt_number",
            [predecessor_id],
        )
        attempts = [r[0] for r in cursor.fetchall()]
        if (
            not attempts
            or attempts[-1]["result"].get("error_code") != expected_failure_code
        ):
            raise KernelError(
                "STEP_SUCCESSOR_FAILURE_MISMATCH",
                "Recovery must bind the exact recorded local failure",
            )
        target = uow.repositories.definitions.get(
            source["definition_name"], target_version
        )
        old_definition = source["definition_snapshot"]
        declared_contract = policy_evidence.get('contract_version')
        supported_contracts = {
            'chapter-core-contract-recovery.v1', 'chapter-candidate-contract-repair.v1',
            'chapter-review-output-repair.v1', 'chapter-length-output-repair.v1',
            'chapter-support-contract-repair.v1', 'chapter-quality-contract-repair.v1',
            'chapter-provider-schema-contract-repair.v1', 'chapter-canon-capacity-repair.v1',
        }
        if declared_contract not in supported_contracts:
            raise KernelError('STEP_SUCCESSOR_CONTRACT_CHANGED', 'Only a declared versioned Chapter correction may succeed a step')
        corrections = {
            'chapter-core-contract-recovery.v1': ('chapter.draft.generate', '3.9.0', '3.9.2', 'REALIZATION_CAPABILITY_INVALID', 'scene_core_projection', 'scene-core-slots.v1'),
            'chapter-candidate-contract-repair.v1': ('chapter.draft.generate', '3.9.1', '3.9.2', 'REALIZATION_EPISTEMIC_SCOPE_VIOLATION', 'scene_information_flow', 'scene-information-flow.v1'),
            'chapter-review-output-repair.v1': ('chapter.review.evaluate', '3.9.0', '3.9.3', expected_failure_code, 'review_knowledge_scope', 'delivered-card-scope.v1'),
            'chapter-length-output-repair.v1': ('chapter.revision.apply', '3.9.0', '3.9.4', 'REVISION_OUTSIDE_DIAGNOSIS_SCOPE', 'chapter_length_scope', 'chapter-length-repair.v1'),
        }
        correction = corrections.get(declared_contract)
        if correction and (not target or (source['definition_name'], source['definition_version'], target_version, expected_failure_code) != correction[:4]
            or target['policy'].get(correction[4]) != correction[5]
            or target['retry_policy'] != old_definition['retry_policy']
            or declared_contract == 'chapter-review-output-repair.v1' and expected_failure_code not in {'REVIEW_KNOWLEDGE_CHECK_INVALID', 'REVIEW_KNOWLEDGE_CHECK_REQUIRED'}):
            raise KernelError('STEP_SUCCESSOR_CONTRACT_CHANGED', 'The exact failed command and declared correction must match')
        if (
            not target
            or target["handler_key"] != old_definition["handler_key"]
            or target["permissions"] != old_definition["permissions"]
            or target["completion_contract"] != old_definition["completion_contract"]
            or target["command_schema"] != old_definition["command_schema"]
            or target["result_schema"] != old_definition["result_schema"]
            or target["external_capabilities"]
            != old_definition["external_capabilities"]
        ):
            raise KernelError(
                "STEP_SUCCESSOR_CONTRACT_CHANGED",
                "Successor cannot relax completion, permissions or external execution requirements",
            )
        if canon_capacity_repair or canon_protocol_repair or canon_support_repair or quality_contract_repair:
            from novel_forge.modules.production_execution.execution_template import selected_book_template, selected_template
            cursor.execute("SELECT book_id,active_chapter_request_id,accepted_through_chapter FROM authority_book_production WHERE book_run_id=%s AND project_id=%s FOR UPDATE", [policy_evidence.get('book_run_id'),project])
            book = cursor.fetchone()
            admission = selected_book_template(cursor, project_id=project, book_id=book[0]) if book else None
            template = selected_template(admission['policy_snapshot']['policy'],book[0]) if admission else None
            if not template or template.get('chapter_contract_recovery') != 'KNOWN_SETTLED_CONTRACT_REPAIR' or admission != policy_evidence.get('policy_admission'):
                raise KernelError('STEP_SUCCESSOR_POLICY_REQUIRED', 'Canon succession requires the exact trusted creative policy')
            cursor.execute('SELECT chapter_root_operation_id,chapter_number FROM authority_book_chapter_request WHERE chapter_request_id=%s', [book[1]])
            if book[1] != policy_evidence.get('chapter_request_id') or cursor.fetchone() != (source['root_operation_id'],book[2]+1):
                raise KernelError('STEP_SUCCESSOR_FRONTIER_INVALID', 'Canon succession cannot change an accepted or superseded frontier')
        if quality_contract_repair:
            if (not source['definition_name'].startswith('chapter.quality.') or source['definition_version']!='3.9.0'
                or target_version!='3.9.9' or expected_failure_code!='QUALITY_APPLICABILITY_CONFLICT'
                or target['policy'].get('quality_applicability_contract')!='quality-host-applicability.v1'
                or target['retry_policy']!=old_definition['retry_policy']
                or any(a['status']!='FAILED_RETRYABLE' or a['result'].get('error_code')!=expected_failure_code for a in attempts)):
                raise KernelError('STEP_SUCCESSOR_CONTRACT_CHANGED','Only the exact Quality applicability contract can succeed this dead letter')
            from novel_forge.modules.chapter_quality_authority.applicability_contract import quality_applicability_repair_evidence
            if quality_applicability_repair_evidence(cursor,predecessor_id,attempts[-1]['attempt_id'])!=policy_evidence.get('quality_applicability_repair'):
                raise KernelError('STEP_SUCCESSOR_QUALITY_EVIDENCE_MISMATCH','Bind the exact recorded applicability diagnostic')
            cursor.execute("""SELECT r.status,r.accounting_basis,r.evidence->>'cost_authorization_ref' FROM authority_external_effect e
                LEFT JOIN authority_budget_reservation r USING(external_effect_id) WHERE e.operation_id=%s""",[predecessor_id])
            if any(r[:2]!=('SETTLED','ACCOUNT_ENTITLEMENT') or not r[2] for r in cursor.fetchall()):
                raise KernelError('STEP_SUCCESSOR_QUALITY_UNSETTLED','Retain authorized settled membership reviews')
        if canon_support_repair:
            if (source['definition_name']!='chapter.canon.propose_changes' or source['definition_version']!='3.9.0'
                or target_version!='3.9.8' or expected_failure_code!='CANON_GROUNDING_REEXTRACTION_REQUIRED'
                or target['policy'].get('support_kind_contract')!='canon-support-kinds.v2'
                or target['retry_policy']!=old_definition['retry_policy']):
                raise KernelError('STEP_SUCCESSOR_CONTRACT_CHANGED','Only the explicit independent support taxonomy contract may succeed this failure')
            from novel_forge.modules.canon_graph.support_recovery import support_kind_repair_evidence
            if support_kind_repair_evidence(cursor,predecessor_id,attempts[-1]['attempt_id'])!=policy_evidence.get('support_kind_repair'):
                raise KernelError('STEP_SUCCESSOR_SUPPORT_EVIDENCE_MISMATCH','Bind the exact independently recorded taxonomy diagnostic')
            cursor.execute("""SELECT r.status,r.accounting_basis,r.evidence->>'cost_authorization_ref'
                FROM authority_external_effect e LEFT JOIN authority_budget_reservation r USING(external_effect_id)
                WHERE e.operation_id=%s""",[predecessor_id])
            if any(r[:2]!=('SETTLED','ACCOUNT_ENTITLEMENT') or not r[2] for r in cursor.fetchall()):
                raise KernelError('STEP_SUCCESSOR_SUPPORT_UNSETTLED','Only authorized settled membership reviews may use this taxonomy succession')
        if canon_protocol_repair:
            if (source['definition_name']!='chapter.canon.extract' or source['definition_version'] not in {'3.9.5','3.9.6'} or target_version!='3.9.7'
                or expected_failure_code!='MODEL_EFFECT_FINAL_PROVIDER_SCHEMA_REJECTED'
                or target['policy'].get('canon_wire_projection')!='codex-canonical-json.v1'
                or target['retry_policy']!=old_definition['retry_policy']):
                raise KernelError('STEP_SUCCESSOR_CONTRACT_CHANGED','Only the explicit terminal Canon Schema contract can adopt compiler v4')
            cursor.execute("""SELECT v.asset_version_id,v.content_hash,v.content FROM authority_operation_output_asset oa JOIN authority_asset x USING(asset_id)
                JOIN authority_asset_version v USING(asset_version_id) WHERE oa.operation_id=%s AND x.asset_type='model_call_log'
                AND v.content->>'attempt_id'=%s AND v.content->>'failure_code'='PROVIDER_SCHEMA_REJECTED'
                AND v.content->'real_model_call'='false'::jsonb""",[predecessor_id,attempts[-1]['attempt_id']])
            rejection=cursor.fetchone()
            if not rejection or policy_evidence.get('protocol_rejection_asset') != {'asset_version_id':rejection[0],'content_hash':rejection[1]}:
                raise KernelError('STEP_SUCCESSOR_PROTOCOL_REJECTION_REQUIRED','The latest failure must retain its exact non-producing Schema rejection')
            from novel_forge.modules.production_execution.codex_configuration import CODEX_SCHEMA_PROJECTION_VERSION, codex_output_schema
            evidence=rejection[2]['provider_evidence']['production_execution']['process_evidence']
            contract=evidence.get('provider_schema_contract') or {}
            def digest_wire(value):
                return 'sha256:'+hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            if (evidence.get('output_schema_version')!='schema:chapter-provider-output:canon_extraction:v24'
                or contract.get('version') not in {'codex-structured-schema.v3','codex-structured-schema.v4'} or CODEX_SCHEMA_PROJECTION_VERSION!='codex-structured-schema.v5'
                or digest_wire(evidence['output_schema'])!=contract.get('canonical_hash')
                or digest_wire(codex_output_schema(evidence['output_schema'],schema_ref='schema:chapter-provider-output:canon_extraction:v25'))==contract.get('provider_hash')):
                raise KernelError('STEP_SUCCESSOR_PROTOCOL_CORRECTION_REQUIRED','An unchanged or unrelated wire contract cannot replenish a failed step')
        if canon_capacity_repair:
            if (source["definition_name"] != "chapter.canon.extract" or source["definition_version"] != "3.9.0"
                or target["retry_policy"] != old_definition["retry_policy"]
                or target_version not in {"3.9.5","3.9.6","3.9.7"} or expected_failure_code != "PROVIDER_ROUTING_BLOCKED"
                or target["policy"].get("canon_schema_projection") != "canon-provider-shared-types.v1"
                or any(a["status"] != "FAILED_RETRYABLE" or a["result"].get("error_code") != expected_failure_code for a in attempts)):
                raise KernelError("STEP_SUCCESSOR_CONTRACT_CHANGED", "Canon correction requires exact no-send legacy capacity failures")
            cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_operation_output_asset oa JOIN authority_asset a USING(asset_id)
                JOIN authority_asset_version v USING(asset_version_id) WHERE oa.operation_id=%s AND a.asset_type='routing_decision'
                AND v.content #>> '{candidates,0,rejected_reasons}' LIKE '%%CONTEXT_CAPACITY_EXCEEDED%%'),
                EXISTS(SELECT 1 FROM authority_operation_output_asset oa JOIN authority_asset a USING(asset_id)
                JOIN authority_asset_version v USING(asset_version_id) WHERE oa.operation_id=%s AND a.asset_type='capability_materialization_manifest'
                AND v.content #>> '{contract,output_schema,ref}' IN ('schema:chapter-provider-output:canon_extraction:v22','schema:chapter-provider-output:canon_extraction:v23'))""", [predecessor_id]*2)
            if not all(cursor.fetchone()):
                raise KernelError("STEP_SUCCESSOR_CAPACITY_PROOF_REQUIRED", "Retain exact legacy Schema and capacity refusal evidence")
        if final_review_repair and target["policy"].get("review_knowledge_scope") != "delivered-card-scope.v1":
            raise KernelError("STEP_SUCCESSOR_CONTRACT_CHANGED", "Review recovery requires its versioned delivered scope")
        if policy_evidence.get("contract_version") == "chapter-length-output-repair.v1" and (target["policy"].get("chapter_length_scope") != "chapter-length-repair.v1" or source["definition_name"] != "chapter.revision.apply" or expected_failure_code != "REVISION_OUTSIDE_DIAGNOSIS_SCOPE"):
            raise KernelError("STEP_SUCCESSOR_CONTRACT_CHANGED", "Length recovery requires its exact versioned correction scope")
        if canon_capacity_repair or settled_candidate_effects and not final_review_repair and not quality_contract_repair:
            from novel_forge.modules.command_kernel.runtime import OperationTransitionCommand, transition_operation_in_uow
            transition_operation_in_uow(uow, OperationTransitionCommand(operation_id=predecessor_id,
                project_id=project, expected_version=source['version'], expected_status='CANCELLATION_REQUESTED',
                target_status='CANCELLED', actor_id=context.actor_id,
                reason='Exact versioned contract successor; terminal attempts, snapshots and settlement retained',
                trace_id=source['trace_id'], correlation_id=source['correlation_id'], causation_id=predecessor_id))
        graph_context = GraphCommandContext(
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
            + ":successor:"
            + target_version,
            "trace_id": source["trace_id"],
            "span_id": str(uuid4()),
            "correlation_id": source["correlation_id"],
            "causation_id": predecessor_id,
            "input": source["command_payload"],
            "input_assets": source["input_asset_snapshot"],
            "root_operation_id": source["root_operation_id"],
            "parent_operation_id": source["parent_operation_id"],
            "causation_operation_id": predecessor_id,
        }
        admitted = admit_command_in_uow(uow, command, context=context)
        successor = admitted["operation_id"]
        cursor.execute(
            "SELECT depends_on_operation_id,dependency_condition FROM authority_operation_dependency WHERE operation_id=%s",
            [predecessor_id],
        )
        for dependency, condition in cursor.fetchall():
            repo.add_dependency(successor, dependency, condition)
        cursor.execute(
            """INSERT INTO authority_saga_step_successor(successor_id,project_id,saga_id,
            predecessor_operation_id,successor_operation_id,actor_id,contract_version,request_digest,
            source_step_snapshot,source_failure_snapshot,policy_evidence) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
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
                Jsonb({"operation": source, "attempts": attempts}),
                Jsonb(policy_evidence),
            ],
        )
        cursor.execute(
            "UPDATE authority_saga_step SET operation_id=%s WHERE saga_id=%s AND operation_id=%s",
            [successor, saga["saga_id"], predecessor_id],
        )
        if cursor.rowcount != 1:
            raise KernelError(
                "STEP_SUCCESSOR_BINDING_CONFLICT", "Current Saga reference changed"
            )
        cursor.execute(
            "UPDATE authority_operation SET saga_id=%s,step_key=%s WHERE operation_id=%s AND status='ADMITTED'",
            [saga["saga_id"], step["step_key"], successor],
        )
        if cursor.rowcount != 1:
            raise KernelError(
                "STEP_SUCCESSOR_BINDING_CONFLICT", "Current Saga reference changed"
            )
        cursor.execute("UPDATE authority_operation SET version=version+1,updated_at=NOW() WHERE operation_id=%s AND version=%s AND status='WAITING_CHILDREN'", [root["operation_id"], root["version"]])
        if cursor.rowcount != 1:
            raise KernelError("STEP_SUCCESSOR_ROOT_CHANGED", "The current graph fence changed")
        repo.update_saga(saga["saga_id"], saga["version"], saga["status"])
        _record(
            repo,
            graph_context,
            predecessor_id,
            "authority.saga.failed_step_superseded",
            {
                "contract_version": CONTRACT,
                "successor_operation_id": successor,
                "source_step": step,
                "policy_evidence": policy_evidence,
                "provider_invoked": False,
            },
            aggregate_type="authority_saga",
            aggregate_id=saga["saga_id"],
        )
        repo.release_coordinator(
            saga["saga_id"], context.actor_id, lease["fencing_token"]
        )
        uow.commit()
    return {"operation_id": successor, "replayed": False}
