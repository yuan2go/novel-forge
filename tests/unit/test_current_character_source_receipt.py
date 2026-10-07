import pytest

from novel_forge.modules.chapter_authority.model_effects import normalize_model_output


@pytest.mark.parametrize("stage,current,historical", [("draft", "v4", "v3"), ("revision", "v6", "v5")])
def test_current_schema_normalization_retains_actor_source_evidence_without_rewriting_history(stage, current, historical):
    raw = {"scene_artifacts": [{"slot_id": "scene", "text": "The door opened.", "character_source_uses": [{"character_id": "actor", "used_fact_ids": ["own-observation"]}]}], "resolved_issue_codes": [],
        "unused_root_value": []}
    current_output = normalize_model_output(stage, raw, output_schema_ref=f"schema:chapter-provider-output:{stage}:{current}")
    assert current_output["scene_artifacts"][0]["character_source_uses"] == raw["scene_artifacts"][0]["character_source_uses"]
    old = normalize_model_output(stage, raw, output_schema_ref=f"schema:chapter-provider-output:{stage}:{historical}")
    assert "unused_root_value" not in old
    assert "unused_root_value" not in normalize_model_output(stage, raw)
