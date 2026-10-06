from __future__ import annotations

from copy import deepcopy
import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.review.quality_namespace import separate_quality_checks


def evidence():
    return ({'issues': [], 'unresolved_issues': []}, {
        'text': '保留事实。',
        'quality_edit_contract': {'contract_version': 'quality-targeted-repair.v2',
            'permitted_ranges': [{'code': 'quality:range', 'observation': 'economy'}]},
    }, {'resolution_checks': [{'code': 'quality:range', 'status': 'SATISFIED',
        'preservation': 'PRESERVED', 'reason': 'literal repaired prose', 'evidence': {'quote': '保留事实'}}],
        'quality_resolution_checks': [{'observation': 'economy', 'status': 'SATISFIED',
            'preservation': 'PRESERVED'}]})


def test_only_exact_quality_namespace_is_reclassified_and_original_is_immutable():
    review, revision, result = evidence()
    frozen = deepcopy(result)
    actual = separate_quality_checks(result, review, revision)
    assert result == frozen
    assert actual['resolution_checks'] == []
    assert actual['quality_resolution_checks'] == result['quality_resolution_checks']
    assert actual['quality_range_reassessment']['checks'] == result['resolution_checks']


@pytest.mark.parametrize('fault', ['unknown', 'duplicate', 'conflicting', 'invalid_quote', 'missing_observation'])
def test_unrelated_or_conflicting_checks_are_never_discarded(fault):
    review, revision, result = evidence()
    check = result['resolution_checks'][0]
    if fault == 'unknown':
        check['code'] = 'not-a-frozen-code'
    elif fault == 'duplicate':
        result['resolution_checks'].append(deepcopy(check))
    elif fault == 'conflicting':
        check['status'] = 'UNRESOLVED'
    elif fault == 'invalid_quote':
        check['evidence']['quote'] = '不存在'
    else:
        result['quality_resolution_checks'] = []
    with pytest.raises(KernelError):
        separate_quality_checks(result, review, revision)


def test_historical_and_strict_interpretation_is_preserved():
    review, revision, result = evidence()
    revision['quality_edit_contract']['contract_version'] = 'quality-targeted-repair.v1'
    assert separate_quality_checks(result, review, revision) is result


def test_actual_unresolved_independent_quality_is_not_promoted_to_pass():
    review, revision, result = evidence()
    result['resolution_checks'][0]['status'] = 'UNRESOLVED'
    result['quality_resolution_checks'][0]['status'] = 'UNRESOLVED'
    actual = separate_quality_checks(result, review, revision)
    assert actual['quality_resolution_checks'][0]['status'] == 'UNRESOLVED'


@pytest.mark.parametrize('name,version', [('chapter.review.evaluate','3.9.19'), ('chapter.revision.review','3.9.19'), ('chapter.revision.apply','3.9.16')])
def test_gateway_admits_only_the_explicit_executable_successor_versions(name, version):
    from unittest.mock import MagicMock, patch
    from novel_forge.modules.chapter_authority.execution_gateway import PostgresChapterExecutionContractBinder
    binder = object.__new__(PostgresChapterExecutionContractBinder)
    object.__setattr__(binder, 'database_url', 'controlled-test')
    runtime = MagicMock()
    runtime.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value.fetchone.return_value = (name,version,'root','saga')
    with patch('novel_forge.modules.chapter_authority.execution_gateway.get_database_runtime', return_value=runtime):
        assert binder._operation_graph('operation','project')['definition_version'] == version


def test_retained_independent_review_is_a_fenced_pure_derivation_with_the_original_scope():
    from novel_forge.modules.chapter_authority.definitions import retained_rereview_definition
    d = retained_rereview_definition(application_build_id='test', commit_sha='a'*40)
    assert d['definition_version'] == '3.9.20'
    assert d['external_capabilities'] == []
    assert 'required_external_effects' not in d['completion_contract']
    assert d['policy']['review_knowledge_scope'] == 'delivered-card-scope.v1'
    assert d['policy']['retained_result_contract'] == 'chapter-quality-review-revalidation.v1'


@pytest.mark.parametrize('open_codes', [[], ['original']])
def test_rendered_schema_binds_only_original_codes_without_aliasing_reason(open_codes):
    from novel_forge.modules.chapter_authority.execution_gateway import PostgresChapterExecutionContractBinder
    from novel_forge.modules.chapter_authority.provider_output_contracts import validate_chapter_provider_output_against_schema
    schema, _ = PostgresChapterExecutionContractBinder._provider_output_contract(
        stage='rereview', prompt_contract_version='v11', request_payload={'input': {
            'review_resolution_namespace': 'quality-review-namespaces.v1',
            'review': {'issues': [{'code': code, 'severity': 'major'} for code in open_codes]},
        }})
    checks = [{'code': code, 'status': 'SATISFIED', 'preservation': 'PRESERVED',
        'reason': 'A prose explanation, never an issue identifier.', 'evidence': {'quote': 'literal prose'}} for code in open_codes]
    raw = {'score': 90, 'issues': [], 'knowledge_checks': [], 'resolution_checks': checks}
    assert validate_chapter_provider_output_against_schema('rereview', schema, raw) == raw
    raw['resolution_checks'] = [dict(checks[0], code='quality:range')] if checks else [{'code': 'extra'}]
    with pytest.raises(KernelError):
        validate_chapter_provider_output_against_schema('rereview', schema, raw)
