from __future__ import annotations

from novel_forge.modules.authority_security import (
    canonical_formation_auto_authorization,
)
from novel_forge.modules.capability_pack_authority.domain import canonical_hash
from novel_forge.modules.command_kernel.budget_runtime import require_known_cli_lineage
from novel_forge.modules.command_kernel.errors import KernelError


def require_auto_replan_proof(
    cursor, *, project_id: str, proposal_id: str, actor_id: str, evidence
):
    if (
        evidence.get("contract_version") != "book-authorized-future-correction.v2"
        or evidence.get("human_decision_claimed") is not False
    ):
        raise KernelError(
            "BOOK_AUTO_REPLAN_PROOF_INVALID",
            "Require explicit native authorization without a human decision claim",
        )
    cursor.execute(
        """SELECT to_jsonb(book),to_jsonb(replan),formation.formation_run_id,formation.frozen_stage_inputs,
        formation.frozen_input_digest,formation.lifecycle FROM authority_book_replan replan
        JOIN authority_book_production book USING(book_run_id)
        JOIN authority_story_formation_run formation ON formation.project_id=book.project_id AND formation.book_id=book.book_id
          AND book.stable_idempotency_key=formation.formation_run_id || ':production'
        WHERE replan.project_id=%s AND replan.plan_change_proposal_id=%s FOR UPDATE OF book,replan""",
        [project_id, proposal_id],
    )
    row = cursor.fetchone()
    if not row:
        raise KernelError(
            "BOOK_AUTO_REPLAN_SCOPE_INVALID",
            "Use the exact original Formation and Book Replan owner",
        )
    book, replan, formation_id, frozen, digest, lifecycle = row
    policy = frozen.get("generation_policy") or {}
    authorization = canonical_formation_auto_authorization(
        policy.get("auto_authorization") or {}
    )
    expected = {
        "project_id": project_id,
        "workspace_id": book["workspace_id"],
        "book_id": book["book_id"],
        "formation_run_id": formation_id,
        "authorized_by_principal_id": actor_id,
    }
    if (
        lifecycle != "READY"
        or policy.get("approval_mode") != "AUTO"
        or authorization != evidence.get("authorization")
        or any(authorization.get(k) != v for k, v in expected.items())
        or digest != evidence.get("formation_input_digest")
        or not {
            "story_planning.candidate.approve",
            "story_planning.candidate.activate",
            "plan_change.future_only.approve",
        }
        <= set(authorization["allowed_actions"])
        or book["state"] != "REPLAN_APPROVAL_PENDING"
        or replan["status"] != "APPROVAL_PENDING"
        or replan["future_only"] is not True
        or replan["affected_scope"]
        not in {"ARC", "ARC_SEGMENT", "CHAPTER_GROUP", "CHAPTER"}
        or replan["replan_id"] != evidence.get("book_replan_id")
        or int(book["version"]) != evidence.get("book_version")
        or book["input_snapshot_id"] != evidence.get("book_input_snapshot_id")
        or int(book["accepted_through_chapter"])
        != evidence.get("accepted_through_chapter")
        or book["active_story_state_version_id"]
        != evidence.get("accepted_story_state_version_id")
        or book["active_canon_snapshot_version_id"]
        != evidence.get("accepted_canon_snapshot_version_id")
    ):
        raise KernelError(
            "BOOK_AUTO_REPLAN_FRONTIER_DRIFT",
            "Retain original grant, future scope and immutable accepted frontier",
        )
    from novel_forge.modules.book_authority.reader_pack import (
        require_current_reader_template,
    )

    require_current_reader_template(
        cursor, project_id=project_id, book_id=book["book_id"]
    )
    require_known_cli_lineage(
        cursor, project_id=project_id, operation_id=book["root_operation_id"]
    )
    cursor.execute(
        """SELECT EXISTS(SELECT 1 FROM authority_story_creation_cancellation WHERE formation_run_id=%s)
        OR EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=%s)""",
        [formation_id, book["root_operation_id"]],
    )
    if cursor.fetchone()[0]:
        raise KernelError(
            "BOOK_AUTO_REPLAN_CANCELLED", "Cancellation revokes automatic future work"
        )
    for key, column in (
        ("source_recap", "source_recap_asset_version_id"),
        ("replan_request", "replan_request_asset_version_id"),
        ("candidate", "replacement_candidate_asset_version_id"),
    ):
        ref = evidence.get(key) or {}
        cursor.execute(
            """SELECT version.content_hash,version.content FROM authority_asset_version version JOIN authority_asset asset USING(asset_id)
            WHERE version.asset_version_id=%s AND asset.project_id=%s AND version.governance='CLEAR'""",
            [replan[column], project_id],
        )
        stored = cursor.fetchone()
        if not stored or ref != {
            "asset_version_id": replan[column],
            "content_hash": stored[0],
        }:
            raise KernelError(
                "BOOK_AUTO_REPLAN_ASSET_DRIFT",
                "Every proposal input retains its exact native owner hash",
            )
        content = stored[1]
        if key == "source_recap":
            lineage = content.get("accepted_input_lineage") or {}
            if (
                content.get("book_id") != book["book_id"]
                or lineage.get("observed_through_chapter")
                != book["accepted_through_chapter"]
                or lineage.get("accepted_story_state_version")
                != book["active_story_state_version_id"]
                or lineage.get("accepted_canon_snapshot_version")
                != book["active_canon_snapshot_version_id"]
            ):
                raise KernelError(
                    "BOOK_AUTO_REPLAN_RECAP_STALE",
                    "Recap must observe exactly this accepted frontier",
                )
        if key == "replan_request" and (
            content.get("required_authority") != "PLAN_CHANGE_AUTHORITY"
            or content.get("future_from_chapter")
            != int(book["accepted_through_chapter"]) + 1
            or content.get("impact_scope", {}).get("future_only") is not True
            or content.get("affected_scope") != replan["affected_scope"]
        ):
            raise KernelError(
                "BOOK_AUTO_REPLAN_SCOPE_INVALID",
                "Proposal cannot modify accepted history or escalate future scope",
            )
    cursor.execute(
        """SELECT EXISTS(SELECT 1 FROM authority_operation_output_asset recap
        JOIN authority_operation owner ON owner.operation_id=recap.operation_id
        JOIN authority_operation_output_asset request ON request.operation_id=owner.operation_id
        WHERE recap.asset_version_id=%s AND request.asset_version_id=%s AND owner.project_id=%s
          AND owner.workspace_id=%s AND owner.actor_id=%s AND owner.definition_name='longform.recap'
          AND owner.definition_version='1.1.0' AND owner.status='SUCCEEDED')""",
        [
            replan["source_recap_asset_version_id"],
            replan["replan_request_asset_version_id"],
            project_id,
            book["workspace_id"],
            actor_id,
        ],
    )
    if not cursor.fetchone()[0]:
        raise KernelError(
            "BOOK_AUTO_REPLAN_RECAP_OWNER_INVALID",
            "Only exact successful native Recap outputs authorize this proposal",
        )
    cursor.execute(
        """SELECT decision.comparison,decision.comparison_hash,search.input_snapshot_hash,
        search.accepted_through_chapter,search.parent_state_asset_version_id,search.desired_transformation
        FROM authority_story_planning_generation generation
        JOIN authority_story_narrative_search search ON search.search_id=generation.narrative_search_id
        JOIN authority_story_narrative_search_decision decision ON decision.search_id=search.search_id
        WHERE generation.operation_id=%s AND generation.project_id=%s AND decision.selected_candidate_asset_version_id=%s""",
        [
            replan["generation_operation_id"],
            project_id,
            replan["replacement_candidate_asset_version_id"],
        ],
    )
    selection = cursor.fetchone()
    if (
        not selection
        or canonical_hash(selection[0]) != selection[1]
        or selection[1] != evidence.get("comparison_hash")
        or selection[2] != evidence.get("search_input_snapshot_hash")
        or selection[3] != book["accepted_through_chapter"]
        or selection[4] != book["active_story_state_version_id"]
        or selection[5].get("replan_request_asset_version_id")
        != replan["replan_request_asset_version_id"]
        or selection[5].get("target_asset_version_id")
        != replan["target_asset_version_id"]
    ):
        raise KernelError(
            "BOOK_AUTO_REPLAN_COMPARISON_DRIFT",
            "Comparison is only evidence for this exact future correction",
        )
