from __future__ import annotations

from typing import Any


SOURCE_IMPORT_DEFINITION_VERSION = "1.3.3"
SOURCE_IMPORT_OPERATION_TIMEOUT_SECONDS = 900
SOURCE_IMPORT_PROFILING_QUEUE_TIMEOUT_SECONDS = 14_400
SOURCE_IMPORT_DISCOVERY_OPERATION = "source.import.repository.discover"
SOURCE_IMPORT_DISCOVERY_HANDLER = "novel_forge.source_import.repository_discover"
SOURCE_IMPORT_FILE_OPERATION = "source.import.file.process"
SOURCE_IMPORT_FILE_HANDLER = "novel_forge.source_import.file_process"
SOURCE_IMPORT_WORK_OPERATION = "source.import.work.process"
SOURCE_IMPORT_WORK_HANDLER = "novel_forge.source_import.work_process"
SOURCE_IMPORT_PROFILING_OPERATION = "source.import.document.profile"
SOURCE_IMPORT_PROFILING_HANDLER = "novel_forge.source_import.document_profile"
SOURCE_IMPORT_ANALYSIS_PLANNING_OPERATION = "source.import.analysis.plan"
SOURCE_IMPORT_ANALYSIS_PLANNING_HANDLER = "novel_forge.source_import.analysis_plan"
SOURCE_IMPORT_DECONSTRUCTION_OPERATION = "source.import.deconstruction.execute"
SOURCE_IMPORT_DECONSTRUCTION_HANDLER = (
    "novel_forge.source_import.deconstruction_execute"
)
SOURCE_IMPORT_MKAOS_OPERATION = "source.import.mkaos.extract"
SOURCE_IMPORT_MKAOS_HANDLER = "novel_forge.source_import.mkaos_extract"
SOURCE_IMPORT_REPROCESSING_OPERATION = "source.import.reprocessing.apply"
SOURCE_IMPORT_REPROCESSING_HANDLER = "novel_forge.source_import.reprocessing_apply"

SOURCE_IMPORT_OPERATIONS = frozenset(
    {
        SOURCE_IMPORT_DISCOVERY_OPERATION,
        SOURCE_IMPORT_FILE_OPERATION,
        SOURCE_IMPORT_WORK_OPERATION,
        SOURCE_IMPORT_PROFILING_OPERATION,
        SOURCE_IMPORT_ANALYSIS_PLANNING_OPERATION,
        SOURCE_IMPORT_DECONSTRUCTION_OPERATION,
        SOURCE_IMPORT_MKAOS_OPERATION,
        SOURCE_IMPORT_REPROCESSING_OPERATION,
    }
)


def source_import_definitions(
    *, application_build_id: str, commit_sha: str
) -> tuple[dict[str, Any], ...]:
    common = {
        "definition_version": SOURCE_IMPORT_DEFINITION_VERSION,
        "family": "source_import",
        "enabled": True,
        "command_schema": {
            "type": "object",
            "required": ["project_id", "workspace_id", "payload"],
            "properties": {
                "project_id": {"type": "string"},
                "workspace_id": {"type": "string"},
                "payload": {"type": "object"},
            },
            "additionalProperties": False,
        },
        "result_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        },
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "worker",
        "permissions": ["source.authority.execute"],
        "approval_policy": {"required": False, "policy_key": "source-import-v1"},
        "idempotency_scope": "project:source-import",
        "retry_policy": {"max_attempts": 3},
        "timeout_policy": {
            "operation_timeout_seconds": SOURCE_IMPORT_OPERATION_TIMEOUT_SECONDS
        },
        "cancellation_policy": {"mode": "cancel_active_attempt"},
        "compensation_policy": {
            "supported": False,
            "reason": "immutable snapshots, source evidence, and Provider receipts",
        },
        "irreversible_effect_policy": {"allowed": True},
        "policy": {
            "execution_classification": "durable_job",
            "project_scope_required": True,
            "postgresql_authority_required": True,
            "raw_source_in_postgresql_forbidden": True,
            "raw_source_in_generation_context_forbidden": True,
            "external_effect_and_fence_required": True,
        },
        "completion_contract": {
            "version": "source.import.completion.v1",
            "required_asset_selectors": [],
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": [],
        },
    }
    rows = (
        (
            SOURCE_IMPORT_DISCOVERY_OPERATION,
            SOURCE_IMPORT_DISCOVERY_HANDLER,
            "repository:{project_id}",
            ["source.remote.fetch"],
        ),
        (
            SOURCE_IMPORT_FILE_OPERATION,
            SOURCE_IMPORT_FILE_HANDLER,
            "source-file:{project_id}",
            ["object_store.put"],
        ),
        (
            SOURCE_IMPORT_WORK_OPERATION,
            SOURCE_IMPORT_WORK_HANDLER,
            "source-work:{project_id}",
            ["object_store.put"],
        ),
        (
            SOURCE_IMPORT_PROFILING_OPERATION,
            SOURCE_IMPORT_PROFILING_HANDLER,
            "source-profile:{project_id}",
            ["source.content.classify"],
        ),
        (
            SOURCE_IMPORT_ANALYSIS_PLANNING_OPERATION,
            SOURCE_IMPORT_ANALYSIS_PLANNING_HANDLER,
            "source-analysis-plan:{project_id}",
            [],
        ),
        (
            SOURCE_IMPORT_DECONSTRUCTION_OPERATION,
            SOURCE_IMPORT_DECONSTRUCTION_HANDLER,
            "source-analysis:{project_id}",
            ["deconstruction.observe"],
        ),
        (
            SOURCE_IMPORT_MKAOS_OPERATION,
            SOURCE_IMPORT_MKAOS_HANDLER,
            "source-abstraction:{project_id}",
            [
                "mkaos.knowledge.extract",
                "mkaos.rule.extract",
                "mkaos.template.extract",
            ],
        ),
        (
            SOURCE_IMPORT_REPROCESSING_OPERATION,
            SOURCE_IMPORT_REPROCESSING_HANDLER,
            "source-reprocessing:{project_id}",
            [
                "deconstruction.observe",
                "mkaos.knowledge.extract",
                "mkaos.rule.extract",
                "mkaos.template.extract",
            ],
        ),
    )
    return tuple(
        {
            **common,
            "name": name,
            "handler_key": handler,
            "handler_contract_version": (
                "source-import-deconstruction-handler-v2"
                if name == SOURCE_IMPORT_DECONSTRUCTION_OPERATION
                else "source-import-profile-handler-v2"
                if name == SOURCE_IMPORT_PROFILING_OPERATION
                else "source-import-analysis-plan-handler-v2"
                if name == SOURCE_IMPORT_ANALYSIS_PLANNING_OPERATION
                else "source-import-handler-v1"
            ),
            "concurrency_key_template": concurrency,
            "external_capabilities": capabilities,
            "timeout_policy": {
                "operation_timeout_seconds": (
                    SOURCE_IMPORT_PROFILING_QUEUE_TIMEOUT_SECONDS
                    if name == SOURCE_IMPORT_PROFILING_OPERATION
                    else SOURCE_IMPORT_OPERATION_TIMEOUT_SECONDS
                )
            },
        }
        for name, handler, concurrency, capabilities in rows
    )


__all__ = [
    "SOURCE_IMPORT_DECONSTRUCTION_OPERATION",
    "SOURCE_IMPORT_DEFINITION_VERSION",
    "SOURCE_IMPORT_DISCOVERY_OPERATION",
    "SOURCE_IMPORT_FILE_OPERATION",
    "SOURCE_IMPORT_WORK_OPERATION",
    "SOURCE_IMPORT_PROFILING_OPERATION",
    "SOURCE_IMPORT_PROFILING_QUEUE_TIMEOUT_SECONDS",
    "SOURCE_IMPORT_OPERATION_TIMEOUT_SECONDS",
    "SOURCE_IMPORT_ANALYSIS_PLANNING_OPERATION",
    "SOURCE_IMPORT_MKAOS_OPERATION",
    "SOURCE_IMPORT_OPERATIONS",
    "SOURCE_IMPORT_REPROCESSING_OPERATION",
    "source_import_definitions",
]
