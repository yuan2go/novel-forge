from __future__ import annotations

import unittest
from pathlib import Path

from novel_forge.modules.longform_stability.semantic_similarity import (
    resolve_similarity_provider,
)
from novel_forge.modules.production_execution import (
    DomainExecutionCandidate,
    DomainExecutionEvidence,
    LongformAnalysisKind,
    execute_longform_analysis,
)


class _RecordingLongformPort:
    def __init__(self) -> None:
        self.capabilities: list[str] = []

    def execute(self, command):
        self.capabilities.append(command.capability)
        return DomainExecutionCandidate(
            command.candidate_kind,
            {"analysis": "fixture candidate"},
            DomainExecutionEvidence(
                execution_id=f"execution-{len(self.capabilities)}",
                operation_id="operation-1",
                attempt_id=f"attempt-{len(self.capabilities)}",
                fencing_token=1,
                capability=command.capability,
                backend_id="scripted-fixture",
                route_snapshot_id="route-1",
                input_manifest_ref="input-1",
                output_manifest_ref="output-1",
                validation_manifest_ref="validation-1",
                usage_receipt_ref="usage-1",
                cost_receipt_ref="cost-1",
                fixture_protocol_only=True,
                real_model_call=False,
                production_verified=False,
            ),
        )


class _ExternalSemanticAdapter:
    name = "legacy-external"
    dimensions = 2

    def embed_text(self, text):
        raise AssertionError("controlled legacy embedding was invoked")

    def health_check(self):
        return {
            "ok": True,
            "semantic_model": True,
            "external_api": True,
        }


class LongformExecutionMigrationTests(unittest.TestCase):
    def test_uncertain_longform_kinds_resolve_to_governed_capabilities(self) -> None:
        port = _RecordingLongformPort()
        for kind in LongformAnalysisKind:
            candidate = execute_longform_analysis(
                kind,
                prompt="Analyze the frozen longform state.",
                context={"input_manifest_ref": "input-1"},
                execution_port=port,
            )
            self.assertTrue(candidate.evidence.fixture_protocol_only)
            self.assertFalse(candidate.evidence.real_model_call)

        self.assertEqual(
            port.capabilities,
            [
                "longform.recap.analyze",
                "longform.plan_vs_actual.judge",
                "longform.plan_vs_actual.judge",
                "longform.arc_closure.judge",
                "longform.arc_closure.judge",
                "longform.plan_change.generate",
                "longform.recap.analyze",
                "longform.plan_change.generate",
            ],
        )

    def test_controlled_semantic_similarity_blocks_direct_external_adapter(
        self,
    ) -> None:
        with self.assertRaisesRegex(RuntimeError, "RetrievalExecutionPort"):
            resolve_similarity_provider(
                adapter=_ExternalSemanticAdapter(),
                environment="validation",
            )

    def test_deterministic_semantic_reducers_do_not_import_execution_plane(
        self,
    ) -> None:
        source = (
            Path(__file__).resolve().parents[2]
            / "src/novel_forge/modules/longform_stability/semantic_domain.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("production_execution", source)
        self.assertNotIn("model_adapters", source)


if __name__ == "__main__":
    unittest.main()
