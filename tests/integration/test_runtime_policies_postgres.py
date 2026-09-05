from __future__ import annotations

from dataclasses import replace
import unittest

import psycopg

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.book_followup_authority.reader_policy import ReaderProxyPolicy
from novel_forge.modules.book_followup_authority.reader_policy_authority import (
    PostgresReaderProxyPolicyAuthority,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    seed_authority_project_book,
)


class RuntimePolicyPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def setUp(self) -> None:
        self.project_id = identifier("policy-contract")
        self.workspace_id = f"workspace:{self.project_id}"
        seed_authority_project_book(
            project_id=self.project_id, book_id=f"book:{self.project_id}"
        )
        self.principal = Principal(
            principal_id="policy-operator",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset({"book.authority.execute"}),
            project_scope=frozenset({self.project_id}),
            authentication_source="integration-test",
        )
        self.authority = PostgresReaderProxyPolicyAuthority(
            DATABASE_URL,
            application_build_id="policy-contract-test",
            commit_sha="f" * 40,
        )
        self.policy = replace(
            ReaderProxyPolicy(), policy_version="configured-v1", confusion=0.6
        )
        self.command = {
            "project_id": self.project_id,
            "workspace_id": self.workspace_id,
            "principal": self.principal,
            "policy": self.policy,
            "idempotency_key": identifier("configure"),
            "trace_id": identifier("trace"),
            "correlation_id": identifier("correlation"),
        }

    def test_configuration_rollback_lost_response_and_replay_are_atomic(self) -> None:
        def fail_after_selection(name: str) -> None:
            if name == "after_policy_selection":
                raise RuntimeError("rollback policy selection")

        with self.assertRaisesRegex(RuntimeError, "rollback policy"):
            self.authority.configure(
                **self.command, fault_injector=fail_after_selection
            )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "SELECT COUNT(*) FROM authority_runtime_policy_version WHERE project_id=%s",
                [self.project_id],
            )
            self.assertEqual(uow.cursor.fetchone()[0], 0)

        def lose_committed_response(name: str) -> None:
            if name == "after_operation_completion_before_response":
                raise RuntimeError("lost committed response")

        with self.assertRaisesRegex(RuntimeError, "lost committed"):
            self.authority.configure(
                **self.command, fault_injector=lose_committed_response
            )
        replay = self.authority.configure(**self.command)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["status"], "SUCCEEDED")
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """SELECT selected_by_operation_id FROM authority_runtime_policy_selection
                   WHERE owner='READER_PROXY' AND project_id=%s""",
                [self.project_id],
            )
            self.assertEqual(uow.cursor.fetchone()[0], replay["operation_id"])

    def test_new_policy_cannot_change_frozen_admission_or_reuse_version(self) -> None:
        self.authority.configure(**self.command)
        old = self.authority.freeze_for_admission(
            project_id=self.project_id,
            idempotency_key="followup:1",
            actor_id=self.principal.principal_id,
        )
        changed = replace(self.policy, policy_version="configured-v2", confusion=0.95)
        self.authority.configure(
            **{**self.command, "policy": changed, "idempotency_key": "configure:v2"}
        )
        recovered = PostgresReaderProxyPolicyAuthority(
            DATABASE_URL,
            application_build_id="policy-contract-restarted",
            commit_sha="f" * 40,
        ).freeze_for_admission(
            project_id=self.project_id,
            idempotency_key="followup:1",
            actor_id=self.principal.principal_id,
        )
        new = self.authority.freeze_for_admission(
            project_id=self.project_id,
            idempotency_key="followup:2",
            actor_id=self.principal.principal_id,
        )
        self.assertEqual(old, recovered)
        self.assertEqual(new["policy"]["policy_version"], "configured-v2")
        with self.assertRaisesRegex(KernelError, "RUNTIME_POLICY_VERSION_CONFLICT"):
            self.authority.configure(
                **{
                    **self.command,
                    "policy": replace(self.policy, confusion=0.1),
                    "idempotency_key": "illegal-version-reuse",
                }
            )
        for table in (
            "authority_runtime_policy_binding",
            "authority_runtime_policy_version",
        ):
            with self.assertRaises(psycopg.errors.CheckViolation):
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute(
                        f"UPDATE {table} SET policy_version=policy_version WHERE project_id=%s",
                        [self.project_id],
                    )
                    uow.commit()

    def test_policy_configuration_rejects_cross_project_principal(self) -> None:
        with self.assertRaises(PermissionError):
            self.authority.configure(
                **{**self.command, "project_id": "another-project"}
            )
