import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg
import pytest

from novel_forge.api.authority_app import create_authority_app
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.project_authority import (
    ProjectAuthorityApplication,
    ProjectAuthorityCommand,
)
from novel_forge.modules.source_authority import (
    SourceAuthorityApplication,
    SourceAuthorityScheduler,
)
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated


BASE = "/product/source-governance/corpus"
DIGEST = "sha256:" + "a" * 64


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    ensure_migrated()
    project, workspace = f"corpus-{uuid4()}", f"workspace-{uuid4()}"
    ProjectAuthorityApplication(
        DATABASE_URL,
        application_build_id="corpus-test",
        commit_sha=os.environ.get("CORPUS_TESTED_SHA", "e" * 40),
    ).execute(
        ProjectAuthorityCommand(
            definition_name="project_lifecycle.create",
            project_id=project,
            workspace_id=workspace,
            actor_id="corpus-operator",
            idempotency_key=project,
            trace_id=project,
            correlation_id=project,
            payload={"title": "Corpus Foundation"},
        )
    )
    for key, value in {
        "NOVEL_FORGE_APPLICATION_BUILD_ID": "corpus-test",
        "NOVEL_FORGE_COMMIT_SHA": os.environ.get("CORPUS_TESTED_SHA", "e" * 40),
        "NOVEL_FORGE_ENVIRONMENT": "test",
        "NOVEL_FORGE_MODEL_PROVIDER": "mock",
        "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_BACKEND": "local",
        "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(tmp_path / "objects"),
        "NOVEL_FORGE_AUTHORITY_PROJECT_SCOPE": project,
    }.items():
        monkeypatch.setenv(key, value)
    app = create_authority_app(
        IndustrialSettings(
            root=tmp_path,
            environment="test",
            storage_authority="postgresql",
            database_url=DATABASE_URL,
        )
    )
    application = SourceAuthorityApplication(
        DATABASE_URL,
        application_build_id="corpus-test",
        commit_sha=os.environ.get("CORPUS_TESTED_SHA", "e" * 40),
    )
    scheduler = SourceAuthorityScheduler(
        application, worker_id=f"corpus-worker-{uuid4()}", lease_seconds=2
    )
    with TestClient(app) as client:
        yield CorpusFixture(client, project, workspace, scheduler)


class CorpusFixture:
    def __init__(self, client, project, workspace, scheduler):
        self.client, self.project, self.workspace, self.scheduler = (
            client,
            project,
            workspace,
            scheduler,
        )

    def admit(self, action, key=None):
        response = self.client.post(
            BASE + "/commands",
            json={
                "project_id": self.project,
                "workspace_id": self.workspace,
                "idempotency_key": key or str(uuid4()),
                "action": action,
            },
        )
        assert response.status_code == 202, response.text
        return response.json()

    def run(self, action, key=None):
        admitted = self.admit(action, key)
        return self.scheduler.run_or_recover(
            operation_id=admitted["operation_id"], project_id=self.project
        )

    def source(self, purpose="RESEARCH", external="dataset:test"):
        return self.run(
            {
                "action": "register_source",
                "source_kind": "operator_manifest",
                "external_identity": external,
                "purpose": purpose,
            }
        )["source_id"]

    def rights(self, source, status="UNKNOWN", previous=None):
        return self.run(
            {
                "action": "declare_rights",
                "source_id": source,
                "previous_rights_id": previous,
                "dataset_license": "MIT",
                "underlying_rights": status,
                "underlying_license": "work-license:explicit"
                if status == "LICENSED"
                else "",
                "allowed_purposes": ["RESEARCH", "BENCHMARK", "PRODUCTION_REFERENCE"],
                "evidence_refs": [f"operator-declaration:{source}:{status}"],
                "copyright_boundary": "metadata catalog and governed abstraction; no raw generation",
                "scope": "ALL_WORKS_IN_SNAPSHOT",
            }
        )["rights_id"]

    def snapshot(self, source, rights, previous=None, version="v1"):
        return self.run(
            {
                "action": "freeze_snapshot",
                "source_id": source,
                "rights_id": rights,
                "previous_snapshot_id": previous,
                "manifest": {
                    "origin_uri": "https://example.invalid/dataset",
                    "external_version": version,
                    "format": "jsonl",
                    "checksum": DIGEST,
                    "adapter_profile": "operator-metadata",
                    "adapter_contract_version": "1",
                },
                "acquisition": {
                    "locator": "archive:manifest.json",
                    "acquired_at": "2026-09-08T00:00:00Z",
                    "receipt_ref": "operator-receipt:1",
                    "checksum": DIGEST,
                },
            }
        )["snapshot_id"]

    def batch(self, snapshot, key="page-1", entries=None):
        return {
            "action": "import_batch",
            "snapshot_id": snapshot,
            "batch_key": key,
            "entries": entries
            or [
                {
                    "external_work_id": "work-one",
                    "external_edition_id": "edition-a",
                    "title": "原创书目甲",
                    "checksum": DIGEST,
                    "locator": "manifest:book/one",
                    "metadata": {
                        "language": "zh",
                        "external_work_identifiers": {"catalog": "one"},
                    },
                },
            ],
        }

    def lineage(self, edition):
        response = self.client.get(
            BASE + f"/lineage/{edition}", params={"project_id": self.project}
        )
        assert response.status_code == 200, response.text
        return response.json()


def test_native_api_worker_vertical_multi_source_editions_and_replay(corpus):
    source = corpus.source()
    rights = corpus.rights(source)
    snapshot = corpus.snapshot(source, rights)
    action = corpus.batch(snapshot)
    first = corpus.run(action)
    duplicate = corpus.run(action)
    assert duplicate["operation_id"] == first["operation_id"]
    assert duplicate["entries"] == first["entries"]
    assert duplicate["replayed"]
    lineage = corpus.lineage(first["entries"][0]["edition_id"])
    assert lineage["source"]["source_id"] == source
    assert lineage["rights"]["rights_id"] == rights
    assert lineage["snapshot"]["snapshot_id"] == snapshot
    assert len(lineage["memberships"]) == 1
    assert not lineage["admissions"][0]["evidence"]["generation_context_allowed"]
    second_snapshot = corpus.snapshot(source, rights, snapshot, "v2")
    second = corpus.run(corpus.batch(second_snapshot))
    assert (
        second["entries"][0]["book_source_id"] == first["entries"][0]["book_source_id"]
    )
    assert second["entries"][0]["edition_id"] != first["entries"][0]["edition_id"]
    other_source = corpus.source(external="other:dataset")
    other = corpus.run(
        corpus.batch(corpus.snapshot(other_source, corpus.rights(other_source)))
    )
    assert (
        other["entries"][0]["book_source_id"] != first["entries"][0]["book_source_id"]
    )
    job = corpus.client.get(
        BASE + "/imports/" + first["import_job_id"],
        params={"project_id": corpus.project},
    ).json()
    assert job["operation_status"] == "SUCCEEDED"
    assert len(job["attempts"]) == 1
    assert job["corpus_snapshot_id"] == snapshot
    evidence_dir = os.environ.get("CORPUS_EVIDENCE_DIR")
    if evidence_dir:
        Path(evidence_dir, "native-vertical.json").write_text(
            json.dumps(
                {"result": first, "job": job, "lineage": lineage},
                ensure_ascii=False,
                indent=2,
            )
        )


def test_rights_update_cannot_reauthorize_frozen_editions_and_benchmark_stays_isolated(
    corpus,
):
    source = corpus.source("PRODUCTION_REFERENCE")
    old_rights = corpus.rights(source)
    snapshot = corpus.snapshot(source, old_rights)
    first = corpus.run(corpus.batch(snapshot))
    assert first["entries"][0]["admission"]["decision"] == "DENY"
    edition = first["entries"][0]["edition_id"]
    new_rights = corpus.rights(source, "OWNED", old_rights)
    decision = corpus.run(
        {
            "action": "evaluate_admission",
            "edition_id": edition,
            "purpose": "PRODUCTION_REFERENCE",
        }
    )
    assert "RIGHTS_REVIEW_REQUIRED" in decision["admission"]["reasons"]
    assert not corpus.lineage(edition)["memberships"]
    new_snapshot = corpus.snapshot(source, new_rights, snapshot)
    permitted = corpus.run(corpus.batch(new_snapshot))
    assert permitted["entries"][0]["admission"]["decision"] == "ALLOW"
    benchmark_source = corpus.source("BENCHMARK", "benchmark:test")
    benchmark = corpus.run(
        corpus.batch(
            corpus.snapshot(benchmark_source, corpus.rights(benchmark_source, "OWNED"))
        )
    )
    denied = corpus.run(
        {
            "action": "evaluate_admission",
            "edition_id": benchmark["entries"][0]["edition_id"],
            "purpose": "PRODUCTION_REFERENCE",
        }
    )
    assert "BENCHMARK_PRODUCTION_FORBIDDEN" in denied["admission"]["reasons"]
    corpus.run(
        {
            "action": "retire_source",
            "source_id": source,
            "reason": "withdrawn from new use",
        }
    )
    assert corpus.lineage(edition)["retired"]
    assert corpus.lineage(edition)["rights"]["rights_id"] == old_rights


def test_concurrent_duplicate_import_and_immutable_batch_input(corpus):
    source = corpus.source()
    snapshot = corpus.snapshot(source, corpus.rights(source))
    action = corpus.batch(snapshot)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: corpus.admit(action), range(2)))
    assert results[0]["operation_id"] == results[1]["operation_id"]

    def competing_worker(number):
        scheduler = SourceAuthorityScheduler(
            corpus.scheduler.application, worker_id=f"competing-{number}"
        )
        try:
            return scheduler.run_or_recover(
                operation_id=results[0]["operation_id"], project_id=corpus.project
            )
        except KernelError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(competing_worker, range(2)))
    errors = [value for value in outcomes if isinstance(value, KernelError)]
    assert all(
        error.code
        in {
            "LEASE_NOT_AVAILABLE",
            "ATTEMPT_LEASE_ACTIVE",
            "ATTEMPT_ALREADY_ACTIVE",
            "OPERATION_COMPARE_AND_SET_CONFLICT",
            "ATTEMPT_COMPARE_AND_SET_CONFLICT",
            "OPERATION_STATUS_CONFLICT",
        }
        for error in errors
    ), errors
    successful = [value for value in outcomes if isinstance(value, dict)]
    assert successful
    result = successful[0]
    assert len(corpus.lineage(result["entries"][0]["edition_id"])["memberships"]) == 1
    action["entries"][0]["title"] = "silently changed metadata"
    response = corpus.client.post(
        BASE + "/commands",
        json={
            "project_id": corpus.project,
            "workspace_id": corpus.workspace,
            "idempotency_key": "another-key",
            "action": action,
        },
    )
    assert response.status_code == 409


def test_failed_batch_rolls_back_and_postgres_rejects_immutable_and_illegal_admission(
    corpus,
):
    source = corpus.source("PRODUCTION_REFERENCE")
    snapshot = corpus.snapshot(source, corpus.rights(source))
    first = corpus.run(corpus.batch(snapshot))
    edition = first["entries"][0]["edition_id"]
    entries = [
        {
            "external_work_id": "aaa-new",
            "external_edition_id": "1",
            "title": "new",
            "checksum": DIGEST,
            "locator": "new",
        },
        {
            **corpus.batch(snapshot)["entries"][0],
            "title": "conflicting immutable title",
        },
    ]
    failed = corpus.admit(corpus.batch(snapshot, "bad-page", entries))
    with pytest.raises(KernelError, match="CORPUS_IMMUTABLE_IDENTITY_INVALID"):
        corpus.scheduler.run_or_recover(
            operation_id=failed["operation_id"], project_id=corpus.project
        )
    status = corpus.client.get(
        BASE + "/imports/" + failed["import_job_id"],
        params={"project_id": corpus.project},
    ).json()
    assert status["effective_status"] == "FAILED_FINAL"
    resume = corpus.client.post(
        f"/product/source-imports/{failed['import_job_id']}/resume",
        params={"project_id": corpus.project},
    )
    assert resume.status_code == 409
    with psycopg.connect(DATABASE_URL) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM authority_corpus_book_identity WHERE source_id=%s",
                [source],
            ).fetchone()[0]
            == 1
        )
    for statement, params in [
        (
            "UPDATE authority_corpus_snapshot SET manifest=jsonb_set(manifest,'{external_version}','\"rewritten\"') WHERE snapshot_id=%s",
            [snapshot],
        ),
        ("DELETE FROM authority_corpus_source WHERE source_id=%s", [source]),
        (
            """INSERT INTO authority_corpus_admission SELECT %s,project_id,edition_id,rights_id,purpose,'ALLOW',evidence,created_by_operation_id,NOW() FROM authority_corpus_admission WHERE decision_id=%s""",
            [str(uuid4()), first["entries"][0]["decision_id"]],
        ),
    ]:
        with (
            psycopg.connect(DATABASE_URL) as connection,
            pytest.raises(psycopg.errors.CheckViolation),
        ):
            connection.execute(statement, params)
    assert not corpus.lineage(edition)["memberships"]


@pytest.mark.parametrize("crash_boundary", ["after_output", "after_attempt"])
def test_new_process_recovers_committed_batch_without_duplicate_state(
    corpus, crash_boundary
):
    source = corpus.source()
    snapshot = corpus.snapshot(source, corpus.rights(source))
    admitted = corpus.admit(corpus.batch(snapshot))
    operation = admitted["operation_id"]
    resume = corpus.client.post(
        f"/product/source-imports/{admitted['import_job_id']}/resume",
        params={"project_id": corpus.project},
    )
    assert resume.status_code == 202, resume.text
    assert resume.json()["resumable_operation_ids"] == [operation]
    assert not resume.json()["new_provider_work_created"]
    script = """
import os, sys
from novel_forge.modules.source_authority import SourceAuthorityApplication, SourceAuthorityScheduler
import novel_forge.modules.source_authority.scheduler as scheduling
app=SourceAuthorityApplication(os.environ['NOVEL_FORGE_DATABASE_URL'], application_build_id='corpus-test', commit_sha=os.environ.get('CORPUS_TESTED_SHA','e'*40))
if sys.argv[3]=='after_output':
    original=app.execute_fenced
    def crash(worker):
        original(worker)
        os._exit(73)
    app.execute_fenced=crash
elif sys.argv[3]=='after_attempt':
    def crash(*args, **kwargs):
        os._exit(73)
    scheduling.queue_attempt=crash
result=SourceAuthorityScheduler(app,worker_id='subprocess-'+sys.argv[3],lease_seconds=1).run_or_recover(operation_id=sys.argv[1],project_id=sys.argv[2])
assert result['status']=='SUCCEEDED'
"""
    environment = {**os.environ, "NOVEL_FORGE_DATABASE_URL": DATABASE_URL}
    crashed = subprocess.run(
        [sys.executable, "-c", script, operation, corpus.project, crash_boundary],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert crashed.returncode == 73, crashed.stderr
    time.sleep(1.2)
    recovered = subprocess.run(
        [sys.executable, "-c", script, operation, corpus.project, "recover"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert recovered.returncode == 0, recovered.stderr
    result = corpus.scheduler.run_or_recover(
        operation_id=operation, project_id=corpus.project
    )
    lineage = corpus.lineage(result["entries"][0]["edition_id"])
    assert len(lineage["admissions"]) == len(lineage["memberships"]) == 1
    with psycopg.connect(DATABASE_URL) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM authority_external_effect WHERE operation_id=%s",
                [operation],
            ).fetchone()[0]
            == 0
        )


def test_bounded_catalog_pagination_uses_index_with_representative_imports(corpus):
    source = corpus.source()
    rights = corpus.rights(source)
    snapshot = None
    for page in range(5):
        snapshot = corpus.snapshot(source, rights, snapshot, version=f"v{page}")
        entries = [
            {
                "external_work_id": f"work-{page}-{i}",
                "external_edition_id": "one",
                "title": f"书目{page}-{i}",
                "checksum": DIGEST,
                "locator": f"index:{page}:{i}",
            }
            for i in range(100)
        ]
        corpus.run(corpus.batch(snapshot, f"page-{page}", entries))
    params = {"project_id": corpus.project, "parent_id": snapshot, "limit": 5}
    first = corpus.client.get(BASE + "/records/edition", params=params).json()
    second = corpus.client.get(
        BASE + "/records/edition", params={**params, "after": first[-1]["edition_id"]}
    ).json()
    assert len(first) == len(second) == 5
    assert {row["edition_id"] for row in first}.isdisjoint(
        {row["edition_id"] for row in second}
    )
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute("ANALYZE authority_corpus_edition")
        plan = connection.execute(
            """
            EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
            SELECT to_jsonb(r) FROM authority_corpus_edition r
            WHERE project_id=%s AND edition_id>%s AND snapshot_id=%s ORDER BY edition_id LIMIT 5
        """,
            [corpus.project, first[-1]["edition_id"], snapshot],
        ).fetchone()[0]
    assert "authority_corpus_edition_page_idx" in json.dumps(plan)
    evidence_dir = os.environ.get("CORPUS_EVIDENCE_DIR")
    if evidence_dir:
        Path(evidence_dir, "query-plan.json").write_text(
            json.dumps(
                {
                    "catalog_rows": 500,
                    "query_plan": plan,
                    "planner_settings_changed": False,
                },
                indent=2,
            )
        )
