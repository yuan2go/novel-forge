from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from novel_forge.modules.production_execution import (
    CodexProcessSupervisor,
    EnvironmentAllowlist,
    PersistentExecutionDirectory,
    ProcessLaunchRequest,
    ProcessReceiptStatus,
    ProcessTimeout,
    ResultIntegrity,
)


class _IdentityProbe:
    def __init__(self, *, alive: bool, start_token: str | None) -> None:
        self.alive = alive
        self.start_token = start_token

    def is_alive(self, pid: int) -> bool:
        return self.alive

    def process_start_token(self, pid: int) -> str | None:
        return self.start_token


class _CancelController:
    status = "cancelled"

    def cancel_if_requested(self) -> None:
        raise RuntimeError("local cancellation requested")

    def observe_usage_delta(self, usage_delta, *, elapsed_ms: int = 0) -> None:
        return None


class _InterruptController:
    def cancel_if_requested(self) -> None:
        raise KeyboardInterrupt("worker shutdown")

    def observe_usage_delta(self, usage_delta, *, elapsed_ms: int = 0) -> None:
        return None


class _DelayedCancellationStore(PersistentExecutionDirectory):
    """Make the signal-to-receipt race deterministic without changing signaling."""

    def write_receipt(self, receipt):
        if receipt.status is ProcessReceiptStatus.CANCELLED:
            time.sleep(0.05)
        return super().write_receipt(receipt)


class ProcessSupervisorTests(unittest.TestCase):
    def test_codex_environment_allowlist_drops_unlisted_secrets(self) -> None:
        source = {
            "PATH": "/bin",
            "HOME": "/safe-home",
            "CODEX_HOME": "/codex-home",
            "LANG": "en_US.UTF-8",
            "OPENAI_API_KEY": "must-not-cross-process-boundary",
            "AWS_SECRET_ACCESS_KEY": "must-not-cross-process-boundary",
        }

        filtered = EnvironmentAllowlist.codex_default().build(source)

        self.assertEqual(filtered["PATH"], "/bin")
        self.assertEqual(filtered["CODEX_HOME"], "/codex-home")
        self.assertNotIn("OPENAI_API_KEY", filtered)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", filtered)
        with self.assertRaisesRegex(ValueError, "not allowlisted"):
            EnvironmentAllowlist.codex_default().build(source, overrides={"OPENAI_API_KEY": "no"})

    def test_execution_directory_is_stable_and_rejects_identity_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PersistentExecutionDirectory(Path(tmp))
            first = store.prepare("execution:book/1:chapter/1")
            second = PersistentExecutionDirectory(Path(tmp)).prepare("execution:book/1:chapter/1")

            self.assertEqual(first.path, second.path)
            self.assertTrue(first.metadata_path.exists())
            store.bind_request(first, "a" * 64)
            store.bind_request(second, "a" * 64)
            with self.assertRaisesRegex(ValueError, "request digest drift"):
                store.bind_request(second, "b" * 64)
            self.assertTrue(str(first.path.resolve()).startswith(str(Path(tmp).resolve())))

    def test_supervisor_writes_attempt_bound_success_receipt_and_persistent_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PersistentExecutionDirectory(Path(tmp))
            layout = store.prepare("execution:success")
            command = (
                sys.executable,
                "-c",
                "import json,sys; json.dump({'ok': True}, open(sys.argv[1], 'w'))",
                str(layout.result_path("result.json")),
            )
            result = CodexProcessSupervisor(store).run(
                ProcessLaunchRequest(
                    execution_id="execution:success",
                    operation_id="operation:chapter-1",
                    attempt_id="attempt:7",
                    fencing_token=7,
                    command=command,
                    cwd=tmp,
                    input_text="bounded input",
                    result_filename="result.json",
                    result_format="json",
                    timeout=ProcessTimeout(timeout_seconds=3),
                )
            )

            self.assertEqual(result.receipt.status, ProcessReceiptStatus.SUCCEEDED)
            self.assertEqual(result.receipt.result_integrity, ResultIntegrity.VALID)
            self.assertTrue(result.receipt.authority_bound)
            self.assertEqual(result.receipt.attempt_id, "attempt:7")
            self.assertEqual(result.receipt.fencing_token, 7)
            self.assertEqual(result.receipt.transport, "LOCAL_CLI_REMOTE_INFERENCE")
            self.assertIsNone(result.receipt.provider_request_id)
            self.assertEqual(result.receipt.process_group.pid, result.receipt.process_group.pgid)
            self.assertTrue(layout.receipt_path.exists())
            self.assertEqual(json.loads(layout.result_path("result.json").read_text())["ok"], True)

    def test_supervisor_child_receives_only_allowlisted_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PersistentExecutionDirectory(Path(tmp))
            layout = store.prepare("execution:environment")
            command = (
                sys.executable,
                "-c",
                "import json,os,sys; json.dump({'keys': sorted(os.environ)}, open(sys.argv[1], 'w'))",
                str(layout.result_path("environment.json")),
            )
            with patch.dict(
                os.environ,
                {
                    "PATH": os.environ.get("PATH", ""),
                    "HOME": os.environ.get("HOME", ""),
                    "CODEX_HOME": "/safe-codex-home",
                    "NOVEL_FORGE_PRIVATE_TEST_SECRET": "must-not-leak",
                },
                clear=False,
            ):
                result = CodexProcessSupervisor(store).run(
                    ProcessLaunchRequest(
                        execution_id="execution:environment",
                        command=command,
                        cwd=tmp,
                        input_text="",
                        result_filename="environment.json",
                        result_format="json",
                        timeout=ProcessTimeout(timeout_seconds=3),
                    )
                )

            child_keys = json.loads(layout.result_path("environment.json").read_text())["keys"]
            self.assertEqual(result.receipt.status, ProcessReceiptStatus.SUCCEEDED)
            self.assertIn("CODEX_HOME", child_keys)
            self.assertNotIn("NOVEL_FORGE_PRIVATE_TEST_SECRET", child_keys)
            self.assertTrue(
                set(result.receipt.environment_keys).issubset(
                    set(EnvironmentAllowlist.codex_default().allowed_names)
                )
            )

    @unittest.skipUnless(hasattr(os, "killpg"), "process-group signaling requires POSIX")
    def test_timeout_escalates_from_sigterm_to_sigkill_for_entire_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PersistentExecutionDirectory(Path(tmp))
            command = (
                sys.executable,
                "-c",
                "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)",
            )
            result = CodexProcessSupervisor(store).run(
                ProcessLaunchRequest(
                    execution_id="execution:timeout",
                    command=command,
                    cwd=tmp,
                    input_text="",
                    timeout=ProcessTimeout(
                        timeout_seconds=0.5,
                        termination_grace_seconds=0.05,
                        poll_interval_seconds=0.01,
                    ),
                )
            )

            self.assertEqual(result.receipt.status, ProcessReceiptStatus.TIMED_OUT)
            self.assertEqual(result.receipt.termination_signal, signal.Signals(signal.SIGKILL).name)
            self.assertTrue(result.receipt.local_termination_only)
            self.assertIsNone(result.receipt.provider_request_id)
            with self.assertRaises(ProcessLookupError):
                os.killpg(result.receipt.process_group.pgid, 0)

    def test_successful_exit_with_corrupt_json_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PersistentExecutionDirectory(Path(tmp))
            layout = store.prepare("execution:corrupt")
            result = CodexProcessSupervisor(store).run(
                ProcessLaunchRequest(
                    execution_id="execution:corrupt",
                    command=(
                        sys.executable,
                        "-c",
                        "import sys; open(sys.argv[1], 'w').write('{not-json')",
                        str(layout.result_path("result.json")),
                    ),
                    cwd=tmp,
                    input_text="",
                    result_filename="result.json",
                    result_format="json",
                    timeout=ProcessTimeout(timeout_seconds=3),
                )
            )

            self.assertEqual(result.receipt.status, ProcessReceiptStatus.CORRUPT_RESULT)
            self.assertEqual(result.receipt.result_integrity, ResultIntegrity.CORRUPT)
            self.assertIn("JSON", result.receipt.failure_reason)

    def test_process_start_failure_is_persisted_without_fabricated_process_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PersistentExecutionDirectory(Path(tmp))
            result = CodexProcessSupervisor(store).run(
                ProcessLaunchRequest(
                    execution_id="execution:start-failure",
                    command=(str(Path(tmp) / "missing-codex-executable"),),
                    cwd=tmp,
                    input_text="",
                    timeout=ProcessTimeout(timeout_seconds=3),
                )
            )

            self.assertEqual(result.receipt.status, ProcessReceiptStatus.START_FAILED)
            self.assertIsNone(result.receipt.process_group)
            self.assertIsNone(result.receipt.provider_request_id)
            self.assertIn("FileNotFoundError", result.receipt.failure_reason)
            persisted = store.read_receipt("execution:start-failure")
            self.assertEqual(persisted.receipt_id, result.receipt.receipt_id)

    def test_local_cancellation_terminates_process_without_claiming_upstream_cancel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PersistentExecutionDirectory(Path(tmp))
            result = CodexProcessSupervisor(store).run(
                ProcessLaunchRequest(
                    execution_id="execution:cancel",
                    command=(sys.executable, "-c", "import time; time.sleep(30)"),
                    cwd=tmp,
                    input_text="",
                    timeout=ProcessTimeout(
                        timeout_seconds=5,
                        termination_grace_seconds=0.05,
                        poll_interval_seconds=0.01,
                    ),
                ),
                controller=_CancelController(),
            )

            self.assertEqual(result.receipt.status, ProcessReceiptStatus.CANCELLED)
            self.assertTrue(result.receipt.local_termination_only)
            self.assertIsNone(result.receipt.provider_request_id)
            self.assertIn(result.receipt.termination_signal, {"SIGTERM", "SIGKILL"})

    @unittest.skipUnless(hasattr(os, "killpg"), "process-group signaling requires POSIX")
    def test_supervisor_interrupt_terminates_process_group_and_persists_receipt(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PersistentExecutionDirectory(Path(tmp))
            supervisor = CodexProcessSupervisor(store)
            with self.assertRaisesRegex(KeyboardInterrupt, "worker shutdown"):
                supervisor.run(
                    ProcessLaunchRequest(
                        execution_id="execution:worker-interrupt",
                        operation_id="operation:worker-interrupt",
                        attempt_id="attempt:worker-interrupt",
                        fencing_token=17,
                        command=(sys.executable, "-c", "import time; time.sleep(30)"),
                        cwd=tmp,
                        input_text="",
                        timeout=ProcessTimeout(
                            timeout_seconds=10,
                            termination_grace_seconds=0.05,
                            poll_interval_seconds=0.01,
                        ),
                    ),
                    controller=_InterruptController(),
                )

            receipt = store.read_receipt("execution:worker-interrupt")
            self.assertEqual(receipt.status, ProcessReceiptStatus.CANCELLED)
            self.assertTrue(receipt.local_termination_only)
            self.assertEqual(receipt.termination_reason, "local supervisor interrupted: KeyboardInterrupt: worker shutdown")
            self.assertIn(receipt.termination_signal, {"SIGTERM", "SIGKILL"})
            with self.assertRaises(ProcessLookupError):
                os.killpg(receipt.process_group.pgid, 0)

    @unittest.skipUnless(hasattr(os, "killpg"), "process-group signaling requires POSIX")
    def test_external_cancel_signals_verified_running_process_and_persists_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _DelayedCancellationStore(Path(tmp))
            supervisor = CodexProcessSupervisor(store)
            request = ProcessLaunchRequest(
                execution_id="execution:external-cancel",
                operation_id="operation:external-cancel",
                attempt_id="attempt:external-cancel",
                fencing_token=11,
                command=(sys.executable, "-c", "import time; time.sleep(30)"),
                cwd=tmp,
                input_text="",
                timeout=ProcessTimeout(
                    timeout_seconds=10,
                    termination_grace_seconds=0.1,
                    poll_interval_seconds=0.01,
                ),
            )

            with ThreadPoolExecutor(max_workers=1) as pool:
                running = pool.submit(supervisor.run, request)
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    receipt = store.read_receipt(request.execution_id)
                    if (
                        receipt is not None
                        and receipt.status is ProcessReceiptStatus.RUNNING
                    ):
                        break
                    time.sleep(0.01)
                else:
                    self.fail("process never reached RUNNING")

                cancellation = supervisor.cancel(
                    request.execution_id,
                    reason="operator requested cancellation",
                    timeout=ProcessTimeout(
                        timeout_seconds=2,
                        termination_grace_seconds=0.1,
                        poll_interval_seconds=0.01,
                    ),
                )
                completed = running.result(timeout=3)

            self.assertEqual(
                cancellation.receipt.status, ProcessReceiptStatus.CANCELLED
            )
            self.assertEqual(completed.receipt.status, ProcessReceiptStatus.CANCELLED)
            self.assertTrue(cancellation.receipt.local_termination_only)
            self.assertEqual(
                cancellation.receipt.termination_reason,
                "operator requested cancellation",
            )
            self.assertIn(
                cancellation.receipt.termination_signal, {"SIGTERM", "SIGKILL"}
            )
            self.assertIsNone(cancellation.receipt.provider_request_id)
            self.assertFalse(cancellation.safe_to_signal)
            persisted = store.read_receipt(request.execution_id)
            self.assertEqual(persisted.status, ProcessReceiptStatus.CANCELLED)

    def test_external_cancel_refuses_pid_reuse_without_signaling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PersistentExecutionDirectory(Path(tmp))
            store.record_running_process(
                execution_id="execution:cancel-pid-reuse",
                pid=4242,
                pgid=4242,
                process_start_token="old-process-start-token",
                result_filename="result.json",
            )
            supervisor = CodexProcessSupervisor(
                store,
                identity_probe=_IdentityProbe(
                    alive=True, start_token="new-process-start-token"
                ),
            )

            cancellation = supervisor.cancel(
                "execution:cancel-pid-reuse",
                reason="must not signal unrelated process",
            )

            self.assertEqual(
                cancellation.receipt.status, ProcessReceiptStatus.ORPHANED
            )
            self.assertEqual(
                cancellation.receipt.recovery_reason, "PID_REUSE_DETECTED"
            )
            self.assertFalse(cancellation.safe_to_signal)

    def test_duplicate_submission_reuses_receipt_without_relaunching_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PersistentExecutionDirectory(Path(tmp))
            layout = store.prepare("execution:duplicate")
            counter_path = Path(tmp) / "launch-count.txt"
            request = ProcessLaunchRequest(
                execution_id="execution:duplicate",
                command=(
                    sys.executable,
                    "-c",
                    (
                        "import json,pathlib,sys; "
                        "p=pathlib.Path(sys.argv[1]); "
                        "p.write_text(str(int(p.read_text())+1) if p.exists() else '1'); "
                        "json.dump({'ok': True}, open(sys.argv[2], 'w'))"
                    ),
                    str(counter_path),
                    str(layout.result_path("result.json")),
                ),
                cwd=tmp,
                input_text="",
                result_filename="result.json",
                result_format="json",
                timeout=ProcessTimeout(timeout_seconds=3),
            )
            supervisor = CodexProcessSupervisor(store)

            first = supervisor.run(request)
            second = CodexProcessSupervisor(store).run(request)

            self.assertEqual(first.receipt.receipt_id, second.receipt.receipt_id)
            self.assertTrue(second.duplicate_submission)
            self.assertEqual(counter_path.read_text(encoding="utf-8"), "1")

    def test_concurrent_duplicate_submission_launches_only_one_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PersistentExecutionDirectory(Path(tmp))
            layout = store.prepare("execution:concurrent-duplicate")
            counter_path = Path(tmp) / "concurrent-launches.txt"
            request = ProcessLaunchRequest(
                execution_id="execution:concurrent-duplicate",
                command=(
                    sys.executable,
                    "-c",
                    (
                        "import json,sys,time; "
                        "open(sys.argv[1], 'a').write('launch\\n'); "
                        "time.sleep(0.3); "
                        "json.dump({'ok': True}, open(sys.argv[2], 'w'))"
                    ),
                    str(counter_path),
                    str(layout.result_path("result.json")),
                ),
                cwd=tmp,
                input_text="",
                result_filename="result.json",
                result_format="json",
                timeout=ProcessTimeout(timeout_seconds=3, poll_interval_seconds=0.01),
            )

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: CodexProcessSupervisor(store).run(request), range(2)))

            self.assertEqual(counter_path.read_text(encoding="utf-8").splitlines(), ["launch"])
            self.assertEqual(sum(result.duplicate_submission for result in results), 1)
            self.assertEqual(
                {result.receipt.status for result in results},
                {ProcessReceiptStatus.SUCCEEDED},
                [result.receipt.to_dict() for result in results],
            )

    def test_recovery_detects_pid_reuse_without_signaling_unrelated_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PersistentExecutionDirectory(Path(tmp))
            store.record_running_process(
                execution_id="execution:pid-reuse",
                pid=4242,
                pgid=4242,
                process_start_token="old-process-start-token",
                result_filename="result.json",
            )
            supervisor = CodexProcessSupervisor(
                store,
                identity_probe=_IdentityProbe(alive=True, start_token="new-process-start-token"),
            )

            recovery = supervisor.recover("execution:pid-reuse")

            self.assertEqual(recovery.receipt.status, ProcessReceiptStatus.ORPHANED)
            self.assertEqual(recovery.receipt.recovery_reason, "PID_REUSE_DETECTED")
            self.assertFalse(recovery.safe_to_signal)

    def test_recovery_preserves_valid_result_after_worker_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PersistentExecutionDirectory(Path(tmp))
            layout = store.record_running_process(
                execution_id="execution:orphan",
                pid=4343,
                pgid=4343,
                process_start_token="dead-process-token",
                result_filename="result.json",
            )
            layout.result_path("result.json").write_text('{"recoverable": true}', encoding="utf-8")
            supervisor = CodexProcessSupervisor(
                store,
                identity_probe=_IdentityProbe(alive=False, start_token=None),
            )

            recovery = supervisor.recover("execution:orphan")

            self.assertEqual(recovery.receipt.status, ProcessReceiptStatus.ORPHANED)
            self.assertEqual(recovery.receipt.result_integrity, ResultIntegrity.VALID)
            self.assertTrue(recovery.result_recoverable)
            self.assertEqual(recovery.receipt.recovery_reason, "WORKER_CRASH_RESULT_RECOVERABLE")


if __name__ == "__main__":
    unittest.main()
