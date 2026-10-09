from __future__ import annotations

import pytest

from novel_forge.modules.command_kernel.derived_step_revalidation import _settled_graph
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.chapter_quality_authority.context_views import _longform_chapter_plan_view


class SettledEvidence:
    def __init__(self, effects, *, recorded_failure=False, live_lease=False):
        self.effects=effects
        self.recorded_failure=recorded_failure
        self.live_lease=live_lease
        self.failure_lookup=False

    def execute(self, query, params):
        self.failure_lookup='known_failed_effects' in query

    def fetchall(self):
        return self.effects

    def fetchone(self):
        return (self.recorded_failure if self.failure_lookup else self.live_lease,)


@pytest.mark.parametrize('status,reservation,basis,authorization',[
    ('UNKNOWN','HELD_UNKNOWN','ACCOUNT_ENTITLEMENT','member'),
    ('DISPATCHING','RESERVED','ACCOUNT_ENTITLEMENT','member'),
    ('SUCCEEDED','RESERVED','ACCOUNT_ENTITLEMENT','member'),
    ('SUCCEEDED','SETTLED','PRICED','paid'),
    ('SUCCEEDED','SETTLED','ACCOUNT_ENTITLEMENT',''),
    ('FAILED_FINAL','SETTLED','ACCOUNT_ENTITLEMENT','member'),
])
def test_revalidation_cannot_release_unknown_or_borrow_unrelated_failure(status,reservation,basis,authorization):
    cursor=SettledEvidence([('effect','request-hash',status,reservation,basis,authorization)])
    with pytest.raises(KernelError):
        _settled_graph(cursor,'root')


def test_revalidation_retains_known_settled_calls_and_requires_no_live_lease():
    records=[('producing','hash1','SUCCEEDED','SETTLED','ACCOUNT_ENTITLEMENT','member'),
             ('schema-refusal','hash2','FAILED_FINAL','SETTLED','ACCOUNT_ENTITLEMENT','member')]
    assert _settled_graph(SettledEvidence(records,recorded_failure=True),'root')==[list(r) for r in records]
    with pytest.raises(KernelError,match='DERIVED_STEP_LIVE_LEASE'):
        _settled_graph(SettledEvidence(records,recorded_failure=True,live_lease=True),'root')


def test_continuity_projection_keeps_declared_constraints_distinct_from_history():
    plan={'chapter':1,'constraint_envelope':{'hard_constraints':['食火每日两次']},
          'world_rule_usages':[{'rule':'食火','use':'一次启动'}],
          'power_state_changes':[{'from':'','to':'NOVICE'}], 'scene_plan':[]}
    legacy=_longform_chapter_plan_view(plan)
    current=_longform_chapter_plan_view(plan,include_governed_constraints=True)
    assert 'governed_plan_contract' not in legacy
    assert current['governed_plan_contract']['constraint_envelope']==plan['constraint_envelope']
    assert current['governed_plan_contract']['power_state_changes']==plan['power_state_changes']
    assert 'neither accepted past events' in current['governed_plan_contract']['evidence_scope']


class FrontierEvidence:
    def __init__(self, row):
        self.row = row

    def execute(self, query, params):
        self.parameters = params

    def fetchone(self):
        return self.row


@pytest.mark.parametrize('frontier', [
    None,
    ('book', 'ABORTED', 'RUNNING', False),
    ('book', 'COMPLETED', 'RUNNING', False),
    ('book', 'CHAPTER_RUNNING', 'CANCELLED', False),
    ('book', 'CHAPTER_RUNNING', 'RUNNING', True),
    ('foreign-book', 'CHAPTER_RUNNING', 'RUNNING', False),
])
def test_chapter_recovery_rejects_closed_foreign_or_cancelled_frontier(frontier):
    from novel_forge.modules.command_kernel.step_successor import require_live_chapter_frontier
    with pytest.raises(KernelError, match='CHAPTER_RECOVERY_FRONTIER_CANCELLED'):
        require_live_chapter_frontier(FrontierEvidence(frontier), root_id='root',
                                     project_id='project', book_run_id='book')


def test_chapter_recovery_allows_exact_live_unaccepted_frontier():
    from novel_forge.modules.command_kernel.step_successor import require_live_chapter_frontier
    from novel_forge.modules.book_authority.manuscript import AUTHOR_WORKFLOW
    cursor = FrontierEvidence(('book', 'CHAPTER_RUNNING', 'RUNNING', False))
    require_live_chapter_frontier(cursor, root_id='root', project_id='project', book_run_id='book')
    assert cursor.parameters[:2] == ['project', 'root']
    assert cursor.parameters[2].obj == AUTHOR_WORKFLOW
