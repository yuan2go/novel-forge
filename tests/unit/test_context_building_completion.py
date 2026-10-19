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


def test_new_request_snapshot_keeps_complete_envelope_and_checks_effect_identity():
    from novel_forge.modules.chapter_authority.request_snapshot import (
        freeze_provider_request, request_snapshot_required, validate_provider_request_snapshot,
    )
    from novel_forge.modules.production_execution.provider_admission import ProviderRequestEnvelope
    from novel_forge.modules.story_planning_runtime.domain import canonical_hash
    envelope = ProviderRequestEnvelope(provider="codex-cli", model="gpt-test", protocol="codex-cli-application-stdin-v1",
        input_text="Exact source and frozen task.\nNo current preview substitution.", max_output_tokens=2000,
        timeout_seconds=180, stable_idempotency_key="frozen-effect")
    snapshot = freeze_provider_request(envelope)
    assert validate_provider_request_snapshot(snapshot, identity=envelope.to_identity_dict(), envelope_hash=envelope.envelope_hash) == envelope
    assert request_snapshot_required("working_memory_extract", {})
    assert request_snapshot_required("draft", {"nested": [{"projection_policy": {"version": "working-prose-projection.v10"}}]})
    assert not request_snapshot_required("draft", {"projection_policy": {"version": "working-prose-projection.v9"}})
    snapshot["envelope"]["input_text"] += " Changed."
    snapshot["snapshot_hash"] = canonical_hash({key: value for key, value in snapshot.items() if key != "snapshot_hash"})
    with pytest.raises(ValueError, match="IDENTITY_DRIFT"):
        validate_provider_request_snapshot(snapshot, identity=envelope.to_identity_dict(), envelope_hash=envelope.envelope_hash)


def test_native_event_locators_recover_changed_wording_without_realizing_future_plans():
    from types import SimpleNamespace
    from novel_forge.modules.book_authority.source_locators import freeze_source_locators
    from novel_forge.modules.book_authority.working_selection import select_working_context
    from novel_forge.modules.story_planning_runtime.domain import canonical_hash
    book = {"project_id": "project:test", "book_id": "book:test"}
    plans, documents, rows = {}, [], []
    texts = ["She crossed out a guess. The fragment's use stayed unclear.",
        "Mira's old boots were damp, and the lamp was still broken.", "They closed the gate."]
    for number, text in enumerate(texts, 1):
        content = {**book, "chapter": number, "scene_plan": [{"realization_event_ids": ["opaque:lesson" if number == 1 else "opaque:other"]}],
            "narrative_realization_slice": {"events": [{"next_event_ids": ["opaque:future"]}]}}
        plan = SimpleNamespace(asset_type="chapter_plan", asset_version_id=f"plan:{number}", content=content, content_hash=canonical_hash(content))
        plans[plan.asset_version_id] = plan
        draft = {"chapter": number, "text": text, "creative_baseline": {"source_plan": {"asset_version_id": plan.asset_version_id, "content_hash": plan.content_hash}}}
        document = SimpleNamespace(asset_type="chapter_draft", asset_version_id=f"draft:{number}", content=draft, content_hash=canonical_hash(draft))
        documents.append((number, document))
        rows.append({**source(number, text), "content_hash": document.content_hash})
    repository = SimpleNamespace(require=lambda **kw: plans[kw["asset_version_id"]])
    uow = SimpleNamespace(repositories=SimpleNamespace(asset_documents=repository))
    index = freeze_source_locators(uow, book, documents)
    task = {"goal": "Respect the earlier instruction", "event_refs": ["opaque:lesson"], "scenes": [], "target_chapter": 4}
    task["task_hash"] = canonical_hash(task)
    from novel_forge.modules.book_authority.working_prose import working_prose_policy
    policy = working_prose_policy({"working_prose_policy": {"version": "working-prose-projection.v10", "history_chapters": 10000,
        "recent_complete_chapters": 0, "recent_tail_paragraphs": 1, "retrieval_passages": 12, "retrieval_per_chapter": 3,
        "neighbor_paragraphs": 0, "passage_characters": 512, "max_characters": None, "queries": [], "guidance_mode": "COMBINED"}})
    result = select_working_context(rows, target_chapter=4, policy=policy, task=task, source_locators=index)
    assert result["contract_version"] == "working-task-selection.v3"
    assert result["source_locator_receipt"]["version"] == "working-source-locators.v2"
    assert [entry["chapter"] for entry in result["source_locator_receipt"]["selected"]] == [1]
    assert not any(entry["chapter"] == 2 for entry in result["passages"])
    assert {entry["chapter"] for entry in result["passages"] if "TASK_SOURCE_LOCATOR" in entry["reasons"]} == {1}
    future = {**task, "event_refs": ["opaque:future"]}
    future["task_hash"] = canonical_hash({key: value for key, value in future.items() if key != "task_hash"})
    assert select_working_context(rows, target_chapter=4, policy=policy, task=future, source_locators=index)["source_locator_receipt"]["selected"] == []
    plans["plan:1"].content = {**plans["plan:1"].content, "chapter": 9}
    with pytest.raises(KernelError, match="historical generation plan"):
        freeze_source_locators(uow, book, documents)


def test_literal_chapter_locators_support_ordinals_and_exclude_current_or_future_sources():
    from novel_forge.modules.book_authority.source_locators import explicit_chapters
    task = {"goal": "参照第十四章、第二十至二十二章与 Chapters 9-10。第100章尚未发生。", "scenes": []}
    assert explicit_chapters(task, 22) == {9, 10, 14, 20, 21}


@pytest.mark.parametrize('complete_snapshot', [False, True])
def test_request_readback_retains_root_working_snapshot_beside_each_provider_envelope(monkeypatch, complete_snapshot):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from novel_forge.modules.book_authority import memory_readback
    from novel_forge.modules.chapter_authority.request_snapshot import freeze_provider_request
    from novel_forge.modules.production_execution.provider_admission import ProviderRequestEnvelope
    from novel_forge.modules.story_planning_runtime.domain import canonical_hash
    working = dict(version='working-manuscript-context.v2', book_run_id='run', retrieval_task={'task_hash': 'frozen-task'})
    working['snapshot_hash'] = canonical_hash(working)
    envelope = ProviderRequestEnvelope(provider='codex-cli', model='test', protocol='codex-cli-application-stdin-v1',
        input_text='Frozen Writer task and original prose.', max_output_tokens=2000, timeout_seconds=180, stable_idempotency_key='effect')
    contract = dict(provider_request_identity=envelope.to_identity_dict())
    if complete_snapshot:
        contract['provider_request_snapshot'] = freeze_provider_request(envelope)
    content = {'contract': contract}
    document = SimpleNamespace(content=content, content_hash=canonical_hash(content))
    capability = dict(provider_admission_asset_version_id='admission', provider_admission_content_hash=document.content_hash,
        provider_request_envelope_hash=envelope.envelope_hash)
    uow = MagicMock()
    uow.cursor.fetchone.return_value = ({'chapter_root_operation_id': 'root'}, {'preparation_report': {'working_manuscript': working}}, [])
    uow.cursor.fetchall.side_effect = [[('effect', 'operation', 'SUCCEEDED', {'_production_execution': {'capability_runtime': capability}}, [], [])], []]
    uow.repositories.asset_documents.require.return_value = document
    factory = MagicMock()
    factory.return_value.__enter__.return_value = uow
    monkeypatch.setattr(memory_readback, 'AuthorityUnitOfWork', factory)
    result = memory_readback.request_memory('postgresql://unit', project_id='project', book_run_id='run', chapter_request_id='request', principal=MagicMock())
    assert result['working_manuscript'] == working
    effect = result['writer_effects'][0]
    assert effect['provider_admission']['content'] == contract
    assert effect['input_snapshot_status'] == ('FROZEN_APPLICATION_REQUEST' if complete_snapshot else 'LEGACY_HASH_ONLY')


def test_current_planning_task_binds_volume_segment_cast_mentions_and_matching_arc_without_future_facts():
    from novel_forge.modules.book_authority.working_task import build_working_task, validate_working_task
    from novel_forge.modules.story_planning_runtime.domain import canonical_hash
    book = dict(project_id='project', workspace_id='workspace', book_id='book', book_run_id='run', input_snapshot_id='input')
    def bound(kind, identity, value):
        content = {**{key: book[key] for key in ('project_id', 'book_id')}, **value}
        return dict(asset_type=kind, asset_version_id=identity, content_hash=canonical_hash(content), content=content)
    volume = bound('volume_plan', 'volume', {'chapter_range': [1, 100], 'narrative_segments': [
        {'segment_id': 'learning', 'chapter_range': [13, 22], 'objective': 'Mira chooses a limited lesson after paying the agreed fee.'},
        {'segment_id': 'later', 'chapter_range': [23, 40], 'objective': 'Mirabelle discovers an unrelated future island.'}]})
    arc = bound('arc_plan', 'arc', {'arc_segments': [
        {'volume_plan_version_id': 'volume', 'narrative_segment_id': 'learning', 'objective': 'Respect the original labour boundary.'},
        {'volume_plan_version_id': 'volume', 'narrative_segment_id': 'later', 'objective': 'Assume the future island has already been found.'}]})
    cast = bound('character_cast', 'cast', {'characters': [
        {'character_id': 'actor:mira', 'name': 'Mira', 'aliases': []},
        {'character_id': 'actor:mirabelle', 'name': 'Mirabelle', 'aliases': []}]})
    task = build_working_task(sources=[arc, volume, cast], book=book, chapter=21, stage='PLANNING', version='working-retrieval-task.v2')
    assert task['handoff_predecessor'] == 20
    assert 'limited lesson' in task['goal'] and 'labour boundary' in task['goal']
    assert 'island' not in task['goal'] and task['subjects'] == ['Mira', 'actor:mira']
    assert any(row['asset_version_id'] == 'volume' and row['pointer'] == '/narrative_segments/0/objective' for row in task['field_sources'])
    validate_working_task(task, book=book, chapter=21, stage='PLANNING', sources=[arc, volume, cast])
    old = build_working_task(sources=[arc, cast], book=book, chapter=21, stage='PLANNING')
    assert old['goal'] == '' and old['subjects'] == [] and 'handoff_predecessor' not in old
    validate_working_task(old, book=book, chapter=21, stage='PLANNING', sources=[arc, cast])
    volume['content']['narrative_segments'][0]['objective'] = 'Changed source'
    with pytest.raises(KernelError, match='frozen digest'):
        build_working_task(sources=[arc, volume, cast], book=book, chapter=21, stage='PLANNING', version='working-retrieval-task.v2')


def test_current_handoff_keeps_the_complete_predecessor_and_legacy_locator_replays_original_scope():
    from novel_forge.modules.book_authority.source_locators import source_locator_receipt, BOUNDARY
    from novel_forge.modules.book_authority.working_selection import select_working_context
    from novel_forge.modules.book_authority.working_prose import working_prose_policy
    from novel_forge.modules.story_planning_runtime.domain import canonical_hash
    rows = [source(1, 'An unrelated walk.'), source(2, 'The mistaken guess.\n' + 'Necessary original action. ' * 40 + '\nThe correction and consequence.')]
    entries = [{**{key: row[key] for key in ('chapter', 'asset_version_id', 'content_hash', 'text_hash')},
        'plan': None, 'event_refs': [], 'status': 'SOURCE_PLAN_UNAVAILABLE'} for row in rows]
    def index(version):
        body = dict(version=version, boundary=BOUNDARY, entries=entries)
        return {**body, 'index_hash': canonical_hash(body)}
    task = dict(goal='Current native task', scenes=[], handoff_predecessor=2)
    current = source_locator_receipt(index('working-source-locators.v2'), task, 3)
    assert [row['chapter'] for row in current['selected']] == [2]
    assert current['selected'][0]['predecessor_handoff'] is True
    assert current['selected'][0]['explicit_chapter_reference'] is False
    assert source_locator_receipt(index('working-source-locators.v1'), task, 3)['selected'] == []
    task['task_hash'] = canonical_hash(task)
    policy = working_prose_policy({'working_prose_policy': {'version': 'working-prose-projection.v10', 'history_chapters': 10000,
        'recent_complete_chapters': 0, 'recent_tail_paragraphs': 1, 'retrieval_passages': 12, 'retrieval_per_chapter': 3,
        'neighbor_paragraphs': 0, 'passage_characters': 512, 'max_characters': None, 'queries': [], 'guidance_mode': 'COMBINED'}})
    selection = select_working_context(rows, target_chapter=3, policy=policy, task=task, source_locators=index('working-source-locators.v2'))
    spans = [(row['start'], row['end']) for row in selection['passages'] if row['chapter'] == 2]
    assert spans[0][0] == 0 and spans[-1][1] == len(rows[1]['text'])
    assert all(left[1] == right[0] for left, right in zip(spans, spans[1:]))


@pytest.mark.parametrize('stage', ['chapter_group_plan.generate', 'chapter_plan.generate', 'draft', 'context_compress', 'working_memory_extract'])
@pytest.mark.parametrize('policy', ['working-prose-projection.v9', 'working-prose-projection.v10'])
def test_shared_admission_snapshot_uses_frozen_inputs_and_context_across_native_owners(stage, policy):
    from novel_forge.modules.chapter_authority.request_snapshot import admission_with_request_snapshot, validate_provider_request_snapshot
    from novel_forge.modules.production_execution.provider_admission import ProviderRequestEnvelope
    envelope = ProviderRequestEnvelope(provider='codex-cli', model='test', protocol='codex-cli-application-stdin-v1',
        input_text='Complete actual application input.', max_output_tokens=2000, timeout_seconds=180, stable_idempotency_key='effect')
    original = {'schema_version': 'novelos.provider_request_admission.v1', 'provider_request_identity': envelope.to_identity_dict()}
    contract = admission_with_request_snapshot(original, stage=stage, frozen_inputs={'rendering_capture': {}},
        frozen_context={'arc_working_set': {'working_manuscript': {'projection_policy': {'version': policy}}}}, envelope=envelope)
    assert original['schema_version'] == 'novelos.provider_request_admission.v1' and 'provider_request_snapshot' not in original
    if policy.endswith('.v10') or stage == 'working_memory_extract':
        assert contract['schema_version'] == 'novelos.provider_request_admission.v2'
        actual = validate_provider_request_snapshot(contract['provider_request_snapshot'], identity=contract['provider_request_identity'], envelope_hash=envelope.envelope_hash)
        assert actual.input_text == envelope.input_text
    else:
        assert contract == original


def test_delivery_contract_requires_full_snapshot_without_reinterpreting_frozen_task2():
    from novel_forge.modules.book_authority.working_task import build_working_task, validate_working_task
    from novel_forge.modules.chapter_authority.request_snapshot import request_snapshot_required
    from novel_forge.modules.story_planning_runtime.domain import canonical_hash
    book = dict(project_id='project', book_id='book', book_run_id='run')
    content = dict(project_id='project', book_id='book', chapter=3, chapter_intent='Continue the previous action.')
    sources = [dict(asset_type='chapter_plan', asset_version_id='plan', content_hash=canonical_hash(content), content=content)]
    old = build_working_task(sources=sources, book=book, chapter=3, stage='CHAPTER', version='working-retrieval-task.v2')
    current = build_working_task(sources=sources, book=book, chapter=3, stage='CHAPTER', version='working-retrieval-task.v3')
    assert 'delivery_contract' not in old
    assert current['delivery_contract'] == 'source-bound-full-provider-request.v1'
    assert current['task_hash'] != old['task_hash']
    assert {key: value for key, value in current.items() if key not in {'contract_version', 'delivery_contract', 'task_hash'}} == {
        key: value for key, value in old.items() if key not in {'contract_version', 'task_hash'}}
    validate_working_task(old, book=book, chapter=3, stage='CHAPTER', sources=sources)
    validate_working_task(current, book=book, chapter=3, stage='CHAPTER', sources=sources)
    assert request_snapshot_required('draft', {'frozen_task': current})
    assert not request_snapshot_required('draft', {'frozen_task': old})
