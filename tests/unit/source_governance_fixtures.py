from __future__ import annotations

from typing import Any

from novel_forge.modules.mkaos import create_knowledge_card, create_usage_binding, import_source_document
from novel_forge.modules.source_intake import (
    create_source_policy,
    create_source_risk_report,
    sweep_source_retention_expiry,
    sweep_source_stale_quarantine,
)
from novel_forge.storage.local import LocalStorage


def create_governed_knowledge(
    storage: LocalStorage,
    *,
    project_id: str,
    flow: str,
    concept_name: str,
    core_explanation: str,
    input_role: str,
    workspace_path: str = "",
) -> dict[str, Any]:
    source_ref = f"project-owned-{flow}-{project_id}"
    source = import_source_document(
        storage,
        {
            "project_id": project_id,
            "title": f"Project-owned {flow} governance note",
            "source_uri": source_ref,
            "text": core_explanation,
            "rights": {
                "authorization": "owned",
                "allow_downstream_generation": True,
                "copyright_boundary": "project-owned fixture used only for governance contract tests",
            },
        },
    )
    policy = create_source_policy(storage, {"project_id": project_id, "source_ref": source_ref, "risk_tier": "R0"})
    risk = create_source_risk_report(
        storage,
        {"project_id": project_id, "source_ref": source_ref, "source_policy_path": policy["path"], "risk_tier": "R0"},
    )
    card = create_knowledge_card(
        storage,
        {
            "project_id": project_id,
            "environment": "production",
            "os_envelope": {
                "project_id": project_id,
                "task_type": flow,
                "asset_type": "knowledge_card",
                "actor_type": "unit_test",
                "source": "tests.unit.source_governance_fixtures",
                "trace_id": f"trace-{flow}-knowledge-{project_id}",
                "source_policy": {"raw_source_text_allowed": False, "generation_rag_allowed": True},
                "environment": "production",
            },
            "concept_name": concept_name,
            "core_explanation": core_explanation,
            "source_chunk_ids": [source["chunks"][0]["id"]],
            "source_policy_path": policy["path"],
            "risk_report_path": risk["path"],
            "weight": 1.0,
            "risk_level": "low",
        },
    )
    binding = create_usage_binding(
        storage,
        card["asset"]["id"],
        {"flow": flow, "usage_type": "required", "input_role": input_role, "priority": 10},
    )
    return {"card": card, "binding": binding, "source": source, "policy": policy, "risk": risk}


def record_clean_source_governance_evidence(
    storage: LocalStorage,
    *,
    project_id: str,
    workspace_path: str = "",
) -> None:
    payload = {"project_id": project_id, "workspace_path": workspace_path, "max_assets": 1000}
    stale = sweep_source_stale_quarantine(storage, payload)
    retention = sweep_source_retention_expiry(storage, payload)
    if stale["status"] != "clean" or retention["status"] != "clean":
        raise AssertionError(
            f"production-ready fixture has unresolved source governance: stale={stale['status']} retention={retention['status']}"
        )
