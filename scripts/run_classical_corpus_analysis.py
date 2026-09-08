#!/usr/bin/env python3
"""Run governed corpus intelligence work through the production SourceImport chain."""

from __future__ import annotations

import argparse
from datetime import date, datetime
from decimal import Decimal
import json
import os
from pathlib import Path
from typing import Any, Mapping

from novel_forge.api.authority_dependencies import (
    authority_release_identity,
    build_production_execution_composition,
    build_source_import_application,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.mkaos_authority import (
    ApproveKnowledgeCandidateCommand,
    ExperimentalKnowledgeApprovalPolicy,
    MkaosAuthorityApplication,
)
from novel_forge.modules.source_import import (
    SourceImportQuery,
    SourceImportScheduler,
    SourceMethodologyRegistry,
)
from novel_forge.modules.source_import.analysis_profiles import (
    resolve_corpus_analysis_strategy,
)
from novel_forge.modules.source_import.classical_corpus import (
    canonical_hash,
    load_corpus_registry,
    resolve_work_spec,
)
from novel_forge.modules.source_import.profiling import SourceContentType
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.migrations import run_migrations


ROOT = Path(__file__).resolve().parents[1]
SOURCE_MODEL_CAPABILITIES = (
    "source.content.classify",
    "deconstruction.observe",
    "mkaos.knowledge.extract",
    "mkaos.rule.extract",
    "mkaos.template.extract",
)
SOURCE_MODEL_WORK_KINDS = frozenset(
    {"PROFILING", "DECONSTRUCTION", "MKAOS_EXTRACTION"}
)
SOURCE_APPLICATION_CALL_LIMIT = 180
SOURCE_REPAIR_RESERVE = 14


def _jsonable(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    destination = path.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(_jsonable(value), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def _build_budget_plan(
    registry: Mapping[str, Any],
    *,
    selected_work_keys: tuple[str, ...],
    model_context_limit: int,
    output_token_reserve: int,
) -> dict[str, Any]:
    methodology = SourceMethodologyRegistry(ROOT / "skills")
    selected = set(selected_work_keys)
    works: list[dict[str, Any]] = []
    for row in registry["works"]:
        spec = resolve_work_spec(str(row["work_key"]), registry=dict(registry))
        strategy = resolve_corpus_analysis_strategy(
            SourceContentType.CLASSIC_LITERATURE,
            collection_kind=spec.collection_kind,
            registry=methodology,
            routing_policy_version="source-analysis-routing.v2",
        )
        model_calls = 2 + len(strategy.analyzers)
        works.append(
            {
                "work_key": spec.work_key,
                "title": spec.title,
                "collection_kind": spec.collection_kind,
                "dimension_count": len(strategy.analyzers),
                "normal_application_calls": model_calls,
                "selected_for_this_run": spec.work_key in selected,
            }
        )
    normal_calls = sum(int(item["normal_application_calls"]) for item in works)
    selected_calls = sum(
        int(item["normal_application_calls"])
        for item in works
        if item["selected_for_this_run"]
    )
    total_with_repairs = normal_calls + SOURCE_REPAIR_RESERVE
    if total_with_repairs != SOURCE_APPLICATION_CALL_LIMIT:
        raise RuntimeError(
            "frozen source call DAG no longer fits the approved 180-call envelope"
        )
    if model_context_limit <= 0 or output_token_reserve <= 0:
        raise RuntimeError("source token admission limits must be positive")
    return {
        "schema_version": "classical-corpus-analysis-budget.v1",
        "normal_application_calls": normal_calls,
        "repair_application_call_reserve": SOURCE_REPAIR_RESERVE,
        "maximum_application_calls": SOURCE_APPLICATION_CALL_LIMIT,
        "selected_normal_application_calls": selected_calls,
        "application_visible_input_upper_bound_per_call": model_context_limit,
        "provider_output_token_reserve_per_call": output_token_reserve,
        "project_token_limit": SOURCE_APPLICATION_CALL_LIMIT
        * model_context_limit,
        "token_control_scope": (
            "APPLICATION_VISIBLE_UTF8_BYTE_UPPER_BOUND; terminal measured usage is "
            "post-call and does not prove an exact pre-call remote token limit"
        ),
        "maximum_concurrency": 2,
        "runner_concurrency": 1,
        "works": works,
    }


def _operation_rows(
    database_url: str, *, project_id: str, import_job_id: str
) -> list[dict[str, Any]]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT operation.operation_id, operation.definition_name,
                   operation.status, work.work_kind, work.status,
                   work.result, work.failure, operation.created_at
            FROM authority_source_import_work AS work
            JOIN authority_operation AS operation
              ON operation.operation_id=work.operation_id
            WHERE work.project_id=%s AND work.import_job_id=%s
            ORDER BY operation.created_at, operation.operation_id
            """,
            [project_id, import_job_id],
        )
        rows = uow.cursor.fetchall()
    keys = (
        "operation_id",
        "definition_name",
        "operation_status",
        "work_kind",
        "work_status",
        "result",
        "failure",
        "created_at",
    )
    return [dict(zip(keys, row, strict=True)) for row in rows]


def _model_effect_summary(database_url: str, *, project_id: str) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT capability, status, COUNT(*)
            FROM authority_external_effect
            WHERE project_id=%s AND capability=ANY(%s)
            GROUP BY capability, status
            ORDER BY capability, status
            """,
            [project_id, list(SOURCE_MODEL_CAPABILITIES)],
        )
        rows = uow.cursor.fetchall()
        uow.cursor.execute(
            """
            SELECT COUNT(*),
                   COALESCE(SUM(reservation.actual_tokens), 0),
                   COUNT(*) FILTER (
                     WHERE reservation.accounting_basis='ACCOUNT_ENTITLEMENT'
                       AND reservation.settled_cost_status='UNKNOWN'
                   )
            FROM authority_budget_reservation AS reservation
            JOIN authority_external_effect AS effect
              ON effect.external_effect_id=reservation.external_effect_id
             AND effect.project_id=reservation.project_id
            WHERE reservation.project_id=%s
              AND effect.capability=ANY(%s)
            """,
            [project_id, list(SOURCE_MODEL_CAPABILITIES)],
        )
        budget_row = uow.cursor.fetchone()
    by_capability = [
        {"capability": str(row[0]), "status": str(row[1]), "count": int(row[2])}
        for row in rows
    ]
    return {
        "application_effect_count": sum(int(row["count"]) for row in by_capability),
        "by_capability_and_status": by_capability,
        "budget_reservation_count": int(budget_row[0]),
        "measured_actual_tokens": int(budget_row[1]),
        "unknown_monetary_cost_reservation_count": int(budget_row[2]),
    }


def _approve_candidates(
    *,
    database_url: str,
    project_id: str,
    workspace_id: str,
    import_job_id: str,
    reviewer_id: str,
    build_id: str,
    commit_sha: str,
) -> list[dict[str, Any]]:
    source_query = SourceImportQuery(database_url)
    candidate_ids = sorted(
        {
            str(dict(item["result"] or {}).get("candidate_asset_version_id") or "")
            for item in source_query.work(
                project_id=project_id, import_job_id=import_job_id
            )
            if str(item["work_kind"]) == "MKAOS_EXTRACTION"
            and str(item["status"]) in {"SUCCEEDED", "REUSED"}
            and dict(item["result"] or {}).get("candidate_asset_version_id")
        }
    )
    principal = Principal(
        principal_id=reviewer_id,
        principal_type=PrincipalType.LOCAL_OPERATOR,
        permissions=frozenset(
            {
                "mkaos.authority.execute",
                "mkaos.authority.approve",
                "mkaos.authority.query",
            }
        ),
        project_scope=frozenset({project_id}),
        authentication_source="explicit-experimental-corpus-policy",
    )
    authority = MkaosAuthorityApplication(
        database_url,
        application_build_id=build_id,
        commit_sha=commit_sha,
        worker_id="worker:classical-corpus-governance",
        allow_fixture_activation=False,
        experimental_approval_policy=ExperimentalKnowledgeApprovalPolicy(
            project_id=project_id,
            workspace_id=workspace_id,
            policy_version="classical-corpus-experimental-auto-review.v1",
            reviewer_id=reviewer_id,
        ),
    )
    approvals = []
    for candidate_id in candidate_ids:
        result = authority.execute_approval(
            ApproveKnowledgeCandidateCommand(
                project_id=project_id,
                workspace_id=workspace_id,
                candidate_asset_version_id=candidate_id,
                policy_version="classical-corpus-experimental-auto-review.v1",
                rationale=(
                    "EXPERIMENTAL_POLICY_APPROVAL_NOT_HUMAN: candidate passed "
                    "production execution, evidence, abstraction, and anti-copy gates; "
                    "approval is limited to the isolated local validation project."
                ),
                actor_id=reviewer_id,
                idempotency_key=f"classical-corpus:experimental-approve:{candidate_id}",
                trace_id=f"trace:classical-corpus:approve:{candidate_id}",
                correlation_id=f"correlation:classical-corpus:{project_id}",
                approval_class="EXPERIMENTAL_VALIDATION",
            ),
            principal=principal,
        )
        approvals.append(
            {
                "candidate_asset_version_id": candidate_id,
                "knowledge_card_asset_version_id": result["asset_version_id"],
                "approval_operation_id": result["operation_id"],
                "replayed": bool(result.get("replayed")),
                "review_class": "EXPERIMENTAL_POLICY_APPROVAL_NOT_HUMAN",
            }
        )
    return approvals


def _load_native_report(
    path: Path, *, project_id: str, workspace_id: str
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if (
        report.get("schema_version") != "classical-corpus-native-import-run.v1"
        or report.get("project_id") != project_id
        or report.get("workspace_id") != workspace_id
        or int(report.get("materialized_work_count", 0)) != 20
        or int(report.get("failed_work_count", -1)) != 0
    ):
        raise RuntimeError("native import report is not a complete matching 20-work run")
    works = {str(item["work_key"]): dict(item) for item in report["works"]}
    if len(works) != 20:
        raise RuntimeError("native import report work identities are incomplete")
    return report, works


def _run(args: argparse.Namespace) -> dict[str, Any]:
    settings = IndustrialSettings.from_env(root=ROOT)
    if not settings.database_url:
        raise RuntimeError("NOVEL_FORGE_DATABASE_URL is required")
    migration = run_migrations(settings.database_url)
    if not migration["ok"]:
        raise RuntimeError(f"migrations incomplete: {migration}")
    native_report, imported_works = _load_native_report(
        args.native_import_report,
        project_id=args.project_id,
        workspace_id=args.workspace_id,
    )
    registry = load_corpus_registry()
    selected_keys = tuple(
        args.work_key or [str(item["work_key"]) for item in registry["works"]]
    )
    if len(set(selected_keys)) != len(selected_keys):
        raise RuntimeError("work selections must be unique")
    unknown = sorted(set(selected_keys) - set(imported_works))
    if unknown:
        raise RuntimeError("unknown or unimported work keys: " + ", ".join(unknown))
    context_limit = int(os.environ.get("NOVEL_FORGE_PROVIDER_MODEL_CONTEXT_LIMIT") or 0)
    output_reserve = int(
        os.environ.get("NOVEL_FORGE_SOURCE_PROVIDER_OUTPUT_TOKEN_RESERVE") or 4096
    )
    budget = _build_budget_plan(
        registry,
        selected_work_keys=selected_keys,
        model_context_limit=context_limit,
        output_token_reserve=output_reserve,
    )
    environment_limit = int(
        os.environ.get("NOVEL_FORGE_PROJECT_PROVIDER_CALL_LIMIT") or 0
    )
    if (
        args.max_application_calls != SOURCE_APPLICATION_CALL_LIMIT
        or environment_limit != SOURCE_APPLICATION_CALL_LIMIT
    ):
        raise RuntimeError("source execution requires the frozen 180-call project cap")
    build_id, commit_sha = authority_release_identity()
    execution = build_production_execution_composition(settings)
    application = build_source_import_application(settings, execution=execution)
    scheduler = SourceImportScheduler(
        application,
        worker_id=str(
            os.environ.get("NOVEL_FORGE_SOURCE_IMPORT_WORKER_ID")
            or "worker:classical-corpus-source"
        ),
        lease_seconds=int(os.environ.get("NOVEL_FORGE_AUTHORITY_LEASE_SECONDS") or 60),
    )
    query = SourceImportQuery(settings.database_url)
    before = _model_effect_summary(settings.database_url, project_id=args.project_id)
    report: dict[str, Any] = {
        "schema_version": "classical-corpus-analysis-run.v1",
        "status": "RUNNING",
        "project_id": args.project_id,
        "workspace_id": args.workspace_id,
        "application_build_id": build_id,
        "commit_sha": commit_sha,
        "registry_id": registry["registry_id"],
        "registry_hash": canonical_hash(registry),
        "native_import_run_hash": native_report["run_hash"],
        "selected_work_keys": list(selected_keys),
        "budget": budget,
        "model_effects_before": before,
        "works": [],
        "failure": {},
        "governance": {
            "mode": (
                "EXPERIMENTAL_POLICY_APPROVAL_NOT_HUMAN"
                if args.approve_experimental
                else "CANDIDATE_ONLY"
            ),
            "human_editorial": "NOT_RUN",
        },
    }
    _write_json(args.output, report)
    try:
        for work_key in selected_keys:
            imported = imported_works[work_key]
            import_job_id = str(imported["import_job_id"])
            work_result: dict[str, Any] = {
                "work_key": work_key,
                "title": imported["title"],
                "import_job_id": import_job_id,
                "executions": [],
                "approvals": [],
            }
            report["works"].append(work_result)
            for _cycle in range(40):
                rows = _operation_rows(
                    settings.database_url,
                    project_id=args.project_id,
                    import_job_id=import_job_id,
                )
                pending = {
                    operation_id
                    for operation_id, project_id in scheduler.pending_operations(
                        limit=500
                    )
                    if project_id == args.project_id
                }
                runnable = [
                    item
                    for item in rows
                    if str(item["operation_id"]) in pending
                    and str(item["work_kind"])
                    in {
                        "PROFILING",
                        "ANALYSIS_PLANNING",
                        "DECONSTRUCTION",
                        "MKAOS_EXTRACTION",
                    }
                ]
                if not runnable:
                    break
                item = runnable[0]
                current_effects = _model_effect_summary(
                    settings.database_url, project_id=args.project_id
                )
                if (
                    str(item["work_kind"]) in SOURCE_MODEL_WORK_KINDS
                    and int(current_effects["application_effect_count"])
                    >= args.max_application_calls
                ):
                    raise RuntimeError("SOURCE_APPLICATION_CALL_LIMIT_EXHAUSTED")
                result = scheduler.run_or_recover(
                    operation_id=str(item["operation_id"]),
                    project_id=args.project_id,
                )
                work_result["executions"].append(
                    {
                        "operation_id": item["operation_id"],
                        "definition_name": item["definition_name"],
                        "work_kind": item["work_kind"],
                        "attempt_id": result.get("attempt_id", ""),
                        "attempt_number": result.get("attempt_number", 0),
                        "recovery_mode": result.get("recovery_mode", ""),
                        "status": result.get("status", "SUCCEEDED"),
                    }
                )
                report["model_effects_current"] = _model_effect_summary(
                    settings.database_url, project_id=args.project_id
                )
                _write_json(args.output, report)
            else:
                raise RuntimeError("source analysis work did not quiesce within 40 steps")
            final_rows = _operation_rows(
                settings.database_url,
                project_id=args.project_id,
                import_job_id=import_job_id,
            )
            incomplete = [
                item
                for item in final_rows
                if str(item["work_kind"])
                in {
                    "PROFILING",
                    "ANALYSIS_PLANNING",
                    "DECONSTRUCTION",
                    "MKAOS_EXTRACTION",
                }
                and str(item["work_status"])
                not in {"SUCCEEDED", "REUSED"}
            ]
            if incomplete:
                work_result["incomplete_operations"] = _jsonable(incomplete)
                raise RuntimeError(
                    f"source analysis stopped with incomplete work for {work_key}"
                )
            if args.approve_experimental:
                work_result["approvals"] = _approve_candidates(
                    database_url=settings.database_url,
                    project_id=args.project_id,
                    workspace_id=args.workspace_id,
                    import_job_id=import_job_id,
                    reviewer_id=args.reviewer_id,
                    build_id=build_id,
                    commit_sha=commit_sha,
                )
            work_result["downstream"] = query.downstream_status(
                project_id=args.project_id,
                import_job_id=import_job_id,
            )
            work_result["final_job_status"] = query.import_job(
                project_id=args.project_id,
                import_job_id=import_job_id,
            )["effective_status"]
            _write_json(args.output, report)
    except BaseException as exc:
        report["status"] = "INTERRUPTED" if isinstance(
            exc, (KeyboardInterrupt, SystemExit)
        ) else "BLOCKED"
        report["failure"] = {
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        report["model_effects_after"] = _model_effect_summary(
            settings.database_url, project_id=args.project_id
        )
        report["run_hash"] = canonical_hash(report)
        _write_json(args.output, report)
        raise
    report["status"] = "SUCCEEDED"
    report["model_effects_after"] = _model_effect_summary(
        settings.database_url, project_id=args.project_id
    )
    report["model_application_calls_performed_by_run"] = (
        int(report["model_effects_after"]["application_effect_count"])
        - int(before["application_effect_count"])
    )
    report["run_hash"] = canonical_hash(report)
    _write_json(args.output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--native-import-report", type=Path, required=True)
    parser.add_argument("--work-key", action="append")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--max-application-calls", type=int, default=SOURCE_APPLICATION_CALL_LIMIT
    )
    parser.add_argument("--approve-experimental", action="store_true")
    parser.add_argument(
        "--reviewer-id", default="operator:classical-corpus-experimental-policy"
    )
    args = parser.parse_args()
    report = _run(args)
    print(json.dumps(_jsonable(report), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
