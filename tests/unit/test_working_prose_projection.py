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
    registered, binding = _registered_version_and_snapshot()
    pack = materialize_registered_pack_version(binding, registered)
    *_, request = contracts(
        backend_id="codex-cli", runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE
    )
    prompt, evidence = _materialize_chapter_codex_prompt(
        request=request,
        stage="memo",
        inputs={"execution_intent": intent},
        materialization={
            "materialization_hash": binding.manifest_hash,
            "pack_artifacts": {
                "system_instruction": pack.system_instruction.to_dict(),
                "prompt_template": pack.prompt_template.to_dict(),
                "skill": {
                    "ref": "chapter-outline",
                    "version": "chapter-plan-skill-v3",
                    "content_hash": "sha256:skill",
                    "content": {
                        "text": "## Shared rules\nPreserve evidence.\n## Memo\nUse exact experience."
                    },
                },
            },
            "context_selection": [{"asset_version_id": "intent", "content": intent}],
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
    assert "FROZEN_INTENT_ONLY" in prompt
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
