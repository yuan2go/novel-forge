from __future__ import annotations

import unittest

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.chapter_authority.author_draft import freeze_author_adoption
from novel_forge.modules.chapter_authority.author_editor import ChapterAuthorEditingApplication, text_hash
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated, identifier, insert_definition, insert_operation, seed_authority_project_book


def seed_editor_source():
    project_id, workspace_id, book_id = identifier("author-project"), identifier("author-workspace"), identifier("author-book")
    seed_authority_project_book(project_id=project_id, workspace_id=workspace_id, book_id=book_id)
    root = identifier("author-chapter-root")
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        definition = identifier("author-fixture-chapter")
        insert_definition(uow.cursor, definition)
        insert_operation(uow.cursor, operation_id=root, definition_name=definition, project_id=project_id,
                         workspace_id=workspace_id, status="EXECUTING", command_payload={"chapter": 1, "book_id": book_id})
        document = uow.repositories.asset_documents.materialize_output(AuthorityAssetWriteCommand(
            operation_id=root, project_id=project_id, asset_id=identifier("author-draft"), asset_type="draft_chapter",
            schema_version="fixture-author-prose.v1", logical_ref=f"drafts/{root}", category="drafts", output_key="chapter.draft",
            role="primary", content={"chapter": 1, "title": "关山旧约", "text": "　剑😀未出。\n\n她留步。\n",
                "scene_artifacts": [{"slot_id": "s1:skeleton", "text": "　剑😀未出。\n\n她留步。\n", "used_fact_ids": []}]},
            qualification_policy="fixture-only", trace_id=identifier("trace"), correlation_id=identifier("correlation")))
        uow.commit()
    return {"project_id": project_id, "workspace_id": workspace_id, "book_id": book_id, "chapter": 1,
            "base_asset_version_id": document.asset_version_id, "base_asset_hash": document.content_hash,
            "base_text_hash": text_hash(document.content["text"]), "expected_version": 0}, document


class AuthorEditorPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_migrated()

    def setUp(self):
        self.scope, self.source = seed_editor_source()
        self.principal = Principal("author-editor-test", PrincipalType.LOCAL_OPERATOR,
                                   frozenset({"chapter.authority.execute", "chapter.authority.query"}),
                                   frozenset({self.scope['project_id']}), "test")
        self.app = ChapterAuthorEditingApplication(DATABASE_URL, application_build_id="author-test", commit_sha="e" * 40)
        self.payload = {**self.scope, "text": "　剑😀已出。\n\n她留步。\n", "rights_basis": "ORIGINAL_AUTHOR_INPUT"}

    def test_exact_input_accepts_candidate_and_freezes_native_review_handoff(self):
        saved = self.app.execute(action="save", payload=self.payload, idempotency_key=identifier("save"), principal=self.principal)
        accepted = self.app.execute(action="accept", payload={**self.scope, "expected_version": saved['version'],
                                   "candidate_asset_version_id": saved['candidate_asset_version_id'], "rationale": "纠正动作次序"},
                                   idempotency_key=identifier("accept"), principal=self.principal)
        frozen = freeze_author_adoption(DATABASE_URL, **{key: self.scope[key] for key in ('project_id','workspace_id','book_id','chapter')},
                                        candidate_asset_version_id=saved['candidate_asset_version_id'],
                                        decision_asset_version_id=accepted['decision_asset_version_id'], principal=self.principal)
        self.assertEqual(frozen['text_hash'], text_hash(self.payload['text']))
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            base = uow.repositories.asset_documents.require(project_id=self.scope['project_id'], asset_version_id=self.source.asset_version_id)
            candidate = uow.repositories.asset_documents.require(project_id=self.scope['project_id'], asset_version_id=saved['candidate_asset_version_id'])
        self.assertEqual(base.content['text'], self.source.content['text'])
        self.assertEqual(candidate.content['text'], self.payload['text'])
        self.assertEqual(candidate.content['edits'][0]['start'], 3)
        self.assertEqual(accepted['editor_status'], 'ADOPTED_PENDING_REVIEW')
        different_base = self.app.require(**{key: self.scope[key] for key in ('project_id','workspace_id','book_id','chapter')},
            base_asset_version_id=saved['candidate_asset_version_id'],principal=self.principal)
        self.assertIsNone(different_base['session'])
        self.assertEqual(different_base['version'], accepted['version'])
        self.assertEqual(different_base['text'], self.payload['text'])

    def test_repeated_author_candidate_retains_original_contract_and_scope(self):
        saved = self.app.execute(action="save", payload=self.payload, idempotency_key=identifier("first-edit"), principal=self.principal)
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            first = uow.repositories.asset_documents.require(project_id=self.scope["project_id"], asset_version_id=saved["candidate_asset_version_id"])
        second_payload = {**self.payload, "expected_version": saved["version"],
            "base_asset_version_id": first.asset_version_id, "base_asset_hash": first.content_hash,
            "base_text_hash": first.content["text_hash"], "text": first.content["text"].replace("留步", "止步")}
        second = self.app.execute(action="save", payload=second_payload, idempotency_key=identifier("second-edit"), principal=self.principal)
        adopted = self.app.execute(action="accept", payload={**second_payload, "expected_version": second["version"],
            "candidate_asset_version_id": second["candidate_asset_version_id"], "rationale": "复核两轮措辞"},
            idempotency_key=identifier("adopt-second"), principal=self.principal)
        frozen = freeze_author_adoption(DATABASE_URL, **{key: self.scope[key] for key in ("project_id", "workspace_id", "book_id", "chapter")},
            candidate_asset_version_id=second["candidate_asset_version_id"], decision_asset_version_id=adopted["decision_asset_version_id"], principal=self.principal)
        self.assertEqual(frozen["originating_draft_asset_version_id"], self.source.asset_version_id)
        self.assertEqual(frozen["base_asset_version_id"], first.asset_version_id)
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            candidate = uow.repositories.asset_documents.require(project_id=self.scope["project_id"], asset_version_id=second["candidate_asset_version_id"])
        self.assertNotIn("draft_content", candidate.content["draft_content"])
        self.assertEqual(candidate.content["draft_content"]["scene_artifacts"][0]["text"], second_payload["text"])
        self.assertEqual(candidate.content["draft_content"]["chapter"], 1)

    def test_commit_response_loss_replays_once_and_conflict_keeps_author_input(self):
        def lose_response(name):
            if name == 'after_operation_completion_before_response':
                raise RuntimeError('simulated lost HTTP response after durable commit')
        self.app.fault_injector = lose_response
        key = identifier('lost-response')
        with self.assertRaises(RuntimeError):
            self.app.execute(action='save', payload=self.payload, idempotency_key=key, principal=self.principal)
        self.app.fault_injector = None
        replay = self.app.execute(action='save', payload=self.payload, idempotency_key=key, principal=self.principal)
        self.assertTrue(replay['replayed'])
        with self.assertRaises(KernelError) as caught:
            self.app.execute(action='save', payload={**self.payload, 'text': '另一个并发版本。'}, idempotency_key=identifier('concurrent'), principal=self.principal)
        self.assertEqual(caught.exception.code, 'AUTHOR_VERSION_CONFLICT')
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            candidates = uow.repositories.asset_documents.list(project_id=self.scope['project_id'], asset_type='author_edit_candidate')
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].content['text'], self.payload['text'])

    def test_reject_is_read_only_for_original_and_cannot_authorize_adoption(self):
        saved = self.app.execute(action='save', payload=self.payload, idempotency_key=identifier('save'), principal=self.principal)
        rejected = self.app.execute(action='reject', payload={**self.scope, 'expected_version': saved['version'],
                                   'candidate_asset_version_id': saved['candidate_asset_version_id'], 'rationale': '保留含蓄动作'},
                                   idempotency_key=identifier('reject'), principal=self.principal)
        with self.assertRaises(KernelError) as caught:
            freeze_author_adoption(DATABASE_URL, **{key: self.scope[key] for key in ('project_id','workspace_id','book_id','chapter')},
                                   candidate_asset_version_id=saved['candidate_asset_version_id'],
                                   decision_asset_version_id=rejected['decision_asset_version_id'], principal=self.principal)
        self.assertEqual(caught.exception.code, 'AUTHOR_ADOPTION_INVALID')

    def test_scope_hash_selection_and_principal_are_enforced(self):
        for change, code in [({'book_id': 'other-book'}, 'AUTHOR_BOOK_SCOPE_CONFLICT'),
                             ({'chapter': 2}, 'AUTHOR_BASE_SCOPE_CONFLICT'),
                             ({'base_text_hash': text_hash('forged')}, 'AUTHOR_BASE_HASH_CONFLICT'),
                             ({'allowed_ranges': [{'start': 7, 'end': 8}]}, 'AUTHOR_EDIT_OUTSIDE_RANGE')]:
            with self.subTest(code=code), self.assertRaises(KernelError) as caught:
                self.app.execute(action='save', payload={**self.payload, **change}, idempotency_key=identifier('invalid'), principal=self.principal)
            self.assertEqual(caught.exception.code, code)
        denied = Principal('reader', PrincipalType.LOCAL_OPERATOR, frozenset({'chapter.authority.query'}), frozenset({'*'}), 'test')
        with self.assertRaises(PermissionError):
            self.app.execute(action='save', payload=self.payload, idempotency_key=identifier('denied'), principal=denied)

    def test_authored_draft_and_partial_revision_survive_unresolved_formal_review(self):
        from novel_forge.modules.chapter_authority.handlers import DeterministicFixtureChapterProvider, build_chapter_handler_registry
        from novel_forge.modules.chapter_authority.orchestrator import SingleChapterRequest, run_single_chapter_slice
        from novel_forge.modules.chapter_authority.contracts import ChapterNode
        from novel_forge.modules.command_kernel.external_effect_adapters import FakeDeterministicProvider
        from tests.integration.test_postgresql_only_chapter_slice import PostgreSQLOnlyChapterSliceTests

        class ReviewOnlyFixture(DeterministicFixtureChapterProvider):
            stages = []

            def invoke(self, request, *, stage, payload, **kwargs):
                self.stages.append(stage)
                if stage == 'draft':
                    raise AssertionError('Human draft must not call a model')
                generated = super().invoke(request, stage=stage, payload=payload, **kwargs)
                from dataclasses import replace
                if stage == 'revision':
                    return replace(generated, output={"text": payload['draft']['text'],
                        "scene_artifacts": payload['draft']['scene_artifacts'], "resolved_issue_codes": []})
                if stage == 'rereview':
                    return replace(generated, output={**generated.output, "decision": payload['review']['decision'],
                        "issues": payload['review']['issues'], "resolved_issue_codes": [], "resolution_checks": []})
                return generated

        text = '剑已出鞘，林遥却在最后一步收住锋芒。她将归山的令牌压在桥头，任追兵踏碎。'
        saved = self.app.execute(action='save', payload={**self.payload, 'text': text,
                                 'scene_artifacts': [{'slot_id': 's1:skeleton', 'text': text, 'used_fact_ids': []}]},
                                 idempotency_key=identifier('save'), principal=self.principal)
        accepted = self.app.execute(action='accept', payload={**self.scope, 'expected_version': saved['version'],
                                   'candidate_asset_version_id': saved['candidate_asset_version_id'], 'rationale': '采用原创动作描写'},
                                   idempotency_key=identifier('accept'), principal=self.principal)
        frozen = freeze_author_adoption(DATABASE_URL, **{key: self.scope[key] for key in ('project_id','workspace_id','book_id','chapter')},
                                        candidate_asset_version_id=saved['candidate_asset_version_id'],
                                        decision_asset_version_id=accepted['decision_asset_version_id'], principal=self.principal)
        provider = ReviewOnlyFixture()
        request = SingleChapterRequest(**{key: self.scope[key] for key in ('project_id','workspace_id','book_id','chapter')},
                                       actor_id=self.principal.principal_id, title='关山旧约', premise='守住同伴的退路需要付出归山的代价。',
                                       trace_id=identifier('trace'), correlation_id=identifier('correlation'),
                                       application_build_id='author-native-fixture', commit_sha='e' * 40, context_token_budget=16_000,
                                       context_candidates=PostgreSQLOnlyChapterSliceTests.release_evidence(self.scope['project_id']),
                                       preparation_report={'author_draft_adoption': frozen})
        with self.assertRaisesRegex(KernelError, 'CHAPTER_QUALITY_GATE_BLOCKED'):
            run_single_chapter_slice(DATABASE_URL, request=request, registry=build_chapter_handler_registry(provider),
                                     object_store_adapter=FakeDeterministicProvider('success'))
        self.assertNotIn('draft', provider.stages)
        self.assertIn('review', provider.stages)
        self.assertTrue({'review', 'revision', 'rereview'}.issubset(provider.stages))
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            retained = {}
            for node in (ChapterNode.DRAFT, ChapterNode.REVISION, ChapterNode.REREVIEW):
                uow.cursor.execute('''SELECT output.operation_id,asset.content FROM authority_operation_output_asset output
                    JOIN authority_operation operation ON operation.operation_id=output.operation_id
                    JOIN authority_asset_version asset USING(asset_version_id)
                    WHERE operation.project_id=%s AND operation.command_payload->>'book_id'=%s
                      AND operation.command_payload->>'chapter_root_operation_id' IS NOT NULL
                      AND output.output_key=%s AND output.role='primary' ''',
                    [self.scope['project_id'], self.scope['book_id'], node.output_key])
                retained[node] = uow.cursor.fetchone()
                self.assertIsNotNone(retained[node])
            self.assertEqual(retained[ChapterNode.DRAFT][1]['text'], text)
            self.assertEqual(retained[ChapterNode.REVISION][1]['text'], text)
            self.assertEqual(retained[ChapterNode.REVISION][1]['resolved_issue_codes'], [])
            self.assertNotEqual(retained[ChapterNode.REREVIEW][1]['decision'], 'PASSED')
            self.assertTrue(retained[ChapterNode.REREVIEW][1]['issues'])
            uow.cursor.execute("SELECT COUNT(*) FROM authority_operation_output_asset WHERE operation_id=%s AND output_key='chapter.draft.author_adoption'",
                               [retained[ChapterNode.DRAFT][0]])
            self.assertEqual(uow.cursor.fetchone()[0], 1)
            uow.cursor.execute("SELECT COUNT(*) FROM authority_external_effect WHERE operation_id=%s AND capability='model.draft'",
                               [retained[ChapterNode.DRAFT][0]])
            self.assertEqual(uow.cursor.fetchone()[0], 0)

    def test_existing_same_project_other_book_and_superseded_base_are_rejected(self):
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute('SELECT operation_id FROM authority_operation_output_asset WHERE asset_version_id=%s', [self.source.asset_version_id])
            operation_id = uow.cursor.fetchone()[0]
            book_asset = uow.repositories.asset_documents.materialize_output(AuthorityAssetWriteCommand(
                operation_id=operation_id, project_id=self.scope['project_id'], asset_id=identifier('other-book-asset'),
                asset_type='book', schema_version='fixture-book.v1', logical_ref=identifier('other-book'), category='books',
                output_key='fixture.other_book', role='fixture', content={'title': '另一部小说'},
                qualification_policy='fixture-only', trace_id=identifier('trace'), correlation_id=identifier('correlation')))
            other_book = identifier('other-book')
            uow.cursor.execute('''INSERT INTO authority_book(book_id,project_id,workspace_id,principal_id,service_identity,
                book_scope,production_profile,runtime_policy,release_identity,status,current_book_asset_version_id,
                created_by_operation_id,last_operation_id)
                SELECT %s,project_id,workspace_id,principal_id,service_identity,book_scope,production_profile,runtime_policy,
                       release_identity,status,%s,created_by_operation_id,last_operation_id
                FROM authority_book WHERE book_id=%s''', [other_book, book_asset.asset_version_id, self.scope['book_id']])
            uow.commit()
        with self.assertRaises(KernelError) as caught:
            self.app.execute(action='save', payload={**self.payload, 'book_id': other_book}, idempotency_key=identifier('cross-book'), principal=self.principal)
        self.assertEqual(caught.exception.code, 'AUTHOR_BASE_SCOPE_CONFLICT')
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.repositories.asset_documents.materialize_output(AuthorityAssetWriteCommand(
                operation_id=operation_id, project_id=self.scope['project_id'], asset_id=self.source.asset_id,
                asset_type='draft_chapter', schema_version='fixture-author-prose.v1', logical_ref=self.source.logical_ref,
                category='drafts', output_key='fixture.new_version', role='fixture', content={**self.source.content, 'text': '更新后的原稿。'},
                qualification_policy='fixture-only', trace_id=identifier('trace'), correlation_id=identifier('correlation'),
                expected_current_asset_version_id=self.source.asset_version_id))
            uow.commit()
        with self.assertRaises(KernelError) as caught:
            self.app.execute(action='save', payload=self.payload, idempotency_key=identifier('stale-base'), principal=self.principal)
        self.assertEqual(caught.exception.code, 'AUTHOR_BASE_STALE')
