"""INVARIANT: longitudinal evidence consumes accepted observations only and cannot infer Arc or Volume quality by averaging Chapter scores."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import json
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.reader_calibration.proxy_policy import READER_PROXY_POLICY_V1


REPETITION_DIMENSIONS = (
    "plot_pattern",
    "conflict_solution",
    "scene_function",
    "chapter_structure",
    "emotional_beat",
    "dialogue_behavior",
    "information_release",
    "protagonist_reaction",
    "antagonist_response",
    "hook_pattern",
    "prose_style",
)

READER_OUTCOME_DIMENSIONS = (
    "continue_intent",
    "curiosity",
    "satisfaction",
    "confusion",
    "trust",
    "character_attachment",
    "antagonist_pressure",
    "promise_expectation",
    "payoff_satisfaction",
    "drop_risk",
    "repetition_fatigue",
)

_NEGATIVE_READER_DIMENSIONS = frozenset(
    {"confusion", "drop_risk", "repetition_fatigue"}
)


@dataclass(frozen=True, slots=True)
class MomentumEvidence:
    status: str
    observed_chapters: tuple[int, ...]
    activity_chapters: tuple[int, ...]
    progress_chapters: tuple[int, ...]
    stagnation_chapters: tuple[int, ...]
    causal_event_coverage: float | None
    irreversible_change_chapters: tuple[int, ...]
    protagonist_decision_count: int | None
    antagonist_response_count: int | None
    obstacle_escalation_chapters: tuple[int, ...]
    ending_propulsion_chapters: tuple[int, ...]
    longest_stagnation_run: int | None


@dataclass(frozen=True, slots=True)
class ObligationTimeline:
    obligation_id: str
    opened_chapter: int
    transitions: tuple[str, ...]
    chapter_states: tuple[tuple[int, tuple[str, ...]], ...]
    payoff_chapter: int | None
    payoff_latency: int | None
    linked_arc_ids: tuple[str, ...]
    source_acceptance_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PromisePayoffEvidence:
    status: str
    timelines: tuple[ObligationTimeline, ...]
    payoff_chapters: tuple[int, ...]
    payoff_latencies: tuple[int, ...]
    payoff_cadence_gaps: tuple[int, ...]
    payoff_clustering: bool | None
    overdue_ids: tuple[str, ...]
    repeated_delay_ids: tuple[str, ...]
    false_promise_ids: tuple[str, ...]
    unresolved_debt_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RepetitionEvidence:
    dimension: str
    status: str
    observed_chapter_count: int
    dominant_ratio: float | None
    longest_streak: int | None
    repeated_signature_hashes: tuple[str, ...]
    lexical_similarity: float | None
    lexical_similarity_decides: bool = False


@dataclass(frozen=True, slots=True)
class ReaderTrendEvidence:
    dimension: str
    status: str
    trend: str
    values: tuple[tuple[int, float], ...]
    evidence_class: str = "READER_PROXY_ADVISORY"
    policy_version: str = READER_PROXY_POLICY_V1.version
    policy_content_hash: str = READER_PROXY_POLICY_V1.snapshot()["content_hash"]


@dataclass(frozen=True, slots=True)
class LongitudinalQualityEvidence:
    observation_status: str
    chapter_range: tuple[int, int] | tuple[()]
    momentum: MomentumEvidence
    promise_payoff: PromisePayoffEvidence
    repetition: Mapping[str, RepetitionEvidence]
    reader_trends: Mapping[str, ReaderTrendEvidence]
    source_acceptance_ids: tuple[str, ...]
    source_accepted_asset_version_ids: tuple[str, ...]
    reader_source_asset_version_ids: tuple[str, ...]
    contract_version: str = "accepted-longitudinal-quality-v1"

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(
            {
                "observation_status": self.observation_status,
                "chapter_range": list(self.chapter_range),
                "momentum": asdict(self.momentum),
                "promise_payoff": asdict(self.promise_payoff),
                "repetition": {
                    key: asdict(value) for key, value in self.repetition.items()
                },
                "reader_proxy_policy": READER_PROXY_POLICY_V1.snapshot(),
                "reader_trends": {
                    key: asdict(value) for key, value in self.reader_trends.items()
                },
                "source_acceptance_ids": list(self.source_acceptance_ids),
                "source_accepted_asset_version_ids": list(
                    self.source_accepted_asset_version_ids
                ),
                "reader_source_asset_version_ids": list(
                    self.reader_source_asset_version_ids
                ),
                "accepted_history_only": True,
                "contract_version": self.contract_version,
            }
        )


@dataclass(frozen=True, slots=True)
class ArcQualityEvaluation:
    arc_plan_version_id: str
    status: str
    chapter_range: tuple[int, int] | tuple[()]
    observed_chapters: tuple[int, ...]
    causal_progression: bool | None
    total_progress_units: int | None
    actual_consequence_count: int | None
    protagonist_decision_count: int | None
    antagonist_response_count: int | None
    tension_growth: str
    payoff_ids: tuple[str, ...]
    transformation_progress: str
    fake_escalation: bool | None
    source_acceptance_ids: tuple[str, ...]
    contract_version: str = "arc-quality-evaluation-v1"

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True, slots=True)
class VolumeSliceQualityEvaluation:
    volume_scope_id: str
    status: str
    chapter_range: tuple[int, int] | tuple[()]
    momentum_status: str
    arc_statuses: tuple[tuple[str, str], ...]
    long_promise_progress: str
    payoff_distribution: str
    fatigue_trend: str
    cumulative_evolution: str
    ending_reachability: str
    source_acceptance_ids: tuple[str, ...]
    contract_version: str = "bounded-volume-quality-evaluation-v1"

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


def _json_ready(value: Any) -> Any:
    """COMPATIBILITY: Round-trip to the exact JSON shape persisted by PostgreSQL JSONB."""
    return json.loads(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def _accepted_rows(
    observations: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    rows = tuple(dict(item) for item in observations)
    ordered = tuple(sorted(rows, key=lambda item: int(item.get("chapter_number") or 0)))
    seen: set[int] = set()
    project_book: tuple[str, str] | None = None
    for row in ordered:
        chapter = row.get("chapter_number")
        scope = (str(row.get("project_id") or ""), str(row.get("book_id") or ""))
        valid = (
            isinstance(chapter, int)
            and not isinstance(chapter, bool)
            and chapter > 0
            and chapter not in seen
            and all(scope)
            and bool(str(row.get("acceptance_id") or ""))
            and bool(str(row.get("accepted_asset_version_id") or ""))
            and row.get("acceptance_status") == "COMMITTED"
        )
        if not valid or (project_book is not None and scope != project_book):
            raise KernelError(
                "LONGITUDINAL_QUALITY_ACCEPTED_LINEAGE_REQUIRED",
                "longitudinal evidence requires one exact accepted Book sequence",
            )
        seen.add(chapter)
        project_book = scope
    return ordered


def _items(value: object) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)):
        return None
    return tuple(str(item) for item in value if str(item))


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _arc_progress_units(row: Mapping[str, Any]) -> int:
    return sum(
        int(item.get("progress_units") or 0)
        for item in row.get("arc_evidence") or ()
        if isinstance(item, Mapping)
        and str(item.get("observation_status") or "") == "OBSERVED"
    )


def _momentum(rows: Sequence[Mapping[str, Any]]) -> MomentumEvidence:
    observed: list[int] = []
    activity: list[int] = []
    progress: list[int] = []
    stagnation: list[int] = []
    irreversible: list[int] = []
    escalation: list[int] = []
    propulsion: list[int] = []
    decision_count = 0
    response_count = 0
    for row in rows:
        chapter = int(row["chapter_number"])
        fields = (
            row.get("activity_event_count"),
            row.get("causal_progress_event_ids"),
            row.get("irreversible_state_change_ids"),
            row.get("goal_progress_units"),
            row.get("protagonist_decision_ids"),
            row.get("antagonist_response_ids"),
            row.get("obstacle_escalation"),
            row.get("ending_propulsion"),
            row.get("arc_evidence"),
        )
        if all(value is None for value in fields):
            continue
        observed.append(chapter)
        event_count = _number(row.get("activity_event_count"))
        causal = _items(row.get("causal_progress_event_ids")) or ()
        irreversible_ids = _items(row.get("irreversible_state_change_ids")) or ()
        goal = _number(row.get("goal_progress_units"))
        decisions = _items(row.get("protagonist_decision_ids")) or ()
        responses = _items(row.get("antagonist_response_ids")) or ()
        has_activity = bool((event_count or 0) > 0 or causal or decisions or responses)
        has_progress = bool(
            causal
            or irreversible_ids
            or (goal or 0) > 0
            or _arc_progress_units(row) > 0
        )
        if has_activity:
            activity.append(chapter)
        if has_progress:
            progress.append(chapter)
        if has_activity and not has_progress:
            stagnation.append(chapter)
        if irreversible_ids:
            irreversible.append(chapter)
        if row.get("obstacle_escalation") is True:
            escalation.append(chapter)
        if row.get("ending_propulsion") is True:
            propulsion.append(chapter)
        decision_count += len(decisions)
        response_count += len(responses)

    if not observed:
        return MomentumEvidence(
            "NOT_OBSERVED", (), (), (), (), None, (), None, None, (), (), None
        )
    longest = _longest_consecutive(stagnation)
    midpoint = max(1, len(observed) // 2)
    first = set(observed[:midpoint])
    second = set(observed[midpoint:])
    first_ratio = len(first & set(progress)) / max(len(first), 1)
    second_ratio = len(second & set(progress)) / max(len(second), 1)
    if not progress and stagnation:
        status = "STAGNATING"
    elif longest >= 3 or second_ratio + 0.25 < first_ratio:
        status = "DECLINING"
    elif len(progress) / len(observed) >= 0.5:
        status = "SUSTAINED"
    else:
        status = "MIXED"
    return MomentumEvidence(
        status=status,
        observed_chapters=tuple(observed),
        activity_chapters=tuple(activity),
        progress_chapters=tuple(progress),
        stagnation_chapters=tuple(stagnation),
        causal_event_coverage=round(len(progress) / len(observed), 4),
        irreversible_change_chapters=tuple(irreversible),
        protagonist_decision_count=decision_count,
        antagonist_response_count=response_count,
        obstacle_escalation_chapters=tuple(escalation),
        ending_propulsion_chapters=tuple(propulsion),
        longest_stagnation_run=longest,
    )


def _longest_consecutive(chapters: Sequence[int]) -> int:
    longest = current = 0
    previous: int | None = None
    for chapter in sorted(set(chapters)):
        current = current + 1 if previous is not None and chapter == previous + 1 else 1
        longest = max(longest, current)
        previous = chapter
    return longest


def _obligation_id(state: Mapping[str, Any]) -> str:
    return str(state.get("obligation_id") or state.get("entity_key") or "")


def _promise_payoff(rows: Sequence[Mapping[str, Any]]) -> PromisePayoffEvidence:
    by_id: dict[str, list[tuple[int, dict[str, Any], str]]] = {}
    for row in rows:
        states = row.get("obligation_states")
        if not isinstance(states, (list, tuple)):
            continue
        for raw in states:
            if not isinstance(raw, Mapping):
                continue
            state = dict(raw.get("state") or raw)
            identity = _obligation_id(state) or str(raw.get("entity_key") or "")
            if identity.startswith("obligation_id="):
                identity = identity.removeprefix("obligation_id=")
            if identity:
                by_id.setdefault(identity, []).append(
                    (int(row["chapter_number"]), state, str(row["acceptance_id"]))
                )
    if not by_id:
        return PromisePayoffEvidence(
            "NOT_OBSERVED", (), (), (), (), None, (), (), (), ()
        )

    timelines: list[ObligationTimeline] = []
    payoff_chapters: list[int] = []
    overdue_ids: list[str] = []
    repeated_delay_ids: list[str] = []
    false_promises: list[str] = []
    unresolved: list[str] = []
    for identity, entries in sorted(by_id.items()):
        entries.sort(key=lambda item: item[0])
        transitions: list[str] = []
        chapter_states: list[tuple[int, tuple[str, ...]]] = []
        previous_development_count = 0
        overdue_count = 0
        payoff_chapter: int | None = None
        payoff_latency: int | None = None
        opened = int(entries[0][1].get("opened_chapter") or entries[0][0])
        linked_arcs: set[str] = set()
        for ordinal, (chapter, state, _) in enumerate(entries):
            status = str(state.get("status") or "OPEN").upper()
            history = tuple(
                item
                for item in state.get("development_history") or ()
                if isinstance(item, Mapping)
            )
            target = dict(state.get("target_window") or {})
            due_from = int(target.get("from_chapter") or 0)
            due_to = int(target.get("to_chapter") or 0)
            overdue = (
                status not in {"FULFILLED", "PAID", "CANCELLED", "ABANDONED"}
                and due_to > 0
                and chapter > due_to
            )
            due = (
                status not in {"FULFILLED", "PAID", "CANCELLED", "ABANDONED"}
                and due_from > 0
                and due_from <= chapter <= max(due_to, due_from)
            )
            payoff = dict(state.get("payoff_evidence") or {})
            actual_payoff = dict(state.get("actual_payoff") or {})
            if status in {"FULFILLED", "PAID"}:
                partial = actual_payoff.get("complete") is False
                primary = "PARTIALLY_PAID" if partial else "PAID"
                # INVARIANT: Accepted Story State carries terminal obligations forward.
                # Setup-to-payoff latency binds the first observed payment,
                # never the latest snapshot that still contains PAID.
                if payoff_chapter is None:
                    payoff_chapter = chapter
                    payoff_latency = max(0, chapter - opened)
            elif status in {"CANCELLED", "ABANDONED"}:
                primary = "ABANDONED"
            elif ordinal == 0:
                primary = "CREATED"
            elif (
                status in {"DEVELOPING", "ESCALATED"}
                or len(history) > previous_development_count
            ):
                primary = "ESCALATED"
            elif overdue:
                primary = "OVERDUE"
            elif due:
                primary = "DUE"
            else:
                primary = "MAINTAINED"
            labels = [primary]
            if due and "DUE" not in labels:
                labels.append("DUE")
            if overdue and "OVERDUE" not in labels:
                labels.append("OVERDUE")
            transitions.append(primary)
            chapter_states.append((chapter, tuple(labels)))
            previous_development_count = max(previous_development_count, len(history))
            overdue_count += int(overdue)
            linked_arcs.update(
                str(item) for item in state.get("linked_arc_ids") or () if str(item)
            )
            if primary in {"PAID", "PARTIALLY_PAID"} and not payoff:
                # INVARIANT: A terminal state without immutable payoff evidence is not a
                # qualified payoff; preserve it as unresolved debt.
                unresolved.append(identity)
        terminal = transitions[-1]
        if payoff_chapter is not None:
            payoff_chapters.append(payoff_chapter)
        if any("OVERDUE" in labels for _, labels in chapter_states):
            overdue_ids.append(identity)
        if overdue_count >= 2:
            repeated_delay_ids.append(identity)
        if terminal == "ABANDONED" and payoff_chapter is None:
            false_promises.append(identity)
        if terminal not in {"PAID", "PARTIALLY_PAID", "ABANDONED"}:
            unresolved.append(identity)
        timelines.append(
            ObligationTimeline(
                obligation_id=identity,
                opened_chapter=opened,
                transitions=tuple(transitions),
                chapter_states=tuple(chapter_states),
                payoff_chapter=payoff_chapter,
                payoff_latency=payoff_latency,
                linked_arc_ids=tuple(sorted(linked_arcs)),
                source_acceptance_ids=tuple(item[2] for item in entries),
            )
        )
    sorted_payoffs = tuple(sorted(payoff_chapters))
    latencies = tuple(
        sorted(
            item.payoff_latency for item in timelines if item.payoff_latency is not None
        )
    )
    cadence = tuple(
        right - left for left, right in zip(sorted_payoffs, sorted_payoffs[1:])
    )
    clustering = (
        len(set(sorted_payoffs)) < len(sorted_payoffs) if sorted_payoffs else False
    )
    return PromisePayoffEvidence(
        status="MEASURED",
        timelines=tuple(timelines),
        payoff_chapters=sorted_payoffs,
        payoff_latencies=latencies,
        payoff_cadence_gaps=cadence,
        payoff_clustering=clustering,
        overdue_ids=tuple(sorted(set(overdue_ids))),
        repeated_delay_ids=tuple(sorted(set(repeated_delay_ids))),
        false_promise_ids=tuple(sorted(set(false_promises))),
        unresolved_debt_ids=tuple(sorted(set(unresolved))),
    )


def _chapter_signature(raw: object) -> str:
    if not isinstance(raw, (list, tuple)):
        return ""
    values = sorted({str(item) for item in raw if str(item)})
    return "|".join(values)


def _longest_same(values: Sequence[str]) -> int:
    longest = current = 0
    previous = ""
    for value in values:
        current = current + 1 if value and value == previous else 1
        longest = max(longest, current)
        previous = value
    return longest


def _lexical_similarity(rows: Sequence[Mapping[str, Any]]) -> float | None:
    sets = [
        set(_items(row.get("lexical_fingerprints")) or ())
        for row in rows
        if row.get("lexical_fingerprints") is not None
    ]
    if len(sets) < 2:
        return None
    values: list[float] = []
    for left, right in zip(sets, sets[1:]):
        union = left | right
        values.append(len(left & right) / len(union) if union else 0.0)
    return round(sum(values) / len(values), 4)


def _repetition(
    rows: Sequence[Mapping[str, Any]],
) -> Mapping[str, RepetitionEvidence]:
    lexical = _lexical_similarity(rows)
    reports: dict[str, RepetitionEvidence] = {}
    for dimension in REPETITION_DIMENSIONS:
        values = [
            signature
            for row in rows
            if isinstance(row.get("semantic_repetition_signatures"), Mapping)
            and (
                signature := _chapter_signature(
                    row["semantic_repetition_signatures"].get(dimension)
                )
            )
        ]
        if not values:
            reports[dimension] = RepetitionEvidence(
                dimension, "NOT_OBSERVED", 0, None, None, (), lexical
            )
            continue
        counts = Counter(values)
        dominant = max(counts.values()) / len(values)
        longest = _longest_same(values)
        repeated = tuple(sorted(value for value, count in counts.items() if count >= 2))
        if len(values) < 2:
            status = "INSUFFICIENT_EVIDENCE"
        elif len(values) >= 3 and (longest >= 3 or dominant >= 0.75):
            status = "FATIGUE_RISK"
        elif repeated:
            status = "REPETITION_OBSERVED"
        else:
            status = "DIVERSE"
        reports[dimension] = RepetitionEvidence(
            dimension=dimension,
            status=status,
            observed_chapter_count=len(values),
            dominant_ratio=round(dominant, 4),
            longest_streak=longest,
            repeated_signature_hashes=repeated,
            lexical_similarity=lexical,
        )
    return MappingProxyType(reports)


def _reader_trends(
    rows: Sequence[Mapping[str, Any]],
) -> Mapping[str, ReaderTrendEvidence]:
    reports: dict[str, ReaderTrendEvidence] = {}
    for dimension in READER_OUTCOME_DIMENSIONS:
        values = tuple(
            (int(row["chapter_number"]), numeric)
            for row in rows
            if isinstance(row.get("reader_outcome"), Mapping)
            and (numeric := _number(row["reader_outcome"].get(dimension))) is not None
        )
        if not values:
            reports[dimension] = ReaderTrendEvidence(
                dimension, "NOT_OBSERVED", "NOT_OBSERVED", ()
            )
            continue
        if len(values) < 2:
            trend = "INSUFFICIENT_EVIDENCE"
        else:
            midpoint = max(1, len(values) // 2)
            before = sum(value for _, value in values[:midpoint]) / midpoint
            after_values = values[midpoint:]
            after = sum(value for _, value in after_values) / max(len(after_values), 1)
            delta = after - before
            if dimension in _NEGATIVE_READER_DIMENSIONS:
                delta = -delta
            trend = (
                "IMPROVING"
                if delta > READER_PROXY_POLICY_V1.trend_delta_threshold
                else "WORSENING"
                if delta < -READER_PROXY_POLICY_V1.trend_delta_threshold
                else "STABLE"
            )
        reports[dimension] = ReaderTrendEvidence(
            dimension=dimension,
            status="MEASURED",
            trend=trend,
            values=values,
        )
    return MappingProxyType(reports)


def build_longitudinal_quality_evidence(
    observations: Iterable[Mapping[str, Any]],
) -> LongitudinalQualityEvidence:
    rows = _accepted_rows(observations)
    chapters = tuple(int(row["chapter_number"]) for row in rows)
    reader_sources = tuple(
        dict.fromkeys(
            str(item)
            for row in rows
            for item in row.get("reader_outcome_asset_version_ids") or ()
            if str(item)
        )
    )
    observed = bool(rows)
    return LongitudinalQualityEvidence(
        observation_status="MEASURED" if observed else "NOT_OBSERVED",
        chapter_range=(chapters[0], chapters[-1]) if chapters else (),
        momentum=_momentum(rows),
        promise_payoff=_promise_payoff(rows),
        repetition=_repetition(rows),
        reader_trends=_reader_trends(rows),
        source_acceptance_ids=tuple(str(row["acceptance_id"]) for row in rows),
        source_accepted_asset_version_ids=tuple(
            str(row["accepted_asset_version_id"]) for row in rows
        ),
        reader_source_asset_version_ids=reader_sources,
    )


def build_arc_quality_evaluation(
    observations: Iterable[Mapping[str, Any]],
    *,
    arc_plan_version_id: str,
) -> ArcQualityEvaluation:
    if not arc_plan_version_id:
        raise ValueError("arc_plan_version_id is required")
    rows = _accepted_rows(observations)
    matched: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for row in rows:
        for raw in row.get("arc_evidence") or ():
            if (
                isinstance(raw, Mapping)
                and str(raw.get("arc_plan_version_id") or "") == arc_plan_version_id
            ):
                matched.append((row, dict(raw)))
    if not matched:
        return ArcQualityEvaluation(
            arc_plan_version_id,
            "NOT_OBSERVED",
            (),
            (),
            None,
            None,
            None,
            None,
            None,
            "NOT_OBSERVED",
            (),
            "NOT_OBSERVED",
            None,
            (),
        )
    arc_rows = [item[0] for item in matched]
    evidence = [item[1] for item in matched]
    chapters = tuple(int(row["chapter_number"]) for row in arc_rows)
    progress = sum(
        int(item.get("progress_units") or 0)
        for item in evidence
        if item.get("observation_status") == "OBSERVED"
    )
    consequences = tuple(
        str(value)
        for item in evidence
        for value in item.get("actual_consequences") or ()
        if str(value)
    )
    decisions = sum(
        len(_items(row.get("protagonist_decision_ids")) or ()) for row in arc_rows
    )
    responses = sum(
        len(_items(row.get("antagonist_response_ids")) or ()) for row in arc_rows
    )
    escalation_count = sum(row.get("obstacle_escalation") is True for row in arc_rows)
    completion_ids = tuple(
        str(value)
        for item in evidence
        for value in item.get("completion_criterion_ids") or ()
        if str(value)
    )
    phases = tuple(
        dict.fromkeys(
            str(item.get("phase_to") or "")
            for item in evidence
            if str(item.get("phase_to") or "")
        )
    )
    causal_ids = sum(
        len(_items(row.get("causal_progress_event_ids")) or ()) for row in arc_rows
    )
    causal = progress > 0 and bool(consequences or causal_ids)
    fake = escalation_count > 0 and not causal
    if completion_ids:
        status = "COMPLETED"
        transformation = "COMPLETED"
    elif not causal:
        status = "STAGNATING"
        transformation = "NOT_ADVANCED"
    else:
        status = "PROGRESSING"
        transformation = "ADVANCING" if progress > 0 or len(phases) > 1 else "PARTIAL"
    tension = (
        "GROWING"
        if escalation_count >= max(1, len(arc_rows) // 2) and responses > 0
        else "STATIC"
        if escalation_count == 0
        else "MIXED"
    )
    payoff_ids = tuple(
        sorted(
            {
                str((raw.get("state") or raw).get("obligation_id") or "")
                for row in arc_rows
                for raw in row.get("obligation_states") or ()
                if isinstance(raw, Mapping)
                and arc_plan_version_id
                in {
                    str(item)
                    for item in (raw.get("state") or raw).get("linked_arc_ids") or ()
                }
                and str((raw.get("state") or raw).get("status") or "").upper()
                in {"FULFILLED", "PAID"}
                and str((raw.get("state") or raw).get("obligation_id") or "")
            }
        )
    )
    return ArcQualityEvaluation(
        arc_plan_version_id=arc_plan_version_id,
        status=status,
        chapter_range=(chapters[0], chapters[-1]),
        observed_chapters=chapters,
        causal_progression=causal,
        total_progress_units=progress,
        actual_consequence_count=len(consequences),
        protagonist_decision_count=decisions,
        antagonist_response_count=responses,
        tension_growth=tension,
        payoff_ids=payoff_ids,
        transformation_progress=transformation,
        fake_escalation=fake,
        source_acceptance_ids=tuple(str(row["acceptance_id"]) for row in arc_rows),
    )


def build_volume_slice_quality_evaluation(
    observations: Iterable[Mapping[str, Any]],
    *,
    arc_evaluations: Iterable[ArcQualityEvaluation],
    volume_scope_id: str,
) -> VolumeSliceQualityEvaluation:
    if not volume_scope_id:
        raise ValueError("volume_scope_id is required")
    rows = _accepted_rows(observations)
    arcs = tuple(arc_evaluations)
    if not rows:
        return VolumeSliceQualityEvaluation(
            volume_scope_id,
            "NOT_OBSERVED",
            (),
            "NOT_OBSERVED",
            (),
            "NOT_OBSERVED",
            "NOT_OBSERVED",
            "NOT_OBSERVED",
            "NOT_OBSERVED",
            "NOT_OBSERVED",
            (),
        )
    longitudinal = build_longitudinal_quality_evidence(rows)
    fatigue_count = sum(
        item.status == "FATIGUE_RISK" for item in longitudinal.repetition.values()
    )
    progressing_arcs = sum(item.status in {"PROGRESSING", "COMPLETED"} for item in arcs)
    at_risk = (
        longitudinal.momentum.status in {"STAGNATING", "DECLINING"}
        or any(item.fake_escalation for item in arcs)
        or bool(longitudinal.promise_payoff.repeated_delay_ids)
        or fatigue_count >= 3
    )
    status = (
        "AT_RISK" if at_risk else "PROGRESSING" if progressing_arcs else "NOT_PROVEN"
    )
    promises = longitudinal.promise_payoff
    long_promise = (
        "NOT_OBSERVED"
        if promises.status == "NOT_OBSERVED"
        else "DEBT_GROWING"
        if promises.repeated_delay_ids
        else "ADVANCING"
        if promises.payoff_chapters or promises.timelines
        else "STATIC"
    )
    payoff_distribution = (
        "NOT_OBSERVED"
        if promises.status == "NOT_OBSERVED"
        else "CLUSTERED"
        if promises.payoff_clustering
        else "DISTRIBUTED"
        if promises.payoff_chapters
        else "NO_PAYOFF_OBSERVED"
    )
    fatigue = (
        "RISING"
        if fatigue_count
        else "NOT_OBSERVED"
        if not any(
            item.observed_chapter_count for item in longitudinal.repetition.values()
        )
        else "CONTROLLED"
    )
    evolution = (
        "ACCUMULATING"
        if longitudinal.momentum.irreversible_change_chapters or progressing_arcs
        else "NOT_ACCUMULATING"
    )
    last_chapter = int(rows[-1]["chapter_number"])
    reachability = (
        "IMPROVING"
        if progressing_arcs
        and last_chapter in longitudinal.momentum.ending_propulsion_chapters
        else "DETERIORATING"
        if at_risk
        else "NOT_PROVEN"
    )
    chapters = tuple(int(row["chapter_number"]) for row in rows)
    return VolumeSliceQualityEvaluation(
        volume_scope_id=volume_scope_id,
        status=status,
        chapter_range=(chapters[0], chapters[-1]),
        momentum_status=longitudinal.momentum.status,
        arc_statuses=tuple((item.arc_plan_version_id, item.status) for item in arcs),
        long_promise_progress=long_promise,
        payoff_distribution=payoff_distribution,
        fatigue_trend=fatigue,
        cumulative_evolution=evolution,
        ending_reachability=reachability,
        source_acceptance_ids=longitudinal.source_acceptance_ids,
    )


__all__ = [
    "ArcQualityEvaluation",
    "LongitudinalQualityEvidence",
    "MomentumEvidence",
    "ObligationTimeline",
    "PromisePayoffEvidence",
    "READER_OUTCOME_DIMENSIONS",
    "REPETITION_DIMENSIONS",
    "ReaderTrendEvidence",
    "RepetitionEvidence",
    "VolumeSliceQualityEvaluation",
    "build_arc_quality_evaluation",
    "build_longitudinal_quality_evidence",
    "build_volume_slice_quality_evaluation",
]
