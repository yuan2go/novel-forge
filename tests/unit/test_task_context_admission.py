from __future__ import annotations

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from tests.unit.test_context_retrieval_v2 import _intent, _memo


def test_task_dependency_admission_is_wired_only_for_the_frozen_v4_profile(monkeypatch) -> None:
    from novel_forge.modules.chapter_authority import orchestrator
    from novel_forge.modules.context_builder.production_retrieval import RetrievalDiscovery

    boundary = {"accepted_through_chapter": 8}
    contents = {"plan:v1": {"book_id": "book:novel", "required_long_distance_fact_ids": ["fact:hook"]},
                "intent:v1": _intent(), "memo:v1": _memo()}
    monkeypatch.setattr(orchestrator, "_asset_content", lambda _url, **values: contents[values["asset_version_id"]])
    source_rows = [["sha256:" + "a" * 64, "ACTIVE", "ELIGIBLE", "CLEAR"]]

    class Cursor:
        def execute(self, query, params):
            assert params == ["state:v8", "project:novel"]

        def fetchone(self):
            return source_rows[0]

    class Uow:
        cursor = Cursor()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(orchestrator, "AuthorityUnitOfWork", lambda _url: Uow())
    observed = []

    def discover(_url, **values):
        observed.append(values["query_plan"])
        return RetrievalDiscovery((), (), (), values["query_plan"], {})

    monkeypatch.setattr(orchestrator, "discover_accepted_retrieval_candidates", discover)
    request_args = dict(project_id="project:novel", workspace_id="workspace:novel", actor_id="author:novel",
        chapter=9, title="Title", premise="Premise", trace_id="trace:novel", correlation_id="correlation:novel",
        application_build_id="build:novel", commit_sha="a" * 40, book_id="book:novel",
        context_candidates=({"asset_type": "story_state_snapshot", "asset_version_id": "state:v8",
            "content_hash": "sha256:" + "a" * 64, "project_id": "project:novel", "book_id": "book:novel",
            "accepted_boundary": boundary, "structured_facts": [{"source_event_id": "event:current", "state": {"fact_id": "fact:hook", "world_transition": {"cause_refs": ["event:causal"]}}}]},))
    snapshot_args = dict(plan_asset_version_id="plan:v1", intent_asset_version_id="intent:v1", memo_asset_version_id="memo:v1")
    v4 = orchestrator.SingleChapterRequest(**request_args, preparation_report={"stage_context_profile_versions": {"draft": "draft-context-profile-v4"}})
    orchestrator._retrieval_admission_snapshot("fixture", request=v4, **snapshot_args)
    assert observed[-1]["task_dependency_refs"]["required_refs"] == ["event:causal", "fact:hook"]
    assert observed[-1]["task_dependency_refs"]["protected_fact_aliases"] == ["event:current", "fact:hook"]
    legacy = orchestrator.SingleChapterRequest(**request_args, preparation_report={"stage_context_profile_versions": {"draft": "draft-context-profile-v3"}})
    orchestrator._retrieval_admission_snapshot("fixture", request=legacy, **snapshot_args)
    assert "task_dependency_refs" not in observed[-1]
    source_rows[0] = None
    with pytest.raises(KernelError) as failure:
        orchestrator._retrieval_admission_snapshot("fixture", request=v4, **snapshot_args)
    assert failure.value.code == "RETRIEVAL_TASK_SOURCE_BINDING_INVALID"


def test_obligation_lineage_requires_exact_frozen_state_canon_and_rejects_unknown_sources() -> None:
    from novel_forge.modules.context_builder.production_retrieval import _obligation_accepted_lineage
    from types import SimpleNamespace
    class Cursor:
        def __init__(self, rows):
            self.rows = rows
        def execute(self, query, parameters):
            assert "accepted.status='COMMITTED'" in query and "projection.status='COMPLETE'" in query
            assert parameters == ["project", "book", 8, "state:8", "canon:8"]
        def fetchall(self):
            return self.rows
    arguments = dict(project_id="project", book_id="book", boundary=8, accepted_boundary={
        "story_state_asset_version_id": "state:8", "canon_snapshot_asset_version_id": "canon:8",
    })
    assert _obligation_accepted_lineage(SimpleNamespace(cursor=Cursor([("source-run",)])), **arguments) == "source-run"
    for rows in ([], [("source-run",), ("other-edition",)]):
        with pytest.raises(KernelError) as failure:
            _obligation_accepted_lineage(SimpleNamespace(cursor=Cursor(rows)), **arguments)
        assert failure.value.code == "RETRIEVAL_TASK_SOURCE_BINDING_INVALID"
    with pytest.raises(KernelError):
        _obligation_accepted_lineage(SimpleNamespace(cursor=Cursor([])), **{**arguments, "accepted_boundary": {"story_state_asset_version_id": "state:8"}})
    with pytest.raises(KernelError) as missing:
        _obligation_accepted_lineage(SimpleNamespace(cursor=Cursor([])), **{**arguments, "accepted_boundary": {}, "require_frozen": True})
    assert missing.value.code == "RETRIEVAL_TASK_SOURCE_BINDING_INVALID"


def test_obligation_boundary_discovery_blocks_instead_of_truncating_excess_events() -> None:
    from types import SimpleNamespace
    from novel_forge.modules.context_builder.production_retrieval import _discover_obligation_dependencies
    class Cursor:
        def execute(self, query, parameters):
            assert "LIMIT %s" in query and parameters[-1] == 4097
            assert "authority_book_acceptance_lineage" in query
        def fetchall(self):
            return [(None,)] * 4097
    with pytest.raises(KernelError) as failure:
        _discover_obligation_dependencies(SimpleNamespace(cursor=Cursor()), project_id="project", book_id="book", boundary=8,
            cutoff="2026-10-01T00:00:00Z", obligation_ids={"obligation"}, accepted_boundary={})
    assert failure.value.code == "RETRIEVAL_TASK_DEPENDENCY_LIMIT"


@pytest.mark.parametrize("chapter,alias", [(0, ""), (0, "original-initial-alias"), (1, ""), (1, "original-initial-alias")])
def test_initial_obligation_discovery_validates_original_state_without_accepted_planting(chapter, alias, monkeypatch) -> None:
    from copy import deepcopy
    from types import SimpleNamespace
    from novel_forge.modules.context_builder.production_retrieval import _discover_task_dependencies, build_task_dependency_refs
    from novel_forge.modules.narrative_state import compact_current_state_facts
    from novel_forge.modules.narrative_state.reality import narrative_hash
    state = {"obligation_id": "initial-promise", "status": "OPEN", "priority": "HIGH", "condition": "only if the key returns"}
    entry = {"entity_key": "obligation_id=initial-promise", "state": state, "source_event_id": alias, "source_chapter": 0, "effective_from_chapter": 0}
    original = {"contract_version": "story-state-snapshot-v2", "project_id": "project", "book_id": "book", "accepted_through_chapter": chapter,
                "current_state": {"narrative_obligation": [entry]}}
    digest = narrative_hash(original)
    boundary = {"accepted_through_chapter": chapter, "story_state_asset_version_id": "state:current", "canon_snapshot_asset_version_id": "canon:current"}
    dependencies = build_task_dependency_refs(plan={"chapter": chapter + 1}, current_candidates=[
        {"asset_type": "story_state_snapshot", "asset_version_id": "state:current", "content_hash": digest,
         "accepted_boundary": boundary, "structured_facts": compact_current_state_facts(original)},
    ])
    class Cursor:
        def __init__(self, row):
            self.row = row
            self.history_queries = 0
        def execute(self, query, parameters):
            self.query = query
            if "authority_narrative_reality_revision" in query:
                self.history_queries += 1
            elif "SELECT version.content_hash, version.content" in query:
                assert parameters == ["state:current", "project"]
        def fetchone(self):
            if "clock_timestamp()" in self.query:
                from datetime import datetime, timezone
                return [datetime(2026, 10, 1, tzinfo=timezone.utc)]
            return self.row
        def fetchall(self):
            return []
    row = [digest, original, "story_state_snapshot", "ACTIVE", "ELIGIBLE", "CLEAR"]
    cursor = Cursor(row)
    arguments = dict(project_id="project", book_id="book", boundary=chapter, cutoff="2026-10-01T00:00:00Z", query_plan={"accepted_boundary": boundary, "task_dependency_refs": dependencies})
    documents, trace = _discover_task_dependencies(SimpleNamespace(cursor=cursor), **arguments)
    assert documents == () and trace["protected_initial_obligation_ids"] == ["initial-promise"]
    assert trace["protected_initial_obligation_sources"] == dependencies["protected_initial_obligations"]
    assert trace["required_obligation_ids"] == ["initial-promise"] and trace["matched_documents_by_obligation"] == {} and cursor.history_queries == 0
    from novel_forge.modules.context_builder import production_retrieval
    from novel_forge.modules.context_builder.retrieval_campaign import evaluate_retrieval_coverage
    class Uow:
        def __init__(self):
            self.cursor = Cursor(row)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
    monkeypatch.setattr(production_retrieval, "AuthorityUnitOfWork", lambda _url: Uow())
    intent = {"chapter": chapter + 1, "intent_fingerprint": narrative_hash("intent"), "accepted_boundary": boundary,
              "active_obligations": [{"state": state}], "retrieval_graph": {}, "required_arc_contributions": []}
    memo = {"chapter": chapter + 1, "qualification": "QUALIFIED", "memo_fingerprint": narrative_hash("memo"), "accepted_boundary": boundary,
            "retrieval_queries": ["initial promise"], "obligation_actions": [{"obligation_id": "initial-promise"}], "arc_actions": []}
    query = production_retrieval.build_retrieval_query_plan(intent=intent, memo=memo, semantic_policy="DISABLED", task_dependency_refs=dependencies)
    original_coverage = deepcopy(query["coverage_contract"])
    assert original_coverage["protected_evidence"]["obligation_ids"] == []
    discovery = production_retrieval.discover_accepted_retrieval_candidates("fixture", project_id="project", book_id="book", query_plan=query)
    coverage = discovery.query_plan["coverage_contract"]
    assert coverage["protected_evidence"]["obligation_ids"] == (["initial-promise"] if chapter else [])
    assert evaluate_retrieval_coverage(contract=coverage, documents=())["sufficient"] is True
    if chapter:
        assert coverage["coverage_contract_fingerprint"] != original_coverage["coverage_contract_fingerprint"]
        assert evaluate_retrieval_coverage(contract=original_coverage, documents=())["sufficient"] is False
    assert discovery.query_plan["query_plan_fingerprint"] != query["query_plan_fingerprint"]
    replay = production_retrieval.discover_accepted_retrieval_candidates("fixture", project_id="project", book_id="book", query_plan=discovery.query_plan)
    assert replay.query_plan == discovery.query_plan
    legacy_frozen = {**discovery.query_plan, "coverage_contract": original_coverage}
    legacy_frozen.pop("query_plan_fingerprint")
    legacy_frozen["query_plan_fingerprint"] = narrative_hash(legacy_frozen)
    legacy = production_retrieval.discover_accepted_retrieval_candidates("fixture", project_id="project", book_id="book", query_plan=legacy_frozen)
    assert legacy.query_plan == legacy_frozen
    changed_state = deepcopy(original)
    changed_state["current_state"]["narrative_obligation"][0]["state"]["condition"] = "invented candidate condition"
    progressed = deepcopy(original)
    progressed["current_state"]["narrative_obligation"][0]["source_chapter"] = 1
    private = deepcopy(original)
    private["current_state"]["narrative_obligation"][0]["provider_visibility"] = "INTERNAL_QUALITY_ONLY"
    for source in (None, ["changed-source-hash", *row[1:]], [digest, changed_state, *row[2:]], [digest, progressed, *row[2:]], [digest, private, *row[2:]]):
        with pytest.raises(KernelError) as denied:
            _discover_task_dependencies(SimpleNamespace(cursor=Cursor(source)), **arguments)
        assert denied.value.code == "RETRIEVAL_TASK_SOURCE_BINDING_INVALID"
    unknown = {**dependencies, "required_obligation_ids": ["unknown-promise"]}
    with pytest.raises(KernelError) as missing:
        _discover_task_dependencies(SimpleNamespace(cursor=Cursor(row)), **{**arguments, "query_plan": {"accepted_boundary": boundary, "task_dependency_refs": unknown}})
    assert missing.value.code == "RETRIEVAL_TASK_SOURCE_BINDING_INVALID"


def test_reference_observation_compiles_real_source_without_production_canon():
    import hashlib
    from dataclasses import replace
    from novel_forge.modules.context_contracts import ContextCandidate
    from novel_forge.modules.context_builder.task_compression import compile_task_context
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.source_authority.observation import observation_boundary
    boundary={'boundary_type':'SOURCE_OBSERVATION','task_id':'task:test','source_id':'source:test','edition_id':'edition:test','processing_id':'processing:test','source_work_asset_version_id':'work:test','source_hash':'sha256:'+'a'*64,'mode':'PREFIX','visible_through_chapter':2,'spans':[{'unit_version_id':'unit:2','chunk_asset_version_id':'chunk:2','byte_start':0,'byte_end':200,'content_hash':'sha256:'+'b'*64,'chapter':2}],'authorization_ref':'user:test','authorized_actor_id':'author:test','expires_at':'2099-01-01T00:00:00+00:00','use':'SOURCE_ANALYSIS','transmission':'PRIVATE_DESIGNATED_ACCOUNT','provider':'codex-cli','model':'gpt-6.1-sol','reasoning_effort':'high'}
    text='He suspects the gate is open; he has not checked.\n\nA long irrelevant description. '*8
    candidate=ContextCandidate(asset_version_id='chunk:2',asset_type='source_chunk',project_id='project:test',estimated_tokens=1,raw_source=True,source_use_mode='source_analysis',allowed_use='source_analysis',safe_summary=text,content_digest='sha256:'+hashlib.sha256(text.encode()).hexdigest(),observation_boundary=boundary,provenance={'source':'chunk:2'},relevance_score=1)
    task={'stage':'reference_analysis','observation_boundary':boundary,'goal':'What does he know?','memo_fingerprint':'observation:test'}
    selected,receipt=compile_task_context([candidate],task=task,token_budget=5000,required_asset_types=())
    assert selected[0].safe_summary==text and receipt['fast_path']
    assert receipt['observation_boundary']==boundary and 'accepted_boundary' not in receipt
    with pytest.raises(KernelError,match='BOUNDARY_REQUIRED'):
        compile_task_context([candidate],task={'stage':'draft'},token_budget=5000,required_asset_types=())
    with pytest.raises(KernelError,match='REFERENCE_SOURCE'):
        compile_task_context([replace(candidate,source_use_mode='generation')],task=task,token_budget=5000,required_asset_types=())
    future={**boundary,'visible_through_chapter':1}
    with pytest.raises(KernelError,match='future'):
        observation_boundary(future)
    observed=[]
    def semantic(stage,chunk):
        observed.append((stage,chunk))
        assert 'accepted_boundary' not in chunk and chunk['observation_boundary']==boundary
        if stage=='context_compress':
            return {'selected_unit_ids':['text:0']}
        return {'supported':True,'coverage_complete':True,'missing_unit_ids':[],'distorted_unit_ids':[]}
    selected,receipt=compile_task_context([candidate],task=task,token_budget=250,required_asset_types=(),model_call=semantic,compression_input_tokens=10000)
    assert [stage for stage,_ in observed]==['context_compress','context_fidelity']
    assert receipt['compression_trace'] and selected[0].safe_summary==text.split('\n\n')[0]
