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


def test_source_budget_scopes_unknown_guidance_to_its_original_root(monkeypatch):
    from novel_forge.storage.source_import_operations_records import SourceImportOperationsRecords
    from novel_forge.modules.command_kernel import budget_runtime
    scopes = []
    def unresolved(cursor, project, **kwargs):
        scopes.append(kwargs.get("root_operation_id"))
        return [] if kwargs else [{"operation_id": "unrelated-book-unknown"}]
    monkeypatch.setattr(budget_runtime, "unresolved_cli_outcomes", unresolved)
    monkeypatch.setattr(budget_runtime, "provider_project_usage", lambda *_: {"unmeasured_reserved_tokens": 100})
    repository = SourceImportOperationsRecords()
    repository.cursor = SimpleNamespace(execute=lambda *_: None, fetchall=lambda: [], fetchone=lambda: ("source-original-root",))
    result = repository.analysis_budget("project:1", "source-job:1")
    assert scopes == ["source-original-root", None]
    assert result["unresolved_cli_outcomes"] == []
    assert result["project_unresolved_cli_outcomes"] == [{"operation_id": "unrelated-book-unknown"}]
    assert result["project_cumulative"]["unmeasured_reserved_tokens"] == 100
