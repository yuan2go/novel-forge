from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority.domain import resolve_book_knowledge_access_policy
from .corpus import CorpusUse, corpus_hash


def require_curated_consumption(
    repository: Any, project: str, frozen: dict, members: list[dict], *,
    intended_use: str = "SOURCE_ANALYSIS", target_book_id: str = "",
) -> dict:
    if intended_use not in {"SOURCE_ANALYSIS", "ABSTRACT_GENERATION"}:
        raise KernelError("CORPUS_CONSUMPTION_INTENT_INVALID", "analysis requires an explicit analysis or abstract-generation use")
    if intended_use == "SOURCE_ANALYSIS":
        if target_book_id:
            raise KernelError("CORPUS_CONSUMPTION_INTENT_INVALID", "a target Book requires intended_use=ABSTRACT_GENERATION")
        return {"schema_version": "source-consumption-admission.v1", "intended_use": intended_use,
                "generation_consumption_allowed": False, "book_status": "NOT_REQUESTED"}
    if not target_book_id.strip():
        raise KernelError("CORPUS_CONSUMPTION_TARGET_REQUIRED", "declare the intended Book identity; its creation and knowledge review may still be pending")
    if frozen["manifest"]["purpose"] != "PRODUCTION_REFERENCE":
        raise KernelError("CORPUS_CONSUMPTION_DENIED", "PRODUCTION_PURPOSE_NOT_GRANTED: preserve this research revision; import and curate a separately authorized production-reference source")
    workspace = frozen["workspace_id"]
    repository.require_scope(project_id=project, workspace_id=workspace)
    decisions = repository.corpus_edition_uses(project, tuple(m["edition_id"] for m in members), CorpusUse.ABSTRACT_GENERATION)
    sources = repository.catalog_processings(project, [m["processing_id"] for m in members])
    denied = repository.corpus_document_denials(project, tuple(s["source_document_id"] for s in sources.values()), CorpusUse.ABSTRACT_GENERATION)
    evidence = []
    for member in members:
        decision = decisions.get(member["edition_id"])
        source = sources.get(member["processing_id"])
        if not decision or decision["decision"] != "ALLOW":
            raise KernelError("CORPUS_CONSUMPTION_DENIED", str(decision["reasons"] if decision else ["RIGHTS_SCOPE_MISSING"]))
        if (not source or source["workspace_id"] != workspace or source["source_document_id"] in denied
                or member["evidence"].get("rights_id") != decision["rights_id"]
                or member["evidence"].get("purpose") != decision["purpose"]):
            raise KernelError("CORPUS_CONSUMPTION_DENIED", "exact source processing, rights, purpose or workspace evidence is unavailable: " + str(denied))
        evidence.append({"processing_id": member["processing_id"], "edition_id": member["edition_id"],
                         "membership_id": member["evidence"]["membership_id"],
                         **{key: decision[key] for key in ("source_id", "snapshot_id", "rights_id", "external_work_id", "purpose", "use", "policy_version")},
                         "rights_declaration_hash": corpus_hash(decision["declaration"])})
    repository.cursor.execute(
        "SELECT project_id,workspace_id,status,production_profile,current_book_asset_version_id FROM authority_book WHERE book_id=%s",
        [target_book_id],
    )
    book = repository.cursor.fetchone()
    policies = []
    book_status = "PENDING_BOOK_CREATION"
    if book:
        if book[:2] != (project, workspace):
            raise KernelError("CORPUS_TARGET_BOOK_SCOPE_INVALID", "declared Book belongs to another project or workspace")
        if book[2] == "ARCHIVED":
            raise KernelError("CORPUS_TARGET_BOOK_UNAVAILABLE", "archived Book cannot consume new knowledge")
        policies.append((str(book[4]), book[3]))
        repository.cursor.execute(
            """SELECT version.asset_version_id,version.content FROM authority_book_production production
               JOIN authority_asset_version version ON version.asset_version_id=production.production_profile_version
               WHERE production.project_id=%s AND production.book_id=%s AND production.state NOT IN ('COMPLETED','ABORTED')
               ORDER BY production.created_at DESC""", [project, target_book_id])
        policies.extend(repository.cursor.fetchall())
        book_status = "EXISTING_BOOK_SCOPE_VERIFIED"
    policy_evidence = []
    for asset_version, profile in policies:
        policy = resolve_book_knowledge_access_policy(production_profile=profile, project_id=project, book_id=target_book_id)
        if policy["mode"] == "DENY_ALL":
            raise KernelError("CORPUS_TARGET_BOOK_KNOWLEDGE_DENIED", "target Book DENY_ALL policy cannot consume the requested external knowledge")
        if policy.get("usage_scope", "PRODUCTION") != "PRODUCTION":
            raise KernelError("CORPUS_TARGET_BOOK_KNOWLEDGE_DENIED", "experimental-only Book policy does not authorize production knowledge consumption")
        policy_evidence.append({"asset_version_id": asset_version, "policy_hash": policy["policy_hash"], "mode": policy["mode"]})
    return {"schema_version": "source-consumption-admission.v1", "intended_use": intended_use,
            "project_id": project, "workspace_id": workspace, "target_book_id": target_book_id,
            "source_use_admitted": True, "generation_consumption_allowed": False,
            "book_status": book_status, "knowledge_status": "PENDING_CARD_REVIEW",
            "target_card_selection_status": "PENDING_CARD_SELECTION_AND_BOOK_POLICY_CHECK",
            "source_evidence": evidence, "book_policy_evidence": policy_evidence}
