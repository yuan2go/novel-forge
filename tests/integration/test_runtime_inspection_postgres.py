from uuid import uuid4

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from novel_forge.cli.runtime_inspection import inspect_runtime
from novel_forge.modules.command_kernel.errors import KernelError
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated, seed_authority_project_book


def test_runtime_inspection_is_scoped_repeatable_and_refuses_a_substitute_database():
    ensure_migrated()
    project = 'runtime-inspection:' + uuid4().hex
    seed_authority_project_book(project_id=project, book_id='book:' + project)
    expected = conninfo_to_dict(DATABASE_URL)['dbname']
    with psycopg.connect(DATABASE_URL) as c, c.cursor() as cur:
        cur.execute('select count(*) from authority_external_effect')
        before = cur.fetchone()[0]
    first = inspect_runtime(DATABASE_URL, project_id=project, expected_database=expected)
    assert first == inspect_runtime(DATABASE_URL, project_id=project, expected_database=expected)
    assert first['books'] == ['book:' + project]
    assert first['provider_dispatches'] == 0 and first['effect_counts'] == {}
    assert first['production_authorization'] == 'NOT_ESTABLISHED_BY_INSPECTION'
    with pytest.raises(KernelError, match='RUNTIME_DATABASE_IDENTITY_MISMATCH'):
        inspect_runtime(DATABASE_URL, project_id=project, expected_database='other')
    with pytest.raises(KernelError, match='RUNTIME_PROJECT_NOT_FOUND'):
        inspect_runtime(DATABASE_URL, project_id='absent:' + uuid4().hex, expected_database=expected)
    with psycopg.connect(DATABASE_URL) as c, c.cursor() as cur:
        cur.execute('select count(*) from authority_external_effect')
        assert cur.fetchone()[0] == before
