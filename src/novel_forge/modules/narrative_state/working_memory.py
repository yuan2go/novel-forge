from copy import deepcopy
import json
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.review.diagnostics import prose_hash as text_hash, validate_location
from novel_forge.modules.story_planning_runtime.domain import canonical_hash

MEMORY_VERSION = "working-observations.v1"
PROVIDER_MEMORY_VERSION = "working-observations-provider.v1"
KINDS = {"CHARACTER_STATE", "KNOWLEDGE", "RELATIONSHIP", "EVENT", "CONSEQUENCE", "PROMISE"}
PERSPECTIVES = {"OBSERVED", "BELIEF", "HEARSAY", "READER_ONLY"}
ENTRY_KEYS = {"kind", "subject", "state_key", "claim", "perspective", "knowledge_owner", "quote", "causes"}


def normalize_observations(raw: Any, text: str, *, available_causes: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(raw, list) or len(raw) > 64:
        raise KernelError("WORKING_MEMORY_INVALID", "Observations require a bounded list")
    entries = []
    for ordinal, entry in enumerate(raw):
        if (not isinstance(entry, Mapping) or set(entry) != ENTRY_KEYS
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
        location = validate_location({"quote": entry["quote"]}, text)
        value = {**deepcopy(dict(entry)), "location": location, "ordinal": ordinal}
        value["observation_id"] = canonical_hash({"text_hash": text_hash(text), **value})
        entries.append(value)
    return {"version": MEMORY_VERSION, "text_hash": text_hash(text), "entries": entries,
            "authority": "UNREVIEWED_WORKING_OBSERVATIONS", "semantic_support": "NOT_VERIFIED"}


def optional_draft_memory(raw: Any, text: str, *, available_causes: set[str] | None = None) -> dict[str, Any]:
    if raw is None:
        return {"status": "NOT_REQUESTED"}
    try:
        if not isinstance(raw, str) or len(raw) > 100_000:
            raise KernelError("WORKING_MEMORY_INVALID", "Observation envelope must be bounded JSON text")
        memory = normalize_observations(json.loads(raw), text, available_causes=available_causes)
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
    rebuilt = normalize_observations([{k: row[k] for k in ENTRY_KEYS} for row in memory["entries"]], text,
                                     available_causes=available_causes)
    if dict(memory) != rebuilt:
        raise KernelError("WORKING_MEMORY_INVALID", "Observation identity or located evidence changed")


def compile_working_memory(sources: list[dict[str, Any]], *, queries: list[str], max_characters: int, dependency_closed: bool = False) -> dict[str, Any]:
    entries, coverage, known = [], [], set()
    for source in sources:
        memory = source.get("observations")
        status = source.get("memory_provenance", {}).get("status", "MISSING")
        if memory is not None:
            try:
                validate_observations(memory, source["text"], available_causes=known)
                if source.get("dependency_changes"):
                    raise KernelError("WORKING_MEMORY_DEPENDENCY_CHANGED", "Earlier selected sources changed")
                for row in memory["entries"]:
                    entries.append({**deepcopy(row), "source": {k: source[k] for k in
                                   ("chapter", "asset_version_id", "content_hash", "text_hash")},
                                    "provenance": deepcopy(source.get("memory_provenance", {}))})
                    known.add(row["observation_id"])
                status = "LOCATED_UNREVIEWED"
            except (KernelError, TypeError, ValueError, KeyError) as error:
                status = getattr(error, "code", "WORKING_MEMORY_INVALID")
        coverage.append({"chapter": source["chapter"], "asset_version_id": source["asset_version_id"], "status": status})
    latest = {}
    for entry in entries:
        if entry["kind"] in {"CHARACTER_STATE", "KNOWLEDGE", "RELATIONSHIP"}:
            latest[(entry["kind"], entry["subject"], entry["state_key"], entry["perspective"], entry["knowledge_owner"])] = entry["observation_id"]
    current = set(latest.values())
    ranked = sorted(entries, key=lambda row: (
        -sum(q.casefold() in (row["claim"] + row["subject"] + row["state_key"]).casefold() for q in queries),
        -int(row["observation_id"] in current), -row["source"]["chapter"], row["location"]["start"]))
    selected, omitted, remaining = [], [], max_characters
    for entry in ranked:
        size = len(json.dumps(entry, ensure_ascii=False, sort_keys=True))
        if size <= remaining:
            selected.append({**entry, "state_role": "LATEST_OBSERVATION" if entry["observation_id"] in current else "HISTORICAL_OBSERVATION"})
            remaining -= size + 80
        else:
            omitted.append(entry["observation_id"])
    if dependency_closed:
        originals = {entry["observation_id"]: entry for entry in entries}
        included = {entry["observation_id"] for entry in selected}
        pending = list(selected)
        while pending:
            entry = pending.pop()
            for cause in entry["causes"]:
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
    packet = {"version": MEMORY_VERSION, "authority": "UNREVIEWED_WORKING_OBSERVATIONS",
              "semantic_support": "NOT_VERIFIED", "entries": selected, "omitted_observation_ids": omitted,
              "source_coverage": coverage, "candidate_count": len(entries)}
    return {**packet, "packet_hash": canonical_hash(packet)}


def project_memory_for_provider(packet: Mapping[str, Any], visible: set[str]) -> dict[str, Any]:
    result = {key: deepcopy(packet[key]) for key in ("authority", "semantic_support", "entries", "candidate_count")}
    result.update(version=PROVIDER_MEMORY_VERSION, host_packet_hash=packet["packet_hash"],
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
    provider = isinstance(packet, Mapping) and packet.get("version") == PROVIDER_MEMORY_VERSION
    fields = ({"host_packet_hash", "source_coverage_hash", "omitted_observation_count", "omitted_observation_hash",
        "retrieval_omission_count", "retrieval_omission_hash"} if provider else {"omitted_observation_ids", "retrieval_omissions"})
    if (not isinstance(packet, Mapping) or packet.get("version") not in {MEMORY_VERSION, PROVIDER_MEMORY_VERSION}
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
        if (not isinstance(entry, Mapping) or set(entry) != ENTRY_KEYS | {"location", "ordinal", "observation_id", "source", "provenance", "state_role"}
                or not isinstance(entry["source"], Mapping) or entry["source"].get("asset_version_id") not in by_version
                or entry["kind"] not in KINDS or entry["perspective"] not in PERSPECTIVES
                or entry["perspective"] == "READER_ONLY" and entry["knowledge_owner"]
                or (entry["kind"] == "KNOWLEDGE" or entry["perspective"] in {"BELIEF", "HEARSAY"}) and not entry["knowledge_owner"]
                or entry["state_role"] not in {"LATEST_OBSERVATION", "HISTORICAL_OBSERVATION"}):
            raise failure
        source = by_version[entry["source"]["asset_version_id"]]
        if dict(entry["source"]) != {k: source[k] for k in ("chapter", "asset_version_id", "content_hash", "text_hash")}:
            raise failure
        expected = canonical_hash({"text_hash": source["text_hash"], **{k: entry[k] for k in ENTRY_KEYS | {"location", "ordinal"}}})
        if entry["observation_id"] != expected:
            raise failure
        location = entry["location"]
        if not isinstance(location, Mapping) or not _location_covered(location, source["passages"]):
            raise failure
        identities.append(entry["observation_id"])
    if len(set(identities)) != len(identities) or not provider and bind_packet_coverage(dict(packet), sources) != dict(packet):
        raise failure
