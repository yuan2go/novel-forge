import json
from dataclasses import replace

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.context_contracts import ContextCandidate
from novel_forge.modules.context_builder import semantic_units as semantic
from novel_forge.modules.context_builder.task_compression import compile_task_context


def candidate(text, **values):
    return ContextCandidate(asset_version_id="history:a", asset_type="historical_expression_projection", project_id="p",
        estimated_tokens=1, relevance_score=1, safe_summary=text, **values)


@pytest.mark.parametrize("newline", ["\n\n", "\r\n\r\n"])
def test_quote_locates_original_unicode_ranges_before_splitting(newline):
    original = candidate("引子。" + newline + "🜁门不认姓名。" + newline + "若潮声停了，切勿推门。" + newline + "尾声。")
    units = semantic.source_units(original, {})
    proof = semantic.protect_quotes([original], {original.asset_version_id: units}, ["🜁门不认姓名。\n\n若潮声停了，切勿推门。"])
    keep = {unit["unit_id"] for unit in units if unit["required"]}
    assert keep == {"text:1", "text:2"}
    result = semantic.reconstruct(original, units, keep)
    assert "🜁门不认姓名。" + newline + "若潮声停了，切勿推门。" in result["safe_summary"]
    assert proof[0]["coordinates"] == "UNICODE_CODEPOINTS_ORIGINAL_NEWLINES"


def test_cross_scene_quote_and_attribution_survive_projection_and_exact_restoration():
    source = {"status": "SELECTED_WORKING_NOT_ACCEPTED", "scenes": [
        {"subject": "阿岚", "time": "初九", "perspective": "HEARSAY", "knowledge_owner": "阿岚", "text": "她听说守闸人离城了。"},
        {"subject": "读者", "perspective": "READER_ONLY", "text": "守闸人其实在夹层里。"}]}
    original = candidate(json.dumps(source, ensure_ascii=False, indent=2))
    units = semantic.source_units(original, {})
    semantic.protect_quotes([original], {original.asset_version_id: units}, ["她听说守闸人离城了。\n\n守闸人其实在夹层里。"])
    text_units = [unit for unit in units if unit.get("source_span")]
    assert all(unit["required"] for unit in text_units)
    assert text_units[0]["attribution"]["knowledge_owner"] == "阿岚"
    assert text_units[1]["attribution"]["perspective"] == "READER_ONLY"
    assert semantic.reconstruct(original, units, {unit["unit_id"] for unit in units})["safe_summary"] == original.safe_summary


def test_missing_quote_is_not_satisfied_by_the_instruction_copy_and_duplicates_are_exposed():
    original = candidate(json.dumps({"preserve_quotes": ["不存在的经历"], "text": "实有原文。"}, ensure_ascii=False))
    units = semantic.source_units(original, {})
    with pytest.raises(KernelError, match="TASK_CONTEXT_PRESERVE_QUOTE_UNAVAILABLE"):
        semantic.protect_quotes([original], {original.asset_version_id: units}, ["不存在的经历"])
    original = candidate("同一句。\n\n同一句。")
    units = semantic.source_units(original, {})
    receipts = semantic.protect_quotes([original], {original.asset_version_id: units}, ["同一句。"])
    assert receipts[0]["resolution"] == "ALL_EXACT_MATCHES_PROTECTED"
    assert all(unit["required"] for unit in units)


def test_a_short_quote_does_not_lock_an_entire_oversized_history_paragraph():
    quote = "只有潮尺低于二尺才可开闸。"
    original = candidate("街市闲谈。" * 5000 + quote + "日常杂事。" * 5000)
    units = semantic.source_units(original, {})
    semantic.protect_quotes([original], {original.asset_version_id: units}, [quote])
    assert len(units) == 3
    required = [unit for unit in units if unit["required"]]
    assert [unit["text"] for unit in required] == [quote]
    assert quote in semantic.reconstruct(original, units, {unit["unit_id"] for unit in required})["safe_summary"]


def test_same_source_different_fragments_remain_and_only_exact_duplicates_are_removed():
    first = candidate("先接过钥匙。", source_identity="same", source_revision="v1", content_digest="source")
    different = replace(first, asset_version_id="history:b", safe_summary="后来归还钥匙。")
    same = replace(first, asset_version_id="history:c")
    selected, receipts = semantic.exact_deduplicate([first, different, same])
    assert selected == [first, different]
    assert len(receipts) == 1 and receipts[0]["asset_version_id"] == same.asset_version_id


def test_partial_source_overlap_requires_exact_version_scope_and_reconstructs_both_members():
    import hashlib
    def fragment(identity, text, start, end, revision="v1"):
        return replace(candidate(text, source_identity="source", source_revision=revision, content_digest="whole-source"),
            asset_version_id=identity, provenance={"source_range": {"field_path": ["text"], "start": start, "end": end,
                "text_hash": "sha256:" + hashlib.sha256(text.encode()).hexdigest()}})
    first, second = fragment("a", "甲乙丙丁", 0, 4), fragment("b", "丙丁戊己", 2, 6)
    selected, receipts = semantic.exact_deduplicate([second, first])
    assert len(selected) == 1 and selected[0].safe_summary == "甲乙丙丁戊己"
    assert receipts[0]["reason"] == "VERIFIED_ORIGINAL_RANGE_UNION"
    assert len(semantic.exact_deduplicate([first, replace(second, source_revision="v2")])[0]) == 2
    changed = fragment("c", "坏丁戊己", 2, 6)
    with pytest.raises(KernelError, match="SOURCE_RANGE_AMBIGUOUS"):
        semantic.exact_deduplicate([first, changed])


def test_explicit_dependencies_close_without_resolving_contradictory_attribution():
    units = [{"unit_id": "condition", "source_aliases": ["cause:a"], "explicit_refs": []},
        {"unit_id": "contradictory", "source_aliases": ["cause:a"], "explicit_refs": []},
        {"unit_id": "result", "explicit_refs": ["cause:a"]}]
    assert semantic.close_dependencies(units, {"result"}) == {"condition", "contradictory", "result"}
    with pytest.raises(KernelError, match="TASK_CONTEXT_DEPENDENCY_UNAVAILABLE"):
        semantic.close_dependencies([{**units[-1], "explicit_refs": ["missing"]}], {"result"})


def test_catalog_dependency_closure_reaches_another_original_source():
    catalogs = {"earlier": [{"unit_id": "before", "source_aliases": ["cause"], "explicit_refs": [], "required": False}],
        "later": [{"unit_id": "after", "source_aliases": ["effect"], "explicit_refs": ["cause"], "required": True}]}
    aliases = semantic.close_catalog_dependencies(catalogs)
    assert aliases == {"cause", "effect"} and catalogs["earlier"][0]["required"]


def test_new_working_memory_preparation_restores_original_causal_observation_and_keeps_legacy_selection():
    from novel_forge.modules.narrative_state.working_memory import compile_working_memory, normalize_observations
    first_text, second_text = "潮尺还在二尺，许可尚未生效。", "后果：她因此没有开闸。"
    def entry(text, causes):
        return {"kind": "EVENT", "subject": "阿岚", "state_key": text, "claim": text, "perspective": "OBSERVED", "knowledge_owner": "", "quote": text, "causes": causes}
    first = normalize_observations([entry(first_text, [])], first_text)
    cause = first["entries"][0]["observation_id"]
    second = normalize_observations([entry(second_text, [cause])], second_text, available_causes={cause})
    rows = [{"chapter": index + 1, "asset_version_id": f"source:{index}", "content_hash": f"hash:{index}", "text_hash": memory["text_hash"],
        "text": text, "observations": memory, "memory_provenance": {"status": "LOCATED_UNREVIEWED"}}
        for index, (text, memory) in enumerate(((first_text, first), (second_text, second)))]
    legacy = compile_working_memory(rows, queries=["后果"], max_characters=850)
    current = compile_working_memory(rows, queries=["后果"], max_characters=850, dependency_closed=True)
    assert [row["observation_id"] for row in legacy["entries"]] == [second["entries"][0]["observation_id"]]
    assert {row["observation_id"] for row in current["entries"]} == {cause, second["entries"][0]["observation_id"]}
    assert current["authority"] == "UNREVIEWED_WORKING_OBSERVATIONS" and current["semantic_support"] == "NOT_VERIFIED"


def test_working_observation_quote_cannot_satisfy_its_own_missing_source():
    from novel_forge.modules.context_builder.request_capacity import protected_expression_quotes, validate_projection_quotes
    data = {"working_memory": {"version": "working-observations-provider.v1", "authority": "UNREVIEWED_WORKING_OBSERVATIONS",
        "entries": [{"quote": "必要的原文", "location": {"quote": "必要的原文", "start": 0, "end": 5}, "source": {"asset_version_id": "source"}}]},
        "sources": [{"asset_version_id": "source", "safe_summary": "实际来源没有这句话。"}]}
    quotes = protected_expression_quotes(data, include_working_observations=True)
    assert quotes == ("必要的原文",) and protected_expression_quotes(data) == ()
    with pytest.raises(KernelError, match="PRESERVE_QUOTE_UNAVAILABLE"):
        validate_projection_quotes(data, quotes)


def test_nonconsecutive_excerpts_keep_json_structure_and_restore_the_actual_original():
    original = candidate(json.dumps({"subject": "甲", "time": "初八", "summary": "开头。\n\n中间未携带。\n\n结尾。"}, ensure_ascii=False, indent=2))
    units = semantic.source_units(original, {})
    keep = {unit["unit_id"] for unit in units if unit["required"] or unit["text"] in {"开头。", "结尾。"}}
    content = semantic.reconstruct(original, units, keep)
    rebuilt = json.loads(content["safe_summary"])
    assert rebuilt["subject"] == "甲" and rebuilt["time"] == "初八"
    assert "省略原来源片段" in rebuilt["summary"] and "中间未携带" not in rebuilt["summary"]
    assert semantic.reconstruct(original, units, {unit["unit_id"] for unit in units})["safe_summary"] == original.safe_summary


def test_final_composition_checker_restores_a_condition_from_original_neighbors():
    original = candidate("条件是潮尺低于二尺。\n\n于是她开闸。\n\n闲话。")
    units = semantic.source_units(original, {})
    calls = []
    def call(stage, task):
        calls.append(task)
        selected = task["selected_unit_ids"]
        return {"supported": True, "coverage_complete": True, "missing_unit_ids": [] if "text:0" in selected else ["text:0"], "distorted_unit_ids": []}
    keep, proof, _ = semantic.verify_final_selection(original, units, {"text:1"}, payload=lambda group: {"units": group}, fits=lambda _: True, model_call=call)
    assert keep == {"text:0", "text:1"}
    assert proof["result_content_hash"] == semantic.narrative_hash(semantic.reconstruct(original, units, keep))
    assert calls and all(task["composition_check"]["phase"] == "FINAL_COMPOSED_EXTRACT" for task in calls)


def test_oversized_units_split_only_at_sentences_and_preserve_quote_spans():
    original = candidate("甲走近。乙没有开闸。条件尚未成立。后来退回。")
    unit = semantic.source_units(original, {})[0]
    fragments = semantic.split_oversized_unit(unit, lambda group: len(group[0]["text"]) <= 11)
    assert "".join(fragment["text"] for fragment in fragments) == original.safe_summary
    assert all(fragment["text"][-1] == "。" for fragment in fragments)
    with pytest.raises(KernelError, match="TASK_CONTEXT_CAUSAL_UNIT_TOO_LARGE"):
        semantic.split_oversized_unit({**unit, "text": "没有任何安全分界的超大句子", "source_span": [0, 15]}, lambda _: False)


def test_capacity_fast_path_preserves_original_and_runs_no_model_but_validates_quotes():
    boundary = {"kind": "FROZEN_STAGE_INPUTS", "project_id": "p", "book_id": "b", "sources": [{"asset_version_id": "source", "content_hash": "hash"}]}
    original = candidate("主体：阿岚。\n\n她没有开闸。", provenance={"frozen_input_boundary": boundary})
    task = {"stage": "draft", "semantic_contract": semantic.SEMANTIC_CONTRACT, "frozen_input_boundary": boundary, "source_projection_hash": "hash", "preserve_quotes": ["阿岚。\n\n她没有开闸。"]}
    selected, receipt = compile_task_context([original], task=task, token_budget=512000, required_asset_types=(),
        model_call=lambda *_: pytest.fail("a fitting request must not call the compressor"))
    assert selected[0].safe_summary == original.safe_summary and receipt["fast_path"]
    assert receipt["quote_locations"]


def semantic_preparation(data, *, limit=6000, callback=None, history_exact_chapters=None, selected_route=None, preserve_quotes=()):
    from novel_forge.modules.context_builder.request_capacity import apply_capacity_projection, expand_semantic_history, prepare_request_capacity, project_capacity_passages
    from novel_forge.modules.chapter_authority.context_compression_provider import context_compression_task_view
    from tests.unit.test_complete_request_capacity import route
    original = expand_semantic_history(data)
    boundary = {"kind": "FROZEN_STAGE_INPUTS", "project_id": "p", "book_id": "b", "sources": [{"asset_version_id": "context", "content_hash": "frozen"}]}
    calls = []
    def measure(projection):
        supplied = project_capacity_passages(original, apply_capacity_projection(original, projection), projection) if projection else original
        return len(json.dumps(supplied, ensure_ascii=False).encode()) + 500, limit
    def call(stage, task):
        view = context_compression_task_view(stage, {"context_compression_task": task})
        calls.append(view)
        if callback:
            overridden = callback(stage, task)
            if overridden is not None:
                return overridden
        if stage == "context_compress":
            optional = [unit["unit_id"] for unit in task["units"] if not unit.get("context_only") and not unit["required"]]
            return {"selected_unit_ids": [*task["required_unit_ids"], *optional[:1]]}
        return {"supported": True, "coverage_complete": True, "missing_unit_ids": [], "distorted_unit_ids": []}
    projection = prepare_request_capacity(original=original, stage="draft", source_boundary=boundary,
        route=selected_route or route(method="SCRIPTED_UTF8_BYTES_EXACT_V1", model="fixture", limit=limit), measure=measure,
        model_call=call, chunk_fits=lambda chunk: len(json.dumps(chunk, ensure_ascii=False).encode()) < 18000,
        semantic_contract=semantic.SEMANTIC_CONTRACT, history_exact_chapters=history_exact_chapters, preserve_quotes=preserve_quotes)
    return original, projection, calls


def test_semantic_complete_request_consumes_the_actual_final_projection_and_preserves_rich_fields():
    from novel_forge.modules.context_builder.request_capacity import apply_capacity_projection, project_capacity_passages
    data = {"input_manifest": {"goal": "Continue from the selected working experience."}, "context_bundle": {"segments": [{
        "asset_type": "chapter_episodic_summary", "asset_version_id": "history:v1", "content_hash": "original",
        "safe_summary": json.dumps({"subject": "阿岚", "perspective": "HEARSAY", "knowledge_owner": "阿岚", "status": "SELECTED_WORKING_NOT_ACCEPTED",
            "summary": "\n\n".join(f"第{index}段。" + "海潮拍打旧石堤。" * 40 for index in range(40))}, ensure_ascii=False),
        "structured_facts": [{"condition": "潮尺严格低于二尺", "time": "初九", "knowledge_owner": "阿岚"}]}]}}
    original, projection, calls = semantic_preparation(data)
    assert projection and projection["measurement"]["after_reserved"] <= 6000
    final = project_capacity_passages(original, apply_capacity_projection(original, projection), projection)
    summary = final["context_bundle"]["segments"][0]["safe_summary"]
    assert summary["subject"] == "阿岚" and summary["knowledge_owner"] == "阿岚"
    assert summary["status"] == "SELECTED_WORKING_NOT_ACCEPTED" and "省略" in summary["summary"]
    assert final["context_bundle"]["segments"][0]["structured_facts"] == data["context_bundle"]["segments"][0]["structured_facts"]
    assert projection["final_composition"]["supplied_projection_hash"] == semantic.narrative_hash(final)
    assert any(call.get("composition_check", {}).get("phase") == "FINAL_PROVIDER_COMPOSITION" for call in calls)
    assert any(unit.get("source_fields") and unit["attribution"].get("knowledge_owner") == "阿岚" for call in calls for unit in call["units"])


def test_final_request_restore_reallocates_from_original_sources_and_checks_the_new_version():
    from novel_forge.modules.context_builder.request_capacity import apply_capacity_projection
    from tests.unit.test_complete_request_capacity import source_data
    data = source_data(40, 180)
    restored = []
    def callback(stage, task):
        if stage == "context_fidelity" and task.get("composition_check", {}).get("phase") == "FINAL_PROVIDER_COMPOSITION" and not restored:
            omitted = [unit for unit in task["units"] if unit["unit_id"] not in task["selected_unit_ids"]]
            if omitted:
                restored.append(omitted[0]["text"])
                return {"supported": True, "coverage_complete": False, "missing_unit_ids": [omitted[0]["unit_id"]], "distorted_unit_ids": []}
    original, projection, calls = semantic_preparation(data, limit=5000, callback=callback)
    assert restored and projection
    final = apply_capacity_projection(original, projection)
    assert restored[0] in final["context_bundle"]["segments"][0]["safe_summary"]
    assert projection["measurement"]["after_reserved"] <= 5000
    checks = projection["final_composition"]["provider_combination"]
    assert checks["supplied_projection_hash"] == projection["final_composition"]["supplied_projection_hash"]
    assert len({call["composition_check"].get("supplied_projection_hash") for call in calls if call.get("composition_check", {}).get("phase") == "FINAL_PROVIDER_COMPOSITION"}) >= 2


def test_real_structured_record_dependencies_include_the_original_condition_text():
    source = candidate(json.dumps({'events': [
        {'event_id': 'cause:a', 'summary': '只有潮尺低于二尺，许可方才生效。'},
        {'event_id': 'effect:b', 'depends_on': ['cause:a'], 'summary': '于是她开闸。'}]}, ensure_ascii=False))
    units = semantic.source_units(source, {})
    semantic.close_catalog_dependencies({source.asset_version_id: units})
    keep = semantic.close_dependencies(units, {unit['unit_id'] for unit in units if unit['required'] or unit['text'] == '于是她开闸。'})
    result = json.loads(semantic.reconstruct(source, units, keep)['safe_summary'])
    assert result['events'][0]['summary'] == '只有潮尺低于二尺，许可方才生效。'
    assert result['events'][1]['summary'] == '于是她开闸。'


def test_contiguous_working_passages_use_original_unicode_newline_coordinates():
    from novel_forge.modules.context_builder.request_capacity import validate_projection_quotes
    source = {'asset_version_id': 'original', 'passages': [
        {'start': 0, 'end': 5, 'text': '🜁甲。\n\n'}, {'start': 5, 'end': 7, 'text': '乙。'}]}
    assert validate_projection_quotes({'working_prose': source}, ('🜁甲。\n\n乙。',))
    source['passages'][1].update(start=6, end=8)
    with pytest.raises(KernelError, match='PRESERVE_QUOTE_UNAVAILABLE'):
        validate_projection_quotes({'working_prose': source}, ('🜁甲。\n\n乙。',))


def test_exact_indivisible_source_does_not_require_a_second_full_checker_request():
    big = 'if ' + 'x' * 19000 + '.'
    small = '\n\n'.join('ordinary ' + str(i) + ' ' + 'y' * 500 + '.' for i in range(70))
    data = {'context_bundle': {'segments': [{'asset_type': 'chapter_episodic_summary', 'asset_version_id': identity,
        'content_hash': identity, 'safe_summary': text} for identity, text in [('big', big), ('small', small)]]}}
    _, projection, _ = semantic_preparation(data, limit=22000)
    assert projection['measurement']['after_reserved'] <= 22000
    assert projection['final_composition']['provider_combination']['exact_original_sources']


@pytest.mark.parametrize('order', [(0, 1, 2), (2, 1, 0), (1, 0, 2)])
def test_bridging_original_ranges_merge_the_entire_connected_component(order):
    import hashlib
    ranges = [(0, 4), (6, 10), (3, 7)]
    original = 'abcdefghij'
    sources = [replace(candidate(original[start:end], source_identity='source', source_revision='v1', content_digest='whole'),
        asset_version_id=str(index), provenance={'source_range': {'field_path': ['text'], 'start': start, 'end': end,
        'text_hash': 'sha256:' + hashlib.sha256(original[start:end].encode()).hexdigest()}}) for index, (start, end) in enumerate(ranges)]
    result, _ = semantic.exact_deduplicate([sources[index] for index in order])
    assert len(result) == 1 and result[0].safe_summary == original
    assert len(result[0].provenance['lossless_range_union']['members']) == 3


def test_budget_allocation_reserves_required_quotes_in_later_chunks():
    import json
    boundary = {'kind': 'FROZEN_STAGE_INPUTS', 'project_id': 'p', 'book_id': 'b',
        'sources': [{'asset_version_id': 'context', 'content_hash': 'frozen'}]}
    original = candidate('\n\n'.join(['ordinary ' + 'x' * 80 for _ in range(15)] + ['must keep last.']),
        provenance={'frozen_input_boundary': boundary})
    task = {'stage': 'draft', 'semantic_contract': semantic.SEMANTIC_CONTRACT, 'frozen_input_boundary': boundary,
        'source_projection_hash': 'frozen', 'preserve_quotes': ['must keep last.']}
    compression_calls = []
    def call(stage, chunk):
        if stage == 'context_compress':
            compression_calls.append(chunk)
            return {'selected_unit_ids': [unit['unit_id'] for unit in chunk['units'] if not unit.get('context_only')]}
        return {'supported': True, 'coverage_complete': True, 'missing_unit_ids': [], 'distorted_unit_ids': []}
    result, _ = compile_task_context([original], task=task, token_budget=300, required_asset_types=(),
        model_call=call, compression_input_tokens=16000, chunk_fits=lambda chunk: len(json.dumps(chunk).encode()) <= 4500,
        token_counter=lambda value: len(json.dumps(value)))
    assert len(compression_calls) > 1
    assert 'must keep last.' in result[0].safe_summary


def test_unversioned_history_fields_keep_the_actual_custodian_without_fabricated_source_identity():
    from tests.unit.test_complete_request_capacity import source_data
    data = source_data(40, 180)
    segment = data['context_bundle']['segments'][0]
    segment.pop('asset_version_id', None)
    segment.pop('content_hash', None)
    segment['chapter'] = 1
    _, projection, calls = semantic_preparation(data)
    assert projection and all('source_expression' not in call['task'] for call in calls)
    assert all(call['frozen_input_boundary']['sources'] == [{'asset_version_id': 'context', 'content_hash': 'frozen'}] for call in calls)


@pytest.mark.parametrize('protected_cause', [False, True])
def test_final_global_dependency_closure_uses_original_cause_and_actual_unchanged_plan(protected_cause):
    from novel_forge.modules.context_builder.request_capacity import apply_capacity_projection
    condition = '只有潮尺低于二尺才可开闸。'
    side = '\n\n'.join('side ' + str(i) + ' ' + 'x' * 180 for i in range(18))
    data = {'context_bundle': {'segments': [
        {'asset_type': 'chapter_episodic_summary', 'asset_version_id': 'a', 'content_hash': 'original-a',
            'safe_summary': json.dumps({'event_id': 'cause:a', 'summary': condition + '\n\n' + side}, ensure_ascii=False)},
        {'asset_type': 'chapter_episodic_summary', 'asset_version_id': 'b', 'content_hash': 'original-b',
            'safe_summary': json.dumps({'event_id': 'effect:b', 'depends_on': ['cause:a'], 'summary': '因此她开闸。\n\n' + side}, ensure_ascii=False)}]}}
    if protected_cause:
        data['context_bundle']['segments'].pop(0)
        data['chapter_plan'] = {'planned_dependency_sources': [{'status': 'FROZEN_PLAN_NOT_EVENT_ACCEPTANCE',
            'source_asset_version_id': 'original-plan', 'dependencies': [{'planned_event': {'event_id': 'cause:a', 'summary': condition}}]}]}
    def select(stage, chunk):
        if stage == 'context_compress':
            return {'selected_unit_ids': [unit['unit_id'] for unit in chunk['units'] if not unit.get('context_only') and unit['text'].startswith('因此')]}
    original, projection, _ = semantic_preparation(data, limit=3000 if protected_cause else 6500, callback=select)
    assert projection
    final = apply_capacity_projection(original, projection)
    assert '因此她开闸。' in final['context_bundle']['segments'][-1]['safe_summary']['summary']
    if protected_cause:
        assert final['chapter_plan'] == original['chapter_plan']
        assert any(row['alias'] == 'cause:a' for row in projection['final_composition']['unchanged_dependency_bindings'])
    else:
        assert condition in final['context_bundle']['segments'][0]['safe_summary']['summary']
    assert projection['measurement']['after_reserved'] <= projection['measurement']['limit']


def test_frozen_semantic_policy_separates_complete_preparation_from_exact_recent_expression():
    from copy import deepcopy
    from novel_forge.modules.context_builder.request_capacity import apply_capacity_projection, historical_expression_paths
    import hashlib
    paragraphs, position = [], 0
    for i in range(12):
        text = 'Paragraph ' + str(i) + ' ' + 'x' * 180 + '.\n\n'
        paragraphs.append({'text': text, 'start': position, 'end': position + len(text),
            'text_hash': 'sha256:' + hashlib.sha256(text.encode()).hexdigest()})
        position += len(text)
    data = {'working_manuscript': {'projection_policy': {'version': 'working-prose-projection.v6', 'recent_complete_chapters': 2},
        'target_chapter': 3, 'sources': [{'chapter': chapter, 'asset_version_id': str(chapter), 'content_hash': 'original-' + str(chapter),
            'source_characters': position, 'passages': deepcopy(paragraphs)} for chapter in (1, 2)]}}
    frozen = deepcopy(data)
    assert not historical_expression_paths(data, semantic=True)
    original, projection, _ = semantic_preparation(data, limit=7500, history_exact_chapters=1)
    final = apply_capacity_projection(original, projection)
    assert data == frozen
    assert final['working_manuscript']['projection_policy'] == frozen['working_manuscript']['projection_policy']
    assert final['working_manuscript']['sources'][1] == frozen['working_manuscript']['sources'][1]
    assert final['working_manuscript']['sources'][0] != frozen['working_manuscript']['sources'][0]
    assert projection['capacity_history_exact_chapters'] == 1 and projection['measurement']['after_reserved'] <= 7500


@pytest.mark.parametrize('raw,reason', [
    ('{"quantity":0.123456789012345678901,"summary":"original"}', 'JSON_NUMERIC_VALUE_NOT_PRESERVED'),
    ('{"subject":"A","subject":"B","summary":"original"}', 'DUPLICATE_JSON_FIELD'),
    ('{"quantity":NaN,"summary":"original"}', 'JSON_NONFINITE_VALUE'),
    ('{"quantity":1e99999999999999999999999999,"summary":"original"}', 'JSON_NUMERIC_VALUE_NOT_PRESERVED'),
    ('{"quantity":0e99999999999999999999999999,"summary":"original"}', 'JSON_NUMERIC_VALUE_NOT_PRESERVED'),
])
def test_ambiguous_or_inexact_json_keeps_the_original_bytes_and_exposes_the_reason(raw, reason):
    from novel_forge.modules.context_builder.request_capacity import expand_semantic_history
    data = {'asset_type': 'chapter_episodic_summary', 'safe_summary': raw}
    assert expand_semantic_history(data) == data
    original = candidate(raw)
    units = semantic.source_units(original, {})
    assert len(units) == 1 and units[0]['required']
    assert units[0]['source_parse_assessment'] == reason
    assert semantic.reconstruct(original, units, {units[0]['unit_id']})['safe_summary'] == raw
    assert semantic.source_audit(units, {units[0]['unit_id']})[0]['source_parse_assessment'] == reason
    with pytest.raises(KernelError, match='REQUIRED_UNIT_MISSING'):
        semantic.reconstruct(original, units, set())


def test_partial_structured_reconstruction_preserves_numeric_values_and_original_version():
    raw = '{"quantity":0.1,"units":"尺","summary":"necessary.\\n\\noptional."}'
    original = candidate(raw)
    units = semantic.source_units(original, {})
    keep = {unit['unit_id'] for unit in units if unit['required'] or unit['text'] == 'necessary.'}
    result = semantic.reconstruct(original, units, keep)
    parsed = json.loads(result['safe_summary'])
    assert parsed['quantity'] == 0.1 and parsed['units'] == '尺'
    assert 'necessary.' in parsed['summary'] and 'optional.' not in parsed['summary']
    assert semantic.reconstruct(original, units, {unit['unit_id'] for unit in units})['safe_summary'] == raw


@pytest.mark.parametrize('field,value', [
    ('narrative_function', 'reader_knowledge'), ('semantic_representation_identity', 'reader-only:B'),
    ('logical_narrative_identity', 'reader-scope'), ('physical_asset_type', 'draft_version'),
    ('policy_version', 'different-source-policy'), ('section', 'KNOWLEDGE'), ('bucket', 'reader-only'),
    ('raw_source', True), ('source_risk', 1), ('active_read_generation_id', 'other-generation'),
])
def test_identical_text_does_not_collapse_distinct_semantic_or_governance_metadata(field, value):
    original = candidate('门仍未开。', source_identity='original:v1', source_revision='v1', content_digest='whole')
    other = replace(original, asset_version_id='history:b', **{field: value})
    result, receipts = semantic.exact_deduplicate([original, other])
    assert len(result) == 2 and not receipts
    assert [getattr(item, field) for item in result] == [getattr(original, field), value]


def test_exact_duplicate_retains_member_mapping_and_highest_task_relevance():
    original = replace(candidate('门仍未开。', source_identity='original:v1', source_revision='v1', content_digest='whole'), relevance_score=0.1)
    other = replace(original, asset_version_id='history:b', relevance_score=0.9, estimated_tokens=10)
    result, receipts = semantic.exact_deduplicate([original, other])
    assert len(result) == 1 and result[0].asset_version_id == original.asset_version_id
    assert result[0].relevance_score == 0.9
    assert receipts[0]['asset_version_id'] == other.asset_version_id
    assert receipts[0]['retained_asset_version_id'] == original.asset_version_id


@pytest.mark.parametrize('field,value', [
    ('semantic_representation_identity', 'reader-only:B'), ('narrative_function', 'reader_knowledge'),
    ('policy_version', 'other-policy'), ('section', 'KNOWLEDGE'), ('bucket', 'reader-only'),
])
def test_overlapping_original_ranges_require_the_entire_remaining_metadata_scope(field, value):
    import hashlib
    original = candidate('甲乙丙丁', source_identity='original:v1', source_revision='v1', content_digest='whole',
        provenance={'source_range': {'field_path': ['text'], 'start': 0, 'end': 4,
            'text_hash': 'sha256:' + hashlib.sha256('甲乙丙丁'.encode()).hexdigest()}})
    other = replace(original, asset_version_id='history:b', safe_summary='丙丁戊己', **{field: value},
        provenance={'source_range': {'field_path': ['text'], 'start': 2, 'end': 6,
            'text_hash': 'sha256:' + hashlib.sha256('丙丁戊己'.encode()).hexdigest()}})
    result, receipts = semantic.exact_deduplicate([original, other])
    assert len(result) == 2 and not receipts
    assert [getattr(item, field) for item in result] == [getattr(original, field), value]


def test_admitted_belief_and_reader_only_sources_keep_both_roles_in_actual_bundle():
    from novel_forge.modules.context_builder.domain import build_authority_context_bundle, validate_task_context_sources
    from novel_forge.modules.mkaos_authority.domain import resolve_book_knowledge_access_policy
    boundary = {'accepted_through_chapter': 0}
    access = resolve_book_knowledge_access_policy(production_profile={}, project_id='p', book_id='b')
    first = ContextCandidate(asset_version_id='A', asset_type='chapter_episodic_summary', project_id='p', book_id='b',
        estimated_tokens=10, relevance_score=1, source_identity='original:v1', source_revision='v1', content_digest='hash',
        safe_summary='门仍未开。', narrative_function='character_belief', semantic_representation_identity='hearsay:A',
        accepted_boundary=boundary, provenance={'authority': 'Book'})
    second = replace(first, asset_version_id='B', narrative_function='reader_knowledge', semantic_representation_identity='reader-only:B')
    plan = ContextCandidate(asset_version_id='plan', asset_type='chapter_plan', project_id='p', book_id='b',
        estimated_tokens=10, safe_summary='继续查验。', context_class='PROTECTED', accepted_boundary=boundary,
        provenance={'authority': 'Planning'})
    inputs = [plan, first, second]
    admitted = validate_task_context_sources(project_id='p', book_id='b', candidates=inputs, token_budget=512000,
        required_asset_types=(), accepted_boundary=boundary, knowledge_access_policy=access)
    assert admitted == frozenset({'plan', 'A', 'B'})
    selected, receipt = compile_task_context(inputs, task={'stage': 'draft', 'accepted_boundary': boundary,
        'semantic_contract': semantic.SEMANTIC_CONTRACT}, token_budget=512000, required_asset_types=(),
        admitted_source_ids=admitted, defer_token_capacity=True, model_call=lambda *args: pytest.fail('Capacity fast path called a model'))
    bundle = build_authority_context_bundle(project_id='p', book_id='b', stage='draft', created_by_operation_id='op',
        context_profile_version='draft-context-profile-v4', candidates=selected, token_budget=512000,
        authority_state_boundary=boundary, knowledge_access_policy=access, task_context_receipt=receipt, defer_token_capacity=True)
    manifest = {row['asset_version_id']: row for row in bundle['context_manifest']['selected_inputs']}
    segments = {row['asset_version_id']: row for row in bundle['stage_context_view']['segments']}
    assert manifest['A']['semantic_representation_identity'] == 'hearsay:A'
    assert manifest['B']['semantic_representation_identity'] == 'reader-only:B'
    assert segments['A']['narrative_function'] == 'character_belief'
    assert segments['B']['narrative_function'] == 'reader_knowledge'
    assert not receipt['deduplications']


@pytest.mark.parametrize("provider,method", [
    ("codex-cli", "CODEX_CLI_APPLICATION_UTF8_BYTES_UPPER_BOUND_V1"),
    ("openai", "OPENAI_UTF8_BYTES_UPPER_BOUND_V1"),
    ("deepseek", "DEEPSEEK_UTF8_BYTES_UPPER_BOUND_V1"),
])
def test_semantic_preparation_conservatively_fits_history_without_claiming_actual_overflow(provider, method):
    from tests.unit.test_complete_request_capacity import route
    from novel_forge.modules.context_builder.request_capacity import apply_capacity_projection
    selected = route(method=method, model="owned-model", limit=6000)
    selected.model_profile.model_provider = provider
    data = {"input_manifest": {"current_draft": "Keep exact current input."}, "context_bundle": {"segments": [{
        "asset_type": "chapter_episodic_summary", "asset_version_id": "history:v1", "content_hash": "original",
        "safe_summary": "\n\n".join(f"第{i}段。" + "海潮拍打旧石堤。" * 40 for i in range(40)),
        "structured_facts": [{"knowledge_owner": "阿岚", "condition": "潮尺低于二尺"}]}]}}
    original, projection, calls = semantic_preparation(data, selected_route=selected)
    assert calls and projection["measurement"]["before_reserved"] > 6000
    assert projection["measurement"]["after_reserved"] <= 6000
    final = apply_capacity_projection(original, projection)
    assert final["input_manifest"] == original["input_manifest"]
    assert final["context_bundle"]["segments"][0]["structured_facts"] == data["context_bundle"]["segments"][0]["structured_facts"]
    assert selected.token_accounting_method == method


@pytest.mark.parametrize("semantic_enabled,provider,method,evidence", [
    (False, "codex-cli", "CODEX_CLI_APPLICATION_UTF8_BYTES_UPPER_BOUND_V1", "owned-window"),
    (True, "codex-cli", "OPENAI_UTF8_BYTES_UPPER_BOUND_V1", "owned-window"),
    (True, "codex-cli", "CODEX_CLI_APPLICATION_UTF8_BYTES_UPPER_BOUND_V1", ""),
    (True, "codex-cli", "ARBITRARY_UPPER_BOUND", "owned-window"),
])
def test_uncertain_preparation_keeps_historical_and_unproven_accounting_rejections(semantic_enabled, provider, method, evidence):
    from tests.unit.test_complete_request_capacity import route
    from novel_forge.modules.context_builder.request_capacity import prepare_request_capacity
    selected = route(method=method, model="owned-model", limit=6000)
    selected.model_profile.model_provider = provider
    selected.token_accounting_evidence_ref = evidence
    with pytest.raises(KernelError, match="PROVIDER_CONTEXT_CAPACITY_UNCERTAIN"):
        prepare_request_capacity(original={}, stage="draft", source_boundary={}, route=selected,
            semantic_contract=semantic.SEMANTIC_CONTRACT if semantic_enabled else "",
            measure=lambda _: (6001, 6000), model_call=lambda *_: pytest.fail("unproven preparation"), chunk_fits=lambda _: True)


@pytest.mark.parametrize("retain_first", [False, True])
def test_small_complete_request_excess_does_not_spread_loss_across_every_history_source(retain_first):
    from novel_forge.modules.context_builder.request_capacity import expand_semantic_history, apply_capacity_projection
    data = {"input_manifest": {"goal": "Continue with the known working consequences."}, "context_bundle": {"segments": [
        {"asset_type": "chapter_episodic_summary", "asset_version_id": f"history:{i}", "content_hash": f"original:{i}",
         "safe_summary": "\n\n".join(f"Source {i} incident {j}: " + "a" * 80 for j in range(24))}
        for i in range(8)]}}
    size = len(json.dumps(expand_semantic_history(data), ensure_ascii=False).encode()) + 500

    def select_to_target(stage, task):
        if retain_first and task.get("task", {}).get("source_expression", {}).get("asset_version_id") == "history:0":
            if stage == "context_fidelity":
                return {"supported": False, "coverage_complete": False, "missing_unit_ids": [], "distorted_unit_ids": []}
            return {"selected_unit_ids": [unit["unit_id"] for unit in task["units"] if not unit.get("context_only")]}
        if stage != "context_compress":
            return None
        chosen = [unit for unit in task["units"] if unit["required"]]
        for unit in task["units"]:
            if unit in chosen or unit.get("context_only"):
                continue
            text = "\n\n".join(row["text"] for row in [*chosen, unit])
            amount = len(json.dumps({"safe_summary": text, "structured_facts": []}, ensure_ascii=False,
                sort_keys=True, separators=(",", ":")).encode())
            if amount <= task["target_tokens"]:
                chosen.append(unit)
        return {"selected_unit_ids": [unit["unit_id"] for unit in chosen]}

    original, projection, calls = semantic_preparation(data, limit=size - 1600, callback=select_to_target)
    assert projection["measurement"]["after_reserved"] <= size - 1600
    final = apply_capacity_projection(original, projection)
    changes = [old["asset_version_id"] for old, new in zip(original["context_bundle"]["segments"], final["context_bundle"]["segments"])
               if old != new]
    assert len(changes) == 1
    assert sum(call["stage"] == "context_compress" for call in calls) == 1 + retain_first
    assert changes == ["history:1" if retain_first else "history:0"]
    assert len(projection["final_composition"]["provider_combination"]["exact_original_sources"]) == 7


def test_required_material_floor_stops_without_repeating_identical_semantic_preparation():
    quote = "不能删除的已发生条件。" * 100
    data = {"context_bundle": {"segments": [{"asset_type": "chapter_episodic_summary",
        "asset_version_id": "history:v1", "content_hash": "source",
        "safe_summary": quote + "\n\n" + "可以省略的旧日闲谈。" * 100}]}}
    calls = []
    def observe(stage, task):
        calls.append(stage)
    with pytest.raises(KernelError, match="TASK_CONTEXT_COMPRESSION_NO_PROGRESS") as failure:
        semantic_preparation(data, limit=1800, preserve_quotes=(quote,), callback=observe)
    projection = failure.value.details["projection"]
    receipt = projection["compression_receipt"]
    assert receipt["effective_material_target_tokens"] > receipt["task_target_tokens"]
    assert projection["measurement"]["after_reserved"] > projection["measurement"]["limit"]
    assert calls.count("context_compress") == 1


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\n \n", "\r\n\t\r\n"])
def test_complete_request_units_keep_native_single_line_paragraph_locations(newline):
    original = candidate(newline.join(["她提起木桶。", "宋既明没有准她开闸。", "她把木桶放回原处。", "门外的闲谈渐渐散了。 "]))
    historical = semantic.source_units(original, {})
    units = semantic.source_units(original, {"semantic_contract": semantic.SEMANTIC_CONTRACT,
        "capacity_policy": "complete-request-capacity.v1"})
    assert len(historical) == (1 if newline in {"\n", "\r\n"} else 4)
    assert len(units) == 4
    assert [original.safe_summary[start:end] for start, end in (unit["source_span"] for unit in units)] == [unit["text"] for unit in units]
    quote = newline.join(["宋既明没有准她开闸。", "她把木桶放回原处。"])
    semantic.protect_quotes([original], {original.asset_version_id: units}, [quote])
    assert [unit["text"] for unit in units if unit["required"]] == ["宋既明没有准她开闸。", "她把木桶放回原处。"]
    assert semantic.reconstruct(original, units, {unit["unit_id"] for unit in units})["safe_summary"] == original.safe_summary
    selected = semantic.reconstruct(original, units, {unit["unit_id"] for unit in units if unit["required"]})["safe_summary"]
    assert quote in selected


@pytest.mark.parametrize('limit', [4000, 100000])
def test_final_risk_windows_batch_all_original_units_by_complete_request_capacity(limit):
    original = candidate('\n\n'.join(f'她没有开第{index}道闸；此前的许可尚未生效。' for index in range(90)))
    units = semantic.source_units(original, {})
    chosen = {unit['unit_id'] for index,unit in enumerate(units) if index % 2}
    calls = []
    fixed_context = '冻结原始任务身份和完整上下文。' * 20
    def fits(task):
        return len(json.dumps({'fixed_context':fixed_context,'task':task},ensure_ascii=False).encode()) <= limit
    def call(stage, task):
        assert stage == 'context_fidelity' and fits(task)
        calls.append(task)
        return dict(supported=True,coverage_complete=True,missing_unit_ids=[],distorted_unit_ids=[])
    final,proof,_ = semantic.verify_final_selection(original,units,chosen,payload=lambda group:dict(units=group),fits=fits,model_call=call)
    assert final == chosen
    checked = [unit for task in calls for unit in task['units']]
    assert {unit['unit_id'] for unit in checked} == {unit['unit_id'] for unit in units}
    assert len(checked) >= len(units) == 90
    checked_groups = [{unit["unit_id"] for unit in task["units"]} for task in calls]
    assert all(any({unit["unit_id"] for unit in window} <= batch for batch in checked_groups)
        for window in semantic.final_windows(units,chosen))
    assert proof['result_content_hash'] == semantic.narrative_hash(semantic.reconstruct(original,units,chosen))
    if limit == 100000:
        assert len(calls) == 1 and len(calls[0]['units']) > 32
    else:
        assert len(calls) > 1


def test_batched_final_checker_restores_a_far_missing_condition_and_uncertainty():
    original = candidate('\n\n'.join(f'只有第{index}份许可生效才可行动。' for index in range(90)))
    units = semantic.source_units(original,{})
    chosen = {unit['unit_id'] for index,unit in enumerate(units) if index % 2}
    def call(stage,task):
        return dict(supported=True,coverage_complete=True,missing_unit_ids=[] if 'text:80' in task['selected_unit_ids'] else ['text:80'],distorted_unit_ids=[])
    final,_,_ = semantic.verify_final_selection(original,units,chosen,payload=lambda group:dict(units=group),fits=lambda _:True,model_call=call)
    assert final == chosen | {'text:80'}
    uncertain,proof,_ = semantic.verify_final_selection(original,units,chosen,payload=lambda group:dict(units=group),fits=lambda _:True,
        model_call=lambda *_:dict(supported=False,coverage_complete=False,missing_unit_ids=[],distorted_unit_ids=[]))
    assert uncertain == {unit['unit_id'] for unit in units}
    assert proof['semantic_scope'] == 'EXACT_COMPLETE_ORIGINAL_RESTORED'


@pytest.mark.parametrize('limit',[4000,100000])
def test_capacity_batched_fidelity_keeps_condition_and_consequence_visible_together(limit):
    original = candidate('\n\n'.join(f'她没有开第{index}道闸；此前的许可尚未生效。' for index in range(90)))
    units = semantic.source_units(original,{})
    chosen = {unit['unit_id'] for index,unit in enumerate(units) if index % 2}
    calls = []
    def fits(task):
        return len(json.dumps({'frozen_context':'冻结原始任务身份和完整上下文。'*20,'task':task},ensure_ascii=False).encode()) <= limit
    def call(stage,task):
        visible = {unit['unit_id'] for unit in task['units']}
        calls.append(visible)
        missing = ['text:22'] if {'text:21','text:22'} <= visible and 'text:22' not in task['selected_unit_ids'] else []
        return dict(supported=True,coverage_complete=not missing,missing_unit_ids=missing,distorted_unit_ids=[])
    final,_,_ = semantic.verify_final_selection(original,units,chosen,payload=lambda group:dict(units=group),fits=fits,model_call=call)
    assert 'text:22' in final
    assert any({'text:21','text:22'} <= group for group in calls)


def test_final_batching_preserves_far_dependency_closures_and_rejects_an_oversized_closure():
    original = candidate('\n\n'.join(f'第{index}段的后果尚未确定。' for index in range(90)))
    units = semantic.source_units(original,{})
    units[21]['explicit_refs'] = ['far-cause']
    units[88]['source_aliases'] = ['far-cause']
    windows = semantic.final_windows(units,{'text:21','text:45'})
    def payload(group):
        return dict(frozen_context='精确冻结上下文。'*50,units=group)
    def amount(task):
        return len(json.dumps(task,ensure_ascii=False).encode())
    limit = max(amount(payload(window)) for window in windows)
    batches = semantic.pack_final_windows(windows,payload=payload,fits=lambda task:amount(task)<=limit)
    assert all(any({unit['unit_id'] for unit in window} <= {unit['unit_id'] for unit in batch} for batch in batches) for window in windows)
    assert any({'text:19','text:20','text:21','text:22','text:23','text:88'} <= {unit['unit_id'] for unit in batch} for batch in batches)
    with pytest.raises(KernelError,match='TASK_CONTEXT_CAUSAL_UNIT_TOO_LARGE'):
        semantic.pack_final_windows(windows,payload=payload,fits=lambda task:amount(task)<limit)
