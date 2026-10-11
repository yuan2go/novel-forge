from dataclasses import fields
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


ORIGIN_VERSION = "book-working-revision-origin.v1"
_ROLES = (
    "book_design_version",
    "book_plan_version",
    "foundation_set_digest",
    "production_profile_version",
    "reader_segment_version",
    "reader_contract_version",
    "platform_profile_version",
    "character_state_version",
    "foreshadowing_state_version",
    "quality_trend_version",
    "reward_ledger_version",
    "promise_ledger_version",
    "initial_story_state_version",
    "initial_canon_snapshot_version",
)


def validate_origin_request(origin: Any) -> dict[str, Any]:
    required = {
        "version",
        "source_book_run_id",
        "source_book_version",
        "plan_change_proposal_id",
    }
    if (
        not isinstance(origin, Mapping)
        or not required <= set(origin)
        or set(origin) - required - {"evidence"}
        or origin.get("version") != ORIGIN_VERSION
        or type(origin.get("source_book_version")) is not int
        or origin["source_book_version"] < 0
        or any(
            not isinstance(origin.get(key), str) or not origin[key].strip()
            for key in ("source_book_run_id", "plan_change_proposal_id")
        )
    ):
        raise KernelError(
            "BOOK_REVISION_ORIGIN_INVALID",
            "Working revision requires an exact versioned source and Plan Change",
        )
    return dict(origin)


def require_revision_origin(
    authority: Any, command: Any, *, uow: Any = None
) -> dict[str, Any]:
    origin = validate_origin_request(command.revision_candidate_origin)
    if command.input_mode != "RESOLVED_AUTHORITY_INPUT" or command.edition_revision_id:
        raise KernelError(
            "BOOK_REVISION_ORIGIN_INVALID",
            "Genesis working revision uses resolved inputs and is separate from accepted editions",
        )
    if uow is None:
        with AuthorityUnitOfWork(authority.database_url) as owned:
            return require_revision_origin(authority, command, uow=owned)
    cursor = uow.cursor
    cursor.execute(
        "SELECT to_jsonb(b) FROM authority_book_production b WHERE book_run_id=%s FOR SHARE",
        [origin["source_book_run_id"]],
    )
    row = cursor.fetchone()
    source = row[0] if row else None
    scope = (command.project_id, command.workspace_id, command.book_id)
    if (
        not source
        or tuple(source[key] for key in ("project_id", "workspace_id", "book_id"))
        != scope
    ):
        raise KernelError(
            "BOOK_REVISION_SOURCE_SCOPE_INVALID",
            "Revision source must be this same Project, workspace and Book",
        )
    from .manuscript import AUTHOR_WORKFLOW, effective_workflow

    if (
        source["version"] != origin["source_book_version"]
        or source["state"] not in {"READY", "PAUSED"}
        or source["accepted_through_chapter"] != 0
        or source["active_chapter_request_id"]
        or source["active_child_delegation_id"]
        or effective_workflow(cursor, source) != AUTHOR_WORKFLOW
    ):
        raise KernelError(
            "BOOK_REVISION_SOURCE_CHECKPOINT_REQUIRED",
            "Genesis revision requires the exact settled, unaccepted author-first source checkpoint",
        )
    cursor.execute(
        "SELECT command_payload,status FROM authority_operation WHERE operation_id=%s",
        [source["root_operation_id"]],
    )
    root = cursor.fetchone()
    payload = root[0].get("payload", root[0]) if root else {}
    from .production import StartBookProductionCommand

    if (
        not payload
        or payload.get("revision_candidate_origin")
        or payload.get("edition_revision_id")
    ):
        raise KernelError(
            "BOOK_REVISION_SOURCE_OPENING_REQUIRED",
            "Retain a directly opened source work for genesis revision",
        )
    original = StartBookProductionCommand(
        **{
            field.name: payload[field.name]
            for field in fields(StartBookProductionCommand)
            if field.name in payload
        }
    )
    authority._require_completed_opening_workflow_for_snapshot(original)
    cursor.execute(
        "SELECT to_jsonb(s) FROM authority_book_production_input_snapshot s WHERE snapshot_id=ANY(%s)",
        [[source["input_snapshot_id"], command.input_snapshot_id]],
    )
    snapshots = {item[0]["snapshot_id"]: item[0] for item in cursor.fetchall()}
    previous, current = (
        snapshots.get(source["input_snapshot_id"]),
        snapshots.get(command.input_snapshot_id),
    )
    if (
        not previous
        or not current
        or tuple(current[key] for key in ("project_id", "workspace_id", "book_id"))
        != scope
        or current["narrative_chapter_cursor"] != 1
        or any(previous[key] != current[key] for key in _ROLES)
    ):
        raise KernelError(
            "BOOK_REVISION_GENESIS_INPUT_DRIFT",
            "Retain the source Foundation, Book plan, initial state and policies; only replan its future portfolio",
        )
    cursor.execute(
        """SELECT to_jsonb(p),op.workspace_id,op.status FROM authority_plan_change_proposal p
        JOIN authority_operation op ON op.operation_id=p.activation_operation_id
        WHERE p.proposal_id=%s FOR SHARE OF p""",
        [origin["plan_change_proposal_id"]],
    )
    row = cursor.fetchone()
    proposal = row[0] if row else None
    before = {
        previous["book_plan_version"],
        *previous["volume_portfolio_plan_versions"],
        *previous["arc_portfolio_plan_versions"],
    }
    after = {
        current["book_plan_version"],
        *current["volume_portfolio_plan_versions"],
        *current["arc_portfolio_plan_versions"],
    }
    if (
        not proposal
        or (proposal["project_id"], row[1], proposal["book_id"]) != scope
        or proposal["status"] != "ACTIVE"
        or row[2] != "SUCCEEDED"
        or proposal["target_asset_version_id"] not in before
        or proposal["proposed_asset_version_id"] not in after
    ):
        raise KernelError(
            "BOOK_REVISION_PLAN_CHANGE_REQUIRED",
            "Revision must descend from this source portfolio's confirmed active Plan Change",
        )
    changed = after - before - {proposal["proposed_asset_version_id"]}
    cursor.execute(
        """SELECT binding.asset_version_id,op.command_payload,op.status
        FROM active_story_plan_version active JOIN story_plan_binding binding USING(binding_id)
        JOIN authority_operation op ON op.operation_id=binding.created_by_operation_id
        WHERE binding.project_id=%s AND binding.book_id=%s AND binding.asset_version_id=ANY(%s)
          AND active.asset_version_id=binding.asset_version_id AND binding.freshness='CURRENT'
        FOR SHARE OF active,binding""",
        [command.project_id, command.book_id, list(changed)],
    )
    descendants = {
        asset: (
            frozen.get("decision_evidence", {}).get("parent_plan_change_proposal_id"),
            status,
        )
        for asset, frozen, status in cursor.fetchall()
    }
    if set(descendants) != changed or any(
        value != (proposal["proposal_id"], "SUCCEEDED")
        for value in descendants.values()
    ):
        raise KernelError(
            "BOOK_REVISION_PORTFOLIO_LINEAGE_INVALID",
            "Every changed dependent Plan needs the exact owning activation under this Plan Change",
        )
    evidence = {
        "source_root_operation_id": source["root_operation_id"],
        "source_opening_input_snapshot_id": original.input_snapshot_id,
        "source_current_input_snapshot_id": source["input_snapshot_id"],
        "candidate_input_snapshot_id": command.input_snapshot_id,
        "plan_change_activation_operation_id": proposal["activation_operation_id"],
        "source_evidence_version_id": proposal["source_evidence_version_id"],
        "changed_plan_version_ids": sorted(after - before),
        "source_history_rewritten": False,
        "author_adoption": "NOT_GRANTED",
        "formal_acceptance": "NOT_GRANTED",
    }
    if "evidence" in origin and origin["evidence"] != evidence:
        raise KernelError(
            "BOOK_REVISION_ORIGIN_EVIDENCE_DRIFT",
            "Recorded revision provenance must match its immutable source identities",
        )
    return evidence
