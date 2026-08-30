from __future__ import annotations

from dataclasses import asdict
import hashlib
from typing import Any, Callable
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    TransactionCheckpoint,
    execute_transaction_command,
)
from novel_forge.modules.reader_calibration import (
    JudgeMode,
    ReaderJudgeQualificationStatus,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .domain import (
    ReaderJudgeDefinition,
    ReaderJudgeExecutionSnapshot,
    ReaderJudgeResolutionScope,
    canonical_hash,
    require_mode_status,
    safe_shadow_snapshot,
    scope_matches,
    validate_qualification_transition,
)


VERSION = "1.0.0"
HANDLER_PREFIX = "novel_forge.reader_judge_authority"
DEFINITIONS = (
    "reader_judge.definition.create",
    "reader_judge.qualification.decide",
    "reader_judge.activate",
    "reader_judge.suspend",
    "reader_judge.retire",
    "reader_judge.drift.record",
    "reader_judge.calibration_observation_set.build",
)


class ReaderJudgeAuthorityApplication:

    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
    ) -> None:
        if not database_url or not application_build_id or len(commit_sha) != 40:
            raise ValueError(
                "Reader Judge Authority requires PostgreSQL and build identity"
            )
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha

    def create_definition(
        self,
        *,
        project_id: str,
        workspace_id: str,
        definition: ReaderJudgeDefinition,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
        principal: Principal,
    ) -> dict[str, Any]:
        principal.require("reader_judge.authority.manage", project_id)
        self._validate_pack_binding(project_id, definition)
        payload = {"definition": definition.to_dict()}

        def handler(
            uow: AuthorityUnitOfWork,
            operation_id: str,
            checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            checkpoint("after_domain_validation")
            uow.cursor.execute(
                """
                INSERT INTO authority_reader_judge(
                    judge_id, project_id, created_by_operation_id
                ) VALUES (%s,%s,%s)
                ON CONFLICT (judge_id) DO NOTHING
                """,
                [definition.judge_id, project_id, operation_id],
            )
            judge_version_id = (
                f"reader-judge-version:{definition.judge_id}:"
                f"{definition.definition_version}:{definition.definition_hash.removeprefix('sha256:')}"
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_reader_judge_version(
                    judge_version_id, judge_id, project_id, definition_version,
                    model_profile_ref, model_version, capability_pack_ref,
                    prompt_ref, skill_ref, reader_segment_scope, platform_scope,
                    genre_scope, subgenre_scope, chapter_type_scope,
                    evaluation_contract_ref, calibration_policy_ref,
                    decision_policy_ref, mode, status,
                    maximum_adjustment_chapters, definition, definition_hash,
                    created_by_operation_id
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s
                ) ON CONFLICT (judge_id, definition_version) DO NOTHING
                """,
                [
                    judge_version_id,
                    definition.judge_id,
                    project_id,
                    definition.definition_version,
                    definition.model_profile_ref,
                    definition.model_version,
                    definition.capability_pack_ref,
                    definition.prompt_ref,
                    definition.skill_ref,
                    definition.reader_segment_scope,
                    definition.platform_scope,
                    definition.genre_scope,
                    definition.subgenre_scope,
                    definition.chapter_type_scope,
                    definition.evaluation_contract_ref,
                    definition.calibration_policy_ref,
                    definition.decision_policy_ref,
                    definition.mode.value,
                    definition.status.value,
                    definition.maximum_adjustment_chapters,
                    Jsonb(definition.to_dict()),
                    definition.definition_hash,
                    operation_id,
                ],
            )
            self._event(
                uow,
                operation_id=operation_id,
                project_id=project_id,
                aggregate_id=judge_version_id,
                event_type="reader_judge.definition.create",
                correlation_id=correlation_id,
                payload={
                    "judge_id": definition.judge_id,
                    "judge_version_id": judge_version_id,
                    "definition_hash": definition.definition_hash,
                },
            )
            checkpoint("after_outbox_insert")
            return {
                "judge_id": definition.judge_id,
                "judge_version_id": judge_version_id,
                "definition_hash": definition.definition_hash,
            }

        return self._run(
            "reader_judge.definition.create",
            project_id=project_id,
            workspace_id=workspace_id,
            book_id="",
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            correlation_id=correlation_id,
            payload=payload,
            principal=principal,
            handler=handler,
        )

    def decide_qualification(
        self,
        *,
        project_id: str,
        workspace_id: str,
        judge_version_id: str,
        qualification_status: ReaderJudgeQualificationStatus,
        evidence_level: str,
        evidence: dict[str, Any],
        calibration_profile_id: str,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
        principal: Principal,
    ) -> dict[str, Any]:
        principal.require("reader_judge.authority.manage", project_id)
        current = self._current_qualification(project_id, judge_version_id)
        sample_size = int(evidence.get("sample_size") or 0)
        minimum_sample_size = int(evidence.get("minimum_sample_size") or 1)
        drift_detected = bool(evidence.get("drift_detected", False))
        validate_qualification_transition(
            current,
            qualification_status,
            evidence_level=evidence_level,
            sample_size=sample_size,
            minimum_sample_size=minimum_sample_size,
            drift_detected=drift_detected,
        )
        if (
            qualification_status
            in {
                ReaderJudgeQualificationStatus.CALIBRATED,
                ReaderJudgeQualificationStatus.QUALIFIED,
            }
            and not calibration_profile_id
        ):
            raise KernelError(
                "READER_JUDGE_CALIBRATION_PROFILE_REQUIRED",
                "Calibrated or Qualified Judge decisions require an Active Calibration Profile",
            )
        if calibration_profile_id:
            self._validate_calibration_profile(
                project_id, judge_version_id, calibration_profile_id
            )
        evidence_hash = canonical_hash(evidence)

        def handler(
            uow: AuthorityUnitOfWork,
            operation_id: str,
            checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            if (
                self._current_qualification_in_cursor(
                    uow.cursor, project_id, judge_version_id
                )
                is not current
            ):
                raise KernelError(
                    "READER_JUDGE_QUALIFICATION_CONFLICT",
                    "Reader Judge qualification changed before decision commit",
                )
            decision_id = (
                "reader-judge-decision:"
                + hashlib.sha256(
                    f"{judge_version_id}:{operation_id}".encode()
                ).hexdigest()
            )
            checkpoint("after_domain_validation")
            uow.cursor.execute(
                """
                INSERT INTO authority_reader_judge_qualification_decision(
                    decision_id, judge_version_id, project_id,
                    qualification_status, evidence_level,
                    calibration_profile_id, evidence, evidence_hash,
                    decided_by, decision_operation_id
                ) VALUES (%s,%s,%s,%s,%s,NULLIF(%s,''),%s,%s,%s,%s)
                """,
                [
                    decision_id,
                    judge_version_id,
                    project_id,
                    qualification_status.value,
                    evidence_level,
                    calibration_profile_id,
                    Jsonb(evidence),
                    evidence_hash,
                    principal.principal_id,
                    operation_id,
                ],
            )
            self._event(
                uow,
                operation_id=operation_id,
                project_id=project_id,
                aggregate_id=judge_version_id,
                event_type="reader_judge.qualification.decide",
                correlation_id=correlation_id,
                payload={
                    "decision_id": decision_id,
                    "qualification_status": qualification_status.value,
                    "evidence_level": evidence_level,
                },
            )
            checkpoint("after_outbox_insert")
            return {
                "decision_id": decision_id,
                "qualification_status": qualification_status.value,
            }

        return self._run(
            "reader_judge.qualification.decide",
            project_id=project_id,
            workspace_id=workspace_id,
            book_id="",
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            correlation_id=correlation_id,
            payload={
                "judge_version_id": judge_version_id,
                "qualification_status": qualification_status.value,
                "evidence_level": evidence_level,
                "evidence_hash": evidence_hash,
                "calibration_profile_id": calibration_profile_id,
            },
            principal=principal,
            handler=handler,
        )

    def activate(
        self,
        *,
        project_id: str,
        workspace_id: str,
        book_id: str,
        judge_version_id: str,
        expected_activation_version: int,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
        principal: Principal,
    ) -> dict[str, Any]:
        principal.require("reader_judge.authority.manage", project_id)
        definition = self._definition(project_id, judge_version_id)
        qualification = self._latest_decision(project_id, judge_version_id)
        if qualification is None:
            raise KernelError(
                "READER_JUDGE_QUALIFICATION_DECISION_REQUIRED",
                "Reader Judge activation requires an append-only qualification decision",
            )
        mode = JudgeMode(str(definition["mode"]))
        status = ReaderJudgeQualificationStatus(
            str(qualification["qualification_status"])
        )
        require_mode_status(mode, status)
        scope_key = self._scope_key(project_id, book_id)

        def handler(
            uow: AuthorityUnitOfWork,
            operation_id: str,
            checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            uow.cursor.execute(
                """
                SELECT activation_version FROM authority_reader_judge_active
                WHERE scope_key=%s FOR UPDATE
                """,
                [scope_key],
            )
            row = uow.cursor.fetchone()
            actual = int(row[0]) if row else 0
            if actual != expected_activation_version:
                raise KernelError(
                    "READER_JUDGE_ACTIVATION_CAS_CONFLICT",
                    "Active Reader Judge changed before activation",
                )
            activation_version = actual + 1
            activation_id = (
                "reader-judge-activation:"
                + hashlib.sha256(
                    f"{scope_key}:{activation_version}:{judge_version_id}".encode()
                ).hexdigest()
            )
            checkpoint("after_domain_validation")
            uow.cursor.execute(
                """
                INSERT INTO authority_reader_judge_activation(
                    activation_id, judge_version_id, project_id, book_id,
                    activation_version, expected_previous_activation_version,
                    qualification_decision_id, activation_operation_id
                ) VALUES (%s,%s,%s,NULLIF(%s,''),%s,%s,%s,%s)
                """,
                [
                    activation_id,
                    judge_version_id,
                    project_id,
                    book_id,
                    activation_version,
                    actual,
                    qualification["decision_id"],
                    operation_id,
                ],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_reader_judge_active(
                    scope_key, project_id, book_id, activation_id,
                    activation_version, effective_mode,
                    effective_qualification_status, state,
                    updated_by_operation_id
                ) VALUES (%s,%s,NULLIF(%s,''),%s,%s,%s,%s,'ACTIVE',%s)
                ON CONFLICT(scope_key) DO UPDATE SET
                    activation_id=EXCLUDED.activation_id,
                    activation_version=EXCLUDED.activation_version,
                    effective_mode=EXCLUDED.effective_mode,
                    effective_qualification_status=EXCLUDED.effective_qualification_status,
                    state='ACTIVE', updated_by_operation_id=EXCLUDED.updated_by_operation_id,
                    updated_at=NOW()
                WHERE authority_reader_judge_active.activation_version=%s
                """,
                [
                    scope_key,
                    project_id,
                    book_id,
                    activation_id,
                    activation_version,
                    mode.value,
                    status.value,
                    operation_id,
                    actual,
                ],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "READER_JUDGE_ACTIVATION_CAS_CONFLICT",
                    "Active Reader Judge pointer CAS failed",
                )
            self._event(
                uow,
                operation_id=operation_id,
                project_id=project_id,
                aggregate_id=scope_key,
                event_type="reader_judge.activate",
                correlation_id=correlation_id,
                payload={
                    "activation_id": activation_id,
                    "judge_version_id": judge_version_id,
                    "activation_version": activation_version,
                    "mode": mode.value,
                },
            )
            checkpoint("after_outbox_insert")
            return {
                "activation_id": activation_id,
                "activation_version": activation_version,
                "scope_key": scope_key,
                "mode": mode.value,
            }

        return self._run(
            "reader_judge.activate",
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            correlation_id=correlation_id,
            payload={
                "judge_version_id": judge_version_id,
                "expected_activation_version": expected_activation_version,
                "scope_key": scope_key,
            },
            principal=principal,
            handler=handler,
        )

    def suspend(
        self,
        *,
        project_id: str,
        workspace_id: str,
        book_id: str,
        expected_activation_version: int,
        reason: str,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
        principal: Principal,
    ) -> dict[str, Any]:
        return self._change_active_state(
            definition_name="reader_judge.suspend",
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            expected_activation_version=expected_activation_version,
            reason=reason,
            target="SUSPENDED",
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            correlation_id=correlation_id,
            principal=principal,
        )

    def record_drift(
        self,
        *,
        project_id: str,
        workspace_id: str,
        book_id: str,
        expected_activation_version: int,
        severity: str,
        drift_type: str,
        evidence: dict[str, Any],
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
        principal: Principal,
    ) -> dict[str, Any]:
        principal.require("reader_judge.authority.manage", project_id)
        if severity not in {"LOW", "MEDIUM", "HIGH", "SEVERE"} or not drift_type:
            raise ValueError("Reader Judge drift classification is invalid")
        scope_key = self._scope_key(project_id, book_id)
        downgrade = JudgeMode.ADVISORY if severity == "LOW" else JudgeMode.SHADOW
        evidence_hash = canonical_hash(evidence)

        def handler(
            uow: AuthorityUnitOfWork,
            operation_id: str,
            checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            active = self._lock_active(
                uow, scope_key, expected_activation_version=expected_activation_version
            )
            drift_id = (
                "reader-judge-drift:"
                + hashlib.sha256(
                    f"{active['judge_version_id']}:{operation_id}".encode()
                ).hexdigest()
            )
            checkpoint("after_domain_validation")
            uow.cursor.execute(
                """
                INSERT INTO authority_reader_judge_drift(
                    drift_id, judge_version_id, project_id, severity,
                    drift_type, evidence, evidence_hash, downgrade_mode,
                    detected_by_operation_id
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                [
                    drift_id,
                    active["judge_version_id"],
                    project_id,
                    severity,
                    drift_type,
                    Jsonb(evidence),
                    evidence_hash,
                    downgrade.value,
                    operation_id,
                ],
            )
            uow.cursor.execute(
                """
                UPDATE authority_reader_judge_active
                SET effective_mode=%s, effective_qualification_status='DRIFTED',
                    updated_by_operation_id=%s, updated_at=NOW()
                WHERE scope_key=%s AND activation_version=%s AND state='ACTIVE'
                """,
                [downgrade.value, operation_id, scope_key, expected_activation_version],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "READER_JUDGE_DRIFT_CAS_CONFLICT",
                    "Judge activation changed during drift downgrade",
                )
            self._event(
                uow,
                operation_id=operation_id,
                project_id=project_id,
                aggregate_id=scope_key,
                event_type="reader_judge.drift.record",
                correlation_id=correlation_id,
                payload={"drift_id": drift_id, "downgrade_mode": downgrade.value},
            )
            checkpoint("after_outbox_insert")
            return {
                "drift_id": drift_id,
                "effective_mode": downgrade.value,
                "qualification_status": "DRIFTED",
            }

        return self._run(
            "reader_judge.drift.record",
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            correlation_id=correlation_id,
            payload={
                "scope_key": scope_key,
                "severity": severity,
                "drift_type": drift_type,
                "evidence_hash": evidence_hash,
            },
            principal=principal,
            handler=handler,
        )

    def retire(
        self,
        *,
        project_id: str,
        workspace_id: str,
        judge_version_id: str,
        reason: str,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
        principal: Principal,
    ) -> dict[str, Any]:
        principal.require("reader_judge.authority.manage", project_id)
        self._definition(project_id, judge_version_id)

        def handler(
            uow: AuthorityUnitOfWork,
            operation_id: str,
            checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            retirement_id = (
                "reader-judge-retirement:"
                + hashlib.sha256(
                    f"{judge_version_id}:{operation_id}".encode()
                ).hexdigest()
            )
            checkpoint("after_domain_validation")
            uow.cursor.execute(
                """
                INSERT INTO authority_reader_judge_retirement(
                    retirement_id, judge_version_id, project_id, reason,
                    retirement_operation_id
                ) VALUES (%s,%s,%s,%s,%s)
                """,
                [retirement_id, judge_version_id, project_id, reason, operation_id],
            )
            uow.cursor.execute(
                """
                UPDATE authority_reader_judge_active AS active
                SET state='RETIRED', effective_qualification_status='RETIRED',
                    updated_by_operation_id=%s, updated_at=NOW()
                FROM authority_reader_judge_activation AS activation
                WHERE active.activation_id=activation.activation_id
                  AND activation.judge_version_id=%s AND active.state='ACTIVE'
                """,
                [operation_id, judge_version_id],
            )
            self._event(
                uow,
                operation_id=operation_id,
                project_id=project_id,
                aggregate_id=judge_version_id,
                event_type="reader_judge.retire",
                correlation_id=correlation_id,
                payload={"retirement_id": retirement_id, "reason": reason},
            )
            checkpoint("after_outbox_insert")
            return {"retirement_id": retirement_id, "status": "RETIRED"}

        return self._run(
            "reader_judge.retire",
            project_id=project_id,
            workspace_id=workspace_id,
            book_id="",
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            correlation_id=correlation_id,
            payload={"judge_version_id": judge_version_id, "reason": reason},
            principal=principal,
            handler=handler,
        )

    def build_calibration_observation_set(
        self,
        *,
        project_id: str,
        workspace_id: str,
        book_id: str,
        reader_segment: str,
        platform: str,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
        principal: Principal,
    ) -> dict[str, Any]:
        principal.require("reader_judge.authority.manage", project_id)

        def handler(
            uow: AuthorityUnitOfWork,
            operation_id: str,
            checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            exposure_ids = self._ids(
                uow.cursor,
                "SELECT exposure_id FROM reader_exposure WHERE project_id=%s AND book_id=%s AND reader_segment=%s AND platform=%s AND denominator_eligible=TRUE ORDER BY exposure_id",
                [project_id, book_id, reader_segment, platform],
            )
            outcome_ids = self._ids(
                uow.cursor,
                "SELECT outcome_event_id FROM reader_outcome_event WHERE project_id=%s AND book_id=%s AND reader_segment=%s AND platform=%s ORDER BY outcome_event_id",
                [project_id, book_id, reader_segment, platform],
            )
            metric_ids = self._ids(
                uow.cursor,
                "SELECT metric_id FROM chapter_outcome_metric WHERE project_id=%s AND book_id=%s AND reader_segment=%s AND platform=%s ORDER BY metric_id",
                [project_id, book_id, reader_segment, platform],
            )
            retention_ids = self._ids(
                uow.cursor,
                "SELECT retention_metric_id FROM retention_window_metric WHERE project_id=%s AND book_id=%s AND reader_segment=%s AND platform=%s ORDER BY retention_metric_id",
                [project_id, book_id, reader_segment, platform],
            )
            value = {
                "project_id": project_id,
                "book_id": book_id,
                "reader_segment": reader_segment,
                "platform": platform,
                "exposure_ids": exposure_ids,
                "outcome_event_ids": outcome_ids,
                "chapter_metric_ids": metric_ids,
                "retention_metric_ids": retention_ids,
                "observation_count": len(outcome_ids),
                # Existing behavior records lack proof provenance; fail closed.
                "evidence_level": "FIXTURE",
            }
            observation_hash = canonical_hash(value)
            observation_set_id = (
                "reader-observation-set:" + observation_hash.removeprefix("sha256:")
            )
            checkpoint("after_domain_validation")
            uow.cursor.execute(
                """
                INSERT INTO authority_reader_calibration_observation_set(
                    observation_set_id, project_id, book_id, reader_segment,
                    platform, exposure_ids, outcome_event_ids, chapter_metric_ids,
                    retention_metric_ids, observation_count, evidence_level,
                    observation_hash, built_by_operation_id
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'FIXTURE',%s,%s)
                ON CONFLICT(observation_hash) DO NOTHING
                """,
                [
                    observation_set_id,
                    project_id,
                    book_id,
                    reader_segment,
                    platform,
                    Jsonb(exposure_ids),
                    Jsonb(outcome_ids),
                    Jsonb(metric_ids),
                    Jsonb(retention_ids),
                    len(outcome_ids),
                    observation_hash,
                    operation_id,
                ],
            )
            self._event(
                uow,
                operation_id=operation_id,
                project_id=project_id,
                aggregate_id=observation_set_id,
                event_type="reader_judge.calibration_observation_set.build",
                correlation_id=correlation_id,
                payload={
                    "observation_set_id": observation_set_id,
                    "observation_count": len(outcome_ids),
                    "evidence_level": "FIXTURE",
                },
            )
            checkpoint("after_outbox_insert")
            return {
                "observation_set_id": observation_set_id,
                "observation_hash": observation_hash,
                "observation_count": len(outcome_ids),
                "evidence_level": "FIXTURE",
            }

        return self._run(
            "reader_judge.calibration_observation_set.build",
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            correlation_id=correlation_id,
            payload={"reader_segment": reader_segment, "platform": platform},
            principal=principal,
            handler=handler,
        )

    def _change_active_state(
        self,
        *,
        definition_name: str,
        project_id: str,
        workspace_id: str,
        book_id: str,
        expected_activation_version: int,
        reason: str,
        target: str,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
        principal: Principal,
    ) -> dict[str, Any]:
        principal.require("reader_judge.authority.manage", project_id)
        if not reason:
            raise ValueError("Reader Judge state change requires a reason")
        scope_key = self._scope_key(project_id, book_id)

        def handler(
            uow: AuthorityUnitOfWork,
            operation_id: str,
            checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            active = self._lock_active(
                uow, scope_key, expected_activation_version=expected_activation_version
            )
            suspension_id = (
                "reader-judge-suspension:"
                + hashlib.sha256(
                    f"{active['activation_id']}:{operation_id}".encode()
                ).hexdigest()
            )
            checkpoint("after_domain_validation")
            uow.cursor.execute(
                """
                INSERT INTO authority_reader_judge_suspension(
                    suspension_id, activation_id, project_id, reason,
                    suspension_operation_id
                ) VALUES (%s,%s,%s,%s,%s)
                """,
                [
                    suspension_id,
                    active["activation_id"],
                    project_id,
                    reason,
                    operation_id,
                ],
            )
            uow.cursor.execute(
                """
                UPDATE authority_reader_judge_active
                SET state=%s, effective_mode='SHADOW',
                    effective_qualification_status=%s,
                    updated_by_operation_id=%s, updated_at=NOW()
                WHERE scope_key=%s AND activation_version=%s AND state='ACTIVE'
                """,
                [target, target, operation_id, scope_key, expected_activation_version],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "READER_JUDGE_STATE_CAS_CONFLICT",
                    "Active Judge changed before state transition",
                )
            self._event(
                uow,
                operation_id=operation_id,
                project_id=project_id,
                aggregate_id=scope_key,
                event_type="reader_judge.suspend",
                correlation_id=correlation_id,
                payload={"suspension_id": suspension_id, "reason": reason},
            )
            checkpoint("after_outbox_insert")
            return {"suspension_id": suspension_id, "status": target}

        return self._run(
            definition_name,
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            correlation_id=correlation_id,
            payload={
                "scope_key": scope_key,
                "expected_activation_version": expected_activation_version,
                "reason": reason,
            },
            principal=principal,
            handler=handler,
        )

    def _run(
        self,
        definition_name: str,
        *,
        project_id: str,
        workspace_id: str,
        book_id: str,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
        payload: dict[str, Any],
        principal: Principal,
        handler: Callable[
            [AuthorityUnitOfWork, str, TransactionCheckpoint], dict[str, Any]
        ],
    ) -> dict[str, Any]:
        self._register_definitions()
        result = execute_transaction_command(
            self.database_url,
            {
                "definition_name": definition_name,
                "definition_version": VERSION,
                "project_id": project_id,
                "workspace_id": workspace_id,
                "book_id": book_id,
                "actor_id": principal.principal_id,
                "idempotency_scope": "project:reader-judge-authority",
                "idempotency_key": idempotency_key,
                "trace_id": trace_id,
                "span_id": str(uuid4()),
                "correlation_id": correlation_id,
                "causation_id": "",
                "input": {"project_id": project_id, "book_id": book_id, **payload},
                "input_assets": [],
            },
            context=AdmissionContext(
                actor_id=principal.principal_id,
                permissions=frozenset({"reader_judge.authority.manage"}),
                available_handlers=frozenset({f"{HANDLER_PREFIX}.{definition_name}"}),
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
            handler=handler,
        )
        return dict(result)

    def _register_definitions(self) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            for name in DEFINITIONS:
                uow.repositories.definitions.register(
                    reader_judge_definition(
                        name,
                        application_build_id=self.application_build_id,
                        commit_sha=self.commit_sha,
                    )
                )
            uow.commit()

    def _validate_pack_binding(
        self, project_id: str, definition: ReaderJudgeDefinition
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT deployment.project_id, binding.node_bindings
                FROM authority_capability_pack_deployment AS deployment
                JOIN authority_capability_pack_binding_set AS binding
                  ON binding.binding_set_id=deployment.binding_set_id
                WHERE deployment.deployment_id=%s
                  AND deployment.deployment_status='ACTIVE'
                """,
                [definition.capability_pack_ref],
            )
            row = uow.cursor.fetchone()
        if row is None or (row[0] is not None and str(row[0]) != project_id):
            raise KernelError(
                "READER_JUDGE_CAPABILITY_PACK_INVALID",
                "Reader Judge requires an Active compatible Capability Pack deployment",
            )
        matches = [
            dict(node)
            for node in list(row[1])
            if str(node.get("commit_authority") or "") == "READER_JUDGE_AUTHORITY"
            and str(node.get("prompt_bundle_ref") or "") == definition.prompt_ref
            and str(node.get("skill_bundle_ref") or "") == definition.skill_ref
            and str(node.get("agent_definition_ref") or "")
        ]
        if len(matches) != 1:
            raise KernelError(
                "READER_JUDGE_PACK_BINDING_MISMATCH",
                "Prompt, Skill, and commit Authority must come from the compiled Pack binding",
            )

    def _validate_calibration_profile(
        self, project_id: str, judge_version_id: str, profile_id: str
    ) -> None:
        definition = self._definition(project_id, judge_version_id)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT project_id, platform, genre, subgenre, chapter_type,
                       reader_segment, model_version, status
                FROM calibration_profile WHERE profile_id=%s
                """,
                [profile_id],
            )
            row = uow.cursor.fetchone()
        if row is None or str(row[0]) != project_id:
            raise KernelError(
                "READER_JUDGE_CALIBRATION_PROFILE_INVALID",
                "Calibration Profile is missing or outside Project scope",
            )
        pairs = (
            (definition["platform_scope"], row[1]),
            (definition["genre_scope"], row[2]),
            (definition["subgenre_scope"], row[3]),
            (definition["chapter_type_scope"], row[4]),
            (definition["reader_segment_scope"], row[5]),
            (definition["model_version"], row[6]),
        )
        if any(
            not scope_matches(str(expected), str(actual)) for expected, actual in pairs
        ) or str(row[7]) not in {"VALID", "CALIBRATED", "QUALIFIED"}:
            raise KernelError(
                "READER_JUDGE_CALIBRATION_SCOPE_MISMATCH",
                "Calibration Profile does not match the Judge definition scope",
            )

    def _definition(self, project_id: str, judge_version_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT judge_id, mode, status, maximum_adjustment_chapters,
                       platform_scope, genre_scope, subgenre_scope,
                       chapter_type_scope, reader_segment_scope, model_version,
                       definition_hash, capability_pack_ref, prompt_ref, skill_ref,
                       model_profile_ref
                FROM authority_reader_judge_version
                WHERE project_id=%s AND judge_version_id=%s
                """,
                [project_id, judge_version_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "READER_JUDGE_DEFINITION_NOT_FOUND",
                "Reader Judge definition version does not exist",
            )
        keys = (
            "judge_id",
            "mode",
            "status",
            "maximum_adjustment_chapters",
            "platform_scope",
            "genre_scope",
            "subgenre_scope",
            "chapter_type_scope",
            "reader_segment_scope",
            "model_version",
            "definition_hash",
            "capability_pack_ref",
            "prompt_ref",
            "skill_ref",
            "model_profile_ref",
        )
        return dict(zip(keys, row, strict=True))

    def _current_qualification(
        self, project_id: str, judge_version_id: str
    ) -> ReaderJudgeQualificationStatus:
        with AuthorityUnitOfWork(self.database_url) as uow:
            return self._current_qualification_in_cursor(
                uow.cursor, project_id, judge_version_id
            )

    @staticmethod
    def _current_qualification_in_cursor(
        cursor: Any, project_id: str, judge_version_id: str
    ) -> ReaderJudgeQualificationStatus:
        cursor.execute(
            """
            SELECT COALESCE(
                (SELECT qualification_status
                 FROM authority_reader_judge_qualification_decision
                 WHERE project_id=%s AND judge_version_id=%s
                 ORDER BY created_at DESC, decision_id DESC LIMIT 1),
                (SELECT status FROM authority_reader_judge_version
                 WHERE project_id=%s AND judge_version_id=%s)
            )
            """,
            [project_id, judge_version_id, project_id, judge_version_id],
        )
        row = cursor.fetchone()
        if row is None or row[0] is None:
            raise KernelError(
                "READER_JUDGE_DEFINITION_NOT_FOUND",
                "Reader Judge definition version does not exist",
            )
        return ReaderJudgeQualificationStatus(str(row[0]))

    def _latest_decision(
        self, project_id: str, judge_version_id: str
    ) -> dict[str, Any] | None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT decision_id, qualification_status,
                       COALESCE(calibration_profile_id, ''), evidence_level
                FROM authority_reader_judge_qualification_decision
                WHERE project_id=%s AND judge_version_id=%s
                ORDER BY created_at DESC, decision_id DESC LIMIT 1
                """,
                [project_id, judge_version_id],
            )
            row = uow.cursor.fetchone()
        return (
            dict(
                zip(
                    (
                        "decision_id",
                        "qualification_status",
                        "calibration_profile_id",
                        "evidence_level",
                    ),
                    row,
                    strict=True,
                )
            )
            if row
            else None
        )

    @staticmethod
    def _lock_active(
        uow: AuthorityUnitOfWork, scope_key: str, *, expected_activation_version: int
    ) -> dict[str, Any]:
        uow.cursor.execute(
            """
            SELECT active.activation_id, active.activation_version,
                   activation.judge_version_id
            FROM authority_reader_judge_active AS active
            JOIN authority_reader_judge_activation AS activation
              ON activation.activation_id=active.activation_id
            WHERE active.scope_key=%s AND active.state='ACTIVE'
            FOR UPDATE OF active
            """,
            [scope_key],
        )
        row = uow.cursor.fetchone()
        if row is None or int(row[1]) != expected_activation_version:
            raise KernelError(
                "READER_JUDGE_ACTIVATION_CAS_CONFLICT",
                "Active Reader Judge pointer does not match expected version",
            )
        return dict(
            zip(
                ("activation_id", "activation_version", "judge_version_id"),
                row,
                strict=True,
            )
        )

    @staticmethod
    def _ids(cursor: Any, query: str, parameters: list[Any]) -> list[str]:
        cursor.execute(query, parameters)
        return [str(row[0]) for row in cursor.fetchall()]

    @staticmethod
    def _scope_key(project_id: str, book_id: str) -> str:
        return canonical_hash({"project_id": project_id, "book_id": book_id or "*"})

    @staticmethod
    def _event(
        uow: AuthorityUnitOfWork,
        *,
        operation_id: str,
        project_id: str,
        aggregate_id: str,
        event_type: str,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> None:
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": "reader_judge_authority",
                "aggregate_id": aggregate_id,
                "operation_id": operation_id,
                "project_id": project_id,
                "event_type": event_type,
                "correlation_id": correlation_id,
                "causation_id": operation_id,
                "payload": {"operation_id": operation_id, **payload},
            }
        )


class ReaderJudgeRuntimeResolver:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("Reader Judge resolver requires PostgreSQL")
        self.database_url = database_url

    def resolve(
        self, scope: ReaderJudgeResolutionScope
    ) -> ReaderJudgeExecutionSnapshot:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT active.scope_key, active.effective_mode,
                       active.effective_qualification_status,
                       activation.activation_id, activation.judge_version_id,
                       decision.decision_id, COALESCE(decision.calibration_profile_id,''),
                       version.judge_id, version.definition_hash,
                       version.maximum_adjustment_chapters,
                       version.platform_scope, version.genre_scope,
                       version.subgenre_scope, version.chapter_type_scope,
                       version.reader_segment_scope, version.model_version,
                       version.capability_pack_ref, version.prompt_ref,
                       version.skill_ref, version.model_profile_ref,
                       deployment.deployment_status,
                       deployment.project_id, deployment.book_id,
                       EXISTS (
                           SELECT 1
                           FROM authority_capability_pack_activation AS pack_active
                           WHERE pack_active.active_deployment_id=
                               deployment.deployment_id
                       ) AS pack_is_active,
                       profile.status, profile.evidence_level,
                       profile.judge_mode, profile.platform, profile.genre,
                       profile.subgenre, profile.chapter_type,
                       profile.reader_segment, profile.model_version
                FROM authority_reader_judge_active AS active
                JOIN authority_reader_judge_activation AS activation
                  ON activation.activation_id=active.activation_id
                JOIN authority_reader_judge_qualification_decision AS decision
                  ON decision.decision_id=activation.qualification_decision_id
                JOIN authority_reader_judge_version AS version
                  ON version.judge_version_id=activation.judge_version_id
                JOIN authority_capability_pack_deployment AS deployment
                  ON deployment.deployment_id=version.capability_pack_ref
                LEFT JOIN calibration_profile AS profile
                  ON profile.profile_id=decision.calibration_profile_id
                WHERE active.project_id=%s AND active.state='ACTIVE'
                  AND (active.book_id=%s OR active.book_id IS NULL)
                ORDER BY (active.book_id IS NOT NULL) DESC,
                         active.activation_version DESC
                """,
                [scope.project_id, scope.book_id],
            )
            fields = (
                "scope_key",
                "effective_mode",
                "effective_qualification_status",
                "activation_id",
                "judge_version_id",
                "decision_id",
                "calibration_profile_id",
                "judge_id",
                "definition_hash",
                "maximum_adjustment_chapters",
                "platform_scope",
                "genre_scope",
                "subgenre_scope",
                "chapter_type_scope",
                "reader_segment_scope",
                "model_version",
                "capability_pack_ref",
                "prompt_ref",
                "skill_ref",
                "model_profile_ref",
                "deployment_status",
                "deployment_project_id",
                "deployment_book_id",
                "pack_is_active",
                "profile_status",
                "profile_evidence_level",
                "profile_judge_mode",
                "profile_platform",
                "profile_genre",
                "profile_subgenre",
                "profile_chapter_type",
                "profile_reader_segment",
                "profile_model_version",
            )
            rows = [
                dict(zip(fields, row, strict=True)) for row in uow.cursor.fetchall()
            ]
        for row in rows:
            scoped = (
                (row["platform_scope"], scope.platform),
                (row["genre_scope"], scope.genre),
                (row["subgenre_scope"], scope.subgenre),
                (row["chapter_type_scope"], scope.chapter_type),
                (row["reader_segment_scope"], scope.reader_segment),
                (row["model_version"], scope.model_version),
            )
            if any(
                not scope_matches(str(expected), str(actual))
                for expected, actual in scoped
            ):
                continue
            if (
                str(row["deployment_status"]) != "ACTIVE"
                or not bool(row["pack_is_active"])
                or (
                    row["deployment_project_id"] is not None
                    and str(row["deployment_project_id"]) != scope.project_id
                )
                or (
                    row["deployment_book_id"] is not None
                    and str(row["deployment_book_id"]) != scope.book_id
                )
            ):
                continue
            mode = JudgeMode(str(row["effective_mode"]))
            qualification = ReaderJudgeQualificationStatus(
                str(row["effective_qualification_status"])
            )
            if qualification is ReaderJudgeQualificationStatus.DRIFTED:
                mode = JudgeMode.SHADOW
            try:
                require_mode_status(mode, qualification)
            except KernelError:
                return safe_shadow_snapshot(
                    scope, reason="ACTIVE_JUDGE_QUALIFICATION_INVALID"
                )
            if qualification in {
                ReaderJudgeQualificationStatus.CALIBRATED,
                ReaderJudgeQualificationStatus.QUALIFIED,
            }:
                profile_scope = (
                    (row["profile_platform"], scope.platform),
                    (row["profile_genre"], scope.genre),
                    (row["profile_subgenre"], scope.subgenre),
                    (row["profile_chapter_type"], scope.chapter_type),
                    (row["profile_reader_segment"], scope.reader_segment),
                    (row["profile_model_version"], scope.model_version),
                )
                if (
                    not row["calibration_profile_id"]
                    or str(row["profile_status"]) != "VALID"
                    or str(row["profile_evidence_level"]) == "FIXTURE"
                    or str(row["profile_judge_mode"]) != mode.value
                    or any(
                        not scope_matches(str(expected), str(actual))
                        for expected, actual in profile_scope
                    )
                ):
                    return safe_shadow_snapshot(
                        scope, reason="ACTIVE_JUDGE_CALIBRATION_INVALID"
                    )
            bounded = mode is JudgeMode.BOUNDED_PRODUCTION
            payload = {
                **asdict(scope),
                "activation_id": str(row["activation_id"]),
                "judge_version_id": str(row["judge_version_id"]),
                "definition_hash": str(row["definition_hash"]),
                "mode": mode.value,
                "qualification": qualification.value,
            }
            return ReaderJudgeExecutionSnapshot(
                snapshot_id="reader-judge-snapshot:"
                + canonical_hash(payload).removeprefix("sha256:"),
                project_id=scope.project_id,
                book_id=scope.book_id,
                judge_id=str(row["judge_id"]),
                judge_version_id=str(row["judge_version_id"]),
                definition_hash=str(row["definition_hash"]),
                qualification_decision_id=str(row["decision_id"]),
                calibration_profile_id=str(row["calibration_profile_id"]),
                mode=mode,
                calibration_status=qualification,
                score_semantics=(
                    "CALIBRATED_PROBABILITY"
                    if row["calibration_profile_id"]
                    else "RAW_SCORE"
                ),
                publish_blocking=False,
                authority_commit_allowed=bounded,
                human_review_recommended=mode is not JudgeMode.SHADOW,
                plan_adjustment_candidate_allowed=bounded,
                maximum_adjustment_chapters=(
                    int(row["maximum_adjustment_chapters"]) if bounded else 0
                ),
                capability_pack_ref=str(row["capability_pack_ref"]),
                prompt_ref=str(row["prompt_ref"]),
                skill_ref=str(row["skill_ref"]),
                model_profile_ref=str(row["model_profile_ref"]),
                model_version=str(row["model_version"]),
            )
        return safe_shadow_snapshot(scope, reason="NO_ACTIVE_QUALIFIED_JUDGE")


def reader_judge_definition(
    name: str, *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    schema = {"type": "object"}
    return {
        "name": name,
        "definition_version": VERSION,
        "family": "reader_judge_authority",
        "enabled": True,
        "definition_status": "implemented_validation_pending",
        "command_schema_version": f"{name}.command.v1",
        "result_schema_version": f"{name}.result.v1",
        "command_schema": schema,
        "result_schema": schema,
        "input_contract": schema,
        "output_contract": {"type": "ReaderJudgeAuthorityFact"},
        "handler_key": f"{HANDLER_PREFIX}.{name}",
        "handler_contract_version": "reader-judge-authority-v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "transactional",
        "permissions": ["reader_judge.authority.manage"],
        "approval_policy": {"required": False},
        "policy": {
            "execution_classification": "transaction_command",
            "append_only_decisions": True,
            "candidate_only": True,
            "direct_plan_mutation_forbidden": True,
            "publish_blocking": False,
        },
        "idempotency_scope": "project:reader-judge-authority",
        "concurrency_key_template": "project:{project_id}:reader-judge",
        "retry_policy": {"max_attempts": 1},
        "timeout_policy": {"operation_timeout_seconds": 30},
        "cancellation_policy": {"mode": "not_applicable"},
        "compensation_policy": {"supported": False, "reason": "append-only fact"},
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "projection_consumers": ["reader_outcome", "book_replan"],
        "migration_owner": "reader-judge-authority",
        "completion_contract": {
            "version": "reader-judge-authority-completion-v1",
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": [name],
        },
    }


__all__ = [
    "ReaderJudgeAuthorityApplication",
    "ReaderJudgeRuntimeResolver",
    "reader_judge_definition",
]
