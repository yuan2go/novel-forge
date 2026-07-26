from __future__ import annotations

from typing import Any

from novel_forge.modules.model_router import create_model_route
from novel_forge.modules.production_execution import (
    create_legacy_development_model_adapter,
)
from novel_forge.storage.local import LocalStorage


class FixtureProviderAdapter:
    def __init__(self, *, response: dict[str, Any], provider_evidence: dict[str, Any] | None = None, provider_name: str = "fixture-provider") -> None:
        self.response = response
        self.name = provider_name
        self.external_provider_evidence = provider_evidence or {}

    def generate(self, payload: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return dict(self.response)

    def review(self, payload: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return dict(self.response)


def ensure_model_route_from_payload(
    storage: LocalStorage,
    *,
    task_type: str,
    payload: dict[str, Any],
    project_id: str = "",
    workspace_path: str = "",
    environment: str = "",
) -> dict[str, Any] | None:
    route = payload.get("provider_route", {}) if isinstance(payload.get("provider_route", {}), dict) else {}
    provider_config = payload.get("provider_config", {}) if isinstance(payload.get("provider_config", {}), dict) else {}
    if not route and not provider_config:
        return None
    provider = str(route.get("provider") or provider_config.get("provider") or "mock")
    model_name = str(route.get("model_name") or provider_config.get("model_name") or provider_config.get("model") or "mock-model")
    approval = payload.get("operator_approval", {}) if isinstance(payload.get("operator_approval", {}), dict) else {}
    route_allowlist = route.get("production_provider_allowlist")
    config_allowlist = provider_config.get("production_provider_allowlist")
    production_provider_allowlist = route_allowlist if isinstance(route_allowlist, list) else config_allowlist if isinstance(config_allowlist, list) else None
    return create_model_route(
        storage,
        task_type=str(route.get("task_type") or task_type),
        provider=provider,
        model_name=model_name,
        fallbacks=route.get("fallbacks") if isinstance(route.get("fallbacks"), list) else [],
        selection_rule=str(route.get("selection_rule") or "balanced"),
        max_cost_per_run=float(route.get("max_cost_per_run") or payload.get("budget_cap") or provider_config.get("budget_cap") or 0.0),
        max_latency_ms=int(route.get("max_latency_ms") or provider_config.get("max_latency_ms") or 0),
        status=str(route.get("status") or "active"),
        project_id=project_id,
        workspace_path=workspace_path,
        environment=str(route.get("environment") or environment or ""),
        approval_status=str(route.get("approval_status") or approval.get("status") or ""),
        approval_id=str(route.get("approval_id") or approval.get("approval_id") or ""),
        approved_by=str(route.get("approved_by") or approval.get("approved_by") or ""),
        approval_reason=str(route.get("approval_reason") or approval.get("reason") or ""),
        production_provider_allowlist=production_provider_allowlist,
        mock_provider_test_mode=bool(route.get("mock_provider_test_mode") or payload.get("allow_mock_fixture") or provider_config.get("mock_provider_test_mode")),
    )


def adapter_from_provider_payload(payload: dict[str, Any], *, default_operation: str) -> Any | None:
    provider_config = payload.get("provider_config", {}) if isinstance(payload.get("provider_config", {}), dict) else {}
    fixture_response = payload.get("fixture_response") if isinstance(payload.get("fixture_response"), dict) else payload.get("fixture_judge_response") if isinstance(payload.get("fixture_judge_response"), dict) else payload.get("fixture_chapter_response") if isinstance(payload.get("fixture_chapter_response"), dict) else None
    mode = str(payload.get("mode") or provider_config.get("mode") or ("fixture" if fixture_response else "real")).strip().lower()
    provider = str(provider_config.get("provider") or payload.get("provider") or "").strip().lower()
    if fixture_response:
        if mode == "real" and not payload.get("allow_mock_fixture"):
            raise ValueError("fixture response requires allow_mock_fixture=true unless mode is fixture")
        return FixtureProviderAdapter(
            response=fixture_response,
            provider_evidence=provider_config.get("external_provider_evidence") if isinstance(provider_config.get("external_provider_evidence"), dict) else {},
            provider_name=provider or "fixture-provider",
        )
    if mode == "fixture":
        raise ValueError("fixture mode requires fixture_response")
    if not provider:
        return None
    model_name = str(provider_config.get("model_name") or provider_config.get("model") or "").strip()
    return create_legacy_development_model_adapter(
        provider=provider,
        model_name=model_name,
        environment=str(
            payload.get("environment")
            or provider_config.get("environment")
            or ""
        ),
    )
