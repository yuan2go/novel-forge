from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from novel_forge.infrastructure.settings import IndustrialSettings


@pytest.mark.parametrize('runner_name', ['run_creation_synthesis', 'run_world_production_smoke'])
def test_native_creation_runners_preserve_isolated_object_store_configuration(monkeypatch, tmp_path, runner_name):
    import scripts.run_creation_synthesis as run_creation_synthesis
    import scripts.run_world_production_smoke as run_world_production_smoke
    runner = run_creation_synthesis if runner_name == 'run_creation_synthesis' else run_world_production_smoke
    values = {
        'NOVEL_FORGE_ENVIRONMENT': 'production',
        'NOVEL_FORGE_DATABASE_URL': 'postgresql://dummy:dummy@127.0.0.1/isolated_pilot_test',
        'NOVEL_FORGE_MINIO_ENDPOINT': 'isolated-storage.invalid:9911',
        'NOVEL_FORGE_MINIO_ACCESS_KEY': 'dummy-pilot-access',
        'NOVEL_FORGE_MINIO_SECRET_KEY': 'dummy-pilot-secret',
        'NOVEL_FORGE_MINIO_SECURE': 'true',
        'NOVEL_FORGE_MINIO_RAW_BUCKET': 'pilot-raw',
        'NOVEL_FORGE_MINIO_ARTIFACT_BUCKET': 'pilot-artifacts',
        'NOVEL_FORGE_MINIO_EXPORT_BUCKET': 'pilot-exports',
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(runner.subprocess, 'check_output', lambda args, **_kw: '' if args[1] == 'status' else 'a' * 40)
    monkeypatch.setattr(runner, 'build_implementation_tree_identity', lambda _root: {'implementation_tree_sha': 'fixture-tree'})
    monkeypatch.setattr(runner, 'validate_configuration', lambda _values, **_kwargs: None)
    import psycopg
    connection = SimpleNamespace(execute=lambda _sql: SimpleNamespace(fetchone=lambda: ('isolated_pilot_test',)))
    monkeypatch.setattr(psycopg, 'connect', lambda *_args, **_kw: nullcontext(connection))
    captured = []
    def capture(settings, **_kwargs):
        captured.append(settings)
        raise RuntimeError('test stops before execution composition')
    monkeypatch.setattr(runner, 'build_production_execution_composition', capture)
    args = ['--expected-sha', 'a' * 40, '--root', str(tmp_path / 'runtime'), '--run-key', 'settings-only',
            '--evidence-dir', str(tmp_path / 'evidence'), '--execute']
    if runner_name == 'run_creation_synthesis':
        monkeypatch.setattr(runner, 'authorize_execution', lambda *_args: {'accounting_basis': 'FIXTURE'})
        monkeypatch.setattr(runner, 'build_trusted_principal_resolver', lambda **_kwargs: Mock())
        monkeypatch.setattr(runner, 'build_content_authority_application', lambda *_args, **_kwargs: None)
        source = Path(__file__).resolve().parents[2] / 'config/production/knowledge-closure'
        args += ['--brief', str(source / 'brief.json'), '--policy', str(source / 'creation.json'),
                 '--formation-policy', str(source / 'formation.json'), '--project-id', 'settings-project', '--book-id', 'settings-book']
    else:
        args += ['--input-snapshot-id', 'settings-snapshot']
    assert runner.main(args) == 2
    assert len(captured) == 1
    settings = captured[0]
    assert isinstance(settings, IndustrialSettings)
    assert Path(settings.root) == (tmp_path / 'runtime').resolve()
    assert settings.database_url == values['NOVEL_FORGE_DATABASE_URL']
    assert settings.environment.value == 'production'
    for field in ('endpoint', 'access_key', 'secret_key', 'raw_bucket', 'artifact_bucket', 'export_bucket'):
        assert getattr(settings, f'minio_{field}') == values[f'NOVEL_FORGE_MINIO_{field.upper()}']
    assert settings.minio_secure is True
    assert values['NOVEL_FORGE_MINIO_SECRET_KEY'] not in ''.join(path.read_text() for path in (tmp_path / 'evidence').iterdir())
