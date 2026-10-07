from copy import deepcopy
from types import SimpleNamespace

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.runtime_continuation import (
    require_source,
    _world_agency_pack_profile,
)


def test_agency_pack_successor_changes_only_contract_identity_and_keeps_frozen_catalog():
    version = {
        "manifest": {
            "identity": {"pack_id": "planning", "version": "1.1.0"},
            "workflow_template": {
                "workflow_id": "planning",
                "workflow_version": "1.12.0",
                "nodes": [
                    {
                        "node_id": "chapter_plan.generate",
                        "operation_definition_ref": "story_planning.generate@1.18.0",
                        "operation_definition_hash": "old",
                        "policy": {"no_paid_switch": True},
                    },
                ],
            },
            "skill_binding": {"skills": [{"skill_ref": "long-outline"}]},
            "prompt_binding": {"hash": "frozen"},
        },
        "artifact_catalog": {
            "artifacts": [{"ref": "frozen", "content": {"text": "author intent"}}]
        },
    }
    frozen = deepcopy(version)
    profile, generation = _world_agency_pack_profile(version, "new")
    assert version == frozen and generation == 1
    expected = deepcopy(frozen["manifest"])
    expected["identity"]["version"] = "1.2.0"
    expected["workflow_template"]["nodes"][0].update(
        operation_definition_ref="story_planning.generate@1.19.0",
        operation_definition_hash="new",
    )
    assert profile.manifest == expected
    assert profile.artifact_catalog == frozen["artifact_catalog"]
    version["manifest"]["workflow_template"]["nodes"][0]["operation_definition_ref"] = (
        "chapter.generate@1.18.0"
    )
    with pytest.raises(KernelError, match="PLANNING_WORLD_CONTRACT_PACK_INVALID"):
        _world_agency_pack_profile(version, "new")


def source_uow(
    *,
    status="CANCELLED",
    candidate=None,
    command=None,
    error="EXECUTION_CONTRACT_FROZEN_CONFLICT",
    effects=None,
    reservations=None,
    dispatch_count=0,
    depth=0,
):
    frozen = {
        "project_id": "project",
        "workspace_id": "workspace",
        "book_id": "book",
        **(command or {}),
    }
    if depth:
        frozen["runtime_continuation_id"] = "prior"
    request = {
        "_production_execution": {
            "capability_runtime": {
                "provider_admission_asset_version_id": "admission",
                "provider_admission_content_hash": "hash",
            }
        }
    }
    responses = [
        (status, 8, "workspace", frozen, "book", candidate),
        ("FAILED_RETRYABLE", {"error_code": error}, {}),
        effects
        if effects is not None
        else [
            ("effect", "CANCELLED", "production_execution_gateway", "model", request)
        ],
        (dispatch_count,),
        reservations if reservations is not None else [("RELEASED",)],
        ({"release_sha": "e" * 40, "route_policy_hash": "route"},),
        (
            "hash",
            "provider_request_admission_manifest",
            {
                "contract": {
                    "provider_request_identity": {
                        "provider": "provider",
                        "model": "model",
                    }
                }
            },
        ),
        (depth,),
    ]

    class Cursor:
        def execute(self, statement, values):
            self.result = responses.pop(0)

        def fetchone(self):
            return self.result

        def fetchall(self):
            return self.result

    return SimpleNamespace(cursor=Cursor())


@pytest.mark.parametrize(
    "change,code",
    [
        ({"status": "FAILED_RETRYABLE"}, "SOURCE_INVALID"),
        ({"candidate": "candidate"}, "SOURCE_INVALID"),
        ({"command": {"book_id": "other-book"}}, "SCOPE_INVALID"),
        ({"command": {"workspace_id": "other-workspace"}}, "SCOPE_INVALID"),
        ({"error": "PROGRAMMING_BUG"}, "FAILURE_NOT_ALLOWED"),
        ({"dispatch_count": 1}, "DISPATCH_UNSAFE"),
        ({"reservations": []}, "DISPATCH_UNSAFE"),
        ({"reservations": [("RESERVED",)]}, "DISPATCH_UNSAFE"),
        ({"reservations": [("HELD_UNKNOWN",)]}, "DISPATCH_UNSAFE"),
        ({"reservations": [("RELEASED",), ("SETTLED",)]}, "DISPATCH_UNSAFE"),
        ({"effects": []}, "DISPATCH_UNSAFE"),
        (
            {"effects": [("effect", "UNKNOWN", "gateway", "model", {})]},
            "DISPATCH_UNSAFE",
        ),
        (
            {
                "effects": [
                    ("effect", "CANCELLED", "gateway", "model", {}),
                    ("other", "READY", "gateway", "model", {}),
                ]
            },
            "DISPATCH_UNSAFE",
        ),
        (
            {
                "effects": [
                    ("effect", "CANCELLED", "gateway", "model", {}),
                    ("other", "CANCELLED", "gateway", "model", {}),
                ]
            },
            "EFFECT_SCOPE_INVALID",
        ),
        ({"depth": 2}, "BOUND_EXCEEDED"),
    ],
)
def test_runtime_continuation_rejects_unsafe_or_unrelated_source(change, code):
    with pytest.raises(KernelError, match=f"PLANNING_RUNTIME_CONTINUATION_{code}"):
        require_source(
            source_uow(**change), source_operation_id="source", project_id="project"
        )


def test_runtime_continuation_uses_admission_provider_not_gateway_alias():
    source = require_source(
        source_uow(depth=1), source_operation_id="source", project_id="project"
    )
    assert source["provider"] == "provider"
    assert source["model_id"] == "model"
    assert source["depth"] == 2


@pytest.mark.parametrize(
    "statuses,reservations,dispatch_count,owner_status,code",
    [
        (
            ["READY"],
            ["RESERVED"],
            0,
            "CANCELLATION_REQUESTED",
            "NOT_DISPATCHED_PROOF_REQUIRED",
        ),
        (
            ["READY"],
            ["HELD_UNKNOWN"],
            0,
            "CANCELLATION_REQUESTED",
            "NOT_DISPATCHED_PROOF_REQUIRED",
        ),
        (
            ["READY"],
            ["RELEASED"],
            1,
            "CANCELLATION_REQUESTED",
            "NOT_DISPATCHED_PROOF_REQUIRED",
        ),
        (
            ["READY", "UNKNOWN"],
            ["RELEASED"],
            0,
            "CANCELLATION_REQUESTED",
            "NOT_DISPATCHED_PROOF_REQUIRED",
        ),
        (["READY"], ["RELEASED"], 0, "CANCELLED", "TERMINAL_EFFECT_CONFLICT"),
    ],
)
def test_cancel_never_dispatched_refuses_incomplete_proof_without_mutation(
    monkeypatch, statuses, reservations, dispatch_count, owner_status, code
):
    import novel_forge.modules.command_kernel.cancellation as cancellation

    results = [
        (owner_status, 8),
        [(f"effect-{i}", value) for i, value in enumerate(statuses)],
        (dispatch_count,),
        [(value,) for value in reservations],
    ]
    writes = []

    class Uow:
        cursor = None

        def __init__(self, database_url):
            self.cursor = self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, statement, args):
            assert statement.lstrip().startswith("SELECT")
            self.result = results.pop(0)

        def fetchone(self):
            return self.result

        def fetchall(self):
            return self.result

        def commit(self):
            writes.append("commit")

    monkeypatch.setattr(cancellation, "AuthorityUnitOfWork", Uow)
    with pytest.raises(KernelError, match=f"CANCELLATION_{code}"):
        cancellation.resolve_cancellation(
            "fixture-only",
            operation_id="source",
            project_id="project",
            expected_version=8,
            resolution="never_dispatched_effects",
            actor_id="operator",
            reason="test",
            trace_id="trace",
            correlation_id="correlation",
        )
    assert not writes


def test_model_profile_exact_legacy_stays_immutable_and_new_identities_do_not_race():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from novel_forge.modules.story_planning_runtime.execution import (
        PostgresPlanningExecutionPreparer,
    )
    from novel_forge.modules.production_execution import ExecutionRuntimeClass
    from tests.unit.test_production_execution_gateway import contracts
    from dataclasses import replace

    _, profile, _, _, _, _ = contracts(
        backend_id="codex-profile-test",
        runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
    )
    preparer = object.__new__(PostgresPlanningExecutionPreparer)
    legacy = SimpleNamespace(
        asset_type="model_profile", content={"contract": profile.to_dict()}
    )
    before = deepcopy(legacy.content)
    preparer.query = SimpleNamespace(require=lambda **kwargs: legacy)
    assert preparer._select_model_profile("project", profile) == profile
    assert legacy.content == before
    barrier = Barrier(2)

    def missing(**kwargs):
        barrier.wait(timeout=5)
        raise KernelError("AUTHORITY_ASSET_NOT_FOUND", "no legacy contracts exist")

    preparer.query = SimpleNamespace(require=missing)
    with ThreadPoolExecutor(max_workers=2) as pool:
        selected = list(
            pool.map(
                lambda value: preparer._select_model_profile(
                    "project", replace(profile, output_policy_ref=value)
                ),
                ["schema:first", "schema:second"],
            )
        )
    assert len({item.profile_id for item in selected}) == 2
    assert all(".sha256." in item.profile_id for item in selected)


@pytest.mark.parametrize("same", [True, False])
def test_profile_contract_creation_race_reuses_only_exact_winner(same):
    from novel_forge.modules.story_planning_runtime.execution import (
        PostgresPlanningExecutionPreparer,
    )

    contract = {"field": "value"}
    winner = SimpleNamespace(
        asset_type="model_profile",
        content={"contract": contract if same else {"field": "changed"}},
    )
    lookups = iter([None, winner])

    def lookup(**kwargs):
        value = next(lookups)
        if value is None:
            raise KernelError(
                "AUTHORITY_ASSET_NOT_FOUND", "first creator not committed"
            )
        return value

    def race(command):
        raise KernelError(
            "AUTHORITY_ASSET_VERSION_CONFLICT", "another creator committed first"
        )

    preparer = object.__new__(PostgresPlanningExecutionPreparer)
    preparer.query = SimpleNamespace(require=lookup)
    preparer.writer = SimpleNamespace(materialize_output=race)

    def create():
        return preparer._ensure_contract(
            operation_id="operation",
            project_id="project",
            logical_ref="contract",
            asset_type="model_profile",
            contract=contract,
            trace_id="trace",
            correlation_id="correlation",
        )

    if same:
        assert create() is winner
    else:
        with pytest.raises(KernelError, match="EXECUTION_CONTRACT_FROZEN_CONFLICT"):
            create()


@pytest.mark.parametrize(
    "change,code",
    [
        ({}, None),
        ({"reasoning_effort": "medium"}, "REASONING_UNAUTHORIZED"),
        ({"model_backend_id": "different-backend"}, "ACCOUNT_DRIFT"),
        ({"runtime_class": "REMOTE_API"}, "ACCOUNT_DRIFT"),
        ({"cost_accounting_basis": "PRICED"}, "ACCOUNT_DRIFT"),
        ({"account_identity_ref": "different-account"}, "ACCOUNT_DRIFT"),
        ({"codex_home": "/different/account"}, "ACCOUNT_DRIFT"),
        ({"executable": "/different/codex"}, "ACCOUNT_DRIFT"),
        ({"configuration_ref": "different-configuration"}, "ACCOUNT_DRIFT"),
        ({"retry_policy": "codex-no-transport-retry.v1"}, "ACCOUNT_DRIFT"),
    ],
)
def test_continuation_preserves_native_book_account_but_uses_current_reasoning_decision(
    change, code
):
    from novel_forge.modules.production_execution.codex_configuration import (
        codex_local_binding_hash,
    )
    from novel_forge.modules.story_planning_runtime.runtime_continuation import (
        require_route_evidence,
    )

    old = {
        "authorization_ref": "old-budget",
        "account_identity_ref": "same-account",
        "cli_version": "1.0",
        "executable_sha256": "sha256:" + "a" * 64,
        "configuration_ref": "configuration",
    }
    suffix = codex_local_binding_hash(
        codex_home="/account", executable="/bin/codex", entitlement=old
    )
    route = {
        "model_profile": {
            "backend_id": "codex-cli",
            "runtime_class": "LOCAL_CLI_REMOTE_INFERENCE",
        },
        "auth_profile_ref": "auth:codex:" + suffix,
    }
    frozen = {
        "models": {"draft": route, "narrative_semantic_evaluation": deepcopy(route)},
        "cost_accounting": {
            "accounting_basis": "ACCOUNT_ENTITLEMENT",
            "authorization_ref": {"native_budget_contract_hash": "old-contract"},
        },
        "runtime_settings": {
            "NOVEL_FORGE_CODEX_ACCOUNT_IDENTITY_REF": old["account_identity_ref"],
            "NOVEL_FORGE_CODEX_CLI_VERSION": old["cli_version"],
            "NOVEL_FORGE_CODEX_EXECUTABLE_SHA256": old["executable_sha256"],
            "NOVEL_FORGE_CODEX_CONFIGURATION_REF": old["configuration_ref"],
            "NOVEL_FORGE_CODEX_ACCOUNT_AUTHORIZATION_REF": {
                "native_budget_contract_hash": "old-contract"
            },
        },
    }
    target = {
        "reasoning_effort": "high",
        "model_backend_id": "codex-cli",
        "runtime_class": "LOCAL_CLI_REMOTE_INFERENCE",
        "model_provider": "codex-cli",
        "cost_accounting_basis": "ACCOUNT_ENTITLEMENT",
        "account": {
            "codex_home": "/account",
            "executable": "/bin/codex",
            "entitlement": {**old, "authorization_ref": "native-new-budget"},
        },
    }
    for key, value in change.items():
        if key in {"codex_home", "executable", "retry_policy"}:
            target["account"][key] = value
        elif key in old:
            target["account"]["entitlement"][key] = value
        else:
            target[key] = value
    results = [({"creation_pilot": frozen},), [("old-budget",)]]

    class Cursor:
        def execute(self, query, args):
            self.result = results.pop(0)

        def fetchone(self):
            return self.result

        def fetchall(self):
            return self.result

    source = {
        "source_operation_id": "source",
        "provider": "codex-cli",
        "command": {
            "project_id": "project",
            "workspace_id": "workspace",
            "book_id": "book",
        },
    }

    def validate():
        return require_route_evidence(
            SimpleNamespace(cursor=Cursor()),
            source=source,
            target=target,
            authorized_reasoning_effort="high",
        )

    if code:
        with pytest.raises(KernelError, match=f"PLANNING_RUNTIME_CONTINUATION_{code}"):
            validate()
    else:
        evidence = validate()
        assert evidence["reasoning_evidence_source"] == "CURRENT_USER_DECISION"
        assert (
            evidence["account_evidence_source"] == "BOOK_RUNTIME_POLICY_CREATION_PILOT"
        )
        assert evidence["source_auth_profile_ref"] == route["auth_profile_ref"]
        assert (
            evidence["authorization_reference_change"]
            == "NATIVE_BUDGET_SUCCESSOR_ALLOWED"
        )


@pytest.mark.parametrize("status", ["FAILED_FINAL", "DEAD_LETTER"])
def test_terminal_capacity_continuation_rejects_any_external_intent_or_frozen_context(
    status,
):
    from unittest.mock import Mock

    uow = SimpleNamespace(cursor=Mock())
    frozen = {"project_id": "project", "workspace_id": "workspace", "book_id": "book"}
    uow.cursor.fetchone.side_effect = [
        (status, 8, "workspace", frozen, "book", None),
        (
            "FAILED_FINAL",
            {},
            {"error_code": "PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED"},
        ),
        (True,),
    ]
    with pytest.raises(KernelError, match="DISPATCH_UNSAFE"):
        require_source(uow, source_operation_id="source", project_id="project")
    assert uow.cursor.execute.call_count == 3


def test_terminal_noncapacity_failure_cannot_borrow_cancelled_runtime_continuation():
    with pytest.raises(KernelError, match="SOURCE_INVALID"):
        require_source(
            source_uow(status="FAILED_FINAL"),
            source_operation_id="source",
            project_id="project",
        )


@pytest.mark.parametrize("continued", [False, True])
def test_recap_context_successor_cannot_revive_cancelled_or_dispatched_source(monkeypatch, continued):
    from unittest.mock import Mock
    from novel_forge.modules.story_planning_runtime import application

    command = SimpleNamespace(project_id="project", book_id="book", runtime_continuation_id="prior" if continued else None)
    monkeypatch.setattr(application, "_command_from_payload", lambda value: command)
    frozen = {"project_id": "project", "workspace_id": "workspace", "book_id": "book", "execution_contract_version": "1.19.0"}
    cursor = Mock()
    cursor.fetchone.side_effect = [
        ("FAILED_FINAL", 8, "workspace", frozen, "book", None),
        ("FAILED_FINAL", {}, {"error_code": "PLANNING_CONTEXT_CHANGE_EVIDENCE_INVALID"}),
        (True,),
    ]
    code = "BOUND_EXCEEDED" if continued else "DISPATCH_UNSAFE"
    with pytest.raises(KernelError, match=code):
        require_source(SimpleNamespace(cursor=cursor), source_operation_id="source", project_id="project")


@pytest.mark.parametrize("wrong_contract", ["1.18.0", "1.20.0"])
def test_recap_context_successor_is_exact_historical_contract_recovery(wrong_contract):
    with pytest.raises(KernelError, match="SOURCE_INVALID"):
        require_source(source_uow(status="FAILED_FINAL", error="PLANNING_CONTEXT_CHANGE_EVIDENCE_INVALID", command={"execution_contract_version": wrong_contract}), source_operation_id="source", project_id="project")


@pytest.mark.parametrize('fault', [None, 'unrelated-route', 'identity', 'missing-input', 'typed-context'])
def test_arc_context_continuation_requires_exact_capacity_failure_and_frozen_semantics(monkeypatch, fault):
    from unittest.mock import Mock
    from novel_forge.modules.story_planning_runtime import runtime_continuation as module
    from novel_forge.modules.chapter_authority import provider_views

    segment = {'role': 'related_arc:1', 'asset_version_id': 'arc-version', 'content_hash': 'arc-hash',
        'content': {'generator_operation_name': 'arc_plan.generate', 'narrative_search_projection': {}}}
    if fault == 'typed-context':
        segment['content'].pop('narrative_search_projection')
    monkeypatch.setattr(provider_views, 'compile_planning_provider_context', lambda *args: ({'segments': [segment]}, {}))
    inputs = [{'role': 'arc_plans', 'asset_version_id': 'arc-version', 'content_hash': 'arc-hash'}]
    context = {'input_versions': [] if fault == 'missing-input' else inputs}
    decision = {'status': 'BLOCKED', 'mode': 'CREATIVE_VALIDATION',
        'task': {'operation_id': 'other' if fault == 'identity' else 'source'},
        'candidates': [{'rejected_reasons': ['PROVIDER_UNAVAILABLE'] if fault == 'unrelated-route' else ['CONTEXT_CAPACITY_EXCEEDED', 'BUDGET_HARD_LIMIT']}]}
    uow = SimpleNamespace(cursor=Mock())
    uow.cursor.fetchone.side_effect = [('context-version', 'context-hash', context), ('route-version', 'route-hash', decision)]
    capacity = Mock(return_value={'inputs': inputs, 'depth': 2})
    monkeypatch.setattr(module, '_pre_send_capacity_source', capacity)
    def run():
        return module._arc_role_context_source(uow, source_operation_id='source', row=None,
            frozen={'generator_operation_name': 'chapter_group_plan.generate'}, attempt=None)
    if fault:
        with pytest.raises(KernelError, match='PLANNING_ARC_CONTEXT_SOURCE_INVALID'):
            run()
    else:
        result = run()
        assert result['mode'] == 'ARC_ROLE_CONTEXT_REVALIDATION'
        assert result['depth'] == 2
        assert result['arc_context_proof']['context_content_hash'] == 'context-hash'
        assert capacity.call_args.kwargs['allow_frozen_context'] is True


@pytest.mark.parametrize('has_external_intent', [True, False])
def test_arc_context_cannot_borrow_unknown_or_reserved_external_outcome(has_external_intent):
    from unittest.mock import Mock
    from novel_forge.modules.story_planning_runtime.runtime_continuation import _pre_send_capacity_source
    uow = SimpleNamespace(cursor=Mock())
    uow.cursor.fetchone.side_effect = [(has_external_intent,), None]
    with pytest.raises(KernelError, match='DISPATCH_UNSAFE' if has_external_intent else 'SNAPSHOT_MISSING'):
        _pre_send_capacity_source(uow, source_operation_id='source', row=None, frozen={}, attempt=None, allow_frozen_context=True)

@pytest.mark.parametrize('status', ['SUCCEEDED','EXECUTING','FAILED_FINAL','CANCELLED','DEAD_LETTER',None])
def test_completed_owner_receipt_read_cannot_reopen_an_execution(monkeypatch,status):
    from unittest.mock import Mock, MagicMock
    from novel_forge.modules.command_kernel import external_effect_runtime as module
    context=module.EffectCommandContext(operation_id='owner',project_id='project',actor_id='actor',trace_id='trace',correlation_id='correlation')
    uow=Mock();uow.cursor.fetchone.return_value=(status,) if status else None
    factory=MagicMock();factory.return_value.__enter__.return_value=uow
    read=Mock(return_value={'recovered':True})
    monkeypatch.setattr(module,'AuthorityUnitOfWork',factory)
    monkeypatch.setattr(module,'_read_verified_success',read)
    if status=='SUCCEEDED':
        assert module.read_completed_operation_success('database',context,effect_id='effect')=={'recovered':True}
        read.assert_called_once()
    else:
        with pytest.raises(KernelError,match='EFFECT_RETAINED_RESULT_OWNER_INVALID'):
            module.read_completed_operation_success('database',context,effect_id='effect')
        read.assert_not_called()


def test_frozen_context_successor_rebinds_only_host_catalog_and_preserves_original():
    from novel_forge.modules.story_planning_runtime.execution import PostgresPlanningExecutionPreparer
    from unittest.mock import Mock
    source={'token_budget':10,'input_versions':[{'role':'story_state','content_hash':'accepted-hash'}],
        'narrative_intelligence':{'selection_digest':'frozen'},'repair_context':{'repair_number':2},
        'realization_reference_contract':{'references_by_domain':{'WORLD_STATE':[{'asset_version_id':'state:1','frozen_by_operation_id':'parent'}]}},
        'context_manifest':{'provider_context_view':'original'}}
    frozen=deepcopy(source)
    preparer=SimpleNamespace(_planning_context_manifest=Mock(return_value={'token_accounting':{'accepted_tokens':12}}))
    value=PostgresPlanningExecutionPreparer._reproject_frozen_context(preparer,source,command=SimpleNamespace(execution_contract_version='1.20.0'),task_tokens=20,operation_id='successor')
    assert source==frozen
    assert value['input_versions']==source['input_versions']
    assert value['narrative_intelligence']==source['narrative_intelligence']
    assert value['repair_context']=={'repair_number':2}
    assert value['realization_reference_contract']['references_by_domain']['WORLD_STATE'][0]['frozen_by_operation_id']=='successor'
    assert value['estimated_tokens']==12


def test_source_selector_contract_binds_host_identity_and_rejects_foreign_or_metadata_input():
    from novel_forge.modules.story_planning_runtime.execution import bind_provider_realization_selectors,bind_realization_selector_schema
    domains=['WORLD_INVARIANT','WORLD_STRUCTURE','WORLD_STATE','CHARACTER_IDENTITY','CHARACTER_STATE','CHARACTER_TRAJECTORY']
    catalog={'references_by_domain':{domain:[{'asset_version_id':domain.lower(), 'domain_type':domain,
        'project_id':'project','book_id':'book','content_hash':'sha256:'+'a'*64,'frozen_by_operation_id':'current'}] for domain in domains}}
    raw={'objective':'Preserve silence and a future choice.',
        'world_realization':[{'world_id':'city','invariant_refs':[{'asset_version_id':'world_invariant'}],
            'structure_refs':[{'asset_version_id':'world_structure'}],'state_ref':{'asset_version_id':'world_state'}}],
        'character_realization':[{'character_id':'witness','identity_ref':{'asset_version_id':'character_identity'},
            'state_ref':{'asset_version_id':'character_state'},'trajectory_ref':{'asset_version_id':'character_trajectory'}}]}
    frozen=deepcopy(raw)
    bound=bind_provider_realization_selectors(raw,catalog)
    assert raw==frozen and bound['objective']==raw['objective']
    assert bound['world_realization'][0]['state_ref']==catalog['references_by_domain']['WORLD_STATE'][0]
    for selector in [{'asset_version_id':'future-version'},{'asset_version_id':'world_state','frozen_by_operation_id':'forged'}]:
        invalid=deepcopy(raw);invalid['world_realization'][0]['state_ref']=selector
        with pytest.raises(KernelError,match='PLANNING_REALIZATION_SELECTOR_INVALID'):
            bind_provider_realization_selectors(invalid,catalog)
    schema={'properties':{'world_realization':{'items':{'properties':{'invariant_refs':{},'structure_refs':{},'state_ref':{}}}},
        'character_realization':{'items':{'properties':{'identity_ref':{},'state_ref':{},'trajectory_ref':{}}}},
        'primary_arc_ids':{},'secondary_arc_ids':{}}}
    original=deepcopy(schema)
    value=bind_realization_selector_schema(schema,catalog,primary_arc_id='main-arc',related_arc_ids=('witness-arc','cost-arc'))
    assert schema==original
    reference=value['properties']['world_realization']['items']['properties']['state_ref']
    assert reference['required']==['asset_version_id'] and reference['additionalProperties'] is False
    assert value['properties']['secondary_arc_ids']['minItems']==2
    assert value['properties']['secondary_arc_ids']['maxItems']==2
    assert value['properties']['secondary_arc_ids']['uniqueItems'] is True


@pytest.mark.parametrize("source_repair_number", [0, 1])
def test_zero_send_capacity_route_is_not_a_content_repair(monkeypatch, source_repair_number):
    from unittest.mock import Mock
    from novel_forge.modules.story_planning_runtime import execution, runtime_continuation
    from novel_forge.storage import authority_uow
    payload = {"execution_contract_version": "1.20.0"}
    command = SimpleNamespace(runtime_continuation_id="continuation", execution_contract_version="1.20.0",
                              project_id="project", repair_number=0)
    monkeypatch.setattr(runtime_continuation, "require_binding", lambda *args: {
        "successor_command": payload, "target_runtime": {"pack_snapshot": {}}, "source_operation_id": "source"})
    monkeypatch.setattr(runtime_continuation, "require_source", lambda *args, **kwargs: {
        "mode": "PRE_SEND_CAPACITY", "command": {"repair_number": source_repair_number}})
    uow = Mock()
    uow.__enter__ = Mock(return_value=uow)
    uow.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(authority_uow, "AuthorityUnitOfWork", lambda *args: uow)
    def receipt():
        return execution._world_contract_route_receipt("db", command=command, payload=payload,
                                                      task_type="chapter_group.generate", input_hash="new", lineage=("source", "successor"), maximum=2)
    if source_repair_number:
        with pytest.raises(KernelError, match="PLANNING_ROUTING_CONTRACT_DRIFT"):
            receipt()
    else:
        assert receipt() is None
    uow.cursor.execute.assert_not_called()
