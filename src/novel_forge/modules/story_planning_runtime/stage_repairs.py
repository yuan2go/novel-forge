from __future__ import annotations

from dataclasses import replace

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.execution_template import (
    decision_template,
    selected_book_template,
    verify_template_provenance,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def repair_stage(payload):
    from .world_result_recovery import WORLD_GENERATION_CONTRACT_ERRORS

    if (payload.get("repair_result_diagnostic") or {}).get(
        "error_code"
    ) in WORLD_GENERATION_CONTRACT_ERRORS:
        return "world_candidates.generate"
    return payload["generator_operation_name"]


def stage_ordinal(cursor, *, lineage, stage):
    cursor.execute(
        "SELECT g.operation_id,g.repair_number,o.command_payload->'payload',e.external_effect_id,e.status,r.status,e.request_payload->>'stage' FROM authority_story_planning_generation g JOIN authority_operation o USING(operation_id) LEFT JOIN authority_external_effect e USING(operation_id) LEFT JOIN authority_budget_reservation r USING(external_effect_id) WHERE g.operation_id=ANY(%s::text[])",
        [list(lineage)],
    )
    rows = cursor.fetchall()
    if {row[0] for row in rows} != set(lineage) or any(
        row[3] and (row[4] not in {"SUCCEEDED", "FAILED_FINAL"} or row[5] != "SETTLED")
        for row in rows
    ):
        raise KernelError(
            "PLANNING_STAGE_REPAIR_RECONCILIATION_REQUIRED",
            "Preserve every original call and settled usage before phase repair",
        )
    return len(
        {
            row[1]
            for row in rows
            if row[1] and row[3] and row[6] == stage and repair_stage(row[2]) == stage
        }
    )


def repair_bound(application, *, command, operation_id, maximum):
    with AuthorityUnitOfWork(application.database_url) as uow:
        admission = selected_book_template(
            uow.cursor, project_id=command.project_id, book_id=command.book_id
        )
        template = (
            decision_template(
                {
                    "task": {
                        "work_id": command.book_id,
                        "policy_snapshot": admission["policy_snapshot"],
                    }
                }
            )
            if admission
            else None
        )
        if not template or template["version"] not in {"creative-execution-template.v4", "creative-execution-template.v5","creative-execution-template.v6","creative-execution-template.v7", "creative-execution-template.v8", "creative-execution-template.v9"}:
            return None
        from .execution import _planning_repair_routing_lineage

        lineage = _planning_repair_routing_lineage(
            application.database_url,
            project_id=command.project_id,
            book_id=command.book_id,
            generator_operation_name=command.generator_operation_name,
            operation_id=operation_id,
            repair_of_operation_id=command.repair_of_operation_id,
            repair_of_candidate_id=command.repair_of_candidate_id,
        )
        uow.cursor.execute(
            "SELECT request_payload #> '{_production_execution,capability_runtime,routing_decision}' FROM authority_external_effect WHERE operation_id=%s AND request_payload->>'stage'=%s",
            [operation_id, command.generator_operation_name],
        )
        decisions = uow.cursor.fetchall()
        stage = command.generator_operation_name
        if not decisions and command.world_preparation_request:
            stage = "world_candidates.generate"
            uow.cursor.execute(
                "SELECT request_payload #> '{_production_execution,capability_runtime,routing_decision}' FROM authority_external_effect WHERE operation_id=%s AND request_payload->>'stage'=%s",
                [operation_id, stage],
            )
            decisions = uow.cursor.fetchall()
        if not decisions:
            return None
        if len(decisions) != 1:
            raise KernelError("PLANNING_STAGE_REPAIR_SOURCE_AMBIGUOUS", operation_id)
        source = verify_template_provenance(uow.cursor, decisions[0][0])
        if (
            not source
            or source["mode"] != "CREATIVE_VALIDATION"
            or source["require_literary_qualification"]
            or source["member_authorization_ref"]
            != template["member_authorization_ref"]
            or source["require_independent_review"]
            != template["require_independent_review"]
        ):
            return None
        ordinal = stage_ordinal(uow.cursor, lineage=lineage, stage=stage)
    return {
        "version": "native-stage-repair-bound.v1",
        "stage": stage,
        "stage_repair_number": ordinal,
        "monotonic_repair_number": command.repair_number,
        "maximum_repairs": min(
            maximum, template["repair_routing"]["max_same_route_repairs"]
        ),
        "lineage_operation_ids": list(lineage),
        "policy_admission": admission,
    }


def follow_rejected(
    application, *, command, operation_id, candidate_asset_version_id, principal
):
    with AuthorityUnitOfWork(application.database_url) as uow:
        uow.cursor.execute(
            "SELECT status FROM authority_story_planning_generation WHERE operation_id=%s AND candidate_asset_version_id=%s",
            [operation_id, candidate_asset_version_id],
        )
        if uow.cursor.fetchone() not in {("REJECTED",), ("REPAIR_REQUIRED",)}:
            return None
        uow.cursor.execute(
            "SELECT report,report_hash FROM authority_story_planning_validation_report WHERE candidate_asset_version_id=%s AND status='FAIL' ORDER BY created_at DESC LIMIT 1",
            [candidate_asset_version_id],
        )
        failure = uow.cursor.fetchone()
    if not failure:
        return None
    from .application import GENERATOR_CATALOG

    definition = GENERATOR_CATALOG[command.generator_operation_name]
    maximum = (
        definition.maximum_semantic_repairs
        if failure[0]["validation_kind"] == "SEMANTIC"
        else definition.maximum_structural_regenerations
    )
    bound = repair_bound(
        application, command=command, operation_id=operation_id, maximum=maximum
    )
    if bound is None or bound["stage_repair_number"] >= bound["maximum_repairs"]:
        return None
    repaired = replace(
        command,
        runtime_continuation_id="",
        repair_of_candidate_id=candidate_asset_version_id,
        repair_of_operation_id="",
        repair_result_asset_version_id="",
        repair_result_diagnostic=None,
        repair_reason=f"{failure[0]['error_code']}:{failure[1]}",
        repair_number=command.repair_number + 1,
        idempotency_key=f"{command.idempotency_key}:repair:{command.repair_number + 1}",
    )
    return application.generate(repaired, principal=principal)


def resume_rejected_book_plan(composition, book, *, worker):
    if book["state"] != "PLAN_APPROVAL_PENDING":
        return False
    with AuthorityUnitOfWork(composition.authority.database_url) as uow:
        uow.cursor.execute(
            "SELECT g.operation_id,o.command_payload->'payload',g.candidate_asset_version_id FROM authority_story_planning_generation g JOIN authority_operation o USING(operation_id) WHERE g.project_id=%s AND g.book_id=%s AND g.logical_key=%s AND g.status IN ('REJECTED','REPAIR_REQUIRED') ORDER BY g.created_at DESC LIMIT 1",
            [
                book["project_id"],
                book["book_id"],
                f"chapter:{book['accepted_through_chapter'] + 1}",
            ],
        )
        row = uow.cursor.fetchone()
    if not row:
        return False
    from .application import _command_from_payload, GENERATOR_CATALOG

    command = _command_from_payload(row[1])
    worker.require("book.authority.execute", book["project_id"])
    composition.principal.require("story_planning.authority.execute", book["project_id"])
    if (
        command.actor_id != composition.principal.principal_id
        or (command.world_preparation_request or {}).get("book_run_id")
        != book["book_run_id"]
        or (command.world_preparation_request or {}).get("accepted_through_chapter")
        != book["accepted_through_chapter"]
        or not command.auto_approve_low_risk
    ):
        return False
    from novel_forge.modules.story_design_authority.creative_validation import (
        candidate_validation,
    )

    with AuthorityUnitOfWork(composition.authority.database_url) as uow:
        provenance = candidate_validation(
            uow.cursor, project_id=book["project_id"], asset_version_id=row[2]
        )
    if (
        not provenance
        or provenance["generation_operation_id"] != row[0]
        or provenance["book_id"] != book["book_id"]
    ):
        return False
    application = composition.formation.generation.planning
    bound = repair_bound(
        application,
        command=command,
        operation_id=row[0],
        maximum=GENERATOR_CATALOG[
            command.generator_operation_name
        ].maximum_structural_regenerations,
    )
    if bound is None or bound["stage_repair_number"] >= bound["maximum_repairs"]:
        return False
    from novel_forge.modules.book_authority.production import BookProductionState

    composition.authority.advance_supervisor_checkpoint(
        book["book_run_id"],
        expected_version=book["version"],
        expected_state=book["state"],
        target_state=BookProductionState.CHAPTER_PLAN_REQUIRED,
        principal=worker,
    )
    return True
