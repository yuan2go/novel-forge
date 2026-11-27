from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Any, Mapping, Sequence

from .prose_review import completion_digest, text_digest


RELATION_VERSION = "accepted-state-relations.v2"
_IDENTITIES = {"character_id": "character", "source_id": "character", "target_id": "character", "fact_id": "proposition", "proposition_id": "proposition", "relationship_id": "relationship", "obligation_id": "obligation", "event_id": "event", "world_state_id": "world_state"}


def accepted_relation_evidence(outcome: Mapping[str, Any], draft: Mapping[str, Any], draft_id: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    text = draft["text"]
    events = outcome.get("state_events") or []
    evidence, missing, invalid = [], 0, 0
    for event in events[:256]:
        provenance, located = event.get("provenance") or {}, event.get("evidence") or {}
        span = located.get("span") or {}
        start, end = span.get("start"), span.get("end")
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
            missing += 1
            continue
        permitted = {draft_id, draft.get("selected_source_asset_version_id")}
        if (not provenance.get("accepted_draft_asset_version_id") or provenance["accepted_draft_asset_version_id"] not in permitted
            or located.get("source_revision_asset_version_id") not in permitted
            or located.get("excerpt_digest") != text_digest(text[start:end])):
            invalid += 1
            continue
        payload = event.get("mutation", {}).get("payload", {})
        refs = {_IDENTITIES[key] + ":" + value for key, value in payload.items() if key in _IDENTITIES and isinstance(value, str) and value}
        identity = event.get("identity") or {}
        if identity.get("entity_key"):
            refs.add(event["state_kind"] + ":" + str(identity["entity_key"]))
        refs.update("event:" + ref for ref in event.get("causality", {}).get("cause_refs", []) if isinstance(ref, str) and ref)
        refs.add("event:" + event["event_id"])
        evidence.append({"event_id": event["event_id"], "state_kind": event["state_kind"], "references": sorted(refs), "start": start, "end": end})
    return evidence, {"events": len(events), "indexed": len(evidence), "unlocated": missing, "invalid_location": invalid, "truncated": max(0, len(events) - 256)}


def structured_relation_windows(sources: Sequence[Mapping[str, Any]], records: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    spans, index = [], defaultdict(list)
    omitted = 0
    width = policy["window_codepoints"] // 4
    for source, record in zip(sources, records, strict=True):
        for item in source.get("relation_evidence", []):
            start, end = item["start"], item["end"]
            if end - start > width or width < 1:
                omitted += 1
                continue
            padding = (width - (end - start)) // 2
            left = max(0, start - padding)
            right = min(len(source["text"]), left + width)
            evidence_id = len(spans)
            spans.append({**record, "start": left, "end": right, "text": source["text"][left:right]})
            for ref in item["references"]:
                index[ref].append(evidence_id)
    groups: dict[tuple[int, ...], set[str]] = defaultdict(set)
    excluded_common = 0
    for ref, indexes in sorted(index.items()):
        indexes = list(dict.fromkeys(indexes))
        if len(indexes) > 24:
            excluded_common += 1
            indexes = indexes[:12] + indexes[-12:]
        if len({spans[i]["chapter_number"] for i in indexes}) < 2:
            continue
        for pair in combinations(indexes, 2):
            if spans[pair[0]]["chapter_number"] != spans[pair[1]]["chapter_number"]:
                groups[pair].add(ref)
        for offset in range(0, len(indexes), 3):
            group = tuple(indexes[offset:offset + 4])
            if len(group) >= 3 and len({spans[i]["chapter_number"] for i in group}) >= 2:
                groups[group].add(ref)
    ordered = sorted(groups, key=lambda group: (-len(group), -len(groups[group]), group))
    windows, seen = [], set()
    for group in ordered:
        evidence = []
        for i in group:
            if spans[i] not in evidence:
                evidence.append(spans[i])
        digest = completion_digest(evidence)
        if digest in seen:
            continue
        seen.add(digest)
        hypothesis = {"schema_version": "prose-relation-hypothesis.v2", "basis": "ACCEPTED_STATE_IDENTITIES_AND_CAUSES", "anchors": sorted(groups[group]),
            "status": "UNVERIFIED", "confidence": None, "uncertainty": "Shared accepted entities, knowledge, relationships or commitments retrieve candidates; causality and contradictions require located review of every passage.", "hard_dependency_created": False}
        hypothesis["hypothesis_id"] = completion_digest({"evidence": evidence, "hypothesis": hypothesis})
        body = {"spans": evidence, "policy": dict(policy), "relation_hypothesis": hypothesis}
        windows.append({"window_id": completion_digest(body), **{key: value for key, value in body.items() if key != "policy"}})
        if len(windows) >= policy["relation_window_limit"]:
            break
    return windows, {"status": "BOUNDED_ACCEPTED_STATE_RETRIEVAL", "candidate_groups": len(ordered), "selected_groups": len(windows),
        "unreviewed_candidate_groups": max(0, len(ordered) - len(windows)), "oversized_evidence_spans": omitted, "truncated_frequent_identities": excluded_common,
        "source_coverage": [source.get("relation_evidence_coverage", {}) for source in sources],
        "uncovered_relation_classes": ["UNINDEXED_PARAPHRASE", "UNEXTRACTED_EVENTS", "MORE_THAN_FOUR_PASSAGES", "TRUNCATED_IDENTITY_OCCURRENCES"], "global_relationships_verified": False}
