from __future__ import annotations

from novel_forge.modules.canon_graph.validation_recovery import (
    selected_validation_policy,
    canon_revalidation_evidence,
)
from novel_forge.modules.command_kernel.derived_step_revalidation import (
    replace_derived_step,
    CONTRACT,
)
from novel_forge.modules.command_kernel.service import AdmissionContext
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def recover_derived_frontier(authority, *, book_run_id, principal):
    book = authority.require(book_run_id)
    principal.require("book.authority.execute", book["project_id"])
    principal.require("chapter.authority.execute", book["project_id"])
    if not book.get("active_chapter_request_id"):
        return False
    request = authority.require_chapter_request(book["active_chapter_request_id"])
    root_id = request["chapter_root_operation_id"]
    project = book["project_id"]
    with AuthorityUnitOfWork(authority.database_url) as uow:
        c = uow.cursor
        admission = selected_validation_policy(
            c, project_id=project, root_operation_id=root_id
        )
        if not admission or admission["book_run_id"] != book_run_id:
            return False
        from novel_forge.modules.chapter_quality_authority.revalidation import quality_revalidation_evidence
        c.execute("""SELECT to_jsonb(o) FROM authority_operation o JOIN authority_saga_step s USING(operation_id)
            WHERE o.root_operation_id=%s AND ((o.definition_name='chapter.quality.longform.evaluate' AND o.definition_version='3.9.9' AND o.status='SUCCEEDED')
              OR (o.definition_name='chapter.quality.evaluate' AND o.definition_version='3.9.0' AND o.status='SUCCEEDED')
              OR (o.definition_name='chapter.publishing.prepare_release' AND o.definition_version='3.9.0'))
            ORDER BY CASE o.definition_name WHEN 'chapter.quality.longform.evaluate' THEN 1 WHEN 'chapter.quality.evaluate' THEN 2 ELSE 3 END""", [root_id])
        quality_source = None
        for (candidate,) in c.fetchall():
            try:
                correction = quality_revalidation_evidence(c,candidate)
            except KernelError as error:
                if error.code in {'QUALITY_REVALIDATION_NOT_APPLICABLE','QUALITY_REVALIDATION_NOT_READY'}:
                    continue
                raise
            quality_source = candidate
            quality_evidence = {'admission':admission,'quality_revalidation':correction}
            break
        if quality_source:
            source = quality_source
            evidence = quality_evidence
        c.execute(
            """SELECT to_jsonb(o) FROM authority_operation o JOIN authority_saga_step s USING(operation_id)
            WHERE o.root_operation_id=%s AND o.definition_name='chapter.canon.update' """,
            [root_id],
        )
        row = c.fetchone()
        if not row:
            return False
        canon = row[0]
        source = quality_source
        evidence = quality_evidence if quality_source else None
        if not source and canon["definition_version"] == "3.9.0" and canon["status"] == "SUCCEEDED":
            try:
                diagnostic = canon_revalidation_evidence(c, canon)
            except KernelError as error:
                if error.code == "CANON_REVALIDATION_NOT_APPLICABLE":
                    return False
                raise
            source = canon
            evidence = {"admission": admission, "diagnostic": diagnostic}
        elif not source and canon["definition_version"] == "3.9.10" and canon["status"] == "SUCCEEDED":
            c.execute(
                "SELECT predecessor_operation_id,policy_evidence FROM authority_saga_step_revalidation WHERE successor_operation_id=%s AND contract_version=%s",
                [canon["operation_id"], CONTRACT],
            )
            lineage = c.fetchone()
            if not lineage:
                return False
            c.execute(
                "SELECT v.asset_version_id,v.content_hash FROM authority_operation_output_asset o JOIN authority_asset_version v USING(asset_version_id) WHERE o.operation_id=%s AND o.role='primary'",
                [canon["operation_id"]],
            )
            current = c.fetchone()
            canonical_replacement = {
                "predecessor_operation_id": lineage[0],
                "successor_operation_id": canon["operation_id"],
                "old_input": lineage[1]["diagnostic"]["source_output"],
                "new_input": {
                    "asset_version_id": current[0],
                    "content_hash": current[1],
                },
            }
            c.execute(
                """SELECT to_jsonb(o) FROM authority_operation o JOIN authority_saga_step s USING(operation_id)
                WHERE o.root_operation_id=%s AND o.definition_version='3.9.0'
                  AND ((o.definition_name='chapter.quality.longform.evaluate' AND o.status='SUCCEEDED')
                    OR (o.definition_name='chapter.quality.commercial.evaluate' AND o.status='DEAD_LETTER'))
                ORDER BY o.definition_name LIMIT 1""",
                [root_id],
            )
            row = c.fetchone()
            if not row:
                return False
            source = row[0]
            evidence = {
                "admission": admission,
                "canonical_input_replacement": canonical_replacement,
            }
            if source["status"] == "DEAD_LETTER":
                from novel_forge.modules.chapter_quality_authority.applicability_contract import (
                    quality_applicability_repair_evidence,
                )

                c.execute(
                    "SELECT attempt_id FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number DESC LIMIT 1",
                    [source["operation_id"]],
                )
                evidence["diagnostic"] = quality_applicability_repair_evidence(
                    c, source["operation_id"], c.fetchone()[0]
                )
        if source is None:
            return False
    replace_derived_step(
        authority.database_url,
        predecessor_id=source["operation_id"],
        context=AdmissionContext(
            principal.principal_id,
            principal.permissions,
            authority.chapter_port.application.registry.available_handler_keys,
            authority.application_build_id,
            authority.commit_sha,
        ),
        policy_evidence=evidence,
    )
    return True
