from __future__ import annotations

import unittest
from dataclasses import replace

from novel_forge.modules.agent_collaboration import (
    CandidateVersion,
    InMemoryAgentCollaborationRepository,
)


class CandidateVersionGraphTests(unittest.TestCase):
    def test_multi_parent_lineage_is_deterministic_and_idempotent(self) -> None:
        repository = InMemoryAgentCollaborationRepository()
        one = _candidate("candidate:1", ())
        alternative = _candidate("candidate:alternative", ())
        merge = _candidate(
            "candidate:merge",
            ("candidate:1", "candidate:alternative"),
        )
        repository.save_candidate(one)
        repository.save_candidate(alternative)
        repository.save_candidate(merge)
        replay = repository.save_candidate(merge)

        self.assertEqual(replay, merge)
        self.assertEqual(
            repository.candidate_lineage("candidate:merge"),
            ("candidate:1", "candidate:alternative", "candidate:merge"),
        )

    def test_candidate_id_replay_with_different_content_fails_closed(self) -> None:
        repository = InMemoryAgentCollaborationRepository()
        repository.save_candidate(_candidate("candidate:1", ()))

        with self.assertRaisesRegex(ValueError, "different content"):
            repository.save_candidate(
                replace(
                    _candidate("candidate:1", ()),
                    content_ref="content:mutated",
                )
            )

    def test_parent_must_exist_and_cycles_cannot_be_introduced(self) -> None:
        repository = InMemoryAgentCollaborationRepository()

        with self.assertRaisesRegex(ValueError, "parent"):
            repository.save_candidate(
                _candidate("candidate:orphan", ("candidate:missing",))
            )


def _candidate(
    candidate_id: str,
    parents: tuple[str, ...],
) -> CandidateVersion:
    return CandidateVersion(
        candidate_version_id=candidate_id,
        session_id="session:1",
        candidate_type="BOOK_DESIGN_CORE_ADVANTAGE",
        parent_version_ids=parents,
        originating_message_id=f"message:{candidate_id}",
        originating_turn_id=f"turn:{candidate_id}",
        created_by_agent="character-design-agent",
        scope_snapshot_ref="scope:1",
        content_ref=f"content:{candidate_id}",
        structured_diff={"op": "create" if not parents else "merge"},
        change_reason_refs=("goal:core-advantage",),
        preserved_constraints=("ending unchanged",),
        resolved_conflicts=(),
        unresolved_conflicts=(),
        validation_status="VALID",
    )


if __name__ == "__main__":
    unittest.main()
