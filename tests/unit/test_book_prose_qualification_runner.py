from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.book_prose_qualification import (
    CAPABILITY,
    ConsumerRestartRequired,
    WindowResponseLoss,
    require_review_scope,
    require_unknown_checkpoint,
    validate_window_request,
)
from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapterError,
)


def fixture():
    scope = dict(
        project_id="project",
        workspace_id="workspace",
        actor_id="author",
        book_id="book",
        book_run_id="book-run",
        run_id="review-run",
        manifest_digest="digest",
    )
    binding = dict(asset_version_id="window-asset", content_hash="window-hash")
    window = dict(window_id="window", input_asset=binding)
    payload = dict(
        book_id="book",
        book_run_id="book-run",
        window_id="window",
        manifest_digest="digest",
    )
    metadata = dict(
        operation_id="operation",
        book_id="book",
        project_id="project",
        workspace_id="workspace",
        input_artifacts=[dict(binding, artifact_type="longform_prose_review_window")],
    )
    rows = [("project", "workspace", "author", {"payload": payload}, [binding])]
    return scope, window, metadata, rows


@pytest.mark.parametrize(
    "drift",
    [
        "book",
        "workspace",
        "author",
        "manifest",
        "source_hash",
        "source_version",
        "admission",
        "input_count",
    ],
)
def test_native_review_fault_requires_exact_owner_and_source(drift):
    scope, window, metadata, rows = deepcopy(fixture())
    if drift == "book":
        metadata["book_id"] = "foreign"
    elif drift == "workspace":
        scope["workspace_id"] = "foreign"
    elif drift == "author":
        scope["actor_id"] = "foreign"
    elif drift == "manifest":
        scope["manifest_digest"] = "changed"
    elif drift == "source_hash":
        metadata["input_artifacts"][0]["content_hash"] = "changed"
    elif drift == "source_version":
        metadata["input_artifacts"][0]["asset_version_id"] = "other"
    elif drift == "admission":
        rows = []
    else:
        rows[0][4].append({"asset_version_id": "other"})
    with pytest.raises(ValueError, match="D0"):
        validate_window_request(rows, scope, window, metadata)


def test_only_successful_exact_main_result_loses_response_after_retention(monkeypatch):
    scope, window, metadata, rows = fixture()
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.cursor.fetchall.return_value = rows
    monkeypatch.setattr(
        "scripts.book_prose_qualification.AuthorityUnitOfWork", lambda _: uow
    )
    delegate = MagicMock()
    delegate.execute.return_value = SimpleNamespace(outcome="success")
    wrapper = WindowResponseLoss(
        delegate, database_url="database", scope=scope, window=window
    )
    wrapper.execute(
        stable_idempotency_key="preparation",
        capability="model.context_fidelity",
        request_payload={"stage": "context_fidelity"},
    )
    assert not wrapper.triggered and wrapper.operation_id is None
    with pytest.raises(ExternalEffectAdapterError) as failure:
        wrapper.execute(
            stable_idempotency_key="main",
            capability=CAPABILITY,
            request_payload={
                "stage": "longform_prose_review",
                "_production_execution": metadata,
            },
        )
    assert failure.value.request_sent and failure.value.failure_kind == "response_loss"
    assert wrapper.triggered and wrapper.operation_id == "operation"
    assert delegate.execute.call_count == 2
    with pytest.raises(ConsumerRestartRequired):
        wrapper.session_for_project("project")
    delegate.session_for_project.assert_not_called()


def test_foreign_window_is_rejected_before_delegate_and_failed_result_is_not_a_controlled_fault(
    monkeypatch,
):
    scope, window, metadata, rows = fixture()
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.cursor.fetchall.return_value = []
    monkeypatch.setattr(
        "scripts.book_prose_qualification.AuthorityUnitOfWork", lambda _: uow
    )
    delegate = MagicMock()
    wrapper = WindowResponseLoss(
        delegate, database_url="database", scope=scope, window=window
    )
    request = dict(
        stable_idempotency_key="main",
        capability=CAPABILITY,
        request_payload={
            "stage": "longform_prose_review",
            "_production_execution": metadata,
        },
    )
    with pytest.raises(ValueError):
        wrapper.execute(**request)
    delegate.execute.assert_not_called()
    uow.cursor.fetchall.return_value = rows
    delegate.execute.return_value = SimpleNamespace(outcome="unknown")
    assert wrapper.execute(**request).outcome == "unknown"
    assert not wrapper.triggered


@pytest.mark.parametrize(
    "drift",
    [
        "paused",
        "stale",
        "release",
        "automatic",
        "acceptance",
        "whole_book",
        "dynamic_sources",
        "multiple_windows",
        "reused",
    ],
)
def test_qualification_cannot_enlarge_native_review_scope(drift):
    report = dict(
        exact_release_sha="release",
        paused=False,
        source_current=True,
        operations=[],
        manifest=dict(
            windows=[{}],
            policy=dict(
                execution_mode="MANUAL",
                window_selection="EXPLICIT_RANGES_ONLY",
                source_current_policy="FROZEN_SELECTED_RANGE",
            ),
        ),
    )
    policy = report["manifest"]["policy"]
    if drift == "paused":
        report["paused"] = True
    elif drift == "stale":
        report["source_current"] = False
    elif drift == "release":
        report["exact_release_sha"] = "old"
    elif drift == "automatic":
        policy["execution_mode"] = "AUTOMATIC"
    elif drift == "acceptance":
        policy["follow_acceptance"] = True
    elif drift == "whole_book":
        policy["window_selection"] = "ALL"
    elif drift == "dynamic_sources":
        policy["source_current_policy"] = "FOLLOW_CURRENT"
    elif drift == "multiple_windows":
        report["manifest"]["windows"].append({})
    else:
        report["operations"] = [{"source_run_id": "old-review"}]
    with pytest.raises(ValueError, match="D0"):
        require_review_scope(report, commit_sha="release")


def test_membership_native_capability_keeps_accounting_and_credentials_guards():
    from scripts.run_real_provider_qualification import _provider_readiness

    env = dict(
        NOVEL_FORGE_CODEX_ACCOUNTING_MODE="ACCOUNT_ENTITLEMENT",
        NOVEL_FORGE_RESOURCE_CONTROL_VERSION="billing-channel-resources.v1",
        NOVEL_FORGE_PROVIDER_TOKEN_ACCOUNTING_METHOD="CODEX_CLI_APPLICATION_UTF8_BYTES_UPPER_BOUND_V1",
        NOVEL_FORGE_PROVIDER_TOKEN_ACCOUNTING_EVIDENCE_REF="actual-route",
        NOVEL_FORGE_PROVIDER_MODEL_CONTEXT_LIMIT="475000",
    )
    valid = _provider_readiness(
        provider="codex-cli",
        model="model",
        env=env,
        codex_login_available=True,
        capability=CAPABILITY,
    )
    assert (
        valid["status"] == "READY_FOR_LIVE_QUALIFICATION"
        and not valid["provider_request_sent"]
    )

    assert _provider_readiness(
        provider="codex-cli",
        model="model",
        env=env,
        codex_login_available=False,
        capability=CAPABILITY,
    )["blockers"] == ["EXTERNAL_CREDENTIAL_MISSING"]
    assert (
        "RUNTIME_ACCOUNTING_CONTRACT_MISSING"
        in _provider_readiness(
            provider="codex-cli",
            model="model",
            env={},
            codex_login_available=True,
            capability=CAPABILITY,
        )["blockers"]
    )
    assert (
        "ENGINEERING_QUALIFICATION_BLOCKED:MEMBERSHIP_RETRIEVAL_RESOURCE_BINDING_MISSING"
        in _provider_readiness(
            provider="codex-cli", model="model", env=env, codex_login_available=True
        )["blockers"]
    )


@pytest.mark.parametrize(
    "change", ["none", "success", "receipt", "reconciled", "duplicate", "wrong_failure"]
)
def test_initial_consumer_cannot_claim_unknown_after_accepting_result(
    monkeypatch, change
):
    row = [
        "effect",
        "UNKNOWN",
        "UNKNOWN",
        dict(failure_kind="response_loss", request_sent=True),
        1,
        0,
        0,
    ]
    if change == "success":
        row[1] = "SUCCEEDED"
    elif change == "receipt":
        row[5] = 1
    elif change == "reconciled":
        row[6] = 1
    elif change == "duplicate":
        row[4] = 2
    elif change == "wrong_failure":
        row[3]["failure_kind"] = "network_failure"
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.cursor.fetchall.return_value = [tuple(row)]
    monkeypatch.setattr(
        "scripts.book_prose_qualification.AuthorityUnitOfWork", lambda _: uow
    )
    if change == "none":
        assert require_unknown_checkpoint("database", "operation")["receipt_count"] == 0
    else:
        with pytest.raises(ValueError, match="UNKNOWN"):
            require_unknown_checkpoint("database", "operation")


def test_direct_script_bootstrap_can_import_the_native_scenario():
    root = Path(__file__).resolve().parents[2]
    program = """import sys,runpy
from pathlib import Path
root=Path.cwd()
sys.path=[str(root/'scripts'),str(root/'src')]+[p for p in sys.path if p and Path(p).resolve()!=root]
runpy.run_path(str(root/'scripts/run_real_provider_qualification.py'))
from scripts.book_prose_qualification import run_book_prose_qualification
assert callable(run_book_prose_qualification)
print('native-scenario-imported')
"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("NOVEL_FORGE_")}
    env["PYTHONPATH"] = "src"
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "native-scenario-imported"
