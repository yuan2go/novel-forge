from types import SimpleNamespace

import pytest

from novel_forge.modules.source_import import analysis_query


@pytest.mark.parametrize("unknown", [False, True])
def test_paused_analysis_requires_cli_reconciliation_before_resume(monkeypatch, unknown):
    frozen = {
        "workspace_id": "workspace:1",
        "corpus_id": "corpus:1",
        "revision_id": "revision:1",
        "manifest": {"state": "FROZEN", "purpose": "RESEARCH"},
        "members": [],
    }
    budget = {"unresolved_cli_outcomes": [{"effect_id": "effect:1"}] if unknown else []}
    repository = SimpleNamespace(
        job_execution_counts=lambda *_: [],
        analysis_member_counts=lambda *_: {},
        analysis_knowledge_counts=lambda *_: {"review_required": False},
        job_active_leases=lambda *_: [],
        analysis_budget=lambda *_: budget,
    )
    sources = SimpleNamespace(catalog_current=lambda *_, **__: frozen)
    monkeypatch.setattr(analysis_query, "curated_availability", lambda *_: [])
    result = analysis_query.analysis_job(
        repository,
        sources,
        {
            "project_id": "project:1",
            "workspace_id": "workspace:1",
            "import_job_id": "job:1",
            "status": "PAUSED",
        },
        {
            "version": 1,
            "payload": {
                "curated_revision_id": "revision:1",
                "members": [],
                "budget": {},
                "requested_manifest": {"revision_id": "revision:1"},
            },
        },
    )
    assert result["analysis_state"] == "PAUSED"
    assert result["budget"] == budget
    assert result["next_action"] == ("RECONCILE_CLI_OUTCOME" if unknown else "RESUME")
