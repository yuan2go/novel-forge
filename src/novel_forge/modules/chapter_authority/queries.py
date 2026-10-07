from __future__ import annotations

from dataclasses import asdict
from typing import Any

from novel_forge.modules.chapter_outcome.acceptance_contract import resolve_accepted_manuscript
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


class ChapterAuthorityQuery:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url

    def require_provider_sample(self, *, project_id: str, operation_id: str) -> dict[str, Any]:
        from novel_forge.modules.command_kernel.routing_bootstrap import (
            CHAPTER_BOOTSTRAP_TASKS, CHAPTER_SAMPLE_READABLE_VERSIONS, chapter_sample_definition_name,
            chapter_sample_definition_supported,
        )

        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """SELECT operation_id,status,definition_name,definition_version,command_payload->'payload',
                          trace_id,correlation_id,causation_operation_id
                   FROM authority_operation WHERE project_id=%s AND operation_id=%s
                     AND definition_name=ANY(%s) AND definition_version=ANY(%s)""",
                [project_id, operation_id, [chapter_sample_definition_name(stage) for stage in CHAPTER_BOOTSTRAP_TASKS.values()],
                 list(CHAPTER_SAMPLE_READABLE_VERSIONS)],
            )
            row = uow.cursor.fetchone()
            if row is None or not chapter_sample_definition_supported(row[2], row[3], reference_samples=(row[4].get("chapter_sampling") or {}).get("generation_sample") is not None):
                raise KernelError("CHAPTER_SAMPLE_NOT_FOUND", "Chapter sample is absent from the authorized project")
            result = dict(zip(("operation_id", "status", "definition_name", "definition_version", "input_snapshot",
                               "trace_id", "correlation_id", "causation_operation_id"), row, strict=True))
            uow.cursor.execute(
                """SELECT o.asset_version_id,o.content_hash,o.output_key,o.role,a.asset_type,v.eligibility,
                          CASE WHEN a.asset_type='chapter_provider_sample' THEN v.content ELSE NULL END
                   FROM authority_operation_output_asset o JOIN authority_asset_version v USING(asset_version_id)
                   JOIN authority_asset a ON a.asset_id=v.asset_id WHERE o.operation_id=%s ORDER BY o.created_at,o.output_key""",
                [operation_id],
            )
            result["outputs"] = [dict(zip(("asset_version_id", "content_hash", "output_key", "role", "asset_type", "eligibility", "sample"), row, strict=True)) for row in uow.cursor.fetchall()]
            uow.cursor.execute(
                "SELECT attempt_id,attempt_number,status,result FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number", [operation_id],
            )
            result["attempts"] = [dict(zip(("attempt_id", "attempt_number", "status", "result"), row, strict=True)) for row in uow.cursor.fetchall()]
            uow.cursor.execute(
                "SELECT external_effect_id,status,capability FROM authority_external_effect WHERE operation_id=%s ORDER BY created_at", [operation_id],
            )
            result["effects"] = [dict(zip(("external_effect_id", "status", "capability"), row, strict=True)) for row in uow.cursor.fetchall()]
        return {**result, "production_eligible": False}

    def list_runs(self, *, project_id: str, limit: int = 100, book_run_id: str = "") -> list[dict[str, Any]]:
        if not project_id:
            raise ValueError("project_id is required for chapter run queries")
        if limit < 1 or limit > 500:
            raise ValueError("chapter run query limit must be between 1 and 500")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT root.operation_id, root.status, root.version, root.workspace_id,
                       root.trace_id, root.correlation_id, root.command_payload,
                       root.created_at, root.updated_at, saga.saga_id, saga.status,
                       COUNT(child.operation_id) FILTER (
                           WHERE child.operation_id <> root.operation_id
                       ) AS child_count,
                       COUNT(child.operation_id) FILTER (
                           WHERE child.operation_id <> root.operation_id
                             AND child.status = 'SUCCEEDED'
                       ) AS succeeded_child_count
                FROM authority_operation AS root
                LEFT JOIN authority_saga AS saga
                  ON saga.root_operation_id = root.operation_id
                LEFT JOIN authority_operation AS child
                  ON child.root_operation_id = root.operation_id
                WHERE root.project_id = %s
                  AND root.definition_name = 'chapter.slice.run'
                  AND root.operation_id = root.root_operation_id
                  AND (%s = '' OR EXISTS (
                      SELECT 1 FROM authority_book_chapter_request request
                      WHERE request.chapter_root_operation_id=root.operation_id AND request.book_run_id=%s
                  ))
                GROUP BY root.operation_id, saga.saga_id, saga.status
                ORDER BY root.created_at DESC, root.operation_id
                LIMIT %s
                """,
                [project_id, book_run_id, book_run_id, limit],
            )
            rows = uow.cursor.fetchall()
        return [
            {
                "root_operation_id": row[0],
                "project_id": project_id,
                "status": row[1],
                "version": int(row[2]),
                "workspace_id": row[3],
                "trace_id": row[4],
                "correlation_id": row[5],
                "chapter": int((row[6] or {}).get("chapter") or 0),
                "title": str((row[6] or {}).get("title") or ""),
                "created_at": str(row[7]),
                "updated_at": str(row[8]),
                "saga_id": row[9] or "",
                "saga_status": row[10] or "",
                "child_count": int(row[11]),
                "succeeded_child_count": int(row[12]),
            }
            for row in rows
        ]

    def require_run(
        self,
        *,
        project_id: str,
        root_operation_id: str,
    ) -> dict[str, Any]:
        if not project_id or not root_operation_id:
            raise ValueError("project_id and root_operation_id are required")
        with AuthorityUnitOfWork(self.database_url) as uow:
            cursor = uow.cursor
            cursor.execute(
                """
                SELECT operation_id, status, version, workspace_id, trace_id,
                       correlation_id, command_payload, created_at, updated_at
                FROM authority_operation
                WHERE operation_id = %s AND root_operation_id = %s
                  AND project_id = %s AND definition_name = 'chapter.slice.run'
                """,
                [root_operation_id, root_operation_id, project_id],
            )
            root = cursor.fetchone()
            if root is None:
                raise KernelError(
                    "CHAPTER_RUN_NOT_FOUND", "authoritative chapter run does not exist"
                )
            cursor.execute(
                """
                SELECT operation_id, definition_name, definition_version, status,
                       version, parent_operation_id, step_key, created_at, updated_at
                FROM authority_operation
                WHERE root_operation_id = %s AND project_id = %s
                ORDER BY created_at, operation_id
                """,
                [root_operation_id, project_id],
            )
            operations = [
                {
                    "operation_id": row[0],
                    "definition_name": row[1],
                    "definition_version": row[2],
                    "status": row[3],
                    "version": int(row[4]),
                    "parent_operation_id": row[5] or "",
                    "step_key": row[6] or "",
                    "created_at": str(row[7]),
                    "updated_at": str(row[8]),
                }
                for row in cursor.fetchall()
            ]
            operation_ids = [row["operation_id"] for row in operations]
            cursor.execute(
                """
                SELECT binding.operation_id, binding.output_key, binding.role,
                       binding.asset_id, binding.asset_version_id, binding.content_hash,
                       asset.asset_type, version.lifecycle, version.eligibility,
                       version.governance
                FROM authority_operation_output_asset AS binding
                JOIN authority_asset AS asset ON asset.asset_id = binding.asset_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id = binding.asset_version_id
                WHERE binding.operation_id = ANY(%s) AND binding.role = 'primary'
                ORDER BY binding.created_at, binding.operation_id
                """,
                [operation_ids],
            )
            primary_outputs = [
                {
                    "operation_id": row[0],
                    "output_key": row[1],
                    "role": row[2],
                    "asset_id": row[3],
                    "asset_version_id": row[4],
                    "content_hash": row[5],
                    "asset_type": row[6],
                    "lifecycle": row[7],
                    "eligibility": row[8],
                    "governance": row[9],
                }
                for row in cursor.fetchall()
            ]
            cursor.execute(
                """
                SELECT effect.external_effect_id, effect.operation_id,
                       effect.capability, effect.provider, effect.status,
                       effect.completion_policy, effect.stable_idempotency_key,
                       effect.created_at,
                       effect.request_payload #>>
                           '{_production_execution,attempt_id}' AS attempt_id,
                       attempt.status AS attempt_status,
                       COALESCE((succ.contract_version='kernel-failed-step-successor.v1'
                         AND ((succ.policy_evidence->>'contract_version'='chapter-candidate-contract-repair.v1' AND source.status='CANCELLED'
                             AND attempt.result->>'error_code'='REALIZATION_EPISTEMIC_SCOPE_VIOLATION')
                           OR (succ.policy_evidence->>'contract_version'='chapter-review-output-repair.v1' AND source.status='FAILED_FINAL'
                             AND source.definition_name='chapter.review.evaluate' AND replacement.definition_version='3.9.3'
                             AND attempt.result->>'error_code' IN ('REVIEW_KNOWLEDGE_CHECK_INVALID','REVIEW_KNOWLEDGE_CHECK_REQUIRED'))
                           OR (succ.policy_evidence->>'contract_version'='chapter-length-output-repair.v1' AND source.status='CANCELLED'
                             AND source.definition_name='chapter.revision.apply' AND replacement.definition_version='3.9.4'
                             AND attempt.result->>'error_code'='REVISION_OUTSIDE_DIAGNOSIS_SCOPE')
                           OR (succ.policy_evidence->>'contract_version'='chapter-support-contract-repair.v1' AND source.status='CANCELLED'
                             AND source.definition_name='chapter.canon.propose_changes' AND source.definition_version='3.9.0' AND replacement.definition_version='3.9.8'
                             AND attempt.result->>'error_code'='CANON_GROUNDING_REEXTRACTION_REQUIRED')
                           OR (succ.policy_evidence->>'contract_version'='chapter-quality-contract-repair.v1' AND source.status='DEAD_LETTER'
                             AND source.definition_name LIKE 'chapter.quality.%%' AND source.definition_version='3.9.0' AND replacement.definition_version='3.9.9'
                             AND attempt.result->>'error_code'='QUALITY_APPLICABILITY_CONFLICT'))
                         AND replacement.status='SUCCEEDED'
                         AND active.operation_id IS NOT NULL AND effect.status='SUCCEEDED' AND budget.status='SETTLED'
                         AND (succ.policy_evidence #>> '{source_failure,attempt_id}'=attempt.attempt_id OR (
                           succ.policy_evidence->>'contract_version'='chapter-quality-contract-repair.v1'
                           AND EXISTS(SELECT 1 FROM jsonb_array_elements(succ.source_failure_snapshot->'attempts') recorded
                               WHERE recorded->>'attempt_id'=attempt.attempt_id AND recorded->>'status'='FAILED_RETRYABLE'
                               AND recorded #>> '{result,error_code}'='QUALITY_APPLICABILITY_CONFLICT')))
                         AND EXISTS(SELECT 1 FROM jsonb_array_elements(succ.policy_evidence->'settled_candidate_effects') binding
                             WHERE binding->>0=effect.external_effect_id AND binding->>1=effect.request_hash ) OR (succ.contract_version='kernel-failed-step-successor.v1'
                         AND succ.policy_evidence->>'contract_version'='chapter-provider-schema-contract-repair.v1'
                         AND source.status='FAILED_FINAL' AND source.definition_name='chapter.canon.extract' AND source.definition_version IN ('3.9.5','3.9.6')
                         AND replacement.definition_version IN ('3.9.6','3.9.7')
                         AND (replacement.status='SUCCEEDED' OR (replacement.status='FAILED_FINAL' AND replacement.definition_version='3.9.6'
                           AND next_succ.contract_version='kernel-failed-step-successor.v1'
                           AND next_succ.policy_evidence->>'contract_version'='chapter-provider-schema-contract-repair.v1'
                           AND next_replacement.status='SUCCEEDED' AND next_replacement.definition_version='3.9.7'))
                         AND active.operation_id IS NOT NULL
                         AND effect.status IN ('FAILED_FINAL','FAILED_RETRYABLE') AND budget.status='SETTLED' AND budget.accounting_basis='ACCOUNT_ENTITLEMENT'
                         AND EXISTS(SELECT 1 FROM jsonb_array_elements(succ.policy_evidence->'known_failed_effects') binding
                             WHERE binding->>0=effect.external_effect_id AND binding->>1=effect.request_hash
                               AND binding->>2=effect.status AND binding->>3='SETTLED' AND binding->>4='ACCOUNT_ENTITLEMENT'
                               AND binding->>5=budget.evidence->>'cost_authorization_ref'))),FALSE),
                       COALESCE(next_succ.successor_operation_id,succ.successor_operation_id)
                FROM authority_external_effect AS effect
                LEFT JOIN authority_attempt AS attempt
                  ON attempt.operation_id=effect.operation_id
                 AND attempt.attempt_id=(
                     effect.request_payload #>>
                         '{_production_execution,attempt_id}'
                 )
                LEFT JOIN authority_saga_step_successor succ ON succ.predecessor_operation_id=effect.operation_id
                LEFT JOIN authority_operation source ON source.operation_id=succ.predecessor_operation_id
                  AND source.project_id=succ.project_id AND source.saga_id=succ.saga_id
                  AND source.actor_id=succ.actor_id
                LEFT JOIN authority_operation replacement ON replacement.operation_id=succ.successor_operation_id
                  AND replacement.project_id=source.project_id AND replacement.workspace_id=source.workspace_id
                  AND replacement.root_operation_id=source.root_operation_id AND replacement.saga_id=succ.saga_id
                  AND replacement.step_key=source.step_key AND replacement.actor_id=source.actor_id
                  AND replacement.definition_name=source.definition_name
                LEFT JOIN authority_saga_step_successor next_succ ON next_succ.predecessor_operation_id=succ.successor_operation_id
                  AND next_succ.saga_id=succ.saga_id AND next_succ.contract_version='kernel-failed-step-successor.v1'
                  AND next_succ.policy_evidence->>'contract_version'='chapter-provider-schema-contract-repair.v1'
                LEFT JOIN authority_operation next_replacement ON next_replacement.operation_id=next_succ.successor_operation_id
                  AND next_succ.project_id=succ.project_id AND next_succ.actor_id=succ.actor_id
                  AND next_replacement.project_id=source.project_id AND next_replacement.workspace_id=source.workspace_id
                  AND next_replacement.root_operation_id=source.root_operation_id AND next_replacement.saga_id=succ.saga_id
                  AND next_replacement.step_key=source.step_key AND next_replacement.actor_id=source.actor_id
                  AND next_replacement.definition_name=source.definition_name
                LEFT JOIN authority_saga_step active ON active.operation_id=COALESCE(next_succ.successor_operation_id,succ.successor_operation_id) AND active.saga_id=succ.saga_id
                LEFT JOIN authority_budget_reservation budget ON budget.external_effect_id=effect.external_effect_id
                WHERE effect.operation_id = ANY(%s)
                  AND effect.effect_type = 'model.invoke'
                ORDER BY effect.created_at, effect.external_effect_id
                """,
                [operation_ids],
            )
            model_effects = [
                {
                    "external_effect_id": row[0],
                    "operation_id": row[1],
                    "capability": row[2],
                    "provider": row[3],
                    "status": row[4],
                    "completion_policy": row[5],
                    "stable_idempotency_key": row[6],
                    "created_at": str(row[7]),
                    "attempt_id": row[8] or "",
                    "attempt_status": row[9] or "",
                    "settled_candidate_superseded": bool(row[10]) and row[4] == "SUCCEEDED",
                    "settled_nonproducing_superseded": bool(row[10]) and row[4] in {"FAILED_FINAL", "FAILED_RETRYABLE"},
                    "successor_operation_id": row[11] or "",
                }
                for row in cursor.fetchall()
            ]
            from novel_forge.modules.command_kernel.derived_step_revalidation import acknowledge_revalidated_effects
            acknowledge_revalidated_effects(cursor, model_effects, operation_ids)
            from novel_forge.modules.command_kernel.settled_successor_evidence import acknowledge_successor_effects
            acknowledge_successor_effects(cursor, model_effects, operation_ids)
            cursor.execute(
                """
                SELECT saga_id, status, coordinator_owner,
                       coordinator_fencing_token, created_at, updated_at
                FROM authority_saga
                WHERE root_operation_id = %s AND project_id = %s
                """,
                [root_operation_id, project_id],
            )
            saga = cursor.fetchone()
        return {
            "root_operation_id": root[0],
            "project_id": project_id,
            "status": root[1],
            "version": int(root[2]),
            "workspace_id": root[3],
            "trace_id": root[4],
            "correlation_id": root[5],
            "command": root[6],
            "created_at": str(root[7]),
            "updated_at": str(root[8]),
            "saga": (
                {
                    "saga_id": saga[0],
                    "status": saga[1],
                    "coordinator_owner": saga[2],
                    "coordinator_fencing_token": int(saga[3]),
                    "created_at": str(saga[4]),
                    "updated_at": str(saga[5]),
                }
                if saga is not None
                else {}
            ),
            "operations": operations,
            "primary_outputs": primary_outputs,
            "model_effects": model_effects,
        }

    def require_acceptance_evidence(
        self,
        *,
        project_id: str,
        root_operation_id: str,
    ) -> dict[str, Any]:
        run = self.require_run(
            project_id=project_id,
            root_operation_id=root_operation_id,
        )
        operation_ids = [item["operation_id"] for item in run["operations"]]
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT asset.asset_type, binding.output_key, binding.role,
                       version.asset_version_id, version.content_hash,
                       version.content, version.lifecycle, version.eligibility,
                       version.governance, binding.operation_id
                FROM authority_operation_output_asset AS binding
                JOIN authority_asset AS asset
                  ON asset.asset_id=binding.asset_id
                 AND asset.project_id=%s
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=binding.asset_version_id
                WHERE binding.operation_id = ANY(%s)
                ORDER BY binding.created_at, binding.output_key
                """,
                [project_id, operation_ids],
            )
            outputs = [
                {
                    "asset_type": row[0],
                    "project_id": project_id,
                    "output_key": row[1],
                    "role": row[2],
                    "asset_version_id": row[3],
                    "content_hash": row[4],
                    "content": row[5],
                    "lifecycle": row[6],
                    "eligibility": row[7],
                    "governance": row[8],
                    "operation_id": row[9],
                }
                for row in uow.cursor.fetchall()
            ]
            uow.cursor.execute(
                """
                SELECT reservation_id, status, settled_amount, actual_tokens,
                       provider, evidence
                FROM authority_budget_reservation
                WHERE project_id=%s AND operation_id = ANY(%s)
                ORDER BY created_at, reservation_id
                """,
                [project_id, operation_ids],
            )
            budgets = [
                {
                    "reservation_id": row[0],
                    "status": row[1],
                    "settled_amount": str(row[2]),
                    "actual_tokens": int(row[3]),
                    "provider": row[4],
                    "evidence": row[5],
                }
                for row in uow.cursor.fetchall()
            ]
            uow.cursor.execute(
                """
                SELECT cost_evidence_id
                FROM authority_operation_cost_evidence
                WHERE operation_id = ANY(%s)
                ORDER BY recorded_at, cost_evidence_id
                """,
                [operation_ids],
            )
            cost_receipt_refs = tuple(str(row[0]) for row in uow.cursor.fetchall())
        return {
            **run,
            "outputs": outputs,
            "budgets": budgets,
            "cost_receipt_refs": cost_receipt_refs,
        }

    def require_workspace(self, *, project_id: str, root_operation_id: str) -> dict[str, Any]:
        evidence = self.require_acceptance_evidence(project_id=project_id, root_operation_id=root_operation_id)
        stages = {
            "inputs": {"chapter_plan", "chapter_execution_intent", "context_bundle"},
            "memo": {"chapter_memo"},
            "candidates": {"draft_chapter", "draft_version", "best_draft_candidate"},
            "diagnoses": {"review_report", "re_review_report", "revision_task", "candidate_comparison"},
            "facts": {"canon_extraction", "canon_change_proposal", "canon_approval_decision", "canon_patch"},
            "gates": {"quality_score_report", "publish_gate_report", "final_release_gate_report"},
        }
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT acceptance.acceptance_id, acceptance.status, acceptance.chapter_number,
                       acceptance.chapter_outcome_asset_version_id,
                       acceptance.story_state_asset_version_id, acceptance.canon_snapshot_asset_version_id,
                       acceptance.longform_projection_set_id, request.book_run_id, book_run.book_id
                FROM authority_book_chapter_request request
                JOIN authority_book_production book_run ON book_run.book_run_id=request.book_run_id
                LEFT JOIN authority_book_chapter_acceptance acceptance USING(chapter_request_id)
                WHERE request.chapter_root_operation_id=%s AND request.project_id=%s
                """, [root_operation_id, project_id],
            )
            row = uow.cursor.fetchone()
            outcome = None
            outcome_error = None
            if row and row[0] and row[1] == "COMMITTED":
                try:
                    outcome = asdict(uow.repositories.asset_documents.require(
                        project_id=project_id, asset_version_id=row[3],
                    ))
                except KernelError as error:
                    outcome_error = {"code": error.code, "message": str(error)}
            uow.cursor.execute(
                """
                SELECT attempt.attempt_id, attempt.operation_id, attempt.attempt_number,
                       attempt.status, attempt.worker_id, attempt.error
                FROM authority_attempt attempt JOIN authority_operation operation USING(operation_id)
                WHERE operation.root_operation_id=%s AND operation.project_id=%s
                ORDER BY operation.created_at, attempt.attempt_number
                """, [root_operation_id, project_id],
            )
            attempt_rows = uow.cursor.fetchall()
            source_refs = dict(evidence["command"].get("context_version_refs") or {})
            snapshot_id = str(source_refs.get("book_production_input_snapshot_id") or "")
            creation = {"status": "NOT_BOOK_SCOPED", "input_snapshot_id": snapshot_id}
            if snapshot_id:
                uow.cursor.execute("SELECT book_design_version, foundation_set, snapshot_hash FROM authority_book_production_input_snapshot WHERE project_id=%s AND snapshot_id=%s", [project_id, snapshot_id])
                snapshot = uow.cursor.fetchone()
                if snapshot is None:
                    raise KernelError("CHAPTER_WORKSPACE_SOURCE_MISSING", "Frozen Book input snapshot is missing")
                creation = {"status": "EXACT_FROZEN_INPUT", "input_snapshot_id": snapshot_id, "snapshot_hash": snapshot[2], "book_design_asset_version_id": snapshot[0], "foundation_set": snapshot[1], "policy_versions": {key: value for key, value in source_refs.items() if key in {"style_policy_versions", "quality_rubric_versions", "platform_profile_version"}}}
            attempts = [{"attempt_id": item[0], "operation_id": item[1], "attempt_number": item[2],
                         "status": item[3], "worker_id": item[4], "error": item[5]}
                        for item in attempt_rows]
        workspace = {
            "contract_version": "chapter-workspace.v1",
            "cross_chapter_review_enabled": bool((evidence["command"].get("preparation_report") or {}).get("accepted_prose_snapshot")),
            "cross_chapter_review": [
                {"asset_version_id": item["asset_version_id"],
                 **{key: item["content"][key] for key in ("cross_chapter_window", "cross_chapter_coverage", "issues", "issue_lineage", "resolution_checks", "preservation_checks") if key in item["content"]}}
                for item in evidence["outputs"] if item["content"].get("cross_chapter_window")
            ],
            "attempts": attempts,
            "creation_sources": creation,
            "book_run_id": row[7] if row else "", "authority": "READ_ONLY_PROJECTION",
            "book_id": row[8] if row else "",
            "project_id": project_id, "root_operation_id": root_operation_id,
            "run": {key: value for key, value in evidence.items() if key != "outputs"},
            "artifacts": {stage: [item for item in evidence["outputs"] if item["asset_type"] in types]
                          for stage, types in stages.items()},
            "acceptance": None if row is None or row[0] is None else {
                "acceptance_id": row[0], "status": row[1], "accepted_through_chapter": int(row[2]),
                "outcome_asset_version_id": row[3], "story_state_asset_version_id": row[4],
                "outcome": outcome,
                "canon_snapshot_asset_version_id": row[5], "longform_projection_set_id": row[6],
                "next_input_policy": "ACCEPTED_BOUNDARY_WITH_COMPLETED_PROJECTIONS",
            },
        }
        if workspace["acceptance"] and workspace["acceptance"]["status"] == "COMMITTED":
            try:
                resolved = resolve_accepted_manuscript(workspace)
                workspace["accepted_manuscript"] = {"status": "EXACT_ACCEPTANCE_BOUND", "bindings": {
                    key: {"asset_version_id": value["asset_version_id"], "content_hash": value["content_hash"]}
                    for key, value in resolved.items()
                }}
            except (KernelError, KeyError, TypeError, ValueError) as error:
                workspace["accepted_manuscript"] = {"status": "EVIDENCE_INCOMPLETE_OR_CONFLICTING",
                    "error": outcome_error or {"code": getattr(error, "code", "EXPORT_CONTRACT_INVALID"), "message": str(error)}}
        from novel_forge.modules.mkaos_authority.trace import workspace_knowledge_trace
        try:
            workspace["knowledge_trace"] = workspace_knowledge_trace(workspace)
        except KernelError as error:
            workspace["knowledge_trace"] = {
                "status": "EVIDENCE_INCOMPLETE_OR_CONFLICTING", "code": error.code,
                "message": str(error),
            }
        from novel_forge.modules.review.craft import craft_trace_projection
        try:
            workspace["craft_trace"] = craft_trace_projection(workspace)
        except KernelError as error:
            workspace["craft_trace"] = {
                "status": "EVIDENCE_INCOMPLETE_OR_CONFLICTING", "code": error.code,
                "message": str(error),
            }
        return workspace

    def require_operation_control_state(
        self,
        *,
        project_id: str,
        root_operation_id: str,
    ) -> dict[str, Any]:
        if not project_id or not root_operation_id:
            raise ValueError("project_id and root_operation_id are required")
        with AuthorityUnitOfWork(self.database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(
                root_operation_id,
                project_id,
            )
        return {
            "status": str(state["status"]),
            "version": int(state["version"]),
        }


__all__ = ["ChapterAuthorityQuery"]
