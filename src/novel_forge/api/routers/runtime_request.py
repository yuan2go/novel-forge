from __future__ import annotations

from typing import Any

from novel_forge.modules.os_envelope import normalize_runtime_request_policy

MUTATING_PRODUCT_METHODS = {"POST", "PATCH", "PUT", "DELETE"}


def normalize_product_api_runtime_request(request: Any, *, operation: str) -> dict[str, Any]:
    payload = request if isinstance(request, dict) else getattr(request, "model_dump", lambda: {})()
    if not isinstance(payload, dict):
        payload = {}
    envelope = payload.get("os_envelope") if isinstance(payload.get("os_envelope"), dict) else payload.get("envelope") if isinstance(payload.get("envelope"), dict) else {}
    source_policy = payload.get("source_policy") if isinstance(payload.get("source_policy"), dict) else {}
    return normalize_runtime_request_policy(
        envelope_payload=envelope or None,
        environment=str(payload.get("environment") or ""),
        source_policy=source_policy or None,
        operation=operation,
    )


async def normalize_product_api_request_state(request: Any) -> dict[str, Any]:
    """Normalize runtime policy for every product API request.

    Routers can opt into stricter service-level handling, but the API layer
    should still parse the same environment/envelope/source-policy contract for
    all `/product/...` traffic. The normalized policy is stored on
    ``request.state.runtime_request_policy`` by the middleware.
    """

    payload = await _json_payload(request)
    query = getattr(request, "query_params", {})
    headers = getattr(request, "headers", {})
    environment = (
        payload.get("environment")
        or _mapping_get(query, "environment")
        or _mapping_get(query, "mode")
        or _mapping_get(headers, "x-novel-forge-environment")
        or _mapping_get(headers, "x-novel-forge-runtime-mode")
        or ""
    )
    source_policy = payload.get("source_policy") if isinstance(payload.get("source_policy"), dict) else {}
    envelope = payload.get("os_envelope") if isinstance(payload.get("os_envelope"), dict) else payload.get("envelope") if isinstance(payload.get("envelope"), dict) else {}
    policy = normalize_runtime_request_policy(
        envelope_payload=envelope or None,
        environment=str(environment or ""),
        source_policy=source_policy or None,
        operation=f"{getattr(request, 'method', 'GET')} {getattr(getattr(request, 'url', None), 'path', '')}",
    )
    policy["api_surface"] = "product"
    policy["request_path"] = str(getattr(getattr(request, "url", None), "path", ""))
    policy["request_method"] = str(getattr(request, "method", "GET")).upper()
    policy["normalized_at_api_boundary"] = True
    return policy


def product_api_policy_violation(policy: dict[str, Any]) -> str:
    method = str(policy.get("request_method", "GET")).upper()
    if not policy.get("production") or method not in MUTATING_PRODUCT_METHODS:
        return ""
    if not isinstance(policy.get("envelope"), dict) or not policy["envelope"]:
        return "OS envelope required for production product API mutation"
    return ""


def product_api_policy_response_headers(policy: dict[str, Any]) -> dict[str, str]:
    return {
        "x-novel-forge-runtime-policy": "normalized",
        "x-novel-forge-runtime-environment": str(policy.get("environment") or ""),
        "x-novel-forge-runtime-production": "true" if policy.get("production") else "false",
    }


async def _json_payload(request: Any) -> dict[str, Any]:
    method = str(getattr(request, "method", "GET")).upper()
    if method not in MUTATING_PRODUCT_METHODS:
        return {}
    content_type = str(_mapping_get(getattr(request, "headers", {}), "content-type") or "").lower()
    if content_type and "json" not in content_type:
        return {}
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _mapping_get(mapping: Any, key: str) -> Any:
    try:
        return mapping.get(key)
    except Exception:
        return None
