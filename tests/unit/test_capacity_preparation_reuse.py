from copy import deepcopy

import pytest

from novel_forge.modules.chapter_authority.capacity_reuse import CONTRACT, reusable_preparation
from novel_forge.modules.story_planning_runtime.domain import canonical_hash


def prepared():
    original = {'input_manifest': {'goal': 'Preserve the actual prior event.'}}
    boundary = {'pack_snapshot_hash': 'pack:snapshot', 'sources': [{'asset_version_id': 'context', 'content_hash': 'hash'}]}
    route = {'provider': 'configured', 'model': 'authorized', 'capacity': 475000}
    projection = {'original_hash': canonical_hash(original), 'source_boundary': boundary, 'replacements': []}
    proof = {'contract_version': CONTRACT, 'projection_hash': canonical_hash(projection),
        'pack_snapshot_hash': 'pack:snapshot', 'prepared_route': route}
    return original, boundary, route, projection, proof


def test_admitted_preparation_is_reused_only_with_current_complete_request_capacity():
    original, boundary, route, projection, proof = prepared()
    kwargs = dict(source_boundary=boundary, original=original, route_contract=route)
    assert reusable_preparation(projection, proof, **kwargs, measure=lambda _: (475000, 475000))
    assert not reusable_preparation(projection, proof, **kwargs, measure=lambda _: (475001, 475000))
    assert proof['projection_hash'] == canonical_hash(projection)


@pytest.mark.parametrize('change', ['source', 'pack', 'task', 'route', 'algorithm', 'projection'])
def test_preparation_binding_changes_invalidate_before_capacity_probe(change):
    original, boundary, route, projection, proof = deepcopy(prepared())
    if change == 'source':
        boundary['sources'][0]['content_hash'] = 'new-source'
    if change == 'pack':
        proof['pack_snapshot_hash'] = 'new-pack'
    if change == 'task':
        original['input_manifest']['goal'] = 'Changed task'
    if change == 'route':
        route = {**route, 'model': 'different-model'}
    if change == 'algorithm':
        proof['contract_version'] = 'unsupported-method'
    if change == 'projection':
        projection['replacements'].append({'unverified': True})
    assert not reusable_preparation(projection, proof, source_boundary=boundary, original=original,
        route_contract=route, measure=lambda _: pytest.fail('Changed frozen inputs must invalidate before measurement'))
