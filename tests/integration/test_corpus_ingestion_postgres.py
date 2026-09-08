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
