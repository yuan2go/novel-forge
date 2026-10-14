from copy import deepcopy
import re
from typing import Any, Mapping

from novel_forge.modules.chapter_authority.author_editor import text_hash
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.domain import canonical_hash

POLICY_VERSION = "working-prose-projection.v2"
MEMORY_POLICY_VERSION = "working-prose-projection.v3"
PROGRESSION_POLICY_VERSION = "working-prose-projection.v4"
LONGFORM_POLICY_VERSION = "working-prose-projection.v5"
MEMORY_POLICY_VERSIONS = {MEMORY_POLICY_VERSION, PROGRESSION_POLICY_VERSION, LONGFORM_POLICY_VERSION}
RESOLVED_POLICY_VERSIONS = {PROGRESSION_POLICY_VERSION, LONGFORM_POLICY_VERSION}
POLICY_VERSIONS = {POLICY_VERSION, *MEMORY_POLICY_VERSIONS}
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
PROGRESSION_INSTRUCTION = (
    "Consequence-forward chapter contract: resolved inquiries, confirmed arrangements and daily "
    "baselines in the effective working sources are starting premises, not scenes to perform again. "
    "Inherit their realized consequences while retaining each character's actual knowledge limits. "
    "Prior prose supplies continuity, not a model for repeating its domestic framing: compress "
    "necessary eating, washing, tool packing and resting transitions to a single bridging clause. "
    "Planning must give the declared chapter length enough dramatic capacity, including a "
    "4000–5000 Chinese-character allocation when supplied. Use three connected "
    "dramatic turns in the existing scene goals, conflicts, beats and exit states: opening immediate "
    "friction inherited from the predecessor or the opening predicament; middle substantive escalation through an attempted "
    "action, resistance, adjustment and a real cost-gain exchange; ending an irreversible, measurable "
    "change in ability, leverage, obligation or risk that leaves an open action loop for the next chapter. "
    "The turns can share a scene; do not manufacture three scenes or generic peril. Use physical "
    "execution, trial and adjustment, concrete obstacle friction or competing interests to earn "
    "progress within the characters' established abilities and constraints. Costs can be resources, "
    "time, foregone options, obligation or exposed leverage; choose what this story supports. "
    "Permission for quiet scenes does not waive progression: resistance can be a practical limit "
    "or incompatible interests, and an irreversible shift can be a voluntary commitment or changed "
    "access rather than injury or loss. Name this friction, the attempted response and its consequence "
    "in the existing plan fields; a reminder to ask again later cannot replace a triggered next action. "
    "Repeated verbal inquiry or passive confirmation cannot supply the middle. "
    "A practical trial must change a task that matters to the participants now; repeated measurements, "
    "written records and explanations of the same limit do not supply further turns. "
    "Writer must realize these planned turns in concrete action; spend the length allocation on their "
    "choices, attempts, resistance, negotiation and consequences, rather than internal recap. "
    "Dialogue must change a decision, price, permission or relationship. End on the changed situation demanding a next action, never "
    "a static reset of tidying tools, reviewing the day or going to sleep. Quiet breakthroughs can carry "
    "this hook without an unrelated threat. If a frozen plan instead mandates routine padding or a "
    "static ending, expose the conflict for an authorized Planning/Plan Change correction; Writer "
    "cannot silently replace the plan. These are creation directives, not automatic literary checks. "
)
LONGFORM_INSTRUCTION = (
    "Use realized experiences and supported consequences as the next chapter's starting situation. "
    "Let this Book's goals, established character choices and unresolved commitments determine "
    "what develops or pays off now. Use the author's declared chapter length and the frozen plan "
    "to allocate sufficient meaningful action, conversation, reflection or quiet development. "
    "No fixed number of turns, reversal, cost, irreversible change or dialogue outcome is required. "
    "Return structural contradictions to the first affected design layer and use authorized Plan "
    "Change for active future plans; Writer retains the frozen fictional constraints. "
    "Earlier source identities locate host evidence. Their omitted prose remains unknown here, "
    "not evidence that an experience never happened or that a promise was fulfilled. "
    "Source receipts and workflow status impose no duties on fictional characters. "
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
        if policy["version"] in MEMORY_POLICY_VERSIONS else ""
    )
    return (
        (CONTINUITY_INSTRUCTION.replace("selected working versions", "effective working versions")
            .replace("Discarded or unselected versions", "Discarded or superseded versions")
            if policy["version"] in RESOLVED_POLICY_VERSIONS else CONTINUITY_INSTRUCTION)
        + (REACTION_INSTRUCTION if focus in {"CHARACTER_REACTION", "COMBINED"} else "")
        + (
            (PROGRESSION_INSTRUCTION if policy["version"] == PROGRESSION_POLICY_VERSION
                else CONSEQUENCE_INSTRUCTION + LONGFORM_INSTRUCTION if policy["version"] == LONGFORM_POLICY_VERSION
                else CONSEQUENCE_INSTRUCTION)
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
        or value.get("version") not in POLICY_VERSIONS
        or not isinstance(value.get("guidance_mode"), str)
        or value.get("guidance_mode")
        not in {
            "CONTINUITY_ONLY",
            "CHARACTER_REACTION",
            "ACTION_CONSEQUENCES",
            "COMBINED",
        }
        or value.get("version") == PROGRESSION_POLICY_VERSION and value.get("guidance_mode") != "COMBINED"
        or type(value.get("history_chapters")) is not int
        or not 1 <= value["history_chapters"] <= (10000 if value["version"] in MEMORY_POLICY_VERSIONS else 32)
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
    chosen_numbers = {number for number, _, _ in chosen}
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
        if len(text) <= remaining and (policy["version"] != LONGFORM_POLICY_VERSION
                or number in chosen_numbers or len(chosen_numbers) < policy["history_chapters"]):
            chosen.add((number, start, end))
            chosen_numbers.add(number)
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


def _source_identity(source: Mapping[str, Any]) -> dict[str, Any]:
    keys = {"chapter", "asset_version_id", "content_hash", "text_hash", "source_characters", "source_resolution", "dependency_changes"}
    return {key: deepcopy(value) for key, value in source.items() if key in keys}


def freeze_source_history(sources: list[dict[str, Any]], *, book: Mapping[str, Any], target_chapter: int) -> dict[str, Any]:
    body = {"contract_version": "working-source-history.v1",
        **{key: book[key] for key in ("project_id", "book_id", "book_run_id")},
        "target_chapter": target_chapter, "source_count": len(sources),
        "sources": [_source_identity(source) for source in sources]}
    return {**body, "content_hash": canonical_hash(body)}


def _validate_source_resolution(row: Mapping[str, Any]) -> None:
    resolution = row.get("source_resolution")
    if (not isinstance(resolution, Mapping)
        or set(resolution) != {"native_source", "native_basis", "overrides", "effective_source"}
        or resolution["native_basis"] not in {"NATIVE_DELIVERY", "ACCEPTED_OUTCOME", "NATIVE_DRAFT_OUTPUT"}
        or resolution["effective_source"] != {"asset_version_id": row["asset_version_id"], "content_hash": row["content_hash"]}
        or not isinstance(resolution["overrides"], list)
        or resolution["native_basis"] == "ACCEPTED_OUTCOME" and bool(resolution["overrides"])):
        raise KernelError("WORKING_PROSE_SOURCE_RESOLUTION_INVALID", "Effective prose requires its exact native source and selection lineage")
    pointers = [resolution["native_source"], *resolution["overrides"]]
    if any(not isinstance(pointer, Mapping) or set(pointer) != {"asset_version_id", "content_hash"}
        or any(not isinstance(pointer[key], str) or not pointer[key] for key in pointer) for pointer in pointers):
        raise KernelError("WORKING_PROSE_SOURCE_RESOLUTION_INVALID", "Source resolution pointers must retain exact version hashes")
    if not resolution["overrides"] and resolution["native_source"] != resolution["effective_source"]:
        raise KernelError("WORKING_PROSE_SOURCE_RESOLUTION_INVALID", "A changed effective source requires its selection lineage")


def working_source_rows(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    if (snapshot.get("projection_policy") or {}).get("version") != LONGFORM_POLICY_VERSION:
        return snapshot["sources"]
    history = snapshot.get("source_history")
    expected = {"contract_version", "project_id", "book_id", "book_run_id", "target_chapter", "source_count", "sources", "content_hash"}
    if (not isinstance(history, Mapping) or set(history) != expected
            or history["contract_version"] != "working-source-history.v1"
            or any(history[key] != snapshot[key] for key in ("project_id", "book_id", "book_run_id", "target_chapter"))
            or not isinstance(history["sources"], list)
            or type(history["source_count"]) is not int
            or history["source_count"] != snapshot["target_chapter"] - 1
            or history["content_hash"] != canonical_hash({key: value for key, value in history.items() if key != "content_hash"})):
        raise KernelError("WORKING_PROSE_HISTORY_INVALID", "Long-form host evidence requires its complete exact predecessor manifest")
    numbers = []
    for source in history["sources"]:
        if (not isinstance(source, Mapping)
                or set(source) - {"chapter", "asset_version_id", "content_hash", "text_hash", "source_characters", "source_resolution", "dependency_changes"}
                or type(source.get("chapter")) is not int
                or any(not isinstance(source.get(key), str) or not source[key] for key in ("asset_version_id", "content_hash", "text_hash"))
                or type(source.get("source_characters")) is not int or source["source_characters"] <= 0):
            raise KernelError("WORKING_PROSE_HISTORY_INVALID", "Every predecessor must retain its exact source identity")
        _validate_source_resolution(source)
        numbers.append(source["chapter"])
    if numbers != list(range(1, snapshot["target_chapter"])):
        raise KernelError("WORKING_PROSE_HISTORY_INVALID", "Long-form history requires every ordered predecessor version")
    return history["sources"]


def project_working_history_for_provider(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    if (snapshot.get("projection_policy") or {}).get("version") != LONGFORM_POLICY_VERSION:
        return deepcopy(dict(snapshot))
    validate_working_projection(snapshot, project_id=snapshot["project_id"], book_id=snapshot["book_id"])
    if snapshot["source_history"]["contract_version"] == "working-source-history-reference.v1":
        return deepcopy(dict(snapshot))
    working_source_rows(snapshot)
    result = deepcopy(dict(snapshot))
    history = result["source_history"]
    coverage = result["working_memory"]["source_coverage"]
    visible = {source["asset_version_id"] for source in result["sources"]}
    result["source_history"] = {"contract_version": "working-source-history-reference.v1",
        **{key: history[key] for key in ("project_id", "book_id", "book_run_id", "target_chapter", "source_count")},
        "source_history_hash": history["content_hash"], "source_snapshot_hash": snapshot["snapshot_hash"],
        "visible_sources_hash": canonical_hash([_source_identity(source) for source in result["sources"]]),
        "memory_source_coverage_hash": canonical_hash(coverage),
        "boundary": "OMITTED_PROSE_UNKNOWN_NO_ACCEPTED_FACTS"}
    memory = result["working_memory"]
    memory["source_coverage"] = [row for row in coverage if row["asset_version_id"] in visible]
    memory["packet_hash"] = canonical_hash({key: value for key, value in memory.items() if key != "packet_hash"})
    result["snapshot_hash"] = canonical_hash({key: value for key, value in result.items() if key != "snapshot_hash"})
    validate_working_projection(result, project_id=snapshot["project_id"], book_id=snapshot["book_id"])
    return result


def _validate_history_reference(snapshot: Mapping[str, Any]) -> None:
    history = snapshot["source_history"]
    expected = {"contract_version", "project_id", "book_id", "book_run_id", "target_chapter", "source_count",
        "source_history_hash", "source_snapshot_hash", "visible_sources_hash", "memory_source_coverage_hash", "boundary"}
    if (set(history) != expected or history["contract_version"] != "working-source-history-reference.v1"
            or any(history[key] != snapshot[key] for key in ("project_id", "book_id", "book_run_id", "target_chapter"))
            or type(history["source_count"]) is not int
            or history["source_count"] != snapshot["target_chapter"] - 1
            or history["boundary"] != "OMITTED_PROSE_UNKNOWN_NO_ACCEPTED_FACTS"
            or any(not isinstance(history[key], str) or not history[key].startswith("sha256:")
                for key in ("source_history_hash", "source_snapshot_hash", "memory_source_coverage_hash"))
            or history["visible_sources_hash"] != canonical_hash([_source_identity(source) for source in snapshot["sources"]])):
        raise KernelError("WORKING_PROSE_HISTORY_INVALID", "Provider history is a scoped reference to immutable host evidence")


def complete_prose_delivery(snapshot: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_working_projection(snapshot, project_id=snapshot.get("project_id"), book_id=snapshot.get("book_id"))
    delivered = deepcopy(dict(snapshot))
    coalesced = []
    for source in delivered["sources"]:
        passages = source["passages"]
        if source["omitted_ranges"] or len(passages) <= 1:
            continue
        text = "".join(passage["text"] for passage in passages)
        if len(text) != source["source_characters"] or text_hash(text) != source["text_hash"]:
            raise KernelError("WORKING_PROSE_DELIVERY_DRIFT", "Complete delivery must reconstruct the exact retained source text")
        source["passages"] = [{"start": 0, "end": len(text), "text": text, "text_hash": source["text_hash"]}]
        coalesced.append({"chapter": source["chapter"], "asset_version_id": source["asset_version_id"],
            "content_hash": source["content_hash"], "text_hash": source["text_hash"], "original_passage_count": len(passages)})
    delivered["snapshot_hash"] = canonical_hash({k: v for k, v in delivered.items() if k != "snapshot_hash"})
    validate_working_projection(delivered, project_id=snapshot["project_id"], book_id=snapshot["book_id"])
    receipt = {"contract_version": "world-working-prose-delivery.v1", "source_snapshot_hash": snapshot["snapshot_hash"],
        "delivery_snapshot_hash": delivered["snapshot_hash"], "coalesced_sources": coalesced,
        "accepted_history_mutation_allowed": False, "character_knowledge_granted": False}
    return delivered, receipt


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
    if policy and policy["version"] == PROGRESSION_POLICY_VERSION and type(snapshot.get("target_chapter")) is int and snapshot["target_chapter"] - 1 > policy["history_chapters"]:
        raise KernelError("WORKING_PROSE_HISTORY_INCOMPLETE", "Progression requires the contiguous predecessor chain within its declared history allocation")
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
    history_sources = None
    if policy["version"] == LONGFORM_POLICY_VERSION:
        history = snapshot.get("source_history")
        if isinstance(history, Mapping) and history.get("contract_version") == "working-source-history-reference.v1":
            _validate_history_reference(snapshot)
        else:
            history_sources = {source["chapter"]: source for source in working_source_rows(snapshot)}
    elif "source_history" in snapshot:
        raise KernelError("WORKING_PROSE_HISTORY_INVALID", "Historical projections cannot acquire a new predecessor manifest")
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
                "source_resolution",
            }
            or type(row.get("chapter")) is not int
            or not (1 if policy["version"] == LONGFORM_POLICY_VERSION else max(1, snapshot["target_chapter"] - policy["history_chapters"]))
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
        resolution = row.get("source_resolution")
        if policy["version"] in RESOLVED_POLICY_VERSIONS:
            _validate_source_resolution(row)
        elif resolution is not None:
            raise KernelError("WORKING_PROSE_SOURCE_RESOLUTION_INVALID", "Historical projections cannot acquire new resolution evidence")
        if history_sources is not None and history_sources.get(row["chapter"]) != _source_identity(row):
            raise KernelError("WORKING_PROSE_HISTORY_INVALID", "Projected prose must bind its exact complete host source history")
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
    if policy["version"] == LONGFORM_POLICY_VERSION:
        if (numbers != sorted(set(numbers)) or len(numbers) > policy["history_chapters"]
                or not set(range(max(1, snapshot["target_chapter"] - policy["recent_complete_chapters"]), snapshot["target_chapter"])).issubset(numbers)):
            raise KernelError("WORKING_PROSE_HISTORY_INVALID", "Bounded long-form prose must retain every mandatory recent source")
        expected = numbers
    if policy["version"] in MEMORY_POLICY_VERSIONS or snapshot.get("working_memory") is not None:
        from novel_forge.modules.narrative_state.working_memory import validate_memory_packet
        validate_memory_packet(snapshot["working_memory"], snapshot["sources"])
        if policy["version"] not in MEMORY_POLICY_VERSIONS:
            raise KernelError("WORKING_MEMORY_POLICY_INVALID", "Frozen older projections cannot acquire observations")
    if numbers != expected or characters > policy["max_characters"]:
        raise KernelError(
            "WORKING_PROSE_PROJECTION_INVALID",
            "Working sources require complete ordered version coverage within allocation",
        )
