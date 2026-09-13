from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import unicodedata

from novel_forge.modules.chapter_outcome.acceptance_contract import resolve_accepted_manuscript
from novel_forge.modules.story_planning_runtime.domain import canonical_hash


def accepted_reading_manifest(*, book: dict, workspaces: list[dict], lineage: dict,
                              through_chapter: int | None = None, require_closed_groups: bool = False) -> dict:
    through = book["accepted_through_chapter"] if through_chapter is None else through_chapter
    if type(through) is not int or not 0 <= through <= book["accepted_through_chapter"]:
        raise ValueError("Reading scope must be an existing accepted Book prefix")
    scope = {key: book[key] for key in ("project_id", "book_id", "book_run_id")}
    if (lineage.get("contract_version") != "book-chapter-group-lineage.v1"
        or any(lineage.get(key) != value for key, value in scope.items())
        or lineage.get("has_more") is not False or lineage.get("offset") != 0
        or lineage.get("accepted_through_chapter") != book["accepted_through_chapter"]):
        raise ValueError("Reading requires complete current native ChapterGroup lineage")
    selected = {}
    for workspace in workspaces:
        acceptance = workspace.get("acceptance") or {}
        if acceptance.get("status") != "COMMITTED":
            continue
        number = acceptance["accepted_through_chapter"]
        if number > through:
            continue
        if number in selected or any(workspace.get(key) != value for key, value in scope.items()):
            raise ValueError("Reading contains duplicate or foreign accepted chapters")
        selected[number] = (workspace, resolve_accepted_manuscript(workspace))
    if set(selected) != set(range(1, through + 1)):
        raise ValueError("Reading requires every exact accepted chapter in the requested prefix")
    groups, owners = set(), {}
    for group in lineage["groups"]:
        if group["group_run_id"] in groups or any(group.get(key) != value for key, value in scope.items()):
            raise ValueError("ChapterGroup identity repeats or belongs to another Book")
        groups.add(group["group_run_id"])
        start, end = group["chapter_range"]
        plan = group["plan"]
        if (type(start) is not int or type(end) is not int or not 1 <= start <= end
            or plan["asset_version_id"] != group["group_plan_version_id"]
            or canonical_hash(plan["content"]) != plan["content_hash"]
            or plan["content"].get("chapter_range") != [start, end]):
            raise ValueError("ChapterGroup range differs from its immutable plan")
        included = [child for child in group["chapters"] if child["status"] == "ACCEPTED" and child["chapter_number"] <= through]
        if included and require_closed_groups and (
            group["state"] != "COMPLETED" or group["accepted_through_chapter"] != end
            or end > through or [child["chapter_number"] for child in included] != list(range(start, end + 1))
        ):
            raise ValueError("Reading checkpoint intersects an incomplete ChapterGroup")
        for child in included:
            number = child["chapter_number"]
            if number not in selected or number in owners or not start <= number <= end:
                raise ValueError("ChapterGroup accepted coverage is duplicate or inconsistent")
            workspace, resolved = selected[number]
            acceptance, outcome = workspace["acceptance"], resolved["outcome"]["content"]
            if (child["acceptance_status"] != "COMMITTED"
                or child["child_root_operation_id"] != workspace["root_operation_id"]
                or child["acceptance_id"] != acceptance["acceptance_id"]
                or child["chapter_outcome_version_id"] != acceptance["outcome_asset_version_id"]
                or outcome.get("parent_group_version_id") != group["group_plan_version_id"]
                or not child.get("chapter_request_id") or not child.get("acceptance_operation_id")
                or any(not child.get(key) or child[key] != acceptance.get(key)
                       for key in ("story_state_asset_version_id", "canon_snapshot_asset_version_id"))):
                raise ValueError("ChapterGroup child differs from the exact accepted manuscript and state")
            command = workspace["run"]["command"]
            plans = [item for values in workspace["artifacts"].values() for item in values
                     if item.get("asset_type") == "chapter_plan" and item["asset_version_id"] == outcome["chapter_plan_version_id"]]
            if not plans or any(
                canonical_hash(item["content"]) != item["content_hash"]
                or item["content"].get("source_extensions", {}).get("source_planning_candidate_asset_version_id") != child["chapter_plan_version_id"]
                or item["content"].get("source_chapter_plan_asset_version_id") != command.get("chapter_plan_asset_version_id")
                or item["content"].get("source_chapter_plan_content_hash") != command.get("chapter_plan_content_hash")
                for item in plans
            ):
                raise ValueError("ChapterGroup planning lineage differs from accepted Chapter input")
            owners[number] = (group, child)
    if set(owners) != set(selected):
        raise ValueError("Native ChapterGroups do not cover the accepted reading prefix")
    chapters = []
    for number, (workspace, resolved) in sorted(selected.items()):
        group, child = owners[number]
        candidate = resolved["candidate"]
        text = candidate["content"]["text"]
        plans = [item for values in workspace["artifacts"].values() for item in values
                 if item.get("asset_type") == "chapter_plan" and item["asset_version_id"] == resolved["outcome"]["content"]["chapter_plan_version_id"]]
        title_source = next((item for item in (candidate, resolved["memo"], *plans) if item["content"].get("title")), None)
        title = str(title_source["content"]["title"]) if title_source else ""
        chapters.append({
            "chapter_number": number, "title": title, "title_status": "RECORDED" if title else "NOT_RECORDED",
            "title_source_asset_version_id": title_source["asset_version_id"] if title_source else "",
            "text": text, "text_hash": resolved["outcome"]["content"]["grounding"]["text_hash"],
            "han_characters": sum(unicodedata.name(char, "").startswith(("CJK UNIFIED IDEOGRAPH-", "CJK COMPATIBILITY IDEOGRAPH-")) for char in text),
            "count_unit": "HAN_CHARACTERS_V1", "acceptance_status": "COMMITTED",
            "acceptance_id": workspace["acceptance"]["acceptance_id"],
            "candidate_asset_version_id": candidate["asset_version_id"], "candidate_content_hash": candidate["content_hash"],
            "outcome_asset_version_id": resolved["outcome"]["asset_version_id"],
            "outcome_content_hash": resolved["outcome"]["content_hash"],
            "review_asset_version_id": resolved["review"]["asset_version_id"],
            "group_run_id": group["group_run_id"], "group_state": group["state"],
            "group_plan_version_id": group["group_plan_version_id"],
            "chapter_request_id": child["chapter_request_id"], "root_operation_id": workspace["root_operation_id"],
            "story_state_asset_version_id": child["story_state_asset_version_id"],
            "canon_snapshot_asset_version_id": child["canon_snapshot_asset_version_id"],
        })
    value = {"contract_version": "accepted-reading-manifest.v1", **scope,
             "accepted_through_chapter": through, "chapters": chapters}
    return {**value, "manifest_hash": canonical_hash(value), "book_version": book.get("version")}


def load_accepted_reading(*, composition: Any, book_run_id: str, through_chapter: int | None = None,
                          require_closed_groups: bool = False) -> dict:
    from novel_forge.modules.chapter_authority.queries import ChapterAuthorityQuery
    book = composition.authority.require(book_run_id)
    query = ChapterAuthorityQuery(composition.authority.database_url)
    runs = query.list_runs(project_id=book["project_id"], book_run_id=book_run_id, limit=500)
    if len(runs) == 500:
        raise ValueError("Reading reached the native workspace page bound")
    workspaces = [query.require_workspace(project_id=book["project_id"], root_operation_id=run["root_operation_id"]) for run in runs]
    lineage = composition.query.chapter_group_execution_lineage(project_id=book["project_id"], book_run_id=book_run_id, limit=500)
    return accepted_reading_manifest(book=book, workspaces=workspaces, lineage=lineage,
                                     through_chapter=through_chapter, require_closed_groups=require_closed_groups)


def write_accepted_reading(manifest: dict, *, destination: Path, book: dict) -> None:
    directory = destination / "reading"
    directory.mkdir(exist_ok=True)
    pages = []
    for chapter in manifest["chapters"]:
        number = chapter["chapter_number"]
        heading = f"第 {number} 章" + (" " + chapter["title"] if chapter["title"] else "")
        page = f"# {heading}\n\n{chapter['text']}\n"
        (directory / f"chapter-{number:03d}.md").write_text(page, encoding="utf-8")
        pages.append(page)
    (destination / "accepted-manuscript.md").write_text("\n\n".join(pages), encoding="utf-8")
    (destination / "accepted-manuscript.json").write_text(json.dumps({
        **manifest, "book_state": book["state"], "full_book_target": book["target_chapter_count"],
        "full_book_completion": "NOT_PROVEN", "independent_human_review": "NOT_REVIEWED",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
