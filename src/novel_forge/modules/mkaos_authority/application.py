from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any
from uuid import uuid4

from novel_forge.modules.authority_handler_runtime.runtime import require_current_fence
from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    WorkerResultCommand,
    acquire_attempt_lease,
    create_attempt,
    queue_attempt,
    start_attempt,
    submit_attempt_failure,
    submit_attempt_result,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.modules.mkaos_authority.definitions import (
    MKAOS_APPROVE_DEFINITION_VERSION,
    MKAOS_APPROVE_HANDLER_KEY,
    MKAOS_APPROVE_OPERATION,
    MKAOS_CANDIDATE_DEFINITION_VERSION,
    MKAOS_CANDIDATE_HANDLER_KEY,
    MKAOS_CANDIDATE_OPERATION,
    MKAOS_PACK_DEFINITION_VERSION,
    MKAOS_PACK_HANDLER_KEY,
    MKAOS_PACK_OPERATION,
    mkaos_authority_definitions,
)
from novel_forge.modules.mkaos_authority.domain import (
    KnowledgeEvidenceSpan,
    KnowledgePackSelection,
    assert_abstract_content_safe,
    validate_evidence_spans,
    validate_knowledge_candidate,
    validate_pack_selections,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.mkaos_authority_repositories import MkaosAuthorityRepository
from novel_forge.storage.source_intelligence_repositories import (
    SourceIntelligenceRepository,
)


@dataclass(frozen=True, slots=True)
class CommitKnowledgeCandidateCommand:
    project_id: str
    workspace_id: str
    execution_asset_version_id: str
    candidate: dict[str, Any]
    evidence_spans: tuple[KnowledgeEvidenceSpan, ...]
    abstraction_policy_version: str
    actor_id: str
    idempotency_key: str
    trace_id: str
    correlation_id: str
    observation_asset_version_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_strings(
            self.project_id,
            self.workspace_id,
            self.execution_asset_version_id,
            self.abstraction_policy_version,
            self.actor_id,
            self.idempotency_key,
            self.trace_id,
            self.correlation_id,
        )
        if not self.candidate or not (
            self.evidence_spans or self.observation_asset_version_ids
        ):
            raise ValueError("MKAOS candidate command is incomplete")


@dataclass(frozen=True, slots=True)
class ApproveKnowledgeCandidateCommand:
    project_id: str
    workspace_id: str
    candidate_asset_version_id: str
    policy_version: str
    rationale: str
    actor_id: str
    idempotency_key: str
    trace_id: str
    correlation_id: str
    approval_class: str = "PRODUCTION"

    def __post_init__(self) -> None:
        _require_strings(
            self.project_id,
            self.workspace_id,
            self.candidate_asset_version_id,
            self.policy_version,
            self.rationale,
            self.actor_id,
            self.idempotency_key,
            self.trace_id,
            self.correlation_id,
        )
        if len(self.rationale) > 4_000:
            raise ValueError("MKAOS governance rationale is too long")
        approval_class = self.approval_class.strip().upper()
        if approval_class not in {"PRODUCTION", "EXPERIMENTAL_VALIDATION"}:
            raise ValueError("MKAOS approval class is unsupported")
        object.__setattr__(self, "approval_class", approval_class)


@dataclass(frozen=True, slots=True)
class ExperimentalKnowledgeApprovalPolicy:
    project_id: str
    workspace_id: str
    policy_version: str
    reviewer_id: str

    def __post_init__(self) -> None:
        _require_strings(
            self.project_id,
            self.workspace_id,
            self.policy_version,
            self.reviewer_id,
        )


@dataclass(frozen=True, slots=True)
class BuildKnowledgePackCommand:
    project_id: str
    workspace_id: str
    target_asset_version_id: str
    selector_policy_version: str
    selector_policy_hash: str
    selections: tuple[KnowledgePackSelection, ...]
    actor_id: str
    idempotency_key: str
    trace_id: str
    correlation_id: str
    supersedes_pack_asset_version_id: str = ""

    def __post_init__(self) -> None:
        _require_strings(
            self.project_id,
            self.workspace_id,
            self.target_asset_version_id,
            self.selector_policy_version,
            self.selector_policy_hash,
            self.actor_id,
            self.idempotency_key,
            self.trace_id,
            self.correlation_id,
        )
        _require_sha256(self.selector_policy_hash, "selector policy Hash")
        if not self.selections:
            raise ValueError("KnowledgePack selections are required")


class MkaosAuthorityApplication:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        worker_id: str = "mkaos-authority-worker",
        allow_fixture_activation: bool = False,
        experimental_approval_policy: ExperimentalKnowledgeApprovalPolicy | None = None,
    ) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.worker_id = worker_id
        self.allow_fixture_activation = bool(allow_fixture_activation)
        self.experimental_approval_policy = experimental_approval_policy

    def execute_candidate(
        self,
        command: CommitKnowledgeCandidateCommand,
        *,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        admitted = self.admit_candidate(command, principal=principal)
        if admitted["status"] == "SUCCEEDED":
            return admitted
        return self._run(str(admitted["operation_id"]), command.project_id)

    def admit_candidate(
        self,
        command: CommitKnowledgeCandidateCommand,
        *,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        actor_id = self._actor(
            command.actor_id,
            principal,
            "mkaos.authority.execute",
            command.project_id,
        )
        (
            candidate,
            execution,
            chunks,
            spans,
            observations,
            execution_binding,
            candidate_hash,
        ) = self._preflight_candidate(command)
        with AuthorityUnitOfWork(self.database_url) as uow:
            existing = MkaosAuthorityRepository(uow.cursor).existing_candidate(
                project_id=command.project_id, candidate_hash=candidate_hash
            )
        if existing is not None:
            if existing["operation_status"] != "SUCCEEDED":
                raise KernelError(
                    "MKAOS_CANDIDATE_RECOVERY_REQUIRED",
                    "existing candidate Operation is incomplete and requires recovery",
                )
            return {
                **existing,
                "project_id": command.project_id,
                "status": "SUCCEEDED",
                "replayed": True,
                "duplicate": True,
            }
        payload = {
            "candidate": candidate,
            "evidence_spans": [asdict(span) for span in spans],
            "abstraction_policy_version": command.abstraction_policy_version,
            "candidate_hash": candidate_hash,
            "execution_asset_version_id": command.execution_asset_version_id,
            "execution_binding": execution_binding,
            "observation_asset_version_ids": sorted(observations),
            "lineage_mode": (
                "OBSERVATION_ABSTRACTION"
                if observations
                else "MIGRATION_ONLY_DIRECT_EVIDENCE"
            ),
            "source_expression_included": False,
            "client_idempotency_key": command.idempotency_key,
        }
        inputs = [
            _input_asset(execution["asset_version_id"], "execution_evidence", execution["content_hash"]),
            *[
                _input_asset(
                    version_id,
                    "source_chunk_evidence",
                    chunks[version_id]["asset_content_hash"],
                )
                for version_id in sorted(chunks)
            ],
            *[
                _input_asset(
                    version_id,
                    "source_deconstruction_observation",
                    observations[version_id]["content_hash"],
                )
                for version_id in sorted(observations)
            ],
        ]
        return self._admit(
            definition_name=MKAOS_CANDIDATE_OPERATION,
            definition_version=MKAOS_CANDIDATE_DEFINITION_VERSION,
            handler_key=MKAOS_CANDIDATE_HANDLER_KEY,
            permission="mkaos.authority.execute",
            project_id=command.project_id,
            workspace_id=command.workspace_id,
            actor_id=actor_id,
            idempotency_scope="project:mkaos-knowledge-candidate",
            idempotency_key=(
                f"mkaos.knowledge_candidate.commit:{command.project_id}:{candidate_hash}"
            ),
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            causation_id=command.execution_asset_version_id,
            command_payload={
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "execution_asset_version_id": command.execution_asset_version_id,
                "payload": payload,
            },
            input_assets=inputs,
            ready_reason="validated abstract MKAOS Candidate ready",
        )

    def execute_approval(
        self,
        command: ApproveKnowledgeCandidateCommand,
        *,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        admitted = self.admit_approval(command, principal=principal)
        if admitted["status"] == "SUCCEEDED":
            return admitted
        return self._run(str(admitted["operation_id"]), command.project_id)

    def admit_approval(
        self,
        command: ApproveKnowledgeCandidateCommand,
        *,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        actor_id = self._actor(
            command.actor_id,
            principal,
            "mkaos.authority.approve",
            command.project_id,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = MkaosAuthorityRepository(uow.cursor)
            repository.require_scope(
                project_id=command.project_id, workspace_id=command.workspace_id
            )
            existing = repository.existing_approval(
                project_id=command.project_id,
                candidate_asset_version_id=command.candidate_asset_version_id,
            )
            if existing is not None:
                if existing["operation_status"] != "SUCCEEDED":
                    raise KernelError(
                        "MKAOS_APPROVAL_RECOVERY_REQUIRED",
                        "existing approval Operation is incomplete and requires recovery",
                    )
                return {
                    **existing,
                    "project_id": command.project_id,
                    "status": "SUCCEEDED",
                    "replayed": True,
                    "duplicate": True,
                }
            candidate = repository.candidate_for_approval(
                project_id=command.project_id,
                asset_version_id=command.candidate_asset_version_id,
            )
        approval_contract = self._require_approvable(
            candidate,
            project_id=command.project_id,
            workspace_id=command.workspace_id,
            policy_version=command.policy_version,
            reviewer_id=actor_id,
            approval_class=command.approval_class,
        )
        assert_abstract_content_safe(candidate["content"])
        payload = {
            "policy_version": command.policy_version,
            "rationale": command.rationale,
            "reviewer_id": actor_id,
            "approval_contract": approval_contract,
            "candidate_content_hash": candidate["content_hash"],
            "client_idempotency_key": command.idempotency_key,
        }
        return self._admit(
            definition_name=MKAOS_APPROVE_OPERATION,
            definition_version=MKAOS_APPROVE_DEFINITION_VERSION,
            handler_key=MKAOS_APPROVE_HANDLER_KEY,
            permission="mkaos.authority.approve",
            project_id=command.project_id,
            workspace_id=command.workspace_id,
            actor_id=actor_id,
            idempotency_scope="project:mkaos-knowledge-approve",
            idempotency_key=(
                f"mkaos.knowledge.approve:{command.project_id}:"
                f"{command.candidate_asset_version_id}"
            ),
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            causation_id=str(candidate["created_by_operation_id"]),
            command_payload={
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "candidate_asset_version_id": command.candidate_asset_version_id,
                "payload": payload,
            },
            input_assets=[
                _input_asset(
                    command.candidate_asset_version_id,
                    "knowledge_candidate",
                    candidate["content_hash"],
                )
            ],
            ready_reason="MKAOS governance approval decision ready",
        )

    def execute_pack(
        self,
        command: BuildKnowledgePackCommand,
        *,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        admitted = self.admit_pack(command, principal=principal)
        if admitted["status"] == "SUCCEEDED":
            return admitted
        return self._run(str(admitted["operation_id"]), command.project_id)

    def admit_pack(
        self,
        command: BuildKnowledgePackCommand,
        *,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        actor_id = self._actor(
            command.actor_id,
            principal,
            "mkaos.authority.execute",
            command.project_id,
        )
        target, cards, selections, selection_hash = self._preflight_pack(command)
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = MkaosAuthorityRepository(uow.cursor)
            existing = repository.existing_pack(
                project_id=command.project_id,
                target_asset_version_id=command.target_asset_version_id,
                selection_hash=selection_hash,
            )
            active = repository.active_pack_for_target(
                project_id=command.project_id,
                target_asset_version_id=command.target_asset_version_id,
            )
        if existing is not None:
            if existing["operation_status"] != "SUCCEEDED":
                raise KernelError(
                    "MKAOS_PACK_RECOVERY_REQUIRED",
                    "existing KnowledgePack Operation is incomplete and requires recovery",
                )
            return {
                **existing,
                "project_id": command.project_id,
                "status": "SUCCEEDED",
                "replayed": True,
                "duplicate": True,
            }
        if active is not None:
            if command.supersedes_pack_asset_version_id != active["asset_version_id"]:
                raise KernelError(
                    "MKAOS_PACK_ACTIVE_CONFLICT",
                    "target already has a different Active KnowledgePack; provide its exact AssetVersion to supersede",
                )
        elif command.supersedes_pack_asset_version_id:
            raise KernelError(
                "MKAOS_PACK_SUPERSEDE_TARGET_MISSING",
                "the expected Active KnowledgePack no longer exists",
            )
        selection_payload = [
            {
                "knowledge_card_asset_version_id": item.knowledge_card_asset_version_id,
                "usage_role": item.usage_role,
                "frozen_weight": str(item.frozen_weight),
                "content_hash": cards[item.knowledge_card_asset_version_id]["content_hash"],
            }
            for item in selections
        ]
        return self._admit(
            definition_name=MKAOS_PACK_OPERATION,
            definition_version=MKAOS_PACK_DEFINITION_VERSION,
            handler_key=MKAOS_PACK_HANDLER_KEY,
            permission="mkaos.authority.execute",
            project_id=command.project_id,
            workspace_id=command.workspace_id,
            actor_id=actor_id,
            idempotency_scope="project:mkaos-knowledge-pack",
            idempotency_key=(
                f"mkaos.knowledge_pack.build:{command.project_id}:"
                f"{command.target_asset_version_id}:{selection_hash}"
            ),
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            causation_id=command.target_asset_version_id,
            command_payload={
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "target_asset_version_id": command.target_asset_version_id,
                "payload": {
                    "selector_policy_version": command.selector_policy_version,
                    "selector_policy_hash": command.selector_policy_hash,
                    "selection_hash": selection_hash,
                    "selections": selection_payload,
                    "directory_selection_used": False,
                    "learned_weight_applied": False,
                    "client_idempotency_key": command.idempotency_key,
                    "supersedes_pack_asset_version_id": (
                        command.supersedes_pack_asset_version_id
                    ),
                },
            },
            input_assets=[
                _input_asset(
                    target["asset_version_id"], "pack_target", target["content_hash"]
                ),
                *[
                    _input_asset(version_id, "knowledge_card", cards[version_id]["content_hash"])
                    for version_id in sorted(cards)
                ],
                *(
                    [
                        _input_asset(
                            str(active["asset_version_id"]),
                            "superseded_knowledge_pack",
                            str(active["content_hash"]),
                        )
                    ]
                    if active is not None
                    else []
                ),
            ],
            ready_reason="deterministic explicit-version KnowledgePack ready",
        )

    def _preflight_candidate(
        self, command: CommitKnowledgeCandidateCommand
    ) -> tuple[
        dict[str, Any],
        dict[str, Any],
        dict[str, dict[str, Any]],
        tuple[KnowledgeEvidenceSpan, ...],
        dict[str, dict[str, Any]],
        dict[str, Any],
        str,
    ]:
        candidate = validate_knowledge_candidate(command.candidate)
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = MkaosAuthorityRepository(uow.cursor)
            repository.require_scope(
                project_id=command.project_id, workspace_id=command.workspace_id
            )
            execution = repository.execution_evidence(
                project_id=command.project_id,
                asset_version_id=command.execution_asset_version_id,
            )
            execution_proof = _execution_proof(execution["content"])
            chunk_ids = tuple(
                sorted(
                    {span.source_chunk_asset_version_id for span in command.evidence_spans}
                )
            )
            chunks = repository.source_chunks(
                project_id=command.project_id, asset_version_ids=chunk_ids
            )
            source_intelligence = SourceIntelligenceRepository(uow.cursor)
            observations = source_intelligence.observations(
                project_id=command.project_id,
                asset_version_ids=command.observation_asset_version_ids,
            )
            observation_chunks = source_intelligence.observation_source_chunk_inputs(
                project_id=command.project_id,
                asset_version_ids=command.observation_asset_version_ids,
            )
        if len(chunks) != len(chunk_ids):
            raise KernelError(
                "MKAOS_SOURCE_CHUNK_NOT_FOUND",
                "one or more evidence SourceChunk versions do not exist in the project",
            )
        spans = validate_evidence_spans(
            command.evidence_spans,
            source_chunk_sizes={key: int(value["byte_size"]) for key, value in chunks.items()},
        )
        if len(observations) != len(set(command.observation_asset_version_ids)):
            raise KernelError(
                "MKAOS_OBSERVATION_NOT_FOUND",
                "one or more deconstruction Observations are unavailable",
            )
        for observation in observations.values():
            if (
                observation["lifecycle"],
                observation["eligibility"],
                observation["governance"],
            ) != ("ACTIVE", "INELIGIBLE", "CLEAR"):
                raise KernelError(
                    "MKAOS_OBSERVATION_INELIGIBLE",
                    "MKAOS abstraction requires an active evidence-only Observation",
                )
            if observation["evidence_class"] == "FIXTURE" and not self.allow_fixture_activation:
                raise KernelError(
                    "MKAOS_FIXTURE_OBSERVATION_BLOCKED",
                    "fixture Observation cannot enter the controlled MKAOS knowledge chain",
                )
        permitted_chunks = set().union(*observation_chunks.values())
        if observations and set(chunks) - permitted_chunks:
            raise KernelError(
                "MKAOS_OBSERVATION_EVIDENCE_CONFLICT",
                "Candidate EvidenceSpan is outside the referenced Observation lineage",
            )
        execution_binding = _candidate_execution_binding(
            execution["content"],
            fixture_protocol_only=execution_proof["fixture_protocol_only"],
            candidate_payload_hash=_hash(candidate),
            abstraction_policy_version=command.abstraction_policy_version,
            evidence_spans=spans,
            observation_asset_version_ids=tuple(sorted(observations)),
        )
        candidate_hash = _hash(
            {
                "candidate": candidate,
                "execution_asset_version_id": command.execution_asset_version_id,
                "execution_content_hash": execution["content_hash"],
                "execution_proof": execution_proof,
                "abstraction_policy_version": command.abstraction_policy_version,
                "evidence_spans": [asdict(span) for span in spans],
                "observation_asset_version_ids": sorted(observations),
                "execution_binding": execution_binding,
            }
        )
        return (
            candidate,
            execution,
            chunks,
            spans,
            observations,
            execution_binding,
            candidate_hash,
        )

    def _preflight_pack(
        self, command: BuildKnowledgePackCommand
    ) -> tuple[
        dict[str, Any],
        dict[str, dict[str, Any]],
        tuple[KnowledgePackSelection, ...],
        str,
    ]:
        selections = validate_pack_selections(command.selections)
        identities = tuple(
            item.knowledge_card_asset_version_id for item in selections
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = MkaosAuthorityRepository(uow.cursor)
            repository.require_scope(
                project_id=command.project_id, workspace_id=command.workspace_id
            )
            target = repository.target_asset(
                project_id=command.project_id,
                asset_version_id=command.target_asset_version_id,
            )
            cards = repository.knowledge_cards(
                project_id=command.project_id, asset_version_ids=identities
            )
        if len(cards) != len(identities):
            raise KernelError(
                "MKAOS_KNOWLEDGE_CARD_NOT_FOUND",
                "one or more selected KnowledgeCard versions are unavailable",
            )
        for card in cards.values():
            if (
                card["status"],
                card["lifecycle"],
                card["eligibility"],
                card["governance"],
            ) != ("ACTIVE", "ACTIVE", "ELIGIBLE", "CLEAR"):
                raise KernelError(
                    "MKAOS_KNOWLEDGE_CARD_INELIGIBLE",
                    "KnowledgePack selection contains an ineligible KnowledgeCard version",
                )
            assert_abstract_content_safe(card["content"])
        selection_hash = _hash(
            {
                "target_asset_version_id": command.target_asset_version_id,
                "target_content_hash": target["content_hash"],
                "selector_policy_version": command.selector_policy_version,
                "selector_policy_hash": command.selector_policy_hash,
                "selections": [
                    {
                        "asset_version_id": item.knowledge_card_asset_version_id,
                        "usage_role": item.usage_role,
                        "frozen_weight": str(item.frozen_weight),
                        "content_hash": cards[item.knowledge_card_asset_version_id]["content_hash"],
                    }
                    for item in selections
                ],
            }
        )
        return target, cards, selections, selection_hash

    def _admit(
        self,
        *,
        definition_name: str,
        definition_version: str,
        handler_key: str,
        permission: str,
        project_id: str,
        workspace_id: str,
        actor_id: str,
        idempotency_scope: str,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
        causation_id: str,
        command_payload: dict[str, Any],
        input_assets: list[dict[str, Any]],
        ready_reason: str,
    ) -> dict[str, Any]:
        self._register_definitions()
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": definition_name,
                "definition_version": definition_version,
                "project_id": project_id,
                "workspace_id": workspace_id,
                "actor_id": actor_id,
                "idempotency_scope": idempotency_scope,
                "idempotency_key": idempotency_key,
                "trace_id": trace_id,
                "span_id": str(uuid4()),
                "correlation_id": correlation_id,
                "causation_id": causation_id,
                "input": command_payload,
                "input_assets": input_assets,
            },
            context=AdmissionContext(
                actor_id=actor_id,
                permissions=frozenset({permission}),
                available_handlers=frozenset({handler_key}),
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
        )
        operation_id = str(admitted["operation_id"])
        state = self._operation_state(operation_id, project_id)
        if state["status"] == "SUCCEEDED":
            return self.result(operation_id, project_id, replayed=True)
        if state["status"] == "ADMITTED":
            transition_operation(
                self.database_url,
                OperationTransitionCommand(
                    operation_id=operation_id,
                    project_id=project_id,
                    expected_version=int(state["version"]),
                    expected_status="ADMITTED",
                    target_status="READY",
                    actor_id=actor_id,
                    reason=ready_reason,
                    trace_id=trace_id,
                    correlation_id=correlation_id,
                    causation_id=causation_id,
                ),
            )
            state = self._operation_state(operation_id, project_id)
        return {
            "operation_id": operation_id,
            "project_id": project_id,
            "status": state["status"],
            "replayed": bool(admitted.get("replayed")),
            "duplicate": False,
        }

    def _register_definitions(self) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            for definition in mkaos_authority_definitions(
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ):
                uow.repositories.definitions.register(definition)
            uow.commit()

    def _run(self, operation_id: str, project_id: str) -> dict[str, Any]:
        state = self._operation_state(operation_id, project_id)
        if state["status"] not in {"READY", "FAILED_RETRYABLE"}:
            raise KernelError(
                "MKAOS_OPERATION_NOT_RUNNABLE",
                f"MKAOS Operation is not runnable from {state['status']}",
            )
        attempt = create_attempt(
            self.database_url,
            operation_id=operation_id,
            project_id=project_id,
            max_attempts=2,
            trace_id=str(state["trace_id"]),
            correlation_id=str(state["correlation_id"]),
        )
        if attempt["dead_letter"] or not attempt["attempt_id"]:
            raise KernelError("MKAOS_OPERATION_DEAD_LETTER", "retry policy exhausted")
        attempt_id = str(attempt["attempt_id"])
        queue_attempt(
            self.database_url,
            attempt_id=attempt_id,
            project_id=project_id,
            trace_id=str(state["trace_id"]),
            correlation_id=str(state["correlation_id"]),
        )
        lease = acquire_attempt_lease(
            self.database_url,
            attempt_id=attempt_id,
            project_id=project_id,
            worker_id=self.worker_id,
            lease_seconds=30,
            trace_id=str(state["trace_id"]),
            correlation_id=str(state["correlation_id"]),
        )
        worker = WorkerLeaseCommand(
            attempt_id=attempt_id,
            project_id=project_id,
            worker_id=self.worker_id,
            fencing_token=int(lease["fencing_token"]),
            trace_id=str(state["trace_id"]),
            correlation_id=str(state["correlation_id"]),
            causation_id=operation_id,
        )
        start_attempt(self.database_url, worker)
        try:
            result = self.execute_fenced(worker)
            current = self._operation_state(operation_id, project_id)
            submit_attempt_result(
                self.database_url,
                WorkerResultCommand(
                    **worker.__dict__,
                    expected_operation_version=int(current["version"]),
                    expected_operation_status=str(current["status"]),
                ),
                outcome="success",
                result=result,
            )
        except Exception as exc:
            try:
                submit_attempt_failure(
                    self.database_url,
                    worker,
                    retryable=False,
                    error_code=(
                        exc.code if isinstance(exc, KernelError) else "MKAOS_HANDLER_FAILED"
                    ),
                    error_message=str(exc),
                    failure_class="MKAOS_GOVERNANCE_FAILURE",
                )
            except KernelError:
                pass
            raise
        return self.result(operation_id, project_id, replayed=False)

    def execute_fenced(self, worker: WorkerLeaseCommand) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT definition_name FROM authority_operation
                WHERE operation_id = %s AND project_id = %s
                """,
                [worker.causation_id, worker.project_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("OPERATION_NOT_FOUND", "MKAOS Operation does not exist")
        if row[0] == MKAOS_CANDIDATE_OPERATION:
            return self._execute_candidate_fenced(worker)
        if row[0] == MKAOS_APPROVE_OPERATION:
            return self._execute_approval_fenced(worker)
        if row[0] == MKAOS_PACK_OPERATION:
            return self._execute_pack_fenced(worker)
        raise KernelError(
            "MKAOS_HANDLER_NOT_FOUND", f"unsupported MKAOS Operation: {row[0]}"
        )

    def _execute_candidate_fenced(
        self, worker: WorkerLeaseCommand
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            require_current_fence(uow, worker)
            operation = uow.repositories.chapter_authority.operation_execution(
                worker.causation_id, worker.project_id
            )
            command = dict(operation["command_payload"])
            payload = dict(command["payload"])
            repository = MkaosAuthorityRepository(uow.cursor)
            repository.require_scope(
                project_id=worker.project_id,
                workspace_id=str(command["workspace_id"]),
            )
            execution = repository.execution_evidence(
                project_id=worker.project_id,
                asset_version_id=str(command["execution_asset_version_id"]),
            )
            execution_proof = _execution_proof(execution["content"])
            candidate = validate_knowledge_candidate(dict(payload["candidate"]))
            spans = tuple(
                KnowledgeEvidenceSpan(**item) for item in payload["evidence_spans"]
            )
            chunk_ids = tuple(
                sorted({span.source_chunk_asset_version_id for span in spans})
            )
            chunks = repository.source_chunks(
                project_id=worker.project_id, asset_version_ids=chunk_ids
            )
            observation_ids = tuple(payload.get("observation_asset_version_ids") or ())
            source_intelligence = SourceIntelligenceRepository(uow.cursor)
            observations = source_intelligence.observations(
                project_id=worker.project_id,
                asset_version_ids=observation_ids,
            )
            observation_chunks = source_intelligence.observation_source_chunk_inputs(
                project_id=worker.project_id,
                asset_version_ids=observation_ids,
            )
            if len(chunks) != len(chunk_ids):
                raise KernelError(
                    "MKAOS_SOURCE_CHUNK_NOT_FOUND",
                    "evidence SourceChunk disappeared after admission",
                )
            if len(observations) != len(observation_ids):
                raise KernelError(
                    "MKAOS_OBSERVATION_NOT_FOUND",
                    "deconstruction Observation disappeared after admission",
                )
            for observation in observations.values():
                if (
                    observation["lifecycle"],
                    observation["eligibility"],
                    observation["governance"],
                ) != ("ACTIVE", "INELIGIBLE", "CLEAR"):
                    raise KernelError(
                        "MKAOS_OBSERVATION_INELIGIBLE",
                        "deconstruction Observation became ineligible after admission",
                    )
                if (
                    observation["evidence_class"] == "FIXTURE"
                    and not self.allow_fixture_activation
                ):
                    raise KernelError(
                        "MKAOS_FIXTURE_OBSERVATION_BLOCKED",
                        "fixture Observation cannot enter the controlled MKAOS knowledge chain",
                    )
            permitted_chunks = set().union(*observation_chunks.values())
            if observations and set(chunks) - permitted_chunks:
                raise KernelError(
                    "MKAOS_OBSERVATION_EVIDENCE_CONFLICT",
                    "Candidate EvidenceSpan no longer matches Observation lineage",
                )
            spans = validate_evidence_spans(
                spans,
                source_chunk_sizes={
                    key: int(value["byte_size"]) for key, value in chunks.items()
                },
            )
            execution_binding = _candidate_execution_binding(
                execution["content"],
                fixture_protocol_only=execution_proof["fixture_protocol_only"],
                candidate_payload_hash=_hash(candidate),
                abstraction_policy_version=payload["abstraction_policy_version"],
                evidence_spans=spans,
                observation_asset_version_ids=tuple(sorted(observations)),
            )
            expected_hash = _hash(
                {
                    "candidate": candidate,
                    "execution_asset_version_id": execution["asset_version_id"],
                    "execution_content_hash": execution["content_hash"],
                    "execution_proof": execution_proof,
                    "abstraction_policy_version": payload["abstraction_policy_version"],
                    "evidence_spans": [asdict(span) for span in spans],
                    "observation_asset_version_ids": sorted(observations),
                    "execution_binding": execution_binding,
                }
            )
            if (
                expected_hash != payload["candidate_hash"]
                or execution_binding != payload["execution_binding"]
            ):
                raise KernelError(
                    "MKAOS_CANDIDATE_INPUT_DRIFT",
                    "MKAOS Candidate changed after admission",
                )
            digest = expected_hash.removeprefix("sha256:")
            candidate_id = f"knowledge-candidate:{worker.project_id}:{digest}"
            asset_version_id = f"{candidate_id}:v1"
            content = {
                "schema_version": "mkaos-knowledge-candidate.v1",
                "knowledge_candidate_id": candidate_id,
                "project_id": worker.project_id,
                "workspace_id": str(command["workspace_id"]),
                "candidate": candidate,
                "evidence_spans": [asdict(span) for span in spans],
                "execution_evidence": {
                    "asset_version_id": execution["asset_version_id"],
                    "content_hash": execution["content_hash"],
                    "proof": execution_proof,
                    "binding": execution_binding,
                },
                "abstraction_policy_version": payload[
                    "abstraction_policy_version"
                ],
                "observation_asset_version_ids": sorted(observations),
                "lineage_mode": payload["lineage_mode"],
                "source_policy": {
                    "raw_source_expression_included": False,
                    "generation_eligible": False,
                    "authority_approval_required": True,
                    "fixture_protocol_only": execution_proof[
                        "fixture_protocol_only"
                    ],
                },
                "lineage": {
                    "created_by_operation_id": worker.causation_id,
                    "source_chunk_asset_version_ids": list(chunk_ids),
                    "observation_asset_version_ids": sorted(observations),
                },
            }
            content_hash = _hash(content)
            created = uow.repositories.chapter_authority.materialize_output(
                operation_id=worker.causation_id,
                project_id=worker.project_id,
                asset_id=candidate_id,
                asset_version_id=asset_version_id,
                qualification_id=f"{asset_version_id}:qualification:v1",
                asset_type="knowledge_card_candidate",
                output_key="mkaos.knowledge.candidate",
                role="candidate",
                content=content,
                content_hash=content_hash,
                qualification_policy="mkaos-candidate-isolation-v1",
                qualification_evidence={
                    "operation_id": worker.causation_id,
                    "attempt_id": worker.attempt_id,
                    "fencing_token": worker.fencing_token,
                    "candidate_hash": expected_hash,
                    "raw_source_expression_included": False,
                    "authority_approval_required": True,
                    "fixture_protocol_only": execution_proof[
                        "fixture_protocol_only"
                    ],
                    "production_verified": execution_proof[
                        "production_verified"
                    ],
                },
                lifecycle="CANDIDATE",
                eligibility="PENDING_EVALUATION",
                governance="CLEAR",
            )
            if created:
                repository.register_candidate(
                    {
                        "knowledge_candidate_id": candidate_id,
                        "project_id": worker.project_id,
                        "workspace_id": str(command["workspace_id"]),
                        "asset_version_id": asset_version_id,
                        "execution_asset_version_id": execution["asset_version_id"],
                        "created_by_operation_id": worker.causation_id,
                        "candidate_hash": expected_hash,
                        "abstraction_policy_version": payload[
                            "abstraction_policy_version"
                        ],
                    }
                )
                for index, span in enumerate(spans):
                    chunk = chunks[span.source_chunk_asset_version_id]
                    repository.register_evidence_span(
                        {
                            "evidence_span_id": f"{asset_version_id}:evidence:{index}",
                            "project_id": worker.project_id,
                            "candidate_asset_version_id": asset_version_id,
                            "source_chunk_id": chunk["source_chunk_id"],
                            "source_chunk_asset_version_id": span.source_chunk_asset_version_id,
                            "chunk_byte_start": span.chunk_byte_start,
                            "chunk_byte_end": span.chunk_byte_end,
                            "evidence_hash": span.evidence_hash,
                            "created_by_operation_id": worker.causation_id,
                        }
                    )
                dependencies = SourceIntelligenceRepository(uow.cursor)
                for observation_id in sorted(observations):
                    dependencies.record_dependency(
                        {
                            "dependency_id": str(uuid4()),
                            "project_id": worker.project_id,
                            "upstream_asset_version_id": observation_id,
                            "downstream_asset_version_id": asset_version_id,
                            "relationship": "ABSTRACTS",
                            "selector_key": str(
                                payload["abstraction_policy_version"]
                            ),
                            "created_by_operation_id": worker.causation_id,
                        }
                    )
                self._event(
                    uow,
                    worker,
                    aggregate_type="authority_mkaos_knowledge_candidate",
                    aggregate_id=candidate_id,
                    event_type="authority.mkaos.knowledge_candidate.committed",
                    causation_id=execution["asset_version_id"],
                    payload={
                        "knowledge_candidate_id": candidate_id,
                        "asset_version_id": asset_version_id,
                        "candidate_hash": expected_hash,
                        "evidence_span_count": len(spans),
                        "status": "NEEDS_REVIEW",
                    },
                )
            uow.commit()
        return {
            "knowledge_candidate_id": candidate_id,
            "asset_version_id": asset_version_id,
            "candidate_hash": expected_hash,
        }

    def _execute_approval_fenced(
        self, worker: WorkerLeaseCommand
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            require_current_fence(uow, worker)
            operation = uow.repositories.chapter_authority.operation_execution(
                worker.causation_id, worker.project_id
            )
            command = dict(operation["command_payload"])
            payload = dict(command["payload"])
            repository = MkaosAuthorityRepository(uow.cursor)
            repository.require_scope(
                project_id=worker.project_id,
                workspace_id=str(command["workspace_id"]),
            )
            candidate = repository.candidate_for_approval(
                project_id=worker.project_id,
                asset_version_id=str(command["candidate_asset_version_id"]),
            )
            approval_contract = self._require_approvable(
                candidate,
                project_id=worker.project_id,
                workspace_id=str(command["workspace_id"]),
                policy_version=str(payload["policy_version"]),
                reviewer_id=str(payload["reviewer_id"]),
                approval_class=str(
                    dict(payload.get("approval_contract") or {}).get(
                        "approval_class"
                    )
                    or "PRODUCTION"
                ),
            )
            if approval_contract != dict(payload.get("approval_contract") or {}):
                raise KernelError(
                    "MKAOS_APPROVAL_POLICY_DRIFT",
                    "MKAOS approval scope changed after admission",
                )
            if candidate["content_hash"] != payload["candidate_content_hash"]:
                raise KernelError(
                    "MKAOS_CANDIDATE_INPUT_DRIFT",
                    "MKAOS Candidate Hash changed after approval admission",
                )
            assert_abstract_content_safe(candidate["content"])
            digest = hashlib.sha256(
                str(candidate["asset_version_id"]).encode("utf-8")
            ).hexdigest()
            decision_id = f"knowledge-decision:{worker.project_id}:{digest}"
            decision_asset_version_id = f"{decision_id}:v1"
            decision_content = {
                "schema_version": "mkaos-governance-decision.v1",
                "governance_decision_id": decision_id,
                "candidate_asset_version_id": candidate["asset_version_id"],
                "decision": "APPROVE",
                "reviewer_id": payload["reviewer_id"],
                "policy_version": payload["policy_version"],
                "approval_contract": approval_contract,
                "rationale": payload["rationale"],
                "candidate_content_hash": candidate["content_hash"],
                "created_by_operation_id": worker.causation_id,
            }
            decision_hash = _hash(decision_content)
            decision_created = uow.repositories.chapter_authority.materialize_output(
                operation_id=worker.causation_id,
                project_id=worker.project_id,
                asset_id=decision_id,
                asset_version_id=decision_asset_version_id,
                qualification_id=f"{decision_asset_version_id}:qualification:v1",
                asset_type="knowledge_governance_decision",
                output_key="mkaos.knowledge.decision",
                role="decision",
                content=decision_content,
                content_hash=decision_hash,
                qualification_policy="mkaos-governance-decision-v1",
                qualification_evidence={
                    "operation_id": worker.causation_id,
                    "candidate_asset_version_id": candidate["asset_version_id"],
                    "decision": "APPROVE",
                    "reviewer_id": payload["reviewer_id"],
                    "approval_class": approval_contract["approval_class"],
                    "review_class": approval_contract["review_class"],
                },
                lifecycle="ACTIVE",
                eligibility="ELIGIBLE",
                governance="CLEAR",
            )
            card_id = f"knowledge-card:{worker.project_id}:{digest}"
            card_asset_version_id = f"{card_id}:v1"
            candidate_payload = dict(candidate["content"]["candidate"])
            card_content = {
                "schema_version": "mkaos-knowledge-card.v1",
                "knowledge_card_id": card_id,
                "project_id": worker.project_id,
                "workspace_id": str(command["workspace_id"]),
                "abstract_content": candidate_payload,
                "source_policy": {
                    "raw_source_expression_included": False,
                    "source_chunks_direct_context_eligible": False,
                    "knowledge_card_context_eligible": True,
                    "production_context_eligible": approval_contract[
                        "production_context_eligible"
                    ],
                    "experimental_context_eligible": approval_contract[
                        "experimental_context_eligible"
                    ],
                    "approval_class": approval_contract["approval_class"],
                    "review_class": approval_contract["review_class"],
                    "activation_scope": approval_contract["activation_scope"],
                    "approval_policy_version": approval_contract["policy_version"],
                    "fixture_protocol_only": candidate["content"][
                        "execution_evidence"
                    ]["proof"]["fixture_protocol_only"],
                },
                "lineage": {
                    "candidate_asset_version_id": candidate["asset_version_id"],
                    "execution_asset_version_id": candidate[
                        "execution_asset_version_id"
                    ],
                    "source_chunk_asset_version_ids": list(
                        candidate["content"]["lineage"][
                            "source_chunk_asset_version_ids"
                        ]
                    ),
                    "observation_asset_version_ids": list(
                        candidate["content"]["lineage"].get(
                            "observation_asset_version_ids", []
                        )
                    ),
                    "governance_decision_asset_version_id": decision_asset_version_id,
                    "created_by_operation_id": worker.causation_id,
                },
            }
            assert_abstract_content_safe(card_content)
            card_hash = _hash(card_content)
            card_created = uow.repositories.chapter_authority.materialize_output(
                operation_id=worker.causation_id,
                project_id=worker.project_id,
                asset_id=card_id,
                asset_version_id=card_asset_version_id,
                qualification_id=f"{card_asset_version_id}:qualification:v1",
                asset_type="knowledge_card",
                output_key="mkaos.knowledge.card",
                role="primary",
                content=card_content,
                content_hash=card_hash,
                qualification_policy=(
                    "mkaos-knowledge-experimental-activation-v1"
                    if approval_contract["approval_class"]
                    == "EXPERIMENTAL_VALIDATION"
                    else "mkaos-knowledge-activation-v1"
                ),
                qualification_evidence={
                    "operation_id": worker.causation_id,
                    "attempt_id": worker.attempt_id,
                    "fencing_token": worker.fencing_token,
                    "candidate_asset_version_id": candidate["asset_version_id"],
                    "governance_decision_asset_version_id": decision_asset_version_id,
                    "raw_source_expression_included": False,
                    "fixture_protocol_only": candidate["content"][
                        "execution_evidence"
                    ]["proof"]["fixture_protocol_only"],
                    "production_verified": candidate["content"][
                        "execution_evidence"
                    ]["proof"]["production_verified"],
                    "approval_contract": approval_contract,
                },
                lifecycle="ACTIVE",
                eligibility="ELIGIBLE",
                governance="CLEAR",
            )
            if decision_created != card_created:
                raise KernelError(
                    "MKAOS_APPROVAL_REPLAY_CONFLICT",
                    "Decision and KnowledgeCard replay state differs",
                )
            if decision_created:
                repository.register_decision(
                    {
                        "governance_decision_id": decision_id,
                        "project_id": worker.project_id,
                        "workspace_id": str(command["workspace_id"]),
                        "asset_version_id": decision_asset_version_id,
                        "candidate_asset_version_id": candidate["asset_version_id"],
                        "created_by_operation_id": worker.causation_id,
                        "decision": "APPROVE",
                        "reviewer_id": payload["reviewer_id"],
                        "policy_version": payload["policy_version"],
                        "rationale_hash": _hash({"rationale": payload["rationale"]}),
                    }
                )
                repository.register_card(
                    {
                        "knowledge_card_id": card_id,
                        "project_id": worker.project_id,
                        "workspace_id": str(command["workspace_id"]),
                        "asset_version_id": card_asset_version_id,
                        "candidate_asset_version_id": candidate["asset_version_id"],
                        "governance_decision_asset_version_id": decision_asset_version_id,
                        "created_by_operation_id": worker.causation_id,
                        "content_hash": card_hash,
                    }
                )
                dependencies = SourceIntelligenceRepository(uow.cursor)
                self._content_dependency(
                    dependencies,
                    worker,
                    upstream=candidate["asset_version_id"],
                    downstream=decision_asset_version_id,
                    relationship="GOVERNS",
                    selector_key=str(payload["policy_version"]),
                )
                self._content_dependency(
                    dependencies,
                    worker,
                    upstream=candidate["asset_version_id"],
                    downstream=card_asset_version_id,
                    relationship="ACTIVATES",
                    selector_key=str(payload["policy_version"]),
                )
                self._content_dependency(
                    dependencies,
                    worker,
                    upstream=decision_asset_version_id,
                    downstream=card_asset_version_id,
                    relationship="ACTIVATES",
                    selector_key=str(payload["policy_version"]),
                )
                self._event(
                    uow,
                    worker,
                    aggregate_type="authority_mkaos_knowledge_card",
                    aggregate_id=card_id,
                    event_type="authority.mkaos.knowledge.approved",
                    causation_id=candidate["asset_version_id"],
                    payload={
                        "knowledge_card_id": card_id,
                        "asset_version_id": card_asset_version_id,
                        "candidate_asset_version_id": candidate["asset_version_id"],
                        "governance_decision_asset_version_id": decision_asset_version_id,
                        "approval_class": approval_contract["approval_class"],
                        "review_class": approval_contract["review_class"],
                    },
                )
            uow.commit()
        return {
            "knowledge_card_id": card_id,
            "asset_version_id": card_asset_version_id,
            "governance_decision_asset_version_id": decision_asset_version_id,
            "approval_class": approval_contract["approval_class"],
            "review_class": approval_contract["review_class"],
        }

    def _execute_pack_fenced(self, worker: WorkerLeaseCommand) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            require_current_fence(uow, worker)
            operation = uow.repositories.chapter_authority.operation_execution(
                worker.causation_id, worker.project_id
            )
            command = dict(operation["command_payload"])
            payload = dict(command["payload"])
            repository = MkaosAuthorityRepository(uow.cursor)
            repository.require_scope(
                project_id=worker.project_id,
                workspace_id=str(command["workspace_id"]),
            )
            target = repository.target_asset(
                project_id=worker.project_id,
                asset_version_id=str(command["target_asset_version_id"]),
                for_update=True,
            )
            active = repository.active_pack_for_target(
                project_id=worker.project_id,
                target_asset_version_id=target["asset_version_id"],
            )
            if active is not None:
                if active["selection_hash"] == payload["selection_hash"]:
                    raise KernelError(
                        "MKAOS_PACK_RECOVERY_REQUIRED",
                        "an Active KnowledgePack already materialized for this selection",
                    )
                if active["asset_version_id"] != payload.get(
                    "supersedes_pack_asset_version_id"
                ):
                    raise KernelError(
                        "MKAOS_PACK_ACTIVE_CONFLICT",
                        "Active KnowledgePack changed after admission",
                    )
            elif payload.get("supersedes_pack_asset_version_id"):
                raise KernelError(
                    "MKAOS_PACK_SUPERSEDE_TARGET_MISSING",
                    "Active KnowledgePack disappeared after admission",
                )
            selections = validate_pack_selections(
                tuple(
                    KnowledgePackSelection(
                        knowledge_card_asset_version_id=str(
                            item["knowledge_card_asset_version_id"]
                        ),
                        usage_role=str(item["usage_role"]),
                        frozen_weight=Decimal(str(item["frozen_weight"])),
                    )
                    for item in payload["selections"]
                )
            )
            identities = tuple(
                item.knowledge_card_asset_version_id for item in selections
            )
            cards = repository.knowledge_cards(
                project_id=worker.project_id, asset_version_ids=identities
            )
            if len(cards) != len(identities):
                raise KernelError(
                    "MKAOS_KNOWLEDGE_CARD_NOT_FOUND",
                    "selected KnowledgeCard disappeared after admission",
                )
            for card in cards.values():
                if (
                    card["status"],
                    card["lifecycle"],
                    card["eligibility"],
                    card["governance"],
                ) != ("ACTIVE", "ACTIVE", "ELIGIBLE", "CLEAR"):
                    raise KernelError(
                        "MKAOS_KNOWLEDGE_CARD_INELIGIBLE",
                        "selected KnowledgeCard is no longer eligible",
                    )
                assert_abstract_content_safe(card["content"])
            expected_hash = _hash(
                {
                    "target_asset_version_id": target["asset_version_id"],
                    "target_content_hash": target["content_hash"],
                    "selector_policy_version": payload["selector_policy_version"],
                    "selector_policy_hash": payload["selector_policy_hash"],
                    "selections": [
                        {
                            "asset_version_id": item.knowledge_card_asset_version_id,
                            "usage_role": item.usage_role,
                            "frozen_weight": str(item.frozen_weight),
                            "content_hash": cards[
                                item.knowledge_card_asset_version_id
                            ]["content_hash"],
                        }
                        for item in selections
                    ],
                }
            )
            if expected_hash != payload["selection_hash"]:
                raise KernelError(
                    "MKAOS_PACK_INPUT_DRIFT",
                    "KnowledgePack selection changed after admission",
                )
            digest = expected_hash.removeprefix("sha256:")
            pack_id = f"knowledge-pack:{worker.project_id}:{digest}"
            asset_version_id = f"{pack_id}:v1"
            items = [
                {
                    "knowledge_card_asset_version_id": item.knowledge_card_asset_version_id,
                    "content_hash": cards[item.knowledge_card_asset_version_id][
                        "content_hash"
                    ],
                    "usage_role": item.usage_role,
                    "frozen_weight": str(item.frozen_weight),
                    "ordinal": index,
                }
                for index, item in enumerate(selections)
            ]
            content = {
                "schema_version": "mkaos-knowledge-pack.v1",
                "knowledge_pack_id": pack_id,
                "project_id": worker.project_id,
                "workspace_id": str(command["workspace_id"]),
                "target_asset_version_id": target["asset_version_id"],
                "target_content_hash": target["content_hash"],
                "selector_policy_version": payload["selector_policy_version"],
                "selector_policy_hash": payload["selector_policy_hash"],
                "selection_hash": expected_hash,
                "items": items,
                "source_policy": {
                    "explicit_asset_versions_only": True,
                    "directory_selection_used": False,
                    "raw_source_expression_included": False,
                    "learned_weight_applied": False,
                },
                "lineage": {
                    "created_by_operation_id": worker.causation_id,
                    "knowledge_card_asset_version_ids": list(identities),
                    "supersedes_pack_asset_version_id": payload.get(
                        "supersedes_pack_asset_version_id"
                    )
                    or None,
                },
            }
            content_hash = _hash(content)
            created = uow.repositories.chapter_authority.materialize_output(
                operation_id=worker.causation_id,
                project_id=worker.project_id,
                asset_id=pack_id,
                asset_version_id=asset_version_id,
                qualification_id=f"{asset_version_id}:qualification:v1",
                asset_type="knowledge_pack",
                output_key="mkaos.knowledge.pack",
                role="primary",
                content=content,
                content_hash=content_hash,
                qualification_policy="mkaos-deterministic-pack-v1",
                qualification_evidence={
                    "operation_id": worker.causation_id,
                    "attempt_id": worker.attempt_id,
                    "fencing_token": worker.fencing_token,
                    "target_asset_version_id": target["asset_version_id"],
                    "selection_hash": expected_hash,
                    "explicit_asset_versions_only": True,
                    "raw_source_expression_included": False,
                },
                lifecycle="ACTIVE",
                eligibility="ELIGIBLE",
                governance="CLEAR",
            )
            if created:
                if active is not None:
                    repository.supersede_pack(
                        project_id=worker.project_id,
                        asset_version_id=str(active["asset_version_id"]),
                        expected_selection_hash=str(active["selection_hash"]),
                    )
                repository.register_pack(
                    {
                        "knowledge_pack_id": pack_id,
                        "project_id": worker.project_id,
                        "workspace_id": str(command["workspace_id"]),
                        "asset_version_id": asset_version_id,
                        "target_asset_version_id": target["asset_version_id"],
                        "created_by_operation_id": worker.causation_id,
                        "selector_policy_version": payload[
                            "selector_policy_version"
                        ],
                        "selector_policy_hash": payload["selector_policy_hash"],
                        "selection_hash": expected_hash,
                        "item_count": len(items),
                    }
                )
                for item in items:
                    repository.register_pack_item(
                        {
                            "knowledge_pack_id": pack_id,
                            "knowledge_pack_asset_version_id": asset_version_id,
                            "knowledge_card_asset_version_id": item[
                                "knowledge_card_asset_version_id"
                            ],
                            "ordinal": item["ordinal"],
                            "usage_role": item["usage_role"],
                            "frozen_weight": item["frozen_weight"],
                            "created_by_operation_id": worker.causation_id,
                        }
                    )
                dependencies = SourceIntelligenceRepository(uow.cursor)
                for item in items:
                    self._content_dependency(
                        dependencies,
                        worker,
                        upstream=item["knowledge_card_asset_version_id"],
                        downstream=asset_version_id,
                        relationship="SELECTS",
                        selector_key=str(payload["selector_policy_hash"]),
                    )
                self._content_dependency(
                    dependencies,
                    worker,
                    upstream=target["asset_version_id"],
                    downstream=asset_version_id,
                    relationship="PROJECTS",
                    selector_key=str(payload["selector_policy_hash"]),
                )
                self._event(
                    uow,
                    worker,
                    aggregate_type="authority_mkaos_knowledge_pack",
                    aggregate_id=pack_id,
                    event_type="authority.mkaos.knowledge_pack.built",
                    causation_id=target["asset_version_id"],
                    payload={
                        "knowledge_pack_id": pack_id,
                        "asset_version_id": asset_version_id,
                        "target_asset_version_id": target["asset_version_id"],
                        "selection_hash": expected_hash,
                        "item_count": len(items),
                    },
                )
            uow.commit()
        return {
            "knowledge_pack_id": pack_id,
            "asset_version_id": asset_version_id,
            "selection_hash": expected_hash,
            "item_count": len(items),
        }

    def _operation_state(self, operation_id: str, project_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(
                operation_id, project_id
            )
            uow.cursor.execute(
                """
                SELECT trace_id, correlation_id FROM authority_operation
                WHERE operation_id = %s AND project_id = %s
                """,
                [operation_id, project_id],
            )
            row = uow.cursor.fetchone()
        return {**state, "trace_id": row[0], "correlation_id": row[1]}

    def result(
        self, operation_id: str, project_id: str, *, replayed: bool
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT definition_name, status FROM authority_operation
                WHERE operation_id = %s AND project_id = %s
                """,
                [operation_id, project_id],
            )
            operation = uow.cursor.fetchone()
            if operation is None:
                raise KernelError("OPERATION_NOT_FOUND", "MKAOS Operation does not exist")
            if operation[0] == MKAOS_CANDIDATE_OPERATION:
                sql = """
                    SELECT knowledge_candidate_id, asset_version_id,
                           candidate_hash, status
                    FROM authority_mkaos_knowledge_candidate
                    WHERE created_by_operation_id = %s AND project_id = %s
                """
                keys = (
                    "knowledge_candidate_id",
                    "asset_version_id",
                    "candidate_hash",
                    "candidate_status",
                )
            elif operation[0] == MKAOS_APPROVE_OPERATION:
                sql = """
                    SELECT knowledge_card_id, asset_version_id,
                           governance_decision_asset_version_id, status
                    FROM authority_mkaos_knowledge_card
                    WHERE created_by_operation_id = %s AND project_id = %s
                """
                keys = (
                    "knowledge_card_id",
                    "asset_version_id",
                    "governance_decision_asset_version_id",
                    "card_status",
                )
            elif operation[0] == MKAOS_PACK_OPERATION:
                sql = """
                    SELECT knowledge_pack_id, asset_version_id,
                           selection_hash, item_count, status
                    FROM authority_mkaos_knowledge_pack
                    WHERE created_by_operation_id = %s AND project_id = %s
                """
                keys = (
                    "knowledge_pack_id",
                    "asset_version_id",
                    "selection_hash",
                    "item_count",
                    "pack_status",
                )
            else:
                raise KernelError(
                    "MKAOS_HANDLER_NOT_FOUND",
                    f"unsupported MKAOS Operation: {operation[0]}",
                )
            uow.cursor.execute(sql, [operation_id, project_id])
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("MKAOS_RESULT_MISSING", "MKAOS Operation result is missing")
        return {
            "operation_id": operation_id,
            "project_id": project_id,
            **dict(zip(keys, row, strict=True)),
            "status": operation[1],
            "replayed": replayed,
            "duplicate": False,
        }

    @staticmethod
    def _actor(
        actor_id: str,
        principal: Principal | None,
        permission: str,
        project_id: str,
    ) -> str:
        if principal is None:
            return actor_id
        principal.require(permission, project_id)
        return principal.principal_id

    def _require_approvable(
        self,
        candidate: dict[str, Any],
        *,
        project_id: str,
        workspace_id: str,
        policy_version: str,
        reviewer_id: str,
        approval_class: str,
    ) -> dict[str, Any]:
        if candidate["workspace_id"] != workspace_id:
            raise KernelError(
                "MKAOS_PROJECT_SCOPE_INVALID",
                "candidate belongs to another workspace",
            )
        if (
            candidate["status"],
            candidate["lifecycle"],
            candidate["eligibility"],
            candidate["governance"],
        ) != ("NEEDS_REVIEW", "CANDIDATE", "PENDING_EVALUATION", "CLEAR"):
            raise KernelError(
                "MKAOS_CANDIDATE_STATUS_CONFLICT",
                "only a clear Candidate awaiting review can be approved",
            )
        proof = dict(
            candidate["content"].get("execution_evidence", {}).get("proof", {})
        )
        if proof.get("fixture_protocol_only") and not self.allow_fixture_activation:
            raise KernelError(
                "MKAOS_FIXTURE_CANDIDATE_NOT_ACTIVATABLE",
                "fixture execution can prove the protocol but cannot activate a production KnowledgeCard",
            )
        if approval_class == "PRODUCTION":
            if not proof.get("fixture_protocol_only") and not (
                proof.get("real_provider_proven")
                and proof.get("production_verified")
            ):
                raise KernelError(
                    "MKAOS_EXECUTION_NOT_PRODUCTION_VERIFIED",
                    "production activation requires verified real-provider execution evidence",
                )
            return {
                "schema_version": "mkaos-approval-contract.v1",
                "approval_class": "PRODUCTION",
                "review_class": "GOVERNANCE_REVIEW",
                "activation_scope": {
                    "kind": "PROJECT",
                    "project_id": project_id,
                    "workspace_id": workspace_id,
                },
                "project_id": project_id,
                "workspace_id": workspace_id,
                "policy_version": policy_version,
                "reviewer_id": reviewer_id,
                "production_context_eligible": True,
                "experimental_context_eligible": False,
            }
        experimental = self.experimental_approval_policy
        if (
            approval_class != "EXPERIMENTAL_VALIDATION"
            or experimental is None
            or (
                project_id,
                workspace_id,
                policy_version,
                reviewer_id,
            )
            != (
                experimental.project_id,
                experimental.workspace_id,
                experimental.policy_version,
                experimental.reviewer_id,
            )
            or candidate["project_id"] != project_id
        ):
            raise KernelError(
                "MKAOS_EXPERIMENTAL_APPROVAL_SCOPE_INVALID",
                "experimental approval is not bound to the configured validation scope",
            )
        if proof.get("fixture_protocol_only") or not proof.get(
            "real_provider_proven"
        ):
            raise KernelError(
                "MKAOS_EXPERIMENTAL_REAL_PROVIDER_REQUIRED",
                "experimental validation approval requires real-provider evidence",
            )
        return {
            "schema_version": "mkaos-approval-contract.v1",
            "approval_class": "EXPERIMENTAL_VALIDATION",
            "review_class": "EXPERIMENTAL_POLICY_APPROVAL_NOT_HUMAN",
            "activation_scope": {
                "kind": "ISOLATED_PROJECT_AND_WORKSPACE",
                "project_id": project_id,
                "workspace_id": workspace_id,
            },
            "project_id": project_id,
            "workspace_id": workspace_id,
            "policy_version": policy_version,
            "reviewer_id": reviewer_id,
            "production_context_eligible": False,
            "experimental_context_eligible": True,
        }

    @staticmethod
    def _content_dependency(
        repository: SourceIntelligenceRepository,
        worker: WorkerLeaseCommand,
        *,
        upstream: str,
        downstream: str,
        relationship: str,
        selector_key: str,
    ) -> None:
        repository.record_dependency(
            {
                "dependency_id": str(uuid4()),
                "project_id": worker.project_id,
                "upstream_asset_version_id": upstream,
                "downstream_asset_version_id": downstream,
                "relationship": relationship,
                "selector_key": selector_key,
                "created_by_operation_id": worker.causation_id,
            }
        )

    @staticmethod
    def _event(
        uow: AuthorityUnitOfWork,
        worker: WorkerLeaseCommand,
        *,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        causation_id: str,
        payload: dict[str, Any],
    ) -> None:
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": aggregate_type,
                "aggregate_id": aggregate_id,
                "operation_id": worker.causation_id,
                "project_id": worker.project_id,
                "event_type": event_type,
                "correlation_id": worker.correlation_id,
                "causation_id": causation_id,
                "payload": {
                    **payload,
                    "operation_id": worker.causation_id,
                    "trace_id": worker.trace_id,
                    "attempt_id": worker.attempt_id,
                    "fencing_token": worker.fencing_token,
                },
            }
        )


def _input_asset(asset_version_id: str, role: str, content_hash: str) -> dict[str, Any]:
    return {
        "asset_version_id": asset_version_id,
        "role": role,
        "content_hash": content_hash,
    }


def _require_strings(*values: str) -> None:
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError("MKAOS Authority command is incomplete")


def _require_sha256(value: str, label: str) -> None:
    digest = value.removeprefix("sha256:")
    if not value.startswith("sha256:") or len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError(f"{label} must be canonical sha256")


def _hash(content: dict[str, Any]) -> str:
    encoded = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _candidate_execution_binding(
    content: Any,
    *,
    fixture_protocol_only: bool,
    candidate_payload_hash: str,
    abstraction_policy_version: str,
    evidence_spans: tuple[KnowledgeEvidenceSpan, ...],
    observation_asset_version_ids: tuple[str, ...],
) -> dict[str, Any]:
    evidence_manifest_hash = _hash(
        {
            "evidence_spans": [
                asdict(span)
                for span in sorted(
                    evidence_spans,
                    key=lambda item: (
                        item.source_chunk_asset_version_id,
                        item.chunk_byte_start,
                        item.chunk_byte_end,
                        item.evidence_hash,
                    ),
                )
            ]
        }
    )
    expected = {
        "schema_version": "mkaos-candidate-execution-binding.v1",
        "candidate_payload_hash": candidate_payload_hash,
        "abstraction_policy_version": abstraction_policy_version,
        "evidence_manifest_hash": evidence_manifest_hash,
        "observation_asset_version_ids": sorted(
            set(observation_asset_version_ids)
        ),
    }
    binding = (
        content.get("mkaos_candidate_binding")
        if isinstance(content, dict)
        else None
    )
    if binding is None and fixture_protocol_only:
        return {
            "schema_version": expected["schema_version"],
            "validation_status": "FIXTURE_PROTOCOL_UNBOUND",
        }
    if not isinstance(binding, dict) or any(
        binding.get(key) != value for key, value in expected.items()
    ):
        raise KernelError(
            "MKAOS_EXECUTION_OUTPUT_UNBOUND",
            "execution evidence is not bound to this Candidate, policy and inputs",
        )
    return {**expected, "validation_status": "VERIFIED"}


def _execution_proof(content: Any) -> dict[str, bool]:
    if not isinstance(content, dict):
        raise KernelError(
            "MKAOS_EXECUTION_EVIDENCE_INVALID",
            "execution evidence content must be an object",
        )
    gateway_backed = bool(
        content.get("production_execution_gateway_backed")
        or content.get("gateway") == "ProductionExecutionGateway"
    )
    if not gateway_backed:
        raise KernelError(
            "MKAOS_EXECUTION_GATEWAY_REQUIRED",
            "MKAOS model evidence must come through ProductionExecutionGateway",
        )
    fixture = bool(content.get("fixture_protocol_only"))
    real_provider_proven = bool(content.get("real_provider_proven"))
    production_verified = bool(content.get("production_verified"))
    if fixture and production_verified:
        raise KernelError(
            "MKAOS_EXECUTION_PROOF_CONFLICT",
            "fixture execution cannot claim production verification",
        )
    if production_verified and not real_provider_proven:
        raise KernelError(
            "MKAOS_EXECUTION_PROOF_CONFLICT",
            "production verification requires real-provider proof",
        )
    return {
        "production_execution_gateway_backed": True,
        "fixture_protocol_only": fixture,
        "real_provider_proven": real_provider_proven,
        "production_verified": production_verified,
    }


__all__ = [
    "ApproveKnowledgeCandidateCommand",
    "BuildKnowledgePackCommand",
    "CommitKnowledgeCandidateCommand",
    "ExperimentalKnowledgeApprovalPolicy",
    "MkaosAuthorityApplication",
]
