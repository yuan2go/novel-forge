from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from novel_forge.modules.command_kernel.asset_runtime import (
    AssetCommandContext,
    bind_blob_to_asset_version,
    request_blob_upload,
    reserve_blob,
    verify_blob,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapter,
)
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    accept_external_effect_receipt,
    acquire_effect_dispatch,
    dispatch_external_effect,
    prepare_effect_dispatch,
    reconcile_external_effect,
    submit_effect_dispatch_result,
)
from novel_forge.modules.production_execution.security import (
    assert_legacy_execution_allowed,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


@dataclass(frozen=True, slots=True)
class ExportDeliveryRequest:
    operation_id: str
    asset_version_id: str
    project_id: str
    actor_id: str
    chapter: int
    trace_id: str
    correlation_id: str


@dataclass(frozen=True, slots=True)
class ExportDeliveryEvidence:
    blob_id: str
    external_effect_id: str
    dispatch_id: str
    retry_blocked_before_reconciliation: bool
    stale_fencing_rejected: bool
    reconciliation_outcome: str
    duplicate_receipt_replayed: bool


def deliver_export(
    database_url: str,
    *,
    request: ExportDeliveryRequest,
    adapter: ExternalEffectAdapter,
    exercise_unknown_reconciliation: bool,
) -> ExportDeliveryEvidence:
    content = _asset_version_content(database_url, request.asset_version_id)
    rendered = str(content["rendered_text"]).encode("utf-8")
    expected_hash = "sha256:" + hashlib.sha256(rendered).hexdigest()
    # INVARIANT: an immutable export asset separates Books and runs that share
    # a project/chapter number; recovery below preserves already frozen keys.
    object_key = f"chapters/{request.project_id}/{request.chapter}/versions/{request.asset_version_id}/chapter.txt"
    asset_context = AssetCommandContext(
        operation_id=request.operation_id,
        project_id=request.project_id,
        actor_id=request.actor_id,
        trace_id=request.trace_id,
        correlation_id=request.correlation_id,
        causation_id=request.operation_id,
    )
    retained = _retained_export_blob(database_url, request, provider=adapter.provider,
                                     expected_hash=expected_hash, expected_size=len(rendered))
    if retained is not None:
        blob_id, object_key = retained
    else:
        blob_id = reserve_blob(
            database_url,
            asset_context,
            provider=adapter.provider,
            object_key=object_key,
            expected_hash=expected_hash,
            expected_size=len(rendered),
            media_type="text/plain",
            stable_identity=f"chapter-export:{request.operation_id}:{request.asset_version_id}",
        )
    effect_id = request_blob_upload(
        database_url,
        asset_context,
        blob_id=blob_id,
        content_base64=base64.b64encode(rendered).decode("ascii"),
        source_asset_version_id=request.asset_version_id,
    )["external_effect_id"]
    effect_context = EffectCommandContext(
        operation_id=request.operation_id,
        project_id=request.project_id,
        actor_id=request.actor_id,
        trace_id=request.trace_id,
        correlation_id=request.correlation_id,
        causation_id=request.operation_id,
    )
    if exercise_unknown_reconciliation:
        evidence = _exercise_unknown_delivery(
            database_url,
            request=request,
            adapter=adapter,
            effect_context=effect_context,
            blob_id=blob_id,
            effect_id=effect_id,
            object_key=object_key,
            expected_hash=expected_hash,
            expected_size=len(rendered),
        )
    else:
        evidence = _deliver_synchronously(
            database_url,
            adapter=adapter,
            asset_context=asset_context,
            effect_context=effect_context,
            blob_id=blob_id,
            effect_id=effect_id,
            asset_version_id=request.asset_version_id,
        )
    if exercise_unknown_reconciliation:
        verify_blob(database_url, asset_context, blob_id=blob_id)
        bind_blob_to_asset_version(
            database_url,
            asset_context,
            asset_version_id=request.asset_version_id,
            blob_id=blob_id,
            role="content",
            ordinal=0,
        )
    return evidence


def _retained_export_blob(database_url: str, request: ExportDeliveryRequest, *, provider: str,
                          expected_hash: str, expected_size: int) -> tuple[str, str] | None:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("""SELECT DISTINCT b.blob_id,b.object_key,b.provider,b.expected_hash,b.expected_size,
                   effect.request_payload->>'source_asset_version_id'
            FROM authority_blob b JOIN state_event event ON event.aggregate_id=b.blob_id
             AND event.aggregate_type='authority_blob' AND event.event_type='blob.reserved'
             AND event.project_id=b.project_id
            LEFT JOIN authority_external_effect effect ON effect.external_effect_id=b.upload_effect_id
            WHERE b.project_id=%s AND event.payload->>'operation_id'=%s""",
            [request.project_id, request.operation_id])
        rows = uow.cursor.fetchall()
    if not rows:
        return None
    if len(rows) != 1 or tuple(rows[0][2:5]) != (provider, expected_hash, expected_size) or rows[0][5] not in (None, "", request.asset_version_id):
        raise KernelError("CHAPTER_EXPORT_RESERVATION_DRIFT", "Export recovery differs from its original Blob reservation")
    return str(rows[0][0]), str(rows[0][1])


def _deliver_synchronously(
    database_url: str,
    *,
    adapter: ExternalEffectAdapter,
    asset_context: AssetCommandContext,
    effect_context: EffectCommandContext,
    blob_id: str,
    effect_id: str,
    asset_version_id: str,
) -> ExportDeliveryEvidence:
    dispatched = _retained_delivery_receipt(
        database_url, effect_context, effect_id=effect_id
    )
    if dispatched is None:
        with AuthorityUnitOfWork(database_url) as uow:
            effect = uow.repositories.external_effects.get_for_update(effect_id)
        if effect["status"] in {"UNKNOWN", "RECONCILIATION_REQUIRED"}:
            reconcile_external_effect(database_url, effect_context, effect_id=effect_id, adapter=adapter)
            dispatched = _retained_delivery_receipt(database_url, effect_context, effect_id=effect_id)
    if dispatched is None:
        dispatched = dispatch_external_effect(
            database_url,
            effect_context,
            effect_id=effect_id,
            worker_id="chapter-export-effect-worker",
            lease_seconds=30,
            adapter=adapter,
        )
    if dispatched["outcome"] != "success" or dispatched["receipt"] is None:
        raise KernelError(
            "CHAPTER_EXPORT_DELIVERY_INCOMPLETE",
            "Export adapter did not produce a synchronous verified receipt",
        )
    with AuthorityUnitOfWork(database_url) as uow:
        blob = uow.repositories.asset_blobs.blob_for_update(blob_id)
        uow.cursor.execute("""SELECT blob_id FROM authority_asset_version_blob_reference
            WHERE asset_version_id=%s AND role='content' AND ordinal=0""", [asset_version_id])
        bound = uow.cursor.fetchone()
    if blob["status"] != "AVAILABLE":
        verify_blob(database_url, asset_context, blob_id=blob_id)
    if bound is not None and bound[0] != blob_id:
        raise KernelError("CHAPTER_EXPORT_RESERVATION_DRIFT", "Export is bound to another Blob")
    if bound is None:
        bind_blob_to_asset_version(
            database_url, asset_context, asset_version_id=asset_version_id,
            blob_id=blob_id, role="content", ordinal=0,
        )
    return ExportDeliveryEvidence(
        blob_id=blob_id,
        external_effect_id=effect_id,
        dispatch_id=str(dispatched["dispatch_id"]),
        retry_blocked_before_reconciliation=False,
        stale_fencing_rejected=False,
        reconciliation_outcome="not_exercised",
        duplicate_receipt_replayed=bool(dispatched.get("replayed")),
    )


def _retained_delivery_receipt(database_url: str, context: EffectCommandContext, *, effect_id: str) -> dict[str, Any] | None:
    with AuthorityUnitOfWork(database_url) as uow:
        effect = uow.repositories.external_effects.get_for_update(effect_id)
        if (effect["project_id"], effect["operation_id"], effect["effect_type"]) != (context.project_id, context.operation_id, "blob.upload"):
            raise KernelError("CHAPTER_EXPORT_RESERVATION_DRIFT", "Export Effect belongs to another scope")
        if effect["status"] != "SUCCEEDED":
            return None
        uow.cursor.execute("""SELECT d.dispatch_id,d.evidence,r.payload_hash,r.payload
            FROM authority_external_effect_dispatch d JOIN authority_external_receipt r USING(dispatch_id)
            WHERE d.external_effect_id=%s AND d.status='SUCCEEDED' AND r.status='VERIFIED'
            ORDER BY d.generation DESC LIMIT 1""", [effect_id])
        row = uow.cursor.fetchone()
    evidence = row[3].get("evidence") if row is not None else None
    if (
        not isinstance(evidence, dict) or not evidence
        or _json_hash(evidence) != row[2]
        or any(row[1].get(key) != value for key, value in evidence.items())
        or any(evidence.get(actual) != effect["request_payload"].get(expected)
               for actual, expected in (("object_key", "object_key"), ("actual_hash", "expected_hash"), ("actual_size", "expected_size")))
    ):
        raise KernelError("EFFECT_SUCCESS_RECEIPT_INVALID", "Export success lacks an intact verified receipt")
    return {"dispatch_id": row[0], "outcome": "success", "receipt": row[3], "replayed": True}


def _exercise_unknown_delivery(
    database_url: str,
    *,
    request: ExportDeliveryRequest,
    adapter: ExternalEffectAdapter,
    effect_context: EffectCommandContext,
    blob_id: str,
    effect_id: str,
    object_key: str,
    expected_hash: str,
    expected_size: int,
) -> ExportDeliveryEvidence:
    assert_legacy_execution_allowed(
        component="Chapter export adapter",
        gateway_backed=bool(
            getattr(adapter, "production_execution_gateway_backed", False)
        ),
    )
    dispatch = prepare_effect_dispatch(database_url, effect_context, effect_id=effect_id)
    lease = acquire_effect_dispatch(
        database_url,
        effect_context,
        dispatch_id=dispatch["dispatch_id"],
        worker_id="chapter-export-effect-worker",
        lease_seconds=30,
    )
    provider_result = adapter.execute(
        stable_idempotency_key=f"blob.upload:{request.project_id}:{blob_id}",
        capability="object_store.put",
        request_payload={
            "blob_id": blob_id,
            "project_id": request.project_id,
            "provider": adapter.provider,
            "object_key": object_key,
            "expected_hash": expected_hash,
            "expected_size": expected_size,
            "media_type": "text/plain",
        },
    )
    if provider_result.outcome != "unknown":
        raise KernelError(
            "CHAPTER_EXPORT_FIXTURE_INVALID",
            "acceptance adapter must inject one post-send UNKNOWN result",
        )
    submit_effect_dispatch_result(
        database_url,
        effect_context,
        dispatch_id=dispatch["dispatch_id"],
        worker_id="chapter-export-effect-worker",
        fencing_token=lease["fencing_token"],
        outcome="unknown",
        evidence=provider_result.evidence,
        provider_correlation_id=provider_result.provider_correlation_id,
    )
    stale_rejected = _stale_result_is_rejected(
        database_url,
        effect_context,
        dispatch_id=dispatch["dispatch_id"],
        fencing_token=lease["fencing_token"],
    )
    retry_blocked = _blind_retry_is_blocked(database_url, effect_context, effect_id)
    reconciliation = reconcile_external_effect(
        database_url,
        effect_context,
        effect_id=effect_id,
        adapter=adapter,
    )
    receipt_evidence = {
        "object_key": object_key,
        "actual_hash": expected_hash,
        "actual_size": expected_size,
        "reconciled_after_unknown": True,
    }
    receipt_hash = _json_hash(receipt_evidence)
    message_id = f"chapter-export-receipt:{effect_id}:1"
    receipt_arguments = {
        "dispatch_id": dispatch["dispatch_id"],
        "provider": adapter.provider,
        "receipt_id": f"receipt:{effect_id}:1",
        "message_id": message_id,
        "payload_hash": receipt_hash,
        "provider_correlation_id": provider_result.provider_correlation_id,
        "generation": dispatch["generation"],
        "outcome": "success",
        "evidence": receipt_evidence,
    }
    first_receipt = accept_external_effect_receipt(
        database_url,
        effect_context,
        **receipt_arguments,
    )
    duplicate_receipt = accept_external_effect_receipt(
        database_url,
        effect_context,
        **receipt_arguments,
    )
    if first_receipt["replayed"] or not duplicate_receipt["replayed"]:
        raise KernelError("CHAPTER_RECEIPT_REPLAY_INVALID", "receipt replay contract failed")
    return ExportDeliveryEvidence(
        blob_id=blob_id,
        external_effect_id=effect_id,
        dispatch_id=dispatch["dispatch_id"],
        retry_blocked_before_reconciliation=retry_blocked,
        stale_fencing_rejected=stale_rejected,
        reconciliation_outcome=reconciliation["outcome"],
        duplicate_receipt_replayed=duplicate_receipt["replayed"],
    )


def _stale_result_is_rejected(
    database_url: str,
    context: EffectCommandContext,
    *,
    dispatch_id: str,
    fencing_token: int,
) -> bool:
    try:
        submit_effect_dispatch_result(
            database_url,
            context,
            dispatch_id=dispatch_id,
            worker_id="chapter-export-effect-worker",
            fencing_token=fencing_token,
            outcome="success",
            evidence={"late": True},
        )
    except KernelError as exc:
        return exc.code == "EFFECT_FENCING_TOKEN_STALE"
    return False


def _blind_retry_is_blocked(
    database_url: str,
    context: EffectCommandContext,
    effect_id: str,
) -> bool:
    try:
        prepare_effect_dispatch(database_url, context, effect_id=effect_id)
    except KernelError as exc:
        return exc.code == "EFFECT_RECONCILIATION_REQUIRED"
    return False


def _asset_version_content(database_url: str, asset_version_id: str) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            "SELECT content FROM authority_asset_version WHERE asset_version_id = %s",
            [asset_version_id],
        )
        row = uow.cursor.fetchone()
    if row is None:
        raise KernelError("ASSET_VERSION_NOT_FOUND", "Export AssetVersion disappeared")
    return dict(row[0])


def _json_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
