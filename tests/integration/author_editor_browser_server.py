from __future__ import annotations

import os
from pathlib import Path
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from novel_forge.api.models import product_model_map
from novel_forge.api.routers.authority_projects import create_router as project_router
from novel_forge.api.routers.chapter_editor import create_router as editor_router
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.chapter_authority.queries import ChapterAuthorityQuery
from novel_forge.modules.project_authority import ProjectAuthorityQuery
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated
from tests.integration.conftest import preflight_integration_database
from tests.integration.test_author_editor_postgres import seed_editor_source


def create_app():
    if os.environ.get('NOVEL_FORGE_EDITOR_BROWSER_FIXTURE') != '1':
        raise RuntimeError('Explicit isolated editor browser fixture switch is required')
    preflight_integration_database(DATABASE_URL)
    ensure_migrated()
    scope, document = seed_editor_source()
    from tests.integration.test_chapter_authority_scheduler_postgres import ChapterAuthoritySchedulerPostgresTests
    from novel_forge.modules.chapter_authority.application import ChapterAuthorityApplication
    from novel_forge.modules.command_kernel.external_effect_adapters import FakeDeterministicProvider
    ChapterAuthoritySchedulerPostgresTests._preparation_assets(scope['project_id'])
    chapter = ChapterAuthorityApplication(DATABASE_URL, model_adapter=FakeDeterministicProvider('success'),
        object_store_adapter=FakeDeterministicProvider('success'), worker_id='author-browser-fixture')
    helper, followup, prose = seed_prose_browser()
    replacement_helper, replacement_fixture, replacement = seed_replacement_browser()
    evidence_dir = Path(os.environ['NOVEL_FORGE_EDITOR_BROWSER_EVIDENCE'])
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / 'fixture.json').write_text(json.dumps({'scope': scope, 'original': document.content,
                                                        'prose': prose, 'replacement': replacement, 'proof_ceiling': 'SCRIPTED_FIXTURE_API_AND_POSTGRESQL_BROWSER'}, ensure_ascii=False, indent=2))
    services = SimpleNamespace(project_authority_query=ProjectAuthorityQuery(DATABASE_URL),
                               chapter_query=ChapterAuthorityQuery(DATABASE_URL), chapter_application=chapter, book_production=SimpleNamespace(followup=followup, authority=replacement_fixture["authority"]))
    context = ProductRouterContext(app_settings=SimpleNamespace(database_url=DATABASE_URL), models=product_model_map(), services=services)
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=['http://127.0.0.1:58322'], allow_methods=['*'], allow_headers=['*'])
    app.include_router(project_router(context))
    app.include_router(editor_router(context))
    from novel_forge.api.routers.chapter_authority import create_router as chapter_router
    app.include_router(chapter_router(context))
    from novel_forge.api.routers.prose_review import create_router as prose_router
    app.include_router(prose_router(context))
    app.state.fixture_helper = (helper, replacement_helper)
    return app


def seed_prose_browser():
    from dataclasses import replace
    from tests.integration import test_book_to_chapter_authority_vertical_postgres as scripted_book
    from tests.integration.test_longform_prose_editorial_postgres import ProseFixturePort, metadata
    from novel_forge.modules.book_followup_authority.application import BookFollowupAuthorityApplication
    from novel_forge.modules.book_followup_authority.prose_coordinator import BookProseReviewCoordinator

    class FindingPort(ProseFixturePort):
        def invoke(self, request, **kwargs):
            result = super().invoke(request, **kwargs)
            source = request.require_input('longform_prose_review_window').content
            span = source['window']['spans'][0]
            output = {**result.output, 'findings': [{'lineage_id': 'browser-cost-evidence', 'dimension': 'motivation_cost',
                'judgment': 'INSUFFICIENT_EVIDENCE', 'severity': 'NONE', 'confidence': 0.5,
                'claim': '局部正文尚不能确认代价是否在后文持续发生。', 'rationale': '需要后续章节原文，保留当前稿。',
                'evidence': [{'asset_version_id': span['asset_version_id'], 'text_hash': span['text_hash'],
                              'start': span['start'], 'end': span['start'] + 2, 'quote': span['text'][:2]}]}]}
            return replace(result, output=output)

    helper = scripted_book.BookToChapterAuthorityVerticalPostgresTests()
    fixture = helper._new_book_fixture(target_chapter_count=1)
    delegated = fixture['authority'].submit_chapter(helper._chapter_command(fixture, chapter_number=1), principal=fixture['principal'])
    helper._run_child(fixture, delegated['chapter_root_operation_id'])
    fixture['authority'].reconcile_chapter(delegated['chapter_request_id'])
    fixture['authority'].accept_chapter(delegated['chapter_request_id'], principal=fixture['principal'])
    principal = replace(fixture['principal'], authentication_source='server_configuration', permissions=frozenset({'book.authority.execute','book.authority.query','book.followup:*'}))
    followup = BookFollowupAuthorityApplication(DATABASE_URL, application_build_id='browser-fixture', commit_sha='e' * 40, prose_model_port=FindingPort())
    coordinator = BookProseReviewCoordinator(followup)
    scope = dict(project_id=fixture['project_id'], workspace_id='workspace:' + fixture['project_id'], book_run_id=fixture['book'].book_run_id, principal=principal)
    run = coordinator.start(**scope, **metadata('browser-prose'), policy={'policy_version':'v1','window_codepoints':512,'overlap_codepoints':32,'context_token_budget':4000,'maximum_windows':20})
    report = coordinator.report(**scope, run_id=run['run_id'])
    while not report['review_complete']:
        report = coordinator.advance(**scope, run_id=run['run_id'], expected_version=report['expected_version'], **metadata('browser-prose-advance'))
    return helper, followup, {'project_id': fixture['project_id'], 'book_run_id': fixture['book'].book_run_id, 'run_id': run['run_id']}


def seed_replacement_browser():
    from tests.integration import test_book_to_chapter_authority_vertical_postgres as native
    helper = native.BookToChapterAuthorityVerticalPostgresTests()
    fixture = helper._new_book_fixture(target_chapter_count=1)
    delegated = fixture['authority'].submit_chapter(helper._chapter_command(fixture, chapter_number=1), principal=fixture['principal'])
    helper._run_child(fixture, delegated['chapter_root_operation_id'])
    fixture['authority'].reconcile_chapter(delegated['chapter_request_id'])
    outputs = fixture['chapter'].query.require_acceptance_evidence(project_id=fixture['project_id'],root_operation_id=delegated['chapter_root_operation_id'])['outputs']
    draft = next(item for item in outputs if item['asset_type']=='draft_chapter')
    other = next(item for item in outputs if item['asset_type'] in {'draft_version','best_draft_candidate'} and item['content'].get('text'))
    return helper, fixture, {'project_id':fixture['project_id'],'book_run_id':fixture['book'].book_run_id,
        'chapter_request_id':delegated['chapter_request_id'],'root_operation_id':delegated['chapter_root_operation_id'],
        'base_asset_version_id':draft['asset_version_id'],'source_text':draft['content']['text'],
        'other_base_asset_version_id':other['asset_version_id'],'other_source_text':other['content']['text']}
