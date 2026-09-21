from __future__ import annotations

import unittest

from novel_forge.modules.chapter_authority.author_editor import edit_map, reconcile_author_scenes, text_hash
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.book_authority.author_revision import require_author_replacement_dispatch


class AuthorEditorTests(unittest.TestCase):
    def test_unicode_codepoint_edit_preserves_exact_unedited_text(self):
        before, after = '　剑😀未出。\r\n她留步。\n', '　剑😀已出。\r\n她留步。\n'
        edits = edit_map(before, after)
        self.assertEqual(edits, [{"start": 3, "end": 4, "after_start": 3, "after_end": 4, "before": "未", "after": "已"}])
        self.assertNotEqual(text_hash(before), text_hash(before.strip()))
        rebuilt = before
        for item in reversed(edits):
            rebuilt = rebuilt[:item['start']] + item['after'] + rebuilt[item['end']:]
        self.assertEqual(rebuilt, after)

    def test_scene_mapping_follows_author_word_edit_without_stale_prose(self):
        source = {"text": "剑未出。\n\n她留步。", "scene_artifacts": [
            {"slot_id": "fight:skeleton", "text": "剑未出。", "used_fact_ids": []},
            {"slot_id": "talk:skeleton", "text": "她留步。", "used_fact_ids": []}]}
        scenes = reconcile_author_scenes(source, "剑已出。\n\n她留步。")
        self.assertEqual(scenes[0]['text'], "剑已出。")
        self.assertEqual(scenes[1], source['scene_artifacts'][1])
        with self.assertRaises(KernelError) as caught:
            reconcile_author_scenes(source, "剑未出。她留步。")
        self.assertEqual(caught.exception.code, "AUTHOR_SCENE_MAPPING_REQUIRED")
        with self.assertRaises(KernelError) as removed:
            reconcile_author_scenes(source, "剑未出。\n\n")
        self.assertEqual(removed.exception.code, "AUTHOR_SCENE_SCOPE_CONFLICT")

    def test_author_explicit_scene_mapping_cannot_change_slot_identity(self):
        source = {"text": "剑未出。", "scene_artifacts": [{"slot_id": "a", "text": "剑未出。", "used_fact_ids": []}]}
        with self.assertRaises(KernelError) as caught:
            reconcile_author_scenes(source, "剑已出。", [{"slot_id": "b", "text": "剑已出。", "used_fact_ids": []}])
        self.assertEqual(caught.exception.code, "AUTHOR_SCENE_SCOPE_CONFLICT")

    def test_malformed_author_replacement_fails_closed_before_database_access(self):
        for binding in ([], 'marker', {}, {'contract_version':'book-author-replacement.v1'}):
            with self.subTest(binding=binding), self.assertRaises(KernelError) as caught:
                require_author_replacement_dispatch('invalid-database-never-used', command_payload={
                    'preparation_report':{'author_book_replacement':binding}}, root_operation_id='root')
            self.assertEqual(caught.exception.code,'BOOK_AUTHOR_REPLACEMENT_INVALID')
        require_author_replacement_dispatch('invalid-database-never-used',command_payload={'preparation_report':None},root_operation_id='legacy-root')


    def test_explicit_cross_scene_mapping_preserves_scope_and_revises_exact_unicode(self):
        from novel_forge.modules.chapter_authority.realization_composition import integrate_realization, reconcile_revision_composition
        from novel_forge.modules.review.craft import _scene_ranges
        source = {"text": "　剑😀未出。\n\n她留步。", "scene_artifacts": [
            {"slot_id": "a", "text": "　剑😀未出。", "used_fact_ids": []},
            {"slot_id": "b", "text": "她留步。", "used_fact_ids": []}]}
        contract = {"contract_digest": "hash", "slots": [
            {"slot_id": "a", "scene_id": "first", "accessible_knowledge": []},
            {"slot_id": "b", "scene_id": "second", "accessible_knowledge": []}], "voices": []}
        source["realization_contract"] = contract
        mapped = [{"slot_id": "a", "text": "　剑😀未出，", "used_fact_ids": []},
                  {"slot_id": "b", "text": "她便留步。", "used_fact_ids": []}]
        text = "　剑😀未出，她便留步。"
        actual = reconcile_author_scenes(source, text, mapped, [""])
        integrated = integrate_realization(contract=contract, artifacts=actual, text=text, separators=[""])
        draft = {**integrated, "text": text}
        self.assertEqual(_scene_ranges(draft), {"first": [{"start": 0, "end": 6}], "second": [{"start": 6, "end": 11}]})
        changed = reconcile_author_scenes(draft, text.replace("未", "已"))
        revision = reconcile_revision_composition(draft, {"scene_artifacts": changed, "text": text.replace("未", "已")})
        self.assertEqual(revision["scene_separators"], [""])
        self.assertEqual(revision["changed_slot_ids"], ["a"])
        self.assertNotEqual(integrated["composition_digest"], revision["composition_digest"])
        with self.assertRaises(KernelError):
            reconcile_author_scenes(source, text, [{**mapped[0], "scene_id": "invented"}, mapped[1]], [""])
        with self.assertRaises(KernelError):
            reconcile_author_scenes(source, text, [{**mapped[0], "used_fact_ids": ["secret"]}, mapped[1]], [""])
        with self.assertRaises(KernelError):
            reconcile_author_scenes(source, text, mapped, ["invented text"])


    def test_unmapped_prose_cannot_invent_a_scene(self):
        with self.assertRaises(KernelError) as caught:
            reconcile_author_scenes({"text": "原文"}, "改文", [{"slot_id": "invented", "text": "改文", "used_fact_ids": []}])
        self.assertEqual(caught.exception.code, "AUTHOR_SCENE_SCOPE_CONFLICT")


def test_repeated_candidate_requires_retained_realization_contract():
    from types import SimpleNamespace
    from novel_forge.modules.chapter_authority.author_editor import source_draft_content
    contract = {"plan_version_id": "original-plan", "slots": [
        {"slot_id": "one", "scene_id": "s", "accessible_knowledge": []}], "voices": [], "contract_digest": "digest"}
    draft = {"text": "守密。", "scene_artifacts": [{"slot_id": "one", "text": "守密。", "used_fact_ids": []}], "realization_contract": contract}
    source = SimpleNamespace(asset_type="author_edit_candidate", content={**draft, "draft_content": draft})
    retained = source_draft_content(source)
    assert retained["realization_contract"]["plan_version_id"] == "original-plan"
    try:
        reconcile_author_scenes(retained, "泄密。", [{"slot_id": "one", "text": "泄密。", "used_fact_ids": ["unlearned-secret"]}])
    except KernelError as error:
        assert error.code == "REALIZATION_EPISTEMIC_SCOPE_VIOLATION"
    else:
        raise AssertionError("second author edit leaked an unavailable fact")
