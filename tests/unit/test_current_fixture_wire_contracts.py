from copy import deepcopy
import json

import pytest

from novel_forge.modules.canon_graph.source_spans import bind_source_spans, source_spans
from novel_forge.modules.command_kernel.errors import KernelError
from tests.integration.current_chapter_wire_support import current_chapter_wire_result
from tests.integration.current_planning_wire_support import current_planning_wire_result


def fixture_claim(text):
    return {"canon_facts": [{"subject": "observer", "predicate": "sees", "object": "snow",
        "evidence_start": 0, "evidence_end": 3, "evidence_quote": text[:3]}]}


@pytest.mark.parametrize("envelope", [False, True])
def test_scripted_current_spans_bind_through_actual_domain(envelope):
    text = "雪落在长街。无人改变决定。"
    raw = fixture_claim(text)
    original = deepcopy(raw)
    wire = current_chapter_wire_result("canon_extraction", {"canon_context_projection": "canon-source-context.v1",
        "source_span_table": source_spans(text), "revision": {"text": text}}, raw, json_envelope=envelope)
    payload = json.loads(wire["payload_json"]) if envelope else wire
    bound = bind_source_spans(payload, text)
    assert bound["canon_facts"][0]["evidence_quote"] in text
    assert raw == original
    with pytest.raises(KernelError, match="CANON_SOURCE_SPAN_INVALID"):
        bind_source_spans(payload, "风吹过庭院。无人改变决定。")


def test_scripted_old_canon_wire_is_not_reinterpreted():
    raw = fixture_claim("雪落在长街。")
    assert current_chapter_wire_result("canon_extraction", {}, raw) == raw
    with pytest.raises(ValueError, match="exact frozen source span table"):
        current_chapter_wire_result("canon_extraction", {"canon_context_projection": "canon-source-context.v1"}, raw)


@pytest.mark.parametrize("version,contract", [("1.18.0", "chapter-mission-scene.v3"), ("1.19.0", "chapter-mission-scene.v4")])
def test_scripted_method_projection_follows_frozen_work_contract(version, contract):
    raw = {"chapter_contract_schema_version": "chapter-mission-scene.v2", "required_state_delta": {"summary": "A choice becomes public"}}
    inputs = {"stage": "chapter_plan.generate", "planning_command": {"execution_contract_version": version,
        "creative_requirements_contract": "work-requirements.v1"}}
    result = current_planning_wire_result(raw, inputs)
    assert result["chapter_contract_schema_version"] == contract
    assert result["required_state_delta"] == {"status": "CHANGED", "summary": "A choice becomes public"}
    assert current_planning_wire_result(result, inputs) == result
    assert current_planning_wire_result(raw, {"planning_command": {"execution_contract_version": version}}) == raw
