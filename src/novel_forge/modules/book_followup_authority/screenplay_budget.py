from __future__ import annotations

from novel_forge.modules.book_authority.completion_domain import completion_digest
from novel_forge.modules.command_kernel.errors import KernelError
from .screenplay import SOURCE_TYPE, SCREENPLAY_STAGES, require_source


def frozen_screenplay_budget_scope(cursor, identity, *, project_id):
    failure = KernelError("CREATIVE_BUDGET_BUSINESS_SCOPE_UNKNOWN", "Screenplay budget needs its exact accepted edition and mapped source units")
    stage = identity["operation_name"]
    if stage not in SCREENPLAY_STAGES:
        raise failure
    command = identity["command_payload"].get("payload", identity["command_payload"])
    request = identity["request_payload"]
    cursor.execute("SELECT input_asset_snapshot FROM authority_operation WHERE project_id=%s AND operation_id=%s AND definition_name=%s",
                   [project_id, identity.get("source_operation_id", identity["operation_id"]), identity.get("source_definition_name", stage)])
    row = cursor.fetchone()
    if not row:
        raise failure
    sources = []
    for binding in row[0]:
        cursor.execute("""SELECT a.asset_type,v.content,v.content_hash FROM authority_asset a
            JOIN authority_asset_version v USING(asset_id) WHERE a.project_id=%s AND v.asset_version_id=%s""",
            [project_id, binding["asset_version_id"]])
        item = cursor.fetchone()
        if item and item[0] == SOURCE_TYPE:
            if item[2] != binding["content_hash"] or completion_digest(item[1]) != item[2]:
                raise failure
            sources.append((binding, item[1]))
    if len(sources) != 1:
        raise failure
    binding, source = sources[0]
    require_source(source)
    if any(value.get("source_digest") != source["source_digest"] for value in (command, request.get("input", {}))):
        raise failure
    pointers = [item for item in request.get("_production_execution", {}).get("input_artifacts", []) if item.get("artifact_type") == SOURCE_TYPE]
    if len(pointers) != 1 or any(pointers[0].get(key) != binding[key] for key in ("asset_version_id", "content_hash")):
        raise failure
    units = source.get("accepted_source_evidence", {}).get("units", [])
    if not units or [unit["unit_id"] for unit in units] != source["selected_unit_ids"]:
        raise failure
    for unit in units:
        cursor.execute("""SELECT a.book_run_id,a.chapter_number,a.chapter_outcome_asset_version_id,a.story_state_asset_version_id,
            a.canon_snapshot_asset_version_id,a.longform_projection_set_id FROM authority_book_chapter_acceptance a
            JOIN authority_book_production b ON b.book_run_id=a.book_run_id
            WHERE a.project_id=%s AND b.book_id=%s AND a.acceptance_id=%s AND a.status='COMMITTED'""",
            [project_id, source["book_id"], unit["acceptance_id"]])
        if cursor.fetchone() != tuple(unit[key] for key in ("book_run_id", "chapter_number", "outcome_asset_version_id",
            "story_state_asset_version_id", "canon_snapshot_asset_version_id", "projection_set_id")):
            raise failure
    return {"source_revision_id": source["source_revision_id"], "manifest_digest": source["source_manifest_digest"],
        "source_digest": source["source_digest"], "source_asset": {key: binding[key] for key in ("asset_version_id", "content_hash")},
        "chapter_start": min(unit["chapter_number"] for unit in units), "chapter_end": max(unit["chapter_number"] for unit in units),
        "units": units, "novel_canon_mutation_allowed": False}
