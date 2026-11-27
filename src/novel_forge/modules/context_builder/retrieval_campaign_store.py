from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any, Iterable, Mapping

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.context_builder.retrieval_campaign import (
    RetrievalCampaignPolicy,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def start_retrieval_campaign(
    database_url: str,
    *,
    project_id: str,
    book_id: str,
    operation_id: str,
    attempt_id: str,
    fencing_token: int,
    worker_id: str,
    chapter: int,
    intent_asset_version_id: str,
    memo_asset_version_id: str,
    intent_fingerprint: str,
    memo_fingerprint: str,
    accepted_boundary: Mapping[str, Any],
    policy: RetrievalCampaignPolicy,
    coverage_contract: Mapping[str, Any],
) -> dict[str, Any]:
    accepted_through = int(accepted_boundary.get("accepted_through_chapter") or 0)
    body = {
        "project_id": project_id,
        "book_id": book_id,
        "operation_id": operation_id,
        "chapter": chapter,
        "accepted_boundary": dict(accepted_boundary),
        "intent_asset_version_id": intent_asset_version_id,
        "memo_asset_version_id": memo_asset_version_id,
        "intent_fingerprint": intent_fingerprint,
        "memo_fingerprint": memo_fingerprint,
        "policy": policy.to_dict(),
        "coverage_contract": dict(coverage_contract),
    }
    input_fingerprint = _hash(body)
    campaign_id = (
        "retrieval-campaign:" + hashlib.sha256(operation_id.encode()).hexdigest()
    )
    with AuthorityUnitOfWork(database_url) as uow:
        _lock_current_fence(
            uow,
            project_id=project_id,
            operation_id=operation_id,
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            worker_id=worker_id,
        )
        uow.cursor.execute(
            """
            INSERT INTO authority_retrieval_campaign(
                campaign_id, project_id, book_id, operation_id, attempt_id,
                fencing_token, chapter, accepted_through_chapter,
                accepted_boundary, intent_asset_version_id,
                memo_asset_version_id, intent_fingerprint, memo_fingerprint,
                policy_version, policy, coverage_contract, input_fingerprint
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(operation_id) DO NOTHING
            """,
            [
                campaign_id,
                project_id,
                book_id,
                operation_id,
                attempt_id,
                fencing_token,
                chapter,
                accepted_through,
                Jsonb(dict(accepted_boundary)),
                intent_asset_version_id,
                memo_asset_version_id,
                intent_fingerprint,
                memo_fingerprint,
                policy.policy_version,
                Jsonb(policy.to_dict()),
                Jsonb(dict(coverage_contract)),
                input_fingerprint,
            ],
        )
        uow.commit()
    campaign = load_retrieval_campaign(database_url, campaign_id=campaign_id)
    if campaign is None:
        raise KernelError(
            "RETRIEVAL_CAMPAIGN_MISSING",
            "retrieval campaign admission did not persist",
        )
    if campaign["input_fingerprint"] != input_fingerprint:
        raise KernelError(
            "RETRIEVAL_CAMPAIGN_INPUT_CONFLICT",
            "existing retrieval campaign has different frozen inputs",
        )
    return campaign


def load_retrieval_campaign(
    database_url: str, *, campaign_id: str
) -> dict[str, Any] | None:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT campaign_id, project_id, book_id, operation_id, attempt_id,
                   fencing_token, chapter, accepted_through_chapter,
                   accepted_boundary, intent_asset_version_id,
                   memo_asset_version_id, intent_fingerprint, memo_fingerprint,
                   policy_version, policy, coverage_contract, input_fingerprint,
                   status, termination_reason, final_result_fingerprint,
                   final_evidence_identity, version, final_result
            FROM authority_retrieval_campaign WHERE campaign_id=%s
            """,
            [campaign_id],
        )
        row = uow.cursor.fetchone()
    if row is None:
        return None
    return {
        "campaign_id": str(row[0]),
        "project_id": str(row[1]),
        "book_id": str(row[2]),
        "operation_id": str(row[3]),
        "attempt_id": str(row[4]),
        "fencing_token": int(row[5]),
        "chapter": int(row[6]),
        "accepted_through_chapter": int(row[7]),
        "accepted_boundary": dict(row[8]),
        "intent_asset_version_id": str(row[9]),
        "memo_asset_version_id": str(row[10]),
        "intent_fingerprint": str(row[11]),
        "memo_fingerprint": str(row[12]),
        "policy_version": str(row[13]),
        "policy": dict(row[14]),
        "coverage_contract": dict(row[15]),
        "input_fingerprint": str(row[16]),
        "status": str(row[17]),
        "termination_reason": str(row[18]),
        "final_result_fingerprint": str(row[19] or ""),
        "final_evidence_identity": str(row[20] or ""),
        "version": int(row[21]),
        "final_result": dict(row[22]) if row[22] is not None else None,
    }


def freeze_retrieval_round(
    database_url: str,
    *,
    campaign_id: str,
    project_id: str,
    book_id: str,
    operation_id: str,
    attempt_id: str,
    fencing_token: int,
    worker_id: str,
    round_number: int,
    query_plan: Mapping[str, Any],
    documents: Iterable[Mapping[str, Any]],
    rejected_documents: Iterable[Mapping[str, Any]],
    semantic_status: Mapping[str, Any],
    coverage_before: Mapping[str, Any],
    coverage_after: Mapping[str, Any],
    new_evidence_count: int,
    expansion_plan: Mapping[str, Any] | None = None,
    expansion_reason: str = "",
    provider_evidence: Mapping[str, Any] | None = None,
    external_effect_id: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_amount: str | None = None,
    currency: str = "UNKNOWN",
    latency_ms: int | None = None,
) -> dict[str, Any]:
    documents_value = tuple(dict(item) for item in documents)
    rejected_value = tuple(dict(item) for item in rejected_documents)
    expansion_value = dict(expansion_plan or {})
    expansion_fingerprint = str(expansion_value.get("expansion_plan_fingerprint") or "")
    query_fingerprint = str(query_plan.get("query_plan_fingerprint") or "")
    cutoff = str(query_plan.get("candidate_projection_cutoff") or "")
    if not query_fingerprint or not cutoff:
        raise KernelError(
            "RETRIEVAL_ROUND_QUERY_NOT_FROZEN",
            "retrieval round requires a fingerprinted projection cutoff",
        )
    candidate_versions = [
        {"asset_version_id": identity, "content_hash": content_hash}
        for identity, content_hash in sorted(
            {
                (
                    str(item.get("source_asset_version_id") or ""),
                    str(item.get("source_content_hash") or ""),
                )
                for item in documents_value
                if str(item.get("source_asset_version_id") or "")
                and str(item.get("source_content_hash") or "")
            }
        )
    ]
    campaign = load_retrieval_campaign(database_url, campaign_id=campaign_id)
    if campaign is None:
        raise KernelError(
            "RETRIEVAL_CAMPAIGN_MISSING", "retrieval round has no campaign owner"
        )
    core = {
        "contract_version": "retrieval-round-snapshot-v2",
        "campaign_id": campaign_id,
        "project_id": project_id,
        "book_id": book_id,
        "operation_id": operation_id,
        "round_number": round_number,
        "accepted_through_chapter": campaign["accepted_through_chapter"],
        "query_plan": dict(query_plan),
        "query_plan_fingerprint": query_fingerprint,
        "expansion_plan": expansion_value,
        "expansion_plan_fingerprint": expansion_fingerprint,
        "expansion_reason": expansion_reason,
        "provider_evidence": dict(provider_evidence or {}),
        "external_effect_id": external_effect_id or "",
        "candidate_projection_cutoff": cutoff,
        "candidate_asset_versions": candidate_versions,
        "documents": list(documents_value),
        "rejected_documents": list(rejected_value),
        "semantic_status": dict(semantic_status),
        "coverage_before": dict(coverage_before),
        "coverage_after": dict(coverage_after),
        "new_evidence_count": int(new_evidence_count),
        "usage": {
            "input_tokens": _nullable_integer(input_tokens),
            "output_tokens": _nullable_integer(output_tokens),
            "cost_amount": _observed_decimal_text(cost_amount),
            "currency": currency,
            "latency_ms": _nullable_integer(latency_ms),
        },
    }
    snapshot_hash = _hash(core)
    round_id = (
        "retrieval-round:"
        + hashlib.sha256(f"{campaign_id}:{round_number}".encode()).hexdigest()
    )
    with AuthorityUnitOfWork(database_url) as uow:
        _lock_current_fence(
            uow,
            project_id=project_id,
            operation_id=operation_id,
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            worker_id=worker_id,
        )
        uow.cursor.execute(
            """
            INSERT INTO authority_retrieval_round(
                round_id, campaign_id, project_id, book_id, operation_id,
                attempt_id, fencing_token, round_number,
                accepted_through_chapter, query_plan, query_plan_fingerprint,
                expansion_plan, expansion_plan_fingerprint, expansion_reason,
                provider_evidence, external_effect_id,
                candidate_projection_cutoff, candidate_asset_versions,
                documents, rejected_documents, semantic_status,
                coverage_before, coverage_after, new_evidence_count,
                input_tokens, output_tokens, cost_amount, currency,
                latency_ms, snapshot_hash, snapshot_contract_version
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
            ) ON CONFLICT(campaign_id, round_number) DO NOTHING
            """,
            [
                round_id,
                campaign_id,
                project_id,
                book_id,
                operation_id,
                attempt_id,
                fencing_token,
                round_number,
                campaign["accepted_through_chapter"],
                Jsonb(dict(query_plan)),
                query_fingerprint,
                Jsonb(expansion_value),
                expansion_fingerprint,
                expansion_reason,
                Jsonb(dict(provider_evidence or {})),
                external_effect_id or None,
                cutoff,
                Jsonb(candidate_versions),
                Jsonb(list(documents_value)),
                Jsonb(list(rejected_value)),
                Jsonb(dict(semantic_status)),
                Jsonb(dict(coverage_before)),
                Jsonb(dict(coverage_after)),
                int(new_evidence_count),
                _nullable_integer(input_tokens),
                _nullable_integer(output_tokens),
                cost_amount,
                currency,
                _nullable_integer(latency_ms),
                snapshot_hash,
                core["contract_version"],
            ],
        )
        inserted = uow.cursor.rowcount == 1
        uow.commit()
    rounds = load_retrieval_rounds(database_url, campaign_id=campaign_id)
    persisted = next(
        (item for item in rounds if item["round_number"] == round_number), None
    )
    if persisted is None:
        raise KernelError(
            "RETRIEVAL_ROUND_MISSING", "retrieval round snapshot did not persist"
        )
    if persisted["snapshot_hash"] != snapshot_hash:
        raise KernelError(
            "RETRIEVAL_ROUND_CONFLICT",
            "existing retrieval round differs from the frozen replay",
        )
    return {**persisted, "replayed": not inserted}


def load_retrieval_rounds(
    database_url: str, *, campaign_id: str
) -> tuple[dict[str, Any], ...]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT round_id, campaign_id, project_id, book_id, operation_id,
                   attempt_id, fencing_token, round_number,
                   accepted_through_chapter, query_plan,
                   query_plan_fingerprint, expansion_plan,
                   expansion_plan_fingerprint, expansion_reason,
                   provider_evidence, external_effect_id,
                   candidate_projection_cutoff, candidate_asset_versions,
                   documents, rejected_documents, semantic_status,
                   coverage_before, coverage_after, new_evidence_count,
                   input_tokens, output_tokens, cost_amount, currency,
                   latency_ms, snapshot_hash, snapshot_contract_version
            FROM authority_retrieval_round
            WHERE campaign_id=%s ORDER BY round_number
            """,
            [campaign_id],
        )
        rows = uow.cursor.fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        usage = {
            "input_tokens": _nullable_integer(row[24]),
            "output_tokens": _nullable_integer(row[25]),
            "cost_amount": (_decimal_text(row[26]) if row[30] == "retrieval-round-snapshot-v1" else _observed_decimal_text(row[26])),
            "currency": str(row[27]),
            "latency_ms": _nullable_integer(row[28]),
        }
        core = {
            "contract_version": str(row[30]),
            "campaign_id": str(row[1]),
            "project_id": str(row[2]),
            "book_id": str(row[3]),
            "operation_id": str(row[4]),
            "round_number": int(row[7]),
            "accepted_through_chapter": int(row[8]),
            "query_plan": dict(row[9]),
            "query_plan_fingerprint": str(row[10]),
            "expansion_plan": dict(row[11]),
            "expansion_plan_fingerprint": str(row[12]),
            "expansion_reason": str(row[13]),
            "provider_evidence": dict(row[14]),
            "external_effect_id": str(row[15] or ""),
            "candidate_projection_cutoff": row[16].isoformat(),
            "candidate_asset_versions": [dict(item) for item in row[17]],
            "documents": [dict(item) for item in row[18]],
            "rejected_documents": [dict(item) for item in row[19]],
            "semantic_status": dict(row[20]),
            "coverage_before": dict(row[21]),
            "coverage_after": dict(row[22]),
            "new_evidence_count": int(row[23]),
            "usage": usage,
        }
        if _hash(core) != str(row[29]):
            raise KernelError(
                "RETRIEVAL_ROUND_CORRUPT",
                "retrieval round snapshot hash differs from durable content",
            )
        results.append(
            {
                **core,
                "round_id": str(row[0]),
                "attempt_id": str(row[5]),
                "fencing_token": int(row[6]),
                "snapshot_hash": str(row[29]),
            }
        )
    return tuple(results)


def complete_retrieval_campaign(
    database_url: str,
    *,
    campaign_id: str,
    project_id: str,
    operation_id: str,
    attempt_id: str,
    fencing_token: int,
    worker_id: str,
    status: str,
    termination_reason: str,
    final_result_fingerprint: str,
    final_evidence_identity: str,
    final_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if status not in {"COMPLETED", "FALLBACK", "FAILED"}:
        raise KernelError(
            "RETRIEVAL_CAMPAIGN_STATUS_INVALID",
            "retrieval campaign terminal status is invalid",
        )
    if final_result is not None:
        verify_campaign_result(dict(final_result), final_result_fingerprint)
    with AuthorityUnitOfWork(database_url) as uow:
        _lock_current_fence(
            uow,
            project_id=project_id,
            operation_id=operation_id,
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            worker_id=worker_id,
        )
        uow.cursor.execute(
            """
            SELECT status, termination_reason, final_result_fingerprint,
                   final_evidence_identity, book_id
            FROM authority_retrieval_campaign
            WHERE campaign_id=%s AND project_id=%s AND operation_id=%s
            FOR UPDATE
            """,
            [campaign_id, project_id, operation_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "RETRIEVAL_CAMPAIGN_MISSING",
                "retrieval campaign completion target is missing",
            )
        if final_result is not None and (final_result.get("project_id") != project_id
                or final_result.get("book_id") != row[4]
                or (final_result.get("retrieval_campaign") or {}).get("campaign_id") != campaign_id):
            raise KernelError("RETRIEVAL_CAMPAIGN_RESULT_SCOPE", "Final result must bind this exact campaign and Book")
        expected = (
            status,
            termination_reason,
            final_result_fingerprint,
            final_evidence_identity,
        )
        if str(row[0]) != "RUNNING":
            observed = tuple(str(item or "") for item in row[:4])
            if observed != expected:
                raise KernelError(
                    "RETRIEVAL_CAMPAIGN_TERMINAL_CONFLICT",
                    "terminal retrieval campaign differs from replay evidence",
                )
            uow.commit()
            campaign = load_retrieval_campaign(database_url, campaign_id=campaign_id)
            if campaign is None:
                raise KernelError(
                    "RETRIEVAL_CAMPAIGN_MISSING",
                    "terminal retrieval campaign disappeared",
                )
            return campaign
        uow.cursor.execute(
            """
            UPDATE authority_retrieval_campaign
            SET status=%s, termination_reason=%s,
                final_result_fingerprint=%s, final_evidence_identity=%s, final_result=%s,
                version=version+1, updated_at=NOW()
            WHERE campaign_id=%s
            """,
            [
                status,
                termination_reason,
                final_result_fingerprint,
                final_evidence_identity,
                Jsonb(dict(final_result)) if final_result is not None else None,
                campaign_id,
            ],
        )
        uow.commit()
    campaign = load_retrieval_campaign(database_url, campaign_id=campaign_id)
    if campaign is None:
        raise KernelError(
            "RETRIEVAL_CAMPAIGN_MISSING",
            "retrieval campaign disappeared after completion",
        )
    return campaign


def _lock_current_fence(
    uow: AuthorityUnitOfWork,
    *,
    project_id: str,
    operation_id: str,
    attempt_id: str,
    fencing_token: int,
    worker_id: str,
) -> None:
    uow.cursor.execute(
        """
        SELECT 1
        FROM authority_operation AS operation
        JOIN authority_attempt AS attempt
          ON attempt.operation_id=operation.operation_id
        JOIN authority_lease_acquisition AS lease
          ON lease.attempt_id=attempt.attempt_id
        WHERE operation.operation_id=%s AND operation.project_id=%s
          AND operation.status='EXECUTING'
          AND attempt.attempt_id=%s
          AND attempt.status IN ('LEASED','RUNNING','RESULT_SUBMITTED')
          AND lease.fencing_token=%s AND lease.owner=%s
          AND lease.status='HELD' AND lease.expires_at>NOW()
        FOR UPDATE OF attempt, lease
        """,
        [operation_id, project_id, attempt_id, fencing_token, worker_id],
    )
    if uow.cursor.fetchone() is None:
        raise KernelError(
            "RETRIEVAL_CAMPAIGN_FENCE_STALE",
            "retrieval campaign write requires the current Attempt lease",
        )


def _hash(value: Mapping[str, Any]) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
    )


def verify_campaign_result(result: dict[str, Any], fingerprint: str) -> None:
    core = {key: value for key, value in result.items() if key != "result_fingerprint"}
    if result.get("result_fingerprint") != fingerprint or _hash(core) != fingerprint:
        raise KernelError("RETRIEVAL_CAMPAIGN_RESULT_CORRUPT", "Retained terminal retrieval result differs from its exact fingerprint")


def _nullable_integer(value):
    return None if value is None else int(value)


def _observed_decimal_text(value):
    if value is None:
        return None
    normalized = format(Decimal(str(value)), "f")
    return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized


def _decimal_text(value: Any) -> str:
    normalized = format(Decimal(str(value)), "f").rstrip("0").rstrip(".")
    return normalized or "0"


__all__ = [
    "complete_retrieval_campaign",
    "freeze_retrieval_round",
    "load_retrieval_campaign",
    "load_retrieval_rounds",
    "start_retrieval_campaign",
]
