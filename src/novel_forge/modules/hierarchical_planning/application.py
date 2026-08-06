"""Typed planning bindings over active Story Design AssetVersions."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    TransactionCheckpoint,
    execute_transaction_command,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .definitions import (
    PLAN_BINDING_DEFINITION_VERSION,
    PLAN_BINDING_HANDLER_KEY,
    plan_binding_definitions,
)
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
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        if not database_url or not application_build_id or len(commit_sha) != 40:
            raise ValueError(
                "Hierarchical Planning requires PostgreSQL and build identity"
            )
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.fault_injector = fault_injector

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
        expected_active_asset_version_id: str = "",
        decision_evidence: dict[str, Any] | None = None,
        workspace_id: str,
        actor_id: str,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
        causation_operation_id: str = "",
        principal: Principal,
    ) -> dict[str, Any]:
        principal.require("book.authority.execute", project_id)
        if principal.principal_id != actor_id:
            raise KernelError(
                "ACTOR_IDENTITY_INVALID",
                "planning command actor does not match authenticated principal",
            )
        evidence = dict(decision_evidence or {})
        if replacement_approved and not evidence:
            raise KernelError(
                "PLANNING_REPLACEMENT_EVIDENCE_REQUIRED",
                "approved plan replacement requires decision evidence",
            )
        self._register_definitions()
        input_assets = self._input_assets(
            project_id,
            tuple(item for item in (asset_version_id, parent_version_id) if item),
        )
        result = execute_transaction_command(
            self.database_url,
            {
                "definition_name": "planning.binding.activate",
                "definition_version": PLAN_BINDING_DEFINITION_VERSION,
                "project_id": project_id,
                "workspace_id": workspace_id,
                "book_id": book_id,
                "actor_id": actor_id,
                "idempotency_scope": "book:planning-binding",
                "idempotency_key": idempotency_key,
                "trace_id": trace_id,
                "span_id": str(uuid4()),
                "correlation_id": correlation_id,
                "causation_id": causation_operation_id,
                "causation_operation_id": causation_operation_id or None,
                "input": {
                    "project_id": project_id,
                    "workspace_id": workspace_id,
                    "book_id": book_id,
                    "asset_version_id": asset_version_id,
                    "contract_type": contract_type.value,
                    "parent_version_id": parent_version_id,
                    "execution_scope": execution_scope.value,
                    "expected_active_asset_version_id": (
                        expected_active_asset_version_id
                    ),
                    "replacement_approved": replacement_approved,
                    "decision_evidence": evidence,
                },
                "input_assets": list(input_assets),
            },
            context=AdmissionContext(
                actor_id=actor_id,
                permissions=frozenset({"book.authority.execute"}),
                available_handlers=frozenset({PLAN_BINDING_HANDLER_KEY}),
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
            handler=self._execute_transaction,
            fault_injector=self.fault_injector,
        )
        binding = self.require_binding(
            project_id=project_id, asset_version_id=asset_version_id
        )
        return {
            **binding,
            "operation_id": result["operation_id"],
            "replayed": result["replayed"],
        }

    def _execute_transaction(
        self,
        uow: AuthorityUnitOfWork,
        operation_id: str,
        checkpoint: TransactionCheckpoint,
    ) -> dict[str, Any]:
        uow.cursor.execute(
            """
            SELECT project_id, command_payload, actor_id,
                   trace_id, correlation_id, causation_id
            FROM authority_operation
            WHERE operation_id=%s
            """,
            [operation_id],
        )
        operation = uow.cursor.fetchone()
        if operation is None:
            raise KernelError(
                "PLANNING_OPERATION_NOT_FOUND",
                "admitted Planning binding Operation does not exist",
            )
        project_id = str(operation[0])
        payload = dict(operation[1])
        book_id = str(payload["book_id"])
        asset_version_id = str(payload["asset_version_id"])
        contract_type = PlanContractType(str(payload["contract_type"]))
        parent_version_id = str(payload.get("parent_version_id") or "")
        execution_scope = PlanExecutionScope(str(payload["execution_scope"]))
        expected_active = str(payload.get("expected_active_asset_version_id") or "")
        replacement_approved = bool(payload["replacement_approved"])
        decision_evidence = dict(payload.get("decision_evidence") or {})
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
        checkpoint("after_domain_validation")
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
        previous_asset_version_id = self._guard_replacement(
            uow.cursor,
            project_id=project_id,
            book_id=book_id,
            logical_key=contract.logical_key,
            new_asset_version_id=asset_version_id,
            expected_active_asset_version_id=expected_active,
            replacement_approved=replacement_approved,
        )
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
        else:
            uow.cursor.execute(
                """
                SELECT execution_scope FROM story_plan_binding
                WHERE binding_id=%s FOR UPDATE
                """,
                [str(existing[0])],
            )
            current_scope = str(uow.cursor.fetchone()[0])
            if current_scope != execution_scope.value:
                if (
                    current_scope,
                    execution_scope.value,
                ) != (
                    PlanExecutionScope.PLANNED.value,
                    PlanExecutionScope.FROZEN.value,
                ):
                    raise KernelError(
                        "PLANNING_EXECUTION_SCOPE_TRANSITION_INVALID",
                        "only an Active Planned contract may advance to Frozen here",
                    )
                uow.cursor.execute(
                    """
                    UPDATE story_plan_binding
                    SET execution_scope='FROZEN', version=version+1
                    WHERE binding_id=%s AND execution_scope='PLANNED'
                    """,
                    [str(existing[0])],
                )
                if uow.cursor.rowcount != 1:
                    raise KernelError(
                        "PLANNING_EXECUTION_SCOPE_CONFLICT",
                        "planning execution scope changed during freeze",
                    )
        checkpoint("after_business_projection_update")
        uow.cursor.execute(
            """
            INSERT INTO active_story_plan_version(
                project_id, book_id, logical_key, binding_id,
                asset_version_id, activated_by_operation_id
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (project_id, book_id, logical_key) DO UPDATE
            SET binding_id=EXCLUDED.binding_id,
                asset_version_id=EXCLUDED.asset_version_id,
                activated_by_operation_id=EXCLUDED.activated_by_operation_id,
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
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": "story_plan_binding",
                "aggregate_id": binding_id,
                "operation_id": operation_id,
                "project_id": project_id,
                "event_type": "story_plan.bound",
                "correlation_id": str(operation[4]),
                "causation_id": str(operation[5] or row[2]),
                "payload": {
                    "operation_id": operation_id,
                    "project_id": project_id,
                    "binding_id": binding_id,
                    "book_id": book_id,
                    "contract_type": contract_type.value,
                    "asset_version_id": asset_version_id,
                    "previous_asset_version_id": previous_asset_version_id,
                    "parent_version_id": parent_version_id,
                    "execution_scope": execution_scope.value,
                    "content_hash": str(row[4]),
                    "decision_evidence": decision_evidence,
                },
            }
        )
        checkpoint("after_outbox_insert")
        return {
            "binding_id": binding_id,
            "book_id": book_id,
            "asset_version_id": asset_version_id,
            "logical_key": contract.logical_key,
            "previous_asset_version_id": previous_asset_version_id,
        }

    def _register_definitions(self) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            for definition in plan_binding_definitions(
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ):
                uow.repositories.definitions.register(definition)
            uow.commit()

    def _input_assets(
        self, project_id: str, asset_version_ids: tuple[str, ...]
    ) -> tuple[dict[str, str], ...]:
        if not asset_version_ids:
            return ()
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT version.asset_version_id, version.content_hash
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE asset.project_id=%s
                  AND version.asset_version_id=ANY(%s)
                """,
                [project_id, list(asset_version_ids)],
            )
            found = {str(row[0]): str(row[1]) for row in uow.cursor.fetchall()}
        missing = sorted(set(asset_version_ids) - set(found))
        if missing:
            raise KernelError(
                "PLANNING_INPUT_ASSET_SCOPE_INVALID",
                "planning inputs are missing or outside Project scope: "
                + ", ".join(missing),
            )
        return tuple(
            {"asset_version_id": item, "content_hash": found[item]}
            for item in asset_version_ids
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
        new_asset_version_id: str,
        expected_active_asset_version_id: str,
        replacement_approved: bool,
    ) -> str:
        cursor.execute(
            """
            SELECT binding.binding_id, binding.execution_scope,
                   active.asset_version_id
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
            if expected_active_asset_version_id:
                raise KernelError(
                    "PLANNING_EXPECTED_VERSION_CONFLICT",
                    "expected active plan version does not exist",
                )
            return ""
        previous_asset_version_id = str(previous[2])
        if previous_asset_version_id != expected_active_asset_version_id:
            raise KernelError(
                "PLANNING_EXPECTED_VERSION_CONFLICT",
                "expected active plan version is stale",
            )
        if previous_asset_version_id == new_asset_version_id:
            return previous_asset_version_id
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
        return previous_asset_version_id

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
                self._arc_membership(
                    cursor,
                    project_id=project_id,
                    book_id=book_id,
                    arc_plan_version=asset_version_id,
                    member_plan_version=str(volume_version),
                    member_scope="VOLUME",
                    membership_kind="VOLUME_SPAN",
                    declaration={"volume_plan_version_id": str(volume_version)},
                    operation_id=operation_id,
                )
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
        if contract_type is PlanContractType.CHAPTER_GROUP:
            declarations = (
                ("primary_arc_ids", "PRIMARY"),
                ("secondary_arc_ids", "SECONDARY"),
                ("required_arc_contributions", "REQUIRED_CONTRIBUTION"),
                ("arc_checkpoint_expectations", "CHECKPOINT_EXPECTATION"),
            )
            for field, membership_kind in declarations:
                for raw in content.get(field) or []:
                    declaration = dict(raw) if isinstance(raw, dict) else {"value": raw}
                    arc_ref = (
                        declaration.get("arc_plan_version_id")
                        or declaration.get("arc_id")
                        or declaration.get("value")
                    )
                    arc_version = self._resolve_arc_version(
                        cursor,
                        project_id=project_id,
                        book_id=book_id,
                        arc_ref=str(arc_ref or ""),
                    )
                    self._arc_membership(
                        cursor,
                        project_id=project_id,
                        book_id=book_id,
                        arc_plan_version=arc_version,
                        member_plan_version=asset_version_id,
                        member_scope="CHAPTER_GROUP",
                        membership_kind=membership_kind,
                        declaration={**declaration, "source_field": field},
                        operation_id=operation_id,
                    )
        if contract_type is PlanContractType.CHAPTER:
            for contribution in content.get("required_arc_contributions") or []:
                arc_version = (
                    contribution.get("arc_plan_version_id")
                    if isinstance(contribution, dict)
                    else contribution
                )
                if not isinstance(arc_version, str) or not arc_version:
                    raise KernelError(
                        "PLANNING_ARC_CONTRIBUTION_INVALID",
                        "Chapter arc contribution must bind an exact ArcPlan AssetVersion",
                    )
                arc_version = self._resolve_arc_version(
                    cursor,
                    project_id=project_id,
                    book_id=book_id,
                    arc_ref=arc_version,
                )
                self._arc_membership(
                    cursor,
                    project_id=project_id,
                    book_id=book_id,
                    arc_plan_version=arc_version,
                    member_plan_version=asset_version_id,
                    member_scope="CHAPTER",
                    membership_kind="REQUIRED_CONTRIBUTION",
                    declaration=(
                        dict(contribution)
                        if isinstance(contribution, dict)
                        else {"value": contribution}
                    ),
                    operation_id=operation_id,
                )
                self._dependency(
                    cursor,
                    project_id,
                    book_id,
                    arc_version,
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
    def _resolve_arc_version(
        cursor: Any,
        *,
        project_id: str,
        book_id: str,
        arc_ref: str,
    ) -> str:
        if not arc_ref:
            raise KernelError(
                "PLANNING_ARC_MEMBERSHIP_INVALID",
                "Arc membership requires an exact version or active logical Arc id",
            )
        cursor.execute(
            """
            SELECT binding.asset_version_id
            FROM story_plan_binding AS binding
            JOIN active_story_plan_version AS active
              ON active.binding_id=binding.binding_id
            WHERE binding.project_id=%s AND binding.book_id=%s
              AND binding.contract_type='ARC' AND binding.freshness='CURRENT'
              AND (binding.asset_version_id=%s OR binding.logical_key=%s)
            """,
            [project_id, book_id, arc_ref, arc_ref],
        )
        rows = cursor.fetchall()
        if len(rows) != 1:
            raise KernelError(
                "PLANNING_ARC_MEMBERSHIP_AMBIGUOUS",
                f"Arc reference {arc_ref} did not resolve to one Active ArcPlan",
            )
        return str(rows[0][0])

    @staticmethod
    def _arc_membership(
        cursor: Any,
        *,
        project_id: str,
        book_id: str,
        arc_plan_version: str,
        member_plan_version: str,
        member_scope: str,
        membership_kind: str,
        declaration: dict[str, Any],
        operation_id: str,
    ) -> None:
        identity = (
            f"{project_id}:{arc_plan_version}:{member_plan_version}:{membership_kind}"
        )
        cursor.execute(
            """
            INSERT INTO authority_arc_membership(
                membership_id, project_id, book_id, arc_plan_version_id,
                member_plan_version_id, member_scope, membership_kind,
                required_contribution, created_by_operation_id
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (
                project_id, arc_plan_version_id,
                member_plan_version_id, membership_kind
            ) DO NOTHING
            """,
            [
                "arc-membership:" + sha256(identity.encode()).hexdigest(),
                project_id,
                book_id,
                arc_plan_version,
                member_plan_version,
                member_scope,
                membership_kind,
                Jsonb(declaration),
                operation_id,
            ],
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
                f"dependency:{project_id}:{source}:{dependent}:{dependency_type}",
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
