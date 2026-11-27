import gzip
import hashlib
import json
import os
from pathlib import Path

import pytest

from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
from novel_forge.cli.authority import _authority_parser
from novel_forge.cli.creation import run_creation_command
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.capability_packs.validation_deployment import install_chapter_validation_pack
from novel_forge.modules.chapter_authority import capacity_continuation
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.capability_pack_postgres_support import CapabilityPackPostgresHarness
from tests.integration.creative_validation_production_support import controlled_member_environment
from tests.integration.synthesis_production_support import AdviceOnlySynthesisChapterTransport, SynthesisTransport


@pytest.mark.parametrize("enable_memo", [False, True])
def test_native_creation_continues_a_frozen_legacy_chapter_context_capacity_failure(tmp_path, monkeypatch, enable_memo):
    _run_capacity_continuation(tmp_path, monkeypatch, enable_memo=enable_memo, target_pack="3.1.0")


def test_native_creation_upgrades_to_semantic_context_without_claiming_zero_root_calls(tmp_path, monkeypatch):
    _run_capacity_continuation(tmp_path, monkeypatch, enable_memo=True, target_pack="3.2.0")


def _run_capacity_continuation(tmp_path, monkeypatch, *, enable_memo, target_pack):
    harness = CapabilityPackPostgresHarness("chapter-capacity-continuation-" + str(enable_memo))
    root = Path(__file__).resolve().parents[2]
    transport = SynthesisTransport()
    transport.chapter = AdviceOnlySynthesisChapterTransport()
    transport.database_url = DATABASE_URL
    env = controlled_member_environment(tmp_path, {
        "NOVEL_FORGE_APPLICATION_BUILD_ID": harness.application_build_id,
        "NOVEL_FORGE_COMMIT_SHA": harness.release_sha,
        "NOVEL_FORGE_MODEL_PROVIDER": "codex-cli", "NOVEL_FORGE_MODEL": "gpt-test",
        "NOVEL_FORGE_PLANNING_PROVIDER": "codex-cli", "NOVEL_FORGE_PLANNING_MODEL": "gpt-test",
        "NOVEL_FORGE_STORAGE_AUTHORITY": "postgresql", "NOVEL_FORGE_DATABASE_URL": DATABASE_URL,
        "NOVEL_FORGE_LOCAL_OPERATOR_PRINCIPAL_ID": "native-creation-operator",
        "NOVEL_FORGE_OPERATOR_PRINCIPAL_ID": "native-creation-operator",
        "NOVEL_FORGE_NARRATIVE_EVALUATOR_PRINCIPAL_ID": "native-planning-evaluator",
        "NOVEL_FORGE_ENVIRONMENT": "production",
    }, monkeypatch, transport)
    env["NOVEL_FORGE_ENVIRONMENT"] = "production"
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    policy = json.loads((root / "config/execution_templates/creation_inputs.json").read_text())
    policy["narrative_execution_contract"] = "native-narrative-execution.v2"
    profile = policy["profiles"]["production_profile"]["content"]
    profile.pop("context_capacity_policy")
    profile["working_prose_policy"] = {
        "version": "working-prose-projection.v5", "history_chapters": 128,
        "recent_complete_chapters": 2, "max_characters": 24_000, "queries": [], "guidance_mode": "COMBINED"}
    profile["chapter_context_policy"] = {"version": "book-chapter-context.v1", "draft_profile": "draft-context-profile-v4",
        "draft_token_budget": 6000, "quality_token_budget": 512_000}
    policy_file = tmp_path / "frozen-legacy-policy.json"
    policy_file.write_text(json.dumps(policy))
    template = json.loads((root / "config/execution_templates/author_first.json").read_text())
    if enable_memo:
        template["optional_enhancements"].append("memo")
    template_file = tmp_path / "execution-template.json"
    template_file.write_text(json.dumps(template))
    source = tmp_path / "request.json"
    source.write_text(json.dumps({"version": "creation-request.v1", "title": harness.project_id,
        "target_chapters": 1, "chapter_length": {"minimum": 800, "maximum": 8000},
        "language_contract": {"required_language": "zh-CN"},
        "brief": {"creative_brief_contract_version": "creative-brief-v2", "idea": "An archivist investigates a flood.",
            "genre": "social mystery", "audience": "adult readers",
            "constraints": ["Keep the witness's limited viewpoint"], "source_boundaries": ["Original work"]}}))
    settings = IndustrialSettings(root=tmp_path, database_url=DATABASE_URL, environment="production")
    start = _authority_parser().parse_args(["authority-creation", "start", "--input-file", str(source),
        "--creation-policy-file", str(policy_file), "--execution-template-file", str(template_file),
        "--repository-root", str(root), "--maximum-ticks", "150", "--foreground"])
    with monkeypatch.context() as old_worker:
        old_worker.setattr(capacity_continuation, "recover_capacity_continuation", lambda *args: False)
        stopped = run_creation_command(settings, start)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        failures = uow.cursor.execute("""SELECT to_jsonb(operation),attempt.result FROM authority_operation operation
            JOIN authority_attempt attempt USING(operation_id) WHERE operation.project_id=%s
            AND operation.status IN ('FAILED_FINAL','DEAD_LETTER','FAILED_RETRYABLE') ORDER BY operation.created_at""",
            [stopped["project_id"]]).fetchall()
        contexts = [row[0] for row in failures if row[0]["definition_name"] == "chapter.context.build"]
        assert len(contexts) == 1, (stopped, [(row[0]["definition_name"], row[1]) for row in failures])
        failed = contexts[0]
        original_command, original_inputs = failed["command_payload"], failed["input_asset_snapshot"]
        original_attempts = uow.cursor.execute("SELECT attempt_id,result FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number",
            [failed["operation_id"]]).fetchall()
        assert not original_command["preparation_report"].get("context_capacity_policy")
        uow.cursor.execute("SELECT count(*) FROM authority_external_effect WHERE operation_id=%s", [failed["operation_id"]])
        assert uow.cursor.fetchone() == (0,)
        before = uow.cursor.execute("""SELECT effect.external_effect_id,effect.request_hash,effect.status FROM authority_external_effect effect
            JOIN authority_operation owner USING(operation_id) WHERE owner.root_operation_id=%s ORDER BY effect.external_effect_id""",
            [failed["root_operation_id"]]).fetchall()
        assert all(row[2] == "SUCCEEDED" for row in before)
        assert bool(before) is enable_memo
        book = uow.cursor.execute("SELECT to_jsonb(book) FROM authority_book_production book WHERE project_id=%s",
            [stopped["project_id"]]).fetchone()[0]
        pack_id = uow.cursor.execute("SELECT pack_id FROM authority_capability_pack_activation WHERE project_id=%s AND book_id=%s AND workflow_definition_ref='chapter_authority_slice@3.10.0'",
            [book["project_id"], book["book_id"]]).fetchone()[0]
    principal = build_trusted_principal_resolver().resolve_api_principal()
    install_chapter_validation_pack(DATABASE_URL, repository_root=root,
        project_id=book["project_id"], workspace_id=book["workspace_id"], book_id=book["book_id"],
        application_build_id=harness.application_build_id, commit_sha=harness.release_sha,
        compiler=principal, approver=principal, agent_admin=principal, pack_id_override=pack_id,
        pack_version_override=target_pack, expected_activation_version=1, runtime_environment="production",
        prose_skill_version="prose-generation-v5", prompt_template_version="v15")
    from novel_forge.modules.chapter_authority.execution_gateway import PostgresProductionExecutionPayloadResolver
    resolve = PostgresProductionExecutionPayloadResolver.resolve
    sent = []
    def capture(resolver, request, admission):
        payload = resolve(resolver, request, admission)
        if request.stage == "draft":
            sent.append((request.external_effect_id, payload.input_text))
        return payload
    monkeypatch.setattr(PostgresProductionExecutionPayloadResolver, "resolve", capture)
    resume = _authority_parser().parse_args(["authority-creation", "continue", "--project-id", book["project_id"],
        "--formation-run-id", stopped["formation_run_id"], "--repository-root", str(root), "--maximum-ticks", "150", "--foreground"])
    completed = run_creation_command(settings, resume)
    assert completed["stop_reason"] == "MANUSCRIPT_READY", completed
    repeated = run_creation_command(settings, resume)
    assert repeated["stop_reason"] == "MANUSCRIPT_READY"
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        old = uow.cursor.execute("SELECT command_payload,input_asset_snapshot,status FROM authority_operation WHERE operation_id=%s",
            [failed["operation_id"]]).fetchone()
        assert old[:2] == (original_command, original_inputs)
        assert old[2] == ("DEAD_LETTER" if failed["status"] == "FAILED_RETRYABLE" else failed["status"])
        assert uow.cursor.execute("SELECT attempt_id,result FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number",
            [failed["operation_id"]]).fetchall() == original_attempts
        edge = uow.cursor.execute("SELECT policy_evidence,successor_operation_id FROM authority_saga_step_successor WHERE predecessor_operation_id=%s",
            [failed["operation_id"]]).fetchone()
        assert edge[0]["transport_projection"] == capacity_continuation.PROJECTION
        assert edge[0]["root_external_effect_count"] == len(before)
        after = uow.cursor.execute("SELECT external_effect_id,request_hash,status FROM authority_external_effect WHERE external_effect_id=ANY(%s) ORDER BY external_effect_id",
            [[row[0] for row in before]]).fetchall()
        assert after == before
        context = uow.cursor.execute("""SELECT version.content FROM authority_operation_output_asset output
            JOIN authority_asset_version version USING(asset_version_id) WHERE output.operation_id=%s AND output.output_key='chapter.context'""",
            [edge[1]]).fetchone()[0]
        assert context["context_manifest"]["task_context_receipt"]["capacity_admission"] == "DEFERRED_COMPLETE_REQUEST"
        assert context["capacity_policy_upgrade"]["source_operation_id"] == failed["operation_id"]
        if target_pack == "3.2.0":
            assert context["context_manifest"]["task_context_receipt"]["semantic_contract"] == "source-unit-dependency-and-final-composition.v2"
        prose = uow.cursor.execute("""SELECT version.content FROM authority_asset_version version
            JOIN authority_asset asset USING(asset_id) WHERE asset.project_id=%s AND asset.asset_type='draft_chapter'""",
            [book["project_id"]]).fetchone()[0]["text"]
        assert prose and len(sent) == 1
        final = uow.cursor.execute("SELECT request_payload FROM authority_external_effect WHERE external_effect_id=%s", [sent[0][0]]).fetchone()[0]
        runtime = final["_production_execution"]["capability_runtime"]
        admission = uow.cursor.execute("SELECT content->'contract' FROM authority_asset_version WHERE asset_version_id=%s",
            [runtime["provider_admission_asset_version_id"]]).fetchone()[0]
        assert final["input"]["_context_capacity_upgrade"]["policy_hash"] == context["capacity_policy_upgrade"]["policy_hash"]
        assert admission["prompt_materialization"]["provider_view"]["capacity_policy_upgrade"]["source_selection"] == "UNCHANGED"
        assert runtime["provider_admission"]["status"] == "ADMITTED"
        assert admission["provider_request_identity"]["input_text_hash"] == "sha256:" + hashlib.sha256(sent[0][1].encode()).hexdigest()
    evidence = os.environ.get("NOVEL_FORGE_POSTGRES_EVIDENCE_DIR")
    if evidence:
        target = Path(evidence) / ("chapter-capacity-upgrade-memo-" + str(enable_memo) + ("-semantic-v4" if target_pack == "3.2.0" else ""))
        target.mkdir(parents=True, exist_ok=True)
        (target / "proof.json").write_text(json.dumps({"evidence_class": "NATIVE_CONTROLLED_PROVIDER_ONLY",
            "project_id": book["project_id"], "book_run_id": book["book_run_id"], "source": failed,
            "policy": edge[0], "context": context, "final_request": final, "admission": admission, "result": completed}, ensure_ascii=False, default=str))
        (target / "sent.txt.gz").write_bytes(gzip.compress(sent[0][1].encode(), mtime=0))
        (target / "native-prose.txt").write_text(prose)
