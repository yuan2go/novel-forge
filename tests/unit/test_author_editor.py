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
