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
    approval_ref = None
    if receipt.get("schema_version") == "narrative-design-evaluation.v1":
        cursor.execute(
            """SELECT approval.asset_version_id,approval.content_hash,approval.content
            FROM authority_story_design_transition approved
            JOIN authority_operation approval_op ON approval_op.operation_id=approved.transition_operation_id
              AND approval_op.project_id=approved.project_id AND approval_op.status='SUCCEEDED'
            JOIN authority_operation_output_asset output ON output.operation_id=approval_op.operation_id
            JOIN authority_asset_version approval ON approval.asset_version_id=output.asset_version_id
            JOIN authority_asset approval_asset ON approval_asset.asset_id=approval.asset_id
              AND approval_asset.project_id=approved.project_id
              AND approval_asset.asset_type='story_design_transition_receipt'
            WHERE approved.project_id=%s AND approved.asset_version_id=%s
              AND approved.transition_type='APPROVE'
              AND EXISTS (
                SELECT 1 FROM authority_story_design_transition activated
                JOIN authority_operation activation_op ON activation_op.operation_id=activated.transition_operation_id
                  AND activation_op.project_id=activated.project_id AND activation_op.status='SUCCEEDED'
                WHERE activated.project_id=approved.project_id AND activated.asset_version_id=approved.asset_version_id
                  AND activated.transition_type='ACTIVATE' AND activated.transition_operation_id=%s)
              AND EXISTS (
                SELECT 1 FROM authority_narrative_design_qualification q
                JOIN authority_operation evaluated ON evaluated.operation_id=q.evaluation_operation_id
                  AND evaluated.project_id=q.project_id AND evaluated.status='SUCCEEDED'
                JOIN authority_operation_output_asset evaluated_output ON evaluated_output.operation_id=evaluated.operation_id
                  AND evaluated_output.asset_version_id=q.evaluation_asset_version_id
                WHERE q.project_id=approved.project_id AND q.book_id=%s
                  AND q.asset_version_id=approved.asset_version_id AND q.candidate_content_hash=%s
                  AND q.evaluation_asset_version_id=%s AND q.qualification_status='PASS'
                  AND q.trust_boundary='INDEPENDENT'
                  AND q.generation_operation_id<>q.evaluation_operation_id)
            ORDER BY approved.to_version DESC LIMIT 1""",
            [project_id, binding.asset_version_id, binding.activation_id, book[0],
             binding.content_hash, binding.qualification_evidence_asset_version_id],
        )
        approved = cursor.fetchone()
        if (not approved or receipt.get("project_id") != project_id
                or receipt.get("candidate_asset_version_id") != binding.asset_version_id
                or receipt.get("candidate_content_hash") != binding.content_hash
                or receipt.get("qualification", {}).get("status") != "PASS"):
            raise KernelError(
                "QUALITY_FOUNDATION_SCOPE_INVALID",
                "Frozen independent World qualification needs its exact native approval and activation",
            )
        approval_ref = {"asset_version_id": approved[0], "content_hash": approved[1], "project_id": project_id}
        receipt = approved[2]
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
        "inputs": [design_ref, world_ref, receipt_ref, *([approval_ref] if approval_ref else [])],
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
