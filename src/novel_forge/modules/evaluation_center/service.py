from __future__ import annotations

import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.model_adapters.output_validation import validate_model_output
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.modules.production_execution import (
    CandidateKind,
    DomainExecutionPort,
    execute_domain_candidate,
)
from novel_forge.modules.runtime_policy import provider_hard_stop_evidence_report
from novel_forge.schemas import (
    BaseAsset,
    ModelBenchmarkRun,
    ModelBenchmarkTask,
    ModelComparisonReport,
    ModelProfile,
    ModelRoutingPolicy,
    PromptRegressionReport,
    PromptVersion,
    QualityRubricPack,
    validate_common_fields,
)
from novel_forge.storage.local import LocalStorage

EVALUATION_TYPES = {
    "model_profile",
    "model_benchmark_task",
    "model_benchmark_run",
    "model_comparison_report",
    "model_routing_policy",
    "prompt_version",
    "prompt_regression_report",
    "evaluation_suite",
    "evaluation_case",
    "evaluation_run",
    "evaluation_result",
    "evaluation_metric",
    "evaluation_gate",
    "evaluation_regression_report",
    "evaluation_dashboard_snapshot",
}

CONTENT_QUALITY_DIMENSIONS = [
    "readability",
    "hook_strength",
    "emotional_curve",
    "conflict_density",
    "plot_progress",
    "character_motivation",
    "scene_vividness",
    "dialogue_quality",
    "ai_flavor_risk",
    "originality_risk",
]
LONGFORM_DIMENSIONS = [
    "canon_consistency",
    "character_drift",
    "arc_progress",
    "foreshadowing_tracking",
    "power_scale_consistency",
    "timeline_consistency",
    "world_rule_consistency",
]
ENGINEERING_DIMENSIONS = [
    "schema_validity",
    "context_adherence",
    "source_isolation",
    "os_envelope_coverage",
    "trace_coverage",
    "cost_budget",
    "latency",
    "failure_rate",
    "rollback_readiness",
]
PLATFORM_DIMENSIONS = [
    "opening_gate",
    "chapter_rhythm",
    "platform_retention_risk",
    "publish_compliance",
    "feedback_backflow_quality",
]


def create_model_profile(
    storage: LocalStorage,
    *,
    provider: str,
    model_name: str,
    task_types: list[str] | None = None,
    status: str = "candidate",
    capabilities: dict[str, Any] | None = None,
    cost_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with AgentExecutionContext(
        storage,
        agent_key="model_evaluation",
        operation="create-model-profile",
        output_types=["model_profile"],
        sla_seconds=300,
    ) as run:
        run.guard("write_model_profile", "model_profile")
        asset = ModelProfile(
            title=f"{provider}/{model_name}",
            tags=["model", provider, status, *[str(item) for item in task_types or []]],
            content={
                "profile_id": make_id("model_profile", f"{provider}-{model_name}"),
                "provider": provider,
                "model_name": model_name,
                "task_types": task_types or [],
                "capabilities": capabilities or _default_capabilities(task_types or []),
                "cost_profile": cost_profile or {"input_per_1k": 0, "output_per_1k": 0, "currency": "USD", "source": "manual"},
                "status": status,
                "created_at": utc_now(),
            },
            metadata={"provider": provider, "model_name": model_name},
        )
        result = _write(storage, asset)
        run.succeed(output_assets=[result["path"]])
        return result


def create_model_benchmark_task(
    storage: LocalStorage,
    *,
    task_type: str,
    input_assets: list[str | Path],
    rubric: dict[str, Any] | None = None,
    expected_output_type: str = "generate",
    prompt_template: str = "",
    workspace_path: str | None = None,
) -> dict[str, Any]:
    refs = [_asset_ref(storage, item) for item in input_assets]
    project = _project_scope(storage, refs, workspace_path=workspace_path)
    with AgentExecutionContext(
        storage,
        agent_key="model_evaluation",
        operation="create-model-benchmark-task",
        input_assets=input_assets,
        output_types=["model_benchmark_task"],
        workspace_path=str(project.get("workspace_path", "")),
        sla_seconds=300,
    ) as run:
        run.guard("read_asset")
        run.guard("write_model_benchmark_task", "model_benchmark_task")
        task_id = make_id("benchmark_task", task_type)
        asset = ModelBenchmarkTask(
            title=f"{task_type} benchmark task",
            tags=["model-benchmark", task_type],
            content={
                "task_id": task_id,
                "task_type": task_type,
                "input_assets": refs,
                "rubric": rubric or _default_rubric(task_type),
                "expected_output_type": expected_output_type,
                "prompt_template": prompt_template or _default_prompt_template(task_type),
                "created_at": utc_now(),
            },
            metadata={"project_id": project.get("project_id", ""), "workspace_path": project.get("workspace_path", "")},
            references=filter_project_safe_references(storage, str(project.get("project_id", "")), [ref["id"] for ref in refs] + [ref["path"] for ref in refs]),
        )
        result = _write(storage, asset)
        run.succeed(output_assets=[result["path"]])
        return result


def create_benchmark_task_from_generation_run(
    storage: LocalStorage,
    generation_run_path: str | Path,
    *,
    task_type: str = "generation",
    expected_output_type: str = "generate",
    prompt_template: str = "",
) -> dict[str, Any]:
    path = resolve_path(storage.root, generation_run_path)
    generation = storage.read_asset(path)
    if generation.type != "generation_run":
        raise ValueError("generation_run_path must point to a generation_run asset")
    content = generation.content if isinstance(generation.content, dict) else {}
    input_assets = _dedupe(
        [
            str(content.get("input_asset_path", "")),
            str(content.get("context_bundle_path", "")),
            str(content.get("output_asset_path", "")),
        ]
    )
    rubric = {
        "task_type": task_type,
        "source_generation_run_id": generation.id,
        "dimensions": ["schema_validity", "context_adherence", "quality_signal", "latency", "cost"],
        "weights": {"schema_validity": 0.3, "context_adherence": 0.25, "quality_signal": 0.25, "latency": 0.1, "cost": 0.1},
        "target_chars": 1200,
    }
    project = project_scope_from_asset(storage, generation, input_path=path)
    result = create_model_benchmark_task(
        storage,
        task_type=task_type,
        input_assets=input_assets,
        rubric=rubric,
        expected_output_type=expected_output_type,
        prompt_template=prompt_template
        or "Replay this production generation run as a benchmark. Respect the recorded context bundle and output schema.",
        workspace_path=str(project.get("workspace_path", "")),
    )
    task_asset = result.get("asset", {}) if isinstance(result.get("asset", {}), dict) else {}
    task_content = task_asset.get("content", {}) if isinstance(task_asset.get("content", {}), dict) else {}
    task_metadata = task_asset.get("metadata", {}) if isinstance(task_asset.get("metadata", {}), dict) else {}
    task_content["source_generation_run_id"] = generation.id
    task_content["source_generation_run_path"] = _display_path(storage.root, path)
    task_content["production_trace"] = {
        "provider": content.get("provider", ""),
        "model": content.get("model", ""),
        "prompt_version": content.get("prompt_version", ""),
        "context_bundle_path": content.get("context_bundle_path", ""),
        "output_asset_path": content.get("output_asset_path", ""),
    }
    task_metadata["source_generation_run_path"] = _display_path(storage.root, path)
    task_asset["content"] = task_content
    task_asset["metadata"] = task_metadata
    task_path = resolve_path(storage.root, result["path"])
    storage.write_json(task_path, task_asset)
    return {"path": result["path"], "asset": task_asset, "validation": result.get("validation", {"ok": True, "errors": []})}


def run_model_benchmark(
    storage: LocalStorage,
    task_path: str | Path,
    *,
    provider: str = "mock",
    model_name: str = "mock-model",
    model: object | None = None,
    execution_port: DomainExecutionPort | None = None,
    environment: str = "development",
) -> dict[str, Any]:
    path = resolve_path(storage.root, task_path)
    task = storage.read_asset(path)
    if task.type != "model_benchmark_task":
        raise ValueError("task_path must point to a model_benchmark_task asset")
    project = project_scope_from_asset(storage, task, input_path=path)
    with AgentExecutionContext(
        storage,
        agent_key="model_evaluation",
        operation="run-model-benchmark",
        input_assets=[path],
        output_types=["model_benchmark_run"],
        workspace_path=str(project.get("workspace_path", "")),
        model_provider=provider,
        model_name=model_name,
        sla_seconds=900,
    ) as run:
        run.guard("read_asset")
        task_type = str(task.content.get("task_type", "generate"))
        started = time.perf_counter()
        status = "succeeded"
        error = ""
        raw_output: dict[str, Any] = {}
        try:
            operation = _benchmark_operation(task_type)
            candidate = execute_domain_candidate(
                capability="quality.intrinsic.judge",
                operation=operation,
                candidate_kind=CandidateKind.JUDGE,
                prompt=str(task.content.get("prompt_template", "")),
                context={
                    "benchmark_task": task.content,
                    "input_assets": task.content.get("input_assets", []),
                    "judge_profile_version": f"{provider}:{model_name}",
                    "target_asset_version": task.id,
                },
                review={} if operation == "revise" else None,
                execution_port=execution_port,
                legacy_model=model,
                legacy_model_role=task_type,
                legacy_provider=provider,
                legacy_model_name=model_name,
                environment=environment,
                storage=storage,
                agent_run_path=run.path,
            )
            raw_output = dict(candidate.raw_output)
            validated = _validate_expected(task.content.get("expected_output_type", "generate"), raw_output)
        except Exception as exc:
            status = "failed"
            error = str(exc)
            validated = {}
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        scores = _score_output(task, validated, status=status, latency_ms=latency_ms)
        cost_estimate = _estimate_run_cost(storage, provider=provider, model_name=model_name, scores=scores, task=task)
        run.guard("write_model_benchmark_run", "model_benchmark_run")
        asset = ModelBenchmarkRun(
            title=f"{provider}/{model_name} on {task.title or task.id}",
            source=task.id,
            tags=["model-benchmark-run", str(task.content.get("task_type", "")), status, provider],
            content={
                "run_id": make_id("benchmark_run", f"{task.id}-{provider}-{model_name}"),
                "task_id": task.content.get("task_id", task.id),
                "task_path": _display_path(storage.root, path),
                "task_type": task.content.get("task_type", ""),
                "provider": provider,
                "model_name": model_name,
                "scores": scores,
                "latency_ms": latency_ms,
                "cost_estimate": cost_estimate,
                "status": status,
                "error": error,
                "raw_output": raw_output,
                "production_execution": (
                    candidate.evidence.to_dict()
                    if status == "succeeded"
                    else {}
                ),
                "validated_output": validated,
                "created_at": utc_now(),
            },
            metadata={"project_id": project.get("project_id", ""), "workspace_path": project.get("workspace_path", ""), "provider": provider, "model_name": model_name},
            references=filter_project_safe_references(storage, str(project.get("project_id", "")), [task.id, _display_path(storage.root, path)]),
        )
        result = _write(storage, asset)
        run.succeed(output_assets=[result["path"]], token_used=int(scores.get("output_chars", 0)))
        return result


def compare_model_runs(
    storage: LocalStorage,
    run_paths: list[str | Path],
    *,
    task_type: str = "",
    workspace_path: str | None = None,
) -> dict[str, Any]:
    runs = [_read_run(storage, item) for item in run_paths]
    project = _project_scope(storage, [{"path": run["path"], "id": run["id"], "type": run["asset"].get("type", "")} for run in runs], workspace_path=workspace_path)
    with AgentExecutionContext(
        storage,
        agent_key="model_evaluation",
        operation="compare-model-runs",
        input_assets=run_paths,
        output_types=["model_comparison_report"],
        workspace_path=str(project.get("workspace_path", "")),
        sla_seconds=300,
    ) as agent_run:
        agent_run.guard("read_asset")
        agent_run.guard("write_model_comparison_report", "model_comparison_report")
        ranked = sorted(runs, key=lambda row: float(row["content"].get("scores", {}).get("overall", 0)), reverse=True)
        winner = ranked[0] if ranked else None
        scores = [float(row["content"].get("scores", {}).get("overall", 0)) for row in runs]
        asset = ModelComparisonReport(
            title=f"Model comparison: {task_type or _common_task_type(runs)}",
            tags=["model-comparison", task_type or _common_task_type(runs)],
            content={
                "comparison_id": make_id("model_comparison", task_type or "mixed"),
                "task_type": task_type or _common_task_type(runs),
                "runs": [_run_summary(row) for row in runs],
                "winner": _run_summary(winner) if winner else {},
                "score_summary": {
                    "count": len(scores),
                    "max": max(scores) if scores else 0,
                    "min": min(scores) if scores else 0,
                    "average": round(sum(scores) / len(scores), 2) if scores else 0,
                },
                "recommendation": _recommendation(ranked),
                "created_at": utc_now(),
            },
            metadata={"project_id": project.get("project_id", ""), "workspace_path": project.get("workspace_path", "")},
            references=filter_project_safe_references(storage, str(project.get("project_id", "")), [row["id"] for row in runs] + [row["path"] for row in runs]),
        )
        result = _write(storage, asset)
        agent_run.succeed(output_assets=[result["path"]])
        return result


def run_model_benchmark_batch(
    storage: LocalStorage,
    *,
    task_paths: list[str | Path],
    candidates: list[dict[str, str]] | None = None,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    if not task_paths:
        raise ValueError("task_paths must not be empty")
    model_candidates = candidates or _active_model_candidates(storage)
    if not model_candidates:
        model_candidates = [{"provider": "mock", "model_name": "mock-model"}]
    run_results: list[dict[str, Any]] = []
    comparison_results: list[dict[str, Any]] = []
    with AgentExecutionContext(
        storage,
        agent_key="model_evaluation",
        operation="run-model-benchmark-batch",
        input_assets=task_paths,
        output_types=["model_benchmark_run", "model_comparison_report"],
        workspace_path=workspace_path or "",
        sla_seconds=3600,
    ) as batch_run:
        batch_run.guard("read_asset")
        for task_path in task_paths:
            task_run_paths: list[str] = []
            for candidate in model_candidates:
                result = run_model_benchmark(
                    storage,
                    task_path,
                    provider=str(candidate.get("provider") or "mock"),
                    model_name=str(candidate.get("model_name") or "mock-model"),
                )
                run_results.append(result)
                task_run_paths.append(result["path"])
            comparison = compare_model_runs(storage, task_run_paths, workspace_path=workspace_path)
            comparison_results.append(comparison)
        batch_run.succeed(
            output_assets=[*[item["path"] for item in run_results], *[item["path"] for item in comparison_results]],
            token_used=len(run_results),
        )
    return {"runs": run_results, "comparisons": comparison_results, "candidate_count": len(model_candidates)}


def create_model_routing_policy(
    storage: LocalStorage,
    *,
    comparison_paths: list[str | Path],
    status: str = "active",
    workspace_path: str | None = None,
) -> dict[str, Any]:
    if not comparison_paths:
        raise ValueError("comparison_paths must not be empty")
    comparisons = [_read_comparison(storage, item) for item in comparison_paths]
    project = _project_scope(
        storage,
        [{"id": row["id"], "path": row["path"], "type": row["asset"].get("type", "")} for row in comparisons],
        workspace_path=workspace_path,
    )
    task_routes: dict[str, Any] = {}
    fallbacks: dict[str, list[dict[str, Any]]] = {}
    tradeoffs: dict[str, Any] = {}
    for row in comparisons:
        content = row["content"]
        task_type = str(content.get("task_type") or "generate")
        runs = content.get("runs", []) if isinstance(content.get("runs", []), list) else []
        ranked = sorted(runs, key=lambda item: float(item.get("overall", 0)) if isinstance(item, dict) else 0, reverse=True)
        winner = content.get("winner", {}) if isinstance(content.get("winner", {}), dict) else {}
        if not winner and ranked:
            winner = ranked[0]
        task_routes[task_type] = {
            "provider": winner.get("provider", "mock"),
            "model_name": winner.get("model_name", "mock-model"),
            "source_comparison_path": row["path"],
            "overall": winner.get("overall", 0),
            "latency_ms": winner.get("latency_ms", 0),
            "reason": content.get("recommendation", ""),
        }
        fallbacks[task_type] = [
            {
                "provider": item.get("provider", ""),
                "model_name": item.get("model_name", ""),
                "overall": item.get("overall", 0),
                "latency_ms": item.get("latency_ms", 0),
            }
            for item in ranked[1:4]
            if isinstance(item, dict)
        ]
        tradeoffs[task_type] = {
            "score_summary": content.get("score_summary", {}),
            "selection_rule": "highest overall benchmark score, then latest active policy",
        }
    with AgentExecutionContext(
        storage,
        agent_key="model_evaluation",
        operation="create-model-routing-policy",
        input_assets=comparison_paths,
        output_types=["model_routing_policy"],
        workspace_path=str(project.get("workspace_path", "")),
        sla_seconds=300,
    ) as run:
        run.guard("read_asset")
        run.guard("write_model_routing_policy", "model_routing_policy")
        asset = ModelRoutingPolicy(
            title=f"Model routing policy {utc_now()}",
            tags=["model-routing", status],
            content={
                "policy_id": make_id("model_routing_policy", str(project.get("project_id") or "global")),
                "task_routes": task_routes,
                "fallbacks": fallbacks,
                "cost_quality_tradeoffs": tradeoffs,
                "effective_from": utc_now(),
                "status": status,
                "created_at": utc_now(),
            },
            metadata={"project_id": project.get("project_id", ""), "workspace_path": project.get("workspace_path", ""), "status": status},
            references=filter_project_safe_references(
                storage,
                str(project.get("project_id", "")),
                [row["id"] for row in comparisons] + [row["path"] for row in comparisons],
            ),
        )
        result = _write(storage, asset)
        run.succeed(output_assets=[result["path"]])
        return result


def resolve_model_route(
    storage: LocalStorage,
    *,
    task_type: str,
    project_id: str | None = None,
) -> dict[str, Any]:
    policy = _latest_active_routing_policy(storage, project_id=project_id)
    if not policy:
        return {"provider": "mock", "model_name": "mock-model", "source": "default"}
    content = policy.get("content", {}) if isinstance(policy.get("content", {}), dict) else {}
    routes = content.get("task_routes", {}) if isinstance(content.get("task_routes", {}), dict) else {}
    route = routes.get(task_type) or routes.get("generate") or {}
    if not isinstance(route, dict) or not route:
        return {"provider": "mock", "model_name": "mock-model", "source": "default"}
    return {**route, "source": "model_routing_policy", "policy_id": content.get("policy_id", ""), "policy_path": policy.get("path", "")}


def create_prompt_version(
    storage: LocalStorage,
    *,
    prompt_id: str,
    version: str,
    task_type: str,
    template: str,
    status: str = "draft",
) -> dict[str, Any]:
    with AgentExecutionContext(
        storage,
        agent_key="model_evaluation",
        operation="create-prompt-version",
        output_types=["prompt_version"],
        sla_seconds=300,
    ) as run:
        run.guard("write_prompt_version", "prompt_version")
        asset = PromptVersion(
            title=f"{prompt_id} {version}",
            tags=["prompt-version", task_type, status],
            content={
                "prompt_id": prompt_id,
                "version": version,
                "task_type": task_type,
                "template": template,
                "status": status,
                "created_at": utc_now(),
            },
            metadata={"task_type": task_type},
        )
        result = _write(storage, asset)
        run.succeed(output_assets=[result["path"]])
        return result


def create_prompt_regression_report(
    storage: LocalStorage,
    *,
    prompt_id: str,
    baseline_version: str,
    candidate_version: str,
    benchmark_runs: list[str],
) -> dict[str, Any]:
    run_rows = [_read_run(storage, item) for item in benchmark_runs]
    baseline_scores = [float(row["content"].get("scores", {}).get("overall", 0)) for row in run_rows if baseline_version in str(row["content"].get("raw_output", ""))]
    candidate_scores = [float(row["content"].get("scores", {}).get("overall", 0)) for row in run_rows if candidate_version in str(row["content"].get("raw_output", ""))]
    recommendation = "promote" if (sum(candidate_scores) / len(candidate_scores) if candidate_scores else 0) >= (sum(baseline_scores) / len(baseline_scores) if baseline_scores else 0) else "keep_baseline"
    with AgentExecutionContext(
        storage,
        agent_key="model_evaluation",
        operation="create-prompt-regression-report",
        input_assets=benchmark_runs,
        output_types=["prompt_regression_report"],
        sla_seconds=300,
    ) as run:
        run.guard("read_asset")
        run.guard("write_prompt_regression_report", "prompt_regression_report")
        asset = PromptRegressionReport(
            title=f"Prompt regression {prompt_id}: {baseline_version} -> {candidate_version}",
            tags=["prompt-regression", recommendation],
            content={
                "prompt_id": prompt_id,
                "baseline_version": baseline_version,
                "candidate_version": candidate_version,
                "benchmark_runs": benchmark_runs,
                "score_delta": round((sum(candidate_scores) / len(candidate_scores) if candidate_scores else 0) - (sum(baseline_scores) / len(baseline_scores) if baseline_scores else 0), 2),
                "recommendation": recommendation,
                "created_at": utc_now(),
            },
            references=benchmark_runs,
        )
        result = _write(storage, asset)
        run.succeed(output_assets=[result["path"]])
        return result


def list_model_evaluation_assets(storage: LocalStorage, *, project_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in storage.list_json("runs"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") not in EVALUATION_TYPES:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        scores = content.get("scores", {}) if isinstance(content.get("scores", {}), dict) else {}
        score = float(content.get("overall_score", scores.get("overall", 0)) or 0)
        rows.append(
            {
                "path": _display_path(storage.root, path),
                "id": data.get("id", ""),
                "type": data.get("type", ""),
                "title": data.get("title") or data.get("name", ""),
                "content": content,
                "metadata": metadata,
                "provider": content.get("provider") or metadata.get("provider", ""),
                "model_name": content.get("model_name") or metadata.get("model_name", ""),
                "task_type": content.get("task_type", ""),
                "status": content.get("status", ""),
                "target_asset_type": content.get("target_asset_type", ""),
                "target_asset_path": content.get("target_asset_path", ""),
                "scores": scores,
                "overall_score": score,
                "score": score,
                "cost_estimate": content.get("cost_estimate", {}),
                "latency_ms": content.get("latency_ms", ""),
                "recommendation": content.get("recommendation", ""),
                "blocking": bool(content.get("blocking") or metadata.get("blocking")),
                "task_routes": content.get("task_routes", {}),
                "updated_at": data.get("updated_at", ""),
            }
        )
        if len(rows) >= limit:
            break
    return sorted(rows, key=lambda row: row.get("updated_at", ""), reverse=True)


def create_evaluation_suite(
    storage: LocalStorage,
    *,
    name: str,
    target_asset_types: list[str] | None = None,
    metrics: list[str] | None = None,
    status: str = "active",
    project_id: str = "",
) -> dict[str, Any]:
    selected_metrics = metrics or [*CONTENT_QUALITY_DIMENSIONS, *LONGFORM_DIMENSIONS, *ENGINEERING_DIMENSIONS, *PLATFORM_DIMENSIONS]
    asset = BaseAsset(
        type="evaluation_suite",
        title=name,
        tags=["evaluation", "suite", status],
        content={
            "suite_id": make_id("evaluation_suite", name),
            "name": name,
            "target_asset_types": target_asset_types
            or [
                "outline",
                "chapter_plan",
                "draft_chapter",
                "review_report",
                "context_bundle",
                "rag_quality_report",
                "review_issue",
                "agent_run",
                "workflow_run",
                "loop_run",
                "longform_recap_report",
                "publish_gate_report",
                "release_package",
                "reader_feedback_backflow_report",
            ],
            "metrics": selected_metrics,
            "status": status,
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id, "status": status, "metric_count": len(selected_metrics)},
    )
    return _write(storage, asset)


def create_evaluation_case(storage: LocalStorage, *, suite_id: str, target_asset_path: str, expected: dict[str, Any] | None = None, status: str = "active") -> dict[str, Any]:
    target = storage.read_asset(resolve_path(storage.root, target_asset_path))
    project = project_scope_from_asset(storage, target, input_path=target_asset_path)
    asset = BaseAsset(
        type="evaluation_case",
        title=f"Evaluation case {target.title or target.id}",
        tags=["evaluation", "case", target.type, status],
        content={
            "case_id": make_id("evaluation_case", f"{suite_id}-{target.id}"),
            "suite_id": suite_id,
            "target_asset_path": target_asset_path,
            "target_asset_id": target.id,
            "target_asset_type": target.type,
            "expected": expected or {},
            "status": status,
            "created_at": utc_now(),
        },
        metadata={"project_id": project.get("project_id", ""), "suite_id": suite_id, "target_asset_type": target.type, "status": status},
        references=filter_project_safe_references(storage, str(project.get("project_id", "")), [target.id, target_asset_path]),
    )
    return _write(storage, asset)


def create_human_annotation_asset(
    storage: LocalStorage,
    *,
    target_asset_path: str | Path,
    annotator: str,
    scores: dict[str, Any],
    verdict: str = "needs_review",
    comment: str = "",
    project_id: str = "",
    rubric_id: str = "eval-center-human-annotation",
    annotation_version: str = "human-calibration-v1",
    annotator_role: str = "",
    confidence: float | None = None,
) -> dict[str, Any]:
    path = resolve_path(storage.root, target_asset_path)
    target = storage.read_asset(path)
    project = project_scope_from_asset(storage, target, input_path=path)
    normalized_scores = {str(key): _score_0_1(value) for key, value in (scores or {}).items()}
    overall = round(sum(normalized_scores.values()) / max(1, len(normalized_scores)), 4)
    asset = BaseAsset(
        type="human_annotation",
        title=f"Human annotation {target.type}",
        source=target.id,
        tags=["evaluation", "human-annotation", verdict],
        content={
            "annotation_id": make_id("human_annotation", f"{target.id}-{annotator}-{utc_now()}"),
            "target_asset_id": target.id,
            "rubric_id": rubric_id,
            "annotation_version": annotation_version,
            "target_asset_type": target.type,
            "target_asset_path": _display_path(storage.root, path),
            "annotator": annotator,
            "annotator_role": annotator_role,
            "scores": normalized_scores,
            "overall_score": overall,
            "confidence": _score_0_1(confidence) if confidence is not None else None,
            "verdict": verdict,
            "recommendation": verdict,
            "comment": comment[:1000],
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id or project.get("project_id", ""), "target_asset_type": target.type, "overall_score": overall, "verdict": verdict},
        references=filter_project_safe_references(storage, str(project_id or project.get("project_id", "")), [target.id, _display_path(storage.root, path)]),
    )
    return _write(storage, asset)


def build_golden_set(
    storage: LocalStorage,
    *,
    name: str,
    case_specs: list[dict[str, Any]],
    project_id: str = "",
    status: str = "active",
    calibration_version: str = "golden-human-calibration-v1",
) -> dict[str, Any]:
    if not case_specs:
        raise ValueError("case_specs must not be empty")
    case_rows = []
    references: list[str] = []
    metrics: set[str] = set()
    for index, spec in enumerate(case_specs, start=1):
        target_path = str(spec.get("target_asset_path") or "")
        if not target_path:
            raise ValueError("each golden set case requires target_asset_path")
        target = storage.read_asset(resolve_path(storage.root, target_path))
        expected_scores = {str(key): _score_0_1(value) for key, value in (spec.get("expected_scores", {}) if isinstance(spec.get("expected_scores", {}), dict) else {}).items()}
        annotation_path = str(spec.get("annotation_path") or "")
        raw_annotation_paths = spec.get("annotation_paths", []) if isinstance(spec.get("annotation_paths", []), list) else []
        annotation_paths = _dedupe([annotation_path, *[str(item) for item in raw_annotation_paths if str(item or "").strip()]])
        annotation_summary = _annotation_summary(storage, annotation_path)
        metrics.update(expected_scores.keys())
        case_rows.append(
            {
                "case_id": make_id("golden_case", f"{name}-{index}-{target.id}"),
                "target_asset_path": _display_path(storage.root, resolve_path(storage.root, target_path)),
                "target_asset_id": target.id,
                "target_asset_type": target.type,
                "expected_scores": expected_scores,
                "annotation_path": annotation_path,
                "annotation_paths": annotation_paths,
                "annotation_summary": annotation_summary,
                "expected_verdict": str(spec.get("expected_verdict") or annotation_summary.get("verdict") or ""),
                "acceptance_band": float(spec.get("acceptance_band", 0.08) or 0.08),
                "status": str(spec.get("status") or "active"),
            }
        )
        references.extend([target.id, target_path, annotation_path])
    asset = BaseAsset(
        type="evaluation_suite",
        title=name,
        tags=["evaluation", "suite", "golden-set", status],
        content={
            "suite_id": make_id("evaluation_suite", f"golden-{name}"),
            "name": name,
            "target_asset_types": sorted({row["target_asset_type"] for row in case_rows}),
            "metrics": sorted(metrics) or ["overall"],
            "status": status,
            "golden_set": {
                "enabled": True,
                "calibration_version": calibration_version,
                "case_count": len(case_rows),
                "cases": case_rows,
                "calibration_policy": {
                    "compare_provider_judge_to_human_or_expected_scores": True,
                    "default_tolerance": 0.08,
                    "fail_closed_for_production_release": True,
                },
            },
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id, "status": status, "golden_set": True, "case_count": len(case_rows)},
        references=filter_project_safe_references(storage, project_id, _dedupe(references)),
    )
    return _write(storage, asset)


def calibrate_provider_judge(
    storage: LocalStorage,
    *,
    golden_set_path: str | Path,
    provider_judge_results: list[dict[str, Any]],
    tolerance: float = 0.08,
    project_id: str = "",
    calibration_version: str = "golden-human-calibration-v1",
) -> dict[str, Any]:
    golden_path = resolve_path(storage.root, golden_set_path)
    golden = storage.read_json(golden_path)
    content = golden.get("content", {}) if isinstance(golden.get("content", {}), dict) else {}
    golden_set = content.get("golden_set", {}) if isinstance(content.get("golden_set", {}), dict) else {}
    cases = golden_set.get("cases", []) if isinstance(golden_set.get("cases", []), list) else []
    if not cases:
        raise ValueError("golden_set_path must point to an evaluation_suite with golden_set cases")
    result_by_target: dict[str, dict[str, Any]] = {}
    for row in provider_judge_results:
        if not isinstance(row, dict):
            continue
        for key in _target_lookup_keys(storage, row):
            result_by_target[key] = row
    comparisons = []
    errors: list[float] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        target_path = str(case.get("target_asset_path") or "")
        result = result_by_target.get(target_path) or result_by_target.get(str(case.get("target_asset_id") or "")) or {}
        expected_scores = case.get("expected_scores", {}) if isinstance(case.get("expected_scores", {}), dict) else {}
        human_scores, human_meta = _human_consensus(storage, case)
        reference_scores = {str(key): _score_0_1(value) for key, value in expected_scores.items()} or human_scores
        # Explicit golden scores define the case contract.  Human consensus is
        # retained as calibration evidence and is used when a case has no
        # expected score map.
        if not expected_scores and human_scores:
            expected_scores = human_scores
        judge_scores = result.get("scores", {}) if isinstance(result.get("scores", {}), dict) else {}
        if not result or not judge_scores:
            comparisons.append(
                {
                    "case_id": case.get("case_id", ""),
                    "target_asset_path": target_path,
                    "provider": str(result.get("provider") or ""),
                    "reference_scores": reference_scores,
                    "human_calibration": human_meta,
                    "expected_verdict": str(case.get("expected_verdict") or ""),
                    "dimension_errors": {},
                    "status": "missing_provider_result",
                }
            )
            errors.append(1.0)
            continue
        dimensions = sorted(set(expected_scores) | set(judge_scores))
        dimension_errors = {}
        for dimension in dimensions:
            expected = _score_0_1(expected_scores.get(dimension, 0))
            observed = _score_0_1(judge_scores.get(dimension, 0))
            error = round(abs(observed - expected), 4)
            dimension_errors[dimension] = {"expected": expected, "observed": observed, "absolute_error": error}
            errors.append(error)
        comparisons.append(
            {
                "case_id": case.get("case_id", ""),
                "target_asset_path": target_path,
                "provider": str(result.get("provider") or ""),
                "reference_scores": reference_scores,
                "human_calibration": human_meta,
                "expected_verdict": str(case.get("expected_verdict") or ""),
                "dimension_errors": dimension_errors,
                "status": "passed" if (sum(item["absolute_error"] for item in dimension_errors.values()) / max(1, len(dimension_errors))) <= tolerance else "needs_calibration",
            }
        )
    mean_absolute_error = round(sum(errors) / max(1, len(errors)), 4)
    status = "passed" if mean_absolute_error <= tolerance and not any(row.get("status") == "missing_provider_result" for row in comparisons) else "needs_calibration"
    threshold_recommendation = _calibrated_threshold_recommendation(comparisons)
    human_calibration = _human_calibration_summary(comparisons)
    asset = BaseAsset(
        type="evaluation_regression_report",
        title=f"Provider judge calibration {status}",
        source=str(golden.get("id") or ""),
        tags=["evaluation", "provider-judge-calibration", status],
        content={
            "report_id": make_id("provider_judge_calibration", f"{golden.get('id', '')}-{utc_now()}"),
            "golden_set_path": _display_path(storage.root, golden_path),
            "baseline_path": _display_path(storage.root, golden_path),
            "candidate_path": "inline_provider_judge_results",
            "calibration_status": status,
            "mean_absolute_error": mean_absolute_error,
            "tolerance": float(tolerance),
            "calibration_version": calibration_version,
            "threshold_recommendation": threshold_recommendation,
            "human_calibration": human_calibration,
            "threshold_source": "human_consensus_and_golden_labels",
            "comparisons": comparisons,
            "recommendation": "provider_judge_calibrated" if status == "passed" else "review rubric, prompt, or provider route before production use",
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id or golden.get("metadata", {}).get("project_id", ""), "status": status, "mean_absolute_error": mean_absolute_error},
        references=filter_project_safe_references(storage, str(project_id or golden.get("metadata", {}).get("project_id", "")), [_display_path(storage.root, golden_path)]),
    )
    return _write(storage, asset)


def create_calibrated_quality_rubric(
    storage: LocalStorage,
    *,
    rubric_path: str | Path,
    calibration_report_path: str | Path,
    project_id: str = "",
) -> dict[str, Any]:
    """Create a new rubric version whose thresholds come from calibration evidence.

    The source rubric is never mutated.  Production provider acceptance can
    therefore point at an auditable, immutable rubric/calibration pair.
    """

    source_path = resolve_path(storage.root, rubric_path)
    report_path = resolve_path(storage.root, calibration_report_path)
    source = storage.read_json(source_path)
    report = storage.read_json(report_path)
    if source.get("type") != "quality_rubric_pack":
        raise ValueError("rubric_path must point to a quality_rubric_pack")
    if report.get("type") != "evaluation_regression_report":
        raise ValueError("calibration_report_path must point to an evaluation_regression_report")
    report_content = report.get("content", {}) if isinstance(report.get("content", {}), dict) else {}
    if str(report_content.get("calibration_status") or "") != "passed":
        raise ValueError("only passed provider calibration reports can create a production rubric")
    recommendation = report_content.get("threshold_recommendation", {}) if isinstance(report_content.get("threshold_recommendation", {}), dict) else {}
    thresholds = recommendation.get("thresholds", {}) if isinstance(recommendation.get("thresholds", {}), dict) else {}
    if not thresholds or not {"ready", "needs_revision", "blocked"}.issubset(thresholds):
        raise ValueError("calibration report has no complete threshold recommendation")
    source_content = source.get("content", {}) if isinstance(source.get("content", {}), dict) else {}
    content = deepcopy(source_content)
    old_version = str(content.get("rubric_version") or "v1")
    content["rubric_version"] = f"{old_version}-calibrated"
    content["thresholds"] = {key: float(value) for key, value in thresholds.items()}
    content["calibration_ref"] = _display_path(storage.root, report_path)
    content["threshold_calibration"] = {
        "status": "passed",
        "production_ready": bool((report_content.get("human_calibration", {}) or {}).get("production_ready")) if isinstance(report_content.get("human_calibration", {}), dict) else False,
        "calibration_version": report_content.get("calibration_version", ""),
        "source": "human_consensus_and_golden_labels",
        "mean_absolute_error": report_content.get("mean_absolute_error", 0),
        "human_calibration": report_content.get("human_calibration", {}),
    }
    judge_policy = content.get("judge_policy", {}) if isinstance(content.get("judge_policy", {}), dict) else {}
    judge_policy["threshold_source"] = "human_calibrated"
    judge_policy["calibration_required_for_production_acceptance"] = True
    content["judge_policy"] = judge_policy
    metadata = deepcopy(source.get("metadata", {}) if isinstance(source.get("metadata", {}), dict) else {})
    metadata.update({"project_id": project_id or metadata.get("project_id", ""), "calibration_report_path": _display_path(storage.root, report_path), "rubric_status": "calibrated"})
    asset = QualityRubricPack(
        title=f"{source.get('title', 'Quality rubric')} calibrated",
        source=str(source.get("id") or ""),
        tags=["quality-eval-v2", "rubric", "calibrated"],
        content=content,
        metadata=metadata,
        references=_dedupe([_display_path(storage.root, source_path), _display_path(storage.root, report_path)]),
    )
    return _write(storage, asset)


def evaluate_asset(
    storage: LocalStorage,
    target_asset_path: str | Path,
    *,
    suite_id: str = "default-novel-os-quality",
    project_id: str = "",
    create_issue_on_fail: bool = False,
    human_annotations: list[dict[str, Any]] | None = None,
    model_judge: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = resolve_path(storage.root, target_asset_path)
    target = storage.read_asset(path)
    project = project_scope_from_asset(storage, target, input_path=path)
    project_id = project_id or str(project.get("project_id", ""))
    scores = _score_asset(target.to_dict())
    model_judge = _resolve_model_judge(storage, target.to_dict(), path, project_id=project_id, model_judge=model_judge)
    evaluator_inputs = _apply_evaluator_inputs(scores, human_annotations=human_annotations, model_judge=model_judge)
    overall = round(sum(scores.values()) / max(1, len(scores)), 4)
    recommendation = "pass" if overall >= 0.72 else ("revise" if overall >= 0.55 else "block")
    content = {
        "result_id": make_id("evaluation_result", f"{target.type}-{target.id}-{utc_now()}"),
        "suite_id": suite_id,
        "target_asset_id": target.id,
        "target_asset_type": target.type,
        "target_asset_path": _display_path(storage.root, path),
        "scores": scores,
        "overall_score": overall,
        "recommendation": recommendation,
        "evaluation_mode": evaluator_inputs["evaluation_mode"],
        "evaluator_inputs": evaluator_inputs,
        "dimensions": {
            "content_quality": {key: scores[key] for key in CONTENT_QUALITY_DIMENSIONS if key in scores},
            "longform_consistency": {key: scores[key] for key in LONGFORM_DIMENSIONS if key in scores},
            "engineering_quality": {key: scores[key] for key in ENGINEERING_DIMENSIONS if key in scores},
            "platform_fit": {key: scores[key] for key in PLATFORM_DIMENSIONS if key in scores},
        },
        "created_at": utc_now(),
    }
    asset = BaseAsset(
        type="evaluation_result",
        title=f"Evaluation result {target.type}",
        source=target.id,
        tags=["evaluation", "result", target.type, recommendation],
        content=content,
        metadata={"project_id": project_id, "suite_id": suite_id, "target_asset_type": target.type, "overall_score": overall, "recommendation": recommendation},
        references=filter_project_safe_references(storage, project_id, [target.id, _display_path(storage.root, path)]),
    )
    result = _write(storage, asset)
    issue = {}
    if create_issue_on_fail and recommendation == "block":
        issue = _create_review_issue_for_evaluation(storage, target.to_dict(), result, project_id=project_id)
    return {**result, "scores": scores, "recommendation": recommendation, "review_issue": issue}


def run_evaluation_suite(storage: LocalStorage, *, suite_path: str | Path | None = None, target_asset_paths: list[str] | None = None, project_id: str = "") -> dict[str, Any]:
    suite = _load_or_default_suite(storage, suite_path)
    suite_content = suite.get("content", {}) if isinstance(suite.get("content", {}), dict) else {}
    target_paths = target_asset_paths or _recent_evaluation_targets(storage, project_id=project_id)
    result_paths = []
    results = []
    for target_path in target_paths:
        try:
            result = evaluate_asset(storage, target_path, suite_id=str(suite_content.get("suite_id") or "default-novel-os-quality"), project_id=project_id, create_issue_on_fail=True)
            result_paths.append(result["path"])
            results.append(result["asset"])
        except Exception as exc:
            results.append({"target_asset_path": target_path, "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
    status = "failed" if not result_paths else ("completed_with_failures" if len(result_paths) != len(target_paths) else "completed")
    asset = BaseAsset(
        type="evaluation_run",
        title="Evaluation suite run",
        tags=["evaluation", "run", status],
        content={
            "run_id": make_id("evaluation_run", f"{suite_content.get('suite_id', 'suite')}-{utc_now()}"),
            "suite_id": suite_content.get("suite_id", "default-novel-os-quality"),
            "target_asset_path": ",".join(target_paths),
            "status": status,
            "result_paths": result_paths,
            "results": results,
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id, "suite_id": suite_content.get("suite_id", "default-novel-os-quality"), "status": status, "result_count": len(result_paths)},
        references=filter_project_safe_references(storage, project_id, [*target_paths, *result_paths]),
    )
    return _write(storage, asset)


def create_evaluation_gate(
    storage: LocalStorage,
    target_asset_path: str | Path,
    *,
    minimum_score: float = 0.72,
    project_id: str = "",
    require_provider_runtime: bool = False,
) -> dict[str, Any]:
    result = evaluate_asset(storage, target_asset_path, project_id=project_id, create_issue_on_fail=True)
    evaluation = result.get("asset", {})
    content_result = evaluation.get("content", {}) if isinstance(evaluation.get("content", {}), dict) else {}
    score = float(content_result.get("overall_score", 0) or 0)
    provider_runtime = provider_hard_stop_evidence_report(storage, project_id=project_id or None)
    provider_blocking = bool(require_provider_runtime and provider_runtime.get("status") != "passed")
    status = "passed" if score >= minimum_score and not provider_blocking else "blocked"
    issue = {}
    if status == "blocked" and not result.get("review_issue"):
        try:
            target_asset = storage.read_asset(resolve_path(storage.root, target_asset_path))
            issue = _create_review_issue_for_evaluation(storage, target_asset.to_dict(), result, project_id=project_id)
        except Exception:
            issue = {}
    asset = BaseAsset(
        type="evaluation_gate",
        title=f"Evaluation gate {status}",
        tags=["evaluation", "gate", status],
        content={
            "gate_id": make_id("evaluation_gate", f"{content_result.get('target_asset_id', '')}-{utc_now()}"),
            "target_asset_id": content_result.get("target_asset_id", ""),
            "target_asset_type": content_result.get("target_asset_type", ""),
            "target_asset_path": content_result.get("target_asset_path", ""),
            "evaluation_result_path": result["path"],
            "minimum_score": minimum_score,
            "overall_score": score,
            "status": status,
            "blocking": status == "blocked",
            "provider_runtime_policy": {
                "required": bool(require_provider_runtime),
                "status": provider_runtime.get("status", ""),
                "summary": provider_runtime.get("summary", {}),
            },
            "review_issue_path": issue.get("path", "") if isinstance(issue, dict) else "",
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id, "status": status, "blocking": status == "blocked"},
        references=filter_project_safe_references(storage, project_id, [result["path"], str(target_asset_path), issue.get("path", "") if isinstance(issue, dict) else ""]),
    )
    written = _write(storage, asset)
    return {**written, "evaluation_result": result, "review_issue": issue}


def create_evaluation_dashboard_snapshot(storage: LocalStorage, *, project_id: str = "") -> dict[str, Any]:
    results = [row for row in list_model_evaluation_assets(storage, project_id=project_id or None, limit=1000) if row.get("type") in {"evaluation_result", "model_benchmark_run"}]
    scores = []
    for row in results:
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        if row.get("type") == "evaluation_result":
            scores.append(float(content.get("overall_score", row.get("score", 0)) or 0))
        elif row.get("type") == "model_benchmark_run":
            scores.append(float(row.get("score", 0) or 0))
    average = round(sum(scores) / max(1, len(scores)), 4)
    asset = BaseAsset(
        type="evaluation_dashboard_snapshot",
        title="Evaluation dashboard snapshot",
        tags=["evaluation", "dashboard"],
        content={
            "snapshot_id": make_id("evaluation_dashboard", f"{project_id}-{utc_now()}"),
            "summary": {"result_count": len(results), "average_score": average, "block_count": sum(1 for row in results if row.get("recommendation") == "block")},
            "quality_trends": [{"index": index + 1, "score": score} for index, score in enumerate(scores[-50:])],
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id, "average_score": average, "result_count": len(results)},
        references=[str(row.get("path", "")) for row in results if row.get("path")],
    )
    return _write(storage, asset)


def evaluation_dashboard(storage: LocalStorage, *, project_id: str = "") -> dict[str, Any]:
    return create_evaluation_dashboard_snapshot(storage, project_id=project_id)["asset"]["content"]


def _benchmark_operation(task_type: str) -> str:
    if task_type in {"review", "quality_review", "chapter_review"}:
        return "review"
    if task_type in {"analysis", "decomposition"}:
        return "analyze"
    if task_type in {"revision", "revise"}:
        return "revise"
    return "generate"


def _score_asset(asset: dict[str, Any]) -> dict[str, float]:
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    metadata = asset.get("metadata", {}) if isinstance(asset.get("metadata", {}), dict) else {}
    text = str(content.get("text") or content.get("summary") or content.get("actual_context") or content)
    source_isolation = content.get("source_isolation", {}) if isinstance(content.get("source_isolation", {}), dict) else {}
    has_trace = bool(metadata.get("trace_id") or content.get("trace_id") or metadata.get("agent_run_path"))
    has_context = bool(content.get("context_bundle") or content.get("context_bundle_id") or metadata.get("context_bundle_id"))
    has_envelope = bool(metadata.get("os_envelope_id") or content.get("envelope_id") or metadata.get("envelope_id"))
    raw_text_risk = _contains_key(content, "raw_text") or bool(source_isolation.get("source_chunk_raw_text_allowed"))
    length_score = min(1.0, max(0.35, len(text) / 1200))
    issue_count = len(content.get("issues", [])) if isinstance(content.get("issues", []), list) else 0
    blocking = bool(content.get("blocking") or metadata.get("blocking"))
    return {
        "readability": round(length_score, 4),
        "hook_strength": 0.72 if any(key in text.lower() for key in ["hook", "钩子", "悬念", "期待"]) else 0.58,
        "emotional_curve": 0.7 if any(key in text for key in ["情绪", "压力", "代价", "动机"]) else 0.56,
        "conflict_density": 0.74 if any(key in text for key in ["冲突", "风险", "阻碍", "代价"]) else 0.52,
        "plot_progress": 0.72 if any(key in text for key in ["推进", "目标", "结果", "转折"]) else 0.55,
        "character_motivation": 0.72 if any(key in text for key in ["动机", "目标", "欲望", "选择"]) else 0.55,
        "scene_vividness": 0.68 if len(text) > 80 else 0.5,
        "dialogue_quality": 0.66 if "dialogue" in text.lower() or "对话" in text else 0.55,
        "ai_flavor_risk": 0.78 if "AI" not in text and "模板化" not in text else 0.45,
        "originality_risk": 0.25 if raw_text_risk else 0.82,
        "canon_consistency": 0.35 if blocking else 0.76,
        "character_drift": 0.45 if issue_count >= 3 else 0.72,
        "arc_progress": 0.7 if asset.get("type") in {"outline", "chapter_plan", "longform_recap_report"} else 0.6,
        "foreshadowing_tracking": 0.72 if "foreshadow" in text.lower() or "伏笔" in text else 0.58,
        "power_scale_consistency": 0.68,
        "timeline_consistency": 0.68,
        "world_rule_consistency": 0.68,
        "schema_validity": 1.0,
        "context_adherence": 0.78 if has_context else 0.55,
        "source_isolation": 0.2 if raw_text_risk else 0.95,
        "os_envelope_coverage": 0.78 if has_envelope else 0.55,
        "trace_coverage": 0.8 if has_trace else 0.5,
        "cost_budget": 0.72,
        "latency": 0.72,
        "failure_rate": 0.25 if str(content.get("status", "")).lower() == "failed" else 0.8,
        "rollback_readiness": 0.72 if metadata.get("rollback_path") or content.get("rollback_plan") else 0.56,
        "opening_gate": 0.68,
        "chapter_rhythm": 0.72 if any(key in text for key in ["节奏", "反转", "爽点", "hook"]) else 0.55,
        "platform_retention_risk": 0.72 if "retention" in text.lower() or "留存" in text else 0.58,
        "publish_compliance": 0.25 if raw_text_risk or blocking else 0.8,
        "feedback_backflow_quality": 0.74 if asset.get("type") == "reader_feedback_backflow_report" else 0.6,
    }


def _apply_evaluator_inputs(
    scores: dict[str, float],
    *,
    human_annotations: list[dict[str, Any]] | None,
    model_judge: dict[str, Any] | None,
) -> dict[str, Any]:
    annotations = _normalize_human_annotations(human_annotations)
    judge = _normalize_model_judge(model_judge)
    if annotations:
        scores["human_annotation"] = round(sum(item["score"] for item in annotations) / len(annotations), 4)
    if judge.get("score") is not None:
        scores["model_judge"] = float(judge["score"])
    mode = "local_heuristic"
    external = bool(judge.get("external_provider_called", False))
    if annotations and external:
        mode = "local_heuristic_with_human_and_external_model_judge"
    elif external:
        mode = "local_heuristic_with_external_model_judge"
    elif annotations and judge.get("score") is not None:
        mode = "local_heuristic_with_human_and_model_judge"
    elif annotations:
        mode = "local_heuristic_with_human_annotations"
    elif judge.get("score") is not None:
        mode = "local_heuristic_with_model_judge"
    return {
        "evaluation_mode": mode,
        "human_annotations": annotations,
        "model_judge": judge,
        "external_provider_called": bool(judge.get("external_provider_called", False)),
    }


def _normalize_human_annotations(value: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        score = _score_0_1(row.get("score", row.get("rating", 0)))
        normalized.append(
            {
                "dimension": str(row.get("dimension") or "overall"),
                "score": score,
                "annotator": str(row.get("annotator") or "human"),
                "comment": str(row.get("comment") or "")[:500],
            }
        )
    return normalized


def _normalize_model_judge(value: dict[str, Any] | None) -> dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    score_value = payload.get("score")
    score = _score_0_1(score_value) if score_value not in (None, "") else None
    return {
        "enabled": bool(payload.get("enabled", False)),
        "provider": str(payload.get("provider") or "local"),
        "model": str(payload.get("model") or "deterministic-judge"),
        "score": score,
        "score_semantics": str(payload.get("score_semantics") or "Raw Score"),
        "calibration_status": str(
            payload.get("calibration_status") or "uncalibrated"
        ),
        "probability_claim_allowed": bool(
            payload.get("calibration_status") == "calibrated"
            and payload.get("probability_claim_allowed")
        ),
        "confidence": _score_0_1(payload.get("confidence", 1.0)),
        "recommendation": str(payload.get("recommendation") or ""),
        "status": str(payload.get("status") or ("provided_score" if score is not None else "not_provided")),
        "external_provider_called": bool(payload.get("external_provider_called", False)),
        "model_gateway_call": payload.get("model_gateway_call", {}) if isinstance(payload.get("model_gateway_call", {}), dict) else {},
    }


def _resolve_model_judge(storage: LocalStorage, target: dict[str, Any], target_path: Path, *, project_id: str, model_judge: dict[str, Any] | None) -> dict[str, Any] | None:
    payload = model_judge if isinstance(model_judge, dict) else {}
    if not payload or not payload.get("enabled"):
        return model_judge
    mode = str(payload.get("mode") or payload.get("judge_mode") or "score").lower()
    if mode not in {"external", "provider", "model"}:
        return model_judge
    policy = payload.get("runtime_policy", {}) if isinstance(payload.get("runtime_policy", {}), dict) else {}
    source_policy = payload.get("source_policy", {}) if isinstance(payload.get("source_policy", {}), dict) else {}
    allowed = bool(payload.get("allow_external_model_judge") or policy.get("allow_external_model_judge"))
    if not allowed:
        raise PermissionError("external model judge requires allow_external_model_judge=true")
    if bool(source_policy.get("raw_source_text_allowed")):
        raise PermissionError("external model judge cannot run with raw_source_text_allowed=true")
    if str(target.get("type", "")) in {"source_document", "source_chunk", "cleaned_text"}:
        raise PermissionError("external model judge cannot evaluate raw source assets")
    provider = str(payload.get("provider") or "mock")
    text = _evaluation_judge_text(target)
    execution_port = payload.get("execution_port")
    if execution_port is not None and not callable(
        getattr(execution_port, "execute", None)
    ):
        raise ValueError("model judge execution_port does not implement execute")
    candidate = execute_domain_candidate(
        capability="quality.intrinsic.judge",
        operation="review",
        candidate_kind=CandidateKind.JUDGE,
        prompt=text,
        context={
            "evaluation_judge": True,
            "target_asset_type": target.get("type", ""),
            "target_asset_version": target.get("id", ""),
            "target_asset_path": _display_path(storage.root, target_path),
            "source_policy": source_policy,
            "judge_profile_version": str(
                payload.get("judge_profile_version") or "evaluation-center:v1"
            ),
        },
        execution_port=execution_port,
        legacy_model_role="review",
        legacy_provider=provider,
        legacy_model_name=str(payload.get("model") or ""),
        environment=str(
            payload.get("environment")
            or (
                (payload.get("os_envelope") or {}).get("environment")
                if isinstance(payload.get("os_envelope"), dict)
                else ""
            )
            or "development"
        ),
        storage=storage,
    )
    result = dict(candidate.raw_output)
    score = _score_0_1(result.get("score", payload.get("score", 0)) if isinstance(result, dict) else 0)
    return {
        **payload,
        "score": score,
        "score_semantics": "Raw Score",
        "calibration_status": str(payload.get("calibration_status") or "uncalibrated"),
        "recommendation": str((result or {}).get("next_action") or payload.get("recommendation") or ""),
        "status": "execution_candidate_received",
        "external_provider_called": candidate.evidence.real_model_call,
        "provider": provider,
        "model": str((result or {}).get("model") or payload.get("model") or ""),
        "model_gateway_call": candidate.evidence.to_dict(),
    }


def _evaluation_judge_text(target: dict[str, Any]) -> str:
    content = target.get("content", {}) if isinstance(target.get("content", {}), dict) else {}
    text = str(content.get("text") or content.get("summary") or content.get("actual_context") or content)
    return text[:4000]


def _annotation_summary(storage: LocalStorage, annotation_path: str) -> dict[str, Any]:
    if not annotation_path:
        return {}
    try:
        annotation = storage.read_json(resolve_path(storage.root, annotation_path))
    except (FileNotFoundError, ValueError):
        return {"path": annotation_path, "status": "missing"}
    content = annotation.get("content", {}) if isinstance(annotation.get("content", {}), dict) else {}
    return {
        "path": annotation_path,
        "annotation_id": content.get("annotation_id", annotation.get("id", "")),
        "annotator": content.get("annotator", ""),
        "overall_score": content.get("overall_score", 0),
        "verdict": content.get("verdict", ""),
        "scores": content.get("scores", {}) if isinstance(content.get("scores", {}), dict) else {},
        "confidence": content.get("confidence"),
    }


def _human_consensus(storage: LocalStorage, case: dict[str, Any]) -> tuple[dict[str, float], dict[str, Any]]:
    """Aggregate linked annotations without persisting raw annotation text."""

    raw_paths = case.get("annotation_paths", []) if isinstance(case.get("annotation_paths", []), list) else []
    paths = _dedupe([str(case.get("annotation_path") or ""), *[str(item) for item in raw_paths if str(item or "").strip()]])
    rows: list[dict[str, Any]] = []
    for path in paths:
        try:
            data = storage.read_json(resolve_path(storage.root, path))
        except (FileNotFoundError, ValueError):
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        scores = content.get("scores", {}) if isinstance(content.get("scores", {}), dict) else {}
        if scores:
            rows.append({
                "annotator": str(content.get("annotator") or ""),
                "verdict": str(content.get("verdict") or ""),
                "scores": {str(key): _score_0_1(value) for key, value in scores.items()},
            })
    dimensions = sorted({dimension for row in rows for dimension in row["scores"]})
    consensus = {
        dimension: round(sum(row["scores"].get(dimension, 0.0) for row in rows) / max(1, len(rows)), 4)
        for dimension in dimensions
    }
    pairwise_errors: list[float] = []
    for index, left in enumerate(rows):
        for right in rows[index + 1 :]:
            shared = set(left["scores"]) & set(right["scores"])
            pairwise_errors.extend(abs(left["scores"][dimension] - right["scores"][dimension]) for dimension in shared)
    agreement = round(1.0 - (sum(pairwise_errors) / len(pairwise_errors) if pairwise_errors else 0.0), 4)
    return consensus, {
        "annotator_count": len(rows),
        "annotators": sorted({row["annotator"] for row in rows if row["annotator"]}),
        "verdicts": sorted({row["verdict"] for row in rows if row["verdict"]}),
        "pairwise_mean_absolute_error": round(sum(pairwise_errors) / len(pairwise_errors), 4) if pairwise_errors else 0.0,
        "agreement_score": agreement,
        "agreement_status": "passed" if len(rows) <= 1 or agreement >= 0.8 else "needs_review",
    }


def _human_calibration_summary(comparisons: list[dict[str, Any]]) -> dict[str, Any]:
    metas = [row.get("human_calibration", {}) for row in comparisons if isinstance(row.get("human_calibration", {}), dict)]
    annotators = {str(annotator) for meta in metas for annotator in meta.get("annotators", []) if str(annotator or "").strip()}
    annotator_count = max(max((int(meta.get("annotator_count") or 0) for meta in metas), default=0), len(annotators))
    agreement_scores = [float(meta.get("agreement_score") or 0.0) for meta in metas if int(meta.get("annotator_count") or 0) > 1]
    annotated_case_count = sum(1 for meta in metas if int(meta.get("annotator_count") or 0) > 0)
    mean_agreement = round(sum(agreement_scores) / len(agreement_scores), 4) if agreement_scores else None
    production_ready = bool(annotated_case_count >= 2 and len(annotators) >= 2 and mean_agreement is not None and mean_agreement >= 0.8)
    return {
        "case_count": len(comparisons),
        "annotated_case_count": annotated_case_count,
        "annotator_count_max": annotator_count,
        "unique_annotator_count": len(annotators),
        "mean_agreement_score": mean_agreement,
        "production_ready": production_ready,
        "agreement_boundary": "single_annotator_is_baseline_only; multi_annotator_agreement_should_be_at_least_0.8",
        "production_boundary": "requires_at_least_two_annotated_cases_two_annotators_and_agreement_at_least_0.8",
    }


def _calibrated_threshold_recommendation(comparisons: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive conservative 0-100 provider thresholds from labelled cases."""

    ready_scores: list[float] = []
    non_ready_scores: list[float] = []
    for row in comparisons:
        scores = row.get("dimension_errors", {}) if isinstance(row.get("dimension_errors", {}), dict) else {}
        observed = [float(value.get("observed", 0.0)) for value in scores.values() if isinstance(value, dict)]
        if not observed:
            continue
        overall = sum(observed) / len(observed) * 100.0
        verdict = str(row.get("expected_verdict") or "").strip().lower()
        if verdict in {"pass", "passed", "ready", "accept", "accepted"}:
            ready_scores.append(overall)
        elif verdict in {"block", "blocked", "needs_revision", "revise", "fail", "failed"}:
            non_ready_scores.append(overall)
    baseline = {"ready": 80.0, "needs_revision": 65.0, "blocked": 50.0}
    if ready_scores:
        baseline["ready"] = round(min(ready_scores), 2)
    if ready_scores and non_ready_scores:
        baseline["needs_revision"] = round((max(non_ready_scores) + min(ready_scores)) / 2.0, 2)
        baseline["blocked"] = round(max(0.0, baseline["needs_revision"] - 15.0), 2)
    baseline["ready"] = max(baseline["ready"], baseline["needs_revision"] + 1.0)
    baseline["needs_revision"] = max(baseline["needs_revision"], baseline["blocked"] + 1.0)
    return {
        "thresholds": baseline,
        "labelled_ready_case_count": len(ready_scores),
        "labelled_non_ready_case_count": len(non_ready_scores),
        "minimum_evidence": "thresholds are recommendations until a multi-case, human-labelled calibration set is reviewed",
    }


def _target_lookup_keys(storage: LocalStorage, row: dict[str, Any]) -> list[str]:
    keys = [str(row.get("target_asset_id") or ""), str(row.get("target_asset_path") or "")]
    path = str(row.get("target_asset_path") or "")
    if path:
        try:
            keys.append(_display_path(storage.root, resolve_path(storage.root, path)))
        except (FileNotFoundError, ValueError):
            pass
    return _dedupe(keys)


def _score_0_1(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = 0.0
    if score > 1.0 and score <= 100.0:
        score = score / 100.0
    return round(max(0.0, min(1.0, score)), 4)


def _load_or_default_suite(storage: LocalStorage, suite_path: str | Path | None) -> dict[str, Any]:
    if suite_path:
        return storage.read_json(resolve_path(storage.root, suite_path))
    for path in reversed(storage.list_json("runs")):
        data = _read_json_safe(storage, path)
        if data.get("type") == "evaluation_suite" and data.get("content", {}).get("status") == "active":
            return data
    return create_evaluation_suite(storage, name="Default Novel OS Quality Suite")["asset"]


def _recent_evaluation_targets(storage: LocalStorage, *, project_id: str = "") -> list[str]:
    target_types = {
        "outline",
        "chapter_plan",
        "draft_chapter",
        "review_report",
        "context_bundle",
        "rag_quality_report",
        "agent_run",
        "workflow_run",
        "loop_run",
        "longform_recap_report",
        "publish_gate_report",
        "release_package",
        "reader_feedback_backflow_report",
    }
    paths: list[str] = []
    for category in ["drafts", "reviews", "contexts", "runs", "loops", "publishing", "feedback", "outlines", "chapter_plans"]:
        for path in reversed(storage.list_json(category)):
            data = _read_json_safe(storage, path)
            if data.get("type") not in target_types:
                continue
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            if project_id and str(metadata.get("project_id", "")) != project_id:
                continue
            paths.append(_display_path(storage.root, path))
            if len(paths) >= 12:
                return paths
    return paths


def _create_review_issue_for_evaluation(storage: LocalStorage, target: dict[str, Any], evaluation_result: dict[str, Any], *, project_id: str) -> dict[str, Any]:
    try:
        from novel_forge.modules.review_issue import create_review_issue

        return create_review_issue(
            storage,
            {
                "project_id": project_id,
                "target_asset_id": str(target.get("id", "")),
                "target_asset_type": str(target.get("type", "")),
                "issue_type": "context_budget_overflow" if evaluation_result.get("scores", {}).get("source_isolation", 1) < 0.5 else "plot_logic_gap",
                "severity": "critical",
                "blocking": True,
                "message": "Evaluation gate blocked this asset.",
                "fix_suggestion": "Inspect evaluation_result and revise before publish gate.",
                "source_system": "evaluation_center",
                "evidence_refs": [evaluation_result.get("path", "")],
            },
        )
    except Exception:
        return {}


def _contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return any(child_key == key or _contains_key(child, key) for child_key, child in value.items())
    if isinstance(value, list):
        return any(_contains_key(child, key) for child in value)
    return False


def _read_json_safe(storage: LocalStorage, path: Path) -> dict[str, Any]:
    try:
        data = storage.read_json(path)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _validate_expected(expected_output_type: Any, raw_output: dict[str, Any]) -> dict[str, Any]:
    expected = str(expected_output_type or "generate")
    if expected in {"generate", "review", "analyze", "revise"}:
        return validate_model_output(expected, raw_output)
    return raw_output


def _score_output(task: Any, output: dict[str, Any], *, status: str, latency_ms: float) -> dict[str, Any]:
    if status != "succeeded":
        return {"overall": 0, "schema": 0, "latency": 0, "output_chars": 0}
    text = str(output.get("text") or output.get("summary") or output)
    rubric = task.content.get("rubric", {}) if isinstance(task.content.get("rubric", {}), dict) else {}
    schema_score = 100 if output else 0
    length_target = int(rubric.get("target_chars", 800))
    length_score = min(100, int((len(text) / max(1, length_target)) * 100))
    latency_score = max(0, 100 - int(latency_ms / 1000))
    overall = round(schema_score * 0.45 + length_score * 0.35 + latency_score * 0.2, 2)
    return {"overall": overall, "schema": schema_score, "length": length_score, "latency": latency_score, "output_chars": len(text)}


def _default_capabilities(task_types: list[str]) -> dict[str, Any]:
    return {
        "task_types": task_types,
        "supports_json_output": True,
        "supports_long_context": False,
        "supports_batch": False,
        "local_safe": True,
    }


def _default_rubric(task_type: str) -> dict[str, Any]:
    return {
        "task_type": task_type,
        "dimensions": ["schema_validity", "instruction_following", "usefulness", "latency"],
        "weights": {"schema_validity": 0.45, "instruction_following": 0.2, "usefulness": 0.25, "latency": 0.1},
        "target_chars": 800,
    }


def _default_prompt_template(task_type: str) -> str:
    return f"Run a deterministic {task_type} benchmark for Novel Forge using the provided input assets."


def _read_run(storage: LocalStorage, value: str | Path) -> dict[str, Any]:
    path = resolve_path(storage.root, value)
    data = storage.read_json(path)
    if not isinstance(data, dict) or data.get("type") != "model_benchmark_run":
        raise ValueError(f"path must point to a model_benchmark_run asset: {value}")
    return {"path": _display_path(storage.root, path), "id": data.get("id", ""), "asset": data, "content": data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}}


def _read_comparison(storage: LocalStorage, value: str | Path) -> dict[str, Any]:
    path = resolve_path(storage.root, value)
    data = storage.read_json(path)
    if not isinstance(data, dict) or data.get("type") != "model_comparison_report":
        raise ValueError(f"path must point to a model_comparison_report asset: {value}")
    return {"path": _display_path(storage.root, path), "id": data.get("id", ""), "asset": data, "content": data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}}


def _run_summary(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    content = row["content"]
    return {
        "id": row["id"],
        "path": row["path"],
        "provider": content.get("provider", ""),
        "model_name": content.get("model_name", ""),
        "status": content.get("status", ""),
        "overall": content.get("scores", {}).get("overall", 0) if isinstance(content.get("scores", {}), dict) else 0,
        "latency_ms": content.get("latency_ms", 0),
    }


def _common_task_type(runs: list[dict[str, Any]]) -> str:
    values = {str(row["content"].get("task_type", "")) for row in runs if row["content"].get("task_type")}
    return values.pop() if len(values) == 1 else "mixed"


def _recommendation(ranked: list[dict[str, Any]]) -> str:
    if not ranked:
        return "needs_more_runs"
    winner = _run_summary(ranked[0])
    return f"prefer {winner.get('provider', '')}/{winner.get('model_name', '')} for this benchmark until a stronger run is recorded"


def _estimate_run_cost(storage: LocalStorage, *, provider: str, model_name: str, scores: dict[str, Any], task: Any) -> dict[str, Any]:
    profile = _model_profile(storage, provider=provider, model_name=model_name)
    cost_profile = profile.get("content", {}).get("cost_profile", {}) if isinstance(profile.get("content", {}), dict) else {}
    input_per_1k = float(cost_profile.get("input_per_1k", 0) or 0)
    output_per_1k = float(cost_profile.get("output_per_1k", 0) or 0)
    prompt_chars = len(str(task.content.get("prompt_template", ""))) + len(str(task.content.get("input_assets", [])))
    output_chars = int(scores.get("output_chars", 0) or 0)
    input_tokens = max(1, int(prompt_chars / 4))
    output_tokens = max(1, int(output_chars / 4))
    estimated = round((input_tokens / 1000) * input_per_1k + (output_tokens / 1000) * output_per_1k, 6)
    return {
        "currency": cost_profile.get("currency", "USD"),
        "input_tokens_estimate": input_tokens,
        "output_tokens_estimate": output_tokens,
        "cost": estimated,
        "source": "model_profile.cost_profile" if cost_profile else "default_zero_cost",
    }


def _model_profile(storage: LocalStorage, *, provider: str, model_name: str) -> dict[str, Any]:
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "model_profile":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if str(content.get("provider", "")) == provider and str(content.get("model_name", "")) == model_name:
            return data
    return {"content": {"cost_profile": {"input_per_1k": 0, "output_per_1k": 0, "currency": "USD"}}}


def _active_model_candidates(storage: LocalStorage) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for path in storage.list_json("runs"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "model_profile":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        status = str(content.get("status", "") or data.get("metadata", {}).get("status", ""))
        if status not in {"active", "candidate", "default"}:
            continue
        provider = str(content.get("provider") or data.get("metadata", {}).get("provider") or "").strip()
        model_name = str(content.get("model_name") or data.get("metadata", {}).get("model_name") or "").strip()
        if provider and model_name:
            candidates.append({"provider": provider, "model_name": model_name})
    return candidates[:12]


def _latest_active_routing_policy(storage: LocalStorage, *, project_id: str | None = None) -> dict[str, Any] | None:
    policies: list[dict[str, Any]] = []
    for path in storage.list_json("runs"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "model_routing_policy":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if content.get("status") != "active":
            continue
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        policies.append({**data, "path": _display_path(storage.root, path)})
    return sorted(policies, key=lambda item: str(item.get("updated_at", "")), reverse=True)[0] if policies else None


def _asset_ref(storage: LocalStorage, value: str | Path) -> dict[str, str]:
    path = resolve_path(storage.root, value)
    if path.exists() and path.is_file():
        asset = storage.read_asset(path)
        return {"id": asset.id, "type": asset.type, "title": asset.title or asset.name, "path": _display_path(storage.root, path)}
    return {"id": str(value), "type": "", "title": "", "path": str(value)}


def _project_scope(storage: LocalStorage, refs: list[dict[str, str]], *, workspace_path: str | None = None) -> dict[str, Any]:
    if workspace_path:
        return project_scope_from_asset(storage, {}, workspace_path=workspace_path)
    for ref in refs:
        path = ref.get("path", "")
        if not path:
            continue
        try:
            asset = storage.read_asset(resolve_path(storage.root, path))
        except Exception:
            continue
        project = project_scope_from_asset(storage, asset, input_path=path)
        if project.get("project_id") or project.get("workspace_path"):
            return project
    return {"project_id": "", "workspace_path": "", "title": ""}


def _write(
    storage: LocalStorage,
    asset: BaseAsset,
) -> dict[str, Any]:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "id": asset.id, "asset": asset.to_dict(), "validation": {"ok": True, "errors": []}}


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
