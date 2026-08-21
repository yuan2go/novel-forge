#!/usr/bin/env python3
"""Run the bounded post-merge real-provider qualification at one exact SHA."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.api.authority_dependencies import (
    build_agent_runtime_authority_application,
    build_chapter_authority_application,
    build_production_execution_composition,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.agent_runtime.application import AgentHarnessAdmissionRequest
from novel_forge.modules.agent_runtime.definitions import (
    agent_runtime_operation_definitions,
)
from novel_forge.modules.agent_runtime.harness import (
    AcceptedBoundaryRef,
    AgentHarnessBudget,
    AutonomousAgentRole,
)
from novel_forge.modules.agent_runtime.production import (
    PostgresAgentExecutionContractBinder,
    build_production_agent_harness_factory,
)
from novel_forge.modules.agent_runtime.policy import SERVER_AGENT_TOOL_CATALOG
from novel_forge.modules.agent_runtime.scheduler import AgentAuthorityScheduler
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.book_authority import (
    PostgresBookAuthority,
    StartBookProductionCommand,
)
from novel_forge.modules.chapter_authority import SingleChapterRequest
from novel_forge.modules.chapter_authority.definitions import (
    chapter_operation_definitions,
    chapter_root_operation_definition,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.migrations import run_migrations
from novel_forge.storage.object_store import MinioObjectStore

from run_real_capability_codex_proof import (
    OneShotProviderSuccessCrash,
    SimulatedWorkerInterruption,
    _collect_evidence,
    _install_pack,
    _jsonable,
    _principal,
    _query_rows,
    _runtime_env,
    _seed_authorities,
)


ROOT = Path(__file__).resolve().parents[1]
AGENT_PACK_PATH = ROOT / "config/capability_packs/agent_session_pack.json"


class _UnusedPort:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"qualification unexpectedly used port method {name}")


def _git(*args: str) -> str:
    return subprocess.run(
        ("git", *args), cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


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
    """Create only the frozen Book boundary needed by the Agent qualification.

    The input versions are explicitly labelled qualification fixtures. They establish
    no human, literary, long-form, or production evidence; the Agent execution path
    itself remains the controlled production runtime.
    """

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
                "evidence_class": "FIXTURE_ONLY_NOT_HUMAN_OR_LONGFORM_PROOF",
            }
            content_hash = _hash(content)
            uow.cursor.execute(
                """
                INSERT INTO authority_asset(asset_id,project_id,asset_type)
                VALUES (%s,%s,%s)
                """,
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
                ) VALUES (%s,%s,'small-provider-qualification-fixture-v1',
                          'ELIGIBLE',%s)
                """,
                [
                    f"qualification:{version_id}",
                    version_id,
                    Jsonb({"fixture_only": True, "human_anchored": False}),
                ],
            )
            versions[key] = [version_id] if key == "arc_plan_versions" else version_id
        uow.commit()
    book = PostgresBookAuthority(
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
            stable_idempotency_key=f"{project_id}:book-qualification-boundary",
            book_design_version=str(versions.pop("book_design_version")),
            book_plan_version=str(versions.pop("book_plan_version")),
            production_profile_version=str(versions["platform_profile_version"]),
            longform_context_versions=versions,
            target_chapter_count=1,
            input_mode="LEGACY_FIXTURE_INPUT_MODE",
        ),
        principal=actor,
    )
    return book


def _register_pack_operation_definitions(
    database_url: str,
    *,
    build_id: str,
    commit_sha: str,
) -> None:
    """Register the canonical definitions resolved by both qualification Packs."""

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
    document_id = f"retrieval-document:{project_id}:accepted-ledger"
    asset_version_id = f"asset-version:{project_id}:accepted-ledger"
    content = {
        "type": "accepted_passage",
        "chapter": 0,
        "text": (
            "A rain-soaked municipal ledger preserves a second ink layer: the "
            "official rescue report reassigned casualties, and a living witness "
            "was recorded among the dead."
        ),
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
    projection_hash = _hash(projection_payload)
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
                Jsonb(
                    {
                        "fixture_only": True,
                        "accepted_input": True,
                        "producer": "small-real-provider-qualification",
                    }
                ),
                projection_hash,
                source_operation_id,
            ],
        )
        uow.commit()
    return document_id, asset_version_id


def _expire_active_lease(database_url: str, operation_id: str) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            UPDATE authority_lease_acquisition
            SET acquired_at=NOW()-INTERVAL '2 seconds',
                heartbeat_at=NOW()-INTERVAL '2 seconds',
                expires_at=NOW()-INTERVAL '1 second'
            WHERE attempt_id=(
                SELECT attempt_id FROM authority_attempt
                WHERE operation_id=%s ORDER BY attempt_number DESC LIMIT 1
            ) AND status='HELD'
            RETURNING attempt_id,fencing_token,owner,expires_at
            """,
            [operation_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise RuntimeError("qualification crash left no held lease to expire")
        uow.commit()
    return {
        "attempt_id": str(row[0]),
        "fencing_token": int(row[1]),
        "owner": str(row[2]),
        "expires_at": row[3].isoformat(),
    }


def _hash(value: Mapping[str, Any]) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


def _one_row(
    database_url: str, sql: str, parameters: tuple[Any, ...]
) -> dict[str, Any]:
    rows = _query_rows(database_url, sql, parameters)
    if len(rows) != 1:
        raise RuntimeError(f"expected one evidence row, observed {len(rows)}")
    return rows[0]


def _model_summary(evidence: Mapping[str, Any]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for item in evidence.get("authority_assets") or ():
        if item.get("asset_type") not in {"model_call_log", "cost_ledger"}:
            continue
        content = dict(item.get("content") or {})
        provider = dict(content.get("provider_evidence") or {})
        production = dict(provider.get("production_execution") or {})
        route = dict(production.get("route_snapshot") or {})
        summaries.append(
            {
                "asset_type": item.get("asset_type"),
                "asset_version_id": item.get("asset_version_id"),
                "operation_id": item.get("operation_id"),
                "stage": content.get("stage"),
                "provider": provider.get("provider_id") or content.get("provider"),
                "model": provider.get("model_id") or content.get("model"),
                "real_model_call": provider.get("real_model_call"),
                "route_snapshot_id": route.get("route_snapshot_id"),
                "input_tokens": content.get("input_tokens"),
                "output_tokens": content.get("output_tokens"),
                "total_tokens": content.get("total_tokens"),
                "cost": content.get("cost") or content.get("amount"),
                "currency": content.get("currency"),
                "pricing_ref": content.get("pricing_ref"),
            }
        )
    return summaries


def _runtime_environment(
    *, args: argparse.Namespace, commit_sha: str, runtime_root: Path
) -> dict[str, str]:
    agent_manifest = json.loads(AGENT_PACK_PATH.read_text(encoding="utf-8"))
    agent_prompt = dict(agent_manifest["prompt_binding"])
    agent_skill = dict(agent_manifest["skill_binding"]["skills"][0])
    env = _runtime_env(
        commit_sha=commit_sha,
        codex_executable=args.codex_executable,
        runtime_root=runtime_root,
        worker_id="qualification-worker:initial",
        model=args.model,
        reasoning_effort=args.reasoning_effort,
    )
    env.update(
        {
            "NOVEL_FORGE_APPLICATION_BUILD_ID": "small-real-provider-qualification",
            "NOVEL_FORGE_AGENT_PROVIDER": "codex-cli",
            "NOVEL_FORGE_AGENT_MODEL": args.model,
            "NOVEL_FORGE_AGENT_REASONING_EFFORT": args.reasoning_effort,
            "NOVEL_FORGE_AGENT_CAPABILITY_PACK_ID": "agent_session_pack",
            "NOVEL_FORGE_AGENT_SESSION_PROMPT_VERSION": (
                f"{agent_prompt['system_instruction_ref']}@"
                f"{agent_prompt['system_instruction_version']}"
            ),
            "NOVEL_FORGE_AGENT_SESSION_SKILL_VERSION": (
                f"{agent_skill['skill_ref']}@{agent_skill['version']}"
            ),
            "NOVEL_FORGE_AGENT_SESSION_SYSTEM_INSTRUCTION_HASH": agent_prompt[
                "system_instruction_hash"
            ],
            "NOVEL_FORGE_AGENT_SESSION_PROMPT_TEMPLATE_HASH": agent_prompt[
                "template_hash"
            ],
            "NOVEL_FORGE_AGENT_SESSION_SKILL_BUNDLE_HASH": agent_skill["content_hash"],
            "NOVEL_FORGE_EMBEDDING_PROVIDER": "codex-cli",
            "NOVEL_FORGE_EMBEDDING_MODEL": args.model,
            "NOVEL_FORGE_NARRATIVE_EVALUATOR_PROVIDER": "codex-cli",
            "NOVEL_FORGE_NARRATIVE_EVALUATOR_MODEL": args.model,
            "NOVEL_FORGE_NARRATIVE_SEMANTIC_EVALUATION_REASONING_EFFORT": (
                args.reasoning_effort
            ),
        }
    )
    return env


def _run(args: argparse.Namespace) -> dict[str, Any]:
    commit_sha = _git("rev-parse", "HEAD")
    branch = _git("branch", "--show-current")
    dirty = _git("status", "--porcelain", "--untracked-files=normal")
    if branch != "codex/post-merge-runtime-hardening":
        raise RuntimeError(f"unexpected qualification branch: {branch}")
    if dirty and not args.allow_dirty:
        raise RuntimeError("exact-SHA qualification requires a clean worktree")
    executable = str(Path(args.codex_executable).expanduser().resolve())
    login = subprocess.run(
        (executable, "login", "status"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    runtime_root = Path(args.runtime_root).expanduser().resolve()
    runtime_root.mkdir(parents=True, exist_ok=False)
    env = _runtime_environment(
        args=args, commit_sha=commit_sha, runtime_root=runtime_root
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
    MinioObjectStore(settings).ensure_buckets()
    suffix = uuid4().hex[:12]
    project_id = f"small-provider:{commit_sha[:8]}:{suffix}"
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
        "agent.authority.execute",
    )
    compiler = _principal(
        f"compiler:{project_id}",
        project_id,
        "capability_pack.authority.register",
        "capability_pack.authority.compile",
        "capability_pack.authority.deploy",
        "capability_pack.authority.activate",
    )
    approver = _principal(
        f"approver:{project_id}",
        project_id,
        "capability_pack.authority.approve",
    )
    agent_admin = _principal(
        f"agent-admin:{project_id}", project_id, "agent.authority.admin"
    )
    inputs, chapter_command = _seed_authorities(
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
    _register_pack_operation_definitions(
        args.database_url, build_id=build_id, commit_sha=commit_sha
    )
    chapter_pack = _install_pack(
        args.database_url,
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        build_id=build_id,
        commit_sha=commit_sha,
        compiler=compiler,
        approver=approver,
        agent_admin=agent_admin,
    )
    agent_pack = _install_pack(
        args.database_url,
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        build_id=build_id,
        commit_sha=commit_sha,
        compiler=compiler,
        approver=approver,
        agent_admin=agent_admin,
        pack_path=AGENT_PACK_PATH,
        agent_skill_ref="agent-loop-governance",
        agent_domain="agent_runtime",
        agent_scope_type="BOOK",
        agent_role="STUDIO_DIRECTOR",
        allowed_tools=(
            "narrative.query_accepted",
            "story_planning.generate_candidate",
            "plan_change.submit",
        ),
        authority_scope_ref="scope:book@1",
        default_scope_policy_ref="scope:book-frozen@1",
    )

    execution = build_production_execution_composition(settings, env=env)
    agent_application = build_agent_runtime_authority_application(
        settings, execution=execution, env=env
    )
    agent_ref = str(
        agent_pack["compilation"]["compiled"]["workflow_nodes"][0][
            "agent_definition_ref"
        ]
    )
    agent_id = agent_ref.rpartition("@")[0]
    admitted_agent = agent_application.admit_harness_session(
        AgentHarnessAdmissionRequest(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            actor_id=operator.principal_id,
            agent_session_id=f"agent-session:{project_id}",
            agent_role=AutonomousAgentRole.STUDIO_DIRECTOR,
            instruction=(
                "This is an already admitted, frozen, read-only qualification session; "
                "the execution contract summary supplied with this turn is sufficient. "
                "Your first action MUST call narrative.query_accepted exactly once, "
                "with an empty JSON object as its arguments. Do not hard-stop or ask "
                "for more contract fields. After receiving the Tool observation, call "
                "no other Tool and return a concise final response confirming only "
                "what the accepted boundary proves."
            ),
            accepted_boundary=AcceptedBoundaryRef(
                book_id=book_id,
                book_run_id=book.book_run_id,
                accepted_through_chapter=0,
                acceptance_id="",
                projection_set_id="",
            ),
            tool_policy=tuple(
                SERVER_AGENT_TOOL_CATALOG[name]
                for name in (
                    "narrative.query_accepted",
                    "story_planning.generate_candidate",
                    "plan_change.submit",
                )
            ),
            skill_bindings=(),
            budget=AgentHarnessBudget(
                max_turns=3,
                max_tool_calls=2,
                max_external_effects=4,
                max_input_tokens=20_000,
                max_output_tokens=4_000,
                max_cost_amount="2.00",
            ),
            idempotency_key=f"{project_id}:agent-session",
            trace_id=f"trace:{project_id}:agent-session",
            correlation_id=f"correlation:{project_id}",
            agent_id=agent_id,
        ),
        principal=operator,
    )
    if args.setup_only:
        return _jsonable(
            {
                "schema_version": (
                    "novel-forge.small-real-provider-qualification-preflight.v1"
                ),
                "release_sha": commit_sha,
                "project_id": project_id,
                "book_run_id": book.book_run_id,
                "agent_session_id": admitted_agent["agent_session_id"],
                "agent_execution_contract_hash": admitted_agent[
                    "execution_contract_hash"
                ],
                "chapter_pack_compilation_hash": chapter_pack["compilation"][
                    "compilation_hash"
                ],
                "agent_pack_compilation_hash": agent_pack["compilation"][
                    "compilation_hash"
                ],
                "configured_routes": sorted(execution.gateway.routes),
                "proof_flags": {
                    "SETUP_PREFLIGHT": True,
                    "PROVIDER_WIRED": True,
                    "PROVIDER_PROVEN": False,
                    "LONGFORM_PROVEN": False,
                    "PRODUCTION_QUALIFIED": False,
                },
            }
        )
    agent_binder = PostgresAgentExecutionContractBinder(
        args.database_url,
        execution.gateway.routes,
        capability_pack_id="agent_session_pack",
        pack_environment="validation",
        pack_runtime_profile="validation",
        pack_release_channel="VALIDATION",
        pack_required=True,
    )
    agent_factory = build_production_agent_harness_factory(
        args.database_url,
        adapter=execution.gateway,
        capability_binder=agent_binder,
        planning=_UnusedPort(),  # type: ignore[arg-type]
        plan_change=_UnusedPort(),  # type: ignore[arg-type]
        principal=operator,
        worker_id="qualification-agent-worker",
        max_cost_per_call=execution.max_cost_per_call,
        budget_caps=execution.budget_caps(),
    )
    agent_tick = AgentAuthorityScheduler(
        args.database_url,
        execution_preparer=_UnusedPort(),  # type: ignore[arg-type]
        worker_id="qualification-agent-worker",
        harness_factory=agent_factory,
    ).tick(
        project_id=project_id,
        agent_run_id=str(admitted_agent["operation_id"]),
    )
    if agent_tick.operation_status != "SUCCEEDED":
        raise RuntimeError(f"real Agent Session ended {agent_tick.operation_status}")

    document_id, document_asset_version_id = _seed_accepted_retrieval_document(
        args.database_url,
        project_id=project_id,
        book_id=book_id,
        source_operation_id=book.root_operation_id,
    )
    crash = OneShotProviderSuccessCrash()
    embedding_env = {**env, "NOVEL_FORGE_AUTHORITY_WORKER_ID": "embedding-worker:crash"}
    embedding_execution = build_production_execution_composition(
        settings, env=embedding_env
    )
    embedding_application = build_chapter_authority_application(
        settings,
        execution=embedding_execution,
        env=embedding_env,
        runtime_fault_injector=crash,
    )
    embedding_runtime = embedding_application.embedding_projection_runtime
    if embedding_runtime is None:
        raise RuntimeError("production embedding projection runtime is not wired")
    scheduled = embedding_runtime.schedule_pending(project_id=project_id)
    if len(scheduled) != 1:
        raise RuntimeError(f"expected one embedding projection, observed {scheduled}")
    embedding_operation_id = scheduled[0]
    try:
        embedding_runtime.tick(
            project_id=project_id, operation_id=embedding_operation_id
        )
    except SimulatedWorkerInterruption:
        pass
    else:
        raise RuntimeError("embedding crash injection did not trigger")
    embedding_application.close()
    expired_lease = _expire_active_lease(args.database_url, embedding_operation_id)
    recovered_env = {
        **env,
        "NOVEL_FORGE_AUTHORITY_WORKER_ID": "embedding-worker:recovered",
    }
    recovered_execution = build_production_execution_composition(
        settings, env=recovered_env
    )
    recovered_application = build_chapter_authority_application(
        settings, execution=recovered_execution, env=recovered_env
    )
    recovered_embedding_runtime = recovered_application.embedding_projection_runtime
    assert recovered_embedding_runtime is not None
    embedding_tick = recovered_embedding_runtime.tick(
        project_id=project_id, operation_id=embedding_operation_id
    )
    embedding_replay = recovered_embedding_runtime.tick(
        project_id=project_id, operation_id=embedding_operation_id
    )
    if embedding_tick.status != "SUCCEEDED" or not embedding_replay.replayed:
        raise RuntimeError("embedding receipt recovery/replay did not converge")
    projection = _one_row(
        args.database_url,
        """
        SELECT embedding_projection_id,status,embedding_model,
               embedding_dimensions,vector_dims(embedding_vector) AS vector_dimensions,
               route_snapshot_id,external_effect_id,receipt_id,operation_id,
               projection_hash
        FROM authority_retrieval_embedding_projection
        WHERE retrieval_document_id=%s
        """,
        (document_id,),
    )
    embedding_dispatch_count = _one_row(
        args.database_url,
        """
        SELECT COUNT(*)::int AS count
        FROM authority_external_effect_dispatch AS dispatch
        JOIN authority_external_effect AS effect
          ON effect.external_effect_id=dispatch.external_effect_id
        WHERE effect.operation_id=%s AND effect.capability='model.retrieval'
        """,
        (embedding_operation_id,),
    )["count"]
    if int(embedding_dispatch_count) != 1:
        raise RuntimeError("embedding recovery dispatched a duplicate Provider effect")

    chapter_request = SingleChapterRequest(
        project_id=chapter_command.project_id,
        workspace_id=chapter_command.workspace_id,
        actor_id=operator.principal_id,
        chapter=chapter_command.chapter,
        title=chapter_command.title,
        premise=chapter_command.premise,
        trace_id=f"trace:{project_id}:chapter:1",
        correlation_id=f"correlation:{project_id}",
        application_build_id=build_id,
        commit_sha=commit_sha,
        chapter_plan_asset_version_id=chapter_command.chapter_plan_asset_version_id,
        chapter_plan_content_hash=chapter_command.chapter_plan_content_hash,
        context_candidates=chapter_command.context_candidates,
        context_version_refs={
            **dict(chapter_command.context_version_refs),
            "semantic_retrieval_policy": "REQUIRED",
        },
        context_token_budget=chapter_command.context_token_budget,
        preparation_report=chapter_command.preparation_report,
        idempotency_key=chapter_command.idempotency_key,
    )
    chapter_admission = recovered_application.admit(chapter_request, principal=operator)
    chapter_worker = Principal(
        principal_id="qualification-chapter-worker",
        principal_type=PrincipalType.WORKER,
        permissions=frozenset({"chapter.authority.execute"}),
        project_scope=frozenset({project_id}),
        authentication_source="small-real-provider-qualification",
    )
    scheduler = recovered_application.scheduler(principal=chapter_worker)
    chapter_ticks: list[dict[str, Any]] = []
    for _ in range(20):
        tick = scheduler.tick(
            project_id=project_id,
            root_operation_id=chapter_admission.root_operation_id,
        )
        chapter_ticks.append(_jsonable(asdict(tick)))
        draft_state = _query_rows(
            args.database_url,
            """
            SELECT operation_id,status FROM authority_operation
            WHERE project_id=%s AND root_operation_id=%s
              AND definition_name='chapter.draft.generate'
            """,
            (project_id, chapter_admission.root_operation_id),
        )
        if draft_state and draft_state[0]["status"] == "SUCCEEDED":
            break
    else:
        raise RuntimeError("one-Chapter qualification did not reach Draft")
    recovered_application.close()

    agent_evidence = _collect_evidence(
        args.database_url,
        project_id=project_id,
        root_operation_id=str(admitted_agent["operation_id"]),
    )
    embedding_evidence = _collect_evidence(
        args.database_url,
        project_id=project_id,
        root_operation_id=embedding_operation_id,
    )
    chapter_evidence = _collect_evidence(
        args.database_url,
        project_id=project_id,
        root_operation_id=chapter_admission.root_operation_id,
    )
    transcript = _query_rows(
        args.database_url,
        """
        SELECT sequence,event_type,payload,payload_hash,created_at
        FROM authority_agent_transcript_event
        WHERE agent_session_id=%s ORDER BY sequence_number
        """,
        (str(admitted_agent["agent_session_id"]),),
    )
    session = _one_row(
        args.database_url,
        """
        SELECT agent_session_id,status,accepted_boundary,tool_policy,skill_bindings,
               execution_contract,execution_contract_hash,budget,usage
        FROM authority_agent_harness_session WHERE agent_session_id=%s
        """,
        (str(admitted_agent["agent_session_id"]),),
    )
    retrieval = _one_row(
        args.database_url,
        """
        SELECT result.asset_version_id,result.content_hash,result.content
        FROM authority_asset AS asset
        JOIN authority_asset_version AS result ON result.asset_id=asset.asset_id
        JOIN authority_operation_output_asset AS output
          ON output.asset_version_id=result.asset_version_id
        JOIN authority_operation AS operation
          ON operation.operation_id=output.operation_id
        WHERE asset.project_id=%s AND asset.asset_type='retrieval_result'
          AND operation.root_operation_id=%s
        """,
        (project_id, chapter_admission.root_operation_id),
    )
    context = _one_row(
        args.database_url,
        """
        SELECT version.asset_version_id,version.content_hash,
               version.content->'context_manifest' AS context_manifest
        FROM authority_asset AS asset
        JOIN authority_asset_version AS version ON version.asset_id=asset.asset_id
        JOIN authority_operation_output_asset AS output
          ON output.asset_version_id=version.asset_version_id
        JOIN authority_operation AS operation
          ON operation.operation_id=output.operation_id
        WHERE asset.project_id=%s AND asset.asset_type='context_bundle'
          AND operation.root_operation_id=%s
        """,
        (project_id, chapter_admission.root_operation_id),
    )
    draft = _one_row(
        args.database_url,
        """
        SELECT version.asset_version_id,version.content_hash,
               output.operation_id,
               version.content->>'retrieval_result_fingerprint'
                 AS retrieval_result_fingerprint,
               version.content->>'context_fingerprint' AS context_fingerprint
        FROM authority_asset AS asset
        JOIN authority_asset_version AS version ON version.asset_id=asset.asset_id
        JOIN authority_operation_output_asset AS output
          ON output.asset_version_id=version.asset_version_id
        JOIN authority_operation AS operation
          ON operation.operation_id=output.operation_id
        WHERE asset.project_id=%s AND asset.asset_type='draft_chapter'
          AND operation.root_operation_id=%s
        """,
        (project_id, chapter_admission.root_operation_id),
    )
    retrieval_content = dict(retrieval["content"] or {})
    semantic = dict(retrieval_content.get("semantic_status") or {})
    selected = list(retrieval_content.get("selected_documents") or ())
    selected_doc = next(
        (item for item in selected if item.get("retrieval_document_id") == document_id),
        None,
    )
    if selected_doc is None or "VECTOR" not in selected_doc.get(
        "candidate_channels", []
    ):
        raise RuntimeError(
            "real semantic VECTOR channel did not select accepted document"
        )
    if semantic.get("degraded") is True:
        raise RuntimeError("semantic REQUIRED qualification degraded silently")
    query_evidence = dict(retrieval_content.get("query_embedding_evidence") or {})
    if query_evidence.get("real_model_call") is not True:
        raise RuntimeError("retrieval query embedding is not real-provider evidence")
    if str(query_evidence.get("model_id") or "") != str(projection["embedding_model"]):
        raise RuntimeError("document/query embedding model identity drifted")
    if int(projection["embedding_dimensions"]) != int(
        semantic.get("query_embedding_dimensions") or 0
    ):
        raise RuntimeError("document/query embedding dimensions drifted")
    future_leak = any(
        int(item.get("accepted_from_chapter") or 0) > 0 for item in selected
    )
    if future_leak:
        raise RuntimeError("RetrievalResult crossed the accepted boundary")

    agent_model = _model_summary(agent_evidence)
    embedding_model = _model_summary(embedding_evidence)
    chapter_models = _model_summary(chapter_evidence)
    all_logs = agent_model + embedding_model + chapter_models
    if not all(
        item.get("real_model_call") is True
        for item in all_logs
        if item["asset_type"] == "model_call_log"
    ):
        raise RuntimeError("qualification contains a non-real model call")
    return _jsonable(
        {
            "schema_version": "novel-forge.small-real-provider-qualification.v1",
            "created_at": datetime.now().astimezone().isoformat(),
            "release_sha": commit_sha,
            "branch": branch,
            "environment": "validation",
            "provider": "codex-cli",
            "model": args.model,
            "reasoning_effort": args.reasoning_effort,
            "provider_login": login,
            "migration": migration,
            "scope": {
                "project_id": project_id,
                "workspace_id": workspace_id,
                "book_id": book_id,
                "book_run_id": book.book_run_id,
                "accepted_boundary": 0,
                "fixture_inputs_are_not_human_or_longform_proof": True,
            },
            "agent_qualification": {
                "passed": True,
                "agent_session_id": admitted_agent["agent_session_id"],
                "operation_id": admitted_agent["operation_id"],
                "attempt_id": agent_tick.attempt_id,
                "status": agent_tick.operation_status,
                "policy_hash": session["execution_contract_hash"],
                "execution_contract": session["execution_contract"],
                "budget": session["budget"],
                "usage": session["usage"],
                "transcript": transcript,
                "model_and_cost_evidence": agent_model,
                "operation_evidence": {
                    "operations": agent_evidence["operations"],
                    "attempts": agent_evidence["attempts"],
                    "external_effects": agent_evidence["external_effects"],
                    "external_receipts": agent_evidence["external_receipts"],
                },
            },
            "embedding_qualification": {
                "passed": True,
                "document_id": document_id,
                "document_asset_version_id": document_asset_version_id,
                "operation_id": embedding_operation_id,
                "projection": projection,
                "provider_success_crash_injected": crash.triggered,
                "expired_lease": expired_lease,
                "receipt_replay": embedding_replay.replayed,
                "provider_dispatch_count": embedding_dispatch_count,
                "model_and_cost_evidence": embedding_model,
                "external_effects": embedding_evidence["external_effects"],
                "external_receipts": embedding_evidence["external_receipts"],
            },
            "chapter_intelligence_qualification": {
                "passed": True,
                "root_operation_id": chapter_admission.root_operation_id,
                "ticks": chapter_ticks,
                "retrieval_result_asset_version_id": retrieval["asset_version_id"],
                "retrieval_result_fingerprint": retrieval_content.get(
                    "result_fingerprint"
                ),
                "candidate_snapshot_id": retrieval_content.get("candidate_snapshot_id"),
                "candidate_snapshot_hash": retrieval_content.get(
                    "candidate_snapshot_hash"
                ),
                "ranking_policy": retrieval_content.get("ranking_policy"),
                "semantic_status": semantic,
                "selected_document": selected_doc,
                "future_leak": future_leak,
                "query_embedding_evidence": query_evidence,
                "context_asset_version_id": context["asset_version_id"],
                "context_fingerprint": dict(context["context_manifest"] or {}).get(
                    "context_fingerprint"
                ),
                "draft": draft,
                "model_and_cost_evidence": chapter_models,
                "operations": chapter_evidence["operations"],
                "external_effects": chapter_evidence["external_effects"],
                "external_receipts": chapter_evidence["external_receipts"],
            },
            "capability_packs": {
                "chapter_pack_compilation_hash": chapter_pack["compilation"][
                    "compilation_hash"
                ],
                "agent_pack_compilation_hash": agent_pack["compilation"][
                    "compilation_hash"
                ],
            },
            "proof_flags": {
                "LOCAL_TESTED": True,
                "POSTGRES_TESTED": True,
                "PROVIDER_WIRED": True,
                "PROVIDER_PROVEN": True,
                "RECOVERY_PROVEN": True,
                "LONGFORM_PROVEN": False,
                "PRODUCTION_QUALIFIED": False,
            },
            "non_claims": {
                "provider_billed_cost": False,
                "codex_cost_is_immutable_pricing_estimate": True,
                "literary_quality": False,
                "human_behavior_calibration": False,
                "ten_chapter_campaign": False,
                "longform_proven": False,
                "production_qualified": False,
            },
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--codex-executable",
        default="/Applications/ChatGPT.app/Contents/Resources/codex",
    )
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--minio-endpoint", default="127.0.0.1:59039")
    parser.add_argument("--minio-access-key", default="novel_forge")
    parser.add_argument("--minio-secret-key", default="novel_forge_secret")
    parser.add_argument("--minio-secure", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--setup-only", action="store_true")
    args = parser.parse_args()
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = _run(args)
    except BaseException as exc:
        failure = {
            "schema_version": "novel-forge.small-real-provider-qualification.v1",
            "created_at": datetime.now().astimezone().isoformat(),
            "proof_flags": {
                "PROVIDER_WIRED": True,
                "PROVIDER_PROVEN": False,
                "LONGFORM_PROVEN": False,
                "PRODUCTION_QUALIFIED": False,
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
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
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
