from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapterError,
)
from novel_forge.tools.historical_reality import (
    load_historical_reality_policy,
    validate_proof_scope,
)


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "run_real_provider_qualification",
    SCRIPTS / "run_real_provider_qualification.py",
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("real Provider qualification runner could not be loaded")
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class RealProviderQualificationRunnerTests(unittest.TestCase):
    def test_live_evidence_uses_the_typed_current_proof_scope(self) -> None:
        policy = load_historical_reality_policy(ROOT)

        self.assertEqual(
            validate_proof_scope(RUNNER.PROOF_SCOPE, policy=policy),
            [],
        )

    def test_ambiguous_response_fault_is_typed_as_request_sent(self) -> None:
        class Delegate:
            calls = 0

            def execute(self, **_values: object) -> object:
                self.calls += 1
                return object()

        delegate = Delegate()
        gateway = RUNNER.OneShotAmbiguousResponseGateway(delegate)

        with self.assertRaises(ExternalEffectAdapterError) as failure:
            gateway.execute(
                stable_idempotency_key="effect:stable",
                capability="model.retrieval",
                request_payload={},
            )

        self.assertTrue(failure.exception.request_sent)
        self.assertTrue(gateway.triggered)
        self.assertEqual(delegate.calls, 1)

    def test_runtime_environment_freezes_controlled_composition_routes(self) -> None:
        with TemporaryDirectory() as directory:
            env = RUNNER._runtime_environment(
                commit_sha="a" * 40,
                codex_executable="/tmp/codex",
                runtime_root=Path(directory),
                model="gpt-test",
                reasoning_effort="high",
            )

        self.assertEqual(env["NOVEL_FORGE_EMBEDDING_PROVIDER"], "codex-cli")
        self.assertEqual(env["NOVEL_FORGE_EMBEDDING_MODEL"], "gpt-test")
        self.assertEqual(env["NOVEL_FORGE_DRAFT_MODEL"], "gpt-test")
        self.assertEqual(env["NOVEL_FORGE_REVIEW_MODEL"], "gpt-test")
        self.assertEqual(env["NOVEL_FORGE_QUALITY_MODEL"], "gpt-test")
        self.assertEqual(
            env["NOVEL_FORGE_RUNTIME_HOST_ID"],
            "host:provider-qualification:" + "a" * 12,
        )
        self.assertEqual(
            env["NOVEL_FORGE_NARRATIVE_EVALUATOR_PROVIDER"], "codex-cli"
        )
        self.assertEqual(env["NOVEL_FORGE_NARRATIVE_EVALUATOR_MODEL"], "gpt-test")
        self.assertEqual(
            env["NOVEL_FORGE_NARRATIVE_SEMANTIC_EVALUATION_REASONING_EFFORT"],
            "high",
        )

    def test_process_receipt_count_is_measured_from_runtime_state(self) -> None:
        with TemporaryDirectory() as directory:
            runtime_root = Path(directory)
            receipt_dir = runtime_root / "codex-executions" / "execution-a"
            receipt_dir.mkdir(parents=True)
            stdout_path = receipt_dir / "stdout.log"
            stderr_path = receipt_dir / "stderr.log"
            stdout_path.write_text('{"result":"ok"}\n', encoding="utf-8")
            stderr_path.write_text("", encoding="utf-8")
            (receipt_dir / "process-receipt.json").write_text(
                json.dumps(
                    {
                        "receipt_id": "receipt:a",
                        "execution_id": "execution:a",
                        "status": "SUCCEEDED",
                        "transport": "LOCAL_CLI_REMOTE_INFERENCE",
                        "stdout_path": str(stdout_path),
                        "stderr_path": str(stderr_path),
                        "environment_keys": ["PATH", "CODEX_HOME"],
                    }
                ),
                encoding="utf-8",
            )

            evidence = RUNNER._provider_process_evidence(
                runtime_root, execution_id="execution:a"
            )

        self.assertEqual(evidence["process_receipt_count"], 1)
        self.assertEqual(evidence["duplicate_provider_process_count"], 0)
        self.assertRegex(
            evidence["process_receipt_identity_hash"], r"^sha256:[0-9a-f]{64}$"
        )
        self.assertEqual(
            evidence["process_log_evidence"]["stdout"]["secret_scan"], "PASS"
        )
        self.assertEqual(evidence["credential_environment_keys_present"], [])

    def test_process_log_secret_material_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            runtime_root = Path(directory)
            receipt_dir = runtime_root / "codex-executions" / "execution-a"
            receipt_dir.mkdir(parents=True)
            stdout_path = receipt_dir / "stdout.log"
            stderr_path = receipt_dir / "stderr.log"
            stdout_path.write_text(
                "api_key=provider-secret-value\n", encoding="utf-8"
            )
            stderr_path.write_text("", encoding="utf-8")
            (receipt_dir / "process-receipt.json").write_text(
                json.dumps(
                    {
                        "execution_id": "execution:a",
                        "stdout_path": str(stdout_path),
                        "stderr_path": str(stderr_path),
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "inline secret material"):
                RUNNER._provider_process_evidence(
                    runtime_root, execution_id="execution:a"
                )

    def test_duplicate_process_receipts_fail_closed(self) -> None:
        with TemporaryDirectory() as directory:
            runtime_root = Path(directory)
            for name in ("execution-a", "execution-b"):
                receipt_dir = runtime_root / "codex-executions" / name
                receipt_dir.mkdir(parents=True)
                (receipt_dir / "process-receipt.json").write_text(
                    json.dumps({"execution_id": "execution:a"}),
                    encoding="utf-8",
                )

            with self.assertRaisesRegex(RuntimeError, "exactly one"):
                RUNNER._provider_process_evidence(
                    runtime_root, execution_id="execution:a"
                )

    def test_failure_evidence_and_stdout_redact_secret_material(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "failure.json"
            argv = [
                "run_real_provider_qualification.py",
                "--database-url",
                "postgresql://operator:database-secret@localhost/runtime",
                "--runtime-root",
                str(Path(directory) / "runtime"),
                "--output",
                str(output),
                "--expected-sha",
                "a" * 40,
                "--minio-endpoint",
                "localhost:9000",
            ]
            stdout = io.StringIO()
            with (
                patch.object(sys, "argv", argv),
                patch.object(
                    RUNNER,
                    "_run",
                    side_effect=RuntimeError(
                        "postgresql://operator:database-secret@localhost/runtime "
                        "api_key=provider-secret-value"
                    ),
                ),
                redirect_stdout(stdout),
            ):
                status = RUNNER.main()

            retained = output.read_text(encoding="utf-8")
            self.assertEqual(status, 1)
            self.assertNotIn("database-secret", retained)
            self.assertNotIn("provider-secret-value", retained)
            self.assertNotIn("database-secret", stdout.getvalue())
            self.assertNotIn("provider-secret-value", stdout.getvalue())
            evidence = json.loads(retained)
            self.assertEqual(evidence["result"], "FAIL")
            self.assertEqual(
                evidence["proof_scope"]["proves"],
                ["external-effect-provider-control"],
            )
            self.assertNotIn("proof_flags", evidence)


if __name__ == "__main__":
    unittest.main()
