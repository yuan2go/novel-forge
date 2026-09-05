from __future__ import annotations

import hashlib
import json
import unittest

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.reader_calibration import (
    BLIND_EVALUATION_DIMENSIONS,
    BlindComparisonSubject,
    BlindEvaluator,
    BlindScope,
    CalibrationScope,
    EvaluatorIdentityClass,
    HumanBlindDecision,
    PreferenceChoice,
    export_blind_evaluation_packs,
)
from novel_forge.modules.reader_calibration.application import (
    PostgresReaderCalibrationAuthority,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    seed_authority_project_book,
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
        seed_authority_project_book(
            project_id=self.project_id,
            book_id=self.book_id,
            workspace_id=f"workspace:{self.project_id}",
        )
        self.draft_a = self._seed_asset("draft-a", "draft_version")
        self.draft_b = self._seed_asset("draft-b", "draft_version")
        self.manifest = self._seed_asset(
            "behavior-manifest", "calibration_input_manifest"
        )

    def test_versioned_two_reviewer_packs_persist_without_identity_leakage(
        self,
    ) -> None:
        campaign_id, subjects = self._seed_quality_campaign_and_subjects()
        task = self.authority.create_preference_task(
            project_id=self.project_id,
            workspace_id=f"workspace:{self.project_id}",
            book_id=self.book_id,
            reader_segment="bounded-editorial-panel",
            evidence_level="HUMAN_VERIFIED",
            idempotency_key=f"{self.project_id}:quality-preference:v1",
            campaign_id=campaign_id,
            protocol_version="human-blind-comparison-v1",
            evaluation_profile_version="editorial-pairwise-v1",
            required_evaluator_count=2,
            evaluator_identity_classes=(
                "PROFESSIONAL_EDITOR",
                "EXPERIENCED_READER",
            ),
            scope_manifest={"chapter_range": [1, 6], "arc_count": 1},
            principal=self.principal,
        )
        evaluators = (
            BlindEvaluator(
                "human-reviewer-1",
                EvaluatorIdentityClass.PROFESSIONAL_EDITOR,
            ),
            BlindEvaluator(
                "human-reviewer-2",
                EvaluatorIdentityClass.EXPERIENCED_READER,
            ),
        )
        bundle = export_blind_evaluation_packs(
            campaign_token="campaign:opaque-quality-v1",
            campaign_version=1,
            protocol_version="human-blind-comparison-v1",
            evaluation_version="editorial-pairwise-v1",
            campaign_secret="database-only-campaign-secret",
            evaluators=evaluators,
            subjects=subjects,
        )
        first_export = self.authority.register_blind_packs(
            task_id=task["task_id"], bundle=bundle, principal=self.principal
        )
        replay = self.authority.register_blind_packs(
            task_id=task["task_id"], bundle=bundle, principal=self.principal
        )
        self.assertEqual(first_export, replay)

        first_pack_id = first_export["human-reviewer-1"]["pack_id"]
        second_pack_id = first_export["human-reviewer-2"]["pack_id"]
        public = self.authority.reviewer_pack(
            pack_id=first_pack_id,
            reviewer_id="human-reviewer-1",
            principal=self.principal,
        )
        rendered = json.dumps(public, ensure_ascii=False).lower()
        self.assertNotIn("asset_version", rendered)
        self.assertNotIn("database-only-campaign-secret", rendered)
        self.assertNotIn("private_mapping", rendered)
        self.assertEqual(len(public["pairs"]), 7)
        with self.assertRaisesRegex(
            KernelError, "BLIND_PACK_REVIEWER_SCOPE_MISMATCH"
        ):
            self.authority.reviewer_pack(
                pack_id=first_pack_id,
                reviewer_id="human-reviewer-2",
                principal=self.principal,
            )

        first_mapping = bundle.packs["human-reviewer-1"].private_mapping[0]
        second_mapping = bundle.packs["human-reviewer-2"].private_mapping[0]
        score = {
            dimension: {"a": 4, "b": 3}
            for dimension in BLIND_EVALUATION_DIMENSIONS
        }
        first_decision = HumanBlindDecision(
            decision_id="external:decision:1",
            pair_token=first_mapping.pair_token,
            reviewer_id="human-reviewer-1",
            evaluator_identity_class=EvaluatorIdentityClass.PROFESSIONAL_EDITOR,
            protocol_version="human-blind-comparison-v1",
            evaluation_version="editorial-pairwise-v1",
            scope_type=BlindScope.CHAPTER,
            chapter_start=1,
            chapter_end=1,
            choice=PreferenceChoice.A,
            dimension_scores=score,
            confidence=0.8,
            rationale="The visible causal turn is more convincing.",
            evidence_spans=(),
        )
        second_decision = HumanBlindDecision(
            decision_id="external:decision:2",
            pair_token=second_mapping.pair_token,
            reviewer_id="human-reviewer-2",
            evaluator_identity_class=EvaluatorIdentityClass.EXPERIENCED_READER,
            protocol_version="human-blind-comparison-v1",
            evaluation_version="editorial-pairwise-v1",
            scope_type=BlindScope.CHAPTER,
            chapter_start=1,
            chapter_end=1,
            choice=PreferenceChoice.A,
            dimension_scores=score,
            confidence=0.7,
            rationale="The visible scene reads more clearly.",
            evidence_spans=(),
        )
        first_record = self.authority.record_blind_decision(
            first_decision, principal=self.principal
        )
        self.assertEqual(
            first_record,
            self.authority.record_blind_decision(
                first_decision, principal=self.principal
            ),
        )
        second_record = self.authority.record_blind_decision(
            second_decision, principal=self.principal
        )

        cannot_mapping = bundle.packs["human-reviewer-1"].private_mapping[1]
        cannot = HumanBlindDecision(
            decision_id="external:decision:cannot",
            pair_token=cannot_mapping.pair_token,
            reviewer_id="human-reviewer-1",
            evaluator_identity_class=EvaluatorIdentityClass.PROFESSIONAL_EDITOR,
            protocol_version="human-blind-comparison-v1",
            evaluation_version="editorial-pairwise-v1",
            scope_type=BlindScope.CHAPTER,
            chapter_start=2,
            chapter_end=2,
            choice=PreferenceChoice.CANNOT_JUDGE,
            dimension_scores={
                dimension: {"a": None, "b": None}
                for dimension in BLIND_EVALUATION_DIMENSIONS
            },
            confidence=0.1,
            rationale="The render is incomplete.",
            evidence_spans=(),
        )
        cannot_record = self.authority.record_blind_decision(
            cannot, principal=self.principal
        )
        self.assertEqual(cannot_record["choice"], "CANNOT_JUDGE")
        adjudication = self.authority.adjudicate_blind_subject(
            task_id=task["task_id"],
            subject_id=first_mapping.subject_id,
            adjudicator_id="independent-adjudicator",
            resolved_choice=PreferenceChoice.TIE,
            rationale="The disagreement is real and neither response is overwritten.",
            dimension_scores={},
            principal=self.principal,
        )
        self.assertEqual(adjudication["status"], "ADJUDICATED")
        self.assertEqual(adjudication["resolved_choice"], "TIE")
        self.assertCountEqual(
            adjudication["source_decision_ids"],
            [first_record["decision_id"], second_record["decision_id"]],
        )
        own = self.authority.reviewer_decisions(
            pack_id=first_pack_id,
            reviewer_id="human-reviewer-1",
            principal=self.principal,
        )
        self.assertEqual([item["choice"] for item in own], ["A", "CANNOT_JUDGE"])
        with self.assertRaisesRegex(
            KernelError, "BLIND_DECISION_REVIEWER_SCOPE_MISMATCH"
        ):
            self.authority.reviewer_decisions(
                pack_id=first_pack_id,
                reviewer_id="human-reviewer-2",
                principal=self.principal,
            )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM human_preference_evaluation_pack
                     WHERE task_id=%s),
                    (SELECT COUNT(*) FROM human_preference_pair
                     WHERE task_id=%s),
                    (SELECT COUNT(*) FROM human_preference_decision
                     WHERE decision_id=ANY(%s)),
                    (SELECT COUNT(*) FROM human_preference_adjudication
                     WHERE task_id=%s)
                """,
                [
                    task["task_id"],
                    task["task_id"],
                    [first_record["decision_id"], second_record["decision_id"]],
                    task["task_id"],
                ],
            )
            counts = tuple(int(value) for value in uow.cursor.fetchone())
        self.assertEqual(counts, (2, 14, 2, 1))
        self.assertNotEqual(first_pack_id, second_pack_id)

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

    def test_unbound_behavior_observations_and_historical_valid_profile_fail_closed(self) -> None:
        scope = CalibrationScope(
            "fixture-platform", "fantasy", "progression", "payoff", "segment:new-reader", "reader-judge-v1", "scripted-model-v1"
        )
        session = self.authority.start_reader_session(
            project_id=self.project_id, book_id=self.book_id, reader_subject_ref="pseudonym:fixture-reader",
            reader_segment=scope.reader_segment, platform=scope.platform, consent_policy_version="fixture-consent-v1",
            idempotency_key=f"{self.project_id}:lineage-session", principal=self.principal,
        )
        exposure = self.authority.record_exposure(
            reader_session_id=session["reader_session_id"], chapter_asset_version_id=self.draft_a,
            idempotency_key=f"{self.project_id}:lineage-exposure", principal=self.principal,
        )
        self.authority.record_outcome(
            exposure_id=exposure["exposure_id"], event_type="NEXT_CHAPTER_OPEN", event_value={"opened": True},
            idempotency_key=f"{self.project_id}:lineage-outcome", principal=self.principal,
        )
        self.assertEqual(self.authority._behavior_evidence_count(
            project_id=self.project_id, platform=scope.platform, reader_segment=scope.reader_segment
        ), 1)
        for _ in range(2):
            with self.assertRaisesRegex(KernelError, "READER_CALIBRATION_DATASET_LINEAGE_REQUIRED"):
                self.authority.run_calibration(
                    project_id=self.project_id, scope=scope, observations=[(0.9, 1)], minimum_sample_size=1,
                    input_manifest_version_id=self.manifest, evidence_level="BEHAVIOR_CALIBRATED",
                    idempotency_key=f"{self.project_id}:unbound-calibration", principal=self.principal,
                )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("SELECT count(*) FROM calibration_profile WHERE project_id=%s", [self.project_id])
            self.assertEqual(uow.cursor.fetchone()[0], 0)
        fixture = self.authority.run_calibration(
            project_id=self.project_id, scope=scope, observations=[(0.9, 1)], minimum_sample_size=1,
            input_manifest_version_id=self.manifest, evidence_level="FIXTURE",
            idempotency_key=f"{self.project_id}:fixture-calibration", principal=self.principal,
        )
        self.assertFalse(fixture["behavior_calibrated"])
        self.assertEqual(fixture["status"], "INSUFFICIENT_DATA")
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "UPDATE calibration_profile SET status='VALID', evidence_level='BEHAVIOR_CALIBRATED' WHERE profile_id=%s",
                [fixture["profile_id"]],
            )
            uow.commit()
        self.assertIsNone(self.authority.resolve_profile(self.project_id, scope))

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

    def _seed_quality_campaign_and_subjects(
        self,
    ) -> tuple[str, tuple[BlindComparisonSubject, ...]]:
        campaign_id = f"quality-campaign:{self.project_id}"
        manifest_version_id = self._seed_asset(
            "quality-campaign-manifest", "quality_qualification_manifest"
        )
        candidate_rows: list[tuple[str, BlindScope, int, int, str, str]] = []
        for chapter_number in range(1, 7):
            candidate_rows.append(
                (
                    f"{self.project_id}:subject:chapter:{chapter_number}",
                    BlindScope.CHAPTER,
                    chapter_number,
                    chapter_number,
                    self._seed_asset(
                        f"quality-canonical-chapter-{chapter_number}",
                        "best_draft_candidate",
                    ),
                    self._seed_asset(
                        f"quality-baseline-chapter-{chapter_number}",
                        "best_draft_candidate",
                    ),
                )
            )
        candidate_rows.append(
            (
                f"{self.project_id}:subject:arc:1-6",
                BlindScope.ARC,
                1,
                6,
                self._seed_asset(
                    "quality-canonical-arc-1-6", "arc_evaluation_text"
                ),
                self._seed_asset(
                    "quality-baseline-arc-1-6", "arc_evaluation_text"
                ),
            )
        )
        version_ids = [manifest_version_id]
        for _, _, _, _, canonical_id, baseline_id in candidate_rows:
            version_ids.extend((canonical_id, baseline_id))
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT created_by_operation_id
                FROM authority_project
                WHERE project_id=%s
                """,
                [self.project_id],
            )
            operation_id = str(uow.cursor.fetchone()[0])
            uow.cursor.execute(
                """
                SELECT asset_version_id, content_hash
                FROM authority_asset_version
                WHERE asset_version_id=ANY(%s)
                """,
                [version_ids],
            )
            content_hashes = {
                str(version_id): str(content_hash)
                for version_id, content_hash in uow.cursor.fetchall()
            }
            uow.cursor.execute(
                """
                INSERT INTO authority_quality_qualification_campaign(
                    campaign_id, project_id, workspace_id, book_id,
                    manifest_asset_version_id, manifest_hash,
                    exact_release_sha, migration_head, protocol_version,
                    evaluation_profile_version, quality_profile_version,
                    reader_outcome_profile_version, lifecycle,
                    qualification_status, human_evidence_status,
                    required_evaluator_count, chapter_start, chapter_end,
                    chapter_group_ranges, provider_route_manifest,
                    capability_pack_manifest, foundation_lineage,
                    planning_lineage, realization_lineage, context_policy,
                    budget_policy, stable_idempotency_key,
                    created_by_operation_id, frozen_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, 'FROZEN', NULL, 'NOT_STARTED', 2, 1, 6,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
                )
                """,
                [
                    campaign_id,
                    self.project_id,
                    f"workspace:{self.project_id}",
                    self.book_id,
                    manifest_version_id,
                    content_hashes[manifest_version_id],
                    "d" * 40,
                    "20260826_0101_quality_qualification",
                    "human-blind-comparison-v1",
                    "editorial-pairwise-v1",
                    "quality-evidence-v1",
                    "reader-outcome-v3",
                    Jsonb([[1, 3], [4, 6]]),
                    Jsonb({"provider": "scripted-fixture"}),
                    Jsonb({"pack": "fixture-pack", "hash": "sha256:fixture"}),
                    Jsonb({"foundation_set_version_id": "foundation:fixture:v1"}),
                    Jsonb({"book_plan_version_id": "book-plan:fixture:v1"}),
                    Jsonb({"realization_version": "narrative-realization-v1"}),
                    Jsonb({"policy_version": "context-manifest-v3"}),
                    Jsonb({"chapter_budget": 6, "provider_calls": 0}),
                    f"{self.project_id}:quality-campaign:v1",
                    operation_id,
                ],
            )
            for (
                subject_id,
                scope_type,
                chapter_start,
                chapter_end,
                canonical_id,
                baseline_id,
            ) in candidate_rows:
                arc_plan_ids = (
                    ["arc-plan:fixture:v1"]
                    if scope_type is BlindScope.ARC
                    else []
                )
                uow.cursor.execute(
                    """
                    INSERT INTO authority_quality_qualification_subject(
                        subject_id, campaign_id, project_id, scope_type,
                        scope_key, chapter_start, chapter_end,
                        arc_plan_version_ids, canonical_asset_version_id,
                        canonical_content_hash, baseline_asset_version_id,
                        baseline_content_hash, created_by_operation_id
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s
                    )
                    """,
                    [
                        subject_id,
                        campaign_id,
                        self.project_id,
                        scope_type.value,
                        f"{scope_type.value.lower()}:{chapter_start}:{chapter_end}",
                        chapter_start,
                        chapter_end,
                        Jsonb(arc_plan_ids),
                        canonical_id,
                        content_hashes[canonical_id],
                        baseline_id,
                        content_hashes[baseline_id],
                        operation_id,
                    ],
                )
            uow.commit()
        subjects = tuple(
            BlindComparisonSubject(
                subject_id=subject_id,
                scope_type=scope_type,
                chapter_start=chapter_start,
                chapter_end=chapter_end,
                canonical_asset_version_id=canonical_id,
                baseline_asset_version_id=baseline_id,
                canonical_text=(
                    f"Candidate text one for scope {chapter_start}-{chapter_end}."
                ),
                baseline_text=(
                    f"Candidate text two for scope {chapter_start}-{chapter_end}."
                ),
                arc_plan_version_ids=(
                    ("arc-plan:fixture:v1",)
                    if scope_type is BlindScope.ARC
                    else ()
                ),
            )
            for (
                subject_id,
                scope_type,
                chapter_start,
                chapter_end,
                canonical_id,
                baseline_id,
            ) in candidate_rows
        )
        return campaign_id, subjects

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
                    eligibility, governance, content, content_hash, schema_version
                ) VALUES (
                    %s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s, 'integration-fixture.v1'
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
