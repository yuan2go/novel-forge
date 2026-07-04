from __future__ import annotations

from typing import Any


def check_flow_binding(card: dict[str, Any]) -> dict[str, Any]:
    content = card.get("content", {}) if isinstance(card.get("content", {}), dict) else card
    flows = [str(item) for item in content.get("applicable_flows") or [] if str(item).strip()]
    return {"passed": bool(flows), "flow_binding_coverage": 1.0 if flows else 0.0, "applicable_flows": flows}
