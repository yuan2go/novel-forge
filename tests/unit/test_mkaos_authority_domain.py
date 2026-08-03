from __future__ import annotations

import unittest
from decimal import Decimal

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority.domain import (
    KnowledgeEvidenceSpan,
    KnowledgePackSelection,
    validate_evidence_spans,
    validate_knowledge_candidate,
    validate_pack_selections,
)


class MkaosAuthorityDomainTests(unittest.TestCase):
    def test_candidate_requires_abstract_fields_and_blocks_source_expression(self) -> None:
        valid = {
            "concept_name": "Escalating obligation",
            "discipline": "organizational behavior",
            "abstract_principle": "A favor becomes costly when repayment criteria move.",
            "constraints": ["Every escalation must expose a changed obligation."],
            "conflict_generators": ["The beneficiary disputes what repayment means."],
            "review_checks": ["Check that no source-specific proper noun remains."],
            "copyright_boundaries": ["Mechanism only; no protected expression."],
        }
        self.assertEqual(validate_knowledge_candidate(valid), valid)

        with self.assertRaises(KernelError) as caught:
            validate_knowledge_candidate({**valid, "raw_text": "forbidden source prose"})
        self.assertEqual(caught.exception.code, "MKAOS_SOURCE_LEAKAGE_BLOCKED")

    def test_evidence_is_deterministic_unique_and_in_bounds(self) -> None:
        first = KnowledgeEvidenceSpan("chunk:v1", 0, 20, "sha256:" + "a" * 64)
        second = KnowledgeEvidenceSpan("chunk:v1", 30, 50, "sha256:" + "b" * 64)
        self.assertEqual(
            validate_evidence_spans(
                (second, first), source_chunk_sizes={"chunk:v1": 50}
            ),
            (first, second),
        )
        with self.assertRaises(KernelError) as caught:
            validate_evidence_spans(
                (KnowledgeEvidenceSpan("chunk:v1", 0, 51, "sha256:" + "c" * 64),),
                source_chunk_sizes={"chunk:v1": 50},
            )
        self.assertEqual(caught.exception.code, "MKAOS_EVIDENCE_OUT_OF_BOUNDS")

    def test_pack_selection_freezes_roles_weights_and_rejects_duplicates(self) -> None:
        selection = KnowledgePackSelection("card:v1", "constraint", Decimal("1.5"))
        self.assertEqual(selection.usage_role, "CONSTRAINT")
        with self.assertRaises(KernelError) as caught:
            validate_pack_selections((selection, selection))
        self.assertEqual(caught.exception.code, "MKAOS_PACK_SELECTION_DUPLICATE")


if __name__ == "__main__":
    unittest.main()
