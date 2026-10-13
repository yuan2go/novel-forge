from __future__ import annotations

from dataclasses import asdict, dataclass
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import PrincipalType
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import AdmissionContext, execute_transaction_command
from novel_forge.modules.story_planning_runtime.domain import canonical_hash
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

NAME = "story_design.scope.reconcile"
HANDLER = "novel_forge.story_design.scope_reconcile"
CONTRACT = "story-design-scope-reconciliation.v1"


@dataclass(frozen=True)
class ReconcileStoryDesignScopeCommand:
    project_id: str
    workspace_id: str
    book_id: str
    asset_version_id: str
    content_hash: str
    expected_state_version: int
    original_activate_operation_id: str
    superseding_activate_operation_id: str
    approval_decision_asset_version_id: str
    approval_decision_content_hash: str
    active_plan_binding_id: str
    opening_run_id: str
    opening_checkpoint_id: str
    opening_checkpoint_hash: str
    original_opening_binding_hash: str
    actor_id: str
    reason: str
    idempotency_key: str
    trace_id: str
    correlation_id: str

    def __post_init__(self):
        if (type(self.expected_state_version) is not int or self.expected_state_version < 0
                or any(not isinstance(value, str) or not value.strip() for key, value in asdict(self).items() if key != "expected_state_version")):
            raise ValueError("Scope reconciliation requires every exact identity and expected state version")


def _reject(message):
    raise KernelError("STORY_DESIGN_SCOPE_RECONCILIATION_INVALID", message)


def _proof(uow, command):
    cursor = uow.cursor
    cursor.execute("""SELECT state.book_id FROM authority_story_design_transition transition
        JOIN authority_story_design_version_state state USING(project_id,asset_version_id)
        WHERE transition.project_id=%s AND transition.transition_operation_id=%s AND transition.transition_type='ACTIVATE'""",
        [command.project_id, command.superseding_activate_operation_id])
    superseding_scope = cursor.fetchone()
    books = sorted({command.book_id, *([superseding_scope[0]] if superseding_scope and superseding_scope[0] else [])})
    cursor.execute("SELECT book_id FROM authority_book WHERE project_id=%s AND book_id=ANY(%s) ORDER BY book_id FOR UPDATE", [command.project_id, books])
    cursor.execute("SELECT workspace_id FROM authority_book WHERE project_id=%s AND book_id=%s",
        [command.project_id, command.book_id])
    if cursor.fetchone() != (command.workspace_id,):
        _reject("Reconcile only the exact owning Book and Workspace")
    cursor.execute("""SELECT state.book_id,state.design_scope,state.scope_key,state.scope_layer,state.logical_key,
        state.lifecycle,state.qualification,state.approval,state.freshness,state.version,state.updated_by_operation_id,
        version.content_hash,version.lifecycle,version.eligibility,version.governance,state.planning_scope
        FROM authority_story_design_version_state state JOIN authority_asset_version version USING(asset_version_id)
        WHERE state.project_id=%s AND state.asset_version_id=%s FOR UPDATE OF state,version""",
        [command.project_id, command.asset_version_id])
    state = cursor.fetchone()
    if (not state or state[0] != command.book_id or state[5] != "SUPERSEDED"
            or state[7:9] != ("APPROVED", "CURRENT") or state[9] != command.expected_state_version
            or state[10] != command.superseding_activate_operation_id or state[11] != command.content_hash
            or state[12:15] != ("ACTIVE", "ELIGIBLE", "CLEAR") or state[15] not in {"BOOK", "VOLUME"}
            or state[1] not in {"BOOK_PLAN", "VOLUME_PLAN"}):
        _reject("State, approval, exact version or active typed artifact changed")
    from .creative_validation import approved_validation_design
    approval = approved_validation_design(cursor, project_id=command.project_id, book_id=command.book_id,
        asset_version_id=command.asset_version_id)
    if (not approval or approval["decision_asset_version_id"] != command.approval_decision_asset_version_id
            or approval["decision_content_hash"] != command.approval_decision_content_hash):
        _reject("Preserve the exact original experimental approval; this command grants no approval")
    cursor.execute("""SELECT active.binding_id,binding.asset_version_id,binding.execution_scope,binding.freshness,binding.parent_version_id
        FROM active_story_plan_version active JOIN story_plan_binding binding USING(binding_id)
        WHERE active.project_id=%s AND active.book_id=%s AND active.logical_key=%s FOR UPDATE OF active,binding""",
        [command.project_id, command.book_id, state[4]])
    binding = cursor.fetchone()
    if (not binding or binding[:2] != (command.active_plan_binding_id, command.asset_version_id)
            or binding[3] != "CURRENT"):
        _reject("The owning Hierarchical Planning active binding must still select this exact version")
    cursor.execute("""WITH RECURSIVE parents AS (
        SELECT binding.asset_version_id,binding.parent_version_id,binding.execution_scope,binding.freshness
        FROM story_plan_binding binding WHERE binding.project_id=%s AND binding.book_id=%s AND binding.asset_version_id=%s
        UNION SELECT binding.asset_version_id,binding.parent_version_id,binding.execution_scope,binding.freshness
        FROM story_plan_binding binding JOIN parents ON binding.asset_version_id=parents.parent_version_id
        WHERE binding.project_id=%s AND binding.book_id=%s)
        SELECT EXISTS(SELECT 1 FROM parents WHERE freshness<>'CURRENT'
          OR (parent_version_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM parents ancestor WHERE ancestor.asset_version_id=parents.parent_version_id))
          OR NOT EXISTS(SELECT 1 FROM active_story_plan_version active WHERE active.project_id=%s AND active.book_id=%s
            AND active.asset_version_id=parents.asset_version_id)
          OR (parents.asset_version_id<>%s AND NOT EXISTS(SELECT 1 FROM authority_story_design_version_state state
            JOIN authority_story_design_active_version active USING(project_id,asset_version_id,scope_key,scope_layer)
            WHERE state.project_id=%s AND state.book_id=%s AND state.asset_version_id=parents.asset_version_id
              AND state.lifecycle='ACTIVE' AND state.freshness='CURRENT' AND state.approval='APPROVED')))""",
        [command.project_id, command.book_id, command.asset_version_id, command.project_id, command.book_id, command.project_id, command.book_id,
            command.asset_version_id, command.project_id, command.book_id])
    if cursor.fetchone()[0]:
        _reject("The current same-Book parent closure changed; use Plan Change")
    cursor.execute("""SELECT transition.asset_version_id,operation.status,operation.command_payload->'payload',
        version.content_hash,operation.input_asset_snapshot FROM authority_story_design_transition transition
        JOIN authority_operation operation ON operation.operation_id=transition.transition_operation_id
        JOIN authority_asset_version version ON version.asset_version_id=transition.asset_version_id
        WHERE transition.project_id=%s AND transition.transition_operation_id=%s AND transition.transition_type='ACTIVATE'""",
        [command.project_id, command.original_activate_operation_id])
    original = cursor.fetchone()
    if (not original or original[0:2] != (command.asset_version_id, "SUCCEEDED") or original[3] != command.content_hash
            or original[2].get("asset_version_id") != command.asset_version_id
            or not any(item.get("asset_version_id") == command.asset_version_id and item.get("content_hash") == command.content_hash for item in original[4])):
        _reject("The original successful activation must bind the unchanged artifact")
    cursor.execute("""SELECT state.asset_version_id,state.book_id,state.scope_key,state.scope_layer,operation.status,state.logical_key
        FROM authority_story_design_transition transition
        JOIN authority_operation operation ON operation.operation_id=transition.transition_operation_id
        JOIN authority_story_design_version_state state ON state.project_id=transition.project_id AND state.asset_version_id=transition.asset_version_id
        WHERE transition.project_id=%s AND transition.transition_operation_id=%s AND transition.transition_type='ACTIVATE' FOR SHARE OF state""",
        [command.project_id, command.superseding_activate_operation_id])
    superseder = cursor.fetchone()
    if (not superseder or superseder[4] != "SUCCEEDED" or superseder[1] is None
            or superseder[2:4] == state[2:4] or superseder[5] != state[4]):
        _reject("Only a proven different-Book or different-layer supersession can be reconciled")
    cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
        [f"story-design-active:{command.project_id}:{state[2]}:{state[3]}:{state[4]}"])
    cursor.execute("""SELECT asset_version_id FROM authority_story_design_active_version
        WHERE project_id=%s AND scope_key=%s AND scope_layer=%s AND logical_key=%s FOR UPDATE""",
        [command.project_id, state[2], state[3], state[4]])
    active = cursor.fetchone()
    if active and active[0] != command.asset_version_id:
        _reject("Another same-namespace version is current; use Plan Change")
    cursor.execute("""SELECT generation.operation_id,operation.command_payload->'payload'->'opening_execution_binding'
        FROM authority_story_planning_candidate candidate JOIN authority_story_planning_generation generation USING(generation_id,project_id,book_id)
        JOIN authority_operation operation ON operation.operation_id=generation.operation_id
        WHERE candidate.project_id=%s AND candidate.book_id=%s AND candidate.candidate_asset_version_id=%s""",
        [command.project_id, command.book_id, command.asset_version_id])
    generation = cursor.fetchone()
    if (not generation or not isinstance(generation[1], dict)
            or generation[1].get("opening_run_id") != command.opening_run_id
            or canonical_hash(generation[1]) != command.original_opening_binding_hash):
        _reject("Retain this candidate's original frozen Opening execution binding")
    cursor.execute("""SELECT lifecycle,current_checkpoint_id,current_checkpoint_hash,current_execution_id,frozen_request_digest
        FROM authority_book_opening_run WHERE project_id=%s AND book_id=%s AND workspace_id=%s AND opening_run_id=%s FOR UPDATE""",
        [command.project_id, command.book_id, command.workspace_id, command.opening_run_id])
    opening = cursor.fetchone()
    if not opening or opening[:3] != ("FAILED", command.opening_checkpoint_id, command.opening_checkpoint_hash):
        _reject("Reconcile the exact failed Opening checkpoint without replacing its failure or input")
    cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_external_effect effect WHERE effect.project_id=%s
        AND effect.request_payload#>>'{_production_execution,book_id}'=ANY(%s)
        AND effect.status NOT IN ('SUCCEEDED','FAILED_FINAL','CANCELLED','COMPENSATED')
        AND NOT authority_generation_isolated(effect.external_effect_id))
        OR EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt attempt USING(attempt_id)
          JOIN authority_story_planning_generation generation USING(operation_id)
          WHERE generation.project_id=%s AND generation.book_id=ANY(%s) AND lease.status='HELD' AND lease.expires_at>NOW())
        OR EXISTS(SELECT 1 FROM authority_runtime_job_lease lease JOIN authority_runtime_job job USING(runtime_job_id)
          WHERE job.project_id=%s AND lease.status='HELD' AND lease.lease_expires_at>NOW()
          AND job.subject_id IN (SELECT opening_run_id FROM authority_book_opening_run WHERE project_id=%s AND book_id=ANY(%s)
            UNION SELECT formation_run_id FROM authority_story_formation_run WHERE project_id=%s AND book_id=ANY(%s)
            UNION SELECT book_run_id FROM authority_book_production WHERE project_id=%s AND book_id=ANY(%s)))""",
        [command.project_id, books, command.project_id, books, command.project_id, command.project_id, books, command.project_id, books, command.project_id, books])
    if cursor.fetchone()[0]:
        _reject("A related live executor or unresolved external outcome requires its existing recovery owner")
    return {"contract_version": CONTRACT, "project_id": command.project_id, "book_id": command.book_id,
        "asset_version_id": command.asset_version_id, "content_hash": command.content_hash,
        "scope_key": state[2], "scope_layer": state[3], "logical_key": state[4],
        "original_activate_operation_id": command.original_activate_operation_id,
        "superseding_activate_operation_id": command.superseding_activate_operation_id,
        "superseding_asset_version_id": superseder[0], "superseding_book_id": superseder[1], "superseding_scope_layer": superseder[3],
        "original_approval": approval, "hierarchy_binding_id": binding[0], "hierarchy_parent_version_id": binding[4],
        "original_opening_binding": generation[1], "opening_run_id": command.opening_run_id,
        "opening_checkpoint_id": opening[1], "opening_checkpoint_hash": opening[2], "opening_execution_id": opening[3],
        "opening_frozen_request_digest": opening[4], "prior_state_version": state[9],
        "provider_invoked": False, "new_approval": False, "story_content_changed": False,
        "history_preserved": True, "reason": command.reason, "operator_id": command.actor_id,
        "evidence_ceiling": "CURRENT_PROJECTION_RECONCILIATION_NOT_CREATIVE_ACCEPTANCE"}


def scope_reconciliation_definition(*, application_build_id: str, commit_sha: str):
    from .application import _transition_definition
    definition = _transition_definition(application_build_id=application_build_id, commit_sha=commit_sha)
    definition.update(name=NAME, definition_version="1.0.0", command_schema_version=CONTRACT, result_schema_version=CONTRACT,
        command_schema={"type": "object"}, input_contract={"type": "object"}, handler_key=HANDLER,
        handler_contract_version=CONTRACT, execution_mode="transactional", external_capabilities=[],
        policy={"execution_classification": "transaction_command", "trusted_operator_required": True, "provider_dispatch_allowed": False},
        idempotency_scope="book:story-design-scope-reconcile", concurrency_key_template="book:{book_id}:story-design-scope-reconcile",
        completion_contract={"version": CONTRACT, "required_asset_selectors": [{"selector": "story_design_scope_reconciliation",
            "output_key": NAME, "role": "reconciliation_evidence", "lifecycle": "ACTIVE", "eligibility": "ELIGIBLE", "governance": "CLEAR"}],
            "required_evidence": ["trace", "audit"], "required_outbox_events": [NAME]})
    return definition


def reconcile(application, command, *, principal):
    principal.require("story_design.authority.execute", command.project_id)
    if principal.principal_type is not PrincipalType.LOCAL_OPERATOR or principal.principal_id != command.actor_id:
        raise PermissionError("Only the scoped trusted operator can reconcile an exact projection")
    definition = scope_reconciliation_definition(application_build_id=application.application_build_id, commit_sha=application.commit_sha)
    with AuthorityUnitOfWork(application.database_url) as uow:
        uow.repositories.definitions.register(definition)
        uow.commit()

    def commit(uow, operation_id, checkpoint):
        evidence = _proof(uow, command)
        uow.repositories.story_design._activate(project_id=command.project_id, logical_key=evidence["logical_key"],
            asset_version_id=command.asset_version_id, operation_id=operation_id, owns_asset_lifecycle=False)
        uow.cursor.execute("""UPDATE authority_story_design_version_state SET lifecycle='ACTIVE',version=version+1,
            updated_by_operation_id=%s,updated_at=NOW() WHERE project_id=%s AND asset_version_id=%s AND version=%s AND lifecycle='SUPERSEDED'""",
            [operation_id, command.project_id, command.asset_version_id, command.expected_state_version])
        if uow.cursor.rowcount != 1:
            _reject("State changed before scope reconciliation")
        evidence["new_state_version"] = command.expected_state_version + 1
        uow.cursor.execute("""INSERT INTO authority_story_design_transition(transition_operation_id,project_id,asset_version_id,
            transition_type,from_version,to_version,evidence) VALUES(%s,%s,%s,'RECONCILE_SCOPE',%s,%s,%s)""",
            [operation_id, command.project_id, command.asset_version_id, command.expected_state_version, command.expected_state_version + 1, Jsonb(evidence)])
        receipt = uow.repositories.asset_documents.materialize_output(AuthorityAssetWriteCommand(operation_id=operation_id,
            project_id=command.project_id, asset_id="story-design-scope-reconciliation:"+operation_id,
            asset_type="story_design_scope_reconciliation", schema_version=CONTRACT,
            logical_ref="story_design/scope_reconciliation/"+operation_id, category="runs", output_key=NAME,
            role="reconciliation_evidence", content=evidence, qualification_policy=CONTRACT,
            lifecycle="ACTIVE", eligibility="ELIGIBLE", trace_id=command.trace_id, correlation_id=command.correlation_id,
            causation_id=command.superseding_activate_operation_id))
        uow.repositories.operation_graph.record_event(dict(event_id=str(uuid4()), audit_id=str(uuid4()), outbox_id=str(uuid4()),
            aggregate_type="story_design_scope_reconciliation", aggregate_id=command.asset_version_id,
            operation_id=operation_id, project_id=command.project_id, event_type=NAME,
            correlation_id=command.correlation_id, causation_id=command.superseding_activate_operation_id,
            payload={"operation_id": operation_id, "trace_id": command.trace_id, "asset_version_id": command.asset_version_id, "provider_invoked": False}))
        checkpoint("after_scope_projection")
        return {"asset_version_id": command.asset_version_id, "receipt_asset_version_id": receipt.asset_version_id,
            "receipt_content_hash": receipt.content_hash, "new_state_version": evidence["new_state_version"], "provider_invoked": False}

    return execute_transaction_command(application.database_url, dict(definition_name=NAME, definition_version="1.0.0",
        project_id=command.project_id, workspace_id=command.workspace_id, book_id=command.book_id, actor_id=command.actor_id,
        idempotency_scope="book:story-design-scope-reconcile", idempotency_key=command.idempotency_key,
        trace_id=command.trace_id, span_id=str(uuid4()), correlation_id=command.correlation_id,
        causation_id=command.superseding_activate_operation_id, input=asdict(command),
        input_assets=[{"asset_version_id": command.asset_version_id, "content_hash": command.content_hash},
            {"asset_version_id": command.approval_decision_asset_version_id, "content_hash": command.approval_decision_content_hash}]),
        context=AdmissionContext(command.actor_id, principal.permissions, frozenset({HANDLER}),
            application.application_build_id, application.commit_sha), handler=commit)
