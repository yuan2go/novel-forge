from __future__ import annotations

from typing import Any


RULE_FIELDS = ("rule", "scope", "cost", "exception", "observable_consequence", "narrative_function", "conflict_potential", "failure_mode", "canon_policy")


def build_world_bible(*, project_id: str, creative_brief_version_id: str, rules: list[dict[str, Any]], entities: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    if not project_id or not creative_brief_version_id or not rules:
        raise ValueError("world generation requires project, brief version and rules")
    report = validate_world_rules(project_id=project_id, rules=rules)
    return {
        "project_id": project_id, "creative_brief_version_id": creative_brief_version_id,
        "world_premise": entities.get("world_premise", []), "rules": rules,
        "factions": entities.get("factions", []), "institutions": entities.get("institutions", []),
        "locations": entities.get("locations", []), "resources": entities.get("resources", []),
        "technology_or_magic_systems": entities.get("systems", []), "economy": entities.get("economy", []),
        "social_hierarchy": entities.get("social_hierarchy", []), "information_boundaries": entities.get("information_boundaries", []),
        "historical_events": entities.get("historical_events", []), "conflict_sources": entities.get("conflict_sources", []),
        "daily_life_impacts": entities.get("daily_life_impacts", []), "validation": report,
    }


def validate_world_rules(*, project_id: str, rules: list[dict[str, Any]]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    for index, rule in enumerate(rules):
        missing = [field for field in RULE_FIELDS if rule.get(field) in (None, "")]
        if missing:
            issues.append({"code": "WORLD_RULE_INCOMPLETE", "rule_index": index, "missing": missing, "severity": "blocking"})
        if str(rule.get("cost", "")).lower() in {"none", "unlimited", "zero"}:
            issues.append({"code": "UNLIMITED_CAPABILITY", "rule_index": index, "severity": "blocking"})
        for other_index, other in enumerate(rules[:index]):
            if rule.get("scope") == other.get("scope") and rule.get("rule_key") == other.get("rule_key") and rule.get("rule") != other.get("rule"):
                issues.append({"code": "WORLD_RULE_CONFLICT", "rule_index": index, "conflicts_with": other_index, "severity": "blocking"})
    return {"project_id": project_id, "issues": issues, "passed": not any(item["severity"] == "blocking" for item in issues), "report_type": "WorldRuleConflictReport"}


__all__ = ["build_world_bible", "validate_world_rules"]
