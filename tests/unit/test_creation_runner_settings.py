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
        source = Path(__file__).resolve().parents[2] / 'tests/fixtures/creation/knowledge-closure'
        args += ['--input-source', 'HISTORICAL_TEST_SAMPLE', '--input-purpose', 'ENGINEERING_REGRESSION', '--brief', str(source / 'brief.json'), '--policy', str(source / 'creation.json'),
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


def test_native_creation_content_identity_survives_input_file_move(tmp_path, monkeypatch):
    import json
    from novel_forge.cli.authority import _authority_parser
    from novel_forge.cli.creation import run_creation_command
    from novel_forge.api import authority_dependencies
    from novel_forge.modules.book_authority import creation_runtime
    principal = SimpleNamespace(principal_id='current-author')
    monkeypatch.setattr(authority_dependencies, 'build_trusted_principal_resolver',
        lambda: SimpleNamespace(resolve_api_principal=lambda: principal))
    monkeypatch.setattr(creation_runtime, 'execute_creation_command',
        lambda _settings, args: {'book_id': args.book_id, 'idempotency_key': args.idempotency_key})
    parser = _authority_parser()
    current, moved = tmp_path / 'current.json', tmp_path / 'moved.json'
    current.write_text(json.dumps({'idea': 'A cook must price a failed pastry'}))
    moved.write_bytes(current.read_bytes())
    def start(path):
        return run_creation_command(None, parser.parse_args(['authority-creation', 'start', '--input-file', str(path)]))
    assert start(current) == start(moved)
    moved.write_text(json.dumps({'idea': 'Sisters rehearse a play'}))
    assert start(current) != start(moved)
    with pytest.raises(ValueError, match='--input-file'):
        run_creation_command(None, parser.parse_args(['authority-creation', 'start']))


def test_synthesis_preview_freezes_explicit_generated_parent_without_provider(tmp_path):
    import json
    from scripts.run_creation_synthesis import main
    source = Path(__file__).resolve().parents[2] / 'tests/fixtures/creation/knowledge-closure'
    output = tmp_path / 'preview'
    digest = 'sha256:' + 'd' * 64
    assert main(['--brief', str(source / 'brief.json'), '--policy', str(source / 'creation.json'),
        '--formation-policy', str(source / 'formation.json'), '--project-id', 'current-project',
        '--book-id', 'current-book', '--root', str(tmp_path), '--run-key', 'derived-case',
        '--evidence-dir', str(output), '--input-source', 'TASK_GENERATED',
        '--input-purpose', 'CREATIVE_EVALUATION', '--intent-ref', 'current-task',
        '--parent-input-version', 'brief:current', '--parent-input-hash', digest]) == 0
    report = json.loads((output / 'creation-run.json').read_bytes())
    assert report['input_selection']['parent_input'] == {'asset_version_id': 'brief:current', 'content_hash': digest}
    assert report['real_provider'] == 'NOT_RUN'
