from copy import deepcopy
import json
from pathlib import Path

import pytest

from novel_forge.cli.authority import _authority_parser
from novel_forge.cli.creation import run_creation_command
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.book_authority.manuscript import freeze_working_context
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.world_preparation import PlanningWorldPreparation
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.book_control_repositories import BookControlRepository
from novel_forge.storage.world_preparation_repositories import WorldPreparationRepository
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.capability_pack_postgres_support import CapabilityPackPostgresHarness
from tests.integration.creative_validation_production_support import controlled_member_environment
from tests.integration.synthesis_production_support import AdviceOnlySynthesisChapterTransport, SynthesisTransport
from tests.unit.test_working_prose_projection import rehash


def test_native_v5_writer_admission_bounds_observation_ledger_and_keeps_complete_previous_prose(tmp_path, monkeypatch):
    harness = CapabilityPackPostgresHarness("bounded-working-memory")
    root = Path(__file__).resolve().parents[2]
    transport = SynthesisTransport()
    class MemoryTransport(AdviceOnlySynthesisChapterTransport):
        def __call__(self, stage, inputs):
            output = super().__call__(stage, inputs)
            if stage == "draft":
                output["working_memory_json"] = json.dumps([{
                    "kind": "EVENT", "subject": "archivist", "state_key": f"located-event-{index}",
                    "claim": f"Observation {index}. " + "The located opening remains unreviewed evidence. " * 10,
                    "perspective": "OBSERVED", "knowledge_owner": "",
                    "quote": output["scene_artifacts"][0]["text"][:200], "causes": []
                } for index in range(64)], ensure_ascii=False)
            return output
    transport.chapter = MemoryTransport()
    transport.chapter.controlled_prose = "唯一起点的纸签压在账本上。" + "她停在门外，听见木轮碾过石板。" * 80
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
    from novel_forge.modules.chapter_authority.execution_gateway import PostgresProductionExecutionPayloadResolver
    resolve = PostgresProductionExecutionPayloadResolver.resolve
    writers = []
    def capture(resolver, request, admission):
        payload = resolve(resolver, request, admission)
        if request.stage == "draft":
            writers.append(payload)
        return payload
    monkeypatch.setattr(PostgresProductionExecutionPayloadResolver, "resolve", capture)
    source = tmp_path / "bounded-request.json"
    source.write_text(json.dumps({"version": "creation-request.v1", "title": harness.project_id,
        "target_chapters": 2, "chapter_length": {"minimum": 800, "maximum": 4000},
        "language_contract": {"required_language": "zh-CN"},
        "brief": {"creative_brief_contract_version": "creative-brief-v2", "idea": "An archivist investigates a flood.",
            "genre": "social mystery", "audience": "adult readers", "constraints": ["Keep limited viewpoint"], "source_boundaries": ["Original work"]}}))
    policy = json.loads((root / "config/execution_templates/creation_inputs.json").read_text())
    policy["profiles"]["production_profile"]["content"]["working_prose_policy"] = {
        "version": "working-prose-projection.v5", "history_chapters": 128,
        "recent_complete_chapters": 2, "max_characters": 8000, "queries": [], "guidance_mode": "COMBINED"}
    policy_file = tmp_path / "bounded-policy.json"
    policy_file.write_text(json.dumps(policy))
    args = _authority_parser().parse_args(["authority-creation", "start", "--input-file", str(source),
        "--repository-root", str(root), "--creation-policy-file", str(policy_file), "--foreground"])
    result = run_creation_command(IndustrialSettings(root=tmp_path, database_url=DATABASE_URL, environment="production"), args)
    assert result["stop_reason"] == "MANUSCRIPT_READY", result
    assert len(writers) == 2
    from novel_forge.modules.chapter_authority.provider_views import expand_exact_context_references
    prompt = writers[1].input_text
    envelope = expand_exact_context_references(json.JSONDecoder().raw_decode(prompt[prompt.index('{"context_bundle":'):])[0])
    assert transport.chapter.controlled_prose in json.dumps(envelope, ensure_ascii=False)
    packets = []
    def collect(value):
        if isinstance(value, dict):
            if value.get("version") == "working-observations-provider.v1":
                packets.append(value)
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
    collect(envelope)
    assert packets and all(packet["candidate_count"] == 64 and packet["omitted_observation_count"] > 0 for packet in packets)
    assert "omitted_observation_ids" not in prompt
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT context_snapshot FROM authority_book_manuscript_delivery WHERE book_run_id=%s AND chapter_number=2", [result["book_run_id"]])
        frozen = uow.cursor.fetchone()[0]
        assert frozen["accepted_through_chapter"] == 0
        assert frozen["working_memory"]["candidate_count"] == 64
        assert frozen["working_memory"]["omitted_observation_ids"]
        assert frozen["sources"][0]["omitted_ranges"] == []
        assert transport.chapter.controlled_prose in "".join(p["text"] for p in frozen["sources"][0]["passages"])
    assert writers[1].capability_evidence["provider_request_envelope_hash"]
    print(json.dumps({"scope": "SCRIPTED_NATIVE_V5_POSTGRES", "book_run_id": result["book_run_id"],
        "candidate_observations": 64, "host_omitted_count": len(frozen["working_memory"]["omitted_observation_ids"]),
        "prompt_bytes": len(prompt.encode()), "prompt_hash": writers[1].capability_evidence["fully_rendered_prompt_hash"]}))


def test_native_creation_world_binds_selected_delivery_and_rejects_changed_experience(tmp_path, monkeypatch):
    harness = CapabilityPackPostgresHarness("world-working")
    root = Path(__file__).resolve().parents[2]
    transport = SynthesisTransport()
    class WorkingRevisionTransport(AdviceOnlySynthesisChapterTransport):
        def __call__(self, stage, inputs):
            result = super().__call__(stage, inputs)
            if stage == "revision":
                result["text"] = inputs["draft"]["text"]
            if stage == "rereview":
                for check in result.get("preservation_checks", []):
                    check["evidence"] = {"quote": check["evidence"]["quote"]}
            return result
    transport.chapter = WorkingRevisionTransport()
    transport.chapter.controlled_prose = "唯一起点的纸签压在账本上。" + "她停在门外，听见木轮碾过石板。" * 80
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
    from novel_forge.modules.chapter_authority.execution_gateway import PostgresProductionExecutionPayloadResolver
    resolve = PostgresProductionExecutionPayloadResolver.resolve
    writer_prompts = []
    chapter_planning_prompts = []
    world_prompts = []

    def capture_writer_prompt(resolver, request, admission):
        payload = resolve(resolver, request, admission)
        if request.stage in {"draft", "chapter_plan.generate", "world_candidates.generate", "world_candidates.evaluate"}:
            start = payload.input_text.find('{"context_bundle":')
            assert start >= 0
            from novel_forge.modules.chapter_authority.provider_views import expand_exact_context_references
            envelope = expand_exact_context_references(json.JSONDecoder().raw_decode(payload.input_text[start:])[0])
            target = writer_prompts if request.stage == "draft" else world_prompts if request.stage.startswith("world_candidates.") else chapter_planning_prompts
            target.append(envelope)
        return payload

    monkeypatch.setattr(PostgresProductionExecutionPayloadResolver, "resolve", capture_writer_prompt)
    input_file = tmp_path / "request.json"
    input_file.write_text(json.dumps({"version": "creation-request.v1", "title": harness.project_id,
        "target_chapters": 2, "execution_window": {"version": "creation-execution-window.v1", "stop_after_chapter": 1},
        "chapter_length": {"minimum": 800, "maximum": 4000}, "language_contract": {"required_language": "zh-CN"},
        "brief": {"creative_brief_contract_version": "creative-brief-v2", "idea": "An archivist investigates a flood.",
            "genre": "social mystery", "audience": "adult readers", "constraints": ["Keep the witness's limited viewpoint"], "source_boundaries": ["Original work"]}}))
    args = _authority_parser().parse_args(["authority-creation", "start", "--input-file", str(input_file),
        "--repository-root", str(root), "--maximum-ticks", "100", "--foreground"])
    template = json.loads((root / args.execution_template_file).read_text())
    template["optional_enhancements"] = sorted(set(template["optional_enhancements"]) | {"memo"})
    args.execution_template_file = tmp_path / "execution-template.json"
    args.execution_template_file.write_text(json.dumps(template))
    result = run_creation_command(IndustrialSettings(root=tmp_path, database_url=DATABASE_URL, environment="production"), args)
    if result["stop_reason"] != "MANUSCRIPT_READY":
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("""SELECT operation.definition_name,operation.status,attempt.result->>'error_code',attempt.result->>'error_message'
                FROM authority_operation operation LEFT JOIN LATERAL (SELECT result FROM authority_attempt
                    WHERE operation_id=operation.operation_id ORDER BY attempt_number DESC LIMIT 1) attempt ON TRUE
                WHERE operation.project_id=%s ORDER BY operation.created_at DESC LIMIT 8""", [result["project_id"]])
            failures = uow.cursor.fetchall()
        pytest.fail(f"Native Creation stopped at {result['stop_reason']}: {failures!r}")
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT to_jsonb(b) FROM authority_book_production b WHERE book_run_id=%s", [result["book_run_id"]])
        book = uow.cursor.fetchone()[0]
        assert book["current_chapter"] == 1 and book["accepted_through_chapter"] == 0
        uow.cursor.execute("""SELECT v.content FROM authority_asset_version v JOIN authority_asset a USING(asset_id)
            WHERE a.project_id=%s AND a.asset_type='context_bundle' AND v.content->>'stage'='draft'""", [book["project_id"]])
        draft_contexts = [row[0] for row in uow.cursor.fetchall() if row[0].get("chapter_generation_length")]
        assert len(draft_contexts) == 1
        assert draft_contexts[0]["chapter_generation_length"]["minimum"] == 800
        assert draft_contexts[0]["chapter_generation_length"]["maximum"] == 4000
        from novel_forge.modules.chapter_authority.quality_length_requirement import require_generation_binding
        require_generation_binding(draft_contexts[0])
        assert len(writer_prompts) == 1
        assert writer_prompts[0]["context_bundle"]["chapter_generation_length"] == draft_contexts[0]["chapter_generation_length"]
        assert len(chapter_planning_prompts) == 1
        scale = chapter_planning_prompts[0]["context_bundle"]["chapter_planning_length"]
        assert scale["minimum"] == 800 and scale["maximum"] == 4000 and scale["unit"] == "HAN_CHARACTERS_V1"
        uow.cursor.execute("SELECT current_book_asset_version_id FROM authority_book WHERE project_id=%s AND book_id=%s", [book["project_id"], book["book_id"]])
        assert scale["source_book_asset_version_id"] == uow.cursor.fetchone()[0]
        uow.cursor.execute("""SELECT v.content->'creative_baseline' FROM authority_asset_version v
            JOIN authority_asset a USING(asset_id) WHERE a.project_id=%s AND a.asset_type='draft_chapter'""", [book["project_id"]])
        baselines = [row[0] for row in uow.cursor.fetchall()]
        assert len(baselines) == 1
        assert baselines[0]["chapter_generation_length"] == draft_contexts[0]["chapter_generation_length"]
        uow.cursor.execute("""SELECT v.content->'contract' FROM authority_asset_version v JOIN authority_asset a USING(asset_id)
            WHERE a.project_id=%s AND a.asset_type='world_preparation_source' ORDER BY v.created_at LIMIT 1""", [book["project_id"]])
        first_source = uow.cursor.fetchone()[0]
        assert first_source["contract_version"] == "world-preparation-source.v5"
        assert first_source["provider_projection_version"] == "world-role-delivery.v4"
        assert len(world_prompts) == 2
        for envelope in world_prompts:
            delivered = envelope["input_manifest"]["narrative_inputs"]["world_preparation"]
            assert delivered["contract_version"] == "world-provider-task.v5"
            assert delivered["working_delivery_receipt"]["source_snapshot_hash"] == first_source["working_manuscript"]["snapshot_hash"]
            assert "schema" not in delivered["transition_contract"]
            assert delivered["transition_contract"]["payload_schema"]
        working = freeze_working_context(uow, book, 2)
        BookControlRepository(uow.cursor).freeze(project_id=book["project_id"], book_run_id=book["book_run_id"],
            chapter_number=2, actor_id="native-creation-operator")
        repository = WorldPreparationRepository(uow.cursor)
        source = repository.require_source(project_id=book["project_id"], book_id=book["book_id"],
            request=first_source["request"], contract_version="world-preparation-source.v5", epistemic_contract="world-agency.v2",
            working_manuscript=working)
        assert source["target_chapter"] == 2 and source["reality"]["chapter_number"] == 0
        assert source["working_manuscript"]["sources"][0]["passages"] == working["sources"][0]["passages"]
        repository.assert_source_current(project_id=book["project_id"], book_id=book["book_id"], frozen=source)
        task = PlanningWorldPreparation._task(source, {"asset_version_id": "controlled-source", "content_hash": "digest"}, "DIRECTOR")
        assert task["target_chapter"] == 2 and task["accepted_through_chapter"] == 0
        from novel_forge.modules.chapter_authority.provider_views import build_provider_context_view
        from tests.unit.test_author_design_adoption import _world_author_context
        _, _, author_context = _world_author_context("world_candidates.evaluate")
        author_context.update(project_id=book["project_id"], book_id=book["book_id"], logical_key="chapter:2",
            world_preparation=task, token_budget=task["policy"]["context_token_budget"])
        author_context["author_design_projection"]["chapter_range"] = [2, 2]
        for fragment in author_context["author_design_projection"]["fragments"]:
            fragment["chapter_range"] = [2, 2]
        view = build_provider_context_view("world_candidates.evaluate", author_context, {"world_preparation": task})
        assert view["author_design_projection"]["chapter_range"] == [2, 2]
        assert view["accepted_state_boundary"]["accepted_through_chapter"] == 0
        changed = deepcopy(source)
        changed["working_manuscript"]["sources"][0]["content_hash"] = "sha256:" + "0" * 64
        rehash(changed["working_manuscript"])
        with pytest.raises(KernelError, match="MANUSCRIPT_SOURCE_HASH_INVALID|WORKING_PROSE_SOURCE_RESOLUTION_INVALID"):
            repository.assert_source_current(project_id=book["project_id"], book_id=book["book_id"], frozen=changed)
        assert uow.cursor.execute("SELECT accepted_through_chapter FROM authority_book_production WHERE book_run_id=%s", [book["book_run_id"]]).fetchone() == (0,)
    from novel_forge.cli.manuscript import run_manuscript_command
    from novel_forge.modules.book_authority.queries import PostgresBookProductionQuery
    revision = _authority_parser().parse_args(["authority-manuscript", "revise", "--project-id", book["project_id"],
        "--book-run-id", book["book_run_id"], "--chapter", "1", "--expected-version", str(book["version"]),
        "--idempotency-key", harness.project_id + ":working-revision", "--reason", "Native selected working review"])
    admitted = run_manuscript_command(IndustrialSettings(root=root, database_url=DATABASE_URL, environment="production"), revision)
    assert PostgresBookProductionQuery(DATABASE_URL).uses_creation_scope(project_id=book["project_id"], subject_id=admitted["root_operation_id"])
    assert not PostgresBookProductionQuery(DATABASE_URL).uses_creation_scope(project_id="other-project", subject_id=admitted["root_operation_id"])
    continued_revision = _authority_parser().parse_args(["authority-manuscript", "continue-revision", "--project-id", book["project_id"],
        "--book-run-id", book["book_run_id"], "--revision-root", admitted["root_operation_id"], "--foreground", "--work-window-seconds", "30"])
    revised = run_manuscript_command(IndustrialSettings(root=root, database_url=DATABASE_URL, environment="production"), continued_revision)
    assert revised["status"] == "SUCCEEDED", revised
    candidate = next(row["asset_version_id"] for row in revised["stages"] if row["output_key"] == "chapter.best_candidate")
    selection_args = _authority_parser().parse_args(["authority-manuscript", "use-working-candidate", "--project-id", book["project_id"],
        "--book-run-id", book["book_run_id"], "--chapter", "1", "--candidate-version", candidate,
        "--expected-version", str(book["version"]), "--idempotency-key", harness.project_id + ":work-select", "--reason", "Use native revised work"])
    selected = run_manuscript_command(IndustrialSettings(root=root, database_url=DATABASE_URL, environment="production"), selection_args)
    from novel_forge.modules.book_authority.manuscript import require_manuscript
    from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
    principal = build_trusted_principal_resolver().resolve_api_principal()
    current = require_manuscript(DATABASE_URL, project_id=book["project_id"], book_run_id=book["book_run_id"], principal=principal)
    unit = current["units"][0]
    assert unit["asset_version_id"] == candidate
    assert unit["working_selection"]["asset_version_id"] == selected["selection_asset_version_id"]
    assert unit["author_selection"] == unit["working_selection"]["formal_acceptance"] == "NOT_GRANTED"
    from novel_forge.modules.book_authority import manuscript as manuscript_module
    for failure in ("receipt", "sql"):
        def broken_review(uow, _book, _source):
            if failure == "sql":
                uow.cursor.execute("SELECT 1/0")
            raise KernelError("LONGFORM_PROSE_RECEIPT_MISSING", "Controlled missing auxiliary report")
        with monkeypatch.context() as patch:
            patch.setattr(manuscript_module, "_review_status", broken_review)
            readable = require_manuscript(DATABASE_URL, project_id=book["project_id"], book_run_id=book["book_run_id"],
                principal=principal, version_ids=[candidate])
            assert readable["text_digest"] == current["text_digest"]
            assert readable["units"][0]["review_status"] == "UNAVAILABLE"
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT to_jsonb(b) FROM authority_book_production b WHERE book_run_id=%s", [book["book_run_id"]])
        latest = uow.cursor.fetchone()[0]
        following = freeze_working_context(uow, latest, 2)
        assert following["sources"][0]["asset_version_id"] == candidate
        assert latest["accepted_through_chapter"] == 0
    replay = run_manuscript_command(IndustrialSettings(root=root, database_url=DATABASE_URL, environment="production"), selection_args)
    assert replay["selection_asset_version_id"] == selected["selection_asset_version_id"]
    from copy import copy
    late = copy(selection_args)
    late.expected_version = latest["version"]
    late.idempotency_key += ":late"
    with pytest.raises(KernelError, match="MANUSCRIPT_WORK_SELECTION_STALE"):
        run_manuscript_command(IndustrialSettings(root=root, database_url=DATABASE_URL, environment="production"), late)
    cancellation = _authority_parser().parse_args(["authority-creation", "cancel", "--project-id", book["project_id"],
        "--formation-run-id", result["formation_run_id"], "--repository-root", str(root),
        "--idempotency-key", harness.project_id + ":cancel", "--reason", "Controlled cancellation keeps selected prose"])
    run_creation_command(IndustrialSettings(root=root, database_url=DATABASE_URL, environment="production"), cancellation)
    retained = require_manuscript(DATABASE_URL, project_id=book["project_id"], book_run_id=book["book_run_id"], principal=principal)
    assert retained["text_digest"] == current["text_digest"] and retained["units"][0]["asset_version_id"] == candidate


def test_native_upstream_complete_request_overflow_consumes_checked_history_extract(tmp_path, monkeypatch):
    _run_native_semantic_capacity(tmp_path, monkeypatch, upgrade_context_effects=False)


def test_native_semantic_upgrade_retains_settled_compression_before_unsent_writer(tmp_path, monkeypatch):
    _run_native_semantic_capacity(tmp_path, monkeypatch, upgrade_context_effects=True)


def _run_native_semantic_capacity(tmp_path, monkeypatch, *, upgrade_context_effects):
    import hashlib
    from tokenizers import Tokenizer, models, pre_tokenizers
    from novel_forge.modules.chapter_authority.execution_gateway import default_chapter_fixture_response

    harness = CapabilityPackPostgresHarness("upstream-capacity")
    root = Path(__file__).resolve().parents[2]
    gold_path = root / "tests/fixtures/semantic_compression_gold.json"
    gold = json.loads(gold_path.read_text())
    gold_text = "\n\n".join(paragraph for source in gold["sources"] for paragraph in source["paragraphs"])
    actual_prompt_qa = []
    transport = SynthesisTransport()
    class HistoryTransport(AdviceOnlySynthesisChapterTransport):
        def __call__(self, stage, inputs):
            if stage in {"context_compress", "context_fidelity"}:
                return default_chapter_fixture_response(stage, inputs)
            output = super().__call__(stage, inputs)
            if stage == "draft":
                chapter = inputs["plan"]["chapter"]
                text = "\n\n".join(f"第{chapter}章记录第{index}次查验。" + "她停在门外，听见木轮碾过石板，仍不敢替证人确认消息。" * 3 for index in range(600))
                if chapter == 1 and not upgrade_context_effects:
                    text = gold_text + "\n\n" + text
                from novel_forge.modules.chapter_authority.realization_composition import serialize_realization
                output["scene_artifacts"][0]["text"] = text + "\n\n" + output["scene_artifacts"][0]["text"]
                output["text"] = serialize_realization(output["scene_artifacts"])
                if chapter == 1 and not upgrade_context_effects:
                    observations = []
                    for source in gold["sources"]:
                        for index, paragraph in enumerate(source["paragraphs"]):
                            perspective, owner = "OBSERVED", ""
                            if source["id"] == "selected-working:harbor:7" and index == 4:
                                perspective, owner = "HEARSAY", "阿岚"
                            elif source["id"] == "selected-working:harbor:7" and index == 5 or source["id"] == "selected-working:unicode:3" and index == 2:
                                perspective = "READER_ONLY"
                            elif source["id"].startswith("witness:"):
                                perspective, owner = "HEARSAY", "账房甲" if source["id"].endswith(":a") else "搬夫乙"
                            observations.append({"kind": "KNOWLEDGE" if perspective == "HEARSAY" else "EVENT",
                                "subject": owner or "工作稿叙述", "state_key": source["id"] + ":" + str(index),
                                "claim": paragraph, "perspective": perspective, "knowledge_owner": owner,
                                "quote": paragraph, "causes": []})
                    output["working_memory_json"] = json.dumps(observations, ensure_ascii=False)
            return output
    transport.chapter = HistoryTransport()
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
    from novel_forge.modules.chapter_authority.execution_gateway import PostgresProductionExecutionPayloadResolver
    original_resolve = PostgresProductionExecutionPayloadResolver.resolve
    sent_requests = {}
    def capture_sent_request(resolver, request, admission):
        payload = original_resolve(resolver, request, admission)
        sent_requests[request.external_effect_id] = payload.input_text
        if request.stage == "draft":
            from novel_forge.modules.production_execution.process_supervisor import PersistentExecutionDirectory
            from novel_forge.modules.chapter_authority.realization_composition import serialize_realization
            layout = PersistentExecutionDirectory(env["NOVEL_FORGE_CODEX_EXECUTION_ROOT"]).prepare(request.execution_id)
            response_path = layout.result_path("fixture-response.json")
            response = json.loads(response_path.read_text())
            if not upgrade_context_effects and (response.get("chapter") == 4 or any(scene.get("chapter") == 4 for scene in response.get("scene_artifacts", []))):
                assert "阿岚" in payload.input_text
            support = [paragraph for source in gold["sources"] for paragraph in source["paragraphs"] if paragraph in payload.input_text]
            if support:
                actual_prompt_qa.append({"effect_id": request.external_effect_id, "sent_input_hash": hashlib.sha256(payload.input_text.encode()).hexdigest(),
                    "support_paragraphs": support, "scope": "Exact original support in actual serialized prompt; not model semantic comprehension"})
                if "初十清晨，阿岚把同一把铜钥匙退还林砚。她仍未开闸，也没有把茶棚传闻告诉他。" in support:
                    response["scene_artifacts"][0]["text"] += "\n\n钥匙已经归还，闸门仍旧未开；阿岚没有把那条未经核实的传闻递给林砚。"
                    if "text" in response:
                        response["text"] = serialize_realization(response["scene_artifacts"])
                    response_path.write_text(json.dumps(response, ensure_ascii=False))
        return payload
    monkeypatch.setattr(PostgresProductionExecutionPayloadResolver, "resolve", capture_sent_request)
    tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.Split("", behavior="isolated")
    path = tmp_path / "synthetic-character-meter.json"
    tokenizer.save(str(path))
    env.update(NOVEL_FORGE_PROVIDER_TOKEN_ACCOUNTING_METHOD="PINNED_TOKENIZER_JSON_V1",
        NOVEL_FORGE_PROVIDER_TOKEN_ACCOUNTING_EVIDENCE_REF="tokenizer-json:" + hashlib.sha256(path.read_bytes()).hexdigest() + ":" + str(path))
    candidates = json.loads(env["NOVEL_FORGE_CODEX_ROUTER_MODELS"])
    for model in candidates["models"]:
        model["context_limit"] = 310000
    if upgrade_context_effects:
        writer = {**candidates["models"][0], "model": "gpt-test-writer", "tasks": ["draft"], "context_limit": 260000}
        for model in candidates["models"]:
            model["tasks"] = [task for task in model["tasks"] if task != "draft"]
        candidates["models"].append(writer)
    env["NOVEL_FORGE_CODEX_ROUTER_MODELS"] = json.dumps(candidates)
    env["NOVEL_FORGE_CODEX_ESCALATION_CONTEXT_LIMIT"] = "310000"
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    request = tmp_path / "capacity-request.json"
    request.write_text(json.dumps({"version": "creation-request.v1", "title": harness.project_id,
        "target_chapters": 4, "chapter_length": {"minimum": 800, "maximum": 80000},
        "language_contract": {"required_language": "zh-CN"},
        "brief": {"creative_brief_contract_version": "creative-brief-v2", "idea": "An archivist investigates a flood.",
            "genre": "social mystery", "audience": "adult readers", "constraints": ["Keep the witness's limited viewpoint"], "source_boundaries": ["Original work"]}}))
    args = _authority_parser().parse_args(["authority-creation", "start", "--input-file", str(request),
        "--repository-root", str(root), "--maximum-ticks", "250", "--foreground"])
    settings = IndustrialSettings(root=tmp_path, database_url=DATABASE_URL, environment="production")
    upgrade_proof = None
    if upgrade_context_effects:
        from novel_forge.modules.chapter_authority import capacity_continuation
        from novel_forge.modules.chapter_authority.execution_gateway import PostgresChapterExecutionContractBinder
        from novel_forge.modules.capability_packs.validation_deployment import install_chapter_validation_pack
        from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
        from novel_forge.modules.command_kernel.errors import KernelError
        policy = json.loads((root / "config/execution_templates/creation_inputs.json").read_text())
        policy["narrative_execution_contract"] = "native-narrative-execution.v3"
        policy["profiles"]["production_profile"]["content"]["working_prose_policy"]["version"] = "working-prose-projection.v6"
        policy_file = tmp_path / "frozen-complete-capacity-v3.json"
        policy_file.write_text(json.dumps(policy))
        args.creation_policy_file = policy_file
        freeze = PostgresChapterExecutionContractBinder.freeze_before_external_effect
        interrupted = []
        def fail_after_context(binder, **arguments):
            result = freeze(binder, **arguments)
            payload = arguments["request_payload"]
            if payload.get("stage") == "draft" and payload.get("input", {}).get("_context_capacity_projection") and not interrupted:
                interrupted.append(payload["_production_execution"]["operation_id"])
                raise KernelError("PROVIDER_CONTEXT_LIMIT_EXCEEDED", "Controlled failure after settled Context calls and before Writer Effect intent")
            return result
        with monkeypatch.context() as old_worker:
            old_worker.setattr(capacity_continuation, "recover_capacity_continuation", lambda *unused: False)
            old_worker.setattr(PostgresChapterExecutionContractBinder, "freeze_before_external_effect", fail_after_context)
            stopped = run_creation_command(settings, args)
        assert interrupted, stopped
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            failed = uow.cursor.execute("SELECT to_jsonb(owner) FROM authority_operation owner WHERE operation_id=%s", [interrupted[0]]).fetchone()[0]
            retained = uow.cursor.execute("SELECT external_effect_id,request_hash,status,request_payload->>'stage' FROM authority_external_effect WHERE operation_id=%s ORDER BY external_effect_id", [interrupted[0]]).fetchall()
            assert retained and all(row[2] == "SUCCEEDED" and row[3] in {"context_compress", "context_fidelity"} for row in retained)
            book = uow.cursor.execute("SELECT to_jsonb(book) FROM authority_book_production book WHERE project_id=%s", [stopped["project_id"]]).fetchone()[0]
            pack = uow.cursor.execute("SELECT pack_id,active_deployment_id FROM authority_capability_pack_activation WHERE project_id=%s AND book_id=%s AND workflow_definition_ref='chapter_authority_slice@3.10.0'", [book["project_id"], book["book_id"]]).fetchone()
        principal = build_trusted_principal_resolver().resolve_api_principal()
        install_chapter_validation_pack(DATABASE_URL, repository_root=root, project_id=book["project_id"],
            workspace_id=book["workspace_id"], book_id=book["book_id"], application_build_id=harness.application_build_id,
            commit_sha=harness.release_sha, compiler=principal, approver=principal, agent_admin=principal,
            pack_id_override=pack[0], pack_version_override="3.2.0", expected_activation_version=1,
            runtime_environment="production", prose_skill_version="prose-generation-v5", prompt_template_version="v15")
        resume = _authority_parser().parse_args(["authority-creation", "continue", "--project-id", book["project_id"],
            "--formation-run-id", stopped["formation_run_id"], "--repository-root", str(root), "--maximum-ticks", "250", "--foreground"])
        result = run_creation_command(settings, resume)
        assert run_creation_command(settings, resume)["stop_reason"] == "MANUSCRIPT_READY"
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            edge = uow.cursor.execute("SELECT policy_evidence,successor_operation_id FROM authority_saga_step_successor WHERE predecessor_operation_id=%s", [interrupted[0]]).fetchone()
            assert edge and edge[0]["external_call_scope"] == "MAIN_UNSENT_CONTEXT_EFFECTS_RECONCILED"
            after = uow.cursor.execute("SELECT external_effect_id,request_hash,status,request_payload->>'stage' FROM authority_external_effect WHERE operation_id=%s ORDER BY external_effect_id", [interrupted[0]]).fetchall()
            assert after == retained
            assert uow.cursor.execute("SELECT command_payload,input_asset_snapshot FROM authority_operation WHERE operation_id=%s", [interrupted[0]]).fetchone() == (failed["command_payload"], failed["input_asset_snapshot"])
        upgrade_proof = {"source": failed, "retained_context_effects": retained, "policy": edge[0], "successor_operation_id": edge[1]}
    else:
        result = run_creation_command(settings, args)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT capability,status,request_payload,external_effect_id FROM authority_external_effect WHERE project_id=%s ORDER BY created_at", [result["project_id"]])
        effects = uow.cursor.fetchall()
        failures = uow.cursor.execute("SELECT definition_name,status FROM authority_operation WHERE project_id=%s AND status IN ('FAILED_FINAL','FAILED_RETRYABLE')", [result["project_id"]]).fetchall()
    assert result["stop_reason"] == "MANUSCRIPT_READY", (result, failures)
    from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
    from novel_forge.modules.book_authority.manuscript import require_manuscript
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        book_run_id = uow.cursor.execute("SELECT book_run_id FROM authority_book_production WHERE project_id=%s", [result["project_id"]]).fetchone()[0]
    readback = require_manuscript(DATABASE_URL, project_id=result["project_id"], book_run_id=book_run_id,
        principal=build_trusted_principal_resolver().resolve_api_principal())
    readback_text = "\n\n".join(unit["text"] for unit in readback["units"])
    if not upgrade_context_effects:
        assert "钥匙已经归还，闸门仍旧未开" in readback_text
        assert actual_prompt_qa and any(len(row["support_paragraphs"]) == sum(len(source["paragraphs"]) for source in gold["sources"]) for row in actual_prompt_qa)
    else:
        assert len(readback["units"]) == 4 and readback_text
    compression = [row for row in effects if row[2].get("stage") in {"context_compress", "context_fidelity"}]
    assert compression and all(row[1] == "SUCCEEDED" for row in compression)
    compression_proofs = []
    for _, status, payload, effect_id in compression:
        expression = payload["input"]["context_compression_task"]["task"].get("source_expression")
        if expression:
            assert '"source_expression"' in sent_requests[effect_id]
            assert expression["asset_version_id"] in sent_requests[effect_id]
            assert expression["content_hash"] in sent_requests[effect_id]
        compression_proofs.append({"effect_id": effect_id, "stage": payload["stage"], "status": status,
            "source_expression": expression, "sent_request_sha256": hashlib.sha256(sent_requests[effect_id].encode()).hexdigest()})
    derived = [row for row in effects if row[2].get("input", {}).get("_context_capacity_projection")]
    assert derived
    assert any(row[0].startswith("planning.") for row in derived), [row[0] for row in derived]
    proofs = []
    for capability, _, payload, effect_id in derived:
        from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
        runtime = payload["_production_execution"]["capability_runtime"]
        admission = AuthorityAssetQuery(DATABASE_URL).require(project_id=result["project_id"],
            asset_version_id=runtime["provider_admission_asset_version_id"]).content
        admission = admission.get("contract", admission)
        assert admission["provider_request_identity"]["input_text_hash"] == "sha256:" + hashlib.sha256(sent_requests[effect_id].encode()).hexdigest()
        projection = payload["input"]["_context_capacity_projection"]
        if not upgrade_context_effects or projection.get("semantic_contract"):
            assert projection["semantic_contract"] == "source-unit-dependency-and-final-composition.v2"
            assert projection["final_composition"]["provider_combination"]["phase"] == "FINAL_PROVIDER_COMPOSITION"
        assert projection["original_hash"] != projection["result_hash"]
        assert projection["measurement"]["after_reserved"] <= projection["measurement"]["limit"]
        proofs.append({"effect_id": effect_id, "capability": capability, "projection": projection,
            "admission": admission, "sent_request_sha256": hashlib.sha256(sent_requests[effect_id].encode()).hexdigest()})
    import os
    import gzip
    evidence_root = os.environ.get("NOVEL_FORGE_POSTGRES_EVIDENCE_DIR")
    if evidence_root:
        destination = Path(evidence_root) / ("upstream-main-unsent-upgrade" if upgrade_context_effects else "upstream-complete-request")
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "receipts.json").write_text(json.dumps({"evidence_class": "NATIVE_CONTROLLED_MAIN_UNSENT_UPGRADE_WITH_SYNTHETIC_LOAD" if upgrade_context_effects else "NATIVE_CONTROLLED_GOLD_WITH_SYNTHETIC_CAPACITY_LOAD",
            "gold_applied": not upgrade_context_effects, "gold_sha256": hashlib.sha256(gold_path.read_bytes()).hexdigest(), "gold_questions_fixed_before_compression": True,
            "route_windows": {"planning": 310000, "writer": 260000 if upgrade_context_effects else 310000,
                "unit": "SYNTHETIC_CHARACTER_METER_NOT_REAL_TOKENS", "purpose": "A narrower authorized Writer fixture exercises actual compression before its unsent checkpoint" if upgrade_context_effects else "Complete upstream request overflow with fixed original Gold"},
            "actual_prompt_support": actual_prompt_qa, "semantic_comprehension": "NOT_VERIFIED",
            "result": result, "proofs": proofs, "compression_effects": compression_proofs, "upgrade": upgrade_proof}, ensure_ascii=False, indent=2))
        (destination / "native-manuscript-readback.txt.gz").write_bytes(gzip.compress(readback_text.encode(), mtime=0))
        (destination / "manuscript-readback.json").write_text(json.dumps({key: value for key, value in readback.items() if key != "units"}, ensure_ascii=False, default=str))
        for effect_id in {proof["effect_id"] for proof in proofs + compression_proofs}:
            (destination / (effect_id + "-sent.txt.gz")).write_bytes(gzip.compress(sent_requests[effect_id].encode(), mtime=0))
