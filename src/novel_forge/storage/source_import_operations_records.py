from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


class SourceImportOperationsRecords:
    cursor: Any

    def reading_input_records(self, project: str, operation: str) -> list[dict]:
        self.cursor.execute(
            """WITH contracts AS (
                SELECT v.asset_version_id,v.content->'contract' AS content
                FROM authority_operation_output_asset a
                JOIN authority_asset_version v USING(asset_version_id)
                JOIN authority_operation o USING(operation_id)
                WHERE o.project_id=%s AND a.operation_id=%s
            ) SELECT e.external_effect_id,e.operation_id,e.status,
                e.request_payload->'_source_intelligence'->'actual_input_manifest',
                d.receipt_id,
                CASE WHEN e.reconciliation<>'{}'::jsonb THEN e.reconciliation ELSE d.evidence END,
                e.request_payload->'_production_execution'->'capability_runtime'->>'provider_admission_asset_version_id',
                EXISTS(SELECT 1 FROM contracts WHERE content->>'input_receipt_reuse'=e.external_effect_id)
            FROM authority_external_effect e
            LEFT JOIN LATERAL (SELECT receipt_id,evidence FROM authority_external_effect_dispatch
                WHERE external_effect_id=e.external_effect_id ORDER BY generation DESC LIMIT 1) d ON true
            WHERE e.project_id=%s AND (e.operation_id=%s OR e.external_effect_id IN (
                SELECT content->>'input_receipt_reuse' FROM contracts))
            ORDER BY e.created_at,e.external_effect_id LIMIT 33""",
            [project, operation, project, operation],
        )
        rows = self.cursor.fetchall()
        if len(rows) > 32:
            raise KernelError(
                "READING_RECEIPT_BOUND",
                "stage has too many effects; inspect effect records",
            )
        result = []
        for row in rows:
            evidence = row[5] or {}
            execution = evidence.get("production_execution", {}).get(
                "execution_result", {}
            )
            refs = {
                k: execution[k]
                for k in (
                    "raw_output_ref",
                    "normalized_output_ref",
                    "usage_receipt_ref",
                    "cost_receipt_ref",
                    "process_receipt_ref",
                )
                if execution.get(k)
            }
            result.append(
                {
                    "effect_id": row[0],
                    "origin_operation_id": row[1],
                    "status": row[2],
                    "external_state_unknown": bool(evidence.get("external_state_unknown")) or (
                        execution.get("outcome") in {"TIMED_OUT", "CANCELLED", "ORPHANED"}
                        and bool(execution.get("started_at"))
                        and not execution.get("usage_receipt_ref")
                        and evidence.get("production_execution", {}).get("execution_handle", {}).get("transport")
                        == "LOCAL_CLI_REMOTE_INFERENCE"
                    ),
                    "manifest": row[3],
                    "receipt_id": row[4],
                    "diagnostic_refs": refs,
                    "admission_asset_version_id": row[6],
                    "reused": bool(row[7]),
                    "returned": row[2] == "SUCCEEDED"
                    or bool(refs.get("normalized_output_ref")),
                }
            )
        if not rows:
            self.cursor.execute(
                """SELECT v.asset_version_id,v.content->'contract'->'actual_input_manifest'
                FROM authority_operation_output_asset a JOIN authority_asset_version v USING(asset_version_id)
                JOIN authority_operation o USING(operation_id)
                WHERE o.project_id=%s AND a.operation_id=%s
                  AND v.content->'contract' ? 'actual_input_manifest'
                ORDER BY v.created_at DESC LIMIT 1""",
                [project, operation],
            )
            if prepared := self.cursor.fetchone():
                result.append(
                    {
                        "admission_asset_version_id": prepared[0],
                        "manifest": prepared[1],
                        "status": "PREPARED",
                    }
                )
        return result

    def reading_stage(self, project: str, job: str, operation: str) -> dict:
        self.cursor.execute(
            """SELECT o.command_payload->'payload',w.result,w.status
            FROM authority_source_import_work w JOIN authority_operation o USING(operation_id,project_id)
            WHERE w.project_id=%s AND w.import_job_id=%s AND w.operation_id=%s""",
            [project, job, operation],
        )
        row = self.cursor.fetchone()
        if not row or not row[0].get("narrative_reading"):
            raise KernelError(
                "READING_STAGE_NOT_FOUND",
                "exact job and bounded reading operation required",
            )
        return {"payload": row[0], "result": row[1], "status": row[2]}

    def reading_metrics(self, project: str, job: str) -> dict:
        self.cursor.execute(
            """SELECT
            count(*) FILTER(WHERE w.result ? 'validation_error'),
            count(*) FILTER(WHERE w.result->'review'->>'decision'='REVISE'),
            count(*) FILTER(WHERE w.status='BLOCKED'),
            count(DISTINCT u.unit_id) FILTER(WHERE w.result->>'semantic_evidence'='AGENT_REVIEW_ONLY')
            FROM authority_source_import_work w
            LEFT JOIN LATERAL jsonb_array_elements_text(COALESCE(w.result->'coverage'->'target_units','[]')) u(unit_id) ON true
            WHERE w.project_id=%s AND w.import_job_id=%s AND w.work_kind='DECONSTRUCTION'
              AND NOT EXISTS (SELECT 1 FROM authority_operation o WHERE o.operation_id=w.operation_id AND o.command_payload->'payload' ? 'source_sampling')""",
            [project, job],
        )
        row = self.cursor.fetchone()
        return dict(
            zip(
                (
                    "mechanical_failures",
                    "revision_requests",
                    "blocked_stages",
                    "reviewed_target_units",
                ),
                row,
                strict=True,
            )
        )

    def reading_progress_rows(self, project: str, job: str) -> list[dict]:
        self.cursor.execute(
            """SELECT o.operation_id,o.status,w.status,
                o.command_payload->'payload'->>'phase',
                o.command_payload->'payload'->>'unit_index',
                o.command_payload->'payload'->'narrative_reading'->>'identity',
                w.result->>'validation_error',w.result->'review'->>'decision',
                w.result->>'semantic_evidence',w.result ? 'observation_asset_version_id',
                w.result->>'phase_status',w.result->'coverage'->>'input_state'
            FROM authority_source_import_work w JOIN authority_operation o USING(operation_id,project_id)
            WHERE w.project_id=%s AND w.import_job_id=%s
              AND o.command_payload->'payload' ? 'narrative_reading'
              AND NOT (o.command_payload->'payload' ? 'source_sampling')
            ORDER BY o.created_at,o.operation_id LIMIT 10001""",
            [project, job],
        )
        rows = self.cursor.fetchall()
        if len(rows) > 10000:
            raise KernelError(
                "READING_PROGRESS_BOUND", "inspect stages in bounded pages"
            )
        keys = (
            "operation_id",
            "operation_status",
            "status",
            "phase",
            "unit_index",
            "reading_identity",
            "validation_error",
            "decision",
            "semantic_evidence",
            "has_observation",
            "phase_status",
            "input_state",
        )
        return [dict(zip(keys, r, strict=True)) for r in rows]

    def missing_reading_expansions(
        self, project: str, job: str, limit: int = 100
    ) -> list[dict]:
        self.cursor.execute(
            """SELECT o.operation_id,w.result->>'analysis_plan_asset_version_id',
                o.command_payload->'payload'->'reading_plan'->>'identity',
                o.command_payload->'payload'->'reading_plan'->>'processing_id'
            FROM authority_source_import_work w JOIN authority_operation o USING(operation_id,project_id)
            WHERE w.project_id=%s AND w.import_job_id=%s AND w.work_kind='ANALYSIS_PLANNING'
              AND w.status IN ('SUCCEEDED','REUSED') AND o.command_payload->'payload' ? 'reading_plan'
              AND NOT EXISTS (SELECT 1 FROM authority_source_import_work c
                JOIN authority_operation child USING(operation_id,project_id)
                WHERE c.project_id=w.project_id AND c.import_job_id=w.import_job_id
                  AND child.parent_operation_id=o.operation_id
                  AND child.command_payload->'payload'->>'phase'='OBSERVE'
                  AND child.command_payload->'payload'->>'unit_index'='0'
                  AND child.command_payload->'payload'->>'repair_round'='0'
                  AND child.command_payload->'payload'->'narrative_reading'->>'identity'
                      =o.command_payload->'payload'->'reading_plan'->>'identity')
            ORDER BY o.operation_id LIMIT %s""",
            [project, job, limit],
        )
        return [
            dict(
                zip(
                    (
                        "planning_operation_id",
                        "analysis_plan_asset_version_id",
                        "reading_identity",
                        "processing_id",
                    ),
                    r,
                    strict=True,
                )
            )
            for r in self.cursor.fetchall()
        ]

    def frozen_operation(self, project: str, operation: str) -> dict[str, Any]:
        self.cursor.execute(
            "SELECT definition_name,definition_version,command_payload->'payload' FROM authority_operation WHERE project_id=%s AND operation_id=%s",
            [project, operation],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "SOURCE_JOB_CONTRACT_MISSING", "frozen operation not found in project"
            )
        return {"name": row[0], "version": row[1], "payload": row[2]}

    def job_execution_counts(self, project: str, job: str) -> list[dict[str, Any]]:
        self.cursor.execute(
            """SELECT w.work_kind,w.status,o.status,count(*) FROM authority_source_import_work w
            JOIN authority_operation o USING(operation_id,project_id) WHERE w.project_id=%s AND w.import_job_id=%s
              AND NOT (o.command_payload->'payload' ? 'source_sampling')
              AND NOT EXISTS (
                  SELECT 1 FROM authority_source_import_work recovered
                  JOIN authority_operation successor ON successor.operation_id=recovered.operation_id
                  JOIN authority_external_effect original_effect
                    ON original_effect.external_effect_id=
                       successor.command_payload#>>'{payload,completion_recovery,original_effect_id}'
                   AND original_effect.operation_id=o.operation_id
                   AND original_effect.status='SUCCEEDED'
                  WHERE recovered.import_job_id=w.import_job_id AND recovered.project_id=w.project_id
                    AND recovered.status IN ('SUCCEEDED','REUSED') AND successor.status='SUCCEEDED'
                    AND recovered.result->>'provider_execution_reused'='true'
                    AND successor.causation_operation_id=o.operation_id
                    AND successor.command_payload#>>'{payload,completion_recovery,source_operation_id}'=o.operation_id
                    AND (successor.command_payload->'payload')-'completion_recovery'=o.command_payload->'payload'
              )
            GROUP BY w.work_kind,w.status,o.status ORDER BY 1,2,3""",
            [project, job],
        )
        return [
            dict(
                zip(
                    ("kind", "work_status", "operation_status", "count"), r, strict=True
                )
            )
            for r in self.cursor.fetchall()
        ]

    def job_ready_operations(
        self, project: str, job: str, limit: int, excluded: tuple[str, ...] = ()
    ) -> tuple[tuple[str, str], ...]:
        self.cursor.execute(
            """SELECT o.operation_id,o.project_id FROM authority_source_import_work w
            JOIN authority_source_import_job j USING(import_job_id,project_id)
            JOIN authority_operation o ON o.operation_id=w.operation_id AND o.project_id=w.project_id
            WHERE w.project_id=%s AND w.import_job_id=%s AND j.status NOT IN ('PAUSED','CANCELLED') AND NOT(o.operation_id=ANY(%s))
            AND o.status IN ('READY','FAILED_RETRYABLE','EXECUTING','WAITING_EXTERNAL_RESULT','RECONCILIATION_REQUIRED')
            AND NOT EXISTS(SELECT 1 FROM authority_attempt a JOIN authority_lease_acquisition l USING(attempt_id)
                WHERE a.operation_id=o.operation_id AND l.status='HELD' AND l.expires_at>NOW())
            ORDER BY o.created_at,o.operation_id LIMIT %s""",
            [project, job, list(excluded), limit],
        )
        return tuple((r[0], r[1]) for r in self.cursor.fetchall())

    def analysis_stage_page(
        self, project: str, job: str, after: str, limit: int, member: str
    ) -> dict[str, Any]:
        self.cursor.execute(
            """WITH RECURSIVE chain AS (
            SELECT w.operation_id AS target,o.operation_id,o.parent_operation_id,o.command_payload,0 AS depth
            FROM authority_source_import_work w JOIN authority_operation o USING(operation_id,project_id)
            WHERE w.project_id=%s AND w.import_job_id=%s AND w.operation_id>%s
            UNION ALL SELECT c.target,p.operation_id,p.parent_operation_id,p.command_payload,c.depth+1
            FROM chain c JOIN authority_operation p ON p.operation_id=c.parent_operation_id AND p.project_id=%s
            WHERE c.depth<20 AND NOT(c.command_payload->'payload' ? 'member_processing_id')
        ), binding AS (
            SELECT target,max(command_payload->'payload'->>'member_processing_id') AS processing_id FROM chain GROUP BY target
        ) SELECT w.operation_id,w.work_kind,w.status,o.status,b.processing_id,
            w.target_asset_version_id,w.failure,w.result->>'stage',
            w.result->>'analysis_plan_asset_version_id',w.result->>'source_content_profile_asset_version_id',
            (SELECT count(*) FROM authority_attempt a WHERE a.operation_id=o.operation_id),
            (SELECT count(*) FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id) WHERE a.operation_id=o.operation_id),
            CASE WHEN o.command_payload->'payload' ? 'narrative_reading' THEN jsonb_build_object(
              'phase',w.result->'phase','phase_status',w.result->'phase_status','repair_round',w.result->'repair_round',
              'coverage',w.result->'coverage','review',w.result->'review','issues',w.result->'issues',
              'observation',w.result->'observation','validation_error',w.result->'validation_error',
              'output_validation',w.result->'output_validation','semantic_review_status',w.result->'semantic_review_status') END,
            o.command_payload#>>'{payload,capability}'
            FROM binding b JOIN authority_source_import_work w ON w.operation_id=b.target
            JOIN authority_operation o USING(operation_id,project_id)
            WHERE (%s='' OR b.processing_id=%s) ORDER BY w.operation_id LIMIT %s""",
            [project, job, after, project, member, member, limit + 1],
        )
        rows = self.cursor.fetchall()
        result = [
            dict(
                zip(
                    (
                        "operation_id",
                        "kind",
                        "status",
                        "operation_status",
                        "processing_id",
                        "target_asset_version_id",
                        "failure",
                        "stage",
                        "analysis_plan_asset_version_id",
                        "source_content_profile_asset_version_id",
                        "attempt_count",
                        "lease_acquisition_count",
                        "narrative",
                        "capability",
                    ),
                    r,
                    strict=True,
                )
            )
            for r in rows[:limit]
        ]
        for row in result:
            narrative = row.get("narrative")
            if narrative:
                from novel_forge.modules.source_import.corpus_ingestion.reading_evidence import (
                    receipt_input_evidence,
                )

                payload = self.reading_stage(project, job, row["operation_id"])[
                    "payload"
                ]
                narrative.update(
                    receipt_input_evidence(
                        self.reading_input_records(project, row["operation_id"]),
                        payload,
                    )
                )
                narrative["phase"] = payload["phase"]
                narrative["repair_round"] = payload["repair_round"]
                observation = narrative.pop("observation", None) or {}
                narrative["finding_count"] = len(observation.get("findings", []))
                narrative["findings_summary"] = [
                    {
                        k: (v[:500] if isinstance(v, str) else v)
                        for k, v in f.items()
                        if k
                        in {
                            "finding_code",
                            "statement",
                            "dimension",
                            "certainty",
                            "perspective",
                            "evidence_span_ids",
                            "input_observation_asset_version_ids",
                        }
                    }
                    for f in observation.get("findings", [])[:6]
                ]
                narrative["findings_summary_truncated"] = narrative["finding_count"] > 6
        ids = [r["operation_id"] for r in result]
        self.cursor.execute(
            """WITH refs AS (
                SELECT o.operation_id,o.output_key,o.asset_version_id FROM authority_operation_output_asset o WHERE o.operation_id=ANY(%s)
                UNION SELECT w.operation_id,'source.result.'||r.key,r.value FROM authority_source_import_work w
                CROSS JOIN LATERAL jsonb_each_text(w.result) r WHERE w.operation_id=ANY(%s)
                AND r.key IN ('profile_asset_version_id','source_content_profile_asset_version_id','analysis_plan_asset_version_id','candidate_asset_version_id','observation_asset_version_id','execution_asset_version_id')
            ) SELECT r.operation_id,r.output_key,r.asset_version_id,v.content_hash,v.lifecycle,v.eligibility,v.governance
            FROM refs r JOIN authority_asset_version v USING(asset_version_id) JOIN authority_asset a USING(asset_id)
            WHERE a.project_id=%s ORDER BY r.operation_id,r.output_key LIMIT 2001""",
            [ids, ids, project],
        )
        assets = self.cursor.fetchall()
        if len(assets) > 2000:
            raise KernelError("SOURCE_RESULT_PAGE_TOO_LARGE", "reduce stage page size")
        self.cursor.execute(
            """SELECT operation_id,external_effect_id,status,provider,model_id,(SELECT d.receipt_id FROM authority_external_effect_dispatch d WHERE d.external_effect_id=authority_external_effect.external_effect_id ORDER BY d.generation DESC LIMIT 1) FROM authority_external_effect
            WHERE project_id=%s AND operation_id=ANY(%s) ORDER BY operation_id,external_effect_id LIMIT 2001""",
            [project, ids],
        )
        effects = self.cursor.fetchall()
        if len(effects) > 2000:
            raise KernelError("SOURCE_RESULT_PAGE_TOO_LARGE", "reduce stage page size")
        for row in result:
            row["outputs"] = [
                dict(
                    zip(
                        (
                            "output_key",
                            "asset_version_id",
                            "content_hash",
                            "lifecycle",
                            "eligibility",
                            "governance",
                        ),
                        a[1:],
                        strict=True,
                    )
                )
                for a in assets
                if a[0] == row["operation_id"]
            ]
            row["effects"] = [
                dict(
                    zip(
                        ("effect_id", "status", "provider", "model_id", "receipt_id"),
                        e[1:],
                        strict=True,
                    )
                )
                for e in effects
                if e[0] == row["operation_id"]
            ]
            row["recovery_attempts"] = max(0, row["attempt_count"] - 1)
            row["fence_reacquisitions"] = max(
                0, row["lease_acquisition_count"] - row["attempt_count"]
            )
        return {
            "stages": result,
            "next_after": result[-1]["operation_id"] if len(rows) > limit else None,
            "limit": limit,
        }

    def analysis_budget(self, project: str, job: str) -> dict[str, Any]:
        self.cursor.execute(
            """SELECT b.status,b.accounting_basis,b.currency,count(*),sum(b.estimated_tokens),sum(b.actual_tokens),sum(b.reserved_amount),sum(b.settled_amount),count(*) FILTER(WHERE b.settled_cost_status<>'KNOWN')
            FROM authority_budget_reservation b JOIN authority_source_import_work w USING(operation_id,project_id)
            WHERE w.project_id=%s AND w.import_job_id=%s GROUP BY b.status,b.accounting_basis,b.currency ORDER BY 1,2,3""",
            [project, job],
        )
        rows = [
            dict(
                zip(
                    (
                        "status",
                        "accounting_basis",
                        "currency",
                        "reservations",
                        "estimated_tokens",
                        "recorded_actual_tokens",
                        "reserved_amount",
                        "recorded_settled_amount",
                        "cost_unknown_count",
                    ),
                    r,
                    strict=True,
                )
            )
            for r in self.cursor.fetchall()
        ]
        self.cursor.execute(
            """SELECT e.status,count(*) FROM authority_external_effect e JOIN authority_source_import_work w USING(operation_id,project_id)
            WHERE w.project_id=%s AND w.import_job_id=%s GROUP BY e.status ORDER BY e.status""",
            [project, job],
        )
        effects = dict(self.cursor.fetchall())
        from novel_forge.modules.command_kernel.budget_runtime import provider_project_usage, unresolved_cli_outcomes

        return {
            "reservations": rows,
            "effects": effects,
            "project_cumulative": provider_project_usage(self.cursor, project),
            "unresolved_cli_outcomes": unresolved_cli_outcomes(self.cursor, project),
            "scope": "JOB_OWNED_EFFECTS_ONLY",
            "hidden_backend_usage": "NOT_OBSERVED",
        }

    def analysis_knowledge_counts(self, project: str, job: str) -> dict[str, int]:
        self.cursor.execute(
            """WITH outputs AS (
            SELECT DISTINCT w.result->>'candidate_asset_version_id' AS asset_version_id FROM authority_source_import_work w WHERE w.project_id=%s AND w.import_job_id=%s AND w.status IN ('SUCCEEDED','REUSED')
        ), candidates AS (SELECT c.asset_version_id,c.status FROM authority_mkaos_knowledge_candidate c JOIN outputs o USING(asset_version_id)),
        cards AS (SELECT c.asset_version_id FROM authority_mkaos_knowledge_card c JOIN candidates k ON k.asset_version_id=c.candidate_asset_version_id WHERE c.project_id=%s)
        SELECT (SELECT count(*) FROM candidates),(SELECT count(*) FROM candidates WHERE status='NEEDS_REVIEW'),
        (SELECT count(*) FROM cards),(SELECT count(DISTINCT p.knowledge_pack_asset_version_id) FROM authority_mkaos_knowledge_pack_item p JOIN cards c ON c.asset_version_id=p.knowledge_card_asset_version_id)""",
            [project, job, project],
        )
        return dict(
            zip(
                (
                    "knowledge_candidates",
                    "review_required",
                    "knowledge_cards",
                    "knowledge_packs",
                ),
                self.cursor.fetchone(),
                strict=True,
            )
        )

    def analysis_member_counts(
        self, project: str, job: str
    ) -> dict[str, list[dict[str, Any]]]:
        self.cursor.execute(
            """WITH RECURSIVE chain AS (
            SELECT w.operation_id AS target,o.parent_operation_id,o.command_payload,0 AS depth FROM authority_source_import_work w
            JOIN authority_operation o USING(operation_id,project_id) WHERE w.project_id=%s AND w.import_job_id=%s
              AND NOT (o.command_payload->'payload' ? 'source_sampling')
            UNION ALL SELECT c.target,p.parent_operation_id,p.command_payload,c.depth+1 FROM chain c
            JOIN authority_operation p ON p.operation_id=c.parent_operation_id AND p.project_id=%s
            WHERE c.depth<20 AND NOT(c.command_payload->'payload' ? 'member_processing_id')
        ), binding AS (SELECT target,max(command_payload->'payload'->>'member_processing_id') AS processing_id FROM chain GROUP BY target)
        SELECT b.processing_id,w.work_kind,w.status,o.status,count(*) FROM binding b JOIN authority_source_import_work w ON w.operation_id=b.target
        JOIN authority_operation o USING(operation_id,project_id) WHERE b.processing_id IS NOT NULL GROUP BY 1,2,3,4 ORDER BY 1,2,3,4""",
            [project, job, project],
        )
        result = {}
        for row in self.cursor.fetchall():
            result.setdefault(row[0], []).append(
                dict(
                    zip(
                        ("kind", "work_status", "operation_status", "count"),
                        row[1:],
                        strict=True,
                    )
                )
            )
        return result

    def job_active_leases(self, project: str, job: str) -> int:
        self.cursor.execute(
            """SELECT count(DISTINCT w.operation_id) FROM authority_source_import_work w
            JOIN authority_attempt a USING(operation_id) JOIN authority_lease_acquisition l USING(attempt_id)
            WHERE w.project_id=%s AND w.import_job_id=%s AND l.status='HELD' AND l.expires_at>NOW()""",
            [project, job],
        )
        return self.cursor.fetchone()[0]
