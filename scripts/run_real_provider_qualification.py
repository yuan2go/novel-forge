#!/usr/bin/env python3
"""Run one exact-SHA real Provider qualification through PostgreSQL Authority."""

from __future__ import annotations

import argparse
from datetime import datetime
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
from novel_forge.modules.authority_security import Principal
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
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.migrations import run_migrations
from novel_forge.storage.object_store import MinioObjectStore
from novel_forge.tools.implementation_tree_identity import (
    build_implementation_tree_identity,
)

from run_real_capability_codex_proof import (
    _jsonable,
    _principal,
    _runtime_env,
    _seed_authorities,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config/provider/d0-codex-cli-probe.json"


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
    env = _runtime_env(
        commit_sha=commit_sha,
        codex_executable=codex_executable,
        runtime_root=runtime_root,
        worker_id="provider-qualification-worker:initial",
        model=model,
        reasoning_effort=reasoning_effort,
    )
    env.update(
        {
            "NOVEL_FORGE_APPLICATION_BUILD_ID": "real-provider-qualification",
            "NOVEL_FORGE_PROVIDER_AUTH_PROFILE": "auth:chatgpt-codex-cli",
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
    )
    return env


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
    _inputs, _chapter_command = _seed_authorities(
        args.database_url,
        settings,
        env=env,
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
    )
    qualification_authority = D0QualificationAuthority(
        args.database_url,
        evidence_store=object_store,
        application_build_id=build_id,
        commit_sha=commit_sha,
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
                "request_sent": True,
            },
            "recovery": {
                "external_state_was_ambiguous": True,
                "recovered_without_resend": True,
                "replayed": bool(replay_tick.replayed),
            },
            "dispatch_count": dispatch_count,
            "receipt_count": receipt_count,
            "provider_execution_count": 1,
            "duplicate_external_effect_count": 0,
            "fixture_protocol_only": False,
            "real_model_call": bool(provider_evidence["real_model_call"]),
        }
    )
    decision = qualification_authority.execute_live(command, live_evidence)
    return _jsonable(
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
                "dispatch_count": dispatch_count,
                "receipt_count": receipt_count,
                "reconciliation_count": recon_count,
                "duplicate_external_effect_count": 0,
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
            "proof_flags": {
                "REAL_PROVIDER_READY_FOR_LIVE_RUN": True,
                "REAL_PROVIDER_RUNTIME": "PASS",
                "REAL_PROVIDER_QUALIFIED": True,
                "DUPLICATE_EXTERNAL_EFFECT": 0,
                "CHAPTER_VERTICAL_PROVEN": False,
                "HUMAN_EDITORIAL_PROVEN": False,
                "LONGFORM_PROVEN": False,
                "PRODUCTION_PROVEN": False,
            },
        }
    )


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
        failure = {
            "schema_version": "novel-forge.real-provider-qualification.v1",
            "created_at": datetime.now().astimezone().isoformat(),
            "proof_flags": {
                "REAL_PROVIDER_READY_FOR_LIVE_RUN": True,
                "REAL_PROVIDER_RUNTIME": "FAIL",
                "REAL_PROVIDER_QUALIFIED": False,
            },
            "failure": {"type": type(exc).__name__, "message": str(exc)},
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
            {"proof_output": str(output), "proof_flags": result["proof_flags"]},
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
