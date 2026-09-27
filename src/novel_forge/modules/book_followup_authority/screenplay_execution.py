from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError

from .contracts import BOOK_FOLLOWUP_DEFINITION_VERSION
from .execution import PostgresReaderOutcomeExecutionContractBinder
from .screenplay import CANDIDATE_TYPE, REVIEW_TYPE, SOURCE_TYPE, SCREENPLAY_STAGES


class PostgresScreenplayExecutionContractBinder(PostgresReaderOutcomeExecutionContractBinder):
    def __init__(self, *args: Any, stage: str, **kwargs: Any):
        if stage not in SCREENPLAY_STAGES:
            raise ValueError("Unknown screenplay stage")
        self.stage_name = stage
        self.execution_binding_domain = stage
        self.context_schema = "novelos." + stage + "_context_bundle.v1"
        self.workflow_definition_ref = "book_followup_" + stage + "@" + BOOK_FOLLOWUP_DEFINITION_VERSION
        super().__init__(*args, **kwargs)

    def _resolve_pack_snapshot(self, **arguments: Any):
        from .screenplay_sample_execution import resolve_sample_pack
        from .screenplay_sampling import sample_definition_name
        if arguments["graph"]["definition_name"] == sample_definition_name(self.stage_name):
            return resolve_sample_pack(self, arguments)
        return super()._resolve_pack_snapshot(**arguments)

    def _context_input_permitted(self, document: Any, *, project_id: str, operation_id: str) -> bool:
        from .screenplay_sample_execution import sample_input_permitted
        from .screenplay_sampling import SCREENPLAY_SAMPLE_TYPE
        if document.asset_type == SCREENPLAY_SAMPLE_TYPE:
            return sample_input_permitted(self, document, project_id=project_id, operation_id=operation_id)
        return super()._context_input_permitted(document, project_id=project_id, operation_id=operation_id)

    def _project_context_input(self, asset_type: str, content: Mapping[str, Any]) -> dict[str, Any]:
        from .screenplay_sampling import SCREENPLAY_SAMPLE_TYPE
        from .screenplay_sample_execution import upstream_projection
        if asset_type == SCREENPLAY_SAMPLE_TYPE:
            return upstream_projection(self.stage_name, content)
        if asset_type not in {SOURCE_TYPE, CANDIDATE_TYPE, REVIEW_TYPE}:
            raise KernelError("SCREENPLAY_CONTEXT_SOURCE_FORBIDDEN", "Only the frozen adaptation source, candidate and exact review may enter this context")
        return deepcopy(dict(content))

    def _target_scope(self, *, metadata: Mapping[str, Any], project_id: str, book_id: str, chapter: int) -> dict[str, Any]:
        sources = [item for item in metadata.get("input_artifacts", []) if item.get("artifact_type") == SOURCE_TYPE]
        if len(sources) != 1:
            raise KernelError("SCREENPLAY_CONTEXT_SOURCE_INVALID", "One exact edition adaptation contract is required")
        version = sources[0]["asset_version_id"]
        return {"scope_kind": "asset_version", "scope_id": version, "project_id": project_id,
                "book_id": book_id, "asset_version_id": version}


def screenplay_context_view(stage: str, context: Mapping[str, Any]) -> dict[str, Any]:
    if context.get("schema_version") != "novelos." + stage + "_context_bundle.v1":
        raise KernelError("SCREENPLAY_CONTEXT_INVALID", "The Provider needs its exact stage context contract")
    from .screenplay_sample_execution import expand_sample_inputs
    selected = expand_sample_inputs(context.get("selected_inputs", []))
    expected = {SOURCE_TYPE} | ({CANDIDATE_TYPE} if stage != "screenplay_generate" else set()) | ({REVIEW_TYPE} if stage == "screenplay_revision" else set())
    if len(selected) != len(expected) or {item.get("asset_type") for item in selected} != expected:
        raise KernelError("SCREENPLAY_CONTEXT_INVALID", "A stage cannot omit required inputs or admit unrelated manuscript facts")
    return {"contract_version": "provider-context-view-v2", "stage": stage,
            "inputs": {item["asset_type"]: item["projection"] for item in selected},
            "instruction": "以冻结的同书精确稿件版本改编中文场景剧本。遵循逐场结构计划，区分可表演动作和人物对白。保留指定因果与承诺，改编仅限批准范围。对白不得泄露角色未知信息，动作不得泄露读者不可知信息。审稿独立检查来源保真、人物知识、戏剧行动、对白和可表演性，保留不确定或否定结果；修订只修具体定位问题并保留合法部分。所有派生差异仅属于此剧本，不能修改小说 Canon。"}


def build_screenplay_model_ports(settings, *, execution, env):
    from novel_forge.infrastructure.environment import RuntimeEnvironment
    from novel_forge.modules.chapter_authority.model_effects import ExternalEffectChapterModelPort
    runtime = RuntimeEnvironment.parse(str(env.get("NOVEL_FORGE_ENVIRONMENT") or settings.environment))
    if runtime is not execution.runtime_environment:
        raise RuntimeError("Screenplay and Production Execution environments must match")
    ports = {}
    for stage in SCREENPLAY_STAGES:
        binder = PostgresScreenplayExecutionContractBinder(settings.database_url, execution.gateway.routes, stage=stage,
            capability_pack_id=str(env.get("NOVEL_FORGE_" + stage.upper() + "_CAPABILITY_PACK_ID") or stage + "_pack"),
            pack_environment=runtime.value, pack_runtime_profile=runtime.value,
            pack_release_channel=str(env.get("NOVEL_FORGE_RELEASE_CHANNEL") or "VALIDATION").upper(),
            pack_required=runtime.controlled)
        execution.gateway.register_execution_binder(stage, binder)
        ports[stage] = ExternalEffectChapterModelPort(settings.database_url, adapter=execution.gateway,
            worker_id=str(env.get("NOVEL_FORGE_BOOK_FOLLOWUP_WORKER_ID") or "book-followup-authority-worker"),
            max_cost_per_call=execution.max_cost_per_call, budget_caps=execution.budget_caps(),
            capability_binder=binder, execution_binding_domain=stage)
    return ports
