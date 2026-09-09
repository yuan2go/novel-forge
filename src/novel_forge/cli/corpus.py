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
            "inspect", "compare", "discover", "review", "equivalence", "reprocess",
            "preview",
            "import",
            "run",
            "status",
            "pause",
            "resume",
            "cancel",
            "lineage",
        ),
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--workspace-id", default="")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--source", default="")
    parser.add_argument("--run-key", default="")
    parser.add_argument("--edition-id", default="")
    parser.add_argument("--processing-id", default="")
    parser.add_argument("--compare-to", default="")
    parser.add_argument("--decision", type=Path)
    parser.add_argument("--job-id", default="")
    parser.add_argument("--after", default="")
    parser.add_argument("--historical", action="store_true")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--max-stages", type=int, default=100)
    parser.add_argument("--reason", default="operator Corpus import control")


def run_corpus_command(settings: Any, args: argparse.Namespace) -> dict[str, Any]:
    principal = build_trusted_principal_resolver().resolve_api_principal()
    project = args.project_id
    principal.require(
        "source.authority.query"
        if args.action in {"status", "lineage", "inspect", "compare", "discover"}
        else "source.authority.execute",
        project,
    )
    build, sha = authority_release_identity()
    query = SourceImportQuery(settings.database_url)
    if args.action in {"inspect", "compare", "discover"}:
        return query.corpus_processing(project_id=project,identity=args.processing_id or args.edition_id,edition=not bool(args.processing_id),compare_to=args.compare_to,discover=args.action=="discover",limit=args.limit,after=args.after,historical=getattr(args,"historical",False),principal=principal)
    if args.action == "reprocess":
        from novel_forge.modules.source_import.corpus_ingestion.contracts import ParserProfile
        from novel_forge.modules.source_import.corpus_ingestion.runtime import CorpusIngestionRuntime
        from novel_forge.modules.source_import.corpus_ingestion.reprocessing import admit_reprocessing
        if not args.manifest or args.manifest.stat().st_size > 262144:
            raise ValueError("reprocess requires a bounded parser profile JSON in --manifest")
        app = SourceImportApplication(settings.database_url,application_build_id=build,commit_sha=sha)
        return admit_reprocessing(CorpusIngestionRuntime(app),project_id=project,edition_id=args.edition_id,parser=ParserProfile.model_validate(json.loads(args.manifest.read_text())),run_key=args.run_key,principal=principal)
    if args.action in {"review", "equivalence"}:
        if not args.decision or args.decision.stat().st_size > 262144 or not args.workspace_id or not args.run_key:
            raise ValueError("decision, workspace and stable run key are required")
        action = validate_corpus_action(json.loads(args.decision.read_text()))
        if action.action != {"review":"review_processing", "equivalence":"decide_equivalence"}[args.action]:
            raise ValueError("wrong decision action")
        authority = SourceAuthorityApplication(settings.database_url,application_build_id=build,commit_sha=sha)
        admitted = authority.admit_corpus(CorpusCommand(project_id=project,workspace_id=args.workspace_id,actor_id=principal.principal_id,idempotency_key=args.run_key,trace_id=args.run_key,correlation_id=args.run_key,action=action),principal=principal)
        return SourceAuthorityScheduler(authority).run_or_recover(operation_id=admitted["operation_id"],project_id=project)
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
                raise ValueError("--source override is only for local files/directories")
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
    if args.action == "status":
        return job
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
    for _ in range(args.max_stages):
        job = query.import_job(
            project_id=project, import_job_id=args.job_id, principal=principal
        )
        if job["status"] in {"PAUSED", "CANCELLED"}:
            break
        rows = query.work(
            project_id=project, import_job_id=args.job_id, principal=principal
        )
        eligible = {
            operation
            for operation, scope in scheduler.pending_operations(limit=1000)
            if scope == project
        }
        selected = next((row for row in rows if row["operation_id"] in eligible), None)
        if selected is None:
            break
        result = scheduler.run_or_recover(
            operation_id=selected["operation_id"], project_id=project
        )
        outcomes.append(
            {"operation_id": selected["operation_id"], "status": result["status"]}
        )
    return {
        "stages": outcomes,
        "stage_limit": args.max_stages,
        "job": query.import_job(
            project_id=project, import_job_id=args.job_id, principal=principal
        ),
    }
