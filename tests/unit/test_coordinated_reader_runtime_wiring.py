from pathlib import Path
from unittest.mock import patch

import pytest

from novel_forge.api import authority_dependencies as dependencies
from novel_forge.infrastructure.settings import IndustrialSettings


@pytest.mark.parametrize('environment,contract,enabled', [
    ('production', 'reader-accepted-context.v3', True),
    ('validation', 'reader-accepted-context.v3', True),
    ('production', '', False),
    ('production', 'reader-accepted-context.v2', False),
    ('development', 'reader-accepted-context.v3', False),
])
def test_native_followup_uses_explicit_current_contract_without_relabeling_runtime(environment, contract, enabled):
    settings = IndustrialSettings(root=Path('.'), environment=environment, database_url='postgresql://unused')
    env = {'NOVEL_FORGE_COORDINATED_READER_CONTRACT': contract,
           'NOVEL_FORGE_APPLICATION_BUILD_ID': 'current-owner-wiring',
           'NOVEL_FORGE_COMMIT_SHA': 'a' * 40}
    with patch.object(dependencies, 'BookFollowupAuthorityApplication') as owner, \
         patch.object(dependencies, 'build_reader_outcome_model_port'), \
         patch.object(dependencies, 'build_longform_prose_review_model_port'), \
         patch('novel_forge.modules.book_followup_authority.screenplay_execution.build_screenplay_model_ports'):
        dependencies.build_book_followup_authority_application(settings, execution=object(), env=env)
    assert owner.call_args.kwargs['coordinated_reader'] is enabled
    assert str(settings.environment) == environment
