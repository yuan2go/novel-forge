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


def test_inspection_separates_settled_ceiling_from_measured_membership_usage():
    from novel_forge.modules.command_kernel.budget_runtime import BudgetReservationRequest, reserve_provider_budget, settle_provider_budget
    from tests.integration.test_provider_budget_runtime_postgres import ProviderBudgetRuntimePostgresTests

    ensure_migrated()
    project = 'runtime-usage:' + uuid4().hex
    seed_authority_project_book(project_id=project, book_id='book:' + project)
    harness = ProviderBudgetRuntimePostgresTests()
    for tokens, basis in ((120, 'PROVIDER_USAGE_RECEIPT'), (900, 'RESERVATION_CEILING')):
        context, effect = harness._effect_for_project(project)
        reservation = reserve_provider_budget(DATABASE_URL, BudgetReservationRequest(
            operation_id=context.operation_id, external_effect_id=effect, project_id=project,
            stable_idempotency_key='usage:' + effect, provider='fake_deterministic_provider',
            currency='UNKNOWN', estimated_amount=None, estimated_tokens=1000,
            accounting_basis='ACCOUNT_ENTITLEMENT', cost_authorization_ref='fixture:member',
            call_caps={'project_total': 2}, token_caps={'project_total': 2000}))
        settle_provider_budget(DATABASE_URL, reservation_id=reservation['reservation_id'], project_id=project,
            actual_amount=None, actual_tokens=tokens, evidence={'usage_settlement_basis': basis,
                'measurement_available': basis == 'PROVIDER_USAGE_RECEIPT', 'fixture': True})
    expected = conninfo_to_dict(DATABASE_URL)['dbname']
    with psycopg.connect(DATABASE_URL) as c:
        before = c.execute('select to_jsonb(r) from authority_budget_reservation r where project_id=%s order by reservation_id', [project]).fetchall()
    report = inspect_runtime(DATABASE_URL, project_id=project, expected_database=expected)
    row = report['budget_reservations'][0]
    assert report['schema_version'] == 'runtime-ledger-inspection.v2'
    assert row['recorded_tokens'] == 1020 and row['measured_tokens'] == 120
    assert row['conservative_estimate_tokens'] == 900 and row['unmeasured_reservations'] == 1
    assert row['cost_status'] == 'UNKNOWN' and row['settled_amount'] is None
    with psycopg.connect(DATABASE_URL) as c:
        assert c.execute('select to_jsonb(r) from authority_budget_reservation r where project_id=%s order by reservation_id', [project]).fetchall() == before
