from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from novel_forge.modules.chapter_authority.provider_output_contracts import _validate

from novel_forge.modules.chapter_authority.character_references import compile_character_references
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.character_references import bind_character_schema, require_planning_character_references

MODULE = 'novel_forge.modules.story_planning_runtime.character_references'


def references():
    return compile_character_references(project_id='project', workspace_id='workspace', book_id='book', snapshot_id='snapshot',
        cast_version_id='cast-v2', cast_content_hash='hash', cast={'book_id': 'book', 'characters': [
            {'character_id': 'character:17', 'name': '甲', 'aliases': ['小甲']},
            {'character_id': 'character:18', 'name': '乙', 'aliases': []}]}, scenes=None)


@pytest.mark.parametrize('field', ['character_realization', 'character_participation', 'participants', 'pov_character_id'])
@pytest.mark.parametrize('token', ['character:17', 'character:character:17', 'character:role:invented', 'character:19', '甲'])
def test_schema_uses_exact_cast_locators_for_every_character_identity(field, token):
    schema = {'properties': {'character_realization': {'items': {'properties': {'character_id': {}}}},
        'character_participation': {'items': {'properties': {'character_id': {}}}},
        'scene_plan': {'items': {'properties': {'participants': {'items': {}}, 'pov_character_id': {}}}}}}
    bind_character_schema(schema, references())
    part = schema['properties'][field]['items']['properties']['character_id'] if field.startswith('character_') else schema['properties']['scene_plan']['items']['properties'][field]
    if field == 'participants':
        part = part['items']
    if token in {'character:17', 'character:character:17'}:
        _validate(part, token, path='$')
    else:
        with pytest.raises(ValueError):
            _validate(part, token, path='$')


def test_display_names_and_aliases_keep_their_compatibility_role():
    value = references()
    assert value['participant_bindings'] == {'character:character:17': 'character:17', 'character:character:18': 'character:18'}
    assert value['token_bindings']['小甲'] == 'character:17'
    assert value['cast_asset_version_id'] == 'cast-v2'
    assert value['input_snapshot_id'] == 'snapshot'


@pytest.mark.parametrize('rows', [[], [('snapshot',)], [('snapshot',), ('other',)]])
def test_native_book_root_is_scoped_and_unambiguous(rows):
    command = SimpleNamespace(project_id='project', workspace_id='workspace', book_id='book', correlation_id='root', world_preparation_request=None)
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.cursor.fetchall.return_value = rows
    with patch(MODULE+'.AuthorityUnitOfWork', return_value=uow), patch(MODULE+'.frozen_character_references', return_value=references()) as compile:
        if len(rows) > 1:
            with pytest.raises(KernelError):
                require_planning_character_references('db', command)
        else:
            value = require_planning_character_references('db', command)
            assert value is None if not rows else value['input_snapshot_id'] == 'snapshot'
        assert uow.cursor.execute.call_args.args[1] == ['project', 'workspace', 'book', 'root']
        if len(rows) == 1:
            assert compile.call_args.kwargs == {'scenes': None}
            assert compile.call_args.args[0].command['context_version_refs']['book_production_input_snapshot_id'] == 'snapshot'
        else:
            compile.assert_not_called()


def test_explicit_snapshot_uses_the_existing_book_cast_guard_without_new_selection():
    command = SimpleNamespace(project_id='project', workspace_id='workspace', book_id='book', world_preparation_request={'input_snapshot_id': 'frozen-snapshot'})
    with patch(MODULE+'.frozen_character_references', return_value=references()) as compile, patch(MODULE+'.AuthorityUnitOfWork', side_effect=AssertionError('no alternate snapshot lookup')):
        require_planning_character_references('db', command)
    assert compile.call_args.args[0].command == {'book_id': 'book', 'context_version_refs': {'book_production_input_snapshot_id': 'frozen-snapshot'}}


def test_legacy_schema_is_unchanged_without_a_native_book_binding():
    schema = {'properties': {'scene_plan': {'description': 'original'}}}
    before = deepcopy(schema)
    bind_character_schema(schema, None)
    assert schema == before
