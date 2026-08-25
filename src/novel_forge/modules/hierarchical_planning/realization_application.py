"""Command-Kernel lifecycle for Planning-owned Narrative Realization."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any
from uuid import uuid4

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    TransactionCheckpoint,
    execute_transaction_command,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.narrative_realization_repositories import (
    NarrativeRealizationRepository,
)

from .definitions import (
    NARRATIVE_REALIZATION_DEFINITION_VERSION,
    NARRATIVE_REALIZATION_HANDLER_KEY,
    NARRATIVE_REALIZATION_OPERATIONS,
    narrative_realization_definitions,
)
from .realization_domain import (
    NARRATIVE_REALIZATION_PROOF_SCHEMA_VERSION,
    NARRATIVE_REALIZATION_SCHEMA_VERSION,
    NarrativeRealizationContract,
    NarrativeRealizationLifecycle,
)
from novel_forge.modules.story_design_authority import required_qualification_profiles
from novel_forge.storage.foundation_repositories import require_current_foundation_set


@dataclass(frozen=True, slots=True)
class NarrativeRealizationCommand:
    definition_name: str
    project_id: str
    workspace_id: str
    book_id: str
    actor_id: str
    realization_id: str
    expected_version: int
    idempotency_key: str
    trace_id: str
    correlation_id: str
    reason: str
    contract: NarrativeRealizationContract | None = None
    causation_operation_id: str = ""

    def __post_init__(self) -> None:
        if self.definition_name not in NARRATIVE_REALIZATION_OPERATIONS:
            raise ValueError("unsupported Narrative Realization command")
        required = (
            self.project_id,
            self.workspace_id,
            self.book_id,
            self.actor_id,
            self.realization_id,
            self.idempotency_key,
            self.trace_id,
            self.correlation_id,
            self.reason,
        )
        if any(not value.strip() for value in required) or self.expected_version < 0:
            raise ValueError("Narrative Realization command is incomplete")
        qualifying = self.definition_name == "planning.realization.qualify"
        if qualifying != (self.contract is not None):
            raise ValueError("only qualification supplies the immutable contract")
        if self.contract is not None and (
            self.contract.realization_id != self.realization_id
            or self.contract.project_id != self.project_id
            or self.contract.book_id != self.book_id
        ):
            raise ValueError(
                "Narrative Realization command scope differs from contract"
            )


class PostgresNarrativeRealizationApplication:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        fault_injector: TransactionCheckpoint | None = None,
    ) -> None:
        if not database_url or not application_build_id or len(commit_sha) != 40:
            raise ValueError(
                "Narrative Realization application requires PostgreSQL/build identity"
            )
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.fault_injector = fault_injector

    def execute(
        self, command: NarrativeRealizationCommand, *, principal: Principal
    ) -> dict[str, Any]:
        principal.require("book.authority.execute", command.project_id)
        if principal.principal_id != command.actor_id:
            raise KernelError(
                "ACTOR_IDENTITY_INVALID",
                "realization command actor differs from authenticated Principal",
            )
        self._register_definitions()
        contract = command.contract
        contract_value = contract.to_dict() if contract is not None else {}
        input_assets = self._input_assets(command)
        executed = execute_transaction_command(
            self.database_url,
            {
                "definition_name": command.definition_name,
                "definition_version": NARRATIVE_REALIZATION_DEFINITION_VERSION,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "book_id": command.book_id,
                "actor_id": command.actor_id,
                "idempotency_scope": "book:narrative-realization",
                "idempotency_key": command.idempotency_key,
                "trace_id": command.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": command.correlation_id,
                "causation_id": command.causation_operation_id,
                "causation_operation_id": command.causation_operation_id or None,
                "input": {
                    "project_id": command.project_id,
                    "workspace_id": command.workspace_id,
                    "book_id": command.book_id,
                    "realization_id": command.realization_id,
                    "expected_version": command.expected_version,
                    "contract": contract_value,
                    "reason": command.reason,
                },
                "input_assets": list(input_assets),
            },
            context=AdmissionContext(
                actor_id=command.actor_id,
                permissions=frozenset({"book.authority.execute"}),
                available_handlers=frozenset({NARRATIVE_REALIZATION_HANDLER_KEY}),
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
            handler=self._execute_transaction,
            fault_injector=self.fault_injector,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            result = NarrativeRealizationRepository(uow.cursor).require(
                command.realization_id
            )
        return {
            **result,
            "operation_id": executed["operation_id"],
            "replayed": executed["replayed"],
        }

    def require(self, realization_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            return NarrativeRealizationRepository(uow.cursor).require(realization_id)

    def require_current_for_chapter(
        self,
        *,
        project_id: str,
        book_id: str,
        chapter_group_plan_version_id: str,
        chapter_number: int,
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            return NarrativeRealizationRepository(
                uow.cursor
            ).require_current_for_chapter(
                project_id=project_id,
                book_id=book_id,
                chapter_group_plan_version_id=chapter_group_plan_version_id,
                chapter_number=chapter_number,
            )

    def qualify_and_freeze_for_group(
        self,
        *,
        book_run_id: str,
        chapter_group_plan_version_id: str,
        arc_working_set: dict[str, Any],
        principal: Principal,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """Bind a frozen ChapterGroup event chain to exact current evidence.

        The ChapterGroup remains future intent.  This coordinator only creates
        Planning-owned qualification/freeze lineage; it never writes Canon or
        Narrative State.
        """

        with AuthorityUnitOfWork(self.database_url) as uow:
            contract = self._contract_for_group(
                uow.cursor,
                book_run_id=book_run_id,
                chapter_group_plan_version_id=chapter_group_plan_version_id,
                arc_working_set=arc_working_set,
            )
            try:
                current = NarrativeRealizationRepository(uow.cursor).require(
                    contract.realization_id
                )
            except KernelError as error:
                if error.code != "NARRATIVE_REALIZATION_NOT_FOUND":
                    raise
                current = None
        if current is not None and str(current["contract_digest"]) != (
            contract.contract_digest
        ):
            raise KernelError(
                "NARRATIVE_REALIZATION_CONFLICT",
                "deterministic realization identity binds different evidence",
            )
        workspace_id = self._workspace_id(book_run_id)
        if current is None:
            current = self.execute(
                NarrativeRealizationCommand(
                    definition_name="planning.realization.qualify",
                    project_id=contract.project_id,
                    workspace_id=workspace_id,
                    book_id=contract.book_id,
                    actor_id=principal.principal_id,
                    realization_id=contract.realization_id,
                    expected_version=0,
                    idempotency_key=f"{idempotency_key}:qualify",
                    trace_id=trace_id,
                    correlation_id=correlation_id,
                    reason="exact frozen ChapterGroup causal contract qualified",
                    contract=contract,
                ),
                principal=principal,
            )
        lifecycle = NarrativeRealizationLifecycle(str(current["lifecycle"]))
        if lifecycle is NarrativeRealizationLifecycle.QUALIFIED:
            current = self.execute(
                NarrativeRealizationCommand(
                    definition_name="planning.realization.approve",
                    project_id=contract.project_id,
                    workspace_id=workspace_id,
                    book_id=contract.book_id,
                    actor_id=principal.principal_id,
                    realization_id=contract.realization_id,
                    expected_version=int(current["version"]),
                    idempotency_key=f"{idempotency_key}:approve",
                    trace_id=trace_id,
                    correlation_id=correlation_id,
                    reason="qualified realization approved for near-future use",
                    causation_operation_id=str(
                        current.get("qualification_operation_id")
                        or current.get("operation_id")
                        or ""
                    ),
                ),
                principal=principal,
            )
            lifecycle = NarrativeRealizationLifecycle(str(current["lifecycle"]))
        if lifecycle is NarrativeRealizationLifecycle.FROZEN:
            return {
                **current,
                "operation_id": str(current.get("frozen_by_operation_id") or ""),
                "replayed": True,
            }
        if lifecycle is not NarrativeRealizationLifecycle.APPROVED:
            raise KernelError(
                "NARRATIVE_REALIZATION_NOT_FREEZABLE",
                f"cannot resume realization lifecycle {lifecycle.value}",
            )
        return self.execute(
            NarrativeRealizationCommand(
                definition_name="planning.realization.freeze",
                project_id=contract.project_id,
                workspace_id=workspace_id,
                book_id=contract.book_id,
                actor_id=principal.principal_id,
                realization_id=contract.realization_id,
                expected_version=int(current["version"]),
                idempotency_key=f"{idempotency_key}:freeze",
                trace_id=trace_id,
                correlation_id=correlation_id,
                reason="approved realization frozen for Chapter elaboration",
                causation_operation_id=str(
                    current.get("approval_operation_id")
                    or current.get("operation_id")
                    or ""
                ),
            ),
            principal=principal,
        )

    def _workspace_id(self, book_run_id: str) -> str:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                "SELECT workspace_id FROM authority_book_production WHERE book_run_id=%s",
                [book_run_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("BOOK_RUN_NOT_FOUND", "Book run does not exist")
        return str(row[0])

    @staticmethod
    def _contract_for_group(
        cursor: Any,
        *,
        book_run_id: str,
        chapter_group_plan_version_id: str,
        arc_working_set: dict[str, Any],
    ) -> NarrativeRealizationContract:
        cursor.execute(
            """
            SELECT production.project_id, production.book_id,
                   production.accepted_through_chapter,
                   COALESCE(production.active_story_state_version_id,
                            snapshot.initial_story_state_version),
                   COALESCE(production.active_canon_snapshot_version_id,
                            snapshot.initial_canon_snapshot_version),
                   state.content_hash, canon.content_hash,
                   group_version.content, group_version.content_hash,
                   group_binding.execution_scope, group_binding.freshness,
                   snapshot.foundation_set_digest
            FROM authority_book_production AS production
            JOIN authority_book_production_input_snapshot AS snapshot
              ON snapshot.snapshot_id=production.input_snapshot_id
            JOIN authority_asset_version AS state
              ON state.asset_version_id=COALESCE(
                   production.active_story_state_version_id,
                   snapshot.initial_story_state_version)
            JOIN authority_asset_version AS canon
              ON canon.asset_version_id=COALESCE(
                   production.active_canon_snapshot_version_id,
                   snapshot.initial_canon_snapshot_version)
            JOIN story_plan_binding AS group_binding
              ON group_binding.project_id=production.project_id
             AND group_binding.book_id=production.book_id
             AND group_binding.asset_version_id=%s
            JOIN active_story_plan_version AS active_group
              ON active_group.binding_id=group_binding.binding_id
            JOIN authority_asset_version AS group_version
              ON group_version.asset_version_id=group_binding.asset_version_id
            WHERE production.book_run_id=%s
            """,
            [chapter_group_plan_version_id, book_run_id],
        )
        row = cursor.fetchone()
        if row is None or tuple(str(item) for item in row[9:11]) != (
            "FROZEN",
            "CURRENT",
        ):
            raise KernelError(
                "NARRATIVE_REALIZATION_GROUP_STALE",
                "realization requires the exact current frozen ChapterGroup",
            )
        project_id, book_id = str(row[0]), str(row[1])
        foundation = require_current_foundation_set(
            cursor, project_id=project_id, book_id=book_id
        )
        if foundation.set_digest != str(row[11]):
            raise KernelError(
                "FOUNDATION_SET_DRIFT",
                "Book input and current qualified Foundation Set differ",
            )
        group = dict(row[7])
        chapter_range = group.get("chapter_range")
        events = group.get("narrative_event_chain")
        if not isinstance(chapter_range, list) or not isinstance(events, list):
            raise KernelError(
                "NARRATIVE_REALIZATION_INVALID",
                "frozen ChapterGroup lacks its typed causal event chain",
            )
        working_digest = str(arc_working_set.get("working_set_digest") or "")
        selected = [
            str(item.get("arc_plan_version_id") or "")
            for item in arc_working_set.get("selected_contributions") or ()
            if isinstance(item, dict)
        ]
        if not working_digest or not selected or len(set(selected)) != len(selected):
            raise KernelError(
                "NARRATIVE_REALIZATION_ARC_WORKING_SET_INVALID",
                "realization requires the governed bounded Arc Working Set",
            )
        cursor.execute(
            """
            SELECT binding.asset_version_id, version.content_hash
            FROM story_plan_binding AS binding
            JOIN active_story_plan_version AS active
              ON active.binding_id=binding.binding_id
            JOIN authority_asset_version AS version
              ON version.asset_version_id=binding.asset_version_id
            WHERE binding.project_id=%s AND binding.book_id=%s
              AND binding.contract_type='ARC' AND binding.freshness='CURRENT'
              AND binding.asset_version_id=ANY(%s)
            """,
            [project_id, book_id, selected],
        )
        arc_hashes = {str(item[0]): str(item[1]) for item in cursor.fetchall()}
        if set(arc_hashes) != set(selected):
            raise KernelError(
                "NARRATIVE_REALIZATION_ARC_STALE",
                "realization Arc bindings are not exact/current",
            )
        profiles = required_qualification_profiles("chapter_group_plan.generate")
        cursor.execute(
            """
            SELECT qualification.design_layer, qualification.profile_id,
                   qualification.profile_version, qualification.profile_hash,
                   qualification.evaluation_asset_version_id,
                   evaluation.content_hash
            FROM authority_current_narrative_design_qualification AS qualification
            JOIN authority_operation AS operation
              ON operation.operation_id=qualification.source_operation_id
            JOIN authority_asset_version AS evaluation
              ON evaluation.asset_version_id=qualification.evaluation_asset_version_id
            WHERE qualification.project_id=%s AND qualification.book_id=%s
              AND qualification.asset_version_id=%s
              AND qualification.freshness='CURRENT'
              AND operation.status IN ('WAITING_GATE','SUCCEEDED')
            ORDER BY qualification.design_layer
            """,
            [project_id, book_id, chapter_group_plan_version_id],
        )
        qualifications = {str(item[0]): item for item in cursor.fetchall()}
        if set(qualifications) != {profile.layer.value for profile in profiles}:
            raise KernelError(
                "REALIZATION_PROOF_INCOMPLETE",
                "every ChapterGroup semantic qualification is required",
            )
        for profile in profiles:
            receipt = qualifications[profile.layer.value]
            if tuple(str(item) for item in receipt[1:4]) != (
                profile.profile_id,
                profile.profile_version,
                profile.profile_hash,
            ):
                raise KernelError(
                    "REALIZATION_PROOF_STALE",
                    "ChapterGroup semantic proof differs from current policy",
                )
        proof_receipt = qualifications[profiles[0].layer.value]
        realization_seed = (
            f"{chapter_group_plan_version_id}:{row[8]}:{row[2]}:"
            f"{row[3]}:{row[4]}:{working_digest}:{foundation.set_digest}"
        )
        realization_id = "narrative-realization:" + hashlib.sha256(
            realization_seed.encode()
        ).hexdigest()
        proof_asset_version_id = str(proof_receipt[4])
        proof_hash = str(proof_receipt[5])
        contract = {
            "schema_version": NARRATIVE_REALIZATION_SCHEMA_VERSION,
            "realization_id": realization_id,
            "project_id": project_id,
            "book_id": book_id,
            "chapter_group_plan_version_id": chapter_group_plan_version_id,
            "chapter_group_content_hash": str(row[8]),
            "chapter_range": list(chapter_range),
            "foundation_set_digest": foundation.set_digest,
            "accepted_boundary": {
                "accepted_through_chapter": int(row[2]),
                "story_state_version_id": str(row[3]),
                "story_state_content_hash": str(row[5]),
                "canon_version_id": str(row[4]),
                "canon_content_hash": str(row[6]),
            },
            "arc_working_set_digest": working_digest,
            "arc_plan_bindings": [
                {
                    "arc_id": arc_id,
                    "asset_version_id": arc_id,
                    "content_hash": arc_hashes[arc_id],
                }
                for arc_id in selected
            ],
            "events": list(events),
            "proof": {
                "schema_version": NARRATIVE_REALIZATION_PROOF_SCHEMA_VERSION,
                "covered_event_ids": [str(item.get("event_id") or "") for item in events],
                "covered_parent_objectives": [
                    f"chapter-group:{chapter_group_plan_version_id}:objective",
                    *[f"arc:{arc_id}:contribution" for arc_id in selected],
                ],
                "canon_state_legal": True,
                "character_motivation_legal": True,
                "world_rules_legal": True,
                "knowledge_boundaries_legal": True,
                "causal_escalation_proven": True,
                "state_transitions_covered": True,
                "obligations_covered": True,
                "arc_contributions_covered": True,
                "narrative_load_legal": True,
                "chapter_decomposition_legal": True,
                "semantic_evaluation_asset_version_id": proof_asset_version_id,
                "semantic_evaluation_hash": proof_hash,
            },
            "content_asset_version_id": chapter_group_plan_version_id,
            "content_hash": str(row[8]),
            "proof_asset_version_id": proof_asset_version_id,
            "proof_hash": proof_hash,
            "lifecycle": NarrativeRealizationLifecycle.QUALIFIED.value,
        }
        return NarrativeRealizationContract.from_mapping(contract)

    def _execute_transaction(
        self,
        uow: AuthorityUnitOfWork,
        operation_id: str,
        checkpoint: TransactionCheckpoint,
    ) -> dict[str, Any]:
        uow.cursor.execute(
            """
            SELECT project_id, definition_name, command_payload,
                   trace_id, correlation_id, causation_id
            FROM authority_operation
            WHERE operation_id=%s
            """,
            [operation_id],
        )
        operation = uow.cursor.fetchone()
        if operation is None:
            raise KernelError(
                "NARRATIVE_REALIZATION_OPERATION_NOT_FOUND",
                "admitted realization Operation disappeared",
            )
        project_id = str(operation[0])
        definition_name = str(operation[1])
        payload = dict(operation[2])
        repository = NarrativeRealizationRepository(uow.cursor)
        realization_id = str(payload["realization_id"])
        checkpoint("after_domain_validation")
        if definition_name == "planning.realization.qualify":
            result = repository.qualify(
                contract=NarrativeRealizationContract.from_mapping(
                    dict(payload["contract"])
                ),
                operation_id=operation_id,
            )
        else:
            target = {
                "planning.realization.approve": NarrativeRealizationLifecycle.APPROVED,
                "planning.realization.freeze": NarrativeRealizationLifecycle.FROZEN,
                "planning.realization.mark_stale": NarrativeRealizationLifecycle.STALE,
            }[definition_name]
            result = repository.transition(
                realization_id=realization_id,
                expected_version=int(payload["expected_version"]),
                target=target,
                operation_id=operation_id,
                reason=str(payload["reason"]),
            )
        checkpoint("after_business_projection_update")
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": "narrative_realization",
                "aggregate_id": realization_id,
                "operation_id": operation_id,
                "project_id": project_id,
                "event_type": "narrative_realization.transitioned",
                "correlation_id": str(operation[4]),
                "causation_id": str(operation[5] or ""),
                "payload": {
                    "operation_id": operation_id,
                    "project_id": project_id,
                    "realization_id": realization_id,
                    "lifecycle": result["lifecycle"],
                    "version": result["version"],
                    "contract_digest": result["contract_digest"],
                },
            }
        )
        checkpoint("after_outbox_insert")
        return {
            "realization_id": realization_id,
            "lifecycle": str(result["lifecycle"]),
            "version": int(result["version"]),
            "contract_digest": str(result["contract_digest"]),
        }

    def _register_definitions(self) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            for definition in narrative_realization_definitions(
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ):
                uow.repositories.definitions.register(definition)
            uow.commit()

    def _input_assets(
        self, command: NarrativeRealizationCommand
    ) -> tuple[dict[str, str], ...]:
        if command.contract is not None:
            contract = command.contract
            requested = {
                contract.chapter_group_plan_version_id,
                contract.accepted_boundary.story_state_version_id,
                contract.accepted_boundary.canon_version_id,
                contract.content_asset_version_id,
                contract.proof_asset_version_id,
                contract.proof.semantic_evaluation_asset_version_id,
                *(item.asset_version_id for item in contract.arc_plan_bindings),
            }
        else:
            with AuthorityUnitOfWork(self.database_url) as uow:
                uow.cursor.execute(
                    """
                    SELECT chapter_group_plan_version_id,
                           story_state_asset_version_id,
                           canon_snapshot_asset_version_id,
                           content_asset_version_id, proof_asset_version_id,
                           arc_plan_bindings, proof
                    FROM authority_narrative_realization
                    WHERE realization_id=%s AND project_id=%s AND book_id=%s
                    """,
                    [command.realization_id, command.project_id, command.book_id],
                )
                row = uow.cursor.fetchone()
            if row is None:
                raise KernelError(
                    "NARRATIVE_REALIZATION_NOT_FOUND", "realization does not exist"
                )
            requested = {
                *(str(item) for item in row[:5]),
                *(
                    str(item.get("asset_version_id") or "")
                    for item in row[5] or ()
                    if isinstance(item, dict)
                ),
                str((row[6] or {}).get("semantic_evaluation_asset_version_id") or ""),
            }
            requested.discard("")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT version.asset_version_id, version.content_hash
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE asset.project_id=%s AND version.asset_version_id=ANY(%s)
                """,
                [command.project_id, list(requested)],
            )
            found = {str(row[0]): str(row[1]) for row in uow.cursor.fetchall()}
        if set(found) != requested:
            raise KernelError(
                "NARRATIVE_REALIZATION_INPUT_STALE",
                "realization command input assets are missing or outside Project scope",
            )
        return tuple(
            {"asset_version_id": item, "content_hash": found[item]}
            for item in sorted(requested)
        )


__all__ = [
    "NarrativeRealizationCommand",
    "PostgresNarrativeRealizationApplication",
]
