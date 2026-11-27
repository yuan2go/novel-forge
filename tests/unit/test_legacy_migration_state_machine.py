from __future__ import annotations

import unittest

from novel_forge.modules.legacy_migration.state_machine import (
    MigrationCompletionFacts,
    MigrationDomainState,
    MigrationRunCompletionLevel,
    MigrationRunStatus,
    MigrationPhase,
    MigrationPhaseCheckpoint,
    MigrationReferenceStatus,
    MigrationValidationScope,
    MigrationVerificationLevel,
    derive_migration_completion,
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

    def test_domain_pending_is_never_reported_as_domain_pass(self) -> None:
        completion = derive_migration_completion(
            MigrationCompletionFacts(
                archival_integrity=True,
                domain_native_count=3,
                domain_native_activated_count=1,
                pending_domain_native_count=2,
            ),
            required_level=MigrationVerificationLevel.DOMAIN_NATIVE,
        )

        self.assertEqual(completion.run_status, MigrationRunStatus.DOMAIN_ACTIVATION_PARTIAL)
        self.assertEqual(
            completion.completion_level,
            MigrationRunCompletionLevel.ARCHIVAL_RECONCILED,
        )
        self.assertFalse(completion.required_level_satisfied)

    def test_archival_and_domain_verification_levels_are_explicit(self) -> None:
        facts = MigrationCompletionFacts(
            archival_integrity=True,
            domain_native_count=2,
            domain_native_activated_count=0,
            pending_domain_native_count=2,
        )
        archival = derive_migration_completion(
            facts,
            required_level=MigrationVerificationLevel.ARCHIVAL_NATIVE,
        )
        release = derive_migration_completion(
            facts,
            required_level=MigrationVerificationLevel.RELEASE_READY,
        )

        self.assertEqual(archival.run_status, MigrationRunStatus.DOMAIN_REVIEW_PENDING)
        self.assertTrue(archival.required_level_satisfied)
        self.assertFalse(release.required_level_satisfied)

    def test_domain_failures_and_quarantine_fail_closed(self) -> None:
        failed = derive_migration_completion(
            MigrationCompletionFacts(
                archival_integrity=True,
                domain_native_count=1,
                domain_native_activated_count=1,
                domain_validation_failures=1,
            ),
            required_level=MigrationVerificationLevel.DOMAIN_NATIVE,
        )
        quarantined = derive_migration_completion(
            MigrationCompletionFacts(
                archival_integrity=True,
                quarantine_count=1,
            ),
            required_level=MigrationVerificationLevel.ARCHIVAL_NATIVE,
        )

        self.assertEqual(failed.run_status, MigrationRunStatus.FAILED)
        self.assertFalse(failed.required_level_satisfied)
        self.assertEqual(quarantined.run_status, MigrationRunStatus.QUARANTINED)
        self.assertFalse(quarantined.required_level_satisfied)

    def test_state_vocabularies_separate_archival_validation_and_domain_state(self) -> None:
        self.assertEqual(MigrationValidationScope.DOMAIN.value, "DOMAIN")
        self.assertEqual(
            MigrationDomainState.DOMAIN_VALIDATION_PENDING.value,
            "DOMAIN_VALIDATION_PENDING",
        )


if __name__ == "__main__":
    unittest.main()
