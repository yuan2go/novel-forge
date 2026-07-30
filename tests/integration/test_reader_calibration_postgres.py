from __future__ import annotations

import hashlib
import json
import unittest

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.reader_calibration import (
    CalibrationScope,
    PostgresReaderCalibrationAuthority,
    PreferenceChoice,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
)


class ReaderCalibrationPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def setUp(self) -> None:
        self.project_id = identifier("reader-calibration")
        self.book_id = f"book:{self.project_id}"
        self.principal = Principal(
            principal_id="reader-calibration-authority",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset({"book.authority.execute"}),
            project_scope=frozenset({self.project_id}),
            authentication_source="integration-test",
        )
        self.authority = PostgresReaderCalibrationAuthority(
            DATABASE_URL,
            application_build_id="reader-calibration-integration",
            commit_sha="c" * 40,
        )
        self.draft_a = self._seed_asset("draft-a", "draft_version")
        self.draft_b = self._seed_asset("draft-b", "draft_version")
        self.manifest = self._seed_asset(
            "behavior-manifest", "calibration_input_manifest"
        )

    def test_human_preference_vertical_is_blind_and_fixture_not_anchored(
        self,
    ) -> None:
        task = self.authority.create_preference_task(
            project_id=self.project_id,
            workspace_id=f"workspace:{self.project_id}",
            book_id=self.book_id,
            reader_segment="segment:new-reader",
            evidence_level="FIXTURE",
            idempotency_key=f"{self.project_id}:preference-task:1",
            principal=self.principal,
        )
        pair = self.authority.add_blind_pair(
            task_id=task["task_id"],
            asset_a_version_id=self.draft_a,
            asset_b_version_id=self.draft_b,
            randomization_key=f"{task['task_id']}:ab",
            principal=self.principal,
        )
        reversed_pair = self.authority.add_blind_pair(
            task_id=task["task_id"],
            asset_a_version_id=self.draft_a,
            asset_b_version_id=self.draft_b,
            randomization_key=f"{task['task_id']}:ba",
            reversal_of_pair_id=pair["pair_id"],
            principal=self.principal,
        )
        self.assertTrue(pair["pair_id"])
        self.assertNotEqual(
            pair["presentation_order"],
            reversed_pair["presentation_order"],
        )
        self.assertEqual(
            pair["left_asset_version_id"],
            reversed_pair["right_asset_version_id"],
        )
        for current in (pair, reversed_pair):
            for reviewer, group in (
                ("editor:fixture", "EDITOR"),
                ("reader:fixture", "READER"),
            ):
                self.authority.record_preference_decision(
                    pair_id=current["pair_id"],
                    reviewer_id=reviewer,
                    reviewer_group=group,
                    choice=PreferenceChoice.A,
                    evidence_spans=[{"start": 0, "end": 12}],
                    confidence=0.8,
                    annotation_reason="fixture protocol coverage",
                    principal=self.principal,
                )
        report = self.authority.build_agreement_report(
            task["task_id"], principal=self.principal
        )
        self.assertEqual(report["agreement_rate"], 1.0)
        self.assertEqual(report["reversal_pair_count"], 1)
        self.assertFalse(report["human_preference_anchored"])
        self.assertTrue(report["report_asset_version_id"])

    def test_behavior_event_requires_exposure_and_is_project_segment_scoped(
        self,
    ) -> None:
        session = self.authority.start_reader_session(
            project_id=self.project_id,
            book_id=self.book_id,
            reader_subject_ref="pseudonym:fixture-reader",
            reader_segment="segment:new-reader",
            platform="fixture-platform",
            consent_policy_version="fixture-consent-v1",
            idempotency_key=f"{self.project_id}:session:1",
            principal=self.principal,
        )
        with self.assertRaisesRegex(
            KernelError, "READER_EXPOSURE_REQUIRED"
        ):
            self.authority.record_outcome(
                exposure_id="missing-exposure",
                event_type="COMPLETION",
                event_value={"completed": True},
                idempotency_key=f"{self.project_id}:outcome:missing",
                principal=self.principal,
            )
        exposure = self.authority.record_exposure(
            reader_session_id=session["reader_session_id"],
            chapter_asset_version_id=self.draft_a,
            idempotency_key=f"{self.project_id}:exposure:1",
            principal=self.principal,
        )
        event = self.authority.record_outcome(
            exposure_id=exposure["exposure_id"],
            event_type="NEXT_CHAPTER_OPEN",
            event_value={"opened": True},
            idempotency_key=f"{self.project_id}:outcome:1",
            principal=self.principal,
        )
        self.assertEqual(event["project_id"], self.project_id)
        self.assertEqual(event["reader_segment"], "segment:new-reader")
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT outcome.project_id, outcome.reader_segment,
                       exposure.project_id, exposure.reader_segment,
                       exposure.denominator_eligible
                FROM reader_outcome_event AS outcome
                JOIN reader_exposure AS exposure
                  ON exposure.exposure_id=outcome.exposure_id
                WHERE outcome.outcome_event_id=%s
                """,
                [event["outcome_event_id"]],
            )
            row = uow.cursor.fetchone()
        self.assertEqual(
            tuple(row),
            (
                self.project_id,
                "segment:new-reader",
                self.project_id,
                "segment:new-reader",
                True,
            ),
        )

    def test_fixture_calibration_remains_shadow_and_drift_is_fail_closed(
        self,
    ) -> None:
        scope = CalibrationScope(
            platform="fixture-platform",
            genre="fantasy",
            subgenre="progression",
            chapter_type="payoff",
            reader_segment="segment:new-reader",
            judge_profile="reader-judge-v1",
            model_version="scripted-model-v1",
        )
        result = self.authority.run_calibration(
            project_id=self.project_id,
            scope=scope,
            observations=[(0.8, 1), (0.3, 0)],
            minimum_sample_size=50,
            input_manifest_version_id=self.manifest,
            evidence_level="FIXTURE",
            idempotency_key=f"{self.project_id}:calibration:1",
            principal=self.principal,
        )
        self.assertEqual(result["status"], "INSUFFICIENT_DATA")
        self.assertEqual(result["judge_mode"], "SHADOW")
        self.assertFalse(result["behavior_calibrated"])
        self.assertIsNone(
            self.authority.resolve_profile(self.project_id, scope)
        )
        drifted = self.authority.record_drift(
            profile_id=result["profile_id"],
            drift_type="BEHAVIOR",
            severity="SEVERE",
            evidence={
                "fixture_protocol_only": True,
                "production_verified": False,
            },
            principal=self.principal,
        )
        self.assertEqual(drifted["status"], "DRIFTED")
        self.assertEqual(drifted["judge_mode"], "SHADOW")

    def _seed_asset(self, label: str, asset_type: str) -> str:
        asset_id = f"{self.project_id}:{label}:asset"
        version_id = f"{self.project_id}:{label}:v1"
        content = {
            "type": asset_type,
            "fixture_protocol_only": True,
            "production_verified": False,
        }
        content_hash = "sha256:" + hashlib.sha256(
            json.dumps(
                content, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_asset(asset_id, project_id, asset_type)
                VALUES (%s, %s, %s)
                """,
                [asset_id, self.project_id, asset_type],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id, asset_id, version_number, lifecycle,
                    eligibility, governance, content, content_hash
                ) VALUES (
                    %s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s
                )
                """,
                [version_id, asset_id, json.dumps(content), content_hash],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_qualification(
                    qualification_id, asset_version_id, policy_version,
                    decision, evidence
                ) VALUES (%s, %s, 'reader-calibration-fixture-v1',
                          'ELIGIBLE', '{}'::jsonb)
                """,
                [f"{version_id}:qualification", version_id],
            )
            uow.commit()
        return version_id


if __name__ == "__main__":
    unittest.main()
