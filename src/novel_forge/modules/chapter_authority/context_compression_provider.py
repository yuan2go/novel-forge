from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.contracts import ExecutionRuntimeClass


CONTEXT_MODEL_STAGES = frozenset({"context_compress", "context_fidelity"})


def compression_boundary_identity(boundary: Mapping[str, Any], *, strict: bool = False) -> dict[str, Any]:
    if strict:
        if type(boundary.get("accepted_through_chapter")) is not int or boundary["accepted_through_chapter"] < 0:
            raise KernelError("ACCEPTED_BOUNDARY_INVALID", "Accepted frontier must be explicitly known")
        for current, legacy in (("canon_snapshot_asset_version_id", "canon_snapshot_version"), ("story_state_asset_version_id", "story_state_snapshot_version")):
            if (not (boundary.get(current) or boundary.get(legacy))
                or (current in boundary and legacy in boundary and boundary[current] != boundary[legacy])):
                raise KernelError("ACCEPTED_BOUNDARY_INVALID", "Frozen state identities are missing or conflicting")
    return {
        "accepted_through_chapter": int(boundary.get("accepted_through_chapter") or 0),
        "canon_snapshot_asset_version_id": str(boundary.get("canon_snapshot_asset_version_id") or boundary.get("canon_snapshot_version") or ""),
        "story_state_asset_version_id": str(boundary.get("story_state_asset_version_id") or boundary.get("story_state_snapshot_version") or ""),
    }


def context_compression_task_view(stage: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    task = inputs.get("context_compression_task")
    if not isinstance(task, Mapping):
        raise KernelError("CONTEXT_COMPRESSION_TASK_INVALID", "frozen compression task is required")
    units = task.get("units")
    required = task.get("required_unit_ids")
    reference = (task.get("task") or {}).get("stage") == "reference_analysis"
    boundary_key = "observation_boundary" if reference else "accepted_boundary"
    boundary = task.get(boundary_key)
    if reference:
        from novel_forge.modules.source_authority.observation import observation_boundary
        observation_boundary(boundary)
        if task.get("accepted_boundary"):
            raise KernelError("CONTEXT_COMPRESSION_BOUNDARY_TYPE", "reference cannot claim accepted Canon")
    if (
        task.get("contract_version") != "task-context-compression.v1"
        or not isinstance(boundary, Mapping)
        or not isinstance(units, list)
        or not units
        or len(units) > 256
        or not isinstance(required, list)
        or not str(task.get("memo_fingerprint") or "")
        or not str(task.get("policy_version") or "")
        or not 1 <= int(task.get("target_tokens") or 0) <= 512_000
    ):
        raise KernelError("CONTEXT_COMPRESSION_TASK_INVALID", "compression needs a bounded source chunk and frozen task boundary")
    if not reference:
        compression_boundary_identity(boundary, strict=True)
    ids = []
    projected = []
    for unit in units:
        if not isinstance(unit, Mapping) or not isinstance(unit.get("text"), str) or not unit["text"].strip():
            raise KernelError("CONTEXT_COMPRESSION_TASK_INVALID", "compression units require exact text")
        unit_id = str(unit.get("unit_id") or "")
        if not unit_id or len(unit_id) > 200 or unit_id in ids:
            raise KernelError("CONTEXT_COMPRESSION_TASK_INVALID", "compression unit identities must be unique and bounded")
        ids.append(unit_id)
        projected.append({key: deepcopy(unit[key]) for key in (
            "unit_id", "text", "required", "kind", "subject", "time", "epistemic_status",
        ) if key in unit})
    if len(required) != len(set(required)) or set(required) - set(ids):
        raise KernelError("CONTEXT_COMPRESSION_TASK_INVALID", "required semantic units must belong to this exact chunk")
    from novel_forge.modules.canon_graph.background import without_private_world
    from novel_forge.modules.story_design_authority.author_input import without_author_private
    host_task = dict(task.get("task") or {})
    semantic_task = {key: deepcopy(value) for key, value in host_task.items() if key in {"stage", "chapter", "goal", "preserve_quotes"}}
    if isinstance(host_task.get("plan"), dict):
        from .chapter_plan_views import build_draft_plan_view
        plan = dict(host_task["plan"])
        plan.setdefault("source_chapter_plan_asset_version_id", "")
        plan.setdefault("source_chapter_plan_content_hash", "")
        projected_plan = without_private_world(without_author_private(build_draft_plan_view(plan)))
        semantic_task["plan"] = {key: value for key, value in projected_plan.items() if not key.startswith("source_") and value not in (None, "", [], {})}
    result = {
        "contract_version": task["contract_version"],
        "stage": stage,
        boundary_key: deepcopy(dict(boundary)),
        "memo_fingerprint": task["memo_fingerprint"],
        "policy_version": task["policy_version"],
        "task": semantic_task,
        "units": projected,
        "required_unit_ids": list(required),
        "target_tokens": int(task["target_tokens"]),
        "authority_boundary": "DERIVED_EXTRACT_ONLY",
    }
    if stage == "context_fidelity":
        selected = task.get("selected_unit_ids")
        if not isinstance(selected, list) or len(selected) != len(set(selected)) or set(selected) - set(ids):
            raise KernelError("CONTEXT_COMPRESSION_TASK_INVALID", "fidelity requires exact proposed extract identities")
        result["selected_unit_ids"] = list(selected)
    return result


def require_task_reasoning(route: Any, *, task_scoped: bool) -> None:
    if not task_scoped:
        return
    authorization = getattr(route, "task_reasoning_authorization", None)
    authorized = (isinstance(authorization, tuple) and len(authorization) == 2
        and authorization[0] == route.model_profile.reasoning_effort
        and isinstance(authorization[1], str) and authorization[1].startswith("sha256:")
        and len(authorization[1]) == 71)
    if authorization is not None and not authorized:
        raise KernelError("TASK_CONTEXT_REASONING_AUTHORIZATION_DRIFT", "Selected task reasoning differs from its frozen route authorization")
    if route.route_policy.reasoning_downgrade_policy != "PROHIBITED":
        raise KernelError("TASK_CONTEXT_REASONING_DOWNGRADE_FORBIDDEN", "task-scoped execution cannot permit a reasoning downgrade")


def requires_full_output_reserve(route: Any) -> bool:
    profile = getattr(route, "model_profile", None)
    return (
        getattr(profile, "backend_id", "") == "codex-cli"
        and getattr(profile, "runtime_class", None)
        == ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE
    )


CLI_CONTEXT_HEADROOM_POLICY = "codex-cli-context-headroom.v1"


def context_headroom_output_reserve(route: Any, input_tokens: int) -> int:
    if not requires_full_output_reserve(route) or input_tokens <= 0:
        raise KernelError("PROVIDER_OUTPUT_POLICY_INVALID", "Context headroom requires a complete Codex CLI input reservation")
    remaining = int(route.model_context_limit) - input_tokens
    if remaining <= 0:
        raise KernelError("CONTEXT_CAPACITY_EXCEEDED", "Complete input leaves no model context for generation")
    return remaining


def planning_input_capacity(route: Any) -> int:
    output_floor = 1 if getattr(route, "output_reservation_policy", "") == CLI_CONTEXT_HEADROOM_POLICY else route.model_output_limit
    return min(512_000, route.model_context_limit - output_floor - route.token_safety_margin - route.token_framing_overhead)


def task_provider_output_reserve(stage: str, route: Any, *, router_binding_pending: bool = False, input_tokens: int | None = None) -> int:
    if getattr(route, "output_reservation_policy", "") == CLI_CONTEXT_HEADROOM_POLICY:
        return context_headroom_output_reserve(route, input_tokens) if input_tokens is not None else int(route.model_context_limit)
    target = 4096 if stage == "context_compress" else 2048 if stage == "context_fidelity" else 16_384 if stage in {
        "draft", "revision", "review", "rereview", "screenplay_generate", "screenplay_revision",
    } else 8192
    model_limit = int(getattr(route, "model_output_limit", 0) or 0)
    if route is not None and route.model_profile.model_provider == "scripted_provider_v2":
        model_limit = model_limit or 262_144
    if model_limit <= 0:
        if router_binding_pending and not requires_full_output_reserve(route):
            return target
        raise KernelError("TASK_CONTEXT_MODEL_OUTPUT_CAPACITY_UNKNOWN", "task-scoped Provider output capacity must be explicitly bound")
    return model_limit if requires_full_output_reserve(route) else min(target, model_limit)


def require_task_output_reserve(
    stage: str, route: Any, output_reserve: int, *, capacity_error_code: str, input_tokens: int | None = None,
) -> None:
    required_reserve = task_provider_output_reserve(stage, route, input_tokens=input_tokens)
    if getattr(route, "output_reservation_policy", "") == CLI_CONTEXT_HEADROOM_POLICY:
        if input_tokens is None or output_reserve != required_reserve:
            raise KernelError("PROVIDER_OUTPUT_POLICY_DRIFT", "Output reservation must equal the frozen complete-input context headroom")
        return
    if requires_full_output_reserve(route):
        if output_reserve < required_reserve:
            raise KernelError("TASK_CONTEXT_CLI_OUTPUT_RESERVATION_INSUFFICIENT", "Codex CLI requires the full selected model output and reasoning capacity to be reserved")
    elif output_reserve > required_reserve:
        raise KernelError(capacity_error_code, "frozen output reserve exceeds the selected task or model bound")
