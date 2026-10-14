import json

import pytest

from novel_forge.modules.production_execution.codex_configuration import (
    CODEX_INPUT_ONLY_OVERRIDES,
    codex_input_only_overrides,
    codex_local_binding_hash,
    owned_codex_tool_evidence,
)
from tests.unit.test_codex_original_recovery import execution as execution


def test_versioned_input_only_policy_keeps_legacy_binding_and_binds_generation_role():
    assert codex_input_only_overrides("") == CODEX_INPUT_ONLY_OVERRIDES
    updated = codex_input_only_overrides("codex-input-only.v2")
    assert set(CODEX_INPUT_ONLY_OVERRIDES) <= set(updated)
    assert any(value.startswith("instructions=") for value in updated)
    args = {"codex_home": "/home", "executable": "/codex", "entitlement": {}}
    assert codex_local_binding_hash(**args) != codex_local_binding_hash(
        **args, input_only_policy="codex-input-only.v2"
    )
    with pytest.raises(ValueError, match="unsupported"):
        codex_input_only_overrides("unknown")


def rollout(tmp_path, *, call=False, wrong_id=False):
    thread = "11111111-1111-4111-8111-111111111111"
    target = tmp_path / "sessions/2026/10/15" / f"rollout-{thread}.jsonl"
    target.parent.mkdir(parents=True)
    rows = [
        {
            "type": "session_meta",
            "payload": {"id": "foreign" if wrong_id else thread, "cwd": "/work"},
        }
    ]
    if call:
        rows.append(
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "call_id": "hidden-call",
                    "input": "text(1)",
                },
            }
        )
    rows.append(
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "final",
                "content": [],
            },
        }
    )
    target.write_text("\n".join(json.dumps(row) for row in rows))
    stdout = json.dumps({"type": "thread.started", "thread_id": thread})
    return stdout, target


def test_owned_trace_catches_custom_call_missing_from_stdout(tmp_path):
    stdout, _ = rollout(tmp_path, call=True)
    result = owned_codex_tool_evidence(
        stdout, codex_home=str(tmp_path), working_directory="/work"
    )
    assert result["invoked"] == ["codex.custom_tool_call"]
    assert result["calls"][0]["name"] == "exec"


def test_owned_trace_requires_exact_thread_and_directory(tmp_path):
    stdout, target = rollout(tmp_path)
    assert (
        owned_codex_tool_evidence(
            stdout, codex_home=str(tmp_path), working_directory="/work"
        )["invoked"]
        == []
    )
    with pytest.raises(ValueError, match="directory"):
        owned_codex_tool_evidence(
            stdout, codex_home=str(tmp_path), working_directory="/foreign"
        )
    target.unlink()
    with pytest.raises(ValueError, match="one"):
        owned_codex_tool_evidence(
            stdout, codex_home=str(tmp_path), working_directory="/work"
        )


def test_owned_trace_rejects_foreign_metadata_and_path_escape(tmp_path):
    stdout, _ = rollout(tmp_path, wrong_id=True)
    with pytest.raises(ValueError, match="identity"):
        owned_codex_tool_evidence(
            stdout, codex_home=str(tmp_path), working_directory="/work"
        )
    with pytest.raises(ValueError, match="thread"):
        owned_codex_tool_evidence(
            json.dumps({"type": "thread.started", "thread_id": "../../other"}),
            codex_home=str(tmp_path),
            working_directory="/work",
        )


@pytest.mark.parametrize(
    "bad_record", [None, {"type": "response_item", "payload": None}]
)
def test_owned_trace_rejects_malformed_or_incomplete_transcript(tmp_path, bad_record):
    stdout, target = rollout(tmp_path)
    target.write_text(target.read_text() + "\n" + json.dumps(bad_record))
    with pytest.raises(ValueError, match="non-object"):
        owned_codex_tool_evidence(
            stdout, codex_home=str(tmp_path), working_directory="/work"
        )
    target.write_text(target.read_text().splitlines()[0])
    with pytest.raises(ValueError, match="final"):
        owned_codex_tool_evidence(
            stdout, codex_home=str(tmp_path), working_directory="/work"
        )


@pytest.mark.parametrize("hidden_call", [False, True])
def test_backend_checks_owned_trace_before_releasing_output(
    execution, tmp_path, hidden_call
):
    from novel_forge.modules.production_execution import ExecutionOutcome

    backend, handle, store, directory = execution
    backend.input_only_policy = "codex-input-only.v2"
    backend.codex_home = str(tmp_path)
    store.get_record(handle.execution_id).raw_evidence["model_authority"][
        "input_only_policy"
    ] = backend.input_only_policy
    stdout, transcript = rollout(tmp_path, call=hidden_call)
    rows = [json.loads(line) for line in transcript.read_text().splitlines()]
    rows[0]["payload"]["cwd"] = str(tmp_path)
    transcript.write_text("\n".join(map(json.dumps, rows)))
    receipt = directory.read_receipt(handle.execution_id)
    from pathlib import Path

    events = [
        json.loads(line) for line in Path(receipt.stdout_path).read_text().splitlines()
    ]
    events[0] = json.loads(stdout)
    Path(receipt.stdout_path).write_text("\n".join(map(json.dumps, events)))
    result = backend.reconcile(handle)
    assert (result.outcome == ExecutionOutcome.SUCCEEDED) is not hidden_call
    if hidden_call:
        assert result.normalized_output_ref is None
    assert store.get_record(handle.execution_id).raw_evidence["owned_tool_trace"][
        "invoked"
    ] == (["codex.custom_tool_call"] if hidden_call else [])


def test_current_policy_does_not_reinterpret_legacy_saved_receipt(execution):
    from novel_forge.modules.production_execution import ExecutionOutcome

    backend, handle, store, _ = execution
    backend.input_only_policy = "codex-input-only.v2"
    assert backend.reconcile(handle).outcome == ExecutionOutcome.SUCCEEDED
    assert "owned_tool_trace" not in store.get_record(handle.execution_id).raw_evidence


def test_local_preflight_reports_effective_policy_and_blocks_unknown(
    tmp_path, monkeypatch
):
    import sys
    from novel_forge.modules.production_execution import backends
    from novel_forge.modules.production_execution.codex_configuration import (
        inspect_local_codex,
    )

    monkeypatch.setattr(
        backends, "observe_codex_cli_version", lambda *args, **kwargs: "codex-cli test"
    )
    values = {
        "NOVEL_FORGE_CODEX_EXECUTABLE": sys.executable,
        "NOVEL_FORGE_CODEX_WORKSPACE": str(tmp_path),
        "NOVEL_FORGE_CODEX_HOME": str(tmp_path),
        "NOVEL_FORGE_CODEX_EXECUTION_ROOT": str(tmp_path),
        "NOVEL_FORGE_CODEX_INPUT_ONLY_POLICY": "codex-input-only.v2",
    }
    result = inspect_local_codex(values)
    assert result["input_only_policy"] == "codex-input-only.v2"
    assert result["invocation_overrides"] == list(
        codex_input_only_overrides("codex-input-only.v2")
    )
    assert result["model_calls"] == 0
    values["NOVEL_FORGE_CODEX_INPUT_ONLY_POLICY"] = "unknown"
    assert (
        "CODEX_INPUT_ONLY_POLICY_UNSUPPORTED" in inspect_local_codex(values)["blockers"]
    )
