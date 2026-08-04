"""Explicit adapters from archival AssetVersions into domain Authorities.

Adapters never infer approval from Legacy payloads.  They are invoked only
after ``migration.item.approve`` has committed an independent decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.book_design_authority import (
    BOOK_DESIGN_SCHEMA_VERSION,
    BOOK_SCHEMA_VERSION,
    BookDesignAuthorityApplication,
    BookDesignAuthorityCommand,
    BookDesignAuthorityQuery,
    BookDesignPayload,
    BookScope,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.hierarchical_planning import (
    PlanContractType,
    PlanExecutionScope,
    PostgresHierarchicalPlanningAuthority,
    validate_planning_contract,
)
from novel_forge.modules.story_design_authority import (
    DesignTransition,
    PlanningScope,
    PostgresStoryDesignAssetAuthority,
    StoryDesignTransitionCommand,
)
from novel_forge.modules.source_authority import (
    RegisterSourceDocumentCommand,
    SourceAuthorityApplication,
    SourceAuthorityQuery,
    decide_source_governance,
)
from novel_forge.modules.mkaos_authority import (
    ApproveKnowledgeCandidateCommand,
    BuildKnowledgePackCommand,
    CommitKnowledgeCandidateCommand,
    KnowledgeEvidenceSpan,
    KnowledgePackSelection,
    MkaosAuthorityApplication,
    MkaosAuthorityQuery,
)
from novel_forge.modules.mkaos_authority.domain import (
    validate_knowledge_candidate,
    validate_pack_selections,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


@dataclass(frozen=True, slots=True)
class ResolvedMigrationReference:
    legacy_business_key: str
    relation_type: str
    target_item_id: str
    target_asset_version_id: str
    target_domain_projection_id: str
    target_source_asset_type: str


@dataclass(frozen=True, slots=True)
class DomainMigrationContext:
    migration_run_id: str
    migration_item_id: str
    project_id: str
    workspace_id: str
    source_asset_type: str
    stable_business_key: str
    source_hash: str
    import_operation_id: str
    target_asset_id: str
    target_asset_version_id: str
    target_content_hash: str
    content: dict[str, Any]
    references: tuple[ResolvedMigrationReference, ...]
    decision_id: str
    decision_reason: str
    actor_id: str
    item_version: int


@dataclass(frozen=True, slots=True)
class DomainMigrationResult:
    domain_projection_id: str
    target_asset_id: str
    target_asset_version_id: str
    target_content_hash: str
    activation_operation_id: str
    evidence: dict[str, Any]


class DomainMigrationAdapter(Protocol):
    adapter_name: str

    def validate(self, context: DomainMigrationContext) -> dict[str, Any]: ...

    def activate(self, context: DomainMigrationContext) -> DomainMigrationResult: ...


class BookDesignMigrationAdapter:
    adapter_name = "novel_forge.legacy_migration.book_design_authority.v1"

    def __init__(
        self, database_url: str, *, application_build_id: str, commit_sha: str
    ) -> None:
        self.database_url = database_url
        self.application = BookDesignAuthorityApplication(
            database_url,
            application_build_id=application_build_id,
            commit_sha=commit_sha,
        )
        self.query = BookDesignAuthorityQuery(database_url)
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha

    def validate(self, context: DomainMigrationContext) -> dict[str, Any]:
        if context.source_asset_type in {"book", "book_record"}:
            payload = _book_payload(context)
            scope = BookScope.from_mapping(
                project_id=context.project_id,
                workspace_id=context.workspace_id,
                book_id=_book_id(context),
                principal=context.actor_id,
                service_identity="legacy-migration-authority",
                payload=payload,
            )
            scope.content(title=str(payload["title"]))
            validator = "BookScope.from_mapping"
            schema_version = BOOK_SCHEMA_VERSION
        else:
            BookDesignPayload.from_mapping(_book_design_payload(context))
            validator = "BookDesignPayload.from_mapping"
            schema_version = BOOK_DESIGN_SCHEMA_VERSION
        return {
            "status": "PASS",
            "validator": validator,
            "schema_version": schema_version,
            "project_id": context.project_id,
            "workspace_id": context.workspace_id,
            "book_id": _book_id(context),
            "source_hash": context.source_hash,
            "target_asset_version_id": context.target_asset_version_id,
        }

    def activate(self, context: DomainMigrationContext) -> DomainMigrationResult:
        validation = self.validate(context)
        book_id = _book_id(context)
        common = {
            "project_id": context.project_id,
            "workspace_id": context.workspace_id,
            "book_id": book_id,
            "actor_id": context.actor_id,
            "service_identity": "legacy-migration-authority",
            "trace_id": f"trace:{context.migration_run_id}",
            "correlation_id": f"migration:{context.migration_run_id}",
        }
        if context.source_asset_type in {"book", "book_record"}:
            result = self.application.execute(
                BookDesignAuthorityCommand(
                    definition_name="book.create",
                    idempotency_key=(
                        f"migration:book:create:{context.migration_item_id}:"
                        f"{context.source_hash}"
                    ),
                    payload=_book_payload(context),
                    **common,
                )
            )
            version_id = str(result["asset_version_id"])
            return DomainMigrationResult(
                domain_projection_id=book_id,
                target_asset_id=f"book:{book_id}",
                target_asset_version_id=version_id,
                target_content_hash=str(result["content_hash"]),
                activation_operation_id=str(result["operation_id"]),
                evidence={
                    **validation,
                    "book_create_operation_id": result["operation_id"],
                    "independent_migration_decision_id": context.decision_id,
                },
            )
        book = self.query.require_book(project_id=context.project_id, book_id=book_id)
        proposed = self.application.execute(
            BookDesignAuthorityCommand(
                definition_name="book_design.propose",
                idempotency_key=(
                    f"migration:book-design:propose:{context.migration_item_id}:"
                    f"{context.source_hash}"
                ),
                payload=_book_design_payload(context),
                expected_book_version=int(book["version"]),
                expected_current_design_asset_version_id=str(
                    book["active_book_design_version_id"]
                ),
                **common,
            )
        )
        candidate_version = str(proposed["asset_version_id"])
        decided = self.application.execute(
            BookDesignAuthorityCommand(
                definition_name="book_design.decide",
                idempotency_key=(
                    f"migration:book-design:decide:{context.migration_item_id}:"
                    f"{context.decision_id}"
                ),
                payload={"decision": "APPROVE", "reason": context.decision_reason},
                expected_book_version=int(book["version"]),
                expected_current_design_asset_version_id=str(
                    book["active_book_design_version_id"]
                ),
                target_asset_version_id=candidate_version,
                **common,
            )
        )
        activated = self.application.execute(
            BookDesignAuthorityCommand(
                definition_name="book_design.activate",
                idempotency_key=(
                    f"migration:book-design:activate:{context.migration_item_id}:"
                    f"{context.decision_id}"
                ),
                payload={"reason": context.decision_reason},
                expected_book_version=int(book["version"]),
                expected_current_design_asset_version_id=str(
                    book["active_book_design_version_id"]
                ),
                target_asset_version_id=candidate_version,
                **common,
            )
        )
        versions = self.query.list_design_versions(
            project_id=context.project_id, book_id=book_id
        )
        active = next(
            item for item in versions if item["asset_version_id"] == candidate_version
        )
        return DomainMigrationResult(
            domain_projection_id=candidate_version,
            target_asset_id=_asset_id_from_version(self.database_url, candidate_version),
            target_asset_version_id=candidate_version,
            target_content_hash=str(active["content_hash"]),
            activation_operation_id=str(activated["operation_id"]),
            evidence={
                **validation,
                "candidate_operation_id": proposed["operation_id"],
                "domain_decision_operation_id": decided["operation_id"],
                "domain_activation_operation_id": activated["operation_id"],
                "domain_decision_id": decided["decision_id"],
                "domain_activation_id": activated["activation_id"],
                "independent_migration_decision_id": context.decision_id,
                "archival_asset_version_id": context.target_asset_version_id,
            },
        )


class StoryDesignMigrationAdapter:
    adapter_name = "novel_forge.legacy_migration.story_design_authority.v1"

    def __init__(
        self, database_url: str, *, application_build_id: str, commit_sha: str
    ) -> None:
        self.database_url = database_url
        self.authority = PostgresStoryDesignAssetAuthority(
            database_url,
            application_build_id=application_build_id,
            commit_sha=commit_sha,
            worker_id="legacy-story-design-migration-worker",
        )

    def validate(self, context: DomainMigrationContext) -> dict[str, Any]:
        generator, scope, logical_key = _story_design_identity(context)
        return {
            "status": "PASS",
            "validator": "StoryDesign GeneratorCatalog and PlanningScope",
            "generator_operation_name": generator,
            "planning_scope": scope.value,
            "logical_key": logical_key,
            "source_hash": context.source_hash,
            "target_asset_version_id": context.target_asset_version_id,
        }

    def activate(self, context: DomainMigrationContext) -> DomainMigrationResult:
        validation = self.validate(context)
        state, operation_ids = _activate_story_design(
            self.authority,
            context,
            generator=str(validation["generator_operation_name"]),
            scope=PlanningScope(str(validation["planning_scope"])),
            logical_key=str(validation["logical_key"]),
        )
        return DomainMigrationResult(
            domain_projection_id=context.target_asset_version_id,
            target_asset_id=context.target_asset_id,
            target_asset_version_id=context.target_asset_version_id,
            target_content_hash=context.target_content_hash,
            activation_operation_id=operation_ids[-1],
            evidence={
                **validation,
                "transition_operation_ids": operation_ids,
                "story_design_version": int(state["version"]),
                "lifecycle": state["lifecycle"],
                "qualification": state["qualification"],
                "approval": state["approval"],
                "independent_migration_decision_id": context.decision_id,
            },
        )


class HierarchicalPlanningMigrationAdapter:
    adapter_name = "novel_forge.legacy_migration.hierarchical_planning.v1"

    def __init__(
        self, database_url: str, *, application_build_id: str, commit_sha: str
    ) -> None:
        self.database_url = database_url
        self.story = PostgresStoryDesignAssetAuthority(
            database_url,
            application_build_id=application_build_id,
            commit_sha=commit_sha,
            worker_id="legacy-planning-migration-worker",
        )
        self.planning = PostgresHierarchicalPlanningAuthority(
            database_url,
            application_build_id=application_build_id,
            commit_sha=commit_sha,
        )

    def validate(self, context: DomainMigrationContext) -> dict[str, Any]:
        contract_type = _plan_type(context.source_asset_type)
        content = _domain_content(context.content)
        book_id = _required_text(content.get("book_id"), "book_id")
        parent_version_id = _parent_version(context, contract_type)
        execution_scope = PlanExecutionScope(
            str(content.get("execution_scope") or "PLANNED").upper()
        )
        contract = validate_planning_contract(
            project_id=context.project_id,
            book_id=book_id,
            contract_type=contract_type,
            asset_version_id=context.target_asset_version_id,
            parent_version_id=parent_version_id,
            execution_scope=execution_scope,
            content=content,
        )
        return {
            "status": "PASS",
            "validator": "validate_planning_contract",
            "contract_type": contract_type.value,
            "logical_key": contract.logical_key,
            "book_id": book_id,
            "parent_version_id": parent_version_id,
            "execution_scope": execution_scope.value,
            "source_hash": context.source_hash,
            "target_asset_version_id": context.target_asset_version_id,
        }

    def activate(self, context: DomainMigrationContext) -> DomainMigrationResult:
        validation = self.validate(context)
        contract_type = PlanContractType(str(validation["contract_type"]))
        scope = _planning_scope(contract_type)
        generator = _plan_generator(contract_type)
        _, transition_operations = _activate_story_design(
            self.story,
            context,
            generator=generator,
            scope=scope,
            logical_key=str(validation["logical_key"]),
        )
        principal = _principal(
            context.actor_id,
            context.project_id,
            {"book.authority.execute"},
        )
        binding = self.planning.bind_active_contract(
            project_id=context.project_id,
            book_id=str(validation["book_id"]),
            asset_version_id=context.target_asset_version_id,
            contract_type=contract_type,
            parent_version_id=str(validation["parent_version_id"]),
            execution_scope=PlanExecutionScope(str(validation["execution_scope"])),
            workspace_id=context.workspace_id,
            actor_id=context.actor_id,
            idempotency_key=(
                f"migration:planning:bind:{context.migration_item_id}:"
                f"{context.decision_id}"
            ),
            trace_id=f"trace:{context.migration_run_id}",
            correlation_id=f"migration:{context.migration_run_id}",
            causation_operation_id=transition_operations[-1],
            principal=principal,
            decision_evidence={
                "migration_decision_id": context.decision_id,
                "reason": context.decision_reason,
            },
        )
        return DomainMigrationResult(
            domain_projection_id=str(binding["binding_id"]),
            target_asset_id=context.target_asset_id,
            target_asset_version_id=context.target_asset_version_id,
            target_content_hash=context.target_content_hash,
            activation_operation_id=str(binding["operation_id"]),
            evidence={
                **validation,
                "story_design_transition_operation_ids": transition_operations,
                "planning_binding_operation_id": binding["operation_id"],
                "binding_id": binding["binding_id"],
                "created_by_operation_id": binding["created_by_operation_id"],
                "independent_migration_decision_id": context.decision_id,
            },
        )


class SourceDocumentMigrationAdapter:
    adapter_name = "novel_forge.legacy_migration.source_authority.v1"

    def __init__(
        self, database_url: str, *, application_build_id: str, commit_sha: str
    ) -> None:
        self.database_url = database_url
        self.application = SourceAuthorityApplication(
            database_url,
            application_build_id=application_build_id,
            commit_sha=commit_sha,
            worker_id="legacy-source-migration-worker",
        )
        self.query = SourceAuthorityQuery(database_url)

    def validate(self, context: DomainMigrationContext) -> dict[str, Any]:
        content = _domain_content(context.content)
        blob_id = _required_text(content.get("blob_id"), "blob_id")
        authorization = _required_text(
            content.get("rights_authorization"), "rights_authorization"
        )
        decision = decide_source_governance(
            authorization=authorization,
            license_name=str(content.get("license_name") or ""),
            copyright_boundary=str(content.get("copyright_boundary") or ""),
        )
        if (
            decision.lifecycle,
            decision.eligibility,
            decision.governance,
        ) != ("ACTIVE", "ELIGIBLE", "CLEAR"):
            raise KernelError(
                "SOURCE_MIGRATION_GOVERNANCE_BLOCKED",
                "Source migration requires independently eligible rights",
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            blob = uow.repositories.asset_blobs.blob_for_update(blob_id)
        if (
            str(blob["project_id"]) != context.project_id
            or str(blob["status"]) != "AVAILABLE"
            or not blob["actual_hash"]
            or blob["actual_hash"] != blob["expected_hash"]
            or blob["actual_size"] != blob["expected_size"]
            or blob["actual_object_key"] != blob["object_key"]
        ):
            raise KernelError(
                "SOURCE_BLOB_NOT_VERIFIED",
                "Legacy Source requires an AVAILABLE, receipt-verified Blob in scope",
            )
        return {
            "status": "PASS",
            "validator": "SourceAuthority verified Blob and rights preflight",
            "blob_id": blob_id,
            "blob_hash": str(blob["actual_hash"]),
            "blob_size": int(blob["actual_size"]),
            "object_key": str(blob["actual_object_key"]),
            "rights_authorization": authorization,
            "governance_status": decision.governance_status,
            "source_hash": context.source_hash,
        }

    def activate(self, context: DomainMigrationContext) -> DomainMigrationResult:
        validation = self.validate(context)
        content = _domain_content(context.content)
        result = self.application.execute(
            RegisterSourceDocumentCommand(
                project_id=context.project_id,
                workspace_id=context.workspace_id,
                blob_id=str(validation["blob_id"]),
                title=_required_text(content.get("title"), "title"),
                source_kind=_required_text(content.get("source_kind"), "source_kind"),
                source_uri=str(content.get("source_uri") or ""),
                rights_authorization=str(validation["rights_authorization"]),
                license_name=str(content.get("license_name") or ""),
                copyright_boundary=str(content.get("copyright_boundary") or ""),
                actor_id=context.actor_id,
                idempotency_key=(
                    f"migration:source:register:{context.migration_item_id}:"
                    f"{context.decision_id}"
                ),
                trace_id=f"trace:{context.migration_run_id}",
                correlation_id=f"migration:{context.migration_run_id}",
            )
        )
        document = self.query.require_document(
            project_id=context.project_id,
            source_document_id=str(result["source_document_id"]),
        )
        return DomainMigrationResult(
            domain_projection_id=str(result["source_document_id"]),
            target_asset_id=_asset_id_from_version(
                self.database_url, str(result["asset_version_id"])
            ),
            target_asset_version_id=str(result["asset_version_id"]),
            target_content_hash=_content_hash_for_version(
                self.database_url, str(result["asset_version_id"])
            ),
            activation_operation_id=str(result["operation_id"]),
            evidence={
                **validation,
                "source_document_id": result["source_document_id"],
                "source_operation_id": result["operation_id"],
                "source_governance_status": document["governance_status"],
                "source_lifecycle": document["lifecycle"],
                "source_eligibility": document["eligibility"],
                "source_projection_hash": document["source_content_hash"],
                "independent_migration_decision_id": context.decision_id,
                "archival_asset_version_id": context.target_asset_version_id,
            },
        )


class MkaosMigrationAdapter:
    adapter_name = "novel_forge.legacy_migration.mkaos_authority.v1"

    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        allow_fixture_activation: bool,
    ) -> None:
        self.database_url = database_url
        self.application = MkaosAuthorityApplication(
            database_url,
            application_build_id=application_build_id,
            commit_sha=commit_sha,
            worker_id="legacy-mkaos-migration-worker",
            allow_fixture_activation=allow_fixture_activation,
        )
        self.query = MkaosAuthorityQuery(database_url)

    def validate(self, context: DomainMigrationContext) -> dict[str, Any]:
        if context.source_asset_type == "knowledge_pack":
            selections, target_version_id = _mkaos_pack_selections(context)
            validate_pack_selections(selections)
            content = _domain_content(context.content)
            selector_hash = _required_text(
                content.get("selector_policy_hash"), "selector_policy_hash"
            )
            if not selector_hash.startswith("sha256:"):
                raise KernelError(
                    "MKAOS_PACK_POLICY_INVALID",
                    "selector_policy_hash must be canonical SHA-256",
                )
            return {
                "status": "PASS",
                "validator": "validate_pack_selections",
                "target_asset_version_id": target_version_id,
                "selection_count": len(selections),
                "selector_policy_hash": selector_hash,
                "source_hash": context.source_hash,
            }
        candidate = _mkaos_candidate(context)
        validate_knowledge_candidate(candidate)
        spans = _mkaos_evidence_spans(context)
        return {
            "status": "PASS",
            "validator": "validate_knowledge_candidate and KnowledgeEvidenceSpan",
            "execution_asset_version_id": _required_text(
                _domain_content(context.content).get("execution_asset_version_id"),
                "execution_asset_version_id",
            ),
            "evidence_span_count": len(spans),
            "source_chunk_asset_version_ids": sorted(
                {item.source_chunk_asset_version_id for item in spans}
            ),
            "source_hash": context.source_hash,
        }

    def activate(self, context: DomainMigrationContext) -> DomainMigrationResult:
        validation = self.validate(context)
        content = _domain_content(context.content)
        principal = _principal(
            context.actor_id,
            context.project_id,
            {"mkaos.authority.execute", "mkaos.authority.approve"},
        )
        if context.source_asset_type == "knowledge_pack":
            selections, target_version_id = _mkaos_pack_selections(context)
            result = self.application.execute_pack(
                BuildKnowledgePackCommand(
                    project_id=context.project_id,
                    workspace_id=context.workspace_id,
                    target_asset_version_id=target_version_id,
                    selector_policy_version=_required_text(
                        content.get("selector_policy_version"),
                        "selector_policy_version",
                    ),
                    selector_policy_hash=str(validation["selector_policy_hash"]),
                    selections=selections,
                    actor_id=context.actor_id,
                    idempotency_key=(
                        f"migration:mkaos:pack:{context.migration_item_id}:"
                        f"{context.decision_id}"
                    ),
                    trace_id=f"trace:{context.migration_run_id}",
                    correlation_id=f"migration:{context.migration_run_id}",
                ),
                principal=principal,
            )
            pack = self.query.require_pack(
                project_id=context.project_id,
                knowledge_pack_id=str(result["knowledge_pack_id"]),
            )
            projection_id = str(result["knowledge_pack_id"])
            version_id = str(result["asset_version_id"])
            operation_id = str(result["operation_id"])
            evidence = {
                **validation,
                "knowledge_pack_id": projection_id,
                "pack_operation_id": operation_id,
                "selection_hash": pack["selection_hash"],
                "pack_status": pack["pack_status"],
                "independent_migration_decision_id": context.decision_id,
            }
        else:
            candidate = self.application.execute_candidate(
                CommitKnowledgeCandidateCommand(
                    project_id=context.project_id,
                    workspace_id=context.workspace_id,
                    execution_asset_version_id=str(
                        validation["execution_asset_version_id"]
                    ),
                    candidate=_mkaos_candidate(context),
                    evidence_spans=_mkaos_evidence_spans(context),
                    abstraction_policy_version=_required_text(
                        content.get("abstraction_policy_version"),
                        "abstraction_policy_version",
                    ),
                    actor_id=context.actor_id,
                    idempotency_key=(
                        f"migration:mkaos:candidate:{context.migration_item_id}:"
                        f"{context.source_hash}"
                    ),
                    trace_id=f"trace:{context.migration_run_id}",
                    correlation_id=f"migration:{context.migration_run_id}",
                ),
                principal=principal,
            )
            approved = self.application.execute_approval(
                ApproveKnowledgeCandidateCommand(
                    project_id=context.project_id,
                    workspace_id=context.workspace_id,
                    candidate_asset_version_id=str(candidate["asset_version_id"]),
                    policy_version="legacy-migration-independent-approval-v1",
                    rationale=context.decision_reason,
                    actor_id=context.actor_id,
                    idempotency_key=(
                        f"migration:mkaos:approve:{context.migration_item_id}:"
                        f"{context.decision_id}"
                    ),
                    trace_id=f"trace:{context.migration_run_id}",
                    correlation_id=f"migration:{context.migration_run_id}",
                ),
                principal=principal,
            )
            cards = self.query.list_cards(project_id=context.project_id)
            candidates = self.query.list_candidates(project_id=context.project_id)
            card = next(
                item
                for item in cards
                if item["asset_version_id"] == approved["asset_version_id"]
            )
            stored_candidate = next(
                item
                for item in candidates
                if item["asset_version_id"] == candidate["asset_version_id"]
            )
            projection_id = str(approved["knowledge_card_id"])
            version_id = str(approved["asset_version_id"])
            operation_id = str(approved["operation_id"])
            evidence = {
                **validation,
                "knowledge_candidate_id": candidate["knowledge_candidate_id"],
                "candidate_asset_version_id": candidate["asset_version_id"],
                "candidate_operation_id": candidate["operation_id"],
                "knowledge_card_id": projection_id,
                "knowledge_card_operation_id": operation_id,
                "card_status": card["card_status"],
                "card_lifecycle": card["lifecycle"],
                "fixture_protocol_only": card["content"]["source_policy"][
                    "fixture_protocol_only"
                ],
                "production_verified": stored_candidate["content"][
                    "execution_evidence"
                ]["proof"]["production_verified"],
                "independent_migration_decision_id": context.decision_id,
                "archival_asset_version_id": context.target_asset_version_id,
            }
        return DomainMigrationResult(
            domain_projection_id=projection_id,
            target_asset_id=_asset_id_from_version(self.database_url, version_id),
            target_asset_version_id=version_id,
            target_content_hash=_content_hash_for_version(
                self.database_url, version_id
            ),
            activation_operation_id=operation_id,
            evidence=evidence,
        )


class DomainMigrationAdapterRegistry:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        allow_fixture_activation: bool = False,
    ) -> None:
        adapters: tuple[DomainMigrationAdapter, ...] = (
            BookDesignMigrationAdapter(
                database_url,
                application_build_id=application_build_id,
                commit_sha=commit_sha,
            ),
            StoryDesignMigrationAdapter(
                database_url,
                application_build_id=application_build_id,
                commit_sha=commit_sha,
            ),
            HierarchicalPlanningMigrationAdapter(
                database_url,
                application_build_id=application_build_id,
                commit_sha=commit_sha,
            ),
            SourceDocumentMigrationAdapter(
                database_url,
                application_build_id=application_build_id,
                commit_sha=commit_sha,
            ),
            MkaosMigrationAdapter(
                database_url,
                application_build_id=application_build_id,
                commit_sha=commit_sha,
                allow_fixture_activation=allow_fixture_activation,
            ),
        )
        self._adapters = {item.adapter_name: item for item in adapters}

    def resolve(self, adapter_name: str) -> DomainMigrationAdapter:
        try:
            return self._adapters[adapter_name]
        except KeyError as exc:
            raise KernelError(
                "DOMAIN_MIGRATION_ADAPTER_NOT_IMPLEMENTED",
                f"domain migration adapter is not implemented: {adapter_name}",
            ) from exc


def _activate_story_design(
    authority: PostgresStoryDesignAssetAuthority,
    context: DomainMigrationContext,
    *,
    generator: str,
    scope: PlanningScope,
    logical_key: str,
) -> tuple[dict[str, Any], list[str]]:
    principal = _principal(
        context.actor_id,
        context.project_id,
        {"story_design.authority.execute"},
    )
    state: dict[str, Any] | None = None
    operation_ids: list[str] = []
    for ordinal, transition in enumerate(
        (
            DesignTransition.ENROLL,
            DesignTransition.MATERIALIZE,
            DesignTransition.STRUCTURAL_VALIDATE,
            DesignTransition.SEMANTIC_VALIDATE,
            DesignTransition.QUALIFY,
            DesignTransition.SUBMIT_APPROVAL,
            DesignTransition.APPROVE,
            DesignTransition.ACTIVATE,
        )
    ):
        evidence = {
            "legacy_import_operation_id": context.import_operation_id,
            "migration_decision_id": context.decision_id,
            "migration_run_id": context.migration_run_id,
            "source_hash": context.source_hash,
            "passed": True,
            "legacy_state_trusted_for_activation": False,
        }
        state = authority.transition(
            StoryDesignTransitionCommand(
                project_id=context.project_id,
                workspace_id=context.workspace_id,
                actor_id=context.actor_id,
                trace_id=f"trace:{context.migration_run_id}",
                correlation_id=f"migration:{context.migration_run_id}",
                idempotency_key=(
                    f"migration:story-design:{context.migration_item_id}:"
                    f"{transition.value}:{context.decision_id}"
                ),
                asset_version_id=context.target_asset_version_id,
                content_hash=context.target_content_hash,
                logical_key=logical_key,
                generator_operation_name=generator,
                transition=transition,
                planning_scope=scope,
                expected_version=0 if state is None else int(state["version"]),
                source_kind="LEGACY_IMPORT",
                evidence=evidence,
            ),
            principal=principal,
        )
        operation_ids.append(str(state["updated_by_operation_id"]))
    assert state is not None
    return state, operation_ids


def _principal(
    actor_id: str, project_id: str, permissions: set[str]
) -> Principal:
    return Principal(
        principal_id=actor_id,
        principal_type=PrincipalType.LOCAL_OPERATOR,
        permissions=frozenset(permissions),
        project_scope=frozenset({project_id}),
        authentication_source="legacy-migration-independent-decision",
    )


def _domain_content(content: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in content.items()
        if key not in {"legacy_migration", "workspace_id"}
    }


def _book_id(context: DomainMigrationContext) -> str:
    content = _domain_content(context.content)
    return _required_text(
        content.get("book_id") or context.stable_business_key,
        "book_id",
    )


def _book_payload(context: DomainMigrationContext) -> dict[str, Any]:
    content = _domain_content(context.content)
    return {
        "schema_version": BOOK_SCHEMA_VERSION,
        "title": _required_text(content.get("title"), "title"),
        "production_profile": _required_mapping(
            content.get("production_profile"), "production_profile"
        ),
        "runtime_policy": _required_mapping(
            content.get("runtime_policy"), "runtime_policy"
        ),
        "release_identity": _required_text(
            content.get("release_identity"), "release_identity"
        ),
    }


def _book_design_payload(context: DomainMigrationContext) -> dict[str, Any]:
    content = _domain_content(context.content)
    fields = {
        "title",
        "genre",
        "premise",
        "theme",
        "core_conflict",
        "reader_promise",
        "ending",
        "protagonist",
        "world_rules",
        "target_chapters",
    }
    return {
        "schema_version": BOOK_DESIGN_SCHEMA_VERSION,
        **{field: content.get(field) for field in fields},
    }


def _story_design_identity(
    context: DomainMigrationContext,
) -> tuple[str, PlanningScope, str]:
    content = _domain_content(context.content)
    generator = _required_text(
        content.get("generator_operation_name"), "generator_operation_name"
    )
    scope = PlanningScope(_required_text(content.get("planning_scope"), "planning_scope"))
    logical_key = _required_text(content.get("logical_key"), "logical_key")
    return generator, scope, logical_key


def _plan_type(source_type: str) -> PlanContractType:
    mapping = {
        "book_plan": PlanContractType.BOOK,
        "outline_version": PlanContractType.BOOK,
        "volume_plan": PlanContractType.VOLUME,
        "arc_plan": PlanContractType.ARC,
        "chapter_group_plan": PlanContractType.CHAPTER_GROUP,
        "chapter_plan": PlanContractType.CHAPTER,
        "chapter_plan_version": PlanContractType.CHAPTER,
    }
    try:
        return mapping[source_type]
    except KeyError as exc:
        raise KernelError(
            "DOMAIN_MIGRATION_TYPE_UNSUPPORTED",
            f"planning adapter does not support {source_type}",
        ) from exc


def _plan_generator(contract_type: PlanContractType) -> str:
    return {
        PlanContractType.BOOK: "book_plan.generate",
        PlanContractType.VOLUME: "volume_plan.generate",
        PlanContractType.ARC: "arc_plan.generate",
        PlanContractType.CHAPTER_GROUP: "chapter_group_plan.generate",
        PlanContractType.CHAPTER: "chapter_plan.generate",
    }[contract_type]


def _planning_scope(contract_type: PlanContractType) -> PlanningScope:
    return {
        PlanContractType.BOOK: PlanningScope.BOOK,
        PlanContractType.VOLUME: PlanningScope.VOLUME,
        PlanContractType.ARC: PlanningScope.ARC,
        PlanContractType.CHAPTER_GROUP: PlanningScope.CHAPTER_GROUP,
        PlanContractType.CHAPTER: PlanningScope.CHAPTER,
    }[contract_type]


def _parent_version(
    context: DomainMigrationContext, contract_type: PlanContractType
) -> str:
    expected = {
        PlanContractType.VOLUME: {"book_plan", "outline_version"},
        PlanContractType.CHAPTER_GROUP: {"volume_plan"},
        PlanContractType.CHAPTER: {"chapter_group_plan"},
    }.get(contract_type)
    if expected is None:
        return ""
    matches = [
        item.target_asset_version_id
        for item in context.references
        if item.target_source_asset_type in expected
    ]
    if len(matches) != 1:
        raise KernelError(
            "PLANNING_PARENT_REFERENCE_INVALID",
            f"{contract_type.value} requires exactly one resolved parent reference",
        )
    return matches[0]


def _required_text(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise KernelError("DOMAIN_MIGRATION_SCHEMA_INVALID", f"{field} is required")
    return normalized


def _required_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise KernelError(
            "DOMAIN_MIGRATION_SCHEMA_INVALID", f"{field} must be an object"
        )
    return dict(value)


def _mkaos_candidate(context: DomainMigrationContext) -> dict[str, Any]:
    content = _domain_content(context.content)
    value = content.get("candidate")
    if isinstance(value, dict):
        return dict(value)
    fields = {
        "concept_name",
        "discipline",
        "abstract_principle",
        "constraints",
        "conflict_generators",
        "review_checks",
        "copyright_boundaries",
    }
    return {field: content.get(field) for field in fields}


def _mkaos_evidence_spans(
    context: DomainMigrationContext,
) -> tuple[KnowledgeEvidenceSpan, ...]:
    content = _domain_content(context.content)
    values = content.get("evidence_spans")
    if not isinstance(values, list) or not values:
        raise KernelError(
            "MKAOS_EVIDENCE_INVALID", "migration requires evidence_spans"
        )
    return tuple(KnowledgeEvidenceSpan(**dict(value)) for value in values)


def _mkaos_pack_selections(
    context: DomainMigrationContext,
) -> tuple[tuple[KnowledgePackSelection, ...], str]:
    content = _domain_content(context.content)
    values = content.get("selections")
    if not isinstance(values, list) or not values:
        raise KernelError(
            "MKAOS_PACK_SELECTION_INVALID", "migration requires pack selections"
        )
    references = {item.legacy_business_key: item for item in context.references}
    selections: list[KnowledgePackSelection] = []
    for value in values:
        if not isinstance(value, dict):
            raise KernelError(
                "MKAOS_PACK_SELECTION_INVALID", "pack selection must be an object"
            )
        business_key = _required_text(
            value.get("legacy_business_key"), "legacy_business_key"
        )
        reference = references.get(business_key)
        if reference is None:
            raise KernelError(
                "MKAOS_PACK_REFERENCE_MISSING",
                f"pack selection reference is not resolved: {business_key}",
            )
        selections.append(
            KnowledgePackSelection(
                knowledge_card_asset_version_id=(
                    reference.target_asset_version_id
                ),
                usage_role=_required_text(value.get("usage_role"), "usage_role"),
                frozen_weight=Decimal(str(value.get("frozen_weight"))),
            )
        )
    target_key = _required_text(
        content.get("target_legacy_business_key"),
        "target_legacy_business_key",
    )
    target = references.get(target_key)
    if target is None:
        raise KernelError(
            "MKAOS_PACK_TARGET_MISSING",
            "KnowledgePack target reference is not resolved",
        )
    return tuple(selections), target.target_asset_version_id


def _asset_id_from_version(database_url: str, asset_version_id: str) -> str:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            "SELECT asset_id FROM authority_asset_version WHERE asset_version_id=%s",
            [asset_version_id],
        )
        row = uow.cursor.fetchone()
    if row is None:
        raise KernelError(
            "DOMAIN_MIGRATION_TARGET_MISSING", "domain target AssetVersion is missing"
        )
    return str(row[0])


def _content_hash_for_version(database_url: str, asset_version_id: str) -> str:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            "SELECT content_hash FROM authority_asset_version WHERE asset_version_id=%s",
            [asset_version_id],
        )
        row = uow.cursor.fetchone()
    if row is None:
        raise KernelError(
            "DOMAIN_MIGRATION_TARGET_MISSING", "domain target AssetVersion is missing"
        )
    return str(row[0])


__all__ = [
    "DomainMigrationAdapterRegistry",
    "DomainMigrationContext",
    "DomainMigrationResult",
    "ResolvedMigrationReference",
]
