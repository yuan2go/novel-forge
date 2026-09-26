from __future__ import annotations

from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.book_authority.completion import _rows
from novel_forge.modules.book_authority.completion_domain import completion_digest
from novel_forge.modules.book_authority.evidence_commands import (
    execute_book_evidence_command,
)
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .application import BookFollowupAdmission, BookFollowupCommand
from .prose_review import PROSE_REVIEW_DEFINITION, aggregate_reports, freeze_manifest


def load_accepted_sources(
    uow: AuthorityUnitOfWork, book_run_id: str, project_id: str
) -> list[dict[str, Any]]:
    uow.cursor.execute(
        "SELECT acceptance_id,chapter_number,chapter_outcome_asset_version_id FROM authority_book_chapter_acceptance WHERE book_run_id=%s AND project_id=%s AND status='COMMITTED' ORDER BY chapter_number",
        [book_run_id, project_id],
    )
    sources = []
    for acceptance_id, number, outcome_id in uow.cursor.fetchall():
        outcome = uow.repositories.asset_documents.require(
            project_id=project_id, asset_version_id=outcome_id
        )
        draft = uow.repositories.asset_documents.require(
            project_id=project_id,
            asset_version_id=str(
                outcome.content.get("accepted_draft_asset_version_id") or ""
            ),
        )
        if (
            draft.asset_type != "best_draft_candidate"
            or int(draft.content.get("chapter") or 0) != number
            or draft.eligibility != "ELIGIBLE"
            or draft.governance != "CLEAR"
        ):
            raise KernelError(
                "LONGFORM_PROSE_SOURCE_INVALID",
                "accepted outcome must bind its exact eligible manuscript",
            )
        sources.append(
            {
                "acceptance_id": acceptance_id,
                "chapter_number": number,
                "asset_version_id": draft.asset_version_id,
                "asset_hash": draft.content_hash,
                "text": draft.content.get("text"),
            }
        )
    return sources


def load_review_run(
    uow: AuthorityUnitOfWork,
    *,
    run_id: str,
    project_id: str,
    workspace_id: str,
    book_run_id: str,
) -> dict[str, Any]:
    uow.cursor.execute(
        "SELECT * FROM authority_book_prose_review_run WHERE run_id=%s AND project_id=%s AND workspace_id=%s AND book_run_id=%s",
        [run_id, project_id, workspace_id, book_run_id],
    )
    rows = _rows(uow.cursor)
    if not rows:
        raise KernelError(
            "LONGFORM_PROSE_RUN_NOT_FOUND",
            "review run does not belong to the exact Book scope",
        )
    return rows[0]


def review_progress(uow: AuthorityUnitOfWork, run: dict[str, Any]) -> dict[str, Any]:
    uow.cursor.execute(
        "SELECT * FROM authority_book_prose_review_event WHERE run_id=%s ORDER BY event_version",
        [run["run_id"]],
    )
    events = _rows(uow.cursor)
    reports, operations, dispositions = [], [], {}
    paused = False
    for event in events:
        content = event["content"]
        if event["kind"] in {"WINDOW_ADMITTED", "WINDOW_REUSED"}:
            operation_id = content["operation_id"]
            uow.cursor.execute(
                "SELECT status FROM authority_operation WHERE operation_id=%s",
                [operation_id],
            )
            status = uow.cursor.fetchone()[0]
            operations.append({**content, "status": status})
            uow.cursor.execute(
                "SELECT external_effect_id,status,request_hash FROM authority_external_effect WHERE operation_id=%s ORDER BY created_at",
                [operation_id],
            )
            operations[-1]["external_effects"] = _rows(uow.cursor)
            uow.cursor.execute(
                "SELECT reservation_id,external_effect_id,status,estimated_tokens,actual_tokens,reserved_amount,settled_amount,currency,evidence FROM authority_budget_reservation WHERE operation_id=%s ORDER BY created_at",
                [operation_id],
            )
            operations[-1]["budget_receipts"] = _rows(uow.cursor)
            uow.cursor.execute(
                "SELECT version.asset_version_id,asset.asset_type,version.content FROM authority_operation_output_asset output JOIN authority_asset_version version USING(asset_version_id) JOIN authority_asset asset ON asset.asset_id=version.asset_id WHERE output.operation_id=%s AND asset.asset_type IN ('model_call_log','cost_ledger') ORDER BY output.created_at",
                [operation_id],
            )
            operations[-1]["execution_evidence"] = _rows(uow.cursor)
            if status == "SUCCEEDED":
                uow.cursor.execute(
                    "SELECT version.content,version.asset_version_id FROM authority_operation_output_asset output JOIN authority_asset_version version USING(asset_version_id) WHERE output.operation_id=%s AND output.output_key='longform.prose_review.report'",
                    [operation_id],
                )
                report_rows = uow.cursor.fetchall()
                if len(report_rows) != 1:
                    raise KernelError(
                        "LONGFORM_PROSE_RECEIPT_MISSING",
                        "successful review requires exactly one native output",
                    )
                report, asset_version_id = report_rows[0]
                if event["kind"] == "WINDOW_REUSED":
                    original = load_review_run(
                        uow,
                        run_id=content["source_run_id"],
                        project_id=run["project_id"],
                        workspace_id=run["workspace_id"],
                        book_run_id=run["book_run_id"],
                    )
                    old_window = next(
                        item
                        for item in original["manifest"]["windows"]
                        if item["window_id"] == content["window_id"]
                    )
                    new_window = next(
                        item
                        for item in run["manifest"]["windows"]
                        if item["window_id"] == content["window_id"]
                    )
                    from .prose_review import validate_window_report

                    validate_window_report(
                        report, manifest=original["manifest"], window=old_window
                    )
                    if (
                        old_window["spans"] != new_window["spans"]
                        or original["exact_release_sha"] != run["exact_release_sha"]
                    ):
                        raise KernelError(
                            "LONGFORM_PROSE_REUSE_DRIFT",
                            "reused review must retain identical text, policy and implementation",
                        )
                    report = {**report, "manifest_digest": run["manifest_digest"]}
                reports.append(report)
                operations[-1]["report_asset_version_id"] = asset_version_id
        elif event["kind"] == "FINDING_DISPOSITION":
            dispositions[content["lineage_id"]] = {
                **content,
                "event_id": event["event_id"],
            }
        elif event["kind"] in {"PAUSED", "RESUMED"}:
            paused = event["kind"] == "PAUSED"
    result = aggregate_reports(run["manifest"], reports)
    for finding in result["findings"]:
        disposition = dispositions.get(finding["lineage_id"])
        finding["finding_digest"] = completion_digest(finding["members"])
        finding["disposition"] = disposition
        if disposition and disposition["finding_digest"] != completion_digest(
            finding["members"]
        ):
            finding["disposition"] = {**disposition, "status": "STALE_FINDING_EVIDENCE"}
    current = freeze_manifest(
        project_id=run["project_id"],
        workspace_id=run["workspace_id"],
        book_run_id=run["book_run_id"],
        sources=load_accepted_sources(uow, run["book_run_id"], run["project_id"]),
        policy=run["manifest"]["policy"],
    )
    result.update(
        run_id=run["run_id"],
        source_current=current["sources"] == run["manifest"]["sources"],
        paused=paused,
        operations=operations,
        expected_version=len(events),
        manifest=run["manifest"],
        exact_release_sha=run["exact_release_sha"],
    )
    result["review_digest"] = completion_digest(
        {
            "manifest_digest": result["manifest_digest"],
            "reports": reports,
            "dispositions": dispositions,
        }
    )
    return result


class BookProseReviewCoordinator:
    def __init__(self, followup: Any) -> None:
        self.followup = followup
        self.database_url = followup.database_url
        self.application_build_id = followup.application_build_id
        self.commit_sha = followup.commit_sha

    def _command(
        self,
        name: str,
        payload: dict[str, Any],
        principal: Principal,
        handler: Any,
        **metadata: Any,
    ) -> dict[str, Any]:
        return execute_book_evidence_command(
            database_url=self.database_url,
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
            name=name,
            payload=payload,
            principal=principal,
            handler=handler,
            **metadata,
        )

    def start(
        self,
        *,
        project_id: str,
        workspace_id: str,
        book_run_id: str,
        policy: dict[str, Any],
        principal: Principal,
        evidence_ranges: list[dict[str, Any]] | None = None,
        **metadata: Any,
    ) -> dict[str, Any]:
        scope = dict(
            project_id=project_id, workspace_id=workspace_id, book_run_id=book_run_id
        )

        def handler(
            uow: AuthorityUnitOfWork, operation_id: str, checkpoint: Any
        ) -> dict[str, Any]:
            sources = load_accepted_sources(uow, book_run_id, project_id)
            manifest = freeze_manifest(**scope, sources=sources, policy=policy)
            if evidence_ranges:
                self._append_evidence_window(manifest, sources, evidence_ranges)
            uow.cursor.execute(
                "SELECT run_id FROM authority_book_prose_review_run WHERE book_run_id=%s AND manifest_digest=%s AND exact_release_sha=%s",
                [book_run_id, manifest["manifest_digest"], self.commit_sha],
            )
            existing = uow.cursor.fetchone()
            if existing:
                return {
                    "run_id": existing[0],
                    "manifest_digest": manifest["manifest_digest"],
                    "reused": True,
                }
            run_id = str(uuid4())
            for window in manifest["windows"]:
                content = {
                    "schema_version": "longform-prose-window.v1",
                    **scope,
                    "manifest_digest": manifest["manifest_digest"],
                    "window": window,
                    "policy": policy,
                    "source_isolation": "ACCEPTED_PROSE_ONLY",
                }
                document = uow.repositories.asset_documents.materialize_output(
                    AuthorityAssetWriteCommand(
                        operation_id=operation_id,
                        project_id=project_id,
                        asset_id=str(uuid4()),
                        asset_type="longform_prose_review_window",
                        schema_version="longform-prose-window.v1",
                        logical_ref=f"longform_prose/{run_id}/{window['window_id'][7:]}.json",
                        category="longform_prose_review",
                        output_key="longform.prose_review.window",
                        role="source_window",
                        content=content,
                        qualification_policy="accepted-prose-window.v1",
                        trace_id=metadata["trace_id"],
                        correlation_id=metadata["correlation_id"],
                    )
                )
                window["input_asset"] = {
                    "asset_version_id": document.asset_version_id,
                    "content_hash": document.content_hash,
                }
            uow.cursor.execute(
                "INSERT INTO authority_book_prose_review_run(run_id,project_id,workspace_id,book_run_id,manifest_digest,manifest,exact_release_sha,created_by_operation_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                [
                    run_id,
                    project_id,
                    workspace_id,
                    book_run_id,
                    manifest["manifest_digest"],
                    Jsonb(manifest),
                    self.commit_sha,
                    operation_id,
                ],
            )
            self._reuse_windows(uow, run_id, manifest, operation_id)
            return {
                "run_id": run_id,
                "manifest_digest": manifest["manifest_digest"],
                "reused": False,
                "total_windows": len(manifest["windows"]),
            }

        return self._command(
            "book.prose_review.start",
            {**scope, "policy": policy, "evidence_ranges": evidence_ranges or []},
            principal,
            handler,
            **metadata,
        )

    def report(
        self,
        *,
        run_id: str,
        project_id: str,
        workspace_id: str,
        book_run_id: str,
        principal: Principal,
    ) -> dict[str, Any]:
        principal.require("book.authority.query", project_id)
        with AuthorityUnitOfWork(self.database_url) as uow:
            progress = review_progress(
                uow,
                load_review_run(
                    uow,
                    run_id=run_id,
                    project_id=project_id,
                    workspace_id=workspace_id,
                    book_run_id=book_run_id,
                ),
            )
            return {
                **progress,
                "implementation_current": progress["exact_release_sha"]
                == self.commit_sha,
            }

    def automatic_candidates(
        self, *, principal: Principal, limit: int
    ) -> list[dict[str, Any]]:
        if type(limit) is not int or limit <= 0:
            raise ValueError("automatic review limit must be positive")
        projects = (
            [] if "*" in principal.project_scope else sorted(principal.project_scope)
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """SELECT run.run_id,run.project_id,run.workspace_id,run.book_run_id
                   FROM authority_book_prose_review_run run
                   WHERE run.exact_release_sha=%s AND run.manifest #>> '{policy,execution_mode}'='AUTOMATIC'
                     AND (%s OR run.project_id=ANY(%s))
                     AND NOT EXISTS (SELECT 1 FROM authority_book_prose_review_run newer
                         WHERE newer.book_run_id=run.book_run_id
                         AND (newer.created_at,newer.run_id)>(run.created_at,run.run_id))
                     AND COALESCE((SELECT event.kind FROM authority_book_prose_review_event event
                         WHERE event.run_id=run.run_id AND event.kind IN ('PAUSED','RESUMED')
                         ORDER BY event.event_version DESC LIMIT 1),'RESUMED')<>'PAUSED'
                     AND NOT EXISTS (SELECT 1 FROM authority_book_prose_review_event event
                         JOIN authority_operation operation ON operation.operation_id=event.content->>'operation_id'
                         WHERE event.run_id=run.run_id AND event.kind IN ('WINDOW_ADMITTED','WINDOW_REUSED')
                           AND (operation.status IN ('FAILED_FINAL','DEAD_LETTER','CANCELLED','WAITING_APPROVAL','RECONCILIATION_REQUIRED','WAITING_EXTERNAL_RESULT')
                             OR EXISTS (SELECT 1 FROM authority_external_effect effect WHERE effect.operation_id=operation.operation_id
                                 AND effect.status IN ('UNKNOWN','RECONCILIATION_REQUIRED','CANCEL_REQUESTED'))
                             OR EXISTS (SELECT 1 FROM authority_budget_reservation reservation WHERE reservation.operation_id=operation.operation_id
                                 AND reservation.status='HELD_UNKNOWN')
                             OR EXISTS (SELECT 1 FROM authority_attempt attempt JOIN authority_lease_acquisition lease USING(attempt_id)
                                 WHERE attempt.operation_id=operation.operation_id AND lease.status='HELD' AND lease.expires_at>NOW())))
                     AND ((SELECT COUNT(*) FROM authority_book_prose_review_event event
                             WHERE event.run_id=run.run_id AND event.kind='WINDOW_ADMITTED') < (run.manifest #>> '{policy,maximum_windows}')::integer
                         OR EXISTS (SELECT 1 FROM authority_book_prose_review_event event
                             JOIN authority_operation operation ON operation.operation_id=event.content->>'operation_id'
                             WHERE event.run_id=run.run_id AND event.kind='WINDOW_ADMITTED' AND operation.status<>'SUCCEEDED')
                         OR (run.manifest #>> '{policy,follow_acceptance}'='true' AND EXISTS (
                             SELECT 1 FROM authority_book_chapter_acceptance acceptance WHERE acceptance.book_run_id=run.book_run_id
                             AND acceptance.status='COMMITTED' AND NOT EXISTS (
                                 SELECT 1 FROM jsonb_array_elements(run.manifest->'sources') source WHERE source->>'acceptance_id'=acceptance.acceptance_id))))
                     AND (EXISTS (SELECT 1 FROM jsonb_array_elements(run.manifest->'windows') candidate_window
                         WHERE NOT EXISTS (SELECT 1 FROM authority_book_prose_review_event event
                             JOIN authority_operation operation ON operation.operation_id=event.content->>'operation_id'
                             WHERE event.run_id=run.run_id AND event.kind IN ('WINDOW_ADMITTED','WINDOW_REUSED')
                             AND event.content->>'window_id'=candidate_window->>'window_id' AND operation.status='SUCCEEDED'))
                         OR (run.manifest #>> '{policy,follow_acceptance}'='true'
                             AND EXISTS (SELECT 1 FROM authority_book_chapter_acceptance acceptance
                                 WHERE acceptance.book_run_id=run.book_run_id AND acceptance.status='COMMITTED'
                                 AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(run.manifest->'sources') source
                                     WHERE source->>'acceptance_id'=acceptance.acceptance_id))))
                   ORDER BY run.created_at,run.run_id LIMIT %s""",
                [self.commit_sha, "*" in principal.project_scope, projects, limit],
            )
            return _rows(uow.cursor)

    def blocked_dispatch_operations(
        self, *, project_ids: tuple[str, ...] = ()
    ) -> tuple[str, ...]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """SELECT operation.operation_id FROM authority_operation operation
                   WHERE operation.definition_name=%s
                     AND (%s::text[]='{}'::text[] OR operation.project_id=ANY(%s))
                     AND operation.status IN ('READY','FAILED_RETRYABLE','EXECUTING')
                     AND NOT EXISTS (
                         SELECT 1 FROM authority_book_prose_review_event admission
                         WHERE admission.kind='WINDOW_ADMITTED'
                           AND admission.content->>'operation_id'=operation.operation_id
                           AND COALESCE((SELECT control.kind FROM authority_book_prose_review_event control
                               WHERE control.run_id=admission.run_id AND control.kind IN ('PAUSED','RESUMED')
                               ORDER BY control.event_version DESC LIMIT 1),'RESUMED')<>'PAUSED')""",
                [PROSE_REVIEW_DEFINITION, list(project_ids), list(project_ids)],
            )
            return tuple(row[0] for row in uow.cursor.fetchall())

    def automatic_tick(self, *, principal: Principal, **scope: Any) -> dict[str, Any]:
        principal.require("book.authority.execute", scope["project_id"])
        progress = self.report(**scope, principal=principal)
        policy = progress["manifest"]["policy"]
        if progress["paused"] or policy.get("execution_mode") != "AUTOMATIC":
            return {"status": "PAUSED", "run_id": scope["run_id"]}
        if not progress["implementation_current"]:
            return {"status": "STALE_IMPLEMENTATION", "run_id": scope["run_id"]}
        blocked = [
            item
            for item in progress["operations"]
            if item["status"]
            in {
                "FAILED_FINAL",
                "DEAD_LETTER",
                "CANCELLED",
                "WAITING_APPROVAL",
                "RECONCILIATION_REQUIRED",
                "WAITING_EXTERNAL_RESULT",
            }
            or any(
                effect["status"]
                in {"UNKNOWN", "RECONCILIATION_REQUIRED", "CANCEL_REQUESTED"}
                for effect in item.get("external_effects", [])
            )
            or any(
                receipt["status"] == "HELD_UNKNOWN"
                for receipt in item.get("budget_receipts", [])
            )
        ]
        if blocked:
            return {"status": "BLOCKED", "operation_id": blocked[0]["operation_id"]}
        outstanding = next(
            (item for item in progress["operations"] if item["status"] != "SUCCEEDED"),
            None,
        )
        if outstanding:
            self.followup.run_or_recover(
                BookFollowupAdmission(
                    outstanding["operation_id"], scope["project_id"], True
                )
            )
            return self.report(**scope, principal=principal)
        if not progress["source_current"]:
            if not policy.get("follow_acceptance"):
                return {"status": "STALE_MANUSCRIPT", "run_id": scope["run_id"]}
            with AuthorityUnitOfWork(self.database_url) as uow:
                sources = load_accepted_sources(
                    uow, scope["book_run_id"], scope["project_id"]
                )
            current = freeze_manifest(
                **{
                    key: scope[key]
                    for key in ("project_id", "workspace_id", "book_run_id")
                },
                sources=sources,
                policy=policy,
            )
            previous = progress["manifest"]["sources"]
            if current["sources"][: len(previous)] != previous:
                return {"status": "HISTORICAL_SOURCE_DRIFT", "run_id": scope["run_id"]}
            return self.start(
                **{
                    key: scope[key]
                    for key in ("project_id", "workspace_id", "book_run_id")
                },
                principal=principal,
                policy=policy,
                idempotency_key="prose-auto-manifest:" + current["manifest_digest"],
                trace_id="prose-auto:" + scope["run_id"],
                correlation_id=scope["run_id"],
            )
        if progress["review_complete"]:
            return {"status": "COMPLETE", "run_id": scope["run_id"]}
        if (
            sum(not item.get("source_run_id") for item in progress["operations"])
            >= policy["maximum_windows"]
        ):
            return {"status": "BUDGET_PAUSED", "run_id": scope["run_id"]}
        return self.advance(
            **scope,
            principal=principal,
            expected_version=progress["expected_version"],
            idempotency_key=f"prose-auto:{scope['run_id']}:{progress['expected_version']}",
            trace_id="prose-auto:" + scope["run_id"],
            correlation_id=scope["run_id"],
        )

    def advance(
        self,
        *,
        run_id: str,
        project_id: str,
        workspace_id: str,
        book_run_id: str,
        expected_version: int,
        principal: Principal,
        **metadata: Any,
    ) -> dict[str, Any]:
        scope = dict(
            run_id=run_id,
            project_id=project_id,
            workspace_id=workspace_id,
            book_run_id=book_run_id,
        )
        principal.require("book.authority.execute", project_id)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                "SELECT command_payload,status FROM authority_operation WHERE project_id=%s AND idempotency_scope='project:book.prose_review.advance' AND idempotency_key=%s",
                [project_id, metadata["idempotency_key"]],
            )
            previous = uow.cursor.fetchone()
            if previous:
                if previous[0] != {**scope, "expected_version": expected_version}:
                    raise KernelError(
                        "LONGFORM_PROSE_IDEMPOTENCY_CONFLICT",
                        "an advancement key cannot identify changed inputs",
                    )
                if previous[1] == "SUCCEEDED":
                    return self.report(**scope, principal=principal)
        progress = self.report(**scope, principal=principal)
        if progress["expected_version"] != expected_version:
            raise KernelError(
                "LONGFORM_PROSE_VERSION_CONFLICT",
                "reload review progress before advancing",
            )
        if (
            not progress["source_current"]
            or progress["exact_release_sha"] != self.commit_sha
        ):
            raise KernelError(
                "LONGFORM_PROSE_SOURCE_STALE",
                "freeze a new run for changed manuscript or implementation",
            )
        if progress["paused"]:
            raise KernelError(
                "LONGFORM_PROSE_PAUSED",
                "explicitly resume the frozen review before advancing",
            )
        outstanding = next(
            (item for item in progress["operations"] if item["status"] != "SUCCEEDED"),
            None,
        )
        if outstanding:
            self.followup.run_or_recover(
                BookFollowupAdmission(outstanding["operation_id"], project_id, True)
            )
            return self.report(**scope, principal=principal)
        done = set(progress["completed_window_ids"])
        window = next(
            (
                item
                for item in progress["manifest"]["windows"]
                if item["window_id"] not in done
            ),
            None,
        )
        if window is None:
            return {"status": "COMPLETE", "run_id": run_id}
        if (
            sum(not item.get("source_run_id") for item in progress["operations"])
            >= progress["manifest"]["policy"]["maximum_windows"]
        ):
            raise KernelError(
                "LONGFORM_PROSE_BUDGET_PAUSED",
                "frozen window allowance exhausted; explicit new policy/run required",
            )
        payload = {
            "book_id": self._book_id(book_run_id, project_id),
            "book_run_id": book_run_id,
            "manifest_digest": progress["manifest_digest"],
            "window_id": window["window_id"],
            "context_token_budget": progress["manifest"]["policy"][
                "context_token_budget"
            ],
        }
        request = BookFollowupCommand(
            definition_name=PROSE_REVIEW_DEFINITION,
            project_id=project_id,
            workspace_id=workspace_id,
            actor_id=principal.principal_id,
            trace_id=metadata["trace_id"],
            correlation_id=metadata["correlation_id"],
            idempotency_key=f"prose-review:{run_id}:{window['window_id']}",
            payload=payload,
            input_assets=(window["input_asset"],),
        )

        def handler(
            uow: AuthorityUnitOfWork, operation_id: str, checkpoint: Any
        ) -> dict[str, Any]:
            run = load_review_run(uow, **scope)
            state = review_progress(uow, run)
            if (
                state["expected_version"] != expected_version
                or not state["source_current"]
                or state["paused"]
            ):
                raise KernelError(
                    "LONGFORM_PROSE_VERSION_CONFLICT",
                    "review progress changed before linking admission",
                )
            admission = self.followup.admit(request, principal=principal)
            self._event(
                uow,
                run_id,
                expected_version + 1,
                "WINDOW_ADMITTED",
                {
                    "window_id": window["window_id"],
                    "operation_id": admission.operation_id,
                },
                operation_id,
            )
            return {"operation_id": admission.operation_id, "replayed": False}

        linked = self._command(
            "book.prose_review.advance",
            {**scope, "expected_version": expected_version},
            principal,
            handler,
            **metadata,
        )
        self.followup.run_or_recover(
            BookFollowupAdmission(
                linked["operation_id"], project_id, linked["replayed"]
            )
        )
        return self.report(**scope, principal=principal)

    def _book_id(self, book_run_id: str, project_id: str) -> str:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                "SELECT book_id FROM authority_book_production WHERE book_run_id=%s AND project_id=%s",
                [book_run_id, project_id],
            )
            return str(uow.cursor.fetchone()[0])

    @staticmethod
    def _event(
        uow: AuthorityUnitOfWork,
        run_id: str,
        version: int,
        kind: str,
        content: dict[str, Any],
        operation_id: str,
    ) -> str:
        event_id = str(uuid4())
        uow.cursor.execute(
            "INSERT INTO authority_book_prose_review_event(event_id,run_id,event_version,kind,content,created_by_operation_id) VALUES (%s,%s,%s,%s,%s,%s)",
            [event_id, run_id, version, kind, Jsonb(content), operation_id],
        )
        return event_id

    def disposition(
        self,
        *,
        run_id: str,
        project_id: str,
        workspace_id: str,
        book_run_id: str,
        expected_version: int,
        lineage_id: str,
        finding_digest: str,
        decision: str,
        rationale: str,
        consumer_asset_version_id: str,
        principal: Principal,
        **metadata: Any,
    ) -> dict[str, Any]:
        from novel_forge.modules.book_authority.editorial_domain import (
            require_editorial_principal,
        )

        require_editorial_principal(principal, project_id)
        scope = dict(
            run_id=run_id,
            project_id=project_id,
            workspace_id=workspace_id,
            book_run_id=book_run_id,
        )
        payload = {
            **scope,
            "expected_version": expected_version,
            "lineage_id": lineage_id,
            "finding_digest": finding_digest,
            "decision": decision,
            "rationale": rationale,
            "consumer_asset_version_id": consumer_asset_version_id,
        }

        def handler(
            uow: AuthorityUnitOfWork, operation_id: str, checkpoint: Any
        ) -> dict[str, Any]:
            progress = review_progress(uow, load_review_run(uow, **scope))
            if (
                progress["expected_version"] != expected_version
                or not progress["source_current"]
                or progress["exact_release_sha"] != self.commit_sha
            ):
                raise KernelError(
                    "LONGFORM_PROSE_VERSION_CONFLICT",
                    "exact current progress is required",
                )
            finding = next(
                (
                    item
                    for item in progress["findings"]
                    if item["lineage_id"] == lineage_id
                ),
                None,
            )
            if not finding or completion_digest(finding["members"]) != finding_digest:
                raise KernelError(
                    "LONGFORM_PROSE_FINDING_STALE",
                    "disposition must bind exact finding evidence",
                )
            if (
                decision
                not in {
                    "KEEP_HISTORY",
                    "MINOR_EXCEPTION",
                    "DISMISSED_WITH_EVIDENCE",
                    "FUTURE_PLAN_PROPOSAL",
                    "CURRENT_CANDIDATE_REVISION",
                }
                or not rationale.strip()
            ):
                raise KernelError(
                    "LONGFORM_PROSE_DISPOSITION_INVALID",
                    "explicit decision and rationale are required",
                )
            from novel_forge.modules.book_authority.editorial import load_editorial_events
            from novel_forge.modules.book_authority.editorial_domain import validate_finding_disposition
            policy_events = [event for event in load_editorial_events(uow, book_run_id) if event["kind"] == "POLICY"]
            counter_reports = []
            if decision == "DISMISSED_WITH_EVIDENCE":
                counter_operation = next((item for item in progress["operations"]
                    if item.get("report_asset_version_id") == consumer_asset_version_id
                    and item["status"] == "SUCCEEDED"), None)
                if counter_operation is None:
                    raise KernelError("BOOK_EDITORIAL_COUNTEREVIDENCE_REQUIRED", "dismissal requires an exact successful report from the current manuscript review")
                counter = uow.repositories.asset_documents.require(project_id=project_id, asset_version_id=consumer_asset_version_id)
                counter_reports.append(counter.content)
            resolution = validate_finding_disposition(finding=finding, decision=decision,
                policy_event=policy_events[-1] if policy_events else None,
                actor_id=principal.principal_id, counter_reports=counter_reports)
            if decision in {"FUTURE_PLAN_PROPOSAL", "CURRENT_CANDIDATE_REVISION"}:
                consumer = uow.repositories.asset_documents.require(
                    project_id=project_id, asset_version_id=consumer_asset_version_id
                )
                expected_type = (
                    "plan_change_proposal"
                    if decision == "FUTURE_PLAN_PROPOSAL"
                    else "author_edit_candidate"
                )
                if consumer.asset_type != expected_type or consumer.content.get(
                    "book_id"
                ) != self._book_id(book_run_id, project_id):
                    raise KernelError(
                        "LONGFORM_PROSE_CONSUMER_INVALID",
                        "finding action must reference a native consumer in the same Book",
                    )
                if decision == "FUTURE_PLAN_PROPOSAL":
                    report_ids = {
                        item.get("report_asset_version_id")
                        for item in progress["operations"]
                        if item["window_id"]
                        in {member["window_id"] for member in finding["members"]}
                    }
                    if not report_ids.intersection(
                        consumer.content.get("source_asset_versions", [])
                    ):
                        raise KernelError(
                            "LONGFORM_PROSE_CONSUMER_INVALID",
                            "plan proposal must consume this finding's native review report",
                        )
                if decision == "CURRENT_CANDIDATE_REVISION" and (
                    consumer.content.get("source_review_run_id") != run_id
                    or consumer.content.get("source_lineage_id") != lineage_id
                    or consumer.content.get("source_finding_digest") != finding_digest
                    or consumer.content.get("source_manifest_digest") != progress["manifest_digest"]
                ):
                    raise KernelError(
                        "LONGFORM_PROSE_CONSUMER_INVALID",
                        "author candidate must bind this exact finding lineage",
                    )
            content = {
                key: payload[key]
                for key in (
                    "lineage_id",
                    "finding_digest",
                    "decision",
                    "rationale",
                    "consumer_asset_version_id",
                )
            }
            if decision == "FUTURE_PLAN_PROPOSAL":
                from novel_forge.modules.plan_change_authority.semantic_impact import (
                    exact_plan_dependency_closure,
                    semantic_impact_projection,
                )

                book_id = self._book_id(book_run_id, project_id)
                content["semantic_impact"] = semantic_impact_projection(
                    target_asset_version_id=consumer.content["target_asset_version_id"],
                    proposed_asset_version_id=consumer.content[
                        "proposed_asset_version_id"
                    ],
                    changes=consumer.content["semantic_diff"],
                    finding=finding,
                    exact_dependencies=exact_plan_dependency_closure(
                        uow.cursor,
                        project_id=project_id,
                        book_id=book_id,
                        target_asset_version_id=consumer.content[
                            "target_asset_version_id"
                        ],
                    ),
                    accepted_sources=progress["manifest"]["sources"],
                    uncovered_ranges=progress["uncovered_ranges"],
                    confirmation_rationale=rationale,
                )
            content.update(resolution_evidence=resolution, manifest_digest=progress["manifest_digest"],
                           review_digest=progress["review_digest"])
            content["status"] = "DISPOSITION_RECORDED"
            return {
                "event_id": self._event(
                    uow,
                    run_id,
                    expected_version + 1,
                    "FINDING_DISPOSITION",
                    content,
                    operation_id,
                ),
                **content,
            }

        return self._command(
            "book.prose_review.disposition", payload, principal, handler, **metadata
        )

    def _reuse_windows(
        self,
        uow: AuthorityUnitOfWork,
        run_id: str,
        manifest: dict[str, Any],
        operation_id: str,
    ) -> None:
        uow.cursor.execute(
            "SELECT * FROM authority_book_prose_review_run WHERE book_run_id=%s AND exact_release_sha=%s AND run_id<>%s ORDER BY created_at DESC",
            [manifest["book_run_id"], self.commit_sha, run_id],
        )
        previous = _rows(uow.cursor)
        reused: set[str] = set()
        windows = {item["window_id"]: item for item in manifest["windows"]}
        for old in previous:
            if old["manifest"]["policy"] != manifest["policy"]:
                continue
            uow.cursor.execute(
                "SELECT event.content FROM authority_book_prose_review_event event JOIN authority_operation op ON op.operation_id=event.content->>'operation_id' WHERE event.run_id=%s AND event.kind='WINDOW_ADMITTED' AND op.status='SUCCEEDED' ORDER BY event.event_version",
                [old["run_id"]],
            )
            for (content,) in uow.cursor.fetchall():
                window_id = content["window_id"]
                if window_id not in windows or window_id in reused:
                    continue
                old_window = next(
                    item
                    for item in old["manifest"]["windows"]
                    if item["window_id"] == window_id
                )
                if old_window["spans"] != windows[window_id]["spans"]:
                    continue
                self._event(
                    uow,
                    run_id,
                    len(reused) + 1,
                    "WINDOW_REUSED",
                    {
                        **content,
                        "source_run_id": old["run_id"],
                        "source_manifest_digest": old["manifest_digest"],
                        "reuse_basis": "IDENTICAL_WINDOW_POLICY_AND_IMPLEMENTATION",
                    },
                    operation_id,
                )
                reused.add(window_id)

    def control(
        self,
        *,
        run_id: str,
        project_id: str,
        workspace_id: str,
        book_run_id: str,
        expected_version: int,
        paused: bool,
        reason: str,
        principal: Principal,
        **metadata: Any,
    ) -> dict[str, Any]:
        scope = dict(
            run_id=run_id,
            project_id=project_id,
            workspace_id=workspace_id,
            book_run_id=book_run_id,
        )
        if type(paused) is not bool or not reason.strip():
            raise KernelError(
                "LONGFORM_PROSE_CONTROL_INVALID",
                "explicit pause/resume and reason required",
            )

        def handler(
            uow: AuthorityUnitOfWork, operation_id: str, checkpoint: Any
        ) -> dict[str, Any]:
            state = review_progress(uow, load_review_run(uow, **scope))
            if state["expected_version"] != expected_version:
                raise KernelError(
                    "LONGFORM_PROSE_VERSION_CONFLICT", "review progress changed"
                )
            if not paused and (
                not state["source_current"]
                or state["exact_release_sha"] != self.commit_sha
            ):
                policy = state["manifest"]["policy"]
                current = freeze_manifest(
                    project_id=project_id,
                    workspace_id=workspace_id,
                    book_run_id=book_run_id,
                    sources=load_accepted_sources(uow, book_run_id, project_id),
                    policy=policy,
                )
                previous = state["manifest"]["sources"]
                if not (
                    policy.get("execution_mode") == "AUTOMATIC"
                    and policy.get("follow_acceptance")
                    and state["exact_release_sha"] == self.commit_sha
                    and current["sources"][: len(previous)] == previous
                ):
                    raise KernelError(
                        "LONGFORM_PROSE_SOURCE_STALE",
                        "freeze a new run before resuming changed manuscript or implementation",
                    )
            event_id = self._event(
                uow,
                run_id,
                expected_version + 1,
                "PAUSED" if paused else "RESUMED",
                {"reason": reason},
                operation_id,
            )
            return {
                "event_id": event_id,
                "paused": paused,
                "expected_version": expected_version + 1,
            }

        return self._command(
            "book.prose_review.control",
            {
                **scope,
                "expected_version": expected_version,
                "paused": paused,
                "reason": reason,
            },
            principal,
            handler,
            **metadata,
        )

    def propose_plan_change(
        self,
        *,
        plan_change: Any,
        run_id: str,
        project_id: str,
        workspace_id: str,
        book_run_id: str,
        expected_version: int,
        lineage_id: str,
        finding_digest: str,
        target_asset_version_id: str,
        proposed_asset_version_id: str,
        rationale: str,
        principal: Principal,
        **metadata: Any,
    ) -> dict[str, Any]:
        from novel_forge.modules.book_authority.editorial_domain import (
            require_editorial_principal,
        )

        require_editorial_principal(principal, project_id)
        from novel_forge.modules.plan_change_authority import (
            PlanChangeProposalCommand,
            PlanChangeSource,
        )

        scope = dict(
            run_id=run_id,
            project_id=project_id,
            workspace_id=workspace_id,
            book_run_id=book_run_id,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                "SELECT command_payload FROM authority_operation WHERE project_id=%s AND idempotency_scope='project:book.prose_review.disposition' AND idempotency_key=%s AND status='SUCCEEDED'",
                [project_id, metadata["idempotency_key"]],
            )
            previous = uow.cursor.fetchone()
            if previous:
                consumer_id = previous[0].get("consumer_asset_version_id")
                if previous[0] != {
                    **scope,
                    "expected_version": expected_version,
                    "lineage_id": lineage_id,
                    "finding_digest": finding_digest,
                    "decision": "FUTURE_PLAN_PROPOSAL",
                    "rationale": rationale,
                    "consumer_asset_version_id": consumer_id,
                }:
                    raise KernelError(
                        "LONGFORM_PROSE_IDEMPOTENCY_CONFLICT",
                        "a proposal confirmation key cannot identify changed inputs",
                    )
                consumer = uow.repositories.asset_documents.require(
                    project_id=project_id, asset_version_id=consumer_id
                )
                if (
                    consumer.content.get("target_asset_version_id")
                    != target_asset_version_id
                    or consumer.content.get("proposed_asset_version_id")
                    != proposed_asset_version_id
                ):
                    raise KernelError(
                        "LONGFORM_PROSE_IDEMPOTENCY_CONFLICT",
                        "a proposal confirmation key cannot identify changed targets",
                    )
                uow.cursor.execute(
                    "SELECT proposal.proposal_id FROM authority_plan_change_proposal proposal JOIN authority_operation_output_asset output ON output.operation_id=proposal.proposal_operation_id WHERE output.asset_version_id=%s AND proposal.project_id=%s",
                    [consumer_id, project_id],
                )
                proposal_id = str(uow.cursor.fetchone()[0])
        if previous:
            replay = self.disposition(
                **scope,
                expected_version=expected_version,
                lineage_id=lineage_id,
                finding_digest=finding_digest,
                decision="FUTURE_PLAN_PROPOSAL",
                rationale=rationale,
                consumer_asset_version_id=consumer_id,
                principal=principal,
                **metadata,
            )
            return {
                "proposal": plan_change.require(proposal_id),
                "disposition": replay,
                "semantic_impact": replay["semantic_impact"],
                "hard_dependency_created": False,
                "plan_activation_performed": False,
            }
        progress = self.report(**scope, principal=principal)
        finding = next(
            (item for item in progress["findings"] if item["lineage_id"] == lineage_id),
            None,
        )
        if (
            not finding
            or completion_digest(finding["members"]) != finding_digest
            or progress["expected_version"] != expected_version
            or not progress["source_current"]
            or progress["exact_release_sha"] != self.commit_sha
        ):
            raise KernelError(
                "LONGFORM_PROSE_FINDING_STALE",
                "confirm exact current evidence before proposing a future change",
            )
        if not rationale.strip():
            raise KernelError(
                "LONGFORM_PROSE_CONFIRMATION_REQUIRED",
                "human confirmation rationale is required",
            )
        report = next(
            item
            for item in progress["operations"]
            if item["window_id"] == finding["members"][0]["window_id"]
        )
        proposal = plan_change.propose(
            PlanChangeProposalCommand(
                project_id=project_id,
                workspace_id=workspace_id,
                book_id=self._book_id(book_run_id, project_id),
                actor_id=principal.principal_id,
                trace_id=metadata["trace_id"],
                correlation_id=metadata["correlation_id"],
                stable_idempotency_key=f"prose-plan:{run_id}:{lineage_id}:{finding_digest}:{target_asset_version_id}:{proposed_asset_version_id}",
                source_type=PlanChangeSource.QUALITY_ISSUE,
                source_evidence_version_id=report["report_asset_version_id"],
                target_asset_version_id=target_asset_version_id,
                proposed_asset_version_id=proposed_asset_version_id,
            ),
            principal=principal,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                "SELECT asset_version_id FROM authority_operation_output_asset WHERE operation_id=%s AND output_key='plan_change.proposal'",
                [proposal["proposal_operation_id"]],
            )
            consumer_id = str(uow.cursor.fetchone()[0])
        disposition = self.disposition(
            **scope,
            expected_version=expected_version,
            lineage_id=lineage_id,
            finding_digest=finding_digest,
            decision="FUTURE_PLAN_PROPOSAL",
            rationale=rationale,
            consumer_asset_version_id=consumer_id,
            principal=principal,
            **metadata,
        )
        return {
            "proposal": proposal,
            "disposition": disposition,
            "semantic_impact": disposition["semantic_impact"],
            "hard_dependency_created": False,
            "plan_activation_performed": False,
        }

    @staticmethod
    def _append_evidence_window(
        manifest: dict[str, Any],
        sources: list[dict[str, Any]],
        evidence_ranges: list[dict[str, Any]],
    ) -> None:
        if not 2 <= len(evidence_ranges) <= 8:
            raise KernelError(
                "LONGFORM_PROSE_RETRIEVAL_BOUNDS",
                "cross-window verification requires two to eight explicit ranges",
            )
        spans = []
        for reference in evidence_ranges:
            if set(reference) != {"asset_version_id", "start", "end"}:
                raise KernelError(
                    "LONGFORM_PROSE_RETRIEVAL_INVALID",
                    "retrieval requires exact accepted asset and codepoint range",
                )
            source = next(
                (
                    item
                    for item in sources
                    if item["asset_version_id"] == reference["asset_version_id"]
                ),
                None,
            )
            start, end = reference["start"], reference["end"]
            if (
                source is None
                or type(start) is not int
                or type(end) is not int
                or not 0 <= start < end <= len(source["text"])
            ):
                raise KernelError(
                    "LONGFORM_PROSE_RETRIEVAL_INVALID",
                    "retrieval is outside the accepted manifest",
                )
            record = next(
                item
                for item in manifest["sources"]
                if item["asset_version_id"] == source["asset_version_id"]
            )
            spans.append(
                {
                    **record,
                    "start": start,
                    "end": end,
                    "text": source["text"][start:end],
                }
            )
        if (
            sum(len(span["text"]) for span in spans)
            > manifest["policy"]["window_codepoints"]
        ):
            raise KernelError(
                "LONGFORM_PROSE_RETRIEVAL_BOUNDS",
                "selected evidence exceeds the frozen bounded window",
            )
        window = {
            "window_id": completion_digest(
                {"spans": spans, "policy": manifest["policy"]}
            ),
            "spans": spans,
        }
        if not any(
            item["window_id"] == window["window_id"] for item in manifest["windows"]
        ):
            manifest["windows"].append(window)
        manifest["manifest_digest"] = completion_digest(
            {key: value for key, value in manifest.items() if key != "manifest_digest"}
        )

    def impact_preview(
        self,
        *,
        plan_change: Any,
        run_id: str,
        project_id: str,
        workspace_id: str,
        book_run_id: str,
        expected_version: int,
        lineage_id: str,
        finding_digest: str,
        target_asset_version_id: str,
        proposed_asset_version_id: str,
        rationale: str,
        principal: Principal,
        **metadata: Any,
    ) -> dict[str, Any]:
        from dataclasses import asdict
        from novel_forge.modules.plan_change_authority.domain import semantic_plan_diff
        from novel_forge.modules.plan_change_authority.semantic_impact import (
            exact_plan_dependency_closure,
            semantic_impact_projection,
        )

        scope = dict(
            run_id=run_id,
            project_id=project_id,
            workspace_id=workspace_id,
            book_run_id=book_run_id,
        )
        progress = self.report(**scope, principal=principal)
        finding = next(
            (item for item in progress["findings"] if item["lineage_id"] == lineage_id),
            None,
        )
        if (
            not finding
            or completion_digest(finding["members"]) != finding_digest
            or progress["expected_version"] != expected_version
            or not progress["source_current"]
            or progress["exact_release_sha"] != self.commit_sha
        ):
            raise KernelError(
                "LONGFORM_PROSE_FINDING_STALE",
                "impact preview requires exact current finding evidence",
            )
        book_id = self._book_id(book_run_id, project_id)
        target = plan_change._target_binding(
            project_id, book_id, target_asset_version_id
        )
        proposed = plan_change._proposed_design(project_id, proposed_asset_version_id)
        if (
            proposed["logical_key"] != target["logical_key"]
            or proposed["planning_scope"] != target["contract_type"]
        ):
            raise KernelError(
                "PLAN_CHANGE_CANDIDATE_SCOPE_MISMATCH",
                "proposed plan must target the same exact logical scope",
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            projection = semantic_impact_projection(
                target_asset_version_id=target_asset_version_id,
                proposed_asset_version_id=proposed_asset_version_id,
                changes=[
                    asdict(item)
                    for item in semantic_plan_diff(
                        target["content"], proposed["content"]
                    )
                ],
                finding=finding,
                exact_dependencies=exact_plan_dependency_closure(
                    uow.cursor,
                    project_id=project_id,
                    book_id=book_id,
                    target_asset_version_id=target_asset_version_id,
                ),
                accepted_sources=progress["manifest"]["sources"],
                uncovered_ranges=progress["uncovered_ranges"],
                confirmation_rationale=rationale,
            )
        return {
            "semantic_impact": projection,
            "finding_digest": finding_digest,
            "review_digest": progress["review_digest"],
            "proposal_created": False,
        }
