"""SECURITY: model reference Provider inputs are rebuilt from frozen native assets."""

from __future__ import annotations

from typing import Any, Mapping
from dataclasses import dataclass
import json
from uuid import uuid4

from novel_forge.modules.authority_handler_runtime import AuthorityHandlerOutput, AuthorityHandlerRegistration
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command_in_uow
from novel_forge.modules.command_kernel.runtime import OperationTransitionCommand, transition_operation_in_uow
from novel_forge.modules.command_kernel.operation_graph import GraphCommandContext, start_saga, register_saga_step
from novel_forge.modules.content_authority.scheduler import ContentAuthorityScheduler
from novel_forge.modules.authority_handler_runtime.routing_bootstrap import freeze_bootstrap_authorization
from novel_forge.storage.authority_repositories import definition_hash

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.routing_bootstrap import (
    authorization_hash,
    validate_model_reference_creation_binding,
)
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery, AuthorityAssetWriter
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.capability_pack_authority.runtime import CapabilityPackResolutionRequest
from novel_forge.modules.chapter_authority.execution_gateway import PostgresChapterExecutionContractBinder
from novel_forge.modules.chapter_authority.context_compression_provider import CONTEXT_MODEL_STAGES
from novel_forge.modules.command_kernel.routing_bootstrap import load_bootstrap_authorization
from novel_forge.modules.chapter_authority.contracts import ChapterHandlerRequest, ChapterInputAsset
from novel_forge.modules.chapter_authority.model_effects import ExternalEffectChapterModelPort, model_call_log_ref
from novel_forge.modules.authority_handler_runtime import AuthorityHandlerRequest


MODEL_REFERENCE_EVALUATE = "quality.model_reference.evaluate"
MODEL_REFERENCE_ADJUDICATE = "quality.model_reference.adjudicate"
MODEL_REFERENCE_EXECUTION_VERSION = "1.0.0"
MODEL_REFERENCE_STAGE = {
    MODEL_REFERENCE_EVALUATE: "model_reference_evaluate",
    MODEL_REFERENCE_ADJUDICATE: "model_reference_adjudicate",
}
MODEL_REFERENCE_HANDLER = "novel_forge.chapter_quality.model_reference_create"
MODEL_REFERENCE_OUTPUT = "model_reference_provider_result"
MODEL_REFERENCE_OUTPUT_KEY = "quality.model_reference.provider_result"
MODEL_REFERENCE_TOPIC = "quality.model_reference.provider_result.materialized"


def model_reference_creation_definitions(*, application_build_id: str,
                                         commit_sha: str) -> tuple[dict[str, Any], ...]:
    """INVARIANT: diagnostic creation has distinct formal definitions and no qualification claim."""
    schema = {"type": "object", "required": ["project_id", "input_asset_version_ids", "payload"],
              "properties": {"project_id": {"type": "string"},
                             "input_asset_version_ids": {"type": "array", "minItems": 2},
                             "payload": {"type": "object"}}, "additionalProperties": False}
    result = []
    for name, stage in MODEL_REFERENCE_STAGE.items():
        result.append({"name": name, "definition_version": MODEL_REFERENCE_EXECUTION_VERSION,
            "family": "chapter_quality_authority", "enabled": True,
            "definition_status": "implemented", "command_schema_version": "model-reference-creation-command.v1",
            "result_schema_version": "model-reference-provider-result.v1",
            "command_schema": schema, "result_schema": {"type": "object"},
            "input_contract": schema, "output_contract": {"asset_type": MODEL_REFERENCE_OUTPUT,
                "output_key": MODEL_REFERENCE_OUTPUT_KEY},
            "handler_key": MODEL_REFERENCE_HANDLER, "handler_contract_version": "model-reference-creation-handler.v1",
            "application_build_id": application_build_id, "commit_sha": commit_sha,
            "execution_mode": "worker", "permissions": ["chapter.authority.execute"],
            "approval_policy": {"required": False},
            "idempotency_scope": "book:model-reference-creation",
            "concurrency_key_template": "book:{book_id}:model-reference:{logical_key}",
            "retry_policy": {"max_attempts": 2, "dead_letter_on_exhausted": True},
            "timeout_policy": {"operation_timeout_seconds": 3000},
            "cancellation_policy": {"mode": "cancel_active_attempt"},
            "compensation_policy": {"supported": False, "reason": "append-only model evidence"},
            "irreversible_effect_policy": {"allowed": False},
            "external_capabilities": ["model." + stage],
            "projection_consumers": ["chapter_quality_authority"],
            "migration_owner": "chapter-quality-authority",
            "policy": {"model_reference_creation_input_allowed": True,
                "model_reference_stage": stage,
                "model_reference_diagnostic_only": True,
                "qualification_authority": "chapter_quality_authority"},
            "completion_contract": {"version": "model-reference-creation-completion.v1",
                "required_asset_selectors": [{"selector": MODEL_REFERENCE_OUTPUT,
                    "output_key": MODEL_REFERENCE_OUTPUT_KEY, "role": "diagnostic_evidence",
                    "lifecycle": "ACTIVE", "eligibility": "INELIGIBLE", "governance": "CLEAR"}],
                "required_evidence": ["trace", "audit"],
                "required_outbox_events": [MODEL_REFERENCE_TOPIC]}})
    return tuple(result)


def _invalid(message: str) -> KernelError:
    return KernelError("MODEL_REFERENCE_INPUT_INVALID", message)


def _native_asset(cursor: Any, *, project_id: str, binding: Mapping[str, str]) -> dict[str, Any]:
    if not isinstance(binding, Mapping) or set(binding) != {"asset_version_id", "content_hash"}:
        raise _invalid("input requires one exact asset version and content hash")
    cursor.execute("""SELECT asset.asset_type,version.content,version.content_hash,
        version.lifecycle,version.eligibility,version.governance,operation.definition_name,
        operation.definition_version,operation.status,operation.operation_id
        FROM authority_asset_version version JOIN authority_asset asset USING(asset_id)
        JOIN authority_operation_output_asset output ON output.asset_version_id=version.asset_version_id
          AND output.content_hash=version.content_hash
        JOIN authority_operation operation ON operation.operation_id=output.operation_id
          AND operation.project_id=asset.project_id
        WHERE asset.project_id=%s AND version.asset_version_id=%s""",
        [project_id, binding["asset_version_id"]])
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise _invalid("input must have exactly one native Authority output")
    kind, content, digest, lifecycle, eligibility, governance, definition, version, status, operation_id = rows[0]
    if (digest != binding["content_hash"] or digest != authorization_hash(content)
        or governance != "CLEAR"):
        raise _invalid("input content or governance differs from frozen version")
    return {"asset_type": kind, "content": content, "binding": dict(binding),
            "lifecycle": lifecycle, "eligibility": eligibility,
            "definition_name": definition, "definition_version": version,
            "operation_status": status, "operation_id": operation_id}


def _subject_projection(cursor: Any, *, project_id: str, binding: Mapping[str, str],
                        scope: Mapping[str, Any]) -> dict[str, Any]:
    from .reference_subject import require_reference_subject

    native = require_reference_subject(cursor, project_id=project_id, binding=binding,
        allowed_types=frozenset({"chapter_provider_sample", "world_provider_sample", "planning_generation_candidate"}))
    kind = native["asset_type"]
    source = native["content"]
    cursor.execute("""SELECT command_payload->'payload' FROM authority_operation
        WHERE project_id=%s AND operation_id=%s""",
        [project_id, native["generation_operation_id"]])
    origin = cursor.fetchone()
    if not origin or not isinstance(origin[0], Mapping):
        raise _invalid("subject has no frozen generation operation")
    command = origin[0]
    if kind == "planning_generation_candidate":
        from novel_forge.modules.story_planning_runtime.domain import GENERATOR_SCOPE

        planning_scope = GENERATOR_SCOPE.get(command.get("generator_operation_name"))
        planning_scope = getattr(planning_scope, "value", None)
    else:
        planning_scope = None
    if scope["scope_type"] == "BOOK":
        if (kind != "planning_generation_candidate" or planning_scope != "BOOK"
            or command.get("book_id") != scope["book_id"]):
            raise _invalid("book reference scope differs from Planning subject")
    elif kind == "planning_generation_candidate":
        realization = command.get("narrative_realization") or {}
        if (planning_scope != "CHAPTER"
            or realization.get("chapter_number") != scope["chapter_start"]):
            raise _invalid("chapter reference scope differs from Planning realization")
    elif kind == "world_provider_sample":
        source_operation_id = (command.get("world_sampling") or {}).get("source_operation_id")
        cursor.execute("""SELECT command_payload->'payload' FROM authority_operation
            WHERE project_id=%s AND operation_id=%s AND definition_name='story_planning.generate'""",
            [project_id, source_operation_id])
        source_row = cursor.fetchone()
        source_command = source_row[0] if source_row else {}
        request = source_command.get("world_preparation_request") or {}
        if (command.get("generator_operation_name") not in {"world_candidates.generate", "world_candidates.actor_0", "world_candidates.actor_1", "world_candidates.actor_2"}
            or source_command.get("generator_operation_name") != "chapter_plan.generate"
            or type(request.get("accepted_through_chapter")) is not int
            or request["accepted_through_chapter"] + 1 != scope["chapter_start"]):
            raise _invalid("chapter reference scope differs from World preparation frontier")
    elif command.get("chapter") != scope["chapter_start"]:
        raise _invalid("chapter reference scope differs from generated Chapter")
    if kind in {"chapter_provider_sample", "world_provider_sample"}:
        visible = source.get("sampled_output")
    elif kind == "planning_generation_candidate":
        visible = source.get("candidate_payload")
    else:
        raise _invalid("subject type has no governed Provider projection")
    if not isinstance(visible, Mapping) or not visible:
        raise _invalid("subject has no eligible governed projection")
    return {"binding": dict(binding), "asset_type": kind, "content": dict(visible)}


def _baseline_projection(cursor: Any, *, project_id: str, binding: Mapping[str, str]) -> dict[str, Any]:
    native = _native_asset(cursor, project_id=project_id, binding=binding)
    if (native["asset_type"] != "creative_brief" or native["definition_name"] != "creative.brief.create"
        or native["lifecycle"] != "ACTIVE" or native["eligibility"] != "ELIGIBLE"
        or native["operation_status"] != "SUCCEEDED"):
        raise _invalid("author baseline requires its native accepted creative brief")
    cursor.execute("""SELECT version.asset_version_id
        FROM authority_asset_version version JOIN authority_asset asset USING(asset_id)
        JOIN authority_operation_output_asset output ON output.asset_version_id=version.asset_version_id
        JOIN authority_operation operation ON operation.operation_id=output.operation_id
        WHERE asset.project_id=%s AND asset.asset_type='creative_brief'
          AND operation.project_id=asset.project_id
          AND operation.definition_name='creative.brief.create' AND operation.status='SUCCEEDED'
          AND version.lifecycle='ACTIVE' AND version.eligibility='ELIGIBLE'
          AND version.governance='CLEAR'
        ORDER BY version.created_at DESC,version.asset_version_id DESC LIMIT 1""",
        [project_id])
    current = cursor.fetchone()
    if current is None or current[0] != binding["asset_version_id"]:
        raise _invalid("author baseline is no longer the latest governed Brief")
    brief = {key: value for key, value in native["content"].items() if key != "project_id"}
    if not brief:
        raise _invalid("author baseline has no governed brief content")
    from novel_forge.modules.creative.domain import validate_creative_brief

    validate_creative_brief(brief)
    return {"binding": dict(binding), "asset_type": "creative_brief", "content": brief}


def _evaluation_projection(cursor: Any, *, project_id: str, binding: Mapping[str, str],
                           frozen: Mapping[str, Any]) -> dict[str, Any]:
    native = _native_asset(cursor, project_id=project_id, binding=binding)
    if (native["asset_type"] != "model_reference_evaluation"
        or native["definition_name"] != "quality.model_reference_evaluation.record"
        or native["operation_status"] != "SUCCEEDED"
        or native["lifecycle"] != "ACTIVE"):
        raise _invalid("adjudication source must be a native blind evaluation")
    content = native["content"]
    for key in ("subject", "author_baseline", "policy_hash", "producer_contract_hash",
                "protocol_version", "evaluation_version", "dimension", "scope"):
        if content.get(key) != frozen[key]:
            raise _invalid("adjudication source differs from frozen subject or policy")
    if content.get("blind") is not True or not isinstance(content.get("judgment"), Mapping):
        raise _invalid("adjudication source is not a completed blind judgment")
    return {"binding": dict(binding), "judgment": dict(content["judgment"])}


def validate_model_reference_effect_inputs(cursor: Any, *, project_id: str,
                                           frozen: Mapping[str, Any],
                                           provider_input: Mapping[str, Any],
                                           operation_id: str = "", attempt_id: str = "") -> None:
    """SECURITY: peer judgments enter only adjudication and exact source versions govern every projection."""
    try:
        validate_model_reference_creation_binding(frozen)
    except (ValueError, TypeError, KeyError) as exc:
        raise _invalid("frozen model reference contract is invalid") from exc
    expected_keys = {"model_reference", "subject", "author_baseline", "context"}
    if frozen["role"] == "ADJUDICATION":
        expected_keys.add("source_evaluations")
    if not isinstance(provider_input, Mapping) or set(provider_input) != expected_keys:
        raise _invalid("Provider input contains omitted or undeclared reference fields")
    if provider_input["model_reference"] != frozen:
        raise _invalid("Provider reference binding differs from command/grant")
    if provider_input["subject"] != _subject_projection(cursor, project_id=project_id,
                                                          binding=frozen["subject"], scope=frozen["scope"]):
        raise _invalid("Provider subject differs from native sample")
    if provider_input["author_baseline"] != _baseline_projection(cursor, project_id=project_id,
                                                                    binding=frozen["author_baseline"]):
        raise _invalid("Provider baseline differs from native author brief")
    if frozen["role"] == "ADJUDICATION":
        expected = [_evaluation_projection(cursor, project_id=project_id, binding=item, frozen=frozen)
                    for item in frozen["source_evaluations"]]
        if provider_input["source_evaluations"] != expected:
            raise _invalid("adjudicator did not receive the exact two blind reports")
        records = [_native_asset(cursor, project_id=project_id, binding=item)["content"]
            for item in frozen["source_evaluations"]]
        for key in ("session_id", "external_effect_id", "operation_id"):
            values = [str(item.get(key) or "") for item in records]
            if "" in values or len(set(values)) != 2:
                raise _invalid("adjudication sources are not independent native calls")
    context = provider_input["context"]
    if not isinstance(context, Mapping) or set(context) != {"asset_version_id", "content_hash", "projection"}:
        raise _invalid("Provider ContextBundle projection identity is incomplete")
    native_context = _native_asset(cursor, project_id=project_id,
        binding={key: context[key] for key in ("asset_version_id", "content_hash")})
    if native_context["asset_type"] != "context_bundle":
        raise _invalid("Provider Context is not a native ContextBundle")
    content = native_context["content"]
    sources = [frozen["subject"], frozen["author_baseline"],
        *(frozen.get("source_evaluations") or ())]
    if (content.get("model_reference") != frozen
        or content.get("source_bindings") != sources
        or content.get("source_isolation") != "FROZEN_MODEL_REFERENCE_ONLY"
        or (operation_id and content.get("operation_id") != operation_id)
        or (attempt_id and content.get("attempt_id") != attempt_id)
        or (operation_id and native_context["operation_id"] != operation_id)):
        raise _invalid("Provider ContextBundle ownership or source isolation differs")
    projection = native_context["content"].get("provider_context_view")
    if context["projection"] != projection:
        raise _invalid("Provider Context projection differs from frozen ContextBundle")


def prepare_model_reference_inputs(database_url: str, *, project_id: str, book_id: str,
                                   operation_id: str, attempt_id: str, stage: str,
                                   frozen: Mapping[str, Any], trace_id: str,
                                   correlation_id: str) -> tuple[dict[str, Any], Any]:
    """INVARIANT: one Attempt creates an immutable ContextBundle before its Provider Effect."""
    if stage not in MODEL_REFERENCE_STAGE.values():
        raise _invalid("unknown model reference stage")
    validate_model_reference_creation_binding(frozen)
    with AuthorityUnitOfWork(database_url) as uow:
        subject = _subject_projection(uow.cursor, project_id=project_id,
            binding=frozen["subject"], scope=frozen["scope"])
        baseline = _baseline_projection(uow.cursor, project_id=project_id,
            binding=frozen["author_baseline"])
        evaluations = ([_evaluation_projection(uow.cursor, project_id=project_id,
                        binding=item, frozen=frozen) for item in frozen["source_evaluations"]]
                       if frozen["role"] == "ADJUDICATION" else None)
    source_bindings = [frozen["subject"], frozen["author_baseline"], *(frozen.get("source_evaluations") or ())]
    projection = {"contract_version": "model-reference-context-view.v1",
        "source_isolation": "FROZEN_MODEL_REFERENCE_ONLY", "stage": stage,
        "scope": dict(frozen["scope"]), "source_bindings": source_bindings,
        "policy_hash": frozen["policy_hash"], "evaluation_version": frozen["evaluation_version"]}
    content = {"schema_version": "novelos.model_reference_context_bundle.v1",
        "project_id": project_id, "book_id": book_id, "operation_id": operation_id,
        "attempt_id": attempt_id, "model_reference": dict(frozen),
        "source_isolation": "FROZEN_MODEL_REFERENCE_ONLY",
        "source_bindings": source_bindings, "provider_context_view": projection}
    logical_ref = f"model_reference/context/{operation_id}/{attempt_id}"
    query = AuthorityAssetQuery(database_url)
    try:
        context = query.require(project_id=project_id, logical_ref=logical_ref)
        if context.content != content or context.content_hash != authorization_hash(content):
            raise _invalid("ContextBundle changed inside the same Attempt")
    except KernelError as exc:
        if exc.code != "AUTHORITY_ASSET_NOT_FOUND":
            raise
        context = AuthorityAssetWriter(database_url).materialize_output(AuthorityAssetWriteCommand(
            operation_id=operation_id, project_id=project_id,
            asset_id=f"model-reference-context:{attempt_id}", asset_type="context_bundle",
            schema_version="novelos.model_reference_context_bundle.v1",
            logical_ref=logical_ref, category="model_reference_context",
            output_key="quality.model_reference.context", role="context_bundle",
            content=content, qualification_policy="model-reference-context-isolation.v1",
            trace_id=trace_id, correlation_id=correlation_id))
    provider_input = {"model_reference": dict(frozen), "subject": subject,
                      "author_baseline": baseline,
                      "context": {"asset_version_id": context.asset_version_id,
                                  "content_hash": context.content_hash, "projection": projection}}
    if evaluations is not None:
        provider_input["source_evaluations"] = evaluations
    with AuthorityUnitOfWork(database_url) as uow:
        validate_model_reference_effect_inputs(uow.cursor, project_id=project_id,
            frozen=frozen, provider_input=provider_input)
    return provider_input, context


def model_reference_producer_identity(database_url: str, *, project_id: str,
                                      workspace_id: str, book_id: str,
                                      frozen: Mapping[str, Any],
                                      binder: "ModelReferenceExecutionContractBinder") -> dict[str, Any]:
    """INVARIANT: grant preparation uses the same approved Pack/schema/prompt contract as execution."""
    from novel_forge.modules.capability_pack_authority.runtime import materialize_registered_pack_version
    from novel_forge.modules.chapter_authority.execution_gateway import (
        _materialize_production_codex_prompt, _stage_tool_permissions,
        chapter_producer_contract_identity,
    )

    validate_model_reference_creation_binding(frozen)
    stage = "model_reference_evaluate" if frozen["role"] == "BLIND_EVALUATION" else "model_reference_adjudicate"
    name = MODEL_REFERENCE_EVALUATE if stage == "model_reference_evaluate" else MODEL_REFERENCE_ADJUDICATE
    with AuthorityUnitOfWork(database_url) as uow:
        subject = _subject_projection(uow.cursor, project_id=project_id,
            binding=frozen["subject"], scope=frozen["scope"])
        baseline = _baseline_projection(uow.cursor, project_id=project_id,
            binding=frozen["author_baseline"])
        evaluations = ([_evaluation_projection(uow.cursor, project_id=project_id,
            binding=item, frozen=frozen) for item in frozen["source_evaluations"]]
            if frozen["role"] == "ADJUDICATION" else None)
        route = binder.routes.get(stage)
        if route is None:
            raise _invalid("producer preflight has no explicit model reference route")
        pack = binder.pack_resolver.resolve_in_uow(uow, CapabilityPackResolutionRequest(
            project_id=project_id, workspace_id=workspace_id, book_id=book_id,
            workflow_definition_ref=binder.workflow_definition_ref,
            workflow_node_id=stage, environment=binder.pack_environment,
            runtime_profile=binder.pack_runtime_profile,
            release_channel=binder.pack_release_channel, release_sha=route.release_sha,
            operation_definition_ref=name + "@" + MODEL_REFERENCE_EXECUTION_VERSION,
            pack_id=binder.capability_pack_id))
        version = uow.repositories.capability_packs.require_version(pack.pack_id, pack.pack_version)
        artifacts = materialize_registered_pack_version(pack, version)
    source_bindings = [frozen["subject"], frozen["author_baseline"],
        *(frozen.get("source_evaluations") or ())]
    projection = {"contract_version": "model-reference-context-view.v1",
        "source_isolation": "FROZEN_MODEL_REFERENCE_ONLY", "stage": stage,
        "scope": dict(frozen["scope"]), "source_bindings": source_bindings,
        "policy_hash": frozen["policy_hash"], "evaluation_version": frozen["evaluation_version"]}
    context_content = {"schema_version": "novelos.model_reference_context_bundle.v1",
        "model_reference": dict(frozen), "source_isolation": "FROZEN_MODEL_REFERENCE_ONLY",
        "source_bindings": source_bindings, "provider_context_view": projection}
    provider_input = {"model_reference": dict(frozen), "subject": subject,
        "author_baseline": baseline,
        "context": {"asset_version_id": "producer-preflight:context",
            "content_hash": authorization_hash(context_content), "projection": projection}}
    if evaluations is not None:
        provider_input["source_evaluations"] = evaluations
    schema, schema_ref = binder._provider_output_contract(stage=stage,
        request_payload={"input": provider_input,
            "_production_execution": {"project_id": project_id}})
    tool_payload = json.loads(pack.tool_policy_payload_json)
    allowed, denied = _stage_tool_permissions(tool_payload, stage)
    materialization = {"schema_version": "novelos.chapter_capability_materialization.v1",
        "stage": stage, "pack_artifacts": artifacts.to_dict(include_content=True),
        "context_selection": [{"content": context_content}],
        "knowledge_selection": [item.to_dict(include_content=True)
            for item in artifacts.required_knowledge],
        "tool_permissions": {"default": str(tool_payload.get("default") or ""),
            "allowed": list(allowed), "denied": list(denied),
            "invoked": ["model.provider.invoke"]},
        "output_schema": {"ref": schema_ref, "content_hash": authorization_hash(schema),
            "content": schema}}
    _, evidence = _materialize_production_codex_prompt(target_scope={
        "scope_kind": "asset_version", "scope_id": frozen["subject"]["asset_version_id"],
        "project_id": project_id, "book_id": book_id,
        "asset_version_id": frozen["subject"]["asset_version_id"],
        "content_hash": frozen["subject"]["content_hash"]},
        stage=stage, inputs=provider_input, materialization=materialization)
    return chapter_producer_contract_identity(evidence, materialization)


def prepare_model_reference_producer_binding(database_url: str, *, project_id: str,
                                             workspace_id: str, book_id: str,
                                             binding: Mapping[str, Any],
                                             binder: "ModelReferenceExecutionContractBinder") -> tuple[dict[str, Any], dict[str, Any]]:
    """INVARIANT: the pregrant producer hash is derived from the approved Pack, then replayed exactly."""
    provisional = {**dict(binding), "producer_contract_hash": "sha256:" + "0" * 64}
    producer = model_reference_producer_identity(database_url, project_id=project_id,
        workspace_id=workspace_id, book_id=book_id, frozen=provisional, binder=binder)
    frozen = {**dict(binding), "producer_contract_hash": authorization_hash(producer)}
    replay = model_reference_producer_identity(database_url, project_id=project_id,
        workspace_id=workspace_id, book_id=book_id, frozen=frozen, binder=binder)
    if replay != producer:
        raise _invalid("model reference producer identity depends on its own hash")
    return frozen, producer


class ModelReferenceExecutionContractBinder(PostgresChapterExecutionContractBinder):
    execution_binding_domain = "model_reference"
    workflow_definition_ref = "model_reference_creation@1.0.0"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("workflow_definition_ref", self.workflow_definition_ref)
        super().__init__(*args, **kwargs)

    def assert_before_provider_send(self, *, operation_id: str, project_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            snapshot = load_bootstrap_authorization(uow.cursor, project_id=project_id,
                operation_id=operation_id)
            uow.cursor.execute("""SELECT command_payload->'payload',input_asset_snapshot,definition_name,definition_version
                FROM authority_operation WHERE project_id=%s AND operation_id=%s""",
                [project_id, operation_id])
            row = uow.cursor.fetchone()
            if not snapshot or not row or snapshot["authorization"]["purpose"] != "MODEL_REFERENCE_CREATION":
                raise _invalid("reference Effect lacks its immutable creation grant")
            command, inputs, name, version = row
            frozen = command.get("model_reference") if isinstance(command, Mapping) else None
            if (name not in MODEL_REFERENCE_STAGE or version != MODEL_REFERENCE_EXECUTION_VERSION
                or command.get("generator_operation_name") != MODEL_REFERENCE_STAGE[name]
                or frozen != snapshot["authorization"].get("model_reference")):
                raise _invalid("reference Operation differs from its formal grant")
            expected = [frozen["subject"], frozen["author_baseline"], *(frozen.get("source_evaluations") or ())]
            if [{key: item.get(key) for key in ("asset_version_id", "content_hash")} for item in inputs] != expected:
                raise _invalid("reference Operation input snapshot differs from its grant")
            return {"command": command, "frozen": frozen, "input_versions": expected,
                    "authorization": snapshot}

    def freeze_before_external_effect(self, *, capability: str,
        request_payload: Mapping[str, Any], snapshot_fencing_token: int,
        snapshot_worker_id: str, context_model_call: Any = None, capacity_probe: bool = False):
        stage = str(request_payload.get("stage") or "")
        if stage in CONTEXT_MODEL_STAGES:
            metadata = request_payload.get("_production_execution") or {}
            admitted = self.assert_before_provider_send(operation_id=str(metadata.get("operation_id") or ""),
                project_id=str(metadata.get("project_id") or ""))
            self._require_capacity_context_owner(request_payload, owner_stage=admitted["command"]["generator_operation_name"])
            if metadata.get("model_reference") != admitted["frozen"]:
                raise _invalid("reference compression differs from its admitted source")
            return super().freeze_before_external_effect(capability=capability, request_payload=request_payload,
                snapshot_fencing_token=snapshot_fencing_token, snapshot_worker_id=snapshot_worker_id,
                context_model_call=context_model_call, capacity_probe=capacity_probe)
        if stage not in MODEL_REFERENCE_STAGE.values() or capability != "model." + stage:
            raise _invalid("reference binder accepts only formal model reference stages")
        metadata = request_payload.get("_production_execution")
        if not isinstance(metadata, Mapping) or metadata.get("execution_binding_domain") != "model_reference":
            raise _invalid("reference Effect has no model reference execution binding")
        project_id = str(metadata.get("project_id") or "")
        operation_id = str(metadata.get("operation_id") or "")
        admitted = self.assert_before_provider_send(operation_id=operation_id, project_id=project_id)
        frozen = admitted["frozen"]
        if (metadata.get("model_reference") != frozen or metadata.get("book_id") != admitted["command"].get("book_id")
            or stage != admitted["command"].get("generator_operation_name")):
            raise _invalid("reference Effect metadata differs from admitted command")
        with AuthorityUnitOfWork(self.database_url) as uow:
            validate_model_reference_effect_inputs(uow.cursor, project_id=project_id,
                frozen=frozen, provider_input=request_payload.get("input"),
                operation_id=operation_id, attempt_id=str(metadata.get("attempt_id") or ""))
        context_binding = request_payload["input"]["context"]
        artifacts = metadata.get("input_artifacts")
        if (not isinstance(artifacts, list) or len(artifacts) != 1
            or artifacts[0].get("asset_version_id") != context_binding["asset_version_id"]
            or artifacts[0].get("content_hash") != context_binding["content_hash"]
            or artifacts[0].get("artifact_type") != "context_bundle"):
            raise _invalid("reference Effect must select exactly its Attempt ContextBundle")
        return super().freeze_before_external_effect(capability=capability,
            request_payload=request_payload, snapshot_fencing_token=snapshot_fencing_token,
            snapshot_worker_id=snapshot_worker_id, context_model_call=context_model_call, capacity_probe=capacity_probe)

    def _provider_output_contract(self, *, stage: str, request_payload: Mapping[str, Any],
                                  legacy_contract: bool = False,
                                  prompt_contract_version: str = "v9") -> tuple[dict[str, Any], str]:
        if stage in CONTEXT_MODEL_STAGES:
            return super()._provider_output_contract(stage=stage, request_payload=request_payload,
                legacy_contract=legacy_contract, prompt_contract_version=prompt_contract_version)
        del legacy_contract, prompt_contract_version
        if stage not in MODEL_REFERENCE_STAGE.values():
            raise _invalid("reference output schema stage differs")
        properties: dict[str, Any] = {"status": {"type": "string", "enum": ["PASSED", "FAILED", "UNCERTAIN"]},
                "score_range": {"type": "array", "minItems": 2, "maxItems": 2,
                    "items": {"type": "integer", "minimum": 0, "maximum": 100}},
                "findings": {"type": "array", "items": {"type": "string"}}}
        required = ["status", "score_range", "findings"]
        frozen = request_payload.get("input", {}).get("model_reference") or {}
        if frozen.get("scope", {}).get("scope_type") == "BOOK":
            if frozen.get("dimension") != "narrative_semantic_evaluation":
                raise _invalid("Book reference requires its exact Planning evaluation dimension")
            metadata = request_payload.get("_production_execution") or {}
            with AuthorityUnitOfWork(self.database_url) as uow:
                native = _native_asset(uow.cursor, project_id=metadata.get("project_id"),
                    binding=frozen["subject"])
            from novel_forge.modules.story_design_authority.qualification import (
                qualification_profile_options, qualification_provider_schema,
            )
            if native["asset_type"] != "planning_generation_candidate":
                raise _invalid("Book reference subject is not a native Planning candidate")
            content = native["content"]
            properties["evaluation"] = qualification_provider_schema(
                content["generator_operation_name"], **qualification_profile_options(content))
            properties["status"] = {"type": "string", "enum": ["PASSED", "FAILED"]}
            required.append("evaluation")
        schema = {"type": "object", "required": required,
            "properties": properties,
            "additionalProperties": False}
        return schema, "schema:model-reference-consensus:v1"

    def _resolve_pack_snapshot(self, *, project_id: str, workspace_id: str,
        book_id: str, operation_id: str, attempt_id: str,
        execution_fencing_token: int, worker_id: str,
        snapshot_creation_fencing_token: int, snapshot_creation_worker_id: str,
        stage: str, graph: Mapping[str, str], route: Any):
        if stage in CONTEXT_MODEL_STAGES:
            stage = MODEL_REFERENCE_STAGE.get(graph["definition_name"], "")
        if stage not in MODEL_REFERENCE_STAGE.values() or not self.capability_pack_id:
            raise _invalid("reference Pack identity is missing")
        return self.pack_resolver.freeze_attempt_snapshot(CapabilityPackResolutionRequest(
            project_id=project_id, workspace_id=workspace_id, book_id=book_id,
            workflow_definition_ref=self.workflow_definition_ref,
            workflow_node_id=stage, environment=self.pack_environment,
            runtime_profile=self.pack_runtime_profile,
            release_channel=self.pack_release_channel, release_sha=route.release_sha,
            operation_definition_ref=f"{graph['definition_name']}@{graph['definition_version']}",
            pack_id=self.capability_pack_id),
            operation_id=operation_id, attempt_id=attempt_id,
            execution_fencing_token=execution_fencing_token, worker_id=worker_id,
            snapshot_creation_fencing_token=snapshot_creation_fencing_token,
            snapshot_creation_worker_id=snapshot_creation_worker_id)

    def _target_scope(self, *, metadata: Mapping[str, Any], project_id: str,
                      book_id: str, chapter: int) -> dict[str, Any]:
        del chapter
        frozen = metadata.get("model_reference") or {}
        binding = frozen.get("subject") or {}
        if not binding.get("asset_version_id") or not binding.get("content_hash"):
            raise _invalid("reference target lacks exact asset identity")
        return {"scope_kind": "asset_version", "scope_id": binding["asset_version_id"],
            "project_id": project_id, "book_id": book_id,
            "asset_version_id": binding["asset_version_id"], "content_hash": binding["content_hash"]}

    def _resource_claims(self, *, metadata: Mapping[str, Any], chapter: int,
                         stage: str) -> tuple[str, ...]:
        del chapter
        return ("asset-version:" + metadata["model_reference"]["subject"]["asset_version_id"],
                "stage:" + stage)

    @staticmethod
    def _origin_chain(*, graph: Mapping[str, str], stage: str) -> tuple[str, ...]:
        return ("quality.model_reference", graph["definition_name"], stage)


class ModelReferenceExecutionPort:
    production_execution_gateway_backed = True
    external_effect_backed = True

    def __init__(self, database_url: str, *, model_port: ExternalEffectChapterModelPort) -> None:
        if not database_url or not model_port.external_effect_backed:
            raise ValueError("model reference requires the native ExternalEffect port")
        self.database_url = database_url
        self.model_port = model_port
        self.query = AuthorityAssetQuery(database_url)

    def evaluate(self, request: AuthorityHandlerRequest) -> dict[str, Any]:
        payload = request.command.get("payload") or {}
        frozen = payload.get("model_reference")
        stage = MODEL_REFERENCE_STAGE.get(request.definition_name)
        if (not stage or request.definition_version != MODEL_REFERENCE_EXECUTION_VERSION
            or payload.get("generator_operation_name") != stage
            or not request.attempt_id or request.fencing_token <= 0):
            raise _invalid("reference execution lacks its formal leased Attempt")
        provider_input, context = prepare_model_reference_inputs(self.database_url,
            project_id=request.project_id, book_id=payload["book_id"],
            operation_id=request.operation_id, attempt_id=request.attempt_id,
            stage=stage, frozen=frozen, trace_id=request.trace_id,
            correlation_id=request.correlation_id)
        context_input = ChapterInputAsset(asset_version_id=context.asset_version_id,
            asset_type="context_bundle", content_hash=context.content_hash,
            content=dict(context.content))
        chapter_request = ChapterHandlerRequest(operation_id=request.operation_id,
            project_id=request.project_id, workspace_id=request.workspace_id,
            trace_id=request.trace_id, correlation_id=request.correlation_id,
            command={"payload": {"book_id": payload["book_id"],
                "target_asset_version_id": frozen["subject"]["asset_version_id"],
                "target_content_hash": frozen["subject"]["content_hash"],
                "generator_operation_name": stage, "model_reference": dict(frozen),
                "context_token_budget": int(payload["context_token_budget"])}},
            inputs=(context_input,), attempt_id=request.attempt_id,
            fencing_token=request.fencing_token, worker_id=request.worker_id)
        binder = self.model_port.capability_binder
        result = self.model_port.invoke(chapter_request, stage=stage, payload=provider_input,
            pre_send_assertion=lambda: binder.assert_before_provider_send(
                operation_id=request.operation_id, project_id=request.project_id))
        if not result.real_model_call:
            raise _invalid("fixture Provider cannot create a model reference")
        judgment = result.output
        scores = judgment.get("score_range")
        expected_judgment_keys = ({"status", "score_range", "findings", "evaluation"}
            if frozen["scope"]["scope_type"] == "BOOK" else
            {"status", "score_range", "findings"})
        if (set(judgment) != expected_judgment_keys
            or judgment.get("status") not in {"PASSED", "FAILED", "UNCERTAIN"}
            or not isinstance(scores, list) or len(scores) != 2
            or any(type(score) is not int or score < 0 or score > 100 for score in scores)
            or scores[0] > scores[1]
            or not isinstance(judgment.get("findings"), list)
            or any(not isinstance(item, str) or not item.strip()
                   for item in judgment["findings"])):
            raise _invalid("Provider judgment failed local semantic validation")
        if frozen["scope"]["scope_type"] == "BOOK":
            with AuthorityUnitOfWork(self.database_url) as uow:
                native = _native_asset(uow.cursor, project_id=request.project_id,
                    binding=frozen["subject"])
            from novel_forge.modules.story_design_authority.qualification import (
                qualification_profile_options, validate_narrative_qualification,
            )
            qualification = validate_narrative_qualification(
                generator_operation_name=native["content"]["generator_operation_name"],
                value=judgment.get("evaluation"), require_pass=False,
                **qualification_profile_options(native["content"]))
            if (judgment["status"] not in {"PASSED", "FAILED"}
                or {"PASS": "PASSED", "FAIL": "FAILED"}.get(qualification.status)
                   != judgment["status"]):
                raise _invalid("Planning reference verdict differs from structured qualification")
        elif "evaluation" in judgment:
            raise _invalid("Chapter reference judgment cannot add Planning evaluation")
        execution = result.execution_evidence or {}
        external_effect_id = str((execution.get("execution_request") or {}).get("external_effect_id") or "")
        if not external_effect_id:
            raise _invalid("Provider judgment lacks its native ExternalEffect")
        log = self.query.require(project_id=request.project_id, logical_ref=model_call_log_ref(
            request.operation_id, request.attempt_id, stage, external_effect_id))
        if (log.asset_type != "model_call_log" or log.content_hash != authorization_hash(log.content)
            or log.content.get("provider_evidence", {}).get("result") != judgment):
            raise _invalid("Provider judgment differs from native ModelCallLog")
        return {"judgment": dict(judgment), "model_call": {"asset_version_id": log.asset_version_id,
            "content_hash": log.content_hash}, "external_effect_id": external_effect_id,
            "provider_id": result.provider_id, "model_id": result.model_id,
            "context_bundle": {"asset_version_id": context.asset_version_id,
                               "content_hash": context.content_hash}}


class ModelReferenceCreationHandler:
    def __init__(self, execution_port: ModelReferenceExecutionPort) -> None:
        self.execution_port = execution_port

    def execute(self, request: AuthorityHandlerRequest) -> AuthorityHandlerOutput:
        result = self.execution_port.evaluate(request)
        frozen = request.command["payload"]["model_reference"]
        references = (frozen["subject"]["asset_version_id"],
            frozen["author_baseline"]["asset_version_id"],
            *(item["asset_version_id"] for item in frozen.get("source_evaluations", ())),
            result["model_call"]["asset_version_id"],
            result["context_bundle"]["asset_version_id"])
        return AuthorityHandlerOutput(asset_type=MODEL_REFERENCE_OUTPUT,
            output_key=MODEL_REFERENCE_OUTPUT_KEY, role="diagnostic_evidence",
            qualification_policy="model-reference-diagnostic.v1",
            lifecycle="ACTIVE", eligibility="INELIGIBLE", governance="CLEAR",
            reference_asset_version_ids=tuple(references),
            content={"schema_version": "novelos.model_reference_provider_result.v1",
                "project_id": request.project_id, "book_id": request.command["payload"]["book_id"],
                "operation_id": request.operation_id, "attempt_id": request.attempt_id,
                "model_reference": frozen, **result,
                "production_eligible": False, "literary_quality_proven": False},
            evidence={"model_call": result["model_call"],
                "external_effect_id": result["external_effect_id"]})


class ModelReferenceCreationRegistry:
    def __init__(self, execution_port: ModelReferenceExecutionPort) -> None:
        handler = ModelReferenceCreationHandler(execution_port)
        self._items = {name: AuthorityHandlerRegistration(
            definition_name=name, definition_version=MODEL_REFERENCE_EXECUTION_VERSION,
            handler_key=MODEL_REFERENCE_HANDLER,
            handler_contract_version="model-reference-creation-handler.v1",
            output_asset_type=MODEL_REFERENCE_OUTPUT,
            output_key=MODEL_REFERENCE_OUTPUT_KEY, role="diagnostic_evidence",
            completion_topic=MODEL_REFERENCE_TOPIC, handler=handler)
            for name in MODEL_REFERENCE_STAGE}

    @property
    def available_handler_keys(self) -> frozenset[str]:
        return frozenset({MODEL_REFERENCE_HANDLER})

    @property
    def definition_names(self) -> frozenset[str]:
        return frozenset(self._items)

    def registration(self, definition_name: str,
                     definition_version: str) -> AuthorityHandlerRegistration:
        if definition_version != MODEL_REFERENCE_EXECUTION_VERSION:
            raise KeyError((definition_name, definition_version))
        return self._items[definition_name]


@dataclass(frozen=True, slots=True)
class ModelReferenceCreationCommand:
    project_id: str
    workspace_id: str
    book_id: str
    actor_id: str
    authorization_id: str
    idempotency_key: str
    model_reference: dict[str, Any]
    context_token_budget: int
    source_operation_id: str


class ModelReferenceCreationApplication:
    """INVARIANT: native admission freezes one campaign grant and exact source versions before scheduling."""
    def __init__(self, database_url: str, *, application_build_id: str,
                 commit_sha: str, execution_port: ModelReferenceExecutionPort) -> None:
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.execution_port = execution_port
        self.registry = ModelReferenceCreationRegistry(execution_port)

    def admit(self, command: ModelReferenceCreationCommand,
              *, principal: Principal) -> dict[str, Any]:
        principal.require("chapter.authority.execute", command.project_id)
        if (principal.principal_type is not PrincipalType.LOCAL_OPERATOR
            or principal.principal_id != command.actor_id):
            raise PermissionError("model reference admission requires its authenticated operator")
        frozen = command.model_reference
        validate_model_reference_creation_binding(frozen)
        if command.context_token_budget <= 0 or command.context_token_budget > 512000:
            raise _invalid("model reference Context token budget is invalid")
        role = frozen["role"]
        name = MODEL_REFERENCE_EVALUATE if role == "BLIND_EVALUATION" else MODEL_REFERENCE_ADJUDICATE
        stage = MODEL_REFERENCE_STAGE[name]
        source_bindings = [frozen["subject"], frozen["author_baseline"],
            *(frozen.get("source_evaluations") or ())]
        with AuthorityUnitOfWork(self.database_url) as uow:
            _subject_projection(uow.cursor, project_id=command.project_id,
                binding=frozen["subject"], scope=frozen["scope"])
            from .reference_subject import require_reference_subject

            native_subject = require_reference_subject(uow.cursor,
                project_id=command.project_id, binding=frozen["subject"],
                allowed_types=frozenset({"chapter_provider_sample", "world_provider_sample",
                    "planning_generation_candidate"}))
            if native_subject["generation_operation_id"] != command.source_operation_id:
                raise _invalid("creation source Operation differs from native subject")
            _baseline_projection(uow.cursor, project_id=command.project_id,
                binding=frozen["author_baseline"])
            if role == "ADJUDICATION":
                source_sessions: set[str] = set()
                source_calls: set[str] = set()
                for binding in frozen["source_evaluations"]:
                    _evaluation_projection(uow.cursor, project_id=command.project_id,
                        binding=binding, frozen=frozen)
                    record = _native_asset(uow.cursor, project_id=command.project_id,
                        binding=binding)["content"]
                    session = str(record.get("session_id") or "")
                    call = str(record.get("external_effect_id") or "")
                    if not session or not call or session in source_sessions or call in source_calls:
                        raise _invalid("adjudication requires two distinct native blind sessions and Effects")
                    source_sessions.add(session)
                    source_calls.add(call)
            uow.cursor.execute("SELECT operation_id,command_payload->'payload' FROM authority_operation "
                "WHERE project_id=%s AND operation_id=%s", [command.project_id,
                command.source_operation_id])
            source_row = uow.cursor.fetchone()
            if (not source_row or not isinstance(source_row[1], Mapping)
                or source_row[1].get("book_id") != command.book_id):
                raise _invalid("model reference source Operation or Book differs")
        if frozen["scope"]["scope_type"] == "BOOK":
            if frozen["scope"]["book_id"] != command.book_id:
                raise _invalid("model reference Book scope differs from admission")
        payload = {"project_id": command.project_id, "book_id": command.book_id,
            "generator_operation_name": stage, "model_reference": frozen,
            "context_token_budget": command.context_token_budget,
            "routing_bootstrap_authorization_id": command.authorization_id,
            "idempotency_key": command.idempotency_key,
            "logical_key": frozen["subject"]["asset_version_id"] + ":" + role,
            "input_versions": source_bindings}
        snapshot = freeze_bootstrap_authorization(database_url=self.database_url,
            command_payload=payload, principal=principal, environment="validation",
            permission="chapter.authority.execute",
            idempotency_scope="book:model-reference-creation")
        if snapshot["authorization"]["purpose"] != "MODEL_REFERENCE_CREATION":
            raise _invalid("creation admission lacks exact model reference grant")
        binder = self.execution_port.model_port.capability_binder
        producer = model_reference_producer_identity(self.database_url,
            project_id=command.project_id, workspace_id=command.workspace_id,
            book_id=command.book_id, frozen=frozen, binder=binder)
        if authorization_hash(producer) != snapshot["authorization"]["producer_contract_hash"]:
            raise _invalid("creation grant producer contract differs from deployed Pack and prompt")
        payload["routing_bootstrap_authorization"] = snapshot
        definition = next(item for item in model_reference_creation_definitions(
            application_build_id=self.application_build_id, commit_sha=self.commit_sha)
            if item["name"] == name)
        trace = "model-reference:" + command.idempotency_key
        with AuthorityUnitOfWork(self.database_url, coordinate_nested=True) as uow:
            registered = uow.repositories.definitions.get(name, MODEL_REFERENCE_EXECUTION_VERSION)
            if registered is None:
                uow.repositories.definitions.register(definition)
            elif definition_hash(registered) != definition_hash(definition):
                raise _invalid("registered model reference definition differs from runtime")
            admitted = admit_command_in_uow(uow, {
                "definition_name": name, "definition_version": MODEL_REFERENCE_EXECUTION_VERSION,
                "project_id": command.project_id, "workspace_id": command.workspace_id,
                "book_id": command.book_id, "logical_key": payload["logical_key"],
                "actor_id": command.actor_id,
                "idempotency_scope": "book:model-reference-creation",
                "idempotency_key": command.idempotency_key,
                "trace_id": trace, "span_id": str(uuid4()), "correlation_id": trace,
                "causation_id": command.source_operation_id,
                "causation_operation_id": command.source_operation_id,
                "input": {"project_id": command.project_id,
                    "input_asset_version_ids": [item["asset_version_id"] for item in source_bindings],
                    "payload": payload}, "input_assets": source_bindings,
            }, context=AdmissionContext(actor_id=command.actor_id,
                permissions=principal.permissions,
                available_handlers=self.registry.available_handler_keys,
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha))
            operation = uow.repositories.attempt_runtime.operation_state(
                str(admitted["operation_id"]), command.project_id)
            if operation["status"] == "ADMITTED":
                transition_operation_in_uow(uow, OperationTransitionCommand(
                    operation_id=str(admitted["operation_id"]), project_id=command.project_id,
                    expected_version=int(operation["version"]), expected_status="ADMITTED",
                    target_status="READY", actor_id=command.actor_id,
                    reason="frozen model reference sources and campaign grant",
                    trace_id=trace, correlation_id=trace,
                    causation_id=command.source_operation_id))
            graph = GraphCommandContext(command.project_id, command.actor_id, trace, trace)
            saga = start_saga(self.database_url, graph,
                root_operation_id=str(admitted["operation_id"]))
            register_saga_step(self.database_url, graph, str(saga["saga_id"]),
                str(admitted["operation_id"]), stage, 1, "")
            uow.commit()
        return {"operation_id": str(admitted["operation_id"]),
                "replayed": bool(admitted["replayed"]), "production_eligible": False}

    def run_or_recover(self, *, operation_id: str, project_id: str):
        return ContentAuthorityScheduler(self.database_url,
            registry=self.registry, worker_id="model-reference-worker",
            lease_seconds=60).run_or_recover(operation_id=operation_id,
                project_id=project_id)


__all__ = ["MODEL_REFERENCE_EVALUATE", "MODEL_REFERENCE_ADJUDICATE",
           "MODEL_REFERENCE_EXECUTION_VERSION", "MODEL_REFERENCE_STAGE",
           "validate_model_reference_effect_inputs", "prepare_model_reference_inputs",
           "model_reference_producer_identity",
           "prepare_model_reference_producer_binding",
           "ModelReferenceExecutionContractBinder", "ModelReferenceExecutionPort",
           "model_reference_creation_definitions", "ModelReferenceCreationCommand",
           "ModelReferenceCreationApplication", "ModelReferenceCreationRegistry"]
