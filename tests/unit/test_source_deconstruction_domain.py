from __future__ import annotations

import unittest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.source_authority.deconstruction import (
    DECONSTRUCTION_DIMENSIONS,
    AnalyzerContract,
    ObservationEvidenceSpan,
    ObservationScope,
    analyzer_prompt_bundle,
    default_analyzer_contracts,
    validate_observation_payload,
)
from novel_forge.modules.source_authority.deconstruction_application import (
    _execution_binding,
    _execution_proof,
)


class SourceDeconstructionDomainTests(unittest.TestCase):
    def test_non_fixture_execution_must_bind_inputs_contract_and_output(self) -> None:
        expected = {
            "schema_version": "source-deconstruction-execution-binding.v1",
            "analyzer_contract_hash": "sha256:" + "a" * 64,
            "scope_hash": "sha256:" + "b" * 64,
            "observation_hash": "sha256:" + "c" * 64,
            "evidence_span_ids": ["source-evidence-span:1"],
            "input_observation_asset_version_ids": ["observation:1:v1"],
        }
        with self.assertRaisesRegex(
            KernelError, "DECONSTRUCTION_EXECUTION_OUTPUT_UNBOUND"
        ):
            _execution_binding(
                {},
                evidence_class="PROVIDER_QUALIFIED",
                analyzer_contract_hash=expected["analyzer_contract_hash"],
                scope_hash=expected["scope_hash"],
                observation_hash=expected["observation_hash"],
                evidence_span_ids=("source-evidence-span:1",),
                input_observation_asset_version_ids=("observation:1:v1",),
            )

        bound = _execution_binding(
            {"source_deconstruction_binding": expected},
            evidence_class="PROVIDER_QUALIFIED",
            analyzer_contract_hash=expected["analyzer_contract_hash"],
            scope_hash=expected["scope_hash"],
            observation_hash=expected["observation_hash"],
            evidence_span_ids=("source-evidence-span:1",),
            input_observation_asset_version_ids=("observation:1:v1",),
        )
        self.assertEqual(bound["validation_status"], "VERIFIED")

    def test_deterministic_execution_proves_zero_provider_usage(self) -> None:
        proof = _execution_proof(
            {
                "deterministic_execution": True,
                "model_call_performed": False,
                "usage": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                },
                "cost": {"amount_usd": "0"},
            },
            evidence_class="DETERMINISTIC",
        )

        self.assertTrue(proof["deterministic_execution"])
        self.assertFalse(proof["production_execution_gateway_backed"])
        with self.assertRaisesRegex(
            KernelError, "DECONSTRUCTION_DETERMINISTIC_EVIDENCE_INVALID"
        ):
            _execution_proof(
                {
                    "deterministic_execution": True,
                    "model_call_performed": False,
                    "usage": {"total_tokens": 1},
                    "cost": {"amount_usd": "0"},
                },
                evidence_class="DETERMINISTIC",
            )

    def test_registry_covers_required_dimensions_with_split_prompt_contracts(self) -> None:
        contracts = default_analyzer_contracts()

        self.assertEqual(set(contracts), set(DECONSTRUCTION_DIMENSIONS))
        self.assertEqual(len({item.fingerprint for item in contracts.values()}), 14)
        hook = contracts["hook"]
        structure = contracts["structure"]
        self.assertNotEqual(hook.fingerprint, structure.fingerprint)
        prompt = analyzer_prompt_bundle(hook)
        self.assertEqual(prompt["output_kind"], "OBSERVATION")
        self.assertFalse(prompt["output_kind"] == "REUSABLE_KNOWLEDGE")
        self.assertIn("evidence_span_ids", prompt["required_fields"])
        self.assertTrue(prompt["source_policy"]["whole_book_single_call_forbidden"])

    def test_analyzer_upgrade_changes_only_its_contract_fingerprint(self) -> None:
        base = default_analyzer_contracts()
        upgraded_hook = AnalyzerContract(
            **{
                **base["hook"].to_dict(include_fingerprint=False),
                "analyzer_version": "2.0.0",
                "prompt_version": "2.0.0",
            }
        )

        self.assertNotEqual(base["hook"].fingerprint, upgraded_hook.fingerprint)
        self.assertEqual(
            base["structure"].fingerprint,
            default_analyzer_contracts()["structure"].fingerprint,
        )

    def test_evidence_address_is_stable_and_scope_supports_cross_book_pattern(self) -> None:
        span = ObservationEvidenceSpan(
            source_chunk_asset_version_id="source-chunk:a:v1",
            chunk_byte_start=10,
            chunk_byte_end=40,
            evidence_hash="sha256:" + "a" * 64,
        )
        same = ObservationEvidenceSpan(
            source_chunk_asset_version_id="source-chunk:a:v1",
            chunk_byte_start=10,
            chunk_byte_end=40,
            evidence_hash="sha256:" + "a" * 64,
        )
        cross_book = ObservationScope(
            scale="CROSS_BOOK_PATTERN",
            range_start=0,
            range_end=0,
            source_document_ids=("source-a", "source-b"),
            label="cross-book hook recurrence",
        )

        self.assertEqual(span.evidence_span_id, same.evidence_span_id)
        self.assertEqual(cross_book.scale, "CROSS_BOOK_PATTERN")
        with self.assertRaises(ValueError):
            ObservationScope(
                scale="CROSS_BOOK_PATTERN",
                range_start=0,
                range_end=0,
                source_document_ids=("source-a",),
                label="invalid",
            )

    def test_observation_is_evidence_bound_and_blocks_source_expression_fields(self) -> None:
        span = ObservationEvidenceSpan(
            source_chunk_asset_version_id="source-chunk:a:v1",
            chunk_byte_start=0,
            chunk_byte_end=20,
            evidence_hash="sha256:" + "b" * 64,
        )
        payload = {
            "findings": [
                {
                    "finding_code": "HOOK-DELAYED-ANSWER",
                    "statement": "The ending opens a bounded unanswered question.",
                    "reader_effect": "continue_to_next_chapter",
                    "evidence_span_ids": [span.evidence_span_id],
                    "confidence": 0.82,
                }
            ],
            "confidence": 0.82,
            "originality_risk": "MEDIUM",
            "knowledge_status": "NOT_ABSTRACTED",
        }

        self.assertEqual(
            validate_observation_payload(payload, evidence_spans=(span,)), payload
        )
        with self.assertRaises(KernelError) as leaked:
            validate_observation_payload(
                {
                    **payload,
                    "findings": [
                        {**payload["findings"][0], "raw_text": "protected prose"}
                    ],
                },
                evidence_spans=(span,),
            )
        self.assertEqual(leaked.exception.code, "DECONSTRUCTION_SOURCE_LEAKAGE_BLOCKED")


if __name__ == "__main__":
    unittest.main()
