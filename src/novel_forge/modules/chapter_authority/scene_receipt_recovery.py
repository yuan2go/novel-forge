from __future__ import annotations

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import AdmissionContext
from novel_forge.modules.command_kernel.step_successor_v2 import replace_failed_step, has_domain_outputs
from novel_forge.modules.production_execution.cost_routing import snapshot_hash
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from .receipt_recovery import _receipt, _cancelled, _require_current_receipt_family
from .contracts import ChapterHandlerRequest, ChapterInputAsset
from .realization_composition import compile_realization_contract, resolve_accepted_realization_sources, normalize_scene_source_union
from .chapter_plan_views import build_draft_style_view
from .domain_handlers import normalize_draft_result
from .craft_execution import require_craft_delivery


def draft_receipt_inputs(source, *, asset_reader):
    _require_current_receipt_family(source)
    assets = []
    for binding in source["input_asset_snapshot"]:
        asset = asset_reader.require(project_id=source["project_id"], asset_version_id=binding["asset_version_id"])
        if (asset.project_id != source["project_id"] or asset.content_hash != binding["content_hash"]
                or asset.content_hash != snapshot_hash(asset.content)
                or asset.lifecycle not in {"ACTIVE", "SUPERSEDED"}
                or asset.eligibility != "ELIGIBLE" or asset.governance != "CLEAR"):
            raise KernelError("DRAFT_RECOVERY_INPUT_DRIFT", "Retain exact governed inputs")
        assets.append(ChapterInputAsset(asset.asset_version_id, asset.asset_type, asset.content_hash, asset.content))
    return ChapterHandlerRequest(source["operation_id"], source["project_id"], source["workspace_id"], source["trace_id"], source["correlation_id"], source["command_payload"], tuple(assets), definition_version="3.10.0")


def revalidate_scene_receipt(source, result, *, asset_reader):
    request = draft_receipt_inputs(source, asset_reader=asset_reader)
    plan, context = request.require_input("chapter_plan"), request.require_input("context_bundle")
    require_craft_delivery(plan=plan.content, intent=request.require_input("chapter_execution_intent").content,
        memo=request.require_input("chapter_memo").content, context=context.content)
    contract = compile_realization_contract(plan.content, build_draft_style_view(context.content, work_requirements=True),
        core_policy="continuous-scene.v1", information_policy="actor-source-scope.v1",
        accepted_sources=resolve_accepted_realization_sources(request, asset_reader=asset_reader, verify_content_hash=True),
        world_preparation=context.content.get("chapter_execution_expectations", {}).get("world_preparation", {}))
    normalized, changes = normalize_scene_source_union(contract, result.output.get("scene_artifacts"))
    if not changes:
        raise KernelError("DRAFT_RECOVERY_NOT_APPLICABLE", "Require a deterministic legal evidence union correction")
    content = normalize_draft_result(plan=plan.content, context_asset_version_id=context.asset_version_id,
        context_content_hash=context.content_hash, context_content=context.content, result=result.output,
        provider_evidence=result.to_evidence(), work_requirements=True,
        core_policy="continuous-scene.v1", information_policy="actor-source-scope.v1", realization_contract=contract,
        enforce_voice_contract=not bool((request.command.get("preparation_report") or {}).get("author_workflow")))
    from novel_forge.modules.book_authority.manuscript import validate_complete_prose
    validate_complete_prose(content)
    return {"contract_hash": snapshot_hash(contract), "raw_output_hash": snapshot_hash(result.output),
        "normalized_scene_hash": snapshot_hash(normalized), "changes": changes, "prose_changed": False, "fact_mutation_allowed": False}


def recover_scene_source_union(authority, *, book_run_id, principal):
    book = authority.require(book_run_id)
    principal.require("book.authority.execute", book["project_id"])
    principal.require("chapter.authority.execute", book["project_id"])
    if not book.get("active_chapter_request_id") or book["state"] not in {"PAUSED", "CHAPTER_RUNNING", "CHAPTER_SUBMITTED", "CHAPTER_WAITING_RETRY"}:
        return False
    request = authority.require_chapter_request(book["active_chapter_request_id"])
    with AuthorityUnitOfWork(authority.database_url) as u:
        u.cursor.execute("""SELECT to_jsonb(o) FROM authority_operation o JOIN authority_saga_step s USING(operation_id)
            WHERE o.root_operation_id=%s AND o.project_id=%s AND o.definition_name='chapter.draft.generate'
            AND o.definition_version='3.10.0' AND o.status IN ('FAILED_RETRYABLE','FAILED_FINAL','DEAD_LETTER')
            AND NOT EXISTS(SELECT 1 FROM authority_saga_step_successor j WHERE j.predecessor_operation_id=o.operation_id)""", [request["chapter_root_operation_id"], book["project_id"]])
        rows = u.cursor.fetchall()
        if not rows:
            return False
        if len(rows) != 1 or _cancelled(u.cursor, book) or rows[0][0]["actor_id"] != principal.principal_id:
            raise KernelError("DRAFT_RECOVERY_SOURCE_INVALID", "Require one owned uncancelled native source")
        source = rows[0][0]
        u.cursor.execute("SELECT result->>'error_code' FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number", [source["operation_id"]])
        failures = u.cursor.fetchall()
        if not failures or any(r[0] != "REALIZATION_EPISTEMIC_SCOPE_VIOLATION" for r in failures):
            return False
        if source["status"] == "FAILED_RETRYABLE" and len(failures) < source["definition_snapshot"]["retry_policy"]["max_attempts"]:
            return False
        if has_domain_outputs(u.cursor, source["operation_id"]):
            raise KernelError("DRAFT_RECOVERY_SOURCE_INVALID", "Never replace a materialized draft")
        u.cursor.execute("SELECT to_jsonb(e),b.status,b.evidence FROM authority_external_effect e JOIN authority_budget_reservation b USING(external_effect_id) WHERE e.operation_id=%s ORDER BY e.created_at", [source["operation_id"]])
        retained = []
        for effect, status, accounting in u.cursor.fetchall():
            if effect["status"] != "SUCCEEDED" or status != "SETTLED":
                raise KernelError("KNOWN_RECEIPT_RECONCILIATION_REQUIRED", "Every original effect must be settled")
            result = _receipt(u.cursor, effect["external_effect_id"], book["project_id"], source_operation_id=source["operation_id"], allow_retryable=True)
            proof = revalidate_scene_receipt(source, result, asset_reader=u.repositories.asset_documents)
            u.cursor.execute("SELECT d.dispatch_id FROM authority_external_effect_dispatch d JOIN authority_external_receipt r USING(dispatch_id) WHERE d.external_effect_id=%s AND d.status='SUCCEEDED' AND r.status='VERIFIED' ORDER BY d.generation DESC LIMIT 1", [effect["external_effect_id"]])
            retained.append({"source_effect_id": effect["external_effect_id"], "source_request_hash": effect["request_hash"],
                "source_output_hash": snapshot_hash(result.output), "source_dispatch_id": u.cursor.fetchone()[0],
                "normalization": proof, "cost_authorization_ref": accounting.get("cost_authorization_ref")})
        if not retained or len(retained) != len(failures):
            raise KernelError("DRAFT_RECOVERY_RECEIPT_MISSING", "Bind every failed attempt to a verified raw result")
    if source["status"] == "FAILED_RETRYABLE":
        from novel_forge.modules.command_kernel.attempt_runtime import create_attempt
        try:
            exhausted = create_attempt(authority.database_url, operation_id=source["operation_id"], project_id=source["project_id"],
                max_attempts=source["definition_snapshot"]["retry_policy"]["max_attempts"], trace_id=source["trace_id"], correlation_id=source["correlation_id"])
        except KernelError as error:
            if error.code != "OPERATION_STATUS_CONFLICT":
                raise
            with AuthorityUnitOfWork(authority.database_url) as u:
                u.cursor.execute("SELECT status FROM authority_operation WHERE operation_id=%s AND project_id=%s", [source["operation_id"], source["project_id"]])
                if u.cursor.fetchone() != ("DEAD_LETTER",):
                    raise
            exhausted = {"dead_letter": True}
        if not exhausted.get("dead_letter"):
            raise KernelError("DRAFT_RECOVERY_EXHAUSTION_CHANGED", "Do not create another attempt")
    evidence = {"contract_version": "chapter-known-receipt.v2", "source_operation_id": source["operation_id"],
        **{k: retained[-1][k] for k in ("source_effect_id", "source_request_hash", "source_output_hash", "source_dispatch_id", "cost_authorization_ref")},
        "scene_evidence_union_revalidation": "scene-evidence-union.v1", "settled_draft_receipts": retained,
        "provider_invoked": False, "strict_certification_eligible": False, "completion_checks": "UNCHANGED"}
    def guard(u):
        u.cursor.execute("SELECT version,active_chapter_request_id FROM authority_book_production WHERE book_run_id=%s FOR UPDATE", [book_run_id])
        if u.cursor.fetchone() != (book["version"], book["active_chapter_request_id"]) or _cancelled(u.cursor, book):
            raise KernelError("DRAFT_RECOVERY_FRONTIER_CHANGED", "Reload the exact live frontier")
    from .definitions import chapter_operation_definitions
    target = next(d for d in chapter_operation_definitions(application_build_id=authority.application_build_id, commit_sha=authority.commit_sha,
        model_effects_required=True, coordinated_contract=True) if d["name"] == "chapter.draft.generate" and d["definition_version"] == "3.10.1")
    with AuthorityUnitOfWork(authority.database_url) as u:
        u.repositories.definitions.register(target)
        u.commit()
    replace_failed_step(authority.database_url, predecessor_id=source["operation_id"], target_version="3.10.1",
        context=AdmissionContext(principal.principal_id, principal.permissions, authority.chapter_port.application.registry.available_handler_keys,
            authority.application_build_id, authority.commit_sha), policy_evidence=evidence, expected_failure_code="REALIZATION_EPISTEMIC_SCOPE_VIOLATION",
        known_receipt_effects=tuple((r["source_effect_id"], r["source_request_hash"]) for r in retained),
        window_successor={"contract_version": "kernel-corrected-contract-window.v1", "policy_key": "scene_evidence_union_revalidation", "policy_value": "scene-evidence-union.v1"},
        transaction_guard=guard)
    return True
