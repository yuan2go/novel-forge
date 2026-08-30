"""INVARIANT: Closed approval policy contracts for Capability Pack admission.

The policy is intentionally independent from PostgreSQL.  Application commands,
rollout mutation, and runtime admission all call the same evaluator so an
approval record cannot be treated as display-only metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping, Sequence

from novel_forge.modules.command_kernel.errors import KernelError

from .domain import CapabilityPackScope, RolloutStatus, ScopeType


APPROVAL_SCOPE_SCHEMA_VERSION = "CapabilityPackApprovalScope.v1"


class LimitationType(StrEnum):
    INFORMATIONAL = "INFORMATIONAL"
    ADMISSION_CONSTRAINT = "ADMISSION_CONSTRAINT"
    ROLLOUT_CONSTRAINT = "ROLLOUT_CONSTRAINT"
    EXPIRY_CONSTRAINT = "EXPIRY_CONSTRAINT"


_SCOPE_KEYS = frozenset(
    {
        "schema_version",
        "allowed_environments",
        "allowed_runtime_profiles",
        "allowed_release_channels",
        "allowed_scope_types",
        "allowed_project_ids",
        "allowed_workspace_ids",
        "allowed_book_ids",
        "allowed_workflow_definition_refs",
        "allow_canary",
        "allow_percentage_rollout",
        "allow_full_rollout",
        "maximum_rollout_percentage",
    }
)


def _strings(payload: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{key} must be an array of exact strings")
    normalized = tuple(str(item) for item in value)
    if any(not item.strip() for item in normalized) or len(set(normalized)) != len(
        normalized
    ):
        raise ValueError(f"{key} must contain unique non-empty strings")
    return normalized


def _boolean(payload: Mapping[str, Any], key: str) -> bool:
    value = payload.get(key)
    if type(value) is not bool:
        raise ValueError(f"{key} must be boolean")
    return value


@dataclass(frozen=True, slots=True)
class CapabilityPackApprovalScope:
    allowed_environments: tuple[str, ...]
    allowed_runtime_profiles: tuple[str, ...]
    allowed_release_channels: tuple[str, ...]
    allowed_scope_types: tuple[ScopeType, ...]
    allowed_project_ids: tuple[str, ...]
    allowed_workspace_ids: tuple[str, ...]
    allowed_book_ids: tuple[str, ...]
    allowed_workflow_definition_refs: tuple[str, ...]
    allow_canary: bool
    allow_percentage_rollout: bool
    allow_full_rollout: bool
    maximum_rollout_percentage: float
    schema_version: str = APPROVAL_SCOPE_SCHEMA_VERSION

    @classmethod
    def from_payload(
        cls, payload: Mapping[str, Any]
    ) -> "CapabilityPackApprovalScope":
        unknown = sorted(set(payload) - _SCOPE_KEYS)
        missing = sorted(_SCOPE_KEYS - set(payload))
        if unknown or missing:
            details = []
            if unknown:
                details.append("unknown=" + ",".join(unknown))
            if missing:
                details.append("missing=" + ",".join(missing))
            raise ValueError("approval scope is not the closed v1 protocol: " + "; ".join(details))
        if str(payload.get("schema_version") or "") != APPROVAL_SCOPE_SCHEMA_VERSION:
            raise ValueError("approval scope schema_version is unsupported")
        scope_values = _strings(payload, "allowed_scope_types")
        try:
            scope_types = tuple(ScopeType(value) for value in scope_values)
        except ValueError as exc:
            raise ValueError("allowed_scope_types contains an unknown scope") from exc
        try:
            maximum = float(payload["maximum_rollout_percentage"])
        except (TypeError, ValueError) as exc:
            raise ValueError("maximum_rollout_percentage must be numeric") from exc
        if isinstance(payload["maximum_rollout_percentage"], bool) or not 0 <= maximum <= 100:
            raise ValueError("maximum_rollout_percentage must be between 0 and 100")
        result = cls(
            allowed_environments=_strings(payload, "allowed_environments"),
            allowed_runtime_profiles=_strings(payload, "allowed_runtime_profiles"),
            allowed_release_channels=_strings(payload, "allowed_release_channels"),
            allowed_scope_types=scope_types,
            allowed_project_ids=_strings(payload, "allowed_project_ids"),
            allowed_workspace_ids=_strings(payload, "allowed_workspace_ids"),
            allowed_book_ids=_strings(payload, "allowed_book_ids"),
            allowed_workflow_definition_refs=_strings(
                payload, "allowed_workflow_definition_refs"
            ),
            allow_canary=_boolean(payload, "allow_canary"),
            allow_percentage_rollout=_boolean(
                payload, "allow_percentage_rollout"
            ),
            allow_full_rollout=_boolean(payload, "allow_full_rollout"),
            maximum_rollout_percentage=maximum,
        )
        if not result.allowed_environments:
            raise ValueError("approval scope must allow at least one environment")
        if not result.allowed_runtime_profiles:
            raise ValueError("approval scope must allow at least one runtime profile")
        if not result.allowed_release_channels:
            raise ValueError("approval scope must allow at least one release channel")
        if not result.allowed_scope_types:
            raise ValueError("approval scope must allow at least one scope type")
        if not result.allowed_workflow_definition_refs:
            raise ValueError("approval scope must allow at least one workflow")
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "allowed_environments": list(self.allowed_environments),
            "allowed_runtime_profiles": list(self.allowed_runtime_profiles),
            "allowed_release_channels": list(self.allowed_release_channels),
            "allowed_scope_types": [item.value for item in self.allowed_scope_types],
            "allowed_project_ids": list(self.allowed_project_ids),
            "allowed_workspace_ids": list(self.allowed_workspace_ids),
            "allowed_book_ids": list(self.allowed_book_ids),
            "allowed_workflow_definition_refs": list(
                self.allowed_workflow_definition_refs
            ),
            "allow_canary": self.allow_canary,
            "allow_percentage_rollout": self.allow_percentage_rollout,
            "allow_full_rollout": self.allow_full_rollout,
            "maximum_rollout_percentage": self.maximum_rollout_percentage,
        }

    def require_admission(
        self,
        *,
        scope: CapabilityPackScope,
        environment: str,
        runtime_profile: str,
        release_channel: str,
        workflow_definition_ref: str,
        limitations: Sequence[Mapping[str, Any]] = (),
        now: datetime | None = None,
    ) -> None:
        violations: list[str] = []
        if environment not in self.allowed_environments:
            violations.append("environment")
        if runtime_profile not in self.allowed_runtime_profiles:
            violations.append("runtime_profile")
        if release_channel not in self.allowed_release_channels:
            violations.append("release_channel")
        if scope.scope_type not in self.allowed_scope_types:
            violations.append("scope_type")
        if (
            self.allowed_project_ids
            and scope.scope_type is not ScopeType.SYSTEM
            and scope.project_id not in self.allowed_project_ids
        ):
            violations.append("project_id")
        if (
            self.allowed_workspace_ids
            and scope.scope_type in {ScopeType.WORKSPACE, ScopeType.BOOK}
            and scope.workspace_id not in self.allowed_workspace_ids
        ):
            violations.append("workspace_id")
        if (
            self.allowed_book_ids
            and scope.scope_type is ScopeType.BOOK
            and scope.book_id not in self.allowed_book_ids
        ):
            violations.append("book_id")
        if workflow_definition_ref not in self.allowed_workflow_definition_refs:
            violations.append("workflow_definition_ref")
        violations.extend(
            _limitation_violations(
                limitations,
                phase="ADMISSION",
                environment=environment,
                runtime_profile=runtime_profile,
                release_channel=release_channel,
                scope_type=scope.scope_type.value,
                now=now,
            )
        )
        if violations:
            raise KernelError(
                "CAPABILITY_PACK_APPROVAL_SCOPE_DENIED",
                "Approval Scope rejects admission: "
                + ", ".join(sorted(set(violations))),
            )

    def require_rollout(
        self,
        *,
        mode: RolloutStatus,
        percentage: float,
        limitations: Sequence[Mapping[str, Any]] = (),
        now: datetime | None = None,
    ) -> None:
        normalized = RolloutStatus(mode)
        violations: list[str] = []
        if percentage < 0 or percentage > self.maximum_rollout_percentage:
            violations.append("maximum_rollout_percentage")
        if normalized is RolloutStatus.CANARY and not self.allow_canary:
            violations.append("allow_canary")
        if (
            normalized is RolloutStatus.PERCENTAGE
            and not self.allow_percentage_rollout
        ):
            violations.append("allow_percentage_rollout")
        if normalized is RolloutStatus.FULL and not self.allow_full_rollout:
            violations.append("allow_full_rollout")
        violations.extend(
            _limitation_violations(
                limitations,
                phase="ROLLOUT",
                mode=normalized.value,
                percentage=percentage,
                now=now,
            )
        )
        if violations:
            raise KernelError(
                "CAPABILITY_PACK_APPROVAL_ROLLOUT_DENIED",
                "Approval Scope rejects rollout: "
                + ", ".join(sorted(set(violations))),
            )


_LIMITATION_KEYS = frozenset(
    {"limitation_type", "code", "value", "message"}
)


def normalize_limitations(values: Sequence[Any]) -> tuple[dict[str, Any], ...]:
    normalized: list[dict[str, Any]] = []
    for value in values:
        if isinstance(value, str):
            if not value.strip():
                raise ValueError("legacy informational limitation cannot be empty")
            normalized.append(
                {
                    "limitation_type": LimitationType.INFORMATIONAL.value,
                    "code": "LEGACY_TEXT",
                    "value": None,
                    "message": value,
                }
            )
            continue
        if not isinstance(value, Mapping):
            raise ValueError("limitation must be a string or closed object")
        unknown = sorted(set(value) - _LIMITATION_KEYS)
        missing = sorted(_LIMITATION_KEYS - set(value))
        if unknown or missing:
            raise ValueError("limitation is not the closed v1 protocol")
        limitation_type = LimitationType(str(value["limitation_type"]))
        code = str(value["code"])
        message = str(value["message"])
        if not code or not message:
            raise ValueError("limitation code and message are required")
        normalized.append(
            {
                "limitation_type": limitation_type.value,
                "code": code,
                "value": value["value"],
                "message": message,
            }
        )
    return tuple(normalized)


def _limitation_violations(
    limitations: Sequence[Mapping[str, Any]],
    *,
    phase: str,
    now: datetime | None = None,
    **facts: Any,
) -> list[str]:
    violations: list[str] = []
    current = now or datetime.now(timezone.utc)
    for raw in limitations:
        item = dict(raw)
        limitation_type = LimitationType(str(item.get("limitation_type") or ""))
        code = str(item.get("code") or "")
        value = item.get("value")
        if limitation_type is LimitationType.INFORMATIONAL:
            continue
        if limitation_type is LimitationType.EXPIRY_CONSTRAINT:
            if code != "NOT_AFTER" or not isinstance(value, str):
                raise KernelError(
                    "CAPABILITY_PACK_LIMITATION_INVALID",
                    "EXPIRY_CONSTRAINT requires NOT_AFTER ISO timestamp",
                )
            deadline = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            if current >= deadline:
                violations.append(code)
            continue
        expected_type = (
            LimitationType.ADMISSION_CONSTRAINT
            if phase == "ADMISSION"
            else LimitationType.ROLLOUT_CONSTRAINT
        )
        if limitation_type is not expected_type:
            continue
        if code.startswith("DENY_"):
            fact_name = code.removeprefix("DENY_").lower()
            if facts.get(fact_name) == value:
                violations.append(code)
        elif code == "MAXIMUM_PERCENTAGE" and phase == "ROLLOUT":
            try:
                if float(facts.get("percentage") or 0) > float(value):
                    violations.append(code)
            except (TypeError, ValueError) as exc:
                raise KernelError(
                    "CAPABILITY_PACK_LIMITATION_INVALID",
                    "MAXIMUM_PERCENTAGE limitation must be numeric",
                ) from exc
        else:
            raise KernelError(
                "CAPABILITY_PACK_LIMITATION_INVALID",
                f"unsupported enforced limitation: {code}",
            )
    return violations


__all__ = [
    "APPROVAL_SCOPE_SCHEMA_VERSION",
    "CapabilityPackApprovalScope",
    "LimitationType",
    "normalize_limitations",
]
