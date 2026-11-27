from copy import deepcopy

import pytest

from novel_forge.modules.canon_graph.source_spans import source_spans
from tests.integration.current_chapter_wire_support import current_chapter_wire_result


@pytest.mark.parametrize("stage", ["canon_extraction", "quality_structural"])
@pytest.mark.parametrize("envelope", [False, True])
def test_current_fixture_can_replay_its_exact_wire_without_rebinding(stage, envelope):
    inputs, result = _fixture(stage)
    first = current_chapter_wire_result(stage, inputs, result, json_envelope=envelope)
    assert current_chapter_wire_result(stage, inputs, first, json_envelope=envelope) == first


@pytest.mark.parametrize("stage", ["canon_extraction", "quality_structural"])
def test_replayed_fixture_rejects_a_foreign_candidate_span(stage):
    inputs, result = _fixture(stage)
    first = current_chapter_wire_result(stage, inputs, result, json_envelope=False)
    changed = deepcopy(first)
    if stage == "canon_extraction":
        changed["canon_facts"][0]["evidence_span_id"] = "foreign-candidate-span"
    else:
        changed["dimensions"][0]["evidence_locations"][0]["span_id"] = "foreign-candidate-span"
    with pytest.raises(ValueError, match="exact frozen candidate"):
        current_chapter_wire_result(stage, inputs, changed, json_envelope=False)


def _fixture(stage):
    text = "A witness leaves the only safe route before the gate closes."
    inputs = {"revision": {"text": text}, "source_span_table": source_spans(text),
              "canon_context_projection": "canon-source-context.v1", "quality_span_contract": "literal-source-spans.v1",
              "quality_context": {"creative_baseline": {"method_requirements": {}}}}
    result = {"canon_facts": [{"evidence_start": 0, "evidence_end": len(text), "evidence_quote": text}]}
    if stage != "canon_extraction":
        result = {"dimensions": [{"dimension": "readability", "gate_status": "PASSED", "score": 90,
                                  "evidence_locations": [{"start": 0, "end": len(text)}]}]}
    return inputs, result
