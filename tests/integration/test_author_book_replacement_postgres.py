from dataclasses import replace

import pytest

from novel_forge.modules.book_authority.author_revision import replace_author_chapter
from novel_forge.modules.chapter_authority.author_editor import ChapterAuthorEditingApplication, text_hash
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL, identifier
from tests.integration import test_book_to_chapter_authority_vertical_postgres as native_book
from tests.integration import test_chapter_group_authority_postgres as native_group
from novel_forge.modules.chapter_group_authority import StartChapterGroupCommand


def unaccepted_author_fixture(*, finish=True, group=False):
    if group:
        helper=native_group.ChapterGroupAuthorityPostgresTests()
        fixture=helper._fixture(group_chapters=1)
        fixture['authority']=fixture['book_authority']
        started=fixture['group_authority'].start(StartChapterGroupCommand(
            project_id=fixture['project_id'],workspace_id='workspace:'+fixture['project_id'],
            actor_id=fixture['principal'].principal_id,trace_id=identifier('group-trace'),correlation_id=identifier('correlation'),
            stable_idempotency_key=identifier('group'),book_run_id=fixture['book'].book_run_id,
            group_plan_version_id=fixture['group_plan']['asset_version_id'],group_plan_content_hash=fixture['group_plan']['content_hash']),principal=fixture['principal'])
        fixture['group_run_id']=started['group_run_id']
        running=fixture['group_authority'].dispatch(started['group_run_id'],helper._chapter_command(fixture,1),principal=fixture['principal'])
        delegated=fixture['authority'].require_chapter_request(running['active_chapter_request_id'])
    else:
        helper = native_book.BookToChapterAuthorityVerticalPostgresTests()
        fixture = helper._new_book_fixture(target_chapter_count=1)
        delegated = fixture['authority'].submit_chapter(helper._chapter_command(fixture, chapter_number=1), principal=fixture['principal'])
    if finish:
        helper._run_child(fixture, delegated['chapter_root_operation_id'])
        fixture['authority'].reconcile_chapter(delegated['chapter_request_id'])
    else:
        scheduler = fixture['chapter'].scheduler(principal=fixture['worker'])
        for _ in range(16):
            tick = scheduler.tick(project_id=fixture['project_id'], root_operation_id=delegated['chapter_root_operation_id'])
            if tick.node == 'draft':
                break
        else:
            raise AssertionError('fixture did not reach Draft')
    draft = next(item for item in fixture['chapter'].query.require_acceptance_evidence(project_id=fixture['project_id'],root_operation_id=delegated['chapter_root_operation_id'])['outputs'] if item['asset_type']=='draft_chapter')
    principal = replace(fixture['principal'],permissions=fixture['principal'].permissions|{'chapter.authority.query'})
    app = ChapterAuthorEditingApplication(DATABASE_URL,application_build_id='author-replacement-fixture',commit_sha='e'*40)
    scope = dict(project_id=fixture['project_id'],workspace_id='workspace:'+fixture['project_id'],book_id='book:'+fixture['project_id'],chapter=1,
        base_asset_version_id=draft['asset_version_id'],base_asset_hash=draft['content_hash'],base_text_hash=text_hash(draft['content']['text']))
    text = draft['content']['text'] + ' 她收住脚步。'
    saved = app.execute(action='save',payload={**scope,'expected_version':0,'text':text,'rights_basis':'ORIGINAL_AUTHOR_INPUT'},
        idempotency_key=identifier('save'),principal=principal)
    adopted = app.execute(action='accept',payload={**scope,'expected_version':saved['version'],'candidate_asset_version_id':saved['candidate_asset_version_id'],
        'rationale':'核对动作后采用精确作者输入'},idempotency_key=identifier('adopt'),principal=principal)
    return helper,fixture,delegated,principal,scope,text,saved,adopted


def replacement_args(fixture,delegated,principal,saved,adopted):
    return dict(chapter_request_id=delegated['chapter_request_id'],expected_book_version=fixture['authority'].require(fixture['book'].book_run_id)['version'],
        expected_root_operation_id=delegated['chapter_root_operation_id'],candidate_asset_version_id=saved['candidate_asset_version_id'],
        decision_asset_version_id=adopted['decision_asset_version_id'],idempotency_key=identifier('author-review'),principal=principal)


def test_native_book_author_replacement_recovers_unlinked_admission_then_accepts_exact_new_run():
    helper,fixture,previous,principal,scope,text,saved,adopted = unaccepted_author_fixture()
    try:
        authority = fixture['authority']
        arguments = replacement_args(fixture,previous,principal,saved,adopted)
        faults=[]
        def lose_after_admission(point):
            if point=='after_author_replacement_admission' and not faults:
                faults.append(point)
                raise RuntimeError('lost response before Book replacement link')
        authority.failure_injector=lose_after_admission
        with pytest.raises(RuntimeError,match='lost response'):
            replace_author_chapter(authority,**arguments)
        pending = authority.require(fixture['book'].book_run_id)['active_chapter_request_id']
        assert pending != previous['chapter_request_id']
        reserved = authority.require_chapter_request(pending)
        assert not reserved['chapter_root_operation_id']
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("SELECT operation_id FROM authority_operation WHERE project_id=%s AND definition_name='chapter.slice.run' AND command_payload#>>'{preparation_report,author_book_replacement,chapter_request_id}'=%s",[scope['project_id'],pending])
            unlinked = uow.cursor.fetchone()[0]
        with pytest.raises(KernelError,match='BOOK_AUTHOR_REPLACEMENT_UNLINKED'):
            fixture['chapter'].scheduler(principal=fixture['worker']).tick(project_id=scope['project_id'],root_operation_id=unlinked)
        authority.failure_injector=None
        linked=authority.recover_chapter_submission(pending,principal=principal)
        assert linked['chapter_root_operation_id']==unlinked
        replay=replace_author_chapter(authority,**arguments)
        assert replay['chapter_root_operation_id']==unlinked
        with pytest.raises(KernelError,match='BOOK_CHAPTER_SUPERSEDED'):
            authority.accept_chapter(previous['chapter_request_id'],principal=principal)
        helper._run_child(fixture,unlinked)
        outputs=fixture['chapter'].query.require_acceptance_evidence(project_id=scope['project_id'],root_operation_id=unlinked)['outputs']
        assert next(item['content']['text'] for item in outputs if item['asset_type']=='draft_chapter')==text
        authority.reconcile_chapter(pending)
        authority.accept_chapter(pending,principal=principal)
        book=authority.require(fixture['book'].book_run_id)
        assert book['accepted_through_chapter']==1
        assert replace_author_chapter(authority,**arguments)['chapter_root_operation_id']==unlinked
        assert authority.require_chapter_request(previous['chapter_request_id'])['chapter_root_operation_id']==previous['chapter_root_operation_id']
        assert AuthorityAssetQuery(DATABASE_URL).require(project_id=scope['project_id'],asset_version_id=scope['base_asset_version_id']).content['text']!=text
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute('SELECT status,superseded_at FROM authority_child_delegation WHERE chapter_request_id=%s',[previous['chapter_request_id']])
            row=uow.cursor.fetchone()
            assert row[0]=='SUCCEEDED' and row[1] is not None
            uow.cursor.execute('SELECT chapter_request_id FROM authority_book_chapter_acceptance WHERE book_run_id=%s',[book['book_run_id']])
            assert uow.cursor.fetchall()==[(pending,)]
            uow.cursor.execute('SELECT count(*) FROM authority_external_effect e JOIN authority_operation o USING(operation_id) WHERE o.root_operation_id=%s AND e.capability=%s',[unlinked,'model.draft'])
            assert uow.cursor.fetchone()[0]==0
    finally:
        helper.doCleanups()


def test_author_replacement_rejects_stale_book_and_unsettled_predecessor():
    helper,fixture,previous,principal,scope,text,saved,adopted=unaccepted_author_fixture(finish=False)
    try:
        arguments=replacement_args(fixture,previous,principal,saved,adopted)
        with pytest.raises(KernelError,match='BOOK_AUTHOR_REPLACEMENT_CONFLICT'):
            replace_author_chapter(fixture['authority'],**{**arguments,'expected_book_version':arguments['expected_book_version']-1})
        with pytest.raises(KernelError,match='BOOK_AUTHOR_PREDECESSOR_NOT_SETTLED'):
            replace_author_chapter(fixture['authority'],**{**arguments,'idempotency_key':identifier('unsettled')})
        assert fixture['authority'].require(fixture['book'].book_run_id)['active_chapter_request_id']==previous['chapter_request_id']
    finally:
        helper.doCleanups()


def test_author_replacement_cannot_resume_paused_or_aborted_book():
    helper,fixture,previous,principal,scope,text,saved,adopted=unaccepted_author_fixture(finish=False)
    try:
        authority=fixture['authority']
        authority.pause(fixture['book'].book_run_id,reason='author pauses production',principal=principal)
        with pytest.raises(KernelError,match='BOOK_AUTHOR_REPLACEMENT_STATE_BLOCKED'):
            replace_author_chapter(authority,**replacement_args(fixture,previous,principal,saved,adopted))
        authority.cancel(fixture['book'].book_run_id,reason='author cancels production',principal=principal)
        with pytest.raises(KernelError,match='BOOK_AUTHOR_REPLACEMENT_STATE_BLOCKED'):
            replace_author_chapter(authority,**replacement_args(fixture,previous,principal,saved,adopted))
        assert authority.require(fixture['book'].book_run_id)['state']=='ABORTED'
        assert authority.require(fixture['book'].book_run_id)['active_chapter_request_id']==previous['chapter_request_id']
    finally:
        helper.doCleanups()


def test_author_replacement_rebinds_native_group_before_group_acceptance():
    helper,fixture,previous,principal,scope,text,saved,adopted=unaccepted_author_fixture(group=True)
    try:
        authority=fixture['authority']
        replacement=replace_author_chapter(authority,**replacement_args(fixture,previous,principal,saved,adopted))
        group=fixture['group_authority'].require(fixture['group_run_id'])
        assert group['active_chapter_request_id']==replacement['chapter_request_id']
        helper._run_child(fixture,replacement['chapter_root_operation_id'])
        accepted=fixture['group_authority'].reconcile_and_accept(fixture['group_run_id'],principal=principal)
        assert accepted['accepted_through_chapter']==1
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute('SELECT chapter_request_id,child_root_operation_id,status FROM authority_chapter_group_chapter WHERE group_run_id=%s',[fixture['group_run_id']])
            assert uow.cursor.fetchone()==(replacement['chapter_request_id'],replacement['chapter_root_operation_id'],'ACCEPTED')
    finally:
        helper.doCleanups()
