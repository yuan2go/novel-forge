from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    read_failed_operation_success,
)
from novel_forge.storage.authority_asset_store import (
    AuthorityAssetQuery,
    AuthorityAssetWriter,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from .domain import StoryPlanningGenerationCommand, canonical_hash
from .foundation_generation import (
    FOUNDATION_GENERATORS,
    normalize_foundation_payload,
    validate_foundation_payload,
)

RESULT_FAILURE_TYPE = "planning_generation_result_failure"
MAXIMUM_RESULT_REPAIRS = 2


class PlanningResultValidationError(KernelError):
    def __init__(
        self,
        error: KernelError,
        *,
        raw_result: Any,
        execution_evidence: Mapping[str, Any],
    ) -> None:
        super().__init__("PLANNING_GENERATION_RESULT_INVALID", error.message)
        self.raw_result = dict(raw_result) if isinstance(raw_result, Mapping) else raw_result
        self.execution_evidence = dict(execution_evidence)
        self.diagnostic = {
            "status": "FAIL",
            "validation_kind": "PRE_CANDIDATE_CONTRACT",
            "error_code": error.code,
            "message": error.message,
            "fields": list(getattr(error, "diagnostics", ())),
            **({"failure_class": "BUSINESS_REJECT" if error.code == "CRAFT_CONCRETE_REJECTED" else "CONTRACT_INVALID"}
               if error.code.startswith(("CRAFT_", "PLANNING_KNOWLEDGE_")) else {}),
        }


def validate_raw_result(
    generator: str, raw: Any, *, compiled_scope: str | None = None, work_requirements: bool = False
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise KernelError(
            "PLANNING_RESULT_OBJECT_REQUIRED",
            f"$: expected object, actual {type(raw).__name__}",
        )
    objective = raw.get("objective")
    if not isinstance(objective, str) or not objective.strip():
        raise KernelError(
            "PLANNING_RESULT_OBJECTIVE_INVALID",
            f"$.objective: expected nonempty string, actual {type(objective).__name__}",
        )
    normalized = (
        normalize_foundation_payload(
            generator, raw, expected_compiled_scope=compiled_scope
        )
        if generator in FOUNDATION_GENERATORS
        else dict(raw)
    )
    if generator in FOUNDATION_GENERATORS:
        structural = {
            key: value
            for key, value in normalized.items()
            if key not in {"author_design_decisions", "knowledge_translations"}
        }
        envelope = {"foundation_parent_bindings": {}, "contract_version": "foundation-generation.v2" if work_requirements else "foundation-generation.v1"}
        if compiled_scope and generator == "world.design.generate":
            envelope["world_compilation"] = {"compiled_scope": compiled_scope}
        structural.update(constraint_envelope=envelope, foundation_parent_bindings={})
        validate_foundation_payload(generator, {"candidate_payload": structural})
    return normalized


def persist_result_failure(
    database_url: str,
    *,
    request: Any,
    command: StoryPlanningGenerationCommand,
    error: PlanningResultValidationError,
) -> None:
    content = {
        "contract_version": "planning-result-failure.v1",
        "project_id": command.project_id,
        "workspace_id": command.workspace_id,
        "book_id": command.book_id,
        "operation_id": request.operation_id,
        "attempt_id": request.attempt_id,
        "fencing_token": request.fencing_token,
        "generator_operation_name": command.generator_operation_name,
        "logical_key": command.logical_key,
        "execution_contract_version": command.execution_contract_version,
        "input_versions": dict(command.input_versions),
        "raw_result": error.raw_result,
        "raw_result_hash": canonical_hash(error.raw_result),
        "raw_result_hash_basis": "CANONICAL_PARSED_JSON",
        "execution_evidence": error.execution_evidence,
        "diagnostic": error.diagnostic,
        "candidate_status": "NOT_MATERIALIZED",
    }
    AuthorityAssetWriter(database_url).materialize_output(
        AuthorityAssetWriteCommand(
            operation_id=request.operation_id,
            project_id=command.project_id,
            asset_id=f"planning-result-failure:{request.operation_id}:{request.attempt_id}",
            asset_type=RESULT_FAILURE_TYPE,
            schema_version="planning-result-failure.v1",
            logical_ref=f"planning/result_failures/{request.operation_id}/{request.attempt_id}.json",
            category="runs",
            output_key="story_planning.result_failure",
            role="diagnostic_evidence",
            content=content,
            qualification_policy="planning-result-failure-evidence-v1",
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            eligibility="INELIGIBLE",
        )
    )


def require_result_repair_source(
    database_url: str,
    *,
    command: StoryPlanningGenerationCommand,
    operation_id: str,
    source_asset_version_id: str = "",
) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            "SELECT op.status, op.project_id, op.workspace_id, g.book_id, op.command_payload->'payload', g.candidate_asset_version_id FROM authority_operation op JOIN authority_story_planning_generation g USING(operation_id) WHERE op.operation_id=%s",
            [operation_id],
        )
        row = uow.cursor.fetchone()
        if (
            row is None
            or row[0] != "FAILED_FINAL"
            or row[5]
            or tuple(map(str, row[1:4]))
            != (command.project_id, command.workspace_id, command.book_id)
        ):
            raise KernelError(
                "PLANNING_RESULT_REPAIR_SOURCE_INVALID",
                "result repair requires this Book's failed terminal Operation with no Candidate",
            )
        frozen = dict(row[4])
        from .application import _command_payload

        permitted_linkage_fields = {
            "runtime_continuation_id",
            "idempotency_key",
            "repair_of_candidate_id",
            "repair_of_operation_id",
            "repair_result_asset_version_id",
            "repair_result_diagnostic",
            "repair_reason",
            "repair_number",
            "parent_agent_session_operation_id",
        }
        current_task = {
            key: value
            for key, value in _command_payload(command).items()
            if key not in permitted_linkage_fields
        }
        frozen_task = {
            key: value
            for key, value in frozen.items()
            if key not in permitted_linkage_fields
        }
        if current_task != frozen_task:
            raise KernelError(
                "PLANNING_RESULT_REPAIR_INPUT_DRIFT",
                "result repair must retain the failed Operation's entire frozen task",
            )
        uow.cursor.execute(
            "SELECT output.asset_version_id FROM authority_operation_output_asset output JOIN authority_asset asset USING(asset_id) JOIN authority_asset_version version USING(asset_version_id) WHERE output.operation_id=%s AND ((asset.asset_type=%s) OR (asset.asset_type='model_call_log' AND version.content->>'stage'=%s)) ORDER BY CASE WHEN asset.asset_type=%s THEN 0 ELSE 1 END, version.created_at DESC, output.asset_version_id",
            [
                operation_id,
                RESULT_FAILURE_TYPE,
                command.generator_operation_name,
                RESULT_FAILURE_TYPE,
            ],
        )
        sources = [str(item[0]) for item in uow.cursor.fetchall()]
    if source_asset_version_id and source_asset_version_id not in sources:
        raise KernelError(
            "PLANNING_RESULT_REPAIR_SOURCE_INVALID",
            "repair source is not an output of the failed Operation",
        )
    if not sources:
        raise KernelError(
            "PLANNING_RESULT_REPAIR_EVIDENCE_MISSING",
            "failed Operation has no durable Provider result; reconcile before any new request",
        )
    source = AuthorityAssetQuery(database_url).require(
        project_id=command.project_id,
        asset_version_id=source_asset_version_id or sources[0],
    )
    if source.asset_type == RESULT_FAILURE_TYPE:
        raw = source.content["raw_result"]
        evidence = dict(source.content["execution_evidence"])
        effect_id = str(evidence.get("external_receipt_ref") or "")
    else:
        raw = source.content.get("result")
        production = source.content.get("production_execution") or {}
        effect_id = str(source.content.get("external_effect_id") or "")
        if not effect_id:
            with AuthorityUnitOfWork(database_url) as uow:
                uow.cursor.execute(
                    "SELECT external_effect_id FROM authority_external_effect WHERE operation_id=%s AND project_id=%s AND effect_type='model.invoke'",
                    [operation_id, command.project_id],
                )
                effects = uow.cursor.fetchall()
            if len(effects) != 1:
                raise KernelError(
                    "PLANNING_RESULT_REPAIR_RECEIPT_AMBIGUOUS",
                    "the retained result must identify exactly one Provider effect",
                )
            effect_id = str(effects[0][0])
        evidence = {
            "external_receipt_ref": effect_id,
            "production_execution": production,
        }
    receipt = read_failed_operation_success(
        database_url,
        EffectCommandContext(
            operation_id=operation_id,
            project_id=command.project_id,
            actor_id=command.actor_id,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        ),
        effect_id=effect_id,
    )
    if receipt is None or receipt["provider_evidence"].get("result") != raw:
        raise KernelError(
            "PLANNING_RESULT_REPAIR_RECEIPT_INVALID",
            "raw result must match its verified succeeded Provider receipt",
        )
    if receipt["budget_reservation_status"] != "SETTLED":
        raise KernelError(
            "PLANNING_RESULT_REPAIR_BUDGET_UNSETTLED",
            "settle the known original Provider usage before admitting a repair request",
        )
    try:
        validate_raw_result(
            command.generator_operation_name,
            raw,
            work_requirements=command.execution_contract_version == "1.17.0",
            compiled_scope="BOOK"
            if command.generator_operation_name == "world.design.generate"
            else None,
        )
        if source.asset_type == RESULT_FAILURE_TYPE and source.content["diagnostic"]["error_code"].startswith(("CRAFT_", "PLANNING_KNOWLEDGE_")):
            from .knowledge_translation import validate_knowledge_translations
            from novel_forge.modules.mkaos_authority.craft_reselection import validate_concrete_selection
            from novel_forge.modules.mkaos_authority.craft_selection import build_craft_strategy
            context = AuthorityAssetQuery(database_url).require(project_id=command.project_id, asset_version_id=evidence["context_bundle_asset_version_id"])
            selection = context.content["narrative_intelligence"]
            if (context.content_hash != evidence["context_bundle_hash"] or selection["selection_digest"] != evidence["narrative_intelligence_selection_digest"]):
                raise KernelError("PLANNING_RESULT_REPAIR_CONTEXT_DRIFT", "Concrete failure must retain its exact frozen selection")
            validate_knowledge_translations(raw, selection)
            validate_concrete_selection(raw, selection)
            build_craft_strategy(raw, selection)
    except KernelError as error:
        diagnostic = PlanningResultValidationError(
            error, raw_result=raw, execution_evidence=evidence
        ).diagnostic
    else:
        raise KernelError(
            "PLANNING_RESULT_REPAIR_NOT_REQUIRED",
            "retained Provider result is valid; recover the original persistence failure without regenerating",
        )
    if source.asset_type == RESULT_FAILURE_TYPE and source.content["diagnostic"] != diagnostic:
        raise KernelError("PLANNING_RESULT_REPAIR_DIAGNOSTIC_DRIFT", "A replayed failure must match the recorded diagnosis exactly")
    return {
        "asset_version_id": source.asset_version_id,
        "content_hash": source.content_hash,
        "source_operation_id": operation_id,
        "raw_result": raw,
        "diagnostic": diagnostic,
        "execution_evidence": evidence,
        "schema_version": "planning-result-repair-context.v1",
    }
