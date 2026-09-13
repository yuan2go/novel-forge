from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
import hashlib
import json
from typing import Any

from novel_forge.modules.authority_handler_runtime import AuthorityHandlerRequest
from novel_forge.modules.capability_pack_authority.runtime import (
    CapabilityPackResolutionRequest,
)
from novel_forge.modules.chapter_authority.contracts import (
    ChapterHandlerRequest,
    ChapterInputAsset,
)
from novel_forge.modules.chapter_authority.execution_gateway import (
    PostgresChapterExecutionContractBinder,
)
from novel_forge.modules.chapter_authority.model_effects import (
    ExternalEffectChapterModelPort,
    model_call_log_ref,
)
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution import (
    ArtifactPointer,
    ExecutionRuntimeClass,
)
from novel_forge.storage.authority_asset_store import (
    AuthorityAssetQuery,
    AuthorityAssetWriter,
)
from .evaluation_runtime import NarrativeProviderEvaluation
from .replacement_gate import assert_narrative_replacement_execution_gate
from .qualification import (
    NarrativeQualificationProfile,
    qualification_provider_schema,
    validate_narrative_qualification,
)


NARRATIVE_EVALUATION_STAGE = "narrative_semantic_evaluation"
NARRATIVE_EVALUATION_WORKFLOW_REF = "story_design_semantic_evaluation@1.0.0"

_FOUNDATION_DEPENDENCY_ASSET_TYPES = {
    "CREATIVE_FOUNDATION": "creative_foundation",
    "THEME_CONTRACT": "theme_contract",
    "ENDING_INTENT": "ending_intent",
    "READER_PROMISE": "reader_promise",
    "WORLD_BIBLE": "world_bible",
    "CHARACTER_CAST": "character_cast",
}


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class PostgresNarrativeEvaluationExecutionContractBinder(
    PostgresChapterExecutionContractBinder
):

    workflow_definition_ref = NARRATIVE_EVALUATION_WORKFLOW_REF
    execution_binding_domain = "narrative_evaluation"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("workflow_definition_ref", self.workflow_definition_ref)
        super().__init__(*args, **kwargs)
        self.evaluation_query = AuthorityAssetQuery(self.database_url)
        self.evaluation_writer = AuthorityAssetWriter(self.database_url)

    def assert_before_provider_send(
        self,
        *,
        operation_id: str,
        project_id: str,
    ) -> dict[str, Any]:

        return assert_narrative_replacement_execution_gate(
            self.database_url,
            operation_id=operation_id,
            project_id=project_id,
        )

    def freeze_before_external_effect(
        self,
        *,
        capability: str,
        request_payload: Mapping[str, Any],
        snapshot_fencing_token: int,
        snapshot_worker_id: str,
    ):
        if (
            capability != f"model.{NARRATIVE_EVALUATION_STAGE}"
            or str(request_payload.get("stage") or "") != NARRATIVE_EVALUATION_STAGE
        ):
            raise KernelError(
                "NARRATIVE_EVALUATION_CAPABILITY_INVALID",
                "Narrative evaluator binder accepts only semantic evaluation",
            )
        metadata = request_payload.get("_production_execution")
        if not isinstance(metadata, dict):
            raise KernelError(
                "NARRATIVE_EVALUATION_EXECUTION_METADATA_INVALID",
                "Narrative evaluation execution metadata is missing",
            )
        self.assert_before_provider_send(
            operation_id=str(metadata.get("operation_id") or ""),
            project_id=str(metadata.get("project_id") or ""),
        )
        artifacts = metadata.get("input_artifacts")
        if not isinstance(artifacts, list) or len(artifacts) != 1:
            raise KernelError(
                "NARRATIVE_EVALUATION_INPUT_INVALID",
                "Narrative evaluation requires exactly one immutable candidate",
            )
        target_id = str(metadata.get("target_asset_version_id") or "")
        target_hash = str(metadata.get("target_content_hash") or "")
        pointer = artifacts[0]
        if (
            not isinstance(pointer, Mapping)
            or str(pointer.get("asset_version_id") or "") != target_id
            or str(pointer.get("content_hash") or "") != target_hash
        ):
            raise KernelError(
                "NARRATIVE_EVALUATION_TARGET_DRIFT",
                "Narrative evaluator input differs from its frozen target lineage",
            )
        context = self._evaluation_context_bundle(
            operation_id=str(metadata.get("operation_id") or ""),
            attempt_id=str(metadata.get("attempt_id") or ""),
            project_id=str(metadata.get("project_id") or ""),
            trace_id=str(request_payload.get("trace_id") or ""),
            correlation_id=str(request_payload.get("correlation_id") or ""),
            pointer=pointer,
            metadata=metadata,
        )
        artifacts[:] = [
            ArtifactPointer(
                artifact_ref=f"asset-version:{context.asset_version_id}",
                asset_version_id=context.asset_version_id,
                artifact_type="context_bundle",
                content_hash=context.content_hash,
                schema_version="novelos.narrative_evaluation_context_bundle.v1",
                source_eligibility="PRODUCTION_ELIGIBLE",
            ).to_dict()
        ]
        metadata["execution_binding_domain"] = self.execution_binding_domain
        return super().freeze_before_external_effect(
            capability=capability,
            request_payload=request_payload,
            snapshot_fencing_token=snapshot_fencing_token,
            snapshot_worker_id=snapshot_worker_id,
        )

    def _provider_output_contract(
        self,
        *,
        stage: str,
        request_payload: Mapping[str, Any],
    ) -> tuple[dict[str, Any], str]:
        if stage != NARRATIVE_EVALUATION_STAGE:
            raise KernelError(
                "NARRATIVE_EVALUATION_STAGE_INVALID",
                "Narrative evaluator cannot bind another stage",
            )
        metadata = request_payload.get("_production_execution")
        operation_name = (
            str(metadata.get("generator_operation_name") or "")
            if isinstance(metadata, Mapping)
            else ""
        )
        schema = qualification_provider_schema(operation_name)
        schema_hash = _canonical_hash(schema).removeprefix("sha256:")[:16]
        return (
            schema,
            f"schema:narrative-semantic-evaluation:{operation_name}:v1:{schema_hash}",
        )

    def _resolve_pack_snapshot(
        self,
        *,
        project_id: str,
        workspace_id: str,
        book_id: str,
        operation_id: str,
        attempt_id: str,
        execution_fencing_token: int,
        worker_id: str,
        snapshot_creation_fencing_token: int,
        snapshot_creation_worker_id: str,
        stage: str,
        graph: Mapping[str, str],
        route: Any,
    ):
        if stage != NARRATIVE_EVALUATION_STAGE:
            raise KernelError(
                "NARRATIVE_EVALUATION_STAGE_INVALID",
                "Narrative evaluator Pack cannot bind another stage",
            )
        if not self.capability_pack_id:
            return None
        try:
            return self.pack_resolver.freeze_attempt_snapshot(
                CapabilityPackResolutionRequest(
                    project_id=project_id,
                    workspace_id=workspace_id,
                    book_id=book_id,
                    workflow_definition_ref=self.workflow_definition_ref,
                    workflow_node_id=NARRATIVE_EVALUATION_STAGE,
                    environment=self.pack_environment,
                    runtime_profile=self.pack_runtime_profile,
                    release_channel=self.pack_release_channel,
                    release_sha=route.release_sha,
                    operation_definition_ref=(
                        f"{graph['definition_name']}@{graph['definition_version']}"
                    ),
                    pack_id=self.capability_pack_id,
                ),
                operation_id=operation_id,
                attempt_id=attempt_id,
                execution_fencing_token=execution_fencing_token,
                worker_id=worker_id,
                snapshot_creation_fencing_token=snapshot_creation_fencing_token,
                snapshot_creation_worker_id=snapshot_creation_worker_id,
            )
        except KernelError as exc:
            if (
                exc.code
                in {
                    "CAPABILITY_PACK_DEPLOYMENT_NOT_RESOLVED",
                    "CAPABILITY_PACK_SCOPE_NOT_FOUND",
                }
                and not self.pack_required
            ):
                return None
            raise

    def _target_scope(
        self,
        *,
        metadata: Mapping[str, Any],
        project_id: str,
        book_id: str,
        chapter: int,
    ) -> dict[str, Any]:
        del chapter
        target_id = str(metadata.get("target_asset_version_id") or "")
        target_hash = str(metadata.get("target_content_hash") or "")
        if not target_id or not target_hash:
            raise KernelError(
                "NARRATIVE_EVALUATION_TARGET_INVALID",
                "Narrative evaluation target identity is incomplete",
            )
        return {
            "scope_kind": "asset_version",
            "scope_id": target_id,
            "project_id": project_id,
            "book_id": book_id,
            "asset_version_id": target_id,
            "content_hash": target_hash,
        }

    def _resource_claims(
        self,
        *,
        metadata: Mapping[str, Any],
        chapter: int,
        stage: str,
    ) -> tuple[str, ...]:
        del chapter
        return (
            f"asset-version:{metadata.get('target_asset_version_id')}",
            f"stage:{stage}",
        )

    @staticmethod
    def _origin_chain(*, graph: Mapping[str, str], stage: str) -> tuple[str, ...]:
        del stage
        return ("story_design.semantic_evaluate", graph["definition_name"])

    def _evaluation_context_bundle(
        self,
        *,
        operation_id: str,
        attempt_id: str,
        project_id: str,
        trace_id: str,
        correlation_id: str,
        pointer: Mapping[str, Any],
        metadata: Mapping[str, Any],
    ):
        if not all((operation_id, attempt_id, project_id, trace_id, correlation_id)):
            raise KernelError(
                "NARRATIVE_EVALUATION_EXECUTION_METADATA_INVALID",
                "Narrative evaluation context identity is incomplete",
            )
        document = self.evaluation_query.require(
            project_id=project_id,
            asset_version_id=str(pointer.get("asset_version_id") or ""),
        )
        immutable_candidate = (
            document.asset_type in {"book_design", "planning_generation_candidate"}
            and document.lifecycle == "CANDIDATE"
            and document.eligibility == "INELIGIBLE"
            and document.governance == "CLEAR"
        )
        if (
            document.asset_type != str(pointer.get("artifact_type") or "")
            or document.content_hash != str(pointer.get("content_hash") or "")
            or not immutable_candidate
        ):
            raise KernelError(
                "NARRATIVE_EVALUATION_TARGET_DRIFT",
                "Narrative evaluation candidate differs from its Authority version",
            )
        dependencies = self._canonical_dependencies(
            document, book_id=str(metadata.get("book_id") or "")
        )
        logical_ref = (
            f"narrative_evaluation/context_bundles/{operation_id}-{attempt_id}.json"
        )
        selected = {
            "asset_version_id": document.asset_version_id,
            "asset_type": document.asset_type,
            "content_hash": document.content_hash,
            "candidate": document.content,
        }
        selected_inputs = [
            selected,
            *(
                {
                    "asset_version_id": item[1].asset_version_id,
                    "asset_type": item[1].asset_type,
                    "content_hash": item[1].content_hash,
                    "dependency_role": item[0],
                    "candidate": item[1].content,
                }
                for item in dependencies
            ),
        ]
        content = {
            "schema_version": "novelos.narrative_evaluation_context_bundle.v1",
            "project_id": project_id,
            "operation_id": operation_id,
            "attempt_id": attempt_id,
            "source_isolation": (
                "EXACT_CANDIDATE_AND_CANONICAL_DEPENDENCIES"
                if dependencies
                else "EXACT_CANDIDATE_ONLY"
            ),
            "dependency_resolution": (
                "EVALUATOR_RESOLVED_FROM_CANDIDATE_LINEAGE"
                if dependencies
                else "NOT_APPLICABLE"
            ),
            "generation_operation_id": str(
                metadata.get("generation_operation_id") or ""
            ),
            "generator_operation_name": str(
                metadata.get("generator_operation_name") or ""
            ),
            "selected_inputs": selected_inputs,
            "dependency_lineage": [
                {
                    "role": role,
                    "asset_version_id": source.asset_version_id,
                    "content_hash": source.content_hash,
                    "qualification_evidence_asset_version_id": (
                        qualification.asset_version_id
                    ),
                    "qualification_hash": qualification.content_hash,
                }
                for role, source, qualification in dependencies
            ],
        }
        try:
            existing = self.evaluation_query.require(
                project_id=project_id,
                logical_ref=logical_ref,
            )
            if existing.content != content:
                raise KernelError(
                    "NARRATIVE_EVALUATION_CONTEXT_CONFLICT",
                    "Narrative evaluation context changed inside one Attempt",
                )
            return existing
        except KernelError as exc:
            if exc.code != "AUTHORITY_ASSET_NOT_FOUND":
                raise
        return self.evaluation_writer.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=operation_id,
                project_id=project_id,
                asset_id=f"narrative-evaluation-context:{attempt_id}",
                asset_type="context_bundle",
                schema_version="novelos.narrative_evaluation_context_bundle.v1",
                logical_ref=logical_ref,
                category="narrative_evaluation_context",
                output_key="narrative_evaluation.context_bundle",
                role="context_bundle",
                content=content,
                qualification_policy="narrative-evaluation-context-source-isolation-v1",
                trace_id=trace_id,
                correlation_id=correlation_id,
                reference_asset_ids=(
                    document.asset_id,
                    *(
                        asset_id
                        for _, source, qualification in dependencies
                        for asset_id in (source.asset_id, qualification.asset_id)
                    ),
                ),
            )
        )

    def _canonical_dependencies(
        self, document: Any, *, book_id: str = ""
    ) -> tuple[tuple[str, Any, Any], ...]:
        """SECURITY: Resolve only immutable dependencies named by a BookDesign v5 candidate.

        The evaluator, rather than its caller, resolves these versions.  This keeps
        generator prompts and mutable projections out of the evaluation while
        making the reference-only BookDesign contract semantically reviewable.
        Qualification assets are verified for lineage but are intentionally not
        exposed as selected inputs, so a prior verdict cannot prime the evaluator.
        """
        if (
            document.asset_type != "book_design"
            or document.content.get("schema_version") != "book-design.v5"
        ):
            return ()
        foundation = document.content.get("foundation_set")
        if not isinstance(foundation, Mapping):
            raise KernelError(
                "NARRATIVE_EVALUATION_DEPENDENCY_INVALID",
                "BookDesign v5 has no exact Foundation Set",
            )
        bindings = foundation.get("bindings")
        if (
            set(foundation) != {"schema_version", "bindings", "set_digest"}
            or foundation.get("schema_version") != "qualified-foundation-set.v1"
            or not isinstance(bindings, list)
            or len(bindings) != len(_FOUNDATION_DEPENDENCY_ASSET_TYPES)
            or foundation.get("set_digest") != _canonical_hash(bindings)
        ):
            raise KernelError(
                "NARRATIVE_EVALUATION_DEPENDENCY_INVALID",
                "BookDesign v5 Foundation Set is incomplete or digest-drifted",
            )
        by_role: dict[str, Mapping[str, Any]] = {}
        for item in bindings:
            if not isinstance(item, Mapping):
                raise KernelError(
                    "NARRATIVE_EVALUATION_DEPENDENCY_INVALID",
                    "BookDesign v5 Foundation binding is not an object",
                )
            role = str(item.get("role") or "")
            if role not in _FOUNDATION_DEPENDENCY_ASSET_TYPES or role in by_role:
                raise KernelError(
                    "NARRATIVE_EVALUATION_DEPENDENCY_INVALID",
                    "BookDesign v5 Foundation roles are missing or duplicated",
                )
            by_role[role] = item
        if set(by_role) != set(_FOUNDATION_DEPENDENCY_ASSET_TYPES):
            raise KernelError(
                "NARRATIVE_EVALUATION_DEPENDENCY_INVALID",
                "BookDesign v5 does not bind all required Foundation roles",
            )

        resolved: list[tuple[str, Any, Any]] = []
        from .domain import GENERATOR_DESIGN_SCOPE

        for role, expected_asset_type in _FOUNDATION_DEPENDENCY_ASSET_TYPES.items():
            binding = by_role[role]
            asset_version_id = str(binding.get("asset_version_id") or "")
            content_hash = str(binding.get("content_hash") or "")
            qualification_id = str(
                binding.get("qualification_evidence_asset_version_id") or ""
            )
            qualification_hash = str(binding.get("qualification_hash") or "")
            source = self.evaluation_query.require(
                project_id=document.project_id,
                asset_version_id=asset_version_id,
            )
            qualification = self.evaluation_query.require(
                project_id=document.project_id,
                asset_version_id=qualification_id,
            )
            qualification_content = qualification.content
            source_kind_matches = source.asset_type == expected_asset_type
            if source.asset_type == "planning_generation_candidate":
                generator = source.content.get("generator_operation_name")
                scope = (
                    GENERATOR_DESIGN_SCOPE.get(generator)
                    if isinstance(generator, str)
                    else None
                )
                source_kind_matches = (
                    scope is not None
                    and scope.value == role
                    and bool(book_id)
                    and source.content.get("book_id") == book_id
                    and source.content.get("project_id") == document.project_id
                    and source.content.get("type") == "PlanningGenerationCandidate"
                    and source.content.get("schema_version") == "story_design.authority.v1"
                    and source.content.get("planning_scope") == "NOT_APPLICABLE"
                    and isinstance(source.content.get("candidate_payload"), Mapping)
                )
            valid = (
                source_kind_matches
                and source.content_hash == content_hash
                and source.lifecycle == "ACTIVE"
                and source.eligibility == "ELIGIBLE"
                and source.governance == "CLEAR"
                and qualification.asset_type == "narrative_design_evaluation"
                and qualification.content_hash == qualification_hash
                and qualification.lifecycle == "ACTIVE"
                and qualification.eligibility == "ELIGIBLE"
                and qualification.governance == "CLEAR"
                and qualification_content.get("candidate_asset_version_id")
                == source.asset_version_id
                and qualification_content.get("candidate_content_hash")
                == source.content_hash
                and isinstance(qualification_content.get("qualification"), Mapping)
                and qualification_content["qualification"].get("status") == "PASS"
            )
            if not valid:
                raise KernelError(
                    "NARRATIVE_EVALUATION_DEPENDENCY_DRIFT",
                    f"{role} no longer resolves to its exact qualified Authority versions",
                )
            resolved.append((role, source, qualification))
        return tuple(resolved)


class GatewayNarrativeSemanticEvaluationExecutionPort:

    production_execution_gateway_backed = True
    external_effect_backed = True

    def __init__(
        self,
        database_url: str,
        *,
        model_port: ExternalEffectChapterModelPort,
    ) -> None:
        if not database_url or not getattr(model_port, "external_effect_backed", False):
            raise ValueError(
                "Narrative evaluator requires an ExternalEffect model port"
            )
        self.database_url = database_url
        self.model_port = model_port
        self.query = AuthorityAssetQuery(database_url)
        route = getattr(model_port.adapter, "routes", {}).get(
            NARRATIVE_EVALUATION_STAGE
        )
        self.real_provider_execution = bool(
            route is not None and route.real_provider_validation_eligible
        )

    def evaluate(
        self,
        request: AuthorityHandlerRequest,
        *,
        candidate: Any,
        generator_operation_name: str,
        profiles: tuple[NarrativeQualificationProfile, ...],
    ) -> NarrativeProviderEvaluation:
        target = {
            "candidate_asset_version_id": candidate.asset_version_id,
            "candidate_content_hash": candidate.content_hash,
            "generation_operation_id": str(
                request.command["payload"].get("generation_operation_id") or ""
            ),
            "generator_operation_name": generator_operation_name,
        }
        profile_payload = [
            {
                **asdict(profile),
                "layer": profile.layer.value,
                "profile_hash": profile.profile_hash,
            }
            for profile in profiles
        ]
        chapter_request = ChapterHandlerRequest(
            operation_id=request.operation_id,
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            trace_id=request.trace_id,
            correlation_id=request.correlation_id,
            command={
                "payload": {
                    "book_id": str(request.command["payload"].get("book_id") or ""),
                    "target_asset_version_id": candidate.asset_version_id,
                    "target_content_hash": candidate.content_hash,
                    "generation_operation_id": target["generation_operation_id"],
                    "generator_operation_name": generator_operation_name,
                    "context_token_budget": 8_000,
                }
            },
            inputs=(
                ChapterInputAsset(
                    asset_version_id=candidate.asset_version_id,
                    asset_type=candidate.asset_type,
                    content_hash=candidate.content_hash,
                    content=dict(candidate.content),
                ),
            ),
            attempt_id=request.attempt_id,
            fencing_token=request.fencing_token,
            worker_id=request.worker_id,
        )
        binder = self.model_port.capability_binder
        binder_assertion = getattr(binder, "assert_before_provider_send", None)

        def assert_before_provider_send() -> None:
            if callable(binder_assertion):
                binder_assertion(
                    operation_id=request.operation_id,
                    project_id=request.project_id,
                )
                return
            assert_narrative_replacement_execution_gate(
                self.database_url,
                operation_id=request.operation_id,
                project_id=request.project_id,
            )

        result = self.model_port.invoke(
            chapter_request,
            stage=NARRATIVE_EVALUATION_STAGE,
            payload={
                "evaluation_target": target,
                "candidate": dict(candidate.content),
                "qualification_profiles": profile_payload,
            },
            pre_send_assertion=assert_before_provider_send,
        )
        if not result.real_model_call:
            raise KernelError(
                "NARRATIVE_EVALUATION_REAL_PROVIDER_REQUIRED",
                "production semantic evaluation rejected fixture Provider evidence",
            )
        qualification = validate_narrative_qualification(
            generator_operation_name=generator_operation_name,
            value=result.output,
            require_pass=False,
        )
        del qualification
        execution_request = (
            result.execution_evidence.get("execution_request")
            if isinstance(result.execution_evidence, Mapping)
            else None
        )
        external_effect_id = (
            str(execution_request.get("external_effect_id") or "")
            if isinstance(execution_request, Mapping)
            else ""
        )
        if not external_effect_id:
            raise KernelError(
                "NARRATIVE_EVALUATION_PROVIDER_EVIDENCE_INVALID",
                "real-provider evaluator result has no ExternalEffect identity",
            )
        logical_ref = model_call_log_ref(
            request.operation_id,
            request.attempt_id,
            NARRATIVE_EVALUATION_STAGE,
            external_effect_id,
        )
        log = self.query.require(project_id=request.project_id, logical_ref=logical_ref)
        provider_evidence = log.content.get("provider_evidence")
        production_execution = (
            provider_evidence.get("production_execution")
            if isinstance(provider_evidence, Mapping)
            else None
        )
        route_snapshot = (
            production_execution.get("route_snapshot")
            if isinstance(production_execution, Mapping)
            else None
        )
        execution_handle = (
            production_execution.get("execution_handle")
            if isinstance(production_execution, Mapping)
            else None
        )
        valid = (
            log.asset_type == "model_call_log"
            and str(log.content.get("operation_id") or "") == request.operation_id
            and str(log.content.get("attempt_id") or "") == request.attempt_id
            and str(log.content.get("stage") or "") == NARRATIVE_EVALUATION_STAGE
            and log.content.get("target_lineage")
            == {
                "target_asset_version_id": candidate.asset_version_id,
                "target_content_hash": candidate.content_hash,
                "generation_operation_id": target["generation_operation_id"],
                "generator_operation_name": generator_operation_name,
            }
            and isinstance(provider_evidence, Mapping)
            and provider_evidence.get("real_model_call") is True
            and provider_evidence.get("result") == result.output
            and isinstance(route_snapshot, Mapping)
            and str(route_snapshot.get("route_snapshot_id") or "")
            and isinstance(execution_handle, Mapping)
            and str(execution_handle.get("transport") or "")
            in {
                ExecutionRuntimeClass.REMOTE_PROVIDER_API.value,
                ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE.value,
            }
        )
        if not valid:
            raise KernelError(
                "NARRATIVE_EVALUATION_PROVIDER_EVIDENCE_INVALID",
                "ModelCallLog is not the exact real-provider evaluator receipt",
            )
        return NarrativeProviderEvaluation(
            evaluation=dict(result.output),
            model_call_log_asset_version_id=log.asset_version_id,
            model_call_log_content_hash=log.content_hash,
            provider_evidence_hash=_canonical_hash(dict(provider_evidence)),
            provider_result_hash=_canonical_hash(dict(result.output)),
            provider_id=result.provider_id,
            model_id=result.model_id,
            route_snapshot_id=str(route_snapshot["route_snapshot_id"]),
            prompt_version=result.prompt_version,
            skill_version=result.skill_version,
            real_model_call=result.real_model_call,
        )


__all__ = [
    "GatewayNarrativeSemanticEvaluationExecutionPort",
    "NARRATIVE_EVALUATION_STAGE",
    "NARRATIVE_EVALUATION_WORKFLOW_REF",
    "PostgresNarrativeEvaluationExecutionContractBinder",
]
