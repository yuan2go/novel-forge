from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    TransactionCheckpoint,
    execute_transaction_command,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .completion_domain import (
    assess_completion,
    completion_digest,
    completion_result_schema,
    require_completion_review,
    validate_completion_contract,
)


VERSION = "1.1.0"
HUMAN_POLICY_BLOCKER = "WHOLE_BOOK_EDITORIAL_POLICY_REQUIRED"


def book_completion_definitions(
    *, application_build_id: str, commit_sha: str
) -> tuple[dict[str, Any], ...]:
    definitions = []
    for action in ("assess", "decide"):
        name = "book.completion." + action
        properties = {
            key: {"type": "string", "minLength": 1}
            for key in (
                "project_id",
                "workspace_id",
                "book_run_id",
            )
        }
        required = list(properties)
        if action == "decide":
            properties.update(
                {
                    "case_id": {"type": "string", "minLength": 1},
                    "source_digest": {
                        "type": "string",
                        "pattern": "^sha256:[0-9a-f]{64}$",
                    },
                    "expected_case_version": {"type": "integer", "minimum": 1},
                    "expected_decision_version": {"type": "integer", "minimum": 0},
                    "decision": {"type": "string", "enum": ["ACCEPTED", "REJECTED"]},
                    "rationale": {"type": "string", "minLength": 1},
                    "quality_campaign_id": {"type": "string"},
                    "closure_evidence_id": {"type": "string"},
                }
            )
            required = list(properties)
        schema = {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }
        definitions.append(
            {
                "name": name,
                "definition_version": VERSION,
                "family": "book_completion",
                "enabled": True,
                "definition_status": "implemented_validation_pending",
                "command_schema_version": name + ".command.v1",
                "result_schema_version": name + ".result.v1",
                "command_schema": schema,
                "result_schema": completion_result_schema(action),
                "input_contract": schema,
                "output_contract": {
                    "type": "BookCompletionCase"
                    if action == "assess"
                    else "BookCompletionDecision"
                },
                "handler_key": "novel_forge." + name,
                "handler_contract_version": "book-completion-handler.v1",
                "application_build_id": application_build_id,
                "commit_sha": commit_sha,
                "execution_mode": "transactional",
                "permissions": ["book.authority.execute"],
                "approval_policy": {"required": False},
                "policy": {"execution_classification": "transaction_command"},
                "idempotency_scope": "project:book_completion:" + action,
                "concurrency_key_template": "book:{input[book_run_id]}:completion",
                "retry_policy": {"max_attempts": 1},
                "timeout_policy": {"operation_timeout_seconds": 30},
                "cancellation_policy": {"mode": "not_applicable"},
                "compensation_policy": {
                    "supported": False,
                    "reason": "append new completion evidence",
                },
                "irreversible_effect_policy": {"allowed": False},
                "external_capabilities": [],
                "projection_consumers": ["book_completion"],
                "migration_owner": "book_completion",
                "completion_contract": {
                    "version": "book-completion-transaction.v1",
                    "required_evidence": ["trace", "audit"],
                    "required_outbox_events": [name],
                },
            }
        )
    return tuple(definitions)


def _rows(cursor: Any) -> list[dict[str, Any]]:
    fields = [item.name for item in cursor.description]
    return [dict(zip(fields, row, strict=True)) for row in cursor.fetchall()]


def _load_source(
    uow: AuthorityUnitOfWork, *, project_id: str, workspace_id: str, book_run_id: str
) -> dict[str, Any]:
    uow.cursor.execute(
        """
        SELECT book_run_id,project_id,workspace_id,book_id,state,target_chapter_count,
               accepted_through_chapter,active_longform_projection_set_id,
               book_design_version,book_plan_version,longform_context_versions
        FROM authority_book_production
        WHERE book_run_id=%s AND project_id=%s AND workspace_id=%s FOR UPDATE
        """,
        [book_run_id, project_id, workspace_id],
    )
    books = _rows(uow.cursor)
    if not books:
        raise KernelError(
            "BOOK_COMPLETION_BOOK_NOT_FOUND",
            "completion requires the exact Project/Workspace/Book production scope",
        )
    book = books[0]
    arcs = book["longform_context_versions"].get("arc_plan_versions") or []
    book["required_arc_plan_version_ids"] = sorted(set(arcs))
    uow.cursor.execute(
        """
        SELECT accepted.acceptance_id,accepted.chapter_number,
               accepted.status AS acceptance_status,
               accepted.longform_projection_set_id AS acceptance_projection_set_id,
               accepted.chapter_outcome_asset_version_id AS outcome_version_id,
               accepted.story_state_asset_version_id AS story_state_version_id,
               accepted.canon_snapshot_asset_version_id AS canon_version_id,
               projection.projection_set_id,projection.status AS projection_status,
               projection.chapter_outcome_asset_version_id AS projection_outcome_version_id,
               projection.story_state_asset_version_id AS projection_story_state_version_id,
               projection.canon_snapshot_asset_version_id AS projection_canon_version_id,
               projection.projection_hash,projection.arc_state,projection.obligation_state,
               outcome.content_hash AS outcome_hash,story.content_hash AS story_state_hash,
               canon.content_hash AS canon_hash,
               (accepted_operation.status='SUCCEEDED'
                AND outcome.lifecycle IN ('ACTIVE','SUPERSEDED') AND outcome.eligibility='ELIGIBLE' AND outcome.governance='CLEAR'
                AND story.lifecycle IN ('ACTIVE','SUPERSEDED') AND story.eligibility='ELIGIBLE' AND story.governance='CLEAR'
                AND canon.lifecycle IN ('ACTIVE','SUPERSEDED') AND canon.eligibility='ELIGIBLE' AND canon.governance='CLEAR') AS source_eligible
        FROM authority_book_chapter_acceptance AS accepted
        LEFT JOIN authority_book_narrative_projection_set AS projection
          ON projection.projection_set_id=accepted.longform_projection_set_id
         AND projection.acceptance_id=accepted.acceptance_id
         AND projection.project_id=accepted.project_id AND projection.book_run_id=accepted.book_run_id
        JOIN authority_asset_version AS outcome ON outcome.asset_version_id=accepted.chapter_outcome_asset_version_id
        JOIN authority_asset_version AS story ON story.asset_version_id=accepted.story_state_asset_version_id
        LEFT JOIN authority_asset_version AS canon ON canon.asset_version_id=accepted.canon_snapshot_asset_version_id
        JOIN authority_operation AS accepted_operation ON accepted_operation.operation_id=accepted.acceptance_operation_id
        WHERE accepted.project_id=%s AND accepted.book_run_id=%s
        ORDER BY accepted.chapter_number,accepted.acceptance_id
        FOR SHARE OF accepted,outcome,story,accepted_operation
        """,
        [project_id, book_run_id],
    )
    accepted = _rows(uow.cursor)
    for row in accepted:
        outcome = uow.repositories.asset_documents.require(project_id=project_id, asset_version_id=row["outcome_version_id"])
        draft_id = str(outcome.content.get("accepted_draft_asset_version_id") or "")
        if draft_id:
            draft = uow.repositories.asset_documents.require(project_id=project_id, asset_version_id=draft_id)
            from novel_forge.modules.book_followup_authority.prose_review import text_digest
            row["accepted_draft_asset_version_id"] = draft_id
            row["accepted_draft_asset_hash"] = draft.content_hash
            row["accepted_draft_text_hash"] = text_digest(str(draft.content.get("text") or ""))
    return {"book": book, "accepted": accepted}


class PostgresBookCompletionAuthority:
    def __init__(
        self, database_url: str, *, application_build_id: str, commit_sha: str
    ) -> None:
        if (
            not database_url
            or not application_build_id
            or not re.fullmatch(r"[0-9a-f]{40}", commit_sha)
        ):
            raise ValueError(
                "Book Completion requires PostgreSQL and exact implementation identity"
            )
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha

    def assess(
        self,
        *,
        project_id: str,
        workspace_id: str,
        book_run_id: str,
        principal: Principal,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
        fault_injector: TransactionCheckpoint | None = None,
    ) -> dict[str, Any]:
        return self._execute(
            "assess",
            payload={
                "project_id": project_id,
                "workspace_id": workspace_id,
                "book_run_id": book_run_id,
            },
            principal=principal,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            correlation_id=correlation_id,
            fault_injector=fault_injector,
        )

    def decide(
        self,
        *,
        project_id: str,
        workspace_id: str,
        book_run_id: str,
        case_id: str,
        source_digest: str,
        expected_case_version: int,
        expected_decision_version: int,
        decision: str,
        rationale: str,
        principal: Principal,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
        quality_campaign_id: str = "",
        closure_evidence_id: str = "",
        fault_injector: TransactionCheckpoint | None = None,
    ) -> dict[str, Any]:
        return self._execute(
            "decide",
            payload={
                "project_id": project_id,
                "workspace_id": workspace_id,
                "book_run_id": book_run_id,
                "case_id": case_id,
                "source_digest": source_digest,
                "expected_case_version": expected_case_version,
                "expected_decision_version": expected_decision_version,
                "decision": decision,
                "rationale": rationale,
                "quality_campaign_id": quality_campaign_id,
                "closure_evidence_id": closure_evidence_id,
            },
            principal=principal,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            correlation_id=correlation_id,
            fault_injector=fault_injector,
        )

    def _execute(
        self,
        action: str,
        *,
        payload: dict[str, Any],
        principal: Principal,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
        fault_injector: TransactionCheckpoint | None,
    ) -> dict[str, Any]:
        principal.require("book.authority.execute", payload["project_id"])
        definition = next(
            item
            for item in book_completion_definitions(
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            )
            if item["name"].endswith("." + action)
        )
        validate_completion_contract(definition["command_schema"], payload, "input")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.definitions.register(definition)
            uow.commit()

        def handler(
            uow: AuthorityUnitOfWork,
            operation_id: str,
            checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            source = _load_source(
                uow,
                **{
                    key: payload[key]
                    for key in ("project_id", "workspace_id", "book_run_id")
                },
            )
            result = (
                self._assess(uow, source, operation_id)
                if action == "assess"
                else self._decide(uow, source, operation_id, payload)
            )
            validate_completion_contract(definition["result_schema"], result, "result")
            checkpoint("after_completion_evidence")
            uow.repositories.operation_graph.record_event(
                {
                    "event_id": str(uuid4()),
                    "audit_id": str(uuid4()),
                    "outbox_id": str(uuid4()),
                    "aggregate_type": "book_completion",
                    "aggregate_id": payload["book_run_id"],
                    "operation_id": operation_id,
                    "project_id": payload["project_id"],
                    "event_type": definition["name"],
                    "correlation_id": correlation_id,
                    "causation_id": operation_id,
                    "payload": {
                        "operation_id": operation_id,
                        "case_id": result["case_id"],
                        "source_digest": result["source_digest"],
                        "status": result["status"],
                    },
                }
            )
            return result

        return execute_transaction_command(
            self.database_url,
            {
                "definition_name": definition["name"],
                "definition_version": VERSION,
                "project_id": payload["project_id"],
                "workspace_id": payload["workspace_id"],
                "actor_id": principal.principal_id,
                "idempotency_scope": definition["idempotency_scope"],
                "idempotency_key": idempotency_key,
                "trace_id": trace_id,
                "span_id": str(uuid4()),
                "correlation_id": correlation_id,
                "causation_id": "",
                "input": payload,
                "input_assets": [],
            },
            context=AdmissionContext(
                actor_id=principal.principal_id,
                permissions=frozenset({"book.authority.execute"}),
                available_handlers=frozenset({definition["handler_key"]}),
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
            handler=handler,
            fault_injector=fault_injector,
        )

    def _assess(
        self, uow: AuthorityUnitOfWork, source: dict[str, Any], operation_id: str
    ) -> dict[str, Any]:
        book = source["book"]
        assessment = assess_completion(book, source["accepted"]).to_dict()
        case_id = str(uuid4())
        uow.cursor.execute(
            "SELECT COALESCE(MAX(case_version),0)+1 FROM authority_book_completion_case WHERE book_run_id=%s",
            [book["book_run_id"]],
        )
        version = uow.cursor.fetchone()[0]
        uow.cursor.execute(
            """INSERT INTO authority_book_completion_case(
                case_id,project_id,workspace_id,book_id,book_run_id,case_version,exact_release_sha,
                source_digest,accepted_through,status,assessment,source_snapshot,created_by_operation_id
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            [
                case_id,
                book["project_id"],
                book["workspace_id"],
                book["book_id"],
                book["book_run_id"],
                version,
                self.commit_sha,
                assessment["source_digest"],
                assessment["accepted_through"],
                assessment["status"],
                Jsonb(assessment),
                Jsonb(source),
                operation_id,
            ],
        )
        for row in source["accepted"]:
            uow.cursor.execute(
                """INSERT INTO authority_book_completion_source(
                case_id,chapter_number,acceptance_id,projection_set_id,outcome_version_id,story_state_version_id,canon_version_id,source_record
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                [
                    case_id,
                    row["chapter_number"],
                    row["acceptance_id"],
                    row["acceptance_projection_set_id"],
                    row["outcome_version_id"],
                    row["story_state_version_id"],
                    row["canon_version_id"],
                    Jsonb(row),
                ],
            )
        return {
            **assessment,
            "case_id": case_id,
            "case_version": version,
            "book_run_id": book["book_run_id"],
            "current_editorial_policy_status": self._editorial_policy_status(uow, book["book_run_id"]),
        }

    @staticmethod
    def _editorial_policy_status(uow: AuthorityUnitOfWork, book_run_id: str) -> str:
        from .editorial import load_editorial_events
        policies = [event for event in load_editorial_events(uow, book_run_id) if event["kind"] == "POLICY"]
        if not policies:
            return "WAITING_POLICY_APPROVAL"
        return "AWAITING_AUTHORIZED_SIGNATURES" if policies[-1]["content"]["policy"]["enabled"] else "POLICY_INACTIVE"

    def _case(
        self, uow: AuthorityUnitOfWork, case_id: str, book_run_id: str
    ) -> dict[str, Any]:
        uow.cursor.execute(
            "SELECT * FROM authority_book_completion_case WHERE case_id=%s AND book_run_id=%s",
            [case_id, book_run_id],
        )
        cases = _rows(uow.cursor)
        if not cases:
            raise KernelError(
                "BOOK_COMPLETION_CASE_NOT_FOUND",
                "completion case does not belong to this book production",
            )
        case = cases[0]
        frozen = case["source_snapshot"]
        if (
            assess_completion(frozen["book"], frozen["accepted"]).to_dict()
            != case["assessment"]
        ):
            raise KernelError(
                "BOOK_COMPLETION_REPLAY_DRIFT",
                "frozen completion source does not replay to its assessment",
            )
        uow.cursor.execute(
            "SELECT source_record FROM authority_book_completion_source WHERE case_id=%s ORDER BY chapter_number",
            [case_id],
        )
        if [row[0] for row in uow.cursor.fetchall()] != frozen["accepted"]:
            raise KernelError(
                "BOOK_COMPLETION_SOURCE_LINK_DRIFT",
                "typed completion sources differ from frozen accepted history",
            )
        return case

    def _decide(
        self,
        uow: AuthorityUnitOfWork,
        source: dict[str, Any],
        operation_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        case = self._case(uow, payload["case_id"], payload["book_run_id"])
        current = assess_completion(source["book"], source["accepted"]).to_dict()
        if (
            current["source_digest"] != payload["source_digest"]
            or case["source_digest"] != payload["source_digest"]
            or case["case_version"] != payload["expected_case_version"]
        ):
            raise KernelError(
                "BOOK_COMPLETION_SOURCE_STALE",
                "completion decision requires the current exact accepted source and case version",
            )
        uow.cursor.execute(
            "SELECT COALESCE(MAX(decision_version),0) FROM authority_book_completion_decision WHERE book_run_id=%s",
            [payload["book_run_id"]],
        )
        latest = uow.cursor.fetchone()[0]
        if latest != payload["expected_decision_version"]:
            raise KernelError(
                "BOOK_COMPLETION_DECISION_VERSION_CONFLICT",
                "completion decision cursor changed; reload before deciding",
            )
        uow.cursor.execute(
            "SELECT 1 FROM authority_book_completion_decision WHERE case_id=%s",
            [case["case_id"]],
        )
        if uow.cursor.fetchone():
            raise KernelError(
                "BOOK_COMPLETION_CASE_TERMINAL",
                "append a new assessment rather than rewrite terminal completion evidence",
            )
        blockers: list[str] = []
        quality_ids: tuple[str | None, str | None, str | None] = (None, None, None)
        if payload["decision"] == "ACCEPTED":
            blockers = list(current["blockers"])
            if case["exact_release_sha"] != self.commit_sha:
                blockers.append("COMPLETION_IMPLEMENTATION_CHANGED")
            quality_blockers, quality_ids = self._quality_evidence(uow, case, payload)
            blockers.extend(quality_blockers)
            from .editorial import completion_editorial_evidence
            editorial_blockers, _editorial = completion_editorial_evidence(uow, case=case, payload=payload, release_sha=self.commit_sha)
            blockers.extend(editorial_blockers)
        outcome = "REJECTED" if payload["decision"] == "REJECTED" else "BLOCKED" if blockers else "ACCEPTED"
        result = {
            "schema_version": "book-completion-decision.v1",
            "case_id": case["case_id"],
            "book_run_id": payload["book_run_id"],
            "source_digest": case["source_digest"],
            "decision_id": str(uuid4()),
            "decision_version": latest + 1,
            "requested_decision": payload["decision"],
            "status": outcome,
            "rationale": payload["rationale"],
            "blockers": sorted(set(blockers)),
            "evidence_dimensions": {**current["evidence_dimensions"], "HUMAN_EDITORIAL": "BOUNDED_HUMAN_EVIDENCE" if outcome == "ACCEPTED" else "WAITING_EVIDENCE"},
            "accepted_history_mutation_allowed": False,
            "recovery_instruction": "Append a new case after remediation; activate an authorized editorial policy, complete exact prose coverage and obtain its named signatures. Book acceptance does not authorize publication.",
        }
        uow.cursor.execute(
            """INSERT INTO authority_book_completion_decision(
            decision_id,case_id,book_run_id,decision_version,source_digest,requested_decision,outcome,decision,
            quality_campaign_id,quality_decision_id,closure_evidence_id,created_by_operation_id
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            [
                result["decision_id"],
                case["case_id"],
                payload["book_run_id"],
                latest + 1,
                case["source_digest"],
                payload["decision"],
                outcome,
                Jsonb(result),
                *quality_ids,
                operation_id,
            ],
        )
        return result

    def _quality_evidence(
        self, uow: AuthorityUnitOfWork, case: dict[str, Any], payload: dict[str, Any]
    ) -> tuple[list[str], tuple[str | None, str | None, str | None]]:
        campaign_id = payload["quality_campaign_id"]
        if not campaign_id:
            return [
                "WHOLE_BOOK_QUALITY_CAMPAIGN_REQUIRED",
                "WAITING_EXTERNAL_HUMAN_EVIDENCE",
            ], (None, None, None)
        uow.cursor.execute(
            "SELECT * FROM authority_quality_qualification_campaign WHERE campaign_id=%s FOR SHARE",
            [campaign_id],
        )
        campaigns = _rows(uow.cursor)
        if not campaigns or any(
            campaigns[0][key] != case[key]
            for key in ("project_id", "workspace_id", "book_id")
        ):
            raise KernelError(
                "BOOK_COMPLETION_QUALITY_SCOPE_MISMATCH",
                "quality campaign must belong to the exact completion scope",
            )
        campaign = campaigns[0]
        blockers = []
        if (
            campaign["exact_release_sha"] != self.commit_sha
            or campaign["chapter_start"] != 1
            or campaign["chapter_end"] != case["accepted_through"]
        ):
            blockers.append("WHOLE_BOOK_QUALITY_SCOPE_STALE")
        if (
            campaign["lifecycle"] != "COMPLETE"
            or campaign["qualification_status"] != "PASS"
        ):
            blockers.append("WHOLE_BOOK_QUALITY_NOT_PASSED")
        if campaign["human_evidence_status"] != "BOUNDED_HUMAN_EVIDENCE":
            blockers.append("WAITING_EXTERNAL_HUMAN_EVIDENCE")
        uow.cursor.execute(
            "SELECT * FROM authority_quality_qualification_decision WHERE campaign_id=%s ORDER BY decision_version DESC LIMIT 1 FOR SHARE",
            [campaign_id],
        )
        decisions = _rows(uow.cursor)
        decision_id = decisions[0]["decision_id"] if decisions else None
        if not decisions or decisions[0]["qualification_status"] != "PASS":
            blockers.append("WHOLE_BOOK_QUALITY_DECISION_REQUIRED")
        evidence_id = payload["closure_evidence_id"] or None
        if evidence_id:
            uow.cursor.execute(
                """SELECT evidence.*,version.content,version.content_hash
                FROM authority_quality_qualification_evidence AS evidence
                JOIN authority_asset_version AS version ON version.asset_version_id=evidence.evidence_asset_version_id
                WHERE evidence.evidence_id=%s AND evidence.campaign_id=%s FOR SHARE OF evidence,version""",
                [evidence_id, campaign_id],
            )
            evidence_rows = _rows(uow.cursor)
            if not evidence_rows:
                raise KernelError(
                    "BOOK_COMPLETION_CLOSURE_EVIDENCE_NOT_FOUND",
                    "closure evidence must be native Quality evidence from the same campaign",
                )
            evidence = evidence_rows[0]
            if (
                evidence["evidence_type"] != "WHOLE_BOOK_CLOSURE"
                or evidence["evidence_layer"] != "L2_EDITORIAL_QUALITY"
                or evidence["status"] != "PASS"
                or evidence["evidence_content_hash"] != evidence["content_hash"]
                or completion_digest(evidence["content"]) != evidence["content_hash"]
            ):
                raise KernelError(
                    "BOOK_COMPLETION_CLOSURE_EVIDENCE_INVALID",
                    "typed whole-book closure report must bind its exact native evidence content",
                )
            require_completion_review(case["assessment"], evidence["content"])
            if set(evidence["source_asset_version_ids"]) != set(
                case["assessment"]["outcome_version_ids"]
            ):
                raise KernelError(
                    "BOOK_COMPLETION_CLOSURE_SOURCE_MISMATCH",
                    "closure review must include every accepted ChapterOutcome",
                )
        else:
            blockers.append("WHOLE_BOOK_CLOSURE_REVIEW_REQUIRED")
        return blockers, (campaign_id, decision_id, evidence_id)

    def require_case(
        self,
        *,
        project_id: str,
        workspace_id: str,
        book_run_id: str,
        case_id: str,
        principal: Principal,
    ) -> dict[str, Any]:
        principal.require("book.authority.query", project_id)
        with AuthorityUnitOfWork(self.database_url) as uow:
            source = _load_source(
                uow,
                project_id=project_id,
                workspace_id=workspace_id,
                book_run_id=book_run_id,
            )
            case = self._case(uow, case_id, book_run_id)
            current_digest = completion_digest(source)
            uow.cursor.execute(
                "SELECT decision FROM authority_book_completion_decision WHERE case_id=%s",
                [case_id],
            )
            row = uow.cursor.fetchone()
            decision = row[0] if row else None
            editorial_current = None
            if decision and decision["status"] == "ACCEPTED":
                from .editorial import completion_editorial_evidence
                blockers, _status = completion_editorial_evidence(uow, case=case, payload={"book_run_id": book_run_id}, release_sha=self.commit_sha)
                editorial_current = not blockers and current_digest == case["source_digest"]
            return {
                **case["assessment"],
                "case_id": case_id,
                "case_version": case["case_version"],
                "book_run_id": book_run_id,
                "source_current": current_digest == case["source_digest"],
                "decision": decision,
                "editorial_acceptance_current": editorial_current,
                "current_editorial_policy_status": self._editorial_policy_status(uow, book_run_id),
                "public_release_authorized": False,
            }
