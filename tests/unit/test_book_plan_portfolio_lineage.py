from copy import deepcopy

import pytest

from novel_forge.modules.book_authority.input_resolver import project_current_plan_cursor
from novel_forge.modules.book_authority.plan_portfolio import resolve_portfolio_lineage
from novel_forge.modules.command_kernel.errors import KernelError


def test_portfolio_replacement_chain_and_restart_are_deterministic():
    frozen = ('volume:original', 'volume:two', 'arc:original')
    replacements = [('volume:original', 'volume:next'), ('volume:next', 'volume:current')]
    expected = {'volume:original': 'volume:current', 'volume:two': 'volume:two', 'arc:original': 'arc:original'}
    assert resolve_portfolio_lineage(frozen, replacements) == expected
    assert resolve_portfolio_lineage(frozen, reversed(replacements)) == expected
    assert frozen == ('volume:original', 'volume:two', 'arc:original')


@pytest.mark.parametrize('replacements', [
    [('a', 'b'), ('b', 'a')],
    [('a', 'a')],
    [('a', 'b'), ('a', 'c')],
    [('a', 'c'), ('b', 'c')],
])
def test_ambiguous_cyclic_or_collapsed_portfolio_is_blocked(replacements):
    with pytest.raises(KernelError, match='BOOK_INPUT_PORTFOLIO_STALE'):
        resolve_portfolio_lineage(('a', 'b'), replacements)


def test_arc_scope_projects_through_proven_volume_lineage_without_rewriting_arc():
    volumes = [
        {'asset_version_id': 'volume:new', 'content': {'chapter_range': [1, 48]}},
        {'asset_version_id': 'volume:two', 'content': {'chapter_range': [49, 96]}},
    ]
    arcs = [{'asset_version_id': 'arc:one', 'content': {'cross_volume_scope': ['volume:old', 'volume:two']}}]
    original = deepcopy(arcs)
    with pytest.raises(KernelError, match='BOOK_PRODUCTION_ARC_VOLUME_INVALID'):
        project_current_plan_cursor(volumes=volumes, arcs=arcs, chapter_cursor=12)
    volume, relevant = project_current_plan_cursor(
        volumes=volumes, arcs=arcs, chapter_cursor=12,
        volume_version_lineage={'volume:old': 'volume:new'},
    )
    assert volume['asset_version_id'] == 'volume:new'
    assert relevant == ('arc:one',)
    assert arcs == original
