from __future__ import annotations

import unittest

from novel_forge.modules.legacy_migration.state_machine import (
    MigrationPhase,
    MigrationPhaseCheckpoint,
    MigrationReferenceStatus,
    require_phase_transition,
)


class LegacyMigrationStateMachineTests(unittest.TestCase):
    def test_happy_path_and_archival_review_path_are_legal(self) -> None:
        path = (
            MigrationPhase.SCAN,
            MigrationPhase.CLASSIFY,
            MigrationPhase.IMPORT_CANDIDATE,
            MigrationPhase.SEMANTIC_CONVERT,
            MigrationPhase.VALIDATE,
            MigrationPhase.QUALIFY,
            MigrationPhase.ACTIVATE,
            MigrationPhase.RECONCILE,
            MigrationPhase.COMPLETE,
        )
        for source, target in zip(path, path[1:]):
            require_phase_transition(source, target)
        require_phase_transition(MigrationPhase.QUALIFY, MigrationPhase.RECONCILE)

    def test_illegal_phase_jump_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "SCAN->ACTIVATE"):
            require_phase_transition(MigrationPhase.SCAN, MigrationPhase.ACTIVATE)
        with self.assertRaisesRegex(ValueError, "COMPLETE->SCAN"):
            require_phase_transition(MigrationPhase.COMPLETE, MigrationPhase.SCAN)

    def test_checkpoint_hash_covers_required_resume_identity(self) -> None:
        first = MigrationPhaseCheckpoint(
            migration_run_id="run-1",
            item_id="item-1",
            phase=MigrationPhase.VALIDATE,
            source_hash="sha256:" + "a" * 64,
            target_identity="project-1:book_plan:plan-1",
            reference_state=MigrationReferenceStatus.RESOLVED,
            counts={"references": 2, "attempt": 1},
        )
        replay = MigrationPhaseCheckpoint(
            migration_run_id="run-1",
            item_id="item-1",
            phase=MigrationPhase.VALIDATE,
            source_hash="sha256:" + "a" * 64,
            target_identity="project-1:book_plan:plan-1",
            reference_state=MigrationReferenceStatus.RESOLVED,
            counts={"attempt": 1, "references": 2},
        )
        changed = MigrationPhaseCheckpoint(
            migration_run_id="run-1",
            item_id="item-1",
            phase=MigrationPhase.VALIDATE,
            source_hash="sha256:" + "a" * 64,
            target_identity="project-1:book_plan:plan-1",
            reference_state=MigrationReferenceStatus.CONFLICT,
            counts={"attempt": 1, "references": 2},
        )
        self.assertEqual(first.checkpoint_hash, replay.checkpoint_hash)
        self.assertNotEqual(first.checkpoint_hash, changed.checkpoint_hash)


if __name__ == "__main__":
    unittest.main()
