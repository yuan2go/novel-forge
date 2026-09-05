from __future__ import annotations

from dataclasses import asdict
import hashlib
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_handler_runtime import (
    AuthorityHandlerOutput,
    AuthorityHandlerRegistration,
    AuthorityHandlerRequest,
)
from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.operation_graph import (
    GraphCommandContext,
    start_saga,
)
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    admit_command,
)
from novel_forge.modules.content_authority.scheduler import (
    ContentAuthorityScheduler,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .domain import (
    BlindScope,
    CalibrationCandidate,
    CalibrationScope,
    CalibrationStatus,
    JudgeMode,
    PreferenceChoice,
    HumanBlindDecision,
    blind_pair_order,
    calibration_metrics,
    human_agreement_report,
    mode_after_drift,
    preference_bias_report,
    require_exposure_denominator,
    resolve_calibration_profile,
)
from .blind_export import BlindExportBundle


VERSION = "1.0.0"
DEFINITIONS = {
    "reader.preference.task.create": (
        "human_preference_task_receipt",
        "reader.preference.task",
    ),
    "reader.preference.pair.create": (
        "human_preference_pair_receipt",
        "reader.preference.pair",
    ),
    "reader.preference.decision.record": (
        "human_preference_decision_receipt",
        "reader.preference.decision",
    ),
    "reader.preference.agreement.evaluate": (
        "human_judge_agreement_report",
        "reader.preference.agreement",
    ),
    "reader.preference.pack.export": (
        "human_preference_evaluation_pack",
        "reader.preference.pack",
    ),
    "reader.preference.adjudication.record": (
        "human_preference_adjudication",
        "reader.preference.adjudication",
    ),
    "reader.behavior.session.start": (
        "reader_session_receipt",
        "reader.behavior.session",
    ),
    "reader.behavior.exposure.record": (
        "reader_exposure_receipt",
        "reader.behavior.exposure",
    ),
    "reader.behavior.outcome.record": (
        "reader_outcome_event_receipt",
        "reader.behavior.outcome",
    ),
    "reader.calibration.run": (
        "calibration_report",
        "reader.calibration.report",
    ),
    "reader.calibration.drift.record": (
        "calibration_drift_report",
        "reader.calibration.drift",
    ),
}
HANDLER_PREFIX = "novel_forge.reader_calibration"
OUTCOME_EVENT_TYPES = frozenset(
    {
        "CHAPTER_OPEN",
        "EFFECTIVE_READ",
        "COMPLETION",
        "EXIT_POSITION",
        "NEXT_CHAPTER_OPEN",
        "RETENTION_3",
        "RETENTION_10",
        "RETENTION_30",
        "FAVORITE",
        "FOLLOW",
        "NEGATIVE_FEEDBACK",
        "REFUND",
        "COMPLAINT",
    }
)


class _Handler:
    def execute(
        self, request: AuthorityHandlerRequest
    ) -> AuthorityHandlerOutput:
        payload = request.command.get("payload")
        if not isinstance(payload, dict):
            raise KernelError(
                "READER_CALIBRATION_INPUT_INVALID",
                "Reader calibration payload must be an object",
            )
        asset_type, output_key = DEFINITIONS[request.definition_name]
        reviewer_safe = request.definition_name == "reader.preference.pack.export"
        return AuthorityHandlerOutput(
            asset_type=asset_type,
            output_key=output_key,
            role="primary",
            content={
                "type": "".join(
                    part.title()
                    for part in request.definition_name.split(".")
                ),
                "contract_version": request.definition_name.replace(".", "-")
                + "-v1",
                **payload,
                "source_asset_versions": (
                    []
                    if reviewer_safe
                    else [item.asset_version_id for item in request.inputs]
                ),
            },
            qualification_policy="reader-calibration-v1",
            reference_asset_version_ids=tuple(
                item.asset_version_id for item in request.inputs
            ),
            evidence={
                "deterministic": True,
                "model_calls": 0,
                "usage": {"tokens": 0},
                "cost": {"amount": 0, "currency": "USD"},
            },
        )


class _Registry:
    def __init__(self) -> None:
        handler = _Handler()
        self.items = {
            (name, VERSION): AuthorityHandlerRegistration(
                definition_name=name,
                definition_version=VERSION,
                handler_key=f"{HANDLER_PREFIX}.{name}",
                handler_contract_version="reader-calibration-handler-v1",
                output_asset_type=asset_type,
                output_key=output_key,
                role="primary",
                completion_topic=f"{name}.completed",
                handler=handler,
            )
            for name, (asset_type, output_key) in DEFINITIONS.items()
        }

    @property
    def available_handler_keys(self) -> frozenset[str]:
        return frozenset(item.handler_key for item in self.items.values())

    def registration(
        self, definition_name: str, definition_version: str
    ) -> AuthorityHandlerRegistration:
        return self.items[(definition_name, definition_version)]


class PostgresReaderCalibrationAuthority:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        worker_id: str = "reader-calibration-worker",
    ) -> None:
        if not database_url or not application_build_id or len(commit_sha) != 40:
            raise ValueError(
                "Reader Calibration requires PostgreSQL and build identity"
            )
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.worker_id = worker_id
        self.registry = _Registry()

    def create_preference_task(
        self,
        *,
        project_id: str,
        workspace_id: str,
        book_id: str,
        reader_segment: str,
        evidence_level: str,
        idempotency_key: str,
        principal: Principal,
        campaign_id: str = "",
        protocol_version: str = "",
        evaluation_profile_version: str = "",
        required_evaluator_count: int = 0,
        evaluator_identity_classes: tuple[str, ...] = (),
        scope_manifest: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        principal.require("book.authority.execute", project_id)
        if evidence_level not in {"FIXTURE", "HUMAN_VERIFIED"}:
            raise ValueError("preference evidence level is invalid")
        versioned_protocol = bool(protocol_version)
        if versioned_protocol and (
            not campaign_id
            or not evaluation_profile_version
            or required_evaluator_count < 2
            or len(evaluator_identity_classes) < 2
            or not isinstance(scope_manifest, dict)
            or not scope_manifest
        ):
            raise ValueError("versioned blind preference protocol is incomplete")
        if not versioned_protocol and any(
            (
                campaign_id,
                evaluation_profile_version,
                required_evaluator_count,
                evaluator_identity_classes,
                scope_manifest,
            )
        ):
            raise ValueError("legacy preference task cannot contain partial protocol fields")
        operation_id = self._execute(
            "reader.preference.task.create",
            project_id=project_id,
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            payload={
                "book_id": book_id,
                "reader_segment": reader_segment,
                "task_type": "AB_BLIND",
                "evidence_level": evidence_level,
                "campaign_id": campaign_id,
                "protocol_version": protocol_version,
                "evaluation_profile_version": evaluation_profile_version,
                "required_evaluator_count": required_evaluator_count,
                "evaluator_identity_classes": list(evaluator_identity_classes),
                "scope_manifest": scope_manifest or {},
            },
            input_assets=(),
            principal=principal,
        )
        task_id = f"preference-task:{operation_id}"
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO human_preference_task(
                    task_id, project_id, book_id, reader_segment,
                    task_type, status, evidence_level,
                    created_by_operation_id, stable_idempotency_key,
                    campaign_id, protocol_version,
                    evaluation_profile_version, required_evaluator_count,
                    evaluator_identity_classes, scope_manifest,
                    blind_pack_status
                ) VALUES (
                    %s, %s, %s, %s, 'AB_BLIND', 'OPEN', %s, %s, %s,
                    NULLIF(%s, ''), NULLIF(%s, ''), NULLIF(%s, ''),
                    NULLIF(%s, 0), %s, %s,
                    CASE WHEN NULLIF(%s, '') IS NULL THEN NULL ELSE 'PENDING' END
                )
                ON CONFLICT(project_id, stable_idempotency_key) DO NOTHING
                """,
                [
                    task_id,
                    project_id,
                    book_id,
                    reader_segment,
                    evidence_level,
                    operation_id,
                    idempotency_key,
                    campaign_id,
                    protocol_version,
                    evaluation_profile_version,
                    required_evaluator_count,
                    Jsonb(list(evaluator_identity_classes))
                    if versioned_protocol
                    else None,
                    Jsonb(scope_manifest) if versioned_protocol else None,
                    protocol_version,
                ],
            )
            uow.cursor.execute(
                """
                SELECT task_id, project_id, book_id, reader_segment,
                       evidence_level, status, campaign_id,
                       protocol_version, evaluation_profile_version,
                       required_evaluator_count, blind_pack_status
                FROM human_preference_task
                WHERE project_id=%s AND stable_idempotency_key=%s
                """,
                [project_id, idempotency_key],
            )
            row = uow.cursor.fetchone()
            uow.commit()
        return dict(
            zip(
                (
                    "task_id",
                    "project_id",
                    "book_id",
                    "reader_segment",
                    "evidence_level",
                    "status",
                    "campaign_id",
                    "protocol_version",
                    "evaluation_profile_version",
                    "required_evaluator_count",
                    "blind_pack_status",
                ),
                row,
                strict=True,
            )
        )

    def add_blind_pair(
        self,
        *,
        task_id: str,
        asset_a_version_id: str,
        asset_b_version_id: str,
        randomization_key: str,
        principal: Principal,
        reversal_of_pair_id: str = "",
    ) -> dict[str, Any]:
        task = self._task(task_id)
        principal.require("book.authority.execute", task["project_id"])
        if reversal_of_pair_id:
            prior = self._pair(reversal_of_pair_id)
            if prior["task_id"] != task_id:
                raise KernelError(
                    "PREFERENCE_REVERSAL_SCOPE_MISMATCH",
                    "reversal pair belongs to another task",
                )
            left = str(prior["right_asset_version_id"])
            right = str(prior["left_asset_version_id"])
        else:
            left, right = blind_pair_order(
                asset_a_version_id,
                asset_b_version_id,
                randomization_key=randomization_key,
            )
        order = "AB" if left == asset_a_version_id else "BA"
        canonical = ":".join(sorted((asset_a_version_id, asset_b_version_id)))
        randomization_hash = "sha256:" + hashlib.sha256(
            randomization_key.encode()
        ).hexdigest()
        operation_id = self._execute(
            "reader.preference.pair.create",
            project_id=task["project_id"],
            workspace_id=f"workspace:{task['project_id']}",
            idempotency_key=(
                f"{task_id}:{canonical}:{order}:{randomization_hash}"
            ),
            payload={
                "task_id": task_id,
                "canonical_pair_key": canonical,
                "presentation_order": order,
                "blinded": True,
                "reversal_of_pair_id": reversal_of_pair_id,
            },
            input_assets=self._resolve(
                task["project_id"],
                (asset_a_version_id, asset_b_version_id),
            ),
            principal=principal,
        )
        pair_id = f"preference-pair:{operation_id}"
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO human_preference_pair(
                    pair_id, task_id, project_id, canonical_pair_key,
                    asset_a_version_id, asset_b_version_id,
                    left_asset_version_id, right_asset_version_id,
                    presentation_order, randomization_hash, blinded,
                    reversal_of_pair_id, created_by_operation_id
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE,
                    NULLIF(%s, ''), %s
                )
                ON CONFLICT(
                    task_id, canonical_pair_key, presentation_order
                ) DO NOTHING
                """,
                [
                    pair_id,
                    task_id,
                    task["project_id"],
                    canonical,
                    asset_a_version_id,
                    asset_b_version_id,
                    left,
                    right,
                    order,
                    randomization_hash,
                    reversal_of_pair_id,
                    operation_id,
                ],
            )
            uow.commit()
        return self._pair_by_key(task_id, canonical, order)

    def register_blind_packs(
        self,
        *,
        task_id: str,
        bundle: BlindExportBundle,
        principal: Principal,
    ) -> dict[str, dict[str, Any]]:

        task = self._task(task_id)
        principal.require("book.authority.execute", task["project_id"])
        if not task["protocol_version"] or not task["campaign_id"]:
            raise KernelError(
                "BLIND_PACK_PROTOCOL_REQUIRED",
                "evaluation packs require a versioned Quality campaign task",
            )
        results: dict[str, dict[str, Any]] = {}
        for reviewer_id, pack in bundle.packs.items():
            public = pack.public_payload
            if (
                public.get("protocol_version") != task["protocol_version"]
                or str(public.get("evaluation_version") or "")
                != task["evaluation_profile_version"]
            ):
                raise KernelError(
                    "BLIND_PACK_VERSION_MISMATCH",
                    "pack protocol differs from the frozen preference task",
                )
            input_version_ids = tuple(
                dict.fromkeys(
                    version_id
                    for mapping in pack.private_mapping
                    for version_id in (
                        mapping.candidate_a_asset_version_id,
                        mapping.candidate_b_asset_version_id,
                    )
                )
            )
            operation_id = self._execute(
                "reader.preference.pack.export",
                project_id=task["project_id"],
                workspace_id=f"workspace:{task['project_id']}",
                idempotency_key=f"{task_id}:{pack.pack_token}:export",
                payload=public,
                input_assets=self._resolve(task["project_id"], input_version_ids),
                principal=principal,
            )
            output = self._output(operation_id, "reader.preference.pack")
            chapter_count = sum(
                item.scope_type is BlindScope.CHAPTER for item in pack.private_mapping
            )
            arc_count = sum(
                item.scope_type is BlindScope.ARC for item in pack.private_mapping
            )
            with AuthorityUnitOfWork(self.database_url) as uow:
                uow.cursor.execute(
                    """
                    INSERT INTO human_preference_evaluation_pack(
                        pack_id, task_id, campaign_id, project_id,
                        reviewer_id, evaluator_identity_class,
                        protocol_version, evaluation_profile_version,
                        pack_asset_version_id, pack_content_hash,
                        private_mapping_hash, pair_count,
                        chapter_pair_count, arc_pair_count, status,
                        created_by_operation_id, exported_at
                    ) VALUES (
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        'EXPORTED',%s,NOW()
                    )
                    ON CONFLICT(task_id, reviewer_id) DO NOTHING
                    """,
                    [
                        pack.pack_token,
                        task_id,
                        task["campaign_id"],
                        task["project_id"],
                        reviewer_id,
                        str(public["evaluator_identity_class"]),
                        task["protocol_version"],
                        task["evaluation_profile_version"],
                        output["asset_version_id"],
                        pack.content_hash,
                        pack.private_mapping_hash,
                        len(pack.private_mapping),
                        chapter_count,
                        arc_count,
                        operation_id,
                    ],
                )
                uow.commit()
            for ordinal, mapping in enumerate(pack.private_mapping, start=1):
                subject = self._qualification_subject(mapping.subject_id)
                if (
                    subject["campaign_id"] != task["campaign_id"]
                    or subject["project_id"] != task["project_id"]
                    or subject["scope_type"] != mapping.scope_type.value
                    or int(subject["chapter_start"]) != mapping.chapter_start
                    or int(subject["chapter_end"]) != mapping.chapter_end
                ):
                    raise KernelError(
                        "BLIND_PACK_SUBJECT_SCOPE_MISMATCH",
                        "private pair mapping differs from its Quality subject",
                    )
                expected_ids = {
                    subject["canonical_asset_version_id"],
                    subject["baseline_asset_version_id"],
                }
                if {
                    mapping.candidate_a_asset_version_id,
                    mapping.candidate_b_asset_version_id,
                } != expected_ids:
                    raise KernelError(
                        "BLIND_PACK_PRIVATE_MAPPING_MISMATCH",
                        "private pair mapping does not preserve the frozen candidates",
                    )
                pair_operation_id = self._execute(
                    "reader.preference.pair.create",
                    project_id=task["project_id"],
                    workspace_id=f"workspace:{task['project_id']}",
                    idempotency_key=f"{task_id}:{mapping.pair_token}",
                    payload={
                        "task_id": task_id,
                        "pack_token": pack.pack_token,
                        "pair_token": mapping.pair_token,
                        "scope_type": mapping.scope_type.value,
                        "chapter_start": mapping.chapter_start,
                        "chapter_end": mapping.chapter_end,
                        "assigned_reviewer_token": public["reviewer_token"],
                        "blinded": True,
                    },
                    input_assets=self._resolve(
                        task["project_id"],
                        (
                            subject["canonical_asset_version_id"],
                            subject["baseline_asset_version_id"],
                        ),
                    ),
                    principal=principal,
                )
                pair_id = f"preference-pair:{pair_operation_id}"
                order = "AB" if mapping.canonical_position == "A" else "BA"
                canonical_key = ":".join(sorted(expected_ids))
                with AuthorityUnitOfWork(self.database_url) as uow:
                    uow.cursor.execute(
                        """
                        INSERT INTO human_preference_pair(
                            pair_id, task_id, project_id, canonical_pair_key,
                            asset_a_version_id, asset_b_version_id,
                            left_asset_version_id, right_asset_version_id,
                            presentation_order, randomization_hash, blinded,
                            reversal_of_pair_id, created_by_operation_id,
                            subject_id, pack_id, protocol_version, scope_type,
                            chapter_start, chapter_end, arc_plan_version_ids,
                            pair_ordinal, assigned_reviewer_id,
                            blind_pair_token, private_mapping_hash
                        ) VALUES (
                            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,NULL,%s,
                            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                        )
                        ON CONFLICT(task_id, canonical_pair_key, presentation_order)
                        DO NOTHING
                        """,
                        [
                            pair_id,
                            task_id,
                            task["project_id"],
                            canonical_key,
                            subject["canonical_asset_version_id"],
                            subject["baseline_asset_version_id"],
                            mapping.candidate_a_asset_version_id,
                            mapping.candidate_b_asset_version_id,
                            order,
                            pack.private_mapping_hash,
                            pair_operation_id,
                            mapping.subject_id,
                            pack.pack_token,
                            task["protocol_version"],
                            mapping.scope_type.value,
                            mapping.chapter_start,
                            mapping.chapter_end,
                            Jsonb(subject["arc_plan_version_ids"]),
                            ordinal,
                            reviewer_id,
                            mapping.pair_token,
                            pack.private_mapping_hash,
                        ],
                    )
                    uow.commit()
            results[reviewer_id] = {
                "pack_id": pack.pack_token,
                "pack_asset_version_id": output["asset_version_id"],
                "pack_content_hash": pack.content_hash,
                "pair_count": len(pack.private_mapping),
                "status": "EXPORTED",
            }
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                UPDATE human_preference_task
                SET blind_pack_status='EXPORTED', updated_at=NOW()
                WHERE task_id=%s AND blind_pack_status IN ('PENDING','EXPORTED')
                """,
                [task_id],
            )
            uow.commit()
        return results

    def reviewer_pack(
        self,
        *,
        pack_id: str,
        reviewer_id: str,
        principal: Principal,
    ) -> dict[str, Any]:
        pack = self._pack(pack_id)
        principal.require("book.authority.execute", pack["project_id"])
        if pack["reviewer_id"] != reviewer_id:
            raise KernelError(
                "BLIND_PACK_REVIEWER_SCOPE_MISMATCH",
                "an evaluator cannot read another evaluator's pack",
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT version.content
                FROM authority_asset_version AS version
                WHERE version.asset_version_id=%s
                """,
                [pack["pack_asset_version_id"]],
            )
            content = dict(uow.cursor.fetchone()[0])
        content.pop("source_asset_versions", None)
        return content

    def record_blind_decision(
        self,
        decision: HumanBlindDecision,
        *,
        principal: Principal,
    ) -> dict[str, Any]:
        pair = self._pair_by_token(decision.pair_token)
        task = self._task(pair["task_id"])
        principal.require("book.authority.execute", pair["project_id"])
        if task["status"] != "OPEN":
            raise KernelError(
                "PREFERENCE_TASK_CLOSED",
                "decisions cannot be added after agreement is finalized",
            )
        if (
            pair["assigned_reviewer_id"] != decision.reviewer_id
            or pair["protocol_version"] != decision.protocol_version
            or task["evaluation_profile_version"] != decision.evaluation_version
            or pair["scope_type"] != decision.scope_type.value
            or int(pair["chapter_start"]) != decision.chapter_start
            or int(pair["chapter_end"]) != decision.chapter_end
        ):
            raise KernelError(
                "BLIND_DECISION_SCOPE_MISMATCH",
                "decision differs from its assigned blinded pair",
            )
        preferred = (
            pair["left_asset_version_id"]
            if decision.choice is PreferenceChoice.A
            else pair["right_asset_version_id"]
            if decision.choice is PreferenceChoice.B
            else None
        )
        scores = {
            dimension: dict(value)
            for dimension, value in decision.dimension_scores.items()
        }
        reviewer_group = (
            "EDITOR"
            if decision.evaluator_identity_class.value
            in {"PROFESSIONAL_EDITOR", "AUTHOR_EDITOR"}
            else "READER"
        )
        operation_id = self._execute(
            "reader.preference.decision.record",
            project_id=pair["project_id"],
            workspace_id=f"workspace:{pair['project_id']}",
            idempotency_key=f"{pair['pair_id']}:{decision.reviewer_id}",
            payload={
                "pair_token": decision.pair_token,
                "reviewer_group": reviewer_group,
                "choice": decision.choice.value,
                "dimension_scores": scores,
                "confidence": decision.confidence,
                "rationale": decision.rationale,
                "evidence_spans": list(decision.evidence_spans),
                "protocol_version": decision.protocol_version,
                "evaluation_version": decision.evaluation_version,
            },
            input_assets=(),
            principal=principal,
        )
        decision_id = f"preference-decision:{operation_id}"
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO human_preference_decision(
                    decision_id, pair_id, project_id, reviewer_id,
                    reviewer_group, choice, preferred_asset_version_id,
                    evidence_spans, confidence, annotation_reason,
                    position_revealed_after_decision,
                    decision_operation_id, pack_id, protocol_version,
                    evaluation_version, evaluator_identity_class,
                    scope_type, dimension_scores, adjudication_status,
                    submitted_at
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,FALSE,%s,%s,%s,%s,%s,
                    %s,%s,'UNREVIEWED',NOW()
                )
                ON CONFLICT(pair_id, reviewer_id) DO NOTHING
                """,
                [
                    decision_id,
                    pair["pair_id"],
                    pair["project_id"],
                    decision.reviewer_id,
                    reviewer_group,
                    decision.choice.value,
                    preferred,
                    Jsonb(list(decision.evidence_spans)),
                    decision.confidence,
                    decision.rationale,
                    operation_id,
                    pair["pack_id"],
                    decision.protocol_version,
                    decision.evaluation_version,
                    decision.evaluator_identity_class.value,
                    decision.scope_type.value,
                    Jsonb(scores),
                ],
            )
            uow.cursor.execute(
                """
                SELECT decision_id, choice, confidence, dimension_scores,
                       adjudication_status
                FROM human_preference_decision
                WHERE pair_id=%s AND reviewer_id=%s
                """,
                [pair["pair_id"], decision.reviewer_id],
            )
            row = uow.cursor.fetchone()
            uow.cursor.execute(
                """
                UPDATE human_preference_evaluation_pack AS pack
                SET status='COMPLETED', completed_at=NOW()
                WHERE pack.pack_id=%s
                  AND pack.pair_count=(
                      SELECT COUNT(*)
                      FROM human_preference_decision AS decision
                      WHERE decision.pack_id=pack.pack_id
                  )
                """,
                [pair["pack_id"]],
            )
            uow.commit()
        return {
            "decision_id": str(row[0]),
            "pair_token": decision.pair_token,
            "choice": str(row[1]),
            "confidence": float(row[2]),
            "dimension_scores": dict(row[3]),
            "adjudication_status": str(row[4]),
        }

    def reviewer_decisions(
        self,
        *,
        pack_id: str,
        reviewer_id: str,
        principal: Principal,
    ) -> list[dict[str, Any]]:
        pack = self._pack(pack_id)
        principal.require("book.authority.execute", pack["project_id"])
        if pack["reviewer_id"] != reviewer_id:
            raise KernelError(
                "BLIND_DECISION_REVIEWER_SCOPE_MISMATCH",
                "an evaluator cannot read another evaluator's decisions",
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT pair.blind_pair_token, decision.choice,
                       decision.dimension_scores, decision.confidence,
                       decision.annotation_reason, decision.evidence_spans,
                       decision.adjudication_status
                FROM human_preference_decision AS decision
                JOIN human_preference_pair AS pair
                  ON pair.pair_id=decision.pair_id
                WHERE decision.pack_id=%s AND decision.reviewer_id=%s
                ORDER BY pair.pair_ordinal
                """,
                [pack_id, reviewer_id],
            )
            fields = (
                "pair_token",
                "choice",
                "dimension_scores",
                "confidence",
                "rationale",
                "evidence_spans",
                "adjudication_status",
            )
            return [dict(zip(fields, row, strict=True)) for row in uow.cursor.fetchall()]

    def adjudicate_blind_subject(
        self,
        *,
        task_id: str,
        subject_id: str,
        adjudicator_id: str,
        resolved_choice: PreferenceChoice | None,
        rationale: str,
        dimension_scores: dict[str, Any],
        principal: Principal,
    ) -> dict[str, Any]:

        task = self._task(task_id)
        principal.require("book.authority.execute", task["project_id"])
        if not adjudicator_id or not rationale.strip():
            raise ValueError("adjudication identity and rationale are required")
        if resolved_choice is PreferenceChoice.REJECT_BOTH:
            raise ValueError("REJECT_BOTH is historical-only")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT decision.decision_id, decision.choice,
                       decision.preferred_asset_version_id,
                       decision.dimension_scores
                FROM human_preference_decision AS decision
                JOIN human_preference_pair AS pair
                  ON pair.pair_id=decision.pair_id
                WHERE pair.task_id=%s AND pair.subject_id=%s
                ORDER BY decision.reviewer_id
                """,
                [task_id, subject_id],
            )
            raw_rows = uow.cursor.fetchall()
        if len(raw_rows) < 2:
            raise KernelError(
                "BLIND_ADJUDICATION_DECISIONS_REQUIRED",
                "adjudication requires two independent human decisions",
            )
        source_ids = [str(row[0]) for row in raw_rows]
        raw_preferences = {
            (str(row[1]), str(row[2] or "")) for row in raw_rows
        }
        if resolved_choice is not None:
            status = "ADJUDICATED"
        elif len(raw_preferences) == 1:
            status = "AGREED"
        else:
            status = "DISAGREED"
        payload = {
            "task_id": task_id,
            "subject_id": subject_id,
            "status": status,
            "resolved_choice": (
                resolved_choice.value if resolved_choice is not None else None
            ),
            "dimension_scores": dimension_scores,
            "source_decision_ids": source_ids,
            "adjudicator_id": adjudicator_id,
            "evidence_class": "SUBJECTIVE_ADJUDICATION_NOT_GROUND_TRUTH",
            "rationale": rationale,
            "protocol_version": task["protocol_version"],
            "evaluation_version": task["evaluation_profile_version"],
        }
        operation_id = self._execute(
            "reader.preference.adjudication.record",
            project_id=task["project_id"],
            workspace_id=f"workspace:{task['project_id']}",
            idempotency_key=f"{task_id}:{subject_id}:adjudication:v1",
            payload=payload,
            input_assets=(),
            principal=principal,
        )
        output = self._output(operation_id, "reader.preference.adjudication")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO human_preference_adjudication(
                    adjudication_id, campaign_id, task_id, subject_id,
                    project_id, protocol_version, evaluation_version,
                    status, resolved_choice, dimension_scores,
                    source_decision_ids, adjudicator_id,
                    evaluator_identity_class, rationale,
                    adjudication_asset_version_id,
                    adjudication_content_hash, adjudication_operation_id
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    'PROFESSIONAL_EDITOR',%s,%s,%s,%s
                )
                ON CONFLICT(task_id, subject_id) DO NOTHING
                """,
                [
                    f"preference-adjudication:{operation_id}",
                    task["campaign_id"],
                    task_id,
                    subject_id,
                    task["project_id"],
                    task["protocol_version"],
                    task["evaluation_profile_version"],
                    status,
                    resolved_choice.value if resolved_choice is not None else None,
                    Jsonb(dimension_scores),
                    Jsonb(source_ids),
                    adjudicator_id,
                    rationale,
                    output["asset_version_id"],
                    output["content_hash"],
                    operation_id,
                ],
            )
            uow.cursor.execute(
                """
                UPDATE human_preference_decision
                SET adjudication_status=%s
                WHERE decision_id=ANY(%s)
                  AND adjudication_status IN (
                      'UNREVIEWED','AGREED','DISAGREED','ADJUDICATED'
                  )
                """,
                [status, source_ids],
            )
            uow.cursor.execute(
                """
                SELECT adjudication_id, status, resolved_choice,
                       source_decision_ids, evidence_class
                FROM (
                    SELECT adjudication_id, status, resolved_choice,
                           source_decision_ids,
                           'SUBJECTIVE_ADJUDICATION_NOT_GROUND_TRUTH' AS evidence_class
                    FROM human_preference_adjudication
                    WHERE task_id=%s AND subject_id=%s
                ) AS recorded
                """,
                [task_id, subject_id],
            )
            row = uow.cursor.fetchone()
            uow.commit()
        fields = (
            "adjudication_id",
            "status",
            "resolved_choice",
            "source_decision_ids",
            "evidence_class",
        )
        return dict(zip(fields, row, strict=True))

    def record_preference_decision(
        self,
        *,
        pair_id: str,
        reviewer_id: str,
        reviewer_group: str,
        choice: PreferenceChoice,
        evidence_spans: list[dict[str, Any]],
        confidence: float,
        annotation_reason: str,
        principal: Principal,
    ) -> dict[str, Any]:
        pair = self._pair(pair_id)
        principal.require("book.authority.execute", pair["project_id"])
        task = self._task(pair["task_id"])
        if task["status"] != "OPEN":
            raise KernelError(
                "PREFERENCE_TASK_CLOSED",
                "decisions cannot be added after agreement is finalized",
            )
        if reviewer_group not in {"EDITOR", "READER"}:
            raise ValueError("reviewer group is invalid")
        preferred = (
            pair["asset_a_version_id"]
            if choice is PreferenceChoice.A
            else pair["asset_b_version_id"]
            if choice is PreferenceChoice.B
            else None
        )
        operation_id = self._execute(
            "reader.preference.decision.record",
            project_id=pair["project_id"],
            workspace_id=f"workspace:{pair['project_id']}",
            idempotency_key=f"{pair_id}:{reviewer_id}",
            payload={
                "pair_id": pair_id,
                "reviewer_group": reviewer_group,
                "choice": choice.value,
                "evidence_spans": evidence_spans,
                "confidence": confidence,
                "annotation_reason": annotation_reason,
            },
            input_assets=(),
            principal=principal,
        )
        decision_id = f"preference-decision:{operation_id}"
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO human_preference_decision(
                    decision_id, pair_id, project_id, reviewer_id,
                    reviewer_group, choice, preferred_asset_version_id,
                    evidence_spans, confidence, annotation_reason,
                    position_revealed_after_decision,
                    decision_operation_id
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s
                )
                ON CONFLICT(pair_id, reviewer_id) DO NOTHING
                """,
                [
                    decision_id,
                    pair_id,
                    pair["project_id"],
                    reviewer_id,
                    reviewer_group,
                    choice.value,
                    preferred,
                    Jsonb(evidence_spans),
                    confidence,
                    annotation_reason,
                    operation_id,
                ],
            )
            uow.commit()
        return {
            "decision_id": decision_id,
            "pair_id": pair_id,
            "choice": choice.value,
            "preferred_asset_version_id": preferred,
        }

    def build_agreement_report(
        self, task_id: str, *, principal: Principal
    ) -> dict[str, Any]:
        task = self._task(task_id)
        principal.require("book.authority.execute", task["project_id"])
        decisions = self._decisions(task_id)
        if not decisions:
            raise KernelError(
                "PREFERENCE_DECISIONS_REQUIRED",
                "agreement requires at least one preference decision",
            )
        agreement = human_agreement_report(decisions)
        bias = preference_bias_report(decisions)
        editor = {
            item["preferred_asset_version_id"]
            for item in decisions
            if item["reviewer_group"] == "EDITOR"
            and item["preferred_asset_version_id"]
        }
        reader = {
            item["preferred_asset_version_id"]
            for item in decisions
            if item["reviewer_group"] == "READER"
            and item["preferred_asset_version_id"]
        }
        disagreement = (
            0.0
            if not editor or not reader or editor & reader
            else 1.0
        )
        payload = {
            "task_id": task_id,
            **agreement,
            **bias,
            "reader_editor_disagreement": disagreement,
            "sample_coverage": {
                "decision_count": len(decisions),
                "reader_segment": task["reader_segment"],
                "evidence_level": task["evidence_level"],
            },
            "human_preference_anchored": (
                task["evidence_level"] == "HUMAN_VERIFIED"
                and agreement["status"] == "MEASURED"
            ),
        }
        operation_id = self._execute(
            "reader.preference.agreement.evaluate",
            project_id=task["project_id"],
            workspace_id=f"workspace:{task['project_id']}",
            idempotency_key=f"{task_id}:agreement:v1",
            payload=payload,
            input_assets=(),
            principal=principal,
        )
        output = self._output(
            operation_id, "reader.preference.agreement"
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO human_judge_agreement_report(
                    report_id, task_id, project_id,
                    report_asset_version_id, agreement_rate,
                    position_bias_detected, reader_editor_disagreement,
                    sample_coverage, created_by_operation_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(task_id) DO NOTHING
                """,
                [
                    f"agreement-report:{operation_id}",
                    task_id,
                    task["project_id"],
                    output["asset_version_id"],
                    agreement["agreement_rate"],
                    bias["position_bias_detected"],
                    disagreement,
                    Jsonb(payload["sample_coverage"]),
                    operation_id,
                ],
            )
            uow.cursor.execute(
                """
                UPDATE human_preference_task
                SET status='CLOSED', updated_at=NOW()
                WHERE task_id=%s AND status IN ('OPEN', 'CLOSED')
                """,
                [task_id],
            )
            uow.commit()
        return payload | {
            "operation_id": operation_id,
            "report_asset_version_id": output["asset_version_id"],
        }

    def start_reader_session(
        self,
        *,
        project_id: str,
        book_id: str,
        reader_subject_ref: str,
        reader_segment: str,
        platform: str,
        consent_policy_version: str,
        idempotency_key: str,
        principal: Principal,
    ) -> dict[str, Any]:
        principal.require("book.authority.execute", project_id)
        operation_id = self._execute(
            "reader.behavior.session.start",
            project_id=project_id,
            workspace_id=f"workspace:{project_id}",
            idempotency_key=idempotency_key,
            payload={
                "book_id": book_id,
                "reader_segment": reader_segment,
                "platform": platform,
                "consent_policy_version": consent_policy_version,
                "pseudonymized": True,
            },
            input_assets=(),
            principal=principal,
        )
        session_id = f"reader-session:{operation_id}"
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO reader_session(
                    reader_session_id, project_id, book_id,
                    reader_subject_ref, reader_segment, platform,
                    consent_policy_version, pseudonymized, started_at,
                    created_by_operation_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE, NOW(), %s)
                ON CONFLICT(reader_session_id) DO NOTHING
                """,
                [
                    session_id,
                    project_id,
                    book_id,
                    reader_subject_ref,
                    reader_segment,
                    platform,
                    consent_policy_version,
                    operation_id,
                ],
            )
            uow.commit()
        return {
            "reader_session_id": session_id,
            "project_id": project_id,
            "book_id": book_id,
            "reader_segment": reader_segment,
            "platform": platform,
        }

    def record_exposure(
        self,
        *,
        reader_session_id: str,
        chapter_asset_version_id: str,
        idempotency_key: str,
        principal: Principal,
    ) -> dict[str, Any]:
        session = self._session(reader_session_id)
        principal.require("book.authority.execute", session["project_id"])
        operation_id = self._execute(
            "reader.behavior.exposure.record",
            project_id=session["project_id"],
            workspace_id=f"workspace:{session['project_id']}",
            idempotency_key=idempotency_key,
            payload={
                "reader_session_id": reader_session_id,
                "book_id": session["book_id"],
                "reader_segment": session["reader_segment"],
                "platform": session["platform"],
                "denominator_eligible": True,
            },
            input_assets=self._resolve(
                session["project_id"], (chapter_asset_version_id,)
            ),
            principal=principal,
        )
        exposure_id = f"reader-exposure:{operation_id}"
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO reader_exposure(
                    exposure_id, project_id, book_id, reader_session_id,
                    reader_segment, platform, chapter_asset_version_id,
                    exposed_at, denominator_eligible,
                    exposure_operation_id, stable_idempotency_key
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, NOW(), TRUE, %s, %s
                )
                ON CONFLICT(project_id, stable_idempotency_key) DO NOTHING
                """,
                [
                    exposure_id,
                    session["project_id"],
                    session["book_id"],
                    reader_session_id,
                    session["reader_segment"],
                    session["platform"],
                    chapter_asset_version_id,
                    operation_id,
                    idempotency_key,
                ],
            )
            uow.commit()
        return self._exposure_by_key(
            session["project_id"], idempotency_key
        )

    def record_outcome(
        self,
        *,
        exposure_id: str,
        event_type: str,
        event_value: dict[str, Any],
        idempotency_key: str,
        principal: Principal,
    ) -> dict[str, Any]:
        exposure = self._exposure(exposure_id)
        require_exposure_denominator(
            exposure_id=exposure_id,
            project_id=exposure["project_id"],
            reader_segment=exposure["reader_segment"],
        )
        principal.require("book.authority.execute", exposure["project_id"])
        if event_type not in OUTCOME_EVENT_TYPES:
            raise KernelError(
                "READER_OUTCOME_EVENT_TYPE_INVALID",
                "Reader outcome event type is unsupported",
            )
        operation_id = self._execute(
            "reader.behavior.outcome.record",
            project_id=exposure["project_id"],
            workspace_id=f"workspace:{exposure['project_id']}",
            idempotency_key=idempotency_key,
            payload={
                "exposure_id": exposure_id,
                "reader_session_id": exposure["reader_session_id"],
                "book_id": exposure["book_id"],
                "reader_segment": exposure["reader_segment"],
                "platform": exposure["platform"],
                "event_type": event_type,
                "event_value": event_value,
            },
            input_assets=(),
            principal=principal,
        )
        event_id = f"reader-outcome-event:{operation_id}"
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO reader_outcome_event(
                    outcome_event_id, project_id, book_id, exposure_id,
                    reader_session_id, reader_segment, platform,
                    event_type, event_value, occurred_at,
                    event_operation_id, stable_idempotency_key
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s
                )
                ON CONFLICT(project_id, stable_idempotency_key) DO NOTHING
                """,
                [
                    event_id,
                    exposure["project_id"],
                    exposure["book_id"],
                    exposure_id,
                    exposure["reader_session_id"],
                    exposure["reader_segment"],
                    exposure["platform"],
                    event_type,
                    Jsonb(event_value),
                    operation_id,
                    idempotency_key,
                ],
            )
            uow.commit()
        return {
            "outcome_event_id": event_id,
            "project_id": exposure["project_id"],
            "reader_segment": exposure["reader_segment"],
            "event_type": event_type,
            "exposure_id": exposure_id,
        }

    def run_calibration(
        self,
        *,
        project_id: str,
        scope: CalibrationScope,
        observations: list[tuple[float, int]],
        minimum_sample_size: int,
        input_manifest_version_id: str,
        evidence_level: str,
        idempotency_key: str,
        principal: Principal,
    ) -> dict[str, Any]:
        principal.require("book.authority.execute", project_id)
        if evidence_level not in {"FIXTURE", "BEHAVIOR_CALIBRATED"}:
            raise ValueError("calibration evidence level is invalid")
        metrics = calibration_metrics(
            observations, minimum_sample_size=minimum_sample_size
        )
        behavior_evidence_count = self._behavior_evidence_count(
            project_id=project_id,
            platform=scope.platform,
            reader_segment=scope.reader_segment,
        )
        if (
            evidence_level != "BEHAVIOR_CALIBRATED"
            or behavior_evidence_count < minimum_sample_size
        ):
            metrics = {
                **metrics,
                "calibration_status": "INSUFFICIENT_DATA",
                "behavior_probability_allowed": False,
                "evidence_boundary": "NON_PRODUCTION_OR_FIXTURE_DATA",
                "behavior_evidence_count": behavior_evidence_count,
            }
        status = str(metrics["calibration_status"])
        operation_id = self._execute(
            "reader.calibration.run",
            project_id=project_id,
            workspace_id=f"workspace:{project_id}",
            idempotency_key=idempotency_key,
            payload={
                "scope": asdict(scope),
                "metrics": metrics,
                "evidence_level": evidence_level,
                "judge_mode": "SHADOW",
            },
            input_assets=self._resolve(
                project_id, (input_manifest_version_id,)
            ),
            principal=principal,
        )
        scope_digest = hashlib.sha256(
            repr(asdict(scope)).encode()
        ).hexdigest()
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT COALESCE(MAX(profile_version), 0) + 1
                FROM calibration_profile
                WHERE project_id=%s AND platform=%s AND genre=%s
                  AND subgenre=%s AND chapter_type=%s
                  AND reader_segment=%s AND judge_profile=%s
                  AND model_version=%s
                """,
                [
                    project_id,
                    scope.platform,
                    scope.genre,
                    scope.subgenre,
                    scope.chapter_type,
                    scope.reader_segment,
                    scope.judge_profile,
                    scope.model_version,
                ],
            )
            profile_version = int(uow.cursor.fetchone()[0])
        profile_id = (
            f"calibration-profile:{project_id}:{scope_digest}:"
            f"v{profile_version}"
        )
        run_id = f"calibration-run:{operation_id}"
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO calibration_profile(
                    profile_id, project_id, platform, genre, subgenre,
                    chapter_type, reader_segment, judge_profile,
                    model_version, profile_version, minimum_sample_size,
                    sample_size, status, judge_mode, evidence_level,
                    created_by_operation_id
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, 'SHADOW', %s, %s
                )
                ON CONFLICT(
                    project_id, platform, genre, subgenre, chapter_type,
                    reader_segment, judge_profile, model_version,
                    profile_version
                ) DO NOTHING
                """,
                [
                    profile_id,
                    project_id,
                    scope.platform,
                    scope.genre,
                    scope.subgenre,
                    scope.chapter_type,
                    scope.reader_segment,
                    scope.judge_profile,
                    scope.model_version,
                    profile_version,
                    minimum_sample_size,
                    len(observations),
                    status,
                    evidence_level,
                    operation_id,
                ],
            )
            uow.cursor.execute(
                """
                INSERT INTO calibration_run(
                    calibration_run_id, profile_id, project_id,
                    operation_id, input_manifest_ref, sample_size,
                    status, completed_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT(operation_id) DO NOTHING
                """,
                [
                    run_id,
                    profile_id,
                    project_id,
                    operation_id,
                    input_manifest_version_id,
                    len(observations),
                    status,
                ],
            )
            for name in (
                "brier_score",
                "log_loss",
                "calibration_error",
            ):
                uow.cursor.execute(
                    """
                    INSERT INTO calibration_metric(
                        calibration_metric_id, calibration_run_id,
                        metric_name, metric_value
                    ) VALUES (%s, %s, %s, %s)
                    ON CONFLICT(calibration_run_id, metric_name) DO NOTHING
                    """,
                    [
                        f"calibration-metric:{run_id}:{name}",
                        run_id,
                        name,
                        metrics[name],
                    ],
                )
            uow.commit()
        return {
            "profile_id": profile_id,
            "calibration_run_id": run_id,
            "status": status,
            "judge_mode": "SHADOW",
            "metrics": metrics,
            "behavior_calibrated": (
                status == "VALID"
                and evidence_level == "BEHAVIOR_CALIBRATED"
            ),
        }

    def record_drift(
        self,
        *,
        profile_id: str,
        drift_type: str,
        severity: str,
        evidence: dict[str, Any],
        principal: Principal,
    ) -> dict[str, Any]:
        profile = self._profile(profile_id)
        principal.require("book.authority.execute", profile["project_id"])
        operation_id = self._execute(
            "reader.calibration.drift.record",
            project_id=profile["project_id"],
            workspace_id=f"workspace:{profile['project_id']}",
            idempotency_key=(
                f"{profile_id}:drift:{drift_type}:{severity}:"
                f"{hashlib.sha256(repr(evidence).encode()).hexdigest()}"
            ),
            payload={
                "profile_id": profile_id,
                "drift_type": drift_type,
                "severity": severity,
                "evidence": evidence,
            },
            input_assets=(),
            principal=principal,
        )
        severe = severity == "SEVERE"
        mode = mode_after_drift(
            JudgeMode(str(profile["judge_mode"])),
            severe_drift=severe,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO calibration_validity(
                    validity_id, profile_id, project_id, drift_type,
                    severity, status, evidence, detected_by_operation_id
                ) VALUES (%s, %s, %s, %s, %s, 'CURRENT', %s, %s)
                """,
                [
                    f"calibration-validity:{operation_id}",
                    profile_id,
                    profile["project_id"],
                    drift_type,
                    severity,
                    Jsonb(evidence),
                    operation_id,
                ],
            )
            if severe:
                uow.cursor.execute(
                    """
                    UPDATE calibration_profile
                    SET status='DRIFTED', judge_mode='SHADOW'
                    WHERE profile_id=%s
                    """,
                    [profile_id],
                )
            uow.commit()
        return {
            "profile_id": profile_id,
            "status": "DRIFTED" if severe else profile["status"],
            "judge_mode": mode.value,
        }

    def resolve_profile(
        self, project_id: str, scope: CalibrationScope
    ) -> dict[str, Any] | None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT profile_id, platform, genre, subgenre, chapter_type,
                       reader_segment, judge_profile, model_version,
                       sample_size, minimum_sample_size, status
                FROM calibration_profile
                WHERE project_id=%s
                """,
                [project_id],
            )
            rows = uow.cursor.fetchall()
        candidates = [
            CalibrationCandidate(
                profile_id=str(row[0]),
                scope=CalibrationScope(*map(str, row[1:8])),
                sample_size=int(row[8]),
                minimum_sample_size=int(row[9]),
                status=CalibrationStatus(str(row[10])),
            )
            for row in rows
        ]
        selected = resolve_calibration_profile(scope, candidates)
        return asdict(selected) if selected is not None else None

    def _execute(
        self,
        definition: str,
        *,
        project_id: str,
        workspace_id: str,
        idempotency_key: str,
        payload: dict[str, Any],
        input_assets: tuple[dict[str, str], ...],
        principal: Principal,
    ) -> str:
        self._register_definitions()
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": definition,
                "definition_version": VERSION,
                "project_id": project_id,
                "workspace_id": workspace_id,
                "actor_id": principal.principal_id,
                "idempotency_scope": "project:reader-calibration",
                "idempotency_key": idempotency_key,
                "trace_id": f"{idempotency_key}:trace",
                "span_id": str(uuid4()),
                "correlation_id": f"reader-calibration:{project_id}",
                "causation_id": "",
                "input": {
                    "project_id": project_id,
                    "input_asset_version_ids": [
                        item["asset_version_id"] for item in input_assets
                    ],
                    "payload": payload,
                },
                "input_assets": list(input_assets),
            },
            context=AdmissionContext(
                actor_id=principal.principal_id,
                permissions=frozenset({"book.authority.execute"}),
                available_handlers=self.registry.available_handler_keys,
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
        )
        operation_id = str(admitted["operation_id"])
        with AuthorityUnitOfWork(self.database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(
                operation_id, project_id
            )
        if state["status"] == "ADMITTED":
            transition_operation(
                self.database_url,
                OperationTransitionCommand(
                    operation_id=operation_id,
                    project_id=project_id,
                    expected_version=int(state["version"]),
                    expected_status="ADMITTED",
                    target_status="READY",
                    actor_id=principal.principal_id,
                    reason="Reader calibration inputs frozen",
                    trace_id=f"{idempotency_key}:trace",
                    correlation_id=f"reader-calibration:{project_id}",
                    causation_id="",
                ),
            )
            start_saga(
                self.database_url,
                GraphCommandContext(
                    project_id,
                    principal.principal_id,
                    f"{idempotency_key}:trace",
                    f"reader-calibration:{project_id}",
                ),
                root_operation_id=operation_id,
            )
        ContentAuthorityScheduler(
            self.database_url,
            registry=self.registry,
            worker_id=self.worker_id,
        ).run_or_recover(
            operation_id=operation_id,
            project_id=project_id,
        )
        return operation_id

    def _register_definitions(self) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            for name, (asset_type, output_key) in DEFINITIONS.items():
                uow.repositories.definitions.register(
                    _definition(
                        name,
                        asset_type,
                        output_key,
                        application_build_id=self.application_build_id,
                        commit_sha=self.commit_sha,
                    )
                )
            uow.commit()

    def _resolve(
        self, project_id: str, version_ids: tuple[str, ...]
    ) -> tuple[dict[str, str], ...]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            result: list[dict[str, str]] = []
            for version_id in version_ids:
                uow.cursor.execute(
                    """
                    SELECT version.content_hash
                    FROM authority_asset_version AS version
                    JOIN authority_asset AS asset
                      ON asset.asset_id=version.asset_id
                    WHERE version.asset_version_id=%s
                      AND asset.project_id=%s
                    """,
                    [version_id, project_id],
                )
                row = uow.cursor.fetchone()
                if row is None:
                    raise KernelError(
                        "READER_CALIBRATION_INPUT_NOT_FOUND",
                        "Reader calibration input is outside the Project",
                    )
                result.append(
                    {
                        "asset_version_id": version_id,
                        "content_hash": str(row[0]),
                    }
                )
        return tuple(result)

    def _task(self, task_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT task_id, project_id, book_id, reader_segment,
                       evidence_level, status, campaign_id,
                       protocol_version, evaluation_profile_version,
                       required_evaluator_count, blind_pack_status
                FROM human_preference_task WHERE task_id=%s
                """,
                [task_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "PREFERENCE_TASK_NOT_FOUND", "preference task does not exist"
            )
        return dict(
            zip(
                (
                    "task_id",
                    "project_id",
                    "book_id",
                    "reader_segment",
                    "evidence_level",
                    "status",
                    "campaign_id",
                    "protocol_version",
                    "evaluation_profile_version",
                    "required_evaluator_count",
                    "blind_pack_status",
                ),
                row,
                strict=True,
            )
        )

    def _pair(self, pair_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT pair_id, task_id, project_id, canonical_pair_key,
                       asset_a_version_id, asset_b_version_id,
                       left_asset_version_id, right_asset_version_id,
                       presentation_order, subject_id, pack_id,
                       protocol_version, scope_type, chapter_start,
                       chapter_end, arc_plan_version_ids, pair_ordinal,
                       assigned_reviewer_id, blind_pair_token,
                       private_mapping_hash
                FROM human_preference_pair WHERE pair_id=%s
                """,
                [pair_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "PREFERENCE_PAIR_NOT_FOUND", "preference pair does not exist"
            )
        return self._pair_row(row)

    def _pair_by_key(
        self, task_id: str, canonical: str, order: str
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT pair_id, task_id, project_id, canonical_pair_key,
                       asset_a_version_id, asset_b_version_id,
                       left_asset_version_id, right_asset_version_id,
                       presentation_order, subject_id, pack_id,
                       protocol_version, scope_type, chapter_start,
                       chapter_end, arc_plan_version_ids, pair_ordinal,
                       assigned_reviewer_id, blind_pair_token,
                       private_mapping_hash
                FROM human_preference_pair
                WHERE task_id=%s AND canonical_pair_key=%s
                  AND presentation_order=%s
                """,
                [task_id, canonical, order],
            )
            return self._pair_row(uow.cursor.fetchone())

    @staticmethod
    def _pair_row(row: Any) -> dict[str, Any]:
        fields = (
            "pair_id",
            "task_id",
            "project_id",
            "canonical_pair_key",
            "asset_a_version_id",
            "asset_b_version_id",
            "left_asset_version_id",
            "right_asset_version_id",
            "presentation_order",
            "subject_id",
            "pack_id",
            "protocol_version",
            "scope_type",
            "chapter_start",
            "chapter_end",
            "arc_plan_version_ids",
            "pair_ordinal",
            "assigned_reviewer_id",
            "blind_pair_token",
            "private_mapping_hash",
        )
        return dict(zip(fields, row, strict=True))

    def _pair_by_token(self, pair_token: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT pair_id, task_id, project_id, canonical_pair_key,
                       asset_a_version_id, asset_b_version_id,
                       left_asset_version_id, right_asset_version_id,
                       presentation_order, subject_id, pack_id,
                       protocol_version, scope_type, chapter_start,
                       chapter_end, arc_plan_version_ids, pair_ordinal,
                       assigned_reviewer_id, blind_pair_token,
                       private_mapping_hash
                FROM human_preference_pair
                WHERE blind_pair_token=%s
                """,
                [pair_token],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "PREFERENCE_PAIR_NOT_FOUND", "blinded pair token does not exist"
            )
        return self._pair_row(row)

    def _qualification_subject(self, subject_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT subject_id, campaign_id, project_id, scope_type,
                       chapter_start, chapter_end, arc_plan_version_ids,
                       canonical_asset_version_id, baseline_asset_version_id
                FROM authority_quality_qualification_subject
                WHERE subject_id=%s
                """,
                [subject_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "QUALITY_QUALIFICATION_SUBJECT_NOT_FOUND",
                "blind pair subject is not registered",
            )
        fields = (
            "subject_id",
            "campaign_id",
            "project_id",
            "scope_type",
            "chapter_start",
            "chapter_end",
            "arc_plan_version_ids",
            "canonical_asset_version_id",
            "baseline_asset_version_id",
        )
        return dict(zip(fields, row, strict=True))

    def _pack(self, pack_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT pack_id, task_id, campaign_id, project_id,
                       reviewer_id, evaluator_identity_class,
                       protocol_version, evaluation_profile_version,
                       pack_asset_version_id, pack_content_hash,
                       private_mapping_hash, pair_count, status
                FROM human_preference_evaluation_pack
                WHERE pack_id=%s
                """,
                [pack_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BLIND_PACK_NOT_FOUND", "blind evaluation pack does not exist"
            )
        fields = (
            "pack_id",
            "task_id",
            "campaign_id",
            "project_id",
            "reviewer_id",
            "evaluator_identity_class",
            "protocol_version",
            "evaluation_profile_version",
            "pack_asset_version_id",
            "pack_content_hash",
            "private_mapping_hash",
            "pair_count",
            "status",
        )
        return dict(zip(fields, row, strict=True))

    def _decisions(self, task_id: str) -> list[dict[str, Any]]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT decision.pair_id, decision.choice,
                       decision.reviewer_group,
                       decision.preferred_asset_version_id,
                       pair.canonical_pair_key,
                       pair.presentation_order,
                       CASE
                           WHEN pair.asset_a_version_id=
                                pair.left_asset_version_id
                           THEN 'LEFT' ELSE 'RIGHT'
                       END AS asset_a_position,
                       CASE
                           WHEN pair.asset_b_version_id=
                                pair.left_asset_version_id
                           THEN 'LEFT' ELSE 'RIGHT'
                       END AS asset_b_position
                FROM human_preference_decision AS decision
                JOIN human_preference_pair AS pair
                  ON pair.pair_id=decision.pair_id
                WHERE pair.task_id=%s
                """,
                [task_id],
            )
            fields = (
                "pair_id",
                "choice",
                "reviewer_group",
                "preferred_asset_version_id",
                "canonical_pair_key",
                "presentation_order",
                "asset_a_position",
                "asset_b_position",
            )
            return [
                dict(zip(fields, row, strict=True))
                for row in uow.cursor.fetchall()
            ]

    def _session(self, session_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT reader_session_id, project_id, book_id,
                       reader_segment, platform
                FROM reader_session WHERE reader_session_id=%s
                """,
                [session_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "READER_SESSION_NOT_FOUND", "ReaderSession does not exist"
            )
        return dict(
            zip(
                (
                    "reader_session_id",
                    "project_id",
                    "book_id",
                    "reader_segment",
                    "platform",
                ),
                row,
                strict=True,
            )
        )

    def _exposure(self, exposure_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT exposure_id, project_id, book_id,
                       reader_session_id, reader_segment, platform,
                       chapter_asset_version_id, denominator_eligible
                FROM reader_exposure WHERE exposure_id=%s
                """,
                [exposure_id],
            )
            row = uow.cursor.fetchone()
        if row is None or not bool(row[7]):
            raise KernelError(
                "READER_EXPOSURE_REQUIRED",
                "Reader outcome requires an eligible exposure denominator",
            )
        return self._exposure_row(row)

    def _exposure_by_key(
        self, project_id: str, idempotency_key: str
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT exposure_id, project_id, book_id,
                       reader_session_id, reader_segment, platform,
                       chapter_asset_version_id, denominator_eligible
                FROM reader_exposure
                WHERE project_id=%s AND stable_idempotency_key=%s
                """,
                [project_id, idempotency_key],
            )
            return self._exposure_row(uow.cursor.fetchone())

    @staticmethod
    def _exposure_row(row: Any) -> dict[str, Any]:
        fields = (
            "exposure_id",
            "project_id",
            "book_id",
            "reader_session_id",
            "reader_segment",
            "platform",
            "chapter_asset_version_id",
            "denominator_eligible",
        )
        return dict(zip(fields, row, strict=True))

    def _profile(self, profile_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT profile_id, project_id, status, judge_mode
                FROM calibration_profile WHERE profile_id=%s
                """,
                [profile_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "CALIBRATION_PROFILE_NOT_FOUND",
                "CalibrationProfile does not exist",
            )
        return dict(
            zip(
                ("profile_id", "project_id", "status", "judge_mode"),
                row,
                strict=True,
            )
        )

    def _behavior_evidence_count(
        self, *, project_id: str, platform: str, reader_segment: str
    ) -> int:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(DISTINCT exposure.exposure_id)
                FROM reader_exposure AS exposure
                JOIN reader_outcome_event AS outcome
                  ON outcome.exposure_id=exposure.exposure_id
                 AND outcome.project_id=exposure.project_id
                 AND outcome.reader_segment=exposure.reader_segment
                 AND outcome.platform=exposure.platform
                WHERE exposure.project_id=%s
                  AND exposure.platform=%s
                  AND exposure.reader_segment=%s
                  AND exposure.denominator_eligible=TRUE
                """,
                [project_id, platform, reader_segment],
            )
            return int(uow.cursor.fetchone()[0])

    def _output(
        self, operation_id: str, output_key: str
    ) -> dict[str, str]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT binding.asset_version_id, version.content_hash
                FROM authority_operation_output_asset AS binding
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=binding.asset_version_id
                WHERE binding.operation_id=%s AND binding.output_key=%s
                """,
                [operation_id, output_key],
            )
            row = uow.cursor.fetchone()
        return {
            "asset_version_id": str(row[0]),
            "content_hash": str(row[1]),
        }


def _definition(
    name: str,
    asset_type: str,
    output_key: str,
    *,
    application_build_id: str,
    commit_sha: str,
) -> dict[str, Any]:
    schema = {"type": "object"}
    return {
        "name": name,
        "definition_version": VERSION,
        "family": "reader_calibration",
        "enabled": True,
        "definition_status": "integration_proven",
        "command_schema_version": f"{name}.command.v1",
        "result_schema_version": f"{name}.result.v1",
        "command_schema": schema,
        "result_schema": schema,
        "input_contract": schema,
        "output_contract": {
            "asset_type": asset_type,
            "output_key": output_key,
        },
        "handler_key": f"{HANDLER_PREFIX}.{name}",
        "handler_contract_version": "reader-calibration-handler-v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "worker",
        "permissions": ["book.authority.execute"],
        "approval_policy": {"required": False},
        "idempotency_scope": "project:reader-calibration",
        "concurrency_key_template": "project:{project_id}:reader-calibration",
        "retry_policy": {"max_attempts": 2},
        "timeout_policy": {"operation_timeout_seconds": 120},
        "cancellation_policy": {"mode": "cancel_active_attempt"},
        "compensation_policy": {
            "supported": False,
            "reason": "append-only observation and report records",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "policy": {
            "fixture_evidence_mode": "SHADOW",
            "exposure_denominator_required": True,
            "hard_gate_precedence": True,
        },
        "completion_contract": {
            "version": "reader-calibration-completion-v1",
            "required_asset_selectors": [
                {
                    "selector": asset_type,
                    "output_key": output_key,
                    "role": "primary",
                    "lifecycle": "ACTIVE",
                    "eligibility": "ELIGIBLE",
                    "governance": "CLEAR",
                }
            ],
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": [f"{name}.completed"],
        },
    }


__all__ = ["PostgresReaderCalibrationAuthority"]
