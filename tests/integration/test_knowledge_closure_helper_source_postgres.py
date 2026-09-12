from __future__ import annotations

import hashlib
import json

import psycopg
import pytest

from scripts.prepare_knowledge_closure import prepare
from novel_forge.api import authority_dependencies
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority import (
    ApproveKnowledgeCandidateCommand,
    MkaosAuthorityApplication,
    MkaosAuthorityQuery,
)
from novel_forge.modules.provider_qualification.source_binding import (
    require_source_runtime_qualification,
)
from novel_forge.modules.provider_qualification.domain import request_hash
from novel_forge.modules.source_import.execution_contracts import (
    CLASSIFICATION_STAGE,
    content_intelligence_fixture_response,
)
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.test_corpus_ingestion_postgres import _runtime

pytest_plugins = ["tests.integration.test_corpus_foundation_postgres"]


@pytest.mark.parametrize(
    "sample,content_type,units",
    [("professional", "PROFESSIONAL_KNOWLEDGE", 3), ("fiction", "WEB_NOVEL", 6)],
)
def test_default_helper_import_curated_analysis_reaches_fixture_review_without_production_upgrade(
    corpus, tmp_path, monkeypatch, sample, content_type, units
):
    def source_fixture(stage, inputs):
        if stage == CLASSIFICATION_STAGE:
            return {
                "content_type": content_type,
                "confidence": 0.97,
                "alternatives": [
                    {"content_type": content_type, "confidence": 0.97},
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
        authority_dependencies, "content_intelligence_fixture_response", source_fixture
    )
    app, scheduler = _runtime(tmp_path, monkeypatch)
    folder = tmp_path / "helper-inputs"
    frozen_inputs = prepare(folder, target_book_id="intended-book:" + corpus.project)
    manifest_path = folder / f"{sample}-import.json"
    assert (
        frozen_inputs["files"][manifest_path.name]
        == "sha256:" + hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    )
    manifest = json.loads(manifest_path.read_text())
    imported = corpus.client.post(
        "/product/source-imports/corpus",
        json={
            "project_id": corpus.project,
            "workspace_id": corpus.workspace,
            "run_key": sample + ":helper-import",
            "manifest": manifest,
        },
    )
    assert imported.status_code == 202, imported.text
    acquired = scheduler.run_or_recover(
        operation_id=imported.json()["operation_id"], project_id=corpus.project
    )["result"]
    assert len(acquired["children"]) == 1
    processed = scheduler.run_or_recover(
        operation_id=acquired["children"][0]["operation_id"], project_id=corpus.project
    )["result"]
    assert processed["unit_count"] == units
    assert processed["analysis_scheduled"] is False
    processing_id = processed["processing_id"]
    work = corpus.run(
        {
            "action": "resolve_canonical_works",
            "changes": [
                {
                    "work_key": sample,
                    "title": sample,
                    "language": "zh",
                    "metadata_evidence": [
                        "repository:original-synthetic-knowledge-closure-fixture"
                    ],
                    "members": [
                        {
                            "processing_id": processing_id,
                            "relation": "SAME_WORK",
                            "evidence_refs": [
                                "repository:original-synthetic-knowledge-closure-fixture"
                            ],
                        }
                    ],
                }
            ],
            "reason": "Review exact original helper sample identity",
        }
    )
    curation = {
        "action": "revise_curated_corpus",
        "corpus_key": sample,
        "title": sample,
        "purpose": manifest["purpose"],
        "filters": {"work_ids": [work["revisions"][0]["work_id"]]},
        "reason": "Select the exact helper snapshot for abstract generation",
    }
    proposed = corpus.run(curation)
    curated = corpus.run(
        {
            **curation,
            "previous_id": proposed["revision_id"],
            "state": "FROZEN",
            "choices": [
                {
                    "processing_id": processing_id,
                    "selected": True,
                    "reason": "Original bounded helper fixture",
                    "evidence_refs": [
                        "repository:original-synthetic-knowledge-closure-fixture"
                    ],
                }
            ],
        }
    )
    analysis_request = {
        "project_id": corpus.project,
        "revision_id": curated["revision_id"],
        "run_key": sample + ":helper-analysis",
        "max_members": 1,
        "max_calls": 120,
        "max_tokens": 500000,
        "authorization_ref": "fixture:scripted-source-no-real-model-authorization",
        **{
            key: frozen_inputs["analysis_target"][key]
            for key in ("intended_use", "target_book_id")
        },
    }
    analysis = corpus.client.post(
        "/product/source-imports/corpus/analyze", json=analysis_request
    )
    assert analysis.status_code == 202, analysis.text
    admission = analysis.json()["consumption_admission"]
    assert (
        admission["source_use_admitted"] is True
        and admission["generation_consumption_allowed"] is False
    )
    assert (
        admission["book_status"] == "PENDING_BOOK_CREATION"
        and admission["knowledge_status"] == "PENDING_CARD_REVIEW"
    )
    assert admission["source_evidence"][0]["source_id"] == acquired["source_id"]
    for _ in range(50):
        pending = [
            (operation, project)
            for operation, project in scheduler.pending_operations(limit=100)
            if project == corpus.project
        ]
        if not pending:
            break
        for operation, project in pending:
            scheduler.run_or_recover(operation_id=operation, project_id=project)
    else:
        pytest.fail("Default helper bounded Source chain did not finish")
    job_path = f"/product/source-imports/{analysis.json()['import_job_id']}"
    status = corpus.client.get(job_path, params={"project_id": corpus.project})
    assert status.status_code == 200, status.text
    assert status.json()["effective_status"] == "AWAITING_GOVERNANCE", status.json()
    stages = []
    after = ""
    while True:
        page_response = corpus.client.get(
            job_path + "/analysis-results",
            params={"project_id": corpus.project, "after": after, "limit": 20},
        )
        assert page_response.status_code == 200, page_response.text
        page = page_response.json()
        stages.extend(page["stages"])
        after = page["next_after"]
        if not after:
            break
    assert stages and all(
        stage["status"] in {"SUCCEEDED", "REUSED"} for stage in stages
    ), stages
    assert page["summary"]["knowledge"]["knowledge_candidates"] > 0
    assert page["summary"]["knowledge"]["knowledge_cards"] == 0
    query = MkaosAuthorityQuery(DATABASE_URL)
    candidates = query.list_candidates(project_id=corpus.project)
    assert candidates, (
        "Default helper purpose and rights must reach actual Source-derived Candidate review"
    )
    candidate = candidates[0]
    assert candidate["candidate_status"] == "NEEDS_REVIEW"
    execution = candidate["content"]["execution_evidence"]
    assert execution["proof"]["fixture_protocol_only"] is True
    assert execution["proof"]["real_provider_proven"] is False
    with pytest.raises(KernelError, match="SOURCE_RUNTIME_QUALIFICATION_REQUIRED"):
        require_source_runtime_qualification(
            DATABASE_URL,
            project_id=corpus.project,
            workspace_id=corpus.workspace,
            execution_asset_version_id=execution["asset_version_id"],
            execution_content_hash=execution["content_hash"],
            candidate_payload_hash=request_hash(candidate["content"]["candidate"]),
        )
    principal = authority_dependencies.build_trusted_principal_resolver().resolve_api_principal()
    approval_command = ApproveKnowledgeCandidateCommand(
        project_id=corpus.project,
        workspace_id=corpus.workspace,
        candidate_asset_version_id=candidate["asset_version_id"],
        policy_version="helper-source-fixture-review.v1",
        rationale="Scripted protocol review only; no real Provider, human or production qualification",
        actor_id=principal.principal_id,
        idempotency_key=corpus.project + ":helper-review",
        trace_id=corpus.project,
        correlation_id=corpus.project,
    )
    normal = MkaosAuthorityApplication(
        DATABASE_URL,
        application_build_id="helper-source-normal-boundary",
        commit_sha="e" * 40,
    )
    with pytest.raises(KernelError, match="MKAOS_FIXTURE_CANDIDATE_NOT_ACTIVATABLE"):
        normal.execute_approval(approval_command, principal=principal)
    approved = app.mkaos_authority.execute_approval(
        approval_command, principal=principal
    )
    assert (
        app.mkaos_authority.execute_approval(approval_command, principal=principal)[
            "asset_version_id"
        ]
        == approved["asset_version_id"]
    )
    card = next(
        item
        for item in query.list_cards(project_id=corpus.project)
        if item["asset_version_id"] == approved["asset_version_id"]
    )
    assert card["content"]["source_policy"]["fixture_protocol_only"] is True
    assert not card["content"]["source_policy"].get("provider_runtime_qualification")
    with pytest.raises(KernelError, match="PLANNING_NARRATIVE_INTELLIGENCE_DRIFT"):
        query.require_planning_card_current(
            project_id=corpus.project,
            asset_version_id=card["asset_version_id"],
            content_hash=card["content_hash"],
        )
    with psycopg.connect(DATABASE_URL) as connection:
        assert connection.execute(
            "SELECT DISTINCT purpose FROM authority_corpus_source WHERE project_id=%s",
            [corpus.project],
        ).fetchall() == [("PRODUCTION_REFERENCE",)]
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM authority_d0_qualification_run WHERE project_id=%s",
                [corpus.project],
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM authority_book WHERE project_id=%s",
                [corpus.project],
            ).fetchone()[0]
            == 0
        )
        calls = connection.execute(
            "SELECT COUNT(*) FROM authority_budget_reservation WHERE project_id=%s AND status=%s",
            [corpus.project, "SETTLED"],
        ).fetchone()[0]
        assert 0 < calls <= analysis_request["max_calls"]
    print(
        json.dumps(
            {
                "sample": sample,
                "settled_scripted_calls": calls,
                "completed_source_stages": len(stages),
                "analysis_status": status.json()["effective_status"],
                "finite_scripted_call_ceiling": analysis_request["max_calls"],
                "helper_manifest_hash": frozen_inputs["files"][manifest_path.name],
                "import_job_id": imported.json()["import_job_id"],
                "curated_revision_id": curated["revision_id"],
                "analysis_job_id": analysis.json()["import_job_id"],
                "candidate_asset_version_id": candidate["asset_version_id"],
                "fixture_card_asset_version_id": card["asset_version_id"],
                "evidence_class": "SCRIPTED_SOURCE_PROTOCOL_ONLY",
                "real_provider_execution": "NOT_RUN",
                "production_approval": "BLOCKED_FIXTURE_EVIDENCE",
                "real_d0_binding": "NOT_PROVEN",
            },
            sort_keys=True,
        )
    )
