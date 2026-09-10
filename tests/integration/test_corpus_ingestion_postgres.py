import json

import psycopg
import pytest

from novel_forge.api.authority_dependencies import (
    build_production_execution_composition,
    build_source_import_application,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.source_import import SourceImportScheduler
from tests.integration.authority_postgres_support import DATABASE_URL

pytest_plugins = ["tests.integration.test_corpus_foundation_postgres"]


def _manifest(path, purpose="RESEARCH", analyze=False):
    return {
        "source": {"kind": "LOCAL", "location": str(path)},
        "parser": {
            "format": "jsonl",
            "layout": "CHAPTER_ROWS",
            "fields": {
                "work_id": "book",
                "text": "text",
                "chapter_id": "chapter",
                "order": "order",
            },
            "completeness": "COMPLETE",
            "expected_units": 2,
        },
        "purpose": purpose,
        "rights": {
            "dataset_license": "MIT",
            "scope": "ALL_WORKS_IN_SNAPSHOT",
            "underlying_rights": "OWNED",
            "allowed_purposes": [purpose],
            "allowed_uses": [
                "LOCAL_PROCESSING",
                "SOURCE_ANALYSIS",
                "ABSTRACT_GENERATION",
            ],
            "evidence_refs": ["operator:original-test-text"],
            "copyright_boundary": "Original isolated test; abstract knowledge only",
        },
        "analyze": analyze,
    }


def _runtime(tmp_path, monkeypatch):
    for key, value in {
        "NOVEL_FORGE_CORPUS_CACHE_ROOT": str(tmp_path / "cache"),
        "NOVEL_FORGE_CORPUS_LOCAL_ROOTS": json.dumps([str(tmp_path)]),
        "NOVEL_FORGE_SOURCE_IMPORT_GIT_CACHE_ROOT": str(tmp_path / "git-cache"),
    }.items():
        monkeypatch.setenv(key, value)
    settings = IndustrialSettings(
        root=tmp_path, environment="test", database_url=DATABASE_URL
    )
    execution = build_production_execution_composition(settings)
    app = build_source_import_application(settings, execution=execution)
    return app, SourceImportScheduler(
        app, worker_id="corpus-ingestion-test", lease_seconds=30
    )


def test_native_corpus_cross_shard_import_and_replay(corpus, tmp_path, monkeypatch):
    source = tmp_path / "input"
    source.mkdir()
    for index, text in ((1, "阿青把旧钥匙留给守门人。"), (2, "守门人用钥匙打开仓门。")):
        (source / f"part-{index}.jsonl").write_text(
            json.dumps(
                {
                    "book": "original",
                    "chapter": f"c{index}",
                    "order": index,
                    "text": text,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    app, scheduler = _runtime(tmp_path, monkeypatch)
    request = {
        "project_id": corpus.project,
        "workspace_id": corpus.workspace,
        "run_key": "local-cross-shard",
        "manifest": _manifest(source),
    }
    response = corpus.client.post("/product/source-imports/corpus", json=request)
    assert response.status_code == 202, response.text
    admitted = response.json()
    root = scheduler.run_or_recover(
        operation_id=admitted["operation_id"], project_id=corpus.project
    )
    assert root["result"]["work_count"] == 1
    assert root["result"]["parsed_records"] == 2
    child = root["result"]["children"][0]["operation_id"]
    completed = scheduler.run_or_recover(operation_id=child, project_id=corpus.project)
    result = completed["result"]
    assert result["unit_count"] == 2 and result["completeness"] == "COMPLETE"
    assert result["analysis_scheduled"] is False
    replay = scheduler.run_or_recover(operation_id=child, project_id=corpus.project)
    assert replay["result"] == result and replay["replayed"]
    with psycopg.connect(DATABASE_URL) as connection:
        rows = connection.execute(
            "SELECT edition_id,source_document_id FROM authority_corpus_bridge WHERE project_id=%s",
            [corpus.project],
        ).fetchall()
        assert rows == [(result["edition_id"], result["source_document_id"])]
    duplicate = corpus.client.post("/product/source-imports/corpus", json=request)
    assert (
        duplicate.status_code == 202
        and duplicate.json()["operation_id"] == admitted["operation_id"]
    )

    # WHY: Representative query-only rows are rolled back and never count as ingested content.
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            """INSERT INTO authority_corpus_content(
            content_id,project_id,snapshot_id,edition_id,blob_id,role,path,content_hash,byte_size,locator,acquisition_effect_id,created_by_operation_id)
            SELECT 'query-only-'||n,c.project_id,c.snapshot_id,NULL,c.blob_id,c.role,'query-only-'||n,c.content_hash,c.byte_size,
                '{"evidence_class":"QUERY_PLAN_FIXTURE"}'::jsonb,c.acquisition_effect_id,c.created_by_operation_id
            FROM (SELECT * FROM authority_corpus_content WHERE project_id=%s AND role='ACQUISITION' ORDER BY content_id LIMIT 1) c
            CROSS JOIN generate_series(1,5000) n""",
            [corpus.project],
        )
        connection.execute("ANALYZE authority_corpus_content")
        plan = connection.execute(
            """EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) SELECT to_jsonb(c)
            FROM authority_corpus_content c WHERE project_id=%s AND snapshot_id=%s AND content_id>%s ORDER BY content_id LIMIT 20""",
            [corpus.project, result["snapshot_id"], "query-only-2000"],
        ).fetchone()[0]
        # WHY: With one dense snapshot PostgreSQL may correctly choose its primary key.
        scan = plan[0]["Plan"]["Plans"][0]
        assert scan["Node Type"] in {"Index Scan", "Index Only Scan"}, plan
        assert scan["Actual Rows"] == 20, plan
        assert scan.get("Rows Removed by Filter", 0) <= 20, plan
        assert "content_id" in scan["Index Cond"], plan
        connection.rollback()
    import os
    from pathlib import Path

    if directory := os.environ.get("CORPUS_EVIDENCE_DIR"):
        Path(directory, "content-query-plan.json").write_text(
            json.dumps(
                {
                    "query_plan": plan,
                    "representative_rows": 5000,
                    "evidence_class": "QUERY_PLAN_FIXTURE",
                    "fixture_rolled_back": True,
                    "planner_settings_changed": False,
                },
                indent=2,
            )
        )

    from uuid import uuid4
    from novel_forge.modules.project_authority import (
        ProjectAuthorityApplication,
        ProjectAuthorityCommand,
    )

    other_project, other_workspace = "corpus-" + uuid4().hex, "workspace-" + uuid4().hex
    ProjectAuthorityApplication(
        DATABASE_URL,
        application_build_id="corpus-test",
        commit_sha=os.environ.get("CORPUS_TESTED_SHA", "e" * 40),
    ).execute(
        ProjectAuthorityCommand(
            definition_name="project_lifecycle.create",
            project_id=other_project,
            workspace_id=other_workspace,
            actor_id="corpus-operator",
            idempotency_key=other_project,
            trace_id=other_project,
            correlation_id=other_project,
            payload={"title": "Independent source scope"},
        )
    )
    monkeypatch.setenv(
        "NOVEL_FORGE_AUTHORITY_PROJECT_SCOPE", corpus.project + "," + other_project
    )
    _, other_scheduler = _runtime(tmp_path, monkeypatch)
    another = corpus.client.post(
        "/product/source-imports/corpus",
        json={**request, "project_id": other_project, "workspace_id": other_workspace},
    )
    assert another.status_code == 202, another.text
    next_root = other_scheduler.run_or_recover(
        operation_id=another.json()["operation_id"], project_id=other_project
    )
    next_result = other_scheduler.run_or_recover(
        operation_id=next_root["result"]["children"][0]["operation_id"],
        project_id=other_project,
    )
    assert next_result["status"] == "SUCCEEDED", next_result
    assert next_result["result"]["edition_id"] != result["edition_id"]
    assert next_result["result"]["normalized_hash"] == result["normalized_hash"]

    scoped_sources = []
    for project, workspace in (
        (corpus.project, corpus.workspace),
        (other_project, other_workspace),
    ):
        metadata = corpus.client.post(
            "/product/source-governance/corpus/commands",
            json={
                "project_id": project,
                "workspace_id": workspace,
                "idempotency_key": "reusable-operator-key",
                "action": {
                    "action": "register_source",
                    "source_kind": "LOCAL",
                    "external_identity": "urn:original-scoped-source",
                    "purpose": "RESEARCH",
                },
            },
        )
        assert metadata.status_code == 202, metadata.text
        committed = corpus.scheduler.run_or_recover(
            operation_id=metadata.json()["operation_id"], project_id=project
        )
        assert committed["status"] == "SUCCEEDED", committed
        scoped_sources.append(committed["source_id"])
    assert scoped_sources[0] != scoped_sources[1]


def test_authorized_bridge_reaches_existing_analysis_and_governance(
    corpus, tmp_path, monkeypatch
):
    from decimal import Decimal
    from novel_forge.modules.mkaos_authority import (
        MkaosAuthorityQuery,
        ApproveKnowledgeCandidateCommand,
        BuildKnowledgePackCommand,
        KnowledgePackSelection,
    )
    from novel_forge.modules.source_authority.corpus_consumption import (
        require_corpus_consumption,
    )
    from novel_forge.modules.command_kernel.errors import KernelError
    import pytest

    from novel_forge.api import authority_dependencies
    from novel_forge.modules.source_import.execution_contracts import (
        CLASSIFICATION_STAGE,
        content_intelligence_fixture_response,
    )

    def scripted_transport(stage, inputs):
        if stage == CLASSIFICATION_STAGE:
            return {
                "content_type": "PUBLISHED_FICTION",
                "confidence": 0.97,
                "alternatives": [
                    {"content_type": "PUBLISHED_FICTION", "confidence": 0.97},
                    {"content_type": "UNKNOWN", "confidence": 0.03},
                ],
                "evidence_codes": ["BOUNDED_SEMANTIC_SAMPLE"],
                "boundary_assessment": {
                    "scope_kind": "FILE_DOCUMENT",
                    "suspected_document_count": 1,
                    "review_required": False,
                },
            }
        return content_intelligence_fixture_response(stage, inputs)

    monkeypatch.setattr(
        authority_dependencies,
        "content_intelligence_fixture_response",
        scripted_transport,
    )
    source = tmp_path / "original.jsonl"
    source.write_text(
        "\n".join(
            json.dumps(
                {
                    "book": "bridge-original",
                    "chapter": str(i),
                    "order": i,
                    "text": text,
                },
                ensure_ascii=False,
            )
            for i, text in enumerate(
                (
                    "阿青要取回钥匙，却必须先答应替守门人送信。她明知会误船，仍接过信。",
                    "信送到后，守门人才解释仓门后是谁。阿青用迟到的代价换回了弟弟的消息。",
                ),
                1,
            )
        )
    )
    app, scheduler = _runtime(tmp_path, monkeypatch)
    response = corpus.client.post(
        "/product/source-imports/corpus",
        json={
            "project_id": corpus.project,
            "workspace_id": corpus.workspace,
            "run_key": "authorized-bridge",
            "manifest": _manifest(source, "PRODUCTION_REFERENCE", analyze=True),
        },
    )
    assert response.status_code == 202, response.text
    root = scheduler.run_or_recover(
        operation_id=response.json()["operation_id"], project_id=corpus.project
    )["result"]
    child = root["children"][0]["operation_id"]
    content = scheduler.run_or_recover(operation_id=child, project_id=corpus.project)[
        "result"
    ]
    for _ in range(40):
        pending = [
            (operation, project)
            for operation, project in scheduler.pending_operations(limit=100)
            if project == corpus.project
        ]
        if not pending:
            break
        for operation, project in pending:
            scheduler.run_or_recover(operation_id=operation, project_id=project)
    with psycopg.connect(DATABASE_URL) as connection:
        candidates = connection.execute(
            "SELECT asset_version_id FROM authority_mkaos_knowledge_candidate WHERE project_id=%s ORDER BY asset_version_id",
            [corpus.project],
        ).fetchall()
    assert candidates, "native analysis must produce actual governed candidates"
    from novel_forge.api.authority_dependencies import build_trusted_principal_resolver

    principal = build_trusted_principal_resolver().resolve_api_principal()
    query = MkaosAuthorityQuery(DATABASE_URL)
    approval = app.mkaos_authority.execute_approval(
        ApproveKnowledgeCandidateCommand(
            project_id=corpus.project,
            workspace_id=corpus.workspace,
            candidate_asset_version_id=candidates[0][0],
            policy_version="corpus-bridge-test.v1",
            rationale="Original scripted engineering evidence; approve abstract mechanism only",
            actor_id=principal.principal_id,
            idempotency_key="approve-bridge",
            trace_id=corpus.project,
            correlation_id=corpus.project,
        ),
        principal=principal,
    )
    pack = app.mkaos_authority.execute_pack(
        BuildKnowledgePackCommand(
            project_id=corpus.project,
            workspace_id=corpus.workspace,
            target_asset_version_id=content["source_work_asset_version_id"],
            selector_policy_version="corpus-bridge-test.v1",
            selector_policy_hash="sha256:" + "1" * 64,
            selections=(
                KnowledgePackSelection(
                    approval["asset_version_id"], "CONSTRAINT", Decimal("1")
                ),
            ),
            actor_id=principal.principal_id,
            idempotency_key="pack-bridge",
            trace_id=corpus.project,
            correlation_id=corpus.project,
        ),
        principal=principal,
    )
    assert (
        query.require_pack(
            project_id=corpus.project, knowledge_pack_id=pack["knowledge_pack_id"]
        )["item_count"]
        == 1
    )
    require_corpus_consumption(
        DATABASE_URL,
        corpus.project,
        {"knowledge_pack_id": pack["knowledge_pack_id"]},
        source_analysis=False,
    )
    with psycopg.connect(DATABASE_URL) as connection:
        card_hash = connection.execute(
            "SELECT content_hash FROM authority_mkaos_knowledge_card WHERE asset_version_id=%s",
            [approval["asset_version_id"]],
        ).fetchone()[0]
    with pytest.raises(KernelError, match="PLANNING_NARRATIVE_INTELLIGENCE_DRIFT"):
        query.require_planning_card_current(
            project_id=corpus.project,
            asset_version_id=approval["asset_version_id"],
            content_hash=card_hash,
        )
    with pytest.raises(KernelError, match="RAW_CONTENT"):
        require_corpus_consumption(
            DATABASE_URL,
            corpus.project,
            {"source_work_asset_version_id": content["source_work_asset_version_id"]},
            source_analysis=False,
        )
    corpus.run(
        {
            "action": "retire_source",
            "source_id": root["source_id"],
            "reason": "original sample rights withdrawn",
        }
    )
    with pytest.raises(KernelError, match="CORPUS"):
        query.require_planning_card_current(
            project_id=corpus.project,
            asset_version_id=approval["asset_version_id"],
            content_hash=card_hash,
        )
    with pytest.raises(KernelError, match="CORPUS"):
        query.require_pack(
            project_id=corpus.project, knowledge_pack_id=pack["knowledge_pack_id"]
        )
    with pytest.raises(KernelError, match="CORPUS"):
        require_corpus_consumption(
            DATABASE_URL,
            corpus.project,
            {"knowledge_pack_id": pack["knowledge_pack_id"]},
            source_analysis=False,
        )


def test_corpus_pause_resume_cancel_and_preview_do_not_fabricate_content(
    corpus, tmp_path, monkeypatch
):
    source = tmp_path / "input.jsonl"
    source.write_text(
        json.dumps(
            {
                "book": "original",
                "chapter": "c1",
                "order": 1,
                "text": "她决定明天归还钥匙。",
            },
            ensure_ascii=False,
        )
    )
    app, scheduler = _runtime(tmp_path, monkeypatch)
    request = {
        "project_id": corpus.project,
        "workspace_id": corpus.workspace,
        "run_key": "controlled",
        "manifest": _manifest(source),
    }
    preview = corpus.client.post(
        "/product/source-imports/corpus/preview", json=request
    ).json()
    assert (
        scheduler.run_or_recover(
            operation_id=preview["operation_id"], project_id=corpus.project
        )["result"]["content_imported"]
        is False
    )
    admitted = corpus.client.post("/product/source-imports/corpus", json=request).json()
    job = admitted["import_job_id"]
    paused = corpus.run(
        {
            "action": "control_import",
            "import_job_id": job,
            "control": "PAUSE",
            "expected_status": "ADMITTED",
            "reason": "operator checks sources",
        }
    )
    assert paused["control"] == "PAUSE"
    assert admitted["operation_id"] not in dict(
        scheduler.pending_operations(limit=1000)
    )
    corpus.run(
        {
            "action": "control_import",
            "import_job_id": job,
            "control": "RESUME",
            "expected_status": "PAUSED",
            "reason": "operator resumes frozen input",
        }
    )
    assert admitted["operation_id"] in dict(scheduler.pending_operations(limit=1000))
    corpus.run(
        {
            "action": "control_import",
            "import_job_id": job,
            "control": "CANCEL",
            "expected_status": "PROCESSING",
            "reason": "operator cancels before acquisition",
        }
    )
    with psycopg.connect(DATABASE_URL) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM authority_corpus_content WHERE project_id=%s",
                [corpus.project],
            ).fetchone()[0]
            == 0
        )


def test_corpus_native_research_and_benchmark_cannot_be_generation_input(
    corpus, tmp_path, monkeypatch
):
    import pytest
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.source_authority.corpus_consumption import (
        require_corpus_consumption,
    )

    source = tmp_path / "isolation.jsonl"
    source.write_text(
        "\n".join(
            json.dumps(
                {
                    "book": "isolated",
                    "chapter": str(i),
                    "order": i,
                    "text": "原创测评资料，不得作为生产知识。",
                },
                ensure_ascii=False,
            )
            for i in (1, 2)
        )
    )
    app, scheduler = _runtime(tmp_path, monkeypatch)
    imported = []
    for purpose in ("RESEARCH", "BENCHMARK"):
        location = tmp_path / (purpose + ".jsonl")
        location.write_bytes(source.read_bytes())
        request = {
            "project_id": corpus.project,
            "workspace_id": corpus.workspace,
            "run_key": purpose,
            "manifest": _manifest(location, purpose),
        }
        admitted = corpus.client.post(
            "/product/source-imports/corpus", json=request
        ).json()
        root = scheduler.run_or_recover(
            operation_id=admitted["operation_id"], project_id=corpus.project
        )["result"]
        result = scheduler.run_or_recover(
            operation_id=root["children"][0]["operation_id"], project_id=corpus.project
        )["result"]
        imported.append(result)
        for key in ("source_work_asset_version_id", "source_asset_version_id"):
            with pytest.raises(KernelError, match="CORPUS"):
                require_corpus_consumption(
                    DATABASE_URL,
                    corpus.project,
                    {key: result[key]},
                    source_analysis=False,
                )
        if purpose == "BENCHMARK":
            with pytest.raises(KernelError, match="CORPUS"):
                require_corpus_consumption(
                    DATABASE_URL,
                    corpus.project,
                    {
                        "source_work_asset_version_id": result[
                            "source_work_asset_version_id"
                        ]
                    },
                    source_analysis=True,
                )
        lineage = corpus.client.get(
            f"/product/source-imports/{admitted['import_job_id']}/corpus-lineage",
            params={"project_id": corpus.project, "limit": 1},
        )
        assert lineage.status_code == 200, lineage.text
        assert result["edition_id"] in lineage.text

    first, second = imported
    assert first["edition_id"] != second["edition_id"]
    found = corpus.client.get(
        "/product/source-imports/corpus/processing/" + first["processing_id"],
        params={"project_id": corpus.project, "discover": True},
    )
    assert found.status_code == 200, found.text
    assert any(
        c["processing_id"] == second["processing_id"] and c["exact_text"]
        for c in found.json()["candidates"]
    )
    accepted = corpus.run(
        {
            "action": "decide_equivalence",
            "left_id": first["processing_id"],
            "right_id": second["processing_id"],
            "decision": "ACCEPT",
            "evidence_refs": ["synthetic-independent-sources-identical-original-bytes"],
            "reason": "exact content relationship does not transfer purpose",
        }
    )
    assert accepted["status"] == "SUCCEEDED", accepted
    for result in imported:
        with pytest.raises(KernelError, match="CORPUS"):
            require_corpus_consumption(
                DATABASE_URL,
                corpus.project,
                {
                    "source_work_asset_version_id": result[
                        "source_work_asset_version_id"
                    ]
                },
                source_analysis=False,
            )


def test_corpus_current_rights_checked_before_external_acquisition(
    corpus, tmp_path, monkeypatch
):
    import pytest
    from novel_forge.modules.command_kernel.errors import KernelError

    source = tmp_path / "rights.jsonl"
    source.write_text(
        json.dumps(
            {
                "book": "rights",
                "chapter": "1",
                "order": 1,
                "text": "不会下载未授权内容。",
            },
            ensure_ascii=False,
        )
    )
    app, scheduler = _runtime(tmp_path, monkeypatch)
    manifest = _manifest(source)
    manifest["rights"]["allowed_uses"] = []
    admitted = corpus.client.post(
        "/product/source-imports/corpus",
        json={
            "project_id": corpus.project,
            "workspace_id": corpus.workspace,
            "run_key": "unauthorized",
            "manifest": manifest,
        },
    ).json()
    with pytest.raises(KernelError):
        scheduler.run_or_recover(
            operation_id=admitted["operation_id"], project_id=corpus.project
        )
    assert not list((tmp_path / "cache").glob("receipts/*.json"))
    with psycopg.connect(DATABASE_URL) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM authority_corpus_snapshot WHERE project_id=%s",
                [corpus.project],
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize("crash_boundary", ["after_output", "after_receipt"])
def test_native_import_new_process_recovery_and_concurrent_admission(
    corpus, tmp_path, monkeypatch, crash_boundary
):
    import os
    import subprocess
    import sys
    import time
    from concurrent.futures import ThreadPoolExecutor

    source = tmp_path / "restart.jsonl"
    source.write_text(
        "\n".join(
            json.dumps(
                {
                    "book": "restart",
                    "chapter": str(i),
                    "order": i,
                    "text": "恢复必须消费原有正式结果。",
                },
                ensure_ascii=False,
            )
            for i in (1, 2)
        )
    )
    app, scheduler = _runtime(tmp_path, monkeypatch)
    request = {
        "project_id": corpus.project,
        "workspace_id": corpus.workspace,
        "run_key": "restart",
        "manifest": _manifest(source),
    }
    with ThreadPoolExecutor(max_workers=2) as executor:
        admitted = list(
            executor.map(
                lambda _: corpus.client.post(
                    "/product/source-imports/corpus", json=request
                ).json(),
                range(2),
            )
        )
    assert all("operation_id" in item for item in admitted), admitted
    assert admitted[0]["operation_id"] == admitted[1]["operation_id"]
    script = """
import json, os, sys
from pathlib import Path
from novel_forge.api.authority_dependencies import build_production_execution_composition, build_source_import_application
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.source_import import SourceImportScheduler
settings=IndustrialSettings(root=Path(sys.argv[4]), environment='test', database_url=os.environ['NOVEL_FORGE_DATABASE_URL'])
app=build_source_import_application(settings, execution=build_production_execution_composition(settings))
if sys.argv[3]=='after_output':
    original=app.execute_fenced
    def crash(worker):
        original(worker)
        os._exit(73)
    app.execute_fenced=crash
elif sys.argv[3]=='after_receipt':
    original=app.corpus_adapter.execute
    def crash(**kwargs):
        original(**kwargs)
        os._exit(73)
    app.corpus_adapter.execute=crash
result=SourceImportScheduler(app,worker_id='process-'+sys.argv[3],lease_seconds=1).run_or_recover(operation_id=sys.argv[1],project_id=sys.argv[2])
print(json.dumps(result,default=str))
"""
    operation = admitted[0]["operation_id"]
    env = dict(os.environ)
    crashed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            operation,
            corpus.project,
            crash_boundary,
            str(tmp_path),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert crashed.returncode == 73, crashed.stderr
    time.sleep(31 if crash_boundary == "after_receipt" else 1.2)
    recovered = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            operation,
            corpus.project,
            "recover",
            str(tmp_path),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert recovered.returncode == 0, recovered.stderr
    result = json.loads(recovered.stdout)["result"]
    child = result["children"][0]["operation_id"]
    completed = scheduler.run_or_recover(operation_id=child, project_id=corpus.project)
    replay = scheduler.run_or_recover(operation_id=operation, project_id=corpus.project)
    assert replay["result"] == result
    with psycopg.connect(DATABASE_URL) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM authority_corpus_bridge WHERE project_id=%s",
                [corpus.project],
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM authority_external_effect WHERE operation_id=%s AND capability='source.remote.fetch'",
                [operation],
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM authority_corpus_membership WHERE edition_id=%s",
                [completed["result"]["edition_id"]],
            ).fetchone()[0]
            == 1
        )
    changed = json.loads(json.dumps(request))
    changed["manifest"]["parser"]["encoding"] = "gb18030"
    response = corpus.client.post("/product/source-imports/corpus", json=changed)
    assert response.status_code == 409, response.text


def test_mixed_work_rights_and_legacy_rewrapping_remain_fail_closed(
    corpus, tmp_path, monkeypatch
):
    import pytest
    from uuid import uuid4
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.source_authority.application import (
        RegisterSourceDocumentCommand,
    )

    source = tmp_path / "mixed.jsonl"
    source.write_text(
        "\n".join(
            json.dumps(
                {
                    "book": book,
                    "chapter": str(i),
                    "order": i,
                    "text": book + "：同一数据集不意味着共享许可。",
                },
                ensure_ascii=False,
            )
            for book in ("owned", "unknown")
            for i in (1, 2)
        )
    )
    app, scheduler = _runtime(tmp_path, monkeypatch)
    manifest = _manifest(source, "PRODUCTION_REFERENCE")
    rights = manifest["rights"]
    rights["scope"] = "SELECTED_WORKS"
    rights["underlying_rights"] = "UNKNOWN"
    rights["work_grants"] = {
        "owned": {
            "underlying_rights": "OWNED",
            "allowed_purposes": ["PRODUCTION_REFERENCE"],
            "allowed_uses": rights["allowed_uses"],
            "evidence_refs": ["operator:owns-only-owned-work"],
        }
    }
    admitted = corpus.client.post(
        "/product/source-imports/corpus",
        json={
            "project_id": corpus.project,
            "workspace_id": corpus.workspace,
            "run_key": "mixed",
            "manifest": manifest,
        },
    ).json()
    root = scheduler.run_or_recover(
        operation_id=admitted["operation_id"], project_id=corpus.project
    )["result"]
    assert [item["status"] for item in root["children"]].count("READY") == 1
    assert [item["status"] for item in root["children"]].count("BLOCKED") == 1
    child = next(item for item in root["children"] if item["status"] == "READY")
    scheduler.run_or_recover(
        operation_id=child["operation_id"], project_id=corpus.project
    )
    status = corpus.client.get(
        f"/product/source-imports/{admitted['import_job_id']}",
        params={"project_id": corpus.project},
    )
    assert status.status_code == 200, status.text
    assert status.json()["status"] == "AWAITING_GOVERNANCE"
    with psycopg.connect(DATABASE_URL) as connection:
        denied = connection.execute(
            "SELECT decision_id FROM authority_corpus_admission WHERE project_id=%s AND decision='DENY'",
            [corpus.project],
        ).fetchone()[0]
        raw_blob = connection.execute(
            "SELECT blob_id FROM authority_corpus_content WHERE project_id=%s AND role='ACQUISITION' LIMIT 1",
            [corpus.project],
        ).fetchone()[0]
        assert (
            connection.execute(
                "SELECT count(*) FROM authority_corpus_bridge WHERE project_id=%s",
                [corpus.project],
            ).fetchone()[0]
            == 1
        )
    with (
        psycopg.connect(DATABASE_URL) as connection,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        connection.execute(
            "INSERT INTO authority_corpus_admission SELECT %s,project_id,edition_id,rights_id,purpose,'ALLOW',evidence,created_by_operation_id,NOW() FROM authority_corpus_admission WHERE decision_id=%s",
            [str(uuid4()), denied],
        )
    with pytest.raises(KernelError, match="CORPUS_DOCUMENT_LINEAGE_REQUIRED"):
        app.source_authority.execute(
            RegisterSourceDocumentCommand(
                project_id=corpus.project,
                workspace_id=corpus.workspace,
                blob_id=raw_blob,
                title="rewrapped",
                source_kind="owned",
                source_uri="urn:rewrapped",
                rights_authorization="owned",
                license_name="MIT",
                copyright_boundary="cannot authorize the underlying work by changing a label",
                actor_id="source-operator",
                idempotency_key="rewrapped",
                trace_id="rewrapped",
                correlation_id=corpus.project,
            )
        )


def test_final_acquisition_failure_cannot_reopen_import(corpus, tmp_path, monkeypatch):
    from novel_forge.modules.command_kernel.errors import KernelError

    app, scheduler = _runtime(tmp_path, monkeypatch)
    admitted = corpus.client.post(
        "/product/source-imports/corpus",
        json={
            "project_id": corpus.project,
            "workspace_id": corpus.workspace,
            "run_key": "missing-source-final",
            "manifest": _manifest(tmp_path / "missing.jsonl"),
        },
    ).json()
    with pytest.raises(KernelError):
        scheduler.run_or_recover(
            operation_id=admitted["operation_id"], project_id=corpus.project
        )
    status = corpus.client.get(
        f"/product/source-imports/{admitted['import_job_id']}",
        params={"project_id": corpus.project},
    ).json()
    assert status["status"] == "FAILED_FINAL", status["failure"]
    assert status["failure"]["code"] == "SOURCE_IMPORT_EFFECT_FAILED_FINAL"
    from novel_forge.api.authority_dependencies import build_trusted_principal_resolver

    with pytest.raises(KernelError, match="SOURCE_IMPORT_RETRY_REQUIRES_NEW_JOB"):
        app.resume_import(
            project_id=corpus.project,
            import_job_id=admitted["import_job_id"],
            principal=build_trusted_principal_resolver().resolve_api_principal(),
        )
    with pytest.raises(KernelError, match="SOURCE_RECOVERY_TERMINAL"):
        scheduler.run_or_recover(
            operation_id=admitted["operation_id"], project_id=corpus.project
        )
    with psycopg.connect(DATABASE_URL) as connection:
        assert connection.execute(
            "SELECT status,count(*) FROM authority_external_effect WHERE operation_id=%s GROUP BY status",
            [admitted["operation_id"]],
        ).fetchall() == [("FAILED_FINAL", 1)]
        assert (
            connection.execute(
                "SELECT count(*) FROM authority_corpus_snapshot WHERE project_id=%s",
                [corpus.project],
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize("crash_after_commit", [False, True])
def test_native_integrity_review_reprocessing_and_equivalence(
    corpus, tmp_path, monkeypatch, crash_after_commit
):
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.source_authority.corpus import CorpusUse
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    from novel_forge.storage.source_authority_repositories import (
        SourceAuthorityRepository,
    )

    app, scheduler = _runtime(tmp_path, monkeypatch)
    path = tmp_path / "chapters.txt"
    path.write_text(
        "版权与版本说明。\n第一章 起因\n"
        + "甲冒险交出钥匙。" * 20
        + "\n第二章 代价\n"
        + "乙归还钥匙，承担后果。" * 20
    )
    manifest = _manifest(path)
    parser = {
        "version": "corpus-parser.v2",
        "format": "txt",
        "constants": {"work_id": "original"},
        "completeness": "UNKNOWN",
        "normalization": {
            "min_body_chars": 10,
            "expected_toc": ["第一章 起因", "第二章 代价"],
            "toc_evidence": "original-test:catalogue-v1",
        },
    }
    manifest["parser"] = parser
    request = {
        "project_id": corpus.project,
        "workspace_id": corpus.workspace,
        "run_key": "normalization",
        "manifest": manifest,
    }
    admitted = corpus.client.post("/product/source-imports/corpus", json=request)
    assert admitted.status_code == 202, admitted.text
    acquired = scheduler.run_or_recover(
        operation_id=admitted.json()["operation_id"], project_id=corpus.project
    )
    assert acquired["status"] == "SUCCEEDED", acquired
    completed = scheduler.run_or_recover(
        operation_id=acquired["result"]["children"][0]["operation_id"],
        project_id=corpus.project,
    )
    assert completed["status"] == "SUCCEEDED", completed
    first = completed["result"]

    def inspect(identity, **params):
        response = corpus.client.get(
            "/product/source-imports/corpus/processing/" + identity,
            params={"project_id": corpus.project, **params},
        )
        assert response.status_code == 200, response.text
        return response.json()

    processing = inspect(first["processing_id"])
    assert not processing["assessment"]["structure_usable"]
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        with pytest.raises(KernelError, match="MKAOS_CORPUS_BRIDGE_REQUIRED"):
            SourceAuthorityRepository(uow.cursor).require_corpus_documents(
                corpus.project,
                (first["source_document_id"],),
                CorpusUse.SOURCE_ANALYSIS,
            )
    finding = next(
        i for i in processing["assessment"]["issues"] if i["code"] == "NON_BODY_UNIT"
    )
    reviewed = corpus.run(
        {
            "action": "review_processing",
            "processing_id": first["processing_id"],
            "decisions": [
                {
                    "issue_id": finding["issue_id"],
                    "resolution": "MARK_NON_BODY",
                    "reason": "front matter identified in original fixture",
                }
            ],
            "reason": "exclude front matter from analysis, preserve raw evidence",
        }
    )
    assert reviewed["status"] == "SUCCEEDED", reviewed
    reprocess_request = {
        "project_id": corpus.project,
        "edition_id": first["edition_id"],
        "run_key": "apply-review",
        "parser": {
            **parser,
            "version": "corpus-parser.v3",
            "normalization": {
                **parser["normalization"],
                "version": "chinese-longform.v2",
            },
        },
    }
    admitted2 = corpus.client.post(
        "/product/source-imports/corpus/reprocess", json=reprocess_request
    )
    assert admitted2.status_code == 202, admitted2.text
    if crash_after_commit:
        import os
        import subprocess
        import sys
        import time

        script = """
import json,os,sys
from pathlib import Path
from novel_forge.api.authority_dependencies import build_production_execution_composition,build_source_import_application
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.source_import import SourceImportScheduler
settings=IndustrialSettings(root=Path(sys.argv[3]),environment='test',database_url=os.environ['NOVEL_FORGE_DATABASE_URL'])
app=build_source_import_application(settings,execution=build_production_execution_composition(settings))
if sys.argv[4]=='crash':
 original=app.execute_fenced
 def crash(worker):
  original(worker)
  os._exit(73)
 app.execute_fenced=crash
print(json.dumps(SourceImportScheduler(app,worker_id='independent-'+sys.argv[4],lease_seconds=1).run_or_recover(operation_id=sys.argv[1],project_id=sys.argv[2]),default=str))
"""
        args = [
            sys.executable,
            "-c",
            script,
            admitted2.json()["operation_id"],
            corpus.project,
            str(tmp_path),
        ]
        died = subprocess.run(
            [*args, "crash"],
            env=dict(os.environ),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert died.returncode == 73, died.stderr
        time.sleep(2)
        resumed = subprocess.run(
            [*args, "recover"],
            env=dict(os.environ),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert resumed.returncode == 0, resumed.stderr
        second = json.loads(resumed.stdout)
    else:
        second = scheduler.run_or_recover(
            operation_id=admitted2.json()["operation_id"], project_id=corpus.project
        )
    assert second["status"] == "SUCCEEDED", second
    current = inspect(second["result"]["processing_id"])
    assert (
        current["edition_id"] == processing["edition_id"]
        and current["parent_id"] == processing["processing_id"]
    )
    assert current["assessment"]["structure_usable"]
    assert second["result"]["source_document_id"] != first["source_document_id"]
    replay = scheduler.run_or_recover(
        operation_id=admitted2.json()["operation_id"], project_id=corpus.project
    )
    assert replay["replayed"] and replay["result"] == second["result"]
    duplicate = corpus.client.post(
        "/product/source-imports/corpus/reprocess", json=reprocess_request
    )
    assert duplicate.json()["operation_id"] == admitted2.json()["operation_id"]
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        repository = SourceAuthorityRepository(uow.cursor)
        repository.require_corpus_documents(
            corpus.project,
            (second["result"]["source_document_id"],),
            CorpusUse.SOURCE_ANALYSIS,
        )
        with pytest.raises(KernelError, match="MKAOS_CORPUS_BRIDGE_REQUIRED"):
            repository.require_corpus_documents(
                corpus.project,
                (first["source_document_id"],),
                CorpusUse.SOURCE_ANALYSIS,
            )
        uow.cursor.execute(
            "SELECT count(*) FROM authority_corpus_edition WHERE project_id=%s",
            [corpus.project],
        )
        assert uow.cursor.fetchone()[0] == 1
        uow.cursor.execute(
            "SELECT count(*) FROM authority_external_effect WHERE project_id=%s AND capability='source.remote.fetch'",
            [corpus.project],
        )
        assert uow.cursor.fetchone()[0] == 1
    compared = inspect(first["processing_id"], compare_to=current["processing_id"])
    assert (
        not compared["comparison"]["exact_text"]
        and compared["comparison"]["rights_transfer"] is False
    )
    decision = corpus.run(
        {
            "action": "decide_equivalence",
            "left_id": first["processing_id"],
            "right_id": current["processing_id"],
            "decision": "ACCEPT",
            "evidence_refs": ["original-same-edition-two-parser-revisions"],
            "reason": "same source edition with reviewed front matter",
        }
    )
    assert decision["status"] == "SUCCEEDED", decision
    revoke = corpus.run(
        {
            "action": "decide_equivalence",
            "left_id": first["processing_id"],
            "right_id": current["processing_id"],
            "previous_id": decision["decision_id"],
            "decision": "REVOKE",
            "evidence_refs": ["test-pair-revocation"],
            "reason": "demonstrate append-only correction",
        }
    )
    assert revoke["status"] == "SUCCEEDED", revoke

    unchanged = corpus.client.post(
        "/product/source-imports/corpus/reprocess",
        json={**reprocess_request, "run_key": "same-contract-reuse"},
    )
    assert unchanged.status_code == 202, unchanged.text
    reused = scheduler.run_or_recover(
        operation_id=unchanged.json()["operation_id"], project_id=corpus.project
    )
    assert reused["status"] == "SUCCEEDED", reused
    assert reused["result"]["processing_id"] == current["processing_id"]
    with psycopg.connect(DATABASE_URL) as connection:
        with pytest.raises(psycopg.errors.CheckViolation, match="immutable"):
            connection.execute(
                "UPDATE authority_corpus_processing SET assessment='{}' WHERE processing_id=%s",
                [current["processing_id"]],
            )
        connection.rollback()
        assert (
            connection.execute(
                "SELECT count(*) FROM authority_corpus_processing WHERE edition_id=%s",
                [current["edition_id"]],
            ).fetchone()[0]
            == 2
        )


@pytest.mark.parametrize("review_changes_before_commit", [False, True])
def test_native_exact_boundary_repair_preserves_source_and_closes_scoped_issues(
    corpus, tmp_path, monkeypatch, review_changes_before_commit
):
    import hashlib

    app, scheduler = _runtime(tmp_path, monkeypatch)
    path = tmp_path / "unstructured.txt"
    text = "甲交出钥匙并承诺回来。" * 20 + "\n" + "乙归还钥匙兑现约定。" * 20
    raw = text.encode()
    path.write_bytes(raw)
    parser = {
        "version": "corpus-parser.v2",
        "format": "txt",
        "constants": {"work_id": "boundary-original"},
        "normalization": {"min_body_chars": 10},
    }
    manifest = {**_manifest(path), "parser": parser}
    admitted = corpus.client.post(
        "/product/source-imports/corpus",
        json={
            "project_id": corpus.project,
            "workspace_id": corpus.workspace,
            "run_key": "boundaries",
            "manifest": manifest,
        },
    )
    assert admitted.status_code == 202, admitted.text
    root = scheduler.run_or_recover(
        operation_id=admitted.json()["operation_id"], project_id=corpus.project
    )
    first = scheduler.run_or_recover(
        operation_id=root["result"]["children"][0]["operation_id"],
        project_id=corpus.project,
    )
    assert first["status"] == "SUCCEEDED", first
    original = corpus.client.get(
        "/product/source-imports/corpus/processing/" + first["result"]["processing_id"],
        params={"project_id": corpus.project},
    ).json()
    assert not original["assessment"]["structure_usable"]
    cut = len((text.split("\n")[0] + "\n").encode())
    parser["normalization"]["boundaries"] = [
        {
            "path": path.name,
            "checksum": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "start": start,
            "end": end,
            "title": title,
            "number": i,
            "evidence": "original synthetic fixture, exact authored boundary",
        }
        for i, (start, end, title) in enumerate(
            ((0, cut, "第一章 承诺"), (cut, len(raw), "第二章 兑现")), 1
        )
    ]
    repair = corpus.client.post(
        "/product/source-imports/corpus/reprocess",
        json={
            "project_id": corpus.project,
            "edition_id": first["result"]["edition_id"],
            "run_key": "exact-boundaries",
            "parser": parser,
        },
    )
    assert repair.status_code == 202, repair.text
    if review_changes_before_commit:
        from novel_forge.modules.source_import.corpus_ingestion import similarity

        fingerprint = similarity.fingerprint

        def intervene(texts):
            value = fingerprint(texts)
            decision = corpus.run(
                {
                    "action": "review_processing",
                    "processing_id": original["processing_id"],
                    "decisions": [
                        {
                            "issue_id": original["assessment"]["issues"][0]["issue_id"],
                            "resolution": "REJECT_CORRUPT",
                            "reason": "new source evidence found while processing was in flight",
                        }
                    ],
                    "reason": "concurrent source review",
                }
            )
            assert decision["status"] == "SUCCEEDED", decision
            return value

        monkeypatch.setattr(similarity, "fingerprint", intervene)
    if review_changes_before_commit:
        from novel_forge.modules.command_kernel.errors import KernelError

        with pytest.raises(KernelError, match="CORPUS_REPROCESS_STALE_FAILED_FINAL"):
            scheduler.run_or_recover(
                operation_id=repair.json()["operation_id"], project_id=corpus.project
            )
        result = app.result(
            repair.json()["operation_id"], corpus.project, replayed=False
        )
        assert result["status"] == "FAILED_FINAL", result
        current = corpus.client.get(
            "/product/source-imports/corpus/processing/"
            + first["result"]["edition_id"],
            params={"project_id": corpus.project, "edition": True},
        ).json()
        assert current["processing_id"] == original["processing_id"]
        assert current["assessment"]["coverage"] == "CORRUPT"
        with psycopg.connect(DATABASE_URL) as connection:
            assert (
                connection.execute(
                    "SELECT count(*) FROM authority_corpus_bridge WHERE edition_id=%s",
                    [first["result"]["edition_id"]],
                ).fetchone()[0]
                == 1
            )
        return
    result = scheduler.run_or_recover(
        operation_id=repair.json()["operation_id"], project_id=corpus.project
    )
    assert result["status"] == "SUCCEEDED", result
    current = corpus.client.get(
        "/product/source-imports/corpus/processing/"
        + result["result"]["processing_id"],
        params={"project_id": corpus.project},
    ).json()
    assert current["assessment"]["structure_usable"]
    assert current["assessment"]["chapter_count"] == 2
    assert current["assessment"]["coverage"] == "UNKNOWN"
    assert {r["issue_id"] for r in current["assessment"]["resolutions"]} == {
        i["issue_id"] for i in original["assessment"]["issues"]
    }
    assert (
        current["edition_id"] == original["edition_id"]
        and current["parent_id"] == original["processing_id"]
    )
    assert current["downstream_impact"]["operation_id"] == repair.json()["operation_id"]


@pytest.mark.parametrize("invalidate_after_model", [False, True])
def test_native_curated_corpus_freeze_analysis_and_stale_members(
    corpus, tmp_path, monkeypatch, invalidate_after_model
):
    from novel_forge.api import authority_dependencies
    from novel_forge.modules.source_import.execution_contracts import (
        CLASSIFICATION_STAGE,
        content_intelligence_fixture_response,
    )
    from novel_forge.modules.command_kernel.errors import KernelError

    def transport(stage, inputs):
        if stage == CLASSIFICATION_STAGE:
            if invalidate_after_model:
                corpus.run(
                    {
                        "action": "resolve_canonical_works",
                        "changes": [
                            {
                                "work_key": "key-story",
                                "previous_id": work["revisions"][0]["revision_id"],
                                "title": "钥匙与来信",
                                "state": "RETIRED",
                                "metadata_evidence": [
                                    "operator:concurrent-selection-withdrawal"
                                ],
                                "members": [],
                            }
                        ],
                        "reason": "withdraw after request send before formal output publication",
                    }
                )
            return {
                "content_type": "PUBLISHED_FICTION",
                "confidence": 0.97,
                "alternatives": [
                    {"content_type": "PUBLISHED_FICTION", "confidence": 0.97},
                    {"content_type": "UNKNOWN", "confidence": 0.03},
                ],
                "evidence_codes": ["BOUNDED_SEMANTIC_SAMPLE"],
                "boundary_assessment": {
                    "scope_kind": "FILE_DOCUMENT",
                    "suspected_document_count": 1,
                    "review_required": False,
                },
            }
        return content_intelligence_fixture_response(stage, inputs)

    monkeypatch.setattr(
        authority_dependencies, "content_intelligence_fixture_response", transport
    )
    app, scheduler = _runtime(tmp_path, monkeypatch)
    path = tmp_path / "novel.txt"
    path.write_text(
        "第一章 选择\n"
        + "阿青交还钥匙，为弟弟承担迟到的代价。" * 15
        + "\n第二章 消息\n"
        + "守门人履行承诺，将信交还她，但拒绝暴露送信人的姓名。" * 15
    )
    parser = {
        "version": "corpus-parser.v3",
        "format": "txt",
        "constants": {"work_id": "original"},
        "normalization": {
            "version": "chinese-longform.v2",
            "expected_toc": ["第一章 选择", "第二章 消息"],
            "toc_evidence": "original:test-two-chapters",
        },
    }
    admitted = corpus.client.post(
        "/product/source-imports/corpus",
        json={
            "project_id": corpus.project,
            "workspace_id": corpus.workspace,
            "run_key": "curated-input",
            "manifest": {**_manifest(path), "parser": parser},
        },
    )
    assert admitted.status_code == 202, admitted.text
    acquisition = scheduler.run_or_recover(
        operation_id=admitted.json()["operation_id"], project_id=corpus.project
    )
    completed = scheduler.run_or_recover(
        operation_id=acquisition["result"]["children"][0]["operation_id"],
        project_id=corpus.project,
    )["result"]
    processing = completed["processing_id"]
    work = corpus.run(
        {
            "action": "resolve_canonical_works",
            "changes": [
                {
                    "work_key": "key-story",
                    "title": "钥匙与来信",
                    "language": "zh",
                    "genre_tags": ["原创测试"],
                    "metadata_evidence": ["operator:original-authorship"],
                    "members": [
                        {
                            "processing_id": processing,
                            "relation": "SAME_WORK",
                            "evidence_refs": ["operator:original-authorship"],
                        }
                    ],
                }
            ],
            "reason": "explicit original work identity",
        }
    )
    assert work["status"] == "SUCCEEDED", work
    candidate_action = {
        "action": "revise_curated_corpus",
        "corpus_key": "reading-set",
        "title": "中文精选",
        "purpose": "RESEARCH",
        "filters": {"language": "zh"},
        "reason": "inspect original research sources",
    }
    candidate = corpus.run(candidate_action)
    assert (
        len(candidate["availability"]) == 1
        and candidate["availability"][0]["available"]
    ), candidate
    frozen = corpus.run(
        {
            **candidate_action,
            "previous_id": candidate["revision_id"],
            "state": "FROZEN",
            "choices": [
                {
                    "processing_id": processing,
                    "selected": True,
                    "reason": "scoped complete chapter catalogue",
                    "evidence_refs": ["operator:review-two-original-chapters"],
                }
            ],
        }
    )
    assert frozen["selected_count"] == 1
    query = corpus.client.get(
        "/product/source-imports/corpus/catalog/curated/" + frozen["corpus_id"],
        params={"project_id": corpus.project},
    )
    assert query.status_code == 200, query.text
    assert query.json()["current_availability"][0]["available"]
    with psycopg.connect(DATABASE_URL) as connection:
        with pytest.raises(
            psycopg.errors.CheckViolation, match="curated member must retain"
        ):
            with connection.transaction():
                connection.execute(
                    "INSERT INTO authority_corpus_curated_member SELECT revision_id,project_id,processing_id,edition_id,jsonb_set(evidence,'{rights_id}','\"wrong-rights\"'::jsonb) FROM authority_corpus_curated_member WHERE revision_id=%s",
                    [frozen["revision_id"]],
                )
        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                connection.execute(
                    "UPDATE authority_corpus_work_revision SET manifest=manifest WHERE revision_id=%s",
                    [work["revisions"][0]["revision_id"]],
                )
        connection.execute(
            """INSERT INTO authority_corpus_work_revision(revision_id,work_id,project_id,workspace_id,manifest,created_by_operation_id)
            SELECT 'query-only-'||n,'query-work-'||n,project_id,workspace_id,'{"state":"RETIRED","evidence_class":"QUERY_PLAN_FIXTURE"}'::jsonb,created_by_operation_id
            FROM authority_corpus_work_revision CROSS JOIN generate_series(1,5000) n WHERE revision_id=%s""",
            [work["revisions"][0]["revision_id"]],
        )
        connection.execute("ANALYZE authority_corpus_work_revision")
        plan = connection.execute(
            """EXPLAIN(ANALYZE,BUFFERS,FORMAT JSON) SELECT to_jsonb(r) FROM authority_corpus_work_revision r
            WHERE r.project_id=%s AND r.work_id=%s AND NOT EXISTS(SELECT 1 FROM authority_corpus_work_revision n WHERE n.previous_id=r.revision_id)""",
            [corpus.project, work["revisions"][0]["work_id"]],
        ).fetchone()[0]

        def nodes(node):
            yield node
            for child in node.get("Plans", []):
                yield from nodes(child)

        scans = [n for n in nodes(plan[0]["Plan"]) if "Scan" in n["Node Type"]]
        assert scans and all("Index" in n["Node Type"] for n in scans), plan
        connection.rollback()
    import os
    from pathlib import Path

    if directory := os.environ.get("CORPUS_EVIDENCE_DIR"):
        Path(directory, "canonical-work-query-plan.json").write_text(
            json.dumps(
                {
                    "plan": plan,
                    "fixture_rows": 5000,
                    "fixture_rolled_back": True,
                    "planner_settings_changed": False,
                },
                indent=2,
            )
        )
    request = {
        "project_id": corpus.project,
        "revision_id": frozen["revision_id"],
        "run_key": "analysis-first",
        "max_members": 1,
        "max_calls": 20,
        "max_tokens": 200000,
        "authorization_ref": "scripted-engineering-only",
    }
    analysis = corpus.client.post(
        "/product/source-imports/corpus/analyze", json=request
    )
    assert analysis.status_code == 202, analysis.text
    status = corpus.client.get(
        "/product/source-imports/" + analysis.json()["import_job_id"],
        params={"project_id": corpus.project},
    )
    assert status.status_code == 200, status.text
    assert status.json()["corpus"]["purpose"] == "RESEARCH"
    repeated = corpus.client.post(
        "/product/source-imports/corpus/analyze", json=request
    )
    assert repeated.status_code == 202 and repeated.json()["replayed"], repeated.text
    assert repeated.json()["operation_id"] == analysis.json()["operation_id"]
    import os
    import subprocess
    import sys
    import time

    script = """
import json,os,sys
from pathlib import Path
from novel_forge.api.authority_dependencies import build_production_execution_composition,build_source_import_application
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.source_import import SourceImportScheduler
settings=IndustrialSettings(root=Path(sys.argv[3]),environment='test',database_url=os.environ['NOVEL_FORGE_DATABASE_URL'])
app=build_source_import_application(settings,execution=build_production_execution_composition(settings))
if sys.argv[4]=='crash':
 original=app.execute_fenced
 def crash(worker):
  original(worker)
  os._exit(74)
 app.execute_fenced=crash
print(json.dumps(SourceImportScheduler(app,worker_id='curated-'+sys.argv[4],lease_seconds=1).run_or_recover(operation_id=sys.argv[1],project_id=sys.argv[2]),default=str))
"""
    args = [
        sys.executable,
        "-c",
        script,
        analysis.json()["operation_id"],
        corpus.project,
        str(tmp_path),
    ]
    died = subprocess.run(
        [*args, "crash"],
        env=dict(os.environ),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert died.returncode == 74, died.stderr
    time.sleep(2)
    recovered = subprocess.run(
        [*args, "recover"],
        env=dict(os.environ),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert recovered.returncode == 0, recovered.stderr
    queued = json.loads(recovered.stdout)
    assert queued["status"] == "SUCCEEDED", queued
    member = scheduler.run_or_recover(
        operation_id=queued["result"]["children"][0]["operation_id"],
        project_id=corpus.project,
    )
    assert member["result"]["stage"] == "SOURCE_ANALYSIS_SCHEDULED"
    job = analysis.json()["import_job_id"]
    for _ in range(30):
        rows = corpus.client.get(
            f"/product/source-imports/{job}/work", params={"project_id": corpus.project}
        ).json()
        pending = {
            o
            for o, p in scheduler.pending_operations(limit=1000)
            if p == corpus.project
        }
        row = next((r for r in rows if r["operation_id"] in pending), None)
        if row is None:
            break
        if invalidate_after_model and row["work_kind"] == "PROFILING":
            with pytest.raises(KernelError, match="CURATED_PROVIDER_INPUT_STALE"):
                scheduler.run_or_recover(
                    operation_id=row["operation_id"], project_id=corpus.project
                )
            with psycopg.connect(DATABASE_URL) as connection:
                assert (
                    connection.execute(
                        "SELECT count(*) FROM authority_operation_output_asset out JOIN authority_operation op USING(operation_id) WHERE op.project_id=%s AND out.output_key='source.content.profile'",
                        [corpus.project],
                    ).fetchone()[0]
                    == 0
                )
                receipts = connection.execute(
                    "SELECT count(*) FROM authority_external_effect_dispatch d JOIN authority_external_effect e USING(external_effect_id) WHERE e.project_id=%s AND d.receipt_id IS NOT NULL",
                    [corpus.project],
                ).fetchone()[0]
                assert receipts > 0
            with pytest.raises(
                KernelError,
                match="CURATED_PROVIDER_INPUT_STALE|CURATED_MEMBERS_UNAVAILABLE",
            ):
                scheduler.run_or_recover(
                    operation_id=row["operation_id"], project_id=corpus.project
                )
            with psycopg.connect(DATABASE_URL) as connection:
                assert (
                    connection.execute(
                        "SELECT count(*) FROM authority_external_effect_dispatch d JOIN authority_external_effect e USING(external_effect_id) WHERE e.project_id=%s AND d.receipt_id IS NOT NULL",
                        [corpus.project],
                    ).fetchone()[0]
                    == receipts
                )
            return
        scheduler.run_or_recover(
            operation_id=row["operation_id"], project_id=corpus.project
        )
    assert any(
        r["work_kind"] == "PROFILING" and r["status"] == "SUCCEEDED" for r in rows
    ), rows
    assert any(r["work_kind"] == "MKAOS_EXTRACTION" for r in rows), rows
    assert all(r["status"] in {"SUCCEEDED", "REUSED", "BLOCKED"} for r in rows), rows
    with psycopg.connect(DATABASE_URL) as connection:
        count = connection.execute(
            "SELECT count(*) FROM authority_budget_reservation WHERE project_id=%s",
            (corpus.project,),
        ).fetchone()[0]
    assert count > 0
    work_revision = work["revisions"][0]
    corpus.run(
        {
            "action": "resolve_canonical_works",
            "changes": [
                {
                    "work_key": "key-story",
                    "previous_id": work_revision["revision_id"],
                    "title": "钥匙与来信",
                    "state": "RETIRED",
                    "metadata_evidence": ["operator:withdraw-selection"],
                    "members": [],
                }
            ],
            "reason": "withdraw current identity assignment, preserve history",
        }
    )
    blocked = corpus.client.post(
        "/product/source-imports/corpus/analyze",
        json={**request, "run_key": "after-revision"},
    )
    assert blocked.status_code == 409 and "CURATED_MEMBERS_UNAVAILABLE" in blocked.text
    state = corpus.client.get(
        "/product/source-imports/corpus/catalog/curated/" + frozen["corpus_id"],
        params={"project_id": corpus.project},
    ).json()
    assert state["current_availability"][0]["reasons"] == [
        "CANONICAL_MEMBERSHIP_REVISED"
    ]
    replay = scheduler.run_or_recover(
        operation_id=analysis.json()["operation_id"], project_id=corpus.project
    )
    assert replay["status"] == "SUCCEEDED"
    with psycopg.connect(DATABASE_URL) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM authority_budget_reservation WHERE project_id=%s",
                (corpus.project,),
            ).fetchone()[0]
            == count
        )
    with pytest.raises(KernelError, match="CORPUS_CATALOG_STALE"):
        corpus.run({**candidate_action, "previous_id": candidate["revision_id"]})


def test_native_multifile_duplicate_review_relations_and_discovery(
    corpus, tmp_path, monkeypatch
):
    from novel_forge.modules.command_kernel.errors import KernelError

    app, scheduler = _runtime(tmp_path, monkeypatch)
    text = "她将钥匙还给守门人，决定承担迟到的代价。这段誓词在不同场合被完整复述。" * 12
    parser = {
        "version": "corpus-parser.v3",
        "format": "html",
        "constants": {"work_id": "one-work"},
        "normalization": {
            "version": "chinese-longform.v2",
            "external_work_ids": ["original:comparison-test"],
        },
    }

    def ingest(name, variant=""):
        directory = tmp_path / name
        directory.mkdir()
        for n in (1, 2):
            (directory / f"{n}.html").write_text(
                f"<body><h1>第{n}章 场合{n}</h1><p>{text}{variant}</p></body>"
            )
        manifest = {**_manifest(directory), "parser": parser}
        admitted = corpus.client.post(
            "/product/source-imports/corpus",
            json={
                "project_id": corpus.project,
                "workspace_id": corpus.workspace,
                "run_key": name,
                "manifest": manifest,
            },
        )
        assert admitted.status_code == 202, admitted.text
        acquired = scheduler.run_or_recover(
            operation_id=admitted.json()["operation_id"], project_id=corpus.project
        )
        result = scheduler.run_or_recover(
            operation_id=acquired["result"]["children"][0]["operation_id"],
            project_id=corpus.project,
        )
        assert result["status"] == "SUCCEEDED", result
        return result["result"]

    def inspect(identity, **params):
        response = corpus.client.get(
            "/product/source-imports/corpus/processing/" + identity,
            params={"project_id": corpus.project, **params},
        )
        assert response.status_code == 200, response.text
        return response.json()

    first = ingest("first")
    assessment = inspect(first["processing_id"])["assessment"]
    finding = next(i for i in assessment["issues"] if i["code"] == "DUPLICATE_BODY")
    assert len(finding["evidence"]) == 2 and not assessment["structure_usable"]
    action = {
        "action": "review_processing",
        "processing_id": first["processing_id"],
        "decisions": [
            {
                "issue_id": finding["issue_id"],
                "resolution": "CONFIRM_LEGITIMATE_REPETITION",
                "reason": "original test explicitly repeats its oath",
            }
        ],
        "reason": "scoped repeated event",
    }
    with pytest.raises(KernelError, match="CORPUS_SCOPED_EVIDENCE_REQUIRED"):
        corpus.run(action)
    reviewed = corpus.run(
        {
            **action,
            "decisions": [
                {
                    **action["decisions"][0],
                    "evidence_refs": ["operator:two-original-oath-occurrences"],
                    "classification": "LEGITIMATE_REPETITION",
                }
            ],
        }
    )
    assert reviewed["status"] == "SUCCEEDED"
    reprocess = corpus.client.post(
        "/product/source-imports/corpus/reprocess",
        json={
            "project_id": corpus.project,
            "edition_id": first["edition_id"],
            "run_key": "reviewed",
            "parser": parser,
        },
    )
    assert reprocess.status_code == 202, reprocess.text
    processed = scheduler.run_or_recover(
        operation_id=reprocess.json()["operation_id"], project_id=corpus.project
    )["result"]
    assert processed["structure_usable"]
    newest = inspect(processed["processing_id"])
    assert any(
        i.get("resolution")
        for i in newest["assessment"]["issues"]
        if i["code"] == "DUPLICATE_BODY"
    )
    second = ingest("copy")
    third = ingest("other", "这段后续内容改变了场景，并表明不同的叙事后果。" * 5)
    page = inspect(processed["processing_id"], discover=True, limit=1)
    assert (
        page["evaluated_on_page"] == 1
        and page["candidates"][0]["processing_id"] == second["processing_id"]
    )
    assert page["candidates"][0]["exact_text"] and page["next_cursor"]
    page2 = inspect(
        processed["processing_id"], discover=True, limit=1, after=page["next_cursor"]
    )
    assert (
        page2["evaluated_total"] == 2
        and page2["candidates"][0]["processing_id"] == third["processing_id"]
    )
    wrong = corpus.client.get(
        "/product/source-imports/corpus/processing/" + second["processing_id"],
        params={
            "project_id": corpus.project,
            "discover": True,
            "after": page["next_cursor"],
        },
    )
    assert wrong.status_code == 409 and "CURSOR_STALE" in wrong.text
    different = corpus.run(
        {
            "action": "declare_relation",
            "left_id": processed["processing_id"],
            "right_id": second["processing_id"],
            "relation": "DIFFERENT_WORK",
            "evidence_refs": ["operator:synthetic-counterfactual-identity"],
            "reason": "identical bytes do not determine work identity",
        }
    )

    def member(identity):
        return {
            "processing_id": identity,
            "relation": "SAME_WORK",
            "evidence_refs": ["operator:explicit-membership"],
        }

    def group(key, members, **extra):
        return {
            "work_key": key,
            "title": key,
            "metadata_evidence": ["operator:group-decision"],
            "members": members,
            **extra,
        }

    with pytest.raises(KernelError, match="CORPUS_CANONICAL_CONFLICT"):
        corpus.run(
            {
                "action": "resolve_canonical_works",
                "changes": [
                    group(
                        "merged",
                        [
                            member(processed["processing_id"]),
                            member(second["processing_id"]),
                        ],
                    )
                ],
                "reason": "negative relation must prevent merge",
            }
        )
    corpus.run(
        {
            "action": "declare_relation",
            "left_id": processed["processing_id"],
            "right_id": second["processing_id"],
            "previous_id": different["decision_id"],
            "relation": "SAME_EDITION_COPY",
            "evidence_refs": ["operator:corrected-source-identity"],
            "reason": "explicitly supersede mistaken negative evidence",
        }
    )
    groups = corpus.run(
        {
            "action": "resolve_canonical_works",
            "changes": [
                group("a", [member(processed["processing_id"])]),
                group("b", [member(second["processing_id"])]),
            ],
            "reason": "initial explicit groups",
        }
    )["revisions"]
    merged = corpus.run(
        {
            "action": "resolve_canonical_works",
            "changes": [
                group(
                    "a",
                    [
                        member(processed["processing_id"]),
                        member(second["processing_id"]),
                    ],
                    previous_id=groups[0]["revision_id"],
                ),
                group("b", [], previous_id=groups[1]["revision_id"], state="RETIRED"),
            ],
            "reason": "atomic explicit merge retains both source editions",
        }
    )["revisions"]
    split = corpus.run(
        {
            "action": "resolve_canonical_works",
            "changes": [
                group(
                    "a",
                    [member(processed["processing_id"])],
                    previous_id=merged[0]["revision_id"],
                ),
                group(
                    "b",
                    [member(second["processing_id"])],
                    previous_id=merged[1]["revision_id"],
                ),
            ],
            "reason": "atomic correction splits membership without rewriting history",
        }
    )
    assert len(split["revisions"]) == 2
    historical = corpus.client.get(
        "/product/source-imports/corpus/catalog/work/" + merged[0]["revision_id"],
        params={"project_id": corpus.project, "revision": True},
    )
    assert historical.status_code == 200 and len(historical.json()["members"]) == 2


def test_native_catalogue_resolution_preserves_input_scope(
    corpus, tmp_path, monkeypatch
):
    from novel_forge.modules.command_kernel.errors import KernelError

    app, scheduler = _runtime(tmp_path, monkeypatch)
    path = tmp_path / "toc.txt"
    path.write_text(
        "第一章 交付\n"
        + "甲把钥匙交给乙，留下口信。" * 15
        + "\n第二章 回报\n"
        + "乙准时赶到桥边，答谢船夫。" * 15
    )
    parser = {
        "version": "corpus-parser.v3",
        "format": "txt",
        "constants": {"work_id": "toc-original"},
        "normalization": {
            "version": "chinese-longform.v2",
            "expected_toc": ["第01章：交付", "第二章 报答"],
            "toc_evidence": "sha256:catalogue-A",
        },
    }
    response = corpus.client.post(
        "/product/source-imports/corpus",
        json={
            "project_id": corpus.project,
            "workspace_id": corpus.workspace,
            "run_key": "toc-import",
            "manifest": {**_manifest(path), "parser": parser},
        },
    )
    assert response.status_code == 202, response.text
    root = scheduler.run_or_recover(
        operation_id=response.json()["operation_id"], project_id=corpus.project
    )
    result = scheduler.run_or_recover(
        operation_id=root["result"]["children"][0]["operation_id"],
        project_id=corpus.project,
    )["result"]

    def inspect(identity):
        response = corpus.client.get(
            "/product/source-imports/corpus/processing/" + identity,
            params={"project_id": corpus.project},
        )
        assert response.status_code == 200, response.text
        return response.json()

    first = inspect(result["processing_id"])
    findings = [
        i for i in first["assessment"]["issues"] if i["code"] == "TOC_ENTRY_MISMATCH"
    ]
    assert len(findings) == 1 and findings[0]["toc_index"] == 1
    review = corpus.run(
        {
            "action": "review_processing",
            "processing_id": first["processing_id"],
            "decisions": [
                {
                    "issue_id": findings[0]["issue_id"],
                    "resolution": "CONFIRM_TOC_VARIANT",
                    "classification": "VERSION_WORDING",
                    "evidence_refs": ["sha256:catalogue-A", "original:chapter-two"],
                    "reason": "Both located titles denote the same bounded chapter; wording retained.",
                }
            ],
            "reason": "scope title variant to this exact catalogue",
        }
    )
    assert review["assessment"]["structure_usable"]

    def reprocess(profile, key):
        response = corpus.client.post(
            "/product/source-imports/corpus/reprocess",
            json={
                "project_id": corpus.project,
                "edition_id": result["edition_id"],
                "run_key": key,
                "parser": profile,
            },
        )
        assert response.status_code == 202, response.text
        outcome = scheduler.run_or_recover(
            operation_id=response.json()["operation_id"], project_id=corpus.project
        )
        return inspect(outcome["result"]["processing_id"])

    second = reprocess(parser, "same-catalogue")
    assert second["assessment"]["structure_usable"]
    assert any(
        i.get("resolution", {}).get("resolution") == "CONFIRM_TOC_VARIANT"
        for i in second["assessment"]["issues"]
    )
    different = {
        **parser,
        "normalization": {
            **parser["normalization"],
            "expected_toc": ["第一章 交付", "第二章 大火", "第三章 归来"],
            "toc_evidence": "sha256:catalogue-B",
        },
    }
    third = reprocess(different, "new-catalogue")
    assert not third["assessment"]["structure_usable"]
    unresolved = [
        i
        for i in third["assessment"]["issues"]
        if i["code"] == "TOC_ENTRY_MISMATCH" and i["blocking"]
    ]
    assert len(unresolved) == 2
    missing = next(i for i in unresolved if i["observed_title"] is None)
    with pytest.raises(KernelError, match="CORPUS_MISSING_CONTENT_CANNOT_BE_WAIVED"):
        corpus.run(
            {
                "action": "review_processing",
                "processing_id": third["processing_id"],
                "decisions": [
                    {
                        "issue_id": missing["issue_id"],
                        "resolution": "CONFIRM_TOC_VARIANT",
                        "classification": "VERSION_WORDING",
                        "evidence_refs": ["sha256:catalogue-B"],
                        "reason": "missing content is not a title variation",
                    }
                ],
                "reason": "must fail closed",
            }
        )
    page = corpus.client.get(
        "/product/source-imports/corpus/processing/" + second["processing_id"],
        params={
            "project_id": corpus.project,
            "compare_to": third["processing_id"],
            "limit": 1,
        },
    ).json()["comparison"]
    assert page["next_cursor"] and len(page["correspondence"]) == 1
    rest = corpus.client.get(
        "/product/source-imports/corpus/processing/" + second["processing_id"],
        params={
            "project_id": corpus.project,
            "compare_to": third["processing_id"],
            "limit": 1,
            "after": page["next_cursor"],
        },
    ).json()["comparison"]
    assert (
        rest["query_identity"] == page["query_identity"]
        and rest["correspondence"][0]["left"] == 1
    )
    wrong = corpus.client.get(
        "/product/source-imports/corpus/processing/" + first["processing_id"],
        params={
            "project_id": corpus.project,
            "compare_to": third["processing_id"],
            "after": page["next_cursor"],
        },
    )
    assert wrong.status_code == 409 and "CURSOR_INVALID" in wrong.text

    review = corpus.run(
        {
            "action": "review_processing",
            "processing_id": third["processing_id"],
            "decisions": [
                {
                    "issue_id": missing["issue_id"],
                    "resolution": "ANNOTATE_TOC_DIFFERENCE",
                    "classification": "INSUFFICIENT",
                    "evidence_refs": ["sha256:catalogue-B"],
                    "reason": "Directory claims an absent chapter, retain blocking uncertainty",
                }
            ],
            "reason": "annotation changes review evidence, not prose",
        }
    )
    fourth = reprocess(different, "annotation-only-new-processing")
    assert fourth["normalized_hash"] == third["normalized_hash"]
    assert (
        fourth["source_work_asset_version_id"] != third["source_work_asset_version_id"]
    )
    assert not fourth["assessment"]["structure_usable"]
    assert any(i.get("annotations") for i in fourth["assessment"]["issues"])


@pytest.mark.parametrize("bounded_reading", [False, True])
def test_native_cli_curated_analysis_controls_results_and_relation_guards(
    corpus, tmp_path, monkeypatch, bounded_reading
):
    import os
    from pathlib import Path
    import subprocess
    import sys
    from uuid import uuid4

    _runtime(tmp_path, monkeypatch)
    script = """
import sys,json
from novel_forge.api import authority_dependencies as d
from novel_forge.modules.source_import.execution_contracts import content_intelligence_fixture_response,CLASSIFICATION_STAGE
def transport(stage, inputs):
 if stage == CLASSIFICATION_STAGE:
  return {'content_type':'PUBLISHED_FICTION','confidence':0.97,'alternatives':[{'content_type':'PUBLISHED_FICTION','confidence':0.97},{'content_type':'UNKNOWN','confidence':0.03}],'evidence_codes':['BOUNDED_SEMANTIC_SAMPLE'],'boundary_assessment':{'scope_kind':'FILE_DOCUMENT','suspected_document_count':1,'review_required':False}}
 if inputs.get('narrative_contract'):
  context=inputs['reading_context']
  prior=context['prior_issues']
  if 'review_target' in inputs:
   if context['repair_round']==0:
    return {'decision':'REVISE','issues':[{'issue_id':'fixture-specificity','finding_code':'choice','category':'VAGUE_SUMMARY','severity':'BLOCKING','reason':'State the evidenced choice and cost, not a generic summary.','repair_goal':'Tie the statement to the action in the exact supplied span.','acceptance_condition':'The observation names the supported action and distinguishes unknown consequence.'}],'resolved_issue_ids':[],'preserve_requirements':['Keep the exact input boundary and uncertainty.'],'scope_limitations':'Scripted diagnostic, not an independent editorial review.'}
   return {'decision':'ACCEPT_IN_SCOPE','issues':[],'resolved_issue_ids':[i['issue_id'] for i in prior],'preserve_requirements':[],'scope_limitations':'Only the supplied target is evaluated; literary quality is unproven.'}
  segments=inputs.get('source_segments') or []
  evidence=[]
  if segments:
   segment=segments[0];value=segment['content'].splitlines(keepends=True)[0]
   evidence=[{'chunk_id':segment['source_chunk_asset_version_id'],'byte_start':0,'byte_end':len(value.encode()),'support_text':value}]
  return {'findings':[{'finding_code':'choice','statement':'The character makes a costly choice in this bounded source window; later consequences remain unknown.' if context['repair_round'] else 'A choice occurs.', 'dimension':context['dimensions'][0],'certainty':'SUPPORTED_INFERENCE','perspective':'ANALYST_INFERENCE','entity_ids':[],'caused_by':[],'causal_basis':'','supports':evidence,'input_observation_asset_version_ids':inputs.get('input_observation_asset_version_ids') or []}],'entities':[],'confidence':0.7,'knowledge_status':'NOT_ABSTRACTED','scope_limitations':'Only the provided units or lower observations; no external plot knowledge.'}
 return content_intelligence_fixture_response(stage,inputs)
d.content_intelligence_fixture_response=transport
from novel_forge.cli.authority import main
sys.exit(main(sys.argv[1:]))
"""
    transcript = []

    def cli(action, *args, success=True):
        command = [
            sys.executable,
            "-c",
            script,
            "corpus",
            action,
            "--project-id",
            corpus.project,
            *map(str, args),
        ]
        run = subprocess.run(
            command,
            env=dict(os.environ),
            capture_output=True,
            text=True,
            timeout=240 if bounded_reading else 120,
        )
        transcript.append(
            {
                "action": action,
                "args": list(map(str, args)),
                "exit_code": run.returncode,
                "stdout": run.stdout,
                "stderr": run.stderr,
            }
        )
        if directory := os.environ.get("CORPUS_EVIDENCE_DIR"):
            Path(directory, "native-operations.json").write_text(
                json.dumps(transcript, ensure_ascii=False, indent=2)
            )
        if not success:
            assert run.returncode != 0, run.stdout
            return run.stderr
        assert run.returncode in ({0, 2, 3} if action == "run" else {0}), (
            run.stdout,
            run.stderr,
        )
        value = json.loads(run.stdout)
        if action == "run":
            assert (run.returncode == 0) == (value["stop_reason"] == "COMPLETED")
        return value

    def decision(action, payload, success=True):
        path = tmp_path / (str(uuid4()) + ".json")
        path.write_text(json.dumps(payload))
        return cli(
            action,
            "--workspace-id",
            corpus.workspace,
            "--run-key",
            uuid4(),
            "--decision",
            path,
            success=success,
        )

    members = []
    for n in range(2):
        path = tmp_path / f"novel-{n}.txt"
        path.write_text(
            "第一章 选择\n"
            + (
                "阿青归还钥匙，承担失约的代价。"
                if n == 0
                else "守门人送出家书，拒绝交出信任。"
            )
            * 20
            + "\n第二章 回信\n"
            + (
                "弟弟读过信，愿意独自守门。"
                if n == 0
                else "姐姐履行约定，替母亲照看院子。"
            )
            * 20
        )
        manifest = {
            **_manifest(path),
            "parser": {
                "version": "corpus-parser.v3",
                "format": "txt",
                "constants": {"work_id": f"original-{n}"},
                "normalization": {"version": "chinese-longform.v2"},
            },
        }
        config = tmp_path / f"manifest-{n}.json"
        config.write_text(json.dumps(manifest))
        admitted = cli(
            "import",
            "--workspace-id",
            corpus.workspace,
            "--manifest",
            config,
            "--run-key",
            f"import-{n}",
        )
        cli("run", "--job-id", admitted["import_job_id"], "--max-stages", 8)
        lineage = cli("lineage", "--job-id", admitted["import_job_id"])
        edition = lineage["editions"][0]["edition_id"]
        inspected = cli("inspect", "--edition-id", edition)
        members.append(inspected)
    grouped = decision(
        "resolve-work",
        {
            "action": "resolve_canonical_works",
            "changes": [
                {
                    "work_key": "original-library",
                    "title": "同源原创版本示例",
                    "language": "zh",
                    "metadata_evidence": ["synthetic:controlled-test-revisions"],
                    "members": [
                        {
                            "processing_id": m["processing_id"],
                            "relation": "REVISION",
                            "evidence_refs": ["synthetic:controlled-test-revisions"],
                        }
                        for m in members
                    ],
                }
            ],
            "reason": "explicit fixture relation; similarity is not identity",
        },
    )
    for action, typed in [("equivalence", False), ("relate", True)]:
        error = decision(
            action,
            {
                "action": "declare_relation" if typed else "decide_equivalence",
                "left_id": members[0]["processing_id"],
                "right_id": members[1]["processing_id"],
                **({"relation": "DIFFERENT_WORK"} if typed else {"decision": "REJECT"}),
                "evidence_refs": ["synthetic:negative-conflict"],
                "reason": "must split before negative relation",
            },
            success=False,
        )
        assert "CORPUS_SPLIT_REQUIRED" in error
    candidate = {
        "action": "revise_curated_corpus",
        "corpus_key": "operations-set",
        "title": "精选操作测试",
        "purpose": "RESEARCH",
        "filters": {"language": "zh"},
        "reason": "inspect two explicitly scoped members",
    }
    opened = decision("curate", candidate)
    frozen = decision(
        "curate",
        {
            **candidate,
            "previous_id": opened["revision_id"],
            "state": "FROZEN",
            "choices": [
                {
                    "processing_id": m["processing_id"],
                    "selected": True,
                    "reason": "eligible original structure",
                    "evidence_refs": ["synthetic:reviewed"],
                }
                for m in members
            ],
        },
    )
    assert cli("curated", "--revision-id", frozen["revision_id"])[
        "analysis_dispatchable"
    ]

    scope_args = []
    if bounded_reading:
        scopes = []
        with psycopg.connect(DATABASE_URL) as connection:
            for member in members:
                versions = connection.execute(
                    "SELECT source_unit_version_id FROM authority_source_unit_version WHERE source_work_asset_version_id=%s AND status='AVAILABLE' AND kind='chapter' ORDER BY ordinal",
                    [member["source_work_asset_version_id"]],
                ).fetchall()
                assert len(versions) == 2
                scopes.append(
                    {
                        "processing_id": member["processing_id"],
                        "first_unit_version_id": versions[0][0],
                        "last_unit_version_id": versions[-1][0],
                        "max_repairs": 1,
                    }
                )
        scope_file = tmp_path / "reading-scopes.json"
        scope_file.write_text(json.dumps(scopes))
        scope_args = ["--reading-scopes", scope_file]

    def analyze(key, calls=50):
        return cli(
            "analyze",
            "--revision-id",
            frozen["revision_id"],
            "--run-key",
            key,
            "--limit",
            2,
            "--max-calls",
            calls,
            "--max-tokens",
            500000,
            "--authorization-ref",
            "scripted-engineering-no-paid-calls",
            *scope_args,
        )

    admitted = analyze("native-analysis")
    job = admitted["import_job_id"]
    assert cli("status", "--job-id", job)["corpus"]["selected_members"] == 2
    from novel_forge.storage.source_import_repositories import SourceImportRepository

    with psycopg.connect(DATABASE_URL) as connection:
        other = connection.execute(
            "SELECT import_job_id,operation_id FROM authority_source_import_work WHERE project_id=%s AND import_job_id<>%s LIMIT 1",
            [corpus.project, job],
        ).fetchone()
        connection.execute(
            """INSERT INTO authority_operation SELECT (jsonb_populate_record(NULL::authority_operation,to_jsonb(o)||jsonb_build_object('operation_id','query-fixture-'||n,'idempotency_key','query-fixture-'||n,'status','READY','created_at','2000-01-01T00:00:00Z'))).* FROM authority_operation o CROSS JOIN generate_series(1,5000)n WHERE o.operation_id=%s""",
            [other[1]],
        )
        connection.execute(
            """INSERT INTO authority_source_import_work SELECT (jsonb_populate_record(NULL::authority_source_import_work,to_jsonb(w)||jsonb_build_object('work_id','query-fixture-'||n,'stable_key','query-fixture-'||n,'operation_id','query-fixture-'||n,'status','PLANNED'))).* FROM authority_source_import_work w CROSS JOIN generate_series(1,5000)n WHERE w.operation_id=%s""",
            [other[1]],
        )
        connection.execute("ANALYZE authority_source_import_work")
        connection.execute("ANALYZE authority_operation")
        with connection.cursor() as cursor:
            repository = SourceImportRepository(cursor)
            assert repository.job_ready_operations(corpus.project, job, 1) == (
                (admitted["operation_id"], corpus.project),
            )
        plan = connection.execute(
            """EXPLAIN(ANALYZE,BUFFERS,FORMAT JSON) SELECT o.operation_id FROM authority_source_import_work w JOIN authority_operation o USING(operation_id,project_id) WHERE w.project_id=%s AND w.import_job_id=%s ORDER BY o.created_at,o.operation_id LIMIT 10""",
            [corpus.project, job],
        ).fetchone()[0]

        def nodes(node):
            yield node
            for child in node.get("Plans", []):
                yield from nodes(child)

        assert all(
            "Index" in n["Node Type"]
            for n in nodes(plan[0]["Plan"])
            if n.get("Relation Name")
            in {"authority_source_import_work", "authority_operation"}
        ), plan
        if directory := os.environ.get("CORPUS_EVIDENCE_DIR"):
            Path(directory, "job-query-plan.json").write_text(
                json.dumps(
                    {
                        "plan": plan,
                        "unrelated_ready_rows": 5000,
                        "planner_settings_changed": False,
                        "fixture_rolled_back": True,
                    },
                    indent=2,
                )
            )
        connection.rollback()
    initial = cli("run", "--job-id", job, "--max-stages", 1)
    assert initial["stop_reason"] == "MAX_STAGES" and initial["remaining_stages"] == 2
    cli("pause", "--job-id", job)
    assert cli("run", "--job-id", job)["stop_reason"] == "PAUSED"
    cli("resume", "--job-id", job)
    outcome = cli("run", "--job-id", job, "--max-stages", 100)
    assert outcome["stop_reason"] == "COMPLETED", outcome
    stages = []
    after = ""
    while True:
        page = cli("results", "--job-id", job, "--limit", 3, "--after", after)
        stages.extend(page["stages"])
        after = page["next_after"]
        if not after:
            break
    assert {s["processing_id"] for s in stages if s["kind"] == "PROFILING"} == {
        m["processing_id"] for m in members
    }
    assert all(s["status"] == "SUCCEEDED" for s in stages), stages
    assert page["summary"]["knowledge"]["knowledge_candidates"] > 0, page
    assert page["summary"]["knowledge"]["knowledge_cards"] == 0
    assert all(s["outputs"] for s in stages if s["kind"] == "MKAOS_EXTRACTION")
    before = cli("status", "--job-id", job)["corpus"]["budget"]
    assert analyze("native-analysis")["replayed"]
    assert cli("run", "--job-id", job)["stages"] == []
    assert cli("status", "--job-id", job)["corpus"]["budget"] == before
    assert (
        cli("lineage", "--job-id", job)["summary"]["revision_id"]
        == frozen["revision_id"]
    )
    cancelled = analyze("cancel-analysis")
    cli("cancel", "--job-id", cancelled["import_job_id"])
    assert (
        cli("run", "--job-id", cancelled["import_job_id"])["stop_reason"] == "CANCELLED"
    )
    policy = tmp_path / "bounded-policy.json"
    policy.write_text(json.dumps({"max_sample_chunks": 2}))
    partial = cli(
        "analyze",
        "--revision-id",
        frozen["revision_id"],
        "--run-key",
        "budget-bound-analysis",
        "--limit",
        2,
        "--max-calls",
        1,
        "--max-tokens",
        500000,
        "--authorization-ref",
        "scripted-engineering-no-paid-calls",
        "--manifest",
        policy,
    )
    limited = cli("run", "--job-id", partial["import_job_id"], "--max-stages", 50)
    assert limited["job"]["corpus"]["analysis_state"] in {
        "PARTIAL",
        "BLOCKED",
        "FAILED",
    }, limited
    assert (
        cli("results", "--job-id", partial["import_job_id"])["summary"]["failed_stages"]
        > 0
    )
    for action, typed in [("equivalence", False), ("relate", True)]:
        error = decision(
            action,
            {
                "action": "declare_relation" if typed else "decide_equivalence",
                "left_id": members[0]["processing_id"],
                "right_id": members[1]["processing_id"],
                **({"relation": "DIFFERENT_WORK"} if typed else {"decision": "REJECT"}),
                "evidence_refs": ["synthetic:frozen-negative-conflict"],
                "reason": "frozen consumers do not permit group contradictions",
            },
            success=False,
        )
        assert "CORPUS_SPLIT_REQUIRED" in error
    with psycopg.connect(DATABASE_URL) as connection:
        with pytest.raises(
            psycopg.errors.CheckViolation, match="canonical members contradict"
        ):
            with connection.transaction():
                connection.execute(
                    """INSERT INTO authority_corpus_equivalence(decision_id,project_id,left_id,right_id,canonical_work_id,decision,relation,evidence,reason,created_by_operation_id)
                    VALUES(%s,%s,%s,%s,%s,'REJECT','DIFFERENT_WORK','{}','illegal database negative',%s)""",
                    [
                        str(uuid4()),
                        corpus.project,
                        *sorted(m["processing_id"] for m in members),
                        grouped["revisions"][0]["work_id"],
                        grouped["operation_id"],
                    ],
                )
                connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    relation = decision(
        "relate",
        {
            "action": "declare_relation",
            "left_id": members[0]["processing_id"],
            "right_id": members[1]["processing_id"],
            "relation": "REVISION",
            "evidence_refs": ["synthetic:new-precise-version-evidence"],
            "reason": "new relation evidence requires explicit selection refresh",
        },
    )
    assert relation["relation"] == "REVISION"
    stale = cli("curated", "--revision-id", frozen["revision_id"])
    assert not stale["analysis_dispatchable"]
    assert all(
        "RELATION_EVIDENCE_CHANGED" in r["reasons"]
        for r in stale["current_availability"]
    )
    assert analyze("native-analysis")["replayed"]
    assert (
        cli("results", "--job-id", job)["summary"]["knowledge"]["knowledge_candidates"]
        > 0
    )
    assert grouped["revisions"]
