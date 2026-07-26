from __future__ import annotations

import unittest

from novel_forge.modules.production_execution import (
    DomainExecutionCandidate,
    DomainExecutionEvidence,
    EmbeddingCandidate,
    EmbeddingExecutionEvidence,
    RerankCandidate,
    RerankExecutionEvidence,
)
from novel_forge.modules.mkaos_model_extraction.provider_runner import run_provider


class _RecordingMkaosExecutionPort:
    def __init__(self) -> None:
        self.capabilities: list[str] = []

    def execute(self, command):
        self.capabilities.append(command.capability)
        return DomainExecutionCandidate(
            command.candidate_kind,
            {"candidates": [], "model": "mkaos-fixture-v1"},
            DomainExecutionEvidence(
                execution_id=f"execution-{command.capability}",
                operation_id="operation-1",
                attempt_id="attempt-1",
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


class MkaosRetrievalExecutionMigrationTests(unittest.TestCase):
    def test_embedding_evidence_binds_source_batch_index_usage_and_dirty_state(self) -> None:
        evidence = EmbeddingExecutionEvidence(
            embedding_model="fixture-embedding-v1",
            embedding_dimension=3,
            source_chunk_hashes=("sha256:aaa", "sha256:bbb"),
            source_eligibility="PRODUCTION_ELIGIBLE",
            batch_identity="batch-1",
            index_version="qdrant-index-v2",
            usage_receipt_ref="usage-1",
            cost_receipt_ref="cost-1",
            partial_failure=False,
            dirty_index=False,
        )
        candidate = EmbeddingCandidate(
            vectors=((0.1, 0.2, 0.3), (0.3, 0.2, 0.1)),
            evidence=evidence,
        )

        self.assertEqual(len(candidate.vectors), 2)
        self.assertFalse(candidate.evidence.dirty_index)

    def test_embedding_dimension_mismatch_and_dirty_partial_state_are_explicit(self) -> None:
        evidence = EmbeddingExecutionEvidence(
            embedding_model="fixture-embedding-v1",
            embedding_dimension=2,
            source_chunk_hashes=("sha256:aaa",),
            source_eligibility="PRODUCTION_ELIGIBLE",
            batch_identity="batch-2",
            index_version="index-v2",
            usage_receipt_ref="usage-2",
            cost_receipt_ref="cost-2",
            partial_failure=True,
            dirty_index=True,
        )
        with self.assertRaisesRegex(ValueError, "dimensions"):
            EmbeddingCandidate(vectors=((0.1,),), evidence=evidence)

    def test_rerank_evidence_binds_candidate_set_and_order(self) -> None:
        evidence = RerankExecutionEvidence(
            candidate_set_version="candidates:v3",
            route_snapshot_id="route-1",
            input_manifest_ref="input-1",
            ordered_scores=(("asset-b", 0.9), ("asset-a", 0.6)),
            usage_receipt_ref="usage-1",
            cost_receipt_ref="cost-1",
        )
        self.assertEqual(evidence.ordered_scores[0][0], "asset-b")
        candidate = RerankCandidate(("asset-b", "asset-a"), evidence)
        self.assertEqual(candidate.ordered_candidate_ids, ("asset-b", "asset-a"))
        with self.assertRaisesRegex(ValueError, "descending"):
            RerankExecutionEvidence(
                candidate_set_version="candidates:v3",
                route_snapshot_id="route-1",
                input_manifest_ref="input-1",
                ordered_scores=(("asset-a", 0.6), ("asset-b", 0.9)),
                usage_receipt_ref="usage-1",
                cost_receipt_ref="cost-1",
            )

    def test_knowledge_rule_and_template_extraction_use_governed_capabilities(
        self,
    ) -> None:
        port = _RecordingMkaosExecutionPort()
        for extraction_kind, expected in (
            ("knowledge", "mkaos.knowledge.extract"),
            ("rule", "mkaos.rule.extract"),
            ("template", "mkaos.template.extract"),
        ):
            result = run_provider(
                {
                    "environment": "validation",
                    "provider_mode": "mock",
                    "allow_mock_provider_fixture": True,
                    "execution_port": port,
                    "extraction_kind": extraction_kind,
                    "input_summary": "abstract fixture input",
                },
                {"prompt_id": "fixture-prompt", "required_schema": {}},
            )
            self.assertTrue(result["production_execution"]["fixture_protocol_only"])
            self.assertFalse(result["production_execution"]["real_model_call"])
        self.assertEqual(
            port.capabilities,
            [
                "mkaos.knowledge.extract",
                "mkaos.rule.extract",
                "mkaos.template.extract",
            ],
        )


if __name__ == "__main__":
    unittest.main()
