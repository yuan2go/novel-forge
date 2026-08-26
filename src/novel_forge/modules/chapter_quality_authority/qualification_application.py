"""PostgreSQL Authority application for bounded Quality Qualification.

The tables added by migration 0101 are authoritative indexes over immutable
Authority assets and Command Kernel operations.  This module never invokes a
Provider and never treats a projection row as an artifact store.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Callable, Iterable
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_handler_runtime import (
    AuthorityHandlerOutput,
    AuthorityHandlerRegistration,
    AuthorityHandlerRequest,
)
from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.operation_graph import (
    GraphCommandContext,
    start_saga,
)
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.modules.content_authority.scheduler import ContentAuthorityScheduler
from novel_forge.modules.reader_calibration import HumanBlindDecision
from novel_forge.modules.reader_calibration.application import (
    PostgresReaderCalibrationAuthority,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .qualification import (
    CampaignLifecycle,
    EvidenceLayer,
    EvidenceSeverity,
    EvidenceStatus,
    QualityCampaignManifest,
    QualityEvidence,
    decide_quality_qualification,
    transition_campaign,
)


VERSION = "1.0.0"
HANDLER_PREFIX = "novel_forge.quality_qualification"
MANAGE_PERMISSION = "quality.qualification.manage"
QUERY_PERMISSION = "quality.qualification.query"
DEFINITIONS = {
    "quality.qualification.campaign.admit": (
        "quality_qualification_manifest",
        "quality.qualification.manifest",
    ),
    "quality.qualification.campaign.freeze": (
        "quality_qualification_lifecycle_receipt",
        "quality.qualification.lifecycle",
    ),
    "quality.qualification.campaign.start": (
        "quality_qualification_lifecycle_receipt",
        "quality.qualification.lifecycle",
    ),
    "quality.qualification.campaign.resume": (
        "quality_qualification_lifecycle_receipt",
        "quality.qualification.lifecycle",
    ),
    "quality.qualification.subject.bind": (
        "quality_qualification_subject_binding",
        "quality.qualification.subject",
    ),
    "quality.qualification.comparison.materialize": (
        "quality_comparison_candidate",
        "quality.qualification.comparison_candidate",
    ),
    "quality.qualification.evidence.materialize": (
        "quality_qualification_evidence_report",
        "quality.qualification.evidence_report",
    ),
    "quality.qualification.evidence.bind": (
        "quality_qualification_evidence_binding",
        "quality.qualification.evidence",
    ),
    "quality.qualification.decision.record": (
        "quality_qualification_decision",
        "quality.qualification.decision",
    ),
}


@dataclass(frozen=True, slots=True)
class QualitySubjectBindingCommand:
    campaign_id: str
    subject_id: str
    scope_type: str
    scope_key: str
    chapter_start: int
    chapter_end: int
    arc_plan_version_ids: tuple[str, ...]
    canonical_asset_version_id: str
    canonical_content_hash: str
    baseline_asset_version_id: str
    baseline_content_hash: str
    chapter_plan_asset_version_id: str = ""
    narrative_realization_asset_version_id: str = ""


@dataclass(frozen=True, slots=True)
class QualityEvidenceBindingCommand:
    campaign_id: str
    evidence_id: str
    subject_id: str
    evidence_layer: EvidenceLayer
    evidence_type: str
    evidence_asset_version_id: str
    evidence_content_hash: str
    status: EvidenceStatus
    severity: EvidenceSeverity
    source_asset_version_ids: tuple[str, ...]
    evaluator_lineage: dict[str, Any]
    provider_lineage: dict[str, Any]


@dataclass(frozen=True, slots=True)
class QualityArtifactMaterializationCommand:
    campaign_id: str
    artifact_id: str
    artifact_kind: str
    scope_type: str
    chapter_start: int
    chapter_end: int
    content: dict[str, Any]
    source_asset_version_ids: tuple[str, ...]


class _Handler:
    def execute(self, request: AuthorityHandlerRequest) -> AuthorityHandlerOutput:
        payload = request.command.get("payload")
        if not isinstance(payload, dict):
            raise KernelError(
                "QUALITY_QUALIFICATION_INPUT_INVALID",
                "Quality Qualification payload must be an object",
            )
        asset_type, output_key = DEFINITIONS[request.definition_name]
        if request.definition_name == "quality.qualification.campaign.admit":
            content = dict(payload["manifest"])
        else:
            content = {
                "type": "".join(
                    part.title() for part in request.definition_name.split(".")
                ),
                "contract_version": request.definition_name.replace(".", "-") + "-v1",
                **payload,
                "source_asset_versions": [
                    item.asset_version_id for item in request.inputs
                ],
            }
        return AuthorityHandlerOutput(
            asset_type=asset_type,
            output_key=output_key,
            role="primary",
            content=content,
            qualification_policy="quality-qualification-authority-v1",
            reference_asset_version_ids=tuple(
                item.asset_version_id for item in request.inputs
            ),
            evidence={
                "deterministic": True,
                "provider_calls": 0,
                "evidence_boundary": "BOUNDED_QUALITY_QUALIFICATION",
            },
        )


class _Registry:
    def __init__(self) -> None:
        handler = _Handler()
        self.items = {
            (name, VERSION): AuthorityHandlerRegistration(
                definition_name=name,
                definition_version=VERSION,
                handler_key=f"{HANDLER_PREFIX}.{name}",
                handler_contract_version="quality-qualification-handler-v1",
                output_asset_type=asset_type,
                output_key=output_key,
                role="primary",
                completion_topic=f"{name}.completed",
                handler=handler,
            )
            for name, (asset_type, output_key) in DEFINITIONS.items()
        }

    @property
    def available_handler_keys(self) -> frozenset[str]:
        return frozenset(item.handler_key for item in self.items.values())

    def registration(
        self, definition_name: str, definition_version: str
    ) -> AuthorityHandlerRegistration:
        return self.items[(definition_name, definition_version)]


class PostgresQualityQualificationAuthority:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        reader_calibration: PostgresReaderCalibrationAuthority | None = None,
        worker_id: str = "quality-qualification-worker",
        failure_injector: Callable[[str], None] | None = None,
    ) -> None:
        if not database_url or not application_build_id or len(commit_sha) != 40:
            raise ValueError(
                "Quality Qualification requires PostgreSQL and build identity"
            )
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.worker_id = worker_id
        self.failure_injector = failure_injector
        self.registry = _Registry()
        self.reader_calibration = (
            reader_calibration
            or PostgresReaderCalibrationAuthority(
                database_url,
                application_build_id=application_build_id,
                commit_sha=commit_sha,
                worker_id=f"{worker_id}:reader-calibration",
            )
        )

    def admit_campaign(
        self,
        manifest: QualityCampaignManifest,
        *,
        stable_idempotency_key: str,
        trace_id: str,
        correlation_id: str,
        principal: Principal,
    ) -> dict[str, Any]:
        principal.require(MANAGE_PERMISSION, manifest.project_id)
        if manifest.exact_release_sha != self.commit_sha:
            raise KernelError(
                "QUALITY_QUALIFICATION_RELEASE_DRIFT",
                "campaign release SHA differs from the running application",
            )
        if not all((stable_idempotency_key, trace_id, correlation_id)):
            raise ValueError("campaign idempotency, trace and correlation are required")
        existing = self._campaign_or_none(manifest.campaign_id)
        if existing is not None:
            if (
                existing["project_id"] != manifest.project_id
                or existing["manifest_hash"] != manifest.digest
                or existing["stable_idempotency_key"] != stable_idempotency_key
            ):
                raise KernelError(
                    "QUALITY_QUALIFICATION_CAMPAIGN_CONFLICT",
                    "campaign identity already binds another frozen manifest",
                )
            return existing
        operation_id, output = self._execute(
            definition="quality.qualification.campaign.admit",
            project_id=manifest.project_id,
            workspace_id=manifest.workspace_id,
            idempotency_key=stable_idempotency_key,
            trace_id=trace_id,
            correlation_id=correlation_id,
            payload={"manifest": manifest.to_dict(), "manifest_hash": manifest.digest},
            input_assets=(),
            principal=principal,
        )
        if output["content_hash"] != manifest.digest:
            raise KernelError(
                "QUALITY_QUALIFICATION_MANIFEST_HASH_DRIFT",
                "materialized manifest hash differs from its canonical digest",
            )
        self._inject("after_campaign_asset")
        raw = manifest.to_dict()
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_quality_qualification_campaign(
                    campaign_id, project_id, workspace_id, book_id,
                    manifest_asset_version_id, manifest_hash,
                    exact_release_sha, migration_head, protocol_version,
                    evaluation_profile_version, quality_profile_version,
                    reader_outcome_profile_version, lifecycle,
                    qualification_status, human_evidence_status,
                    required_evaluator_count, chapter_start, chapter_end,
                    chapter_group_ranges, provider_route_manifest,
                    capability_pack_manifest, foundation_lineage,
                    planning_lineage, realization_lineage, context_policy,
                    budget_policy, stable_idempotency_key,
                    created_by_operation_id
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    'DRAFT',NULL,'NOT_STARTED',%s,1,8,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s
                )
                ON CONFLICT(project_id, stable_idempotency_key) DO NOTHING
                """,
                [
                    manifest.campaign_id,
                    manifest.project_id,
                    manifest.workspace_id,
                    manifest.book_id,
                    output["asset_version_id"],
                    manifest.digest,
                    manifest.exact_release_sha,
                    manifest.migration_head,
                    manifest.protocol_version,
                    manifest.evaluation_profile_version,
                    manifest.quality_profile_version,
                    manifest.reader_outcome_profile_version,
                    manifest.required_evaluator_count,
                    Jsonb(raw["chapter_group_ranges"]),
                    Jsonb(raw["provider_route_manifest"]),
                    Jsonb(raw["capability_pack_manifest"]),
                    Jsonb(raw["foundation_lineage"]),
                    Jsonb(raw["planning_lineage"]),
                    Jsonb(raw["realization_lineage"]),
                    Jsonb(raw["context_policy"]),
                    Jsonb(raw["budget_policy"]),
                    stable_idempotency_key,
                    operation_id,
                ],
            )
            uow.commit()
        recorded = self._require_campaign_row(manifest.campaign_id)
        if (
            recorded["manifest_hash"] != manifest.digest
            or recorded["manifest_asset_version_id"] != output["asset_version_id"]
        ):
            raise KernelError(
                "QUALITY_QUALIFICATION_CAMPAIGN_CONFLICT",
                "campaign replay resolved to another manifest AssetVersion",
            )
        return recorded

    def freeze_campaign(
        self,
        campaign_id: str,
        *,
        expected_version: int,
        principal: Principal,
    ) -> dict[str, Any]:
        return self._transition(
            campaign_id,
            target=CampaignLifecycle.FROZEN,
            expected_version=expected_version,
            definition="quality.qualification.campaign.freeze",
            principal=principal,
        )

    def start_campaign(
        self,
        campaign_id: str,
        *,
        expected_version: int,
        principal: Principal,
    ) -> dict[str, Any]:
        return self._transition(
            campaign_id,
            target=CampaignLifecycle.RUNNING,
            expected_version=expected_version,
            definition="quality.qualification.campaign.start",
            principal=principal,
        )

    def resume_campaign(
        self,
        campaign_id: str,
        *,
        expected_version: int,
        principal: Principal,
    ) -> dict[str, Any]:
        campaign = self._require_campaign_row(campaign_id)
        principal.require(MANAGE_PERMISSION, campaign["project_id"])
        current = CampaignLifecycle(campaign["lifecycle"])
        if int(campaign["version"]) != expected_version:
            raise KernelError(
                "QUALITY_QUALIFICATION_CAMPAIGN_VERSION_CONFLICT",
                "campaign version differs from the resume request",
            )
        if current not in {
            CampaignLifecycle.RUNNING,
            CampaignLifecycle.WAITING_HUMAN_EVIDENCE,
            CampaignLifecycle.EVALUATING,
        }:
            raise KernelError(
                "QUALITY_QUALIFICATION_RESUME_NOT_ALLOWED",
                "only a waiting or active campaign can resume evaluation",
            )
        completed_evaluators = self._completed_human_evaluators(campaign_id)
        if current is CampaignLifecycle.WAITING_HUMAN_EVIDENCE and completed_evaluators:
            result = self._transition(
                campaign_id,
                target=CampaignLifecycle.EVALUATING,
                expected_version=expected_version,
                definition="quality.qualification.campaign.resume",
                principal=principal,
            )
            return {**result, "resume_status": "EVALUATION_RESUMED"}
        self._execute(
            definition="quality.qualification.campaign.resume",
            project_id=campaign["project_id"],
            workspace_id=campaign["workspace_id"],
            idempotency_key=f"{campaign_id}:resume:{expected_version}",
            trace_id=f"trace:{campaign_id}:resume",
            correlation_id=campaign_id,
            payload={
                "campaign_id": campaign_id,
                "lifecycle": current.value,
                "expected_version": expected_version,
                "completed_human_evaluator_count": len(completed_evaluators),
                "state_mutation": False,
            },
            input_assets=(
                {
                    "asset_version_id": campaign["manifest_asset_version_id"],
                    "content_hash": self._asset_hash(
                        campaign["project_id"], campaign["manifest_asset_version_id"]
                    ),
                },
            ),
            principal=principal,
        )
        resume_status = (
            "WAITING_HUMAN_EVIDENCE"
            if current is CampaignLifecycle.WAITING_HUMAN_EVIDENCE
            else "ALREADY_RESUMABLE"
        )
        return {**campaign, "resume_status": resume_status}

    def bind_subject(
        self,
        command: QualitySubjectBindingCommand,
        *,
        principal: Principal,
    ) -> dict[str, Any]:
        campaign = self._require_campaign_row(command.campaign_id)
        principal.require(MANAGE_PERMISSION, campaign["project_id"])
        self._require_active_campaign(campaign)
        scope_type = str(command.scope_type).upper()
        if scope_type not in {"CHAPTER", "ARC"}:
            raise ValueError("Quality subject scope must be CHAPTER or ARC")
        if (
            command.chapter_start <= 0
            or command.chapter_end < command.chapter_start
            or command.chapter_end > 8
            or (
                scope_type == "CHAPTER" and command.chapter_start != command.chapter_end
            )
            or not command.subject_id
            or not command.scope_key
        ):
            raise ValueError("Quality subject scope is outside the frozen campaign")
        if command.canonical_asset_version_id == command.baseline_asset_version_id:
            raise ValueError("canonical and baseline candidates must differ")
        required_assets = [
            (command.canonical_asset_version_id, command.canonical_content_hash),
            (command.baseline_asset_version_id, command.baseline_content_hash),
        ]
        for optional in (
            command.chapter_plan_asset_version_id,
            command.narrative_realization_asset_version_id,
            *command.arc_plan_version_ids,
        ):
            if optional:
                required_assets.append((optional, ""))
        inputs = self._resolve_assets(campaign["project_id"], required_assets)
        operation_id, _output = self._execute(
            definition="quality.qualification.subject.bind",
            project_id=campaign["project_id"],
            workspace_id=campaign["workspace_id"],
            idempotency_key=f"{command.campaign_id}:{command.subject_id}:bind",
            trace_id=f"trace:{command.campaign_id}:{command.subject_id}",
            correlation_id=command.campaign_id,
            payload={
                "campaign_id": command.campaign_id,
                "subject_id": command.subject_id,
                "scope_type": scope_type,
                "scope_key": command.scope_key,
                "chapter_range": [command.chapter_start, command.chapter_end],
                "arc_plan_version_ids": list(command.arc_plan_version_ids),
                "canonical_asset_version_id": command.canonical_asset_version_id,
                "baseline_asset_version_id": command.baseline_asset_version_id,
                "baseline_protocol": "FIRST_DRAFT_VS_ACCEPTED_REVISION",
            },
            input_assets=inputs,
            principal=principal,
        )
        self._inject("after_subject_asset")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_quality_qualification_subject(
                    subject_id, campaign_id, project_id, scope_type, scope_key,
                    chapter_start, chapter_end, arc_plan_version_ids,
                    canonical_asset_version_id, canonical_content_hash,
                    baseline_asset_version_id, baseline_content_hash,
                    chapter_plan_asset_version_id,
                    narrative_realization_asset_version_id,
                    created_by_operation_id
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    NULLIF(%s,''),NULLIF(%s,''),%s
                )
                ON CONFLICT(campaign_id, scope_type, scope_key) DO NOTHING
                """,
                [
                    command.subject_id,
                    command.campaign_id,
                    campaign["project_id"],
                    scope_type,
                    command.scope_key,
                    command.chapter_start,
                    command.chapter_end,
                    Jsonb(list(command.arc_plan_version_ids)),
                    command.canonical_asset_version_id,
                    command.canonical_content_hash,
                    command.baseline_asset_version_id,
                    command.baseline_content_hash,
                    command.chapter_plan_asset_version_id,
                    command.narrative_realization_asset_version_id,
                    operation_id,
                ],
            )
            uow.commit()
        subject = self._require_subject(command.subject_id)
        if (
            subject["campaign_id"] != command.campaign_id
            or subject["canonical_asset_version_id"]
            != command.canonical_asset_version_id
            or subject["baseline_asset_version_id"] != command.baseline_asset_version_id
        ):
            raise KernelError(
                "QUALITY_QUALIFICATION_SUBJECT_CONFLICT",
                "subject replay differs from the frozen comparison",
            )
        return subject

    def materialize_artifact(
        self,
        command: QualityArtifactMaterializationCommand,
        *,
        principal: Principal,
    ) -> dict[str, str]:
        """Materialize a bounded comparison corpus or derived evidence report.

        This remains inside Quality Qualification Authority. It records a
        derived, source-bound artifact and never mutates accepted prose,
        Canon, Story State, plans, or human evidence.
        """

        campaign = self._require_campaign_row(command.campaign_id)
        principal.require(MANAGE_PERMISSION, campaign["project_id"])
        self._require_active_campaign(campaign)
        kind = str(command.artifact_kind).upper()
        if kind not in {"COMPARISON_CANDIDATE", "EVIDENCE_REPORT"}:
            raise ValueError("Quality artifact kind is unsupported")
        scope_type = str(command.scope_type).upper()
        if (
            scope_type not in {"CHAPTER", "ARC", "VOLUME_SLICE", "CAMPAIGN"}
            or command.chapter_start <= 0
            or command.chapter_end < command.chapter_start
            or command.chapter_end > 8
            or not command.artifact_id
            or not isinstance(command.content, dict)
            or not command.content
            or not command.source_asset_version_ids
        ):
            raise ValueError("Quality materialization scope or content is invalid")
        definition = (
            "quality.qualification.comparison.materialize"
            if kind == "COMPARISON_CANDIDATE"
            else "quality.qualification.evidence.materialize"
        )
        inputs = self._resolve_assets(
            campaign["project_id"],
            [(version_id, "") for version_id in command.source_asset_version_ids],
        )
        _operation_id, output = self._execute(
            definition=definition,
            project_id=campaign["project_id"],
            workspace_id=campaign["workspace_id"],
            idempotency_key=(
                f"{command.campaign_id}:{command.artifact_id}:materialize"
            ),
            trace_id=f"trace:{command.campaign_id}:{command.artifact_id}",
            correlation_id=command.campaign_id,
            payload={
                "campaign_id": command.campaign_id,
                "artifact_id": command.artifact_id,
                "artifact_kind": kind,
                "scope_type": scope_type,
                "chapter_range": [command.chapter_start, command.chapter_end],
                "accepted_history_only": True,
                **command.content,
            },
            input_assets=inputs,
            principal=principal,
        )
        return output

    def bind_evidence(
        self,
        command: QualityEvidenceBindingCommand,
        *,
        principal: Principal,
    ) -> dict[str, Any]:
        campaign = self._require_campaign_row(command.campaign_id)
        principal.require(MANAGE_PERMISSION, campaign["project_id"])
        self._require_active_campaign(campaign)
        layer = EvidenceLayer(command.evidence_layer)
        status = EvidenceStatus(command.status)
        severity = EvidenceSeverity(command.severity)
        if not command.evidence_id or not command.evidence_type:
            raise ValueError("Quality evidence identity and type are required")
        if not command.source_asset_version_ids:
            raise ValueError("Quality evidence requires source AssetVersions")
        if command.subject_id:
            subject = self._require_subject(command.subject_id)
            if subject["campaign_id"] != command.campaign_id:
                raise KernelError(
                    "QUALITY_QUALIFICATION_EVIDENCE_SCOPE_MISMATCH",
                    "evidence subject belongs to another campaign",
                )
        assets = [(command.evidence_asset_version_id, command.evidence_content_hash)]
        assets.extend(
            (version_id, "") for version_id in command.source_asset_version_ids
        )
        inputs = self._resolve_assets(campaign["project_id"], assets)
        operation_id, _output = self._execute(
            definition="quality.qualification.evidence.bind",
            project_id=campaign["project_id"],
            workspace_id=campaign["workspace_id"],
            idempotency_key=f"{command.campaign_id}:{command.evidence_id}:bind",
            trace_id=f"trace:{command.campaign_id}:{command.evidence_id}",
            correlation_id=command.campaign_id,
            payload={
                "campaign_id": command.campaign_id,
                "evidence_id": command.evidence_id,
                "subject_id": command.subject_id,
                "evidence_layer": layer.value,
                "evidence_type": command.evidence_type,
                "status": status.value,
                "severity": severity.value,
                "evaluator_lineage": command.evaluator_lineage,
                "provider_lineage": command.provider_lineage,
            },
            input_assets=inputs,
            principal=principal,
        )
        self._inject("after_evidence_asset")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_quality_qualification_evidence(
                    evidence_id, campaign_id, subject_id, project_id,
                    evidence_layer, evidence_type, evidence_asset_version_id,
                    evidence_content_hash, status, severity,
                    source_asset_version_ids, evaluator_lineage,
                    provider_lineage, created_by_operation_id
                ) VALUES (
                    %s,%s,NULLIF(%s,''),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                )
                ON CONFLICT(campaign_id, evidence_asset_version_id) DO NOTHING
                """,
                [
                    command.evidence_id,
                    command.campaign_id,
                    command.subject_id,
                    campaign["project_id"],
                    layer.value,
                    command.evidence_type,
                    command.evidence_asset_version_id,
                    command.evidence_content_hash,
                    status.value,
                    severity.value,
                    Jsonb(list(command.source_asset_version_ids)),
                    Jsonb(command.evaluator_lineage),
                    Jsonb(command.provider_lineage),
                    operation_id,
                ],
            )
            uow.commit()
        evidence = self._require_evidence(command.evidence_id)
        if (
            evidence["campaign_id"] != command.campaign_id
            or evidence["evidence_asset_version_id"]
            != command.evidence_asset_version_id
        ):
            raise KernelError(
                "QUALITY_QUALIFICATION_EVIDENCE_CONFLICT",
                "evidence replay differs from its immutable AssetVersion",
            )
        return evidence

    def evaluate_campaign(
        self,
        campaign_id: str,
        *,
        human_collection_closed: bool,
        principal: Principal,
    ) -> dict[str, Any]:
        campaign = self._require_campaign_row(campaign_id)
        principal.require(MANAGE_PERMISSION, campaign["project_id"])
        self._require_active_campaign(campaign)
        evidence_rows = self._evidence_rows(campaign_id)
        evidence = tuple(
            QualityEvidence(
                evidence_id=row["evidence_id"],
                subject_id=row["subject_id"] or campaign_id,
                layer=EvidenceLayer(row["evidence_layer"]),
                evidence_type=row["evidence_type"],
                status=EvidenceStatus(row["status"]),
                severity=EvidenceSeverity(row["severity"]),
                source_evidence_ids=tuple(row["source_asset_version_ids"]),
            )
            for row in evidence_rows
        )
        evaluator_ids = self._completed_human_evaluators(campaign_id)
        decision = decide_quality_qualification(
            evidence,
            valid_human_evaluator_ids=evaluator_ids,
            human_collection_closed=human_collection_closed,
            required_evaluator_count=int(campaign["required_evaluator_count"]),
        )
        layer_statuses = {
            layer.value: decision.layer_statuses[layer].value for layer in EvidenceLayer
        }
        evidence_version_ids = tuple(
            row["evidence_asset_version_id"] for row in evidence_rows
        )
        human_decision_assets = self._human_decision_assets(campaign_id)
        decision_fingerprint = _canonical_hash(
            {
                "campaign_id": campaign_id,
                "human_collection_closed": human_collection_closed,
                "human_evaluator_ids": list(evaluator_ids),
                "evidence_asset_version_ids": list(evidence_version_ids),
                "human_decision_asset_version_ids": [
                    item["asset_version_id"] for item in human_decision_assets
                ],
                "status": decision.status.value,
                "lifecycle": decision.lifecycle.value,
            }
        )
        payload = {
            "campaign_id": campaign_id,
            "decision_fingerprint": decision_fingerprint,
            "qualification_status": decision.status.value,
            "campaign_lifecycle": decision.lifecycle.value,
            "human_evidence_status": decision.human_evidence_status.value,
            "layer_statuses": layer_statuses,
            "limitations": list(decision.limitations),
            "diagnostics": list(decision.diagnostics),
            "unproven_claims": list(decision.unproven_claims),
            "evidence_asset_version_ids": list(evidence_version_ids),
            "human_evaluator_ids": list(evaluator_ids),
            "human_subjectivity_is_ground_truth": False,
            "bounded_evidence_only": True,
        }
        inputs = self._resolve_assets(
            campaign["project_id"],
            [
                (campaign["manifest_asset_version_id"], campaign["manifest_hash"]),
                *((version_id, "") for version_id in evidence_version_ids),
                *(
                    (item["asset_version_id"], item["content_hash"])
                    for item in human_decision_assets
                ),
            ],
        )
        operation_id, output = self._execute(
            definition="quality.qualification.decision.record",
            project_id=campaign["project_id"],
            workspace_id=campaign["workspace_id"],
            idempotency_key=f"{campaign_id}:decision:{decision_fingerprint}",
            trace_id=f"trace:{campaign_id}:decision:{decision_fingerprint[-12:]}",
            correlation_id=campaign_id,
            payload=payload,
            input_assets=inputs,
            principal=principal,
        )
        self._inject("after_decision_asset")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT decision_id
                FROM authority_quality_qualification_decision
                WHERE decision_asset_version_id=%s
                """,
                [output["asset_version_id"]],
            )
            existing = uow.cursor.fetchone()
            if existing is None:
                uow.cursor.execute(
                    """
                    SELECT lifecycle, version
                    FROM authority_quality_qualification_campaign
                    WHERE campaign_id=%s FOR UPDATE
                    """,
                    [campaign_id],
                )
                locked = uow.cursor.fetchone()
                if locked is None:
                    raise KernelError(
                        "QUALITY_QUALIFICATION_CAMPAIGN_NOT_FOUND",
                        "campaign disappeared before decision commit",
                    )
                self._validate_decision_transition(
                    CampaignLifecycle(str(locked[0])), decision.lifecycle
                )
                uow.cursor.execute(
                    """
                    SELECT COALESCE(MAX(decision_version), 0) + 1
                    FROM authority_quality_qualification_decision
                    WHERE campaign_id=%s
                    """,
                    [campaign_id],
                )
                decision_version = int(uow.cursor.fetchone()[0])
                decision_id = f"quality-decision:{campaign_id}:v{decision_version}"
                limitations = [
                    *decision.limitations,
                    *decision.diagnostics,
                    *decision.unproven_claims,
                ]
                uow.cursor.execute(
                    """
                    INSERT INTO authority_quality_qualification_decision(
                        decision_id, campaign_id, decision_version, project_id,
                        decision_asset_version_id, decision_content_hash,
                        qualification_status, campaign_lifecycle,
                        human_evidence_status, hard_correctness_status,
                        editorial_quality_status, reader_longitudinal_status,
                        limitations, evidence_asset_version_ids,
                        decided_by_operation_id
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    [
                        decision_id,
                        campaign_id,
                        decision_version,
                        campaign["project_id"],
                        output["asset_version_id"],
                        output["content_hash"],
                        decision.status.value,
                        decision.lifecycle.value,
                        decision.human_evidence_status.value,
                        layer_statuses[EvidenceLayer.L1_HARD_CORRECTNESS.value],
                        layer_statuses[EvidenceLayer.L2_EDITORIAL_QUALITY.value],
                        layer_statuses[EvidenceLayer.L3_READER_LONGITUDINAL.value],
                        Jsonb(limitations),
                        Jsonb(list(evidence_version_ids)),
                        operation_id,
                    ],
                )
                uow.cursor.execute(
                    """
                    UPDATE authority_quality_qualification_campaign
                    SET lifecycle=%s, qualification_status=%s,
                        human_evidence_status=%s, version=version+1,
                        completed_at=CASE WHEN %s IN ('COMPLETE','FAILED')
                                          THEN NOW() ELSE NULL END,
                        updated_at=NOW()
                    WHERE campaign_id=%s
                    """,
                    [
                        decision.lifecycle.value,
                        decision.status.value,
                        decision.human_evidence_status.value,
                        decision.lifecycle.value,
                        campaign_id,
                    ],
                )
            uow.commit()
        return self._decision_by_asset(output["asset_version_id"])

    def require_campaign(
        self, campaign_id: str, *, principal: Principal
    ) -> dict[str, Any]:
        campaign = self._require_campaign_row(campaign_id)
        principal.require(QUERY_PERMISSION, campaign["project_id"])
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT subject_id, scope_type, scope_key, chapter_start,
                       chapter_end, canonical_asset_version_id,
                       baseline_asset_version_id
                FROM authority_quality_qualification_subject
                WHERE campaign_id=%s
                ORDER BY chapter_start, scope_type, scope_key
                """,
                [campaign_id],
            )
            subject_fields = (
                "subject_id",
                "scope_type",
                "scope_key",
                "chapter_start",
                "chapter_end",
                "canonical_asset_version_id",
                "baseline_asset_version_id",
            )
            subjects = [
                dict(zip(subject_fields, row, strict=True))
                for row in uow.cursor.fetchall()
            ]
            uow.cursor.execute(
                """
                SELECT evidence_id, subject_id, evidence_layer, evidence_type,
                       evidence_asset_version_id, status, severity
                FROM authority_quality_qualification_evidence
                WHERE campaign_id=%s
                ORDER BY evidence_layer, evidence_type, evidence_id
                """,
                [campaign_id],
            )
            evidence_fields = (
                "evidence_id",
                "subject_id",
                "evidence_layer",
                "evidence_type",
                "evidence_asset_version_id",
                "status",
                "severity",
            )
            evidence = [
                dict(zip(evidence_fields, row, strict=True))
                for row in uow.cursor.fetchall()
            ]
            uow.cursor.execute(
                """
                SELECT decision_id, decision_version,
                       decision_asset_version_id, qualification_status,
                       campaign_lifecycle, human_evidence_status,
                       hard_correctness_status, editorial_quality_status,
                       reader_longitudinal_status, limitations,
                       evidence_asset_version_ids, created_at
                FROM authority_current_quality_qualification_decision
                WHERE campaign_id=%s
                """,
                [campaign_id],
            )
            decision_row = uow.cursor.fetchone()
        decision_fields = (
            "decision_id",
            "decision_version",
            "decision_asset_version_id",
            "qualification_status",
            "campaign_lifecycle",
            "human_evidence_status",
            "hard_correctness_status",
            "editorial_quality_status",
            "reader_longitudinal_status",
            "limitations",
            "evidence_asset_version_ids",
            "created_at",
        )
        current_decision = (
            dict(zip(decision_fields, decision_row, strict=True))
            if decision_row is not None
            else None
        )
        return {
            **campaign,
            "subjects": subjects,
            "evidence": evidence,
            "current_decision": current_decision,
            "blind_pack_status": self._blind_pack_status(campaign_id),
        }

    def blind_pack_status(
        self, campaign_id: str, *, principal: Principal
    ) -> dict[str, Any]:
        campaign = self._require_campaign_row(campaign_id)
        principal.require(QUERY_PERMISSION, campaign["project_id"])
        return self._blind_pack_status(campaign_id)

    def reviewer_pack(
        self,
        *,
        pack_id: str,
        reviewer_id: str,
        principal: Principal,
    ) -> dict[str, Any]:
        return self.reader_calibration.reviewer_pack(
            pack_id=pack_id,
            reviewer_id=reviewer_id,
            principal=principal,
        )

    def record_human_decision(
        self, decision: HumanBlindDecision, *, principal: Principal
    ) -> dict[str, Any]:
        return self.reader_calibration.record_blind_decision(
            decision,
            principal=principal,
        )

    def _transition(
        self,
        campaign_id: str,
        *,
        target: CampaignLifecycle,
        expected_version: int,
        definition: str,
        principal: Principal,
    ) -> dict[str, Any]:
        campaign = self._require_campaign_row(campaign_id)
        principal.require(MANAGE_PERMISSION, campaign["project_id"])
        current = CampaignLifecycle(campaign["lifecycle"])
        if current is target and int(campaign["version"]) == expected_version + 1:
            return campaign
        transition_campaign(current, target)
        _operation_id, _output = self._execute(
            definition=definition,
            project_id=campaign["project_id"],
            workspace_id=campaign["workspace_id"],
            idempotency_key=f"{campaign_id}:{target.value}:{expected_version}",
            trace_id=f"trace:{campaign_id}:{target.value.lower()}",
            correlation_id=campaign_id,
            payload={
                "campaign_id": campaign_id,
                "from_lifecycle": current.value,
                "to_lifecycle": target.value,
                "expected_version": expected_version,
            },
            input_assets=(
                {
                    "asset_version_id": campaign["manifest_asset_version_id"],
                    "content_hash": self._asset_hash(
                        campaign["project_id"], campaign["manifest_asset_version_id"]
                    ),
                },
            ),
            principal=principal,
        )
        self._inject("after_lifecycle_asset")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                UPDATE authority_quality_qualification_campaign
                SET lifecycle=%s, version=version+1,
                    frozen_at=CASE WHEN %s='FROZEN' THEN NOW() ELSE frozen_at END,
                    updated_at=NOW()
                WHERE campaign_id=%s AND lifecycle=%s AND version=%s
                """,
                [
                    target.value,
                    target.value,
                    campaign_id,
                    current.value,
                    expected_version,
                ],
            )
            if uow.cursor.rowcount != 1:
                uow.cursor.execute(
                    """
                    SELECT lifecycle, version
                    FROM authority_quality_qualification_campaign
                    WHERE campaign_id=%s
                    """,
                    [campaign_id],
                )
                observed = uow.cursor.fetchone()
                if observed != (target.value, expected_version + 1):
                    raise KernelError(
                        "QUALITY_QUALIFICATION_CAMPAIGN_VERSION_CONFLICT",
                        "campaign changed before lifecycle transition commit",
                    )
            uow.commit()
        return self._require_campaign_row(campaign_id)

    def _execute(
        self,
        *,
        definition: str,
        project_id: str,
        workspace_id: str,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
        payload: dict[str, Any],
        input_assets: tuple[dict[str, str], ...],
        principal: Principal,
    ) -> tuple[str, dict[str, str]]:
        self._register_definitions()
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": definition,
                "definition_version": VERSION,
                "project_id": project_id,
                "workspace_id": workspace_id,
                "actor_id": principal.principal_id,
                "idempotency_scope": "project:quality-qualification",
                "idempotency_key": idempotency_key,
                "trace_id": trace_id,
                "span_id": str(uuid4()),
                "correlation_id": correlation_id,
                "causation_id": "",
                "input": {
                    "project_id": project_id,
                    "input_asset_version_ids": [
                        item["asset_version_id"] for item in input_assets
                    ],
                    "payload": payload,
                },
                "input_assets": list(input_assets),
            },
            context=AdmissionContext(
                actor_id=principal.principal_id,
                permissions=frozenset({MANAGE_PERMISSION}),
                available_handlers=self.registry.available_handler_keys,
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
        )
        operation_id = str(admitted["operation_id"])
        with AuthorityUnitOfWork(self.database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(
                operation_id, project_id
            )
        if state["status"] == "ADMITTED":
            transition_operation(
                self.database_url,
                OperationTransitionCommand(
                    operation_id=operation_id,
                    project_id=project_id,
                    expected_version=int(state["version"]),
                    expected_status="ADMITTED",
                    target_status="READY",
                    actor_id=principal.principal_id,
                    reason="Quality Qualification inputs frozen",
                    trace_id=trace_id,
                    correlation_id=correlation_id,
                    causation_id="",
                ),
            )
            start_saga(
                self.database_url,
                GraphCommandContext(
                    project_id,
                    principal.principal_id,
                    trace_id,
                    correlation_id,
                ),
                root_operation_id=operation_id,
            )
        ContentAuthorityScheduler(
            self.database_url,
            registry=self.registry,
            worker_id=self.worker_id,
        ).run_or_recover(operation_id=operation_id, project_id=project_id)
        return operation_id, self._output(operation_id, DEFINITIONS[definition][1])

    def _register_definitions(self) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            for name, (asset_type, output_key) in DEFINITIONS.items():
                uow.repositories.definitions.register(
                    _definition(
                        name,
                        asset_type,
                        output_key,
                        application_build_id=self.application_build_id,
                        commit_sha=self.commit_sha,
                    )
                )
            uow.commit()

    def _resolve_assets(
        self,
        project_id: str,
        requested: Iterable[tuple[str, str]],
    ) -> tuple[dict[str, str], ...]:
        result: list[dict[str, str]] = []
        seen: set[str] = set()
        with AuthorityUnitOfWork(self.database_url) as uow:
            for version_id, expected_hash in requested:
                if not version_id or version_id in seen:
                    continue
                seen.add(version_id)
                uow.cursor.execute(
                    """
                    SELECT version.content_hash
                    FROM authority_asset_version AS version
                    JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                    WHERE version.asset_version_id=%s AND asset.project_id=%s
                    """,
                    [version_id, project_id],
                )
                row = uow.cursor.fetchone()
                if row is None:
                    raise KernelError(
                        "QUALITY_QUALIFICATION_INPUT_ASSET_MISSING",
                        "Quality Qualification input is outside the Project",
                    )
                content_hash = str(row[0])
                if expected_hash and expected_hash != content_hash:
                    raise KernelError(
                        "QUALITY_QUALIFICATION_INPUT_HASH_DRIFT",
                        "Quality Qualification input hash differs from Authority",
                    )
                result.append(
                    {
                        "asset_version_id": version_id,
                        "content_hash": content_hash,
                    }
                )
        return tuple(result)

    def _asset_hash(self, project_id: str, asset_version_id: str) -> str:
        return self._resolve_assets(project_id, [(asset_version_id, "")])[0][
            "content_hash"
        ]

    def _output(self, operation_id: str, output_key: str) -> dict[str, str]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT binding.asset_version_id, version.content_hash
                FROM authority_operation_output_asset AS binding
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=binding.asset_version_id
                WHERE binding.operation_id=%s AND binding.output_key=%s
                """,
                [operation_id, output_key],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "QUALITY_QUALIFICATION_OUTPUT_MISSING",
                "Quality Qualification operation has no immutable output",
            )
        return {"asset_version_id": str(row[0]), "content_hash": str(row[1])}

    def _campaign_or_none(self, campaign_id: str) -> dict[str, Any] | None:
        try:
            return self._require_campaign_row(campaign_id)
        except KernelError as exc:
            if exc.code == "QUALITY_QUALIFICATION_CAMPAIGN_NOT_FOUND":
                return None
            raise

    def _require_campaign_row(self, campaign_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT campaign_id, project_id, workspace_id, book_id,
                       manifest_asset_version_id, manifest_hash,
                       exact_release_sha, migration_head, protocol_version,
                       evaluation_profile_version, quality_profile_version,
                       reader_outcome_profile_version, lifecycle,
                       qualification_status, human_evidence_status,
                       required_evaluator_count, chapter_start, chapter_end,
                       chapter_group_ranges, provider_route_manifest,
                       capability_pack_manifest, foundation_lineage,
                       planning_lineage, realization_lineage, context_policy,
                       budget_policy, stable_idempotency_key,
                       created_by_operation_id, frozen_at, completed_at,
                       version, created_at, updated_at
                FROM authority_quality_qualification_campaign
                WHERE campaign_id=%s
                """,
                [campaign_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "QUALITY_QUALIFICATION_CAMPAIGN_NOT_FOUND",
                "Quality Qualification campaign does not exist",
            )
        fields = (
            "campaign_id",
            "project_id",
            "workspace_id",
            "book_id",
            "manifest_asset_version_id",
            "manifest_hash",
            "exact_release_sha",
            "migration_head",
            "protocol_version",
            "evaluation_profile_version",
            "quality_profile_version",
            "reader_outcome_profile_version",
            "lifecycle",
            "qualification_status",
            "human_evidence_status",
            "required_evaluator_count",
            "chapter_start",
            "chapter_end",
            "chapter_group_ranges",
            "provider_route_manifest",
            "capability_pack_manifest",
            "foundation_lineage",
            "planning_lineage",
            "realization_lineage",
            "context_policy",
            "budget_policy",
            "stable_idempotency_key",
            "created_by_operation_id",
            "frozen_at",
            "completed_at",
            "version",
            "created_at",
            "updated_at",
        )
        return dict(zip(fields, row, strict=True))

    def _require_subject(self, subject_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT subject_id, campaign_id, project_id, scope_type,
                       scope_key, chapter_start, chapter_end,
                       arc_plan_version_ids, canonical_asset_version_id,
                       canonical_content_hash, baseline_asset_version_id,
                       baseline_content_hash, chapter_plan_asset_version_id,
                       narrative_realization_asset_version_id,
                       created_by_operation_id
                FROM authority_quality_qualification_subject
                WHERE subject_id=%s
                """,
                [subject_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "QUALITY_QUALIFICATION_SUBJECT_NOT_FOUND",
                "Quality Qualification subject does not exist",
            )
        fields = (
            "subject_id",
            "campaign_id",
            "project_id",
            "scope_type",
            "scope_key",
            "chapter_start",
            "chapter_end",
            "arc_plan_version_ids",
            "canonical_asset_version_id",
            "canonical_content_hash",
            "baseline_asset_version_id",
            "baseline_content_hash",
            "chapter_plan_asset_version_id",
            "narrative_realization_asset_version_id",
            "created_by_operation_id",
        )
        return dict(zip(fields, row, strict=True))

    def _require_evidence(self, evidence_id: str) -> dict[str, Any]:
        rows = self._evidence_rows("", evidence_id=evidence_id)
        if not rows:
            raise KernelError(
                "QUALITY_QUALIFICATION_EVIDENCE_NOT_FOUND",
                "Quality Qualification evidence does not exist",
            )
        return rows[0]

    def _evidence_rows(
        self, campaign_id: str, *, evidence_id: str = ""
    ) -> list[dict[str, Any]]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT evidence_id, campaign_id, COALESCE(subject_id, ''),
                       project_id, evidence_layer, evidence_type,
                       evidence_asset_version_id, evidence_content_hash,
                       status, severity, source_asset_version_ids,
                       evaluator_lineage, provider_lineage,
                       created_by_operation_id
                FROM authority_quality_qualification_evidence
                WHERE (%s='' OR campaign_id=%s)
                  AND (%s='' OR evidence_id=%s)
                ORDER BY evidence_layer, evidence_type, evidence_id
                """,
                [campaign_id, campaign_id, evidence_id, evidence_id],
            )
            rows = uow.cursor.fetchall()
        fields = (
            "evidence_id",
            "campaign_id",
            "subject_id",
            "project_id",
            "evidence_layer",
            "evidence_type",
            "evidence_asset_version_id",
            "evidence_content_hash",
            "status",
            "severity",
            "source_asset_version_ids",
            "evaluator_lineage",
            "provider_lineage",
            "created_by_operation_id",
        )
        return [dict(zip(fields, row, strict=True)) for row in rows]

    def _completed_human_evaluators(self, campaign_id: str) -> tuple[str, ...]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT reviewer_id
                FROM human_preference_evaluation_pack
                WHERE campaign_id=%s AND status='COMPLETED'
                ORDER BY reviewer_id
                """,
                [campaign_id],
            )
            return tuple(str(row[0]) for row in uow.cursor.fetchall())

    def _human_decision_assets(self, campaign_id: str) -> list[dict[str, str]]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT DISTINCT binding.asset_version_id, binding.content_hash
                FROM human_preference_decision AS decision
                JOIN human_preference_evaluation_pack AS pack
                  ON pack.pack_id=decision.pack_id
                JOIN authority_operation_output_asset AS binding
                  ON binding.operation_id=decision.decision_operation_id
                 AND binding.output_key='reader.preference.decision'
                WHERE pack.campaign_id=%s
                ORDER BY binding.asset_version_id
                """,
                [campaign_id],
            )
            return [
                {"asset_version_id": str(row[0]), "content_hash": str(row[1])}
                for row in uow.cursor.fetchall()
            ]

    def _decision_by_asset(self, asset_version_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT decision_id, campaign_id, decision_version,
                       project_id, decision_asset_version_id,
                       decision_content_hash, qualification_status,
                       campaign_lifecycle, human_evidence_status,
                       hard_correctness_status, editorial_quality_status,
                       reader_longitudinal_status, limitations,
                       evidence_asset_version_ids, decided_by_operation_id,
                       created_at
                FROM authority_quality_qualification_decision
                WHERE decision_asset_version_id=%s
                """,
                [asset_version_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "QUALITY_QUALIFICATION_DECISION_NOT_FOUND",
                "Quality Qualification decision projection is missing",
            )
        fields = (
            "decision_id",
            "campaign_id",
            "decision_version",
            "project_id",
            "decision_asset_version_id",
            "decision_content_hash",
            "qualification_status",
            "campaign_lifecycle",
            "human_evidence_status",
            "hard_correctness_status",
            "editorial_quality_status",
            "reader_longitudinal_status",
            "limitations",
            "evidence_asset_version_ids",
            "decided_by_operation_id",
            "created_at",
        )
        return dict(zip(fields, row, strict=True))

    def _blind_pack_status(self, campaign_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(*),
                       COUNT(*) FILTER (WHERE status='EXPORTED'),
                       COUNT(*) FILTER (WHERE status='IN_PROGRESS'),
                       COUNT(*) FILTER (WHERE status='COMPLETED'),
                       COUNT(DISTINCT reviewer_id)
                FROM human_preference_evaluation_pack
                WHERE campaign_id=%s
                """,
                [campaign_id],
            )
            row = uow.cursor.fetchone()
        return {
            "pack_count": int(row[0]),
            "exported_count": int(row[1]),
            "in_progress_count": int(row[2]),
            "completed_count": int(row[3]),
            "reviewer_count": int(row[4]),
            "private_mapping_exposed": False,
        }

    @staticmethod
    def _require_active_campaign(campaign: dict[str, Any]) -> None:
        if campaign["lifecycle"] not in {
            "FROZEN",
            "RUNNING",
            "WAITING_HUMAN_EVIDENCE",
            "EVALUATING",
        }:
            raise KernelError(
                "QUALITY_QUALIFICATION_CAMPAIGN_NOT_ACTIVE",
                "campaign must be frozen or active before binding evidence",
            )

    @staticmethod
    def _validate_decision_transition(
        current: CampaignLifecycle, target: CampaignLifecycle
    ) -> None:
        if current is target and target is CampaignLifecycle.WAITING_HUMAN_EVIDENCE:
            return
        if target is CampaignLifecycle.COMPLETE and current in {
            CampaignLifecycle.RUNNING,
            CampaignLifecycle.WAITING_HUMAN_EVIDENCE,
        }:
            transition_campaign(current, CampaignLifecycle.EVALUATING)
            transition_campaign(CampaignLifecycle.EVALUATING, target)
            return
        transition_campaign(current, target)

    def _inject(self, stage: str) -> None:
        if self.failure_injector is not None:
            self.failure_injector(stage)


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _definition(
    name: str,
    asset_type: str,
    output_key: str,
    *,
    application_build_id: str,
    commit_sha: str,
) -> dict[str, Any]:
    schema = {"type": "object"}
    return {
        "name": name,
        "definition_version": VERSION,
        "family": "quality_qualification",
        "enabled": True,
        "definition_status": "integration_proven",
        "command_schema_version": f"{name}.command.v1",
        "result_schema_version": f"{name}.result.v1",
        "command_schema": schema,
        "result_schema": schema,
        "input_contract": schema,
        "output_contract": {"asset_type": asset_type, "output_key": output_key},
        "handler_key": f"{HANDLER_PREFIX}.{name}",
        "handler_contract_version": "quality-qualification-handler-v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "worker",
        "permissions": [MANAGE_PERMISSION],
        "approval_policy": {"required": False},
        "idempotency_scope": "project:quality-qualification",
        "concurrency_key_template": "project:{project_id}:quality-qualification",
        "retry_policy": {"max_attempts": 2},
        "timeout_policy": {"operation_timeout_seconds": 120},
        "cancellation_policy": {"mode": "cancel_active_attempt"},
        "compensation_policy": {
            "supported": False,
            "reason": "append-only qualification evidence",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "policy": {
            "provider_calls_allowed": False,
            "hard_correctness_precedence": True,
            "missing_evidence_status": "NOT_PROVEN",
        },
        "completion_contract": {
            "version": "quality-qualification-completion-v1",
            "required_asset_selectors": [
                {
                    "selector": asset_type,
                    "output_key": output_key,
                    "role": "primary",
                    "lifecycle": "ACTIVE",
                    "eligibility": "ELIGIBLE",
                    "governance": "CLEAR",
                }
            ],
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": [f"{name}.completed"],
        },
    }


__all__ = [
    "PostgresQualityQualificationAuthority",
    "QualityArtifactMaterializationCommand",
    "QualityEvidenceBindingCommand",
    "QualitySubjectBindingCommand",
]
