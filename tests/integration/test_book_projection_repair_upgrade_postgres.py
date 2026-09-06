from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import replace
from uuid import uuid4
from types import SimpleNamespace

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

from novel_forge.modules.book_authority.production import PostgresBookAuthority
from novel_forge.modules.book_authority.projection_repair import (
    PostgresBookProjectionRepairAuthority,
)
from novel_forge.modules.book_followup_authority.coordinator import (
    PostgresBookFollowupCoordinator,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.context_builder.production_retrieval import (
    build_retrieval_query_plan,
    build_retrieval_result,
    discover_accepted_retrieval_candidates,
)
from novel_forge.modules.runtime_job import RuntimeJobAuthority
from novel_forge.storage.database_runtime import close_all_database_runtimes
from novel_forge.storage.migrations import LATEST_MIGRATION_ID, MIGRATIONS
from novel_forge.workers.book_authority import execute_book_projection_repair_claim
from tests.integration.authority_postgres_support import DATABASE_URL


REVISION_0093 = "20260820_0093_book_liveness_critical_path_closure"
REVISION_0094 = "20260820_0094_industrial_autonomous_novel_os"
REVISION_0095 = "20260821_0095_post_merge_correctness_repair"
REVISION_0096 = "20260821_0096_runtime_hardening"


def _database_url(database_name: str) -> str:
    values = conninfo_to_dict(DATABASE_URL)
    values["dbname"] = database_name
    return make_conninfo(**values)


def _content_hash(content: dict[str, object]) -> str:
    encoded = json.dumps(
        content, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _apply_through(database_url: str, revision: str) -> None:
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS nf_schema_migrations (
                migration_id TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        applied = {
            str(row[0])
            for row in connection.execute(
                "SELECT migration_id FROM nf_schema_migrations"
            ).fetchall()
        }
        for migration in MIGRATIONS:
            if migration.migration_id not in applied:
                for statement in migration.upgrade_statements:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO nf_schema_migrations(migration_id) VALUES (%s)",
                    [migration.migration_id],
                )
            if migration.migration_id == revision:
                connection.commit()
                return
    raise AssertionError(f"unknown migration revision: {revision}")


def _upgrade_to_current_runtime(database_url: str) -> None:
    """Run current application code only against its current schema contract."""
    _apply_through(database_url, LATEST_MIGRATION_ID)


def _insert_operation(
    cursor: psycopg.Cursor,
    operation_id: str,
    project_id: str,
    workspace_id: str,
    *,
    status: str = "SUCCEEDED",
) -> None:
    cursor.execute(
        """
        INSERT INTO authority_operation(
            operation_id, definition_name, definition_version, project_id,
            workspace_id, actor_id, status, root_operation_id,
            idempotency_scope, idempotency_key, request_digest,
            definition_snapshot, completion_contract_snapshot, policy_snapshot,
            trace_id, span_id, correlation_id, concurrency_key
        ) VALUES (
            %s,'repair.upgrade.fixture','1.0.0',%s,%s,'upgrade-fixture',
            %s,%s,'project:repair-upgrade',%s,%s,
            '{}'::jsonb,'{}'::jsonb,'{}'::jsonb,%s,%s,%s,%s
        )
        """,
        [
            operation_id,
            project_id,
            workspace_id,
            status,
            operation_id,
            operation_id,
            "digest:" + operation_id,
            "trace:" + operation_id,
            "span:" + operation_id,
            "correlation:repair-upgrade",
            "concurrency:" + operation_id,
        ],
    )


def _insert_asset(
    cursor: psycopg.Cursor,
    *,
    project_id: str,
    asset_version_id: str,
    asset_type: str,
    content: dict[str, object],
) -> str:
    asset_id = "asset:" + asset_version_id
    digest = _content_hash(content)
    cursor.execute(
        "INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,%s)",
        [asset_id, project_id, asset_type],
    )
    cursor.execute(
        """
        INSERT INTO authority_asset_version(
            asset_version_id, asset_id, version_number, lifecycle,
            eligibility, governance, content, content_hash, schema_version
        ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,%s)
        """,
        [asset_version_id, asset_id, Jsonb(content), digest, asset_type + ".v1"],
    )
    return digest


def _seed_accepted_history(
    database_url: str,
    *,
    chapters: int = 2,
    arc_content: dict[str, object] | None = None,
    outcome_contents: dict[int, dict[str, object]] | None = None,
    story_state_contents: dict[int, dict[str, object]] | None = None,
) -> dict[str, str]:
    project_id = "project:repair-upgrade"
    workspace_id = "workspace:repair-upgrade"
    book_id = "book:repair-upgrade"
    book_run_id = "book-run:repair-upgrade"
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO authority_operation_definition(
                name, definition_version, family, enabled,
                command_schema, result_schema, policy, completion_contract
            ) VALUES (
                'repair.upgrade.fixture','1.0.0','book_authority',TRUE,
                '{}'::jsonb,'{}'::jsonb,'{}'::jsonb,'{}'::jsonb
            )
            """
        )
        root_operation_id = "operation:repair-upgrade:root"
        _insert_operation(cursor, root_operation_id, project_id, workspace_id)
        project_hash = _insert_asset(
            cursor,
            project_id=project_id,
            asset_version_id="project:repair-upgrade:v1",
            asset_type="project",
            content={"project_id": project_id},
        )
        del project_hash
        _insert_asset(
            cursor,
            project_id=project_id,
            asset_version_id="workspace:repair-upgrade:v1",
            asset_type="workspace",
            content={"workspace_id": workspace_id},
        )
        _insert_asset(
            cursor,
            project_id=project_id,
            asset_version_id="book:repair-upgrade:v1",
            asset_type="book",
            content={"book_id": book_id},
        )
        cursor.execute(
            """
            INSERT INTO authority_project(
                project_id,primary_workspace_id,title,status,stage,health,
                current_asset_version_id,created_by_operation_id,last_operation_id
            ) VALUES (%s,%s,'Repair Upgrade','ACTIVE','PRODUCTION','HEALTHY',
                      'project:repair-upgrade:v1',%s,%s)
            """,
            [project_id, workspace_id, root_operation_id, root_operation_id],
        )
        cursor.execute(
            """
            INSERT INTO authority_workspace(
                workspace_id,project_id,book_id,status,current_asset_version_id,
                created_by_operation_id,last_operation_id
            ) VALUES (%s,%s,%s,'ACTIVE','workspace:repair-upgrade:v1',%s,%s)
            """,
            [workspace_id, project_id, book_id, root_operation_id, root_operation_id],
        )
        cursor.execute(
            """
            INSERT INTO authority_book(
                book_id,project_id,workspace_id,principal_id,service_identity,
                book_scope,production_profile,runtime_policy,release_identity,
                status,current_book_asset_version_id,
                created_by_operation_id,last_operation_id
            ) VALUES (%s,%s,%s,'upgrade-fixture','upgrade-fixture',
                      '{}'::jsonb,'{}'::jsonb,'{}'::jsonb,'repair-upgrade',
                      'DESIGN_PENDING','book:repair-upgrade:v1',%s,%s)
            """,
            [book_id, project_id, workspace_id, root_operation_id, root_operation_id],
        )
        cursor.execute(
            """
            INSERT INTO authority_saga(
                saga_id,root_operation_id,project_id,status,trace_id,correlation_id
            ) VALUES (
                'saga:repair-upgrade:book',%s,%s,'SUCCEEDED',
                'trace:repair-upgrade','correlation:repair-upgrade'
            )
            """,
            [root_operation_id, project_id],
        )
        arc_hash = _insert_asset(
            cursor,
            project_id=project_id,
            asset_version_id="arc-plan:repair-upgrade:v1",
            asset_type="arc_plan",
            content=arc_content
            or {
                "objective": "fixture objective",
                "dependencies": [],
                "closure_conditions": ["accepted evidence only"],
            },
        )
        del arc_hash
        cursor.execute(
            """
            INSERT INTO authority_book_production(
                book_run_id,project_id,workspace_id,book_id,book_design_version,
                book_plan_version,production_profile_version,
                longform_context_versions,root_operation_id,saga_id,
                stable_idempotency_key,state,current_chapter,target_chapter_count,
                light_recap_cadence,formal_recap_cadence,input_mode
            ) VALUES (%s,%s,%s,%s,'book-design:v1','book-plan:v1',
                      'profile:repair-upgrade',%s,%s,'saga:repair-upgrade:book',
                      'repair-upgrade:book','READY',0,%s,5,10,
                      'LEGACY_FIXTURE_INPUT_MODE')
            """,
            [
                book_run_id,
                project_id,
                workspace_id,
                book_id,
                Jsonb(
                    {
                        "volume_plan_version": "volume-plan:v1",
                        "arc_plan_versions": ["arc-plan:repair-upgrade:v1"],
                        "character_state_version": "character-state:v1",
                        "foreshadowing_state_version": "foreshadowing:v1",
                        "quality_trend_version": "quality-trend:v1",
                        "reward_ledger_version": "reward-ledger:v1",
                        "promise_ledger_version": "promise-ledger:v1",
                    }
                ),
                root_operation_id,
                chapters + 1,
            ],
        )
        source_ids: list[str] = []
        for chapter in range(1, chapters + 1):
            request_id = f"chapter-request:repair-upgrade:{chapter}"
            chapter_operation_id = f"operation:repair-upgrade:chapter:{chapter}"
            acceptance_operation_id = f"operation:repair-upgrade:accept:{chapter}"
            _insert_operation(cursor, chapter_operation_id, project_id, workspace_id)
            _insert_operation(cursor, acceptance_operation_id, project_id, workspace_id)
            cursor.execute(
                """
                INSERT INTO authority_saga(
                    saga_id,root_operation_id,project_id,status,trace_id,correlation_id
                ) VALUES (%s,%s,%s,'SUCCEEDED',%s,'correlation:repair-upgrade')
                """,
                [
                    f"saga:repair-upgrade:chapter:{chapter}",
                    chapter_operation_id,
                    project_id,
                    f"trace:repair-upgrade:{chapter}",
                ],
            )
            plan_id = f"chapter-plan:repair-upgrade:{chapter}:v1"
            plan_content = {
                "chapter": chapter,
                "required_arc_contributions": [
                    {
                        "arc_plan_version_id": "arc-plan:repair-upgrade:v1",
                        "expected_progress_units": 9,
                    }
                ],
            }
            plan_hash = _insert_asset(
                cursor,
                project_id=project_id,
                asset_version_id=plan_id,
                asset_type="chapter_plan",
                content=plan_content,
            )
            outcome_id = f"chapter-outcome:repair-upgrade:{chapter}:v1"
            state_id = f"story-state:repair-upgrade:{chapter}:v1"
            canon_id = f"canon:repair-upgrade:{chapter}:v1"
            _insert_asset(
                cursor,
                project_id=project_id,
                asset_version_id=outcome_id,
                asset_type="chapter_outcome",
                content=(outcome_contents or {}).get(chapter)
                or {
                    "contract_version": "chapter-outcome-legacy-v1",
                    "chapter_number": chapter,
                },
            )
            _insert_asset(
                cursor,
                project_id=project_id,
                asset_version_id=state_id,
                asset_type="story_state",
                content=(story_state_contents or {}).get(chapter)
                or {"current_state": {"narrative_obligation": []}},
            )
            _insert_asset(
                cursor,
                project_id=project_id,
                asset_version_id=canon_id,
                asset_type="canon_snapshot",
                content={"chapter_number": chapter, "facts": []},
            )
            source_ids.extend((outcome_id, state_id, canon_id, plan_id))
            cursor.execute(
                """
                INSERT INTO authority_book_chapter_request(
                    chapter_request_id,book_run_id,project_id,chapter_number,
                    chapter_plan_version,chapter_plan_content_hash,
                    production_profile_version,stable_idempotency_key,
                    command_payload,chapter_root_operation_id,chapter_saga_id,
                    status_reference
                ) VALUES (%s,%s,%s,%s,%s,%s,'profile:repair-upgrade',%s,%s,%s,%s,
                          'SUCCEEDED')
                """,
                [
                    request_id,
                    book_run_id,
                    project_id,
                    chapter,
                    plan_id,
                    plan_hash,
                    f"repair-upgrade:{chapter}",
                    Jsonb(
                        {
                            "execution_chapter_plan_asset_version_id": plan_id,
                            "context_version_refs": {
                                "arc_plan_versions": ["arc-plan:repair-upgrade:v1"]
                            },
                        }
                    ),
                    chapter_operation_id,
                    f"saga:repair-upgrade:chapter:{chapter}",
                ],
            )
            cursor.execute(
                """
                INSERT INTO authority_child_delegation(
                    delegation_id,project_id,owner_authority,owner_id,
                    child_authority,chapter_request_id,chapter_number,
                    plan_version_id,child_root_operation_id,child_saga_id,
                    stable_idempotency_key,status,accepted_at
                ) VALUES (%s,%s,'BOOK',%s,'CHAPTER',%s,%s,%s,%s,%s,%s,
                          'ACCEPTED',NOW())
                """,
                [
                    f"delegation:repair-upgrade:{chapter}",
                    project_id,
                    book_run_id,
                    request_id,
                    chapter,
                    plan_id,
                    chapter_operation_id,
                    f"saga:repair-upgrade:chapter:{chapter}",
                    f"repair-upgrade:delegation:{chapter}",
                ],
            )
            cursor.execute(
                """
                INSERT INTO authority_book_chapter_acceptance(
                    acceptance_id,project_id,book_run_id,chapter_request_id,
                    delegation_id,acceptance_operation_id,chapter_number,
                    chapter_outcome_asset_version_id,story_state_asset_version_id,
                    canon_snapshot_asset_version_id,evidence,status
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'{}'::jsonb,'COMMITTED')
                """,
                [
                    f"acceptance:repair-upgrade:{chapter}",
                    project_id,
                    book_run_id,
                    request_id,
                    f"delegation:repair-upgrade:{chapter}",
                    acceptance_operation_id,
                    chapter,
                    outcome_id,
                    state_id,
                    canon_id,
                ],
            )
        cursor.execute(
            """
            UPDATE authority_book_production
            SET current_chapter=%s, accepted_through_chapter=%s,
                active_plan_version_id=%s,
                active_story_state_version_id=%s,
                active_canon_snapshot_version_id=%s,
                last_chapter_outcome_version_id=%s,
                version=version+1, updated_at=NOW()
            WHERE book_run_id=%s
            """,
            [
                chapters,
                chapters,
                f"chapter-plan:repair-upgrade:{chapters}:v1",
                f"story-state:repair-upgrade:{chapters}:v1",
                f"canon:repair-upgrade:{chapters}:v1",
                f"chapter-outcome:repair-upgrade:{chapters}:v1",
                book_run_id,
            ],
        )
        connection.commit()
    return {
        "project_id": project_id,
        "book_id": book_id,
        "book_run_id": book_run_id,
        "source_ids": ",".join(source_ids),
    }


class BookProjectionRepairUpgradePostgresTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_name = ("nf_projection_repair_" + uuid4().hex)[:63]
        self.admin_url = _database_url("postgres")
        with psycopg.connect(self.admin_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name))
            )
        self.database_url = _database_url(self.database_name)

    def tearDown(self) -> None:
        close_all_database_runtimes()
        with psycopg.connect(self.admin_url, autocommit=True) as connection:
            connection.execute(
                """
                SELECT pg_terminate_backend(pid) FROM pg_stat_activity
                WHERE datname=%s AND pid<>pg_backend_pid()
                """,
                [self.database_name],
            )
            connection.execute(
                sql.SQL("DROP DATABASE {}").format(sql.Identifier(self.database_name))
            )

    def test_0093_accepted_history_upgrades_through_0094_and_repairs(self) -> None:
        self._exercise_upgrade(already_at_0094=False)

    def test_existing_0094_install_discovers_and_repairs_missing_pointers(self) -> None:
        self._exercise_upgrade(already_at_0094=True)

    def test_committed_chapter_checkpoint_resumes_after_worker_crash(self) -> None:
        class SimulatedWorkerCrash(BaseException):
            pass

        _apply_through(self.database_url, REVISION_0093)
        scope = _seed_accepted_history(self.database_url)
        _apply_through(self.database_url, REVISION_0095)
        _upgrade_to_current_runtime(self.database_url)
        jobs = RuntimeJobAuthority(self.database_url)
        claim = jobs.claim(
            runtime_group="book_repair",
            worker_id="repair-crash-worker",
            lease_seconds=30,
            job_kinds=("BOOK_PROJECTION_REPAIR",),
        )
        assert claim is not None
        jobs.start(claim)

        def crash_after_commit(checkpoint: str) -> None:
            if checkpoint == "after_projection_repair_business_commit":
                raise SimulatedWorkerCrash()

        crashing = PostgresBookProjectionRepairAuthority(
            self.database_url,
            application_build_id="repair-upgrade-test",
            commit_sha="a" * 40,
            failure_injector=crash_after_commit,
        )
        with self.assertRaises(SimulatedWorkerCrash):
            crashing.run_batch(
                claim, actor_id="repair-crash-worker", maximum_chapters=1
            )
        with psycopg.connect(self.database_url) as connection:
            partial = connection.execute(
                """
                SELECT next_chapter,authoritative_status,
                       (SELECT active_longform_projection_set_id
                        FROM authority_book_production WHERE book_run_id=%s)
                FROM authority_book_projection_repair WHERE book_run_id=%s
                """,
                [scope["book_run_id"], scope["book_run_id"]],
            ).fetchone()
            self.assertEqual(partial, (2, "CHECKPOINTED", None))
            connection.execute(
                """
                UPDATE authority_lease_acquisition
                SET expires_at=acquired_at+INTERVAL '1 microsecond'
                WHERE status='HELD'
                """
            )
            connection.commit()

        recovered = PostgresBookProjectionRepairAuthority(
            self.database_url,
            application_build_id="repair-upgrade-test",
            commit_sha="a" * 40,
        )
        with self.assertRaisesRegex(KernelError, "RuntimeJob lease or fence is stale"):
            recovered.run_batch(
                replace(claim, fencing_token=claim.fencing_token + 1),
                actor_id="repair-crash-worker",
                maximum_chapters=1,
            )
        result = recovered.run_batch(
            claim, actor_id="repair-crash-worker", maximum_chapters=1
        )
        self.assertTrue(result.complete)
        with psycopg.connect(self.database_url) as connection:
            evidence = connection.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM authority_book_projection_repair_checkpoint),
                  (SELECT COUNT(*) FROM authority_book_narrative_projection_set),
                  (SELECT COUNT(*) FROM authority_operation
                   WHERE definition_name='book.projection.repair'
                     AND status='SUCCEEDED')
                """
            ).fetchone()
        self.assertEqual(evidence, (2, 2, 3))

    def test_bounded_runtime_job_atomically_hands_off_continuation(self) -> None:
        _apply_through(self.database_url, REVISION_0093)
        scope = _seed_accepted_history(self.database_url, chapters=5)
        _apply_through(self.database_url, REVISION_0095)
        _upgrade_to_current_runtime(self.database_url)
        jobs = RuntimeJobAuthority(self.database_url)
        repair = PostgresBookProjectionRepairAuthority(
            self.database_url,
            application_build_id="repair-upgrade-test",
            commit_sha="a" * 40,
        )
        composition = SimpleNamespace(
            projection_repair=repair,
            principal=SimpleNamespace(principal_id="repair-continuation-worker"),
        )
        first = jobs.claim(
            runtime_group="book_repair",
            worker_id="repair-continuation-worker",
            lease_seconds=30,
            job_kinds=("BOOK_PROJECTION_REPAIR",),
        )
        assert first is not None
        first_result = execute_book_projection_repair_claim(
            jobs, composition, first, lease_seconds=30, maximum_chapters=4
        )
        self.assertFalse(first_result["complete"])
        self.assertEqual(first_result["next_chapter"], 5)
        continuation_id = str(first_result["continuation_runtime_job_id"])
        second = jobs.claim(
            runtime_group="book_repair",
            worker_id="repair-continuation-worker",
            lease_seconds=30,
            job_kinds=("BOOK_PROJECTION_REPAIR",),
        )
        assert second is not None
        self.assertEqual(second.runtime_job_id, continuation_id)
        second_result = execute_book_projection_repair_claim(
            jobs, composition, second, lease_seconds=30, maximum_chapters=4
        )
        self.assertTrue(second_result["complete"])
        with psycopg.connect(self.database_url) as connection:
            row = connection.execute(
                """
                SELECT repair.authoritative_status,repair.next_chapter,
                       book.active_longform_projection_set_id,
                       (SELECT COUNT(*) FROM authority_runtime_job
                        WHERE runtime_group='book_repair'
                          AND subject_id=%s)
                FROM authority_book_projection_repair AS repair
                JOIN authority_book_production AS book
                  ON book.book_run_id=repair.book_run_id
                WHERE repair.book_run_id=%s
                """,
                [scope["book_run_id"], scope["book_run_id"]],
            ).fetchone()
        self.assertEqual(row[0], "AUTHORITATIVE_REPAIR_COMPLETE")
        self.assertEqual(row[1], 6)
        self.assertTrue(str(row[2]).startswith("longform-projection:"))
        self.assertEqual(row[3], 2)

    def test_repair_persists_accepted_obligation_checkpoint_followup(self) -> None:
        _apply_through(self.database_url, REVISION_0093)
        arc_content = {
            "contract_version": "arc-plan-v1",
            "logical_key": "arc:repair-upgrade",
            "objective": "pay the accepted promise",
            "dependencies": [],
            "closure_conditions": ["promise is paid on page"],
            "target_progress_units": 5,
            "target_window": {"from_chapter": 1, "to_chapter": 10},
        }
        outcome_contents = {
            chapter: {
                "contract_version": "chapter-outcome-v3",
                "project_id": "project:repair-upgrade",
                "book_id": "book:repair-upgrade",
                "chapter_number": chapter,
                "arc_evidence": [
                    {
                        "arc_plan_version_id": "arc-plan:repair-upgrade:v1",
                        "observation_status": "OBSERVED",
                        "contribution_kind": "PRIMARY",
                        "progress_units": 1 if chapter == 1 else 0,
                        "resolution_evidence": [f"scene:{chapter}:1"],
                        "obligation_ids": ["promise:repair"],
                    }
                ],
            }
            for chapter in (1, 2)
        }
        state = {
            "current_state": {
                "narrative_obligation": [
                    {
                        "entity_key": "obligation_id=promise:repair",
                        "state": {
                            "obligation_id": "promise:repair",
                            "obligation_type": "PROMISE",
                            "status": "OPEN",
                            "opened_chapter": 1,
                            "target_window": {
                                "status": "SCHEDULED",
                                "from_chapter": 1,
                                "to_chapter": 1,
                            },
                            "linked_arc_ids": ["arc-plan:repair-upgrade:v1"],
                        },
                    }
                ]
            }
        }
        scope = _seed_accepted_history(
            self.database_url,
            arc_content=arc_content,
            outcome_contents=outcome_contents,
            story_state_contents={2: state},
        )
        _apply_through(self.database_url, REVISION_0095)
        _upgrade_to_current_runtime(self.database_url)
        jobs = RuntimeJobAuthority(self.database_url)
        claim = jobs.claim(
            runtime_group="book_repair",
            worker_id="repair-arc-followup-worker",
            lease_seconds=30,
            job_kinds=("BOOK_PROJECTION_REPAIR",),
        )
        assert claim is not None
        jobs.start(claim)
        repair = PostgresBookProjectionRepairAuthority(
            self.database_url,
            application_build_id="repair-upgrade-test",
            commit_sha="a" * 40,
        )
        result = repair.run_batch(
            claim, actor_id="repair-arc-followup-worker", maximum_chapters=4
        )
        self.assertTrue(result.complete)
        with psycopg.connect(self.database_url) as connection:
            followup = connection.execute(
                """
                SELECT followup.decision, followup.status,
                       followup.reason_evidence->'checkpoints'->0
                           ->'overdue_obligation_ids',
                       book.state
                FROM authority_arc_checkpoint_followup AS followup
                JOIN authority_book_production AS book
                  ON book.book_run_id=followup.book_run_id
                WHERE followup.book_run_id=%s
                ORDER BY followup.accepted_through_chapter DESC
                LIMIT 1
                """,
                [scope["book_run_id"]],
            ).fetchone()
        self.assertEqual(followup[0:2], ("CORRECT", "READY"))
        self.assertEqual(followup[2], ["promise:repair"])
        self.assertEqual(followup[3], "CHECKPOINT_PENDING")

    def test_arc_followup_reconciles_canonical_failures_and_retry_replay(self) -> None:
        _apply_through(self.database_url, REVISION_0093)
        arc_content = {
            "contract_version": "arc-plan-v1",
            "logical_key": "arc:repair-upgrade",
            "objective": "pay the accepted promise",
            "dependencies": [],
            "closure_conditions": ["promise is paid on page"],
            "target_progress_units": 5,
            "target_window": {"from_chapter": 1, "to_chapter": 10},
        }
        outcome_contents = {
            chapter: {
                "contract_version": "chapter-outcome-v3",
                "project_id": "project:repair-upgrade",
                "book_id": "book:repair-upgrade",
                "chapter_number": chapter,
                "arc_evidence": [
                    {
                        "arc_plan_version_id": "arc-plan:repair-upgrade:v1",
                        "observation_status": "OBSERVED",
                        "contribution_kind": "PRIMARY",
                        "progress_units": 1 if chapter == 1 else 0,
                        "resolution_evidence": [f"scene:{chapter}:1"],
                        "obligation_ids": ["promise:repair"],
                    }
                ],
            }
            for chapter in (1, 2)
        }
        story_state = {
            "current_state": {
                "narrative_obligation": [
                    {
                        "entity_key": "obligation_id=promise:repair",
                        "state": {
                            "obligation_id": "promise:repair",
                            "obligation_type": "PROMISE",
                            "status": "OPEN",
                            "opened_chapter": 1,
                            "target_window": {
                                "status": "SCHEDULED",
                                "from_chapter": 1,
                                "to_chapter": 1,
                            },
                            "linked_arc_ids": ["arc-plan:repair-upgrade:v1"],
                        },
                    }
                ]
            }
        }
        scope = _seed_accepted_history(
            self.database_url,
            arc_content=arc_content,
            outcome_contents=outcome_contents,
            story_state_contents={2: story_state},
        )
        _apply_through(self.database_url, REVISION_0096)
        _upgrade_to_current_runtime(self.database_url)
        jobs = RuntimeJobAuthority(self.database_url)
        claim = jobs.claim(
            runtime_group="book_repair",
            worker_id="arc-followup-hardening-worker",
            lease_seconds=30,
            job_kinds=("BOOK_PROJECTION_REPAIR",),
        )
        assert claim is not None
        jobs.start(claim)
        repaired = PostgresBookProjectionRepairAuthority(
            self.database_url,
            application_build_id="repair-upgrade-test",
            commit_sha="a" * 40,
        ).run_batch(claim, actor_id="arc-followup-hardening-worker", maximum_chapters=4)
        self.assertTrue(repaired.complete)

        with (
            psycopg.connect(self.database_url) as connection,
            connection.cursor() as cursor,
        ):
            revision_id = "arc-revision:hardening:v1"
            revision_hash = _insert_asset(
                cursor,
                project_id=scope["project_id"],
                asset_version_id=revision_id,
                asset_type="arc_revision_candidate",
                content={"type": "ArcRevisionCandidate", "future_only": True},
            )
            truth_before = cursor.execute(
                """
                SELECT accepted_through_chapter,active_story_state_version_id,
                       active_canon_snapshot_version_id,
                       active_longform_projection_set_id
                FROM authority_book_production WHERE book_run_id=%s
                """,
                [scope["book_run_id"]],
            ).fetchone()
            connection.commit()

        coordinator = PostgresBookFollowupCoordinator(
            SimpleNamespace(database_url=self.database_url),
            query=SimpleNamespace(),
            principal=SimpleNamespace(),
        )

        def bind_immutable_operation(
            *, operation_id: str, operation_status: str, decision: str
        ) -> None:
            with (
                psycopg.connect(self.database_url) as connection,
                connection.cursor() as cursor,
            ):
                _insert_operation(
                    cursor,
                    operation_id,
                    scope["project_id"],
                    "workspace:repair-upgrade",
                    status=operation_status,
                )
                cursor.execute(
                    """
                    INSERT INTO authority_operation_output_asset(
                        operation_id, asset_id, asset_version_id,
                        output_key, role, content_hash
                    ) VALUES (%s,%s,%s,'longform.recap.replan_request',
                              'proposal',%s)
                    """,
                    [operation_id, "asset:" + revision_id, revision_id, revision_hash],
                )
                cursor.execute(
                    """
                    UPDATE authority_arc_checkpoint_followup
                    SET operation_id=%s,decision=%s,status='RUNNING',
                        last_error='{}'::jsonb,version=version+1
                    WHERE book_run_id=%s
                    """,
                    [operation_id, decision, scope["book_run_id"]],
                )
                cursor.execute(
                    """
                    UPDATE authority_book_production
                    SET state='CHECKPOINT_PENDING',paused_reason='',failure_reason='',
                        version=version+1 WHERE book_run_id=%s
                    """,
                    [scope["book_run_id"]],
                )
                connection.commit()

        for operation_status, followup_status, book_state in (
            ("FAILED_RETRYABLE", "FAILED_RETRYABLE", "CHECKPOINT_PENDING"),
            (
                "RECONCILIATION_REQUIRED",
                "RECONCILIATION_REQUIRED",
                "CHECKPOINT_PENDING",
            ),
            ("FAILED_FINAL", "FAILED_FINAL", "PAUSED"),
            ("DEAD_LETTER", "DEAD_LETTER", "PAUSED"),
            ("CANCELLED", "CANCELLED", "PAUSED"),
        ):
            with self.subTest(operation_status=operation_status):
                recap_operation_id = (
                    "operation:arc-followup-hardening:" + operation_status.lower()
                )
                bind_immutable_operation(
                    operation_id=recap_operation_id,
                    operation_status=operation_status,
                    decision="CORRECT",
                )
                coordinator.reconcile_arc_checkpoint_followup(recap_operation_id)
                coordinator.reconcile_arc_checkpoint_followup(recap_operation_id)
                with psycopg.connect(self.database_url) as connection:
                    observed = connection.execute(
                        """
                        SELECT followup.status,followup.last_error->>'operation_status',
                               book.state,book.accepted_through_chapter,
                               book.active_story_state_version_id,
                               book.active_canon_snapshot_version_id,
                               book.active_longform_projection_set_id
                        FROM authority_arc_checkpoint_followup AS followup
                        JOIN authority_book_production AS book
                          ON book.book_run_id=followup.book_run_id
                        WHERE followup.operation_id=%s
                        """,
                        [recap_operation_id],
                    ).fetchone()
                self.assertEqual(
                    observed[0:3], (followup_status, operation_status, book_state)
                )
                self.assertEqual(observed[3:], truth_before)

        for decision in ("CORRECT", "REPLAN_REQUIRED"):
            with self.subTest(decision=decision):
                recap_operation_id = (
                    "operation:arc-followup-hardening:success:" + decision.lower()
                )
                bind_immutable_operation(
                    operation_id=recap_operation_id,
                    operation_status="SUCCEEDED",
                    decision=decision,
                )
                coordinator.reconcile_arc_checkpoint_followup(recap_operation_id)
                coordinator.reconcile_arc_checkpoint_followup(recap_operation_id)
                with psycopg.connect(self.database_url) as connection:
                    success = connection.execute(
                        """
                        SELECT followup.status,book.state,
                               (SELECT COUNT(*) FROM authority_operation_output_asset
                                WHERE operation_id=%s
                                  AND output_key='longform.recap.replan_request')
                        FROM authority_arc_checkpoint_followup AS followup
                        JOIN authority_book_production AS book
                          ON book.book_run_id=followup.book_run_id
                        WHERE followup.operation_id=%s
                        """,
                        [recap_operation_id, recap_operation_id],
                    ).fetchone()
                self.assertEqual(success, ("PROPOSED", "REPLAN_REQUIRED", 1))

    def test_postgresql_fts_retrieval_freezes_memo_boundary_and_excludes_future(
        self,
    ) -> None:
        _apply_through(self.database_url, REVISION_0093)
        scope = _seed_accepted_history(self.database_url)
        _apply_through(self.database_url, REVISION_0095)
        _upgrade_to_current_runtime(self.database_url)
        jobs = RuntimeJobAuthority(self.database_url)
        claim = jobs.claim(
            runtime_group="book_repair",
            worker_id="repair-retrieval-worker",
            lease_seconds=30,
            job_kinds=("BOOK_PROJECTION_REPAIR",),
        )
        assert claim is not None
        jobs.start(claim)
        repaired = PostgresBookProjectionRepairAuthority(
            self.database_url,
            application_build_id="repair-upgrade-test",
            commit_sha="a" * 40,
        ).run_batch(claim, actor_id="repair-retrieval-worker", maximum_chapters=4)
        self.assertTrue(repaired.complete)
        with psycopg.connect(self.database_url) as connection:
            source = connection.execute(
                """
                SELECT source_asset_version_id,source_artifact_type,content_text
                FROM authority_narrative_retrieval_document
                WHERE book_id=%s ORDER BY retrieval_document_id LIMIT 1
                """,
                [scope["book_id"]],
            ).fetchone()
            assert source is not None
            future_id = "narrative-retrieval:future-boundary"
            future_document = {
                "retrieval_document_id": future_id,
                "project_id": scope["project_id"],
                "book_id": scope["book_id"],
                "source_asset_version_id": str(source[0]),
                "source_artifact_type": str(source[1]),
                "accepted_from_chapter": 3,
                "memory_layer": "L9",
                "content_text": "future accepted fact must not leak",
                "metadata": {"projection_kind": "future_fixture"},
            }
            projection_hash = _content_hash(future_document)
            connection.execute(
                """
                INSERT INTO authority_narrative_retrieval_document(
                    retrieval_document_id,project_id,book_id,
                    source_asset_version_id,source_artifact_type,
                    accepted_from_chapter,memory_layer,content_text,
                    metadata,projection_hash,created_by_operation_id
                )
                SELECT %s,%s,%s,%s,%s,3,'L9',%s,%s,%s,
                       created_by_operation_id
                FROM authority_narrative_retrieval_document
                WHERE book_id=%s ORDER BY retrieval_document_id LIMIT 1
                """,
                [
                    future_id,
                    scope["project_id"],
                    scope["book_id"],
                    str(source[0]),
                    str(source[1]),
                    future_document["content_text"],
                    Jsonb(future_document["metadata"]),
                    projection_hash,
                    scope["book_id"],
                ],
            )
            connection.commit()
        _apply_through(self.database_url, REVISION_0096)
        intent = {
            "chapter": 3,
            "intent_fingerprint": "sha256:" + "1" * 64,
            "accepted_boundary": {"accepted_through_chapter": 2},
            "required_arc_contributions": [],
            "active_obligations": [],
            "retrieval_graph": {},
        }
        memo = {
            "chapter": 3,
            "qualification": "QUALIFIED",
            "memo_fingerprint": "sha256:" + "2" * 64,
            "accepted_boundary": {"accepted_through_chapter": 2},
            "retrieval_queries": ["chapter outcome"],
            "arc_actions": [],
            "obligation_actions": [],
        }
        query_plan = build_retrieval_query_plan(intent=intent, memo=memo)
        discovery = discover_accepted_retrieval_candidates(
            self.database_url,
            project_id=scope["project_id"],
            book_id=scope["book_id"],
            query_plan=query_plan,
        )
        self.assertTrue(discovery.documents)
        self.assertNotIn(
            future_id,
            {item["retrieval_document_id"] for item in discovery.documents},
        )
        self.assertIn(
            (future_id, "FUTURE_ACCEPTED_BOUNDARY"),
            {
                (item["retrieval_document_id"], item["reason"])
                for item in discovery.rejected_documents
            },
        )
        result = build_retrieval_result(
            project_id=scope["project_id"],
            book_id=scope["book_id"],
            intent_asset_version_id="intent:chapter:3:v1",
            memo_asset_version_id="memo:chapter:3:v1",
            query_plan=query_plan,
            documents=discovery.documents,
            discovery_rejections=discovery.rejected_documents,
            semantic_status=discovery.semantic_status,
        )
        self.assertEqual(result["accepted_boundary"], {"accepted_through_chapter": 2})
        self.assertEqual(
            result["ranking"]["lexical_signal"],
            "PostgreSQL Full-Text Search / ts_rank",
        )
        self.assertEqual(
            result,
            build_retrieval_result(
                project_id=scope["project_id"],
                book_id=scope["book_id"],
                intent_asset_version_id="intent:chapter:3:v1",
                memo_asset_version_id="memo:chapter:3:v1",
                query_plan=query_plan,
                documents=discovery.documents,
                discovery_rejections=discovery.rejected_documents,
                semantic_status=discovery.semantic_status,
            ),
        )

    def _exercise_upgrade(self, *, already_at_0094: bool) -> None:
        _apply_through(self.database_url, REVISION_0093)
        scope = _seed_accepted_history(self.database_url)
        with psycopg.connect(self.database_url) as connection:
            before = connection.execute(
                """
                SELECT asset_version_id,content_hash,content
                FROM authority_asset_version
                WHERE asset_version_id=ANY(%s) ORDER BY asset_version_id
                """,
                [scope["source_ids"].split(",")],
            ).fetchall()
        _apply_through(self.database_url, REVISION_0094)
        with psycopg.connect(self.database_url) as connection:
            missing = connection.execute(
                """
                SELECT active_longform_projection_set_id,
                       (SELECT COUNT(*) FROM authority_book_chapter_acceptance
                        WHERE book_run_id=%s
                          AND longform_projection_set_id IS NOT NULL)
                FROM authority_book_production WHERE book_run_id=%s
                """,
                [scope["book_run_id"], scope["book_run_id"]],
            ).fetchone()
            self.assertEqual(missing, (None, 0))
            if already_at_0094:
                self.assertIsNone(
                    connection.execute(
                        "SELECT to_regclass('authority_book_projection_repair')"
                    ).fetchone()[0]
                )
        _apply_through(self.database_url, REVISION_0095)
        _upgrade_to_current_runtime(self.database_url)

        jobs = RuntimeJobAuthority(self.database_url)
        claim = jobs.claim(
            runtime_group="book_repair",
            worker_id="repair-upgrade-worker",
            lease_seconds=30,
            job_kinds=("BOOK_PROJECTION_REPAIR",),
        )
        self.assertIsNotNone(claim)
        assert claim is not None
        jobs.start(claim)
        repair = PostgresBookProjectionRepairAuthority(
            self.database_url,
            application_build_id="repair-upgrade-test",
            commit_sha="a" * 40,
        )
        result = repair.run_batch(
            claim, actor_id="repair-upgrade-worker", maximum_chapters=4
        )
        self.assertTrue(result.complete)
        jobs.complete(claim, {"repair_id": result.repair_id, "complete": True})

        with psycopg.connect(self.database_url) as connection:
            book = connection.execute(
                """
                SELECT project_id,book_id,book_run_id,accepted_through_chapter,
                       active_longform_projection_set_id,
                       active_story_state_version_id,
                       active_canon_snapshot_version_id,
                       last_chapter_outcome_version_id
                FROM authority_book_production WHERE book_run_id=%s
                """,
                [scope["book_run_id"]],
            ).fetchone()
            pointers = connection.execute(
                """
                SELECT COUNT(*),COUNT(longform_projection_set_id)
                FROM authority_book_chapter_acceptance WHERE book_run_id=%s
                """,
                [scope["book_run_id"]],
            ).fetchone()
            after = connection.execute(
                """
                SELECT asset_version_id,content_hash,content
                FROM authority_asset_version
                WHERE asset_version_id=ANY(%s) ORDER BY asset_version_id
                """,
                [scope["source_ids"].split(",")],
            ).fetchall()
            unknown = connection.execute(
                """
                SELECT observation_status,deviation_units
                FROM authority_arc_progress_v2 ORDER BY chapter_number
                """
            ).fetchall()
            realities = connection.execute(
                "SELECT chapter_number, revision_id, parent_revision_id FROM authority_narrative_reality_revision WHERE book_run_id=%s ORDER BY chapter_number",
                [scope["book_run_id"]],
            ).fetchall()
            self.assertEqual([row[0] for row in realities], [1, 2])
            self.assertIsNone(realities[0][2])
            self.assertEqual(realities[1][2], realities[0][1])
            counts_before_rerun = connection.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM authority_book_narrative_projection_set),
                  (SELECT COUNT(*) FROM authority_book_projection_repair_checkpoint),
                  (SELECT COUNT(*) FROM authority_arc_progress_v2)
                """
            ).fetchone()
        self.assertEqual(pointers, (2, 2))
        self.assertEqual(before, after)
        self.assertEqual(unknown, [("UNKNOWN", None), ("UNKNOWN", None)])
        self.assertTrue(str(book[4]).startswith("longform-projection:"))

        gate = object.__new__(PostgresBookAuthority)
        gate.database_url = self.database_url
        gate._require_accepted_projection_boundary(
            {
                "project_id": str(book[0]),
                "book_id": str(book[1]),
                "book_run_id": str(book[2]),
                "accepted_through_chapter": int(book[3]),
                "active_longform_projection_set_id": str(book[4]),
                "active_story_state_version_id": str(book[5]),
                "active_canon_snapshot_version_id": str(book[6]),
                "last_chapter_outcome_version_id": str(book[7]),
            }
        )

        replay = repair.run_batch(
            claim, actor_id="repair-upgrade-worker", maximum_chapters=1
        )
        self.assertTrue(replay.complete)
        with psycopg.connect(self.database_url) as connection:
            self.assertEqual(connection.execute(
                "SELECT chapter_number, revision_id, parent_revision_id FROM authority_narrative_reality_revision WHERE book_run_id=%s ORDER BY chapter_number",
                [scope["book_run_id"]],
            ).fetchall(), realities)
            counts_after_rerun = connection.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM authority_book_narrative_projection_set),
                  (SELECT COUNT(*) FROM authority_book_projection_repair_checkpoint),
                  (SELECT COUNT(*) FROM authority_arc_progress_v2)
                """
            ).fetchone()
        self.assertEqual(counts_before_rerun, counts_after_rerun)


if __name__ == "__main__":
    unittest.main()
