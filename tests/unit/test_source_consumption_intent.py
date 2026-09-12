from novel_forge.modules.source_import.corpus_ingestion.curated_analysis import CuratedAnalysisRequest


def test_historical_research_request_replay_keeps_original_frozen_shape():
    old = {"project_id": "project", "revision_id": "revision", "run_key": "research",
           "max_members": 1, "max_calls": 2, "max_tokens": 100, "authorization_ref": "fixture",
           "intelligence_policy": {}}
    assert CuratedAnalysisRequest.model_validate(old).model_dump(mode="json") == old
    creative = {**old, "intended_use": "ABSTRACT_GENERATION", "target_book_id": "declared-book"}
    assert CuratedAnalysisRequest.model_validate(creative).model_dump(mode="json") == creative
