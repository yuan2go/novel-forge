from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.schemas import (
    FeedbackBackflowPlan,
    FeedbackCluster,
    FeedbackKGPatch,
    PlanAdjustmentProposal,
    ReviewRuleUpdateProposal,
    validate_common_fields,
)
from novel_forge.storage.local import LocalStorage


def create_feedback_backflow_plan(
    storage: LocalStorage,
    *,
    feedback_paths: list[str | Path] | None = None,
    project_id: str | None = None,
    workspace_path: str | None = None,
    require_human_gate: bool = True,
) -> dict[str, Any]:
    storage.ensure_layout()
    rows = _feedback_rows(storage, feedback_paths or [], project_id=project_id, workspace_path=workspace_path)
    clusters = _clusters_from_rows(rows)
    with AgentExecutionContext(
        storage,
        agent_key="feedback",
        operation="create-feedback-backflow-plan",
        output_types=["feedback_backflow_plan", "feedback_cluster", "plan_adjustment_proposal", "review_rule_update_proposal", "feedback_kg_patch"],
        workspace_path=workspace_path,
        sla_seconds=600,
    ) as run:
        run.guard("create_feedback_backflow_plan")
        cluster_assets = [_write_cluster(storage, cluster, project_id=project_id or "", workspace_path=workspace_path or "") for cluster in clusters]
        proposal_assets: list[dict[str, Any]] = []
        for cluster, cluster_asset in zip(clusters, cluster_assets):
            proposal_assets.extend(_write_proposals(storage, cluster, cluster_asset["path"], project_id=project_id or "", workspace_path=workspace_path or "", require_human_gate=require_human_gate))
        plan_id = make_id("feedback_backflow_plan", project_id or workspace_path or "global")
        human_gate = {"required": require_human_gate, "status": "waiting" if require_human_gate else "not_required"}
        asset = FeedbackBackflowPlan(
            title="Feedback backflow plan",
            source=project_id or workspace_path or "",
            tags=["feedback-backflow", "human-gated" if require_human_gate else "auto-review"],
            content={
                "plan_id": plan_id,
                "project_id": project_id or "",
                "workspace_path": workspace_path or "",
                "clusters": [_asset_ref(item) for item in cluster_assets],
                "proposals": [_asset_ref(item) for item in proposal_assets],
                "human_gate": human_gate,
                "status": "waiting_human" if require_human_gate and proposal_assets else "ready",
                "created_at": utc_now(),
            },
            metadata={"project_id": project_id or "", "workspace_path": workspace_path or ""},
            references=filter_project_safe_references(storage, project_id or "", _dedupe([*[str(path) for path in feedback_paths or []], *[item["path"] for item in cluster_assets], *[item["path"] for item in proposal_assets]])),
        )
        result = _write(storage, asset)
        run.succeed(output_assets=[result["path"], *[item["path"] for item in cluster_assets], *[item["path"] for item in proposal_assets]], token_used=len(rows))
        return {"path": result["path"], "asset": result["asset"], "clusters": cluster_assets, "proposals": proposal_assets}


def apply_feedback_backflow_plan(
    storage: LocalStorage,
    *,
    plan_path: str | Path,
    confirmed: bool = False,
    note: str = "",
) -> dict[str, Any]:
    plan_resolved = resolve_path(storage.root, plan_path)
    data = storage.read_json(plan_resolved)
    if not isinstance(data, dict) or data.get("type") != "feedback_backflow_plan":
        raise ValueError(f"plan_path must point to feedback_backflow_plan: {plan_path}")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    human_gate = content.get("human_gate", {}) if isinstance(content.get("human_gate", {}), dict) else {}
    if human_gate.get("required") and not confirmed:
        return {
            "status": "waiting_human",
            "plan_path": _display_path(storage.root, plan_resolved),
            "message": "feedback backflow plan requires human confirmation before mutating chapter plans, review rules, or KG",
        }
    content["status"] = "approved"
    human_gate["status"] = "approved"
    human_gate["note"] = note
    human_gate["confirmed_at"] = utc_now()
    content["human_gate"] = human_gate
    content["applied_at"] = utc_now()
    data["content"] = content
    data["updated_at"] = utc_now()
    data["tags"] = _dedupe([*[str(tag) for tag in data.get("tags", [])], "approved"])
    storage.write_json(plan_resolved, data)
    return {"status": "approved", "plan_path": _display_path(storage.root, plan_resolved), "message": "proposals approved; downstream workflow apply nodes can create new plan/rule/KG versions"}


def _feedback_rows(storage: LocalStorage, paths: list[str | Path], *, project_id: str | None, workspace_path: str | None) -> list[dict[str, Any]]:
    candidates = list(paths)
    if not candidates:
        for path in storage.list_json("feedback"):
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if not isinstance(data, dict) or data.get("type") not in {"reader_feedback", "feedback_insight", "reader_sentiment_report"}:
                continue
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            if project_id and str(metadata.get("project_id", "")) != project_id:
                continue
            if workspace_path and str(metadata.get("workspace_path", "")) != workspace_path:
                continue
            candidates.append(_display_path(storage.root, path))
    rows: list[dict[str, Any]] = []
    for item in candidates:
        path = resolve_path(storage.root, item)
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        content = data.get("content", {}) if isinstance(data, dict) and isinstance(data.get("content", {}), dict) else {}
        for row in content.get("rows", []) if isinstance(content.get("rows", []), list) else []:
            if isinstance(row, dict):
                rows.append({**row, "_source_path": _display_path(storage.root, path)})
        for cluster in content.get("clusters", []) if isinstance(content.get("clusters", []), list) else []:
            if isinstance(cluster, dict):
                rows.append({**cluster, "_source_path": _display_path(storage.root, path)})
        signals = content.get("signals", {}) if isinstance(content.get("signals", {}), dict) else {}
        if signals:
            rows.append({"comment": " ".join(str(value) for value in signals.values()), "_source_path": _display_path(storage.root, path)})
    return rows


def _clusters_from_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        text = " ".join(str(row.get(key, "")) for key in ["comment", "text", "message", "issue", "label", "summary"]).lower()
        chapter = row.get("chapter", row.get("chapter_number", ""))
        if any(keyword in text for keyword in ["hook", "钩子", "开头", "结尾", "weak", "弱"]):
            key = "weak_hook"
            action = "adjust_future_chapter_plan"
        elif any(keyword in text for keyword in ["rule", "设定", "confusing", "看不懂", "混乱"]):
            key = "confusing_rule"
            action = "update_review_rule_and_kg"
        elif any(keyword in text for keyword in ["boring", "无聊", "水", "拖沓", "毒"]):
            key = "quality_toxicity"
            action = "create_revision_task"
        else:
            key = "general_feedback"
            action = "monitor"
        bucket = buckets.setdefault(
            key,
            {"cluster_id": make_id("feedback_cluster", key), "signals": [], "target_action": action, "affected_assets": [], "chapters": set(), "source_paths": set()},
        )
        bucket["signals"].append({key: value for key, value in row.items() if not key.startswith("_")})
        if chapter not in {None, ""}:
            bucket["chapters"].add(str(chapter))
        if row.get("_source_path"):
            bucket["source_paths"].add(str(row.get("_source_path")))
    result: list[dict[str, Any]] = []
    for bucket in buckets.values():
        result.append(
            {
                **bucket,
                "chapters": sorted(bucket["chapters"]),
                "source_paths": sorted(bucket["source_paths"]),
                "affected_assets": sorted(bucket["affected_assets"]),
            }
        )
    return result


def _write_cluster(storage: LocalStorage, cluster: dict[str, Any], *, project_id: str, workspace_path: str) -> dict[str, Any]:
    asset = FeedbackCluster(
        title=f"Feedback cluster: {cluster['target_action']}",
        source=",".join(cluster.get("source_paths", [])),
        tags=["feedback-cluster", cluster["target_action"]],
        content={**cluster, "created_at": utc_now()},
        metadata={"project_id": project_id, "workspace_path": workspace_path},
        references=filter_project_safe_references(storage, project_id, cluster.get("source_paths", [])),
    )
    return _write(storage, asset)


def _write_proposals(storage: LocalStorage, cluster: dict[str, Any], cluster_path: str, *, project_id: str, workspace_path: str, require_human_gate: bool) -> list[dict[str, Any]]:
    human_gate = {"required": require_human_gate, "status": "waiting" if require_human_gate else "not_required"}
    rows: list[Any] = []
    cluster_id = str(cluster.get("cluster_id", ""))
    action = str(cluster.get("target_action", ""))
    if action in {"adjust_future_chapter_plan", "create_revision_task"}:
        rows.append(
            PlanAdjustmentProposal(
                title=f"Plan adjustment from feedback: {action}",
                source=cluster_path,
                tags=["plan-adjustment-proposal", action],
                content={
                    "proposal_id": make_id("plan_adjustment", cluster_id),
                    "cluster_id": cluster_id,
                    "target_scope": {"chapters": cluster.get("chapters", []), "scope": "future_chapter_plan"},
                    "proposed_changes": _plan_changes(cluster),
                    "human_gate": human_gate,
                    "status": "waiting_human" if require_human_gate else "ready",
                    "created_at": utc_now(),
                },
                metadata={"project_id": project_id, "workspace_path": workspace_path},
                references=filter_project_safe_references(storage, project_id, [cluster_path]),
            )
        )
    if action in {"update_review_rule_and_kg", "create_revision_task"}:
        rows.append(
            ReviewRuleUpdateProposal(
                title=f"Review rule update from feedback: {action}",
                source=cluster_path,
                tags=["review-rule-update-proposal", action],
                content={
                    "proposal_id": make_id("review_rule_update", cluster_id),
                    "cluster_id": cluster_id,
                    "rule_dimension": "continuity" if action == "update_review_rule_and_kg" else "quality",
                    "proposed_rule": _review_rule(cluster),
                    "human_gate": human_gate,
                    "status": "waiting_human" if require_human_gate else "ready",
                    "created_at": utc_now(),
                },
                metadata={"project_id": project_id, "workspace_path": workspace_path},
                references=filter_project_safe_references(storage, project_id, [cluster_path]),
            )
        )
    if action == "update_review_rule_and_kg":
        rows.append(
            FeedbackKGPatch(
                title="Feedback KG patch proposal",
                source=cluster_path,
                tags=["feedback-kg-patch", "human-gated"],
                content={
                    "patch_id": make_id("feedback_kg_patch", cluster_id),
                    "cluster_id": cluster_id,
                    "kg_targets": {"rules": ["unclear_rule"], "chapters": cluster.get("chapters", [])},
                    "proposed_updates": [{"kind": "rule_clarification", "message": "Clarify confusing rule before next draft/review."}],
                    "human_gate": human_gate,
                    "status": "waiting_human" if require_human_gate else "ready",
                    "created_at": utc_now(),
                },
                metadata={"project_id": project_id, "workspace_path": workspace_path},
                references=filter_project_safe_references(storage, project_id, [cluster_path]),
            )
        )
    return [_write(storage, asset) for asset in rows]


def _plan_changes(cluster: dict[str, Any]) -> list[dict[str, Any]]:
    action = str(cluster.get("target_action", ""))
    if action == "adjust_future_chapter_plan":
        return [{"field": "hook", "change": "strengthen opening or ending hook and make payoff promise explicit"}]
    return [{"field": "revision_priority", "change": "tighten pacing, reduce filler, and raise conflict pressure"}]


def _review_rule(cluster: dict[str, Any]) -> dict[str, Any]:
    if str(cluster.get("target_action", "")) == "update_review_rule_and_kg":
        return {"check": "reader can explain the active world rule in one sentence", "severity": "high", "gate": "continuity"}
    return {"check": "chapter avoids filler and preserves clear pleasure beat", "severity": "medium", "gate": "quality"}


def _write(storage: LocalStorage, asset: Any) -> dict[str, Any]:
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def _asset_ref(result: dict[str, Any]) -> dict[str, str]:
    asset = result.get("asset", {}) if isinstance(result.get("asset", {}), dict) else {}
    return {"path": str(result.get("path", "")), "id": str(asset.get("id", "")), "type": str(asset.get("type", ""))}


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result
