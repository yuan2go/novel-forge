from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.runtime_ledger import check_budget_policy, record_gate_result, record_model_call_log, record_trace_span
from novel_forge.storage.local import LocalStorage

STRICT_MODES = {"operating_system", "strict", "enforce", "fail_closed"}
COMPAT_MODES = {"", "compat", "compatible", "legacy", "warn"}
POSTFLIGHT_PHASES = {"postflight", "commit", "after", "finish"}


@dataclass(frozen=True)
class OperationPolicy:
    operation: str
    operation_kind: str = "model"
    required_input_types: tuple[str, ...] = ()
    allowed_output_types: tuple[str, ...] = ()
    require_context_bundle: bool = False
    require_kg_context: bool = False
    require_budget_policy: bool = True
    require_trace_span: bool = True
    require_model_call_log: bool = True
    require_cost_ledger_for_cost: bool = True
    required_gates: tuple[str, ...] = ()
    description: str = ""
    test_bypass_allowed: bool = True

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["required_input_types"] = list(self.required_input_types)
        data["allowed_output_types"] = list(self.allowed_output_types)
        data["required_gates"] = list(self.required_gates)
        return data


def _policy(
    operation: str,
    *,
    operation_kind: str = "model",
    required_input_types: tuple[str, ...] = (),
    allowed_output_types: tuple[str, ...] = (),
    require_context_bundle: bool = False,
    require_kg_context: bool = False,
    require_budget_policy: bool = True,
    require_trace_span: bool = True,
    require_model_call_log: bool = True,
    require_cost_ledger_for_cost: bool = True,
    required_gates: tuple[str, ...] = (),
    description: str = "",
) -> OperationPolicy:
    return OperationPolicy(
        operation=operation,
        operation_kind=operation_kind,
        required_input_types=required_input_types,
        allowed_output_types=allowed_output_types,
        require_context_bundle=require_context_bundle,
        require_kg_context=require_kg_context,
        require_budget_policy=require_budget_policy,
        require_trace_span=require_trace_span,
        require_model_call_log=require_model_call_log,
        require_cost_ledger_for_cost=require_cost_ledger_for_cost,
        required_gates=required_gates,
        description=description,
    )


OPERATION_POLICIES: dict[str, OperationPolicy] = {
    "draft": _policy(
        "draft",
        required_input_types=("chapter_plan",),
        allowed_output_types=("draft_chapter", "draft_version"),
        require_context_bundle=True,
        require_kg_context=True,
        required_gates=("runtime_policy", "kg", "review"),
        description="Generate draft prose from a chapter plan and context bundle.",
    ),
    "draft_chapter": _policy(
        "draft_chapter",
        required_input_types=("chapter_plan",),
        allowed_output_types=("draft_chapter", "draft_version"),
        require_context_bundle=True,
        require_kg_context=True,
        required_gates=("runtime_policy", "kg", "review"),
        description="Generate draft prose for a chapter.",
    ),
    "generate_draft": _policy(
        "generate_draft",
        required_input_types=("chapter_plan",),
        allowed_output_types=("draft_chapter", "draft_version"),
        require_context_bundle=True,
        require_kg_context=True,
        required_gates=("runtime_policy", "kg", "review"),
        description="Generate a draft candidate.",
    ),
    "review": _policy(
        "review",
        required_input_types=("draft_chapter", "draft_version"),
        allowed_output_types=("review_report", "chapter_audit_report"),
        require_context_bundle=True,
        require_kg_context=True,
        required_gates=("runtime_policy", "review"),
        description="Run model-assisted review against quality, originality, continuity, and platform gates.",
    ),
    "revise": _policy(
        "revise",
        required_input_types=("draft_chapter", "review_report"),
        allowed_output_types=("revision_plan", "draft_version"),
        require_context_bundle=True,
        require_kg_context=True,
        required_gates=("runtime_policy", "review_rework"),
        description="Revise a draft from review findings.",
    ),
    "editor_patch": _policy(
        "editor_patch",
        required_input_types=("draft_chapter", "review_report"),
        allowed_output_types=("editor_patch", "draft_version"),
        require_context_bundle=True,
        require_kg_context=True,
        required_gates=("runtime_policy", "review_rework"),
        description="Create or apply a controlled editor patch.",
    ),
    "review_rework_loop": _policy(
        "review_rework_loop",
        operation_kind="mutation",
        required_input_types=("review_report", "draft_chapter"),
        allowed_output_types=("revision_task", "editor_patch", "draft_version", "review_report", "publish_gate_report"),
        require_context_bundle=False,
        required_gates=("runtime_policy", "review_rework", "publish"),
        description="Close the review issue -> revision task -> editor patch -> version -> re-review -> publish gate loop.",
    ),
    "analysis_run": _policy(
        "analysis_run",
        required_input_types=("source_document", "cleaned_text"),
        allowed_output_types=("web_fiction_business_analysis_report", "published_fiction_analysis_report", "classic_literary_analysis_report"),
        require_context_bundle=False,
        required_gates=("runtime_policy", "originality"),
        description="Run abstract craft or market analysis from source assets.",
    ),
    "analysis_convert": _policy(
        "analysis_convert",
        operation_kind="mutation",
        required_input_types=("analysis_conversion_report",),
        allowed_output_types=("knowledge_card", "material_card", "writing_template", "review_rule_pack"),
        require_context_bundle=False,
        required_gates=("runtime_policy", "originality"),
        description="Convert approved abstract analysis into reusable assets.",
    ),
    "model_benchmark": _policy(
        "model_benchmark",
        required_input_types=("model_benchmark_task",),
        allowed_output_types=("model_benchmark_run", "model_comparison_report"),
        require_context_bundle=False,
        required_gates=("runtime_policy",),
        description="Evaluate a provider/model candidate for routing.",
    ),
    "semantic_kg_extract": _policy(
        "semantic_kg_extract",
        required_input_types=("draft_chapter", "chapter_plan", "review_report"),
        allowed_output_types=("novel_kg_snapshot", "canon_patch"),
        require_context_bundle=False,
        required_gates=("runtime_policy", "kg"),
        description="Extract semantic KG entities, relations, events, rules, and evidence.",
    ),
    "feedback_cluster": _policy(
        "feedback_cluster",
        required_input_types=("reader_feedback",),
        allowed_output_types=("feedback_insight", "reader_sentiment_report"),
        require_context_bundle=False,
        required_gates=("runtime_policy", "feedback"),
        description="Cluster reader feedback into planning and review signals.",
    ),
}

for _alias, _target in {
    "generate-review": "review",
    "revision": "revise",
    "rework": "review_rework_loop",
    "benchmark": "model_benchmark",
    "kg_extract": "semantic_kg_extract",
}.items():
    OPERATION_POLICIES[_alias] = OPERATION_POLICIES[_target]

MODEL_PRODUCING_OPERATIONS = frozenset(
    operation
    for operation, policy in OPERATION_POLICIES.items()
    if policy.operation_kind in {"model", "mutation"} and policy.require_model_call_log
)


@dataclass
class RuntimeExecutionContext:
    storage: LocalStorage
    project_id: str = ""
    workspace_path: str = ""
    operation: str = ""
    operation_kind: str = ""
    input_assets: list[str | Path] = field(default_factory=list)
    output_assets: list[str | Path] = field(default_factory=list)
    context_bundle_path: str = ""
    runtime_policy: dict[str, Any] = field(default_factory=dict)
    trace: dict[str, Any] = field(default_factory=dict)
    mode: str = ""
    phase: str = "preflight"


class RuntimePolicyEnvelope:
    """Fail-closed runtime wrapper for model-producing operations.

    Long-running services can use this object as a context manager and record
    model/gate/output evidence as each phase completes. Commit re-runs the same
    policy checker used by workflow, agent scheduler, API, and CLI paths.
    """

    def __init__(
        self,
        storage: LocalStorage,
        *,
        operation: str,
        project_id: str = "",
        workspace_path: str = "",
        input_assets: list[str | Path] | None = None,
        output_assets: list[str | Path] | None = None,
        context_bundle_path: str = "",
        runtime_policy: dict[str, Any] | None = None,
        trace: dict[str, Any] | None = None,
        mode: str | None = None,
    ) -> None:
        self.storage = storage
        self.operation = operation
        self.project_id = project_id
        self.workspace_path = workspace_path
        self.input_assets = [str(item) for item in input_assets or []]
        self.output_assets = [str(item) for item in output_assets or []]
        self.context_bundle_path = context_bundle_path
        self.runtime_policy = runtime_policy or {}
        self.trace = _trace_payload(trace, operation=operation)
        self.mode = mode
        self.preflight_result: dict[str, Any] = {}
        self.commit_result: dict[str, Any] = {}
        self.model_call_log_path = ""
        self.cost_ledger_paths: list[str] = []
        self.gate_result_paths: list[str] = []
        self.token_used = 0
        self.cost_estimate = 0.0
        self._committed = False

    def __enter__(self) -> "RuntimePolicyEnvelope":
        self.preflight_result = begin_runtime_execution(
            self.storage,
            operation=self.operation,
            project_id=self.project_id,
            workspace_path=self.workspace_path,
            input_assets=self.input_assets,
            output_assets=self.output_assets,
            context_bundle_path=self.context_bundle_path,
            runtime_policy=self.runtime_policy,
            trace=self.trace,
            mode=self.mode,
        )
        if self.preflight_result.get("status") == "blocked":
            raise RuntimeError("; ".join(self.preflight_result.get("failures", [])) or "runtime policy preflight blocked")
        return self

    def __exit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> bool:
        if exc is not None:
            fail_runtime_execution(
                self.storage,
                operation=self.operation,
                error=str(exc),
                trace=self.trace,
                project_id=self.project_id,
                workspace_path=self.workspace_path,
                target_paths=[*self.input_assets, *self.output_assets],
            )
            return False
        if not self._committed:
            self.commit()
        return False

    def add_output_asset(self, path: str | Path) -> None:
        value = str(path)
        if value and value not in self.output_assets:
            self.output_assets.append(value)

    def add_gate_result(self, gate: dict[str, Any] | str | Path) -> None:
        path = str(gate)
        if isinstance(gate, dict):
            path = str(gate.get("path") or gate.get("asset", {}).get("path") or "")
        if path and path not in self.gate_result_paths:
            self.gate_result_paths.append(path)

    def record_model_result(
        self,
        *,
        provider: str,
        model: str,
        status: str = "succeeded",
        usage: dict[str, Any] | None = None,
        cost: dict[str, Any] | None = None,
        source_id: str = "",
        prompt_version: str = "",
    ) -> dict[str, Any]:
        usage_payload = usage or {}
        cost_payload = cost or {"amount": 0.0, "currency": "USD", "source": "runtime_policy_envelope"}
        self.token_used = int(usage_payload.get("total_tokens", 0) or usage_payload.get("input_tokens", 0) or 0)
        self.cost_estimate = float(cost_payload.get("amount", 0.0) or 0.0)
        model_call = record_runtime_model_result(
            self.storage,
            operation=self.operation,
            provider=provider,
            model=model,
            status=status,
            usage=usage_payload,
            cost={**cost_payload, "source": cost_payload.get("source") or "runtime_policy_envelope"},
            trace={**self.trace, "runtime_policy_envelope": True},
            project_id=self.project_id,
            workspace_path=self.workspace_path,
            source_id=source_id,
            prompt_version=prompt_version,
        )
        self.model_call_log_path = str(model_call.get("path", ""))
        ledger = model_call.get("cost_ledger", {})
        if isinstance(ledger, dict) and ledger.get("path"):
            self.cost_ledger_paths.append(str(ledger["path"]))
        return model_call

    def commit(self, *, token_used: int | None = None, cost_estimate: float | None = None) -> dict[str, Any]:
        self.commit_result = commit_runtime_outputs(
            self.storage,
            operation=self.operation,
            project_id=self.project_id,
            workspace_path=self.workspace_path,
            input_assets=self.input_assets,
            output_assets=self.output_assets,
            context_bundle_path=self.context_bundle_path,
            model_call_log_path=self.model_call_log_path,
            cost_ledger_paths=self.cost_ledger_paths,
            gate_result_paths=self.gate_result_paths,
            token_used=self.token_used if token_used is None else token_used,
            cost_estimate=self.cost_estimate if cost_estimate is None else cost_estimate,
            trace=self.trace,
            mode=self.mode,
        )
        self._committed = True
        if self.commit_result.get("status") == "blocked":
            raise RuntimeError("; ".join(self.commit_result.get("failures", [])) or "runtime policy commit blocked")
        return self.commit_result


def runtime_policy_envelope(storage: LocalStorage, **kwargs: Any) -> RuntimePolicyEnvelope:
    return RuntimePolicyEnvelope(storage, **kwargs)


def runtime_policy_mode(mode: str | None = None) -> str:
    resolved = (mode if mode is not None else os.environ.get("NOVEL_FORGE_RUNTIME_POLICY_MODE", "compat")).strip().lower()
    if resolved in COMPAT_MODES:
        return "compat"
    if resolved in STRICT_MODES:
        return "operating_system"
    return resolved


def runtime_policy_status(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    workspace_path: str | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    storage.ensure_layout()
    resolved_mode = runtime_policy_mode(mode)
    policies = _unique_policies()
    active_budget_policies = _active_budget_policies(storage, project_id=project_id, workspace_path=workspace_path)
    recent_model_calls = _count_assets(storage, "model_call_log", project_id=project_id, workspace_path=workspace_path)
    recent_cost_ledgers = _count_assets(storage, "cost_ledger", project_id=project_id, workspace_path=workspace_path)
    recent_gate_results = _count_assets(storage, "gate_result", project_id=project_id, workspace_path=workspace_path)
    recent_trace_spans = _count_assets(storage, "trace_span", project_id=project_id, workspace_path=workspace_path)
    return {
        "mode": resolved_mode,
        "strict": resolved_mode in STRICT_MODES or resolved_mode == "operating_system",
        "project_id": project_id or "",
        "workspace_path": workspace_path or "",
        "operation_count": len(policies),
        "model_producing_operations": sorted(MODEL_PRODUCING_OPERATIONS),
        "operations": [policy.to_dict() for policy in sorted(policies.values(), key=lambda item: item.operation)],
        "evidence_counts": {
            "active_budget_policy": len(active_budget_policies),
            "trace_span": recent_trace_spans,
            "gate_result": recent_gate_results,
            "model_call_log": recent_model_calls,
            "cost_ledger": recent_cost_ledgers,
        },
        "recommendations": _status_recommendations(resolved_mode, active_budget_policies),
    }


def runtime_policy_enforcement_report(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    workspace_path: str | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    storage.ensure_layout()
    resolved_mode = runtime_policy_mode(mode)
    policies = _unique_policies()
    model_calls = _assets_by_type(storage, "model_call_log", project_id=project_id, workspace_path=workspace_path)
    gates = _assets_by_type(storage, "gate_result", project_id=project_id, workspace_path=workspace_path)
    ledgers = _assets_by_type(storage, "cost_ledger", project_id=project_id, workspace_path=workspace_path)
    trace_spans = _assets_by_type(storage, "trace_span", project_id=project_id, workspace_path=workspace_path)
    calls_by_operation: dict[str, list[dict[str, Any]]] = {}
    for row in model_calls:
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        operation = _normalize_operation(str(content.get("operation", "")))
        calls_by_operation.setdefault(operation, []).append(row)
    gate_by_kind: dict[str, int] = {}
    for row in gates:
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        kind = str(content.get("gate_kind", ""))
        gate_by_kind[kind] = gate_by_kind.get(kind, 0) + 1
    rows: list[dict[str, Any]] = []
    uncovered: list[str] = []
    for operation, policy in sorted(policies.items()):
        operation_calls = calls_by_operation.get(operation, [])
        cost_count = _cost_count_for_operation(ledgers, operation)
        required_gate_counts = {kind: gate_by_kind.get(kind, 0) for kind in policy.required_gates if kind != "runtime_policy"}
        coverage_status = "covered"
        issues: list[str] = []
        if policy.require_model_call_log and not operation_calls:
            coverage_status = "missing_runtime_evidence"
            issues.append("no model_call_log recorded for operation")
        if policy.require_cost_ledger_for_cost and operation_calls and not cost_count:
            issues.append("no cost_ledger recorded for operation calls with cost evidence")
        if policy.required_gates and any(count <= 0 for count in required_gate_counts.values()):
            issues.append("one or more required gate kinds have no recorded evidence")
        if issues:
            uncovered.append(operation)
        rows.append(
            {
                "operation": operation,
                "operation_kind": policy.operation_kind,
                "status": coverage_status if issues else "covered",
                "model_call_count": len(operation_calls),
                "cost_ledger_count": cost_count,
                "required_gate_counts": required_gate_counts,
                "requires_context_bundle": policy.require_context_bundle,
                "requires_kg_context": policy.require_kg_context,
                "issues": issues,
            }
        )
    return {
        "mode": resolved_mode,
        "strict": resolved_mode == "operating_system",
        "project_id": project_id or "",
        "workspace_path": workspace_path or "",
        "summary": {
            "operation_count": len(rows),
            "covered_operation_count": len([row for row in rows if row["status"] == "covered"]),
            "uncovered_operation_count": len(uncovered),
            "model_call_log_count": len(model_calls),
            "cost_ledger_count": len(ledgers),
            "gate_result_count": len(gates),
            "trace_span_count": len(trace_spans),
        },
        "operations": rows,
        "uncovered_operations": uncovered,
        "recommendations": _enforcement_recommendations(uncovered, resolved_mode),
    }


def runtime_policy_legacy_entrypoint_audit(*, repo_root: str | Path | None = None) -> dict[str, Any]:
    """Static audit for model-producing paths that may bypass the OS envelope.

    This is intentionally conservative. It does not prove safety; it gives the
    operator a durable checklist of old CLI/API/service paths that call model
    adapters directly and should be routed through RuntimePolicyEnvelope or the
    Agent Scheduler before being promoted to strict OS mode.
    """

    root = Path(repo_root).resolve() if repo_root else Path(__file__).resolve().parents[4]
    source_roots = [root / "src" / "novel_forge", root / "tests"]
    call_patterns = [".generate(", ".review(", ".revise(", ".analyze(", ".batch(", "get_model_adapter", "get_adapter("]
    coverage_markers = [
        "RuntimePolicyEnvelope",
        "runtime_policy_envelope",
        "GuardedModelAdapter",
        "AgentOperationRegistry",
        "check_runtime_policy",
        "record_model_call_log",
    ]
    rows: list[dict[str, Any]] = []
    for source_root in source_roots:
        if not source_root.exists():
            continue
        for path in sorted(source_root.rglob("*.py")):
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            if not any(pattern in text for pattern in call_patterns):
                continue
            rel = _display_path(root, path)
            matched_calls = [pattern for pattern in call_patterns if pattern in text]
            matched_markers = [marker for marker in coverage_markers if marker in text]
            status = "covered" if matched_markers else "review_required"
            if "tests/" in rel:
                status = "test_fixture" if not matched_markers else "covered_test"
            rows.append(
                {
                    "path": rel,
                    "status": status,
                    "matched_calls": matched_calls,
                    "coverage_markers": matched_markers,
                    "recommendation": _legacy_entrypoint_recommendation(status),
                }
            )
    review_required = [row for row in rows if row["status"] == "review_required"]
    return {
        "repo_root": str(root),
        "summary": {
            "candidate_count": len(rows),
            "review_required_count": len(review_required),
            "covered_count": len([row for row in rows if row["status"].startswith("covered")]),
            "test_fixture_count": len([row for row in rows if row["status"] == "test_fixture"]),
        },
        "entrypoints": rows,
        "recommendations": [
            "wrap review_required paths with RuntimePolicyEnvelope or route them through Agent Scheduler",
            "keep deterministic tests explicit by setting NOVEL_FORGE_MODEL_PROVIDER=mock",
        ]
        if review_required
        else ["no direct model entrypoints without obvious runtime-policy evidence were found"],
    }


def begin_runtime_execution(
    storage: LocalStorage,
    *,
    operation: str,
    project_id: str = "",
    workspace_path: str = "",
    input_assets: list[str | Path] | None = None,
    output_assets: list[str | Path] | None = None,
    context_bundle_path: str = "",
    runtime_policy: dict[str, Any] | None = None,
    token_used: int = 0,
    cost_estimate: float = 0.0,
    trace: dict[str, Any] | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    trace_payload = _trace_payload(trace, operation=operation)
    if trace_payload.get("trace_id"):
        record_trace_span(
            storage,
            trace_id=str(trace_payload.get("trace_id", "")),
            span_type="runtime_policy",
            name=f"{operation}:preflight",
            status="running",
            parent_span_id=str(trace_payload.get("parent_span_id", "") or trace_payload.get("span_id", "")),
            attributes={"operation": operation, "phase": "preflight"},
            project_id=project_id,
            workspace_path=workspace_path,
        )
    return check_runtime_policy(
        storage,
        operation=operation,
        project_id=project_id,
        workspace_path=workspace_path,
        input_assets=input_assets or [],
        output_assets=output_assets or [],
        context_bundle_path=context_bundle_path,
        runtime_policy=runtime_policy or {},
        token_used=token_used,
        cost_estimate=cost_estimate,
        trace=trace_payload,
        phase="preflight",
        mode=mode,
    )


def record_runtime_model_result(
    storage: LocalStorage,
    *,
    operation: str,
    provider: str,
    model: str,
    status: str = "succeeded",
    usage: dict[str, Any] | None = None,
    cost: dict[str, Any] | None = None,
    trace: dict[str, Any] | None = None,
    project_id: str = "",
    workspace_path: str = "",
    source_id: str = "",
    prompt_version: str = "",
) -> dict[str, Any]:
    return record_model_call_log(
        storage,
        provider=provider,
        model=model,
        operation=operation,
        status=status,
        usage=usage or {},
        cost=cost or {"amount": 0.0, "currency": "USD", "source": "runtime_policy"},
        trace=_trace_payload(trace, operation=operation),
        project_id=project_id,
        workspace_path=workspace_path,
        source_id=source_id,
        prompt_version=prompt_version,
    )


def commit_runtime_outputs(
    storage: LocalStorage,
    *,
    operation: str,
    project_id: str = "",
    workspace_path: str = "",
    input_assets: list[str | Path] | None = None,
    output_assets: list[str | Path] | None = None,
    context_bundle_path: str = "",
    model_call_log_path: str = "",
    cost_ledger_paths: list[str] | None = None,
    gate_result_paths: list[str] | None = None,
    token_used: int = 0,
    cost_estimate: float = 0.0,
    trace: dict[str, Any] | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    return check_runtime_policy(
        storage,
        operation=operation,
        project_id=project_id,
        workspace_path=workspace_path,
        input_assets=input_assets or [],
        output_assets=output_assets or [],
        context_bundle_path=context_bundle_path,
        token_used=token_used,
        cost_estimate=cost_estimate,
        trace=trace,
        phase="commit",
        model_call_log_path=model_call_log_path,
        cost_ledger_paths=cost_ledger_paths or [],
        gate_result_paths=gate_result_paths or [],
        mode=mode,
    )


def fail_runtime_execution(
    storage: LocalStorage,
    *,
    operation: str,
    error: str,
    trace: dict[str, Any] | None = None,
    project_id: str = "",
    workspace_path: str = "",
    target_paths: list[str | Path] | None = None,
) -> dict[str, Any]:
    trace_payload = _trace_payload(trace, operation=operation)
    if trace_payload.get("trace_id"):
        record_trace_span(
            storage,
            trace_id=str(trace_payload.get("trace_id", "")),
            span_type="runtime_policy",
            name=f"{operation}:failed",
            status="failed",
            parent_span_id=str(trace_payload.get("parent_span_id", "") or trace_payload.get("span_id", "")),
            attributes={"operation": operation, "error": error},
            references=[str(item) for item in target_paths or []],
            project_id=project_id,
            workspace_path=workspace_path,
        )
    return record_gate_result(
        storage,
        gate_kind="runtime_policy",
        status="failed",
        target_paths=[str(item) for item in target_paths or []],
        result={"operation": operation, "error": error},
        trace=trace_payload,
        project_id=project_id,
        workspace_path=workspace_path,
        message=error,
        blocking=True,
    )


def check_runtime_policy(
    storage: LocalStorage,
    *,
    operation: str,
    project_id: str = "",
    workspace_path: str = "",
    input_assets: list[str | Path] | None = None,
    output_assets: list[str | Path] | None = None,
    context_bundle_path: str = "",
    runtime_policy: dict[str, Any] | None = None,
    token_used: int = 0,
    cost_estimate: float = 0.0,
    currency: str = "USD",
    trace: dict[str, Any] | None = None,
    phase: str = "postflight",
    mode: str | None = None,
    model_call_log_path: str = "",
    cost_ledger_paths: list[str] | None = None,
    gate_result_paths: list[str] | None = None,
    require_context_bundle: bool | None = None,
    require_budget_policy: bool | None = None,
    require_model_call_log: bool | None = None,
    require_cost_ledger: bool | None = None,
    required_gates: list[str] | None = None,
    persist_gate_result: bool = True,
) -> dict[str, Any]:
    storage.ensure_layout()
    resolved_mode = runtime_policy_mode(mode)
    strict = resolved_mode in STRICT_MODES or resolved_mode == "operating_system"
    normalized_operation = _normalize_operation(operation)
    policy = _operation_policy(normalized_operation, runtime_policy or {})
    postflight = str(phase or "postflight").strip().lower() in POSTFLIGHT_PHASES
    trace_payload = _trace_payload(trace, operation=normalized_operation)
    failures: list[str] = []
    warnings: list[str] = []
    evidence: dict[str, Any] = {}

    input_rows = [_asset_row(storage, item) for item in input_assets or []]
    output_rows = [_asset_row(storage, item) for item in output_assets or []]
    evidence["input_assets"] = input_rows
    evidence["output_assets"] = output_rows

    _check_required_input_types(policy, input_rows, failures, warnings)
    _check_allowed_output_types(policy, output_rows, failures, warnings)

    context_required = _override_bool(require_context_bundle, policy.require_context_bundle)
    if context_required:
        context_check = _typed_path_check(storage, context_bundle_path, expected_type="context_bundle", label="context bundle")
        evidence["context_bundle"] = context_check
        if context_check["status"] != "present":
            failures.append(context_check["message"])
        elif policy.require_kg_context:
            kg_check = _kg_context_check(storage, context_bundle_path)
            evidence["kg_context"] = kg_check
            if kg_check["status"] != "present":
                failures.append(kg_check["message"])
    elif context_bundle_path:
        evidence["context_bundle"] = _typed_path_check(storage, context_bundle_path, expected_type="context_bundle", label="context bundle")

    budget_required = _override_bool(require_budget_policy, policy.require_budget_policy)
    if budget_required or token_used or cost_estimate:
        scope = project_id or "global"
        budget = check_budget_policy(
            storage,
            scope=scope,
            amount=float(cost_estimate or 0.0),
            token_used=int(token_used or 0),
            currency=currency or "USD",
            trace=trace_payload,
            project_id=project_id,
            workspace_path=workspace_path,
        )
        evidence["budget_policy"] = budget
        if budget_required and budget.get("status") == "skipped":
            failures.append(f"missing active budget policy for scope {scope}")
        elif budget.get("status") == "failed":
            failures.append(str(budget.get("message") or "budget policy failed"))

    trace_required = bool(policy.require_trace_span)
    if trace_required:
        if not trace_payload.get("trace_id"):
            failures.append("missing trace_id for runtime policy execution")
        else:
            evidence["trace"] = trace_payload

    model_required = _override_bool(require_model_call_log, policy.require_model_call_log)
    if postflight and model_required:
        model_check = _typed_path_check(storage, model_call_log_path, expected_type="model_call_log", label="model call log")
        evidence["model_call_log"] = model_check
        if model_check["status"] != "present":
            failures.append(model_check["message"])

    cost_required = _override_bool(require_cost_ledger, policy.require_cost_ledger_for_cost and float(cost_estimate or 0.0) > 0)
    if postflight and cost_required:
        ledger_checks = [_typed_path_check(storage, path, expected_type="cost_ledger", label="cost ledger") for path in cost_ledger_paths or []]
        evidence["cost_ledgers"] = ledger_checks
        if not ledger_checks:
            failures.append("missing cost ledger for nonzero runtime cost")
        else:
            missing = [check for check in ledger_checks if check["status"] != "present"]
            if missing:
                failures.extend([check["message"] for check in missing])

    gate_kinds = list(required_gates if required_gates is not None else policy.required_gates)
    if postflight and gate_kinds:
        gate_checks = _gate_evidence_checks(storage, gate_result_paths or [], gate_kinds)
        evidence["gate_results"] = gate_checks
        missing_gates = [item for item in gate_checks if item.get("status") != "present"]
        if missing_gates:
            failures.extend([str(item.get("message")) for item in missing_gates])

    blocking_issues = list(failures)
    if failures and not strict:
        warnings.extend(failures)
        failures = []

    status = "passed"
    if failures:
        status = "blocked"
    elif warnings:
        status = "warning"

    result = {
        "status": status,
        "mode": resolved_mode,
        "strict": strict,
        "phase": "postflight" if postflight else "preflight",
        "operation": normalized_operation,
        "operation_policy": policy.to_dict(),
        "failures": failures,
        "warnings": warnings,
        "blocking_issues": blocking_issues,
        "requirements": _requirements(policy, postflight=postflight, cost_required=cost_required, gate_kinds=gate_kinds),
        "evidence": evidence,
        "recommendation": _policy_recommendation(status, strict, blocking_issues),
    }

    if persist_gate_result:
        gate_status = "failed" if status == "blocked" else ("warning" if status == "warning" else "passed")
        gate = record_gate_result(
            storage,
            gate_kind="runtime_policy",
            status=gate_status,
            target_paths=[str(item) for item in [*(input_assets or []), *(output_assets or [])] if item],
            result={
                "operation": normalized_operation,
                "phase": result["phase"],
                "mode": resolved_mode,
                "failures": failures,
                "warnings": warnings,
                "blocking_issues": blocking_issues,
                "requirements": result["requirements"],
            },
            trace=trace_payload,
            project_id=project_id,
            workspace_path=workspace_path,
            message="; ".join(failures or warnings) if failures or warnings else "runtime policy passed",
            blocking=strict,
        )
        result["gate_result"] = gate

    return result


def _operation_policy(operation: str, overrides: dict[str, Any]) -> OperationPolicy:
    base = OPERATION_POLICIES.get(operation)
    if not base:
        base = OperationPolicy(operation=operation, operation_kind=str(overrides.get("operation_kind") or "mutation"), require_model_call_log=False)
    if not overrides:
        return base
    return OperationPolicy(
        operation=base.operation,
        operation_kind=str(overrides.get("operation_kind", base.operation_kind)),
        required_input_types=tuple(overrides.get("required_input_types", base.required_input_types) or ()),
        allowed_output_types=tuple(overrides.get("allowed_output_types", base.allowed_output_types) or ()),
        require_context_bundle=bool(overrides.get("require_context_bundle", base.require_context_bundle)),
        require_kg_context=bool(overrides.get("require_kg_context", base.require_kg_context)),
        require_budget_policy=bool(overrides.get("require_budget_policy", base.require_budget_policy)),
        require_trace_span=bool(overrides.get("require_trace_span", base.require_trace_span)),
        require_model_call_log=bool(overrides.get("require_model_call_log", base.require_model_call_log)),
        require_cost_ledger_for_cost=bool(overrides.get("require_cost_ledger_for_cost", base.require_cost_ledger_for_cost)),
        required_gates=tuple(overrides.get("required_gates", base.required_gates) or ()),
        description=str(overrides.get("description", base.description)),
        test_bypass_allowed=bool(overrides.get("test_bypass_allowed", base.test_bypass_allowed)),
    )


def _unique_policies() -> dict[str, OperationPolicy]:
    rows: dict[str, OperationPolicy] = {}
    for policy in OPERATION_POLICIES.values():
        rows[policy.operation] = policy
    return rows


def _normalize_operation(operation: str) -> str:
    return str(operation or "").strip().lower().replace(" ", "_").replace("-", "_")


def _override_bool(value: bool | None, default: bool) -> bool:
    return default if value is None else bool(value)


def _trace_payload(trace: dict[str, Any] | None, *, operation: str) -> dict[str, Any]:
    data = dict(trace or {})
    if not data.get("trace_id") and data.get("run_id"):
        data["trace_id"] = data.get("run_id")
    if data.get("trace_id") and not data.get("span_id"):
        data["span_id"] = make_id("span", f"{operation}-{utc_now()}")
    if data.get("trace_id") and not data.get("parent_span_id"):
        data["parent_span_id"] = data.get("trace_id")
    return data


def _asset_row(storage: LocalStorage, path_or_id: str | Path) -> dict[str, Any]:
    path = _resolve_existing_path(storage, path_or_id)
    if not path:
        return {"path": str(path_or_id), "status": "missing", "type": "", "id": ""}
    try:
        data = storage.read_json(path)
    except Exception as exc:
        return {"path": _display_path(storage.root, path), "status": "invalid", "type": "", "id": "", "message": str(exc)}
    return {
        "path": _display_path(storage.root, path),
        "status": "present",
        "type": str(data.get("type", "")) if isinstance(data, dict) else "",
        "id": str(data.get("id", "")) if isinstance(data, dict) else "",
    }


def _typed_path_check(storage: LocalStorage, path_or_id: str | Path, *, expected_type: str, label: str) -> dict[str, Any]:
    if not str(path_or_id or "").strip():
        return {"status": "missing", "path": "", "type": "", "message": f"missing {label}"}
    row = _asset_row(storage, path_or_id)
    if row.get("status") != "present":
        row["message"] = f"missing {label}: {path_or_id}"
        return row
    if expected_type and row.get("type") != expected_type:
        row["status"] = "wrong_type"
        row["message"] = f"{label} must be {expected_type}, got {row.get('type') or 'unknown'}"
        return row
    row["message"] = f"{label} present"
    return row


def _gate_evidence_checks(storage: LocalStorage, gate_result_paths: list[str], required_gates: list[str]) -> list[dict[str, Any]]:
    available: dict[str, dict[str, Any]] = {}
    for path in gate_result_paths:
        check = _typed_path_check(storage, path, expected_type="gate_result", label="gate result")
        if check.get("status") != "present":
            available[str(path)] = check
            continue
        data = storage.read_json(resolve_path(storage.root, path))
        content = data.get("content", {}) if isinstance(data, dict) and isinstance(data.get("content", {}), dict) else {}
        gate_kind = str(content.get("gate_kind", ""))
        gate_status = str(content.get("status", ""))
        check.update({"gate_kind": gate_kind, "gate_status": gate_status})
        available[gate_kind] = check
    rows: list[dict[str, Any]] = []
    for gate_kind in required_gates:
        if gate_kind == "runtime_policy":
            continue
        existing = available.get(gate_kind)
        if not existing:
            rows.append({"status": "missing", "gate_kind": gate_kind, "message": f"missing required gate result: {gate_kind}"})
        elif str(existing.get("gate_status", "")) not in {"passed", "warning", "skipped"}:
            rows.append({"status": "failed", "gate_kind": gate_kind, "message": f"required gate did not pass: {gate_kind}", "evidence": existing})
        else:
            rows.append({"status": "present", "gate_kind": gate_kind, "message": f"required gate present: {gate_kind}", "evidence": existing})
    return rows


def _check_required_input_types(policy: OperationPolicy, input_rows: list[dict[str, Any]], failures: list[str], warnings: list[str]) -> None:
    if not policy.required_input_types:
        return
    available = {str(row.get("type", "")) for row in input_rows if row.get("status") == "present"}
    if not available:
        warnings.append(f"no input assets supplied for operation {policy.operation}; expected one of {', '.join(policy.required_input_types)}")
        return
    if not available.intersection(set(policy.required_input_types)):
        failures.append(f"input assets do not include required types for {policy.operation}: {', '.join(policy.required_input_types)}")


def _check_allowed_output_types(policy: OperationPolicy, output_rows: list[dict[str, Any]], failures: list[str], warnings: list[str]) -> None:
    if not policy.allowed_output_types or not output_rows:
        return
    for row in output_rows:
        if row.get("status") != "present":
            warnings.append(f"output asset not readable yet: {row.get('path')}")
            continue
        if str(row.get("type", "")) not in set(policy.allowed_output_types):
            failures.append(f"output asset type {row.get('type') or 'unknown'} is not allowed for {policy.operation}")


def _requirements(policy: OperationPolicy, *, postflight: bool, cost_required: bool, gate_kinds: list[str]) -> dict[str, Any]:
    return {
        "context_bundle": policy.require_context_bundle,
        "kg_context": policy.require_kg_context,
        "budget_policy": policy.require_budget_policy,
        "trace_span": policy.require_trace_span,
        "model_call_log": bool(postflight and policy.require_model_call_log),
        "cost_ledger": bool(postflight and cost_required),
        "gates": gate_kinds if postflight else [],
    }


def _kg_context_check(storage: LocalStorage, context_bundle_path: str | Path) -> dict[str, Any]:
    row = _typed_path_check(storage, context_bundle_path, expected_type="context_bundle", label="context bundle")
    if row.get("status") != "present":
        return row
    try:
        data = storage.read_json(resolve_path(storage.root, context_bundle_path))
    except Exception as exc:
        return {"status": "invalid", "message": f"context bundle unreadable for KG context: {exc}"}
    content = data.get("content", {}) if isinstance(data, dict) and isinstance(data.get("content", {}), dict) else {}
    kg_context = content.get("kg_context", {})
    items = []
    if isinstance(kg_context, dict):
        items = kg_context.get("items", []) if isinstance(kg_context.get("items", []), list) else []
    elif isinstance(kg_context, list):
        items = kg_context
    selected_assets = content.get("selected_assets", []) if isinstance(content.get("selected_assets", []), list) else []
    kg_selected = [item for item in selected_assets if isinstance(item, dict) and ("novel_kg" in item.get("categories", []) or item.get("ranker") == "novel_kg_context")]
    if items or kg_selected:
        return {"status": "present", "message": "KG-backed context present", "item_count": len(items) + len(kg_selected)}
    return {
        "status": "missing",
        "message": "missing KG-backed context in context bundle",
        "expected": "content.kg_context.items or selected_assets ranked by novel_kg_context",
    }


def _policy_recommendation(status: str, strict: bool, blocking_issues: list[str]) -> str:
    if status == "passed":
        return "runtime policy evidence is sufficient for this phase"
    if strict:
        return "block commit and create missing runtime evidence before retrying"
    if blocking_issues:
        return "compat mode allowed the operation, but OS mode would block until evidence is complete"
    return "review runtime policy warnings before promoting this path to OS mode"


def _status_recommendations(mode: str, active_budget_policies: list[dict[str, Any]]) -> list[str]:
    recommendations: list[str] = []
    if mode != "operating_system":
        recommendations.append("set NOVEL_FORGE_RUNTIME_POLICY_MODE=operating_system for fail-closed OS acceptance")
    if not active_budget_policies:
        recommendations.append("create at least one active budget_policy before strict model-producing work")
    return recommendations


def _enforcement_recommendations(uncovered: list[str], mode: str) -> list[str]:
    recommendations: list[str] = []
    if uncovered:
        recommendations.append("route uncovered model-producing operations through RuntimePolicyEnvelope or AgentExecutionContext")
    if mode != "operating_system":
        recommendations.append("run OS acceptance with NOVEL_FORGE_RUNTIME_POLICY_MODE=operating_system to fail closed")
    if not recommendations:
        recommendations.append("runtime policy evidence covers registered model-producing operations for this scope")
    return recommendations


def _legacy_entrypoint_recommendation(status: str) -> str:
    if status == "review_required":
        return "route this direct model-producing path through RuntimePolicyEnvelope, GuardedModelAdapter, or Agent Scheduler"
    if status == "test_fixture":
        return "keep as deterministic test-only path and force mock provider"
    return "runtime policy marker found; verify end-to-end evidence in OS acceptance"


def _active_budget_policies(storage: LocalStorage, *, project_id: str | None, workspace_path: str | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in storage.list_json("runs"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "budget_policy":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if str(content.get("status", "")) != "active":
            continue
        if project_id and str(metadata.get("project_id", "")) not in {project_id, ""} and str(content.get("scope", "")) != project_id:
            continue
        if workspace_path and str(metadata.get("workspace_path", "")) not in {workspace_path, ""}:
            continue
        rows.append({"path": _display_path(storage.root, path), "scope": content.get("scope", ""), "limits": content.get("limits", {})})
    return rows


def _count_assets(storage: LocalStorage, asset_type: str, *, project_id: str | None, workspace_path: str | None) -> int:
    count = 0
    for path in storage.list_json("runs"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != asset_type:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        if workspace_path and str(metadata.get("workspace_path", "")) != workspace_path:
            continue
        count += 1
    return count


def _assets_by_type(storage: LocalStorage, asset_type: str, *, project_id: str | None, workspace_path: str | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in storage.list_json("runs"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != asset_type:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        if workspace_path and str(metadata.get("workspace_path", "")) != workspace_path:
            continue
        data["_path"] = _display_path(storage.root, path)
        rows.append(data)
    return rows


def _cost_count_for_operation(ledgers: list[dict[str, Any]], operation: str) -> int:
    count = 0
    for row in ledgers:
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        metadata = content.get("metadata", {}) if isinstance(content.get("metadata", {}), dict) else {}
        if _normalize_operation(str(metadata.get("operation", ""))) == operation:
            count += 1
    return count


def _resolve_existing_path(storage: LocalStorage, path_or_id: str | Path) -> Path | None:
    if not str(path_or_id or "").strip():
        return None
    try:
        path = resolve_path(storage.root, path_or_id)
        if path.exists():
            return path
    except Exception:
        pass
    needle = str(path_or_id)
    for category in ("runs", "contexts", "chapter_plans", "drafts", "reviews", "analysis", "feedback", "continuity"):
        for path in storage.list_json(category):
            if path.stem == needle:
                return path
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if isinstance(data, dict) and str(data.get("id", "")) == needle:
                return path
    return None


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)
