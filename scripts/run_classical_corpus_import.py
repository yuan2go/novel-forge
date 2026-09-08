#!/usr/bin/env python3
"""Materialize the frozen 20-work corpus through the production SourceImport chain."""

from __future__ import annotations

import argparse
from datetime import date, datetime
from decimal import Decimal
import json
import os
from pathlib import Path
from typing import Any

from novel_forge.api.authority_dependencies import (
    authority_release_identity,
    build_production_execution_composition,
    build_source_import_application,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.project_authority import (
    ProjectAuthorityApplication,
    ProjectAuthorityCommand,
)
from novel_forge.modules.source_import import (
    CreateSourceImportCommand,
    SourceAnalysisOverride,
    SourceImportPolicy,
    SourceImportQuery,
    SourceImportScheduler,
    SourceIntelligencePolicy,
)
from novel_forge.modules.source_import.classical_corpus import (
    canonical_hash,
    load_corpus_registry,
    resolve_work_spec,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.migrations import run_migrations


ROOT = Path(__file__).resolve().parents[1]
MODEL_CAPABILITIES = (
    "source.content.classify",
    "deconstruction.observe",
    "mkaos.knowledge.extract",
    "mkaos.rule.extract",
    "mkaos.template.extract",
)
ANALYSIS_OVERRIDE_SCHEMA_VERSION = "classical-corpus-analysis-overrides.v1"
ANALYSIS_OVERRIDE_POLICY_VERSION = "classical-corpus-content-type-override.v1"
ANALYSIS_OVERRIDE_REVIEW_CLASS = "EXPERIMENTAL_POLICY_APPROVAL_NOT_HUMAN"


def _jsonable(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(_jsonable(value), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _model_effect_count(database_url: str, project_id: str) -> int:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT COUNT(*)
            FROM authority_external_effect
            WHERE project_id=%s AND capability=ANY(%s)
            """,
            [project_id, list(MODEL_CAPABILITIES)],
        )
        return int(uow.cursor.fetchone()[0])


def _work_operation(
    database_url: str, *, project_id: str, import_job_id: str
) -> tuple[str, str]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT operation.operation_id, operation.status
            FROM authority_source_import_work AS work
            JOIN authority_operation AS operation
              ON operation.operation_id=work.operation_id
            WHERE work.project_id=%s AND work.import_job_id=%s
              AND work.work_kind='WORK'
            ORDER BY work.created_at DESC
            """,
            [project_id, import_job_id],
        )
        rows = uow.cursor.fetchall()
    if len(rows) != 1:
        raise RuntimeError(
            f"expected one SourceWork operation for {import_job_id}; got {len(rows)}"
        )
    return str(rows[0][0]), str(rows[0][1])


def _seed_project(
    database_url: str,
    *,
    project_id: str,
    workspace_id: str,
    actor_id: str,
    build_id: str,
    commit_sha: str,
) -> dict[str, Any]:
    return ProjectAuthorityApplication(
        database_url,
        application_build_id=build_id,
        commit_sha=commit_sha,
    ).execute(
        ProjectAuthorityCommand(
            definition_name="project_lifecycle.create",
            project_id=project_id,
            workspace_id=workspace_id,
            actor_id=actor_id,
            idempotency_key=f"classical-corpus:project:{project_id}",
            trace_id=f"trace:classical-corpus:{project_id}",
            correlation_id=f"correlation:classical-corpus:{project_id}",
            payload=_project_payload(),
        )
    )


def _project_payload() -> dict[str, Any]:
    return {
        "title": "Classical Corpus Local Validation",
        "stage": "DESIGN",
        "config": {
            "validation_scope": "CLASSICAL_CORPUS_SOURCE_ONLY",
            "publication_policy": "FORBIDDEN",
        },
    }


def _policy(work_key: str) -> SourceImportPolicy:
    spec = resolve_work_spec(work_key)
    return SourceImportPolicy(
        include_globs=spec.include_globs,
        extension_allowlist=(
            (".html", ".json")
            if spec.parser_profile == "chinese-novel-html.v1"
            else (".json",)
        ),
        max_file_bytes=8_000_000,
        max_repository_bytes=64_000_000,
        max_files=1_000,
        max_chunk_bytes=12_000,
        parser_profile=spec.parser_profile,
        source_work_key=spec.work_key,
        corpus_registry_id=spec.registry_id,
        corpus_registry_hash=spec.registry_hash,
    )


def _load_analysis_overrides(
    path: Path | None,
    *,
    project_id: str,
    workspace_id: str,
    selected_work_keys: tuple[str, ...],
    known_work_keys: frozenset[str],
) -> tuple[dict[str, SourceAnalysisOverride], dict[str, Any]]:
    if path is None:
        return {}, {
            "schema_version": ANALYSIS_OVERRIDE_SCHEMA_VERSION,
            "mode": "NONE",
            "override_count": 0,
        }
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"analysis override manifest is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("analysis override manifest must be an object")
    expected_identity = {
        "schema_version": ANALYSIS_OVERRIDE_SCHEMA_VERSION,
        "policy_version": ANALYSIS_OVERRIDE_POLICY_VERSION,
        "review_class": ANALYSIS_OVERRIDE_REVIEW_CLASS,
        "project_id": project_id,
        "workspace_id": workspace_id,
    }
    mismatches = [
        key for key, expected in expected_identity.items() if value.get(key) != expected
    ]
    if mismatches:
        raise RuntimeError(
            "analysis override manifest identity mismatch: " + ", ".join(mismatches)
        )
    raw_overrides = value.get("overrides")
    if not isinstance(raw_overrides, list) or not raw_overrides:
        raise RuntimeError("analysis override manifest requires non-empty overrides")
    selected = frozenset(selected_work_keys)
    overrides: dict[str, SourceAnalysisOverride] = {}
    for index, raw_override in enumerate(raw_overrides):
        if not isinstance(raw_override, dict):
            raise RuntimeError(f"analysis override {index} must be an object")
        work_key = str(raw_override.get("work_key") or "")
        if work_key not in known_work_keys:
            raise RuntimeError(f"analysis override has unknown work key: {work_key}")
        if work_key not in selected:
            raise RuntimeError(f"analysis override is outside this run: {work_key}")
        if work_key in overrides:
            raise RuntimeError(f"analysis override is duplicated: {work_key}")
        try:
            overrides[work_key] = SourceAnalysisOverride(
                logical_document_scope_hash=str(
                    raw_override.get("logical_document_scope_hash") or ""
                ),
                content_type=str(raw_override.get("content_type") or ""),
                reason=str(raw_override.get("reason") or ""),
                decision_ref=str(raw_override.get("decision_ref") or ""),
                boundary_resolution=str(
                    raw_override.get("boundary_resolution") or ""
                ),
                expected_document_count=int(
                    raw_override.get("expected_document_count") or 0
                ),
            )
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"analysis override is invalid for {work_key}: {exc}"
            ) from exc
    manifest_hash = canonical_hash(value)
    return overrides, {
        "schema_version": ANALYSIS_OVERRIDE_SCHEMA_VERSION,
        "mode": "EXACT_SCOPE_EXPERIMENTAL_POLICY",
        "policy_version": ANALYSIS_OVERRIDE_POLICY_VERSION,
        "review_class": ANALYSIS_OVERRIDE_REVIEW_CLASS,
        "manifest_hash": manifest_hash,
        "override_count": len(overrides),
        "overrides": [
            {
                "work_key": work_key,
                "contract_hash": override.contract_hash,
                "logical_document_scope_hash": (
                    override.logical_document_scope_hash
                ),
                "content_type": override.content_type.value,
                "decision_ref": override.decision_ref,
                "boundary_resolution": override.boundary_resolution,
                "expected_document_count": override.expected_document_count,
            }
            for work_key, override in sorted(overrides.items())
        ],
    }


def _materialize(args: argparse.Namespace) -> dict[str, Any]:
    settings = IndustrialSettings.from_env(root=ROOT)
    if not settings.database_url:
        raise RuntimeError("NOVEL_FORGE_DATABASE_URL is required")
    migration = run_migrations(settings.database_url)
    if not migration["ok"]:
        raise RuntimeError(f"migrations incomplete: {migration}")
    build_id, commit_sha = authority_release_identity()
    project = _seed_project(
        settings.database_url,
        project_id=args.project_id,
        workspace_id=args.workspace_id,
        actor_id=args.actor_id,
        build_id=build_id,
        commit_sha=commit_sha,
    )
    execution = build_production_execution_composition(settings)
    application = build_source_import_application(settings, execution=execution)
    scheduler = SourceImportScheduler(
        application,
        worker_id=str(
            os.environ.get("NOVEL_FORGE_SOURCE_IMPORT_WORKER_ID")
            or "classical-corpus-source-worker"
        ),
        lease_seconds=int(
            os.environ.get("NOVEL_FORGE_AUTHORITY_LEASE_SECONDS") or "60"
        ),
    )
    query = SourceImportQuery(settings.database_url)
    registry = load_corpus_registry()
    selected_keys = tuple(args.work_key or [row["work_key"] for row in registry["works"]])
    known_work_keys = frozenset(str(row["work_key"]) for row in registry["works"])
    unknown = sorted(set(selected_keys) - known_work_keys)
    if unknown:
        raise RuntimeError("unknown work keys: " + ", ".join(unknown))
    if len(set(selected_keys)) != len(selected_keys):
        raise RuntimeError("work selections must be unique")
    analysis_overrides, analysis_override_manifest = _load_analysis_overrides(
        args.analysis_override_file,
        project_id=args.project_id,
        workspace_id=args.workspace_id,
        selected_work_keys=selected_keys,
        known_work_keys=known_work_keys,
    )
    model_effects_before = _model_effect_count(settings.database_url, args.project_id)
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for ordinal, work_key in enumerate(selected_keys, start=1):
        spec = resolve_work_spec(str(work_key), registry=registry)
        try:
            admitted = application.create_import(
                CreateSourceImportCommand(
                    project_id=args.project_id,
                    workspace_id=args.workspace_id,
                    source_type="github_repository",
                    repository_url=spec.repository_url,
                    requested_ref=spec.repository_commit_sha,
                    policy=_policy(spec.work_key),
                    intelligence_policy=SourceIntelligencePolicy(),
                    analysis_override=analysis_overrides.get(spec.work_key),
                    mode="IMPORT",
                    rights_authorization="licensed",
                    license_name=spec.license_name,
                    copyright_boundary=(
                        "local research validation and abstract knowledge only; "
                        "repository license is not independent clearance of every "
                        "modern collation, annotation, or commentary"
                    ),
                    actor_id=args.actor_id,
                    idempotency_key=(
                        f"{spec.registry_id}:{spec.registry_hash}:"
                        f"{spec.work_key}:{args.run_label}"
                    ),
                    trace_id=f"trace:classical-corpus:{args.project_id}:{spec.work_key}",
                    correlation_id=f"correlation:classical-corpus:{args.project_id}",
                )
            )
            discovery = scheduler.run_or_recover(
                operation_id=str(admitted["operation_id"]),
                project_id=args.project_id,
            )
            work_operation_id, _work_status = _work_operation(
                settings.database_url,
                project_id=args.project_id,
                import_job_id=str(admitted["import_job_id"]),
            )
            materialized = scheduler.run_or_recover(
                operation_id=work_operation_id,
                project_id=args.project_id,
            )
            manifest = query.source_work_manifest(
                project_id=args.project_id,
                import_job_id=str(admitted["import_job_id"]),
            )
            job = query.import_job(
                project_id=args.project_id,
                import_job_id=str(admitted["import_job_id"]),
            )
            results.append(
                {
                    "ordinal": ordinal,
                    "work_key": spec.work_key,
                    "title": spec.title,
                    "import_job_id": admitted["import_job_id"],
                    "discovery_operation_id": admitted["operation_id"],
                    "discovery_recovery_mode": discovery.get("recovery_mode", ""),
                    "work_operation_id": work_operation_id,
                    "work_recovery_mode": materialized.get("recovery_mode", ""),
                    "analysis_override_contract_hash": (
                        analysis_overrides[spec.work_key].contract_hash
                        if spec.work_key in analysis_overrides
                        else ""
                    ),
                    "source_work_asset_version_id": manifest["asset_version_id"],
                    "manifest_hash": manifest["manifest_hash"],
                    "unit_count": manifest["unit_count"],
                    "body_unit_count": manifest["body_unit_count"],
                    "character_count": manifest["character_count"],
                    "chunk_count": manifest["chunk_count"],
                    "repository_commit_sha": manifest["repository_commit_sha"],
                    "parser_profile": manifest["parser_profile"],
                    "job_status": job["status"],
                    "effective_status": job["effective_status"],
                    "work_counts": job["work_counts"],
                    "work_kind_counts": job["work_kind_counts"],
                }
            )
        except Exception as exc:
            failures.append(
                {
                    "ordinal": str(ordinal),
                    "work_key": spec.work_key,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            if args.fail_fast:
                raise
    model_effects_after = _model_effect_count(settings.database_url, args.project_id)
    report = {
        "schema_version": "classical-corpus-native-import-run.v1",
        "run_mode": "MATERIALIZE_ONLY",
        "run_label": args.run_label,
        "project_id": args.project_id,
        "workspace_id": args.workspace_id,
        "application_build_id": build_id,
        "commit_sha": commit_sha,
        "registry_id": registry["registry_id"],
        "registry_hash": canonical_hash(registry),
        "analysis_override_manifest": analysis_override_manifest,
        "project_operation": project,
        "requested_work_count": len(selected_keys),
        "materialized_work_count": len(results),
        "failed_work_count": len(failures),
        "provider_model_effect_count_before": model_effects_before,
        "provider_model_effect_count_after": model_effects_after,
        "provider_model_calls_performed_by_run": (
            model_effects_after - model_effects_before
        ),
        "works": results,
        "failures": failures,
        "proof_scope": {
            "proves": [
                "production-source-import-discovery",
                "native-source-work-materialization",
                "postgresql-source-work-and-unit-authority",
                "object-store-raw-and-normalized-boundary",
            ],
            "does_not_establish": [
                "model-classification",
                "model-deconstruction",
                "knowledge-approval",
                "creative-consumption",
            ],
        },
    }
    report["run_hash"] = canonical_hash(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--actor-id", default="operator:classical-corpus-validation")
    parser.add_argument("--work-key", action="append")
    parser.add_argument("--run-label", default="native-import")
    parser.add_argument("--analysis-override-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()
    if (
        not args.run_label.strip()
        or len(args.run_label) > 96
        or any(character.isspace() for character in args.run_label)
    ):
        parser.error("--run-label must be a non-empty, whitespace-free identity")
    report = _materialize(args)
    _write_json(args.output, report)
    print(json.dumps(_jsonable(report), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not report["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
