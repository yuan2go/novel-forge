from copy import deepcopy

import pytest

from novel_forge.modules.book_design_authority.foundation import FoundationRole
from novel_forge.modules.chapter_quality_authority.foundation_context import frozen_world_evidence
from novel_forge.modules.command_kernel.errors import KernelError
from tests.unit.test_foundation_hierarchy import _foundation_set


class Cursor:
    def __init__(self, rows):
        self.rows = iter(rows)
        self.queries = []

    def execute(self, query, parameters):
        self.queries.append((query, parameters))

    def fetchone(self):
        return next(self.rows)


def evidence(mutation=None):
    foundation = _foundation_set()
    world = foundation.by_role[FoundationRole.WORLD_BIBLE]
    approval = {
        'project_id': 'project', 'design_scope': 'WORLD_BIBLE', 'transition': 'APPROVE',
        'asset_version_id': world.asset_version_id, 'target_content_hash': world.content_hash,
    }
    qualification = {
        'schema_version': 'narrative-design-evaluation.v1', 'project_id': 'project',
        'candidate_asset_version_id': world.asset_version_id,
        'candidate_content_hash': world.content_hash, 'qualification': {'status': 'PASS'},
    }
    approved = ('approval:v1', 'sha256:approval', approval)
    if mutation == 'missing-native-proof':
        approved = None
    elif mutation == 'foreign-world':
        approval['asset_version_id'] = 'other:world'
    elif mutation == 'foreign-book':
        approval['target_content_hash'] = 'sha256:foreign'
    elif mutation == 'advisory-fail':
        qualification['qualification']['status'] = 'FAIL'
    elif mutation == 'cross-project':
        qualification['project_id'] = 'other:project'
    rows = [
        ('book', 'design:v1'), ('sha256:design', {'foundation_set': foundation.to_dict()}),
        (world.content_hash, {'book_id': 'book', 'rules': []}),
        (world.qualification_hash, qualification), approved,
    ]
    return Cursor(deepcopy(rows)), world


def test_independent_world_qualification_freezes_exact_native_approval_input():
    cursor, world = evidence()
    result = frozen_world_evidence(cursor, project_id='project', root_operation_id='root')
    assert [item['asset_version_id'] for item in result['inputs']] == [
        'design:v1', world.asset_version_id, world.qualification_evidence_asset_version_id, 'approval:v1',
    ]
    query, parameters = cursor.queries[-1]
    assert "q.trust_boundary='INDEPENDENT'" in query
    assert "activated.transition_type='ACTIVATE'" in query
    assert parameters == [
        'project', world.asset_version_id, world.activation_id, 'book',
        world.content_hash, world.qualification_evidence_asset_version_id,
    ]


@pytest.mark.parametrize('mutation', [
    'missing-native-proof', 'foreign-world', 'foreign-book', 'advisory-fail', 'cross-project',
])
def test_independent_qualification_cannot_replace_native_world_binding(mutation):
    cursor, _ = evidence(mutation)
    with pytest.raises(KernelError, match='QUALITY_FOUNDATION_SCOPE_INVALID'):
        frozen_world_evidence(cursor, project_id='project', root_operation_id='root')
