from types import SimpleNamespace
from unittest.mock import Mock
import json
import pytest

from scripts import run_world_production_smoke as runner


def test_pilot_may_not_report_complete_with_an_unfinished_cross_cursor_group(monkeypatch):
    monkeypatch.setattr(runner, 'RuntimeJobAuthority', lambda database: None)
    book = {'project_id': 'p', 'book_id': 'b', 'book_run_id': 'run', 'state': 'CANON_COMMITTED',
            'target_chapter_count': 180, 'accepted_through_chapter': 6}
    group = {'group_run_id': 'group5-7', 'state': 'CHAPTER_RUNNING', 'chapter_start': 5, 'chapter_end': 7}
    authority = SimpleNamespace(database_url='unused', require=lambda identity: book, pause=Mock())
    composition = SimpleNamespace(principal='operator', authority=authority,
        query=SimpleNamespace(active_chapter_group_run_id=lambda **kwargs: 'group5-7'),
        chapter_groups=SimpleNamespace(require=lambda identity: group, reconcile_and_accept=Mock(), close=Mock()))
    result = runner.drive(composition=composition, chapter=Mock(), book_run_id='run', worker=Mock(),
                          events=lambda event: None, maximum_ticks=1, deadline=0, pilot_stop_after_chapter=6)
    assert result != 'PILOT_ACCEPTED_CURSOR_REACHED', 'group5-7 remains CHAPTER_RUNNING at accepted6'


def test_intervention_stops_before_chapter4_even_inside_an_existing_group(monkeypatch):
    jobs = SimpleNamespace(claim=lambda **kwargs: 'claim')
    monkeypatch.setattr(runner, 'RuntimeJobAuthority', lambda database: jobs)
    monkeypatch.setattr(runner, 'schedule_book_coordination_jobs', lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, 'execute_book_coordination_claim', lambda *args: {'action':'DISPATCH_CHAPTER','operation_id':'root4'})
    book = {'project_id':'p','book_id':'b','book_run_id':'run','state':'CANON_COMMITTED',
            'accepted_through_chapter':3,'target_chapter_count':180}
    chapter = Mock()
    chapter.scheduler.return_value.tick.return_value = SimpleNamespace(saga_status='SUCCEEDED')
    monkeypatch.setattr(runner, 'asdict', lambda value: {'saga_status':value.saga_status})
    composition = SimpleNamespace(principal='operator', authority=SimpleNamespace(database_url='unused',require=lambda identity:book,pause=Mock()),
        query=SimpleNamespace(active_plan_covering_chapter=lambda **kwargs:{'content':{'chapter_range':[3,5]},'asset_version_id':'group3-5'},
                              progress=lambda **kwargs:SimpleNamespace(active_operation_status='READY',active_operation_id='root4')))
    result = runner.drive(composition=composition,chapter=chapter,book_run_id='run',worker=SimpleNamespace(principal_id='w'),
                          events=lambda event:None,maximum_ticks=1,deadline=float('inf'),stop_after_chapter=3,pilot_stop_after_chapter=6)
    chapter.scheduler.assert_not_called()
    assert result == 'FUTURE_PLAN_CHANGE_SCOPE_BLOCKED'


def test_partial_evidence_export_cannot_be_promoted_to_complete_blind_material(tmp_path):
    from tests.unit.test_creation_export import _comparison_exports
    from scripts.prepare_knowledge_closure import blind_export
    _comparison_exports(tmp_path)
    folder=tmp_path/'treatment'
    identity_path=folder/'creation-run.json'
    identity=json.loads(identity_path.read_text())
    identity.update(status='EVIDENCE_EXPORT_BLOCKED',artifact_export_error='model_call_log reached 500 item bound')
    identity_path.write_text(json.dumps(identity))
    (folder/'asset-export-status.json').write_text(json.dumps({'status':'PARTIAL','errors':[{'asset_type':'model_call_log','error':'missing page'}]}))
    with pytest.raises(ValueError):
        blind_export(folder,tmp_path/'control',tmp_path/'blind')
