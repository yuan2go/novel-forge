from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path, run_metadata
from novel_forge.modules.mkaos_quality import gate_knowledge_pack
from novel_forge.modules.review_issue import create_review_issue, list_review_issues
from novel_forge.schemas import BaseAsset, validate_common_fields
from novel_forge.storage.local import LocalStorage


DEFAULT_GATE_POLICY = {
    "gate_policy_version": "mkaos-production-gate-v1",
    "flows": {
        "outline": {"require_creative_usability": True, "block_raw_source": True, "block_weak_cards": False},
        "chapter_outline": {"require_creative_usability": True, "block_raw_source": True, "block_exposition_overload": True},
        "prose": {"require_creative_usability": True, "block_raw_source": True, "block_source_text": True, "block_target_text": True, "block_quote_leakage": True, "block_exposition_overload": True, "block_classical_style_overdensity": True},
        "review": {"block_raw_source": True, "require_review_rules": True},
        "revision": {"block_raw_source": True, "require_review_issue_resolution": True},
        "recap": {"block_raw_source": True, "require_lineage": True},
        "publish": {"block_raw_source": True, "block_quote_leakage": True, "require_no_blocking_review_issue": True},
        "feedback": {"require_attribution": True, "require_lineage": True},
    },
}

FORBIDDEN_KEYS = {"raw_text", "clean_text", "source_text", "target_text", "quote", "quotation", "excerpt", "verbatim", "copied_sentence"}
STRICT_FLOWS = {"prose", "review", "revision", "recap", "publish"}
CORE_OPERATION_FLOWS = {
    "analysis": "review",
    "decompose": "review",
    "convert": "review",
    "outline": "outline",
    "chapter_plan": "chapter_outline",
    "draft": "prose",
    "review": "review",
    "revision": "revision",
    "editor_patch": "revision",
    "recap": "recap",
    "publish_gate": "publish",
    "release_package": "publish",
    "feedback_backflow": "feedback",
}


def run_mkaos_production_gate(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    project_id = str(payload.get("project_id") or _project_from_payload(payload) or "local-system")
    flow = _flow(payload)
    policy = _active_policy(storage, project_id)
    flow_policy = policy.get("flows", {}).get(flow, {})
    target = _target_asset(storage, payload)
    context_bundle = _asset_payload(storage, payload.get("context_bundle") or payload.get("context_bundle_path"))
    knowledge_pack = _knowledge_pack_payload(storage, payload, context_bundle)
    environment = str(payload.get("environment") or "").strip().lower()
    strict_env = environment in {"production", "strict", "operating_system"}
    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    forbidden_hits = _forbidden_hits({"target": target, "context_bundle": context_bundle, "knowledge_pack": knowledge_pack})
    if forbidden_hits:
        issues.append({"issue_type": "source_leakage", "severity": "critical", "blocking": strict_env, "message": "MKAOS production gate found forbidden source text fields", "forbidden_fields": forbidden_hits})
    normalized_pack = _asset_body(knowledge_pack) if knowledge_pack else {"content": {"pack_items": []}}
    pack_gate = gate_knowledge_pack(storage, {"project_id": project_id, "flow": flow, "knowledge_pack": normalized_pack, "environment": "compat"}) if knowledge_pack or flow in STRICT_FLOWS else {"passed": True, "issues": []}
    for issue in pack_gate.get("issues", []):
        row = {**issue, "source_system": "mkaos.production_gate.pack"}
        if not strict_env:
            row["blocking"] = False
            warnings.append({**row, "message": row.get("message", "MKAOS production gate warning")})
        issues.append(row)
    weak_cards = _weak_cards(knowledge_pack)
    if weak_cards and flow_policy.get("require_creative_usability"):
        issues.append({"issue_type": "mkaos_conflict", "severity": "high", "blocking": strict_env and flow in STRICT_FLOWS, "message": "Weak CreativeKnowledgeCard entered production gate", "weak_cards": weak_cards})
    review_rules = _review_rules(knowledge_pack)
    if flow_policy.get("require_review_rules") and not review_rules:
        issues.append({"issue_type": "mkaos_conflict", "severity": "high", "blocking": strict_env, "message": "review flow requires MKAOS review rules"})
    target_id = str((target.get("id") if isinstance(target, dict) else "") or payload.get("target_asset_id") or "")
    context_bundle_id = _asset_id(context_bundle) or str(_content(context_bundle).get("context_bundle_id") or "")
    related_ids = [target_id, context_bundle_id, str(_pack_id(knowledge_pack))]
    blocking_rows = [
        row
        for row in list_review_issues(storage, project_id=project_id, blocking=True, limit=500)
        if str(row.get("content", {}).get("target_asset_id") or "") in set(item for item in related_ids if item)
    ]
    if flow_policy.get("require_no_blocking_review_issue") and blocking_rows:
        issues.append({"issue_type": "mkaos_conflict", "severity": "critical", "blocking": strict_env, "message": "blocking ReviewIssue exists for publish/release target", "review_issue_ids": [row.get("id", "") for row in blocking_rows]})
    if flow_policy.get("require_lineage") and not _lineage_refs(context_bundle, knowledge_pack):
        warning = {"issue_type": "mkaos_conflict", "severity": "medium", "blocking": False, "message": f"{flow} gate has weak lineage coverage"}
        warnings.append(warning)
        if strict_env and flow == "recap":
            issues.append({**warning, "blocking": True, "severity": "high"})
    persisted = _persist_blocking_issues(storage, project_id, issues, target_id=target_id) if strict_env else []
    blocking_count = sum(1 for issue in issues if issue.get("blocking"))
    passed = blocking_count == 0
    recommendation = "continue" if passed else "block" if any(str(issue.get("severity")) == "critical" for issue in issues) else "revise"
    content = {
        "passed": passed,
        "gate_policy_version": policy["gate_policy_version"],
        "flow": flow,
        "target_asset_id": target_id,
        "target_asset_type": str((target.get("type") if isinstance(target, dict) else "") or payload.get("target_asset_type") or ""),
        "context_bundle_id": context_bundle_id,
        "knowledge_pack_id": _pack_id(knowledge_pack),
        "issues": issues,
        "blocking_issue_count": blocking_count,
        "warnings": warnings,
        "source_isolation": {"raw_text_included": False, "clean_text_included": False, "source_text_included": False, "target_text_included": False, "forbidden_field_count": len(forbidden_hits)},
        "quality_scores": {"weak_card_count": len(weak_cards), "review_rule_count": len(review_rules)},
        "review_issue_ids": [row.get("asset", {}).get("id", row.get("id", "")) for row in persisted],
        "recommendation": recommendation,
        "trace_id": str(payload.get("trace_id") or _metadata(context_bundle).get("trace_id") or ""),
        "created_at": utc_now(),
        "source_policy": _source_policy(),
    }
    asset = BaseAsset(
        id=make_id("mkaos_production_gate_report", f"{project_id} {flow} {target_id} {utc_now()}"),
        type="mkaos_production_gate_report",
        title=f"MKAOS production gate {flow}",
        source=target_id or "mkaos-production-gate",
        tags=["mkaos", "production-gate", flow, "passed" if passed else "blocked"],
        content=content,
        metadata={**_meta(project_id, payload), "gate_policy_version": policy["gate_policy_version"], "asset_status": "passed" if passed else "blocked"},
        references=_dedupe([target_id, context_bundle_id, _pack_id(knowledge_pack), *content["review_issue_ids"]]),
    )
    path = _write(storage, asset)
    content["gate_report_path"] = _display_path(storage, path)
    data = storage.read_json(path)
    data["content"] = content
    storage.write_json(path, data)
    if strict_env and not passed:
        raise ValueError(f"MKAOS production gate blocked {flow}: {blocking_count} blocking issue(s)")
    return {"path": _display_path(storage, path), "asset": storage.read_json(path), **content}


def list_gate_reports(storage: LocalStorage, *, project_id: str | None = None, flow: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("runs")):
        if len(rows) >= limit:
            break
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "mkaos_production_gate_report":
            continue
        content = _content(data)
        metadata = _metadata(data)
        if project_id and str(content.get("project_id") or metadata.get("project_id") or "") != project_id:
            continue
        if flow and str(content.get("flow") or "") != flow:
            continue
        rows.append(_row(storage, path, data))
    return rows


def latest_gate_report(storage: LocalStorage, *, project_id: str | None = None, flow: str | None = None) -> dict[str, Any]:
    rows = list_gate_reports(storage, project_id=project_id, flow=flow, limit=1)
    return rows[0] if rows else {"status": "missing", "content": {"passed": False, "recommendation": "run_gate"}}


def mkaos_gate_summary(storage: LocalStorage, *, project_id: str | None = None) -> dict[str, Any]:
    rows = list_gate_reports(storage, project_id=project_id, limit=100)
    latest = rows[0] if rows else {}
    blocking = sum(int(row.get("content", {}).get("blocking_issue_count", 0) or 0) for row in rows)
    return {
        "status": "ready" if rows else "missing",
        "latest_gate_status": "passed" if latest.get("content", {}).get("passed") else "blocked" if latest else "missing",
        "latest_gate_path": latest.get("path", ""),
        "report_count": len(rows),
        "blocking_issue_count": blocking,
        "weak_knowledge_cards": sum(int(row.get("content", {}).get("quality_scores", {}).get("weak_card_count", 0) or 0) for row in rows),
        "leakage_risk": any(row.get("content", {}).get("source_isolation", {}).get("forbidden_field_count", 0) for row in rows),
        "lineage_coverage": "present" if any(row.get("content", {}).get("context_bundle_id") for row in rows) else "weak",
        "recommendation": latest.get("content", {}).get("recommendation", "run_gate"),
    }


def build_gate_coverage_report(storage: LocalStorage, *, project_id: str | None = None, persist: bool = True) -> dict[str, Any]:
    """Report whether core production operations are covered by ContextBuilder + MKAOS gate.

    This is intentionally evidence-based: the report does not claim a route is
    migrated because code exists; it records observed ContextBundle and gate
    artifacts, then marks operations without evidence as compat gaps.
    """

    pid = project_id or ""
    context_by_flow: dict[str, list[dict[str, str]]] = {flow: [] for flow in set(CORE_OPERATION_FLOWS.values())}
    for path in reversed(storage.list_json("contexts")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "context_bundle":
            continue
        content = _content(data)
        metadata = _metadata(data)
        row_project = str(content.get("project_id") or metadata.get("project_id") or "")
        if pid and row_project and row_project != pid:
            continue
        flow = _flow({"flow": content.get("mkaos_flow") or metadata.get("mkaos_flow") or content.get("task_type") or metadata.get("task_type")})
        context_by_flow.setdefault(flow, []).append({"id": str(data.get("id") or ""), "path": _display_path(storage, path)})

    gate_by_flow: dict[str, list[dict[str, Any]]] = {flow: [] for flow in set(CORE_OPERATION_FLOWS.values())}
    for row in list_gate_reports(storage, project_id=pid or None, limit=1000):
        flow = _flow({"flow": row.get("content", {}).get("flow")})
        gate_by_flow.setdefault(flow, []).append(row)

    operations: list[dict[str, Any]] = []
    for operation, flow in CORE_OPERATION_FLOWS.items():
        contexts = context_by_flow.get(flow, [])
        gates = gate_by_flow.get(flow, [])
        critical = flow in STRICT_FLOWS
        status = "covered" if contexts and gates else "gate_only" if gates else "context_only" if contexts else "compat_gap"
        bypass = status != "covered"
        operations.append(
            {
                "operation": operation,
                "flow": flow,
                "critical": critical,
                "status": status,
                "context_bundle_count": len(contexts),
                "gate_report_count": len(gates),
                "latest_context_bundle_id": contexts[0]["id"] if contexts else "",
                "latest_gate_report_path": gates[0].get("path", "") if gates else "",
                "production_enforced": critical and status == "covered",
                "bypass_allowed": bypass,
                "recommendation": "route through build_flow_context_bundle" if bypass else "covered",
            }
        )
    missing = [row for row in operations if row["status"] != "covered"]
    report = {
        "coverage_report_id": make_id("mkaos_gate_coverage_report", f"{pid or 'all'} {utc_now()}"),
        "project_id": pid,
        "operation_count": len(operations),
        "covered_count": sum(1 for row in operations if row["status"] == "covered"),
        "compat_gap_count": len(missing),
        "operations": operations,
        "forbidden_bypass_operations": [row["operation"] for row in operations if row["critical"] and row["status"] != "covered"],
        "source_isolation": {"raw_text_included": False, "source_text_included": False, "target_text_included": False},
        "generated_at": utc_now(),
    }
    if persist:
        asset = BaseAsset(
            id=report["coverage_report_id"],
            type="mkaos_gate_coverage_report",
            title="MKAOS production gate coverage report",
            source="mkaos-production-gate",
            tags=["mkaos", "production-gate", "coverage"],
            content=report,
            metadata={**_meta(pid or "local-system", {}), "project_id": pid},
            references=_dedupe([row["latest_gate_report_path"] for row in operations if row["latest_gate_report_path"]]),
        )
        path = _write(storage, asset)
        report["path"] = _display_path(storage, path)
    return report


def upsert_gate_policy(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "local-system")
    content = {"project_id": project_id, **DEFAULT_GATE_POLICY, **(payload.get("policy") if isinstance(payload.get("policy"), dict) else {})}
    asset = BaseAsset(
        id=make_id("mkaos_production_gate_policy", project_id),
        type="mkaos_production_gate_policy",
        title=f"MKAOS production gate policy {project_id}",
        source="mkaos-production-gate",
        tags=["mkaos", "production-gate", "policy"],
        content=content,
        metadata=_meta(project_id, payload),
    )
    path = _write(storage, asset)
    return {"path": _display_path(storage, path), "asset": storage.read_json(path), "policy": content}


def _active_policy(storage: LocalStorage, project_id: str) -> dict[str, Any]:
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if isinstance(data, dict) and data.get("type") == "mkaos_production_gate_policy" and str(_content(data).get("project_id") or "") == project_id:
            return _content(data)
    return DEFAULT_GATE_POLICY


def _target_asset(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("target_asset"), dict):
        return payload["target_asset"]
    ref = str(payload.get("target_asset_path") or "")
    if ref:
        return storage.read_json(resolve_path(storage.root, ref))
    return {"id": str(payload.get("target_asset_id") or ""), "type": str(payload.get("target_asset_type") or ""), "content": payload.get("target_content") if isinstance(payload.get("target_content"), dict) else {}}


def _asset_payload(storage: LocalStorage, value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value.get("asset", value) if isinstance(value.get("asset", value), dict) else {}
    if value:
        return storage.read_json(resolve_path(storage.root, str(value)))
    return {}


def _knowledge_pack_payload(storage: LocalStorage, payload: dict[str, Any], context_bundle: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("knowledge_pack"), dict):
        return payload["knowledge_pack"]
    if payload.get("knowledge_pack_path"):
        return storage.read_json(resolve_path(storage.root, str(payload.get("knowledge_pack_path"))))
    content = _content(context_bundle)
    pack = content.get("mkaos_pack") or content.get("mkaos_knowledge_pack") or {}
    return pack if isinstance(pack, dict) else {}


def _forbidden_hits(value: Any, prefix: str = "") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if str(key) in FORBIDDEN_KEYS:
                hits.append(path)
            hits.extend(_forbidden_hits(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            hits.extend(_forbidden_hits(item, f"{prefix}[{index}]"))
    return hits


def _weak_cards(pack: dict[str, Any]) -> list[dict[str, Any]]:
    items = _pack_items(pack)
    weak: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        quality = item.get("quality_dimensions") if isinstance(item.get("quality_dimensions"), dict) else {}
        is_creative = (
            str(item.get("knowledge_subtype") or "") == "creative_knowledge_card"
            or "creative_principle" in item
            or "creative_usability_score" in item
            or "creative_usability_score" in quality
        )
        if not is_creative:
            continue
        score = float(item.get("creative_usability_score", quality.get("creative_usability_score", item.get("quality_score", 0.8))) or 0.8)
        if score < 0.7:
            weak.append({"knowledge_id": item.get("knowledge_id") or item.get("id") or "", "creative_usability_score": score})
    return weak


def _review_rules(pack: dict[str, Any]) -> list[Any]:
    content = _content(pack)
    rules = content.get("review_rules")
    return rules if isinstance(rules, list) else []


def _pack_items(pack: dict[str, Any]) -> list[Any]:
    content = _content(pack)
    for key in ["pack_items", "items", "selected_items"]:
        if isinstance(content.get(key), list):
            return content[key]
    grouped = content.get("grouped_items") if isinstance(content.get("grouped_items"), dict) else {}
    result: list[Any] = []
    for rows in grouped.values():
        if isinstance(rows, list):
            result.extend(rows)
    return result


def _lineage_refs(context_bundle: dict[str, Any], knowledge_pack: dict[str, Any]) -> list[str]:
    return _dedupe([*_strings(_content(context_bundle).get("evidence_refs")), *_strings(_content(knowledge_pack).get("evidence_refs")), *_strings(_content(knowledge_pack).get("source_asset_ids"))])


def _persist_blocking_issues(storage: LocalStorage, project_id: str, issues: list[dict[str, Any]], *, target_id: str) -> list[dict[str, Any]]:
    rows = []
    for issue in issues:
        if not issue.get("blocking"):
            continue
        rows.append(create_review_issue(storage, {"project_id": project_id, "issue_type": issue.get("issue_type", "mkaos_conflict"), "severity": issue.get("severity", "high"), "blocking": True, "message": issue.get("message", "MKAOS production gate issue"), "target_asset_id": target_id or project_id, "target_asset_type": "mkaos_production_target", "source_system": "mkaos.production_gate", "source_issue": issue, "evidence_refs": _strings(issue.get("evidence_refs"))}))
    return rows


def _flow(payload: dict[str, Any]) -> str:
    flow = str(payload.get("flow") or payload.get("mkaos_flow") or payload.get("task_type") or "prose")
    return "publish" if flow == "publish_gate" else "chapter_outline" if flow == "chapter_plan" else "prose" if flow == "draft" else "feedback" if flow == "feedback_backflow" else flow


def _pack_id(pack: dict[str, Any]) -> str:
    return _asset_id(pack) or str(_content(pack).get("pack_id") or _content(pack).get("knowledge_pack_id") or "")


def _project_from_payload(payload: dict[str, Any]) -> str:
    for key in ["target_asset", "context_bundle", "knowledge_pack"]:
        value = payload.get(key)
        if isinstance(value, dict):
            metadata = _metadata(value)
            content = _content(value)
            if metadata.get("project_id") or content.get("project_id"):
                return str(metadata.get("project_id") or content.get("project_id") or "")
    return ""


def _content(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    if isinstance(data.get("asset"), dict):
        return _content(data["asset"])
    if isinstance(data.get("content"), dict):
        return data["content"]
    return data


def _metadata(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    if isinstance(data.get("asset"), dict):
        return _metadata(data["asset"])
    return data.get("metadata", {}) if isinstance(data.get("metadata"), dict) else {}


def _asset_id(data: dict[str, Any]) -> str:
    if not isinstance(data, dict):
        return ""
    if isinstance(data.get("asset"), dict):
        return _asset_id(data["asset"])
    return str(data.get("id") or "")


def _asset_body(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    if isinstance(data.get("asset"), dict):
        return data["asset"]
    return data


def _source_policy() -> dict[str, bool]:
    return {"raw_source_text_allowed": False, "source_chunk_raw_text_allowed": False, "parallel_pair_text_allowed": False, "generation_rag_allowed": False}


def _meta(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"project_id": project_id, "mkaos": True, "use_in_generation_rag": False, "trace_id": str(payload.get("trace_id") or ""), "os_envelope": payload.get("os_envelope") if isinstance(payload.get("os_envelope"), dict) else {}, "source_policy": _source_policy(), "source_isolation": {"raw_text_included": False}, "run_metadata": run_metadata("mkaos.production_gate", BaseAsset(title="gate", content={}))}


def _write(storage: LocalStorage, asset: BaseAsset) -> Path:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    return storage.write_asset("runs", asset)


def _row(storage: LocalStorage, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    return {"path": _display_path(storage, path), "id": data.get("id", ""), "type": data.get("type", ""), "title": data.get("title", ""), "content": _content(data), "metadata": _metadata(data), "references": data.get("references", []), "asset": data, "updated_at": data.get("updated_at", "")}


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys([str(item) for item in values if str(item).strip()]))


def _display_path(storage: LocalStorage, path: str | Path) -> str:
    p = Path(path)
    return str(p.relative_to(storage.root)) if p.is_absolute() and p.is_relative_to(storage.root) else str(p)
