from __future__ import annotations

import hashlib
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.book_production.domain import (
    ArcStatus,
    EndingReachabilityInput,
    evaluate_ending_reachability,
    required_arc_contributions,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    TransactionCheckpoint,
    execute_transaction_command,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


class PostgresBookNarrativeCheckpointAuthority:

    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
    ) -> None:
        if not database_url or not application_build_id or len(commit_sha) != 40:
            raise ValueError("PostgreSQL and build identity are required")
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha

    def record_after_acceptance(
        self,
        *,
        book_run_id: str,
        chapter_request_id: str,
        principal: Principal,
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            row = self._acceptance_context(uow.cursor, book_run_id, chapter_request_id)
        project_id, workspace_id, book_id = map(str, row[:3])
        principal.require("book.authority.execute", project_id)
        self._register_definition()

        def handler(
            uow: AuthorityUnitOfWork,
            operation_id: str,
            checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            checkpoint("after_domain_validation")
            result = self._record_in_uow(
                uow,
                operation_id=operation_id,
                book_run_id=book_run_id,
                chapter_request_id=chapter_request_id,
            )
            checkpoint("after_outbox_insert")
            return result

        result = execute_transaction_command(
            self.database_url,
            {
                "definition_name": "book.narrative_checkpoint.record",
                "definition_version": "1.0.0",
                "project_id": project_id,
                "workspace_id": workspace_id,
                "book_id": book_id,
                "actor_id": principal.principal_id,
                "idempotency_scope": "book:narrative-checkpoint",
                "idempotency_key": f"{book_run_id}:{chapter_request_id}",
                "trace_id": f"{row[10]}:narrative-checkpoint",
                "span_id": str(uuid4()),
                "correlation_id": str(row[10]),
                "causation_id": str(row[10]),
                "causation_operation_id": str(row[10]),
                "input": {
                    "book_run_id": book_run_id,
                    "chapter_request_id": chapter_request_id,
                    "chapter_acceptance_operation_id": str(row[10]),
                    "chapter_plan_version_id": str(row[11]),
                    "chapter_outcome_asset_version_id": str(row[13]),
                },
                "input_assets": self._input_assets(
                    project_id, (str(row[11]), str(row[13]))
                ),
            },
            context=AdmissionContext(
                actor_id=principal.principal_id,
                permissions=frozenset({"book.authority.execute"}),
                available_handlers=frozenset(
                    {"novel_forge.book.narrative_checkpoint.record"}
                ),
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
            handler=handler,
        )
        return dict(result)

    def _record_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        *,
        operation_id: str,
        book_run_id: str,
        chapter_request_id: str,
    ) -> dict[str, Any]:
        row = self._acceptance_context(uow.cursor, book_run_id, chapter_request_id)
        chapter_plan = dict(row[12])
        volumes = self._portfolio_assets(
            uow.cursor,
            project_id=str(row[0]),
            asset_version_ids=tuple(str(item) for item in row[15]),
        )
        arcs = self._portfolio_assets(
            uow.cursor,
            project_id=str(row[0]),
            asset_version_ids=tuple(str(item) for item in row[16]),
        )
        # WORKAROUND: lazy import avoids the Book Authority initialization cycle.
        from novel_forge.modules.book_authority.input_resolver import (
            project_current_plan_cursor,
        )

        current_volume, current_arcs = project_current_plan_cursor(
            volumes=volumes,
            arcs=arcs,
            chapter_cursor=int(row[4]),
        )
        declared = required_arc_contributions(chapter_plan)
        active_arcs = current_arcs
        if any(arc_id not in active_arcs for arc_id in declared):
            raise KernelError(
                "ARC_CONTRIBUTION_PLAN_SCOPE_INVALID",
                "ChapterPlan declares an Arc outside the Book input snapshot",
            )
        arc_status, observed_count = self._accepted_arc_projection(
            uow.cursor,
            project_id=str(row[0]),
            book_id=str(row[2]),
            projection_set_id=str(row[17] or ""),
            active_arcs=active_arcs,
        )
        reachability = self._append_ending_report(
            uow.cursor,
            project_id=str(row[0]),
            book_id=str(row[2]),
            book_run_id=book_run_id,
            ending_contract_version=str(row[6]),
            chapter_number=int(row[4]),
            target_chapter_count=int(row[5]),
            acceptance_operation_id=operation_id,
            chapter_plan=chapter_plan,
            arc_status=arc_status,
        )
        volume = self._append_volume_checkpoint(
            uow.cursor,
            project_id=str(row[0]),
            book_id=str(row[2]),
            book_run_id=book_run_id,
            volume_plan_version=str(current_volume["asset_version_id"]),
            active_chapter_group=str(row[9] or ""),
            chapter_number=int(row[4]),
            target_chapter_count=int(row[5]),
            arc_status=arc_status,
            reachability=reachability,
            acceptance_operation_id=operation_id,
        )
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": "book_narrative_checkpoint",
                "aggregate_id": book_run_id,
                "operation_id": operation_id,
                "project_id": str(row[0]),
                "event_type": "book.narrative_checkpoint.recorded",
                "correlation_id": str(row[10]),
                "causation_id": str(row[10]),
                "payload": {
                    "operation_id": operation_id,
                    "chapter_acceptance_operation_id": str(row[10]),
                    "chapter_request_id": chapter_request_id,
                    "volume_checkpoint_id": volume["checkpoint_id"],
                    "ending_report_hash": reachability["report_hash"],
                    "observed_arc_count": observed_count,
                    "longform_projection_set_id": str(row[17]),
                },
            }
        )
        return {
            "arc_status_snapshot": arc_status,
            "ending_reachability": reachability,
            "volume_checkpoint": volume,
            "observed_arc_count": observed_count,
            "longform_projection_set_id": str(row[17]),
        }

    def _register_definition(self) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.definitions.register(
                _narrative_checkpoint_definition(
                    application_build_id=self.application_build_id,
                    commit_sha=self.commit_sha,
                )
            )
            uow.commit()

    def _input_assets(
        self, project_id: str, version_ids: tuple[str, ...]
    ) -> list[dict[str, str]]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT version.asset_version_id, version.content_hash
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE asset.project_id=%s
                  AND version.asset_version_id=ANY(%s::text[])
                """,
                [project_id, list(version_ids)],
            )
            rows = uow.cursor.fetchall()
        if {str(row[0]) for row in rows} != set(version_ids):
            raise KernelError(
                "BOOK_CHECKPOINT_INPUT_AUTHORITY_INVALID",
                "Chapter plan or outcome is outside the Book Project",
            )
        return [
            {"asset_version_id": str(row[0]), "content_hash": str(row[1])}
            for row in rows
        ]

    @staticmethod
    def _acceptance_context(
        cursor: Any, book_run_id: str, request_id: str
    ) -> tuple[Any, ...]:
        cursor.execute(
            """
            SELECT book.project_id, book.workspace_id, book.book_id,
                   snapshot.snapshot_id, request.chapter_number,
                   book.target_chapter_count, snapshot.book_plan_version,
                   snapshot.current_volume_plan_version,
                   snapshot.current_relevant_arc_plan_versions,
                   snapshot.current_chapter_group_plan_version,
                   acceptance.acceptance_operation_id,
                   request.chapter_plan_version, plan.content,
                   acceptance.chapter_outcome_asset_version_id, outcome.content
                   , snapshot.volume_portfolio_plan_versions
                   , snapshot.arc_portfolio_plan_versions
                   , acceptance.longform_projection_set_id
            FROM authority_book_production AS book
            JOIN authority_book_chapter_request AS request
              ON request.book_run_id=book.book_run_id
            JOIN authority_book_chapter_acceptance AS acceptance
              ON acceptance.chapter_request_id=request.chapter_request_id
            JOIN authority_book_production_input_snapshot AS snapshot
              ON snapshot.snapshot_id=COALESCE(
                  NULLIF(request.command_payload #>> '{context_version_refs,book_production_input_snapshot_id}', ''),
                  NULLIF(acceptance.evidence #>> '{followup_snapshot,book_production_input_snapshot_id}', ''),
                  (SELECT binding.snapshot_id FROM authority_book_production_input_binding binding
                   WHERE binding.book_run_id=book.book_run_id AND binding.created_at<=request.created_at
                   ORDER BY binding.binding_version DESC LIMIT 1))
             AND snapshot.project_id=book.project_id AND snapshot.workspace_id=book.workspace_id
             AND snapshot.book_id=book.book_id
            JOIN authority_asset_version AS plan
              ON plan.asset_version_id=request.chapter_plan_version
            JOIN authority_asset_version AS outcome
              ON outcome.asset_version_id=acceptance.chapter_outcome_asset_version_id
            WHERE book.book_run_id=%s AND request.chapter_request_id=%s
            """,
            [book_run_id, request_id],
        )
        row = cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_CHECKPOINT_ACCEPTANCE_MISSING",
                "resolved Book input and Chapter acceptance are required",
            )
        return tuple(row)

    @staticmethod
    def _portfolio_assets(
        cursor: Any, *, project_id: str, asset_version_ids: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        cursor.execute(
            """
            SELECT version.asset_version_id, version.content
            FROM authority_asset_version AS version
            JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
            WHERE asset.project_id=%s
              AND version.asset_version_id=ANY(%s::text[])
            """,
            [project_id, list(asset_version_ids)],
        )
        by_id = {
            str(row[0]): {
                "asset_version_id": str(row[0]),
                "content": dict(row[1]),
            }
            for row in cursor.fetchall()
        }
        if set(by_id) != set(asset_version_ids):
            raise KernelError(
                "BOOK_CHECKPOINT_PORTFOLIO_STALE",
                "frozen Book plan portfolio is incomplete at checkpoint acceptance",
            )
        return [by_id[item] for item in asset_version_ids]

    @staticmethod
    def _accepted_arc_projection(
        cursor: Any,
        *,
        project_id: str,
        book_id: str,
        projection_set_id: str,
        active_arcs: tuple[str, ...],
    ) -> tuple[dict[str, str], int]:
        if not projection_set_id:
            raise KernelError(
                "BOOK_LONGFORM_PROJECTION_INCOMPLETE",
                "narrative checkpoint requires the complete acceptance projection set",
            )
        cursor.execute(
            """
            SELECT state.arc_plan_version_id, state.lifecycle_status,
                   state.observation_status, checkpoint.decision
            FROM authority_arc_actual_state AS state
            JOIN authority_arc_checkpoint_v2 AS checkpoint
              ON checkpoint.projection_set_id=state.projection_set_id
             AND checkpoint.arc_plan_version_id=state.arc_plan_version_id
            WHERE state.project_id=%s AND state.book_id=%s
              AND state.projection_set_id=%s
              AND state.arc_plan_version_id=ANY(%s::text[])
            """,
            [
                project_id,
                book_id,
                projection_set_id,
                list(active_arcs),
            ],
        )
        rows = cursor.fetchall()
        if {str(row[0]) for row in rows} != set(active_arcs):
            raise KernelError(
                "BOOK_LONGFORM_PROJECTION_INCOMPLETE",
                "accepted Arc projection does not cover the frozen active Arc set",
            )
        result: dict[str, str] = {}
        observed_count = 0
        for arc_id, lifecycle_status, observation_status, decision in rows:
            lifecycle = str(lifecycle_status)
            observation = str(observation_status)
            observed_count += observation == "OBSERVED"
            if lifecycle == "COMPLETED":
                status = ArcStatus.COMPLETED.value
            elif lifecycle == "ABANDONED":
                status = ArcStatus.ABORTED.value
            else:
                status = str(decision or lifecycle)
            result[str(arc_id)] = status
        return result, observed_count

    @staticmethod
    def _append_ending_report(
        cursor: Any,
        *,
        project_id: str,
        book_id: str,
        book_run_id: str,
        ending_contract_version: str,
        chapter_number: int,
        target_chapter_count: int,
        acceptance_operation_id: str,
        chapter_plan: dict[str, Any],
        arc_status: dict[str, str],
    ) -> dict[str, Any]:
        open_arcs = sum(
            status not in {ArcStatus.COMPLETED.value, ArcStatus.ABORTED.value}
            for status in arc_status.values()
        )
        value = EndingReachabilityInput(
            evaluated_through_chapter=chapter_number,
            target_chapter_count=target_chapter_count,
            minimum_ending_chapters=int(
                chapter_plan.get("minimum_ending_chapters") or 1
            ),
            critical_arc_open_count=open_arcs,
            critical_arc_closure_capacity=int(
                chapter_plan.get("arc_closure_capacity_remaining")
                or max(0, target_chapter_count - chapter_number)
            ),
            required_event_count=len(chapter_plan.get("required_future_events") or ()),
            open_event_window_count=int(
                chapter_plan.get("open_event_window_count")
                or max(0, target_chapter_count - chapter_number)
            ),
            unsettled_promise_count=len(chapter_plan.get("unsettled_promises") or ()),
            promise_settlement_capacity=int(
                chapter_plan.get("promise_settlement_capacity")
                or max(0, target_chapter_count - chapter_number)
            ),
        )
        report = evaluate_ending_reachability(value)
        report_id = (
            "ending-reachability:"
            + hashlib.sha256(
                f"{project_id}:{book_id}:{report.report_hash}".encode()
            ).hexdigest()
        )
        cursor.execute(
            """
            INSERT INTO authority_ending_reachability_report(
                report_id, project_id, book_id, book_run_id,
                ending_contract_version, evaluated_through_chapter,
                remaining_chapter_budget, ending_contract_reachable,
                critical_arc_closure_path, chapter_budget_sufficient,
                required_event_windows_open, promise_capacity_sufficient,
                replan_required, reasons, report_hash, generated_by_operation_id
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (project_id, book_id, report_hash) DO NOTHING
            """,
            [
                report_id,
                project_id,
                book_id,
                book_run_id,
                ending_contract_version,
                report.evaluated_through_chapter,
                report.remaining_chapter_budget,
                report.ending_contract_reachable,
                report.critical_arc_closure_path,
                report.chapter_budget_sufficient,
                report.required_event_windows_open,
                report.promise_capacity_sufficient,
                report.replan_required,
                Jsonb(list(report.reasons)),
                report.report_hash,
                acceptance_operation_id,
            ],
        )
        return report.to_dict()

    @staticmethod
    def _append_volume_checkpoint(
        cursor: Any,
        *,
        project_id: str,
        book_id: str,
        book_run_id: str,
        volume_plan_version: str,
        active_chapter_group: str,
        chapter_number: int,
        target_chapter_count: int,
        arc_status: dict[str, str],
        reachability: dict[str, Any],
        acceptance_operation_id: str,
    ) -> dict[str, Any]:
        cursor.execute(
            """
            SELECT COALESCE(MAX(version),0)
            FROM authority_book_volume_checkpoint
            WHERE book_run_id=%s AND volume_plan_version=%s
            """,
            [book_run_id, volume_plan_version],
        )
        version = int(cursor.fetchone()[0]) + 1
        state = "COMPLETED" if chapter_number >= target_chapter_count else "ACTIVE"
        checkpoint_id = f"volume-checkpoint:{hashlib.sha256(f'{book_run_id}:{volume_plan_version}:{version}'.encode()).hexdigest()}"
        cursor.execute(
            """
            INSERT INTO authority_book_volume_checkpoint(
                checkpoint_id, project_id, book_id, book_run_id,
                volume_plan_version, chapter_range, accepted_through_chapter,
                active_chapter_group, volume_goal_status, arc_status_snapshot,
                promise_settlement_status, ending_reachability, state, version,
                updated_by_operation_id
            ) VALUES (%s,%s,%s,%s,%s,int4range(1,%s,'[]'),%s,NULLIF(%s,''),%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (book_run_id, volume_plan_version, version) DO NOTHING
            """,
            [
                checkpoint_id,
                project_id,
                book_id,
                book_run_id,
                volume_plan_version,
                target_chapter_count,
                chapter_number,
                active_chapter_group,
                "NOT_PROVEN" if state == "COMPLETED" else "IN_PROGRESS",
                Jsonb(arc_status),
                "AT_RISK" if reachability["replan_required"] else "TRACKING",
                reachability["status"],
                state,
                version,
                acceptance_operation_id,
            ],
        )
        return {
            "checkpoint_id": checkpoint_id,
            "version": version,
            "state": state,
            "accepted_through_chapter": chapter_number,
        }

def _narrative_checkpoint_definition(
    *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    schema = {"type": "object"}
    return {
        "name": "book.narrative_checkpoint.record",
        "definition_version": "1.0.0",
        "family": "book_authority",
        "enabled": True,
        "definition_status": "implemented_validation_pending",
        "command_schema_version": "book.narrative_checkpoint.command.v1",
        "result_schema_version": "book.narrative_checkpoint.result.v1",
        "command_schema": schema,
        "result_schema": schema,
        "input_contract": schema,
        "output_contract": {"type": "BookNarrativeCheckpointFacts"},
        "handler_key": "novel_forge.book.narrative_checkpoint.record",
        "handler_contract_version": "book-narrative-checkpoint-v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "transactional",
        "permissions": ["book.authority.execute"],
        "approval_policy": {"required": False},
        "policy": {
            "execution_classification": "transaction_command",
            "chapter_acceptance_required": True,
            "append_only": True,
        },
        "idempotency_scope": "book:narrative-checkpoint",
        "concurrency_key_template": "book:{book_id}:narrative-checkpoint",
        "retry_policy": {"max_attempts": 1},
        "timeout_policy": {"operation_timeout_seconds": 30},
        "cancellation_policy": {"mode": "not_applicable"},
        "compensation_policy": {
            "supported": False,
            "reason": "append-only checkpoint facts",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "completion_contract": {
            "version": "book-narrative-checkpoint-completion-v1",
            "required_evidence": ["trace", "audit", "chapter_acceptance"],
        },
    }


__all__ = ["PostgresBookNarrativeCheckpointAuthority"]
