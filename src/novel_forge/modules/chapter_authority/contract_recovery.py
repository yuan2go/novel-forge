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
    if not book.get("active_chapter_request_id"):
        return False
    request = authority.require_chapter_request(book["active_chapter_request_id"])
    if request["chapter_number"] != book["accepted_through_chapter"] + 1:
        return False
    with AuthorityUnitOfWork(authority.database_url) as uow:
        template = selected_book_template(
            uow.cursor, project_id=book["project_id"], book_id=book["book_id"]
        )
        if not template:
            return False
        uow.cursor.execute(
            """SELECT o.operation_id,o.command_payload,o.input_asset_snapshot FROM authority_operation o
            JOIN authority_saga_step s USING(operation_id) JOIN authority_attempt a USING(operation_id)
            WHERE o.root_operation_id=%s AND o.project_id=%s AND o.definition_name='chapter.draft.generate'
              AND o.definition_version='3.9.0' AND o.status='FAILED_FINAL'
              AND a.result->>'error_code'='REALIZATION_CAPABILITY_INVALID'""",
            [request["chapter_root_operation_id"], book["project_id"]],
        )
        source = uow.cursor.fetchone()
    if not source:
        return False
    query = AuthorityAssetQuery(authority.database_url)
    inputs = [
        query.require(
            project_id=book["project_id"], asset_version_id=a["asset_version_id"]
        )
        for a in source[2]
    ]
    plan = next(a.content for a in inputs if a.asset_type == "chapter_plan")
    context = next(a.content for a in inputs if a.asset_type == "context_bundle")
    compiled = compile_realization_contract(
        plan,
        build_draft_style_view(context, work_requirements=True),
        core_policy="scene-core-slots.v1",
    )
    evidence = {
        "contract_version": "chapter-core-contract-recovery.v1",
        "book_run_id": book_run_id,
        "chapter_request_id": request["chapter_request_id"],
        "policy_admission": template,
        "input_snapshot": source[2],
        "core_projection": compiled["core_projection"],
        "completion_checks": "UNCHANGED",
        "accepted_cursor": book["accepted_through_chapter"],
    }

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
        ):
            from novel_forge.modules.command_kernel.errors import KernelError

            raise KernelError(
                "CHAPTER_CONTRACT_RECOVERY_CONFLICT",
                "Reload the exact Book frontier and policy",
            )

    replace_failed_step(
        authority.database_url,
        predecessor_id=source[0],
        target_version="3.9.1",
        context=AdmissionContext(
            principal.principal_id,
            principal.permissions,
            authority.chapter_port.application.registry.available_handler_keys,
            authority.application_build_id,
            authority.commit_sha,
        ),
        policy_evidence=evidence,
        expected_failure_code="REALIZATION_CAPABILITY_INVALID",
        transaction_guard=guard,
    )
    return True
