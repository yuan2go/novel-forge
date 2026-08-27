"""Frozen contract and bounded orchestration for Quality Qualification.

The runner owns only proof scope and recovery invariants.  A supplied runtime
port performs Canonical Runtime work and remains the owner of Provider calls,
Chapter acceptance, Reader/Recap, and Authority persistence.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from time import monotonic
from typing import Any, Iterable, Mapping, Protocol

from novel_forge.modules.chapter_authority.execution_gateway import (
    default_chapter_fixture_response,
)
from novel_forge.modules.chapter_quality_authority.qualification import (
    QualityCampaignManifest,
)
from novel_forge.modules.story_planning_runtime.execution import (
    _chapter_function_row,
    _fixture_chapter_shape,
    _fixture_character_arc_stage,
    planning_fixture_response,
)


PROFILE_SCHEMA_VERSION = "novel-forge.bounded-quality-campaign-profile.v1"
QUALITY_CHAPTER_GROUPS = ((1, 4), (5, 8))
QUALITY_CHAPTERS = tuple(range(1, 9))
_ROUTE_STAGES = frozenset(
    {"planning", "generator", "reviewer", "judge", "reader_proxy"}
)
_PACK_ROLES = frozenset({"planning", "chapter", "reader_proxy", "narrative_evaluation"})
_HUMAN_CHOICES = ("A", "B", "TIE", "CANNOT_JUDGE")
_HUMAN_DIMENSIONS = (
    "overall_preference",
    "readability",
    "character_credibility",
    "scene_effectiveness",
    "tension_momentum",
    "emotional_impact",
    "prose_quality",
    "continuity",
    "payoff_satisfaction",
    "desire_to_continue",
)
_PROFILE_FIELDS = frozenset(
    {
        "schema_version",
        "profile_id",
        "profile_version",
        "book",
        "chapter_group_ranges",
        "baseline_protocol",
        "provider_routes",
        "capability_pack_requirements",
        "prompt_skill_lineage",
        "profiles",
        "human_protocol",
        "budget_policy",
        "stop_policy",
    }
)
_SEMANTIC_EVIDENCE_DROPPED_KEYS = frozenset(
    {
        "acceptance_id",
        "source_acceptance_ids",
        "reader_source_asset_version_ids",
        "project_id",
        "book_id",
        "created_at",
        "updated_at",
    }
)
_SEMANTIC_ARC_KEYS = frozenset(
    {
        "arc_plan_version_id",
        "arc_plan_version_ids",
        "linked_arc_ids",
        "active_arc_ids",
        "open_arc_ids",
    }
)


class QualityCampaignTerminalError(RuntimeError):
    """A bounded campaign violation that must become terminal evidence."""

    def __init__(
        self,
        failure_code: str,
        message: str,
        *,
        reasons: tuple[str, ...] = (),
        measurements: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_code = failure_code
        self.reasons = reasons
        self.measurements = dict(measurements or {})


def classify_campaign_recovery_exhaustion(
    operations: Iterable[Mapping[str, Any]],
    *,
    root_operation_id: str,
    error_code: str,
) -> QualityCampaignTerminalError | None:
    """Turn an unrecoverable Chapter subtree into terminal campaign evidence."""

    exhausted: list[dict[str, Any]] = []
    for raw in operations:
        operation_id = str(raw.get("operation_id") or "")
        status = str(raw.get("status") or "")
        attempt_count = int(raw.get("attempt_count") or 0)
        max_attempts = int(raw.get("max_attempts") or 0)
        if not operation_id or max_attempts <= 0:
            continue
        if status in {"FAILED_FINAL", "DEAD_LETTER"} or (
            status == "FAILED_RETRYABLE" and attempt_count >= max_attempts
        ):
            exhausted.append(
                {
                    "operation_id": operation_id,
                    "status": status,
                    "attempt_count": attempt_count,
                    "max_attempts": max_attempts,
                }
            )
    if not exhausted:
        return None
    exhausted.sort(key=lambda item: str(item["operation_id"]))
    reasons = tuple(
        "runtime_recovery_exhausted:"
        f"{item['operation_id']}:{item['status']}:"
        f"{item['attempt_count']}/{item['max_attempts']}"
        for item in exhausted
    )
    return QualityCampaignTerminalError(
        "CAMPAIGN_RUNTIME_RECOVERY_EXHAUSTED",
        "bounded Quality campaign exhausted Chapter Runtime recovery",
        reasons=reasons,
        measurements={
            "root_operation_id": root_operation_id,
            "kernel_error_code": error_code,
            "exhausted_operations": exhausted,
        },
    )


_SEMANTIC_IDENTITY_SUFFIXES = (
    "_asset_version_id",
    "_asset_version_ids",
    "_content_hash",
    "_operation_id",
    "_operation_ids",
    "_attempt_id",
    "_effect_id",
    "_effect_ids",
    "_receipt_ref",
    "_route_snapshot_id",
)


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("quality campaign profile must be canonical JSON") from exc


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _semantic_evidence_value(value: Any, *, field: str = "") -> Any:
    if field in _SEMANTIC_ARC_KEYS:
        if isinstance(value, (list, tuple)):
            return ["<ARC>" for _item in value]
        return "<ARC>" if value else value
    if field == "arc_statuses" and isinstance(value, (list, tuple)):
        return [
            ["<ARC>", item[1]]
            for item in value
            if isinstance(item, (list, tuple)) and len(item) == 2
        ]
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            if key in _SEMANTIC_EVIDENCE_DROPPED_KEYS or key.endswith(
                _SEMANTIC_IDENTITY_SUFFIXES
            ):
                continue
            normalized[key] = _semantic_evidence_value(item, field=key)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_semantic_evidence_value(item, field=field) for item in value]
    return value


def semantic_quality_evidence_identity(value: Mapping[str, Any]) -> str:
    """Hash narrative semantics while excluding generated runtime identity."""

    if not isinstance(value, Mapping) or not value:
        raise ValueError("semantic Quality evidence must be a non-empty object")
    return _digest(_semantic_evidence_value(value))


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{field} must be a non-empty object")
    return {str(key): item for key, item in value.items()}


def _required(value: Any, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{field} is required")
    return result


def _sha256(value: Any, field: str) -> str:
    result = _required(value, field)
    digest = result.removeprefix("sha256:").lower()
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError(f"{field} must be a SHA-256 identity")
    return "sha256:" + digest


@dataclass(frozen=True, slots=True)
class BoundedQualityCampaignProfile:
    profile_id: str
    profile_version: int
    chapter_group_ranges: tuple[tuple[int, int], ...]
    chapter_limit: int
    required_evaluator_count: int
    chapter_pairs_per_evaluator: int
    arc_pairs_per_evaluator: int
    _canonical_payload: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "BoundedQualityCampaignProfile":
        if not isinstance(raw, Mapping):
            raise ValueError("quality campaign profile root must be an object")
        supplied = frozenset(str(key) for key in raw)
        missing = sorted(_PROFILE_FIELDS - supplied)
        unknown = sorted(supplied - _PROFILE_FIELDS)
        if missing:
            raise ValueError("quality campaign profile lacks: " + ", ".join(missing))
        if unknown:
            raise ValueError(
                "quality campaign profile has unknown: " + ", ".join(unknown)
            )
        payload = json.loads(_canonical(dict(raw)))
        if payload["schema_version"] != PROFILE_SCHEMA_VERSION:
            raise ValueError("unsupported bounded Quality campaign profile")
        profile_id = _required(payload["profile_id"], "profile_id")
        profile_version = int(payload["profile_version"] or 0)
        if profile_version <= 0:
            raise ValueError("profile_version must be positive")

        book = _mapping(payload["book"], "book")
        for field in (
            "title",
            "language",
            "bounded_volume_scope",
            "primary_arc_scope",
        ):
            _required(book.get(field), f"book.{field}")
        if int(book.get("target_chapters") or 0) != 8:
            raise ValueError("book.target_chapters must equal eight")

        raw_ranges = payload["chapter_group_ranges"]
        if not isinstance(raw_ranges, list) or not all(
            isinstance(item, list) and len(item) == 2 for item in raw_ranges
        ):
            raise ValueError("chapter_group_ranges must be a list of pairs")
        ranges = tuple((int(item[0]), int(item[1])) for item in raw_ranges)
        if ranges != QUALITY_CHAPTER_GROUPS:
            raise ValueError("chapter_group_ranges must be exactly [1,4] and [5,8]")

        baseline = _mapping(payload["baseline_protocol"], "baseline_protocol")
        comparable = (
            baseline.get("kind") == "FIRST_DRAFT_VS_ACCEPTED_REVISION"
            and all(
                baseline.get(field) is True
                for field in (
                    "shared_story_foundation",
                    "shared_chapter_goal",
                    "shared_accepted_boundary",
                    "shared_context",
                    "provider_model_parity",
                    "comparable_token_budget",
                )
            )
            and baseline.get("controlled_difference")
            == "REVIEW_REVISION_REREVIEW_QUALITY_ACCEPTANCE"
        )
        if not comparable:
            raise ValueError("baseline_protocol must define a comparable baseline")

        routes = _mapping(payload["provider_routes"], "provider_routes")
        if set(routes) != {"scripted", "real"}:
            raise ValueError("provider_routes must define scripted and real modes")
        for mode, raw_mode in routes.items():
            mode_routes = _mapping(raw_mode, f"provider_routes.{mode}")
            if set(mode_routes) != _ROUTE_STAGES:
                raise ValueError(f"provider_routes.{mode} has incomplete stages")
            for stage, raw_route in mode_routes.items():
                route = _mapping(raw_route, f"provider_routes.{mode}.{stage}")
                for field in (
                    "provider",
                    "model",
                    "reasoning_effort",
                    "execution_class",
                ):
                    _required(route.get(field), f"{mode}.{stage}.{field}")
                if route.get("silent_fallback") is not False:
                    raise ValueError("Quality campaign routes forbid silent fallback")
                if stage in {"reviewer", "judge"}:
                    _required(
                        route.get("independence_relationship"),
                        f"{mode}.{stage}.independence_relationship",
                    )

        packs = _mapping(
            payload["capability_pack_requirements"],
            "capability_pack_requirements",
        )
        if set(packs) != _PACK_ROLES or any(not str(value) for value in packs.values()):
            raise ValueError("capability_pack_requirements are incomplete")

        lineage = _mapping(payload["prompt_skill_lineage"], "prompt_skill_lineage")
        for relative_path, expected_hash in lineage.items():
            path = Path(relative_path)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(
                    "prompt/Skill lineage paths must be repository-relative"
                )
            _sha256(expected_hash, f"prompt_skill_lineage.{relative_path}")

        profiles = _mapping(payload["profiles"], "profiles")
        for field in (
            "protocol_version",
            "evaluation_profile_version",
            "quality_profile_version",
            "reader_outcome_profile_version",
        ):
            _required(profiles.get(field), f"profiles.{field}")
        context = _mapping(profiles.get("context_policy"), "profiles.context_policy")
        if not (
            context.get("contract") == "context-manifest-v3"
            and context.get("protected_context_fail_closed") is True
            and context.get("accepted_history_only") is True
        ):
            raise ValueError(
                "Quality campaign requires fail-closed Context Manifest v3"
            )

        human = _mapping(payload["human_protocol"], "human_protocol")
        required_evaluators = int(human.get("required_evaluator_count") or 0)
        chapter_pairs = int(human.get("chapter_pairs_per_evaluator") or 0)
        arc_pairs = int(human.get("arc_pairs_per_evaluator") or 0)
        if required_evaluators != 2:
            raise ValueError("bounded Human protocol requires exactly two evaluators")
        if chapter_pairs != 8 or arc_pairs < 1:
            raise ValueError(
                "Human protocol requires eight Chapter pairs and an Arc pair"
            )
        if tuple(human.get("choices") or ()) != _HUMAN_CHOICES:
            raise ValueError("Human protocol choices differ from the frozen contract")
        if tuple(human.get("dimensions") or ()) != _HUMAN_DIMENSIONS:
            raise ValueError("Human protocol dimensions differ from the frozen rubric")
        if not (
            human.get("chapter_pair_order") == "STORY_SEQUENCE"
            and human.get("candidate_order") == "DETERMINISTIC_BALANCED_COMPLEMENTARY"
        ):
            raise ValueError("Human protocol ordering policy is invalid")

        budget = _mapping(payload["budget_policy"], "budget_policy")
        chapter_limit = int(budget.get("chapter_limit") or 0)
        if chapter_limit != 8:
            raise ValueError("budget_policy.chapter_limit must equal eight")
        positive_integer_fields = (
            "provider_call_limit",
            "retry_limit",
            "input_token_limit",
            "output_token_limit",
            "token_limit",
            "wall_clock_seconds",
        )
        if any(int(budget.get(field) or 0) <= 0 for field in positive_integer_fields):
            raise ValueError("all bounded campaign budget ceilings must be positive")
        if int(budget["token_limit"]) != int(budget["input_token_limit"]) + int(
            budget["output_token_limit"]
        ):
            raise ValueError("budget_policy.token_limit must equal input plus output")
        for field in (
            "cost_limit_per_call_usd",
            "cost_limit_per_operation_usd",
            "cost_limit_per_chapter_usd",
            "cost_limit_usd",
        ):
            try:
                cost_limit = float(budget.get(field) or 0)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"budget_policy.{field} must be positive") from exc
            if cost_limit <= 0:
                raise ValueError(f"budget_policy.{field} must be positive")
        if not (
            float(budget["cost_limit_per_call_usd"])
            <= float(budget["cost_limit_per_operation_usd"])
            <= float(budget["cost_limit_per_chapter_usd"])
            <= float(budget["cost_limit_usd"])
        ):
            raise ValueError("budget_policy cost ceilings are not monotonic")
        freeze_headroom = _mapping(
            budget.get("freeze_headroom_policy"),
            "budget_policy.freeze_headroom_policy",
        )
        minimum_remaining_provider_calls = int(
            freeze_headroom.get("minimum_remaining_provider_calls") or 0
        )
        minimum_remaining_tokens = int(
            freeze_headroom.get("minimum_remaining_tokens") or 0
        )
        try:
            minimum_remaining_cost = float(
                freeze_headroom.get("minimum_remaining_cost_usd") or 0
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("freeze headroom cost must be positive") from exc
        if not (
            0 < minimum_remaining_provider_calls <= int(budget["provider_call_limit"])
            and 0 < minimum_remaining_tokens <= int(budget["token_limit"])
            and 0 < minimum_remaining_cost <= float(budget["cost_limit_usd"])
        ):
            raise ValueError(
                "freeze headroom must fit inside bounded campaign ceilings"
            )

        stop = _mapping(payload["stop_policy"], "stop_policy")
        if not (
            int(stop.get("accepted_through_chapter") or 0) == 8
            and stop.get("chapter_9_allowed") is False
            and stop.get("background_continuation_allowed") is False
        ):
            raise ValueError(
                "stop_policy must forbid Chapter 9 and background continuation"
            )
        return cls(
            profile_id=profile_id,
            profile_version=profile_version,
            chapter_group_ranges=ranges,
            chapter_limit=chapter_limit,
            required_evaluator_count=required_evaluators,
            chapter_pairs_per_evaluator=chapter_pairs,
            arc_pairs_per_evaluator=arc_pairs,
            _canonical_payload=_canonical(payload),
        )

    @property
    def digest(self) -> str:
        return (
            "sha256:"
            + hashlib.sha256(self._canonical_payload.encode("utf-8")).hexdigest()
        )

    @property
    def provider_routes(self) -> dict[str, dict[str, dict[str, Any]]]:
        return self.to_dict()["provider_routes"]

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._canonical_payload)

    def allows_chapter(self, chapter_number: int) -> bool:
        return 1 <= int(chapter_number) <= self.chapter_limit

    def verify_repository_hashes(self, repository_root: str | Path) -> None:
        root = Path(repository_root).resolve()
        for relative_path, expected in self.to_dict()["prompt_skill_lineage"].items():
            source = (root / relative_path).resolve()
            if root not in source.parents or not source.is_file():
                raise ValueError(
                    f"prompt/Skill lineage source is missing: {relative_path}"
                )
            actual = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError(
                    f"prompt/Skill hash drift for {relative_path}: "
                    f"expected {expected}, actual {actual}"
                )

    def freeze_manifest(
        self,
        *,
        campaign_id: str,
        exact_release_sha: str,
        migration_head: str,
        mode: str,
        project_id: str,
        workspace_id: str,
        book_id: str,
        capability_pack_manifest: Mapping[str, Any],
        foundation_lineage: Mapping[str, Any],
        planning_lineage: Mapping[str, Any],
        realization_lineage: Mapping[str, Any],
    ) -> QualityCampaignManifest:
        payload = self.to_dict()
        if mode not in {"scripted", "real"}:
            raise ValueError("Quality campaign mode must be scripted or real")
        packs = _mapping(capability_pack_manifest, "capability_pack_manifest")
        if set(packs) != _PACK_ROLES:
            raise ValueError("frozen capability Pack manifest has incomplete roles")
        for role, raw_binding in packs.items():
            binding = _mapping(raw_binding, f"capability_pack_manifest.{role}")
            _required(binding.get("deployment_id"), f"{role}.deployment_id")
            _sha256(binding.get("hash"), f"{role}.hash")
        foundation = _mapping(foundation_lineage, "foundation_lineage")
        planning = _mapping(planning_lineage, "planning_lineage")
        realization = _mapping(realization_lineage, "realization_lineage")
        profiles = payload["profiles"]
        return QualityCampaignManifest.from_mapping(
            {
                "schema_version": "novel-forge.quality-qualification.v1",
                "campaign_id": _required(campaign_id, "campaign_id"),
                "campaign_version": self.profile_version,
                "exact_release_sha": exact_release_sha,
                "migration_head": migration_head,
                "protocol_version": profiles["protocol_version"],
                "evaluation_profile_version": profiles["evaluation_profile_version"],
                "quality_profile_version": profiles["quality_profile_version"],
                "reader_outcome_profile_version": profiles[
                    "reader_outcome_profile_version"
                ],
                "project_id": project_id,
                "workspace_id": workspace_id,
                "book_id": book_id,
                "chapter_group_ranges": [list(item) for item in QUALITY_CHAPTER_GROUPS],
                "provider_route_manifest": {
                    **payload["provider_routes"][mode],
                    "campaign_profile_digest": self.digest,
                    "mode": mode,
                },
                "capability_pack_manifest": packs,
                "prompt_skill_lineage": payload["prompt_skill_lineage"],
                "foundation_lineage": foundation,
                "planning_lineage": planning,
                "realization_lineage": realization,
                "context_policy": profiles["context_policy"],
                "baseline_protocol": payload["baseline_protocol"],
                "budget_policy": payload["budget_policy"],
                "required_evaluator_count": self.required_evaluator_count,
            }
        )


@dataclass(frozen=True, slots=True)
class CampaignExecutionCheckpoint:
    profile_digest: str
    accepted_through_chapter: int
    completed_group_ranges: tuple[tuple[int, int], ...]
    accepted_chapters: tuple[int, ...]
    provider_effect_ids: tuple[str, ...]

    def validate(self, profile: BoundedQualityCampaignProfile) -> None:
        if self.profile_digest != profile.digest:
            raise ValueError("campaign checkpoint profile digest drift")
        if self.accepted_through_chapter > 8 or any(
            chapter > 8 for chapter in self.accepted_chapters
        ):
            raise ValueError("campaign checkpoint attempts Chapter 9")
        if self.accepted_through_chapter < 0:
            raise ValueError("campaign checkpoint accepted cursor is invalid")
        if self.accepted_chapters != tuple(range(1, self.accepted_through_chapter + 1)):
            raise ValueError("campaign checkpoint accepted Chapters are not contiguous")
        if (
            self.completed_group_ranges
            != profile.chapter_group_ranges[: len(self.completed_group_ranges)]
        ):
            raise ValueError("campaign checkpoint completed groups are not a prefix")
        completed_through = (
            self.completed_group_ranges[-1][1] if self.completed_group_ranges else 0
        )
        if completed_through > self.accepted_through_chapter:
            raise ValueError("campaign checkpoint group completion exceeds acceptance")
        if len(set(self.provider_effect_ids)) != len(self.provider_effect_ids):
            raise ValueError("campaign checkpoint contains duplicate Provider effects")


class BoundedCampaignRuntime(Protocol):
    def run_group(self, chapter_range: tuple[int, int]) -> Mapping[str, Any]: ...

    def final_evidence(self) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class BoundedQualityCampaignResult:
    profile_digest: str
    chapter_group_ranges: tuple[tuple[int, int], ...]
    accepted_chapters: tuple[int, ...]
    accepted_through_chapter: int
    group_run_ids: tuple[str, ...]
    provider_effect_ids: tuple[str, ...]
    duplicate_provider_effect_ids: tuple[str, ...]
    reader_state_asset_version_ids: tuple[str, ...]
    recap_asset_version_ids: tuple[str, ...]
    arc_evaluation_count: int
    volume_evaluation_present: bool
    blind_pack_count: int
    semantic_evidence_hash: str
    provider_runtime_evidence_asset_version_id: str
    provider_runtime_evidence_content_hash: str
    provider_dispatch_count: int
    real_provider_call_count: int
    provider_failure_count: int
    provider_retry_count: int
    measured_input_tokens: int
    measured_output_tokens: int
    measured_total_tokens: int
    settled_cost_amount: str
    currency: str
    capability_pack_snapshot_count: int
    qualification_boundary: str

    @property
    def deterministic_identity(self) -> str:
        """Identity for one exact execution, including durable runtime ids."""

        return _digest(
            {
                "profile_digest": self.profile_digest,
                "chapter_group_ranges": self.chapter_group_ranges,
                "accepted_chapters": self.accepted_chapters,
                "accepted_through_chapter": self.accepted_through_chapter,
                "group_run_ids": self.group_run_ids,
                "provider_effect_ids": self.provider_effect_ids,
                "reader_state_asset_version_ids": self.reader_state_asset_version_ids,
                "recap_asset_version_ids": self.recap_asset_version_ids,
                "arc_evaluation_count": self.arc_evaluation_count,
                "volume_evaluation_present": self.volume_evaluation_present,
                "blind_pack_count": self.blind_pack_count,
                "semantic_evidence_hash": self.semantic_evidence_hash,
                "provider_runtime_evidence_asset_version_id": (
                    self.provider_runtime_evidence_asset_version_id
                ),
                "provider_runtime_evidence_content_hash": (
                    self.provider_runtime_evidence_content_hash
                ),
                "provider_dispatch_count": self.provider_dispatch_count,
                "real_provider_call_count": self.real_provider_call_count,
                "provider_failure_count": self.provider_failure_count,
                "provider_retry_count": self.provider_retry_count,
                "measured_input_tokens": self.measured_input_tokens,
                "measured_output_tokens": self.measured_output_tokens,
                "measured_total_tokens": self.measured_total_tokens,
                "settled_cost_amount": self.settled_cost_amount,
                "currency": self.currency,
                "capability_pack_snapshot_count": (self.capability_pack_snapshot_count),
                "qualification_boundary": self.qualification_boundary,
            }
        )

    @property
    def semantic_identity(self) -> str:
        """Cross-run identity that excludes generated ids and timestamps."""

        return _digest(
            {
                "profile_digest": self.profile_digest,
                "chapter_group_ranges": self.chapter_group_ranges,
                "accepted_chapters": self.accepted_chapters,
                "accepted_through_chapter": self.accepted_through_chapter,
                "provider_effect_count": len(self.provider_effect_ids),
                "duplicate_provider_effect_count": len(
                    self.duplicate_provider_effect_ids
                ),
                "reader_state_count": len(self.reader_state_asset_version_ids),
                "recap_count": len(self.recap_asset_version_ids),
                "arc_evaluation_count": self.arc_evaluation_count,
                "volume_evaluation_present": self.volume_evaluation_present,
                "blind_pack_count": self.blind_pack_count,
                "semantic_evidence_hash": self.semantic_evidence_hash,
                "provider_dispatch_count": self.provider_dispatch_count,
                "real_provider_call_count": self.real_provider_call_count,
                "provider_failure_count": self.provider_failure_count,
                "provider_retry_count": self.provider_retry_count,
                "measured_input_tokens": self.measured_input_tokens,
                "measured_output_tokens": self.measured_output_tokens,
                "measured_total_tokens": self.measured_total_tokens,
                "settled_cost_amount": self.settled_cost_amount,
                "currency": self.currency,
                "capability_pack_snapshot_count": (self.capability_pack_snapshot_count),
                "qualification_boundary": self.qualification_boundary,
            }
        )


class BoundedQualityCampaignRunner:
    def __init__(
        self,
        profile: BoundedQualityCampaignProfile,
        *,
        mode: str = "scripted",
    ) -> None:
        if mode not in {"scripted", "real"}:
            raise ValueError("Quality campaign mode must be scripted or real")
        self.profile = profile
        self.mode = mode

    def run(
        self,
        runtime: BoundedCampaignRuntime,
        *,
        checkpoint: CampaignExecutionCheckpoint | None = None,
    ) -> BoundedQualityCampaignResult:
        deadline = monotonic() + int(
            self.profile.to_dict()["budget_policy"]["wall_clock_seconds"]
        )

        def require_within_deadline() -> None:
            if monotonic() > deadline:
                raise QualityCampaignTerminalError(
                    "CAMPAIGN_WALL_CLOCK_BUDGET_EXPIRED",
                    "bounded Quality campaign wall-clock budget expired",
                    reasons=("wall_clock_seconds>wall_clock_budget",),
                    measurements={
                        "wall_clock_seconds": int(
                            self.profile.to_dict()["budget_policy"][
                                "wall_clock_seconds"
                            ]
                        )
                    },
                )

        checkpoint = checkpoint or CampaignExecutionCheckpoint(
            profile_digest=self.profile.digest,
            accepted_through_chapter=0,
            completed_group_ranges=(),
            accepted_chapters=(),
            provider_effect_ids=(),
        )
        checkpoint.validate(self.profile)
        accepted = list(checkpoint.accepted_chapters)
        completed = list(checkpoint.completed_group_ranges)
        effects = list(checkpoint.provider_effect_ids)
        group_ids: list[str] = [
            f"checkpoint-group:{start}-{end}" for start, end in completed
        ]
        reader_states: list[str] = []
        recaps: list[str] = []
        for chapter_range in self.profile.chapter_group_ranges:
            require_within_deadline()
            if chapter_range in completed:
                continue
            raw = dict(runtime.run_group(chapter_range))
            require_within_deadline()
            if (
                tuple(int(item) for item in raw.get("chapter_range") or ())
                != chapter_range
            ):
                raise ValueError(
                    "runtime ChapterGroup range differs from frozen profile"
                )
            group_chapters = tuple(
                int(item) for item in raw.get("accepted_chapters") or ()
            )
            expected = tuple(range(chapter_range[0], chapter_range[1] + 1))
            if group_chapters != expected:
                raise ValueError(
                    "runtime did not accept the exact ChapterGroup sequence"
                )
            group_effects = tuple(
                str(item) for item in raw.get("provider_effect_ids") or ()
            )
            if not group_effects:
                raise ValueError("runtime ChapterGroup has no Provider effect evidence")
            duplicates = sorted(set(effects).intersection(group_effects))
            duplicates.extend(
                sorted(
                    effect
                    for effect in set(group_effects)
                    if group_effects.count(effect) > 1
                )
            )
            if duplicates:
                raise ValueError(
                    "runtime duplicated Provider effects: "
                    + ", ".join(sorted(set(duplicates)))
                )
            reader_state = _required(
                raw.get("reader_state_asset_version_id"),
                "reader_state_asset_version_id",
            )
            recap = _required(
                raw.get("recap_asset_version_id"), "recap_asset_version_id"
            )
            group_id = _required(raw.get("group_run_id"), "group_run_id")
            accepted.extend(group_chapters)
            effects.extend(group_effects)
            completed.append(chapter_range)
            group_ids.append(group_id)
            reader_states.append(reader_state)
            recaps.append(recap)

        require_within_deadline()
        final = dict(runtime.final_evidence())
        require_within_deadline()
        if (
            tuple(accepted) != QUALITY_CHAPTERS
            or int(final.get("accepted_through_chapter") or 0) != 8
        ):
            raise ValueError("bounded Quality campaign did not stop at Chapter 8")
        arcs = final.get("arc_evaluations")
        volume = final.get("volume_evaluation")
        packs = final.get("blind_pack_ids")
        semantic_evidence_hash = _sha256(
            final.get("semantic_evidence_hash"),
            "semantic_evidence_hash",
        )
        provider_runtime = final.get("provider_runtime_evidence")
        if not isinstance(provider_runtime, Mapping) or not provider_runtime:
            raise ValueError("bounded Quality campaign lacks Provider runtime evidence")
        provider_runtime_asset_id = _required(
            final.get("provider_runtime_evidence_asset_version_id"),
            "provider_runtime_evidence_asset_version_id",
        )
        provider_runtime_content_hash = _sha256(
            final.get("provider_runtime_evidence_content_hash"),
            "provider_runtime_evidence_content_hash",
        )
        if not isinstance(arcs, list) or not arcs:
            raise ValueError("bounded Quality campaign lacks Arc evaluation")
        if not isinstance(volume, Mapping) or not volume:
            raise ValueError("bounded Quality campaign lacks Volume-slice evaluation")
        if not isinstance(packs, list) or len(packs) != 2:
            raise ValueError("bounded Quality campaign must export two blind packs")
        return BoundedQualityCampaignResult(
            profile_digest=self.profile.digest,
            chapter_group_ranges=tuple(completed),
            accepted_chapters=tuple(accepted),
            accepted_through_chapter=8,
            group_run_ids=tuple(group_ids),
            provider_effect_ids=tuple(effects),
            duplicate_provider_effect_ids=(),
            reader_state_asset_version_ids=tuple(reader_states),
            recap_asset_version_ids=tuple(recaps),
            arc_evaluation_count=len(arcs),
            volume_evaluation_present=True,
            blind_pack_count=len(packs),
            semantic_evidence_hash=semantic_evidence_hash,
            provider_runtime_evidence_asset_version_id=provider_runtime_asset_id,
            provider_runtime_evidence_content_hash=provider_runtime_content_hash,
            provider_dispatch_count=int(
                provider_runtime.get("provider_dispatch_count") or 0
            ),
            real_provider_call_count=int(
                provider_runtime.get("real_provider_call_count") or 0
            ),
            provider_failure_count=int(
                provider_runtime.get("provider_failure_count") or 0
            ),
            provider_retry_count=int(provider_runtime.get("provider_retry_count") or 0),
            measured_input_tokens=int(
                provider_runtime.get("measured_input_tokens") or 0
            ),
            measured_output_tokens=int(
                provider_runtime.get("measured_output_tokens") or 0
            ),
            measured_total_tokens=int(
                provider_runtime.get("measured_total_tokens") or 0
            ),
            settled_cost_amount=str(provider_runtime.get("settled_cost_amount") or "0"),
            currency=str(provider_runtime.get("currency") or ""),
            capability_pack_snapshot_count=len(
                provider_runtime.get("capability_pack_snapshots") or ()
            ),
            qualification_boundary=(
                "SCRIPTED_PROTOCOL_ONLY"
                if self.mode == "scripted"
                else "BOUNDED_REAL_PROVIDER_EVIDENCE"
            ),
        )


def load_quality_campaign_profile(
    path: str | Path,
    *,
    repository_root: str | Path | None = None,
) -> BoundedQualityCampaignProfile:
    source = Path(path)
    raw = json.loads(source.read_text(encoding="utf-8"))
    profile = BoundedQualityCampaignProfile.from_mapping(raw)
    if repository_root is not None:
        profile.verify_repository_hashes(repository_root)
    return profile


def _bounded_realization_event_chain(
    *, chapter_start: int, arc_plan_ids: tuple[str, ...]
) -> list[dict[str, Any]]:
    event_ids = [
        f"quality-realization:chapter-group:{chapter_start}:event:{offset}"
        for offset in range(1, 5)
    ]
    events: list[dict[str, Any]] = []
    for offset, event_id in enumerate(event_ids):
        chapter = chapter_start + offset
        events.append(
            {
                "event_id": event_id,
                "slice_id": f"quality-realization:chapter:{chapter}",
                "chapter_number": chapter,
                "causes": [] if offset == 0 else [event_ids[offset - 1]],
                "actor_ref": "protagonist",
                "motivation": "protect the witness without surrendering agency",
                "preconditions": ["the preceding public cost remains active"],
                "knowledge_boundary": {
                    "actor_knows": ["fact:public-risk"],
                    "reader_may_learn": ["fact:hidden-cost"],
                    "forbidden_disclosures": ["fact:future-antagonist-plan"],
                },
                "action": f"take the bounded causal action for Chapter {chapter}",
                "decision": f"accept the distinct visible cost in Chapter {chapter}",
                "resistance": f"opposition escalates through constraint {chapter}",
                "consequence": f"Chapter {chapter} irreversibly changes the next choice",
                "state_deltas": [
                    {
                        "state_kind": "character_arc",
                        "entity_id": "protagonist:accountability",
                        "from_state": _fixture_character_arc_stage(chapter - 1),
                        "to_state": _fixture_character_arc_stage(chapter),
                    }
                ],
                "disclosures": ["fact:hidden-cost"],
                "obligation_actions": [
                    f"promise:group-{1 if chapter <= 4 else 2}:"
                    f"{'PAYOFF' if chapter in {4, 8} else 'ADVANCE'}"
                ],
                "arc_contributions": list(arc_plan_ids),
                "irreversible_change": (
                    f"the Chapter {chapter} choice becomes witnessed and costly"
                ),
                "next_event_ids": (
                    [] if offset == len(event_ids) - 1 else [event_ids[offset + 1]]
                ),
                "required": True,
            }
        )
    return events


def bounded_quality_planning_fixture_response(
    stage: str, inputs: Mapping[str, Any]
) -> dict[str, Any]:
    """Canonical deterministic Planning fixture for the exact 4+4 dry-run."""

    payload = deepcopy(planning_fixture_response(stage, inputs))
    command = dict(inputs.get("planning_command") or {})
    logical_key = str(command.get("logical_key") or "")
    versions = dict(command.get("input_versions") or {})
    arc_plan_ids = tuple(
        value
        for value in (
            str(versions.get("arc_plans") or ""),
            *(str(item) for item in command.get("related_arc_plan_version_ids") or ()),
        )
        if value
    )
    if stage == "book_plan.generate":
        payload["length_strategy"] = {"target_chapters": 8}
        payload["volume_skeleton"] = [{"volume": 1, "function": "bounded arc"}]
        obligations = payload.get("knowledge_disclosure_obligations")
        if isinstance(obligations, dict):
            obligations["promise_ids"] = [
                "promise:group-1",
                "promise:group-2",
            ]
            obligations["obligation_windows"] = [
                {
                    "obligation_id": "promise:group-1",
                    "setup_chapter": 1,
                    "payoff_not_before": 3,
                    "payoff_due_by": 4,
                },
                {
                    "obligation_id": "promise:group-2",
                    "setup_chapter": 5,
                    "payoff_not_before": 7,
                    "payoff_due_by": 8,
                },
            ]
    elif stage == "volume_plan.generate":
        payload["chapter_range"] = [1, 8]
        for segment in payload.get("narrative_segments") or ():
            if isinstance(segment, dict):
                segment["chapter_range"] = [1, 8]
    elif stage == "arc_plan.generate":
        payload["target_window"] = {"from_chapter": 1, "to_chapter": 8}
        payload["target_progress_units"] = 8
        payload["closure_conditions"] = [
            f"Chapter {chapter} causal cost is accepted" for chapter in range(1, 9)
        ]
    elif stage == "chapter_group_plan.generate":
        accepted = int(command.get("narrative_search_accepted_through_chapter") or 0)
        start = max(1, accepted + 1)
        horizon = command.get("narrative_search_planning_horizon")
        frozen_range = (
            horizon.get("chapter_range") if isinstance(horizon, Mapping) else None
        )
        if isinstance(frozen_range, list) and len(frozen_range) == 2:
            start, frozen_end = map(int, frozen_range)
        else:
            frozen_end = start + 3
        if start not in {1, 5}:
            raise ValueError(
                "bounded Quality fixture only permits ChapterGroups 1-4 and 5-8"
            )
        end = start + 3
        if frozen_end != end:
            raise ValueError(
                "bounded Quality fixture requires the exact frozen four-Chapter horizon"
            )
        payload["logical_key"] = f"chapter-group:{start}-{end}"
        payload["contract_id"] = f"contract:chapter-group:{start}-{end}"
        payload["chapter_range"] = [start, end]
        payload["chapter_function_matrix"] = [
            _chapter_function_row(
                chapter,
                *_fixture_chapter_shape(chapter),
                arc_plan_ids,
            )
            for chapter in range(start, end + 1)
        ]
        payload["narrative_event_chain"] = _bounded_realization_event_chain(
            chapter_start=start,
            arc_plan_ids=arc_plan_ids or ("arc:primary",),
        )
    elif stage == "chapter_plan.generate":
        try:
            chapter = int(logical_key.split(":", 2)[1])
        except (IndexError, ValueError) as exc:
            raise ValueError("bounded Quality ChapterPlan identity is invalid") from exc
        if chapter not in QUALITY_CHAPTERS:
            raise ValueError("bounded Quality fixture refuses Chapter 9")
        payload["title"] = f"Chapter {chapter}: Witnessed Cost {chapter}"
        payload["premise"] = (
            f"Chapter {chapter} advances the causal conflict through a distinct choice."
        )
    return payload


def bounded_quality_chapter_fixture_response(
    stage: str, inputs: Mapping[str, Any]
) -> dict[str, Any]:
    """Deterministic Chapter/Reader fixture with auditable longitudinal movement."""

    payload = deepcopy(default_chapter_fixture_response(stage, inputs))
    if stage == "draft":
        plan = dict(inputs.get("plan") or {})
        chapter = int(plan.get("chapter") or plan.get("chapter_number") or 0)
        if chapter not in QUALITY_CHAPTERS:
            raise ValueError("bounded Quality draft refuses an out-of-scope Chapter")
        payload["text"] = (
            f"Chapter {chapter}. The witness names constraint {chapter}. "
            f"The protagonist chooses cost {chapter}, changing the next available path."
        )
        return payload
    if stage == "revision":
        draft = dict(inputs.get("draft") or {})
        text = str(draft.get("text") or "")
        payload["text"] = (
            f"{text} Opposition answers with countermove {len(text)}; the choice cannot "
            "be withdrawn after the room records it."
        )
        return payload
    if stage == "reader_outcome":
        chapter = int(inputs.get("chapter") or inputs.get("chapter_number") or 0)
        if chapter not in QUALITY_CHAPTERS:
            raise ValueError("bounded Reader Outcome requires Chapter 1-8")
        progress = (chapter - 1) / 7
        positive = round(0.68 + progress * 0.16, 3)
        negative = round(0.28 - progress * 0.12, 3)
        payload["reader_state"] = {
            "continue_intent": positive,
            "curiosity": min(0.95, round(positive + 0.04, 3)),
            "satisfaction": round(0.62 + progress * 0.2, 3),
            "confusion": negative,
            "trust": round(0.64 + progress * 0.18, 3),
            "character_attachment": round(0.61 + progress * 0.2, 3),
            "antagonist_pressure": round(0.58 + progress * 0.22, 3),
            "promise_expectation": round(0.7 + progress * 0.12, 3),
            "payoff_satisfaction": round(0.56 + progress * 0.24, 3),
            "drop_risk": negative,
            "repetition_fatigue": round(0.2 - progress * 0.06, 3),
        }
        return payload
    if stage != "canon_extraction":
        return payload

    revision = dict(inputs.get("revision") or {})
    chapter = int(revision.get("chapter") or 0)
    if chapter not in QUALITY_CHAPTERS:
        raise ValueError("bounded Canon extraction requires Chapter 1-8")
    expectations = dict(inputs.get("execution_expectations") or {})
    frozen_arcs = [
        dict(item)
        for item in expectations.get("frozen_arc_plans") or ()
        if isinstance(item, Mapping)
    ]
    if not frozen_arcs:
        raise ValueError("bounded Canon extraction requires frozen Arc lineage")
    primary = frozen_arcs[0]
    criteria = [
        str(item.get("criterion_id") or "")
        for item in primary.get("completion_criteria") or ()
        if str(item.get("criterion_id") or "")
    ]
    payload["arc_evidence"] = [
        {
            "arc_plan_version_id": str(primary["arc_plan_version_id"]),
            "observation_status": "OBSERVED",
            "contribution_kind": "PRIMARY",
            "progress_units": 1,
            "effect_dimensions": ["PLOT", "CHARACTER", "PRESSURE"],
            "milestone_ids": [f"quality:chapter:{chapter}:causal-progress"],
            "actual_consequences": [
                f"the accepted Chapter {chapter} choice removes one safe option"
            ],
            "obligation_ids": [f"promise:group-{1 if chapter <= 4 else 2}"],
            "resolution_evidence": [f"chapter:{chapter}:accepted-prose"],
            "completion_criterion_ids": (
                [criteria[chapter - 1]] if len(criteria) >= chapter else []
            ),
            "phase_to": "PAYOFF" if chapter in {4, 8} else "ESCALATION",
        }
    ]
    group = 1 if chapter <= 4 else 2
    position = ((chapter - 1) % 4) + 1
    status = ("OPEN", "DEVELOPING", "DUE", "FULFILLED")[position - 1]
    previous = None if status == "OPEN" else ("OPEN", "DEVELOPING", "DUE")[position - 2]
    obligation_change = {
        "obligation_id": f"promise:group-{group}",
        "obligation_type": "PROMISE",
        "status": status,
        "priority": "HIGH",
        "target_window": {
            "status": "SCHEDULED",
            "from_chapter": 1 if group == 1 else 5,
            "to_chapter": 4 if group == 1 else 8,
        },
        "payoff_evidence": (
            {
                "asset_version_id": f"quality:chapter:{chapter}:accepted-draft",
                "event_id": f"quality:chapter:{chapter}:payoff",
            }
            if status == "FULFILLED"
            else None
        ),
        "linked_arc_ids": [str(primary["arc_plan_version_id"])],
        "summary": f"The bounded promise reaches {status} in Chapter {chapter}.",
        "evidence_start": 0,
        "evidence_end": max(1, min(len(str(revision.get("text") or "")), 80)),
        "confidence": 0.99,
        "impact_type": "narrative_obligation_progress",
    }
    if previous is not None:
        obligation_change["from_status"] = previous
    payload["obligation_changes"] = [obligation_change]
    return payload


__all__ = [
    "BoundedCampaignRuntime",
    "BoundedQualityCampaignProfile",
    "BoundedQualityCampaignResult",
    "BoundedQualityCampaignRunner",
    "CampaignExecutionCheckpoint",
    "PROFILE_SCHEMA_VERSION",
    "QUALITY_CHAPTER_GROUPS",
    "QUALITY_CHAPTERS",
    "bounded_quality_chapter_fixture_response",
    "bounded_quality_planning_fixture_response",
    "classify_campaign_recovery_exhaustion",
    "load_quality_campaign_profile",
    "semantic_quality_evidence_identity",
]
