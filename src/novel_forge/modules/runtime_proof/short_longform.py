"""Deterministic WP-VERIFY-01 evidence evaluation.

The evaluator is deliberately pure: it receives a serialized evidence snapshot,
performs no I/O, and cannot schedule work or mutate Authority state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


PLANNING_STAGES = frozenset(
    {
        "book_plan.generate",
        "volume_plan.generate",
        "arc_plan.generate",
        "chapter_group_plan.generate",
        "chapter_plan.generate",
    }
)

CONTINUITY_STATE_TYPES = (
    "story_state_snapshot",
    "canon_snapshot",
)

CHAPTER_REAL_PROVIDER_STAGES = frozenset(
    {
        "draft",
        "review",
        "revision",
        "rereview",
        "canon_extraction",
        "quality_structural",
        "quality_commercial",
        "quality_source_originality",
        "quality_longform",
        "quality_platform",
    }
)

PROOF_FLAG_ORDER = (
    "planning_real_provider_proven",
    "reader_outcome_real_provider_proven",
    "real_provider_attempt_retry_proven",
    "book_authority_command_boundary_proven",
    "three_chapter_continuity_proven",
    "longform_recap_proven",
    "replan_loop_proven",
    "resume_after_replan_proven",
    "short_longform_runtime_proven",
)


def _objects(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _object(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value if str(item))


def _sha256(value: Any) -> bool:
    normalized = str(value or "").removeprefix("sha256:")
    return len(normalized) == 64 and all(
        character in "0123456789abcdef" for character in normalized.lower()
    )


def _model_authority_valid(item: Mapping[str, Any]) -> bool:
    authority = _object(item.get("model_authority"))
    models = (
        authority.get("policy_requested_model"),
        authority.get("frozen_route_model"),
        authority.get("invocation_model"),
    )
    efforts = (
        authority.get("policy_requested_reasoning_effort"),
        authority.get("frozen_route_reasoning_effort"),
        authority.get("invocation_reasoning_effort"),
    )
    return bool(
        models[0]
        and len(set(str(value) for value in models)) == 1
        and efforts[0]
        and len(set(str(value) for value in efforts)) == 1
        and bool(authority.get("model_profile_id"))
        and int(authority.get("model_profile_version") or 0) > 0
        and _sha256(authority.get("model_profile_hash"))
        and bool(authority.get("route_policy_id"))
        and int(authority.get("route_policy_version") or 0) > 0
        and _sha256(authority.get("route_policy_hash"))
        and bool(authority.get("route_snapshot_id"))
        and _sha256(authority.get("route_snapshot_hash"))
        and bool(authority.get("local_user_config_ignored"))
        and authority.get("local_user_config_is_model_authority") is False
    )


def _measured_usage_and_estimated_cost(item: Mapping[str, Any]) -> bool:
    usage = _object(item.get("usage"))
    cost = _object(item.get("cost"))
    return bool(
        usage.get("availability") == "AVAILABLE"
        and usage.get("measurement") == "MEASURED"
        and int(usage.get("total_tokens") or 0) > 0
        and cost.get("availability") == "AVAILABLE"
        and cost.get("measurement") == "ESTIMATED"
        and cost.get("estimated") is True
        and cost.get("provider_billed") is False
    )


def _collect_refs(*items: Any) -> tuple[str, ...]:
    refs: set[str] = set()
    for item in items:
        if isinstance(item, Mapping):
            refs.update(_strings(item.get("evidence_refs")))
        elif isinstance(item, (list, tuple)):
            for member in item:
                if isinstance(member, Mapping):
                    refs.update(_strings(member.get("evidence_refs")))
                elif str(member):
                    refs.add(str(member))
    return tuple(sorted(refs))


@dataclass(frozen=True, slots=True)
class ProofCheck:
    passed: bool
    evidence_refs: tuple[str, ...]
    failure_reasons: tuple[str, ...]
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "evidence_refs": list(self.evidence_refs),
            "failure_reasons": list(self.failure_reasons),
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class ShortLongformProofEvaluation:
    checks: Mapping[str, ProofCheck]

    @property
    def proof_flags(self) -> dict[str, bool]:
        return {name: bool(self.checks[name].passed) for name in PROOF_FLAG_ORDER}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "novel-forge.short-longform-proof-evaluation.v1",
            "proof_flags": self.proof_flags,
            "checks": {name: self.checks[name].to_dict() for name in PROOF_FLAG_ORDER},
        }


def _check_planning(evidence: Mapping[str, Any]) -> ProofCheck:
    planning = _object(evidence.get("planning"))
    generators = _objects(planning.get("generators"))
    reasons: list[str] = []
    stages = {str(item.get("stage") or "") for item in generators}
    missing = sorted(PLANNING_STAGES - stages)
    if missing:
        reasons.append("missing governed Planning stages: " + ", ".join(missing))
    for item in generators:
        stage = str(item.get("stage") or "unknown")
        required = {
            "operation_succeeded": item.get("operation_status")
            in {"WAITING_GATE", "SUCCEEDED"},
            "attempt_succeeded": item.get("attempt_status")
            in {"RESULT_SUBMITTED", "SUCCEEDED"},
            "lease_fenced": bool(item.get("lease_id"))
            and int(item.get("fencing_token") or 0) > 0,
            "pack_frozen": bool(item.get("capability_pack_snapshot_ref"))
            and bool(item.get("active_deployment_id")),
            "agent_real_runtime": item.get("agent_runtime_qualification")
            == "QUALIFIED_REAL_RUNTIME",
            "work_order": bool(item.get("work_order_id")),
            "runtime_binding": bool(item.get("runtime_binding_id")),
            "external_effect": bool(item.get("external_effect_id"))
            and bool(item.get("provider_receipt_id")),
            "real_provider": item.get("real_provider_call") is True
            and item.get("fixture_protocol_only") is False,
            "usage_cost": _measured_usage_and_estimated_cost(item),
            "model_authority": _model_authority_valid(item),
            "candidate": bool(item.get("candidate_asset_version_id"))
            and item.get("candidate_accepted") is True,
            "domain_authority": item.get("commit_authority")
            in {"STORY_DESIGN_AUTHORITY", "PLANNING_AUTHORITY"},
        }
        failed = sorted(name for name, passed in required.items() if not passed)
        if failed:
            reasons.append(f"{stage} lacks " + ", ".join(failed))
    provider_observed = [
        _object(item.get("model_authority")).get("provider_observed_model")
        for item in generators
    ]
    limitations = (
        (
            "Codex did not independently report provider model identity; invocation is proven from frozen argv only.",
        )
        if generators
        and all(value in {None, "", "unavailable"} for value in provider_observed)
        else ()
    )
    return ProofCheck(
        passed=not reasons and len(generators) >= len(PLANNING_STAGES),
        evidence_refs=_collect_refs(generators),
        failure_reasons=tuple(reasons),
        limitations=limitations,
    )


def _check_reader(evidence: Mapping[str, Any]) -> ProofCheck:
    reader = _object(evidence.get("reader_outcome"))
    reports = _objects(reader.get("reports"))
    reasons: list[str] = []
    if {int(item.get("chapter_number") or 0) for item in reports} != {1, 2, 3}:
        reasons.append("Reader Outcome is not complete for Chapters 1-3")
    for item in reports:
        chapter = int(item.get("chapter_number") or 0)
        required = {
            "separate_pack": item.get("capability_pack_id")
            and item.get("capability_pack_id") != reader.get("chapter_pack_id"),
            "external_effect": bool(item.get("external_effect_id"))
            and bool(item.get("provider_receipt_id")),
            "real_provider": item.get("real_provider_call") is True
            and item.get("fixture_protocol_only") is False,
            "usage_cost": _measured_usage_and_estimated_cost(item),
            "model_authority": _model_authority_valid(item),
            "report": bool(item.get("report_asset_version_id")),
            "state_transition": bool(item.get("state_transition_asset_version_id")),
            "issue_set": bool(item.get("issue_set_asset_version_id")),
        }
        failed = sorted(name for name, passed in required.items() if not passed)
        if failed:
            reasons.append(f"Reader Chapter {chapter} lacks " + ", ".join(failed))
    judge = _object(reader.get("judge"))
    if not (
        judge.get("mode") == "SHADOW"
        and judge.get("publish_blocking") is False
        and judge.get("authority_commit_allowed") is False
        and judge.get("direct_plan_mutation_allowed") is False
    ):
        reasons.append("Reader Judge fail-safe SHADOW boundary is not proven")
    return ProofCheck(
        passed=not reasons and len(reports) == 3,
        evidence_refs=_collect_refs(reports, judge),
        failure_reasons=tuple(reasons),
        limitations=(
            "Reader intelligence effectiveness and calibration are not proven.",
        ),
    )


def _check_retry(evidence: Mapping[str, Any]) -> ProofCheck:
    retry = _object(evidence.get("retry"))
    attempt_one = _object(retry.get("attempt_1"))
    attempt_two = _object(retry.get("attempt_2"))
    conditions = {
        "deterministic one-shot fault": retry.get("fault_injection")
        == "after_measured_usage_before_candidate_acceptance",
        "same Operation": bool(attempt_one.get("operation_id"))
        and attempt_one.get("operation_id") == attempt_two.get("operation_id"),
        "different Attempts": bool(attempt_one.get("attempt_id"))
        and attempt_one.get("attempt_id") != attempt_two.get("attempt_id"),
        "new Lease/Fence": bool(attempt_one.get("lease_id"))
        and bool(attempt_two.get("lease_id"))
        and attempt_one.get("lease_id") != attempt_two.get("lease_id")
        and bool(attempt_one.get("fence_identity"))
        and bool(attempt_two.get("fence_identity"))
        and attempt_one.get("fence_identity") != attempt_two.get("fence_identity"),
        "Attempt 1 measured evidence": _measured_usage_and_estimated_cost(attempt_one),
        "Attempt 2 recovered Provider evidence": _measured_usage_and_estimated_cost(attempt_two)
        and attempt_two.get("real_provider_call") is True,
        "frozen governance identity": retry.get("frozen_governance_identity_equal")
        is True,
        "frozen materialization": retry.get("frozen_materialization_equal") is True,
        "stale fence rejected": retry.get("stale_fence_commit_rejected") is True,
        "one accepted candidate": int(retry.get("accepted_candidate_count") or 0) == 1,
        "one idempotent Provider execution": int(
            retry.get("provider_execution_count") or 0
        )
        == 1,
        "Provider result recovered by Attempt 2": retry.get(
            "recovered_provider_result"
        )
        is True,
    }
    reasons = tuple(name for name, passed in conditions.items() if not passed)
    return ProofCheck(
        passed=not reasons,
        evidence_refs=_collect_refs(retry, attempt_one, attempt_two),
        failure_reasons=reasons,
        limitations=(),
    )


def _check_book_boundary(evidence: Mapping[str, Any]) -> ProofCheck:
    book = _object(evidence.get("book_authority"))
    mutations = _objects(book.get("mutations"))
    reasons: list[str] = []
    if (
        book.get("state") != "COMPLETED"
        or int(book.get("accepted_through_chapter") or 0) != 3
    ):
        reasons.append("Book Authority did not durably complete three chapters")
    if not mutations:
        reasons.append("Book mutations have no command-boundary evidence")
    for item in mutations:
        if not all(
            (
                item.get("transaction_command") is True,
                bool(item.get("state_event_id")),
                bool(item.get("audit_log_id")),
                bool(item.get("outbox_id")),
            )
        ):
            reasons.append(
                f"Book mutation {item.get('command_name') or 'unknown'} is not atomic"
            )
    return ProofCheck(
        passed=not reasons,
        evidence_refs=_collect_refs(book, mutations),
        failure_reasons=tuple(reasons),
        limitations=(),
    )


def _check_continuity(evidence: Mapping[str, Any]) -> ProofCheck:
    continuity = _object(evidence.get("continuity"))
    chapters = sorted(
        _objects(continuity.get("chapters")),
        key=lambda item: int(item.get("chapter_number") or 0),
    )
    reasons: list[str] = []
    if [int(item.get("chapter_number") or 0) for item in chapters] != [1, 2, 3]:
        reasons.append("accepted Chapter sequence is not exactly 1,2,3")
    for item in chapters:
        if item.get("accepted") is not True:
            reasons.append(f"Chapter {item.get('chapter_number')} is not accepted")
        provider_calls = _objects(item.get("provider_calls"))
        provider_stages = {str(call.get("stage") or "") for call in provider_calls}
        missing_provider_stages = sorted(CHAPTER_REAL_PROVIDER_STAGES - provider_stages)
        if missing_provider_stages:
            reasons.append(
                f"Chapter {item.get('chapter_number')} lacks real Provider stages: "
                + ", ".join(missing_provider_stages)
            )
        for call in provider_calls:
            if not (
                call.get("real_provider_call") is True
                and call.get("fixture_protocol_only") is False
                and _measured_usage_and_estimated_cost(call)
                and _model_authority_valid(call)
            ):
                reasons.append(
                    f"Chapter {item.get('chapter_number')} Provider evidence invalid: "
                    f"{call.get('stage') or 'unknown'}"
                )
    for previous, current in zip(chapters, chapters[1:]):
        outputs = _object(previous.get("output_state_refs"))
        inputs = _object(current.get("input_state_refs"))
        for state_type in CONTINUITY_STATE_TYPES:
            if not outputs.get(state_type) or inputs.get(state_type) != outputs.get(
                state_type
            ):
                reasons.append(
                    f"Chapter {current.get('chapter_number')} lineage break: {state_type}"
                )
    return ProofCheck(
        passed=not reasons and len(chapters) == 3,
        evidence_refs=_collect_refs(chapters),
        failure_reasons=tuple(reasons),
        limitations=(),
    )


def _check_recap(evidence: Mapping[str, Any]) -> ProofCheck:
    recap = _object(evidence.get("longform_recap"))
    conditions = {
        "accepted Chapter trigger": bool(recap.get("accepted_chapter_request_id")),
        "Reader Outcome trigger": bool(recap.get("reader_outcome_asset_version_id")),
        "checkpoint": bool(recap.get("checkpoint_operation_id")),
        "immutable recap": bool(recap.get("recap_asset_version_id"))
        and recap.get("immutable") is True,
        "deviation evidence": bool(recap.get("deviation_asset_version_id")),
        "replan request evidence": bool(recap.get("replan_request_asset_version_id")),
        "control-flow boundary": recap.get("control_flow_proof") is True
        and recap.get("reader_intelligence_effectiveness_proven") is False,
    }
    reasons = tuple(name for name, passed in conditions.items() if not passed)
    return ProofCheck(
        passed=not reasons,
        evidence_refs=_collect_refs(recap),
        failure_reasons=reasons,
        limitations=(
            "Controlled deviation proves control flow, not Reader intelligence effectiveness.",
        ),
    )


def _check_replan(evidence: Mapping[str, Any]) -> ProofCheck:
    replan = _object(evidence.get("replan"))
    conditions = {
        "Recap source": bool(replan.get("source_recap_asset_version_id")),
        "ReplanRequest": bool(replan.get("replan_request_asset_version_id")),
        "replacement candidate": bool(
            replan.get("replacement_candidate_asset_version_id")
        ),
        "PlanChange proposal": bool(replan.get("plan_change_proposal_id")),
        "approval": bool(replan.get("approval_decision_id")),
        "activation": replan.get("status") in {"ACTIVE", "RESUMED"},
        "future-only": replan.get("future_only") is True,
        "executed plan preserved": replan.get("executed_plan_preserved") is True,
        "future superseded": replan.get("future_plan_superseded") is True,
        "old snapshot preserved": bool(replan.get("old_input_snapshot_id")),
        "new snapshot": bool(replan.get("new_input_snapshot_id"))
        and replan.get("new_input_snapshot_id") != replan.get("old_input_snapshot_id"),
        "resume consumed replacement": bool(replan.get("resumed_chapter_plan_version"))
        and replan.get("resumed_chapter_plan_version")
        == replan.get("replacement_candidate_asset_version_id"),
    }
    reasons = tuple(name for name, passed in conditions.items() if not passed)
    return ProofCheck(
        passed=not reasons,
        evidence_refs=_collect_refs(replan),
        failure_reasons=reasons,
        limitations=(),
    )


def _check_resume(evidence: Mapping[str, Any]) -> ProofCheck:
    resume = _object(evidence.get("resume"))
    conditions = {
        "different OS/Python process": bool(resume.get("planning_process_id"))
        and bool(resume.get("book_process_id"))
        and resume.get("planning_process_id") != resume.get("book_process_id"),
        "fresh composition root": resume.get("fresh_composition_root") is True,
        "persisted Authority recovery": resume.get("persisted_state_only") is True,
        "checkpoint contains no business recovery state": resume.get(
            "checkpoint_business_state_used"
        )
        is False,
        "Object Storage namespace preserved": resume.get(
            "object_storage_namespace_preserved"
        )
        is True,
        "Planning checkpoint": bool(resume.get("planning_checkpoint_ref")),
        "Book resumed": resume.get("book_phase_resumed") is True,
        "no duplicate provider effect": resume.get("duplicate_provider_effect_count")
        == 0,
        "no duplicate Chapter": resume.get("duplicate_chapter_count") == 0,
        "no duplicate Canon": resume.get("duplicate_canon_commit_count") == 0,
        "no duplicate Reader": resume.get("duplicate_reader_sidecar_count") == 0,
    }
    reasons = tuple(name for name, passed in conditions.items() if not passed)
    return ProofCheck(
        passed=not reasons,
        evidence_refs=_collect_refs(resume),
        failure_reasons=reasons,
        limitations=(),
    )


def _check_aggregate(
    evidence: Mapping[str, Any], checks: Mapping[str, ProofCheck]
) -> ProofCheck:
    environment = _object(evidence.get("environment"))
    release = _object(evidence.get("release"))
    reasons = [name for name, check in checks.items() if not check.passed]
    prerequisites = {
        "current HEAD clean": release.get("worktree_clean") is True
        and bool(release.get("commit_sha")),
        "PostgreSQL Authority real": environment.get("postgresql") == "REAL",
        "MinIO real": environment.get("object_storage") == "MINIO_REAL",
        "Codex real": environment.get("provider") == "CODEX_CLI_REAL",
    }
    reasons.extend(name for name, passed in prerequisites.items() if not passed)
    refs = _collect_refs(
        [reference for check in checks.values() for reference in check.evidence_refs],
        environment,
        release,
    )
    return ProofCheck(
        passed=not reasons,
        evidence_refs=refs,
        failure_reasons=tuple(reasons),
        limitations=(
            "This is a three-Chapter runtime proof; it is not a 50+ Chapter longform claim.",
        ),
    )


def evaluate_short_longform_evidence(
    evidence: Mapping[str, Any],
) -> ShortLongformProofEvaluation:
    """Evaluate an immutable snapshot without performing I/O or state changes."""

    checks: dict[str, ProofCheck] = {
        "planning_real_provider_proven": _check_planning(evidence),
        "reader_outcome_real_provider_proven": _check_reader(evidence),
        "real_provider_attempt_retry_proven": _check_retry(evidence),
        "book_authority_command_boundary_proven": _check_book_boundary(evidence),
        "three_chapter_continuity_proven": _check_continuity(evidence),
        "longform_recap_proven": _check_recap(evidence),
        "replan_loop_proven": _check_replan(evidence),
        "resume_after_replan_proven": _check_resume(evidence),
    }
    checks["short_longform_runtime_proven"] = _check_aggregate(evidence, checks)
    return ShortLongformProofEvaluation(checks=checks)
