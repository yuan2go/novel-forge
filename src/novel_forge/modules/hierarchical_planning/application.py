from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.artifact_lineage import (
    ArtifactLineageEdge,
    InvalidationPolicy,
    PostgresArtifactLineageRepository,
    semantic_dimensions_for,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    TransactionCheckpoint,
    execute_transaction_command,
)
from novel_forge.modules.story_design_authority.application import (
    STORY_DESIGN_TRANSITION_DEFINITION,
    STORY_DESIGN_TRANSITION_VERSION,
)
from novel_forge.storage.authority_repositories import IdempotencyConflictError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.book_opening_plan_fence import (
    lock_and_assert_book_opening_plan_mutation,
)
from novel_forge.storage.legacy_migration_lineage import (
    require_approved_legacy_migration_lineage,
)

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

_PLAN_BINDING_DEFINITION_NAME = "planning.binding.activate"
_PLAN_BINDING_IDEMPOTENCY_SCOPE = "book:planning-binding"
_LEGACY_PLAN_BINDING_DEFINITION_VERSION = "1.0.0"


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
        story_design_transition_operation_id: str = "",
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
        definition_version = self._binding_definition_version_for_replay(
            project_id=project_id,
            idempotency_key=idempotency_key,
        )
        definition_version = definition_version or PLAN_BINDING_DEFINITION_VERSION
        if self.fault_injector is not None:
            self.fault_injector("after_planning_binding_replay_version_read")
        input_assets = self._input_assets(
            project_id,
            tuple(item for item in (asset_version_id, parent_version_id) if item),
        )
        binding_input = {
            "project_id": project_id,
            "workspace_id": workspace_id,
            "book_id": book_id,
            "asset_version_id": asset_version_id,
            "contract_type": contract_type.value,
            "parent_version_id": parent_version_id,
            "execution_scope": execution_scope.value,
            "expected_active_asset_version_id": expected_active_asset_version_id,
            "replacement_approved": replacement_approved,
            "decision_evidence": evidence,
        }

        def execute(version: str) -> dict[str, Any]:
            command_input = dict(binding_input)
            if version != _LEGACY_PLAN_BINDING_DEFINITION_VERSION:
                command_input["story_design_transition_operation_id"] = (
                    story_design_transition_operation_id
                )
            return execute_transaction_command(
                self.database_url,
                {
                    "definition_name": _PLAN_BINDING_DEFINITION_NAME,
                    "definition_version": version,
                    "project_id": project_id,
                    "workspace_id": workspace_id,
                    "book_id": book_id,
                    "actor_id": actor_id,
                    "idempotency_scope": _PLAN_BINDING_IDEMPOTENCY_SCOPE,
                    "idempotency_key": idempotency_key,
                    "trace_id": trace_id,
                    "span_id": str(uuid4()),
                    "correlation_id": correlation_id,
                    "causation_id": causation_operation_id,
                    "causation_operation_id": causation_operation_id or None,
                    "input": command_input,
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

        try:
            result = execute(definition_version)
        except IdempotencyConflictError:
            if definition_version != PLAN_BINDING_DEFINITION_VERSION:
                raise
            raced_version = self._binding_definition_version_for_replay(
                project_id=project_id,
                idempotency_key=idempotency_key,
            )
            if raced_version != _LEGACY_PLAN_BINDING_DEFINITION_VERSION:
                raise
            result = execute(raced_version)
        binding = self.require_binding(
            project_id=project_id, asset_version_id=asset_version_id
        )
        return {
            **binding,
            "operation_id": result["operation_id"],
            "replayed": result["replayed"],
        }

    def _binding_definition_version_for_replay(
        self,
        *,
        project_id: str,
        idempotency_key: str,
    ) -> str | None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT definition_name,definition_version,project_id
                FROM authority_operation
                WHERE idempotency_scope=%s AND idempotency_key=%s
                """,
                [_PLAN_BINDING_IDEMPOTENCY_SCOPE, idempotency_key],
            )
            row = uow.cursor.fetchone()
        if row is None:
            return None
        if (
            str(row[0]) != _PLAN_BINDING_DEFINITION_NAME
            or str(row[2]) != project_id
            or str(row[1])
            not in {
                _LEGACY_PLAN_BINDING_DEFINITION_VERSION,
                PLAN_BINDING_DEFINITION_VERSION,
            }
        ):
            raise IdempotencyConflictError(
                "planning binding idempotency key belongs to another authority request"
            )
        return str(row[1])

    def _execute_transaction(
        self,
        uow: AuthorityUnitOfWork,
        operation_id: str,
        checkpoint: TransactionCheckpoint,
    ) -> dict[str, Any]:
        uow.cursor.execute(
            """
            SELECT project_id, command_payload, actor_id,
                   trace_id, correlation_id, causation_operation_id
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
        story_design_transition_operation_id = str(
            payload.get("story_design_transition_operation_id") or ""
        )
        lock_and_assert_book_opening_plan_mutation(
            uow.cursor,
            project_id=project_id,
            book_id=book_id,
            generation_operation_id=str(operation[5] or ""),
            candidate_asset_version_id=asset_version_id,
        )
        if story_design_transition_operation_id:
            self._apply_story_design_activation_in_uow(
                uow,
                transition_operation_id=story_design_transition_operation_id,
                project_id=project_id,
                actor_id=str(operation[2]),
                asset_version_id=asset_version_id,
            )
            checkpoint("after_story_design_activation_before_binding")
        uow.cursor.execute(
            """
                SELECT state.logical_key, state.lifecycle,
                       state.updated_by_operation_id,
                       version.content, version.content_hash,
                       version.lifecycle, version.eligibility,
                       state.source_kind,
                       version.created_at,
                       (
                           SELECT applied_at FROM nf_schema_migrations
                           WHERE migration_id='20260825_0100_hierarchy_closure'
                       )
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
        if (
            row is None
            or str(row[1]) != "ACTIVE"
            or str(row[5]) not in {"CANDIDATE", "ACTIVE"}
            or str(row[6]) != "ELIGIBLE"
        ):
            if (
                row is not None
                and str(row[1]) == "ACTIVE"
                and str(row[5]) == "IMPORTED"
                and str(row[6]) == "PENDING_EVALUATION"
            ):
                self._qualify_approved_migration_candidate(
                    uow.cursor,
                    project_id=project_id,
                    workspace_id=str(payload["workspace_id"]),
                    asset_version_id=asset_version_id,
                    target_content_hash=str(row[4]),
                    operation_id=operation_id,
                    decision_evidence=decision_evidence,
                )
                row = (*row[:5], "CANDIDATE", "ELIGIBLE", *row[7:])
        if (
            row is None
            or str(row[1]) != "ACTIVE"
            or str(row[5]) not in {"CANDIDATE", "ACTIVE"}
            or str(row[6]) != "ELIGIBLE"
        ):
            raise KernelError(
                "PLANNING_ACTIVE_DESIGN_REQUIRED",
                "planning binding requires an active, qualified Story Design candidate",
            )
        content = dict(row[3])
        hierarchy_compatibility = str(row[7]) == "LEGACY_IMPORT" or bool(
            row[8] is not None and row[9] is not None and row[8] < row[9]
        )
        contract = validate_planning_contract(
            project_id=project_id,
            book_id=book_id,
            contract_type=contract_type,
            asset_version_id=asset_version_id,
            parent_version_id=parent_version_id,
            execution_scope=execution_scope,
            content=content,
            allow_pre_hierarchy_compatibility=hierarchy_compatibility,
        )
        if contract_type is PlanContractType.BOOK and not hierarchy_compatibility:
            self._require_qualified_foundation_for_book_plan(
                uow.cursor,
                project_id=project_id,
                book_id=book_id,
                content=content,
            )
        if contract_type is PlanContractType.CHAPTER and not hierarchy_compatibility:
            from novel_forge.storage.narrative_realization_repositories import (
                NarrativeRealizationRepository,
            )

            realization = NarrativeRealizationRepository(
                uow.cursor
            ).require_current_for_chapter(
                project_id=project_id,
                book_id=book_id,
                chapter_group_plan_version_id=parent_version_id,
                chapter_number=int(content.get("chapter_number") or 0),
            )
            if dict(content.get("narrative_realization_slice") or {}) != realization:
                raise KernelError(
                    "CHAPTER_NARRATIVE_REALIZATION_DRIFT",
                    "ChapterPlan activation differs from the current Frozen realization",
                )
        self._require_realization_authority_lineage(
            uow.cursor,
            project_id=project_id,
            book_id=book_id,
            content=content,
        )
        checkpoint("after_domain_validation")
        parent_binding = None
        expected_parent = _PARENT_TYPES.get(contract_type)
        if expected_parent is not None:
            uow.cursor.execute(
                """
                SELECT binding.binding_id, binding.contract_type
                FROM story_plan_binding AS binding
                JOIN active_story_plan_version AS active
                  ON active.binding_id=binding.binding_id
                WHERE binding.project_id=%s AND binding.book_id=%s
                  AND binding.asset_version_id=%s
                  AND binding.freshness='CURRENT'
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
        if previous_asset_version_id != asset_version_id:
            if previous_asset_version_id:
                uow.cursor.execute(
                    """
                    UPDATE authority_asset_version
                    SET lifecycle='SUPERSEDED'
                    WHERE asset_version_id=%s AND lifecycle='ACTIVE'
                    """,
                    [previous_asset_version_id],
                )
                if uow.cursor.rowcount != 1:
                    raise KernelError(
                        "PLANNING_SUPERSESSION_CONFLICT",
                        "previous Planning AssetVersion lifecycle changed",
                    )
            if str(row[5]) == "CANDIDATE":
                uow.cursor.execute(
                    """
                    UPDATE authority_asset_version
                    SET lifecycle='ACTIVE'
                    WHERE asset_version_id=%s
                      AND lifecycle='CANDIDATE'
                      AND eligibility='ELIGIBLE'
                    """,
                    [asset_version_id],
                )
                if uow.cursor.rowcount != 1:
                    raise KernelError(
                        "PLANNING_ACTIVATION_CONFLICT",
                        "Planning AssetVersion is no longer an eligible candidate",
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
                    "story_design_transition_operation_id": (
                        story_design_transition_operation_id
                    ),
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

    @staticmethod
    def _apply_story_design_activation_in_uow(
        uow: AuthorityUnitOfWork,
        *,
        transition_operation_id: str,
        project_id: str,
        actor_id: str,
        asset_version_id: str,
    ) -> None:

        uow.cursor.execute(
            """
            SELECT operation.status, operation.definition_name,
                   operation.definition_version, operation.project_id,
                   operation.actor_id, operation.command_payload,
                   operation.input_asset_snapshot,
                   receipt.content, receipt.content_hash,
                   output.content_hash
            FROM authority_operation AS operation
            JOIN authority_operation_output_asset AS output
              ON output.operation_id=operation.operation_id
             AND output.output_key='story_design.transition.receipt'
             AND output.role='transition_evidence'
            JOIN authority_asset_version AS receipt
              ON receipt.asset_version_id=output.asset_version_id
            JOIN authority_asset AS asset ON asset.asset_id=receipt.asset_id
            WHERE operation.operation_id=%s
              AND asset.project_id=operation.project_id
              AND asset.asset_type='story_design_transition_receipt'
            FOR SHARE OF operation, output, receipt, asset
            """,
            [transition_operation_id],
        )
        rows = uow.cursor.fetchall()
        if len(rows) != 1:
            raise KernelError(
                "STORY_DESIGN_ACTIVATION_PREPARATION_REQUIRED",
                "atomic Planning activation requires exactly one durable transition receipt",
            )
        row = rows[0]
        payload = dict(row[5])
        transition = dict(payload.get("payload") or {})
        input_snapshot = list(row[6] or ())
        receipt = dict(row[7])
        frozen_target = input_snapshot[0] if len(input_snapshot) == 1 else {}
        if (
            str(row[0]) != "SUCCEEDED"
            or str(row[1]) != STORY_DESIGN_TRANSITION_DEFINITION
            or str(row[2]) != STORY_DESIGN_TRANSITION_VERSION
            or str(row[3]) != project_id
            or str(row[4]) != actor_id
            or str(payload.get("project_id") or "") != project_id
            or str(transition.get("transition") or "") != "ACTIVATE"
            or str(transition.get("asset_version_id") or "") != asset_version_id
            or str(receipt.get("type") or "") != "StoryDesignTransitionReceipt"
            or str(receipt.get("project_id") or "") != project_id
            or str(receipt.get("asset_version_id") or "") != asset_version_id
            or str(receipt.get("transition") or "") != "ACTIVATE"
            or str(receipt.get("logical_key") or "")
            != str(transition.get("logical_key") or "")
            or str(receipt.get("generator_operation_name") or "")
            != str(transition.get("generator_operation_name") or "")
            or str(receipt.get("generator_definition_version") or "")
            != str(transition.get("generator_definition_version") or "")
            or str(receipt.get("candidate_type") or "")
            != str(transition.get("candidate_type") or "")
            or str(receipt.get("planning_scope") or "")
            != str(transition.get("planning_scope") or "")
            or str(receipt.get("design_scope") or "")
            != str(transition.get("design_scope") or "")
            or receipt.get("expected_version") != transition.get("expected_version")
            or str(receipt.get("source_kind") or "")
            != str(transition.get("source_kind") or "")
            or str(receipt.get("target_content_hash") or "")
            != str(frozen_target.get("content_hash") or "")
            or str(frozen_target.get("asset_version_id") or "") != asset_version_id
            or str(frozen_target.get("project_id") or "") != project_id
            or str(row[8]) != str(row[9])
        ):
            raise KernelError(
                "STORY_DESIGN_ACTIVATION_PREPARATION_INVALID",
                "prepared transition is not the exact successful ACTIVATE receipt",
            )
        uow.repositories.story_design.apply_transition(
            operation_id=transition_operation_id,
            project_id=project_id,
            asset_version_id=asset_version_id,
            logical_key=str(transition["logical_key"]),
            generator_operation_name=str(transition["generator_operation_name"]),
            generator_definition_version=str(
                transition["generator_definition_version"]
            ),
            candidate_type=str(transition["candidate_type"]),
            planning_scope=str(transition["planning_scope"]),
            design_scope=str(transition["design_scope"]),
            transition="ACTIVATE",
            expected_version=int(transition["expected_version"]),
            source_kind=str(transition["source_kind"]),
            evidence=dict(transition.get("evidence") or {}),
        )

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

    @staticmethod
    def _qualify_approved_migration_candidate(
        cursor: Any,
        *,
        project_id: str,
        workspace_id: str,
        asset_version_id: str,
        target_content_hash: str,
        operation_id: str,
        decision_evidence: dict[str, Any],
    ) -> None:
        lineage = require_approved_legacy_migration_lineage(
            cursor,
            project_id=project_id,
            workspace_id=workspace_id,
            target_asset_version_id=asset_version_id,
            target_content_hash=target_content_hash,
            evidence=decision_evidence,
        )
        decision_id = str(lineage["migration_decision_id"])
        item_id = str(lineage["migration_item_id"])
        validation_id = str(lineage["migration_validation_id"])
        result_hash = str(lineage["validator_result_hash"])
        validator_version = str(lineage["validator_version"])
        cursor.execute(
            """
            INSERT INTO authority_asset_qualification(
                qualification_id, asset_version_id,
                policy_version, decision, evidence
            ) VALUES (%s,%s,'approved-legacy-planning-migration-v1','ELIGIBLE',%s)
            ON CONFLICT (qualification_id) DO NOTHING
            """,
            [
                f"migration-planning-qualification:{decision_id}",
                asset_version_id,
                Jsonb(
                    {
                        "migration_decision_id": decision_id,
                        "migration_item_id": item_id,
                        "migration_validation_id": validation_id,
                        "validator_result_hash": result_hash,
                        "validator_version": validator_version,
                        "decision_operation_id": lineage["decision_operation_id"],
                        "validation_operation_id": lineage["validation_operation_id"],
                        "planning_binding_operation_id": operation_id,
                    }
                ),
            ],
        )
        cursor.execute(
            """
            UPDATE authority_asset_version
            SET lifecycle='CANDIDATE', eligibility='ELIGIBLE'
            WHERE asset_version_id=%s
              AND lifecycle='IMPORTED'
              AND eligibility='PENDING_EVALUATION'
              AND governance='CLEAR'
            """,
            [asset_version_id],
        )
        if cursor.rowcount != 1:
            raise KernelError(
                "PLANNING_MIGRATION_QUALIFICATION_CONFLICT",
                "legacy Planning candidate changed before governed promotion",
            )

    @staticmethod
    def _require_qualified_foundation_for_book_plan(
        cursor: Any,
        *,
        project_id: str,
        book_id: str,
        content: dict[str, Any],
    ) -> None:
        from novel_forge.modules.book_design_authority.domain import (
            FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
            BookDesignPayload,
        )
        from novel_forge.modules.book_design_authority.foundation import FoundationRole
        from novel_forge.storage.foundation_repositories import (
            require_current_foundation_set,
        )

        foundation = require_current_foundation_set(
            cursor,
            project_id=project_id,
            book_id=book_id,
            require_ready=True,
        )
        by_role = {
            str(item.get("role") or ""): item
            for item in content.get("frozen_inputs") or ()
            if isinstance(item, dict)
        }
        expected_roles = {
            FoundationRole.CREATIVE_FOUNDATION: "creative_foundation",
            FoundationRole.THEME_CONTRACT: "theme_contract",
            FoundationRole.ENDING_INTENT: "ending_intent",
            FoundationRole.READER_PROMISE: "reader_promise",
            FoundationRole.WORLD_BIBLE: "world_bible",
            FoundationRole.CHARACTER_CAST: "character_cast",
        }
        for role, input_role in expected_roles.items():
            frozen = by_role.get(input_role)
            binding = foundation.by_role[role]
            if frozen is None or (
                str(frozen.get("asset_version_id") or "") != binding.asset_version_id
                or str(frozen.get("content_hash") or "") != binding.content_hash
            ):
                raise KernelError(
                    "BOOK_PLAN_FOUNDATION_INPUT_STALE",
                    f"BookPlan does not freeze current {role.value}",
                )
        design_ref = by_role.get("book_design")
        if design_ref is None:
            raise KernelError(
                "BOOK_PLAN_BOOK_DESIGN_REQUIRED",
                "BookPlan requires the exact active BookDesign v5",
            )
        cursor.execute(
            """
            SELECT version.content, version.content_hash, version.schema_version,
                   version.lifecycle, version.eligibility, version.governance,
                   book.current_book_design_asset_version_id
            FROM authority_asset_version AS version
            JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
            JOIN authority_book AS book
              ON book.project_id=asset.project_id AND book.book_id=%s
            WHERE asset.project_id=%s AND version.asset_version_id=%s
            """,
            [book_id, project_id, str(design_ref.get("asset_version_id") or "")],
        )
        row = cursor.fetchone()
        if (
            row is None
            or str(row[1]) != str(design_ref.get("content_hash") or "")
            or tuple(str(item) for item in row[2:6])
            != (
                FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
                "ACTIVE",
                "ELIGIBLE",
                "CLEAR",
            )
            or str(row[6]) != str(design_ref.get("asset_version_id") or "")
        ):
            raise KernelError(
                "BOOK_PLAN_BOOK_DESIGN_STALE",
                "BookPlan BookDesign v5 input is no longer current",
            )
        design = BookDesignPayload.from_mapping(dict(row[0]))
        if design.foundation_set != foundation:
            raise KernelError(
                "BOOK_PLAN_FOUNDATION_SET_DRIFT",
                "BookPlan BookDesign v5 binds another Foundation Set",
            )

    @staticmethod
    def _require_realization_authority_lineage(
        cursor: Any,
        *,
        project_id: str,
        book_id: str,
        content: dict[str, Any],
    ) -> None:
        envelope = content.get("constraint_envelope")
        if not isinstance(envelope, dict):
            return
        generation_operation_id = str(envelope.get("generation_operation_id") or "")
        references: dict[tuple[str, str], dict[str, Any]] = {}
        for frozen in content.get("frozen_inputs") or ():
            if not isinstance(frozen, dict):
                continue
            references[
                (
                    str(frozen.get("asset_version_id") or ""),
                    str(frozen.get("role") or ""),
                )
            ] = frozen
        for manifest_name in ("world_realization", "character_realization"):
            for entity in content.get(manifest_name) or ():
                if not isinstance(entity, dict):
                    continue
                for field in (
                    "invariant_refs",
                    "structure_refs",
                    "state_ref",
                    "identity_ref",
                    "trajectory_ref",
                ):
                    raw = entity.get(field)
                    values = raw if isinstance(raw, list) else [raw]
                    for reference in values:
                        if isinstance(reference, dict):
                            references[
                                (
                                    str(reference.get("asset_version_id") or ""),
                                    str(reference.get("authority_role") or ""),
                                )
                            ] = reference
        if not references:
            return
        cursor.execute(
            """
            SELECT operation_id
            FROM authority_operation
            WHERE operation_id=%s AND project_id=%s
              AND status IN ('WAITING_GATE', 'SUCCEEDED')
            """,
            [generation_operation_id, project_id],
        )
        if cursor.fetchone() is None:
            raise KernelError(
                "PLANNING_REALIZATION_GENERATION_LINEAGE_STALE",
                "realization frozen Operation is missing or no longer admissible",
            )
        for (asset_version_id, _role), reference in references.items():
            cursor.execute(
                """
                SELECT asset.asset_type, version.content_hash, version.content,
                       version.lifecycle, version.eligibility, version.governance,
                       binding.freshness, active.binding_id
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                LEFT JOIN story_plan_binding AS binding
                  ON binding.project_id=asset.project_id
                 AND binding.book_id=%s
                 AND binding.asset_version_id=version.asset_version_id
                LEFT JOIN active_story_plan_version AS active
                  ON active.binding_id=binding.binding_id
                WHERE version.asset_version_id=%s AND asset.project_id=%s
                """,
                [book_id, asset_version_id, project_id],
            )
            row = cursor.fetchone()
            if (
                row is None
                or str(row[0]) != str(reference.get("asset_type") or "")
                or str(row[1]) != str(reference.get("content_hash") or "")
                or str(row[3]) != "ACTIVE"
                or str(row[4]) != "ELIGIBLE"
                or str(row[5]) != "CLEAR"
                or (row[6] is not None and (str(row[6]) != "CURRENT" or row[7] is None))
                or dict(row[2]).get("book_id") not in {None, "", book_id}
            ):
                raise KernelError(
                    "PLANNING_REALIZATION_AUTHORITY_REFERENCE_STALE",
                    "realization Authority identity, hash, scope, or freshness changed before binding",
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
            logical_key = str(content.get("logical_key") or "")
            for relation in content.get("arc_relations") or []:
                if not isinstance(relation, dict):
                    continue
                source_ref = str(relation.get("source_arc_ref") or "")
                target_ref = str(relation.get("target_arc_ref") or "")
                if not source_ref or not target_ref:
                    raise KernelError(
                        "PLANNING_ARC_RELATION_ENDPOINT_INVALID",
                        "Arc relation requires exact source and target endpoints",
                    )
                source_version = (
                    asset_version_id
                    if source_ref == logical_key
                    else self._resolve_arc_version(
                        cursor,
                        project_id=project_id,
                        book_id=book_id,
                        arc_ref=source_ref,
                    )
                )
                target_version = (
                    asset_version_id
                    if target_ref == logical_key
                    else self._resolve_arc_version(
                        cursor,
                        project_id=project_id,
                        book_id=book_id,
                        arc_ref=target_ref,
                    )
                )
                if source_version == target_version:
                    raise KernelError(
                        "PLANNING_ARC_RELATION_SELF_REFERENCE",
                        "Arc relation source and target must differ",
                    )
                self._dependency(
                    cursor,
                    project_id,
                    book_id,
                    source_version,
                    target_version,
                    "ARC_RELATION",
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
        policy = {
            "MARK_STALE": InvalidationPolicy.PROPAGATE,
            "MARK_IMPACTED": InvalidationPolicy.REQUALIFY,
            "REVALIDATE": InvalidationPolicy.REQUALIFY,
            "NONE": InvalidationPolicy.INFORMATIONAL,
        }[invalidation_policy]
        PostgresArtifactLineageRepository(cursor).record_edge(
            ArtifactLineageEdge(
                project_id=project_id,
                book_id=book_id,
                upstream_asset_version_id=source,
                downstream_asset_version_id=dependent,
                relationship_type=dependency_type,
                semantic_dimensions=semantic_dimensions_for(
                    (dependency_type, "planning")
                ),
                invalidation_policy=policy,
                context_fingerprint="",
                created_by_operation_id=operation_id,
            )
        )


__all__ = ["PostgresHierarchicalPlanningAuthority"]
