"""Drive native Book production from an approved input snapshot in a disposable database."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import time

from novel_forge.api.authority_dependencies import (
    build_book_production_composition,
    build_chapter_authority_application,
    build_production_execution_composition,
    build_trusted_principal_resolver,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.book_authority import StartBookProductionCommand
from novel_forge.modules.runtime_job import RuntimeJobAuthority
from novel_forge.modules.production_execution.security import redact_secret_text
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
from novel_forge.tools.implementation_tree_identity import (
    build_implementation_tree_identity,
)
from novel_forge.tools.backend_qualification_resources import (
    require_disposable_database_name,
)
from novel_forge.workers.book_authority import (
    schedule_book_coordination_jobs,
    execute_book_coordination_claim,
)


CAPS = (
    "NOVEL_FORGE_DAILY_PROVIDER_CAP",
    "NOVEL_FORGE_PROJECT_DAILY_PROVIDER_CAP",
    "NOVEL_FORGE_OPERATION_PROVIDER_CAP",
    "NOVEL_FORGE_PROVIDER_MAX_COST_PER_CALL",
)


def validate_configuration(values: dict[str, str]) -> None:
    for key in CAPS:
        amount = Decimal(values.get(key) or "0")
        if not amount.is_finite() or amount <= 0:
            raise ValueError(f"explicit positive authorized budget required: {key}")
    if values.get("NOVEL_FORGE_ENVIRONMENT") not in {"validation", "production"}:
        raise ValueError("real smoke requires a controlled runtime environment")
    if not values.get("NOVEL_FORGE_LOCAL_OPERATOR_PRINCIPAL_ID"):
        raise ValueError("a configured operator Principal is required")
    if values.get("NOVEL_FORGE_AUTHORITY_PROJECT_SCOPE", "*") == "*":
        raise ValueError("smoke requires an explicit isolated project scope")


def start_command(snapshot, *, actor: str, run_key: str, chapters: int):
    return StartBookProductionCommand(
        project_id=snapshot.project_id,
        workspace_id=snapshot.workspace_id,
        book_id=snapshot.book_id,
        actor_id=actor,
        trace_id=f"trace:{run_key}",
        correlation_id=run_key,
        stable_idempotency_key=run_key,
        book_design_version=snapshot.book_design_version,
        book_plan_version=snapshot.book_plan_version,
        production_profile_version=snapshot.production_profile_version,
        longform_context_versions={
            "volume_plan_version": snapshot.current_volume_plan_version,
            "arc_plan_versions": list(snapshot.current_relevant_arc_plan_versions),
            **{
                key: getattr(snapshot, key)
                for key in (
                    "character_state_version",
                    "foreshadowing_state_version",
                    "quality_trend_version",
                    "reward_ledger_version",
                    "promise_ledger_version",
                    "reader_segment_version",
                    "reader_contract_version",
                    "platform_profile_version",
                )
            },
        },
        target_chapter_count=chapters,
        input_mode="RESOLVED_AUTHORITY_INPUT",
        input_snapshot_id=snapshot.snapshot_id,
    )


def drive(
    *,
    composition,
    chapter,
    book_run_id: str,
    worker,
    events,
    maximum_ticks: int,
    deadline: float,
):
    jobs = RuntimeJobAuthority(composition.authority.database_url)
    for _ in range(maximum_ticks):
        book = composition.authority.require(book_run_id)
        if book["accepted_through_chapter"] >= book["target_chapter_count"]:
            return "ACCEPTED_TARGET_REACHED"
        if time.monotonic() >= deadline:
            return "BOUNDED_TIME_EXHAUSTED"
        schedule_book_coordination_jobs(
            composition.query, jobs, limit=1, book_run_id=book_run_id
        )
        claim = jobs.claim(
            runtime_group="book",
            worker_id=worker.principal_id,
            lease_seconds=30,
            job_kinds=("BOOK_COORDINATION_TICK",),
            subject_kind="BOOK_RUN",
            subject_id=book_run_id,
        )
        if claim is None:
            return "WAITING_LEASE_OR_RETRY"
        tick = execute_book_coordination_claim(jobs, composition, claim)
        events({"kind": "BOOK_TICK", "result": tick})
        progress = composition.query.progress(book_run_id=book_run_id)
        active_root = str(tick.get("operation_id") or "") if tick["action"] == "DISPATCH_CHAPTER" else progress.active_operation_id
        if active_root and progress.active_operation_status not in {"SUCCEEDED", "FAILED_TERMINAL", "CANCELLED"}:
            scheduler = chapter.scheduler(principal=worker)
            for _ in range(80):
                if time.monotonic() >= deadline:
                    return "BOUNDED_TIME_EXHAUSTED"
                result = scheduler.tick(
                    project_id=book["project_id"],
                    root_operation_id=active_root,
                )
                events({"kind": "CHAPTER_TICK", "result": asdict(result)})
                if result.saga_status == "SUCCEEDED":
                    break
        elif tick["action"].startswith(("BLOCK", "WAIT", "APPROVAL", "REQUEST_REPLAN")):
            return tick["action"]
    return "BOUNDED_TICKS_EXHAUSTED"


def export_artifacts(*, database_url: str, project_id: str, destination: Path, extra_kinds: tuple[str, ...] = ()):
    query = AuthorityAssetQuery(database_url)
    kinds = (
        "world_preparation_source",
        "world_preparation_generation",
        "world_preparation_evaluation",
        "narrative_governance_action",
        "model_call_log",
        "cost_ledger",
        "execution_recovery_session",
        "provider_request_admission_manifest",
    )
    for kind in (*kinds, *extra_kinds):
        rows = query.list(project_id=project_id, asset_type=kind, limit=500)
        if len(rows) == 500:
            raise RuntimeError(
                f"evidence export bound reached for {kind}; retain PostgreSQL for paged export"
            )
        (destination / f"{kind}.json").write_text(
            json.dumps(
                [
                    {
                        "asset_version_id": row.asset_version_id,
                        "content_hash": row.content_hash,
                        "logical_ref": row.logical_ref,
                        "content": row.content,
                    }
                    for row in rows
                ],
                default=str,
                indent=2,
            )
            + "\n"
        )


def export(*, composition, book_run_id: str, destination: Path):
    book = composition.authority.require(book_run_id)
    export_artifacts(database_url=composition.authority.database_url,
                     project_id=book["project_id"], destination=destination)
    from novel_forge.modules.chapter_authority.queries import ChapterAuthorityQuery
    chapters = ChapterAuthorityQuery(composition.authority.database_url)
    runs = chapters.list_runs(project_id=book["project_id"], book_run_id=book_run_id, limit=500)
    if len(runs) == 500:
        raise RuntimeError("chapter workspace export bound reached; retain PostgreSQL for paged export")
    (destination / "chapter-workspaces.json").write_text(json.dumps(
        [chapters.require_workspace(project_id=book["project_id"], root_operation_id=run["root_operation_id"]) for run in runs],
        default=str, ensure_ascii=False, indent=2,
    ) + "\n")
    realities = [
        composition.query.narrative_reality(book_run_id=book_run_id, chapter_number=n)
        for n in range(1, book["accepted_through_chapter"] + 1)
    ]
    (destination / "realities.json").write_text(
        json.dumps(realities, default=str, indent=2) + "\n"
    )
    (destination / "book.json").write_text(
        json.dumps(book, default=str, indent=2) + "\n"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument(
        "--input-snapshot-id",
        required=True,
        help="Approved Book opening/input resolver snapshot; no causal candidates or scores",
    )
    parser.add_argument(
        "--run-key",
        required=True,
        help="Keep this exact key when resuming; confirmed effects are reconciled by the runtime",
    )
    parser.add_argument(
        "--root",
        type=Path,
        required=True,
        help="Existing isolated Authority runtime/object-store root",
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        required=True,
        help="A new export directory for this invocation; never overwrites failed evidence",
    )
    parser.add_argument(
        "--chapters",
        type=int,
        default=3,
        help="Experiment bound only, not a quality qualification level",
    )
    parser.add_argument("--max-ticks", type=int, default=60)
    parser.add_argument("--max-seconds", type=int, default=1800)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Use the explicitly configured authorized budgets and real routes",
    )
    args = parser.parse_args(argv)
    if (
        not 3 <= args.chapters <= 12
        or not 1 <= args.max_ticks <= 120
        or not 1 <= args.max_seconds <= 7200
    ):
        parser.error(
            "smoke bounds must be chapters 3..12, ticks 1..120 and seconds 1..7200"
        )
    args.evidence_dir.mkdir(parents=True, exist_ok=False)

    def events(row):
        with (args.evidence_dir / "events.jsonl").open("a") as stream:
            stream.write(json.dumps(row, default=str) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    repo = Path(__file__).resolve().parents[1]
    report = {
        "status": "BLOCKED",
        "proof_ceiling": "REAL_PROVIDER_SMOKE_ONLY",
        "source_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True
        ).strip(),
        "implementation_tree_sha": build_implementation_tree_identity(repo)[
            "implementation_tree_sha"
        ],
        "snapshot_id": args.input_snapshot_id,
        "run_key": args.run_key,
        "human_editorial": "NOT_PROVEN",
        "longitudinal": "NOT_PROVEN",
        "production_operation": "NOT_PROVEN",
    }
    execution = composition = book_run_id = None
    try:
        values = dict(os.environ)
        if (
            report["source_sha"] != args.expected_sha
            or subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=repo, text=True
            ).strip()
        ):
            raise ValueError("a clean expected implementation commit is required")
        validate_configuration(values)
        if not args.execute:
            raise ValueError("--execute is required after budget/configuration review")
        import psycopg

        database_url = values["NOVEL_FORGE_DATABASE_URL"]
        with psycopg.connect(
            database_url, options="-c default_transaction_read_only=on"
        ) as connection:
            require_disposable_database_name(
                connection.execute("SELECT current_database()").fetchone()[0]
            )
        settings = IndustrialSettings(
            root=str(args.root),
            environment=values["NOVEL_FORGE_ENVIRONMENT"],
            storage_authority="postgresql",
            database_url=database_url,
        )
        execution = build_production_execution_composition(settings, env=values)
        if any(
            route.model_profile.model_provider == "scripted_provider_v2"
            for route in execution.gateway.routes.values()
        ):
            raise ValueError("scripted routes cannot execute a real Provider smoke")
        resolver = build_trusted_principal_resolver(env=values)
        principal = resolver.resolve_api_principal()
        worker = resolver.resolve_worker_principal("world-smoke-worker")
        chapter = build_chapter_authority_application(
            settings, execution=execution, env=values
        )
        composition = build_book_production_composition(
            settings,
            principal=principal,
            execution=execution,
            env=values,
            chapter_application=chapter,
        )
        snapshot = composition.input_resolver.require(args.input_snapshot_id)
        admitted = composition.authority.start(
            start_command(
                snapshot,
                actor=principal.principal_id,
                run_key=args.run_key,
                chapters=args.chapters,
            ),
            principal=principal,
        )
        book_run_id = admitted.book_run_id
        events(
            {
                "kind": "ADMITTED",
                "book_run_id": book_run_id,
                "snapshot": snapshot.to_dict(),
            }
        )
        report.update(book_run_id=book_run_id, status="RUNNING")
        report["stop_reason"] = drive(
            composition=composition,
            chapter=chapter,
            book_run_id=book_run_id,
            worker=worker,
            events=events,
            maximum_ticks=args.max_ticks,
            deadline=time.monotonic() + args.max_seconds,
        )
        report["status"] = (
            "EXECUTED_REVIEW_EVIDENCE"
            if report["stop_reason"] == "ACCEPTED_TARGET_REACHED"
            else "BLOCKED"
        )
    except Exception as exc:
        report.update(
            status="BLOCKED" if book_run_id is None else "FAILED",
            error_type=type(exc).__name__,
            error=redact_secret_text(exc),
        )
        events(
            {
                "kind": "FAILURE",
                "error_type": type(exc).__name__,
                "error": redact_secret_text(exc),
            }
        )
    finally:
        try:
            if composition is not None and book_run_id is not None:
                export(
                    composition=composition,
                    book_run_id=book_run_id,
                    destination=args.evidence_dir,
                )
        except Exception as exc:
            report.update(status="EVIDENCE_EXPORT_FAILED", export_error=redact_secret_text(exc))
            events({"kind": "EXPORT_FAILURE", "error": redact_secret_text(exc)})
        finally:
            if execution is not None:
                execution.close()
            if (
                build_implementation_tree_identity(repo)["implementation_tree_sha"]
                != report["implementation_tree_sha"]
            ):
                report.update(
                    status="STALE_IMPLEMENTATION",
                    error="Implementation identity changed during smoke",
                )
            (args.evidence_dir / "result.json").write_text(
                json.dumps(report, indent=2) + "\n"
            )
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "EXECUTED_REVIEW_EVIDENCE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
