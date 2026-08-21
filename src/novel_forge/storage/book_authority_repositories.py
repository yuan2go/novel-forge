"""Mutation repository for the persistent Book Authority aggregate."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from psycopg.types.json import Jsonb


class BookAuthorityRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def create_run(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_book_production (
                book_run_id, project_id, workspace_id, book_id,
                book_design_version, book_plan_version,
                production_profile_version, longform_context_versions,
                root_operation_id, saga_id,
                stable_idempotency_key, state, target_chapter_count,
                light_recap_cadence, formal_recap_cadence,
                input_snapshot_id, input_mode
            ) VALUES (
                %(book_run_id)s, %(project_id)s, %(workspace_id)s, %(book_id)s,
                %(book_design_version)s, %(book_plan_version)s,
                %(production_profile_version)s, %(longform_context_versions)s,
                %(root_operation_id)s,
                %(saga_id)s, %(stable_idempotency_key)s, 'READY',
                %(target_chapter_count)s, %(light_recap_cadence)s,
                %(formal_recap_cadence)s,
                NULLIF(%(input_snapshot_id)s, ''), %(input_mode)s
            )
            ON CONFLICT (project_id, stable_idempotency_key) DO NOTHING
            """,
            {
                **row,
                "longform_context_versions": Jsonb(row["longform_context_versions"]),
            },
        )

    def create_input_binding(
        self, row: dict[str, Any], *, ignore_replay_conflict: bool
    ) -> None:
        conflict = (
            "ON CONFLICT(book_run_id, snapshot_id) DO NOTHING"
            if ignore_replay_conflict
            else ""
        )
        self.cursor.execute(
            f"""
            INSERT INTO authority_book_production_input_binding(
                binding_id, project_id, book_id, book_run_id,
                binding_version, snapshot_id, reason,
                bound_by_operation_id
            ) VALUES (
                %(binding_id)s, %(project_id)s, %(book_id)s, %(book_run_id)s,
                %(binding_version)s, %(snapshot_id)s, %(reason)s,
                %(bound_by_operation_id)s
            )
            {conflict}
            """,
            row,
        )

    def request_delegation_cancellation(self, *, book_run_id: str) -> None:
        self.cursor.execute(
            """
            UPDATE authority_child_delegation
            SET status=CASE
                    WHEN status IN ('DISPATCHED', 'RUNNING', 'WAITING_RETRY',
                                    'SUCCEEDED', 'UNKNOWN')
                    THEN 'CANCELLATION_REQUESTED'
                    ELSE status
                END,
                version=version+1, updated_at=NOW()
            WHERE owner_id=%s AND status <> 'ACCEPTED'
            """,
            [book_run_id],
        )

    def bind_input_snapshot(
        self,
        *,
        book_run_id: str,
        snapshot_id: str,
        state: str,
        expected_version: int,
    ) -> bool:
        self.cursor.execute(
            """
            UPDATE authority_book_production
            SET input_snapshot_id=%s, state=%s, version=version+1,
                updated_at=NOW()
            WHERE book_run_id=%s AND version=%s
            """,
            [snapshot_id, state, book_run_id, expected_version],
        )
        return self.cursor.rowcount == 1

    def advance_if_version(
        self,
        *,
        book_run_id: str,
        chapter_number: int,
        state: str,
        expected_version: int,
    ) -> bool:
        self.cursor.execute(
            """
            UPDATE authority_book_production
            SET state=%s, current_chapter=GREATEST(current_chapter, %s),
                version=version+1, updated_at=NOW()
            WHERE book_run_id=%s AND version=%s
            """,
            [state, chapter_number, book_run_id, expected_version],
        )
        return self.cursor.rowcount == 1

    def compare_and_set_state(
        self,
        *,
        book_run_id: str,
        expected_version: int,
        state: str,
        paused_reason: str,
        failure_reason: str,
    ) -> bool:
        self.cursor.execute(
            """
            UPDATE authority_book_production
            SET state=%s, paused_reason=%s, failure_reason=%s,
                version=version+1, updated_at=NOW()
            WHERE book_run_id=%s AND version=%s
            """,
            [
                state,
                paused_reason,
                failure_reason,
                book_run_id,
                expected_version,
            ],
        )
        return self.cursor.rowcount == 1

    def create_chapter_request(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_book_chapter_request (
                chapter_request_id, book_run_id, project_id, chapter_number,
                chapter_plan_version, chapter_plan_content_hash,
                parent_group_version_id,
                production_profile_version, stable_idempotency_key,
                command_payload, status_reference
            ) VALUES (
                %(chapter_request_id)s, %(book_run_id)s, %(project_id)s,
                %(chapter_number)s, %(chapter_plan_version)s,
                %(chapter_plan_content_hash)s, NULLIF(%(parent_group_version_id)s, ''),
                %(production_profile_version)s,
                %(stable_idempotency_key)s, %(command_payload)s, 'SUBMITTING'
            )
            ON CONFLICT (project_id, stable_idempotency_key) DO NOTHING
            """,
            {**row, "command_payload": Jsonb(row["command_payload"])},
        )

    def reserve_chapter(
        self,
        *,
        book_run_id: str,
        chapter_request_id: str,
        chapter_number: int,
        expected_version: int,
    ) -> bool:
        self.cursor.execute(
            """
            UPDATE authority_book_production
            SET active_chapter_request_id=%s, state='CHAPTER_SUBMITTED',
                version=version+1, updated_at=NOW()
            WHERE book_run_id=%s AND state='READY'
              AND current_chapter=%s AND version=%s
            """,
            [chapter_request_id, book_run_id, chapter_number - 1, expected_version],
        )
        return self.cursor.rowcount == 1

    def link_chapter(
        self,
        *,
        chapter_request_id: str,
        book_run_id: str,
        project_id: str,
        chapter_number: int,
        chapter_plan_version: str,
        stable_idempotency_key: str,
        delegation_id: str,
        root_operation_id: str,
        saga_id: str,
        expected_book_version: int,
    ) -> None:
        self.cursor.execute(
            """
            UPDATE authority_book_chapter_request
            SET chapter_root_operation_id=%s, chapter_saga_id=%s,
                status_reference='ADMITTED', updated_at=NOW()
            WHERE chapter_request_id=%s AND chapter_root_operation_id IS NULL
            """,
            [root_operation_id, saga_id, chapter_request_id],
        )
        self.cursor.execute(
            """
            INSERT INTO authority_child_delegation(
                delegation_id, project_id, owner_authority, owner_id,
                child_authority, chapter_request_id, chapter_number,
                plan_version_id, child_root_operation_id, child_saga_id,
                stable_idempotency_key, status
            ) VALUES (
                %s, %s, 'BOOK', %s, 'CHAPTER', %s, %s, %s, %s, %s, %s,
                'DISPATCHED'
            )
            ON CONFLICT (project_id, stable_idempotency_key) DO NOTHING
            """,
            [
                delegation_id,
                project_id,
                book_run_id,
                chapter_request_id,
                chapter_number,
                chapter_plan_version,
                root_operation_id,
                saga_id,
                stable_idempotency_key,
            ],
        )
        self.cursor.execute(
            """
            UPDATE authority_book_production
            SET active_chapter_request_id=%s, active_child_delegation_id=%s,
                active_chapter_number=%s, active_plan_version_id=%s,
                state='CHAPTER_SUBMITTED', version=version+1, updated_at=NOW()
            WHERE book_run_id=%s AND version=%s
            """,
            [
                chapter_request_id,
                delegation_id,
                chapter_number,
                chapter_plan_version,
                book_run_id,
                expected_book_version,
            ],
        )
        if self.cursor.rowcount != 1:
            raise ValueError("Book checkpoint changed before Chapter link")

    def record_chapter_status(
        self,
        *,
        chapter_request_id: str,
        book_run_id: str,
        request_status: str,
        book_state: str,
        expected_request_status: str,
        expected_book_version: int,
    ) -> None:
        self.cursor.execute(
            """
            UPDATE authority_book_chapter_request
            SET status_reference=%s, updated_at=NOW()
            WHERE chapter_request_id=%s AND status_reference=%s
            """,
            [request_status, chapter_request_id, expected_request_status],
        )
        if self.cursor.rowcount != 1:
            raise ValueError("Chapter request changed before status reconciliation")
        self.cursor.execute(
            """
            UPDATE authority_book_production
            SET state=%s, version=version+1, updated_at=NOW()
            WHERE book_run_id=%s AND version=%s
            """,
            [book_state, book_run_id, expected_book_version],
        )
        if self.cursor.rowcount != 1:
            raise ValueError("Book checkpoint changed before status reconciliation")
        self.cursor.execute(
            """
            UPDATE authority_child_delegation
            SET status=%s, version=version+1, updated_at=NOW()
            WHERE chapter_request_id=%s
              AND status <> 'ACCEPTED'
            """,
            [
                {
                    "ADMITTED": "DISPATCHED",
                    "RUNNING": "RUNNING",
                    "WAITING_RETRY": "WAITING_RETRY",
                    "SUCCEEDED": "SUCCEEDED",
                    "FAILED_RETRYABLE": "FAILED_RETRYABLE",
                    "FAILED_TERMINAL": "FAILED_TERMINAL",
                    "CANCELLED": "CANCELLED",
                    "UNKNOWN": "UNKNOWN",
                }.get(request_status, "UNKNOWN"),
                chapter_request_id,
            ],
        )

    def commit_chapter_acceptance(
        self,
        *,
        acceptance_id: str,
        project_id: str,
        book_run_id: str,
        chapter_request_id: str,
        delegation_id: str,
        acceptance_operation_id: str,
        chapter_number: int,
        chapter_outcome_asset_version_id: str,
        story_state_asset_version_id: str,
        canon_snapshot_asset_version_id: str,
        longform_projection_set: dict[str, Any],
        evidence: dict[str, Any],
        expected_book_version: int,
        before_cursor_advance: Callable[[], None] | None = None,
    ) -> bool:
        self.cursor.execute(
            """
            INSERT INTO authority_book_chapter_acceptance(
                acceptance_id, project_id, book_run_id, chapter_request_id,
                delegation_id, acceptance_operation_id, chapter_number,
                chapter_outcome_asset_version_id, story_state_asset_version_id,
                canon_snapshot_asset_version_id, longform_projection_set_id,
                evidence, status
            ) VALUES (
                %(acceptance_id)s, %(project_id)s, %(book_run_id)s,
                %(chapter_request_id)s, %(delegation_id)s,
                %(acceptance_operation_id)s, %(chapter_number)s,
                %(chapter_outcome_asset_version_id)s,
                %(story_state_asset_version_id)s,
                %(canon_snapshot_asset_version_id)s,
                %(longform_projection_set_id)s, %(evidence)s, 'COMMITTED'
            )
            ON CONFLICT (chapter_request_id) DO NOTHING
            """,
            {
                "acceptance_id": acceptance_id,
                "project_id": project_id,
                "book_run_id": book_run_id,
                "chapter_request_id": chapter_request_id,
                "delegation_id": delegation_id,
                "acceptance_operation_id": acceptance_operation_id,
                "chapter_number": chapter_number,
                "chapter_outcome_asset_version_id": chapter_outcome_asset_version_id,
                "story_state_asset_version_id": story_state_asset_version_id,
                "canon_snapshot_asset_version_id": canon_snapshot_asset_version_id,
                "longform_projection_set_id": longform_projection_set[
                    "projection_set_id"
                ],
                "evidence": Jsonb(evidence),
            },
        )
        inserted = self.cursor.rowcount == 1
        self.commit_longform_projection_set(longform_projection_set)
        if before_cursor_advance is not None:
            before_cursor_advance()
        self.cursor.execute(
            """
            UPDATE authority_child_delegation
            SET status='ACCEPTED', accepted_at=COALESCE(accepted_at, NOW()),
                version=version+1, updated_at=NOW()
            WHERE delegation_id=%s
              AND status IN ('SUCCEEDED', 'ACCEPTED')
            """,
            [delegation_id],
        )
        self.cursor.execute(
            """
            UPDATE authority_book_production
            SET current_chapter=GREATEST(current_chapter, %s),
                accepted_through_chapter=GREATEST(accepted_through_chapter, %s),
                active_chapter_request_id=NULL,
                active_child_delegation_id=NULL,
                active_chapter_number=NULL,
                active_plan_version_id=NULL,
                active_story_state_version_id=%s,
                active_canon_snapshot_version_id=%s,
                last_chapter_outcome_version_id=%s,
                active_longform_projection_set_id=%s,
                state='READY',
                version=version+1, updated_at=NOW()
            WHERE book_run_id=%s
              AND accepted_through_chapter IN (%s, %s)
              AND version=%s
            """,
            [
                chapter_number,
                chapter_number,
                story_state_asset_version_id,
                canon_snapshot_asset_version_id,
                chapter_outcome_asset_version_id,
                longform_projection_set["projection_set_id"],
                book_run_id,
                chapter_number - 1,
                chapter_number,
                expected_book_version,
            ],
        )
        if self.cursor.rowcount != 1:
            raise ValueError("Book cursor cannot accept a non-sequential Chapter")
        return inserted

    def commit_longform_projection_set(self, projection: dict[str, Any]) -> None:
        boundary = dict(projection["accepted_boundary"])
        sources = dict(projection["source_versions"])
        projection_set_id = str(projection["projection_set_id"])
        self.cursor.execute(
            """
            INSERT INTO authority_book_narrative_projection_set(
                projection_set_id, acceptance_id, project_id, book_id,
                book_run_id, chapter_request_id, chapter_number,
                acceptance_operation_id, chapter_outcome_asset_version_id,
                story_state_asset_version_id, canon_snapshot_asset_version_id,
                arc_state, obligation_state, projection_hash,
                projection_provenance, status
            ) VALUES (
                %(projection_set_id)s, %(acceptance_id)s, %(project_id)s,
                %(book_id)s, %(book_run_id)s, %(chapter_request_id)s,
                %(chapter_number)s, %(acceptance_operation_id)s,
                %(chapter_outcome_asset_version_id)s,
                %(story_state_asset_version_id)s,
                %(canon_snapshot_asset_version_id)s,
                %(arc_state)s, %(obligation_state)s, %(projection_hash)s,
                %(projection_provenance)s,
                'COMPLETE'
            )
            ON CONFLICT (acceptance_id) DO NOTHING
            """,
            {
                "projection_set_id": projection_set_id,
                "acceptance_id": boundary["acceptance_id"],
                "project_id": projection["project_id"],
                "book_id": projection["book_id"],
                "book_run_id": projection["book_run_id"],
                "chapter_request_id": projection["chapter_request_id"],
                "chapter_number": boundary["chapter_number"],
                "acceptance_operation_id": boundary["acceptance_operation_id"],
                "chapter_outcome_asset_version_id": sources[
                    "chapter_outcome_asset_version_id"
                ],
                "story_state_asset_version_id": sources[
                    "story_state_asset_version_id"
                ],
                "canon_snapshot_asset_version_id": sources[
                    "canon_snapshot_asset_version_id"
                ],
                "arc_state": Jsonb(list(projection["arc_states"])),
                "obligation_state": Jsonb(list(projection["obligation_states"])),
                "projection_hash": projection["projection_hash"],
                "projection_provenance": Jsonb(
                    dict(projection.get("projection_provenance") or {})
                ),
            },
        )
        progress_by_id = {
            str(item["progress_id"]): dict(item)
            for item in projection["arc_progress"]
        }
        for progress in progress_by_id.values():
            accepted = dict(progress["accepted_boundary"])
            source = dict(progress["source"])
            self.cursor.execute(
                """
                INSERT INTO authority_arc_progress_v2(
                    progress_id, projection_set_id, project_id, book_id,
                    arc_plan_version_id, chapter_number,
                    acceptance_operation_id, chapter_outcome_asset_version_id,
                    observation_status, contribution_kind, progress_units,
                    cumulative_progress_units, deviation_units, evidence
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (project_id, book_id, arc_plan_version_id, chapter_number)
                DO NOTHING
                """,
                [
                    progress["progress_id"],
                    projection_set_id,
                    projection["project_id"],
                    projection["book_id"],
                    progress["arc_plan_version_id"],
                    accepted["chapter_number"],
                    accepted["acceptance_operation_id"],
                    source["chapter_outcome_asset_version_id"],
                    progress["observation_status"],
                    progress["contribution_kind"],
                    progress["progress_units"],
                    progress["cumulative_progress_units"],
                    progress["deviation_units"],
                    Jsonb(dict(progress["evidence"])),
                ],
            )
        for state in projection["arc_states"]:
            self.cursor.execute(
                """
                INSERT INTO authority_arc_actual_state(
                    project_id, book_id, arc_plan_version_id,
                    projection_set_id, accepted_through_chapter,
                    acceptance_operation_id, observation_status,
                    lifecycle_status, cumulative_progress_units,
                    current_phase, state, version
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1)
                ON CONFLICT (project_id, book_id, arc_plan_version_id)
                DO UPDATE SET
                    projection_set_id=EXCLUDED.projection_set_id,
                    accepted_through_chapter=EXCLUDED.accepted_through_chapter,
                    acceptance_operation_id=EXCLUDED.acceptance_operation_id,
                    observation_status=EXCLUDED.observation_status,
                    lifecycle_status=EXCLUDED.lifecycle_status,
                    cumulative_progress_units=EXCLUDED.cumulative_progress_units,
                    current_phase=EXCLUDED.current_phase,
                    state=EXCLUDED.state,
                    version=authority_arc_actual_state.version+1,
                    updated_at=NOW()
                WHERE authority_arc_actual_state.accepted_through_chapter
                      IN (EXCLUDED.accepted_through_chapter-1,
                          EXCLUDED.accepted_through_chapter)
                """,
                [
                    projection["project_id"],
                    projection["book_id"],
                    state["arc_plan_version_id"],
                    projection_set_id,
                    state["accepted_through_chapter"],
                    state["acceptance_operation_id"],
                    state["observation_status"],
                    state["lifecycle_status"],
                    state["cumulative_progress_units"],
                    state["current_phase"],
                    Jsonb(dict(state)),
                ],
            )
        for checkpoint in projection["arc_checkpoints"]:
            accepted = dict(checkpoint["accepted_boundary"])
            self.cursor.execute(
                """
                INSERT INTO authority_arc_checkpoint_v2(
                    checkpoint_id, projection_set_id, project_id, book_id,
                    arc_plan_version_id, accepted_through_chapter,
                    acceptance_operation_id, progress_id, decision, reasons,
                    checkpoint
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (project_id, book_id, arc_plan_version_id,
                             accepted_through_chapter) DO NOTHING
                """,
                [
                    checkpoint["checkpoint_id"],
                    projection_set_id,
                    projection["project_id"],
                    projection["book_id"],
                    checkpoint["arc_plan_version_id"],
                    accepted["chapter_number"],
                    accepted["acceptance_operation_id"],
                    checkpoint["progress_id"],
                    str(checkpoint["decision"]),
                    Jsonb(list(checkpoint["reasons"])),
                    Jsonb(dict(checkpoint)),
                ],
            )
        for outcome in projection["arc_outcomes"]:
            self.cursor.execute(
                """
                INSERT INTO authority_arc_outcome_v2(
                    arc_outcome_id, projection_set_id, project_id, book_id,
                    arc_plan_version_id, accepted_through_chapter,
                    acceptance_operation_id, status, completion_evidence
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (project_id, book_id, arc_plan_version_id) DO NOTHING
                """,
                [
                    outcome["arc_outcome_id"],
                    projection_set_id,
                    projection["project_id"],
                    projection["book_id"],
                    outcome["arc_plan_version_id"],
                    outcome["accepted_through_chapter"],
                    outcome["acceptance_operation_id"],
                    outcome["status"],
                    Jsonb(dict(outcome["completion_evidence"])),
                ],
            )
        for obligation in projection["obligation_states"]:
            state = dict(obligation.get("state") or {})
            obligation_id = str(
                state.get("obligation_id") or obligation.get("entity_key") or ""
            )
            if not obligation_id:
                raise ValueError("accepted obligation projection lacks identity")
            self.cursor.execute(
                """
                INSERT INTO authority_narrative_obligation_state(
                    project_id, book_id, obligation_id, projection_set_id,
                    accepted_through_chapter, acceptance_operation_id,
                    story_state_asset_version_id, obligation_type, status,
                    state, version
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1)
                ON CONFLICT (project_id, book_id, obligation_id)
                DO UPDATE SET
                    projection_set_id=EXCLUDED.projection_set_id,
                    accepted_through_chapter=EXCLUDED.accepted_through_chapter,
                    acceptance_operation_id=EXCLUDED.acceptance_operation_id,
                    story_state_asset_version_id=EXCLUDED.story_state_asset_version_id,
                    obligation_type=EXCLUDED.obligation_type,
                    status=EXCLUDED.status,
                    state=EXCLUDED.state,
                    version=authority_narrative_obligation_state.version+1,
                    updated_at=NOW()
                WHERE authority_narrative_obligation_state.accepted_through_chapter
                      IN (EXCLUDED.accepted_through_chapter-1,
                          EXCLUDED.accepted_through_chapter)
                """,
                [
                    projection["project_id"],
                    projection["book_id"],
                    obligation_id,
                    projection_set_id,
                    obligation["accepted_through_chapter"],
                    obligation["acceptance_operation_id"],
                    obligation["story_state_asset_version_id"],
                    state.get("obligation_type") or "UNKNOWN",
                    state.get("status") or "UNKNOWN",
                    Jsonb(dict(obligation)),
                ],
            )
        self._commit_narrative_retrieval_documents(projection)

    def _commit_narrative_retrieval_documents(
        self, projection: dict[str, Any]
    ) -> None:
        """Index accepted evidence deterministically inside Book Acceptance."""

        sources = dict(projection["source_versions"])
        chapter = int(projection["accepted_boundary"]["chapter_number"])
        operation_id = str(
            projection["accepted_boundary"]["acceptance_operation_id"]
        )
        arc_ids = sorted(
            {
                str(item.get("arc_plan_version_id") or "")
                for item in projection["arc_states"]
                if str(item.get("arc_plan_version_id") or "")
            }
        )
        obligation_ids = sorted(
            {
                str((item.get("state") or {}).get("obligation_id") or item.get("entity_key") or "")
                for item in projection["obligation_states"]
                if str((item.get("state") or {}).get("obligation_id") or item.get("entity_key") or "")
            }
        )
        specifications = (
            (
                sources["chapter_outcome_asset_version_id"],
                "L6",
                None,
                {"projection_kind": "accepted_chapter_outcome"},
            ),
            (
                sources["chapter_outcome_asset_version_id"],
                "L5",
                {
                    "arc_progress": list(projection["arc_progress"]),
                    "arc_states": list(projection["arc_states"]),
                    "arc_checkpoints": list(projection["arc_checkpoints"]),
                },
                {"projection_kind": "accepted_arc_state"},
            ),
            (
                sources["story_state_asset_version_id"],
                "L1",
                None,
                {"projection_kind": "accepted_current_state"},
            ),
            (
                sources["story_state_asset_version_id"],
                "L4",
                {"obligations": list(projection["obligation_states"])},
                {"projection_kind": "accepted_obligation_state"},
            ),
            (
                sources["canon_snapshot_asset_version_id"],
                "L2",
                None,
                {"projection_kind": "accepted_canon"},
            ),
        )
        for source_version_id, memory_layer, projected_content, metadata in specifications:
            self.cursor.execute(
                """
                SELECT asset.asset_type, version.content
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE version.asset_version_id=%s AND asset.project_id=%s
                """,
                [source_version_id, projection["project_id"]],
            )
            source = self.cursor.fetchone()
            if source is None:
                raise ValueError("accepted retrieval source AssetVersion is missing")
            content = (
                dict(projected_content)
                if projected_content is not None
                else dict(source[1] or {})
            )
            content_text = json.dumps(
                content,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            identity = (
                f"{projection['project_id']}:{projection['book_id']}:"
                f"{source_version_id}:{memory_layer}"
            )
            retrieval_document_id = "narrative-retrieval:" + hashlib.sha256(
                identity.encode()
            ).hexdigest()
            document = {
                "retrieval_document_id": retrieval_document_id,
                "project_id": projection["project_id"],
                "book_id": projection["book_id"],
                "source_asset_version_id": source_version_id,
                "source_artifact_type": str(source[0]),
                "accepted_from_chapter": chapter,
                "memory_layer": memory_layer,
                "content_text": content_text,
                "arc_plan_version_ids": arc_ids,
                "obligation_ids": obligation_ids,
                "metadata": {
                    **metadata,
                    "projection_set_id": projection["projection_set_id"],
                    "accepted_boundary": dict(projection["accepted_boundary"]),
                },
            }
            projection_hash = "sha256:" + hashlib.sha256(
                json.dumps(
                    document,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            self.cursor.execute(
                """
                INSERT INTO authority_narrative_retrieval_document(
                    retrieval_document_id, project_id, book_id,
                    source_asset_version_id, source_artifact_type,
                    accepted_from_chapter, memory_layer, content_text,
                    arc_plan_version_ids, obligation_ids, temporal_coordinate,
                    metadata, projection_hash, created_by_operation_id
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(project_id, book_id, source_asset_version_id,
                            memory_layer) DO NOTHING
                """,
                [
                    retrieval_document_id,
                    projection["project_id"],
                    projection["book_id"],
                    source_version_id,
                    str(source[0]),
                    chapter,
                    memory_layer,
                    content_text,
                    Jsonb(arc_ids),
                    Jsonb(obligation_ids),
                    Jsonb({"accepted_chapter": chapter}),
                    Jsonb(document["metadata"]),
                    projection_hash,
                    operation_id,
                ],
            )

    def abort(self, *, book_run_id: str, reason: str) -> None:
        self.cursor.execute(
            """
            UPDATE authority_child_delegation
            SET status=CASE
                    WHEN status IN ('DISPATCHED', 'RUNNING', 'WAITING_RETRY',
                                    'SUCCEEDED', 'UNKNOWN')
                    THEN 'CANCELLATION_REQUESTED'
                    ELSE status
                END,
                version=version+1, updated_at=NOW()
            WHERE owner_id=%s AND status <> 'ACCEPTED'
            """,
            [book_run_id],
        )
        self.cursor.execute(
            """
            UPDATE authority_book_production
            SET state='ABORTED', failure_reason=%s, paused_reason=%s,
                version=version+1, updated_at=NOW()
            WHERE book_run_id=%s AND state <> 'COMPLETED'
            """,
            [reason, reason, book_run_id],
        )

    def link_followup(
        self,
        *,
        followup_id: str,
        book_run_id: str,
        chapter_request_id: str,
        project_id: str,
        followup_type: str,
        operation_id: str,
        stable_idempotency_key: str,
    ) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_book_followup_operation (
                followup_id, book_run_id, chapter_request_id, project_id,
                followup_type, operation_id, stable_idempotency_key
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (project_id, stable_idempotency_key) DO NOTHING
            """,
            [
                followup_id,
                book_run_id,
                chapter_request_id,
                project_id,
                followup_type,
                operation_id,
                stable_idempotency_key,
            ],
        )
    def advance(
        self,
        *,
        book_run_id: str,
        chapter_number: int,
        state: str,
    ) -> None:
        self.cursor.execute(
            """
            UPDATE authority_book_production
            SET state=%s, current_chapter=GREATEST(current_chapter, %s),
                version=version+1, updated_at=NOW()
            WHERE book_run_id=%s
            """,
            [state, chapter_number, book_run_id],
        )

    def set_gate_state(self, *, book_run_id: str, state: str, reason: str = "") -> None:
        self.cursor.execute(
            """
            UPDATE authority_book_production
            SET state=%s, paused_reason=%s, version=version+1,
                updated_at=NOW()
            WHERE book_run_id=%s
            """,
            [state, reason, book_run_id],
        )


__all__ = ["BookAuthorityRepository"]
