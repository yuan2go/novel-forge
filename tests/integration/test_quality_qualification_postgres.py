from __future__ import annotations

import hashlib
import json

import pytest

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.chapter_quality_authority import (
    EvidenceLayer,
    EvidenceSeverity,
    EvidenceStatus,
    QualityCampaignManifest,
)
from novel_forge.modules.chapter_quality_authority.qualification_application import (
    PostgresQualityQualificationAuthority,
    QualityArtifactMaterializationCommand,
    QualityEvidenceBindingCommand,
    QualitySubjectBindingCommand,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    seed_authority_project_book,
)


RELEASE_SHA = "d" * 40


def _manifest(project_id: str, workspace_id: str, book_id: str) -> dict[str, object]:
    return {
        "schema_version": "novel-forge.quality-qualification.v1",
        "campaign_id": f"quality-campaign:{project_id}",
        "campaign_version": 1,
        "exact_release_sha": RELEASE_SHA,
        "migration_head": "20260826_0101_quality_qualification",
        "protocol_version": "human-blind-comparison-v1",
        "evaluation_profile_version": "editorial-pairwise-v1",
        "quality_profile_version": "canonical-quality-v3",
        "reader_outcome_profile_version": "reader-outcome-v3",
        "project_id": project_id,
        "workspace_id": workspace_id,
        "book_id": book_id,
        "chapter_group_ranges": [[1, 4], [5, 8]],
        "provider_route_manifest": {
            "generator": {"provider": "scripted", "model": "fixture-generator"},
            "reviewer": {"provider": "scripted", "model": "fixture-reviewer"},
            "judge": {"provider": "scripted", "model": "fixture-judge"},
        },
        "capability_pack_manifest": {"draft": "sha256:" + "1" * 64},
        "prompt_skill_lineage": {"draft_prompt": "sha256:" + "2" * 64},
        "foundation_lineage": {"qualified_foundation_set": "foundation:v1"},
        "planning_lineage": {"book_plan": "book-plan:v1", "arcs": ["arc:v1"]},
        "realization_lineage": {"contract": "realization:v1"},
        "context_policy": {"contract": "context-manifest-v3"},
        "baseline_protocol": {
            "kind": "FIRST_DRAFT_VS_ACCEPTED_REVISION",
            "shared_story_foundation": True,
            "shared_chapter_goal": True,
            "provider_model_parity": True,
            "controlled_difference": "REVIEW_REVISION_REREVIEW",
        },
        "budget_policy": {
            "chapter_limit": 8,
            "token_limit": 200_000,
            "cost_limit_usd": "100.00",
        },
        "required_evaluator_count": 2,
    }


class TestQualityQualificationPostgres:
    @classmethod
    def setup_class(cls) -> None:
        ensure_migrated()

    def setup_method(self) -> None:
        self.project_id = identifier("quality-qualification")
        self.workspace_id = f"workspace:{self.project_id}"
        self.book_id = f"book:{self.project_id}"
        seed_authority_project_book(
            project_id=self.project_id,
            workspace_id=self.workspace_id,
            book_id=self.book_id,
        )
        self.principal = Principal(
            principal_id="quality-operator",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset(
                {
                    "quality.qualification.manage",
                    "quality.qualification.query",
                    "book.authority.execute",
                }
            ),
            project_scope=frozenset({self.project_id}),
            authentication_source="integration-test",
        )
        self.app = PostgresQualityQualificationAuthority(
            DATABASE_URL,
            application_build_id="quality-qualification-integration",
            commit_sha=RELEASE_SHA,
        )

    def _asset(self, asset_type: str, label: str, content: dict) -> dict[str, str]:
        encoded = json.dumps(content, sort_keys=True, separators=(",", ":"))
        content_hash = "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()
        asset_id = f"asset:{self.project_id}:{label}"
        version_id = f"{asset_id}:v1"
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "INSERT INTO authority_asset(asset_id, project_id, asset_type) VALUES (%s,%s,%s)",
                [asset_id, self.project_id, asset_type],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id, asset_id, version_number, lifecycle,
                    eligibility, governance, content, content_hash, schema_version
                ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,'quality-fixture.v1')
                """,
                [version_id, asset_id, json.dumps(content), content_hash],
            )
            uow.commit()
        return {"asset_version_id": version_id, "content_hash": content_hash}

    def test_campaign_subject_evidence_and_waiting_decision_are_idempotent(
        self,
    ) -> None:
        manifest = QualityCampaignManifest.from_mapping(
            _manifest(self.project_id, self.workspace_id, self.book_id)
        )
        admitted = self.app.admit_campaign(
            manifest,
            stable_idempotency_key=f"{self.project_id}:quality:v1",
            trace_id=f"trace:{self.project_id}",
            correlation_id=f"correlation:{self.project_id}",
            principal=self.principal,
        )
        replay = self.app.admit_campaign(
            manifest,
            stable_idempotency_key=f"{self.project_id}:quality:v1",
            trace_id=f"trace:{self.project_id}",
            correlation_id=f"correlation:{self.project_id}",
            principal=self.principal,
        )
        assert replay == admitted
        assert admitted["manifest_hash"] == manifest.digest
        assert admitted["lifecycle"] == "DRAFT"
        frozen_manifest = manifest.to_dict()
        assert (
            admitted["provider_route_manifest"]
            == frozen_manifest["provider_route_manifest"]
        )
        assert (
            admitted["capability_pack_manifest"]
            == frozen_manifest["capability_pack_manifest"]
        )
        assert admitted["foundation_lineage"] == frozen_manifest["foundation_lineage"]
        assert admitted["planning_lineage"] == frozen_manifest["planning_lineage"]
        assert admitted["realization_lineage"] == frozen_manifest["realization_lineage"]
        assert admitted["context_policy"] == frozen_manifest["context_policy"]
        assert admitted["budget_policy"] == frozen_manifest["budget_policy"]

        frozen = self.app.freeze_campaign(
            manifest.campaign_id, expected_version=0, principal=self.principal
        )
        started = self.app.start_campaign(
            manifest.campaign_id, expected_version=1, principal=self.principal
        )
        assert frozen["lifecycle"] == "FROZEN"
        assert started["lifecycle"] == "RUNNING"

        baseline = self._asset("draft_version", "baseline-1", {"text": "first"})
        canonical = self._asset("draft_version", "canonical-1", {"text": "revised"})
        subject = self.app.bind_subject(
            QualitySubjectBindingCommand(
                campaign_id=manifest.campaign_id,
                subject_id=f"subject:{self.project_id}:chapter:1",
                scope_type="CHAPTER",
                scope_key="chapter:1",
                chapter_start=1,
                chapter_end=1,
                arc_plan_version_ids=(),
                canonical_asset_version_id=canonical["asset_version_id"],
                canonical_content_hash=canonical["content_hash"],
                baseline_asset_version_id=baseline["asset_version_id"],
                baseline_content_hash=baseline["content_hash"],
            ),
            principal=self.principal,
        )
        assert subject["scope_type"] == "CHAPTER"

        for layer in EvidenceLayer:
            evidence_asset = self._asset(
                "quality_qualification_evidence",
                layer.value.lower(),
                {"layer": layer.value, "status": "PASS"},
            )
            recorded = self.app.bind_evidence(
                QualityEvidenceBindingCommand(
                    campaign_id=manifest.campaign_id,
                    evidence_id=f"evidence:{self.project_id}:{layer.value}",
                    subject_id=subject["subject_id"],
                    evidence_layer=layer,
                    evidence_type=f"{layer.value}.SUMMARY",
                    evidence_asset_version_id=evidence_asset["asset_version_id"],
                    evidence_content_hash=evidence_asset["content_hash"],
                    status=EvidenceStatus.PASS,
                    severity=EvidenceSeverity.INFO,
                    source_asset_version_ids=(canonical["asset_version_id"],),
                    evaluator_lineage={"execution_class": "SCRIPTED_FIXTURE"},
                    provider_lineage={"provider": "scripted"},
                ),
                principal=self.principal,
            )
            assert recorded["evidence_layer"] == layer.value

        decision = self.app.evaluate_campaign(
            manifest.campaign_id,
            human_collection_closed=False,
            principal=self.principal,
        )
        decision_replay = self.app.evaluate_campaign(
            manifest.campaign_id,
            human_collection_closed=False,
            principal=self.principal,
        )
        assert decision_replay == decision
        assert decision["qualification_status"] == "NOT_PROVEN"
        assert decision["campaign_lifecycle"] == "WAITING_HUMAN_EVIDENCE"
        assert decision["human_evidence_status"] == "WAITING_HUMAN_EVIDENCE"
        assert decision["human_evaluator_ids"] == []
        assert decision["human_subjectivity_is_ground_truth"] is False
        assert decision["bounded_evidence_only"] is True
        assert decision["decision_version"] == 1

        campaign = self.app.require_campaign(
            manifest.campaign_id, principal=self.principal
        )
        assert campaign["lifecycle"] == "WAITING_HUMAN_EVIDENCE"
        assert campaign["qualification_status"] == "NOT_PROVEN"
        assert len(campaign["subjects"]) == 1
        assert len(campaign["evidence"]) == 3
        assert campaign["current_decision"]["decision_version"] == 1
        assert campaign["blind_pack_status"]["exported_count"] == 0
        resumed = self.app.resume_campaign(
            manifest.campaign_id,
            expected_version=3,
            principal=self.principal,
        )
        assert resumed["lifecycle"] == "WAITING_HUMAN_EVIDENCE"
        assert resumed["resume_status"] == "WAITING_HUMAN_EVIDENCE"

        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(*),
                       COUNT(*) FILTER (
                         WHERE definition_name <>
                               'quality.qualification.campaign.admit'
                           AND jsonb_array_length(input_asset_snapshot)=0
                       ),
                       COUNT(*) FILTER (
                         WHERE definition_name=
                               'quality.qualification.campaign.admit'
                           AND command_payload->'payload'->'manifest'->>
                               'campaign_id'=%s
                       )
                FROM authority_operation
                WHERE project_id=%s
                  AND definition_name LIKE 'quality.qualification.%%'
                """,
                [manifest.campaign_id, self.project_id],
            )
            operation_evidence = uow.cursor.fetchone()
        assert tuple(int(value) for value in operation_evidence) == (9, 0, 1)

    def test_terminal_runtime_failure_is_not_recast_as_narrative_failure(
        self,
    ) -> None:
        manifest = QualityCampaignManifest.from_mapping(
            _manifest(self.project_id, self.workspace_id, self.book_id)
        )
        self.app.admit_campaign(
            manifest,
            stable_idempotency_key=f"{self.project_id}:terminal:v1",
            trace_id=f"trace:{self.project_id}:terminal",
            correlation_id=f"correlation:{self.project_id}:terminal",
            principal=self.principal,
        )
        self.app.freeze_campaign(
            manifest.campaign_id,
            expected_version=0,
            principal=self.principal,
        )
        self.app.start_campaign(
            manifest.campaign_id,
            expected_version=1,
            principal=self.principal,
        )
        source = self._asset(
            "model_call_log",
            "terminal-budget-source",
            {"measured_total_tokens": 1_566_433},
        )

        decision = self.app.record_terminal_failure(
            manifest.campaign_id,
            expected_version=2,
            failure_code="CAMPAIGN_BUDGET_OR_LINEAGE_BREACH",
            reasons=("measured_total_tokens>token_limit",),
            measurements={
                "measured_total_tokens": 1_566_433,
                "token_limit": 1_020_000,
            },
            source_asset_version_ids=(source["asset_version_id"],),
            principal=self.principal,
        )
        replay = self.app.record_terminal_failure(
            manifest.campaign_id,
            expected_version=2,
            failure_code="CAMPAIGN_BUDGET_OR_LINEAGE_BREACH",
            reasons=("measured_total_tokens>token_limit",),
            measurements={
                "measured_total_tokens": 1_566_433,
                "token_limit": 1_020_000,
            },
            source_asset_version_ids=(source["asset_version_id"],),
            principal=self.principal,
        )

        assert replay == decision
        assert decision["qualification_status"] == "FAIL"
        assert decision["campaign_lifecycle"] == "FAILED"
        assert decision["hard_correctness_status"] == "NOT_PROVEN"
        assert decision["editorial_quality_status"] == "NOT_PROVEN"
        assert decision["reader_longitudinal_status"] == "NOT_PROVEN"
        assert "ENGINEERING_QUALIFICATION_FAILURE" in decision["limitations"]
        campaign = self.app.require_campaign(
            manifest.campaign_id,
            principal=self.principal,
        )
        assert campaign["lifecycle"] == "FAILED"
        assert campaign["qualification_status"] == "FAIL"
        assert campaign["human_evidence_status"] == "WAITING_HUMAN_EVIDENCE"
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT definition_name,definition_version
                FROM authority_operation
                WHERE project_id=%s
                  AND definition_name='quality.qualification.campaign.fail'
                """,
                [self.project_id],
            )
            terminal_operation = uow.cursor.fetchone()
        assert terminal_operation == (
            "quality.qualification.campaign.fail",
            "1.1.0",
        )

    def test_materialized_comparison_artifact_is_source_bound_and_bounded(
        self,
    ) -> None:
        manifest = QualityCampaignManifest.from_mapping(
            _manifest(self.project_id, self.workspace_id, self.book_id)
        )
        self.app.admit_campaign(
            manifest,
            stable_idempotency_key=f"{self.project_id}:materialize:v1",
            trace_id=f"trace:{self.project_id}:materialize",
            correlation_id=f"correlation:{self.project_id}:materialize",
            principal=self.principal,
        )
        self.app.freeze_campaign(
            manifest.campaign_id,
            expected_version=0,
            principal=self.principal,
        )
        self.app.start_campaign(
            manifest.campaign_id,
            expected_version=1,
            principal=self.principal,
        )
        source = self._asset("draft_version", "materialize-source", {"text": "one"})
        command = QualityArtifactMaterializationCommand(
            campaign_id=manifest.campaign_id,
            artifact_id="comparison:chapter:1:baseline",
            artifact_kind="COMPARISON_CANDIDATE",
            scope_type="CHAPTER",
            chapter_start=1,
            chapter_end=1,
            content={"candidate_role": "BASELINE", "text": "one"},
            source_asset_version_ids=(source["asset_version_id"],),
        )

        materialized = self.app.materialize_artifact(command, principal=self.principal)
        replay = self.app.materialize_artifact(command, principal=self.principal)

        assert replay == materialized
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT version.content, operation.input_asset_snapshot
                FROM authority_asset_version AS version
                JOIN authority_operation_output_asset AS binding
                  ON binding.asset_version_id=version.asset_version_id
                JOIN authority_operation AS operation
                  ON operation.operation_id=binding.operation_id
                WHERE version.asset_version_id=%s
                """,
                [materialized["asset_version_id"]],
            )
            content, input_snapshot = uow.cursor.fetchone()
        assert content["accepted_history_only"] is True
        assert content["candidate_role"] == "BASELINE"
        assert [item["asset_version_id"] for item in input_snapshot] == [
            source["asset_version_id"]
        ]

        with pytest.raises(ValueError, match="scope or content"):
            self.app.materialize_artifact(
                QualityArtifactMaterializationCommand(
                    campaign_id=manifest.campaign_id,
                    artifact_id="comparison:chapter:9:baseline",
                    artifact_kind="COMPARISON_CANDIDATE",
                    scope_type="CHAPTER",
                    chapter_start=9,
                    chapter_end=9,
                    content={"candidate_role": "BASELINE", "text": "nine"},
                    source_asset_version_ids=(source["asset_version_id"],),
                ),
                principal=self.principal,
            )

    def test_post_asset_failure_recovers_without_duplicate_campaign_or_output(
        self,
    ) -> None:
        manifest = QualityCampaignManifest.from_mapping(
            _manifest(self.project_id, self.workspace_id, self.book_id)
        )
        failures = {"remaining": 1}

        def inject(stage: str) -> None:
            if stage == "after_campaign_asset" and failures["remaining"]:
                failures["remaining"] -= 1
                raise RuntimeError("injected after campaign asset")

        interrupted = PostgresQualityQualificationAuthority(
            DATABASE_URL,
            application_build_id="quality-qualification-integration",
            commit_sha=RELEASE_SHA,
            failure_injector=inject,
        )
        with pytest.raises(RuntimeError, match="after campaign asset"):
            interrupted.admit_campaign(
                manifest,
                stable_idempotency_key=f"{self.project_id}:recovery:v1",
                trace_id=f"trace:{self.project_id}:recovery",
                correlation_id=f"correlation:{self.project_id}:recovery",
                principal=self.principal,
            )

        recovered = self.app.admit_campaign(
            manifest,
            stable_idempotency_key=f"{self.project_id}:recovery:v1",
            trace_id=f"trace:{self.project_id}:recovery",
            correlation_id=f"correlation:{self.project_id}:recovery",
            principal=self.principal,
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_quality_qualification_campaign
                WHERE campaign_id=%s
                """,
                [manifest.campaign_id],
            )
            campaign_count = int(uow.cursor.fetchone()[0])
            uow.cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_operation_output_asset
                WHERE operation_id=%s
                  AND output_key='quality.qualification.manifest'
                """,
                [recovered["created_by_operation_id"]],
            )
            output_count = int(uow.cursor.fetchone()[0])
        assert campaign_count == 1
        assert output_count == 1

    def test_subject_evidence_and_decision_recover_after_asset_commit(self) -> None:
        manifest = QualityCampaignManifest.from_mapping(
            _manifest(self.project_id, self.workspace_id, self.book_id)
        )
        self.app.admit_campaign(
            manifest,
            stable_idempotency_key=f"{self.project_id}:projection-recovery:v1",
            trace_id=f"trace:{self.project_id}:projection-recovery",
            correlation_id=f"correlation:{self.project_id}:projection-recovery",
            principal=self.principal,
        )
        self.app.freeze_campaign(
            manifest.campaign_id,
            expected_version=0,
            principal=self.principal,
        )
        self.app.start_campaign(
            manifest.campaign_id,
            expected_version=1,
            principal=self.principal,
        )

        baseline = self._asset("draft_version", "recovery-baseline", {"text": "first"})
        canonical = self._asset(
            "draft_version", "recovery-canonical", {"text": "revised"}
        )
        subject_command = QualitySubjectBindingCommand(
            campaign_id=manifest.campaign_id,
            subject_id=f"subject:{self.project_id}:chapter:1",
            scope_type="CHAPTER",
            scope_key="chapter:1",
            chapter_start=1,
            chapter_end=1,
            arc_plan_version_ids=(),
            canonical_asset_version_id=canonical["asset_version_id"],
            canonical_content_hash=canonical["content_hash"],
            baseline_asset_version_id=baseline["asset_version_id"],
            baseline_content_hash=baseline["content_hash"],
        )
        failure = {"stage": "after_subject_asset"}

        def inject(stage: str) -> None:
            if stage == failure["stage"]:
                failure["stage"] = ""
                raise RuntimeError(f"injected {stage}")

        interrupted = PostgresQualityQualificationAuthority(
            DATABASE_URL,
            application_build_id="quality-qualification-integration",
            commit_sha=RELEASE_SHA,
            failure_injector=inject,
        )
        with pytest.raises(RuntimeError, match="after_subject_asset"):
            interrupted.bind_subject(subject_command, principal=self.principal)
        subject = self.app.bind_subject(subject_command, principal=self.principal)

        for index, layer in enumerate(EvidenceLayer):
            evidence_asset = self._asset(
                "quality_qualification_evidence",
                f"recovery-{layer.value.lower()}",
                {"layer": layer.value, "status": "PASS"},
            )
            command = QualityEvidenceBindingCommand(
                campaign_id=manifest.campaign_id,
                evidence_id=f"evidence:{self.project_id}:{layer.value}",
                subject_id=subject["subject_id"],
                evidence_layer=layer,
                evidence_type=f"{layer.value}.SUMMARY",
                evidence_asset_version_id=evidence_asset["asset_version_id"],
                evidence_content_hash=evidence_asset["content_hash"],
                status=EvidenceStatus.PASS,
                severity=EvidenceSeverity.INFO,
                source_asset_version_ids=(canonical["asset_version_id"],),
                evaluator_lineage={"execution_class": "SCRIPTED_FIXTURE"},
                provider_lineage={"provider": "scripted"},
            )
            if index == 0:
                failure["stage"] = "after_evidence_asset"
                with pytest.raises(RuntimeError, match="after_evidence_asset"):
                    interrupted.bind_evidence(command, principal=self.principal)
            self.app.bind_evidence(command, principal=self.principal)

        failure["stage"] = "after_decision_asset"
        with pytest.raises(RuntimeError, match="after_decision_asset"):
            interrupted.evaluate_campaign(
                manifest.campaign_id,
                human_collection_closed=False,
                principal=self.principal,
            )
        decision = self.app.evaluate_campaign(
            manifest.campaign_id,
            human_collection_closed=False,
            principal=self.principal,
        )
        assert decision["qualification_status"] == "NOT_PROVEN"
        assert decision["campaign_lifecycle"] == "WAITING_HUMAN_EVIDENCE"

        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT
                  (SELECT COUNT(*)
                     FROM authority_quality_qualification_subject
                    WHERE campaign_id=%s),
                  (SELECT COUNT(*)
                     FROM authority_quality_qualification_evidence
                    WHERE campaign_id=%s),
                  (SELECT COUNT(*)
                     FROM authority_quality_qualification_decision
                    WHERE campaign_id=%s)
                """,
                [manifest.campaign_id] * 3,
            )
            projection_counts = tuple(int(value) for value in uow.cursor.fetchone())
            uow.cursor.execute(
                """
                SELECT definition_name, COUNT(*)
                FROM authority_operation
                WHERE project_id=%s
                  AND definition_name LIKE 'quality.qualification.%%'
                GROUP BY definition_name
                """,
                [self.project_id],
            )
            operation_counts = {
                str(name): int(count) for name, count in uow.cursor.fetchall()
            }
        assert projection_counts == (1, 3, 1)
        assert operation_counts == {
            "quality.qualification.campaign.admit": 1,
            "quality.qualification.campaign.freeze": 1,
            "quality.qualification.campaign.start": 1,
            "quality.qualification.subject.bind": 1,
            "quality.qualification.evidence.bind": 3,
            "quality.qualification.decision.record": 1,
        }
