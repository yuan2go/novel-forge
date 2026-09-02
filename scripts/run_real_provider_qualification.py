#!/usr/bin/env python3
"""Run one exact-SHA real Provider qualification through PostgreSQL Authority."""

from __future__ import annotations

import argparse
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.api.authority_dependencies import (
    build_chapter_authority_application,
    build_production_execution_composition,
)
from novel_forge.infrastructure.production_execution_composition import (
    ProductionExecutionComposition,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapterError,
)
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.book_design_authority import (
    BookDesignAuthorityApplication,
    BookDesignAuthorityCommand,
)
from novel_forge.modules.book_authority import (
    PostgresBookAuthority,
    StartBookProductionCommand,
)
from novel_forge.modules.chapter_authority.definitions import (
    chapter_operation_definitions,
    chapter_root_operation_definition,
)
from novel_forge.modules.agent_runtime.definitions import (
    agent_runtime_operation_definitions,
)
from novel_forge.modules.provider_qualification import (
    D0LiveQualificationEvidence,
    D0ProbeConfig,
    D0QualificationAuthority,
    D0QualificationCommand,
)
from novel_forge.modules.provider_qualification.domain import request_hash
from novel_forge.modules.project_authority import (
    ProjectAuthorityApplication,
    ProjectAuthorityCommand,
)
from novel_forge.modules.production_execution.security import (
    assert_no_inline_secrets,
    redact_secret_text,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.migrations import run_migrations
from novel_forge.storage.object_store import MinioObjectStore
from novel_forge.tools.implementation_tree_identity import (
    build_implementation_tree_identity,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config/provider/d0-codex-cli-probe.json"
PROOF_SCOPE = {
    "schema_version": "novel-forge.qualification-proof-scope.v1",
    "fact_type": "CURRENT_QUALIFICATION_EVIDENCE",
    "proves": ["external-effect-provider-control"],
    "ceiling": "REAL_PROVIDER_RUNTIME",
    "does_not_establish": [
        "CHAPTER_ACCEPTED_ACTUAL",
        "HUMAN_EDITORIAL_EVIDENCE",
        "LONGITUDINAL_NARRATIVE_STABILITY",
        "PRODUCTION_OPERATION",
    ],
}


class SimulatedProviderResponseLoss(ExternalEffectAdapterError):
    pass


class OneShotAmbiguousResponseGateway:
    """INVARIANT: only the response is lost; the delegated Provider result stays durable."""

    production_execution_gateway_backed = True

    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate
        self.triggered = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)

    def execute(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> Any:
        result = self.delegate.execute(
            stable_idempotency_key=stable_idempotency_key,
            capability=capability,
            request_payload=request_payload,
        )
        if not self.triggered:
            self.triggered = True
            raise SimulatedProviderResponseLoss(
                "qualification injected response loss after Provider completion",
                request_sent=True,
                failure_kind="response_loss",
            )
        return result


class _UnusedPort:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"qualification unexpectedly used port method {name}")


def _git(*args: str) -> str:
    return subprocess.run(
        ("git", *args),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _hash(value: Mapping[str, Any]) -> str:
    return request_hash(value)


def _jsonable(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, set):
        return sorted(_jsonable(item) for item in value)
    return value


def _principal(identity: str, project_id: str, *permissions: str) -> Principal:
    return Principal(
        principal_id=identity,
        principal_type=PrincipalType.LOCAL_OPERATOR,
        permissions=frozenset(permissions),
        project_scope=frozenset({project_id}),
        authentication_source="real-provider-qualification",
    )


def _seed_project_and_book(
    database_url: str,
    *,
    project_id: str,
    workspace_id: str,
    book_id: str,
    build_id: str,
    commit_sha: str,
    principal: Principal,
) -> None:
    ProjectAuthorityApplication(
        database_url,
        application_build_id=build_id,
        commit_sha=commit_sha,
    ).execute(
        ProjectAuthorityCommand(
            definition_name="project_lifecycle.create",
            project_id=project_id,
            workspace_id=workspace_id,
            actor_id=principal.principal_id,
            idempotency_key=f"project:create:{project_id}",
            trace_id=f"trace:{project_id}",
            correlation_id=f"correlation:{project_id}",
            payload={"title": "Provider qualification", "stage": "PRODUCTION"},
        ),
        principal=principal,
    )
    BookDesignAuthorityApplication(
        database_url,
        application_build_id=build_id,
        commit_sha=commit_sha,
    ).execute(
        BookDesignAuthorityCommand(
            definition_name="book.create",
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            actor_id=principal.principal_id,
            service_identity="real-provider-qualification",
            idempotency_key=f"book:create:{book_id}",
            trace_id=f"trace:{project_id}",
            correlation_id=f"correlation:{project_id}",
            payload={
                "schema_version": "book-authority.v1",
                "title": "Provider qualification",
                "production_profile": {
                    "environment": "validation",
                    "provider": "codex-cli",
                },
                "runtime_policy": {
                    "legacy_write": False,
                    "silent_fallback": False,
                },
                "release_identity": f"{build_id}@{commit_sha}",
            },
        ),
        principal=principal,
    )


def _seed_book_run(
    database_url: str,
    *,
    project_id: str,
    workspace_id: str,
    book_id: str,
    actor: Principal,
    build_id: str,
    commit_sha: str,
) -> Any:
    types = {
        "book_design_version": "book_design",
        "book_plan_version": "book_plan",
        "volume_plan_version": "volume_plan",
        "arc_plan_versions": "arc_plan",
        "character_state_version": "character_state",
        "foreshadowing_state_version": "foreshadowing_state",
        "quality_trend_version": "quality_trend",
        "reward_ledger_version": "reward_ledger",
        "promise_ledger_version": "reader_promise_ledger",
        "reader_segment_version": "reader_segment_profile",
        "reader_contract_version": "reader_contract",
        "platform_profile_version": "platform_profile",
    }
    versions: dict[str, Any] = {}
    with AuthorityUnitOfWork(database_url) as uow:
        for key, asset_type in types.items():
            version_id = f"{project_id}:{asset_type}:qualification-v1"
            asset_id = f"asset:{version_id}"
            content = {
                "contract_version": f"{asset_type}-qualification-fixture-v1",
                "safe_summary": f"Frozen {asset_type} qualification fixture.",
                "evidence_class": "FIXTURE_ONLY_NOT_PROVIDER_OR_CHAPTER_PROOF",
            }
            content_hash = _hash(content)
            uow.cursor.execute(
                "INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,%s)",
                [asset_id, project_id, asset_type],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id,asset_id,version_number,lifecycle,
                    eligibility,governance,content,content_hash,schema_version
                ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,
                          'qualification-fixture.v1')
                """,
                [version_id, asset_id, Jsonb(content), content_hash],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_qualification(
                    qualification_id,asset_version_id,policy_version,
                    decision,evidence
                ) VALUES (%s,%s,'real-provider-input-fixture-v1','ELIGIBLE',%s)
                """,
                [
                    f"qualification:{version_id}",
                    version_id,
                    Jsonb({"fixture_only": True, "provider_evidence": False}),
                ],
            )
            versions[key] = [version_id] if key == "arc_plan_versions" else version_id
        uow.commit()
    return PostgresBookAuthority(
        database_url,
        chapter_port=_UnusedPort(),  # type: ignore[arg-type]
        followup_application=_UnusedPort(),  # type: ignore[arg-type]
        application_build_id=build_id,
        commit_sha=commit_sha,
        legacy_fixture_input_allowed=True,
    ).start(
        StartBookProductionCommand(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            actor_id=actor.principal_id,
            trace_id=f"trace:{project_id}:book",
            correlation_id=f"correlation:{project_id}",
            stable_idempotency_key=f"{project_id}:provider-qualification-book",
            book_design_version=str(versions.pop("book_design_version")),
            book_plan_version=str(versions.pop("book_plan_version")),
            production_profile_version=str(versions["platform_profile_version"]),
            longform_context_versions=versions,
            target_chapter_count=1,
            input_mode="LEGACY_FIXTURE_INPUT_MODE",
        ),
        principal=actor,
    )


def _register_operation_definitions(
    database_url: str, *, build_id: str, commit_sha: str
) -> None:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.repositories.definitions.register(
            chapter_root_operation_definition(
                application_build_id=build_id,
                commit_sha=commit_sha,
                model_effects_required=True,
            )
        )
        for definition in chapter_operation_definitions(
            application_build_id=build_id,
            commit_sha=commit_sha,
            model_effects_required=True,
            semantic_retrieval_available=True,
        ):
            uow.repositories.definitions.register(definition)
        for definition in agent_runtime_operation_definitions(
            application_build_id=build_id,
            commit_sha=commit_sha,
        ):
            uow.repositories.definitions.register(definition)
        uow.commit()


def _seed_accepted_retrieval_document(
    database_url: str,
    *,
    project_id: str,
    book_id: str,
    source_operation_id: str,
) -> tuple[str, str]:
    document_id = f"retrieval-document:{project_id}:accepted-input"
    asset_version_id = f"asset-version:{project_id}:accepted-input"
    content = {
        "type": "accepted_passage",
        "chapter": 0,
        "text": "A sealed municipal ledger records one witness under two incompatible statuses.",
        "accepted_boundary": 0,
        "evidence_class": "QUALIFICATION_FIXTURE_ACCEPTED_INPUT",
    }
    content_hash = _hash(content)
    projection_payload = {
        "retrieval_document_id": document_id,
        "source_asset_version_id": asset_version_id,
        "source_content_hash": content_hash,
        "accepted_from_chapter": 0,
        "content_text": content["text"],
        "memory_layer": "L0",
    }
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            "INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,%s)",
            [f"asset:{asset_version_id}", project_id, "best_draft_candidate"],
        )
        uow.cursor.execute(
            """
            INSERT INTO authority_asset_version(
                asset_version_id,asset_id,version_number,lifecycle,eligibility,
                governance,content,content_hash,schema_version
            ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,
                      'accepted-passage-qualification.v1')
            """,
            [
                asset_version_id,
                f"asset:{asset_version_id}",
                Jsonb(content),
                content_hash,
            ],
        )
        uow.cursor.execute(
            """
            INSERT INTO authority_narrative_retrieval_document(
                retrieval_document_id,project_id,book_id,
                source_asset_version_id,source_artifact_type,
                accepted_from_chapter,memory_layer,content_text,
                temporal_coordinate,metadata,projection_hash,
                created_by_operation_id
            ) VALUES (%s,%s,%s,%s,'best_draft_candidate',0,'L0',%s,%s,%s,%s,%s)
            """,
            [
                document_id,
                project_id,
                book_id,
                asset_version_id,
                content["text"],
                Jsonb({"accepted_chapter": 0}),
                Jsonb({"fixture_only": True, "provider_evidence": False}),
                _hash(projection_payload),
                source_operation_id,
            ],
        )
        uow.commit()
    return document_id, asset_version_id


def _outside_repository(path: Path) -> bool:
    try:
        path.relative_to(ROOT)
    except ValueError:
        return True
    return False


def _runtime_environment(
    *,
    commit_sha: str,
    codex_executable: str,
    runtime_root: Path,
    model: str,
    reasoning_effort: str,
) -> dict[str, str]:
    workspace = runtime_root / "isolated-codex-workspace"
    executions = runtime_root / "codex-executions"
    objects = runtime_root / "object-store-locators"
    workspace.mkdir(parents=True, exist_ok=False)
    executions.mkdir(parents=True, exist_ok=True)
    objects.mkdir(parents=True, exist_ok=True)
    return {
        "NOVEL_FORGE_ENVIRONMENT": "validation",
        "NOVEL_FORGE_APPLICATION_BUILD_ID": "real-provider-qualification",
        "NOVEL_FORGE_COMMIT_SHA": commit_sha,
        "NOVEL_FORGE_RELEASE_CHANNEL": "VALIDATION",
        "NOVEL_FORGE_MODEL_PROVIDER": "codex-cli",
        "NOVEL_FORGE_PLANNING_PROVIDER": "codex-cli",
        "NOVEL_FORGE_PLANNING_MODEL": model,
        "NOVEL_FORGE_PLANNING_REASONING_EFFORT": reasoning_effort,
        "NOVEL_FORGE_DRAFT_MODEL": model,
        "NOVEL_FORGE_REVIEW_MODEL": model,
        "NOVEL_FORGE_REVISION_MODEL": model,
        "NOVEL_FORGE_REREVIEW_MODEL": model,
        "NOVEL_FORGE_CANON_EXTRACTION_MODEL": model,
        "NOVEL_FORGE_QUALITY_MODEL": model,
        "NOVEL_FORGE_READER_OUTCOME_MODEL": model,
        "NOVEL_FORGE_REASONING_EFFORT": reasoning_effort,
        "NOVEL_FORGE_PROVIDER_AUTH_PROFILE": "auth:chatgpt-codex-cli",
        "NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID": "chapter_generation_pack",
        "NOVEL_FORGE_AUTHORITY_WORKER_ID": "provider-qualification-worker:initial",
        "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_BACKEND": "minio",
        "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(objects),
        "NOVEL_FORGE_CODEX_EXECUTABLE": codex_executable,
        "NOVEL_FORGE_CODEX_WORKSPACE": str(workspace),
        "NOVEL_FORGE_CODEX_EXECUTION_ROOT": str(executions),
        "NOVEL_FORGE_PROVIDER_MAX_COST_PER_CALL": "2.00",
        "NOVEL_FORGE_PROJECT_DAILY_PROVIDER_CAP": "30.00",
        "NOVEL_FORGE_OPERATION_PROVIDER_CAP": "5.00",
        "NOVEL_FORGE_PROVIDER_DAILY_CAP": "30.00",
        "NOVEL_FORGE_DAILY_PROVIDER_CAP": "30.00",
        "NOVEL_FORGE_CHAPTER_PROVIDER_CAP": "20.00",
        "NOVEL_FORGE_CODEX_PRICING_REF": (
            "proof-estimate:gpt-5.6-sol:2026-08-09:not-provider-billing"
        ),
        "NOVEL_FORGE_CODEX_PRICING_CURRENCY": "USD",
        "NOVEL_FORGE_CODEX_INPUT_PER_MILLION": "2.50",
        "NOVEL_FORGE_CODEX_CACHED_INPUT_PER_MILLION": "0.25",
        "NOVEL_FORGE_CODEX_OUTPUT_PER_MILLION": "15.00",
        "NOVEL_FORGE_EMBEDDING_PROVIDER": "codex-cli",
        "NOVEL_FORGE_EMBEDDING_MODEL": model,
        "NOVEL_FORGE_EMBEDDING_DIMENSIONS": "8",
        "NOVEL_FORGE_NARRATIVE_EVALUATOR_PROVIDER": "codex-cli",
        "NOVEL_FORGE_NARRATIVE_EVALUATOR_MODEL": model,
        "NOVEL_FORGE_NARRATIVE_SEMANTIC_EVALUATION_REASONING_EFFORT": (
            reasoning_effort
        ),
        "NOVEL_FORGE_D0_MODEL": model,
        "NOVEL_FORGE_D0_MODEL_VERSION": "provider-not-reported",
    }


def _effect_evidence(
    database_url: str, *, operation_id: str
) -> tuple[dict[str, Any], dict[str, Any], int, int, int, dict[str, Any]]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT effect.external_effect_id,effect.request_hash,
                   effect.request_payload,effect.status,
                   COUNT(DISTINCT dispatch.dispatch_id)::int,
                   COUNT(DISTINCT receipt.external_receipt_id)::int
            FROM authority_external_effect AS effect
            JOIN authority_external_effect_dispatch AS dispatch
              ON dispatch.external_effect_id=effect.external_effect_id
            LEFT JOIN authority_external_receipt AS receipt
              ON receipt.dispatch_id=dispatch.dispatch_id
            WHERE effect.operation_id=%s AND effect.capability='model.retrieval'
            GROUP BY effect.external_effect_id,effect.request_hash,
                     effect.request_payload,effect.status
            """,
            [operation_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise RuntimeError("qualification has no retrieval Provider effect")
        uow.cursor.execute(
            """
            SELECT payload
            FROM authority_external_receipt AS receipt
            JOIN authority_external_effect_dispatch AS dispatch
              ON dispatch.dispatch_id=receipt.dispatch_id
            WHERE dispatch.external_effect_id=%s
            ORDER BY receipt.received_at DESC LIMIT 1
            """,
            [row[0]],
        )
        receipt_row = uow.cursor.fetchone()
        uow.cursor.execute(
            """
            SELECT COUNT(*)::int
            FROM authority_effect_reconciliation_evidence
            WHERE external_effect_id=%s AND outcome='success'
            """,
            [row[0]],
        )
        reconciliation_count = int(uow.cursor.fetchone()[0])
        uow.cursor.execute(
            """
            SELECT outcome,evidence,trace_id,correlation_id,reconciled_at
            FROM authority_effect_reconciliation_evidence
            WHERE external_effect_id=%s AND outcome='success'
            ORDER BY reconciled_at DESC LIMIT 1
            """,
            [row[0]],
        )
        reconciliation_row = uow.cursor.fetchone()
    if str(row[3]) != "SUCCEEDED" or receipt_row is None:
        raise RuntimeError("qualification Provider effect did not converge")
    if reconciliation_row is None:
        raise RuntimeError("qualification Provider effect has no recovery evidence")
    receipt_payload = dict(receipt_row[0] or {})
    provider_evidence = dict(receipt_payload.get("evidence") or {})
    return (
        {
            "external_effect_id": str(row[0]),
            "request_hash": str(row[1]),
            "request_payload": dict(row[2] or {}),
        },
        provider_evidence,
        int(row[4]),
        int(row[5]),
        reconciliation_count,
        {
            "outcome": str(reconciliation_row[0]),
            "evidence": dict(reconciliation_row[1] or {}),
            "trace_id": str(reconciliation_row[2]),
            "correlation_id": str(reconciliation_row[3]),
            "reconciled_at": reconciliation_row[4].isoformat(),
        },
    )


def _duration_ms(execution_result: Mapping[str, Any]) -> int:
    started = datetime.fromisoformat(str(execution_result["started_at"]))
    completed = datetime.fromisoformat(str(execution_result["completed_at"]))
    return max(1, int((completed - started).total_seconds() * 1000))


def _provider_process_evidence(
    runtime_root: Path, *, execution_id: str
) -> dict[str, Any]:
    receipts: list[dict[str, Any]] = []
    for path in sorted(
        runtime_root.glob("codex-executions/*/process-receipt.json")
    ):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if str(payload.get("execution_id") or "") == execution_id:
            assert_no_inline_secrets(
                payload, label="real Provider process receipt"
            )
            receipts.append(dict(payload))
    if len(receipts) != 1:
        raise RuntimeError(
            "real Provider execution must have exactly one process receipt; "
            f"observed {len(receipts)}"
        )
    receipt = receipts[0]
    forbidden_environment_keys = {
        "OPENAI_API_KEY",
        "NOVEL_FORGE_DATABASE_URL",
        "NOVEL_FORGE_MINIO_ACCESS_KEY",
        "NOVEL_FORGE_MINIO_SECRET_KEY",
    }
    environment_keys = {
        str(value) for value in receipt.get("environment_keys") or ()
    }
    leaked_environment_keys = sorted(
        environment_keys & forbidden_environment_keys
    )
    if leaked_environment_keys:
        raise RuntimeError(
            "real Provider process received credential environment keys: "
            + ", ".join(leaked_environment_keys)
        )
    log_evidence: dict[str, Any] = {}
    resolved_runtime_root = runtime_root.resolve()
    for label, key in (("stdout", "stdout_path"), ("stderr", "stderr_path")):
        log_path = Path(str(receipt.get(key) or "")).resolve()
        try:
            relative_path = log_path.relative_to(resolved_runtime_root)
        except ValueError as exc:
            raise RuntimeError(
                f"real Provider {label} log escaped the runtime root"
            ) from exc
        if not log_path.is_file():
            raise RuntimeError(f"real Provider {label} log is missing")
        raw_log = log_path.read_bytes()
        assert_no_inline_secrets(
            raw_log.decode("utf-8", errors="replace"),
            label=f"real Provider {label} log",
        )
        log_evidence[label] = {
            "relative_path": relative_path.as_posix(),
            "byte_count": len(raw_log),
            "sha256": "sha256:" + hashlib.sha256(raw_log).hexdigest(),
            "secret_scan": "PASS",
        }
    identity = {
        key: receipt.get(key)
        for key in (
            "receipt_id",
            "execution_id",
            "status",
            "transport",
            "provider_request_id",
            "request_digest",
            "command_sha256",
            "input_sha256",
            "result_integrity",
            "process_started_at",
            "completed_at",
            "elapsed_ms",
        )
    }
    identity["logs"] = log_evidence
    return {
        "process_receipt_count": len(receipts),
        "duplicate_provider_process_count": max(0, len(receipts) - 1),
        "process_receipt_identity_hash": request_hash(identity),
        "process_log_evidence": log_evidence,
        "credential_environment_keys_present": [],
    }


def _run(args: argparse.Namespace) -> dict[str, Any]:
    commit_sha = _git("rev-parse", "HEAD")
    if commit_sha != args.expected_sha:
        raise RuntimeError("qualification HEAD differs from --expected-sha")
    if _git("status", "--porcelain", "--untracked-files=normal"):
        raise RuntimeError("real Provider qualification requires a clean worktree")
    output = Path(args.output).expanduser().resolve()
    runtime_root = Path(args.runtime_root).expanduser().resolve()
    if not _outside_repository(output) or not _outside_repository(runtime_root):
        raise RuntimeError("live evidence and runtime state must stay outside the repository")
    if runtime_root.exists():
        raise RuntimeError("runtime root must not already exist")
    executable = str(Path(args.codex_executable).expanduser().resolve())
    if not Path(executable).is_file():
        raise RuntimeError("configured Codex executable does not exist")
    subprocess.run(
        (executable, "login", "status"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    identity = build_implementation_tree_identity(ROOT)
    env = _runtime_environment(
        commit_sha=commit_sha,
        codex_executable=executable,
        runtime_root=runtime_root,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
    )
    settings = IndustrialSettings(
        root=ROOT,
        environment="validation",
        storage_authority="postgresql",
        database_url=args.database_url,
        minio_endpoint=args.minio_endpoint,
        minio_access_key=args.minio_access_key,
        minio_secret_key=args.minio_secret_key,
        minio_secure=args.minio_secure,
    )
    migration = run_migrations(args.database_url)
    object_store = MinioObjectStore(settings)
    object_store.ensure_buckets()
    suffix = uuid4().hex[:12]
    project_id = f"real-provider:{commit_sha[:8]}:{suffix}"
    workspace_id = f"workspace:{project_id}"
    book_id = f"book:{project_id}"
    build_id = env["NOVEL_FORGE_APPLICATION_BUILD_ID"]
    operator = _principal(
        f"operator:{project_id}",
        project_id,
        "project.authority.execute",
        "book_design.authority.execute",
        "book.authority.execute",
        "content.authority.execute",
        "content.operation:chapter.plan.author",
        "content.operation:chapter.style_policy.author",
        "content.operation:chapter.quality_rubric.author",
        "content.operation:chapter.platform_profile.author",
        "content.operation:chapter.operator_checklist.author",
        "chapter.authority.execute",
        "provider.qualification.execute",
    )
    _seed_project_and_book(
        args.database_url,
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        build_id=build_id,
        commit_sha=commit_sha,
        principal=operator,
    )
    book = _seed_book_run(
        args.database_url,
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        actor=operator,
        build_id=build_id,
        commit_sha=commit_sha,
    )
    _register_operation_definitions(
        args.database_url, build_id=build_id, commit_sha=commit_sha
    )
    config = D0ProbeConfig.from_mapping(
        json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    )
    command = D0QualificationCommand(
        project_id=project_id,
        workspace_id=workspace_id,
        actor_id=operator.principal_id,
        idempotency_key=f"{project_id}:codex-cli:d0:v1",
        trace_id=f"trace:{project_id}:provider-qualification",
        correlation_id=f"correlation:{project_id}",
        config=config,
        resolved_model=env["NOVEL_FORGE_D0_MODEL"],
        resolved_model_version=env["NOVEL_FORGE_D0_MODEL_VERSION"],
        resolved_auth_profile_ref=env["NOVEL_FORGE_PROVIDER_AUTH_PROFILE"],
        implementation_identity=identity["implementation_tree_sha"],
    )
    qualification_authority = D0QualificationAuthority(
        args.database_url,
        evidence_store=object_store,
        application_build_id=build_id,
        commit_sha=commit_sha,
        implementation_identity=identity["implementation_tree_sha"],
        worker_id="provider-qualification-authority-worker",
    )
    qualification_operation_id = str(
        qualification_authority.admit(command)["operation_id"]
    )
    document_id, document_asset_version_id = _seed_accepted_retrieval_document(
        args.database_url,
        project_id=project_id,
        book_id=book_id,
        source_operation_id=book.root_operation_id,
    )
    initial_execution = build_production_execution_composition(settings, env=env)
    fault_gateway = OneShotAmbiguousResponseGateway(initial_execution.gateway)
    fault_execution = ProductionExecutionComposition(
        gateway=fault_gateway,
        object_store=initial_execution.object_store,
        source_object_reader=initial_execution.source_object_reader,
        runtime_environment=initial_execution.runtime_environment,
        max_cost_per_call=initial_execution.max_cost_per_call,
        shared_budget_caps=initial_execution.shared_budget_caps,
        chapter_total_budget_cap=initial_execution.chapter_total_budget_cap,
    )
    initial_application = build_chapter_authority_application(
        settings,
        execution=fault_execution,
        env=env,
    )
    initial_runtime = initial_application.embedding_projection_runtime
    if initial_runtime is None:
        raise RuntimeError("production embedding projection runtime is not wired")
    scheduled = initial_runtime.schedule_pending(project_id=project_id)
    if len(scheduled) != 1:
        raise RuntimeError(f"expected one Provider operation, observed {scheduled}")
    provider_operation_id = scheduled[0]
    try:
        initial_runtime.tick(
            project_id=project_id,
            operation_id=provider_operation_id,
        )
    except KernelError as exc:
        if exc.code != "EFFECT_EXTERNAL_STATE_UNKNOWN":
            raise
    else:
        raise RuntimeError("ambiguous Provider response fault did not trigger")
    initial_execution.close()
    with AuthorityUnitOfWork(args.database_url) as uow:
        uow.cursor.execute(
            """
            SELECT external_effect_id FROM authority_external_effect
            WHERE operation_id=%s AND capability='model.retrieval'
            """,
            [provider_operation_id],
        )
        effect_row = uow.cursor.fetchone()
    if effect_row is None:
        raise RuntimeError("response loss left no durable ExternalEffect intent")
    external_effect_id = str(effect_row[0])
    recovered_env = {
        **env,
        "NOVEL_FORGE_AUTHORITY_WORKER_ID": "provider-qualification-worker:recovered",
    }
    recovered_execution = build_production_execution_composition(
        settings, env=recovered_env
    )
    recovered_application = build_chapter_authority_application(
        settings,
        execution=recovered_execution,
        env=recovered_env,
    )
    recovered_runtime = recovered_application.embedding_projection_runtime
    if recovered_runtime is None:
        raise RuntimeError("recovered embedding projection runtime is not wired")
    recovered_tick = recovered_runtime.tick(
        project_id=project_id,
        operation_id=provider_operation_id,
    )
    replay_tick = recovered_runtime.tick(
        project_id=project_id,
        operation_id=provider_operation_id,
    )
    recovered_execution.close()
    if recovered_tick.status != "SUCCEEDED" or not replay_tick.replayed:
        raise RuntimeError("Provider recovery/replay did not converge")
    (
        effect,
        provider_evidence,
        dispatch_count,
        receipt_count,
        recon_count,
        reconciliation,
    ) = _effect_evidence(
        args.database_url,
        operation_id=provider_operation_id,
    )
    if dispatch_count != 1 or receipt_count != 1 or recon_count != 1:
        raise RuntimeError("Provider recovery created duplicate execution evidence")
    assert_no_inline_secrets(
        provider_evidence, label="real Provider response evidence"
    )
    production = dict(provider_evidence.get("production_execution") or {})
    execution_request = dict(production.get("execution_request") or {})
    execution_handle = dict(production.get("execution_handle") or {})
    execution_result = dict(production.get("execution_result") or {})
    route_snapshot = dict(production.get("route_snapshot") or {})
    capability_runtime = dict(provider_evidence.get("capability_runtime") or {})
    system_instruction = dict(
        capability_runtime.get("system_instruction") or {}
    )
    prompt_template = dict(capability_runtime.get("prompt_template") or {})
    skill = dict(capability_runtime.get("skill") or {})
    provider_request_identity = str(
        execution_handle.get("provider_request_id")
        or execution_handle.get("external_request_id")
        or execution_handle.get("local_execution_receipt_id")
        or ""
    )
    if not provider_request_identity:
        raise RuntimeError("Provider execution has no durable request identity")
    process_evidence = _provider_process_evidence(
        runtime_root,
        execution_id=str(execution_request.get("execution_id") or ""),
    )
    latency = {"duration_ms": _duration_ms(execution_result)}
    request_ref = object_store.put_json(
        object_key=f"d0/{qualification_operation_id}/request.json",
        payload={
            "schema_version": "d0-live-request-evidence.v1",
            "release_sha": commit_sha,
            "implementation_identity": identity["implementation_tree_sha"],
            "external_effect_id": external_effect_id,
            "request_hash": effect["request_hash"],
            "request_payload": effect["request_payload"],
            "route_snapshot": route_snapshot,
        },
    )
    response_ref = object_store.put_json(
        object_key=f"d0/{qualification_operation_id}/response.json",
        payload={
            "schema_version": "d0-live-response-evidence.v1",
            "external_effect_id": external_effect_id,
            "provider_request_identity": provider_request_identity,
            "provider_evidence": provider_evidence,
            "reconciliation": reconciliation,
            "latency": latency,
        },
    )
    live_evidence = D0LiveQualificationEvidence.from_mapping(
        {
            "schema_version": "d0-live-qualification-evidence.v1",
            "release_sha": commit_sha,
            "implementation_identity": identity["implementation_tree_sha"],
            "source_operation_id": provider_operation_id,
            "external_effect_id": external_effect_id,
            "request_object_ref": request_ref,
            "response_object_ref": response_ref,
            "auth_profile_ref": str(route_snapshot["auth_profile_ref"]),
            "provider": str(provider_evidence["provider_id"]),
            "backend_id": str(execution_handle["backend_id"]),
            "model": str(provider_evidence["model_id"]),
            "model_version": env["NOVEL_FORGE_D0_MODEL_VERSION"],
            "route_snapshot_id": str(route_snapshot["route_snapshot_id"]),
            "route_snapshot_hash": request_hash(route_snapshot),
            "prompt_version": str(provider_evidence["prompt_version"]),
            "prompt_hash": str(prompt_template["content_hash"]),
            "instruction_version": (
                str(provider_evidence["prompt_version"]) + ":system"
            ),
            "instruction_hash": str(system_instruction["content_hash"]),
            "skill_version": str(provider_evidence["skill_version"]),
            "skill_hash": str(skill["content_hash"]),
            "request_hash": str(effect["request_hash"]),
            "response_hash": request_hash(provider_evidence),
            "provider_execution_id": str(execution_request["execution_id"]),
            "provider_request_identity": provider_request_identity,
            "usage": dict(provider_evidence["usage"]),
            "cost": dict(provider_evidence["cost"]),
            "latency": latency,
            "controlled_failure": {
                "checkpoint": "after_provider_response_before_effect_receipt",
                "failure_kind": "response_loss",
                "request_sent": True,
            },
            "recovery": {
                "external_state_was_ambiguous": True,
                "recovered_without_resend": True,
                "replayed": bool(replay_tick.replayed),
            },
            "fixture_protocol_only": False,
            "real_model_call": bool(provider_evidence["real_model_call"]),
        }
    )
    decision = qualification_authority.execute_live(command, live_evidence)
    result = _jsonable(
        {
            "schema_version": "novel-forge.real-provider-qualification.v1",
            "created_at": datetime.now().astimezone().isoformat(),
            "release_sha": commit_sha,
            "implementation_identity": identity["implementation_tree_sha"],
            "migration": migration,
            "scope": {
                "project_id": project_id,
                "workspace_id": workspace_id,
                "book_id": book_id,
                "fixture_inputs_are_not_provider_proof": True,
            },
            "provider": live_evidence.provider,
            "backend_id": live_evidence.backend_id,
            "model": live_evidence.model,
            "model_version": live_evidence.model_version,
            "route_snapshot_id": live_evidence.route_snapshot_id,
            "prompt_version": live_evidence.prompt_version,
            "prompt_hash": live_evidence.prompt_hash,
            "instruction_version": live_evidence.instruction_version,
            "instruction_hash": live_evidence.instruction_hash,
            "skill_version": live_evidence.skill_version,
            "skill_hash": live_evidence.skill_hash,
            "qualification": decision,
            "external_effect": {
                "operation_id": provider_operation_id,
                "external_effect_id": external_effect_id,
                "request_hash": live_evidence.request_hash,
                "response_hash": live_evidence.response_hash,
                "provider_execution_id": live_evidence.provider_execution_id,
                "provider_request_identity": (
                    live_evidence.provider_request_identity
                ),
                "dispatch_count": dispatch_count,
                "receipt_count": receipt_count,
                "reconciliation_count": recon_count,
                "provider_execution_count": decision[
                    "provider_execution_count"
                ],
                "duplicate_external_effect_count": decision[
                    "duplicate_external_effect_count"
                ],
                **process_evidence,
                "ambiguous_response_injected": fault_gateway.triggered,
                "initial_outcome": "EFFECT_EXTERNAL_STATE_UNKNOWN",
                "recovery_runtime_restarted": True,
                "recovered_without_resend": True,
                "replayed": replay_tick.replayed,
            },
            "usage": live_evidence.usage,
            "cost": live_evidence.cost,
            "latency": live_evidence.latency,
            "request_object_ref": request_ref,
            "response_object_ref": response_ref,
            "proof_scope": PROOF_SCOPE,
            "result": "PASS",
        }
    )
    assert_no_inline_secrets(result, label="real Provider qualification output")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument(
        "--codex-executable",
        default="/Applications/ChatGPT.app/Contents/Resources/codex",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("NOVEL_FORGE_REAL_PROVIDER_MODEL", "gpt-5.6-sol"),
    )
    parser.add_argument(
        "--reasoning-effort",
        default=os.environ.get(
            "NOVEL_FORGE_REAL_PROVIDER_REASONING_EFFORT", "medium"
        ),
    )
    parser.add_argument("--minio-endpoint", required=True)
    parser.add_argument(
        "--minio-access-key",
        default=os.environ.get("NOVEL_FORGE_MINIO_ACCESS_KEY", "novel_forge"),
    )
    parser.add_argument(
        "--minio-secret-key",
        default=os.environ.get(
            "NOVEL_FORGE_MINIO_SECRET_KEY", "novel_forge_secret"
        ),
    )
    parser.add_argument("--minio-secure", action="store_true")
    args = parser.parse_args()
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = _run(args)
    except BaseException as exc:
        safe_message = redact_secret_text(exc)
        failure = {
            "schema_version": "novel-forge.real-provider-qualification.v1",
            "created_at": datetime.now().astimezone().isoformat(),
            "proof_scope": PROOF_SCOPE,
            "result": "FAIL",
            "failure": {"type": type(exc).__name__, "message": safe_message},
        }
        output.write_text(
            json.dumps(failure, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(failure, ensure_ascii=False), flush=True)
        return 1
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"proof_output": str(output), "proof_scope": result["proof_scope"]},
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
