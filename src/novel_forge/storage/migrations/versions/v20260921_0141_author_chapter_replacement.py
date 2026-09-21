from __future__ import annotations

MIGRATION_ID = '20260921_0141_author_chapter_replacement'
DOWN_REVISION = '20260921_0140_prose_editorial_closure'
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = 'append a new author replacement generation; preserve previous Chapter requests, delegations and runs'

UPGRADE_STATEMENTS = [
    '''ALTER TABLE authority_book_chapter_request
       ADD COLUMN generation INTEGER NOT NULL DEFAULT 1 CHECK(generation > 0),
       ADD COLUMN predecessor_request_id TEXT REFERENCES authority_book_chapter_request(chapter_request_id),
       ADD CONSTRAINT authority_book_author_generation_check CHECK((generation=1)=(predecessor_request_id IS NULL))''',
    '''DO $$ DECLARE item RECORD; BEGIN
       FOR item IN SELECT conname FROM pg_constraint
         WHERE conrelid='authority_book_chapter_request'::regclass AND contype='u'
           AND pg_get_constraintdef(oid)='UNIQUE (book_run_id, chapter_number, chapter_plan_version, production_profile_version)'
       LOOP EXECUTE format('ALTER TABLE authority_book_chapter_request DROP CONSTRAINT %I', item.conname); END LOOP;
       END $$''',
    '''ALTER TABLE authority_book_chapter_request ADD CONSTRAINT authority_book_chapter_generation_unique
       UNIQUE(book_run_id,chapter_number,chapter_plan_version,production_profile_version,generation)''',
    'CREATE UNIQUE INDEX authority_book_chapter_one_successor_idx ON authority_book_chapter_request(predecessor_request_id) WHERE predecessor_request_id IS NOT NULL',
    'ALTER TABLE authority_child_delegation ADD COLUMN superseded_at TIMESTAMPTZ',
    'DROP INDEX authority_child_delegation_one_active_owner_idx',
    '''CREATE UNIQUE INDEX authority_child_delegation_one_active_owner_idx ON authority_child_delegation(owner_id)
       WHERE superseded_at IS NULL AND status IN ('DISPATCHED','RUNNING','WAITING_RETRY','SUCCEEDED','CANCELLATION_REQUESTED','UNKNOWN')''',
]
DOWNGRADE_STATEMENTS = []
