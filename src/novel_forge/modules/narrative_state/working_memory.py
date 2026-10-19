from copy import deepcopy
import json
import re
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.review.diagnostics import prose_hash as text_hash, validate_location
from novel_forge.modules.story_planning_runtime.domain import canonical_hash

MEMORY_VERSION = "working-observations.v1"
OBSERVATIONS_V2 = "working-observations.v2"
LIFECYCLE_KEYS = {"start", "end", "promise_status", "supersedes"}
PROVIDER_MEMORY_VERSION = "working-observations-provider.v1"
PACKET_V2 = "working-observations-packet.v2"
PROVIDER_PACKET_V2 = "working-observations-provider.v2"
PROVIDER_MEMORY_VERSIONS = {PROVIDER_MEMORY_VERSION, PROVIDER_PACKET_V2}
FROZEN_MEMORY_SOURCE_VERSION = "working-memory-source.v1"
KINDS = {"CHARACTER_STATE", "KNOWLEDGE", "RELATIONSHIP", "EVENT", "CONSEQUENCE", "PROMISE"}
PERSPECTIVES = {"OBSERVED", "BELIEF", "HEARSAY", "READER_ONLY"}
ENTRY_KEYS = {"kind", "subject", "state_key", "claim", "perspective", "knowledge_owner", "quote", "causes"}


def validate_frozen_memory_source(value: Any) -> None:
    if (not isinstance(value, Mapping)
            or set(value) != {"version", "kind", "asset_version_id", "content_hash", "observations_hash"}
            or value["version"] != FROZEN_MEMORY_SOURCE_VERSION
            or not isinstance(value["kind"], str) or value["kind"] not in {"WRITER_SELF_OBSERVATION", "MANUSCRIPT_MEMORY"}
            or any(not isinstance(value[key], str) or not value[key] for key in ("asset_version_id", "content_hash"))
            or not isinstance(value["observations_hash"], str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", value["observations_hash"]) is None):
        raise KernelError("WORKING_MEMORY_SOURCE_INVALID", "Frozen memory requires an exact source version and observation digest")


def normalize_observations(raw: Any, text: str, *, available_causes: set[str] | None = None, version: str = MEMORY_VERSION) -> dict[str, Any]:
    if version not in {MEMORY_VERSION, OBSERVATIONS_V2}:
        raise KernelError("WORKING_MEMORY_VERSION_INVALID", "Unknown observation identity version")
    keys = ENTRY_KEYS | (LIFECYCLE_KEYS if version == OBSERVATIONS_V2 else set())
    if not isinstance(raw, list) or len(raw) > 64:
        raise KernelError("WORKING_MEMORY_INVALID", "Observations require a bounded list")
    entries = []
    for ordinal, entry in enumerate(raw):
        if (not isinstance(entry, Mapping) or set(entry) != keys
                or not isinstance(entry["kind"], str) or entry["kind"] not in KINDS
                or not isinstance(entry["perspective"], str) or entry["perspective"] not in PERSPECTIVES
                or any(not isinstance(entry[k], str) or not entry[k].strip() or len(entry[k]) > limit
                       for k, limit in (("subject", 120), ("state_key", 120), ("claim", 600), ("quote", 2000)))
                or not isinstance(entry["knowledge_owner"], str) or len(entry["knowledge_owner"]) > 120
                or (entry["kind"] == "KNOWLEDGE" or entry["perspective"] in {"BELIEF", "HEARSAY"}) and not entry["knowledge_owner"].strip()
                or entry["perspective"] == "READER_ONLY" and entry["knowledge_owner"]
                or not isinstance(entry["causes"], list) or len(entry["causes"]) > 8
                or any(not isinstance(cause, str) or cause not in (available_causes or set()) for cause in entry["causes"])):
            raise KernelError("WORKING_MEMORY_INVALID", "Observation attribution or causal source is invalid")
        if version == OBSERVATIONS_V2:
            if (not isinstance(entry["promise_status"], str) or entry["promise_status"] not in ({"OPEN", "FULFILLED", "RELEASED", "UNKNOWN"} if entry["kind"] == "PROMISE" else {"NOT_APPLICABLE"})
                    or not isinstance(entry["supersedes"], list) or len(entry["supersedes"]) != len(set(entry["supersedes"]))
                    or any(identity not in (available_causes or set()) for identity in entry["supersedes"])
                    or entry["kind"] != "PROMISE" and entry["supersedes"]
                    or entry["promise_status"] in {"FULFILLED", "RELEASED"} and not entry["supersedes"]):
                raise KernelError("WORKING_MEMORY_LIFECYCLE_INVALID", "Promise closure requires explicit earlier observation identities")
        location = validate_location({"quote": entry["quote"], **({key: entry[key] for key in ("start", "end")} if version == OBSERVATIONS_V2 else {})}, text)
        value = {**deepcopy(dict(entry)), **({key: location[key] for key in ("start", "end")} if version == OBSERVATIONS_V2 else {}), "location": location, "ordinal": ordinal}
        value["observation_id"] = canonical_hash({"text_hash": text_hash(text), **value})
        entries.append(value)
    return {"version": version, "text_hash": text_hash(text), "entries": entries,
            "authority": "UNREVIEWED_WORKING_OBSERVATIONS", "semantic_support": "NOT_VERIFIED"}


def optional_draft_memory(raw: Any, text: str, *, available_causes: set[str] | None = None, version: str = MEMORY_VERSION, prior_observations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if raw is None:
        return {"status": "NOT_REQUESTED"}
    try:
        if not isinstance(raw, str) or len(raw) > 100_000:
            raise KernelError("WORKING_MEMORY_INVALID", "Observation envelope must be bounded JSON text")
        memory = normalize_observations(json.loads(raw), text, available_causes=available_causes, version=version)
        if version == OBSERVATIONS_V2:
            validate_promise_transitions(memory["entries"], prior_observations or [])
        return {"status": "LOCATED_UNREVIEWED", "observations": memory}
    except (KernelError, ValueError, TypeError, KeyError) as error:
        return {"status": "UNAVAILABLE", "error_code": getattr(error, "code", "WORKING_MEMORY_JSON_INVALID"),
                "raw_digest": canonical_hash(raw), "prose_preserved": True}


def validate_observations(memory: Mapping[str, Any], text: str, *, available_causes: set[str] | None = None) -> None:
    if (not isinstance(memory, Mapping) or memory.get("text_hash") != text_hash(text)
            or not isinstance(memory.get("entries"), list)):
        raise KernelError("WORKING_MEMORY_STALE", "Observations belong to another prose version")
    if any(not isinstance(row, Mapping) or not ENTRY_KEYS.issubset(row) for row in memory["entries"]):
        raise KernelError("WORKING_MEMORY_INVALID", "Observation fields are missing")
    version = memory.get("version")
    keys = ENTRY_KEYS | (LIFECYCLE_KEYS if version == OBSERVATIONS_V2 else set())
    rebuilt = normalize_observations([{k: row[k] for k in keys} for row in memory["entries"]], text,
                                     available_causes=available_causes, version=version)
    if dict(memory) != rebuilt:
        raise KernelError("WORKING_MEMORY_INVALID", "Observation identity or located evidence changed")


def validate_promise_transitions(entries, earlier):
    by_id = {row["observation_id"]: row for row in earlier}
    for entry in entries:
        for identity in entry.get("supersedes", []):
            prior = by_id.get(identity)
            if not prior or any(entry[key] != prior[key] for key in ("kind", "subject", "state_key", "perspective", "knowledge_owner")):
                raise KernelError("WORKING_MEMORY_LIFECYCLE_INVALID", "Promise transitions require the same exact attributed earlier promise")


def _task_memory_scope(task: Mapping[str, Any], queries: list[str]) -> tuple[set[str], set[str], list[re.Pattern[str]]]:
    if (not isinstance(task, Mapping) or not isinstance(task.get("scenes", []), list)
            or any(not isinstance(scene, Mapping) for scene in task.get("scenes", []))):
        raise KernelError("WORKING_MEMORY_SELECTION_POLICY_INVALID", "Task scenes require explicit scoped selectors")
    scopes = [task, *task.get("scenes", [])]
    if any(not isinstance(scope.get(key, []), list)
            or any(not isinstance(value, str) for value in scope.get(key, []))
            for scope in scopes for key in ("subjects", "queries", "event_refs", "object_refs", "place_refs")):
        raise KernelError("WORKING_MEMORY_SELECTION_POLICY_INVALID", "Task selectors require explicit string lists")
    subjects = {value.strip().casefold() for scope in scopes for value in scope.get("subjects", []) if value.strip()}
    references = {value.strip() for scope in scopes for key in ("event_refs", "object_refs", "place_refs")
                  for value in scope.get(key, []) if value.strip()}
    terms = {value.strip().casefold() for value in [*queries, *(query for scope in scopes for query in scope.get("queries", []))] if value.strip()} - subjects
    terms.update(value.casefold() for value in references)
    patterns = []
    for term in sorted(terms):
        left = r"(?<![a-z0-9_])" if term[0].isascii() and (term[0].isalnum() or term[0] == "_") else ""
        right = r"(?![a-z0-9_])" if term[-1].isascii() and (term[-1].isalnum() or term[-1] == "_") else ""
        patterns.append(re.compile(left + re.escape(term) + right))
    return subjects, references, patterns


def _task_memory_entry_selected(entry: Mapping[str, Any], *, current: set[str],
                                scope: tuple[set[str], set[str], list[re.Pattern[str]]],
                                selected_ranges: Mapping[str, list[Mapping[str, int]]], closed: set[str],
                                task_related: set[str] | None = None) -> bool:
    subjects, references, patterns = scope
    if entry["observation_id"] in references or any(
            entry["location"]["start"] < selected["end"] and selected["start"] < entry["location"]["end"]
            for selected in selected_ranges.get(entry["source"]["asset_version_id"], [])):
        return True
    related = any(pattern.search(entry[field].casefold()) for pattern in patterns
                  for field in ("claim", "subject", "state_key", "quote"))
    if task_related is not None:
        related = related or entry["observation_id"] in task_related
    participant = bool(subjects.intersection({entry["subject"].strip().casefold(), entry["knowledge_owner"].strip().casefold()}))
    if entry["kind"] in {"CHARACTER_STATE", "KNOWLEDGE", "RELATIONSHIP"}:
        return entry["observation_id"] in current and (related or participant and task_related is None)
    if entry["kind"] == "PROMISE":
        return related or participant and entry["observation_id"] not in closed and entry.get("promise_status") not in {"FULFILLED", "RELEASED"}
    return related


def compile_working_memory(sources: list[dict[str, Any]], *, queries: list[str], max_characters: int | None, dependency_closed: bool = False,
                           recent_complete_from: int | None = None, task: Mapping[str, Any] | None = None,
                           selected_ranges: Mapping[str, list[Mapping[str, int]]] | None = None,
                           frozen_sources: Mapping[str, Mapping[str, Any]] | None = None, lifecycle: bool = False) -> dict[str, Any]:
    if max_characters is None and (not dependency_closed or type(recent_complete_from) is not int):
        raise KernelError("WORKING_MEMORY_SELECTION_POLICY_REQUIRED", "Unallocated retrieval requires scoped latest observations and dependency closure")
    scope = _task_memory_scope(task, queries) if task is not None else None
    if scope is not None:
        if not dependency_closed:
            raise KernelError("WORKING_MEMORY_SELECTION_POLICY_REQUIRED", "Task-selected observations require complete causal sources")
        ranges = selected_ranges if selected_ranges is not None else {}
        by_version = {row["asset_version_id"]: row for row in sources}
        if not isinstance(ranges, Mapping) or any(
                version not in by_version or not isinstance(rows, list)
                or any(not isinstance(row, Mapping) or type(row.get("start")) is not int or type(row.get("end")) is not int
                       or not 0 <= row["start"] < row["end"] <= len(by_version[version]["text"]) for row in rows)
                for version, rows in ranges.items()):
            raise KernelError("WORKING_MEMORY_SELECTION_POLICY_INVALID", "Selected ranges require exact source versions and prose offsets")
    if frozen_sources is not None:
        if scope is None or not isinstance(frozen_sources, Mapping) or set(frozen_sources) != {row["asset_version_id"] for row in sources}:
            raise KernelError("WORKING_MEMORY_SOURCE_INVALID", "Task memory must freeze every candidate source, including omitted observations")
        for source in sources:
            reference = frozen_sources[source["asset_version_id"]]
            validate_frozen_memory_source(reference)
            if reference["observations_hash"] != canonical_hash(source.get("observations")):
                raise KernelError("WORKING_MEMORY_SOURCE_INVALID", "Frozen observations differ from their candidate source digest")
    entries, coverage, known = [], [], set()
    for source in sources:
        memory = source.get("observations")
        status = source.get("memory_provenance", {}).get("status", "MISSING")
        if memory is not None:
            try:
                validate_observations(memory, source["text"], available_causes=known)
                if source.get("dependency_changes"):
                    raise KernelError("WORKING_MEMORY_DEPENDENCY_CHANGED", "Earlier selected sources changed")
                if lifecycle:
                    validate_promise_transitions(memory["entries"], entries)
                for row in memory["entries"]:
                    entries.append({**deepcopy(row), "source": {k: source[k] for k in
                                   ("chapter", "asset_version_id", "content_hash", "text_hash")},
                                    "provenance": deepcopy(source.get("memory_provenance", {}))})
                    known.add(row["observation_id"])
                status = "LOCATED_UNREVIEWED"
            except (KernelError, TypeError, ValueError, KeyError) as error:
                status = getattr(error, "code", "WORKING_MEMORY_INVALID")
        coverage.append({"chapter": source["chapter"], "asset_version_id": source["asset_version_id"], "status": status,
            **({"memory_source": deepcopy(dict(frozen_sources[source["asset_version_id"]]))} if frozen_sources is not None else {})})
    closed, resolutions = set(), {}
    if lifecycle:
        originals = {row["observation_id"]: row for row in entries}
        for row in entries:
            for identity in row.get("supersedes", []):
                prior = originals.get(identity)
                if (not prior or row["source"]["chapter"] <= prior["source"]["chapter"]
                        or any(row[key] != prior[key] for key in ("kind", "subject", "state_key", "perspective", "knowledge_owner"))):
                    raise KernelError("WORKING_MEMORY_LIFECYCLE_INVALID", "A transition must retain the same attributed promise and an earlier source")
                closed.add(identity)
                resolutions.setdefault(identity, []).append(row["observation_id"])
    latest = {}
    for entry in entries:
        if entry["kind"] in {"CHARACTER_STATE", "KNOWLEDGE", "RELATIONSHIP"}:
            latest[(entry["kind"], entry["subject"], entry["state_key"], entry["perspective"], entry["knowledge_owner"])] = entry["observation_id"]
    current = set(latest.values())
    task_selection, task_related = None, None
    if lifecycle and task is not None:
        from novel_forge.modules.book_authority.task_retrieval import select_task_observations
        task_selection = select_task_observations([entry for entry in entries
            if entry["kind"] not in {"CHARACTER_STATE", "KNOWLEDGE", "RELATIONSHIP"}
            or entry["observation_id"] in current], task=task,
            version="working-task-observation-relevance.v2" if task.get("contract_version") == "working-retrieval-task.v4"
                else "working-task-observation-relevance.v1")
        task_related = set(task_selection["selected_ids"])
    ranked = sorted(entries, key=lambda row: (
        -sum(q.casefold() in (row["claim"] + row["subject"] + row["state_key"]).casefold() for q in queries),
        -int(row["observation_id"] in current), -row["source"]["chapter"], row["location"]["start"]))
    selected, omitted, remaining = [], [], max_characters
    for entry in ranked:
        if scope is not None and not _task_memory_entry_selected(entry, current=current, scope=scope, selected_ranges=ranges, closed=closed, task_related=task_related):
            omitted.append(entry["observation_id"])
            continue
        if scope is None and recent_complete_from is not None and not (
                entry["observation_id"] in current or entry["kind"] == "PROMISE"
                or entry["source"]["chapter"] >= recent_complete_from
                or any(q.casefold() in (entry["claim"] + entry["subject"] + entry["state_key"]).casefold() for q in queries)):
            omitted.append(entry["observation_id"])
            continue
        size = len(json.dumps(entry, ensure_ascii=False, sort_keys=True))
        if remaining is None or size <= remaining:
            selected.append({**entry, "state_role": "LATEST_OBSERVATION" if entry["observation_id"] in current else "HISTORICAL_OBSERVATION"})
            if remaining is not None:
                remaining -= size + 80
        else:
            omitted.append(entry["observation_id"])
    if dependency_closed:
        originals = {entry["observation_id"]: entry for entry in entries}
        included = {entry["observation_id"] for entry in selected}
        pending = list(selected)
        while pending:
            entry = pending.pop()
            for cause in [*entry["causes"], *(entry.get("supersedes", []) if lifecycle else []), *(resolutions.get(entry["observation_id"], []) if lifecycle else [])]:
                if cause not in originals:
                    raise KernelError("WORKING_MEMORY_CAUSE_UNAVAILABLE", "A selected observation needs its original source-bound cause")
                if cause not in included:
                    source = originals[cause]
                    restored = {**source, "state_role": "LATEST_OBSERVATION" if cause in current else "HISTORICAL_OBSERVATION"}
                    selected.append(restored)
                    pending.append(restored)
                    included.add(cause)
        omitted = [identity for identity in omitted if identity not in included]
    selected.sort(key=lambda row: (row["source"]["chapter"], row["location"]["start"]))
    packet = {"version": PACKET_V2 if lifecycle else MEMORY_VERSION, "authority": "UNREVIEWED_WORKING_OBSERVATIONS",
              "semantic_support": "NOT_VERIFIED", "entries": selected, "omitted_observation_ids": omitted,
              "source_coverage": coverage, "candidate_count": len(entries)}
    if lifecycle:
        packet["task_selection"] = task_selection
    return {**packet, "packet_hash": canonical_hash(packet)}


def project_memory_for_provider(packet: Mapping[str, Any], visible: set[str]) -> dict[str, Any]:
    result = {key: deepcopy(packet[key]) for key in ("authority", "semantic_support", "entries", "candidate_count")}
    if packet["version"] == PACKET_V2:
        result["task_selection"] = deepcopy(packet["task_selection"])
    result.update(version=PROVIDER_PACKET_V2 if packet["version"] == PACKET_V2 else PROVIDER_MEMORY_VERSION, host_packet_hash=packet["packet_hash"],
        source_coverage=[deepcopy(row) for row in packet["source_coverage"] if row["asset_version_id"] in visible],
        source_coverage_hash=canonical_hash(packet["source_coverage"]))
    for source, target in (("omitted_observation_ids", "omitted_observation"), ("retrieval_omissions", "retrieval_omission")):
        result[target + "_count"] = len(packet[source])
        result[target + "_hash"] = canonical_hash(packet[source])
    return {**result, "packet_hash": canonical_hash(result)}


def _location_covered(location: Mapping[str, Any], passages: list[dict[str, Any]]) -> bool:
    start, end, quote = location.get("start"), location.get("end"), location.get("quote")
    if type(start) is not int or type(end) is not int or not isinstance(quote, str) or end - start != len(quote) or start >= end:
        return False
    cursor = start
    for passage in sorted(passages, key=lambda row: row["start"]):
        left, right = max(start, passage["start"]), min(end, passage["end"])
        if left >= right:
            continue
        if left > cursor and quote[cursor-start:left-start].strip():
            return False
        if passage["text"][left-passage["start"]:right-passage["start"]] != quote[left-start:right-start]:
            return False
        cursor = max(cursor, right)
    return cursor > start and not quote[cursor-start:].strip()


def bind_packet_coverage(packet: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    packet = deepcopy(packet)
    by_version = {row["asset_version_id"]: row for row in sources}
    included, missing = [], list(packet.get("retrieval_omissions", []))
    for entry in packet["entries"]:
        source = by_version[entry["source"]["asset_version_id"]]
        location = entry["location"]
        if _location_covered(location, source["passages"]):
            included.append(entry)
        else:
            missing.append(entry["observation_id"])
    packet["entries"] = included
    packet["retrieval_omissions"] = missing
    packet["packet_hash"] = canonical_hash({k: v for k, v in packet.items() if k != "packet_hash"})
    return packet


def validate_memory_packet(packet: Any, sources: list[dict[str, Any]]) -> None:
    failure = KernelError("WORKING_MEMORY_PACKET_INVALID", "Working memory requires source-bound unreviewed observations")
    provider = isinstance(packet, Mapping) and packet.get("version") in PROVIDER_MEMORY_VERSIONS
    fields = ({"host_packet_hash", "source_coverage_hash", "omitted_observation_count", "omitted_observation_hash",
        "retrieval_omission_count", "retrieval_omission_hash"} if provider else {"omitted_observation_ids", "retrieval_omissions"})
    if isinstance(packet, Mapping) and packet.get("version") in {PACKET_V2, PROVIDER_PACKET_V2}:
        fields |= {"task_selection"}
        selection = packet.get("task_selection")
        if selection is not None and (not isinstance(selection, Mapping) or selection.get("version") not in {"working-task-observation-relevance.v1", "working-task-observation-relevance.v2"}
                or selection.get("selection_hash") != canonical_hash({key: value for key, value in selection.items() if key != "selection_hash"})):
            raise failure
    if (not isinstance(packet, Mapping) or packet.get("version") not in {MEMORY_VERSION, PACKET_V2, *PROVIDER_MEMORY_VERSIONS}
            or packet.get("authority") != "UNREVIEWED_WORKING_OBSERVATIONS"
            or packet.get("semantic_support") != "NOT_VERIFIED"
            or set(packet) != {"version", "authority", "semantic_support", "entries", "source_coverage", "candidate_count", "packet_hash"} | fields
            or packet["packet_hash"] != canonical_hash({k: v for k, v in packet.items() if k != "packet_hash"})
            or not isinstance(packet["entries"], list)
            or type(packet["candidate_count"]) is not int or packet["candidate_count"] < 0
            or not isinstance(packet["source_coverage"], list)):
        raise failure
    if provider:
        if (any(type(packet[key]) is not int or packet[key] < 0 for key in ("omitted_observation_count", "retrieval_omission_count"))
                or any(not isinstance(packet[key], str) or len(packet[key]) != 71 or not packet[key].startswith("sha256:")
                    for key in ("host_packet_hash", "source_coverage_hash", "omitted_observation_hash", "retrieval_omission_hash"))
                or packet["candidate_count"] != len(packet["entries"]) + packet["omitted_observation_count"] + packet["retrieval_omission_count"]):
            raise failure
    elif (any(not isinstance(packet[key], list) for key in ("omitted_observation_ids", "retrieval_omissions"))
            or packet["candidate_count"] != sum(len(packet[key]) for key in ("entries", "omitted_observation_ids", "retrieval_omissions"))):
        raise failure
    by_version = {row["asset_version_id"]: row for row in sources}
    identities = []
    for entry in packet["entries"]:
        if (not isinstance(entry, Mapping) or set(entry) != ENTRY_KEYS | (LIFECYCLE_KEYS if "promise_status" in entry else set()) | {"location", "ordinal", "observation_id", "source", "provenance", "state_role"}
                or not isinstance(entry["source"], Mapping) or entry["source"].get("asset_version_id") not in by_version
                or entry["kind"] not in KINDS or entry["perspective"] not in PERSPECTIVES
                or entry["perspective"] == "READER_ONLY" and entry["knowledge_owner"]
                or (entry["kind"] == "KNOWLEDGE" or entry["perspective"] in {"BELIEF", "HEARSAY"}) and not entry["knowledge_owner"]
                or entry["state_role"] not in {"LATEST_OBSERVATION", "HISTORICAL_OBSERVATION"}):
            raise failure
        source = by_version[entry["source"]["asset_version_id"]]
        if dict(entry["source"]) != {k: source[k] for k in ("chapter", "asset_version_id", "content_hash", "text_hash")}:
            raise failure
        expected = canonical_hash({"text_hash": source["text_hash"], **{k: entry[k] for k in ENTRY_KEYS | (LIFECYCLE_KEYS if "promise_status" in entry else set()) | {"location", "ordinal"}}})
        if entry["observation_id"] != expected:
            raise failure
        location = entry["location"]
        if not isinstance(location, Mapping) or not _location_covered(location, source["passages"]):
            raise failure
        identities.append(entry["observation_id"])
    if len(set(identities)) != len(identities) or not provider and bind_packet_coverage(dict(packet), sources) != dict(packet):
        raise failure
