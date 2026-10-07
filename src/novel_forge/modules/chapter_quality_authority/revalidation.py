from __future__ import annotations

from novel_forge.modules.command_kernel.errors import KernelError
from .foundation_context import frozen_world_evidence

CONTRACT = "chapter-internal-quality-revalidation.v1"


def quality_revalidation_evidence(cursor, source):
    root = source["root_operation_id"]
    project = source["project_id"]
    cursor.execute(
        """SELECT o.definition_name,to_jsonb(o) FROM authority_saga_step s
        JOIN authority_operation o USING(operation_id) WHERE o.root_operation_id=%s""",
        [root],
    )
    nodes = dict(cursor.fetchall())
    quality = nodes.get("chapter.quality.evaluate")
    publish = nodes.get("chapter.publishing.prepare_release")
    longform = nodes.get("chapter.quality.longform.evaluate")
    if not quality or not publish or not longform:
        raise KernelError(
            "QUALITY_REVALIDATION_NOT_APPLICABLE",
            "Retain the native Quality and publication frontier",
        )

    def primary(operation):
        cursor.execute(
            """SELECT v.asset_version_id,v.content_hash,v.content FROM authority_operation_output_asset o
            JOIN authority_asset_version v USING(asset_version_id) WHERE o.operation_id=%s AND o.role='primary' """,
            [operation["operation_id"]],
        )
        row = cursor.fetchone()
        if not row:
            raise KernelError(
                "QUALITY_REVALIDATION_NOT_APPLICABLE",
                "A completed assessment and exact output are required",
            )
        return {"asset_version_id": row[0], "content_hash": row[1]}, row[2]

    from novel_forge.modules.chapter_authority.contracts import ChapterNode
    downstream = list(ChapterNode)[list(ChapterNode).index(ChapterNode.PUBLISH_GATE)+1:]
    for node in downstream:
        name = node.definition_name
        operation = nodes.get(name)
        if operation:
            cursor.execute(
                "SELECT EXISTS(SELECT 1 FROM authority_attempt WHERE operation_id=%s)",
                [operation["operation_id"]],
            )
            if cursor.fetchone()[0]:
                raise KernelError(
                    "QUALITY_REVALIDATION_DOWNSTREAM_STARTED",
                    "Preserve dispatched or completed downstream ownership",
                )
    cursor.execute(
        "SELECT count(*) FROM authority_operation_output_asset WHERE operation_id=%s",
        [publish["operation_id"]],
    )
    if cursor.fetchone()[0] or publish["status"] not in {
        "ADMITTED",
        "READY",
        "FAILED_RETRYABLE",
    }:
        raise KernelError(
            "QUALITY_REVALIDATION_PUBLISH_STARTED",
            "Publication must have no committed output",
        )
    cursor.execute(
        "SELECT result,status FROM authority_attempt WHERE operation_id=%s",
        [publish["operation_id"]],
    )
    if any(
        status != "FAILED_RETRYABLE"
        or result.get("error_code") != "VALIDATION_QUALITY_ADMISSION_REQUIRED"
        for result, status in cursor.fetchall()
    ):
        raise KernelError(
            "QUALITY_REVALIDATION_PUBLISH_FAILURE",
            "Unrelated publication failures retain their owner",
        )
    cursor.execute(
        "SELECT count(*) FROM authority_external_effect WHERE operation_id=%s",
        [publish["operation_id"]],
    )
    if cursor.fetchone()[0]:
        raise KernelError(
            "QUALITY_REVALIDATION_PUBLISH_EFFECT",
            "Publication must be unexecuted externally",
        )
    old_quality_ref, quality_report = primary(quality)
    if quality_report.get("internal_admission", {}).get("status") != "BLOCKED":
        raise KernelError(
            "QUALITY_REVALIDATION_NOT_APPLICABLE",
            "Only a blocked internal assessment can receive this correction",
        )
    inputs = [dict(i) for i in source["input_asset_snapshot"]]
    replacements = []
    name = source["definition_name"]
    if (
        name == "chapter.quality.longform.evaluate"
        and source["definition_version"] == "3.9.9"
        and source["status"] == "SUCCEEDED"
    ):
        old_ref, report = primary(source)
        missing = [
            d["dimension"]
            for d in report["dimensions"]
            if d["dimension"] in {"world_rule_conflict", "power_state_conflict"}
            and d["semantic_verdict"] == "INSUFFICIENT_EVIDENCE"
        ]
        if not missing:
            raise KernelError(
                "QUALITY_REVALIDATION_NOT_APPLICABLE",
                "The retained assessment must show missing independent World evidence",
            )
        world = frozen_world_evidence(
            cursor, project_id=project, root_operation_id=root
        )
        if not world or any(
            i["asset_version_id"] in {x["asset_version_id"] for x in inputs}
            for i in world["inputs"]
        ):
            raise KernelError(
                "QUALITY_REVALIDATION_NOT_APPLICABLE",
                "Only an omitted frozen independent Foundation input may be added",
            )
        inputs.extend(world["inputs"])
        target = "3.9.12"
        diagnostic = {
            "missing_dimensions": missing,
            "source_output": old_ref,
            "world_evidence": world,
        }
    elif (
        name == "chapter.quality.evaluate"
        and source["definition_version"] == "3.9.0"
        and source["status"] == "SUCCEEDED"
    ):
        if (
            longform["definition_version"] != "3.9.12"
            or longform["status"] != "SUCCEEDED"
        ):
            raise KernelError(
                "QUALITY_REVALIDATION_NOT_READY",
                "Complete the source-bound World assessment first",
            )
        cursor.execute(
            "SELECT predecessor_operation_id FROM authority_saga_step_revalidation WHERE successor_operation_id=%s",
            [longform["operation_id"]],
        )
        lineage = cursor.fetchone()
        if not lineage:
            raise KernelError(
                "QUALITY_REVALIDATION_LINEAGE_REQUIRED",
                "Retain the exact assessment predecessor",
            )
        cursor.execute(
            "SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s",
            [lineage[0]],
        )
        old_ref, _ = primary(cursor.fetchone()[0])
        new_ref, _ = primary(longform)
        replacements = [
            {
                "predecessor_operation_id": lineage[0],
                "successor_operation_id": longform["operation_id"],
                "old_input": old_ref,
                "new_input": new_ref,
            }
        ]
        target = "3.9.11"
        diagnostic = {
            "source_output": old_quality_ref,
            "old_internal_admission": quality_report["internal_admission"],
        }
    elif (
        name == "chapter.publishing.prepare_release"
        and source["definition_version"] == "3.9.0"
    ):
        if (
            quality["definition_version"] != "3.9.11"
            or quality["status"] != "SUCCEEDED"
        ):
            raise KernelError(
                "QUALITY_REVALIDATION_NOT_READY",
                "Complete the corrected pure Quality disposition first",
            )
        cursor.execute(
            """SELECT to_jsonb(o) FROM authority_operation o WHERE o.root_operation_id=%s
            AND o.definition_name='chapter.quality.evaluate' AND o.idempotency_key LIKE '%%:quality-correction:1'
            AND o.status='SUCCEEDED'""",
            [root],
        )
        corrected = cursor.fetchone()
        active_quality = corrected[0] if corrected else quality
        _, active_report = primary(active_quality)
        if (
            active_report.get("internal_admission", {}).get("status")
            != "INTERNAL_ADMITTED"
        ):
            raise KernelError(
                "QUALITY_REVALIDATION_NOT_READY",
                "Complete required bounded revisions and all assessments before rebinding publication",
            )
        cursor.execute(
            "SELECT predecessor_operation_id FROM authority_saga_step_revalidation WHERE successor_operation_id=%s",
            [quality["operation_id"]],
        )
        lineage = cursor.fetchone()
        if not lineage:
            raise KernelError(
                "QUALITY_REVALIDATION_LINEAGE_REQUIRED",
                "Retain the original Quality output",
            )
        cursor.execute(
            "SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s",
            [lineage[0]],
        )
        old_quality = cursor.fetchone()[0]
        pairs = [(old_quality, active_quality)]
        if corrected:
            for upstream in ("chapter.candidate.select_best", "chapter.canon.update"):
                cursor.execute(
                    """SELECT to_jsonb(o) FROM authority_operation o WHERE o.root_operation_id=%s
                    AND o.definition_name=%s AND o.idempotency_key LIKE '%%:quality-correction:1' AND o.status='SUCCEEDED'""",
                    [root, upstream],
                )
                row = cursor.fetchone()
                if not row:
                    raise KernelError(
                        "QUALITY_REVALIDATION_CORRECTION_INCOMPLETE",
                        "Keep the exact completed correction chain",
                    )
                pairs.append((nodes[upstream], row[0]))
        replacements = []
        for old_operation, new_operation in pairs:
            old_ref, _ = primary(old_operation)
            new_ref, _ = primary(new_operation)
            replacements.append(
                {
                    "predecessor_operation_id": old_operation["operation_id"],
                    "successor_operation_id": new_operation["operation_id"],
                    "old_input": old_ref,
                    "new_input": new_ref,
                }
            )
        if corrected:

            def selected_review(operation):
                cursor.execute(
                    """SELECT v.asset_version_id,v.content_hash FROM authority_operation_output_asset o
                    JOIN authority_asset_version v USING(asset_version_id) WHERE o.operation_id=%s AND o.output_key='chapter.best_candidate.selected_review'""",
                    [operation["operation_id"]],
                )
                row = cursor.fetchone()
                if not row:
                    raise KernelError(
                        "QUALITY_REVALIDATION_REVIEW_REQUIRED",
                        "Bind the selected independent correction review",
                    )
                return {"asset_version_id": row[0], "content_hash": row[1]}

            best_old, best_new = pairs[1]
            replacements.append(
                {
                    "predecessor_operation_id": nodes["chapter.revision.review"][
                        "operation_id"
                    ],
                    "successor_operation_id": best_new["operation_id"],
                    "old_input": selected_review(best_old),
                    "new_input": selected_review(best_new),
                }
            )
        target = "3.9.13"
        diagnostic = {
            "source_quality_operation_id": active_quality["operation_id"],
            "internal_admission": active_report["internal_admission"],
            "correction_generation": 1 if corrected else 0,
        }
    else:
        raise KernelError(
            "QUALITY_REVALIDATION_NOT_APPLICABLE",
            "This correction cannot replace arbitrary work",
        )
    for replacement in replacements:
        matches = [
            i
            for i in inputs
            if all(i.get(k) == v for k, v in replacement["old_input"].items())
        ]
        if len(matches) != 1:
            raise KernelError(
                "QUALITY_REVALIDATION_INPUT_DRIFT",
                "Consume exactly the historical assessment being replaced",
            )
        inputs = [
            {**i, **replacement["new_input"]} if i is matches[0] else i for i in inputs
        ]
    return {
        "contract_version": CONTRACT,
        "target_version": target,
        "input_snapshot": inputs,
        "input_replacements": replacements,
        "diagnostic": diagnostic,
    }
