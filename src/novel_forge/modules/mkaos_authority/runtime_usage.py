from __future__ import annotations

import json
from typing import Any

from novel_forge.storage.authority_uow import AuthorityUnitOfWork


_SELECTION = """
    SELECT context_asset.project_id,
           COALESCE(context_version.content->>'book_id', '') AS book_id,
           context_version.asset_version_id AS context_bundle_asset_version_id,
           context_version.content_hash AS context_bundle_content_hash,
           context_version.content AS context_content,
           context_output.operation_id AS context_build_operation_id,
           context_operation.trace_id,
           context_version.content #>> '{context_manifest,task,target_capability_id}' AS target_capability_id,
           context_version.content #> '{context_manifest,narrative_position}' AS narrative_position,
           card.knowledge_pack_id, card.knowledge_pack_asset_version_id,
           card.knowledge_card_asset_version_id, card.knowledge_card_content_hash, card.usage_role, card.frozen_weight,
           selected.value->>'inclusion_reason' AS inclusion_reason,
           selected.value->>'narrative_function' AS narrative_function,
           context_operation.created_at AS selected_at
    FROM authority_operation_output_asset context_output
    JOIN authority_operation context_operation
      ON context_operation.operation_id=context_output.operation_id
     AND context_operation.status='SUCCEEDED'
    JOIN authority_asset_version context_version
      ON context_version.asset_version_id=context_output.asset_version_id
    JOIN authority_asset context_asset
      ON context_asset.asset_id=context_version.asset_id
     AND context_asset.asset_type='context_bundle'
    CROSS JOIN LATERAL jsonb_array_elements(
        COALESCE(context_version.content #> '{context_manifest,selected_inputs}', '[]'::jsonb)
    ) selected(value)
    JOIN LATERAL (
        SELECT NULL::text AS knowledge_pack_id,
               NULL::text AS knowledge_pack_asset_version_id,
               direct.asset_version_id AS knowledge_card_asset_version_id,
               version.content_hash AS knowledge_card_content_hash,
               COALESCE(version.content #>> '{abstract_content,applicability_contract,usage_role}',
                        version.content #>> '{abstract_content,usage_role}', 'REFERENCE') AS usage_role,
               NULL::numeric AS frozen_weight
        FROM authority_mkaos_knowledge_card direct
        JOIN authority_asset_version version ON version.asset_version_id=direct.asset_version_id
        WHERE selected.value->>'asset_type'='knowledge_card'
          AND direct.asset_version_id=selected.value->>'asset_version_id'
          AND direct.project_id=context_asset.project_id
        UNION ALL
        SELECT pack.knowledge_pack_id, pack.asset_version_id,
               item.knowledge_card_asset_version_id, card_version.content_hash, item.usage_role, item.frozen_weight
        FROM authority_mkaos_knowledge_pack pack
        JOIN authority_mkaos_knowledge_pack_item item
          ON item.knowledge_pack_id=pack.knowledge_pack_id
         AND item.knowledge_pack_asset_version_id=pack.asset_version_id
        JOIN authority_asset_version card_version ON card_version.asset_version_id=item.knowledge_card_asset_version_id
        JOIN authority_asset card_asset ON card_asset.asset_id=card_version.asset_id
         AND card_asset.project_id=context_asset.project_id AND card_asset.asset_type='knowledge_card'
        WHERE selected.value->>'asset_type'='knowledge_pack'
          AND pack.asset_version_id=selected.value->>'asset_version_id'
          AND pack.project_id=context_asset.project_id
    ) card ON TRUE
    WHERE context_output.output_key='chapter.context'
      AND context_version.content->>'context_contract_version' IN (
          'authority-context-bundle-v5', 'authority-context-bundle-v6',
          'authority-context-bundle-v7', 'authority-context-bundle-v8')
      AND context_version.content #>> '{context_manifest,contract_version}' IN (
          'narrative-context-manifest-v1', 'narrative-context-manifest-v2',
          'narrative-context-manifest-v3', 'narrative-context-manifest-v4')
      AND context_asset.project_id=%(project_id)s
      AND (%(book_id)s='' OR COALESCE(context_version.content->>'book_id', '')=%(book_id)s)
      AND (%(target_capability_id)s='' OR
           context_version.content #>> '{context_manifest,task,target_capability_id}'=%(target_capability_id)s)
      AND (%(knowledge_card_asset_version_id)s='' OR
           card.knowledge_card_asset_version_id=%(knowledge_card_asset_version_id)s)
"""


def _rows(cursor) -> list[dict[str, Any]]:
    keys = [column.name for column in cursor.description]
    rows = [dict(zip(keys, row, strict=True)) for row in cursor.fetchall()]
    for row in rows:
        context = row.pop("context_content")
        if "receipt_evidence" in row:
            receipts = row["receipt_evidence"]
            row["real_model_call"] = bool(receipts) and all(
                item.get("real_model_call") is True
                and item.get("fixture_protocol_only") is not True for item in receipts
            )
            row["fixture_protocol_only"] = any(
                item.get("fixture_protocol_only") is True for item in receipts
            )
            row["delivery_evidence_class"] = (
                "FIXTURE_PROTOCOL_RECEIPT" if row["fixture_protocol_only"]
                else "REAL_PROVIDER_RECEIPT" if row["real_model_call"]
                else "UNVERIFIED_PROVIDER_RECEIPT"
            )
        row["chapter_plan_asset_version_id"] = (context.get("chapter_execution") or {}).get("source_chapter_plan_asset_version_id", "")
        row["source_chapter_plan_asset_version_id"] = (context.get("production_input_manifest") or {}).get("chapter_plan_version_id", "")
        for segment in context.get("context_segments") or []:
            summary = segment.get("safe_summary")
            if isinstance(summary, str):
                try:
                    summary = json.loads(summary)
                except (TypeError, ValueError):
                    continue
            if not isinstance(summary, dict):
                continue
            translation = summary.get("translation") or {}
            if translation.get("knowledge_card_asset_version_id") == row["knowledge_card_asset_version_id"]:
                row["usage_role"] = translation["usage_role"]
                row["knowledge_translation"] = translation
                if row.get("external_effect_id") and row.get("external_receipt_ids"):
                    from .craft_selection import craft_pattern_signature
                    chapter = int((row.get("narrative_position") or {}).get("chapter") or 0)
                    row["craft_usage"] = [{
                        "mechanism_id": use["mechanism_id"], "mechanism_version": use["mechanism_version"],
                        "pattern_signature": craft_pattern_signature(use["mechanism"]),
                        **({"usage": use["usage"]} if "usage" in use else {}),
                        "family": use["mechanism"]["family"], "use_id": use["use_id"], "scene_id": use["scene_id"], "role": use["role"],
                        "chapter": chapter, "knowledge_card_asset_version_id": row["knowledge_card_asset_version_id"],
                        "content_hash": row["knowledge_card_content_hash"], "external_effect_id": row["external_effect_id"],
                        "external_receipt_ids": row["external_receipt_ids"], "result_asset_version_id": row.get("result_asset_version_id"),
                        "delivery_evidence_class": row.get("delivery_evidence_class"), "craft_strategy_digest": summary.get("craft_strategy_digest"),
                        "evidence_ceiling": "DELIVERY_OBSERVATION_NOT_READER_EFFECT",
                    } for use in summary.get("craft_uses") or []]
    return rows


def list_runtime_usage(
    database_url: str, *, project_id: str, book_id: str = "",
    target_capability_id: str = "", result_asset_version_id: str = "",
    knowledge_card_asset_version_id: str = "", limit: int = 100,
) -> list[dict[str, Any]]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            f"""
            -- WHY: Fence selection and exact version lookups before JSON proof
            -- checks. Flattened project-only joins can multiply unrelated manifest
            -- assets under stale statistics and exhaust the query deadline.
            WITH selection AS MATERIALIZED ({_SELECTION})
            SELECT selection.project_id, selection.book_id,
                   selection.context_bundle_asset_version_id,
                   selection.context_bundle_content_hash, selection.context_content,
                   selection.context_build_operation_id,
                   consumer.operation_id AS consumer_operation_id,
                   consumer.definition_name AS consumer_definition_name,
                   consumer.status AS consumer_status,
                   effect.request_payload #>> '{{_production_execution,attempt_id}}' AS attempt_id,
                   effect.external_effect_id, effect.status AS external_effect_status,
                   effect.provider, effect.model_id, effect.provider_request_id,
                   effect.capability AS capability_id,
                   materialization.asset_version_id AS capability_materialization_asset_version_id,
                   materialization.content_hash AS capability_materialization_content_hash,
                   provider_admission.asset_version_id AS provider_admission_asset_version_id,
                   admission.content #>> '{{provider_request_identity,provider}}' AS frozen_model_provider,
                   admission.content #>> '{{provider_request_identity,model}}' AS frozen_model_id,
                   admission.content #>> '{{prompt_materialization,provider_view,component_hashes,provider_context_view}}' AS provider_context_view_hash,
                   receipts.external_receipt_ids, receipts.receipt_evidence,
                   snapshot.snapshot_id AS capability_pack_snapshot_id,
                   snapshot.pack_id AS capability_pack_id, snapshot.pack_version AS capability_pack_version,
                   result.asset_version_id AS result_asset_version_id,
                   result_asset.asset_type AS result_asset_type,
                   selection.target_capability_id, selection.narrative_position, consumer.trace_id,
                   selection.knowledge_pack_id, selection.knowledge_pack_asset_version_id,
                   selection.knowledge_card_asset_version_id, selection.knowledge_card_content_hash, selection.usage_role, selection.frozen_weight,
                   selection.inclusion_reason, selection.narrative_function,
                   effect.created_at AS consumed_at
            FROM selection
            JOIN authority_operation consumer ON consumer.project_id=selection.project_id
             AND EXISTS (SELECT 1 FROM jsonb_array_elements(consumer.input_asset_snapshot) input(value)
                         WHERE input.value->>'asset_version_id'=selection.context_bundle_asset_version_id)
            JOIN authority_external_effect effect ON effect.operation_id=consumer.operation_id
             AND effect.project_id=selection.project_id AND effect.effect_type='model.invoke'
             AND effect.status='SUCCEEDED'
             AND EXISTS (SELECT 1 FROM jsonb_array_elements(COALESCE(
                    effect.request_payload #> '{{_production_execution,input_artifacts}}', '[]'::jsonb)) input(value)
                 WHERE input.value->>'artifact_type'='context_bundle'
                   AND input.value->>'asset_version_id'=selection.context_bundle_asset_version_id
                   AND input.value->>'content_hash'=selection.context_bundle_content_hash)
            JOIN LATERAL (
                SELECT version.asset_version_id, version.content_hash, version.content
                FROM authority_asset_version version
                JOIN authority_asset owner ON owner.asset_id=version.asset_id
                WHERE version.asset_version_id=effect.request_payload #>> '{{_production_execution,capability_runtime,materialization_asset_version_id}}'
                  AND version.content_hash=effect.request_payload #>> '{{_production_execution,capability_runtime,materialization_content_hash}}'
                  AND owner.project_id=selection.project_id
                  AND owner.asset_type='capability_materialization_manifest'
                OFFSET 0
            ) materialization ON TRUE
            CROSS JOIN LATERAL (SELECT COALESCE(materialization.content->'contract', materialization.content) AS content) materialized
            JOIN LATERAL (
                SELECT version.asset_version_id, version.content_hash, version.content
                FROM authority_asset_version version
                JOIN authority_asset owner ON owner.asset_id=version.asset_id
                WHERE version.asset_version_id=effect.request_payload #>> '{{_production_execution,capability_runtime,provider_admission_asset_version_id}}'
                  AND version.content_hash=effect.request_payload #>> '{{_production_execution,capability_runtime,provider_admission_content_hash}}'
                  AND owner.project_id=selection.project_id
                  AND owner.asset_type='provider_request_admission_manifest'
                OFFSET 0
            ) provider_admission ON TRUE
            JOIN LATERAL (SELECT COALESCE(provider_admission.content->'contract', provider_admission.content) AS content) admission
              ON admission.content->>'capability_materialization_asset_version_id'=materialization.asset_version_id
             AND admission.content->>'capability_materialization_content_hash'=materialization.content_hash
             AND admission.content #>> '{{provider_admission,status}}'='ADMITTED'
             AND admission.content #>> '{{provider_admission,envelope_hash}}'=effect.request_payload #>> '{{_production_execution,capability_runtime,provider_request_envelope_hash}}'
             AND admission.content #>> '{{prompt_materialization,materialization_hash}}'=materialized.content->>'materialization_hash'
             AND admission.content #>> '{{prompt_materialization,fully_rendered_prompt_hash}}'=admission.content #>> '{{provider_request_identity,input_text_hash}}'
             AND admission.content #> '{{prompt_materialization,context_asset_version_ids}}' ? selection.context_bundle_asset_version_id
            JOIN LATERAL (
                SELECT jsonb_agg(receipt.external_receipt_id ORDER BY receipt.external_receipt_id) AS external_receipt_ids,
                       jsonb_agg(jsonb_build_object(
                           'external_receipt_id', receipt.external_receipt_id,
                           'receipt_id', receipt.receipt_id,
                           'payload_hash', receipt.payload_hash,
                           'real_model_call', receipt.payload #> '{{evidence,real_model_call}}',
                           'fixture_protocol_only', receipt.payload #> '{{evidence,fixture_protocol_only}}',
                           'production_verified', receipt.payload #> '{{evidence,production_verified}}',
                           'provider_id', receipt.payload #> '{{evidence,provider_id}}',
                           'model_id', receipt.payload #> '{{evidence,model_id}}'
                       ) ORDER BY receipt.external_receipt_id) AS receipt_evidence
                FROM authority_external_effect_dispatch dispatch
                JOIN authority_external_receipt receipt ON receipt.dispatch_id=dispatch.dispatch_id
                WHERE dispatch.external_effect_id=effect.external_effect_id
                  AND receipt.payload->>'outcome'='success'
                HAVING COUNT(*)>0
            ) receipts ON TRUE
            LEFT JOIN authority_attempt_capability_pack_snapshot snapshot
              ON snapshot.operation_id=consumer.operation_id
             AND snapshot.attempt_id=effect.request_payload #>> '{{_production_execution,attempt_id}}'
            LEFT JOIN authority_operation_output_asset result ON result.operation_id=consumer.operation_id
             AND result.role='primary'
            LEFT JOIN authority_asset result_asset ON result_asset.asset_id=result.asset_id
             AND result_asset.project_id=selection.project_id
            WHERE materialized.content->>'materialization_hash'=effect.request_payload #>> '{{_production_execution,capability_runtime,materialization_hash}}'
              AND EXISTS (SELECT 1 FROM jsonb_array_elements(COALESCE(materialized.content->'context_selection', '[]'::jsonb)) actual(value)
                  WHERE actual.value->>'artifact_type'='context_bundle'
                    AND actual.value->>'asset_version_id'=selection.context_bundle_asset_version_id
                    AND actual.value->>'content_hash'=selection.context_bundle_content_hash
                    AND actual.value->'content'=selection.context_content)
              AND (%(result_asset_version_id)s='' OR result.asset_version_id=%(result_asset_version_id)s)
            ORDER BY consumed_at DESC, context_bundle_asset_version_id,
                     knowledge_pack_id, knowledge_card_asset_version_id, effect.external_effect_id
            LIMIT %(limit)s
            """,
            {"project_id": project_id, "book_id": book_id,
             "target_capability_id": target_capability_id,
             "result_asset_version_id": result_asset_version_id,
             "knowledge_card_asset_version_id": knowledge_card_asset_version_id,
             "limit": limit},
        )
        return _rows(uow.cursor)


def list_runtime_selections(
    database_url: str, *, project_id: str, book_id: str = "",
    target_capability_id: str = "", knowledge_card_asset_version_id: str = "",
    limit: int = 100,
) -> list[dict[str, Any]]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            f"""WITH selection AS ({_SELECTION}) SELECT * FROM selection
            ORDER BY selected_at DESC, context_bundle_asset_version_id,
                     knowledge_pack_id, knowledge_card_asset_version_id LIMIT %(limit)s""",
            {"project_id": project_id, "book_id": book_id,
             "target_capability_id": target_capability_id,
             "knowledge_card_asset_version_id": knowledge_card_asset_version_id,
             "limit": limit},
        )
        return _rows(uow.cursor)


def list_accepted_craft_usage(
    database_url: str, *, project_id: str, book_id: str, limit: int = 100,
) -> list[dict[str, Any]]:
    from novel_forge.modules.review.craft import craft_review_targets
    from novel_forge.modules.review.diagnostics import prose_hash, validate_location
    from .craft import craft_hash
    from .craft_selection import craft_pattern_signature

    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """SELECT acceptance.acceptance_id, acceptance.chapter_number,
                      draft.asset_version_id, draft.content_hash, draft.content,
                      review.asset_version_id, review.content_hash, review.content
               FROM authority_book_chapter_acceptance acceptance
               JOIN authority_asset_version outcome
                 ON outcome.asset_version_id=acceptance.chapter_outcome_asset_version_id
               JOIN authority_asset_version draft
                 ON draft.asset_version_id=outcome.content->>'accepted_draft_asset_version_id'
               JOIN authority_asset_version quality
                 ON quality.asset_version_id=outcome.content->>'quality_aggregate_asset_version_id'
               JOIN authority_asset_version review
                 ON review.asset_version_id=quality.content->>'review_asset_version_id'
               WHERE acceptance.project_id=%s AND acceptance.status='COMMITTED'
                 AND outcome.content->>'book_id'=%s
               ORDER BY acceptance.chapter_number DESC, acceptance.acceptance_id LIMIT %s""",
            [project_id, book_id, limit],
        )
        rows = uow.cursor.fetchall()
    result, seen = [], set()
    for acceptance, chapter, draft_id, draft_hash, draft, review_id, review_hash, review in rows:
        if draft_hash != craft_hash(draft) or review_hash != craft_hash(review):
            from novel_forge.modules.command_kernel.errors import KernelError
            raise KernelError("CRAFT_ACCEPTED_EVIDENCE_DRIFT", "accepted prose and review must retain their exact hashes")
        text = draft["text"]
        source_id = draft.get("selected_source_asset_version_id")
        if review.get("revision_version_id") != source_id or review.get("target_text_hash") != prose_hash(text):
            continue
        targets = {item["use_id"]: item for item in craft_review_targets(draft)}
        for check in review.get("craft_checks", []):
            use = targets.get(check["use_id"])
            identity = (acceptance, check["use_id"])
            if (not use or identity in seen or check.get("target_asset_version_id") != source_id
                or check.get("target_text_hash") != prose_hash(text)
                or check.get("content_hash") != use["content_hash"]):
                continue
            evidence = validate_location(dict(check["evidence"]), text)
            seen.add(identity)
            result.append({
                **{key: use[key] for key in ("mechanism_id", "mechanism_version", "use_id", "scene_id", "role", "knowledge_card_asset_version_id", "content_hash")},
                **({"usage": use["usage"]} if "usage" in use else {}),
                "family": use["mechanism"]["family"],
                "pattern_signature": craft_pattern_signature(use["mechanism"]),
                "chapter": chapter, "acceptance_id": acceptance,
                "accepted_draft_asset_version_id": draft_id, "accepted_draft_content_hash": draft_hash,
                "review_asset_version_id": review_id, "review_content_hash": review_hash,
                "target_text_hash": check["target_text_hash"], "evidence": evidence,
                "effect_status": check["effect_status"], "side_effects": check["side_effects"],
                "evidence_class": check["evidence_class"],
                "usage_basis": "ACCEPTED_PROSE_REVIEW", "reader_effect_proven": False,
            })
    return result
