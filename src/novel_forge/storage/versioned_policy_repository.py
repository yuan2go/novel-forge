from __future__ import annotations

import hashlib
import json
from typing import Any

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError


def policy_hash(content: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class VersionedPolicyRepository:
    def __init__(self, cursor: Any, *, owner: str, project_id: str) -> None:
        self.cursor = cursor
        self.owner = owner
        self.project_id = project_id

    def register(
        self, content: dict[str, Any], *, actor_id: str, operation_id: str | None = None
    ) -> None:
        version = str(content["policy_version"])
        digest = policy_hash(content)
        self.cursor.execute(
            """
            INSERT INTO authority_runtime_policy_version(
                owner, project_id, policy_version, content, content_hash, actor_id,
                created_by_operation_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(owner, project_id, policy_version) DO NOTHING
            """,
            [
                self.owner,
                self.project_id,
                version,
                Jsonb(content),
                digest,
                actor_id,
                operation_id,
            ],
        )
        self.cursor.execute(
            """
            SELECT content_hash FROM authority_runtime_policy_version
            WHERE owner=%s AND project_id=%s AND policy_version=%s
            """,
            [self.owner, self.project_id, version],
        )
        if self.cursor.fetchone()[0] != digest:
            raise KernelError(
                "RUNTIME_POLICY_VERSION_CONFLICT",
                "a policy version cannot be reused with different content",
            )

    def select(
        self, content: dict[str, Any], *, actor_id: str, operation_id: str
    ) -> None:
        self.register(content, actor_id=actor_id, operation_id=operation_id)
        self.cursor.execute(
            """
            INSERT INTO authority_runtime_policy_selection(
                owner, project_id, policy_version, selected_by_operation_id
            ) VALUES (%s, %s, %s, %s)
            ON CONFLICT(owner, project_id) DO UPDATE
            SET policy_version=EXCLUDED.policy_version,
                selected_by_operation_id=EXCLUDED.selected_by_operation_id
            """,
            [self.owner, self.project_id, content["policy_version"], operation_id],
        )

    def freeze(
        self, *, subject_id: str, default: dict[str, Any], actor_id: str
    ) -> dict[str, Any]:
        self.register(default, actor_id=actor_id)
        self.cursor.execute(
            """
            INSERT INTO authority_runtime_policy_binding(
                owner, project_id, subject_id, policy_version
            ) VALUES (%s, %s, %s, COALESCE((
                SELECT policy_version FROM authority_runtime_policy_selection
                WHERE owner=%s AND project_id=%s
            ), %s))
            ON CONFLICT(owner, project_id, subject_id) DO NOTHING
            """,
            [
                self.owner,
                self.project_id,
                subject_id,
                self.owner,
                self.project_id,
                default["policy_version"],
            ],
        )
        self.cursor.execute(
            """
            SELECT version.content, version.content_hash
            FROM authority_runtime_policy_binding AS binding
            JOIN authority_runtime_policy_version AS version
              USING(owner, project_id, policy_version)
            WHERE binding.owner=%s AND binding.project_id=%s
              AND binding.subject_id=%s
            """,
            [self.owner, self.project_id, subject_id],
        )
        content, digest = self.cursor.fetchone()
        if policy_hash(content) != digest:
            raise KernelError("RUNTIME_POLICY_HASH_MISMATCH", "policy integrity failed")
        return {
            "owner": self.owner,
            "project_id": self.project_id,
            "subject_id": subject_id,
            "policy_hash": digest,
            "policy": content,
        }
