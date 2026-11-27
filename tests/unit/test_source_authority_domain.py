from __future__ import annotations

import unittest
from dataclasses import replace

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.source_authority import (
    SourceChunkCandidate,
    decide_source_governance,
    validate_source_chunk_candidates,
)


class SourceAuthorityDomainTests(unittest.TestCase):
    def test_owned_source_is_analysis_eligible_but_never_raw_context_eligible(self) -> None:
        decision = decide_source_governance(
            authorization="owned", license_name="", copyright_boundary=""
        )

        self.assertEqual(
            (decision.lifecycle, decision.eligibility, decision.governance),
            ("ACTIVE", "ELIGIBLE", "CLEAR"),
        )
        self.assertTrue(decision.analysis_allowed)
        self.assertFalse(decision.generation_context_allowed)

    def test_unknown_and_forbidden_sources_fail_closed(self) -> None:
        unknown = decide_source_governance(
            authorization="unknown", license_name="", copyright_boundary=""
        )
        forbidden = decide_source_governance(
            authorization="pirated", license_name="", copyright_boundary=""
        )

        self.assertEqual(
            (unknown.lifecycle, unknown.eligibility, unknown.governance_status),
            ("CANDIDATE", "PENDING_EVALUATION", "NEEDS_REVIEW"),
        )
        self.assertEqual(
            (forbidden.lifecycle, forbidden.eligibility, forbidden.governance),
            ("CANDIDATE", "INELIGIBLE", "QUARANTINED"),
        )

    def test_license_and_copyright_evidence_are_required(self) -> None:
        with self.assertRaisesRegex(KernelError, "license"):
            decide_source_governance(
                authorization="licensed",
                license_name="",
                copyright_boundary="licensed analysis only",
            )
        with self.assertRaisesRegex(KernelError, "copyright boundary"):
            decide_source_governance(
                authorization="public_domain",
                license_name="",
                copyright_boundary="",
            )

    def test_chunk_manifest_requires_contiguous_bounded_blob_evidence(self) -> None:
        chunks = (
            SourceChunkCandidate(
                chunk_index=0,
                blob_id="blob-0",
                content_hash="sha256:" + "a" * 64,
                byte_size=80,
                character_count=40,
                token_count=20,
                source_byte_start=0,
                source_byte_end=100,
            ),
            SourceChunkCandidate(
                chunk_index=1,
                blob_id="blob-1",
                content_hash="sha256:" + "b" * 64,
                byte_size=70,
                character_count=35,
                token_count=18,
                source_byte_start=100,
                source_byte_end=200,
            ),
        )

        self.assertEqual(
            validate_source_chunk_candidates(chunks, source_size=200), chunks
        )
        with self.assertRaises(KernelError) as caught:
            validate_source_chunk_candidates(
                (
                    replace(
                        chunks[1],
                        chunk_index=0,
                        source_byte_start=150,
                        source_byte_end=100,
                    ),
                ),
                source_size=200,
            )
        self.assertEqual(caught.exception.code, "SOURCE_CHUNK_SPAN_INVALID")


if __name__ == "__main__":
    unittest.main()
