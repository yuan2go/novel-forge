from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from novel_forge.api.authority_dependencies import (
    authority_release_identity,
    build_production_execution_composition,
    build_source_import_application,
    build_trusted_principal_resolver,
)
from novel_forge.modules.source_authority import (
    SourceAuthorityApplication,
    SourceAuthorityScheduler,
)
from novel_forge.modules.source_authority.corpus import validate_corpus_action
from novel_forge.modules.source_authority.corpus_application import CorpusCommand
from novel_forge.modules.source_import import (
    SourceImportApplication,
    SourceImportQuery,
    SourceImportScheduler,
)
from novel_forge.modules.source_import.corpus_ingestion.contracts import (
    IngestionManifest,
)


def add_corpus_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "corpus", help="governed Corpus preview, ingestion and recovery"
    )
    parser.add_argument(
        "action",
        choices=(
            "catalog-capture",
            "catalog-run",
            "catalog-status",
            "catalog-snapshots",
            "work",
            "jobs",
            "curated",
            "resolve-work",
            "relate",
            "curate",
            "analyze",
            "reading-preview",
            "chapters",
            "evidence",
            "inspect",
            "compare",
            "discover",
            "review",
            "equivalence",
            "reprocess",
            "preview",
            "import",
            "run",
            "status",
            "results",
            "targets",
            "pause",
            "resume",
            "cancel",
            "lineage",
        ),
    )
    parser.add_argument("--format", choices=("json", "text"), default="json")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--workspace-id", default="")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument(
        "--reading-scopes",
        type=Path,
        help="bounded JSON array of exact ChapterReadingScope requests",
    )
    parser.add_argument("--work-id", default="")
    parser.add_argument("--corpus-id", default="")
    parser.add_argument("--revision-id", default="")
    parser.add_argument("--intended-use", choices=("SOURCE_ANALYSIS", "ABSTRACT_GENERATION"), default="SOURCE_ANALYSIS")
    parser.add_argument("--target-book-id", default="")
    parser.add_argument("--inspect-local-codex", action="store_true")
    parser.add_argument("--max-calls", type=int, default=0)
    parser.add_argument("--max-tokens", type=int, default=0)
    parser.add_argument("--authorization-ref", default="")
    parser.add_argument("--source", default="")
    parser.add_argument("--run-key", default="")
    parser.add_argument("--edition-id", default="")
    parser.add_argument("--processing-id", default="")
    parser.add_argument("--compare-to", default="")
    parser.add_argument("--decision", type=Path)
    parser.add_argument("--job-id", default="")
    parser.add_argument("--operation-id", default="")
    parser.add_argument("--chunk-id", default="")
    parser.add_argument("--byte-start", type=int, default=0)
    parser.add_argument("--byte-end", type=int, default=0)
    parser.add_argument("--after", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--source-type", default="")
    parser.add_argument(
        "--run-key-prefix", default="",
        help="literal run-key prefix for jobs from Corpus import/preview only",
    )
    parser.add_argument("--historical", action="store_true")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--max-stages", type=int, default=100)
    parser.add_argument("--reason", default="operator Corpus import control")


def run_corpus_command(settings: Any, args: argparse.Namespace) -> dict[str, Any]:
    principal = build_trusted_principal_resolver().resolve_api_principal()
    project = args.project_id
    principal.require(
        "source.authority.query"
        if args.action
        in {
            "status",
            "catalog-status",
            "catalog-snapshots",
            "jobs",
            "results",
            "targets",
            "reading-preview",
            "chapters",
            "evidence",
            "lineage",
            "inspect",
            "compare",
            "discover",
            "work",
            "curated",
        }
        else "source.authority.execute",
        project,
    )
    build, sha = authority_release_identity()
    if args.action.startswith("catalog-"):
        from novel_forge.modules.source_authority.public_catalog import CatalogCapture
        from novel_forge.modules.source_authority.public_catalog_application import CatalogCommand
        app = SourceAuthorityApplication(settings.database_url, application_build_id=build, commit_sha=sha)
        if args.action == "catalog-snapshots":
            return {"items": app.public_catalog.snapshots(project_id=project, after=args.after, limit=args.limit)}
        if args.action == "catalog-status":
            return app.public_catalog.result(args.operation_id, project, replayed=True)
        if args.action == "catalog-run":
            return SourceAuthorityScheduler(app).run_or_recover(operation_id=args.operation_id, project_id=project)
        if not args.manifest or not args.workspace_id or not args.run_key:
            raise ValueError("catalog capture requires manifest, workspace and stable run key")
        return app.admit_catalog(CatalogCommand(project_id=project, workspace_id=args.workspace_id,
            idempotency_key=args.run_key, actor_id=principal.principal_id,
            capture=CatalogCapture.model_validate_json(args.manifest.read_bytes()),
            trace_id="trace:" + args.run_key, correlation_id="correlation:" + args.run_key), principal=principal)
    query = SourceImportQuery(settings.database_url)
    if args.action == "jobs":
        rows = query.list_imports(
            project_id=project, status=args.status, limit=args.limit,
            after=args.after, source_type=args.source_type,
            run_key_prefix=args.run_key_prefix, principal=principal,
        )
        return {"items": rows, "after": args.after,
                "next_after": rows[-1]["import_job_id"] if len(rows) == args.limit else ""}
    if args.action == "evidence":
        from novel_forge.modules.source_import.corpus_ingestion.reading_scope import (
            read_evidence,
        )

        app = build_source_import_application(
            settings, execution=build_production_execution_composition(settings)
        )
        return read_evidence(
            app,
            project,
            args.job_id,
            args.operation_id,
            args.chunk_id,
            args.byte_start,
            args.byte_end,
            principal,
        )
    if args.action in {"work", "curated"}:
        return query.corpus_catalog(
            project_id=project,
            kind=args.action,
            identity=args.revision_id
            or (args.work_id if args.action == "work" else args.corpus_id),
            revision=bool(args.revision_id),
            principal=principal,
        )
    if args.action == "chapters":
        return query.chapter_units(
            project_id=project,
            processing_id=args.processing_id,
            after=int(args.after or 0),
            limit=args.limit,
            principal=principal,
        )
    reading_scopes = []
    if getattr(args, "reading_scopes", None):
        if args.reading_scopes.stat().st_size > 262144:
            raise ValueError("reading scope configuration exceeds 256 KiB")
        reading_scopes = json.loads(args.reading_scopes.read_text(encoding="utf-8"))
    if args.action == "reading-preview":
        from novel_forge.modules.source_import.corpus_ingestion.reading_scope import (
            preview_reading,
        )

        app = build_source_import_application(
            settings, execution=build_production_execution_composition(settings)
        )
        return preview_reading(
            settings.database_url,
            project,
            args.revision_id,
            reading_scopes,
            principal,
            runtime=app._require_execution_port().frozen_reading_runtime(),
            object_store_reader=app.object_store_reader,
            inspect_codex=args.inspect_local_codex,
            max_calls=args.max_calls,
            max_tokens=args.max_tokens,
            authorization_ref=args.authorization_ref,
            intended_use=args.intended_use,
            target_book_id=args.target_book_id,
        )
    if args.action == "analyze":
        from novel_forge.modules.source_import.corpus_ingestion.curated_analysis import (
            CuratedAnalysisRequest,
            admit_curated_analysis,
        )

        policy = {}
        if args.manifest:
            if args.manifest.stat().st_size > 262144:
                raise ValueError("analysis policy exceeds 256 KiB")
            policy = json.loads(args.manifest.read_text(encoding="utf-8"))
        request = CuratedAnalysisRequest(
            project_id=project,
            revision_id=args.revision_id,
            run_key=args.run_key,
            max_members=args.limit,
            max_calls=args.max_calls,
            max_tokens=args.max_tokens,
            authorization_ref=args.authorization_ref,
            intelligence_policy=policy,
            reading_scopes=reading_scopes,
            intended_use=args.intended_use,
            target_book_id=args.target_book_id,
        )
        app = SourceImportApplication(
            settings.database_url, application_build_id=build, commit_sha=sha
        )
        if reading_scopes:
            app = build_source_import_application(
                settings, execution=build_production_execution_composition(settings)
            )
        return admit_curated_analysis(app, request, principal)
    if args.action in {"inspect", "compare", "discover"}:
        return query.corpus_processing(
            project_id=project,
            identity=args.processing_id or args.edition_id,
            edition=not bool(args.processing_id),
            compare_to=args.compare_to,
            discover=args.action == "discover",
            limit=args.limit,
            after=args.after,
            historical=getattr(args, "historical", False),
            principal=principal,
        )
    if args.action == "reprocess":
        from novel_forge.modules.source_import.corpus_ingestion.contracts import (
            ParserProfile,
        )
        from novel_forge.modules.source_import.corpus_ingestion.runtime import (
            CorpusIngestionRuntime,
        )
        from novel_forge.modules.source_import.corpus_ingestion.reprocessing import (
            admit_reprocessing,
        )

        if not args.manifest or args.manifest.stat().st_size > 262144:
            raise ValueError(
                "reprocess requires a bounded parser profile JSON in --manifest"
            )
        app = SourceImportApplication(
            settings.database_url, application_build_id=build, commit_sha=sha
        )
        return admit_reprocessing(
            CorpusIngestionRuntime(app),
            project_id=project,
            edition_id=args.edition_id,
            parser=ParserProfile.model_validate(json.loads(args.manifest.read_text())),
            run_key=args.run_key,
            principal=principal,
        )
    if args.action in {"review", "equivalence", "resolve-work", "relate", "curate"}:
        if (
            not args.decision
            or args.decision.stat().st_size > 262144
            or not args.workspace_id
            or not args.run_key
        ):
            raise ValueError("decision, workspace and stable run key are required")
        action = validate_corpus_action(json.loads(args.decision.read_text()))
        if (
            action.action
            != {
                "review": "review_processing",
                "equivalence": "decide_equivalence",
                "resolve-work": "resolve_canonical_works",
                "relate": "declare_relation",
                "curate": "revise_curated_corpus",
            }[args.action]
        ):
            raise ValueError("wrong decision action")
        authority = SourceAuthorityApplication(
            settings.database_url, application_build_id=build, commit_sha=sha
        )
        admitted = authority.admit_corpus(
            CorpusCommand(
                project_id=project,
                workspace_id=args.workspace_id,
                actor_id=principal.principal_id,
                idempotency_key=args.run_key,
                trace_id=args.run_key,
                correlation_id=args.run_key,
                action=action,
            ),
            principal=principal,
        )
        return SourceAuthorityScheduler(authority).run_or_recover(
            operation_id=admitted["operation_id"], project_id=project
        )
    if args.action in {"preview", "import"}:
        if not args.workspace_id or args.manifest is None or not args.run_key:
            raise ValueError(
                "preview/import require --workspace-id, --manifest and --run-key"
            )
        if args.manifest.stat().st_size > 262144:
            raise ValueError("manifest exceeds 256 KiB")
        manifest_data = json.loads(args.manifest.read_text(encoding="utf-8"))
        if getattr(args, "source", ""):
            if manifest_data["source"]["kind"] != "LOCAL":
                raise ValueError(
                    "--source override is only for local files/directories"
                )
            manifest_data["source"]["location"] = args.source
        manifest = IngestionManifest.model_validate(manifest_data)
        app = SourceImportApplication(
            settings.database_url, application_build_id=build, commit_sha=sha
        )
        return app.create_corpus_import(
            project_id=project,
            workspace_id=args.workspace_id,
            manifest=manifest,
            mode=args.action.upper(),
            run_key=args.run_key,
            actor_id=principal.principal_id,
            principal=principal,
        )
    if not args.job_id:
        raise ValueError("this action requires --job-id")
    job = query.import_job(
        project_id=project, import_job_id=args.job_id, principal=principal
    )
    if args.action == "results":
        return query.analysis_results(
            project_id=project,
            import_job_id=args.job_id,
            after=args.after,
            limit=min(args.limit, 100),
            processing_id=args.processing_id,
            principal=principal,
        )
    if args.action == "status":
        return job
    if args.action == "targets":
        return query.reading_targets(
            project_id=project,
            import_job_id=args.job_id,
            after=int(args.after or 0),
            limit=args.limit,
            principal=principal,
        )
    if args.action == "lineage":
        return query.corpus_lineage(
            project_id=project,
            import_job_id=args.job_id,
            after=args.after,
            limit=args.limit,
            principal=principal,
        )
    if (
        args.action in {"pause", "cancel"}
        or args.action == "resume"
        and job["status"] == "PAUSED"
    ):
        authority = SourceAuthorityApplication(
            settings.database_url, application_build_id=build, commit_sha=sha
        )
        key = args.run_key or str(uuid4())
        admitted = authority.admit_corpus(
            CorpusCommand(
                project_id=project,
                workspace_id=job["workspace_id"],
                actor_id=principal.principal_id,
                idempotency_key=f"corpus-control:{args.job_id}:{key}",
                trace_id=key,
                correlation_id=key,
                action=validate_corpus_action(
                    {
                        "action": "control_import",
                        "import_job_id": args.job_id,
                        "control": args.action.upper(),
                        "expected_status": job["status"],
                        "reason": args.reason,
                    }
                ),
            ),
            principal=principal,
        )
        return SourceAuthorityScheduler(authority).run_or_recover(
            operation_id=admitted["operation_id"], project_id=project
        )
    if args.action == "resume":
        return SourceImportApplication(
            settings.database_url, application_build_id=build, commit_sha=sha
        ).resume_import(
            project_id=project, import_job_id=args.job_id, principal=principal
        )
    if not 1 <= args.max_stages <= 1000:
        raise ValueError("--max-stages must be 1..1000")
    execution = build_production_execution_composition(settings)
    app = build_source_import_application(settings, execution=execution)
    scheduler = SourceImportScheduler(app)
    outcomes = []
    failed_this_run = []
    for _ in range(args.max_stages):
        job = query.import_job(
            project_id=project, import_job_id=args.job_id, principal=principal
        )
        if job["status"] in {"PAUSED", "CANCELLED"}:
            break
        eligible = scheduler.pending_for_job(
            project_id=project,
            import_job_id=args.job_id,
            limit=1,
            excluded=tuple(failed_this_run),
        )
        selected = {"operation_id": eligible[0][0]} if eligible else None
        if selected is None:
            break
        try:
            result = scheduler.run_or_recover(
                operation_id=selected["operation_id"], project_id=project
            )
        except Exception as exc:
            if not job["source_locator"].get("manifest", {}).get("curated_revision_id"):
                raise
            refreshed = query.work(
                project_id=project, import_job_id=args.job_id, principal=principal
            )
            failed = next(
                (r for r in refreshed if r["operation_id"] == selected["operation_id"]),
                None,
            )
            if not failed or failed["status"] not in {
                "FAILED",
                "FAILED_FINAL",
                "FAILED_RETRYABLE",
                "BLOCKED",
            }:
                raise
            failed_this_run.append(selected["operation_id"])
            outcomes.append(
                {
                    "operation_id": selected["operation_id"],
                    "status": failed["status"],
                    "failure": failed["failure"],
                    "error": str(exc),
                }
            )
            continue
        outcomes.append(
            {"operation_id": selected["operation_id"], "status": result["status"]}
        )
    final = query.import_job(
        project_id=project, import_job_id=args.job_id, principal=principal
    )
    summary = final.get("corpus", {})
    state = summary.get("analysis_state", final["effective_status"])
    remaining = summary.get("remaining_stages")
    stop = (
        state
        if state in {"PAUSED", "CANCELLED", "BLOCKED", "FAILED", "PARTIAL"}
        else "MAX_STAGES"
        if len(outcomes) == args.max_stages and remaining != 0
        else "COMPLETED"
        if remaining == 0 or state in {"IMPORTED", "PREVIEWED", "AWAITING_GOVERNANCE"}
        else "LEASED_BY_OTHER_WORKER"
        if summary.get("leased_stages", 0)
        else "NO_READY_WORK"
    )
    return {
        "stop_reason": stop,
        "remaining_stages": remaining,
        "stages": outcomes,
        "failed_stages": sum(
            r["status"] in {"FAILED", "FAILED_FINAL", "FAILED_RETRYABLE", "BLOCKED"}
            for r in outcomes
        ),
        "stage_limit": args.max_stages,
        "job": final,
    }


def format_corpus_report(result: dict[str, Any]) -> str:
    job = result.get("job", result)
    summary = result.get("summary", job.get("corpus", {}))
    lines = [
        f"Job: {result.get('import_job_id', job.get('import_job_id', '-'))}",
        f"State: {summary.get('analysis_state', job.get('effective_status', job.get('status', '-')))}",
    ]
    for key in (
        "purpose",
        "revision_id",
        "selected_members",
        "unselected_members",
        "remaining_stages",
        "failed_stages",
        "next_action",
    ):
        if key in summary:
            lines.append(f"{key}: {summary[key]}")
    if "stop_reason" in result:
        lines.append(f"stop_reason: {result['stop_reason']}")
    for stage in result.get("stages", []):
        lines.append(
            f"{stage['operation_id']} {stage.get('kind', '')} {stage['status']} {stage.get('processing_id', '')}"
        )
    lines.append(
        "Use --format json for exact frozen lineage, output identities and cost-status evidence."
    )
    return "\n".join(lines)
