"""Typed planning bindings over active Story Design AssetVersions."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .domain import (
    PlanContractType,
    PlanExecutionScope,
    validate_planning_contract,
)


_PARENT_TYPES = {
    PlanContractType.VOLUME: PlanContractType.BOOK,
    PlanContractType.CHAPTER_GROUP: PlanContractType.VOLUME,
    PlanContractType.CHAPTER: PlanContractType.CHAPTER_GROUP,
}

_RELATIONS = {
    PlanContractType.VOLUME: "BOOK_CONTAINS_VOLUME",
    PlanContractType.CHAPTER_GROUP: "VOLUME_CONTAINS_CHAPTER_GROUP",
    PlanContractType.CHAPTER: "CHAPTER_GROUP_CONTAINS_CHAPTER",
}


class PostgresHierarchicalPlanningAuthority:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("Hierarchical Planning requires PostgreSQL")
        self.database_url = database_url

    def bind_active_contract(
        self,
        *,
        project_id: str,
        book_id: str,
        asset_version_id: str,
        contract_type: PlanContractType,
        parent_version_id: str = "",
        execution_scope: PlanExecutionScope = PlanExecutionScope.PLANNED,
        replacement_approved: bool = False,
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT state.logical_key, state.lifecycle,
                       state.updated_by_operation_id,
                       version.content, version.content_hash
                FROM authority_story_design_version_state AS state
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=state.asset_version_id
                JOIN authority_story_design_active_version AS active
                  ON active.project_id=state.project_id
                 AND active.asset_version_id=state.asset_version_id
                WHERE state.project_id=%s AND state.asset_version_id=%s
                FOR UPDATE
                """,
                [project_id, asset_version_id],
            )
            row = uow.cursor.fetchone()
            if row is None or str(row[1]) != "ACTIVE":
                raise KernelError(
                    "PLANNING_ACTIVE_DESIGN_REQUIRED",
                    "planning binding requires an active Story Design version",
                )
            content = dict(row[3])
            contract = validate_planning_contract(
                project_id=project_id,
                book_id=book_id,
                contract_type=contract_type,
                asset_version_id=asset_version_id,
                parent_version_id=parent_version_id,
                execution_scope=execution_scope,
                content=content,
            )
            operation_id = str(row[2])
            parent_binding = None
            expected_parent = _PARENT_TYPES.get(contract_type)
            if expected_parent is not None:
                uow.cursor.execute(
                    """
                    SELECT binding_id, contract_type
                    FROM story_plan_binding
                    WHERE project_id=%s AND book_id=%s
                      AND asset_version_id=%s
                    """,
                    [project_id, book_id, parent_version_id],
                )
                parent_binding = uow.cursor.fetchone()
                if (
                    parent_binding is None
                    or str(parent_binding[1]) != expected_parent.value
                ):
                    raise KernelError(
                        "PLANNING_PARENT_BINDING_INVALID",
                        f"{contract_type.value} requires active "
                        f"{expected_parent.value} parent binding",
                    )
            binding_id = f"plan-binding:{project_id}:{asset_version_id}"
            uow.cursor.execute(
                """
                SELECT binding_id
                FROM story_plan_binding
                WHERE project_id=%s AND asset_version_id=%s
                """,
                [project_id, asset_version_id],
            )
            existing = uow.cursor.fetchone()
            if existing is None:
                self._guard_replacement(
                    uow.cursor,
                    project_id=project_id,
                    book_id=book_id,
                    logical_key=contract.logical_key,
                    replacement_approved=replacement_approved,
                )
                uow.cursor.execute(
                    """
                    INSERT INTO story_plan_binding(
                        binding_id, project_id, book_id, contract_type,
                        logical_key, asset_version_id, parent_version_id,
                        execution_scope, freshness, created_by_operation_id
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, NULLIF(%s, ''),
                        %s, 'CURRENT', %s
                    )
                    """,
                    [
                        binding_id,
                        project_id,
                        book_id,
                        contract_type.value,
                        contract.logical_key,
                        asset_version_id,
                        parent_version_id,
                        execution_scope.value,
                        operation_id,
                    ],
                )
                if parent_binding is not None:
                    uow.cursor.execute(
                        """
                        INSERT INTO story_plan_hierarchy(
                            hierarchy_id, project_id, book_id,
                            parent_binding_id, child_binding_id,
                            relation_type, created_by_operation_id
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        [
                            f"plan-hierarchy:{parent_binding[0]}:{binding_id}",
                            project_id,
                            book_id,
                            str(parent_binding[0]),
                            binding_id,
                            _RELATIONS[contract_type],
                            operation_id,
                        ],
                    )
                    self._dependency(
                        uow.cursor,
                        project_id,
                        book_id,
                        parent_version_id,
                        asset_version_id,
                        "PARENT_VERSION",
                        "MARK_STALE",
                        operation_id,
                    )
                self._semantic_edges(
                    uow.cursor,
                    contract_type=contract_type,
                    project_id=project_id,
                    book_id=book_id,
                    asset_version_id=asset_version_id,
                    content=content,
                    operation_id=operation_id,
                )
            uow.cursor.execute(
                """
                INSERT INTO active_story_plan_version(
                    project_id, book_id, logical_key, binding_id,
                    asset_version_id, activated_by_operation_id
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (project_id, book_id, logical_key) DO UPDATE
                SET binding_id=EXCLUDED.binding_id,
                    asset_version_id=EXCLUDED.asset_version_id,
                    activated_by_operation_id=
                        EXCLUDED.activated_by_operation_id,
                    activated_at=NOW()
                """,
                [
                    project_id,
                    book_id,
                    contract.logical_key,
                    binding_id,
                    asset_version_id,
                    operation_id,
                ],
            )
            event_id = str(uuid4())
            uow.repositories.operation_graph.record_event(
                {
                    "event_id": event_id,
                    "audit_id": str(uuid4()),
                    "outbox_id": str(uuid4()),
                    "aggregate_type": "story_plan_binding",
                    "aggregate_id": binding_id,
                    "operation_id": operation_id,
                    "project_id": project_id,
                    "event_type": "story_plan.bound",
                    "correlation_id": f"book:{book_id}",
                    "causation_id": operation_id,
                    "payload": {
                        "binding_id": binding_id,
                        "book_id": book_id,
                        "contract_type": contract_type.value,
                        "asset_version_id": asset_version_id,
                        "parent_version_id": parent_version_id,
                        "execution_scope": execution_scope.value,
                        "content_hash": str(row[4]),
                    },
                }
            )
            uow.commit()
        return self.require_binding(
            project_id=project_id, asset_version_id=asset_version_id
        )

    def require_binding(
        self, *, project_id: str, asset_version_id: str
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT binding_id, project_id, book_id, contract_type,
                       logical_key, asset_version_id, parent_version_id,
                       execution_scope, freshness, created_by_operation_id,
                       version
                FROM story_plan_binding
                WHERE project_id=%s AND asset_version_id=%s
                """,
                [project_id, asset_version_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "PLANNING_BINDING_NOT_FOUND", "planning binding does not exist"
            )
        fields = (
            "binding_id",
            "project_id",
            "book_id",
            "contract_type",
            "logical_key",
            "asset_version_id",
            "parent_version_id",
            "execution_scope",
            "freshness",
            "created_by_operation_id",
            "version",
        )
        return dict(zip(fields, row, strict=True))

    @staticmethod
    def _guard_replacement(
        cursor: Any,
        *,
        project_id: str,
        book_id: str,
        logical_key: str,
        replacement_approved: bool,
    ) -> None:
        cursor.execute(
            """
            SELECT binding.binding_id, binding.execution_scope
            FROM active_story_plan_version AS active
            JOIN story_plan_binding AS binding
              ON binding.binding_id=active.binding_id
            WHERE active.project_id=%s AND active.book_id=%s
              AND active.logical_key=%s
            FOR UPDATE
            """,
            [project_id, book_id, logical_key],
        )
        previous = cursor.fetchone()
        if previous is None:
            return
        scope = str(previous[1])
        if scope == "EXECUTED":
            raise KernelError(
                "EXECUTED_PLAN_IMMUTABLE",
                "executed plan versions cannot be replaced",
            )
        if scope == "FROZEN" and not replacement_approved:
            raise KernelError(
                "FROZEN_PLAN_APPROVAL_REQUIRED",
                "replacing a frozen plan requires Authority approval",
            )
        cursor.execute(
            """
            UPDATE story_plan_binding
            SET freshness='STALE', version=version+1
            WHERE binding_id=%s
            """,
            [str(previous[0])],
        )

    def _semantic_edges(
        self,
        cursor: Any,
        *,
        contract_type: PlanContractType,
        project_id: str,
        book_id: str,
        asset_version_id: str,
        content: dict[str, Any],
        operation_id: str,
    ) -> None:
        if contract_type is PlanContractType.ARC:
            for volume_version in content.get("cross_volume_scope") or []:
                self._dependency(
                    cursor,
                    project_id,
                    book_id,
                    str(volume_version),
                    asset_version_id,
                    "ARC_CONTRIBUTION",
                    "MARK_IMPACTED",
                    operation_id,
                )
        if contract_type is PlanContractType.CHAPTER:
            for arc_version in content.get(
                "required_arc_contributions"
            ) or []:
                self._dependency(
                    cursor,
                    project_id,
                    book_id,
                    str(arc_version),
                    asset_version_id,
                    "ARC_CONTRIBUTION",
                    "MARK_STALE",
                    operation_id,
                )
        for dependency in content.get("canon_dependencies") or []:
            if isinstance(dependency, str):
                self._dependency(
                    cursor,
                    project_id,
                    book_id,
                    dependency,
                    asset_version_id,
                    "CANON_DEPENDENCY",
                    "MARK_STALE",
                    operation_id,
                )

    @staticmethod
    def _dependency(
        cursor: Any,
        project_id: str,
        book_id: str,
        source: str,
        dependent: str,
        dependency_type: str,
        invalidation_policy: str,
        operation_id: str,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO asset_dependency_edge(
                dependency_edge_id, project_id, book_id,
                source_asset_version_id, dependent_asset_version_id,
                dependency_type, invalidation_policy,
                created_by_operation_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (
                project_id, source_asset_version_id,
                dependent_asset_version_id, dependency_type
            ) DO NOTHING
            """,
            [
                f"dependency:{project_id}:{source}:{dependent}:"
                f"{dependency_type}",
                project_id,
                book_id,
                source,
                dependent,
                dependency_type,
                invalidation_policy,
                operation_id,
            ],
        )


__all__ = ["PostgresHierarchicalPlanningAuthority"]
