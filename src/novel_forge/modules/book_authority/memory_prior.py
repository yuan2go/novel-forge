from novel_forge.modules.story_planning_runtime.domain import canonical_hash
from novel_forge.modules.review.diagnostics import prose_hash


def select_extraction_prior(entries, text):
    latest, closed, resolutions = {}, set(), {}
    by_id = {entry["observation_id"]: entry for entry in entries}
    for entry in entries:
        if entry["kind"] in {"CHARACTER_STATE", "KNOWLEDGE", "RELATIONSHIP"}:
            latest[tuple(entry[key] for key in ("kind", "subject", "state_key", "perspective", "knowledge_owner"))] = entry["observation_id"]
        for identity in entry.get("supersedes", []):
            closed.add(identity)
            resolutions.setdefault(identity, []).append(entry["observation_id"])
    current = set(latest.values())
    selected = set()
    for entry in entries:
        identity = entry["observation_id"]
        participant = any(entry[key] and entry[key] in text for key in ("subject", "knowledge_owner"))
        explicit = entry["state_key"] in text or entry["quote"] in text
        if (explicit or participant and (identity in current or entry["kind"] == "PROMISE"
                and identity not in closed and entry.get("promise_status") not in {"FULFILLED", "RELEASED"})):
            selected.add(identity)
    pending = list(selected)
    while pending:
        identity = pending.pop()
        entry = by_id[identity]
        for dependency in [*entry["causes"], *entry.get("supersedes", []), *resolutions.get(identity, [])]:
            if dependency in by_id and dependency not in selected:
                selected.add(dependency)
                pending.append(dependency)
    observations = [entry for entry in entries if entry["observation_id"] in selected]
    omitted = [entry["observation_id"] for entry in entries if entry["observation_id"] not in selected]
    receipt = {"version": "working-memory-prior-state.v1", "input_hash": canonical_hash(entries),
        "target_text_hash": prose_hash(text), "candidate_count": len(entries),
        "selected_ids": [entry["observation_id"] for entry in observations],
        "omitted_count": len(omitted), "omitted_ids_hash": canonical_hash(omitted), "semantic_completeness": "NOT_ESTABLISHED"}
    return observations, {**receipt, "selection_hash": canonical_hash(receipt)}
