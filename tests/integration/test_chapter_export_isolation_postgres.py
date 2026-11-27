import hashlib
import os

import pytest

from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.chapter_authority.export_delivery import ExportDeliveryRequest, deliver_export
from novel_forge.modules.command_kernel.asset_runtime import AssetCommandContext, create_asset, create_asset_version, reserve_blob
from novel_forge.modules.command_kernel.external_effect_adapters import LocalFileObjectStoreAdapter, MinioObjectStoreExternalEffectAdapter, ProviderResult
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.object_store import MinioObjectStore
from tests.integration.authority_postgres_support import DATABASE_URL, identifier, insert_definition, insert_operation, transaction


def manuscript(project, book, run, text, preparation=None):
    operation, definition = identifier('export'), identifier('definition')
    with transaction() as connection, connection.cursor() as cursor:
        insert_definition(cursor, definition)
        insert_operation(cursor, operation_id=operation, definition_name=definition, project_id=project,
                         status='EXECUTING', command_payload={'book_id':book, 'book_run_id':run,
                         'preparation_report':preparation or {}})
    context = AssetCommandContext(operation, project, 'export-test', identifier('trace'), identifier('correlation'), operation)
    asset = create_asset(DATABASE_URL, context, asset_type='chapter_export')
    digest = 'sha256:' + hashlib.sha256(text.encode()).hexdigest()
    version = create_asset_version(DATABASE_URL, context, asset_id=asset, content={'rendered_text':text},
                                   content_hash=digest, schema_version='export.v1')
    return ExportDeliveryRequest(operation, version, project, context.actor_id, 1, context.trace_id, context.correlation_id), context, digest


@pytest.fixture
def objects(monkeypatch, tmp_path):
    monkeypatch.setenv('NOVEL_FORGE_ENVIRONMENT', 'test')
    if os.environ.get('NOVEL_FORGE_EXPORT_TEST_OBJECT_BACKEND') != 'minio':
        return LocalFileObjectStoreAdapter(tmp_path)
    settings = IndustrialSettings.from_env()
    assert settings.minio_artifact_bucket.startswith('real-prose-'), 'Explicit isolated MinIO bucket required'
    store = MinioObjectStore(settings)
    return MinioObjectStoreExternalEffectAdapter(store.client, bucket=settings.minio_artifact_bucket)


def export(request, objects):
    return deliver_export(DATABASE_URL, request=request, adapter=objects, exercise_unknown_reconciliation=False)


def read_blob(blob, objects):
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute('SELECT object_key,expected_hash,status FROM authority_blob WHERE blob_id=%s', [blob])
        key, digest, status = cursor.fetchone()
    if isinstance(objects, LocalFileObjectStoreAdapter):
        text = (objects.root / key).read_bytes()
    else:
        response = objects.client.get_object(objects.bucket, key)
        try:
            text = response.read()
        finally:
            response.close()
            response.release_conn()
    assert 'sha256:' + hashlib.sha256(text).hexdigest() == digest
    assert status == 'AVAILABLE'
    return key, text


@pytest.mark.parametrize('other_book', [True, False])
def test_same_project_chapter_exports_are_independent(objects, other_book):
    project = identifier('project')
    first, _, _ = manuscript(project, 'book-a', 'run-a', '第一份稿：门外传来三声叩击。')
    second, _, _ = manuscript(project, 'book-b' if other_book else 'book-a', 'run-b', '第二份稿：他把钥匙沉进井里。')
    one = export(first, objects)
    original = read_blob(one.blob_id, objects)
    two = export(second, objects)
    assert one.blob_id != two.blob_id
    assert original[0] != read_blob(two.blob_id, objects)[0]
    assert read_blob(one.blob_id, objects) == original
    replay = export(first, objects)
    assert replay.blob_id == one.blob_id
    assert replay.external_effect_id == one.external_effect_id
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute('SELECT count(*) FROM authority_blob WHERE project_id=%s', [project])
        assert cursor.fetchone()[0] == 2


@pytest.mark.parametrize('preparation', [{}, {'book_edition':{'revision_id':'edition-1'}}, {'author_draft_adoption':{'revision_id':'adoption-1'}}])
def test_existing_reservation_keeps_frozen_key_and_bytes(objects, preparation):
    request, context, digest = manuscript(identifier('project'), 'book-a', 'run-a', '旧稿保持不变。', preparation)
    old_key = f'chapters/{request.project_id}/1/chapter.txt'
    blob = reserve_blob(DATABASE_URL, context, provider=objects.provider, object_key=old_key,
                        expected_hash=digest, expected_size=len('旧稿保持不变。'.encode()), media_type='text/plain')
    evidence = export(request, objects)
    assert evidence.blob_id == blob
    assert read_blob(blob, objects) == (old_key, '旧稿保持不变。'.encode())
    assert export(request, objects).blob_id == blob


def test_lost_upload_receipt_queries_original_object_without_resending(objects, monkeypatch):
    request, _, _ = manuscript(identifier('project'), 'book-a', 'run-a', '上传完成，回执丢失。')
    execute = objects.execute
    calls = []

    def lose_receipt(**kwargs):
        calls.append(kwargs['stable_idempotency_key'])
        result = execute(**kwargs)
        assert result.outcome == 'success'
        return ProviderResult('unknown', result.provider_correlation_id, {'request_sent':True})

    monkeypatch.setattr(objects, 'execute', lose_receipt)
    with pytest.raises(KernelError, match='CHAPTER_EXPORT_DELIVERY_INCOMPLETE'):
        export(request, objects)
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute('SELECT blob_id,object_key,upload_effect_id FROM authority_blob WHERE project_id=%s', [request.project_id])
        original = cursor.fetchone()
    recovered = export(request, objects)
    assert recovered.blob_id == original[0]
    assert recovered.external_effect_id == original[2]
    assert read_blob(recovered.blob_id, objects)[0] == original[1]
    assert len(calls) == 1
    assert export(request, objects).blob_id == original[0]
    assert len(calls) == 1
