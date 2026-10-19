from copy import deepcopy

from novel_forge.modules.book_authority.memory_backfill import STAGE, TASK_TYPE
from novel_forge.modules.command_kernel.errors import KernelError
from .execution import PostgresReaderOutcomeExecutionContractBinder


class PostgresMemoryExecutionContractBinder(PostgresReaderOutcomeExecutionContractBinder):
    workflow_definition_ref = "book_followup_working_memory_extract@1.1.0"
    execution_binding_domain = STAGE
    stage_name = STAGE
    context_schema = "novelos.working_memory_context_bundle.v1"

    def _project_context_input(self, asset_type, content):
        if asset_type != TASK_TYPE:
            raise KernelError("WORKING_MEMORY_CONTEXT_INVALID", "Extract only this Book's frozen selected prose")
        return deepcopy(dict(content))

    def _target_scope(self, *, metadata, project_id, book_id, chapter):
        sources = [row for row in metadata["input_artifacts"] if row.get("artifact_type") == TASK_TYPE]
        if len(sources) != 1:
            raise KernelError("WORKING_MEMORY_CONTEXT_INVALID", "Require one exact extraction task")
        identity = sources[0]["asset_version_id"]
        return {"scope_kind": "asset_version", "scope_id": identity, "project_id": project_id,
            "book_id": book_id, "asset_version_id": identity}


def memory_context_view(context):
    rows = context.get("selected_inputs", [])
    if context.get("schema_version") != PostgresMemoryExecutionContractBinder.context_schema or len(rows) != 1 or rows[0].get("asset_type") != TASK_TYPE:
        raise KernelError("WORKING_MEMORY_CONTEXT_INVALID", "Require the frozen extraction context")
    return {"contract_version": "provider-context-view-v2", "stage": STAGE, "source": rows[0]["projection"],
        "instruction": "Extract source-bound working observations only from the provided current chapter text. Prior observations are fallible navigation, not Canon. Preserve subject, stable state_key, attribution, negation, conditions, uncertainty, beliefs, hearsay and reader-only disclosure. Reuse prior subject/state_key for the same state or promise. For each literal quote use both start/end null when it occurs exactly once; the Host locates it. Supply Unicode code-point offsets only to disambiguate a repeated quote. Prior selection omissions remain unknown, not evidence of absence. Record current state changes, important events, knowledge ownership, relationship changes, consequences and promises. For promise closure use FULFILLED or RELEASED only with direct textual support and supersedes referencing exact earlier promise observation IDs with identical subject/state_key/perspective/knowledge_owner. Otherwise retain UNKNOWN or OPEN. Non-promises use NOT_APPLICABLE and empty supersedes. Causes reference only provided prior observation IDs. Do not invent unseen events, author acceptance, knowledge or future-plan fulfilment. Omit unsupported claims; an empty list is valid. Never rewrite the manuscript."}


def memory_output_schema():
    from novel_forge.modules.narrative_state.working_memory import KINDS, PERSPECTIVES
    properties = {key: {"type": "string", "minLength": 1, "maxLength": limit} for key, limit in (("subject", 120), ("state_key", 120), ("claim", 600), ("quote", 2000))}
    properties.update(kind={"enum": sorted(KINDS)}, perspective={"enum": sorted(PERSPECTIVES)},
        knowledge_owner={"type": "string", "maxLength": 120},
        start={"type": ["integer", "null"], "minimum": 0}, end={"type": ["integer", "null"], "minimum": 1},
        causes={"type": "array", "maxItems": 8, "items": {"type": "string"}},
        supersedes={"type": "array", "items": {"type": "string"}},
        promise_status={"enum": ["OPEN", "FULFILLED", "RELEASED", "UNKNOWN", "NOT_APPLICABLE"]})
    return {"type": "object", "properties": {"observations": {"type": "array", "maxItems": 64,
        "items": {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}}},
        "required": ["observations"], "additionalProperties": False}


def build_memory_model_port(settings, *, execution, env):
    from novel_forge.infrastructure.environment import RuntimeEnvironment
    from novel_forge.modules.chapter_authority.model_effects import ExternalEffectChapterModelPort
    runtime = RuntimeEnvironment.parse(str(env.get("NOVEL_FORGE_ENVIRONMENT") or settings.environment))
    binder = PostgresMemoryExecutionContractBinder(settings.database_url, execution.gateway.routes,
        capability_pack_id=str(env.get("NOVEL_FORGE_WORKING_MEMORY_CAPABILITY_PACK_ID") or "working_memory_pack"),
        pack_environment=runtime.value, pack_runtime_profile=runtime.value,
        pack_release_channel=str(env.get("NOVEL_FORGE_RELEASE_CHANNEL") or "VALIDATION").upper(), pack_required=runtime.controlled)
    execution.gateway.register_execution_binder(STAGE, binder)
    return ExternalEffectChapterModelPort(settings.database_url, adapter=execution.gateway,
        worker_id=str(env.get("NOVEL_FORGE_BOOK_FOLLOWUP_WORKER_ID") or "book-followup-authority-worker"),
        max_cost_per_call=execution.max_cost_per_call, budget_caps=execution.budget_caps(), capability_binder=binder,
        execution_binding_domain=STAGE)
