from copy import deepcopy
import re
from typing import Any, Mapping

from novel_forge.modules.chapter_authority.author_editor import text_hash
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.domain import canonical_hash

POLICY_VERSION = "working-prose-projection.v2"
MEMORY_POLICY_VERSION = "working-prose-projection.v3"
WORKING_SCHEDULE_POLICY = {"version": "working-story-schedule.v1", "history_basis": "SELECTED_WORKING_PROSE"}
WORKING_SCHEDULE_INSTRUCTION = (
    "Assess Arc progress and prerequisites from the exact selected working prose before choosing future contributions. "
    "Formal acceptance lag does not establish absent experience. Missing passages remain unknown; "
    "do not infer completed obligations or grant character knowledge."
)
CONTEXT_VERSION = "working-manuscript-context.v1"
LEGACY_GUIDANCE = {
    "instruction": "Continue the selected working prose. Excerpts are unreviewed observations, not verified Canon. Plans and possible futures are intent, not past experience. Do not infer character knowledge from reader knowledge; retain uncertainty."
}
CONTINUITY_INSTRUCTION = (
    "Continue only these exact selected working versions. Each passage is an attributed "
    "excerpt with Unicode positions; omitted ranges are unknown here, not evidence of absence. "
    "Distinguish what occurred in this working story, what an individual witnessed or was told, "
    "that individual's inference or belief, attributed rumor, reader-only disclosure and future "
    "plan intent. A true world event does not grant every character knowledge; a character's "
    "belief or statement need not be true. Discarded or unselected versions supply no experience. "
    "Carry realized experiences, practical progress and relationship aftermath into the next "
    "situation without reenacting them merely for formal acceptance. Unresolved dependency "
    "changes retain uncertainty. These passages grant no accepted fact IDs or Canon mutation. "
)
REACTION_INSTRUCTION = (
    "Let perception, goals, prior experience and the current situation motivate action, dialogue "
    "and subtext. Planned emotions and optional consequences are directions, not forced "
    "performances; distinguish binding fictional constraints from conditional possibilities. "
)
CONSEQUENCE_INSTRUCTION = (
    "Important actions affect later choices when the story supports that effect; quiet scenes "
    "and unchanged positions are valid. Do not force conflict, reward, reversal or cost. "
    "Realize the chapter's intended movement without repeating settled progress. If a frozen "
    "plan requires repetition or contradicts the sources, retain that conflict for author/Plan "
    "Change rather than silently altering it. "
)
EXPRESSION_INSTRUCTION = (
    "Use this information to write natural prose, "
    "without explaining these categories or a state checklist to the reader."
)
INSTRUCTION = (
    CONTINUITY_INSTRUCTION
    + REACTION_INSTRUCTION
    + CONSEQUENCE_INSTRUCTION
    + EXPRESSION_INSTRUCTION
)


def working_instruction(policy: Mapping[str, Any]) -> str:
    focus = policy["guidance_mode"]
    memory = (
        "Working observations are fallible source-bound navigation, never Canon or verified knowledge. "
        "Use their exact historical passages to assess current character states, attributed knowledge, "
        "relationships, actions, consequences and outstanding promises. Latest means latest observed "
        "statement, not proven truth. Missing or stale memory remains unknown; retain subjective and reader scopes. "
        "If the declared output schema permits working_memory_json, you may return a separate JSON-string "
        "array of observations grounded only in the prose you just wrote; omission must not impair prose. "
        "Each object has kind (CHARACTER_STATE, KNOWLEDGE, RELATIONSHIP, EVENT, CONSEQUENCE, PROMISE), "
        "subject, state_key, claim, perspective (OBSERVED, BELIEF, HEARSAY, READER_ONLY), knowledge_owner "
        "(empty for unattributed world observations or reader-only disclosures), an unambiguous literal quote, "
        "and causes (only observation_ids present in the frozen working memory, or []). Do not turn future "
        "plans into past events or return this metadata inside Scene prose. "
        if policy["version"] == MEMORY_POLICY_VERSION else ""
    )
    return (
        CONTINUITY_INSTRUCTION
        + (REACTION_INSTRUCTION if focus in {"CHARACTER_REACTION", "COMBINED"} else "")
        + (
            CONSEQUENCE_INSTRUCTION
            if focus in {"ACTION_CONSEQUENCES", "COMBINED"}
            else ""
        )
        + EXPRESSION_INSTRUCTION
        + memory
    )


def working_prose_policy(content: Mapping[str, Any]) -> dict[str, Any] | None:
    value = content.get("working_prose_policy")
    if value is None:
        return None
    keys = {
        "version",
        "history_chapters",
        "recent_complete_chapters",
        "max_characters",
        "queries",
        "guidance_mode",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != keys
        or value.get("version") not in {POLICY_VERSION, MEMORY_POLICY_VERSION}
        or not isinstance(value.get("guidance_mode"), str)
        or value.get("guidance_mode")
        not in {
            "CONTINUITY_ONLY",
            "CHARACTER_REACTION",
            "ACTION_CONSEQUENCES",
            "COMBINED",
        }
        or type(value.get("history_chapters")) is not int
        or not 1 <= value["history_chapters"] <= (10000 if value["version"] == MEMORY_POLICY_VERSION else 32)
        or type(value.get("recent_complete_chapters")) is not int
        or not 1 <= value["recent_complete_chapters"] <= value["history_chapters"]
        or type(value.get("max_characters")) is not int
        or not 1 <= value["max_characters"] <= 200_000
        or not isinstance(value.get("queries"), list)
        or len(value["queries"]) > 16
        or any(
            not isinstance(q, str) or not q.strip() or len(q) > 200
            for q in value["queries"]
        )
    ):
        raise KernelError(
            "WORKING_PROSE_POLICY_INVALID",
            "Working prose requires a complete bounded versioned policy",
        )
    return deepcopy(dict(value))


def _paragraph_ranges(text: str) -> list[tuple[int, int]]:
    cuts = [0, *(match.end() for match in re.finditer(r"\n[ \t]*\n", text)), len(text)]
    return [(start, end) for start, end in zip(cuts, cuts[1:]) if start < end]


def project_working_sources(
    sources: list[dict[str, Any]], *, target_chapter: int, policy: Mapping[str, Any],
    memory: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    policy = working_prose_policy({"working_prose_policy": policy})
    units = [
        (row["chapter"], start, end, row["text"][start:end])
        for row in sources
        for start, end in _paragraph_ranges(row["text"])
    ]
    recent_start = max(1, target_chapter - policy["recent_complete_chapters"])
    mandatory = [unit for unit in units if unit[0] >= recent_start]
    remaining = policy["max_characters"] - sum(len(unit[3]) for unit in mandatory)
    if remaining < 0:
        raise KernelError(
            "WORKING_PROSE_REQUIRED_INPUT_OVERFLOW",
            "Complete recent sources exceed the selected allocation; choose a new policy",
        )
    chosen = {(number, start, end) for number, start, end, _ in mandatory}
    scored = [
        (
            sum(text.casefold().count(q.casefold()) for q in policy["queries"]),
            number,
            start,
            end,
            text,
        )
        for number, start, end, text in units
        if number < recent_start
    ]
    evidence = {(row["source"]["chapter"], row["location"]["start"], row["location"]["end"])
                for row in (memory or {}).get("entries", [])}
    def evidence_priority(unit):
        _, number, start, end, _ = unit
        return int(any(n == number and start <= low < high <= end for n, low, high in evidence))
    for score, number, start, end, text in sorted(
        scored, key=lambda row: (-evidence_priority(row), -row[0], -row[1], row[2])
    ):
        if len(text) <= remaining:
            chosen.add((number, start, end))
            remaining -= len(text)
    projected = []
    for source in sources:
        text = source["text"]
        passages, omitted = [], []
        for start, end in _paragraph_ranges(text):
            if (source["chapter"], start, end) in chosen:
                passages.append(
                    {
                        "start": start,
                        "end": end,
                        "text": text[start:end],
                        "text_hash": text_hash(text[start:end]),
                    }
                )
            elif omitted and omitted[-1]["end"] == start:
                omitted[-1]["end"] = end
            else:
                omitted.append({"start": start, "end": end})
        projected.append(
            {
                **{k: deepcopy(v) for k, v in source.items() if k not in {"text", "observations", "memory_provenance"}},
                "source_characters": len(text),
                "passages": passages,
                "omitted_ranges": omitted,
                "status": "UNREVIEWED_WORKING_PROSE",
                "character_knowledge": "NOT_VERIFIED",
            }
        )
    return projected


def validate_working_projection(
    snapshot: Mapping[str, Any],
    *,
    project_id: str,
    book_id: str | None = None,
    target_chapter: int | None = None,
    accepted_through_chapter: int | None = None,
) -> None:
    policy = working_prose_policy(
        {"working_prose_policy": snapshot.get("projection_policy")}
    )
    if (
        policy is None
        or snapshot.get("version") != CONTEXT_VERSION
        or snapshot.get("authority") != "AUTHOR_WORKING_PROSE_ONLY"
        or snapshot.get("structured_facts") != []
        or snapshot.get("project_id") != project_id
        or book_id is not None
        and snapshot.get("book_id") != book_id
        or target_chapter is not None
        and snapshot.get("target_chapter") != target_chapter
        or accepted_through_chapter is not None
        and snapshot.get("accepted_through_chapter") != accepted_through_chapter
        or not isinstance(snapshot.get("book_id"), str)
        or not snapshot["book_id"]
        or not isinstance(snapshot.get("book_run_id"), str)
        or not snapshot["book_run_id"]
        or type(snapshot.get("target_chapter")) is not int
        or type(snapshot.get("accepted_through_chapter")) is not int
        or not 0 <= snapshot["accepted_through_chapter"] < snapshot["target_chapter"]
        or snapshot.get("instruction") != working_instruction(policy)
        or snapshot.get("snapshot_hash")
        != canonical_hash({k: v for k, v in snapshot.items() if k != "snapshot_hash"})
    ):
        raise KernelError(
            "WORKING_PROSE_PROJECTION_INVALID",
            "Working projection requires exact source scope, boundary and identity",
        )
    if policy is None or not isinstance(snapshot.get("sources"), list):
        raise KernelError(
            "WORKING_PROSE_PROJECTION_INVALID",
            "Working projection requires its policy and sources",
        )
    numbers, characters = [], 0
    for row in snapshot["sources"]:
        if (
            not isinstance(row, Mapping)
            or set(row)
            - {
                "chapter",
                "asset_version_id",
                "content_hash",
                "text_hash",
                "source_characters",
                "passages",
                "omitted_ranges",
                "status",
                "character_knowledge",
                "dependency_changes",
            }
            or type(row.get("chapter")) is not int
            or not max(1, snapshot["target_chapter"] - policy["history_chapters"])
            <= row["chapter"]
            < snapshot["target_chapter"]
            or row.get("status") != "UNREVIEWED_WORKING_PROSE"
            or row.get("character_knowledge") != "NOT_VERIFIED"
            or any(
                not isinstance(row.get(k), str) or not row[k]
                for k in ("asset_version_id", "content_hash", "text_hash")
            )
            or type(row.get("source_characters")) is not int
            or row["source_characters"] <= 0
            or not isinstance(row.get("passages"), list)
            or not isinstance(row.get("omitted_ranges"), list)
        ):
            raise KernelError(
                "WORKING_PROSE_PROJECTION_INVALID",
                "Working source is incomplete or falsely promoted",
            )
        ranges = []
        for passage in row["passages"]:
            if (
                not isinstance(passage, Mapping)
                or set(passage) != {"start", "end", "text", "text_hash"}
                or not isinstance(passage.get("text"), str)
                or not passage["text"]
                or passage.get("text_hash") != text_hash(passage["text"])
            ):
                raise KernelError(
                    "WORKING_PROSE_PROJECTION_INVALID",
                    "Working passages must retain their literal identity",
                )
            characters += len(passage["text"])
            ranges.append(
                (passage.get("start"), passage.get("end"), len(passage["text"]))
            )
        ranges.extend(
            (r.get("start"), r.get("end"), None)
            for r in row["omitted_ranges"]
            if isinstance(r, Mapping) and set(r) == {"start", "end"}
        )
        if len(ranges) != len(row["passages"]) + len(row["omitted_ranges"]):
            raise KernelError(
                "WORKING_PROSE_PROJECTION_INVALID", "Omissions must be explicit ranges"
            )
        if any(
            type(start) is not int
            or type(end) is not int
            or not 0 <= start < end <= row["source_characters"]
            or length is not None
            and end - start != length
            for start, end, length in ranges
        ):
            raise KernelError(
                "WORKING_PROSE_PROJECTION_INVALID", "Invalid Unicode range"
            )
        if row["passages"] != sorted(row["passages"], key=lambda p: p["start"]):
            raise KernelError(
                "WORKING_PROSE_PROJECTION_INVALID",
                "Working passages require source order",
            )
        ranges.sort()
        if (
            not ranges
            or ranges[0][0] != 0
            or ranges[-1][1] != row["source_characters"]
            or any(a[1] != b[0] for a, b in zip(ranges, ranges[1:]))
            or row["chapter"]
            >= snapshot["target_chapter"] - policy["recent_complete_chapters"]
            and row["omitted_ranges"]
        ):
            raise KernelError(
                "WORKING_PROSE_PROJECTION_INVALID",
                "Working coverage must partition each source and retain complete recent chapters",
            )
        numbers.append(row["chapter"])
    expected = list(
        range(
            max(1, snapshot["target_chapter"] - policy["history_chapters"]),
            snapshot["target_chapter"],
        )
    )
    if policy["version"] == MEMORY_POLICY_VERSION or snapshot.get("working_memory") is not None:
        from novel_forge.modules.narrative_state.working_memory import validate_memory_packet
        validate_memory_packet(snapshot["working_memory"], snapshot["sources"])
        if policy["version"] != MEMORY_POLICY_VERSION:
            raise KernelError("WORKING_MEMORY_POLICY_INVALID", "Frozen older projections cannot acquire observations")
    if numbers != expected or characters > policy["max_characters"]:
        raise KernelError(
            "WORKING_PROSE_PROJECTION_INVALID",
            "Working sources require complete ordered version coverage within allocation",
        )
