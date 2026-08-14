from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping


class PrincipalType(StrEnum):
    LOCAL_OPERATOR = "local_operator"
    SERVICE = "service"
    WORKER = "worker"
    SYSTEM_SCHEDULER = "system_scheduler"


@dataclass(frozen=True, slots=True)
class Principal:
    principal_id: str
    principal_type: PrincipalType
    permissions: frozenset[str]
    project_scope: frozenset[str]
    authentication_source: str

    def allows(self, permission: str, project_id: str) -> bool:
        project_allowed = "*" in self.project_scope or project_id in self.project_scope
        permission_allowed = (
            "*" in self.permissions
            or permission in self.permissions
            or any(
                value.endswith("*") and permission.startswith(value[:-1])
                for value in self.permissions
            )
        )
        return project_allowed and permission_allowed

    def require(self, permission: str, project_id: str) -> None:
        if not self.allows(permission, project_id):
            raise PermissionError(
                f"principal {self.principal_id} cannot {permission} in project {project_id}"
            )


class TrustedPrincipalResolver:
    """Resolve identities from trusted server configuration, never request payloads."""

    def __init__(
        self,
        *,
        environment: str,
        configured_local_operator_id: str = "",
        configured_narrative_evaluator_id: str = "",
        configured_project_scope: frozenset[str] | None = None,
    ) -> None:
        self.environment = environment.strip().lower() or "development"
        self.configured_local_operator_id = configured_local_operator_id.strip()
        self.configured_narrative_evaluator_id = (
            configured_narrative_evaluator_id.strip()
        )
        self.configured_project_scope = configured_project_scope or frozenset({"*"})

    @classmethod
    def from_environment(cls, values: Mapping[str, str]) -> "TrustedPrincipalResolver":
        scope = frozenset(
            item.strip()
            for item in str(
                values.get("NOVEL_FORGE_AUTHORITY_PROJECT_SCOPE") or "*"
            ).split(",")
            if item.strip()
        )
        return cls(
            environment=str(values.get("NOVEL_FORGE_ENVIRONMENT") or "development"),
            configured_local_operator_id=str(
                values.get("NOVEL_FORGE_LOCAL_OPERATOR_PRINCIPAL_ID") or ""
            ),
            configured_narrative_evaluator_id=str(
                values.get("NOVEL_FORGE_NARRATIVE_EVALUATOR_PRINCIPAL_ID") or ""
            ),
            configured_project_scope=scope,
        )

    def resolve_api_principal(self, *, claimed_actor_id: str = "") -> Principal:
        del (
            claimed_actor_id
        )  # compatibility input is deliberately not an identity source
        principal_id = self.configured_local_operator_id
        if not principal_id and self.environment == "production":
            raise RuntimeError(
                "a trusted local operator principal is required in production"
            )
        return Principal(
            principal_id=principal_id or "local-operator",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset(
                {
                    "chapter.authority.execute",
                    "chapter.authority.query",
                    "chapter.authority.cancel",
                    "agent.authority.admin",
                    "agent.authority.execute",
                    "agent.authority.query",
                    "agent.authority.cancel",
                    "agent.authority.recover",
                    "content.authority.execute",
                    "content.authority.query",
                    "content.authority.cancel",
                    "content.authority.recover",
                    "book.authority.execute",
                    "book.authority.approve_replan",
                    "book.authority.query",
                    "story_planning.authority.execute",
                    "story_design.authority.execute",
                    "narrative_design.evaluate",
                    "book_design.authority.execute",
                    "book_design.authority.query",
                    "project.authority.execute",
                    "project.authority.query",
                    "task.authority.query",
                    "task.authority.cancel",
                    "task.authority.recover",
                    "source.authority.execute",
                    "source.authority.query",
                    "mkaos.authority.execute",
                    "mkaos.authority.approve",
                    "mkaos.authority.query",
                    "asset.authority.query",
                    "system.authority.query",
                    "book.followup:*",
                    "external_effect.resolve",
                    "canon.authority.query",
                    "canon.authority.approve",
                    "content.operation:*",
                    "capability_pack.authority.register",
                    "capability_pack.authority.compile",
                    "capability_pack.authority.approve",
                    "capability_pack.authority.deploy",
                    "capability_pack.authority.activate",
                    "capability_pack.authority.rollback",
                    "capability_pack.authority.retire",
                    "capability_pack.authority.query",
                }
            ),
            project_scope=self.configured_project_scope,
            authentication_source="server_configuration",
        )

    def resolve_narrative_evaluator_principal(self) -> Principal:
        principal_id = self.configured_narrative_evaluator_id
        if not principal_id and self.environment == "production":
            raise RuntimeError(
                "a trusted Narrative Semantic Evaluator principal is required in production"
            )
        return Principal(
            principal_id=principal_id or "narrative-semantic-evaluator",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset({"narrative_design.evaluate"}),
            project_scope=self.configured_project_scope,
            authentication_source="narrative_evaluator_configuration",
        )

    def resolve_worker_principal(
        self,
        worker_id: str,
        *,
        permission_subset: frozenset[str] | None = None,
    ) -> Principal:
        worker_id = worker_id.strip()
        if not worker_id:
            raise RuntimeError("configured Authority worker identity is required")
        worker_permissions = frozenset(
            {
                "chapter.authority.execute",
                "agent.authority.execute",
                "agent.authority.query",
                "agent.authority.recover",
                "book.authority.execute",
                "story_planning.authority.execute",
                "narrative_design.evaluate",
                "project.authority.execute",
                "book_design.authority.execute",
                "content.authority.execute",
                "mkaos.authority.execute",
                "source.authority.execute",
                "mkaos.authority.approve",
                "content.operation:*",
                "external_effect.execute",
                "book.followup:*",
            }
        )
        if (
            permission_subset is not None
            and not permission_subset <= worker_permissions
        ):
            raise RuntimeError(
                "worker permission subset exceeds the trusted worker policy"
            )
        return Principal(
            principal_id=worker_id,
            principal_type=PrincipalType.WORKER,
            permissions=(
                worker_permissions if permission_subset is None else permission_subset
            ),
            project_scope=self.configured_project_scope,
            authentication_source="worker_configuration",
        )
