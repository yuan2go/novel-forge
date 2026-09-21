from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .domain import (
    BLIND_EVALUATION_DIMENSIONS,
    BlindScope,
    EvaluatorIdentityClass,
)


_PUBLIC_FORBIDDEN_KEY_FRAGMENTS = (
    "canonical",
    "baseline",
    "asset_version",
    "provider",
    "model",
    "prompt",
    "judge",
    "system_score",
    "branch",
    "private_mapping",
    "randomization",
    "release_sha",
)


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _token(prefix: str, secret: str, *parts: object) -> str:
    digest = hashlib.sha256(
        "\x1f".join((secret, *(str(item) for item in parts))).encode("utf-8")
    ).hexdigest()
    return f"{prefix}:{digest[:32]}"


@dataclass(frozen=True, slots=True)
class BlindComparisonSubject:
    subject_id: str
    scope_type: BlindScope
    chapter_start: int
    chapter_end: int
    canonical_asset_version_id: str
    baseline_asset_version_id: str
    canonical_text: str
    baseline_text: str
    arc_plan_version_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        try:
            scope = BlindScope(self.scope_type)
        except ValueError as exc:
            raise ValueError("blind comparison subject scope is invalid") from exc
        if (
            not self.subject_id
            or self.chapter_start <= 0
            or self.chapter_end < self.chapter_start
            or not self.canonical_asset_version_id
            or not self.baseline_asset_version_id
            or self.canonical_asset_version_id == self.baseline_asset_version_id
            or not self.canonical_text.strip()
            or not self.baseline_text.strip()
        ):
            raise ValueError("blind comparison subject is incomplete")
        if scope is BlindScope.CHAPTER and self.chapter_start != self.chapter_end:
            raise ValueError("Chapter blind subject must cover one chapter")
        if scope is BlindScope.ARC and not self.arc_plan_version_ids:
            raise ValueError("Arc blind subject requires frozen Arc lineage")
        object.__setattr__(self, "scope_type", scope)


@dataclass(frozen=True, slots=True)
class BlindEvaluator:
    reviewer_id: str
    identity_class: EvaluatorIdentityClass

    def __post_init__(self) -> None:
        if not self.reviewer_id:
            raise ValueError("blind evaluator reviewer_id is required")
        try:
            identity_class = EvaluatorIdentityClass(self.identity_class)
        except ValueError as exc:
            raise ValueError("blind evaluator identity class is invalid") from exc
        object.__setattr__(self, "identity_class", identity_class)


@dataclass(frozen=True, slots=True)
class PrivatePairMapping:
    pair_token: str
    subject_id: str
    scope_type: BlindScope
    chapter_start: int
    chapter_end: int
    canonical_position: str
    candidate_a_asset_version_id: str
    candidate_b_asset_version_id: str


@dataclass(frozen=True, slots=True)
class BlindEvaluationPack:
    reviewer_id: str
    pack_token: str
    content_hash: str
    private_mapping_hash: str
    private_mapping: tuple[PrivatePairMapping, ...]
    _public_payload_json: str

    @property
    def public_payload(self) -> dict[str, Any]:
        return json.loads(self._public_payload_json)


@dataclass(frozen=True, slots=True)
class BlindExportBundle:
    packs: Mapping[str, BlindEvaluationPack]


def _assert_public_keys(value: Any, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in _PUBLIC_FORBIDDEN_KEY_FRAGMENTS):
                raise ValueError(f"blind pack leaks forbidden metadata at {path}.{key}")
            _assert_public_keys(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_public_keys(item, path=f"{path}[{index}]")


def _ordering(
    chapters: tuple[BlindComparisonSubject, ...],
    arcs: tuple[BlindComparisonSubject, ...],
    *,
    campaign_secret: str,
    campaign_version: int,
) -> dict[str, str]:
    ranked = sorted(
        chapters,
        key=lambda item: hashlib.sha256(
            f"{campaign_secret}\x1f{item.subject_id}".encode("utf-8")
        ).hexdigest(),
    )
    offset = (campaign_version - 1) % len(ranked)
    canonical_a_count = (len(ranked) + 1) // 2
    canonical_a = {
        ranked[(offset + index) % len(ranked)].subject_id
        for index in range(canonical_a_count)
    }
    result = {
        item.subject_id: "A" if item.subject_id in canonical_a else "B"
        for item in chapters
    }
    arc_seed = int(
        hashlib.sha256(f"{campaign_secret}\x1farc".encode("utf-8")).hexdigest(),
        16,
    )
    for index, item in enumerate(arcs):
        result[item.subject_id] = (
            "A" if (arc_seed + campaign_version + index) % 2 == 0 else "B"
        )
    return result


def export_blind_evaluation_packs(
    *,
    campaign_token: str,
    campaign_version: int,
    protocol_version: str,
    evaluation_version: str,
    campaign_secret: str,
    evaluators: Iterable[BlindEvaluator],
    subjects: Iterable[BlindComparisonSubject],
    subject_population: str = "CHAPTER_ARC",
) -> BlindExportBundle:

    reviewers = tuple(evaluators)
    rows = tuple(subjects)
    if (
        not campaign_token
        or campaign_version <= 0
        or not protocol_version
        or not evaluation_version
        or len(campaign_secret) < 8
    ):
        raise ValueError("blind pack version and campaign secret are required")
    if len(reviewers) != 2 or len({item.reviewer_id for item in reviewers}) != 2:
        raise ValueError("blind protocol requires exactly two independent evaluators")
    chapters = tuple(
        sorted(
            (item for item in rows if item.scope_type is BlindScope.CHAPTER),
            key=lambda item: item.chapter_start,
        )
    )
    arcs = tuple(
        sorted(
            (item for item in rows if item.scope_type is BlindScope.ARC),
            key=lambda item: (item.chapter_start, item.chapter_end, item.subject_id),
        )
    )
    if subject_population not in {"CHAPTER_ARC", "INDEPENDENT_TASKS"}:
        raise ValueError("blind subject population is invalid")
    independent = subject_population == "INDEPENDENT_TASKS"
    if independent and (arcs or len({item.subject_id for item in chapters}) != len(chapters)):
        raise ValueError("Independent tasks cannot invent Arc coverage or repeat a subject")
    if not chapters or not independent and not arcs:
        raise ValueError("blind campaign requires Chapter and Arc subjects")
    first_chapter = chapters[0].chapter_start
    last_chapter = chapters[-1].chapter_end
    if not independent and tuple(item.chapter_start for item in chapters) != tuple(
        range(first_chapter, last_chapter + 1)
    ):
        raise ValueError("blind campaign Chapter subjects must be contiguous")
    if not independent and not any(
        item.chapter_start <= first_chapter and item.chapter_end >= last_chapter
        for item in arcs
    ):
        raise ValueError("blind campaign requires an Arc subject covering its Chapters")
    first_order = _ordering(
        chapters,
        arcs,
        campaign_secret=campaign_secret,
        campaign_version=campaign_version,
    )
    packs: dict[str, BlindEvaluationPack] = {}
    ordered_subjects = (*chapters, *arcs)
    for reviewer_index, reviewer in enumerate(reviewers):
        reviewer_token = _token(
            "reviewer", campaign_secret, campaign_token, reviewer.reviewer_id
        )
        pack_token = _token(
            "pack",
            campaign_secret,
            campaign_token,
            campaign_version,
            reviewer.reviewer_id,
        )
        public_pairs: list[dict[str, Any]] = []
        private_rows: list[PrivatePairMapping] = []
        for ordinal, subject in enumerate(ordered_subjects, start=1):
            first_position = first_order[subject.subject_id]
            canonical_position = (
                first_position
                if reviewer_index == 0
                else "B" if first_position == "A" else "A"
            )
            pair_token = _token(
                "pair",
                campaign_secret,
                pack_token,
                ordinal,
                subject.subject_id,
            )
            if canonical_position == "A":
                candidate_a_text = subject.canonical_text
                candidate_b_text = subject.baseline_text
                candidate_a_id = subject.canonical_asset_version_id
                candidate_b_id = subject.baseline_asset_version_id
            else:
                candidate_a_text = subject.baseline_text
                candidate_b_text = subject.canonical_text
                candidate_a_id = subject.baseline_asset_version_id
                candidate_b_id = subject.canonical_asset_version_id
            public_pairs.append(
                {
                    "pair_token": pair_token,
                    "ordinal": ordinal,
                    "scope": {
                        "type": subject.scope_type.value,
                        "chapter_start": subject.chapter_start,
                        "chapter_end": subject.chapter_end,
                    },
                    "candidate_a": candidate_a_text,
                    "candidate_b": candidate_b_text,
                    "response": {
                        "choice": None,
                        "dimension_scores": {
                            dimension: {"a": None, "b": None}
                            for dimension in BLIND_EVALUATION_DIMENSIONS
                        },
                        "confidence": None,
                        "rationale": "",
                        "evidence_spans": [],
                    },
                }
            )
            private_rows.append(
                PrivatePairMapping(
                    pair_token=pair_token,
                    subject_id=subject.subject_id,
                    scope_type=subject.scope_type,
                    chapter_start=subject.chapter_start,
                    chapter_end=subject.chapter_end,
                    canonical_position=canonical_position,
                    candidate_a_asset_version_id=candidate_a_id,
                    candidate_b_asset_version_id=candidate_b_id,
                )
            )
        public = {
            "contract_version": "blind-evaluation-pack-v1",
            "campaign_token": campaign_token,
            "campaign_version": campaign_version,
            "pack_token": pack_token,
            "reviewer_token": reviewer_token,
            "evaluator_identity_class": reviewer.identity_class.value,
            "protocol_version": protocol_version,
            "evaluation_version": evaluation_version,
            "instructions": {
                "sequence": (
                    "Read each independent task pair separately; these tasks do not form an Arc."
                    if independent else
                    f"Read Chapter pairs {first_chapter} through {last_chapter} "
                    "in order, then complete the Arc pair."
                ),
                "independence": "Complete this pack independently and do not inspect another evaluator's responses.",
                "allowed_choices": ["A", "B", "TIE", "CANNOT_JUDGE"],
                "ordinal_scale": {"minimum": 1, "maximum": 5},
                "dimensions": list(BLIND_EVALUATION_DIMENSIONS),
            },
            "pairs": public_pairs,
        }
        _assert_public_keys(public)
        private_payload = [
            {
                **asdict(item),
                "scope_type": item.scope_type.value,
            }
            for item in private_rows
        ]
        public_json = _canonical(public)
        pack = BlindEvaluationPack(
            reviewer_id=reviewer.reviewer_id,
            pack_token=pack_token,
            content_hash="sha256:"
            + hashlib.sha256(public_json.encode("utf-8")).hexdigest(),
            private_mapping_hash=_hash(private_payload),
            private_mapping=tuple(private_rows),
            _public_payload_json=public_json,
        )
        packs[reviewer.reviewer_id] = pack
    return BlindExportBundle(packs=MappingProxyType(packs))


__all__ = [
    "BlindComparisonSubject",
    "BlindEvaluationPack",
    "BlindEvaluator",
    "BlindExportBundle",
    "PrivatePairMapping",
    "export_blind_evaluation_packs",
]
