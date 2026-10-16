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


def semantic_preparation(data, *, limit=6000, callback=None):
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
        route=route(method="SCRIPTED_UTF8_BYTES_EXACT_V1", model="fixture", limit=limit), measure=measure,
        model_call=call, chunk_fits=lambda chunk: len(json.dumps(chunk, ensure_ascii=False).encode()) < 18000,
        semantic_contract=semantic.SEMANTIC_CONTRACT)
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
