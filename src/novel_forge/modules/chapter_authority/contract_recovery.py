from __future__ import annotations

from novel_forge.modules.chapter_authority.realization_composition import (
    compile_realization_contract,
)
from novel_forge.modules.chapter_authority.chapter_plan_views import (
    build_draft_style_view,
)
from novel_forge.modules.command_kernel.service import AdmissionContext
from novel_forge.modules.command_kernel.step_successor import replace_failed_step
from novel_forge.modules.production_execution.execution_template import (
    selected_book_template,
)
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def recover_realization_frontier(authority, *, book_run_id, principal):
    book = authority.require(book_run_id)
    principal.require("book.authority.execute", book["project_id"])
    principal.require("chapter.authority.execute", book["project_id"])
    if book["state"] not in {
        "CHAPTER_RUNNING",
        "CHAPTER_SUBMITTED",
        "CHAPTER_WAITING_RETRY",
    } or not book.get("active_chapter_request_id"):
        return False
    request = authority.require_chapter_request(book["active_chapter_request_id"])
    if request["chapter_number"] != book["accepted_through_chapter"] + 1:
        return False
    with AuthorityUnitOfWork(authority.database_url) as uow:
        template = selected_book_template(
            uow.cursor, project_id=book["project_id"], book_id=book["book_id"]
        )
        if not template or _cancelled(uow.cursor, book):
            return False
        uow.cursor.execute(
            """SELECT DISTINCT o.operation_id,o.command_payload,o.input_asset_snapshot,o.definition_name,o.definition_version FROM authority_operation o
            JOIN authority_saga_step s USING(operation_id) JOIN authority_attempt a USING(operation_id)
            WHERE o.root_operation_id=%s AND o.project_id=%s AND o.definition_name IN ('chapter.draft.generate','chapter.revision.review')
              AND ((o.definition_version='3.9.0' AND o.status='FAILED_FINAL' AND a.result->>'error_code'='REALIZATION_CAPABILITY_INVALID') OR (o.definition_name='chapter.revision.review' AND o.definition_version='3.9.1' AND o.status='DEAD_LETTER' AND a.result->>'error_code'='CAPABILITY_PACK_OPERATION_DEFINITION_DRIFT') OR (o.definition_name='chapter.draft.generate' AND o.definition_version='3.9.2' AND o.status='DEAD_LETTER' AND a.result->>'error_code'='REALIZATION_EPISTEMIC_SCOPE_VIOLATION'))""",
            [request["chapter_root_operation_id"], book["project_id"]],
        )
        source = uow.cursor.fetchone()
        known_effects = ()
        if source and source[4] == "3.9.2":
            uow.cursor.execute("SELECT e.external_effect_id,e.request_hash,e.status,b.status FROM authority_external_effect e JOIN authority_budget_reservation b USING(external_effect_id) WHERE e.operation_id=%s ORDER BY e.created_at", [source[0]])
            effects = uow.cursor.fetchall()
            if not effects or any(row[2:] != ("SUCCEEDED", "SETTLED") for row in effects):
                return False
            from .receipt_recovery import _receipt
            for row in effects:
                _receipt(uow.cursor, row[0], book["project_id"])
            known_effects = tuple(row[:2] for row in effects)
    if not source:
        return recover_quality_frontier(authority, book=book, request=request, template=template, principal=principal)
    query = AuthorityAssetQuery(authority.database_url)
    inputs = [
        query.require(
            project_id=book["project_id"], asset_version_id=a["asset_version_id"]
        )
        for a in source[2]
    ]
    if source[3] == "chapter.draft.generate":
        plan = next(a.content for a in inputs if a.asset_type == "chapter_plan")
        context = next(a.content for a in inputs if a.asset_type == "context_bundle")
        extra = {}
        if source[4] == "3.9.2":
            from .contracts import ChapterHandlerRequest
            from .realization_composition import resolve_accepted_realization_sources
            binding_request = ChapterHandlerRequest(source[0], book["project_id"], "", "", "", source[1], tuple(inputs), database_url=authority.database_url, definition_version="3.9.3")
            extra = {"accepted_sources": resolve_accepted_realization_sources(binding_request),
                "world_preparation": context.get("chapter_execution_expectations", {}).get("world_preparation", {})}
        compiled = compile_realization_contract(
            plan,
            build_draft_style_view(context, work_requirements=True),
            core_policy="continuous-scene.v1" if extra else "scene-core-slots.v1",
            information_policy="actor-source-scope.v1" if extra else "scene-information-flow.v1",
            **extra,
        )
    else:
        compiled = {"core_projection": None, "information_flow": None}
    evidence = {
        "contract_version": "chapter-core-contract-recovery.v1",
        "book_run_id": book_run_id,
        "chapter_request_id": request["chapter_request_id"],
        "policy_admission": template,
        "input_snapshot": source[2],
        "core_projection": compiled["core_projection"],
        "information_flow": compiled["information_flow"],
        "completion_checks": "UNCHANGED",
        "accepted_cursor": book["accepted_through_chapter"],
    }
    if known_effects:
        evidence.update({"contract_version": "chapter-actor-source-successor.v1", "corrected_contract_digest": compiled["contract_digest"],
            "source_receipts": [{"effect_id": e, "request_hash": h} for e, h in known_effects],
            "known_receipt_disposition": "RETAINED_REJECTED_CANDIDATES_NEW_VERSIONED_CONTRACT_GENERATION", "accepted_sources": compiled["accepted_sources"],
            "retry_limit": "UNCHANGED", "business_inputs": "IDENTICAL_FROZEN_VERSIONS"})

    def guard(uow):
        uow.cursor.execute(
            "SELECT version,active_chapter_request_id,accepted_through_chapter FROM authority_book_production WHERE book_run_id=%s AND project_id=%s FOR UPDATE",
            [book_run_id, book["project_id"]],
        )
        current = uow.cursor.fetchone()
        fresh_template = selected_book_template(
            uow.cursor, project_id=book["project_id"], book_id=book["book_id"]
        )
        if (
            current
            != (
                book["version"],
                book["active_chapter_request_id"],
                book["accepted_through_chapter"],
            )
            or fresh_template != template
            or _cancelled(uow.cursor, book)
        ):
            from novel_forge.modules.command_kernel.errors import KernelError

            raise KernelError(
                "CHAPTER_CONTRACT_RECOVERY_CONFLICT",
                "Reload the exact Book frontier and policy",
            )

    replace_failed_step(
        authority.database_url,
        predecessor_id=source[0],
        target_version="3.9.3" if known_effects else "3.9.2",
        context=AdmissionContext(
            principal.principal_id,
            principal.permissions,
            authority.chapter_port.application.registry.available_handler_keys,
            authority.application_build_id,
            authority.commit_sha,
        ),
        policy_evidence=evidence,
        expected_failure_code="REALIZATION_EPISTEMIC_SCOPE_VIOLATION" if known_effects else "REALIZATION_CAPABILITY_INVALID"
        if source[3] == "chapter.draft.generate"
        else "CAPABILITY_PACK_OPERATION_DEFINITION_DRIFT",
        transaction_guard=guard,
        known_receipt_effects=known_effects,
        window_successor={"contract_version": "kernel-corrected-contract-window.v1", "policy_key": "scene_information_flow", "policy_value": "actor-source-scope.v1"} if known_effects else None,
    )
    return True


def _cancelled(cursor, book):
    cursor.execute(
        """SELECT EXISTS(SELECT 1 FROM authority_story_creation_cancellation c
        JOIN authority_story_formation_run f USING(formation_run_id)
        WHERE f.project_id=%s AND f.book_id=%s)""",
        [book["project_id"], book["book_id"]],
    )
    return cursor.fetchone()[0]


def recover_quality_frontier(authority, *, book, request, template, principal):
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.command_kernel.step_successor import replace_failed_steps
    from .receipt_recovery import _receipt
    from .canon_contract_recovery import latest_failure_code
    with AuthorityUnitOfWork(authority.database_url) as u:
        u.cursor.execute("""SELECT DISTINCT o.operation_id,to_jsonb(o) FROM authority_operation o JOIN authority_saga_step s USING(operation_id)
            JOIN authority_attempt a USING(operation_id) WHERE o.root_operation_id=%s AND o.project_id=%s
            AND o.definition_name LIKE 'chapter.quality.%%.evaluate' AND o.definition_version='3.9.0'
            AND o.status IN ('READY','FAILED_RETRYABLE','FAILED_FINAL','DEAD_LETTER')
            AND a.result->>'error_code' IN ('QUALITY_APPLICABILITY_CONFLICT','REVIEW_EVIDENCE_INVALID') ORDER BY o.operation_id""",
            [request["chapter_root_operation_id"],book["project_id"]])
        sources = [row[1] for row in u.cursor.fetchall()]
        if not sources:
            return False
        effects = {}
        results = {}
        for source in sources:
            u.cursor.execute("SELECT e.external_effect_id,e.request_hash,e.status,b.status FROM authority_external_effect e JOIN authority_budget_reservation b USING(external_effect_id) WHERE e.operation_id=%s ORDER BY e.created_at", [source["operation_id"]])
            rows = u.cursor.fetchall()
            if not rows or any(row[2:] != ("SUCCEEDED","SETTLED") for row in rows):
                return False
            effects[source["operation_id"]] = [row[:2] for row in rows]
            results[source["operation_id"]] = [_receipt(u.cursor,row[0],book["project_id"]) for row in rows]
    corrections = []
    for source in sources:
        assets = [AuthorityAssetQuery(authority.database_url).require(project_id=book["project_id"], asset_version_id=a["asset_version_id"]) for a in source["input_asset_snapshot"]]
        revision = next(a for a in assets if a.asset_type == "best_draft_candidate")
        requirements = (revision.content.get("creative_baseline") or {}).get("method_requirements", {})
        diagnostics = []
        for result in results[source["operation_id"]]:
            for row in result.output.get("dimensions", []):
                applicability = (requirements.get(row["dimension"]) or {}).get("status", "APPLICABLE")
                if row.get("gate_status") == "NOT_APPLICABLE" and applicability == "APPLICABLE":
                    diagnostics.append({"dimension": row["dimension"], "constraint": "host-confirmed applicability required", "actual": "NOT_APPLICABLE"})
                for location in row.get("evidence_locations", []):
                    quote = location.get("quote")
                    if not isinstance(quote,str) or quote not in revision.content["text"]:
                        diagnostics.append({"dimension": row["dimension"], "constraint": "exact candidate span required", "actual": quote})
        if not diagnostics:
            return False
        corrections.append({"predecessor_id": source["operation_id"], "target_version": "3.9.1",
            "expected_failure_code": latest_failure_code(authority.database_url,source["operation_id"]),
            "known_receipt_effects": tuple(effects[source["operation_id"]]),
            "policy_evidence": {"contract_version": "chapter-quality-span-successor.v1", "book_run_id": book["book_run_id"],
                "chapter_request_id": request["chapter_request_id"], "policy_admission": template, "repair_diagnostics": diagnostics,
                "source_candidate_asset_version_id": revision.asset_version_id, "source_candidate_content_hash": revision.content_hash,
                "completion_checks": "UNCHANGED"}})
    corrections[0]["window_successor"] = {"contract_version": "kernel-corrected-contract-window.v1", "policy_key": "quality_evidence_spans", "policy_value": "literal-source-spans.v1"}
    def guard(u):
        u.cursor.execute("SELECT version,active_chapter_request_id,accepted_through_chapter FROM authority_book_production WHERE book_run_id=%s FOR UPDATE", [book["book_run_id"]])
        if (u.cursor.fetchone() != (book["version"],book["active_chapter_request_id"],book["accepted_through_chapter"])
            or _cancelled(u.cursor,book) or selected_book_template(u.cursor,project_id=book["project_id"],book_id=book["book_id"]) != template):
            raise KernelError("CHAPTER_CONTRACT_RECOVERY_CONFLICT", "Reload the exact Book frontier and authorization")
    replace_failed_steps(authority.database_url, corrections=corrections, context=AdmissionContext(principal.principal_id,principal.permissions,
        authority.chapter_port.application.registry.available_handler_keys,authority.application_build_id,authority.commit_sha), transaction_guard=guard)
    return True
