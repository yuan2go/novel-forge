from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.authority_handler_runtime.policy_commands import (
    configure_owned_policy,
    owned_policy_definition,
)
from novel_forge.modules.command_kernel.service import TransactionCheckpoint
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.versioned_policy_repository import VersionedPolicyRepository


EXECUTION_POLICY_OWNER = "CHAPTER_GROUP_EXECUTION"


@dataclass(frozen=True, slots=True)
class ChapterGroupExecutionPolicy:
    policy_version: str = "chapter-group-execution-v1"
    maximum_chapters: int = 8
    preferred_chapters: int = 4

    def __post_init__(self) -> None:
        if (
            not self.policy_version.strip()
            or type(self.maximum_chapters) is not int
            or type(self.preferred_chapters) is not int
            or not 0 < self.preferred_chapters <= self.maximum_chapters
        ):
            raise ValueError("ChapterGroup execution policy requires positive limits")


def chapter_group_execution_policy_definitions(
    *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    return owned_policy_definition(
        owner=EXECUTION_POLICY_OWNER,
        content=asdict(ChapterGroupExecutionPolicy()),
        application_build_id=application_build_id,
        commit_sha=commit_sha,
    )


class PostgresChapterGroupExecutionPolicyAuthority:
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
        policy: ChapterGroupExecutionPolicy,
        principal: Principal,
        workspace_id: str,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
        fault_injector: TransactionCheckpoint | None = None,
    ) -> dict[str, Any]:
        return configure_owned_policy(
            database_url=self.database_url,
            owner=EXECUTION_POLICY_OWNER,
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

    def freeze_for_book(
        self, *, project_id: str, book_run_id: str, actor_id: str
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                "SELECT 1 FROM authority_book_production WHERE book_run_id=%s AND project_id=%s",
                [book_run_id, project_id],
            )
            if uow.cursor.fetchone() is None:
                raise ValueError("execution policy binding requires an owned Book run")
            snapshot = VersionedPolicyRepository(
                uow.cursor, owner=EXECUTION_POLICY_OWNER, project_id=project_id
            ).freeze(
                subject_id=book_run_id,
                default=asdict(ChapterGroupExecutionPolicy()),
                actor_id=actor_id,
            )
            uow.commit()
        ChapterGroupExecutionPolicy(**snapshot["policy"])
        return snapshot
