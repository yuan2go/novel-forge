from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from novel_forge.modules.chapter_authority.execution_gateway import (
    ChapterExecutionBinding,
    PostgresProductionExecutionPayloadResolver,
    ProductionExecutionGatewayExternalEffectAdapter,
    _materialize_source_intelligence_prompt,
    _provider_process_timeout_seconds,
)
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.budget_runtime import (
    BudgetReservationRequest,
    reserve_provider_budget,
    resolve_provider_budget_failure,
    settle_provider_budget,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapterError,
    ProviderResult,
)
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    dispatch_external_effect,
    plan_external_effect,
)
from novel_forge.modules.command_kernel.attempt_runtime import WorkerLeaseCommand
from novel_forge.modules.mkaos_authority.domain import (
    KnowledgeEvidenceSpan,
    validate_knowledge_candidate,
)
from novel_forge.modules.production_execution import (
    ArtifactPointer,
    ExecutionOutcome,
    ExecutionRecoveryAction,
    ExecutionRecoveryAuthorization,
    ExecutionRequest,
    ExecutionRuntimeClass,
    FallbackPolicy,
    InputManifest,
    ModelProfile,
    RoutePolicy,
    RouteSnapshot,
    TargetScope,
    default_capability_registry,
)
from novel_forge.modules.production_execution.provider_admission import (
    ProviderRequestEnvelope,
    build_route_token_accounting_contract,
    prepare_provider_admission,
    provider_request_protocol,
)
from novel_forge.modules.source_authority.deconstruction import (
    AnalyzerContract,
    ObservationEvidenceSpan,
    ObservationScope,
    stable_hash,
    validate_observation_payload,
)
from novel_forge.storage.authority_asset_store import (
    AuthorityAssetDocument,
    AuthorityAssetQuery,
    AuthorityAssetWriter,
)
from novel_forge.storage.database_runtime import get_database_runtime

from .execution_contracts import (
    CLASSIFICATION_STAGE,
    DECONSTRUCTION_STAGE,
    MKAOS_STAGE,
    compound_deconstruction_output_schema,
    content_intelligence_output_schema,
    validate_content_intelligence_output,
)
from .methodologies import SourceMethodologyRegistry
from .profiling import (
    SOURCE_CLASSIFIER_METHODOLOGY,
    SOURCE_CLASSIFIER_METHODOLOGY_HASH,
)


_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class _ExecutionSpec:
    kind: str
    stage: str
    capability: str
    prompt_id: str
    prompt_version: str
    skill_id: str
    skill_version: str
    methodology_content: str
    methodology_content_hash: str
    target_scope: TargetScope
    input_payload: dict[str, Any]
    artifact_version_ids: tuple[str, ...]
    context_contract: dict[str, Any]
    output_schema: dict[str, Any]


class _SourceGatewayEffectAdapter:
    production_execution_gateway_backed = True

    def __init__(
        self,
        *,
        transport: ProductionExecutionGatewayExternalEffectAdapter,
        binding: ChapterExecutionBinding,
    ) -> None:
        self.transport = transport
        self.binding = binding
        self.session = transport.session_for_project(binding.request.project_id)
        self.provider = transport.provider
        self.reconciliation_mode = transport.reconciliation_mode
        self.capability_profile = transport.capability_profile

    def execute(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        request = self.binding.request
        if (
            stable_idempotency_key != request.stable_idempotency_key
            or capability != request.capability
            or str(request_payload.get("external_effect_id") or "")
            != request.external_effect_id
        ):
            raise ExternalEffectAdapterError(
                "Source execution differs from its frozen PEP request",
                request_sent=False,
            )
        request_sent = False
        try:
            handle = self.session.gateway.submit(request)
            request_sent = True
            result = self.session.gateway.reconcile(handle)
        except Exception as exc:
            recovered = self.session.evidence_store.find_record(request.execution_id)
            submission_phase = (
                str(recovered.raw_evidence.get("submission_phase") or "")
                if recovered is not None
                else ""
            )
            request_sent = request_sent or submission_phase in {
                "PROVIDER_INVOKING",
                "PROVIDER_OUTCOME_UNKNOWN",
                "PROVIDER_RESULT_RECORDED",
                "PROCESS_STARTING",
                "PROCESS_OUTCOME_UNKNOWN",
                "PROCESS_RESULT_RECORDED",
            }
            raise ExternalEffectAdapterError(
                f"Source PEP execution failed: {type(exc).__name__}: {exc}",
                request_sent=request_sent,
            ) from exc
        return _source_gateway_provider_result(
            binding=self.binding,
            session=self.session,
            handle=handle,
            result=result,
        )

    def query(self, **kwargs: Any) -> ProviderResult:
        return self.execute(**kwargs)

    def cancel(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
        provider_request_id: str,
    ) -> ProviderResult:
        del stable_idempotency_key, capability, request_payload
        handle = self.session.gateway.submit(self.binding.request)
        result = self.session.gateway.cancel(handle, "Source execution cancellation")
        return ProviderResult(
            "cancelled",
            handle.backend_execution_id,
            {"production_execution_cancellation": result.to_dict()},
            provider_request_id,
        )


def _source_gateway_provider_result(
    *,
    binding: ChapterExecutionBinding,
    session: Any,
    handle: Any,
    result: Any,
) -> ProviderResult:
    record = session.evidence_store.get_record(binding.request.execution_id)
    evidence: dict[str, Any] = {
        "provider_id": binding.route_snapshot.model_provider,
        "model_id": binding.route_snapshot.model_id,
        "prompt_version": binding.input_manifest.prompt_bundle_version,
        "skill_version": binding.input_manifest.skill_bundle_version,
        "real_model_call": handle.transport
        in {
            ExecutionRuntimeClass.REMOTE_PROVIDER_API,
            ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
        },
        "fixture_protocol_only": (
            handle.transport is ExecutionRuntimeClass.SCRIPTED_FIXTURE
        ),
        "production_verified": False,
        "production_execution": {
            "execution_request": binding.request.to_dict(),
            "execution_handle": handle.to_dict(),
            "execution_result": result.to_dict(),
            "route_snapshot": binding.route_snapshot.to_dict(),
            "input_manifest": binding.input_manifest.to_dict(),
            "process_evidence": dict(record.raw_evidence),
        },
    }
    capability_evidence = record.raw_evidence.get("capability_evidence")
    if isinstance(capability_evidence, Mapping):
        evidence["capability_runtime"] = dict(capability_evidence)
    if result.normalized_output_ref:
        evidence["result"] = session.evidence_store.read_evidence(
            str(result.normalized_output_ref)
        )
    if result.usage_receipt_ref:
        evidence["usage"] = session.evidence_store.read_evidence(
            str(result.usage_receipt_ref)
        )
    if result.cost_receipt_ref:
        evidence["cost"] = session.evidence_store.read_evidence(
            str(result.cost_receipt_ref)
        )
    outcome = {
        ExecutionOutcome.SUCCEEDED: "success",
        ExecutionOutcome.RETRYABLE_FAILURE: "retryable_failure",
        ExecutionOutcome.TIMED_OUT: "retryable_failure",
        ExecutionOutcome.CORRUPT_RESULT: "retryable_failure",
        ExecutionOutcome.FINAL_FAILURE: "final_failure",
        ExecutionOutcome.CANCELLED: "cancelled",
    }.get(result.outcome, "unknown")
    return ProviderResult(
        outcome,
        handle.backend_execution_id,
        evidence,
        handle.provider_request_id or "",
    )


class _SourceGatewayRecoveryEffectAdapter:
    production_execution_gateway_backed = True

    def __init__(
        self,
        *,
        transport: ProductionExecutionGatewayExternalEffectAdapter,
        worker: WorkerLeaseCommand,
        effect: Mapping[str, Any],
    ) -> None:
        self.transport = transport
        self.worker = worker
        self.effect = dict(effect)
        self.provider = transport.provider
        self.reconciliation_mode = transport.reconciliation_mode
        self.capability_profile = transport.capability_profile

    def execute(self, **_kwargs: Any) -> ProviderResult:
        raise ExternalEffectAdapterError(
            "Source recovery adapter cannot dispatch a new execution",
            request_sent=False,
        )

    def query(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        effect_id = str(self.effect["external_effect_id"])
        if (
            stable_idempotency_key != self.effect["stable_idempotency_key"]
            or capability != self.effect["capability"]
            or str(request_payload.get("external_effect_id") or "") != effect_id
        ):
            raise ExternalEffectAdapterError(
                "Source recovery differs from its frozen ExternalEffect",
                request_sent=False,
            )
        metadata = self.effect.get("request_payload", {}).get("_production_execution")
        if not isinstance(metadata, Mapping):
            raise ExternalEffectAdapterError(
                "Source recovery has no frozen execution identity",
                request_sent=False,
            )
        execution_id = f"source-intelligence-execution:{effect_id}"
        session = self.transport.session_for_project(self.worker.project_id)
        record = session.evidence_store.find_record(execution_id)
        if record is None:
            return ProviderResult("not_found", "", {"execution_id": execution_id})
        request = record.request
        execution_fence = int(metadata.get("fencing_token") or 0)
        if (
            request.external_effect_id != effect_id
            or request.operation_id != self.worker.causation_id
            or request.attempt_id != self.worker.attempt_id
            or request.fencing_token != execution_fence
        ):
            raise ExternalEffectAdapterError(
                "persisted Source execution differs from frozen recovery identity",
                request_sent=True,
            )
        authorization = ExecutionRecoveryAuthorization(
            authorization_id=(
                "execution-recovery:"
                + _token(
                    f"{execution_id}:{self.worker.fencing_token}:"
                    f"{ExecutionRecoveryAction.QUERY.value}"
                )
            ),
            execution_id=execution_id,
            external_effect_id=effect_id,
            operation_id=self.worker.causation_id,
            attempt_id=self.worker.attempt_id,
            execution_fencing_token=execution_fence,
            recovery_fencing_token=self.worker.fencing_token,
            recovery_worker_id=self.worker.worker_id,
            action=ExecutionRecoveryAction.QUERY,
            trace_id=self.worker.trace_id,
            correlation_id=self.worker.correlation_id,
        )
        self.transport.recovery_authorizations.record(authorization)
        result = session.gateway.recover_existing_execution(
            request,
            record.handle,
            authorization,
        )
        route = session.gateway.admission.resolve_route(request)
        manifest = session.gateway.admission.contracts.input_manifest(
            request.input_manifest_ref
        )
        return _source_gateway_provider_result(
            binding=ChapterExecutionBinding(request, route, manifest),
            session=session,
            handle=record.handle,
            result=result,
        )

    def cancel(self, **_kwargs: Any) -> ProviderResult:
        raise ExternalEffectAdapterError(
            "Source recovery cancellation requires an explicit cancellation command",
            request_sent=False,
        )


class PostgresContentIntelligenceExecutionPort:
    external_effect_backed = True
    production_execution_gateway_backed = True

    def __init__(
        self,
        database_url: str,
        *,
        transport: ProductionExecutionGatewayExternalEffectAdapter,
        worker_id: str,
        lease_seconds: int = 60,
        max_cost_per_call: str = "0",
        budget_caps: Mapping[str, str] | None = None,
        methodology_registry: SourceMethodologyRegistry | None = None,
        source_object_reader: Any | None = None,
        provider_output_token_reserve: int = 4_096,
        provider_timeout_seconds: int = 300,
    ) -> None:
        if (
            not database_url
            or not worker_id
            or lease_seconds <= 0
            or provider_output_token_reserve <= 0
            or provider_timeout_seconds <= 0
        ):
            raise ValueError(
                "Source PEP port requires database, worker, lease, and Provider limits"
            )
        if not getattr(transport, "production_execution_gateway_backed", False):
            raise ValueError("Source execution requires ProductionExecutionGateway")
        self.database_url = database_url
        self.transport = transport
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.max_cost_per_call = max_cost_per_call
        self.budget_caps = dict(budget_caps or {})
        self.cost_accounting_basis = str(
            getattr(transport, "cost_accounting_basis", "PRICED") or "PRICED"
        ).upper()
        self.account_authorization_ref = str(
            getattr(transport, "account_authorization_ref", "") or ""
        )
        self.provider_call_caps = {
            str(key): int(value)
            for key, value in dict(
                getattr(transport, "provider_call_caps", {}) or {}
            ).items()
        }
        self.provider_token_caps = {
            str(key): int(value)
            for key, value in dict(
                getattr(transport, "provider_token_caps", {}) or {}
            ).items()
        }
        if self.cost_accounting_basis == "ACCOUNT_ENTITLEMENT" and (
            not self.account_authorization_ref or self.budget_caps
        ):
            raise ValueError(
                "Source account-entitlement execution requires authorization and no monetary caps"
            )
        self.query = AuthorityAssetQuery(database_url)
        self.writer = AuthorityAssetWriter(database_url)
        self.methodology_registry = methodology_registry or SourceMethodologyRegistry(
            Path(__file__).resolve().parents[4] / "skills"
        )
        self.source_object_reader = source_object_reader
        self.provider_output_token_reserve = provider_output_token_reserve
        self.provider_timeout_seconds = provider_timeout_seconds

    def recovery_adapter(
        self, *, worker: WorkerLeaseCommand, effect: Mapping[str, Any]
    ) -> _SourceGatewayRecoveryEffectAdapter:
        if str(effect.get("provider") or "") != self.transport.provider:
            raise KernelError(
                "SOURCE_PEP_RECOVERY_PROVIDER_CONFLICT",
                "uncertain Source execution belongs to another Provider",
            )
        return _SourceGatewayRecoveryEffectAdapter(
            transport=self.transport,
            worker=worker,
            effect=effect,
        )

    def execute_classification(
        self,
        *,
        worker: WorkerLeaseCommand,
        logical_document_scope_hash: str,
        classifier_contract: dict[str, Any],
        classification_evidence: dict[str, Any],
        source_segments: tuple[dict[str, Any], ...],
    ) -> dict[str, Any]:
        if not _SHA256.fullmatch(logical_document_scope_hash):
            raise ValueError("classification requires a canonical scope hash")
        if (
            classifier_contract.get("methodology_content_hash")
            != SOURCE_CLASSIFIER_METHODOLOGY_HASH
            or classifier_contract.get("capability") != "source.content.classify"
        ):
            raise KernelError(
                "SOURCE_CLASSIFIER_METHODOLOGY_MISMATCH",
                "classifier methodology or capability differs from runtime",
            )
        if (
            classification_evidence.get("logical_document_scope_hash")
            != logical_document_scope_hash
        ):
            raise ValueError("classification Evidence differs from LogicalDocument")
        by_id = {
            str(item.get("source_chunk_asset_version_id") or ""): item
            for item in source_segments
        }
        samples = list(classification_evidence.get("samples") or [])
        if not by_id or not samples:
            raise ValueError("classification requires bounded Source samples")
        for segment in by_id.values():
            content = str(segment.get("content") or "").encode("utf-8")
            if "sha256:" + hashlib.sha256(content).hexdigest() != str(
                segment.get("content_hash") or ""
            ) or len(content) != int(segment.get("byte_size") or -1):
                raise KernelError(
                    "SOURCE_CLASSIFICATION_INPUT_IDENTITY_INVALID",
                    "transient SourceChunk differs from its Authority identity",
                )
        for sample in samples:
            if not isinstance(sample, Mapping):
                raise ValueError("classification sample manifest is invalid")
            segment = by_id.get(str(sample.get("source_chunk_asset_version_id") or ""))
            start = int(sample.get("byte_start") or 0)
            end = int(sample.get("byte_end") or 0)
            if segment is None or start < 0 or end <= start:
                raise ValueError("classification sample manifest is invalid")
            content = str(segment["content"]).encode("utf-8")
            sample_hash = "sha256:" + hashlib.sha256(content[start:end]).hexdigest()
            if end > len(content) or sample_hash != sample.get("sample_hash"):
                raise KernelError(
                    "SOURCE_CLASSIFICATION_SAMPLE_DRIFT",
                    "bounded sample differs from its frozen Evidence hash",
                )
        classifier_contract_hash = _hash(classifier_contract)
        classification_input_hash = _hash(classification_evidence)
        spec = _ExecutionSpec(
            kind="classification",
            stage=CLASSIFICATION_STAGE,
            capability=str(classifier_contract["capability"]),
            prompt_id=str(classifier_contract["classifier_id"]),
            prompt_version=str(classifier_contract["prompt_version"]),
            skill_id="source-content-classifier",
            skill_version=str(classifier_contract["methodology_version"]),
            methodology_content=SOURCE_CLASSIFIER_METHODOLOGY,
            methodology_content_hash=SOURCE_CLASSIFIER_METHODOLOGY_HASH,
            target_scope=TargetScope(
                scope_kind="logical_document",
                scope_id=logical_document_scope_hash,
                project_id=worker.project_id,
                book_id=f"source-corpus:{worker.project_id}",
            ),
            input_payload={
                "logical_document_scope_hash": logical_document_scope_hash,
                "classifier_contract": classifier_contract,
                "classifier_contract_hash": classifier_contract_hash,
                "classification_evidence": classification_evidence,
                "classification_input_hash": classification_input_hash,
            },
            artifact_version_ids=tuple(sorted(by_id)),
            context_contract={
                "logical_document_scope_hash": logical_document_scope_hash,
                "classifier_contract_hash": classifier_contract_hash,
                "classification_input_hash": classification_input_hash,
                "methodology_content_hash": SOURCE_CLASSIFIER_METHODOLOGY_HASH,
                "bounded_samples_only": True,
                "raw_source_text_in_postgresql": False,
                "generation_context_allowed": False,
            },
            output_schema=content_intelligence_output_schema(CLASSIFICATION_STAGE),
        )
        execution = self._execute(worker=worker, spec=spec)
        classification = dict(
            validate_content_intelligence_output(
                spec.stage, spec.output_schema, execution["result"]
            )
        )
        binding = {
            "schema_version": "source-classification-execution-binding.v1",
            "logical_document_scope_hash": logical_document_scope_hash,
            "classifier_contract_hash": classifier_contract_hash,
            "classification_input_hash": classification_input_hash,
            "classification_output_hash": _hash(classification),
        }
        log = self._execution_log(
            worker=worker,
            spec=spec,
            execution=execution,
            domain_binding={"source_classification_binding": binding},
        )
        return {
            "classification": classification,
            "execution_asset_version_id": log.asset_version_id,
            "evidence_class": self._evidence_class(execution),
            "provider_execution_reused": bool(
                execution.get("provider_execution_reused")
            ),
        }

    def execute_deconstruction(
        self,
        *,
        worker: WorkerLeaseCommand,
        analyzer: AnalyzerContract,
        scope: ObservationScope,
        evidence_spans: tuple[ObservationEvidenceSpan, ...],
        source_segments: tuple[dict[str, Any], ...],
        input_observations: tuple[dict[str, Any], ...] = (),
        analysis_plan_asset_version_id: str = "",
        compound_analyzers: tuple[AnalyzerContract, ...] = (),
        sampling_manifest: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        analyzers = compound_analyzers or (analyzer,)
        compound = bool(compound_analyzers)
        if compound and (
            input_observations
            or not evidence_spans
            or analyzer != analyzers[0]
            or not isinstance(sampling_manifest, Mapping)
            or not sampling_manifest
        ):
            raise KernelError(
                "SOURCE_COMPOUND_ANALYSIS_INPUT_INVALID",
                "compound deconstruction requires frozen Source evidence, analyzers, and sampling",
            )
        if len({item.dimension for item in analyzers}) != len(analyzers):
            raise KernelError(
                "SOURCE_COMPOUND_ANALYZER_DUPLICATE",
                "compound deconstruction analyzer dimensions must be unique",
            )
        shared_contract = (
            analyzer.prompt_id,
            analyzer.prompt_version,
            analyzer.skill_id,
            analyzer.skill_version,
            analyzer.capability_id,
            analyzer.capability_version,
            analyzer.provider_policy_version,
            analyzer.methodology_content_hash,
        )
        if any(
            (
                item.prompt_id,
                item.prompt_version,
                item.skill_id,
                item.skill_version,
                item.capability_id,
                item.capability_version,
                item.provider_policy_version,
                item.methodology_content_hash,
            )
            != shared_contract
            for item in analyzers
        ):
            raise KernelError(
                "SOURCE_COMPOUND_ANALYZER_CONTRACT_CONFLICT",
                "compound analyzers must share one frozen capability and methodology",
            )
        if bool(evidence_spans) == bool(input_observations):
            raise KernelError(
                "SOURCE_PEP_INPUT_MODE_INVALID",
                "deconstruction requires Source evidence or lower Observations exclusively",
            )
        by_id = {
            str(item["source_chunk_asset_version_id"]): item for item in source_segments
        }
        for span in evidence_spans:
            segment = by_id.get(span.source_chunk_asset_version_id)
            if segment is None:
                raise KernelError(
                    "SOURCE_PEP_INPUT_IDENTITY_INVALID",
                    "transient Source segment differs from its frozen identity",
                )
            content = str(segment.get("content") or "").encode("utf-8")
            content_hash = "sha256:" + hashlib.sha256(content).hexdigest()
            if content_hash != str(segment.get("content_hash")):
                raise KernelError(
                    "SOURCE_PEP_INPUT_IDENTITY_INVALID",
                    "transient Source segment differs from its frozen identity",
                )
        segment_manifest = [
            {
                "source_chunk_asset_version_id": span.source_chunk_asset_version_id,
                "content_hash": span.evidence_hash,
                "byte_size": span.chunk_byte_end - span.chunk_byte_start,
            }
            for span in evidence_spans
        ]
        observation_manifest = [
            {
                "asset_version_id": str(item["asset_version_id"]),
                "content_hash": str(item["content_hash"]),
                "observation_hash": _hash(item["observation"]),
            }
            for item in input_observations
        ]
        lower_ids = tuple(str(item["asset_version_id"]) for item in input_observations)
        methodology = self.methodology_registry.require(
            analyzer.skill_id,
            expected_digest=analyzer.methodology_content_hash,
        )
        if methodology.skill_version != analyzer.skill_version:
            raise KernelError(
                "SOURCE_ANALYZER_SKILL_VERSION_MISMATCH",
                "Analyzer Skill version differs from canonical methodology",
            )
        analyzer_contract_hashes = [item.fingerprint for item in analyzers]
        frozen_sampling_manifest = dict(sampling_manifest or {})
        sampling_manifest_hash = (
            _hash(frozen_sampling_manifest) if compound else ""
        )
        input_payload = {
            "analyzer": analyzer.to_dict(),
            "scope": scope.to_dict(),
            "evidence_span_ids": [item.evidence_span_id for item in evidence_spans],
            "source_segments": segment_manifest,
            "input_observation_asset_version_ids": list(lower_ids),
            "input_observations": observation_manifest,
            "analysis_plan_asset_version_id": (analysis_plan_asset_version_id),
        }
        if compound:
            input_payload.update(
                {
                    "analyzers": [item.to_dict() for item in analyzers],
                    "requested_dimensions": [item.dimension for item in analyzers],
                    "sampling_manifest": frozen_sampling_manifest,
                    "sampling_manifest_hash": sampling_manifest_hash,
                }
            )
        spec = _ExecutionSpec(
            kind=(
                "deconstruction_compound"
                if compound
                else (
                    "deconstruction_aggregate"
                    if input_observations
                    else "deconstruction"
                )
            ),
            stage=DECONSTRUCTION_STAGE,
            capability=analyzer.capability_id,
            prompt_id=analyzer.prompt_id,
            prompt_version=analyzer.prompt_version,
            skill_id=analyzer.skill_id,
            skill_version=analyzer.skill_version,
            methodology_content=methodology.content,
            methodology_content_hash=methodology.content_digest,
            target_scope=TargetScope(
                scope_kind=scope.scale.lower(),
                scope_id=scope.fingerprint,
                project_id=worker.project_id,
                book_id=f"source-corpus:{worker.project_id}",
            ),
            input_payload=input_payload,
            artifact_version_ids=(
                lower_ids
                if input_observations
                else tuple(
                    item.source_chunk_asset_version_id for item in evidence_spans
                )
            ),
            context_contract={
                "analyzer_contract_hash": analyzer.fingerprint,
                "analyzer_contract_hashes": analyzer_contract_hashes,
                "scope_hash": scope.fingerprint,
                "evidence_span_ids": [item.evidence_span_id for item in evidence_spans],
                "input_observation_asset_version_ids": list(lower_ids),
                "analysis_plan_asset_version_id": (analysis_plan_asset_version_id),
                "sampling_manifest_hash": sampling_manifest_hash,
                "aggregation_uses_source_text": False,
                "raw_source_text_in_postgresql": False,
                "generation_context_allowed": False,
            },
            output_schema=(
                compound_deconstruction_output_schema()
                if compound
                else content_intelligence_output_schema(DECONSTRUCTION_STAGE)
            ),
        )
        execution = self._execute(worker=worker, spec=spec)
        provider_output = validate_content_intelligence_output(
            spec.stage, spec.output_schema, execution["result"]
        )
        if compound:
            requested_dimensions = tuple(item.dimension for item in analyzers)
            returned_dimensions = tuple(
                str(item["dimension"]) for item in provider_output["observations"]
            )
            if returned_dimensions != requested_dimensions:
                raise KernelError(
                    "SOURCE_COMPOUND_ANALYSIS_DIMENSION_MISMATCH",
                    "Provider dimensions differ from the frozen analyzer order",
                )
            whole_work = frozen_sampling_manifest.get("whole_work_analyzed") is True
            expected_coverage = {
                "scope_claim": (
                    "FULL_WORK" if whole_work else "BOUNDED_STRATIFIED_SAMPLE"
                ),
                "uncovered_material_acknowledged": not whole_work,
            }
            if dict(provider_output["coverage_acknowledgement"]) != expected_coverage:
                raise KernelError(
                    "SOURCE_COMPOUND_ANALYSIS_COVERAGE_OVERCLAIM",
                    "Provider coverage acknowledgement differs from frozen sampling",
                )
            dimension_results: list[dict[str, Any]] = []
            bindings: list[dict[str, Any]] = []
            for result, item_analyzer in zip(
                provider_output["observations"], analyzers, strict=True
            ):
                normalized = {
                    "dimension": item_analyzer.dimension,
                    "provider_status": str(result["status"]),
                    "status": str(result["status"]),
                    "applicability_note": str(result["applicability_note"]),
                    "validation_errors": list(result["validation_errors"]),
                    "analyzer_contract_hash": item_analyzer.fingerprint,
                }
                if result["status"] == "SUCCEEDED":
                    candidate_observation = {
                        "findings": [dict(item) for item in result["findings"]],
                        "confidence": result["confidence"],
                        "knowledge_status": result["knowledge_status"],
                    }
                    try:
                        valid_observation = validate_observation_payload(
                            candidate_observation,
                            evidence_spans=evidence_spans,
                        )
                    except (KernelError, ValueError) as exc:
                        normalized["status"] = "FAILED_VALIDATION"
                        normalized["validation_errors"] = [
                            exc.code if isinstance(exc, KernelError) else type(exc).__name__
                        ]
                    else:
                        observation_hash = stable_hash(valid_observation)
                        normalized.update(
                            {
                                "observation": valid_observation,
                                "observation_hash": observation_hash,
                            }
                        )
                        bindings.append(
                            {
                                "schema_version": (
                                    "source-deconstruction-execution-binding.v1"
                                ),
                                "analyzer_contract_hash": item_analyzer.fingerprint,
                                "scope_hash": scope.fingerprint,
                                "observation_hash": observation_hash,
                                "evidence_span_ids": sorted(
                                    {
                                        item.evidence_span_id
                                        for item in evidence_spans
                                    }
                                ),
                                "input_observation_asset_version_ids": [],
                                **(
                                    {
                                        "analysis_plan_asset_version_id": (
                                            analysis_plan_asset_version_id
                                        )
                                    }
                                    if analysis_plan_asset_version_id
                                    else {}
                                ),
                            }
                        )
                dimension_results.append(normalized)
            compound_binding = {
                "schema_version": "source-compound-deconstruction-execution.v1",
                "scope_hash": scope.fingerprint,
                "analyzer_contract_hashes": analyzer_contract_hashes,
                "sampling_manifest_hash": sampling_manifest_hash,
                "coverage_acknowledgement": expected_coverage,
                "dimension_results": [
                    {
                        key: value
                        for key, value in result.items()
                        if key != "observation"
                    }
                    for result in dimension_results
                ],
            }
            log = self._execution_log(
                worker=worker,
                spec=spec,
                execution=execution,
                domain_binding={
                    "source_deconstruction_bindings": bindings,
                    "source_compound_deconstruction_binding": compound_binding,
                },
            )
            return {
                "dimension_results": dimension_results,
                "coverage_acknowledgement": expected_coverage,
                "sampling_manifest_hash": sampling_manifest_hash,
                "execution_asset_version_id": log.asset_version_id,
                "evidence_class": self._evidence_class(execution),
                "provider_execution_reused": bool(
                    execution.get("provider_execution_reused")
                ),
            }
        observation = provider_output
        observation = validate_observation_payload(
            observation,
            evidence_spans=evidence_spans,
            input_observation_asset_version_ids=lower_ids,
        )
        binding = {
            "schema_version": "source-deconstruction-execution-binding.v1",
            "analyzer_contract_hash": analyzer.fingerprint,
            "scope_hash": scope.fingerprint,
            "observation_hash": stable_hash(observation),
            "evidence_span_ids": sorted(
                {item.evidence_span_id for item in evidence_spans}
            ),
            "input_observation_asset_version_ids": sorted(lower_ids),
            **(
                {"analysis_plan_asset_version_id": (analysis_plan_asset_version_id)}
                if analysis_plan_asset_version_id
                else {}
            ),
        }
        log = self._execution_log(
            worker=worker,
            spec=spec,
            execution=execution,
            domain_binding={"source_deconstruction_binding": binding},
        )
        return {
            "observation": observation,
            "execution_asset_version_id": log.asset_version_id,
            "evidence_class": self._evidence_class(execution),
            "provider_execution_reused": bool(
                execution.get("provider_execution_reused")
            ),
        }

    def execute_mkaos_extraction(
        self,
        *,
        worker: WorkerLeaseCommand,
        capability: str,
        abstraction_policy_version: str,
        observation_asset_version_id: str,
        observation: dict[str, Any],
        evidence_spans: tuple[KnowledgeEvidenceSpan, ...],
    ) -> dict[str, Any]:
        if not observation:
            raise ValueError("MKAOS execution requires one Observation")
        methodology = self.methodology_registry.require("anti-copy-abstraction")
        spec = _ExecutionSpec(
            kind="mkaos",
            stage=MKAOS_STAGE,
            capability=capability,
            prompt_id="mkaos.abstraction",
            prompt_version=abstraction_policy_version,
            skill_id="anti-copy-abstraction",
            skill_version=methodology.skill_version,
            methodology_content=methodology.content,
            methodology_content_hash=methodology.content_digest,
            target_scope=TargetScope(
                scope_kind="observation",
                scope_id=observation_asset_version_id,
                project_id=worker.project_id,
                book_id=f"source-corpus:{worker.project_id}",
            ),
            input_payload={
                "observation_asset_version_id": observation_asset_version_id,
                "observation_hash": _hash(observation),
                "abstraction_policy_version": abstraction_policy_version,
                "evidence_manifest_hash": _evidence_manifest_hash(evidence_spans),
            },
            artifact_version_ids=(observation_asset_version_id,),
            context_contract={
                "observation_asset_version_id": observation_asset_version_id,
                "observation_hash": _hash(observation),
                "abstraction_policy_version": abstraction_policy_version,
                "source_expression_available": False,
                "generation_context_allowed": False,
            },
            output_schema=content_intelligence_output_schema(MKAOS_STAGE),
        )
        execution = self._execute(worker=worker, spec=spec)
        candidate = validate_content_intelligence_output(
            spec.stage, spec.output_schema, execution["result"]
        )
        candidate = validate_knowledge_candidate(candidate)
        binding = {
            "schema_version": "mkaos-candidate-execution-binding.v1",
            "candidate_payload_hash": _hash(candidate),
            "abstraction_policy_version": abstraction_policy_version,
            "evidence_manifest_hash": _evidence_manifest_hash(evidence_spans),
            "observation_asset_version_ids": [observation_asset_version_id],
        }
        log = self._execution_log(
            worker=worker,
            spec=spec,
            execution=execution,
            domain_binding={"mkaos_candidate_binding": binding},
        )
        return {
            "candidate": candidate,
            "execution_asset_version_id": log.asset_version_id,
            "provider_execution_reused": bool(
                execution.get("provider_execution_reused")
            ),
        }

    def _execute(
        self, *, worker: WorkerLeaseCommand, spec: _ExecutionSpec
    ) -> dict[str, Any]:
        cache_key = _hash(
            {
                "schema_version": "source-provider-execution-cache.v2",
                "stage": spec.stage,
                "capability": spec.capability,
                "methodology_content_hash": spec.methodology_content_hash,
                "input": spec.input_payload,
                "context_contract": spec.context_contract,
            }
        )
        replay = self._replay_succeeded_effect(worker=worker, cache_key=cache_key)
        if replay is not None:
            return replay
        definition = default_capability_registry().resolve(spec.capability)
        graph = self._operation_graph(worker.causation_id, worker.project_id)
        documents = tuple(
            self.query.require(project_id=worker.project_id, asset_version_id=identity)
            for identity in sorted(set(spec.artifact_version_ids))
        )
        context = self._ensure_contract(
            operation_id=worker.causation_id,
            project_id=worker.project_id,
            logical_ref=(
                "source-intelligence/context/"
                + _token(f"{worker.causation_id}:{worker.attempt_id}:{spec.stage}")
            ),
            asset_type="source_execution_context_manifest",
            contract=spec.context_contract,
            trace_id=worker.trace_id,
            correlation_id=worker.correlation_id,
            eligibility="INELIGIBLE",
        )
        materialization = self._materialization(spec)
        materialization_document = self._ensure_contract(
            operation_id=worker.causation_id,
            project_id=worker.project_id,
            logical_ref=(
                "source-intelligence/capability-materialization/"
                + _token(f"{worker.causation_id}:{worker.attempt_id}:{spec.capability}")
            ),
            asset_type="capability_materialization_manifest",
            contract=materialization,
            trace_id=worker.trace_id,
            correlation_id=worker.correlation_id,
        )
        stable_key = (
            f"{worker.causation_id}:{worker.attempt_id}:{spec.capability}:source-pep-v1"
        )
        base_route = self.transport.routes["quality_source_originality"]
        transient_inputs = PostgresProductionExecutionPayloadResolver(
            self.database_url,
            source_object_reader=self.source_object_reader,
        ).resolve_source_intelligence_inputs(
            project_id=worker.project_id,
            stored_inputs=spec.input_payload,
            metadata={"kind": spec.kind},
        )
        prompt, prompt_evidence = _materialize_source_intelligence_prompt(
            target_scope=spec.target_scope.to_dict(),
            stage=spec.stage,
            inputs=transient_inputs,
            materialization=materialization,
        )
        provider_timeout = self.provider_timeout_seconds
        envelope = ProviderRequestEnvelope(
            provider=base_route.model_profile.model_provider,
            model=base_route.model_profile.model_id,
            protocol=provider_request_protocol(base_route.model_profile.model_provider),
            input_text=prompt,
            max_output_tokens=self.provider_output_token_reserve,
            timeout_seconds=_provider_process_timeout_seconds(
                provider_timeout, max_attempts=2
            ),
            stable_idempotency_key=stable_key,
        )
        token_contract = build_route_token_accounting_contract(
            provider=base_route.model_profile.model_provider,
            model=base_route.model_profile.model_id,
            route_identity=":".join(
                (
                    spec.stage,
                    base_route.model_profile.model_provider,
                    base_route.model_profile.model_id,
                    base_route.release_sha,
                    materialization["materialization_hash"],
                )
            ),
            accounting_method=base_route.token_accounting_method,
            accounting_evidence_ref=base_route.token_accounting_evidence_ref,
            model_context_limit=base_route.model_context_limit,
            output_reserve=self.provider_output_token_reserve,
            safety_margin=base_route.token_safety_margin,
            framing_overhead=base_route.token_framing_overhead,
        )
        provider_admission = prepare_provider_admission(
            envelope,
            token_contract,
            input_component_hashes=dict(prompt_evidence.get("component_hashes") or {}),
            complete_request_coverage=(
                "system_runtime_instructions",
                "prompt_template",
                "skill_instructions",
                "tool_policy_and_schemas",
                "structured_output_schema",
                "source_analysis_input",
                "request_envelope_and_framing",
                "output_reserve",
                "safety_margin",
            ),
        )
        if provider_admission.status != "ADMITTED":
            raise KernelError(
                "PROVIDER_TOKEN_ADMISSION_REJECTED", provider_admission.reason
            )
        admission_contract = {
            "schema_version": "novelos.provider_request_admission.v1",
            "provider_request_identity": envelope.to_identity_dict(),
            "provider_admission": provider_admission.to_dict(),
            "prompt_materialization": prompt_evidence,
            "source_bytes_transient_only": True,
            "capability_materialization_asset_version_id": (
                materialization_document.asset_version_id
            ),
            "capability_materialization_content_hash": (
                materialization_document.content_hash
            ),
        }
        admission_document = self._ensure_contract(
            operation_id=worker.causation_id,
            project_id=worker.project_id,
            logical_ref=(
                "source-intelligence/provider-admission/"
                + _token(f"{worker.attempt_id}:{spec.capability}")
            ),
            asset_type="provider_request_admission_manifest",
            contract=admission_contract,
            trace_id=worker.trace_id,
            correlation_id=worker.correlation_id,
        )
        effect_context = EffectCommandContext(
            operation_id=worker.causation_id,
            project_id=worker.project_id,
            actor_id=self.worker_id,
            trace_id=worker.trace_id,
            correlation_id=worker.correlation_id,
            causation_id=worker.attempt_id,
        )
        request_payload = {
            "stage": spec.stage,
            "input": spec.input_payload,
            "trace_id": worker.trace_id,
            "correlation_id": worker.correlation_id,
            "_source_intelligence": {
                "kind": spec.kind,
                "cache_key": cache_key,
            },
            "_production_execution": {
                "operation_id": worker.causation_id,
                "attempt_id": worker.attempt_id,
                "fencing_token": worker.fencing_token,
                "project_id": worker.project_id,
                "workspace_id": graph["workspace_id"],
                "book_id": spec.target_scope.book_id,
                "worker_id": worker.worker_id,
                "capability_runtime": {
                    "materialization_asset_version_id": (
                        materialization_document.asset_version_id
                    ),
                    "materialization_content_hash": (
                        materialization_document.content_hash
                    ),
                    "materialization_hash": materialization["materialization_hash"],
                    "provider_admission_asset_version_id": (
                        admission_document.asset_version_id
                    ),
                    "provider_admission_content_hash": (
                        admission_document.content_hash
                    ),
                    "provider_request_envelope_hash": envelope.envelope_hash,
                    "token_accounting_contract": token_contract.to_dict(),
                    "provider_admission": provider_admission.to_dict(),
                },
            },
            "max_output_tokens": self.provider_output_token_reserve,
        }
        effect = plan_external_effect(
            self.database_url,
            effect_context,
            effect_type="model.invoke",
            provider=self.transport.provider,
            capability=spec.capability,
            stable_idempotency_key=stable_key,
            request_payload=request_payload,
            max_attempts=2,
            reversible=False,
            completion_policy="synchronous_final",
            model_id=base_route.model_profile.model_id,
            request_timeout_seconds=provider_timeout,
            reconciliation_mode=self.transport.reconciliation_mode,
            provider_capability_profile=self.transport.capability_profile.to_dict(),
        )
        effect_id = str(effect["external_effect_id"])
        reservation = reserve_provider_budget(
            self.database_url,
            BudgetReservationRequest(
                operation_id=worker.causation_id,
                external_effect_id=effect_id,
                project_id=worker.project_id,
                stable_idempotency_key=f"budget:{stable_key}",
                provider=self.transport.provider,
                currency=(
                    "UNKNOWN"
                    if self.cost_accounting_basis == "ACCOUNT_ENTITLEMENT"
                    else "USD"
                ),
                estimated_amount=(
                    None
                    if self.cost_accounting_basis == "ACCOUNT_ENTITLEMENT"
                    else self.max_cost_per_call
                ),
                estimated_tokens=int(provider_admission.total_reserved),
                caps=self.budget_caps,
                call_caps=self.provider_call_caps,
                token_caps=self.provider_token_caps,
                accounting_basis=self.cost_accounting_basis,
                cost_authorization_ref=self.account_authorization_ref,
            ),
        )
        binding = self._binding(
            worker=worker,
            spec=spec,
            definition=definition,
            graph=graph,
            documents=documents,
            context=context,
            provider_admission=admission_document,
            effect_id=effect_id,
            stable_key=stable_key,
            reservation_id=str(reservation["reservation_id"]),
        )
        adapter = _SourceGatewayEffectAdapter(transport=self.transport, binding=binding)
        try:
            dispatched = dispatch_external_effect(
                self.database_url,
                effect_context,
                effect_id=effect_id,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
                adapter=adapter,
            )
        except Exception:
            resolve_provider_budget_failure(
                self.database_url,
                reservation_id=str(reservation["reservation_id"]),
                project_id=worker.project_id,
            )
            raise
        if dispatched["outcome"] != "success" or not isinstance(
            dispatched.get("provider_evidence"), Mapping
        ):
            resolve_provider_budget_failure(
                self.database_url,
                reservation_id=str(reservation["reservation_id"]),
                project_id=worker.project_id,
            )
            raise KernelError(
                "SOURCE_PEP_EXECUTION_FAILED",
                f"Source Provider outcome was {dispatched.get('outcome')}",
            )
        evidence = dict(dispatched["provider_evidence"])
        result = evidence.get("result")
        usage = evidence.get("usage")
        cost = evidence.get("cost")
        if not all(isinstance(item, Mapping) for item in (result, usage, cost)):
            raise KernelError(
                "SOURCE_PEP_EVIDENCE_INCOMPLETE",
                "Source PEP result lacks output, usage, or cost evidence",
            )
        assert isinstance(usage, Mapping)
        assert isinstance(cost, Mapping)
        total_tokens = int(
            usage.get("total_tokens")
            or int(usage.get("input_tokens") or 0)
            + int(usage.get("output_tokens") or 0)
        )
        amount = (
            None
            if self.cost_accounting_basis == "ACCOUNT_ENTITLEMENT"
            else str(cost.get("amount") or cost.get("amount_usd") or "0")
        )
        settle_provider_budget(
            self.database_url,
            reservation_id=str(reservation["reservation_id"]),
            project_id=worker.project_id,
            actual_amount=amount,
            actual_tokens=total_tokens,
            evidence={
                "provider_id": str(evidence.get("provider_id") or ""),
                "model_id": str(evidence.get("model_id") or ""),
                "real_model_call": bool(evidence.get("real_model_call")),
                "fixture": bool(evidence.get("fixture_protocol_only")),
                "accounting_basis": self.cost_accounting_basis,
                "cost_status": (
                    "UNKNOWN"
                    if self.cost_accounting_basis == "ACCOUNT_ENTITLEMENT"
                    else "KNOWN"
                ),
                "token_accounting_precision": token_contract.precision,
                "actual_token_source": "PROVIDER_USAGE_RECEIPT",
            },
        )
        return evidence

    def _replay_succeeded_effect(
        self, *, worker: WorkerLeaseCommand, cache_key: str
    ) -> dict[str, Any] | None:
        runtime = get_database_runtime(self.database_url)
        with runtime.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT effect.external_effect_id,
                           CASE
                             WHEN effect.reconciliation <> '{}'::jsonb
                               THEN effect.reconciliation
                             ELSE dispatch.evidence
                           END,
                           reservation.reservation_id,
                           reservation.status,
                           effect.request_payload
                    FROM authority_external_effect AS effect
                    JOIN LATERAL (
                        SELECT evidence
                        FROM authority_external_effect_dispatch
                        WHERE external_effect_id=effect.external_effect_id
                          AND status='SUCCEEDED'
                        ORDER BY generation DESC
                        LIMIT 1
                    ) AS dispatch ON TRUE
                    LEFT JOIN LATERAL (
                        SELECT reservation_id, status
                        FROM authority_budget_reservation
                        WHERE external_effect_id=effect.external_effect_id
                        ORDER BY created_at DESC
                        LIMIT 1
                    ) AS reservation ON TRUE
                    WHERE effect.project_id=%s
                      AND effect.status='SUCCEEDED'
                      AND effect.request_payload->'_source_intelligence'
                            ->>'cache_key'=%s
                    ORDER BY effect.created_at DESC
                    LIMIT 1
                    """,
                    [worker.project_id, cache_key],
                )
                row = cursor.fetchone()
        if row is None or not isinstance(row[1], Mapping):
            return None
        evidence = dict(row[1])
        result = evidence.get("result")
        usage = evidence.get("usage")
        cost = evidence.get("cost")
        if not all(isinstance(value, Mapping) for value in (result, usage, cost)):
            raise KernelError(
                "SOURCE_PEP_REPLAY_EVIDENCE_INCOMPLETE",
                "succeeded Provider effect has incomplete durable evidence",
            )
        if row[2] and str(row[3]) in {"RESERVED", "HELD_UNKNOWN"}:
            assert isinstance(usage, Mapping)
            assert isinstance(cost, Mapping)
            total_tokens = int(
                usage.get("total_tokens")
                or int(usage.get("input_tokens") or 0)
                + int(usage.get("output_tokens") or 0)
            )
            request_payload = row[4] if isinstance(row[4], Mapping) else {}
            production = request_payload.get("_production_execution", {})
            runtime = (
                production.get("capability_runtime", {})
                if isinstance(production, Mapping)
                else {}
            )
            token_contract = (
                runtime.get("token_accounting_contract", {})
                if isinstance(runtime, Mapping)
                else {}
            )
            settle_provider_budget(
                self.database_url,
                reservation_id=str(row[2]),
                project_id=worker.project_id,
                actual_amount=(
                    None
                    if self.cost_accounting_basis == "ACCOUNT_ENTITLEMENT"
                    else str(cost.get("amount") or cost.get("amount_usd") or "0")
                ),
                actual_tokens=total_tokens,
                evidence={
                    "replayed_after_worker_failure": True,
                    "external_effect_id": str(row[0]),
                    "token_accounting_precision": str(
                        token_contract.get("precision") or ""
                    ),
                    "actual_token_source": "PROVIDER_USAGE_RECEIPT",
                },
            )
        return {
            **evidence,
            "provider_execution_reused": True,
            "reused_external_effect_id": str(row[0]),
        }

    def _binding(
        self,
        *,
        worker: WorkerLeaseCommand,
        spec: _ExecutionSpec,
        definition: Any,
        graph: dict[str, str],
        documents: tuple[AuthorityAssetDocument, ...],
        context: AuthorityAssetDocument,
        provider_admission: AuthorityAssetDocument,
        effect_id: str,
        stable_key: str,
        reservation_id: str,
    ) -> ChapterExecutionBinding:
        base = self.transport.routes["quality_source_originality"]
        suffix = spec.capability.replace(".", "-")
        profile = ModelProfile(
            profile_id=f"source-intelligence.{suffix}.default",
            profile_version=1,
            backend_id=base.model_profile.backend_id,
            runtime_class=base.model_profile.runtime_class,
            model_provider=base.model_profile.model_provider,
            model_id=base.model_profile.model_id,
            reasoning_effort=base.model_profile.reasoning_effort,
            timeout_policy_ref=definition.timeout_policy_ref,
            workspace_policy_ref="workspace:source-intelligence:v1",
            output_policy_ref=definition.output_schema_ref,
            fallback_policy="FAIL_CLOSED",
            status=base.model_profile.status,
            capability_probe_ref=base.model_profile.capability_probe_ref,
        )
        policy = RoutePolicy(
            policy_id=f"source-intelligence.{suffix}.route",
            policy_version=1,
            default_model_profile_id=profile.profile_id,
            allowed_model_profile_ids=(profile.profile_id,),
            rule_set_ref=f"route-rules:source-intelligence:{suffix}:v1",
            fallback_policy="FAIL_CLOSED",
            fallback_policy_ref=f"source-intelligence.{suffix}.fail-closed",
            fallback_policy_version=1,
            reasoning_downgrade_policy="PROHIBITED",
            status="ACTIVE",
        )
        fallback = FallbackPolicy.fail_closed(
            policy.fallback_policy_ref, policy.fallback_policy_version
        )
        context_ref = f"asset-version:{context.asset_version_id}"
        prompt_ref = (
            f"source-intelligence/prompts/{spec.prompt_id}/{spec.prompt_version}"
        )
        skill_ref = f"source-intelligence/skills/{spec.skill_id}/{spec.skill_version}"
        input_ref = "production_execution/inputs/" + _token(
            f"{worker.causation_id}:{worker.attempt_id}:{spec.capability}"
        )
        route_ref = "production_execution/routes/" + _token(
            f"{worker.causation_id}:{worker.attempt_id}:{spec.capability}"
        )
        pointers = (
            ArtifactPointer(
                artifact_ref=context_ref,
                asset_version_id=context.asset_version_id,
                artifact_type=context.asset_type,
                content_hash=context.content_hash,
                schema_version="source-execution-context.v1",
                source_eligibility="SOURCE_ANALYSIS_ONLY",
            ),
            *tuple(
                ArtifactPointer(
                    artifact_ref=f"asset-version:{document.asset_version_id}",
                    asset_version_id=document.asset_version_id,
                    artifact_type=document.asset_type,
                    content_hash=document.content_hash,
                    schema_version=f"{document.asset_type}.v1",
                    source_eligibility="SOURCE_ANALYSIS_ONLY",
                )
                for document in documents
            ),
            ArtifactPointer(
                artifact_ref=f"asset-version:{provider_admission.asset_version_id}",
                asset_version_id=provider_admission.asset_version_id,
                artifact_type=provider_admission.asset_type,
                content_hash=provider_admission.content_hash,
                schema_version="novelos.provider_request_admission.v1",
                source_eligibility="NOT_SOURCE_DERIVED",
            ),
        )
        manifest = InputManifest(
            manifest_id=input_ref,
            operation_id=worker.causation_id,
            attempt_id=worker.attempt_id,
            fencing_token=worker.fencing_token,
            project_id=worker.project_id,
            book_id=spec.target_scope.book_id,
            target_scope=spec.target_scope,
            context_bundle_ref=context_ref,
            prompt_bundle_ref=prompt_ref,
            skill_bundle_ref=skill_ref,
            context_bundle_version=context.asset_version_id,
            prompt_bundle_version=spec.prompt_version,
            skill_bundle_version=spec.skill_version,
            canon_snapshot_version="not-applicable",
            story_state_version="not-applicable",
            planning_version="not-applicable",
            quality_profile_version="source-intelligence.v1",
            source_policy_ref=definition.source_policy_ref,
            source_eligibility="SOURCE_ANALYSIS_ONLY",
            canon_version_refs=(),
            arc_version_refs=(),
            input_artifacts=pointers,
            read_set=tuple(item.artifact_ref for item in pointers),
        )
        route = RouteSnapshot(
            route_snapshot_id=route_ref,
            route_decision_id=f"route-decision:{_token(route_ref)}",
            operation_id=worker.causation_id,
            attempt_id=worker.attempt_id,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            backend_id=profile.backend_id,
            backend_version=base.backend_version,
            runtime_host_id=base.runtime_host_id,
            auth_profile_ref=base.auth_profile_ref,
            model_profile_id=profile.profile_id,
            model_profile_version=profile.profile_version,
            model_profile_hash=profile.contract_hash,
            route_policy_hash=policy.contract_hash,
            model_provider=profile.model_provider,
            model_id=profile.model_id,
            requested_reasoning_effort=profile.reasoning_effort,
            reasoning_effort=profile.reasoning_effort,
            prompt_bundle_ref=prompt_ref,
            skill_bundle_ref=skill_ref,
            context_bundle_ref=context_ref,
            output_schema_ref=definition.output_schema_ref,
            release_sha=base.release_sha,
            fallback_policy_ref=fallback.policy_id,
            fallback_policy_version=fallback.policy_version,
        )
        for logical_ref, asset_type, contract in (
            (
                f"production_execution/model_profiles/{profile.profile_id}/v1",
                "model_profile",
                profile.to_dict(),
            ),
            (
                f"production_execution/route_policies/{policy.policy_id}/v1",
                "route_policy",
                policy.to_dict(),
            ),
            (
                f"production_execution/fallback_policies/{fallback.policy_id}/v1",
                "fallback_policy",
                fallback.to_dict(),
            ),
            (input_ref, "input_manifest", manifest.to_dict()),
            (route_ref, "route_snapshot", route.to_dict()),
        ):
            self._ensure_contract(
                operation_id=worker.causation_id,
                project_id=worker.project_id,
                logical_ref=logical_ref,
                asset_type=asset_type,
                contract=contract,
                trace_id=worker.trace_id,
                correlation_id=worker.correlation_id,
            )
        request = ExecutionRequest(
            execution_id=f"source-intelligence-execution:{effect_id}",
            operation_id=worker.causation_id,
            root_operation_id=graph["root_operation_id"],
            saga_id=graph["saga_id"],
            attempt_id=worker.attempt_id,
            fencing_token=worker.fencing_token,
            project_id=worker.project_id,
            workspace_id=graph["workspace_id"],
            book_id=spec.target_scope.book_id,
            target_scope=spec.target_scope,
            domain=definition.domain.value,
            task_kind=graph["definition_name"],
            stage=spec.stage,
            capability=spec.capability,
            importance_class="HIGH",
            risk_class=definition.risk_class.value,
            route_snapshot_id=route_ref,
            workspace_snapshot_ref=graph["workspace_id"],
            input_manifest_ref=input_ref,
            resource_claims=(f"source-intelligence:{spec.target_scope.scope_id}",),
            timeout_policy_ref=definition.timeout_policy_ref,
            budget_policy_ref=definition.budget_policy_ref,
            permission_policy_ref=definition.permission_policy_ref,
            validation_policy_ref=definition.validation_policy_ref,
            commit_policy_ref=definition.commit_policy_ref,
            stable_idempotency_key=stable_key,
            origin_chain=("source.import", spec.kind),
            trace_id=worker.trace_id,
            correlation_id=worker.correlation_id,
            external_effect_id=effect_id,
            budget_reservation_id=reservation_id,
        )
        return ChapterExecutionBinding(request, route, manifest)

    def _materialization(self, spec: _ExecutionSpec) -> dict[str, Any]:
        system_text = (
            "You analyze governed source evidence for reusable abstract mechanisms. "
            "Never reproduce protected expression or treat an Observation as reusable "
            "knowledge before MKAOS governance."
        )
        skill_text = spec.methodology_content
        actual_skill_hash = (
            "sha256:" + hashlib.sha256(skill_text.encode("utf-8")).hexdigest()
        )
        if actual_skill_hash != spec.methodology_content_hash:
            raise KernelError(
                "SOURCE_SKILL_MATERIALIZATION_DRIFT",
                "frozen Skill bytes differ from Analyzer methodology digest",
            )
        template_text = (
            "Perform the frozen Source intelligence stage and return a bounded JSON "
            "object matching the supplied schema."
        )
        output_ref = (
            default_capability_registry().resolve(spec.capability).output_schema_ref
        )
        materialization: dict[str, Any] = {
            "schema_version": "source-capability-materialization.v1",
            "stage": spec.stage,
            "capability": spec.capability,
            "system_instruction": {
                "ref": "source-intelligence-system",
                "version": "1.0",
                "content_hash": _hash(system_text),
                "text": system_text,
            },
            "prompt_template": {
                "ref": spec.prompt_id,
                "version": spec.prompt_version,
                "content_hash": _hash(template_text),
                "text": template_text,
            },
            "skill": {
                "ref": spec.skill_id,
                "version": spec.skill_version,
                "content_hash": spec.methodology_content_hash,
                "text": skill_text,
            },
            "tool_permissions": {
                "default": "DENY",
                "allowed": ["model.provider.invoke"],
                "denied": ["shell", "filesystem", "web", "mcp"],
            },
            "output_schema": {
                "ref": output_ref,
                "content_hash": _hash(spec.output_schema),
                "content": spec.output_schema,
            },
            "source_isolation": {
                "raw_source_persisted_in_postgresql": False,
                "raw_source_allowed_in_generation_context": False,
                "provider_input_resolved_from_object_store": True,
            },
        }
        materialization["materialization_hash"] = _hash(materialization)
        return materialization

    def _execution_log(
        self,
        *,
        worker: WorkerLeaseCommand,
        spec: _ExecutionSpec,
        execution: dict[str, Any],
        domain_binding: dict[str, Any],
    ) -> AuthorityAssetDocument:
        content = {
            "schema_version": "source-model-call-log.v1",
            "production_execution_gateway_backed": True,
            "gateway": "ProductionExecutionGateway",
            "fixture_protocol_only": bool(execution.get("fixture_protocol_only")),
            "real_provider_proven": bool(execution.get("real_model_call")),
            "production_verified": bool(execution.get("production_verified")),
            "provider_id": str(execution.get("provider_id") or ""),
            "model_id": str(execution.get("model_id") or ""),
            "prompt_version": str(execution.get("prompt_version") or ""),
            "skill_version": str(execution.get("skill_version") or ""),
            "capability": spec.capability,
            "methodology": {
                "skill_id": spec.skill_id,
                "skill_version": spec.skill_version,
                "content_hash": spec.methodology_content_hash,
            },
            "usage": dict(execution.get("usage") or {}),
            "cost": dict(execution.get("cost") or {}),
            "production_execution": dict(execution.get("production_execution") or {}),
            **domain_binding,
        }
        return self.writer.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=worker.causation_id,
                project_id=worker.project_id,
                asset_id=(
                    f"model-call-log:{worker.causation_id}:{worker.attempt_id}:"
                    f"{_token(spec.capability)}"
                ),
                asset_type="model_call_log",
                schema_version="source-model-call-log.v1",
                logical_ref=(
                    f"runs/model_call_logs/{worker.causation_id}-"
                    f"{worker.attempt_id}-{_token(spec.capability)}.json"
                ),
                category="runs",
                output_key=f"model_call_log.source.{_token(spec.capability)}",
                role="model_evidence",
                content=content,
                qualification_policy="source-content-intelligence-execution-v1",
                trace_id=worker.trace_id,
                correlation_id=worker.correlation_id,
            )
        )

    def _ensure_contract(
        self,
        *,
        operation_id: str,
        project_id: str,
        logical_ref: str,
        asset_type: str,
        contract: dict[str, Any],
        trace_id: str,
        correlation_id: str,
        eligibility: str = "ELIGIBLE",
    ) -> AuthorityAssetDocument:
        try:
            existing = self.query.require(
                project_id=project_id, logical_ref=logical_ref
            )
        except KernelError as exc:
            if exc.code != "AUTHORITY_ASSET_NOT_FOUND":
                raise
            existing = None
        if existing is not None:
            if (
                existing.asset_type != asset_type
                or existing.content.get("contract", existing.content) != contract
            ):
                raise KernelError(
                    "SOURCE_EXECUTION_CONTRACT_FROZEN_CONFLICT",
                    "Source execution contract changed inside one identity",
                )
            return existing
        return self.writer.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=operation_id,
                project_id=project_id,
                asset_id=f"production-execution-contract:{_token(project_id + logical_ref)}",
                asset_type=asset_type,
                schema_version="production-execution-contract.v1",
                logical_ref=logical_ref,
                category="production_execution_contracts",
                output_key=f"production_execution.contract.{asset_type}.{_token(logical_ref)}",
                role="execution_contract",
                content={"contract": contract},
                qualification_policy="production-execution-contract-v1",
                trace_id=trace_id,
                correlation_id=correlation_id,
                eligibility=eligibility,
                governance="CLEAR",
            )
        )

    def _operation_graph(self, operation_id: str, project_id: str) -> dict[str, str]:
        runtime = get_database_runtime(self.database_url)
        with runtime.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT definition_name, root_operation_id,
                           COALESCE(NULLIF(saga_id, ''), root_operation_id),
                           workspace_id
                    FROM authority_operation
                    WHERE operation_id=%s AND project_id=%s
                    """,
                    [operation_id, project_id],
                )
                row = cursor.fetchone()
        if row is None or not all(row):
            raise KernelError(
                "SOURCE_EXECUTION_GRAPH_INVALID",
                "Source PEP execution has no admitted Operation graph",
            )
        return {
            "definition_name": str(row[0]),
            "root_operation_id": str(row[1]),
            "saga_id": str(row[2]),
            "workspace_id": str(row[3]),
        }

    @staticmethod
    def _evidence_class(execution: Mapping[str, Any]) -> str:
        if bool(execution.get("fixture_protocol_only")):
            return "FIXTURE"
        if bool(execution.get("real_model_call")) and bool(
            execution.get("production_verified")
        ):
            return "PROVIDER_QUALIFIED"
        return "PROVIDER_UNCALIBRATED"


def _evidence_manifest_hash(
    evidence_spans: tuple[KnowledgeEvidenceSpan, ...],
) -> str:
    return _hash(
        {
            "evidence_spans": [
                asdict(item)
                for item in sorted(
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


__all__ = ["PostgresContentIntelligenceExecutionPort"]
