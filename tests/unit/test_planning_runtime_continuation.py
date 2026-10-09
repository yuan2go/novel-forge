from copy import deepcopy
from types import SimpleNamespace

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.runtime_continuation import (
    require_source,
)


@pytest.mark.parametrize("changed", ["", "executor", "author", "book", "entitlement"])
def test_author_capacity_registration_preserves_frozen_worker(monkeypatch, changed):
    from novel_forge.modules.story_planning_runtime import runtime_continuation as runtime
    from novel_forge.modules.production_execution import execution_template
    from novel_forge.storage import story_formation_repositories
    auth = {"authorized_by_principal_id": "author", "authorization_ref": "author-grant"}
    run = {"formation_run_id": "formation", "workspace_id": "workspace",
        "frozen_input": {"generation_policy": {"auto_authorization": auth}}}
    class Repository:
        def __init__(self, cursor):
            pass
        def require(self, identity):
            return run
        def cancellation(self, identity):
            return None
    cursor = SimpleNamespace(execute=lambda *args: None, fetchall=lambda: [("formation",)])
    monkeypatch.setattr(story_formation_repositories, "StoryFormationRepository", Repository)
    monkeypatch.setattr(execution_template, "selected_book_template", lambda *args, **kwargs: {
        "policy_snapshot": {"policy": {}, "policy_hash": "policy-hash"}})
    monkeypatch.setattr(execution_template, "selected_template", lambda *args: {
        "allowed_candidates": ["codex-cli:model:medium"], "member_authorization_ref": "membership"})
    source = {"command": {"actor_id": "worker"}, "snapshot": {}}
    successor = SimpleNamespace(project_id="project", book_id="book", workspace_id="workspace", actor_id="worker")
    target = {"model_provider": "codex-cli", "model_id": "model", "reasoning_effort": "medium",
        "cost_accounting_basis": "ACCOUNT_ENTITLEMENT", "account": {"entitlement": {"authorization_ref": "membership"}},
        "pack_snapshot": {}}
    principal = SimpleNamespace(principal_id="author")
    if changed == "executor":
        successor.actor_id = "foreign-worker"
    elif changed == "author":
        principal.principal_id = "other-author"
    elif changed == "book":
        successor.workspace_id = "foreign-workspace"
    elif changed == "entitlement":
        target["account"]["entitlement"]["authorization_ref"] = "other-grant"
    if changed:
        with pytest.raises(KernelError, match="AUTHORIZATION_REQUIRED"):
            runtime._capacity_authorization(SimpleNamespace(cursor=cursor), source=source,
                successor=successor, principal=principal, target=target)
    else:
        result = runtime._capacity_authorization(SimpleNamespace(cursor=cursor), source=source,
            successor=successor, principal=principal, target=target)
        assert result["formation_run_id"] == "formation"


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
        None,
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
        None,
        (
            "FAILED_FINAL",
            {},
            {"error_code": "PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED"},
        ),
        (True,),
    ]
    with pytest.raises(KernelError, match="DISPATCH_UNSAFE"):
        require_source(uow, source_operation_id="source", project_id="project")
    assert uow.cursor.execute.call_count == 4


def test_terminal_noncapacity_failure_cannot_borrow_cancelled_runtime_continuation():
    with pytest.raises(KernelError, match="SOURCE_INVALID"):
        require_source(
            source_uow(status="FAILED_FINAL"),
            source_operation_id="source",
            project_id="project",
        )


def test_frozen_command_may_be_inspected_for_terminal_replay_on_new_release(monkeypatch):
    from dataclasses import replace
    from novel_forge.modules.story_planning_runtime import runtime_continuation as module
    from novel_forge.modules.story_planning_runtime.application import _command_payload
    from tests.unit.test_story_planning_runtime import _command
    command = replace(_command("chapter_group_plan.generate"), runtime_continuation_id="old-continuation")
    binding = {"successor_command":_command_payload(command), "target_release_sha":"a"*40,
        "successor_operation_id":"completed-old-operation", "target_runtime": {}}
    monkeypatch.setattr(module, "require_binding", lambda *args:binding)
    app = SimpleNamespace(database_url="unused", commit_sha="b"*40)
    assert module.require_successor(app, command, validate_runtime=False) == binding
    with pytest.raises(KernelError, match="COMMAND_DRIFT"):
        module.require_successor(app, command, validate_runtime=True)
    binding["successor_command"] = {**binding["successor_command"], "book_id":"foreign-book"}
    with pytest.raises(KernelError, match="COMMAND_DRIFT"):
        module.require_successor(app, command, validate_runtime=False)


def test_completed_unselected_candidate_resumes_owner_admission_without_generation(monkeypatch):
    from unittest.mock import Mock
    from novel_forge.modules.story_planning_runtime import application as module
    from tests.unit.test_story_planning_runtime import _command
    command = _command("chapter_group_plan.generate")

    class Uow:
        cursor = None

        def __enter__(self):
            self.cursor = self
            return self

        def __exit__(self, *args):
            return False

        def execute(self, *args):
            pass

        def fetchone(self):
            return "completed",module._command_payload(command),"SUCCEEDED","APPROVAL_PENDING","candidate"

    monkeypatch.setattr(module, "AuthorityUnitOfWork", lambda *args:Uow())
    app = object.__new__(module.StoryPlanningGenerationApplication)
    app.database_url = "unused"
    app.story_design = SimpleNamespace(require=lambda **kwargs:{"lifecycle":"MATERIALIZED"})
    app._require_asset = Mock(return_value={"content_hash":"frozen-hash"})
    app._advance_candidate = Mock(return_value="owner-admission-result")
    assert app._terminal_generation_replay(command, principal="trusted") == "owner-admission-result"
    assert app._advance_candidate.call_args.kwargs["replayed"] is True
    assert app._advance_candidate.call_args.kwargs["candidate_content_hash"] == "frozen-hash"


def test_terminal_replay_probes_cancellation_before_read_or_recovery(monkeypatch):
    from unittest.mock import Mock
    from novel_forge.modules.story_planning_runtime import application as module
    from tests.unit.test_story_planning_runtime import _command

    app = object.__new__(module.StoryPlanningGenerationApplication)
    app.database_url = "unused"
    uow = Mock()
    monkeypatch.setattr(module, "AuthorityUnitOfWork", uow)
    def cancelled():
        raise KernelError("BOOK_CREATION_CANCELLED", "Retained creation intent is cancelled")
    with pytest.raises(KernelError, match="BOOK_CREATION_CANCELLED"):
        app._terminal_generation_replay(_command("chapter_group_plan.generate"), principal=object(), execution_probe=cancelled)
    uow.assert_not_called()


@pytest.mark.parametrize("required_bytes,expected_error", [(180_000, None), (300_000, "PLANNING_CAPACITY_ALLOCATION_EXHAUSTED")])
def test_capacity_preflight_is_bounded_by_actual_model_window(monkeypatch, required_bytes, expected_error):
    from contextlib import nullcontext
    from novel_forge.modules.story_planning_runtime import runtime_continuation as runtime
    allocations = []
    def context_bundle(**kwargs):
        allocated = kwargs["planning_task_token_budget"]
        allocations.append(allocated)
        assert kwargs["preflight_only"] is True
        if allocated < required_bytes:
            raise KernelError("PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED", "retained input exceeds allocation",
                details={"required_serialized_bytes": required_bytes})
        return {"context_manifest": {"provider_context_view": {"retained_input": "same"}}}, None
    pack = SimpleNamespace(
        require_attempt_snapshot=lambda **kwargs: "original-snapshot",
        materialize_attempt_artifacts=lambda snapshot: SimpleNamespace(context_policy=SimpleNamespace(content={"planning_task_token_budget": 64_000})),
    )
    preparer = SimpleNamespace(pack_runtime=pack, _context_bundle=context_bundle,
        planning_route=SimpleNamespace(model_context_limit=258_400, model_output_limit=32_000,
            token_safety_margin=1_536, token_framing_overhead=256))
    app = SimpleNamespace(database_url="unused", execution_binder=SimpleNamespace(resolver=SimpleNamespace(execution_preparer=preparer)))
    source = {"attempt_id": "attempt", "snapshot_id": "snapshot", "snapshot_hash": "hash", "source_operation_id": "source",
        "snapshot": {"context_policy_ref": "policy"}, "inputs": [], "command": {}, "failure": {"error_code": "PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED"}}
    monkeypatch.setattr(runtime, "AuthorityUnitOfWork", lambda database: nullcontext(SimpleNamespace()))
    monkeypatch.setattr(runtime, "_capacity_authorization", lambda *args, **kwargs: {"capacity_only": True})
    if expected_error:
        with pytest.raises(KernelError, match=expected_error) as caught:
            runtime._capacity_target(app, source, SimpleNamespace(), SimpleNamespace(), {})
        assert caught.value.details["required_serialized_bytes"] == required_bytes
    else:
        target, evidence = runtime._capacity_target(app, source, SimpleNamespace(), SimpleNamespace(), {})
        assert target["planning_capacity"]["allocated_task_tokens"] == 224_608
        assert target["planning_capacity"]["external_intents_at_source"] == 0
    assert allocations == [128_000, 224_608]


@pytest.mark.parametrize("change", ["version", "prompt", "foreign_pack", "corrupt_snapshot"])
def test_capacity_pack_successor_preserves_contracts_and_native_hashes(monkeypatch, change):
    from novel_forge.modules.story_planning_runtime import runtime_continuation as runtime
    from novel_forge.storage import capability_pack_authority_repositories as repositories
    from novel_forge.modules.story_planning_runtime.domain import canonical_hash
    original = {"identity": {"pack_id": "pack", "version": "1.0.0"}, "prompt": {"contract": "original"}}
    current = deepcopy(original)
    current["identity"]["version"] = "1.0.1"
    if change == "prompt":
        current["prompt"]["contract"] = "changed"
    versions = {"1.0.0": original, "1.0.1": current}
    class Repository:
        def __init__(self, cursor):pass
        def require_version(self, pack, version, *, project_id):
            assert project_id == "project"
            return {"manifest": versions[version], "manifest_hash": canonical_hash(versions[version])}
    monkeypatch.setattr(repositories, "CapabilityPackAuthorityRepository", Repository)
    a = {"pack_id": "pack", "pack_version": "1.0.0", "manifest_hash": canonical_hash(original)}
    b = {"pack_id": "foreign" if change == "foreign_pack" else "pack", "pack_version": "1.0.1",
         "manifest_hash": "corrupt" if change == "corrupt_snapshot" else canonical_hash(current)}
    if change != "version":
        with pytest.raises(KernelError, match="MODEL_ROUTE_DRIFT"):
            runtime._require_version_only_pack_successor(SimpleNamespace(cursor=None), project_id="project", original=a, target=b)
    else:
        evidence = runtime._require_version_only_pack_successor(SimpleNamespace(cursor=None), project_id="project", original=a, target=b)
        assert evidence["contract_version"] == "version-only-pack-successor.v1"
        assert original["identity"]["version"] == "1.0.0"
        assert current["identity"]["version"] == "1.0.1"
