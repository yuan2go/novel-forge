from __future__ import annotations

from novel_forge.modules.book_design_authority.foundation import (
    QualifiedFoundationSet,
    FoundationRole,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

CONTRACT = "quality-frozen-world-foundation.v1"


def frozen_world_evidence(cursor, *, project_id, root_operation_id):
    cursor.execute(
        """SELECT b.book_id,b.book_design_version FROM authority_book_production b
        JOIN authority_book_chapter_request r ON r.book_run_id=b.book_run_id
        WHERE r.chapter_root_operation_id=%s AND b.project_id=%s""",
        [root_operation_id, project_id],
    )
    book = cursor.fetchone()
    if not book:
        return None

    def asset(version, expected_hash=None):
        cursor.execute(
            """SELECT v.content_hash,v.content FROM authority_asset_version v
            JOIN authority_asset a USING(asset_id) WHERE v.asset_version_id=%s AND a.project_id=%s""",
            [version, project_id],
        )
        row = cursor.fetchone()
        if not row or expected_hash and row[0] != expected_hash:
            raise KernelError(
                "QUALITY_FOUNDATION_INPUT_DRIFT",
                "Retain the frozen Book Foundation versions and hashes",
            )
        return {
            "asset_version_id": version,
            "content_hash": row[0],
            "project_id": project_id,
        }, row[1]

    design_ref, design = asset(book[1])
    if not design.get("foundation_set"):
        return None
    foundation = QualifiedFoundationSet.from_mapping(design["foundation_set"])
    binding = next(
        b for b in foundation.bindings if b.role is FoundationRole.WORLD_BIBLE
    )
    world_ref, world = asset(binding.asset_version_id, binding.content_hash)
    receipt_ref, receipt = asset(
        binding.qualification_evidence_asset_version_id, binding.qualification_hash
    )
    if (
        world.get("book_id") != book[0]
        or receipt.get("project_id") != project_id
        or receipt.get("design_scope") != "WORLD_BIBLE"
        or receipt.get("transition") != "APPROVE"
        or receipt.get("asset_version_id") != binding.asset_version_id
        or receipt.get("target_content_hash") != binding.content_hash
    ):
        raise KernelError(
            "QUALITY_FOUNDATION_SCOPE_INVALID",
            "An independent governed World design receipt must bind the exact Book input",
        )
    return {
        "contract_version": CONTRACT,
        "book_id": book[0],
        "foundation_set_digest": foundation.set_digest,
        "inputs": [design_ref, world_ref, receipt_ref],
        "world_projection": {
            "asset_version_id": binding.asset_version_id,
            "content_hash": binding.content_hash,
            "qualification_evidence_asset_version_id": binding.qualification_evidence_asset_version_id,
            "qualification_hash": binding.qualification_hash,
            "activation_id": binding.activation_id,
            "rules": world.get("rules", []),
            "constraints": world.get("constraints", []),
            "technology_power": [
                d
                for d in world.get("dimensions", [])
                if d.get("dimension") == "technology_power"
            ],
            "evidence_scope": "Independent governed design constraints and initial capability bounds. Not accepted past events. Empty prior chapter state at genesis is not a contradictory prior state.",
        },
    }


def world_input_bindings(database_url, *, project_id, root_operation_id):
    with AuthorityUnitOfWork(database_url) as uow:
        evidence = frozen_world_evidence(
            uow.cursor, project_id=project_id, root_operation_id=root_operation_id
        )
    return evidence["inputs"] if evidence else []


def request_world_projection(request):
    with AuthorityUnitOfWork(request.database_url) as uow:
        uow.cursor.execute(
            "SELECT root_operation_id FROM authority_operation WHERE operation_id=%s AND project_id=%s",
            [request.operation_id, request.project_id],
        )
        row = uow.cursor.fetchone()
        evidence = (
            frozen_world_evidence(
                uow.cursor, project_id=request.project_id, root_operation_id=row[0]
            )
            if row
            else None
        )
    if not evidence:
        return None
    frozen = {i.asset_version_id: i.content_hash for i in request.inputs}
    if any(
        frozen.get(i["asset_version_id"]) != i["content_hash"]
        for i in evidence["inputs"]
    ):
        raise KernelError(
            "QUALITY_FOUNDATION_INPUT_REQUIRED",
            "Admit exact governed World evidence before assessment; do not read mutable unbound sources",
        )
    return evidence["world_projection"]
