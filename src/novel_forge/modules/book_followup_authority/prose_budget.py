from __future__ import annotations

from copy import deepcopy
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError

from .prose_review import completion_digest, text_digest


def frozen_prose_budget_scope(cursor: Any, identity: dict[str, Any], *, project_id: str) -> dict[str, Any]:
    failure = KernelError("CREATIVE_BUDGET_BUSINESS_SCOPE_UNKNOWN", "review budget requires its exact native accepted manuscript window")
    operation_id = identity.get("source_operation_id", identity["operation_id"])
    command = identity["command_payload"].get("payload", identity["command_payload"])
    request = identity["request_payload"]
    cursor.execute("SELECT input_asset_snapshot FROM authority_operation WHERE project_id=%s AND operation_id=%s AND definition_name='longform.prose_review'", [project_id, operation_id])
    row = cursor.fetchone()
    if not row or len(row[0]) != 1:
        raise failure
    if row[0][0].get("project_id") != project_id:
        raise failure
    binding = {key: row[0][0][key] for key in ("asset_version_id", "content_hash")}
    cursor.execute("SELECT version.content,version.content_hash FROM authority_asset_version version JOIN authority_asset asset USING(asset_id) WHERE asset.project_id=%s AND version.asset_version_id=%s AND asset.asset_type='longform_prose_review_window'", [project_id, binding["asset_version_id"]])
    row = cursor.fetchone()
    if (not row or row[1] != binding["content_hash"] or completion_digest(row[0]) != row[1]
        or row[0].get("source_isolation") not in {"ACCEPTED_PROSE_ONLY", "AUTHOR_SELECTED_UNREVIEWED_PROSE"}):
        raise failure
    frozen = row[0]
    if any(command.get(key) != frozen.get(key) for key in ("book_run_id", "manifest_digest")) or command.get("window_id") != frozen["window"]["window_id"]:
        raise failure
    pointers = [item for item in request.get("_production_execution", {}).get("input_artifacts", []) if item.get("artifact_type") == "longform_prose_review_window"]
    if len(pointers) != 1 or any(pointers[0].get(key) != value for key, value in binding.items()):
        raise failure
    cursor.execute("SELECT run.manifest FROM authority_book_prose_review_run run JOIN authority_book_prose_review_event event USING(run_id) WHERE run.project_id=%s AND run.book_run_id=%s AND run.manifest_digest=%s AND event.kind='WINDOW_ADMITTED' AND event.content->>'operation_id'=%s AND event.content->>'window_id'=%s", [project_id, frozen["book_run_id"], frozen["manifest_digest"], operation_id, frozen["window"]["window_id"]])
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise failure
    manifest = deepcopy(rows[0][0])
    windows = manifest["windows"]
    if not any(window.get("input_asset") == binding and {key: value for key, value in window.items() if key != "input_asset"} == frozen["window"] for window in windows):
        raise failure
    for window in windows:
        window.pop("input_asset", None)
    digest = manifest.pop("manifest_digest")
    if digest != frozen["manifest_digest"] or completion_digest(manifest) != digest:
        raise failure
    spans = frozen["window"]["spans"]
    if not spans or any(type(span.get("chapter_number")) is not int or span["chapter_number"] < 1 for span in spans):
        raise failure
    for span in spans:
        if frozen["source_isolation"] == "AUTHOR_SELECTED_UNREVIEWED_PROSE":
            cursor.execute("""SELECT %s,v.asset_version_id,v.content_hash,v.content FROM authority_asset_version v
                JOIN authority_asset a USING(asset_id) WHERE a.project_id=%s AND v.asset_version_id=%s
                  AND v.governance='CLEAR' AND v.eligibility='ELIGIBLE'""", [span["chapter_number"], project_id, span["asset_version_id"]])
            accepted = cursor.fetchone()
        else:
            cursor.execute("SELECT acceptance.chapter_number,draft.asset_version_id,draft.content_hash,draft.content FROM authority_book_chapter_acceptance acceptance JOIN authority_asset_version outcome ON outcome.asset_version_id=acceptance.chapter_outcome_asset_version_id JOIN authority_asset_version draft ON draft.asset_version_id=outcome.content->>'accepted_draft_asset_version_id' WHERE acceptance.project_id=%s AND acceptance.book_run_id=authority_book_source_run(%s,acceptance.chapter_number) AND acceptance.acceptance_id=%s AND acceptance.status='COMMITTED'", [project_id, frozen["book_run_id"], span["acceptance_id"]])
            accepted = cursor.fetchone()
        if (not accepted or accepted[:3] != (span["chapter_number"], span["asset_version_id"], span["asset_hash"])
            or completion_digest(accepted[3]) != accepted[2] or text_digest(accepted[3]["text"]) != span["text_hash"]
            or accepted[3]["text"][span["start"]:span["end"]] != span["text"]):
            raise failure
    return {"chapter_start": min(span["chapter_number"] for span in spans), "chapter_end": max(span["chapter_number"] for span in spans),
        "manifest_digest": digest, "window": binding, "window_id": frozen["window"]["window_id"],
        "spans": [{key: span[key] for key in ("chapter_number", "acceptance_id", "asset_version_id", "asset_hash", "text_hash", "start", "end")} for span in spans]}
