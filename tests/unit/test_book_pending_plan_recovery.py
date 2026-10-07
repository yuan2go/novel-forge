from types import SimpleNamespace

import pytest

from novel_forge.modules.book_authority.supervisor import PostgresBookProductionSupervisor, SupervisorAction
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.book_authority.production import BookProductionState
from novel_forge.modules.story_planning_runtime import PlanningGenerationStatus


@pytest.fixture
def supervisor(monkeypatch):
    book = dict(book_run_id='book-run', project_id='project', book_id='book', accepted_through_chapter=0,
                state='PLAN_APPROVAL_PENDING', version=9)
    owner = object.__new__(PostgresBookProductionSupervisor)
    calls = []
    owner.authority = SimpleNamespace(database_url='offline', require=lambda _: dict(book),
        advance_supervisor_checkpoint=lambda *a, **k: calls.append(k) or 'checkpoint')
    owner.principal = object()
    owner._active_plan = lambda *_: None
    pending = [None]
    def current_pending(**_):
        return dict(zip(("status","lifecycle","qualification","approval","content","validation_report"), pending[0])) if pending[0] else None
    owner.query = SimpleNamespace(pending_plan_generation=current_pending)
    return owner, book, pending, calls


@pytest.mark.parametrize('rejected_state', ['REJECTED', 'REPAIR_REQUIRED', 'ADMITTED', 'EXECUTING'])
def test_unfinished_generator_never_creates_approval_checkpoint(rejected_state):
    result = SimpleNamespace(status=PlanningGenerationStatus(rejected_state), generation_operation_id='retained-source')
    with pytest.raises(KernelError, match='BOOK_PLANNING_OWNER_RECOVERY_REQUIRED'):
        PostgresBookProductionSupervisor._require_approval_or_active(result)


@pytest.mark.parametrize('status', ['APPROVAL_PENDING', 'APPROVED'])
def test_waiting_for_real_author_decision_never_regenerates_or_activates(supervisor, status):
    owner, book, pending, checkpoints = supervisor
    pending[0] = (status, 'MATERIALIZED', 'QUALIFIED', 'PENDING', {}, {})
    owner._generate_plan = lambda *_: pytest.fail('Author approval remains required')
    tick = owner._resume_pending_plan(book)
    assert tick.action is SupervisorAction.WAIT_PLAN_APPROVAL
    assert checkpoints == []


def test_current_active_chapter_plan_resumes_exact_book_checkpoint(supervisor):
    owner, book, _, checkpoints = supervisor
    owner._active_plan = lambda _book, scope, _chapter: {'asset_version_id': scope + '-plan'}
    owner._generate_plan = lambda *_: pytest.fail('Current active typed plans already exist')
    result = owner._resume_pending_plan(book)
    assert result.operation_id == 'checkpoint'
    assert checkpoints[0]['target_state'] is BookProductionState.READY
    assert checkpoints[0]['expected_version'] == 9


@pytest.mark.parametrize('status', ['REJECTED', 'REPAIR_REQUIRED', 'EXECUTING', 'ACTIVE'])
def test_generic_rejection_never_becomes_author_approval(supervisor, status):
    owner, book, pending, checkpoints = supervisor
    pending[0] = (status, 'MATERIALIZED', 'PENDING', 'NOT_REQUESTED', {}, {'error_code': 'OTHER_FAILURE'})
    owner._generate_plan = lambda *_: pytest.fail('Generic failures require their own owner recovery')
    with pytest.raises(KernelError, match='BOOK_PLANNING_OWNER_RECOVERY_REQUIRED'):
        owner._resume_pending_plan(book)
    assert checkpoints == []
