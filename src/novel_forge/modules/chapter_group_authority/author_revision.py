from novel_forge.modules.command_kernel.errors import KernelError


def replace_unaccepted_child_reference(uow, *, request, root_operation_id, delegation_id):
    binding = request['command_payload']['preparation_report']['author_book_replacement']
    uow.cursor.execute('''SELECT child.group_run_id,child.status,group_run.active_chapter_request_id
        FROM authority_chapter_group_chapter child JOIN authority_chapter_group_production group_run USING(group_run_id)
        WHERE child.chapter_request_id=%s FOR UPDATE OF child,group_run''', [binding['predecessor_request_id']])
    row = uow.cursor.fetchone()
    if row is None:
        return
    if row[1] == 'ACCEPTED' or row[2] != binding['predecessor_request_id']:
        raise KernelError('CHAPTER_GROUP_AUTHOR_REPLACEMENT_CONFLICT', 'ChapterGroup no longer owns the exact unaccepted predecessor')
    uow.cursor.execute('''UPDATE authority_chapter_group_chapter SET chapter_request_id=%s,child_root_operation_id=%s,
        child_delegation_id=%s,status='DISPATCHED',updated_at=NOW() WHERE group_run_id=%s AND chapter_request_id=%s''',
        [request['chapter_request_id'],root_operation_id,delegation_id,row[0],binding['predecessor_request_id']])
    uow.cursor.execute('''UPDATE authority_chapter_group_production SET active_chapter_request_id=%s,state='CHAPTER_RUNNING',
        failure_reason='',version=version+1,updated_at=NOW() WHERE group_run_id=%s''', [request['chapter_request_id'],row[0]])
