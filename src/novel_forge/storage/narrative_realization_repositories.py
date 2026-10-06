from __future__ import annotations

from typing import Any
from uuid import uuid4
from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.hierarchical_planning.realization_domain import (
    NarrativeRealizationContract,
    NarrativeRealizationLifecycle,
    realization_hash,
)
from novel_forge.storage.foundation_repositories import (
    require_current_foundation_set,
)


def _realization_event_deviations(
    planned: dict[str, Any], observed: dict[str, Any]
) -> tuple[str, ...]:

    deviations: set[str] = set()
    if planned.get("feature_status") and any(
        field not in observed
        for field in (
            "observed_action",
            "observed_decision",
            "observed_consequence",
            "observed_cause_event_ids",
            "observed_state_deltas",
            "observed_state_event_ids",
            "observed_disclosures",
        )
    ):
        deviations.add("MISSING_REQUIRED_EVENT")
    if any(
        str(observed.get(observed_field) or "")
        != str(planned.get(planned_field) or "")
        for observed_field, planned_field in (
            ("observed_action", "action"),
            ("observed_decision", "decision"),
            ("observed_consequence", "consequence"),
        )
    ) or set(str(item) for item in observed.get("observed_cause_event_ids") or ()) != set(
        str(item) for item in planned.get("causes") or ()
    ):
        deviations.add("CAUSALITY_DRIFT")

    planned_deltas = {
        realization_hash(dict(item))
        for item in planned.get("state_deltas") or ()
        if isinstance(item, dict)
    }
    observed_deltas = {
        realization_hash(dict(item))
        for item in observed.get("observed_state_deltas") or ()
        if isinstance(item, dict)
    }
    planned_entities = {
        str(item.get("entity_id") or "")
        for item in planned.get("state_deltas") or ()
        if isinstance(item, dict)
    }
    if planned_deltas != observed_deltas or planned_entities != set(
        str(item) for item in observed.get("observed_state_event_ids") or ()
    ):
        deviations.add("STATE_DELTA_DRIFT")

    boundary = dict(planned.get("knowledge_boundary") or {})
    disclosures = {
        str(item) for item in observed.get("observed_disclosures") or ()
    }
    planned_disclosures = {str(item) for item in planned.get("disclosures") or ()}
    allowed = {str(item) for item in boundary.get("reader_may_learn") or ()}
    forbidden = {
        str(item) for item in boundary.get("forbidden_disclosures") or ()
    }
    if (
        disclosures != planned_disclosures
        or not disclosures.issubset(allowed)
        or bool(disclosures & forbidden)
    ):
        deviations.add("KNOWLEDGE_BOUNDARY_DRIFT")
    return tuple(sorted(deviations))


class NarrativeRealizationRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def qualify(
        self,
        *,
        contract: NarrativeRealizationContract,
        operation_id: str,
    ) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT lifecycle, version, contract_digest
            FROM authority_narrative_realization
            WHERE realization_id=%s
            FOR UPDATE
            """,
            [contract.realization_id],
        )
        existing = self.cursor.fetchone()
        if existing is not None:
            if (
                str(existing[0]) == contract.lifecycle.value
                and str(existing[2]) == contract.contract_digest
            ):
                return self.require(contract.realization_id)
            raise KernelError(
                "NARRATIVE_REALIZATION_CONFLICT",
                "realization identity already binds different evidence",
            )
        expected = NarrativeRealizationLifecycle.ADMITTED if contract.proof.design_admission.get("mode") == "CREATIVE_VALIDATION" else NarrativeRealizationLifecycle.QUALIFIED
        if contract.lifecycle is not expected:
            raise KernelError(
                "NARRATIVE_REALIZATION_LIFECYCLE_INVALID",
                "qualification command requires a QUALIFIED contract",
            )
        self._require_frozen_inputs(contract)
        boundary = contract.accepted_boundary
        self.cursor.execute(
            """
            INSERT INTO authority_narrative_realization(
                realization_id, project_id, book_id,
                chapter_group_plan_version_id, chapter_group_content_hash,
                chapter_start, chapter_end, foundation_set_digest,
                accepted_through_chapter, story_state_asset_version_id,
                story_state_content_hash, canon_snapshot_asset_version_id,
                canon_snapshot_content_hash, arc_working_set_digest,
                arc_plan_bindings, proof,
                content_asset_version_id, content_hash,
                proof_asset_version_id, proof_hash, contract_digest, lifecycle,
                qualification_operation_id
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s
            )
            """,
            [
                contract.realization_id,
                contract.project_id,
                contract.book_id,
                contract.chapter_group_plan_version_id,
                contract.chapter_group_content_hash,
                contract.chapter_range[0],
                contract.chapter_range[1],
                contract.foundation_set_digest,
                boundary.accepted_through_chapter,
                boundary.story_state_version_id,
                boundary.story_state_content_hash,
                boundary.canon_version_id,
                boundary.canon_content_hash,
                contract.arc_working_set_digest,
                Jsonb(
                    [
                        {
                            "arc_id": item.arc_id,
                            "asset_version_id": item.asset_version_id,
                            "content_hash": item.content_hash,
                        }
                        for item in contract.arc_plan_bindings
                    ]
                ),
                Jsonb(contract.proof.to_dict()),
                contract.content_asset_version_id,
                contract.content_hash,
                contract.proof_asset_version_id,
                contract.proof_hash,
                contract.contract_digest,
                contract.lifecycle.value,
                operation_id,
            ],
        )
        for order, event in enumerate(contract.events, start=1):
            event_content = event.to_dict()
            self.cursor.execute(
                """
                INSERT INTO authority_narrative_realization_event(
                    realization_id, event_id, slice_id, chapter_number,
                    required, event_order, planned_event, planned_event_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                [
                    contract.realization_id,
                    event.event_id,
                    event.slice_id,
                    event.chapter_number,
                    event.required,
                    order,
                    Jsonb(event_content),
                    realization_hash(event_content),
                ],
            )
        return self.require(contract.realization_id)

    def transition(
        self,
        *,
        realization_id: str,
        expected_version: int,
        target: NarrativeRealizationLifecycle,
        operation_id: str,
        reason: str,
    ) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT project_id, book_id, chapter_group_plan_version_id,
                   lifecycle, version
            FROM authority_narrative_realization
            WHERE realization_id=%s
            FOR UPDATE
            """,
            [realization_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "NARRATIVE_REALIZATION_NOT_FOUND", "realization does not exist"
            )
        current = NarrativeRealizationLifecycle(str(row[3]))
        version = int(row[4])
        if version != expected_version:
            raise KernelError(
                "NARRATIVE_REALIZATION_VERSION_CONFLICT",
                "realization lifecycle version changed",
            )
        allowed = {
            NarrativeRealizationLifecycle.ADMITTED: {
                NarrativeRealizationLifecycle.APPROVED,
                NarrativeRealizationLifecycle.REJECTED,
                NarrativeRealizationLifecycle.STALE,
            },
            NarrativeRealizationLifecycle.QUALIFIED: {
                NarrativeRealizationLifecycle.APPROVED,
                NarrativeRealizationLifecycle.REJECTED,
                NarrativeRealizationLifecycle.STALE,
            },
            NarrativeRealizationLifecycle.APPROVED: {
                NarrativeRealizationLifecycle.FROZEN,
                NarrativeRealizationLifecycle.STALE,
                NarrativeRealizationLifecycle.REJECTED,
            },
            NarrativeRealizationLifecycle.FROZEN: {
                NarrativeRealizationLifecycle.STALE,
                NarrativeRealizationLifecycle.SUPERSEDED,
            },
        }
        if target not in allowed.get(current, set()):
            raise KernelError(
                "NARRATIVE_REALIZATION_TRANSITION_INVALID",
                f"cannot transition {current.value} to {target.value}",
            )
        if target is NarrativeRealizationLifecycle.FROZEN:
            self._freeze_current(
                project_id=str(row[0]),
                book_id=str(row[1]),
                group_version=str(row[2]),
                realization_id=realization_id,
                operation_id=operation_id,
            )
        elif target in {
            NarrativeRealizationLifecycle.STALE,
            NarrativeRealizationLifecycle.SUPERSEDED,
        }:
            self.cursor.execute(
                """
                DELETE FROM authority_narrative_realization_current
                WHERE realization_id=%s
                """,
                [realization_id],
            )
        operation_column = {
            NarrativeRealizationLifecycle.APPROVED: "approval_operation_id",
            NarrativeRealizationLifecycle.FROZEN: "frozen_by_operation_id",
            NarrativeRealizationLifecycle.STALE: "invalidated_by_operation_id",
            NarrativeRealizationLifecycle.SUPERSEDED: "invalidated_by_operation_id",
        }.get(target)
        assignment = f", {operation_column}=%s" if operation_column else ""
        parameters: list[Any] = [target.value]
        if operation_column:
            parameters.append(operation_id)
        parameters.extend([realization_id, expected_version, current.value])
        self.cursor.execute(
            f"""
            UPDATE authority_narrative_realization
            SET lifecycle=%s, version=version+1, updated_at=NOW(){assignment}
            WHERE realization_id=%s AND version=%s AND lifecycle=%s
            """,
            parameters,
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "NARRATIVE_REALIZATION_VERSION_CONFLICT",
                "concurrent realization lifecycle transition won",
            )
        return self.require(realization_id)

    def require(self, realization_id: str) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT realization_id, project_id, book_id,
                   chapter_group_plan_version_id, chapter_start, chapter_end,
                   foundation_set_digest, accepted_through_chapter,
                   story_state_asset_version_id, canon_snapshot_asset_version_id,
                   arc_working_set_digest, content_asset_version_id, content_hash,
                   proof_asset_version_id, proof_hash, contract_digest, lifecycle,
                   version, qualification_operation_id, approval_operation_id,
                   frozen_by_operation_id, invalidated_by_operation_id,
                   executed_by_operation_id
            FROM authority_narrative_realization
            WHERE realization_id=%s
            """,
            [realization_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "NARRATIVE_REALIZATION_NOT_FOUND", "realization does not exist"
            )
        fields = (
            "realization_id",
            "project_id",
            "book_id",
            "chapter_group_plan_version_id",
            "chapter_start",
            "chapter_end",
            "foundation_set_digest",
            "accepted_through_chapter",
            "story_state_asset_version_id",
            "canon_snapshot_asset_version_id",
            "arc_working_set_digest",
            "content_asset_version_id",
            "content_hash",
            "proof_asset_version_id",
            "proof_hash",
            "contract_digest",
            "lifecycle",
            "version",
            "qualification_operation_id",
            "approval_operation_id",
            "frozen_by_operation_id",
            "invalidated_by_operation_id",
            "executed_by_operation_id",
        )
        return dict(zip(fields, row, strict=True))

    def stale_for_noncurrent_plan_inputs(
        self,
        *,
        project_id: str,
        book_id: str,
        operation_id: str,
    ) -> tuple[str, ...]:

        self.cursor.execute(
            """
            SELECT realization.realization_id
            FROM authority_narrative_realization AS realization
            WHERE realization.project_id=%s AND realization.book_id=%s
              AND realization.lifecycle IN ('ADMITTED','QUALIFIED','APPROVED','FROZEN')
              AND (
                EXISTS (
                  SELECT 1
                  FROM story_plan_binding AS binding
                  LEFT JOIN active_story_plan_version AS active
                    ON active.binding_id=binding.binding_id
                  WHERE binding.project_id=realization.project_id
                    AND binding.book_id=realization.book_id
                    AND binding.asset_version_id=
                        realization.chapter_group_plan_version_id
                    AND (
                      binding.freshness<>'CURRENT'
                      OR active.binding_id IS NULL
                    )
                )
                OR EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements(realization.arc_plan_bindings) AS arc
                  JOIN story_plan_binding AS binding
                    ON binding.project_id=realization.project_id
                   AND binding.book_id=realization.book_id
                   AND binding.asset_version_id=arc->>'asset_version_id'
                  LEFT JOIN active_story_plan_version AS active
                    ON active.binding_id=binding.binding_id
                  WHERE binding.freshness<>'CURRENT'
                     OR active.binding_id IS NULL
                )
              )
            ORDER BY realization.realization_id
            FOR UPDATE OF realization
            """,
            [project_id, book_id],
        )
        realization_ids = tuple(str(row[0]) for row in self.cursor.fetchall())
        if not realization_ids:
            return ()
        self.cursor.execute(
            """
            DELETE FROM authority_narrative_realization_current
            WHERE realization_id=ANY(%s)
            """,
            [list(realization_ids)],
        )
        self.cursor.execute(
            """
            UPDATE authority_narrative_realization
            SET lifecycle='STALE', version=version+1,
                invalidated_by_operation_id=%s, updated_at=NOW()
            WHERE realization_id=ANY(%s)
              AND lifecycle IN ('ADMITTED','QUALIFIED','APPROVED','FROZEN')
            """,
            [operation_id, list(realization_ids)],
        )
        if self.cursor.rowcount != len(realization_ids):
            raise KernelError(
                "NARRATIVE_REALIZATION_VERSION_CONFLICT",
                "PlanChange raced with Narrative Realization invalidation",
            )
        return realization_ids

    def require_current_for_chapter(
        self,
        *,
        project_id: str,
        book_id: str,
        chapter_group_plan_version_id: str,
        chapter_number: int,
    ) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT realization.realization_id, realization.contract_digest,
                   realization.chapter_group_content_hash,
                   realization.foundation_set_digest,
                   realization.accepted_through_chapter,
                   realization.arc_working_set_digest,
                   realization.proof_asset_version_id, realization.proof_hash,
                   realization.lifecycle,
                   event.slice_id, event.event_id, event.planned_event,
                   event.planned_event_hash
            FROM authority_narrative_realization_current AS current
            JOIN authority_narrative_realization AS realization
              ON realization.realization_id=current.realization_id
            JOIN authority_narrative_realization_event AS event
              ON event.realization_id=realization.realization_id
            WHERE current.project_id=%s AND current.book_id=%s
              AND current.chapter_group_plan_version_id=%s
              AND event.chapter_number=%s
            ORDER BY event.event_order
            """,
            [
                project_id,
                book_id,
                chapter_group_plan_version_id,
                chapter_number,
            ],
        )
        rows = self.cursor.fetchall()
        if not rows or str(rows[0][8]) != NarrativeRealizationLifecycle.FROZEN.value:
            raise KernelError(
                "NARRATIVE_REALIZATION_REQUIRED",
                "Chapter elaboration requires a current Frozen Narrative Realization slice",
            )
        identity = tuple(str(item) for item in rows[0][:9])
        if any(tuple(str(item) for item in row[:9]) != identity for row in rows):
            raise KernelError(
                "NARRATIVE_REALIZATION_MIXED_LINEAGE",
                "Narrative Realization slice contains mixed contract lineage",
            )
        self._require_current_evidence(
            project_id=project_id,
            book_id=book_id,
            realization_id=str(rows[0][0]),
            chapter_number=chapter_number,
        )
        slice_ids = {str(row[9]) for row in rows}
        if len(slice_ids) != 1:
            raise KernelError(
                "REALIZATION_SLICE_INVALID",
                "one Chapter may consume only one realization slice",
            )
        events = [dict(row[11]) for row in rows]
        return {
            "realization_id": str(rows[0][0]),
            "contract_digest": str(rows[0][1]),
            "chapter_group_plan_version_id": chapter_group_plan_version_id,
            "chapter_group_content_hash": str(rows[0][2]),
            "slice_id": slice_ids.pop(),
            "chapter_number": chapter_number,
            "event_ids": [str(row[10]) for row in rows],
            "events": events,
            "foundation_set_digest": str(rows[0][3]),
            "accepted_through_chapter": int(rows[0][4]),
            "arc_working_set_digest": str(rows[0][5]),
            "proof_asset_version_id": str(rows[0][6]),
            "proof_hash": str(rows[0][7]),
        }

    def consume_accepted_chapter(
        self,
        *,
        project_id: str,
        book_id: str,
        realization_id: str,
        chapter_number: int,
        chapter_plan_asset_version_id: str,
        acceptance_id: str,
        chapter_outcome_asset_version_id: str,
        realization_evidence: list[dict[str, Any]],
        operation_id: str,
    ) -> dict[str, Any]:

        self.cursor.execute(
            """
            SELECT realization.lifecycle, realization.version,
                   event.event_id, event.required, event.planned_event_hash,
                   event.planned_event
            FROM authority_narrative_realization AS realization
            JOIN authority_narrative_realization_event AS event
              ON event.realization_id=realization.realization_id
            WHERE realization.realization_id=%s
              AND realization.project_id=%s AND realization.book_id=%s
              AND event.chapter_number=%s
            ORDER BY event.event_order
            FOR UPDATE OF realization
            """,
            [realization_id, project_id, book_id, chapter_number],
        )
        rows = self.cursor.fetchall()
        if not rows or str(rows[0][0]) not in {
            NarrativeRealizationLifecycle.FROZEN.value,
            NarrativeRealizationLifecycle.EXECUTED.value,
        }:
            raise KernelError(
                "NARRATIVE_REALIZATION_CONSUMPTION_INVALID",
                "accepted Chapter does not bind a Frozen realization slice",
            )
        planned = {
            str(row[2]): (bool(row[3]), str(row[4]), dict(row[5])) for row in rows
        }
        observed: dict[str, dict[str, Any]] = {}
        unplanned: list[dict[str, Any]] = []
        for item in realization_evidence:
            event_id = str(item.get("planned_event_id") or "")
            if not event_id or event_id not in planned:
                unplanned.append(dict(item))
                continue
            if event_id in observed:
                raise KernelError(
                    "NARRATIVE_REALIZATION_EVIDENCE_AMBIGUOUS",
                    "accepted actual contains duplicate evidence for one planned event",
                )
            observed[event_id] = dict(item)
        deviations: list[str] = []
        for event_id, (required, planned_hash, planned_event) in planned.items():
            evidence = observed.get(event_id)
            is_observed = bool(
                evidence
                and evidence.get("observation_status") == "OBSERVED"
                and evidence.get("accepted_prose_evidence")
            )
            event_deviations = (
                _realization_event_deviations(planned_event, evidence)
                if is_observed and evidence is not None
                else ()
            )
            status = (
                "DEVIATED"
                if event_deviations
                else "ACCEPTED"
                if is_observed
                else "NOT_OBSERVED"
            )
            observed_id = (
                str(evidence.get("observed_event_id") or "") if is_observed else None
            )
            if is_observed and not observed_id:
                raise KernelError(
                    "NARRATIVE_REALIZATION_EVIDENCE_INVALID",
                    "observed realization evidence requires an observed event identity",
                )
            observed_hash = realization_hash(evidence) if is_observed else None
            self.cursor.execute(
                """
                INSERT INTO authority_narrative_realization_consumption(
                    consumption_id, realization_id, planned_event_id,
                    chapter_plan_asset_version_id, acceptance_id,
                    chapter_outcome_asset_version_id, observed_event_id,
                    observed_event_hash, coverage_status, evidence,
                    consumed_by_operation_id
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (realization_id, planned_event_id)
                DO NOTHING
                """,
                [
                    str(uuid4()),
                    realization_id,
                    event_id,
                    chapter_plan_asset_version_id,
                    acceptance_id,
                    chapter_outcome_asset_version_id,
                    observed_id,
                    observed_hash,
                    status,
                    Jsonb(
                        {
                            "planned_event_hash": planned_hash,
                            "accepted_actual": dict(evidence or {}),
                        }
                    ),
                    operation_id,
                ],
            )
            if required and not is_observed:
                deviations.append("MISSING_REQUIRED_EVENT")
            deviations.extend(event_deviations)
        if unplanned:
            deviations.append("UNPLANNED_EVENT")
        for kind in sorted(set(deviations)):
            evidence = {
                "chapter_number": chapter_number,
                "planned_event_ids": sorted(planned),
                "observed_event_ids": sorted(observed),
                "unplanned": unplanned,
            }
            evidence_hash = realization_hash(evidence)
            self.cursor.execute(
                """
                INSERT INTO authority_narrative_realization_deviation(
                    deviation_id, realization_id, acceptance_id,
                    chapter_plan_asset_version_id, deviation_kind,
                    affected_future_from_chapter, evidence, evidence_hash,
                    created_by_operation_id
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (
                    realization_id, acceptance_id, deviation_kind, evidence_hash
                ) DO NOTHING
                """,
                [
                    str(uuid4()),
                    realization_id,
                    acceptance_id,
                    chapter_plan_asset_version_id,
                    kind,
                    chapter_number + 1,
                    Jsonb(evidence),
                    evidence_hash,
                    operation_id,
                ],
            )
        self.cursor.execute(
            """
            SELECT COUNT(*), COUNT(*) FILTER (
                       WHERE consumption.coverage_status='ACCEPTED'
                   ), COUNT(*) FILTER (
                       WHERE consumption.coverage_status='ACCEPTED'
                          OR (NOT event.required AND
                              consumption.coverage_status='NOT_OBSERVED')
                   )
            FROM authority_narrative_realization_event AS event
            LEFT JOIN authority_narrative_realization_consumption AS consumption
              ON consumption.realization_id=event.realization_id
             AND consumption.planned_event_id=event.event_id
            WHERE event.realization_id=%s
            """,
            [realization_id],
        )
        total, accepted, covered = (int(item) for item in self.cursor.fetchone())
        if deviations:
            target = NarrativeRealizationLifecycle.STALE.value
        elif total == covered:
            target = NarrativeRealizationLifecycle.EXECUTED.value
        else:
            target = NarrativeRealizationLifecycle.FROZEN.value
        if target != str(rows[0][0]):
            self.cursor.execute(
                """
                UPDATE authority_narrative_realization
                SET lifecycle=%s, version=version+1,
                    executed_by_operation_id=CASE WHEN %s='EXECUTED'
                                                  THEN %s ELSE NULL END,
                    updated_at=NOW()
                WHERE realization_id=%s AND version=%s
                """,
                [target, target, operation_id, realization_id, int(rows[0][1])],
            )
            if self.cursor.rowcount != 1:
                raise KernelError(
                    "NARRATIVE_REALIZATION_VERSION_CONFLICT",
                    "realization coverage changed concurrently",
                )
        if target == NarrativeRealizationLifecycle.STALE.value:
            self.cursor.execute(
                """
                DELETE FROM authority_narrative_realization_current
                WHERE realization_id=%s
                """,
                [realization_id],
            )
        if target in {
            NarrativeRealizationLifecycle.STALE.value,
            NarrativeRealizationLifecycle.EXECUTED.value,
        }:
            self.cursor.execute(
                "DELETE FROM authority_narrative_realization_current WHERE realization_id=%s",
                [realization_id],
            )
        return {
            "realization_id": realization_id,
            "lifecycle": target,
            "planned_event_count": total,
            "accepted_event_count": accepted,
            "covered_event_count": covered,
            "deviations": sorted(set(deviations)),
        }

    def _require_frozen_inputs(self, contract: NarrativeRealizationContract) -> None:
        self._require_foundation_set(contract)
        self._require_group(contract)
        self._require_arcs(contract)
        self._require_accepted_boundary(contract)
        self._require_asset(
            contract.project_id,
            contract.content_asset_version_id,
            contract.content_hash,
            allowed_types={"narrative_realization", "planning_generation_candidate"},
        )
        author_supervised = (
            contract.proof.design_admission.get("mode") == "AUTHOR_SUPERVISED_DESIGN"
        )
        creative = contract.proof.design_admission.get("mode") == "CREATIVE_VALIDATION"
        if creative:
            from novel_forge.modules.story_design_authority.creative_validation import approved_validation_design
            receipt = approved_validation_design(self.cursor, project_id=contract.project_id, book_id=contract.book_id, asset_version_id=contract.chapter_group_plan_version_id)
            if (receipt is None or receipt != contract.proof.design_admission or receipt["content_hash"] != contract.chapter_group_content_hash
                    or receipt["decision_asset_version_id"] != contract.proof_asset_version_id or receipt["decision_content_hash"] != contract.proof_hash):
                raise KernelError("REALIZATION_VALIDATION_STALE", "Exact validation receipt required")
        if author_supervised:
            from novel_forge.modules.story_design_authority.author_supervision import (
                approved_design_receipt,
            )

            receipt = approved_design_receipt(
                self.cursor,
                project_id=contract.project_id,
                book_id=contract.book_id,
                asset_version_id=contract.chapter_group_plan_version_id,
            )
            if (
                receipt != contract.proof.design_admission
                or receipt["content_hash"] != contract.chapter_group_content_hash
                or receipt["decision_asset_version_id"]
                != contract.proof_asset_version_id
                or receipt["decision_content_hash"] != contract.proof_hash
            ):
                raise KernelError(
                    "REALIZATION_AUTHOR_APPROVAL_STALE",
                    "Proof must bind the exact existing native author approval",
                )
        proof_types = (
            {"story_design_transition_receipt"}
            if author_supervised or creative
            else {"narrative_realization_proof", "narrative_design_evaluation"}
        )
        self._require_asset(
            contract.project_id,
            contract.proof_asset_version_id,
            contract.proof_hash,
            allowed_types=proof_types,
        )
        self._require_asset(
            contract.project_id,
            contract.proof.semantic_evaluation_asset_version_id,
            contract.proof.semantic_evaluation_hash,
            allowed_types={"story_design_transition_receipt"}
            if author_supervised or creative
            else {"narrative_design_evaluation"},
        )

    def _require_foundation_set(self, contract: NarrativeRealizationContract) -> None:
        foundation = require_current_foundation_set(
            self.cursor,
            project_id=contract.project_id,
            book_id=contract.book_id,
            require_ready=True,
        )
        if foundation.set_digest != contract.foundation_set_digest:
            raise KernelError(
                "FOUNDATION_SET_DRIFT",
                "Narrative Realization Foundation Set is no longer current",
            )

    def _require_group(self, contract: NarrativeRealizationContract) -> None:
        self.cursor.execute(
            """
            SELECT version.content_hash, binding.contract_type,
                   binding.execution_scope, binding.freshness, active.binding_id
            FROM authority_asset_version AS version
            JOIN story_plan_binding AS binding
              ON binding.asset_version_id=version.asset_version_id
             AND binding.project_id=%s AND binding.book_id=%s
            LEFT JOIN active_story_plan_version AS active
              ON active.binding_id=binding.binding_id
            WHERE version.asset_version_id=%s
            """,
            [
                contract.project_id,
                contract.book_id,
                contract.chapter_group_plan_version_id,
            ],
        )
        row = self.cursor.fetchone()
        if (
            row is None
            or tuple(str(item) for item in row[:4])
            != (
                contract.chapter_group_content_hash,
                "CHAPTER_GROUP",
                "FROZEN",
                "CURRENT",
            )
            or row[4] is None
        ):
            raise KernelError(
                "NARRATIVE_REALIZATION_GROUP_STALE",
                "realization requires the exact current frozen ChapterGroup",
            )

    def _require_arcs(self, contract: NarrativeRealizationContract) -> None:
        for arc in contract.arc_plan_bindings:
            self.cursor.execute(
                """
                SELECT version.content_hash, binding.contract_type,
                       binding.freshness, active.binding_id
                FROM authority_asset_version AS version
                JOIN story_plan_binding AS binding
                  ON binding.asset_version_id=version.asset_version_id
                 AND binding.project_id=%s AND binding.book_id=%s
                LEFT JOIN active_story_plan_version AS active
                  ON active.binding_id=binding.binding_id
                WHERE version.asset_version_id=%s
                """,
                [contract.project_id, contract.book_id, arc.asset_version_id],
            )
            row = self.cursor.fetchone()
            if (
                row is None
                or tuple(str(item) for item in row[:3])
                != (
                    arc.content_hash,
                    "ARC",
                    "CURRENT",
                )
                or row[3] is None
            ):
                raise KernelError(
                    "NARRATIVE_REALIZATION_ARC_STALE",
                    "realization Arc binding is not exact/current",
                )

    def _require_accepted_boundary(
        self, contract: NarrativeRealizationContract
    ) -> None:
        boundary = contract.accepted_boundary
        self._require_accepted_boundary_values(
            project_id=contract.project_id,
            book_id=contract.book_id,
            book_run_id=self._group_run_scope(contract.chapter_group_plan_version_id, contract.chapter_group_content_hash),
            expected=(
                boundary.accepted_through_chapter,
                boundary.story_state_version_id,
                boundary.story_state_content_hash,
                boundary.canon_version_id,
                boundary.canon_content_hash,
            ),
        )

    def _group_run_scope(self, plan_version_id: str, content_hash: str) -> str:
        self.cursor.execute("""SELECT COALESCE(content#>>'{constraint_envelope,edition_execution,book_run_id}','')
            FROM authority_asset_version WHERE asset_version_id=%s AND content_hash=%s""",
            [plan_version_id, content_hash])
        source = self.cursor.fetchone()
        if source is None:
            raise KernelError("NARRATIVE_REALIZATION_GROUP_STALE", "Realization requires its exact frozen ChapterGroup")
        return str(source[0])

    def _require_accepted_boundary_values(
        self,
        *,
        project_id: str,
        book_id: str,
        expected: tuple[int, str, str, str, str],
        book_run_id: str = "",
    ) -> None:
        self.cursor.execute(
            """
            SELECT production.accepted_through_chapter,
                   COALESCE(production.active_story_state_version_id,
                            snapshot.initial_story_state_version),
                   state.content_hash,
                   COALESCE(production.active_canon_snapshot_version_id,
                            snapshot.initial_canon_snapshot_version),
                   canon.content_hash
            FROM authority_book_production AS production
            JOIN authority_book_production_input_snapshot AS snapshot
              ON snapshot.snapshot_id=production.input_snapshot_id
            JOIN authority_asset_version AS state
              ON state.asset_version_id=COALESCE(
                   production.active_story_state_version_id,
                   snapshot.initial_story_state_version)
            JOIN authority_asset_version AS canon
              ON canon.asset_version_id=COALESCE(
                   production.active_canon_snapshot_version_id,
                   snapshot.initial_canon_snapshot_version)
            WHERE production.project_id=%s AND production.book_id=%s
              AND production.state NOT IN ('COMPLETED','ABORTED')
              AND ((%s<>'' AND production.book_run_id=%s) OR (%s='' AND NOT EXISTS (
                  SELECT 1 FROM authority_book_edition_run edition
                  WHERE edition.book_run_id=production.book_run_id AND edition.role='VALIDATION')))
            ORDER BY production.created_at DESC
            LIMIT 2
            """,
            [project_id, book_id, book_run_id, book_run_id, book_run_id],
        )
        rows = self.cursor.fetchall()
        row = rows[0] if len(rows) == 1 else None
        if row is None or tuple(row) != expected:
            raise KernelError(
                "NARRATIVE_REALIZATION_ACCEPTED_BOUNDARY_STALE",
                "realization must use the latest complete accepted boundary",
            )

    def _require_current_evidence(
        self,
        *,
        project_id: str,
        book_id: str,
        realization_id: str,
        chapter_number: int,
    ) -> None:
        self.cursor.execute(
            """
            SELECT chapter_group_plan_version_id, chapter_group_content_hash,
                   foundation_set_digest, arc_plan_bindings,
                   accepted_through_chapter,
                   story_state_asset_version_id, story_state_content_hash,
                   canon_snapshot_asset_version_id, canon_snapshot_content_hash,
                   proof_asset_version_id, proof_hash, proof
            FROM authority_narrative_realization
            WHERE realization_id=%s AND project_id=%s AND book_id=%s
            """,
            [realization_id, project_id, book_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "NARRATIVE_REALIZATION_NOT_FOUND", "realization does not exist"
            )
        foundation = require_current_foundation_set(
            self.cursor,
            project_id=project_id,
            book_id=book_id,
            require_ready=True,
        )
        if foundation.set_digest != str(row[2]):
            raise KernelError(
                "FOUNDATION_SET_DRIFT", "Narrative Realization Foundation drifted"
            )
        self._require_asset(
            project_id,
            str(row[0]),
            str(row[1]),
            allowed_types={"planning_generation_candidate"},
        )
        admission = dict(row[11] or {}).get("design_admission", {})
        proof_types = {"narrative_design_evaluation"}
        if admission.get("mode") == "CREATIVE_VALIDATION":
            from novel_forge.modules.story_design_authority.creative_validation import approved_validation_design
            receipt = approved_validation_design(self.cursor, project_id=project_id, book_id=book_id, asset_version_id=str(row[0]))
            if receipt != admission or receipt["decision_asset_version_id"] != str(row[9]) or receipt["decision_content_hash"] != str(row[10]):
                raise KernelError("REALIZATION_VALIDATION_STALE", "Current realization validation changed")
            proof_types = {"story_design_transition_receipt"}
        elif admission.get("mode") == "AUTHOR_SUPERVISED_DESIGN":
            from novel_forge.modules.story_design_authority.author_supervision import approved_design_receipt
            receipt = approved_design_receipt(self.cursor, project_id=project_id, book_id=book_id, asset_version_id=str(row[0]))
            if receipt != admission or receipt["decision_asset_version_id"] != str(row[9]) or receipt["decision_content_hash"] != str(row[10]):
                raise KernelError("REALIZATION_AUTHOR_APPROVAL_STALE", "Current realization approval changed")
            proof_types = {"story_design_transition_receipt"}
        self._require_asset(project_id, str(row[9]), str(row[10]), allowed_types=proof_types)
        for arc in row[3] or ():
            if not isinstance(arc, dict):
                raise KernelError(
                    "NARRATIVE_REALIZATION_ARC_STALE",
                    "persisted realization Arc binding is invalid",
                )
            self.cursor.execute(
                """
                SELECT version.content_hash, binding.freshness, active.binding_id
                FROM authority_asset_version AS version
                JOIN story_plan_binding AS binding
                  ON binding.asset_version_id=version.asset_version_id
                 AND binding.project_id=%s AND binding.book_id=%s
                LEFT JOIN active_story_plan_version AS active
                  ON active.binding_id=binding.binding_id
                WHERE version.asset_version_id=%s AND binding.contract_type='ARC'
                """,
                [project_id, book_id, str(arc.get("asset_version_id") or "")],
            )
            current_arc = self.cursor.fetchone()
            if (
                current_arc is None
                or str(current_arc[0]) != str(arc.get("content_hash") or "")
                or str(current_arc[1]) != "CURRENT"
                or current_arc[2] is None
            ):
                raise KernelError(
                    "NARRATIVE_REALIZATION_ARC_STALE",
                    "persisted realization Arc binding is no longer current",
                )
        book_run_id = self._group_run_scope(str(row[0]), str(row[1]))
        self.cursor.execute(
            """
            SELECT production.accepted_through_chapter,
                   COALESCE(production.active_story_state_version_id,
                            snapshot.initial_story_state_version),
                   COALESCE(production.active_canon_snapshot_version_id,
                            snapshot.initial_canon_snapshot_version)
            FROM authority_book_production AS production
            JOIN authority_book_production_input_snapshot AS snapshot
              ON snapshot.snapshot_id=production.input_snapshot_id
            WHERE production.project_id=%s AND production.book_id=%s
              AND production.state NOT IN ('COMPLETED','ABORTED')
              AND ((%s<>'' AND production.book_run_id=%s) OR (%s='' AND NOT EXISTS (
                  SELECT 1 FROM authority_book_edition_run edition
                  WHERE edition.book_run_id=production.book_run_id AND edition.role='VALIDATION')))
            ORDER BY production.created_at DESC
            LIMIT 2
            """,
            [project_id, book_id, book_run_id, book_run_id, book_run_id],
        )
        boundaries = self.cursor.fetchall()
        if len(boundaries) != 1 or int(boundaries[0][0]) != chapter_number - 1:
            raise KernelError(
                "NARRATIVE_REALIZATION_ACCEPTED_BOUNDARY_STALE",
                "realization slice is not adjacent to the complete accepted boundary",
            )
        accepted_through = int(boundaries[0][0])
        original_boundary = int(row[4])
        if accepted_through == original_boundary:
            if tuple(str(item) for item in boundaries[0][1:]) != (
                str(row[5]),
                str(row[7]),
            ):
                raise KernelError(
                    "NARRATIVE_REALIZATION_ACCEPTED_BOUNDARY_STALE",
                    "original realization boundary identity drifted",
                )
        elif accepted_through > original_boundary:
            self.cursor.execute(
                """
                SELECT COUNT(*), COUNT(*) FILTER (
                           WHERE consumption.coverage_status='ACCEPTED'
                       )
                FROM authority_narrative_realization_event AS event
                LEFT JOIN authority_narrative_realization_consumption AS consumption
                  ON consumption.realization_id=event.realization_id
                 AND consumption.planned_event_id=event.event_id
                WHERE event.realization_id=%s
                  AND event.chapter_number>%s
                  AND event.chapter_number<=%s
                """,
                [realization_id, original_boundary, accepted_through],
            )
            planned, consumed = (int(item) for item in self.cursor.fetchone())
            if planned == 0 or planned != consumed:
                raise KernelError(
                    "NARRATIVE_REALIZATION_COVERAGE_INCOMPLETE",
                    "later realization slice requires complete accepted prior coverage",
                )
        else:
            raise KernelError(
                "NARRATIVE_REALIZATION_ACCEPTED_BOUNDARY_STALE",
                "accepted history cannot move behind a frozen realization boundary",
            )

    def _require_asset(
        self,
        project_id: str,
        asset_version_id: str,
        content_hash: str,
        *,
        allowed_types: set[str],
    ) -> None:
        self.cursor.execute(
            """
            SELECT asset.asset_type, version.content_hash,
                   version.lifecycle, version.eligibility, version.governance
            FROM authority_asset_version AS version
            JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
            WHERE asset.project_id=%s AND version.asset_version_id=%s
            """,
            [project_id, asset_version_id],
        )
        row = self.cursor.fetchone()
        if (
            row is None
            or str(row[0]) not in allowed_types
            or tuple(str(item) for item in row[1:])
            != (content_hash, "ACTIVE", "ELIGIBLE", "CLEAR")
        ):
            raise KernelError(
                "NARRATIVE_REALIZATION_EVIDENCE_STALE",
                "realization content/proof evidence is missing or drifted",
            )

    def _freeze_current(
        self,
        *,
        project_id: str,
        book_id: str,
        group_version: str,
        realization_id: str,
        operation_id: str,
    ) -> None:
        self.cursor.execute(
            """
            SELECT realization_id
            FROM authority_narrative_realization_current
            WHERE project_id=%s AND book_id=%s
              AND chapter_group_plan_version_id=%s
            FOR UPDATE
            """,
            [project_id, book_id, group_version],
        )
        row = self.cursor.fetchone()
        if row is not None and str(row[0]) != realization_id:
            raise KernelError(
                "NARRATIVE_REALIZATION_CURRENT_CONFLICT",
                "another realization is already frozen for this ChapterGroup",
            )
        self.cursor.execute(
            """
            INSERT INTO authority_narrative_realization_current(
                project_id, book_id, chapter_group_plan_version_id,
                realization_id, bound_by_operation_id
            ) VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (project_id, book_id, chapter_group_plan_version_id)
            DO UPDATE SET realization_id=EXCLUDED.realization_id,
                          bound_by_operation_id=EXCLUDED.bound_by_operation_id,
                          bound_at=NOW()
            WHERE authority_narrative_realization_current.realization_id=
                  EXCLUDED.realization_id
            """,
            [project_id, book_id, group_version, realization_id, operation_id],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "NARRATIVE_REALIZATION_CURRENT_CONFLICT",
                "realization current binding changed concurrently",
            )


__all__ = ["NarrativeRealizationRepository"]
