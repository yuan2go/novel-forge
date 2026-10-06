from __future__ import annotations

from typing import TYPE_CHECKING, Any

from novel_forge.modules.command_kernel.errors import KernelError

if TYPE_CHECKING:
    from novel_forge.modules.book_design_authority.foundation import (
        QualifiedFoundationSet,
    )


def require_current_foundation_set(
    cursor: Any,
    *,
    project_id: str,
    book_id: str,
    require_ready: bool = False,
    lock: bool = False,
) -> QualifiedFoundationSet:
    # WORKAROUND: defer construction until both sides of the import cycle load.
    from novel_forge.modules.book_design_authority.foundation import (
        FoundationBinding,
        FoundationRole,
        QualifiedFoundationSet,
    )

    lock_clause = (
        " FOR SHARE OF binding, version, state, active, qualification" if lock else ""
    )
    cursor.execute(
        """
        SELECT binding.foundation_role, binding.authority_name,
               binding.asset_version_id, binding.content_hash,
               binding.schema_version,
               binding.qualification_evidence_asset_version_id,
               binding.qualification_hash, binding.activation_operation_id,
               COALESCE(binding.upstream_digest, ''),
               version.content_hash, version.schema_version,
               version.lifecycle, version.eligibility, version.governance,
               state.lifecycle, state.qualification, state.approval,
               state.freshness, active.activated_by_operation_id,
               qualification.content_hash, qualification.lifecycle,
               qualification.eligibility, qualification.governance,
               binding.set_generation, binding.formation_run_id,
               formation.lifecycle, formation.current_stage
        FROM authority_book_foundation_binding AS binding
        JOIN authority_asset_version AS version
          ON version.asset_version_id=binding.asset_version_id
        JOIN authority_story_design_version_state AS state
          ON state.project_id=binding.project_id
         AND state.asset_version_id=binding.asset_version_id
        JOIN authority_story_design_active_version AS active
          ON active.project_id=binding.project_id
         AND active.asset_version_id=binding.asset_version_id
        JOIN authority_asset_version AS qualification
          ON qualification.asset_version_id=
             binding.qualification_evidence_asset_version_id
        JOIN authority_story_formation_run AS formation
          ON formation.formation_run_id=binding.formation_run_id
        WHERE binding.project_id=%s AND binding.book_id=%s
          AND binding.freshness='CURRENT' AND binding.retired_at IS NULL
        ORDER BY binding.foundation_role
        """
        + lock_clause,
        [project_id, book_id],
    )
    rows = cursor.fetchall()
    if (
        len({int(row[23]) for row in rows}) > 1
        or len({str(row[24]) for row in rows}) > 1
    ):
        raise KernelError(
            "FOUNDATION_SET_MIXED_GENERATION",
            "Foundation Set cannot mix Formation runs or set generations",
        )
    allowed_formation_states = (
        {("READY", "COMPLETE")}
        if require_ready
        else {("RUNNING", "BOOK_DESIGN"), ("WAITING_APPROVAL", "BOOK_DESIGN"), ("READY", "COMPLETE")}
    )
    if any(
        (str(row[25]), str(row[26])) not in allowed_formation_states for row in rows
    ):
        raise KernelError(
            "FOUNDATION_FORMATION_NOT_READY",
            "Foundation bindings are not at an allowed durable Formation boundary",
        )
    bindings: list[FoundationBinding] = []
    for row in rows:
        qualification_status = "QUALIFIED"
        if row[15] == "STRUCTURALLY_VALID":
            from novel_forge.modules.story_design_authority.creative_validation import approved_validation_design
            receipt = approved_validation_design(cursor, project_id=project_id, book_id=book_id, asset_version_id=str(row[2]))
            if receipt is None or (receipt["decision_asset_version_id"], receipt["decision_content_hash"]) != (str(row[5]), str(row[6])):
                raise KernelError("FOUNDATION_VALIDATION_DRIFT", "Foundation validation receipt differs from the frozen binding")
            qualification_status = "STRUCTURALLY_VALID"
        elif row[15] == "SEMANTICALLY_VALID":
            from novel_forge.modules.story_design_authority.author_supervision import approved_design_receipt
            receipt = approved_design_receipt(cursor, project_id=project_id, book_id=book_id, asset_version_id=str(row[2]))
            if receipt is None or (receipt["decision_asset_version_id"], receipt["decision_content_hash"]) != (str(row[5]), str(row[6])):
                raise KernelError("FOUNDATION_QUALIFICATION_DRIFT", "Foundation author approval differs from the frozen receipt")
            qualification_status = "SEMANTICALLY_VALID"
        if tuple(str(item) for item in row[9:14]) != (
            str(row[3]),
            str(row[4]),
            "ACTIVE",
            "ELIGIBLE",
            "CLEAR",
        ) or tuple(str(item) for item in row[14:19]) != (
            "ACTIVE",
            qualification_status,
            "APPROVED",
            "CURRENT",
            str(row[7]),
        ):
            raise KernelError(
                "FOUNDATION_BINDING_STALE",
                "Foundation binding no longer matches its active qualified design",
            )
        if tuple(str(item) for item in row[19:23]) != (
            str(row[6]),
            "ACTIVE",
            "ELIGIBLE",
            "CLEAR",
        ):
            raise KernelError(
                "FOUNDATION_QUALIFICATION_DRIFT",
                "Foundation qualification evidence is missing or stale",
            )
        bindings.append(
            FoundationBinding(
                role=FoundationRole(str(row[0])),
                authority=str(row[1]),
                asset_version_id=str(row[2]),
                content_hash=str(row[3]),
                schema_version=str(row[4]),
                qualification_evidence_asset_version_id=str(row[5]),
                qualification_hash=str(row[6]),
                activation_id=str(row[7]),
                upstream_digest=str(row[8]),
            )
        )
    return QualifiedFoundationSet.from_bindings(tuple(bindings))


__all__ = ["require_current_foundation_set"]
