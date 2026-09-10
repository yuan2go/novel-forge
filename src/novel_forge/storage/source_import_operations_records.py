from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


class SourceImportOperationsRecords:
    cursor: Any

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
            (SELECT count(*) FROM authority_attempt a WHERE a.operation_id=o.operation_id)
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
                    ),
                    r,
                    strict=True,
                )
            )
            for r in rows[:limit]
        ]
        ids = [r["operation_id"] for r in result]
        self.cursor.execute(
            """WITH refs AS (
                SELECT o.operation_id,o.output_key,o.asset_version_id FROM authority_operation_output_asset o WHERE o.operation_id=ANY(%s)
                UNION SELECT w.operation_id,'source.result.'||r.key,r.value FROM authority_source_import_work w
                CROSS JOIN LATERAL jsonb_each_text(w.result) r WHERE w.operation_id=ANY(%s)
                AND r.key IN ('profile_asset_version_id','source_content_profile_asset_version_id','analysis_plan_asset_version_id','candidate_asset_version_id','observation_asset_version_id','execution_asset_version_id')
            ) SELECT r.operation_id,r.output_key,r.asset_version_id,v.content_hash,v.lifecycle,v.eligibility,v.governance
            FROM refs r JOIN authority_asset_version v USING(asset_version_id) JOIN authority_asset a USING(asset_id)
            WHERE a.project_id=%s ORDER BY r.operation_id,r.output_key LIMIT 2001""", [ids, ids, project])
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
        return {
            "reservations": rows,
            "effects": dict(self.cursor.fetchall()),
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

    def analysis_member_counts(self, project: str, job: str) -> dict[str, list[dict[str, Any]]]:
        self.cursor.execute("""WITH RECURSIVE chain AS (
            SELECT w.operation_id AS target,o.parent_operation_id,o.command_payload,0 AS depth FROM authority_source_import_work w
            JOIN authority_operation o USING(operation_id,project_id) WHERE w.project_id=%s AND w.import_job_id=%s
            UNION ALL SELECT c.target,p.parent_operation_id,p.command_payload,c.depth+1 FROM chain c
            JOIN authority_operation p ON p.operation_id=c.parent_operation_id AND p.project_id=%s
            WHERE c.depth<20 AND NOT(c.command_payload->'payload' ? 'member_processing_id')
        ), binding AS (SELECT target,max(command_payload->'payload'->>'member_processing_id') AS processing_id FROM chain GROUP BY target)
        SELECT b.processing_id,w.work_kind,w.status,o.status,count(*) FROM binding b JOIN authority_source_import_work w ON w.operation_id=b.target
        JOIN authority_operation o USING(operation_id,project_id) WHERE b.processing_id IS NOT NULL GROUP BY 1,2,3,4 ORDER BY 1,2,3,4""", [project, job, project])
        result = {}
        for row in self.cursor.fetchall():
            result.setdefault(row[0], []).append(dict(zip(("kind", "work_status", "operation_status", "count"), row[1:], strict=True)))
        return result

    def job_active_leases(self, project: str, job: str) -> int:
        self.cursor.execute("""SELECT count(DISTINCT w.operation_id) FROM authority_source_import_work w
            JOIN authority_attempt a USING(operation_id) JOIN authority_lease_acquisition l USING(attempt_id)
            WHERE w.project_id=%s AND w.import_job_id=%s AND l.status='HELD' AND l.expires_at>NOW()""", [project, job])
        return self.cursor.fetchone()[0]
