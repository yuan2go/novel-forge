from pathlib import Path

import pytest

from novel_forge.modules.book_authority.derived_cache import DerivedResultCache, task_selection_cache
from novel_forge.modules.book_authority.task_retrieval import select_task_passages
from novel_forge.modules.capability_packs.memory_profiles import build_working_memory_pack_profile
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.working_memory import OBSERVATIONS_V2, compile_working_memory, normalize_observations, validate_observations
from tests.unit.test_working_memory import note, source


def transition(text, **changes):
    return note(quote=text, start=None, end=None, promise_status="OPEN", supersedes=[], **changes)


def test_closed_promise_is_historical_but_retrieval_restores_both_ends():
    opened = note()["quote"]
    first = normalize_observations([transition(opened)], opened, version=OBSERVATIONS_V2)
    identity = first["entries"][0]["observation_id"]
    fulfilled = "Mira repaired the bridge and the mayor released her obligation."
    raw = transition(fulfilled)
    raw.update(promise_status="FULFILLED", supersedes=[identity])
    second = normalize_observations([raw], fulfilled, version=OBSERVATIONS_V2, available_causes={identity})
    rows = [source(1, opened, first), source(2, fulfilled, second)]
    task = {"subjects": ["Mira"], "queries": ["orchard"], "scenes": []}
    options = dict(queries=[], max_characters=None, dependency_closed=True, recent_complete_from=3, task=task)
    assert compile_working_memory(rows, lifecycle=True, **options)["entries"] == []
    task["queries"] = ["bridge"]
    packet = compile_working_memory(rows, lifecycle=True, **options)
    assert {entry["observation_id"] for entry in packet["entries"]} == {identity, second["entries"][0]["observation_id"]}
    assert next(entry for entry in packet["entries"] if entry["observation_id"] == identity)["state_role"] == "HISTORICAL_OBSERVATION"
    validate_observations(first, opened)
    assert compile_working_memory(rows, lifecycle=False, **{**options, "task": {"subjects": ["Mira"]}})["entries"]


def test_promise_closure_requires_prior_source_and_preserves_belief_owner():
    text = "Mira promised to repair the bridge."
    raw = transition(text)
    raw.update(promise_status="FULFILLED")
    with pytest.raises(KernelError, match="earlier"):
        normalize_observations([raw], text, version=OBSERVATIONS_V2)
    raw.update(promise_status="UNKNOWN", perspective="BELIEF", knowledge_owner="Mira")
    value = normalize_observations([raw], text, version=OBSERVATIONS_V2)
    assert value["entries"][0]["knowledge_owner"] == "Mira"
    validate_observations(value, text)
    with pytest.raises(KernelError, match="another prose"):
        validate_observations(value, text + " Changed.")


def test_location_disambiguates_repeated_quote_without_changing_v1_identity():
    text = "She returned. She returned."
    raw = transition("She returned.")
    raw.update(start=14, end=len(text))
    v2 = normalize_observations([raw], text, version=OBSERVATIONS_V2)
    assert v2["entries"][0]["location"]["start"] == 14
    with pytest.raises(KernelError, match="more than once"):
        normalize_observations([note(quote="She returned.")], text)
    validate_observations(v2, text)


def test_rank_cache_reuses_exact_input_and_never_aliases_or_hides_source_drift():
    task_selection_cache.clear()
    units = [(1, 0, 12, "bridge broke"), (2, 0, 13, "orchard grows")]
    task = {"goal": "repair bridge", "target_chapter": 3}
    first = select_task_passages(units, task=task)
    repeated = select_task_passages(units, task=task)
    assert first == repeated and task_selection_cache.hits == 1
    repeated["selected"].clear()
    assert select_task_passages(units, task=task) == first
    changed = select_task_passages([(1, 0, 12, "garden grows"), units[1]], task=task)
    assert changed["source_units_hash"] != first["source_units_hash"]
    with pytest.raises(KernelError, match="range"):
        select_task_passages([(1, 0, 9, "changed")], task=task)


def test_disposable_cache_corruption_eviction_and_rebuild():
    cache = DerivedResultCache(max_bytes=40)
    cache.put("a", {"value": "old"})
    cache._rows["a"] = (b'{}', b'invalid')
    assert cache.get("a") is None
    cache.put("a", {"value": "new"})
    assert cache.get("a") == {"value": "new"}
    cache.put("b", {"value": "x" * 25})
    assert cache.get("a") is None
    cache.clear()
    assert cache.get("b") is None


def test_memory_pack_is_separate_source_bound_and_uses_versioned_schema():
    from novel_forge.modules.production_execution.cost_routing import task_policy
    policy = task_policy("working_memory_extract")
    assert policy.risk == "MEDIUM"
    assert policy.quality_metric == "DOMAIN_GATE_ACCEPTANCE"
    pack = build_working_memory_pack_profile(Path(__file__).resolve().parents[2], operation_definition_hash="sha256:" + "a" * 64)
    node = pack.manifest["workflow_template"]["nodes"][0]
    assert node["operation_name"] == "working_memory_extract"
    assert node["input_asset_types"] == ["working_memory_task"]
    assert pack.manifest["identity"]["version"] == "1.0.0"
    schema = next(row for row in pack.artifact_catalog["artifacts"] if row["ref"] == "schema:working-memory-pack-output:v1")
    assert "supersedes" in schema["content"]["properties"]["observations"]["items"]["properties"]


def test_v2_writer_metadata_and_transport_keep_literal_support_and_scope():
    import json
    from novel_forge.modules.narrative_state.working_memory import (
        PACKET_V2, PROVIDER_PACKET_V2, bind_packet_coverage, optional_draft_memory, project_memory_for_provider, validate_memory_packet,
    )
    text = note()["quote"]
    memory = optional_draft_memory(json.dumps([transition(text)]), text, version=OBSERVATIONS_V2)
    assert memory["status"] == "LOCATED_UNREVIEWED"
    row = source(1, text, memory["observations"])
    packet = compile_working_memory([row], queries=[], max_characters=None, dependency_closed=True,
        recent_complete_from=2, task={"subjects": ["Mira"]}, lifecycle=True)
    assert packet["version"] == PACKET_V2
    row["passages"] = [{"start": 0, "end": len(text), "text": text, "text_hash": row["text_hash"]}]
    packet = bind_packet_coverage(packet, [row])
    validate_memory_packet(packet, [row])
    provider = project_memory_for_provider(packet, {row["asset_version_id"]})
    assert provider["version"] == PROVIDER_PACKET_V2
    validate_memory_packet(provider, [row])
    assert provider["entries"][0]["promise_status"] == "OPEN"
    assert optional_draft_memory('[{}]', text, version=OBSERVATIONS_V2)["prose_preserved"]


def test_backfill_prior_selection_keeps_latest_attribution_and_unbounded_cause_closure():
    from novel_forge.modules.book_authority.memory_prior import select_extraction_prior
    entries = []
    for number in range(15):
        entries.append({**note(kind="EVENT", subject="storm", state_key=f"cause-{number}",
            quote="The wind blew.", causes=[str(number - 1)] if number else []), "observation_id": str(number)})
    entries.append({**note(kind="CHARACTER_STATE", state_key="position", causes=["14"]), "observation_id": "old"})
    entries.append({**note(kind="CHARACTER_STATE", state_key="position", causes=["14"]), "observation_id": "new"})
    selected, receipt = select_extraction_prior(entries, "Mira went into the orchard.")
    assert {row["observation_id"] for row in selected} == {str(number) for number in range(15)} | {"new"}
    assert receipt["omitted_count"] == 1


def test_v10_selects_task_related_state_instead_of_every_state_of_the_same_character():
    texts = ["Mira's old boots were wet.", "Mira knows which end of the timber must face the open path."]
    rows = []
    for index, text in enumerate(texts):
        raw = note(kind="KNOWLEDGE", state_key="boots" if index == 0 else "timber handling",
            claim=text, quote=text, knowledge_owner="Mira")
        rows.append(source(index + 1, text, normalize_observations([raw], text)))
    task = {"subjects": ["Mira"], "queries": ["timber handling open path"], "scenes": []}
    options = dict(queries=[], max_characters=None, dependency_closed=True, recent_complete_from=3, task=task)
    selected = compile_working_memory(rows, lifecycle=True, **options)
    assert [entry["state_key"] for entry in selected["entries"]] == ["timber handling"]
    assert len(compile_working_memory(rows, lifecycle=False, **options)["entries"]) == 2
    assert selected["task_selection"]["query_support"]
