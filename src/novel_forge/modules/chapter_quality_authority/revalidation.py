from __future__ import annotations

from novel_forge.modules.command_kernel.errors import KernelError
from .foundation_context import frozen_world_evidence

CONTRACT = "chapter-internal-quality-revalidation.v1"


def quality_revalidation_evidence(cursor, source):
    if (
        source["definition_name"] == "chapter.publishing.prepare_release"
        and source["definition_version"] == "3.9.13"
    ):
        return corrected_publication_evidence(cursor, source)
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

    downstream = list(ChapterNode)[
        list(ChapterNode).index(ChapterNode.PUBLISH_GATE) + 1 :
    ]
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


def corrected_publication_evidence(cursor, source):
    if (
        source["definition_name"] != "chapter.publishing.prepare_release"
        or source["definition_version"] != "3.9.13"
    ):
        raise KernelError(
            "QUALITY_REVALIDATION_NOT_APPLICABLE",
            "Retain the exact internal publication frontier",
        )
    cursor.execute(
        """SELECT to_jsonb(o) FROM authority_operation o WHERE o.root_operation_id=%s
        AND o.definition_name='chapter.quality.evaluate' AND o.definition_version='3.9.25' AND o.status='SUCCEEDED'
        AND o.idempotency_key ~ ':quality-correction:[0-9]+(:action-revalidation)?$'
        ORDER BY substring(o.idempotency_key from ':quality-correction:([0-9]+)')::int DESC,o.created_at DESC LIMIT 1""",
        [source["root_operation_id"]],
    )
    row = cursor.fetchone()
    if not row:
        raise KernelError(
            "QUALITY_REVALIDATION_NOT_READY",
            "Complete the latest native correction assessment",
        )
    latest = row[0]
    cursor.execute(
        """SELECT v.asset_version_id,v.content_hash,v.content FROM authority_operation_output_asset o
        JOIN authority_asset_version v USING(asset_version_id) WHERE o.operation_id=%s AND o.role='primary' """,
        [latest["operation_id"]],
    )
    latest_ref = cursor.fetchone()
    admission = latest_ref[2].get("internal_admission", {}) if latest_ref else {}
    if (
        admission.get("status") != "INTERNAL_ADMITTED"
        or admission.get("strict_certification_eligible") is not False
    ):
        raise KernelError(
            "QUALITY_REVALIDATION_NOT_READY",
            "A blocked correction cannot authorize publication",
        )
    cursor.execute(
        """SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s)
        OR EXISTS(SELECT 1 FROM authority_operation_output_asset WHERE operation_id=%s)""",
        [source["operation_id"]] * 2,
    )
    if cursor.fetchone()[0] or source["status"] not in {
        "READY",
        "ADMITTED",
        "FAILED_RETRYABLE",
    }:
        raise KernelError(
            "QUALITY_REVALIDATION_PUBLISH_STARTED",
            "Preserve publication with effects or committed outputs",
        )
    cursor.execute(
        "SELECT status,result FROM authority_attempt WHERE operation_id=%s",
        [source["operation_id"]],
    )
    if any(
        status != "FAILED_RETRYABLE"
        or result.get("error_code") != "VALIDATION_QUALITY_ADMISSION_REQUIRED"
        for status, result in cursor.fetchall()
    ):
        raise KernelError(
            "QUALITY_REVALIDATION_PUBLISH_FAILURE",
            "Only the frozen blocked-quality admission may be rebound",
        )
    cursor.execute(
        """SELECT EXISTS(SELECT 1 FROM authority_operation_dependency d JOIN authority_attempt a USING(operation_id)
        WHERE d.depends_on_operation_id=%s)""",
        [source["operation_id"]],
    )
    if cursor.fetchone()[0]:
        raise KernelError(
            "QUALITY_REVALIDATION_DOWNSTREAM_STARTED",
            "Started downstream work retains its recovery owner",
        )
    replacements = []
    inputs = []
    for original in source["input_asset_snapshot"]:
        cursor.execute(
            """SELECT a.asset_type,v.content,v.content_hash FROM authority_asset_version v
            JOIN authority_asset a USING(asset_id) WHERE v.asset_version_id=%s AND a.project_id=%s""",
            [original["asset_version_id"], source["project_id"]],
        )
        old = cursor.fetchone()
        if not old or old[2] != original["content_hash"]:
            raise KernelError(
                "QUALITY_REVALIDATION_INPUT_DRIFT",
                "Retain every frozen publication input",
            )
        kind = old[0]
        replacement = None
        if kind == "quality_score_report":
            if old[1].get("internal_admission", {}).get("status") != "BLOCKED":
                raise KernelError(
                    "QUALITY_REVALIDATION_NOT_APPLICABLE",
                    "The source publication must consume blocked quality",
                )
            replacement = {
                "asset_version_id": latest_ref[0],
                "content_hash": latest_ref[1],
            }
        elif kind in {"best_draft_candidate", "re_review_report", "canon_patch"}:
            matches = []
            for binding in latest["input_asset_snapshot"]:
                cursor.execute(
                    """SELECT a.asset_type FROM authority_asset_version v JOIN authority_asset a USING(asset_id)
                    WHERE v.asset_version_id=%s AND v.content_hash=%s AND a.project_id=%s""",
                    [
                        binding["asset_version_id"],
                        binding["content_hash"],
                        source["project_id"],
                    ],
                )
                if cursor.fetchone() == (kind,):
                    matches.append(binding)
            if len(matches) != 1:
                raise KernelError(
                    "QUALITY_REVALIDATION_CORRECTION_INCOMPLETE",
                    "Bind exactly the latest selected candidate, review and Canon",
                )
            replacement = {
                key: matches[0][key] for key in ("asset_version_id", "content_hash")
            }
        if (
            replacement
            and replacement["asset_version_id"] != original["asset_version_id"]
        ):
            cursor.execute(
                "SELECT operation_id FROM authority_operation_output_asset WHERE asset_version_id=%s LIMIT 1",
                [original["asset_version_id"]],
            )
            old_op = cursor.fetchone()
            cursor.execute(
                "SELECT operation_id FROM authority_operation_output_asset WHERE asset_version_id=%s LIMIT 1",
                [replacement["asset_version_id"]],
            )
            new_op = cursor.fetchone()
            replacements.append(
                {
                    "predecessor_operation_id": old_op[0],
                    "successor_operation_id": new_op[0],
                    "old_input": {
                        key: original[key]
                        for key in ("asset_version_id", "content_hash")
                    },
                    "new_input": replacement,
                }
            )
            inputs.append({**original, **replacement})
        else:
            inputs.append(dict(original))
    if not any(
        r["successor_operation_id"] == latest["operation_id"] for r in replacements
    ):
        raise KernelError(
            "QUALITY_REVALIDATION_NOT_APPLICABLE",
            "Keep an already current publication request",
        )
    return {
        "contract_version": CONTRACT,
        "target_version": "3.9.13",
        "input_snapshot": inputs,
        "input_replacements": replacements,
        "diagnostic": {
            "contract_version": "quality-correction-publication.v1",
            "source_quality_operation_id": latest["operation_id"],
            "internal_admission": admission,
        },
    }
