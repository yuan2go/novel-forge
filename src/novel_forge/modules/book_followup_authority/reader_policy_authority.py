from __future__ import annotations

from dataclasses import asdict
from typing import Any

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.authority_handler_runtime.policy_commands import (
    configure_owned_policy,
    owned_policy_definition,
)
from novel_forge.modules.command_kernel.service import TransactionCheckpoint
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.versioned_policy_repository import VersionedPolicyRepository

from .reader_policy import READER_POLICY_OWNER, ReaderProxyPolicy, policy_from_snapshot


def reader_proxy_policy_definitions(
    *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    return owned_policy_definition(
        owner=READER_POLICY_OWNER,
        content=asdict(ReaderProxyPolicy()),
        application_build_id=application_build_id,
        commit_sha=commit_sha,
    )


class PostgresReaderProxyPolicyAuthority:
    def __init__(
        self, database_url: str, *, application_build_id: str, commit_sha: str
    ) -> None:
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha

    def configure(
        self,
        *,
        project_id: str,
        policy: ReaderProxyPolicy,
        principal: Principal,
        workspace_id: str,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
        fault_injector: TransactionCheckpoint | None = None,
    ) -> dict[str, Any]:
        return configure_owned_policy(
            database_url=self.database_url,
            owner=READER_POLICY_OWNER,
            content=asdict(policy),
            project_id=project_id,
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            correlation_id=correlation_id,
            principal=principal,
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
            fault_injector=fault_injector,
        )

    def freeze_for_admission(
        self, *, project_id: str, idempotency_key: str, actor_id: str
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            snapshot = VersionedPolicyRepository(
                uow.cursor, owner=READER_POLICY_OWNER, project_id=project_id
            ).freeze(
                subject_id=idempotency_key,
                default=asdict(ReaderProxyPolicy()),
                actor_id=actor_id,
            )
            uow.commit()
        policy_from_snapshot(snapshot)
        return snapshot
