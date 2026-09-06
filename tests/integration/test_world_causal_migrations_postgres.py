import psycopg
import pytest

from novel_forge.storage.migrations import run_migrations
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.migration_window_postgres_support import (
    disposable_database_at_migration,
)


@pytest.mark.parametrize(
    "baseline",
    ["20260625_0001_initial_industrial_schema", "20260906_0116_book_control_policy"],
)
def test_world_event_identity_clock_migration_fresh_and_supported_upgrade(baseline):
    with disposable_database_at_migration(
        DATABASE_URL, prefix="world_clock", target_migration_id=baseline
    ) as url:
        status = run_migrations(url)
        assert status["ok"]
        with psycopg.connect(url) as connection:
            columns = connection.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name='authority_reality_event_index'"
            ).fetchall()
            assert {
                "state_kind",
                "entity_key",
                "batch_local_id",
                "fact_origin_kind",
            }.issubset({row[0] for row in columns})
            definition = connection.execute(
                "SELECT pg_get_functiondef('authority_index_reality_events(text)'::regprocedure)"
            ).fetchone()[0]
            assert "batch_local_id" in definition
            indexes = connection.execute(
                "SELECT indexname FROM pg_indexes WHERE tablename='authority_reality_event_index'"
            ).fetchall()
            assert ("authority_reality_entity_clock_idx",) in indexes
        assert run_migrations(url) == status


def test_published_accepted_history_upgrades_and_frozen_planning_replays(
    tmp_path, request
):
    import io
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys
    import tarfile

    from novel_forge.modules.authority_security import Principal, PrincipalType
    from novel_forge.modules.book_authority.queries import PostgresBookProductionQuery
    from novel_forge.modules.narrative_state import NarrativeStateRebuildService
    from novel_forge.modules.story_planning_runtime.application import (
        StoryPlanningGenerationApplication,
    )

    baseline = "ed494c62ec9d9065dc560f9c7bafceb1e26df6f1"
    root = Path(__file__).resolve().parents[2]
    archived = subprocess.run(
        ["git", "archive", baseline], cwd=root, check=True, capture_output=True
    ).stdout
    checkout = tmp_path / "published"
    checkout.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archived)) as archive:
        archive.extractall(checkout, filter="data")
    with disposable_database_at_migration(
        DATABASE_URL,
        prefix="world_history",
        target_migration_id="20260906_0116_book_control_policy",
    ) as url:
        env = {
            **os.environ,
            "NOVEL_FORGE_DATABASE_URL": url,
            "PYTHONPATH": str(checkout / "src"),
        }
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/integration/test_core_functional_loops_postgres.py::test_open_book_runs_foundation_search_and_snapshot_vertical_in_postgres",
            ],
            cwd=checkout,
            env=env,
            capture_output=True,
            text=True,
            timeout=240,
        )
        (tmp_path / "published-production.log").write_text(
            result.stdout + result.stderr
        )
        assert result.returncode == 0, result.stdout + result.stderr
        with psycopg.connect(url) as connection:
            versions_before = connection.execute(
                "SELECT asset_version_id, content_hash FROM authority_asset_version ORDER BY asset_version_id"
            ).fetchall()
            revisions_before = connection.execute(
                "SELECT revision_id, book_run_id, project_id, book_id, chapter_number FROM authority_narrative_reality_revision ORDER BY chapter_number"
            ).fetchall()
            assert len(revisions_before) == 2
            assert (
                connection.execute(
                    "SELECT count(*) FROM nf_schema_migrations"
                ).fetchone()[0]
                == 116
            )
            frozen = connection.execute(
                "SELECT g.project_id, op.idempotency_key, op.command_payload->'payload'->>'actor_id' FROM authority_story_planning_generation g JOIN authority_operation op USING(operation_id) ORDER BY g.created_at"
            ).fetchall()
        assert run_migrations(url)["ok"]
        query = PostgresBookProductionQuery(url)
        for _, book_run_id, project_id, book_id, chapter in revisions_before:
            original = query.narrative_reality(
                book_run_id=book_run_id, chapter_number=chapter
            )
            rebuilt = NarrativeStateRebuildService(url).rebuild(
                project_id=project_id, book_id=book_id, through_chapter=chapter
            )
            assert rebuilt.projection["current_state"] == original["current_state"]

        class RejectProviderReplay:
            def execute(self, **kwargs):
                raise AssertionError(
                    "terminal historical replay must not dispatch a Provider"
                )

        application = StoryPlanningGenerationApplication(
            url,
            execution_binder=RejectProviderReplay(),
            application_build_id="published-contract-replay",
            commit_sha=baseline,
        )
        replayed = []
        for project_id, key, actor in frozen:
            command = application.find_frozen_generation_command(
                project_id=project_id, idempotency_key=key
            )
            assert (
                command is not None and command.execution_contract_version == "1.11.0"
            )
            assert command.world_preparation_request is None
            principal = Principal(
                principal_id=actor,
                principal_type=PrincipalType.LOCAL_OPERATOR,
                permissions=frozenset({"story_planning.authority.execute"}),
                project_scope=frozenset({project_id}),
                authentication_source="published-contract-replay-fixture",
            )
            try:
                replay = application.generate(command, principal=principal)
            except Exception as exc:
                with psycopg.connect(url) as connection:
                    diagnostic = connection.execute(
                        "SELECT op.status, g.status, s.lifecycle, s.qualification, s.approval FROM authority_operation op JOIN authority_story_planning_generation g USING(operation_id) LEFT JOIN authority_story_design_version_state s ON s.asset_version_id=g.candidate_asset_version_id WHERE op.project_id=%s AND op.idempotency_key=%s",
                        [project_id, key],
                    ).fetchone()
                raise AssertionError(
                    {
                        "generator": command.generator_operation_name,
                        "state": diagnostic,
                        "original_error": str(exc),
                    }
                ) from exc
            assert replay.replayed
            replayed.append(replay.generation_operation_id)
        from dataclasses import replace
        from novel_forge.modules.command_kernel.errors import KernelError

        with pytest.raises(
            KernelError, match="PLANNING_HISTORICAL_CONTRACT_REPLAY_ONLY"
        ):
            application.generate(
                replace(
                    command,
                    idempotency_key=command.idempotency_key
                    + ":new-historical-admission",
                ),
                principal=principal,
            )
        with pytest.raises(
            KernelError, match="PLANNING_GENERATION_COMMAND_IDENTITY_DRIFT"
        ):
            application.generate(
                replace(command, trace_id="altered-historical-input"),
                principal=principal,
            )
        with psycopg.connect(url) as connection:
            assert (
                connection.execute(
                    "SELECT asset_version_id, content_hash FROM authority_asset_version ORDER BY asset_version_id"
                ).fetchall()
                == versions_before
            )
            assert (
                connection.execute(
                    "SELECT count(*) FROM nf_schema_migrations"
                ).fetchone()[0]
                == 117
            )
            assert (
                connection.execute(
                    "SELECT count(*) FROM authority_reality_event_index WHERE state_kind IS NULL OR entity_key IS NULL"
                ).fetchone()[0]
                == 0
            )
        request.node.user_properties.append(
            (
                "historical_acceptance_upgrade",
                json.dumps(
                    {
                        "published_implementation_sha": baseline,
                        "migration_from": 116,
                        "migration_to": 117,
                        "reality_revisions": len(revisions_before),
                        "frozen_planning_replays": replayed,
                        "proof_ceiling": "HISTORICAL_MIGRATION_COMPATIBILITY_ONLY",
                    }
                ),
            )
        )
