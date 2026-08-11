"""Authoritative Asset and Blob command handlers backed by short PostgreSQL transactions."""
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import psycopg

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    accept_external_effect_receipt,
    mark_external_effect_unknown,
    prepare_effect_dispatch,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


@dataclass(frozen=True)
class AssetCommandContext:
    operation_id: str
    project_id: str
    actor_id: str
    trace_id: str
    correlation_id: str
    causation_id: str = ""


def create_asset(
    database_url: str,
    context: AssetCommandContext,
    *,
    asset_type: str,
) -> str:
    if not asset_type:
        raise KernelError("COMMAND_SCHEMA_INVALID", "asset type is required")
    asset_id = str(uuid4())
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.asset_blobs
        _require_context(repository, context)
        repository.create_asset(asset_id, context.project_id, asset_type)
        _record(repository, context, "authority_asset", asset_id, "asset.created", {})
        uow.commit()
    return asset_id


def create_asset_version(
    database_url: str,
    context: AssetCommandContext,
    *,
    asset_id: str,
    content: dict[str, Any],
    content_hash: str,
    schema_version: str,
) -> str:
    if not content_hash or not isinstance(content, dict) or not schema_version:
        raise KernelError(
            "COMMAND_SCHEMA_INVALID",
            "asset content, hash, and schema version are required",
        )
    version_id = str(uuid4())
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.asset_blobs
        _require_context(repository, context)
        repository.asset_for_update(asset_id, context.project_id)
        version_number = repository.next_version_number(asset_id)
        repository.create_version(
            {
                "asset_version_id": version_id,
                "asset_id": asset_id,
                "version_number": version_number,
                "content": content,
                "content_hash": content_hash,
                "schema_version": schema_version,
            }
        )
        _record(
            repository,
            context,
            "authority_asset_version",
            version_id,
            "asset.version.created",
            {"asset_id": asset_id, "version_number": version_number},
        )
        uow.commit()
    return version_id


def qualify_asset_version(
    database_url: str,
    context: AssetCommandContext,
    *,
    asset_version_id: str,
    decision: str,
    policy_version: str,
    evidence: dict[str, Any],
) -> str:
    if decision not in {"ELIGIBLE", "INELIGIBLE", "REVOKED"}:
        raise KernelError("ASSET_QUALIFICATION_INVALID", "unknown qualification decision")
    qualification_id = str(uuid4())
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.asset_blobs
        _require_context(repository, context)
        version = repository.version_for_update(asset_version_id)
        _require_project(version, context.project_id, "asset version")
        repository.qualify_version(
            qualification_id,
            asset_version_id,
            policy_version,
            decision,
            evidence,
        )
        _record(
            repository,
            context,
            "authority_asset_version",
            asset_version_id,
            "asset.version.qualified",
            {
                "qualification_id": qualification_id,
                "decision": decision,
                "policy_version": policy_version,
            },
        )
        uow.commit()
    return qualification_id


def activate_asset_version(
    database_url: str,
    context: AssetCommandContext,
    *,
    asset_version_id: str,
) -> None:
    try:
        with AuthorityUnitOfWork(database_url) as uow:
            repository = uow.repositories.asset_blobs
            _require_context(repository, context)
            version = repository.version_for_update(asset_version_id)
            _require_project(version, context.project_id, "asset version")
            repository.asset_for_update(version["asset_id"], context.project_id)
            active = repository.active_version(version["asset_id"])
            if active and active != asset_version_id:
                raise KernelError(
                    "ASSET_ACTIVE_VERSION_CONFLICT",
                    "asset already has another active version",
                )
            repository.activate_version(asset_version_id)
            _record(
                repository,
                context,
                "authority_asset_version",
                asset_version_id,
                "asset.version.activated",
                {"asset_id": version["asset_id"]},
            )
            uow.commit()
    except psycopg.errors.UniqueViolation as exc:
        raise KernelError(
            "ASSET_ACTIVE_VERSION_CONFLICT",
            "asset already has another active version",
        ) from exc


def bind_operation_output_asset(
    database_url: str,
    context: AssetCommandContext,
    *,
    asset_version_id: str,
    output_key: str,
    role: str,
) -> dict[str, Any]:
    if not output_key or not role:
        raise KernelError("COMMAND_SCHEMA_INVALID", "output key and role are required")
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.asset_blobs
        _require_context(repository, context)
        version = repository.version_for_update(asset_version_id)
        _require_project(version, context.project_id, "asset version")
        created = repository.bind_operation_output(
            operation_id=context.operation_id,
            asset_id=version["asset_id"],
            asset_version_id=asset_version_id,
            output_key=output_key,
            role=role,
            content_hash=version["content_hash"],
        )
        if created:
            _record(
                repository,
                context,
                "authority_operation",
                context.operation_id,
                "operation.output_asset.bound",
                {
                    "asset_id": version["asset_id"],
                    "asset_version_id": asset_version_id,
                    "output_key": output_key,
                    "role": role,
                    "content_hash": version["content_hash"],
                },
            )
        uow.commit()
    return {
        "operation_id": context.operation_id,
        "asset_version_id": asset_version_id,
        "output_key": output_key,
        "role": role,
        "replayed": not created,
    }


def reserve_blob(
    database_url: str,
    context: AssetCommandContext,
    *,
    provider: str,
    object_key: str,
    expected_hash: str,
    expected_size: int,
    media_type: str,
    retention_class: str = "STANDARD",
    encryption_metadata: dict[str, Any] | None = None,
    stable_identity: str = "",
) -> str:
    if not all((provider, object_key, expected_hash, media_type)) or expected_size < 0:
        raise KernelError("COMMAND_SCHEMA_INVALID", "blob reservation is incomplete")
    if retention_class not in {"EPHEMERAL", "STANDARD", "LONG_TERM", "LEGAL_HOLD"}:
        raise KernelError("COMMAND_SCHEMA_INVALID", "unsupported Blob retention_class")
    if stable_identity and len(stable_identity) > 512:
        raise KernelError(
            "COMMAND_SCHEMA_INVALID", "Blob stable_identity exceeds the limit"
        )
    blob_id = str(
        uuid5(
            NAMESPACE_URL,
            f"novel-forge:blob:{context.project_id}:{stable_identity}",
        )
        if stable_identity
        else uuid4()
    )
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.asset_blobs
        _require_context(repository, context)
        created = repository.reserve_blob(
            {
                "blob_id": blob_id,
                "project_id": context.project_id,
                "provider": provider,
                "object_key": object_key,
                "expected_hash": expected_hash,
                "expected_size": expected_size,
                "media_type": media_type,
                "retention_class": retention_class,
                "encryption_metadata": dict(encryption_metadata or {}),
            }
        )
        if created:
            _record(
                repository,
                context,
                "authority_blob",
                blob_id,
                "blob.reserved",
                {
                    "provider": provider,
                    "object_key": object_key,
                    "retention_class": retention_class,
                    "encryption_metadata": dict(encryption_metadata or {}),
                    "stable_identity": bool(stable_identity),
                },
            )
        else:
            existing = repository.blob_for_update(blob_id)
            expected = {
                "project_id": context.project_id,
                "provider": provider,
                "object_key": object_key,
                "expected_hash": expected_hash,
                "expected_size": expected_size,
                "media_type": media_type,
                "retention_class": retention_class,
            }
            if any(existing[key] != value for key, value in expected.items()):
                raise KernelError(
                    "BLOB_STABLE_IDENTITY_CONFLICT",
                    "Blob stable identity is already frozen to different content",
                )
        uow.commit()
    return blob_id


def request_blob_upload(
    database_url: str,
    context: AssetCommandContext,
    *,
    blob_id: str,
    content_base64: str = "",
    source_asset_version_id: str = "",
) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.asset_blobs
        _require_context(repository, context)
        blob = repository.blob_for_update(blob_id)
        _require_project(blob, context.project_id, "blob")
        request_payload = {
            "blob_id": blob_id,
            "project_id": context.project_id,
            "provider": blob["provider"],
            "object_key": blob["object_key"],
            "expected_hash": blob["expected_hash"],
            "expected_size": blob["expected_size"],
            "media_type": blob["media_type"],
        }
        if content_base64:
            try:
                content_bytes = base64.b64decode(content_base64, validate=True)
            except (ValueError, TypeError) as exc:
                raise KernelError(
                    "BLOB_UPLOAD_CONTENT_INVALID",
                    "Blob upload content is not valid base64",
                ) from exc
            actual_hash = "sha256:" + hashlib.sha256(content_bytes).hexdigest()
            if actual_hash != blob["expected_hash"] or len(content_bytes) != blob["expected_size"]:
                raise KernelError(
                    "BLOB_UPLOAD_CONTENT_MISMATCH",
                    "Blob upload content does not match the reservation",
                )
            request_payload["content_base64"] = content_base64
            request_payload["source_asset_version_id"] = source_asset_version_id
        result = uow.repositories.external_effects.plan(
            {
                "external_effect_id": str(uuid4()),
                "operation_id": context.operation_id,
                "project_id": context.project_id,
                "effect_type": "blob.upload",
                "stable_idempotency_key": f"blob.upload:{context.project_id}:{blob_id}",
                "request_hash": _hash(request_payload),
                "request_payload": request_payload,
                "provider": blob["provider"],
                "capability": "object_store.put",
                "max_attempts": 3,
                "reversible": False,
                "completion_policy": "synchronous_final",
                "compensates_effect_id": None,
            }
        )
        repository.attach_upload_effect(blob_id, result["external_effect_id"])
        if not result["replayed"]:
            _record(
                repository,
                context,
                "authority_external_effect",
                result["external_effect_id"],
                "blob.upload.requested",
                request_payload,
            )
        uow.commit()
    return result


def begin_blob_upload_dispatch(
    database_url: str,
    context: AssetCommandContext,
    *,
    external_effect_id: str,
    provider: str,
) -> dict[str, Any]:
    """Deprecated compatibility entry point backed by the generic dispatcher."""
    with AuthorityUnitOfWork(database_url) as uow:
        effect = uow.repositories.external_effects.get_for_update(external_effect_id)
        _require_project(effect, context.project_id, "external effect")
        if effect["effect_type"] != "blob.upload":
            raise KernelError("EFFECT_TYPE_INVALID", "effect is not a Blob upload")
        if provider != effect["provider"]:
            raise KernelError(
                "EFFECT_PROVIDER_CONFLICT",
                "dispatch provider differs from the frozen Blob effect",
            )
    return prepare_effect_dispatch(
        database_url,
        _effect_context(context),
        effect_id=external_effect_id,
    )


def accept_blob_upload_receipt(
    database_url: str,
    context: AssetCommandContext,
    *,
    dispatch_id: str,
    provider: str,
    receipt_id: str,
    object_key: str,
    actual_hash: str,
    actual_size: int,
    payload_hash: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Deprecated receipt shape translated into the generic receipt inbox."""
    if actual_size < 0:
        raise KernelError("COMMAND_SCHEMA_INVALID", "receipt size cannot be negative")
    with AuthorityUnitOfWork(database_url) as uow:
        _require_context(uow.repositories.asset_blobs, context)
        dispatch = uow.repositories.external_effects.dispatch_for_update(dispatch_id)
        _require_project(dispatch, context.project_id, "dispatch")
        if dispatch["provider"] != provider:
            raise KernelError(
                "RECEIPT_PROVIDER_CONFLICT",
                "receipt provider differs from dispatch provider",
            )
        generation = int(dispatch["generation"])
    return accept_external_effect_receipt(
        database_url,
        _effect_context(context),
        dispatch_id=dispatch_id,
        provider=provider,
        receipt_id=receipt_id,
        message_id=f"{provider}:{receipt_id}",
        payload_hash=payload_hash,
        provider_correlation_id=receipt_id,
        generation=generation,
        outcome="success",
        evidence={
            **evidence,
            "object_key": object_key,
            "actual_hash": actual_hash,
            "actual_size": actual_size,
        },
    )


def verify_blob(
    database_url: str,
    context: AssetCommandContext,
    *,
    blob_id: str,
) -> dict[str, Any]:
    mismatch_code = ""
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.asset_blobs
        _require_context(repository, context)
        blob = repository.blob_for_update(blob_id)
        _require_project(blob, context.project_id, "blob")
        if blob["status"] == "RECONCILIATION_REQUIRED":
            raise KernelError(
                "BLOB_RECONCILIATION_REQUIRED",
                "unknown upload outcome must be reconciled before verification",
            )
        if blob["status"] != "UPLOADED":
            raise KernelError("BLOB_STATUS_CONFLICT", "blob has no accepted upload receipt")
        if blob["receipt_provider"] != blob["provider"]:
            mismatch_code = "BLOB_PROVIDER_MISMATCH"
        elif blob["actual_object_key"] != blob["object_key"]:
            mismatch_code = "BLOB_OBJECT_KEY_MISMATCH"
        elif blob["actual_hash"] != blob["expected_hash"]:
            mismatch_code = "BLOB_HASH_MISMATCH"
        elif blob["actual_size"] != blob["expected_size"]:
            mismatch_code = "BLOB_SIZE_MISMATCH"
        target = "QUARANTINED" if mismatch_code else "AVAILABLE"
        repository.update_blob_status(blob_id, ("UPLOADED",), target)
        _record(
            repository,
            context,
            "authority_blob",
            blob_id,
            "blob.verification_failed" if mismatch_code else "blob.verified",
            {"status": target, "error_code": mismatch_code},
        )
        uow.commit()
    if mismatch_code:
        raise KernelError(mismatch_code, "Blob receipt does not match reservation")
    return {"blob_id": blob_id, "status": "AVAILABLE"}


def bind_blob_to_asset_version(
    database_url: str,
    context: AssetCommandContext,
    *,
    asset_version_id: str,
    blob_id: str,
    role: str,
    ordinal: int,
) -> str:
    reference_id = str(uuid4())
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.asset_blobs
        _require_context(repository, context)
        version = repository.version_for_update(asset_version_id)
        _require_project(version, context.project_id, "asset version")
        blob = repository.blob_for_update(blob_id)
        _require_project(blob, context.project_id, "blob")
        if blob["status"] != "AVAILABLE":
            raise KernelError("BLOB_NOT_AVAILABLE", "only an AVAILABLE Blob can be bound")
        repository.bind_blob(
            reference_id,
            asset_version_id,
            blob_id,
            role,
            ordinal,
            blob["media_type"],
            blob["actual_hash"],
        )
        _record(
            repository,
            context,
            "authority_asset_version",
            asset_version_id,
            "blob.bound_to_asset_version",
            {"reference_id": reference_id, "blob_id": blob_id, "role": role},
        )
        uow.commit()
    return reference_id


def apply_blob_legal_hold(
    database_url: str,
    context: AssetCommandContext,
    *,
    blob_id: str,
    reason: str,
) -> None:
    _set_blob_hold(database_url, context, blob_id=blob_id, reason=reason, enabled=True)


def release_blob_legal_hold(
    database_url: str,
    context: AssetCommandContext,
    *,
    blob_id: str,
    reason: str,
) -> None:
    _set_blob_hold(database_url, context, blob_id=blob_id, reason=reason, enabled=False)


def release_blob(
    database_url: str,
    context: AssetCommandContext,
    *,
    blob_id: str,
) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.asset_blobs
        _require_context(repository, context)
        blob = repository.blob_for_update(blob_id)
        _require_project(blob, context.project_id, "blob")
        if blob["legal_hold"]:
            raise KernelError("BLOB_LEGAL_HOLD", "Legal Hold blocks Blob release")
        if repository.reference_count(blob_id):
            raise KernelError("BLOB_REFERENCE_EXISTS", "Blob reference closure is not empty")
        request_payload = {
            "blob_id": blob_id,
            "project_id": context.project_id,
            "provider": blob["provider"],
            "object_key": blob["object_key"],
        }
        result = uow.repositories.external_effects.plan(
            {
                "external_effect_id": str(uuid4()),
                "operation_id": context.operation_id,
                "project_id": context.project_id,
                "effect_type": "blob.delete",
                "stable_idempotency_key": f"blob.delete:{context.project_id}:{blob_id}",
                "request_hash": _hash(request_payload),
                "request_payload": request_payload,
                "provider": blob["provider"],
                "capability": "object_store.delete",
                "max_attempts": 3,
                "reversible": False,
                "completion_policy": "synchronous_final",
                "compensates_effect_id": None,
            }
        )
        repository.update_blob_status(
            blob_id,
            ("PENDING_UPLOAD", "AVAILABLE", "FAILED", "ABANDONED", "QUARANTINED"),
            "DELETE_PENDING",
        )
        _record(
            repository,
            context,
            "authority_blob",
            blob_id,
            "blob.release_requested",
            {"external_effect_id": result["external_effect_id"]},
        )
        uow.commit()
    return result


def reconcile_blob_upload(
    database_url: str,
    context: AssetCommandContext,
    *,
    dispatch_id: str,
    outcome: str,
    evidence: dict[str, Any],
) -> None:
    if outcome != "UNKNOWN":
        raise KernelError(
            "RECONCILIATION_OUTCOME_INVALID",
            "Task 4 supports explicit UNKNOWN classification only",
        )
    mark_external_effect_unknown(
        database_url,
        _effect_context(context),
        dispatch_id=dispatch_id,
        evidence=evidence,
    )


def _set_blob_hold(
    database_url: str,
    context: AssetCommandContext,
    *,
    blob_id: str,
    reason: str,
    enabled: bool,
) -> None:
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.asset_blobs
        _require_context(repository, context)
        blob = repository.blob_for_update(blob_id)
        _require_project(blob, context.project_id, "blob")
        repository.set_legal_hold(blob_id, enabled)
        _record(
            repository,
            context,
            "authority_blob",
            blob_id,
            "blob.legal_hold.applied" if enabled else "blob.legal_hold.released",
            {"reason": reason},
        )
        uow.commit()


def _require_context(repository: Any, context: AssetCommandContext) -> None:
    required = (
        context.operation_id,
        context.project_id,
        context.actor_id,
        context.trace_id,
        context.correlation_id,
    )
    if any(not value for value in required):
        raise KernelError("COMMAND_SCHEMA_INVALID", "asset command context is incomplete")
    repository.require_executing_operation(context.operation_id, context.project_id)


def _effect_context(context: AssetCommandContext) -> EffectCommandContext:
    return EffectCommandContext(
        operation_id=context.operation_id,
        project_id=context.project_id,
        actor_id=context.actor_id,
        trace_id=context.trace_id,
        correlation_id=context.correlation_id,
        causation_id=context.causation_id,
    )


def _require_project(row: dict[str, Any], project_id: str, aggregate: str) -> None:
    if row["project_id"] != project_id:
        raise KernelError(
            "CROSS_PROJECT_REFERENCE",
            f"{aggregate} belongs to another project",
        )


def _record(
    repository: Any,
    context: AssetCommandContext,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    repository.record_event(
        {
            "event_id": str(uuid4()),
            "audit_id": str(uuid4()),
            "outbox_id": str(uuid4()),
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "operation_id": context.operation_id,
            "project_id": context.project_id,
            "event_type": event_type,
            "correlation_id": context.correlation_id,
            "causation_id": context.causation_id,
            "payload": {
                **payload,
                "actor_id": context.actor_id,
                "trace_id": context.trace_id,
                "operation_id": context.operation_id,
            },
        }
    )


def _hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
