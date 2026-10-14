from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from novel_forge.modules.book_authority import manuscript
from novel_forge.modules.book_authority.working_prose import (
    CONTEXT_VERSION,
    INSTRUCTION,
    POLICY_VERSION,
    project_working_sources,
    complete_prose_delivery,
    validate_working_projection,
    working_prose_policy,
)
from novel_forge.modules.chapter_authority.author_editor import text_hash
from novel_forge.modules.chapter_authority.execution_artifacts import (
    build_chapter_execution_intent,
    validate_chapter_execution_intent,
)
from novel_forge.modules.chapter_authority.provider_views import (
    build_provider_context_view,
    build_provider_task_view,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.domain import canonical_hash
from tests.unit.test_chapter_execution_artifacts import _plan


def policy(**overrides):
    return {
        "version": POLICY_VERSION,
        "history_chapters": 4,
        "recent_complete_chapters": 1,
        "max_characters": 1000,
        "queries": ["promise"],
        "guidance_mode": "COMBINED",
        **overrides,
    }


def snapshot():
    sources = [
        {
            "chapter": n,
            "asset_version_id": f"selected:{n}",
            "content_hash": f"sha256:source:{n}",
            "text_hash": text_hash(text),
            "text": text,
        }
        for n, text in enumerate(
            [
                "An old promise.\n\nAn unrelated detail.",
                "She believed the bell signalled safety.\n\nOnly the reader saw the broken wire.",
                "He said the plan might fail.\n\nNobody had tried it yet.",
                "She kept her promise.\n\nHe heard the bell and waited.",
            ],
            1,
        )
    ]
    body = {
        "version": CONTEXT_VERSION,
        "book_run_id": "run",
        "project_id": "p",
        "book_id": "b",
        "target_chapter": 5,
        "accepted_through_chapter": 0,
        "authority": "AUTHOR_WORKING_PROSE_ONLY",
        "structured_facts": [],
        "projection_policy": policy(),
        "instruction": INSTRUCTION,
        "sources": project_working_sources(sources, target_chapter=5, policy=policy()),
    }
    return {**body, "snapshot_hash": canonical_hash(body)}


def rehash(body):
    body["snapshot_hash"] = canonical_hash(
        {k: v for k, v in body.items() if k != "snapshot_hash"}
    )


def test_complete_prose_delivery_coalesces_ranges_without_changing_any_literal_or_omission():
    original = snapshot()
    before = deepcopy(original)
    delivered, receipt = complete_prose_delivery(original)
    assert original == before
    validate_working_projection(delivered, project_id="p", book_id="b", target_chapter=5, accepted_through_chapter=0)
    assert receipt["source_snapshot_hash"] == original["snapshot_hash"]
    assert receipt["delivery_snapshot_hash"] == delivered["snapshot_hash"]
    for raw, result in zip(original["sources"], delivered["sources"], strict=True):
        assert {k: v for k, v in raw.items() if k != "passages"} == {k: v for k, v in result.items() if k != "passages"}
        assert "".join(p["text"] for p in raw["passages"]) == "".join(p["text"] for p in result["passages"])
        if raw["omitted_ranges"]:
            assert raw == result
        else:
            assert len(result["passages"]) == 1
    damaged = deepcopy(original)
    damaged["sources"][-1]["text_hash"] = text_hash("different complete story")
    rehash(damaged)
    with pytest.raises(KernelError, match="WORKING_PROSE_DELIVERY_DRIFT"):
        complete_prose_delivery(damaged)


def test_projection_retains_literal_belief_and_reader_only_prose_without_promoting_it():
    value = snapshot()
    validate_working_projection(
        value, project_id="p", book_id="b", target_chapter=5, accepted_through_chapter=0
    )
    assert value["structured_facts"] == []
    assert all(row["character_knowledge"] == "NOT_VERIFIED" for row in value["sources"])
    assert any(
        "Only the reader" in p["text"]
        for row in value["sources"]
        for p in row["passages"]
    )
    assert all(row["omitted_ranges"] == [] for row in value["sources"])


@pytest.mark.parametrize(
    "mutation",
    [
        "scope",
        "accepted",
        "promotion",
        "future",
        "missing",
        "overlap",
        "text",
        "budget",
        "nested_fact",
    ],
)
def test_rehashed_invalid_evidence_still_fails(mutation):
    value = snapshot()
    if mutation == "scope":
        value["book_id"] = "foreign"
    if mutation == "accepted":
        value["accepted_through_chapter"] = 5
    if mutation == "promotion":
        value["sources"][0]["character_knowledge"] = "VERIFIED"
    if mutation == "future":
        value["sources"][-1]["chapter"] = 6
    if mutation == "missing":
        value["sources"].pop(0)
    if mutation == "overlap":
        value["sources"][0]["passages"][1]["start"] = 0
    if mutation == "text":
        value["sources"][0]["passages"][0]["text"] = "Invented replacement"
    if mutation == "nested_fact":
        value["sources"][0]["accepted_fact_ids"] = ["promoted"]
    if mutation == "budget":
        value["projection_policy"]["max_characters"] = 1
    rehash(value)
    with pytest.raises(KernelError, match="WORKING_PROSE_PROJECTION_INVALID"):
        validate_working_projection(value, project_id="p", book_id="b")


def test_required_recent_source_cannot_be_truncated_to_fit():
    with pytest.raises(KernelError, match="WORKING_PROSE_REQUIRED_INPUT_OVERFLOW"):
        project_working_sources(
            [{"chapter": 4, "text": "A complete paragraph."}],
            target_chapter=5,
            policy=policy(max_characters=3),
        )


def test_query_selects_complete_attributed_old_units_and_records_omissions():
    text = "Irrelevant paragraph.\n\nAn old promise remembered.\n\nAnother detail."
    sources = [{"chapter": 1, "text": text}, {"chapter": 2, "text": "Recent."}]
    result = project_working_sources(
        sources, target_chapter=3, policy=policy(history_chapters=2, max_characters=38)
    )
    assert [p["text"] for p in result[0]["passages"]] == [
        "An old promise remembered.\n\n"
    ]
    assert result[0]["omitted_ranges"] == [
        {"start": 0, "end": 23},
        {"start": 51, "end": len(text)},
    ]
    assert result[1]["omitted_ranges"] == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"history_chapters": True},
        {"recent_complete_chapters": 5},
        {"queries": [""]},
        {"version": "latest"},
        {"guidance_mode": []},
    ],
)
def test_optional_profile_policy_is_strict_and_default_remains_off(overrides):
    assert working_prose_policy({}) is None
    with pytest.raises(KernelError, match="WORKING_PROSE_POLICY_INVALID"):
        working_prose_policy({"working_prose_policy": policy(**overrides)})


def test_memo_consumes_exact_working_experience_and_character_goal_without_acceptance():
    plan = _plan()
    plan["book_id"] = "b"
    plan["character_participation"] = [
        {
            "character_id": "actor",
            "goal": "keep her promise",
            "causal_trigger": "she heard the bell",
            "entry_emotion": "hope",
            "exit_emotion": "uncertain",
        }
    ]
    intent = build_chapter_execution_intent(
        project_id="p",
        operation_id="op",
        chapter_plan_asset_version_id="plan",
        chapter_plan_content_hash="sha256:plan",
        chapter_plan=plan,
        accepted_inputs=[],
        accepted_through_chapter=0,
        working_manuscript=snapshot(),
    )
    validate_chapter_execution_intent(intent)
    before = deepcopy(intent)
    task = build_provider_task_view("memo", {"execution_intent": intent})
    build_provider_context_view("memo", intent, task)
    assert task["frozen_intent"]["working_manuscript"] == snapshot()
    assert (
        task["frozen_intent"]["character_situation"]["participants"]
        == plan["character_participation"]
    )
    assert (
        intent == before
        and intent["accepted_boundary"]["accepted_through_chapter"] == 0
    )
    changed = deepcopy(task)
    changed["frozen_intent"]["working_manuscript"]["sources"][0]["asset_version_id"] = (
        "discarded"
    )
    with pytest.raises(KernelError, match="CHAPTER_MEMO_INTENT_DRIFT"):
        build_provider_context_view("memo", intent, changed)


def test_book_checks_literal_ranges_against_source_even_when_passage_hash_is_recomputed():
    value = snapshot()
    source_text = "An old promise.\n\nAn unrelated detail."
    value["sources"][0]["passages"][0]["text"] = "An old premise.\n\n"
    value["sources"][0]["passages"][0]["text_hash"] = text_hash(
        value["sources"][0]["passages"][0]["text"]
    )
    rehash(value)
    source = SimpleNamespace(
        content_hash=value["sources"][0]["content_hash"],
        content={"text": source_text, "title": "", "chapter": 1},
        asset_type="chapter_draft",
    )
    uow = MagicMock()
    uow.repositories.asset_documents.require.return_value = source
    with pytest.raises(KernelError, match="MANUSCRIPT_SOURCE_HASH_INVALID"):
        manuscript.verify_working_context(
            uow,
            {"project_id": "p", "book_id": "b", "book_run_id": "run"},
            value,
            require_current=False,
        )


def test_frozen_legacy_reconstruction_does_not_load_new_profile(monkeypatch):
    uow = MagicMock()
    book = {
        "project_id": "p",
        "book_id": "b",
        "book_run_id": "run",
        "accepted_through_chapter": 0,
        "production_profile_version": "new-profile",
    }
    monkeypatch.setattr(manuscript, "working_dependency_changes", lambda *_: ([], {}))
    monkeypatch.setattr(
        manuscript,
        "selected_source",
        lambda _uow, _book, number: SimpleNamespace(
            asset_version_id=f"source:{number}",
            content_hash="hash",
            asset_type="chapter_draft",
            content={"text": "Whole source", "title": "", "chapter": number},
        ),
    )
    value = manuscript.freeze_working_context(uow, book, 2, projection_policy=None)
    assert (
        "projection_policy" not in value
        and value["sources"][0]["excerpt"] == "Whole source"
    )
    uow.repositories.asset_documents.require.assert_not_called()


def test_enhanced_memo_reaches_final_provider_prompt_and_preserves_legacy_skill():
    _assert_enhanced_prompt("memo", False)


@pytest.mark.parametrize("progression", [False, True])
def test_writer_system_progression_overlay_is_versioned_and_legacy_unchanged(progression):
    _assert_enhanced_prompt("draft", progression)


def _assert_enhanced_prompt(stage, progression):
    from pathlib import Path
    from novel_forge.modules.capability_packs.artifacts import (
        ArtifactKind,
        default_chapter_artifact_resolver,
    )
    from novel_forge.modules.chapter_authority.execution_gateway import (
        _materialize_chapter_codex_prompt,
    )
    from novel_forge.modules.chapter_authority.provider_output_contracts import (
        chapter_provider_output_schema,
    )
    from novel_forge.modules.production_execution import ExecutionRuntimeClass
    from tests.unit.test_production_execution_gateway import contracts
    from tests.unit.test_capability_pack_artifact_materialization import (
        _registered_version_and_snapshot,
    )
    from novel_forge.modules.capability_pack_authority.runtime import (
        materialize_registered_pack_version,
    )

    plan = _plan()
    plan["book_id"] = "b"
    working = snapshot()
    if progression:
        from novel_forge.modules.book_authority.working_prose import PROGRESSION_POLICY_VERSION, working_instruction
        from novel_forge.modules.narrative_state.working_memory import compile_working_memory, bind_packet_coverage
        working["projection_policy"]["version"] = PROGRESSION_POLICY_VERSION
        working["instruction"] = working_instruction(working["projection_policy"])
        for row in working["sources"]:
            pointer = {key: row[key] for key in ("asset_version_id", "content_hash")}
            row["source_resolution"] = {"native_source": pointer, "effective_source": pointer,
                "native_basis": "NATIVE_DRAFT_OUTPUT", "overrides": []}
        working["working_memory"] = bind_packet_coverage(compile_working_memory([], queries=[], max_characters=1000), working["sources"])
        rehash(working)
    intent = build_chapter_execution_intent(
        project_id="p",
        operation_id="op",
        chapter_plan_asset_version_id="plan",
        chapter_plan_content_hash="sha256:plan",
        chapter_plan=plan,
        accepted_inputs=[],
        accepted_through_chapter=0,
        working_manuscript=working,
    )
    registered, binding = _registered_version_and_snapshot()
    pack = materialize_registered_pack_version(binding, registered)
    *_, request = contracts(
        backend_id="codex-cli", runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE
    )
    prompt, evidence = _materialize_chapter_codex_prompt(
        request=request,
        stage=stage,
        inputs={"execution_intent": intent, "plan": plan, "style": {"policies": []}},
        materialization={
            "materialization_hash": binding.manifest_hash,
            "pack_artifacts": {
                "system_instruction": pack.system_instruction.to_dict(),
                "prompt_template": pack.prompt_template.to_dict(),
                "skill": pack.skill.to_dict() if stage == "draft" else {
                    "ref": "chapter-outline",
                    "version": "chapter-plan-skill-v3",
                    "content_hash": "sha256:skill",
                    "content": {
                        "text": "## Shared rules\nPreserve evidence.\n## Memo\nUse exact experience."
                    },
                },
            },
            "context_selection": [{"asset_version_id": "intent", "content": intent if stage == "memo" else {
                "project_id": "p", "book_id": "b", "chapter": 5,
                "context_segments": [], "working_manuscript": working,
            }}],
            "knowledge_selection": [item.to_dict() for item in pack.required_knowledge],
            "tool_permissions": {"allowed": ["model.provider.invoke"], "denied": []},
            "output_schema": {
                "ref": "memo",
                "content_hash": "sha256:output",
                "content": chapter_provider_output_schema("memo"),
            },
        },
    )
    assert "Only the reader saw the broken wire." in prompt
    assert "AUTHOR_WORKING_PROSE_ONLY" in prompt and "NOT_VERIFIED" in prompt
    if stage == "memo":
        assert "FROZEN_INTENT_ONLY" in prompt
    if progression:
        import hashlib
        from novel_forge.modules.book_authority.working_prose import PROGRESSION_INSTRUCTION
        projection = evidence["progression_policy_projection"]
        assert projection["source_snapshot_hash"] == working["snapshot_hash"]
        assert PROGRESSION_INSTRUCTION in prompt
        assert projection["overlay_hash"].startswith("sha256:")
        assert projection["effective_system_hash"] != pack.system_instruction.content_hash
        overlay = "\nThe selected frozen progression policy governs this new candidate within its fictional constraints.\n" + PROGRESSION_INSTRUCTION
        assert projection["overlay_hash"] == "sha256:" + hashlib.sha256(overlay.encode()).hexdigest()
    else:
        assert "progression_policy_projection" not in evidence
    resolver = default_chapter_artifact_resolver(Path(__file__).resolve().parents[2])
    assert (
        resolver.resolve(
            ArtifactKind.SKILL, "prose-generation", "prose-generation-v4"
        ).content_hash
        == pack.skill.content_hash
    )
    assert (
        resolver.resolve(
            ArtifactKind.SKILL, "prose-generation", "prose-generation-v5"
        ).content_hash
        != pack.skill.content_hash
    )


def test_current_pack_keeps_each_exact_skill_binding_including_review_v4():
    import json
    from pathlib import Path
    from novel_forge.modules.capability_packs.artifacts import (
        ArtifactKind,
        default_chapter_artifact_resolver,
    )

    root = Path(__file__).resolve().parents[2]
    resolver = default_chapter_artifact_resolver(root)
    manifest = json.loads(
        (root / "config/capability_packs/chapter_generation_pack.json").read_text()
    )
    for binding in manifest["skill_binding"]["skills"]:
        assert (
            resolver.resolve(
                ArtifactKind.SKILL, binding["skill_ref"], binding["version"]
            ).content_hash
            == binding["content_hash"]
        )


def test_planning_v3_carries_same_working_sources_without_fact_or_actor_promotion():
    from tests.unit.test_planning_working_continuity import inputs

    raw, context = inputs()
    working = snapshot()
    working["project_id"], working["book_id"] = "project:original", "book:original"
    rehash(working)
    for source in (raw, context):
        source["working_continuity_projection_version"] = (
            "planning-working-continuity.v3"
        )
        source["arc_working_set"]["working_manuscript"] = deepcopy(working)
    task = build_provider_task_view("chapter_group_plan.generate", raw)
    view = build_provider_context_view("chapter_group_plan.generate", context, task)
    assert task["working_continuity"] == view["working_continuity"]
    assert task["arc_working_set"]["working_manuscript"]["structured_facts"] == []
    assert view["accepted_state_boundary"] == {"accepted_through_chapter": 0}


def _writer_context_with_working_intent():
    import json
    from tests.unit.test_provider_task_views import _context

    context = _context(0)
    working = snapshot()
    context['project_id'] = 'p'
    context['context_manifest']['narrative_position'] = {'book_id': 'b', 'chapter': 5}
    context['context_manifest']['authority_state_boundary'] = {'accepted_through_chapter': 0}
    context['working_manuscript'] = working
    intent = {'working_manuscript': deepcopy(working), 'chapter_objective': 'Keep the old promise.',
              'character_situation': {'authority': 'FUTURE_INTENT_NOT_OBSERVED', 'goal': 'leave safely'}}
    context['context_segments'].append({'asset_version_id': 'intent', 'asset_type': 'chapter_execution_intent',
        'safe_summary': json.dumps(intent), 'structured_facts': [], 'allowed_use': 'generation'})
    return context, intent


def test_writer_renders_selected_prose_once_and_keeps_structured_intent_losslessly():
    import json

    context, intent = _writer_context_with_working_intent()
    before = deepcopy(context)
    view = build_provider_context_view('draft', context, {}, writer_projection_version='accepted-writer-history.v2')
    assert view['contract_version'] == 'provider-context-view-v7'
    assert view['working_manuscript'] == intent['working_manuscript']
    assert view['frozen_intent'] == {key: value for key, value in intent.items() if key != 'working_manuscript'}
    assert not any(row['asset_type'] == 'chapter_execution_intent' for row in view['segments'])
    assert json.dumps(view).count('Only the reader saw the broken wire.') == 1
    assert context == before


def test_writer_rejects_rehashed_foreign_working_source_in_intent():
    import json

    context, intent = _writer_context_with_working_intent()
    intent['working_manuscript']['sources'][0]['asset_version_id'] = 'unselected:old'
    rehash(intent['working_manuscript'])
    context['context_segments'][-1]['safe_summary'] = json.dumps(intent)
    with pytest.raises(KernelError, match='WORKING_PROSE_INTENT_DRIFT'):
        build_provider_context_view('draft', context, {})


def test_legacy_writer_view_keeps_its_original_intent_summary():
    import json

    context, intent = _writer_context_with_working_intent()
    context.pop('working_manuscript')
    context['context_segments'][-1]['safe_summary'] = json.dumps({'chapter_objective': intent['chapter_objective']})
    view = build_provider_context_view('draft', context, {})
    assert 'frozen_intent' not in view
    assert any(row['asset_type'] == 'chapter_execution_intent' for row in view['segments'])


@pytest.mark.parametrize("target", [4, 5])
def test_partial_selection_resolves_contiguous_native_prose_with_provenance(monkeypatch, target):
    from novel_forge.modules.book_authority.working_prose import PROGRESSION_POLICY_VERSION
    documents = {}
    for number in (1, 2, 3, 4):
        text = f"Trial {number} spent material and changed the next choice."
        documents[f"native:{number}"] = SimpleNamespace(asset_version_id=f"native:{number}",
            content_hash=f"hash:{number}", asset_type="draft_chapter", governance="CLEAR", eligibility="ELIGIBLE",
            content={"chapter": number, "title": "", "text": text})
    documents["chosen:1"] = SimpleNamespace(asset_version_id="chosen:1", content_hash="chosen-hash",
        asset_type="best_draft_candidate", governance="CLEAR", eligibility="ELIGIBLE",
        content={"chapter": 1, "title": "", "text": "The paid trial secured access, not acceptance."})
    selection = SimpleNamespace(asset_version_id="selection:1", content_hash="selection-hash", content={
        "book_run_id": "run", "native_source_asset_version_id": "native:1",
        "selected_asset_version_id": "chosen:1", "selected_content_hash": "chosen-hash"})
    uow = MagicMock()
    def execute(query, args):
        # This fixture exercises the real delivery -> acceptance -> native-output fallback.
        number = args[-1]
        if "authority_book_manuscript_delivery" in query or "authority_book_acceptance_lineage" in query:
            uow.cursor.fetchone.return_value = None
        else:
            uow.cursor.fetchone.return_value = (f"native:{number}",)
    uow.cursor.execute.side_effect = execute
    uow.repositories.asset_documents.require.side_effect = lambda **kwargs: documents[kwargs["asset_version_id"]]
    monkeypatch.setattr(manuscript, "_optional_document", lambda _uow, _project, ref: selection if ref.endswith("/1") else None)
    monkeypatch.setattr(manuscript, "_session_ref", lambda scope: "session")
    original_require = uow.repositories.asset_documents.require.side_effect
    def require(**kwargs):
        if kwargs.get("logical_ref") == "session":
            raise KernelError("AUTHORITY_ASSET_NOT_FOUND", "No editor choice")
        return original_require(**kwargs)
    uow.repositories.asset_documents.require.side_effect = require
    monkeypatch.setattr(manuscript, "working_dependency_changes", lambda *_: ([], {}))
    monkeypatch.setattr(manuscript, "require_prose_propagation", lambda *_: None)
    monkeypatch.setattr("novel_forge.modules.book_authority.manuscript_memory.source_memory", lambda *_: ([], {"status": "NOT_REQUESTED"}))
    book = {"project_id": "p", "workspace_id": "w", "book_id": "b", "book_run_id": "run", "accepted_through_chapter": 0}
    chosen_policy = policy(version=PROGRESSION_POLICY_VERSION, history_chapters=128, recent_complete_chapters=3)
    before = deepcopy(book)
    value = manuscript.freeze_working_context(uow, book, target, projection_policy=chosen_policy)
    validate_working_projection(value, project_id="p", book_id="b", target_chapter=target, accepted_through_chapter=0)
    assert [row["asset_version_id"] for row in value["sources"]] == ["chosen:1", *[f"native:{n}" for n in range(2, target)]]
    assert [row["chapter"] for row in value["sources"]] == list(range(1, target))
    assert all(row["omitted_ranges"] == [] for row in value["sources"])
    assert value["sources"][0]["source_resolution"]["overrides"] == [{"asset_version_id": "selection:1", "content_hash": "selection-hash"}]
    assert all(row["source_resolution"]["native_basis"] == "NATIVE_DRAFT_OUTPUT" for row in value["sources"])
    assert all(row["source_resolution"]["overrides"] == [] for row in value["sources"][1:])
    assert value == manuscript.freeze_working_context(uow, book, target, projection_policy=chosen_policy)
    assert book == before
    assert all(call.args[0].lstrip().startswith("SELECT") for call in uow.cursor.execute.call_args_list)
    uow.cursor.execute.side_effect = lambda *_: setattr(uow.cursor.fetchone, "return_value", None)
    with pytest.raises(KernelError, match="MANUSCRIPT_CHAPTER_MISSING"):
        manuscript.freeze_working_context(uow, book, target, projection_policy=chosen_policy)


def test_progression_policy_survives_planning_and_writer_frozen_views_without_rewriting_history():
    from novel_forge.modules.book_authority.working_prose import PROGRESSION_POLICY_VERSION, working_instruction
    from tests.unit.test_planning_working_continuity import inputs
    from novel_forge.modules.narrative_state.working_memory import compile_working_memory, bind_packet_coverage
    old = snapshot()
    legacy_instruction = old["instruction"]
    working = deepcopy(old)
    working["projection_policy"]["version"] = PROGRESSION_POLICY_VERSION
    working["instruction"] = working_instruction(working["projection_policy"])
    for row in working["sources"]:
        pointer = {key: row[key] for key in ("asset_version_id", "content_hash")}
        row["source_resolution"] = {"native_source": pointer, "effective_source": pointer,
            "native_basis": "NATIVE_DRAFT_OUTPUT", "overrides": []}
    working["working_memory"] = bind_packet_coverage(compile_working_memory([], queries=[], max_characters=1000), working["sources"])
    rehash(working)
    raw, context = inputs()
    for value in (raw, context):
        value["arc_working_set"]["working_manuscript"] = working
        value["working_continuity_projection_version"] = "planning-working-continuity.v3"
        value["planning_command"] = {"project_id": "p", "book_id": "b", "logical_key": "chapter:5", "planning_scope": "CHAPTER"}
    context.update(project_id="p", book_id="b")
    task = build_provider_task_view("chapter_plan.generate", raw)
    view = build_provider_context_view("chapter_plan.generate", context, task)
    assert task["working_continuity"]["instruction"] == view["working_continuity"]["instruction"] == working["instruction"]
    from novel_forge.modules.chapter_authority.provider_views import project_planning_narrative_intent
    task["planning_command"].update(repair_number=1, repair_reason="Replace the repeated baseline with an attempted action and its consequence.")
    corrected, _, _ = project_planning_narrative_intent(task, view)
    assert corrected["narrative_inputs"]["planning_correction"]["instruction"] == task["planning_command"]["repair_reason"]
    assert corrected["narrative_inputs"]["planning_correction"]["authority"] == "NEW_CANDIDATE_CORRECTION_NOT_ACCEPTED_HISTORY"
    historical = deepcopy(task)
    historical["arc_working_set"]["working_manuscript"] = old
    legacy, _, _ = project_planning_narrative_intent(historical, view)
    assert "planning_correction" not in legacy["narrative_inputs"]
    from novel_forge.modules.chapter_authority.provider_views import bind_narrative_intent_schema
    frozen_schema = {"type": "object", "properties": {"ending_hook": {"type": "string", "const": "old bound ending"}, "scene_plan": {"type": "array"}}}
    described = bind_narrative_intent_schema(frozen_schema, progression=True)
    assert "connected opening friction" in described["properties"]["scene_plan"]["description"]
    assert described["properties"]["ending_hook"]["const"] == "old bound ending"
    assert "upstream Plan Change" in described["properties"]["ending_hook"]["description"]
    assert "connected opening friction" not in bind_narrative_intent_schema(frozen_schema)["properties"]["scene_plan"]["description"]
    import json
    writer_context, writer_intent = _writer_context_with_working_intent()
    writer_context["working_manuscript"] = working
    writer_intent["working_manuscript"] = deepcopy(working)
    writer_context["context_segments"][-1]["safe_summary"] = json.dumps(writer_intent)
    writer = build_provider_context_view("draft", writer_context, {}, writer_projection_version="accepted-writer-history.v2")
    assert writer["working_manuscript"] == working
    assert json.dumps(writer).count("single bridging clause") == 1
    for phrase in ("starting premises", "single bridging clause", "three connected", "cost-gain exchange", "irreversible", "open action loop", "never a static reset"):
        assert phrase in working["instruction"]
    assert "Do not force conflict" not in working["instruction"]
    assert snapshot()["instruction"] == legacy_instruction
    assert "three connected" not in legacy_instruction
    assert working["accepted_through_chapter"] == 0 and working["structured_facts"] == []
    bad = deepcopy(working)
    bad["sources"][1]["source_resolution"]["effective_source"]["asset_version_id"] = "unselected"
    rehash(bad)
    with pytest.raises(KernelError, match="WORKING_PROSE_SOURCE_RESOLUTION_INVALID"):
        validate_working_projection(bad, project_id="p")


def test_progression_prefers_committed_acceptance_over_delivery_and_selection(monkeypatch):
    source = SimpleNamespace(asset_version_id="accepted:1", content_hash="accepted-hash",
        asset_type="draft_chapter", governance="CLEAR", eligibility="ELIGIBLE",
        content={"chapter": 1, "title": "", "text": "The already committed choice remains the premise."})
    uow = MagicMock()
    uow.cursor.fetchone.return_value = (source.asset_version_id,)
    uow.repositories.asset_documents.require.return_value = source
    selection = MagicMock(side_effect=AssertionError("Acceptance must not be overridden"))
    monkeypatch.setattr(manuscript, "_optional_document", selection)
    book = {"project_id": "p", "workspace_id": "w", "book_id": "b", "book_run_id": "run"}
    actual, provenance = manuscript.resolve_working_source(uow, book, 1)
    assert actual is source and provenance["native_basis"] == "ACCEPTED_OUTCOME"
    assert provenance["overrides"] == []
    assert "authority_book_acceptance_lineage" in uow.cursor.execute.call_args.args[0]
    assert uow.cursor.execute.call_count == 1
    selection.assert_not_called()


def test_progression_does_not_silently_drop_early_predecessors():
    from novel_forge.modules.book_authority.working_prose import PROGRESSION_POLICY_VERSION
    book = {"project_id": "p", "book_id": "b", "book_run_id": "run", "accepted_through_chapter": 0}
    with pytest.raises(KernelError, match="WORKING_PROSE_HISTORY_INCOMPLETE"):
        manuscript.freeze_working_context(MagicMock(), book, 5, projection_policy=policy(version=PROGRESSION_POLICY_VERSION, history_chapters=3))
