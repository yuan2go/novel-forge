from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from uuid import uuid4

from novel_forge.modules.authority_security import (
    Principal,
    require_worker_scoped_auto_decision,
)
from novel_forge.modules.book_design_authority.definitions import (
    BOOK_DESIGN_DEFINITION_VERSION,
    BOOK_DESIGN_HANDLER_KEY,
    BOOK_DESIGN_OPERATIONS,
    book_design_definitions,
)
from novel_forge.modules.book_design_authority.domain import (
    BookDesignPayload,
    BookScope,
    EVOLUTION_BOOK_DESIGN_SCHEMA_VERSION,
    FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
)
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    TransactionCheckpoint,
    execute_transaction_command,
)
from novel_forge.modules.story_design_authority.evaluation_runtime import (
    NarrativeSemanticEvaluationApplication,
    NarrativeSemanticEvaluationCommand,
    NarrativeSemanticEvaluationExecutionPort,
)
from novel_forge.modules.story_design_authority.qualification import (
    required_qualification_profiles,
    scripted_qualification,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.book_design_authority_repositories import (
    BookDesignAuthorityRepository,
)


@dataclass(frozen=True, slots=True)
class ApprovedBookDesignMigrationEvidence:
    migration_run_id: str
    migration_item_id: str
    migration_decision_id: str
    migration_validation_id: str
    archival_asset_version_id: str
    archival_content_hash: str
    source_hash: str
    validator_result_hash: str
    validator_version: str
    item_version: int

    def __post_init__(self) -> None:
        identities = (
            self.migration_run_id,
            self.migration_item_id,
            self.migration_decision_id,
            self.migration_validation_id,
            self.archival_asset_version_id,
            self.validator_version,
        )
        hashes = (
            self.archival_content_hash,
            self.source_hash,
            self.validator_result_hash,
        )
        if (
            any(not value.strip() for value in identities)
            or any(
                len(value) != 71 or not value.startswith("sha256:") for value in hashes
            )
            or self.item_version <= 0
        ):
            raise ValueError("approved BookDesign migration evidence is incomplete")


@dataclass(frozen=True, slots=True)
class BookDesignAuthorityCommand:
    definition_name: str
    project_id: str
    workspace_id: str
    book_id: str
    actor_id: str
    service_identity: str
    idempotency_key: str
    trace_id: str
    correlation_id: str
    payload: dict[str, Any]
    expected_book_version: int = 0
    expected_current_design_asset_version_id: str = ""
    target_asset_version_id: str = ""
    migration_evidence: ApprovedBookDesignMigrationEvidence | None = None

    def __post_init__(self) -> None:
        if self.definition_name not in BOOK_DESIGN_OPERATIONS:
            raise ValueError(
                f"unsupported BookDesign Authority operation: {self.definition_name}"
            )
        for field in (
            "project_id",
            "workspace_id",
            "book_id",
            "actor_id",
            "service_identity",
            "idempotency_key",
            "trace_id",
            "correlation_id",
        ):
            if not str(getattr(self, field)).strip():
                raise ValueError(f"{field} is required")
        if self.expected_book_version < 0:
            raise ValueError("expected_book_version cannot be negative")
        if self.migration_evidence is not None and (
            self.definition_name != "book_design.activate"
            or self.service_identity != "legacy-migration-authority"
        ):
            raise ValueError(
                "approved migration evidence is valid only for Legacy BookDesign activation"
            )


class BookDesignAuthorityApplication:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        fault_injector: TransactionCheckpoint | None = None,
        semantic_evaluation_execution_port: NarrativeSemanticEvaluationExecutionPort
        | None = None,
        allow_scripted_evaluation_fixture: bool = False,
        narrative_evaluator_principal: Principal | None = None,
        allow_approved_archival_migration: bool = False,
    ) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.fault_injector = fault_injector
        self.allow_scripted_evaluation_fixture = allow_scripted_evaluation_fixture
        self.narrative_evaluator_principal = narrative_evaluator_principal
        self.allow_approved_archival_migration = allow_approved_archival_migration
        self.semantic_evaluation = NarrativeSemanticEvaluationApplication(
            database_url,
            application_build_id=application_build_id,
            commit_sha=commit_sha,
            worker_id="book-design-semantic-evaluation-worker",
            execution_port=semantic_evaluation_execution_port,
            allow_scripted_fixture=allow_scripted_evaluation_fixture,
        )

    def execute(
        self, command: BookDesignAuthorityCommand, *, principal: Principal | None = None
    ) -> dict[str, Any]:
        actor_id = command.actor_id
        if principal is not None:
            principal.require("book_design.authority.execute", command.project_id)
            if principal.principal_id != command.actor_id:
                raise KernelError(
                    "ACTOR_IDENTITY_INVALID",
                    "BookDesign actor differs from authenticated Principal",
                )
            actor_id = principal.principal_id
        self._register_definitions()
        migration_lineage = (
            self._require_approved_migration_evidence(command)
            if command.migration_evidence is not None
            else None
        )
        from .author_supervision import proposed_supervision, approved_book_design_receipt
        from novel_forge.modules.production_execution.author_supervision import selected_book_supervision
        supervision = None
        with AuthorityUnitOfWork(self.database_url) as uow:
            if command.definition_name == "book_design.propose":
                uow.cursor.execute("""SELECT command_payload FROM authority_operation
                    WHERE project_id=%s AND idempotency_scope='book:design' AND idempotency_key=%s""",
                    [command.project_id, command.idempotency_key])
                replay = uow.cursor.fetchone()
                supervision = (replay[0].get("payload", {}).get("_author_supervision") if replay else
                    selected_book_supervision(uow.cursor, project_id=command.project_id, book_id=command.book_id))
            elif command.definition_name in {"book_design.decide", "book_design.activate"}:
                supervision = proposed_supervision(uow.cursor, project_id=command.project_id,
                    book_id=command.book_id, asset_version_id=command.target_asset_version_id)
                if supervision and command.definition_name == "book_design.activate":
                    approved_book_design_receipt(uow.cursor, project_id=command.project_id,
                        book_id=command.book_id, asset_version_id=command.target_asset_version_id)
        if supervision and command.definition_name == "book_design.decide":
            from novel_forge.modules.authority_security import PrincipalType
            if principal is None or principal.principal_type is not PrincipalType.LOCAL_OPERATOR or principal.principal_id != supervision["author_id"]:
                raise PermissionError("Supervised BookDesign requires the authenticated scoped author")
            if not str(command.payload.get("reason") or "").strip():
                raise KernelError("AUTHOR_SUPERVISION_EXACT_REVIEW_REQUIRED", "Author decision needs a reason")
        if "_author_supervision" in command.payload:
            raise KernelError("AUTHOR_SUPERVISION_POLICY_UNTRUSTED", "Book supervision is resolved by the Authority")
        if (
            command.definition_name == "book_design.activate"
            and not self.allow_scripted_evaluation_fixture
            and migration_lineage is None
            and supervision is None
        ):
            self._require_model_provider_qualification(
                project_id=command.project_id,
                book_id=command.book_id,
                asset_version_id=command.target_asset_version_id,
            )
        command_input = {
            "project_id": command.project_id,
            "workspace_id": command.workspace_id,
            "book_id": command.book_id,
            "service_identity": command.service_identity,
            "expected_book_version": command.expected_book_version,
            "expected_current_design_asset_version_id": command.expected_current_design_asset_version_id,
            "target_asset_version_id": command.target_asset_version_id,
            "payload": {**dict(command.payload), **({"_author_supervision": supervision} if supervision else {})},
            "migration_evidence": (
                asdict(command.migration_evidence)
                if command.migration_evidence is not None
                else {}
            ),
        }
        input_assets: list[dict[str, str]] = []
        target_content_hash = ""
        if command.target_asset_version_id:
            with AuthorityUnitOfWork(self.database_url) as uow:
                uow.cursor.execute(
                    """
                    SELECT version.content_hash
                    FROM authority_asset_version AS version
                    JOIN authority_asset AS asset ON asset.asset_id = version.asset_id
                    WHERE version.asset_version_id = %s AND asset.project_id = %s
                    """,
                    [command.target_asset_version_id, command.project_id],
                )
                row = uow.cursor.fetchone()
                if row is None:
                    raise KernelError(
                        "BOOK_DESIGN_CANDIDATE_NOT_FOUND",
                        "target AssetVersion is outside project scope",
                    )
                target_content_hash = str(row[0])
                input_assets.append(
                    {
                        "asset_version_id": command.target_asset_version_id,
                        "content_hash": target_content_hash,
                    }
                )
        if (
            principal is not None
            and command.definition_name in {"book_design.decide", "book_design.activate"}
        ):
            require_worker_scoped_auto_decision(
                principal=principal,
                evidence=command.payload.get("formation_auto_decision"),
                project_id=command.project_id,
                workspace_id=command.workspace_id,
                book_id=command.book_id,
                action={
                    "book_design.decide": "book_design.candidate.decide",
                    "book_design.activate": "book_design.candidate.activate",
                }[command.definition_name],
                candidate_asset_version_id=command.target_asset_version_id,
                candidate_content_hash=target_content_hash,
            )
        if migration_lineage is not None:
            input_assets.append(
                {
                    "asset_version_id": migration_lineage["archival_asset_version_id"],
                    "content_hash": migration_lineage["archival_content_hash"],
                }
            )
        context = AdmissionContext(
            actor_id=actor_id,
            permissions=frozenset({"book_design.authority.execute"}),
            available_handlers=frozenset({BOOK_DESIGN_HANDLER_KEY}),
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )
        result = execute_transaction_command(
            self.database_url,
            {
                "definition_name": command.definition_name,
                "definition_version": BOOK_DESIGN_DEFINITION_VERSION,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "actor_id": actor_id,
                "idempotency_scope": "book:design",
                "idempotency_key": command.idempotency_key,
                "trace_id": command.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": command.correlation_id,
                "causation_id": (
                    migration_lineage["migration_decision_id"]
                    if migration_lineage is not None
                    else ""
                ),
                "causation_operation_id": (
                    migration_lineage["decision_operation_id"]
                    if migration_lineage is not None
                    else None
                ),
                "input": command_input,
                "input_assets": input_assets,
            },
            context=context,
            handler=self._execute_transaction,
            fault_injector=self.fault_injector,
        )
        if (
            command.definition_name == "book_design.propose"
            and supervision is None
            and self.narrative_evaluator_principal is not None
            and (semantic_port := self.semantic_evaluation.execution_port) is not None
        ):
            candidate_id = str(result.get("asset_version_id") or "")
            with AuthorityUnitOfWork(self.database_url) as uow:
                uow.cursor.execute(
                    """
                    SELECT content_hash
                    FROM authority_asset_version AS version
                    JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                    WHERE version.asset_version_id=%s AND asset.project_id=%s
                    """,
                    [candidate_id, command.project_id],
                )
                row = uow.cursor.fetchone()
            if row is None:
                raise KernelError(
                    "BOOK_DESIGN_CANDIDATE_NOT_FOUND",
                    "new BookDesign candidate is not readable for evaluation",
                )
            real_provider = bool(
                getattr(semantic_port, "real_provider_execution", False)
            )
            if not real_provider and not self.allow_scripted_evaluation_fixture:
                raise KernelError(
                    "NARRATIVE_EVALUATION_REAL_PROVIDER_REQUIRED",
                    "BookDesign production evaluation has no real Provider route",
                )
            evaluation = self.evaluate_semantics(
                NarrativeSemanticEvaluationCommand(
                    project_id=command.project_id,
                    workspace_id=command.workspace_id,
                    book_id=command.book_id,
                    actor_id=self.narrative_evaluator_principal.principal_id,
                    candidate_asset_version_id=candidate_id,
                    generation_operation_id=str(result.get("operation_id") or ""),
                    generator_operation_name="book_design.propose",
                    candidate_content_hash=str(row[0]),
                    evaluator_execution_class=(
                        "MODEL_PROVIDER" if real_provider else "SCRIPTED_FIXTURE"
                    ),
                    evaluation=(
                        None
                        if real_provider
                        else scripted_qualification("book_design.propose")
                    ),
                    idempotency_key=f"{command.idempotency_key}:semantic-evaluation",
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                ),
                principal=self.narrative_evaluator_principal,
            )
            return {**result, "semantic_evaluation": evaluation}
        return result

    def _require_approved_migration_evidence(
        self, command: BookDesignAuthorityCommand
    ) -> dict[str, str]:
        if (
            not self.allow_approved_archival_migration
            or command.service_identity != "legacy-migration-authority"
            or command.migration_evidence is None
        ):
            raise KernelError(
                "BOOK_DESIGN_MIGRATION_EVIDENCE_FORBIDDEN",
                "Legacy BookDesign activation is not enabled with typed evidence",
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            return self._require_migration_evidence_in_uow(
                uow,
                project_id=command.project_id,
                workspace_id=command.workspace_id,
                evidence=command.migration_evidence,
            )

    @staticmethod
    def _require_migration_evidence_in_uow(
        uow: AuthorityUnitOfWork,
        *,
        project_id: str,
        workspace_id: str,
        evidence: ApprovedBookDesignMigrationEvidence,
    ) -> dict[str, str]:
        uow.cursor.execute(
            """
            SELECT decision.operation_id, decision.decision,
                   decision.source_hash, decision.target_asset_version_id,
                   decision.expected_item_version,
                   decision.validation_result_hash,
                   validation.status, validation.source_hash,
                   validation.target_asset_version_id,
                   validation.item_version, validation.result_hash,
                   validation.validator_version,
                   item.migration_run_id, item.project_id,
                   COALESCE(item.workspace_id,''), item.source_hash,
                   item.target_asset_version_id, item.target_content_hash,
                   item.item_version
            FROM authority_legacy_migration_decision AS decision
            JOIN authority_legacy_migration_validation AS validation
              ON validation.migration_validation_id=
                 decision.migration_validation_id
            JOIN authority_legacy_migration_item AS item
              ON item.migration_item_id=decision.migration_item_id
            WHERE decision.migration_decision_id=%s
              AND decision.migration_item_id=%s
              AND decision.migration_validation_id=%s
            FOR SHARE OF decision, validation, item
            """,
            [
                evidence.migration_decision_id,
                evidence.migration_item_id,
                evidence.migration_validation_id,
            ],
        )
        row = uow.cursor.fetchone()
        expected = (
            "APPROVE",
            evidence.source_hash,
            evidence.archival_asset_version_id,
            evidence.item_version - 1,
            evidence.validator_result_hash,
            "PASS",
            evidence.source_hash,
            evidence.archival_asset_version_id,
            evidence.item_version - 1,
            evidence.validator_result_hash,
            evidence.validator_version,
            evidence.migration_run_id,
            project_id,
            workspace_id,
            evidence.source_hash,
            evidence.archival_asset_version_id,
            evidence.archival_content_hash,
            evidence.item_version,
        )
        if row is None or tuple(row[1:]) != expected or not str(row[0] or ""):
            raise KernelError(
                "BOOK_DESIGN_MIGRATION_EVIDENCE_STALE",
                "Legacy BookDesign activation evidence is missing, stale, or outside scope",
            )
        return {
            "decision_operation_id": str(row[0]),
            "migration_decision_id": evidence.migration_decision_id,
            "archival_asset_version_id": evidence.archival_asset_version_id,
            "archival_content_hash": evidence.archival_content_hash,
        }

    def _require_model_provider_qualification(
        self,
        *,
        project_id: str,
        book_id: str,
        asset_version_id: str,
    ) -> None:
        expected = {
            profile.layer.value: profile
            for profile in required_qualification_profiles("book_design.propose")
        }
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT design_layer, profile_id, profile_version, profile_hash,
                       capability_id, skill_ref, evaluation_operation_id,
                       qualification_hash
                FROM authority_narrative_design_qualification
                WHERE project_id=%s AND book_id=%s AND asset_version_id=%s
                  AND qualification_status='PASS'
                  AND trust_boundary='INDEPENDENT'
                  AND evaluator_execution_class='MODEL_PROVIDER'
                  AND provider_model_call_asset_version_id IS NOT NULL
                  AND provider_model_call_content_hash IS NOT NULL
                  AND provider_evidence_hash IS NOT NULL
                  AND provider_result_hash IS NOT NULL
                  AND provider_route_snapshot_id IS NOT NULL
                """,
                [project_id, book_id, asset_version_id],
            )
            rows = uow.cursor.fetchall()
        by_layer = {str(row[0]): row for row in rows}
        operation_ids = {str(row[6]) for row in rows}
        qualification_hashes = {str(row[7]) for row in rows}
        if not rows:
            raise KernelError(
                "NARRATIVE_EVALUATION_REAL_PROVIDER_REQUIRED",
                "BookDesign activation requires current real-Provider qualification",
            )
        stale = set(by_layer) != set(expected) or len(rows) != len(expected)
        for layer, profile in expected.items():
            row = by_layer.get(layer)
            if row is None or tuple(str(item) for item in row[1:6]) != (
                profile.profile_id,
                profile.profile_version,
                profile.profile_hash,
                profile.capability_id,
                profile.skill_ref,
            ):
                stale = True
        if stale or len(operation_ids) != 1 or len(qualification_hashes) != 1:
            raise KernelError(
                "NARRATIVE_EVALUATION_QUALIFICATION_STALE",
                "BookDesign activation requires one current real-Provider qualification with exact profile lineage",
            )

    def evaluate_semantics(
        self,
        command: NarrativeSemanticEvaluationCommand,
        *,
        principal: Principal,
    ) -> dict[str, Any]:

        if command.generator_operation_name != "book_design.propose":
            raise KernelError(
                "BOOK_DESIGN_EVALUATION_STAGE_INVALID",
                "BookDesign Authority can evaluate only BookDesign candidates",
            )
        result = self.semantic_evaluation.execute(
            command,
            principal=principal,
            caller_permission="book_design.authority.execute",
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = BookDesignAuthorityRepository(uow.cursor)
            book = repository.book_for_update(
                project_id=command.project_id,
                workspace_id=command.workspace_id,
                book_id=command.book_id,
            )
            projection = repository.complete_semantic_evaluation(
                book=book,
                asset_version_id=command.candidate_asset_version_id,
                generation_operation_id=command.generation_operation_id,
                evaluation_operation_id=result.lineage.evaluation_operation_id,
                passed=result.qualification.status == "PASS",
            )
            uow.commit()
        return {
            **projection,
            "generation_operation_id": result.lineage.generation_operation_id,
            "evaluation_operation_id": result.lineage.evaluation_operation_id,
            "evaluation_attempt_id": result.lineage.evaluation_attempt_id,
            "evaluation_asset_version_id": (result.lineage.evaluation_asset_version_id),
            "evaluation_evidence_hash": (result.lineage.evaluation_evidence_hash),
            "qualification_status": result.qualification.status,
            "trust_boundary": "INDEPENDENT",
            "replayed": result.replayed,
        }

    def _register_definitions(self) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            for definition in book_design_definitions(
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ):
                uow.repositories.definitions.register(definition)
            uow.commit()

    def _execute_transaction(
        self,
        uow: AuthorityUnitOfWork,
        operation_id: str,
        checkpoint: TransactionCheckpoint,
    ) -> dict[str, Any]:
        project_id = self._project_for_operation(uow, operation_id)
        operation = uow.repositories.chapter_authority.operation_execution(
            operation_id, project_id
        )
        payload = dict(operation["command_payload"])
        action = str(operation["definition_name"])
        project_id = str(payload["project_id"])
        workspace_id = str(payload["workspace_id"])
        book_id = str(payload["book_id"])
        actor_id = str(operation["actor_id"])
        repository = BookDesignAuthorityRepository(uow.cursor)
        result: dict[str, Any] = {"book_id": book_id}
        if action == "book.create":
            scope = BookScope.from_mapping(
                project_id=project_id,
                workspace_id=workspace_id,
                book_id=book_id,
                principal=actor_id,
                service_identity=str(payload["service_identity"]),
                payload=dict(payload["payload"]),
            )
            content = scope.content(title=str(payload["payload"].get("title") or ""))
            checkpoint("after_domain_validation")
            document = uow.repositories.asset_documents.materialize_output(
                AuthorityAssetWriteCommand(
                    operation_id=operation_id,
                    project_id=project_id,
                    asset_id=f"book:{book_id}",
                    asset_type="book_record",
                    schema_version="book-authority.v1",
                    logical_ref=f"books/{book_id}",
                    category="books",
                    output_key="book.record",
                    role="primary",
                    content=content,
                    qualification_policy="book-authority-v1",
                    trace_id=str(operation["trace_id"]),
                    correlation_id=str(operation["correlation_id"]),
                    causation_id=operation_id,
                )
            )
            checkpoint("after_asset_version_insert")
            repository.create_book(
                scope=scope,
                book_asset_version_id=document.asset_version_id,
                operation_id=operation_id,
            )
            checkpoint("after_business_projection_update")
            result["asset_version_id"] = document.asset_version_id
            result["content_hash"] = document.content_hash
        else:
            book = repository.book_for_update(
                project_id=project_id, workspace_id=workspace_id, book_id=book_id
            )
            expected_version = int(payload["expected_book_version"])
            expected_design = str(
                payload.get("expected_current_design_asset_version_id") or ""
            )
            if (
                expected_version != book["version"]
                or expected_design != book["current_design_asset_version_id"]
            ):
                raise KernelError(
                    "BOOK_VERSION_CONFLICT", "expected Book/design version is stale"
                )
            if action == "book_design.propose":
                design_payload = dict(payload["payload"])
                supervision = design_payload.pop("_author_supervision", None)
                if supervision:
                    from novel_forge.modules.production_execution.author_supervision import verify_book_supervision
                    verify_book_supervision(uow.cursor, supervision)
                design = BookDesignPayload.from_mapping(design_payload)
                checkpoint("after_domain_validation")
                result.update(
                    repository.propose(
                        book=book,
                        design=design,
                        author_supervision=supervision,
                        operation_id=operation_id,
                        trace_id=str(operation["trace_id"]),
                        checkpoint=checkpoint,
                    )
                )
                checkpoint("after_business_projection_update")
            elif action == "book_design.decide":
                target = str(payload.get("target_asset_version_id") or "")
                checkpoint("after_domain_validation")
                result["asset_version_id"] = target
                result["decision_id"] = repository.decide(
                    book=book,
                    asset_version_id=target,
                    decision=str(payload["payload"].get("decision") or ""),
                    reason=str(payload["payload"].get("reason") or ""),
                    decided_by=actor_id,
                    author_supervision=payload["payload"].get("_author_supervision"),
                    operation_id=operation_id,
                )
                checkpoint("after_business_projection_update")
            elif action == "book_design.activate":
                target = str(payload.get("target_asset_version_id") or "")
                migration_payload = dict(payload.get("migration_evidence") or {})
                if migration_payload:
                    self._require_migration_evidence_in_uow(
                        uow,
                        project_id=project_id,
                        workspace_id=workspace_id,
                        evidence=ApprovedBookDesignMigrationEvidence(
                            **migration_payload
                        ),
                    )
                checkpoint("after_domain_validation")
                result["asset_version_id"] = target
                result.update(
                    repository.activate(
                        book=book,
                        asset_version_id=target,
                        reason=str(payload["payload"].get("reason") or ""),
                        operation_id=operation_id,
                    )
                )
                result["foundation_asset_versions"] = (
                    self._materialize_evolution_foundation(
                        uow,
                        operation_id=operation_id,
                        project_id=project_id,
                        book_id=book_id,
                        design_asset_version_id=target,
                        trace_id=str(operation["trace_id"]),
                        correlation_id=str(operation["correlation_id"]),
                    )
                )
                checkpoint("after_business_projection_update")
            else:
                raise KernelError(
                    "BOOK_DESIGN_COMMAND_INVALID", f"unsupported action: {action}"
                )
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": "authority_book",
                "aggregate_id": book_id,
                "operation_id": operation_id,
                "project_id": project_id,
                "event_type": f"authority.{action}.committed",
                "correlation_id": str(operation["correlation_id"]),
                "causation_id": operation_id,
                "payload": {
                    **result,
                    "operation_id": operation_id,
                    "project_id": project_id,
                    "workspace_id": workspace_id,
                    "trace_id": str(operation["trace_id"]),
                    "execution_classification": "transaction_command",
                },
            }
        )
        checkpoint("after_outbox_insert")
        return result

    @staticmethod
    def _materialize_evolution_foundation(
        uow: AuthorityUnitOfWork,
        *,
        operation_id: str,
        project_id: str,
        book_id: str,
        design_asset_version_id: str,
        trace_id: str,
        correlation_id: str,
    ) -> dict[str, str]:
        uow.cursor.execute(
            """
            SELECT content, schema_version
            FROM authority_asset_version
            WHERE asset_version_id=%s
            """,
            [design_asset_version_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            return {}
        if str(row[1]) == FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION:
            bindings = dict(row[0])["foundation_set"]["bindings"]
            source = next(item for item in bindings if item["role"] == "CHARACTER_CAST")
            cast = uow.repositories.asset_documents.require(project_id=project_id, asset_version_id=source["asset_version_id"])
            if cast.content_hash != source["content_hash"]:
                raise KernelError("BOOK_DESIGN_CHARACTER_SOURCE_DRIFT", "Character projection requires its exact Foundation binding")
            value = cast.content.get("candidate_payload", cast.content)
            outputs = (("character_arc_portfolio", "character-arc-portfolio.v2", "character-arcs", {
                "book_id": book_id,
                "trajectories": [{key: item[key] for key in ("character_id", "desire", "need", "false_belief", "arc_direction")} for item in value["characters"]],
                "foundation_design_asset_version_id": design_asset_version_id,
                "source_cast_asset_version_id": cast.asset_version_id,
                "source_cast_content_hash": cast.content_hash,
                "authority": "FOUNDATION_PLANNING_PROJECTION",
            }),)
            return BookDesignAuthorityApplication._write_foundation_outputs(uow, operation_id=operation_id, project_id=project_id, book_id=book_id, design_asset_version_id=design_asset_version_id, trace_id=trace_id, correlation_id=correlation_id, outputs=outputs)
        if str(row[1]) != EVOLUTION_BOOK_DESIGN_SCHEMA_VERSION:
            return {}
        content = dict(row[0])
        characters = list(content["character_system"])
        outputs: tuple[tuple[str, str, str, dict[str, Any]], ...] = (
            (
                "creative_foundation",
                "creative-foundation.v1",
                "creative-foundation",
                {
                    **dict(content["creative_foundation"]),
                    "genre": content["genre"],
                    "premise": content["premise"],
                    "core_conflict": content["core_conflict"],
                    "foundation_design_asset_version_id": design_asset_version_id,
                },
            ),
            (
                "world_bible",
                "world-bible.v1",
                "world-bibles",
                {
                    "rules": list(content["world_system"]),
                    "legacy_rule_summaries": list(content["world_rules"]),
                    "foundation_design_asset_version_id": design_asset_version_id,
                },
            ),
            (
                "character_cast",
                "character-cast.v1",
                "character-casts",
                {
                    "characters": characters,
                    "foundation_design_asset_version_id": design_asset_version_id,
                },
            ),
            (
                "character_arc_portfolio",
                "character-arc-portfolio.v1",
                "character-arcs",
                {
                    "trajectories": [
                        {
                            "character_id": item["character_id"],
                            "desire": item["desire"],
                            "need": item["need"],
                            "false_belief": item["false_belief"],
                            "arc_direction": item["arc_direction"],
                        }
                        for item in characters
                    ],
                    "foundation_design_asset_version_id": design_asset_version_id,
                },
            ),
            (
                "theme_contract",
                "theme-contract.v1",
                "theme-contracts",
                {
                    "theme": content["theme"],
                    "thematic_question": content["creative_foundation"][
                        "thematic_question"
                    ],
                    "recurring_choice": content["narrative_dna"]["recurring_choice"],
                    "foundation_design_asset_version_id": design_asset_version_id,
                },
            ),
            (
                "ending_intent",
                "ending-intent.v1",
                "ending-intents",
                {
                    "ending": content["ending"],
                    "direction": content["creative_foundation"]["ending_direction"],
                    "foundation_design_asset_version_id": design_asset_version_id,
                },
            ),
            (
                "reader_promise",
                "reader-promise.v1",
                "reader-promises",
                {
                    "promise": content["reader_promise"],
                    "target_reader": content["creative_foundation"]["target_reader"],
                    "emotional_contract": content["creative_foundation"][
                        "emotional_contract"
                    ],
                    "foundation_design_asset_version_id": design_asset_version_id,
                },
            ),
        )
        return BookDesignAuthorityApplication._write_foundation_outputs(uow, operation_id=operation_id, project_id=project_id, book_id=book_id, design_asset_version_id=design_asset_version_id, trace_id=trace_id, correlation_id=correlation_id, outputs=outputs)

    @staticmethod
    def _write_foundation_outputs(uow, *, operation_id, project_id, book_id, design_asset_version_id, trace_id, correlation_id, outputs):
        versions: dict[str, str] = {}
        for asset_type, schema_version, category, output_content in outputs:
            logical_ref = f"books/{book_id}/{asset_type.replace('_', '-')}"
            uow.cursor.execute(
                """
                SELECT current_asset_version_id
                FROM authority_asset_locator
                WHERE project_id=%s AND logical_ref=%s
                """,
                [project_id, logical_ref],
            )
            current = uow.cursor.fetchone()
            document = uow.repositories.asset_documents.materialize_output(
                AuthorityAssetWriteCommand(
                    operation_id=operation_id,
                    project_id=project_id,
                    asset_id=f"{asset_type}:{book_id}",
                    asset_type=asset_type,
                    schema_version=schema_version,
                    logical_ref=logical_ref,
                    category=category,
                    output_key=f"book_design.{asset_type}",
                    role="foundation",
                    content=output_content,
                    qualification_policy="book-design-evolution-foundation-v1",
                    trace_id=trace_id,
                    correlation_id=correlation_id,
                    causation_id=design_asset_version_id,
                    expected_current_asset_version_id=(
                        str(current[0]) if current is not None else None
                    ),
                )
            )
            versions[asset_type] = document.asset_version_id
        return versions

    @staticmethod
    def _project_for_operation(uow: AuthorityUnitOfWork, operation_id: str) -> str:
        uow.cursor.execute(
            "SELECT project_id FROM authority_operation WHERE operation_id = %s",
            [operation_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("OPERATION_NOT_FOUND", "BookDesign Operation disappeared")
        return str(row[0])


__all__ = [
    "ApprovedBookDesignMigrationEvidence",
    "BookDesignAuthorityApplication",
    "BookDesignAuthorityCommand",
]
