from __future__ import annotations

from types import SimpleNamespace

from novel_forge.modules.chapter_authority.character_references import frozen_character_references
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def require_planning_character_references(database_url, command):
    snapshot = (command.world_preparation_request or {}).get("input_snapshot_id")
    if not snapshot:
        with AuthorityUnitOfWork(database_url) as uow:
            uow.cursor.execute("SELECT input_snapshot_id FROM authority_book_production WHERE project_id=%s AND workspace_id=%s AND book_id=%s AND root_operation_id::text=%s",
                [command.project_id, command.workspace_id, command.book_id, command.correlation_id])
            rows = uow.cursor.fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise KernelError("CHAPTER_MEMO_REFERENCE_CONTRACT_INVALID", "Planning must bind one exact native Book input snapshot")
        snapshot = rows[0][0]
    return frozen_character_references(SimpleNamespace(database_url=database_url,
        project_id=command.project_id, workspace_id=command.workspace_id,
        command={"book_id": command.book_id, "context_version_refs": {"book_production_input_snapshot_id": snapshot}}), scenes=None)


def bind_character_schema(schema, references):
    if references is None:
        return
    choices = sorted(set(references["participant_bindings"]) | {row["character_id"] for row in references["bindings"]})
    if not choices:
        raise KernelError("CHAPTER_MEMO_REFERENCE_CONTRACT_INVALID", "Planning character references require a nonempty frozen cast")
    identity = {"type": "string", "enum": choices,
        "description": "Select an exact frozen character locator. Unnamed background appearances do not create typed participants or character identities."}
    properties = schema["properties"]
    for key in ("character_realization", "character_participation"):
        if key in properties:
            properties[key]["items"]["properties"]["character_id"] = dict(identity)
    if "scene_plan" in properties:
        scene = properties["scene_plan"]["items"]["properties"]
        scene["participants"]["items"] = dict(identity)
        scene["pov_character_id"] = dict(identity)
