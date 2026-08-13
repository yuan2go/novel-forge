"""Pure loading and validation for a frozen long-form proof contract.

The contract is an operator input.  This module performs no database writes,
Provider calls, scheduler ticks, or business-state activation.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "novel-forge.longform-proof-contract.v1"
TARGET_CHAPTERS = 300
CHAPTERS_PER_VOLUME = 30
CHECKPOINT_CHAPTERS = (30, 100, 300)
REQUIRED_LANGUAGE = "zh-CN"
MINIMUM_ZH_CN_HAN_RATIO = 0.60


def _mapping(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return {str(key): item for key, item in value.items()}


def _objects(value: Any, *, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(
        isinstance(item, Mapping) for item in value
    ):
        raise ValueError(f"{field} must be a list of objects")
    return [dict(item) for item in value]


def _nonempty(value: Any, *, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{field} is required")
    return result


def _sha256(value: Any, *, field: str) -> str:
    result = _nonempty(value, field=field)
    digest = result.removeprefix("sha256:")
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest.lower()
    ):
        raise ValueError(f"{field} must be a SHA-256 identity")
    return "sha256:" + digest.lower()


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _expand_chapter_matrix(
    volumes: list[dict[str, Any]], chapter_pattern: list[dict[str, Any]]
) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for volume in volumes:
        volume_number = int(volume["volume"])
        for beat in chapter_pattern:
            offset = int(beat["offset"])
            rows.append(
                {
                    "chapter": (volume_number - 1) * CHAPTERS_PER_VOLUME
                    + offset,
                    "volume": volume_number,
                    "volume_title": str(volume["title"]),
                    "volume_goal": str(volume["goal"]),
                    "volume_pressure": str(volume["pressure"]),
                    "volume_reward": str(volume["reward"]),
                    "volume_cost": str(volume["cost"]),
                    "volume_ending_escalation": str(
                        volume["ending_escalation"]
                    ),
                    **{
                        key: value
                        for key, value in beat.items()
                        if key != "offset"
                    },
                    "offset": offset,
                }
            )
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class LongformCampaignContract:
    """Validated immutable representation of one Campaign version."""

    campaign_id: str
    campaign_version: int
    baseline_git_sha: str
    migration_head: str
    language: str
    target_chapters: int
    checkpoint_chapters: tuple[int, ...]
    chapter_matrix: tuple[dict[str, Any], ...]
    _canonical_payload: str

    @classmethod
    def from_mapping(
        cls, raw_payload: Mapping[str, Any]
    ) -> "LongformCampaignContract":
        payload = json.loads(json.dumps(dict(raw_payload), ensure_ascii=False))
        payload.pop("contract_identity", None)
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported long-form proof contract schema")

        campaign_id = _nonempty(payload.get("campaign_id"), field="campaign_id")
        campaign_version = int(payload.get("campaign_version") or 0)
        if campaign_version <= 0:
            raise ValueError("campaign_version must be positive")
        baseline_git_sha = _nonempty(
            payload.get("baseline_git_sha"), field="baseline_git_sha"
        )
        if len(baseline_git_sha) != 40 or any(
            character not in "0123456789abcdef"
            for character in baseline_git_sha.lower()
        ):
            raise ValueError("baseline_git_sha must be a full Git SHA")
        migration_head = _nonempty(
            payload.get("migration_head"), field="migration_head"
        )

        freeze = _mapping(payload.get("freeze_policy"), field="freeze_policy")
        if not (
            freeze.get("ground_truth_mutable_after_chapter_1") is False
            and freeze.get("thresholds_mutable_after_chapter_1") is False
            and freeze.get("material_change_requires_new_campaign_version") is True
        ):
            raise ValueError("Ground Truth and thresholds must be immutable")

        book = _mapping(payload.get("book"), field="book")
        _nonempty(book.get("title"), field="book.title")
        language = _nonempty(book.get("language"), field="book.language")
        if language != REQUIRED_LANGUAGE:
            raise ValueError(f"book.language must equal {REQUIRED_LANGUAGE}")
        target_chapters = int(book.get("target_chapters") or 0)
        if target_chapters != TARGET_CHAPTERS:
            raise ValueError("Campaign target_chapters must equal 300")
        volumes = _objects(book.get("volumes"), field="book.volumes")
        if [int(item.get("volume") or 0) for item in volumes] != list(
            range(1, 11)
        ):
            raise ValueError("book volumes must be contiguous 1..10")
        for volume in volumes:
            for field in (
                "title",
                "goal",
                "pressure",
                "reward",
                "cost",
                "ending_escalation",
            ):
                _nonempty(volume.get(field), field=f"book.volumes.{field}")
        chapter_pattern = _objects(
            book.get("chapter_pattern"), field="book.chapter_pattern"
        )
        if [int(item.get("offset") or 0) for item in chapter_pattern] != list(
            range(1, CHAPTERS_PER_VOLUME + 1)
        ):
            raise ValueError("chapter_pattern offsets must be contiguous 1..30")
        for beat in chapter_pattern:
            for field in (
                "function",
                "pressure_delta",
                "information_gain",
                "hook",
            ):
                _nonempty(beat.get(field), field=f"book.chapter_pattern.{field}")
        chapter_matrix = _expand_chapter_matrix(volumes, chapter_pattern)
        if [row["chapter"] for row in chapter_matrix] != list(
            range(1, TARGET_CHAPTERS + 1)
        ):
            raise ValueError("expanded chapter matrix must be contiguous 1..300")

        ground_truth = _mapping(
            payload.get("ground_truth"), field="ground_truth"
        )
        world_rules = _objects(
            ground_truth.get("world_rules"), field="ground_truth.world_rules"
        )
        characters = _objects(
            ground_truth.get("characters"), field="ground_truth.characters"
        )
        if not world_rules or not characters:
            raise ValueError("Ground Truth requires world rules and characters")

        knowledge = _objects(
            ground_truth.get("knowledge_matrix"),
            field="ground_truth.knowledge_matrix",
        )
        knowledge_from: dict[str, int] = {}
        for item in knowledge:
            fact_id = _nonempty(item.get("fact_id"), field="knowledge.fact_id")
            if fact_id in knowledge_from:
                raise ValueError(f"duplicate knowledge fact: {fact_id}")
            known_from = int(item.get("known_from_chapter") or 0)
            if not 1 <= known_from <= TARGET_CHAPTERS:
                raise ValueError("knowledge known_from_chapter is out of range")
            knowledge_from[fact_id] = known_from
            _nonempty(item.get("holder"), field="knowledge.holder")

        obligations = _objects(
            ground_truth.get("obligations"),
            field="ground_truth.obligations",
        )
        for item in obligations:
            _nonempty(item.get("obligation_id"), field="obligation.obligation_id")
            setup = int(item.get("setup_chapter") or 0)
            payoff = int(item.get("payoff_chapter") or 0)
            if not 1 <= setup < payoff <= TARGET_CHAPTERS:
                raise ValueError(
                    "obligation payoff must follow setup within the Campaign"
                )
            _nonempty(item.get("setup"), field="obligation.setup")
            _nonempty(item.get("payoff"), field="obligation.payoff")

        checkpoints = _objects(
            ground_truth.get("state_checkpoints"),
            field="ground_truth.state_checkpoints",
        )
        if tuple(int(item.get("chapter") or 0) for item in checkpoints) != (
            CHECKPOINT_CHAPTERS
        ):
            raise ValueError("state checkpoints must be exactly 30, 100, 300")

        probes = _objects(
            ground_truth.get("context_probes"),
            field="ground_truth.context_probes",
        )
        for probe in probes:
            chapter = int(probe.get("chapter") or 0)
            if not 1 <= chapter <= TARGET_CHAPTERS:
                raise ValueError("context probe chapter is out of range")
            for fact_id in probe.get("must_include") or []:
                if fact_id not in knowledge_from:
                    raise ValueError(f"unknown context fact: {fact_id}")
                if knowledge_from[fact_id] > chapter:
                    raise ValueError(
                        f"context probe includes future knowledge: {fact_id}"
                    )
            for fact_id in probe.get("must_exclude") or []:
                if fact_id not in knowledge_from:
                    raise ValueError(f"unknown context fact: {fact_id}")

        thresholds = _mapping(
            payload.get("proof_thresholds"), field="proof_thresholds"
        )
        checkpoint_chapters = tuple(
            int(item) for item in thresholds.get("checkpoint_chapters") or []
        )
        if checkpoint_chapters != CHECKPOINT_CHAPTERS:
            raise ValueError("proof checkpoint_chapters must be 30, 100, 300")
        if int(thresholds.get("minimum_chapter_characters") or 0) < 80:
            raise ValueError("minimum_chapter_characters is too low")
        for name in ("minimum_context_precision", "minimum_context_recall"):
            value = float(thresholds.get(name) or 0)
            if not 0 < value <= 1:
                raise ValueError(f"{name} must be in (0,1]")

        provider = _mapping(payload.get("provider"), field="provider")
        _nonempty(provider.get("provider"), field="provider.provider")
        _nonempty(provider.get("model"), field="provider.model")
        _nonempty(
            provider.get("reasoning_effort"), field="provider.reasoning_effort"
        )
        if provider.get("silent_fallback") is not False:
            raise ValueError("Provider silent fallback must be disabled")

        bindings = _mapping(
            payload.get("runtime_bindings"), field="runtime_bindings"
        )
        _nonempty(
            bindings.get("capability_pack_id"),
            field="runtime_bindings.capability_pack_id",
        )
        _nonempty(
            bindings.get("capability_pack_version"),
            field="runtime_bindings.capability_pack_version",
        )
        _sha256(
            bindings.get("capability_pack_manifest_hash"),
            field="runtime_bindings.capability_pack_manifest_hash",
        )
        skill_bindings = _objects(
            bindings.get("skill_bindings"),
            field="runtime_bindings.skill_bindings",
        )
        if not skill_bindings:
            raise ValueError("runtime_bindings requires Skill identities")
        for item in skill_bindings:
            _nonempty(item.get("skill_ref"), field="skill.skill_ref")
            _nonempty(item.get("version"), field="skill.version")
            _sha256(item.get("content_hash"), field="skill.content_hash")

        canonical_payload = _canonical(payload)
        return cls(
            campaign_id=campaign_id,
            campaign_version=campaign_version,
            baseline_git_sha=baseline_git_sha.lower(),
            migration_head=migration_head,
            language=language,
            target_chapters=target_chapters,
            checkpoint_chapters=checkpoint_chapters,
            chapter_matrix=chapter_matrix,
            _canonical_payload=canonical_payload,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a detached copy of the canonical contract payload."""

        return json.loads(self._canonical_payload)


def contract_identity(contract: LongformCampaignContract) -> str:
    digest = hashlib.sha256(contract._canonical_payload.encode("utf-8")).hexdigest()
    return "sha256:" + digest


def evaluate_proof_language(
    text: str,
    *,
    required_language: str,
) -> dict[str, Any]:
    """Fail-closed language evaluation for reader-facing Proof prose.

    Authority acceptance remains untouched.  This independent Proof check counts
    Han characters and ASCII Latin letters, ignoring punctuation and numerals.
    """

    han_characters = sum(
        1
        for character in text
        if "\u3400" <= character <= "\u4dbf" or "\u4e00" <= character <= "\u9fff"
    )
    latin_characters = sum(
        1 for character in text if "a" <= character.casefold() <= "z"
    )
    considered_characters = han_characters + latin_characters
    ratio = han_characters / considered_characters if considered_characters else 0.0
    if required_language != REQUIRED_LANGUAGE:
        status = "FAILED"
        reason = "UNSUPPORTED_REQUIRED_LANGUAGE"
    elif han_characters == 0 or ratio < MINIMUM_ZH_CN_HAN_RATIO:
        status = "FAILED"
        reason = "PROSE_NOT_PRIMARILY_ZH_CN"
    else:
        status = "PASSED"
        reason = "PROSE_PRIMARILY_ZH_CN"
    return {
        "status": status,
        "reason": reason,
        "required_language": required_language,
        "han_characters": han_characters,
        "latin_characters": latin_characters,
        "considered_characters": considered_characters,
        "han_character_ratio": round(ratio, 6),
        "minimum_han_character_ratio": MINIMUM_ZH_CN_HAN_RATIO,
    }


def load_campaign_contract(path: str | Path) -> LongformCampaignContract:
    source = Path(path)
    raw = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError("long-form proof contract root must be an object")
    declared = _nonempty(raw.get("contract_identity"), field="contract_identity")
    contract = LongformCampaignContract.from_mapping(raw)
    actual = contract_identity(contract)
    if declared != actual:
        raise ValueError(
            f"long-form proof contract identity drift: declared {declared}, actual {actual}"
        )
    return contract


__all__ = [
    "CHECKPOINT_CHAPTERS",
    "LongformCampaignContract",
    "contract_identity",
    "evaluate_proof_language",
    "load_campaign_contract",
]
