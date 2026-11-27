from datetime import datetime, timezone

import pytest
from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.attempt_runtime import create_attempt
from novel_forge.modules.command_kernel.deadline_runtime import probe_operation_execution
from novel_forge.modules.command_kernel.errors import KernelError
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated, identifier, insert_definition, transaction


def seed(capabilities):
    ensure_migrated()
    definition, operation, project = (identifier(value) for value in ("definition", "operation", "project"))
    with transaction() as connection, connection.cursor() as cursor:
        insert_definition(cursor, definition)
        cursor.execute("""INSERT INTO authority_operation(operation_id,definition_name,definition_version,
            project_id,status,root_operation_id,idempotency_scope,idempotency_key,request_digest,
            command_payload,definition_snapshot,completion_contract_snapshot,policy_snapshot,business_deadline_at)
            VALUES(%s,%s,'1.0.0',%s,'READY',%s,%s,%s,%s,'{}',%s,'{}','{}',%s)""",
            [operation, definition, project, operation, project, operation, operation,
             Jsonb({"external_capabilities": capabilities}), datetime(2000, 1, 1, tzinfo=timezone.utc)])
        for number in (1, 2):
            cursor.execute("""INSERT INTO authority_attempt(attempt_id,operation_id,attempt_number,max_attempts,status)
                VALUES(%s,%s,%s,1,'FAILED_FINAL')""", [identifier("attempt"), operation, number])
    return operation, project


def test_old_model_deadline_and_attempt_ceiling_are_observations():
    operation, project = seed(["model.draft"])
    assert probe_operation_execution(DATABASE_URL, operation_id=operation, project_id=project)["status"] == "READY"
    result = create_attempt(DATABASE_URL, operation_id=operation, project_id=project,
        max_attempts=1, trace_id="trace", correlation_id="correlation")
    assert result["attempt_number"] == 3
    assert not result["dead_letter"]
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute('SELECT attempt_number,max_attempts,status FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number', [operation])
        assert cursor.fetchall() == [(1, 1, "FAILED_FINAL"), (2, 1, "FAILED_FINAL"), (3, 1, "CREATED")]
        cursor.execute('SELECT business_deadline_at FROM authority_operation WHERE operation_id=%s', [operation])
        assert cursor.fetchone()[0].year == 2000


def test_non_generation_deadline_and_cumulative_limit_are_preserved():
    operation, project = seed(["external.publish"])
    with pytest.raises(KernelError, match="OPERATION_BUSINESS_TIMEOUT"):
        probe_operation_execution(DATABASE_URL, operation_id=operation, project_id=project)
    result = create_attempt(DATABASE_URL, operation_id=operation, project_id=project,
        max_attempts=1, trace_id="trace", correlation_id="correlation")
    assert result["dead_letter"]


@pytest.mark.parametrize("mode", ["model", "coordinated", "author_first", "working_revision"])
def test_native_chapter_root_ignores_deadline_before_first_model_child(mode):
    from novel_forge.modules.chapter_authority.contracts import ChapterNode
    from novel_forge.modules.chapter_authority.definitions import chapter_root_operation_definition
    from novel_forge.modules.chapter_authority.working_revision import working_revision_definition
    from novel_forge.modules.command_kernel.deadline_runtime import scan_expired_operation_deadlines
    from novel_forge.modules.command_kernel.generation_policy import generation_graph
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork

    root, project = seed([])
    definition = chapter_root_operation_definition(application_build_id="native-deadline-proof",
        commit_sha="f" * 40, model_effects_required=True, coordinated_contract=mode != "model")
    if mode == "author_first":
        from novel_forge.modules.book_authority.manuscript import AUTHOR_ROOT_VERSION, AUTHOR_WORKFLOW
        nodes = tuple(ChapterNode)[:tuple(ChapterNode).index(ChapterNode.DRAFT) + 1]
        definition["definition_version"] = AUTHOR_ROOT_VERSION
        definition["policy"].update(expected_saga_steps=len(nodes), author_workflow=AUTHOR_WORKFLOW)
        definition["completion_contract"]["required_child_operations"] = [
            {"definition_name": node.definition_name, "allowed_states": ["SUCCEEDED"]} for node in nodes]
    elif mode == "working_revision":
        definition = working_revision_definition(application_build_id="native-deadline-proof", commit_sha="f" * 40)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.repositories.definitions.register(definition)
        stored = uow.repositories.definitions.get(definition["name"], definition["definition_version"])
        uow.cursor.execute("""UPDATE authority_operation SET definition_name=%s,definition_version=%s,
            definition_snapshot=%s,workspace_id=%s WHERE operation_id=%s""",
            [stored["name"], stored["definition_version"], Jsonb(stored), "workspace:" + project, root])
        assert generation_graph(uow.cursor, root, project)
        uow.repositories.operation_graph.start_saga(saga_id=identifier("native-saga"), root_operation_id=root,
            project_id=project, trace_id="trace", correlation_id="correlation")
        assert generation_graph(uow.cursor, root, project)
        uow.commit()
    observed = probe_operation_execution(DATABASE_URL, operation_id=root, project_id=project)
    assert observed["business_deadline_at"].year == 2000
    assert create_attempt(DATABASE_URL, operation_id=root, project_id=project,
        max_attempts=1, trace_id="trace", correlation_id="correlation")["attempt_number"] == 3
    assert root not in scan_expired_operation_deadlines(DATABASE_URL,
        actor_id="native-chapter-deadline-proof", limit=1000)["cancellation_issued"]


def test_expired_generation_does_not_starve_infrastructure_deadline_scan():
    from novel_forge.modules.command_kernel.deadline_runtime import scan_expired_operation_deadlines
    generation, generation_project = seed(["model.draft"])
    infrastructure, infrastructure_project = seed(["external.publish"])
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE authority_operation SET business_deadline_at='0100-01-01' WHERE operation_id=%s", [generation])
        cursor.execute("UPDATE authority_operation SET business_deadline_at='0101-01-01' WHERE operation_id=%s", [infrastructure])
    report = scan_expired_operation_deadlines(DATABASE_URL, actor_id="deadline-pagination-fixture", limit=1)
    assert report["cancellation_issued"] == [infrastructure]
    assert report["expired_count"] >= 2
    assert probe_operation_execution(DATABASE_URL, operation_id=generation, project_id=generation_project)["status"] == "READY"
    with pytest.raises(KernelError, match="OPERATION_CANCELLATION_REQUESTED"):
        probe_operation_execution(DATABASE_URL, operation_id=infrastructure, project_id=infrastructure_project)


def test_model_graph_parent_survives_expired_deadline_and_attempt_observations():
    from novel_forge.modules.command_kernel.deadline_runtime import scan_expired_operation_deadlines
    root, project = seed([])
    child, definition = identifier("child"), identifier("model-definition")
    with transaction() as connection, connection.cursor() as cursor:
        insert_definition(cursor, definition)
        cursor.execute("""INSERT INTO authority_operation(operation_id,definition_name,definition_version,
            project_id,status,root_operation_id,idempotency_scope,idempotency_key,request_digest,
            command_payload,definition_snapshot,completion_contract_snapshot,policy_snapshot,business_deadline_at)
            VALUES(%s,%s,'1.0.0',%s,'READY',%s,%s,%s,%s,'{}',%s,'{}','{}',%s)""",
            [child, definition, project, root, project, child, child,
             Jsonb({"external_capabilities": ["model.draft"]}), datetime(2000, 1, 1, tzinfo=timezone.utc)])
    assert probe_operation_execution(DATABASE_URL, operation_id=root, project_id=project)["status"] == "READY"
    attempt = create_attempt(DATABASE_URL, operation_id=root, project_id=project,
        max_attempts=1, trace_id="trace", correlation_id="correlation")
    assert attempt["attempt_number"] == 3 and not attempt["dead_letter"]
    report = scan_expired_operation_deadlines(DATABASE_URL, actor_id="deadline-fixture", limit=1000)
    assert root not in report["cancellation_issued"] and child not in report["cancellation_issued"]


def test_recovery_finds_each_completed_context_chunk_before_selecting_latest(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from novel_forge.modules.chapter_authority import receipt_recovery
    from novel_forge.modules.chapter_authority.contracts import ChapterHandlerRequest
    ensure_migrated()
    with transaction() as connection, connection.cursor() as cursor:
        for table in ('authority_operation', 'authority_attempt', 'authority_external_effect'):
            cursor.execute(f'CREATE TEMP TABLE {table} AS SELECT * FROM public.{table} WITH NO DATA')
        cursor.execute("INSERT INTO authority_operation(operation_id,project_id,workspace_id,actor_id,trace_id,correlation_id) VALUES ('op','p','w','actor','trace','root')")
        cursor.execute("INSERT INTO authority_attempt(attempt_id,operation_id,attempt_number,status) VALUES ('old','op',1,'FAILED_RETRYABLE')")
        for index in (1, 2):
            cursor.execute("INSERT INTO authority_external_effect(external_effect_id,request_hash,request_payload,operation_id,project_id,status,effect_type,created_at) VALUES (%s,'hash',%s,'op','p','SUCCEEDED','model.invoke',to_timestamp(%s))",
                ['chunk'+str(index), Jsonb({'stage': 'context_compress', 'input': {'chunk': index},
                    '_production_execution': {'attempt_id': 'old', 'book_id': 'book'}}), index])
        uow = SimpleNamespace(cursor=cursor, repositories=SimpleNamespace(external_effects=None))
        monkeypatch.setattr(receipt_recovery, 'AuthorityUnitOfWork', lambda *args: nullcontext(uow))
        seen = []
        def verified(_uow, _repository, _context, effect_id, **kwargs):
            seen.append(effect_id)
            return {'budget_reservation_status': 'HELD_UNKNOWN', 'budget_reservation_id': 'reservation:' + effect_id,
                'budget_reserved_amount': None, 'budget_estimated_tokens': 0, 'provider_capability_profile': {}, 'provider_evidence': {
                'result': {'text': effect_id}, 'provider_id': 'fixture', 'model_id': 'fixture',
                'prompt_version': 'fixture', 'skill_version': 'fixture', 'real_model_call': False,
                'usage': {'availability': 'UNAVAILABLE', 'measurement': 'UNKNOWN'},
                'cost': {'availability': 'UNAVAILABLE', 'measurement': 'UNKNOWN', 'currency': 'UNKNOWN'}}}
        monkeypatch.setattr(receipt_recovery, '_read_verified_success', verified)
        request = ChapterHandlerRequest('op', 'p', 'w', 'trace', 'root', {'book_id': 'book'}, (), attempt_id='new', database_url=DATABASE_URL)
        for index in (1, 2):
            result = receipt_recovery.consume_completed_generation_result(request, stage='context_compress', payload={'chunk': index})
            assert result.output['text'] == 'chunk'+str(index)
        assert seen == ['chunk1', 'chunk2']


@pytest.mark.parametrize("error,stage,version,working,reuse", [
    ("REVIEW_RESOLUTION_CHECKS_REQUIRED", "rereview", "3.10.0", True, False),
    ("REVIEW_RESOLUTION_CHECKS_REQUIRED", "rereview", "3.9.4", True, True),
    ("REVIEW_RESOLUTION_CHECKS_REQUIRED", "rereview", "3.10.0", False, True),
    ("REVIEW_RESOLUTION_CHECKS_REQUIRED", "revision", "3.10.0", True, True),
    ("PROGRAMMING_BUG", "rereview", "3.10.0", True, True),
    ("DELIVERY_COORDINATION_FAILED", "revision", "3.10.0", True, True),
])
def test_known_invalid_working_rereview_does_not_reconsume_foreign_ledger_result(monkeypatch, error, stage, version, working, reuse):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from novel_forge.modules.chapter_authority import receipt_recovery
    from novel_forge.modules.chapter_authority.contracts import ChapterHandlerRequest
    ensure_migrated()
    with transaction() as connection, connection.cursor() as cursor:
        for table in ('authority_operation', 'authority_attempt', 'authority_external_effect'):
            cursor.execute(f'CREATE TEMP TABLE {table} AS SELECT * FROM public.{table} WITH NO DATA')
        cursor.execute("INSERT INTO authority_operation(operation_id,project_id,workspace_id,actor_id,trace_id,correlation_id) VALUES ('ledger-op','p','w','actor','trace','root')")
        cursor.execute("INSERT INTO authority_attempt(attempt_id,operation_id,attempt_number,status,result) VALUES ('old','ledger-op',1,'FAILED_RETRYABLE',%s)", [Jsonb({'error_code': error})])
        payload = {'review': {'issues': []}, 'revision': {'text': '完整已保存的修订稿'}}
        cursor.execute("INSERT INTO authority_external_effect(external_effect_id,request_hash,request_payload,operation_id,project_id,status,effect_type) VALUES ('retained-ledger','original-hash',%s,'ledger-op','p','SUCCEEDED','model.invoke')",
            [Jsonb({'stage': stage, 'input': payload, '_production_execution': {'attempt_id': 'old', 'book_id': 'book'}})])
        cursor.execute("SELECT to_jsonb(a) FROM authority_attempt a")
        original_attempt = cursor.fetchone()[0]
        cursor.execute("SELECT to_jsonb(e) FROM authority_external_effect e")
        original_effect = cursor.fetchone()[0]
        uow = SimpleNamespace(cursor=cursor, repositories=SimpleNamespace(external_effects=None))
        monkeypatch.setattr(receipt_recovery, 'AuthorityUnitOfWork', lambda *args: nullcontext(uow))
        seen = []
        def verified(_uow, _repository, _context, effect_id, **kwargs):
            seen.append(effect_id)
            return {'budget_reservation_status': 'SETTLED', 'provider_evidence': {
                'result': {'resolution_checks': []}, 'provider_id': 'fixture', 'model_id': 'fixture',
                'prompt_version': 'fixture', 'skill_version': 'fixture', 'real_model_call': False,
                'usage': {'availability': 'UNAVAILABLE', 'measurement': 'UNKNOWN'},
                'cost': {'availability': 'UNAVAILABLE', 'measurement': 'UNKNOWN', 'currency': 'UNKNOWN'}}}
        monkeypatch.setattr(receipt_recovery, '_read_verified_success', verified)
        command = {'book_id': 'book', **({'preparation_report': {'working_revision': {'contract_version': 'chapter-working-revision.v1'}}} if working else {})}
        request = ChapterHandlerRequest('ledger-op', 'p', 'w', 'trace', 'root', command, (),
            attempt_id='new', database_url=DATABASE_URL, definition_version=version)
        result = receipt_recovery.consume_completed_generation_result(request, stage=stage, payload=payload)
        assert (result is not None) is reuse
        assert seen == (['retained-ledger'] if reuse else [])
        cursor.execute("SELECT to_jsonb(a) FROM authority_attempt a")
        assert cursor.fetchone()[0] == original_attempt
        cursor.execute("SELECT to_jsonb(e) FROM authority_external_effect e")
        assert cursor.fetchone()[0] == original_effect


def test_completed_revalidation_graph_preserves_unknown_cost_and_rejects_live_outcomes():
    from novel_forge.modules.command_kernel.step_successor_v2 import _require_reconciled_graph
    ensure_migrated()
    with transaction() as connection, connection.cursor() as cursor:
        for table in ('authority_operation', 'authority_external_effect', 'authority_budget_reservation',
                      'authority_attempt', 'authority_lease_acquisition', 'authority_cancellation_command'):
            cursor.execute(f'CREATE TEMP TABLE {table} AS SELECT * FROM public.{table} WITH NO DATA')
        cursor.execute("INSERT INTO authority_operation(operation_id,project_id,root_operation_id) VALUES ('root','p','root'),('source','p','root')")
        cursor.execute("INSERT INTO authority_external_effect(external_effect_id,operation_id,status) VALUES ('retained','source','SUCCEEDED')")
        cursor.execute("INSERT INTO authority_budget_reservation(external_effect_id,status) VALUES ('retained','HELD_UNKNOWN')")
        _require_reconciled_graph(cursor, root_id='root', predecessor_id='source', completed_receipts=(('retained','hash'),))
        cursor.execute("SELECT status FROM authority_budget_reservation WHERE external_effect_id='retained'")
        assert cursor.fetchone() == ('HELD_UNKNOWN',)
        for status in ('UNKNOWN', 'DISPATCHING', 'PENDING'):
            cursor.execute("UPDATE authority_external_effect SET status=%s WHERE external_effect_id='retained'", [status])
            with pytest.raises(KernelError, match='STEP_SUCCESSOR_GRAPH_UNRECONCILED'):
                _require_reconciled_graph(cursor, root_id='root', predecessor_id='source', completed_receipts=(('retained','hash'),))


def test_canon_reextraction_keeps_complete_result_after_historical_deadline():
    from novel_forge.modules.canon_graph.approval_authority import CanonApprovalContext, advance_canon_reextraction
    root, project = seed(["model.canon_extract"])
    saga, generation, asset, version = (identifier(value) for value in ("saga","reextraction","asset","version"))
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute("INSERT INTO authority_saga(saga_id,root_operation_id,project_id,status,trace_id,correlation_id) VALUES(%s,%s,%s,'RUNNING','trace','correlation')",[saga,root,project])
        cursor.execute("INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES(%s,%s,'canon_extraction')",[asset,project])
        cursor.execute("INSERT INTO authority_asset_version(asset_version_id,asset_id,version_number,lifecycle,eligibility,governance,content,content_hash,schema_version) VALUES(%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,'synthetic-canon-fixture.v1')",
            [version,asset,Jsonb({"synthetic":True,"facts":[]}),"sha256:"+"a"*64])
        cursor.execute("""INSERT INTO authority_canon_reextraction_generation(reextraction_generation_id,project_id,root_operation_id,
            saga_id,generation,status,supersedes_proposal_asset_version_id,invalidation_reason,created_by_decision_asset_version_id,deadline_at)
            VALUES(%s,%s,%s,%s,100,'EXTRACTION_RUNNING',%s,'controlled verification',%s,'2000-01-01')""",
            [generation,project,root,saga,version,version])
    context = CanonApprovalContext(project,"operator","trace","correlation")
    result = advance_canon_reextraction(DATABASE_URL,context,generation_id=generation,
        expected_status="EXTRACTION_RUNNING",target_status="PROPOSAL_PENDING",extraction_operation_id=root,extraction_asset_version_id=version)
    assert result == "PROPOSAL_PENDING"
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT status,extraction_asset_version_id,extraction_digest,escalation_reason,deadline_at FROM authority_canon_reextraction_generation WHERE reextraction_generation_id=%s",[generation])
        row = cursor.fetchone()
        assert row[:4] == ("PROPOSAL_PENDING",version,"sha256:"+"a"*64,"")
        assert row[4].year == 2000
        cursor.execute("SELECT content FROM authority_asset_version WHERE asset_version_id=%s",[version])
        assert cursor.fetchone()[0] == {"synthetic":True,"facts":[]}
