from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.source_authority import corpus_consumption
from novel_forge.modules.source_authority.corpus import CorpusUse


@pytest.fixture
def consumed(monkeypatch):
    calls = []
    repository = SimpleNamespace(require_corpus_execution_assets=lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(corpus_consumption, 'AuthorityUnitOfWork', lambda _: nullcontext(SimpleNamespace(cursor=object())))
    monkeypatch.setattr(corpus_consumption, 'SourceAuthorityRepository', lambda _: repository)
    return calls


@pytest.mark.parametrize('shape', ['wide', 'deep', 'shared'])
def test_complete_finite_input_keeps_all_source_identities(consumed, shape):
    tail = {'source_document_id':'tail', 'knowledge_pack_id':'knowledge'}
    if shape == 'wide':
        nested = [{}, *[{} for _ in range(55000)], tail]
    elif shape == 'deep':
        nested = tail
        for _ in range(80):
            nested = {'evidence':nested}
    else:
        nested = [tail] * 55000
    payload = {'asset_version_id':'original', 'receipt_evidence':nested,
               'asset_version_ids':['other', 'original', {'asset_version_id':'nested-source'}]}
    corpus_consumption.require_corpus_consumption('db','project',payload,source_analysis=False)
    assert consumed == [(('project',('knowledge','nested-source','original','other','tail'),CorpusUse.ABSTRACT_GENERATION), {'observation':None})]


@pytest.mark.parametrize('shape', ['mapping', 'list', 'identity-list'])
def test_cyclic_input_refuses_before_any_source_authorization(consumed, shape):
    payload = {'asset_version_id':'original'}
    if shape == 'mapping':
        payload['loop'] = payload
    elif shape == 'list':
        child = []
        child.append(child)
        payload['loop'] = child
    else:
        payload['asset_version_ids'] = [payload]
    with pytest.raises(KernelError, match='CORPUS_CONSUMPTION_INPUT_CYCLE'):
        corpus_consumption.require_corpus_consumption('db','project',payload,source_analysis=False)
    assert consumed == []
