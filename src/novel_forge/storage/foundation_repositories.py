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
    # Keep the storage module loadable while Book Design Authority composes its
    # application package.  Runtime construction happens only after both
    # modules have completed initialization.
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
        else {("WAITING_APPROVAL", "BOOK_DESIGN"), ("READY", "COMPLETE")}
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
        if tuple(str(item) for item in row[9:14]) != (
            str(row[3]),
            str(row[4]),
            "ACTIVE",
            "ELIGIBLE",
            "CLEAR",
        ) or tuple(str(item) for item in row[14:19]) != (
            "ACTIVE",
            "QUALIFIED",
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
