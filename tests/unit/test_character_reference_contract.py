import pytest

from novel_forge.modules.chapter_authority.character_references import compile_character_references, normalize_character_choices
from novel_forge.modules.chapter_authority.creative_memo import creative_memo_schema
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.worker_execution import WorkerFailureClassifier, WorkerFailureClass


def contract(cast=None):
    return compile_character_references(project_id="p", workspace_id="w", book_id="b", snapshot_id="snapshot-7",
        cast_version_id="cast-9", cast_content_hash="sha256:frozen", cast=cast or {"book_id": "b", "characters": [
            {"character_id": "character:17", "name": "乙", "aliases": ["小乙"]}]}, scenes=[{"participants": ["乙"]}])


def output(token):
    return {"creative_guidance": {"character_choices": [{"character_id": token, "choice": "乙的决定", "motivation": "x"}]}}


@pytest.mark.parametrize("token", ["character:17", "乙", "小乙"])
def test_exact_unique_frozen_binding_preserves_prose(token):
    value = output(token)
    result = normalize_character_choices({"project_id": "p", "scene_plans": [{"participants": ["乙"]}]}, value, contract())
    assert result["creative_guidance"]["character_choices"][0] == {"character_id": "character:17", "choice": "乙的决定", "motivation": "x"}
    assert value == output(token)


@pytest.mark.parametrize("token", ["character:yi", "character:18", "someone", "乙 "])
def test_unknown_references_fail_without_guessing(token):
    with pytest.raises(KernelError, match="Unknown or ambiguous"):
        normalize_character_choices({"project_id": "p", "scene_plans": [{"participants": ["乙"]}]}, output(token), contract())


def test_cross_book_and_ambiguous_name_are_rejected():
    cast = {"book_id": "elsewhere", "characters": []}
    with pytest.raises(KernelError):
        contract(cast)
    cast = {"book_id": "b", "characters": [{"character_id": "a", "name": "乙", "aliases": []}, {"character_id": "b", "name": "乙", "aliases": []}]}
    with pytest.raises(KernelError):
        contract(cast)


def test_schema_uses_same_program_owned_ids():
    schema = creative_memo_schema(character_references=contract())
    assert schema["properties"]["creative_guidance"]["properties"]["character_choices"]["items"]["properties"]["character_id"] == {"enum": ["character:17"]}


def test_legacy_names_still_work_but_ids_are_not_invented():
    intent = {"scene_plans": [{"participants": ["乙"]}]}
    assert normalize_character_choices(intent, output("乙")) == output("乙")
    with pytest.raises(KernelError):
        normalize_character_choices(intent, output("character:17"))


@pytest.mark.parametrize("code", ["CHAPTER_MEMO_CHARACTER_DRIFT", "CHAPTER_MEMO_REFERENCE_CONTRACT_INVALID", "CHAPTER_MEMO_MISSION_DRIFT"])
def test_contract_errors_do_not_retry_the_same_input(code):
    assert WorkerFailureClassifier.classify(KernelError(code, "invalid frozen contract")) is WorkerFailureClass.FINAL_FAILURE


def test_alias_shared_with_nonparticipant_is_not_a_trusted_binding():
    cast = {"book_id": "b", "characters": [{"character_id": "a", "name": "乙", "aliases": ["同名"]}, {"character_id": "b", "name": "丙", "aliases": ["同名"]}]}
    with pytest.raises(KernelError):
        normalize_character_choices({"project_id": "p", "scene_plans": [{"participants": ["乙"]}]}, output("同名"), contract(cast))
