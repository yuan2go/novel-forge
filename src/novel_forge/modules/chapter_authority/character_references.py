from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError

CONTRACT = "frozen-character-references.v1"


def compile_character_references(*, project_id: str, workspace_id: str, book_id: str,
                                 snapshot_id: str, cast_version_id: str, cast_content_hash: str,
                                 cast: Mapping[str, Any], scenes) -> dict[str, Any]:
    if not all((project_id, workspace_id, book_id, snapshot_id, cast_version_id, cast_content_hash)) or cast.get("book_id") != book_id:
        raise KernelError("CHAPTER_MEMO_REFERENCE_CONTRACT_INVALID", "Require exact Book-scoped frozen cast provenance")
    bindings: dict[str, dict[str, Any]] = {}
    tokens: dict[str, set[str]] = {}
    for row in cast.get("characters", []):
        identity, name = row.get("character_id"), row.get("name")
        aliases = row.get("aliases", [])
        if not isinstance(identity, str) or not identity or not isinstance(name, str) or not name or identity in bindings or not isinstance(aliases, list) or any(not isinstance(a, str) or not a for a in aliases):
            raise KernelError("CHAPTER_MEMO_REFERENCE_CONTRACT_INVALID", "Cast identities and names must be explicit and unique")
        bindings[identity] = {"character_id": identity, "display_name": name, "aliases": list(aliases)}
        for token in (identity, name, *aliases):
            tokens.setdefault(token, set()).add(identity)
    participants: dict[str, str] = {}
    for scene in scenes:
        for token in scene.get("participants", []):
            matches = tokens.get(token, set())
            if len(matches) != 1:
                raise KernelError("CHAPTER_MEMO_REFERENCE_CONTRACT_INVALID", "Each frozen Scene participant needs a unique exact cast binding")
            participants[token] = next(iter(matches))
    legal = sorted(set(participants.values()))
    return {"contract_version": CONTRACT, "project_id": project_id, "workspace_id": workspace_id,
            "book_id": book_id, "input_snapshot_id": snapshot_id, "cast_asset_version_id": cast_version_id,
            "cast_content_hash": cast_content_hash, "bindings": [bindings[i] for i in legal],
            "participant_bindings": participants,
            "token_bindings": {token: next(iter(matches)) for token, matches in tokens.items() if len(matches) == 1 and next(iter(matches)) in legal}}


def normalize_character_choices(intent, result, references=None):
    contract = references or intent.get("character_reference_contract")
    participants = {p for scene in intent.get("scene_plans", []) for p in scene.get("participants", [])}
    normalized = deepcopy(result)
    if contract is None:
        if any(c["character_id"] not in participants for c in normalized["creative_guidance"]["character_choices"]):
            raise KernelError("CHAPTER_MEMO_CHARACTER_DRIFT", "Legacy references require an exact frozen Scene participant")
        return normalized
    if contract.get("contract_version") != CONTRACT or contract.get("project_id") != intent.get("project_id") or (intent.get("book_id") and contract.get("book_id") != intent["book_id"]) or (intent.get("character_reference_contract") and contract != intent["character_reference_contract"]) or set(contract.get("participant_bindings", {})) != participants:
        raise KernelError("CHAPTER_MEMO_REFERENCE_CONTRACT_INVALID", "Reference contract must bind this exact frozen intent")
    targets = set(contract["participant_bindings"].values())
    tokens: dict[str, set[str]] = {}
    for row in contract["bindings"]:
        for token in (row["character_id"], row["display_name"], *row["aliases"]):
            tokens.setdefault(token, set()).add(row["character_id"])
    if set(r["character_id"] for r in contract["bindings"]) != targets:
        raise KernelError("CHAPTER_MEMO_REFERENCE_CONTRACT_INVALID", "Legal references must equal the frozen participant set")
    for choice in normalized["creative_guidance"]["character_choices"]:
        identity = contract.get("token_bindings", {}).get(choice["character_id"])
        matches = tokens.get(choice["character_id"], set()) if identity in targets else set()
        if len(matches) != 1:
            raise KernelError("CHAPTER_MEMO_CHARACTER_DRIFT", "Unknown or ambiguous identity needs a contract repair, not Provider retry")
        choice["character_id"] = next(iter(matches))
    return normalized


def frozen_character_references(request, *, scenes):
    refs = request.command.get("context_version_refs") or {}
    snapshot_id = refs.get("book_production_input_snapshot_id")
    if not snapshot_id:
        return None
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    with AuthorityUnitOfWork(request.database_url) as uow:
        uow.cursor.execute("SELECT foundation_set FROM authority_book_production_input_snapshot WHERE snapshot_id=%s AND project_id=%s AND workspace_id=%s AND book_id=%s",
                           [snapshot_id, request.project_id, request.workspace_id, request.command.get("book_id")])
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("CHAPTER_MEMO_REFERENCE_CONTRACT_INVALID", "Frozen Book snapshot is outside this execution scope")
        bindings = [b for b in row[0].get("bindings", []) if b["role"] == "CHARACTER_CAST"]
        if len(bindings) != 1:
            raise KernelError("CHAPTER_MEMO_REFERENCE_CONTRACT_INVALID", "One frozen cast is required")
        binding = bindings[0]
        cast = uow.repositories.asset_documents.require(project_id=request.project_id, asset_version_id=binding["asset_version_id"])
        if cast.content_hash != binding["content_hash"] or cast.governance != "CLEAR" or cast.eligibility != "ELIGIBLE":
            raise KernelError("CHAPTER_MEMO_REFERENCE_CONTRACT_INVALID", "Frozen cast hash and governance must match")
        return compile_character_references(project_id=request.project_id, workspace_id=request.workspace_id,
            book_id=request.command["book_id"], snapshot_id=snapshot_id, cast_version_id=cast.asset_version_id,
            cast_content_hash=cast.content_hash, cast=cast.content, scenes=scenes)
