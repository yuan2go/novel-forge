"""TEST: Native import admission, scoped keyset queries and bounded query measurements."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tracemalloc
from uuid import uuid4

import psycopg
import pytest

from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.project_authority import (
    ProjectAuthorityApplication,
    ProjectAuthorityCommand,
)
from novel_forge.modules.source_import.corpus_ingestion.contracts import IngestionManifest
from novel_forge.modules.source_import.query import SourceImportQuery
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.test_corpus_ingestion_postgres import _manifest, _runtime

pytest_plugins = ["tests.integration.test_corpus_foundation_postgres"]
BASE = "/product/source-imports"


def _input(tmp_path):
    path = tmp_path / "original.jsonl"
    path.write_text("\n".join(json.dumps({
        "book": "original-query-fixture", "chapter": str(n), "order": n,
        "text": "Original query fixture; no analysis is requested.",
    }) for n in (1, 2)))
    return _manifest(path)


def _enqueue(corpus, manifest, run_key, *, project=None, workspace=None):
    response = corpus.client.post(BASE + "/corpus", json={
        "project_id": project or corpus.project,
        "workspace_id": workspace or corpus.workspace,
        "run_key": run_key, "manifest": manifest,
    })
    assert response.status_code == 202, response.text
    return response.json()["import_job_id"]


def _page(corpus, **params):
    response = corpus.client.get(BASE, params={"project_id": corpus.project, **params})
    assert response.status_code == 200, response.text
    return response.json()


def _ids(rows):
    return [row["import_job_id"] for row in rows]


def _cli(corpus, *args, scope=None):
    env = {**os.environ, "NOVEL_FORGE_DATABASE_URL": DATABASE_URL,
           "NOVEL_FORGE_STORAGE_AUTHORITY": "postgresql"}
    if scope is not None:
        env["NOVEL_FORGE_AUTHORITY_PROJECT_SCOPE"] = scope
    return subprocess.run([
        sys.executable, "-c", "from novel_forge.cli.authority import main; raise SystemExit(main())",
        "corpus", "jobs", "--project-id", corpus.project, *args,
    ], text=True, capture_output=True, check=False, env=env)


def test_native_jobs_keyset_literal_batches_filters_and_cli(corpus, tmp_path, monkeypatch):
    app, _ = _runtime(tmp_path, monkeypatch)
    manifest = _input(tmp_path)
    principal = build_trusted_principal_resolver().resolve_api_principal()
    admitted = []
    # WHY: Native commands share PostgreSQL transaction time, without rewriting job timestamps.
    with AuthorityUnitOfWork(DATABASE_URL, coordinate_nested=True) as uow:
        for key in ("batch%_a/1", "batch%_a/2", "batchZZa/1", "batchZZa/2"):
            admitted.append(app.create_corpus_import(
                project_id=corpus.project, workspace_id=corpus.workspace,
                manifest=IngestionManifest.model_validate(manifest),
                mode="PREVIEW" if key.endswith("/2") else "IMPORT",
                run_key=key, actor_id=principal.principal_id, principal=principal,
            )["import_job_id"])
        uow.commit()
    git = corpus.client.post(BASE, json={
        "project_id": corpus.project, "workspace_id": corpus.workspace,
        "source": {"type": "github_repository", "repository": "https://github.com/fixture/not-fetched",
                   "ref": "batch%_a/not-a-run-key"},
        "rights_authorization": "owned", "copyright_boundary": "Synthetic fixture admission only; no fetch or model",
        "idempotency_key": "separate-git-job",
    })
    assert git.status_code == 202, git.text
    git_id = git.json()["import_job_id"]
    full = _page(corpus, limit=10)
    assert _ids(full) == [git_id, *sorted(admitted)]
    assert len({row["created_at"] for row in full if row["import_job_id"] in admitted}) == 1
    pages, after = [], ""
    while page := _page(corpus, limit=2, after=after):
        pages.extend(page)
        after = page[-1]["import_job_id"]
    assert pages == full
    assert len(set(_ids(pages))) == 5
    assert set(_ids(_page(corpus, run_key_prefix="batch%_a/"))) == set(admitted[:2])
    assert {row["mode"] for row in _page(corpus, run_key_prefix="batch%_a/")} == {"IMPORT", "PREVIEW"}
    assert set(_ids(_page(corpus, run_key_prefix="batchZZa/"))) == set(admitted[2:])
    assert _ids(_page(corpus, source_type="github_repository")) == [git_id]
    assert set(_ids(_page(corpus, source_type="corpus_content"))) == set(admitted)
    corpus.run({"action": "control_import", "import_job_id": admitted[0], "control": "PAUSE",
                "expected_status": "ADMITTED", "reason": "Native query status fixture"})
    assert _ids(_page(corpus, status="PAUSED", source_type="corpus_content", run_key_prefix="batch%_a/")) == [admitted[0]]
    assert set(_ids(_page(corpus, status="ADMITTED"))) == {git_id, *admitted[1:]}
    cli = _cli(corpus, "--run-key-prefix", "batch%_a/", "--source-type", "corpus_content", "--limit", "1")
    assert cli.returncode == 0, cli.stderr
    first = json.loads(cli.stdout)
    assert len(first["items"]) == 1 and first["next_after"] == first["items"][0]["import_job_id"]
    cli = _cli(corpus, "--run-key-prefix", "batch%_a/", "--after", first["next_after"], "--limit", "2")
    assert cli.returncode == 0, cli.stderr
    second = json.loads(cli.stdout)
    assert set(_ids(first["items"] + second["items"])) == set(admitted[:2])
    assert second["next_after"] == ""
    cli = _cli(corpus, "--status", "PAUSED", "--source-type", "corpus_content", "--run-key-prefix", "batch%_a/")
    assert cli.returncode == 0 and _ids(json.loads(cli.stdout)["items"]) == [admitted[0]], cli.stderr
    with psycopg.connect(DATABASE_URL) as connection:
        assert connection.execute("SELECT count(*) FROM authority_external_effect WHERE project_id=%s", [corpus.project]).fetchone()[0] == 0


def test_native_jobs_reject_foreign_cursors_and_permissions(corpus, tmp_path, monkeypatch):
    _runtime(tmp_path, monkeypatch)
    manifest = _input(tmp_path)
    own = _enqueue(corpus, manifest, "own/1")
    project, workspace = "foreign-" + uuid4().hex, "workspace-" + uuid4().hex
    ProjectAuthorityApplication(DATABASE_URL, application_build_id="jobs-test", commit_sha="e" * 40).execute(
        ProjectAuthorityCommand(definition_name="project_lifecycle.create", project_id=project,
            workspace_id=workspace, actor_id="query-test", idempotency_key=project,
            trace_id=project, correlation_id=project, payload={"title": "Independent query fixture"}))
    monkeypatch.setenv("NOVEL_FORGE_AUTHORITY_PROJECT_SCOPE", corpus.project + "," + project)
    foreign = _enqueue(corpus, manifest, "other/1", project=project, workspace=workspace)
    for cursor in (foreign, "does-not-exist"):
        response = corpus.client.get(BASE, params={"project_id": corpus.project, "after": cursor})
        assert response.status_code == 409 and response.json()["detail"]["code"] == "SOURCE_IMPORT_NOT_FOUND"
    assert _ids(_page(corpus)) == [own]
    for params in ({"after": "x" * 201}, {"limit": 0}, {"limit": 501}, {"run_key_prefix": "x" * 201}):
        response = corpus.client.get(BASE, params={"project_id": corpus.project, **params})
        assert response.status_code == 422, response.text
    monkeypatch.setenv("NOVEL_FORGE_AUTHORITY_PROJECT_SCOPE", project)
    assert corpus.client.get(BASE, params={"project_id": corpus.project}).status_code == 403
    assert _cli(corpus, scope=project).returncode != 0
    restricted = Principal(principal_id="no-query-permission", principal_type=PrincipalType.LOCAL_OPERATOR,
        permissions=frozenset({"source.authority.execute"}), project_scope=frozenset({corpus.project}),
        authentication_source="integration-test")
    with pytest.raises(PermissionError, match="source.authority.query"):
        SourceImportQuery(DATABASE_URL).list_imports(project_id=corpus.project, principal=restricted)


def test_native_fifty_job_pages_record_bounded_database_cost(corpus, tmp_path, monkeypatch):
    _runtime(tmp_path, monkeypatch)
    manifest = _input(tmp_path)
    admitted = {_enqueue(corpus, manifest, f"measurement%_/item-{n:02}") for n in range(50)}
    statements = []
    original = psycopg.Cursor.execute

    def count_execute(cursor, query, *args, **kwargs):
        statements.append(str(query))
        return original(cursor, query, *args, **kwargs)

    rows, page_sizes, after = [], [], ""
    with monkeypatch.context() as measure:
        measure.setattr(psycopg.Cursor, "execute", count_execute)
        tracemalloc.start()
        started = time.perf_counter()
        while True:
            page = _page(corpus, limit=10, after=after, run_key_prefix="measurement%_/",
                         source_type="corpus_content", status="ADMITTED")
            page_sizes.append(len(page))
            rows.extend(page)
            if len(page) < 10:
                break
            after = page[-1]["import_job_id"]
        elapsed = time.perf_counter() - started
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    job_queries = [sql for sql in statements if "FROM authority_source_import_job" in sql]
    assert set(_ids(rows)) == admitted and len(rows) == 50
    assert page_sizes == [10, 10, 10, 10, 10, 0]
    assert len(job_queries) == 11
    with psycopg.connect(DATABASE_URL) as connection:
        effect_count = connection.execute("SELECT count(*) FROM authority_external_effect WHERE project_id=%s", [corpus.project]).fetchone()[0]
    assert effect_count == 0
    if directory := os.environ.get("CORPUS_JOBS_EVIDENCE_DIR"):
        Path(directory).mkdir(parents=True, exist_ok=True)
        Path(directory, "fifty-jobs-query.json").write_text(json.dumps({
            "evidence_class": "ISOLATED_POSTGRES_NATIVE_QUERY_FIXTURE", "project_id": corpus.project,
            "native_enqueued_jobs": 50, "page_limit": 10, "page_sizes": page_sizes,
            "business_query_count": len(job_queries), "observed_cursor_execute_count": len(statements),
            "elapsed_seconds": elapsed, "python_tracemalloc_current_bytes": current,
            "python_tracemalloc_peak_bytes": peak, "external_effect_count": effect_count,
            "provider_calls": 0, "measurement_scope": "API pagination including terminal empty page; excludes admission, DB server memory and subprocess CLI",
        }, indent=2))
