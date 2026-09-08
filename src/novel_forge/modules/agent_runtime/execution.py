from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from novel_forge.modules.chapter_authority.contracts import (
    ChapterHandlerRequest,
    ChapterInputAsset,
    resolve_stage_context_token_budget,
)
from novel_forge.modules.chapter_authority.execution_gateway import (
    ChapterExecutionBinding,
    PostgresChapterExecutionContractBinder,
    ProductionExecutionGatewayExternalEffectAdapter,
    chapter_stage_capability,
)
from novel_forge.modules.chapter_authority.model_effects import (
    ExternalEffectChapterModelPort,
    ModelProviderResult,
)
from novel_forge.modules.command_kernel.budget_runtime import (
    BudgetReservationRequest,
    reserve_provider_budget,
    resolve_provider_token_reservation_contract,
    resolve_provider_budget_failure,
    settle_provider_budget,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    dispatch_external_effect,
    plan_external_effect,
    read_external_effect_intent,
)
from novel_forge.modules.production_execution.domain_execution import (
    CandidateKind,
    DomainExecutionCandidate,
    DomainExecutionCommand,
    DomainExecutionEvidence,
)
from novel_forge.modules.production_execution.contracts import ExecutionRecoveryAction
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
from novel_forge.storage.database_runtime import get_database_runtime

from .scheduler import PreparedAgentExecution


_STAGES = frozenset(
    {
        "draft",
        "review",
        "revision",
        "rereview",
        "canon_extraction",
        "quality_structural",
        "quality_commercial",
        "quality_source_originality",
        "quality_longform",
        "quality_platform",
        "reader_outcome",
    }
)


class ChapterGatewayAgentExecutionPreparer:
    def __init__(
        self,
        database_url: str,
        *,
        adapter: ProductionExecutionGatewayExternalEffectAdapter,
        capability_binder: PostgresChapterExecutionContractBinder,
        worker_id: str,
        lease_seconds: int = 60,
        max_cost_per_call: str = "0",
        budget_caps: Mapping[str, str] | None = None,
    ) -> None:
        if not database_url or not worker_id or lease_seconds <= 0:
            raise ValueError("Agent PEP preparer requires database, worker, and lease")
        if not getattr(adapter, "production_execution_gateway_backed", False):
            raise ValueError("Agent production execution requires the PEP adapter")
        self.database_url = database_url
        self.adapter = adapter
        self.capability_binder = capability_binder
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.max_cost_per_call = max_cost_per_call
        self.budget_caps = dict(budget_caps or {})
        self.cost_accounting_basis = str(
            getattr(adapter, "cost_accounting_basis", "PRICED") or "PRICED"
        ).upper()
        self.account_authorization_ref = str(
            getattr(adapter, "account_authorization_ref", "") or ""
        )
        self.provider_call_caps = {
            str(key): int(value)
            for key, value in dict(
                getattr(adapter, "provider_call_caps", {}) or {}
            ).items()
        }
        self.provider_token_caps = {
            str(key): int(value)
            for key, value in dict(
                getattr(adapter, "provider_token_caps", {}) or {}
            ).items()
        }
        self.assets = AuthorityAssetQuery(database_url)
        self.evidence_writer = ExternalEffectChapterModelPort(
            database_url,
            adapter=adapter,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            max_cost_per_call=max_cost_per_call,
            budget_caps=dict(budget_caps or {}),
        )

    def prepare(
        self,
        *,
        operation: dict[str, Any],
        attempt_id: str,
        execution_fencing_token: int,
        recovery_fencing_token: int,
        worker_id: str,
    ) -> PreparedAgentExecution:
        if worker_id != self.worker_id:
            raise KernelError(
                "AGENT_WORKER_IDENTITY_DRIFT", "PEP preparer belongs to another worker"
            )
        command = dict(operation["command_payload"])
        stage = str(command["workflow_node_id"])
        if stage not in _STAGES:
            raise KernelError(
                "AGENT_CHAPTER_STAGE_UNSUPPORTED",
                f"unsupported Agent-bound Chapter stage: {stage}",
            )
        expected_capability = chapter_stage_capability(stage).value
        if str(command["execution_capability_id"]) != expected_capability:
            raise KernelError(
                "AGENT_EXECUTION_CAPABILITY_DRIFT",
                "Agent Capability mapping differs from the Chapter PEP Capability",
            )
        inputs = self._input_assets(
            project_id=str(operation["project_id"]),
            asset_version_ids=tuple(command["input_asset_versions"]),
        )
        effect_context = EffectCommandContext(
            operation_id=str(operation["operation_id"]),
            project_id=str(operation["project_id"]),
            actor_id=self.worker_id,
            trace_id=str(operation["trace_id"]),
            correlation_id=str(operation["correlation_id"]),
        )
        stable_key = f"{operation['operation_id']}:{attempt_id}:{stage}:agent-v1"
        execution_fencing_token, execution_worker_id = self._execution_identity(
            operation=operation,
            attempt_id=attempt_id,
            stable_key=stable_key,
            execution_fencing_token=execution_fencing_token,
        )
        frozen_context_ceiling = max(
            (
                int(item.content.get("token_budget") or 0)
                for item in inputs
                if item.asset_type == "context_bundle"
            ),
            default=0,
        )
        frozen_request_token_ceiling = resolve_stage_context_token_budget(
            command, stage, default=frozen_context_ceiling
        )
        if frozen_request_token_ceiling <= 0:
            raise KernelError(
                "MODEL_EFFECT_PROVIDER_TOKEN_CEILING_REQUIRED",
                "Agent-bound Provider execution requires a positive token ceiling",
            )
        cost_accounting_basis = str(
            getattr(
                self,
                "cost_accounting_basis",
                getattr(self.adapter, "cost_accounting_basis", "PRICED"),
            )
            or "PRICED"
        ).upper()
        account_authorization_ref = str(
            getattr(
                self,
                "account_authorization_ref",
                getattr(self.adapter, "account_authorization_ref", ""),
            )
            or ""
        )
        provider_token_contract = resolve_provider_token_reservation_contract(
            self.database_url,
            operation_id=str(operation["operation_id"]),
            project_id=str(operation["project_id"]),
            currency=(
                "UNKNOWN" if cost_accounting_basis == "ACCOUNT_ENTITLEMENT" else "USD"
            ),
            frozen_request_token_ceiling=frozen_request_token_ceiling,
            accounting_basis=cost_accounting_basis,
            cost_authorization_ref=account_authorization_ref,
        )
        provider_output_token_ceiling = int(
            provider_token_contract["max_output_tokens"]
        )
        provider_budget_tokens = int(provider_token_contract["estimated_total_tokens"])
        route = self.adapter.routes.get(stage)
        provider_token_limit = (
            provider_budget_tokens
            if provider_token_contract["source"]
            == "BOOK_OPENING_IMMUTABLE_PER_CALL_POLICY"
            else int(getattr(route, "model_context_limit", 0) or 0)
            or provider_budget_tokens
        )
        payload = {
            "stage": stage,
            "max_output_tokens": provider_output_token_ceiling,
            "stable_idempotency_key": stable_key,
            "input": _stage_payload(stage, inputs),
            "trace_id": str(operation["trace_id"]),
            "correlation_id": str(operation["correlation_id"]),
            "workspace_id": str(operation["workspace_id"]),
            "_production_execution": {
                "operation_id": str(operation["operation_id"]),
                "attempt_id": attempt_id,
                "fencing_token": execution_fencing_token,
                "project_id": str(operation["project_id"]),
                "workspace_id": str(operation["workspace_id"]),
                "worker_id": execution_worker_id,
                "chapter": int(command["chapter_number"]),
                "book_id": str(command["book_id"]),
                "route_provider": self.adapter.provider_id_for_stage(stage),
                "provider_request_timeout_seconds": self.lease_seconds * 5,
                "provider_token_limit": provider_token_limit,
                "input_artifacts": [
                    {
                        "artifact_ref": f"asset-version:{item.asset_version_id}",
                        "asset_version_id": item.asset_version_id,
                        "artifact_type": item.asset_type,
                        "content_hash": item.content_hash,
                        "schema_version": str(
                            item.content.get("schema_version")
                            or item.content.get("contract_version")
                            or f"{item.asset_type}.v1"
                        ),
                        "source_eligibility": "PRODUCTION_ELIGIBLE",
                    }
                    for item in inputs
                ],
            },
        }
        provider_admission_required = bool(
            self.adapter.production_execution_gateway_backed
            and self.adapter.provider_id_for_stage(stage) != "scripted_provider_v2"
        )
        existing_intent = read_external_effect_intent(
            self.database_url,
            effect_context,
            effect_type="model.invoke",
            stable_idempotency_key=stable_key,
        )
        if existing_intent is not None:
            frozen_payload = dict(existing_intent["request_payload"])
            expected_outer = {
                key: value
                for key, value in payload.items()
                if key != "_production_execution"
            }
            frozen_outer = {
                key: value
                for key, value in frozen_payload.items()
                if key != "_production_execution"
            }
            frozen_metadata = frozen_payload.get("_production_execution")
            if (
                frozen_outer != expected_outer
                or existing_intent["provider"] != self.adapter.provider
                or existing_intent["capability"] != f"model.{stage}"
                or int(existing_intent["max_attempts"]) != 2
                or not isinstance(frozen_metadata, Mapping)
                or str(frozen_metadata.get("operation_id") or "")
                != str(operation["operation_id"])
                or str(frozen_metadata.get("attempt_id") or "") != attempt_id
                or str(frozen_metadata.get("project_id") or "")
                != str(operation["project_id"])
                or str(frozen_metadata.get("book_id") or "") != str(command["book_id"])
            ):
                raise KernelError(
                    "AGENT_EFFECT_INTENT_DRIFT",
                    "Agent retry differs from the first frozen Provider intent",
                )
            frozen_runtime = frozen_metadata.get("capability_runtime")
            if isinstance(frozen_runtime, Mapping):
                frozen_admission = frozen_runtime.get("provider_admission")
                if isinstance(frozen_admission, Mapping):
                    frozen_total = int(frozen_admission.get("total_reserved") or 0)
                    if frozen_total <= 0:
                        raise KernelError(
                            "PROVIDER_ADMISSION_INVALID",
                            "frozen Agent admission has no positive bounded usage",
                        )
                    provider_budget_tokens = frozen_total
            payload = frozen_payload
        else:
            preflight = self.capability_binder.freeze_before_external_effect(
                capability=f"model.{stage}",
                request_payload=payload,
                snapshot_fencing_token=recovery_fencing_token,
                snapshot_worker_id=worker_id,
            )
            if provider_admission_required and (
                preflight is None or preflight.provider_admission_artifact is None
            ):
                raise KernelError(
                    "PROVIDER_ADMISSION_REQUIRED",
                    "Agent execution cannot create an ExternalEffect without admission",
                )
            if preflight is not None:
                if provider_admission_required:
                    receipt = preflight.effect_binding.get("provider_admission")
                    if not isinstance(receipt, Mapping):
                        raise KernelError(
                            "PROVIDER_ADMISSION_REQUIRED",
                            "Agent admission receipt is absent from the frozen binding",
                        )
                    provider_budget_tokens = int(receipt.get("total_reserved") or 0)
                    if provider_budget_tokens <= 0:
                        raise KernelError(
                            "PROVIDER_ADMISSION_INVALID",
                            "Agent admission has no positive bounded request usage",
                        )
                metadata = dict(payload["_production_execution"])
                frozen_artifacts = list(metadata["input_artifacts"])
                frozen_artifacts.append(preflight.materialization_artifact.to_dict())
                if preflight.provider_admission_artifact is not None:
                    frozen_artifacts.append(
                        preflight.provider_admission_artifact.to_dict()
                    )
                metadata.update(
                    {
                        "input_artifacts": frozen_artifacts,
                        "capability_runtime": dict(preflight.effect_binding),
                    }
                )
                payload = {**payload, "_production_execution": metadata}
        effect = plan_external_effect(
            self.database_url,
            effect_context,
            effect_type="model.invoke",
            provider=self.adapter.provider,
            capability=f"model.{stage}",
            stable_idempotency_key=stable_key,
            request_payload=payload,
            max_attempts=2,
            reversible=False,
            completion_policy="synchronous_final",
            model_id=self.adapter.model_id_for_stage(stage),
            request_timeout_seconds=self.lease_seconds * 5,
            reconciliation_mode=self.adapter.reconciliation_mode,
            provider_capability_profile=self.adapter.capability_profile.to_dict(),
        )
        effect_adapter: Any = self.adapter
        if bool(effect.get("replayed")):
            effect_adapter = self.adapter.for_recovery(
                execution_id=("chapter-execution:" + str(effect["external_effect_id"])),
                external_effect_id=str(effect["external_effect_id"]),
                operation_id=str(operation["operation_id"]),
                attempt_id=attempt_id,
                execution_fencing_token=execution_fencing_token,
                recovery_fencing_token=recovery_fencing_token,
                recovery_worker_id=worker_id,
                action=ExecutionRecoveryAction.DISPATCH_PLANNED,
                trace_id=str(operation["trace_id"]),
                correlation_id=str(operation["correlation_id"]),
            )
            effect_adapter.record_authorization()
        reservation = reserve_provider_budget(
            self.database_url,
            BudgetReservationRequest(
                operation_id=str(operation["operation_id"]),
                external_effect_id=str(effect["external_effect_id"]),
                project_id=str(operation["project_id"]),
                stable_idempotency_key=f"budget:{stable_key}",
                provider=self.adapter.provider,
                currency=(
                    "UNKNOWN"
                    if cost_accounting_basis == "ACCOUNT_ENTITLEMENT"
                    else "USD"
                ),
                estimated_amount=(
                    None
                    if cost_accounting_basis == "ACCOUNT_ENTITLEMENT"
                    else str(
                        provider_token_contract.get("estimated_cost_amount")
                        or self.max_cost_per_call
                    )
                ),
                estimated_tokens=provider_budget_tokens,
                chapter=int(command["chapter_number"]),
                caps=self.budget_caps,
                call_caps=dict(getattr(self, "provider_call_caps", {}) or {}),
                token_caps=dict(getattr(self, "provider_token_caps", {}) or {}),
                budget_scope_id=str(
                    provider_token_contract.get("budget_scope_id") or ""
                ),
                expected_budget_scope_revision=(
                    int(provider_token_contract["budget_scope_revision"])
                    if provider_token_contract.get("budget_scope_revision") is not None
                    else None
                ),
                accounting_basis=cost_accounting_basis,
                cost_authorization_ref=account_authorization_ref,
            ),
        )
        payload["external_effect_id"] = str(effect["external_effect_id"])
        binding = self.capability_binder.bind(
            stable_idempotency_key=stable_key,
            capability=f"model.{stage}",
            request_payload=payload,
            external_effect_id=str(effect["external_effect_id"]),
        )
        contracts = self._contracts(str(operation["project_id"]), binding, stage)
        return PreparedAgentExecution(
            execution_port=_ExternalEffectPepAgentPort(
                database_url=self.database_url,
                adapter=effect_adapter,
                worker_id=worker_id,
                lease_seconds=self.lease_seconds,
                effect_context=effect_context,
                external_effect_id=str(effect["external_effect_id"]),
                stable_key=stable_key,
                reservation_id=str(reservation["reservation_id"]),
                binding=binding,
                recovery_fencing_token=recovery_fencing_token,
                operation=operation,
                inputs=inputs,
                evidence_writer=self.evidence_writer,
                accounting_basis=cost_accounting_basis,
            ),
            **contracts,
        )

    def _execution_identity(
        self,
        *,
        operation: dict[str, Any],
        attempt_id: str,
        stable_key: str,
        execution_fencing_token: int,
    ) -> tuple[int, str]:
        runtime = get_database_runtime(self.database_url)
        with runtime.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT request_payload
                    FROM authority_external_effect
                    WHERE project_id=%s AND operation_id=%s
                      AND effect_type='model.invoke'
                      AND stable_idempotency_key=%s
                    """,
                    [
                        str(operation["project_id"]),
                        str(operation["operation_id"]),
                        stable_key,
                    ],
                )
                row = cursor.fetchone()
        if row is None:
            return execution_fencing_token, self.worker_id
        payload = row[0]
        metadata = (
            payload.get("_production_execution") if isinstance(payload, dict) else None
        )
        if not isinstance(metadata, dict):
            raise KernelError(
                "AGENT_EXECUTION_IDENTITY_INVALID",
                "replayed ExternalEffect has no frozen execution identity",
            )
        if str(metadata.get("attempt_id") or "") != attempt_id:
            raise KernelError(
                "AGENT_EXECUTION_IDENTITY_CONFLICT",
                "replayed ExternalEffect belongs to another Attempt",
            )
        frozen_fence = int(metadata.get("fencing_token") or 0)
        execution_worker_id = str(metadata.get("worker_id") or "")
        if (
            frozen_fence <= 0
            or frozen_fence > execution_fencing_token
            or not execution_worker_id
        ):
            raise KernelError(
                "AGENT_EXECUTION_IDENTITY_INVALID",
                "replayed ExternalEffect has invalid frozen execution identity",
            )
        return frozen_fence, execution_worker_id

    def _input_assets(
        self, *, project_id: str, asset_version_ids: tuple[str, ...]
    ) -> tuple[ChapterInputAsset, ...]:
        values: list[ChapterInputAsset] = []
        for asset_version_id in asset_version_ids:
            document = self.assets.require(
                project_id=project_id, asset_version_id=asset_version_id
            )
            values.append(
                ChapterInputAsset(
                    asset_version_id=document.asset_version_id,
                    asset_type=document.asset_type,
                    content_hash=document.content_hash,
                    content=dict(document.content),
                    blobs=(),
                )
            )
        return tuple(values)

    def _contracts(
        self, project_id: str, binding: ChapterExecutionBinding, stage: str
    ) -> dict[str, str]:
        refs = {
            "route_snapshot_ref": binding.route_snapshot.route_snapshot_id,
            "input_manifest_ref": binding.input_manifest.manifest_id,
            "prompt_bundle_ref": binding.route_snapshot.prompt_bundle_ref,
            "skill_bundle_ref": binding.route_snapshot.skill_bundle_ref,
            "tool_permission_snapshot_ref": (
                "production_execution/tool_permissions/"
                + binding.route_snapshot.route_snapshot_id.rsplit("/", 1)[-1]
            ),
            "context_policy_ref": (
                "context-policy:"
                + chapter_stage_capability(stage).value.replace(".", "-")
                + ":v1"
            ),
        }
        result: dict[str, str] = {}
        for name, logical_ref in refs.items():
            document = self.assets.require(
                project_id=project_id, logical_ref=logical_ref
            )
            result[name] = logical_ref
            result[name.removesuffix("_ref") + "_hash"] = document.content_hash
        return result


@dataclass(slots=True)
class _ExternalEffectPepAgentPort:
    database_url: str
    adapter: Any
    worker_id: str
    lease_seconds: int
    effect_context: EffectCommandContext
    external_effect_id: str
    stable_key: str
    reservation_id: str
    binding: ChapterExecutionBinding
    recovery_fencing_token: int
    operation: dict[str, Any]
    inputs: tuple[ChapterInputAsset, ...]
    evidence_writer: ExternalEffectChapterModelPort
    accounting_basis: str = "PRICED"

    external_effect_backed = True
    production_execution_gateway_backed = True

    def execute(self, command: DomainExecutionCommand) -> DomainExecutionCandidate:
        if command.capability != self.binding.request.capability:
            raise KernelError(
                "AGENT_PEP_CAPABILITY_DRIFT",
                "Domain execution capability differs from frozen PEP request",
            )
        result = self.evidence_writer.completed_effect_result(
            self.external_effect_id,
            self.effect_context.project_id,
        )
        recovered_completed_effect = result is not None
        if result is None:
            try:
                dispatched = dispatch_external_effect(
                    self.database_url,
                    self.effect_context,
                    effect_id=self.external_effect_id,
                    worker_id=self.worker_id,
                    lease_seconds=self.lease_seconds,
                    adapter=self.adapter,
                )
            except KernelError:
                resolve_provider_budget_failure(
                    self.database_url,
                    reservation_id=self.reservation_id,
                    project_id=self.effect_context.project_id,
                )
                raise
            if dispatched["outcome"] != "success":
                resolve_provider_budget_failure(
                    self.database_url,
                    reservation_id=self.reservation_id,
                    project_id=self.effect_context.project_id,
                )
                raise KernelError(
                    "AGENT_EXTERNAL_EFFECT_NOT_FINAL",
                    "Agent PEP ExternalEffect did not complete successfully",
                )
            result = ModelProviderResult.from_evidence(
                dict(dispatched["provider_evidence"])
            )
        settle_provider_budget(
            self.database_url,
            reservation_id=self.reservation_id,
            project_id=self.effect_context.project_id,
            actual_amount=(
                None
                if self.accounting_basis == "ACCOUNT_ENTITLEMENT"
                else result.cost_amount
            ),
            actual_tokens=result.total_tokens,
            evidence={
                "provider_id": result.provider_id,
                "model_id": result.model_id,
                "real_model_call": result.real_model_call,
                "fixture": not result.real_model_call,
                "recovered_completed_effect": recovered_completed_effect,
                "accounting_basis": self.accounting_basis,
                "cost_status": (
                    "UNKNOWN"
                    if self.accounting_basis == "ACCOUNT_ENTITLEMENT"
                    else "KNOWN"
                ),
            },
        )
        stage = self.binding.request.stage
        request = ChapterHandlerRequest(
            operation_id=self.binding.request.operation_id,
            project_id=self.binding.request.project_id,
            workspace_id=self.binding.request.workspace_id,
            trace_id=self.binding.request.trace_id,
            correlation_id=self.binding.request.correlation_id,
            command=dict(self.operation["command_payload"]),
            inputs=self.inputs,
            attempt_id=self.binding.request.attempt_id,
            fencing_token=self.binding.request.fencing_token,
            worker_id=self.worker_id,
        )
        self.evidence_writer.record_result_evidence(request, stage=stage, result=result)
        production = dict(result.execution_evidence or {})
        execution_result = dict(production.get("execution_result") or {})
        execution_handle = dict(production.get("execution_handle") or {})
        required = {
            "output_manifest_ref": execution_result.get("output_manifest_ref"),
            "validation_manifest_ref": execution_result.get("validation_report_ref"),
            "usage_receipt_ref": execution_result.get("usage_receipt_ref"),
            "cost_receipt_ref": execution_result.get("cost_receipt_ref"),
        }
        if any(not value for value in required.values()):
            raise KernelError(
                "AGENT_PEP_EVIDENCE_INCOMPLETE",
                "successful Agent PEP result lacks required manifests",
            )
        command_payload = dict(self.operation["command_payload"])
        turn_id = str(
            uuid5(
                NAMESPACE_URL,
                f"novel-forge:agent-turn:{self.binding.request.attempt_id}",
            )
        )
        envelope = {
            "output_id": str(
                uuid5(
                    NAMESPACE_URL,
                    f"novel-forge:agent-output:{self.binding.request.attempt_id}",
                )
            ),
            "session_id": str(command_payload["collaboration_session_id"]),
            "turn_id": turn_id,
            "agent_id": str(command_payload["agent_id"]),
            "message_type": str(command_payload["message_type"]),
            "structured_payload": {
                "candidate_version_id": str(
                    uuid5(
                        NAMESPACE_URL,
                        "novel-forge:agent-candidate:"
                        + self.binding.request.attempt_id,
                    )
                ),
                "candidate_type": f"{stage}_candidate",
                "candidate_kind": stage,
                "content_ref": str(required["output_manifest_ref"]),
                "structured_diff": {
                    "op": "candidate.create",
                    "path": f"/{stage}",
                    "value_ref": str(required["output_manifest_ref"]),
                },
                "domain_candidate": result.output,
                "commit_status": "NOT_COMMITTED",
                "change_reason_refs": [str(required["validation_manifest_ref"])],
            },
            "natural_language_explanation": (
                "PEP produced a structured candidate for Domain Authority validation."
            ),
            "source_asset_versions": list(command_payload["input_asset_versions"]),
            "evidence_refs": [
                str(required["output_manifest_ref"]),
                str(required["validation_manifest_ref"]),
            ],
            "assumptions": [],
            "confidence": 0.5,
            "affected_assets": [],
            "proposed_changes": [],
            "preserved_constraints": list(command_payload["must_preserve"]),
            "accessed_knowledge": [],
            "unresolved_questions": [],
            "risk_level": str(command_payload["risk_level"]),
            "requested_next_action": "DOMAIN_AUTHORITY_VALIDATE",
        }
        return DomainExecutionCandidate(
            candidate_kind=CandidateKind.AGENT_RESULT,
            raw_output=envelope,
            evidence=DomainExecutionEvidence(
                execution_id=self.binding.request.execution_id,
                operation_id=self.binding.request.operation_id,
                attempt_id=self.binding.request.attempt_id,
                fencing_token=self.recovery_fencing_token,
                capability=self.binding.request.capability,
                backend_id=str(execution_handle.get("backend_id") or ""),
                route_snapshot_id=self.binding.request.route_snapshot_id,
                input_manifest_ref=self.binding.request.input_manifest_ref,
                output_manifest_ref=str(required["output_manifest_ref"]),
                validation_manifest_ref=str(required["validation_manifest_ref"]),
                usage_receipt_ref=str(required["usage_receipt_ref"]),
                cost_receipt_ref=str(required["cost_receipt_ref"]),
                fixture_protocol_only=not result.real_model_call,
                real_model_call=result.real_model_call,
                production_verified=False,
                provider_id=result.provider_id,
                model_id=result.model_id,
                provider_request_id=str(
                    execution_handle.get("provider_request_id") or ""
                ),
                external_receipt_ref=str(
                    execution_result.get("external_receipt_ref") or ""
                ),
            ),
        )


def _stage_payload(stage: str, inputs: tuple[ChapterInputAsset, ...]) -> dict[str, Any]:
    by_type = {item.asset_type: dict(item.content) for item in inputs}
    if stage == "draft":
        return {
            "plan": by_type.get("chapter_plan", {}),
            "context": by_type.get("context_bundle", {}),
            "style": by_type.get("style_profile", {}),
        }
    if stage in {"review", "rereview"}:
        return {
            "draft": by_type.get("draft_chapter") or by_type.get("draft_version") or {},
            "review": by_type.get("review_report", {}),
            "revision": by_type.get("draft_version", {}),
        }
    if stage == "revision":
        return {
            "draft": by_type.get("draft_chapter", {}),
            "review": by_type.get("review_report", {}),
        }
    if stage == "canon_extraction":
        return {
            "revision": by_type.get("draft_version", {}),
            "context": by_type.get("context_bundle", {}),
        }
    if stage.startswith("quality_"):
        return {
            "revision": by_type.get("draft_version", {}),
            "quality_context": by_type.get("context_bundle", {}),
            "dimensions": [stage.removeprefix("quality_")],
        }
    return {
        "chapter": by_type.get("draft_version", {}),
        "book_id": "",
        "assets": {key: value for key, value in by_type.items()},
    }


__all__ = ["ChapterGatewayAgentExecutionPreparer"]
