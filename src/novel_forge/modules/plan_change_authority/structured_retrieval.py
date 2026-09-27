from __future__ import annotations

import json
from typing import Any


IDENTITY_FIELDS = {
    "character_id": "character", "source_id": "character", "target_id": "character",
    "source_character_id": "character", "target_character_id": "character",
    "fact_id": "proposition", "proposition_id": "proposition", "event_id": "event",
    "obligation_id": "obligation", "promise_id": "promise", "relationship_id": "relationship",
    "rule_id": "rule", "world_state_id": "world_state", "resource_id": "resource",
    "ability_id": "ability", "capability_id": "ability", "thread_id": "thread",
}
RECORD_LIMIT = 512
RECORD_CODEPOINTS = 4096


def _records(value, pointer=""):
    pending, records, omitted = [(pointer, value)], [], 0
    visited = 0
    while pending:
        pointer, item = pending.pop()
        visited += 1
        if visited > 8192:
            return records, omitted + len(pending) + 1
        if isinstance(item, dict):
            identities = sorted({IDENTITY_FIELDS[key] + ":" + identity for key, identity in item.items()
                if key in IDENTITY_FIELDS and isinstance(identity, str) and identity})
            if identities:
                quote = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                if len(records) >= RECORD_LIMIT or len(quote) > RECORD_CODEPOINTS:
                    omitted += 1
                else:
                    records.append({"json_pointer": pointer, "references": identities, "value": item, "quote": quote})
            pending.extend((pointer + "/" + key.replace("~", "~0").replace("/", "~1"), child) for key, child in reversed(sorted(item.items())))
        elif isinstance(item, list):
            pending.extend((pointer + "/" + str(index), item[index]) for index in reversed(range(len(item))))
    return records, omitted


def changed_records(changes: list[dict[str, Any]]):
    result, omitted = [], 0
    for change in changes:
        sides = {}
        for side in ("before", "after"):
            sides[side], lost = _records(change[side], "/" + change["field"].replace("~", "~0").replace("/", "~1"))
            omitted += lost
        for side, other in (("before", "after"), ("after", "before")):
            for record in sides[side]:
                if any(record["references"] == peer["references"] and record["value"] == peer["value"] for peer in sides[other]):
                    continue
                if len(result) < RECORD_LIMIT:
                    result.append({**record, "side": side, "changed_field": change["field"]})
                else:
                    omitted += 1
    return result, omitted


def retrieve_structured_matches(plan, changed, *, evidence_limit, digest):
    records, omitted = _records(plan["content"])
    matches, count = [], 0
    for record in records:
        for source in changed:
            shared = sorted(set(record["references"]) & set(source["references"]))
            if not shared:
                continue
            count += 1
            if len(matches) < evidence_limit:
                matches.append({"retrieval_kind": "TYPED_STATE_CHANGE", "source_position": source,
                    "asset_version_id": plan["asset_version_id"], "content_hash": plan["content_hash"],
                    "json_pointer": record["json_pointer"], "value_hash": digest(record["value"]),
                    "quote": record["quote"], "shared_typed_references": shared,
                    "evidence_format": "CANONICAL_JSON_VALUE", "start": 0, "end": len(record["quote"])})
    return matches, {"unscanned_or_oversized_records": omitted, "matching_records_omitted": max(0, count - len(matches))}
