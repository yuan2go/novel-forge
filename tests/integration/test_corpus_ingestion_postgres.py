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
def test_native_integrity_review_reprocessing_and_equivalence(corpus, tmp_path, monkeypatch, crash_after_commit):
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.source_authority.corpus import CorpusUse
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    from novel_forge.storage.source_authority_repositories import SourceAuthorityRepository

    app,scheduler=_runtime(tmp_path,monkeypatch)
    path=tmp_path/'chapters.txt'
    path.write_text('版权与版本说明。\n第一章 起因\n'+'甲冒险交出钥匙。'*20+'\n第二章 代价\n'+'乙归还钥匙，承担后果。'*20)
    manifest=_manifest(path)
    parser={'version':'corpus-parser.v2','format':'txt','constants':{'work_id':'original'},'completeness':'UNKNOWN','normalization':{'min_body_chars':10,'expected_toc':['第一章 起因','第二章 代价'],'toc_evidence':'original-test:catalogue-v1'}}
    manifest['parser']=parser
    request={'project_id':corpus.project,'workspace_id':corpus.workspace,'run_key':'normalization','manifest':manifest}
    admitted=corpus.client.post('/product/source-imports/corpus',json=request)
    assert admitted.status_code==202,admitted.text
    acquired=scheduler.run_or_recover(operation_id=admitted.json()['operation_id'],project_id=corpus.project)
    assert acquired['status']=='SUCCEEDED',acquired
    completed=scheduler.run_or_recover(operation_id=acquired['result']['children'][0]['operation_id'],project_id=corpus.project)
    assert completed['status']=='SUCCEEDED',completed
    first=completed['result']
    def inspect(identity,**params):
        response=corpus.client.get('/product/source-imports/corpus/processing/'+identity,params={'project_id':corpus.project,**params})
        assert response.status_code==200,response.text
        return response.json()
    processing=inspect(first['processing_id'])
    assert not processing['assessment']['structure_usable']
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        with pytest.raises(KernelError,match='MKAOS_CORPUS_BRIDGE_REQUIRED'):
            SourceAuthorityRepository(uow.cursor).require_corpus_documents(corpus.project,(first['source_document_id'],),CorpusUse.SOURCE_ANALYSIS)
    finding=next(i for i in processing['assessment']['issues'] if i['code']=='NON_BODY_UNIT')
    reviewed=corpus.run({'action':'review_processing','processing_id':first['processing_id'],'decisions':[{'issue_id':finding['issue_id'],'resolution':'MARK_NON_BODY','reason':'front matter identified in original fixture'}],'reason':'exclude front matter from analysis, preserve raw evidence'})
    assert reviewed['status']=='SUCCEEDED',reviewed
    reprocess_request={'project_id':corpus.project,'edition_id':first['edition_id'],'run_key':'apply-review','parser':parser}
    admitted2=corpus.client.post('/product/source-imports/corpus/reprocess',json=reprocess_request)
    assert admitted2.status_code==202,admitted2.text
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
        args=[sys.executable,'-c',script,admitted2.json()['operation_id'],corpus.project,str(tmp_path)]
        died=subprocess.run([*args,'crash'],env=dict(os.environ),capture_output=True,text=True,timeout=60)
        assert died.returncode==73,died.stderr
        time.sleep(2)
        resumed=subprocess.run([*args,'recover'],env=dict(os.environ),capture_output=True,text=True,timeout=60)
        assert resumed.returncode==0,resumed.stderr
        second=json.loads(resumed.stdout)
    else:
        second=scheduler.run_or_recover(operation_id=admitted2.json()['operation_id'],project_id=corpus.project)
    assert second['status']=='SUCCEEDED',second
    current=inspect(second['result']['processing_id'])
    assert current['edition_id']==processing['edition_id'] and current['parent_id']==processing['processing_id']
    assert current['assessment']['structure_usable']
    assert second['result']['source_document_id']!=first['source_document_id']
    replay=scheduler.run_or_recover(operation_id=admitted2.json()['operation_id'],project_id=corpus.project)
    assert replay['replayed'] and replay['result']==second['result']
    duplicate=corpus.client.post('/product/source-imports/corpus/reprocess',json=reprocess_request)
    assert duplicate.json()['operation_id']==admitted2.json()['operation_id']
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        repository=SourceAuthorityRepository(uow.cursor)
        repository.require_corpus_documents(corpus.project,(second['result']['source_document_id'],),CorpusUse.SOURCE_ANALYSIS)
        with pytest.raises(KernelError,match='MKAOS_CORPUS_BRIDGE_REQUIRED'):
            repository.require_corpus_documents(corpus.project,(first['source_document_id'],),CorpusUse.SOURCE_ANALYSIS)
        uow.cursor.execute('SELECT count(*) FROM authority_corpus_edition WHERE project_id=%s',[corpus.project])
        assert uow.cursor.fetchone()[0]==1
        uow.cursor.execute("SELECT count(*) FROM authority_external_effect WHERE project_id=%s AND capability='source.remote.fetch'",[corpus.project])
        assert uow.cursor.fetchone()[0]==1
    compared=inspect(first['processing_id'],compare_to=current['processing_id'])
    assert not compared['comparison']['exact_text'] and compared['comparison']['rights_transfer'] is False
    decision=corpus.run({'action':'decide_equivalence','left_id':first['processing_id'],'right_id':current['processing_id'],'decision':'ACCEPT','evidence_refs':['original-same-edition-two-parser-revisions'],'reason':'same source edition with reviewed front matter'})
    assert decision['status']=='SUCCEEDED',decision
    revoke=corpus.run({'action':'decide_equivalence','left_id':first['processing_id'],'right_id':current['processing_id'],'previous_id':decision['decision_id'],'decision':'REVOKE','evidence_refs':['test-pair-revocation'],'reason':'demonstrate append-only correction'})
    assert revoke['status']=='SUCCEEDED',revoke

    unchanged=corpus.client.post('/product/source-imports/corpus/reprocess',json={**reprocess_request,'run_key':'same-contract-reuse'})
    assert unchanged.status_code==202,unchanged.text
    reused=scheduler.run_or_recover(operation_id=unchanged.json()['operation_id'],project_id=corpus.project)
    assert reused['status']=='SUCCEEDED',reused
    assert reused['result']['processing_id']==current['processing_id']
    with psycopg.connect(DATABASE_URL) as connection:
        with pytest.raises(psycopg.errors.CheckViolation,match='immutable'):
            connection.execute("UPDATE authority_corpus_processing SET assessment='{}' WHERE processing_id=%s",[current['processing_id']])
        connection.rollback()
        assert connection.execute('SELECT count(*) FROM authority_corpus_processing WHERE edition_id=%s',[current['edition_id']]).fetchone()[0]==2
