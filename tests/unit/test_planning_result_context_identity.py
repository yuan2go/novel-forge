from types import SimpleNamespace

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime import application, result_recovery


def retained_primary_source(monkeypatch, *, damage=None, role_downgrade=False):
    raw = {"objective": ""}
    error = KernelError("PLANNING_RESULT_OBJECTIVE_INVALID", "$.objective: empty")
    evidence = {"external_receipt_ref": "effect:primary", "context_bundle_asset_version_id": "context:primary",
        "context_bundle_hash": "hash:primary"}
    diagnostic = result_recovery.PlanningResultValidationError(error, raw_result=raw, execution_evidence=evidence).diagnostic
    source = SimpleNamespace(asset_type=result_recovery.RESULT_FAILURE_TYPE, asset_version_id="failure:primary", content_hash="hash:failure",
        content={"raw_result": raw, "execution_evidence": evidence, "diagnostic": diagnostic})
    contexts = [("context:world-generation", "hash:world-generation", {"stage": "world_candidates.generate"}),
        ("context:world-evaluation", "hash:world-evaluation", {"stage": "world_candidates.evaluate"}),
        ("context:primary", "hash:primary", {"stage": "chapter_plan.generate"})]
    if role_downgrade:
        from tests.unit.test_knowledge_translation import _case
        selection, raw = _case()
        selection['selection_digest'] = 'selection:exact'
        selection['candidate_review'] = {'contract_version': 'explicit-allowlist-craft-review.v1'}
        selection['selected'][0]['applicability_assessment']['usage_role'] = 'MECHANISM'
        raw['knowledge_translations'][0]['usage_role'] = 'REVIEW_CHECK'
        source = SimpleNamespace(asset_type='model_call_log', asset_version_id='log:primary', content_hash='hash:log',
            content={'result': raw, 'external_effect_id': 'effect:primary', 'production_execution': {}})
        contexts = [('context:primary', 'hash:primary', {'stage': 'creative.candidates.generate', 'narrative_intelligence': selection})]
        if role_downgrade == 'legacy-missing-digest':
            selection.pop('candidate_review')
            diagnostic = {'error_code': 'PLANNING_KNOWLEDGE_ROLE_DOWNGRADE'}
            source = SimpleNamespace(asset_type=result_recovery.RESULT_FAILURE_TYPE, asset_version_id='failure:primary', content_hash='hash:failure',
                content={'raw_result': raw, 'execution_evidence': evidence, 'diagnostic': diagnostic})
    if damage == "cross-stage-substitution":
        contexts[-1] = contexts[0]
    elif damage == "hash-drift":
        contexts[-1] = (contexts[-1][0], "hash:changed", contexts[-1][2])
    frozen = {"project_id": "project", "workspace_id": "workspace", "book_id": "book"}

    class Cursor:
        def execute(self, query, args):
            assert args[0] == "operation:primary"
            if query.startswith("SELECT op.status"):
                self.rows = [("FAILED_FINAL", "project", "workspace", "book", frozen, None)]
            elif query.startswith("SELECT 1 FROM authority_external_effect"):
                self.rows = []
            elif "asset.asset_type='context_bundle'" in query:
                self.rows = contexts
            else:
                self.rows = [(source.asset_version_id,)]

        def fetchone(self):
            return self.rows[0] if self.rows else None

        def fetchall(self):
            return self.rows

    class Uow:
        def __init__(self, database_url):
            assert database_url == "postgresql://unused"
            self.cursor = Cursor()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(result_recovery, "AuthorityUnitOfWork", Uow)
    monkeypatch.setattr(application, "_command_payload", lambda command: frozen)
    def require_source(**kwargs):
        if role_downgrade and kwargs['asset_version_id'] == 'context:primary':
            return SimpleNamespace(content_hash='hash:primary', content=contexts[0][2])
        return source
    monkeypatch.setattr(result_recovery, "AuthorityAssetQuery", lambda *args: SimpleNamespace(require=require_source))
    monkeypatch.setattr(result_recovery, "read_failed_operation_success", lambda *args, **kwargs: {
        "provider_evidence": {"result": raw}, "budget_reservation_status": "SETTLED"})

    def reject_raw(*args, **kwargs):
        if role_downgrade:
            return raw
        if damage:
            pytest.fail("Context drift must fail before any raw-result revalidation")
        raise error

    monkeypatch.setattr(result_recovery, "validate_raw_result", reject_raw)
    command = SimpleNamespace(project_id="project", workspace_id="workspace", book_id="book", actor_id="author",
        trace_id="trace", correlation_id="correlation", generator_operation_name="chapter_plan.generate", execution_contract_version="1.19.0", narrative_search_id="")
    return command


def test_retained_opt_in_model_log_rechecks_exact_knowledge_before_result_repair(monkeypatch):
    command = retained_primary_source(monkeypatch, role_downgrade=True)
    command.generator_operation_name = 'creative.candidates.generate'
    retained = result_recovery.require_result_repair_source('postgresql://unused', command=command,
        operation_id='operation:primary', source_asset_version_id='log:primary')
    assert retained['diagnostic']['error_code'] == 'PLANNING_KNOWLEDGE_ROLE_DOWNGRADE'
    assert retained['context_asset_version_id'] == 'context:primary'
    assert retained['raw_result']['knowledge_translations'][0]['usage_role'] == 'REVIEW_CHECK'


def test_legacy_typed_knowledge_failure_still_requires_exact_selection_digest(monkeypatch):
    command = retained_primary_source(monkeypatch, role_downgrade='legacy-missing-digest')
    with pytest.raises(KernelError, match='PLANNING_RESULT_REPAIR_DIAGNOSTIC_DRIFT'):
        result_recovery.require_result_repair_source('postgresql://unused', command=command,
            operation_id='operation:primary', source_asset_version_id='failure:primary')


def test_primary_failure_selects_exact_frozen_context_among_three_stages(monkeypatch):
    command = retained_primary_source(monkeypatch)
    retained = result_recovery.require_result_repair_source("postgresql://unused", command=command,
        operation_id="operation:primary", source_asset_version_id="failure:primary")
    assert retained["context_asset_version_id"] == "context:primary"
    assert retained["context_hash"] == "hash:primary"
    assert retained["context_content"] == {"stage": "chapter_plan.generate"}


@pytest.mark.parametrize("damage", ["cross-stage-substitution", "hash-drift"])
def test_primary_failure_rejects_other_stage_context_or_changed_frozen_hash(monkeypatch, damage):
    command = retained_primary_source(monkeypatch, damage=damage)
    with pytest.raises(KernelError, match="PLANNING_RESULT_REPAIR_CONTEXT_DRIFT"):
        result_recovery.require_result_repair_source("postgresql://unused", command=command,
            operation_id="operation:primary", source_asset_version_id="failure:primary")
