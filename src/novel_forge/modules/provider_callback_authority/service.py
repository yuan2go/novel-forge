from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Mapping
from uuid import uuid4

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    accept_external_effect_receipt,
    resolve_external_effect_receipt_budget,
)
from novel_forge.modules.provider_control import ProviderAdapterRegistry, ProviderReceipt
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


@dataclass(frozen=True, slots=True)
class ProviderCallbackAcceptCommand:
    provider: str
    provider_message_id: str
    body: bytes
    headers: Mapping[str, str]
    signature_secret: str
    actor_id: str
    worker_id: str
    trace_id: str
    correlation_id: str

    def __post_init__(self) -> None:
        if not all(
            (
                self.provider,
                self.provider_message_id,
                self.body,
                self.signature_secret,
                self.actor_id,
                self.worker_id,
                self.trace_id,
                self.correlation_id,
            )
        ):
            raise ValueError("provider callback command is incomplete")


class ProviderCallbackAuthorityService:
    """Durable callback ingress bound to an existing ExternalEffect authority."""

    def __init__(self, database_url: str, registry: ProviderAdapterRegistry) -> None:
        if not database_url:
            raise ValueError("callback authority requires PostgreSQL")
        self.database_url = database_url
        self.registry = registry

    def accept(self, command: ProviderCallbackAcceptCommand) -> dict[str, object]:
        provider = command.provider.strip().lower()
        adapter = self.registry.resolve(provider)
        verifier = getattr(adapter, "verify_callback", None)
        if verifier is None or not adapter.capability_profile.supports_callback:
            raise KernelError(
                "PROVIDER_CALLBACK_UNSUPPORTED",
                "provider route does not declare durable callback verification",
            )
        payload_hash = "sha256:" + hashlib.sha256(command.body).hexdigest()
        try:
            receipt = verifier(
                command.body,
                command.headers,
                secret=command.signature_secret,
            )
        except Exception as exc:
            self._quarantine(command, provider, payload_hash, type(exc).__name__)
            raise KernelError(
                "PROVIDER_CALLBACK_SIGNATURE_INVALID",
                "provider callback signature verification failed",
            ) from exc
        if receipt.message_id != command.provider_message_id:
            self._quarantine(command, provider, payload_hash, "MESSAGE_ID_MISMATCH")
            raise KernelError(
                "PROVIDER_CALLBACK_MESSAGE_CONFLICT",
                "verified provider message ID differs from the ingress identity",
            )
        if receipt.payload_hash != payload_hash:
            raise KernelError(
                "PROVIDER_CALLBACK_HASH_CONFLICT",
                "verified callback payload hash differs from the ingress body",
            )
        binding = self._bind_and_record(command, provider, receipt)
        if binding["disposition"] == "REPLAY" and binding["processing_status"] == "PROCESSED":
            return {**binding, "replayed": True}
        if binding["disposition"] == "CONFLICT":
            raise KernelError(
                "PROVIDER_CALLBACK_PAYLOAD_CONFLICT",
                "provider message ID was reused with a different callback",
            )
        callback_receipt_id = str(binding["callback_receipt_id"])
        project_id = str(binding["project_id"])
        operation_id = str(binding["operation_id"])
        attempt_id = str(uuid4())
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.provider_callbacks.begin_attempt(
                callback_receipt_id, project_id, command.worker_id, attempt_id
            )
            uow.commit()
        context = EffectCommandContext(
            operation_id=operation_id,
            project_id=project_id,
            actor_id=command.actor_id,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            causation_id=callback_receipt_id,
        )
        try:
            accepted = accept_external_effect_receipt(
                self.database_url,
                context,
                dispatch_id=str(binding["dispatch_id"]),
                provider=str(binding["provider"]),
                receipt_id=receipt.receipt_id,
                message_id=receipt.message_id,
                payload_hash=receipt.payload_hash,
                provider_correlation_id=receipt.provider_request_id,
                generation=int(binding["generation"]),
                outcome=receipt.outcome,
                evidence=dict(receipt.evidence),
            )
            resolve_external_effect_receipt_budget(
                self.database_url,
                project_id=project_id,
                effect_id=str(binding["external_effect_id"]),
                outcome=receipt.outcome,
                evidence=dict(receipt.evidence),
            )
        except KernelError as exc:
            self._finish(
                callback_receipt_id,
                project_id,
                attempt_id,
                "FAILED_FINAL" if "CONFLICT" in exc.code else "FAILED_RETRYABLE",
                exc.code,
                str(exc),
            )
            raise
        self._finish(callback_receipt_id, project_id, attempt_id, "PROCESSED", "", "")
        return {
            **binding,
            "processing_status": "PROCESSED",
            "effect_receipt_replayed": bool(accepted.get("replayed")),
            "replayed": False,
        }

    def _bind_and_record(
        self,
        command: ProviderCallbackAcceptCommand,
        provider: str,
        receipt: ProviderReceipt,
    ) -> dict[str, object]:
        callback_receipt_id = str(uuid4())
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = uow.repositories.provider_callbacks
            binding = repository.effect_binding_for_update(
                provider, receipt.provider_request_id
            )
            if binding is None:
                disposition, stored = repository.record_receipt(
                    self._row(
                        command,
                        provider,
                        receipt,
                        callback_receipt_id,
                        binding=None,
                        processing_status="QUARANTINED",
                    )
                )
                uow.commit()
                raise KernelError(
                    "PROVIDER_CALLBACK_EFFECT_UNKNOWN",
                    "verified callback does not match a provider request",
                )
            disposition, stored = repository.record_receipt(
                self._row(
                    command,
                    provider,
                    receipt,
                    callback_receipt_id,
                    binding=binding,
                    processing_status="PENDING",
                )
            )
            if disposition == "CONFLICT":
                uow.cursor.execute(
                    "UPDATE authority_provider_callback_receipt SET processing_status='CONFLICTED', updated_at=NOW() WHERE callback_receipt_id=%s",
                    [stored["callback_receipt_id"]],
                )
            if disposition == "INSERTED":
                self._record_event(
                    uow,
                    binding,
                    command,
                    "provider.callback.accepted",
                    {"callback_receipt_id": callback_receipt_id, "provider_message_id": receipt.message_id},
                )
            uow.commit()
        return {
            **binding,
            **stored,
            "callback_receipt_id": stored.get("callback_receipt_id", callback_receipt_id),
            "disposition": disposition,
        }

    def _quarantine(
        self,
        command: ProviderCallbackAcceptCommand,
        provider: str,
        payload_hash: str,
        reason: str,
    ) -> None:
        receipt = ProviderReceipt(
            provider_request_id="unverified",
            receipt_id=command.provider_message_id,
            message_id=command.provider_message_id,
            outcome="final_failure",
            payload_hash=payload_hash,
            evidence={"quarantine_reason": reason},
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.provider_callbacks.record_receipt(
                self._row(
                    command,
                    provider,
                    receipt,
                    str(uuid4()),
                    binding=None,
                    processing_status="QUARANTINED",
                    signature_status="REJECTED",
                )
            )
            uow.commit()

    @staticmethod
    def _row(
        command: ProviderCallbackAcceptCommand,
        provider: str,
        receipt: ProviderReceipt,
        callback_receipt_id: str,
        *,
        binding: dict[str, object] | None,
        processing_status: str,
        signature_status: str = "VERIFIED",
    ) -> dict[str, object]:
        safe_headers = {
            key.lower(): value
            for key, value in command.headers.items()
            if key.lower() not in {"authorization", "x-api-key", "webhook-signature"}
        }
        return {
            "callback_receipt_id": callback_receipt_id,
            "project_id": None if binding is None else binding["project_id"],
            "provider": provider,
            "provider_request_id": receipt.provider_request_id,
            "provider_message_id": receipt.message_id,
            "external_effect_id": None if binding is None else binding["external_effect_id"],
            "dispatch_id": None if binding is None else binding["dispatch_id"],
            "payload_hash": receipt.payload_hash,
            "signature_status": signature_status,
            "outcome": receipt.outcome,
            "raw_metadata": {"headers": safe_headers, "body_size": len(command.body)},
            "normalized_receipt": asdict(receipt),
            "processing_status": processing_status,
            "trace_id": command.trace_id,
            "correlation_id": command.correlation_id,
        }

    def _finish(
        self,
        callback_receipt_id: str,
        project_id: str,
        attempt_id: str,
        status: str,
        error_code: str,
        detail: str,
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.provider_callbacks.finish_attempt(
                callback_receipt_id,
                project_id,
                attempt_id,
                status=status,
                error_code=error_code,
                error_detail=detail[:2000],
            )
            uow.commit()

    @staticmethod
    def _record_event(
        uow: AuthorityUnitOfWork,
        binding: dict[str, object],
        command: ProviderCallbackAcceptCommand,
        event_type: str,
        payload: dict[str, object],
    ) -> None:
        uow.repositories.external_effects.record_event(
            {
                "event_id": str(uuid4()), "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()), "aggregate_type": "authority_external_effect",
                "aggregate_id": binding["external_effect_id"],
                "operation_id": binding["operation_id"], "project_id": binding["project_id"],
                "event_type": event_type, "correlation_id": command.correlation_id,
                "causation_id": binding["external_effect_id"],
                "payload": {**payload, "actor_id": command.actor_id, "trace_id": command.trace_id},
            }
        )


__all__ = ["ProviderCallbackAcceptCommand", "ProviderCallbackAuthorityService"]
