from __future__ import annotations

import re

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.world_preparation_repositories import WorldPreparationRepository
from .domain import canonical_hash

CONTRACT = "world-method-scope-projection.v1"


def require_projection_source(uow, *, source_operation_id, frozen, attempt):
    if (frozen.get("execution_contract_version") != "1.21.0"
            or frozen.get("generator_operation_name") != "chapter_plan.generate"
            or not frozen.get("world_preparation_request") or not frozen.get("runtime_continuation_id")):
        raise KernelError("WORLD_CONTEXT_RECOVERY_SOURCE_INVALID", "Only exact unsent Chapter World preparation is eligible")
    uow.cursor.execute("""SELECT output.output_key,output.asset_version_id,output.content_hash,asset.asset_type
        FROM authority_operation_output_asset output JOIN authority_asset_version version USING(asset_version_id)
        JOIN authority_asset asset ON asset.asset_id=version.asset_id
        WHERE output.operation_id=%s AND asset.project_id=%s""", [source_operation_id, frozen["project_id"]])
    outputs = uow.cursor.fetchall()
    contexts = [row for row in outputs if row[0] == "planning.context_bundle" and row[3] == "context_bundle"]
    worlds = [row for row in outputs if row[3] == "world_preparation_source"
              and row[0].startswith("production_execution.contract.world_preparation_source.")]
    if len(outputs) != 2 or len(contexts) != 1 or len(worlds) != 1:
        raise KernelError("WORLD_CONTEXT_RECOVERY_SOURCE_INVALID", "Retain exactly the base Context and unsent World source")
    context = uow.repositories.asset_documents.require(project_id=frozen["project_id"], asset_version_id=contexts[0][1])
    world = uow.repositories.asset_documents.require(project_id=frozen["project_id"], asset_version_id=worlds[0][1])
    source = world.content["contract"]
    failure = dict(attempt[2] or {})
    signature = re.fullmatch(r"PROTECTED_CONTEXT_BUDGET_EXCEEDED: (.+) exceeds TOTAL_CONTEXT_LIMIT; requires=(\d+), available=(\d+), used=(\d+), total=(\d+)", failure.get("error_message", ""))
    exact_accounting = context.content.get("world_method_scope_projection_version") == CONTRACT
    if (not signature or signature[1] != world.asset_version_id or int(signature[2]) <= int(signature[3])
            or context.content_hash != contexts[0][2] or world.content_hash != worlds[0][2]
            or context.content.get("world_protected_context_accounting_version")
            or (context.content.get("world_method_scope_projection_version") not in (None, CONTRACT))
            or context.content.get("project_id") != frozen["project_id"]
            or context.content.get("workspace_id") != frozen["workspace_id"]
            or context.content.get("book_id") != frozen["book_id"]
            or context.content.get("planning_scope") != "CHAPTER"
            or source.get("request") != frozen["world_preparation_request"]
            or source.get("fact_mutation_allowed") is not False
            or source.get("reality", {}).get("project_id") != frozen["project_id"]
            or source.get("reality", {}).get("book_id") != frozen["book_id"]
            or failure.get("error_code") != "PROGRAMMING_BUG" or failure.get("failure_class") != "programming_bug"):
        raise KernelError("WORLD_CONTEXT_RECOVERY_SOURCE_DRIFT", "Protected budget failure must identify its exact immutable World source")
    uow.cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s)
        OR EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=%s)
        OR (SELECT count(*) FROM authority_operation_output_asset WHERE operation_id=%s)<>2
        OR EXISTS(SELECT 1 FROM authority_attempt WHERE operation_id=%s AND status IN ('CLAIMED','EXECUTING','WAITING_EXTERNAL_RESULT','LEASED','RUNNING','CHECKPOINTED','RESULT_SUBMITTED'))
        OR EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt attempt USING(attempt_id) WHERE attempt.operation_id=%s AND lease.status='HELD')
        OR EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=%s AND acknowledged_at IS NULL)""", [source_operation_id]*6)
    if uow.cursor.fetchone()[0]:
        raise KernelError("WORLD_CONTEXT_RECOVERY_DISPATCH_UNSAFE", "World Context recovery cannot have dispatch, extra output, live lease or cancellation")
    WorldPreparationRepository(uow.cursor).assert_source_current(project_id=frozen["project_id"], book_id=frozen["book_id"], frozen=source)
    from novel_forge.modules.mkaos_authority.craft_context_projection import project_world_method_scope
    project_world_method_scope(context.content.get("narrative_intelligence", {}))
    uow.cursor.execute("""SELECT target_runtime FROM authority_story_planning_runtime_continuation
        WHERE continuation_id=%s AND successor_operation_id=%s AND project_id=%s AND workspace_id=%s AND book_id=%s""",
        [frozen["runtime_continuation_id"], source_operation_id, frozen["project_id"], frozen["workspace_id"], frozen["book_id"]])
    prior = uow.cursor.fetchone()
    if not prior:
        raise KernelError("WORLD_CONTEXT_RECOVERY_RUNTIME_DRIFT", "World source must retain its exact registered runtime")
    return {"contract_version": "world-protected-context-accounting.v1" if exact_accounting else CONTRACT, "source_operation_status": "FAILED_FINAL",
        "source_operation_id": source_operation_id, "source_failure": failure,
        "context_asset_version_id": context.asset_version_id, "context_content_hash": context.content_hash,
        "world_source_asset_version_id": world.asset_version_id, "world_source_content_hash": world.content_hash,
        "world_source_output_key": worlds[0][0],
        "prior_runtime_continuation_id": frozen["runtime_continuation_id"], "prior_runtime_hash": canonical_hash(prior[0]),
        "reason": "Retain complete current methods and typed plans; reference repeated unverified retrieval terms and prior plan application audits in exact immutable sources"}


def require_runtime_identity(uow, *, source, target):
    proof = source["context_revalidation"]
    uow.cursor.execute("""SELECT target_runtime FROM authority_story_planning_runtime_continuation
        WHERE continuation_id=%s AND successor_operation_id=%s""",
        [proof["prior_runtime_continuation_id"], source["source_operation_id"]])
    row = uow.cursor.fetchone()
    if not row or canonical_hash(row[0]) != proof["prior_runtime_hash"]:
        raise KernelError("WORLD_CONTEXT_RECOVERY_RUNTIME_DRIFT", "World source registered runtime changed")
    prior = row[0]
    def stable_account(runtime):
        account = dict(runtime.get("account") or {})
        account["entitlement"] = {key: value for key, value in dict(account.get("entitlement") or {}).items() if key != "authorization_ref"}
        return account
    fields = ("model_provider", "model_id", "reasoning_effort", "runtime_class", "model_backend_id", "cost_accounting_basis")
    if any(prior.get(key) != target.get(key) for key in fields) or stable_account(prior) != stable_account(target):
        raise KernelError("WORLD_CONTEXT_RECOVERY_RUNTIME_DRIFT", "Retain the exact prior model, reasoning, backend and stable account")
    return {"prior_runtime_continuation_id": proof["prior_runtime_continuation_id"], "prior_runtime_hash": proof["prior_runtime_hash"],
        "authorization_reference_change": "NATIVE_BUDGET_SUCCESSOR_ALLOWED"}


def require_chapter_projection_source(uow, *, source_operation_id, frozen, attempt):
    failure = dict(attempt[2] or {})
    if (attempt[0] != 'FAILED_RETRYABLE' or failure.get('error_code') != 'CONTEXT_CAPACITY_EXCEEDED'
            or failure.get('error_message') != 'CONTEXT_CAPACITY_EXCEEDED: Complete input leaves no model context for generation'
            or failure.get('failure_class') != 'retryable' or not frozen.get('runtime_continuation_id')):
        raise KernelError('CHAPTER_CONTEXT_RECOVERY_SOURCE_INVALID', 'Require the exact unsent main input capacity failure')
    uow.cursor.execute("""SELECT asset_version_id,content_hash FROM authority_operation_output_asset
        WHERE operation_id=%s AND output_key='planning.context_bundle'""", [source_operation_id])
    rows = uow.cursor.fetchall()
    if len(rows) != 1:
        raise KernelError('CHAPTER_CONTEXT_RECOVERY_SOURCE_INVALID', 'Retain one exact base Planning Context')
    context = uow.repositories.asset_documents.require(project_id=frozen['project_id'], asset_version_id=rows[0][0])
    prior_audits = context.content.get('planning_chapter_method_scope_projection_version') == 'chapter-method-scope-projection.v1'
    if (context.content_hash != rows[0][1] or context.content.get('planning_scope') != 'CHAPTER'
            or context.content.get('project_id') != frozen['project_id']
            or context.content.get('workspace_id') != frozen['workspace_id']
            or context.content.get('book_id') != frozen['book_id']
            or context.content.get('planning_chapter_method_scope_projection_version') not in (None, 'chapter-method-scope-projection.v1')
            or context.content.get('planning_prior_method_audit_projection_version')):
        raise KernelError('CHAPTER_CONTEXT_RECOVERY_SOURCE_DRIFT', 'Chapter projection must preserve its complete unprojected selection')
    uow.cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=%s AND acknowledged_at IS NULL)
        OR EXISTS(SELECT 1 FROM authority_book_production WHERE project_id=%s AND book_id=%s AND state IN ('ABORTED','CANCELLED','COMPLETED'))
        OR EXISTS(SELECT 1 FROM authority_attempt WHERE operation_id=%s AND status IN ('CLAIMED','EXECUTING','WAITING_EXTERNAL_RESULT','LEASED','RUNNING','CHECKPOINTED','RESULT_SUBMITTED'))""",
        [source_operation_id, frozen['project_id'], frozen['book_id'], source_operation_id])
    if uow.cursor.fetchone()[0]:
        raise KernelError('CHAPTER_CONTEXT_RECOVERY_DISPATCH_UNSAFE', 'Cancelled or terminal Book cannot acquire a projection successor')
    from novel_forge.modules.mkaos_authority.craft_context_projection import project_chapter_method_scope
    project_chapter_method_scope(context.content.get('narrative_intelligence', {}))
    uow.cursor.execute("""SELECT target_runtime FROM authority_story_planning_runtime_continuation
        WHERE continuation_id=%s AND successor_operation_id=%s AND project_id=%s AND workspace_id=%s AND book_id=%s""",
        [frozen['runtime_continuation_id'], source_operation_id, frozen['project_id'], frozen['workspace_id'], frozen['book_id']])
    prior = uow.cursor.fetchone()
    if not prior:
        raise KernelError('CHAPTER_CONTEXT_RECOVERY_RUNTIME_DRIFT', 'Chapter source must retain its exact registered runtime')
    return {'contract_version': 'chapter-prior-method-audits.v1' if prior_audits else 'chapter-method-scope-projection.v1', 'source_operation_status': 'FAILED_RETRYABLE',
        'source_operation_id': source_operation_id, 'source_failure': failure,
        'context_asset_version_id': context.asset_version_id, 'context_content_hash': context.content_hash,
        'prior_runtime_continuation_id': frozen['runtime_continuation_id'], 'prior_runtime_hash': canonical_hash(prior[0]),
        'reason': 'Retain complete current methods, usage histories, typed plans and the verified completed World action; reference only duplicate semantic-unverified retrieval terms and recall diagnostics'}
