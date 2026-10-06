from __future__ import annotations

from novel_forge.modules.command_kernel.errors import KernelError

CONTRACT = "grounded-canon-validation.v2"


def selected_validation_policy(cursor, *, project_id, root_operation_id, lock=False):
    from novel_forge.modules.production_execution.execution_template import (
        selected_book_template,
        selected_template,
    )

    cursor.execute(
        """SELECT b.book_run_id,b.book_id,b.active_chapter_request_id,b.accepted_through_chapter,
        b.version,r.chapter_number FROM authority_book_production b JOIN authority_book_chapter_request r
        ON r.chapter_request_id=b.active_chapter_request_id WHERE r.chapter_root_operation_id=%s AND b.project_id=%s"""
        + (" FOR UPDATE OF b,r" if lock else ""),
        [root_operation_id, project_id],
    )
    book = cursor.fetchone()
    admission = (
        selected_book_template(cursor, project_id=project_id, book_id=book[1])
        if book
        else None
    )
    template = (
        selected_template(admission["policy_snapshot"]["policy"], book[1])
        if admission
        else None
    )
    if (
        not template
        or template.get("version") not in {"creative-execution-template.v6", "creative-execution-template.v7", "creative-execution-template.v8"}
        or template.get("canon_validation_contract") != CONTRACT
        or template.get("chapter_contract_recovery") != "KNOWN_SETTLED_CONTRACT_REPAIR"
        or book[5] != book[3] + 1
    ):
        return None
    return {
        "book_run_id": book[0],
        "chapter_request_id": book[2],
        "accepted_cursor": book[3],
        "policy_admission": admission,
        "canon_validation_contract": CONTRACT,
    }


def canon_revalidation_evidence(cursor, source):
    from novel_forge.modules.chapter_authority.domain_handlers import build_canon_patch
    from novel_forge.modules.canon_graph.approval_domain import resolve_canon_extraction
    from novel_forge.modules.production_execution.cost_routing import snapshot_hash

    inputs = {}
    decisions = []
    for binding in source["input_asset_snapshot"]:
        cursor.execute(
            "SELECT a.asset_type,v.content,v.content_hash FROM authority_asset_version v JOIN authority_asset a USING(asset_id) WHERE v.asset_version_id=%s",
            [binding["asset_version_id"]],
        )
        row = cursor.fetchone()
        if not row or row[2] != binding["content_hash"]:
            raise KernelError(
                "CANON_REVALIDATION_INPUT_DRIFT", "Retain the exact frozen Canon inputs"
            )
        if row[0] == "canon_approval_decision":
            decisions.append(
                {**row[1], "asset_version_id": binding["asset_version_id"]}
            )
        else:
            inputs[row[0]] = (binding["asset_version_id"], row[1])
    cursor.execute(
        "SELECT v.asset_version_id,v.content_hash,v.content FROM authority_operation_output_asset o JOIN authority_asset_version v USING(asset_version_id) WHERE o.operation_id=%s AND o.role='primary'",
        [source["operation_id"]],
    )
    old = cursor.fetchone()
    required = {
        "best_draft_candidate",
        "canon_extraction",
        "canon_change_proposal",
        "context_bundle",
    }
    if not old or not required.issubset(inputs):
        raise KernelError(
            "CANON_REVALIDATION_EVIDENCE_REQUIRED",
            "Retain the completed pure Canon reduction and its grounded inputs",
        )
    resolved = resolve_canon_extraction(
        extraction=inputs["canon_extraction"][1],
        proposal={
            **inputs["canon_change_proposal"][1],
            "asset_version_id": inputs["canon_change_proposal"][0],
        },
        decisions=decisions,
    )
    args = dict(
        project_id=source["project_id"],
        revision=inputs["best_draft_candidate"][1],
        revision_asset_version_id=inputs["best_draft_candidate"][0],
        context_bundle_version_id=inputs["context_bundle"][0],
        context_bundle=inputs["context_bundle"][1],
        extraction=resolved,
    )
    legacy = build_canon_patch(**args)
    current = build_canon_patch(**args, validation_contract=CONTRACT)
    changed = sorted(
        k for k in set(legacy) | set(current) if legacy.get(k) != current.get(k)
    )
    if (
        legacy != old[2]
        or not legacy["conflicts"]
        or legacy["gate"] != "BLOCKED"
        or not changed
        or not set(changed).issubset({"conflicts", "deterministic_validation", "gate"})
    ):
        raise KernelError(
            "CANON_REVALIDATION_NOT_APPLICABLE",
            "Only a reproduced derived validator diagnostic may receive this successor",
        )
    return {
        "contract_version": "chapter-canon-derived-revalidation.v1",
        "source_output": {"asset_version_id": old[0], "content_hash": old[1]},
        "input_snapshot": source["input_asset_snapshot"],
        "legacy_reconstructed_exactly": True,
        "changed_fields": changed,
        "corrected_content_hash": snapshot_hash(current),
        "facts_and_state_changed": False,
        "provider_invoked": False,
    }
