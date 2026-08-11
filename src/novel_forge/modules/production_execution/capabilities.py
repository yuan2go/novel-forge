"""Governed capability identifiers and immutable execution definitions."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from .contracts import ExecutionRuntimeClass


_CAPABILITY_ID = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_BACKEND_ID = re.compile(r"^[a-z0-9][a-z0-9._*-]*$")


class CapabilityId(StrEnum):
    CREATIVE_TOPIC_GENERATE = "creative.topic.generate"
    CREATIVE_PROPOSAL_GENERATE = "creative.proposal.generate"
    THEME_QUESTION_GENERATE = "theme.question.generate"
    ENDING_INTENT_GENERATE = "ending.intent.generate"
    WORLD_DESIGN_GENERATE = "world.design.generate"
    CHARACTER_CAST_GENERATE = "character.cast.generate"
    PLANNING_BOOK_GENERATE = "planning.book.generate"
    PLANNING_VOLUME_GENERATE = "planning.volume.generate"
    PLANNING_ARC_GENERATE = "planning.arc.generate"
    PLANNING_CHAPTER_GROUP_GENERATE = "planning.chapter_group.generate"
    PLANNING_CHAPTER_GENERATE = "planning.chapter.generate"
    PLANNING_STORY_CHAPTER_GENERATE = "planning.story_chapter.generate"
    PROSE_CHAPTER_DRAFT = "prose.chapter.draft"
    REVIEW_CHAPTER_EVALUATE = "review.chapter.evaluate"
    REVISION_CHAPTER_REVISE = "revision.chapter.revise"
    CANON_EXTRACT = "canon.extract"
    TEMPORAL_QUERY = "temporal.query"
    CANON_VALIDATE = "canon.validate"
    CONTINUITY_VALIDATE = "continuity.validate"
    HOOK_ANALYZE = "hook.analyze"
    PACING_ANALYZE = "pacing.analyze"
    PACING_AGGREGATE = "pacing.aggregate"
    WORLD_CONSEQUENCE_ANALYZE = "world.consequence.analyze"
    FACT_VERIFY = "fact.verify"
    DECONSTRUCTION_OBSERVE = "deconstruction.observe"
    QUALITY_INTRINSIC_JUDGE = "quality.intrinsic.judge"
    QUALITY_AGGREGATE = "quality.aggregate"
    QUALITY_ORIGINALITY_JUDGE = "quality.originality.judge"
    QUALITY_PLATFORM_JUDGE = "quality.platform.judge"
    QUALITY_READER_OUTCOME_JUDGE = "quality.reader_outcome.judge"
    QUALITY_PAIRWISE_JUDGE = "quality.pairwise.judge"
    MKAOS_KNOWLEDGE_EXTRACT = "mkaos.knowledge.extract"
    MKAOS_RULE_EXTRACT = "mkaos.rule.extract"
    MKAOS_TEMPLATE_EXTRACT = "mkaos.template.extract"
    RETRIEVAL_EMBED = "retrieval.embed"
    RETRIEVAL_RERANK = "retrieval.rerank"
    RETRIEVAL_INDEX_UPSERT = "retrieval.index.upsert"
    RETRIEVAL_INDEX_QUERY = "retrieval.index.query"
    LONGFORM_RECAP_ANALYZE = "longform.recap.analyze"
    LONGFORM_PLAN_VS_ACTUAL_JUDGE = "longform.plan_vs_actual.judge"
    LONGFORM_ARC_CLOSURE_JUDGE = "longform.arc_closure.judge"
    LONGFORM_PLAN_CHANGE_GENERATE = "longform.plan_change.generate"
    AGENT_WORKSPACE_EXECUTE = "agent.workspace.execute"
    PUBLISHING_RELEASE_SUBMIT = "publishing.release.submit"
    PUBLISHING_RELEASE_QUERY = "publishing.release.query"
    PUBLISHING_RELEASE_WITHDRAW = "publishing.release.withdraw"
    FEEDBACK_PLATFORM_FETCH = "feedback.platform.fetch"
    SOURCE_REMOTE_FETCH = "source.remote.fetch"
    NOTIFICATION_SEND = "notification.send"
    STORAGE_OBJECT_PUT = "storage.object.put"
    TOOL_REMOTE_INVOKE = "tool.remote.invoke"
    ANALYTICS_QUERY_EXECUTE = "analytics.query.execute"


class ExecutionDomain(StrEnum):
    CREATIVE = "creative"
    THEME = "theme"
    ENDING = "ending"
    WORLD = "world"
    CHARACTER = "character"
    PLANNING = "planning"
    PROSE = "prose"
    REVIEW = "review"
    REVISION = "revision"
    CANON = "canon"
    QUALITY = "quality"
    MKAOS = "mkaos"
    RETRIEVAL = "retrieval"
    LONGFORM = "longform"
    AGENT = "agent"
    PUBLISHING = "publishing"
    FEEDBACK = "feedback"
    SOURCE = "source"
    NOTIFICATION = "notification"
    STORAGE = "storage"
    TOOL = "tool"
    ANALYTICS = "analytics"
    DECONSTRUCTION = "deconstruction"


class RiskClass(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    capability_id: CapabilityId
    domain: ExecutionDomain
    input_schema_ref: str
    output_schema_ref: str
    allowed_runtime_classes: tuple[ExecutionRuntimeClass, ...]
    allowed_backend_ids: tuple[str, ...]
    prompt_bundle_type: str
    skill_bundle_type: str
    timeout_policy_ref: str
    budget_policy_ref: str
    permission_policy_ref: str
    source_policy_ref: str
    validation_policy_ref: str
    commit_policy_ref: str
    requires_provider_idempotency: bool
    supports_query: bool
    supports_cancel: bool
    supports_callback: bool
    fixture_allowed: bool
    production_allowed: bool
    risk_class: RiskClass

    def __post_init__(self) -> None:
        capability_id = (
            self.capability_id
            if isinstance(self.capability_id, CapabilityId)
            else CapabilityId(str(self.capability_id))
        )
        domain = (
            self.domain
            if isinstance(self.domain, ExecutionDomain)
            else ExecutionDomain(str(self.domain))
        )
        risk = (
            self.risk_class
            if isinstance(self.risk_class, RiskClass)
            else RiskClass(str(self.risk_class))
        )
        runtimes = tuple(
            item
            if isinstance(item, ExecutionRuntimeClass)
            else ExecutionRuntimeClass(str(item))
            for item in self.allowed_runtime_classes
        )
        backends = tuple(str(item).strip().lower() for item in self.allowed_backend_ids)
        object.__setattr__(self, "capability_id", capability_id)
        object.__setattr__(self, "domain", domain)
        object.__setattr__(self, "risk_class", risk)
        object.__setattr__(self, "allowed_runtime_classes", runtimes)
        object.__setattr__(self, "allowed_backend_ids", backends)
        required = (
            self.input_schema_ref,
            self.output_schema_ref,
            self.prompt_bundle_type,
            self.skill_bundle_type,
            self.timeout_policy_ref,
            self.budget_policy_ref,
            self.permission_policy_ref,
            self.source_policy_ref,
            self.validation_policy_ref,
            self.commit_policy_ref,
        )
        if not _CAPABILITY_ID.fullmatch(capability_id.value):
            raise ValueError("capability ID is invalid")
        if not all(value.strip() for value in required):
            raise ValueError("capability definition has an empty governance reference")
        if not runtimes or not backends:
            raise ValueError(
                "capability definition requires runtime and backend allowlists"
            )
        if any(not _BACKEND_ID.fullmatch(item) for item in backends):
            raise ValueError("capability definition has an invalid backend allowlist")
        if not self.fixture_allowed and not self.production_allowed:
            raise ValueError(
                "capability must be admitted in at least one environment class"
            )
        if (
            ExecutionRuntimeClass.SCRIPTED_FIXTURE in runtimes
            and not self.fixture_allowed
        ):
            raise ValueError("fixture runtime requires fixture_allowed")
        if self.requires_provider_idempotency and not self.production_allowed:
            raise ValueError(
                "Provider idempotency has no meaning on a fixture-only capability"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id.value,
            "domain": self.domain.value,
            "input_schema_ref": self.input_schema_ref,
            "output_schema_ref": self.output_schema_ref,
            "allowed_runtime_classes": [
                item.value for item in self.allowed_runtime_classes
            ],
            "allowed_backend_ids": list(self.allowed_backend_ids),
            "prompt_bundle_type": self.prompt_bundle_type,
            "skill_bundle_type": self.skill_bundle_type,
            "timeout_policy_ref": self.timeout_policy_ref,
            "budget_policy_ref": self.budget_policy_ref,
            "permission_policy_ref": self.permission_policy_ref,
            "source_policy_ref": self.source_policy_ref,
            "validation_policy_ref": self.validation_policy_ref,
            "commit_policy_ref": self.commit_policy_ref,
            "requires_provider_idempotency": self.requires_provider_idempotency,
            "supports_query": self.supports_query,
            "supports_cancel": self.supports_cancel,
            "supports_callback": self.supports_callback,
            "fixture_allowed": self.fixture_allowed,
            "production_allowed": self.production_allowed,
            "risk_class": self.risk_class.value,
        }

    @property
    def contract_hash(self) -> str:
        encoded = json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CapabilityDefinition":
        return cls(
            capability_id=CapabilityId(str(payload.get("capability_id") or "")),
            domain=ExecutionDomain(str(payload.get("domain") or "")),
            input_schema_ref=str(payload.get("input_schema_ref") or ""),
            output_schema_ref=str(payload.get("output_schema_ref") or ""),
            allowed_runtime_classes=tuple(
                ExecutionRuntimeClass(str(item))
                for item in payload.get("allowed_runtime_classes") or ()
            ),
            allowed_backend_ids=tuple(
                str(item) for item in payload.get("allowed_backend_ids") or ()
            ),
            prompt_bundle_type=str(payload.get("prompt_bundle_type") or ""),
            skill_bundle_type=str(payload.get("skill_bundle_type") or ""),
            timeout_policy_ref=str(payload.get("timeout_policy_ref") or ""),
            budget_policy_ref=str(payload.get("budget_policy_ref") or ""),
            permission_policy_ref=str(payload.get("permission_policy_ref") or ""),
            source_policy_ref=str(payload.get("source_policy_ref") or ""),
            validation_policy_ref=str(payload.get("validation_policy_ref") or ""),
            commit_policy_ref=str(payload.get("commit_policy_ref") or ""),
            requires_provider_idempotency=_strict_bool(
                payload.get("requires_provider_idempotency"),
                "requires_provider_idempotency",
            ),
            supports_query=_strict_bool(
                payload.get("supports_query"), "supports_query"
            ),
            supports_cancel=_strict_bool(
                payload.get("supports_cancel"), "supports_cancel"
            ),
            supports_callback=_strict_bool(
                payload.get("supports_callback"), "supports_callback"
            ),
            fixture_allowed=_strict_bool(
                payload.get("fixture_allowed"), "fixture_allowed"
            ),
            production_allowed=_strict_bool(
                payload.get("production_allowed"), "production_allowed"
            ),
            risk_class=RiskClass(str(payload.get("risk_class") or "")),
        )


def _strict_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be boolean")
    return value


__all__ = [
    "CapabilityDefinition",
    "CapabilityId",
    "ExecutionDomain",
    "RiskClass",
]
