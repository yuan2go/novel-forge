from __future__ import annotations

from typing import Any, Mapping


def output_capacity_contract_failure(decision: Mapping[str, Any]) -> bool:
    task = decision.get("task") or {}
    candidates = decision.get("candidates") or []
    return bool(candidates) and any(
        candidate.get("rejected_reasons") == ["CONTEXT_CAPACITY_EXCEEDED"]
        and int(task.get("output_tokens") or 0)
        > int((candidate.get("candidate") or {}).get("output_limit") or 0) > 0
        and int(task.get("input_tokens") or 0) + int(candidate["candidate"]["output_limit"])
        <= int(candidate["candidate"].get("context_limit") or 0)
        for candidate in candidates
    )


def read_reader_recovery_source(cursor, operation_id: str, project_id: str) -> dict[str, Any] | None:
    cursor.execute("""SELECT to_jsonb(operation), attempt.result->>'error_code',
        EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=operation.operation_id)
        FROM authority_operation operation JOIN LATERAL (SELECT result FROM authority_attempt
          WHERE operation_id=operation.operation_id ORDER BY attempt_number DESC LIMIT 1) attempt ON TRUE
        WHERE operation.operation_id=%s AND operation.project_id=%s""", [operation_id, project_id])
    row = cursor.fetchone()
    if not row or row[2]:
        return None
    source = dict(row[0])
    if source.get("definition_name") != "reader_outcome.evaluate":
        return None
    if (source.get("definition_version") == "1.1.0" and source.get("status") == "FAILED_FINAL"
        and row[1] == "READER_OUTCOME_PROVIDER_CONTEXT_VIEW_INVALID"):
        return source
    if (source.get("definition_version") != "1.2.0" or source.get("status") != "DEAD_LETTER"
        or row[1] != "PROVIDER_ROUTING_BLOCKED"):
        return None
    cursor.execute("""SELECT version.content FROM authority_asset_version version
        JOIN authority_asset asset USING(asset_id) WHERE asset.project_id=%s
          AND asset.asset_type='routing_decision' AND version.content #>> '{task,operation_id}'=%s""",
        [project_id, operation_id])
    decisions = [dict(item[0]) for item in cursor.fetchall()]
    if decisions and all(output_capacity_contract_failure(item) for item in decisions):
        return source
    return None
