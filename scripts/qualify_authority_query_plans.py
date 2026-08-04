#!/usr/bin/env python3
"""Representative-scale PostgreSQL planner qualification for a disposable DB."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import time
from typing import Any
from uuid import uuid4

import psycopg

from novel_forge.storage.migrations import get_migration_status


ROW_COUNTS = {
    "authority_operation": 100_000,
    "outbox_event": 100_000,
    "authority_asset_version": 100_000,
    "authority_book_production": 10_000,
    "authority_legacy_migration_item": 100_000,
}


def _plan_nodes(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        result = [value] if "Node Type" in value else []
        for nested in value.values():
            result.extend(_plan_nodes(nested))
        return result
    if isinstance(value, list):
        result: list[dict[str, Any]] = []
        for nested in value:
            result.extend(_plan_nodes(nested))
        return result
    return []


def _qualify_plan(
    connection: psycopg.Connection[Any], *, name: str, relation: str, query: str
) -> dict[str, Any]:
    plan = connection.execute(
        f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query}"
    ).fetchone()[0][0]
    nodes = _plan_nodes(plan)
    relation_nodes = [node for node in nodes if node.get("Relation Name") == relation]
    index_nodes = [
        node
        for node in relation_nodes
        if node.get("Node Type") in {"Index Scan", "Index Only Scan", "Bitmap Index Scan"}
        or node.get("Index Name")
    ]
    sequential = [node for node in relation_nodes if node.get("Node Type") == "Seq Scan"]
    if not index_nodes or sequential:
        raise RuntimeError(
            f"planner qualification failed for {name}: "
            f"indexes={[node.get('Index Name') for node in index_nodes]} "
            f"sequential={len(sequential)}"
        )
    return {
        "name": name,
        "relation": relation,
        "index_names": sorted(
            {str(node["Index Name"]) for node in index_nodes if node.get("Index Name")}
        ),
        "node_types": sorted({str(node["Node Type"]) for node in nodes}),
        "actual_rows": sum(int(node.get("Actual Rows") or 0) for node in relation_nodes),
        "rows_removed_by_filter": sum(
            int(node.get("Rows Removed by Filter") or 0) for node in relation_nodes
        ),
        "sort_present": any(node.get("Node Type") == "Sort" for node in nodes),
        "planning_time_ms": float(plan.get("Planning Time") or 0),
        "execution_time_ms": float(plan.get("Execution Time") or 0),
        "shared_hit_blocks": sum(int(node.get("Shared Hit Blocks") or 0) for node in nodes),
        "shared_read_blocks": sum(int(node.get("Shared Read Blocks") or 0) for node in nodes),
        "plan": plan,
    }


def qualify(database_url: str) -> dict[str, Any]:
    migration = get_migration_status(database_url)
    if not migration["ok"]:
        raise RuntimeError("release query qualification requires the current migration head")
    token = f"rq-{uuid4().hex[:12]}"
    started = time.monotonic()
    with psycopg.connect(database_url) as connection:
        connection.execute("SET statement_timeout='120s'")
        connection.execute("SET lock_timeout='5s'")
        connection.execute("SET CONSTRAINTS ALL DEFERRED")
        connection.execute(
            """
            INSERT INTO authority_operation_definition(
                name,definition_version,family,enabled,command_schema,result_schema,
                policy,completion_contract
            ) VALUES ('rq.worker.poll','1.0.0','release_qualification',TRUE,
                      '{}'::jsonb,'{}'::jsonb,'{}'::jsonb,'{}'::jsonb)
            ON CONFLICT DO NOTHING
            """
        )
        connection.execute(
            """
            INSERT INTO authority_operation(
                operation_id,definition_name,definition_version,project_id,status,
                root_operation_id,idempotency_scope,idempotency_key,request_digest,
                definition_snapshot,completion_contract_snapshot,policy_snapshot,
                workspace_id,actor_id,concurrency_key,trace_id,span_id,correlation_id,
                created_at,updated_at
            )
            SELECT %(token)s || ':op:' || value,'rq.worker.poll','1.0.0',
                   %(token)s || ':project:' || (value %% 1000),
                   CASE WHEN value %% 100 = 0 THEN 'READY' ELSE 'SUCCEEDED' END,
                   %(token)s || ':op:' || value,%(token)s,
                   'op:' || value,'sha256:' || repeat('a',64),
                   '{}'::jsonb,'{}'::jsonb,'{}'::jsonb,
                   %(token)s || ':workspace','release-qualification',
                   %(token)s || ':concurrency:' || value,%(token)s || ':trace',
                   %(token)s || ':span',%(token)s || ':correlation',
                   NOW() - (value * INTERVAL '1 millisecond'),NOW()
            FROM generate_series(1,100000) AS value
            """,
            {"token": token},
        )
        connection.execute(
            """
            INSERT INTO authority_saga(
                saga_id,root_operation_id,project_id,status,trace_id,correlation_id
            )
            SELECT %(token)s || ':saga:' || value,%(token)s || ':op:' || value,
                   %(token)s || ':project:' || (value %% 1000),'RUNNING',
                   %(token)s || ':trace',%(token)s || ':correlation'
            FROM generate_series(1,10000) AS value
            """,
            {"token": token},
        )
        connection.execute(
            """
            INSERT INTO authority_book_production(
                book_run_id,project_id,workspace_id,book_id,book_design_version,
                book_plan_version,production_profile_version,longform_context_versions,
                root_operation_id,saga_id,stable_idempotency_key,state,
                target_chapter_count,light_recap_cadence,formal_recap_cadence,
                created_at,updated_at
            )
            SELECT %(token)s || ':book-run:' || value,
                   %(token)s || ':project:' || (value %% 1000),
                   %(token)s || ':workspace',%(token)s || ':book:' || value,
                   'design-v1','plan-v1','profile-v1',
                   jsonb_build_object(
                       'volume_plan_version','v1','arc_plan_version','v1',
                       'character_state_version','v1','foreshadowing_state_version','v1',
                       'quality_trend_version','v1','reward_ledger_version','v1',
                       'promise_ledger_version','v1'
                   ),
                   %(token)s || ':op:' || value,%(token)s || ':saga:' || value,
                   %(token)s || ':book-idempotency:' || value,
                   CASE WHEN value %% 50 = 0 THEN 'CHAPTER_SUBMITTED' ELSE 'READY' END,
                   100,5,20,NOW() - (value * INTERVAL '1 millisecond'),NOW()
            FROM generate_series(1,10000) AS value
            """,
            {"token": token},
        )
        connection.execute(
            """
            INSERT INTO state_event(
                event_id,aggregate_type,aggregate_id,project_id,event_type,
                event_version,sequence_number,payload,created_at
            )
            SELECT %(token)s || ':event:' || value,'rq',%(token)s || ':aggregate:' || value,
                   %(token)s || ':project:' || (value %% 1000),'rq.created',1,1,
                   '{}'::jsonb,NOW() - (value * INTERVAL '1 millisecond')
            FROM generate_series(1,100000) AS value
            """,
            {"token": token},
        )
        connection.execute(
            """
            INSERT INTO outbox_event(
                outbox_id,event_id,project_id,topic,status,available_at,payload,
                created_at,updated_at
            )
            SELECT %(token)s || ':outbox:' || value,%(token)s || ':event:' || value,
                   %(token)s || ':project:' || (value %% 1000),'rq.created',
                   CASE WHEN value %% 100 = 0 THEN 'PENDING' ELSE 'ACKED' END,
                   NOW() - INTERVAL '1 minute','{}'::jsonb,
                   NOW() - (value * INTERVAL '1 millisecond'),NOW()
            FROM generate_series(1,100000) AS value
            """,
            {"token": token},
        )
        connection.execute(
            """
            INSERT INTO authority_asset(asset_id,project_id,asset_type)
            SELECT %(token)s || ':asset:' || value,
                   %(token)s || ':project:' || (value %% 1000),'rq_asset'
            FROM generate_series(1,100000) AS value
            """,
            {"token": token},
        )
        connection.execute(
            """
            INSERT INTO authority_asset_version(
                asset_version_id,asset_id,version_number,lifecycle,eligibility,
                governance,content,content_hash,schema_version
            )
            SELECT %(token)s || ':version:' || value,%(token)s || ':asset:' || value,
                   1,'IMPORTED','PENDING_EVALUATION','CLEAR','{}'::jsonb,
                   'sha256:' || repeat('b',64),'rq_asset.schema.v1'
            FROM generate_series(1,100000) AS value
            """,
            {"token": token},
        )
        connection.execute(
            """
            INSERT INTO authority_migration_run(
                migration_run_id,source_kind,source_hash,status,report,workspace_id,
                snapshot_hash,mode,idempotency_key,phase
            ) VALUES (%s,'release_qualification','sha256:' || repeat('c',64),
                      'RUNNING','{}'::jsonb,%s || ':workspace',
                      'sha256:' || repeat('c',64),'IMPORT',%s,'VALIDATE')
            """,
            [token, token, token],
        )
        connection.execute(
            """
            INSERT INTO authority_legacy_migration_item(
                migration_item_id,migration_run_id,project_id,workspace_id,
                source_ref,source_category,source_hash,stable_business_key,
                status,decision,source_asset_type,phase,next_phase,updated_at
            )
            SELECT %(token)s || ':item:' || value,%(token)s,
                   %(token)s || ':project:' || (value %% 1000),%(token)s || ':workspace',
                   'source/' || value || '.json','asset',
                   'sha256:' || repeat('d',64),'business:' || value,
                   CASE WHEN value %% 100 = 0 THEN 'NEEDS_REVIEW' ELSE 'IMPORTED' END,
                   'IMPORT','draft',
                   CASE WHEN value %% 100 = 0 THEN 'VALIDATE' ELSE 'RECONCILE' END,
                   CASE WHEN value %% 100 = 0 THEN 'VALIDATE' ELSE 'RECONCILE' END,
                   NOW() - (value * INTERVAL '1 millisecond')
            FROM generate_series(1,100000) AS value
            """,
            {"token": token},
        )
        for table in ROW_COUNTS:
            connection.execute(f"ANALYZE {table}")

        probes = (
            (
                "worker_poll",
                "authority_operation",
                """SELECT operation_id,project_id FROM authority_operation
                   WHERE definition_name='rq.worker.poll' AND status='READY'
                   ORDER BY created_at,operation_id LIMIT 10""",
            ),
            (
                "outbox_claim",
                "outbox_event",
                """SELECT outbox_id FROM outbox_event
                   WHERE LOWER(status) IN ('pending','queued','failed')
                     AND available_at <= NOW()
                     AND (lease_expires_at IS NULL OR lease_expires_at < NOW())
                   ORDER BY available_at,created_at,outbox_id LIMIT 10""",
            ),
            (
                "asset_version_lookup",
                "authority_asset_version",
                f"""SELECT asset_version_id FROM authority_asset_version
                    WHERE asset_id='{token}:asset:50000'
                    ORDER BY version_number DESC LIMIT 1""",
            ),
            (
                "book_worker_poll",
                "authority_book_production",
                """SELECT book_run_id,project_id FROM authority_book_production
                   WHERE state='CHAPTER_SUBMITTED'
                   ORDER BY updated_at,book_run_id LIMIT 10""",
            ),
            (
                "migration_resume",
                "authority_legacy_migration_item",
                f"""SELECT migration_item_id FROM authority_legacy_migration_item
                    WHERE migration_run_id='{token}' AND phase='VALIDATE'
                      AND status='NEEDS_REVIEW'
                    ORDER BY updated_at,migration_item_id LIMIT 10""",
            ),
        )
        plans = [
            _qualify_plan(connection, name=name, relation=relation, query=query)
            for name, relation, query in probes
        ]
        connection.rollback()

    return {
        "type": "AuthorityQueryPlanReleaseQualification",
        "status": "PASS",
        "migration_head": migration["current"],
        "row_counts": ROW_COUNTS,
        "enable_seqscan_disabled": False,
        "explain": "ANALYZE, BUFFERS, FORMAT JSON",
        "plans": plans,
        "duration_seconds": round(time.monotonic() - started, 3),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        default=os.environ.get("NOVEL_FORGE_DATABASE_URL") or "",
    )
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("NOVEL_FORGE_DATABASE_URL or --database-url is required")
    result = qualify(args.database_url)
    encoded = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(encoded + "\n")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
